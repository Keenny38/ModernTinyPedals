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

from functools import lru_cache

from PySide6.QtGui import QColor

from ...api_control import api
from ...template.setting_heatmap import HEATMAP_DEFAULT_TYRE
from ...userfile.heatmap import select_compound_color, select_compound_symbol, select_tyre_heatmap_name
from .quad import heatmap, reload_heatmaps

# Heatmap centered on optimal temperature: (offset from optimal in Celsius, color), same colors
# as tyre_optimal_* heatmap presets (cold blue, ideal green, hot red)
OPTIMAL_STEPS = (
    (-30, "#48F"), (-20, "#4FF"), (-10, "#4F8"), (0, "#4F4"), (10, "#8F4"), (20, "#FF4"), (30, "#F84"),
    (40, "#F44"),
)


@lru_cache(maxsize=32)
def heatmap_around(optimal: int) -> tuple:
    """Heatmap steps ((value, QColor), ...) centered on optimal temperature (Celsius)"""
    return ((-273.0, QColor("#44F")), *((float(optimal + offset), QColor(color)) for offset, color in OPTIMAL_STEPS))


class TyreCompounds:
    """Tyre compounds read while in pits (or when pit state changes), heatmap per wheel

    Heatmap of a wheel: centered on optimal temperature given by game (LMU) if optimal option,
    else heatmap of compound (auto matching), else fixed heatmap.
    """

    def __init__(self, auto_heatmap: bool = True, heatmap_name: str = HEATMAP_DEFAULT_TYRE,
                 optimal_heatmap: bool = False):
        reload_heatmaps()  # new widget: latest saved heatmaps
        self.auto_heatmap = auto_heatmap
        self.heatmap_name = heatmap_name
        self.use_optimal = optimal_heatmap
        self.last_in_pits = -1
        self.names: tuple[str, ...] = ("", "", "", "")
        self.optimal: tuple[int, ...] = (0, 0, 0, 0)
        fixed = heatmap(heatmap_name, HEATMAP_DEFAULT_TYRE)
        self.compound_heat = [fixed] * 4
        self.heat = [fixed] * 4
        # Front & rear center badges: ((symbol, QColor),) or left & right ones if they differ
        self.badges: tuple = ((), ())

    def update(self) -> bool:
        """Read compounds (& optimal temperatures), True if changed"""
        changed = self.update_compounds()
        if self.use_optimal:
            optimal = tuple(round(value) if value > 0 else 0 for value in api.read.tyre.optimal_temperature())
            if optimal != self.optimal:
                self.optimal = optimal
                changed = True
        if changed:
            self.heat = [
                heatmap_around(optimal) if optimal > 0 else heat
                for optimal, heat in zip(self.optimal, self.compound_heat)
            ]
        return changed

    def update_compounds(self) -> bool:
        """Read compounds while in pits or when pit state changes, True if changed"""
        in_pits = api.read.vehicle.in_pits()
        if not in_pits and self.last_in_pits == in_pits:
            return False
        self.last_in_pits = in_pits
        names = api.read.tyre.compound_class()
        if names == self.names:
            return False
        self.names = names
        if self.auto_heatmap:
            self.compound_heat = [heatmap(select_tyre_heatmap_name(name), HEATMAP_DEFAULT_TYRE) for name in names]
        self.badges = (axle_badges(names[0], names[1]), axle_badges(names[2], names[3]))
        return True


def badge(name: str) -> tuple[str, QColor]:
    """Compound symbol & color"""
    return select_compound_symbol(name), QColor(select_compound_color(name, text=False))  # badge


def axle_badges(left: str, right: str) -> tuple:
    """Compound badge of axle, left & right badges if wheels have different compounds"""
    if left == right:
        return (badge(left),)
    return badge(left), badge(right)
