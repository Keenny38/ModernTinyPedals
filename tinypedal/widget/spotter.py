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
Spotter Widget

Two slim side bars (left & right, meant for screen edges) lit while a car is alongside, like a
spotter: lit part of bar is the part of player car overlapped by the other car (top = front),
critical color when it is close sideways. "Clear" signal: bar flashes green when the side
becomes free again. Car coming up behind on a side (not yet alongside) lights the bottom of
the bar, brighter as it gets closer. Cars come from vehicles module, same relative positions
as radar.
"""

from __future__ import annotations

from itertools import islice
from time import monotonic
from typing import Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from ..module_info import minfo
from ._base import Overlay
from ._race_aids import HiddenPreview, finite

PRECISION = 2  # overlap fraction decimals (bar redrawn only when lit part moves visibly)
CLEAR_STEPS = 10  # fade steps of clear signal (widget redrawn only on step change)
APPROACH_ZONE = 0.35  # bottom part of bar lit by car coming up behind


class Side(NamedTuple):
    """Overlap of cars on one side of player car: lit part of bar (0 = front, 1 = rear),
    closeness of nearest car sideways (0 at nearby distance, 1 at critical distance or closer)"""

    top: float = 0.0
    bottom: float = 0.0
    critical: bool = False
    closeness: float = 0.0

    @property
    def lit(self) -> bool:
        return self.bottom > self.top


NO_CAR = Side()


class SpotterState(NamedTuple):
    """Both side bars: overlap, clear signal step (0 = none), car coming up behind (0 to 1)"""

    left: Side = NO_CAR
    right: Side = NO_CAR
    clear: tuple[int, int] = (0, 0)
    approach: tuple[float, float] = (0.0, 0.0)

    @property
    def shown(self) -> bool:
        """Something to draw"""
        return self.left.lit or self.right.lit or any(self.clear) or any(self.approach)


NO_STATE = SpotterState()


def side_overlap(cars, length: float, nearby: float, critical: float) -> tuple[Side, Side]:
    """Overlap on left & right side, from relative positions of cars (meters, -x left, -y ahead)

    Args:
        cars: (relative x, relative y) of other cars.
        length: car length.
        nearby: lateral distance (center to center) under which a car is alongside.
        critical: lateral distance under which car alongside is critical.
    """
    half = length / 2
    left_top = right_top = 1.0
    left_bottom = right_bottom = 0.0
    left_gap = right_gap = nearby
    for pos_x, pos_y in cars:
        if not (finite(pos_x) and finite(pos_y)) or abs(pos_x) > nearby or abs(pos_y) >= length:
            continue
        top = (max(-half, pos_y - half) + half) / length  # overlapped part of player car
        bottom = (min(half, pos_y + half) + half) / length
        if pos_x < 0:
            left_top = min(left_top, top)
            left_bottom = max(left_bottom, bottom)
            left_gap = min(left_gap, -pos_x)
        else:
            right_top = min(right_top, top)
            right_bottom = max(right_bottom, bottom)
            right_gap = min(right_gap, pos_x)
    return (side(left_top, left_bottom, left_gap, nearby, critical),
            side(right_top, right_bottom, right_gap, nearby, critical))


def side(top: float, bottom: float, gap: float, nearby: float, critical: float) -> Side:
    """Side overlap, rounded (no car if nothing overlapped)"""
    if bottom <= top:
        return NO_CAR
    span = nearby - critical
    closeness = 1.0 if gap <= critical or span <= 0 else min(max((nearby - gap) / span, 0.0), 1.0)
    return Side(round(top, PRECISION), round(bottom, PRECISION), gap <= critical, round(closeness, 1))


def side_approach(cars, length: float, nearby: float, distance: float, min_side: float = 0.0) -> tuple[float, float]:
    """Car coming up behind on left & right side, not alongside yet: 0 (none, or distance away)
    to 1 (about to overlap), from relative positions of cars (meters, -x left, -y ahead)

    Args:
        cars: (relative x, relative y) of other cars.
        length: car length.
        nearby: lateral distance (center to center) of a car on the side.
        distance: gap (other car front to player car rear) from which a car is shown.
        min_side: lateral distance under which a car is in player lane (straight behind, not on a side).
    """
    left = right = 0.0
    if not distance > 0:
        return left, right
    for pos_x, pos_y in cars:
        if not (finite(pos_x) and finite(pos_y)) or not min_side <= abs(pos_x) <= nearby or pos_y < length:
            continue
        gap = pos_y - length
        if gap >= distance:
            continue
        closeness = round(1.0 - gap / distance, 1)
        if pos_x < 0:
            left = max(left, closeness)
        else:
            right = max(right, closeness)
    return left, right


class SpotterMixin:
    """Side overlap, clear signal & cars coming up behind, for classic & modern widget"""

    wcfg: Any

    def setup_spotter(self):
        """Options, last state"""
        wcfg = self.wcfg
        self.length = max(float(wcfg["vehicle_length"]), 0.5)
        self.nearby = max(float(wcfg["nearby_side_distance"]), float(wcfg["vehicle_width"]) * 0.5, 0.1)
        self.critical = min(max(float(wcfg["critical_side_distance"]), 0.0), self.nearby)
        self.min_side = min(max(float(wcfg["vehicle_width"]), 0.0) * 0.6, self.nearby)  # closer: same lane
        self.clear_duration = max(float(wcfg["clear_signal_duration"]), 0.0) if wcfg["show_clear_signal"] else 0.0
        self.approach_distance = max(float(wcfg["approaching_distance"]), 0.0) if wcfg["show_approaching_cars"] else 0.0
        self.sides = (NO_CAR, NO_CAR)
        self.approach = (0.0, 0.0)
        self.clear_until = [0.0, 0.0]  # monotonic time clear signal ends, per side
        self.last_version = None
        self.clock = monotonic

    def read_spotter(self) -> SpotterState:
        """Spotter state, cars read again only when vehicles module updated"""
        version = minfo.vehicles.dataSetVersion
        now = self.clock()
        if self.last_version != version:
            self.last_version = version
            cars = tuple(self.nearby_cars())
            sides = side_overlap(cars, self.length, self.nearby, self.critical)
            if self.clear_duration:
                for index, (old, new) in enumerate(zip(self.sides, sides)):
                    if new.lit:
                        self.clear_until[index] = 0.0
                    elif old.lit:  # side just became free
                        self.clear_until[index] = now + self.clear_duration
            self.sides = sides
            self.approach = side_approach(cars, self.length, self.nearby, self.approach_distance, self.min_side)
        left, right = (
            max(round((until - now) / self.clear_duration * CLEAR_STEPS), 1) if until > now else 0
            for until in self.clear_until
        )
        return SpotterState(self.sides[0], self.sides[1], (left, right), self.approach)

    @staticmethod
    def nearby_cars():
        """Relative position of other cars on track (garage left out)"""
        vehicles = minfo.vehicles
        return (
            (car.relativeRotatedPositionX, car.relativeRotatedPositionY)
            for car in islice(vehicles.dataSet, vehicles.totalVehicles)
            if not car.isPlayer and car.inPit != 2
        )


class Realtime(HiddenPreview, SpotterMixin, Overlay):
    """Draw widget"""

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        self.setup_spotter()

        # Config variable
        wcfg = self.wcfg
        self.bar_width = max(int(wcfg["bar_width"]), 1)
        self.bar_height = max(int(wcfg["bar_height"]), 4)
        gap = max(int(wcfg["horizontal_gap"]), 0)
        self.show_background = bool(wcfg["show_bar_background"])
        self.rect_bars = (
            QRectF(0, 0, self.bar_width, self.bar_height),
            QRectF(self.bar_width + gap, 0, self.bar_width, self.bar_height),
        )
        self.color_nearby = QColor(wcfg["bar_color_nearby"])
        self.color_critical = QColor(wcfg["bar_color_critical"])
        self.color_clear = QColor(wcfg["bar_color_clear"])
        self.color_background = QColor(wcfg["bar_background_color"])
        self.color_preview = QColor(self.color_background)  # unlocked: bars always visible
        self.color_preview.setAlpha(max(self.color_background.alpha(), 68))

        # Config canvas
        self.resize(self.bar_width * 2 + gap, self.bar_height)
        self.state = NO_STATE

    def timerEvent(self, event):
        """Update when vehicle on track"""
        state = self.read_spotter()
        if self.state != state:
            self.state = state
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        preview = self.previewing()
        state = self.state
        if not (preview or state.shown):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for rect, overlap, clear, approach in zip(self.rect_bars, state[:2], state.clear, state.approach):
            if self.show_background:
                self.fill_bar(painter, rect, self.color_background)
            elif preview:
                self.fill_bar(painter, rect, self.color_preview)
            if clear:
                painter.setOpacity(clear / CLEAR_STEPS)
                self.fill_bar(painter, rect, self.color_clear)
                painter.setOpacity(1.0)
            if approach:
                painter.setOpacity(approach * 0.7)
                zone = rect.height() * APPROACH_ZONE
                self.fill_bar(painter, QRectF(rect.left(), rect.bottom() - zone, rect.width(), zone), self.color_nearby)
                painter.setOpacity(1.0)
            if overlap.lit:
                lit = QRectF(rect.left(), rect.top() + rect.height() * overlap.top,
                             rect.width(), rect.height() * (overlap.bottom - overlap.top))
                self.fill_bar(painter, lit, self.color_critical if overlap.critical else self.color_nearby)

    def fill_bar(self, painter: QPainter, rect: QRectF, color: Any):
        """Bar part (square, classic)"""
        painter.fillRect(rect, color)
