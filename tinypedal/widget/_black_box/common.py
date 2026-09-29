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
Black box widget, shared constants
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QColor

LAYOUT_NORMAL = 0  # info column between tyres
LAYOUT_VERTICAL = 1  # info column below tyres
LAYOUT_COMPACT = 2  # tyres & brakes only

CENTER_ITEMS = (
    "abs", "tc", "brake_bias", "brake_migration", "locking", "delta", "laptime",
    "pit_limiter", "gear", "speed", "rpm", "pedals", "brake_heat",
)

FONT_CACHE_SIZE = 1024  # fitted fonts kept per widget, cleared when full


@lru_cache(maxsize=256)
def qcolor(value: str) -> QColor:
    """Shared QColor per color string, instead of one new object per draw call (never mutated)"""
    return QColor(value)
