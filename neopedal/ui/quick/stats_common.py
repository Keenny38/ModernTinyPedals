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
Driver stats viewer: constants, formatting of figures & table cells (no page state)
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections.abc import Iterable, Sequence
from typing import Any, NamedTuple

from PySide6.QtCore import QUrl

from ... import units
from ...const_common import MAX_SECONDS
from ...const_file import FileExt
from ...formatter import strip_invalid_char
from ...i18n import current_language, tr, trm
from ...process import driver_ranks as dr
from ...process import results_index as ri
from ...process.results_text import (
    MISSING,
    SESSION_FILTER_LABELS,
    gap_seconds_text,
    laps_behind_text,
    laptime_text,
    place_tone,
    position_text,
)
from ...rank_info import ranks
from ...setting import cfg
from ...userfile.brands import select_brand_name
from ...userfile.driver_history import SESSION_GROUPS, SessionRecord
from ...userfile.driver_stats import (
    DriverStats,
    load_stats_backup,
    validate_stats_file,
)
from ...userfile.lap_reference import LEVELS
from ..lap_viewer import number_text
from .formatting import format_date, localized_number, temperature_text
from .game_pictures import LogoCache
from .stats_analysis import rank_chart

logger = logging.getLogger(__name__)

REFERENCE_MAX_AGE = 24 * 3600  # seconds before cached lap time reference is downloaded again
REFERENCE_KEYS = ("gap", "level")  # table columns from lap time reference, after personal best
WATCH_DELAY = 800  # milliseconds after stats or history file changed before reloading
LAPS_DELAY = 150  # milliseconds after selection changed before recorded laps are read (arrow keys: one read)
SELECTION_BURST = 0.25  # seconds: selection changed again within it (arrow key held): details shown once it settles
SELECTION_DELAY = 120  # milliseconds after last quick selection change before its details are shown
SYNC_HISTORY_BYTES = 64 * 1024  # history file read at once up to this size (a few ms), bigger one in background
SYNC_STATS_BYTES = 128 * 1024  # stats file read at once (saved every lap) up to this size, bigger one in background
RANKS_CHECK = 5_000  # milliseconds between checks of game ranks file (driver card)
HIDDEN_RELEASE_DELAY = 60_000  # milliseconds page hidden before session history is released (read again once shown)
HOME_RESET_DELAY = 120.0  # seconds page hidden before it opens on All Tracks again
LAP_FOLDERS_KEPT = 4  # recorded laps folders whose lap infos are kept (stints of selected vehicle)
MAX_UNDO = 50
ROLLBACK_ATTEMPTS = 3  # history change undone again if stats not saved
ROLLBACK_DELAY = 0.1  # seconds between attempts
MAX_SESSIONS = 200  # sessions listed for selected vehicle, newest first
ALL_TRACKS = ""  # selected track key of All Tracks (first entry of track list)
CONFIG_NAME = "driver_stats_viewer"

# Vehicle table columns: stats (DriverStats), lap time reference & figures derived from stats
VEHICLE_COLUMNS = (
    "vehicle", "pb", *REFERENCE_KEYS, "theory", "potential", "qb", "rb", "wet_pb", "version_pb",
    "meters", "seconds", "liters", "valid", "invalid", "valid_rate", "speed", "consumption",
    "penalties", "penalty_rate", "starts", "races", "wins", "podiums", "dnf", "win_rate", "podium_rate",
    "avg_finish", "gained", "clean_rate", "last",
)
HISTORY_KEYS = ("wet_pb", "version_pb", "gained", "clean_rate")  # columns from session history & results files
# All Tracks table columns: track, best lap of each class (class:name), then these totals
TRACK_TOTAL_COLUMNS = ("meters", "seconds", "valid", "races", "wins", "podiums", "last")
FIXED_COLUMNS = ("vehicle", "track")  # never hidden
LAP_TIME_COLUMNS = ("pb", "qb", "rb", "theory", "wet_pb", "version_pb")
LOWER_IS_BETTER = ("pb", "qb", "rb", "theory", "potential", "gap", "level", "avg_finish", "wet_pb", "version_pb")
DERIVED_COLUMNS = ("valid_rate", "speed", "consumption", "penalty_rate", "win_rate", "podium_rate", "avg_finish")
HEADER_KEYS = {
    "vehicle": "Vehicle", "track": "Track", "pb": "PB", "qb": "Qualifying", "rb": "Race",
    "gap": "% Ref.", "theory": "Theoretical", "potential": "Potential", "seconds": "Driving Time",
    "valid_rate": "% Valid", "speed": "Avg. Speed", "consumption": "Consumption",
    "penalty_rate": "Penalties/Race", "starts": "Starts", "races": "Finishes", "dnf": "DNF",
    "win_rate": "% Wins", "podium_rate": "% Podiums", "avg_finish": "Avg. Finish", "last": "Last Driven",
    "wet_pb": "Wet PB", "version_pb": "PB This Version", "gained": "Places Gained", "clean_rate": "% Clean",
}
HEADER_TOOLTIPS = {
    "gap": "Personal best in percent of community reference lap time",
    "level": ("Level of personal best on the community race pace ladder (in percent of class reference): "
              "qualifying & race bests are marked on the ladder of the reference card"),
    "theory": "Theoretical best: sum of best sectors of the class (all brands), from Sectors module",
    "potential": "Personal best minus theoretical best of the class (best sectors may be of another brand)",
    "starts": "Race starts (recorded since this version)",
    "dnf": "Races not finished or disqualified (recorded since this version)",
    "avg_finish": "Average finish position (recorded since this version)",
    "last": "Last session on this track (recorded since this version)",
    "wet_pb": "Best lap on a damp or wet road (road conditions recorded since this version)",
    "version_pb": "Best lap driven with the latest game version of your session history",
    "gained": "Average places gained from start to finish in races (start position recorded since this version, "
              "else from race results)",
    "clean_rate": "Races without contact nor penalty, in percent of races found in race results",
}
RAW_UNITS = {"pb": "s", "qb": "s", "rb": "s", "theory": "s", "potential": "s", "meters": "m", "seconds": "s",
             "liters": "L", "speed": "m/s", "consumption": "L/100 km", "gap": "%", "wet_pb": "s", "version_pb": "s",
             "clean_rate": "%"}
# Level colors easier to tell apart with color vision deficiency (Okabe & Ito palette)
COLORBLIND_LEVEL_COLORS = ("#CC79A7", "#0072B2", "#009E73", "#F0E442", "#E69F00", "#999999")
SESSION_NAMES = ("Test day", "Practice", "Qualifying", "Warmup", "Race")
SESSION_CODES = ("T", "P", "Q", "W", "R")  # badge letters of SESSION_NAMES
SESSION_FILTERS = SESSION_FILTER_LABELS
CONDITION_FILTERS = ("All Conditions", "Dry Road", "Wet Road")  # road of session best lap (see SessionRecord.wet)
ONLINE_FILTERS = ("Online & Offline", "Online Only", "Offline Only")
RUST_DAYS = 30  # combos not driven for this many days marked in Last Driven column
RUST_COLOR = "#D9902F"  # Last Driven of those combos (amber, darker on light theme)
UPCOMING_EVERY = 600.0  # seconds between reads of official races to come (page shown on All Tracks)
GAME_TRACKS_AGE = 60.0  # seconds a game track list read for another page is used again
GOAL_STEP = 0.5  # seconds under personal best of the suggested goal (no community lap time)
GOAL_RANGE = 0.03  # goal faster than personal best by up to this share of it: chart made taller to show it
FINISH_TEXTS = {2: "DNF", 3: "DQ"}  # race result codes, same in every language
MAX_FIX_LINES = 12  # lap times from results listed in confirmation
MAX_STINTS = 12  # stints & sessions listed with their consistency, newest first
ACTIVITY_WEEKS = 53  # weeks of daily driving activity (All Tracks), page shows the last ones that fit
ACTIVITY_STEPS = (1800, 3600, 7200)  # driving time (seconds) of activity levels 1 to 4 (above last)
RECENT_SESSIONS = 8  # latest sessions of every track (All Tracks)
STATS_TABS = 3  # page tabs: overview, progression, compare
LOGO_EM = 2.6  # room of game logo before cell text (em)
HISTORY_COLUMNS = (  # session history CSV export
    "Date", "Track", "Vehicle", "Class", "Session", "Best Lap (s)", "Valid Laps", "Invalid Laps", "Distance (m)",
    "Driving Time (s)", "Position", "Finish", "Start Position", "Road Wetness (%)", "Track Temperature (°C)",
    "Compound", "Online", "Game Version",
)


# Formatting
def stat_number(data: dict, key: str) -> float:
    """Stat value, 0 if missing or not a number"""
    value = data.get(key, 0)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def plural(count: float, one: str, many: str) -> str:
    """Count with translated noun: singular for 1 (and 0 in French)"""
    number = round(count)
    singular = number == 1 or (number == 0 and current_language() == "fr")
    return f"{number} {tr(one) if singular else tr(many)}"


def format_duration(seconds: float) -> str:
    """Driving time in hours & minutes: "12 h 05 min", "45 min" under an hour"""
    hours, minutes = divmod(round(max(seconds, 0) / 60), 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def rank_rows(player: dr.DriverRanks | None, history: Sequence[dr.HistoryEntry]) -> list[dict]:
    """Driver card rank rows: label, value, color, progress (0-1), progress text, change since previous rank
    (percent of a tier, history of rank changes) & its tone (1 better, -1 worse, 0 none)"""
    if player is None:
        return []
    rows = []
    for label, field in (("Driver Rank", "driver"), ("Safety Rank", "safety")):
        rank = getattr(player, field)
        if rank is None:
            continue
        change = dr.rank_change_since(history, field, rank)
        progress = max(min(rank.progress, 100), 0)
        rows.append({
            "label": tr(label),
            "value": rank.text,
            "color": dr.RANK_COLORS.get(rank.name.casefold(), ""),  # dark theme
            "lightColor": dr.RANK_COLORS_LIGHT.get(rank.name.casefold(), ""),
            "progress": progress / 100,
            "progressText": f"{progress}%",
            "change": f"{change:+d}%" if change else "",
            "changeTone": (change > 0) - (change < 0),
            "chart": rank_chart(history, field),  # rank over time (empty under 2 ranks seen)
        })
    return rows


def badge_card(player: dr.DriverRanks | None) -> dict:
    """Driver card badge: game name & description (translated), icon file URL ("" until downloaded), colors
    (dark & light theme); empty if no badge"""
    from ...userfile.badge_icons import badge_info, icons

    if player is None or not player.badge:
        return {}
    info = badge_info(player.badge)
    if info is None:  # badge unknown to this version: game name as given
        return {"name": player.badge, "description": "", "icon": "", "color": "", "lightColor": ""}
    path = icons.file(player.badge)
    return {
        "name": tr(info.name),
        "description": tr(info.description),
        "icon": QUrl.fromLocalFile(path).toString() if path else "",
        "color": info.color,
        "lightColor": info.light_color,
    }


def read_stats_backup(path: str, name: str) -> dict | None:
    """Stats backup read & checked (background), None if unreadable"""
    stats_backup = load_stats_backup(path, name)
    return validate_stats_file(stats_backup) if stats_backup is not None else None


def lap_folder_stamp(folder: str) -> int:
    """Modification time of recorded laps folder (changes when a lap file is added or removed), 0 if none"""
    try:
        return os.stat(os.path.join(cfg.path.telemetry, folder)).st_mtime_ns
    except OSError:
        return 0


def folder_stamp(path: str) -> int:
    """Modification time (ns) of a folder (changes when an entry is added or removed), 0 if none"""
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def sector_file_times() -> dict[str, float]:
    """Modified time of every sector best file (track & class name: seconds), one listing (worker thread)"""
    times: dict[str, float] = {}
    try:
        with os.scandir(cfg.path.sector_best) as entries:
            for entry in entries:
                name, extension = os.path.splitext(entry.name)
                if extension == FileExt.SECTOR and entry.is_file():
                    times[name] = entry.stat().st_mtime
    except OSError:
        pass
    return times


def list_lap_folders() -> tuple[int, dict[str, int]]:
    """Recorded laps folders (track & class name: modified time ns, see lap_folder_stamp) & the telemetry folder
    stamp they were listed at, one listing (worker thread)"""
    stamp = folder_stamp(cfg.path.telemetry)
    folders: dict[str, int] = {}
    try:
        with os.scandir(cfg.path.telemetry) as entries:
            for entry in entries:
                if entry.is_dir():
                    folders[entry.name] = entry.stat().st_mtime_ns
    except OSError:
        pass
    return stamp, folders


def other_account_rows(others: list[dr.OtherAccount]) -> list[dict]:
    """Driver card rows of other game accounts of this computer: Steam name, picture URL, ranks (short label,
    value, colors), badge (name, colors), date ranks were seen"""
    from ...userfile.badge_icons import badge_info

    rows = []
    for other in others:
        ranks = []
        for label, field in (("DR", "driver"), ("SR", "safety")):
            rank = getattr(other.ranks, field)
            if rank is not None:
                ranks.append({"label": label, "value": rank.text,
                              "color": dr.RANK_COLORS.get(rank.name.casefold(), ""),
                              "lightColor": dr.RANK_COLORS_LIGHT.get(rank.name.casefold(), "")})
        info = badge_info(other.ranks.badge) if other.ranks.badge else None
        rows.append({
            "name": other.name or tr("Other account"),
            "avatar": QUrl.fromLocalFile(other.avatar).toString() if other.avatar else "",
            "ranks": ranks,
            "badge": {"name": tr(info.name), "color": info.color, "lightColor": info.light_color} if info else (
                {"name": other.ranks.badge, "color": "", "lightColor": ""} if other.ranks.badge else {}),
            "when": format_date(other.time),
        })
    return rows


def rank_info_text(player: dr.DriverRanks | None) -> str:
    """Where ranks come from & when game menu updated them"""
    if player is None or not ranks.updated:
        return ""
    if ranks.remembered:  # game emptied its menu cache: last ranks seen
        return trm(f"Last ranks seen in game menu, {format_date(ranks.updated)}")
    if ranks.online:
        return trm(f"Ranks of RaceControl, updated {format_date(ranks.updated)}")
    return trm(f"Ranks of game menu, updated {format_date(ranks.updated)}")


def session_kind(session: int) -> int:
    """Session filter (SESSION_FILTERS index) a session belongs to: 1 practice, 2 qualifying, 3 race, 0 unknown"""
    return next((group for group in range(1, len(SESSION_GROUPS)) if session in SESSION_GROUPS[group]), 0)


def session_name(session: int) -> str:
    return tr(SESSION_NAMES[session]) if 0 <= session < len(SESSION_NAMES) else ""


def session_code(session: int) -> str:
    """Letter of session badge, same as Results & Replays pages (ResultsBadge): T, P, Q, W, R, "" if unknown"""
    return SESSION_CODES[session] if 0 <= session < len(SESSION_CODES) else ""


def race_result(record: SessionRecord) -> str:
    """Finish position (P3), DNF or DQ, empty if no result"""
    if record.finish == 1 and record.position > 0:
        return f"P{record.position}"
    return FINISH_TEXTS.get(record.finish, "")


def result_tone(record: SessionRecord) -> str:
    """Tone of race result, same rule as Results page: podium gold, silver, bronze, DNF & DQ in loss tone"""
    return place_tone(record.position if record.finish == 1 else 0, True, retired=record.finish in (2, 3))


def parse_display_value(key: str, value: float) -> str | float:
    """Parse stats display value"""
    if DriverStats.is_lap_time(key) or key == "theory":
        return laptime_text(value) if value < MAX_SECONDS else MISSING
    if key == "meters":
        if cfg.units["odometer_unit"] == "Kilometer":
            return round(units.meter_to_kilometer(value), 1)
        if cfg.units["odometer_unit"] == "Mile":
            return round(units.meter_to_mile(value), 1)
        return int(value)
    if key == "seconds":
        return format_duration(value)
    if key == "liters":
        if cfg.units["fuel_unit"] == "Gallon":
            value = units.liter_to_gallon(value)
        return round(value, 2)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def format_header_key(key: str):
    """Format header key"""
    if key == "meters":
        if cfg.units["odometer_unit"] == "Kilometer":
            return "Km"
        if cfg.units["odometer_unit"] == "Mile":
            return "Miles"
        return "Meters"
    if key == "liters":
        if cfg.units["fuel_unit"] == "Gallon":
            return "Gallons"
        return "Liters"
    return HEADER_KEYS.get(key, key.title())


def speed_unit_text() -> str:
    return {"KPH": "km/h", "MPH": "mph"}.get(cfg.units["speed_unit"], "m/s")


def consumption_unit_text() -> str:
    fuel = "gal" if cfg.units["fuel_unit"] == "Gallon" else "L"
    distance = "mi" if cfg.units["odometer_unit"] == "Mile" else "km"
    return f"{fuel}/100 {distance}"


def header_label(key: str) -> str:
    """Translated column title, with unit of setting"""
    label = tr(format_header_key(key))
    if key == "speed":
        return f"{label} ({speed_unit_text()})"
    if key == "consumption":
        return f"{label} ({consumption_unit_text()})"
    return label


def derived_value(key: str, data: dict) -> float | None:
    """Figure derived from vehicle stats (base units: m/s, liters per 100 km), None if unknown"""
    if key == "valid_rate":
        laps = stat_number(data, "valid") + stat_number(data, "invalid")
        return stat_number(data, "valid") / laps * 100 if laps else None
    if key == "speed":
        seconds = stat_number(data, "seconds")
        return stat_number(data, "meters") / seconds if seconds > 0 and stat_number(data, "meters") > 0 else None
    if key == "consumption":
        meters = stat_number(data, "meters")
        return stat_number(data, "liters") / meters * 100000 if meters >= 1000 and stat_number(data, "liters") > 0 else None
    if key == "avg_finish":
        placed = stat_number(data, "placed")
        return stat_number(data, "positions") / placed if placed > 0 else None
    # Rates per start: starts not recorded by older versions, at least finishes & DNF
    starts = max(stat_number(data, "starts"), stat_number(data, "races") + stat_number(data, "dnf"))
    if not starts:
        return None
    if key == "penalty_rate":
        return stat_number(data, "penalties") / starts
    if key == "win_rate":
        return stat_number(data, "wins") / starts * 100
    if key == "podium_rate":
        return stat_number(data, "podiums") / starts * 100
    return None


def format_derived(key: str, value: float | None) -> str:
    """Derived figure text in units of setting"""
    if value is None:
        return MISSING
    if key in ("valid_rate", "win_rate", "podium_rate"):
        return f"{number_text(value)} %"
    if key == "speed":
        if cfg.units["speed_unit"] == "KPH":
            value = units.mps_to_kph(value)
        elif cfg.units["speed_unit"] == "MPH":
            value = units.mps_to_mph(value)
        return number_text(value, 1)
    if key == "consumption":
        if cfg.units["odometer_unit"] == "Mile":
            value = value / 100000 * (100 / units.meter_to_mile(1.0))
        if cfg.units["fuel_unit"] == "Gallon":
            value = units.liter_to_gallon(value)
        return number_text(value, 1)
    if key == "penalty_rate":
        return number_text(value, 2)
    return number_text(value, 1)


def chart_ticks(low: float, high: float, wanted: int = 4) -> list[float]:
    """Round lap times between low & high for chart grid lines (0.1 s to 10 s steps, about wanted lines)"""
    span = high - low
    if span <= 0:
        return []
    step = next((step for step in (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0) if span / step <= wanted),
                10.0 * math.ceil(span / wanted / 10.0))
    first = math.ceil(low / step - 1e-9) * step
    count = int((high - first) / step + 1e-9) + 1
    return [round(first + step * index, 3) for index in range(count) if low < first + step * index < high]


def valid_laptime(value) -> float:
    """Lap time in seconds, 0 if none"""
    return value if isinstance(value, (int, float)) and 0 < value < MAX_SECONDS else 0.0


def level_text(level: int) -> str:
    return tr(LEVELS[level]) if level >= 0 else MISSING


def level_letter(level: int) -> str:
    """First letter of level name: level told without color"""
    return level_text(level)[:1].upper() if level >= 0 else ""


def class_prefix(vehicle: str) -> str:
    """Class part of a driver stats vehicle key ("Class - Brand", "Class", or vehicle name)"""
    return vehicle.split(" - ", 1)[0].strip()


def vehicle_logo(vehicle: str, classes: Iterable[str] = (), logos: LogoCache | None = None) -> str:
    """Brand logo of a driver stats vehicle key: brand of "Class - Brand", or of vehicle name (none
    for a class key)"""
    logos = logos or LogoCache()
    if " - " in vehicle:
        return logos.brand("", vehicle.split(" - ", 1)[1].strip())
    if vehicle in classes:
        return ""
    return logos.brand(vehicle)


def combo_name(track: str, vehicle_class: str) -> str:
    """Track & class name of sector best & recorded laps files"""
    return strip_invalid_char(f"{track} - {vehicle_class}")


def csv_text(text: str, decimal: str) -> str:
    """Cell text for CSV: numbers with decimal separator of locale"""
    if decimal != "." and re.fullmatch(r"[-+]?\d+\.\d+( %)?", text):
        return text.replace(".", decimal)
    return text


def csv_number(value, decimal: str) -> str:
    """Raw value for CSV (empty if unknown), numbers with decimal separator of locale"""
    if value is None:
        return ""
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".") if not value.is_integer() else str(int(value))
        return text.replace(".", decimal) if decimal != "." else text
    return str(value)


def lap_matches_vehicle(info: dict, vehicle_key: str) -> bool:
    """Recorded lap (lap info) driven with driver stats vehicle (brand of "Class - Brand", vehicle name)"""
    name = str(info.get("vehicle", "") or "")
    if not name:
        return True  # older lap without info: class folder only
    if " - " in vehicle_key:
        brand = vehicle_key.split(" - ", 1)[1].strip()
        return select_brand_name(vehicle_name=name) == brand or brand.lower() in name.lower()
    return vehicle_key in (name, str(info.get("class", "")))


class Cell(NamedTuple):
    """Table cell: shown text, sort value (None: unknown, sorted last), raw CSV value, look"""

    text: str
    value: Any = None
    raw: Any = None
    color: str = ""
    bold: bool = False
    tip: str = ""
    badge: str = ""  # level letter
    pill: bool = False  # shown as a pill of its color (level)
    logo: str = ""  # game logo URL before text (car brand, circuit)

def gap_text(summary: ri.ResultSummary) -> str:
    """Gap to class leader of session: "+1.234", "+2 laps", "" for leader or unknown"""
    if summary.gap_laps:
        return laps_behind_text(summary.gap_laps)
    if summary.gap_time > 0:
        return gap_seconds_text(summary.gap_time)
    return ""


def result_details(summary: ri.ResultSummary) -> list[str]:
    """Tooltip lines of a session from its results file: classification, gap, incidents, setting, version"""
    lines = []
    if summary.position > 0:
        place = f"{tr('Position')} {position_text(summary.position, summary.cars)}"  # "P3/12": one form everywhere
        if summary.class_cars != summary.cars and summary.class_position > 0:
            place += f" · {tr('Class')} {position_text(summary.class_position, summary.class_cars)}"
        lines.append(place)
    gap = gap_text(summary)
    if gap:
        lines.append(f"{tr('Gap')} {gap}")
    lines.append(trm(f"Contacts: {summary.contacts} · Penalties: {summary.penalties} · "
                     f"Track limits: {localized_number(summary.track_limits, 0)} pts"))
    online = tr("Online") if summary.setting == "Multiplayer" else tr("Single Player")
    lines.append(" · ".join(part for part in (online, summary.server,
                                              f"{tr('Version')} {summary.game_version}" if summary.game_version
                                              else "") if part))
    return lines


def summary_rank(summary: ri.ResultSummary) -> str:
    """Class position of player in session: "P3/12", "" if not classified"""
    if summary.class_position <= 0:
        return ""
    return position_text(summary.class_position, summary.class_cars)


# Session history: conditions, game versions, race starts
def version_key(version: str) -> tuple[int, float]:
    """Game version ordered as numbers ("1.415" < "1.42"), (-1, 0) if not a version"""
    major, _, minor = version.partition(".")
    if not major.isdigit() or (minor and not minor.isdigit()):
        return -1, 0.0
    return int(major), float(f"0.{minor}") if minor else 0.0


def online_value(record: SessionRecord, summary: ri.ResultSummary | None) -> int:
    """1 online, 0 offline, -1 unknown: recorded, else setting of its results file"""
    if record.online >= 0:
        return record.online
    if summary is not None and summary.setting:
        return int(summary.setting == "Multiplayer")
    return -1


def start_position(record: SessionRecord, summary: ri.ResultSummary | None) -> int:
    """Start position of a race in the scope of its finish position (class or overall), 0 if unknown"""
    if record.start_position > 0:
        return record.start_position
    if summary is None or summary.kind != "Race":
        return 0
    if record.position > 0 and record.position == summary.position and summary.grid > 0:
        return summary.grid  # finish recorded overall
    return summary.class_grid if summary.class_grid > 0 else 0


def places_gained(record: SessionRecord, summary: ri.ResultSummary | None) -> int | None:
    """Places gained (lost: negative) from start to finish of a finished race, None if unknown"""
    if record.finish != 1 or record.position <= 0:
        return None
    start = start_position(record, summary)
    return start - record.position if start > 0 else None


def signed_places(value: int) -> str:
    return f"+{value}" if value > 0 else str(value) if value < 0 else "="


def conditions_text(record: SessionRecord) -> str:
    """Road & track temperature of session best lap: "Wet road 35 % · Track Temp 28 °C" (user temperature unit),
    "" if not recorded"""
    if not record.conditions_known:
        return ""
    road = (trm(f"Wet road {localized_number(record.wetness * 100, 0)} %") if record.wet
            else tr("Dry road"))
    return f"{road} · {tr('Track Temp')} {temperature_text(record.track_temp)}"


def parse_laptime(text: str) -> float:
    """Lap time written by user: "1:52.300", "1:52,3", "112.3", 0 if not a lap time"""
    text = text.strip().replace(",", ".")
    match = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,3}(?:\.\d{1,3})?)", text)
    if match is None:
        return 0.0
    minutes = int(match[1]) if match[1] else 0
    seconds = float(match[2])
    if minutes and seconds >= 60:
        return 0.0
    laptime = minutes * 60 + seconds
    return laptime if 0 < laptime < MAX_SECONDS else 0.0
