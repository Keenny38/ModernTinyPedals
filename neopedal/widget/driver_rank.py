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
Driver rank Widget

Le Mans Ultimate Driver Rank (DR) & Safety Rank (SR) of player, as shown by game menu (rank, tier &
progress to next tier, read from game folder, see rank_info), and track limits points of session against
points allowed per penalty. A dash while unknown (game folder not found, never signed in online, no
limit given for session).
"""

from __future__ import annotations

from ..api_control import api
from ..demo_state import drawing_demo
from ..formatter import format_points
from ..process.driver_ranks import DriverRanks, Rank
from ..rank_info import ranks
from ._base import Overlay

ITEMS = ("driver_rank", "safety_rank", "track_limits")  # option key suffixes, design order
DEMO_PLAYER = DriverRanks("", "", "", "", Rank("Silver", 2, 40), Rank("Platinum", 3, 50))  # overlay pictures


def player_ranks() -> DriverRanks | None:
    """Ranks of player (simulated ones while overlay picture is drawn), file checked in background"""
    if drawing_demo():
        return DEMO_PLAYER
    ranks.poll()
    return ranks.player


def track_limits() -> tuple[float, float]:
    """Track limits points of player & points allowed per penalty of session (0: no limit given)"""
    return api.read.session.cut_points(), api.read.session.limits_points()


def track_limits_text(points: float, limit: float, dash: str = "-") -> str:
    """Track limits points against limit: 1.25/5"""
    return f"{format_points(points)}/{format_points(limit) if limit > 0 else dash}"


class Realtime(Overlay):
    """Draw widget"""

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
        self.show_progress = self.wcfg["show_progress"]
        shown = [key for key in ITEMS if self.wcfg[f"show_{key}"]]
        prefix_just = max((len(self.wcfg[f"prefix_{key}"]) for key in shown), default=0) if self.wcfg["layout"] == 0 else 0
        self.prefixes = {key: self.wcfg[f"prefix_{key}"].ljust(prefix_just) for key in shown}
        self.value_width = 8  # "P3  100%", "1.25/10"
        self.bars = {}
        for key in shown:
            sample = f"{self.prefixes[key]}{'8' * self.value_width}"
            bar = self.set_rawtext(
                text=f"{self.prefixes[key]}{'-':>{self.value_width}}",
                width=font_m.width * len(sample) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg[f"font_color_{key}"],
                bg_color=self.wcfg[f"background_color_{key}"],
                last=None,
            )
            self.set_primary_orient(target=bar, column=self.wcfg[f"display_order_{key}"])
            self.bars[key] = bar

    def timerEvent(self, event):
        """Update when vehicle on track"""
        player = player_ranks() if ("driver_rank" in self.bars or "safety_rank" in self.bars) else None
        for key, bar in self.bars.items():
            if key == "track_limits":
                text = track_limits_text(*track_limits())
            else:
                text = self.rank_text(getattr(player, "driver" if key == "driver_rank" else "safety", None))
            self.update_text(bar, text, self.prefixes[key])

    def rank_text(self, rank: Rank | None) -> str:
        """Short rank & progress: S2 40%"""
        if rank is None:
            return "-"
        return f"{rank.short} {rank.progress:>3}%" if self.show_progress else rank.text

    # GUI update methods
    def update_text(self, target, text: str, prefix: str):
        """Update item text"""
        if target.last != text:
            target.last = text
            target.text = f"{prefix}{text:>{self.value_width}}"
            target.update()
