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
Default widget setting template

Widget default options are grouped by category in "widget" package, plugins are added here.
Widget key name must match corresponding file name in 'widget' folder
"""

from ..plugin_loader import load_plugin_defaults
from .widget import WIDGET_CATEGORIES, WIDGET_DISPLAY_ORDER

# Merge categories in display order
_widgets = {}
for _category in WIDGET_CATEGORIES:
    _widgets.update(_category)
WIDGET_DEFAULT = {_name: _widgets.pop(_name) for _name in WIDGET_DISPLAY_ORDER}
if _widgets:  # widget added to a category but missing from display order
    raise RuntimeError(f"widget missing from WIDGET_DISPLAY_ORDER: {sorted(_widgets)}")

# Add widget plugins ("plugins" folder)
WIDGET_DEFAULT.update(load_plugin_defaults())

# Per widget overlay theme (common option), "Global" = use overlay style theme
for _widget_setting in WIDGET_DEFAULT.values():
    _widget_setting.setdefault("widget_theme", "Global")

WIDGET_FILENAME = tuple(WIDGET_DEFAULT)
