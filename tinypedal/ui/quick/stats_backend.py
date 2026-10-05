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
recorded since. Stats & history files saved by stats module are reloaded at once (page shown).
"""

from __future__ import annotations

import copy
import csv
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
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
from ..track_map_viewer import TrackMapViewer
from .models import DictListModel

logger = logging.getLogger(__name__)

REFERENCE_MAX_AGE = 24 * 3600  # seconds before cached lap time reference is downloaded again
REFERENCE_KEYS = ("gap", "level")  # table columns from lap time reference, after personal best
WATCH_DELAY = 800  # milliseconds after stats or history file changed before reloading
MAX_UNDO = 50
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
    date = QDateTime.fromSecsSinceEpoch(int(timestamp)).date()
    return date_locale().toString(date, QLocale.FormatType.ShortFormat)


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


class StatsEdit(NamedTuple):
    """Change of stats file at path (track, vehicle, stat; empty: whole file), session history change

    Undo puts history_before back (instead of history_after), redo the other way.
    """

    path: tuple[str, ...]
    before: Any
    after: Any
    history_before: tuple[SessionRecord, ...] = ()
    history_after: tuple[SessionRecord, ...] = ()


class DriverStatsBackend(QObject):
    """Driver stats viewer page state & actions"""

    tracksChanged = Signal()
    statsChanged = Signal()
    selectionChanged = Signal()
    referenceChanged = Signal()
    editsChanged = Signal()
    optionsChanged = Signal()
    reference_loaded = Signal(str, str)  # sheet CSV text (empty if failed), error

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
        # Table
        self.table_header_key: list[str] = list(VEHICLE_COLUMNS)
        self._labels: dict[str, str] = {}
        self._table: list[tuple[str, dict[str, Cell]]] = []  # rows in shown order
        self._columns: list[dict] = []
        self._sort = {"vehicles": ("pb", False), "tracks": ("track", False)}
        self._selected = {"vehicles": "", "tracks": ""}
        self.row_model = DictListModel(("key", "cells"), self)
        # Selected vehicle
        self._tiles: list[dict] = []
        self._reference: dict = {}
        self._progression: dict = {}
        self._sessions: list[dict] = []
        self._session_filter = 0
        self._tracks: list[dict] = []
        self.reference_loaded.connect(self.reference_downloaded)

        # Stats & history files saved by stats module: reloaded
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.schedule_reload)
        self.watcher.fileChanged.connect(self.schedule_reload)
        self.watch_timer = QTimer(self)
        self.watch_timer.setSingleShot(True)
        self.watch_timer.setInterval(WATCH_DELAY)
        self.watch_timer.timeout.connect(self.reload_if_changed)

        self.load_reference()
        self.reload_stats()
        self.watch_files()
        self.download_reference()

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
            try:
                text, error = lap_reference.fetch_sheet(url), ""
            except (OSError, ValueError) as exc:
                text, error = "", str(exc)
            with suppress(RuntimeError):  # page closed meanwhile
                self.reference_loaded.emit(text, error)

        threading.Thread(target=download, daemon=True, name="Lap reference download").start()

    def reference_downloaded(self, text: str, error: str):
        self._downloading = False
        self.reference_error = error
        if text:
            lap_reference.save_cache(cfg.path.config, text)
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
        """Page closed: stop watching files"""
        self.watch_timer.stop()
        paths = self.watcher.files() + self.watcher.directories()
        if paths:
            self.watcher.removePaths(paths)

    @Slot()
    def reload(self):
        self.reload_stats()

    def reload_stats(self, select: str | None = None):
        """Reload stats & history files: selected track kept (current track at first load)

        Args:
            select: track key to select, else selected one (neighbor track if removed).
        """
        with STATS_LOCK:
            stats_user = load_stats_json_file(filepath=cfg.path.config)
            self.history = load_history(cfg.path.config)
        self._file_times = self.file_times()
        if stats_user is None:  # invalid file: stats shown kept
            self.refresh_table()
            return
        self.stats_temp = validate_stats_file(stats_user)
        self.history_index = index_history(self.history)
        self.classes = vehicle_classes(self.history)
        self.vehicle_last_driven = last_driven(self.history)
        self.track_last_driven = track_last_driven(self.history)
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
        self._tracks = [{"key": ALL_TRACKS, "label": tr("All Tracks"), "date": "", "current": False}] + [
            {"key": key, "label": key, "date": format_date(self.track_last_driven.get(key, 0.0)),
             "current": key == current}
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
    def refresh_table(self):
        """Table of vehicles (or tracks), sort, selection & tiles kept"""
        if self.selected_stats_key:
            rows = self.vehicle_rows()
        else:
            rows = self.track_rows()
        self._table = self.sorted_rows(rows)
        self.publish_table()
        self.refresh_tiles()
        selected = self._selected[self.mode]
        keys = [key for key, _ in self._table]
        if selected not in keys:
            self._selected[self.mode] = keys[0] if keys else ""
        self.statsChanged.emit()
        self.editsChanged.emit()
        self.update_selection()

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
        cells: dict[str, Cell] = {"vehicle": Cell(vehicle, vehicle.lower(), vehicle)}
        percent = reference.percent(best) if reference else 0.0
        cells["gap"] = Cell(f"{percent:.2f} %" if percent else "-", percent or None, round(percent, 3) if percent else None)
        level = reference.level(best) if reference else -1
        cells["level"] = Cell(level_text(level), level if level >= 0 else None, level_text(level) if level >= 0 else None,
                              self.level_color(level), level >= 0)
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
                                  round(laptime, 3) if laptime else None)
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
            cells: dict[str, Cell] = {"track": Cell(track, track.lower(), track)}
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
        self.publish_table()
        self.statsChanged.emit()

    @Property(str, notify=statsChanged)
    def sortKey(self) -> str:
        return self._sort[self.mode][0]

    @Property(bool, notify=statsChanged)
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
        """Visible columns (widths from contents, measured once) & rows to page"""
        keys = self.visible_keys()
        font = QFont(QApplication.font())
        metrics = QFontMetricsF(font)
        font.setBold(True)
        bold = QFontMetricsF(font)
        em = float(UIScaler.FONT_PIXEL_SCALED)  # theme.em of page
        user_widths = self.column_widths()
        columns = []
        for key in keys:
            label = self._labels.get(key, key)
            width = bold.horizontalAdvance(label) * 1.05 + em * 2.0  # margins & sort arrow (StatsTable.qml)
            for _, cells in self._table:
                cell = cells.get(key)
                if cell is not None:
                    text_width = (bold if cell.bold else metrics).horizontalAdvance(cell.text)
                    width = max(width, text_width * 1.05 + em * (3.3 if cell.badge else 1.6))  # badge, margins
            if key in user_widths:
                width = max(user_widths[key] * em, em * 2)
            tip = HEADER_TOOLTIPS.get(key, "")
            columns.append({"key": key, "label": label, "tip": tr(tip) if tip else "",
                            "width": round(width), "align": "left" if key in FIXED_COLUMNS else "center"})
        self._columns = columns
        self.row_model.reset([
            {"key": row_key, "cells": [self.cell_data(cells.get(key)) for key in keys]}
            for row_key, cells in self._table
        ])

    @staticmethod
    def cell_data(cell: Cell | None) -> dict:
        if cell is None:
            return {"text": "", "color": "", "bold": False, "tip": "", "badge": ""}
        return {"text": cell.text, "color": cell.color, "bold": cell.bold, "tip": cell.tip, "badge": cell.badge}

    @Property(QObject, constant=True)
    def rows(self) -> QObject:
        return self.row_model

    @Property(list, notify=statsChanged)
    def columns(self) -> list[dict]:
        return self._columns

    @Property(list, notify=statsChanged)
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
        self.statsChanged.emit()

    @Slot(str, float)
    def setColumnWidth(self, key: str, width: float):
        """Column resized by user (pixels), saved in font size units"""
        em = float(UIScaler.FONT_PIXEL_SCALED)
        widths = self.column_widths()
        widths[key] = round(max(width, em * 2) / em, 2)
        self.save_viewer_config(column_widths=",".join(f"{name}:{value:g}" for name, value in widths.items()))
        self.publish_table()
        self.statsChanged.emit()

    @Slot()
    def resetColumnWidths(self):
        self.save_viewer_config(column_widths="")
        self.publish_table()
        self.statsChanged.emit()

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
                      if data else "-"),
            self.tile(tr("Driving Time"), format_duration(total("seconds")) if data else "-"),
            self.tile(tr("Valid Laps"), f"{valid:.0f}" if data else "-", laps_detail),
            self.tile(tr("Races"), f"{total('races'):.0f}" if data else "-", races_detail if data else ""),
        ]
        self._tiles = tiles

    @staticmethod
    def tile(title: str, value: str, detail: str = "", color: str = "", tip: str = "") -> dict:
        return {"title": title, "value": value, "detail": detail, "color": color, "tip": tip}

    def track_tiles(self) -> list[dict]:
        """Best lap of track & its level"""
        bests = [(valid_laptime(value.get("pb", 0)), name) for name, value in self.selected_stats_dict.items()
                 if isinstance(value, dict)]
        bests = [entry for entry in bests if entry[0] > 0]
        tip_best = tr("Best personal best of the track, any vehicle")
        tip_level = tr("Level of best lap on community lap times")
        if not bests:
            return [self.tile(tr("Best Lap"), "-", tip=tip_best), self.tile(tr("Level"), "-", tip=tip_level)]
        best, vehicle = min(bests)
        reference = self.reference_of(vehicle)
        level = reference.level(best) if reference else -1
        if reference is not None:
            detail = f"{reference.percent(best):.2f} %"
        else:
            detail = tr("No reference for this track or class") if self.references.entries else ""
        return [self.tile(tr("Best Lap"), calc.sec2laptime_full(best), vehicle, tip=tip_best),
                self.tile(tr("Level"), level_text(level), detail, self.level_color(level), tip_level)]

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
            self.tile(tr("Tracks"), str(len(tracks)) if tracks else "-", detail, tip=f"{tr('Tracks with stats')}\n{detail}"),
            self.tile(tr("Level"), level_text(level), level_detail, self.level_color(level),
                      tr("Median level of your best laps, all tracks & classes")),
        ]

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

    @Property(int, notify=selectionChanged)
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
        self.selectionChanged.emit()

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
                           "marks": "  ".join(f"← {text}" for text in mark), "active": bool(mark)})
        patch = f" · {tr('patch')} {reference.patch}" if reference.patch else ""
        if best > 0:
            gap = best - reference.reference
            gap_text = trm(f"Personal best {calc.sec2laptime_full(best)}: {gap:+.2f} s ({reference.percent(best):.2f} %) "
                           f"to reference {calc.sec2laptime_full(reference.reference)}")
            level, to_find = reference.next_level(best)
            if level >= 0:
                next_text = trm(f"Next level {tr(LEVELS[level])}: {to_find:.2f} s to find")
            else:
                next_text = tr("Top level reached") if reference.level(best) == 0 else ""
        else:
            gap_text = trm(f"Reference {calc.sec2laptime_full(reference.reference)}, no personal best yet")
            next_text = ""
        fastest = ""
        if reference.fastest_car and reference.fastest_time:
            fastest = trm(f"Fastest car: {reference.fastest_car} · {calc.sec2laptime_full(reference.fastest_time)}")
        return {"visible": True, "reason": "", "vehicle": vehicle,
                "detail": f"{reference.track} · {reference.vehicle_class}{patch}", "ladder": ladder,
                "gap": gap_text, "next": next_text, "fastest": fastest}

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
            if record.finish == 1 and record.position > 0:
                result = f"P{record.position}"
            else:
                result = FINISH_TEXTS.get(record.finish, "")
            sessions.append({
                "date": format_date(record.time),
                "session": tr(SESSION_NAMES[record.session]) if 0 <= record.session < len(SESSION_NAMES) else "",
                "best": calc.sec2laptime_full(laptime) if laptime else "-",
                "laps": f"{record.valid}/{record.valid + record.invalid}",
                "result": result,
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
            session = tr(SESSION_NAMES[record.session]) if 0 <= record.session < len(SESSION_NAMES) else ""
            tip = f"{format_date(record.time)} · {session}\n{calc.sec2laptime_full(record.best)}"
            if new_best:
                tip += f" · {tr('PB')}"
            points.append({"x": index / (count - 1), "y": y_of(record.best), "pbY": y_of(best_so_far),
                           "newPb": new_best, "clipped": record.best > high, "tip": tip})
            last_best = best_so_far
        limits = []
        if reference is not None:
            for level in range(len(LEVELS) - 1):
                limit = reference.level_limit(level)
                if low < limit < high:
                    limits.append({"y": y_of(limit), "color": self.level_color(level), "name": tr(LEVELS[level])})
        marks = sorted({0, count // 2, count - 1}) if count >= 3 else [0, count - 1]
        dates = [{"x": index / (count - 1), "text": format_date(progression[index][0].time)} for index in marks]
        return {"visible": True, "points": points, "limits": limits, "dates": dates,
                "top": calc.sec2laptime_full(fastest), "bottom": calc.sec2laptime_full(high)}

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

    def load_fresh_stats(self) -> dict | None:
        """Stats file as saved now (stats module may have saved since loaded), None if invalid"""
        stats_user = load_stats_json_file(filepath=cfg.path.config)
        if stats_user is None:
            self.warning(tr("Unable to read stats file."))
            return None
        return validate_stats_file(stats_user)

    def edit_stats(self, path: tuple[str, ...], value: Any,
                   history_change: Callable[[list[SessionRecord]], tuple[list, list]] | None = None) -> bool:
        """Set stats at path (None removes it, empty path: whole file), history changed, undo recorded

        Args:
            history_change: history records -> (records removed, records added).
        """
        with STATS_LOCK:
            stats_user = self.load_fresh_stats()
            if stats_user is None:
                return False
            backup_stats_file(cfg.path.config)
            before = stats_entry(stats_user, path) if path else copy.deepcopy(stats_user)
            if path:
                set_stats_entry(stats_user, path, value)
            else:
                stats_user = copy.deepcopy(value)
            save_stats_json_file(stats_user=stats_user, filepath=cfg.path.config)
            removed: tuple = ()
            added: tuple = ()
            if history_change is not None:
                removed_list, added_list = history_change(load_history(cfg.path.config))
                removed, added = tuple(removed_list), tuple(added_list)
                replace_records(cfg.path.config, removed, added)
        self._edits_undo.append(StatsEdit(path, before, copy.deepcopy(value), removed, added))
        del self._edits_undo[:-MAX_UNDO]
        self._edits_redo.clear()
        self.reload_stats()
        return True

    def apply_edit(self, edit: StatsEdit, undo: bool) -> bool:
        """Apply edit again (redo) or its reverse (undo, stats recorded since kept) on stats file read again"""
        with STATS_LOCK:
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
            save_stats_json_file(stats_user=stats_user, filepath=cfg.path.config)
            if undo:
                replace_records(cfg.path.config, edit.history_after, edit.history_before)
            else:
                replace_records(cfg.path.config, edit.history_before, edit.history_after)
        return True

    @Slot()
    def undo(self):
        """Undo last edit"""
        if not self._edits_undo:
            return
        edit = self._edits_undo.pop()
        if self.apply_edit(edit, undo=True):
            self._edits_redo.append(edit)
        else:
            self._edits_undo.append(edit)
        self.reload_stats(select=edit.path[0] if edit.path else None)

    @Slot()
    def redo(self):
        """Redo last undone edit"""
        if not self._edits_redo:
            return
        edit = self._edits_redo.pop()
        if self.apply_edit(edit, undo=False):
            self._edits_undo.append(edit)
        else:
            self._edits_redo.append(edit)
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
        return self.backup_list()

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
        date = next((entry["date"] for entry in self.backup_list() if entry["name"] == name), name)
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
        return bool(self.lap_folder())

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
