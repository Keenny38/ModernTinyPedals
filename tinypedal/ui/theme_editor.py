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
Overlay theme editor: create custom color palettes with live preview
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import loader
from ..i18n import tr, trm
from ..setting import cfg
from ..userfile.overlay_theme import save_custom_themes
from ..widget._style import (
    BUILTIN_THEMES,
    MODERN_PALETTE,
    OVERLAY_THEMES,
    custom_themes,
    set_custom_themes,
)
from ._common import BaseEditor, CompactButton, UIScaler, singleton_dialog, table_item
from .widget_preview import render_widget

logger = logging.getLogger(__name__)

PREVIEW_WIDGETS = ("gear", "deltabest", "fuel")
COLUMN_CLASSIC, COLUMN_BASE, COLUMN_THEME = 0, 1, 2


def theme_color(theme: dict, classic: str) -> str:
    """Resulting color of custom theme for classic color"""
    if classic in theme["colors"]:
        return theme["colors"][classic]
    base: Mapping[str, str] = OVERLAY_THEMES.get(theme["base"]) or {}
    return base.get(classic, classic)


class ColorItem(QTableWidgetItem):
    """Color cell with swatch"""

    def __init__(self, rgb: str, editable: bool = False):
        super().__init__(f"#{rgb}")
        self.set_color(rgb)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if editable:
            flags |= Qt.ItemFlag.ItemIsEditable
        self.setFlags(flags)

    def set_color(self, rgb: str):
        color = QColor(f"#{rgb}")
        self.setBackground(color)
        self.setForeground(QColor("#000000" if color.lightness() > 128 else "#FFFFFF"))
        self.setText(f"#{rgb}")


@singleton_dialog("theme_editor")
class ThemeEditor(BaseEditor):
    """Custom overlay theme editor"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Overlay Theme Editor"))
        self.themes: dict[str, dict] = deepcopy(custom_themes())
        self.classic_colors = sorted(MODERN_PALETTE, key=lambda rgb: QColor(f"#{rgb}").hslHue())
        self._loading = False

        # Theme selector
        self.theme_list = QComboBox(self)
        self.theme_list.currentTextChanged.connect(self.load_theme)
        button_new = CompactButton(tr("New"))
        button_new.clicked.connect(self.new_theme)
        button_delete = CompactButton(tr("Delete"))
        button_delete.clicked.connect(self.delete_theme)
        self.base_list = QComboBox(self)
        self.base_list.addItems([name for name in BUILTIN_THEMES if OVERLAY_THEMES[name] is not None])
        self.base_list.currentTextChanged.connect(self.change_base)

        layout_theme = QHBoxLayout()
        layout_theme.addWidget(QLabel(tr("Theme")))
        layout_theme.addWidget(self.theme_list, stretch=1)
        layout_theme.addWidget(button_new)
        layout_theme.addWidget(button_delete)
        layout_theme.addWidget(QLabel(tr("Based on")))
        layout_theme.addWidget(self.base_list)

        # Color table
        self.table = QTableWidget(len(self.classic_colors), 3, self)
        self.table.setHorizontalHeaderLabels((tr("Classic color"), tr("Base theme"), tr("Theme color")))
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self.pick_color)
        self.table.itemChanged.connect(self.edit_color)
        self.table.setMinimumHeight(UIScaler.size(18))

        # Preview
        self.label_preview = QLabel(self)
        self.label_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_preview.setMinimumHeight(UIScaler.size(5))

        # Buttons
        button_reset = CompactButton(tr("Reset Color"))
        button_reset.clicked.connect(self.reset_color)
        button_apply = CompactButton(tr("Apply"))
        button_apply.clicked.connect(self.applying)
        button_save = CompactButton(tr("Save"))
        button_save.clicked.connect(self.saving)
        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.close)
        layout_button = QHBoxLayout()
        layout_button.addWidget(button_reset)
        self.add_undo_buttons(layout_button)
        layout_button.addStretch(1)
        layout_button.addWidget(button_apply)
        layout_button.addWidget(button_save)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout()
        layout_main.addLayout(layout_theme)
        layout_main.addWidget(self.table, stretch=1)
        layout_main.addWidget(QLabel(tr("Preview (double-click a color to change it):")))
        layout_main.addWidget(self.label_preview)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)
        self.setMinimumWidth(UIScaler.size(40))

        self.refresh_theme_list()
        self.enable_undo(lambda: deepcopy(self.themes), self.restore_themes)

    # Theme list
    def refresh_theme_list(self, selected: str = ""):
        self._loading = True
        self.theme_list.clear()
        self.theme_list.addItems(sorted(self.themes))
        self._loading = False
        if selected:
            self.theme_list.setCurrentText(selected)
        self.load_theme(self.theme_list.currentText())

    def restore_themes(self, state: dict):
        current = self.theme_list.currentText()
        self.themes = deepcopy(state)
        self.refresh_theme_list(current if current in self.themes else "")

    def current_theme(self) -> dict | None:
        return self.themes.get(self.theme_list.currentText())

    def new_theme(self):
        name, ok = QInputDialog.getText(self, tr("New Theme"), tr("Theme name:"))
        name = name.strip()
        if not ok or not name:
            return
        if name in self.themes or name in BUILTIN_THEMES or name == "Global":
            QMessageBox.warning(self, tr("Error"), tr("Theme already exists."))
            return
        base = self.theme_list.currentText() and self.current_theme()
        self.themes[name] = deepcopy(base) if base else {"base": "Modern Dark", "colors": {}}
        self.refresh_theme_list(name)
        self.set_modified()

    def delete_theme(self):
        name = self.theme_list.currentText()
        if name and self.confirm_operation(tr("Delete"), trm(f"Delete <b>{name}</b> theme?")):
            self.themes.pop(name, None)
            self.refresh_theme_list()
            self.set_modified()

    def change_base(self, base: str):
        theme = self.current_theme()
        if theme is None or self._loading:
            return
        theme["base"] = base
        self.load_theme(self.theme_list.currentText())
        self.set_modified()

    # Color table
    def load_theme(self, name: str):
        if self._loading:
            return
        theme = self.themes.get(name)
        self._loading = True
        self.table.setEnabled(theme is not None)
        self.base_list.setEnabled(theme is not None)
        if theme is not None:
            self.base_list.setCurrentText(theme["base"])
        base: Mapping[str, str] = (OVERLAY_THEMES.get(theme["base"]) if theme else MODERN_PALETTE) or {}
        for row, classic in enumerate(self.classic_colors):
            self.table.setItem(row, COLUMN_CLASSIC, ColorItem(classic))
            self.table.setItem(row, COLUMN_BASE, ColorItem(base.get(classic, classic)))
            result = theme_color(theme, classic) if theme else classic
            item = ColorItem(result, editable=theme is not None)
            if theme and classic in theme["colors"]:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.table.setItem(row, COLUMN_THEME, item)
        self._loading = False
        self.update_preview()

    def set_theme_color(self, row: int, rgb: str):
        theme = self.current_theme()
        if theme is None:
            return
        classic = self.classic_colors[row]
        base: Mapping[str, str] = OVERLAY_THEMES.get(theme["base"]) or {}
        if rgb == base.get(classic, classic):
            theme["colors"].pop(classic, None)  # same as base, no override needed
        else:
            theme["colors"][classic] = rgb
        self.load_theme(self.theme_list.currentText())
        self.table.setCurrentCell(row, COLUMN_THEME)
        self.set_modified()

    def pick_color(self, row: int, column: int):
        if column != COLUMN_THEME or self.current_theme() is None:
            return
        current = QColor(table_item(self.table, row, COLUMN_THEME).text())
        color = QColorDialog.getColor(current, self, tr("Select Color"))
        if color.isValid():
            self.set_theme_color(row, color.name()[1:].upper())

    def edit_color(self, item: QTableWidgetItem):
        if self._loading or item.column() != COLUMN_THEME:
            return
        text = item.text().strip().lstrip("#").upper()
        if len(text) == 6 and QColor(f"#{text}").isValid():
            self.set_theme_color(item.row(), text)
        else:
            self.load_theme(self.theme_list.currentText())  # revert invalid input

    def reset_color(self):
        row = self.table.currentRow()
        theme = self.current_theme()
        if theme is None or row < 0:
            return
        theme["colors"].pop(self.classic_colors[row], None)
        self.load_theme(self.theme_list.currentText())
        self.set_modified()

    # Preview
    def update_preview(self):
        name = self.theme_list.currentText()
        if not name:
            self.label_preview.setText(tr("Create a theme to start."))
            return
        saved = deepcopy(custom_themes())
        set_custom_themes(self.themes)  # preview edited (unsaved) theme
        try:
            pixmaps = []
            for widget_name in PREVIEW_WIDGETS:
                setting = dict(cfg.user.setting.get(widget_name, cfg.default.setting[widget_name]))
                setting["widget_theme"] = name
                pixmaps.append(render_widget(cfg, widget_name, setting))
        except Exception as error:  # preview must not break editor
            logger.debug("Theme preview error", exc_info=True)
            self.label_preview.setText(trm(f"Preview not available: {error}"))
            return
        finally:
            set_custom_themes(saved)
        self.label_preview.setPixmap(combine_pixmaps(pixmaps))

    # Save
    def applying(self):
        self.save_themes()

    def saving(self):
        if self.save_themes():
            self.set_unmodified()
            self.accept()

    def save_themes(self) -> bool:
        if not save_custom_themes(cfg.path.config, self.themes):
            QMessageBox.warning(self, tr("Error"), tr("Unable to save themes, see log for details."))
            return False
        set_custom_themes(self.themes)
        self.set_unmodified()
        loader.reload(reload_preset=False)  # restyle widgets
        return True


def combine_pixmaps(pixmaps: list):
    """Place pixmaps side by side"""
    from PySide6.QtGui import QPainter, QPixmap

    gap = UIScaler.pixel(8)
    width = sum(pixmap.width() for pixmap in pixmaps) + gap * max(len(pixmaps) - 1, 0)
    height = max((pixmap.height() for pixmap in pixmaps), default=1)
    output = QPixmap(max(width, 1), height)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    offset = 0
    for pixmap in pixmaps:
        painter.drawPixmap(offset, 0, pixmap)
        offset += pixmap.width() + gap
    painter.end()
    return output
