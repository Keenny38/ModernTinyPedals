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
Weight distribution Widget, modern design

Front, left & cross weight share, each with a split bar.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...module_info import minfo
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value

ITEMS = (
    ("front_to_rear_distribution", "Front", "frontWeightRatio"),
    ("left_to_right_distribution", "Left", "leftWeightRatio"),
    ("cross_weight", "Cross", "crossWeightRatio"),
)


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = ("font_size", "layout", "show_percentage_sign", "decimal_places", "smoothing_samples",
               *(f"show_{key}" for key, _, _ in ITEMS))

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.decimals = max(int(wcfg["decimal_places"]), 0)
        self.sign = "%" if wcfg["show_percentage_sign"] else ""
        self.ema = calc.ema_filter(wcfg["smoothing_samples"])
        self.items = {key: attr for key, _, attr in ITEMS}
        self.ratios = {key: 0.5 for key, _, _ in ITEMS}
        stats = [Stat(key, label, "88." + "8" * self.decimals + self.sign) for key, label, _ in ITEMS if wcfg[f"show_{key}"]]
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        values = []
        for key in self.keys:
            self.ratios[key] = self.ema(self.ratios[key], getattr(minfo.wheels, self.items[key]))
            ratio = self.ratios[key]
            values.append(Value(f"{ratio * 100:.{self.decimals}f}{self.sign}", bar=min(max(ratio, 0.0), 1.0),
                                bar_color=self.theme.accent))
        self.refresh(tuple(values))
