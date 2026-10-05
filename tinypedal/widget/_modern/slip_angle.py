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
Slip angle Widget, modern design

Slip angle per tyre with gauge, gauge color by balance: oversteer (blue), understeer (orange).
"""

from __future__ import annotations

from ...module_info import minfo
from .gauge_quad import GaugeQuad


class Realtime(GaugeQuad):
    """Draw widget"""

    options = (
        *GaugeQuad.common_options, "slip_angle_maximum_range",
        "minimum_oversteer_slip_angle_difference", "minimum_understeer_slip_angle_difference",
    )
    label = "Slip angle"
    sample = "88"

    def setup(self):
        self.max_range = max(int(self.wcfg["slip_angle_maximum_range"]), 1)

    def read(self) -> tuple:
        theme = self.theme
        difference = minfo.wheels.slipAngleDifference
        if difference > self.wcfg["minimum_understeer_slip_angle_difference"]:
            color = theme.warning
        elif difference < self.wcfg["minimum_oversteer_slip_angle_difference"]:
            color = theme.blue
        else:
            color = theme.text_dim
        return tuple(
            self.gauge(abs(value), abs(value), abs(value) / self.max_range, color)
            for value in minfo.wheels.slipAngle
        )
