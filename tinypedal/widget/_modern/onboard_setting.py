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
Onboard setting Widget, modern design

Driver aid & car settings: ABS, TC (highlighted while active), TC cut & slip, brake migration,
motor map, front & rear anti-roll bars.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...api_control import api
from .base import DASH, ModernOverlay, display_order_options
from .stats import Stat, StatsMixin, Value

ITEMS = (
    ("abs", "ABS"),
    ("tc", "TC"),
    ("tc_cut", "Cut"),
    ("tc_slip", "Slip"),
    ("brake_migration", "BM"),
    ("motor_map", "Map"),
    ("front_arb", "FARB"),
    ("rear_arb", "RARB"),
)


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = ("font_size", "layout", *(f"show_{key}" for key, _ in ITEMS), *display_order_options("onboard_setting"))

    def design_unit(self) -> float:
        return float(self.wcfg["font_size"]) * 0.62  # font size 25 by default

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.add_font("strong", 1.45, "bold")
        stats = [Stat(key, label, "88", "strong") for key, label in ITEMS if self.wcfg[f"show_{key}"]]
        stats = self.display_ordered(stats)
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=self.wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        switch = api.read.switch
        readers = {
            "tc_cut": switch.tc_cut_level, "tc_slip": switch.tc_slip_level,
            "brake_migration": switch.brake_migration_level, "motor_map": switch.motor_map_level,
            "front_arb": switch.front_arb_level, "rear_arb": switch.rear_arb_level,
        }
        values = []
        for key in self.keys:
            if key in ("abs", "tc"):
                level = switch.abs_level() if key == "abs" else switch.tc_level()
                active = switch.abs_active() if key == "abs" else switch.tc_active()
                color = theme.warning if key == "abs" else theme.accent
                values.append(Value(DASH if level < 0 else f"{level}", color if active else None,
                                    theme.tint(color, 80) if active else None))
            else:
                level = readers[key]()
                values.append(Value(DASH if level < 0 else f"{level}", theme.text_faint if level < 0 else None))
        self.refresh(tuple(values))
