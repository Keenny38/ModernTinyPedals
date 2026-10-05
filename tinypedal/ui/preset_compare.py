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
Preset comparison dialog
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import loader
from ..const_file import FileExt
from ..i18n import tr, trm
from ..i18n.options import module_label, option_label, option_tooltip
from ..setting import cfg, load_setting_json_file, save_and_verify_json_file
from ..userfile.json_setting import copy_setting
from ..userfile.preset_compare import copy_values, diff_presets
from ._common import BaseEditor, CompactButton, UIScaler, singleton_dialog, table_item

COLUMNS = ("Section", "Option", "Preset A", "Preset B")


def load_preset(filename: str) -> dict:
    """Load preset file (validated, missing options filled with default)"""
    if cfg.is_loaded(filename):
        return copy_setting(cfg.user.setting)
    return load_setting_json_file(filename=filename, filepath=cfg.path.settings, dict_def=cfg.default.setting)


def format_value(value) -> str:
    if isinstance(value, bool):
        return tr("On") if value else tr("Off")
    return "" if value is None else str(value)


@singleton_dialog("preset_compare")
class PresetCompare(BaseEditor):
    """Compare two presets, copy options between them"""

    def __init__(self, parent, preset_a: str = "", preset_b: str = ""):
        super().__init__(parent)
        self.set_utility_title(tr("Preset Comparison"))
        self.presets: dict[str, dict] = {}  # file name: loaded (possibly edited) preset
        self.edits: dict[str, dict[tuple[str, str], Any]] = {}  # file name: copied values by (section, key)

        files = [f"{name}{FileExt.JSON}" for name in cfg.preset_files()]
        self.combo_a = QComboBox(self)
        self.combo_b = QComboBox(self)
        for combo in (self.combo_a, self.combo_b):
            combo.addItems(files)
        self.combo_a.setCurrentText(preset_a or cfg.filename.setting)
        self.combo_b.setCurrentText(preset_b or next((name for name in files if name != self.combo_a.currentText()), ""))
        self.combo_a.currentTextChanged.connect(self.refresh)
        self.combo_b.currentTextChanged.connect(self.refresh)

        self.check_position = QCheckBox(tr("Ignore widget positions"), self)
        self.check_position.setChecked(True)
        self.check_position.toggled.connect(self.refresh)
        self.edit_filter = QLineEdit(self)
        self.edit_filter.setPlaceholderText(tr("Filter"))
        self.edit_filter.textChanged.connect(self.apply_filter)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels([tr(text) for text in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumSize(UIScaler.size(46), UIScaler.size(26))
        self.label_count = QLabel(self)

        button_to_a = CompactButton(tr("Copy B → A"))
        button_to_a.clicked.connect(lambda: self.copy_selected(to_a=True))
        button_to_b = CompactButton(tr("Copy A → B"))
        button_to_b.clicked.connect(lambda: self.copy_selected(to_a=False))
        button_save = CompactButton(tr("Save"))
        button_save.clicked.connect(self.saving)
        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.close)

        layout_select = QGridLayout()
        layout_select.addWidget(QLabel(tr("Preset A")), 0, 0)
        layout_select.addWidget(self.combo_a, 0, 1)
        layout_select.addWidget(QLabel(tr("Preset B")), 1, 0)
        layout_select.addWidget(self.combo_b, 1, 1)
        layout_select.setColumnStretch(1, 1)
        layout_filter = QHBoxLayout()
        layout_filter.addWidget(self.edit_filter, stretch=1)
        layout_filter.addWidget(self.check_position)
        layout_button = QHBoxLayout()
        layout_button.addWidget(button_to_a)
        layout_button.addWidget(button_to_b)
        layout_button.addStretch(1)
        layout_button.addWidget(button_save)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout()
        layout_main.addLayout(layout_select)
        layout_main.addLayout(layout_filter)
        layout_main.addWidget(self.table, stretch=1)
        layout_main.addWidget(self.label_count)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)
        self.refresh()

    def preset(self, filename: str) -> dict:
        if filename not in self.presets:
            self.presets[filename] = load_preset(filename)
        return self.presets[filename]

    def refresh(self):
        """Rebuild difference table"""
        name_a, name_b = self.combo_a.currentText(), self.combo_b.currentText()
        self.table.setRowCount(0)
        if not name_a or not name_b:
            return
        differences = diff_presets(self.preset(name_a), self.preset(name_b), self.check_position.isChecked())
        self.table.setRowCount(len(differences))
        for row, diff in enumerate(differences):
            cells = (
                module_label(diff.section), option_label(diff.key),
                format_value(diff.value_a), format_value(diff.value_b),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, (diff.section, diff.key))
                if column == 1:
                    item.setToolTip(option_tooltip(diff.section, diff.key))
                self.table.setItem(row, column, item)
        if name_a == name_b:
            self.label_count.setText(tr("Select two different presets."))
        else:
            self.label_count.setText(trm(f"Differences: {len(differences)}"))
        self.apply_filter(self.edit_filter.text())

    def apply_filter(self, text: str):
        words = text.lower().split()
        for row in range(self.table.rowCount()):
            content = " ".join(table_item(self.table, row, column).text() for column in range(2)).lower()
            section, key = table_item(self.table, row, 0).data(Qt.ItemDataRole.UserRole)
            haystack = f"{content} {section} {key}"
            self.table.setRowHidden(row, not all(word in haystack for word in words))

    def selected_items(self) -> list[tuple[str, str]]:
        rows = sorted({index.row() for index in self.table.selectedIndexes() if not self.table.isRowHidden(index.row())})
        return [table_item(self.table, row, 0).data(Qt.ItemDataRole.UserRole) for row in rows]

    def copy_selected(self, to_a: bool):
        """Copy selected options between presets"""
        name_a, name_b = self.combo_a.currentText(), self.combo_b.currentText()
        items = self.selected_items()
        if not items or name_a == name_b:
            return
        target, source = (name_a, name_b) if to_a else (name_b, name_a)
        if target in cfg.user.filelock:
            QMessageBox.warning(self, tr("Error"), trm("Changes to locked preset will not be saved."))
            return
        target_preset, source_preset = self.preset(target), self.preset(source)
        if copy_values(target_preset, source_preset, items):
            edits = self.edits.setdefault(target, {})
            for section, key in items:
                if key in source_preset.get(section, {}):
                    edits[section, key] = source_preset[section][key]
            self.set_modified()
            self.refresh()

    def save_action(self):
        """Ctrl+S: save modified presets"""
        return self.saving

    def saving(self):
        """Save modified presets

        Presets are read when shown, then may change elsewhere (loaded preset: widgets moved,
        options edited), so only copied values are written into a fresh copy of each preset.
        """
        reload_loaded = False
        for filename in sorted(self.edits):
            is_loaded = cfg.is_loaded(filename)
            # Loaded preset is live (saved by app), others are read from file again
            preset = cfg.user.setting if is_loaded else load_preset(filename)
            for (section, key), value in self.edits[filename].items():
                preset.setdefault(section, {})[key] = value
            if is_loaded:
                cfg.save(0)
                reload_loaded = True
            else:
                save_and_verify_json_file(
                    dict_user=preset, filename=filename, filepath=cfg.path.settings,
                    max_attempts=cfg.max_saving_attempts,
                )
        self.edits.clear()
        self.presets.clear()  # read again, with changes made elsewhere
        self.set_unmodified()
        if reload_loaded:
            cfg.set_next_to_load(cfg.filename.setting)
            loader.reload(reload_preset=True)  # waits for saving
        self.refresh()
