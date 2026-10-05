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
Push to pass Widget, modern design

Battery charge (ready, cooldown, draining, regen) & activation timer.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...api_control import api
from ...module_info import minfo
from .base import ModernOverlay, display_order_options
from .draw import fraction
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_battery_charge", "show_activation_timer", "activation_threshold_gear",
        "activation_threshold_speed", "activation_threshold_throttle", "minimum_activation_time_delay",
        "maximum_activation_time_per_lap",
        *display_order_options("push_to_pass"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit = self.unit * 0.5  # font size 30 by default
        for role, scale, weight in (("value", 1.0, "semibold"), ("strong", 1.0, "bold"), ("label", 0.68, "bold")):
            self.add_font(role, scale * 1.4 if role != "label" else scale, weight,
                          spacing=106 if role == "label" else 100, caps=role == "label")
        stats = []
        if wcfg["show_battery_charge"]:
            stats.append(Stat("charge", "P2P", "MAX", "strong"))
        if wcfg["show_activation_timer"]:
            stats.append(Stat("timer", "Active", "88.8"))
        stats = self.display_ordered(stats, names={"charge": "battery_charge", "timer": "activation_timer"})
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        theme = self.theme
        hybrid = minfo.hybrid
        values = []
        for key in self.keys:
            if key == "charge":
                state = hybrid.motorState
                if state == 1:  # cooldown check
                    state = int(
                        api.read.engine.gear() >= wcfg["activation_threshold_gear"]
                        and api.read.vehicle.speed() * 3.6 > wcfg["activation_threshold_speed"]
                        and api.read.inputs.throttle_raw() >= wcfg["activation_threshold_throttle"]
                        and hybrid.motorInactiveTimer >= wcfg["minimum_activation_time_delay"]
                        and hybrid.motorActiveTimer < wcfg["maximum_activation_time_per_lap"] - 0.05
                    )
                charge = hybrid.batteryCharge
                text = "MAX" if charge >= 100 else f"{charge:.0f}"
                fills = (None, theme.tint(theme.positive, 70), theme.tint(theme.accent, 90), theme.tint(theme.warning, 80))
                colors = (theme.text_faint, theme.positive, theme.accent, theme.warning)
                values.append(Value(text, colors[min(state, 3)], fills[min(state, 3)], bar=fraction(charge / 100),
                                    bar_color=colors[min(state, 3)]))
            elif key == "timer":
                active = hybrid.motorState == 2
                values.append(Value(f"{hybrid.motorActiveTimer:.1f}", theme.accent if active else theme.text_dim))
        self.refresh(tuple(values))
