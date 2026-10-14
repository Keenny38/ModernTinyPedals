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
used by the track map mixin
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, TypeVar

from PySide6.QtCore import QObject

from ..lap_viewer import PERCENT_RANGES, Channel, format_value, signed

if TYPE_CHECKING:
    from collections import OrderedDict
    from collections.abc import Callable
    from typing import Any

    from PySide6.QtCore import QTimer, SignalInstance

    from ...userfile import track_geometry
    from ...userfile.corner_analysis import CornerComparison, CornerStats, ResampledLap
    from ...userfile.telemetry_lap import LapData
    from ..lap_viewer import PlotLap
    from . import lap_map
    from .lap_corners import CornerTable
    from .lines import Vertices
    from .models import DictListModel
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
    """Base of track map mixin of LapViewerBackend (see lap_map_view): page state & methods it uses

    Declared for type checking only: state is set & methods defined by LapViewerBackend & its parts.
    """

    if TYPE_CHECKING:
        # Page state (set by LapViewerBackend.__init__)
        _corner_table: CornerTable
        _arrows: tuple
        _band_cache: OrderedDict[float, dict[str, object]]
        _band_cache_applied: bool
        _band_generation: int
        _base: lap_map.MapLine
        _base_official: bool
        _circuit_shapes: dict[float, tuple]
        _color_lines: tuple
        _colored_shown: Vertices | None
        _colored_steps: dict[float, Vertices]
        _consistency: dict
        _consistency_scope: str
        _edge_normals: tuple
        _edges: tuple[list[float], list[float]]
        _edges_cache: tuple
        _events: dict[str, tuple[tuple, list[tuple[float, str]]]]
        _geometry: track_geometry.TrackGeometry | None
        _grids: dict[str, lap_map.LineGrid]
        _lap_offsets: dict[str, tuple[tuple, lap_map.MapLine, list[float], list[int]]]
        _lap_mtimes: tuple[int, dict[str, float | None]]
        _lap_shapes: dict[tuple, tuple]
        _line_boxes: tuple
        _list_revision: int
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
        _map_kinds: list[str]
        _map_lines: list[tuple[lap_map.MapLine, PlotLap]]
        _map_mode: str
        _map_options: dict[str, bool]
        _map_quarters: int
        _map_range: tuple[float, float]
        _map_shown: int
        _map_slip: bool
        _map_view: tuple[float, float, float]
        _trail_state: tuple[dict, float, list[float]] | None
        _mini_busy: bool
        _mini_times: dict[str, tuple[float, tuple, list[float]]]
        _normals: dict[str, tuple]
        _official_line: tuple
        _outline_cache: dict[str, list[tuple[float, float]]]
        _pit: list[lap_map.MapLine]
        _placements: dict[str, tuple[tuple, tuple]]
        _placing: int
        _prepared_placements: dict[str, tuple[tuple, tuple]]
        _prefetch_step: float
        _prefetch_timer: QTimer
        _prefetching: set[tuple[int, float]]
        _preview_step: float
        _road: lap_map.MapLine
        _selected_corner: int
        _slips: dict[str, tuple[LapData, list]]
        _speed_range: tuple[float, float]
        _trail_revision: int
        _turned: dict[str, tuple]
        _yaw: dict[str, tuple[LapData, float, float]]
        _zones: dict[str, tuple[LapData, tuple]]
        chartChanged: SignalInstance
        mapDataChanged: SignalInstance
        data: TraceData
        folder: str
        mapChanged: SignalInstance
        map_lap_model: DictListModel
        pinChanged: SignalInstance
        prefix: str
        reference_key: str
        trailChanged: SignalInstance

        # Methods of LapViewerBackend & its other parts
        def bump_revision(self): ...
        def cursorState(self, x: float) -> dict: ...
        def compared_lap(self) -> PlotLap | None: ...
        def lap_corner_stats(self, lap: PlotLap) -> tuple[ResampledLap, list[CornerStats | None]]: ...
        def official_base(self, length: float=0.0) -> lap_map.MapLine | None: ...
        def rebuild_chart(self): ...
        def row_label(self, row: CornerComparison) -> str: ...
        def corner_rows(self) -> list[CornerComparison]: ...
        def run_job(self, name: str, work: Callable[[], Any], done: Callable[[Any], None]): ...
        def run_process_job(self, name: str, done: Callable[[Any], None], function: Callable, *args): ...
        def short_label(self, key: str) -> str: ...
        def track_sessions(self) -> list: ...
