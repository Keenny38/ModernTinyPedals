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

Cars around player on track: one row per car, player row highlighted, class color on row edge. Gap trend:
gap change per lap to each car (averaged over about 30 seconds), green when player gains, red when player loses.
"""

from __future__ import annotations

from collections.abc import Callable

from ...api_control import api
from ...module_info import minfo
from ...template.widget.drivers_ui import RELATIVE_COLUMNS
from ..relative import relative_data
from .drivers import DRIVER_OPTIONS, Context, DriverTable
from .table import RIGHT, TEXT, TREND, Cell, Column, Row, change_width

TREND_STEADY = 0.05  # seconds per lap: gap change below this shown as steady
# Gap change per lap of sample race rows (index -> seconds), overlay pictures
SAMPLE_TRENDS = {2: 0.3, 7: -0.2, 8: -0.4, 10: -0.3, 3: -1.8, 11: 0.5}

TrendOf = Callable[[float, int], "float | None"]


class Realtime(DriverTable):
    """Draw widget"""

    COLUMNS = RELATIVE_COLUMNS
    options = (
        *DRIVER_OPTIONS,
        "show_vehicle_in_garage",  # read by relative module
        "additional_players_front", "additional_players_behind",
        "column_time_gap", "show_time_gap_sign", "decimal_places_time_gap", "display_order_time_gap",
        "column_gap_trend", "display_order_gap_trend",
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
        if key == "gap_trend":
            return Column(key, change_width(self.unit, 1.62, self.digit_width("value"), 2) + self.text_width("value", "."))
        return None

    def extra_cell(self, key: str, veh, ctx: Context, extra: dict) -> Cell:
        if key == "time_gap":
            return self.gap_cell(extra["gap"], veh.isPlayer)
        if key == "gap_trend":
            return self.trend_cell(extra["gap"], extra.get("trend"), veh)
        return Cell()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.show_rows(minfo.vehicles.dataSet, minfo.relative.relativeAhead, minfo.relative.relativeBehind,
                       minfo.vehicles.playerIndex, self.context(), live_trends())

    def show_field(self, field, ctx: Context):
        self.show_rows(field.vehicles, field.relative_ahead, field.relative_behind, field.player_index, ctx,
                       lambda gap, index: SAMPLE_TRENDS.get(index))

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

    def trend_cell(self, gap: float, rate: float | None, veh) -> Cell:
        """Gap change per lap: good for player when closing on car ahead or pulling away from car behind"""
        if veh.isPlayer:
            return Cell()
        if rate is None or veh.inPit or abs(rate) < TREND_STEADY or not gap:
            return Cell(TREND)
        good = rate < 0 if gap > 0 else rate > 0
        return Cell(TREND, extra=(round(rate, 1), good))

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


def live_trends() -> TrendOf:
    """Gap change per lap of cars (relative module averages of gap change per second, about 30 s)"""
    laptime = api.read.timing.estimated_laptime()
    ahead = minfo.relative.relativeDeltaAhead
    behind = minfo.relative.relativeDeltaBehind

    def trend(gap: float, index: int) -> float | None:
        if laptime <= 0 or not 0 <= index < len(ahead):
            return None
        delta = ahead[index] if gap > 0 else behind[index]
        if not delta.short:
            return None
        return -delta.short * laptime  # gap shrinking (delta > 0) -> negative change
    return trend
