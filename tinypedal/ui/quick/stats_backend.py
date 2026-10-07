#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
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
recorded since. The page never waits for STATS_LOCK: while stats module saves, reloads & edits wait in
order and are tried again shortly (see run_locked). Stats & history files saved by stats module are reloaded at once (page shown), history
only when its file changed (stats file is saved every lap while driving).

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
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import date, timedelta
from statistics import median_low
from typing import Any, NamedTuple

from PySide6.QtCore import (
    Property,
    QDate,
    QDateTime,
    QFileSystemWatcher,
    QLocale,
    QObject,
    QStandardPaths,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPalette
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_common import MAX_SECONDS, TEXT_NOLAPTIME
from ...const_file import ConfigType
from ...formatter import strip_invalid_char
from ...i18n import current_language, tr, trm
from ...setting import cfg
from ...userfile import lap_reference
from ...userfile.brands import select_brand_name
from ...userfile.driver_history import (
    SESSION_GROUPS,
    SessionRecord,
    best_lap_date,
    best_progression,
    filter_sessions,
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
from .game_pictures import brand_logo_url, notifier, track_logo_url
from .models import DictListModel
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
LOCK_RETRY_MS = 25  # stats files busy (stats module saving): reload or edit tried again after this time
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
    "theory": "Theoretical best: sum of best sectors of the class (all brands), from Sectors module",
    "potential": "Personal best minus theoretical best",
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


def date_locale() -> QLocale:
    """Date format of system, or of app language if system speaks another one"""
    system = QLocale.system()
    code = current_language()
    if system.name().split("_")[0] == code:
        return system
    return QLocale(code)


def format_date(timestamp: float) -> str:
    """Short date in language format (24/10/2025 in French), "-" if none"""
    if timestamp <= 0:
        return "-"
    day = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    return date_locale().toString(day, QLocale.FormatType.ShortFormat)


def format_day(day: date) -> str:
    """Short date of a calendar day in language format"""
    return date_locale().toString(QDate(day.year, day.month, day.day), QLocale.FormatType.ShortFormat)


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
        return f"{value:.0f} %"
    if key == "speed":
        if cfg.units["speed_unit"] == "KPH":
            value = units.mps_to_kph(value)
        elif cfg.units["speed_unit"] == "MPH":
            value = units.mps_to_mph(value)
        return f"{value:.1f}"
    if key == "consumption":
        if cfg.units["odometer_unit"] == "Mile":
            value = value / 100000 * (100 / units.meter_to_mile(1.0))
        if cfg.units["fuel_unit"] == "Gallon":
            value = units.liter_to_gallon(value)
        return f"{value:.1f}"
    if key == "penalty_rate":
        return f"{value:.2f}"
    return f"{value:.1f}"


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


def vehicle_logo(vehicle: str, classes: Iterable[str] = ()) -> str:
    """Brand logo of a driver stats vehicle key: brand of "Class - Brand", or of vehicle name (none
    for a class key)"""
    if " - " in vehicle:
        return brand_logo_url(brand=vehicle.split(" - ", 1)[1].strip())
    if vehicle in classes:
        return ""
    return brand_logo_url(vehicle_name=vehicle)


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


class DriverStatsBackend(QObject):
    """Driver stats viewer page state & actions"""

    tracksChanged = Signal()
    statsChanged = Signal()  # rows, key figures, levels, activity (track or stats changed)
    sortChanged = Signal()  # sort column or order: rows moved, nothing else built again
    columnsChanged = Signal()  # columns shown, their widths
    selectionChanged = Signal()
    rowIndexChanged = Signal()  # place of selected row (selection changed or rows sorted)
    referenceChanged = Signal()
    editsChanged = Signal()
    optionsChanged = Signal()
    lapsChanged = Signal()  # stints & consistency of selected vehicle (recorded laps read)
    friendChanged = Signal()  # friend's stats compared (loaded, removed, own stats changed)
    reference_loaded = Signal(str, str)  # sheet CSV text (empty if failed), error
    laps_loaded = Signal(str, int, object)  # recorded laps folder & vehicle, read generation, stints report

    def __init__(self, parent):
        super().__init__(parent)
        self._window = parent
        self.stats_temp: dict = {}
        self.selected_stats_key = ""  # selected track, empty for All Tracks
        self.selected_stats_dict: dict = {}
        self.history: list[SessionRecord] = []
        self.history_index: dict[tuple[str, str], list[SessionRecord]] = {}
        self.classes: dict[str, str] = {}  # game class of vehicle keys, from history
        self.vehicle_last_driven: dict[tuple[str, str], float] = {}
        self.track_last_driven: dict[str, float] = {}
        self.level_counts: list[int] = [0] * len(LEVELS)
        self.unrated = 0
        self.references = LapReferenceTable()
        self.reference_error = ""
        self._downloading = False
        self._loaded = False  # first load selects current track
        self._visible = True
        self._dirty = False  # files changed while page hidden
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
        self.reference_loaded.connect(self.reference_downloaded)
        # Stints & consistency of selected vehicle from recorded laps (read in background), friend's stats
        self._stints: dict = {}
        self._laps_key = ""  # recorded laps folder & vehicle shown in stints
        self._lap_infos: dict[str, tuple[float, dict]] = {}  # lap path: file time, lap info (read once)
        self._laps_generation = 0  # latest read asked: older reads (same key, stale laps) ignored
        self._laps_job: tuple | None = None  # read waiting for debounce or running read: key, folder, vehicle, generation
        self._laps_running = 0  # generation of read running in background (0: none), one at a time
        self.laps_timer = QTimer(self)
        self.laps_timer.setSingleShot(True)
        self.laps_timer.setInterval(LAPS_DELAY)
        self.laps_timer.timeout.connect(self.start_laps_read)
        self.laps_loaded.connect(self.stints_loaded)
        notifier().changed.connect(self.pictures_changed)
        self._friend: dict | None = None
        self._friend_view: dict = {"visible": False}
        self.load_friend(str(self.viewer_config().get("friend_file", "")), quiet=True)

        # Stats & history files saved by stats module: reloaded
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.schedule_reload)
        self.watcher.fileChanged.connect(self.schedule_reload)
        self.watch_timer = QTimer(self)
        self.watch_timer.setSingleShot(True)
        self.watch_timer.setInterval(WATCH_DELAY)
        self.watch_timer.timeout.connect(self.reload_if_changed)
        # Reloads & edits waiting for stats files (STATS_LOCK held by stats module): run in order once free
        self._locked_jobs: list[Callable[[], Callable[[], Any] | None]] = []
        self.lock_timer = QTimer(self)
        self.lock_timer.setSingleShot(True)
        self.lock_timer.setInterval(LOCK_RETRY_MS)
        self.lock_timer.timeout.connect(self.run_locked_jobs)
        # Level colors depend on light or dark theme: table, tiles & charts colored again when theme changes
        self._backups: list[dict] | None = None  # automatic backups (listed again once one is made)
        self._palette_connected = False
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.paletteChanged.connect(self.palette_changed)
            self._palette_connected = True

        self.load_reference()
        self.reload_stats()
        self.watch_files()
        self.download_reference()

    @Slot()
    def palette_changed(self, *_args):
        """Light / dark theme switched: level colors (darker on light theme) computed again"""
        if self._loaded:
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
        """Lap time reference kept from last download (works offline)"""
        text, _ = lap_reference.load_cache(cfg.path.config)
        self.references = lap_reference.parse_lap_references(text) if text else LapReferenceTable()

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

        def download():
            text, error = "", "download failed"
            try:
                text, error = lap_reference.fetch_sheet(url), ""
            except (OSError, ValueError) as exc:
                text, error = "", str(exc)
            except Exception as exc:  # cut off response (IncompleteRead), bad CSV...: never left downloading
                logger.exception("STATS: lap time reference download failed")
                text, error = "", str(exc) or type(exc).__name__
            finally:
                with suppress(RuntimeError):  # page closed meanwhile
                    self.reference_loaded.emit(text, error)

        threading.Thread(target=download, daemon=True, name="Lap reference download").start()

    def reference_downloaded(self, text: str, error: str):
        self._downloading = False
        self.reference_error = error
        if text:
            try:
                lap_reference.save_cache(cfg.path.config, text)
            except OSError:  # cache not written (disk full, read only): downloaded reference still used
                logger.exception("STATS: unable to save lap time reference cache")
            self.references = lap_reference.parse_lap_references(text)
        self.referenceChanged.emit()
        self.refresh_table()

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
    def file_times(self) -> tuple[float, float]:
        """Modified time of stats & history files (0 if none)"""
        times = []
        for path in (f"{cfg.path.config}driver.stats", history_path(cfg.path.config)):
            try:
                times.append(os.path.getmtime(path))
            except OSError:
                times.append(0.0)
        return times[0], times[1]

    @staticmethod
    def history_stamp() -> tuple[int, int]:
        """History file modified time (ns) & size, (0, 0) if none: file read again once changed"""
        try:
            stat = os.stat(history_path(cfg.path.config))
        except OSError:
            return 0, 0
        return stat.st_mtime_ns, stat.st_size

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
        if self._dirty:
            self._dirty = False
            self.reload_if_changed()

    def page_hidden(self):
        self._visible = False

    def release(self):
        """Page closed: stop watching files & theme"""
        self.watch_timer.stop()
        self.laps_timer.stop()
        self.lock_timer.stop()
        self._locked_jobs.clear()
        self._laps_job = None
        paths = self.watcher.files() + self.watcher.directories()
        if paths:
            self.watcher.removePaths(paths)
        if self._palette_connected:
            self._palette_connected = False
            with suppress(RuntimeError, TypeError):
                QApplication.instance().paletteChanged.disconnect(self.palette_changed)  # type: ignore[union-attr]

    @Slot()
    def reload(self):
        self.reload_stats()

    # Stats files lock: page (GUI thread) never waits for stats module saving
    def run_locked(self, job: Callable[[], Callable[[], Any] | None]) -> bool:
        """Run job holding STATS_LOCK: now if free & no job waiting, else in order once free (tried again
        every LOCK_RETRY_MS), so the page never waits while stats module saves. Job returns what to do
        once lock released (page update, messages), or None.

        Returns:
            True if job ran now.
        """
        self._locked_jobs.append(job)
        return self.run_locked_jobs()

    @Slot()
    def run_locked_jobs(self) -> bool:
        """Run waiting jobs in order while STATS_LOCK is free, True if none left"""
        while self._locked_jobs:
            if not STATS_LOCK.acquire(blocking=False):
                self.lock_timer.start()
                return False
            try:
                after = self._locked_jobs.pop(0)()
            finally:
                STATS_LOCK.release()
            if after is not None:
                after()
        return True

    def reload_stats(self, select: str | None = None):
        """Reload stats & history files: selected track kept (current track at first load)

        Args:
            select: track key to select, else selected one (neighbor track if removed).
        """
        self.run_locked(lambda: self.read_stats_files(select))

    def read_stats_files(self, select: str | None) -> Callable[[], None]:
        """Read stats & history files (STATS_LOCK held), page updated once lock released"""
        stats_user = load_stats_json_file(filepath=cfg.path.config)
        stamp = self.history_stamp()
        if stamp != self._history_stamp:  # stats saved every lap, history at end of each stint only
            self.history = load_history(cfg.path.config)
            self._history_stamp = self.history_stamp()  # file rewritten if over limit
            self.history_index = index_history(self.history)
            self.classes = vehicle_classes(self.history)
            self.vehicle_last_driven = last_driven(self.history)
            self.track_last_driven = track_last_driven(self.history)
        return lambda: self.stats_read(stats_user, select)

    def stats_read(self, stats_user: dict | None, select: str | None):
        """Page updated with stats file read"""
        self._file_times = self.file_times()
        if stats_user is None:  # invalid file: stats shown kept
            self.refresh_table()
            return
        self.stats_temp = validate_stats_file(stats_user)
        self._laps_key = ""  # stints read again (laps recorded with new stats)
        if select is not None:
            wanted = select
        elif self._loaded:
            wanted = self.selected_stats_key
        else:
            wanted = self.initial_track()
        old_keys = [ALL_TRACKS, *(entry["key"] for entry in self._tracks[1:])]
        old_index = old_keys.index(self.selected_stats_key) if self.selected_stats_key in old_keys else 0
        self._loaded = True
        keys = self.sorted_tracks()
        current = api.read.session.track_name() if api.read is not None else ""
        self._tracks = [{"key": ALL_TRACKS, "label": tr("All Tracks"), "date": "", "current": False, "logo": ""}] + [
            {"key": key, "label": key, "date": format_date(self.track_last_driven.get(key, 0.0)),
             "current": key == current, "logo": track_logo_url(key)}
            for key in keys
        ]
        if wanted and wanted not in self.stats_temp:  # removed meanwhile: neighbor track
            index = min(max(old_index, 0), len(keys))
            wanted = keys[index - 1] if index > 0 else ALL_TRACKS
        self.select_stats(wanted)
        self.tracksChanged.emit()

    def initial_track(self) -> str:
        """Current track if it has stats, else last driven track, else All Tracks"""
        current = api.read.session.track_name() if api.read is not None else ""
        if current in self.stats_temp:
            return current
        driven = [(when, track) for track, when in self.track_last_driven.items() if track in self.stats_temp]
        return max(driven)[1] if driven else ALL_TRACKS

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
        return track_logo_url(self.selected_stats_key) if self.selected_stats_key else ""

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
        self.reload_stats()

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
        """Logos fetched from game meanwhile: track list & table shown again"""
        if not self._loaded:
            return
        for entry in self._tracks[1:]:
            entry["logo"] = track_logo_url(entry["key"])
        self._tracks = list(self._tracks)
        self.tracksChanged.emit()
        self.refresh_table()

    def refresh_table(self):
        """Table of vehicles (or tracks), sort, selection & tiles kept"""
        if self.selected_stats_key:
            rows = self.vehicle_rows()
        else:
            rows = self.track_rows()
        self._table = self.sorted_rows(rows)
        self.publish_table()
        self.refresh_tiles()
        self._track_info = self.track_info()
        if not self.selected_stats_key:
            self._activity = self.activity_data()
            self._recent = self.recent_sessions()
        selected = self._selected[self.mode]
        keys = [key for key, _ in self._table]
        if selected not in keys:
            self._selected[self.mode] = keys[0] if keys else ""
        self.columnsChanged.emit()
        self.sortChanged.emit()
        self.statsChanged.emit()
        self.editsChanged.emit()
        self.update_selection()
        self.refresh_friend()  # rows of selected track

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
                                                  logo=vehicle_logo(vehicle, self.classes.values()))}
        percent = reference.percent(best) if reference else 0.0
        cells["gap"] = Cell(f"{percent:.2f} %" if percent else "-", percent or None, round(percent, 3) if percent else None)
        level = reference.level(best) if reference else -1
        cells["level"] = Cell(level_text(level), level if level >= 0 else None, level_text(level) if level >= 0 else None,
                              self.level_color(level), level >= 0, pill=level >= 0)
        cells["theory"] = Cell(str(parse_display_value("theory", theory)), theory or None, round(theory, 3) if theory else None)
        potential = best - theory if best and theory and best >= theory - 0.0005 else None
        cells["potential"] = Cell(f"{max(potential, 0.0):.3f}" if potential is not None else "-",
                                  potential, round(max(potential, 0.0), 3) if potential is not None else None)
        for key in DERIVED_COLUMNS:
            value = derived_value(key, data)
            cells[key] = Cell(format_derived(key, value), value, round(value, 3) if value is not None else None)
        driven = self.vehicle_last_driven.get((track, vehicle), 0.0)
        cells["last"] = Cell(format_date(driven), driven or None,
                             time.strftime("%Y-%m-%d", time.localtime(driven)) if driven else None)
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
            cells: dict[str, Cell] = {"track": Cell(track, track.lower(), track, logo=track_logo_url(track))}
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
                    tip = f"{vehicle} · {level_text(level)} · {reference.percent(best):.2f} %"
                else:
                    unrated += 1
                    tip = vehicle
                cells[f"class:{name}"] = Cell(calc.sec2laptime_full(best), best, round(best, 3),
                                              self.level_color(level), level >= 0, tip, level_letter(level))
            data_list = [data for data in vehicles.values() if isinstance(data, dict)]
            for key in TRACK_TOTAL_COLUMNS:
                if key == "last":
                    driven = self.track_last_driven.get(track, 0.0)
                    cells[key] = Cell(format_date(driven), driven or None,
                                      time.strftime("%Y-%m-%d", time.localtime(driven)) if driven else None)
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
        self.sortChanged.emit()
        self.rowIndexChanged.emit()  # same row, other place: reference & charts kept

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
        hidden = self.hidden_columns()
        return [key for key in self.table_header_key if key in FIXED_COLUMNS or key not in hidden]

    def publish_table(self):
        """Visible columns (widths from contents) & rows to page"""
        self.publish_columns()
        self.publish_rows()

    def publish_columns(self):
        """Visible columns: widths from contents (each text measured once), or set by user"""
        keys = self.visible_keys()
        font = QFont(QApplication.font())
        metrics = QFontMetricsF(font)
        font.setBold(True)
        bold = QFontMetricsF(font)
        measured: dict[tuple[str, bool], float] = {}  # many cells share a text ("-", dates...)

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
            for _, cells in self._table:
                cell = cells.get(key)
                if cell is not None:
                    margins = 3.3 if cell.badge else 2.4 if cell.pill else 1.6  # badge, pill & cell margins
                    if cell.logo:
                        margins += LOGO_EM  # logo before text (StatsTable.qml)
                    width = max(width, text_width(cell.text, cell.bold) * 1.05 + em * margins)
            if key in user_widths:
                width = max(user_widths[key] * em, em * 2)
            tip = HEADER_TOOLTIPS.get(key, "")
            columns.append({"key": key, "label": label, "tip": tr(tip) if tip else "",
                            "width": round(width), "align": "left" if key in FIXED_COLUMNS else "center"})
        self._columns = columns

    def publish_rows(self):
        """Rows to page: rows of another track rebuilt, else moved & changed in place (scroll & delegates kept)"""
        keys = self.visible_keys()
        rows = [{"key": row_key, "cells": [self.cell_data(cells.get(key)) for key in keys]}
                for row_key, cells in self._table]
        if self._published_track != self.selected_stats_key:
            self._published_track = self.selected_stats_key
            self.row_model.reset(rows)
        else:
            self.row_model.sync(rows)

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
        return [{"key": key, "label": header_label(key), "visible": key not in hidden}
                for key in VEHICLE_COLUMNS if key not in FIXED_COLUMNS]

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
            detail = f"{reference.percent(best):.2f} %"
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
            records = [record for record in self.history if record.track == track]
            parts = [plural(len(self.selected_stats_dict), "vehicle", "vehicles")]
            driven = self.track_last_driven.get(track, 0.0)
        else:
            records = [record for record in self.history if record.track in self.stats_temp]
            count = len([key for key in self.stats_temp if key])
            parts = [plural(count, "track", "tracks")] if count else []  # no stats: empty page says it
            driven = 0.0
        if records:
            parts.append(plural(len(records), "session", "sessions"))
            if track:
                parts.append(f"{tr('last driven')} {format_date(driven)}")
            else:
                parts.append(f"{tr('since')} {format_date(records[0].time)}")
        current = api.read.session.track_name() if api.read is not None else ""
        return {"subtitle": " · ".join(parts), "live": bool(track) and track == current}

    @Property(dict, notify=statsChanged)
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

    @Property(dict, notify=statsChanged)
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
                "trackLogo": track_logo_url(record.track),
                "session": session_name(record.session), "kind": session_kind(record.session),
                "best": calc.sec2laptime_full(laptime) if laptime else "-",
                "pb": bool(best and laptime and abs(laptime - best) < 0.0005), "result": race_result(record),
                "podium": record.position if record.finish == 1 and 0 < record.position <= 3 else 0,
            })
            if len(rows) >= RECENT_SESSIONS:
                break
        return rows

    @Property(list, notify=statsChanged)
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

    @Property(list, notify=statsChanged)
    def tiles(self) -> list[dict]:
        return self._tiles

    # Level distribution (All Tracks)
    @Property(list, notify=statsChanged)
    def levels(self) -> list[dict]:
        top = max(self.level_counts, default=0)
        return [{"name": tr(name), "color": self.level_color(level), "count": self.level_counts[level],
                 "ratio": self.level_counts[level] / top if top else 0.0, "letter": level_letter(level)}
                for level, name in enumerate(LEVELS)]

    @Property(str, notify=statsChanged)
    def levelsInfo(self) -> str:
        if not any(self.level_counts):
            return tr("No level yet: community lap times needed, vehicle classification by class.")
        if self.unrated:
            return plural(self.unrated, "track & class combo without reference", "track & class combos without reference")
        return ""

    # Selection: reference, progression & sessions of selected vehicle
    @Property(str, notify=selectionChanged)
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
            self.selectRow(keys[min(max(index + step, 0), len(keys) - 1) if index >= 0 else 0])

    def selected_row_key(self) -> str:
        return self._selected[self.mode]

    @Slot(str)
    def openRow(self, key: str):
        """All Tracks: double click or Enter shows vehicles of track"""
        if not self.selected_stats_key and key in self.stats_temp:
            self.selectTrack(key)

    def update_selection(self):
        self._reference = self.reference_data()
        self._progression, self._sessions = self.history_data()
        self._has_laps = bool(self.lap_folder())
        self.selectionChanged.emit()
        self.rowIndexChanged.emit()
        self.update_stints()

    # Stints & consistency of selected vehicle: recorded laps of its track & class folder
    def update_stints(self, background: bool = True):
        """Recorded laps of selected vehicle read (in a thread if background): stint pace & degradation by tyre
        compound, consistency of each session & of the track"""
        vehicle = self._selected["vehicles"] if self.selected_stats_key else ""
        folder = self.lap_folder(vehicle) if vehicle else ""
        key = f"{folder}|{vehicle}"
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
            return  # same laps shown (reloaded when stats change: see refresh)
        self._laps_key = key
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
        threading.Thread(target=self.read_stints, args=job, daemon=True, name="Driver stats laps").start()

    def read_stints(self, key: str, folder: str, vehicle: str, generation: int):
        path = os.path.join(cfg.path.telemetry, folder)
        try:
            report = stint_report(read_laps(path, lambda info: lap_matches_vehicle(info, vehicle), self._lap_infos))
        except Exception:  # unreadable folder: nothing shown, page goes on
            logger.exception("DRIVER STATS: unable to read recorded laps of %s", folder)
            report = None
        with suppress(RuntimeError):  # page closed meanwhile
            self.laps_loaded.emit(key, generation, report)

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

        compounds = [{"compound": compound(row["compound"]), "stints": row["stints"], "laps": row["laps"],
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
        if not filename:
            return False
        try:
            self._friend = load_friend(filename)
        except ValueError as error:
            if not quiet:
                self.warning(trm(f"Unable to read friend's stats: {error}"))
            return False
        return True

    @Slot()
    def importFriend(self):
        """Compare with a friend's exported session history (JSON)"""
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        filename, _ = QFileDialog.getOpenFileName(self._window, tr("Compare With a Friend's Stats..."),
                                                  folder or os.path.expanduser("~"), "JSON (*.json)")
        if filename and self.load_friend(filename):
            self.save_viewer_config(friend_file=filename)
            self.refresh_friend()

    @Slot()
    def clearFriend(self):
        self._friend = None
        self.save_viewer_config(friend_file="")
        self.refresh_friend()

    @Property(dict, notify=friendChanged)
    def friend(self) -> dict:
        """Friend's personal bests against own: name, rows (track, class, lap times, gap), summary"""
        return self._friend_view

    def refresh_friend(self):
        self._friend_view = self.friend_data()
        self.friendChanged.emit()

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
            gap_text = trm(f"Personal best {calc.sec2laptime_full(best)}: {gap:+.2f} s ({reference.percent(best):.2f} %) "
                           f"to reference {calc.sec2laptime_full(reference.reference)}")
            level, to_find = reference.next_level(best)
            if level >= 0:
                next_text = trm(f"Next level {tr(LEVELS[level])}: {to_find:.2f} s to find")
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
                "letter": level_letter(level), "percent": f"{reference.percent(best):.2f} %" if best > 0 else "",
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
                "tip": f"{name} {calc.sec2laptime_full(laptime)} · {level_text(level)} · {reference.percent(laptime):.2f} %",
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
            if date:
                lines.append(trm(f"PB {calc.sec2laptime_full(best)} set on {format_date(date)}"))
        if records:
            lines.append(f"{plural(len(records), 'session', 'sessions')} · {tr('last driven')} "
                         f"{format_date(records[-1].time)}")
        else:
            lines.append(tr("No session recorded yet: history starts with your next session."))
        chart["info"] = "\n".join(lines)
        sessions = []
        for record in reversed(records[-MAX_SESSIONS:]):
            laptime = record.best if record.best > 0 and not (best and record.best < best - 0.0005) else 0.0
            sessions.append({
                "date": format_date(record.time),
                "session": session_name(record.session),
                "kind": session_kind(record.session),
                "best": calc.sec2laptime_full(laptime) if laptime else "-",
                "laps": f"{record.valid}/{record.valid + record.invalid}",
                "result": race_result(record),
                "podium": record.position if record.finish == 1 and 0 < record.position <= 3 else 0,
                "pb": bool(best and laptime and abs(laptime - best) < 0.0005),
                "tip": f"{format_duration(record.seconds)} · {parse_display_value('meters', record.meters)} "
                       f"{tr(format_header_key('meters')).lower()}",
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
    def save_edit(stats_user: dict, removed: Iterable[SessionRecord], added: Iterable[SessionRecord]) -> bool | None:
        """Save edited stats & history change (STATS_LOCK held)

        History changed first: a change (records removed or added once) undone safely if stats not saved,
        tried again a few times.

        Returns:
            True if saved, False if not saved (both files kept),
            None if stats not saved and history change could not be undone (history changed only).
        """
        removed, added = tuple(removed), tuple(added)
        try:
            replace_records(cfg.path.config, removed, added)
        except OSError:  # history unreadable (never rewritten as empty) or not saved
            return False
        if save_stats_json_file(stats_user=stats_user, filepath=cfg.path.config):
            return True
        for attempt in range(ROLLBACK_ATTEMPTS):
            if attempt:
                time.sleep(ROLLBACK_DELAY)
            try:
                replace_records(cfg.path.config, added, removed)  # history change undone
                return False
            except OSError as error:
                logger.warning("STATS: history change not undone (attempt %s): %s", attempt + 1, error)
        return None

    def edit_stats(self, path: tuple[str, ...], value: Any,
                   history_change: Callable[[list[SessionRecord]], tuple[list, list]] | None = None) -> bool:
        """Set stats at path (None removes it, empty path: whole file), history changed, undo recorded

        Done once stats module is not saving (see run_locked).

        Args:
            history_change: history records -> (records removed, records added).

        Returns:
            True if done now.
        """
        return self.run_locked(lambda: self.write_edit(path, value, history_change))

    def write_edit(self, path: tuple[str, ...], value: Any,
                   history_change: Callable[[list[SessionRecord]], tuple[list, list]] | None,
                   ) -> Callable[[], None]:
        """Edit applied to stats file read again (STATS_LOCK held), see edit_stats"""
        with STATS_LOCK:  # held already (run_locked), reentrant
            stats_user = self.load_fresh_stats()
            if stats_user is None:
                return self.stats_unreadable
            backup_stats_file(cfg.path.config)
            self._backups = None  # listed again
            before = stats_entry(stats_user, path) if path else copy.deepcopy(stats_user)
            if path:
                set_stats_entry(stats_user, path, value)
            else:
                stats_user = copy.deepcopy(value)
            removed: tuple = ()
            added: tuple = ()
            if history_change is not None:
                try:
                    history = load_history(cfg.path.config, strict=True)
                except OSError:  # never rewritten from empty history
                    return self.stats_unreadable
                removed_list, added_list = history_change(history)
                removed, added = tuple(removed_list), tuple(added_list)
            saved = self.save_edit(stats_user, removed, added)
            if saved is False:  # not saved: no undo recorded
                return self.stats_unsaved
            if saved is None:  # history changed only: its undo recorded

                def history_changed():
                    self.edit_done(StatsEdit(path, None, None, removed, added, history_only=True))
                    self.stats_unsaved_history_changed()
                return history_changed
        return lambda: self.edit_done(StatsEdit(path, before, copy.deepcopy(value), removed, added))

    def edit_done(self, edit: StatsEdit):
        """Edit saved: undo recorded, page reloaded"""
        self._edits_undo.append(edit)
        del self._edits_undo[:-MAX_UNDO]
        self._edits_redo.clear()
        self.reload_stats()

    def apply_edit(self, edit: StatsEdit, undo: bool) -> bool:
        """Apply edit again (redo) or its reverse (undo, stats recorded since kept) on stats file read again

        Called with STATS_LOCK held (see run_locked), False if stats file unreadable or not saved.
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
            stats_user = self.load_fresh_stats()
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
                return bool(self.save_edit(stats_user, edit.history_after, edit.history_before))
            return bool(self.save_edit(stats_user, edit.history_before, edit.history_after))

    @Slot()
    def undo(self):
        """Undo last edit"""
        if not self._edits_undo:
            return
        edit = self._edits_undo.pop()

        def job() -> Callable[[], None]:
            done = self.apply_edit(edit, undo=True)

            def after():
                if done:
                    self._edits_redo.append(edit)
                else:
                    self._edits_undo.append(edit)
                    self.stats_unreadable()
                self.reload_stats(select=edit.path[0] if edit.path else None)
            return after

        self.run_locked(job)

    @Slot()
    def redo(self):
        """Redo last undone edit"""
        if not self._edits_redo:
            return
        edit = self._edits_redo.pop()

        def job() -> Callable[[], None]:
            done = self.apply_edit(edit, undo=False)

            def after():
                if done:
                    self._edits_undo.append(edit)
                else:
                    self._edits_redo.append(edit)
                    self.stats_unreadable()
                self.reload_stats(select=edit.path[0] if len(edit.path) > 1 else None)
            return after

        self.run_locked(job)

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
        if not DriverStats.is_lap_time(column) or not self.selected_stats_key:
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
        """Stats file as saved in backup (undo: stats before restore)"""
        stats_backup = load_stats_backup(cfg.path.config, name)
        if stats_backup is None:
            self.warning(tr("Unable to read stats file."))
            return
        date = next((entry["date"] for entry in self.cached_backups() if entry["name"] == name), name)
        if self.confirm(trm(f"Restore stats saved on <b>{date}</b>?<br><br>Undo with Ctrl+Z while this page is open.")):
            self.edit_stats((), validate_stats_file(stats_backup))

    # Context menu
    @Slot(str, str, result=list)
    def rowActions(self, key: str, column: str) -> list[dict]:
        """Right click menu entries of row & column: id, text, enabled"""
        actions = []
        if not self.selected_stats_key:
            actions += [{"id": "show", "text": tr("Show Track"), "enabled": True},
                        {"id": "delete", "text": tr("Delete Track"), "enabled": True}]
        elif column == "vehicle":
            actions.append({"id": "remove", "text": tr("Remove Vehicle"), "enabled": True})
        elif DriverStats.is_lap_time(column):
            laptime = valid_laptime(self.selected_stats_dict.get(key, {}).get(column, 0))
            actions.append({"id": "reset", "text": tr("Reset Lap Time"), "enabled": bool(laptime)})
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
        TrackMapViewer(self._window, filepath=cfg.path.track_map,
                       filename=strip_invalid_char(self.selected_stats_key)).show()

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
