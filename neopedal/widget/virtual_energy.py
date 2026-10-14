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
from ._consumption import ConsumptionBars
from ._painter import RawText

if TYPE_CHECKING:
    from ..template.widget_config_types import VirtualEnergyConfig


class Realtime(ConsumptionBars):
    """Draw widget"""

    wcfg: "VirtualEnergyConfig"
    refill = "refilling"
    amount = "energy"
    bar_ratio: RawText
    bar_bias: RawText

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        self.show_ratio = self.wcfg["show_fuel_ratio_and_fuel_bias"]
        # Fuel ratio & fuel bias cells
        extra_cells = (("bar_ratio", "fuel_ratio", False, 5), ("bar_bias", "fuel_bias", True, 5))
        self.set_consumption_bars(extra_cells if self.show_ratio else ())

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.update_consumption(minfo.energy, float)

        if self.show_ratio:
            self.update_value(self.bar_ratio, minfo.hybrid.fuelEnergyRatio)
            self.update_value(self.bar_bias, minfo.hybrid.fuelEnergyBias, None, "+")
