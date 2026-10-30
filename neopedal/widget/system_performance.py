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
System performance Widget
"""

import os
from time import monotonic
from typing import TYPE_CHECKING

import psutil

from .. import calculation as calc
from ._base import Overlay

if TYPE_CHECKING:
    from ..template.widget_config_types import SystemPerformanceConfig

MEMORY_READ_INTERVAL = 5.0  # seconds, app memory (unique set size) is slow to read (about 1 ms)


class AppMemory:
    """App memory in megabytes (unique set size), read again every few seconds only"""

    __slots__ = ("process", "next_read", "used")

    def __init__(self, process: psutil.Process):
        self.process = process
        self.next_read = 0.0
        self.used = 0.0

    def megabytes(self) -> float:
        now = monotonic()
        if now >= self.next_read:
            self.next_read = now + MEMORY_READ_INTERVAL
            self.used = self.process.memory_full_info().uss / 1024 / 1024
        return self.used


class CpuAverage:
    """CPU use (percent) averaged over samples, started from first reading (full value at once, not risen from 0)"""

    __slots__ = ("ema", "value")

    def __init__(self, samples: int):
        self.ema = calc.ema_filter(samples)
        self.value: float | None = None

    def update(self, reading: float) -> float:
        value = self.value
        self.value = reading if value is None else self.ema(value, reading)
        return self.value


def start_cpu_readings(process: psutil.Process):
    """Next system & app CPU readings measured from now (first app reading of psutil is always 0, first system
    reading measured since a call long ago)"""
    psutil.cpu_percent()
    process.cpu_percent()


def fit_number(value: float, width: int, decimals: int) -> str:
    """Number right aligned in width characters, fewer decimals when too wide (never cut)"""
    text = f"{value:.{decimals}f}"
    while len(text) > width and decimals > 0:
        decimals -= 1
        text = f"{value:.{decimals}f}"
    return text.rjust(width)


def app_cpu_percent(process: psutil.Process, cpu_count: int) -> float:
    """App CPU use, share of every core (0 to 100%)

    Measured over the time since the previous reading, in steps of the system clock tick: readings close
    together can go far over 100% (1026.88% seen), which is noise.
    """
    return min(max(process.cpu_percent() / cpu_count, 0.0), 100.0)


class Realtime(Overlay):
    """Draw widget"""

    wcfg: "SystemPerformanceConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout = self.set_grid_layout(gap=self.wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(
            self.wcfg["font_name"],
            self.wcfg["font_size"],
            self.wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        # Config variable
        bar_padx = self.set_padding(self.wcfg["font_size"], self.wcfg["bar_padding"])

        if self.wcfg["layout"] == 0:
            prefix_just = max(
                len(self.wcfg["prefix_system"]),
                len(self.wcfg["prefix_neopedal"]),
            )
        else:
            prefix_just = 0

        self.prefix_sys = self.wcfg["prefix_system"].ljust(prefix_just)
        self.prefix_app = self.wcfg["prefix_neopedal"].ljust(prefix_just)

        # System
        if self.wcfg["show_system_performance"]:
            text_system = f"{self.prefix_sys}0.00% 0.00GB"
            self.bar_system = self.set_rawtext(
                text=text_system,
                width=font_m.width * len(text_system) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_system"],
                bg_color=self.wcfg["background_color_system"],
                last=0,
            )
            self.set_primary_orient(
                target=self.bar_system,
                column=self.wcfg["display_order_system"],
            )

        # APP performance
        if self.wcfg["show_neopedal_performance"]:
            text_app = f"{self.prefix_app}0.00% 0.00MB"
            self.bar_app = self.set_rawtext(
                text=text_app,
                width=font_m.width * len(text_app) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_neopedal"],
                bg_color=self.wcfg["background_color_neopedal"],
                last=0,
            )
            self.set_primary_orient(
                target=self.bar_app,
                column=self.wcfg["display_order_neopedal"],
            )

        self.cpu_system = CpuAverage(self.wcfg["average_samples"])
        self.cpu_app = CpuAverage(self.wcfg["average_samples"])

        # Last data
        self.app_info = psutil.Process(os.getpid())
        self.app_memory = AppMemory(self.app_info)
        self.cpu_count = os.cpu_count() or 1
        start_cpu_readings(self.app_info)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        if self.wcfg["show_system_performance"]:
            sys_cpu_ema = self.cpu_system.update(psutil.cpu_percent())
            self.update_system(self.bar_system, sys_cpu_ema, self.prefix_sys)

        if self.wcfg["show_neopedal_performance"]:
            app_cpu_ema = self.cpu_app.update(app_cpu_percent(self.app_info, self.cpu_count))
            self.update_app(self.bar_app, app_cpu_ema, self.prefix_app)

    # GUI update methods
    def update_system(self, target, data, prefix):
        """System performance"""
        memory_used = psutil.virtual_memory().used / 1024 / 1024 / 1024
        text = f"{prefix}{fit_number(data, 4, 2)}%{fit_number(memory_used, 5, 1)}GB"
        if target.last != text:
            target.last = text
            target.text = text
            target.update()

    def update_app(self, target, data, prefix):
        """APP performance"""
        memory_used = self.app_memory.megabytes()
        text = f"{prefix}{fit_number(data, 4, 2)}%{fit_number(memory_used, 5, 1)}MB"
        if target.last != text:
            target.last = text
            target.text = text
            target.update()
