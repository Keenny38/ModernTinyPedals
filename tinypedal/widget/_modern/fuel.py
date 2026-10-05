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
Fuel Widget, modern design
"""

from __future__ import annotations

from ... import units
from ...module_info import minfo
from .consumption import COMMON_OPTIONS, ConsumptionPanel, Names


class Realtime(ConsumptionPanel):
    """Draw widget"""

    names = Names(
        title="Fuel",
        refill="Refuel",
        absolute="show_absolute_refueling",
        refill_decimals="decimal_places_refueling",
        warning_flash="show_low_fuel_warning_flash",
        low_threshold="low_fuel_lap_threshold",
        level_bar="show_fuel_level_bar",
        start_mark="show_starting_fuel_level_mark",
        refill_mark="show_refueling_level_mark",
    )
    options = (*COMMON_OPTIONS, *names[2:])

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        fuel_unit = self.cfg.units["fuel_unit"]
        self.source = minfo.fuel
        self.convert = units.set_unit_fuel(fuel_unit)
        self.symbol = units.set_symbol_fuel(fuel_unit)
        self.setup_panel([])

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.read_panel([])
