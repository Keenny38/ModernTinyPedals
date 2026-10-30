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
Hotkeys page backend (qml/Hotkeys.qml): key bindings by section, global hotkey switch, key capture

Rows: one header per section (General, Spectate, Broadcast Director, Preset, Overlays, Module: collapsible, with
counts), then its bindings (search & "assigned only" filter applied). A binding shared by several actions is
marked on each of them. Clearing a binding (one, or all) is immediate, undone from the toast.
Key capture (dialog of the page): pressed keys, mouse & game controller buttons read every 200 ms while the
dialog shows on the visible page; meanwhile global hotkeys are off and key events of the whole app go to the
capture (Esc excepted), so any key combination can be bound.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from PySide6.QtCore import Property, QEvent, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget

from ... import app_signal
from ...const_app import PLATFORM
from ...const_file import ConfigType, FileExt
from ...hotkey.common import (
    format_hotkey_name,
    get_key_state_function,
    held_controller_buttons,
    held_modifiers,
    refresh_keystate,
    set_hotkey,
)
from ...hotkey_control import kctrl
from ...i18n import tr, trm
from ...i18n.options import option_label
from ...setting import cfg
from ...template.setting_shortcuts import (
    SHORTCUTS_GENERAL,
    SHORTCUTS_MODULE,
    SHORTCUTS_PRESET,
    SHORTCUTS_WIDGET,
)
from ..module_view import sort_key
from .models import DictListModel
from .page_backend import PageBackend

CAPTURE_INTERVAL = 200  # ms between two reads of pressed keys & buttons
# Key events kept from app while capturing a key (shortcut override accepted: no app shortcut run)
CAPTURED_KEY_EVENTS = frozenset((QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease))
SECTION_PREFIX = "section:"  # header row keys
ROLES = (
    "key", "header", "section", "label", "binding", "bound", "isPreset", "preset", "conflict", "count", "assigned",
    "expanded",
)


def section_of(name: str) -> str:
    """Section of a binding: General, Spectate, Broadcast Director, Preset, Overlays or Module"""
    if name in SHORTCUTS_PRESET:
        return "Preset"
    if name in SHORTCUTS_WIDGET:
        return "Overlays"
    if name in SHORTCUTS_MODULE:
        return "Module"
    if name.startswith("spectate_"):
        return "Spectate"
    if name.startswith("director_"):
        return "Broadcast Director"
    return "General"


SECTIONS = ("General", "Spectate", "Broadcast Director", "Preset", "Overlays", "Module")
# Every binding in page order: (option name, section)
BINDINGS = tuple(
    (name, section)
    for section in SECTIONS
    for name in (*SHORTCUTS_GENERAL, *SHORTCUTS_PRESET, *SHORTCUTS_WIDGET, *SHORTCUTS_MODULE)
    if section_of(name) == section
)


def binding_label(name: str) -> str:
    """Shown name of binding (translated): overlay & module names without their prefix"""
    if name in SHORTCUTS_WIDGET:
        return option_label(name.replace("widget_", ""))
    if name in SHORTCUTS_MODULE:
        return option_label(name.replace("module_", ""))
    return option_label(name)


def capture_placeholder() -> str:
    """Text of key capture before a key is pressed (keyboard not read on Linux)"""
    if PLATFORM.WINDOWS:
        return tr("Press a key, key combination, mouse or controller button")
    return tr("Press a controller button (keyboard not supported on Linux)")


class HotkeyBackend(PageBackend):
    """Hotkeys page state & actions

    Args:
        parent: page widget.
        window: window of the page (key capture takes the app's keys only while it is the active window).
    """

    stateChanged = Signal()  # global hotkey switch, counts, undo
    filterChanged = Signal()
    captureChanged = Signal()  # capture opened or closed, preset choices
    captureTextChanged = Signal()  # keys pressed, binding captured, conflict
    notice = Signal(str, bool)  # toast text, undo offered

    def __init__(self, parent=None, window: Callable[[], QWidget | None] | None = None):
        super().__init__(parent, "Hotkeys")
        self._window = window
        self.model = DictListModel(ROLES, self)
        self._search = ""
        self._words: tuple[str, ...] = ()
        self._assigned_only = False
        self._collapsed: set[str] = set()
        self._assigned = 0
        self._conflicts = 0
        self._shown = 0  # action rows shown (sections unfolded)
        self._undo: dict[str, str] = {}  # binds cleared last: option name -> bind
        self._undo_text = ""
        # Key capture
        self._capture = ""  # option name, "" if no capture
        self._temp = ""  # binding captured (or kept)
        self._conflict = ""  # actions already using the captured binding (shown names)
        self._capture_text = ""
        self._preset_choices: list[str] = []
        self._preset_index = 0
        self._get_key_state: Callable[[int], int] | None = None
        self._held_buttons: set[int] = set()
        self._capturing = False  # reading keys now: page shown, global hotkeys off, app keys filtered
        self._timer = self.page_timer(self.read_keys, CAPTURE_INTERVAL)
        self.rebuild()

    # Page state
    def page_shown(self):
        self.drop_when_shown()  # rows read now: refresh deferred while hidden not run again
        self.rebuild()
        self._update_capturing()

    def page_hidden(self):
        self._update_capturing()  # page left with capture open: global hotkeys back on

    def release_resources(self):
        self._end_capture()

    def refresh(self):
        """Settings or presets changed elsewhere: rows read again (once shown if hidden)"""
        if self.defer_while_hidden(self.rebuild):
            return
        self.rebuild()

    # Rows
    def check_presets(self):
        """Preset of a preset binding whose file is gone: cleared (saved)"""
        changed = False
        for name in SHORTCUTS_PRESET:
            options = cfg.user.shortcuts[name]
            preset = options.get("preset", "")
            if preset and not os.path.exists(f"{cfg.path.settings}{preset}{FileExt.JSON}"):
                options["preset"] = ""
                changed = True
        if changed:
            cfg.save(config_type=ConfigType.SHORTCUTS)

    def rebuild(self):
        """Rows of every section, counts & conflicts"""
        enabled = bool(cfg.application["enable_global_hotkey"])
        if enabled:  # preset files checked while hotkeys are used only (as loading presets by key needs them)
            self.check_presets()
        shortcuts = cfg.user.shortcuts
        users: dict[str, list[str]] = {}  # bind: names using it
        for name, _ in BINDINGS:
            bind = shortcuts[name]["bind"]
            if bind:
                users.setdefault(bind, []).append(name)
        rows: list[dict] = []
        searching = bool(self._words)
        assigned = conflicts = 0
        for section in SECTIONS:
            entries = []
            for name, entry_section in BINDINGS:
                if entry_section != section:
                    continue
                bind = shortcuts[name]["bind"]
                if bind:
                    assigned += 1
                others = [binding_label(other) for other in users.get(bind, ()) if other != name] if bind else []
                conflicts += bool(others)
                preset = shortcuts[name].get("preset", "") if name in SHORTCUTS_PRESET else ""
                entry = {
                    "key": name,
                    "header": False,
                    "section": section,
                    "label": binding_label(name),
                    "binding": format_hotkey_name(bind, delimiter=" + "),
                    "bound": bool(bind),
                    "isPreset": name in SHORTCUTS_PRESET,
                    "preset": preset,
                    "conflict": ", ".join(others),
                    "count": 0,
                    "assigned": 0,
                    "expanded": True,
                }
                if self.accepts(entry, tr(section)):
                    entries.append(entry)
            if searching and not entries:
                continue  # section without match left out
            expanded = searching or section not in self._collapsed
            rows.append({
                "key": f"{SECTION_PREFIX}{section}",
                "header": True,
                "section": section,
                "label": tr(section),
                "binding": "",
                "bound": False,
                "isPreset": False,
                "preset": "",
                "conflict": "",
                "count": len(entries),
                "assigned": sum(entry["bound"] for entry in entries),
                "expanded": expanded,
            })
            if expanded:
                rows.extend(entries)
        self.model.sync(rows)
        self._assigned, self._conflicts = assigned, conflicts
        self._shown = sum(1 for row in rows if not row["header"])
        self.stateChanged.emit()

    def accepts(self, entry: dict, section_label: str) -> bool:
        if self._assigned_only and not entry["bound"]:
            return False
        if not self._words:
            return True
        text = sort_key(" ".join((
            entry["label"], entry["key"].replace("_", " "), entry["binding"], entry["preset"], section_label)))
        return all(word in text for word in self._words)

    # Properties
    @Property(QObject, constant=True)
    def rows(self) -> QObject:
        return self.model

    @Property(bool, notify=stateChanged)
    def enabled(self) -> bool:
        return bool(cfg.application["enable_global_hotkey"])

    @Property(int, notify=stateChanged)
    def assignedCount(self) -> int:
        return self._assigned

    @Property(int, constant=True)
    def totalCount(self) -> int:
        return len(BINDINGS)

    @Property(int, notify=stateChanged)
    def conflictCount(self) -> int:
        """Actions whose binding another action uses too"""
        return self._conflicts

    @Property(bool, notify=stateChanged)
    def canUndo(self) -> bool:
        return bool(self._undo)

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(bool, notify=filterChanged)
    def assignedOnly(self) -> bool:
        return self._assigned_only

    @Property(bool, notify=filterChanged)
    def filtered(self) -> bool:
        return bool(self._words) or self._assigned_only

    @Property(int, notify=stateChanged)
    def shownCount(self) -> int:
        return self._shown

    # Global hotkey switch, filters & sections
    @Slot(bool)
    def setEnabled(self, enabled: bool):
        """Global hotkeys on or off (saved at once)"""
        cfg.application["enable_global_hotkey"] = bool(enabled)
        cfg.save(config_type=ConfigType.CONFIG)
        kctrl.reload()
        app_signal.refresh.emit(True)
        self.rebuild()

    @Slot(str)
    def setSearch(self, text: str):
        self._search = text
        words = tuple(sort_key(text).split())
        if words != self._words:
            self._words = words
            self.rebuild()
        self.filterChanged.emit()

    @Slot(bool)
    def setAssignedOnly(self, assigned_only: bool):
        if bool(assigned_only) != self._assigned_only:
            self._assigned_only = bool(assigned_only)
            self.rebuild()
            self.filterChanged.emit()

    @Slot()
    def clearFilters(self):
        self._search, self._words, self._assigned_only = "", (), False
        self.rebuild()
        self.filterChanged.emit()

    @Slot(str)
    def toggleSection(self, section: str):
        """Section folded or unfolded (sections stay unfolded while searching)"""
        if section not in SECTIONS or self._words:
            return
        if section in self._collapsed:
            self._collapsed.discard(section)
        else:
            self._collapsed.add(section)
        self.rebuild()
        self.filterChanged.emit()

    # Clear & undo
    def _save_binds(self):
        cfg.save(0, config_type=ConfigType.SHORTCUTS)
        kctrl.reload()
        app_signal.refresh.emit(True)
        self.rebuild()

    @Slot(str)
    def clear(self, name: str):
        """Binding of one action cleared, undo offered"""
        options = cfg.user.shortcuts.get(name)
        if not self.enabled or options is None or not options["bind"]:
            return
        self._undo = {name: options["bind"]}
        options["bind"] = ""
        self._undo_text = trm(f"Hotkey cleared: {binding_label(name)}")
        self._save_binds()
        self.notice.emit(self._undo_text, True)

    @Slot()
    def clearAll(self):
        """Every binding cleared, undo offered"""
        if not self.enabled:
            return
        cleared = {name: options["bind"] for name, options in cfg.user.shortcuts.items() if options.get("bind")}
        if not cleared:
            return
        for name in cleared:
            cfg.user.shortcuts[name]["bind"] = ""
        self._undo = cleared
        self._undo_text = trm(f"Hotkeys cleared: {len(cleared)}")
        self._save_binds()
        self.notice.emit(self._undo_text, True)

    @Slot()
    def undo(self):
        """Bindings cleared last set again (an action bound meanwhile keeps its new key)"""
        if not self._undo:
            return
        restored, self._undo = self._undo, {}
        for name, bind in restored.items():
            options = cfg.user.shortcuts.get(name)
            if options is not None and not options["bind"]:
                options["bind"] = bind
        self._save_binds()
        self.notice.emit(tr("Hotkeys restored"), False)

    # Key capture
    @Property(str, notify=captureChanged)
    def captureKey(self) -> str:
        return self._capture

    @Property(str, notify=captureChanged)
    def captureTitle(self) -> str:
        return trm(f"Key Binding - {binding_label(self._capture)}") if self._capture else ""

    @Property(bool, notify=captureChanged)
    def captureIsPreset(self) -> bool:
        return self._capture in SHORTCUTS_PRESET

    @Property(list, notify=captureChanged)
    def presetChoices(self) -> list:
        """Presets a preset binding can load, "Select a preset ..." (none) first"""
        return [tr("Select a preset …"), *self._preset_choices]

    @Property(int, notify=captureTextChanged)
    def presetIndex(self) -> int:
        return self._preset_index

    @Property(str, notify=captureTextChanged)
    def captureText(self) -> str:
        return self._capture_text

    @Property(str, notify=captureTextChanged)
    def capturedBinding(self) -> str:
        return self._temp

    @Property(str, notify=captureTextChanged)
    def captureConflict(self) -> str:
        """Actions already using the captured binding (shown names), "" if none"""
        return self._conflict

    def _set_temp(self, temp: str):
        """Captured binding & the actions already using it"""
        self._temp = temp
        self._conflict = ", ".join(
            binding_label(name) for name, _ in BINDINGS
            if name != self._capture and cfg.user.shortcuts[name]["bind"] == temp) if temp else ""

    @Slot(str)
    def startCapture(self, name: str):
        """Key capture of action opened (page dialog)"""
        if not self.enabled or name not in cfg.user.shortcuts or self._capture:
            return
        self._capture = name
        self._set_temp(cfg.user.shortcuts[name]["bind"])
        if name in SHORTCUTS_PRESET:
            self._preset_choices = cfg.preset_files()
            preset = cfg.user.shortcuts[name].get("preset", "")
            self._preset_index = self._preset_choices.index(preset) + 1 if preset in self._preset_choices else 0
        else:
            self._preset_choices, self._preset_index = [], 0
        get_key_state = self._get_key_state = get_key_state_function()
        # Controller button tapped between two reads (short pulse of a virtual controller, ex. SimHub Control
        # Mapper, rotary encoder step) still captured once
        get_key_state.latch_controller_buttons = True
        refresh_keystate(get_key_state)
        # Controller buttons held at start (switch, rotary) never taken as pressed until released
        self._held_buttons = held_controller_buttons(get_key_state)
        self._set_text(format_hotkey_name(self._temp, capture_placeholder(), delimiter=" + "))
        self.captureChanged.emit()
        self.captureTextChanged.emit()
        self._update_capturing()

    def read_keys(self):
        """Pressed keys read (capture timer): combination taken, modifiers held alone shown"""
        get_key_state = self._get_key_state
        if get_key_state is None or not self._capturing:
            return
        held_buttons = self._held_buttons = {code for code in self._held_buttons if get_key_state(code)}
        key_combo = set_hotkey(lambda code: 0 if code in held_buttons else get_key_state(code))
        if key_combo:
            temp = "+".join(key for key in key_combo if key)
            if temp != self._temp:
                self._set_temp(temp)
                self.captureTextChanged.emit()
            self._set_text(format_hotkey_name(temp, delimiter=" + "))
            return
        # Modifiers held alone shown while waiting for the key, ex. "Ctrl + Shift + ..."
        modifiers = held_modifiers(get_key_state)
        if modifiers:
            self._set_text(f"{format_hotkey_name('+'.join(modifiers), delimiter=' + ')} + …")
        else:
            self._set_text(format_hotkey_name(self._temp, capture_placeholder(), delimiter=" + "))

    def _set_text(self, text: str):
        if text != self._capture_text:
            self._capture_text = text
            self.captureTextChanged.emit()

    @Slot(int)
    def setPresetIndex(self, index: int):
        if 0 <= index <= len(self._preset_choices) and index != self._preset_index:
            self._preset_index = index
            self.captureTextChanged.emit()

    @Slot()
    def clearCapture(self):
        """Captured binding (and preset) emptied, saved with Save"""
        self._set_temp("")
        self._preset_index = 0
        self._set_text(capture_placeholder())
        self.captureTextChanged.emit()

    @Slot()
    def saveCapture(self):
        """Captured binding (and preset) saved, capture closed (an action already using the binding keeps it: the
        dialog shows it and names its button "Assign Anyway")"""
        name = self._capture
        if not name:
            return
        options = cfg.user.shortcuts[name]
        save = False
        if self._temp != options["bind"]:
            options["bind"] = self._temp
            save = True
        if name in SHORTCUTS_PRESET:
            options["preset"] = self._preset_choices[self._preset_index - 1] if self._preset_index > 0 else ""
            save = True
        self._end_capture()
        if save:
            cfg.save(0, config_type=ConfigType.SHORTCUTS)
            app_signal.refresh.emit(True)
        self.rebuild()

    @Slot()
    def cancelCapture(self):
        self._end_capture()

    def _end_capture(self):
        if not self._capture:
            return
        self._capture = ""
        self._set_temp("")
        self._capture_text = ""
        self._get_key_state = None  # game controller devices released
        self._held_buttons = set()
        self._update_capturing()
        self.captureChanged.emit()
        self.captureTextChanged.emit()

    def _update_capturing(self):
        """Keys read (global hotkeys off, app keys filtered) only while capture is open on the shown page"""
        capturing = bool(self._capture) and self.page_visible
        if capturing == self._capturing:
            return
        self._capturing = capturing
        app = QApplication.instance()
        if capturing:
            kctrl.disable()  # pressed keys would run their commands
            if app is not None:
                app.installEventFilter(self)
            self._timer.start()
        else:
            self._timer.stop()
            if app is not None:
                app.removeEventFilter(self)
            kctrl.enable()  # only if enabled in setting

    @property
    def capturing(self) -> bool:
        """Keys being read (capture open on the shown page)"""
        return self._capturing

    def capturing_keys(self) -> bool:
        """Keys pressed in app go to key capture: page window active, no message box or popup over it"""
        window = self._window() if self._window is not None else None
        return (
            self._capturing
            and QApplication.activeModalWidget() is None
            and QApplication.activePopupWidget() is None
            and window is not None
            and QApplication.activeWindow() is window
        )

    def eventFilter(self, watched, event):
        """App shortcuts & keys off while capturing (Ctrl+K, Ctrl+1, Ctrl+S, Alt menu, Enter, Space...), so any key
        combination can be bound; Esc still closes the capture"""
        if (event.type() in CAPTURED_KEY_EVENTS and event.key() != Qt.Key.Key_Escape
                and self.capturing_keys()):
            event.accept()
            return True
        return False
