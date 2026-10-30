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
Driver stats viewer part (StatsCore, mixin of DriverStatsBackend): Page state shared by the other parts: signals, settings, lap time reference, stats & history files (watched, reloaded in order on a worker thread), results files, track list & selected track
"""

from __future__ import annotations

import html
import logging
import os
import threading
import time
from collections import OrderedDict
from contextlib import suppress
from functools import partial
from typing import Any

from PySide6.QtCore import (
    Property,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ... import app_signal
from ...api_control import api
from ...const_file import ConfigType
from ...i18n import tr
from ...process import results_index as ri
from ...rank_info import ranks
from ...setting import cfg
from ...userfile import lap_reference
from ...userfile.driver_history import (
    SessionRecord,
    forget_records,
    history_path,
)
from ...userfile.driver_stats import (
    STATS_LOCK,
)
from ...userfile.lap_reference import LEVEL_COLORS, LapReference, LapReferenceTable
from . import open_web_link
from .formatting import format_date
from .stats_common import (
    ALL_TRACKS,
    COLORBLIND_LEVEL_COLORS,
    CONFIG_NAME,
    REFERENCE_MAX_AGE,
    STATS_TABS,
    SYNC_HISTORY_BYTES,
    SYNC_STATS_BYTES,
    online_value,
    version_key,
)
from .stats_io import (
    ResultsData,
    StatsFiles,
    StatsHost,
    StatsJob,
    download_reference_sheet,
    history_file_stamp,
    read_reference_cache,
    read_results_data,
    read_stats_files,
    run_holding_lock,
    save_edits_detached,
    stats_file_size,
    stats_file_times,
    store_reference,
)

logger = logging.getLogger(__name__)


def results_combo(stats: dict, track: str, venue: str, car_class: str = "", car: str = "", vehicle: str = ""
                  ) -> tuple[str, str] | None:
    """Stats track & vehicle keys of a results session car (race results page): track of the event or venue
    name, vehicle of the entry name, then class & brand, then class ("" if none); None if track not in stats"""
    names = {name.strip().casefold() for name in (track, venue) if name.strip()}
    track_key = next((key for key in stats if key and key.casefold() in names), "")
    if not track_key:
        return None
    keys = [str(key) for key in stats.get(track_key, {})]
    described = f"{car} {vehicle}".casefold()
    prefix = f"{car_class} - "
    found = next((key for key in keys if vehicle and key == vehicle), "") or next(
        (key for key in keys if car_class and key.startswith(prefix) and key[len(prefix):].casefold() in described),
        "") or next((key for key in keys if car_class and key == car_class), "")
    return track_key, found

class StatsCore(StatsHost):
    """Page state shared by the other parts: signals, settings, lap time reference, stats & history files (watched, reloaded in order on a worker thread), results files, track list & selected track"""

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
    filtersChanged = Signal()  # conditions, online & game version filters of the selected vehicle sessions
    tableFilterChanged = Signal()  # table search, class filter & classes, grouping by class
    rivalsChanged = Signal()  # people met in online races (All Tracks)
    upcomingChanged = Signal()  # official races to come (All Tracks, RaceControl)
    goalChanged = Signal()  # lap time goal of selected vehicle
    weeklyChanged = Signal()  # progress of the last days (All Tracks)
    _wanted_combo: tuple[str, str] | None = None  # track & vehicle shown once stats are read (see show_combo)
    _wanted_results: tuple[str, ...] | None = None  # results session shown once stats are read (show_results_combo)

    @Slot()
    def palette_changed(self, *_args):
        """Light / dark theme switched: level colors (darker on light theme) computed again"""
        if self._loaded:
            self.refresh_table()

    def settings_changed(self, _changed: bool = True):
        """Settings applied (units, vehicle classification): page shown again with them (hidden page: once shown,
        never while its session history is released, see page_shown)"""
        if self.defer_while_hidden(self.settings_changed):
            return
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
            return tr("Downloading community lap times…")
        if self.references.entries:
            # Date cell of the sheet (anyone's sheet: its address can be changed): text, never markup
            updated = f" · {tr('updated')} {html.escape(self.references.updated)}" if self.references.updated else ""
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

    @Slot(str)
    def openLink(self, link: str):
        """Link of the reference text (sheet source) in the browser: https only, never another scheme"""
        open_web_link(link)

    @Slot()
    def changeSheetUrl(self, text: str = ""):
        """Published Google Sheet of lap times (same layout), downloaded at once; not a sheet address: told, then
        asked again with the address typed"""
        from . import dialogs

        def accept(url: str) -> bool:
            url = url.strip() or lap_reference.DEFAULT_SHEET_URL
            if not url.startswith("https://docs.google.com/spreadsheets/"):
                dialogs.alert(self._window, tr("Error"), tr("Not a Google Sheets address."), "warning",
                              lambda: self.changeSheetUrl(url))
                return True
            self.save_viewer_config(lap_reference_sheet_url=url)
            self.download_reference(force=True)
            return True

        dialogs.ask_text(
            self._window, tr("Change Sheet Address…"),
            tr("Address of the published Google Sheet of community lap times (empty for default):"), accept,
            text or self.viewer_config().get("lap_reference_sheet_url") or lap_reference.DEFAULT_SHEET_URL)

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

    def record_online(self, record: SessionRecord) -> int:
        """1 online server, 0 offline, -1 unknown: recorded, else setting of its results file"""
        return online_value(record, self.record_result(record) if record.online < 0 else None)

    def latest_version(self) -> str:
        """Newest game version of session history ("" if none), found again only when history changed (game
        version of records only: results files of older records never make a newer version)"""
        if self._latest_version[0] != self._history_stamp:
            versions = {record.game_version for record in self.history if record.game_version}
            self._latest_version = (self._history_stamp, max(versions, key=version_key, default=""))
        return self._latest_version[1]

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
        self._sector_times, self._lap_folders = files.sector_times, files.lap_folders
        if files.history is not None:
            history = files.history
            self.history, self._history_stamp, self.history_index = history.records, history.stamp, history.by_combo
            self.classes, self.vehicle_last_driven = history.classes, history.vehicle_last_driven
            self.track_last_driven, self.track_sessions = history.track_last_driven, history.track_sessions
            self._history_released = False
            self.load_results()  # session ended: its results file written too
        self.stats_read(files.stats, select)

    def show_combo(self, track: str, vehicle: str):
        """Track & vehicle of a session shown, vehicle row selected (Home page last session): now if stats are read,
        else once read"""
        reloading = any(job is not None and job.kind == "reload" for job in (self._running_job, *self._locked_jobs))
        if not self._loaded or reloading:
            self._wanted_combo = (track, vehicle)
            return
        self._wanted_combo = None
        if track in self.stats_temp:
            self.selectTrack(track)
            self.selectRow(vehicle)

    def show_results_combo(self, track: str, venue: str, car_class: str = "", car: str = "", vehicle: str = ""):
        """Track & player's car of a results session (race results page): stats track of its event or venue name,
        vehicle row of the car (entry name, class & brand, class); now if stats are read, else once read"""
        if not self._loaded or any(job is not None and job.kind == "reload"
                                   for job in (self._running_job, *self._locked_jobs)):
            self._wanted_results = (track, venue, car_class, car, vehicle)
            return
        self._wanted_results = None
        combo = results_combo(self.stats_temp, track, venue, car_class, car, vehicle)
        if combo is not None:
            self.show_combo(*combo)

    def stats_read(self, stats_user: dict | None, select: str | None):
        """Page updated with stats file read (checked already: validate_stats_file)"""
        if stats_user is None:  # invalid file: stats shown kept
            self.refresh_table()
            return
        if self._wanted_results is not None:  # results session asked while reading (see show_results_combo)
            self._wanted_combo = results_combo(stats_user, *self._wanted_results) or self._wanted_combo
            self._wanted_results = None
        self.stats_temp = stats_user
        self._stats_serial += 1
        combo, self._wanted_combo = self._wanted_combo, None  # asked while reading (see show_combo)
        if combo is not None and combo[0] in stats_user:
            select = combo[0]
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
        if combo is not None and self.selected_stats_key == combo[0]:
            self.selectRow(combo[1])
        self.check_goals()  # personal best of a goal beaten meanwhile: told once

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

    # Page layout choices (saved): level limits list of the reference card, activity shown as days or breakdown
    @Property(bool, notify=optionsChanged)
    def levelsOpen(self) -> bool:
        return bool(self.viewer_config().get("show_level_limits", False))

    @Slot(bool)
    def setLevelsOpen(self, shown: bool):
        self.save_viewer_config(show_level_limits=shown)
        self.optionsChanged.emit()

    @Property(int, notify=optionsChanged)
    def activityView(self) -> int:
        """0: calendar of days, 1: driving time by track & class"""
        return 1 if self.viewer_config().get("activity_view", 0) == 1 else 0

    @Slot(int)
    def setActivityView(self, view: int):
        self.save_viewer_config(activity_view=1 if view == 1 else 0)
        self.optionsChanged.emit()

    @Property(int, notify=optionsChanged)
    def statsTab(self) -> int:
        """Tab of the page: 0 overview, 1 progression, 2 compare"""
        value = self.viewer_config().get("stats_tab", 0)
        return value if isinstance(value, int) and 0 <= value < STATS_TABS else 0

    @Slot(int)
    def setStatsTab(self, index: int):
        if 0 <= index < STATS_TABS and index != self.statsTab:
            self.save_viewer_config(stats_tab=index)
            self.optionsChanged.emit()
