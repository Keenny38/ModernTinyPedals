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
Pit stop estimate Widget, modern design

Pit lane pass time, pit timer, stop duration (lengthy stop warning), minimum total time,
refill set & needed, laps & minutes the refill lasts, pit occupancy & requests.
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
        "font_size", "additional_pitstop_time", "lengthy_stop_duration_threshold",
        "decimal_places_pass_duration", "decimal_places_pit_timer", "decimal_places_stop_duration",
        "decimal_places_minimum_total_duration", "show_relative_refilling", "decimal_places_actual_relative_refill",
        "decimal_places_total_relative_refill", "show_estimated_laps_and_minutes", "decimal_places_estimated_laps",
        "decimal_places_estimated_minutes", "show_pit_occupancy",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        stats = [
            Stat("pass_duration", "Pass", "888.88"),
            Stat("pit_timer", "Timer", "888.88"),
            Stat("stop_duration", "Stop", "888.88", "strong"),
            Stat("minimum_total_duration", "Total", "888.88", "strong"),
        ]
        if wcfg["show_relative_refilling"]:
            stats += [Stat("actual_relative_refill", "Refill", "+888.88"), Stat("total_relative_refill", "Needed", "+888.88")]
        if wcfg["show_estimated_laps_and_minutes"]:
            stats += [Stat("estimated_laps", "Laps", "888.88"), Stat("estimated_minutes", "Minutes", "888.88")]
        if wcfg["show_pit_occupancy"]:
            stats += [Stat("in_pit", "In pit", "88/88"), Stat("requests", "Requests", "88/88")]
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, columns=4)
        self.set_size(width, height)
        self.minimum_total = 0.0

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def number(self, key: str, value: float, sign: str = "") -> str:
        """Value with decimal places option"""
        return f"{value:{sign}.{max(int(self.wcfg[f'decimal_places_{key}']), 0)}f}"

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        stop_time = api.read.vehicle.pit_stop_time()
        abs_refill = api.read.vehicle.absolute_refill()
        pass_time = minfo.mapping.pitPassTime
        pit_timer = minfo.vehicles.dataSet[minfo.vehicles.playerIndex].pitTimer.elapsed
        lengthy = stop_time >= self.wcfg["lengthy_stop_duration_threshold"]
        if not api.read.vehicle.in_pits() or self.minimum_total < pass_time:
            if stop_time > 0:
                self.minimum_total = stop_time + pass_time + self.wcfg["additional_pitstop_time"]
            else:
                self.minimum_total = pass_time
        energy = minfo.energy.available
        values = []
        for key in self.keys:
            if key == "pass_duration":
                values.append(Value(self.number(key, pass_time), theme.text_dim))
            elif key == "pit_timer":
                values.append(Value(self.number(key, pit_timer), theme.accent if pit_timer > 0 else theme.text_dim))
            elif key == "stop_duration":
                values.append(Value(self.number(key, stop_time), theme.warning if lengthy else None,
                                    theme.tint(theme.warning, 50) if lengthy else None))
            elif key == "minimum_total_duration":
                values.append(Value(self.number(key, self.minimum_total)))
            elif key == "actual_relative_refill":
                if energy:
                    actual = abs_refill - minfo.energy.amountCurrent
                else:
                    actual = self.unit_fuel(abs_refill - minfo.fuel.amountCurrent)
                values.append(Value(self.number(key, max(actual, 0), "+")))
            elif key == "total_relative_refill":
                if energy:
                    total = calc.sym_max(minfo.energy.neededRelative, 9999)
                else:
                    total = calc.sym_max(self.unit_fuel(minfo.fuel.neededRelative), 9999)
                values.append(Value(self.number(key, total, "+"), theme.accent))
            elif key in ("estimated_laps", "estimated_minutes"):
                consumption = (minfo.energy if energy else minfo.fuel).estimatedValidConsumption
                laps = calc.end_stint_laps(abs_refill, consumption)
                value = laps if key == "estimated_laps" else calc.end_stint_minutes(laps, minfo.delta.lapTimePace)
                values.append(Value(self.number(key, value)))
            elif key == "in_pit":
                values.append(Value(f"{minfo.vehicles.totalStoppedPits}/{minfo.vehicles.totalInPits}", theme.text_dim))
            elif key == "requests":
                values.append(Value(f"{minfo.vehicles.totalPitRequests}/{minfo.vehicles.totalOutPits}", theme.text_dim))
        self.refresh(tuple(values))
