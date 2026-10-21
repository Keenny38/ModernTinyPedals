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
Driver stats viewer: stats, session history, results & lap time reference files read or saved in the
background (worker threads, plain data only), edits recorded for undo
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, NamedTuple

from PySide6.QtCore import QFileSystemWatcher, QTimer, Signal

from ...process import results_file as rf
from ...process import results_index as ri
from ...process.player_profile import PlayerProfile, player_profile
from ...setting import cfg
from ...userfile import lap_reference
from ...userfile.driver_history import (
    SessionRecord,
    forget_records,
    history_path,
    index_history,
    last_driven,
    load_history,
    track_last_driven,
    vehicle_classes,
)
from ...userfile.driver_stats import (
    STATS_LOCK,
    load_stats_json_file,
    validate_stats_file,
)
from ...userfile.lap_reference import LapReference, LapReferenceTable
from .game_pictures import LogoCache
from .models import DictListModel
from .page_backend import PageBackend
from .stats_analysis import Upcoming, read_upcoming, track_names
from .stats_common import (
    GAME_TRACKS_AGE,
    LAP_FOLDERS_KEPT,
    Cell,
    lap_matches_vehicle,
)
from .stint_analysis import (
    read_laps,
    stint_report,
)

logger = logging.getLogger(__name__)

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



def read_official_races() -> tuple[list[Upcoming], dict[str, tuple[str, ...]]]:
    """Official races to come (RaceControl, signed in with the game) & names of game tracks (worker thread)"""
    from ...game_rest_cache import rest_cache
    from ...rank_info import online_client, ranks

    client = online_client()
    events = read_upcoming(lambda path: client.get(path, ranks.account))
    names = track_names(rest_cache.json("/rest/race/track", GAME_TRACKS_AGE)) if events else {}
    return events, names

if TYPE_CHECKING:
    _HostBase = PageBackend
else:
    _HostBase = object


class StatsHost(_HostBase):
    """Base of the parts (mixins) of DriverStatsBackend: page state they share & methods of other parts they call

    Declared for type checking only: state is set by DriverStatsBackend.__init__, methods are defined by its parts
    (at run time a plain class: the page is the only QObject).
    """

    if TYPE_CHECKING:
        CANCEL_JOBS_ON_RELEASE: bool
        _window: Any
        stats_temp: dict
        selected_stats_key: str
        selected_stats_dict: dict
        history: list[SessionRecord]
        history_index: dict[tuple[str, str], list[SessionRecord]]
        classes: dict[str, str]
        vehicle_last_driven: dict[tuple[str, str], float]
        track_last_driven: dict[str, float]
        track_sessions: dict[str, tuple[int, float]]
        level_counts: list[int]
        unrated: int
        references: LapReferenceTable
        reference_error: str
        _downloading: bool
        _loaded: bool
        _reading: bool
        _visible: bool
        _dirty: bool
        _hidden_since: float
        _theory_cache: dict[str, tuple[float, float]]
        _edits_undo: list[StatsEdit]
        _edits_redo: list[StatsEdit]
        _file_times: tuple[float, float]
        _history_stamp: tuple[int, int]
        table_header_key: list[str]
        _labels: dict[str, str]
        _table: list[tuple[str, dict[str, Cell]]]
        _columns: list[dict]
        _sort: dict[str, tuple[str, bool]]
        _selected: dict[str, str]
        row_model: DictListModel
        _published_track: str | None
        _text_widths: dict[tuple[str, bool], float]
        _width_font: tuple
        logos: LogoCache
        _tiles: list[dict]
        _track_info: dict
        _reference: dict
        _progression: dict
        _sessions: list[dict]
        _session_filter: int
        _has_laps: bool
        _tracks: list[dict]
        _activity: dict
        _activity_key: tuple
        _recent: list[dict]
        results: list[ri.ResultSummary]
        profile: PlayerProfile | None
        _matcher: ri.SessionMatcher
        _record_results: dict[SessionRecord, ri.ResultSummary | None]
        _linked: dict[str, str] | None
        _results_serial: int
        _stats_serial: int
        _fixes_key: tuple
        _driver_key: tuple
        _driver: dict
        _fixes: list[ri.BestLapFix]
        _published: dict[str, Any]
        _stints: dict
        _laps_key: str
        _lap_infos: OrderedDict[str, dict[str, tuple[float, dict]]]
        _laps_generation: int
        _laps_job: tuple | None
        _laps_running: int
        laps_timer: QTimer
        selection_timer: QTimer
        _selection_time: float
        _friend: dict | None
        _friend_view: dict
        _friend_file: str
        watcher: QFileSystemWatcher
        watch_timer: QTimer
        hidden_timer: QTimer
        _ranks_serial: tuple[int, int]
        ranks_timer: QTimer
        _live_track: str
        _history_released: bool
        _locked_jobs: list[StatsJob]
        _running_job: StatsJob | None
        _last_finished: threading.Event | None
        _released: bool
        _backups: list[dict] | None
        _palette_connected: bool
        _settings_connected: bool
        _latest_version: tuple[tuple[int, int], str]
        _goal: dict
        _filter_names: tuple[list[str], list[str]]
        _search: str
        _class_filter: str
        _unfiltered_rows: int
        _table_classes: list[str]
        _rivals: list[dict]
        _rivals_key: tuple
        _upcoming_events: list[Upcoming]
        _game_tracks: dict[str, tuple[str, ...]]
        _upcoming_note: str
        _upcoming_time: float
        # Signals (StatsCore) & methods of other parts
        filtersChanged: Signal
        goalChanged: Signal
        rivalsChanged: Signal
        tableFilterChanged: Signal
        upcomingChanged: Signal
        def check_goals(self): ...
        def confirm(self, message: str) -> bool: ...
        def set_goal(self, key: str, laptime: float): ...
        def latest_version(self) -> str: ...
        def load_upcoming(self, force: bool = False): ...
        def publish_upcoming(self): ...
        def record_online(self, record: SessionRecord) -> int: ...
        def rivals_card(self) -> list[dict]: ...
        @property
        def mode(self) -> str: ...
        def level_color(self, level: int) -> str: ...
        editing: Any  # Qt Property of StatsCore
        def publish(self, name: str, value: Any, signal) -> bool: ...
        def refresh_table(self): ...
        def warning(self, text: str): ...
        def save_viewer_config(self, **values): ...
        def run_locked(self, job: StatsJob, now: bool = False) -> bool: ...
        lapsChanged: Signal
        columnsChanged: Signal
        def selectTrack(self, key: str): ...
        def row_keys(self) -> list[str]: ...
        rowIndexChanged: Signal
        def reload_stats(self, select: str | None = None): ...
        def reference_of(self, vehicle: str) -> LapReference | None: ...
        def publish_edits(self): ...
        def viewer_config(self) -> dict: ...
        def selected_index(self) -> int: ...
        selectedKeyChanged: Signal
        def selectRow(self, key: str): ...
        def reference_for(self, track: str, vehicle: str) -> LapReference | None: ...
        def driver_card(self) -> dict: ...
        compare: Any  # Qt Property of StatsCore
        def class_of(self, vehicle: str) -> str: ...
        def visible_keys(self) -> list[str]: ...
        def update_selection(self, keyboard: bool = False): ...
        tracksChanged: Signal
        def track_info(self) -> dict: ...
        trackInfoChanged: Signal
        tilesChanged: Signal
        def stats_unreadable(self): ...
        statsChanged: Signal
        def sorted_rows(self, rows: list[tuple[str, dict[str, Cell]]]) -> list[tuple[str, dict[str, Cell]]]: ...
        sortChanged: Signal
        selectionChanged: Signal
        rowsSwitched: Signal
        def refresh_friend(self): ...
        def record_version(self, record: SessionRecord) -> str: ...
        def record_result(self, record: SessionRecord) -> ri.ResultSummary | None: ...
        def recent_sessions(self) -> list[dict]: ...
        recentChanged: Signal
        def publish_stats(self): ...
        def publish_sort(self): ...
        def publish_rows(self): ...
        def pictures_changed(self): ...
        def openRow(self, key: str): ...
        def openLapViewer(self): ...
        levelsChanged: Signal
        def lap_time_fixes(self) -> list[ri.BestLapFix]: ...
        def lap_folder(self, key: str = "") -> str: ...
        @staticmethod
        def game_track() -> str: ...
        friendChanged: Signal
        editsChanged: Signal
        driverChanged: Signal
        def best_lap_result(self, track: str, vehicle: str, laptime: float) -> ri.ResultSummary | None: ...
        def activity_data(self) -> dict: ...
        activityChanged: Signal
        referenceChanged: Signal
        optionsChanged: Signal
