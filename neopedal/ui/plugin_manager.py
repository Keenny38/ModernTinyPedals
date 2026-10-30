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
Plugin manager: list widget plugins, show errors, enable, trust, hot reload, install
"""

from __future__ import annotations

import html
import os

from PySide6.QtCore import QFile, QRectF, Qt, QUrl
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
from . import status_color
from ._common import BaseDialog, CompactButton, UIScaler, confirm_action, singleton_dialog
from .toast import show_toast

COLUMNS = ("Plugin", "Status", "Enabled")
ROLE_NAME = Qt.ItemDataRole.UserRole
ROLE_BADGE = Qt.ItemDataRole.UserRole + 1  # badge color name of status & enabled cells
BADGE_ACCENT = "accent"  # palette highlight color
BADGE_COLORS = {  # status color names (see status_color), colors read when painted (theme may change)
    "loaded": "badge_success",
    "error": "badge_danger",
    "untrusted": "badge_warning",
    "restart": "badge_neutral",
    "off": "badge_neutral",
    "on": BADGE_ACCENT,
}


def plugin_status(widget_name: str) -> tuple[str, str]:
    """Plugin status text & detail"""
    return plugin_status_kind(widget_name)[1:]


def plugin_status_kind(widget_name: str) -> tuple[str, str, str]:
    """Plugin status kind (badge color key), text & detail"""
    if widget_name not in wctrl.names:
        return "restart", tr("Restart required"), tr("Plugin found after start, restart NeoPedal to load it.")
    if PLUGIN_ERRORS.get(widget_name) == UNTRUSTED_ERROR:
        return "untrusted", tr("Not trusted"), tr(UNTRUSTED_ERROR)
    if widget_name in PLUGIN_ERRORS:  # known error texts translated (safe mode...), others as is
        return "error", tr("Error"), tr(PLUGIN_ERRORS[widget_name])
    return "loaded", tr("Loaded"), ""


def badge_colors(badge: str, palette: QPalette) -> tuple[QColor, QColor]:
    """Badge background & text colors of window theme in use"""
    if badge == BADGE_ACCENT:
        return (
            palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight),
            palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText),
        )
    return QColor(status_color(badge, palette)), QColor(status_color("badge_text", palette))


class BadgeDelegate(QStyledItemDelegate):
    """Draw cell text as a filled pill badge (status at a glance), color name from ROLE_BADGE"""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        badge = index.data(ROLE_BADGE)
        if not badge:
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
        background, foreground = badge_colors(badge, option.palette)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setPen(foreground)
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


def reload_plugin(widget_name: str) -> str:
    """Reload plugin code, returns error message or "" """
    module = load_plugin_widget("neopedal.widget", widget_name)
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

        # Buttons named after what they do to the selected plugin (Enable or Disable), off without selection
        self.button_toggle = button_toggle = CompactButton(tr("Enable"))
        button_toggle.clicked.connect(self.toggle_selected)
        self.button_trust = button_trust = CompactButton(tr("Trust Plugin…"))
        button_trust.setToolTip(tr("Review the plugin code files and fingerprint, then allow it to run"))
        button_trust.clicked.connect(self.trust_selected)
        self.button_reload = button_reload = CompactButton(tr("Reload Code"))
        button_reload.clicked.connect(self.reload_selected)
        self.button_uninstall = button_uninstall = CompactButton(tr("Uninstall…"))
        button_uninstall.setToolTip(tr("Move the plugin files to the recycle bin (restart to unload it)"))
        button_uninstall.clicked.connect(self.uninstall_selected)
        button_install = CompactButton(tr("Install…"))
        button_install.clicked.connect(self.install)
        button_folder = CompactButton(tr("Open Folder"))
        button_folder.clicked.connect(self.open_folder)
        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.reject)
        self.table.itemSelectionChanged.connect(self.refresh_buttons)

        layout_button = QHBoxLayout()
        for button in (button_toggle, button_trust, button_reload, button_uninstall, button_install, button_folder):
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
        self.refresh_buttons()

    def refresh_buttons(self):
        """Buttons of selected plugin: Enable or Disable as its state, Trust only while not trusted"""
        name = self.selected_name()
        loaded = bool(name) and name in wctrl.names
        enabled = bool(cfg.user.setting.get(name, {}).get("enable", False)) if name else False
        self.button_toggle.setText(tr("Disable") if enabled else tr("Enable"))
        self.button_toggle.setEnabled(loaded)
        self.button_trust.setEnabled(bool(name) and plugin_status_kind(name)[0] == "untrusted")
        self.button_reload.setEnabled(loaded)
        self.button_uninstall.setEnabled(bool(name))

    def plugin_names(self) -> list[str]:
        loaded = [name for name in wctrl.names if name.startswith(PLUGIN_PREFIX)]
        found = discover_plugins()
        return sorted(set(loaded) | set(found))

    def refresh(self):
        selected = self.selected_name()
        names = self.plugin_names()
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            kind, status, _ = plugin_status_kind(name)
            enabled = bool(cfg.user.setting.get(name, {}).get("enable", False))
            cells = (
                (name[len(PLUGIN_PREFIX):], ""),
                (status, BADGE_COLORS[kind]),
                (tr("On") if enabled else tr("Off"), BADGE_COLORS["on" if enabled else "off"]),
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
        self.refresh_buttons()

    def reload_selected(self):
        name = self.selected_name()
        if not name or name not in wctrl.names:
            return
        error = reload_plugin(name)
        if error:
            QMessageBox.warning(self, tr("Error"), trm(f"Plugin reloaded with error:<br>{html.escape(tr(error))}"))
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
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to read plugin:<br>{html.escape(str(error))}"))
            return
        file_list = "<br>".join(html.escape(file) for file in files) or "-"
        plugin_name = html.escape(name[len(PLUGIN_PREFIX):])
        if not self.confirm_operation(
            tr("Trust Plugin…"),
            (
                "Plugins run as normal Python code with full access to your computer."
                f"<br>Only trust <b>{plugin_name}</b> if you reviewed its code or trust its author."
                f"<br><br>Code files:<br>{file_list}<br><br>SHA-256: <code>{digest[:32]}<br>{digest[32:]}</code>"
                "<br><br>Trust this plugin? Any later code change requires trusting again."
            ),
        ):
            return
        try:
            trust_plugin(name, expected_digest=digest)  # refuse code changed after confirmation
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to save plugin trust:<br>{html.escape(str(error))}"))
            return
        if name in wctrl.names:
            load_error = reload_plugin(name)
            if load_error:
                QMessageBox.warning(
                    self, tr("Error"), trm(f"Plugin loaded with error:<br>{html.escape(tr(load_error))}"))
        self.refresh()
        self.show_detail()
        self.refresh_buttons()

    def uninstall_selected(self):
        """Plugin files moved to the recycle bin after confirmation (never deleted for good), disabled first;
        unloaded at next start"""
        name = self.selected_name()
        if not name:
            return
        path = plugin_path(name)
        plugin_name = html.escape(name[len(PLUGIN_PREFIX):])
        if not confirm_action(
            self, tr("Uninstall Plugin"),
            trm(f"Move plugin <b>{plugin_name}</b> to the recycle bin?<br><br>"
                "It stops once NeoPedal restarts. Restore it from the recycle bin to install it again."),
            tr("Uninstall"), danger=True,
        ):
            return
        if name in wctrl.names and cfg.user.setting.get(name, {}).get("enable", False):
            wctrl.toggle(name)  # overlay closed now, setting saved off
            app_signal.refresh.emit(True)
        if not os.path.exists(path) or not QFile.moveToTrash(path):
            QMessageBox.warning(self, tr("Error"), trm(
                f"Unable to move plugin <b>{plugin_name}</b> to the recycle bin. Remove it from the plugins folder."))
            return
        show_toast(self, trm(f"Plugin <b>{plugin_name}</b> moved to the recycle bin, restart NeoPedal to unload it."))
        self.refresh()
        self.refresh_buttons()

    def install(self):
        from .quick import last_folder  # picker started in the folder of the last package installed

        filename, _ = QFileDialog.getOpenFileName(self, tr("Install…"), last_folder.start_folder("plugin_install"),
                                                  "Zip (*.zip)")
        if filename:
            last_folder.remember("plugin_install", filename)
            self.install_file(filename)

    def install_file(self, filename: str):
        """Install plugin package file, after confirmation"""
        if not self.confirm_operation(
            tr("Install…"),
            "Plugins run as normal Python code, only install plugins from trusted sources.<br><br>Install plugin?",
        ):
            return
        try:
            name = install_plugin_package(filename)
            trust_plugin(name)  # installing is confirmed by user above
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("Error"), trm(f"Unable to install plugin:<br>{html.escape(str(error))}"))
            return
        plugin_name = html.escape(name[len(PLUGIN_PREFIX):])
        show_toast(self, trm(f"Plugin <b>{plugin_name}</b> installed, restart NeoPedal to load it."))
        self.refresh()

    @staticmethod
    def open_folder():
        os.makedirs(PLUGIN_FOLDER, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(PLUGIN_FOLDER)))
