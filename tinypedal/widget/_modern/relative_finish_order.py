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
Relative finish order Widget, modern design

Grid of predictions, one column per pit stop time: leader & player final lap progress
(near start of lap in green, near finish line in orange), refill needed (and with extra laps).
"""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_common import ENERGY_TYPE_ID, MAX_SECONDS, RACELENGTH_TYPE_ID
from ...module_info import minfo
from .base import CENTER, DASH, ModernOverlay
from .draw import panel, rounded

LABEL_ROWS = (0, 3)  # pit time rows (small labels)


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "bar_width", "show_absolute_refilling", "near_start_range", "near_finish_range",
        "decimal_places_laps", "decimal_places_refill", "show_extra_refilling", "number_of_extra_laps",
        "number_of_prediction", *(f"prediction_{index}_{who}_pit_time" for index in range(1, 11) for who in ("leader", "player")),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.char_width = max(int(wcfg["bar_width"]), 3)
        self.range_start = max(wcfg["near_start_range"], 0)
        self.range_finish = max(wcfg["near_finish_range"], 0)
        self.total_slot = min(max(int(wcfg["number_of_prediction"]), 0), 10) + 3
        self.leader_pit_times = list(self.pit_time_set("leader"))
        self.player_pit_times = list(self.pit_time_set("player"))
        self.decimals_laps = max(int(wcfg["decimal_places_laps"]), 0)
        self.decimals_refill = max(int(wcfg["decimal_places_refill"]), 0)
        self.extra_laps = max(int(wcfg["number_of_extra_laps"]), 1)
        self.refill_sign = "" if wcfg["show_absolute_refilling"] else "+"
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.rows = 6 if wcfg["show_extra_refilling"] else 5

        pad = unit * 0.3
        gap = unit * 0.14
        cell_w = max(self.text_width("value", "8" * self.char_width), self.text_width("label", "LAPS")) + unit * 0.6
        value_h = unit * 1.45
        label_h = unit * 1.0
        heights = [label_h if row in LABEL_ROWS else value_h for row in range(self.rows)]
        width = pad * 2 + cell_w * self.total_slot + gap * (self.total_slot - 1)
        reversed_layout = wcfg["layout"] != 0
        self.cells = []  # [row][slot] rect
        top = pad
        for height in heights:
            row = []
            for slot in range(self.total_slot):
                column = self.total_slot - 1 - slot if reversed_layout else slot
                row.append(QRectF(pad + column * (cell_w + gap), top, cell_w, height))
            self.cells.append(row)
            top += height + gap
        self.set_size(width, top - gap + pad)

    def pit_time_set(self, who: str):
        """Pit time of each prediction slot (first two & last reserved)"""
        yield 0
        yield 0
        for index in range(self.total_slot - 3):
            yield max(self.wcfg[f"prediction_{index + 1}_{who}_pit_time"], 0)
        yield 0

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for row_index, row in enumerate(self.cells):
            if row_index in LABEL_ROWS:
                continue
            for slot, rect in enumerate(row):
                fill = theme.surface_raised if slot == 0 else theme.tint(theme.surface_alt, 170)
                rounded(painter, rect, self.radius(0.25), fill)
        # Fixed labels
        self.draw_text(painter, self.cells[1][0], "LDR", "label", theme.text_dim, CENTER)
        if self.rows > 5:
            self.draw_text(painter, self.cells[5][0], f"EX+{self.extra_laps}", "label", theme.text_dim, CENTER)
        self.draw_text(painter, self.cells[3][0], "DIFF", "label", theme.text_muted, CENTER)

    def paint(self, painter: QPainter):
        theme = self.theme
        race_type, energy_type, lap_diff, leader, player, refills, extras, _ = self.state
        lap_colors = (theme.text, theme.positive, theme.orange)  # normal, near start, near finish
        cells = self.cells
        self.draw_text(painter, cells[0][0], race_type, "label", theme.text_muted, CENTER)
        self.draw_text(painter, cells[4][0], energy_type, "label", theme.text_dim, CENTER)
        self.draw_text(painter, cells[2][0], lap_diff, "small", theme.text_dim, CENTER)
        for slot in range(1, self.total_slot):
            self.draw_text(painter, cells[0][slot], f"{self.leader_pit_times[slot]:.0f}s", "small", theme.text_muted, CENTER)
            self.draw_text(painter, cells[3][slot], f"{self.player_pit_times[slot]:.0f}s", "small", theme.text_muted, CENTER)
            text, highlight = leader[slot]
            self.draw_text(painter, cells[1][slot], text, "value", lap_colors[highlight], CENTER)
            text, highlight = player[slot]
            self.draw_text(painter, cells[2][slot], text, "strong", lap_colors[highlight] if highlight else theme.accent, CENTER)
            self.draw_text(painter, cells[4][slot], refills[slot], "value", theme.text_dim, CENTER)
            if extras:
                self.draw_text(painter, cells[5][slot], extras[slot], "value", theme.text_dim, CENTER)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        pre_race = api.read.session.pre_race()
        energy_type = minfo.energy.available
        leader_index = minfo.vehicles.leaderIndex
        player_index = minfo.vehicles.playerIndex
        leader_lap_into = api.read.lap.progress(leader_index)
        player_lap_into = api.read.lap.progress()
        leader_pace = minfo.vehicles.dataSet[leader_index].lapTimeHistory.average
        player_pace = minfo.delta.lapTimePace
        leader_valid = 0 < leader_pace < MAX_SECONDS
        player_valid = 0 < player_pace < MAX_SECONDS
        finish_as_lap = api.read.session.finish_type(minfo.vehicles.finishAsLap) > 0

        if finish_as_lap and leader_valid and player_valid:
            laps_total = api.read.lap.maximum()
            leader_laps_left = laps_total - api.read.lap.completed_laps(leader_index) - leader_lap_into
            player_laps_left = laps_total - api.read.lap.completed_laps() - player_lap_into
            time_left = min(leader_pace, player_pace) * leader_laps_left
            laps_diff = player_laps_left - (time_left / player_pace)
        else:
            time_left = api.read.session.remaining() - minfo.vehicles.finishTimeOffset
            laps_diff = 0

        self.leader_pit_times[-1] = minfo.vehicles.dataSet[leader_index].pitTimer.elapsed
        self.player_pit_times[-1] = minfo.vehicles.dataSet[player_index].pitTimer.elapsed
        consumption = minfo.energy if energy_type else minfo.fuel
        fuel_in_tank = 0 if self.wcfg["show_absolute_refilling"] else consumption.amountCurrent
        fuel_consumption = consumption.estimatedValidConsumption

        if MAX_SECONDS > player_pace > leader_pace > 0:
            lap_diff_text = self.laps_text((player_pace - leader_pace) / player_pace)
        else:
            lap_diff_text = DASH

        leader = [(DASH, 0)]
        player = [(DASH, 0)]
        refills = [DASH]
        extras = [DASH] if self.rows > 5 else []
        relative_lap_offset = 0.0
        for index in range(1, self.total_slot):
            # Player
            if not player_valid:
                lap_final, player_hi, full_laps_left = -MAX_SECONDS, 0, 0.0
            elif finish_as_lap and index > 1:
                lap_final = calc.lap_progress_offset(player_pace, relative_lap_offset, self.player_pit_times[index])
                player_hi = self.highlight(player_pace, lap_final % 1)
                full_laps_left = 0.0
            else:
                lap_into_offset = calc.lap_progress_offset(player_pace, player_lap_into, self.player_pit_times[index])
                lap_remaining = calc.end_timer_laps_remain(lap_into_offset, player_pace, time_left)
                lap_final = lap_remaining % 1
                player_hi = self.highlight(player_pace, lap_final)
                full_laps_left = calc.time_type_laps_remain(ceil(lap_remaining), player_lap_into)
            player.append((self.laps_text(lap_final), player_hi))
            if index == 1:
                relative_lap_offset = lap_final
            # Refill
            if (finish_as_lap and index != 1) or pre_race or not leader_valid or not player_valid:
                refill = -MAX_SECONDS
            else:
                refill = calc.total_fuel_needed(full_laps_left, fuel_consumption, fuel_in_tank)
            refills.append(self.refill_text(refill, energy_type))
            if self.rows > 5:
                if refill == -MAX_SECONDS:
                    extra = -MAX_SECONDS
                else:
                    extra = calc.total_fuel_needed(full_laps_left + self.extra_laps, fuel_consumption, fuel_in_tank)
                extras.append(self.refill_text(extra, energy_type))
            # Leader
            if not leader_valid or player_index == leader_index:
                leader_final, leader_hi = -MAX_SECONDS, 0
            elif finish_as_lap:
                leader_final = calc.lap_progress_offset(leader_pace, ceil(laps_diff), self.leader_pit_times[index])
                leader_hi = self.highlight(leader_pace, leader_final % 1)
            else:
                leader_into_offset = calc.lap_progress_offset(leader_pace, leader_lap_into, self.leader_pit_times[index])
                leader_remaining = calc.end_timer_laps_remain(leader_into_offset, leader_pace, time_left)
                leader_final = leader_remaining % 1
                leader_hi = self.highlight(leader_pace, leader_final)
            leader.append((self.laps_text(leader_final), leader_hi))
        live_pit_times = (self.leader_pit_times[-1] // 1, self.player_pit_times[-1] // 1)  # last column
        self.refresh((
            RACELENGTH_TYPE_ID[finish_as_lap], ENERGY_TYPE_ID[energy_type > 0], lap_diff_text,
            tuple(leader), tuple(player), tuple(refills), tuple(extras), live_pit_times,
        ))

    def laps_text(self, value: float) -> str:
        """Final lap progress"""
        if value <= -MAX_SECONDS:
            return DASH
        return f"{value:.{self.decimals_laps}f}"[:self.char_width]

    def refill_text(self, value: float, energy_type: bool) -> str:
        """Refill needed"""
        if value <= -MAX_SECONDS:
            return DASH
        if not energy_type:
            value = self.unit_fuel(value)
        return f"{value:{self.refill_sign}.{self.decimals_refill}f}"[:self.char_width].strip(".")

    def highlight(self, pace: float, lap_final: float) -> int:
        """1 if final lap ends near start of lap, 2 near finish line, else 0"""
        if pace > 0:
            limit = pace / 3
            if lap_final < min(self.range_start, limit) / pace:
                return 1
            if lap_final > 1 - min(self.range_finish, limit) / pace:
                return 2
        return 0
