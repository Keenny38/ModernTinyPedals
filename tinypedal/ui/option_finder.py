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
Global option search: find any option in all widgets, modules & global settings
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from .. import loader
from ..const_file import ConfigType
from ..i18n import tr, trm
from ..i18n.options import module_label, option_label, option_tooltip, search_text
from ..module_control import mctrl, wctrl
from ..setting import cfg
from ._common import BaseDialog, UIScaler, singleton_dialog

MAX_RESULTS = 200
# Global config sections edited from other places (API menu, tool dialogs)
EXCLUDED_CONFIG = {"preset", "telemetry", "fuel_calculator", "tyre_strategy_planner", "track_map_viewer"}
EXCLUDED_SETTING = {"preset"}


class OptionEntry(NamedTuple):
    """Searchable option"""

    section: str
    key: str
    config_type: str  # ConfigType.CONFIG, SETTING, WIDGET, MODULE
    text: str  # lowercase searchable text


def build_index() -> list[OptionEntry]:
    """All editable options"""
    entries: list[OptionEntry] = []
    widgets, modules = set(wctrl.names), set(mctrl.names)
    groups = (
        (cfg.user.config, EXCLUDED_CONFIG, lambda name: ConfigType.CONFIG),
        (cfg.user.setting, EXCLUDED_SETTING, lambda name: (
            ConfigType.WIDGET if name in widgets else ConfigType.MODULE if name in modules else ConfigType.SETTING
        )),
    )
    for user_setting, excluded, config_type in groups:
        for section, options in user_setting.items():
            if section in excluded or not isinstance(options, dict):
                continue
            if section.startswith("api_") and section != cfg.api_key:
                continue  # only options of selected API
            section_text = f"{module_label(section)} {section}".lower()
            for key in options:
                entries.append(OptionEntry(section, key, config_type(section), f"{section_text} {search_text(key)}"))
    return entries


def search_options(entries: list[OptionEntry], text: str) -> list[OptionEntry]:
    """Options matching all words (any order)"""
    words = text.lower().split()
    if not words:
        return []
    return [entry for entry in entries if all(word in entry.text for word in words)][:MAX_RESULTS]


def open_option(parent, entry: OptionEntry):
    """Open config dialog of option, filtered to the option"""
    from .config import UserConfig

    if entry.config_type == ConfigType.CONFIG:
        user_setting, default_setting, preset_name = cfg.user.config, cfg.default.config, cfg.filename.config
    else:
        user_setting, default_setting, preset_name = cfg.user.setting, cfg.default.setting, cfg.filename.setting
    dialog = UserConfig(
        parent=parent,
        key_name=entry.section,
        preset_name=preset_name,
        config_type=entry.config_type,
        user_setting=user_setting,
        default_setting=default_setting,
        reload_func=reload_function(entry),
    )
    dialog.edit_search.setText(entry.key)
    dialog.open()
    return dialog


def reload_function(entry: OptionEntry):
    """Apply changes of edited section"""
    if entry.config_type == ConfigType.WIDGET:
        return lambda: wctrl.reload(entry.section)
    if entry.config_type == ConfigType.MODULE:
        return lambda: mctrl.reload(entry.section)
    return lambda: loader.reload(reload_preset=entry.config_type == ConfigType.CONFIG)


@singleton_dialog("option_finder")
class OptionFinder(BaseDialog):
    """Find option dialog"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Find Option"))
        self.entries = build_index()

        self.edit_search = QLineEdit(self)
        self.edit_search.setPlaceholderText(tr("Type option name, in any language (ex. font color speed)"))
        self.edit_search.textChanged.connect(self.update_results)
        self.edit_search.returnPressed.connect(self.open_selected)

        self.list_results = QListWidget(self)
        self.list_results.itemActivated.connect(self.open_item)
        self.list_results.setMinimumSize(UIScaler.size(34), UIScaler.size(24))

        self.label_count = QLabel(self)

        layout = QVBoxLayout()
        layout.addWidget(self.edit_search)
        layout.addWidget(self.list_results, stretch=1)
        layout.addWidget(self.label_count)
        layout.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout)
        self.update_results("")

    def update_results(self, text: str):
        """Refresh result list"""
        self.list_results.clear()
        results = search_options(self.entries, text)
        for entry in results:
            item = QListWidgetItem(f"{module_label(entry.section)}  →  {option_label(entry.key)}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(option_tooltip(entry.section, entry.key))
            self.list_results.addItem(item)
        if text.strip():
            self.label_count.setText(trm(f"Found: {len(results)}"))
        else:
            self.label_count.setText(trm(f"Options: {len(self.entries)}"))
        if results:
            self.list_results.setCurrentRow(0)

    def open_selected(self):
        item = self.list_results.currentItem()
        if item is not None:
            self.open_item(item)

    def open_item(self, item: QListWidgetItem):
        open_option(self.parent(), item.data(Qt.ItemDataRole.UserRole))
