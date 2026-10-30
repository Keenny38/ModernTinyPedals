#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
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
Tyre load Widget, modern design

Load per tyre (or share of total load), gauge of load share (full at 50%), warning when load is low.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ... import calculation as calc
from ...api_control import api
from ..tyre_load import FULL_GAUGE_RATIO
from .gauge_quad import GaugeQuad

if TYPE_CHECKING:
    from ...template.widget_config_types import TyreLoadConfig


class Realtime(GaugeQuad):
    """Draw widget"""

    wcfg: TyreLoadConfig

    options = (*GaugeQuad.common_options, "low_load_threshold", "show_tyre_load_ratio")
    label = "Tyre load"
    sample = "88888"

    def setup(self):
        self.low = self.wcfg["low_load_threshold"]  # percent with load ratio shown, else Newtons
        self.show_ratio = self.wcfg["show_tyre_load_ratio"]

    def read(self) -> tuple:
        loads = api.read.tyre.load()
        total = sum(loads)
        tiles = []
        for load in loads:
            ratio = calc.part_to_whole_ratio(load, total) * 100
            value = ratio if self.show_ratio else load
            tiles.append(self.gauge(value, value, ratio / FULL_GAUGE_RATIO, self.theme.accent, value <= self.low))
        return tuple(tiles)
