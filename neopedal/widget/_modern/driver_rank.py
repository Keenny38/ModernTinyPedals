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
Driver rank Widget, modern design

Driver Rank (DR) & Safety Rank (SR) of player in rank color (bronze, silver, gold, platinum) with
progress to next tier as a bar, and track limits points against points allowed per penalty (amber
once any, red one point before penalty). A dash while unknown.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPainter

from ...process import driver_ranks as dr
from ...process.driver_ranks import Rank
from ..driver_rank import ITEMS, player_ranks, track_limits, track_limits_text
from .base import DASH, ModernOverlay
from .stats import Stat, StatsMixin, Value

LABELS = {"driver_rank": "Driver Rank", "safety_rank": "Safety Rank", "track_limits": "Track limits"}
RANK_COLORS = {name: QColor(color) for name, color in dr.RANK_COLORS.items()}


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_progress", "show_driver_rank", "show_safety_rank", "show_track_limits",
        "display_order_driver_rank", "display_order_safety_rank", "display_order_track_limits",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.show_progress = wcfg["show_progress"]
        stats = []
        for key in ITEMS:
            if not wcfg[f"show_{key}"]:
                continue
            if key == "track_limits":
                stats.append(Stat(key, LABELS[key], "8.88/88"))
            else:
                stats.append(Stat(key, LABELS[key], "Platinum 3", "strong",
                                  sub_sample="100%" if self.show_progress else ""))
        stats = self.display_ordered(stats)
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0, show_sub=self.show_progress)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        player = player_ranks() if ("driver_rank" in self.keys or "safety_rank" in self.keys) else None
        values = []
        for key in self.keys:
            if key == "track_limits":
                values.append(self.limits_value(*track_limits()))
            else:
                values.append(self.rank_value(getattr(player, "driver" if key == "driver_rank" else "safety", None)))
        self.refresh(tuple(values))

    def rank_value(self, rank: Rank | None) -> Value:
        theme = self.theme
        if rank is None:
            return Value(DASH, theme.text_dim)
        color = RANK_COLORS.get(rank.name.casefold(), theme.text)
        if not self.show_progress:
            return Value(rank.text, color)
        progress = max(min(rank.progress, 100), 0)
        return Value(rank.text, color, sub=f"{progress}%", sub_color=theme.text_muted, bar=progress / 100,
                     bar_color=color)

    def limits_value(self, points: float, limit: float) -> Value:
        theme = self.theme
        if limit > 0 and points >= limit - 1:
            color = theme.negative
        else:
            color = theme.warning if points > 0 else theme.text_dim
        return Value(track_limits_text(points, limit, DASH), color)
