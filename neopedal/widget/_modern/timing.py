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
Timing Widget, modern design

Lap times: session best, personal best, last, current, estimated, session personal best,
stint best, average pace. Colored mark before each label. Current lap highlighted in loss color
while game invalidated it (track limits).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ...api_control import api
from ...module_info import minfo
from .._common import SessionBestLap
from .base import ModernOverlay, laptime_text, reference_accent
from .stats import Stat, StatsMixin, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import TimingConfig

SAMPLE = "8:88.888"


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: TimingConfig

    options = (
        "font_size", "layout",
        "show_session_best", "show_session_best_from_same_class_only", "show_best", "show_last",
        "show_current", "show_estimated", "show_session_personal_best", "show_stint_best", "show_average_pace",
        "show_invalid_lap_indicator",
        "display_order_session_best", "display_order_best", "display_order_last", "display_order_current",
        "display_order_estimated", "display_order_session_personal_best", "display_order_stint_best",
        "display_order_average_pace",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        items = (  # reference laps: accents shared with deltabest extended & speed delta
            ("session_best", "Session", reference_accent(theme, "session_best")),
            ("best", "Best", reference_accent(theme, "best")),
            ("last", "Last", reference_accent(theme, "last")),
            ("current", "Current", theme.text),
            ("estimated", "Estimate", theme.accent),
            ("session_personal_best", "Session PB", reference_accent(theme, "session_personal_best")),
            ("stint_best", "Stint", reference_accent(theme, "stint_best")),
            ("average_pace", "Pace", theme.text_muted),
        )
        stats = [Stat(key, label, SAMPLE, "value", accent) for key, label, accent in items if wcfg[f"show_{key}"]]
        stats = self.display_ordered(stats)
        self.keys = tuple(stat.key for stat in stats)
        self.show_invalid = wcfg["show_invalid_lap_indicator"]
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)
        self.session_best = SessionBestLap()

    def post_update(self):
        self.session_best.reset()

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
                best = self.session_best.update(self.wcfg["show_session_best_from_same_class_only"])
                values.append(Value(laptime(best)))
            elif key == "best":
                values.append(Value(laptime(minfo.delta.lapTimeBest)))
            elif key == "last":  # invalid lap in red, as current lap (invalid lap indicator option)
                invalid = self.show_invalid and not minfo.delta.isValidLap
                values.append(Value(laptime(minfo.delta.lapTimeLast), theme.negative if invalid else None))
            elif key == "current":
                text = laptime(minfo.delta.lapTimeCurrent, True)
                if self.show_invalid and api.read.lap.invalidated():
                    values.append(Value(text, theme.negative, theme.tint(theme.negative, 55)))
                else:
                    values.append(Value(text))
            elif key == "estimated":
                values.append(Value(laptime(minfo.delta.lapTimeEstimated, True)))
            elif key == "session_personal_best":
                values.append(Value(laptime(api.read.timing.best_laptime())))
            elif key == "stint_best":
                values.append(Value(laptime(minfo.delta.lapTimeStint)))
            elif key == "average_pace":
                values.append(Value(laptime(minfo.delta.lapTimePace)))
        self.refresh(tuple(values))


def laptime(seconds: float, running: bool = False) -> str:
    """Lap time text (same format as every overlay), running: lap being driven"""
    return laptime_text(seconds, running=running)
