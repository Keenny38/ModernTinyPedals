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
Overlay base common class.
"""

from __future__ import annotations

import re
from math import isfinite
from time import monotonic, strftime
from typing import Any, NamedTuple

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QWidget

from .. import calculation as calc
from ..api_control import api
from ..const_common import MAX_SECONDS, MIN_IMPACT_MAGNITUDE
from ..module_info import VehicleDataSet, minfo
from ..validator import generator_init
from ._snapping import constrain_axis, grid_value, snap_position

NO_PLAYER = VehicleDataSet()  # neutral car data (read only): no player car (spectating, player left)


def player_vehicle() -> VehicleDataSet:
    """Player car data of vehicles module, neutral data (NO_PLAYER) if no player car (player index -1): never
    the last car of the list (dataSet[-1])"""
    vehicles = minfo.vehicles
    index = vehicles.playerIndex
    data_set = vehicles.dataSet
    return data_set[index] if 0 <= index < len(data_set) else NO_PLAYER


def player_race_laps(est_remaining: float) -> tuple[float, float]:
    """Player laps done (completed laps + lap progress) & race finish lap, same count in Laps and position and
    Session overlays. Both from game scoring, updated together (LMU telemetry lap number equals completed laps
    while driving, recorded sessions, but updates one frame before scoring at the line: never mixed with them).
    Timed race ends on crossing the line after the timer: finish lap rounded up"""
    lap_into = api.read.lap.progress()
    laps_completed = api.read.lap.completed_laps()
    if api.read.session.finish_type(minfo.vehicles.finishAsLap):
        return laps_completed + lap_into, api.read.lap.maximum()
    laps_timer = calc.end_timer_laps_remain(lap_into, minfo.delta.lapTimePace, est_remaining)
    return laps_completed + lap_into, laps_completed + calc.ceil(laps_timer)


def system_clock_samples(clock_format: str) -> tuple[str, ...]:
    """Texts of system clock format to size its value: every day & month name (Wednesday, September...), morning &
    afternoon, every digit as 8 (widest digit, digits are tabular); format itself if invalid"""
    try:
        return tuple(
            re.sub(r"\d", "8", strftime(clock_format, (2021, month, 28, 10 + month % 2 * 12, 58, 58, month % 7, 1, 0)))
            for month in range(1, 13)
        )
    except ValueError:
        return (clock_format,)


class SessionBestLap:
    """Session best lap time of all cars (or player class), one car read per update (Timing overlays): cleared on
    new or restarted session, as overlay may stay shown from one session to the next (spectating, streamed)"""

    __slots__ = ("laptime", "index", "session", "elapsed")

    def __init__(self):
        self.reset()

    def reset(self):
        """Read again from first car"""
        self.laptime = MAX_SECONDS
        self.index = 0
        self.session = -1
        self.elapsed = 0.0

    def update(self, same_class_only: bool) -> float:
        """Best lap time so far"""
        session = api.read.session.identifier()[0]
        elapsed = api.read.session.elapsed()
        if session != self.session or elapsed < self.elapsed - 1:  # new session, or same session restarted
            self.laptime = MAX_SECONDS
            self.session = session
        self.elapsed = elapsed
        # Bounded before reading: fewer cars than at last update (car left) would read a stale slot past the field
        if self.index >= api.read.vehicle.total_vehicles():
            self.index = 0
        if not same_class_only or api.read.vehicle.same_class(self.index):
            best = api.read.timing.best_laptime(self.index)
            if 0 < best < self.laptime:
                self.laptime = best
        self.index += 1  # one car per update, wrap after last car
        return self.laptime


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


def lap_reference(source: str, game_delta: bool = False) -> float:
    """Reference lap time of lap under way (read once lap started, kept until line, see lap_delta_shown): 0 if
    reference is last lap and it went through pit lane (out lap, pit in lap: not comparable). Game delta shown
    (game_deltabest): best lap as defined by game, that live game delta compares against (no jump at line)"""
    delta = minfo.delta
    if source == "Last" and not delta.hasLastLap:
        return 0.0
    laptime = getattr(delta, f"lapTime{source}", 0.0)
    if game_delta and 0 < laptime < MAX_SECONDS:  # live delta shown (app reference exists)
        game_live = api.read.timing.delta_best()
        game_best = api.read.timing.best_laptime()
        if game_live and isfinite(game_live) and 0 < game_best < MAX_SECONDS:
            return game_best
    return laptime


def game_deltabest(app_delta: float) -> float:
    """Delta to best lap computed by game (LMU), app computed delta if game gives none (0)"""
    delta = api.read.timing.delta_best()
    return delta if delta and isfinite(delta) else app_delta


def tyre_punctured() -> tuple[bool, ...]:
    """Flat tyre state from game, or tyre worn through (tread at 1% or less, game state missed)"""
    return tuple(flat or worn for flat, worn in zip(api.read.tyre.flat(), api.read.tyre.puncture()))


def impact_cone_position() -> tuple[float, float] | None:
    """Position (x, y) of last impact if strong enough for impact cone, None for light or empty impact"""
    if api.read.vehicle.impact_magnitude() < MIN_IMPACT_MAGNITUDE:
        return None
    position = api.read.vehicle.impact_position()
    return position if any(position) else None


# Flashes of every overlay (warnings, alerts, flags, pedal bars, damage pulse): one phase rule (flash_lit)
FLASH_MINIMUM = 0.2  # seconds: shortest lit or dark part of a flash
FAST_FLASH_MINIMUM = 0.05  # pedal bar alerts (ABS, TC, wheel lock & spin) flicker faster


def flash_lit(elapsed: float, on: float, off: float | None = None, minimum: float = FLASH_MINIMUM) -> bool:
    """Flash lit elapsed seconds after it started: lit for on seconds, then dark for off seconds (default: on),
    each at least minimum seconds"""
    on = max(on, minimum)
    off = on if off is None else max(off, minimum)
    return elapsed % (on + off) < on


@generator_init
def warning_flash(duration: float, interval: float, max_count: int):
    """Warning flash state while condition sent is true: lit for duration, dark for interval (flash_lit), steady
    lit from flash number max_count on (at least 3)"""
    lit_seconds = max(duration, FLASH_MINIMUM)
    period = lit_seconds + max(interval, FLASH_MINIMUM)
    flash_max = max(max_count, 3)
    start = -1.0  # when condition became true, -1 while false
    highlight = False

    while True:
        condition = yield highlight
        if not condition:
            start = -1.0
            highlight = False
            continue
        elapsed = monotonic()
        if start < 0:
            start = elapsed
        age = elapsed - start
        highlight = age // period >= flash_max - 1 or flash_lit(age, lit_seconds, period - lit_seconds)
