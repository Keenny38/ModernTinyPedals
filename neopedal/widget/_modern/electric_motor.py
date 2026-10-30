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
Electric motor Widget, modern design

Motor & water temperature (overheat highlight), RPM, torque, power deployed, regeneration power.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ... import units
from ...api_control import api
from ..electric_motor import fitted
from .base import DASH, ModernOverlay, display_order_options
from .stats import Stat, StatsMixin, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import ElectricMotorConfig


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: ElectricMotorConfig

    options = (
        "font_size", "layout", "overheat_threshold_motor", "overheat_threshold_water", "show_motor_temperature",
        "show_water_temperature", "show_rpm", "show_torque", "show_power", "show_regeneration_level",
        *display_order_options("electric_motor"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.unit_power = units.set_unit_power(self.cfg.units["power_unit"])
        self.symbol_power = units.set_symbol_power(self.cfg.units["power_unit"])
        items = (
            ("motor_temperature", "Motor", "888.8°"),
            ("water_temperature", "Water", "888.8°"),
            ("rpm", "RPM", "88888"),
            ("torque", "Torque", "888.88Nm"),
            ("power", "Power", f"888.88{self.symbol_power}"),
            ("regeneration_level", "Regen", f"888.88{self.symbol_power}"),
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

    def temperature(self, value: float, threshold: float) -> Value:
        """Temperature, highlighted if overheating"""
        hot = value >= threshold
        theme = self.theme
        return Value(f"{self.unit_temp(value):.1f}°", theme.negative if hot else None, theme.tint(theme.negative, 55) if hot else None)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        emotor = api.read.emotor
        values = []
        for key in self.keys:
            if key == "motor_temperature":
                values.append(self.temperature(round(emotor.motor_temperature(), 1), self.wcfg["overheat_threshold_motor"]))
            elif key == "water_temperature":
                values.append(self.temperature(round(emotor.water_temperature(), 1), self.wcfg["overheat_threshold_water"]))
            elif key == "rpm":
                values.append(Value(f"{int(emotor.rpm())}"))
            elif key == "torque":
                values.append(Value(fitted(emotor.torque()) + "Nm"))
            elif key == "power":
                values.append(Value(fitted(self.unit_power(emotor.power())) + self.symbol_power))
            elif key == "regeneration_level":
                regen = emotor.regeneration_level()
                if regen < 0:  # not available (rF2)
                    values.append(Value(DASH, self.theme.text_faint))
                else:
                    text = fitted(self.unit_power(regen))
                    values.append(Value(text + self.symbol_power, self.theme.positive if float(text) else None))
        self.refresh(tuple(values))
