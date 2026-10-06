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
Module and widget control
"""

from __future__ import annotations

import logging
from collections.abc import KeysView
from types import MappingProxyType
from typing import Any

from . import module, widget
from .const_file import ConfigType
from .plugin_loader import PLUGIN_ERRORS, PLUGIN_PREFIX
from .setting import cfg
from .thread_guard import wait_stopped
from .widget._modern import modern_module, uses_modern_design

logger = logging.getLogger(__name__)


def create_module_pack(target: Any) -> dict:
    """Create module reference pack as dictionary, modules imported when first started

    Args:
        target: module.

    Returns:
        Dictionary, key = module name. value = imported module, None until first used.
    """
    return dict.fromkeys(target.__all__)


class ModuleControl:
    """Module and widget control

    Args:
        target: module.

    Attributes:
        type_id: module type indentifier, either "module" or "widget".
        active_modules: active module reference dict (read-only).
    """

    __slots__ = (
        "_target",
        "_module_pack",
        "_imported_modules",
        "_active_modules",
        "type_id",
        "active_modules",
    )

    def __init__(self, target: Any, type_id: str):
        self._target = target
        self._module_pack = create_module_pack(target)
        self._imported_modules = MappingProxyType(self._module_pack)
        self._active_modules: dict = {}
        self.type_id = type_id
        self.active_modules: MappingProxyType = MappingProxyType(self._active_modules)

    def start(self, name: str = ""):
        """Start module, specify name for selected module"""
        if name:
            self.__start_selected(name)
        else:
            self.__start_enabled()

    def close(self, name: str = "", discard: bool = False):
        """Close module, specify name for selected module

        Args:
            name: selected module name, all modules if not set.
            discard: discard data of module not saved yet (data reset), modules only.
        """
        if name:
            self.__close_selected(name, discard)
        else:
            self.__close_enabled(discard)

    def reload(self, name: str = "", discard: bool = False):
        """Reload module

        Args:
            name: selected module name, all modules if not set.
            discard: discard data of module not saved yet (data reset), modules only.
        """
        self.close(name, discard)
        self.start(name)

    def replace(self, name: str, new_module: Any):
        """Replace module code (plugin hot reload), restart if active"""
        was_active = name in self._active_modules
        self.close(name)
        self._module_pack[name] = new_module
        if was_active:
            self.start(name)

    def toggle(self, name: str):
        """Toggle module"""
        if cfg.user.setting[name]["enable"]:
            cfg.user.setting[name]["enable"] = False
            self.__close_selected(name)
        else:
            cfg.user.setting[name]["enable"] = True
            self.__start_selected(name)
        cfg.save()

    def enable_all(self):
        """Enable all modules"""
        for _name in self._imported_modules:
            cfg.user.setting[_name]["enable"] = True
        self.start()
        cfg.save()
        logger.info("ENABLED: all %s(s)", self.type_id)

    def disable_all(self):
        """Disable all modules"""
        for _name in self._imported_modules:
            cfg.user.setting[_name]["enable"] = False
        self.close()
        cfg.save()
        logger.info("DISABLED: all %s(s)", self.type_id)

    def __start_enabled(self):
        """Start all enabled module"""
        for _name in self._imported_modules:
            self.__start_selected(_name)

    def __start_selected(self, name: str):
        """Start selected module, a module failing to start is skipped (error logged)"""
        if cfg.user.setting[name]["enable"] and name not in self._active_modules:
            # Create module instance and add to dict
            try:
                if self.type_id == ConfigType.WIDGET and uses_modern_design(cfg, name):
                    target = modern_module(name)  # classic widget code not loaded
                else:
                    target = self.module_of(name)
                instance = target.Realtime(cfg, name)
            except Exception as error:  # plugin or invalid option must not stop app
                self.__start_failed(name, error)
                return
            self._active_modules[name] = instance
            try:
                instance.start()
            except Exception as error:
                self.__start_failed(name, error)
                self.__close_selected(name)

    def __start_failed(self, name: str, error: Exception):
        """Log module start error, shown in plugin manager for plugin widget"""
        logger.error("ERROR: unable to start %s: %s", name, error, exc_info=True)
        if name.startswith(PLUGIN_PREFIX):
            PLUGIN_ERRORS[name] = f"{type(error).__name__}: {error}"

    def __close_enabled(self, discard: bool = False):
        """Close all enabled module"""
        for _name in tuple(self._active_modules):
            self.__close_selected(_name, discard)

    def __close_selected(self, name: str, discard: bool = False):
        """Close selected module, wait (bounded) until closed"""
        if name in self._active_modules:
            _module = self._active_modules[name]  # get instance
            self._active_modules.pop(name)  # remove active reference
            try:
                if discard and self.type_id == ConfigType.MODULE:
                    _module.stop(discard=True)  # close module without saving data
                else:
                    _module.stop()  # close module
            except Exception:  # widget failed half-way to start
                logger.exception("ERROR: unable to close %s", name)
                return
            wait_stopped(lambda: _module.closed, name)  # wait finish
            _module = None  # remove final reference

    def module_of(self, name: str) -> Any:
        """Module code of name, imported on first use (disabled overlays never loaded)"""
        loaded = self._module_pack[name]
        if loaded is None:
            loaded = self._module_pack[name] = getattr(self._target, name)
        return loaded

    @property
    def number_active(self) -> int:
        """Number of active modules"""
        return len(self._active_modules)

    @property
    def number_total(self) -> int:
        """Number of total modules"""
        return len(self._imported_modules)

    @property
    def names(self) -> KeysView[str]:
        """List of module names"""
        return self._imported_modules.keys()


mctrl = ModuleControl(target=module, type_id=ConfigType.MODULE)
wctrl = ModuleControl(target=widget, type_id=ConfigType.WIDGET)
