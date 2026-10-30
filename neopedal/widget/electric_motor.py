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
Electric motor Widget
"""

from typing import TYPE_CHECKING

from .. import units
from ..api_control import api
from ..const_common import TEXT_PLACEHOLDER
from ._base import Overlay

if TYPE_CHECKING:
    from ..template.widget_config_types import ElectricMotorConfig


class Realtime(Overlay):
    """Draw widget"""

    wcfg: "ElectricMotorConfig"

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

        # Config units
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.unit_power = units.set_unit_power(self.cfg.units["power_unit"])
        self.symbol_power = units.set_symbol_power(self.cfg.units["power_unit"])

        # Motor temperature
        if self.wcfg["show_motor_temperature"]:
            self.bar_style_motor = (
                self.wcfg["background_color_motor_temperature"],
                self.wcfg["warning_color_overheat"],
            )
            self.bar_motor = self.set_rawtext(
                text="M TEMP",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_motor_temperature"],
                bg_color=self.bar_style_motor[0],
            )
            self.set_primary_orient(
                target=self.bar_motor,
                column=self.wcfg["display_order_motor_temperature"],
            )

        # Motor water temperature
        if self.wcfg["show_water_temperature"]:
            self.bar_style_water = (
                self.wcfg["background_color_water_temperature"],
                self.wcfg["warning_color_overheat"],
            )
            self.bar_water = self.set_rawtext(
                text="W TEMP",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_water_temperature"],
                bg_color=self.bar_style_water[0],
            )
            self.set_primary_orient(
                target=self.bar_water,
                column=self.wcfg["display_order_water_temperature"],
            )

        # Motor rpm
        if self.wcfg["show_rpm"]:
            self.bar_rpm = self.set_rawtext(
                text="RPM",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_rpm"],
                bg_color=self.wcfg["background_color_rpm"],
            )
            self.set_primary_orient(
                target=self.bar_rpm,
                column=self.wcfg["display_order_rpm"],
            )

        # Motor torque
        if self.wcfg["show_torque"]:
            self.bar_torque = self.set_rawtext(
                text="TORQUE",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_torque"],
                bg_color=self.wcfg["background_color_torque"],
            )
            self.set_primary_orient(
                target=self.bar_torque,
                column=self.wcfg["display_order_torque"],
            )

        # Motor power
        if self.wcfg["show_power"]:
            self.bar_power = self.set_rawtext(
                text="POWER",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_power"],
                bg_color=self.wcfg["background_color_power"],
            )
            self.set_primary_orient(
                target=self.bar_power,
                column=self.wcfg["display_order_power"],
            )

        # Regeneration level
        if self.wcfg["show_regeneration_level"]:
            self.bar_regen = self.set_rawtext(
                text="REGEN",
                width=bar_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_regeneration_level"],
                bg_color=self.wcfg["background_color_regeneration_level"],
            )
            self.set_primary_orient(
                target=self.bar_regen,
                column=self.wcfg["display_order_regeneration_level"],
            )

    def timerEvent(self, event):
        """Update when vehicle on track"""
        emotor = api.read.emotor
        # Motor temperature
        if self.wcfg["show_motor_temperature"]:
            self.update_motor(self.bar_motor, emotor.motor_temperature())

        # Water temperature
        if self.wcfg["show_water_temperature"]:
            self.update_water(self.bar_water, emotor.water_temperature())

        # Motor rpm
        if self.wcfg["show_rpm"]:
            self.update_rpm(self.bar_rpm, int(emotor.rpm()))

        # Motor torque
        if self.wcfg["show_torque"]:
            self.update_text(self.bar_torque, f"{fitted(emotor.torque()):>6}Nm")

        # Motor power (deployed)
        if self.wcfg["show_power"]:
            power = fitted(self.unit_power(emotor.power()))
            self.update_text(self.bar_power, f"{power:>6}{self.symbol_power}")

        # Regeneration power, not available on rF2
        if self.wcfg["show_regeneration_level"]:
            regen = emotor.regeneration_level()
            regen_text = fitted(self.unit_power(regen)) if regen >= 0 else TEXT_PLACEHOLDER
            self.update_text(self.bar_regen, f"{regen_text:>6}{self.symbol_power}")

    # GUI update methods
    def update_motor(self, target, data):
        """Motor temperature"""
        text = f"M{self.unit_temp(data):>6.1f}°"
        hot = data >= self.wcfg["overheat_threshold_motor"]
        if target.last != (text, hot):
            target.last = (text, hot)
            target.text = text
            target.bg = self.bar_style_motor[hot]
            target.update()

    def update_water(self, target, data):
        """Water temperature"""
        text = f"W{self.unit_temp(data):>6.1f}°"
        hot = data >= self.wcfg["overheat_threshold_water"]
        if target.last != (text, hot):
            target.last = (text, hot)
            target.text = text
            target.bg = self.bar_style_water[hot]
            target.update()

    def update_rpm(self, target, data):
        """Motor rpm"""
        if target.last != data:
            target.last = data
            target.text = f"{data:>5}rpm"
            target.update()

    def update_text(self, target, text):
        """Torque, power & regeneration: drawn again only when shown text changes"""
        if target.last != text:
            target.last = text
            target.text = text
            target.update()


def fitted(value: float, width: int = 6) -> str:
    """Value with 2 decimals cut to width, without trailing point (-2301 Nm, not -2301.Nm)"""
    return f"{value:z.2f}"[:width].rstrip(".")
