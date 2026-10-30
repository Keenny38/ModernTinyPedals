#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Broadcast Director page (quick/director_backend.py): settings, texts & helpers shared by the page and its parts

Parts of the page (child QObjects of its backend, QML: backend.timing, backend.graphics...) read the page state
through DirectorPart.page.
"""

from __future__ import annotations

import json
import math
import os
import re
import weakref
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QLocale, QObject

from ...formatter import (  # noqa: F401  # class_*: shared by Director parts
    class_alias,
    class_color,
    class_style,
    shorten_driver_name,
)
from ...i18n import current_language, tr
from ...process import championship as champ
from ...process import director as dr
from ...process.driver_history import history as driver_history
from ...process.game_info import Standing
from ...process.results_text import gap_seconds_text, laps_behind_text, laptime_text, signed_text
from ...setting import cfg
from ...template.setting_compounds import compound_letter
from ...template.setting_status_colors import SAME_TIME
from ...userfile import atomic_write
from . import page_settings

if TYPE_CHECKING:
    from .director_backend import DirectorBackend

POLL_MS = 1000  # game asked again (session or replay)
IDLE_POLL_MS = 5000  # game in menus or not answering
HIDDEN_POLL_MS = 5000  # page hidden, nothing needs fresh answers (see needs_fresh): game asked this often
# Game answering without session while one is shown: session left only after so many answers in a row, or two
# answers this many seconds apart (one missed answer, game busy loading, keeps the desk: greyed, banner)
LOST_ANSWERS = 3
LOST_SECONDS = 2.0
SHARED_MAX_AGE = POLL_MS / 2000  # seconds an answer read by connector or another page is used instead of asking
SETTINGS_FILE = "broadcast_director.json"
MODES = ("manual", "assist", "auto")
FEED_FILTERS = ("all", "incidents", "positions", "pits")
FEED_KINDS = {
    "incidents": frozenset((dr.CONTACT, dr.WALL, dr.STOPPED, dr.SLOW, dr.YELLOW, dr.FCY, dr.GREEN, dr.RETIRED,
                            dr.PENALTY)),
    "positions": frozenset((dr.OVERTAKE, dr.LEAD, dr.BATTLE, dr.FASTEST, dr.FINISH, dr.WINNER)),
    "pits": frozenset((dr.PIT_IN, dr.PIT_OUT)),
}
INCIDENT_KINDS = frozenset((dr.CONTACT, dr.WALL, dr.STOPPED, dr.SLOW, dr.YELLOW, dr.RETIRED, dr.PENALTY))
SUGGESTIONS = 6
POST_ROLL = 5  # instant replay: seconds shown after the event before going back to live
INSTANT_LIMIT = 90.0  # seconds: instant replay ends anyway (game not answering)
CLOSE_GAP, NEAR_GAP = 0.3, 0.5  # seconds: battle gap colored red, amber
WEATHER_RESOURCE = "/rest/sessions/weather"
WEATHER_EVERY = 60  # answers: forecast asked again (changes slowly)
FORECAST_NODES = (("START", "Start"), ("NODE_25", "25%"), ("NODE_50", "50%"), ("NODE_75", "75%"),
                  ("FINISH", "Finish"))
LOG_FOLDER = "broadcast_logs"  # events written as they happen (config folder)
LOCAL_HOSTS = ("", "localhost", "127.0.0.1", "::1")
SAVE_DELAY_MS = 500  # page settings written once changes pause (number arrows held)
PUBLISH_DELAY_MS = 100  # same graphics setting changed again this soon: graphics sent at most this often
LOG_FLUSH_SECONDS = 5.0  # events log lines waited for (page closing, log read)
COMMENTARY_TABS = ("events", "battles", "classes", "pits")  # commentator screen tabs (lists made when shown)
# Broadcast graphics (stream overlay server source /director), page settings "graphics"
GRAPHICS_DEFAULTS: dict[str, Any] = {
    "tower": True, "towerMode": "class", "towerRows": 12, "towerCycle": 10,
    "towerLaps": True, "towerTyres": True, "towerPenalties": True, "towerFastest": True, "towerStops": False,
    "towerGap": "interval", "towerGroup": False,
    "card": True, "cardSeconds": 8, "cardPicture": True,
    "battle": True, "train": True, "banners": True, "bannerSeconds": 6, "replay": True, "replayGraphics": True,
    "clock": True, "hidden": False, "pitRadar": True, "pitRadarRange": 150,
    "onboard": False, "onboardStyle": "dash", "quali": True, "map": False, "mapRotation": 0, "mapDots": 100,
    "gridSeconds": 8, "pageSeconds": 10, "resultsRows": 10,
    "autoGrid": True, "autoEvent": False, "autoResults": True,
    "opacity": 92, "temperatureUnit": "app",
    "accent": "#e5383b", "brandName": "", "logo": False, "sponsors": False, "sponsorSeconds": 8,
}
GRAPHICS_LIMITS = {  # number settings: lowest, highest
    "towerRows": (3, 70), "towerCycle": (3, 60), "cardSeconds": (0, 60), "bannerSeconds": (2, 30),
    "pitRadarRange": (30, 400), "gridSeconds": (3, 60), "pageSeconds": (3, 60), "resultsRows": (5, 20),
    "opacity": (30, 100), "mapDots": (50, 200), "sponsorSeconds": (3, 60),
}
TOWER_MODES = ("all", "class", "air")  # overall, each class in turn, class of the car on air
ONBOARD_STYLES = ("dash", "cockpit", "helmet")
TEMPERATURE_UNITS = ("app", "celsius", "fahrenheit")  # app: unit of app settings
GRAPHICS_CHOICES: dict[str, tuple] = {
    "towerMode": TOWER_MODES, "onboardStyle": ONBOARD_STYLES, "temperatureUnit": TEMPERATURE_UNITS,
    "towerGap": ("interval", "leader"), "mapRotation": (0, 90, 180, 270),
}
ACCENT = re.compile(r"^#[0-9a-fA-F]{6}$")
BRAND_NAME_LENGTH = 60
AUTO_EVENT_SECONDS = 20  # event card shown this long at the start of a session (automatic)
MESSAGE_LENGTH = 160
COUNTDOWN_LIMIT = 24 * 3600  # seconds
BANNER_PRIORITY = {dr.PENALTY: 5, dr.FCY: 5, dr.GREEN: 4, dr.WINNER: 5, dr.LEAD: 4, dr.RETIRED: 3, dr.STOPPED: 3,
                   dr.CONTACT: 3, dr.WALL: 3, dr.FASTEST: 2, dr.YELLOW: 2, dr.SLOW: 1}
HISTORY_EVERY = 300  # answers: race results files read again (new races)
ON_DEMAND = ("grid", "event", "results", "champ")  # graphics shown by the operator, one at a time
LIVE_MS = 100  # onboard & track map positions sent again (sources ease & glide between them)
TRAIN_MIN, TRAIN_MAX = 3, 6  # cars of a battle train
TRACKMAP_RESOURCE = "/rest/watch/trackmap"
HUD_RESOURCE = "/rest/hud"  # HUD parts of the game shown (chat, mfd, speedo, timing, trackMap)
GAME_UI_DELAY_MS = 700  # middle click done: HUD parts asked again (the game shows or hides them too)
CHAMPIONSHIP_FILE = "broadcast_championships.json"
# Timing table: columns (key, title, width in em, alignment), views & their columns by default
TIMING_COLUMNS: dict[str, tuple[str, float, str]] = {
    "pos": ("Pos", 2.4, "right"), "classPos": ("Class", 2.8, "right"), "change": ("+/-", 2.6, "center"),
    "number": ("#", 2.8, "left"), "driver": ("Driver", 10.0, "left"), "team": ("Team", 9.0, "left"),
    "laps": ("Laps", 3.0, "right"), "interval": ("Interval", 4.6, "right"), "gap": ("Gap", 4.8, "right"),
    "best": ("Best", 5.4, "right"), "last": ("Last", 5.4, "right"), "s1": ("S1", 4.2, "right"),
    "s2": ("S2", 4.2, "right"), "s3": ("S3", 4.2, "right"), "pits": ("Pit Stops", 3.4, "right"),
    "stint": ("Stint", 3.2, "right"), "pitTime": ("Pit Lane", 6.0, "right"), "energy": ("Energy", 5.0, "left"),
    "tyres": ("Tyres", 3.4, "center"), "penalties": ("Pen", 2.8, "center"), "status": ("Status", 6.5, "left"),
}
TIMING_VIEWS: dict[str, tuple[str, ...]] = {
    "race": ("pos", "classPos", "change", "number", "driver", "laps", "interval", "gap", "best", "last", "pits",
             "energy", "tyres", "penalties"),
    "qualifying": ("classPos", "number", "driver", "team", "best", "gap", "s1", "s2", "s3", "last", "laps", "tyres"),
    "pits": ("classPos", "number", "driver", "pits", "stint", "pitTime", "status", "energy", "tyres"),
}
TIMING_ROLES = ("key", "slot", "classColor", "onAir", "battle", "trend", "yellow", "energyLevel", "tyreList",
                "intervalTone", "gapTone", "bestTone", "lastTone", "s1Tone", "s2Tone", "s3Tone", "changeValue",
                "statusTone", *TIMING_COLUMNS)
BANNER_KINDS = frozenset((dr.FASTEST, dr.PENALTY, dr.FCY, dr.GREEN, dr.LEAD, dr.YELLOW, dr.WINNER, dr.RETIRED,
                          dr.STOPPED, dr.SLOW))
STORY_KINDS = frozenset((dr.BATTLE, dr.OVERTAKE, dr.LEAD, dr.CONTACT, dr.WALL, dr.STOPPED, dr.SLOW, dr.PIT_IN,
                         dr.PIT_OUT, dr.FASTEST, dr.FINISH, dr.WINNER, dr.RETIRED, dr.PENALTY, dr.YELLOW,
                         dr.START))  # stories told on the driver card
BANNERS_KEPT = 8
RECENT = 90.0  # seconds of session time: events still looked at by the director
FOCUS_GRACE = 3.0  # seconds after a cut: game may still tell the car shown before
SECONDS_BEFORE = 5  # replay: event shown from this long before
NEAR = 200.0  # meters: interval from current speed below, from lap time above
GAME_FOCUS = "game"  # shot kind: car chosen in game (or another app)
SESSION_TEXTS = {"PRACTICE": "Practice", "QUALIFY": "Qualify", "WARMUP": "Warmup", "RACE": "Race"}
# Game state: no answer, game in menus, in a session, replay open
OFFLINE, MENU, SESSION, REPLAY = "offline", "menu", "session", "replay"
STATE_TEXTS = {
    OFFLINE: "Game not answering: LMU not running, or Rest API access disabled",
    MENU: "LMU running, not in a session",
    SESSION: "Live session",
    REPLAY: "Replay open in game",
}
KIND_TEXTS = {
    dr.BATTLE: "Battle", dr.OVERTAKE: "Overtake", dr.LEAD: "Lead Change", dr.CONTACT: "Contact",
    dr.WALL: "Wall Contact", dr.STOPPED: "Stopped Car", dr.PIT_IN: "Pit Entry", dr.PIT_OUT: "Pit Exit",
    dr.FASTEST: "Fastest Lap", dr.FINISH: "Finish", dr.WINNER: "Win", dr.RETIRED: "Retired",
    dr.PENALTY: "Penalty", dr.ROAM: "Around the Track", dr.MANUAL: "Operator Cut",
    GAME_FOCUS: "Chosen in Game", dr.SLOW: "Slow Car", dr.YELLOW: "Yellow Flag", dr.FCY: "Full Course Yellow",
    dr.GREEN: "Green Flag", dr.START: "Race Start",
}
KIND_GLYPHS = {  # Segoe Fluent Icons / MDL2 Assets
    dr.BATTLE: "\ue9d9",  # pulse
    dr.OVERTAKE: "\ue72a",  # arrow
    dr.LEAD: "\ue7c1",  # flag
    dr.CONTACT: "\ue945",  # lightning
    dr.WALL: "\ue7ba",  # warning
    dr.STOPPED: "\ue71a",  # stop
    dr.PIT_IN: "\ue804",  # car
    dr.PIT_OUT: "\ue804",
    dr.FASTEST: "\ue916",  # stopwatch
    dr.FINISH: "\ue7c1",
    dr.WINNER: "\ue735",  # star
    dr.RETIRED: "\ue71a",
    dr.PENALTY: "\ue8c9",  # important
    dr.ROAM: "\ue714",  # video
    dr.MANUAL: "\ue722",  # camera
    GAME_FOCUS: "\ue7f4",  # monitor
    dr.SLOW: "\uec48",  # speed gauge low
    dr.YELLOW: "\ue7c1",  # flag
    dr.FCY: "\ue7c1",
    dr.GREEN: "\ue7c1",
    dr.START: "\ue768",  # play
}
KIND_TONES = {
    dr.CONTACT: "loss", dr.WALL: "loss", dr.STOPPED: "loss", dr.RETIRED: "loss", dr.PENALTY: "warning",
    dr.OVERTAKE: "gain", dr.LEAD: "gain", dr.WINNER: "gain", dr.FINISH: "gain", dr.FASTEST: "fastest",
    dr.BATTLE: "accent", dr.PIT_IN: "warning", dr.PIT_OUT: "warning", dr.ROAM: "dim", dr.MANUAL: "accent",
    GAME_FOCUS: "dim", dr.SLOW: "loss", dr.YELLOW: "yellow", dr.FCY: "yellow", dr.GREEN: "gain", dr.START: "gain",
}
CAMERA_STYLE_TEXTS = ("Mixed", "Trackside", "Onboard", "Keep Camera")
CAR_ROLES = (
    "key", "slot", "position", "classPosition", "number", "driver", "team", "carClass", "classColor", "classAlias",
    "interval", "laps", "best", "last", "fastest", "pits", "status", "statusTone", "onAir", "battle",
    "incidents", "selected", "intervalTone", "gained", "s1Tone", "s2Tone", "s3Tone", "sectorTip", "brandLogo",
    "tyreFront", "tyreRear",
)
FEED_ROLES = ("key", "timeText", "kind", "kindText", "glyph", "tone", "title", "detail", "live", "classColor",
              "unseen", "canReplay")
SUGGESTION_ROLES = ("key", "slot", "kind", "kindText", "glyph", "tone", "title", "detail", "number",
                    "classColor", "score", "best", "hotkey")
# Hotkeys of the director (keyboard shortcut settings): key text shown in tooltips & the keys sheet
DIRECTOR_HOTKEYS = ("director_toggle", "director_next_car", "director_previous_car", "director_auto",
                    "director_take_best", "director_lock", "director_starting_grid", "director_event_card",
                    "director_classification", "director_championship", "director_hide_graphics",
                    "director_next_layout")
BATTLE_ROLES = ("key", "behindSlot", "carClass", "classColor", "position", "ahead", "behind", "gap", "trend",
                "duration", "onAir", "gapTone", "trendText")
CLASS_ROLES = ("key", "name", "classColor", "count", "leader", "leaderNumber", "bestLap", "bestDriver", "battles")
PIT_ROLES = ("key", "slot", "number", "driver", "classColor", "stops", "lastStop", "stint", "inPit", "status")
LAP_ROLES = ("key", "lap", "time", "s1", "s2", "s3", "timeTone", "s1Tone", "s2Tone", "s3Tone", "pit", "energy",
             "position")
RADAR_ROLES = ("key", "number", "name", "color", "distance", "alongside", "ahead")
TIMING_COLUMN_ROLES = ("key", "title", "size", "align")
# Car sheet: what changes at (nearly) every answer, bound apart from the rest (driver, pictures, note, history)
SHEET_LIVE = ("tyres", "position", "classPosition", "ahead", "intervalAhead", "behind", "intervalBehind", "best",
              "last", "laps", "pits", "stint", "incidents", "penalties", "status", "statusTone", "onAir", "gained",
              "sectors", "energy", "lapCount")


@lru_cache(maxsize=8)
def decimal_point(code: str) -> str:
    return QLocale(code).decimalPoint() or "."


def localized(text: str) -> str:
    """Number text with decimal separator of app language"""
    point = decimal_point(current_language())
    return text if point == "." else text.replace(".", point)


def lap_text(seconds: float) -> str:
    """Lap time m:ss.sss, missing text if none"""
    return laptime_text(seconds)


def clock_text(seconds: float) -> str:
    """Session time h:mm:ss"""
    total = max(int(seconds), 0)
    return f"{total // 3600}:{total // 60 % 60:02d}:{total % 60:02d}"


def seconds_text(seconds: float, decimals: int = 1) -> str:
    return f"{localized(f'{seconds:.{decimals}f}')} s"


def interval(ahead: Standing, car: Standing, track_length: float) -> tuple[float, int]:
    """Time (seconds) car needs to reach where car ahead is, & whole laps between them: (-1, laps) when a lap
    or more behind, (-1, 0) if unknown"""
    if track_length <= 0:
        if ahead.laps_behind != car.laps_behind:
            return -1.0, max(car.laps_behind - ahead.laps_behind, 0)
        return (car.gap - ahead.gap, 0) if car.gap > 0 else (-1.0, 0)
    distance = (ahead.laps - car.laps) * track_length + ahead.distance - car.distance
    if distance < 0:
        return -1.0, 0
    if distance >= track_length:
        return -1.0, int(distance // track_length)
    if distance < NEAR:
        return distance / max(car.speed, dr.MIN_SPEED), 0
    lap_time = next((value for value in (car.last, car.best, car.estimated) if value > 0), 0.0)
    return (distance / track_length * lap_time if lap_time > 0 else -1.0), 0


def interval_text(ahead: Standing | None, car: Standing, track_length: float) -> str:
    """Interval to car ahead: "+0.6", "+1 lap", "" for class leader or unknown"""
    if ahead is None:
        return ""
    seconds, laps = interval(ahead, car, track_length)
    if laps > 0:
        return laps_behind_text(laps)
    return gap_seconds_text(seconds, 1) if seconds >= 0 else ""


def status_text(car: Standing) -> tuple[str, str]:
    """Status of car & its tone, ("", "") on track"""
    if car.finish == "FSTAT_DQ":
        return tr("Disqualified"), "loss"
    if car.finish == "FSTAT_DNF":
        return tr("Retired"), "loss"
    if car.finish == "FSTAT_FINISHED":
        return tr("Finished"), "gain"
    if car.garage:
        return tr("Garage"), "dim"
    if car.in_pit:
        return tr("In Pits"), "warning"
    return "", ""


@lru_cache(maxsize=1024)
def fold(text: str) -> str:
    """Search text: no case, no accents (same names folded at every answer)"""
    from ..module_view import sort_key

    return sort_key(text)


def gap_tone(seconds: float) -> str:
    """Color of a gap between two cars of a class: red under 0.3 s, amber under 0.5 s"""
    if 0 <= seconds < CLOSE_GAP:
        return "loss"
    if 0 <= seconds < NEAR_GAP:
        return "warning"
    return ""


def sector_tone(value: float, personal: float, class_best: float) -> str:
    """Sector or lap time color: purple best of class, green personal best, yellow slower, "" unknown"""
    if value <= 0:
        return ""
    if class_best > 0 and value <= class_best + SAME_TIME:
        return "fastest"
    if personal > 0 and value <= personal + SAME_TIME:
        return "gain"
    return "yellow"


def temperature_text(celsius: float, unit: str = "app") -> str:
    """Temperature in user unit (or celsius, fahrenheit), "" if unknown"""
    if celsius <= -999:
        return ""
    if unit == "fahrenheit" or (unit not in TEMPERATURE_UNITS[1:] and cfg.units.get("temperature_unit") == "Fahrenheit"):
        return f"{round(celsius * 1.8 + 32)}°F"
    return f"{round(celsius)}°C"


def parse_forecast(answer: Any, session: str) -> list[dict]:
    """Forecast of session (weather of game: start, 25 %, 50 %, 75 %, finish): label, rain chance, temperature,
    sky (text of game)"""
    if not isinstance(answer, dict):
        return []
    name = next((key for key in answer if session.upper().startswith(str(key).upper())), "")
    nodes = answer.get(name)
    if not isinstance(nodes, dict):
        return []
    result = []
    for node, label in FORECAST_NODES:
        values = nodes.get(node)
        if not isinstance(values, dict):
            continue

        rain, temperature = (entry.get("currentValue") if isinstance(entry := values.get(key), dict) else None
                             for key in ("WNV_RAIN_CHANCE", "WNV_TEMPERATURE"))
        sky = values.get("WNV_SKY")
        result.append({
            "label": label,
            "rain": f"{round(rain)}%" if isinstance(rain, (int, float)) else "",
            "temperature": temperature_text(float(temperature)) if isinstance(temperature, (int, float)) else "",
            "celsius": float(temperature) if isinstance(temperature, (int, float)) else -1000.0,
            "sky": str(sky.get("stringValue") or "") if isinstance(sky, dict) else "",
            "wet": isinstance(rain, (int, float)) and rain >= 40,
        })
    return result


def tyre_letter(name: str) -> str:
    """Badge letter of tyre compound, as overlays: S, M, H, Q (supersoft), I, W (first letter of other names)"""
    return compound_letter(name)


def read_tyres(reader: Any) -> dict[int, tuple[str, str]]:
    """Front & rear tyre compound of every car (slot) from shared memory of the game on this computer,
    empty if not readable"""
    tyres: dict[int, tuple[str, str]] = {}
    try:
        for index in range(reader.vehicle.total_vehicles()):
            names = reader.tyre.compound_name(index)
            tyres[reader.vehicle.slot_id(index)] = (tyre_letter(names[0]), tyre_letter(names[2]))
    except (AttributeError, IndexError, TypeError, ValueError):
        return {}
    return tyres


def short_name(driver: str) -> str:
    """Name for graphics: "Lena Hartmann" -> "L. Hartmann", online tags dropped (same as overlays)"""
    return shorten_driver_name(driver)


def graphics_setting(data: Any) -> dict[str, Any]:
    """Graphics settings kept, unknown or wrong values back to default"""
    result = dict(GRAPHICS_DEFAULTS)
    if isinstance(data, dict):
        for key, default in GRAPHICS_DEFAULTS.items():
            value = data.get(key)
            if type(value) is type(default) and (key not in GRAPHICS_CHOICES or value in GRAPHICS_CHOICES[key]):
                if key in GRAPHICS_LIMITS and isinstance(value, int):
                    low, high = GRAPHICS_LIMITS[key]
                    value = min(max(value, low), high)
                if key == "accent" and not ACCENT.match(str(value)):
                    continue
                if key == "brandName":
                    value = str(value)[:BRAND_NAME_LENGTH]
                result[key] = value
    return result


def timing_setting(data: Any) -> dict[str, list[str]]:
    """Columns of each timing view kept (known ones, once each), views without columns back to default"""
    result = {view: list(columns) for view, columns in TIMING_VIEWS.items()}
    if isinstance(data, dict):
        for view in TIMING_VIEWS:
            columns = data.get(view)
            if isinstance(columns, list):
                kept = list(dict.fromkeys(str(key) for key in columns if key in TIMING_COLUMNS))
                if kept:
                    result[view] = kept
    return result


def championship_path() -> str:
    return os.path.join(cfg.path.config, CHAMPIONSHIP_FILE)


def load_championships() -> list[dict[str, Any]]:
    """Championships imported (name & rows), kept between sessions"""
    try:
        with open(championship_path(), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError, RecursionError):  # RecursionError: nested too deeply
        return []
    result = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("rows"), list):
            continue
        rows = []
        for row in item["rows"]:
            try:
                points = float(row[1])
                if not math.isfinite(points):  # NaN & Infinity accepted by json: never shown
                    continue
                rows.append(champ.ChampionshipRow(str(row[0]), points, str(row[2]), str(row[3]), str(row[4])))
            except (IndexError, TypeError, ValueError):
                continue
        if rows:
            result.append({"name": str(item.get("name") or "Championship"), "rows": rows})
    return result


def save_championships(items: list[dict[str, Any]]) -> None:
    """Championships written, OSError if the file could not be written (caller tells the user)"""
    with atomic_write(championship_path(), raise_error=True) as file:
        file.write(json.dumps([{"name": item["name"], "rows": [list(row) for row in item["rows"]]} for item in items],
                              indent=1, ensure_ascii=False))


def speed_value(speed: float) -> tuple[float, str]:
    """Speed (m/s) in user unit & unit name"""
    from ... import units

    unit = cfg.units.get("speed_unit", "KPH")
    if unit == "MPH":
        return units.mps_to_mph(speed), "mph"
    if unit == "KPH":
        return units.mps_to_kph(speed), "km/h"
    return speed, "m/s"


def delta_text(seconds: float) -> str:
    """Gap "+0,345", "-0,345" (typeset minus sign, decimal separator of app language)"""
    return signed_text(seconds, 3)


def safe_name(text: str) -> str:
    return "".join(char if char.isalnum() or char in " -_" else "_" for char in text).strip() or "session"


def car_label(car: Standing | None, driver: str = "") -> str:
    """#7 Driver Name"""
    if car is None:
        return driver
    return f"#{car.number} {car.driver}" if car.number else car.driver



def load_page_settings() -> dict[str, Any]:
    """Page settings (changes of an open page written first)"""
    return page_settings.load_settings(SETTINGS_FILE)


def read_qualifying_times(track: str) -> dict[str, float]:
    """Best lap of each driver in the latest qualifying results file of a track (folded name), worker thread"""
    from ...stream_overlay import streamoverlay

    try:
        result = streamoverlay.results.latest("qualifying")
    except (OSError, ValueError):
        return {}
    if result is None or not track or not (track in fold(result.track) or fold(result.track) in track):
        return {}
    return {entry.name: entry.best_lap for entry in result.entries if entry.best_lap > 0}


def scan_history() -> bool:
    """Race results files read again (drivers history), True if anything changed (worker thread)"""
    from ...process.driver_history import results_folders

    return driver_history.scan(results_folders())


def number_setting(data: dict, name: str, default: float, low: float, high: float) -> float:
    value = data.get(name, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return min(max(float(value), low), high)


class DirectorPart(QObject):
    """Part of the Broadcast Director page (child QObject of its backend, QML: backend.<part>): page state read
    through page (weak: no reference cycle, a page without parent is freed on the UI thread). Jobs, page settings
    file & release stay with the page (PageBackend), which calls its parts"""

    def __init__(self, page: DirectorBackend):
        super().__init__(page)
        self._page = weakref.ref(page)

    @property
    def page(self) -> DirectorBackend:
        page = self._page()
        if page is None:  # parts are children of the page: deleted with it
            raise RuntimeError("Broadcast Director page deleted")
        return page
