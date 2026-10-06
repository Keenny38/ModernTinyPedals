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
Settings page: every global option (config.json) by category, in one page

Qt Quick page (qml/Settings.qml), state & actions in quick/settings_backend.py. Replaces the config
pages of Application, Compatibility, Notification, Overlay Style, Remote Control, Web Dashboard,
VR Overlay & User Path (Config menu entries open their category).
"""

from __future__ import annotations

import os
import sys
from contextlib import suppress

from PySide6.QtCore import QMetaObject, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QColorDialog, QFileDialog, QMessageBox, QVBoxLayout

from .. import app_signal, loader
from ..const_file import FileFilter
from ..i18n import current_language, tr, trm
from ._common import BaseDialog, UIScaler, run_after_saving, translate_filter
from .toast import show_toast

TITLE = "Config"


def open_app_settings(parent, section: str = "", key: str = "") -> AppSettings:
    """Open settings page (shown again if open) at category of config section, option flashed if set"""
    dialog = AppSettings(parent)
    dialog.open()
    shown = dialog.shown_dialog()  # same page already open: shown instead, this copy deleted
    if isinstance(shown, AppSettings):
        if key:
            shown.backend.focus_option(section, key)
        elif section:
            shown.backend.selectCategory(section)
    return shown  # type: ignore[return-value]


class AppSettings(BaseDialog):
    """Settings page (global options of config.json)"""

    def __init__(self, parent):
        from .quick import create_quick_view
        from .quick.settings_backend import SettingsBackend

        super().__init__(parent)
        self.set_utility_title(tr(TITLE))
        # Layout follows page width (categories as a choice list when narrow): window never grown for it
        self.setMinimumSize(UIScaler.size(32), UIScaler.size(24))
        self.backend = SettingsBackend(self, self)
        self.backend.stateChanged.connect(self.refresh_modified)
        self._language = current_language()
        self._stale = False  # changed while hidden, see refresh
        self.view: QQuickWidget = create_quick_view(self, "Settings.qml", {"backend": self.backend}, samples=0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        # Text fields keep their own undo while focused (shortcut override)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self, self.backend.undo)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Redo), self, self.backend.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.backend.redo)
        app_signal.refresh.connect(self.refresh)

    # Page state
    def is_modified(self) -> bool:
        return self.backend.is_modified()

    def save_action(self):
        """Ctrl+S: Apply, page kept open"""
        return self.apply_edits

    def apply_edits(self) -> bool:
        """Field being edited committed first (Ctrl+S keeps focus in it), then Apply"""
        root = self.view.rootObject() if self.view is not None else None
        if root is not None:
            QMetaObject.invokeMethod(root, "commitEdits")
        return self.backend.apply()

    def refresh(self, *_):
        """Settings saved elsewhere, or app language changed: page updated now if shown, else once shown
        (navigation bar page kept open behind other pages)"""
        if self.view is None:
            return
        if not self.isVisible():
            self._stale = True
            return
        self.refresh_now()

    def refresh_now(self):
        """Values & status cards read again, page rebuilt in new app language"""
        self._stale = False
        if self.view is None:
            return
        if current_language() != self._language:
            self.retranslate()
        self.backend.refresh()

    def showEvent(self, event):
        if self._stale:
            self.refresh_now()
        super().showEvent(event)

    def retranslate(self):
        """QML texts & page title in new app language, pending edits kept"""
        self._language = current_language()
        self.set_utility_title(tr(TITLE))
        from .app import DialogPage

        page = self.parentWidget()
        while page is not None and not isinstance(page, DialogPage):
            page = page.parentWidget()
        if isinstance(page, DialogPage):  # in-app page title
            page.title = tr(TITLE)
            page.show_modified()
        source = self.view.source()
        self.view.setSource(QUrl())
        self.view.setSource(source)

    def closeEvent(self, event):
        if self.is_modified():
            confirm = QMessageBox.question(
                self, tr("Confirm"), tr("<b>Save changes before continue?</b>"),
                buttons=QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if confirm == QMessageBox.StandardButton.Cancel or (
                    confirm == QMessageBox.StandardButton.Save and not self.apply_edits()):
                event.ignore()
                return
        event.accept()
        with suppress(RuntimeError, TypeError):  # closed twice
            app_signal.refresh.disconnect(self.refresh)
        view, self.view = self.view, None  # type: ignore[assignment]
        if view is not None:  # closed twice (nested event loop while asking to save)
            view.setSource(QUrl())  # QML gone before the backend it binds to

    def reject(self):
        """Esc: close, asking to save pending changes"""
        self.close()

    # Settings host: dialogs & applying
    def confirm(self, text: str) -> bool:
        return self.confirm_operation(title="Confirm", message=text)

    def pick_color(self, color: str) -> str:
        from ._option import ColorEdit

        dialog = QColorDialog(self)
        for index, old_color in enumerate(ColorEdit.HISTORY):
            dialog.setCustomColor(index, QColor(old_color))
        picked = dialog.getColor(
            initial=QColor(color), parent=self, options=QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not picked.isValid():
            return ""
        if ColorEdit.HISTORY[0] != picked:
            ColorEdit.HISTORY.appendleft(picked)
        name_format = QColor.NameFormat.HexRgb if picked.alpha() == 255 else QColor.NameFormat.HexArgb
        return picked.name(name_format).upper()

    def pick_folder(self, folder: str) -> str:
        return QFileDialog.getExistingDirectory(self, dir=folder)

    def pick_image(self, filename: str) -> str:
        return QFileDialog.getOpenFileName(self, dir=filename, filter=translate_filter(FileFilter.PNG))[0]

    def open_folder(self, folder: str):
        """Folder in file manager, created if missing"""
        with suppress(OSError):
            os.makedirs(folder, exist_ok=True)
        if os.path.isdir(folder):
            if sys.platform == "win32":  # platform check also read by type checker
                try:
                    os.startfile(folder)
                    return
                except OSError:  # no associated application, access denied: try Qt below
                    pass
            if QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
                return
        QMessageBox.warning(self, tr("Error"), trm(f"Cannot open folder:<br><b>{folder}</b>"))

    def applied(self, sections: set[str], restart: list[str]):
        """Settings saved: notices only refresh the window, other settings reload the app, options read at
        startup offer a restart"""
        from .menu import menu_reload_preset

        if restart and self.confirm_operation(
                title="Restart Modern Tiny Pedals",
                message=f"<b>{', '.join(restart)}</b>: restart Modern Tiny Pedals now to apply?"):
            window = self.window()
            restart_app = getattr(window, "restart_app", None) if window is not self else None
            run_after_saving(restart_app if callable(restart_app) else loader.restart)
            return
        show_toast(self, tr("Settings saved"))
        if sections <= {"notification"}:
            app_signal.refresh.emit(True)
        else:
            run_after_saving(menu_reload_preset)  # overlays, modules & servers restarted

    def open_link(self, name: str):
        """Settings kept in the loaded preset, edited on their own page"""
        from .menu import open_preset_config

        open_preset_config(self.parentWidget() or self, name)
