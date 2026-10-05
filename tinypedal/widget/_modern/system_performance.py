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
System performance Widget, modern design

CPU & memory usage of system and of this app.
"""

from __future__ import annotations

import os

import psutil
from PySide6.QtGui import QPainter

from ... import calculation as calc
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = ("font_size", "layout", "average_samples", "show_system_performance", "show_tinypedal_performance")

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.ema = calc.ema_filter(wcfg["average_samples"])
        self.app_info = psutil.Process(os.getpid())
        self.cpu_count = os.cpu_count() or 1
        stats = []
        if wcfg["show_system_performance"]:
            stats.append(Stat("system", "System", "88.88%", sub_sample="88.8GB"))
        if wcfg["show_tinypedal_performance"]:
            stats.append(Stat("app", "App", "88.88%", sub_sample="888.8MB"))
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0, show_sub=True)
        self.set_size(width, height)
        self.cpu = {"system": 0.0, "app": 0.0}

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        values = []
        for key in self.keys:
            if key == "system":
                self.cpu[key] = self.ema(self.cpu[key], psutil.cpu_percent())
                memory = f"{psutil.virtual_memory().used / 1024 ** 3:.1f}GB"
            else:
                self.cpu[key] = self.ema(self.cpu[key], self.app_info.cpu_percent() / self.cpu_count)
                memory = f"{self.app_info.memory_full_info().uss / 1024 ** 2:.1f}MB"
            values.append(Value(f"{self.cpu[key]:.2f}%", bar=min(self.cpu[key] / 100, 1.0), sub=memory))
        self.refresh(tuple(values))
