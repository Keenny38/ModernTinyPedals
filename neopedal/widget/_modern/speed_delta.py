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
Speed delta Widget, modern design

Speed difference to all time best, session best, stint best and last lap at same lap distance, green when
faster, red when slower, in speed unit. A dash while there is no reference lap yet or no comparison on this
lap (out lap from pit lane or garage, in pit lane before start line).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ..speed_delta import REFERENCES, SpeedDeltas, display_range
from .base import DASH, ModernOverlay
from .stats import Stat, StatsMixin, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import SpeedDeltaConfig

STEADY = 0.05  # speed difference (speed unit) shown in neutral color below this


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: SpeedDeltaConfig

    options = (
        "font_size", "layout", "decimal_places", "speed_delta_display_range", "speed_delta_smoothing_samples",
        "show_speed_unit",
        "show_all_time_best", "show_session_best", "show_stint_best", "show_last_lap",
        "display_order_all_time_best", "display_order_session_best", "display_order_stint_best",
        "display_order_last_lap",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.decimals = max(int(wcfg["decimal_places"]), 0)
        self.display_range = display_range(wcfg["speed_delta_display_range"], self.decimals)
        self.speeds = SpeedDeltas(units.set_unit_speed(self.cfg.units["speed_unit"]),
                                  wcfg["speed_delta_smoothing_samples"])
        self.symbol = units.set_symbol_speed(self.cfg.units["speed_unit"]) if wcfg["show_speed_unit"] else ""
        accents = {"all_time_best": theme.positive, "session_best": theme.best, "stint_best": theme.orange,
                   "last_lap": theme.text_dim}
        sample = "+88" + ("." + "8" * self.decimals if self.decimals else "")
        stats = [Stat(key, label, sample, "strong", accents[key], sub_sample=self.symbol)
                 for key, _, _, label in REFERENCES if wcfg[f"show_{key}"]]
        stats = self.display_ordered(stats)
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0, show_sub=bool(self.symbol))
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        speeds = self.speeds.read()
        values = []
        for key in self.keys:
            value = speeds[key]
            if value is None:  # no reference lap, or no comparison on this lap
                values.append(Value(DASH, theme.text_dim, sub=self.symbol, sub_color=theme.text_muted))
                continue
            value = round(calc.sym_max(value, self.display_range), self.decimals)
            if abs(value) < STEADY:
                color = theme.text
            else:
                color = theme.positive if value > 0 else theme.negative
            values.append(Value(f"{value:+.{self.decimals}f}", color, sub=self.symbol, sub_color=theme.text_muted))
        self.refresh(tuple(values))
