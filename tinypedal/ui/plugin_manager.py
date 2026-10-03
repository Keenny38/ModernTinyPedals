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
Plugin manager: list widget plugins, show errors, enable, trust, hot reload, install
"""

from __future__ import annotations

import html
import os

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import app_signal
from ..i18n import tr, trm
from ..module_control import wctrl
from ..plugin_loader import (
    PLUGIN_ERRORS,
    PLUGIN_FOLDER,
    PLUGIN_PREFIX,
    UNTRUSTED_ERROR,
    discover_plugins,
    install_plugin_package,
    load_plugin_widget,
    plugin_code_files,
    plugin_digest,
    plugin_path,
    trust_plugin,
)
from ..setting import cfg
from ._common import BaseDialog, CompactButton, UIScaler, singleton_dialog
from .toast import show_toast

COLUMNS = ("Plugin", "Status", "Enabled")
ROLE_NAME = Qt.ItemDataRole.UserRole
ROLE_BADGE = Qt.ItemDataRole.UserRole + 1  # badge color of status & enabled cells
BADGE_COLORS = {
    "loaded": "#2DA44E",
    "error": "#D1242F",
    "untrusted": "#BF8700",
    "restart": "#6E7781",
    "off": "#6E7781",
}


def plugin_status(widget_name: str) -> tuple[str, str]:
    """Plugin status text & detail"""
    return plugin_status_kind(widget_name)[1:]


def plugin_status_kind(widget_name: str) -> tuple[str, str, str]:
    """Plugin status kind (badge color key), text & detail"""
    if widget_name not in wctrl.names:
        return "restart", tr("Restart required"), tr("Plugin found after start, restart Modern Tiny Pedals to load it.")
    if PLUGIN_ERRORS.get(widget_name) == UNTRUSTED_ERROR:
        return "untrusted", tr("Not trusted"), tr(UNTRUSTED_ERROR)
    if widget_name in PLUGIN_ERRORS:
        return "error", tr("Error"), PLUGIN_ERRORS[widget_name]
    return "loaded", tr("Loaded"), ""


class BadgeDelegate(QStyledItemDelegate):
    """Draw cell text as a filled pill badge (status at a glance), color from ROLE_BADGE"""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        color = index.data(ROLE_BADGE)
        if not color:
            super().paint(painter, option, index)
            return
        # Row selection & hover background, without text
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        style_option.text = ""
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, style_option, painter, widget)
        text = index.data(Qt.ItemDataRole.DisplayRole)
        metrics = QFontMetricsF(option.font)
        height = metrics.height() + 4
        width = metrics.horizontalAdvance(text) + height
        cell = QRectF(option.rect)
        pill = QRectF(cell.center().x() - width / 2, cell.center().y() - height / 2, width, height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


def reload_plugin(widget_name: str) -> str:
    """Reload plugin code, returns error message or "" """
    module = load_plugin_widget("tinypedal.widget", widget_name)
    wctrl.replace(widget_name, module)
    return PLUGIN_ERRORS.get(widget_name, "")


@singleton_dialog("plugin_manager")
class PluginManager(BaseDialog):
    """Widget plugin manager"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Plugin Manager"))

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels([tr(text) for text in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumSize(UIScaler.size(34), UIScaler.size(14))
        self.table.cellDoubleClicked.connect(lambda row, column: self.toggle_selected())
        self.table.setItemDelegate(BadgeDelegate(self.table))
        self.label_detail = QLabel(self)
        self.label_detail.setWordWrap(True)
        self.table.itemSelectionChanged.connect(self.show_detail)

        warning = QLabel(tr("Plugins run as normal Python code, only install plugins from trusted sources."))
        warning.setWordWrap(True)

        button_toggle = CompactButton(tr("Enable / Disable"))
        button_toggle.clicked.connect(self.toggle_selected)
        button_trust = CompactButton(tr("Trust..."))
        button_trust.clicked.connect(self.trust_selected)
        button_reload = CompactButton(tr("Reload Code"))
        button_reload.clicked.connect(self.reload_selected)
        button_install = CompactButton(tr("Install..."))
        button_install.clicked.connect(self.install)
        button_folder = CompactButton(tr("Open Folder"))
        button_folder.clicked.connect(self.open_folder)
        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.reject)

        layout_button = QHBoxLayout()
        for button in (button_toggle, button_trust, button_reload, button_install, button_folder):
            layout_button.addWidget(button)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        layout = QVBoxLayout()
        layout.addWidget(warning)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.label_detail)
        layout.addLayout(layout_button)
        layout.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout)
        self.refresh()

    def plugin_names(self) -> list[str]:
        loaded = [name for name in wctrl.names if name.startswith(PLUGIN_PREFIX)]
        found = discover_plugins()
        return sorted(set(loaded) | set(found))

    def refresh(self):
        selected = self.selected_name()
        names = self.plugin_names()
        self.table.setRowCount(len(names))
        accent = self.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name()
        for row, name in enumerate(names):
            kind, status, _ = plugin_status_kind(name)
            enabled = bool(cfg.user.setting.get(name, {}).get("enable", False))
            cells = (
                (name[len(PLUGIN_PREFIX):], ""),
                (status, BADGE_COLORS[kind]),
                (tr("On") if enabled else tr("Off"), accent if enabled else BADGE_COLORS["off"]),
            )
            for column, (text, badge) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(ROLE_NAME, name)
                if badge:
                    item.setData(ROLE_BADGE, badge)
                self.table.setItem(row, column, item)
            if name == selected:
                self.table.selectRow(row)
        if not names:
            self.label_detail.setText(trm(f"No plugin found in \"{PLUGIN_FOLDER}\" folder."))

    def selected_name(self) -> str:
        items = self.table.selectedItems()
        return items[0].data(ROLE_NAME) if items else ""

    def show_detail(self):
        name = self.selected_name()
        if name:
            self.label_detail.setText(plugin_status(name)[1] or tr("Plugin loaded without error."))

    def toggle_selected(self):
        name = self.selected_name()
        if not name or name not in wctrl.names:
            return
        wctrl.toggle(name)
        app_signal.refresh.emit(True)
        self.refresh()

    def reload_selected(self):
        name = self.selected_name()
        if not name or name not in wctrl.names:
            return
        error = reload_plugin(name)
        if error:
            QMessageBox.warning(self, tr("Error"), trm(f"Plugin reloaded with error:<br>{error}"))
        self.refresh()
        self.show_detail()

    def trust_selected(self):
        """Show plugin code files & digest, trust after confirmation, then load code"""
        name = self.selected_name()
        if not name:
            return
        path = plugin_path(name)
        try:
            files = plugin_code_files(path)
            digest = plugin_digest(path)
        except OSError as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to read plugin:<br>{error}"))
            return
        file_list = "<br>".join(html.escape(file) for file in files) or "-"
        if not self.confirm_operation(
            tr("Trust..."),
            (
                "Plugins run as normal Python code with full access to your computer."
                f"<br>Only trust <b>{name[len(PLUGIN_PREFIX):]}</b> if you reviewed its code or trust its author."
                f"<br><br>Code files:<br>{file_list}<br><br>SHA-256: <code>{digest[:32]}<br>{digest[32:]}</code>"
                "<br><br>Trust this plugin? Any later code change requires trusting again."
            ),
        ):
            return
        try:
            trust_plugin(name)
        except OSError as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to save plugin trust:<br>{error}"))
            return
        if name in wctrl.names:
            load_error = reload_plugin(name)
            if load_error:
                QMessageBox.warning(self, tr("Error"), trm(f"Plugin loaded with error:<br>{load_error}"))
        self.refresh()
        self.show_detail()

    def install(self):
        filename, _ = QFileDialog.getOpenFileName(self, tr("Install..."), "", "Zip (*.zip)")
        if filename:
            self.install_file(filename)

    def install_file(self, filename: str):
        """Install plugin package file, after confirmation"""
        if not self.confirm_operation(
            tr("Install..."),
            "Plugins run as normal Python code, only install plugins from trusted sources.<br><br>Install plugin?",
        ):
            return
        try:
            name = install_plugin_package(filename)
            trust_plugin(name)  # installing is confirmed by user above
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to install plugin:<br>{error}"))
            return
        show_toast(
            self, trm(f"Plugin <b>{name[len(PLUGIN_PREFIX):]}</b> installed, restart Modern Tiny Pedals to load it."))
        self.refresh()

    @staticmethod
    def open_folder():
        os.makedirs(PLUGIN_FOLDER, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(PLUGIN_FOLDER)))
