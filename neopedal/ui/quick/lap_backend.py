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
Lap telemetry viewer state for QML page: laps, chart series, track map, G circle, corners, cursor values

Charts, map & G circle vertices go to VertexStore (drawn by GpuShape items),
everything else is exposed as properties of plain values (lists of dicts) & a lap list model.
Page parts are child QObjects of LapViewerBackend with their own state, slots & properties (QML backend.<part>):
conditions (lap_conditions), dashboard (lap_dashboard), session (lap_session), math & charts (lap_charts), exports
(lap_export), cornerTable (lap_corners), trackNotes (lap_track_notes), and of the track map: mapMarks (corner labels
& points, lap_map_marks), mapPointer (mouse over map, lap positions at cursor, lap_map_pointer), mapConsistency
(consistency mode, lap_consistency). Each reaches the page through an explicit host (Protocol of what it uses);
the page owns the jobs & timers. Track map building (lap_map_view) is still a mixin: its state (map lines, placements
across track, zoom steps) is shared with lap loading, corners, cursor & playback of this class. So are tracks & lap list (lap_library), lap actions & trash (lap_actions), official
circuit, track limits & lap loading (lap_loading), page options & charts (lap_panels), XY tab, G circle & replay
(lap_xy): mixins sharing page state, this module keeps the page state, properties, background jobs & worker process.
"""

from __future__ import annotations

import base64
import concurrent.futures
import logging
import math
import multiprocessing
import os
import queue
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import (
    Property,
    QByteArray,
    QCoreApplication,
    QFileSystemWatcher,
    QObject,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import QWidget

from ... import app_signal
from ...i18n import tr, trm
from ...userfile import track_geometry
from ...userfile.corner_analysis import (
    CornerComparison,
    CornerStats,
    ResampledLap,
)
from ...userfile.lap_cache import (  # noqa: F401  (INFO_FOLDER & INFO_READERS re-exported)
    INFO_FOLDER,
    INFO_READERS,
    IndexedInfos,
    indexed_infos,
    info_index_path,
    load_cached_lap,
    prune_cache,
    read_infos,
    remove_cached_lap,
    remove_unreadable_listener,
    save_info_index,
    save_pending_index,
    set_unreadable_listener,
)
from ...userfile.lap_geometry import (  # noqa: F401  (limits_part & median_bounds re-exported)
    JobCancelled,
    Yielder,
    coordinate_array,
    limits_part,
    median_bounds,
    session_values,
    track_limits_job,
)
from ...userfile.telemetry_lap import (
    LapData,
    best_laps,
    forget_increasing,
)
from .. import lap_viewer, safe_markup
from ..lap_viewer import (
    CHANNEL_MAP,
    CHANNEL_PRESETS,
    CHANNELS,
    DEFAULT_CHANNELS,
    DELTA_RATE_WINDOWS,
    SMOOTHING_LEVELS,
    LapEntry,
    PlotLap,
    acquire_viewer_settings,
    channel_title,
    distance_text,
    distance_unit,
    format_laptime,
    lap_label,
    load_viewer_setting,
    release_viewer_settings,
    save_viewer_setting,
)
from . import lap_map
from .game_pictures import notifier
from .lap_actions import (  # noqa: F401  (re-exported)
    TRASH_DAYS,
    TRASH_FOLDER,
    UNDO_DEPTH,
    LapActions,
    list_trash,
    path_key,
    purge_trash,
    trash_batch_time,
)
from .lap_base import (  # noqa: F401  (re-exported)
    COLOR_GAIN,
    COLOR_LOSS,
    PagePart,
    format_diff,
    int_setting,
    keys_match,
)
from .lap_charts import ChartTools, MathChannels, legend_offset
from .lap_conditions import LapConditions
from .lap_consistency import CONSISTENCY_SCOPES, MapConsistency  # noqa: F401  (re-exported)
from .lap_corners import CornerTable
from .lap_dashboard import DashboardTab, pedal_value  # noqa: F401  (re-exported)
from .lap_export import LapExports
from .lap_library import (  # noqa: F401  (re-exported)
    INFO_BACKGROUND,
    TRACK_ROLES,
    LapLibrary,
    TrackListModel,
    setup_text,
)
from .lap_library_panel import ImportedLaps
from .lap_loading import (  # noqa: F401  (re-exported)
    LIMITS_FOLDER,
    LIMITS_LAPS,
    LapLoading,
    circuit_name,
    read_limits_cache,
)
from .lap_map_marks import MapMarks
from .lap_map_pointer import MapPointer, yaw_calibration  # noqa: F401  (re-exported)
from .lap_map_view import (  # noqa: F401  (re-exported: lap_backend.scale_step...)
    BAND_CACHE_STEPS,
    MAP_OPTIONS,
    PREFETCH_DELAY,
    ZOOM_BUCKETS,
    MapView,
    pit_parts,
    prepare_placements,
    scale_step,
)
from .lap_panels import (  # noqa: F401  (re-exported)
    CHART_RETRIES,
    LOD_LEVELS,
    LOD_MIN_RATIO,
    SERIES_ROLES,
    ChartPanels,
)
from .lap_session import SessionTab, least_squares  # noqa: F401  (re-exported)
from .lap_track_notes import TrackNotes
from .lap_xy import (  # noqa: F401  (re-exported)
    G_ENVELOPE_QUANTILE,
    G_PERCENTILE,
    G_SECTORS,
    HISTOGRAM_BINS,
    XY_DOT,
    XyTabs,
    find_replay,
    g_envelope,
    percentile,
    time_weights,
)
from .lines import (
    VertexStore,
    Vertices,
)
from .models import DictListModel, FoldedListModel
from .page_backend import PageBackend
from .trace_data import TraceData

logger = logging.getLogger(__name__)

PANEL_ROLES = ("column", "low", "high", "ticks", "envelope", "note", "available", "seriesModel")
LEGEND_ROLES = ("key", "label", "full", "color", "reference", "clean", "tip", "excluded", "offset")
MAP_LAP_ROLES = ("lap", "key", "highlight", "trail", "color", "reference", "shapes", "brakeZones", "throttleZones")
LAP_ROLES = (
    "kind", "session", "path", "title", "time", "s1", "s2", "s3", "best1", "best2", "best3", "info", "note",
    "checked", "reference", "color", "dim", "fastest", "personalBest", "count", "error", "gap", "tip", "open", "hint",
    "logo", "compound",
)
STATUS_DURATION = 8000  # ms, transient status messages shown
WATCH_DELAY = 1500  # ms after a lap file appears before list is refreshed (file fully written)
JOB_INTERVAL = 80  # ms, background jobs checked
WORKER_IDLE = 60_000  # ms without job before worker process stops (its memory given back)
USE_WORKER_PROCESS = True  # heavy jobs (track limits, session values) in a worker process, else in threads


_worker: concurrent.futures.ProcessPoolExecutor | None = None
_worker_broken = False  # worker process could not start (or died running a job): jobs run in fallback thread
_quit_hooked = False  # worker killed when app quits (a running job would delay exit until done)
_finishing: list[concurrent.futures.ProcessPoolExecutor] = []  # worker processes of closed pages ending exports
_export_futures: set[concurrent.futures.Future] = set()  # export jobs not finished yet
_fallback_jobs: queue.SimpleQueue = queue.SimpleQueue()  # jobs worker process could not run: future, work
_fallback_thread: threading.Thread | None = None
_fallback_lock = threading.Lock()
EXPORT_JOBS = ("MoTeC export", "CSV export", "MoTeC import", "Lap import", "lap share")  # finished even if viewer closed (whole files)
# Never run again in page process when worker process died with them: a log too big or malformed for the worker (out of
# memory) would freeze the page, worker is started again for next jobs instead
IMPORT_JOBS = ("MoTeC import", "Lap import")
EXIT_EXPORT_WAIT = 5.0  # seconds app exit waits for exports still running, then they are dropped


def worker_pool() -> concurrent.futures.ProcessPoolExecutor | None:
    """Worker process for heavy lap jobs, None if not available

    Pure Python work in a thread holds the interpreter lock: page thread (drawing, mouse) would wait for it.
    A worker process runs beside the page instead (frozen app: started by multiprocessing.freeze_support).
    A worker process found dead (import of a log too big for it, not handled yet) is started again.
    """
    global _worker, _worker_broken, _quit_hooked
    if _worker is not None and getattr(_worker, "_broken", False):
        stop_worker(kill=True)
    if _worker is None and not _worker_broken and USE_WORKER_PROCESS:
        try:
            _worker = concurrent.futures.ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        except (OSError, ValueError, RuntimeError) as error:
            logger.warning("LAP VIEWER: worker process not available, jobs in fallback thread: %s", error)
            _worker_broken = True
        app = QCoreApplication.instance()
        if _worker is not None and app is not None and not _quit_hooked:
            app.aboutToQuit.connect(quit_workers)
            _quit_hooked = True
    return _worker


def stop_worker(kill: bool = False, finish: bool = False):
    """Stop worker process (started again when needed): its running job dropped too if kill,
    waiting jobs still done if finish (process exits once done)"""
    global _worker
    pool, _worker = _worker, None
    if pool is None:
        return
    if not kill:
        pool.shutdown(wait=False, cancel_futures=not finish)
        if finish:  # kept until app exit (pools already done forgotten)
            _finishing[:] = [other for other in _finishing if pool_alive(other)] + [pool]
        return
    terminate_pool(pool)


def pool_alive(pool: concurrent.futures.ProcessPoolExecutor) -> bool:
    return any(process.is_alive() for process in list((getattr(pool, "_processes", None) or {}).values()))


def terminate_pool(pool: concurrent.futures.ProcessPoolExecutor):
    """Worker processes of pool stopped now, running job dropped"""
    terminate = getattr(pool, "terminate_workers", None)  # Python 3.14
    if terminate is not None:
        with suppress(Exception):
            terminate()
            return
    processes = list((getattr(pool, "_processes", None) or {}).values())
    pool.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        with suppress(Exception):
            process.terminate()


def kill_worker():
    """Lap viewer closed: running job dropped"""
    stop_worker(kill=True)


def quit_workers():
    """App quitting: exports still running get a few seconds to finish (whole files), any other job dropped
    (exit never waits longer)"""
    if _export_futures:
        concurrent.futures.wait(list(_export_futures), timeout=EXIT_EXPORT_WAIT)
    stop_worker(kill=True)
    while _finishing:
        terminate_pool(_finishing.pop())


class JobHandle:
    """Background job running in a thread, or in worker process or fallback thread (future): same interface"""

    BROKEN = object()  # result of a job lost with its worker process (run again in fallback thread, imports not)

    def __init__(self, name: str, thread: threading.Thread | None = None, holder: dict | None = None,
                 future: concurrent.futures.Future | None = None,
                 pool: concurrent.futures.ProcessPoolExecutor | None = None):
        self.name = name
        self.thread = thread
        self.holder = holder if holder is not None else {}
        self.future = future
        self.pool = pool  # worker process running job

    def is_alive(self) -> bool:
        if self.future is not None:
            return not self.future.done()
        return self.thread is not None and self.thread.is_alive()

    def join(self):
        if self.future is not None:
            concurrent.futures.wait([self.future])
        elif self.thread is not None:
            self.thread.join()

    def result(self) -> Any:
        """Job result, None if failed, BROKEN if worker process died"""
        if self.future is None:
            return self.holder.get("result")
        try:
            return self.future.result()
        except concurrent.futures.process.BrokenProcessPool as error:
            logger.warning("LAP VIEWER: worker process stopped (%s), %s lost with it", error, self.name)
            return JobHandle.BROKEN
        except concurrent.futures.CancelledError:
            return None
        except Exception:  # job failing must not stop page
            logger.exception("LAP VIEWER: %s failed", self.name)
            return None


def start_thread_job(name: str, work: Callable[[], Any]) -> JobHandle:
    holder: dict = {}

    def running():
        try:
            holder["result"] = work()
        except JobCancelled:  # stale job stopped early (result None)
            holder["cancelled"] = True
        except Exception:  # job failing must not stop page
            logger.exception("LAP VIEWER: %s failed", name)

    thread = threading.Thread(target=running, daemon=True, name=f"Lap viewer {name}")
    thread.start()
    return JobHandle(name, thread, holder)


def start_job(name: str, function: Callable, *args) -> JobHandle:
    """Job in worker process if available (function & args picklable), else in fallback thread"""
    pool = worker_pool()
    if pool is not None:
        try:
            future = pool.submit(function, *args)
            if name in EXPORT_JOBS:  # waited for a few seconds at app exit
                _export_futures.add(future)
                future.add_done_callback(_export_futures.discard)
            return JobHandle(name, future=future, pool=pool)
        except (RuntimeError, concurrent.futures.process.BrokenProcessPool) as error:
            logger.warning("LAP VIEWER: worker process not available (%s), %s in fallback thread", error, name)
            mark_worker_broken()
    return start_fallback_job(name, function, *args)


def start_fallback_job(name: str, function: Callable, *args) -> JobHandle:
    """Job worker process could not run, in fallback thread of page process: one at a time (every lap of a track
    exported at once would hold interpreter lock & memory of each), daemon thread (app exit never waits for it)"""
    global _fallback_thread
    future: concurrent.futures.Future = concurrent.futures.Future()
    _fallback_jobs.put((future, lambda: function(*args)))
    with _fallback_lock:
        if _fallback_thread is None or not _fallback_thread.is_alive():
            _fallback_thread = threading.Thread(target=run_fallback_jobs, daemon=True, name="Lap viewer jobs")
            _fallback_thread.start()
    if name in EXPORT_JOBS:  # waited for a few seconds at app exit
        _export_futures.add(future)
        future.add_done_callback(_export_futures.discard)
    return JobHandle(name, future=future)


def run_fallback_jobs():
    """Fallback thread: jobs in order (cancelled ones skipped), result or error told by their future"""
    while True:
        future, work = _fallback_jobs.get()
        result = None
        try:
            if future.set_running_or_notify_cancel():
                try:
                    result = work()
                except BaseException as error:  # any failure: future done (logged by JobHandle.result)
                    future.set_exception(error)
                else:
                    future.set_result(result)
        finally:  # job, its data & result (lap data, tens of MB) never kept while waiting for the next job
            del future, work, result


def mark_worker_broken():
    global _worker_broken
    _worker_broken = True
    stop_worker()


def worker_died(handle: JobHandle):
    """Worker process of job died (killed, out of memory): an import (log too big or malformed for it) only drops it,
    started again for next jobs; any other job marks worker broken (jobs in fallback thread)"""
    if handle.pool is None or handle.pool is not _worker:  # other job of same process already handled it
        return
    if handle.name in IMPORT_JOBS:
        stop_worker(kill=True)
    else:
        mark_worker_broken()


class LapViewerBackend(LapLibrary, LapActions, LapLoading, ChartPanels, XyTabs, MapView, PageBackend):
    """Lap telemetry viewer page state (QML context property "backend")

    Parts (child QObjects, see module docstring) as constant properties; track map, lap list, lap actions, lap
    loading, charts & XY tab in their own modules (mixins).
    """

    tracksChanged = Signal()
    listChanged = Signal()  # best lap text, expanded sessions, hide unclean, search, no match
    listOrderChanged = Signal()  # session kinds & counts, session & lap order (filter menu)
    chartChanged = Signal()  # laps shown: panels, legend, maps, corners
    channelsChanged = Signal()
    statusChanged = Signal()
    revisionChanged = Signal()  # vertex store updated
    mapChanged = Signal()  # map color mode, options
    optionsChanged = Signal()  # smoothing, envelope, live mode, layout...
    trailChanged = Signal()  # cursor trail vertices updated (trail shapes only, not every shape)
    selectionChanged = Signal()  # corner selected on map or in corner table
    pinChanged = Signal()  # position kept by clicking charts or map
    viewRestored = Signal(float, float)  # chart zoom to show again (laps reloaded after release)
    pageHidden = Signal()  # page in background: lap playback stopped
    undoChanged = Signal()  # deleted laps that can be restored
    lapsTrashed = Signal(int, str)  # laps moved to trash: count, name of the lap when one (page toast)
    lapColumnsLost = Signal(str, str)  # columns of a cached lap not read again (lap path, reason), from any thread
    trashChanged = Signal()  # recently deleted laps (trash folder) read
    mathChanged = Signal()  # math channels added, changed or removed
    gCircleChanged = Signal()  # G circle built (laps changed while its tab is hidden: built once shown)
    # Parts of charts changed alone (also sent by chartChanged): panel height or autoscale, corner table & marks
    # (compared lap, sort, sensitivity, alignment), track map (turned). QML items of other parts are kept.
    panelsChanged = Signal()
    cornersChanged = Signal()
    mapDataChanged = Signal()
    mapCornersChanged = Signal()  # corner labels & sector times of map (compared lap changed: map itself kept)
    picturesChanged = Signal()  # car brand & circuit logos fetched from game
    lostCornersShown = Signal()  # guided analysis ready: charts zoom on the worst corner, keys step to the others

    def __init__(self, parent: QWidget, folder: str):
        super().__init__(parent, "Lap viewer")
        self._window = parent
        self.widget = parent  # page host (dialogs parent)
        self._picture_version = 0
        notifier().changed.connect(self.pictures_changed)
        for part in (self.panelsChanged, self.cornersChanged, self.mapDataChanged):
            self.chartChanged.connect(part)
        # Lists rebuilt only when charts change, not on every QML read (connected first: dropped before QML reads)
        self._chart_lists: dict[str, tuple[tuple, list[dict]]] = {}
        self.chartChanged.connect(self._chart_lists.clear)
        self.folder = folder
        self._settings = acquire_viewer_settings(folder)  # viewer settings in memory, written merged in background
        # Cache columns of a shown lap that could not be read again (see lap_cache.CachedColumns): told from the
        # reading thread, shown in the status line on the page thread (queued signal)
        self.lapColumnsLost.connect(self.columns_lost)
        self._lost_listener = self.lapColumnsLost.emit
        set_unreadable_listener(self._lost_listener)
        self._file_actions = 0  # lap files moved in background (deletion, restore), see lap_actions
        self.prefix = f"lap_viewer_{id(self)}|"  # vertex store keys of this page
        self.data = TraceData()
        self.entries: list[LapEntry] = []
        self.external: list[LapEntry] = []
        self.checked: set[str] = set()
        self.reference_key = ""
        self.lap_model = FoldedListModel(LAP_ROLES, "id", self)  # lap rows of expanded sessions listed
        # Models kept between lap changes: QML keeps delegates of rows still there (only new laps create items)
        self.panel_model = DictListModel(PANEL_ROLES, self)
        self.series_models: dict[str, DictListModel] = {}  # channel column: series of its panel
        self.legend_model = DictListModel(LEGEND_ROLES, self)
        self.mapDataChanged.connect(self.mapCornersChanged)
        self.map_lap_model = DictListModel(MAP_LAP_ROLES, self)
        self.track_model = TrackListModel(self)  # track picker rows, made again when tracks or circuit logos change
        self._track_rows: tuple = ()  # tracks & logos version of track picker rows
        self.tracksChanged.connect(self.update_track_rows)
        self.picturesChanged.connect(self.update_track_rows)
        self._tracks: list[str] = []
        self._track = ""
        self._expanded: list[str] = []
        self._best_text = ""
        self._status = ""
        self._status_shown: tuple[str, bool] = ("", False)  # status text & busy indicator last told to QML
        self._warning = ""
        self._revision = 0
        self._panels: list[dict] = []
        self._overview: dict = {}
        self._legend: list[dict] = []
        self._map: dict = {}
        self._gcircle: dict = {}
        self._gcircle_stale = False  # laps changed while G circle tab hidden: built once shown (or read)
        self._line_offsets: dict[str, Any] = {}  # compared line distance to reference line (line mode): key, offsets
        self._band_cache: OrderedDict[float, dict[str, object]] = OrderedDict()  # map scale step: thick lines
        self._preview_step = math.nan  # scale step of thick lines shown
        self._band_cache_applied = False  # shapes of shown step put in vertex store
        self._band_generation = 0  # map built again: scale steps computed in background for older map dropped
        self._prefetching: set[tuple[int, float]] = set()  # map generation & scale steps computed in background
        self._jobs: list[tuple[JobHandle, Callable[[Any], None], Callable[[], Any] | None]] = []
        self._job_timer = QTimer(self)
        self._job_timer.setInterval(JOB_INTERVAL)
        self._job_timer.timeout.connect(self.check_jobs)
        self._idle_timer = QTimer(self)  # worker process stopped after a while without job
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(WORKER_IDLE)
        self._idle_timer.timeout.connect(self.stop_idle_worker)
        self._geometry: track_geometry.TrackGeometry | None = None  # official circuit (game REST API)
        self._geometry_track = ""
        self._geometry_tried: set[str] = set()  # tracks asked to game this session (not asked again)
        self._base = lap_map.MapLine([], [], [])  # line lap placement is measured from (official circuit path)
        self._base_official = False
        self._edges: tuple[list[float], list[float]] = ([], [])  # track edge offsets along base line
        self._lap_offsets: dict[str, tuple[tuple, lap_map.MapLine, list[float], list[int]]] = {}
        self._events: dict[str, tuple[tuple, list[tuple[float, str]]]] = {}  # off track & track limits of laps
        self._color_lines: tuple = ()  # colored map line: (key, colors at each line point), rebuilt if key changes
        self._colored_steps: dict[float, Vertices] = {}  # colored line vertices by map scale step
        self._colored_shown: Vertices | None = None  # colored line vertices put in vertex store
        self._zones: dict[str, tuple[LapData, tuple]] = {}  # lap key: lap data, braking & throttle zones
        # Per lap & per reference results kept while laps stay the same (showing one more lap computes only it)
        self._official_line: tuple = ()  # (key, official circuit path line)
        self._edges_cache: tuple = ()  # (key, track edge offsets along base line)
        self._placements: dict[str, tuple[tuple, tuple]] = {}  # lap key: (key, placement)
        self._prepared_placements: dict[str, tuple[tuple, tuple]] = {}  # measured by loading thread (same keys)
        self._placing = 0  # lap placement jobs running (charts & map built again once done)
        self._map_marks = MapMarks(self, self)  # corner labels & points of map
        self._g_laps: dict[str, tuple] = {}  # lap key: lap data, distances, x, y, peak G
        self._g_drawn: dict[str, tuple] = {}  # lap key: lap data & G scale of dots in vertex store
        self._normals: dict[str, tuple] = {}  # lap key: lap data, map angle, point count, normals of map line
        self._turned: dict[str, tuple] = {}  # lap key: lap data, map angle, lap line turned like map
        self._arrows: tuple = ()  # (line, direction arrows along it)
        self._circuit_shapes: dict[float, tuple] = {}  # map scale: (key, road & edge vertices)
        self._lap_shapes: dict[tuple, tuple] = {}  # (lap key, map scale): (key, thick line, markers & zones of lap)
        self._edge_normals: tuple = ()  # (key, normals of left & right track edges turned like map)
        self._groups: tuple[list[LapEntry], list] | None = None  # sessions of current track entries (cached)
        self._labels: dict[str, str] = {}  # shown lap key: short name (told apart when two are the same)
        self._filter = ""  # lap list search text
        self._no_match = False  # search or clean only filter leaves no lap (lap list hint)
        self._session_kinds: list[str] = []  # lap list session filter, order (see load_list_view)
        self._session_order = "newest"
        self._lap_order = "driven"
        # Deletions undone last first, each lap: path, trash path, marks, checked, reference
        self._undo: list[list[tuple[str, str, dict, bool, bool]]] = []
        self._pending_delete: list[str] = []  # laps deleted once background loading is done
        self._pending_batch: list[tuple[str, str, dict, bool, bool]] | None = None  # deletion they join (undone with)
        self._trash_rows: list[dict] = []  # recently deleted laps (trash folder)
        self._trash_loading = False
        self._trash_serial = 0  # trash listings asked (newest applied only)
        self._replay_lookup = False  # replay file of a lap looked for in background
        self._loaded_paths: set[str] = set()  # laps read by background loading
        self._xy_keys: set[str] = set()  # scatter vertices shown (kept when laps change)
        self._xy = {"mode": "scatter", "x": "speed_kph", "y": "accel_lat", "histogram": "throttle"}  # XY tab
        self._xy_weights: dict[tuple, list[float]] = {}  # histogram time weights per lap, channel & zoomed part
        self._session = SessionTab(self, self)
        self._grids: dict[str, lap_map.LineGrid] = {}  # lap key: driving line points by grid cell (mouse)
        self._limits: lap_map.TrackLimits | None = None  # track edges of current track (game coordinates)
        self._limits_track = ""
        self._limits_source = ""  # "game": track edges from game data, "estimated": from laps spread
        self._track_sectors: list[float] = []  # sector 2 & 3 start distances, median of every lap of track
        self._limits_job: JobHandle | None = None
        self._limits_result: dict = {}
        self._limits_reading = False  # track limits cache file being read in background
        self._limits_token = 0  # latest track limits asked (cache read for a former one ignored)
        self._limits_timer = QTimer(self)
        self._limits_timer.setInterval(100)
        self._limits_timer.timeout.connect(self.check_limits_job)
        self._trail_revision = 0
        self._trail_state: tuple[dict, float, list[float]] | None = None  # map, scale, lap ends of trails built
        self._cursor_state: tuple[tuple, dict] | None = None  # last cursorState: page state & position, state
        self._map_pointer = MapPointer(self, self)  # mouse over map, lap positions at cursor
        self._selected_corner = -1
        self._map_range = (-1.0, -1.0)  # chart markers A & B (reference distances), shown on map
        self._map_shown = 0  # track maps shown (trails built only if any)
        self._map_lines: list[tuple[lap_map.MapLine, PlotLap]] = []
        self._pit: list[lap_map.MapLine] = []  # pit lane parts (official circuit), turned like map
        self._line_cache: dict[str, tuple[LapData, lap_map.MapLine | None]] = {}  # lap key: data, driving line
        self._road = lap_map.MapLine([], [], [])  # circuit: track map file, else reference line
        self._road_numbered = False  # circuit of track map file: its distances are point numbers, not meters
        self._map_angle = 0.0  # radians, map turned by (auto orientation & quarter turns)
        self._map_aspect = 1.0  # map view width / height (auto orientation)
        self._g_points: list[tuple[Sequence[float], Sequence[float], Sequence[float], PlotLap]] = []  # distance, x, y
        self._map_view = (0.0, 0.0, 1.0)  # highlighted reference distances & map meters per pixel
        self._chart_view = (0.0, 0.0)  # chart axis range shown, kept while laps are released
        self._restore_view: tuple[float, float] | None = None
        self._released_view = (0.0, 0.0)
        self._speed_range = (0.0, 0.0)
        self._info_cache: dict[str, tuple[float, dict]] = {}
        self._lap_cache: dict[str, LapData | None] = {}
        self._cache_mtime: dict[str, float] = {}
        self._outline_cache: dict[str, list[tuple[float, float]]] = {}
        self._marks: dict[str, dict[str, dict]] = {}
        self._color_slots: dict[str, int] = {}  # lap color index of each shown lap, kept while shown
        self._failed: set[str] = set()  # checked laps that could not be read
        # (main lap path, lap path): file stamps of both laps checked, whether same circuit (imported lap, see
        # same_imported_circuit; False: another circuit), no lap data kept
        self._shape_checks: dict[tuple[str, str], tuple[tuple[float, float], bool | None]] = {}
        # Selection (shown laps, main, anchor & reference lap) whose shape checks & alignments were just measured in
        # background (load_laps), None if none: another selection picked meanwhile is measured in background too
        self._prepared: tuple | None = None
        self._preparing: tuple | None = None  # selection measured by loading thread
        self._loader: threading.Thread | None = None
        self._exports = LapExports(self, self._lap_cache, self)
        self._loaded: dict[str, LapData | None] = {}
        self._prepared_laps: list[tuple[dict, dict]] = []  # shape checks & aligned laps measured by loading thread
        self._prepared_charts: list[tuple[TraceData, dict[str, Vertices], dict]] = []  # prepared by loading thread
        self._load_plan: tuple | None = None  # laps about to be shown compared by loading thread (see prepare_laps)
        self._prepared_checks: dict[tuple[str, str], tuple[tuple[float, float], bool | None]] = {}
        self._load_total = 0
        self._load_message = ""  # status before loading started
        # Charts of laps about to be shown prepared by loading thread: trace data snapshot laps were set on, vertices
        # (see prepare_chart), None if none
        self._prepared_chart: tuple[TraceData, dict[str, Vertices], dict] | None = None
        self._chart_changes: list[Callable[[TraceData], Any]] = []  # trace data settings changed, applied once ready
        self._chart_afters: list[Callable[[], None]] = []  # chart updates waiting for their series (see update_chart)
        self._chart_generation = 0  # latest chart update: series built in background for an older one dropped
        self._chart_running = False  # charts job running (one at a time: later updates build again once it ends)
        self._chart_rejected = 0  # charts jobs in a row whose snapshot was too old (trace data changed meanwhile)
        self._load_retries = 0  # laps prepared again in a row by loading thread (its snapshot was too old)
        self._panels_axis = False  # time axis of chart panels shown (charts switched to other axis once built)
        self._infos_track = ""  # track whose lap infos are read in background (shown once read)
        self._infos_generation = 0  # latest track load: infos read for an older one ignored
        self._infos_reading = False  # infos of new lap files of shown track read in background (see auto_refresh)
        self._index_saves: dict[str, dict] = {}  # lap infos index path: index waiting to be saved in background
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(30)
        self._load_timer.timeout.connect(self.check_background_load)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(STATUS_DURATION)
        self._status_timer.timeout.connect(lambda: self.set_status("", False))
        self._released = False
        self._hidden = False  # page in background: lap files recorded meanwhile listed & read once shown
        self._refresh_pending = False  # lap files changed while hidden
        self._chosen_reference = ""  # reference lap picked by user (kept by live mode while on same circuit)
        self._switched = False  # circuit of laps opened shown (see switch_circuit) until another track is loaded
        # Laps of another circuit opened: track folder shown (empty: added laps only), laps checked & reference lap
        # once that track is loaded (see switch_circuit)
        self._switch_to: tuple[str, set[str], str] | None = None
        # Laps just added (all, shown, reference lap): viewer switches to their circuit if every shown one is found
        # driven on another circuit from its telemetry once loaded (see drop_other_shapes), switch asked meanwhile
        self._added_batch: tuple[list[str], list[str], str] | None = None
        self._pending_switch: tuple[list[str], list[str], str] | None = None
        self._release_timer = QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.setInterval(lap_viewer.RELEASE_DELAY)
        self._release_timer.timeout.connect(self.release_laps)
        self._prefetch_step = 0.0
        self._prefetch_timer = QTimer(self)  # neighbor map scales built once map view settles
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(PREFETCH_DELAY)
        self._prefetch_timer.timeout.connect(lambda: self.prefetch_steps(self._prefetch_step))
        self._zoom_timer = QTimer(self)  # G circle zoomed part built once chart zoom settles
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(60)
        self._zoom_timer.timeout.connect(self.update_gcircle_zoom)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(WATCH_DELAY)
        self._watch_timer.timeout.connect(self.auto_refresh)
        self._watcher = QFileSystemWatcher(self)
        self._watched: dict[str, tuple] = {}  # folder: lap files & track folders seen (hidden files left out)
        self._listing: set[str] = set()  # watched folders being listed in background (see list_watched)
        self._new_lap_tracks: set[str] = set()  # other track folders with new lap files (live mode: track shown)
        self._watcher.directoryChanged.connect(self.folder_changed)
        setting = load_viewer_setting(folder)
        self._hide_unclean = bool(setting.get("hide_unclean_laps", False))
        self.load_list_view(setting)
        self.data.set_time_axis(bool(setting.get("time_axis", False)))
        mode = setting.get("map_color_mode", "gain" if setting.get("map_time_gain") else "laps")
        self._map_mode = mode if mode in lap_map.MAP_MODES else "laps"
        self._map_follow = bool(setting.get("map_follow_zoom", True))
        self._map_braking = bool(setting.get("map_braking_points", True))
        self._map_slip = bool(setting.get("map_slip_points", True))
        saved_options = setting.get("map_options", {})
        saved_options = saved_options if isinstance(saved_options, dict) else {}
        self._map_options = {name: bool(saved_options.get(name, default)) for name, default in MAP_OPTIONS.items()}
        self._map_auto_orient = bool(setting.get("map_auto_orient", False))
        self._map_quarters = self.int_setting(setting, "map_rotation", 0) % 4
        self._corner_table = CornerTable(self, setting, self)
        self._smoothing = min(max(self.int_setting(setting, "smoothing", 0), 0), len(SMOOTHING_LEVELS) - 1)
        self.data.set_smoothing(SMOOTHING_LEVELS[self._smoothing])
        window = self.int_setting(setting, "delta_window", 40)
        self._delta_window = window if window in DELTA_RATE_WINDOWS else 40  # picked (charts may still be built)
        self.data.set_delta_window(float(self._delta_window))
        self._envelope = bool(setting.get("envelope", False))
        self._g_envelope = bool(setting.get("g_envelope", False))
        self._live = bool(setting.get("live_mode", False))
        self._ideal_delta = bool(setting.get("ideal_delta", False))  # picked (charts may still be built)
        self.data.set_ideal_mode(self._ideal_delta)
        self._time_axis = self.data.time_axis  # picked (charts may still be built)
        self._panels_axis = self._time_axis
        saved_xy = setting.get("xy", {})
        if isinstance(saved_xy, dict):
            self._xy.update({name: value for name, value in saved_xy.items()
                             if name in self._xy and isinstance(value, str)})
        side_tab = self.int_setting(setting, "side_tab", 0)
        # Simple view: page mode over charts (was side tab 6 before, opened again as simple view)
        self._simple_view = bool(setting.get("simple_view", side_tab == 6))
        self._side_tab = 0 if side_tab == 6 else min(max(side_tab, 0), 5)  # track map under simple view
        layout = setting.get("layout", "")
        self._layout = layout if isinstance(layout, str) else ""
        self._math = MathChannels(self, setting, self)  # before saved channels: math channels shown are kept
        self._dashboard = DashboardTab(self, self.data, self._simple_view, self)
        self._charts = ChartTools(self, setting, self)
        self._conditions = LapConditions(self, setting, self)
        self._track_notes = TrackNotes(self, self)
        self._library = ImportedLaps(self, self)  # imported laps library panel
        self._map_consistency = MapConsistency(self, setting, self)
        self._list_revision = 0  # lap list filled again (lap files may have changed)
        weights = setting.get("panel_weights", {})
        self._weights: dict[str, float] = {
            column: float(weight) for column, weight in weights.items()
            if column in CHANNEL_MAP and isinstance(weight, (int, float)) and 0.2 <= weight <= 6
        } if isinstance(weights, dict) else {}
        pins = setting.get("pins", {})
        self._pins: dict[str, float] = {  # position kept on each track (reference lap distance)
            track: float(distance) for track, distance in pins.items() if isinstance(distance, (int, float))
        } if isinstance(pins, dict) else {}
        columns = setting.get("channels", [])
        self.visible = [column for column in columns if column in CHANNEL_MAP] if isinstance(columns, list) else []
        self.visible = self.visible or list(DEFAULT_CHANNELS)
        app_signal.refresh.connect(self.units_refresh)  # unit setting changed in settings dialog
        self._units_connected = True

    int_setting = staticmethod(int_setting)

    def release_resources(self):
        """Forget page vertices (page closed), worker process stopped (page timers that would stop it go too)

        Exports still running finish in worker process (other jobs dropped): files written whole. Page timers
        stopped & jobs forgotten: a check before page deletion would see the stopped worker as broken (jobs in
        threads for the rest of the session).
        """
        VertexStore.remove_prefix(self.prefix)
        remove_unreadable_listener(self._lost_listener)
        release_viewer_settings(self.folder)  # pending setting changes written now
        for timer in (self._job_timer, self._limits_timer, self._idle_timer, self._load_timer, self._prefetch_timer,
                      self._zoom_timer, self._watch_timer, self._release_timer):
            timer.stop()
        for handle in [job[0] for job in self._jobs] + ([self._limits_job] if self._limits_job is not None else []):
            if handle.future is not None and handle.name not in EXPORT_JOBS:
                handle.future.cancel()  # waiting page jobs not done (running one ends soon), in fallback thread too
        if self._exports.exporting() or self._exports.importing():
            stop_worker(finish=True)
        else:
            kill_worker()
        self._jobs = []
        self._limits_job = None
        self._chart_changes, self._chart_afters = [], []  # chart updates waiting for dropped jobs
        self._chart_generation += 1  # running charts job stops at its next pause
        self._chart_running = False
        if self._units_connected:
            self._units_connected = False
            with suppress(RuntimeError, TypeError):
                app_signal.refresh.disconnect(self.units_refresh)
        for part in self.parts():
            part.release()
        self.release_lap_data()

    def release_lap_data(self):
        """Page closed: loaded laps & everything kept per lap forgotten at once (not after 60 s like a hidden page,
        see release_laps), a loading still running ends unread (load timer stopped)"""
        self._lap_cache.clear()
        self._cache_mtime.clear()
        self._loaded = {}
        self._prepared_laps, self._prepared_charts, self._prepared_chart = [], [], None
        self.clear_lap_caches()
        forget_increasing()
        self.data.release()  # never reads unit settings (unloaded while app quits)

    def parts(self) -> tuple[PagePart, ...]:
        """Page parts (children of page)"""
        return (self._conditions, self._dashboard, self._session, self._math, self._charts, self._exports,
                self._corner_table, self._track_notes, self._map_consistency, self._map_marks, self._map_pointer,
                self._library)

    def run_job(self, name: str, work: Callable[[], Any], done: Callable[[Any], None]):
        """Run work in a thread, done(result) called on page thread once finished (result None if failed)"""
        self.add_job(start_thread_job(name, work), done)

    def run_process_job(self, name: str, done: Callable[[Any], None], function: Callable, *args):
        """Run module level function in worker process (fallback thread if not available), done(result) on page
        thread"""
        self.add_job(start_job(name, function, *args), done, lambda: function(*args))

    def add_job(self, handle: JobHandle, done: Callable[[Any], None], retry: Callable[[], Any] | None = None):
        self._jobs.append((handle, done, retry))
        self._idle_timer.stop()
        self._job_timer.start()

    @Slot()
    def check_jobs(self):
        """Finished background jobs: results handled on page thread (a result failing never drops the others)"""
        finished: list[tuple[JobHandle, Callable[[Any], None], Callable[[], Any] | None]] = []
        running: list[tuple[JobHandle, Callable[[Any], None], Callable[[], Any] | None]] = []
        for job in self._jobs:  # checked once: a job ending meanwhile is handled next time, never lost
            (running if job[0].is_alive() else finished).append(job)
        self._jobs = running
        results = [(job, job[0].result()) for job in finished]
        # Imports lost with worker process first: worker blamed on them is started again, not marked broken
        results.sort(key=lambda item: not (item[1] is JobHandle.BROKEN and item[0][0].name in IMPORT_JOBS))
        for (handle, done, retry), result in results:
            if result is JobHandle.BROKEN:  # worker process died: job run again in fallback thread (one at a time)
                worker_died(handle)
                if retry is not None and handle.name not in IMPORT_JOBS:
                    self.add_job(start_fallback_job(handle.name, retry), done)
                    continue
                result = None  # import never run in page process (log may have killed worker): failed
            try:
                done(result)
            except Exception:  # page goes on, other results handled
                logger.exception("LAP VIEWER: %s result not handled", handle.name)
        if not self._jobs and self._limits_job is None:
            self._job_timer.stop()
            if _worker is not None:
                self._idle_timer.start()

    @Slot()
    def stop_idle_worker(self):
        if not self._jobs and self._limits_job is None:
            stop_worker()

    def wait_jobs(self):
        """Wait for background jobs & handle results (tests), neighbor map scales prepared now"""
        if self._prefetch_timer.isActive():
            self._prefetch_timer.stop()
            self.prefetch_steps(self._prefetch_step)
        while self._jobs:
            for handle, _, _ in list(self._jobs):
                handle.join()
            self.check_jobs()

    def load_lap_file(self, path: str) -> LapData:
        """Lap from binary cache if lap file did not change, else from CSV (cached), raises OSError or ValueError"""
        return load_cached_lap(self.folder, path)

    @Slot(bool)
    def units_refresh(self, _changed: bool = True):
        """Unit setting changed (settings dialog): charts, corners & map labels in new units"""
        if not self.data.units_changed():
            return
        if not self.data.laps:
            self.data.refresh_units()
        self.optionsChanged.emit()  # distance unit of axis, ruler & scale bar
        if self.data.laps:
            self.update_chart(self.rebuild_chart_now, TraceData.refresh_units)
        entries = {entry.file.path: entry for entry in self.all_entries()}
        self.lap_model.update_rows(  # conditions tooltip (temperatures, fuel) in new units, list kept in place
            lambda row: {"tip": self.entry_conditions(entries[row["path"]])} if row["path"] in entries else {})
        self._session.changed.emit()

    # Properties
    def _tracks_get(self) -> list[str]:
        return self._tracks

    def _track_get(self) -> str:
        return self._track

    def _track_set(self, track: str):
        if self._infos_track and track == self._infos_track:
            return  # its lap infos being read
        self._switch_to = None  # track picked: its own laps shown (circuit switch still loading dropped)
        if track != self._track or self._infos_track:  # shown track picked again: pending track dropped
            self.load_track(track)

    tracks = Property(list, _tracks_get, notify=tracksChanged)
    currentTrack = Property(str, _track_get, _track_set, notify=tracksChanged)

    @Property(QObject, constant=True)
    def trackModel(self) -> QObject:
        """Track picker rows, filtered by its search text (see TrackListModel)"""
        return self.track_model

    @Property(str, notify=tracksChanged)
    def trackLabel(self) -> str:
        """Circuit shown without track folder (laps of another circuit opened from a log or another folder, see
        switch_circuit): its name in track picker, empty if a track folder is shown"""
        if self._track or not self.external:
            return ""
        infos = {entry.file.path: entry.info for entry in self.external}
        key = self.reference_key if self.reference_key in infos else self.external[0].file.path
        return ", ".join(self.circuit_names([key], infos))

    @Property(int, notify=picturesChanged)
    def pictureVersion(self) -> int:
        """Grows when game logos arrive (bindings calling trackLogo depend on it)"""
        return self._picture_version

    # Page parts (composed children, own state & slots): QML backend.<part>.<member>
    @Property(QObject, constant=True)
    def conditions(self) -> LapConditions:
        """Similar conditions reference & setup differences (see lap_conditions)"""
        return self._conditions

    @Property(QObject, constant=True)
    def mapPointer(self) -> MapPointer:
        """Mouse over map & lap positions at cursor (see lap_map_pointer)"""
        return self._map_pointer

    @Property(QObject, constant=True)
    def mapMarks(self) -> MapMarks:
        """Corner labels & points of track map (see lap_map_marks)"""
        return self._map_marks

    @Property(QObject, constant=True)
    def mapConsistency(self) -> MapConsistency:
        """Consistency mode of track map: laps compared, spreads (see lap_consistency)"""
        return self._map_consistency

    @Property(QObject, constant=True)
    def trackNotes(self) -> TrackNotes:
        """Notes at track distances, shared with Track Notes overlay (see lap_track_notes)"""
        return self._track_notes

    @Property(QObject, constant=True)
    def library(self) -> ImportedLaps:
        """Imported laps library panel: MoTeC logs & other drivers' laps (see lap_library_panel)"""
        return self._library

    @Property(QObject, constant=True)
    def dashboard(self) -> DashboardTab:
        """Simple view & Show menu (see lap_dashboard)"""
        return self._dashboard

    @Property(QObject, constant=True)
    def session(self) -> SessionTab:
        """Session tab: every lap of a session of current track (see lap_session)"""
        return self._session

    def session_shown(self) -> bool:
        """Session tab shown (its lap values read)"""
        return self._side_tab == 4

    def session_corners(self) -> list[tuple[int, float, float, float]]:
        """Corners of reference lap (number, start, apex & end distances): corner values of session tab"""
        return [(row.corner.number, row.corner.start, row.corner.apex, row.corner.end)
                for row in self._corner_table.rows]

    @Property(QObject, constant=True)
    def math(self) -> MathChannels:
        """Math channels (see lap_charts)"""
        return self._math

    @Property(QObject, constant=True)
    def charts(self) -> ChartTools:
        """Value axis of panels & laps aligned on a braking point (see lap_charts)"""
        return self._charts

    @Property(QObject, constant=True)
    def cornerTable(self) -> CornerTable:
        """Corner by corner comparison with reference lap, coaching, corner card (see lap_corners)"""
        return self._corner_table

    def corner_rows(self) -> list[CornerComparison]:
        """Corners of reference lap compared (corner table rows)"""
        return self._corner_table.rows

    @Slot()
    def analyzeLastLap(self):
        """Guided analysis: best lap of track against newest lap (Best vs Last Lap), Corners tab opened once both are
        shown, charts zoomed on the corner where the newest lap loses most time (lostCornersShown)"""
        laps = [entry.file for entry in self.entries]
        if not laps:
            self.set_status(tr("No recorded lap"))
            return
        best = best_laps(laps, 1)
        newest = laps[0].path
        if not best or path_key(best[0].path) == path_key(newest):
            self.compareBestLast()
            self.set_status(tr("Your last lap is your best lap: nothing lost against it"))
            return
        from .lap_focus import LostCornerFocus, analyze_last_lap

        for waiting in self.findChildren(LostCornerFocus):  # asked again before laps were shown: newest ask only
            waiting.stop()
        self._corner_table.compare_key = newest  # compared corner by corner (shown laps: best & newest only)
        self.compareBestLast()
        analyze_last_lap(self, best[0].path, newest)

    def compared_lap(self) -> PlotLap | None:
        """Lap compared corner by corner & on gain map"""
        return self._corner_table.compared_lap()

    def row_label(self, row: CornerComparison) -> str:
        return self._corner_table.row_label(row)

    def lap_corner_stats(self, lap: PlotLap) -> tuple[ResampledLap, list[CornerStats | None]]:
        return self._corner_table.lap_corner_stats(lap)

    def resampled(self, lap: PlotLap) -> ResampledLap:
        return self._corner_table.resampled(lap)

    def track_name(self) -> str:
        """Track of displayed laps (see CornerTable.track_name)"""
        return self._corner_table.track_name()

    def track_limits(self) -> lap_map.TrackLimits | None:
        """Track edges of current track (game coordinates), None if unknown"""
        return self._limits

    def track_edges(self) -> tuple[list[float], list[float]]:
        """Track edge offsets along base line"""
        return self._edges

    def compared_changed(self):
        """Compared lap changed: corner labels & colors of map (rest of map unchanged: not read again by QML)"""
        if self._map:
            self._map["corners"] = self._map_marks.corner_points()
            self._map["sectors"] = self._map_marks.sector_labels()
            if self._map_mode in ("gain", "line", "corners"):  # colors depend on compared lap
                self.build_colored_line(self._map_view[2])
                self.bump_revision()
            self.mapCornersChanged.emit()

    def corners_found(self):
        """Corners found again (sensitivity changed): map corners, driving points & thick lines built again"""
        if self._map:
            self._map["corners"] = self._map_marks.corner_points()
            self._map["points"] = self._map_marks.driving_points()
            self._band_cache = OrderedDict()
            self._band_generation += 1
            self._preview_step = math.nan
            self._band_cache_applied = False
            self.build_map_bands()
            self.bump_revision()
            self.mapDataChanged.emit()

    def alignment_moved(self):
        """Laps shifted on another braking point: legend offsets, panels & charts again"""
        self._legend = [dict(row, offset=legend_offset(self.data, row["key"])) for row in self._legend]
        self.legend_model.sync(self._legend)
        self.build_panels()
        self.drop_unused_vertices()
        self.bump_revision()
        self.chartChanged.emit()

    def autoscale_changed(self, autoscale: set[str]):
        """Panels fitted to visible part of lap changed"""
        self._panels = [dict(panel, autoscale=panel["column"] in autoscale) for panel in self._panels]
        self.panelsChanged.emit()

    def drop_panel_weight(self, column: str) -> dict[str, float]:
        """Panel height of a channel no longer shown forgotten, panel heights left"""
        self._weights.pop(column, None)
        return self._weights

    @Property(QObject, constant=True)
    def exports(self) -> LapExports:
        """MoTeC & CSV exports, imports, delta best, pictures & corner report (see lap_export)"""
        return self._exports

    def import_motec(self, filenames: list[str], background: bool = True,
                     done: Callable[[list[tuple[str, list[str], str]]], None] | None = None):
        """MoTeC logs imported as page jobs (also by imported laps library, see lap_library_panel & LapExports)"""
        self._exports.import_motec(filenames, background, done)

    def shown_track(self) -> str:
        """Track folder shown ("Track - Class"), empty if none (laps of another circuit opened)"""
        return self._track

    def track_map(self) -> dict:
        """Track map shapes & labels (see trackMap), empty if none"""
        return self._map

    def corner_table(self) -> list[dict]:
        """Corner table rows (see CornerTable.items)"""
        return self._corner_table.table()

    def coaching_rows(self) -> list[dict]:
        """Corners where compared lap loses most time (see CornerTable.coaching)"""
        return self._corner_table.coaching_rows()

    @Property(QObject, constant=True)
    def laps(self) -> QObject:
        return self.lap_model

    @Property(QObject, constant=True)
    def panelModel(self) -> QObject:
        """Chart panels (lines layer): rows kept while their channel stays shown"""
        return self.panel_model

    @Property(QObject, constant=True)
    def legendModel(self) -> QObject:
        return self.legend_model

    @Property(QObject, constant=True)
    def mapLaps(self) -> QObject:
        """Lap lines & markers of track map: rows kept while their lap stays shown"""
        return self.map_lap_model

    @Property(list, notify=listChanged)
    def expanded(self) -> list[str]:
        return self._expanded

    @Property(str, notify=listChanged)
    def bestText(self) -> str:
        return self._best_text

    @Property(bool, notify=listChanged)
    def hideUnclean(self) -> bool:
        return self._hide_unclean

    @Property(list, notify=listOrderChanged)
    def sessionKinds(self) -> list[str]:
        """Session kinds listed: practice, qualify, race"""
        return self._session_kinds

    @Property(dict, notify=listOrderChanged)
    def sessionCounts(self) -> dict[str, int]:
        """Sessions of current track by kind (filter menu)"""
        return self.session_counts()

    @Property(str, notify=listOrderChanged)
    def sessionOrder(self) -> str:
        return self._session_order

    @Property(str, notify=listOrderChanged)
    def lapOrder(self) -> str:
        return self._lap_order

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=statusChanged)
    def loading(self) -> bool:
        """Laps or lap infos being read or MoTeC logs imported (busy indicator)"""
        return self.busy()

    def busy(self) -> bool:
        """Busy indicator state (see loading), a few attribute checks: worked out on read, never a stale value"""
        return self._loader is not None or self._exports.importing() or self.reading_infos()

    @Property(int, notify=revisionChanged)
    def revision(self) -> int:
        return self._revision

    @Property(list, notify=panelsChanged)
    def panels(self) -> list[dict]:
        return self._panels

    @Property(dict, notify=chartChanged)
    def overview(self) -> dict:
        """Speed of reference lap over whole lap, for zoom navigator"""
        return self._overview

    @Property(list, notify=chartChanged)
    def legend(self) -> list[dict]:
        return self._legend

    @Property(str, notify=chartChanged)
    def warning(self) -> str:
        return self._warning

    @Property(float, notify=chartChanged)
    def maxX(self) -> float:
        return self.data.max_x()

    @Property(bool, notify=chartChanged)
    def timeAxis(self) -> bool:
        return self.data.time_axis

    def chart_list(self, name: str, key: tuple, build: Callable[[], list[dict]]) -> list[dict]:
        """List property computed once until charts change (chartChanged) or its key does"""
        cached = self._chart_lists.get(name)
        if cached is None or cached[0] != key:
            cached = (key, build())
            self._chart_lists[name] = cached
        return cached[1]

    @Property(list, notify=chartChanged)
    def sectorLines(self) -> list[dict]:
        return self.chart_list(
            "sectorLines", (tuple(self.data.sector_lines), self.data.time_axis, id(self.data.reference)),
            lambda: [{"x": self.data.x_at_distance(distance), "label": f"S{index + 2}", "index": index + 1}
                     for index, distance in enumerate(self.data.sector_lines)])

    @Property(dict, notify=mapCornersChanged)
    def mapCorners(self) -> dict:
        """Corner labels & sector labels of map (also in trackMap): changed alone when compared lap changes"""
        return {"corners": self._map.get("corners", []), "sectors": self._map.get("sectors", [])} if self._map else {}

    @Property(dict, notify=mapDataChanged)
    def trackMap(self) -> dict:
        return self._map

    @Property(dict, notify=gCircleChanged)
    def gCircle(self) -> dict:
        """Dots of shown laps & G scale, built now if laps changed while G circle tab was hidden"""
        if self._gcircle_stale:
            self.build_gcircle(True)
        return self._gcircle

    @Property(list, notify=chartChanged)
    def comparedLaps(self) -> list[dict]:
        """Laps that can be compared with reference (corner table, gain map): key, label, color"""
        laps = self.data.compared()
        return self.chart_list(
            "comparedLaps", tuple((lap.key, lap.color.rgba()) for lap in laps),
            lambda: [{"key": lap.key, "label": self.short_label(lap.key), "color": lap.color.name()} for lap in laps])

    @Property(str, notify=chartChanged)
    def speedUnit(self) -> str:
        return self.data.units["speed"][1]

    @Property(str, notify=optionsChanged)
    def distanceUnit(self) -> str:
        """User distance unit symbol: m or ft (axis, ruler, scale bar)"""
        return distance_unit()[1]

    @Property(float, notify=optionsChanged)
    def distanceScale(self) -> float:
        """User distance unit per meter"""
        return distance_unit()[0]

    @Property(list, notify=optionsChanged)
    def deltaWindowTexts(self) -> list[str]:
        """Time gain/loss windows in user distance unit (menu)"""
        return [distance_text(meters) for meters in DELTA_RATE_WINDOWS]

    @Property(float, notify=chartChanged)
    def speedScale(self) -> float:
        """User speed unit per km/h (corner sensitivity shown in user unit)"""
        convert = self.data.units["speed"][0]
        return convert(1.0) if convert is not None else 1.0

    @Property(str, notify=mapChanged)
    def mapMode(self) -> str:
        return self._map_mode

    @Property(bool, notify=mapChanged)
    def mapFollow(self) -> bool:
        return self._map_follow

    @Property(bool, notify=mapChanged)
    def mapBraking(self) -> bool:
        return self._map_braking

    @Property(bool, notify=mapChanged)
    def mapSlip(self) -> bool:
        return self._map_slip

    @Property(bool, notify=mapChanged)
    def mapAutoOrient(self) -> bool:
        return self._map_auto_orient


    @Property(int, notify=trailChanged)
    def trailRevision(self) -> int:
        return self._trail_revision

    @Property(int, notify=selectionChanged)
    def selectedCorner(self) -> int:
        """Corner row selected on map or in corner table, -1 if none"""
        return self._selected_corner

    @Slot(int)
    def setSelectedCorner(self, index: int):
        if index != self._selected_corner:
            self._selected_corner = index
            if self._map:
                self.build_map_overlays(self._map_view[2])
                self.bump_revision()
            self.selectionChanged.emit()

    @Property(float, notify=pinChanged)
    def pinnedX(self) -> float:
        """Axis position kept by clicking charts or map, -1 if none"""
        distance = self._pins.get(self._track, -1.0)
        if distance < 0 or not self.data.laps:
            return -1.0
        return self.data.x_at_distance(distance)

    @Property(dict, notify=pinChanged)
    def mapPin(self) -> dict:
        """Kept position on map (reference line), empty if none"""
        distance = self._pins.get(self._track, -1.0)
        line = self.reference_map_line()
        if distance < 0 or line is None:
            return {}
        x, y = lap_map.point_at(line, distance)
        return {"x": x, "y": y, "angle": math.degrees(lap_map.heading_at(line, distance))}

    @Slot(float)
    def setPinned(self, x: float):
        """Keep position (axis position) on this track, shown until cleared, remembered next time"""
        if not self._track or not self.data.laps:
            return
        self._pins[self._track] = round(self.data.distance_at_x(x), 2)
        save_viewer_setting(self.folder, pins=self._pins)
        self.pinChanged.emit()

    @Slot()
    def clearPinned(self):
        if self._pins.pop(self._track, None) is not None:
            save_viewer_setting(self.folder, pins=self._pins)
            self.pinChanged.emit()

    @Property(bool, notify=mapChanged)
    def hasLimits(self) -> bool:
        return self._limits is not None

    @Property(dict, notify=mapChanged)
    def mapOptions(self) -> dict:
        """Track map display options: apex, exit, arrows, sectors, values, track"""
        return dict(self._map_options)

    @Property(dict, notify=mapChanged)
    def mapLegend(self) -> dict:
        """Colors of current map mode with their meaning (items: gain / loss, pedals, racing line, gear), pedal zones
        colors, gain / loss text colors for the colorblind option (tones: dark, light theme), plus mode scale"""
        colorblind = bool(self._map_options.get("colorblind"))
        legend = dict(self.mode_legend())
        legend.update({"items": lap_map.legend_items(self._map_mode, colorblind), "zones": lap_map.zone_colors(colorblind),
                       "tones": {name: list(pair) for name, pair in lap_map.COLORBLIND_TEXT.items()} if colorblind else {}})
        return legend

    def mode_legend(self) -> dict:
        """Color scale of current map mode: speed range in user unit, elevation range in meters,
        mini-sectors won by each lap & ideal lap, spread of mini-sector times (consistency)"""
        if self._map_mode == "consistency":
            return self._map_consistency.legend()
        if self._map_mode == "minisectors":
            mini = self.mini_sectors()
            if not mini:
                return {}
            rows = [{"label": self.short_label(lap.key), "color": lap.color.name(),
                     "count": mini["winners"].count(index)} for index, lap in enumerate(self.data.laps)]
            return {"mini": rows, "ideal": format_laptime(mini["ideal"]) if mini["ideal"] > 0 else "",
                    "sectors": len(mini["winners"])}
        low, high = self._speed_range
        if high <= low or self._map_mode not in ("speed", "elevation"):
            return {}
        if self._map_mode == "elevation":
            convert, unit = self.data.units["distance"]
            low, high = (convert(value) if convert else value for value in self._speed_range)
            return {"low": f"{low:.0f}", "high": f"{high:.0f}", "unit": unit,
                    "colors": [color.name() for color in lap_map.ELEVATION_COLORS]}
        convert, unit = self.data.units["speed"]
        low, high = (convert(value) if convert else value for value in self._speed_range)
        return {"low": f"{low:.0f}", "high": f"{high:.0f}", "unit": unit,
                "colors": [color.name() for color in lap_map.SPEED_COLORS]}

    @Property(list, notify=channelsChanged)
    def channelMenu(self) -> list[dict]:
        """Every channel: column, title, group (per wheel channels), visible, available in shown laps"""
        menu = []
        for channel in CHANNELS:
            if channel.parts and channel.group:
                title = tr("All 4 wheels")
            elif channel.group:
                title = channel.title[len(channel.group):].strip()
            else:
                title = tr(channel.title)
            menu.append({
                "column": channel.column, "group": tr(channel.group) if channel.group else "", "title": title,
                "search": f"{channel_title(channel)} {channel.title}".lower(),
                "visible": channel.column in self.visible,
                "available": not self.data.laps or self.data.available(channel),
            })
        return menu + self._math.math_menu()

    @Property(list, constant=True)
    def channelPresets(self) -> list[dict]:
        return [{"name": name, "title": tr(name)} for name in CHANNEL_PRESETS]

    @Property(list, notify=mathChanged)
    def mathChannels(self) -> list[dict]:
        """Math channels: name, expression, unit, column (also backend.math.items)"""
        return self._math.math_items()

    @Property(int, notify=optionsChanged)
    def smoothing(self) -> int:
        return self._smoothing

    @Property(list, constant=True)
    def lodLevels(self) -> list[int]:
        """Buckets of reduced series copies (charts pick one for zoom)"""
        return list(LOD_LEVELS)

    @Property(int, constant=True)
    def smoothingLevels(self) -> int:
        return len(SMOOTHING_LEVELS)

    @Property(int, notify=optionsChanged)
    def deltaWindow(self) -> int:
        return self._delta_window

    @Property(list, constant=True)
    def deltaWindows(self) -> list[int]:
        return list(DELTA_RATE_WINDOWS)

    @Property(bool, notify=optionsChanged)
    def envelope(self) -> bool:
        return self._envelope

    @Property(bool, notify=optionsChanged)
    def gEnvelope(self) -> bool:
        return self._g_envelope

    @Property(bool, notify=optionsChanged)
    def liveMode(self) -> bool:
        return self._live

    @Property(int, notify=optionsChanged)
    def sideTab(self) -> int:
        return self._side_tab

    @Property(bool, notify=optionsChanged)
    def simpleView(self) -> bool:
        return self._simple_view

    @Property(QByteArray, notify=optionsChanged)
    def layoutState(self) -> QByteArray:
        try:
            return QByteArray(base64.b64decode(self._layout)) if self._layout else QByteArray()
        except ValueError:
            return QByteArray()

    @Slot(str, str)
    def columns_lost(self, path: str, reason: str):
        """Columns of a shown lap could not be read again from its cache nor its file: told in the status line
        (channels of the lap shown as missing, never as zeros), lap read again from its file when shown next"""
        self._lap_cache.pop(path, None)
        self._cache_mtime.pop(path, None)
        self.set_status(trm(f"Channels of {lap_label(os.path.basename(path))} could not be read "
                            f"again, shown as missing: {reason}"), False)

    def set_status(self, text: str, transient: bool = True):
        """Status line text, transient messages cleared after a while (same message again: shown for the whole
        while again). Rich text of the page: lap & file names, errors in it never read as markup (safe_markup)"""
        self._status = safe_markup(text)
        if transient and text:
            self._status_timer.start()
        else:
            self._status_timer.stop()
        self.notify_status()

    def notify_status(self):
        """statusChanged sent only when status text or busy indicator changed: loading progress sets the same status
        every 30 ms, each signal made every status & loading binding of the page read again"""
        shown = (self._status, self.busy())
        if shown != self._status_shown:
            self._status_shown = shown
            self.statusChanged.emit()

    def bump_revision(self):
        """Vertex store updated: shapes showing changed keys are already told (VertexStore.notify), the global
        revision no longer redraws every shape of the page"""
        self._revision += 1

    # Track limits job in worker process (track limits otherwise in lap_loading)
    def start_limits_job(self, job: dict):
        self._limits_result = job
        self._limits_job = start_job("track limits", track_limits_job, *job["args"])
        self._idle_timer.stop()
        self._limits_timer.start()

    @Slot()
    def check_limits_job(self):
        """Track limits computed: kept, saved & map built again"""
        if self._limits_job is None or self._limits_job.is_alive():
            return
        result = self._limits_job.result()
        job = self._limits_result
        if result is JobHandle.BROKEN:  # worker process died: computed again in fallback thread
            worker_died(self._limits_job)
            self._limits_job = start_fallback_job("track limits", track_limits_job, *job["args"])
            return
        self._limits_timer.stop()
        self._limits_job = None
        if not self._jobs and _worker is not None:
            self._idle_timer.start()
        failed = not isinstance(result, dict) or bool(result.get("unreadable"))
        job["result"] = result if isinstance(result, dict) else {}
        limits = job["result"].get("limits")
        if job["track"] != self._limits_track:
            return
        self._limits = limits
        self._limits_source = job["result"].get("source", "") if limits is not None else ""
        self._track_sectors = job["result"].get("sectors", [])
        if failed:  # job failed or a lap unreadable: not saved, computed again next time track is shown
            logger.warning("LAP VIEWER: track limits of %s not saved (job failed or unreadable laps)", job["track"])
        else:
            self.save_limits(job, limits)
        if self.data.laps:
            self.apply_track_sectors()
            self.place_laps()  # map built again once placement is measured with new edges (in background)
        self.mapChanged.emit()

    # Properties of the mixins (Qt properties stay in the page class): track limits, lap list, lap actions
    @Property(str, notify=mapChanged)
    def limitsSource(self) -> str:
        """Track edges shown: "game" (game data), "estimated" (laps spread), "" (none)"""
        return self._limits_source if self._limits is not None else ""

    @Property(str, notify=listChanged)
    def filterText(self) -> str:
        """Search text used (stripped): search field keeps text as typed"""
        return self._filter

    @Property(bool, notify=listChanged)
    def hasTrackLaps(self) -> bool:
        """Recorded laps of current track (compare presets & guided analysis possible)"""
        return bool(self.entries)

    @Property(bool, notify=listChanged)
    def noMatch(self) -> bool:
        """Search or clean only filter leaves no lap (checked laps stay listed): hint & action to show laps"""
        return self._no_match

    @Property(str, notify=undoChanged)
    def undoText(self) -> str:
        """Undo button text (laps of last deletion), empty if nothing to restore"""
        return trm(f"Undo delete ({len(self._undo[-1])})") if self._undo else ""

    # Recently deleted laps (trash folder, kept TRASH_DAYS days)
    @Property(list, notify=trashChanged)
    def trashRows(self) -> list:
        return self._trash_rows

    @Property(bool, notify=trashChanged)
    def trashLoading(self) -> bool:
        return self._trash_loading

    @Property(int, constant=True)
    def trashDays(self) -> int:
        return TRASH_DAYS

    # Memory release while page is in background (loaded laps released by lap_loading.release_laps)
    def page_hidden(self):
        self._hidden = True
        self._release_timer.start()
        self.pageHidden.emit()  # playing lap would keep moving cursor (backend calls every frame) while hidden

    def page_shown(self):
        self._hidden = False
        self._release_timer.stop()
        released, self._released = self._released, False
        if released:  # same laps & zoom as before
            view = self._released_view
            self._restore_view = view if view[1] > view[0] else None
        if self._refresh_pending:  # laps recorded while hidden: listed now (new lap compared in live mode)
            self._refresh_pending = False
            self.auto_refresh()
        if released and not self.data.laps and self._loader is None:  # not read by list update
            self.load_laps()

    # Charts (lap_panels)
    @Property(bool, notify=optionsChanged)
    def idealDelta(self) -> bool:
        """Delta against ideal lap (fastest clean shown lap in each mini-sector) instead of reference lap"""
        return self._ideal_delta

    @Property(str, notify=chartChanged)
    def idealTime(self) -> str:
        """Ideal lap time of shown laps (delta against ideal lap), empty if unknown"""
        seconds = self.data.ideal_time() if self.data.ideal_mode else 0.0
        return format_laptime(seconds) if seconds > 0 else ""

    @Property(float, notify=chartChanged)
    def referenceLapTime(self) -> float:
        reference = self.data.reference
        return self.data.lap_times(reference)[1][-1] if reference is not None and self.data.lap_times(
            reference)[1] else 0.0

    # XY tab: scatter of two channels, time spent in value ranges (histogram)
    @Property(list, notify=channelsChanged)
    def xyChannels(self) -> list[dict]:
        """Single channels available in shown laps: column, title (unit)"""
        rows = []
        for channel in (*CHANNELS, *(CHANNEL_MAP[channel.column] for channel in self._math.channels)):
            if channel.parts or (self.data.laps and not self.data.available(channel)):
                continue
            unit = self.data.unit_of(channel)
            rows.append({"column": channel.column, "title": channel_title(channel) + (f" ({unit})" if unit else "")})
        return rows

    @Property(dict, notify=optionsChanged)
    def xyState(self) -> dict:
        """XY tab choices: mode (scatter, histogram), x & y channels, histogram channel"""
        return dict(self._xy)
