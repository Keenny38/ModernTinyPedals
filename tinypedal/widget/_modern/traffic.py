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
Traffic Widget, modern design

Laps until player catches slower car ahead, until race leader laps player, until faster car
behind catches player; highlighted when it happens within current lap.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...api_control import api
from ...const_common import MAX_SECONDS
from ...formatter import shorten_driver_name
from ...module_info import minfo
from .base import ModernOverlay
from .rows import DASH, class_style
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_race_leader", "show_slower_ahead", "show_faster_behind",
        "show_class", "show_driver_name_instead_of_class", "driver_name_shorten", "driver_name_uppercase",
        "show_estimated_laps", "decimal_places_estimated_laps", "show_time_interval", "decimal_places_time_interval",
        "enable_traffic_highlight_from_current_lap",
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
        self.keys = tuple(key for key, _, show in items if show)
        sample = f"8.{'8' * self.dec_laps}L" if wcfg["show_estimated_laps"] else f"88.{'8' * self.dec_time}s"
        sub_sample = "M. Laurent  88.88s" if wcfg["show_driver_name_instead_of_class"] else "LMGT3  88.88s"
        stats = [Stat(key, label, sample, "strong", sub_sample=sub_sample) for key, label, show in items if show]
        self.show_sub = wcfg["show_class"] or (wcfg["show_estimated_laps"] and wcfg["show_time_interval"])
        width, height = self.build_stats(stats, show_sub=self.show_sub)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        veh_data = minfo.vehicles.dataSet
        player_index = minfo.vehicles.playerIndex
        player_laptime = api.read.timing.estimated_laptime()
        ahead = (MAX_SECONDS, 0.0, -1)  # laps, time gap, index
        behind = (MAX_SECONDS, 0.0, -1)
        leader_index = minfo.vehicles.leaderIndex
        leader = (0.0, 0.0, leader_index)
        if player_laptime > 0:
            delta_ahead = minfo.relative.relativeDeltaAhead
            delta_behind = minfo.relative.relativeDeltaBehind
            for gap, index in minfo.relative.relativeAhead:
                if veh_data[index].inPit:
                    continue
                avg = delta_ahead[index].long
                laps = gap / avg / player_laptime if avg > 0 else 0
                if 0 < laps < ahead[0]:
                    ahead = (laps, gap, index)
            for gap, index in minfo.relative.relativeBehind:
                if veh_data[index].inPit:
                    continue
                avg = delta_behind[index].long
                laps = -gap / avg / player_laptime if avg > 0 else 0
                if 0 < laps < behind[0]:
                    behind = (laps, gap, index)
                if index == leader_index:
                    leader = (laps, gap, index)
        if ahead[0] >= MAX_SECONDS:
            ahead = (0.0, 0.0, ahead[2])
        if behind[0] >= MAX_SECONDS:
            behind = (0.0, 0.0, behind[2])
        player_progress = 1 - veh_data[player_index].currentLapProgress
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
        text_time = f"{abs(gap):.{self.dec_time}f}s" if gap else DASH
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
            sub = f"{name}  {extra}".strip() if name else extra
            sub_color = color
        return Value(main, theme.warning if soon else theme.text,
                     theme.tint(theme.warning, 50) if soon else None, sub, sub_color)
