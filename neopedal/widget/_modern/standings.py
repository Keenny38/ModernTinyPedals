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
Standings Widget, modern design

Running order, split by class (space between class groups, class name above each group) or combined.
Widget height follows the number of cars shown. Gaps & intervals in class in split mode (option) and in
single class mode.
"""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING, Any

from ...api_control import api
from ...const_common import MAX_SECONDS
from ...demo_state import drawing_demo
from ...formatter import format_points
from ...i18n import tr_overlay
from ...module_info import minfo
from ...template.widget.drivers_ui import STANDINGS_COLUMNS
from .drivers import DRIVER_OPTIONS, Context, DriverTable, gap_text
from .rows import DASH, class_style, laptime_text
from .table import DELTAS, LAPTIME, RIGHT, SEPARATOR, TEXT, Cell, ClassHeader, Column

if TYPE_CHECKING:
    from ...template.widget_config_types import StandingsConfig


class Realtime(DriverTable):
    """Draw widget"""

    wcfg: StandingsConfig

    COLUMNS = STANDINGS_COLUMNS
    options = (
        *DRIVER_OPTIONS,
        "show_column_headers",
        "enable_multi_class_split_mode", "enable_single_class_exclusive_mode", "minimum_top_vehicles",
        "show_class_header", "show_class_column_with_class_header", "class_order",
        "maximum_vehicles_exclusive_mode", "maximum_vehicles_combined_mode", "maximum_vehicles_split_mode",
        "maximum_vehicles_per_split_player", "maximum_vehicles_per_split_others",
        "column_delta_laptime", "number_of_delta_laptime", "display_order_delta_laptime",
        "column_time_interval", "show_time_interval_from_same_class", "decimal_places_time_interval",
        "time_interval_leader_text", "display_order_time_interval",
        "column_time_gap", "show_time_gap_from_same_class", "decimal_places_time_gap", "time_gap_leader_text",
        "display_order_time_gap", "column_track_limits",
        "display_order_track_limits", "column_energy_per_lap", "show_energy_per_lap_average",
        "display_order_energy_per_lap",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.gap_decimals = max(int(wcfg["decimal_places_time_gap"]), 0)
        self.int_decimals = max(int(wcfg["decimal_places_time_interval"]), 0)
        split = wcfg["enable_multi_class_split_mode"]
        by_class = split or wcfg["enable_single_class_exclusive_mode"]  # cars shown grouped by class
        self.class_gap = by_class and wcfg["show_time_gap_from_same_class"]
        self.class_interval = by_class and wcfg["show_time_interval_from_same_class"]
        self.limit = 0.0  # track limits points per penalty of session, 0 if none
        self.demo = False  # overlay pictures & previews: simulated energy usage, nothing read from game
        self.energy_usage: Any = None  # energy usage poller, see usages
        self.usage_average = bool(wcfg["show_energy_per_lap_average"])
        self.delta_count = min(max(int(wcfg["number_of_delta_laptime"]), 2), 5)
        self.gap_leader = self.user_text("time_gap_leader_text", tr_overlay("Leader"))
        self.int_leader = self.user_text("time_interval_leader_text", DASH)
        if wcfg["enable_single_class_exclusive_mode"]:
            max_vehicles = wcfg["maximum_vehicles_exclusive_mode"]
        elif split:
            max_vehicles = wcfg["maximum_vehicles_split_mode"]
        else:
            max_vehicles = wcfg["maximum_vehicles_combined_mode"]
        self.max_rows = min(max(int(max_vehicles), 5), 126)
        # Cars grouped by class (split or exclusive mode): class name above each group instead of class column
        # (also with it if chosen)
        self.class_headers = bool(wcfg["show_class_header"]) and (
            split or wcfg["enable_single_class_exclusive_mode"])
        self.class_column_hidden = self.class_headers and not wcfg["show_class_column_with_class_header"]
        self.setup_table()
        self.set_size(self.table.width, self.table.height(1))

    def extra_column(self, key: str) -> Column | None:
        if key == "time_gap":
            sample = "+888." + "8" * self.gap_decimals if self.gap_decimals else "+888"
            return Column(key, max(self.text_width("strong", sample), self.text_width("label", self.gap_leader)), RIGHT)
        if key == "time_interval":
            sample = "888." + "8" * self.int_decimals if self.int_decimals else "888"
            return Column(key, max(self.text_width("value", sample), self.text_width("label", self.int_leader)), RIGHT)
        if key == "delta_laptime":
            return Column(key, (self.text_width("small", "8.8") + self.unit * 0.3) * self.delta_count, RIGHT)
        if key == "track_limits":
            return Column(key, self.text_width("dim", "88.88"), RIGHT)
        if key == "energy_per_lap":
            return Column(key, self.text_width("dim", "88.8%"), RIGHT)
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
                if self.int_leader == DASH:
                    return Cell(TEXT, DASH, "value", theme.text_faint)
                return Cell(TEXT, self.int_leader, "label", theme.accent)
            if not ctx.in_race and not 0 < veh.bestLapTime < MAX_SECONDS:  # best lap interval: no time yet
                return Cell(TEXT, DASH, "value", theme.text_faint)
            return Cell(TEXT, gap_text(gap, self.int_decimals), "value", theme.text_dim)
        if key == "track_limits":
            return self.track_limits_cell(veh.trackLimitsPoints, ctx.in_race)
        if key == "energy_per_lap":
            return self.energy_per_lap_cell(veh)
        if key == "delta_laptime":
            if ctx.player is None or veh.isPlayer:
                return Cell(DELTAS)
            return Cell(DELTAS, extra=tuple(veh.lapTimeHistory.delta(ctx.player.lapTimeHistory, self.delta_count)))
        return Cell()

    def laptime_cell(self, veh, ctx: Context) -> Cell:
        """Last lap in race (or if best lap column shown, or running time shown), else best lap (purple if fastest
        of class), sector bars of lap being driven"""
        if ctx.in_race or self.wcfg["column_best_laptime"] or self.wcfg.get("show_running_lap_time", True):
            return super().laptime_cell(veh, ctx)
        theme = self.theme
        best, class_best = veh.bestLapTime, veh.classBestLapTime
        valid = 0 < best < MAX_SECONDS
        fastest = (self.wcfg.get("show_highlighted_fastest_last_laptime", True) and valid
                   and abs(best - (veh.classBestLap or class_best)) < 0.0005)
        sectors = self.sector_parts(veh, ctx) if self.wcfg.get("show_lap_sectors", True) else ()
        return Cell(LAPTIME, laptime_text(best), "dim", theme.best if fastest else theme.text_dim,
                    extra=self.laptime_extra(sectors))

    def gap_cell(self, veh, ctx: Context) -> Cell:
        """Gap to leader (race), or to leader best lap (other sessions)"""
        theme = self.theme
        leader_cell = Cell(TEXT, self.gap_leader, "label", theme.accent)
        if ctx.in_race:
            if self.class_gap:
                position, gap = veh.positionInClass, veh.gapBehindLeaderInClass
            else:
                position, gap = veh.positionOverall, veh.gapBehindLeader
            if position == 1:
                return leader_cell
            text = gap_text(gap, self.gap_decimals)
            return Cell(TEXT, text if text == DASH else f"+{text}", "strong", theme.text)
        best = veh.bestLapTime
        leader_best = veh.classBestLapTime if self.class_gap else minfo.vehicles.leaderBestLapTime
        gap = best - leader_best
        if gap == 0 and best > 0:
            return leader_cell
        if gap < 0 or best < 1:
            return Cell(TEXT, DASH, "strong", theme.text_faint)
        return Cell(TEXT, f"+{gap:.{self.gap_decimals}f}", "strong", theme.text)

    def energy_per_lap_cell(self, veh) -> Cell:
        """Virtual energy used in last lap (or average of last 5 laps) as game gives it, dash if unknown"""
        theme = self.theme
        if self.demo:
            used = demo_energy_per_lap(veh)
        else:
            usage = self.usages().usage(veh.driverName)
            used = -1.0 if usage is None else (usage.average if self.usage_average else usage.last)
        if used <= 0:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        return Cell(TEXT, f"{used * 100:.1f}%", "dim", theme.text_dim)

    def usages(self) -> Any:
        """Energy usage poller (energy_usage module loaded only with energy per lap column)"""
        if self.energy_usage is None:
            from ...energy_usage import energy_usage

            self.energy_usage = energy_usage
        return self.energy_usage

    def track_limits_cell(self, points: float, in_race: bool) -> Cell:
        """Track limits points: amber once any, red one point before penalty (races only: no penalty in
        practice & qualifying)"""
        theme = self.theme
        if points <= 0:
            return Cell(TEXT, DASH, "dim", theme.text_faint)
        limit = self.limit if in_race else 0.0
        color = theme.negative if limit > 0 and points >= limit - 1 else theme.warning
        return Cell(TEXT, format_points(points), "dim", color)

    def class_header(self, class_name: str) -> ClassHeader:
        """Header of a class group: class name (game name, words apart) on class color"""
        _, color = class_style(self.cfg, class_name, self.theme)
        return ClassHeader(class_name.replace("_", " ").strip() or DASH, color)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.limit = api.read.session.limits_points()
        self.demo = drawing_demo()
        if self.wcfg["column_energy_per_lap"] and not self.demo:
            self.usages().poll()
        self.show_rows(minfo.vehicles.dataSet, minfo.relative.standings, self.context())

    def show_field(self, field, ctx: Context):
        from .sample_field import sample_standings

        self.limit = 5.0
        self.demo = True
        self.show_rows(field.vehicles, sample_standings(field, self.wcfg), ctx)

    def show_rows(self, data_set, standings: list[int], ctx: Context):
        """Rows of cars in standings order (-1: space between classes or cars apart in a class), class name
        above each class group if class headers, widget height follows"""
        rows: list = []
        shown_class = None
        for index in standings[:self.max_rows]:
            if index == -1:
                if rows and rows[-1] is not SEPARATOR:
                    rows.append(SEPARATOR)
            elif 0 <= index < len(data_set):
                veh = data_set[index]
                if self.class_headers and veh.vehicleClass != shown_class:
                    shown_class = veh.vehicleClass
                    rows.append(self.class_header(shown_class))
                rows.append(self.driver_row(veh, ctx))
        while rows and rows[-1] is SEPARATOR:
            rows.pop()
        rows_tuple = tuple(rows)
        if self.refresh(rows_tuple):  # rows compared once: height follows changed rows
            height = self.table.content_height(rows_tuple) if rows_tuple else self.table.height(1)
            if ceil(height) != self.height():
                self.set_size(self.table.width, height)
                self.update()  # resized: whole widget


def demo_energy_per_lap(veh) -> float:
    """Simulated energy used per lap (overlay pictures & previews): cars with virtual energy only"""
    if "LMP2" in veh.vehicleClass or "LMP3" in veh.vehicleClass:
        return -1.0
    return 0.031 + (veh.positionOverall * 7 % 9) * 0.0012
