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
Lap viewer page parts: base of composed parts (children of LapViewerBackend, QML backend.<part>), helpers, page state
used by the mixins (track map, lap list, lap actions, lap loading, charts, XY tab)
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import QObject

from ..lap_viewer import PERCENT_RANGES, Channel, format_value, signed

if TYPE_CHECKING:
    import threading
    from collections import OrderedDict
    from collections.abc import Callable, Sequence
    from typing import Any

    from PySide6.QtCore import QFileSystemWatcher, QTimer, SignalInstance
    from PySide6.QtWidgets import QWidget

    from ...userfile import track_geometry
    from ...userfile.corner_analysis import CornerComparison, CornerStats, ResampledLap
    from ...userfile.lap_cache import IndexedInfos
    from ...userfile.telemetry_lap import LapData, LapFile
    from ..lap_viewer import LapEntry, PlotLap
    from . import lap_map
    from .lap_backend import JobHandle
    from .lap_charts import ChartTools
    from .lap_consistency import MapConsistency
    from .lap_corners import CornerTable
    from .lap_dashboard import DashboardTab
    from .lap_export import LapExports
    from .lap_library import TrackListModel
    from .lap_map_marks import MapMarks
    from .lap_map_pointer import MapPointer
    from .lap_session import SessionTab
    from .lines import VertexStore, Vertices
    from .models import DictListModel, FoldedListModel
    from .trace_data import TraceData

COLOR_GAIN = "gain"  # theme color names (QML theme.gain / theme.loss: readable on light & dark themes)
COLOR_LOSS = "loss"
HostType = TypeVar("HostType")


def weak_host(page: HostType) -> HostType:
    """Page seen by a part through a weak proxy: page keeps its parts, a part never keeps its page (no reference
    cycle: a closed page is freed at once, even one alive at a gc.freeze, see loader)"""
    return weakref.proxy(page)


def format_diff(channel: Channel, value: float) -> str:
    """Difference with reference lap at cursor: "-4" (typeset minus sign), "+12%" """
    if channel.fixed_range in PERCENT_RANGES:
        return signed(value * 100, 0, "%")
    if channel.column == "gear":
        return signed(value, 0)
    text = format_value(abs(value))
    return ("+" if value >= 0 else chr(0x2212)) + text


def int_setting(setting: dict, name: str, default: int) -> int:
    """Whole number of viewer setting, default if missing or not a number"""
    value = setting.get(name, default)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


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


class PagePart(QObject):
    """Part of lap viewer page: child QObject of LapViewerBackend with its own state, slots & properties (QML
    backend.<part>.<member>), page reached through an explicit host (Protocol of what the part uses, set as _page: weak_host)

    Created by the page (its parent: deleted with it), released when the page closes (see release).
    """

    def release(self):
        """Page closed: results kept by part forgotten (page jobs & timers stopped by page)"""


class BackendBase:
    """Base of the mixins of LapViewerBackend (track map: lap_map_view, lap list: lap_library, lap actions: lap_actions,
    lap loading: lap_loading, charts: lap_panels, XY tab: lap_xy): page state & methods they use

    Declared for type checking only: state is set & methods defined by LapViewerBackend, its mixins & its parts.
    """

    if TYPE_CHECKING:
        # Page state (set by LapViewerBackend.__init__ & its mixins)
        _added_batch: tuple[list[str], list[str], str] | None
        _arrows: tuple
        _band_cache: OrderedDict[float, dict[str, object]]
        _band_cache_applied: bool
        _band_generation: int
        _base: lap_map.MapLine
        _base_official: bool
        _best_text: str
        _cache_mtime: dict[str, float]
        _chart_afters: list[Callable[[], None]]
        _chart_changes: list[Callable[[TraceData], Any]]
        _chart_generation: int
        _chart_rejected: int
        _chart_running: bool
        _chart_view: tuple[float, float]
        _charts: ChartTools
        _chosen_reference: str
        _circuit_shapes: dict[float, tuple]
        _color_lines: tuple
        _color_slots: dict[str, int]
        _colored_shown: Vertices | None
        _colored_steps: dict[float, Vertices]
        _map_consistency: MapConsistency
        _map_marks: MapMarks
        _map_pointer: MapPointer
        _corner_table: CornerTable
        _cursor_state: tuple[tuple, dict] | None
        _dashboard: DashboardTab
        _delta_window: int
        _edge_normals: tuple
        _edges: tuple[list[float], list[float]]
        _edges_cache: tuple
        _envelope: bool
        _events: dict[str, tuple[tuple, list[tuple[float, str]]]]
        _expanded: list[str]
        _exports: LapExports
        _failed: set[str]
        _filter: str
        _g_drawn: dict[str, tuple]
        _g_envelope: bool
        _g_laps: dict[str, tuple]
        _g_points: list[tuple[Sequence[float], Sequence[float], Sequence[float], PlotLap]]
        _gcircle: dict
        _gcircle_stale: bool
        _geometry: track_geometry.TrackGeometry | None
        _geometry_track: str
        _geometry_tried: set[str]
        _grids: dict[str, lap_map.LineGrid]
        _groups: tuple[list[LapEntry], list] | None
        _hidden: bool
        _hide_unclean: bool
        _ideal_delta: bool
        _index_saves: dict[str, dict]
        _info_cache: dict[str, tuple[float, dict]]
        _infos_generation: int
        _infos_reading: bool
        _infos_track: str
        _labels: dict[str, str]
        _lap_cache: dict[str, LapData | None]
        _lap_offsets: dict[str, tuple[tuple, lap_map.MapLine, list[float], list[int]]]
        _lap_shapes: dict[tuple, tuple]
        _layout: str
        _legend: list[dict]
        _limits: lap_map.TrackLimits | None
        _limits_job: JobHandle | None
        _limits_reading: bool
        _limits_source: str
        _limits_token: int
        _limits_track: str
        _line_cache: dict[str, tuple[LapData, lap_map.MapLine | None]]
        _line_offsets: dict[str, Any]
        _list_revision: int
        _listing: set[str]
        _live: bool
        _load_message: str
        _load_plan: tuple | None
        _load_retries: int
        _load_timer: QTimer
        _load_total: int
        _loaded: dict[str, LapData | None]
        _loaded_paths: set[str]
        _loader: threading.Thread | None
        _map: dict
        _map_angle: float
        _map_aspect: float
        _map_auto_orient: bool
        _map_braking: bool
        _map_follow: bool
        _map_lines: list[tuple[lap_map.MapLine, PlotLap]]
        _map_mode: str
        _map_options: dict[str, bool]
        _map_quarters: int
        _map_range: tuple[float, float]
        _map_shown: int
        _map_slip: bool
        _map_view: tuple[float, float, float]
        _marks: dict[str, dict[str, dict]]
        _new_lap_tracks: set[str]
        _no_match: bool
        _normals: dict[str, tuple]
        _official_line: tuple
        _outline_cache: dict[str, list[tuple[float, float]]]
        _overview: dict
        _panels: list[dict]
        _panels_axis: bool
        _pending_batch: list[tuple[str, str, dict, bool, bool]] | None
        _pending_delete: list[str]
        _pending_switch: tuple[list[str], list[str], str] | None
        _picture_version: int
        _pit: list[lap_map.MapLine]
        _placements: dict[str, tuple[tuple, tuple]]
        _placing: int
        _prefetch_step: float
        _prefetch_timer: QTimer
        _prefetching: set[tuple[int, float]]
        _prepared: tuple | None
        _prepared_chart: tuple[TraceData, dict[str, Vertices], dict] | None
        _prepared_charts: list[tuple[TraceData, dict[str, Vertices], dict]]
        _prepared_checks: dict[tuple[str, str], tuple[tuple[float, float], bool | None]]
        _prepared_laps: list[tuple[dict, dict]]
        _prepared_placements: dict[str, tuple[tuple, tuple]]
        _preparing: tuple | None
        _preview_step: float
        _refresh_pending: bool
        _release_timer: QTimer
        _released: bool
        _released_view: tuple[float, float]
        _replay_lookup: bool
        _restore_view: tuple[float, float] | None
        _revision: int
        _road: lap_map.MapLine
        _selected_corner: int
        _session: SessionTab
        _shape_checks: dict[tuple[str, str], tuple[tuple[float, float], bool | None]]
        _side_tab: int
        _simple_view: bool
        _smoothing: int
        _speed_range: tuple[float, float]
        _status: str
        _switch_to: tuple[str, set[str], str] | None
        _switched: bool
        _time_axis: bool
        _track: str
        _track_rows: tuple
        _track_sectors: list[float]
        _tracks: list[str]
        _trail_revision: int
        _trail_state: tuple[dict, float, list[float]] | None
        _trash_loading: bool
        _trash_rows: list[dict]
        _turned: dict[str, tuple]
        _undo: list[list[tuple[str, str, dict, bool, bool]]]
        _warning: str
        _watch_timer: QTimer
        _watched: dict[str, tuple]
        _watcher: QFileSystemWatcher
        _weights: dict[str, float]
        _window: QWidget
        _xy: dict[str, str]
        _xy_keys: set[str]
        _zones: dict[str, tuple[LapData, tuple]]
        _zoom_timer: QTimer
        channelsChanged: SignalInstance
        chartChanged: SignalInstance
        checked: set[str]
        data: TraceData
        entries: list[LapEntry]
        external: list[LapEntry]
        folder: str
        gCircleChanged: SignalInstance
        lap_model: FoldedListModel
        lapsTrashed: SignalInstance
        legend_model: DictListModel
        listChanged: SignalInstance
        map_lap_model: DictListModel
        mapChanged: SignalInstance
        mapDataChanged: SignalInstance
        optionsChanged: SignalInstance
        panel_model: DictListModel
        panelsChanged: SignalInstance
        picturesChanged: SignalInstance
        pinChanged: SignalInstance
        prefix: str
        reference_key: str
        selectionChanged: SignalInstance
        series_models: dict[str, DictListModel]
        track_model: TrackListModel
        tracksChanged: SignalInstance
        trailChanged: SignalInstance
        trashChanged: SignalInstance
        undoChanged: SignalInstance
        viewRestored: SignalInstance
        visible: list[str]

        # Methods of LapViewerBackend & its mixins
        def all_entries(self) -> list[LapEntry]: ...
        def apply_delete(self, paths: list[str], pending: bool = False) -> bool: ...
        def build_colored_line(self, meters_per_pixel: float): ...
        def build_gcircle(self, now: bool = False): ...
        def build_gcircle_zoom(self): ...
        def build_labels(self, laps: list[PlotLap]): ...
        def build_map(self): ...
        def build_trails(self, x: float): ...
        def bump_revision(self): ...
        def chart_vertices(self, data: TraceData, visible: Sequence[str], envelope: bool,
                           have: Callable[[str], bool] = VertexStore.has,
                           pause: Callable[[], None] | None = None) -> dict[str, Vertices]: ...
        def circuit_hints(self) -> Callable[[dict], dict]: ...
        @staticmethod
        def circuit_names(paths: list[str], infos: dict[str, dict]) -> list[str]: ...
        def compared_lap(self) -> PlotLap | None: ...
        def corner_rows(self) -> list[CornerComparison]: ...
        def cursorState(self, x: float) -> dict: ...
        @staticmethod
        def entry_conditions(entry: LapEntry) -> str: ...
        def fill_list(self): ...
        def g_positions(self, x: float) -> list[float]: ...
        def gCursor(self, x: float) -> list[dict]: ...
        def keep_placements(self, prepared: dict): ...
        def lap_corner_stats(self, lap: PlotLap) -> tuple[ResampledLap, list[CornerStats | None]]: ...
        def lap_info(self, path: str) -> dict: ...
        def lap_marks(self, path: str) -> dict: ...
        def lap_rows(self) -> list[dict]: ...
        def limits_parts_folder(self, track: str) -> str: ...
        def load_lap_file(self, path: str) -> LapData: ...
        def load_laps(self): ...
        def load_track(self, track: str, new_lap: LapFile | None = None, background: bool = True): ...
        def main_circuit(self) -> tuple[dict, str]: ...
        def mark_values(self, entry: LapEntry, vehicle: str) -> dict: ...
        def notify_status(self): ...
        def official_base(self, length: float=0.0) -> lap_map.MapLine | None: ...
        def ordered_checked(self) -> list[str]: ...
        def other_circuit(self, main: tuple[dict, str], info: dict, path: str) -> bool: ...
        def place_laps(self): ...
        def placements_current(self, prepared: dict) -> bool: ...
        def rebuild_chart(self): ...
        def row_label(self, row: CornerComparison) -> str: ...
        def run_job(self, name: str, work: Callable[[], Any], done: Callable[[Any], None]): ...
        def run_process_job(self, name: str, done: Callable[[Any], None], function: Callable, *args): ...
        def save_selection(self, paths: list[str]): ...
        def series_count(self) -> int: ...
        def set_status(self, text: str, transient: bool = True): ...
        def short_label(self, key: str) -> str: ...
        def start_geometry(self, track: str): ...
        def start_limits(self, track: str): ...
        def start_limits_job(self, job: dict): ...
        def switch_circuit(self, paths: list[str], shown: list[str], reference: str, refused: str = ""): ...
        def track_infos(self, track: str, laps: list[LapFile], indexed: IndexedInfos | None = None) -> list[dict]: ...
        def track_sessions(self) -> list: ...
        def update_base(self): ...
        def update_gcircle_zoom(self): ...
        def update_list_state(self, laps: list[PlotLap]): ...
        def zoom_distances(self) -> tuple[float, float]: ...
