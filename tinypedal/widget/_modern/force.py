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
Force Widget, modern design

Longitudinal & lateral g force (direction arrows), downforce ratio, front & rear downforce,
estimated static & dynamic weight, acceleration reduction.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import units
from ...module_info import minfo
from ...validator import infnan_to_zero as rmnan
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_longitudinal_g_force", "show_lateral_g_force", "show_downforce_ratio",
        "show_front_downforce", "show_rear_downforce", "show_estimated_static_weight",
        "show_minimum_static_weight_without_fuel", "show_estimated_dynamic_weight", "show_acceleration_reduction",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_weight = units.set_unit_weight(self.cfg.units["weight_unit"])
        self.symbol_weight = units.set_symbol_weight(self.cfg.units["weight_unit"])
        items = (
            ("longitudinal_g_force", "Long. G", "▲ 8.88"),
            ("lateral_g_force", "Lat. G", "8.88 ▶"),
            ("downforce_ratio", "DF ratio", "88.88%"),
            ("front_downforce", "DF front", "88888"),
            ("rear_downforce", "DF rear", "88888"),
            ("estimated_static_weight", "Static", f"8888{self.symbol_weight}"),
            ("estimated_dynamic_weight", "Dynamic", f"8888{self.symbol_weight}"),
            ("acceleration_reduction", "Accel. loss", "8.888%"),
        )
        stats = [Stat(key, label, sample) for key, label, sample in items if wcfg[f"show_{key}"]]
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        force = minfo.force
        wheels = minfo.wheels
        values = []
        for key in self.keys:
            if key == "longitudinal_g_force":
                g = round(force.lgtGForceRaw, 2)
                sign = "▼" if g > 0.1 else ("▲" if g < -0.1 else "●")
                values.append(Value(f"{sign} {abs(g):.2f}", theme.negative if g > 0.1 else (theme.positive if g < -0.1 else None)))
            elif key == "lateral_g_force":
                g = round(force.latGForceRaw, 2)
                sign = "◀" if g > 0.1 else ("▶" if g < -0.1 else "●")
                values.append(Value(f"{abs(g):.2f} {sign}"))
            elif key == "downforce_ratio":
                values.append(Value(f"{rmnan(force.downForceRatio) * 100:.2f}"[:5] + "%"))
            elif key == "front_downforce":
                values.append(Value(f"{abs(round(rmnan(force.downForceFront))):.0f}", theme.text_dim))
            elif key == "rear_downforce":
                values.append(Value(f"{abs(round(rmnan(force.downForceRear))):.0f}", theme.text_dim))
            elif key == "estimated_static_weight":
                weight = wheels.minimumStaticWeight if self.wcfg["show_minimum_static_weight_without_fuel"] else wheels.totalStaticWeight
                values.append(Value(f"{self.unit_weight(round(rmnan(weight))):.0f}{self.symbol_weight}"))
            elif key == "estimated_dynamic_weight":
                values.append(Value(f"{self.unit_weight(round(rmnan(wheels.totalDynamicWeight))):.0f}{self.symbol_weight}"))
            elif key == "acceleration_reduction":
                total = wheels.totalStaticWeight
                loss = (1 - wheels.minimumStaticWeight / total) * 100 if total > 0 else 0.0
                values.append(Value(f"{loss:.3f}"[:5] + "%", theme.text_dim))
        self.refresh(tuple(values))
