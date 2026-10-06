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
Modules page backend (qml/Modules.qml): data modules, what they compute, their state and what depends on them

Dependencies are read from compiled code, nothing imported nor run (also in release build): an overlay
depends on a module when its code (classic & modern design, helper modules of the widget package it
imports) reads a module_info field the module fills (minfo.<field>). Modules depending on other modules
are found the same way.
"""

from __future__ import annotations

import dis
import logging
import re
import sys
from collections.abc import Callable, Iterable
from importlib.machinery import ModuleSpec as ImportSpec
from importlib.machinery import PathFinder
from types import CodeType
from typing import NamedTuple

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from ... import app_signal
from ...i18n import tr, trm
from ...i18n.options import module_label
from ...module_control import ModuleControl
from ...setting import cfg
from ..module_view import sort_key
from .models import DictListModel

logger = logging.getLogger(__name__)

FILTER_ALL = 0
FILTER_ACTIVE = 1
FILTER_INACTIVE = 2
WIDGET_PACKAGE = "tinypedal.widget"
MODULE_PACKAGE = "tinypedal.module"
ROLES = (
    "key", "label", "description", "glyph", "active", "running", "failed", "interval", "idleInterval",
    "users", "userCount", "userTotal", "moduleUsers", "needs", "needed", "resets",
)


class ModuleSpec(NamedTuple):
    """Module of the page: icon glyph, data it fills, what it does, data that can be reset"""

    glyph: str  # Segoe Fluent Icons / MDL2 Assets
    fields: tuple[str, ...]  # module_info fields filled (minfo.<field>), read by overlays & other modules
    description: str
    resets: tuple[tuple[str, str], ...] = ()  # (data name, menu.ResetDataMenu method)
    writes: tuple[str, ...] = ()  # module_info fields of other modules it writes into (not a dependency)


MODULE_SPECS = {
    "module_delta": ModuleSpec(
        "", ("delta",),  # stopwatch
        "Lap times and deltas: current, last and best lap, delta to best, session, stint or last lap, "
        "lap pace and validity.",
        (("Delta Best", "reset_deltabest"),),
    ),
    "module_force": ModuleSpec(
        "", ("force",),  # pulse
        "G forces, front and rear downforce, braking rate.",
    ),
    "module_fuel": ModuleSpec(
        "", ("fuel", "energy"),  # gauge
        "Fuel and virtual energy: consumption per lap, laps and time left, amount to add, pit stops to the finish.",
        (("Fuel Delta", "reset_fueldelta"), ("Energy Delta", "reset_energydelta")),
        ("hybrid",),  # fuel / energy ratio & bias
    ),
    "module_hybrid": ModuleSpec(
        "", ("hybrid",),  # lightning
        "Battery charge, drain and regeneration per lap, electric motor state.",
    ),
    "module_mapping": ModuleSpec(
        "", ("mapping",),  # map
        "Track map: records the layout of each track with elevation, sectors, pit entry and exit.",
        (("Track Map", "reset_trackmap"),),
    ),
    "module_notes": ModuleSpec(
        "", ("pacenotes", "tracknotes"),  # quick note
        "Pace notes and track notes at the current position on track.",
    ),
    "module_recorder": ModuleSpec(
        "", (),  # record
        "Records the telemetry of each lap for the Lap Telemetry Viewer, and session replays.",
    ),
    "module_relative": ModuleSpec(
        "", ("relative",),  # people
        "Relative and standings order of every car, for the timing overlays.",
    ),
    "module_sectors": ModuleSpec(
        "", ("sectors",),  # flag
        "Best sectors of the session and of all time, theoretical best lap.",
        (("Sector Best", "reset_sectorbest"),),
    ),
    "module_stats": ModuleSpec(
        "", ("stats",),  # pie chart
        "Driver stats and session history for the Driver Stats Viewer, car setup backups.",
    ),
    "module_stint": ModuleSpec(
        "", ("history",),  # history
        "Stint and consumption history of past laps and stints.",
        (("Consumption History", "reset_consumption"),),
    ),
    "module_vehicles": ModuleSpec(
        "", ("vehicles",),  # car
        "Data of every car: class, laps, gaps, pit stops, nearest traffic, blue and yellow flags.",
    ),
    "module_wheels": ModuleSpec(
        "", ("wheels",),  # sliders
        "Tyre and brake wear per lap, wheel locking, suspension travel, weight distribution and slip.",
    ),
}
DEFAULT_SPEC = ModuleSpec("", (), "")  # chip: module without description


def module_title(name: str) -> str:
    """Module name without the "Module:" prefix of some translations (the page lists modules only)"""
    label = module_label(name)
    title = re.sub(r"^module\s*:\s*", "", label, flags=re.IGNORECASE)
    return title[:1].upper() + title[1:] if title else label


# Dependencies from compiled code
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
        return result


class Dependencies(NamedTuple):
    """Overlays & modules depending on each module (by name), modules each module needs"""

    overlays: dict[str, tuple[str, ...]]
    modules: dict[str, tuple[str, ...]]
    needs: dict[str, tuple[str, ...]]


def producers(module_names: Iterable[str]) -> dict[str, str]:
    """Module filling each module_info field"""
    return {field: name for name in module_names for field in MODULE_SPECS.get(name, DEFAULT_SPEC).fields}


def find_dependencies(widget_names: Iterable[str], module_names: Iterable[str]) -> Dependencies:
    """Overlays & modules using the data of each module, from compiled code (see module docstring)

    Code never changes while app runs: read once per set of names (plugins may add overlays).
    """
    key = (tuple(widget_names), tuple(module_names))
    found = _found_dependencies.get(key)
    if found is None:
        found = _found_dependencies[key] = _find_dependencies(*key)
    return found


_found_dependencies: dict[tuple[tuple[str, ...], tuple[str, ...]], Dependencies] = {}


def _find_dependencies(widget_names: tuple[str, ...], module_names: tuple[str, ...]) -> Dependencies:
    scan = CodeScan()
    producer_of = producers(module_names)
    overlays: dict[str, list[str]] = {name: [] for name in module_names}
    for widget in widget_names:
        fields = scan.fields_of(f"{WIDGET_PACKAGE}.{widget}", WIDGET_PACKAGE)
        fields |= scan.fields_of(f"{WIDGET_PACKAGE}._modern.{widget}", WIDGET_PACKAGE)
        for module in sorted({producer_of[field] for field in fields if field in producer_of}):
            overlays[module].append(widget)
    modules: dict[str, list[str]] = {name: [] for name in module_names}
    needs: dict[str, tuple[str, ...]] = {}
    for name in module_names:
        spec = MODULE_SPECS.get(name, DEFAULT_SPEC)
        own = set(spec.fields) | set(spec.writes)
        fields = scan.fields_of(f"{MODULE_PACKAGE}.{name}", MODULE_PACKAGE) - own
        needed = sorted({producer_of[field] for field in fields if field in producer_of} - {name})
        needs[name] = tuple(needed)
        for other in needed:
            modules[other].append(name)
    return Dependencies(
        {name: tuple(users) for name, users in overlays.items()},
        {name: tuple(users) for name, users in modules.items()},
        needs,
    )


class ModuleBackend(QObject):
    """Modules page state & actions

    Args:
        parent: page widget, parent of config dialogs & messages.
        module_control: module control.
        widget_control: widget control (overlays depending on modules).
        open_config: open config dialog of module (name).
        confirm: ask a yes / no question (message), True if yes.
        show_log: show app log (start errors).
        reset_data: reset saved data of module (menu.ResetDataMenu method name).
    """

    countsChanged = Signal()
    filterChanged = Signal()
    dependenciesChanged = Signal()

    def __init__(
        self,
        parent,
        module_control: ModuleControl,
        widget_control: ModuleControl,
        open_config: Callable[[str], None],
        confirm: Callable[[str], bool],
        show_log: Callable[[], None] = lambda: None,
        reset_data: Callable[[str], None] = lambda method: None,
    ):
        super().__init__(parent)
        self._control = module_control
        self._widgets = widget_control
        self._open_config = open_config
        self._confirm = confirm
        self._show_log = show_log
        self._reset_data = reset_data
        self._dependencies: Dependencies | None = None
        self._rows: list[dict] = []
        self._search = ""
        self._words: tuple[str, ...] = ()
        self._state = FILTER_ALL
        self.rows_model = DictListModel(ROLES, self)
        self.refresh()

    # Dependencies
    def load_dependencies(self, dependencies: Dependencies | None = None):
        """Read dependencies from code (once, about 0.1 s), or set them (tests)"""
        if dependencies is None and self._dependencies is not None:
            return
        if dependencies is None:
            dependencies = find_dependencies(self._widgets.names, self._control.names)
        self._dependencies = dependencies
        self.refresh()
        self.dependenciesChanged.emit()

    @Slot()
    def loadDependenciesLater(self):
        """Read dependencies once page is drawn (page shown at once)"""
        if self._dependencies is None:
            QTimer.singleShot(0, self, self.load_dependencies)

    @Property(bool, notify=dependenciesChanged)
    def dependenciesReady(self) -> bool:
        return self._dependencies is not None

    # Rows
    def _enabled(self, name: str) -> bool:
        return bool(cfg.user.setting[name]["enable"])

    def _row(self, name: str) -> dict:
        spec = MODULE_SPECS.get(name, DEFAULT_SPEC)
        setting = cfg.user.setting[name]
        enabled = bool(setting["enable"])
        running = name in self._control.active_modules
        dependencies = self._dependencies
        users: list[str] = []
        user_total = 0
        module_users: list[str] = []
        needs: list[str] = []
        if dependencies is not None:
            overlays = dependencies.overlays.get(name, ())
            user_total = len(overlays)
            users = sorted(
                (module_label(overlay) for overlay in overlays if overlay in self._widgets.names
                 and cfg.user.setting.get(overlay, {}).get("enable")),
                key=sort_key,
            )
            module_users = sorted(
                (module_title(other) for other in dependencies.modules.get(name, ()) if self._enabled(other)),
                key=sort_key,
            )
            needs = sorted(  # modules it needs that are off
                (module_title(other) for other in dependencies.needs.get(name, ()) if not self._enabled(other)),
                key=sort_key,
            )
        return {
            "key": name,
            "label": module_title(name),
            "description": tr(spec.description) if spec.description else "",
            "glyph": spec.glyph,
            "active": enabled,
            "running": running,
            "failed": enabled and not running,
            "interval": int(setting.get("update_interval", 0)),
            "idleInterval": int(setting.get("idle_update_interval", 0)),
            "users": users,
            "userCount": len(users),
            "userTotal": user_total,
            "moduleUsers": module_users,
            "needs": needs if enabled else [],
            "needed": not enabled and bool(users or module_users),
            "resets": [{"key": method, "label": tr(label)} for label, method in spec.resets],
        }

    def _matches(self, row: dict, use_state: bool = True) -> bool:
        if self._words:
            text = sort_key(f"{row['label']} {row['key'].replace('_', ' ')} {row['description']}")
            if not all(word in text for word in self._words):
                return False
        return not use_state or self._state == FILTER_ALL or (self._state == FILTER_ACTIVE) == row["active"]

    @Slot()
    def refresh(self):
        """Module states & overlays using them read again (setting, preset, toggles on other pages)"""
        self._rows = sorted((self._row(name) for name in self._control.names), key=lambda row: sort_key(row["label"]))
        self._apply()

    def _apply(self):
        self.rows_model.sync([row for row in self._rows if self._matches(row)])
        self.countsChanged.emit()

    def row(self, name: str) -> dict | None:
        return next((row for row in self._rows if row["key"] == name), None)

    @Property(QObject, constant=True)
    def model(self) -> QObject:
        """Shown rows (search & state filter applied)"""
        return self.rows_model

    # Counts
    @Property(int, notify=countsChanged)
    def totalCount(self) -> int:
        return len(self._rows)

    @Property(int, notify=countsChanged)
    def activeCount(self) -> int:
        return sum(row["active"] for row in self._rows)

    @Property(int, notify=countsChanged)
    def failedCount(self) -> int:
        return sum(row["failed"] for row in self._rows)

    @Property(int, notify=countsChanged)
    def shownCount(self) -> int:
        return self.rows_model.rowCount()

    @Property(list, notify=countsChanged)
    def neededNames(self) -> list[str]:
        """Modules off that enabled overlays or modules need"""
        return [row["label"] for row in self._rows if row["needed"]]

    @Property(list, notify=countsChanged)
    def stateCounts(self) -> list[int]:
        """Rows of All, Active & Inactive choice (search applied)"""
        rows = [row for row in self._rows if self._matches(row, use_state=False)]
        active = sum(row["active"] for row in rows)
        return [len(rows), active, len(rows) - active]

    # Filters
    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(int, notify=filterChanged)
    def stateFilter(self) -> int:
        return self._state

    @Property(bool, notify=filterChanged)
    def filtered(self) -> bool:
        return bool(self._words) or self._state != FILTER_ALL

    @Slot(str)
    def setSearch(self, text: str):
        self._search = text
        words = tuple(sort_key(text).split())
        if words != self._words:
            self._words = words
            self._apply()
        self.filterChanged.emit()

    @Slot(int)
    def setStateFilter(self, state: int):
        if state in (FILTER_ALL, FILTER_ACTIVE, FILTER_INACTIVE) and state != self._state:
            self._state = state
            self._apply()
            self.filterChanged.emit()

    @Slot()
    def clearFilters(self):
        self._search = ""
        self._words = ()
        self._state = FILTER_ALL
        self._apply()
        self.filterChanged.emit()

    # Actions
    @Slot(str)
    def toggle(self, name: str):
        if name in self._control.names:
            self._control.toggle(name)
            self.refresh()

    @Slot(str)
    def openConfig(self, name: str):
        if name in self._control.names:
            self._open_config(name)

    @Slot(str, str)
    def resetData(self, name: str, method: str):
        """Reset saved data of module (delta best, fuel delta...), asked first"""
        spec = MODULE_SPECS.get(name, DEFAULT_SPEC)
        if any(method == reset for _, reset in spec.resets):
            self._reset_data(method)
            self.refresh()

    @Slot()
    def showLog(self):
        self._show_log()

    @Slot()
    def enableShown(self):
        self._set_shown(True)

    @Slot()
    def disableShown(self):
        self._set_shown(False)

    @Slot()
    def enableNeeded(self):
        """Enable modules off that enabled overlays or modules need"""
        names = [row["key"] for row in self._rows if row["needed"]]
        if names:
            for name in names:
                self._control.toggle(name)
            app_signal.refresh.emit(True)
            self.refresh()

    def _set_shown(self, enable: bool):
        """Enable or disable shown modules (every module without filter), confirmed if set so"""
        shown = [row["key"] for row in self._rows if self._matches(row)]
        names = [name for name in shown if self._enabled(name) != enable]
        if not names:
            return
        word = "Enable" if enable else "Disable"
        everything = not self.filtered or len(names) == len(self._rows)
        if cfg.application["show_confirmation_for_batch_toggle"]:
            text = f"<b>{word}</b> all modules?" if everything else f"<b>{word}</b> {len(names)} shown modules?"
            if not self._confirm(trm(text)):
                return
        if everything:
            if enable:
                self._control.enable_all()
            else:
                self._control.disable_all()
        else:
            for name in names:
                self._control.toggle(name)
        app_signal.refresh.emit(True)  # other pages & menus follow, rows updated by refresh
        self.refresh()
