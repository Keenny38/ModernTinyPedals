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
Command palette (Ctrl+K): find & run anything, pages, widgets, modules, tools, presets, options
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import NamedTuple

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from .. import app_signal
from ..const_file import ConfigType, FileExt
from ..i18n import tr
from ..i18n.options import module_label, option_label
from ..module_control import ModuleControl, mctrl, wctrl
from ..overlay_control import octrl
from ..setting import cfg
from ._common import UIScaler
from .module_view import sort_key
from .option_finder import build_index, open_option, search_options

MAX_COMMANDS = 60
MAX_OPTIONS = 30


class Command(NamedTuple):
    """Palette entry"""

    title: str
    kind: str  # shown on the right
    text: str  # lowercase searchable text, both languages
    run: Callable[[], object]


def search_text(*parts: str) -> str:
    """Lowercase, accent-free search text"""
    return sort_key(" ".join(parts))


def match_commands(commands: list[Command], query: str) -> list[Command]:
    """Commands containing all words of query (any order)"""
    words = search_text(query).split()
    if not words:
        return commands[:MAX_COMMANDS]
    return [command for command in commands if all(word in command.text for word in words)][:MAX_COMMANDS]


def module_commands(control: ModuleControl, kind: str, parent) -> list[Command]:
    """Toggle & configure commands of every widget or module"""
    from .config import UserConfig

    def toggle(name: str):
        control.toggle(name)
        app_signal.refresh.emit(True)

    def configure(name: str):
        if control.type_id == ConfigType.WIDGET:  # one page for every overlay
            from .overlay_options import open_overlay_options

            open_overlay_options(parent, name)
            return
        UserConfig(
            parent=parent,
            key_name=name,
            preset_name=cfg.filename.setting,
            config_type=control.type_id,
            user_setting=cfg.user.setting,
            default_setting=cfg.default.setting,
            reload_func=lambda: control.reload(name),
        ).open()

    commands = []
    for name in control.names:
        label = module_label(name)
        state = tr("On") if cfg.user.setting[name]["enable"] else tr("Off")
        commands.append(Command(
            f"{label}  ({state})", tr(kind), search_text(label, name, kind, "toggle enable disable"),
            partial(toggle, name)))
        commands.append(Command(
            f"{label}  {chr(0x2699)}", tr("Config"), search_text(label, name, kind, "config settings"),
            partial(configure, name)))
    return commands


def build_commands(window) -> list[Command]:
    """All palette commands, built when palette opens (states are current)"""
    from .app import NAV_PAGES
    from .menu import open_config_application
    from .tools_view import TOOL_KEYWORDS, TOOL_SECTIONS, open_tool

    tab_view = window.centralWidget()
    commands: list[Command] = []
    for index, (key, label, *_) in enumerate(NAV_PAGES):
        commands.append(Command(
            tr(label), tr("Page"), search_text(tr(label), label, key, "page go"),
            partial(tab_view.select_page, index)))
    actions = (
        ("Lock Overlay", "fixed_position", octrl.toggle.lock),
        ("Auto Hide", "auto_hide", octrl.toggle.hide),
        ("Grid Move", "enable_grid_move", octrl.toggle.grid),
        ("VR Compatibility", "vr_compatibility", octrl.toggle.vr),
    )
    for label, option, action in actions:
        state = tr("On") if cfg.overlay[option] else tr("Off")
        commands.append(Command(
            f"{tr(label)}  ({state})", tr("Overlay"), search_text(tr(label), label, "overlay toggle"), action))
    commands.append(Command(
        tr("Reload"), tr("Overlay"), search_text(tr("Reload"), "reload preset"), lambda: window.reload_preset(True)))
    commands.append(Command(
        tr("Reset Window Size and Position"), tr("Window"),
        search_text(tr("Reset Window Size and Position"), "reset window size position default center"),
        window.reset_window_size))
    from .quick.settings_backend import CATEGORIES

    for category in CATEGORIES:  # settings page categories (config.json)
        commands.append(Command(
            tr(category.label), tr("Config"),
            search_text(tr(category.label), category.label, tr(category.description), "config settings"),
            partial(open_config_application, window, category.key)))
    for _, tools in TOOL_SECTIONS:
        for label, _, dialog_path in tools:
            commands.append(Command(
                tr(label), tr("Tools"), search_text(tr(label), label, "tool", TOOL_KEYWORDS.get(dialog_path, "")),
                partial(open_tool, dialog_path, window)))
    for preset_name in cfg.preset_files():
        commands.append(Command(
            preset_name, tr("Preset"), search_text(preset_name, tr("Preset"), "preset load"),
            partial(load_preset, preset_name)))
    commands += module_commands(wctrl, "Overlays", window)
    commands += module_commands(mctrl, "Module", window)
    return commands


def load_preset(preset_name: str):
    """Load preset by name (without extension)"""
    cfg.set_next_to_load(f"{preset_name}{FileExt.JSON}")
    app_signal.reload.emit(True)


class CommandPalette(QDialog):
    """Search box over a result list, Enter runs, Esc closes"""

    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle(tr("Command Palette"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._window = window
        self.commands = build_commands(window)
        self.options = build_index()

        self.edit_search = QLineEdit(self)
        self.edit_search.setObjectName("searchBox")
        self.edit_search.setPlaceholderText(tr("Search pages, widgets, tools, presets, options..."))
        self.edit_search.textChanged.connect(self.update_results)
        self.edit_search.returnPressed.connect(self.run_selected)
        self.edit_search.installEventFilter(self)

        self.list_results = QListWidget(self)
        self.list_results.itemActivated.connect(self.run_item)
        self.list_results.setMinimumSize(UIScaler.size(34), UIScaler.size(22))

        self.label_hint = QLabel(tr("Enter to run, Esc to close"), self)
        self.label_hint.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.edit_search)
        layout.addWidget(self.list_results, stretch=1)
        layout.addWidget(self.label_hint)
        self.update_results("")

    def eventFilter(self, watched, event):
        """Arrow keys in search box move selection in list"""
        if watched is self.edit_search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                row = self.list_results.currentRow()
                step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: 10, Qt.Key.Key_PageUp: -10}[key]
                count = self.list_results.count()
                if count:
                    self.list_results.setCurrentRow(max(0, min(count - 1, row + step)))
                return True
        return super().eventFilter(watched, event)

    def update_results(self, text: str):
        """Refresh result list"""
        self.list_results.clear()
        for command in match_commands(self.commands, text):
            self.add_item(command.title, command.kind, command.run)
        if len(text.strip()) >= 2:
            for entry in search_options(self.options, text)[:MAX_OPTIONS]:
                self.add_item(
                    f"{module_label(entry.section)}  →  {option_label(entry.key)}", tr("Option"),
                    partial(open_option, self._window, entry))
        if self.list_results.count():
            self.list_results.setCurrentRow(0)

    def add_item(self, title: str, kind: str, run: Callable[[], object]):
        item = QListWidgetItem(f"{title}\t· {kind}")
        item.setData(Qt.ItemDataRole.UserRole, run)
        self.list_results.addItem(item)

    def run_selected(self):
        item = self.list_results.currentItem()
        if item is not None:
            self.run_item(item)

    def run_item(self, item: QListWidgetItem):
        run = item.data(Qt.ItemDataRole.UserRole)
        self.close()
        run()
