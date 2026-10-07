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
Modern overlay design

Widgets with a modern design (see template.widget.modern.MODERN_DESIGNS) have a second
implementation here, same module name: tinypedal.widget._modern.<name>.Realtime. It is used
while overlay theme is a modern one, otherwise (or with widget "enable_classic_layout" option)
the classic widget is used, so classic look stays available as it was.

    theme.py  color tokens, remapped by overlay theme
    draw.py   shapes: panel, bars, pills, arrows
    base.py   ModernOverlay: one painted surface, cached text & background
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

from ...template.widget.modern import CLASSIC_LAYOUT_OPTION, MODERN_DESIGN_OPTIONS, MODERN_DESIGNS
from .._style import overlay_theme


def uses_modern_design(config, name: str) -> bool:
    """Whether widget is drawn with modern design"""
    if name not in MODERN_DESIGNS:
        return False
    if not overlay_theme(config.user.config["overlay_style"]).modern:  # legacy theme
        return False
    return not config.user.setting[name].get(CLASSIC_LAYOUT_OPTION, False)


def modern_module(name: str) -> ModuleType:
    """Modern design module of widget"""
    return import_module(f"{__name__}.{name}")


def widget_class(module: ModuleType, config, name: str) -> type:
    """Widget class to create: modern design or classic"""
    if uses_modern_design(config, name):
        return modern_module(name).Realtime
    return module.Realtime


def create_widget(module: ModuleType, config, name: str):
    """Create widget instance (modern design or classic)"""
    return widget_class(module, config, name)(config, name)


# Options of every modern design widget, always shown in config dialog
COMMON_OPTIONS = (
    "enable", CLASSIC_LAYOUT_OPTION, "update_interval", "position_x", "position_y", "opacity",
    "visibility_context", "stream_visibility",
)


def design_option_keys(config, name: str, keys: list[str]) -> list[str]:
    """Options of current widget design (config dialog, option search): modern design shows
    only the options it reads, classic layout hides the ones only modern design reads"""
    modern_only = MODERN_DESIGN_OPTIONS.get(name)
    if modern_only is None:
        return keys
    if uses_modern_design(config, name):
        realtime = modern_module(name).Realtime
        shown = {*COMMON_OPTIONS, *realtime.options}
        if not config.user.config["overlay_style"].get("enable_modern_font", True):
            shown.add("font_name")  # modern font off: design drawn in widget font
            from .restyle import Restyled

            if issubclass(realtime, Restyled):  # restyled classic drawing: widget font weight too
                shown.add("font_weight")
        return [key for key in keys if key in shown]
    if not overlay_theme(config.user.config["overlay_style"]).modern:  # legacy theme: no design switch either
        modern_only = {**modern_only, CLASSIC_LAYOUT_OPTION: False}
    return [key for key in keys if key not in modern_only]
