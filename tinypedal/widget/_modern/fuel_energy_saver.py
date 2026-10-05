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
Fuel energy saver Widget, modern design

One column per stint length target (current laps highlighted, then more laps): total laps,
consumption per lap to reach it, delta to current consumption (green if already saving enough).
Optional columns on the left: rate of consumption, pit entry bias, last lap consumption.
"""

from __future__ import annotations

from math import floor

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_common import ENERGY_TYPE_ID, MAX_SECONDS
from ...i18n import tr_overlay
from ...module_info import minfo
from .base import CENTER, DASH, ModernOverlay
from .draw import panel, rounded


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "bar_width", "minimum_reserve", "number_of_more_laps", "number_of_less_laps",
        "show_rate_of_consumption", "enable_pit_entry_bias", "remaining_pitstop_threshold",
        "decimal_places_consumption", "decimal_places_delta",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.char_width = max(int(wcfg["bar_width"]), 4)
        self.pitin_bias = bool(wcfg["enable_pit_entry_bias"])
        self.consumption_rate = bool(wcfg["show_rate_of_consumption"])
        self.column_rate = 0
        self.column_bias = int(self.consumption_rate)
        self.column_last = int(self.consumption_rate) + int(self.pitin_bias)
        self.center_slot = min(max(int(wcfg["number_of_less_laps"]), 0), 5) + 1 + self.column_last
        self.total_slot = min(max(int(wcfg["number_of_more_laps"]), 1), 10) + 1 + self.center_slot
        self.dec_use = max(int(wcfg["decimal_places_consumption"]), 0)
        self.dec_delta = max(int(wcfg["decimal_places_delta"]), 0)
        self.min_reserve = max(wcfg["minimum_reserve"], 0)
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])

        pad = unit * 0.3
        gap = unit * 0.14
        cell_w = max(
            self.text_width("value", "8" * self.char_width), self.text_width("small", "88/888"),
            *(self.text_width("label", tr_overlay(text)) for text in ("RATE", "BIAS", "LAST")),  # column labels
        ) + unit * 0.6
        heights = (unit * 1.0, unit * 1.45, unit * 1.45)
        reversed_layout = wcfg["layout"] != 0
        self.cells = []
        top = pad
        for height in heights:
            row = []
            for slot in range(self.total_slot):
                column = self.total_slot - 1 - slot if reversed_layout else slot
                row.append(QRectF(pad + column * (cell_w + gap), top, cell_w, height))
            self.cells.append(row)
            top += height + gap
        self.set_size(pad * 2 + cell_w * self.total_slot + gap * (self.total_slot - 1), top - gap + pad)

        self.reset_stint = True
        self.start_laps = 0
        self.last_tyre_life = 0.0
        self.last_fuel = 0.0

    def post_update(self):
        self.reset_stint = True

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for slot in range(self.total_slot):
            column = QRectF(self.cells[0][slot].topLeft(), self.cells[2][slot].bottomRight())
            if slot == self.center_slot:
                rounded(painter, column.adjusted(-2, -2, 2, 2), self.radius(0.35), theme.highlight)
            elif slot <= self.column_last:
                rounded(painter, column, self.radius(0.3), theme.tint(theme.surface_raised, 200))
            else:
                rounded(painter, column, self.radius(0.3), theme.tint(theme.surface_alt, 170))
        if self.consumption_rate:
            self.draw_text(painter, self.cells[0][self.column_rate], tr_overlay("RATE"), "label", theme.text_muted, CENTER)
        if self.pitin_bias:
            self.draw_text(painter, self.cells[0][self.column_bias], tr_overlay("BIAS"), "label", theme.text_muted, CENTER)
        self.draw_text(painter, self.cells[0][self.column_last], tr_overlay("LAST"), "label", theme.text_muted, CENTER)

    def paint(self, painter: QPainter):
        theme = self.theme
        laps, uses, deltas = self.state
        delta_colors = (theme.positive, theme.negative, theme.text_faint)
        for slot in range(self.total_slot):
            if slot > self.column_last:
                color = theme.accent if slot == self.center_slot else theme.text_muted
                self.draw_text(painter, self.cells[0][slot], laps[slot], "small", color, CENTER)
            self.draw_text(painter, self.cells[1][slot], uses[slot], "value", theme.text, CENTER)
            text, color_index = deltas[slot]
            if slot > self.column_last:
                self.draw_text(painter, self.cells[2][slot], text, "dim", delta_colors[color_index], CENTER)
            else:
                self.draw_text(painter, self.cells[2][slot], text, "small", theme.text_dim, CENTER)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        in_pits = api.read.vehicle.in_pits()
        tyre_life = sum(api.read.tyre.wear())
        lap_num = api.read.lap.number()
        energy_type = minfo.energy.available
        data = minfo.energy if energy_type else minfo.fuel
        fuel_curr = data.amountCurrent
        fuel_est = data.estimatedConsumption
        pit_bias = 0.0
        if self.pitin_bias:
            pitin_pos = minfo.mapping.pitEntryPosition
            track_length = api.read.lap.track_length()
            if 0 < pitin_pos < track_length and data.estimatedNumPitStopsEnd > self.wcfg["remaining_pitstop_threshold"]:
                pit_bias = 1 - pitin_pos / track_length
        # Stint reset: tyres changed, refueled or back in garage
        if not in_pits:
            self.last_fuel = fuel_curr
            self.last_tyre_life = tyre_life
        elif self.last_tyre_life < tyre_life or self.last_fuel < fuel_curr or api.read.vehicle.in_garage():
            self.reset_stint = True
        if self.reset_stint:
            self.reset_stint = False
            self.start_laps = lap_num
        laps_done = max(lap_num - self.start_laps, 0)
        total_remaining = max(fuel_curr + data.amountUsedCurrent - self.min_reserve + pit_bias * fuel_est, 0)
        est_runlaps = floor(round(calc.end_stint_laps(total_remaining, fuel_est), 1)) - self.center_slot

        laps = [""] * self.total_slot
        uses = [DASH] * self.total_slot
        deltas = [(DASH, 2)] * self.total_slot
        if self.consumption_rate:
            uses[self.column_rate] = self.use_text(data.rateOfConsumption, energy_type)
            deltas[self.column_rate] = (f"{api.read.vehicle.speed():.0f}m"[:self.char_width], 2)
        if self.pitin_bias:
            uses[self.column_bias] = self.use_text(pit_bias * fuel_est, energy_type)
            deltas[self.column_bias] = (f"{pit_bias:.1%}"[:self.char_width], 2)
        uses[self.column_last] = self.use_text(data.lastLapConsumption, energy_type)
        deltas[self.column_last] = (ENERGY_TYPE_ID[energy_type > 0], 2)
        for index in range(1 + self.column_last, self.total_slot):
            target_laps = est_runlaps + index
            if index == self.center_slot:
                laps[index] = f"{laps_done}/{laps_done + target_laps:d}"
            else:
                laps[index] = f"{laps_done + target_laps:d}"
            if target_laps > 0 < fuel_est:
                target_use = total_remaining / target_laps
                uses[index] = self.use_text(target_use, energy_type)
                delta = fuel_est - target_use
                if not energy_type:
                    delta = self.unit_fuel(delta)
                deltas[index] = (f"{delta:+.{self.dec_delta}f}"[:self.char_width], int(delta >= 0))
        self.refresh((tuple(laps), tuple(uses), tuple(deltas)))

    def use_text(self, value: float, energy_type: bool) -> str:
        """Consumption text"""
        if value <= -MAX_SECONDS:
            return DASH
        if not energy_type:
            value = self.unit_fuel(value)
        return f"{value:.{self.dec_use}f}"[:self.char_width]
