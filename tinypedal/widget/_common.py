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
Overlay base common class.
"""

from __future__ import annotations

from math import isfinite
from time import monotonic
from typing import Any, NamedTuple

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QWidget

from ..api_control import api
from ..const_common import MAX_SECONDS
from ..module_info import minfo
from ..validator import generator_init
from ._snapping import constrain_axis, grid_value, snap_position


class FontMetrics(NamedTuple):
    """Font metrics info"""

    width: int = 0
    height: int = 0
    leading: int = 0
    capital: int = 0
    descent: int = 0
    voffset: int = 0


class MousePosition:
    """Overlay drag: grab offset, magnetic snapping, grid, axis lock

    Magnetic snapping (edges & centers of screen and other overlays) is on by default
    (`enable_magnetic_snap`): hold Ctrl to move freely. With magnetic snapping off, Ctrl snaps
    (former behavior). Shift keeps the move on one axis. Grid move rounds the axes not snapped.
    """

    __slots__ = (
        "_init_pos",
        "_start",
        "_screen_name",
        "_others",
        "_screens",
        "_grid_move",
        "_grid_size",
        "_snap_gap",
        "_snap_distance",
        "_magnetic",
        "snapped",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset"""
        self._init_pos: Any = None
        self._start: QPoint | None = None
        self._screen_name: str | None = None
        self._others: list[QRect] = []
        self._screens: list[QRect] = []
        self._grid_move = False
        self._grid_size = 1
        self._snap_gap = 0
        self._snap_distance = 0
        self._magnetic = False
        self.snapped = (False, False)

    def valid(self) -> bool:
        """Is initial position valid"""
        return isinstance(self._init_pos, QPoint)

    def config(
        self, init_pos: QPoint, grid_move: bool, grid_size: int, snap_gap: int, snap_distance: int,
        magnetic: bool = False, start: QPoint | None = None,
    ):
        """Config mouse move

        Args:
            init_pos: grab position in widget.
            grid_move: round position to grid.
            grid_size: grid size in pixels.
            snap_gap: space kept between snapped overlays (and from screen edges).
            snap_distance: snapping distance in pixels.
            magnetic: snap without Ctrl held.
            start: widget position when grabbed, for Shift axis lock.
        """
        self._init_pos = init_pos
        self._start = start
        self._screen_name = None
        self._grid_move = grid_move
        self._grid_size = max(grid_size, 1)
        self._snap_gap = max(0, snap_gap)
        self._snap_distance = max(snap_gap, snap_distance)
        self._magnetic = magnetic
        self.snapped = (False, False)

    def update_grid(self, widget: QWidget):
        """Update snapping references (screen & other overlays) when widget changes screen

        Other overlays do not move while one is dragged: read once per screen.
        """
        screen = widget.screen()
        if self._screen_name == screen.name():
            return
        self._screen_name = screen.name()
        # Full screen area & restricted area (excludes task bar, system menu, etc)
        self._screens = [screen.geometry(), screen.availableGeometry()]
        self._others = []
        try:
            for other_widget in QApplication.topLevelWidgets():
                if (
                    not hasattr(other_widget, "widget_name")
                    or widget is other_widget
                    or not other_widget.isVisible()
                    or screen is not other_widget.screen()
                ):
                    continue
                self._others.append(other_widget.geometry())
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass

    def position(self, widget: QWidget, global_pos: QPoint, modifiers: Qt.KeyboardModifier) -> QPoint:
        """New widget position for mouse position"""
        pos = global_pos - self._init_pos
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier) and self._start is not None
        if shift:
            pos = constrain_axis(self._start, pos)  # type: ignore[arg-type]
        snapped_x = snapped_y = False
        if self._magnetic != ctrl:  # Ctrl inverts magnetic snapping
            self.update_grid(widget)
            pos, snapped_x, snapped_y = snap_position(
                QRect(pos, widget.size()), self._others, self._screens, self._snap_distance, self._snap_gap)
        if self._grid_move and not (self._magnetic and ctrl):  # free move: Ctrl with magnetic snapping
            if not snapped_x:
                pos.setX(grid_value(pos.x(), self._grid_size))
            if not snapped_y:
                pos.setY(grid_value(pos.y(), self._grid_size))
        if shift:  # snapping or grid never leaves locked axis
            pos = constrain_axis(self._start, pos)  # type: ignore[arg-type]
        self.snapped = (snapped_x, snapped_y)
        return pos


def delta_shown(source: str) -> bool:
    """Delta to reference lap of source ("Best", "Session", "Stint", "Last") can be shown: reference
    lap exists, current lap comparable (not an out lap from pit lane or garage, whose time counts,
    not in pit lane before start line)"""
    delta = minfo.delta
    if not delta.isDeltaAvailable:
        return False
    if source == "Last":
        return delta.hasLastLap
    return 0 < getattr(delta, f"lapTime{source}", 0.0) < MAX_SECONDS


def lap_delta_shown(reference_laptime: float) -> bool:
    """Lap time difference of lap just completed can be shown (shown a few seconds after line, see
    freeze_duration): completed lap comparable, reference lap existed when it started"""
    return minfo.delta.hasLastLap and 0 < reference_laptime < MAX_SECONDS


def game_deltabest(app_delta: float) -> float:
    """Delta to best lap computed by game (LMU), app computed delta if game gives none (0)"""
    delta = api.read.timing.delta_best()
    return delta if delta and isfinite(delta) else app_delta


def tyre_punctured() -> tuple[bool, ...]:
    """Flat tyre state from game, or tyre worn through (tread at 1% or less, game state missed)"""
    return tuple(flat or worn for flat, worn in zip(api.read.tyre.flat(), api.read.tyre.puncture()))


@generator_init
def warning_flash(duration: float, interval: float, max_count: int):
    """Warning flash state"""
    last_condition = False
    highlight = False
    highlight_seconds = max(duration, 0.2)
    highlight_timer = 0.0
    interval_seconds = max(interval, 0.2)
    interval_timer = 0.0
    flash_count = 0
    flash_max = max(max_count, 3)

    while True:
        condition = yield highlight
        elapsed = monotonic()

        if last_condition != condition:
            last_condition = condition
            if condition:
                highlight_timer = elapsed
                highlight = False
                interval_timer = 0
                flash_count = 0

        if not condition:
            highlight = False
            continue
        elif flash_count >= flash_max:
            highlight = True
            continue

        if elapsed - highlight_timer < highlight_seconds:
            if not highlight:
                flash_count += 1
            highlight = True
            interval_timer = elapsed
        else:
            highlight = False
            if elapsed - interval_timer >= interval_seconds:
                highlight_timer = elapsed
