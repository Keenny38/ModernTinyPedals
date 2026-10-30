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
System performance Widget, modern design

CPU & memory usage of system and of this app.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import psutil
from PySide6.QtGui import QPainter

from ..system_performance import AppMemory, CpuAverage, app_cpu_percent, start_cpu_readings
from .base import ModernOverlay, display_order_options
from .draw import fraction
from .stats import Stat, StatsMixin, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import SystemPerformanceConfig


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: SystemPerformanceConfig

    options = (
        "font_size", "layout", "average_samples", "show_system_performance", "show_neopedal_performance",
        *display_order_options("system_performance"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.app_info = psutil.Process(os.getpid())
        self.app_memory = AppMemory(self.app_info)
        self.cpu_count = os.cpu_count() or 1
        start_cpu_readings(self.app_info)
        stats = []
        if wcfg["show_system_performance"]:
            stats.append(Stat("system", "System", "888.88%", sub_sample="888.8GB"))
        if wcfg["show_neopedal_performance"]:
            stats.append(Stat("app", "App", "888.88%", sub_sample="8888.8MB"))
        stats = self.display_ordered(stats, names={"app": "neopedal"})
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0, show_sub=True)
        self.set_size(width, height)
        self.cpu = {key: CpuAverage(wcfg["average_samples"]) for key in ("system", "app")}

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        values = []
        for key in self.keys:
            if key == "system":
                cpu = self.cpu[key].update(psutil.cpu_percent())
                memory = f"{psutil.virtual_memory().used / 1024 ** 3:.1f}GB"
            else:
                cpu = self.cpu[key].update(app_cpu_percent(self.app_info, self.cpu_count))
                memory = f"{self.app_memory.megabytes():.1f}MB"
            values.append(Value(f"{cpu:.2f}%", bar=fraction(cpu / 100), sub=memory))
        state = tuple(values)
        self.refresh_keyed(state, self.pixel_key(state, [slot.value.width() for slot in self.slots], "bar"))
