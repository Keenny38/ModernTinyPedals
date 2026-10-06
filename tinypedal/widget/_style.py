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
Overlay themes & style

Themes: Modern Dark, Modern Light, Legacy Dark (classic TinyPedal look), Legacy Light,
each with an optional colorblind safe variant. Only options that still use default value
are restyled, any user customized option is kept as it is.
"""

from __future__ import annotations

import colorsys
import re
from functools import lru_cache
from types import MappingProxyType
from typing import Any, NamedTuple

from .. import regex_pattern as rxp

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


# Light themes: classic grays (panels & text) inverted, colors on panels darkened to stay readable.
# Modern Light grays: slate scale of Modern Dark, reversed
MODERN_LIGHT_NEUTRALS = MappingProxyType({
    "000000": "FFFFFF",
    "111111": "FAFBFC",
    "222222": "F4F6F9",
    "2A2A2A": "EDF0F4",
    "333333": "E5E9EF",
    "444444": "D8DDE5",
    "555555": "C5CBD5",
    "666666": "98A1B0",
    "777777": "848D9C",
    "888888": "6B7383",
    "999999": "5E6676",
    "AAAAAA": "4E5666",
    "BBBBBB": "3F4655",
    "CCCCCC": "313845",
    "DDDDDD": "252B36",
    "EEEEEE": "171B22",
    "FFFFFF": "0E1116",
})
MODERN_LIGHT_PANEL = "E5E9EF"  # darkest modern light panel: colors drawn on panels stay readable on it
LEGACY_LIGHT_PANEL = "CCCCCC"  # darkest legacy light panel (classic #333333 inverted)
MINIMUM_CONTRAST = 3.0  # WCAG minimum for large text & graphics
NEUTRAL_SPREAD = 24  # gray: RGB channels differ by this much at most

# Colorblind safe variant of every theme (Okabe-Ito): red / green pairs become orange / blue
COLORBLIND_COLORS = MappingProxyType({
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
    # Black box: warning & hot, cold & low, good, between, yellow, blue, magenta
    "FF3D3D": "D55E00", "3DC8FF": "56B4E9", "2FC46A": "009E73", "FF9F1C": "E69F00",
    "FFC400": "F0E442", "3D8BFF": "0072B2", "B0106A": "CC79A7",
})

# Overlay themes: design (modern, or legacy: classic TinyPedal look) & dark or light colors
THEME_NAMES = rxp.THEME_NAMES
DEFAULT_THEME = THEME_NAMES[0]

# Color option roles on light themes
BACKGROUND = "background"  # panel, cell background: grays inverted, colors kept
FOREGROUND = "foreground"  # text, bar or mark on panel: grays inverted, colors darkened
ON_COLOR = "on_color"  # text on a colored background: kept
# Background options also drawn as text or mark on panel (deltabest gain & loss: delta text & bar mark)
COLORED_ON_PANEL = frozenset(("background_color_time_gain", "background_color_time_loss"))

_HEX_RGB = re.compile(r"[0-9A-F]{6}")


class OverlayTheme(NamedTuple):
    """Overlay theme: design & colors"""

    modern: bool  # modern design, else legacy (classic TinyPedal look)
    light: bool  # light panels & dark text
    colorblind: bool  # colorblind safe colors

    @property
    def recolors(self) -> bool:
        """Whether classic colors are changed"""
        return self.modern or self.light or self.colorblind


def overlay_theme(style: dict) -> OverlayTheme:
    """Overlay theme of global overlay style setting"""
    name = style.get("overlay_theme")
    if name not in THEME_NAMES:
        name = DEFAULT_THEME
    return OverlayTheme(
        modern=not name.startswith("Legacy"),
        light=name.endswith("Light"),
        colorblind=bool(style.get("enable_colorblind_colors", False)),
    )


def _channels(rgb: str) -> tuple[int, int, int]:
    return int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)


def _is_neutral(rgb: str) -> bool:
    channels = _channels(rgb)
    return max(channels) - min(channels) <= NEUTRAL_SPREAD


def _luminance(rgb: str) -> float:
    """WCAG relative luminance"""
    red, green, blue = (
        value / 3294.6 if value <= 10 else ((value / 255 + 0.055) / 1.055) ** 2.4  # 3294.6 = 255 x 12.92
        for value in _channels(rgb)
    )
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first: str, second: str) -> float:
    """WCAG contrast ratio (1 to 21)"""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _hls(rgb: str) -> tuple[float, float, float]:
    red, green, blue = _channels(rgb)
    return colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)


def _from_hls(hue: float, lightness: float, saturation: float) -> str:
    return "".join(f"{round(value * 255):02X}" for value in colorsys.hls_to_rgb(hue, lightness, saturation))


def _inverted(rgb: str) -> str:
    """Gray of light theme: same hue, lightness inverted"""
    hue, lightness, saturation = _hls(rgb)
    return _from_hls(hue, 1 - lightness, saturation)


def _darkened(rgb: str, panel: str) -> str:
    """Color of light theme: same hue, darkened until readable on light panel"""
    hue, lightness, saturation = _hls(rgb)
    color = rgb
    while lightness > 0 and _contrast(color, panel) < MINIMUM_CONTRAST:
        lightness = max(lightness - 0.02, 0.0)
        color = _from_hls(hue, lightness, saturation)
    return color


@lru_cache(maxsize=4096)
def theme_rgb(rgb: str, theme: OverlayTheme, role: str = FOREGROUND) -> str:
    """Theme color of classic color (RRGGBB, upper case)"""
    if theme.colorblind and rgb in COLORBLIND_COLORS:
        color = COLORBLIND_COLORS[rgb]
    elif theme.modern:
        color = MODERN_PALETTE.get(rgb, rgb)
    else:
        color = rgb
    if not theme.light or role == ON_COLOR:
        return color
    if _is_neutral(rgb):
        if theme.modern and rgb in MODERN_LIGHT_NEUTRALS:
            return MODERN_LIGHT_NEUTRALS[rgb]
        return _inverted(color)
    if role == BACKGROUND:
        return color
    return _darkened(color, MODERN_LIGHT_PANEL if theme.modern else LEGACY_LIGHT_PANEL)


def _option_rgb(value: Any) -> str | None:
    """RGB part (upper case) of #RRGGBB or #AARRGGBB color, None if not a color"""
    if not isinstance(value, str) or len(value) not in (7, 9) or value[0] != "#":
        return None
    rgb = value[-6:].upper()
    return rgb if _HEX_RGB.fullmatch(rgb) else None


def theme_color(color: str, theme: OverlayTheme, role: str = FOREGROUND) -> str:
    """Theme color of classic color (#RRGGBB or #AARRGGBB, alpha kept), other formats unchanged"""
    rgb = _option_rgb(color)
    if rgb is None:
        return color
    themed = theme_rgb(rgb, theme, role)
    if themed == rgb:
        return color
    return f"{color[:-6]}{themed}"


def option_role(key: str, options: dict) -> str:
    """Role of color option on light themes, from classic default colors of widget

    Text colors are paired with background of same suffix (font_color_x, background_color_x):
    text on a colored background (flags, warnings) or on another colored element keeps its color.
    """
    if key in COLORED_ON_PANEL:
        return FOREGROUND
    if "background" in key:
        return BACKGROUND
    if not key.startswith("font_color"):
        return FOREGROUND
    text = _option_rgb(options.get(key))
    if text is None:
        return FOREGROUND
    background = _option_rgb(options.get(f"background_color{key[len('font_color'):]}"))
    if background is None:  # text on panel, unless dark text (drawn on a colored element)
        return FOREGROUND if not _is_neutral(text) or _luminance(text) > 0.18 else ON_COLOR
    if not _is_neutral(background) or _contrast(text, background) < 2:
        return ON_COLOR
    return FOREGROUND


def theme_overrides(wcfg: dict, default: dict, style: dict) -> dict:
    """Get overlay theme overrides for options that still use default value

    Colors follow theme (modern palette, light & colorblind variants), modern design also sets
    modern font & minimum bar gap.

    Args:
        wcfg: widget user setting.
        default: widget default setting.
        style: global overlay style setting.

    Returns:
        Dictionary of overridden options.
    """
    theme = overlay_theme(style)
    overrides: dict[str, Any] = {}
    min_gap = max(int(style["minimum_bar_gap"]), 0)
    for key, value in wcfg.items():
        if value != default.get(key):  # user customized
            continue
        if "color" in key and isinstance(value, str):
            if theme.recolors:
                new_color = theme_color(value, theme, option_role(key, default))
                if new_color != value:
                    overrides[key] = new_color
        elif not theme.modern:
            continue
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
    r"|^(delta_)?bar_length$|^bar_width_(unfiltered|filtered)$|^maximum_indicator_height$"  # pedal, deltabest
    r"|^parts_(maximum_)?(width|height)$"  # damage
    r"|^global_scale$"  # radar: pixels per meter
)
OVERLAY_SCALE_RANGE = (0.5, 3.0)
# Widgets whose "bar_width" is a number of characters (already follows font size)
CHARACTER_BAR_WIDTH = frozenset((
    "acceleration", "fuel", "fuel_energy_saver", "pit_stop_estimate", "relative_finish_order", "traffic",
    "virtual_energy",
))


def is_scaled_option(widget_name: str, key: str, value: Any) -> bool:
    """Whether option is a pixel size, scaled with widget"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if key == "bar_width" and widget_name in CHARACTER_BAR_WIDTH:
        return False
    return SCALED_OPTION.search(key) is not None


def scale_overrides(wcfg: dict, scale: float, widget_name: str = "") -> dict:
    """Pixel size options multiplied by global overlay scale

    Args:
        wcfg: widget setting (with style overrides).
        scale: global overlay scale, 1 = unchanged.
        widget_name: widget name.

    Returns:
        Dictionary of scaled options.
    """
    scale = min(max(scale, OVERLAY_SCALE_RANGE[0]), OVERLAY_SCALE_RANGE[1])
    if scale == 1:
        return {}
    overrides: dict[str, Any] = {}
    for key, value in wcfg.items():
        if not is_scaled_option(widget_name, key, value):
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
