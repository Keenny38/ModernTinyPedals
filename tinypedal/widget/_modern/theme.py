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
Modern overlay design: color tokens

Each token is a role (panel surface, dim text, gain, loss...) instead of a per cell color.
Tokens are defined as classic colors and remapped by the overlay theme palette, so built-in
themes (Modern Dark, High Contrast, Colorblind Safe) and user custom themes recolor modern
widgets the same way they recolor classic ones.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtGui import QColor

from .._style import GLOBAL_THEME, remap_color, theme_palette

# Token -> classic color (remapped by theme palette)
TOKEN_COLORS = {
    "surface": "#222222",  # panel background
    "surface_alt": "#2A2A2A",  # alternate row, inner tile
    "surface_raised": "#333333",  # badge, chip, bar track
    "surface_strong": "#444444",  # hovered or selected element
    "text": "#EEEEEE",  # main value
    "text_dim": "#AAAAAA",  # secondary value
    "text_muted": "#888888",  # label, caption
    "text_faint": "#666666",  # placeholder, inactive
    "accent": "#00CCFF",  # player, selection, info
    "positive": "#22CC22",  # gain, faster, ok
    "negative": "#FF2200",  # loss, slower, danger
    "warning": "#FFAA00",  # warning, attention
    "caution": "#FFFF00",  # yellow flag, low
    "best": "#9900FF",  # session or class best (purple)
    "orange": "#FF6600",
    "blue": "#0088FF",  # lapped car, cold
    "lap_ahead": "#FF4422",  # car one lap or more ahead
    "lap_behind": "#66CCFF",  # car one lap or more behind
}

BORDER_ALPHA = 20  # panel hairline border (white)
HIGHLIGHT_ALPHA = 46  # player row tint


class Theme(NamedTuple):
    """Modern overlay colors"""

    surface: QColor
    surface_alt: QColor
    surface_raised: QColor
    surface_strong: QColor
    text: QColor
    text_dim: QColor
    text_muted: QColor
    text_faint: QColor
    accent: QColor
    positive: QColor
    negative: QColor
    warning: QColor
    caution: QColor
    best: QColor
    orange: QColor
    blue: QColor
    lap_ahead: QColor
    lap_behind: QColor
    border: QColor
    highlight: QColor  # player row background tint

    def tint(self, color: QColor, alpha: int) -> QColor:
        """Same color with alpha"""
        tinted = QColor(color)
        tinted.setAlpha(alpha)
        return tinted


def theme_name(style: dict, widget_theme: str) -> str:
    """Theme used by widget: own theme, or global overlay theme"""
    if widget_theme and widget_theme != GLOBAL_THEME:
        return widget_theme
    return style.get("overlay_theme", "Modern Dark")


def build_theme(style: dict, widget_theme: str = GLOBAL_THEME, surface_alpha: int = 235) -> Theme:
    """Theme colors for overlay style & widget theme option

    Args:
        style: global overlay style setting.
        widget_theme: widget "widget_theme" option.
        surface_alpha: panel background alpha (0-255).
    """
    palette = theme_palette(theme_name(style, widget_theme))
    colors = {name: QColor(remap_color(value, palette)) for name, value in TOKEN_COLORS.items()}
    colors["surface"].setAlpha(surface_alpha)
    border = QColor(255, 255, 255, BORDER_ALPHA)
    highlight = QColor(colors["accent"])
    highlight.setAlpha(HIGHLIGHT_ALPHA)
    return Theme(border=border, highlight=highlight, **colors)
