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
Relative Widget, modern design

Cars around player on track: one row per car, player row highlighted, class color on row edge. Gap trend:
gap change per lap to each car (averaged over about 30 seconds), green when player gains, red when player loses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...module_info import minfo
from ...template.widget.drivers_ui import RELATIVE_COLUMNS
from ..relative import relative_data
from .base import signed
from .drivers import DRIVER_OPTIONS, Context, DriverTable, TrendOf, live_trends
from .table import RIGHT, TEXT, Cell, Column, Row

if TYPE_CHECKING:
    from ...template.widget_config_types import RelativeConfig


class Realtime(DriverTable):
    """Draw widget"""

    wcfg: RelativeConfig

    COLUMNS = RELATIVE_COLUMNS
    options = (
        *DRIVER_OPTIONS,
        "show_vehicle_in_garage",  # read by relative module
        "additional_players_front", "additional_players_behind",
        "column_time_gap", "show_time_gap_sign", "decimal_places_time_gap", "display_order_time_gap",
        "column_gap_trend", "display_order_gap_trend", "column_driver_ranks", "column_driver_badge",
        "display_order_driver_ranks", "display_order_driver_badge",
        "show_highlighted_nearest_time_gap", "nearest_time_gap_threshold_front", "nearest_time_gap_threshold_behind",
        "column_delta_laptime", "number_of_delta_laptime", "show_inverted_delta_laptime_layout",
        "display_order_delta_laptime", "column_track_limits", "display_order_track_limits",
        "column_energy_per_lap", "show_energy_per_lap_average", "display_order_energy_per_lap",
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
        self.poll_columns(minfo.vehicles.dataSet)
        self.show_rows(minfo.vehicles.dataSet, minfo.relative.relativeAhead, minfo.relative.relativeBehind,
                       minfo.vehicles.playerIndex, self.context(), live_trends())

    def show_field(self, field, ctx: Context):
        self.sample_columns()
        self.show_rows(field.vehicles, field.relative_ahead, field.relative_behind, field.player_index, ctx,
                       self.trend_of)

    def show_rows(self, data_set, ahead: list, behind: list, player_index: int, ctx: Context,
                  trend_of: TrendOf | None = None):
        """Rows of cars ahead, player & cars behind (empty rows if fewer cars)

        Args:
            trend_of: gap change per lap (seconds, + growing) of car (gap, index), None if unknown.
        """
        rows: list[Row | None] = []
        trends = trend_of if trend_of is not None and self.wcfg["column_gap_trend"] else None
        for gap, index in relative_data(ahead, behind, player_index, self.max_front, self.max_behind):
            if 0 <= index < len(data_set):
                trend = trends(gap, index) if trends is not None and index != player_index else None
                rows.append(self.driver_row(data_set[index], ctx, gap=gap, trend=trend))
            else:
                rows.append(None)
        self.refresh(tuple(rows))

    def gap_cell(self, gap: float, is_player: bool) -> Cell:
        """Relative time gap"""
        if is_player:
            return Cell()
        if self.wcfg["show_time_gap_sign"] and gap:
            text = signed(-gap, self.gap_decimals)
        else:
            text = f"{abs(gap):.{self.gap_decimals}f}"
        near = self.wcfg["show_highlighted_nearest_time_gap"] and self.nearest_gap[0] <= gap <= self.nearest_gap[1]
        return Cell(TEXT, text, "strong", self.theme.warning if near else self.theme.text)
