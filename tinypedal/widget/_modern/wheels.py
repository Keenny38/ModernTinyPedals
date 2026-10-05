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
Modern overlay design: tyre compound tracking & heatmaps shared by wheel widgets
"""

from __future__ import annotations

from PySide6.QtGui import QColor

from ...api_control import api
from ...template.setting_heatmap import HEATMAP_DEFAULT_TYRE
from ...userfile.heatmap import select_compound_color, select_compound_symbol, select_tyre_heatmap_name
from .quad import heatmap


class TyreCompounds:
    """Tyre compounds read while in pits (or when pit state changes), heatmap per wheel"""

    def __init__(self, auto_heatmap: bool = True, heatmap_name: str = HEATMAP_DEFAULT_TYRE):
        self.auto_heatmap = auto_heatmap
        self.heatmap_name = heatmap_name
        self.last_in_pits = -1
        self.names: tuple[str, ...] = ("", "", "", "")
        fixed = heatmap(heatmap_name, HEATMAP_DEFAULT_TYRE)
        self.heat = [fixed] * 4
        self.badges: tuple = ((), ())  # front & rear (symbol, QColor)

    def update(self) -> bool:
        """Read compounds, True if changed"""
        in_pits = api.read.vehicle.in_pits()
        if not in_pits and self.last_in_pits == in_pits:
            return False
        self.last_in_pits = in_pits
        names = api.read.tyre.compound_class()
        if names == self.names:
            return False
        self.names = names
        if self.auto_heatmap:
            self.heat = [heatmap(select_tyre_heatmap_name(name), HEATMAP_DEFAULT_TYRE) for name in names]
        self.badges = (badge(names[0]), badge(names[2]))
        return True


def badge(name: str) -> tuple[str, QColor]:
    """Compound symbol & color"""
    return select_compound_symbol(name), QColor(select_compound_color(name))
