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
Suspension position Widget, modern design

Suspension position per wheel with gauge (compression orange, extension blue), highlighted
when beyond maximum position range, maximum position range line along outer edge, third spring
position mark (front & rear).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...api_control import api
from ...module_info import minfo
from .draw import rounded
from .gauge_quad import GaugeQuad

if TYPE_CHECKING:
    from ...template.widget_config_types import SuspensionPositionConfig


class Realtime(GaugeQuad):
    """Draw widget"""

    wcfg: SuspensionPositionConfig

    options = (
        *GaugeQuad.common_options, "position_maximum_range", "show_maximum_position_range",
        "show_third_spring_position_mark",
    )
    label = "Suspension"

    def setup(self):
        self.max_range = max(int(self.wcfg["position_maximum_range"]), 10)
        self.show_maximum = self.wcfg["show_maximum_position_range"]

    def paint(self, painter: QPainter):
        tiles, maximums = self.state
        self.draw_quads(painter, (tiles,))
        if self.show_maximum:
            self.draw_maximum_ranges(painter, maximums)

    def draw_maximum_ranges(self, painter: QPainter, maximums: tuple[float, ...]):
        """Maximum position range (0-1): line along tile outer edge (top front, bottom rear), growing outward
        from car center as gauge"""
        if not self.quad_slots:
            return
        height = max(self.unit * 0.12, 2.0)
        inset = self.unit * 0.08
        for wheel, (rect, level) in enumerate(zip(self.quad_slots[0].tiles, maximums)):
            width = rect.width() * min(level, 1.0)
            if width < 1:  # none (not recorded yet, or negative: too much packers)
                continue
            left = rect.left() if wheel % 2 else rect.right() - width
            top = rect.top() + inset if wheel < 2 else rect.bottom() - inset - height
            rounded(painter, QRectF(left, top, width, height), height / 2, self.theme.negative)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        tiles = self.read()
        if self.show_maximum:
            maximums = tuple(max(value, 0.0) / self.max_range for value in minfo.wheels.maxSuspensionPosition)
        else:
            maximums = (0.0,) * 4
        widths = [rect.width() for rect in self.quad_slots[0].tiles] if self.quad_slots else []
        self.refresh_keyed((tiles, maximums), (
            self.pixel_key(tiles, widths, "level", "mark"),
            tuple(self.pixel_steps(level, width) for level, width in zip(maximums, widths)),
        ))

    def read(self) -> tuple:
        theme = self.theme
        positions = minfo.wheels.currentSuspensionPosition
        maximums = minfo.wheels.maxSuspensionPosition if self.wcfg["show_maximum_position_range"] else (0, 0, 0, 0)
        if self.wcfg["show_third_spring_position_mark"]:
            thirds = tuple(abs(value) / self.max_range for value in api.read.wheel.third_spring_deflection())
        else:
            thirds = (-1.0,) * 4
        tiles = []
        for position, maximum, third in zip(positions, maximums, thirds):
            exceeded = 0 < maximum <= position
            color = theme.warning if position >= 0 else theme.blue
            tiles.append(self.gauge(abs(position), position, abs(position) / self.max_range, color, exceeded, third))
        return tuple(tiles)
