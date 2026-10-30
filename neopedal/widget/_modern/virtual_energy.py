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
Virtual energy Widget, modern design

Same panel as fuel, in percent of virtual energy, plus fuel ratio & fuel bias tiles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...module_info import minfo
from .base import DASH, signed
from .consumption import COMMON_OPTIONS, ConsumptionPanel, Names, decimals
from .stats import Stat, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import VirtualEnergyConfig


class Realtime(ConsumptionPanel):
    """Draw widget"""

    wcfg: VirtualEnergyConfig

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
        refill_shown="show_refilling",
    )
    options = (
        *COMMON_OPTIONS, *names[2:],
        "show_fuel_ratio", "show_fuel_bias", "decimal_places_fuel_ratio", "decimal_places_fuel_bias",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.source = minfo.energy
        self.convert = float
        self.symbol = "%"
        self.show_ratio = bool(self.wcfg["show_fuel_ratio"])
        self.show_bias = bool(self.wcfg["show_fuel_bias"])
        extra = [Stat("ratio", "Ratio", "8.888")] if self.show_ratio else []
        if self.show_bias:
            extra.append(Stat("bias", "Bias", "+8.88"))
        self.setup_panel(extra)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        if not minfo.energy.available:  # car without virtual energy: no values, no low energy warning
            missing = Value(DASH, theme.text_faint)
            self.refresh(((missing,) * len(self.keys), DASH, (DASH, 0.0), False, None))
            return
        extra = []
        if self.show_ratio:
            extra.append(Value(f"{minfo.hybrid.fuelEnergyRatio:.{decimals(self.wcfg, 'fuel_ratio')}f}", theme.text_dim))
        if self.show_bias:
            bias = minfo.hybrid.fuelEnergyBias
            extra.append(Value(signed(bias, decimals(self.wcfg, "fuel_bias")),
                               theme.negative if bias < 0 else theme.text_dim))
        self.read_panel(extra)
