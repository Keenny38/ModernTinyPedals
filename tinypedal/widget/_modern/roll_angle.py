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
Roll angle Widget, modern design

Front & rear roll angle, difference rear to front, roll angle ratio (front share).
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from .base import ModernOverlay, display_order_options
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_degree_and_percentage_sign", "wheel_track_front", "wheel_track_rear",
        "roll_angle_smoothing_samples", "roll_angle_ratio_smoothing_samples", "decimal_places",
        "show_roll_angle_difference", "show_roll_angle_ratio",
        *display_order_options("roll_angle"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.decimals = max(int(wcfg["decimal_places"]), 0)
        self.sign = "°" if wcfg["show_degree_and_percentage_sign"] else ""
        self.percent = "%" if wcfg["show_degree_and_percentage_sign"] else ""
        self.ema_roll = calc.ema_filter(wcfg["roll_angle_smoothing_samples"])
        self.ema_ratio = calc.ema_filter(wcfg["roll_angle_ratio_smoothing_samples"])
        self.front = self.rear = 0.0
        self.ratio = 0.5
        sample = "+8." + "8" * self.decimals + self.sign
        stats = [Stat("front", "Front", sample), Stat("rear", "Rear", sample)]
        if wcfg["show_roll_angle_difference"]:
            stats.append(Stat("difference", "Diff", sample))
        if wcfg["show_roll_angle_ratio"]:
            stats.append(Stat("ratio", "Ratio", "88.8" + self.percent))
        stats = self.display_ordered(stats, names={
            "front": "roll_angle_front", "rear": "roll_angle_rear", "difference": "roll_angle_difference",
            "ratio": "roll_angle_ratio",
        })
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        height_fl, height_fr, height_rl, height_rr = api.read.wheel.ride_height()
        front = calc.slope_angle(height_fr - height_fl, wcfg["wheel_track_front"])
        rear = calc.slope_angle(height_rr - height_rl, wcfg["wheel_track_rear"])
        self.front = self.ema_roll(self.front, front)
        self.rear = self.ema_roll(self.rear, rear)
        if front < 0 > rear or front > 0 < rear:
            ratio = calc.part_to_whole_ratio(front, front + rear, 0.5)
        else:
            ratio = 0.5
        self.ratio = self.ema_ratio(self.ratio, ratio)
        angles = {"front": self.front, "rear": self.rear, "difference": self.rear - self.front}
        values = []
        for key in self.keys:
            if key == "ratio":
                values.append(Value(f"{self.ratio * 100:.1f}{self.percent}", self.theme.text_dim))
            else:
                values.append(Value(f"{angles[key]:+.{self.decimals}f}{self.sign}"))
        self.refresh(tuple(values))
