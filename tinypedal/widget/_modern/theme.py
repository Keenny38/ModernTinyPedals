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
Tokens are defined as classic colors and remapped by the overlay theme (Modern Dark or Light,
colorblind variant), so themes recolor modern widgets the same way they recolor classic ones.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtGui import QColor

from .._style import BACKGROUND, FOREGROUND, overlay_theme, theme_rgb

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
LIGHT_BORDER_ALPHA = 28  # panel hairline border on light themes (black)
HIGHLIGHT_ALPHA = 46  # player row tint
_tints: dict[tuple[int, int], QColor] = {}  # (color rgba, alpha): tinted color


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
        """Same color with alpha (shared color, never modified)

        Asked for on every paint by rows & tiles: cached per color & alpha.
        """
        key = (color.rgba(), alpha)
        tinted = _tints.get(key)
        if tinted is None:
            tinted = QColor(color)
            tinted.setAlpha(alpha)
            if len(_tints) > 1024:
                _tints.clear()
            _tints[key] = tinted
        return tinted


def build_theme(style: dict, surface_alpha: int = 235) -> Theme:
    """Theme colors of overlay theme

    Args:
        style: global overlay style setting.
        surface_alpha: panel background alpha (0-255).
    """
    theme = overlay_theme(style)
    colors = {
        name: QColor(f"#{theme_rgb(value[1:], theme, BACKGROUND if name.startswith('surface') else FOREGROUND)}")
        for name, value in TOKEN_COLORS.items()
    }
    colors["surface"].setAlpha(surface_alpha)
    if theme.light:
        border = QColor(0, 0, 0, LIGHT_BORDER_ALPHA)
    else:
        border = QColor(255, 255, 255, BORDER_ALPHA)
    highlight = QColor(colors["accent"])
    highlight.setAlpha(HIGHLIGHT_ALPHA)
    return Theme(border=border, highlight=highlight, **colors)
