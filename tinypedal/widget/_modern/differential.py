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
Differential Widget, modern design

Lowest differential locking of last power (on throttle) & coast phases, front & rear.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...api_control import api
from ...module_info import minfo
from ..differential import DiffLockingTimer
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value

ITEMS = (
    ("power_locking_front", "Power F", True, True),
    ("coast_locking_front", "Coast F", False, True),
    ("power_locking_rear", "Power R", True, False),
    ("coast_locking_rear", "Coast R", False, False),
)


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_inverted_locking", "decimal_places", "off_throttle_threshold",
        "on_throttle_threshold", "power_locking_reset_cooldown", "coast_locking_reset_cooldown",
        *(f"show_{key}" for key, _, _, _ in ITEMS),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.decimals = max(int(wcfg["decimal_places"]), 0)
        sample = "100." + "8" * self.decimals + "%" if self.decimals else "100%"
        stats = [
            Stat(key, label, sample, accent=theme.positive if power else theme.blue)
            for key, label, power, _ in ITEMS if wcfg[f"show_{key}"]
        ]
        self.keys = tuple(stat.key for stat in stats)
        self.items = {key: (power, front) for key, _, power, front in ITEMS}
        self.timers = {
            key: DiffLockingTimer(wcfg["power_locking_reset_cooldown" if power else "coast_locking_reset_cooldown"])
            for key, _, power, _ in ITEMS
        }
        self.locking = {key: 0.0 for key, _, _, _ in ITEMS}
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        elapsed = api.read.timing.elapsed()
        throttle = api.read.inputs.throttle_raw()
        on_throttle = throttle > wcfg["on_throttle_threshold"]
        off_throttle = throttle < wcfg["off_throttle_threshold"]
        values = []
        for key in self.keys:
            power, front = self.items[key]
            if (power and on_throttle) or (not power and off_throttle):
                locking = minfo.wheels.lockingPercentFront if front else minfo.wheels.lockingPercentRear
                self.locking[key] = self.timers[key].update(locking, elapsed)
            value = self.locking[key]
            if wcfg["show_inverted_locking"]:
                value = 1 - value
            values.append(Value(f"{value:.{self.decimals}%}", bar=min(max(value, 0.0), 1.0)))
        self.refresh(tuple(values))
