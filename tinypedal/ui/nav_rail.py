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
Navigation rail entries: pages of main window & tool dialogs, chosen & ordered by user

Rail content is saved in application setting "rail_items": entry keys separated by comma,
page keys (see NAV_PAGES) or tool dialog module names (see tools_view.TOOL_SECTIONS).
Pages left out of the rail stay reachable from command palette (Ctrl+K).
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..const_file import ConfigType
from ..i18n import tr
from ..setting import cfg
from ..template.setting_global import GLOBAL_DEFAULT
from ._common import BaseDialog, UIScaler
from .tools_view import RENAMED_TOOL_KEYS, TOOL_SECTIONS

# Pages: (key, label, icon glyph in Segoe Fluent Icons / MDL2 Assets, fallback letter)
NAV_PAGES = (
    ("home", "Home", "", "A"),  # home
    ("widget", "Overlays", "", "W"),  # all apps grid
    ("module", "Module", "", "M"),  # diagnostic
    ("preset", "Preset", "", "P"),  # library
    ("spectate", "Spectate", "", "S"),  # view
    ("pacenotes", "Pacenotes", "", "N"),  # quick note
    ("hotkey", "Hotkey", "", "H"),  # keyboard
    ("tools", "Tools", "", "T"),  # developer tools
)
PAGE_INDEX = {key: index for index, (key, *_) in enumerate(NAV_PAGES)}

# Short rail label of tools (rail buttons are narrow), full name in tooltip
TOOL_SHORT_LABELS = {
    "race_calculator": "Race",
    "driver_stats_viewer": "Stats",
    "track_map_viewer": "Map",
    "lap_viewer": "Telemetry",
    "replay_view": "Replay",
    "heatmap_editor": "Heatmap",
    "brake_editor": "Brakes",
    "tyre_compound_editor": "Compounds",
    "vehicle_brand_editor": "Brands",
    "vehicle_class_editor": "Classes",
    "track_info_editor": "Tracks",
    "track_notes_editor": "Notes",
    "layout_editor": "Layout",
    "theme_editor": "Themes",
    "preset_compare": "Compare",
    "plugin_manager": "Plugins",
    "perf_view": "Performance",
}


class RailEntry(NamedTuple):
    """Navigation rail entry"""

    key: str
    label: str  # short label under icon
    tooltip: str  # full name
    glyph: str
    letter: str  # drawn without icon font
    page: int = -1  # page index, -1 for tool
    dialog: str = ""  # "module.DialogClass" of tool


def rail_entries() -> dict[str, RailEntry]:
    """Every possible rail entry by key, pages first then tools"""
    entries = {
        key: RailEntry(key, label, label, glyph, letter, page=index)
        for index, (key, label, glyph, letter) in enumerate(NAV_PAGES)
    }
    for _, tools in TOOL_SECTIONS:
        for label, glyph, dialog_path in tools:
            key = dialog_path.split(".", 1)[0]
            short = TOOL_SHORT_LABELS.get(key, label)
            entries[key] = RailEntry(key, short, label, glyph, short[:1], dialog=dialog_path)
    return entries


def parse_rail_items(text: str) -> list[str]:
    """Known & unique entry keys of rail setting text, in order"""
    known = rail_entries()
    keys: list[str] = []
    for key in (text or "").split(","):
        key = RENAMED_TOOL_KEYS.get(key.strip(), key.strip())  # merged tools: new tool
        if key in known and key not in keys:
            keys.append(key)
    return keys


def default_rail_items() -> list[str]:
    application: dict = GLOBAL_DEFAULT["application"]  # type: ignore[assignment]
    return parse_rail_items(str(application["rail_items"]))


def current_rail_items() -> list[str]:
    """Rail entry keys from setting, default rail if setting has no valid entry"""
    return parse_rail_items(cfg.application.get("rail_items", "")) or default_rail_items()


class RailEditor(BaseDialog):
    """Choose & order navigation rail entries"""

    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self.set_utility_title(tr("Customize Navigation Bar"))
        self.setMinimumSize(UIScaler.size(22), UIScaler.size(30))
        self._on_saved = on_saved
        label = QLabel(tr("Check entries to show, drag to reorder. Hidden pages stay in command palette (Ctrl+K)."))
        label.setWordWrap(True)
        self.list_entries = QListWidget(self)
        self.list_entries.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_entries.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.fill(current_rail_items())

        button_up = QPushButton(tr("Up"))
        button_up.clicked.connect(lambda: self.move_current(-1))
        button_down = QPushButton(tr("Down"))
        button_down.clicked.connect(lambda: self.move_current(1))
        button_reset = QPushButton(tr("Reset"))
        button_reset.clicked.connect(lambda: self.fill(default_rail_items()))
        button_save = QPushButton(tr("Save"))
        button_save.clicked.connect(self.saving)
        button_cancel = QPushButton(tr("Close"))
        button_cancel.clicked.connect(self.reject)
        layout_button = QHBoxLayout()
        for button in (button_up, button_down, button_reset):
            layout_button.addWidget(button)
        layout_button.addStretch(1)
        layout_button.addWidget(button_save)
        layout_button.addWidget(button_cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.list_entries, stretch=1)
        layout.addLayout(layout_button)
        layout.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)

    def fill(self, shown: list[str]):
        """Shown entries first in rail order, then hidden ones"""
        entries = rail_entries()
        self.list_entries.clear()
        for key in [*shown, *(key for key in entries if key not in shown)]:
            entry = entries[key]
            text = tr(entry.tooltip) if entry.page >= 0 else f"{tr(entry.tooltip)}  ({tr('Tool')})"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in shown else Qt.CheckState.Unchecked)
            self.list_entries.addItem(item)

    def move_current(self, step: int):
        row = self.list_entries.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list_entries.count():
            return
        item = self.list_entries.takeItem(row)
        self.list_entries.insertItem(target, item)
        self.list_entries.setCurrentRow(target)

    def checked_items(self) -> list[str]:
        keys = []
        for row in range(self.list_entries.count()):
            item = self.list_entries.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                keys.append(item.data(Qt.ItemDataRole.UserRole))
        return keys

    def saving(self):
        keys = self.checked_items()
        cfg.application["rail_items"] = ",".join(keys) if keys else ",".join(default_rail_items())
        cfg.save(config_type=ConfigType.CONFIG)
        if self._on_saved is not None:
            self._on_saved()
        self.accept()
