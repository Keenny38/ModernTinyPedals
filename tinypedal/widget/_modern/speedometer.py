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
Speedometer Widget, modern design

Current speed, minimum speed off throttle (corner), maximum speed on throttle (straight),
fastest speed of session.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import units
from ...api_control import api
from .base import ModernOverlay, display_order_options
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "decimal_places", "off_throttle_threshold", "on_throttle_threshold",
        "speed_minimum_reset_cooldown", "speed_maximum_reset_cooldown", "show_speed", "show_speed_minimum",
        "show_speed_maximum", "show_speed_fastest",
        *display_order_options("speedometer"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.unit_speed = units.set_unit_speed(self.cfg.units["speed_unit"])
        self.decimals = max(int(wcfg["decimal_places"]), 0)
        sample = "888." + "8" * self.decimals if self.decimals else "888"
        items = (
            ("speed", units.set_symbol_speed(self.cfg.units["speed_unit"]), "strong", None),
            ("speed_minimum", "Min", "value", theme.warning),
            ("speed_maximum", "Max", "value", theme.positive),
            ("speed_fastest", "Top", "value", theme.best),
        )
        stats = [Stat(key, label, sample, role, accent) for key, label, role, accent in items if wcfg[f"show_{key}"]]
        stats = self.display_ordered(stats)
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)
        self.speed_min = self.speed_max = 0.0
        self.speed_fast = -1.0
        self.min_timer = self.max_timer = 0.0

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        speed = api.read.vehicle.speed()
        elapsed = api.read.timing.elapsed()
        throttle = api.read.inputs.throttle_raw()
        if throttle < wcfg["off_throttle_threshold"]:  # lowest speed off throttle
            if speed < self.speed_min:
                self.speed_min = speed
                self.min_timer = elapsed
            if self.min_timer > elapsed:
                self.min_timer = elapsed
            if elapsed - self.min_timer > wcfg["speed_minimum_reset_cooldown"]:
                self.speed_min = speed
        if throttle > wcfg["on_throttle_threshold"]:  # highest speed on throttle
            if speed > self.speed_max:
                self.speed_max = speed
                self.max_timer = elapsed
            if self.max_timer > elapsed:
                self.max_timer = elapsed
            if elapsed - self.max_timer > wcfg["speed_maximum_reset_cooldown"]:
                self.speed_max = speed
        if api.read.engine.gear() < 0:  # reset on reverse gear
            self.speed_fast = -1.0
        self.speed_fast = max(self.speed_fast, speed)
        speeds = {"speed": speed, "speed_minimum": self.speed_min, "speed_maximum": self.speed_max,
                  "speed_fastest": max(self.speed_fast, 0.0)}
        self.refresh(tuple(Value(f"{self.unit_speed(speeds[key]):.{self.decimals}f}") for key in self.keys))
