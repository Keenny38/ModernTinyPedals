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
Damage stats Widget, modern design

Aero, body, suspension & tyre integrity with gauges, low integrity in red.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...api_control import api
from ...const_common import TEXT_NA
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value

ITEMS = (
    ("aero", "Aero"),
    ("body", "Body"),
    ("suspension", "Suspension"),
    ("tyre", "Tyre"),
)


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "decimal_places",
        *(option for key, _ in ITEMS for option in (f"show_{key}_integrity", f"low_{key}_integrity_threshold")),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.decimals = max(int(self.wcfg["decimal_places"]), 0)
        sample = "100." + "8" * self.decimals + "%" if self.decimals else "100%"
        stats = [Stat(key, label, sample) for key, label in ITEMS if self.wcfg[f"show_{key}_integrity"]]
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
        values = []
        for key in self.keys:
            if key == "aero":
                value = api.read.vehicle.aero_damage()
                value = 1 - value if value >= 0 else -1
            elif key == "body":
                value = 1 - sum(api.read.vehicle.damage_severity()) / 16
            elif key == "suspension":
                damage = max(api.read.wheel.suspension_damage())
                value = 1 - damage if damage >= 0 else float(not any(api.read.wheel.is_detached()))
            else:
                value = min(api.read.tyre.wear())
            if value == -1:
                values.append(Value(TEXT_NA, theme.text_faint))
                continue
            value = max(value, 0.0)
            low = value <= self.wcfg[f"low_{key}_integrity_threshold"]
            color = theme.negative if low else theme.positive
            values.append(Value(f"{value:.{self.decimals}%}", theme.negative if low else None, bar=min(value, 1.0), bar_color=color))
        self.refresh(tuple(values))
