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
Deltabest extended Widget, modern design

Delta to all time best, session best, stint best and last lap, colored by gain or loss.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...module_info import minfo
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "decimal_places", "delta_display_range", "freeze_duration",
        "show_all_time_deltabest", "show_session_deltabest", "show_stint_deltabest", "show_deltalast",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.decimals = max(int(wcfg["decimal_places"]), 1)
        self.delta_range = calc.decimal_strip(wcfg["delta_display_range"], self.decimals)
        self.freeze_duration = min(max(wcfg["freeze_duration"], 0), 30)
        items = (
            ("all_time_deltabest", "Best", theme.positive),
            ("session_deltabest", "Session", theme.best),
            ("stint_deltabest", "Stint", theme.orange),
            ("deltalast", "Last", theme.text_dim),
        )
        self.shown = tuple(wcfg[f"show_{key}"] for key, _, _ in items)
        sample = "+88." + "8" * self.decimals
        stats = [Stat(key, label, sample, "strong", accent) for (key, label, accent), show in zip(items, self.shown) if show]
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)
        self.last_laptimes = [0.0] * 4
        self.new_lap = True

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        delta = minfo.delta
        if delta.lapTimeCurrent < self.freeze_duration:
            deltas = tuple(delta.lapTimeLast - last for last in self.last_laptimes)
            self.new_lap = True
        else:
            if self.new_lap:
                self.last_laptimes = [delta.lapTimeBest, delta.lapTimeSession, delta.lapTimeStint, delta.lapTimeLast]
                self.new_lap = False
            deltas = (delta.deltaBest, delta.deltaSession, delta.deltaStint, delta.deltaLast)
        theme = self.theme
        values = []
        for value, show in zip(deltas, self.shown):
            if show:
                text = f"{calc.sym_max(value, self.delta_range):+.{self.decimals}f}"
                values.append(Value(text, theme.negative if value > 0 else theme.positive))
        self.refresh(tuple(values))
