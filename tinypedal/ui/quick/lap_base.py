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
Lap viewer page state shared by its parts (lap_backend & mixins: map, corners, session, export): helpers & attributes
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..lap_viewer import PERCENT_RANGES, Channel, format_value, signed

if TYPE_CHECKING:
    from collections import OrderedDict
    from collections.abc import Callable
    from typing import Any

    from PySide6.QtCore import QTimer, SignalInstance
    from PySide6.QtWidgets import QWidget

    from ...userfile import track_geometry
    from ...userfile.corner_analysis import CornerComparison, CornerStats, IdealLap, ResampledLap
    from ...userfile.telemetry_lap import LapData
    from ...userfile.track_corners import TrackCorner
    from ..lap_viewer import LapEntry, PlotLap
    from . import lap_map
    from .lines import Vertices
    from .math_channels import MathChannel
    from .models import DictListModel
    from .trace_data import TraceData

COLOR_GAIN = "gain"  # theme color names (QML theme.gain / theme.loss: readable on light & dark themes)
COLOR_LOSS = "loss"


def format_diff(channel: Channel, value: float) -> str:
    """Difference with reference lap at cursor: "-4" (typeset minus sign), "+12%" """
    if channel.fixed_range in PERCENT_RANGES:
        return signed(value * 100, 0, "%")
    if channel.column == "gear":
        return signed(value, 0)
    text = format_value(abs(value))
    return ("+" if value >= 0 else chr(0x2212)) + text


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


class BackendBase:
    """Base of lap viewer page parts (mixins of LapViewerBackend, see lap_backend): page state & methods they use

    Declared for type checking only: state is set & methods defined by LapViewerBackend & its other parts.
    """

    if TYPE_CHECKING:
        # Page state (set by LapViewerBackend.__init__)
        _align_apex: float
        _arrows: tuple
        _autoscale: set[str]
        _band_cache: OrderedDict[float, dict[str, object]]
        _band_cache_applied: bool
        _band_generation: int
        _base: lap_map.MapLine
        _base_official: bool
        _circuit_shapes: dict[float, tuple]
        _coaching: list[dict]
        _color_lines: tuple
        _colored_shown: Vertices | None
        _colored_steps: dict[float, Vertices]
        _compare_key: str
        _consistency: dict
        _consistency_scope: str
        _corner_key: tuple
        _corner_marks: list[dict]
        _corner_rows: list[CornerComparison]
        _corner_sort: str
        _corners: list[dict]
        _edge_normals: tuple
        _edges: tuple[list[float], list[float]]
        _edges_cache: tuple
        _events: dict[str, tuple[tuple, list[tuple[float, str]]]]
        _exports: int
        _geometry: track_geometry.TrackGeometry | None
        _grids: dict[str, lap_map.LineGrid]
        _hysteresis: int
        _ideal: IdealLap | None
        _imports: int
        _lap_corners: dict[str, tuple[tuple, ResampledLap, list[CornerStats | None]]]
        _lap_offsets: dict[str, tuple[tuple, lap_map.MapLine, list[float], list[int]]]
        _lap_shapes: dict[tuple, tuple]
        _legend: list[dict]
        _limits: lap_map.TrackLimits | None
        _limits_source: str
        _line_cache: dict[str, tuple[LapData, lap_map.MapLine | None]]
        _line_offsets: dict[str, Any]
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
        _trail_state: tuple[dict, float, list[float]] | None
        _math: list[MathChannel]
        _mini_busy: bool
        _mini_times: dict[str, tuple[float, tuple, list[float]]]
        _normals: dict[str, tuple]
        _official: list[TrackCorner]
        _official_key: tuple | None
        _official_numbered: bool
        _outline_cache: dict[str, list[tuple[float, float]]]
        _panels: list[dict]
        _pit: list[lap_map.MapLine]
        _placements: dict[str, tuple[tuple, tuple]]
        _prefetch_step: float
        _prefetch_timer: QTimer
        _prefetching: set[float]
        _preview_step: float
        _resampled: dict[str, ResampledLap]
        _road: lap_map.MapLine
        _selected_corner: int
        _session_busy: bool
        _session_extra: dict[str, tuple[float, dict]]
        _session_key: str
        _side_tab: int
        _similar_tolerance: int
        _slips: dict[str, tuple[LapData, list]]
        _speed_range: tuple[float, float]
        _track: str
        _trackouts: dict[str, tuple[tuple, dict[int, float]]]
        _trail_revision: int
        _turned: dict[str, tuple]
        _weights: dict[str, float]
        _window: QWidget
        _yaw: dict[str, tuple[LapData, float, float]]
        _zones: dict[str, tuple[LapData, tuple]]
        chartChanged: SignalInstance
        cornersChanged: SignalInstance
        mapDataChanged: SignalInstance
        panelsChanged: SignalInstance
        checked: set[str]
        data: TraceData
        entries: list[LapEntry]
        external: list[LapEntry]
        folder: str
        legend_model: DictListModel
        mapChanged: SignalInstance
        map_lap_model: DictListModel
        mathChanged: SignalInstance
        optionsChanged: SignalInstance
        pinChanged: SignalInstance
        prefix: str
        reference_key: str
        sessionChanged: SignalInstance
        trailChanged: SignalInstance
        visible: list[str]

        # Methods of LapViewerBackend & its other parts
        def add_external(self, lap_paths: list[str], reference_from: list[str] | None=None,
                         checked: list[str] | None=None): ...
        def all_entries(self) -> list[LapEntry]: ...
        def build_colored_line(self, meters_per_pixel: float): ...
        def build_map_bands(self): ...
        def build_panels(self): ...
        def bump_revision(self): ...
        def channels_updated(self, save: bool=True): ...
        def compared_lap(self) -> PlotLap | None: ...
        def drop_unused_vertices(self): ...
        def fill_list(self): ...
        def lap_corner_stats(self, lap: PlotLap) -> tuple[ResampledLap, list[CornerStats | None]]: ...
        def lap_line(self, lap: PlotLap) -> lap_map.MapLine | None: ...
        def lap_offsets(self, lap: PlotLap) -> tuple[lap_map.MapLine, list[float], list[int]] | None: ...
        def lap_placement(self, lap: PlotLap, distance: float) -> tuple[float, float, float] | None: ...
        def load_laps(self): ...
        def lap_trackouts(self, lap: PlotLap, stats: list[CornerStats | None], turns: dict[int, float], reference_line: lap_map.MapLine) -> dict[int, float]: ...
        def map_corner_points(self) -> list[dict]: ...
        def map_driving_points(self) -> list[dict]: ...
        def map_sector_labels(self) -> list[dict]: ...
        def official_base(self, length: float=0.0) -> lap_map.MapLine | None: ...
        def official_in(self, row: CornerComparison) -> list[TrackCorner]: ...
        def official_text(self, label: str) -> str: ...
        def ordered_checked(self) -> list[str]: ...
        def read_lap(self, path: str) -> LapData | None: ...
        def reference_map_line(self) -> lap_map.MapLine | None: ...
        def resampled(self, lap: PlotLap) -> ResampledLap: ...
        def row_label(self, row: CornerComparison) -> str: ...
        def run_job(self, name: str, work: Callable[[], Any], done: Callable[[Any], None]): ...
        def run_process_job(self, name: str, done: Callable[[Any], None], function: Callable, *args): ...
        def session_row(self, group: list[LapEntry], is_added: bool) -> dict: ...
        def set_status(self, text: str, transient: bool=True): ...
        def short_label(self, key: str) -> str: ...
        def track_name(self) -> str: ...
        def track_sessions(self) -> list: ...
