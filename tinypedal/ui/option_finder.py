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

Results are ranked (words found in the option name first, then in its overlay or section name),
case & accent folded, in English and in app language. Find Option page: Qt Quick page
(qml/OptionFinder.qml), state & actions in quick/finder_backend.py.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from PySide6.QtCore import QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout

from .. import loader
from ..const_file import ConfigType
from ..i18n import tr
from ..i18n.options import module_label, search_text
from ..module_control import mctrl, wctrl
from ..setting import cfg
from ..widget._modern import design_option_keys
from ._common import BaseDialog, UIScaler, singleton_dialog
from .config import HIDDEN_OPTIONS
from .module_view import sort_key

MAX_RESULTS = 200
# Global config sections edited from other places (API menu, tool dialogs)
EXCLUDED_CONFIG = {"preset", "telemetry", "fuel_calculator", "tyre_strategy_planner", "track_map_viewer"}
EXCLUDED_SETTING = {"preset"}


class OptionEntry(NamedTuple):
    """Searchable option"""

    section: str
    key: str
    config_type: str  # ConfigType.CONFIG, SETTING, WIDGET, MODULE
    text: str  # searchable text: section & option names, case & accent folded
    label: str = ""  # searchable option names only (ranking), case & accent folded


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
            section_text = sort_key(f"{module_label(section)} {section.replace('_', ' ')} {section}")
            section_type = config_type(section)
            keys = list(options)
            if section_type == ConfigType.WIDGET:  # options shown by current design only
                keys = design_option_keys(cfg, section, keys)
            elif section_type == ConfigType.CONFIG:  # kept up to date by app, not shown in config dialog
                keys = [key for key in keys if key not in HIDDEN_OPTIONS.get(section, ())]
            for key in keys:
                label = sort_key(search_text(key))
                entries.append(OptionEntry(section, key, section_type, f"{section_text} {label}", label))
    return entries


def match_score(entry: OptionEntry, words: tuple[str, ...]) -> int:
    """Rank of a matching entry: words found in option name count more than words of overlay name,
    a word starting a name word more than one inside it, the whole phrase most"""
    label = entry.label or entry.text
    score = 0
    for word in words:
        if word not in label:
            continue  # found in section name only
        score += 2
        if re.search(rf"(^|[\s_]){re.escape(word)}", label):
            score += 2
        if label.startswith(word):
            score += 1
    if len(words) > 1 and " ".join(words) in label:
        score += 4
    return score


def search_options(entries: list[OptionEntry], text: str, limit: int = MAX_RESULTS) -> list[OptionEntry]:
    """Options matching all words (any order, case & accents ignored), best matches first

    Args:
        limit: most results returned, 0 for all.
    """
    words = tuple(sort_key(text).split())
    if not words:
        return []
    found = [entry for entry in entries if all(word in entry.text for word in words)]
    # Best score first, then closest name (fewest other words), page order kept among equals
    found.sort(key=lambda entry: (-match_score(entry, words), len(entry.label.split())))
    return found[:limit] if limit > 0 else found


def open_option(parent, entry: OptionEntry):
    """Open settings page of option, scrolled to (or filtered on) the option

    Global options: Config page. Overlay options: Overlay Options page (saving restarts the edited
    overlays itself). Module & preset options: their config page, filtered on the option.
    """
    if entry.config_type == ConfigType.CONFIG:
        from .app_settings import open_app_settings

        return open_app_settings(parent, entry.section, entry.key)
    if entry.config_type == ConfigType.WIDGET:
        from .overlay_options import open_overlay_options

        return open_overlay_options(parent, entry.section, entry.key)

    from .config import UserConfig

    dialog = UserConfig(
        parent=parent,
        key_name=entry.section,
        preset_name=cfg.filename.setting,
        config_type=entry.config_type,
        user_setting=cfg.user.setting,
        default_setting=cfg.default.setting,
        reload_func=reload_function(entry),
    )
    dialog.open()
    # Same config already open as page: that page is shown & filtered (new copy is deleted)
    shown = dialog.shown_dialog() if isinstance(dialog, BaseDialog) else dialog
    search = getattr(shown, "edit_search", None)
    if search is not None:
        search.setText(entry.key)
    return shown


def reload_function(entry: OptionEntry):
    """Apply changes of edited section"""
    if entry.config_type == ConfigType.WIDGET:
        return lambda: wctrl.reload(entry.section)
    if entry.config_type == ConfigType.MODULE:
        return lambda: mctrl.reload(entry.section)
    return lambda: loader.reload(reload_preset=entry.config_type == ConfigType.CONFIG)


@singleton_dialog("option_finder")
class OptionFinder(BaseDialog):
    """Find Option page"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.finder_backend import FinderBackend

        super().__init__(parent)
        self.set_utility_title(tr("Find Option"))
        self.setMinimumSize(UIScaler.size(34), UIScaler.size(24))
        self.backend = FinderBackend(self, self.open_entry)
        self.entries = self.backend.entries
        self.view: QQuickWidget = create_quick_view(self, "OptionFinder.qml", {"backend": self.backend}, samples=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)

    def open_entry(self, entry: OptionEntry):
        open_option(self.parent(), entry)

    def set_search(self, text: str):
        """Search text (command palette, tests)"""
        self.backend.setSearch(text)

    def showEvent(self, event):
        self.backend.refresh_values()  # values changed while hidden
        super().showEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():  # QML gone before the backend it binds to
            self.view.setSource(QUrl())
