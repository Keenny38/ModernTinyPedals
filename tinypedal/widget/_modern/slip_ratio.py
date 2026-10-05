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
Slip ratio Widget, modern design

Slip ratio per tyre (percent) with gauge, highlighted beyond optimal range.
"""

from __future__ import annotations

from ...module_info import minfo
from .gauge_quad import GaugeQuad


class Realtime(GaugeQuad):
    """Draw widget"""

    options = (*GaugeQuad.common_options, "slip_ratio_optimal_range", "slip_ratio_maximum_range")
    label = "Slip ratio"

    def setup(self):
        self.max_range = min(max(int(self.wcfg["slip_ratio_maximum_range"]), 10), 100)
        self.optimal = self.wcfg["slip_ratio_optimal_range"]

    def read(self) -> tuple:
        theme = self.theme
        tiles = []
        for ratio in minfo.wheels.slipRatio:
            value = min(abs(ratio * 100), 100)
            critical = value > self.optimal
            tiles.append(self.gauge(value, value, value / self.max_range, theme.best if critical else theme.text_dim, critical))
        return tuple(tiles)
