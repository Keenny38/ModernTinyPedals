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
Keyboard shortcuts sheet (Ctrl+/ or F1, qml/shell/Shortcuts.qml): shortcuts of the main window (registered
shortcuts, menu entries, navigation bar Ctrl+1..9), common keys of pages, global hotkeys bound on the Hotkeys
page; filtered by typed text
"""

from __future__ import annotations

from PySide6.QtCore import Property, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QWidget

from ...i18n import tr
from ..module_view import sort_key
from .shell_popup import ShellBackend, ShellPopup, centered_top, popup_size

KIND = "shortcuts"
# Keys of pages (not app shortcuts, kept by each page): (keys, what they do)
PAGE_KEYS = (
    ("Esc", "Close page (pages with a Close button), clear a search"),
    ("Ctrl+F", "Find in page (pages with a search field)"),
    ("Ctrl+Z / Ctrl+Y", "Undo / redo in editors and pages that keep changes"),
    ("/", "Search the list of the page"),
)


def native(sequence: QKeySequence | str) -> str:
    """Key sequence as shown on this system"""
    return QKeySequence(sequence).toString(QKeySequence.SequenceFormat.NativeText)


def window_shortcuts(window: QWidget) -> list[dict]:
    """Shortcuts of the main window: own shortcuts (described by whatsThis), menu entries, rail entries"""
    rows: list[dict] = []
    found: dict[tuple[str, str], dict] = {}  # (group, text): row, keys of one action on one row

    def add(group: str, keys: str, text: str):
        row = found.get((group, text))
        if not keys or (row is not None and keys in row["keys"].split(", ")):
            return
        if row is not None:
            row["keys"] = f"{row['keys']}, {keys}"
            return
        found[group, text] = row = {"group": group, "keys": keys, "text": text}
        rows.append(row)

    window_group = tr("Main Window")
    for shortcut in window.findChildren(QShortcut):
        if shortcut.isEnabled() and shortcut.whatsThis():
            add(window_group, native(shortcut.key()), shortcut.whatsThis())
            if shortcut.key().toString() == "Ctrl+/":
                add(window_group, "F1", shortcut.whatsThis())  # F1: key press not taken by the page
    central = getattr(window, "centralWidget", None)
    view = central() if callable(central) else None
    rail_buttons = getattr(view, "rail_shortcut_labels", None)
    for keys, text in (rail_buttons() if callable(rail_buttons) else ()):
        add(tr("Navigation Bar"), native(keys), text)
    menu_bar = getattr(window, "menuBar", None)
    for action in (menu_bar().actions() if callable(menu_bar) else ()):
        menu = action.menu()
        if isinstance(menu, QMenu):
            for item in menu.actions():
                if not item.shortcut().isEmpty() and item.isVisible():
                    add(menu.title().replace("&", ""), native(item.shortcut()), item.text().replace("&", ""))
    return rows


def hotkey_shortcuts() -> list[dict]:
    """Global hotkeys bound on the Hotkeys page (work while the game has focus, when enabled)"""
    from ...hotkey.common import format_hotkey_name
    from ...setting import cfg
    from .hotkey_backend import BINDINGS, binding_label

    group = tr("Global hotkeys")
    rows = []
    for name, _ in BINDINGS:
        bind = cfg.user.shortcuts.get(name, {}).get("bind", "")
        if bind:
            rows.append({"group": group, "keys": format_hotkey_name(bind, delimiter=" + "), "text": binding_label(name)})
    return rows


class ShortcutsBackend(ShellBackend):
    """Shortcut rows (group, keys, text) filtered by search"""

    rowsChanged = Signal()

    def __init__(self, window: QWidget):
        super().__init__()
        self._window = window
        page_group = tr("Pages")
        self._all = [
            *window_shortcuts(window),
            *({"group": page_group, "keys": keys, "text": tr(text)} for keys, text in PAGE_KEYS),
            *hotkey_shortcuts(),
        ]
        self._search = ""
        self._rows = list(self._all)

    @Property(list, notify=rowsChanged)
    def rows(self) -> list[dict]:
        return self._rows

    @Property(bool, constant=True)
    def hotkeysEnabled(self) -> bool:
        from ...setting import cfg

        return bool(cfg.application["enable_global_hotkey"])

    @Slot(str)
    def setSearch(self, text: str):
        words = sort_key(text).split()
        rows = [row for row in self._all
                if all(word in sort_key(f"{row['keys']} {row['text']} {row['group']}") for word in words)]
        self._search = text
        if rows != self._rows:
            self._rows = rows
            self.rowsChanged.emit()

    @Slot()
    def close(self):
        self.closeRequested.emit()

    @Slot()
    def openHotkeys(self):
        """Hotkeys page (bind global hotkeys)"""
        self.closeRequested.emit()
        central = getattr(self._window, "centralWidget", None)
        view = central() if callable(central) else None
        select = getattr(view, "select_page", None)
        if callable(select):
            from ..nav_rail import PAGE_INDEX

            select(PAGE_INDEX["hotkey"])


class ShortcutsSheet(ShellPopup):
    """Keyboard shortcuts popup, centered over the main window"""

    backend: ShortcutsBackend

    @classmethod
    def toggle(cls, window: QWidget) -> ShortcutsSheet | None:
        """Open, or close if open"""
        shown = cls.shown(KIND)
        if shown is not None:
            shown.close()
            return None
        size = popup_size(window, 34, 32)
        popup = cls(window, KIND, "Shortcuts.qml", ShortcutsBackend(window), size)
        popup.popup(centered_top(window, size, 0.08))
        return popup

