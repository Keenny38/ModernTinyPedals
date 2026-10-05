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
Tyre temperature Widget, modern design

Surface temperature per tyre (or inner / center / outer), tiles in heatmap color of compound,
compound badges between left and right tyres.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import units
from ...api_control import api
from .base import DASH, ModernOverlay
from .quad import QuadMixin, Section, Tile, heat_color
from .wheels import TyreCompounds


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_inner_center_outer", "show_degree_sign", "leading_zero",
        "enable_heatmap_auto_matching", "heatmap_name", "show_tyre_compound",
    )
    reader = "surface"

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.sign = "°" if wcfg["show_degree_sign"] else ""
        self.leading_zero = min(max(int(wcfg.get("leading_zero", 2)), 1), 3)
        self.ico = wcfg.get("show_inner_center_outer", False)
        self.compounds = TyreCompounds(wcfg.get("enable_heatmap_auto_matching", True), wcfg.get("heatmap_name", "tyre_default"))
        self.show_compound = wcfg.get("show_tyre_compound", True)
        sample = f"888{self.sign}"
        section = Section(self.widget_name, "", sample, 3 if self.ico else 1)
        center = self.unit * 1.2 if self.show_compound else 0.0
        self.set_size(*self.build_quads([section], center_width=center, show_labels=False))

    def read_temperatures(self) -> tuple:
        """Temperatures: 12 (inner, center, outer per wheel) or 4"""
        if self.ico:
            return api.read.tyre.surface_temperature_ico()
        return api.read.tyre.surface_temperature_avg()

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        tiles, badges = self.state
        self.draw_quads(painter, (tiles,))
        if self.show_compound:
            self.draw_center_badges(painter, self.quad_slots[0], badges)

    def text(self, value: float) -> str:
        """Temperature text"""
        if value < -100:
            return DASH
        return f"{self.unit_temp(value):0{self.leading_zero}.0f}{self.sign}"

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.compounds.update()
        heat = self.compounds.heat
        temps = self.read_temperatures()
        parts = 3 if self.ico else 1
        tiles = []
        for wheel in range(4):
            values = [round(value) for value in temps[wheel * parts:wheel * parts + parts]]
            tiles.append(Tile(
                tuple(self.text(value) for value in values),
                tuple(heat_color(heat[wheel], value) if value > -100 else None for value in values),
            ))
        self.refresh((tuple(tiles), self.compounds.badges))
