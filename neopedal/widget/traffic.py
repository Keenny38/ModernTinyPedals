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
Traffic Widget
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from .. import units
from ..api_control import api
from ..const_common import MAX_SECONDS, TEXT_PLACEHOLDER
from ..formatter import random_color_class, shorten_driver_name
from ..module_info import VehicleDataSet, minfo
from ._base import Overlay
from ._common import player_vehicle

if TYPE_CHECKING:
    from ..template.widget_config_types import TrafficConfig


class Realtime(Overlay):
    """Draw widget"""

    wcfg: "TrafficConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout = self.set_grid_layout(gap_hori=self.wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(
            self.wcfg["font_name"],
            self.wcfg["font_size"],
            self.wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        if self.wcfg["show_caption"]:
            font_cap = self.config_font(
                self.wcfg["font_name"],
                self.wcfg["font_size"] * self.wcfg["font_scale_caption"],
                self.wcfg["font_weight"],
            )
            font_cap_m = self.get_font_metrics(font_cap)

        # Config variable
        bar_padx = self.set_padding(self.wcfg["font_size"], self.wcfg["bar_padding"])
        bar_width = max(self.wcfg["bar_width"], 3)
        style_width = font_m.width * bar_width + bar_padx
        self.lap_width = bar_width - 1
        self.cls_width = bar_width
        self.show_slower_ahead = self.wcfg["show_slower_ahead"]
        self.show_race_leader = self.wcfg["show_race_leader"]
        self.show_faster_behind = self.wcfg["show_faster_behind"]

        # Config units
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])

        if self.wcfg["show_caption"]:
            cap_temps = self.set_rawtext(
                font=font_cap,
                fixed_height=font_cap_m.height,
                offset_y=font_cap_m.voffset,
                fg_color=self.wcfg["font_color_caption"],
                bg_color=self.wcfg["background_color_caption"],
                count=3,
            )
            texts = (
                self.wcfg["caption_text_slower"],
                self.wcfg["caption_text_leader"],
                self.wcfg["caption_text_faster"],
            )
            for cap_temp, cap_text in zip(cap_temps, texts):
                cap_temp.text = cap_text
            self.add_column(layout, cap_temps, 0)

        # Class name
        if self.wcfg["show_class"]:
            self.bar_classes = self.set_rawtext(
                text=TEXT_PLACEHOLDER,
                fixed_width=style_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_class"],
                bg_color=self.wcfg["background_color_class"],
                count=3,
            )
            self.add_column(layout, self.bar_classes, 1)

        # Estimated laps
        if self.wcfg["show_estimated_laps"]:
            self.decimals_laps = max(self.wcfg["decimal_places_estimated_laps"], 0)
            self.bar_style_laps = (
                (
                    self.wcfg["font_color_estimated_laps"],
                    self.wcfg["background_color_estimated_laps"],
                ),
                (
                    self.wcfg["font_color_traffic_highlight"],
                    self.wcfg["background_color_traffic_highlight"],
                ),
            )
            self.bar_laps = self.set_rawtext(
                text=TEXT_PLACEHOLDER,
                fixed_width=style_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_estimated_laps"],
                bg_color=self.wcfg["background_color_estimated_laps"],
                count=3,
            )
            self.add_column(layout, self.bar_laps, 2)

        # Time interval
        if self.wcfg["show_time_interval"]:
            self.decimals_time = max(self.wcfg["decimal_places_time_interval"], 0)
            self.bar_time = self.set_rawtext(
                text=TEXT_PLACEHOLDER,
                fixed_width=style_width,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_time_interval"],
                bg_color=self.wcfg["background_color_time_interval"],
                count=3,
            )
            self.add_column(layout, self.bar_time, 3)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        veh_data = minfo.vehicles.dataSet
        (
            (ahead_overtake_laps, ahead_overtake_timegap, ahead_overtake_index),
            (leader_overtake_laps, leader_overtake_timegap, leader_overtake_index),
            (behind_overtake_laps, behind_overtake_timegap, behind_overtake_index),
        ) = traffic_cars()

        if self.wcfg["show_class"]:
            if self.show_slower_ahead:
                self.update_class(self.bar_classes[0], *class_and_driver(veh_data, ahead_overtake_index))
            if self.show_race_leader:
                self.update_class(self.bar_classes[1], *class_and_driver(veh_data, leader_overtake_index))
            if self.show_faster_behind:
                self.update_class(self.bar_classes[2], *class_and_driver(veh_data, behind_overtake_index))

        if self.wcfg["show_estimated_laps"]:
            plr_lap_progress = 1 - player_vehicle().currentLapProgress
            if ahead_overtake_index >= 0:
                opt_lap_progress = 1 - veh_data[ahead_overtake_index].currentLapProgress
            else:
                opt_lap_progress = 1.0
            if self.show_slower_ahead:
                self.update_laps(self.bar_laps[0], ahead_overtake_laps, opt_lap_progress)
            if self.show_race_leader:
                self.update_laps(self.bar_laps[1], leader_overtake_laps, plr_lap_progress)
            if self.show_faster_behind:
                self.update_laps(self.bar_laps[2], behind_overtake_laps, plr_lap_progress)

        if self.wcfg["show_time_interval"]:
            if self.show_slower_ahead:
                self.update_time(self.bar_time[0], ahead_overtake_timegap)
            if self.show_race_leader:
                self.update_time(self.bar_time[1], leader_overtake_timegap)
            if self.show_faster_behind:
                self.update_time(self.bar_time[2], behind_overtake_timegap)

    # GUI update methods
    def update_laps(self, target, laps, lap_progress):
        """Traffic laps, keyed on text & highlight shown (changes too small to show never repaint)"""
        if laps > 0:
            text = f"{laps:.{self.decimals_laps}f}"[:self.lap_width].strip(".")
            text = f"{text}L"
        else:
            text = TEXT_PLACEHOLDER
        highlight = self.wcfg["enable_traffic_highlight_from_current_lap"] and 0 < laps <= lap_progress
        if target.last != (text, highlight):
            target.last = (text, highlight)
            target.text = text
            if self.wcfg["enable_traffic_highlight_from_current_lap"]:
                target.fg, target.bg = self.bar_style_laps[highlight]
            target.update()

    def update_time(self, target, data):
        """Time interval, keyed on text shown"""
        if data != 0:
            text = f"{abs(data):.{self.decimals_time}f}"[:self.lap_width].strip(".")
            text = f"{text}s"
        else:
            text = TEXT_PLACEHOLDER
        if target.last != text:
            target.last = text
            target.text = text
            target.update()

    def update_class(self, target, *data):
        """Vehicle class"""
        if target.last != data:
            target.last = data
            text, bg_color = self.set_class_style(data[0])
            if self.wcfg["show_driver_name_instead_of_class"]:
                text = data[1]
                if not text:
                    text = TEXT_PLACEHOLDER
                elif self.wcfg["driver_name_shorten"]:
                    text = shorten_driver_name(text)
                if self.wcfg["driver_name_uppercase"]:
                    text = text.upper()
            target.text = text[:self.cls_width]
            target.fg, target.bg = (self.wcfg["font_color_class"], bg_color)
            target.update()

    def set_class_style(self, class_name: str):
        """Compare vehicle class name with user defined dictionary"""
        style = self.cfg.user.classes.get(class_name)
        if style is not None:
            return style["alias"], style["color"]
        if class_name:
            return class_name, random_color_class(class_name)
        return TEXT_PLACEHOLDER, self.wcfg["background_color_class"]

    def add_column(self, layout, bar_temp, row_index):
        """Add column"""
        layout.addWidget(bar_temp[0], row_index, self.wcfg["display_order_slower"])
        if not self.show_slower_ahead:
            bar_temp[0].hide()
        layout.addWidget(bar_temp[1], row_index, self.wcfg["display_order_leader"])
        if not self.show_race_leader:
            bar_temp[1].hide()
        layout.addWidget(bar_temp[2], row_index, self.wcfg["display_order_faster"])
        if not self.show_faster_behind:
            bar_temp[2].hide()


def traffic_cars() -> tuple[tuple[float, float, int], tuple[float, float, int], tuple[float, float, int]]:
    """Slower car ahead player catches first, race leader, faster car behind catching player first, for classic &
    modern design: (laps until caught, time gap, car index), laps & gap 0 if none or unknown (index -1: no car);
    cars in pits left out, leader too while player leads (no car to watch)"""
    veh_data = minfo.vehicles.dataSet
    player_laptime = api.read.timing.estimated_laptime()
    leader_index = minfo.vehicles.leaderIndex
    if leader_index == minfo.vehicles.playerIndex:
        leader_index = -1
    ahead = behind = (MAX_SECONDS, 0.0, -1)
    leader = (0.0, 0.0, leader_index)
    if player_laptime > 0:
        relative = minfo.relative
        for gap, index in relative.relativeAhead:
            if index < 0 or veh_data[index].inPit:  # index -1: empty list entry
                continue
            avg = relative.relativeDeltaAhead[index].long
            laps = gap / avg / player_laptime if avg > 0 else 0
            if 0 < laps < ahead[0]:
                ahead = (laps, gap, index)
        for gap, index in relative.relativeBehind:
            if index < 0 or veh_data[index].inPit:
                continue
            avg = relative.relativeDeltaBehind[index].long
            laps = -gap / avg / player_laptime if avg > 0 else 0
            if 0 < laps < behind[0]:
                behind = (laps, gap, index)
            if index == leader_index:
                leader = (laps, gap, index)
    if ahead[0] >= MAX_SECONDS:
        ahead = (0.0, 0.0, -1)
    if behind[0] >= MAX_SECONDS:
        behind = (0.0, 0.0, -1)
    return ahead, leader, behind


def class_and_driver(veh_data: Sequence[VehicleDataSet], index: int) -> tuple[str, str]:
    """Class & driver name of car, empty if no car (index -1: no leader, no car ahead or behind)"""
    if index < 0:
        return "", ""
    veh_info = veh_data[index]
    return veh_info.vehicleClass, veh_info.driverName
