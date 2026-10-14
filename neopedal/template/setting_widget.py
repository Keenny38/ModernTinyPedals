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
Default widget setting template

Widget default options are grouped by category in "widget" package, every built-in widget is
declared in widget.registry.OVERLAYS (display order), plugins are added here.
Widget key name must match corresponding file name in 'widget' folder
"""

from __future__ import annotations

from ..plugin_loader import load_plugin_defaults
from .widget.modern import add_modern_options
from .widget.registry import OVERLAYS, OverlaySpec


def widget_defaults(overlays: tuple[OverlaySpec, ...], plugins: dict[str, dict]) -> dict[str, dict]:
    """Default setting of every widget in display order, plugins last (template dicts updated in place)"""
    defaults = {spec.name: spec.defaults for spec in overlays}
    # Modern design switch & options of widgets that have a modern design
    add_modern_options(defaults, overlays)
    # Add widget plugins ("plugins" folder)
    defaults.update(plugins)
    # Visibility context (common option): when widget is shown while driving, see widget._base
    # Stream visibility (common option): shown on screen and/or on stream (browser sources), see stream_overlay
    for widget_setting in defaults.values():
        widget_setting.setdefault("visibility_context", "Always")
        widget_setting.setdefault("stream_visibility", "Screen & Stream")
    return defaults


WIDGET_DEFAULT = widget_defaults(OVERLAYS, load_plugin_defaults())
WIDGET_FILENAME = tuple(WIDGET_DEFAULT)
