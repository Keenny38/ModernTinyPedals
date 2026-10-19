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
Rivals Widget, modern design

Car ahead and car behind in player class, with interval to player.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...module_info import minfo
from ...template.widget.drivers_ui import RIVALS_COLUMNS
from .drivers import DRIVER_OPTIONS, Context, DriverTable, live_trends
from .rows import laptime_text
from .table import RIGHT, TEXT, Cell, Column, Row

if TYPE_CHECKING:
    from ...template.widget_config_types import RivalsConfig


class Realtime(DriverTable):
    """Draw widget"""

    wcfg: RivalsConfig

    COLUMNS = RIVALS_COLUMNS
    options = (
        *DRIVER_OPTIONS,
        "column_delta_laptime", "number_of_delta_laptime", "show_inverted_delta_laptime_layout",
        "display_order_delta_laptime",
        "column_time_interval", "decimal_places_time_interval", "display_order_time_interval",
        "column_track_limits", "display_order_track_limits", "column_driver_ranks", "show_driver_badge",
        "display_order_driver_ranks", "column_gap_trend", "display_order_gap_trend",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.int_decimals = max(int(self.wcfg["decimal_places_time_interval"]), 0)
        self.setup_table()
        self.set_size(self.table.width, self.table.height(2))

    def extra_column(self, key: str) -> Column | None:
        if key == "time_interval":
            sample = "+888." + "8" * self.int_decimals if self.int_decimals else "+888"
            return Column(key, self.text_width("strong", sample), RIGHT)
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
        return Cell()

    def laptime_cell(self, veh, ctx: Context) -> Cell:
        """Last lap in race (or if best lap column shown), else best lap"""
        if ctx.in_race or self.wcfg["column_best_laptime"]:
            return super().laptime_cell(veh, ctx)
        return Cell(TEXT, laptime_text(veh.bestLapTime), "dim", self.theme.text_dim)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.poll_columns(minfo.vehicles.dataSet)  # driver ranks: names of whole session (as other lists)
        self.trend_of = live_trends() if self.wcfg["column_gap_trend"] else None
        self.show_rows(minfo.vehicles.dataSet, self.context())

    def show_field(self, field, ctx: Context):
        self.sample_columns()
        self.show_rows(field.vehicles, ctx)

    def show_rows(self, data_set, ctx: Context):
        """Car ahead & car behind in player class"""
        rows: list[Row | None] = []
        if ctx.player is not None:
            for index in (ctx.player.classAheadIndex, ctx.player.classBehindIndex):
                if 0 <= index < len(data_set):
                    veh = data_set[index]
                    rows.append(self.driver_row(veh, ctx, **self.position_trend(veh, index, ctx)))
                else:
                    rows.append(None)
        self.refresh(tuple(rows))
