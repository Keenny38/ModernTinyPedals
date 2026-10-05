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
Brake bias Widget, modern design

Front brake bias (or front:rear), change since leaving pits, brake migration. Bias shown on a
front / rear split bar.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...api_control import api
from ..brake_bias import brake_migration
from .base import ModernOverlay, display_order_options
from .draw import fraction
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_brake_bias", "decimal_places_brake_bias", "show_front_and_rear",
        "show_percentage_sign", "show_baseline_bias_delta", "decimal_places_baseline_bias_delta",
        "show_brake_migration", "decimal_places_brake_migration", "electric_braking_allocation",
        *display_order_options("brake_bias"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.dec_bias = max(int(wcfg["decimal_places_brake_bias"]), 0)
        self.dec_delta = max(int(wcfg["decimal_places_baseline_bias_delta"]), 0)
        self.dec_migration = max(int(wcfg["decimal_places_brake_migration"]), 0)
        self.sign = "%" if wcfg["show_percentage_sign"] else ""
        stats = []
        if wcfg["show_brake_bias"]:
            sample = "88.88:88.88" if wcfg["show_front_and_rear"] else "88.88%"
            stats.append(Stat("bias", "Brake bias", sample, "strong", theme.orange))
        if wcfg["show_baseline_bias_delta"]:
            stats.append(Stat("delta", "Change", "+8.88"))
        if wcfg["show_brake_migration"]:
            stats.append(Stat("migration", "Migration", "88.8F"))
        stats = self.display_ordered(stats, names={
            "bias": "brake_bias", "delta": "baseline_bias_delta", "migration": "brake_migration",
        })
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)
        self.baseline = 0.0
        self.migration = brake_migration(wcfg["electric_braking_allocation"])

    def post_update(self):
        self.migration.send(-1)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        bias = api.read.brake.bias_front()
        values = []
        for key in self.keys:
            if key == "bias":
                front = bias * 100
                if self.wcfg["show_front_and_rear"]:
                    text = f"{front:.{self.dec_bias}f}:{100 - front:.{self.dec_bias}f}"
                else:
                    text = f"{front:.{self.dec_bias}f}{self.sign}"
                values.append(Value(text, bar=fraction(bias), bar_color=theme.orange))
            elif key == "delta":
                if not self.baseline or ((api.read.vehicle.in_pits() or api.read.session.pre_race())
                                         and api.read.vehicle.speed() < 0.1):
                    self.baseline = bias
                delta = (bias - self.baseline) * 100
                values.append(Value(f"{delta:+.{self.dec_delta}f}", theme.text_dim if not round(delta, 3) else theme.warning))
            elif key == "migration":
                migration = api.read.brake.migration()
                if migration < 0:
                    migration = self.migration.send(bias) * 100
                values.append(Value(f"{migration:.{self.dec_migration}f}F", theme.text_dim))
        self.refresh(tuple(values))
