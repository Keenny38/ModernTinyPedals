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
Engine Widget, modern design

Oil & water temperature (overheat highlight), turbo pressure, RPM & max RPM, torque, power,
power to weight ratio.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...module_info import minfo
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "overheat_threshold_oil", "overheat_threshold_water", "show_oil_temperature",
        "show_water_temperature", "show_turbo_pressure", "show_rpm", "show_rpm_maximum", "show_torque",
        "show_power", "show_power_to_weight_ratio",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit_cfg = self.cfg.units
        self.unit_temp = units.set_unit_temperature(unit_cfg["temperature_unit"])
        self.unit_power = units.set_unit_power(unit_cfg["power_unit"])
        self.symbol_power = units.set_symbol_power(unit_cfg["power_unit"])
        self.unit_pres = units.set_unit_pressure(unit_cfg["turbo_pressure_unit"])
        self.symbol_pres = units.set_symbol_pressure(unit_cfg["turbo_pressure_unit"])
        self.unit_weight = units.set_unit_weight(unit_cfg["weight_unit"])
        items = (
            ("oil_temperature", "Oil", "888.8°"),
            ("water_temperature", "Water", "888.8°"),
            ("turbo_pressure", "Turbo", f"8.888{self.symbol_pres}"),
            ("rpm", "RPM", "88888"),
            ("rpm_maximum", "Max RPM", "88888"),
            ("torque", "Torque", "888.88Nm"),
            ("power", "Power", f"888.88{self.symbol_power}"),
            ("power_to_weight_ratio", "P/W", "8.888"),
        )
        stats = [Stat(key, label, sample) for key, label, sample in items if wcfg[f"show_{key}"]]
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)
        self.ema_power = 0.0
        self.max_power_kw = 0.0

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
        engine = api.read.engine
        rpm = engine.rpm()
        torque = engine.torque()
        if torque:
            power_kw = calc.engine_power(torque, rpm)
        else:
            power_kw = 0.0
            max_ve = engine.max_virtual_energy()
            if max_ve > 0:  # from energy consumption if torque not available
                power_kw = minfo.energy.rateOfConsumption * max_ve / 100_000
                torque = calc.engine_torque(power_kw, rpm)
        values = []
        for key in self.keys:
            if key == "oil_temperature":
                values.append(self.temperature(engine.oil_temperature(), self.wcfg["overheat_threshold_oil"]))
            elif key == "water_temperature":
                values.append(self.temperature(engine.water_temperature(), self.wcfg["overheat_threshold_water"]))
            elif key == "turbo_pressure":
                values.append(Value(f"{self.unit_pres(int(engine.turbo()) * 0.001):.3f}"[:5] + self.symbol_pres))
            elif key == "rpm":
                values.append(Value(f"{int(rpm)}"))
            elif key == "rpm_maximum":
                values.append(Value(f"{int(engine.rpm_max())}", self.theme.text_dim))
            elif key == "torque":
                values.append(Value(f"{torque:.2f}"[:6] + "Nm"))
            elif key == "power":
                values.append(Value(f"{self.unit_power(power_kw):.2f}"[:6] + self.symbol_power))
            elif key == "power_to_weight_ratio":
                weight = minfo.wheels.totalStaticWeight
                self.ema_power += 0.2 * (power_kw - self.ema_power)
                self.max_power_kw = max(self.max_power_kw, self.ema_power)
                ratio = self.unit_power(self.max_power_kw) / self.unit_weight(weight) if weight > 0 else 0.0
                values.append(Value(f"{ratio:.3f}", self.theme.text_dim))
        self.refresh(tuple(values))
