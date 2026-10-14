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
Rivals Widget
"""

from typing import TYPE_CHECKING

from .. import calculation as calc
from ..api_control import api
from ..module_info import minfo
from ._columns import DriverTable, lap_time_key, pit_time_key, styles
from ._common import player_vehicle
from ._painter import DeltaLapTime

if TYPE_CHECKING:
    from ..template.widget_config_types import RivalsConfig

COLUMN_NAMES = ("pos", "pgl", "drv", "veh", "brd", "int", "lpt", "blp", "alp", "dlt", "pic", "cls", "pit", "tcp",
                "psc", "nrg", "dmg", "icd", "stl", "spd", "lic")


class Realtime(DriverTable):
    """Draw widget"""

    wcfg: "RivalsConfig"

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
        self.int_width = max(int(self.wcfg["time_interval_width"]), 1)
        self.int_decimals = max(int(self.wcfg["decimal_places_time_interval"]), 0)
        self.max_delta = int(calc.asym_max(int(self.wcfg["number_of_delta_laptime"]), 2, 5))
        self.nrg_decimals = max(int(self.wcfg["decimal_places_energy_remaining"]), 0)
        self.nrg_width = 3 + self.nrg_decimals + (self.nrg_decimals > 0)

        # Max display players
        self.veh_range = 2
        self.row_visible = [True] * self.veh_range

        # Columns (shared columns, see _columns): no player colors, interval colored ahead or behind
        self.set_driver_columns(
            layout, font_m, bar_padx, COLUMN_NAMES, hide_start=1, player_styles=False,
            own_styles={
                "int": styles("time_interval_behind", "time_interval_ahead"),
                "lpt": styles("laptime"),
            },
            own_columns={"dlt": self.set_delta_column},
        )

    def set_delta_column(self, layout, font_m, bar_padx):
        """Delta laptime column"""
        if not self.wcfg["show_delta_laptime"]:
            return
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
        in_race = api.read.session.in_race()
        plr_veh_info = player_vehicle()  # neutral if none: no rival rows
        rivals_list = plr_veh_info.classAheadIndex, plr_veh_info.classBehindIndex

        # Standings update
        for idx, rvl_idx in enumerate(rivals_list):

            # Get vehicle dataset
            if rvl_idx >= 0:
                self.row_visible[idx] = True
                state = 1
            elif not self.row_visible[idx]:
                continue  # skip if already empty
            else:
                self.row_visible[idx] = False
                state = 0

            # Get vehicle dataset
            veh_info = minfo.vehicles.dataSet[rvl_idx]
            # Shared columns (no highlighted player)
            self.update_columns(idx, veh_info, False, False, in_race, state)
            # Time interval
            if self.wcfg["show_time_interval"]:
                is_ahead = veh_info.positionOverall < plr_veh_info.positionOverall
                if is_ahead:
                    time_int = plr_veh_info.gapBehindNextInClass
                else:
                    time_int = veh_info.gapBehindNextInClass
                if not isinstance(time_int, int):  # as displayed: cell rebuilt only once text changes
                    time_int = round(time_int, self.int_decimals)
                self.update_int(self.bars_int[idx], time_int, is_ahead, state)
            # Vehicle laptime
            if self.wcfg["show_laptime"]:
                # Values as displayed (text made once changed)
                if self.wcfg["show_pitstop_duration_while_requested_pitstop"] and plr_veh_info.pitRequested:
                    lap_key = pit_time_key(veh_info.inPit, veh_info.pitTimer.elapsed)
                elif in_race or self.wcfg["show_best_laptime"]:
                    if veh_info.pitTimer.pitting:
                        lap_key = pit_time_key(veh_info.inPit, veh_info.pitTimer.elapsed)
                    else:
                        lap_key = lap_time_key(veh_info.lastLapTime, veh_info.isValidLap)
                else:
                    lap_key = lap_time_key(veh_info.bestLapTime)
                self.update_lpt(self.bars_lpt[idx], lap_key, False, False, state)
            # Delta laptime
            if self.wcfg["show_delta_laptime"]:
                delta_laptime = tuple(veh_info.lapTimeHistory.delta(plr_veh_info.lapTimeHistory, self.max_delta))
                self.update_dlt(self.bars_dlt[idx], delta_laptime, state)

    # GUI update methods
    def update_int(self, target, *data):
        """Time interval"""
        if target.last != data:
            target.last = data
            text = self.int_to_next(data[0], data[1])[:self.int_width].strip(".")
            if not self.wcfg["time_interval_align_center"]:
                text = f"{text:>{self.int_width}}"
            target.text = text
            target.fg, target.bg = self.bar_style_int[data[1]]
            self.toggle_visibility(target, data[-1])

    def update_dlt(self, target, *data):
        """Vehicle delta laptime"""
        if target.last != data:
            target.last = data
            target.delta = data[0]
            self.toggle_visibility(target, data[-1])

    # Additional methods
    def toggle_visibility(self, target, state):
        """Hide bar if unavailable"""
        target.update()
        if target.state == state:
            return
        target.state = state
        target.setHidden(not state)

    def int_to_next(self, gap_behind_class, is_ahead):
        """Interval to next"""
        if isinstance(gap_behind_class, int):
            return f"{'+-'[is_ahead]}{gap_behind_class:.0f}L"
        return f"{'+-'[is_ahead]}{gap_behind_class:.{self.int_decimals}f}"
