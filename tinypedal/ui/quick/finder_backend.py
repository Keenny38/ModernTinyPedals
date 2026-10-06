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
Find Option page backend (qml/OptionFinder.qml): ranked results with current values

Results show the value of each option (on / off switch, color, number...), whether it differs from
default, and the option description. On / off options switch right in the list; any result opens
its settings page filtered on the option. Without search words, "Changed only" lists every option
set apart from its default.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ... import app_signal
from ...const_file import ConfigType
from ...i18n import tr
from ...i18n.options import module_label, option_help, option_label
from ...module_control import mctrl, wctrl
from ...setting import cfg
from .._common import run_after_saving
from ..module_view import sort_key
from ..option_finder import OptionEntry, build_index, reload_function, search_options
from .models import DictListModel
from .option_kinds import KIND_BOOL, KIND_COLOR, display_text, value_kind

MAX_SHOWN = 200
GROUP_ALL = ""
GROUPS = (  # filter chips: (config type, label)
    (ConfigType.WIDGET, "Overlays"),
    (ConfigType.MODULE, "Modules"),
    (ConfigType.SETTING, "Preset"),
    (ConfigType.CONFIG, "Application"),
)
GROUP_GLYPHS = {
    ConfigType.WIDGET: "\ue71d",  # all apps
    ConfigType.MODULE: "\ue9d9",  # diagnostic
    ConfigType.SETTING: "\ue8f1",  # library
    ConfigType.CONFIG: "\ue713",  # settings
}
ROLES = (
    "key", "section", "option", "label", "sectionLabel", "group", "groupLabel", "glyph",
    "kind", "value", "color", "checked", "modified", "help",
)


def entry_key(entry: OptionEntry) -> str:
    return f"{entry.config_type}/{entry.section}/{entry.key}"


def user_values(entry: OptionEntry) -> tuple[dict, dict]:
    """Saved & default options of entry section"""
    if entry.config_type == ConfigType.CONFIG:
        return cfg.user.config.get(entry.section, {}), cfg.default.config.get(entry.section, {})
    return cfg.user.setting.get(entry.section, {}), cfg.default.setting.get(entry.section, {})


def highlight(text: str, words: tuple[str, ...]) -> str:
    """Label as rich text, searched words in bold (case & accent folded match)"""
    folded = sort_key(text)
    if len(folded) != len(text) or not words:  # folding changed length: no safe mapping
        return html.escape(text)
    marks = [False] * len(text)
    for word in words:
        for match in re.finditer(re.escape(word), folded):
            for index in range(match.start(), match.end()):
                marks[index] = True
    parts, bold = [], False
    for char, mark in zip(text, marks):
        if mark != bold:
            parts.append("<b>" if mark else "</b>")
            bold = mark
        parts.append(html.escape(char))
    if bold:
        parts.append("</b>")
    return "".join(parts)


class FinderBackend(QObject):
    """Find Option page state & actions

    Args:
        parent: page dialog.
        open_option: open settings page of an option, filtered on it.
    """

    resultsChanged = Signal()
    filterChanged = Signal()

    def __init__(self, parent, open_option: Callable[[OptionEntry], Any]):
        super().__init__(parent)
        self._open_option = open_option
        self.entries = build_index()
        self._by_key = {entry_key(entry): entry for entry in self.entries}
        self.model = DictListModel(ROLES, self)
        self._search = ""
        self._words: tuple[str, ...] = ()
        self._group = GROUP_ALL
        self._changed_only = False
        self._found: list[OptionEntry] = []  # matching search & changed filter, all groups
        self._counts: dict[str, int] = {}
        self.update_results()

    # Results
    def matching(self) -> list[OptionEntry]:
        """Entries matching search words (ranked) & changed filter, any group"""
        if self._words:
            entries = search_options(self.entries, self._search, limit=0)
        elif self._changed_only:
            entries = self.entries
        else:
            return []
        if self._changed_only:
            entries = [entry for entry in entries if self.is_modified(entry)]
        return entries

    @staticmethod
    def is_modified(entry: OptionEntry) -> bool:
        values, defaults = user_values(entry)
        return entry.key in defaults and values.get(entry.key) != defaults[entry.key]

    def row(self, entry: OptionEntry) -> dict:
        values, defaults = user_values(entry)
        value = values.get(entry.key)
        kind = value_kind(entry.key, defaults.get(entry.key, value))
        group_label = next((label for group, label in GROUPS if group == entry.config_type), "")
        return {
            "key": entry_key(entry),
            "section": entry.section,
            "option": entry.key,
            "label": highlight(option_label(entry.key), self._words),
            "sectionLabel": module_label(entry.section),
            "group": entry.config_type,
            "groupLabel": tr(group_label),
            "glyph": GROUP_GLYPHS.get(entry.config_type, ""),
            "kind": kind.kind,
            "value": display_text(kind, value) if value is not None else "",
            "color": value if kind.kind == KIND_COLOR and isinstance(value, str) else "",
            "checked": bool(value) if kind.kind == KIND_BOOL else False,
            "modified": entry.key in defaults and value != defaults[entry.key],
            "help": option_help(entry.section, entry.key),
        }

    def update_results(self):
        self._found = self.matching()
        counts = dict.fromkeys((GROUP_ALL, *(group for group, _ in GROUPS)), 0)
        for entry in self._found:
            counts[GROUP_ALL] += 1
            counts[entry.config_type] = counts.get(entry.config_type, 0) + 1
        self._counts = counts
        shown = [entry for entry in self._found if self._group in (GROUP_ALL, entry.config_type)][:MAX_SHOWN]
        self.model.sync([self.row(entry) for entry in shown])
        self.resultsChanged.emit()

    def refresh_values(self):
        """Values changed elsewhere (config saved, preset loaded): shown rows updated in place"""
        self.update_results()

    # Properties
    @Property(QObject, constant=True)
    def results(self) -> QObject:
        return self.model

    @Property(int, constant=True)
    def optionCount(self) -> int:
        return len(self.entries)

    @Property(int, notify=resultsChanged)
    def foundCount(self) -> int:
        return self._counts.get(self._group, 0)

    @Property(int, notify=resultsChanged)
    def shownCount(self) -> int:
        return self.model.rowCount()

    @Property(list, notify=resultsChanged)
    def groups(self) -> list[dict]:
        """Group filter chips with their number of results"""
        chips = [{"key": GROUP_ALL, "label": tr("All"), "count": self._counts.get(GROUP_ALL, 0)}]
        chips.extend(
            {"key": group, "label": tr(label), "count": self._counts.get(group, 0)} for group, label in GROUPS
        )
        return chips

    @Property(str, notify=filterChanged)
    def searchText(self) -> str:
        return self._search

    @Property(str, notify=filterChanged)
    def group(self) -> str:
        return self._group

    @Property(bool, notify=filterChanged)
    def changedOnly(self) -> bool:
        return self._changed_only

    @Property(bool, notify=filterChanged)
    def searching(self) -> bool:
        return bool(self._words) or self._changed_only

    # Filters
    @Slot(str)
    def setSearch(self, text: str):
        self._search = text
        words = tuple(sort_key(text).split())
        if words != self._words:
            self._words = words
            self.update_results()
        self.filterChanged.emit()

    @Slot(str)
    def setGroup(self, group: str):
        if group != self._group and group in (GROUP_ALL, *(key for key, _ in GROUPS)):
            self._group = group
            self.update_results()
            self.filterChanged.emit()

    @Slot(bool)
    def setChangedOnly(self, changed: bool):
        if changed != self._changed_only:
            self._changed_only = changed
            self.update_results()
            self.filterChanged.emit()

    # Actions
    def entry(self, key: str) -> OptionEntry | None:
        return self._by_key.get(key)

    @Slot(str)
    def openOption(self, key: str):
        entry = self.entry(key)
        if entry is not None:
            self._open_option(entry)

    @Slot(str)
    def toggle(self, key: str):
        """Switch on / off option at once: saved & applied"""
        entry = self.entry(key)
        values, defaults = user_values(entry) if entry is not None else ({}, {})
        if entry is None or value_kind(entry.key, defaults.get(entry.key)).kind != KIND_BOOL:
            return
        self.set_value(entry, not bool(values.get(entry.key)))

    @Slot(str)
    def resetOption(self, key: str):
        """Option back to default: saved & applied"""
        entry = self.entry(key)
        if entry is None:
            return
        _, defaults = user_values(entry)
        if entry.key in defaults:
            self.set_value(entry, defaults[entry.key])

    @Slot(str)
    def copyKey(self, key: str):
        """Option key (as in setting files & documentation) to clipboard"""
        entry = self.entry(key)
        clipboard = QGuiApplication.clipboard()
        if entry is not None and clipboard is not None:
            clipboard.setText(entry.key)

    def set_value(self, entry: OptionEntry, value: Any):
        """Save option value & apply it (overlay or module restarted, app reloaded for global options)"""
        values, _ = user_values(entry)
        if values.get(entry.key) == value:
            return
        control = wctrl if entry.config_type == ConfigType.WIDGET else mctrl
        if entry.key == "enable" and entry.config_type in (ConfigType.WIDGET, ConfigType.MODULE):
            control.toggle(entry.section)  # started or stopped, saved
            app_signal.refresh.emit(True)  # pages & menus follow
        else:
            values[entry.key] = value
            if entry.config_type == ConfigType.CONFIG:
                cfg.save(0, config_type=ConfigType.CONFIG)
            else:
                cfg.save(0)
            run_after_saving(reload_function(entry))
        self.update_results()
