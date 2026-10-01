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
Modern overlay style

Only options that still use default value are restyled,
any user customized option is kept as it is.
"""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any

# Classic default color (RGB) -> modern color (RGB), alpha channel is kept
MODERN_PALETTE = MappingProxyType({
    # Neutral (slate)
    "000000": "0E1116",
    "111111": "13161C",
    "222222": "1B1F27",
    "2A2A2A": "212631",
    "333333": "2A303C",
    "444444": "373E4C",
    "555555": "4A5262",
    "666666": "576071",
    "777777": "646D7E",
    "888888": "747D8E",
    "AAAAAA": "9AA3B2",
    "BBBBBB": "AEB4C0",
    "CCCCCC": "C3C8D1",
    "DDDDDD": "D6DAE1",
    "EEEEEE": "E9ECF1",
    "FFFFFF": "F4F6F9",
    # Red & orange
    "FF2200": "FF4D4F",
    "FF4400": "FF5A36",
    "DD5500": "F06A2B",
    "EE6600": "F2743A",
    "FF6600": "FF7A45",
    # Yellow
    "FFAA00": "FFB020",
    "FFCC00": "FFD43B",
    "FFFF00": "FDE047",
    "CCCC22": "D4D44A",
    # Green
    "009900": "22A052",
    "22AA00": "2FB344",
    "22CC22": "34C759",
    "448800": "3A9D5D",
    "44FF00": "4ADE80",
    "66EE00": "52D273",
    "66FF00": "5BE37D",
    "88FF00": "8BE36B",
    # Blue & cyan
    "00CCEE": "22B8E0",
    "00CCFF": "38BDF8",
    "66CCFF": "5CC8FF",
    "66CCCC": "5EC4C4",
    # Purple & pink
    "AA00AA": "A63DC7",
    "CC22CC": "C026D3",
    "FF44FF": "E879F9",
    "FF66FF": "F472D0",
    # Other default colors
    "00AAFF": "38A9F5", "FF0000": "F23B3B", "999999": "8A93A3", "FF00FF": "E056E0",
    "FF4422": "FF5A40", "0088FF": "2F86F0", "FF44CC": "F062C8", "00FF00": "3EDC6B",
    "AA22AA": "A33FB0", "008800": "2A8F4F", "44CC00": "4CC45A", "00FFFF": "4FE3EE",
    "00CC00": "36B85A", "77FF00": "86E35C", "00C2F2": "2BB8E6", "EE00EE": "D94BD9",
    "2266CC": "3570C8", "CC7700": "D08526", "0000FF": "3B5BF0", "22FFFF": "5CE8F0",
    "FFFF22": "F8E45A", "22EE22": "45D86A", "EE7700": "F08A2E", "4444FF": "5B5BF5",
    "44AA00": "4FA84A", "FF8800": "FF9530", "22FF00": "4EE36B", "00BBDD": "22B0D6",
    "EE0000": "E53E3E", "9900FF": "9150F0", "0099FF": "2E98F2", "0055FF": "3565F2",
    "0066CC": "2A6EC2", "BBAA00": "C2B236", "887700": "8A7E2E", "880088": "8A3A8F",
    "008888": "2A8A8A", "DD2200": "E0452F", "CC00CC": "C23BC9", "FF2222": "F44848",
    "CC44CC": "C257C7", "44DDFF": "5AD2F7", "88FF88": "8FE8A0", "FFFF88": "F9EE95",
    "EE77FF": "E08AF2",
})


# High contrast: darker backgrounds, brighter text
HIGH_CONTRAST_PALETTE = MappingProxyType({
    **MODERN_PALETTE,
    "111111": "000000",
    "222222": "050608",
    "2A2A2A": "0A0C10",
    "333333": "12151B",
    "444444": "1E232C",
    "555555": "39404D",
    "AAAAAA": "E6E9EF",
    "BBBBBB": "EEF0F4",
    "CCCCCC": "FFFFFF",
    "DDDDDD": "FFFFFF",
    "EEEEEE": "FFFFFF",
    "FFFFFF": "FFFFFF",
    "FF2200": "FF3B3B",
    "FFAA00": "FFC400",
    "66EE00": "3DFF6E",
    "66CCFF": "7FD8FF",
    "FF0000": "FF3B3B", "EE0000": "FF3B3B", "FF2222": "FF3B3B", "FF4422": "FF4B2E",
    "00FF00": "3DFF6E", "22EE22": "3DFF6E", "00CC00": "2EE85A", "44CC00": "4CE85A",
    "00AAFF": "4DC2FF", "0088FF": "3D9BFF",
})

# Colorblind safe (Okabe-Ito): red / green pairs become orange / blue
COLORBLIND_PALETTE = MappingProxyType({
    **MODERN_PALETTE,
    "FF2200": "D55E00",
    "FF4400": "D55E00",
    "DD5500": "D55E00",
    "EE6600": "E69F00",
    "FF6600": "E69F00",
    "FFAA00": "F0E442",
    "FFCC00": "F0E442",
    "FFFF00": "F0E442",
    "009900": "0072B2",
    "22AA00": "0072B2",
    "22CC22": "56B4E9",
    "448800": "0072B2",
    "44FF00": "56B4E9",
    "66EE00": "56B4E9",
    "66FF00": "56B4E9",
    "88FF00": "56B4E9",
    "00CCEE": "009E73",
    "00CCFF": "009E73",
    "66CCFF": "009E73",
    "CC22CC": "CC79A7",
    "FF44FF": "CC79A7",
    "FF66FF": "CC79A7",
    "FF0000": "D55E00", "EE0000": "D55E00", "FF2222": "D55E00", "DD2200": "D55E00",
    "FF4422": "D55E00", "00FF00": "56B4E9", "22EE22": "56B4E9", "22FF00": "56B4E9",
    "00CC00": "56B4E9", "44CC00": "56B4E9", "77FF00": "56B4E9", "88FF88": "56B4E9",
    "008800": "0072B2", "44AA00": "0072B2", "00AAFF": "0072B2", "0088FF": "0072B2",
    "0099FF": "0072B2", "FF00FF": "CC79A7", "EE00EE": "CC79A7", "CC00CC": "CC79A7",
})

# Overlay theme name -> palette (None = keep classic colors)
OVERLAY_THEMES = MappingProxyType({
    "Modern Dark": MODERN_PALETTE,
    "High Contrast": HIGH_CONTRAST_PALETTE,
    "Colorblind Safe": COLORBLIND_PALETTE,
    "Classic": None,
})


BUILTIN_THEMES = tuple(OVERLAY_THEMES)
GLOBAL_THEME = "Global"  # widget option: use global overlay theme
_custom_themes: dict[str, dict] = {}


def set_custom_themes(themes: dict[str, dict]):
    """Set custom themes (loaded from user file)"""
    _custom_themes.clear()
    _custom_themes.update(themes)


def custom_themes() -> dict[str, dict]:
    """Custom themes (name: {"base": name, "colors": {classic: color}})"""
    return _custom_themes


def overlay_theme_names() -> tuple[str, ...]:
    """Built-in & custom theme names"""
    return (*BUILTIN_THEMES, *sorted(_custom_themes))


def theme_palette(name: str) -> MappingProxyType | None:
    """Palette of built-in or custom theme, None for classic colors"""
    if name in OVERLAY_THEMES:
        return OVERLAY_THEMES[name]
    theme = _custom_themes.get(name)
    if theme is None:
        return MODERN_PALETTE
    base = OVERLAY_THEMES.get(theme["base"], MODERN_PALETTE)
    return MappingProxyType({**(base or {}), **theme["colors"]})


def remap_color(color: str, palette: MappingProxyType | None = MODERN_PALETTE) -> str:
    """Remap classic color with theme palette, keep alpha channel"""
    if palette is None or len(color) not in (7, 9) or color[0] != "#":
        return color
    modern = palette.get(color[-6:].upper())
    if modern is None:
        return color
    return f"{color[:-6]}{modern}"


def modern_overrides(wcfg: dict, default: dict, style: dict) -> dict:
    """Get modern style overrides for options that still use default value

    Args:
        wcfg: widget user setting.
        default: widget default setting.
        style: global overlay style setting.

    Returns:
        Dictionary of overridden options.
    """
    overrides: dict[str, Any] = {}
    min_gap = max(int(style["minimum_bar_gap"]), 0)
    theme = wcfg.get("widget_theme", GLOBAL_THEME)
    palette = theme_palette(style["overlay_theme"] if theme == GLOBAL_THEME else theme)
    for key, value in wcfg.items():
        if value != default.get(key):  # user customized
            continue
        if palette is not None and "color" in key and isinstance(value, str):
            new_color = remap_color(value, palette)
            if new_color != value:
                overrides[key] = new_color
        elif style["enable_modern_font"] and key.endswith("font_name"):
            overrides[key] = style["modern_font_name"]
        elif key == "bar_gap" and isinstance(value, int) and value < min_gap:
            overrides[key] = min_gap
    return overrides


# Pixel size options scaled by global overlay scale (other geometry derives from them)
SCALED_OPTION = re.compile(
    r"(^|_)font_size$"
    r"|^display_(size|width|height)$"
    r"|(^|_)bar_(height|width)$"
    r"|^(led|wheel)_(width|height)$"
    r"|^(icon|dot|area|vehicle|brake_input)_size$"
)
OVERLAY_SCALE_RANGE = (0.5, 3.0)


def scale_overrides(wcfg: dict, scale: float) -> dict:
    """Pixel size options multiplied by global overlay scale

    Args:
        wcfg: widget setting (with style overrides).
        scale: global overlay scale, 1 = unchanged.

    Returns:
        Dictionary of scaled options.
    """
    scale = min(max(scale, OVERLAY_SCALE_RANGE[0]), OVERLAY_SCALE_RANGE[1])
    if scale == 1:
        return {}
    overrides: dict[str, Any] = {}
    for key, value in wcfg.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not SCALED_OPTION.search(key):
            continue
        if isinstance(value, int):
            overrides[key] = max(round(value * scale), 1)
        else:
            overrides[key] = value * scale
    return overrides


class StyledConfig(dict):
    """Widget setting with style overrides applied

    Reading returns overridden value; writing (such as saving widget position)
    is passed through to user setting, so overrides are never saved to file.
    """

    __slots__ = ("_source",)

    def __init__(self, source: dict, overrides: dict):
        super().__init__(source)
        super().update(overrides)
        self._source = source

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._source[key] = value
