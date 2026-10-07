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
Overlay edit mode: toolbar, selected overlay, undo & redo of placement changes

Edit mode starts when the overlay is unlocked by the user (lock toggle of the app, tray menu,
command palette or hotkey) and ends when it is locked again or its toolbar is closed. While on:

- every overlay shows its outline & name, also empty ones and ones hidden by auto hide or
  by their visibility context, so each one can be found and moved;
- a floating toolbar (widget._edit_toolbar) toggles snapping, grid & guides, undoes & redoes
  changes, lists active overlays and locks the overlay when done.

An overlay unlocked at startup does not start edit mode: the outline of an overlay only shows
under the mouse, as before, so nothing stays on screen while driving with an unlocked overlay.

Changes made while unlocked (move, arrow keys, center, move to screen, resize, opacity,
visibility, disable) go to an undo history, cleared once locked or when another preset loads.
"""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any, NamedTuple

from PySide6.QtCore import QObject, QTimer

from .. import app_signal, overlay_signal, realtime_state
from ..const_file import ConfigType
from ..setting import cfg

logger = logging.getLogger(__name__)

POSITION_KEYS = frozenset(("position_x", "position_y"))
LIVE_KEYS = POSITION_KEYS | {"opacity", "visibility_context"}  # applied without reloading overlay
HISTORY_SIZE = 100
MERGE_SECONDS = 1.5  # arrow key presses of one overlay in a row: one undo step
LAYOUT_STORE_DELAY_MS = 600  # screen layout profile written once arrow key presses stop


class EditStep(NamedTuple):
    """Undoable change of overlay options"""

    name: str  # overlay name
    text: str  # action name (English, translated when shown)
    before: dict
    after: dict
    preset: str  # preset file the change was made in
    time: float


class EditHistory:
    """Undo & redo stacks of overlay changes"""

    __slots__ = ("_undo", "_redo", "_size")

    def __init__(self, size: int = HISTORY_SIZE):
        self._undo: list[EditStep] = []
        self._redo: list[EditStep] = []
        self._size = size

    def push(self, step: EditStep, merge: bool = False):
        """Add step, redo stack cleared

        Args:
            merge: merge with previous step of same overlay & action made just before
                (arrow key presses), keeping its first before state.
        """
        if merge and self._undo:
            last = self._undo[-1]
            if (last.name, last.text, last.preset) == (step.name, step.text, step.preset) and (
                step.time - last.time <= MERGE_SECONDS
            ):
                step = step._replace(before=last.before)
                self._undo.pop()
        if step.before != step.after:
            self._undo.append(step)
            del self._undo[:-self._size]
        self._redo.clear()

    def undo(self) -> EditStep | None:
        """Step to undo, moved to redo stack"""
        if not self._undo:
            return None
        step = self._undo.pop()
        self._redo.append(step)
        return step

    def redo(self) -> EditStep | None:
        """Step to redo, moved back to undo stack"""
        if not self._redo:
            return None
        step = self._redo.pop()
        self._undo.append(step)
        return step

    def peek_undo(self) -> EditStep | None:
        return self._undo[-1] if self._undo else None

    def peek_redo(self) -> EditStep | None:
        return self._redo[-1] if self._redo else None

    def keep_preset(self, preset: str):
        """Forget steps made in another preset (overlay options of another file)"""
        if any(step.preset != preset for step in self._undo + self._redo):
            self.clear()

    def clear(self):
        self._undo.clear()
        self._redo.clear()

    def __len__(self) -> int:
        return len(self._undo)


def active_overlays() -> dict[str, Any]:
    """Active overlay widgets by name"""
    from ..module_control import wctrl

    return dict(wctrl.active_modules)


class EditMode(QObject):
    """Overlay edit mode state, shared by all overlays (see edit_mode())"""

    def __init__(self):
        super().__init__()
        self.history = EditHistory()
        self.selected = ""
        self.toolbar: Any = None  # widget._edit_toolbar.EditToolbar, created on first use
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.setInterval(LAYOUT_STORE_DELAY_MS)
        self._layout_timer.timeout.connect(self.store_layout)

    @property
    def editing(self) -> bool:
        """Edit mode on (toolbar shown, outlines of all overlays shown)"""
        return realtime_state.editing

    # Edit mode
    def follow_lock(self, locked: bool):
        """Overlay locked or unlocked by user: leave or enter edit mode (if enabled on unlock,
        else overlays just movable, outline on hover, edit mode from right-click menu)"""
        if locked:
            self.leave()
            self.history.clear()
            self.select("")
        elif cfg.application.get("enable_edit_mode_on_unlock", False):
            self.enter()

    def enter(self) -> bool:
        """Start edit mode, nothing to edit without active overlay"""
        if cfg.overlay["fixed_position"] or not active_overlays():
            return False
        if not realtime_state.editing:
            realtime_state.editing = True
            overlay_signal.editing.emit(True)
            logger.info("OVERLAY: edit mode on")
        self.show_toolbar()
        return True

    def leave(self):
        """End edit mode (overlay locked or toolbar closed), overlay may stay unlocked"""
        self._flush_layout()
        if self.toolbar is not None:
            self.toolbar.hide()
        if realtime_state.editing:
            realtime_state.editing = False
            overlay_signal.editing.emit(False)
            logger.info("OVERLAY: edit mode off")

    def sync(self):
        """Overlays (re)started: leave edit mode if new preset is locked"""
        if realtime_state.editing and cfg.overlay["fixed_position"]:
            self.follow_lock(True)
        elif self.toolbar is not None and self.toolbar.isVisible():
            self.toolbar.refresh()

    def show_toolbar(self):
        if self.toolbar is None:
            from ._edit_toolbar import EditToolbar

            self.toolbar = EditToolbar(self)
        self.toolbar.refresh()
        self.toolbar.show_on_screen()

    def refresh_toolbar(self):
        if self.toolbar is not None and self.toolbar.isVisible():
            self.toolbar.refresh()

    # Selection
    def select(self, name: str):
        """Select overlay (clicked one): highlighted, moved by arrow keys, shown on toolbar"""
        if name == self.selected:
            return
        overlays = active_overlays()
        for old_or_new, state in ((self.selected, False), (name, True)):
            widget = overlays.get(old_or_new)
            frame = getattr(widget, "_edit_frame", None)
            if frame is not None:
                frame.set_selected(state)
        self.selected = name
        self.refresh_toolbar()

    def deselect(self, name: str):
        """Overlay lost focus (or closed): no longer selected"""
        if name and name == self.selected:
            self.select("")

    def placement_changed(self, name: str):
        """Overlay moved: toolbar shows new position"""
        if name == self.selected:
            self.refresh_toolbar()

    # History
    def record(self, name: str, text: str, before: dict, after: dict, merge: bool = False):
        """Add change made to overlay options to undo history"""
        self.history.keep_preset(cfg.filename.setting)
        self.history.push(EditStep(name, text, dict(before), dict(after), cfg.filename.setting, monotonic()), merge)
        self.refresh_toolbar()

    def undo(self) -> bool:
        return self._restore(self.history.undo, "before")

    def redo(self) -> bool:
        return self._restore(self.history.redo, "after")

    def _restore(self, take, state: str) -> bool:
        self.history.keep_preset(cfg.filename.setting)
        step = take()
        if step is None:
            return False
        apply_values(step.name, getattr(step, state))
        self.refresh_toolbar()
        return True

    # Saving
    def store_layout_soon(self):
        """Write screen layout profile once moves stop (arrow keys held down)"""
        self._layout_timer.start()

    def _flush_layout(self):
        if self._layout_timer.isActive():
            self._layout_timer.stop()
            self.store_layout()

    @staticmethod
    def store_layout():
        from ._base import store_screen_layout

        store_screen_layout(cfg)


def apply_values(name: str, values: dict):
    """Apply overlay option values (undo, redo, menu actions), saved to preset

    Position, opacity & visibility are applied to the running overlay at once, other options
    reload it. Option "enable" turns the overlay on or off.
    """
    setting = cfg.user.setting.get(name)
    if setting is None:  # plugin overlay removed
        return
    values = dict(values)
    enable = values.pop("enable", None)
    if enable is not None and bool(setting.get("enable")) != enable:
        from ..module_control import wctrl

        wctrl.toggle(name)  # saved
        app_signal.refresh.emit(True)
    if not values:
        return
    widget = active_overlays().get(name)
    if widget is not None and set(values) <= LIVE_KEYS:
        for key, value in values.items():
            widget.wcfg[key] = value  # written through to user setting
        widget.apply_placement()
    else:
        setting.update(values)
        if widget is not None:
            from ._base import reload_widget

            QTimer.singleShot(0, lambda: reload_widget(name))
    cfg.save()
    if POSITION_KEYS & values.keys():
        edit_mode().store_layout_soon()
        edit_mode().placement_changed(name)


def toggle_application_option(key: str) -> bool:
    """Toggle application (config.json) option of edit mode: snapping, guides"""
    cfg.application[key] = not cfg.application[key]
    cfg.save(config_type=ConfigType.CONFIG)
    edit_mode().refresh_toolbar()
    return cfg.application[key]


_edit_mode: EditMode | None = None


def edit_mode() -> EditMode:
    """Shared edit mode state (created on first use)"""
    global _edit_mode
    if _edit_mode is None:
        _edit_mode = EditMode()
    return _edit_mode


def follow_lock(locked: bool):
    """Overlay lock toggled by user: edit mode follows (see overlay_control & hotkey commands)"""
    if locked and _edit_mode is None:
        return  # never edited: nothing to leave
    edit_mode().follow_lock(locked)


def sync_edit_mode():
    """Overlay started: edit mode left if preset locked, toolbar count updated"""
    if _edit_mode is not None:
        _edit_mode.sync()


def forget_overlay(name: str):
    """Overlay stopped: no longer selected"""
    if _edit_mode is not None:
        _edit_mode.deselect(name)


def step_text(step: EditStep | None) -> str:
    """Undo step shown after Undo or Redo: action and overlay name"""
    if step is None:
        return ""
    from ..i18n import tr
    from ..i18n.options import module_label

    return f": {tr(step.text)} \u2013 {module_label(step.name)}"
