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
Lap telemetry viewer state for QML page: laps, chart series, track map, G circle, corners, cursor values

Charts, map & G circle vertices go to VertexStore (drawn by GpuShape items),
everything else is exposed as properties of plain values (lists of dicts) & a lap list model.
Track map (lap_map_view), corners (lap_corners), session tab (lap_session) & exports (lap_export) are mixins of
LapViewerBackend: QML properties & signals are declared here (a property's notify signal must be of its class).
"""

from __future__ import annotations

import base64
import bisect
import concurrent.futures
import html
import json
import logging
import math
import multiprocessing
import os
import queue
import shutil
import threading
import time
from collections import Counter, OrderedDict
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
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from ... import app_signal
from ...const_api import API_LMU_CONFIG
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile import track_geometry
from ...userfile.circuit_match import same_imported_circuit
from ...userfile.corner_analysis import (
    SPEED_HYSTERESIS,
    CornerComparison,
    CornerStats,
    IdealLap,
    ResampledLap,
)
from ...userfile.lap_cache import CACHE_FOLDER, load_cached_lap, prune_cache, remove_cached_lap
from ...userfile.lap_geometry import (  # noqa: F401  (limits_part & median_bounds re-exported)
    Yielder,
    limits_part,
    median_bounds,
    session_values,
    track_limits_job,
)
from ...userfile.lap_library import is_foreign, track_of_folder
from ...userfile.lap_marks import load_marks, remove_mark, set_mark
from ...userfile.lap_offset import is_recorded
from ...userfile.telemetry_lap import (
    LapData,
    LapFile,
    best_laps,
    decimate_minmax,
    group_sessions,
    interpolate,
    is_valid_name,
    lap_number_of,
    lap_stem,
    lap_time_of,
    lap_timestamp_of,
    list_laps,
    list_tracks,
    median_sector_bounds,
    read_lap_info,
    same_circuit,
    theoretical_best,
)
from ...userfile.track_corners import TrackCorner
from .. import lap_viewer
from .._common import TextInputDialog
from ..lap_viewer import (
    CHANNEL_MAP,
    CHANNEL_PRESETS,
    CHANNELS,
    DEFAULT_CHANNELS,
    DELTA_CHANNELS,
    DELTA_RATE_WINDOWS,
    INTEGER_CHANNELS,
    PERCENT_RANGES,
    SMOOTHING_LEVELS,
    Channel,
    LapEntry,
    PlotLap,
    channel_title,
    distance_text,
    distance_unit,
    format_axis_time,
    format_axis_value,
    format_channel_value,
    format_laptime,
    lap_color,
    lap_label,
    load_viewer_setting,
    nice_step,
    number_text,
    part_color,
    part_label,
    save_viewer_setting,
    shade,
    signed,
)
from . import lap_map
from .game_pictures import brand_logo_url, notifier, track_logo_url
from .lap_base import COLOR_GAIN, COLOR_LOSS, format_diff, keys_match  # noqa: F401  (re-exported)
from .lap_charts import ChartTools
from .lap_conditions import SIMILAR_TOLERANCE, SIMILAR_TOLERANCES, LapConditions
from .lap_corners import CORNER_SORTS, CornerTable
from .lap_export import LapExports
from .lap_map_view import (  # noqa: F401  (re-exported: lap_backend.scale_step...)
    BAND_CACHE_STEPS,
    CONSISTENCY_SCOPES,
    MAP_OPTIONS,
    PREFETCH_DELAY,
    ZOOM_BUCKETS,
    MapView,
    pit_parts,
    scale_step,
    yaw_calibration,
)
from .lap_session import SessionTab, least_squares  # noqa: F401  (re-exported)
from .lines import (
    VertexStore,
    Vertices,
    dots,
    line_strip,
    range_band,
    step_strip,
)
from .math_channels import PRESETS as MATH_PRESETS
from .math_channels import MathChannel
from .models import DictListModel, FoldedListModel
from .trace_data import TraceData, align_laps

logger = logging.getLogger(__name__)

PANEL_ROLES = ("column", "low", "high", "ticks", "envelope", "note", "available", "seriesModel")
SERIES_ROLES = ("key", "lods", "color", "lap")
LEGEND_ROLES = ("key", "label", "full", "color", "reference", "clean", "tip", "excluded", "offset")
MAP_LAP_ROLES = ("lap", "key", "highlight", "trail", "color", "reference", "shapes", "brakeZones", "throttleZones")
LAP_ROLES = (
    "kind", "session", "path", "title", "time", "s1", "s2", "s3", "best1", "best2", "best3", "info", "note",
    "checked", "reference", "color", "dim", "fastest", "count", "error", "gap", "tip", "open", "hint", "logo",
)
STATUS_DURATION = 8000  # ms, transient status messages shown
WATCH_DELAY = 1500  # ms after a lap file appears before list is refreshed (file fully written)
G_PERCENTILE = 0.99  # G circle scale: share of samples inside (curb & contact spikes left out)
G_SECTORS = 36  # G-G envelope directions
G_ENVELOPE_QUANTILE = 0.98  # G-G envelope radius: share of samples inside, in each direction
LIMITS_FOLDER = ".track_limits"  # track limits cache, in telemetry folder (hidden: not a track)
LIMITS_LAPS = 40  # newest clean laps used to guess track limits
JOB_INTERVAL = 80  # ms, background jobs checked
# Chart series reduced copies (min & max of each bucket, same peaks): drawn when a bucket is at most a pixel wide
LOD_LEVELS = (1500, 4500)  # buckets over whole lap
LOD_MIN_RATIO = 2.5  # copy made only for series with this many samples per bucket or more
TRASH_FOLDER = ".trash"  # deleted laps, in telemetry folder (hidden: not a track), restored by undo
TRASH_DAYS = 30  # deleted laps kept in trash folder
INFO_FOLDER = "info"  # in lap cache folder: lap infos of each track (first line of lap files), see track_infos
INFO_READERS = 8  # threads reading infos of new lap files (first open of a file waits for antivirus scan)
INFO_BACKGROUND = 24  # more lap infos to read from files than this: read in background (track shown once read)
WORKER_IDLE = 60_000  # ms without job before worker process stops (its memory given back)
USE_WORKER_PROCESS = True  # heavy jobs (track limits, session values) in a worker process, else in threads
XY_DOT = 0.007  # scatter dot size, share of plot
HISTOGRAM_BINS = 12  # about this many bins for continuous channels


def percentile(values: list[float], share: float) -> float:
    """Value under which share of values are, 0 if none"""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * share), len(ordered) - 1)]


def g_envelope(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """Closed G-G envelope: grip used in every direction (high quantile radius per direction sector)"""
    radii: list[list[float]] = [[] for _ in range(G_SECTORS)]
    for x, y in zip(xs, ys):
        sector = int((math.atan2(y, x) + math.pi) / math.tau * G_SECTORS) % G_SECTORS
        radii[sector].append(math.hypot(x, y))
    points = []
    for sector, values in enumerate(radii):
        if len(values) >= 3:
            angle = (sector + 0.5) / G_SECTORS * math.tau - math.pi
            radius = percentile(values, G_ENVELOPE_QUANTILE)
            points.append((math.cos(angle) * radius, math.sin(angle) * radius))
    if len(points) < 3:
        return [], []
    points.append(points[0])
    return [x for x, _ in points], [y for _, y in points]


_worker: concurrent.futures.ProcessPoolExecutor | None = None
_worker_broken = False  # worker process could not start (or died running a job): jobs run in fallback thread
_quit_hooked = False  # worker killed when app quits (a running job would delay exit until done)
_finishing: list[concurrent.futures.ProcessPoolExecutor] = []  # worker processes of closed pages ending exports
_export_futures: set[concurrent.futures.Future] = set()  # export jobs not finished yet
_fallback_jobs: queue.SimpleQueue = queue.SimpleQueue()  # jobs worker process could not run: future, work
_fallback_thread: threading.Thread | None = None
_fallback_lock = threading.Lock()
EXPORT_JOBS = ("MoTeC export", "CSV export", "MoTeC import", "Lap import")  # finished even if viewer closed (whole files)
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
        if not future.set_running_or_notify_cancel():
            continue
        try:
            result = work()
        except BaseException as error:  # any failure: future done (logged by JobHandle.result)
            future.set_exception(error)
        else:
            future.set_result(result)


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


def trash_batch_time(name: str) -> float:
    """Time trash batch folder was made (folder name), 0 if not a batch folder"""
    try:
        return time.mktime(time.strptime(name, "%Y-%m-%d %H-%M-%S"))
    except (ValueError, OverflowError):
        return 0.0


def purge_trash(folder: str, days: int = TRASH_DAYS) -> int:
    """Remove deleted laps older than days from trash, returns batch folders removed"""
    root = os.path.join(folder, TRASH_FOLDER)
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    removed = 0
    limit = time.time() - days * 86400
    for name in names:
        made = trash_batch_time(name)
        if 0 < made < limit:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
            removed += 1
    return removed


def setup_text(info: dict) -> str:
    """Setup of a lap: name loaded in game (* if changed in garage), with fingerprint of its values"""
    name = str(info.get("setup_name", ""))
    fingerprint = str(info.get("setup", ""))
    if name:
        name += "*" if info.get("setup_modified") else ""
        return f"{name} ({fingerprint})" if fingerprint else name
    return fingerprint


def time_weights(times: Sequence[float]) -> list[float]:
    """Time each sample stands for (half of time to previous & next sample), histogram weights"""
    count = len(times)
    if count < 2:
        return [1.0] * count
    weights = []
    for index in range(count):
        before = times[index] - times[index - 1] if index > 0 else 0.0
        after = times[index + 1] - times[index] if index + 1 < count else 0.0
        weights.append(max((before + after) / 2, 0.0))
    return weights


def path_key(path: str) -> str:
    """Lap file path compared with others: listed laps use mixed slashes & relative telemetry folder, picked files
    absolute paths"""
    return os.path.normcase(os.path.abspath(path))


def circuit_name(info: dict, path: str) -> str:
    """Track name telling circuits apart: game track name of lap recorded by app, track of track folder
    ("<track> - <class>") of lap without lap info, empty if unknown (imported log: venue name, not game name)"""
    if "combo" in info:
        return str(info.get("track", ""))
    if not (info.get("track") or info.get("track_length")):
        return track_of_folder(path)
    return ""


class LapViewerBackend(MapView, CornerTable, SessionTab, LapExports, ChartTools, LapConditions, QObject):
    """Lap telemetry viewer page state (QML context property "backend")

    Track map, corners, session tab & exports in their own modules (mixins): QML properties & signals here.
    """

    tracksChanged = Signal()
    listChanged = Signal()  # best lap text, expanded sessions, hide unclean
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
    sessionChanged = Signal()  # session tab laps
    undoChanged = Signal()  # deleted laps that can be restored
    mathChanged = Signal()  # math channels added, changed or removed
    gCircleChanged = Signal()  # G circle built (laps changed while its tab is hidden: built once shown)
    # Parts of charts changed alone (also sent by chartChanged): panel height or autoscale, corner table & marks
    # (compared lap, sort, sensitivity, alignment), track map (turned). QML items of other parts are kept.
    panelsChanged = Signal()
    cornersChanged = Signal()
    mapDataChanged = Signal()
    picturesChanged = Signal()  # car brand & circuit logos fetched from game

    def __init__(self, parent: QWidget, folder: str):
        super().__init__(parent)
        self._window = parent
        self._picture_version = 0
        notifier().changed.connect(self.pictures_changed)
        for part in (self.panelsChanged, self.cornersChanged, self.mapDataChanged):
            self.chartChanged.connect(part)
        # Lists rebuilt only when charts change, not on every QML read (connected first: dropped before QML reads)
        self._chart_lists: dict[str, tuple[tuple, list[dict]]] = {}
        self.chartChanged.connect(self._chart_lists.clear)
        self.folder = folder
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
        self.map_lap_model = DictListModel(MAP_LAP_ROLES, self)
        self._tracks: list[str] = []
        self._track = ""
        self._expanded: list[str] = []
        self._best_text = ""
        self._status = ""
        self._warning = ""
        self._revision = 0
        self._panels: list[dict] = []
        self._overview: dict = {}
        self._legend: list[dict] = []
        self._map: dict = {}
        self._gcircle: dict = {}
        self._gcircle_stale = False  # laps changed while G circle tab hidden: built once shown (or read)
        self._corners: list[dict] = []
        self._corner_marks: list[dict] = []
        self._corner_rows: list[CornerComparison] = []
        self._corner_key: tuple = ()  # laps & sensitivity of corner rows (computed again only if changed)
        self._ideal: IdealLap | None = None
        self._lap_corners: dict[str, tuple[tuple, ResampledLap, list[CornerStats | None]]] = {}  # stats of each lap
        self._line_offsets: dict[str, Any] = {}  # compared line distance to reference line (line mode): key, offsets
        self._band_cache: OrderedDict[float, dict[str, object]] = OrderedDict()  # map scale step: thick lines
        self._preview_step = math.nan  # scale step of thick lines shown
        self._band_cache_applied = False  # shapes of shown step put in vertex store
        self._band_generation = 0  # map built again: scale steps computed in background for older map dropped
        self._prefetching: set[float] = set()  # scale steps being computed in background
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
        self._official_key: tuple | None = None  # reference & track of placed official corners
        self._edges_cache: tuple = ()  # (key, track edge offsets along base line)
        self._placements: dict[str, tuple[tuple, tuple]] = {}  # lap key: (key, placement)
        self._trackouts: dict[str, tuple[tuple, dict[int, float]]] = {}  # lap key: (key, track-out point by corner)
        self._slips: dict[str, tuple[LapData, list]] = {}  # lap key: lap data, wheel slip events
        self._g_laps: dict[str, tuple] = {}  # lap key: lap data, distances, x, y, peak G
        self._g_drawn: dict[str, tuple] = {}  # lap key: lap data & G scale of dots in vertex store
        self._resampled: dict[str, ResampledLap] = {}  # lap key: columns on corner grid (same lap, same object)
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
        # Deleted laps: path, trash path, marks, checked, reference
        self._undo: list[tuple[str, str, dict, bool, bool]] = []
        self._pending_delete: list[str] = []  # laps deleted once background loading is done
        self._loaded_paths: set[str] = set()  # laps read by background loading
        self._coaching: list[dict] = []  # corners where compared lap loses most time, causes
        self._xy_keys: set[str] = set()  # scatter vertices shown (kept when laps change)
        self._xy = {"mode": "scatter", "x": "speed_kph", "y": "accel_lat", "histogram": "throttle"}  # XY tab
        self._session_key = ""  # session shown in session tab
        self._session_extra: dict[str, tuple[float, dict]] = {}  # lap path: file time, values read from lap
        self._session_busy = False
        self._yaw: dict[str, tuple[LapData, float, float]] = {}  # lap key: lap data, yaw sign & offset to map heading
        self._grids: dict[str, lap_map.LineGrid] = {}  # lap key: driving line points by grid cell (mouse)
        self._limits: lap_map.TrackLimits | None = None  # track edges of current track (game coordinates)
        self._limits_track = ""
        self._limits_source = ""  # "game": track edges from game data, "estimated": from laps spread
        self._track_sectors: list[float] = []  # sector 2 & 3 start distances, median of every lap of track
        self._limits_job: JobHandle | None = None
        self._limits_result: dict = {}
        self._limits_timer = QTimer(self)
        self._limits_timer.setInterval(100)
        self._limits_timer.timeout.connect(self.check_limits_job)
        self._trail_revision = 0
        self._trail_state: tuple[dict, float, list[float]] | None = None  # map, scale, lap ends of trails built
        self._selected_corner = -1
        self._map_range = (-1.0, -1.0)  # chart markers A & B (reference distances), shown on map
        self._map_shown = 0  # track maps shown (trails built only if any)
        self._official: list[TrackCorner] = []  # official corner numbers (or names) of circuit
        self._official_numbered = True
        self._map_lines: list[tuple[lap_map.MapLine, PlotLap]] = []
        self._pit: list[lap_map.MapLine] = []  # pit lane parts (official circuit), turned like map
        self._line_cache: dict[str, tuple[LapData, lap_map.MapLine | None]] = {}  # lap key: data, driving line
        self._road = lap_map.MapLine([], [], [])  # circuit: track map file, else reference line
        self._map_angle = 0.0  # radians, map turned by (auto orientation & quarter turns)
        self._map_aspect = 1.0  # map view width / height (auto orientation)
        self._g_points: list[tuple[list[float], list[float], list[float], PlotLap]] = []  # distance, x, y
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
        self._compare_key = ""  # lap compared corner by corner & on gain map, first compared lap if not shown
        self._loader: threading.Thread | None = None
        self._exports = 0  # MoTeC & CSV export jobs running
        self._imports = 0  # MoTeC logs being imported
        self._loaded: dict[str, LapData | None] = {}
        self._prepared_laps: list[tuple[dict, dict]] = []  # shape checks & aligned laps measured by loading thread
        self._load_plan: tuple | None = None  # laps about to be shown compared by loading thread (see prepare_laps)
        self._prepared_checks: dict[tuple[str, str], tuple[tuple[float, float], bool | None]] = {}
        self._load_total = 0
        self._load_message = ""  # status before loading started
        self._infos_track = ""  # track whose lap infos are read in background (shown once read)
        self._infos_generation = 0  # latest track load: infos read for an older one ignored
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
        self._new_lap_tracks: set[str] = set()  # other track folders with new lap files (live mode: track shown)
        self._watcher.directoryChanged.connect(self.folder_changed)
        setting = load_viewer_setting(folder)
        self._hide_unclean = bool(setting.get("hide_unclean_laps", False))
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
        saved = setting.get("corner_hysteresis", SPEED_HYSTERESIS)
        self._hysteresis = int(saved) if isinstance(saved, (int, float)) else int(SPEED_HYSTERESIS)
        sort = setting.get("corner_sort", "track")
        self._corner_sort = sort if sort in CORNER_SORTS else "track"
        self._smoothing = min(max(self.int_setting(setting, "smoothing", 0), 0), len(SMOOTHING_LEVELS) - 1)
        self.data.set_smoothing(SMOOTHING_LEVELS[self._smoothing])
        window = self.int_setting(setting, "delta_window", 40)
        self.data.set_delta_window(float(window if window in DELTA_RATE_WINDOWS else 40))
        self._envelope = bool(setting.get("envelope", False))
        self._g_envelope = bool(setting.get("g_envelope", False))
        self._live = bool(setting.get("live_mode", False))
        self.data.set_ideal_mode(bool(setting.get("ideal_delta", False)))
        saved_xy = setting.get("xy", {})
        if isinstance(saved_xy, dict):
            self._xy.update({name: value for name, value in saved_xy.items()
                             if name in self._xy and isinstance(value, str)})
        self._side_tab = min(max(self.int_setting(setting, "side_tab", 0), 0), 5)
        layout = setting.get("layout", "")
        self._layout = layout if isinstance(layout, str) else ""
        self._math: list[MathChannel] = []
        self.load_math_channels(setting)  # before saved channels: math channels shown are kept
        autoscale = setting.get("panel_autoscale", [])
        self._autoscale: set[str] = {
            column for column in autoscale if isinstance(column, str) and column in CHANNEL_MAP
        } if isinstance(autoscale, list) else set()
        self._align_apex = -1.0  # reference distance of corner laps are aligned on (braking start), -1 if none
        tolerance = self.int_setting(setting, "similar_tolerance", SIMILAR_TOLERANCE)
        self._similar_tolerance = tolerance if tolerance in SIMILAR_TOLERANCES else SIMILAR_TOLERANCE
        scope = setting.get("consistency_scope", "session")
        self._consistency_scope = scope if scope in CONSISTENCY_SCOPES else "session"
        self._consistency: dict = {}  # spread of mini-sector times shown on map (consistency mode)
        self._mini_times: dict[str, tuple[float, tuple, list[float]]] = {}  # lap path: file time, bounds, times
        self._mini_busy = False  # mini-sector times of laps not shown being read
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

    @staticmethod
    def int_setting(setting: dict, name: str, default: int) -> int:
        value = setting.get(name, default)
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default

    def release(self):
        """Forget page vertices (page closed), worker process stopped (page timers that would stop it go too)

        Exports still running finish in worker process (other jobs dropped): files written whole. Page timers
        stopped & jobs forgotten: a check before page deletion would see the stopped worker as broken (jobs in
        threads for the rest of the session).
        """
        VertexStore.remove_prefix(self.prefix)
        for timer in (self._job_timer, self._limits_timer, self._idle_timer, self._load_timer, self._prefetch_timer,
                      self._zoom_timer, self._watch_timer, self._release_timer):
            timer.stop()
        for handle in [job[0] for job in self._jobs] + ([self._limits_job] if self._limits_job is not None else []):
            if handle.future is not None and handle.name not in EXPORT_JOBS:
                handle.future.cancel()  # waiting page jobs not done (running one ends soon), in fallback thread too
        if self._exports > 0 or self._imports > 0:
            stop_worker(finish=True)
        else:
            kill_worker()
        self._jobs = []
        self._limits_job = None
        if self._units_connected:
            self._units_connected = False
            with suppress(RuntimeError, TypeError):
                app_signal.refresh.disconnect(self.units_refresh)

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
        if not self.data.refresh_units():
            return
        self.optionsChanged.emit()  # distance unit of axis, ruler & scale bar
        if self.data.laps:
            self.rebuild_chart()
        entries = {entry.file.path: entry for entry in self.all_entries()}
        self.lap_model.update_rows(  # conditions tooltip (temperatures, fuel) in new units, list kept in place
            lambda row: {"tip": self.entry_conditions(entries[row["path"]])} if row["path"] in entries else {})
        self.sessionChanged.emit()

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

    @Slot(str, result=str)
    def trackLogo(self, folder: str) -> str:
        """Circuit logo of game for a track folder ("Track - Class")"""
        return track_logo_url(folder.rsplit(" - ", 1)[0], folder) if folder else ""

    @Slot()
    def pictures_changed(self):
        self._picture_version += 1
        self.picturesChanged.emit()
        if self.entries or self.external:
            self.fill_list()

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

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=statusChanged)
    def loading(self) -> bool:
        """Laps being read or MoTeC logs imported (busy indicator)"""
        return self._loader is not None or self._imports > 0

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

    @Property(list, notify=cornersChanged)
    def cornerMarks(self) -> list[dict]:
        return self._corner_marks

    @Property(dict, notify=mapDataChanged)
    def trackMap(self) -> dict:
        return self._map

    @Property(dict, notify=gCircleChanged)
    def gCircle(self) -> dict:
        """Dots of shown laps & G scale, built now if laps changed while G circle tab was hidden"""
        if self._gcircle_stale:
            self.build_gcircle(True)
        return self._gcircle

    @Property(list, notify=cornersChanged)
    def corners(self) -> list[dict]:
        return self._corners

    @Property(int, notify=cornersChanged)
    def hysteresis(self) -> int:
        return self._hysteresis

    @Property(list, notify=chartChanged)
    def comparedLaps(self) -> list[dict]:
        """Laps that can be compared with reference (corner table, gain map): key, label, color"""
        laps = self.data.compared()
        return self.chart_list(
            "comparedLaps", tuple((lap.key, lap.color.rgba()) for lap in laps),
            lambda: [{"key": lap.key, "label": self.short_label(lap.key), "color": lap.color.name()} for lap in laps])

    @Property(str, notify=cornersChanged)
    def compareKey(self) -> str:
        lap = self.compared_lap()
        return lap.key if lap is not None else ""

    @Property(str, notify=cornersChanged)
    def cornerSort(self) -> str:
        return self._corner_sort

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

    @Property(str, notify=mapChanged)
    def consistencyScope(self) -> str:
        """Laps compared in consistency mode: stint, session (of reference lap) or shown"""
        return self._consistency_scope

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
        """Color scale of current map mode: speed range in user unit, elevation range in meters,
        mini-sectors won by each lap & ideal lap, spread of mini-sector times (consistency)"""
        if self._map_mode == "consistency":
            return self.consistency_legend()
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
        return menu + self.math_menu()

    @Property(list, constant=True)
    def channelPresets(self) -> list[dict]:
        return [{"name": name, "title": tr(name)} for name in CHANNEL_PRESETS]

    @Property(list, notify=mathChanged)
    def mathChannels(self) -> list[dict]:
        """Math channels: name, expression, unit, column"""
        return [{"name": channel.name, "expression": channel.expression, "unit": channel.unit,
                 "column": channel.column} for channel in self._math]

    @Property(list, constant=True)
    def mathPresets(self) -> list[dict]:
        """Built-in math channels: understeer angle, brake release & throttle application rates"""
        return [{"title": tr(name), "expression": expression, "unit": unit} for name, expression, unit in MATH_PRESETS]

    @Property(list, notify=channelsChanged)
    def mathInputs(self) -> list[str]:
        """Channel names math channels can use (editor list)"""
        return self.math_inputs()

    @Property(dict, notify=cornersChanged)
    def alignment(self) -> dict:
        """Corner laps are aligned on (braking start) & offset of each lap, empty if not aligned"""
        return self.alignment_info()

    @Property(int, notify=optionsChanged)
    def similarTolerance(self) -> int:
        """Track temperature difference (°C) of laps in similar conditions"""
        return self._similar_tolerance

    @Property(list, notify=optionsChanged)
    def similarTolerances(self) -> list[dict]:
        """Track temperature differences to choose from: degrees, text in user unit"""
        symbol = lap_viewer.display_units()["temperature"][1]
        factor = 1.8 if symbol.endswith("F") else 1.0
        return [{"value": degrees, "text": f"±{number_text(degrees * factor)}{symbol}"} for degrees in SIMILAR_TOLERANCES]

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
        return int(self.data.delta_window)

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

    @Property(QByteArray, notify=optionsChanged)
    def layoutState(self) -> QByteArray:
        try:
            return QByteArray(base64.b64decode(self._layout)) if self._layout else QByteArray()
        except ValueError:
            return QByteArray()

    def set_status(self, text: str, transient: bool = True):
        """Status line text, transient messages cleared after a while"""
        self._status = text
        if transient and text:
            self._status_timer.start()
        else:
            self._status_timer.stop()
        self.statusChanged.emit()

    def bump_revision(self):
        """Vertex store updated: shapes showing changed keys are already told (VertexStore.notify), the global
        revision no longer redraws every shape of the page"""
        self._revision += 1

    # Tracks & lap list
    @Slot()
    def refresh(self):
        if self._geometry is None:  # game started since: official circuit asked again
            self._geometry_tried.discard(self._track)
            self._geometry_track = ""
        if not self._tracks:  # first refresh: oldest cached laps removed over size limit, old deleted laps
            folder = self.folder
            self.run_job("lap cache", lambda: (prune_cache(folder), purge_trash(folder)), lambda _: None)
        self._tracks = list_tracks(self.folder)
        self._switch_to = None
        # Laps of another circuit shown without track folder (see switch_circuit): kept
        kept = self._track in self._tracks or (not self._track and bool(self.external))
        track = self._track if kept else (self._tracks[0] if self._tracks else "")
        self.drop_changed_laps()
        self._marks.clear()
        self.load_track(track)
        if not self._tracks and not self.external:
            self.set_status(tr("No recorded lap. Enable the Recorder module, then drive a few laps."), False)

    def drop_changed_laps(self):
        """Forget loaded laps whose file changed or was removed, and laps that could not be read (refresh: read
        again, file may be readable now)"""
        for path in list(self._lap_cache):
            try:
                changed = self._lap_cache[path] is None or os.path.getmtime(path) != self._cache_mtime.get(path)
            except OSError:
                changed = True
            if changed:
                self._lap_cache.pop(path, None)
                self._cache_mtime.pop(path, None)

    def load_track(self, track: str, new_lap: LapFile | None = None, background: bool = True):
        """Laps of track listed, laps shown last time on it shown (new_lap: lap just recorded compared, live mode),
        many new lap files: their infos read in background first (unless not background)"""
        laps = list_laps(self.folder, track) if track else []
        self._infos_generation += 1  # infos read for a former load ignored
        self._infos_track = ""
        indexed = self.indexed_infos(track, laps)
        if background and len(indexed[3]) > INFO_BACKGROUND:  # hundreds of new lap files (seconds): page not frozen
            self.read_track_infos(track, new_lap, [lap.path for lap in indexed[3]])
            return
        switch = self._switch_to if self._switch_to is not None and self._switch_to[0] == track else None
        self._switch_to = None
        changed = track != self._track
        self._track = track
        self.entries = [LapEntry(lap, info) for lap, info in zip(laps, self.track_infos(track, laps, indexed))]
        if switch is not None:  # laps opened (kept while track laps infos were read in background)
            self.checked, self.reference_key = set(switch[1]), switch[2]
        elif self._switched and changed:  # circuit of laps opened left: reference picked there not carried over
            self._chosen_reference = ""
        self._switched = switch is not None or (self._switched and not changed)
        adopted = self.adopt_external()
        self.tracksChanged.emit()
        if changed or switch is not None:  # analysis of former circuit laps not carried over (distances)
            self.reset_circuit_state()
        if new_lap is not None:
            self.compare_new_lap(laps, new_lap)
        elif switch is not None:  # laps of another circuit opened: only them shown (track laps listed)
            self.checked &= {entry.file.path for entry in self.all_entries()}  # adopted laps: track lap paths
        else:
            self.checked, self.reference_key = self.track_selection(track, laps, adopted)
        self._expanded = []
        self.watch_folders()
        self.start_geometry(track)
        self.start_limits(track)
        self.fill_list()
        self.load_laps()
        if self._side_tab == 4:  # session tab shown (page opened on it, track changed): its laps read
            self.start_session_job()

    def reset_circuit_state(self):
        """Analysis of former circuit laps not carried over: corner alignment, compared lap, session tab, chart
        markers, selected corner (track or circuit changed)"""
        self._align_apex = -1.0  # laps aligned on a corner
        self._compare_key = ""
        self._session_key = ""
        self._map_range = (-1.0, -1.0)  # chart markers A & B
        if self._selected_corner != -1:
            self._selected_corner = -1
            self.selectionChanged.emit()

    def read_track_infos(self, track: str, new_lap: LapFile | None, paths: list[str]):
        """Lap infos of track read in background, track shown once read (shown track kept meanwhile), unless another
        track was loaded since"""
        generation = self._infos_generation
        self._infos_track = track
        self.set_status(tr("Reading laps..."), False)

        def read(path: str) -> tuple[str, float, dict] | None:
            try:
                mtime = os.path.getmtime(path)
            except OSError:  # removed meanwhile
                return None
            return path, mtime, read_lap_info(path)

        def reading() -> list:
            with concurrent.futures.ThreadPoolExecutor(INFO_READERS, "Lap viewer infos") as pool:
                return list(pool.map(read, paths))

        def done(result):
            for item in result if isinstance(result, list) else []:
                if item is not None:  # kept even if another track is shown: read once
                    self._info_cache[item[0]] = (item[1], item[2])
            if generation != self._infos_generation:
                return  # another track loaded meanwhile
            self._infos_track = ""
            if self._status == tr("Reading laps..."):
                self.set_status("", False)
            self.load_track(track, new_lap, False)  # infos known now (laps failed or added meanwhile: read here)

        self.run_job("lap infos", reading, done)

    def track_selection(self, track: str, laps: list[LapFile], adopted: set[str]) -> tuple[set[str], str]:
        """Laps shown on track & reference: laps shown last time (saved reference, else fastest of them), else fastest
        lap compared with newest other lap; added laps stay checked, an added reference stays if on this circuit"""
        saved = load_viewer_setting(self.folder).get("selections", {})
        saved = saved.get(track, {}) if isinstance(saved, dict) else {}
        saved = saved if isinstance(saved, dict) else {}
        paths = {lap.filename: lap.path for lap in laps}
        names = saved.get("checked", [])
        checked = {paths[name] for name in names if name in paths} if isinstance(names, list) else set()
        reference = paths.get(str(saved.get("reference", "")), "")
        if checked and reference not in checked:  # reference was an added lap (not saved): fastest checked lap
            best = best_laps([lap for lap in laps if lap.path in checked], 1)
            reference = best[0].path if best else next(lap.path for lap in laps if lap.path in checked)
        elif not checked:
            best = best_laps(laps, 1)
            reference = best[0].path if best else (laps[0].path if laps else "")
            checked = {reference} if reference else set()
            newest = next((lap.path for lap in laps if lap.valid and lap.path != reference), "")
            if newest:
                checked.add(newest)
        kept = self.checked & ({entry.file.path for entry in self.external} | adopted)
        if self.reference_key in kept and (not laps or self.same_circuit_paths(laps[0].path, self.reference_key)):
            reference = self.reference_key  # added lap chosen as reference, still shown & driven on this circuit
        return checked | kept, reference

    def adopt_external(self) -> set[str]:
        """Added laps that are laps of shown track listed once, as track laps (check & reference kept), their paths"""
        if not self.external:
            return set()
        listed = {path_key(entry.file.path): entry.file.path for entry in self.entries}
        moved = {entry.file.path: listed[path_key(entry.file.path)] for entry in self.external
                 if path_key(entry.file.path) in listed}
        if not moved:
            return set()
        self.external = [entry for entry in self.external if entry.file.path not in moved]
        self.checked = {moved.get(path, path) for path in self.checked}
        self.reference_key = moved.get(self.reference_key, self.reference_key)
        self._chosen_reference = moved.get(self._chosen_reference, self._chosen_reference)
        return set(moved.values())

    def same_circuit_paths(self, reference: str, path: str) -> bool:
        """Whether listed lap was driven on circuit of reference lap (lap info: game track name & length)"""
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        return same_circuit(LapData("", {}, infos.get(reference, {})), LapData("", {}, infos.get(path, {})))

    # Official circuit: circuit path (game driving line) & pit lane from game REST API (saved), base of lap placement
    def track_title(self, track: str) -> str:
        """Game track name of track folder (lap info), else folder name without class"""
        for entry in self.entries:
            if entry.info.get("track"):
                return str(entry.info["track"])
        return track.rsplit(" - ", 1)[0]

    def start_geometry(self, track: str):
        """Official circuit of track: saved file, else asked to game in background (once per session)

        Saved circuit checked in background: dropped if best lap no longer lies along it (another layout), fetched
        again if game has another version of its layout (or file saved without version).
        """
        if track == self._geometry_track:
            return
        self._geometry_track = track
        saved = self._geometry = track_geometry.load_geometry(self.folder, track) if track else None
        setting = cfg.user.setting.get(API_LMU_CONFIG, {}) if hasattr(cfg.user, "setting") else {}
        ask = bool(track) and track not in self._geometry_tried and bool(setting.get("enable_restapi_access", True))
        clean = [entry for entry in self.entries if entry.file.valid and entry.info.get("kind", "lap") == "lap"]
        if not clean or (saved is None and not ask):
            return
        if ask:
            self._geometry_tried.add(track)
        best = min(clean, key=lambda entry: entry.file.lap_time or float("inf"))
        host, port = str(setting.get("url_host", "localhost")), int(setting.get("url_port", 6397))
        title, folder = self.track_title(track), self.folder

        def best_positions() -> tuple[list[tuple[float, float]], float]:
            """Positions & track length of best lap (empty if unreadable)"""
            try:
                lap = load_cached_lap(folder, best.file.path)
            except (OSError, ValueError):
                return [], 0.0
            found = lap_map.map_line(lap)
            positions = list(zip(found.xs, found.ys)) if found is not None else []
            return positions, float(best.info.get("track_length") or (lap.distance[-1] if len(lap) else 0.0))

        def fetching() -> tuple:
            """(circuit to use) : saved one if still right, else from game, None if none"""
            positions, length = best_positions() if saved is not None else ([], 0.0)
            fitting = saved is not None and track_geometry.fits(saved, positions)
            tracks = track_geometry.rest_get(host, port, "/rest/race/track") if ask else None
            if not isinstance(tracks, list):  # game not running (lap file read only if game answers)
                return (saved if fitting else None,)
            if fitting and saved is not None and saved.name in track_geometry.layout_names(tracks, saved.layout):
                return (saved,)  # current game version
            if saved is None:
                positions, length = best_positions()
            found = track_geometry.fetch_geometry(host, port, title, positions, length, tracks)
            return (found if found is not None else saved if fitting else None,)

        def fetched(result):
            if not isinstance(result, tuple) or result[0] is saved:  # job failed or saved circuit still right
                return
            geometry = result[0]
            if geometry is not None:
                track_geometry.save_geometry(self.folder, track, geometry)  # kept even if another track is shown
            if track != self._track:
                return
            before = self.base_key()
            self._geometry = geometry
            if self.base_key() == before:  # same circuit
                return
            self._limits_track = ""  # placement measured from another base line: track limits again
            self.start_limits(track)
            if self.data.laps:
                self.rebuild_chart()
            if geometry is not None:
                self.set_status(tr("Official circuit map received from game"))
            else:
                logger.info("LAP VIEWER: saved official circuit of %s does not fit recorded laps", track)

        self.run_job("official circuit", fetching, fetched)

    def official_base(self, length: float = 0.0) -> lap_map.MapLine | None:
        """Official circuit path (game driving line, not track center) from start line, distances scaled to lap length,
        None if unknown"""
        geometry = self._geometry
        if geometry is None:
            return None
        key = (geometry, length or geometry.length)
        if self._official_line and keys_match(self._official_line[0], key):
            return self._official_line[1]
        line = lap_map.geometry_line(geometry.center, geometry.start, length or geometry.length)
        self._official_line = (key, line)
        return line

    def base_key(self) -> str:
        """What lap placement is measured from (saved track limits & lap placements valid only for the same): official
        circuit layout, game version, points & start line (nearest points of laps change with them), else lap line"""
        geometry = self._geometry
        if geometry is None:
            return "lap"
        start = "{:.1f},{:.1f}".format(*geometry.start) if geometry.start else "-"
        return f"official|{geometry.layout}|{geometry.name}|{len(geometry.center)}|{start}"

    # Track limits: guessed in background from every clean lap of the track, cached in telemetry folder
    def limits_cache_path(self, track: str) -> str:
        return os.path.join(self.folder, LIMITS_FOLDER, f"{track}.json")

    def limits_parts_folder(self, track: str) -> str:
        """Per lap placement around base line (track limits): only new laps computed when laps change"""
        return os.path.join(self.folder, LIMITS_FOLDER, f"{track}.laps")

    def start_limits(self, track: str):
        """Track limits of track: from cache file if laps did not change, else computed in a thread"""
        if track == self._limits_track and (self._limits is not None or self._limits_job is not None):
            return
        self._limits_track = track
        self._limits = None
        self._limits_source = ""
        self._track_sectors = []
        clean = [entry for entry in self.entries
                 if entry.file.valid and entry.info.get("kind", "lap") not in ("out", "in")][:LIMITS_LAPS]
        if not track or len(clean) < lap_map.LIMITS_MIN_LAPS:
            return
        names = sorted(entry.file.filename for entry in clean)
        cache = self.limits_cache_path(track)
        base_key = self.base_key()
        try:
            with open(cache, encoding="utf-8") as file:
                saved = json.load(file)
            if (isinstance(saved, dict) and saved.get("laps") == names and "sectors" in saved  # damaged: not a dict
                    and saved.get("base", "lap") == base_key
                    and saved.get("version") == lap_map.LIMITS_VERSION):  # older algorithm: computed again
                if saved.get("left"):
                    self._limits = lap_map.TrackLimits(*(
                        lap_map.MapLine([p[0] for p in saved[side]], [p[1] for p in saved[side]],
                                        [p[2] for p in saved[side]])
                        for side in ("left", "right")))
                self._limits_source = str(saved.get("source", "estimated"))
                self._track_sectors = [float(value) for value in saved["sectors"]][:2]
                return
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
        best = min(clean, key=lambda entry: entry.file.lap_time or float("inf"))
        paths = [best.file.path] + [entry.file.path for entry in clean if entry is not best]
        official = self.official_base(float(best.info.get("track_length") or 0.0))
        args = (self.folder, self.limits_parts_folder(track), os.path.join(self.folder, track), paths, official,
                base_key)
        self._limits_result = {"track": track, "names": names, "cache": cache, "base": base_key, "args": args}
        self._limits_job = start_job("track limits", track_limits_job, *args)
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
            self.rebuild_chart()  # map built again: placement measured with new edges
        self.mapChanged.emit()

    def save_limits(self, job: dict, limits: lap_map.TrackLimits | None):
        """Track limits saved in cache file (used while laps of track stay the same)"""
        try:
            os.makedirs(os.path.dirname(job["cache"]), exist_ok=True)
            saved: dict = {"laps": job["names"], "source": self._limits_source, "sectors": self._track_sectors,
                           "base": job["base"], "version": lap_map.LIMITS_VERSION}
            if limits is not None:
                for side, line in (("left", limits.left), ("right", limits.right)):
                    saved[side] = [[round(d, 2), round(x, 2), round(y, 2)]
                                   for d, x, y in zip(line.distances, line.xs, line.ys)]
            with open(job["cache"], "w", encoding="utf-8") as file:
                json.dump(saved, file)
        except OSError as error:
            logger.warning("LAP VIEWER: unable to save track limits: %s", error)

    def apply_track_sectors(self):
        """Sector lines: median of every lap of track (game sector times), else of laps shown"""
        bounds = self._track_sectors or median_sector_bounds([lap.data for lap in self.data.laps])
        if len(bounds) == 2:
            self.data.sector_lines = list(bounds)

    @Property(str, notify=mapChanged)
    def limitsSource(self) -> str:
        """Track edges shown: "game" (game data), "estimated" (laps spread), "" (none)"""
        return self._limits_source if self._limits is not None else ""

    def watch_folders(self):
        """Watch telemetry & current track folders (every track folder in live mode: lap driven on another track
        shown): new laps listed without refresh"""
        current = set(self._watcher.directories())
        tracks = self._tracks if self._live else [self._track] if self._track else []
        folders = (self.folder, *(os.path.join(self.folder, track) for track in tracks))
        wanted = {folder for folder in folders if folder and os.path.isdir(folder)}
        if current - wanted:
            self._watcher.removePaths(list(current - wanted))
        if wanted - current:
            self._watcher.addPaths(list(wanted - current))
        self._watched = {os.path.normpath(folder): self.folder_entries(folder) for folder in wanted}

    @staticmethod
    def folder_entries(folder: str) -> tuple:
        """Lap files & track folders of watched folder (hidden settings, caches, trash & files being written left out)"""
        try:
            names = os.listdir(folder)
        except OSError:
            return ()
        return tuple(sorted(name for name in names if not name.startswith(".") and not name.endswith(".tmp")))

    @Slot(str)
    def folder_changed(self, folder: str):
        """Watched folder changed: list refreshed a moment later only if laps or tracks changed (viewer settings,
        lap caches & trash are written in telemetry folder too)"""
        entries = self.folder_entries(folder)
        key = os.path.normpath(folder)
        seen = self._watched.get(key)
        if seen == entries:
            return
        self._watched[key] = entries
        track = os.path.basename(key)
        if (seen is not None and key != os.path.normpath(self.folder) and track != self._track
                and set(entries) - set(seen)):  # other track folder watched in live mode: new lap there
            self._new_lap_tracks.add(track)
        self._watch_timer.start()

    @Slot()
    def auto_refresh(self):
        """Lap files added or removed: list updated, newest lap compared with best lap in live mode (lap driven on
        another track: that track shown); page hidden: done once shown again (no list update nor lap read while
        driving, laps released stay released)"""
        if self._hidden:
            self._refresh_pending = True
            return
        if self._loader is not None:
            self._watch_timer.start()  # after current loading
            return
        tracks = list_tracks(self.folder)
        added_tracks = [track for track in tracks if track not in self._tracks]
        if tracks != self._tracks:
            self._tracks = tracks
            self.tracksChanged.emit()
        changed, self._new_lap_tracks = self._new_lap_tracks, set()
        if not self._track and tracks and not self.external:  # first lap ever recorded (laps of another circuit
            # shown without track folder kept, see switch_circuit: live mode shows track of a new lap below)
            self.load_track(tracks[0])
            return
        if self._live:
            found = self.other_track_lap(added_tracks + sorted(changed - set(added_tracks)))
            if found is not None:
                self.load_track(*found)
                return
            if added_tracks:  # new track folders watched
                self.watch_folders()
        known = {entry.file.path for entry in self.entries}
        laps = list_laps(self.folder, self._track) if self._track else []
        listed = {lap.path for lap in laps}
        if listed == known:
            return
        new = [lap for lap in laps if lap.path not in known]
        self.entries = [LapEntry(lap, info) for lap, info in zip(laps, self.track_infos(self._track, laps))]
        self.checked = {path for path in self.checked if path in listed or path not in known}
        if self.reference_key not in self.checked:
            self.reference_key = ""
        if self._live and new:
            self.compare_new_lap(laps, new[0])  # lap files newest first
        self.fill_list()
        self.load_laps()

    def other_track_lap(self, tracks: list[str]) -> tuple[str, LapFile] | None:
        """Track & newest lap recorded on other tracks than shown one (live mode), None if none newer than laps of
        shown track (laps copied there)"""
        found = None
        newest = max((lap_timestamp_of(entry.file.filename) for entry in self.entries), default=0.0)
        for track in tracks:
            laps = list_laps(self.folder, track) if track != self._track else []
            timestamp = lap_timestamp_of(laps[0].filename) if laps else 0.0
            if timestamp > newest:
                found, newest = (track, laps[0]), timestamp
        return found

    def compare_new_lap(self, laps: list[LapFile], new_lap: LapFile):
        """Live mode: lap just recorded compared with reference lap picked by user if driven on same circuit, else with
        best lap of track (former best lap if new lap is best lap)"""
        reference = self.reference_key
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        if not (reference and reference == self._chosen_reference and reference != new_lap.path and reference in infos
                and not self.other_circuit((infos.get(new_lap.path, {}), new_lap.path), infos[reference], reference)
                and not self.other_circuit(self.main_circuit(), infos[reference], reference)):
            best = [lap.path for lap in best_laps(laps, 2)]
            reference = next((path for path in best if path != new_lap.path), new_lap.path)
        self.checked = {new_lap.path, reference}
        self.reference_key = reference
        self.set_status(trm(f"New lap: {lap_label(new_lap.filename)}"))

    @Slot(bool)
    def setLiveMode(self, enabled: bool):
        self._live = enabled
        save_viewer_setting(self.folder, live_mode=enabled)
        self.watch_folders()  # every track folder in live mode
        self.optionsChanged.emit()

    def lap_info(self, path: str) -> dict:
        """Lap info (first line of file), read again only if file changed"""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        cached = self._info_cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        info = read_lap_info(path)
        self._info_cache[path] = (mtime, info)
        return info

    def info_index_path(self, track: str) -> str:
        return os.path.join(self.folder, CACHE_FOLDER, INFO_FOLDER, f"{track}.json")

    def indexed_infos(self, track: str, laps: list[LapFile]) -> tuple[dict, dict, dict, list[LapFile]]:
        """Lap file stamps, saved track index, infos known (memory or index) & laps whose info must be read from file"""
        stamps: dict[str, tuple[int, int, float]] = {}
        if not laps:
            return stamps, {}, {}, []
        with suppress(OSError), os.scandir(os.path.join(self.folder, track)) as found:  # no file opened
            for item in found:
                stat = item.stat()
                stamps[item.name] = (stat.st_size, stat.st_mtime_ns, stat.st_mtime)
        path = self.info_index_path(track)
        saved: Any = {}
        with suppress(OSError, ValueError), open(path, encoding="utf-8") as file:
            saved = json.load(file)
        saved = saved if isinstance(saved, dict) else {}  # damaged index ignored
        known: dict[str, dict] = {}
        missing: list[LapFile] = []
        for lap in laps:
            stamp = stamps.get(lap.filename)
            if stamp is None:  # removed meanwhile
                continue
            cached = self._info_cache.get(lap.path)
            indexed = saved.get(lap.filename)
            if cached is not None and cached[0] == stamp[2]:
                known[lap.filename] = cached[1]
            elif (isinstance(indexed, list) and len(indexed) == 3 and indexed[:2] == list(stamp[:2])
                  and isinstance(indexed[2], dict)):
                known[lap.filename] = indexed[2]
            else:
                missing.append(lap)
        return stamps, saved, known, missing

    def track_infos(self, track: str, laps: list[LapFile],
                    indexed: tuple[dict, dict, dict, list[LapFile]] | None = None) -> list[dict]:
        """Infos of track laps: from memory, else from track index (lap file size & time unchanged), else read from
        lap files (index saved again): opening hundreds of new files takes seconds (antivirus scan, see
        read_track_infos)"""
        if not laps:
            return []
        stamps, saved, known, missing = indexed if indexed is not None else self.indexed_infos(track, laps)
        path = self.info_index_path(track)
        paths = [lap.path for lap in missing]
        if len(paths) > 2:  # new files read together: each one is scanned by antivirus on first open
            with concurrent.futures.ThreadPoolExecutor(INFO_READERS, "Lap viewer infos") as pool:
                read = list(pool.map(read_lap_info, paths))
        else:
            read = [read_lap_info(lap_path) for lap_path in paths]
        known.update(zip((lap.filename for lap in missing), read))
        infos, index = [], {}
        for lap in laps:
            stamp = stamps.get(lap.filename)
            if stamp is None:
                infos.append(self.lap_info(lap.path))
                continue
            info = known[lap.filename]
            self._info_cache[lap.path] = (stamp[2], info)
            index[lap.filename] = [stamp[0], stamp[1], info]
            infos.append(info)
        if missing or index.keys() != saved.keys():
            self.save_info_index(path, index)
        return infos

    @staticmethod
    def save_info_index(path: str, index: dict):
        """Lap infos of a track saved atomically (temporary file renamed): never read half written"""
        temp = f"{path}.{os.getpid()}.tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temp, "w", encoding="utf-8", newline="\n") as file:
                json.dump(index, file, separators=(",", ":"))
            os.replace(temp, path)
        except (OSError, TypeError, ValueError) as error:
            logger.warning("LAP VIEWER: unable to save lap infos of track: %s", error)
            with suppress(OSError):
                os.remove(temp)

    def lap_marks(self, path: str) -> dict:
        """Kept state & note of lap"""
        folder, name = os.path.split(path)
        if folder not in self._marks:
            self._marks[folder] = load_marks(folder)
        return self._marks[folder].get(name, {})

    @staticmethod
    def entry_sectors(entry: LapEntry) -> list[float]:
        sectors = entry.info.get("sectors")
        if isinstance(sectors, list) and len(sectors) == 3 and all(isinstance(v, (int, float)) for v in sectors):
            return [float(value) for value in sectors]
        return []

    @staticmethod
    def entry_text(entry: LapEntry, session_vehicle: str = "") -> str:
        """Lap details not shown by its session header"""
        texts = []
        if not entry.file.valid:
            texts.append(tr("invalid"))
        kind = entry.info.get("kind", "")
        if kind == "out":
            texts.append(tr("out lap"))
        elif kind == "in":
            texts.append(tr("in lap"))
        if entry.foreign:
            texts.append(tr("foreign"))
        if entry.external and entry.info.get("session"):
            texts.append(tr(str(entry.info["session"])))
        vehicle = str(entry.info.get("vehicle", ""))
        if vehicle and vehicle != session_vehicle:
            texts.append(vehicle)
        return ", ".join(texts)

    @staticmethod
    def entry_conditions(entry: LapEntry) -> str:
        """Lap conditions tooltip: vehicle, temperatures, wetness, fuel used"""
        info = entry.info
        lines = []
        for key, label in (("vehicle", "Vehicle"), ("class", "Class"), ("combo", "Layout")):
            if info.get(key):
                lines.append(f"{tr(label)}: {info[key]}")

        def number(key: str) -> float | None:
            value = info.get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        convert, symbol = lap_viewer.display_units()["temperature"]
        for key, label in (("track_temperature", "Track Temp"), ("ambient_temperature", "Air Temp")):
            value = number(key)
            if value is not None:
                lines.append(f"{tr(label)}: {number_text(convert(value) if convert else value, 1)}{symbol}")
        wetness = number("wetness")
        if wetness is not None:
            lines.append(f"{tr('Wetness')}: {wetness * 100:.0f}%")
        start, end = number("fuel_start"), number("fuel_end")
        if start is not None:
            convert, symbol = lap_viewer.display_units()["fuel"]
            lines.append(f"{tr('Starting Fuel')}: {number_text(convert(start) if convert else start, 1)} {symbol}")
            if end is not None and start >= end:
                used = start - end
                lines.append(f"{tr('Fuel Used')}: {number_text(convert(used) if convert else used, 2)} {symbol}")
        setup = setup_text(info)
        if setup:
            lines.append(f"{tr('Setup')}: {setup}")
        return "\n".join(lines)

    def all_entries(self) -> list[LapEntry]:
        return self.entries + self.external

    def track_sessions(self) -> list:
        """Laps of current track grouped by session (cached while track laps stay the same)"""
        if self._groups is None or self._groups[0] is not self.entries:
            self._groups = (self.entries, group_sessions(self.entries, lambda entry: entry.file.filename,
                                                         lambda entry: entry.info))
        return self._groups[1]

    def entry_search_text(self, entry: LapEntry) -> str:
        """Everything a lap can be searched by: name, time, session, vehicle, conditions, note, setup"""
        info = entry.info
        number = lap_number_of(entry.file.filename)
        parts = [lap_label(entry.file.filename), trm(f"Lap {number}") if number else "", format_laptime(entry.file.lap_time),
                 str(info.get("session", "")), tr(str(info.get("session", ""))), str(info.get("vehicle", "")),
                 str(info.get("class", "")), str(info.get("combo", "")), str(info.get("setup", "")),
                 str(info.get("setup_name", "")),
                 self.entry_text(entry), self.entry_conditions(entry), entry.file.filename]
        if not entry.external:
            parts.append(str(self.lap_marks(entry.file.path).get("note", "")))
            if self.lap_marks(entry.file.path).get("kept"):
                parts.append(tr("kept"))
        return " ".join(parts).lower()

    def matches_filter(self, entry: LapEntry) -> bool:
        """Lap list search: every word of search text found in lap details"""
        words = self._filter.lower().split()
        if not words:
            return True
        text = self.entry_search_text(entry)
        return all(word in text for word in words)

    @Property(str, notify=listChanged)
    def filterText(self) -> str:
        """Search text used (stripped): search field keeps text as typed"""
        return self._filter

    @Property(bool, notify=listChanged)
    def noMatch(self) -> bool:
        """Search or clean only filter leaves no lap (checked laps stay listed): hint & action to show laps"""
        return self._no_match

    @Slot(str)
    def setFilter(self, text: str):
        """Lap list search text: vehicle, session, conditions, note, setup..."""
        text = text.strip()
        if text != self._filter:
            self._filter = text
            self.fill_list()
            self.update_list_state(self.data.laps)

    def build_labels(self, laps: list[PlotLap]):
        """Short names of shown laps, told apart when two are the same (folder of added laps, else session date)"""
        entries = {entry.file.path: entry for entry in self.all_entries()}
        labels = {lap.key: lap_label(os.path.basename(lap.key)) for lap in laps}
        counts = Counter(labels.values())
        for key, label in list(labels.items()):
            if counts[label] < 2:
                continue
            entry = entries.get(key)
            if entry is None or entry.external:
                extra = os.path.basename(os.path.dirname(key))
            else:
                timestamp = lap_timestamp_of(entry.file.filename)
                extra = time.strftime("%d/%m %H:%M", time.localtime(timestamp)) if timestamp > 0 else ""
            labels[key] = f"{label} ({extra})" if extra else label
        counts = Counter(labels.values())
        seen: Counter = Counter()
        for key, label in list(labels.items()):
            if counts[label] > 1:
                seen[label] += 1
                labels[key] = f"{label} #{seen[label]}"
        self._labels = labels

    def short_label(self, key: str) -> str:
        """Short name of shown lap (legend chips, map, corners)"""
        return self._labels.get(key) or lap_label(os.path.basename(key))

    def fill_list(self):
        """Laps grouped by session (newest first), added files on top, sessions with shown laps expanded

        Rows kept in place (list keeps scroll position), lap rows of collapsed sessions left out of list model.
        """
        # Added files may come from other tracks: theoretical best & best sectors of current track only
        sectors = [self.entry_sectors(entry) for entry in self.entries if entry.file.valid]
        best_total, best_sectors = theoretical_best(sectors)
        best_lap = min((entry.file.lap_time for entry in self.entries if entry.file.valid and entry.file.lap_time > 0),
                       default=0.0)
        shown = self.checked | {self.reference_key}  # listed even if search or clean only filter leaves them out
        matched = False
        entries = []
        for entry in self.entries:
            match = ((not self._hide_unclean or (entry.file.valid and entry.info.get("kind") not in ("out", "in")))
                     and self.matches_filter(entry))
            matched = matched or match
            if match or entry.file.path in shown:
                entries.append(entry)
        groups: list[tuple[list[LapEntry], bool]] = [
            (group, False)
            for group in group_sessions(entries, lambda entry: entry.file.filename, lambda entry: entry.info)
        ]
        added: dict[str, list[LapEntry]] = {}  # added laps by folder (imported log, other track)
        for entry in self.external:
            match = self.matches_filter(entry)
            matched = matched or match
            if match or entry.file.path in shown:
                added.setdefault(os.path.dirname(entry.file.path), []).append(entry)
        groups[:0] = [(group, True) for group in added.values()]
        colors = {lap.key: lap.color.name() for lap in self.data.laps}
        hint = self.circuit_hints()
        rows: list[dict] = []
        expanded = []
        for index, (group, is_added) in enumerate(groups):
            header = self.session_row(group, is_added)
            rows.append(header)
            vehicle = str(group[0].info.get("vehicle", ""))
            fastest = min((entry for entry in group if entry.file.valid and entry.file.lap_time > 0),
                          key=lambda entry: entry.file.lap_time, default=None)
            for entry in group:
                row = self.lap_row(header["session"], entry, best_sectors, vehicle, entry is fastest, best_lap,
                                   colors.get(entry.file.path, ""))
                row.update(hint(row))
                rows.append(row)
            if (index == 0 or header["session"] in self._expanded
                    or any(entry.file.path in shown for entry in group)):
                expanded.append(header["session"])
        self._expanded = expanded
        self.show_rows(rows)
        self._no_match = not matched and bool(self.entries or self.external)
        self.sessionChanged.emit()
        self._best_text = trm(f"Theoretical best: {format_laptime(best_total)}") if best_total > 0 else ""
        self.listChanged.emit()

    def show_rows(self, rows: list[dict]):
        """List rows: lap rows of collapsed sessions left out of list model (no delegate made for them)"""
        opened = set(self._expanded)
        for row in rows:
            if row["kind"] == "session":
                row["open"] = row["session"] in opened
        self.lap_model.set_rows(rows, lambda row: row["kind"] == "session" or row["session"] in opened)

    def circuit_hints(self) -> Callable[[dict], dict]:
        """Lap row change: lap driven on another circuit than reference lap dimmed with a hint (unchecked & never
        compared with it, see drop_other_circuits)"""
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        main = self.main_circuit() if self.entries or self.reference_key in infos else None
        text = tr("Another circuit than reference lap: not compared")

        def hint(row: dict) -> dict:
            if row["kind"] != "lap":
                return {}
            other = main is not None and self.other_circuit(main, infos.get(row["path"], {}), row["path"])
            return {"hint": text if other else ""}

        return hint

    def session_row(self, group: list[LapEntry], is_added: bool) -> dict:
        """Session header: session & date, best lap, number of laps & vehicle"""
        first = group[0]
        if is_added:  # imported log or other folder
            folder = os.path.dirname(first.file.path)
            title = os.path.basename(folder)
            key = f"added {folder}"
        else:
            session = str(first.info.get("session", "")) or tr("Session")
            start = first.info.get("session_start")  # recorded, else when first lap started
            timestamp = start if isinstance(start, (int, float)) else (
                lap_timestamp_of(first.file.filename) - first.file.lap_time)
            date = time.strftime("%d/%m %H:%M", time.localtime(timestamp)) if timestamp > 0 else ""
            title = f"{tr(session)}  {date}".strip()
            key = f"{session} {first.file.filename[:19]}"
        best = min((entry.file.lap_time for entry in group if entry.file.valid and entry.file.lap_time > 0), default=0)
        details = []
        vehicle = str(first.info.get("vehicle", ""))
        if is_added:
            details.append(tr("foreign laps") if first.foreign else tr("added"))
        if vehicle:
            details.append(vehicle)
        return {
            "id": f"session:{key}", "kind": "session", "session": key, "path": "", "title": title,
            "time": format_laptime(best), "s1": "", "s2": "", "s3": "", "best1": False, "best2": False, "best3": False,
            "info": ", ".join(details), "note": "", "count": len(group), "checked": False, "reference": False,
            "color": "", "dim": False, "fastest": False, "error": False, "gap": "", "tip": "", "open": False,
            "hint": "", "logo": brand_logo_url(vehicle) if vehicle and not is_added else "",
        }

    def lap_row(self, session: str, entry: LapEntry, best_sectors: list[float], vehicle: str,
                is_fastest: bool, best_lap: float = 0.0, color: str = "") -> dict:
        """Lap row: number, time, gap to best lap, sectors (best ones flagged), info; invalid & out/in laps dimmed"""
        number = lap_number_of(entry.file.filename)
        sectors = self.entry_sectors(entry) or [0.0, 0.0, 0.0]
        bests = [
            value > 0 and bool(best_sectors) and abs(value - best) < 0.0005 and entry.file.valid and not entry.external
            for value, best in zip(sectors, best_sectors or [0.0, 0.0, 0.0])
        ]
        gap = ""
        if best_lap > 0 and entry.file.lap_time > 0 and not entry.external:
            difference = entry.file.lap_time - best_lap
            gap = signed(difference, 3) if difference >= 0.0005 else ""
        path = entry.file.path
        return {
            "id": path, "kind": "lap", "session": session, "path": path, "vehicle": vehicle,
            "title": trm(f"Lap {number}") if number else lap_stem(entry.file.filename),
            "time": format_laptime(entry.file.lap_time),
            "s1": format_laptime(sectors[0]), "s2": format_laptime(sectors[1]), "s3": format_laptime(sectors[2]),
            "best1": bests[0], "best2": bests[1], "best3": bests[2], **self.mark_values(entry, vehicle),
            "checked": path in self.checked, "reference": path == self.reference_key,
            "color": color, "dim": not entry.file.valid or entry.info.get("kind") in ("out", "in"),
            "fastest": is_fastest, "count": 0, "error": path in self._failed and path in self.checked, "gap": gap,
            "tip": self.entry_conditions(entry), "open": True, "hint": "", "logo": "",
        }

    def mark_values(self, entry: LapEntry, vehicle: str) -> dict:
        """Lap row info & note: details not shown by session header (vehicle), kept state & note of recorded lap"""
        info = self.entry_text(entry, vehicle)
        note = ""
        if not entry.external:
            mark = self.lap_marks(entry.file.path)
            note = str(mark.get("note", ""))
            if mark.get("kept"):
                info = ", ".join(filter(None, [info, tr("kept")]))
        return {"info": info, "note": note}

    def lap_rows(self) -> list[dict]:
        """Lap rows, also of collapsed sessions (their checked laps are shown in charts)"""
        return [row for row in self.lap_model.all_rows if row["kind"] == "lap"]

    def ordered_checked(self) -> list[str]:
        """Checked laps in list order"""
        return [row["path"] for row in self.lap_rows() if row["path"] in self.checked]

    @Slot(str)
    def toggleSession(self, key: str):
        """Session expanded or collapsed: its lap rows added to or removed from list model"""
        if key in self._expanded:
            self._expanded = [session for session in self._expanded if session != key]
        else:
            self._expanded = [*self._expanded, key]
        self.show_rows(self.lap_model.all_rows)
        self.listChanged.emit()

    @Slot(str)
    def toggleLap(self, path: str):
        self.setLapChecked(path, path not in self.checked)

    @Slot(str, bool)
    def setLapChecked(self, path: str, checked: bool):
        if checked:
            self.checked.add(path)
        else:
            self.checked.discard(path)
        self.load_laps()

    @Slot(str, str, bool)
    def selectRange(self, first: str, last: str, checked: bool):
        """Shift+click: every lap seen between two laps checked (or unchecked, reference lap kept): laps of collapsed
        sessions left as they are"""
        paths = [row["path"] for row in self.lap_rows()]
        if first not in paths or last not in paths:
            self.setLapChecked(last, checked)
            return
        listed = {row["path"] for row in self.lap_model.rows} | {first, last}
        low, high = sorted((paths.index(first), paths.index(last)))
        for path in paths[low:high + 1]:
            if path not in listed:
                continue
            if checked:
                self.checked.add(path)
            elif path != self.reference_key:
                self.checked.discard(path)
        self.load_laps()

    @Slot()
    def clearSelection(self):
        """Uncheck every lap except reference lap"""
        self.checked = {self.reference_key} if self.reference_key else set()
        self.load_laps()

    @Slot()
    def compareBestLast(self):
        """Fastest valid lap of track as reference, compared with newest lap"""
        laps = [entry.file for entry in self.entries]
        best = best_laps(laps, 1)
        if not laps:
            return
        newest = laps[0]
        self.reference_key = best[0].path if best else newest.path
        self._chosen_reference = ""  # best lap: follows new laps in live mode
        self.checked = {self.reference_key, newest.path}
        self.fill_list()
        self.load_laps()

    @Slot(int)
    def compareBest(self, count: int):
        """Fastest valid laps of track, fastest as reference"""
        best = best_laps([entry.file for entry in self.entries], count)
        if not best:
            return
        self.reference_key = best[0].path
        self._chosen_reference = ""
        self.checked = {lap.path for lap in best}
        self.fill_list()
        self.load_laps()

    @Slot(str)
    def setReference(self, path: str):
        if not path:  # session header
            return
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        if self.entries and self.other_circuit(self.main_circuit(), infos.get(path, {}), path):
            self.set_status(trm(f"Lap from another circuit, not usable as reference lap: "
                                f"{', '.join(self.circuit_names([path], infos))}"))
            return
        self.reference_key = self._chosen_reference = path
        self.checked.add(path)
        self.load_laps()

    @Slot(bool)
    def setHideUnclean(self, enabled: bool):
        self._hide_unclean = enabled
        save_viewer_setting(self.folder, hide_unclean_laps=enabled)
        self.fill_list()
        self.update_list_state(self.data.laps)

    def save_selection(self, paths: list[str]):
        """Remember checked laps & reference of current track"""
        track_paths = {entry.file.path for entry in self.entries}
        names = sorted(os.path.basename(path) for path in paths if path in track_paths)
        if not self._track or not names:
            return
        selections = load_viewer_setting(self.folder).get("selections", {})
        if not isinstance(selections, dict):
            selections = {}
        reference = os.path.basename(self.reference_key) if self.reference_key in track_paths else ""
        selection = {"checked": names, "reference": reference}
        if selections.get(self._track) != selection:
            selections[self._track] = selection
            save_viewer_setting(self.folder, selections=selections)

    # Lap actions (lap list context menu)
    @Slot(str, result=dict)
    def lapActions(self, path: str) -> dict:
        """Actions available for lap: recorded laps of track can be kept, noted, deleted & used as delta best"""
        recorded = path in {entry.file.path for entry in self.entries}
        return {"recorded": recorded, "kept": bool(self.lap_marks(path).get("kept")) if recorded else False}

    @Slot(str, result=bool)
    def isCompared(self, path: str) -> bool:
        """Lap shown & not reference lap (setup differences with reference lap)"""
        return path != self.reference_key and any(lap.key == path for lap in self.data.laps)

    @Slot(str, bool)
    def keepLap(self, path: str, keep: bool):
        """Kept lap is never removed by recorder (oldest laps over limit are)"""
        set_mark(path, kept=keep)
        self.marks_changed(path)

    def marks_changed(self, path: str = ""):
        """Lap kept or noted (any lap if no path): its row changed in place, list built again while searching (marks
        are searched)"""
        if path:
            self._marks.pop(os.path.dirname(path), None)
        else:
            self._marks.clear()
        if self._filter:
            self.fill_list()
            self.update_list_state(self.data.laps)
            return
        entries = {entry.file.path: entry for entry in self.entries}
        self.lap_model.update_rows(lambda row: self.mark_values(entries[row["path"]], row.get("vehicle", ""))
                                   if row["path"] in entries and path in ("", row["path"]) else {})

    @Slot(str)
    def editNote(self, path: str):
        """Free text note of lap, shown in lap list"""
        def saving(text: str) -> bool:
            set_mark(path, note=text)
            self.marks_changed(path)
            return True

        TextInputDialog(self._window, tr("Lap Note"), tr("Note for this lap (empty to remove):"), saving,
                        str(self.lap_marks(path).get("note", ""))).show()

    @Slot(str)
    def deleteLap(self, path: str):
        """Move recorded lap file to trash (undo restores it)"""
        self.deleteLaps([path])

    @Slot(list)
    def deleteLaps(self, paths: list):
        """Move recorded laps to trash, confirmation asked for several laps (undo restores them)"""
        recorded = {entry.file.path for entry in self.entries}
        paths = [str(path) for path in paths if str(path) in recorded]
        if not paths:
            return
        if len(paths) > 1:
            confirm = QMessageBox.question(
                self._window, tr("Delete Laps"), trm(f"Move {len(paths)} laps to trash?"),
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                defaultButton=QMessageBox.StandardButton.No)
            if confirm != QMessageBox.StandardButton.Yes:
                return
        if self._loader is not None:  # file read by background loading: deleted once loaded
            reading = [path for path in paths if path in self._loaded_paths]
            if reading and not self._pending_delete:  # undo restores this deletion (pending part added to it)
                self._undo = []
                self.undoChanged.emit()
            self._pending_delete.extend(path for path in reading if path not in self._pending_delete)
            paths = [path for path in paths if path not in self._loaded_paths]
        if paths:
            self.apply_delete(paths)

    def trash_folder(self) -> str:
        """New trash batch folder (deletion time)"""
        return os.path.join(self.folder, TRASH_FOLDER, time.strftime("%Y-%m-%d %H-%M-%S"))

    def apply_delete(self, paths: list[str], pending: bool = False) -> bool:
        """Move laps to trash, forget their caches, undo kept (pending: laps deleted while being read, restored with
        laps of same deletion), False if none moved"""
        batch = self.trash_folder()
        moved = []
        for path in paths:
            target = os.path.join(batch, os.path.basename(os.path.dirname(path)), os.path.basename(path))
            mark = dict(self.lap_marks(path))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(path, target)
            except OSError as error:
                logger.error("LAP VIEWER: unable to delete %s: %s", path, error)
                self.set_status(trm(f"Unable to delete lap: {error}"))
                continue
            remove_mark(path)
            remove_cached_lap(self.folder, path)
            with suppress(OSError):
                os.remove(os.path.join(self.limits_parts_folder(os.path.basename(os.path.dirname(path))),
                                       os.path.basename(path) + ".bin"))
            moved.append((path, target, mark, path in self.checked, path == self.reference_key))
        if not moved:
            return False
        gone = {item[0] for item in moved}
        for path in gone:
            self._marks.pop(os.path.dirname(path), None)
            self._lap_cache.pop(path, None)
        self.entries = [entry for entry in self.entries if entry.file.path not in gone]
        self.checked -= gone
        if self.reference_key in gone:
            self.reference_key = ""
        self._undo = self._undo + moved if pending else moved
        self.undoChanged.emit()
        self.set_status(trm(f"{len(self._undo)} lap(s) moved to trash"))
        self.fill_list()
        self.load_laps()
        return True

    @Property(str, notify=undoChanged)
    def undoText(self) -> str:
        """Undo button text, empty if nothing to restore"""
        return trm(f"Undo delete ({len(self._undo)})") if self._undo else ""

    @Slot()
    def undoDelete(self):
        """Restore last deleted laps from trash (marks, check state & reference too)"""
        if not self._undo:
            return
        restored = []
        for path, target, mark, checked, reference in self._undo:
            if os.path.exists(path):
                continue
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                os.replace(target, path)
            except OSError as error:
                logger.error("LAP VIEWER: unable to restore %s: %s", path, error)
                continue
            if mark.get("kept") or mark.get("note"):
                set_mark(path, kept=bool(mark.get("kept")), note=str(mark.get("note", "")))
            restored.append(path)
            if checked:
                self.checked.add(path)
            if reference:
                self.reference_key = path
            for folder in (os.path.dirname(target), os.path.dirname(os.path.dirname(target))):
                with suppress(OSError):  # trash track & batch folders removed once empty (never above)
                    os.rmdir(folder)
        self._undo = []
        self.undoChanged.emit()
        self._marks.clear()
        if self._track:
            laps = list_laps(self.folder, self._track)
            self.entries = [LapEntry(lap, info) for lap, info in zip(laps, self.track_infos(self._track, laps))]
        self.set_status(trm(f"{len(restored)} lap(s) restored"))
        self.fill_list()
        self.load_laps()

    @Slot(bool)
    def keepChecked(self, keep: bool):
        """Keep (or stop keeping) every checked recorded lap"""
        recorded = {entry.file.path for entry in self.entries}
        paths = [path for path in self.ordered_checked() if path in recorded]
        for path in paths:
            set_mark(path, kept=keep)
        if paths:
            self.marks_changed()

    @Slot()
    def deleteChecked(self):
        """Move every checked recorded lap to trash"""
        self.deleteLaps(self.ordered_checked())

    def session_paths(self, key: str) -> list[str]:
        """Laps listed in session (lap list order)"""
        return [row["path"] for row in self.lap_rows() if row["session"] == key]

    @Slot(str, str)
    def sessionAction(self, key: str, action: str):
        """Session header menu: show, hide, keep, delete laps listed in session"""
        paths = self.session_paths(key)
        if not paths:
            return
        recorded = {entry.file.path for entry in self.entries}
        if action == "show":
            self.checked.update(paths)
            self.load_laps()
        elif action == "hide":
            self.checked.difference_update(path for path in paths if path != self.reference_key)
            self.load_laps()
        elif action in ("keep", "unkeep"):
            for path in paths:
                if path in recorded:
                    set_mark(path, kept=action == "keep")
            self.marks_changed()
        elif action == "delete":
            self.deleteLaps(paths)

    # Added laps: other folders, MoTeC logs (see lap_export), imported laps library
    def add_external(self, lap_paths: list[str], reference_from: list[str] | None = None,
                     checked: list[str] | None = None):
        """Show laps from other folders (checked laps only if given, else every lap given, listed before or not),
        fastest of reference_from laps set as reference; laps of another driver's folder marked foreign, laps of shown
        track listed once (as track laps)

        Laps of one circuit only are ever shown: laps of shown circuit kept, others refused (told in status line).
        Laps given all driven on another circuit: viewer switches to it (see switch_circuit), laps of the circuit of
        the fastest reference_from lap (else first lap) kept.
        """
        listed = {path_key(entry.file.path): entry.file.path for entry in self.all_entries()}
        main = self.main_circuit() if self.entries or self.reference_key in self.checked else None
        new: dict[str, dict] = {}  # lap infos of laps not listed yet
        for lap_path in lap_paths:
            path = os.path.normpath(lap_path)
            if path_key(lap_path) not in listed and path not in new:
                new[path] = self.lap_info(path)
        kept = [path for path in new if main is None or not self.other_circuit(main, new[path], path)]
        listed_given = any(path_key(path) in listed for path in lap_paths)  # laps of shown circuit given again
        switching = main is not None and bool(new) and not kept and not listed_given
        if new and (switching or main is None):  # laps of one circuit kept: circuit of lead lap
            lead = self.lead_lap(list(new), reference_from, checked)
            kept = [path for path in new if not self.other_circuit((new[lead], lead), new[path], path)]
        rejected = {path: info for path, info in new.items() if path not in kept}
        added = []
        for path in kept:
            name = os.path.basename(path)
            self.external.append(LapEntry(
                LapFile(name, path, is_valid_name(name), lap_time_of(name)), new[path], external=True,
                foreign=is_foreign(path)))
            listed[path_key(path)] = path
            added.append(path)
        refused = ""
        if rejected:
            refused = trm(f"Laps from another circuit, not added: "
                          f"{', '.join(self.circuit_names(list(rejected), rejected))}")
            self.set_status(refused)
            lap_paths = [path for path in lap_paths if os.path.normpath(path) not in rejected]
            reference_from = [path for path in reference_from or () if os.path.normpath(path) not in rejected]
            checked = None if checked is None else [path for path in checked if os.path.normpath(path) not in rejected]
        shown = [listed.get(path_key(path), "") for path in (lap_paths if checked is None else checked)]
        shown = [path for path in shown if path and (switching or path not in self.checked)]
        reference = ""
        if reference_from:  # compare own laps with fastest imported lap
            fastest = min(reference_from, key=lambda path: lap_time_of(os.path.basename(path)) or float("inf"))
            reference = listed.get(path_key(fastest), os.path.normpath(fastest))
        if switching:
            self.switch_circuit(added, shown, reference or (shown or added)[0], refused)
            return
        self.checked.update(shown)
        if reference:
            self.reference_key = self._chosen_reference = reference
        if main is not None and added:  # imported laps checked against shown circuit once loaded
            self._added_batch = (added, [path for path in added if path in self.checked],
                                 reference if reference in added else "")
        if added or shown or reference_from:
            self.fill_list()
            self.load_laps()

    @staticmethod
    def lead_lap(paths: list[str], reference_from: list[str] | None, checked: list[str] | None) -> str:
        """Lap whose circuit is kept among added laps of several circuits: fastest reference_from lap, else first
        checked lap, else first lap"""
        fastest = sorted((os.path.normpath(path) for path in reference_from or ()
                          if os.path.normpath(path) in paths),
                         key=lambda path: lap_time_of(os.path.basename(path)) or float("inf"))
        first = [os.path.normpath(path) for path in checked or () if os.path.normpath(path) in paths]
        return (fastest or first or paths)[0]

    def track_folder_of(self, path: str) -> str:
        """Track folder of telemetry folder lap is in ("<track> - <class>"), empty if none (imported log, other
        folder)"""
        folder = os.path.dirname(path)
        name = os.path.basename(folder)
        if not name or name.startswith(".") or path_key(os.path.dirname(folder)) != path_key(self.folder):
            return ""
        if name not in self._tracks and os.path.isdir(folder):  # recorded since list was read
            self._tracks = list_tracks(self.folder)
        return name if name in self._tracks else ""

    def switch_circuit(self, paths: list[str], shown: list[str], reference: str, refused: str = ""):
        """Laps of another circuit opened (file, library, MoTeC log, folder): viewer shows that circuit instead,
        laps of former circuit no longer listed nor compared. Track folder of reference lap shown if it is one (its
        laps listed, notes, pins, track limits, official circuit), else opened laps alone; track picker goes back."""
        keep = set(paths)
        self.external = [entry for entry in self.external if entry.file.path in keep]
        infos = {entry.file.path: entry.info for entry in self.external}
        self.checked = (set(shown) | {reference}) & keep if reference else set(shown) & keep
        self.reference_key = self._chosen_reference = reference
        self._added_batch = self._pending_switch = None
        track = self.track_folder_of(reference)
        self._switch_to = (track, set(self.checked), reference)
        plural = "s" if len(paths) > 1 else ""
        message = trm(f"Showing {', '.join(self.circuit_names([reference], infos))}: "
                      f"lap{plural} from another circuit")
        self.set_status(f"{message} · {refused}" if refused else message)
        self.load_track(track)

    @Slot()
    def openLibrary(self):
        from ..lap_library import LapLibrary

        LapLibrary(self._window, self.folder, self.add_from_library, self.library_changed).show()

    def add_from_library(self, paths: list[str]):
        """Laps picked in library shown & checked, fastest one as reference"""
        self.add_external(paths, paths)

    def library_changed(self, moved: dict[str, str]):
        """Imported laps renamed (new path) or deleted (empty path) in library"""
        moved = {os.path.normpath(old): os.path.normpath(new) if new else "" for old, new in moved.items()}
        if not any(entry.file.path in moved for entry in self.external):
            return
        self.checked = {moved.get(path, path) for path in self.checked} - {""}
        external = []
        for entry in self.external:
            path = moved.get(entry.file.path, entry.file.path)
            if path:
                external.append(entry._replace(file=entry.file._replace(path=path)))
            self._lap_cache.pop(entry.file.path, None)
        self.external = external
        if self.reference_key in moved:
            self.reference_key = moved[self.reference_key]
        self._chosen_reference = moved.get(self._chosen_reference, self._chosen_reference)
        self.fill_list()
        self.load_laps()

    # Lap loading
    def read_lap(self, path: str) -> LapData | None:
        if not path:
            return None
        if path in self._lap_cache:
            self._lap_cache[path] = self._lap_cache.pop(path)  # most recently used last
            return self._lap_cache[path]
        try:
            lap = self.load_lap_file(path)
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to load %s: %s", path, error)
            self.set_status(trm(f"Unable to load lap: {error}"))
            lap = None
        except Exception as error:  # unexpected: lap flagged unreadable, page goes on
            logger.exception("LAP VIEWER: unable to load %s", path)
            self.set_status(trm(f"Unable to load lap: {error}"))
            lap = None
        self.store_lap(path, lap)
        return lap

    def store_lap(self, path: str, lap: LapData | None):
        """Keep loaded lap, oldest laps forgotten over cache size (a lap takes several MB in memory)"""
        self._lap_cache[path] = lap
        try:
            self._cache_mtime[path] = os.path.getmtime(path)
        except OSError:
            self._cache_mtime.pop(path, None)
        limit = max(lap_viewer.LAP_CACHE_SIZE, len(self.checked) + 2)  # shown laps, main & anchor laps
        while len(self._lap_cache) > limit:
            oldest = next(iter(self._lap_cache))
            self._lap_cache.pop(oldest)
            self._cache_mtime.pop(oldest, None)

    def load_in_background(self, paths: list[str]):
        """Read laps in a thread, charts updated once all are loaded (page stays responsive), shape checks &
        alignments of laps about to be shown measured there too (see prepare_laps)"""
        if self._loader is not None:
            return  # current selection shown once loaded (check_background_load)
        plan, self._load_plan = self._load_plan, None
        results: dict[str, LapData | None] = {}
        prepared: list[tuple[dict, dict]] = []
        cached = {path: self._lap_cache.get(path) for path in (plan[0] + list(plan[1:3]) if plan else ())}
        checks, aligned = dict(self._shape_checks), self.data.aligned_snapshot()

        def loading():
            for path in paths:
                try:
                    results[path] = self.load_lap_file(path)
                except (OSError, ValueError) as error:
                    logger.error("LAP VIEWER: unable to load %s: %s", path, error)
                    results[path] = None
                except Exception:  # any other failure: lap flagged unreadable, never loaded again in a loop
                    logger.exception("LAP VIEWER: unable to load %s", path)
                    results[path] = None
            if plan is not None:
                try:
                    prepared.append(self.prepare_laps(plan, {**cached, **results}, checks, aligned))
                except Exception:  # measured again when shown
                    logger.exception("LAP VIEWER: unable to compare laps")

        self._prepared_laps = prepared
        self._preparing = plan[:4] if plan is not None else None
        self._loaded = results
        self._loaded_paths = set(paths)
        self._load_total = len(paths)
        self._load_message = self._status
        self._loader = threading.Thread(target=loading, daemon=True, name="Lap viewer loading")
        self._loader.start()
        self._load_timer.start()
        if paths:
            self.set_status(trm(f"Loading {len(paths)} lap{'s' if len(paths) > 1 else ''}..."), False)
        else:  # laps loaded: imported laps compared in background
            self.set_status(tr("Reading laps..."), False)

    @Slot()
    def check_background_load(self):
        """Background loading progress, once finished: laps kept, charts updated"""
        if self._loader is None:
            return
        if self._loader.is_alive():
            if self._load_total > 1:
                self.set_status(trm(f"Loading laps: {len(self._loaded)}/{self._load_total}"), False)
            return
        self._load_timer.stop()
        self._loader = None
        for path in self._loaded_paths - self._loaded.keys():  # loading stopped before it: unreadable
            self._loaded[path] = None
        failed = [path for path, lap in self._loaded.items() if lap is None]
        for path, lap in self._loaded.items():
            self.store_lap(path, lap)
        self._failed.update(failed)  # not read again by load_laps below (read again once checked again, refresh)
        self._loaded = {}
        prepared, self._prepared_laps = self._prepared_laps, []
        for checks, aligned in prepared:  # used by load_laps below if laps are still the same
            self._prepared_checks.update(checks)  # laps found on another circuit told by drop_other_shapes
            self.data.keep_aligned(aligned)
            self._prepared = self._preparing
        if failed:
            self.set_status(trm(f"Unable to load lap: {html.escape(os.path.basename(failed[0]))}"))
        else:  # message shown before loading (new lap) shown again
            self.set_status(self._load_message)
        if self._pending_delete:  # deleted while loading: laps list & charts updated by deletion if any lap moved
            paths, self._pending_delete = self._pending_delete, []
            if self.apply_delete(paths, pending=True):
                return
        self.load_laps()

    def is_loading(self) -> bool:
        """Laps loading, importing or exporting in background"""
        return self._loader is not None or self._exports > 0 or self._imports > 0

    def assign_colors(self, ordered: list[str]) -> dict[str, int]:
        """Color index of each shown lap: kept while lap stays shown, lowest free index for new laps"""
        slots = {path: slot for path, slot in self._color_slots.items() if path in ordered}
        used = set(slots.values())
        for path in ordered:
            if path not in slots:
                slot = next(index for index in range(len(ordered) + len(used) + 1) if index not in used)
                slots[path] = slot
                used.add(slot)
        self._color_slots = slots
        return slots

    def load_laps(self):
        paths = self.ordered_checked()
        track_paths = {entry.file.path for entry in self.entries}
        if paths and self.reference_key not in paths:  # lap of current track first (added laps listed on top)
            self.reference_key = next((path for path in paths if path in track_paths), paths[0])
        paths = self.drop_other_circuits(paths)
        if paths and self.reference_key not in paths:  # reference lap of another circuit than shown track
            self.reference_key = next((path for path in paths if path in track_paths), paths[0])
        ordered = sorted(paths, key=lambda path: path != self.reference_key)  # reference first
        for path in ordered:  # unreadable lap checked again: read again (file may be readable now, antivirus lock)
            if path not in self._failed and path in self._lap_cache and self._lap_cache[path] is None:
                del self._lap_cache[path]
        main_path = self.main_circuit()[1]
        anchor_path = self.track_anchor(ordered)
        needed = [*ordered, *(path for path in (main_path, anchor_path) if path and path not in ordered)]
        missing = [path for path in needed if path not in self._lap_cache]
        prepared = self._prepared == (ordered, main_path, anchor_path, self.reference_key)  # else picked meanwhile
        self._prepared = None
        if (self._loader is not None or len(missing) >= lap_viewer.BACKGROUND_LOAD_COUNT
                or (not prepared and self.needs_preparing(ordered, main_path, anchor_path))):
            self.update_list_state(self.data.laps)
            stamps = {path: self.shape_stamps(main_path, path) for path in ordered}
            self._load_plan = (ordered, main_path, anchor_path, self.reference_key, stamps)
            self.load_in_background(missing)
            return
        entries = {entry.file.path: entry for entry in self.all_entries()}
        loaded = self.drop_other_shapes([(path, self.read_lap(path)) for path in ordered])
        if self._pending_switch is not None:  # laps just added all driven on another circuit: shown instead
            switch, self._pending_switch = self._pending_switch, None
            self.switch_circuit(*switch)
            return
        paths = [path for path in paths if path in self.checked]
        self._failed = {path for path, lap_data in loaded if lap_data is None}
        if self.reference_key in self._failed:  # first lap read is reference (star, compared laps, exports, saved)
            self.reference_key = next((path for path, lap_data in loaded if lap_data is not None), self.reference_key)
        self.save_selection(paths)
        slots = self.assign_colors([path for path, lap_data in loaded if lap_data is not None])
        laps = [
            PlotLap(path, self.entry_label(entries.get(path), path), lap_data, lap_color(slots[path]),
                    self.is_clean(entries.get(path), path, lap_data))
            for path, lap_data in loaded if lap_data is not None
        ]
        self.build_labels(laps)
        anchor_data = self.read_lap(anchor_path) if anchor_path and anchor_path in self._lap_cache else None
        self.data.set_laps(laps, self.reference_key, (anchor_path, anchor_data) if anchor_data is not None else None)
        self.apply_track_sectors()
        self.update_list_state(laps)
        self._warning = self.laps_warning(laps)
        self.rebuild_chart()
        if self._restore_view is not None:
            self.viewRestored.emit(*self._restore_view)
            self._restore_view = None

    def drop_other_circuits(self, paths: list[str]) -> list[str]:
        """Checked laps driven on another circuit than main lap unchecked (told in status line): never drawn
        nor compared with it (added lap of another track, laps kept checked when track changes)"""
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        main = self.main_circuit()
        others = [path for path in paths if self.other_circuit(main, infos.get(path, {}), path)]
        if not others:
            return paths
        self.checked.difference_update(others)
        self.set_status(trm(f"Laps from another circuit, not compared with reference lap: "
                            f"{', '.join(self.circuit_names(others, infos))}"))
        return [path for path in paths if path not in others]

    def main_circuit(self) -> tuple[dict, str]:
        """Lap info & path of main lap, every shown lap must be driven on its circuit: reference lap if a lap of shown
        track, else newest lap of track, else reference lap (only added laps)"""
        entries = {entry.file.path: entry for entry in self.entries}
        entry = entries.get(self.reference_key) or (self.entries[0] if self.entries else None)
        if entry is not None:
            return entry.info, entry.file.path
        infos = {entry.file.path: entry.info for entry in self.external}
        key = self.reference_key
        if self._added_batch is not None and key in self._added_batch[0]:  # laps just added not checked yet:
            # shown lap added before is main lap
            key = next((entry.file.path for entry in self.external
                        if entry.file.path in self.checked and entry.file.path not in self._added_batch[0]), key)
        return infos.get(key, {}), key

    def other_circuit(self, main: tuple[dict, str], info: dict, path: str) -> bool:
        """Whether lap (lap info & path) was driven on another circuit than main lap: game track name & length (see
        same_circuit), else track of track folder ("<track> - <class>") of laps without lap info, imported lap found
        on another circuit from its telemetry once loaded (see drop_other_shapes)"""
        main_info, main_path = main
        if path == main_path:
            return False
        if not same_circuit(LapData("", {}, main_info), LapData("", {}, info)):
            return True
        names = [circuit_name(main_info, main_path), circuit_name(info, path)]
        if all(names) and names[0].casefold() != names[1].casefold():
            return True
        checked = self._shape_checks.get((main_path, path))
        return checked is not None and checked[1] is False and checked[0] == self.shape_stamps(main_path, path)

    def lap_stamp(self, path: str) -> float:
        """File time of lap (loaded lap: time of file read), -1 if no file"""
        stamp = self._cache_mtime.get(path)
        if stamp is not None:
            return stamp
        try:
            return os.path.getmtime(path)
        except OSError:
            return -1.0

    def shape_stamps(self, main_path: str, path: str) -> tuple[float, float]:
        """File stamps of main lap & lap a shape check is valid for (see drop_other_shapes)"""
        return self.lap_stamp(main_path), self.lap_stamp(path)

    @staticmethod
    def shape_check(main: LapData, lap_data: LapData, path: str) -> bool | None:
        """Whether lap was driven on circuit of main lap from telemetry (see same_imported_circuit), None if unknown
        or if its telemetry cannot be compared (damaged log: logged, lap kept)"""
        if is_recorded(main) and is_recorded(lap_data):
            return None
        try:
            return same_imported_circuit(main, lap_data)
        except Exception:  # unexpected values in an imported log: lap kept, page never stuck
            logger.exception("LAP VIEWER: unable to compare circuit of %s", path)
            return None

    @classmethod
    def prepare_laps(cls, plan: tuple, laps: dict[str, LapData | None],
                     checks: dict[tuple[str, str], tuple[tuple[float, float], bool | None]],
                     aligned: dict) -> tuple[dict, dict]:
        """Shape checks & alignments of laps about to be shown measured in background thread (slow on a long track:
        page stays responsive), same as drop_other_shapes & TraceData.set_laps then find them done: new shape checks
        & aligned laps (see align_laps)

        plan: shown lap paths (reference first), main lap path, anchor lap path, reference lap path, file stamps of
        each shown lap shape check (see shape_stamps). Never touches page state (thread).
        """
        ordered, main_path, anchor_path, reference_key, stamps = plan
        main = laps.get(main_path)
        found = {}
        others = set()
        for path in ordered:
            lap_data = laps.get(path)
            if main is None or lap_data is None or path == main_path:
                continue
            checked = checks.get((main_path, path))
            if checked is None or checked[0] != stamps[path]:
                checked = found[(main_path, path)] = (stamps[path], cls.shape_check(main, lap_data, path))
            if checked[1] is False:
                others.add(path)
        shown = [(path, lap_data) for path in ordered if path not in others
                 for lap_data in (laps.get(path),) if lap_data is not None]
        anchor_data = laps.get(anchor_path) if anchor_path else None
        anchor = (anchor_path, anchor_data) if anchor_data is not None else None
        return found, align_laps(shown, reference_key, anchor, aligned)[0]

    def needs_preparing(self, ordered: list[str], main_path: str, anchor_path: str) -> bool:
        """Whether showing laps (all loaded) measures shape checks or lap offsets of imported laps long enough to
        freeze the page (long track, many laps): done in background first (see prepare_laps)"""
        cache = self._lap_cache
        main = cache.get(main_path)
        shown = []
        work = 0
        for path in ordered:
            lap_data = cache.get(path)
            if lap_data is None:
                continue
            if main is not None and path != main_path and not (is_recorded(main) and is_recorded(lap_data)):
                checked = self._shape_checks.get((main_path, path))
                if checked is None or checked[0] != self.shape_stamps(main_path, path):
                    work += len(lap_data)
                elif checked[1] is False:
                    continue
            shown.append((path, lap_data))
        anchor_data = cache.get(anchor_path) if anchor_path else None
        anchor = (anchor_path, anchor_data) if anchor_data is not None else None
        work += self.data.alignment_work(shown, self.reference_key, anchor)
        return work >= lap_viewer.BACKGROUND_PREPARE_SAMPLES

    def track_anchor(self, paths: list[str]) -> str:
        """Lap recorded by the app an imported reference lap is aligned on when no shown lap was recorded by the app
        (see TraceData.aligned_laps): main lap, else newest lap of track recorded by the app, empty if not needed"""
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        if "combo" in infos.get(self.reference_key, {"combo": ""}) or any(
                "combo" in infos.get(path, {}) for path in paths):
            return ""
        main_path = self.main_circuit()[1]
        candidates = [main_path, *(entry.file.path for entry in self.entries)]
        return next((path for path in candidates if path != self.reference_key and path not in self._failed
                     and "combo" in infos.get(path, {})), "")

    def drop_other_shapes(self, loaded: list[tuple[str, LapData | None]]) -> list[tuple[str, LapData | None]]:
        """Loaded laps without imported laps found driven on another circuit than main lap from their telemetry
        (driven line, else speed trace, see same_imported_circuit): added laps no longer listed, laps of track
        unchecked (told in status line like laps of another circuit)"""
        main_path = self.main_circuit()[1]
        batch, self._added_batch = self._added_batch, None
        main = dict(loaded).get(main_path) or self.read_lap(main_path)
        if main is None:
            return loaded
        checks = {key: value for key, value in self._shape_checks.items() if key[0] == main_path}
        prepared, self._prepared_checks = self._prepared_checks, {}
        others = []
        for path, lap_data in loaded:
            if lap_data is None or path == main_path:
                continue
            stamps = self.shape_stamps(main_path, path)
            found = checks.get((main_path, path))
            if found is None or found[0] != stamps:  # measured in background unless few samples (see prepare_laps)
                found = prepared.get((main_path, path))
                if found is None or found[0] != stamps:
                    found = (stamps, self.shape_check(main, lap_data, path))
                checks[(main_path, path)] = found
            if found[1] is False:
                others.append(path)
        self._shape_checks = checks
        if not others:
            return loaded
        if batch is not None:  # every lap just added & shown driven on another circuit: viewer switches to it
            opened = {path for path, lap_data in loaded if path in batch[1] and lap_data is not None}
            if opened and opened <= set(others):
                lead = batch[2] or next(path for path in batch[1] if path in opened)
                self._pending_switch = (batch[0], batch[1], lead)
                return loaded
        infos = {entry.file.path: entry.info for entry in self.all_entries()}
        names = ", ".join(self.circuit_names(others, infos))
        self.checked.difference_update(others)
        added = {entry.file.path for entry in self.external} & set(others)
        if added:  # never listed, like laps of another circuit added (see add_external)
            self.external = [entry for entry in self.external if entry.file.path not in added]
            self.fill_list()
            self.set_status(trm(f"Laps from another circuit, not added: {names}"))
        else:
            self.set_status(trm(f"Laps from another circuit, not compared with reference lap: {names}"))
        kept = [(path, lap_data) for path, lap_data in loaded if path not in others]
        if self.reference_key in others:
            self.reference_key = next((path for path, lap_data in kept if lap_data is not None), main_path)
        return kept

    @staticmethod
    def circuit_names(paths: list[str], infos: dict[str, dict]) -> list[str]:
        """Track names of laps (lap info, else track folder), each once"""
        return sorted({str(infos.get(path, {}).get("track") or track_of_folder(path)
                           or os.path.basename(os.path.dirname(path))) for path in paths})

    @staticmethod
    def laps_warning(laps: list[PlotLap]) -> str:
        """Shown laps not alike: driven with different vehicles"""
        vehicles = sorted({str(lap.data.meta.get("vehicle")) for lap in laps if lap.data.meta.get("vehicle")})
        return trm(f"Laps from different vehicles: {', '.join(vehicles)}") if len(vehicles) > 1 else ""

    @staticmethod
    def is_clean(entry: LapEntry | None, path: str, lap: LapData) -> bool:
        """Valid lap, not out or in lap: may count in ideal lap & mini-sectors"""
        info = entry.info if entry is not None else lap.meta
        return is_valid_name(os.path.basename(path)) and info.get("kind", "lap") == "lap"

    @staticmethod
    def entry_label(entry: LapEntry | None, path: str) -> str:
        """Lap name in legend: "Lap 12 · 1:11.525 · Race 03/10", or "log: Lap 3 · 2:18.200" """
        label = lap_label(os.path.basename(path))
        if entry is None or entry.external:
            return f"{os.path.basename(os.path.dirname(path))}: {label}"
        session = str(entry.info.get("session", ""))
        timestamp = lap_timestamp_of(entry.file.filename)
        date = time.strftime("%d/%m", time.localtime(timestamp)) if timestamp > 0 else ""
        where = " ".join(filter(None, [tr(session) if session else "", date]))
        return f"{label} · {where}" if where else label

    def update_list_state(self, laps: list[PlotLap]):
        """Check marks, lap colors, reference, errors & other circuit hints in lap list (in place: list keeps scroll
        position)"""
        colors = {lap.key: lap.color.name() for lap in laps}
        hint = self.circuit_hints()  # reference may have changed
        self.lap_model.update_rows(lambda row: {
            "checked": row["path"] in self.checked,
            "reference": bool(row["path"]) and row["path"] == self.reference_key,
            "color": colors.get(row["path"], ""),
            "error": row["path"] in self._failed and row["path"] in self.checked,
            **hint(row),
        })

    # Memory release while page is in background
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

    @Slot()
    def release_laps(self):
        """Free memory of loaded laps (several MB each) while page is hidden, see page_shown"""
        if self._window.isVisible() or self._released:
            return
        if self._loader is not None:  # released once loading is done
            self._release_timer.start()
            return
        self._released_view = self._chart_view
        self._lap_cache.clear()
        self._cache_mtime.clear()
        self.data.set_laps([])
        self.clear_lap_caches()
        self.rebuild_chart()
        self._released = True
        logger.info("LAP VIEWER: loaded laps released while hidden")

    def clear_lap_caches(self):
        """Forget results kept per loaded lap (they keep lap data in memory)"""
        for cache in (self._line_cache, self._lap_corners, self._lap_offsets, self._events, self._yaw, self._grids,
                      self._zones, self._placements, self._trackouts, self._slips, self._g_laps, self._g_drawn,
                      self._resampled, self._normals, self._turned, self._lap_shapes):
            cache.clear()
        self._corner_key = ()
        self._corner_rows = []
        self._ideal = None
        self._color_lines = ()
        self._colored_steps = {}
        self._line_offsets = {}
        self._official_key = None
        self._edges_cache = ()
        self._edge_normals = ()
        self._g_points = []
        self._shape_checks.clear()

    @Slot(float, float)
    def setChartView(self, start: float, end: float):
        """Chart zoom (kept to show same part after laps are reloaded), G circle zoomed part follows it"""
        self._chart_view = (start, end)
        if self._gcircle and self._side_tab == 1:  # G circle shown: zoomed part follows charts
            self._zoom_timer.start()

    def zoom_distances(self) -> tuple[float, float]:
        """Reference distances of charts zoomed part, (0, 0) if whole lap shown"""
        start, end = self._chart_view
        if end <= start or end - start >= self.data.max_x() - 1:
            return 0.0, 0.0
        return self.data.distance_at_x(start), self.data.distance_at_x(end)

    @Slot()
    def update_gcircle_zoom(self):
        if self._gcircle:
            self.build_gcircle_zoom()
            self.bump_revision()

    # Page layout & options
    @Slot(int)
    def setSideTab(self, index: int):
        index = min(max(index, 0), 5)
        if index != self._side_tab:
            self._side_tab = index
            save_viewer_setting(self.folder, side_tab=index)
            self.optionsChanged.emit()
        if index == 1 and self._gcircle_stale:  # laps changed while G circle was hidden: built now
            self.build_gcircle()
            self.bump_revision()
            self.gCircleChanged.emit()
        elif index == 1:  # G circle: zoomed part of charts (not followed while hidden)
            self.update_gcircle_zoom()
        if index == 4:  # session tab: values read from lap files
            self.start_session_job()

    @Slot("QVariant")
    def setLayoutState(self, state):
        """Split view sizes (SplitView.saveState), restored next time"""
        data = bytes(state.data()) if isinstance(state, QByteArray) else bytes(state or b"")
        text = base64.b64encode(data).decode("ascii") if data else ""
        if text != self._layout:
            self._layout = text
            save_viewer_setting(self.folder, layout=text)

    @Slot(int)
    def setSmoothing(self, level: int):
        level = min(max(level, 0), len(SMOOTHING_LEVELS) - 1)
        if level != self._smoothing:
            self._smoothing = level
            self.data.set_smoothing(SMOOTHING_LEVELS[level])
            save_viewer_setting(self.folder, smoothing=level)
            self.optionsChanged.emit()
            self.channels_updated(save=False)

    @Slot(int)
    def setDeltaWindow(self, meters: int):
        if meters in DELTA_RATE_WINDOWS and meters != self.data.delta_window:
            self.data.set_delta_window(float(meters))
            save_viewer_setting(self.folder, delta_window=meters)
            self.optionsChanged.emit()
            self.channels_updated(save=False)
            if self._map and self._map_mode == "gain":
                self.build_colored_line(self._map_view[2])
                self.bump_revision()

    @Slot(bool)
    def setEnvelope(self, enabled: bool):
        if enabled != self._envelope:
            self._envelope = enabled
            save_viewer_setting(self.folder, envelope=enabled)
            self.optionsChanged.emit()
            self.channels_updated(save=False)

    @Property(bool, notify=optionsChanged)
    def idealDelta(self) -> bool:
        """Delta against ideal lap (fastest clean shown lap in each mini-sector) instead of reference lap"""
        return self.data.ideal_mode

    @Slot(bool)
    def setIdealDelta(self, enabled: bool):
        if enabled != self.data.ideal_mode:
            self.data.set_ideal_mode(enabled)
            save_viewer_setting(self.folder, ideal_delta=enabled)
            self.optionsChanged.emit()
            self.channels_updated(save=False)

    @Property(str, notify=chartChanged)
    def idealTime(self) -> str:
        """Ideal lap time of shown laps (delta against ideal lap), empty if unknown"""
        seconds = self.data.ideal_time() if self.data.ideal_mode else 0.0
        return format_laptime(seconds) if seconds > 0 else ""

    @Slot(bool)
    def setGEnvelope(self, enabled: bool):
        if enabled != self._g_envelope:
            self._g_envelope = enabled
            save_viewer_setting(self.folder, g_envelope=enabled)
            self.optionsChanged.emit()

    @Slot(str, float)
    def setPanelWeight(self, column: str, weight: float):
        """Panel height set by dragging its lower edge"""
        if column in CHANNEL_MAP:
            self._weights[column] = round(min(max(weight, 0.2), 6.0), 2)
            save_viewer_setting(self.folder, panel_weights=self._weights)
            for panel in self._panels:
                if panel["column"] == column:
                    panel["weight"] = self._weights[column]
            self._panels = [dict(panel) for panel in self._panels]
            self.panelsChanged.emit()

    @Slot()
    def resetPanelWeights(self):
        self._weights = {}
        save_viewer_setting(self.folder, panel_weights={})
        self.channels_updated(save=False)

    # Charts
    def series_key(self, lap: PlotLap, channel: Channel) -> str:
        signature = self.data.signature(channel, lap)  # only rescaled laps drawn again (reference lap changed)
        return f"{self.prefix}{lap.key}|{channel.column}|{signature}{self.shift_key(lap.key, channel)}"

    def rebuild_chart(self):
        """Vertices & properties of every view from displayed laps"""
        self.update_base()
        self.build_official()
        self.build_corners()
        self.update_alignment()  # laps aligned on a braking point: shifted before charts are built
        entries = {entry.file.path: entry for entry in self.all_entries()}
        self._legend = [
            {"key": lap.key, "label": self.short_label(lap.key), "full": lap.label,
             "color": lap.color.name(), "reference": lap is self.data.reference, "clean": lap.clean,
             "tip": self.entry_conditions(entries[lap.key]) if lap.key in entries
             else self.entry_conditions(LapEntry(LapFile("", lap.key, True), lap.data.meta)),
             "excluded": self.excluded_text(lap), "offset": self.legend_offset(lap.key)}
            for lap in self.data.laps
        ]
        self.legend_model.sync(self._legend)
        self.build_panels()
        self.build_overview()
        self.build_map()
        self.build_gcircle()  # only if its tab is shown, else once shown
        self.drop_unused_vertices()
        self.bump_revision()
        self.chartChanged.emit()
        self.mapChanged.emit()
        self.channelsChanged.emit()  # channels available in shown laps
        self.pinChanged.emit()
        if not self._gcircle_stale:
            self.gCircleChanged.emit()

    @staticmethod
    def excluded_text(lap: PlotLap) -> str:
        """Why lap never counts in ideal lap & mini-sectors (legend tooltip), empty if it may"""
        if not lap.clean:
            return tr("Not counted in ideal lap & mini-sectors (invalid, out or in lap)")
        return ""

    def drop_unused_vertices(self):
        """Forget vertices of laps no longer shown & of former settings (others kept: not built again)"""
        keep = {series["key"] for panel in self._panels for series in panel["series"]}
        keep.update(key for panel in self._panels for series in panel["series"] for _, key in series["lods"])
        keep.update(self._xy_keys)
        keep.update(panel["envelope"] for panel in self._panels if panel["envelope"])
        if self._overview:
            keep.add(self._overview["key"])
        if self._map:
            keep.update((self._map["road"], self._map["edge"], self._map["colored"], self._map["marks"],
                         self._map["arrowsKey"], self._map["rangeKey"], self._map["selectedKey"], self._map["pit"],
                         self._map["mini"], self._map["spread"]))
            for line in self._map["lines"]:
                keep.update((line["key"], line["highlight"], line["trail"]))
            for item in self._map["markers"]:
                keep.update((item["brakeZones"], item["throttleZones"]))
                for shape in item["shapes"]:
                    keep.update((shape["fill"], shape["outline"]))
        for item in self._gcircle.get("dots", []):
            keep.update((item["key"], item["zoom"], item["envelope"]))
        VertexStore.retain(self.prefix, keep)

    def build_panels(self):
        panels = []
        laps = self.data.laps
        for column in self.visible:
            channel = CHANNEL_MAP[column]
            low, high = self.data.value_range(channel)
            parts = channel.parts or (column,)
            single = len(laps) == 1
            series = []
            for lap in laps:
                for index, part in enumerate(parts):
                    part_channel = CHANNEL_MAP[part]
                    key = self.series_key(lap, part_channel)
                    xs, ys = self.data.series(part_channel, lap)
                    stepped = part in INTEGER_CHANNELS
                    if not VertexStore.has(key):
                        VertexStore.set(key, step_strip(xs, ys) if stepped else line_strip(xs, ys))
                    lods = []  # reduced copies (buckets over whole lap, key): same peaks, far fewer vertices
                    for buckets in LOD_LEVELS:
                        if stepped or len(xs) < buckets * LOD_MIN_RATIO:
                            break
                        lod = f"{key}|lod{buckets}"
                        if not VertexStore.has(lod):
                            points = decimate_minmax(xs, ys, xs[0], xs[-1], buckets)
                            VertexStore.set(lod, line_strip([p[0] for p in points], [p[1] for p in points]))
                        lods.append([buckets, lod])
                    if not channel.parts:
                        color = lap.color.name()
                    elif single:
                        color = part_color(part)
                    else:
                        color = shade(lap.color, index, len(parts)).name()
                    series.append({"key": key, "lods": lods, "color": color, "lap": lap.key})
            envelope = ""
            if self._envelope and not channel.parts:
                shown = hash((tuple(lap.key for lap in laps), tuple(sorted(self.data.offsets.items()))))  # laps, offsets
                envelope = f"{self.prefix}envelope|{column}|{self.data.signature(channel)}|{len(laps)}|{shown:x}"
                if not VertexStore.has(envelope):
                    VertexStore.set(envelope, range_band(*self.data.envelope(channel)))
                band_vertices = VertexStore.get(envelope)
                if band_vertices is None or band_vertices.vertex_count == 0:
                    envelope = ""
            span = high - low
            reference = self.data.reference
            available = self.data.available(channel) if laps else True
            note = ""
            if not available:
                if column not in DELTA_CHANNELS:
                    note = tr("Not recorded in shown laps")
                elif self.data.ideal_mode:
                    note = tr("Ideal lap needs 2 laps or more with lap times")
                else:
                    note = tr("Check a second lap to compare")
            panels.append({
                "ticks": self.axis_ticks(channel, low, high),  # value grid between range limits
                "column": column, "title": channel_title(channel), "unit": self.data.unit_of(channel),
                "weight": self._weights.get(column, channel.weight), "low": low, "high": high,
                "lowText": format_axis_value(channel, low, span), "highText": format_axis_value(channel, high, span),
                "zero": low < 0 < high, "percent": channel.fixed_range in PERCENT_RANGES, "series": series,
                "available": available, "note": note, "envelope": envelope, "autoscale": column in self._autoscale,
                "parts": [
                    {"label": part_label(part),
                     "color": part_color(part) if single or reference is None
                     else shade(reference.color, index, len(parts)).name()}
                    for index, part in enumerate(channel.parts)
                ],
            })
        self._panels = panels
        self.sync_panel_models()

    def sync_panel_models(self):
        """Panel & series models follow panels list (changed rows only)"""
        rows = []
        shown = set()
        for panel in self._panels:
            column = panel["column"]
            shown.add(column)
            series = self.series_models.get(column)
            if series is None:
                series = self.series_models[column] = DictListModel(SERIES_ROLES, self)
            series.sync([{"key": item["key"], "lods": item["lods"], "color": item["color"], "lap": item["lap"]}
                         for item in panel["series"]])
            rows.append({"column": column, "low": panel["low"], "high": panel["high"], "ticks": panel["ticks"],
                         "envelope": panel["envelope"], "note": panel["note"], "available": panel["available"],
                         "seriesModel": series})
        self.panel_model.sync(rows, "column")
        for column in [column for column in self.series_models if column not in shown]:
            self.series_models.pop(column).deleteLater()

    def build_overview(self):
        reference = self.data.reference
        if reference is None or "speed_kph" not in reference.data.columns:
            self._overview = {}
            return
        channel = CHANNEL_MAP["speed_kph"]
        key = self.series_key(reference, channel) + "|overview"
        xs, ys = self.data.series(channel, reference)
        if not VertexStore.has(key):
            VertexStore.set(key, line_strip(xs, ys))
        low, high = min(ys, default=0.0), max(ys, default=1.0)
        self._overview = {"key": key, "low": low, "high": high if high > low else low + 1}

    @Slot(str, bool)
    def setChannelVisible(self, column: str, visible: bool):
        if visible and column not in self.visible:
            self.visible.append(column)  # added at bottom, can be moved by dragging its name
        elif not visible and column in self.visible:
            self.visible.remove(column)
        self.channels_updated()

    @Slot(int, int)
    def moveChannel(self, source: int, target: int):
        if source != target and 0 <= source < len(self.visible) and 0 <= target < len(self.visible):
            self.visible.insert(target, self.visible.pop(source))
            self.channels_updated()

    @Slot()
    def resetChannels(self):
        self.visible = list(DEFAULT_CHANNELS)
        self.channels_updated()

    @Slot(str)
    def applyPreset(self, name: str):
        """Channel menu preset: Pedals, Tyres, Brakes, Suspension..."""
        if name in CHANNEL_PRESETS:
            self.visible = list(CHANNEL_PRESETS[name])
            self.channels_updated()

    def channels_updated(self, save: bool = True):
        if save:
            save_viewer_setting(self.folder, channels=self.visible)
        self.build_panels()
        self.build_overview()
        self.drop_unused_vertices()  # series of former settings (smoothing, delta window...) forgotten
        self.bump_revision()
        self.channelsChanged.emit()
        self.chartChanged.emit()

    @Slot(bool)
    def setTimeAxis(self, enabled: bool):
        """Lap time or distance horizontal axis, same part of lap kept in view"""
        if enabled == self.data.time_axis:
            return
        start, end = self._chart_view
        zoomed = end > start and end - start < self.data.max_x() - 1
        if zoomed:
            start, end = self.data.distance_at_x(start), self.data.distance_at_x(end)
        self.data.set_time_axis(enabled)
        save_viewer_setting(self.folder, time_axis=enabled)
        self.build_panels()
        self.build_overview()
        self.build_corner_marks()
        self.drop_unused_vertices()  # series along former axis forgotten
        self.bump_revision()
        self.chartChanged.emit()
        self.pinChanged.emit()  # same place, other axis position
        if zoomed:
            self.viewRestored.emit(self.data.x_at_distance(start), self.data.x_at_distance(end))

    @Slot(float, result=float)
    def distanceAt(self, x: float) -> float:
        """Reference lap distance at axis position"""
        return self.data.distance_at_x(x)

    @Slot(float, result=float)
    def xAtDistance(self, distance: float) -> float:
        return self.data.x_at_distance(distance)

    @Slot(float, result=float)
    def referenceTimeAt(self, x: float) -> float:
        """Reference lap time at axis position (playback)"""
        return self.data.reference_time_at_x(x)

    @Slot(float, result=float)
    def xAtReferenceTime(self, seconds: float) -> float:
        return self.data.x_at_reference_time(seconds)

    @Property(float, notify=chartChanged)
    def referenceLapTime(self) -> float:
        reference = self.data.reference
        return self.data.lap_times(reference)[1][-1] if reference is not None and self.data.lap_times(
            reference)[1] else 0.0

    @Slot(float, result=str)
    def cursorTitle(self, x: float) -> str:
        distance = self.data.distance_at_x(x)
        return f"{format_axis_time(x)} · {distance_text(distance)}" if self.data.time_axis else distance_text(distance)

    @Slot(float, result=list)
    def cursorValues(self, x: float) -> list[list[dict]]:
        """Value of each lap (each series of combined panels) at axis position, for each panel

        One entry per drawn series (empty text past end of lap), so QML keeps its items.
        Difference with reference lap value added for single channel panels.
        """
        result = []
        reference = self.data.reference
        for column in self.visible:
            channel = CHANNEL_MAP[column]
            values = []
            if channel.parts:
                for lap in self.data.laps:
                    for index, part in enumerate(channel.parts):
                        part_channel = CHANNEL_MAP[part]
                        value = self.data.value_at(part_channel, lap, x)
                        color = (part_color(part) if len(self.data.laps) == 1
                                 else shade(lap.color, index, len(channel.parts)).name())
                        values.append({"text": "" if value is None else f"{part_label(part)} "
                                       f"{format_channel_value(part_channel, value)}", "color": color, "diff": ""})
            else:
                reference_value = self.data.value_at(channel, reference, x) if reference is not None else None
                for lap in self.data.laps:
                    value = self.data.value_at(channel, lap, x)
                    diff = ""
                    if (value is not None and reference_value is not None and lap is not reference
                            and column not in DELTA_CHANNELS):
                        diff = format_diff(channel, value - reference_value)
                    values.append({"text": "" if value is None else format_channel_value(channel, value),
                                   "color": lap.color.name(), "diff": diff})
            result.append(values)
        return result

    @Slot(float, result=dict)
    def cursorState(self, x: float) -> dict:
        """Everything shown at cursor in one call: title, chart values, map & G circle positions

        Map & G circle positions only while shown (empty otherwise, asked again once shown: optionsChanged,
        setMapShown): a hidden side tab costs nothing per cursor move.
        """
        self.build_trails(x)
        return {"title": self.cursorTitle(x), "values": self.cursorValues(x),
                "map": self.mapCursor(x) if self._map_shown else [],
                "g": self.gCursor(x) if self._side_tab == 1 else []}

    @Slot(float)
    def copyValues(self, x: float):
        """Values at cursor to clipboard as text (one line per channel)"""
        lines = [self.cursorTitle(x)]
        for column, values in zip(self.visible, self.cursorValues(x)):
            channel = CHANNEL_MAP[column]
            unit = self.data.unit_of(channel)
            texts = [
                f"{lap.label}: {value['text']}" for lap, value in zip(
                    [lap for lap in self.data.laps for _ in (channel.parts or (column,))], values) if value["text"]
            ]
            lines.append(f"{channel_title(channel)}{f' ({unit})' if unit else ''}: " + " | ".join(texts))
        QApplication.clipboard().setText("\n".join(lines))
        self.set_status(tr("Values copied to clipboard."))

    @Slot(int, result=list)
    def sectorRange(self, sector: int) -> list[float]:
        """Axis range of sector 1, 2 or 3 of reference lap (zoom on it), empty if sectors unknown"""
        bounds = self.data.sector_lines
        if len(bounds) != 2 or not 1 <= sector <= 3:
            return []
        limits = [0.0, *bounds, self.data.distance_at_x(self.data.max_x())]
        return [self.data.x_at_distance(limits[sector - 1]), self.data.x_at_distance(limits[sector])]

    @Slot(float, int, result=float)
    def stepFrame(self, x: float, frames: int) -> float:
        """Axis position of recorded sample frames before (negative) or after cursor, on reference lap"""
        reference = self.data.reference
        if reference is None or not frames:
            return x
        times = self.data.lap_times(reference)[1]
        if len(times) < 2:
            return x
        current = self.data.reference_time_at_x(x)
        if frames > 0:
            index = min(bisect.bisect_right(times, current + 1e-6) + frames - 1, len(times) - 1)
        else:
            index = max(bisect.bisect_left(times, current - 1e-6) + frames, 0)
        return self.data.x_at_reference_time(times[index])

    @Slot(float, float, result=list)
    def passageTimes(self, start: float, end: float) -> list[dict]:
        """Time of each shown lap between markers A & B, gap to fastest of them (fastest flagged)"""
        rows = self.data.range_stats(start, end, [])
        if not rows:
            return []
        best = min(row["time"] for row in rows)
        return [{"label": self.short_label(row["lap"].key), "color": row["lap"].color.name(),
                 "time": number_text(row["time"], 3), "gap": signed(row["time"] - best, 3) if row["time"] > best else "",
                 "best": row["time"] <= best} for row in rows]

    @Slot(float, float, result=dict)
    def rangeStats(self, start: float, end: float) -> dict:
        """Between markers A & B: each lap time taken (and gap to reference), min / max / mean of channels"""
        channels = [channel for channel in self.csv_channels() if channel.column not in DELTA_CHANNELS]
        stats = self.data.range_stats(start, end, channels)
        if not stats:
            return {}
        low, high = sorted((start, end))
        reference_time = next((row["time"] for row in stats if row["lap"] is self.data.reference), None)
        laps = []
        for row in stats:
            gap = ""
            if reference_time is not None and row["lap"] is not self.data.reference:
                gap = signed(row["time"] - reference_time, 3)
            laps.append({"label": self.short_label(row["lap"].key), "color": row["lap"].color.name(),
                         "time": f"{number_text(row['time'], 3)} s", "gap": gap, "distance": distance_text(row["distance"])})
        channel_rows = []
        for index, channel in enumerate(channels):
            unit = self.data.unit_of(channel)
            cells = []
            for row in stats:
                values = row["values"][index]
                if values is None:
                    cells.append({"text": "—", "color": row["lap"].color.name()})
                    continue
                low_value, high_value, mean = (format_channel_value(channel, value) for value in values)
                cells.append({"text": f"{low_value} / {high_value} / {mean}", "color": row["lap"].color.name()})
            channel_rows.append({"title": channel_title(channel) + (f" ({unit})" if unit else ""), "cells": cells})
        return {
            "title": f"{self.cursorTitle(low)} → {self.cursorTitle(high)}", "laps": laps, "channels": channel_rows,
        }

    # Session tab (see lap_session)
    @Property(list, notify=sessionChanged)
    def sessions(self) -> list[dict]:
        return [{"key": key, "title": title} for key, title, _ in self.session_groups()]

    @Property(str, notify=sessionChanged)
    def sessionKey(self) -> str:
        return self.session_key()

    @Property(dict, notify=sessionChanged)
    def sessionData(self) -> dict:
        """Laps of shown session: number, time, valid, fuel & tyre wear used, off tracks, track limits, shown"""
        return self.session_data()

    # Corners (see lap_corners)
    @Property(list, notify=cornersChanged)
    def coaching(self) -> list[dict]:
        """Corners where compared lap loses most time (up to 3): row index, name, time lost, causes"""
        return self._coaching

    @Property(str, notify=cornersChanged)
    def coachingLap(self) -> str:
        lap = self.compared_lap()
        return self.short_label(lap.key) if lap is not None else ""

    @Property(list, notify=cornersChanged)
    def cornerRanges(self) -> list[list[float]]:
        """Axis range of every corner in lap order (previous / next corner keys)"""
        return [self.cornerRange(index) for index in range(len(self._corner_rows))]

    # XY tab: scatter of two channels, time spent in value ranges (histogram)
    @Property(list, notify=channelsChanged)
    def xyChannels(self) -> list[dict]:
        """Single channels available in shown laps: column, title (unit)"""
        rows = []
        for channel in (*CHANNELS, *(CHANNEL_MAP[channel.column] for channel in self._math)):
            if channel.parts or (self.data.laps and not self.data.available(channel)):
                continue
            unit = self.data.unit_of(channel)
            rows.append({"column": channel.column, "title": channel_title(channel) + (f" ({unit})" if unit else "")})
        return rows

    def xy_samples(self, column: str, lap: PlotLap) -> tuple[Sequence[float], Sequence[float]]:
        """Reference distances & values of channel (user unit), zoomed chart part only when charts are zoomed"""
        if column not in CHANNEL_MAP or CHANNEL_MAP[column].parts:
            return [], []
        xs, ys = self.data.series(CHANNEL_MAP[column], lap, time_axis=False, aligned=False)
        start, end = self.zoom_distances()
        if end > start and xs:
            low, high = bisect.bisect_left(xs, start), bisect.bisect_right(xs, end)
            return xs[low:high], ys[low:high]
        return xs, ys

    @Property(dict, notify=optionsChanged)
    def xyState(self) -> dict:
        """XY tab choices: mode (scatter, histogram), x & y channels, histogram channel"""
        return dict(self._xy)

    @Slot(str, str, str, str)
    def setXyState(self, mode: str, x_column: str, y_column: str, histogram: str):
        state = {"mode": mode if mode in ("scatter", "histogram") else "scatter", "x": x_column, "y": y_column,
                 "histogram": histogram}
        state.update({name: self._xy[name] for name in ("x", "y", "histogram") if state[name] not in CHANNEL_MAP})
        if state != self._xy:
            self._xy = state
            save_viewer_setting(self.folder, xy=state)

    @Slot(str, str, result=dict)
    def scatter(self, x_column: str, y_column: str) -> dict:
        """Dots of each shown lap: x channel value against y channel value (same place on track)

        Vertices in plot fractions (0 to 1, y up) & value range of each axis, zoomed chart part only if zoomed.
        """
        if x_column not in CHANNEL_MAP or y_column not in CHANNEL_MAP or not self.data.laps:
            return {}
        pairs: list[tuple[PlotLap, Sequence[float], Sequence[float]]] = []
        for lap in self.data.laps:
            x_distances, x_values = self.xy_samples(x_column, lap)
            y_distances, y_values = self.xy_samples(y_column, lap)
            if len(x_distances) < 2 or len(y_distances) < 2:
                continue
            ys = y_values if y_distances == x_distances else [interpolate(y_distances, y_values, distance)
                                                               for distance in x_distances]
            pairs.append((lap, x_values, ys))
        if not pairs:
            return {}
        ranges = []
        for series, column in (([pair[1] for pair in pairs], x_column), ([pair[2] for pair in pairs], y_column)):
            channel = CHANNEL_MAP[column]
            if channel.fixed_range:
                low, high = channel.fixed_range
            else:
                low = min(min(values) for values in series)
                high = max(max(values) for values in series)
                if high - low < 1e-6:
                    high = low + 1
                padding = (high - low) * 0.04
                low, high = low - padding, high + padding
            ranges.append((low, high, channel))
        (x_low, x_high, x_channel), (y_low, y_high, y_channel) = ranges
        laps = []
        keys = set()
        for lap, lap_xs, lap_ys in pairs:
            key = f"{self.prefix}xy|{lap.key}"
            VertexStore.set(key, dots([(x - x_low) / (x_high - x_low) for x in lap_xs],
                                      [(y - y_low) / (y_high - y_low) for y in lap_ys], XY_DOT, 6000))
            keys.add(key)
            laps.append({"key": key, "lap": lap.key, "color": lap.color.name()})
        self._xy_keys = keys
        self.bump_revision()

        def ticks(low: float, high: float, channel: Channel) -> list[dict]:
            step = nice_step(high - low, 4)
            first = math.ceil(low / step) * step
            return [{"at": (value - low) / (high - low), "text": format_axis_value(channel, value, high - low)}
                    for value in (first + index * step for index in range(10)) if value <= high]

        return {"laps": laps, "xTicks": ticks(x_low, x_high, x_channel), "yTicks": ticks(y_low, y_high, y_channel),
                "xTitle": channel_title(x_channel), "yTitle": channel_title(y_channel),
                "zero": [(0 - x_low) / (x_high - x_low), (0 - y_low) / (y_high - y_low)],
                "xRange": [x_low, x_high], "yRange": [y_low, y_high]}  # zoomed plot asks ticks of part shown

    @Slot(str, result=dict)
    def histogram(self, column: str) -> dict:
        """Share of lap time spent in each value range of channel, each shown lap (zoomed chart part if zoomed)"""
        channel = CHANNEL_MAP.get(column)
        if channel is None or channel.parts or not self.data.laps:
            return {}
        samples = []
        for lap in self.data.laps:
            distances, values = self.xy_samples(column, lap)
            if len(distances) < 2:
                continue
            own, times = self.data.lap_times(lap)
            scale = self.data.scale_of(lap)
            lap_times = [interpolate(own, times, distance / scale) for distance in distances] if own else distances
            samples.append((lap, values, time_weights(lap_times)))
        if not samples:
            return {}
        if column in INTEGER_CHANNELS:  # one bar per whole value (gear 1, 2, 3...)
            levels = sorted({round(value) for _, values, _ in samples for value in values})
            edges = [level - 0.5 for level in levels] + [levels[-1] + 0.5]
            labels = [str(level) for level in levels]
        else:
            if channel.fixed_range:
                low, high = channel.fixed_range
                step = (high - low) / 10
            else:
                low = min(min(values) for _, values, _ in samples)
                high = max(max(values) for _, values, _ in samples)
                step = nice_step(max(high - low, 1e-6), HISTOGRAM_BINS)
                low = math.floor(low / step) * step
            count = max(min(math.ceil((high - low) / step - 1e-9), 40), 1)
            edges = [low + step * index for index in range(count + 1)]
            labels = [format_axis_value(channel, edges[index], step * count) for index in range(count)]
        laps = []
        top = 0.0
        for lap, values, weights in samples:
            shares = [0.0] * (len(edges) - 1)
            total = sum(weights) or 1.0
            for value, weight in zip(values, weights):
                position = min(max(bisect.bisect_right(edges, value) - 1, 0), len(shares) - 1)
                shares[position] += weight
            shares = [share / total * 100 for share in shares]
            top = max(top, max(shares, default=0.0))
            laps.append({"label": self.short_label(lap.key), "color": lap.color.name(), "values": shares, "lap": lap.key})
        return {"bins": labels, "laps": laps, "max": top, "unit": self.data.unit_of(channel),
                "title": channel_title(channel)}

    # G circle: right turn on the right, braking at bottom
    def build_gcircle(self, now: bool = False):
        """Dots & grip envelope of each shown lap, built only while G circle tab is shown or if now (laps changed
        while hidden: built once shown or read, see gCircle)"""
        self._g_points = []
        peaks = []
        shown = {lap.key for lap in self.data.laps}
        self._g_laps = {name: value for name, value in self._g_laps.items() if name in shown}
        self._g_drawn = {name: value for name, value in self._g_drawn.items() if name in shown}
        self._gcircle_stale = self._side_tab != 1 and not now
        if self._gcircle_stale:  # vertices of laps still shown kept (not built again), of other laps dropped
            kept = [item for item in self._gcircle.get("dots", []) if item["lap"] in shown]
            self._gcircle = {"dots": kept} if kept else {}
            return
        for lap in self.data.laps:
            cached = self._g_laps.get(lap.key)
            if cached is None or cached[0] is not lap.data:
                lat, lon = lap.data.columns.get("accel_lat"), lap.data.columns.get("accel_long")
                if not lat or not lon:
                    continue
                # Game: lateral positive to the left, longitudinal positive when braking
                xs, ys = [-value for value in lat], [-value for value in lon]
                peak = percentile([max(abs(x), abs(y)) for x, y in zip(xs, ys)], G_PERCENTILE)
                cached = self._g_laps[lap.key] = (lap.data, lap.data.distance, xs, ys, peak)
            self._g_points.append((cached[1], cached[2], cached[3], lap))
            peaks.append(cached[4])
        if not self._g_points:
            self._gcircle = {}
            return
        limit = max(peaks, default=1.0)
        limit = max(1.0, float(math.ceil(limit * 1.05)))  # some room around
        dots_list = []
        for _, xs, ys, lap in self._g_points:
            key = f"{self.prefix}g|{lap.key}"
            drawn = self._g_drawn.get(lap.key)
            if drawn is None or drawn[0] is not lap.data or drawn[1] != limit or not VertexStore.has(key):
                VertexStore.set(key, dots(xs, ys, limit / 110))
                VertexStore.set(key + "|envelope", line_strip(*g_envelope(xs, ys)))
                self._g_drawn[lap.key] = (lap.data, limit)
            dots_list.append({"key": key, "zoom": key + "|zoom", "envelope": key + "|envelope",
                              "color": lap.color.name(), "lap": lap.key})
        self._gcircle = {"limit": limit, "dots": dots_list}
        if self._side_tab == 1:  # else built when G circle tab is shown
            self.build_gcircle_zoom()

    def build_gcircle_zoom(self):
        start, end = self.zoom_distances()  # charts zoom (map view is not updated while map is hidden)
        limit = self._gcircle.get("limit", 1.0)
        for distances, xs, ys, lap in self._g_points:
            key = f"{self.prefix}g|{lap.key}|zoom"
            if end > start:
                scale = self.data.scale_of(lap)
                low, high = bisect.bisect_left(distances, start / scale), bisect.bisect_right(distances, end / scale)
                VertexStore.set(key, dots(xs[low:high], ys[low:high], limit / 70))
            else:
                VertexStore.set(key, dots([], [], 0))

    @Slot(float, result=list)
    def gCursor(self, x: float) -> list[dict]:
        if self._gcircle_stale:
            self.build_gcircle(True)
        points = []
        for distances, xs, ys, lap in self._g_points:
            distance = self.data.lap_distance_at_x(lap, x)
            points.append({"x": interpolate(distances, xs, distance), "y": interpolate(distances, ys, distance),
                           "color": lap.color.name(), "lap": lap.key})
        return points

    # Replay
    def replay_target(self, lap: PlotLap, x: float) -> tuple[str, float] | None:
        """Replay file covering lap & position in it at axis position, None if no replay recorded then

        Lap end: exact time of lap info if recorded ("finished"), else file name date (whole seconds: middle of that
        second). Imported MoTeC laps without a log date (named at import time) are never linked.
        """
        from ...replay import list_replays

        meta = lap.data.meta
        finished = meta.get("finished")
        if isinstance(finished, (int, float)) and not isinstance(finished, bool) and finished > 0:
            timestamp = float(finished)
        elif meta.get("source") == "MoTeC":
            return None
        else:  # lap end: real time, or replay time if replayed
            timestamp = lap_timestamp_of(os.path.basename(lap.key)) + 0.5
        lap_time = lap.data.lap_time or lap_time_of(os.path.basename(lap.key))
        if timestamp <= 0.5 or lap_time <= 0:
            return None
        distances, times = self.data.lap_times(lap)
        at = interpolate(distances, times, self.data.lap_distance_at_x(lap, x)) if distances else 0.0
        moment = timestamp - lap_time + at
        replayed = str(meta.get("replay", ""))
        candidates = list_replays(cfg.path.telemetry or ".")
        if replayed:  # lap recorded while replaying: that replay first
            candidates.sort(key=lambda item: os.path.basename(item.filename) != replayed)
        for item in candidates:
            if item.duration >= 0:
                end = item.created + item.duration
            else:  # interrupted recording: written until file last changed
                try:
                    end = os.path.getmtime(item.filename)
                except OSError:
                    continue
            if item.created - 2 <= moment <= end + 2:
                return item.filename, min(max(moment - item.created, 0.0), max(end - item.created, 0.0))
        return None

    @Slot(float, str)
    def openReplay(self, x: float, lap_key: str = ""):
        """Open replay recorded with lap at cursor position (replay page)"""
        lap = next((lap for lap in self.data.laps if lap.key == lap_key), self.data.reference)
        if lap is None:
            return
        target = self.replay_target(lap, x)
        if target is None:
            self.set_status(tr("No replay recorded with this lap."))
            return
        filename, position = target
        from ...replay import replay
        from .._common import BaseDialog
        from ..tools_view import open_tool

        open_tool("replay_view.ReplayView", self._window)
        top = self._window.window()
        views = [widget for widget in [top, *top.findChildren(BaseDialog), *QApplication.topLevelWidgets()]
                 if type(widget).__name__ == "ReplayView"]
        if not views:
            return
        view: Any = views[-1]  # ReplayView (imported only when replay page opens)

        def show_position():
            player = replay.player
            if player is None or os.path.normpath(player.replay.filename) != os.path.normpath(filename):
                return
            player.seek(position)
            player.set_paused(True)
            view.refresh()
            with suppress(RuntimeError):  # lap viewer closed while replay was loading
                self.set_status(
                    trm(f"Replay: {html.escape(os.path.basename(filename))} at {format_axis_time(position)}"))

        player = replay.player
        if player is None or os.path.normpath(player.replay.filename) != os.path.normpath(filename):
            view.open_file(filename, show_position)  # loaded in background, position shown once loaded
            if view.loader.busy:
                self.set_status(tr("Loading replay…"))
        else:
            show_position()
