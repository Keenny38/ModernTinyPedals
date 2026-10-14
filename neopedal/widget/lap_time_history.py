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
Lap time history Widget
"""

from typing import TYPE_CHECKING

from .. import calculation as calc
from ..api_control import api
from ..const_common import TEXT_NOLAPTIME
from ..module_info import ConsumptionDataSet, minfo
from ._common import delta_shown
from ._data import cut_number, lap_delta, used_amount
from ._history import HistoryTable

if TYPE_CHECKING:
    from ..template.widget_config_types import LapTimeHistoryConfig


class Realtime(HistoryTable):
    """Draw widget"""

    wcfg: "LapTimeHistoryConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        self.history_slot = min(max(self.wcfg["lap_time_history_count"], 1), 100)
        self.set_history_layout(self.history_slot)

        # Laps
        if self.wcfg["show_laps"]:
            self.bars_laps = self.set_history_column("laps", "last_laps", "---", 3)

        # Time
        if self.wcfg["show_time"]:
            self.bar_style_time = (
                (
                    self.wcfg["font_color_time"],
                    self.wcfg["background_color_time"],
                ),
                (
                    self.wcfg["font_color_last_time"],
                    self.wcfg["background_color_last_time"],
                ),
                (
                    self.wcfg["font_color_invalid_time"],
                    self.wcfg["background_color_last_time"],
                ),
            )
            self.bars_time = self.set_history_column("time", "last_time", TEXT_NOLAPTIME, 8)

        # Lap time delta
        self.set_delta_column("last_delta")

        # Fuel
        self.set_fuel_column("last_fuel")

        # Fuel ratio
        if self.wcfg["show_fuel_ratio"]:
            decimals_ratio = max(self.wcfg["decimal_places_fuel_ratio"], 1)
            self.width_ratio = 2 + decimals_ratio
            self.bars_ratio = self.set_history_column(
                "fuel_ratio", "last_fuel_ratio", f"-.{'-' * decimals_ratio}", self.width_ratio)

        # Tyre wear
        self.set_wear_column("last_wear")

        # Last data
        self.empty_data = ConsumptionDataSet()
        self.last_data_version = -1
        self.last_energy_type = None
        self.update_laps_history(())

    def timerEvent(self, event):
        """Update when vehicle on track"""
        energy_type = self.wcfg["show_virtual_energy_if_available"] and minfo.energy.available

        # Current laps data
        if self.wcfg["show_laps"]:
            self.update_laps(self.bars_laps[0], api.read.lap.number() + 1)
        if self.wcfg["show_time"]:
            self.update_time(self.bars_time[0], minfo.delta.lapTimeEstimated)
        if self.wcfg["show_delta"]:
            self.update_delta(self.bars_delta[0], minfo.delta.deltaLast if delta_shown("Last") else None)
        if self.wcfg["show_fuel"]:
            fuel, sign_fuel = used_amount(
                energy_type, minfo.energy.estimatedConsumption, minfo.fuel.estimatedConsumption,
                self.unit_fuel, self.sign_fuel)
            if self.wcfg["show_caption"]:
                self.update_fuel_caption(self.cap_fuel, energy_type)
            self.update_fuel(self.bars_fuel[0], fuel, sign_fuel)
        if self.wcfg["show_fuel_ratio"]:
            self.update_ratio(self.bars_ratio[0], minfo.hybrid.fuelEnergyRatio)
        if self.wcfg["show_wear"]:
            self.update_wear(self.bars_wear[0], calc.mean(minfo.wheels.estimatedTreadWear))

        # History laps data
        if (
            self.last_data_version != minfo.history.consumptionDataVersion
            or self.last_energy_type != energy_type
        ):
            self.last_data_version = minfo.history.consumptionDataVersion
            self.last_energy_type = energy_type
            self.update_laps_history(minfo.history.consumptionDataSet)

    # GUI update methods
    def update_laps(self, target, data):
        """Laps data"""
        if target.last != data:
            target.last = data
            target.text = f"{data:03.0f}"
            target.update()

    def update_time(self, target, data):
        """Time data"""
        if target.last != data:
            target.last = data
            target.text = calc.sec2laptime_full(data)[:8]
            target.update()

    def update_delta(self, target, data):
        """Delta data (None: no last lap to compare, or out lap)"""
        if target.last != data:
            target.last = data
            if data is None:
                target.text = "-"
            else:
                target.text = cut_number(calc.sym_max(data, 99.9), self.width_delta, "+")
            target.update()

    def update_ratio(self, target, data):
        """Fuel ratio data"""
        if target.last != data:
            target.last = data
            target.text = cut_number(data, self.width_ratio)
            target.update()

    def update_laps_history(self, dataset):
        """Laps history data"""
        show_energy = self.wcfg["show_virtual_energy_if_available"]
        for index in range(self.history_slot):
            if index < len(dataset):
                data = dataset[index]
                hidden = False
            else:
                data = self.empty_data
                hidden = not self.wcfg["show_empty_history"]
            index += 1

            if self.wcfg["show_laps"]:
                self.update_laps(self.bars_laps[index], data.lapNumber)
                self.bars_laps[index].setHidden(hidden)

            if self.wcfg["show_time"]:
                invalid = (2 - data.isValidLap) if (data.lapTimeLast > 0) else 1
                self.bars_time[index].fg = self.bar_style_time[invalid][0]
                self.bars_time[index].bg = self.bar_style_time[invalid][1]
                self.update_time(self.bars_time[index], data.lapTimeLast)
                self.bars_time[index].setHidden(hidden)

            if self.wcfg["show_delta"]:
                last_data = dataset[index] if index < len(dataset) else self.empty_data
                # No lap to compare (oldest lap, or no time set): dash, not the whole lap time
                self.update_delta(self.bars_delta[index], lap_delta(data.lapTimeLast, last_data.lapTimeLast))
                self.bars_delta[index].setHidden(hidden)

            if self.wcfg["show_fuel"]:
                fuel, sign_fuel = used_amount(
                    show_energy and bool(data.lastLapUsedEnergy), data.lastLapUsedEnergy, data.lastLapUsedFuel,
                    self.unit_fuel, self.sign_fuel)
                self.update_fuel(self.bars_fuel[index], fuel, sign_fuel)
                self.bars_fuel[index].setHidden(hidden)

            if self.wcfg["show_fuel_ratio"]:
                fuel_ratio = calc.fuel_to_energy_ratio(data.lastLapUsedFuel, data.lastLapUsedEnergy)
                self.update_ratio(self.bars_ratio[index], fuel_ratio)
                self.bars_ratio[index].setHidden(hidden)

            if self.wcfg["show_wear"]:
                self.update_wear(self.bars_wear[index], data.tyreAvgWearLast)
                self.bars_wear[index].setHidden(hidden)
