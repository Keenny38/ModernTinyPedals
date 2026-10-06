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
Widget modules

Built-in widget modules are imported when first used (widget started, preview drawn):
disabled overlays never load their code. Plugin widgets are loaded here (trust checked once).
"""

from importlib import import_module
from types import ModuleType

from ..plugin_loader import PLUGIN_PREFIX, load_plugin_widget
from ..template.setting_widget import WIDGET_FILENAME

__all__ = WIDGET_FILENAME

for _plugin_name in WIDGET_FILENAME:
    if _plugin_name.startswith(PLUGIN_PREFIX):
        globals()[_plugin_name] = load_plugin_widget(__name__, _plugin_name)


def __getattr__(name: str) -> ModuleType:
    """Widget module imported on first access (tinypedal.widget.<name>)"""
    if name in WIDGET_FILENAME:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
