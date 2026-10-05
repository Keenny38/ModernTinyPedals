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
Ride height Widget, modern design

Ride height per wheel with gauge, warning below bottoming height.
"""

from __future__ import annotations

from ...api_control import api
from .gauge_quad import GaugeQuad

CORNERS = ("front_left", "front_right", "rear_left", "rear_right")


class Realtime(GaugeQuad):
    """Draw widget"""

    options = (
        *GaugeQuad.common_options, "ride_height_maximum_range",
        *(f"bottoming_height_{corner}" for corner in CORNERS),
    )
    label = "Ride height"

    def setup(self):
        self.max_range = max(int(self.wcfg["ride_height_maximum_range"]), 10)
        self.bottoming = tuple(self.wcfg[f"bottoming_height_{corner}"] for corner in CORNERS)

    def read(self) -> tuple:
        theme = self.theme
        return tuple(
            self.gauge(value, value, value / self.max_range, theme.positive, value < bottom)
            for value, bottom in zip(api.read.wheel.ride_height(), self.bottoming)
        )
