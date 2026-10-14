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
Module and widget control
"""

from __future__ import annotations

import dis
import logging
import sys
from collections.abc import Callable, Iterable, KeysView, Mapping
from importlib.machinery import ModuleSpec as ImportSpec
from importlib.machinery import PathFinder
from time import monotonic
from types import CodeType, MappingProxyType
from typing import Any

from . import app_signal, module, realtime_state, widget
from .const_file import ConfigType
from .plugin_loader import PLUGIN_ERRORS, PLUGIN_PREFIX
from .setting import cfg
from .template.setting_module import FEATURE_MODULES, MODULE_ON_DEMAND
from .thread_guard import STOP_TIMEOUT, wait_all_stopped
from .widget._modern import modern_module, uses_modern_design

logger = logging.getLogger(__name__)
STOPPING_POLL_MS = 10  # single module stopped without waiting: interval checking whether stopped
WIDGET_PACKAGE = "neopedal.widget"
MODULE_PACKAGE = "neopedal.module"


def event_loop_running() -> bool:
    """Whether current thread runs a Qt event loop (GUI thread of started app): timers fire, never block it"""
    from PySide6.QtCore import QCoreApplication, QThread
    return QCoreApplication.instance() is not None and QThread.currentThread().loopLevel() > 0


# Dependencies from compiled code (also read by Modules page, see ui.quick.module_backend)
def find_spec(name: str) -> ImportSpec | None:
    """Import spec of module name, nothing imported (parent packages found the same way)"""
    module = sys.modules.get(name)
    if module is not None:
        return getattr(module, "__spec__", None)
    parent, _, _ = name.rpartition(".")
    if not parent:
        return None
    parent_spec = find_spec(parent)
    locations = None if parent_spec is None else parent_spec.submodule_search_locations
    if not locations:
        return None
    try:  # path entry finders: source files & release build archive
        return PathFinder.find_spec(name, list(locations))
    except (ImportError, ValueError, OSError):
        return None


def module_code(name: str) -> tuple[CodeType | None, bool]:
    """Compiled code of module (not run) & whether it is a package, None if not found"""
    spec = find_spec(name)
    get_code = getattr(spec.loader, "get_code", None) if spec is not None else None
    if get_code is None:
        return None, False
    try:
        return get_code(name), spec.submodule_search_locations is not None  # type: ignore[union-attr]
    except Exception:  # source with syntax error, archive entry missing
        logger.debug("Modules page: no code for %s", name, exc_info=True)
        return None, False


def resolve_import(module_name: str, is_package: bool, name: str, level: int, fromlist) -> set[str]:
    """Module names an import statement may load (from x import y: x, and x.y if y is a module)"""
    if level:
        parts = module_name.split(".")
        if not is_package:
            parts = parts[:-1]
        if level > 1:
            parts = parts[:len(parts) - (level - 1)]
        base = ".".join(parts)
        target = f"{base}.{name}" if name else base
    else:
        target = name
    found = {target}
    if isinstance(fromlist, tuple):
        found.update(f"{target}.{item}" for item in fromlist if isinstance(item, str) and item != "*")
    return found


# Opcodes read by scan_code (wordcode: opcode & argument bytes, inline cache entries are CACHE opcodes)
_OPCODES = dis.opmap
_CACHE = _OPCODES["CACHE"]
_EXTENDED_ARG = _OPCODES["EXTENDED_ARG"]
_LOAD_GLOBAL = _OPCODES["LOAD_GLOBAL"]  # name index << 1 (Python 3.11+)
_LOAD_NAME = {_OPCODES[name] for name in ("LOAD_NAME", "LOAD_FROM_DICT_OR_GLOBALS") if name in _OPCODES}
_LOAD_ATTR = _OPCODES["LOAD_ATTR"]
_ATTR_SHIFT = 1 if sys.version_info >= (3, 12) else 0  # name index << 1 since Python 3.12
_LOAD_CONST = _OPCODES["LOAD_CONST"]
_LOAD_SMALL_INT = _OPCODES.get("LOAD_SMALL_INT", -1)  # Python 3.14
_IMPORT_NAME = _OPCODES["IMPORT_NAME"]


def _instructions(code: CodeType):
    """(opcode, argument) of code, cache entries left out (much faster than dis.get_instructions)"""
    raw = code.co_code
    extended = 0
    for index in range(0, len(raw), 2):
        opcode = raw[index]
        if opcode == _CACHE:
            continue
        argument = raw[index + 1] | extended
        if opcode == _EXTENDED_ARG:
            extended = argument << 8
            continue
        extended = 0
        yield opcode, argument


def scan_code(code: CodeType, module_name: str, is_package: bool) -> tuple[frozenset[str], frozenset[str]]:
    """module_info fields read (minfo.<field>, nested functions & classes included) & modules imported
    at module level by code"""
    fields: set[str] = set()
    imports: set[str] = set()
    stack = [(code, True)]
    while stack:
        current, top = stack.pop()
        names = current.co_names
        if top or "minfo" in names:  # other code objects have nothing to read
            after_minfo = False
            consts: list = []
            for opcode, argument in _instructions(current):
                if opcode == _LOAD_GLOBAL:
                    after_minfo = names[argument >> 1] == "minfo"
                    continue
                if opcode in _LOAD_NAME:
                    after_minfo = names[argument] == "minfo"
                    continue
                if opcode == _LOAD_ATTR and after_minfo:
                    fields.add(names[argument >> _ATTR_SHIFT])
                elif top:
                    if opcode == _LOAD_CONST:
                        consts.append(current.co_consts[argument])
                    elif opcode == _LOAD_SMALL_INT:
                        consts.append(argument)
                    elif opcode == _IMPORT_NAME and len(consts) >= 2 and isinstance(consts[-2], int):
                        imports.update(resolve_import(module_name, is_package, names[argument], consts[-2], consts[-1]))
                after_minfo = False
        stack.extend((const, False) for const in current.co_consts if isinstance(const, CodeType))
    return frozenset(fields), frozenset(imports)


class CodeScan:
    """module_info fields read by modules & the modules of their package they import (cached)"""

    def __init__(self):
        self._scanned: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        self._missing: set[str] = set()  # code not found

    def fields_of(self, name: str, package: str) -> set[str]:
        """Fields read by module name & modules of package it imports (any depth)"""
        found: set[str] = set()
        pending = [name]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            fields, imports = self._scan(current)
            found |= fields
            pending.extend(imported for imported in imports if imported.startswith(f"{package}."))
        return found

    def _scan(self, name: str) -> tuple[frozenset[str], frozenset[str]]:
        result = self._scanned.get(name)
        if result is None:
            code, is_package = module_code(name)
            result = scan_code(code, name, is_package) if code is not None else (frozenset(), frozenset())
            self._scanned[name] = result
            if code is None:
                self._missing.add(name)
        return result

    def clear(self):
        """Forget scanned code (code replaced)"""
        self._scanned.clear()
        self._missing.clear()

    def found(self, name: str) -> bool:
        """Whether code of module name was found (scanned first)"""
        self._scan(name)
        return name not in self._missing


_demand_scan = CodeScan()  # code never changes while app runs (plugin replaced: forgotten)


def overlay_fields(name: str, scan: CodeScan | None = None) -> set[str] | None:
    """module_info fields read by overlay (classic & modern design), None if its code is not found (plugin)"""
    scan = _demand_scan if scan is None else scan
    classic, modern = f"{WIDGET_PACKAGE}.{name}", f"{WIDGET_PACKAGE}._modern.{name}"
    fields = scan.fields_of(classic, WIDGET_PACKAGE) | scan.fields_of(modern, WIDGET_PACKAGE)
    if not scan.found(classic) and not scan.found(modern):
        return None
    return fields


def needed_on_demand(
    on_demand: Mapping[str, tuple[str, ...]], overlay_names: Iterable[str], module_names: Iterable[str],
    setting: Mapping[str, Any], scan: CodeScan | None = None,
) -> frozenset[str]:
    """On demand modules needed by enabled overlays, enabled features & modules running (any depth)

    Args:
        on_demand: on demand modules, with module_info fields each fills.
        overlay_names: overlay names (enabled ones read from setting).
        module_names: module names.
        setting: user setting (each name: dict with "enable").
        scan: code scan, shared cache if None.
    """
    scan = _demand_scan if scan is None else scan
    producer = {field: name for name, fields in on_demand.items() for field in fields}
    if not producer:
        return frozenset()

    def enabled(name: str) -> bool:
        options = setting.get(name)
        return isinstance(options, dict) and bool(options.get("enable"))

    needed: set[str] = set()
    for feature, names in FEATURE_MODULES.items():
        if enabled(feature):
            needed.update(name for name in names if name in on_demand)
    for overlay in overlay_names:
        if enabled(overlay):
            fields = overlay_fields(overlay, scan)
            if fields is None:  # overlay of unknown code (plugin) may read any data
                needed.update(on_demand)
            else:
                needed.update(producer[field] for field in fields if field in producer)
    # Modules running (always on, or on demand & needed) needing on demand modules
    pending = [name for name in module_names if enabled(name) and (name not in on_demand or name in needed)]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        for field in scan.fields_of(f"{MODULE_PACKAGE}.{name}", MODULE_PACKAGE):
            other = producer.get(field)
            if other is not None and other != name and other not in needed:
                needed.add(other)
                pending.append(other)
    return frozenset(needed)


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
        type_id: module type indentifier.
        on_demand: modules run on demand (enabled & needed, see needed_on_demand), with fields each fills.

    Attributes:
        type_id: module type indentifier, either "module" or "widget".
        active_modules: active module reference dict (read-only).

    On demand modules: enabled one runs only while needed by enabled overlays (widget control watched,
    see watch), features or running modules, recomputed on start of all (preset load), overlay started or
    closed, module toggled & app refresh. Disabled one never runs.
    """

    __slots__ = (
        "_target",
        "_module_pack",
        "_imported_modules",
        "_active_modules",
        "_stopping",
        "_stop_deadline",
        "_stop_timeout",
        "_start_pending",
        "_held",
        "_polling",
        "_on_demand",
        "_needed",
        "_demand_ready",
        "_watched",
        "_listeners",
        "_batch",
        "type_id",
        "active_modules",
        "__weakref__",  # bound methods connected to Qt signals (update_demand): weak reference kept by PySide
    )

    def __init__(self, target: Any, type_id: str, on_demand: Mapping[str, tuple[str, ...]] | None = None):
        self._target = target
        self._module_pack = create_module_pack(target)
        self._imported_modules = MappingProxyType(self._module_pack)
        self._active_modules: dict = {}
        # Modules signalled to stop by stop_all (reload), not yet seen stopped: name, (name, is_stopped, wait)
        self._stopping: dict[str, tuple] = {}
        self._stop_deadline = 0.0
        self._stop_timeout = STOP_TIMEOUT
        self._start_pending: set[str] = set()  # started while previous instance stopping: started once stopped
        self._held = False  # stop_all (reload) until start of all: pending starts left to it
        self._polling = False  # stopping polled by timer, see __poll_stopping
        self._on_demand = {name: tuple(fields) for name, fields in (on_demand or {}).items() if name in self._module_pack}
        self._needed: frozenset[str] = frozenset()  # on demand modules needed
        self._demand_ready = False  # demand known: after start of all, until close or stop of all
        self._watched: ModuleControl | None = None  # widget control: overlays needing on demand modules
        self._listeners: list[Callable[[], None]] = []  # called once active modules changed
        self._batch = 0  # start or close of all running: listeners called once at end
        self.type_id = type_id
        self.active_modules: MappingProxyType = MappingProxyType(self._active_modules)

    def start(self, name: str = ""):
        """Start module, specify name for selected module"""
        if name:
            self.__start_selected(name)
        else:
            self.__start_enabled()

    def close(self, name: str = "", discard: bool = False, wait: bool | None = None):
        """Close module, specify name for selected module

        Args:
            name: selected module name, all modules if not set.
            discard: discard data of module not saved yet (data reset), modules only.
            wait: selected module only, wait until stopped (bounded). Default: only if current thread
                runs no event loop (quit, tests, other thread), else stopping polled by timer (GUI kept
                running while module saves), and module started again only once stopped.
        """
        if name:
            if wait is None:
                wait = not event_loop_running()
            self.__close_selected(name, discard, wait)
        else:
            self.__close_enabled(discard)

    def stop_all(self, discard: bool = False):
        """Signal all active modules to stop without waiting (reload: GUI & event loop kept running)

        Stopped ones are polled with stopping(), or waited with wait_stopping(). A module is never
        started again (start, close) before its previous instance stopped or its stop timeout passed.
        """
        busy = bool(self._stopping)
        self._held = True
        self._demand_ready = False
        self._start_pending.clear()  # started by start of all after reload
        timeout = STOP_TIMEOUT
        self._batch += 1
        try:
            for _name in tuple(self._active_modules):
                timeout = max(timeout, self.__stop_timeout(_name))
                target = self.__stop_selected(_name, discard)
                if target is not None:
                    self._stopping[_name] = target
        finally:
            self._batch -= 1
        self.__changed()
        if self._stopping:
            deadline = monotonic() + timeout
            if busy:  # earlier ones still stopping: never given less time
                deadline = max(deadline, self._stop_deadline)
                timeout = max(timeout, self._stop_timeout)
            self._stop_deadline = deadline
            self._stop_timeout = timeout

    def stopping(self) -> bool:
        """Whether a module signalled by stop_all is still running, one past stop timeout logged & forgotten"""
        if not self._stopping:
            return False
        expired = monotonic() >= self._stop_deadline
        for _name, target in tuple(self._stopping.items()):
            if target[1]():
                del self._stopping[_name]
            elif expired:
                del self._stopping[_name]
                logger.error("ERROR: %s not stopped after %ss, continue anyway", _name, self._stop_timeout)
        return bool(self._stopping)

    def wait_stopping(self, names: Iterable[str] | None = None) -> bool:
        """Wait (bounded by stop timeout of stop_all) until modules signalled by stop_all stopped

        Args:
            names: module names, all modules signalled if None.

        Returns:
            True if all stopped, False if gave up on any (error logged).
        """
        targets = [
            self._stopping.pop(_name) for _name in (tuple(self._stopping) if names is None else names)
            if _name in self._stopping
        ]
        if not targets:
            return True
        return wait_all_stopped(targets, self._stop_timeout, self._stop_deadline)

    def reload(self, name: str = "", discard: bool = False):
        """Reload module, selected module started again once stopped (see close)

        Args:
            name: selected module name, all modules if not set.
            discard: discard data of module not saved yet (data reset), modules only.
        """
        self.close(name, discard)
        self.start(name)

    def replace(self, name: str, new_module: Any):
        """Replace module code (plugin hot reload), restart if active"""
        was_active = name in self._active_modules
        self.close(name, wait=True)  # old code never runs again after replaced
        self._module_pack[name] = new_module
        _demand_scan.clear()  # code read again
        if was_active:
            self.start(name)

    def toggle(self, name: str, wait: bool | None = None):
        """Toggle module, never waits for module stop work (saving) on GUI thread, see close

        Enabled on demand module runs only if needed (see should_run).
        """
        if wait is None:
            wait = not event_loop_running()
        if cfg.user.setting[name]["enable"]:
            cfg.user.setting[name]["enable"] = False
            self.__close_selected(name, wait=wait)
        else:
            cfg.user.setting[name]["enable"] = True
            self.__start_selected(name, wait)
        cfg.save()
        self.update_demand()  # module needing (or no longer needing) on demand modules

    def should_run(self, name: str) -> bool:
        """Whether module runs: enabled, and needed if on demand"""
        return bool(cfg.user.setting[name]["enable"]) and (name not in self._on_demand or name in self._needed)

    def watch(self, widget_control: ModuleControl):
        """Overlays of widget control decide which on demand modules run, recomputed once overlays changed"""
        self._watched = widget_control
        widget_control.add_listener(self.update_demand)

    def add_listener(self, listener: Callable[[], None]):
        """Call listener once active modules changed (start, close, reload of all: once at end)"""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def update_demand(self, *_):
        """Start on demand modules needed, close ones no longer needed (see needed_on_demand)

        Only between start of all & close or stop of all (preset loaded), never waits on GUI thread.
        """
        if not self._on_demand or not self._demand_ready:
            return
        self._needed = self.__find_needed()
        for name in self._on_demand:
            if self.should_run(name):
                if name not in self._active_modules and name not in self._start_pending:
                    self.__start_selected(name)
            elif name in self._active_modules:
                logger.info("DEMAND: %s no longer needed", name)
                self.__close_selected(name, wait=not event_loop_running())

    def __find_needed(self) -> frozenset[str]:
        """On demand modules needed now"""
        if not self._on_demand:
            return frozenset()
        overlays = self._watched.names if self._watched is not None else ()
        try:
            return needed_on_demand(self._on_demand, overlays, self._imported_modules, cfg.user.setting)
        except Exception:  # unreadable code: every on demand module runs, as without demand
            logger.exception("ERROR: unable to find modules needed, all enabled modules run")
            return frozenset(self._on_demand)

    def __changed(self):
        """Active modules changed: running overlays published (realtime_state.overlays), listeners called"""
        if self._batch:
            return
        if self.type_id == ConfigType.WIDGET:
            realtime_state.overlays = frozenset(self._active_modules)
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:
                logger.exception("ERROR: module control listener failed")

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
        """Start all enabled module (on demand ones if needed)"""
        self._held = False
        self._start_pending.clear()
        self._demand_ready = True
        self._needed = self.__find_needed()
        self._batch += 1
        try:
            for _name in self._imported_modules:
                self.__start_selected(_name)
        finally:
            self._batch -= 1
        self.__changed()

    def __start_selected(self, name: str, wait: bool | None = None):
        """Start selected module, a module failing to start is skipped (error logged)

        Previous instance still stopping: waited (bounded), or if not wait (default: current thread runs
        an event loop) module started once stopped (polled by timer).
        """
        if self.should_run(name) and name not in self._active_modules:
            stopping = self._stopping.get(name)
            if stopping is not None:  # previous instance stopping (reload, toggle)
                if stopping[1]():
                    del self._stopping[name]
                else:
                    if wait is None:
                        wait = not event_loop_running()
                    if not wait:
                        self._start_pending.add(name)
                        self.__poll_later()
                        return
                    self.wait_stopping((name,))
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
                return
            self.__changed()

    def __start_failed(self, name: str, error: Exception):
        """Log module start error, shown in plugin manager for plugin widget"""
        logger.error("ERROR: unable to start %s: %s", name, error, exc_info=True)
        if name.startswith(PLUGIN_PREFIX):
            PLUGIN_ERRORS[name] = f"{type(error).__name__}: {error}"

    def __close_enabled(self, discard: bool = False):
        """Close all enabled module, stop all first then wait (bounded, shared deadline) until closed"""
        self._start_pending.clear()  # never started after closed
        self._demand_ready = False
        stopping = []
        timeout = STOP_TIMEOUT
        self._batch += 1
        try:
            for _name in tuple(self._active_modules):
                timeout = max(timeout, self.__stop_timeout(_name))
                target = self.__stop_selected(_name, discard)
                if target is not None:
                    stopping.append(target)
        finally:
            self._batch -= 1
        self.__changed()
        if self._stopping:  # signalled by stop_all earlier (quit during reload)
            stopping.extend(self._stopping.values())
            self._stopping.clear()
            timeout = max(timeout, self._stop_deadline - monotonic())
        wait_all_stopped(stopping, timeout)  # wait finish

    def __close_selected(self, name: str, discard: bool = False, wait: bool = True):
        """Close selected module, wait (bounded) until closed, or poll stopping if not wait"""
        self._start_pending.discard(name)
        timeout = self.__stop_timeout(name)
        target = self.__stop_selected(name, discard)
        if target is not None:
            if wait:
                wait_all_stopped((target,), timeout)  # wait finish
            elif not target[1]():  # stop work left (saving), polled
                self.__add_stopping(name, target, timeout)
        elif name in self._stopping and wait:  # signalled earlier
            self.wait_stopping((name,))

    def __add_stopping(self, name: str, target: tuple, timeout: float):
        """Module signalled to stop polled until stopped, never given less time than earlier ones"""
        deadline = monotonic() + timeout
        if self._stopping:
            deadline = max(deadline, self._stop_deadline)
            timeout = max(timeout, self._stop_timeout)
        self._stopping[name] = target
        self._stop_deadline = deadline
        self._stop_timeout = timeout
        self.__poll_later()

    def __poll_later(self):
        """Poll stopping modules by timer (once at a time)"""
        if not self._polling:
            from PySide6.QtCore import QTimer

            self._polling = True
            QTimer.singleShot(STOPPING_POLL_MS, self.__poll_stopping)

    def __poll_stopping(self):
        """Forget stopped modules (timeouts logged), start modules waiting for previous instance stopped"""
        self._polling = False
        busy = self.stopping()
        started = False
        if not self._held:
            for _name in tuple(self._start_pending):
                if _name not in self._stopping:
                    self._start_pending.discard(_name)
                    self.__start_selected(_name, wait=True)
                    started = True
        if started:
            from . import app_signal

            app_signal.refresh.emit(True)  # pages & menus show started modules
        if busy or (self._start_pending and not self._held):
            self.__poll_later()

    def __stop_timeout(self, name: str) -> float:
        """Longest wait for active module to stop: its own stop work may take longer (saving), never started
        again while previous instance still running"""
        timeout = getattr(self._active_modules.get(name), "STOP_TIMEOUT", STOP_TIMEOUT)
        return timeout if isinstance(timeout, (int, float)) else STOP_TIMEOUT

    def __stop_selected(self, name: str, discard: bool = False) -> tuple | None:
        """Signal selected module to stop, without waiting

        Returns:
            (name, is_stopped, wait) for wait_all_stopped, None if not active or failed to stop.
        """
        if name not in self._active_modules:
            return None
        _module = self._active_modules.pop(name)  # remove active reference
        self.__changed()
        try:
            if discard and self.type_id == ConfigType.MODULE:
                _module.stop(discard=True)  # close module without saving data
            else:
                _module.stop()  # close module
        except Exception:  # widget failed half-way to start
            logger.exception("ERROR: unable to close %s", name)
            return None
        # Data module waits on its thread finished event, widget (closed in UI thread) polls
        return name, lambda: _module.closed, getattr(_module, "wait_closed", None)

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


mctrl = ModuleControl(target=module, type_id=ConfigType.MODULE, on_demand=MODULE_ON_DEMAND)
wctrl = ModuleControl(target=widget, type_id=ConfigType.WIDGET)
mctrl.watch(wctrl)
app_signal.refresh.connect(mctrl.update_demand)  # features needing modules toggled (pace notes playback)
