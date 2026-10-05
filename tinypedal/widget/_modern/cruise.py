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
Cruise Widget, modern design

Compass heading, elevation, odometer, distance into lap.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_common import COMPASS_BEARINGS
from ...module_info import minfo
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_compass", "show_elevation", "show_odometer", "odometer_maximum_digits",
        "show_distance_into_lap",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit_cfg = self.cfg.units
        self.unit_dist = units.set_unit_distance(unit_cfg["distance_unit"])
        self.symbol_dist = units.set_symbol_distance(unit_cfg["distance_unit"])
        self.unit_odm = units.set_unit_distance(unit_cfg["odometer_unit"])
        self.symbol_odm = units.set_symbol_distance(unit_cfg["odometer_unit"])
        digits = min(max(int(wcfg["odometer_maximum_digits"]), 1), 12)
        self.odm_decimals = 0 if self.symbol_odm == "m" else 1
        self.odm_range = int(digits * "9")
        items = (
            ("compass", "Heading", "888° NW"),
            ("elevation", "Elevation", f"8888{self.symbol_dist}"),
            ("odometer", "Odometer", "8" * digits + self.symbol_odm),
            ("distance_into_lap", "Lap dist.", f"88888{self.symbol_dist}"),
        )
        stats = [Stat(key, label, sample) for key, label, sample in items if wcfg[f"show_{key}"]]
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        values = []
        for key in self.keys:
            if key == "compass":
                degree = 180 - calc.degrees(api.read.vehicle.orientation_yaw_radians())
                values.append(Value(f"{degree:03.0f}° {calc.select_grade(COMPASS_BEARINGS, degree)}"))
            elif key == "elevation":
                values.append(Value(f"{self.unit_dist(api.read.vehicle.position_vertical()):.0f}{self.symbol_dist}"))
            elif key == "odometer":
                distance = min(self.unit_odm(int(minfo.stats.metersDriven)), self.odm_range)
                values.append(Value(f"{distance:.{self.odm_decimals}f}{self.symbol_odm}", self.theme.text_dim))
            elif key == "distance_into_lap":
                values.append(Value(f"{self.unit_dist(minfo.delta.lapDistance):.0f}{self.symbol_dist}"))
        self.refresh(tuple(values))
