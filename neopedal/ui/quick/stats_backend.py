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

Page made of parts (mixins sharing the page state, see stats_io.StatsHost): stats_core (signals, settings, files,
reloads, track selection), stats_table, stats_overview (All Tracks), stats_selection (selected vehicle),
stats_edits, stats_sharing (exports, friend); plain helpers in stats_common & stats_io (worker thread work).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from PySide6.QtCore import QFileSystemWatcher, QTimer
from PySide6.QtWidgets import QApplication

from ... import app_signal
from ...i18n import tr
from ...process import results_index as ri
from ...process.player_profile import PlayerProfile
from ...userfile.driver_history import SessionRecord
from ...userfile.lap_reference import LEVELS, LapReferenceTable
from .game_pictures import LogoCache, notifier
from .models import DictListModel
from .page_backend import PageBackend
from .stats_analysis import Upcoming
from .stats_common import (
    ALL_TRACKS,
    CONDITION_FILTERS,
    HIDDEN_RELEASE_DELAY,
    HOME_RESET_DELAY,
    LAPS_DELAY,
    ONLINE_FILTERS,
    RANKS_CHECK,
    SELECTION_BURST,
    SELECTION_DELAY,
    VEHICLE_COLUMNS,
    WATCH_DELAY,
    Cell,
)
from .stats_core import StatsCore
from .stats_edits import StatsEdits
from .stats_io import StatsEdit, StatsJob
from .stats_overview import StatsOverview
from .stats_selection import StatsSelection
from .stats_sharing import StatsSharing
from .stats_table import StatsTable


class DriverStatsBackend(StatsSharing, StatsEdits, StatsSelection, StatsOverview, StatsTable, StatsCore,
                         PageBackend):
    """Driver stats viewer page state & actions"""

    CANCEL_JOBS_ON_RELEASE = False  # running edit saved after close (waiting ones wait for it), see release_resources

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
        self._sector_times: dict[str, float] = {}  # sector best files listed by the last reload (name: modified)
        self._lap_folders: tuple[int, dict[str, int]] = (-1, {})  # recorded laps folders listed (see lap_folders)
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
        self.row_model = DictListModel(("key", "cells", "group"), self)  # group: class of a new class group
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
        self._weekly: dict = {}  # progress of the last days (made again when its key changed)
        self._weekly_key: tuple = ()
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
        # Session history figures: newest game version (history stamp, version), goal of selected vehicle
        self._latest_version: tuple[tuple[int, int], str] = ((-1, -1), "")
        self._goal: dict = {"visible": False}
        self._filter_names = ([tr(name) for name in CONDITION_FILTERS], [tr(name) for name in ONLINE_FILTERS])
        # Table search & class filter (not saved), rows before them, classes of rows
        self._search = ""
        self._class_filter = ""
        self._unfiltered_rows = 0
        self._table_classes: list[str] = []
        # All Tracks: rivals of online races (made again when results read), official races to come (option)
        self._rivals: list[dict] = []
        self._rivals_key: tuple = ()
        self._upcoming_events: list[Upcoming] = []
        self._game_tracks: dict[str, tuple[str, ...]] = {}  # game track scene: names
        self._upcoming_note = ""
        self._upcoming_time = 0.0  # monotonic time of last read asked (0: never)

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

    # Page shown & hidden: in this class (PageBackend wraps the ones a page class defines itself)
    def page_shown(self):
        self._visible = True
        self.hidden_timer.stop()
        self.ranks_timer.start()
        hidden_since, self._hidden_since = self._hidden_since, 0.0
        home = bool(hidden_since) and time.monotonic() - hidden_since >= HOME_RESET_DELAY and self._loaded
        if self._history_released:
            self._history_released = self._dirty = False
            # Table made again with the history read: settings changed meanwhile never shown on the empty one
            self.drop_when_shown(self.settings_changed)
            self.drop_when_shown(self.pictures_changed)  # logos of the history read again
            # history read again, then its results files & links (see stats_files_read)
            self.reload_stats(select=ALL_TRACKS if home else None)
            return
        if home:  # page left a while: opens on All Tracks again
            self.selectTrack(ALL_TRACKS)
        self.check_ranks()  # ranks changed while hidden
        self.check_live_track()  # game session started or ended while hidden
        if not self.selected_stats_key:
            self.load_upcoming()  # official races to come (option), read again after a while
        if self._dirty:
            self._dirty = False
            self.reload_if_changed()

    def page_hidden(self):
        self._visible = False
        self._hidden_since = time.monotonic()
        self.ranks_timer.stop()  # game ranks file checked only while page shown
        if not self._released:
            self.hidden_timer.start()
