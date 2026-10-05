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
Modern overlay design: classic drawing in modern design colors & font

For graphic widgets (maps, radar, circles, plots) whose drawing is already custom: the classic
widget draws, with options still at default value replaced by design values: design font,
panel color as background, theme colors by role. Options customized by user are kept.
"""

from __future__ import annotations

from typing import Any, ClassVar

from PySide6.QtGui import QColor

from ...template.setting_widget import WIDGET_DEFAULT
from .._style import GLOBAL_THEME
from .base import design_font_family
from .theme import build_theme

DESIGN_WEIGHT = "Semi Bold"


def restyled_options(name: str) -> tuple[str, ...]:
    """Options shown for restyled widget: all but colors & font face (design sets them)"""
    return tuple(
        key for key in WIDGET_DEFAULT.get(name, {})
        if "color" not in key and not key.endswith(("font_name", "font_weight"))
    )


class Restyled:
    """Mixin before classic widget class: design overrides of default options"""

    # Option -> theme token, or (token, alpha) to set alpha (default: keep alpha of default color)
    color_tokens: ClassVar[dict[str, str | tuple[str, int]]] = {}
    background_options: ClassVar[tuple[str, ...]] = ("background_color",)

    cfg: Any
    widget_name: Any

    def design_overrides(self, style: dict) -> dict:
        user = self.cfg.user.setting[self.widget_name]
        default = self.cfg.default.setting[self.widget_name]
        theme = build_theme(style, user.get("widget_theme", GLOBAL_THEME))
        overrides: dict = {}
        tokens = {**{key: "surface" for key in self.background_options}, **self.color_tokens}
        for key, value in default.items():
            if user.get(key) != value:  # customized by user
                continue
            if key.endswith("font_name"):
                overrides[key] = design_font_family(style)
            elif key.endswith("font_weight"):
                overrides[key] = DESIGN_WEIGHT
            elif key in tokens and isinstance(value, str):
                overrides[key] = token_color(theme, tokens[key], value)
        return overrides


def token_color(theme, token: str | tuple[str, int], default: str) -> str:
    """Theme token color as #AARRGGBB, alpha of default color unless given"""
    if isinstance(token, tuple):
        token, alpha = token
    else:
        alpha = QColor(default).alpha()
    color = QColor(getattr(theme, token))
    if token != "surface" or alpha < 255:
        color.setAlpha(alpha)
    return color.name(QColor.NameFormat.HexArgb)
