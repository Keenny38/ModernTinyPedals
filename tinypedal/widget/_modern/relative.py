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
Relative Widget, modern design

Cars around player on track: one row per car, player row highlighted, class color on row edge.
"""

from __future__ import annotations

from ...module_info import minfo
from ..relative import relative_data
from .drivers import DRIVER_OPTIONS, Context, DriverTable
from .table import RIGHT, TEXT, Cell, Column, Row


class Realtime(DriverTable):
    """Draw widget"""

    COLUMNS = (
        "position", "class", "position_change", "driver_name", "vehicle_name", "brand_logo", "tyre_compound",
        "pit_status", "pitstop_count", "laptime", "best_laptime", "average_laptime", "energy_remaining",
        "vehicle_integrity", "incidents", "stint_laps", "speed_trap", "lift_and_coast_time", "time_gap",
    )
    options = (
        *DRIVER_OPTIONS,
        "show_vehicle_in_garage",  # read by relative module
        "additional_players_front", "additional_players_behind",
        "column_time_gap", "show_time_gap_sign", "decimal_places_time_gap", "display_order_time_gap",
        "show_highlighted_nearest_time_gap", "nearest_time_gap_threshold_front", "nearest_time_gap_threshold_behind",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        base_rows = 3
        self.max_front = base_rows + min(max(int(wcfg["additional_players_front"]), 0), 60)
        self.max_behind = base_rows + min(max(int(wcfg["additional_players_behind"]), 0), 60)
        self.gap_decimals = max(int(wcfg["decimal_places_time_gap"]), 0)
        self.nearest_gap = (
            -max(wcfg["nearest_time_gap_threshold_behind"], 0),
            max(wcfg["nearest_time_gap_threshold_front"], 0),
        )
        self.setup_table()
        self.set_size(self.table.width, self.table.height(self.max_front + self.max_behind + 1))

    def extra_column(self, key: str) -> Column | None:
        if key == "time_gap":
            sample = "+888." + "8" * self.gap_decimals if self.gap_decimals else "+888"
            return Column(key, self.text_width("strong", sample), RIGHT)
        return None

    def extra_cell(self, key: str, veh, ctx: Context, extra: dict) -> Cell:
        if key == "time_gap":
            return self.gap_cell(extra["gap"], veh.isPlayer)
        return Cell()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        data_set = minfo.vehicles.dataSet
        ctx = self.context()
        rows: list[Row | None] = []
        for gap, index in relative_data(
            minfo.relative.relativeAhead, minfo.relative.relativeBehind,
            minfo.vehicles.playerIndex, self.max_front, self.max_behind,
        ):
            if 0 <= index < len(data_set):
                rows.append(self.driver_row(data_set[index], ctx, gap=gap))
            else:
                rows.append(None)
        self.refresh(tuple(rows))

    def gap_cell(self, gap: float, is_player: bool) -> Cell:
        """Relative time gap"""
        if is_player:
            return Cell()
        if self.wcfg["show_time_gap_sign"] and gap:
            text = f"{-gap:+.{self.gap_decimals}f}"
        else:
            text = f"{abs(gap):.{self.gap_decimals}f}"
        near = self.wcfg["show_highlighted_nearest_time_gap"] and self.nearest_gap[0] <= gap <= self.nearest_gap[1]
        return Cell(TEXT, text, "strong", self.theme.warning if near else self.theme.text)
