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
Battery Widget, modern design

Battery charge with gauge (low / high charge warning), state of charge shown by game, drain &
regen this lap, estimated net change, motor activation timer.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...api_control import api
from ...module_info import minfo
from .._common import warning_flash
from .base import DASH, ModernOverlay
from .draw import fraction
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_battery_charge", "high_battery_threshold", "low_battery_threshold",
        "show_battery_charge_warning_flash", "number_of_warning_flashes", "warning_flash_highlight_duration",
        "warning_flash_interval", "show_state_of_charge", "show_battery_drain", "show_battery_regen",
        "show_estimated_net_change", "show_activation_timer", "freeze_duration",
        "display_order_battery_charge", "display_order_battery_drain", "display_order_battery_regen",
        "display_order_estimated_net_change", "display_order_activation_timer",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.freeze_duration = min(max(wcfg["freeze_duration"], 0), 30)
        stats = []
        if wcfg["show_battery_charge"]:
            stats.append(Stat("charge", "Battery", "100.00%", "strong", theme.positive))
        if wcfg["show_state_of_charge"]:  # as shown by game (LMU), battery charge on rF2
            stats.append(Stat("soc", "SoC", "100.0%", "value", theme.accent))
        if wcfg["show_battery_drain"]:
            stats.append(Stat("drain", "Drain", "-88.88", "value", theme.negative))
        if wcfg["show_battery_regen"]:
            stats.append(Stat("regen", "Regen", "+88.88", "value", theme.positive))
        if wcfg["show_estimated_net_change"]:
            stats.append(Stat("net", "Net", "+88.88"))
        if wcfg["show_activation_timer"]:
            stats.append(Stat("timer", "Motor", "888.88s"))
        stats = self.display_ordered(stats, names={
            "charge": "battery_charge", "soc": "battery_charge", "drain": "battery_drain",
            "regen": "battery_regen", "net": "estimated_net_change", "timer": "activation_timer",
        })
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)
        if wcfg["show_battery_charge_warning_flash"]:
            self.warn_flash = warning_flash(
                wcfg["warning_flash_highlight_duration"],
                wcfg["warning_flash_interval"],
                wcfg["number_of_warning_flashes"],
            )
        else:
            self.warn_flash = None

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        hybrid = minfo.hybrid
        if 0 <= minfo.delta.lapTimeCurrent < self.freeze_duration:
            drain, regen = hybrid.batteryDrainLast, hybrid.batteryRegenLast
        else:
            drain, regen = hybrid.batteryDrain, hybrid.batteryRegen
        values = []
        for key in self.keys:
            if key == "charge":
                charge = hybrid.batteryCharge
                if charge >= self.wcfg["high_battery_threshold"]:
                    warning = 2
                elif charge <= self.wcfg["low_battery_threshold"]:
                    warning = 1
                else:
                    warning = 0
                if self.warn_flash is not None and not self.warn_flash.send(warning):
                    warning = 0
                warn_color = (None, theme.negative, theme.warning)[warning]
                values.append(Value(f"{charge:.2f}%", warn_color,
                                    theme.tint(warn_color, 55) if warn_color is not None else None,
                                    bar=fraction(charge / 100),
                                    bar_color=theme.negative if charge <= self.wcfg["low_battery_threshold"] else theme.positive))
            elif key == "soc":
                if hybrid.motorState > 0:  # electric motor available
                    soc = min(max(api.read.emotor.state_of_charge(), 0.0), 100.0)
                    values.append(Value(f"{soc:.1f}%", bar=fraction(soc / 100)))
                else:
                    values.append(Value(DASH, theme.text_faint))
            elif key == "drain":
                values.append(Value(f"-{drain:.2f}"))
            elif key == "regen":
                values.append(Value(f"+{regen:.2f}"))
            elif key == "net":
                net = hybrid.batteryNetChange
                values.append(Value(f"{net:+.2f}", theme.positive if net > 0 else (theme.negative if net < 0 else None)))
            elif key == "timer":
                values.append(Value(f"{hybrid.motorActiveTimer:.2f}s", theme.text_dim))
        self.refresh(tuple(values))
