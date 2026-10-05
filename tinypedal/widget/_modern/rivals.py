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
Rivals Widget, modern design

Car ahead and car behind in player class, with interval to player.
"""

from __future__ import annotations

from ...module_info import minfo
from .drivers import DRIVER_OPTIONS, Context, DriverTable
from .rows import laptime_text
from .table import DELTAS, RIGHT, TEXT, Cell, Column


class Realtime(DriverTable):
    """Draw widget"""

    COLUMNS = (
        "position", "class", "position_change", "driver_name", "vehicle_name", "tyre_compound",
        "pit_status", "pitstop_count", "laptime", "best_laptime", "delta_laptime", "energy_remaining",
        "vehicle_integrity", "incidents", "stint_laps", "time_interval",
    )
    options = (
        *DRIVER_OPTIONS,
        "column_delta_laptime", "number_of_delta_laptime",
        "column_time_interval", "decimal_places_time_interval",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.int_decimals = max(int(self.wcfg["decimal_places_time_interval"]), 0)
        self.delta_count = min(max(int(self.wcfg["number_of_delta_laptime"]), 2), 5)
        self.setup_table()
        self.set_size(self.table.width, self.table.height(2))

    def extra_column(self, key: str) -> Column | None:
        if key == "time_interval":
            sample = "+88." + "8" * self.int_decimals if self.int_decimals else "+88"
            return Column(key, self.text_width("strong", sample), RIGHT)
        if key == "delta_laptime":
            return Column(key, (self.text_width("small", "8.8") + self.unit * 0.3) * self.delta_count, RIGHT)
        return None

    def extra_cell(self, key: str, veh, ctx: Context, extra: dict) -> Cell:
        theme = self.theme
        player = ctx.player
        if key == "time_interval":
            if player is None:
                return Cell()
            ahead = veh.positionOverall < player.positionOverall
            gap = player.gapBehindNextInClass if ahead else veh.gapBehindNextInClass
            sign = "-" if ahead else "+"
            text = f"{sign}{gap}L" if isinstance(gap, int) else f"{sign}{gap:.{self.int_decimals}f}"
            return Cell(TEXT, text, "strong", theme.positive if ahead else theme.warning)
        if key == "delta_laptime":
            if player is None:
                return Cell(DELTAS)
            return Cell(DELTAS, extra=tuple(veh.lapTimeHistory.delta(player.lapTimeHistory, self.delta_count)))
        return Cell()

    def laptime_cell(self, veh, ctx: Context) -> Cell:
        """Last lap in race (or if best lap column shown), else best lap"""
        if ctx.in_race or self.wcfg["column_best_laptime"]:
            return super().laptime_cell(veh, ctx)
        return Cell(TEXT, laptime_text(veh.bestLapTime), "dim", self.theme.text_dim)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        ctx = self.context()
        data_set = minfo.vehicles.dataSet
        rows = []
        if ctx.player is not None:
            for index in (ctx.player.classAheadIndex, ctx.player.classBehindIndex):
                rows.append(self.driver_row(data_set[index], ctx) if 0 <= index < len(data_set) else None)
        self.refresh(tuple(rows))
