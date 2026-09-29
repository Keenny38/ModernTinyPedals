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
Black box widget, dynamic size

Pure logic, no Qt:
- Presence: which optional blocks the current car & data actually have (energy gauge,
  battery, ABS, TC, stint comparison), so the layout only reserves room for what can be shown.
  Starts compact, a block appears once its data exists.
- Debounce: a presence change is applied only once it stayed the same for a delay, so data
  arriving in steps (session start, car change) never makes the widget jump several times.
- Fit: content scaled uniformly into a fixed width and/or height, centered, never distorted.
- Anchor: the chosen corner stays in place on screen when the size changes.
"""

from __future__ import annotations

import math
from typing import NamedTuple

RESIZE_ANCHORS = ("Top Left", "Top Center", "Top Right", "Bottom Left", "Bottom Center", "Bottom Right")


class Presence(NamedTuple):
    """Optional blocks the layout makes room for"""

    fuel_row: bool = True
    energy_row: bool = True
    battery: bool = True
    abs: bool = True
    tc: bool = True
    stint: bool = True


# Auto resize starts compact: a block appears once its data exists, so nothing empty is shown
# in menus or before data arrives. Fuel gauge is shown at once, fuel data exists for every car.
COMPACT_START = Presence(fuel_row=True, energy_row=False, battery=False, abs=False, tc=False, stint=False)


class Debounce:
    """Return a new value only once it stayed unchanged for delay seconds

    Args:
        value: value applied at start.
        delay: seconds a new value must stay unchanged, 0 applies at once.
    """

    __slots__ = ("applied", "pending", "since", "delay")

    def __init__(self, value, delay: float):
        self.applied = value
        self.pending = value
        self.since = 0.0
        self.delay = max(delay, 0.0)

    def update(self, value, now: float):
        """Feed current value, return value to apply now"""
        if value == self.applied:
            self.pending = value
            return self.applied
        if value != self.pending:  # new candidate, start waiting
            self.pending = value
            self.since = now
        if now - self.since >= self.delay:
            self.applied = value
        return self.applied


class Fit(NamedTuple):
    """Widget size and content transform"""

    width: int
    height: int
    scale: float
    offset_x: float
    offset_y: float


def fit_content(natural_w: float, natural_h: float, fixed_w: float = 0, fixed_h: float = 0) -> Fit:
    """Scale content uniformly to fit fixed width and/or height (0 = follow content), centered"""
    natural_w, natural_h = max(natural_w, 1), max(natural_h, 1)
    fixed_w = fixed_w if math.isfinite(fixed_w) and fixed_w > 0 else 0
    fixed_h = fixed_h if math.isfinite(fixed_h) and fixed_h > 0 else 0
    if fixed_w and fixed_h:
        scale = min(fixed_w / natural_w, fixed_h / natural_h)
        width, height = fixed_w, fixed_h
    elif fixed_w:
        scale = fixed_w / natural_w
        width, height = fixed_w, natural_h * scale
    elif fixed_h:
        scale = fixed_h / natural_h
        width, height = natural_w * scale, fixed_h
    else:
        return Fit(round(natural_w), round(natural_h), 1.0, 0.0, 0.0)
    width, height = max(round(width), 1), max(round(height), 1)
    return Fit(width, height, scale, (width - natural_w * scale) / 2, (height - natural_h * scale) / 2)


def anchored_position(x: int, y: int, old_w: int, old_h: int, new_w: int, new_h: int, anchor: str) -> tuple[int, int]:
    """Widget position keeping anchor point in place when size changes"""
    if anchor.endswith("Right"):
        x += old_w - new_w
    elif anchor.endswith("Center"):
        x += round((old_w - new_w) / 2)
    if anchor.startswith("Bottom"):
        y += old_h - new_h
    return x, y
