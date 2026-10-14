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
Default compounds template
"""

import re
from types import MappingProxyType

from ..regex_pattern import COMMON_TYRE_COMPOUNDS
from .setting_heatmap import HEATMAP_DEFAULT_TYRE

# Tyre compound colors (soft white, medium yellow, hard red, wet blue, intermediate green), same in
# overlays & app pages: (dark background, light background). Overlays use the first one (light overlay themes
# darken colors themselves), app pages pick by theme (theme.compound in QML).
COMPOUND_COLORS = MappingProxyType({
    "ultrasoft": ("#C084FC", "#9333EA"),
    "supersoft": ("#F43F5E", "#E11D48"),
    "soft": ("#EDEDED", "#777777"),
    "medium": ("#F5C518", "#CA8A04"),
    "hard": ("#E5484D", "#DC2626"),
    "intermediate": ("#30A46C", "#15803D"),
    "wet": ("#3E8EF7", "#2563EB"),
})
# Compound symbol (lower case) -> COMPOUND_COLORS key, see regex_pattern.COMMON_TYRE_COMPOUNDS
COMPOUND_SYMBOLS = MappingProxyType({
    "q": "supersoft", "s": "soft", "m": "medium", "h": "hard", "i": "intermediate", "w": "wet",
})
UNKNOWN_COMPOUND_COLOR = "#AAAAAA"
# Default compound colors before 0.24.0 by symbol (compounds added on the fly were all gray):
# replaced once by name_color if never changed
FORMER_DEFAULT_COLORS = MappingProxyType({"S": "#AAAAAA", "M": "#FFCC00", "H": "#EE2200", "W": "#00AAFF"})


def name_color(compound_name: str) -> str:
    """Overlay color (dark background color) of compound name ("Hyper - Soft", "Wet"...): soft, medium, hard,
    wet... by name, gray for others (only dry compound of a car, bias ply, oval...)"""
    tyre_name = compound_name.split("-")[-1].strip()
    for pattern, symbol in COMMON_TYRE_COMPOUNDS:
        if re.search(pattern, tyre_name, flags=re.IGNORECASE):
            key = COMPOUND_SYMBOLS.get(symbol.lower()) if pattern != "slick|dry" else None
            return COMPOUND_COLORS[key][0] if key else UNKNOWN_COMPOUND_COLOR
    return UNKNOWN_COMPOUND_COLOR


def compound_letter(name: str) -> str:
    """Badge letter of a compound name, same as default compound symbols of overlays ("Medium #2" -> "M",
    "Hyper - Soft" -> "S", "Wet" -> "W"), "" if no name (app pages & Broadcast Director)"""
    tyre = name.split("#")[0].split(" - ")[-1].strip()
    if len(tyre) <= 1:
        return tyre.upper()
    for pattern, symbol in COMMON_TYRE_COMPOUNDS:
        if re.search(pattern, tyre, flags=re.IGNORECASE):
            return symbol
    return tyre[0].upper()


def letter_color(letter: str) -> str:
    """Overlay color (dark background color) of a badge letter ("S", "M"...), gray if unknown"""
    key = COMPOUND_SYMBOLS.get(letter.lower())
    return COMPOUND_COLORS[key][0] if key else UNKNOWN_COMPOUND_COLOR


COMPOUNDINFO_DEFAULT = MappingProxyType({
    "symbol": "?",
    "color": UNKNOWN_COMPOUND_COLOR,
    "heatmap": HEATMAP_DEFAULT_TYRE,
})

COMPOUNDS_DEFAULT = {
    "Hyper - Soft": {
        "symbol": "S",
        "color": "#EDEDED",
        "heatmap": "tyre_optimal_80",
    },
    "Hyper - Medium": {
        "symbol": "M",
        "color": "#F5C518",
        "heatmap": "tyre_optimal_90",
    },
    "Hyper - Hard": {
        "symbol": "H",
        "color": "#E5484D",
        "heatmap": "tyre_optimal_100",
    },
    "Hyper - Wet": {
        "symbol": "W",
        "color": "#3E8EF7",
        "heatmap": "tyre_optimal_50",
    },
    "LMP2 - Soft": {
        "symbol": "S",
        "color": "#EDEDED",
        "heatmap": "tyre_optimal_80",
    },
    "LMP2 - Medium": {
        "symbol": "M",
        "color": "#F5C518",
        "heatmap": "tyre_optimal_90",
    },
    "LMP2 - Hard": {
        "symbol": "H",
        "color": "#E5484D",
        "heatmap": "tyre_optimal_100",
    },
    "LMP2 - Wet": {
        "symbol": "W",
        "color": "#3E8EF7",
        "heatmap": "tyre_optimal_50",
    },
    "LMP2_ELMS - Soft": {
        "symbol": "S",
        "color": "#EDEDED",
        "heatmap": "tyre_optimal_80",
    },
    "LMP2_ELMS - Medium": {
        "symbol": "M",
        "color": "#F5C518",
        "heatmap": "tyre_optimal_90",
    },
    "LMP2_ELMS - Hard": {
        "symbol": "H",
        "color": "#E5484D",
        "heatmap": "tyre_optimal_100",
    },
    "LMP2_ELMS - Wet": {
        "symbol": "W",
        "color": "#3E8EF7",
        "heatmap": "tyre_optimal_50",
    },
    "LMP3 - Soft": {
        "symbol": "S",
        "color": "#EDEDED",
        "heatmap": "tyre_optimal_80",
    },
    "LMP3 - Medium": {
        "symbol": "M",
        "color": "#F5C518",
        "heatmap": "tyre_optimal_90",
    },
    "LMP3 - Hard": {
        "symbol": "H",
        "color": "#E5484D",
        "heatmap": "tyre_optimal_100",
    },
    "LMP3 - Wet": {
        "symbol": "W",
        "color": "#3E8EF7",
        "heatmap": "tyre_optimal_50",
    },
    "GTE - Soft": {
        "symbol": "S",
        "color": "#EDEDED",
        "heatmap": "tyre_optimal_80",
    },
    "GTE - Medium": {
        "symbol": "M",
        "color": "#F5C518",
        "heatmap": "tyre_optimal_90",
    },
    "GTE - Hard": {
        "symbol": "H",
        "color": "#E5484D",
        "heatmap": "tyre_optimal_100",
    },
    "GTE - Wet": {
        "symbol": "W",
        "color": "#3E8EF7",
        "heatmap": "tyre_optimal_50",
    },
    "GT3 - Soft": {
        "symbol": "S",
        "color": "#EDEDED",
        "heatmap": "tyre_optimal_80",
    },
    "GT3 - Medium": {
        "symbol": "M",
        "color": "#F5C518",
        "heatmap": "tyre_optimal_90",
    },
    "GT3 - Hard": {
        "symbol": "H",
        "color": "#E5484D",
        "heatmap": "tyre_optimal_100",
    },
    "GT3 - Wet": {
        "symbol": "W",
        "color": "#3E8EF7",
        "heatmap": "tyre_optimal_50",
    },
}
