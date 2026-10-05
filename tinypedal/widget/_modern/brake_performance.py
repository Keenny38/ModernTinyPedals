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
Brake performance Widget, modern design

Braking rate (g) of last braking & best, difference to best, front & rear wheel lock time.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...module_info import minfo
from .base import ModernOverlay, display_order_options
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_transient_maximum_braking_rate", "show_maximum_braking_rate",
        "show_delta_braking_rate", "show_delta_braking_rate_in_percentage", "show_front_wheel_lock_duration",
        "show_rear_wheel_lock_duration",
        *display_order_options("brake_performance"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        items = (
            ("transient_maximum_braking_rate", "Braking", "8.88g"),
            ("maximum_braking_rate", "Best", "8.88g"),
            ("delta_braking_rate", "Delta", "+888%"),
            ("front_wheel_lock_duration", "Lock F", "88.8s"),
            ("rear_wheel_lock_duration", "Lock R", "88.8s"),
        )
        stats = [Stat(key, label, sample) for key, label, sample in items if wcfg[f"show_{key}"]]
        stats = self.display_ordered(stats)
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
        force = minfo.force
        values = []
        for key in self.keys:
            if key == "transient_maximum_braking_rate":
                values.append(Value(f"{force.transientMaxBrakingRate:.2f}g"))
            elif key == "maximum_braking_rate":
                values.append(Value(f"{force.maxBrakingRate:.2f}g", theme.positive))
            elif key == "delta_braking_rate":
                delta = force.deltaBrakingRate
                if self.wcfg["show_delta_braking_rate_in_percentage"]:
                    delta = delta / force.maxBrakingRate if force.maxBrakingRate else 0.0
                    text = f"{delta:+.0%}"
                else:
                    text = f"{delta:+.2f}"
                values.append(Value(text, theme.positive if delta > 0 else (theme.negative if delta < 0 else theme.text_dim)))
            elif key == "front_wheel_lock_duration":
                lock = max(minfo.wheels.lockingTime[:2])
                values.append(Value(f"{lock:.1f}s", theme.negative if lock > 0 else theme.text_dim))
            elif key == "rear_wheel_lock_duration":
                lock = max(minfo.wheels.lockingTime[2:])
                values.append(Value(f"{lock:.1f}s", theme.negative if lock > 0 else theme.text_dim))
        self.refresh(tuple(values))
