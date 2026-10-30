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
Battery Widget
"""

from typing import TYPE_CHECKING

from ..const_common import TEXT_PLACEHOLDER
from ..module_info import minfo
from ._base import Overlay
from ._common import warning_flash

if TYPE_CHECKING:
    from ..template.widget_config_types import BatteryConfig


class Realtime(Overlay):
    """Draw widget"""

    wcfg: "BatteryConfig"

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
        bar_width = font_m.width * 8 + bar_padx
        self.freeze_duration = min(max(self.wcfg["freeze_duration"], 0), 30)

        # Battery charge
        if self.wcfg["show_battery_charge"]:
            self.bar_style_charge = (
                self.wcfg["background_color_battery_charge"],
                self.wcfg["warning_color_low_battery"],
                self.wcfg["warning_color_high_battery"],
            )
            self.bar_charge = self.set_rawtext(
                text="BATTERY",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_battery_charge"],
                bg_color=self.bar_style_charge[0],
            )
            self.set_primary_orient(
                target=self.bar_charge,
                column=self.wcfg["display_order_battery_charge"],
            )

        # Battery drain
        if self.wcfg["show_battery_drain"]:
            self.bar_drain = self.set_rawtext(
                text="B DRAIN",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_battery_drain"],
                bg_color=self.wcfg["background_color_battery_drain"],
            )
            self.set_primary_orient(
                target=self.bar_drain,
                column=self.wcfg["display_order_battery_drain"],
            )

        # Battery regen
        if self.wcfg["show_battery_regen"]:
            self.bar_regen = self.set_rawtext(
                text="B REGEN",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_battery_regen"],
                bg_color=self.wcfg["background_color_battery_regen"],
            )
            self.set_primary_orient(
                target=self.bar_regen,
                column=self.wcfg["display_order_battery_regen"],
            )

        # Battery charge net change
        if self.wcfg["show_estimated_net_change"]:
            self.bar_net = self.set_rawtext(
                text="B   NET",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_estimated_net_change"],
                bg_color=self.wcfg["background_color_estimated_net_change"],
            )
            self.set_primary_orient(
                target=self.bar_net,
                column=self.wcfg["display_order_estimated_net_change"],
            )

        # Activation timer
        if self.wcfg["show_activation_timer"]:
            self.bar_timer = self.set_rawtext(
                text="B TIMER",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_activation_timer"],
                bg_color=self.wcfg["background_color_activation_timer"],
            )
            self.set_primary_orient(
                target=self.bar_timer,
                column=self.wcfg["display_order_activation_timer"],
            )

        if self.wcfg["show_battery_charge_warning_flash"]:
            self.warn_flash = warning_flash(
                self.wcfg["warning_flash_highlight_duration"],
                self.wcfg["warning_flash_interval"],
                self.wcfg["number_of_warning_flashes"],
            )

    def timerEvent(self, event):
        """Update when vehicle on track"""
        hybrid = minfo.hybrid
        # Battery charge & usage
        if self.wcfg["show_battery_charge"]:
            battery_charge = hybrid.batteryCharge

            if battery_charge >= self.wcfg["high_battery_threshold"]:
                batt_warning = 2
            elif battery_charge <= self.wcfg["low_battery_threshold"]:
                batt_warning = 1
            else:
                batt_warning = 0

            if not has_battery(hybrid):  # car without hybrid system: no low battery warning
                self.update_charge(self.bar_charge, -1.0, 0)
            else:
                if self.wcfg["show_battery_charge_warning_flash"]:
                    batt_highlight = self.warn_flash.send(batt_warning)
                    if batt_highlight:
                        padding = 0.00000001  # add padding for switching state
                    else:
                        batt_warning = 0
                        padding = 0
                else:
                    padding = 0

                self.update_charge(self.bar_charge, battery_charge + padding, batt_warning)

        # Last lap usage shown after line, if a full lap was recorded
        if 0 <= minfo.delta.lapTimeCurrent < self.freeze_duration and has_last_lap(hybrid):
            battery_drain = hybrid.batteryDrainLast
            battery_regen = hybrid.batteryRegenLast
        else:
            battery_drain = hybrid.batteryDrain
            battery_regen = hybrid.batteryRegen

        if self.wcfg["show_battery_drain"]:
            self.update_drain(self.bar_drain, battery_drain)

        if self.wcfg["show_battery_regen"]:
            self.update_regen(self.bar_regen, battery_regen)

        if self.wcfg["show_estimated_net_change"]:
            net_change = hybrid.batteryNetChange
            self.update_net(self.bar_net, net_change)

        # Motor activation timer
        if self.wcfg["show_activation_timer"]:
            active_timer = hybrid.motorActiveTimer
            self.update_timer(self.bar_timer, active_timer)

    # GUI update methods
    def update_charge(self, target, data, color_index):
        """Battery charge, -1 if no battery"""
        if target.last != data:
            target.last = data
            target.text = f"B{TEXT_PLACEHOLDER:>7}" if data < 0 else f"B{data:>7.2f}"
            target.bg = self.bar_style_charge[color_index]
            target.update()

    def update_drain(self, target, data):
        """Battery drain"""
        if target.last != data:
            target.last = data
            target.text = f"{change_text(data, '-'):>8}"
            target.update()

    def update_regen(self, target, data):
        """Battery regen"""
        if target.last != data:
            target.last = data
            target.text = f"{change_text(data, '+'):>8}"
            target.update()

    def update_net(self, target, data):
        """Battery charge net change, none (0) until a full lap is recorded"""
        if target.last != data:
            target.last = data
            target.text = f"N{change_text(data, '') if data else TEXT_PLACEHOLDER:>7}"
            target.update()

    def update_timer(self, target, data):
        """Motor activation timer"""
        if target.last != data:
            target.last = data
            target.text = f"{data:>7.2f}s"
            target.update()


def has_battery(hybrid) -> bool:
    """Electric motor & battery available (no motor state & empty battery: car without hybrid system)"""
    return hybrid.motorState > 0 or hybrid.batteryCharge > 0


def has_last_lap(hybrid) -> bool:
    """Battery usage of a full lap recorded (none after reset, or module started mid-lap)"""
    return hybrid.batteryDrainLast > 0 or hybrid.batteryRegenLast > 0


def change_text(value: float, sign: str) -> str:
    """Battery charge change: sign "-" drain, "+" regen, "" net (sign of value), no sign when shown as 0"""
    text = f"{abs(value):.2f}"
    if text == "0.00":
        return text
    return (sign or ("-" if value < 0 else "+")) + text
