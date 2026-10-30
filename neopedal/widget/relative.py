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
Relative Widget
"""

from typing import TYPE_CHECKING

from ..api_control import api
from ..const_common import REL_TIME_DEFAULT
from ..module_info import minfo
from ._columns import DriverTable, lap_time_key, pit_time_key, pit_time_shown, styles
from ._common import player_vehicle

if TYPE_CHECKING:
    from ..template.widget_config_types import RelativeConfig

COLUMN_NAMES = ("pos", "pgl", "drv", "veh", "brd", "gap", "lpt", "blp", "alp", "pic", "cls", "pit", "tcp", "psc",
                "nrg", "dmg", "icd", "stl", "spd", "lic")


class Realtime(DriverTable):
    """Draw widget"""

    wcfg: "RelativeConfig"
    blank_state = 0  # empty rows: cells kept, text cleared

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
        self.gap_decimals = max(int(self.wcfg["decimal_places_time_gap"]), 0)
        self.nrg_decimals = max(int(self.wcfg["decimal_places_energy_remaining"]), 0)
        self.nrg_width = 3 + self.nrg_decimals + (self.nrg_decimals > 0)
        self.nearest_time_gap = (
            -max(self.wcfg["nearest_time_gap_threshold_behind"], 0),
            max(self.wcfg["nearest_time_gap_threshold_front"], 0),
        )

        # Max display players
        min_base_veh = 3
        self.max_veh_front = min_base_veh + min(max(int(self.wcfg["additional_players_front"]), 0), 60)
        self.max_veh_behind = min_base_veh + min(max(int(self.wcfg["additional_players_behind"]), 0), 60)
        self.veh_range = max(self.max_veh_front + self.max_veh_behind, min_base_veh * 2) + 1
        self.row_visible = [False] * self.veh_range

        # Columns (shared columns, see _columns): position, driver & vehicle name colored by lap difference
        self.set_driver_columns(
            layout, font_m, bar_padx, COLUMN_NAMES, lap_difference=True,
            own_styles={"gap": styles("time_gap", "player_time_gap", "nearest_time_gap")},
        )

    def timerEvent(self, event):
        """Update when vehicle on track"""
        player_idx = minfo.vehicles.playerIndex
        relative_list = relative_data(
            minfo.relative.relativeAhead,
            minfo.relative.relativeBehind,
            player_idx,
            self.max_veh_front,
            self.max_veh_behind,
        )
        plr_veh_info = player_vehicle()
        in_race = api.read.session.in_race()

        # Relative update
        for idx, (rel_time_gap, rel_idx) in enumerate(relative_list):
            # Set row state: 1 - show text, 0 - hide text
            if rel_idx >= 0:
                self.row_visible[idx] = True
                state = 1
            elif not self.row_visible[idx]:
                continue  # skip if already empty
            else:
                self.row_visible[idx] = False
                state = 0

            # Get vehicle dataset
            veh_info = minfo.vehicles.dataSet[rel_idx]
            # Highlighted player
            hi_player = self.wcfg["show_player_highlighted"] and veh_info.isPlayer
            # Position & name color: player, or lap difference
            if hi_player:
                name_style = 1
            elif self.wcfg["show_lap_difference"]:
                name_style = lap_difference_index(veh_info.isLapped)
            else:
                name_style = 0
            # Shared columns
            self.update_columns(idx, veh_info, hi_player, name_style, in_race, state)
            # Time gap
            if self.wcfg["show_time_gap"]:
                self.update_gap(self.bars_gap[idx], rel_time_gap, hi_player, state)
            # Vehicle laptime (values as displayed, text made once changed)
            if self.wcfg["show_laptime"]:
                if (self.wcfg["show_pitstop_duration_while_requested_pitstop"] and plr_veh_info.pitRequested) or pit_time_shown(veh_info):
                    laptime = pit_time_key(veh_info.inPit, veh_info.pitTimer.elapsed)
                    is_class_best = False
                else:
                    laptime = lap_time_key(veh_info.lastLapTime, veh_info.isValidLap)
                    is_class_best = veh_info.isClassFastestLastLap
                self.update_lpt(self.bars_lpt[idx], laptime, is_class_best, hi_player, state)

    # GUI update methods
    def update_gap(self, target, *data):
        """Time gap"""
        if target.last != data:
            target.last = data
            if data[1]:  # highlight player
                color_index = 1
            elif (self.wcfg["show_highlighted_nearest_time_gap"] and data[-1] and
                  self.nearest_time_gap[0] <= data[0] <= self.nearest_time_gap[1]):
                color_index = 2
            else:
                color_index = 0
            if data[-1]:
                if self.wcfg["show_time_gap_sign"] and data[0] != 0:
                    text = f"{-data[0]:+z.{self.gap_decimals}f}"[:self.gap_width].strip(".")
                else:
                    text = f"{abs(data[0]):.{self.gap_decimals}f}"[:self.gap_width].strip(".")
                if not self.wcfg["time_gap_align_center"]:
                    text = f"{text:>{self.gap_width}}"
            else:
                text = ""
            fg, bg = self.bar_style_gap[color_index]
            if text != target.text or fg != target.fg or bg != target.bg:  # gap changes every update, text less
                target.text = text
                target.fg, target.bg = fg, bg
                target.update()

    # Additional methods
    def toggle_visibility(self, target, state):
        """Cells never hidden: drawn again (empty row: text cleared)"""
        target.update()


def lap_difference_index(is_lapped, offset=2):
    """Set lap difference as index

    Returns:
        0 = same lap, 1 = behind, 2 = ahead
    """
    return (is_lapped < 0) + (is_lapped > 0) * 2 + offset


def relative_data(ahead_list: list, behind_list: list, player_index: int, max_ahead: int, max_behind: int):
    """Generate relative time & index data"""
    if len(ahead_list) < max_ahead + max_behind:  # few cars: some may be shown ahead and behind
        ahead_list, behind_list = split_relative(ahead_list, behind_list, max_ahead, max_behind)
    # Yield ahead data
    ahead_count = len(ahead_list)
    while ahead_count < max_ahead:
        ahead_count += 1
        yield REL_TIME_DEFAULT
    for ahead_data in ahead_list:
        if ahead_count > max_ahead:
            ahead_count -= 1
        else:
            yield ahead_data
    # Yield player data
    yield (0.0, player_index)
    # Yield behind data
    behind_count = 0
    for behind_data in behind_list:
        if behind_count < max_behind:
            behind_count += 1
            yield behind_data
        else:
            break
    while behind_count < max_behind:
        behind_count += 1
        yield REL_TIME_DEFAULT


def split_relative(ahead_list: list, behind_list: list, max_ahead: int, max_behind: int) -> tuple[list, list]:
    """Each car once (fewer cars than rows): ahead if nearer ahead than behind, as rows allow; lists unchanged
    if no car would be shown twice

    Both lists hold every car: ahead list farthest ahead first (nearest behind first in behind list).
    Cars kept ahead are the nearest ones of ahead list, the others are behind.
    """
    total = len(ahead_list)
    shown_ahead = {index for _, index in ahead_list[max(total - max_ahead, 0):]}
    if shown_ahead.isdisjoint(index for _, index in behind_list[:max_behind]):
        return ahead_list, behind_list
    gap_behind = {index: gap for gap, index in behind_list}
    nearer_ahead = sum(gap <= -gap_behind.get(index, -gap) for gap, index in ahead_list)
    ahead_count = min(max(nearer_ahead, total - max_behind), max_ahead)
    ahead = ahead_list[total - ahead_count:]
    shown_ahead = {index for _, index in ahead}
    return ahead, [data for data in behind_list if data[1] not in shown_ahead]
