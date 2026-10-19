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

from PySide6.QtGui import QColor

from ...const_common import MAX_SECONDS
from ...i18n import tr_overlay
from ...module_info import minfo
from ...template.widget.drivers_ui import STANDINGS_COLUMNS
from .drivers import DRIVER_OPTIONS, Context, DriverTable, gap_text, live_trends
from .rows import DASH, class_style, laptime_text
from .table import LAPTIME, RIGHT, SEPARATOR, TEXT, Cell, ClassHeader, Column

DEFAULT_SPLIT_GAP = 5  # split_gap template default: space between class groups of design

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
        "show_class_header", "show_class_column_with_class_header", "show_class_sof", "class_order",
        "maximum_vehicles_exclusive_mode", "maximum_vehicles_combined_mode", "maximum_vehicles_split_mode",
        "maximum_vehicles_per_split_player", "maximum_vehicles_per_split_others", "split_gap",
        "column_delta_laptime", "number_of_delta_laptime", "show_inverted_delta_laptime_layout",
        "display_order_delta_laptime",
        "column_time_interval", "show_time_interval_from_same_class", "decimal_places_time_interval",
        "time_interval_leader_text", "display_order_time_interval",
        "column_time_gap", "show_time_gap_from_same_class", "decimal_places_time_gap", "time_gap_leader_text",
        "display_order_time_gap", "column_track_limits",
        "display_order_track_limits", "column_energy_per_lap", "show_energy_per_lap_average",
        "display_order_energy_per_lap", "column_driver_ranks", "show_driver_badge",
        "display_order_driver_ranks", "column_gap_trend", "display_order_gap_trend",
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
        self.class_sof = self.class_headers and bool(wcfg["show_class_sof"])  # strength of field in class headers
        self.sof_label = tr_overlay("SoF")
        self.rank_colors: dict[str, QColor] = {}
        self.setup_table()
        # Space between class groups follows split gap (pixels in classic design, design space at default)
        self.table = self.table._replace(split_scale=max(float(wcfg["split_gap"]), 0.0) / DEFAULT_SPLIT_GAP)
        self.set_size(self.table.width, self.table.height(1))

    def extra_column(self, key: str) -> Column | None:
        if key == "time_gap":
            sample = "+888." + "8" * self.gap_decimals if self.gap_decimals else "+888"
            return Column(key, max(self.text_width("strong", sample), self.text_width("label", self.gap_leader)), RIGHT)
        if key == "time_interval":
            sample = "888." + "8" * self.int_decimals if self.int_decimals else "888"
            return Column(key, max(self.text_width("value", sample), self.text_width("label", self.int_leader)), RIGHT)
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

    def class_header(self, class_name: str, level: Any = None) -> ClassHeader:
        """Header of a class group: class name (game name, words apart) on class color, strength of field of
        class at right end (average driver & safety rank with progress, in color of driver rank) if known"""
        _, color = class_style(self.cfg, class_name, self.theme)
        text = class_name.replace("_", " ").strip() or DASH
        if level is None or level.driver is None:
            return ClassHeader(text, color)
        from ...process import driver_ranks as dr

        colors = self.rank_colors
        if not colors:  # rank colors made once
            colors.update((name, QColor(value)) for name, value in
                          (dr.RANK_COLORS_LIGHT if self.theme.light else dr.RANK_COLORS).items())
        info = f"{self.sof_label} {level.driver.short} {level.driver.progress}%"
        if level.safety is not None:
            info = f"{info} · {level.safety.short} {level.safety.progress}%"
        return ClassHeader(text, color, info, colors.get(level.driver.name.casefold(), self.theme.text_dim))

    def class_levels(self, data_set) -> dict[str, Any]:
        """Strength of field of each class: average ranks of its drivers (all cars of class, shown or not)"""
        from ...process import field_ranks as fr

        if self.demo:
            from ...process import driver_ranks as dr
            from .drivers import SAMPLE_RANKS

            ranks: dict[str, list] = {}
            for veh in data_set:
                if veh.driverName:
                    sample = SAMPLE_RANKS[veh.positionOverall % len(SAMPLE_RANKS)]
                    ranks.setdefault(veh.vehicleClass, []).append(
                        dr.DriverRanks("", "", "", "", dr.Rank(*sample[:2], 50), dr.Rank(*sample[2:4], 50)))
            return {name: fr.average_level(found) for name, found in ranks.items()}
        from ...rank_info import field_level

        names: dict[str, list[str]] = {}
        for veh in data_set:
            if veh.driverName:
                names.setdefault(veh.vehicleClass, []).append(veh.driverName)
        return {name: field_level(class_names) for name, class_names in names.items()}

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.poll_columns(minfo.vehicles.dataSet)
        self.trend_of = live_trends() if self.wcfg["column_gap_trend"] else None
        # Cars of session only (strength of field of classes): slots beyond keep drivers of a former bigger session
        cars = minfo.vehicles.dataSet[:max(minfo.vehicles.totalVehicles, 0)]
        self.show_rows(cars, minfo.relative.standings, self.context())

    def show_field(self, field, ctx: Context):
        from .sample_field import sample_standings

        self.sample_columns()
        self.show_rows(field.vehicles, sample_standings(field, self.wcfg), ctx)

    def show_rows(self, data_set, standings: list[int], ctx: Context):
        """Rows of cars in standings order (-1: space between classes or cars apart in a class), class name
        above each class group if class headers, widget height follows"""
        rows: list = []
        shown_class = None
        levels = self.class_levels(data_set) if self.class_sof else {}
        for index in standings[:self.max_rows]:
            if index == -1:
                if rows and rows[-1] is not SEPARATOR:
                    rows.append(SEPARATOR)
            elif 0 <= index < len(data_set):
                veh = data_set[index]
                if self.class_headers and veh.vehicleClass != shown_class:
                    shown_class = veh.vehicleClass
                    rows.append(self.class_header(shown_class, levels.get(shown_class)))
                rows.append(self.driver_row(veh, ctx, **self.position_trend(veh, index, ctx)))
        while rows and rows[-1] is SEPARATOR:
            rows.pop()
        rows_tuple = tuple(rows)
        if self.refresh(rows_tuple):  # rows compared once: height follows changed rows
            height = self.table.content_height(rows_tuple) if rows_tuple else self.table.height(1)
            if ceil(height) != self.height():
                self.set_size(self.table.width, height)
                self.update()  # resized: whole widget
