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
Session Widget, modern design

Session type, system clock, remaining session time, estimated remaining laps.
"""

from __future__ import annotations

from time import strftime

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from ...i18n import tr_overlay
from ...module_info import minfo
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value

SESSION_NAMES = ("TEST", "PRACTICE", "QUALIFY", "WARMUP", "RACE")


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_session_name", "show_system_clock", "system_clock_format",
        "show_session_time", "show_estimated_laps", "show_predicted_extra_laps",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        stats = []
        if wcfg["show_session_name"]:
            stats.append(Stat("session_name", "Session", "PRACTICE", "strong"))
        if wcfg["show_system_clock"]:
            stats.append(Stat("system_clock", "Clock", "88:88PM"))
        if wcfg["show_session_time"]:
            stats.append(Stat("session_time", "Remaining", "~88:88:88", "strong", theme.accent))
        if wcfg["show_estimated_laps"]:
            sample = "888.888 (+8)" if wcfg["show_predicted_extra_laps"] else "888.888"
            stats.append(Stat("estimated_laps", "Laps left", sample))
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        remaining = api.read.session.remaining()
        offset = minfo.vehicles.finishTimeOffset
        est_remaining = remaining - offset
        values = []
        for key in self.keys:
            if key == "session_name":
                index = api.read.session.session_type()
                name = SESSION_NAMES[index] if 0 <= index < len(SESSION_NAMES) else ""
                values.append(Value(tr_overlay(name), theme.positive if index == 4 else theme.text))
            elif key == "system_clock":
                values.append(Value(strftime(self.wcfg["system_clock_format"]), theme.text_dim))
            elif key == "session_time":
                if offset:
                    text = f"~{calc.sec2countdown(max(est_remaining, 0)):.7}"
                else:
                    text = calc.sec2sessiontime(max(remaining, 0))
                values.append(Value(text))
            elif key == "estimated_laps":
                values.append(Value(self.laps_left(est_remaining)))
        self.refresh(tuple(values))

    def laps_left(self, est_remaining: float) -> str:
        """Estimated remaining laps"""
        if api.read.session.finish_type(minfo.vehicles.finishAsLap):
            laps = api.read.lap.remaining()
        else:
            lap_into = api.read.lap.progress()
            laps_timer = calc.end_timer_laps_remain(lap_into, minfo.delta.lapTimePace, est_remaining)
            laps = calc.time_type_laps_remain(calc.ceil(laps_timer), lap_into)
        text = f"{laps:.3f}"[:7]
        if self.wcfg["show_predicted_extra_laps"]:
            return f"{text} ({minfo.vehicles.finishLapOffset:+.0f})"
        return text
