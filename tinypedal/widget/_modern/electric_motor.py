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
Electric motor Widget, modern design

Motor & water temperature (overheat highlight), RPM, torque, power, regeneration level.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "overheat_threshold_motor", "overheat_threshold_water", "show_motor_temperature",
        "show_water_temperature", "show_rpm", "show_torque", "show_power", "show_regeneration_level",
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
            ("regeneration_level", "Regen", f"+888.88{self.symbol_power}"),
        )
        stats = [Stat(key, label, sample) for key, label, sample in items if wcfg[f"show_{key}"]]
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
                values.append(Value(f"{emotor.torque():.2f}"[:6] + "Nm"))
            elif key == "power":
                power = calc.engine_power(emotor.torque(), emotor.rpm())
                values.append(Value(f"{self.unit_power(power):.2f}"[:6] + self.symbol_power))
            elif key == "regeneration_level":
                regen = self.unit_power(emotor.regeneration_level())
                values.append(Value(f"{regen:+.2f}"[:7] + self.symbol_power, self.theme.positive if regen > 0 else None))
        self.refresh(tuple(values))
