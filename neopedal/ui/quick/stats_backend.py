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
Driver stats viewer state for its Qt Quick page (ui/qml/DriverStats.qml)

Track selector (search, All Tracks first, last driven date), key figures of the track (career for All
Tracks), table of vehicles (tracks for All Tracks) with stats, community lap time reference & derived
figures, sorted by any column, columns shown & widths saved. Selected vehicle: level ladder of community
lap times (userfile.lap_reference), personal best progression & sessions list (userfile.driver_history).

Edits (delete track, remove vehicle, reset lap time, restore backup) are applied to stats file read again
under STATS_LOCK (stats module saves meanwhile kept), after an automatic backup; undo merges stats
recorded since. The page never waits for STATS_LOCK nor big files: reloads & edits run in order on a worker
thread, page updated once done (see run_locked). Stats & history files saved by stats module are reloaded at
once (page shown), history only when its file changed (stats file is saved every lap while driving).

All Tracks also shows driving activity of each day (last weeks) & recent sessions. Table rows of the same
track are moved & changed in place (sort, reload): delegates, scroll & animations kept.
"""

from __future__ import annotations

import copy
import csv
import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import date, timedelta
from functools import partial
from statistics import median_low
from typing import Any, NamedTuple

from PySide6.QtCore import (
    Property,
    QDateTime,
    QFileSystemWatcher,
    QLocale,
    QObject,
    QStandardPaths,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPalette
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ... import app_signal, units
from ... import calculation as calc
from ...api_control import api
from ...const_common import MAX_SECONDS, TEXT_NOLAPTIME
from ...const_file import ConfigType
from ...formatter import strip_invalid_char
from ...i18n import current_language, tr, trm
from ...process import driver_ranks as dr
from ...process import results_file as rf
from ...process import results_index as ri
from ...process.player_profile import PlayerProfile, player_profile
from ...process.results_text import gap_seconds_text, laps_behind_text
from ...rank_info import history_path as ranks_history_path
from ...rank_info import ranks
from ...setting import cfg
from ...userfile import lap_reference
from ...userfile.brands import select_brand_name
from ...userfile.driver_history import (
    SESSION_GROUPS,
    SessionRecord,
    best_lap_date,
    best_progression,
    filter_sessions,
    forget_records,
    history_path,
    index_history,
    last_driven,
    load_history,
    replace_records,
    track_last_driven,
    vehicle_classes,
)
from ...userfile.driver_stats import (
    STATS_LOCK,
    DriverStats,
    backup_stats_file,
    list_stats_backups,
    load_stats_backup,
    load_stats_json_file,
    merge_stats_entry,
    save_stats_json_file,
    set_stats_entry,
    stats_entry,
    validate_stats_file,
)
from ...userfile.lap_reference import LEVEL_COLORS, LEVELS, LapReference, LapReferenceTable
from ...userfile.sector_best import load_theoretical_best
from .. import UIScaler
from ..lap_viewer import number_text, signed
from ..track_map_viewer import TrackMapViewer
from .formatting import country_name, date_locale, format_date, format_day, iso_day, localized_number
from .game_pictures import LogoCache, notifier
from .models import DictListModel
from .page_backend import PageBackend
from .stint_analysis import (
    compare_friend,
    history_document,
    load_friend,
    read_laps,
    stint_report,
    write_history_csv,
    write_history_json,
)

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
    "vehicle", "pb", *REFERENCE_KEYS, "theory", "potential", "qb", "rb",
    "meters", "seconds", "liters", "valid", "invalid", "valid_rate", "speed", "consumption",
    "penalties", "penalty_rate", "starts", "races", "wins", "podiums", "dnf", "win_rate", "podium_rate",
    "avg_finish", "last",
)
# All Tracks table columns: track, best lap of each class (class:name), then these totals
TRACK_TOTAL_COLUMNS = ("meters", "seconds", "valid", "races", "wins", "podiums", "last")
FIXED_COLUMNS = ("vehicle", "track")  # never hidden
LAP_TIME_COLUMNS = ("pb", "qb", "rb", "theory")
LOWER_IS_BETTER = ("pb", "qb", "rb", "theory", "potential", "gap", "level", "avg_finish")
DERIVED_COLUMNS = ("valid_rate", "speed", "consumption", "penalty_rate", "win_rate", "podium_rate", "avg_finish")
HEADER_KEYS = {
    "vehicle": "Vehicle", "track": "Track", "pb": "PB", "qb": "Qualifying", "rb": "Race",
    "gap": "% Ref.", "theory": "Theoretical", "potential": "Potential", "seconds": "Driving Time",
    "valid_rate": "% Valid", "speed": "Avg. Speed", "consumption": "Consumption",
    "penalty_rate": "Penalties/Race", "starts": "Starts", "races": "Finishes", "dnf": "DNF",
    "win_rate": "% Wins", "podium_rate": "% Podiums", "avg_finish": "Avg. Finish", "last": "Last Driven",
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
}
RAW_UNITS = {"pb": "s", "qb": "s", "rb": "s", "theory": "s", "potential": "s", "meters": "m", "seconds": "s",
             "liters": "L", "speed": "m/s", "consumption": "L/100 km", "gap": "%"}
# Level colors easier to tell apart with color vision deficiency (Okabe & Ito palette)
COLORBLIND_LEVEL_COLORS = ("#CC79A7", "#0072B2", "#009E73", "#F0E442", "#E69F00", "#999999")
SESSION_NAMES = ("Test day", "Practice", "Qualifying", "Warmup", "Race")
SESSION_FILTERS = ("All", "Practice", "Qualifying", "Race")
FINISH_TEXTS = {2: "DNF", 3: "DQ"}  # race result codes, same in every language
MAX_FIX_LINES = 12  # lap times from results listed in confirmation
MAX_STINTS = 12  # stints & sessions listed with their consistency, newest first
ACTIVITY_WEEKS = 53  # weeks of daily driving activity (All Tracks), page shows the last ones that fit
ACTIVITY_STEPS = (1800, 3600, 7200)  # driving time (seconds) of activity levels 1 to 4 (above last)
RECENT_SESSIONS = 8  # latest sessions of every track (All Tracks)
LOGO_EM = 2.6  # room of game logo before cell text (em)
HISTORY_COLUMNS = (  # session history CSV export
    "Date", "Track", "Vehicle", "Class", "Session", "Best Lap (s)", "Valid Laps", "Invalid Laps", "Distance (m)",
    "Driving Time (s)", "Position", "Finish",
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


def rank_rows(player: dr.DriverRanks | None, history: list[dr.HistoryEntry]) -> list[dict]:
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
    return trm(f"Ranks of game menu, updated {format_date(ranks.updated)}")


def session_kind(session: int) -> int:
    """Session filter (SESSION_FILTERS index) a session belongs to: 1 practice, 2 qualifying, 3 race, 0 unknown"""
    return next((group for group in range(1, len(SESSION_GROUPS)) if session in SESSION_GROUPS[group]), 0)


def session_name(session: int) -> str:
    return tr(SESSION_NAMES[session]) if 0 <= session < len(SESSION_NAMES) else ""


def race_result(record: SessionRecord) -> str:
    """Finish position (P3), DNF or DQ, empty if no result"""
    if record.finish == 1 and record.position > 0:
        return f"P{record.position}"
    return FINISH_TEXTS.get(record.finish, "")


def parse_display_value(key: str, value: float) -> str | float:
    """Parse stats display value"""
    if DriverStats.is_lap_time(key) or key == "theory":
        if 0 < value < MAX_SECONDS:
            return calc.sec2laptime_full(value)
        return TEXT_NOLAPTIME
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
        return "-"
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
    return tr(LEVELS[level]) if level >= 0 else "-"


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


class HistoryData(NamedTuple):
    """Session history read & indexed (background): records, file stamp, records of each (track, vehicle),
    vehicle classes, last driven time of each (track, vehicle) & of each track, sessions of each track"""

    records: list[SessionRecord]
    stamp: tuple[int, int]
    by_combo: dict[tuple[str, str], list[SessionRecord]]
    classes: dict[str, str]
    vehicle_last_driven: dict[tuple[str, str], float]
    track_last_driven: dict[str, float]
    track_sessions: dict[str, tuple[int, float]]


def track_sessions(records: Iterable[SessionRecord]) -> dict[str, tuple[int, float]]:
    """Session count & first session time of each track (records oldest first)"""
    found: dict[str, tuple[int, float]] = {}
    for record in records:
        count, first = found.get(record.track, (0, 0.0))
        found[record.track] = (count + 1, first if count else record.time)
    return found


class StatsJob(NamedTuple):
    """Reload or edit of stats files: work runs holding STATS_LOCK (worker thread, plain data only, never
    the page), done(result, *extra) called on UI thread"""

    kind: str  # "reload" or "edit"
    work: Callable[..., Any]
    args: tuple
    done: Callable[..., Any]
    extra: tuple = ()


def history_file_stamp() -> tuple[int, int]:
    """History file modified time (ns) & size, (0, 0) if none: file read again once changed"""
    try:
        stat = os.stat(history_path(cfg.path.config))
    except OSError:
        return 0, 0
    return stat.st_mtime_ns, stat.st_size


def read_history() -> HistoryData:
    """Session history read & indexed (STATS_LOCK held), file trimmed if over limit"""
    records = load_history(cfg.path.config)
    return HistoryData(records, history_file_stamp(), index_history(records), vehicle_classes(records),
                       last_driven(records), track_last_driven(records), track_sessions(records))


class StatsFiles(NamedTuple):
    """Stats file (checked, None if invalid), session history (None if unchanged), files modified times when
    read"""

    stats: dict | None
    history: HistoryData | None
    times: tuple[float, float]


def stats_file_times() -> tuple[float, float]:
    """Modified time of stats & history files (0 if none)"""
    times = []
    for path in (f"{cfg.path.config}driver.stats", history_path(cfg.path.config)):
        try:
            times.append(os.path.getmtime(path))
        except OSError:
            times.append(0.0)
    return times[0], times[1]


def stats_file_size() -> int:
    try:
        return os.path.getsize(f"{cfg.path.config}driver.stats")
    except OSError:
        return 0


def read_stats_files(history_stamp: tuple[int, int]) -> StatsFiles:
    """Stats file & session history (None if unchanged since history_stamp) read (STATS_LOCK held)"""
    times = stats_file_times()  # files not changed until lock released
    stats_user = load_stats_json_file(filepath=cfg.path.config)
    if stats_user is not None:
        stats_user = validate_stats_file(stats_user)
    if history_file_stamp() == history_stamp:  # stats saved every lap, history at end of each stint only
        return StatsFiles(stats_user, None, times)
    return StatsFiles(stats_user, read_history(), times)


def run_holding_lock(work: Callable[..., Any], *args, finished: threading.Event | None = None) -> Any:
    """Job of worker thread: waits while stats module saves, finished set once work over (raised or not)"""
    try:
        with STATS_LOCK:
            return work(*args)
    finally:
        if finished is not None:
            finished.set()


def save_edits_detached(edits: list[StatsJob], after: threading.Event | None) -> threading.Event:
    """Edits still waiting when page closed: saved in order on a thread once job running before is over,
    page never updated (done callbacks skipped)

    Returns:
        Event set once all edits are over.
    """
    finished = threading.Event()

    def saving():
        try:
            if after is not None:
                after.wait()
            for job in edits:
                try:
                    run_holding_lock(job.work, *job.args)
                except Exception:  # next edits saved all the same (each one complete on its own)
                    logger.exception("DRIVER STATS: stats edit failed after page closed")
        finally:
            forget_records(cfg.path.config)  # history read by edits not kept: page closed
            finished.set()

    threading.Thread(target=saving, daemon=True, name="Driver stats edits").start()
    return finished


class ResultsData(NamedTuple):
    """Game results files summed up for player (oldest first) & game driver profile, read in background with
    session of each history record (None: links made on UI thread, tests)"""

    summaries: list[ri.ResultSummary]
    profile: PlayerProfile | None
    matcher: ri.SessionMatcher | None = None
    links: dict[SessionRecord, ri.ResultSummary | None] | None = None  # record: session
    linked: dict[str, str] | None = None  # results path: vehicle key of record linked


def read_results_data(records: Iterable[SessionRecord] = ()) -> ResultsData:
    """Results files of folders of race results page (game folders found, else folder chosen) & profile,
    linked to session history records (worker thread)"""
    folders = rf.results_folders(rf.chosen_results_folder(cfg.path.config))
    summaries = ri.read_summaries(folders)
    matcher, links, linked = ri.link_records(records, summaries)
    return ResultsData(summaries, player_profile(folders), matcher, links, linked)


def read_reference_cache() -> LapReferenceTable:
    """Lap time reference kept from last download (works offline), worker thread"""
    text, _ = lap_reference.load_cache(cfg.path.config)
    return lap_reference.parse_lap_references(text) if text else LapReferenceTable()


def store_reference(text: str) -> LapReferenceTable:
    """Lap time reference downloaded: kept for next time & parsed (worker thread)"""
    try:
        lap_reference.save_cache(cfg.path.config, text)
    except OSError:  # cache not written (disk full, read only): downloaded reference still used
        logger.exception("STATS: unable to save lap time reference cache")
    return lap_reference.parse_lap_references(text)


def download_reference_sheet(url: str) -> tuple[str, str]:
    """Lap time reference sheet downloaded (worker thread): CSV text (empty if failed), error"""
    try:
        return lap_reference.fetch_sheet(url), ""
    except (OSError, ValueError) as exc:
        return "", str(exc)
    except Exception as exc:  # cut off response (IncompleteRead), bad CSV...: never left downloading
        logger.exception("STATS: lap time reference download failed")
        return "", str(exc) or type(exc).__name__


def read_stints_report(folders: OrderedDict[str, dict], key: str, folder: str, vehicle: str,
                       generation: int) -> tuple[str, int, dict | None]:
    """Recorded laps of vehicle read (worker thread, one read at a time): stints report (None if unreadable) with
    its laps key & read generation. folders: lap infos of last folders read (kept between reads)"""
    path = os.path.join(cfg.path.telemetry, folder)
    infos = folders.pop(folder, None) or {}
    folders[folder] = infos
    while len(folders) > LAP_FOLDERS_KEPT:
        folders.popitem(last=False)
    try:
        report = stint_report(read_laps(path, lambda info: lap_matches_vehicle(info, vehicle), infos, prune=True))
    except Exception:  # unreadable folder: nothing shown, page goes on
        logger.exception("DRIVER STATS: unable to read recorded laps of %s", folder)
        report = None
    return key, generation, report


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
        place = trm(f"Position P{summary.position} of {summary.cars}")
        if summary.class_cars != summary.cars and summary.class_position > 0:
            place += " · " + trm(f"P{summary.class_position} of {summary.class_cars} in class")
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
    return f"P{summary.class_position}/{summary.class_cars}"


class StatsEdit(NamedTuple):
    """Change of stats file at path (track, vehicle, stat; empty: whole file), session history change

    Undo puts history_before back (instead of history_after), redo the other way.
    """

    path: tuple[str, ...]
    before: Any
    after: Any
    history_before: tuple[SessionRecord, ...] = ()
    history_after: tuple[SessionRecord, ...] = ()
    history_only: bool = False  # stats not saved, history change kept (stats not changed by undo & redo)


class DriverStatsBackend(PageBackend):
    """Driver stats viewer page state & actions"""

    CANCEL_JOBS_ON_RELEASE = False  # running edit saved after close (waiting ones wait for it), see release_resources

    tracksChanged = Signal()
    statsChanged = Signal()  # table state: rows or not, track or All Tracks, loading
    # Parts of page told only when changed (see publish)
    driverChanged = Signal()
    activityChanged = Signal()
    recentChanged = Signal()
    tilesChanged = Signal()
    levelsChanged = Signal()
    trackInfoChanged = Signal()
    sortChanged = Signal()  # sort column or order: rows moved, nothing else built again
    columnsChanged = Signal()  # columns shown, their widths
    selectionChanged = Signal()
    selectedKeyChanged = Signal()  # selected row only (light: told at once, even while arrow key held)
    rowIndexChanged = Signal()  # place of selected row (selection changed or rows sorted)
    rowsSwitched = Signal()  # other track shown with rows changed in place (page: back to top, short fade)
    referenceChanged = Signal()
    editsChanged = Signal()
    optionsChanged = Signal()
    lapsChanged = Signal()  # stints & consistency of selected vehicle (recorded laps read)
    friendChanged = Signal()  # friend's stats compared (loaded, removed, own stats changed)

    def __init__(self, parent):
        super().__init__(parent, "Driver stats")
        self._window = parent
        self.stats_temp: dict = {}
        self.selected_stats_key = ""  # selected track, empty for All Tracks
        self.selected_stats_dict: dict = {}
        self.history: list[SessionRecord] = []
        self.history_index: dict[tuple[str, str], list[SessionRecord]] = {}
        self.classes: dict[str, str] = {}  # game class of vehicle keys, from history
        self.vehicle_last_driven: dict[tuple[str, str], float] = {}
        self.track_last_driven: dict[str, float] = {}
        self.track_sessions: dict[str, tuple[int, float]] = {}  # session count & first time of tracks
        self.level_counts: list[int] = [0] * len(LEVELS)
        self.unrated = 0
        self.references = LapReferenceTable()
        self.reference_error = ""
        self._downloading = False
        self._loaded = False  # first load selects current track
        self._reading = True  # stats files not read yet (read in background): page shows it is loading
        self._visible = True
        self._dirty = False  # files changed while page hidden
        self._hidden_since = 0.0  # monotonic time page was hidden (0: shown)
        self._theory_cache: dict[str, tuple[float, float]] = {}  # sector best file: modified time, value
        self._edits_undo: list[StatsEdit] = []
        self._edits_redo: list[StatsEdit] = []
        self._file_times = (0.0, 0.0)
        self._history_stamp: tuple[int, int] = (-1, -1)  # history file read: modified time (ns), size
        # Table
        self.table_header_key: list[str] = list(VEHICLE_COLUMNS)
        self._labels: dict[str, str] = {}
        self._table: list[tuple[str, dict[str, Cell]]] = []  # rows in shown order
        self._columns: list[dict] = []
        self._sort = {"vehicles": ("pb", False), "tracks": ("track", False)}
        self._selected = {"vehicles": "", "tracks": ""}
        self.row_model = DictListModel(("key", "cells"), self)
        self._published_track: str | None = None  # track of rows in model (rows of another one: model reset)
        self._text_widths: dict[tuple[str, bool], float] = {}  # cell texts measured (font of _width_font)
        self._width_font: tuple = ()
        self.logos = LogoCache()  # car brand & circuit logos looked for once per name
        # Selected vehicle
        self._tiles: list[dict] = []
        self._track_info: dict = {}
        self._reference: dict = {}
        self._progression: dict = {}
        self._sessions: list[dict] = []
        self._session_filter = 0
        self._has_laps = False
        self._tracks: list[dict] = []
        # All Tracks: daily activity (computed once per history & day), latest sessions
        self._activity: dict = {}
        self._activity_key: tuple = ()
        self._recent: list[dict] = []
        # Game results files: session of each record (classification, incidents, game version), driver card,
        # lap times missing from stats (read in background with session history)
        self.results: list[ri.ResultSummary] = []
        self.profile: PlayerProfile | None = None
        self._matcher = ri.SessionMatcher(())
        self._record_results: dict[SessionRecord, ri.ResultSummary | None] = {}
        self._linked: dict[str, str] | None = None  # results path: vehicle key (None: made from history)
        self._results_serial = 0  # results read (fixes computed again)
        self._stats_serial = 0  # stats file read
        self._fixes_key: tuple = ()
        self._driver_key: tuple = ()
        self._driver: dict = {"visible": False}
        self._fixes: list[ri.BestLapFix] = []
        self._published: dict[str, Any] = {}  # parts of page as last told (see publish)
        # Stints & consistency of selected vehicle from recorded laps (read in background), friend's stats
        self._stints: dict = {}
        self._laps_key = ""  # recorded laps folder & vehicle shown in stints
        # Lap infos read once: recorded laps folder: lap path: file time, lap info (last folders only)
        self._lap_infos: OrderedDict[str, dict[str, tuple[float, dict]]] = OrderedDict()
        self._laps_generation = 0  # latest read asked: older reads (same key, stale laps) ignored
        self._laps_job: tuple | None = None  # read waiting for debounce or running read: key, folder, vehicle, generation
        self._laps_running = 0  # generation of read running in background (0: none), one at a time
        self.laps_timer = QTimer(self)
        self.laps_timer.setSingleShot(True)
        self.laps_timer.setInterval(LAPS_DELAY)
        self.laps_timer.timeout.connect(self.start_laps_read)
        # Arrow key held in table: row highlighted at once, its reference, progression & sessions once it settles
        self.selection_timer = QTimer(self)
        self.selection_timer.setSingleShot(True)
        self.selection_timer.setInterval(SELECTION_DELAY)
        self.selection_timer.timeout.connect(self.publish_selection)
        self._selection_time = -SELECTION_BURST
        notifier().changed.connect(self.pictures_changed)
        self._friend: dict | None = None
        self._friend_view: dict = {"visible": False}
        self._friend_file = ""  # friend's file being read (chosen by user)

        # Stats & history files saved by stats module: reloaded
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.schedule_reload)
        self.watcher.fileChanged.connect(self.schedule_reload)
        self.watch_timer = QTimer(self)
        self.watch_timer.setSingleShot(True)
        self.watch_timer.setInterval(WATCH_DELAY)
        self.watch_timer.timeout.connect(self.reload_if_changed)
        # Page hidden a while: session history released, read again once shown
        self.hidden_timer = QTimer(self)
        self.hidden_timer.setSingleShot(True)
        self.hidden_timer.setInterval(HIDDEN_RELEASE_DELAY)
        self.hidden_timer.timeout.connect(self.release_history)
        # Driver & safety ranks of game menu file: driver card made again when they change
        self._ranks_serial: tuple[int, int] = (-1, -1)  # ranks & badge icons versions of driver card
        self.ranks_timer = QTimer(self)
        self.ranks_timer.setInterval(RANKS_CHECK)
        self.ranks_timer.timeout.connect(self.check_ranks)
        self.ranks_timer.timeout.connect(self.check_live_track)
        self._live_track = ""  # track of game session shown as live (track list marker, Live badge)
        self.ranks_timer.start()
        self._history_released = False
        # Reloads & edits of stats files run in order, one at a time, on a worker thread (see run_locked)
        ri.hold_files()  # results files read once for race results page too
        self._locked_jobs: list[StatsJob] = []  # waiting
        self._running_job: StatsJob | None = None
        self._last_finished: threading.Event | None = None  # set once last job started (or saved after close) is over
        self._released = False
        # Level colors depend on light or dark theme: table, tiles & charts colored again when theme changes
        self._backups: list[dict] | None = None  # automatic backups (listed again once one is made)
        self._palette_connected = False
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.paletteChanged.connect(self.palette_changed)
            self._palette_connected = True
        # Units & vehicle classification changed in settings: cells, headers & tiles shown again in new ones
        app_signal.refresh.connect(self.settings_changed)
        self._settings_connected = True

        self.load_reference()
        self.load_friend_file(str(self.viewer_config().get("friend_file", "")))
        self.reload_stats()
        self.watch_files()
        self.download_reference()

    @Slot()
    def palette_changed(self, *_args):
        """Light / dark theme switched: level colors (darker on light theme) computed again"""
        if self._loaded:
            self.refresh_table()

    def settings_changed(self, _changed: bool = True):
        """Settings applied (units, vehicle classification): page shown again with them"""
        if self._loaded and not self._released:
            self.refresh_table()

    # Setting
    def viewer_config(self) -> dict:
        return cfg.user.config.get(CONFIG_NAME, {})

    def save_viewer_config(self, **values):
        config = cfg.user.config.setdefault(CONFIG_NAME, {})
        if any(config.get(key) != value for key, value in values.items()):
            config.update(values)
            cfg.save(config_type=ConfigType.CONFIG)

    @property
    def mode(self) -> str:
        return "vehicles" if self.selected_stats_key else "tracks"

    @property
    def colorblind_colors(self) -> bool:
        return bool(self.viewer_config().get("enable_colorblind_colors", False))

    def level_color(self, level: int) -> str:
        """Level color of setting, darker on light theme for contrast"""
        if level < 0:
            return ""
        color = QColor((COLORBLIND_LEVEL_COLORS if self.colorblind_colors else LEVEL_COLORS)[level])
        if QApplication.palette().color(QPalette.ColorRole.Window).lightness() >= 128:
            color = color.darker(135)
        return color.name()

    # Lap time reference
    def load_reference(self):
        """Lap time reference kept from last download (works offline), read in background"""
        self.jobs.run("lap reference", read_reference_cache, self.reference_read, key="reference")

    def reference_read(self, references: LapReferenceTable):
        """Lap time reference read (cache or download): levels shown"""
        self.references = references
        self.referenceChanged.emit()
        if self._loaded and not self._released:
            self.refresh_table()

    def download_reference(self, force: bool = False):
        """Download lap time reference in background, when older than a day (or asked)"""
        config = self.viewer_config()
        if not config.get("enable_lap_reference", True) or self._downloading:
            return
        cached_time = lap_reference.cache_time(cfg.path.config)
        if not force and cached_time and time.time() - cached_time < REFERENCE_MAX_AGE:
            return
        url = config.get("lap_reference_sheet_url") or lap_reference.DEFAULT_SHEET_URL
        self._downloading = True
        self.referenceChanged.emit()
        self.jobs.run("lap reference download", partial(download_reference_sheet, url), self.reference_fetched,
                      self.reference_fetch_failed)

    def reference_fetched(self, result: tuple[str, str]):
        self.reference_downloaded(*result)

    def reference_fetch_failed(self, error: BaseException):
        logger.error("STATS: lap time reference download failed", exc_info=(type(error), error, error.__traceback__))
        self.reference_downloaded("", "download failed")  # never left downloading

    def reference_downloaded(self, text: str, error: str):
        """Download over: reference saved & parsed in background (cache read still running dropped)"""
        self._downloading = False
        self.reference_error = error
        self.referenceChanged.emit()
        if text and not self._released:
            self.jobs.run("lap reference", partial(store_reference, text), self.reference_read, key="reference")

    def reference_for(self, track: str, vehicle: str) -> LapReference | None:
        if not self.references.entries or not self.viewer_config().get("enable_lap_reference", True):
            return None
        return self.references.find(track, vehicle, self.classes.get(vehicle, ""))

    def reference_of(self, vehicle: str) -> LapReference | None:
        return self.reference_for(self.selected_stats_key, vehicle)

    @Property(str, notify=referenceChanged)
    def referenceText(self) -> str:
        source = f"<a href='{lap_reference.SHEET_SOURCE_URL}'>{lap_reference.SHEET_SOURCE}</a>"
        if not self.viewer_config().get("enable_lap_reference", True):
            return tr("Community lap times off")
        if self._downloading:
            return tr("Downloading community lap times...")
        if self.references.entries:
            updated = f" · {tr('updated')} {self.references.updated}" if self.references.updated else ""
            return f"{tr('Community lap times')} ({source}){updated}"
        if self.reference_error:
            return tr("Community lap times unavailable (offline?)")
        return ""

    @Property(bool, notify=referenceChanged)
    def downloading(self) -> bool:
        return self._downloading

    @Property(bool, notify=optionsChanged)
    def compare(self) -> bool:
        return bool(self.viewer_config().get("enable_lap_reference", True))

    @Slot(bool)
    def setCompare(self, enabled: bool):
        """Compare with community lap times or not (saved)"""
        self.save_viewer_config(enable_lap_reference=enabled)
        self.optionsChanged.emit()
        self.referenceChanged.emit()
        self.refresh_table()
        self.columnsChanged.emit()  # reference columns shown only while compared
        if enabled:
            self.download_reference()

    @Slot()
    def updateReference(self):
        self.download_reference(force=True)

    @Slot()
    def changeSheetUrl(self):
        """Published Google Sheet of lap times (same layout), downloaded at once"""
        from .._common import TextInputDialog

        def accept(url: str) -> bool:
            url = url.strip() or lap_reference.DEFAULT_SHEET_URL
            if not url.startswith("https://docs.google.com/spreadsheets/"):
                QMessageBox.warning(self._window, tr("Error"), tr("Not a Google Sheets address."))
                return False
            self.save_viewer_config(lap_reference_sheet_url=url)
            self.download_reference(force=True)
            return True

        TextInputDialog(
            self._window, tr("Change Sheet Address..."),
            tr("Address of the published Google Sheet of community lap times (empty for default):"),
            accept, self.viewer_config().get("lap_reference_sheet_url") or lap_reference.DEFAULT_SHEET_URL,
        ).open()

    # Stats & history files
    @staticmethod
    def file_times() -> tuple[float, float]:
        return stats_file_times()

    @staticmethod
    def history_stamp() -> tuple[int, int]:
        return history_file_stamp()

    def watch_files(self):
        """Watch config folder & stats files (replaced file dropped by watcher: added again)"""
        paths = [os.path.normpath(path) for path in (
            cfg.path.config, f"{cfg.path.config}driver.stats", history_path(cfg.path.config))]
        watched = set(self.watcher.files()) | set(self.watcher.directories())
        wanted = [path for path in paths if path not in watched and os.path.exists(path)]
        if wanted:
            self.watcher.addPaths(wanted)

    def schedule_reload(self, _path: str = ""):
        self.watch_timer.start()

    def reload_if_changed(self):
        """Stats or history file saved meanwhile (stats module): reloaded, or once page shown again"""
        self.watch_files()
        if self.file_times() == self._file_times:
            return
        if not self._visible:
            self._dirty = True
            return
        self.reload_stats()

    def page_shown(self):
        self._visible = True
        self.hidden_timer.stop()
        self.ranks_timer.start()
        hidden_since, self._hidden_since = self._hidden_since, 0.0
        home = bool(hidden_since) and time.monotonic() - hidden_since >= HOME_RESET_DELAY and self._loaded
        if self._history_released:
            self._history_released = self._dirty = False
            # history read again, then its results files & links (see stats_files_read)
            self.reload_stats(select=ALL_TRACKS if home else None)
            return
        if home:  # page left a while: opens on All Tracks again
            self.selectTrack(ALL_TRACKS)
        self.check_ranks()  # ranks changed while hidden
        self.check_live_track()  # game session started or ended while hidden
        if self._dirty:
            self._dirty = False
            self.reload_if_changed()

    def page_hidden(self):
        self._visible = False
        self._hidden_since = time.monotonic()
        self.ranks_timer.stop()  # game ranks file checked only while page shown
        if not self._released:
            self.hidden_timer.start()

    @Slot()
    def release_history(self):
        """Page hidden a while: session history & what is made of it released (memory), read again once shown
        (table, key figures & selection kept as shown)"""
        if self._visible or self._released or self._history_released:
            return
        if self.busy():
            self.hidden_timer.start()  # reload or edit running: later
            return
        self._history_released = True
        self.history, self.history_index = [], {}
        self._history_stamp = (-1, -1)  # read again
        self._record_results = {}
        self._activity_key = ()
        self._lap_infos = OrderedDict()  # a read running fills the former one
        self._laps_key = ""
        forget_records(cfg.path.config)

    def release_resources(self):
        """Page closed: stop watching files & theme"""
        self.watch_timer.stop()
        self.laps_timer.stop()
        self.selection_timer.stop()
        self.hidden_timer.stop()
        self.ranks_timer.stop()
        if not self._released:
            ri.release_files()
        self._released = True
        # Running job finishes (edit saved), waiting reloads dropped, waiting edits still saved: page not updated
        self.save_after_release([job for job in self._locked_jobs if job.kind == "edit"])
        self._locked_jobs.clear()
        self._laps_job = None
        self._lap_infos = OrderedDict()  # a read running fills the former one
        forget_records(cfg.path.config)  # session history kept for next read: memory freed
        paths = self.watcher.files() + self.watcher.directories()
        if paths:
            self.watcher.removePaths(paths)
        if self._palette_connected:
            self._palette_connected = False
            with suppress(RuntimeError, TypeError):
                QApplication.instance().paletteChanged.disconnect(self.palette_changed)  # type: ignore[union-attr]
        if self._settings_connected:
            self._settings_connected = False
            with suppress(RuntimeError, TypeError):
                app_signal.refresh.disconnect(self.settings_changed)

    @Slot()
    def reload(self):
        self.reload_stats()
        self.load_results()

    # Game results files
    def load_results(self):
        """Results files read & linked to session history in background (history as now)"""
        if not self._released:
            self.jobs.run("race results", partial(read_results_data, self.history), self.results_loaded,
                          self.results_failed, key="results")

    def results_loaded(self, data: ResultsData):
        if self._released:
            return
        self.results, self.profile = data.summaries, data.profile
        self._matcher = data.matcher if data.matcher is not None else ri.SessionMatcher(data.summaries)
        self._record_results = data.links if data.links is not None and not self._history_released else {}
        self._linked = data.linked
        self._results_serial += 1
        self.refresh_table()

    def results_failed(self, error: BaseException):
        logger.warning("DRIVER STATS: race results not read", exc_info=(type(error), error, error.__traceback__))

    def record_result(self, record: SessionRecord) -> ri.ResultSummary | None:
        """Session of results file a stint was driven in, None if not found (linked in background, records
        recorded since looked for at once)"""
        try:
            return self._record_results[record]
        except KeyError:
            found = self._record_results[record] = self._matcher.match(
                record.time, record.session, record.track, record.vehicle, record.vehicle_class)
            return found

    def record_version(self, record: SessionRecord) -> str:
        """Game version a stint was driven with: recorded, else of its results file"""
        if record.game_version:
            return record.game_version
        result = self.record_result(record)
        return result.game_version if result is not None else ""

    def best_lap_result(self, track: str, vehicle: str, laptime: float) -> ri.ResultSummary | None:
        """Oldest results session of track & vehicle with lap time as best lap (lap time not in history)"""
        vehicles = self.stats_temp.get(track, {})
        for summary in self.results:
            if (abs(summary.best_lap - laptime) < 0.0005 and ri.same_track(track, summary)
                    and ri.vehicle_key(summary, vehicles, self.classification(), cfg.user.brands) == vehicle):
                return summary
        return None

    @staticmethod
    def classification() -> str:
        """Vehicle keys of stats module: class, class & brand or vehicle name"""
        setting = cfg.user.setting.get("module_stats", {})
        return str(setting.get("vehicle_classification", "Class - Brand")) if isinstance(setting, dict) else ""

    def lap_time_fixes(self) -> list[ri.BestLapFix]:
        """Lap times of stats missing or slower than best lap of a results session, found again only when
        results or stats changed (results linked to history in background)"""
        brands = cfg.user.brands
        key = (self._results_serial, self._stats_serial, self.classification(), id(brands), len(brands))
        if key == self._fixes_key:
            return self._fixes
        linked = self._linked
        if linked is None:  # results given without links
            linked = {}
            for record in self.history:
                result = self.record_result(record)
                if result is not None:
                    linked[result.path] = record.vehicle
        self._fixes_key = key
        return ri.best_lap_fixes(self.results, self.stats_temp, linked, self.classification(), brands)

    def check_ranks(self):
        """Game ranks file checked in background, driver card made again once ranks or badge icon changed"""
        from ...userfile.badge_icons import icons

        ranks.poll()
        serial = (ranks.serial, icons.version)
        if serial == self._ranks_serial:
            return
        self._ranks_serial = serial
        if not self.selected_stats_key:
            self._driver = self.driver_card()
            self.publish("driver", self._driver, self.driverChanged)

    @staticmethod
    def game_track() -> str:
        """Track of game session, empty if none"""
        return api.read.session.track_name() if api.read is not None else ""

    def check_live_track(self):
        """Game session on another track (or ended): track list marker & Live badge shown again at once (else
        only once stats are saved, after a lap)"""
        current = self.game_track()
        if current == self._live_track or not self._loaded or self._released:
            return
        self._live_track = current
        self.track_list()
        self.tracksChanged.emit()
        self._track_info = self.track_info()
        self.publish("trackInfo", self._track_info, self.trackInfoChanged)

    def driver_card(self) -> dict:
        """Driver card, made again only when results, fixes or ranks changed"""
        from ...userfile.badge_icons import icons

        key = (self._results_serial, len(self._fixes), current_language(), ranks.serial, icons.version)
        if key != self._driver_key:
            self._driver_key = key
            self._driver = self.driver_data()
        return self._driver

    def driver_data(self) -> dict:
        """Driver card (All Tracks): game profile, Steam picture, races of results files, lap times to complete"""
        profile = self.profile
        races = [summary for summary in self.results if summary.kind == "Race"]
        player = ranks.player
        others = ranks.others
        if profile is None and not races and player is None and not others:
            return {"visible": False}
        if profile is not None:
            name = profile.name
        else:
            name = races[-1].driver if races else player.name if player is not None else ""
        details = []
        if profile is not None:
            details = [country_name(profile.nationality), profile.team, f"#{profile.number}" if profile.number else ""]
        figures = []
        if races:
            record = ri.race_record(races)
            figures = [
                {"label": tr("Races"), "value": str(record.races)},
                {"label": tr("Wins"), "value": str(record.wins)},
                {"label": tr("Podiums"), "value": str(record.podiums)},
                {"label": tr("Avg. Finish"),
                 "value": f"P{localized_number(record.average_finish, 1)}" if record.average_finish else "-"},
                {"label": tr("Clean Races"), "value": f"{record.clean}/{record.races}"},
                {"label": tr("Contacts/Race"), "value": localized_number(record.contacts / record.races, 1)},
            ]
        fixes = len(self._fixes)
        return {
            "visible": True,
            "name": name,
            "initials": "".join(word[:1] for word in name.split()[:2]).upper(),
            "detail": " · ".join(part for part in details if part),
            "avatar": QUrl.fromLocalFile(profile.avatar).toString() if profile is not None and profile.avatar else "",
            "figures": figures,
            "ranks": rank_rows(player, dr.account_history(dr.read_history(ranks_history_path()), player.steam_id)
                               if player is not None else []),
            "ranksInfo": rank_info_text(player),
            "badge": badge_card(player),
            "otherAccounts": other_account_rows(others),
            "info": trm(f"From {len(races)} race results of the game, class positions") if races else "",
            "fixes": fixes,
            "fixText": trm(f"{fixes} lap time(s) found in race results") if fixes else "",
        }

    @Property(dict, notify=driverChanged)
    def driver(self) -> dict:
        """Driver card: name, initials, detail, avatar URL, figures (label, value), ranks (see rank_rows), ranksInfo,
        badge (see badge_card), info, fixes, fixText"""
        return self._driver

    @Slot(str)
    def openResults(self, path: str):
        """Session of results file shown in race results page"""
        if not path:
            return
        from ..tools_view import open_tool

        page = open_tool("race_results_viewer.RaceResultsViewer", self._window)
        backend = getattr(page, "backend", None)
        if backend is not None:
            backend.open_path(path)

    @Slot()
    def completeLapTimes(self):
        """Lap times missing or slower in stats taken from results files, after confirmation (undo: Ctrl+Z)"""
        fixes = self._fixes
        if not fixes or self.editing:
            return
        lines = []
        for fix in fixes[:MAX_FIX_LINES]:
            before = calc.sec2laptime_full(fix.current) if fix.current else "-"
            lines.append(f"{fix.track} · {fix.vehicle} · {tr(HEADER_KEYS[fix.stat])}: "
                         f"{before} → <b>{calc.sec2laptime_full(fix.laptime)}</b> ({format_date(fix.time)})")
        if len(fixes) > MAX_FIX_LINES:
            lines.append("...")
        message = (trm(f"Complete {len(fixes)} lap time(s) from race results?") + "<br><br>" + "<br>".join(lines)
                   + "<br><br>" + tr("Undo with Ctrl+Z while this page is open."))
        if self.confirm(message):
            self.run_locked(StatsJob("edit", self.write_fixes, (tuple(fixes),), self.edit_written))

    @classmethod
    def write_fixes(cls, fixes: tuple[ri.BestLapFix, ...]) -> tuple[str, StatsEdit | None]:
        """Lap times of fixes saved in stats file read again (STATS_LOCK held, worker thread), faster ones kept"""
        with STATS_LOCK:
            stats_user = cls.load_fresh_stats()
            if stats_user is None:
                return "unreadable", None
            backup_stats_file(cfg.path.config)
            before = copy.deepcopy(stats_user)
            for fix in fixes:
                vehicles = stats_user.get(fix.track)
                data = vehicles.get(fix.vehicle) if isinstance(vehicles, dict) else None
                if not isinstance(data, dict):
                    continue
                current = valid_laptime(data.get(fix.stat, 0))
                if not current or fix.laptime < current - 0.0005:
                    data[fix.stat] = fix.laptime
            if not cls.save_edit(stats_user, (), ()):
                return "unsaved", None
        return "saved", StatsEdit((), before, copy.deepcopy(stats_user))

    # Stats files lock: page (GUI thread) never waits for stats module saving nor for big files read
    def run_locked(self, job: StatsJob, now: bool = False) -> bool:
        """Run job holding STATS_LOCK, in order: on a worker thread (waits there while stats module saves),
        page updated by job.done on UI thread; now (cheap job) on UI thread if lock free & no job waiting.

        Returns:
            True if job ran now.
        """
        if self._released:  # page closed: edit saved all the same, reload dropped
            if job.kind == "edit":
                self.save_after_release([job])
            return False
        if now and not self._locked_jobs and self._running_job is None and STATS_LOCK.acquire(blocking=False):
            try:
                result = job.work(*self.job_args(job))
            finally:
                STATS_LOCK.release()
            job.done(result, *job.extra)
            return True
        self._locked_jobs.append(job)
        if job.kind == "edit":
            self.publish_edits()  # editing
        self.start_locked_job()
        return False

    def job_args(self, job: StatsJob) -> tuple:
        """Reload: history read again only if changed since last read (known when job starts)"""
        return (self._history_stamp, *job.args) if job.kind == "reload" else job.args

    def start_locked_job(self):
        """Next waiting job started on worker thread, once running one is done"""
        if self._running_job is not None or not self._locked_jobs or self._released:
            return
        job = self._running_job = self._locked_jobs.pop(0)
        finished = self._last_finished = threading.Event()
        self.jobs.run(f"stats {job.kind}", partial(run_holding_lock, job.work, *self.job_args(job), finished=finished),
                      self.locked_job_done, self.locked_job_failed, key="history" if job.kind == "reload" else None)

    def save_after_release(self, edits: list[StatsJob]):
        """Edits waiting when page closed: saved in order after running job (page and its jobs may be gone)"""
        if edits:
            self._last_finished = save_edits_detached(edits, self._last_finished)

    def locked_job_done(self, result: Any):
        job, self._running_job = self._running_job, None
        try:
            if job is not None and not self._released:
                job.done(result, *job.extra)
        finally:
            if job is not None and job.kind == "edit" and not self._released:
                self.publish_edits()  # editing
            self.start_locked_job()

    def locked_job_failed(self, error: BaseException):
        job, self._running_job = self._running_job, None
        logger.error("DRIVER STATS: stats %s failed", job.kind if job is not None else "job",
                     exc_info=(type(error), error, error.__traceback__))
        try:
            if job is None or self._released:
                return
            if job.kind == "edit":
                self.publish_edits()
                self.stats_unreadable()
            elif self._reading:  # page never left loading
                self._reading = False
                self.publish_stats()
        finally:
            self.start_locked_job()

    @Property(bool, notify=editsChanged)
    def editing(self) -> bool:
        """Edit waiting or being saved: page disables edit actions meanwhile (edits run in order anyway)"""
        return any(job.kind == "edit" for job in (self._running_job, *self._locked_jobs) if job is not None)

    @Property(bool, notify=statsChanged)
    def loading(self) -> bool:
        """Stats files not read yet (page opened, big session history read in background)"""
        return self._reading

    def busy(self) -> bool:
        """Reload or edit waiting or running"""
        return self._running_job is not None or bool(self._locked_jobs)

    def reload_stats(self, select: str | None = None):
        """Reload stats & history files: selected track kept (current track at first load)

        Small stats file with small or unchanged session history read at once, bigger files read in background
        (page shown as it was meanwhile).

        Args:
            select: track key to select, else selected one (neighbor track if removed).
        """
        stamp = self.history_stamp()
        now = (stamp == self._history_stamp or stamp[1] <= SYNC_HISTORY_BYTES) and stats_file_size() <= SYNC_STATS_BYTES
        self.run_locked(StatsJob("reload", read_stats_files, (), self.stats_files_read, (select,)), now=now)

    def stats_files_read(self, files: StatsFiles, select: str | None):
        """Page updated with stats & history files read"""
        self._reading = False
        self._file_times = files.times
        if files.history is not None:
            history = files.history
            self.history, self._history_stamp, self.history_index = history.records, history.stamp, history.by_combo
            self.classes, self.vehicle_last_driven = history.classes, history.vehicle_last_driven
            self.track_last_driven, self.track_sessions = history.track_last_driven, history.track_sessions
            self._history_released = False
            self.load_results()  # session ended: its results file written too
        self.stats_read(files.stats, select)

    def stats_read(self, stats_user: dict | None, select: str | None):
        """Page updated with stats file read (checked already: validate_stats_file)"""
        if stats_user is None:  # invalid file: stats shown kept
            self.refresh_table()
            return
        self.stats_temp = stats_user
        self._stats_serial += 1
        if select is not None:
            wanted = select
        elif self._loaded:
            wanted = self.selected_stats_key
        else:
            wanted = self.initial_track()
        old_keys = [ALL_TRACKS, *(entry["key"] for entry in self._tracks[1:])]
        old_index = old_keys.index(self.selected_stats_key) if self.selected_stats_key in old_keys else 0
        self._loaded = True
        keys = self.track_list()
        if wanted and wanted not in self.stats_temp:  # removed meanwhile: neighbor track
            index = min(max(old_index, 0), len(keys))
            wanted = keys[index - 1] if index > 0 else ALL_TRACKS
        self.select_stats(wanted)
        self.tracksChanged.emit()

    def track_list(self) -> list[str]:
        """Track list of picker made again (All Tracks first), track keys in shown order"""
        keys = self.sorted_tracks()
        current = self._live_track = self.game_track()
        self._tracks = [{"key": ALL_TRACKS, "label": tr("All Tracks"), "date": "", "current": False, "logo": ""}] + [
            {"key": key, "label": key, "date": format_date(self.track_last_driven.get(key, 0.0)),
             "current": key == current, "logo": self.logos.track(key)}
            for key in keys
        ]
        return keys

    @staticmethod
    def initial_track() -> str:
        """Page opens on All Tracks"""
        return ALL_TRACKS

    def sorted_tracks(self) -> list[str]:
        """Track keys by name, or last driven first (never driven last)"""
        keys = sorted((key for key in self.stats_temp if key), key=str.lower)
        if self.viewer_config().get("enable_sort_by_last_driven", False):
            keys.sort(key=lambda key: self.track_last_driven.get(key, 0.0), reverse=True)
        return keys

    # Track selection
    @Property(list, notify=tracksChanged)
    def tracks(self) -> list[dict]:
        return self._tracks

    @Property(str, notify=tracksChanged)
    def currentTrack(self) -> str:
        return self.selected_stats_key

    @Property(str, notify=tracksChanged)
    def currentLabel(self) -> str:
        return self.selected_stats_key or tr("All Tracks")

    @Property(bool, notify=tracksChanged)
    def allTracks(self) -> bool:
        return not self.selected_stats_key

    @Property(str, notify=tracksChanged)
    def currentLogo(self) -> str:
        """Circuit logo of selected track (game)"""
        return self.logos.track(self.selected_stats_key) if self.selected_stats_key else ""

    @Slot(str)
    def selectTrack(self, key: str):
        if key == self.selected_stats_key and self._loaded:
            return
        self.select_stats(key)
        self.tracksChanged.emit()

    def select_stats(self, key: str):
        """Select track (empty: All Tracks)"""
        self.selected_stats_key = key if key in self.stats_temp else ""
        self.selected_stats_dict = self.stats_temp.get(self.selected_stats_key, {}) if self.selected_stats_key else {}
        self.refresh_table()

    @Property(bool, notify=optionsChanged)
    def sortRecent(self) -> bool:
        return bool(self.viewer_config().get("enable_sort_by_last_driven", False))

    @Slot(bool)
    def setSortRecent(self, enabled: bool):
        """Tracks driven lately first (track list & All Tracks table)"""
        self.save_viewer_config(enable_sort_by_last_driven=enabled)
        self._sort["tracks"] = ("last", True) if enabled else ("track", False)
        self.optionsChanged.emit()
        if not self._loaded:
            return
        self.track_list()  # sorted again in memory: nothing read
        self.tracksChanged.emit()
        if not self.selected_stats_key:  # All Tracks table sorted like track list
            self._table = self.sorted_rows(self._table)
            self.publish_rows()
            self.publish_sort()
            self.publish("rowIndex", self.selected_index(), self.rowIndexChanged)

    @Property(bool, notify=optionsChanged)
    def colorblind(self) -> bool:
        return self.colorblind_colors

    @Slot(bool)
    def setColorblind(self, enabled: bool):
        self.save_viewer_config(enable_colorblind_colors=enabled)
        self.optionsChanged.emit()
        self.refresh_table()

    # Table
    @Slot()
    def pictures_changed(self):
        """Logos fetched from game meanwhile (or theme changed): track list & table shown again if their
        logos changed"""
        if not self._loaded:
            return
        tracks = [dict(entry, logo=self.logos.track(entry["key"])) if entry["key"] else entry
                  for entry in self._tracks]
        if tracks != self._tracks:
            self._tracks = tracks
            self.tracksChanged.emit()
        if self.table_logos_changed():
            self.refresh_table()

    def table_logos_changed(self) -> bool:
        """Logo of a table row or recent session (All Tracks) not the one shown"""
        if self.selected_stats_key:
            classes = self.classes.values()
            return any(cells["vehicle"].logo != vehicle_logo(key, classes, self.logos)
                       for key, cells in self._table if "vehicle" in cells)
        return (any(row["trackLogo"] != self.logos.track(row["track"]) for row in self._recent)
                or any(cells["track"].logo != self.logos.track(key) for key, cells in self._table if "track" in cells))

    def publish(self, name: str, value: Any, signal) -> bool:
        """Part of page told (signal) only if it changed since last told, True if told"""
        if name in self._published and self._published[name] == value:
            return False
        self._published[name] = value
        signal.emit()
        return True

    def refresh_table(self):
        """Table of vehicles (or tracks), sort, selection & tiles kept; parts of page told only when changed
        (every lap while driving: stats saved)"""
        columns = self._columns
        if self.selected_stats_key:
            rows = self.vehicle_rows()
        else:
            rows = self.track_rows()
        self._table = self.sorted_rows(rows)
        self.publish_table()
        self.refresh_tiles()
        self._track_info = self.track_info()
        self._fixes = self.lap_time_fixes()
        if not self.selected_stats_key:
            self._activity = self.activity_data()
            self._recent = self.recent_sessions()
            self._driver = self.driver_card()
        selected = self._selected[self.mode]
        keys = [key for key, _ in self._table]
        if selected not in keys:
            self._selected[self.mode] = keys[0] if keys else ""
        if self._columns != columns:
            self.columnsChanged.emit()
        self.publish_sort()
        self.publish_stats()
        self.publish("tiles", self._tiles, self.tilesChanged)
        self.publish("trackInfo", self._track_info, self.trackInfoChanged)
        self.publish("levels", (self.levels_data(), self.levels_info()), self.levelsChanged)
        if not self.selected_stats_key:
            self.publish("activity", self._activity, self.activityChanged)
            self.publish("recent", self._recent, self.recentChanged)
            self.publish("driver", self._driver, self.driverChanged)
        self.publish_edits()
        self.update_selection()
        self.refresh_friend()  # rows of selected track

    def publish_sort(self):
        self.publish("sort", (self.mode, *self._sort[self.mode]), self.sortChanged)

    def publish_stats(self):
        self.publish("stats", (bool(self._table), self.mode, self._reading), self.statsChanged)

    def publish_edits(self):
        self.publish("edits", (self.editing, bool(self._edits_undo), bool(self._edits_redo), self._backups is None),
                     self.editsChanged)

    def set_header(self, keys: list[str], labels: list[str]):
        self.table_header_key = keys
        self._labels = dict(zip(keys, labels))

    def vehicle_rows(self) -> list[tuple[str, dict[str, Cell]]]:
        """Vehicles of selected track: stats, reference, derived figures"""
        self.set_header(list(VEHICLE_COLUMNS), [header_label(key) for key in VEHICLE_COLUMNS])
        track = self.selected_stats_key
        return [(str(vehicle), self.vehicle_cells(track, str(vehicle), data))
                for vehicle, data in self.selected_stats_dict.items() if isinstance(data, dict)]

    def vehicle_cells(self, track: str, vehicle: str, data: dict) -> dict[str, Cell]:
        reference = self.reference_for(track, vehicle)
        best = valid_laptime(data.get("pb", 0))
        theory = self.theory_of(track, vehicle)
        cells: dict[str, Cell] = {"vehicle": Cell(vehicle, vehicle.lower(), vehicle,
                                                  logo=vehicle_logo(vehicle, self.classes.values(), self.logos))}
        percent = reference.percent(best) if reference else 0.0
        cells["gap"] = Cell(f"{number_text(percent, 2)} %" if percent else "-", percent or None, round(percent, 3) if percent else None)
        level = reference.level(best) if reference else -1
        cells["level"] = Cell(level_text(level), level if level >= 0 else None, level_text(level) if level >= 0 else None,
                              self.level_color(level), level >= 0, pill=level >= 0)
        cells["theory"] = Cell(str(parse_display_value("theory", theory)), theory or None, round(theory, 3) if theory else None)
        potential = best - theory if best and theory and best >= theory - 0.0005 else None
        cells["potential"] = Cell(number_text(max(potential, 0.0), 3) if potential is not None else "-",
                                  potential, round(max(potential, 0.0), 3) if potential is not None else None)
        for key in DERIVED_COLUMNS:
            value = derived_value(key, data)
            cells[key] = Cell(format_derived(key, value), value, round(value, 3) if value is not None else None)
        driven = self.vehicle_last_driven.get((track, vehicle), 0.0)
        cells["last"] = Cell(format_date(driven), driven or None, iso_day(driven) if driven else None)
        for key in ("pb", "qb", "rb", "meters", "seconds", "liters", "valid", "invalid", "penalties",
                    "starts", "races", "wins", "podiums", "dnf"):
            value = stat_number(data, key)
            if DriverStats.is_lap_time(key):
                laptime = valid_laptime(value)
                cells[key] = Cell(str(parse_display_value(key, laptime or MAX_SECONDS)), laptime or None,
                                  round(laptime, 3) if laptime else None, bold=key == "pb" and laptime > 0)
            else:
                cells[key] = Cell(str(parse_display_value(key, value)), value, value)
        return cells

    def track_rows(self) -> list[tuple[str, dict[str, Cell]]]:
        """All Tracks: best lap of each class (level color & letter), totals; level distribution"""
        tracks = {key: vehicles for key, vehicles in self.stats_temp.items() if key and isinstance(vehicles, dict)}
        classes = sorted({self.class_of(str(vehicle)) for vehicles in tracks.values() for vehicle in vehicles},
                         key=str.lower)
        keys = ["track", *(f"class:{name}" for name in classes), *TRACK_TOTAL_COLUMNS]
        self.set_header(keys, [tr("Track"), *classes, *(header_label(key) for key in TRACK_TOTAL_COLUMNS)])
        counts = [0] * len(LEVELS)
        unrated = 0
        rows = []
        for track, vehicles in tracks.items():
            cells: dict[str, Cell] = {"track": Cell(track, track.lower(), track, logo=self.logos.track(track))}
            bests: dict[str, tuple[float, str]] = {}
            for vehicle, data in vehicles.items():
                best = valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0
                name = self.class_of(str(vehicle))
                if best and (name not in bests or best < bests[name][0]):
                    bests[name] = (best, str(vehicle))
            for name in classes:
                best, vehicle = bests.get(name, (0.0, ""))
                if not best:
                    cells[f"class:{name}"] = Cell("-")
                    continue
                reference = self.reference_for(track, vehicle)
                level = reference.level(best) if reference else -1
                if reference is not None and level >= 0:
                    counts[level] += 1
                    tip = f"{vehicle} · {level_text(level)} · {number_text(reference.percent(best), 2)} %"
                else:
                    unrated += 1
                    tip = vehicle
                cells[f"class:{name}"] = Cell(calc.sec2laptime_full(best), best, round(best, 3),
                                              self.level_color(level), level >= 0, tip, level_letter(level))
            data_list = [data for data in vehicles.values() if isinstance(data, dict)]
            for key in TRACK_TOTAL_COLUMNS:
                if key == "last":
                    driven = self.track_last_driven.get(track, 0.0)
                    cells[key] = Cell(format_date(driven), driven or None, iso_day(driven) if driven else None)
                else:
                    value = sum(stat_number(data, key) for data in data_list)
                    cells[key] = Cell(str(parse_display_value(key, value)), value, value)
            rows.append((track, cells))
        self.level_counts = counts
        self.unrated = unrated
        return rows

    def class_of(self, vehicle: str) -> str:
        """Game class of vehicle key: recorded in history, else class part of key"""
        return self.classes.get(vehicle) or class_prefix(vehicle)

    def theory_of(self, track: str, vehicle: str) -> float:
        """Theoretical best of track & vehicle class (sector best file, read again once changed), 0 if unknown"""
        name = combo_name(track, self.class_of(vehicle))
        path = f"{cfg.path.sector_best}{name}.sector"
        try:
            modified = os.path.getmtime(path)
        except OSError:
            return 0.0
        cached = self._theory_cache.get(name)
        if cached is None or cached[0] != modified:
            cached = self._theory_cache[name] = (modified, load_theoretical_best(cfg.path.sector_best, name))
        return cached[1]

    def sorted_rows(self, rows: list[tuple[str, dict[str, Cell]]]) -> list[tuple[str, dict[str, Cell]]]:
        """Rows by sort column (unknown values last, whatever the order)"""
        key, descending = self._sort[self.mode]
        if key not in self.table_header_key:
            key, descending = (self.table_header_key[1] if self.selected_stats_key else "track"), False
            self._sort[self.mode] = (key, descending)
        known = [row for row in rows if row[1].get(key, Cell("")).value is not None]
        unknown = [row for row in rows if row[1].get(key, Cell("")).value is None]
        known.sort(key=lambda row: row[1][key].value, reverse=descending)
        unknown.sort(key=lambda row: row[0].lower())
        return known + unknown

    @Slot(str)
    def sortBy(self, key: str):
        """Sort by column, again for reverse order"""
        current, descending = self._sort[self.mode]
        if key == current:
            descending = not descending
        else:
            descending = key in ("last",) or (key not in LOWER_IS_BETTER and key not in FIXED_COLUMNS
                                             and not key.startswith("class:"))
        self._sort[self.mode] = (key, descending)
        self._table = self.sorted_rows(self._table)
        self.publish_rows()  # rows moved: columns & widths unchanged
        self.publish_sort()
        self.publish("rowIndex", self.selected_index(), self.rowIndexChanged)  # same row: reference & charts kept

    @Property(str, notify=sortChanged)
    def sortKey(self) -> str:
        return self._sort[self.mode][0]

    @Property(bool, notify=sortChanged)
    def sortDescending(self) -> bool:
        return self._sort[self.mode][1]

    def hidden_columns(self) -> set[str]:
        text = self.viewer_config().get("hidden_columns", "")
        return {key.strip() for key in str(text).split(",") if key.strip()}

    def column_widths(self) -> dict[str, float]:
        """Column widths set by user (font size units)"""
        widths = {}
        for entry in str(self.viewer_config().get("column_widths", "")).split(","):
            key, _, width = entry.rpartition(":")
            with suppress(ValueError):
                widths[key] = float(width)
        return widths

    def visible_keys(self) -> list[str]:
        """Columns shown: fixed ones, others unless hidden by user (reference ones only while compared)"""
        hidden = self.hidden_columns()
        if not self.compare:
            hidden |= set(REFERENCE_KEYS)
        return [key for key in self.table_header_key if key in FIXED_COLUMNS or key not in hidden]

    def publish_table(self):
        """Visible columns (widths from contents) & rows to page"""
        self.publish_columns()
        self.publish_rows()

    def publish_columns(self):
        """Visible columns: widths from contents (each text measured once, kept while font unchanged), or set
        by user"""
        keys = self.visible_keys()
        font = QFont(QApplication.font())
        font_key = (font.key(), UIScaler.FONT_PIXEL_SCALED)
        measured = self._text_widths  # many cells share a text ("-", dates...), most unchanged after a lap
        if font_key != self._width_font or len(measured) > 20000:
            measured.clear()
            self._width_font = font_key
        metrics = QFontMetricsF(font)
        font.setBold(True)
        bold = QFontMetricsF(font)

        def text_width(text: str, is_bold: bool) -> float:
            width = measured.get((text, is_bold))
            if width is None:
                width = measured[(text, is_bold)] = (bold if is_bold else metrics).horizontalAdvance(text)
            return width

        em = float(UIScaler.FONT_PIXEL_SCALED)  # theme.em of page
        user_widths = self.column_widths()
        columns = []
        for key in keys:
            label = self._labels.get(key, key)
            width = text_width(label, True) * 1.05 + em * 2.0  # margins & sort arrow (StatsTable.qml)
            extras = False  # logo, pill or letter badge in any cell: decorations made in this column only
            for _, cells in self._table:
                cell = cells.get(key)
                if cell is not None:
                    margins = 3.3 if cell.badge else 2.4 if cell.pill else 1.6  # badge, pill & cell margins
                    if cell.logo:
                        margins += LOGO_EM  # logo before text (StatsTable.qml)
                    extras = extras or bool(cell.badge or cell.pill or cell.logo)
                    width = max(width, text_width(cell.text, cell.bold) * 1.05 + em * margins)
            if key in user_widths:
                width = max(user_widths[key] * em, em * 2)
            tip = HEADER_TOOLTIPS.get(key, "")
            columns.append({"key": key, "label": label, "tip": tr(tip) if tip else "", "width": round(width),
                            "align": "left" if key in FIXED_COLUMNS else "center", "extras": extras})
        self._columns = columns

    def publish_rows(self):
        """Rows to page: moved & changed in place (scroll & delegates kept); other track with mostly the same
        vehicles changed in place too (page told: back to top), else rows made again (All Tracks, few shared)"""
        keys = self.visible_keys()
        rows = [{"key": row_key, "cells": [self.cell_data(cells.get(key)) for key in keys]}
                for row_key, cells in self._table]
        if self._published_track == self.selected_stats_key:
            self.row_model.sync(rows)
            return
        switched_from = self._published_track
        self._published_track = self.selected_stats_key
        old_keys = {row.get("key") for row in self.row_model.rows}
        shared = sum(row["key"] in old_keys for row in rows)
        if not switched_from or not self.selected_stats_key or shared * 2 < max(len(rows), len(old_keys)):
            self.row_model.reset(rows)  # All Tracks, or few vehicles in common: rows fade in
            return
        self.row_model.sync(rows)  # a reset if too many rows move (then rows fade in too)
        self.rowsSwitched.emit()

    @staticmethod
    def cell_data(cell: Cell | None) -> dict:
        """Cell of page: text, look, tooltip; unknown value dimmed"""
        if cell is None:
            return {"text": "", "color": "", "bold": False, "tip": "", "badge": "", "pill": False, "dim": False,
                    "logo": ""}
        return {"text": cell.text, "color": cell.color, "bold": cell.bold, "tip": cell.tip, "badge": cell.badge,
                "pill": cell.pill, "dim": cell.value is None and not cell.color, "logo": cell.logo}

    @Property(QObject, constant=True)
    def rows(self) -> QObject:
        return self.row_model

    @Property(list, notify=columnsChanged)
    def columns(self) -> list[dict]:
        return self._columns

    @Property(list, notify=columnsChanged)
    def columnMenu(self) -> list[dict]:
        """Columns of vehicle table that can be hidden (shared ones in All Tracks too)"""
        hidden = self.hidden_columns()
        compare = self.compare
        return [{"key": key, "label": header_label(key), "visible": key not in hidden}
                for key in VEHICLE_COLUMNS if key not in FIXED_COLUMNS and (compare or key not in REFERENCE_KEYS)]

    @Slot(str, bool)
    def setColumnVisible(self, key: str, visible: bool):
        hidden = self.hidden_columns()
        if visible:
            hidden.discard(key)
        else:
            hidden.add(key)
        self.save_viewer_config(hidden_columns=",".join(key for key in VEHICLE_COLUMNS if key in hidden))
        self.publish_table()
        self.columnsChanged.emit()

    @Slot(str, float)
    def setColumnWidth(self, key: str, width: float):
        """Column resized by user (pixels), saved in font size units"""
        em = float(UIScaler.FONT_PIXEL_SCALED)
        widths = self.column_widths()
        widths[key] = round(max(width, em * 2) / em, 2)
        self.save_viewer_config(column_widths=",".join(f"{name}:{value:g}" for name, value in widths.items()))
        self.publish_columns()  # rows unchanged
        self.columnsChanged.emit()

    @Slot()
    def resetColumnWidths(self):
        self.save_viewer_config(column_widths="")
        self.publish_columns()
        self.columnsChanged.emit()

    @Property(bool, notify=statsChanged)
    def hasRows(self) -> bool:
        return bool(self._table)

    @Property(str, notify=statsChanged)
    def tableTitle(self) -> str:
        return tr("Vehicles") if self.selected_stats_key else tr("Tracks")

    @Property(str, notify=statsChanged)
    def hint(self) -> str:
        if self.selected_stats_key:
            return tr("Right click a vehicle or lap time to remove or reset it, Ctrl+Z to undo.")
        return tr("Double click a track to show its vehicles.")

    @Property(str, notify=statsChanged)
    def emptyText(self) -> str:
        if self.selected_stats_key:
            return tr("No stats for this track yet: drive a few laps.")
        return tr("No stats yet: drive a few laps.")

    def cell(self, key: str, column: str) -> Cell | None:
        """Cell of row key & column key (tests, actions)"""
        for row_key, cells in self._table:
            if row_key == key:
                return cells.get(column)
        return None

    def row_keys(self) -> list[str]:
        return [key for key, _ in self._table]

    # Key figures
    def refresh_tiles(self):
        """Key figures of selected track, all vehicles (All Tracks: career)"""
        if self.selected_stats_key:
            data = [value for value in self.selected_stats_dict.values() if isinstance(value, dict)]
            tiles = self.track_tiles()
        else:
            data = [value for vehicles in self.stats_temp.values() if isinstance(vehicles, dict)
                    for value in vehicles.values() if isinstance(value, dict)]
            tiles = self.career_tiles()

        def total(key: str) -> float:
            return sum(stat_number(value, key) for value in data)

        meters = total("meters")
        valid, invalid = total("valid"), total("invalid")
        laps = valid + invalid
        laps_detail = ""
        if laps:
            laps_detail = trm(f"{valid / laps * 100:.0f} % of {laps:.0f} {'lap' if laps == 1 else 'laps'}")
        races_detail = f"{plural(total('wins'), 'win', 'wins')} · {plural(total('podiums'), 'podium', 'podiums')}"
        tiles += [
            self.tile(tr("Distance"), f"{parse_display_value('meters', meters)} {tr(format_header_key('meters')).lower()}"
                      if data else "-", glyph=""),  # car
            self.tile(tr("Driving Time"), format_duration(total("seconds")) if data else "-", glyph=""),  # clock
            self.tile(tr("Valid Laps"), f"{valid:.0f}" if data else "-", laps_detail, glyph="",  # check
                      ratio=valid / laps if laps else -1.0),
            self.tile(tr("Races"), f"{total('races'):.0f}" if data else "-", races_detail if data else "",
                      glyph=""),  # flag
        ]
        self._tiles = tiles

    @staticmethod
    def tile(title: str, value: str, detail: str = "", color: str = "", tip: str = "", glyph: str = "",
             letter: str = "", ratio: float = -1.0) -> dict:
        """Key figure: icon, title, value (color: level), detail line, level letter, ratio bar (-1: none)"""
        return {"title": title, "value": value, "detail": detail, "color": color, "tip": tip, "glyph": glyph,
                "letter": letter, "ratio": ratio}

    def track_tiles(self) -> list[dict]:
        """Best lap of track & its level"""
        bests = [(valid_laptime(value.get("pb", 0)), name) for name, value in self.selected_stats_dict.items()
                 if isinstance(value, dict)]
        bests = [entry for entry in bests if entry[0] > 0]
        tip_best = tr("Best personal best of the track, any vehicle")
        tip_level = tr("Level of best lap on community lap times")
        if not bests:
            return [self.tile(tr("Best Lap"), "-", tip=tip_best, glyph=""),  # stopwatch
                    self.tile(tr("Level"), "-", tip=tip_level, glyph="")]  # star
        best, vehicle = min(bests)
        reference = self.reference_of(vehicle)
        level = reference.level(best) if reference else -1
        if reference is not None:
            detail = f"{number_text(reference.percent(best), 2)} %"
        else:
            detail = tr("No reference for this track or class") if self.references.entries else ""
        return [self.tile(tr("Best Lap"), calc.sec2laptime_full(best), vehicle, tip=tip_best, glyph=""),
                self.tile(tr("Level"), level_text(level), detail, self.level_color(level), tip_level, glyph="",
                          letter=level_letter(level))]

    def career_tiles(self) -> list[dict]:
        """Tracks driven & most driven one, median level of best laps"""
        tracks = {key: vehicles for key, vehicles in self.stats_temp.items() if key and isinstance(vehicles, dict)}
        seconds = {key: sum(stat_number(data, "seconds") for data in vehicles.values() if isinstance(data, dict))
                   for key, vehicles in tracks.items()}
        most = max(seconds, key=lambda key: seconds[key], default="")
        detail = trm(f"Most driven: {most}") if most and seconds[most] > 0 else ""
        levels = [level for level, count in enumerate(self.level_counts) for _ in range(count)]
        level = median_low(levels) if levels else -1
        level_detail = f"{tr('Median of')} {plural(len(levels), 'best lap', 'best laps')}" if levels else ""
        return [
            self.tile(tr("Tracks"), str(len(tracks)) if tracks else "-", detail, tip=f"{tr('Tracks with stats')}\n{detail}",
                      glyph=""),  # map pin
            self.tile(tr("Level"), level_text(level), level_detail, self.level_color(level),
                      tr("Median level of your best laps, all tracks & classes"), glyph="",
                      letter=level_letter(level)),
        ]

    # Header line: vehicles, sessions & last driven date of track (All Tracks: tracks, sessions, first date)
    def track_info(self) -> dict:
        track = self.selected_stats_key
        if track:
            sessions, first = self.track_sessions.get(track, (0, 0.0))
            parts = [plural(len(self.selected_stats_dict), "vehicle", "vehicles")]
            driven = self.track_last_driven.get(track, 0.0)
        else:
            found = [self.track_sessions[key] for key in self.stats_temp if key in self.track_sessions]
            sessions, first = sum(count for count, _ in found), min((when for _, when in found), default=0.0)
            count = len([key for key in self.stats_temp if key])
            parts = [plural(count, "track", "tracks")] if count else []  # no stats: empty page says it
            driven = 0.0
        if sessions:
            parts.append(plural(sessions, "session", "sessions"))
            if track:
                parts.append(f"{tr('last driven')} {format_date(driven)}")
            else:
                parts.append(f"{tr('since')} {format_date(first)}")
        return {"subtitle": " · ".join(parts), "live": bool(track) and track == self.game_track()}

    @Property(dict, notify=trackInfoChanged)
    def trackInfo(self) -> dict:
        """Line under track name (subtitle), live: track of game session"""
        return self._track_info

    # Daily driving activity of last weeks, recent sessions (All Tracks)
    def activity_data(self) -> dict:
        """Driving time of each day of last ACTIVITY_WEEKS weeks (Monday first), month & day names, summary

        Days: level (0 none, 1-4 driving time, -1 future), tooltip. Computed again only when history or day changes.
        """
        today = date.today()
        key = (self._history_stamp, today, current_language())
        if key == self._activity_key and self._activity:
            return self._activity
        start = today - timedelta(days=today.weekday() + (ACTIVITY_WEEKS - 1) * 7)
        seconds: dict[date, float] = {}
        sessions: dict[date, int] = {}
        for record in reversed(self.history):  # oldest first: older records skipped at once
            day = date.fromtimestamp(record.time)
            if day < start:
                break
            seconds[day] = seconds.get(day, 0.0) + record.seconds
            sessions[day] = sessions.get(day, 0) + 1
        days = []
        streak = longest = 0
        for number in range(ACTIVITY_WEEKS * 7):
            day = start + timedelta(days=number)
            if day > today:
                days.append({"level": -1, "tip": ""})
                continue
            count = sessions.get(day, 0)
            driven = seconds.get(day, 0.0)
            streak = streak + 1 if count else 0
            longest = max(longest, streak)
            level = 0 if not count else 1 + sum(driven >= step for step in ACTIVITY_STEPS)
            detail = (f"{plural(count, 'session', 'sessions')} · {format_duration(driven)}" if count
                      else tr("No driving"))
            days.append({"level": level, "tip": f"{format_day(day)}\n{detail}"})
        locale = date_locale()
        months = []
        for week in range(ACTIVITY_WEEKS):
            first = start + timedelta(days=week * 7)
            if week == 0 or first.month != (first - timedelta(days=7)).month:
                months.append({"week": week, "text": locale.monthName(first.month, QLocale.FormatType.ShortFormat)})
        driven_days = len(seconds)
        if driven_days:
            summary = " · ".join((
                plural(driven_days, "day driven", "days driven"),
                format_duration(sum(seconds.values())),
                f"{tr('longest streak')} {plural(longest, 'day', 'days')}",
            ))
        else:
            summary = tr("No session recorded yet: history starts with your next session.")
        self._activity_key = key
        return {"weeks": ACTIVITY_WEEKS, "days": days, "months": months, "summary": summary,
                "dayNames": [locale.dayName(number, QLocale.FormatType.ShortFormat) for number in (1, 3, 5)]}

    @Property(dict, notify=activityChanged)
    def activity(self) -> dict:
        """Daily driving activity (All Tracks): weeks, days (level, tip), months (week, text), summary"""
        return self._activity

    def recent_sessions(self) -> list[dict]:
        """Latest sessions of tracks with stats, newest first"""
        rows = []
        for record in reversed(self.history):
            vehicles = self.stats_temp.get(record.track)
            if not isinstance(vehicles, dict) or record.vehicle not in vehicles:
                continue  # removed since
            data = vehicles[record.vehicle]
            best = valid_laptime(data.get("pb", 0)) if isinstance(data, dict) else 0.0
            laptime = record.best if record.best > 0 and not (best and record.best < best - 0.0005) else 0.0
            rows.append({
                "track": record.track, "vehicle": record.vehicle, "date": format_date(record.time),
                "trackLogo": self.logos.track(record.track),
                "session": session_name(record.session), "kind": session_kind(record.session),
                "best": calc.sec2laptime_full(laptime) if laptime else "-",
                "pb": bool(best and laptime and abs(laptime - best) < 0.0005), "result": race_result(record),
                "podium": record.position if record.finish == 1 and 0 < record.position <= 3 else 0,
            })
            if len(rows) >= RECENT_SESSIONS:
                break
        return rows

    @Property(list, notify=recentChanged)
    def recent(self) -> list[dict]:
        """Latest sessions (All Tracks): track, vehicle, date, session, kind, best lap, pb, result"""
        return self._recent

    @Slot(str, str)
    def openSession(self, track: str, vehicle: str):
        """Recent session clicked: its track shown, its vehicle selected"""
        if track not in self.stats_temp:
            return
        self.selectTrack(track)
        self.selectRow(vehicle)

    @Slot()
    def showAllTracks(self):
        self.selectTrack(ALL_TRACKS)

    @Slot()
    def deleteSelected(self):
        """Delete key: remove selected vehicle (All Tracks: delete selected track), after confirmation"""
        if self.selected_stats_key:
            self.removeVehicle()
        elif self._selected["tracks"]:
            self.deleteTrack(self._selected["tracks"])

    @Property(list, notify=tilesChanged)
    def tiles(self) -> list[dict]:
        return self._tiles

    # Level distribution (All Tracks)
    def levels_data(self) -> list[dict]:
        top = max(self.level_counts, default=0)
        return [{"name": tr(name), "color": self.level_color(level), "count": self.level_counts[level],
                 "ratio": self.level_counts[level] / top if top else 0.0, "letter": level_letter(level)}
                for level, name in enumerate(LEVELS)]

    @Property(list, notify=levelsChanged)
    def levels(self) -> list[dict]:
        return self._published.get("levels", ([], ""))[0]

    @Property(str, notify=levelsChanged)
    def levelsInfo(self) -> str:
        return self._published.get("levels", ([], ""))[1]

    def levels_info(self) -> str:
        if not any(self.level_counts):
            return tr("No level yet: community lap times needed, vehicle classification by class.")
        if self.unrated:
            return plural(self.unrated, "track & class combo without reference", "track & class combos without reference")
        return ""

    # Selection: reference, progression & sessions of selected vehicle
    @Property(str, notify=selectedKeyChanged)
    def selectedKey(self) -> str:
        return self._selected[self.mode]

    @Slot(str)
    def selectRow(self, key: str):
        if key == self._selected[self.mode] or key not in self.row_keys():
            return
        self._selected[self.mode] = key
        self.update_selection()

    def selected_index(self) -> int:
        keys = self.row_keys()
        return keys.index(self._selected[self.mode]) if self._selected[self.mode] in keys else -1

    @Property(int, notify=rowIndexChanged)
    def selectedIndex(self) -> int:
        return self.selected_index()

    @Slot(int)
    def moveSelection(self, step: int):
        """Keyboard: select previous or next row"""
        keys = self.row_keys()
        if keys:
            index = self.selected_index()
            key = keys[min(max(index + step, 0), len(keys) - 1) if index >= 0 else 0]
            if key != self._selected[self.mode]:
                self._selected[self.mode] = key
                self.update_selection(keyboard=True)

    def selected_row_key(self) -> str:
        return self._selected[self.mode]

    @Slot(str)
    def openRow(self, key: str):
        """All Tracks: double click or Enter shows vehicles of track"""
        if not self.selected_stats_key and key in self.stats_temp:
            self.selectTrack(key)

    def update_selection(self, keyboard: bool = False):
        """Selected row told at once; its reference, progression & sessions too, unless moved by keyboard quickly
        (arrow key held: shown once it settles, page not rebuilt for each row passed)"""
        burst = False
        if keyboard:
            now = time.monotonic()
            burst = now - self._selection_time < SELECTION_BURST
            self._selection_time = now
        if burst:
            self.publish("selectedKey", self._selected[self.mode], self.selectedKeyChanged)
            self.publish("rowIndex", self.selected_index(), self.rowIndexChanged)
            self.selection_timer.start()
            return
        self.selection_timer.stop()
        self.publish_selection()

    @Slot()
    def publish_selection(self):
        """Reference, progression & sessions of selected row, told only if changed (stats saved every lap)"""
        if self._released:
            return
        self.publish("selectedKey", self._selected[self.mode], self.selectedKeyChanged)
        self._reference = self.reference_data()
        self._progression, self._sessions = self.history_data()
        self._has_laps = bool(self.lap_folder())
        self.publish("selection", (self.mode, self._selected[self.mode], self._session_filter, self._reference,
                                   self._progression, self._sessions, self._has_laps), self.selectionChanged)
        self.publish("rowIndex", self.selected_index(), self.rowIndexChanged)
        self.update_stints()

    # Stints & consistency of selected vehicle: recorded laps of its track & class folder
    def update_stints(self, background: bool = True):
        """Recorded laps of selected vehicle read (in a thread if background): stint pace & degradation by tyre
        compound, consistency of each session & of the track"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        folder = self.lap_folder(vehicle) if vehicle else ""
        laps = f"{folder}|{vehicle}"
        key = f"{laps}|{lap_folder_stamp(folder)}" if folder else laps
        if not vehicle or not folder:
            self._laps_generation += 1  # running or waiting read ignored
            self._laps_job = None
            self.laps_timer.stop()
        if not vehicle:
            self._laps_key, self._stints = key, {}
            self.lapsChanged.emit()
            return
        if not folder:
            self._laps_key = key
            self._stints = {"visible": True, "busy": False,
                            "note": tr("No recorded lap for this vehicle class: enable the Recorder module, then drive a few laps.")}
            self.lapsChanged.emit()
            return
        if key == self._laps_key and self._stints.get("visible"):
            return  # same laps shown (read again once laps folder changed: lap recorded or removed)
        same_laps = self._laps_key.rpartition("|")[0] == laps and self._stints.get("visible") and "note" not in self._stints
        self._laps_key = key
        if same_laps:  # new lap recorded: stints shown kept while read again
            self._stints = {**self._stints, "busy": True}
        else:
            self._stints = {"visible": True, "busy": True, "note": tr("Reading recorded laps...")}
        self.lapsChanged.emit()
        self._laps_generation += 1
        job = (key, folder, vehicle, self._laps_generation)
        if not background:
            self.read_stints(*job)
            return
        self._laps_job = job
        self.laps_timer.start()  # selection changing quickly (arrow keys): read once it settles

    @Slot()
    def start_laps_read(self):
        """Debounced read started in background, once the running read (if any) has finished"""
        if self._laps_running or self._laps_job is None:
            return  # started when running read is loaded
        job, self._laps_job = self._laps_job, None
        self._laps_running = job[3]
        # Lap infos of last folders read only (one read at a time), result handed over on the UI thread
        self.jobs.run("laps", partial(read_stints_report, self._lap_infos, *job), self.stints_read)

    def read_stints(self, key: str, folder: str, vehicle: str, generation: int):
        """Recorded laps read now (UI thread)"""
        self.stints_read(read_stints_report(self._lap_infos, key, folder, vehicle, generation))

    def stints_read(self, result: tuple[str, int, dict | None]):
        self.stints_loaded(*result)

    def stints_loaded(self, key: str, generation: int, report):
        """Recorded laps read: stints & consistency shown if still selected & latest read (an older read of
        same laps finishing later never overwrites newer laps)"""
        if generation == self._laps_running:
            self._laps_running = 0
            if self._laps_job is not None and not self.laps_timer.isActive():
                self.start_laps_read()  # read asked while this one was running
        if key != self._laps_key or generation != self._laps_generation:
            return
        self._stints = self.stints_data(report) if isinstance(report, dict) else {
            "visible": True, "busy": False, "note": tr("Unable to read recorded laps.")}
        self.lapsChanged.emit()

    def stints_data(self, report: dict) -> dict:
        """Stints, compounds & consistency as shown: lap times, degradation per lap, coefficient of variation"""

        def slope_text(slope: float | None) -> str:
            return f"{signed(slope, 3)} s/{tr('lap')}" if slope is not None else "—"

        def slope_color(slope: float | None) -> str:
            return "" if slope is None or abs(slope) < 0.02 else "loss" if slope > 0 else "gain"

        def compound(name: str) -> str:
            return name or tr("Compound not recorded")

        def session(name: str) -> str:
            return tr(name) if name else tr("Session")

        compounds = [{"compound": compound(row["compound"]),
                      "names": row["compound"].split("/") if row["compound"] else [],  # badges: front, rear
                      "stints": row["stints"], "laps": row["laps"],
                      "pace": calc.sec2laptime_full(row["pace"]), "slope": slope_text(row["slope"]),
                      "slopeColor": slope_color(row["slope"])} for row in report["compounds"]]
        stints = [{"date": format_date(row["start"]), "session": session(row["session"]),
                   "compound": compound(row["compound"]), "laps": f"{row['clean']}/{row['laps']}",
                   "pace": calc.sec2laptime_full(row["pace"]), "slope": slope_text(row["slope"]),
                   "slopeColor": slope_color(row["slope"])}
                  for row in sorted(report["stints"], key=lambda row: -row["start"])[:MAX_STINTS]]
        sessions = [{"date": format_date(row["start"]), "session": session(row["session"]), "laps": row["clean"],
                     "index": f"{number_text(row['index'], 2)} %", "pace": calc.sec2laptime_full(row["pace"])}
                    for row in sorted(report["sessions"], key=lambda row: -row["start"])[:MAX_STINTS]]
        index = report["index"]
        return {
            "visible": True, "busy": False, "compounds": compounds, "stints": stints, "sessions": sessions,
            "index": f"{number_text(index, 2)} %" if index is not None else "",
            "indexInfo": f"{tr('Median of')} {plural(len(report['sessions']), 'session', 'sessions')}"
            if index is not None else "",
            "note": "" if stints or sessions else tr("3 clean laps or more needed in a session."),
        }

    @Property(dict, notify=lapsChanged)
    def stints(self) -> dict:
        """Stints & consistency of selected vehicle: visible, busy, note, index, compounds, stints, sessions"""
        return self._stints

    # Session history export (CSV, or JSON a friend can compare with)
    def history_records(self) -> list[SessionRecord]:
        """Session records of selected track, every track for All Tracks"""
        return [record for record in self.history if not self.selected_stats_key or record.track == self.selected_stats_key]

    @Slot(str)
    def exportHistory(self, kind: str):
        """Session history of selected track (every track for All Tracks) to CSV or JSON (friend's comparison)"""
        if not self.history_records():
            self.warning(tr("No session recorded yet: history starts with your next session."))
            return
        name = strip_invalid_char(self.selected_stats_key or tr("All Tracks"))
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        extension = "json" if kind == "json" else "csv"
        default = os.path.join(folder or os.path.expanduser("~"), f"{name} - {tr('Session History')}.{extension}")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export Session History..."), default,
                                                  "JSON (*.json)" if extension == "json" else "CSV (*.csv)")
        if filename:
            self.write_history(filename, extension)

    def write_history(self, filename: str, kind: str, decimal_point: str = "") -> bool:
        """Write session history of selected track (every track for All Tracks), CSV in system number format"""
        records = self.history_records()
        try:
            if kind == "json":
                tracks = {self.selected_stats_key} if self.selected_stats_key else set(self.stats_temp)
                stats = {track: self.stats_temp[track] for track in tracks if track in self.stats_temp}
                write_history_json(filename, history_document(records, stats, self.classes))
            else:
                decimal = decimal_point or QLocale.system().decimalPoint() or "."
                header = [tr(name) for name in HISTORY_COLUMNS]
                write_history_csv(filename, records, header, [tr(name) for name in SESSION_NAMES], decimal)
        except OSError as error:
            logger.error("DRIVER STATS: unable to export %s: %s", filename, error)
            self.warning(trm(f"Unable to export: {error}"))
            return False
        return True

    # Friend's stats: exported session history of another driver, personal bests compared track by track
    def load_friend(self, filename: str, quiet: bool = False) -> bool:
        """Friend's file read now (tests), see load_friend_file"""
        if not filename:
            return False
        try:
            self._friend = load_friend(filename)
        except ValueError as error:
            if not quiet:
                self.warning(trm(f"Unable to read friend's stats: {error}"))
            return False
        return True

    def load_friend_file(self, filename: str, chosen: bool = False):
        """Friend's file read in background, compared once read (chosen by user: saved for next time, warned if
        unreadable)"""
        if not filename or self._released:
            return
        self._friend_file = filename if chosen else ""
        self.jobs.run("friend", partial(load_friend, filename), self.friend_loaded,
                      self.friend_failed if chosen else self.friend_skipped, key="friend")

    def friend_loaded(self, friend: dict):
        if self._released:
            return
        self._friend = friend
        if self._friend_file:
            self.save_viewer_config(friend_file=self._friend_file)
            self._friend_file = ""
        self.refresh_friend()

    def friend_failed(self, error: BaseException):
        self._friend_file = ""
        if isinstance(error, ValueError) and not self._released:
            self.warning(trm(f"Unable to read friend's stats: {error}"))
        else:
            self.friend_skipped(error)

    @staticmethod
    def friend_skipped(error: BaseException):
        """Friend's file of last time unreadable (moved): nothing compared"""
        if not isinstance(error, ValueError):
            logger.warning("DRIVER STATS: friend's stats not read", exc_info=(type(error), error, error.__traceback__))

    @Slot()
    def importFriend(self):
        """Compare with a friend's exported session history (JSON)"""
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        filename, _ = QFileDialog.getOpenFileName(self._window, tr("Compare With a Friend's Stats..."),
                                                  folder or os.path.expanduser("~"), "JSON (*.json)")
        if filename:
            self.load_friend_file(filename, chosen=True)

    @Slot()
    def clearFriend(self):
        self._friend = None
        self._friend_file = ""
        self.jobs.cancel("friend")  # file being read dropped
        self.save_viewer_config(friend_file="")
        self.refresh_friend()

    @Property(dict, notify=friendChanged)
    def friend(self) -> dict:
        """Friend's personal bests against own: name, rows (track, class, lap times, gap), summary"""
        return self._friend_view

    def refresh_friend(self):
        self._friend_view = self.friend_data()
        self.publish("friend", self._friend_view, self.friendChanged)

    def friend_data(self) -> dict:
        """Friend's personal bests against own on selected track (every track both drove for All Tracks)"""
        if self._friend is None:
            return {"visible": False}
        tracks = [self.selected_stats_key] if self.selected_stats_key else None
        rows = compare_friend(self.stats_temp, self.class_of, self._friend, tracks)
        shown = []
        for row in rows:
            gap = row["gap"]
            shown.append({
                "track": row["track"], "vehicleClass": row["class"],
                "mine": calc.sec2laptime_full(row["mine"]) if row["mine"] else "-",
                "friend": calc.sec2laptime_full(row["friend"]) if row["friend"] else "-",
                "gap": ("" if not (row["mine"] and row["friend"]) else number_text(0.0, 3) if abs(gap) < 0.0005
                        else signed(gap, 3)),
                "gapColor": "" if abs(gap) < 0.0005 else "loss" if gap > 0 else "gain",
            })
        compared = [row for row in rows if row["mine"] and row["friend"]]
        faster = sum(1 for row in compared if row["gap"] < 0)
        return {"visible": True, "name": self._friend["name"], "rows": shown,
                "summary": trm(f"Faster on {faster} of {len(compared)}") if compared else
                tr("No track & class driven by both of you here.")}

    def reference_data(self) -> dict:
        """Level ladder of selected vehicle, gap to reference, next level, fastest car (empty: reason)"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        if not self.selected_stats_key:
            return {"visible": False, "reason": ""}
        if not vehicle:
            return {"visible": False, "reason": tr("Select a vehicle to compare its lap times.")}
        data = self.selected_stats_dict.get(vehicle, {})
        reference = self.reference_of(vehicle)
        if reference is None:
            if not self.references.entries:
                reason = tr("Community lap times not downloaded yet.")
            elif not lap_reference.vehicle_class_of(vehicle) and not lap_reference.vehicle_class_of(
                    self.classes.get(vehicle, "")):
                reason = tr("Vehicle class unknown: set vehicle classification to class (Class - Brand) to compare.")
            else:
                reason = trm(f"No community lap time for {self.selected_stats_key} in this class.")
            return {"visible": False, "reason": reason, "vehicle": vehicle}
        best = valid_laptime(data.get("pb", 0))
        marks = [(tr("PB"), best), (tr("Qualifying"), valid_laptime(data.get("qb", 0))),
                 (tr("Race"), valid_laptime(data.get("rb", 0)))]
        marks_by_level: dict[int, list[str]] = {}
        for text, laptime in marks:
            if laptime > 0:
                marks_by_level.setdefault(reference.level(laptime), []).append(text)
        ladder = []
        for level, name in enumerate(LEVELS):
            limit = reference.level_limit(level)
            faster_limit = reference.level_limit(level - 1) if level > 0 else 0.0
            if level == len(LEVELS) - 1 and faster_limit:
                limit_text = f"> {calc.sec2laptime_full(faster_limit)}"
            else:
                limit_text = f"≤ {calc.sec2laptime_full(limit)}" if limit else "-"
            mark = marks_by_level.get(level, [])
            ladder.append({"name": tr(name), "color": self.level_color(level), "limit": limit_text,
                           "marks": "  ".join(f"← {text}" for text in mark), "active": bool(mark), "pills": mark,
                           "letter": level_letter(level)})
        patch = f" · {tr('patch')} {reference.patch}" if reference.patch else ""
        next_level = {}
        if best > 0:
            gap = best - reference.reference
            gap_text = trm(f"Personal best {calc.sec2laptime_full(best)}: {signed(gap, 2)} s "
                           f"({number_text(reference.percent(best), 2)} %) "
                           f"to reference {calc.sec2laptime_full(reference.reference)}")
            level, to_find = reference.next_level(best)
            if level >= 0:
                next_text = trm(f"Next level {tr(LEVELS[level])}: {number_text(to_find, 2)} s to find")
                next_level = {"name": tr(LEVELS[level]), "color": self.level_color(level), "letter": level_letter(level),
                              "toFind": signed(-to_find, 2, " s")}
            else:
                next_text = tr("Top level reached") if reference.level(best) == 0 else ""
        else:
            gap_text = trm(f"Reference {calc.sec2laptime_full(reference.reference)}, no personal best yet")
            next_text = ""
        fastest = ""
        if reference.fastest_car and reference.fastest_time:
            fastest = trm(f"Fastest car: {reference.fastest_car} · {calc.sec2laptime_full(reference.fastest_time)}")
        level = reference.level(best) if best > 0 else -1
        return {"visible": True, "reason": "", "vehicle": vehicle,
                "detail": f"{reference.track} · {reference.vehicle_class}{patch}", "ladder": ladder,
                "gap": gap_text, "next": next_text, "fastest": fastest, "gauge": self.gauge_data(reference, marks),
                "level": level_text(level) if level >= 0 else "", "levelColor": self.level_color(level),
                "letter": level_letter(level), "percent": f"{number_text(reference.percent(best), 2)} %" if best > 0 else "",
                "best": calc.sec2laptime_full(best) if best > 0 else "", "nextLevel": next_level,
                "referenceTime": calc.sec2laptime_full(reference.reference) if reference.reference > 0 else "",
                "gapTime": signed(best - reference.reference, 2, " s") if best > 0 and reference.reference > 0 else ""}

    def gauge_data(self, reference: LapReference, marks: list[tuple[str, float]]) -> dict:
        """Level scale: levels from slowest (left) to fastest (right), positions (0-1) of lap time marks

        Levels take the same width, a lap time is placed in its level by its share of the level lap time range
        (Alien & Offline as wide as their neighbor). Empty if ladder unknown.
        """
        count = len(LEVELS)
        limits = [reference.level_limit(level) for level in range(count - 1)]
        if not all(limits):
            return {}
        ranges = []  # (fastest, slowest) lap time of each level
        for level in range(count):
            if level == 0:
                ranges.append((limits[0] - (limits[1] - limits[0]), limits[0]))
            elif level == count - 1:
                ranges.append((limits[-1], limits[-1] + (limits[-1] - limits[-2])))
            else:
                ranges.append((limits[level - 1], limits[level]))

        def position(laptime: float) -> float:
            level = reference.level(laptime)
            fast, slow = ranges[level]
            share = (slow - laptime) / (slow - fast) if slow > fast else 0.5
            return (count - 1 - level + min(max(share, 0.0), 1.0)) / count

        segments = []
        for level in reversed(range(count)):
            fast, slow = ranges[level]
            if level == count - 1:
                limit = f"> {calc.sec2laptime_full(fast)}"
            else:
                limit = f"≤ {calc.sec2laptime_full(slow)}"
            segments.append({"name": tr(LEVELS[level]), "letter": level_letter(level), "color": self.level_color(level),
                             "limit": limit})
        markers = []
        for index, (name, laptime) in enumerate(marks):
            if laptime <= 0:
                continue
            level = reference.level(laptime)
            markers.append({
                "label": name, "short": name[:1].upper(), "main": index == 0, "pos": round(position(laptime), 4),
                "time": calc.sec2laptime_full(laptime), "color": self.level_color(level),
                "tip": f"{name} {calc.sec2laptime_full(laptime)} · {level_text(level)} · {number_text(reference.percent(laptime), 2)} %",
            })
        markers.sort(key=lambda marker: bool(marker["main"]))  # personal best drawn last (on top)
        return {"segments": segments, "markers": markers}

    def history_data(self) -> tuple[dict, list[dict]]:
        """Progression chart (best lap of each session, personal best so far) & sessions list"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        if not vehicle:
            return {"visible": False, "points": [], "info": ""}, []
        data = self.selected_stats_dict.get(vehicle, {})
        best = valid_laptime(data.get("pb", 0))
        records = filter_sessions(self.history_index.get((self.selected_stats_key, vehicle), []), self._session_filter)
        progression = best_progression(records, best)
        reference = self.reference_of(vehicle)
        chart = self.chart_data(progression, reference)
        lines = []
        if best > 0:
            date = best_lap_date(records, best)
            pb_record = next((record for record in records if record.time == date), None) if date else None
            version = self.record_version(pb_record) if pb_record is not None else ""
            if not date:  # lap time completed from race results, or recorded before session history
                pb_result = self.best_lap_result(self.selected_stats_key, vehicle, best)
                if pb_result is not None:
                    date, version = pb_result.end, pb_result.game_version
            if date:
                line = trm(f"PB {calc.sec2laptime_full(best)} set on {format_date(date)}")
                lines.append(f"{line} · {tr('Version')} {version}" if version else line)
        if records:
            lines.append(f"{plural(len(records), 'session', 'sessions')} · {tr('last driven')} "
                         f"{format_date(records[-1].time)}")
        else:
            lines.append(tr("No session recorded yet: history starts with your next session."))
        chart["info"] = "\n".join(lines)
        chart["sessions"] = len(records)  # all sessions (list shows the newest MAX_SESSIONS)
        sessions = []
        for record in reversed(records[-MAX_SESSIONS:]):
            laptime = record.best if record.best > 0 and not (best and record.best < best - 0.0005) else 0.0
            summary = self.record_result(record)
            version = record.game_version or (summary.game_version if summary is not None else "")
            tip = [f"{format_duration(record.seconds)} · {parse_display_value('meters', record.meters)} "
                   f"{tr(format_header_key('meters')).lower()}"]
            if summary is not None:
                tip += result_details(summary)
                tip.append(tr("Click to show race results"))
            elif version:
                tip.append(f"{tr('Version')} {version}")
            sessions.append({
                "date": format_date(record.time),
                "session": session_name(record.session),
                "kind": session_kind(record.session),
                "best": calc.sec2laptime_full(laptime) if laptime else "-",
                "laps": f"{record.valid}/{record.valid + record.invalid}",
                "result": race_result(record),
                "podium": record.position if record.finish == 1 and 0 < record.position <= 3 else 0,
                "pb": bool(best and laptime and abs(laptime - best) < 0.0005),
                "tip": "\n".join(tip),
                "rank": summary_rank(summary) if summary is not None and not race_result(record) else "",
                "incidents": summary.contacts + summary.penalties if summary is not None else 0,
                "version": version,
                "results": summary.path if summary is not None else "",
            })
        return chart, sessions

    def chart_data(self, progression: list[tuple[SessionRecord, float]], reference: LapReference | None) -> dict:
        """Points in chart coordinates (0-1, faster higher), level limits, labels & date marks"""
        if len(progression) < 2:
            return {"visible": False, "points": [], "limits": [], "dates": [], "top": "", "bottom": ""}
        fastest = min(best for _, best in progression)
        slowest = min(max(record.best for record, _ in progression), fastest * 1.04)  # slow sessions clipped
        slowest = max(slowest, fastest + 0.5)
        margin = (slowest - fastest) * 0.08
        low, high = fastest - margin, slowest + margin

        def y_of(laptime: float) -> float:
            return (min(max(laptime, low), high) - low) / (high - low)

        count = len(progression)
        points = []
        last_best = MAX_SECONDS
        for index, (record, best_so_far) in enumerate(progression):
            new_best = record.best < last_best
            tip = f"{format_date(record.time)} · {session_name(record.session)}\n{calc.sec2laptime_full(record.best)}"
            if new_best:
                tip += f" · {tr('PB')}"
            points.append({"x": index / (count - 1), "y": y_of(record.best), "pbY": y_of(best_so_far),
                           "newPb": new_best, "clipped": record.best > high, "tip": tip,
                           "kind": session_kind(record.session)})
            last_best = best_so_far
        limits = []
        if reference is not None:
            for level in range(len(LEVELS) - 1):
                limit = reference.level_limit(level)
                if low < limit < high:
                    limits.append({"y": y_of(limit), "color": self.level_color(level), "name": tr(LEVELS[level]),
                                   "letter": level_letter(level)})
        marks = sorted({0, count // 2, count - 1}) if count >= 3 else [0, count - 1]
        dates = [{"x": index / (count - 1), "text": format_date(progression[index][0].time)} for index in marks]
        ticks = [{"y": y_of(value), "text": calc.sec2laptime_full(value)} for value in chart_ticks(low, high)]
        return {"visible": True, "points": points, "limits": limits, "dates": dates, "ticks": ticks,
                "top": calc.sec2laptime_full(fastest), "bottom": calc.sec2laptime_full(high), "pbY": y_of(fastest)}

    @Property(dict, notify=selectionChanged)
    def reference(self) -> dict:
        return self._reference

    @Property(dict, notify=selectionChanged)
    def progression(self) -> dict:
        return self._progression

    @Property(list, notify=selectionChanged)
    def sessions(self) -> list[dict]:
        return self._sessions

    @Property(list, constant=True)
    def sessionFilters(self) -> list[str]:
        return [tr(name) for name in SESSION_FILTERS]

    @Property(int, notify=selectionChanged)
    def sessionFilter(self) -> int:
        return self._session_filter

    @Slot(int)
    def setSessionFilter(self, index: int):
        """Progression & sessions of a session type: all, practice, qualifying, race"""
        self._session_filter = index if 0 <= index < len(SESSION_GROUPS) else 0
        self.update_selection()

    # Edits: applied to stats file read again, undo & redo
    def confirm(self, message: str) -> bool:
        return bool(self._window.confirm_operation(message=message))

    def warning(self, text: str):
        QMessageBox.warning(self._window, tr("Error"), text)

    @staticmethod
    def load_fresh_stats() -> dict | None:
        """Stats file as saved now (stats module may have saved since loaded), None if invalid"""
        stats_user = load_stats_json_file(filepath=cfg.path.config)
        if stats_user is None:
            return None
        return validate_stats_file(stats_user)

    def stats_unreadable(self):
        self.warning(tr("Unable to read stats file."))

    def stats_unsaved(self):
        self.warning(tr("Unable to save stats file."))

    def stats_unsaved_history_changed(self):
        self.warning(tr("Unable to save stats file. Session history was changed anyway, use Undo to revert it."))

    @staticmethod
    def save_edit(stats_user: dict, removed: Iterable[SessionRecord], added: Iterable[SessionRecord],
                  history: list[SessionRecord] | None = None) -> bool | None:
        """Save edited stats & history change (STATS_LOCK held, worker thread)

        History changed first: a change (records removed or added once) undone safely if stats not saved,
        tried again a few times.

        Args:
            history: records of history file loaded already (STATS_LOCK held since), else file read.

        Returns:
            True if saved, False if not saved (both files kept),
            None if stats not saved and history change could not be undone (history changed only).
        """
        removed, added = tuple(removed), tuple(added)
        try:
            written = replace_records(cfg.path.config, removed, added, history)
        except OSError:  # history unreadable (never rewritten as empty) or not saved
            return False
        if save_stats_json_file(stats_user=stats_user, filepath=cfg.path.config):
            return True
        for attempt in range(ROLLBACK_ATTEMPTS):
            if attempt:
                time.sleep(ROLLBACK_DELAY)  # worker thread: page not held up
            try:
                replace_records(cfg.path.config, added, removed, written)  # history change undone
                return False
            except OSError as error:
                logger.warning("STATS: history change not undone (attempt %s): %s", attempt + 1, error)
        return None

    def edit_stats(self, path: tuple[str, ...], value: Any,
                   history_change: Callable[[list[SessionRecord]], tuple[list, list]] | None = None) -> bool:
        """Set stats at path (None removes it, empty path: whole file), history changed, undo recorded

        Saved on worker thread after edits asked before (see run_locked), page updated once saved.

        Args:
            history_change: history records -> (records removed, records added), run on worker thread.

        Returns:
            True if done now (never: saved in background).
        """
        return self.run_locked(StatsJob("edit", self.write_edit, (path, value, history_change), self.edit_written))

    @classmethod
    def write_edit(cls, path: tuple[str, ...], value: Any,
                   history_change: Callable[[list[SessionRecord]], tuple[list, list]] | None,
                   ) -> tuple[str, StatsEdit | None]:
        """Edit applied to stats file read again (STATS_LOCK held, worker thread), see edit_stats

        Returns:
            Outcome ("saved", "history" changed only, "unsaved", "unreadable"), edit to undo.
        """
        with STATS_LOCK:  # held already (run_locked), reentrant
            stats_user = cls.load_fresh_stats()
            if stats_user is None:
                return "unreadable", None
            backup_stats_file(cfg.path.config)
            before = stats_entry(stats_user, path) if path else copy.deepcopy(stats_user)
            if path:
                set_stats_entry(stats_user, path, value)
            else:
                stats_user = copy.deepcopy(value)
            removed: tuple = ()
            added: tuple = ()
            history = None
            if history_change is not None:
                try:
                    history = load_history(cfg.path.config, strict=True)
                except OSError:  # never rewritten from empty history
                    return "unreadable", None
                removed_list, added_list = history_change(history)
                removed, added = tuple(removed_list), tuple(added_list)
            saved = cls.save_edit(stats_user, removed, added, history)
            if saved is False:  # not saved: no undo recorded
                return "unsaved", None
            if saved is None:  # history changed only: its undo recorded
                return "history", StatsEdit(path, None, None, removed, added, history_only=True)
        return "saved", StatsEdit(path, before, copy.deepcopy(value), removed, added)

    def edit_written(self, result: tuple[str, StatsEdit | None]):
        """Edit saved (UI thread): undo recorded & page reloaded, or warned"""
        outcome, edit = result
        self._backups = None  # listed again (backup made before edit)
        if outcome == "unreadable":
            self.stats_unreadable()
        elif outcome == "unsaved":
            self.stats_unsaved()
        elif edit is not None:
            self.edit_done(edit)
            if outcome == "history":
                self.stats_unsaved_history_changed()

    def edit_done(self, edit: StatsEdit):
        """Edit saved: undo recorded, page reloaded"""
        self._edits_undo.append(edit)
        del self._edits_undo[:-MAX_UNDO]
        self._edits_redo.clear()
        self.reload_stats()

    @classmethod
    def apply_edit(cls, edit: StatsEdit, undo: bool) -> bool:
        """Apply edit again (redo) or its reverse (undo, stats recorded since kept) on stats file read again

        Called with STATS_LOCK held (worker thread, see run_locked), False if stats file unreadable or not saved.
        """
        with STATS_LOCK:
            if edit.history_only:
                try:
                    if undo:
                        replace_records(cfg.path.config, edit.history_after, edit.history_before)
                    else:
                        replace_records(cfg.path.config, edit.history_before, edit.history_after)
                except OSError:
                    return False
                return True
            stats_user = cls.load_fresh_stats()
            if stats_user is None:
                return False
            if not edit.path:  # whole file (backup restored)
                stats_user = copy.deepcopy(edit.before if undo else edit.after)
            elif undo:
                current = stats_entry(stats_user, edit.path)
                set_stats_entry(stats_user, edit.path, merge_stats_entry(current, edit.before, edit.path))
            else:
                set_stats_entry(stats_user, edit.path, edit.after)
            if undo:
                return bool(cls.save_edit(stats_user, edit.history_after, edit.history_before))
            return bool(cls.save_edit(stats_user, edit.history_before, edit.history_after))

    @Slot()
    def undo(self):
        """Undo last edit (saved in background), not while an edit is being saved (not in undo stack yet)"""
        if not self._edits_undo or self.editing:
            return
        edit = self._edits_undo.pop()
        self.run_locked(StatsJob("edit", self.apply_edit, (edit, True), self.edit_applied, (edit, True)))

    @Slot()
    def redo(self):
        """Redo last undone edit (saved in background), not while an edit is being saved"""
        if not self._edits_redo or self.editing:
            return
        edit = self._edits_redo.pop()
        self.run_locked(StatsJob("edit", self.apply_edit, (edit, False), self.edit_applied, (edit, False)))

    def edit_applied(self, done: bool, edit: StatsEdit, undo: bool):
        """Undo or redo saved (UI thread): moved to other stack (back to its stack if not saved), page reloaded"""
        if done:
            (self._edits_redo if undo else self._edits_undo).append(edit)
        else:
            (self._edits_undo if undo else self._edits_redo).append(edit)
            self.stats_unreadable()
        if undo:
            self.reload_stats(select=edit.path[0] if edit.path else None)
        else:
            self.reload_stats(select=edit.path[0] if len(edit.path) > 1 else None)

    @Property(bool, notify=editsChanged)
    def canUndo(self) -> bool:
        return bool(self._edits_undo)

    @Property(bool, notify=editsChanged)
    def canRedo(self) -> bool:
        return bool(self._edits_redo)

    @Property(bool, notify=tracksChanged)
    def canDelete(self) -> bool:
        return bool(self.selected_stats_key)

    @Slot(str)
    def deleteTrack(self, track: str = ""):
        """Delete stats of track (empty: selected track) & its session history"""
        if self.editing:  # stats shown not up to date yet
            return
        track = track or self.selected_stats_key
        if not track or track not in self.stats_temp:
            self.warning(tr("No data found."))
            return
        msg_text = (
            "Delete all stats from<br>"
            f"<b>{track}</b> ?<br><br>"
            "Undo with Ctrl+Z while this page is open."
        )
        if self.confirm(msg_text):
            self.edit_stats((track,), None, lambda records: (
                [record for record in records if record.track == track], []))

    @Slot()
    def removeVehicle(self):
        """Remove selected vehicle stats & its session history"""
        if self.editing:
            return
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        if not vehicle:
            self.warning(tr("No data selected."))
            return
        if vehicle not in self.selected_stats_dict:
            self.warning(tr("No data found."))
            return
        track = self.selected_stats_key
        msg_text = (
            f"Remove all stats from <b>{vehicle}</b>?<br><br>"
            "Undo with Ctrl+Z while this page is open."
        )
        if self.confirm(msg_text):
            self.edit_stats((track, vehicle), None, lambda records: (
                [record for record in records if record.track == track and record.vehicle == vehicle], []))

    @Slot(str, str)
    def resetLapTime(self, vehicle: str, column: str):
        """Reset lap time of vehicle, its session bests in history too (progression)"""
        if not DriverStats.is_lap_time(column) or not self.selected_stats_key or self.editing:
            return
        data = self.selected_stats_dict.get(vehicle, {})
        laptime = valid_laptime(data.get(column, 0))
        if not laptime:
            self.warning(tr("No lap time found."))
            return
        msg_text = (
            f"Reset <b>{calc.sec2laptime_full(laptime)}</b> lap time for <b>{vehicle}</b>?<br><br>"
            "Undo with Ctrl+Z while this page is open."
        )
        if not self.confirm(msg_text):
            return
        track = self.selected_stats_key
        sessions = {"pb": (), "qb": SESSION_GROUPS[2], "rb": SESSION_GROUPS[3]}[column]

        def reset_history(records: list[SessionRecord]) -> tuple[list, list]:
            reset = [record for record in records
                     if record.track == track and record.vehicle == vehicle and abs(record.best - laptime) < 0.0005
                     and (not sessions or record.session in sessions)]
            return reset, [record._replace(best=0.0) for record in reset]

        self.edit_stats((track, vehicle, column), DriverStats.__dict__[column], reset_history)

    # Backups
    @Property(list, notify=editsChanged)
    def backups(self) -> list[dict]:
        return self.cached_backups()

    def cached_backups(self) -> list[dict]:
        """Automatic backups, listed once (again after an edit makes one), not on every table refresh"""
        if self._backups is None:
            self._backups = self.backup_list()
        return self._backups

    @staticmethod
    def backup_list() -> list[dict]:
        """Automatic backups made before edits, newest first"""
        return [{"name": name, "date": QDateTime.fromSecsSinceEpoch(int(created)).toString(
                    date_locale().dateTimeFormat(QLocale.FormatType.ShortFormat))}
                for name, created in list_stats_backups(cfg.path.config)]

    @Slot(str)
    def restoreBackup(self, name: str):
        """Stats file as saved in backup (undo: stats before restore), read in background once confirmed"""
        if self.editing:
            return
        date = next((entry["date"] for entry in self.cached_backups() if entry["name"] == name), name)
        if not self.confirm(trm(f"Restore stats saved on <b>{date}</b>?<br><br>Undo with Ctrl+Z while this page is open.")):
            return
        self.jobs.run("stats backup", partial(read_stats_backup, cfg.path.config, name), self.backup_read,
                      self.backup_failed, key="backup")

    def backup_read(self, stats_backup: dict | None):
        """Backup read (checked): restored as an edit"""
        if self._released or self.editing:
            return
        if stats_backup is None:
            self.warning(tr("Unable to read stats file."))
            return
        self.edit_stats((), stats_backup)

    def backup_failed(self, error: BaseException):
        logger.warning("DRIVER STATS: backup not read", exc_info=(type(error), error, error.__traceback__))
        if not self._released:
            self.warning(tr("Unable to read stats file."))

    # Context menu
    @Slot(str, str, result=list)
    def rowActions(self, key: str, column: str) -> list[dict]:
        """Right click menu entries of row & column: id, text, enabled"""
        actions = []
        editable = not self.editing  # edit being saved: stats shown not up to date yet
        if not self.selected_stats_key:
            actions += [{"id": "show", "text": tr("Show Track"), "enabled": True},
                        {"id": "delete", "text": tr("Delete Track"), "enabled": editable}]
        elif column == "vehicle":
            actions.append({"id": "remove", "text": tr("Remove Vehicle"), "enabled": editable})
        elif DriverStats.is_lap_time(column):
            laptime = valid_laptime(self.selected_stats_dict.get(key, {}).get(column, 0))
            actions.append({"id": "reset", "text": tr("Reset Lap Time"), "enabled": bool(laptime) and editable})
        actions.append({"id": "laps", "text": tr("Open Recorded Laps"), "enabled": bool(self.lap_folder(key))})
        return actions

    @Slot(str, str, str)
    def runAction(self, action: str, key: str, column: str):
        self.selectRow(key)
        if action == "show":
            self.openRow(key)
        elif action == "delete":
            self.deleteTrack(key)
        elif action == "remove":
            self.removeVehicle()
        elif action == "reset":
            self.resetLapTime(key, column)
        elif action == "laps":
            self.openLapViewer()

    # Other tools
    def lap_folder(self, key: str = "") -> str:
        """Recorded laps folder (track & class) of vehicle (All Tracks: of a class of track), empty if none"""
        key = key or self.selected_row_key()
        if not key:
            return ""
        if self.selected_stats_key:
            candidates = [(self.selected_stats_key, key)]
        else:
            candidates = [(key, str(vehicle)) for vehicle in self.stats_temp.get(key, {})]
        for track, vehicle in candidates:
            folder = combo_name(track, self.class_of(vehicle))
            if os.path.isdir(os.path.join(cfg.path.telemetry, folder)):
                return folder
        return ""

    @Property(bool, notify=selectionChanged)
    def hasLaps(self) -> bool:
        """Recorded laps of selected row (checked when selected)"""
        return self._has_laps

    @Slot()
    def openLapViewer(self):
        """Recorded laps of selected vehicle class in lap telemetry viewer, its personal best lap as reference"""
        folder = self.lap_folder()
        if not folder:
            self.warning(tr("No recorded lap for this vehicle class: enable the Recorder module, then drive a few laps."))
            return
        from ..tools_view import open_tool

        window = self._window
        parent = window.window() if getattr(window, "in_app_page", False) else window
        viewer = open_tool("lap_viewer.LapViewer", parent)
        backend = getattr(viewer, "backend", None)
        if backend is None:
            return
        if folder not in backend.tracks:  # recorded since lap viewer opened
            backend.refresh()
        backend.currentTrack = folder
        if self.selected_stats_key:
            path = self.best_lap_path(backend, self.selected_row_key())
            if path:
                backend.setReference(path)

    def best_lap_path(self, lap_backend, vehicle: str) -> str:
        """Recorded lap file of vehicle personal best (else its fastest valid lap), empty if none"""
        best = valid_laptime(self.selected_stats_dict.get(vehicle, {}).get("pb", 0))
        laps = [entry for entry in getattr(lap_backend, "entries", [])
                if entry.file.valid and entry.file.lap_time > 0 and lap_matches_vehicle(entry.info, vehicle)]
        if not laps:
            return ""
        fastest = min(laps, key=lambda entry: entry.file.lap_time)
        exact = [entry for entry in laps if best and abs(entry.file.lap_time - best) < 0.002]
        return (exact[0] if exact else fastest).file.path

    @Slot()
    def openMap(self):
        """Track map of selected track"""
        if not self.selected_stats_key:
            return
        viewer = TrackMapViewer(self._window)
        viewer.show()
        # Loaded in the page shown: viewer already open as page is shown instead (this copy deleted)
        shown: Any = viewer.shown_dialog()
        shown.backend.load_map(cfg.path.track_map, strip_invalid_char(self.selected_stats_key))

    @Slot(bool)
    def exportCsv(self, raw: bool = False):
        """Table shown (visible columns) to CSV file"""
        if not self._table:
            return
        name = strip_invalid_char(self.selected_stats_key or tr("All Tracks"))
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        default = os.path.join(folder or os.path.expanduser("~"), f"{name} - {tr('Driver Stats Viewer')}.csv")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename:
            self.write_csv(filename, raw=raw)

    def write_csv(self, filename: str, decimal_point: str = "", raw: bool = False) -> bool:
        """Visible columns of table, number format of system locale (decimal comma & semicolon in French)

        Args:
            raw: values in base units without formatting (lap times in seconds, distance in meters...).
        """
        decimal = decimal_point or QLocale.system().decimalPoint() or "."
        delimiter = ";" if decimal == "," else ","
        keys = self.visible_keys()
        header = []
        for key in keys:
            label = self._labels.get(key, key)
            unit = RAW_UNITS.get("pb" if key.startswith("class:") else key, "") if raw else ""
            header.append(f"{label} ({unit})" if unit else label)
        try:
            with open(filename, "w", newline="", encoding="utf-8-sig") as file:  # BOM: Excel reads UTF-8
                writer = csv.writer(file, delimiter=delimiter)
                writer.writerow(header)
                for _, cells in self._table:
                    if raw:
                        writer.writerow([csv_number(cells[key].raw if key in cells else None, decimal) for key in keys])
                    else:
                        writer.writerow([csv_text(cells[key].text, decimal) if key in cells else "" for key in keys])
        except OSError as error:
            logger.error("DRIVER STATS: unable to export %s: %s", filename, error)
            self.warning(trm(f"Unable to export: {error}"))
            return False
        return True
