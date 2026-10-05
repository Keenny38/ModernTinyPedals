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
critical color when it is close sideways. Cars come from vehicles module, same relative
positions as radar.
"""

from __future__ import annotations

from itertools import islice
from typing import Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from ..module_info import minfo
from ._base import Overlay
from ._race_aids import HiddenPreview, finite

PRECISION = 2  # overlap fraction decimals (bar redrawn only when lit part moves visibly)


class Side(NamedTuple):
    """Overlap of cars on one side of player car: lit part of bar (0 = front, 1 = rear)"""

    top: float = 0.0
    bottom: float = 0.0
    critical: bool = False

    @property
    def lit(self) -> bool:
        return self.bottom > self.top


NO_CAR = Side()


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
    left_critical = right_critical = False
    for pos_x, pos_y in cars:
        if not (finite(pos_x) and finite(pos_y)) or abs(pos_x) > nearby or abs(pos_y) >= length:
            continue
        top = (max(-half, pos_y - half) + half) / length  # overlapped part of player car
        bottom = (min(half, pos_y + half) + half) / length
        if pos_x < 0:
            left_top = min(left_top, top)
            left_bottom = max(left_bottom, bottom)
            left_critical |= abs(pos_x) <= critical
        else:
            right_top = min(right_top, top)
            right_bottom = max(right_bottom, bottom)
            right_critical |= abs(pos_x) <= critical
    return side(left_top, left_bottom, left_critical), side(right_top, right_bottom, right_critical)


def side(top: float, bottom: float, critical: bool) -> Side:
    """Side overlap, rounded (no car if nothing overlapped)"""
    if bottom <= top:
        return NO_CAR
    return Side(round(top, PRECISION), round(bottom, PRECISION), critical)


class Realtime(HiddenPreview, Overlay):
    """Draw widget"""

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)

        # Config variable
        wcfg = self.wcfg
        self.bar_width = max(int(wcfg["bar_width"]), 1)
        self.bar_height = max(int(wcfg["bar_height"]), 4)
        gap = max(int(wcfg["horizontal_gap"]), 0)
        self.length = max(float(wcfg["vehicle_length"]), 0.5)
        self.nearby = max(float(wcfg["nearby_side_distance"]), float(wcfg["vehicle_width"]) * 0.5, 0.1)
        self.critical = min(max(float(wcfg["critical_side_distance"]), 0.0), self.nearby)
        self.show_background = bool(wcfg["show_bar_background"])
        self.rect_bars = (
            QRectF(0, 0, self.bar_width, self.bar_height),
            QRectF(self.bar_width + gap, 0, self.bar_width, self.bar_height),
        )
        self.color_nearby = QColor(wcfg["bar_color_nearby"])
        self.color_critical = QColor(wcfg["bar_color_critical"])
        self.color_background = QColor(wcfg["bar_background_color"])
        self.color_preview = QColor(self.color_background)  # unlocked: bars always visible
        self.color_preview.setAlpha(max(self.color_background.alpha(), 68))

        # Config canvas
        self.resize(self.bar_width * 2 + gap, self.bar_height)
        self.state = (NO_CAR, NO_CAR)
        self.last_version = None

    def timerEvent(self, event):
        """Update when vehicle on track"""
        version = minfo.vehicles.dataSetVersion
        if self.last_version == version:
            return
        self.last_version = version
        state = side_overlap(self.nearby_cars(), self.length, self.nearby, self.critical)
        if self.state != state:
            self.state = state
            self.update()

    @staticmethod
    def nearby_cars():
        """Relative position of other cars on track (garage left out)"""
        vehicles = minfo.vehicles
        return (
            (car.relativeRotatedPositionX, car.relativeRotatedPositionY)
            for car in islice(vehicles.dataSet, vehicles.totalVehicles)
            if not car.isPlayer and car.inPit != 2
        )

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        preview = self.previewing()
        if not (preview or self.state[0].lit or self.state[1].lit):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for rect, overlap in zip(self.rect_bars, self.state):
            if self.show_background:
                self.fill_bar(painter, rect, self.color_background)
            elif preview:
                self.fill_bar(painter, rect, self.color_preview)
            if overlap.lit:
                lit = QRectF(rect.left(), rect.top() + rect.height() * overlap.top,
                             rect.width(), rect.height() * (overlap.bottom - overlap.top))
                self.fill_bar(painter, lit, self.color_critical if overlap.critical else self.color_nearby)

    def fill_bar(self, painter: QPainter, rect: QRectF, color: Any):
        """Bar part (square, classic)"""
        painter.fillRect(rect, color)
