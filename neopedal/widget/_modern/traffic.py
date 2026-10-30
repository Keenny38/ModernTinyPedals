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
Traffic Widget, modern design

Laps until player catches slower car ahead, until race leader laps player, until faster car
behind catches player; highlighted when it happens within current lap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QPainter

from ...formatter import shorten_driver_name
from ...module_info import minfo
from .._common import player_vehicle
from ..traffic import traffic_cars
from .base import ModernOverlay, display_order_options
from .rows import DASH, class_style
from .stats import Stat, StatsMixin, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import TrafficConfig


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: TrafficConfig

    options = (
        "font_size", "show_caption", "show_race_leader", "show_slower_ahead", "show_faster_behind",
        "show_class", "show_driver_name_instead_of_class", "driver_name_shorten", "driver_name_uppercase",
        "show_estimated_laps", "decimal_places_estimated_laps", "show_time_interval", "decimal_places_time_interval",
        "enable_traffic_highlight_from_current_lap", *display_order_options("traffic"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.dec_laps = max(int(wcfg["decimal_places_estimated_laps"]), 0)
        self.dec_time = max(int(wcfg["decimal_places_time_interval"]), 0)
        items = (
            ("slower", "Slower ahead", wcfg["show_slower_ahead"]),
            ("leader", "Leader", wcfg["show_race_leader"]),
            ("faster", "Faster behind", wcfg["show_faster_behind"]),
        )
        # Class as badge (as class column of driver lists), driver name as text in class color
        self.class_badge = wcfg["show_class"] and not wcfg["show_driver_name_instead_of_class"]
        name_sample = "M. Laurent" if wcfg["show_driver_name_instead_of_class"] else "LMGT3"
        time_sample = f"88.{'8' * self.dec_time}"  # time gap without unit, as time intervals of driver lists
        # Neither laps nor time interval shown: car name or class as value (as classic design)
        self.show_values = bool(wcfg["show_estimated_laps"] or wcfg["show_time_interval"])
        badge_sample = ""
        if not self.show_values:
            sample, sub_sample = name_sample, ""
        else:
            sample = f"8.{'8' * self.dec_laps}L" if wcfg["show_estimated_laps"] else time_sample
            extra = time_sample if wcfg["show_estimated_laps"] and wcfg["show_time_interval"] else ""
            if self.class_badge:
                sub_sample, badge_sample = extra, name_sample
            else:
                sub_sample = f"{name_sample}  {extra}".strip() if wcfg["show_class"] else extra
        stats = [Stat(key, label, sample, "strong", sub_sample=sub_sample, badge_sample=badge_sample)
                 for key, label, show in items if show]
        stats = self.display_ordered(stats)
        self.keys = tuple(stat.key for stat in stats)
        self.show_sub = self.show_values and (
            wcfg["show_class"] or (wcfg["show_estimated_laps"] and wcfg["show_time_interval"]))
        width, height = self.build_stats(stats, show_sub=self.show_sub)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        veh_data = minfo.vehicles.dataSet
        ahead, leader, behind = traffic_cars()  # laps, time gap, index
        player_progress = 1 - player_vehicle().currentLapProgress
        ahead_progress = 1 - veh_data[ahead[2]].currentLapProgress if ahead[2] >= 0 else 0
        data = {
            "slower": (ahead, ahead_progress),
            "leader": (leader, player_progress),
            "faster": (behind, player_progress),
        }
        self.refresh(tuple(self.traffic_value(*data[key]) for key in self.keys))

    def traffic_value(self, traffic: tuple, lap_progress: float) -> Value:
        """Laps (or time) until traffic, car name or class"""
        wcfg = self.wcfg
        theme = self.theme
        laps, gap, index = traffic
        text_laps = f"{laps:.{self.dec_laps}f}L" if laps > 0 else DASH
        text_time = f"{abs(gap):.{self.dec_time}f}" if gap else DASH
        main, extra = (text_laps, text_time) if wcfg["show_estimated_laps"] else (text_time, "")
        if not wcfg["show_time_interval"]:
            extra = ""
        soon = wcfg["enable_traffic_highlight_from_current_lap"] and 0 < laps <= lap_progress
        sub, sub_color = extra, theme.text_dim
        data_set = minfo.vehicles.dataSet
        if wcfg["show_class"] and 0 <= index < len(data_set):
            veh = data_set[index]
            alias, color = class_style(self.cfg, veh.vehicleClass, theme)
            name = alias
            if wcfg["show_driver_name_instead_of_class"]:
                name = shorten_driver_name(veh.driverName) if wcfg["driver_name_shorten"] else veh.driverName
                if wcfg["driver_name_uppercase"]:
                    name = name.upper()
            if not self.show_values:
                return Value(name or DASH, color)
            if self.class_badge and name:
                return Value(main, theme.warning if soon else theme.text,
                             theme.tint(theme.warning, 50) if soon else None,
                             extra, theme.text_dim, badge=name, badge_color=color)
            sub = f"{name}  {extra}".strip() if name else extra
            sub_color = color
        if not self.show_values:
            return Value(DASH)
        return Value(main, theme.warning if soon else theme.text,
                     theme.tint(theme.warning, 50) if soon else None, sub, sub_color)
