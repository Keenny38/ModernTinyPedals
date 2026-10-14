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
App context: the app-wide objects (game data API, settings, module data, module & overlay controls) given to an
object instead of read from module globals, so a test can hand it fakes

New code takes a context (widget Base, DataModule & PageBackend have `ctx`, default app_context()). Code reading
game data many times a frame keeps its module globals (or binds ctx values to locals once): an attribute lookup
per value read costs, and rewriting every reader brings nothing. Tests swap the globals & the default context
together with the app_ctx fixture (tests/conftest.py).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api_control import APIControl
    from .module_control import ModuleControl
    from .module_info import ModuleInfo
    from .overlay_control import OverlayControl
    from .setting import Setting

# Fields of AppContext: module & name of the global each one is by default
GLOBALS: dict[str, tuple[str, str]] = {
    "api": ("neopedal.api_control", "api"),
    "cfg": ("neopedal.setting", "cfg"),
    "minfo": ("neopedal.module_info", "minfo"),
    "mctrl": ("neopedal.module_control", "mctrl"),
    "wctrl": ("neopedal.module_control", "wctrl"),
    "octrl": ("neopedal.overlay_control", "octrl"),
}


@dataclass(frozen=True, slots=True)
class AppContext:
    """App-wide objects: game data API, settings, module data, module & widget controls, overlay control

    Frozen: a different context is a new one (with_), objects themselves keep their own state.
    """

    api: APIControl
    cfg: Setting
    minfo: ModuleInfo
    mctrl: ModuleControl
    wctrl: ModuleControl
    octrl: OverlayControl

    def with_(self, **changes: Any) -> AppContext:
        """Same context, some objects replaced (fakes of a test)"""
        return replace(self, **changes)


_default: AppContext | None = None


def app_context() -> AppContext:
    """Context of the app: the real globals (made on first use: imported once the app is loaded, no import cycle
    with the widgets & modules using it)"""
    global _default
    if _default is None:
        _default = real_context()
    return _default


def real_context() -> AppContext:
    """Context of the app globals as they are now (module attributes read again)"""
    import importlib

    values = {name: getattr(importlib.import_module(module), attribute)
              for name, (module, attribute) in GLOBALS.items()}
    return AppContext(**values)


def set_app_context(context: AppContext | None) -> AppContext | None:
    """Default context replaced (tests: app_ctx fixture), None: real globals again; previous one returned"""
    global _default
    previous, _default = _default, context
    return previous
