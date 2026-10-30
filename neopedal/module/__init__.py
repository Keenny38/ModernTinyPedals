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
Data modules

Imported when first used (module started, see module_control.ModuleControl.module_of): disabled modules
never load their code nor their dependencies (recorder: replay & lap cache, stats: results & driver files).
"""

from importlib import import_module
from types import ModuleType

from ..template.setting_module import MODULE_FILENAME

__all__ = MODULE_FILENAME


def __getattr__(name: str) -> ModuleType:
    """Data module imported on first access (neopedal.module.<name>)"""
    if name in MODULE_FILENAME:
        return import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
