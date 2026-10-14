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
Stint history Widget
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from .. import calculation as calc
from ..module_info import StintData, StintDataSet, minfo
from ._data import cut_number, used_amount
from ._history import HistoryTable

if TYPE_CHECKING:
    from ..template.widget_config_types import StintHistoryConfig


class Realtime(HistoryTable):
    """Draw widget"""

    wcfg: StintHistoryConfig

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        self.stint_slot = max(self.wcfg["stint_history_count"], 1)
        self.set_history_layout(self.stint_slot)

        # Laps
        if self.wcfg["show_laps"]:
            self.bars_laps = self.set_history_column("laps", "last_stint_laps", "---", 3)

        # Time
        if self.wcfg["show_time"]:
            self.bars_time = self.set_history_column("time", "last_stint_time", "--:--", 5)

        # Fuel
        self.set_fuel_column("last_stint_fuel")

        # Tyre compound
        if self.wcfg["show_tyre"]:
            self.bars_cmpd = self.set_history_column("tyre", "last_stint_tyre", "----", 4)

        # Tyre wear
        self.set_wear_column("last_stint_wear")

        # Stint delta
        self.set_delta_column("last_stint_delta")

        # Stint consistency
        if self.wcfg["show_consistency"]:
            if self.wcfg["show_consistency_sign"]:
                self.sign_consist = "%"
            else:
                self.sign_consist = ""
            decimals_consist = max(self.wcfg["decimal_places_consistency"], 1)
            self.width_consist = 3 + decimals_consist
            self.bars_consist = self.set_history_column(
                "consistency", "last_stint_consistency", f"--.{'-' * decimals_consist}{self.sign_consist}",
                self.width_consist + len(self.sign_consist))

        # Last data
        self.last_data_version = -1
        self.empty_data = StintData()
        self.update_stint_history(())

    def timerEvent(self, event):
        """Update when vehicle on track"""
        energy_type = self.wcfg["show_virtual_energy_if_available"] and minfo.energy.available
        stint_data = minfo.history.stintDataCurrent

        # Current stint data
        if self.wcfg["show_laps"]:
            self.update_laps(self.bars_laps[0], stint_data.totalLaps)
        if self.wcfg["show_time"]:
            self.update_time(self.bars_time[0], stint_data.totalTime)
        if self.wcfg["show_fuel"]:
            fuel, sign_fuel = used_amount(
                energy_type, stint_data.totalEnergy, stint_data.totalFuel, self.unit_fuel, self.sign_fuel)
            if self.wcfg["show_caption"]:
                self.update_fuel_caption(self.cap_fuel, energy_type)
            self.update_fuel(self.bars_fuel[0], max(fuel, 0), sign_fuel)
        if self.wcfg["show_tyre"]:
            self.update_cmpd(self.bars_cmpd[0], stint_data.tyreCompound)
        if self.wcfg["show_wear"]:
            self.update_wear(self.bars_wear[0], max(stint_data.totalTyreWear, 0))
        if self.wcfg["show_delta"]:
            self.update_delta(self.bars_delta[0], stint_data.lapTimeDelta)
        if self.wcfg["show_consistency"]:
            self.update_consist(self.bars_consist[0], stint_data.lapTimeConsistency)

        # History stint data
        if self.last_data_version != minfo.history.stintDataVersion:
            self.last_data_version = minfo.history.stintDataVersion
            self.update_stint_history(minfo.history.stintDataSet)

    # GUI update methods
    def update_laps(self, target, data):
        """Laps data"""
        if target.last != data:
            target.last = data
            if data < 0:
                data = 0
            target.text = f"{data:03.0f}"
            target.update()

    def update_time(self, target, data):
        """Time data"""
        if target.last != data:
            target.last = data
            if data < 0:
                data = 0
            target.text = calc.sec2stinttime(data)
            target.update()

    def update_cmpd(self, target, data):
        """Compound data"""
        if target.last != data:
            target.last = data
            target.text = data
            target.update()

    def update_delta(self, target, data):
        """Delta data"""
        if target.last != data:
            target.last = data
            target.text = cut_number(data, self.width_delta, "+")
            target.update()

    def update_consist(self, target, data):
        """Consistency data"""
        if target.last != data:
            target.last = data
            target.text = f"{cut_number(data, self.width_consist)}{self.sign_consist}"
            target.update()

    def update_stint_history(self, dataset: Sequence[StintDataSet]):
        """Stint history data"""
        show_energy = self.wcfg["show_virtual_energy_if_available"]
        data: StintData | StintDataSet
        for index in range(self.stint_slot):
            if index < len(dataset):
                data = dataset[index]
                hidden = False
            else:
                data = self.empty_data
                hidden = not self.wcfg["show_empty_history"]
            index += 1

            if self.wcfg["show_laps"]:
                self.update_laps(self.bars_laps[index], data.totalLaps)
                self.bars_laps[index].setHidden(hidden)

            if self.wcfg["show_time"]:
                self.update_time(self.bars_time[index], data.totalTime)
                self.bars_time[index].setHidden(hidden)

            if self.wcfg["show_fuel"]:
                fuel, sign_fuel = used_amount(
                    show_energy and bool(data.totalEnergy), data.totalEnergy, data.totalFuel,
                    self.unit_fuel, self.sign_fuel)
                self.update_fuel(self.bars_fuel[index], max(fuel, 0), sign_fuel)
                self.bars_fuel[index].setHidden(hidden)

            if self.wcfg["show_tyre"]:
                self.update_cmpd(self.bars_cmpd[index], data.tyreCompound)
                self.bars_cmpd[index].setHidden(hidden)

            if self.wcfg["show_wear"]:
                self.update_wear(self.bars_wear[index], max(data.totalTyreWear, 0))
                self.bars_wear[index].setHidden(hidden)

            if self.wcfg["show_delta"]:
                self.update_delta(self.bars_delta[index], data.lapTimeDelta)
                self.bars_delta[index].setHidden(hidden)

            if self.wcfg["show_consistency"]:
                self.update_consist(self.bars_consist[index], data.lapTimeConsistency)
                self.bars_consist[index].setHidden(hidden)
