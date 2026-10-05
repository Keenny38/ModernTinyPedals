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
"""

from __future__ import annotations

import base64
import bisect
import concurrent.futures
import csv
import html
import json
import logging
import math
import multiprocessing
import os
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
    QLocale,
    QObject,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from ... import app_signal
from ...const_api import API_LMU_CONFIG
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile import track_geometry
from ...userfile.corner_analysis import (
    SPEED_HYSTERESIS,
    CornerComparison,
    CornerStats,
    IdealLap,
    ResampledLap,
    coaching_tips,
    compare_corners,
    corner_stats,
    ideal_lap,
    lap_time_delta,
    resample_sorted,
    straights_delta,
)
from ...userfile.lap_cache import load_cached_lap, prune_cache, remove_cached_lap
from ...userfile.lap_geometry import (  # noqa: F401  (limits_part & median_bounds re-exported)
    Yielder,
    limits_part,
    median_bounds,
    session_values,
    track_limits_job,
)
from ...userfile.lap_marks import load_marks, remove_mark, set_mark
from ...userfile.motec_import import import_ld_file
from ...userfile.motec_ld import export_lap, export_lap_job
from ...userfile.telemetry_lap import (
    IMPORT_FOLDER,
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
    monotonic_distance,
    read_lap_info,
    sector_times,
    theoretical_best,
    write_lap_csv,
)
from ...userfile.track_corners import TrackCorner, track_corners
from ...userfile.track_map import load_track_map_file
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
    TRACK_WIDTH,
    Channel,
    LapEntry,
    PlotLap,
    channel_title,
    corner_label,
    format_axis_time,
    format_axis_value,
    format_channel_value,
    format_laptime,
    format_value,
    lap_color,
    lap_label,
    load_viewer_setting,
    nice_step,
    part_color,
    part_label,
    save_viewer_setting,
    shade,
    signed,
)
from . import lap_map
from .lines import (
    VertexStore,
    Vertices,
    band,
    band_part,
    colored_band,
    dots,
    line_strip,
    markers,
    merge_strips,
    normals,
    range_band,
    range_indexes,
    segments,
    step_strip,
)
from .models import DictListModel
from .trace_data import TraceData

logger = logging.getLogger(__name__)

COLOR_GAIN = "gain"  # theme color names (QML theme.gain / theme.loss: readable on light & dark themes)
COLOR_LOSS = "loss"
PANEL_ROLES = ("column", "low", "high", "ticks", "envelope", "note", "available", "seriesModel")
SERIES_ROLES = ("key", "lods", "color", "lap")
LEGEND_ROLES = ("key", "label", "full", "color", "reference", "clean", "tip")
MAP_LAP_ROLES = ("lap", "key", "highlight", "trail", "color", "reference", "shapes", "brakeZones", "throttleZones")
LAP_ROLES = (
    "kind", "session", "path", "title", "time", "s1", "s2", "s3", "best1", "best2", "best3", "info", "note",
    "checked", "reference", "color", "dim", "fastest", "count", "error", "gap", "tip",
)
LINE_WIDTH = 1.2  # half width of driving lines on map, pixels
ZOOMED_WIDTH = 2.2  # half width of zoomed part & colored line, pixels
STATUS_DURATION = 8000  # ms, transient status messages shown
WATCH_DELAY = 1500  # ms after a lap file appears before list is refreshed (file fully written)
G_PERCENTILE = 0.99  # G circle scale: share of samples inside (curb & contact spikes left out)
G_SECTORS = 36  # G-G envelope directions
G_ENVELOPE_QUANTILE = 0.98  # G-G envelope radius: share of samples inside, in each direction
CORNER_SORTS = ("track", "loss")
MAP_OPTIONS = {  # track map display options & default
    "apex": True,  # minimum speed point of each lap in each corner
    "exit": True,  # full throttle point of each lap after each apex
    "arrows": True,  # driving direction arrows
    "sectors": True,  # sector times & gap of compared lap
    "values": False,  # speed next to driving points
    "track": True,  # view follows vehicles while playing lap or moving cursor with keys
    "trackout": True,  # point where each lap comes closest to corner outside edge (track limits needed)
    "zones": False,  # braking & throttle application zones of reference (or highlighted) lap
    "trail": True,  # last seconds of each lap behind cursor
    "limits": True,  # track edges guessed from every recorded lap of the circuit
    "colorblind": False,  # gain / loss in blue & orange instead of green & red
    "distances": True,  # distance marks along circuit
    "offtrack": True,  # where 2 wheels or more go on grass, dirt or gravel (recorded wheel surface)
    "limit": True,  # where car goes beyond track edge (four wheels out)
    "spread": False,  # braking points range of shown laps in each corner
    "pit": True,  # pit lane (official circuit map)
    "minimap": True,  # whole circuit in a corner when zoomed in
}
MARKER_PIXELS = {  # driving point marker size across (pixels) & shape
    "brake": (11, "diamond"), "apex": (11, "dot"), "exit": (15, "triangle"), "trackout": (10, "square"),
    "lock": (13, "ring"), "spin": (14, "hollow_triangle"), "offtrack": (13, "hollow_diamond"), "limit": (12, "cross"),
}
OUTLINE_PIXELS = 3  # marker outline (map background color) around each marker
ARROW_PIXELS = 11  # driving direction arrows
TRAIL_SECONDS = 3.0  # cursor trail length (lap time)
LIMITS_FOLDER = ".track_limits"  # track limits cache, in telemetry folder (hidden: not a track)
LIMITS_LAPS = 40  # newest clean laps used to guess track limits
ZOOM_BUCKETS = 2  # map scale steps per doubling: thick lines & markers built once per step (cached)
BAND_CACHE_STEPS = 10  # map scale steps kept (least recently used dropped)
JOB_INTERVAL = 80  # ms, background jobs checked
MINIMAP_PIXELS = 150  # minimap size across (thin lines sized for it)
EVENT_TITLES = {"offtrack": "Off track", "limit": "Track limits exceeded"}
# Chart series reduced copies (min & max of each bucket, same peaks): drawn when a bucket is at most a pixel wide
LOD_LEVELS = (1500, 4500)  # buckets over whole lap
LOD_MIN_RATIO = 2.5  # copy made only for series with this many samples per bucket or more
TRASH_FOLDER = ".trash"  # deleted laps, in telemetry folder (hidden: not a track), restored by undo
TRASH_DAYS = 30  # deleted laps kept in trash folder
WORKER_IDLE = 60_000  # ms without job before worker process stops (its memory given back)
USE_WORKER_PROCESS = True  # heavy jobs (track limits, session values) in a worker process, else in threads
XY_DOT = 0.007  # scatter dot size, share of plot
PREFETCH_DELAY = 400  # ms map view stays still before neighbor scales are built
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


def format_diff(channel: Channel, value: float) -> str:
    """Difference with reference lap at cursor: "-4" (typeset minus sign), "+12%" """
    if channel.fixed_range in PERCENT_RANGES:
        return signed(value * 100, 0, "%")
    if channel.column == "gear":
        return signed(value, 0)
    text = format_value(abs(value))
    return ("+" if value >= 0 else chr(0x2212)) + text


PIT_PART_GAP = 20.0  # meters between pit lane points: separate parts (not joined by a line)


def scale_step(meters_per_pixel: float) -> float:
    """Map scale rounded to steps (ZOOM_BUCKETS per doubling): thick lines built once per step"""
    return round(math.log2(max(meters_per_pixel, 1e-3)) * ZOOM_BUCKETS) / ZOOM_BUCKETS


_worker: concurrent.futures.ProcessPoolExecutor | None = None
_worker_broken = False  # worker process could not start: jobs run in threads
_quit_hooked = False  # worker killed when app quits (a running job would delay exit until done)
_finishing: list[concurrent.futures.ProcessPoolExecutor] = []  # worker processes of closed pages ending exports
_export_futures: set[concurrent.futures.Future] = set()  # export jobs not finished yet
EXPORT_JOBS = ("MoTeC export", "CSV export")  # jobs finished even if viewer is closed
EXIT_EXPORT_WAIT = 5.0  # seconds app exit waits for exports still running, then they are dropped


def worker_pool() -> concurrent.futures.ProcessPoolExecutor | None:
    """Worker process for heavy lap jobs, None if not available

    Pure Python work in a thread holds the interpreter lock: page thread (drawing, mouse) would wait for it.
    A worker process runs beside the page instead (frozen app: started by multiprocessing.freeze_support).
    """
    global _worker, _worker_broken, _quit_hooked
    if _worker is None and not _worker_broken and USE_WORKER_PROCESS:
        try:
            _worker = concurrent.futures.ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        except (OSError, ValueError, RuntimeError) as error:
            logger.warning("LAP VIEWER: worker process not available, jobs in threads: %s", error)
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
    """Background job running in a thread, or in worker process (future): same interface for both"""

    BROKEN = object()  # result of a job lost with its worker process (run again in a thread)

    def __init__(self, name: str, thread: threading.Thread | None = None, holder: dict | None = None,
                 future: concurrent.futures.Future | None = None):
        self.name = name
        self.thread = thread
        self.holder = holder if holder is not None else {}
        self.future = future

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
            logger.warning("LAP VIEWER: worker process stopped (%s), %s run again in a thread", error, self.name)
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
    """Job in worker process if available (function & args picklable), else in a thread"""
    pool = worker_pool()
    if pool is not None:
        try:
            future = pool.submit(function, *args)
            if name in EXPORT_JOBS:  # waited for a few seconds at app exit
                _export_futures.add(future)
                future.add_done_callback(_export_futures.discard)
            return JobHandle(name, future=future)
        except (RuntimeError, concurrent.futures.process.BrokenProcessPool) as error:
            logger.warning("LAP VIEWER: worker process not available (%s), %s in a thread", error, name)
            mark_worker_broken()
    return start_thread_job(name, lambda: function(*args))


def mark_worker_broken():
    global _worker_broken
    _worker_broken = True
    stop_worker()


def pit_parts(points: list[tuple[float, float, float]]) -> list[list[tuple[float, float, float]]]:
    """Pit lane points split where consecutive points are far apart, parts of 2 points or more"""
    parts: list[list[tuple[float, float, float]]] = []
    for point in points:
        if not parts or math.hypot(point[0] - parts[-1][-1][0], point[1] - parts[-1][-1][1]) > PIT_PART_GAP:
            parts.append([])
        parts[-1].append(point)
    return [part for part in parts if len(part) > 1]


def yaw_calibration(lap: LapData) -> tuple[float, float]:
    """Sign & offset turning recorded yaw into map heading (radians): heading = sign * yaw + offset, sign 0 if
    not found (car not pointing where it goes)"""
    columns = lap.columns
    yaws, xs, ys, speeds = columns.get("yaw"), columns.get("pos_x"), columns.get("pos_y"), columns.get("speed_kph")
    if not yaws or not xs or not ys or not speeds:
        return 0.0, 0.0
    samples = []
    for index in range(5, len(yaws) - 5, 5):
        if speeds[index] < 60:
            continue
        dx, dy = xs[index + 5] - xs[index - 5], ys[index + 5] - ys[index - 5]
        if dx * dx + dy * dy < 4:
            continue
        samples.append((math.atan2(dy, dx), yaws[index]))
    if len(samples) < 20:
        return 0.0, 0.0
    best = (math.inf, 0.0, 0.0)
    for sign in (1.0, -1.0):
        offset = math.atan2(sum(math.sin(travel - sign * yaw) for travel, yaw in samples),
                            sum(math.cos(travel - sign * yaw) for travel, yaw in samples))
        error = sum(abs((travel - sign * yaw - offset + math.pi) % math.tau - math.pi)
                    for travel, yaw in samples) / len(samples)
        if error < best[0]:
            best = (error, sign, offset)
    error, sign, offset = best
    return (sign, offset) if error < math.radians(8) else (0.0, 0.0)


def keys_match(old: tuple | None, new: tuple) -> bool:
    """Cache key comparison: loaded laps (objects) by identity, other parts by value

    Never compares lap data by value (slow) nor by id() (an id is reused once a lap is freed).
    """
    if old is None or len(old) != len(new):
        return False
    for first, second in zip(old, new):
        if type(second) is tuple:  # nested key (NamedTuple: lap, line... compared by identity)
            if type(first) is not tuple or not keys_match(first, second):
                return False
        elif isinstance(second, (str, int, float, bool)) or second is None:
            if first != second:
                return False
        elif first is not second:
            return False
    return True


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


def least_squares(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Slope & intercept of line fitting points, (0, mean) if x does not vary"""
    count = len(points)
    if not count:
        return 0.0, 0.0
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    if spread <= 0:
        return 0.0, mean_y
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread
    return slope, mean_y - slope * mean_x


class LapViewerBackend(QObject):
    """Lap telemetry viewer page state (QML context property "backend")"""

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
    sessionChanged = Signal()  # session tab laps
    undoChanged = Signal()  # deleted laps that can be restored

    def __init__(self, parent: QWidget, folder: str):
        super().__init__(parent)
        self._window = parent
        self.folder = folder
        self.prefix = f"lap_viewer_{id(self)}|"  # vertex store keys of this page
        self.data = TraceData()
        self.entries: list[LapEntry] = []
        self.external: list[LapEntry] = []
        self.checked: set[str] = set()
        self.reference_key = ""
        self.lap_model = DictListModel(LAP_ROLES, self)
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
        self._base = lap_map.MapLine([], [], [])  # line lap placement is measured from (official center path)
        self._base_official = False
        self._edges: tuple[list[float], list[float]] = ([], [])  # track edge offsets along base line
        self._lap_offsets: dict[str, tuple[tuple, lap_map.MapLine, list[float], list[int]]] = {}
        self._events: dict[str, tuple[tuple, list[tuple[float, str]]]] = {}  # off track & track limits of laps
        self._color_lines: tuple = ()  # colored map line: (key, colors at each line point), rebuilt if key changes
        self._colored_steps: dict[float, Vertices] = {}  # colored line vertices by map scale step
        self._colored_shown: Vertices | None = None  # colored line vertices put in vertex store
        self._zones: dict[str, tuple[LapData, tuple]] = {}  # lap key: lap data, braking & throttle zones
        # Per lap & per reference results kept while laps stay the same (showing one more lap computes only it)
        self._official_line: tuple = ()  # (key, official center path line)
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
        self._undo: list[tuple[str, str, dict, bool]] = []  # deleted laps: path, trash path, marks, checked
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
        self._compare_key = ""  # lap compared corner by corner & on gain map, first compared lap if not shown
        self._loader: threading.Thread | None = None
        self._exports = 0  # MoTeC & CSV export jobs running
        self._loaded: dict[str, LapData | None] = {}
        self._load_total = 0
        self._load_message = ""  # status before loading started
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(30)
        self._load_timer.timeout.connect(self.check_background_load)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(STATUS_DURATION)
        self._status_timer.timeout.connect(lambda: self.set_status("", False))
        self._released = False
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

        Exports still running finish in worker process (other jobs dropped): files written whole.
        """
        VertexStore.remove_prefix(self.prefix)
        if self._exports > 0:
            for handle, _, _ in self._jobs:
                if handle.future is not None and handle.name not in EXPORT_JOBS:
                    handle.future.cancel()  # waiting page jobs not done (running one ends soon)
            stop_worker(finish=True)
        else:
            kill_worker()
        if self._units_connected:
            self._units_connected = False
            with suppress(RuntimeError, TypeError):
                app_signal.refresh.disconnect(self.units_refresh)

    def run_job(self, name: str, work: Callable[[], Any], done: Callable[[Any], None]):
        """Run work in a thread, done(result) called on page thread once finished (result None if failed)"""
        self.add_job(start_thread_job(name, work), done)

    def run_process_job(self, name: str, done: Callable[[Any], None], function: Callable, *args):
        """Run module level function in worker process (thread if not available), done(result) on page thread"""
        self.add_job(start_job(name, function, *args), done, lambda: function(*args))

    def add_job(self, handle: JobHandle, done: Callable[[Any], None], retry: Callable[[], Any] | None = None):
        self._jobs.append((handle, done, retry))
        self._idle_timer.stop()
        self._job_timer.start()

    @Slot()
    def check_jobs(self):
        """Finished background jobs: results handled on page thread"""
        finished = [job for job in self._jobs if not job[0].is_alive()]
        self._jobs = [job for job in self._jobs if job[0].is_alive()]
        for handle, done, retry in finished:
            result = handle.result()
            if result is JobHandle.BROKEN:  # worker process died: job run again in a thread
                mark_worker_broken()
                if retry is not None:
                    self.add_job(start_thread_job(handle.name, retry), done)
                continue
            done(result)
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
        if track != self._track:
            self.load_track(track)

    tracks = Property(list, _tracks_get, notify=tracksChanged)
    currentTrack = Property(str, _track_get, _track_set, notify=tracksChanged)

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
        return self._loader is not None

    @Property(int, notify=revisionChanged)
    def revision(self) -> int:
        return self._revision

    @Property(list, notify=chartChanged)
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

    @Property(list, notify=chartChanged)
    def sectorLines(self) -> list[dict]:
        return [
            {"x": self.data.x_at_distance(distance), "label": f"S{index + 2}", "index": index + 1}
            for index, distance in enumerate(self.data.sector_lines)
        ]

    @Property(list, notify=chartChanged)
    def cornerMarks(self) -> list[dict]:
        return self._corner_marks

    @Property(dict, notify=chartChanged)
    def trackMap(self) -> dict:
        return self._map

    @Property(dict, notify=chartChanged)
    def gCircle(self) -> dict:
        return self._gcircle

    @Property(list, notify=chartChanged)
    def corners(self) -> list[dict]:
        return self._corners

    @Property(int, notify=chartChanged)
    def hysteresis(self) -> int:
        return self._hysteresis

    @Property(list, notify=chartChanged)
    def comparedLaps(self) -> list[dict]:
        """Laps that can be compared with reference (corner table, gain map): key, label, color"""
        return [{"key": lap.key, "label": self.short_label(lap.key), "color": lap.color.name()}
                for lap in self.data.compared()]

    @Property(str, notify=chartChanged)
    def compareKey(self) -> str:
        lap = self.compared_lap()
        return lap.key if lap is not None else ""

    @Property(str, notify=chartChanged)
    def cornerSort(self) -> str:
        return self._corner_sort

    @Property(str, notify=chartChanged)
    def speedUnit(self) -> str:
        return self.data.units["speed"][1]

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
        if distance < 0 or not self._map_lines:
            return {}
        line = self._map_lines[0][0]
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

    @Slot(bool)
    def setMapShown(self, shown: bool):
        """Track map shown or hidden (side panel tab, focus mode): cursor trails built only when shown"""
        self._map_shown = max(self._map_shown + (1 if shown else -1), 0)

    @Slot(float, float)
    def setMapRange(self, start_x: float, end_x: float):
        """Chart markers A & B shown on map (negative: none)"""
        if start_x < 0 or end_x < 0:
            view = (-1.0, -1.0)
        else:
            low, high = sorted((start_x, end_x))
            view = (self.data.distance_at_x(low), self.data.distance_at_x(high))
        if view != self._map_range:
            self._map_range = view
            if self._map:
                self.build_map_overlays(self._map_view[2])
                self.bump_revision()

    @Slot(float, float, float, float, float, float, result=list)
    def mapVisibleRange(self, x0: float, y0: float, x1: float, y1: float, center_x: float, center_y: float) -> list:
        """Axis range of reference line part shown in map view around view center (charts follow map), empty if none"""
        if not self._map_lines:
            return []
        line, lap = self._map_lines[0]
        grid = self._grids.get(lap.key)
        found = lap_map.visible_range(line, (x0, y0, x1, y1), (center_x, center_y), grid) if grid else None
        if found is None or found[1] - found[0] < 20:
            return []
        return [self.data.x_at_distance(found[0]), self.data.x_at_distance(found[1])]

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
        mini-sectors won by each lap & ideal lap"""
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
            return {"low": f"{low:.0f}", "high": f"{high:.0f}", "unit": "m",
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
        return menu

    @Property(list, constant=True)
    def channelPresets(self) -> list[dict]:
        return [{"name": name, "title": tr(name)} for name in CHANNEL_PRESETS]

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
        track = self._track if self._track in self._tracks else (self._tracks[0] if self._tracks else "")
        self.drop_changed_laps()
        self._marks.clear()
        self.load_track(track)
        if not self._tracks and not self.external:
            self.set_status(tr("No recorded lap. Enable the Recorder module, then drive a few laps."), False)

    def drop_changed_laps(self):
        """Forget loaded laps whose file changed or was removed (refresh)"""
        for path in list(self._lap_cache):
            try:
                changed = os.path.getmtime(path) != self._cache_mtime.get(path)
            except OSError:
                changed = True
            if changed:
                self._lap_cache.pop(path, None)
                self._cache_mtime.pop(path, None)

    def load_track(self, track: str):
        self._track = track
        self.tracksChanged.emit()
        laps = list_laps(self.folder, track) if track else []
        self.entries = [LapEntry(lap, self.lap_info(lap.path)) for lap in laps]
        # Laps shown last time on this track, else fastest lap compared with newest other lap
        saved = load_viewer_setting(self.folder).get("selections", {})
        saved = saved.get(track, {}) if isinstance(saved, dict) else {}
        paths = {lap.filename: lap.path for lap in laps}
        checked = {paths[name] for name in saved.get("checked", []) if name in paths}
        reference = paths.get(saved.get("reference", ""), "")
        if checked and reference in checked:
            self.reference_key = reference
        else:
            best = best_laps(laps, 1)
            self.reference_key = best[0].path if best else (laps[0].path if laps else "")
            checked = {self.reference_key} if self.reference_key else set()
            newest = next((lap.path for lap in laps if lap.valid and lap.path != self.reference_key), "")
            if newest:
                checked.add(newest)
        added = {entry.file.path for entry in self.external}
        self.checked = checked | (self.checked & added)
        self._expanded = []
        self.watch_folders()
        self.start_geometry(track)
        self.start_limits(track)
        self.fill_list()
        self.load_laps()

    # Official circuit: track center path & pit lane from game REST API (saved), base of lap placement
    def track_title(self, track: str) -> str:
        """Game track name of track folder (lap info), else folder name without class"""
        for entry in self.entries:
            if entry.info.get("track"):
                return str(entry.info["track"])
        return track.rsplit(" - ", 1)[0]

    def start_geometry(self, track: str):
        """Official circuit of track: saved file, else asked to game in background (once per session)"""
        if track == self._geometry_track:
            return
        self._geometry_track = track
        self._geometry = track_geometry.load_geometry(self.folder, track) if track else None
        setting = cfg.user.setting.get(API_LMU_CONFIG, {}) if hasattr(cfg.user, "setting") else {}
        if (self._geometry is not None or not track or track in self._geometry_tried
                or not setting.get("enable_restapi_access", True)):
            return
        clean = [entry for entry in self.entries if entry.file.valid and entry.info.get("kind", "lap") == "lap"]
        if not clean:
            return
        self._geometry_tried.add(track)
        best = min(clean, key=lambda entry: entry.file.lap_time or float("inf"))
        host, port = str(setting.get("url_host", "localhost")), int(setting.get("url_port", 6397))
        title, folder = self.track_title(track), self.folder

        def fetching():
            tracks = track_geometry.rest_get(host, port, "/rest/race/track")
            if not isinstance(tracks, list):  # game not running: no lap file read
                return None
            lap = load_cached_lap(folder, best.file.path)
            found = lap_map.map_line(lap)
            positions = list(zip(found.xs, found.ys)) if found is not None else []
            length = float(best.info.get("track_length") or (lap.distance[-1] if len(lap) else 0.0))
            return track_geometry.fetch_geometry(host, port, title, positions, length, tracks)

        def fetched(geometry):
            if geometry is None or track != self._track:
                return
            track_geometry.save_geometry(self.folder, track, geometry)
            self._geometry = geometry
            self._limits_track = ""  # placement measured from official center path: track limits again
            self.start_limits(track)
            if self.data.laps:
                self.rebuild_chart()
            self.set_status(tr("Official circuit map received from game"))

        self.run_job("official circuit", fetching, fetched)

    def official_base(self, length: float = 0.0) -> lap_map.MapLine | None:
        """Official track center path from start line, distances scaled to lap length, None if unknown"""
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
        """What lap placement is measured from (saved track limits valid only for the same)"""
        geometry = self._geometry
        return f"official|{geometry.layout}|{len(geometry.center)}" if geometry is not None else "lap"

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
            if saved.get("laps") == names and "sectors" in saved and saved.get("base", "lap") == base_key:
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
        if result is JobHandle.BROKEN:  # worker process died: computed again in a thread
            mark_worker_broken()
            self._limits_job = start_thread_job("track limits", lambda: track_limits_job(*job["args"]))
            return
        self._limits_timer.stop()
        self._limits_job = None
        if not self._jobs and _worker is not None:
            self._idle_timer.start()
        job["result"] = result if isinstance(result, dict) else {}
        limits = job["result"].get("limits")
        if job["track"] != self._limits_track:
            return
        self._limits = limits
        self._limits_source = job["result"].get("source", "") if limits is not None else ""
        self._track_sectors = job["result"].get("sectors", [])
        try:
            os.makedirs(os.path.dirname(job["cache"]), exist_ok=True)
            saved: dict = {"laps": job["names"], "source": self._limits_source, "sectors": self._track_sectors,
                           "base": job["base"]}
            if limits is not None:
                for side, line in (("left", limits.left), ("right", limits.right)):
                    saved[side] = [[round(d, 2), round(x, 2), round(y, 2)]
                                   for d, x, y in zip(line.distances, line.xs, line.ys)]
            with open(job["cache"], "w", encoding="utf-8") as file:
                json.dump(saved, file)
        except OSError as error:
            logger.warning("LAP VIEWER: unable to save track limits: %s", error)
        if self.data.laps:
            self.apply_track_sectors()
            self.rebuild_chart()  # map built again: placement measured with new edges
        self.mapChanged.emit()

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
        """Watch telemetry & current track folders: new laps listed without refresh"""
        current = set(self._watcher.directories())
        wanted = {folder for folder in (self.folder, os.path.join(self.folder, self._track) if self._track else "")
                  if folder and os.path.isdir(folder)}
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
        if self._watched.get(key) == entries:
            return
        self._watched[key] = entries
        self._watch_timer.start()

    @Slot()
    def auto_refresh(self):
        """Lap files added or removed: list updated, newest lap compared with best lap in live mode"""
        if self._loader is not None:
            self._watch_timer.start()  # after current loading
            return
        tracks = list_tracks(self.folder)
        if tracks != self._tracks:
            self._tracks = tracks
            self.tracksChanged.emit()
        if not self._track and tracks:  # first lap ever recorded
            self.load_track(tracks[0])
            return
        known = {entry.file.path for entry in self.entries}
        laps = list_laps(self.folder, self._track) if self._track else []
        listed = {lap.path for lap in laps}
        if listed == known:
            return
        new = [lap for lap in laps if lap.path not in known]
        self.entries = [LapEntry(lap, self.lap_info(lap.path)) for lap in laps]
        self.checked = {path for path in self.checked if path in listed or path not in known}
        if self.reference_key not in self.checked:
            self.reference_key = ""
        if self._live and new:
            newest = new[0]  # lap files newest first
            best = best_laps(laps, 1)
            self.checked = {newest.path} | ({best[0].path} if best else set())
            self.reference_key = best[0].path if best and best[0].path != newest.path else newest.path
            self.set_status(trm(f"New lap: {lap_label(newest.filename)}"))
        self.fill_list()
        self.load_laps()

    @Slot(bool)
    def setLiveMode(self, enabled: bool):
        self._live = enabled
        save_viewer_setting(self.folder, live_mode=enabled)
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
                lines.append(f"{tr(label)}: {convert(value) if convert else value:.1f}{symbol}")
        wetness = number("wetness")
        if wetness is not None:
            lines.append(f"{tr('Wetness')}: {wetness * 100:.0f}%")
        start, end = number("fuel_start"), number("fuel_end")
        if start is not None:
            convert, symbol = lap_viewer.display_units()["fuel"]
            lines.append(f"{tr('Starting Fuel')}: {convert(start) if convert else start:.1f} {symbol}")
            if end is not None and start >= end:
                used = start - end
                lines.append(f"{tr('Fuel Used')}: {convert(used) if convert else used:.2f} {symbol}")
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
        return self._filter

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
        """Laps grouped by session (newest first), added files on top, sessions with shown laps expanded"""
        # Added files may come from other tracks: theoretical best & best sectors of current track only
        sectors = [self.entry_sectors(entry) for entry in self.entries if entry.file.valid]
        best_total, best_sectors = theoretical_best(sectors)
        best_lap = min((entry.file.lap_time for entry in self.entries if entry.file.valid and entry.file.lap_time > 0),
                       default=0.0)
        entries = [
            entry for entry in self.entries
            if entry.file.path in self.checked or entry.file.path == self.reference_key
            or ((not self._hide_unclean or (entry.file.valid and entry.info.get("kind") not in ("out", "in")))
                and self.matches_filter(entry))
        ]
        groups: list[tuple[list[LapEntry], bool]] = [
            (group, False)
            for group in group_sessions(entries, lambda entry: entry.file.filename, lambda entry: entry.info)
        ]
        added: dict[str, list[LapEntry]] = {}  # added laps by folder (imported log, other track)
        for entry in self.external:
            if entry.file.path in self.checked or entry.file.path == self.reference_key or self.matches_filter(entry):
                added.setdefault(os.path.dirname(entry.file.path), []).append(entry)
        groups[:0] = [(group, True) for group in added.values()]
        rows: list[dict] = []
        expanded = []
        for index, (group, is_added) in enumerate(groups):
            header = self.session_row(group, is_added)
            rows.append(header)
            vehicle = str(group[0].info.get("vehicle", ""))
            fastest = min((entry for entry in group if entry.file.valid and entry.file.lap_time > 0),
                          key=lambda entry: entry.file.lap_time, default=None)
            for entry in group:
                rows.append(self.lap_row(header["session"], entry, best_sectors, vehicle, entry is fastest, best_lap))
            if (index == 0 or header["session"] in self._expanded
                    or any(entry.file.path in self.checked or entry.file.path == self.reference_key
                           for entry in group)):
                expanded.append(header["session"])
        self.lap_model.reset(rows)
        self._expanded = expanded
        self.sessionChanged.emit()
        self._best_text = trm(f"Theoretical best: {format_laptime(best_total)}") if best_total > 0 else ""
        self.listChanged.emit()

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
            details.append(tr("added"))
        if vehicle:
            details.append(vehicle)
        return {
            "kind": "session", "session": key, "path": "", "title": title, "time": format_laptime(best),
            "s1": "", "s2": "", "s3": "", "best1": False, "best2": False, "best3": False,
            "info": ", ".join(details), "note": "", "count": len(group), "checked": False, "reference": False,
            "color": "", "dim": False, "fastest": False, "error": False, "gap": "", "tip": "",
        }

    def lap_row(self, session: str, entry: LapEntry, best_sectors: list[float], vehicle: str,
                is_fastest: bool, best_lap: float = 0.0) -> dict:
        """Lap row: number, time, gap to best lap, sectors (best ones flagged), info; invalid & out/in laps dimmed"""
        number = lap_number_of(entry.file.filename)
        sectors = self.entry_sectors(entry) or [0.0, 0.0, 0.0]
        bests = [
            value > 0 and bool(best_sectors) and abs(value - best) < 0.0005 and entry.file.valid and not entry.external
            for value, best in zip(sectors, best_sectors or [0.0, 0.0, 0.0])
        ]
        info = self.entry_text(entry, vehicle)
        note = ""
        if not entry.external:
            mark = self.lap_marks(entry.file.path)
            note = str(mark.get("note", ""))
            if mark.get("kept"):
                info = ", ".join(filter(None, [info, tr("kept")]))
        gap = ""
        if best_lap > 0 and entry.file.lap_time > 0 and not entry.external:
            difference = entry.file.lap_time - best_lap
            gap = signed(difference, 3) if difference >= 0.0005 else ""
        return {
            "kind": "lap", "session": session, "path": entry.file.path,
            "title": trm(f"Lap {number}") if number else lap_stem(entry.file.filename),
            "time": format_laptime(entry.file.lap_time),
            "s1": format_laptime(sectors[0]), "s2": format_laptime(sectors[1]), "s3": format_laptime(sectors[2]),
            "best1": bests[0], "best2": bests[1], "best3": bests[2], "info": info, "note": note,
            "checked": entry.file.path in self.checked, "reference": entry.file.path == self.reference_key,
            "color": "", "dim": not entry.file.valid or entry.info.get("kind") in ("out", "in"),
            "fastest": is_fastest, "count": 0, "error": entry.file.path in self._failed, "gap": gap,
            "tip": self.entry_conditions(entry),
        }

    def lap_rows(self) -> list[dict]:
        return [row for row in self.lap_model.rows if row["kind"] == "lap"]

    def ordered_checked(self) -> list[str]:
        """Checked laps in list order"""
        return [row["path"] for row in self.lap_rows() if row["path"] in self.checked]

    @Slot(str)
    def toggleSession(self, key: str):
        if key in self._expanded:
            self._expanded = [session for session in self._expanded if session != key]
        else:
            self._expanded = [*self._expanded, key]
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
        """Shift+click: every lap listed between two laps checked (or unchecked)"""
        paths = [row["path"] for row in self.lap_rows()]
        if first not in paths or last not in paths:
            self.setLapChecked(last, checked)
            return
        low, high = sorted((paths.index(first), paths.index(last)))
        for path in paths[low:high + 1]:
            if checked:
                self.checked.add(path)
            else:
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
        self.checked = {lap.path for lap in best}
        self.fill_list()
        self.load_laps()

    @Slot(str)
    def setReference(self, path: str):
        if not path:  # session header
            return
        self.reference_key = path
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

    # Delta best: recorded lap as delta reference of Delta Best widgets (same file as module_delta)
    def delta_best_file(self, path: str) -> str:
        """Delta best file of recorded lap track (track & class folder is the game combo name)"""
        return os.path.join(cfg.path.delta_best, f"{os.path.basename(os.path.dirname(path))}.csv")

    @staticmethod
    def delta_best_rows(lap: LapData, lap_time: float) -> list[tuple[float, float]]:
        """Distance & lap time rows of delta best file (same layout as module_delta: start, every meter, end)"""
        distances, times = monotonic_distance(lap)
        rows = [(0.0, 0.0)]
        for distance, seconds in zip(distances, times):
            if distance > rows[-1][0] + 1.0 and seconds > rows[-1][1] and 0 < seconds < lap_time:
                rows.append((round(distance, 6), round(seconds, 6)))
        rows.append((round(rows[-1][0] + 10, 6), round(lap_time, 6)))  # end value, like module_delta
        return rows

    @Slot(str)
    def exportDeltaBest(self, path: str = ""):
        """Use recorded lap as delta best reference of its track (former file kept as backup)"""
        from ...userfile.delta_best import load_delta_best_file

        path = path or self.reference_key
        if path not in {entry.file.path for entry in self.entries}:
            return
        lap = self.read_lap(path)
        lap_time = lap_time_of(os.path.basename(path)) or (lap.lap_time if lap is not None else 0.0)
        if lap is None or lap_time <= 0 or "lap_time" not in lap.columns:
            self.set_status(tr("This lap has no lap time: not usable as delta best."))
            return
        target = self.delta_best_file(path)
        name = os.path.splitext(os.path.basename(target))[0]
        current = load_delta_best_file(f"{os.path.dirname(target)}/", name, ((), 0.0))[1]
        message = trm(f"Use <b>{html.escape(lap_label(os.path.basename(path)))}</b> as delta best of "
                      f"<b>{html.escape(name)}</b>?")
        if current > 0:
            message += "<br>" + trm(f"Current delta best: {format_laptime(current)} (kept as backup file)")
        confirm = QMessageBox.question(
            self._window, tr("Delta Best"), message,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self.write_delta_best(path, lap, lap_time):
            self.set_status(trm(f"Delta best of {html.escape(name)}: {format_laptime(lap_time)} "
                                "(used next time you drive)"))

    def write_delta_best(self, path: str, lap: LapData, lap_time: float) -> bool:
        """Write delta best file of lap track, former file copied to .bak"""
        target = self.delta_best_file(path)
        rows = self.delta_best_rows(lap, lap_time)
        if len(rows) < 12:
            self.set_status(tr("This lap has no lap time: not usable as delta best."))
            return False
        temp = f"{target}.tmp"
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                shutil.copy2(target, f"{target}.bak")
            with open(temp, "w", newline="", encoding="utf-8") as file:
                csv.writer(file).writerows(rows)
            os.replace(temp, target)
        except OSError as error:
            logger.error("LAP VIEWER: unable to save delta best %s: %s", target, error)
            self.set_status(trm(f"Unable to save delta best: {error}"))
            with suppress(OSError):
                os.remove(temp)
            return False
        return True

    @Slot(str, bool)
    def keepLap(self, path: str, keep: bool):
        """Kept lap is never removed by recorder (oldest laps over limit are)"""
        set_mark(path, kept=keep)
        self.marks_changed(path)

    def marks_changed(self, path: str):
        self._marks.pop(os.path.dirname(path), None)
        self.fill_list()
        self.update_list_state(self.data.laps)

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
            self._pending_delete.extend(path for path in reading if path not in self._pending_delete)
            paths = [path for path in paths if path not in self._loaded_paths]
        if paths:
            self.apply_delete(paths)

    def trash_folder(self) -> str:
        """New trash batch folder (deletion time)"""
        return os.path.join(self.folder, TRASH_FOLDER, time.strftime("%Y-%m-%d %H-%M-%S"))

    def apply_delete(self, paths: list[str]):
        """Move laps to trash, forget their caches, undo kept"""
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
            moved.append((path, target, mark, path in self.checked))
        if not moved:
            return
        gone = {path for path, _, _, _ in moved}
        for path in gone:
            self._marks.pop(os.path.dirname(path), None)
            self._lap_cache.pop(path, None)
        self.entries = [entry for entry in self.entries if entry.file.path not in gone]
        self.checked -= gone
        if self.reference_key in gone:
            self.reference_key = ""
        self._undo = moved
        self.undoChanged.emit()
        self.set_status(trm(f"{len(moved)} lap(s) moved to trash"))
        self.fill_list()
        self.load_laps()

    @Property(str, notify=undoChanged)
    def undoText(self) -> str:
        """Undo button text, empty if nothing to restore"""
        return trm(f"Undo delete ({len(self._undo)})") if self._undo else ""

    @Slot()
    def undoDelete(self):
        """Restore last deleted laps from trash (marks & check state too)"""
        if not self._undo:
            return
        restored = []
        for path, target, mark, checked in self._undo:
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
            for folder in (os.path.dirname(target), os.path.dirname(os.path.dirname(target))):
                with suppress(OSError):  # trash track & batch folders removed once empty (never above)
                    os.rmdir(folder)
        self._undo = []
        self.undoChanged.emit()
        self._marks.clear()
        if self._track:
            self.entries = [LapEntry(lap, self.lap_info(lap.path)) for lap in list_laps(self.folder, self._track)]
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
            self._marks.clear()
            self.fill_list()
            self.update_list_state(self.data.laps)

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
            self._marks.clear()
            self.fill_list()
            self.update_list_state(self.data.laps)
        elif action == "delete":
            self.deleteLaps(paths)

    # Added laps: other folders, MoTeC logs, imported laps library
    @Slot()
    def addFiles(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self._window, tr("Add File..."), self.folder,
            f"{tr('Laps')} (*.csv *.csv.gz *.ld);;Modern Tiny Pedals Lap (*.csv *.csv.gz);;MoTeC i2 (*.ld)")
        paths: list[str] = []
        imported: list[str] = []
        for filename in filenames:
            if filename.lower().endswith(".ld"):  # MoTeC log: complete laps converted to lap files
                laps = [os.path.normpath(path) for path in self.import_motec(filename)]
                imported.extend(laps)
                paths.extend(laps)
            else:
                paths.append(filename)
        self.add_external(paths, imported)

    def import_motec(self, filename: str) -> list[str]:
        """Import complete laps of MoTeC .ld file, returns lap file paths"""
        try:
            paths = import_ld_file(filename, os.path.join(self.folder, IMPORT_FOLDER))
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to import %s: %s", filename, error)
            self.set_status(trm(f"Unable to import MoTeC file: {error}"))
            return []
        if not paths:
            self.set_status(trm(f"No complete lap in: {os.path.basename(filename)}"))
        return paths

    def add_external(self, lap_paths: list[str], reference_from: list[str] | None = None):
        """Show laps from other folders, fastest of reference_from laps set as reference"""
        known = {entry.file.path for entry in self.all_entries()}
        added = []
        for lap_path in lap_paths:
            path = os.path.normpath(lap_path)
            if path in known or path in added:
                continue
            name = os.path.basename(path)
            self.external.append(LapEntry(
                LapFile(name, path, is_valid_name(name), lap_time_of(name)), self.lap_info(path), external=True))
            added.append(path)
        self.checked.update(added)
        if reference_from:  # compare own laps with fastest imported lap
            self.reference_key = os.path.normpath(min(
                reference_from, key=lambda path: lap_time_of(os.path.basename(path)) or float("inf")))
        if added or reference_from:
            self.fill_list()
            self.load_laps()

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
        self.fill_list()
        self.load_laps()

    # Export
    @Slot(str)
    def exportMotec(self, path: str = ""):
        """Export lap (reference lap by default) to MoTeC .ld file"""
        path = path or self.reference_key
        lap = self.read_lap(path) if path else None
        if lap is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self._window, tr("Export MoTeC..."), lap_stem(path) + ".ld", "MoTeC i2 (*.ld)")
        if filename and self.export_file(path, lap, filename):
            self.set_status(trm(f"Exported: {os.path.basename(filename)}"))

    @Slot(bool)
    def exportMotecMany(self, whole_track: bool):
        """Export displayed laps, or every lap of track, to folder (in background)"""
        paths = [entry.file.path for entry in self.entries] if whole_track else self.ordered_checked()
        if not paths:
            return
        folder = QFileDialog.getExistingDirectory(self._window, tr("Export MoTeC..."), self.folder)
        if folder:
            self.export_many(paths, folder)

    def export_many(self, paths: list[str], folder: str, background: bool = True) -> int:
        """Export laps to folder (laps read from binary cache), one worker process job per lap if background
        (window stays responsive), returns count if not"""
        jobs = [(path, os.path.join(folder, os.path.basename(lap_stem(path)) + ".ld"),
                 os.path.basename(os.path.dirname(path)).split(" - ")[0]) for path in paths]
        if not background:
            results = [export_lap_job(self.folder, path, target, venue) for path, target, venue in jobs]
            self.set_status(self.export_message(folder, results))
            return results.count("")
        errors: list[str] = []
        self._exports += len(jobs)

        def exported(error):
            self._exports -= 1
            errors.append(tr("Unknown error") if error is None else error)  # None: job failed (logged)
            if len(errors) < len(jobs):
                self.set_status(trm(f"Exporting {len(errors)}/{len(jobs)} laps..."), False)
            else:
                self.set_status(self.export_message(folder, errors))

        self.set_status(trm(f"Exporting 0/{len(jobs)} laps..."), False)
        for path, target, venue in jobs:
            self.run_process_job("MoTeC export", exported, export_lap_job, self.folder, path, target, venue)
        return 0

    @staticmethod
    def export_message(folder: str, errors: list[str]) -> str:
        """Exported file count, then failed count & first reason if any failed"""
        message = trm(f"Exported <b>{errors.count('')}</b> file(s) to: {folder}")
        failed = [error for error in errors if error]
        if failed:
            message += " · " + trm(f"{len(failed)} failed: {html.escape(failed[0])}")
        return message

    def export_file(self, path: str, lap: LapData, filename: str) -> bool:
        track = os.path.basename(os.path.dirname(path)).split(" - ")[0]
        try:
            export_lap(lap, filename, venue=track, timestamp=os.path.getmtime(path))
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self.set_status(trm(f"Unable to export lap: {error}"))
            return False
        return True

    @Slot()
    def exportCsv(self):
        """Displayed charts of displayed laps to CSV, every meter"""
        if not self.data.laps:
            self.set_status(tr("Check laps to export first."))
            return
        default = os.path.join(self.folder, f"{self._track or 'laps'}.csv")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename:
            self.write_csv(filename, background=True)

    def csv_channels(self) -> list[Channel]:
        """Displayed channels, combined panels as their sub-channels"""
        channels: list[Channel] = []
        for column in self.visible:
            for part in CHANNEL_MAP[column].parts or (column,):
                if CHANNEL_MAP[part] not in channels:
                    channels.append(CHANNEL_MAP[part])
        return channels

    def write_csv(self, filename: str, decimal_point: str = "", start: float = 0.0, end: float = -1.0,
                  background: bool = False) -> bool:
        """Distance, then each displayed channel of each displayed lap, resampled every meter (start to end)

        Number format follows system locale (decimal comma & semicolon separator in French), for Excel.
        """
        decimal = decimal_point or QLocale.system().decimalPoint() or "."
        length = max((lap.data.distance[-1] * self.data.scale_of(lap) for lap in self.data.laps if len(lap.data)),
                     default=0.0)
        last = int(min(end, length) if end >= 0 else length)
        grid = [float(meter) for meter in range(max(math.ceil(start), 0), last + 1)]
        header = [f"{tr('Distance')} (m)"]
        columns: list[list[float | None]] = []
        for lap in self.data.laps:
            for channel in self.csv_channels():
                unit = self.data.unit_of(channel)
                header.append(f"{lap.label} - {channel_title(channel)}" + (f" ({unit})" if unit else ""))
                xs, ys = self.data.series(channel, lap, time_axis=False)
                if len(xs) < 2:
                    columns.append([None] * len(grid))
                    continue
                low, high = bisect.bisect_left(grid, xs[0]), bisect.bisect_right(grid, xs[-1])
                inside = resample_sorted(xs, ys, grid[low:high])  # one pass, no search per meter
                columns.append([None] * low + inside + [None] * (len(grid) - high))
        if background:  # numbers written by worker process (page stays responsive)
            name = html.escape(os.path.basename(filename))

            def written(error):
                self._exports -= 1
                if error is None or error:  # None: job failed (logged)
                    self.set_status(trm(f"Unable to export lap: {html.escape(error or tr('Unknown error'))}"))
                else:
                    self.set_status(trm(f"Exported: {name}"))

            self._exports += 1
            self.run_process_job("CSV export", written, write_lap_csv, filename, header, grid, columns, decimal)
            return True
        error = write_lap_csv(filename, header, grid, columns, decimal)
        if error:
            self.set_status(trm(f"Unable to export lap: {error}"))
            return False
        return True

    @Slot("QVariant")
    def saveImage(self, image):
        """Save page picture (charts, map) to PNG file"""
        if not isinstance(image, QImage) or image.isNull():
            return
        default = os.path.join(self.folder, f"{self._track or 'laps'}.png")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export Picture..."), default, "PNG (*.png)")
        if filename:
            if image.save(filename, b"PNG"):
                self.set_status(trm(f"Exported: {html.escape(os.path.basename(filename))}"))
            else:
                self.set_status(trm(f"Unable to save picture: {html.escape(os.path.basename(filename))}"))

    @Slot("QVariant")
    def copyImage(self, image):
        """Page picture to clipboard (paste in Discord...)"""
        if isinstance(image, QImage) and not image.isNull():
            QApplication.clipboard().setImage(image)
            self.set_status(tr("Picture copied to clipboard."))

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
        self.store_lap(path, lap)
        return lap

    def store_lap(self, path: str, lap: LapData | None):
        """Keep loaded lap, oldest laps forgotten over cache size (a lap takes several MB in memory)"""
        self._lap_cache[path] = lap
        try:
            self._cache_mtime[path] = os.path.getmtime(path)
        except OSError:
            self._cache_mtime.pop(path, None)
        limit = max(lap_viewer.LAP_CACHE_SIZE, len(self.checked))
        while len(self._lap_cache) > limit:
            oldest = next(iter(self._lap_cache))
            self._lap_cache.pop(oldest)
            self._cache_mtime.pop(oldest, None)

    def load_in_background(self, paths: list[str]):
        """Read laps in a thread, charts updated once all are loaded (page stays responsive)"""
        if self._loader is not None:
            return  # current selection shown once loaded (check_background_load)
        results: dict[str, LapData | None] = {}

        def loading():
            for path in paths:
                try:
                    results[path] = self.load_lap_file(path)
                except (OSError, ValueError) as error:
                    logger.error("LAP VIEWER: unable to load %s: %s", path, error)
                    results[path] = None

        self._loaded = results
        self._loaded_paths = set(paths)
        self._load_total = len(paths)
        self._load_message = self._status
        self._loader = threading.Thread(target=loading, daemon=True, name="Lap viewer loading")
        self._loader.start()
        self._load_timer.start()
        self.set_status(trm(f"Loading {len(paths)} lap{'s' if len(paths) > 1 else ''}..."), False)

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
        failed = [path for path, lap in self._loaded.items() if lap is None]
        for path, lap in self._loaded.items():
            self.store_lap(path, lap)
        self._loaded = {}
        if failed:
            self.set_status(trm(f"Unable to load lap: {html.escape(os.path.basename(failed[0]))}"))
        else:  # message shown before loading (new lap) shown again
            self.set_status(self._load_message)
        if self._pending_delete:  # deleted while loading
            paths, self._pending_delete = self._pending_delete, []
            self.apply_delete(paths)
            return
        self.load_laps()

    def is_loading(self) -> bool:
        """Laps loading or exporting in background"""
        return self._loader is not None or self._exports > 0

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
        if paths and self.reference_key not in paths:
            self.reference_key = paths[0]
        ordered = sorted(paths, key=lambda path: path != self.reference_key)  # reference first
        missing = [path for path in ordered if path not in self._lap_cache]
        if self._loader is not None or len(missing) >= lap_viewer.BACKGROUND_LOAD_COUNT:
            self.update_list_state(self.data.laps)
            self.load_in_background(missing)
            return
        self.save_selection(paths)
        entries = {entry.file.path: entry for entry in self.all_entries()}
        loaded = [(path, self.read_lap(path)) for path in ordered]
        self._failed = {path for path, lap_data in loaded if lap_data is None}
        slots = self.assign_colors([path for path, lap_data in loaded if lap_data is not None])
        laps = [
            PlotLap(path, self.entry_label(entries.get(path), path), lap_data, lap_color(slots[path]),
                    self.is_clean(entries.get(path), path, lap_data))
            for path, lap_data in loaded if lap_data is not None
        ]
        self.build_labels(laps)
        self.data.set_laps(laps, self.reference_key)
        self.apply_track_sectors()
        self.update_list_state(laps)
        vehicles = sorted({str(lap.data.meta.get("vehicle")) for lap in laps if lap.data.meta.get("vehicle")})
        self._warning = trm(f"Laps from different vehicles: {', '.join(vehicles)}") if len(vehicles) > 1 else ""
        self.rebuild_chart()
        if self._restore_view is not None:
            self.viewRestored.emit(*self._restore_view)
            self._restore_view = None

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
        """Check marks, lap colors, reference & errors in lap list (in place: list keeps scroll position)"""
        colors = {lap.key: lap.color.name() for lap in laps}
        self.lap_model.update_rows(lambda row: {
            "checked": row["path"] in self.checked,
            "reference": bool(row["path"]) and row["path"] == self.reference_key,
            "color": colors.get(row["path"], ""),
            "error": row["path"] in self._failed and row["path"] in self.checked,
        })

    # Memory release while page is in background
    def page_hidden(self):
        self._release_timer.start()

    def page_shown(self):
        self._release_timer.stop()
        if self._released:  # same laps & zoom as before
            self._released = False
            view = self._released_view
            self._restore_view = view if view[1] > view[0] else None
            self.load_laps()

    @Slot()
    def release_laps(self):
        """Free memory of loaded laps (several MB each) while page is hidden, see page_shown"""
        if self._window.isVisible() or self._released or self._loader is not None:
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
        if index == 1:  # G circle: zoomed part of charts (not followed while hidden)
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
            self.chartChanged.emit()

    @Slot()
    def resetPanelWeights(self):
        self._weights = {}
        save_viewer_setting(self.folder, panel_weights={})
        self.channels_updated(save=False)

    # Charts
    def series_key(self, lap: PlotLap, channel: Channel) -> str:
        return f"{self.prefix}{lap.key}|{channel.column}|{self.data.signature(channel)}"

    def rebuild_chart(self):
        """Vertices & properties of every view from displayed laps"""
        entries = {entry.file.path: entry for entry in self.all_entries()}
        self._legend = [
            {"key": lap.key, "label": self.short_label(lap.key), "full": lap.label,
             "color": lap.color.name(), "reference": lap is self.data.reference, "clean": lap.clean,
             "tip": self.entry_conditions(entries[lap.key]) if lap.key in entries
             else self.entry_conditions(LapEntry(LapFile("", lap.key, True), lap.data.meta))}
            for lap in self.data.laps
        ]
        self.legend_model.sync(self._legend)
        self.update_base()
        self.build_panels()
        self.build_overview()
        self.build_official()
        self.build_corners()
        self.build_map()
        self.build_gcircle()
        self.drop_unused_vertices()
        self.bump_revision()
        self.chartChanged.emit()
        self.mapChanged.emit()
        self.channelsChanged.emit()  # channels available in shown laps
        self.pinChanged.emit()

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
                envelope = f"{self.prefix}envelope|{column}|{self.data.signature(channel)}|{len(laps)}"
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
            step = nice_step(high - low, 5)
            ticks = [] if channel.fixed_range in PERCENT_RANGES else [  # value grid between range limits
                {"value": value, "text": format_axis_value(channel, value, span)}
                for value in (math.ceil(low / step) * step + index * step for index in range(10))
                if low < value < high and value - low > step * 0.25 and high - value > step * 0.25
            ]
            if channel.fixed_range in PERCENT_RANGES:  # pedals & steering: quarters
                ticks = [{"value": low + (high - low) * quarter / 4,
                          "text": format_axis_value(channel, low + (high - low) * quarter / 4, span)}
                         for quarter in (1, 2, 3)]
            panels.append({
                "ticks": ticks,
                "column": column, "title": channel_title(channel), "unit": self.data.unit_of(channel),
                "weight": self._weights.get(column, channel.weight), "low": low, "high": high,
                "lowText": format_axis_value(channel, low, span), "highText": format_axis_value(channel, high, span),
                "zero": low < 0 < high, "percent": channel.fixed_range in PERCENT_RANGES, "series": series,
                "available": available, "note": note, "envelope": envelope,
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
        return f"{format_axis_time(x)} · {distance:.0f} m" if self.data.time_axis else f"{distance:.0f} m"

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
        """Everything shown at cursor in one call: title, chart values, map & G circle positions"""
        self.build_trails(x)
        return {"title": self.cursorTitle(x), "values": self.cursorValues(x), "map": self.mapCursor(x),
                "g": self.gCursor(x)}

    def build_trails(self, x: float):
        """Last seconds of each lap behind cursor, fading in (trail option)"""
        if not self._map or not self._map_options.get("trail") or not self._map_shown:
            return
        meters_per_pixel = self._map_view[2]
        for (line, lap), keys in zip(self._map_lines, self._map["lines"]):
            distances, times = self.data.lap_times(lap)
            if not distances:
                continue
            end = self.data.lap_distance_at_x(lap, x)
            start = interpolate(times, distances, interpolate(distances, times, end) - TRAIL_SECONDS)
            xs, ys, alphas = lap_map.trail(line, start, end)
            bright = lap.color.lighter(165)  # stands out over its own driving line
            VertexStore.set(keys["trail"], colored_band(xs, ys, [bright] * len(xs), meters_per_pixel * 3.2, alphas))
        self._trail_revision += 1
        self.trailChanged.emit()

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

    @Slot(float, str, result=dict)
    def placementAt(self, x: float, lap_key: str = "") -> dict:
        """Lap (highlighted, else reference) across track at axis position: room to each edge & track position"""
        lap = next((lap for lap in self.data.laps if lap.key == lap_key), self.data.reference)
        if lap is None:
            return {}
        distance = self.data.lap_distance_at_x(lap, x)
        found = self.lap_placement(lap, distance)
        if found is None:
            return {}
        left, right, percent = found
        side = tr("left") if percent > 0 else tr("right")
        texts = [f"{distance:.0f} m", f"{abs(percent):.0f}% {side}" if abs(percent) >= 5 else tr("track middle")]
        for room, label in ((left, tr("Left edge")), (right, tr("Right edge"))):
            texts.append(f"{label} {room:.1f} m" if room >= 0 else f"{label} {tr('beyond')} {-room:.1f} m")
        return {"text": " · ".join(texts), "color": lap.color.name(), "out": left < 0 or right < 0}

    @Slot(float, float, result=list)
    def passageTimes(self, start: float, end: float) -> list[dict]:
        """Time of each shown lap between markers A & B, gap to fastest of them (fastest flagged)"""
        rows = self.data.range_stats(start, end, [])
        if not rows:
            return []
        best = min(row["time"] for row in rows)
        return [{"label": self.short_label(row["lap"].key), "color": row["lap"].color.name(),
                 "time": f"{row['time']:.3f}", "gap": signed(row["time"] - best, 3) if row["time"] > best else "",
                 "best": row["time"] <= best} for row in rows]

    @Slot(float, float)
    def exportPassageCsv(self, start: float, end: float):
        """Displayed charts of displayed laps between markers A & B to CSV, every meter"""
        if not self.data.laps:
            self.set_status(tr("Check laps to export first."))
            return
        low, high = sorted((self.data.distance_at_x(start), self.data.distance_at_x(end)))
        default = os.path.join(self.folder, f"{self._track or 'laps'} {low:.0f}-{high:.0f}m.csv")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename:
            self.write_csv(filename, "", low, high, background=True)

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
                         "time": f"{row['time']:.3f} s", "gap": gap, "distance": f"{row['distance']:.0f} m"})
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

    # Session: every lap of a session of current track (session tab)
    def session_groups(self) -> list[tuple[str, str, list[LapEntry]]]:
        """Sessions of current track, newest first: key, title, laps in driving order"""
        groups = []
        for group in self.track_sessions():
            header = self.session_row(group, False)
            groups.append((header["session"], f"{header['title']} · {len(group)}", group))
        return groups

    @Property(list, notify=sessionChanged)
    def sessions(self) -> list[dict]:
        return [{"key": key, "title": title} for key, title, _ in self.session_groups()]

    @Property(str, notify=sessionChanged)
    def sessionKey(self) -> str:
        groups = self.session_groups()
        keys = [key for key, _, _ in groups]
        if self._session_key in keys:
            return self._session_key
        for key, _, group in groups:  # session of reference lap, else newest
            if any(entry.file.path == self.reference_key for entry in group):
                return key
        return keys[0] if keys else ""

    @Slot(str)
    def setSession(self, key: str):
        self._session_key = key
        self.sessionChanged.emit()
        self.start_session_job()

    @Property(dict, notify=sessionChanged)
    def sessionData(self) -> dict:
        """Laps of shown session: number, time, valid, fuel & tyre wear used, off tracks, track limits, shown"""
        key = self.sessionKey
        group = next((laps for name, _, laps in self.session_groups() if name == key), [])
        colors = {lap.key: lap.color.name() for lap in self.data.laps}
        rows = []
        for entry in group:
            info = entry.info
            extra = self._session_extra.get(entry.file.path, (0.0, {}))[1]
            fuel = -1.0
            start, end = info.get("fuel_start"), info.get("fuel_end")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and start >= end:
                fuel = float(start - end)
            wear = extra.get("wear", -1.0)
            wear_start, wear_end = info.get("wear_start"), info.get("wear_end")
            if isinstance(wear_start, list) and isinstance(wear_end, list) and len(wear_start) == len(wear_end) == 4:
                wear = sum(first - last for first, last in zip(wear_start, wear_end)) / 4
            temperature = info.get("track_temperature")
            rows.append({
                "path": entry.file.path, "number": lap_number_of(entry.file.filename),
                "time": entry.file.lap_time, "text": format_laptime(entry.file.lap_time),
                "valid": entry.file.valid and info.get("kind", "lap") == "lap", "kind": str(info.get("kind", "lap")),
                "fuel": fuel, "wear": wear,
                "temp": float(temperature) if isinstance(temperature, (int, float)) else None,
                "offtrack": extra.get("offtrack", -1), "limits": extra.get("limits", -1),
                "shown": entry.file.path in colors, "color": colors.get(entry.file.path, ""),
                "reference": entry.file.path == self.reference_key,
            })
        valid = [row["time"] for row in rows if row["valid"] and row["time"] > 0]
        fuel_unit = lap_viewer.display_units()["fuel"]
        return {
            "laps": rows, "best": min(valid, default=0.0), "worst": max(valid, default=0.0),
            "busy": self._session_busy, "fuelUnit": fuel_unit[1],
            "fuelScale": fuel_unit[0](1.0) if fuel_unit[0] else 1.0,
            "trend": self.session_trend(rows, group),
        }

    @staticmethod
    def session_trend(rows: list[dict], group: list[LapEntry]) -> dict:
        """Long run of session: clean laps without outliers (traffic, mistakes), pace, lap time trend per lap,
        per % of tyre wear; outlier laps flagged in rows"""
        clean = [(index, row["time"]) for index, row in enumerate(rows) if row["valid"] and row["time"] > 0]
        for row in rows:
            row["outlier"] = False
        if len(clean) < 3:
            return {}
        times = sorted(lap_time for _, lap_time in clean)
        quarter, three_quarters = times[len(times) // 4], times[(len(times) * 3) // 4]
        limit = min(three_quarters + 1.5 * (three_quarters - quarter), times[0] * 1.07)
        paced = [(index, lap_time) for index, lap_time in clean if lap_time <= limit + 1e-6]
        for index, lap_time in clean:
            if lap_time > limit + 1e-6:
                rows[index]["outlier"] = True
        result: dict = {"pace": sum(lap_time for _, lap_time in paced) / len(paced), "used": len(paced),
                        "left": len(clean) - len(paced)}
        if len(paced) >= 4:
            slope, intercept = least_squares([(float(index), lap_time) for index, lap_time in paced])
            first, last = paced[0][0], paced[-1][0]
            result.update({"slope": slope, "x0": first, "y0": intercept + slope * first, "x1": last,
                           "y1": intercept + slope * last})
            worn = []  # tread worn at lap start (%), lap time
            for index, lap_time in paced:
                start = group[index].info.get("wear_start") if index < len(group) else None
                if isinstance(start, list) and len(start) == 4 and all(isinstance(value, (int, float)) for value in start):
                    worn.append((100 - sum(start) / 4, lap_time))
            if len(worn) >= 4 and max(value for value, _ in worn) - min(value for value, _ in worn) >= 1:
                result["wearSlope"] = least_squares(worn)[0]
        return result

    def start_session_job(self):
        """Tyre wear, off tracks & track limits of session laps read from lap files in background (cached)"""
        if self._session_busy:
            return
        key = self.sessionKey
        group = next((laps for name, _, laps in self.session_groups() if name == key), [])
        todo = []
        for entry in group:
            try:
                mtime = os.path.getmtime(entry.file.path)
            except OSError:
                continue
            cached = self._session_extra.get(entry.file.path)
            if cached is None or cached[0] != mtime:
                todo.append((entry.file.path, mtime))
        if not todo:
            return
        self._session_busy = True

        def done(found):
            self._session_busy = False
            if found:
                self._session_extra.update(found)
            self.sessionChanged.emit()

        self.run_process_job("session", done, session_values, self.folder, todo)

    # Corners
    def compared_lap(self) -> PlotLap | None:
        """Lap compared corner by corner & on gain map: chosen lap if shown, else first compared lap"""
        compared = self.data.compared()
        return next((lap for lap in compared if lap.key == self._compare_key), compared[0] if compared else None)

    @Slot(str)
    def setCompareKey(self, key: str):
        if key != self._compare_key:
            self._compare_key = key
            self.build_corners()
            if self._map:
                self._map["corners"] = self.map_corner_points()
                self._map["sectors"] = self.map_sector_labels()
                if self._map_mode in ("gain", "line"):
                    self.build_colored_line(self._map_view[2])
                    self.bump_revision()
            self.chartChanged.emit()

    @Slot(str)
    def setCornerSort(self, sort: str):
        if sort in CORNER_SORTS and sort != self._corner_sort:
            self._corner_sort = sort
            save_viewer_setting(self.folder, corner_sort=sort)
            self.build_corners()
            self.chartChanged.emit()

    def build_corners(self):
        """Corner by corner comparison of chosen compared lap with reference lap

        Time: positive = compared lap slower. Braking: positive = brakes later.
        Full throttle: negative = full throttle earlier.
        """
        reference = self.data.reference.data if self.data.reference else None
        compared_lap = self.compared_lap()
        other = compared_lap.data if compared_lap is not None else None
        scales = tuple(self.data.scale_of(lap) for lap in self.data.laps)
        key = (reference, other, self._hysteresis, tuple(lap.data for lap in self.data.laps), scales,
               tuple(lap.clean for lap in self.data.laps))
        if not keys_match(self._corner_key, key):
            self._corner_key = key
            self._corner_rows = compare_corners(
                self.resampled(self.data.reference), self.resampled(compared_lap) if compared_lap is not None else None,
                self._hysteresis) if self.data.reference is not None else []
            self._ideal = self.clean_ideal_lap()
        convert = self.data.units["speed"][0]

        def speed(value: float) -> float:
            return convert(value) if convert is not None else value

        def judged(delta: float) -> str:
            return COLOR_LOSS if delta > 0.005 else COLOR_GAIN if delta < -0.005 else ""

        def more_is_worse(ref_value: float, other_value: float) -> str:
            if other_value - ref_value >= 0.1:
                return COLOR_LOSS
            if ref_value - other_value >= 0.1:
                return COLOR_GAIN
            return ""

        def faster_is_better(ref_value: float, other_value: float) -> str:
            if other_value - ref_value >= 1:
                return COLOR_GAIN
            if ref_value - other_value >= 1:
                return COLOR_LOSS
            return ""

        best_of = self.corner_best_laps()
        rows = []
        for index, row in enumerate(self._corner_rows):
            ref, comp = row.reference, row.compared
            item: dict[str, Any] = {
                "index": index, "label": self.row_label(row), "apex": f"{row.corner.apex:.0f} m",
                "kind": "corner", "best": best_of.get(index, ""),
            }
            if comp is None:  # reference lap values only
                item.update({
                    "time": f"{ref.time:.2f} s", "timeColor": "", "bar": 0.0, "speed": f"{speed(ref.min_speed):.0f}",
                    "speedColor": "", "brake": f"{ref.brake_point:.0f} m" if ref.brake_point >= 0 else "—",
                    "throttle": f"{ref.throttle_point:.0f} m" if ref.throttle_point >= 0 else "—",
                    "trail": f"{ref.trail_braking:.1f} s", "coast": f"{ref.coasting:.1f} s",
                    "overlap": f"{ref.overlap:.1f} s", "coastColor": "", "overlapColor": "",
                    "entry": f"{speed(ref.entry_speed):.0f}", "exit": f"{speed(ref.exit_speed):.0f}",
                    "entryColor": "", "exitColor": "",
                    "gear": str(ref.apex_gear) if ref.apex_gear else "—", "peakBrake": f"{ref.peak_brake * 100:.0f}%",
                })
            else:
                delta = comp.time - ref.time
                speed_delta = speed(comp.min_speed) - speed(ref.min_speed)
                item.update({
                    "time": signed(delta, 2), "timeColor": judged(delta), "bar": delta,
                    "speed": f"{speed(ref.min_speed):.0f} / {speed(comp.min_speed):.0f}",
                    "speedColor": COLOR_GAIN if speed_delta >= 1 else COLOR_LOSS if speed_delta <= -1 else "",
                    "brake": signed(comp.brake_point - ref.brake_point, 0, " m")
                    if ref.brake_point >= 0 and comp.brake_point >= 0 else "—",
                    "throttle": signed(comp.throttle_point - ref.throttle_point, 0, " m")
                    if ref.throttle_point >= 0 and comp.throttle_point >= 0 else "—",
                    # Driving: trail braking (no judgement), coasting & overlap (more = time lost)
                    "trail": f"{ref.trail_braking:.1f} / {comp.trail_braking:.1f} s",
                    "coast": f"{ref.coasting:.1f} / {comp.coasting:.1f} s",
                    "overlap": f"{ref.overlap:.1f} / {comp.overlap:.1f} s",
                    "coastColor": more_is_worse(ref.coasting, comp.coasting),
                    "overlapColor": more_is_worse(ref.overlap, comp.overlap),
                    "entry": f"{speed(ref.entry_speed):.0f} / {speed(comp.entry_speed):.0f}",
                    "exit": f"{speed(ref.exit_speed):.0f} / {speed(comp.exit_speed):.0f}",
                    "entryColor": faster_is_better(speed(ref.entry_speed), speed(comp.entry_speed)),
                    "exitColor": faster_is_better(speed(ref.exit_speed), speed(comp.exit_speed)),
                    "gear": f"{ref.apex_gear or '—'} / {comp.apex_gear or '—'}",
                    "peakBrake": f"{ref.peak_brake * 100:.0f} / {comp.peak_brake * 100:.0f}%",
                })
            rows.append(item)
        if self._corner_sort == "loss":
            rows.sort(key=lambda item: -item["bar"])
        if reference is not None and other is not None and self._corner_rows:  # corners + straights = lap delta
            for text, kind, delta in ((tr("Straights"), "sum", straights_delta(self._corner_rows, reference, other)),
                                      (tr("Total"), "total", lap_time_delta(reference, other))):
                rows.append({"index": -1, "label": text, "apex": "", "kind": kind, "time": signed(delta, 2),
                             "timeColor": judged(delta), "bar": delta})
        if self._ideal is not None and reference is not None:
            gap = self._ideal.time - reference.lap_time
            rows.append({"index": -1, "label": tr("Ideal Lap"), "apex": "", "speed": format_laptime(self._ideal.time),
                         "speedColor": "", "kind": "ideal", "time": signed(gap, 2), "timeColor": judged(gap),
                         "bar": gap})
        self._corners = rows
        self.build_coaching()
        self.build_corner_marks()

    def clean_ideal_lap(self) -> IdealLap | None:
        """Ideal lap (fastest lap in each corner & straight) among clean shown laps: invalid, out & in laps
        (cut track) never count; best lap indexes are shown lap indexes"""
        clean = [index for index, lap in enumerate(self.data.laps) if lap.clean]
        found = ideal_lap([self.resampled(self.data.laps[index]) for index in clean],
                          [row.corner for row in self._corner_rows])
        if found is None:
            return None
        return found._replace(best=[clean[position] for position in found.best])

    def build_coaching(self):
        """Corners where compared lap loses most time against reference lap & likely causes (corner table)"""
        convert, unit = self.data.units["speed"]

        def speed(value: float) -> float:
            return convert(value) if convert is not None else value

        texts = {
            "brake_early": lambda value: trm(f"Brakes {value:.0f} m earlier"),
            "brake_late": lambda value: trm(f"Brakes {value:.0f} m later, runs wide"),
            "min_speed": lambda value: trm(f"Minimum speed {speed(value):.0f} {unit} lower"),
            "throttle_late": lambda value: trm(f"Full throttle {value:.0f} m later"),
            "coasting": lambda value: trm(f"Coasting {value:.1f} s longer"),
            "overlap": lambda value: trm(f"Throttle & brake together {value:.1f} s longer"),
            "exit_speed": lambda value: trm(f"Exit speed {speed(value):.0f} {unit} lower"),
        }
        self._coaching = [
            {"index": tip.row, "label": self.row_label(self._corner_rows[tip.row]), "loss": signed(tip.loss, 2, " s"),
             "causes": [texts[kind](value) for kind, value in tip.causes[:3]]
             or [tr("No clear cause: compare traces of this corner")]}
            for tip in coaching_tips(self._corner_rows)
        ]

    @Property(list, notify=chartChanged)
    def coaching(self) -> list[dict]:
        """Corners where compared lap loses most time (up to 3): row index, name, time lost, causes"""
        return self._coaching

    @Property(str, notify=chartChanged)
    def coachingLap(self) -> str:
        lap = self.compared_lap()
        return self.short_label(lap.key) if lap is not None else ""

    def corner_best_laps(self) -> dict[int, str]:
        """Fastest lap through each corner (ideal lap), corner row index: short lap name"""
        ideal = self._ideal
        if ideal is None:
            return {}
        result = {}
        for index, row in enumerate(self._corner_rows):
            if row.corner.start in ideal.bounds:
                part = ideal.bounds.index(row.corner.start)
                if part < len(ideal.best):
                    result[index] = self.short_label(self.data.laps[ideal.best[part]].key)
        return result

    def build_corner_marks(self):
        """Corner numbers on charts: official corners of circuit, else corners found on reference lap"""
        if self._official:
            self._corner_marks = [
                {"x": self.data.x_at_distance(corner.distance), "label": self.official_text(corner.label),
                 "distance": corner.distance}
                for corner in self._official
            ]
            return
        self._corner_marks = [
            {"x": self.data.x_at_distance(row.corner.apex), "label": corner_label(row.corner.number),
             "distance": row.corner.apex}
            for row in self._corner_rows
        ]

    # Official corners
    def track_name(self) -> str:
        """Track of displayed laps, from lap info or older lap files folder ("<track> - <class>")"""
        laps = self.data.laps
        if not laps:
            return ""
        track = str(laps[0].data.meta.get("track", ""))
        return track or os.path.basename(os.path.dirname(laps[0].key)).rsplit(" - ", 1)[0]

    def build_official(self):
        """Official corners of circuit placed on reference line (or track map file), once per reference lap"""
        reference = self.data.reference
        key = (reference.data if reference is not None else None, self.track_name())
        if self._official_key is not None and keys_match(self._official_key, key):
            return
        self._official_key = key
        self._official, self._official_numbered = [], True
        if reference is None:
            return
        line = self.lap_line(reference)
        if line is not None:
            distances, xs, ys = line.distances, line.xs, line.ys
        else:  # positions not recorded (imported log): track map file
            coords, dists, _ = load_track_map_file(cfg.path.track_map, self.track_name())
            if not coords or not dists:
                return
            nodes = sorted(zip((float(distance) for distance, _ in dists), coords))
            distances = [distance for distance, _ in nodes]
            xs = [float(coord[0]) for _, coord in nodes]
            ys = [float(coord[1]) for _, coord in nodes]
        self._official, self._official_numbered = track_corners(self.track_name(), distances, xs, ys)

    def official_text(self, label: str) -> str:
        """Official corner shown: "T5" ("V5" in French), or translated name"""
        return trm(f"T{label}") if self._official_numbered else tr(label)

    def official_in(self, row: CornerComparison) -> list[TrackCorner]:
        """Official corners inside corner found on reference lap"""
        return [corner for corner in self._official if row.corner.start <= corner.distance <= row.corner.end]

    def row_label(self, row: CornerComparison) -> str:
        """Corner found on reference lap named after official corners it covers: "T5", "T5-6" """
        if not self._official:
            return corner_label(row.corner.number)
        inside = self.official_in(row)
        if not inside:
            nearest = min(self._official, key=lambda corner: abs(corner.distance - row.corner.apex))
            if abs(nearest.distance - row.corner.apex) > 200:
                return "—"
            inside = [nearest]
        if len(inside) == 1:
            return self.official_text(inside[0].label)
        if self._official_numbered:
            return trm(f"T{inside[0].label}-{inside[-1].label}")
        return " / ".join(tr(corner.label) for corner in inside)

    @Slot(int, result=list)
    def cornerRange(self, index: int) -> list[float]:
        """Axis range of corner (zoom on it)"""
        if not 0 <= index < len(self._corner_rows):
            return []
        corner = self._corner_rows[index].corner
        return [self.data.x_at_distance(corner.start), self.data.x_at_distance(corner.end)]

    @Property(list, notify=chartChanged)
    def cornerRanges(self) -> list[list[float]]:
        """Axis range of every corner in lap order (previous / next corner keys)"""
        return [self.cornerRange(index) for index in range(len(self._corner_rows))]

    @Slot(int)
    def setHysteresis(self, value: int):
        if value != self._hysteresis:
            self._hysteresis = value
            save_viewer_setting(self.folder, corner_hysteresis=value)
            self.build_corners()
            if self._map:
                self._map["corners"] = self.map_corner_points()
                self._map["points"] = self.map_driving_points()
                self._band_cache = OrderedDict()
                self._band_generation += 1
                self._preview_step = math.nan
                self._band_cache_applied = False
                self.build_map_bands()
                self.bump_revision()
            self.chartChanged.emit()

    # Track map
    def track_outline(self) -> list[tuple[float, float]]:
        """Circuit coordinates from track map file (recorded by Mapping module), empty if none"""
        laps = self.data.laps
        if not laps:
            return []
        track = str(laps[0].data.meta.get("track", ""))
        if not track:  # older lap files: "<track> - <class>" folder
            track = os.path.basename(os.path.dirname(laps[0].key)).rsplit(" - ", 1)[0]
        if track not in self._outline_cache:
            coords, _, _ = load_track_map_file(cfg.path.track_map, track)
            self._outline_cache[track] = [(float(x), float(y)) for x, y in coords] if coords else []
        return self._outline_cache[track]

    def lap_line(self, lap: PlotLap) -> lap_map.MapLine | None:
        """Driving line of lap (not turned), computed once per loaded lap (official corners & map)"""
        cached = self._line_cache.get(lap.key)
        if cached is None or cached[0] is not lap.data:
            cached = (lap.data, lap_map.map_line(lap.data))
            self._line_cache = {key: value for key, value in self._line_cache.items()
                                if key in {shown.key for shown in self.data.laps}}
            self._line_cache[lap.key] = cached
        return cached[1]

    def map_angle(self, road: lap_map.MapLine) -> float:
        """Map rotation: auto orientation (longest extent along longest view side) & quarter turns

        Map drawn y down: positive angle turns clockwise on screen.
        Auto orientation turns the least possible from game orientation.
        """
        angle = self._map_quarters * math.pi / 2
        if self._map_auto_orient and len(road.xs) > 2:
            turn = -lap_map.principal_angle(road.xs, road.ys)  # -90 to 90 degrees
            if self._map_aspect < 1:  # tall view: longest extent vertical
                turn += math.pi / 2 if turn < 0 else -math.pi / 2
            angle += turn
        return angle

    def rotate_point(self, x: float, y: float) -> tuple[float, float]:
        if not self._map_angle:
            return x, y
        cos, sin = math.cos(self._map_angle), math.sin(self._map_angle)
        return x * cos - y * sin, x * sin + y * cos

    def build_map(self):
        """Circuit, driving lines, start & sector marks, corners, braking points of displayed laps"""
        lines = []
        for lap in self.data.laps:
            line = self.lap_line(lap)
            if line is not None:
                lines.append((line, lap))
        official = self.official_base(self.reference_length())
        outline = self.track_outline() if official is None else []
        if official is not None:  # official circuit from game
            road = official
        elif outline:
            road = lap_map.MapLine(list(range(len(outline))), [x for x, _ in outline], [y for _, y in outline])
        elif lines:
            road = lines[0][0]
        else:
            self._map_lines = []
            self._map = {}
            self.map_lap_model.sync([], "lap")
            return
        self._map_angle = self.map_angle(road)
        self._road = lap_map.rotate_line(road, self._map_angle)
        self._map_lines = [(self.turned_line(lap, line), lap) for line, lap in lines]
        geometry = self._geometry
        self._pit = [  # pit lane parts (game gives pit entry & exit roads apart)
            lap_map.rotate_line(lap_map.MapLine(list(range(len(part))), [p[0] for p in part], [p[1] for p in part]),
                                self._map_angle)
            for part in pit_parts(geometry.pit if geometry is not None else [])
        ]
        self._band_cache = OrderedDict()
        self._band_generation += 1
        self._preview_step = math.nan
        self._band_cache_applied = False
        shown = {lap.key for _, lap in self._map_lines}
        self._normals = {name: value for name, value in self._normals.items() if name in shown}
        self._turned = {name: value for name, value in self._turned.items() if name in shown}
        self._lap_shapes = {key: value for key, value in list(self._lap_shapes.items()) if key[0] in shown}
        grids = self._grids  # mouse picking grid of each lap line, kept while lap & rotation stay the same
        self._grids = {lap.key: grids[lap.key] if lap.key in grids and grids[lap.key].line is line
                       else lap_map.LineGrid(line) for line, lap in self._map_lines}
        xs = self._road.xs + [x for line, _ in self._map_lines for x in line.xs]
        ys = self._road.ys + [y for line, _ in self._map_lines for y in line.ys]
        limits = self.shown_limits()
        if limits is not None:
            xs = xs + limits.left.xs + limits.right.xs
            ys = ys + limits.left.ys + limits.right.ys
        for part in self._pit:
            xs, ys = xs + part.xs, ys + part.ys
        events = self.map_event_points()
        self._map = {
            "road": self.prefix + "map|road", "edge": self.prefix + "map|edge", "colored": self.prefix + "map|colored",
            "marks": self.prefix + "map|marks", "pit": self.prefix + "map|pit", "mini": self.prefix + "map|mini",
            "spread": self.prefix + "map|spread", "official": official is not None,
            "layout": geometry.layout if geometry is not None and official is not None else "",
            "events": events, "violations": self.violation_counts(events),
            "lines": [
                {"key": f"{self.prefix}map|{lap.key}", "highlight": f"{self.prefix}map|{lap.key}|zoom",
                 "trail": f"{self.prefix}map|{lap.key}|trail",
                 "color": lap.color.name(), "reference": lap is self.data.reference, "lap": lap.key}
                for _, lap in self._map_lines
            ],
            "markers": [
                {"lap": lap.key, "color": lap.color.name(), "reference": lap is self.data.reference,
                 "shapes": [{"kind": kind, "fill": f"{self.prefix}mk|{lap.key}|{kind}",
                             "outline": f"{self.prefix}mk|{lap.key}|{kind}|o"} for kind in MARKER_PIXELS],
                 "brakeZones": f"{self.prefix}zone|{lap.key}|brake",
                 "throttleZones": f"{self.prefix}zone|{lap.key}|throttle"}
                for _, lap in self._map_lines
            ],
            "arrowsKey": self.prefix + "map|arrows",
            "rangeKey": self.prefix + "map|range", "selectedKey": self.prefix + "map|selected",
            "ticks": [{"x": x, "y": y, "label": f"{distance / 1000:g} km"}
                      for x, y, distance in lap_map.distance_ticks(self._map_lines[0][0] if self._map_lines else self._road)],
            "limits": limits is not None,
            "minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys),
            "corners": self.map_corner_points(),
            "points": self.map_driving_points(),
            "slips": self.map_slip_points(),
            "sectors": self.map_sector_labels(),
            "arrows": [{"x": x, "y": y, "angle": angle} for x, y, angle in self.direction_marks()],
            "start": self.start_mark(),
        }
        self.map_lap_model.sync([{**line, **marker} for line, marker in zip(self._map["lines"], self._map["markers"])],
                                "lap")
        self.build_minimap()
        self.build_map_bands()
        self.pinChanged.emit()  # kept position on map turned with it

    def shown_limits(self) -> lap_map.TrackLimits | None:
        """Track edges turned like map, None if not guessed or option off"""
        if self._limits is None or not self._map_options.get("limits"):
            return None
        return lap_map.TrackLimits(lap_map.rotate_line(self._limits.left, self._map_angle),
                                   lap_map.rotate_line(self._limits.right, self._map_angle))

    def start_mark(self) -> list[float]:
        """Start line across circuit (reference line start), x0 y0 x1 y1"""
        if not self._map_lines:
            road = self._road
            if len(road.xs) < 2:
                return []
            dx, dy = road.xs[1] - road.xs[0], road.ys[1] - road.ys[0]
            length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
            nx, ny = -dy / length * TRACK_WIDTH, dx / length * TRACK_WIDTH
            return [road.xs[0] - nx, road.ys[0] - ny, road.xs[0] + nx, road.ys[0] + ny]
        line = self._map_lines[0][0]
        return list(lap_map.cross_mark(line, line.distances[0] + 1, TRACK_WIDTH))

    def map_corner_points(self) -> list[dict]:
        """Corner labels at apex of reference line, with time lost or gained by compared lap

        Official corners of circuit when known (every corner, even flat out ones), else corners found
        on reference lap. Each label zooms charts on its corner (start & end distances).
        Labels with a time delta are drawn first when labels overlap (priority).
        """
        if self._official:
            return self.official_points()
        if not self._map_lines or not self._corner_rows:
            return []
        line = self._map_lines[0][0]
        points = []
        for index, row in enumerate(self._corner_rows):
            x, y = lap_map.point_at(line, row.corner.apex)
            delta = row.time_delta
            points.append({
                "x": x, "y": y, "label": corner_label(row.corner.number), "index": index, "row": index,
                "start": row.corner.start, "end": row.corner.end,
                "delta": signed(delta, 2) if delta is not None else "",
                "deltaColor": COLOR_LOSS if delta is not None and delta > 0.005
                else COLOR_GAIN if delta is not None and delta < -0.005 else "",
                "priority": abs(delta) if delta is not None else 0.0,
            })
        return points

    def official_points(self) -> list[dict]:
        """Official corners on map, time lost / gained shown on the official corner nearest to apex"""
        delta_on: dict[int, CornerComparison] = {}  # official corner index: corner found on reference lap
        for row in self._corner_rows:
            nearest = min(self.official_in(row) or self._official,
                          key=lambda corner: abs(corner.distance - row.corner.apex))
            if abs(nearest.distance - row.corner.apex) <= 200:
                delta_on[self._official.index(nearest)] = row
        points = []
        for index, corner in enumerate(self._official):
            found = delta_on.get(index) or next(
                (row for row in self._corner_rows if corner in self.official_in(row)), None)
            delta = found.time_delta if found is not None and index in delta_on else None
            start, end = (found.corner.start, found.corner.end) if found is not None else (
                corner.distance - 120, corner.distance + 120)
            x, y = self.rotate_point(corner.x, corner.y)
            points.append({
                "x": x, "y": y, "label": self.official_text(corner.label), "index": index,
                "row": self._corner_rows.index(found) if found is not None else -1,
                "start": start, "end": end,
                "delta": signed(delta, 2) if delta is not None else "",
                "deltaColor": COLOR_LOSS if delta is not None and delta > 0.005
                else COLOR_GAIN if delta is not None and delta < -0.005 else "",
                "priority": abs(delta) if delta is not None else 0.0,
            })
        return points

    def lap_corner_stats(self, lap: PlotLap) -> tuple[ResampledLap, list[CornerStats | None]]:
        """Driving of lap in each corner found on reference lap, computed again only if laps or corners changed"""
        key = (lap.data, self._corner_key, self.data.scale_of(lap))
        cached = self._lap_corners.get(lap.key)
        if cached is None or not keys_match(cached[0], key):
            sampled = self.resampled(lap)
            cached = (key, sampled, [corner_stats(sampled, row.corner) for row in self._corner_rows])
            self._lap_corners = {name: value for name, value in self._lap_corners.items()
                                 if name in {shown.key for shown in self.data.laps}}
            self._lap_corners[lap.key] = cached
        return cached[1], cached[2]

    def resampled(self, lap: PlotLap) -> ResampledLap:
        """Lap columns on corner grid, resampled once per loaded lap (columns resampled at first use)"""
        scale = self.data.scale_of(lap)
        cached = self._resampled.get(lap.key)
        if cached is None or cached.lap is not lap.data or cached.scale != scale:
            cached = ResampledLap(lap.data, scale=scale)
            shown = {shown_lap.key for shown_lap in self.data.laps}
            self._resampled = {name: value for name, value in self._resampled.items() if name in shown}
            self._resampled[lap.key] = cached
        return cached

    def lap_trackouts(self, lap: PlotLap, stats: list[CornerStats | None], turns: dict[int, float],
                      reference_line: lap_map.MapLine) -> dict[int, float]:
        """Track-out point of lap in each corner (reference distance), computed once per lap, corners & edges"""
        scale = self.data.scale_of(lap)
        reference = self.data.reference
        key = (lap.data, reference.data if reference is not None else None, self._limits, self._corner_key, scale,
               self._edges)
        cached = self._trackouts.get(lap.key)
        if cached is not None and keys_match(cached[0], key):
            return cached[1]
        placed = self.lap_offsets(lap)  # offsets from base line, edges along it: no line search again
        found: dict[int, float] = {}
        if placed is not None and placed[1] and self._edges[0]:
            line, sides, indexes = placed
            for index, row in enumerate(self._corner_rows):
                stat = stats[index]
                if stat is None or index not in turns:
                    continue
                distance = lap_map.trackout_from_offsets(line.distances, sides, indexes, self._edges,
                                                         stat.apex / scale, row.corner.end / scale,
                                                         turns[index])
                found[index] = distance * scale if distance >= 0 else -1.0
        shown = {shown_lap.key for shown_lap in self.data.laps}
        self._trackouts = {name: value for name, value in self._trackouts.items() if name in shown}
        self._trackouts[lap.key] = (key, found)
        return found

    def map_driving_points(self) -> list[dict]:
        """Braking, apex (minimum speed) & exit (full throttle) points of each lap in each corner

        Each point tells its corner, speed & distance, and differences with reference lap.
        """
        if not self._map_lines or not self._corner_rows or self.data.reference is None:
            return []
        convert, unit = self.data.units["speed"]
        speed_channel = CHANNEL_MAP["speed_kph"]
        reference_sampled, reference_stats = self.lap_corner_stats(self.data.reference)
        titles = {"brake": tr("Braking"), "apex": tr("Apex"), "exit": tr("Exit (full throttle)"),
                  "trackout": tr("Track-out (outside edge)")}
        lefts = self._edges[0]  # track edges known
        reference_line = self.lap_line(self.data.reference)
        turns: dict[int, float] = {}  # turning direction at each corner apex (reference line)
        reference_trackouts: dict[int, float] = {}  # track-out point of reference lap in each corner
        if lefts and reference_line is not None:
            for index, row in enumerate(self._corner_rows):
                turns[index] = lap_map.turning(reference_line, min(bisect.bisect_left(
                    reference_line.distances, row.corner.apex), len(reference_line.xs) - 1))
            reference_trackouts = self.lap_trackouts(self.data.reference, reference_stats, turns, reference_line)
        points = []
        for order, (line, lap) in enumerate(self._map_lines):
            sampled, lap_stats = self.lap_corner_stats(lap)
            is_reference = lap is self.data.reference
            name = self.short_label(lap.key)
            scale = self.data.scale_of(lap)  # corner stats in reference distances, map line in lap distances
            trackouts = self.lap_trackouts(lap, lap_stats, turns, reference_line) \
                if turns and reference_line is not None else {}
            for index, row in enumerate(self._corner_rows):
                stats, reference = lap_stats[index], reference_stats[index]
                if stats is None:
                    continue
                corner = self.row_label(row)
                trackout = trackouts.get(index, -1.0)
                reference_trackout = reference_trackouts.get(index, -1.0)
                for kind, distance, reference_distance in (
                    ("brake", stats.brake_point, reference.brake_point if reference else -1.0),
                    ("apex", stats.apex, reference.apex if reference else -1.0),
                    ("exit", stats.throttle_point, reference.throttle_point if reference else -1.0),
                    ("trackout", trackout, reference_trackout),
                ):
                    if distance < 0:
                        continue
                    speed = sampled.value_at("speed_kph", distance) or 0.0
                    shown_speed = convert(speed) if convert else speed
                    lines = [f"{shown_speed:.0f} {unit}", f"{distance:.0f} m"]
                    if not is_reference and reference_distance >= 0:
                        reference_speed = reference_sampled.value_at("speed_kph", reference_distance) or 0.0
                        reference_shown = convert(reference_speed) if convert else reference_speed
                        lines[0] += f" ({format_diff(speed_channel, shown_speed - reference_shown)})"
                        lines[1] += f" ({signed(distance - reference_distance, 0, ' m')})"
                    x, y = lap_map.point_at(line, distance / scale)
                    points.append({
                        "x": x, "y": y, "kind": kind, "color": lap.color.name(), "lap": lap.key, "corner": index,
                        "distance": distance,
                        "order": order,  # lap position (speed labels of laps stacked)
                        "angle": math.degrees(lap_map.heading_at(line, distance / scale)), "value": f"{shown_speed:.0f}",
                        "tip": f"{name} · {corner} · {titles[kind]}\n" + " · ".join(lines),
                    })
        return points

    # Lap placement across track: offset from base line (official center path) & track edges
    def reference_length(self) -> float:
        reference = self.data.reference
        if reference is None or not len(reference.data):
            return 0.0
        length = reference.data.meta.get("track_length")
        return float(length) if isinstance(length, (int, float)) and length > 0 else reference.data.distance[-1]

    def lap_offsets(self, lap: PlotLap) -> tuple[lap_map.MapLine, list[float], list[int]] | None:
        """Offset of each lap line point from base line (left positive) & nearest base point, cached"""
        line = self.lap_line(lap)
        base = self._base
        if line is None or len(base.xs) < 3:
            return None
        key = (lap.data, len(base.xs), base.xs[0], base.ys[0], base.distances[-1])
        cached = self._lap_offsets.get(lap.key)
        if cached is None or not keys_match(cached[0], key):
            sides, indexes = lap_map.lateral_offsets(base, line)
            cached = (key, line, sides, indexes)
            shown = {shown_lap.key for shown_lap in self.data.laps}
            self._lap_offsets = {name: value for name, value in self._lap_offsets.items() if name in shown}
            self._lap_offsets[lap.key] = cached
        return cached[1], cached[2], cached[3]

    def update_base(self):
        """Line lap placement is measured from: official center path, else reference lap line"""
        reference = self.data.reference
        official = self.official_base(self.reference_length())
        line = self.lap_line(reference) if reference is not None else None
        self._base_official = official is not None
        self._base = official if official is not None else (line if line is not None else lap_map.MapLine([], [], []))
        self.update_placements()

    def update_placements(self):
        """Track edges along base line & placement of each shown lap (track position & distance to center charts)"""
        base = self._base
        if self._limits is not None and len(base.xs) > 2:
            key = (base, self._limits)
            if not self._edges_cache or not keys_match(self._edges_cache[0], key):
                self._edges_cache = (key, lap_map.edge_offsets(base, self._limits))
            self._edges = self._edges_cache[1]
        else:
            self._edges = ([], [])
        lefts, rights = self._edges
        placements: dict[str, tuple[list[float], list[float], list[float]]] = {}
        cache: dict[str, tuple[tuple, tuple]] = {}
        if lefts or self._base_official:
            for lap in self.data.laps:
                found = self.lap_offsets(lap)
                if found is None or not found[1]:
                    continue
                placement_key = (found[1], self._edges)
                cached = self._placements.get(lap.key)
                if cached is None or not keys_match(cached[0], placement_key):
                    cached = (placement_key, self.lap_placements(found, lefts, rights))
                cache[lap.key] = cached
                placements[lap.key] = cached[1]
        unchanged = cache.keys() == self._placements.keys() and all(
            cache[name] is self._placements[name] for name in cache)
        self._placements = cache
        if not unchanged or self.data.placements.keys() != placements.keys():  # charts drawn again only if changed
            self.data.set_placements(placements)

    @staticmethod
    def lap_placements(found: tuple, lefts: list[float], rights: list[float]) -> tuple:
        """Lap distances, distance to track middle (m) & track position (%) of each lap line point"""
        line, sides, indexes = found
        if lefts:
            centers = [side - (lefts[index] + rights[index]) / 2 for side, index in zip(sides, indexes)]
            percents = [max(min(lap_map.placement(side, lefts[index], rights[index])[2], 150.0), -150.0)
                        for side, index in zip(sides, indexes)]
        else:  # official center path without edges: distance only
            centers, percents = list(sides), []
        return list(line.distances[:len(sides)]), centers, percents

    def lap_placement(self, lap: PlotLap, distance: float) -> tuple[float, float, float] | None:
        """Lap at distance: room to left edge, to right edge (m), track position (%), None if edges unknown"""
        lefts, rights = self._edges
        found = self.lap_offsets(lap) if lefts else None
        if found is None or not found[1]:
            return None
        line, sides, indexes = found
        position = min(max(bisect.bisect_left(line.distances, distance), 0), len(sides) - 1)
        if position > 0 and abs(line.distances[position - 1] - distance) < abs(line.distances[position] - distance):
            position -= 1
        index = indexes[position]
        return lap_map.placement(sides[position], lefts[index], rights[index])

    def lap_events(self, lap: PlotLap) -> list[tuple[float, str]]:
        """Off track moments (wheel surface) & track limits exceeded (game edge, else game edges of track)"""
        key = (lap.data, self._limits, self._limits_source, len(self._base.xs))
        cached = self._events.get(lap.key)
        if cached is not None and keys_match(cached[0], key):
            return cached[1]
        events = [(distance, "offtrack") for distance in lap_map.off_track_events(lap.data)]
        limits = lap_map.limits_events(lap.data)
        recorded = any(lap.data.columns.get("track_edge") or ())
        lefts, rights = self._edges
        if not recorded and self._limits_source == "game" and lefts:  # older lap, game edges known from others
            found = self.lap_offsets(lap)
            if found is not None:
                line, sides, indexes = found
                limits = lap_map.track_events(line.distances, [
                    side > lefts[index] + lap_map.CAR_HALF_WIDTH or side < rights[index] - lap_map.CAR_HALF_WIDTH
                    for side, index in zip(sides, indexes)])
        events += [(distance, "limit") for distance in limits]
        events.sort()
        shown = {shown_lap.key for shown_lap in self.data.laps}
        self._events = {name: value for name, value in self._events.items() if name in shown}
        self._events[lap.key] = (key, events)
        return events

    def map_event_points(self) -> list[dict]:
        """Off track & track limits points of each shown lap on map"""
        points = []
        for line, lap in self._map_lines:
            name = self.short_label(lap.key)
            for distance, kind in self.lap_events(lap):
                x, y = lap_map.point_at(line, distance)
                points.append({"x": x, "y": y, "kind": kind, "color": lap.color.name(), "lap": lap.key,
                               "distance": distance, "corner": -1, "angle": 0.0,
                               "tip": f"{name} · {tr(EVENT_TITLES[kind])} · {distance:.0f} m"})
        return points

    def violation_counts(self, events: list[dict]) -> list[dict]:
        """Track limits exceeded & off track count of each shown lap (map legend)"""
        rows = []
        for _, lap in self._map_lines:
            limits = sum(1 for point in events if point["lap"] == lap.key and point["kind"] == "limit")
            offs = sum(1 for point in events if point["lap"] == lap.key and point["kind"] == "offtrack")
            if limits or offs:
                rows.append({"lap": lap.key, "label": self.short_label(lap.key), "color": lap.color.name(),
                             "limits": limits, "offtrack": offs})
        return rows

    def brake_spreads(self) -> dict[int, tuple[float, float]]:
        """First & last braking point of shown laps in each corner (reference distances)"""
        spreads: dict[int, list[float]] = {}
        for point in self._map.get("points", []) if self._map else []:
            if point["kind"] == "brake" and point.get("distance") is not None:
                spreads.setdefault(point["corner"], []).append(point["distance"])
        return {corner: (min(values), max(values)) for corner, values in spreads.items() if len(values) > 1}

    # Mini-sectors: lap split in equal parts, fastest shown lap in each part
    def mini_sectors(self) -> dict:
        """Mini-sectors of shown laps: bounds, winner of each, times, ideal time (invalid laps never win)"""
        return self.data.mini_sectors()

    def map_sector_labels(self) -> list[dict]:
        """Sector names at mid sector on reference line: reference sector time, gap of compared lap"""
        reference = self.data.reference
        bounds = self.data.sector_lines
        if reference is None or len(bounds) != 2 or not self._map_lines:
            return []
        line = self._map_lines[0][0]
        reference_times = sector_times(reference.data)
        compared = self.compared_lap()
        compared_times = sector_times(compared.data) if compared is not None else []
        limits = [line.distances[0], *bounds, line.distances[-1]]
        labels = []
        for index in range(3):
            x, y = lap_map.point_at(line, (limits[index] + limits[index + 1]) / 2)
            gap = compared_times[index] - reference_times[index] if reference_times and compared_times else None
            labels.append({
                "x": x, "y": y, "label": f"S{index + 1}",
                "time": format_laptime(reference_times[index]) if reference_times else "",
                "delta": signed(gap, 3) if gap is not None else "",
                "deltaColor": COLOR_LOSS if gap is not None and gap > 0.0005
                else COLOR_GAIN if gap is not None and gap < -0.0005 else "",
            })
        return labels

    def map_slip_points(self) -> list[dict]:
        """Front wheel lockups & rear wheelspin of each lap, colored like its lap"""
        points = []
        shown = {lap.key for _, lap in self._map_lines}
        self._slips = {name: value for name, value in self._slips.items() if name in shown}
        for line, lap in self._map_lines:
            cached = self._slips.get(lap.key)
            if cached is None or cached[0] is not lap.data:
                cached = self._slips[lap.key] = (lap.data, lap_map.slip_events(lap.data))
            for distance, kind in cached[1]:
                x, y = lap_map.point_at(line, distance)
                points.append({"x": x, "y": y, "color": lap.color.name(), "kind": kind, "distance": distance,
                               "lap": lap.key})
        return points

    def build_map_bands(self):
        """Thick lines & markers sized for current map zoom, zoomed part, colored line

        Map scale rounded to steps: what does not depend on chart zoom is built once per step & cached,
        zooming back to a step already seen costs nothing.
        """
        if not self._map:
            return
        start, end, meters_per_pixel = self._map_view
        step = scale_step(meters_per_pixel)
        shown = step
        cached = self._band_cache.get(step)
        if cached is None:
            nearest = min(self._band_cache, key=lambda cached_step: abs(cached_step - step), default=None)
            if nearest is None:  # first scale of this map: built now
                cached = self._band_cache[step] = self.scale_shapes(2 ** step)
            else:  # nearest built scale shown at once, this one built in background (shown once ready)
                self.prepare_step(step)
                shown, cached = nearest, self._band_cache[nearest]
        self._band_cache.move_to_end(shown)
        while len(self._band_cache) > BAND_CACHE_STEPS:
            self._band_cache.popitem(last=False)
        if shown != self._preview_step or not self._band_cache_applied:
            for key, vertices in cached.items():
                VertexStore.set(key, vertices)  # type: ignore[arg-type]
            self._band_cache_applied = True
        self._preview_step = shown
        self._prefetch_step = step
        self._prefetch_timer.start()  # neighbor scales once map stays still (threads would slow zoom frames)
        zoomed = end > start
        for (line, lap), keys in zip(self._map_lines, self._map["lines"]):
            scale = self.data.scale_of(lap)
            indexes = range_indexes(line.distances, start / scale, end / scale) if zoomed else range(0)
            VertexStore.set(keys["highlight"], band_part(line.xs, line.ys, self.line_normals(lap, line), indexes,
                                                         meters_per_pixel * ZOOMED_WIDTH))
        self.build_map_overlays(meters_per_pixel)
        self.build_colored_line(meters_per_pixel)

    def prefetch_steps(self, step: float):
        """Thick lines of next zoom steps in & out built in background: zoom preview always ready"""
        for neighbor in (step - 1 / ZOOM_BUCKETS, step + 1 / ZOOM_BUCKETS):
            self.prepare_step(neighbor)

    def prepare_step(self, step: float):
        """Thick lines of map scale step built in background, shown once ready if it is the scale shown"""
        if step in self._band_cache or step in self._prefetching or not self._map:
            return
        generation = self._band_generation
        self._prefetching.add(step)

        def done(shapes):
            self._prefetching.discard(step)
            if shapes is None or generation != self._band_generation or step in self._band_cache:
                return
            self._band_cache[step] = shapes  # kept like recently used, shown step kept newest
            if self._preview_step in self._band_cache:
                self._band_cache.move_to_end(self._preview_step)
            while len(self._band_cache) > BAND_CACHE_STEPS:
                self._band_cache.popitem(last=False)
            if self._map and step == scale_step(self._map_view[2]) and step != self._preview_step:
                self.build_map_bands()  # map waits at this scale: exact thickness now

        self.run_job("map zoom step", lambda: self.scale_shapes(2 ** step), done)

    def build_minimap(self):
        """Whole circuit as thin lines for minimap (built once per map)"""
        road = self._road
        span = max(self._map["maxX"] - self._map["minX"], self._map["maxY"] - self._map["minY"], 1.0)
        meters = span / MINIMAP_PIXELS
        VertexStore.set(self._map["mini"], band(road.xs, road.ys, meters * 1.6) if len(road.xs) > 1 else band([], [], 1))

    def build_map_overlays(self, meters_per_pixel: float):
        """Chart markers A-B range & selected corner along reference line"""
        line = self._map_lines[0][0] if self._map_lines else lap_map.MapLine([], [], [])
        start, end = self._map_range
        shown = lap_map.part(line, start, end) if end > start else lap_map.MapLine([], [], [])
        VertexStore.set(self._map["rangeKey"], lap_map.line_band(shown, meters_per_pixel * 7))
        selected = lap_map.MapLine([], [], [])
        if 0 <= self._selected_corner < len(self._corner_rows):
            corner = self._corner_rows[self._selected_corner].corner
            selected = lap_map.part(line, corner.start, corner.end)
        VertexStore.set(self._map["selectedKey"], lap_map.line_band(selected, meters_per_pixel * 9))

    def scale_shapes(self, meters_per_pixel: float) -> dict[str, object]:
        """Vertices of everything sized in pixels for map scale: road, lines, marks, markers, zones, arrows"""
        shapes: dict[str, object] = {}
        pause = Yielder() if threading.current_thread() is not threading.main_thread() else (lambda: None)
        road = self._road
        road_half = max(TRACK_WIDTH / 2, meters_per_pixel * 4)  # visible when zoomed out
        # Circuit (road, edges) does not depend on laps shown: kept per scale while circuit & rotation stay
        circuit_key = (meters_per_pixel, self._map_angle, self._limits if self._map_options.get("limits") else None,
                       road.xs[0] if road.xs else 0.0, len(road.xs))
        cached_circuit = self._circuit_shapes.get(meters_per_pixel)
        if cached_circuit is not None and keys_match(cached_circuit[0], circuit_key):
            shapes[self._map["road"]], shapes[self._map["edge"]] = cached_circuit[1]
        else:
            shapes[self._map["road"]], shapes[self._map["edge"]] = self.circuit_shapes(road, road_half, meters_per_pixel)
            self._circuit_shapes[meters_per_pixel] = (circuit_key, (shapes[self._map["road"]], shapes[self._map["edge"]]))
            while len(self._circuit_shapes) > BAND_CACHE_STEPS * 2:
                self._circuit_shapes.pop(next(iter(self._circuit_shapes)))
        reference = self.data.reference.data if self.data.reference is not None else None
        # Lap shapes depend on map rotation, corners of reference lap & track edges (driving points, track-out,
        # events): not on other laps shown
        lap_key = (self._map_angle, reference, self._hysteresis, self._limits, self._edges)
        built: set[str] = set()
        for _, lap in self._map_lines:
            cached = self._lap_shapes.get((lap.key, meters_per_pixel))
            if cached is not None and keys_match(cached[0], (lap.data, *lap_key)):
                shapes.update(cached[1])  # lap shown before at this scale: nothing built
                built.add(lap.key)
        for (line, lap), keys in zip(self._map_lines, self._map["lines"]):
            if lap.key in built:
                continue
            pause()
            shapes[keys["key"]] = band_part(line.xs, line.ys, self.line_normals(lap, line),
                                            lap_map.kept_indexes(line, meters_per_pixel * 0.75),
                                            meters_per_pixel * LINE_WIDTH)
        marks = []
        if self._map_lines:
            reference_line = self._map_lines[0][0]
            for distance in self.data.sector_lines:  # sector boundaries across road
                marks.append(lap_map.cross_mark(reference_line, distance, road_half * 1.6))
        shapes[self._map["marks"]] = segments(marks)
        # Markers: one buffer per lap & kind, outline (map background color) drawn under fill
        points: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
        for point in self._map.get("points", []) + self._map.get("slips", []) + self._map.get("events", []):
            points.setdefault((point["lap"], point["kind"]), []).append(
                (point["x"], point["y"], math.radians(point.get("angle", 0.0))))
        for item in self._map["markers"]:
            if item["lap"] in built:
                continue
            pause()
            for shape in item["shapes"]:
                pixels, form = MARKER_PIXELS[shape["kind"]]
                found = points.get((item["lap"], shape["kind"]), [])
                shapes[shape["fill"]] = markers(found, form, pixels * meters_per_pixel)
                outline = "dot" if form in ("dot", "ring") else form.replace("hollow_", "")
                shapes[shape["outline"]] = markers(found, outline, (pixels + OUTLINE_PIXELS * 2) * meters_per_pixel)
        # Braking & throttle application zones of each lap
        for (line, lap), keys, item in zip(self._map_lines, self._map["lines"], self._map["markers"]):
            if lap.key in built:
                continue
            pause()
            braking, applying = self.pedal_zones(lap)
            line_normals = self.line_normals(lap, line)
            shapes[item["brakeZones"]] = lap_map.zones_band(line, braking, meters_per_pixel * 6, line_normals)
            shapes[item["throttleZones"]] = lap_map.zones_band(line, applying, meters_per_pixel * 6, line_normals)
            own = [keys["key"], item["brakeZones"], item["throttleZones"]]
            own += [key for shape in item["shapes"] for key in (shape["fill"], shape["outline"])]
            self._lap_shapes[(lap.key, meters_per_pixel)] = ((lap.data, *lap_key), {key: shapes[key] for key in own})
        arrows = [(x, y, math.radians(angle)) for x, y, angle in self.direction_marks()]
        shapes[self._map["arrowsKey"]] = markers(arrows, "triangle", ARROW_PIXELS * meters_per_pixel)
        pits = [band(part.xs, part.ys, meters_per_pixel * 1.2) for part in self._pit]
        shapes[self._map["pit"]] = merge_strips(pits) if pits else band([], [], 1)
        # Braking points range of shown laps in each corner, along reference line
        spreads = []
        if self._map_lines and len(self._map_lines) > 1:
            reference_line, reference_lap = self._map_lines[0]
            reference_normals = self.line_normals(reference_lap, reference_line)
            for low, high in self.brake_spreads().values():
                if high - low >= 1:
                    spreads.append(band_part(reference_line.xs, reference_line.ys, reference_normals,
                                             range_indexes(reference_line.distances, low, high), meters_per_pixel * 6))
        shapes[self._map["spread"]] = merge_strips(spreads) if spreads else band([], [], 1)
        return shapes

    def circuit_shapes(self, road: lap_map.MapLine, road_half: float, meters_per_pixel: float) -> tuple:
        """Road & road edge (or track edges) sized for map scale"""
        limits = self.shown_limits()
        if limits is not None:  # road between guessed track edges, thin edge lines
            keep = lap_map.kept_indexes(limits.left, meters_per_pixel * 0.75)
            edges = [band_part(edge.xs, edge.ys, edge_normals, keep, meters_per_pixel * 1.1)
                     for edge, edge_normals in zip((limits.left, limits.right), self.edge_normals(limits))]
            return lap_map.limits_band(limits, keep), merge_strips(edges)
        closed = len(road.xs) > 2 and (road.xs[0] - road.xs[-1]) ** 2 + (road.ys[0] - road.ys[-1]) ** 2 < 50 ** 2
        simple_road = lap_map.simplify(road, meters_per_pixel * 0.75)
        return (band(simple_road.xs, simple_road.ys, road_half, closed),
                band(simple_road.xs, simple_road.ys, road_half + meters_per_pixel * 1.5, closed))

    def direction_marks(self) -> list[tuple[float, float, float]]:
        """Driving direction arrows along reference line (or circuit), once per line"""
        line = self._map_lines[0][0] if self._map_lines else self._road
        if not self._arrows or self._arrows[0] is not line:
            self._arrows = (line, lap_map.direction_marks(line))
        return self._arrows[1]

    def turned_line(self, lap: PlotLap, line: lap_map.MapLine) -> lap_map.MapLine:
        """Lap line turned like map, once per lap & map rotation (same object: kept caches stay valid)"""
        cached = self._turned.get(lap.key)
        if cached is None or cached[0] is not lap.data or cached[1] != self._map_angle:
            cached = self._turned[lap.key] = (lap.data, self._map_angle, lap_map.rotate_line(line, self._map_angle))
        return cached[2]

    def line_normals(self, lap: PlotLap, line: lap_map.MapLine) -> list[tuple[float, float]]:
        """Normals of lap line turned like map: same at every map scale, computed once per lap & map rotation"""
        cached = self._normals.get(lap.key)
        if cached is None or cached[0] is not lap.data or cached[1] != self._map_angle or cached[2] != len(line.xs):
            cached = (lap.data, self._map_angle, len(line.xs), normals(line.xs, line.ys))
            self._normals[lap.key] = cached  # one assignment: safe from background map builds
        return cached[3]

    def edge_normals(self, limits: lap_map.TrackLimits) -> tuple[list, list]:
        """Normals of track edges turned like map, computed once per track edges & map rotation"""
        key = (self._limits, self._map_angle)
        cached = self._edge_normals
        if not cached or not keys_match(cached[0], key):
            cached = (key, (normals(limits.left.xs, limits.left.ys), normals(limits.right.xs, limits.right.ys)))
            self._edge_normals = cached
        return cached[1]

    def pedal_zones(self, lap: PlotLap) -> tuple[list, list]:
        """Braking & throttle application zones of lap (computed once per loaded lap, every zoom step uses them)"""
        cached = self._zones.get(lap.key)
        if cached is None or cached[0] is not lap.data:
            cached = (lap.data, lap_map.pedal_zones(lap.data))
            self._zones = {key: value for key, value in self._zones.items()
                           if key in {shown.key for shown in self.data.laps}}
            self._zones[lap.key] = cached
        return cached[1]

    def build_colored_line(self, meters_per_pixel: float):
        """Line of current color mode: compared lap by time gain, reference lap by speed or pedals

        Colors depend on laps & options only: computed once, map zoom only simplifies the line again.
        """
        key = self._map["colored"]
        mode = self._map_mode
        lines = self._map_lines
        if mode == "laps" or not lines:
            self._speed_range = (0.0, 0.0)
            self._colored_shown = None
            VertexStore.set(key, lap_map.colored_line(lap_map.MapLine([], [], []), [], 0))
            return
        color_key = self.color_key(mode)
        if self._color_lines and keys_match(self._color_lines[0], color_key):
            line, colors, self._speed_range = self._color_lines[1]
        else:
            line, colors = self.line_colors(mode, lines)
            self._color_lines = (color_key, (line, colors, self._speed_range))
            self._colored_steps = {}
        if line is None:
            self._colored_shown = None
            VertexStore.set(key, lap_map.colored_line(lap_map.MapLine([], [], []), [], 0))
            return
        step = scale_step(meters_per_pixel)
        vertices = self._colored_steps.get(step)
        if vertices is None:  # built once per map scale step (chart zoom & pan reuse it)
            scale = 2 ** step
            simple = lap_map.simplify(line, scale * 0.5)
            if simple is not line and colors:  # colors of kept points
                index = {distance: number for number, distance in enumerate(line.distances)}
                colors = [colors[index[distance]] for distance in simple.distances]
            vertices = self._colored_steps[step] = lap_map.colored_line(simple, colors, scale * ZOOMED_WIDTH)
        if self._colored_shown is not vertices or not VertexStore.has(key):  # not uploaded again on chart zoom
            VertexStore.set(key, vertices)
            self._colored_shown = vertices

    def color_key(self, mode: str) -> tuple:
        """What colored line of map mode depends on (colors computed again only if it changes)"""
        reference = self.data.reference.data if self.data.reference is not None else None
        compared = self.compared_lap()
        compared_data = compared.data if compared is not None else None
        colorblind = bool(self._map_options.get("colorblind"))
        if mode == "gain":
            return (mode, reference, compared_data, self.data.delta_window, colorblind, self._map_angle)
        if mode == "line":
            return (mode, reference, compared_data, self._map_angle)
        if mode == "corners":
            return (mode, reference, self._corner_key, colorblind, self._map_angle)
        if mode == "minisectors":
            return (mode, tuple(lap.data for _, lap in self._map_lines), tuple(lap.color.rgba() for _, lap in self._map_lines),
                    tuple(lap.clean for _, lap in self._map_lines), self._map_angle)
        return (mode, reference, self._map_angle)

    def line_colors(self, mode: str, lines: list[tuple[lap_map.MapLine, PlotLap]],
                    ) -> tuple[lap_map.MapLine | None, list[QColor]]:
        """Colored line of map mode & its color at each point, None if nothing to color"""
        self._speed_range = (0.0, 0.0)
        if mode == "gain":
            compared = self.compared_lap()
            found = next(((line, lap) for line, lap in lines[1:] if compared is not None and lap is compared), None)
            delta = self.data.reference_deltas.get(found[1].key) if found is not None else None
            if found is None or self.data.reference is None or not delta:
                return None, []
            line, lap = found
            colors = lap_map.gain_colors_from_delta(delta[0], delta[1], line, self.data.scale_of(lap),
                                                    self.data.delta_window, bool(self._map_options.get("colorblind")))
        elif mode == "corners":  # reference line colored corner by corner by compared lap time delta
            line, lap = lines[0]
            corners = [(row.corner.start, row.corner.end, row.time_delta) for row in self._corner_rows
                       if row.time_delta is not None]
            colors = lap_map.corner_delta_colors(line, corners, bool(self._map_options.get("colorblind")))
        elif mode == "minisectors":  # reference line colored by fastest shown lap of each mini-sector
            line, lap = lines[0]
            mini = self.mini_sectors()
            if not mini:
                return None, []
            bounds, winners = mini["bounds"], mini["winners"]
            neutral = QColor("#9CA3AF")
            laps = self.data.laps
            colors = []
            for distance in line.distances:
                sector = min(max(bisect.bisect_right(bounds, distance) - 1, 0), len(winners) - 1)
                winner = winners[sector] if winners else -1
                colors.append(laps[winner].color if 0 <= winner < len(laps) else neutral)
        elif mode == "line":  # compared lap line: inside or outside of reference line
            compared = self.compared_lap()
            found = next(((line, lap) for line, lap in lines[1:] if compared is not None and lap is compared), None)
            if found is None:
                return None, []
            line, lap = found
            colors = lap_map.line_colors(self.line_offsets(lines[0][0], lines[0][1], line, lap))
        else:
            line, lap = lines[0]
            if mode == "speed":
                colors, low, high = lap_map.speed_colors(lap.data, line)
                self._speed_range = (low, high)
            elif mode == "elevation":
                colors, low, high = lap_map.elevation_colors(lap.data, line)
                self._speed_range = (low, high)
            elif mode == "gear":
                colors = lap_map.gear_colors(lap.data, line)
            else:
                colors = lap_map.pedal_colors(lap.data, line)
        return line, colors

    def line_offsets(self, reference_line: lap_map.MapLine, reference: PlotLap, line: lap_map.MapLine,
                     lap: PlotLap) -> list[float]:
        """Compared line distance to reference line, cached (slow, map zoom rebuilds colored line)"""
        key = (reference.key, reference.data, lap.key, lap.data)  # offsets do not change when map turns
        cached = self._line_offsets.get("key")
        if cached is None or not keys_match(cached, key):
            self._line_offsets = {"key": key, "offsets": lap_map.line_offsets(reference_line, line)}
        return self._line_offsets["offsets"]

    @Slot(str, bool)
    def setMapOption(self, name: str, enabled: bool):
        """Track map display option: apex, exit, arrows, sectors, values"""
        if name in self._map_options and self._map_options[name] != enabled:
            self._map_options[name] = enabled
            save_viewer_setting(self.folder, map_options=self._map_options)
            if self._map and name == "limits":
                self.build_map()
                self.bump_revision()
                self.chartChanged.emit()
            elif self._map and name == "colorblind" and self._map_mode in ("gain", "corners"):
                self.build_colored_line(self._map_view[2])
                self.bump_revision()
            self.mapChanged.emit()

    @Slot(float, float, float)
    def setMapView(self, start_x: float, end_x: float, meters_per_pixel: float):
        """Charts zoom (axis range, equal if not zoomed) & map scale: map lines rebuilt"""
        start, end = (self.data.distance_at_x(start_x), self.data.distance_at_x(end_x)) if end_x > start_x else (0, 0)
        view = (start, end, max(meters_per_pixel, 1e-3))
        if view != self._map_view or scale_step(view[2]) != self._preview_step:  # zoom preview showed another step
            self._map_view = view
            self.build_map_bands()
            self.bump_revision()

    @Slot(float)
    def previewMapScale(self, meters_per_pixel: float):
        """Map zoom easing: thick lines of nearest scale step already built shown at once (nothing built)"""
        if not self._map:
            return
        wanted = scale_step(meters_per_pixel)
        # Nearest step already built (target step is prepared as soon as zoom starts, see prepareMapScale)
        step = min(self._band_cache, key=lambda cached_step: abs(cached_step - wanted), default=math.nan)
        if math.isnan(step) or step == self._preview_step or (
                not math.isnan(self._preview_step) and abs(self._preview_step - wanted) <= abs(step - wanted)):
            return
        cached = self._band_cache[step]
        self._preview_step = step
        for key, vertices in cached.items():
            VertexStore.set(key, vertices)  # type: ignore[arg-type]

    @Slot(float)
    def prepareMapScale(self, meters_per_pixel: float):
        """Map zoom starting toward a scale: its thick lines built in background (shown while zoom eases)"""
        if not self._map:
            return
        self.prepare_step(scale_step(meters_per_pixel))

    @Slot(str)
    def setMapMode(self, mode: str):
        if mode in lap_map.MAP_MODES and mode != self._map_mode:
            self._map_mode = mode
            save_viewer_setting(self.folder, map_color_mode=mode)
            if self._map:
                self.build_colored_line(self._map_view[2])
                self.bump_revision()
            self.mapChanged.emit()

    @Slot(bool)
    def setMapFollow(self, enabled: bool):
        self._map_follow = enabled
        save_viewer_setting(self.folder, map_follow_zoom=enabled)
        self.mapChanged.emit()

    @Slot(bool)
    def setMapBraking(self, enabled: bool):
        self._map_braking = enabled
        save_viewer_setting(self.folder, map_braking_points=enabled)
        self.mapChanged.emit()

    @Slot(bool)
    def setMapSlip(self, enabled: bool):
        self._map_slip = enabled
        save_viewer_setting(self.folder, map_slip_points=enabled)
        self.mapChanged.emit()

    def map_rotated(self):
        """Map built again turned (orientation changed)"""
        if self.data.laps:
            self.build_map()
            self.bump_revision()
            self.chartChanged.emit()
        self.mapChanged.emit()

    @Slot()
    def rotateMap(self):
        """Turn map a quarter clockwise"""
        self._map_quarters = (self._map_quarters + 1) % 4
        save_viewer_setting(self.folder, map_rotation=self._map_quarters)
        self.map_rotated()

    @Slot(bool)
    def setMapAutoOrient(self, enabled: bool):
        self._map_auto_orient = enabled
        save_viewer_setting(self.folder, map_auto_orient=enabled)
        self.map_rotated()

    @Slot(float)
    def setMapAspect(self, aspect: float):
        """Map view width / height: auto orientation follows view shape"""
        tall = aspect < 1
        changed = tall != (self._map_aspect < 1)
        self._map_aspect = aspect
        if changed and self._map_auto_orient:
            self.map_rotated()

    @Slot(float, float, result=list)
    def mapBounds(self, start_x: float, end_x: float) -> list[float]:
        """Map area of reference line between axis positions (map follows chart zoom), empty if none"""
        if not self._map_lines:
            return []
        line = lap_map.part(self._map_lines[0][0], self.data.distance_at_x(start_x), self.data.distance_at_x(end_x))
        if len(line.xs) < 2:
            return []
        return [min(line.xs), min(line.ys), max(line.xs), max(line.ys)]

    @Slot(float, result=list)
    def mapCursor(self, x: float) -> list[dict]:
        """Position of each lap at axis position, map coordinates (time axis: where each lap is at that time)"""
        points = []
        reference = self.data.reference
        reference_distance = self.data.lap_distance_at_x(reference, x) if reference is not None else 0.0
        reference_distance *= self.data.scale_of(reference) if reference is not None else 1.0
        deltas = self.data.reference_deltas
        for line, lap in self._map_lines:
            distance = self.data.lap_distance_at_x(lap, x)  # lap distance (own line)
            along = distance * self.data.scale_of(lap)  # reference distance
            gap = ""  # behind (+) or ahead (-) of reference lap: time on distance axis, meters on time axis
            if lap is not reference:
                if self.data.time_axis:
                    gap = signed(reference_distance - along, 0, " m")
                elif lap.key in deltas and deltas[lap.key][0]:
                    gap = signed(interpolate(*deltas[lap.key], along), 2, " s")
            travel = math.degrees(lap_map.heading_at(line, distance))
            angle, slip = travel, ""
            heading = self.lap_heading(lap, distance)
            if heading is not None:  # car pointing direction (recorded), driving direction: slip angle
                angle = math.degrees(heading + self._map_angle)
                drift = (angle - travel + 180) % 360 - 180
                slip = f"{drift:+.0f}°" if abs(drift) >= 1.5 else ""
            points.append({"x": interpolate(line.distances, line.xs, distance),
                           "y": interpolate(line.distances, line.ys, distance), "color": lap.color.name(),
                           "lap": lap.key, "angle": angle, "gap": gap, "slip": slip})
        return points

    def lap_heading(self, lap: PlotLap, distance: float) -> float | None:
        """Car heading on map at distance (radians, map not turned) from recorded yaw, None if not recorded

        Game yaw & map heading differ by a sign and an offset (game axes): both found on each lap from driving
        direction at speed, where car points nearly where it goes.
        """
        yaws = lap.data.columns.get("yaw")
        if not yaws or not any(yaws):
            return None
        cached = self._yaw.get(lap.key)
        if cached is None or cached[0] is not lap.data:
            cached = (lap.data, *yaw_calibration(lap.data))
            self._yaw = {key: value for key, value in self._yaw.items()
                         if key in {shown.key for shown in self.data.laps}}
            self._yaw[lap.key] = cached
        _, sign, offset = cached
        if sign == 0:
            return None
        distances = lap.data.distance
        index = min(max(bisect.bisect_left(distances, distance), 0), len(yaws) - 1)
        return sign * yaws[index] + offset

    @Slot(float, float, float, result=float)
    def mapPick(self, map_x: float, map_y: float, radius: float) -> float:
        """Axis position of reference line point nearest to map point, -1 if farther than radius"""
        if not self._map_lines:
            return -1.0
        _, lap = self._map_lines[0]
        grid = self._grids.get(lap.key)
        distance = grid.project(map_x, map_y, radius) if grid is not None else -1.0  # between samples
        return self.data.x_at_distance(distance) if distance >= 0 else -1.0

    @Slot(float, float, float, result=dict)
    def mapPickLap(self, map_x: float, map_y: float, radius: float) -> dict:
        """Lap line nearest to map point: lap key & axis position of that point on its lap, empty if none"""
        best, found = radius * radius, None
        for line, lap in self._map_lines:
            grid = self._grids.get(lap.key)
            index = grid.nearest(map_x, map_y, radius) if grid is not None else -1
            if index >= 0:
                gap = (line.xs[index] - map_x) ** 2 + (line.ys[index] - map_y) ** 2
                if gap <= best:
                    best, found = gap, (lap, grid.project(map_x, map_y, radius) if grid is not None else -1.0)
        if found is None:
            return {}
        lap, distance = found
        return {"lap": lap.key, "x": self.data.x_at_lap_distance(lap, distance)}

    @Slot(float, float, float, list, result=dict)
    def mapPointAt(self, map_x: float, map_y: float, radius: float, kinds: list) -> dict:
        """Driving point or wheel slip nearest to map point among shown kinds (tooltip), empty if none"""
        best, found = radius * radius, {}
        for point in self._map.get("points", []) + self._map.get("slips", []):
            if point["kind"] in kinds:
                gap = (point["x"] - map_x) ** 2 + (point["y"] - map_y) ** 2
                if gap <= best:
                    best, found = gap, point
        if found and "tip" not in found:  # wheel slip
            title = tr("Front wheel lockup") if found["kind"] == "lock" else tr("Rear wheelspin")
            found = {**found, "tip": f"{title} · {found['distance']:.0f} m", "corner": -1}
        return found

    @Slot(int, result=dict)
    def cornerCard(self, index: int) -> dict:
        """Every shown lap in corner (row of corner table): time, gap, speeds, braking & throttle points"""
        if not 0 <= index < len(self._corner_rows) or self.data.reference is None:
            return {}
        row = self._corner_rows[index]
        convert, unit = self.data.units["speed"]

        def speed(value: float) -> str:
            return f"{convert(value) if convert else value:.0f}"

        reference = self.lap_corner_stats(self.data.reference)[1][index]
        reference_line = self.lap_line(self.data.reference)
        turn = 0.0
        if reference_line is not None and len(reference_line.xs) > 2:
            turn = lap_map.turning(reference_line, min(bisect.bisect_left(reference_line.distances, row.corner.apex),
                                                       len(reference_line.xs) - 1))

        def room(lap: PlotLap, distance: float, inside: bool) -> str:
            """Room left to inside (apex) or outside edge (entry, exit), meters (distance: reference distance)"""
            found = self.lap_placement(lap, distance / self.data.scale_of(lap)) if distance >= 0 else None
            if found is None:
                return "—"
            left, right, _ = found
            value = (left if turn > 0 else right) if inside else (right if turn > 0 else left)
            return f"{value:.1f}"

        laps = []
        brakes = []
        for lap in self.data.laps:
            stats = self.lap_corner_stats(lap)[1][index]
            if stats is None:
                continue
            if stats.brake_point >= 0:
                brakes.append(stats.brake_point)
            gap = stats.time - reference.time if reference is not None and lap is not self.data.reference else None
            laps.append({
                "label": self.short_label(lap.key), "color": lap.color.name(),
                "time": f"{stats.time:.2f} s", "gap": signed(gap, 2) if gap is not None else "",
                "gapColor": COLOR_LOSS if gap is not None and gap > 0.005 else COLOR_GAIN if gap is not None
                and gap < -0.005 else "",
                "speeds": f"{speed(stats.entry_speed)} → {speed(stats.min_speed)} "
                          f"→ {speed(stats.exit_speed)} {unit}",  # entry, minimum, exit
                "brake": f"{stats.brake_point:.0f} m" if stats.brake_point >= 0 else "—",
                "throttle": f"{stats.throttle_point:.0f} m" if stats.throttle_point >= 0 else "—",
                # Room to edge: outside at braking point, inside at apex, outside at full throttle
                "width": (f"{room(lap, stats.brake_point, False)} → {room(lap, stats.apex, True)} → "
                          f"{room(lap, stats.throttle_point, False)} m") if self._edges[0] else "",
            })
        spread = max(brakes) - min(brakes) if len(brakes) > 1 else -1.0
        return {"title": self.row_label(row), "apex": f"{row.corner.apex:.0f} m", "laps": laps,
                "spread": trm(f"Braking points spread: {spread:.0f} m") if spread >= 0 else "",
                "widthTitle": tr("Room to edge: outside at braking, inside at apex, outside at exit")
                if self._edges[0] else ""}

    # XY tab: scatter of two channels, time spent in value ranges (histogram)
    @Property(list, notify=channelsChanged)
    def xyChannels(self) -> list[dict]:
        """Single channels available in shown laps: column, title (unit)"""
        rows = []
        for channel in CHANNELS:
            if channel.parts or (self.data.laps and not self.data.available(channel)):
                continue
            unit = self.data.unit_of(channel)
            rows.append({"column": channel.column, "title": channel_title(channel) + (f" ({unit})" if unit else "")})
        return rows

    def xy_samples(self, column: str, lap: PlotLap) -> tuple[Sequence[float], Sequence[float]]:
        """Reference distances & values of channel (user unit), zoomed chart part only when charts are zoomed"""
        if column not in CHANNEL_MAP or CHANNEL_MAP[column].parts:
            return [], []
        xs, ys = self.data.series(CHANNEL_MAP[column], lap, time_axis=False)
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
                "zero": [(0 - x_low) / (x_high - x_low), (0 - y_low) / (y_high - y_low)]}

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
            laps.append({"label": self.short_label(lap.key), "color": lap.color.name(), "values": shares})
        return {"bins": labels, "laps": laps, "max": top, "unit": self.data.unit_of(channel),
                "title": channel_title(channel)}

    # G circle: right turn on the right, braking at bottom
    def build_gcircle(self):
        self._g_points = []
        peaks = []
        shown = {lap.key for lap in self.data.laps}
        self._g_laps = {name: value for name, value in self._g_laps.items() if name in shown}
        self._g_drawn = {name: value for name, value in self._g_drawn.items() if name in shown}
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
        points = []
        for distances, xs, ys, lap in self._g_points:
            distance = self.data.lap_distance_at_x(lap, x)
            points.append({"x": interpolate(distances, xs, distance), "y": interpolate(distances, ys, distance),
                           "color": lap.color.name(), "lap": lap.key})
        return points

    # Replay
    def replay_target(self, lap: PlotLap, x: float) -> tuple[str, float] | None:
        """Replay file covering lap & position in it at axis position, None if no replay recorded then"""
        from ...replay import list_replays

        timestamp = lap_timestamp_of(os.path.basename(lap.key))  # lap end: real time, or replay time if replayed
        lap_time = lap.data.lap_time or lap_time_of(os.path.basename(lap.key))
        if timestamp <= 0 or lap_time <= 0:
            return None
        distances, times = self.data.lap_times(lap)
        at = interpolate(distances, times, self.data.lap_distance_at_x(lap, x)) if distances else 0.0
        moment = timestamp - lap_time + at
        replayed = str(lap.data.meta.get("replay", ""))
        candidates = list_replays(cfg.path.telemetry or ".")
        if replayed:  # lap recorded while replaying: that replay first
            candidates.sort(key=lambda item: os.path.basename(item.filename) != replayed)
        for item in candidates:
            end = item.created + (item.duration if item.duration >= 0 else 86400)
            if item.created - 2 <= moment <= end + 2:
                return item.filename, max(moment - item.created, 0.0)
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
        player = replay.player
        if player is None or os.path.normpath(player.replay.filename) != os.path.normpath(filename):
            view.open_file(filename)
            player = replay.player
        if player is not None and os.path.normpath(player.replay.filename) == os.path.normpath(filename):
            player.seek(position)
            player.set_paused(True)
            view.refresh()
            self.set_status(trm(f"Replay: {html.escape(os.path.basename(filename))} at {format_axis_time(position)}"))
