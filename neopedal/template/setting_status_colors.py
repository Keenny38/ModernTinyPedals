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
    loss: places lost, penalty, disqualified, retired, energy low, invalid lap
    warning: in pit lane (orange), energy getting low, attention
    gold: yellow flag, slower lap or sector
    player: player's row

Colorblind safe variant (overlay style "enable_colorblind_colors"): COLORBLIND_STATUS_COLORS, read by overlay
themes (widget._style.COLORBLIND_COLORS), app pages (ui.quick COLORBLIND_STATUS) & stream pages (status_css).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

# Role: (on dark background, on light background)
STATUS_COLORS = MappingProxyType({
    "purple": ("#C084FC", "#7E22CE"),
    "gain": ("#4ADE80", "#15803D"),
    "loss": ("#F87171", "#B91C1C"),
    "warning": ("#FB923C", "#C2410C"),
    "gold": ("#FACC15", "#B45309"),
    "player": ("#38BDF8", "#0369A1"),
})
# Colorblind safe status colors (Okabe-Ito like: green -> sky blue, red -> vermillion, purple -> reddish purple,
# player blue -> bluish green as blue is taken by gain), same roles & order as STATUS_COLORS
COLORBLIND_STATUS_COLORS = MappingProxyType({
    "purple": ("#E08AC0", "#A33D80"),
    "gain": ("#56B4E9", "#0067A8"),
    "loss": ("#F08A50", "#B04A00"),
    "warning": ("#E69F00", "#8F5F00"),
    "gold": ("#F0E442", "#8A7A00"),
    "player": ("#009E73", "#007A59"),
})
CSS_NAMES = MappingProxyType({"warning": "warn"})  # CSS variable names of stream pages (--warn)

# Energy left (fraction): loss at or under LOW, warning at or under MEDIUM, else gain
ENERGY_LOW = 0.1
ENERGY_MEDIUM = 0.3

# Times equal under this (seconds): game times have millisecond resolution, float sums do not
SAME_TIME = 0.0005


def colorblind_style(style: Any) -> bool:
    """Colorblind safe colors set in overlay style setting (overlays, app pages & stream pages follow it)"""
    return isinstance(style, Mapping) and bool(style.get("enable_colorblind_colors", False))


def status_colors(colorblind: bool = False) -> MappingProxyType:
    """Status colors (role: (on dark, on light)), colorblind safe variant if asked"""
    return COLORBLIND_STATUS_COLORS if colorblind else STATUS_COLORS


def status_css(light: bool = False, colorblind: bool = False) -> str:
    """CSS custom properties of status colors: --purple:#c084fc;--gain:...;"""
    return "".join(
        f"--{CSS_NAMES.get(role, role)}:{pair[light].lower()};" for role, pair in status_colors(colorblind).items())


def energy_tone(fraction: float) -> str:
    """Status role of energy left (0-1)"""
    if fraction <= ENERGY_LOW:
        return "loss"
    if fraction <= ENERGY_MEDIUM:
        return "warning"
    return "gain"
