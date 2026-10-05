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
Suspension position Widget, modern design

Suspension position per wheel with gauge (compression orange, extension blue), highlighted
when beyond maximum position range, third spring position mark (front & rear).
"""

from __future__ import annotations

from ...api_control import api
from ...module_info import minfo
from .gauge_quad import GaugeQuad


class Realtime(GaugeQuad):
    """Draw widget"""

    options = (
        *GaugeQuad.common_options, "position_maximum_range", "show_maximum_position_range",
        "show_third_spring_position_mark",
    )
    label = "Suspension"

    def setup(self):
        self.max_range = max(int(self.wcfg["position_maximum_range"]), 10)

    def read(self) -> tuple:
        theme = self.theme
        positions = minfo.wheels.currentSuspensionPosition
        maximums = minfo.wheels.maxSuspensionPosition if self.wcfg["show_maximum_position_range"] else (0, 0, 0, 0)
        if self.wcfg["show_third_spring_position_mark"]:
            thirds = tuple(abs(value) / self.max_range for value in api.read.wheel.third_spring_deflection())
        else:
            thirds = (-1.0,) * 4
        tiles = []
        for position, maximum, third in zip(positions, maximums, thirds):
            exceeded = 0 < maximum <= position
            color = theme.warning if position >= 0 else theme.blue
            tiles.append(self.gauge(abs(position), position, abs(position) / self.max_range, color, exceeded, third))
        return tuple(tiles)
