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
Virtual energy Widget
"""

from typing import TYPE_CHECKING

from ..module_info import minfo
from ._consumption import TEXT_DEFAULT, ConsumptionBars

if TYPE_CHECKING:
    from ..template.widget_config_types import VirtualEnergyConfig


class Realtime(ConsumptionBars):
    """Draw widget"""

    wcfg: "VirtualEnergyConfig"
    refill = "refilling"
    amount = "energy"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        # Fuel ratio & fuel bias cells
        self.set_consumption_bars(((("fuel_ratio", "show_fuel_ratio"), ("fuel_bias", "show_fuel_bias")),))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        if not minfo.energy.available:  # car without virtual energy: no values
            self.clear_cells()
            return
        self.update_consumption(minfo.energy, float)
        self.update_cell("fuel_ratio", minfo.hybrid.fuelEnergyRatio)
        self.update_cell("fuel_bias", minfo.hybrid.fuelEnergyBias, None, "+")

    def clear_cells(self):
        """No value in cells, no low energy warning, empty level bar (drawn again once)"""
        for name, target in self.cells.items():
            if target.last is not None:
                target.last = None
                target.text = TEXT_DEFAULT
                if name == "remaining":
                    target.bg = self.bar_style_curr[0]
                elif name == self.refill:
                    target.bg = self.bar_style_need[0]
                target.update()
        if self.shown.level and self.bar_level.last is not None:
            self.bar_level.last = None
            self.bar_level.update_input(0.0, 0.0, 0.0)
