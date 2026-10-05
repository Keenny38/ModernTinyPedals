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
Wheel toe Widget, modern design

Toe angle per wheel, total toe per axle in middle (toe out in orange, toe in in blue).
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPainter

from ... import calculation as calc
from ...module_info import minfo
from .base import ModernOverlay
from .quad import QuadMixin, Section, Tile


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "enable_symmetric_toe_angle", "decimal_places_toe_angle", "toe_angle_smoothing_samples",
        "show_total_toe_angle", "decimal_places_total_toe_angle", "total_toe_angle_smoothing_samples",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.dec = max(int(wcfg["decimal_places_toe_angle"]), 0)
        self.dec_total = max(int(wcfg["decimal_places_total_toe_angle"]), 0)
        self.ema = calc.ema_filter(wcfg["toe_angle_smoothing_samples"])
        self.ema_total = calc.ema_filter(wcfg["total_toe_angle_smoothing_samples"])
        self.toes = [0.0] * 4
        self.totals = [0.0, 0.0]
        self.show_total = wcfg["show_total_toe_angle"]
        section = Section(widget_name, "Toe", "+8." + "8" * self.dec)
        center = self.text_width("small", "8." + "8" * self.dec_total) + self.unit * 0.3 if self.show_total else 0.0
        self.set_size(*self.build_quads([section], center_width=center))

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        tiles, totals, colors = self.state
        self.draw_quads(painter, (tiles,))
        if self.show_total:
            self.draw_center_texts(painter, self.quad_slots[0], totals, colors)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        wheels = minfo.wheels
        symmetric = self.wcfg["enable_symmetric_toe_angle"]
        tiles = []
        for index, toe in enumerate(wheels.toeAngle):
            if symmetric and index % 2:
                toe = -toe
            self.toes[index] = self.ema(self.toes[index], toe)
            tiles.append(Tile((f"{self.toes[index]:+.{self.dec}f}",)))
        totals: tuple[str, ...] = ("", "")
        colors: tuple[QColor | None, ...] = (None, None)
        if self.show_total:
            self.totals[0] = self.ema_total(self.totals[0], wheels.frontToeAngleDifference)
            self.totals[1] = self.ema_total(self.totals[1], wheels.rearToeAngleDifference)
            totals = tuple(f"{abs(value):.{self.dec_total}f}" for value in self.totals)
            colors = tuple(theme.orange if value > 0 else theme.lap_behind for value in self.totals)
        self.refresh((tuple(tiles), totals, colors))
