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
Fuel Widget
"""

from typing import TYPE_CHECKING

from .. import units
from ..module_info import minfo
from ._consumption import ConsumptionBars

if TYPE_CHECKING:
    from ..template.widget_config_types import FuelConfig


class Realtime(ConsumptionBars):
    """Draw widget"""

    wcfg: "FuelConfig"
    refill = "refueling"
    amount = "fuel"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        # Config units
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.set_consumption_bars()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.update_consumption(minfo.fuel, self.unit_fuel)
