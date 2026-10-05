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
Tyre carcass Widget, modern design

Carcass temperature per tyre in heatmap color of compound, rate of change (heating in orange,
cooling in blue) under it, compound badges between left and right tyres.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from .base import DASH, STEADY, ModernOverlay
from .quad import QuadMixin, Section, Tile, heat_color
from .wheels import TyreCompounds


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_degree_sign", "leading_zero", "enable_heatmap_auto_matching", "heatmap_name",
        "enable_heatmap_from_optimal_temperature", "show_rate_of_change", "rate_of_change_interval",
        "rate_of_change_smoothing_samples", "show_tyre_compound",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.temp_scale = 1.8 if self.cfg.units["temperature_unit"] == "Fahrenheit" else 1.0  # temperature difference
        self.sign = "°" if wcfg["show_degree_sign"] else ""
        self.leading_zero = min(max(int(wcfg["leading_zero"]), 1), 3)
        self.compounds = TyreCompounds(
            wcfg["enable_heatmap_auto_matching"], wcfg["heatmap_name"], wcfg["enable_heatmap_from_optimal_temperature"],
        )
        self.add_font("tiny", 0.5, "bold", caps=True)  # left & right compound badges
        self.show_compound = wcfg["show_tyre_compound"]
        self.show_rate = wcfg["show_rate_of_change"]
        self.rate_interval = min(max(wcfg["rate_of_change_interval"], 1), 60)
        self.ema_rate = calc.ema_filter(wcfg["rate_of_change_smoothing_samples"])
        self.rates = [0.0] * 4
        self.last_temps: list[float] | None = None
        self.last_elapsed = 0.0
        section = Section(widget_name, "", f"888{self.sign}", sub=self.show_rate)
        center = self.unit * 1.2 if self.show_compound else 0.0
        self.set_size(*self.build_quads([section], center_width=center, show_labels=False))

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        tiles, badges = self.state
        self.draw_quads(painter, (tiles,))
        if self.show_compound:
            self.draw_center_badges(painter, self.quad_slots[0], badges)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.compounds.update()
        heat = self.compounds.heat
        temps = api.read.tyre.carcass_temperature()
        if self.show_rate:
            elapsed = api.read.timing.elapsed()
            if self.last_elapsed > elapsed:
                self.last_elapsed = elapsed
            elif elapsed - self.last_elapsed >= 0.1:
                interval = self.rate_interval / (elapsed - self.last_elapsed)
                self.last_elapsed = elapsed
                last_temps = self.last_temps
                if last_temps is not None:  # first reading: no rate yet (from 0 would be a fake spike)
                    for index in range(4):
                        self.rates[index] = self.ema_rate(self.rates[index], (temps[index] - last_temps[index]) * interval)
                self.last_temps = list(temps)
        theme = self.theme
        tiles = []
        for index in range(4):
            temp = round(temps[index])
            text = DASH if temp < -100 else f"{self.unit_temp(temp):0{self.leading_zero}.0f}{self.sign}"
            sub = ""
            sub_color = None
            if self.show_rate:  # heating (orange) or cooling (blue) per rate interval
                rate = self.rates[index]
                change = abs(rate) * self.temp_scale
                sub = f"{change:.0f}" if change > 9.94 else f"{change:.1f}"
                if sub != STEADY:
                    sub = f"{'▲' if rate > 0 else '▼'}{sub}"
                    sub_color = theme.orange if rate > 0 else theme.lap_behind
            tiles.append(Tile((text,), (heat_color(heat[index], temp) if temp > -100 else None,),
                              sub=sub, sub_color=sub_color))
        self.refresh((tuple(tiles), self.compounds.badges))
