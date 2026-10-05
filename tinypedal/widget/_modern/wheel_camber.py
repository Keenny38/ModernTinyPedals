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
Wheel camber Widget, modern design

Camber angle per wheel (positive camber highlighted), camber difference per axle in middle.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...module_info import minfo
from .base import ModernOverlay
from .quad import QuadMixin, Section, Tile


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "decimal_places_camber", "camber_smoothing_samples", "positive_camber_threshold",
        "show_camber_difference", "decimal_places_camber_difference", "camber_difference_smoothing_samples",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.dec = max(int(wcfg["decimal_places_camber"]), 0)
        self.dec_diff = max(int(wcfg["decimal_places_camber_difference"]), 0)
        self.ema = calc.ema_filter(wcfg["camber_smoothing_samples"])
        self.ema_diff = calc.ema_filter(wcfg["camber_difference_smoothing_samples"])
        self.cambers = [0.0] * 4
        self.diffs = [0.0, 0.0]
        self.show_diff = wcfg["show_camber_difference"]
        section = Section(widget_name, "Camber", "+8." + "8" * self.dec)
        center = self.text_width("small", "+8." + "8" * self.dec_diff) + self.unit * 0.3 if self.show_diff else 0.0
        self.set_size(*self.build_quads([section], center_width=center))

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        tiles, diffs = self.state
        self.draw_quads(painter, (tiles,))
        if self.show_diff:
            self.draw_center_texts(painter, self.quad_slots[0], diffs)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        wheels = minfo.wheels
        tiles = []
        for index, camber in enumerate(wheels.camberAngle):
            self.cambers[index] = self.ema(self.cambers[index], camber)
            positive = self.cambers[index] >= self.wcfg["positive_camber_threshold"]
            tiles.append(Tile((f"{self.cambers[index]:+.{self.dec}f}",), colors=(theme.warning if positive else None,)))
        diffs: tuple[str, ...] = ("", "")
        if self.show_diff:
            self.diffs[0] = self.ema_diff(self.diffs[0], wheels.frontCamberAngleDifference)
            self.diffs[1] = self.ema_diff(self.diffs[1], wheels.rearCamberAngleDifference)
            diffs = tuple(f"{value:+.{self.dec_diff}f}" for value in self.diffs)
        self.refresh((tuple(tiles), diffs))
