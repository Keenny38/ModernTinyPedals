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
Default widget setting templates, grouped by category

Each module holds default options of its widgets, merged here into WIDGET_CATEGORIES.
Every built-in overlay is declared in registry.OVERLAYS (display order, category, modern design...),
tables below are derived from it. WIDGET_DISPLAY_ORDER sets the order of widget list in UI & keybinding.
"""

from .registry import OVERLAYS, TEMPLATE_GROUPS, display_order, option_ui_of

# Template groups, merged in this order (see setting_widget)
WIDGET_CATEGORIES = tuple(TEMPLATE_GROUPS.values())

# Config dialog extras for widgets with many options: sections, simple mode, color themes,
# profile overrides (see black_box_ui.OptionUI)
WIDGET_OPTION_UI = option_ui_of(OVERLAYS)
# Config dialog sections per widget: {widget: {first option of section: section title}}
WIDGET_OPTION_SECTIONS = {name: ui.sections for name, ui in WIDGET_OPTION_UI.items()}

# Display order of widget list (UI, keyboard shortcuts)
WIDGET_DISPLAY_ORDER = display_order(OVERLAYS)
