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
Standings Widget, modern design

Running order, split by class (space between class groups) or combined. Widget height
follows the number of cars shown.
"""

from __future__ import annotations

from math import ceil

from ...i18n import tr_overlay
from ...module_info import minfo
from .drivers import DRIVER_OPTIONS, Context, DriverTable, gap_text
from .rows import DASH
from .table import DELTAS, RIGHT, SEPARATOR, TEXT, Cell, Column


class Realtime(DriverTable):
    """Draw widget"""

    COLUMNS = (
        "position", "class", "position_change", "driver_name", "vehicle_name", "tyre_compound",
        "pit_status", "pitstop_count", "laptime", "best_laptime", "delta_laptime", "energy_remaining",
        "vehicle_integrity", "incidents", "stint_laps", "time_interval", "time_gap",
    )
    options = (
        *DRIVER_OPTIONS,
        "enable_multi_class_split_mode", "enable_single_class_exclusive_mode", "minimum_top_vehicles",
        "maximum_vehicles_exclusive_mode", "maximum_vehicles_combined_mode", "maximum_vehicles_split_mode",
        "maximum_vehicles_per_split_player", "maximum_vehicles_per_split_others",
        "column_delta_laptime", "number_of_delta_laptime",
        "column_time_interval", "show_time_interval_from_same_class", "decimal_places_time_interval",
        "column_time_gap", "show_time_gap_from_same_class", "decimal_places_time_gap",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.gap_decimals = max(int(wcfg["decimal_places_time_gap"]), 0)
        self.int_decimals = max(int(wcfg["decimal_places_time_interval"]), 0)
        split = wcfg["enable_multi_class_split_mode"]
        self.class_gap = split and wcfg["show_time_gap_from_same_class"]
        self.class_interval = split and wcfg["show_time_interval_from_same_class"]
        self.delta_count = min(max(int(wcfg["number_of_delta_laptime"]), 2), 5)
        if wcfg["enable_single_class_exclusive_mode"]:
            max_vehicles = wcfg["maximum_vehicles_exclusive_mode"]
        elif split:
            max_vehicles = wcfg["maximum_vehicles_split_mode"]
        else:
            max_vehicles = wcfg["maximum_vehicles_combined_mode"]
        self.max_rows = min(max(int(max_vehicles), 5), 126)
        self.setup_table()
        self.set_size(self.table.width, self.table.height(1))

    def extra_column(self, key: str) -> Column | None:
        if key == "time_gap":
            sample = "888." + "8" * self.gap_decimals if self.gap_decimals else "888"
            return Column(key, max(self.text_width("strong", sample), self.text_width("label", tr_overlay("Leader"))), RIGHT)
        if key == "time_interval":
            sample = "88." + "8" * self.int_decimals if self.int_decimals else "88"
            return Column(key, self.text_width("value", sample), RIGHT)
        if key == "delta_laptime":
            return Column(key, (self.text_width("small", "8.8") + self.unit * 0.3) * self.delta_count, RIGHT)
        return None

    def extra_cell(self, key: str, veh, ctx: Context, extra: dict) -> Cell:
        theme = self.theme
        if key == "time_gap":
            return self.gap_cell(veh, ctx)
        if key == "time_interval":
            if self.class_interval:
                position, gap = veh.positionInClass, veh.gapBehindNextInClass
            else:
                position, gap = veh.positionOverall, veh.gapBehindNext
            if position == 1:
                return Cell(TEXT, DASH, "value", theme.text_faint)
            return Cell(TEXT, gap_text(gap, self.int_decimals), "value", theme.text_dim)
        if key == "delta_laptime":
            if ctx.player is None or veh.isPlayer:
                return Cell(DELTAS)
            return Cell(DELTAS, extra=tuple(veh.lapTimeHistory.delta(ctx.player.lapTimeHistory, self.delta_count)))
        return Cell()

    def laptime_cell(self, veh, ctx: Context) -> Cell:
        """Last lap in race (or if best lap column shown), else best lap"""
        if ctx.in_race or self.wcfg["column_best_laptime"]:
            return super().laptime_cell(veh, ctx)
        from .rows import laptime_text

        return Cell(TEXT, laptime_text(veh.bestLapTime), "dim", self.theme.text_dim)

    def gap_cell(self, veh, ctx: Context) -> Cell:
        """Gap to leader (race), or to leader best lap (other sessions)"""
        theme = self.theme
        leader_cell = Cell(TEXT, tr_overlay("Leader"), "label", theme.accent)
        if ctx.in_race:
            if self.class_gap:
                position, gap = veh.positionInClass, veh.gapBehindLeaderInClass
            else:
                position, gap = veh.positionOverall, veh.gapBehindLeader
            if position == 1:
                return leader_cell
            return Cell(TEXT, gap_text(gap, self.gap_decimals), "strong", theme.text)
        best = veh.bestLapTime
        leader_best = veh.classBestLapTime if self.class_gap else minfo.vehicles.leaderBestLapTime
        gap = best - leader_best
        if gap == 0 and best > 0:
            return leader_cell
        if gap < 0 or best < 1:
            return Cell(TEXT, DASH, "strong", theme.text_faint)
        return Cell(TEXT, f"+{gap:.{self.gap_decimals}f}", "strong", theme.text)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        data_set = minfo.vehicles.dataSet
        ctx = self.context()
        rows: list = []
        for index in minfo.relative.standings[:self.max_rows]:
            if index == -1:
                if rows and rows[-1] is not SEPARATOR:
                    rows.append(SEPARATOR)
            elif 0 <= index < len(data_set):
                rows.append(self.driver_row(data_set[index], ctx))
        while rows and rows[-1] is SEPARATOR:
            rows.pop()
        rows_tuple = tuple(rows)
        if rows_tuple != self.state:
            height = self.table.content_height(rows_tuple) if rows_tuple else self.table.height(1)
            if ceil(height) != self.height():
                self.set_size(self.table.width, height)
        self.refresh(rows_tuple)
