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
Suspension force Widget, modern design

Suspension force per wheel (or share of total force) with gauge of force share.
"""

from __future__ import annotations

from ... import calculation as calc
from ...api_control import api
from .gauge_quad import GaugeQuad


class Realtime(GaugeQuad):
    """Draw widget"""

    options = (*GaugeQuad.common_options, "show_force_ratio")
    label = "Suspension force"
    sample = "88888"

    def read(self) -> tuple:
        forces = api.read.wheel.suspension_force()
        total = sum(forces)
        tiles = []
        for force in forces:
            ratio = calc.part_to_whole_ratio(force, total) * 100
            value = ratio if self.wcfg["show_force_ratio"] else force
            tiles.append(self.gauge(value, value, ratio / 50, self.theme.best))
        return tuple(tiles)
