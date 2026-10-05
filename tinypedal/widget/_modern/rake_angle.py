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
Rake Widget, modern design

Rake angle (negative rake in red) and ride height difference front to rear.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_degree_sign", "show_ride_height_difference", "wheelbase", "rake_angle_smoothing_samples",
        "decimal_places",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.decimals = max(int(wcfg["decimal_places"]), 0)
        self.sign = "°" if wcfg["show_degree_sign"] else ""
        self.ema = calc.ema_filter(wcfg["rake_angle_smoothing_samples"])
        self.rake = 0.0
        sample = "+8." + "8" * self.decimals + self.sign
        stat = Stat("rake", "Rake", sample, "strong", sub_sample="88mm")
        width, height = self.build_stats([stat], show_sub=wcfg["show_ride_height_difference"])
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        self.rake = self.ema(self.rake, calc.rake(*api.read.wheel.ride_height()))
        angle = calc.slope_angle(self.rake, self.wcfg["wheelbase"])
        sub = f"{abs(self.rake):.0f}mm" if self.wcfg["show_ride_height_difference"] else ""
        self.refresh((Value(f"{angle:+.{self.decimals}f}{self.sign}", theme.negative if self.rake < 0 else None, sub=sub),))
