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
Status colors shared by every surface: modern overlays (theme palette), app pages (QML theme),
Broadcast Director stream graphics, OBS results & phone dashboard (CSS).

One meaning per color:
    purple: session or class best (lap, sector), fastest lap
    gain: personal best, places gained, finished, energy ok
    loss: places lost, penalty, disqualified, retired, energy low
    warning: in pit lane (orange), energy getting low
    gold: yellow flag, slower sector
    player: player's row
"""

from __future__ import annotations

from types import MappingProxyType

# Role: (on dark background, on light background)
STATUS_COLORS = MappingProxyType({
    "purple": ("#C084FC", "#7E22CE"),
    "gain": ("#4ADE80", "#15803D"),
    "loss": ("#F87171", "#B91C1C"),
    "warning": ("#FB923C", "#C2410C"),
    "gold": ("#FACC15", "#B45309"),
    "player": ("#38BDF8", "#0369A1"),
})
CSS_NAMES = MappingProxyType({"warning": "warn"})  # CSS variable names of stream pages (--warn)

# Energy left (fraction): loss at or under LOW, warning at or under MEDIUM, else gain
ENERGY_LOW = 0.1
ENERGY_MEDIUM = 0.3

# Times equal under this (seconds): game times have millisecond resolution, float sums do not
SAME_TIME = 0.0005


def status_css(light: bool = False) -> str:
    """CSS custom properties of status colors: --purple:#c084fc;--gain:...;"""
    return "".join(
        f"--{CSS_NAMES.get(role, role)}:{pair[light].lower()};" for role, pair in STATUS_COLORS.items())


def energy_tone(fraction: float) -> str:
    """Status role of energy left (0-1)"""
    if fraction <= ENERGY_LOW:
        return "loss"
    if fraction <= ENERGY_MEDIUM:
        return "warning"
    return "gain"
