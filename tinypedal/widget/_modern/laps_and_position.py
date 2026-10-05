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
Laps and position Widget, modern design

Lap progress (with final lap highlight), overall & class position, track limits points,
places gained since start.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from ...module_info import minfo
from .base import DASH, ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_laps", "show_predicted_extra_laps", "show_position_overall",
        "show_position_in_class", "show_track_limits_points", "show_position_change", "show_position_change_in_class",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        stats = []
        if wcfg["show_laps"]:
            sample = "888.88/~888.88 (+8)" if wcfg["show_predicted_extra_laps"] else "888.88/~888.88"
            stats.append(Stat("laps", "Lap", sample))
        if wcfg["show_position_overall"]:
            stats.append(Stat("position_overall", "Position", "88/88", "strong"))
        if wcfg["show_position_in_class"]:
            stats.append(Stat("position_in_class", "Class", "88/88", "strong"))
        if wcfg["show_track_limits_points"]:
            stats.append(Stat("track_limits", "Track limits", "8.88/88"))
        if wcfg["show_position_change"]:
            stats.append(Stat("position_change", "Gained", "▲88", "strong"))
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)
        self.class_position = (0, 0, 0, 0)  # place, total vehicles -> position, class total

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        values = []
        place = api.read.vehicle.place()
        total = api.read.vehicle.total_vehicles()
        for key in self.keys:
            if key == "laps":
                values.append(self.laps_value())
            elif key == "position_overall":
                values.append(Value(f"{place}/{total}"))
            elif key == "position_in_class":
                position, class_total = self.position_in_class(place, total)
                values.append(Value(f"{position}/{class_total}"))
            elif key == "track_limits":
                points = api.read.session.cut_points()
                limit = api.read.session.limits_points() * api.read.session.in_race()
                text_limit = f"{limit:.0f}" if limit > 0 else DASH
                color = theme.negative if limit > 0 and points >= limit - 1 else (theme.warning if points > 0 else theme.text_dim)
                values.append(Value(f"{points:.2f}".rstrip("0").rstrip(".") + f"/{text_limit}", color))
            elif key == "position_change":
                veh = minfo.vehicles.dataSet[minfo.vehicles.playerIndex]
                if self.wcfg["show_position_change_in_class"]:
                    places = veh.qualifyInClass - veh.positionInClass
                else:
                    places = veh.qualifyOverall - veh.positionOverall
                if places > 0:
                    values.append(Value(f"▲{places}", theme.positive))
                elif places < 0:
                    values.append(Value(f"▼{-places}", theme.negative))
                else:
                    values.append(Value(DASH, theme.text_faint))
        self.refresh(tuple(values))

    def laps_value(self) -> Value:
        """Laps done / total laps, last lap highlighted"""
        lap_into = calc.lap_progress_correction(api.read.lap.progress(), api.read.timing.current_laptime())
        lap_num = api.read.lap.number()
        lap_max = api.read.lap.maximum()
        if api.read.session.finish_type(minfo.vehicles.finishAsLap):
            text_total = f"{lap_max:.2f}"
        else:
            session_time = api.read.session.remaining() - minfo.vehicles.finishTimeOffset
            text_total = f"~{lap_num + calc.end_timer_laps_remain(lap_into, minfo.delta.lapTimePace, session_time):.2f}"
        text = f"{lap_num + lap_into:.2f}/{text_total}"
        if self.wcfg["show_predicted_extra_laps"]:
            text = f"{text} ({minfo.vehicles.finishLapOffset:+.0f})"
        final = lap_num - lap_max >= -1
        return Value(text, fill=self.theme.tint(self.theme.warning, 60) if final else None)

    def position_in_class(self, place: int, total: int) -> tuple[int, int]:
        """Player position in class & class size, computed again only if place or field changes"""
        if self.class_position[:2] != (place, total):
            player_class = api.read.vehicle.class_name()
            class_total = 0
            higher = 0
            for index in range(total):
                if api.read.vehicle.class_name(index) == player_class:
                    class_total += 1
                    if api.read.vehicle.place(index) > place:
                        higher += 1
            self.class_position = (place, total, class_total - higher, class_total)
        return self.class_position[2], self.class_position[3]
