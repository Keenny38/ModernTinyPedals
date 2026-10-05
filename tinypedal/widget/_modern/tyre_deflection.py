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
Tyre deflection Widget, modern design

Vertical deflection per tyre with gauge, warning when tyre lifts off.
"""

from __future__ import annotations

from ...api_control import api
from .gauge_quad import GaugeQuad


class Realtime(GaugeQuad):
    """Draw widget"""

    options = (*GaugeQuad.common_options, "deflection_maximum_range", "lift_off_threshold")
    label = "Deflection"

    def setup(self):
        self.max_range = max(int(self.wcfg["deflection_maximum_range"]), 10)
        self.lift_off = self.wcfg["lift_off_threshold"]

    def read(self) -> tuple:
        theme = self.theme
        return tuple(
            self.gauge(value, value, value / self.max_range, theme.caution, value <= self.lift_off)
            for value in api.read.tyre.vertical_deflection()
        )
