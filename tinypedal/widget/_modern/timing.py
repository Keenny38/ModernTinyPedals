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
Timing Widget, modern design

Lap times: session best, personal best, last, current, estimated, session personal best,
stint best, average pace. Colored mark before each label.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from ...const_common import MAX_SECONDS, TEXT_NOLAPTIME
from ...module_info import minfo
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value

SAMPLE = "8:88.888"


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout",
        "show_session_best", "show_session_best_from_same_class_only", "show_best", "show_last",
        "show_current", "show_estimated", "show_session_personal_best", "show_stint_best", "show_average_pace",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        items = (
            ("session_best", "Session", theme.best),
            ("best", "Best", theme.positive),
            ("last", "Last", theme.text_dim),
            ("current", "Current", theme.text),
            ("estimated", "Estimate", theme.accent),
            ("session_personal_best", "Session PB", theme.warning),
            ("stint_best", "Stint", theme.orange),
            ("average_pace", "Pace", theme.text_muted),
        )
        self.keys = tuple(key for key, _, _ in items if wcfg[f"show_{key}"])
        stats = [Stat(key, label, SAMPLE, "value", accent) for key, label, accent in items if key in self.keys]
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)
        self.player_index = 0
        self.laptime_session_best = MAX_SECONDS

    def post_update(self):
        self.laptime_session_best = MAX_SECONDS

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        values = []
        for key in self.keys:
            if key == "session_best":
                values.append(Value(laptime(self.session_best())))
            elif key == "best":
                values.append(Value(laptime(minfo.delta.lapTimeBest)))
            elif key == "last":
                valid = minfo.delta.isValidLap
                values.append(Value(laptime(minfo.delta.lapTimeLast), None if valid else theme.negative))
            elif key == "current":
                values.append(Value(laptime(minfo.delta.lapTimeCurrent)))
            elif key == "estimated":
                values.append(Value(laptime(minfo.delta.lapTimeEstimated)))
            elif key == "session_personal_best":
                values.append(Value(laptime(api.read.timing.best_laptime())))
            elif key == "stint_best":
                values.append(Value(laptime(minfo.delta.lapTimeStint)))
            elif key == "average_pace":
                values.append(Value(laptime(minfo.delta.lapTimePace)))
        self.refresh(tuple(values))

    def session_best(self) -> float:
        """Session best lap time, one vehicle checked per update"""
        if (not self.wcfg["show_session_best_from_same_class_only"]
                or api.read.vehicle.same_class(self.player_index)):
            best = api.read.timing.best_laptime(self.player_index)
            if 0 < best < self.laptime_session_best:
                self.laptime_session_best = best
        if self.player_index < api.read.vehicle.total_vehicles():
            self.player_index += 1
        else:
            self.player_index = 0
        return self.laptime_session_best


def laptime(seconds: float) -> str:
    """Lap time text"""
    if 0 < seconds < MAX_SECONDS:
        return calc.sec2laptime(seconds)
    return TEXT_NOLAPTIME
