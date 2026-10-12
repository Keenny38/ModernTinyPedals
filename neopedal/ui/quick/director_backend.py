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
Broadcast Director page state (LMU, qml/BroadcastDirector.qml): camera desk, director & commentator screen

The game is asked about once a second while the page is open (shown or not: the director keeps cutting while
another page is looked at): standings, contacts, camera & car followed, session time. Race events & battles
come from process/director.RaceWatcher, shots from process/director.Director. Modes: manual (operator cuts
only), assisted (stories worth showing listed, taken in one click), automatic (director cuts by itself,
an operator cut holds it a while). Live session (driving or spectating) and replays alike.

Broadcast graphics (stream_director): state published about once a second, onboard & car positions of the track
map ten times a second (local game: shared memory) while a graphics source asks. On demand graphics (starting
grid, event card, classification captured, championship standings) shown one at a time by the operator.
Timing table (separate panel): race, qualifying & pits views, columns ordered & chosen per view.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import threading
import time
import weakref
from functools import lru_cache
from itertools import pairwise
from typing import Any

from PySide6.QtCore import Property, QLocale, QObject, QTimer, Signal, Slot

from ... import app_signal
from ... import calculation as calc
from ...formatter import random_color_class
from ...i18n import current_language, tr
from ...process import championship as champ
from ...process import director as dr
from ...process.driver_history import history as driver_history
from ...process.game_info import (
    IMMOVABLE,
    Contact,
    SessionState,
    Standing,
    merge_contacts,
    parse_camera,
    parse_contacts,
    parse_focus,
    parse_session_end,
    parse_session_state,
    parse_session_time,
    parse_standings,
    standings_time,
)
from ...rank_info import ranks
from ...setting import cfg
from ...userfile import atomic_write
from .. import game_rest
from ..game_rest import GameConnection, GameRequest
from . import game_camera as gc
from .game_pictures import LogoCache, car_picture_url, notifier
from .models import DictListModel

logger = logging.getLogger(__name__)

POLL_MS = 1000  # game asked again (session or replay)
IDLE_POLL_MS = 5000  # game in menus or not answering
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
    "towerRows": (3, 30), "towerCycle": (3, 60), "cardSeconds": (0, 60), "bannerSeconds": (2, 30),
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
CHAMPIONSHIP_FILE = "broadcast_championships.json"
# Timing table: columns (key, title, width in em, alignment), views & their columns by default
TIMING_COLUMNS: dict[str, tuple[str, float, str]] = {
    "pos": ("Pos", 2.4, "right"), "classPos": ("Class", 2.8, "right"), "change": ("+/-", 2.6, "center"),
    "number": ("#", 2.8, "left"), "driver": ("Driver", 10.0, "left"), "team": ("Team", 9.0, "left"),
    "laps": ("Laps", 3.0, "right"), "interval": ("Interval", 4.6, "right"), "gap": ("Gap", 4.8, "right"),
    "best": ("Best", 5.4, "right"), "last": ("Last", 5.4, "right"), "s1": ("S1", 4.2, "right"),
    "s2": ("S2", 4.2, "right"), "s3": ("S3", 4.2, "right"), "pits": ("Pit Stops", 3.4, "right"),
    "stint": ("Stint", 3.2, "right"), "pitTime": ("Pit lane", 6.0, "right"), "energy": ("Energy", 5.0, "left"),
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
    "key", "slot", "position", "classPosition", "number", "driver", "team", "carClass", "classColor",
    "interval", "laps", "best", "last", "fastest", "pits", "status", "statusTone", "onAir", "battle",
    "incidents", "selected", "intervalTone", "gained", "s1Tone", "s2Tone", "s3Tone", "sectorTip", "brandLogo",
    "tyreFront", "tyreRear",
)
FEED_ROLES = ("key", "timeText", "kind", "kindText", "glyph", "tone", "title", "detail", "live", "classColor",
              "unseen", "canReplay")
SUGGESTION_ROLES = ("key", "slot", "kind", "kindText", "glyph", "tone", "title", "detail", "number",
                    "classColor", "score", "best")
BATTLE_ROLES = ("key", "behindSlot", "carClass", "classColor", "position", "ahead", "behind", "gap", "trend",
                "duration", "onAir", "gapTone", "trendText")
CLASS_ROLES = ("key", "name", "classColor", "count", "leader", "leaderNumber", "bestLap", "bestDriver", "battles")
PIT_ROLES = ("key", "slot", "number", "driver", "classColor", "stops", "lastStop", "stint", "inPit", "status")
LAP_ROLES = ("key", "lap", "time", "s1", "s2", "s3", "timeTone", "s1Tone", "s2Tone", "s3Tone", "pit", "energy",
             "position")

_active: weakref.ReferenceType | None = None  # director of open page (hotkeys)


def active_director() -> DirectorBackend | None:
    """Director of the Broadcast Director page if open"""
    return _active() if _active is not None else None


def class_color(car_class: str) -> str:
    """Color of vehicle class (vehicle class editor), made from name if not set"""
    style = cfg.user.classes.get(car_class)
    return str(style["color"]) if isinstance(style, dict) and "color" in style else random_color_class(car_class)


@lru_cache(maxsize=8)
def decimal_point(code: str) -> str:
    return QLocale(code).decimalPoint() or "."


def localized(text: str) -> str:
    """Number text with decimal separator of app language"""
    point = decimal_point(current_language())
    return text if point == "." else text.replace(".", point)


def lap_text(seconds: float) -> str:
    """Lap time m:ss.sss, "-" if none"""
    return calc.sec2laptime_full(seconds) if seconds > 0 else "-"


def clock_text(seconds: float) -> str:
    """Session time h:mm:ss"""
    total = max(int(seconds), 0)
    return f"{total // 3600}:{total // 60 % 60:02d}:{total % 60:02d}"


def seconds_text(seconds: float, decimals: int = 1) -> str:
    return f"{localized(f'{seconds:.{decimals}f}')} s"


def lap_count_text(laps: int) -> str:
    return f"+{laps} {tr('Lap') if laps == 1 else tr('Laps')}"


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
    """Interval to car ahead: "+0.6", "+1 Lap", "" for class leader or unknown"""
    if ahead is None:
        return ""
    seconds, laps = interval(ahead, car, track_length)
    if laps > 0:
        return lap_count_text(laps)
    return f"+{localized(f'{seconds:.1f}')}" if seconds >= 0 else ""


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
    if class_best > 0 and value <= class_best + 0.0005:
        return "fastest"
    if personal > 0 and value <= personal + 0.0005:
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
    """Letter of tyre compound: S, M, H, W (first letter of other names)"""
    return name.strip()[:1].upper()


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
    """Name for graphics: "Lena Hartmann" -> "L. Hartmann", online tags dropped ("Tobias Mueller#7949")"""
    name = driver.split("#", 1)[0].strip() or driver
    parts = name.split()
    return f"{parts[0][:1]}. {' '.join(parts[1:])}" if len(parts) > 1 else name


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
    except (OSError, ValueError):
        return []
    result = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("rows"), list):
            continue
        rows = []
        for row in item["rows"]:
            try:
                rows.append(champ.ChampionshipRow(str(row[0]), float(row[1]), str(row[2]), str(row[3]), str(row[4])))
            except (IndexError, TypeError, ValueError):
                continue
        if rows:
            result.append({"name": str(item.get("name") or "Championship"), "rows": rows})
    return result


def save_championships(items: list[dict[str, Any]]):
    with atomic_write(championship_path()) as file:
        json.dump([{"name": item["name"], "rows": [list(row) for row in item["rows"]]} for item in items], file,
                  indent=1, ensure_ascii=False)


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
    return localized(f"{'+' if seconds >= 0 else '-'}{abs(seconds):.3f}")


def safe_name(text: str) -> str:
    return "".join(char if char.isalnum() or char in " -_" else "_" for char in text).strip() or "session"


def car_label(car: Standing | None, driver: str = "") -> str:
    """#7 Driver Name"""
    if car is None:
        return driver
    return f"#{car.number} {car.driver}" if car.number else car.driver


def ask_state(connection: GameConnection, forecast: bool = False, trackmap: bool = False) -> dict[str, Any]:
    """Game state (in background): session, standings, contacts, camera & car followed, weather forecast &
    track outline if asked"""
    active = connection.get(gc.ACTIVE_RESOURCE)
    if active is None:  # not in a session: game running if it answers anything
        connection.get(gc.FOCUS_RESOURCE)
        return {"active": None, "running": connection.answered}
    info = connection.get(gc.SESSION_RESOURCE)
    info = info if isinstance(info, dict) else {}
    standings = parse_standings(connection.get(gc.STANDINGS_RESOURCE))
    length = info.get("lapDistance")
    return {
        "active": active is True, "running": True,
        "standings": standings,
        "contacts": parse_contacts(connection.get(gc.INCIDENTS_RESOURCE), ()),
        "camera": parse_camera(connection.get(gc.CAMERA_RESOURCE)),
        "focus": parse_focus(connection.get(gc.FOCUS_RESOURCE)),
        # Replay: session time of info stays 0, cars tell where the replay is
        "time": standings_time(standings) if active is True else parse_session_time(info),
        "track": str(info.get("trackName") or ""),
        "session": str(info.get("session") or ""),
        "start": info.get("startEventTime") if isinstance(info.get("startEventTime"), (int, float)) else 0,
        "length": float(length) if isinstance(length, (int, float)) and not isinstance(length, bool) and length > 0
        else 0.0,
        "info": parse_session_state(info),
        "end": parse_session_end(info),
        **({"forecast": connection.get(WEATHER_RESOURCE)} if forecast else {}),
        **({"trackmap": connection.get(TRACKMAP_RESOURCE)} if trackmap else {}),
    }


def settings_path() -> str:
    return os.path.join(cfg.path.config, SETTINGS_FILE)


def load_page_settings() -> dict[str, Any]:
    try:
        with open(settings_path(), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_page_settings(data: dict[str, Any]):
    with atomic_write(settings_path()) as file:
        json.dump(data, file, indent=1, ensure_ascii=False)


def number_setting(data: dict, name: str, default: float, low: float, high: float) -> float:
    value = data.get(name, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return min(max(float(value), low), high)


class DirectorBackend(QObject):
    """Broadcast Director page state (QML context property "backend")"""

    statusChanged = Signal()
    clockChanged = Signal()
    modeChanged = Signal()
    settingsChanged = Signal()
    onAirChanged = Signal()
    cameraChanged = Signal()
    carsChanged = Signal()
    classFilterChanged = Signal()
    suggestionsChanged = Signal()
    feedChanged = Signal()
    battlesChanged = Signal()
    classesChanged = Signal()
    pitsChanged = Signal()
    sheetChanged = Signal()
    noticeChanged = Signal()
    lockChanged = Signal()
    instantChanged = Signal()
    weatherChanged = Signal()
    forecastChanged = Signal()
    graphicsChanged = Signal()
    lapsChanged = Signal()
    onDemandChanged = Signal()
    championshipChanged = Signal()
    timingChanged = Signal()
    timingColumnsChanged = Signal()

    def __init__(self, parent: QObject):
        global _active
        super().__init__(parent)
        settings = load_page_settings()
        saved_mode = settings.get("mode")
        # Automatic cuts never start by themselves: page opens assisted when it was left automatic
        self.mode = "assist" if saved_mode == "auto" or saved_mode not in MODES else str(saved_mode)
        style = settings.get("camera_style")
        self.director = dr.Director(dr.DirectorSettings(
            min_shot=number_setting(settings, "min_shot", 8.0, 3.0, 60.0),
            max_shot=number_setting(settings, "max_shot", 30.0, 5.0, 300.0),
            battle_gap=number_setting(settings, "battle_gap", 1.0, 0.2, 3.0),
            camera_style=str(style) if style in dr.CAMERA_STYLES else "mixed",
        ))
        self.director.settings.max_shot = max(self.director.settings.max_shot, self.director.settings.min_shot)
        self.watcher = dr.RaceWatcher(self.director.settings.battle_gap)
        self.follow_overlays = settings.get("follow_overlays") is True
        self.seconds_before = int(number_setting(settings, "seconds_before", SECONDS_BEFORE, 0, 60))
        self.post_roll = int(number_setting(settings, "post_roll", POST_ROLL, 0, 60))
        # Car chosen in the game (or by another app): operator cut holding the director, or just followed
        self.follow_game_cuts = settings.get("follow_game_cuts") is not False
        host = settings.get("game_host")
        self.game_host = host.strip() if isinstance(host, str) else ""  # game on another computer, "" this one
        self.log_events = settings.get("log_events") is True  # events written to a file as they happen
        self.tyres: dict[int, tuple[str, str]] = {}
        self.forecast: list[dict] = []
        self._polls = 0
        self.logos = LogoCache()
        self.graphics = graphics_setting(settings.get("graphics"))
        self.on_demand = ""  # graphic shown by the operator (starting grid, event card...), "" if none
        self.captured: dict[str, Any] | None = None  # classification captured for the graphics
        self.championships = load_championships()
        index = settings.get("championship")
        self.championship_index = index if isinstance(index, int) and 0 <= index < len(self.championships) else 0
        cls = settings.get("championship_class")
        self.championship_class = cls if isinstance(cls, str) else ""
        self.timing_columns = timing_setting(settings.get("timing"))
        view = settings.get("timing_view")
        self.timing_view = view if view in TIMING_VIEWS else "race"
        self.timing_open = False  # timing table shown: its rows made at each answer
        self._timing_model = DictListModel(TIMING_ROLES, self)
        self.instant_event: dr.Event | None = None  # event of the instant replay shown
        self.auto_shown = ""  # on demand graphic shown by the director itself (hidden by it too)
        self._auto_done: set[str] = set()  # automatic graphics already shown this session
        self.message: dict[str, Any] | None = None  # message of the operator on the graphics
        self.countdown_end = 0.0  # time.time() the countdown of the operator ends, 0 if none
        self.countdown_label = ""
        self._sector_ends = [0.0, 0.0]  # meters: end of sectors 1 & 2 (furthest place seen in each)
        self._brand: tuple[float, tuple[str, list[str]]] = (0.0, ("", []))  # read time, logo & sponsors
        self._champ_view: tuple = ()  # what the championship graphic was made from
        self._champ_state: dict[str, Any] | None = None
        self._history_busy = False
        self._history_version = -1
        self._need_track = True  # track outline asked with next state (new session)
        self._quali_times: tuple[tuple, dict[str, float]] = ((), {})  # qualifying results of the session
        self._index_of: dict[int, int] = {}  # shared memory vehicle index of each slot (live feed)
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(LIVE_MS)
        self._live_timer.timeout.connect(self.publish_live)
        self._auto_timer = QTimer(self)  # event card shown at session start: hidden after a while
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self.end_auto_event)
        self.read_history()
        self.session_end = -1.0
        self.cut_count = 0  # cars put on air: graphics show the driver card again
        self._links: dict[tuple[str, int], tuple[str, str]] = {}  # (vehicle, pictures version): logo & picture links
        notifier().changed.connect(self.pictures_changed)
        self.search_words: list[str] = []
        self._stale = False  # answers came while page hidden: models refreshed when shown
        self._fronts: dict[int, Standing] = {}  # car ahead in class of each car (slot), each answer
        self._grid: dict[int, int] = {}  # class place on starting grid of each car (slot), each answer
        self._texts: dict[str, tuple[str, str]] = {}  # event key: title & detail
        self._laps_view: tuple | None = None  # what lap rows were made from
        self._feed_view: tuple | None = None  # what feed rows were made from
        self._connection: GameConnection | None = None  # connection of state requests (their thread only)
        self.locked = False  # car on air kept: director does not cut
        self.seen: set[str] = set()  # incidents looked at (shown on air, replayed, clicked)
        self.instant = False  # instant replay of a live session shown
        self.instant_waiting = False  # instant replay asked, not playing yet
        self.session_info = SessionState()
        self.laps_slot = -1  # car of lap history shown, -1 if none
        self._weather: list[str] = []
        notes = settings.get("notes")
        self.notes: dict[str, str] = ({str(key): str(value) for key, value in notes.items() if value}
                                      if isinstance(notes, dict) else {})
        self.state = OFFLINE
        self.session_key: tuple[str, str, float] = ("", "", 0)
        self.session_time = -1.0
        self.time_received = 0.0  # time.time() of session time
        self.replay_rate = 0.0
        self.track_length = 0.0
        self.standings: list[Standing] = []
        self.by_slot: dict[int, Standing] = {}
        self.places: dict[int, int] = {}
        self.contacts: tuple[Contact, ...] = ()
        self.incident_counts: dict[str, int] = {}
        self.events: list[dr.Event] = []  # oldest first
        self.event_index: dict[str, dr.Event] = {}
        self.candidates: list[dr.Candidate] = []
        self.camera = ("", "")  # group & name told by game
        self.trackside_choice = ""
        self.focus = -1  # car followed by camera (game)
        self.last_cut = 0.0  # monotonic time of last cut sent
        self.on_air_slot = -1  # car on air (director or operator), -1 if none
        self.on_air_kind = ""
        self.on_air_start = 0.0  # time.time() shot started
        self.selected = -1  # car of sheet
        self.class_filter = ""
        self.feed_filter = 0
        self.last_command = ""
        self.notice = ""
        self.notice_error = False
        self._shown = False
        self._open = True
        self._cars_model = DictListModel(CAR_ROLES, self)
        self._feed_model = DictListModel(FEED_ROLES, self)
        self._suggestions_model = DictListModel(SUGGESTION_ROLES, self)
        self._battles_model = DictListModel(BATTLE_ROLES, self)
        self._classes_model = DictListModel(CLASS_ROLES, self)
        self._pits_model = DictListModel(PIT_ROLES, self)
        self._laps_model = DictListModel(LAP_ROLES, self)
        self._class_list: list[dict] = []
        self._on_air: dict[str, Any] = {}
        self._sheet: dict[str, Any] = {}
        self._hold = (0.0, 0.0)  # director hold (monotonic), same as time.time()
        self.request_state = GameRequest(self, (), self.received_state, self.schedule)
        self.request_command = GameRequest(self, (), self.command_done, self.command_failed)
        self.command_queue: list[tuple[gc.Command, ...]] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh_state)
        self._instant_timer = QTimer(self)  # instant replay over: back to live
        self._instant_timer.setSingleShot(True)
        self._instant_timer.timeout.connect(self.backToLive)
        _active = weakref.ref(self)

    # Page
    def page_shown(self):
        """Game asked at once; then about every second until the page closes (hidden too: director runs)"""
        self._shown = True
        if self._stale:
            self.refresh_models()
        if not self.request_state.busy:
            self._timer.stop()
            self.refresh_state()

    def page_hidden(self):
        self._shown = False

    def release(self):
        global _active
        self._open = False
        self._timer.stop()
        self._instant_timer.stop()
        self._live_timer.stop()
        self._auto_timer.stop()
        self.command_queue.clear()
        connection, self._connection = self._connection, None
        if connection is not None and not self.request_state.busy:
            connection.close()
        if _active is not None and _active() is self:
            _active = None

    def refresh_models(self):
        """Every list & card of the page made again from the last answer"""
        self._stale = False
        self.update_feed()
        self.update_suggestions()
        self.update_laps()
        self.update_cars()
        self.update_battles()
        self.update_classes()
        self.update_pits()
        self.update_sheet()
        self.update_on_air()

    def save_settings(self):
        settings = self.director.settings
        save_page_settings({
            "mode": self.mode, "min_shot": settings.min_shot, "max_shot": settings.max_shot,
            "battle_gap": settings.battle_gap, "camera_style": settings.camera_style,
            "follow_overlays": self.follow_overlays, "seconds_before": self.seconds_before,
            "post_roll": self.post_roll, "follow_game_cuts": self.follow_game_cuts,
            "game_host": self.game_host, "log_events": self.log_events, "graphics": self.graphics,
            "notes": dict(sorted(self.notes.items())), "championship": self.championship_index,
            "championship_class": self.championship_class, "timing": self.timing_columns,
            "timing_view": self.timing_view,
        })

    def notify(self, text: str, error: bool = False):
        self.notice, self.notice_error = text, error
        self.noticeChanged.emit()

    # Game requests
    @Slot()
    def refresh(self):
        self._timer.stop()
        self.refresh_state()

    def refresh_state(self):
        if self._open:
            self.request_state.start(self.poll_game)

    def poll_game(self) -> dict[str, Any]:
        """Game state (background thread of state requests): one connection kept from answer to answer
        (game keeps it alive), a new one once it failed"""
        connection = self._connection
        if connection is None or connection.failed:
            address = self.game_address()
            connection = self._connection = (game_rest.GameConnection(address=address) if address is not None
                                             else game_rest.GameConnection())
        self._polls += 1
        return ask_state(connection, forecast=self._polls % WEATHER_EVERY == 1, trackmap=self._need_track)

    def game_address(self) -> tuple[str, int] | None:
        """Game on another computer (host of page settings, port of the app Rest API), None: app settings"""
        if self.game_host.lower() in LOCAL_HOSTS:
            return None
        default = game_rest.game_address()
        return self.game_host, default[1] if default is not None else 6397

    def local_game(self) -> bool:
        """Game runs on this computer: its shared memory tells the same session"""
        return self.game_host.lower() in LOCAL_HOSTS

    @staticmethod
    def connected(work) -> Any:
        with game_rest.GameConnection() as connection:
            return work(connection)

    def schedule(self):
        if self._open and not self.request_state.busy:
            self._timer.start(POLL_MS if self.state in (SESSION, REPLAY) else IDLE_POLL_MS)

    def received_state(self, state: dict):
        if not self._open:
            return
        active = state["active"]
        if active is None:
            self.set_state(MENU if state["running"] else OFFLINE)
            self.schedule()
            return
        self.set_state(REPLAY if active else SESSION)
        key = (state["track"], state["session"], state.get("start", 0))
        # Another session (other track or session, or same session started again): everything starts again
        if key[:2] != self.session_key[:2] or (key[2] and self.session_key[2] and key[2] != self.session_key[2]):
            self.session_key = key
            self.new_session()
        self.session_key = key
        self.session_end = state.get("end", -1.0)
        self.track_length = state["length"]
        self.update_clock(state["time"])
        self.standings = state["standings"]
        self.index_cars()
        if state["contacts"] != self.contacts:
            self.contacts = state["contacts"]
            self.incident_counts = self.count_incidents()
        if state["camera"] != self.camera:
            self.camera = state["camera"]
            self.cameraChanged.emit()
        self.update_weather(state["info"])
        if "forecast" in state:
            forecast = parse_forecast(state["forecast"], self.session_key[1])
            if forecast != self.forecast:
                self.forecast = forecast
                self.forecastChanged.emit()
        self.tyres = self.read_tyres() if self.local_game() else {}
        if "trackmap" in state:
            self.set_track(state["trackmap"])
        if self.instant:  # instant replay: replay frames are not the race going on, director waits
            if self._shown:
                self.update_cars()
                self.update_on_air()
            self.publish_graphics()
            self.schedule()
            return
        self.follow_game_focus(state["focus"] if state["focus"] >= 0
                               else next((car.slot for car in self.standings if car.focus), -1))
        new_events = self.watcher.update(self.standings, self.contacts, self.session_time, state["session"],
                                         self.track_length, state["info"])
        if new_events:
            self.add_events(new_events)
        self.note_sector_ends()
        self.auto_graphics(new_events)
        if self._polls % HISTORY_EVERY == 0:
            self.read_history()
        self.direct()
        if self._shown:  # hidden: director & watcher go on, lists made again once shown
            self.refresh_models()
        else:
            self._stale = True
        if self.timing_open:
            self.update_timing()
        self.publish_graphics()
        self.schedule()

    @staticmethod
    def read_tyres() -> dict[int, tuple[str, str]]:
        """Tyres of every car while the API reads the game (shared memory)"""
        from ...api_control import api

        reader = getattr(api, "read", None)
        return read_tyres(reader) if reader is not None else {}

    def pictures_changed(self):
        """Car brand logos & pictures arrived from the game"""
        if self._shown:
            self._sheet = {}
            self._on_air = {}
            self.update_cars()
            self.update_sheet()
            self.update_on_air()

    # Broadcast graphics
    def picture_links(self, vehicle: str) -> tuple[str, str]:
        """Brand logo (for dark graphics) & car picture addresses on the stream server, "" if none"""
        from ...stream_overlay import picture_link
        from ...userfile.custom_image import brand_logo_file
        from ...userfile.game_images import images

        key = (vehicle, images.version)
        links = self._links.get(key)
        if links is None:
            logo = brand_logo_file(cfg.path.brand_logo, images.brand(vehicle, ""), False, vehicle) if vehicle else ""
            links = (picture_link(logo), picture_link(images.car_picture(vehicle)) if vehicle else "")
            if len(self._links) > 256:
                self._links.clear()
            self._links[key] = links
        return links

    def clock_state(self) -> dict[str, str] | None:
        """Session clock of graphics: time left when the session has a length, else time gone"""
        if self.session_time < 0:
            return None
        start = self.session_key[2] if isinstance(self.session_key[2], (int, float)) else 0
        if self.session_info.phase < dr.GREEN_PHASE and start > self.session_time > 0:
            return {"text": clock_text(start - self.session_time), "label": tr("Start in")}
        if self.session_end > 0:
            return {"text": clock_text(max(self.session_end - self.session_time, 0.0)), "label": tr("Remaining")}
        return {"text": clock_text(self.session_time), "label": tr("Elapsed")}

    def graphics_state(self) -> dict[str, Any]:
        """What the broadcast graphics show now (texts in app language)"""
        from ...stream_director import labels

        race = dr.is_race(self.session_key[1])
        grid = self._grid if race else {}
        fastest = self.class_fastest()
        tower = []
        previous: Standing | None = None
        leader = self.standings[0] if self.standings else None
        class_leaders: dict[str, Standing] = {}
        for car in self.standings:
            class_leaders.setdefault(car.car_class, car)
            seconds, laps = interval(self._fronts[car.slot], car, self.track_length) \
                if car.slot in self._fronts else (-1.0, 0)
            tower.append({
                "pos": car.position, "classPos": self.places.get(car.slot, 0), "cls": car.car_class,
                "color": class_color(car.car_class), "number": car.number, "name": short_name(car.driver),
                "gap": interval_text(previous, car, self.track_length) if previous is not None else "",
                "gapClass": interval_text(self._fronts.get(car.slot), car, self.track_length),
                "close": laps == 0 and 0 <= seconds < NEAR_GAP, "pit": car.in_pit or car.garage,
                "air": car.slot == self.on_air_slot,
                "change": grid[car.slot] - self.places.get(car.slot, 0) if car.slot in grid else 0,
                # Last lap: shown a few seconds by the source when a new one comes (lap count changed)
                "lap": lap_text(car.last) if car.last > 0 else "", "lapId": car.laps,
                "lapTone": "fastest" if car.last > 0 and car.last <= fastest.get(car.car_class, 0.0) + 0.0005 else "",
                "tyres": [letter for letter in dict.fromkeys(self.tyres.get(car.slot, ())) if letter],
                "pen": car.penalties,
                "gapLeader": interval_text(leader, car, self.track_length) if car is not leader else "",
                "gapClassLeader": interval_text(class_leaders[car.car_class], car, self.track_length)
                if car is not class_leaders[car.car_class] else "",
                "fastest": car.best > 0 and car.best <= fastest.get(car.car_class, 0.0) + 0.0005,
                "stops": car.pitstops,
            })
            previous = car
        on_air = None
        shown = self.by_slot.get(self.on_air_slot)
        if shown is not None:
            kind = self.on_air_kind
            on_air = self.card_state(shown, self.story_text(kind),
                                     KIND_TONES.get(kind, "") if kind in STORY_KINDS else "", grid)
        battle = None
        fight = next((item for item in self.watcher.battles.values()
                      if self.on_air_slot in (item.ahead, item.behind)), None)
        story = self.on_air_kind in (dr.BATTLE, dr.OVERTAKE, dr.LEAD)
        if fight is not None and story:
            ahead, behind = self.by_slot.get(fight.ahead), self.by_slot.get(fight.behind)
            if ahead is not None and behind is not None:
                trend = self.trend_text(fight, behind)
                battle = {
                    "title": f"{tr('Battle for P%1').replace('%1', str(fight.position))} · {fight.car_class}",
                    "color": class_color(fight.car_class), "gap": seconds_text(fight.gap), "trend": trend,
                    "trendClass": "closing" if fight.trend < -0.02 else "opening" if fight.trend > 0.02 else "",
                    "ahead": {"number": ahead.number, "name": short_name(ahead.driver), "team": ahead.team},
                    "behind": {"number": behind.number, "name": short_name(behind.driver), "team": behind.team},
                }
        events: list[dict[str, Any]] = []
        for event in reversed(self.events):
            if len(events) >= BANNERS_KEPT:
                break
            heavy = event.kind in (dr.CONTACT, dr.WALL) and self.watcher.severity.get(event.key, -1.0) >= dr.HEAVY
            if event.live and (event.kind in BANNER_KINDS or heavy):
                title, detail = self.event_texts(event)
                events.append({"id": event.key, "kind": self.kind_text(event), "title": title, "detail": detail,
                               "tone": KIND_TONES.get(event.kind, "accent"), "type": event.kind,
                               "priority": BANNER_PRIORITY.get(event.kind, 1) + (3 if heavy else 0),
                               # Source opened just now: banner of what just happened still shown
                               "fresh": 0 <= self.session_time - event.time < self.graphics["bannerSeconds"]})
        events.reverse()
        flag = "" if self.session_info.yellow in ("NONE", "INVALID", "") else tr("Full course yellow")
        radar = None
        if shown is not None and self.graphics["pitRadar"]:
            rows = self.pit_neighbours(shown)
            if rows:
                count = sum(1 for row in rows if not row["ahead"])
                radar = {"title": tr("Pit lane"), "rows": rows[:6],
                         "count": tr("%1 cars approaching").replace("%1", str(count)) if count else ""}
        on_demand = self.on_demand
        return {
            "pitRadar": radar,
            "live": self.can_command(), "graphics": self.graphics, "cut": self.cut_count, "tower": tower,
            "onAir": on_air, "battle": battle, "events": events, "replay": self.instant or self.state == REPLAY,
            "train": self.train_state() if story and self.graphics["train"] else None,
            "replayInfo": self.replay_info(grid) if self.graphics["replayGraphics"] else None,
            "clock": self.clock_state(), "flag": flag,
            "weather": [text for text in self.weather_texts() if text != flag],
            "onboard": self.onboard_state() if self.graphics["onboard"] else None,
            "quali": self.quali_state() if self.graphics["quali"] and not race else None,
            "map": self.map_state() if self.graphics["map"] else None,
            "grid": self.grid_state() if on_demand == "grid" else None,
            "event": self.event_state() if on_demand == "event" else None,
            "results": self.captured if on_demand == "results" else None,
            "champ": self.championship_state() if on_demand == "champ" else None,
            "message": self.message,
            "countdown": self.countdown_state(),
            "brand": self.brand_state(),
            "labels": labels(tr),
        }

    def card_state(self, car: Standing, story: str, tone: str, grid: dict[int, int]) -> dict[str, Any]:
        """Driver card of a car"""
        logo, picture = self.picture_links(car.vehicle)
        gained = grid.get(car.slot, 0) - self.places.get(car.slot, 0) if car.slot in grid else 0
        name = car.driver.split("#", 1)[0].strip() or car.driver
        ranks.poll()
        known = ranks.team_ranks(name)  # player & team members only (game menu data)
        return {
            "number": car.number, "name": name,
            "team": car.team or car.vehicle, "cls": car.car_class, "color": class_color(car.car_class),
            "classPos": self.places.get(car.slot, 0), "logo": logo, "picture": picture,
            "stats": [[tr("Best"), lap_text(car.best) if car.best > 0 else ""],
                      [tr("Last"), lap_text(car.last) if car.last > 0 else ""],
                      [tr("Laps"), str(car.laps)],
                      [tr("Places"), f"{'+' if gained > 0 else ''}{gained}" if gained else ""],
                      ["DR", known.driver.short if known is not None and known.driver else ""],
                      ["SR", known.safety.short if known is not None and known.safety else ""]],
            "story": story, "storyTone": tone,
        }

    def class_fastest(self) -> dict[str, float]:
        """Best lap of each class"""
        fastest: dict[str, float] = {}
        for car in self.standings:
            if car.best > 0 and (fastest.get(car.car_class, 0.0) <= 0 or car.best < fastest[car.car_class]):
                fastest[car.car_class] = car.best
        return fastest

    def weather_texts(self) -> list[str]:
        """Weather of the graphics, in the temperature unit of the graphics"""
        info, unit = self.session_info, self.graphics["temperatureUnit"]
        return [text for text in (
            tr("Air %1").replace("%1", temperature_text(info.air, unit)) if info.air > -999 else "",
            tr("Track %1").replace("%1", temperature_text(info.track, unit)) if info.track > -999 else "",
            tr("Rain %1").replace("%1", f"{round(info.rain * 100)}%") if info.rain > 0.005 else "",
            tr("Wet %1").replace("%1", f"{round(info.wetness * 100)}%") if info.wetness > 0.005 else "",
        ) if text]

    def train_state(self) -> dict[str, Any] | None:
        """Battle train of the car on air: cars of its class following each other closely (3 to 6), None if not"""
        car = self.by_slot.get(self.on_air_slot)
        if car is None or not dr.running(car):
            return None
        cars = [other for other in self.standings if other.car_class == car.car_class and dr.running(other)]
        limit = self.director.settings.battle_gap
        chain = [cars[0]] if cars else []
        trains = [chain]
        for ahead, behind in pairwise(cars):
            seconds, laps = interval(ahead, behind, self.track_length)
            if laps == 0 and 0 <= seconds <= limit:
                chain.append(behind)
            else:
                chain = [behind]
                trains.append(chain)
        train = next((item for item in trains if any(other.slot == car.slot for other in item)), [])
        if len(train) < TRAIN_MIN:
            return None
        index = next(position for position, other in enumerate(train) if other.slot == car.slot)
        start = min(max(index - TRAIN_MAX // 2, 0), max(len(train) - TRAIN_MAX, 0))
        train = train[start:start + TRAIN_MAX]
        first = self.places.get(train[0].slot, 0)
        return {
            "title": f"{tr('Battle for P%1').replace('%1', str(first))} · {car.car_class}",
            "color": class_color(car.car_class),
            "cars": [{"number": other.number, "name": short_name(other.driver), "color": class_color(other.car_class),
                      "classPos": self.places.get(other.slot, 0), "air": other.slot == car.slot,
                      "gap": interval_text(train[position - 1], other, self.track_length) if position else ""}
                     for position, other in enumerate(train)],
        }

    def replay_info(self, grid: dict[int, int]) -> dict[str, Any] | None:
        """Graphics of the instant replay shown: contact of two cars (both), other events (driver card)"""
        event = self.instant_event
        if not self.instant or event is None:
            return None
        cars = [self.by_slot[slot] for slot in event.slots if slot in self.by_slot]
        if not cars:
            return None
        kind, tone = self.kind_text(event), KIND_TONES.get(event.kind, "accent")
        if event.kind == dr.CONTACT and len(cars) > 1:
            first, second = cars[0], cars[1]
            return {
                "mode": "duel", "kind": kind, "tone": tone, "center": tr("Replay").upper(),
                "ahead": {"number": first.number, "name": short_name(first.driver), "team": first.team},
                "behind": {"number": second.number, "name": short_name(second.driver), "team": second.team},
            }
        return {"mode": "driver", "kind": kind, "tone": tone, "car": self.card_state(cars[0], kind, tone, grid)}

    def onboard_state(self) -> dict[str, Any] | None:
        """Car of the onboard graphic (car on air): what does not change many times a second"""
        car = self.by_slot.get(self.on_air_slot)
        if car is None:
            return None
        ahead = self._fronts.get(car.slot)
        gap = interval_text(ahead, car, self.track_length) if ahead is not None else ""
        return {"number": car.number, "name": short_name(car.driver), "color": class_color(car.car_class),
                "cls": car.car_class, "rpmMax": self.rpm_max(car.slot),
                "ahead": f"#{ahead.number} {gap}" if ahead is not None and gap else ""}

    def rpm_max(self, slot: int) -> float:
        """Highest engine rpm of a car (shared memory of the game on this computer), 9000 if unknown"""
        reader = self.reader()
        index = self.vehicle_index(slot)
        if reader is None or index < 0:
            return 9000.0
        try:
            value = float(reader.engine.rpm_max(index))
        except (AttributeError, IndexError, TypeError, ValueError):
            return 9000.0
        return value if value > 1000 else 9000.0

    def quali_state(self) -> dict[str, Any] | None:
        """Lap of the car on air outside races: lap time running, sectors, gap to pole of its class"""
        car = self.by_slot.get(self.on_air_slot)
        if car is None:
            return None
        personal, class_best = self.watcher.best_sectors(self.standings)
        bests, class_bests = personal.get(car.slot, [-1.0] * 3), class_best.get(car.car_class, [-1.0] * 3)
        current = dr.current_sectors(car)
        timed = [other for other in self.standings if other.car_class == car.car_class and other.best > 0]
        pole = min(timed, key=lambda other: other.best) if timed else None
        delta, improving = None, False
        if pole is not None and current[0] > 0:  # gap to pole lap at the last sector done
            done = car.current_sector2 if current[1] > 0 else car.current_sector1
            reference = pole.best_sector2 if current[1] > 0 else pole.best_sector1
            if reference > 0:
                delta = done - reference
            improving = all(value <= best + 0.0005 for value, best in zip(current, bests) if value > 0 and best > 0)
        elif pole is not None and car.best > 0:
            delta = car.best - pole.best
        state = self.watcher.cars.get(car.slot)
        if car.in_pit or car.garage:
            status = tr("In Pits")
        elif state is not None and state.lap_pit:
            status = tr("Out lap")
        elif improving and car.best > 0:
            status = tr("Improving")
        else:
            status = ""
        running = not car.in_pit and not car.garage and car.into_lap >= 0
        return {
            "number": car.number, "name": short_name(car.driver), "color": class_color(car.car_class),
            "position": f"P{self.places.get(car.slot, 0)}", "running": running,
            "lapStart": car.lap_start, "now": self.session_time,
            "best": lap_text(car.best), "target": lap_text(pole.best) if pole is not None else "-",
            "targetLabel": tr("Pole"),
            "delta": delta_text(delta) if delta is not None else "",
            "deltaTone": "" if delta is None else "gain" if delta < 0 else "loss",
            "status": status,
            "sectors": [{"text": localized(f"{value:.3f}") if value > 0 else "-",
                         "tone": sector_tone(value, bests[index], class_bests[index])}
                        for index, value in enumerate(current)],
        }

    def map_state(self) -> dict[str, Any]:
        """Cars of the track map (positions of the answer, live feed moves them), yellow flag car"""
        from ...stream_director import track_outline

        cars = {str(car.slot): [round(car.x, 1), round(car.y, 1), class_color(car.car_class), car.number,
                                car.slot == self.on_air_slot, car.in_pit]
                for car in self.standings if not car.garage}
        flagged = any(self.session_info.sector_flags) if self.session_info.sector_flags else False
        yellow = -1
        if flagged:
            event = next((event for event in reversed(self.events[-50:]) if event.kind == dr.YELLOW and event.slots
                          and self.session_time - event.time < 120), None)
            yellow = event.slots[0] if event is not None else -1
        flags = list(self.session_info.sector_flags or ())[:3]
        ends = self._sector_ends
        sectors = [round(end / self.track_length, 4) for end in ends] if (
            self.track_length > 0 and 0 < ends[0] < ends[1] < self.track_length) else []
        return {"track": track_outline.key, "yellow": yellow, "cars": cars, "sectors": sectors,
                "yellowSectors": flags + [False] * (3 - len(flags))}

    def note_sector_ends(self):
        """End of sectors 1 & 2 along the lap: furthest place a car was seen in each (track map sectors)"""
        for car in self.standings:
            if car.sector in (1, 2) and 0 < car.distance < self.track_length and not car.in_pit:
                index = car.sector - 1
                if car.distance > self._sector_ends[index]:
                    self._sector_ends[index] = car.distance

    def set_track(self, points: Any):
        """Track outline of the session from the game (racing line & pit lane)"""
        from ...stream_director import track_outline
        from ...userfile.track_geometry import parse_points

        if not isinstance(points, list):
            return
        racing, pit = parse_points(points)
        if len(racing) < 3:
            return
        self._need_track = False
        track_outline.set(f"{self.session_key[0]}|{len(racing)}", [(x, y) for x, y, _ in racing],
                          [(x, y) for x, y, _ in pit])

    def qualifying_times(self) -> dict[str, float]:
        """Best lap of each driver in the last qualifying of this track (results files), read once a session in
        background (empty until read: grid made again then)"""
        key = self.session_key
        if self._quali_times[0] == key:
            return self._quali_times[1]
        self._quali_times = (key, {})
        track = fold(self.session_key[0])

        def read():
            from ...stream_overlay import streamoverlay

            try:
                result = streamoverlay.results.latest("qualifying")
            except (OSError, ValueError):
                result = None
            times: dict[str, float] = {}
            if result is not None and track and (track in fold(result.track) or fold(result.track) in track):
                times = {entry.name: entry.best_lap for entry in result.entries if entry.best_lap > 0}
            if times and self._quali_times[0] == key:
                self._quali_times = (key, times)  # next graphics state shows them

        threading.Thread(target=read, daemon=True, name="Director qualifying times").start()
        return {}

    def grid_state(self) -> dict[str, Any]:
        """Starting grid: cars by qualifying place, qualifying lap, car picture"""
        times = self.qualifying_times()
        ordered = sorted(self.standings, key=lambda car: (car.grid <= 0, car.grid, car.position))
        cars = []
        for index, car in enumerate(ordered, 1):
            _, picture = self.picture_links(car.vehicle)
            best = times.get(car.driver, 0.0)
            cars.append({"pos": car.grid if car.grid > 0 else index, "number": car.number,
                         "name": short_name(car.driver), "team": car.team or car.vehicle, "cls": car.car_class,
                         "color": class_color(car.car_class), "time": lap_text(best) if best > 0 else "",
                         "picture": picture})
        return {"title": tr("Starting Grid"), "cars": cars}

    def event_state(self) -> dict[str, Any]:
        """Event card: track, session, conditions, forecast, schedule"""
        from ...stream_overlay import picture_link
        from ...userfile.game_images import images

        track, session = self.session_key[:2]
        unit = self.graphics["temperatureUnit"]
        kind = next((text for prefix, text in SESSION_TEXTS.items() if session.upper().startswith(prefix)), "")
        schedule = [[tr("Session"), tr(kind) if kind else session.title()]]
        start = self.session_key[2] if isinstance(self.session_key[2], (int, float)) else 0
        if self.session_end > 0:
            schedule.append([tr("Session length"), clock_text(self.session_end - max(start, 0.0))])
        clock = self.clock_state()
        if clock is not None:
            schedule.append([clock["label"], clock["text"]])
        schedule.append([tr("Cars"), str(len(self.standings))])
        classes = list(dict.fromkeys(car.car_class for car in self.standings if car.car_class))
        if len(classes) > 1:
            schedule.append([tr("Classes"), " · ".join(classes)])
        forecast = [{**node, "temperature": temperature_text(node.get("celsius", -1000.0), unit)
                     if node.get("celsius", -1000.0) > -999 else node.get("temperature", "")} for node in self.forecast]
        return {
            "track": track, "session": tr(kind) if kind else session.title(),
            "logo": picture_link(images.track_logo(track)) if track else "",
            "conditions": self.weather_texts(), "forecast": forecast, "schedule": schedule,
        }

    def results_state(self) -> dict[str, Any]:
        """Classification now (captured by the operator): every car, gap to leader, best lap, pit stops"""
        leader = self.standings[0] if self.standings else None
        rows = []
        for car in self.standings:
            status, _ = status_text(car)
            if car.finish == "FSTAT_FINISHED" or car.in_pit or car.garage:
                status = "" if car.finish == "FSTAT_FINISHED" else status
            rows.append({
                "pos": car.position, "classPos": self.places.get(car.slot, 0), "cls": car.car_class,
                "color": class_color(car.car_class), "number": car.number, "name": short_name(car.driver),
                "team": car.team or car.vehicle, "laps": car.laps,
                "gap": tr("Leader") if car is leader else interval_text(leader, car, self.track_length),
                "best": lap_text(car.best), "pits": car.pitstops,
                "status": status if car.finish in ("FSTAT_DNF", "FSTAT_DQ") else "",
            })
        laps = leader.laps if leader is not None else 0
        clock = self.clock_state()
        parts = [tr("Lap %1").replace("%1", str(laps)) if laps else "", f"{clock['label']} {clock['text']}" if clock else ""]
        return {"title": tr("Classification"), "subtitle": " · ".join(part for part in parts if part), "rows": rows}

    def championship_state(self) -> dict[str, Any] | None:
        """Championship standings chosen (class chosen, or every driver), made again only when changed"""
        view = (self.championship_index, self.championship_class, id(self.championships),
                len(self.championships))
        if view != self._champ_view:
            self._champ_view = view
            self._champ_state = self.make_championship_state()
        return self._champ_state

    def make_championship_state(self) -> dict[str, Any] | None:
        if not 0 <= self.championship_index < len(self.championships):
            return None
        item = self.championships[self.championship_index]
        cls = self.championship_class if self.championship_class in champ.classes(item["rows"]) else ""
        rows = [{"pos": place, "name": row.name, "team": row.team, "cls": row.car_class,
                 "color": class_color(row.car_class) if row.car_class else "", "points": champ.points_text(row.points),
                 "medal": place if place <= 3 else 0}
                for place, row in champ.standings(item["rows"], cls)]
        return {"title": item["name"], "subtitle": cls, "rows": rows}

    # Live feed: onboard & car positions
    @staticmethod
    def reader() -> Any:
        """Game data of the app (shared memory), None if not readable"""
        from ...api_control import api

        return getattr(api, "read", None)

    def vehicle_index(self, slot: int) -> int:
        """Shared memory vehicle index of a car (slot), -1 if not there (game on another computer)"""
        if not self.local_game():
            return -1
        reader = self.reader()
        if reader is None:
            return -1
        index = self._index_of.get(slot, -1)
        try:
            if index >= 0 and reader.vehicle.slot_id(index) == slot:
                return index
            self._index_of = {reader.vehicle.slot_id(index): index for index in range(reader.vehicle.total_vehicles())}
        except (AttributeError, IndexError, TypeError, ValueError):
            self._index_of = {}
        return self._index_of.get(slot, -1)

    def live_wanted(self) -> bool:
        return self._open and self.can_command() and (self.graphics["onboard"] or self.graphics["map"])

    def update_live_timer(self):
        """Live feed made while onboard or track map graphic is on (a source asks for it)"""
        if self.live_wanted():
            if not self._live_timer.isActive():
                self._live_timer.start()
        else:
            self._live_timer.stop()

    def publish_live(self):
        from ...stream_director import live_feed

        if not self.live_wanted():
            self._live_timer.stop()
            return
        if live_feed.watched():
            live_feed.publish(self.live_state())

    def live_state(self) -> dict[str, Any]:
        """Onboard of the car on air & positions of every car (shared memory of the game on this computer, else
        positions of the last answer)"""
        reader = self.reader() if self.local_game() else None
        onboard = None
        car = self.by_slot.get(self.on_air_slot)
        if self.graphics["onboard"] and car is not None:
            index = self.vehicle_index(car.slot)
            energy = dr.level(car)
            if reader is not None and index >= 0:
                try:
                    speed, unit = speed_value(float(reader.vehicle.speed(index)))
                    onboard = {"speed": round(speed, 1), "unit": unit, "gear": int(reader.engine.gear(index)),
                               "rpm": round(float(reader.engine.rpm(index))),
                               "rpmMax": round(float(reader.engine.rpm_max(index))),
                               "throttle": round(min(max(float(reader.inputs.throttle_raw(index)), 0.0), 1.0), 2),
                               "brake": round(min(max(float(reader.inputs.brake_raw(index)), 0.0), 1.0), 2),
                               "energy": round(energy, 3)}
                except (AttributeError, IndexError, TypeError, ValueError):
                    onboard = None
            if onboard is None:  # game on another computer: speed of the last answer only
                speed, unit = speed_value(car.speed)
                onboard = {"speed": round(speed, 1), "unit": unit, "gear": None, "rpm": 0, "rpmMax": 0, "throttle": 0,
                           "brake": 0, "energy": round(energy, 3)}
        cars: list[float] = []  # slot, x, y of each car (meters, flat: less to send five times a second)
        if self.graphics["map"]:
            done = False
            if reader is not None:
                try:
                    for index in range(reader.vehicle.total_vehicles()):
                        x, _, z = reader.vehicle.position_xyz(index)
                        cars.extend((reader.vehicle.slot_id(index), round(x), round(-z)))
                    done = bool(cars)  # no vehicle in shared memory (other game data): last answer
                except (AttributeError, IndexError, TypeError, ValueError):
                    cars = []
            if not done:
                cars = [value for car in self.standings for value in (car.slot, round(car.x), round(car.y))]
        return {"onboard": onboard, "cars": cars}

    def pit_neighbours(self, car: Standing) -> list[dict[str, Any]]:
        """Cars near the car on air in the pit lane: number, name, color, distance text, alongside, ahead"""
        from ... import units

        unit = units.set_unit_distance(cfg.units.get("distance_unit", "Meter"))
        symbol = units.set_symbol_distance(cfg.units.get("distance_unit", "Meter"))
        rows = []
        for neighbour in dr.pit_radar(car, self.standings, self.track_length, self.graphics["pitRadarRange"]):
            other = self.by_slot[neighbour.slot]
            rows.append({
                "number": other.number, "name": short_name(other.driver), "color": class_color(other.car_class),
                "distance": f"{round(unit(abs(neighbour.distance)))} {symbol}", "alongside": neighbour.alongside,
                "ahead": neighbour.distance > 0,
            })
        return rows

    def story_text(self, kind: str) -> str:
        if kind == dr.BATTLE and self.on_air_slot in {slot for battle in self.watcher.battles.values()
                                                      for slot in (battle.ahead, battle.behind)}:
            fight = next(item for item in self.watcher.battles.values()
                         if self.on_air_slot in (item.ahead, item.behind))
            return tr("Battle for P%1").replace("%1", str(fight.position))
        return tr(KIND_TEXTS[kind]) if kind in STORY_KINDS else ""

    def publish_graphics(self, force: bool = False):
        """Graphics state to the browser source, only while a source shows it (or settings changed)"""
        from ...stream_director import director_feed

        self.update_live_timer()
        if force or director_feed.watched():
            director_feed.publish(self.graphics_state())

    def index_cars(self):
        """Indexes of the cars of last answer: by slot, class place, car ahead in class, class place on grid"""
        self.by_slot = {car.slot: car for car in self.standings}
        self.places = dr.class_places(self.standings)
        last: dict[str, Standing] = {}
        self._fronts = {}
        for car in self.standings:
            if car.car_class in last:
                self._fronts[car.slot] = last[car.car_class]
            last[car.car_class] = car
        counts: dict[str, int] = {}
        self._grid = {}
        for car in sorted((car for car in self.standings if car.grid > 0), key=lambda item: item.grid):
            counts[car.car_class] = counts.get(car.car_class, 0) + 1
            self._grid[car.slot] = counts[car.car_class]

    def set_state(self, state: str):
        if state == self.state:
            return
        self.state = state
        if state != REPLAY:
            self.last_command = ""
        if state in (OFFLINE, MENU) and self.instant:
            self.instant = False
            self.instant_event = None
            self._instant_timer.stop()
            self.instantChanged.emit()
        if state in (OFFLINE, MENU):
            self.candidates = []
            self._suggestions_model.reset([])
            self.suggestionsChanged.emit()
        self.statusChanged.emit()

    def new_session(self):
        self.watcher.reset()
        self.director.reset()
        self.events.clear()
        self.event_index.clear()
        self.contacts = ()
        self.incident_counts = {}
        self.on_air_slot = -1
        self.on_air_kind = ""
        self.selected = -1
        self.seen.clear()
        self.laps_slot = -1
        self._texts.clear()
        self._need_track = True
        self.captured = None
        self.instant_event = None
        self._sector_ends = [0.0, 0.0]
        self._auto_done.clear()
        if self.auto_shown and self.on_demand == self.auto_shown:
            self.on_demand = ""
            self.onDemandChanged.emit()
        self.auto_shown = ""
        if self.graphics["autoEvent"]:
            self.show_auto("event")
            self._auto_timer.start(AUTO_EVENT_SECONDS * 1000)
        if self.on_demand == "results":
            self.on_demand = ""
            self.onDemandChanged.emit()
        self.update_feed()
        self.update_laps()

    def update_clock(self, session_time: float):
        now = time.time()
        if self.session_time >= 0 and session_time >= 0 and now - self.time_received > 0.2:
            rate = (session_time - self.session_time) / (now - self.time_received)
            self.replay_rate = rate if abs(rate) < 50 else 0.0
        self.session_time, self.time_received = session_time, now
        self.clockChanged.emit()

    def count_incidents(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for incident in merge_contacts(self.contacts):
            for name in (incident.driver, incident.other):
                if name != IMMOVABLE:
                    counts[name] = counts.get(name, 0) + 1
        return counts

    def follow_game_focus(self, focus: int):
        """Car followed by game camera: another car chosen in game (or elsewhere) is an operator cut"""
        self.focus = focus
        if focus < 0 or focus == self.on_air_slot or time.monotonic() - self.last_cut < FOCUS_GRACE:
            return
        if self.follow_game_cuts:  # operator in game: director held a while
            self.director.manual(focus, "", time.monotonic())
        elif self.director.shot is not None:  # another app cuts too: car followed, director goes on
            self.director.shot = self.director.shot._replace(slot=focus)
        self.set_on_air(focus, GAME_FOCUS)

    # Director
    def direct(self):
        """Stories worth showing listed, best one cut to in automatic mode"""
        recent = [event for event in self.events[-200:] if self.session_time - event.time <= RECENT]
        clock = time.monotonic()
        race = dr.is_race(self.session_key[1])
        leader = next((car for car in self.standings if car.position == 1), None)
        phase = self.session_info.phase
        start = phase in dr.START_PHASES or (phase == dr.GREEN_PHASE and leader is not None and leader.laps < 1)
        gained = {slot: place - self.places.get(slot, place) for slot, place in self._grid.items()} if race else {}
        self.candidates = self.director.candidates(recent, list(self.watcher.battles.values()), self.standings,
                                                   self.session_time, clock, race, start, self.watcher.severity,
                                                   seen=self.seen, gained=gained)
        if self.mode == "auto" and not self.locked:
            pick = self.director.decide(self.candidates, clock)
            if pick is not None:
                self.cut(self.director.take(pick, clock))
        if self._shown:
            self.update_suggestions()

    def cut(self, shot: dr.Shot):
        """Car & camera of shot on air: commands to game, overlays follow if wanted"""
        commands: list[gc.Command] = []
        if shot.slot != self.focus:
            commands.append(gc.focus_command(shot.slot))
        if shot.camera and shot.camera != self.camera_key():
            commands.extend(gc.camera_commands(shot.camera))
            self.trackside_choice = shot.camera if shot.camera.startswith("TRACKSIDE") else ""
        if commands:
            self.last_cut = time.monotonic()
            self.send(*commands)
        self.focus = shot.slot
        if shot.key in self.event_index and shot.key not in self.seen:
            self.seen.add(shot.key)
            if self._shown:
                self.update_feed()
        self.set_on_air(shot.slot, shot.kind)
        if self.follow_overlays:
            self.overlays_follow(shot.slot)

    def set_on_air(self, slot: int, kind: str):
        if slot != self.on_air_slot or kind != self.on_air_kind:
            if slot != self.on_air_slot:
                self.on_air_start = time.time()
                self.cut_count += 1
            self.on_air_slot, self.on_air_kind = slot, kind
            self.publish_graphics()
            if self._shown:
                self.update_on_air()
                self.update_cars()

    @staticmethod
    def overlays_follow(slot: int):
        """Overlays (stream sources too) show the car on air: spectate mode on that car"""
        from ...api_control import api

        if cfg.api["player_index"] == slot and cfg.api["enable_player_index_override"]:
            return
        cfg.api["player_index"] = slot
        cfg.api["enable_player_index_override"] = True
        cfg.save()
        api.setup()
        app_signal.refresh.emit(True)

    def send(self, *commands: gc.Command):
        """Commands to game in background, in order, after commands sent before"""
        if commands:
            self.command_queue.append(commands)
        if self.request_command.busy or not self.command_queue:
            return
        batch = self.command_queue.pop(0)
        address = self.game_address()
        self.request_command.start(lambda: gc.send_commands(batch, address))

    def command_done(self, accepted: bool):
        if self.instant_waiting and not self.command_queue:  # instant replay playing: back to live after it
            self.instant_waiting = False
            if self.instant and not accepted:  # game refused the replay: live again at once
                self.backToLive()
            if self.instant:
                self._instant_timer.start(int((self.seconds_before + self.post_roll) * 1000))
        if not accepted:
            self.notify(tr("Game did not accept the command"), True)
        if self.command_queue:
            self.send()

    def command_failed(self):
        self.command_done(False)

    def camera_key(self) -> str:
        return gc.camera_key(*self.camera, self.trackside_choice) if self.state in (SESSION, REPLAY) else ""

    def can_command(self) -> bool:
        return self.state in (SESSION, REPLAY)

    # Texts
    def event_texts(self, event: dr.Event) -> tuple[str, str]:
        """Title & detail of event, made once (when its cars are known)"""
        texts = self._texts.get(event.key)
        if texts is None:
            texts = self.make_event_texts(event)
            if all(slot in self.by_slot for slot in event.slots):
                self._texts[event.key] = texts
        return texts

    def make_event_texts(self, event: dr.Event) -> tuple[str, str]:
        cars = [self.by_slot.get(slot) for slot in event.slots]
        first = car_label(cars[0] if cars else None, event.drivers[0] if event.drivers else "")
        second = car_label(cars[1] if len(cars) > 1 else None, event.drivers[1] if len(event.drivers) > 1 else "")
        place = f"P{event.position} {event.car_class}".strip() if event.position else event.car_class
        kind = event.kind
        if kind == dr.BATTLE:
            return tr("Battle for P%1").replace("%1", str(event.position)), \
                f"{first} · {second} · {seconds_text(event.value)} · {event.car_class}"
        if kind == dr.OVERTAKE:
            return tr("%1 passes %2").replace("%1", first).replace("%2", second), place
        if kind == dr.LEAD:
            return tr("%1 takes the lead").replace("%1", first), f"{event.car_class} · {second}"
        if kind == dr.CONTACT:
            return tr("Contact: %1 and %2").replace("%1", first).replace("%2", second), \
                tr("%1 contacts").replace("%1", str(int(event.value))) if event.value > 1 else event.car_class
        if kind == dr.WALL:
            return tr("%1 hits the wall").replace("%1", first), event.car_class
        if kind == dr.STOPPED:
            return tr("%1 stopped on track").replace("%1", first), place
        if kind == dr.PIT_IN:
            return tr("%1 enters the pits").replace("%1", first), place
        if kind == dr.PIT_OUT:
            stop = f" · {tr('Stopped %1').replace('%1', seconds_text(event.extra))}" if event.extra > 0 else ""
            return tr("%1 leaves the pits").replace("%1", first), \
                f"{place} · {tr('%1 in pit lane').replace('%1', seconds_text(event.value))}{stop}"
        if kind == dr.FASTEST:
            return tr("Fastest lap: %1").replace("%1", first), f"{lap_text(event.value)} · {event.car_class}"
        if kind == dr.FINISH:
            return tr("%1 finishes").replace("%1", first), place
        if kind == dr.WINNER:
            return tr("%1 wins").replace("%1", first), event.car_class
        if kind == dr.RETIRED:
            text = "%1 disqualified" if event.value > 0 else "%1 retires"
            return tr(text).replace("%1", first), place
        if kind == dr.PENALTY:
            return tr("Penalty for %1").replace("%1", first), \
                tr("%1 pending").replace("%1", str(int(event.value)))
        if kind == dr.SLOW:
            return tr("%1 slow on track").replace("%1", first), place
        if kind == dr.YELLOW:
            return tr("Yellow flag in sector %1").replace("%1", str(int(event.value))), \
                tr("Slowest car: %1").replace("%1", first) if event.slots else ""
        if kind == dr.FCY:
            return tr("Full course yellow"), ""
        if kind == dr.GREEN:
            return tr("Green flag: racing again"), ""
        return first, ""

    def candidate_texts(self, candidate: dr.Candidate) -> tuple[str, str]:
        if candidate.event is not None:
            return self.event_texts(candidate.event)
        car = self.by_slot.get(candidate.slot)
        if candidate.battle is not None:
            battle = candidate.battle
            ahead = self.by_slot.get(battle.ahead)
            return tr("Battle for P%1").replace("%1", str(battle.position)), \
                f"{car_label(car)} → {car_label(ahead)} · {seconds_text(battle.gap)}"
        place = self.places.get(candidate.slot, 0)
        if candidate.kind == dr.START:
            return tr("Race start: %1 leads").replace("%1", car_label(car)), \
                f"P{place} {car.car_class}" if car is not None else ""
        return car_label(car), f"P{place} {car.car_class}" if car is not None else ""

    # Models
    def add_events(self, events: list[dr.Event]):
        for event in events:
            if event.key in self.event_index:
                continue
            self.event_index[event.key] = event
            self.events.append(event)
        if len(self.events) > dr.FEED_LIMIT:
            for event in self.events[:-dr.FEED_LIMIT]:
                self.event_index.pop(event.key, None)
            del self.events[:-dr.FEED_LIMIT]
        self.events.sort(key=lambda event: event.time)
        if self.log_events:
            self.write_log([event for event in events if event.live])
        if self._shown:
            self.update_feed()

    def log_path(self) -> str:
        track, session = self.session_key[:2]
        name = f"{time.strftime('%Y-%m-%d')} {safe_name(track)} {safe_name(session)}.csv"
        return os.path.join(cfg.path.config, LOG_FOLDER, name)

    def write_log(self, events: list[dr.Event]):
        """Events added to the log file of the session (race control): one line each, as they happen"""
        if not events:
            return
        path = self.log_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            new = not os.path.exists(path)
            with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as file:
                writer = csv.writer(file)
                if new:
                    writer.writerow(("Time", "Session time", "Kind", "Event", "Detail", "Class", "Cars"))
                for event in events:
                    title, detail = self.event_texts(event)
                    cars = " / ".join(car_label(self.by_slot.get(slot)) for slot in event.slots)
                    writer.writerow((time.strftime("%H:%M:%S"), clock_text(event.time), self.kind_text(event), title,
                                     detail, event.car_class, cars))
        except OSError as error:
            logger.warning("Broadcast director: events log not written: %s", error)

    def update_feed(self):
        # Made again only when events, incidents seen, filter or known cars changed (not at every answer)
        view = (len(self.events), self.events[-1].key if self.events else "", len(self.seen), self.feed_filter,
                len(self._texts), self.watcher.severity_version)
        if view == self._feed_view:
            return
        self._feed_view = view
        kinds = FEED_KINDS.get(FEED_FILTERS[self.feed_filter])
        rows = []
        for event in reversed(self.events):
            if kinds is not None and event.kind not in kinds:
                continue
            title, detail = self.event_texts(event)
            rows.append({
                "key": event.key, "timeText": clock_text(event.time), "kind": event.kind,
                "kindText": self.kind_text(event), "glyph": KIND_GLYPHS[event.kind],
                "tone": KIND_TONES.get(event.kind, "dim"), "title": title, "detail": detail, "live": event.live,
                "classColor": class_color(event.car_class) if event.car_class else "",
                "unseen": self.unseen(event), "canReplay": bool(event.slots),
            })
        if self._feed_model.sync(rows, reset_if_mostly_new=True):
            self.feedChanged.emit()

    def kind_text(self, event: dr.Event) -> str:
        """Kind of event, contacts with their severity (speed lost by the cars)"""
        lost = self.watcher.severity.get(event.key, -1.0)
        if event.kind in (dr.CONTACT, dr.WALL) and lost >= dr.HEAVY:
            return tr("Heavy Contact") if event.kind == dr.CONTACT else tr("Heavy Wall Contact")
        if event.kind in (dr.CONTACT, dr.WALL) and 0 <= lost < dr.LIGHT:
            return tr("Light Contact")
        return tr(KIND_TEXTS[event.kind])

    def unseen(self, event: dr.Event) -> bool:
        """Incident nobody looked at yet (live ones only)"""
        return event.live and event.kind in INCIDENT_KINDS and event.key not in self.seen

    def mark_seen(self, key: str):
        if key in self.event_index and key not in self.seen:
            self.seen.add(key)
            self.update_feed()

    def update_suggestions(self):
        rows = []
        shot = self.director.shot
        on_air = shot.key if shot is not None and shot.slot == self.on_air_slot else ""
        waiting = [candidate for candidate in self.candidates if candidate.key != on_air]  # story on air left out
        stories = [candidate for candidate in waiting if candidate.kind != dr.ROAM]
        shown = stories[:SUGGESTIONS] if stories else waiting[:3]
        for index, candidate in enumerate(shown):
            car = self.by_slot.get(candidate.slot)
            title, detail = self.candidate_texts(candidate)
            rows.append({
                "key": candidate.key, "slot": candidate.slot, "kind": candidate.kind,
                "kindText": tr(KIND_TEXTS[candidate.kind]), "glyph": KIND_GLYPHS[candidate.kind],
                "tone": KIND_TONES.get(candidate.kind, "dim"), "title": title, "detail": detail,
                "number": car.number if car is not None else "",
                "classColor": class_color(car.car_class) if car is not None else "",
                "score": round(max(min(candidate.score, 100.0), 0.0)), "best": index == 0,
            })
        if self._suggestions_model.sync(rows):
            self.suggestionsChanged.emit()

    def update_cars(self):
        counts: dict[str, int] = {}
        for car in self.standings:
            counts[car.car_class] = counts.get(car.car_class, 0) + 1
        class_list = [{"name": name, "color": class_color(name), "count": count} for name, count in counts.items()]
        if class_list != self._class_list:
            self._class_list = class_list
            if self.class_filter and self.class_filter not in counts:
                self.class_filter = ""
            self.classFilterChanged.emit()
        fastest: dict[str, float] = {}
        for car in self.standings:
            if car.best > 0 and (fastest.get(car.car_class, 0.0) <= 0 or car.best < fastest[car.car_class]):
                fastest[car.car_class] = car.best
        in_battle = {slot for battle in self.watcher.battles.values() for slot in (battle.ahead, battle.behind)}
        ahead_of = self.class_ahead()
        personal, class_best = self.watcher.best_sectors(self.standings)
        grid = self.class_grid() if dr.is_race(self.session_key[1]) else {}
        rows = []
        for car in self.standings:
            if (self.class_filter and car.car_class != self.class_filter) or not self.matches(car):
                continue
            status, tone = status_text(car)
            ahead = ahead_of.get(car.slot)
            seconds, laps = interval(ahead, car, self.track_length) if ahead is not None else (-1.0, 0)
            sectors = self.shown_sectors(car)
            bests, class_bests = personal.get(car.slot, [-1.0] * 3), class_best.get(car.car_class, [-1.0] * 3)
            tones = [sector_tone(value, bests[index], class_bests[index]) for index, value in enumerate(sectors)]
            rows.append({
                "intervalTone": gap_tone(seconds) if laps == 0 else "",
                "gained": grid[car.slot] - self.places.get(car.slot, 0) if car.slot in grid else 0,
                "s1Tone": tones[0], "s2Tone": tones[1], "s3Tone": tones[2],
                "sectorTip": " · ".join(f"S{index} {lap_text(value) if value >= 60 else localized(f'{value:.3f}')}"
                                        for index, value in enumerate(sectors, 1) if value > 0),
                "key": str(car.slot), "slot": car.slot, "position": car.position,
                "classPosition": self.places.get(car.slot, 0), "number": car.number, "driver": car.driver,
                "team": car.team or car.vehicle, "carClass": car.car_class, "classColor": class_color(car.car_class),
                "interval": interval_text(ahead_of.get(car.slot), car, self.track_length),
                "laps": car.laps, "best": lap_text(car.best), "last": lap_text(car.last),
                "fastest": car.best > 0 and car.best == fastest.get(car.car_class), "pits": car.pitstops,
                "status": status, "statusTone": tone, "onAir": car.slot == self.on_air_slot,
                "battle": car.slot in in_battle, "incidents": self.incident_counts.get(car.driver, 0),
                "selected": car.slot == self.selected,
                "brandLogo": self.logos.brand(car.vehicle),
                "tyreFront": self.tyres.get(car.slot, ("", ""))[0], "tyreRear": self.tyres.get(car.slot, ("", ""))[1],
            })
        if self._cars_model.sync(rows):
            self.carsChanged.emit()

    def shown_sectors(self, car: Standing) -> tuple[float, float, float]:
        """Sectors of the lap being driven when done (as they complete), else of last lap"""
        current = dr.current_sectors(car)
        last = dr.last_sectors(car)
        if current[0] > 0:
            return current[0], current[1], -1.0
        return last

    def class_grid(self) -> dict[int, int]:
        """Class place on the starting grid of each car (slot), from qualifying places of the game"""
        return self._grid

    def class_ahead(self) -> dict[int, Standing]:
        """Car ahead in class of each car (slot)"""
        return self._fronts

    def matches(self, car: Standing) -> bool:
        """Car found by search words: number (from its start, "7" finds #7 & #77) or driver, team, car, class"""
        if not self.search_words:
            return True
        text = fold(f"{car.driver} {car.team} {car.vehicle} {car.car_class}")
        return all(car.number.startswith(word.lstrip("#")) or word in text for word in self.search_words)

    def update_battles(self):
        rows = []
        battles = sorted(self.watcher.battles.values(), key=lambda battle: (battle.position, battle.gap))
        for battle in battles:
            ahead, behind = self.by_slot.get(battle.ahead), self.by_slot.get(battle.behind)
            rows.append({
                "key": f"{battle.ahead}-{battle.behind}", "behindSlot": battle.behind, "carClass": battle.car_class,
                "classColor": class_color(battle.car_class), "position": battle.position,
                "ahead": car_label(ahead), "behind": car_label(behind), "gap": seconds_text(battle.gap),
                "trend": -1 if battle.trend < -0.02 else 1 if battle.trend > 0.02 else 0,
                "duration": clock_text(max(self.session_time - battle.since, 0.0)),
                "onAir": battle.behind == self.on_air_slot or battle.ahead == self.on_air_slot,
                "gapTone": gap_tone(battle.gap),
                "trendText": self.trend_text(battle, behind),
            })
        if self._battles_model.sync(rows):
            self.battlesChanged.emit()

    @staticmethod
    def trend_text(battle: dr.Battle, behind: Standing | None) -> str:
        """Gap change per lap of a battle: "-0.3 s/lap" closing, "" if steady or unknown"""
        lap_time = next((value for value in (behind.last, behind.best) if value > 0), 0.0) if behind else 0.0
        per_lap = battle.trend * lap_time
        if lap_time <= 0 or abs(per_lap) < 0.05:
            return ""
        return tr("%1/lap").replace("%1", f"{'+' if per_lap > 0 else '-'}{seconds_text(abs(per_lap))}")

    def update_classes(self):
        rows = []
        by_class: dict[str, list[Standing]] = {}
        for car in self.standings:
            by_class.setdefault(car.car_class, []).append(car)
        battles: dict[str, int] = {}
        for battle in self.watcher.battles.values():
            battles[battle.car_class] = battles.get(battle.car_class, 0) + 1
        for name, cars in by_class.items():
            leader = cars[0]
            timed = [car for car in cars if car.best > 0]
            best = min(timed, key=lambda car: car.best) if timed else None
            rows.append({
                "key": name, "name": name or tr("Unknown"), "classColor": class_color(name), "count": len(cars),
                "leader": leader.driver, "leaderNumber": leader.number,
                "bestLap": lap_text(best.best) if best is not None else "-",
                "bestDriver": car_label(best) if best is not None else "", "battles": battles.get(name, 0),
            })
        if self._classes_model.sync(rows):
            self.classesChanged.emit()

    def update_pits(self):
        ordered: list[tuple[tuple[bool, float, int], dict]] = []  # in pit lane first, then latest stop
        for car in self.standings:
            stops = self.watcher.pit_stops.get(car.slot, [])
            if not stops and car.pitstops <= 0 and not car.in_pit:
                continue
            last = stops[-1] if stops else None
            if last is None:
                last_text = ""
            elif last.duration > 0:
                last_text = tr("Lap %1").replace("%1", str(last.lap)) + f" · {seconds_text(last.duration)}"
                if last.stopped > 0:
                    last_text += f" · {tr('Stopped %1').replace('%1', seconds_text(last.stopped))}"
            else:
                last_text = tr("Lap %1").replace("%1", str(last.lap))
            status, _ = status_text(car)
            state = self.watcher.cars.get(car.slot)
            if car.in_pit and not car.garage and state is not None and state.pit_since >= 0:
                lane = max(self.session_time - state.pit_since, 0.0)
                status = tr("Pit lane %1").replace("%1", seconds_text(lane, 0))
                if car.pit_state == "STOPPED" and state.box_since >= 0:
                    stopped = state.box_time + max(self.session_time - state.box_since, 0.0)
                    status += f" · {tr('Stopped %1').replace('%1', seconds_text(stopped, 0))}"
            ordered.append(((not car.in_pit, -(last.time if last is not None else -1.0), car.position), {
                "key": str(car.slot), "slot": car.slot, "number": car.number, "driver": car.driver,
                "classColor": class_color(car.car_class), "stops": car.pitstops, "lastStop": last_text,
                "stint": self.watcher.stint_laps(car), "inPit": car.in_pit, "status": status,
            }))
        ordered.sort(key=lambda item: item[0])
        if self._pits_model.sync([row for _, row in ordered]):
            self.pitsChanged.emit()

    def update_sheet(self):
        car = self.by_slot.get(self.selected)
        if car is None:
            sheet: dict[str, Any] = {}
        else:
            fronts = self.class_ahead()
            ahead = fronts.get(car.slot)
            behind = next((other for other, front in fronts.items() if front.slot == car.slot), None)
            behind_car = self.by_slot.get(behind) if behind is not None else None
            status, tone = status_text(car)
            sheet = {
                "brandLogo": self.logos.brand(car.vehicle), "carPicture": car_picture_url(car.vehicle),
                "tyres": "/".join(dict.fromkeys(self.tyres.get(car.slot, ()))),
                "slot": car.slot, "driver": car.driver, "number": car.number, "team": car.team,
                "vehicle": car.vehicle, "carClass": car.car_class, "classColor": class_color(car.car_class),
                "position": car.position, "classPosition": self.places.get(car.slot, 0),
                "ahead": car_label(ahead) if ahead is not None else "",
                "intervalAhead": interval_text(ahead, car, self.track_length),
                "behind": car_label(behind_car) if behind_car is not None else "",
                "intervalBehind": interval_text(car, behind_car, self.track_length) if behind_car is not None else "",
                "best": lap_text(car.best), "last": lap_text(car.last), "laps": car.laps, "pits": car.pitstops,
                "stint": self.watcher.stint_laps(car), "incidents": self.incident_counts.get(car.driver, 0),
                "penalties": car.penalties, "status": status, "statusTone": tone,
                "note": self.notes.get(car.driver, ""), "onAir": car.slot == self.on_air_slot,
                "gained": self.class_grid().get(car.slot, 0) - self.places.get(car.slot, 0)
                if dr.is_race(self.session_key[1]) and car.grid > 0 else 0,
                "sectors": self.sector_cells(car), "energy": self.energy_text(car),
                "lapCount": len(self.watcher.laps.get(car.slot, ())),
                "history": self.history_text(car),
                "headToHead": self.head_to_head_text(car, ahead, behind_car),
            }
        if sheet != self._sheet:
            self._sheet = sheet
            self.sheetChanged.emit()

    def sector_cells(self, car: Standing) -> list[dict]:
        """Sectors shown for car: text & color"""
        personal, class_best = self.watcher.best_sectors(self.standings)
        bests, class_bests = personal.get(car.slot, [-1.0] * 3), class_best.get(car.car_class, [-1.0] * 3)
        return [{"text": localized(f"{value:.3f}") if value > 0 else "-",
                 "tone": sector_tone(value, bests[index], class_bests[index])}
                for index, value in enumerate(self.shown_sectors(car))]

    def energy_text(self, car: Standing) -> str:
        """Energy (else fuel) left, used per lap over 3 & 5 laps, laps left: "62% · 3.9%/lap (5: 4.0%) · 15 laps"
        "" if hidden"""
        left = dr.level(car)
        if left < 0:
            return ""
        parts = [f"{round(left * 100)}%"]
        three, five = self.watcher.energy_average(car.slot, 3), self.watcher.energy_average(car.slot, 5)
        if three > 0:
            per_lap = tr("%1/lap").replace("%1", f"{localized(f'{three * 100:.1f}')}%")
            if five > 0:
                per_lap += f" (5: {localized(f'{five * 100:.1f}')}%)"
            parts.append(per_lap)
            parts.append(tr("%1 laps").replace("%1", str(int(left / three))))
        return " · ".join(parts)

    def update_laps(self):
        """Lap history of the car asked (laps seen while the page watched)"""
        car = self.by_slot.get(self.laps_slot)
        records = self.watcher.laps.get(self.laps_slot, []) if car is not None else []
        personal, class_best = self.watcher.best_sectors(self.standings)
        bests = personal.get(self.laps_slot, [-1.0] * 3)
        class_bests = class_best.get(car.car_class, [-1.0] * 3) if car is not None else [-1.0] * 3
        class_lap = min((other.best for other in self.standings if car is not None
                         and other.car_class == car.car_class and other.best > 0), default=-1.0)
        view = (self.laps_slot, len(records), records[-1].lap if records else 0, tuple(bests), tuple(class_bests),
                class_lap, car.best if car is not None else 0.0)
        if view == self._laps_view:
            return
        self._laps_view = view
        rows = []
        for record in reversed(records):
            sectors = record.sectors
            rows.append({
                "key": str(record.lap), "lap": record.lap, "time": lap_text(record.time),
                "s1": localized(f"{sectors[0]:.3f}") if sectors[0] > 0 else "-",
                "s2": localized(f"{sectors[1]:.3f}") if sectors[1] > 0 else "-",
                "s3": localized(f"{sectors[2]:.3f}") if sectors[2] > 0 else "-",
                "timeTone": sector_tone(record.time, car.best if car is not None else -1.0, class_lap),
                "s1Tone": sector_tone(sectors[0], bests[0], class_bests[0]),
                "s2Tone": sector_tone(sectors[1], bests[1], class_bests[1]),
                "s3Tone": sector_tone(sectors[2], bests[2], class_bests[2]),
                "pit": record.pit, "energy": f"{localized(f'{record.energy * 100:.1f}')}%" if record.energy >= 0 else "",
                "position": record.position,
            })
        if self._laps_model.sync(rows):
            self.lapsChanged.emit()

    def update_weather(self, info: SessionState):
        self.session_info = info
        weather = [text for text in (
            tr("Air %1").replace("%1", temperature_text(info.air)) if info.air > -999 else "",
            tr("Track %1").replace("%1", temperature_text(info.track)) if info.track > -999 else "",
            tr("Rain %1").replace("%1", f"{round(info.rain * 100)}%") if info.rain > 0.005 else "",
            tr("Wet %1").replace("%1", f"{round(info.wetness * 100)}%") if info.wetness > 0.005 else "",
        ) if text]
        flag = "" if info.yellow in ("NONE", "INVALID", "") else tr("Full course yellow")
        weather = [flag, *weather] if flag else weather
        if weather != self._weather:
            self._weather = weather
            self.weatherChanged.emit()

    def update_on_air(self):
        car = self.by_slot.get(self.on_air_slot)
        if car is None:
            on_air: dict[str, Any] = {}
        else:
            kind = self.on_air_kind or dr.MANUAL
            on_air = {
                "brandLogo": self.logos.brand(car.vehicle), "carPicture": car_picture_url(car.vehicle),
                "slot": car.slot, "driver": car.driver, "number": car.number, "carClass": car.car_class,
                "classColor": class_color(car.car_class), "classPosition": self.places.get(car.slot, 0),
                "position": car.position, "kindText": tr(KIND_TEXTS.get(kind, "")),
                "glyph": KIND_GLYPHS.get(kind, ""), "tone": KIND_TONES.get(kind, "dim"),
                "startMs": self.on_air_start * 1000,
                "holdMs": self.hold_end() * 1000 if self.mode == "auto" else 0.0,
                "locked": self.locked,
                "minShotMs": self.director.settings.min_shot * 1000 if self.mode == "auto" else 0.0,
                "pitRadar": self.pit_neighbours(car)[:4],
            }
        if on_air != self._on_air:
            self._on_air = on_air
            self.onAirChanged.emit()

    def hold_end(self) -> float:
        """time.time() the director cuts again after an operator cut, 0 if not held"""
        hold = self.director.hold_until
        if hold != self._hold[0]:
            remaining = hold - time.monotonic()
            self._hold = (hold, time.time() + remaining if remaining > 0 else 0.0)
        return self._hold[1]

    # Properties
    @Property(str, notify=statusChanged)
    def gameState(self) -> str:
        return self.state

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return tr(STATE_TEXTS[self.state])

    @Property(bool, notify=statusChanged)
    def inSession(self) -> bool:
        return self.state in (SESSION, REPLAY)

    @Property(bool, notify=statusChanged)
    def replayActive(self) -> bool:
        return self.state == REPLAY

    @Property(str, notify=clockChanged)
    def sessionText(self) -> str:
        track, session = self.session_key[:2]
        if not self.can_command():
            return ""
        kind = next((text for prefix, text in SESSION_TEXTS.items() if session.upper().startswith(prefix)), "")
        return " · ".join(part for part in (track, tr(kind) if kind else session.title()) if part)

    @Property(float, notify=clockChanged)
    def sessionTime(self) -> float:
        return self.session_time

    @Property(float, notify=clockChanged)
    def timeReceived(self) -> float:
        return self.time_received * 1000

    @Property(float, notify=clockChanged)
    def clockRate(self) -> float:
        """Session seconds per second (live 1, replay its speed), 0 if unknown"""
        return self.replay_rate if self.state == REPLAY else 1.0 if self.state == SESSION else 0.0

    @Property(int, notify=modeChanged)
    def modeIndex(self) -> int:
        return MODES.index(self.mode)

    @Property(str, notify=modeChanged)
    def modeName(self) -> str:
        return self.mode

    @Property(dict, notify=onAirChanged)
    def onAir(self) -> dict:
        return self._on_air

    @Property(str, notify=cameraChanged)
    def cameraKey(self) -> str:
        return self.camera_key()

    @Property(str, notify=cameraChanged)
    def cameraLabel(self) -> str:
        key = self.camera_key()
        entry = next((entry for entry in gc.CAMERAS if entry[0] == key), None)
        if entry is None:
            return f"{tr(gc.camera_group(self.camera[0]))} · {self.camera[1]}" if self.camera[1] else ""
        return f"{tr(entry[2])} · {tr(entry[1]).replace('%1', str(entry[4]))}"

    @Property(list, constant=True)
    def cameras(self) -> list[dict]:
        """Cameras of camera desk: key, label, group"""
        return [{"key": key, "text": tr(label).replace("%1", str(group_number)), "group": group,
                 "groupText": tr(group)}
                for key, label, group, _, group_number in gc.CAMERAS]

    @Property(QObject, constant=True)
    def carRows(self) -> DictListModel:
        return self._cars_model

    @Property(int, notify=carsChanged)
    def carCount(self) -> int:
        return len(self.standings)

    @Property(list, notify=classFilterChanged)
    def classes(self) -> list[dict]:
        return self._class_list

    @Property(str, notify=classFilterChanged)
    def classFilter(self) -> str:
        return self.class_filter

    @Property(QObject, constant=True)
    def suggestionRows(self) -> DictListModel:
        return self._suggestions_model

    @Property(QObject, constant=True)
    def feedRows(self) -> DictListModel:
        return self._feed_model

    @Property(int, notify=feedChanged)
    def feedFilter(self) -> int:
        return self.feed_filter

    @Property(QObject, constant=True)
    def battleRows(self) -> DictListModel:
        return self._battles_model

    @Property(int, notify=battlesChanged)
    def battleCount(self) -> int:
        return len(self.watcher.battles)

    @Property(QObject, constant=True)
    def classRows(self) -> DictListModel:
        return self._classes_model

    @Property(QObject, constant=True)
    def pitRows(self) -> DictListModel:
        return self._pits_model

    @Property(dict, notify=sheetChanged)
    def sheet(self) -> dict:
        return self._sheet

    @Property(str, notify=noticeChanged)
    def noticeText(self) -> str:
        return self.notice

    @Property(bool, notify=noticeChanged)
    def noticeError(self) -> bool:
        return self.notice_error

    @Property(str, notify=statusChanged)
    def lastCommand(self) -> str:
        return self.last_command

    @Property(bool, notify=lockChanged)
    def carLocked(self) -> bool:
        return self.locked

    @Property(int, notify=feedChanged)
    def unseenCount(self) -> int:
        return sum(1 for event in self.events if self.unseen(event))

    @Property(bool, notify=instantChanged)
    def instantReplay(self) -> bool:
        return self.instant

    @Property(list, notify=weatherChanged)
    def weather(self) -> list[str]:
        """Full course yellow, air & track temperatures, rain, wet track"""
        return self._weather

    @Property(QObject, constant=True)
    def lapRows(self) -> DictListModel:
        return self._laps_model

    @Property(bool, notify=lapsChanged)
    def lapsOpen(self) -> bool:
        return self.laps_slot >= 0

    @Property(str, notify=lapsChanged)
    def lapsTitle(self) -> str:
        return car_label(self.by_slot.get(self.laps_slot))

    @Property(int, notify=settingsChanged)
    def postRoll(self) -> int:
        return self.post_roll

    # Settings
    @Property(float, notify=settingsChanged)
    def minShot(self) -> float:
        return self.director.settings.min_shot

    @Property(float, notify=settingsChanged)
    def maxShot(self) -> float:
        return self.director.settings.max_shot

    @Property(float, notify=settingsChanged)
    def battleGap(self) -> float:
        return self.director.settings.battle_gap

    @Property(int, notify=settingsChanged)
    def cameraStyle(self) -> int:
        return dr.CAMERA_STYLES.index(self.director.settings.camera_style)

    @Property(list, constant=True)
    def cameraStyles(self) -> list[str]:
        return [tr(text) for text in CAMERA_STYLE_TEXTS]

    @Property(bool, notify=settingsChanged)
    def followOverlays(self) -> bool:
        return self.follow_overlays

    @Property(int, notify=settingsChanged)
    def secondsBefore(self) -> int:
        return self.seconds_before

    @Slot(str, float)
    def setNumber(self, name: str, value: float):
        """Director setting: minShot, maxShot, battleGap, secondsBefore"""
        settings = self.director.settings
        if name == "minShot":
            settings.min_shot = min(max(value, 3.0), 60.0)
            settings.max_shot = max(settings.max_shot, settings.min_shot)
        elif name == "maxShot":
            settings.max_shot = min(max(value, settings.min_shot, 5.0), 300.0)
        elif name == "battleGap":
            settings.battle_gap = min(max(value, 0.2), 3.0)
            self.watcher.battle_gap = settings.battle_gap
        elif name == "secondsBefore":
            self.seconds_before = int(min(max(value, 0), 60))
        elif name == "postRoll":
            self.post_roll = int(min(max(value, 0), 60))
        else:
            return
        self.save_settings()
        self.settingsChanged.emit()

    @Slot(int)
    def setCameraStyle(self, index: int):
        if 0 <= index < len(dr.CAMERA_STYLES):
            self.director.settings.camera_style = dr.CAMERA_STYLES[index]
            self.save_settings()
            self.settingsChanged.emit()

    @Slot(bool)
    def setFollowOverlays(self, follow: bool):
        self.follow_overlays = follow
        self.save_settings()
        self.settingsChanged.emit()
        if follow and self.on_air_slot >= 0:
            self.overlays_follow(self.on_air_slot)
        elif not follow:
            self.overlays_stop_following()

    @staticmethod
    def overlays_stop_following():
        """Overlays back to the player car: spectate mode turned off (as turning the option on turned it on)"""
        from ...api_control import api

        if not cfg.api["enable_player_index_override"]:
            return
        cfg.api["enable_player_index_override"] = False
        cfg.save()
        api.setup()
        app_signal.refresh.emit(True)

    # Actions
    @Slot(int)
    def setMode(self, index: int):
        """Manual, assisted or automatic: automatic cuts at once if nothing is on air"""
        if not 0 <= index < len(MODES) or MODES[index] == self.mode:
            return
        self.mode = MODES[index]
        self.director.hold_until = 0.0
        self.save_settings()
        self.modeChanged.emit()
        self.update_on_air()
        if self.mode == "auto" and self.can_command():
            self.direct()

    @Property(str, notify=classFilterChanged)
    def searchText(self) -> str:
        return " ".join(self.search_words)

    @Slot(str)
    def setSearch(self, text: str):
        words = [fold(word) for word in text.split()]
        if words != self.search_words:
            self.search_words = words
            self.classFilterChanged.emit()
            self.update_cars()

    @Slot()
    def cutToFirstMatch(self):
        """Search confirmed (Enter): first car found on air"""
        car = next((car for car in self.standings if self.matches(car)
                    and (not self.class_filter or car.car_class == self.class_filter)), None)
        if car is not None:
            self.cutToCar(car.slot)

    @Slot(int)
    def takeSuggestionAt(self, index: int):
        """Suggestion of the list by place (keys 1 to 6)"""
        rows = self._suggestions_model.rows
        if 0 <= index < len(rows):
            self.takeSuggestion(rows[index]["key"])

    @Property(dict, notify=graphicsChanged)
    def graphicsSettings(self) -> dict:
        return self.graphics

    @Slot(str, "QVariant")
    def setGraphic(self, name: str, value: Any):
        """Graphics setting (see GRAPHICS_DEFAULTS): shown or not, numbers, choices"""
        default = GRAPHICS_DEFAULTS.get(name)
        if default is None:
            return
        if isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, int):
            low, high = GRAPHICS_LIMITS.get(name, (-1e9, 1e9))
            try:
                value = int(min(max(float(value), low), high))
            except (TypeError, ValueError):
                return
            if name in GRAPHICS_CHOICES and value not in GRAPHICS_CHOICES[name]:
                return
        elif name == "accent":
            value = str(value).strip()
            if not ACCENT.match(value):
                return
        elif name == "brandName":
            value = str(value).strip()[:BRAND_NAME_LENGTH]
        elif value not in GRAPHICS_CHOICES.get(name, ()):
            return
        if self.graphics.get(name) == value:
            return
        self.graphics = {**self.graphics, name: value}
        self.save_settings()
        self.graphicsChanged.emit()
        self.publish_graphics(force=True)

    @Slot()
    def checkGraphics(self):
        """Graphics panel opened: source address made again (stream overlays turned on or off meanwhile)"""
        self.graphicsChanged.emit()

    @Slot()
    def showDriverCard(self):
        """Driver card of the car on air shown again now"""
        self.cut_count += 1
        self.publish_graphics(force=True)

    @Property(str, notify=graphicsChanged)
    def graphicsUrl(self) -> str:
        """Address of the graphics browser source, "" while stream overlays are off"""
        return self.graphics_url()

    @staticmethod
    def graphics_url() -> str:
        from ...stream_overlay import streamoverlay

        return streamoverlay.url("/director") if streamoverlay.running else ""

    @Slot()
    def copyGraphicsUrl(self):
        from PySide6.QtGui import QGuiApplication

        url = self.graphics_url()
        if url:
            QGuiApplication.clipboard().setText(url)
            self.notify(tr("Address copied: add it as a browser source (1920 x 1080)"))

    @Slot()
    def openStreamOverlays(self):
        """Stream Overlays page (turn the server on, sources)"""
        from PySide6.QtWidgets import QWidget

        from ..tools_view import open_tool

        parent = self.parent()
        open_tool("stream_overlay_view.StreamOverlaysView", parent.window() if isinstance(parent, QWidget) else None)

    @Property(list, notify=forecastChanged)
    def forecastNodes(self) -> list[dict]:
        return self.forecast

    @Property(str, notify=settingsChanged)
    def gameHost(self) -> str:
        return self.game_host

    @Slot(str)
    def setGameHost(self, host: str):
        """Game on another computer (address), "" for this one: asked again at once on a new connection"""
        host = host.strip()
        if host == self.game_host:
            return
        self.game_host = host
        self._connection = None  # state thread makes a new connection at next request
        self.save_settings()
        self.settingsChanged.emit()
        self.refresh()

    @Property(bool, notify=settingsChanged)
    def logEvents(self) -> bool:
        return self.log_events

    @Slot(bool)
    def setLogEvents(self, log: bool):
        self.log_events = log
        self.save_settings()
        self.settingsChanged.emit()

    @Slot()
    def openLogFolder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = os.path.join(cfg.path.config, LOG_FOLDER)
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Property(bool, notify=settingsChanged)
    def followGameCuts(self) -> bool:
        return self.follow_game_cuts

    @Slot(bool)
    def setFollowGameCuts(self, follow: bool):
        self.follow_game_cuts = follow
        self.save_settings()
        self.settingsChanged.emit()

    @Slot()
    def toggleLock(self):
        """Car on air kept (automatic mode does not cut) or let go"""
        self.locked = not self.locked
        self.lockChanged.emit()
        self.update_on_air()

    @Slot()
    def markAllSeen(self):
        self.seen.update(event.key for event in self.events if event.kind in INCIDENT_KINDS)
        self.update_feed()
        self.feedChanged.emit()

    @Slot()
    def toggleAuto(self):
        self.setMode(MODES.index("assist") if self.mode == "auto" else MODES.index("auto"))

    @Slot(int)
    def cutToCar(self, slot: int):
        """Operator cut: camera on car (camera kept), director held a while"""
        if not self.can_command() or slot not in self.by_slot:
            return
        self.cut(self.director.manual(slot, "", time.monotonic()))
        self.update_on_air()

    @Slot(str)
    def selectCamera(self, key: str):
        """Operator camera on car on air (director held a while)"""
        if not self.can_command() or key not in gc.CAMERA_KEYS:
            return
        self.trackside_choice = key if key.startswith("TRACKSIDE") else ""
        self.send(*gc.camera_commands(key))
        self.last_cut = time.monotonic()
        slot = self.on_air_slot if self.on_air_slot >= 0 else self.focus
        if slot >= 0:
            self.director.manual(slot, key, time.monotonic())
            self.set_on_air(slot, dr.MANUAL)
        self.cameraChanged.emit()

    @Slot(str, int)
    def stepCamera(self, group: str, direction: int):
        """Previous (-1) or next (1) angle of camera group (Driving, Onboard, Trackside)"""
        if group in gc.CAMERA_GROUPS and self.can_command():
            self.trackside_choice = ""
            body = json.dumps({"cameraGroup": group, "direction": -1 if direction < 0 else 1})
            self.send(("POST", gc.SET_CAMERA_RESOURCE, body))
            self.last_cut = time.monotonic()

    @Slot(int)
    def stepCar(self, offset: int):
        """Operator cut to next (1) or previous (-1) car by place from the car on air"""
        ordered = [car.slot for car in self.standings if not self.class_filter or car.car_class == self.class_filter]
        if not ordered:
            return
        current = self.on_air_slot if self.on_air_slot >= 0 else self.focus
        if current in ordered:
            target = ordered[(ordered.index(current) + offset) % len(ordered)]
        else:
            target = ordered[0] if offset > 0 else ordered[-1]
        self.cutToCar(target)

    @Slot(str)
    def takeSuggestion(self, key: str):
        """Story cut to by operator: shown at least the shortest shot"""
        candidate = next((candidate for candidate in self.candidates if candidate.key == key), None)
        if candidate is None or not self.can_command():
            return
        clock = time.monotonic()
        self.cut(self.director.take(candidate, clock))
        self.director.hold_until = clock + self.director.settings.min_shot
        self.update_on_air()
        self.update_suggestions()

    @Slot()
    def takeBest(self):
        best = next((candidate for candidate in self.candidates if candidate.slot != self.on_air_slot), None)
        if best is not None:
            self.takeSuggestion(best.key)

    @Slot(str)
    def showEvent(self, key: str):
        """Event of feed shown: replay goes a little before it with the camera on its car, live: camera on car"""
        event = self.event_index.get(key)
        if event is None or not event.slots or not self.can_command():
            return
        slot = event.slots[0]
        if slot not in self.by_slot:
            return
        clock = time.monotonic()
        camera = "" if self.director.settings.camera_style == "keep" else self.director.camera_for(event.kind)
        shot = self.director.manual(slot, camera, clock)
        self.cut(shot)
        self.mark_seen(key)
        if self.state == REPLAY:
            self.send(("PUT", f"/rest/watch/replaytime/{max(int(event.time) - self.seconds_before, 0)}"))
        self.update_on_air()

    @Slot(str)
    def replayEvent(self, key: str):
        """Instant replay (live session): the game goes to the replay of the session a little before the event,
        camera on its car, plays it, then back to live after the event (in a replay: same as showEvent)"""
        event = self.event_index.get(key)
        if event is None or not event.slots or event.slots[0] not in self.by_slot:
            return
        if self.state == REPLAY and not self.instant:
            self.showEvent(key)
            return
        if self.state != SESSION and not self.instant:
            return
        slot = event.slots[0]
        self.mark_seen(key)
        self.instant = True
        self.instant_event = event
        self.instantChanged.emit()
        camera = "" if self.director.settings.camera_style == "keep" else self.director.camera_for(event.kind)
        self.director.manual(slot, camera, time.monotonic())
        self.last_cut = time.monotonic()
        commands: list[gc.Command] = [gc.enter_replay,
                                      gc.seek_replay(int(event.time) - self.seconds_before, slot),
                                      *gc.camera_commands(camera), ("PUT", f"/rest/watch/replayCommand/{gc.PLAY}")]
        self.instant_waiting = True  # back to live counted from when the replay plays there
        self.send(*commands)
        self.set_on_air(slot, event.kind)
        self._instant_timer.start(int(INSTANT_LIMIT * 1000))

    @Slot()
    def backToLive(self):
        """Instant replay over: live session shown again (director goes on)"""
        self._instant_timer.stop()
        if not self.instant:
            return
        self.instant = False
        self.instant_event = None
        self.instantChanged.emit()
        self.last_cut = time.monotonic()
        self.director.hold_until = time.monotonic() + self.director.settings.urgent_after
        self.send(gc.leave_replay)

    @Slot()
    def exportEvents(self):
        """Race events saved as a CSV file (session time, kind, title, detail, class, cars)"""
        from PySide6.QtWidgets import QFileDialog, QWidget

        parent = self.parent()
        track, session = self.session_key[:2]
        name = "-".join(part for part in (track, session, time.strftime("%Y-%m-%d-%H%M")) if part)
        path, _ = QFileDialog.getSaveFileName(parent if isinstance(parent, QWidget) else None,
                                              tr("Export Events"), f"{name}.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(("Session time", "Kind", "Event", "Detail", "Class", "Cars"))
                for event in self.events:
                    title, detail = self.event_texts(event)
                    cars = " / ".join(car_label(self.by_slot.get(slot)) for slot in event.slots)
                    writer.writerow((clock_text(event.time), tr(KIND_TEXTS[event.kind]), title, detail,
                                     event.car_class, cars))
        except OSError as error:
            self.notify(f"{tr('Events not saved')}: {error}", True)
            return
        self.notify(tr("Events saved"))

    @Slot(int)
    def showLaps(self, slot: int):
        """Lap history of car (-1: closed)"""
        self.laps_slot = slot
        self._laps_model.reset([])
        self.update_laps()
        self.lapsChanged.emit()

    @Slot(int)
    def selectCar(self, slot: int):
        """Car of sheet (no cut)"""
        self.selected = slot if slot != self.selected else -1
        self.update_sheet()
        self.update_cars()

    @Slot(str)
    def setNote(self, text: str):
        """Note of commentator on driver of sheet, kept between sessions"""
        car = self.by_slot.get(self.selected)
        if car is None:
            return
        text = text.strip()
        if text:
            self.notes[car.driver] = text
        else:
            self.notes.pop(car.driver, None)
        self.save_settings()
        self.update_sheet()

    @Slot(str)
    def setClassFilter(self, name: str):
        self.class_filter = "" if name == self.class_filter else name
        self.classFilterChanged.emit()
        self.update_cars()

    @Slot(int)
    def setFeedFilter(self, index: int):
        if 0 <= index < len(FEED_FILTERS) and index != self.feed_filter:
            self.feed_filter = index
            self._feed_model.reset([])
            self._feed_view = None
            self.update_feed()
            self.feedChanged.emit()

    @Slot(str)
    def playback(self, command: str):
        if command in gc.PLAYBACK_COMMANDS and self.state == REPLAY:
            self.last_command = command
            self.statusChanged.emit()
            self.send(("PUT", f"/rest/watch/replayCommand/{command}"))

    @Slot()
    def togglePlay(self):
        self.playback(gc.PAUSE if self.last_command not in ("", gc.PAUSE) else gc.PLAY)

    @Slot(int)
    def jump(self, seconds: int):
        """Replay moves back (negative) or forward"""
        if self.state == REPLAY and self.session_time >= 0:
            self.send(("PUT", f"/rest/watch/replaytime/{max(int(self.session_time + seconds), 0)}"))

    # On demand graphics: starting grid, event card, classification, championship
    @Property(str, notify=onDemandChanged)
    def onDemand(self) -> str:
        return self.on_demand

    @Slot(str)
    def showOnDemand(self, name: str):
        """Graphic shown by the operator (the same name again: hidden), one at a time"""
        if name not in ON_DEMAND:
            name = ""
        name = "" if name == self.on_demand else name
        self.auto_shown = ""  # operator takes over
        if name == "results" and self.captured is None:
            self.captured = self.results_state()
        self.on_demand = name
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Property(str, notify=onDemandChanged)
    def captureText(self) -> str:
        """When the classification shown was captured, "" if none"""
        return self.captured["subtitle"] if self.captured is not None else ""

    @Slot()
    def captureResults(self):
        """Classification now captured & shown (stays as it is until captured again)"""
        self.captured = self.results_state()
        self.on_demand = "results"
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Slot()
    def clearResults(self):
        self.captured = None
        if self.on_demand == "results":
            self.on_demand = ""
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Property(list, notify=championshipChanged)
    def championshipNames(self) -> list[str]:
        return [item["name"] for item in self.championships]

    @Property(int, notify=championshipChanged)
    def championshipIndex(self) -> int:
        return self.championship_index if self.championships else -1

    @Property(list, notify=championshipChanged)
    def championshipClasses(self) -> list[str]:
        if not 0 <= self.championship_index < len(self.championships):
            return []
        return champ.classes(self.championships[self.championship_index]["rows"])

    @Property(str, notify=championshipChanged)
    def championshipClass(self) -> str:
        return self.championship_class

    @Slot()
    def importChampionship(self):
        """Championship standings from a CSV file (driver, points, team, class...): added, or replacing the one of
        the same name"""
        from PySide6.QtWidgets import QFileDialog, QWidget

        parent = self.parent()
        path, _ = QFileDialog.getOpenFileName(parent if isinstance(parent, QWidget) else None,
                                              tr("Import Championship"), "", "CSV (*.csv *.txt)")
        if path:
            self.import_championship(path)

    def import_championship(self, path: str) -> bool:
        try:
            with open(path, "rb") as file:
                data = file.read(2_000_000)
        except OSError as error:
            self.notify(f"{tr('Championship not imported')}: {error}", True)
            return False
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", "replace")
        rows = champ.parse_championship(text)
        if not rows:
            self.notify(tr("No driver with points found in this file"), True)
            return False
        name = os.path.splitext(os.path.basename(path))[0]
        items = [item for item in self.championships if item["name"] != name]
        items.append({"name": name, "rows": rows})
        self.championships = items
        self.championship_index = len(items) - 1
        self.championship_class = ""
        self.store_championships()
        self.notify(tr("%1 drivers imported").replace("%1", str(len(rows))))
        return True

    def store_championships(self):
        try:
            save_championships(self.championships)
        except OSError as error:
            self.notify(f"{tr('Championship not imported')}: {error}", True)
        self.save_settings()
        self.championshipChanged.emit()
        if self.on_demand == "champ":
            self.publish_graphics(force=True)

    @Slot()
    def removeChampionship(self):
        if 0 <= self.championship_index < len(self.championships):
            del self.championships[self.championship_index]
            self.championship_index = max(min(self.championship_index, len(self.championships) - 1), 0)
            if not self.championships and self.on_demand == "champ":
                self.on_demand = ""
                self.onDemandChanged.emit()
            self.store_championships()

    @Slot(int)
    def setChampionship(self, index: int):
        if 0 <= index < len(self.championships) and index != self.championship_index:
            self.championship_index = index
            self.championship_class = ""
            self.store_championships()

    @Slot(str)
    def setChampionshipClass(self, name: str):
        if name != self.championship_class:
            self.championship_class = name
            self.store_championships()

    # Layout editor of the graphics (browser)
    @Slot()
    def editGraphicsLayout(self):
        """Layout editor of the graphics opened in the browser (sample data, drag to move, wheel to resize)"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ...stream_overlay import streamoverlay

        if streamoverlay.running:
            QDesktopServices.openUrl(QUrl(streamoverlay.url("/director", "edit=1")))

    @Slot()
    def resetGraphicsLayout(self):
        """Every graphic back to its place & size"""
        from ...stream_director import director_feed, director_layout

        director_layout.set("", {})
        director_feed.bump()
        self.notify(tr("Graphics back to their places"))

    # Timing table
    @Property(QObject, constant=True)
    def timingRows(self) -> QObject:
        return self._timing_model

    @Property(int, notify=timingColumnsChanged)
    def timingViewIndex(self) -> int:
        return list(TIMING_VIEWS).index(self.timing_view)

    @Property(list, notify=timingColumnsChanged)
    def timingColumns(self) -> list[dict]:
        """Columns of the view shown: key, title, width (em), alignment"""
        return [{"key": key, "title": tr(TIMING_COLUMNS[key][0]), "width": TIMING_COLUMNS[key][1],
                 "align": TIMING_COLUMNS[key][2]} for key in self.timing_columns[self.timing_view]]

    @Property(list, notify=timingColumnsChanged)
    def timingChoices(self) -> list[dict]:
        """Every column: key, title, shown in the view"""
        shown = self.timing_columns[self.timing_view]
        return [{"key": key, "title": tr(title), "shown": key in shown} for key, (title, _, _) in TIMING_COLUMNS.items()]

    @Slot(bool)
    def setTimingOpen(self, shown: bool):
        """Timing table shown: rows made at each answer (none while closed)"""
        self.timing_open = shown
        if shown:
            self.update_timing()

    @Slot(int)
    def setTimingView(self, index: int):
        views = list(TIMING_VIEWS)
        if 0 <= index < len(views) and views[index] != self.timing_view:
            self.timing_view = views[index]
            self.save_settings()
            self.timingColumnsChanged.emit()

    @Slot(int, int)
    def moveTimingColumn(self, source: int, target: int):
        """Column of the view moved (dragged) to another place"""
        columns = self.timing_columns[self.timing_view]
        if not (0 <= source < len(columns) and 0 <= target < len(columns)) or source == target:
            return
        columns.insert(target, columns.pop(source))
        self.save_settings()
        self.timingColumnsChanged.emit()

    @Slot(str)
    def toggleTimingColumn(self, key: str):
        """Column shown or hidden in the view (one column at least stays)"""
        columns = self.timing_columns[self.timing_view]
        if key in columns:
            if len(columns) > 1:
                columns.remove(key)
        elif key in TIMING_COLUMNS:
            columns.append(key)
        else:
            return
        self.save_settings()
        self.timingColumnsChanged.emit()

    @Slot()
    def resetTimingColumns(self):
        self.timing_columns[self.timing_view] = list(TIMING_VIEWS[self.timing_view])
        self.save_settings()
        self.timingColumnsChanged.emit()

    def update_timing(self):
        """Rows of the timing table: every column of every view (columns shown chosen by the page)"""
        qualifying = self.timing_view == "qualifying"
        race = dr.is_race(self.session_key[1])
        grid = self._grid if race else {}
        fastest = self.class_fastest()
        personal, class_best = self.watcher.best_sectors(self.standings)
        in_battle: dict[int, int] = {}
        for battle in self.watcher.battles.values():
            trend = -1 if battle.trend < -0.02 else 1 if battle.trend > 0.02 else 0
            in_battle[battle.ahead] = in_battle.get(battle.ahead, trend)
            in_battle[battle.behind] = trend
        leader = self.standings[0] if self.standings else None
        slow = {event.slots[0] for event in self.events[-80:] if event.kind in (dr.SLOW, dr.STOPPED, dr.YELLOW)
                and event.slots and self.session_time - event.time < 30}
        rows = []
        for car in self.standings:
            status, tone = status_text(car)
            ahead = self._fronts.get(car.slot)
            seconds, laps = interval(ahead, car, self.track_length) if ahead is not None else (-1.0, 0)
            sectors = self.shown_sectors(car)
            bests, class_bests = personal.get(car.slot, [-1.0] * 3), class_best.get(car.car_class, [-1.0] * 3)
            tones = [sector_tone(value, bests[index], class_bests[index]) for index, value in enumerate(sectors)]
            pole = fastest.get(car.car_class, 0.0)
            if qualifying:
                gap = delta_text(car.best - pole) if car.best > 0 and pole > 0 and car.best > pole else ""
            else:
                gap = "" if car is leader else interval_text(leader, car, self.track_length)
            stops = self.watcher.pit_stops.get(car.slot, [])
            state = self.watcher.cars.get(car.slot)
            if car.in_pit and not car.garage and state is not None and state.pit_since >= 0:
                pit_time = seconds_text(max(self.session_time - state.pit_since, 0.0), 0)
            elif stops and stops[-1].duration > 0:
                pit_time = seconds_text(stops[-1].duration)
            else:
                pit_time = ""
            level = dr.level(car)
            change = grid[car.slot] - self.places.get(car.slot, 0) if car.slot in grid else 0
            tyres = [letter for letter in dict.fromkeys(self.tyres.get(car.slot, ())) if letter]
            rows.append({
                "key": str(car.slot), "slot": car.slot, "classColor": class_color(car.car_class),
                "onAir": car.slot == self.on_air_slot, "battle": car.slot in in_battle,
                "trend": in_battle.get(car.slot, 0), "yellow": car.slot in slow,
                "energyLevel": level, "tyreList": tyres,
                "intervalTone": gap_tone(seconds) if laps == 0 else "", "gapTone": "",
                "bestTone": "fastest" if car.best > 0 and car.best <= pole + 0.0005 else "",
                "lastTone": sector_tone(car.last, car.best, pole), "s1Tone": tones[0], "s2Tone": tones[1],
                "s3Tone": tones[2], "changeValue": change, "statusTone": tone,
                "pos": str(car.position), "classPos": str(self.places.get(car.slot, 0)),
                "change": (f"▲{change}" if change > 0 else f"▼{-change}") if change else "",
                "number": f"#{car.number}" if car.number else "", "driver": car.driver,
                "team": car.team or car.vehicle, "laps": str(car.laps),
                "interval": interval_text(ahead, car, self.track_length), "gap": gap,
                "best": lap_text(car.best), "last": lap_text(car.last),
                "s1": localized(f"{sectors[0]:.3f}") if sectors[0] > 0 else "",
                "s2": localized(f"{sectors[1]:.3f}") if sectors[1] > 0 else "",
                "s3": localized(f"{sectors[2]:.3f}") if sectors[2] > 0 else "",
                "pits": str(car.pitstops), "stint": str(self.watcher.stint_laps(car))
                if self.watcher.stint_laps(car) >= 0 else "",
                "pitTime": pit_time, "energy": f"{round(level * 100)}%" if level >= 0 else "",
                "tyres": "/".join(tyres), "penalties": str(car.penalties) if car.penalties else "",
                "status": status,
            })
        if self._timing_model.sync(rows):
            self.timingChanged.emit()

    # Graphics shown by the director itself: starting grid before the start, event card, classification at the end
    def auto_graphics(self, new_events: list[dr.Event]):
        race = dr.is_race(self.session_key[1])
        phase = self.session_info.phase
        settings = self.graphics
        if race and settings["autoGrid"] and phase in dr.START_PHASES and "grid" not in self._auto_done:
            self._auto_done.add("grid")
            self.show_auto("grid")
        elif self.auto_shown == "grid" and phase >= dr.GREEN_PHASE:  # race started
            self.hide_auto("grid")
        if (race and settings["autoResults"] and "results" not in self._auto_done
                and any(event.kind == dr.WINNER and event.live for event in new_events)):
            self._auto_done.add("results")
            self.captured = self.results_state()
            self.show_auto("results")
        elif self.auto_shown == "results":  # cars still finishing: classification kept up to date
            self.captured = self.results_state()

    def show_auto(self, name: str):
        """On demand graphic shown by the director, unless the operator shows another one"""
        if self.on_demand and self.on_demand != self.auto_shown:
            return
        self.on_demand = self.auto_shown = name
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    def hide_auto(self, name: str):
        if self.on_demand == name and self.auto_shown == name:
            self.on_demand = ""
            self.onDemandChanged.emit()
            self.publish_graphics(force=True)
        if self.auto_shown == name:
            self.auto_shown = ""

    def end_auto_event(self):
        self.hide_auto("event")

    # Message of the operator & countdown
    @Property(str, notify=onDemandChanged)
    def messageText(self) -> str:
        return self.message["text"] if self.message is not None else ""

    @Slot(str, str)
    def showMessage(self, title: str, text: str):
        """Message on the graphics (lower third) until hidden: title (race control, commentators...) & text"""
        text = " ".join(text.split())[:MESSAGE_LENGTH]
        if not text:
            self.hideMessage()
            return
        count = self.message["id"] + 1 if self.message is not None else 1
        self.message = {"id": count, "title": " ".join(title.split())[:40], "text": text}
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Slot()
    def hideMessage(self):
        self.message = None
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    def countdown_state(self) -> dict[str, Any] | None:
        if self.countdown_end <= time.time():
            return None
        return {"label": self.countdown_label or tr("Race starts in"), "endsAt": round(self.countdown_end * 1000)}

    @Property(bool, notify=onDemandChanged)
    def countdownRunning(self) -> bool:
        return self.countdown_end > time.time()

    @Slot(float, str)
    def startCountdown(self, minutes: float, label: str):
        """Countdown on the graphics until a time (minutes from now), with a text"""
        seconds = min(max(float(minutes) * 60, 1.0), COUNTDOWN_LIMIT)
        self.countdown_end = time.time() + seconds
        self.countdown_label = " ".join(label.split())[:60]
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    @Slot()
    def stopCountdown(self):
        self.countdown_end = 0.0
        self.onDemandChanged.emit()
        self.publish_graphics(force=True)

    # League branding: name, logo, sponsors pictures (config folder)
    def brand_state(self) -> dict[str, Any]:
        from ...stream_director import brand_pictures

        now = time.monotonic()
        if now - self._brand[0] > 5:  # folder looked at again every few seconds (pictures added)
            self._brand = (now, brand_pictures())
        logo, sponsors = self._brand[1]
        return {"name": self.graphics["brandName"], "logo": logo, "sponsors": sponsors}

    @Slot()
    def chooseLogo(self):
        """League logo picked (PNG, JPG, WEBP, SVG): copied to the branding folder"""
        from PySide6.QtWidgets import QFileDialog, QWidget

        parent = self.parent()
        path, _ = QFileDialog.getOpenFileName(parent if isinstance(parent, QWidget) else None, tr("League logo"), "",
                                              "Images (*.png *.jpg *.jpeg *.webp *.svg)")
        if path:
            self.set_logo(path)

    def set_logo(self, path: str) -> bool:
        import shutil

        from ...stream_director import BRAND_TYPES, brand_folder

        extension = os.path.splitext(path)[1].lower().lstrip(".")
        if extension not in BRAND_TYPES:
            self.notify(tr("Choose a PNG, JPG, WEBP or SVG picture"), True)
            return False
        folder = brand_folder()
        try:
            os.makedirs(folder, exist_ok=True)
            self.remove_logo_files()
            shutil.copyfile(path, os.path.join(folder, f"logo.{extension}"))
        except OSError as error:
            self.notify(f"{tr('Logo not saved')}: {error}", True)
            return False
        self._brand = (0.0, self._brand[1])
        self.publish_graphics(force=True)
        return True

    @staticmethod
    def remove_logo_files():
        from ...stream_director import brand_folder

        folder = brand_folder()
        try:
            for entry in os.scandir(folder):
                if entry.is_file() and entry.name.lower().startswith("logo."):
                    os.remove(entry.path)
        except OSError:
            pass

    @Slot()
    def clearLogo(self):
        self.remove_logo_files()
        self._brand = (0.0, self._brand[1])
        self.publish_graphics(force=True)

    @Slot()
    def openSponsorsFolder(self):
        """Folder of sponsors pictures (shown in turn, file name order)"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from ...stream_director import brand_folder

        folder = os.path.join(brand_folder(), "sponsors")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self._brand = (0.0, self._brand[1])

    # Layout presets & sources with some graphics only
    @Property(list, constant=True)
    def layoutPresets(self) -> list[dict]:
        from ...stream_director import LAYOUT_PRESETS, labels

        names = labels(tr)["presets"]
        return [{"key": key, "name": names[key]} for key in LAYOUT_PRESETS]

    @Property(str, notify=graphicsChanged)
    def layoutPreset(self) -> str:
        from ...stream_director import director_layout

        return director_layout.active()

    @Slot(str)
    def setLayoutPreset(self, key: str):
        """Layout preset used by the graphics sources (those without their own preset)"""
        from ...stream_director import director_feed, director_layout

        if director_layout.set_active(key):
            director_feed.bump()
            self.graphicsChanged.emit()

    @Slot()
    def nextLayoutPreset(self):
        from ...stream_director import LAYOUT_PRESETS, director_layout, labels

        presets = list(LAYOUT_PRESETS)
        key = presets[(presets.index(director_layout.active()) + 1) % len(presets)]
        self.setLayoutPreset(key)
        self.notify(tr("Layout: %1").replace("%1", labels(tr)["presets"][key]))

    @Property(list, constant=True)
    def graphicNames(self) -> list[dict]:
        """Every graphic of the source: id & name (sources with some graphics only)"""
        from ...stream_director import GRAPHIC_IDS, labels

        names = labels(tr)["names"]
        return [{"key": key, "name": names[key]} for key in GRAPHIC_IDS]

    @Slot("QVariantList", str)
    def copyPartialUrl(self, ids: list, preset: str):
        """Address of a graphics source with some graphics only (another OBS scene or source), its own layout
        preset if given"""
        from PySide6.QtGui import QGuiApplication

        from ...stream_director import GRAPHIC_IDS, LAYOUT_PRESETS
        from ...stream_overlay import streamoverlay

        chosen = [str(key) for key in ids if key in GRAPHIC_IDS]
        if not streamoverlay.running or not chosen:
            return
        query = f"only={','.join(chosen)}"
        if preset in LAYOUT_PRESETS and preset:
            query += f"&preset={preset}"
        QGuiApplication.clipboard().setText(streamoverlay.url("/director", query))
        self.notify(tr("Address copied: add it as a browser source (1920 x 1080)"))

    # Race history of the drivers (results files read in background)
    def read_history(self):
        if self._history_busy:
            return
        self._history_busy = True

        def scan():
            from ...process.driver_history import results_folders

            try:
                driver_history.scan(results_folders())
            except Exception:  # never stop the page for a results file
                logger.exception("Broadcast director: race history not read")
            finally:
                self._history_busy = False

        threading.Thread(target=scan, daemon=True, name="Director race history").start()

    def history_text(self, car: Standing) -> str:
        """Races of the driver: starts, wins & podiums in class, best finish on this track, last races"""
        stats = driver_history.stats(car.driver, self.session_key[0])
        if stats is None:
            return ""
        parts = [tr("%1 races").replace("%1", str(stats.starts)), tr("%1 wins").replace("%1", str(stats.wins)),
                 tr("%1 podiums").replace("%1", str(stats.podiums))]
        if stats.best_here:
            parts.append(tr("Best here: P%1").replace("%1", str(stats.best_here)))
        last = ", ".join(f"{'P' + str(record.class_position) if record.finished else tr('DNF')} {record.track}"
                         for record in stats.last)
        return " · ".join(parts) + (f"  —  {tr('Last')}: {last}" if last else "")

    def head_to_head_text(self, car: Standing, *others: Standing | None) -> str:
        """Races the driver ran with the cars ahead & behind: who finished ahead"""
        parts = []
        for other in others:
            if other is None:
                continue
            ahead, behind = driver_history.head_to_head(car.driver, other.driver)
            if ahead or behind:
                parts.append(tr("vs #%1: %2").replace("%1", other.number).replace("%2", f"{ahead}-{behind}"))
        return " · ".join(parts)
