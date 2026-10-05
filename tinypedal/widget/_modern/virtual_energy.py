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
Virtual energy Widget, modern design

Same panel as fuel, in percent of virtual energy, plus fuel ratio & fuel bias tiles.
"""

from __future__ import annotations

from ...module_info import minfo
from .consumption import COMMON_OPTIONS, ConsumptionPanel, Names, decimals
from .stats import Stat, Value


class Realtime(ConsumptionPanel):
    """Draw widget"""

    names = Names(
        title="Energy",
        refill="Refill",
        absolute="show_absolute_refilling",
        refill_decimals="decimal_places_refilling",
        warning_flash="show_low_energy_warning_flash",
        low_threshold="low_energy_lap_threshold",
        level_bar="show_energy_level_bar",
        start_mark="show_starting_energy_level_mark",
        refill_mark="show_refilling_level_mark",
    )
    options = (
        *COMMON_OPTIONS, *names[2:],
        "show_fuel_ratio_and_fuel_bias", "decimal_places_fuel_ratio", "decimal_places_fuel_bias",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.source = minfo.energy
        self.convert = float
        self.symbol = "%"
        self.show_ratio = self.wcfg["show_fuel_ratio_and_fuel_bias"]
        extra = [Stat("ratio", "Ratio", "8.888"), Stat("bias", "Bias", "+8.88")] if self.show_ratio else []
        self.setup_panel(extra)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        extra = []
        if self.show_ratio:
            theme = self.theme
            bias = minfo.hybrid.fuelEnergyBias
            extra = [
                Value(f"{minfo.hybrid.fuelEnergyRatio:.{decimals(self.wcfg, 'fuel_ratio')}f}", theme.text_dim),
                Value(f"{bias:+.{decimals(self.wcfg, 'fuel_bias')}f}", theme.negative if bias < 0 else theme.text_dim),
            ]
        self.read_panel(extra)
