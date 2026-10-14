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
Standings Widget
"""

from typing import TYPE_CHECKING

from .. import calculation as calc
from ..api_control import api
from ..const_common import MAX_SECONDS
from ..module_info import minfo
from ._columns import DriverTable, lap_time_key, pit_time_key
from ._common import player_vehicle
from ._painter import DeltaLapTime

if TYPE_CHECKING:
    from ..template.widget_config_types import StandingsConfig

COLUMN_NAMES = ("pos", "pgl", "drv", "veh", "brd", "gap", "int", "lpt", "blp", "alp", "dlt", "pic", "cls", "pit",
                "tcp", "psc", "nrg", "dmg", "icd", "stl", "spd", "lic")


class Realtime(DriverTable):
    """Draw widget"""

    wcfg: "StandingsConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout = self.set_grid_layout(gap_vert=self.wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(
            self.wcfg["font_name"],
            self.wcfg["font_size"],
            self.wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        # Config variable
        bar_padx = self.set_padding(self.wcfg["font_size"], self.wcfg["bar_padding"])
        self.drv_width = max(int(self.wcfg["driver_name_width"]), 1)
        self.veh_width = max(int(self.wcfg["vehicle_name_width"]), 1)
        self.brd_width = max(int(self.wcfg["brand_logo_width"]), 1)
        self.brd_height = max(self.wcfg["font_size"], 1)
        self.cls_width = max(int(self.wcfg["class_width"]), 0)
        self.gap_width = max(int(self.wcfg["time_gap_width"]), 1)
        self.int_width = max(int(self.wcfg["time_interval_width"]), 1)
        self.gap_decimals = max(int(self.wcfg["decimal_places_time_gap"]), 0)
        self.int_decimals = max(int(self.wcfg["decimal_places_time_interval"]), 0)
        self.show_class_separator = self.wcfg["split_gap"] > 0
        by_class = (self.wcfg["enable_multi_class_split_mode"]  # cars shown grouped by class
            or self.wcfg["enable_single_class_exclusive_mode"])
        self.show_class_timegap = by_class and self.wcfg["show_time_gap_from_same_class"]
        self.show_class_interval = by_class and self.wcfg["show_time_interval_from_same_class"]
        self.max_delta = int(calc.asym_max(int(self.wcfg["number_of_delta_laptime"]), 2, 5))
        self.nrg_decimals = max(int(self.wcfg["decimal_places_energy_remaining"]), 0)
        self.nrg_width = 3 + self.nrg_decimals + (self.nrg_decimals > 0)

        self.height_def = font_m.height
        self.height_gap = self.wcfg["split_gap"]

        # Max display players
        if self.wcfg["enable_single_class_exclusive_mode"]:
            max_display_vehicles = self.wcfg["maximum_vehicles_exclusive_mode"]
        elif self.wcfg["enable_multi_class_split_mode"]:
            max_display_vehicles = self.wcfg["maximum_vehicles_split_mode"]
        else:
            max_display_vehicles = self.wcfg["maximum_vehicles_combined_mode"]
        self.veh_range = min(max(int(max_display_vehicles), 5), 126)
        self.row_visible = [False] * self.veh_range

        # Columns (shared columns, see _columns)
        self.set_driver_columns(
            layout, font_m, bar_padx, COLUMN_NAMES, hide_start=1,
            own_columns={"dlt": self.set_delta_column},
        )

    def set_delta_column(self, layout, font_m, bar_padx):
        """Delta laptime column"""
        if not self.wcfg["show_delta_laptime"]:
            return
        self.bar_style_dlt = (
            self.wcfg["background_color_delta_laptime"],
            self.wcfg["background_color_player_delta_laptime"],
        )
        self.bars_dlt = tuple(
            DeltaLapTime(
                parent=self,
                count=self.max_delta,
                padding=bar_padx,
                width=font_m.width * 4,
                height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_delta_laptime"],
                bg_color=self.wcfg["background_color_delta_laptime"],
                fg_color_gain=self.wcfg["font_color_delta_laptime_gain"],
                fg_color_loss=self.wcfg["font_color_delta_laptime_loss"],
                fg_color_player=self.wcfg["font_color_player_delta_laptime"],
                inverted=self.wcfg["show_inverted_delta_laptime_layout"],
            )
            for _ in range(self.veh_range)
        )
        self.set_grid_layout_table_column(
            layout=layout,
            targets=self.bars_dlt,
            column=self.wcfg["display_order_delta_laptime"],
            hide_start=1,
        )

    def timerEvent(self, event):
        """Update when vehicle on track"""
        standings_list = minfo.relative.standings
        total_std_idx = len(standings_list) - 1  # skip final -1 index
        plr_veh_info = player_vehicle()
        in_race = api.read.session.in_race()

        # Standings update
        for idx in range(self.veh_range):

            if idx < total_std_idx:
                std_idx = standings_list[idx]
            else:
                std_idx = -2

            # Set row state: 0 - show, 1 - draw gap, 2 - hide
            if std_idx >= -1:
                self.row_visible[idx] = True
                state = int(std_idx == -1)
            elif not self.row_visible[idx]:
                continue  # skip update if already empty
            else:
                self.row_visible[idx] = False
                state = 2

            # Get vehicle dataset
            veh_info = minfo.vehicles.dataSet[std_idx]
            # Highlighted player
            hi_player = self.wcfg["show_player_highlighted"] and veh_info.isPlayer
            # Shared columns
            self.update_columns(idx, veh_info, hi_player, hi_player, in_race, state)
            # Time gap (values as displayed, text made once changed)
            if self.wcfg["show_time_gap"]:
                if in_race:
                    if self.show_class_timegap:
                        time_gap = self.gap_key_race(veh_info.gapBehindLeaderInClass, veh_info.positionInClass)
                    else:
                        time_gap = self.gap_key_race(veh_info.gapBehindLeader, veh_info.positionOverall)
                else:
                    if self.show_class_timegap:
                        time_gap = self.gap_key_best(veh_info.bestLapTime, veh_info.classBestLapTime)
                    else:
                        time_gap = self.gap_key_best(veh_info.bestLapTime, minfo.vehicles.leaderBestLapTime)
                self.update_gap(self.bars_gap[idx], time_gap, hi_player, state)
            # Time interval
            if self.wcfg["show_time_interval"]:
                if self.show_class_interval:
                    time_int = self.int_key(veh_info.positionInClass, veh_info.gapBehindNextInClass)
                else:
                    time_int = self.int_key(veh_info.positionOverall, veh_info.gapBehindNext)
                self.update_int(self.bars_int[idx], time_int, hi_player, state)
            # Vehicle laptime
            if self.wcfg["show_laptime"]:
                if self.wcfg["show_pitstop_duration_while_requested_pitstop"] and plr_veh_info.pitRequested:
                    lap_key = pit_time_key(veh_info.inPit, veh_info.pitTimer.elapsed)
                    is_class_best = False
                elif in_race or self.wcfg["show_best_laptime"]:
                    if veh_info.pitTimer.pitting:
                        lap_key = pit_time_key(veh_info.inPit, veh_info.pitTimer.elapsed)
                        is_class_best = False
                    else:
                        lap_key = lap_time_key(veh_info.lastLapTime, veh_info.isValidLap)
                        is_class_best = veh_info.isClassFastestLastLap
                else:
                    lap_key = lap_time_key(veh_info.bestLapTime)
                    is_class_best = False
                self.update_lpt(self.bars_lpt[idx], lap_key, is_class_best, hi_player, state)
            # Delta laptime
            if self.wcfg["show_delta_laptime"]:
                recent = 5 - self.max_delta  # recent laps compared, deltas made once changed
                self.update_dlt(
                    self.bars_dlt[idx], veh_info.lapTimeHistory[recent:], plr_veh_info.lapTimeHistory[recent:],
                    hi_player, state)

    # GUI update methods
    def update_gap(self, target, *data):
        """Time gap"""
        if target.last != data:
            target.last = data
            target.text = self.gap_text(data[0], self.gap_decimals)[:self.gap_width].strip(".")
            target.fg, target.bg = self.bar_style_gap[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_int(self, target, *data):
        """Time interval"""
        if target.last != data:
            target.last = data
            target.text = self.gap_text(data[0], self.int_decimals)[:self.int_width].strip(".")
            target.fg, target.bg = self.bar_style_int[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_dlt(self, target, *data):
        """Vehicle delta laptime"""
        if target.last != data:
            target.last = data
            is_player = data[2]
            target.is_player = is_player
            target.delta = tuple(
                other - own if other > 0 < own else MAX_SECONDS for own, other in zip(data[0], data[1]))
            target.bg = self.bar_style_dlt[is_player]
            self.toggle_visibility(target, data[-1])

    # Additional methods
    def toggle_visibility(self, target, state):
        """Hide bar if unavailable"""
        target.update()
        if target.state == state:
            return
        target.state = state
        if state == 1 and self.show_class_separator:  # draw gap
            target.clear()
            target.setFixedHeight(self.height_gap)
            target.show()
        else:
            target.setHidden(state)
            target.setFixedHeight(self.height_def)

    def gap_key_best(self, player_best, leader_best):
        """Gap to leader's best laptime as displayed: text, or seconds rounded to decimals"""
        time = player_best - leader_best  # leader best
        if time == 0 and player_best > 0:
            return self.wcfg["time_gap_leader_text"]
        if time < 0 or player_best < 1:  # no time set
            return "0.0"
        return round(time, self.gap_decimals)

    def gap_key_race(self, gap_behind, position):
        """Gap to race leader as displayed: text, or seconds rounded to decimals"""
        if position == 1:
            return self.wcfg["time_gap_leader_text"]
        if isinstance(gap_behind, int):
            return f"{gap_behind:.0f}L"
        return round(gap_behind, self.gap_decimals)

    def int_key(self, position, gap_behind):
        """Interval to next as displayed: text, or seconds rounded to decimals"""
        if position == 1:
            return self.wcfg["time_interval_leader_text"]
        if isinstance(gap_behind, int):
            return f"{gap_behind:.0f}L"
        return round(gap_behind, self.int_decimals)

    @staticmethod
    def gap_text(key, decimals):
        """Gap or interval text of its displayed value"""
        if isinstance(key, str):
            return key
        return f"{key:.{decimals}f}"
