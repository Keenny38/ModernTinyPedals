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
Suspension travel Widget, modern design

Sections of four wheels: total, bump & rebound travel, travel ratio (gauge), motion ratio,
minimum, maximum & live position.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ...module_info import minfo
from ..suspension_travel import travel_text
from .base import ModernOverlay, display_order_options
from .draw import fraction
from .quad import QuadMixin, Section, Tile

if TYPE_CHECKING:
    from ...template.widget_config_types import SuspensionTravelConfig

SECTIONS = (
    ("total_travel", "Total"),
    ("bump_travel", "Bump"),
    ("rebound_travel", "Rebound"),
    ("travel_ratio", "Travel ratio"),
    ("motion_ratio", "Motion ratio"),
    ("minimum_position", "Min pos"),
    ("maximum_position", "Max pos"),
    ("live_position", "Live pos"),
)


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    wcfg: SuspensionTravelConfig

    options = ("font_size", "layout", "show_caption", *(f"show_{key}" for key, _ in SECTIONS),
               "show_live_position_relative_to_static_position", *display_order_options("suspension_travel"))

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.keys = tuple(self.display_ordered([key for key, _ in SECTIONS if self.wcfg[f"show_{key}"]], key=str))
        labels = dict(SECTIONS)
        sections = [
            Section(key, labels[key], "888%" if key == "travel_ratio" else "88.8",
                    min_width=3.2 if key == "travel_ratio" else 0.0)
            for key in self.keys
        ]
        self.set_size(*self.build_quads(sections, horizontal=self.wcfg["layout"] != 0))

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        self.draw_quads(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        wheels = minfo.wheels
        relative_live = self.wcfg["show_live_position_relative_to_static_position"]
        sections: dict[str, list[Tile]] = {key: [] for key in self.keys}
        for index in range(4):
            min_pos = wheels.minSuspensionPosition[index]
            max_pos = wheels.maxSuspensionPosition[index]
            static_pos = wheels.staticSuspensionPosition[index]
            total = max_pos - min_pos
            bump = max_pos - static_pos if static_pos != 0 and static_pos < max_pos else 0.0
            rebound = static_pos - min_pos if static_pos != 0 and static_pos > min_pos else 0.0
            ratio = bump / total if total > 0 and total >= bump else 0.0
            live = wheels.currentSuspensionPosition[index] - (static_pos if relative_live else 0.0)
            values = {
                "total_travel": total, "bump_travel": bump, "rebound_travel": rebound,
                "motion_ratio": wheels.motionRatio[index], "minimum_position": min_pos,
                "maximum_position": max_pos, "live_position": live,
            }
            for key in self.keys:
                if key == "travel_ratio":
                    sections[key].append(Tile((f"{ratio:.0%}",), level=fraction(ratio),
                                              level_color=theme.tint(theme.warning, 110)))
                else:
                    color = theme.accent if key == "live_position" else None
                    sections[key].append(Tile((travel_text(values[key]),), colors=(color,)))
        state = tuple(tuple(sections[key]) for key in self.keys)
        self.refresh_keyed(state, tuple(self.pixel_key(tiles, [rect.width() for rect in slot.tiles], "level", "mark")
                                        for slot, tiles in zip(self.quad_slots, state)))
