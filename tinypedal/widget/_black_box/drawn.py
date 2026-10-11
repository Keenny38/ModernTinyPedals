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
Black box widget, change keys of drawn values

Each part (see regions) builds its key from what it draws, with the helpers its drawing code uses:
texts as formatted for display, colors (or what picks them), lengths as drawn. Equal keys draw the same pixels,
so a reading moving below its display precision repaints nothing, and any pixel change repaints.

Continuous motion (wheel angle, suspension travel) is drawn on a grid of 1/MOTION_GRID device pixel and
damper tint in 8 bit color steps: below that, sensor noise & slow filters would repaint wheels every
update for changes the eye cannot see.
"""

from __future__ import annotations

import math

MOTION_GRID = 8  # wheel motion drawn in 1/8 device pixel steps
TINT_STEPS = 255  # color blend amount steps


def motion_steps(length: float, scale: float) -> int:
    """Move (content units) in motion grid steps, 0 if not finite

    Args:
        scale: device pixels per content unit (content fit scale x screen scale).
    """
    steps = length * scale * MOTION_GRID
    return round(steps) if math.isfinite(steps) else 0


def motion_length(steps: int, scale: float) -> float:
    """Move (content units) of motion grid steps"""
    return steps / (scale * MOTION_GRID) if steps else 0.0


def tint_step(amount: float) -> float:
    """Color blend amount (0 to 1) in 8 bit color steps"""
    return round(amount * TINT_STEPS) / TINT_STEPS
