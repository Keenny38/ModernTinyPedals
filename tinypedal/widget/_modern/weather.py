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
Weather Widget, modern design

Track & air temperature, rain, surface wetness (or rubber coverage while dry), each with
trend arrow (rising, falling, steady).
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import units
from ...api_control import api
from ...i18n import tr_overlay
from ...module_info import minfo
from ..weather import TrendTimer, laps_to_rubber, rubber_to_laps
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value

TREND_SIGN = ("●", "▲", "▼")  # steady, rising, falling


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_temperature", "decimal_places_temperature", "show_rain", "show_wetness",
        "show_rubber_coverage_while_dry", "rubber_median_laps", "rubber_time_scale_practice",
        "rubber_time_scale_qualifying", "rubber_time_scale_race", "starting_rubber_practice",
        "starting_rubber_qualifying", "starting_rubber_race", "show_trend", "temperature_trend_interval",
        "raininess_trend_interval", "wetness_trend_interval",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.symbol_temp = units.set_symbol_temperature(self.cfg.units["temperature_unit"])
        self.decimals = max(int(wcfg["decimal_places_temperature"]), 0)
        self.rubber_median = max(int(wcfg["rubber_median_laps"]), 100)
        self.rubber_scale = tuple(wcfg[f"rubber_time_scale_{name}"] for name in ("practice", "practice", "qualifying", "race", "race"))
        self.rubber_start = tuple(wcfg[f"starting_rubber_{name}"] for name in ("practice", "practice", "qualifying", "race", "race"))
        self.show_trend = wcfg["show_trend"]
        stats = []
        sample_temp = f"88.{'8' * self.decimals} / 88.{'8' * self.decimals}{self.symbol_temp} ▲"
        if wcfg["show_temperature"]:
            stats.append(Stat("temperature", "Track / Air", sample_temp))
        if wcfg["show_rain"]:
            stats.append(Stat("rain", "Rain", "100% ▲"))
        if wcfg["show_wetness"]:
            stats.append(Stat("wetness", "Surface", "Rubber 100% ▲"))
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats)
        self.set_size(width, height)
        self.trends = {
            "temperature": TrendTimer(wcfg["temperature_trend_interval"]),
            "rain": TrendTimer(wcfg["raininess_trend_interval"]),
            "wetness": TrendTimer(wcfg["wetness_trend_interval"]),
        }

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def trend(self, key: str, value: float, elapsed: float) -> str:
        """Trend sign suffix"""
        if not self.show_trend:
            return ""
        return f" {TREND_SIGN[self.trends[key].update(value, elapsed)]}"

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        session = api.read.session
        elapsed = api.read.timing.elapsed()
        values = []
        for key in self.keys:
            if key == "temperature":
                track = session.track_temperature()
                air = session.ambient_temperature()
                text = f"{self.unit_temp(track):.{self.decimals}f} / {self.unit_temp(air):.{self.decimals}f}{self.symbol_temp}"
                values.append(Value(text + self.trend(key, round(track + air, 1), elapsed)))
            elif key == "rain":
                rain = round(session.raininess(), 2)
                values.append(Value(f"{rain:.0%}" + self.trend(key, rain, elapsed), theme.accent if rain > 0 else None))
            elif key == "wetness":
                wet_min, wet_max, wet_avg = session.wetness()
                if wet_avg >= 0.01 or not self.wcfg["show_rubber_coverage_while_dry"]:
                    text, color = f"{tr_overlay('Wet')} {wet_avg:.0%}", theme.accent
                else:
                    session_type = session.session_type()
                    laps = rubber_to_laps(self.rubber_start[session_type], self.rubber_median)
                    if self.rubber_scale[session_type] > 0:
                        laps += minfo.vehicles.totalCompletedLaps * self.rubber_scale[session_type]
                    text, color = f"{tr_overlay('Rubber')} {laps_to_rubber(laps, self.rubber_median):.0%}", None
                values.append(Value(text + self.trend(key, wet_min + wet_max + wet_avg, elapsed), color))
        self.refresh(tuple(values))
