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
Tyre pressure Widget, modern design

Pressure per tyre (blue while carcass is cold, orange once hot), deviation from highest
average pressure under it, compound badges between left and right tyres.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from .base import ModernOverlay
from .quad import QuadMixin, Section, Tile
from .wheels import TyreCompounds


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "hot_pressure_temperature_threshold", "average_sampling_duration",
        "show_pressure_deviation", "show_tyre_compound",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        pres_unit = self.cfg.units["tyre_pressure_unit"]
        self.unit_pres = units.set_unit_pressure(pres_unit)
        self.text_width_chars = 3 + (pres_unit != "kPa")
        self.hot_temp = max(wcfg["hot_pressure_temperature_threshold"], 0)
        self.compounds = TyreCompounds(False)
        self.show_compound = wcfg["show_tyre_compound"]
        self.show_deviation = wcfg["show_pressure_deviation"]
        self.averages = [0.0] * 4
        interval = max(wcfg["update_interval"], 0.01)
        samples = int(min(max(wcfg["average_sampling_duration"], 1), 600) / (interval * 0.001))
        self.ema_pressure = calc.ema_filter(samples)
        section = Section(widget_name, "", "888.8", sub=self.show_deviation)
        center = self.unit * 1.2 if self.show_compound else 0.0
        self.set_size(*self.build_quads([section], center_width=center, show_labels=False))

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        tiles, badges = self.state
        self.draw_quads(painter, (tiles,))
        if self.show_compound:
            self.draw_center_badges(painter, self.quad_slots[0], badges)

    def number(self, value: float) -> str:
        """Pressure text, same width in any unit"""
        return f"{self.unit_pres(value):.2f}"[:self.text_width_chars].strip(".")

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        self.compounds.update()
        pressures = api.read.tyre.pressure()
        carcass = api.read.tyre.carcass_temperature()
        peak = max(self.averages)
        tiles = []
        for index in range(4):
            hot = carcass[index] >= self.hot_temp
            sub = ""
            if self.show_deviation:
                sub = f"±{self.number(peak - self.averages[index])}"
                self.averages[index] = self.ema_pressure(self.averages[index], pressures[index])
            tiles.append(Tile((self.number(pressures[index]),), colors=(theme.orange if hot else theme.lap_behind,),
                              sub=sub))
        self.refresh((tuple(tiles), self.compounds.badges))
