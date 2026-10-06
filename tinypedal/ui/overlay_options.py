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
Overlay Options page: options of every overlay, in one page

Qt Quick page (qml/OverlayOptions.qml), state & actions in quick/overlay_options_backend.py. Opened at
an overlay (and option) by every "configure overlay" entry: Overlays page, overlay right click menu,
command palette, option search. One page for all overlays: opening it again selects the overlay.
"""

from __future__ import annotations

from contextlib import suppress
from functools import partial

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QColorDialog, QDialog, QFileDialog, QMessageBox, QVBoxLayout

from .. import app_signal
from ..const_file import ConfigType, FileFilter
from ..i18n import current_language, tr
from ..module_control import ModuleControl, wctrl
from ._common import BaseDialog, DialogSingleton, UIScaler, run_after_saving, translate_filter
from .toast import show_toast

TITLE = "Overlay Options"


def open_overlay_options(parent, name: str = "", key: str = "") -> OverlayOptions | None:
    """Open page (shown again if open) at overlay, option flashed if set; None if it cannot open"""
    dialog = OverlayOptions(parent)
    dialog.open()
    shown = dialog.shown_dialog()  # same page already open: shown instead, this copy deleted
    if isinstance(shown, OverlayOptions) and name:
        shown.backend.focus_option(name, key)
    return shown if isinstance(shown, OverlayOptions) else None


def pick_color(parent, color: str) -> str:
    """Color chosen in color dialog (recent colors shared with config pages), "" if cancelled"""
    from ._option import ColorEdit

    dialog = QColorDialog(parent)
    for index, old_color in enumerate(ColorEdit.HISTORY):
        dialog.setCustomColor(index, QColor(old_color))
    picked = dialog.getColor(
        initial=QColor(color), parent=parent, options=QColorDialog.ColorDialogOption.ShowAlphaChannel)
    if not picked.isValid():
        return ""
    if ColorEdit.HISTORY[0] != picked:
        ColorEdit.HISTORY.appendleft(picked)
    name_format = QColor.NameFormat.HexRgb if picked.alpha() == 255 else QColor.NameFormat.HexArgb
    return picked.name(name_format).upper()


class OverlayOptions(BaseDialog):
    """Overlay Options page (options of every overlay, saved in loaded preset)"""

    def __init__(self, parent, module_control: ModuleControl = wctrl):
        from .quick import create_quick_view
        from .quick.overlay_options_backend import OverlayOptionsBackend
        from .quick.preview_provider import install_provider as install_preview_provider

        super().__init__(parent)
        self.set_utility_title(tr(TITLE))
        self.setMinimumSize(UIScaler.size(40), UIScaler.size(26))
        self.module_control = module_control
        self.backend = OverlayOptionsBackend(self, self, module_control)
        self.backend.stateChanged.connect(self.refresh_modified)
        self._language = current_language()
        self._stale = False  # preset or options changed while hidden, see refresh
        self._shown_once = False  # values read when built: read again when shown again
        self.view: QQuickWidget = create_quick_view(
            self, "OverlayOptions.qml", {"backend": self.backend}, samples=0)
        install_preview_provider(self.view.engine())  # overlay pictures (image://overlaypreview)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        self.resize(UIScaler.size(80), UIScaler.size(48))
        # Text fields keep their own undo while focused (shortcut override)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self, self.backend.undo)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Redo), self, self.backend.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.backend.redo)
        app_signal.refresh.connect(self.refresh)
        DialogSingleton.register(ConfigType.CONFIG, self)  # open config pages: preset loading asks first

    # Page state
    def is_modified(self) -> bool:
        return self.backend.is_modified()

    def is_preset_setting(self) -> bool:
        """Unsaved preset options: page kept open (refreshed) when a preset loads unless edited"""
        return self.backend.is_modified()

    def save_action(self):
        """Ctrl+S: Apply, page kept open"""
        return self.backend.apply

    def showEvent(self, event):
        """Saved values read again: options may have changed while hidden without app refresh (overlay
        moved, option switched from Find Option)"""
        if self._stale or self._shown_once:
            self.refresh_now()
        self._shown_once = True
        super().showEvent(event)
        self.backend.set_active(True)

    def hideEvent(self, event):
        self.backend.set_active(False)  # nothing rendered while another page is shown or racing
        super().hideEvent(event)

    def refresh(self, *_):
        """Preset loaded, options saved elsewhere, or app language changed: page updated now if shown,
        else once shown again"""
        if self.view is None:
            return
        if not self.isVisible():
            self._stale = True
            return
        self.refresh_now()

    def refresh_now(self):
        """Saved values read again, page rebuilt in new app language (pending edits kept)"""
        self._stale = False
        if self.view is None:
            return
        if current_language() != self._language:
            self.retranslate()
        self.backend.refresh()

    def retranslate(self):
        """QML texts & page title in new app language, pending edits kept"""
        from .app import DialogPage

        self._language = current_language()
        self.set_utility_title(tr(TITLE))
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
                    confirm == QMessageBox.StandardButton.Save and not self.backend.apply()):
                event.ignore()
                return
        event.accept()
        with suppress(RuntimeError, TypeError):  # closed twice
            app_signal.refresh.disconnect(self.refresh)
        self.backend.close()
        view, self.view = self.view, None  # type: ignore[assignment]
        if view is not None:  # closed twice (nested event loop while asking to save)
            view.setSource(QUrl())  # QML gone before the backend it binds to

    def reject(self):
        """Esc: close, asking to save pending changes"""
        self.close()

    # Backend host: dialogs, notices & applying
    def confirm(self, text: str) -> bool:
        return self.confirm_operation(title="Confirm", message=text)

    def pick_color(self, color: str) -> str:
        return pick_color(self, color)

    def pick_folder(self, folder: str) -> str:
        return QFileDialog.getExistingDirectory(self, dir=folder)

    def pick_image(self, filename: str) -> str:
        return QFileDialog.getOpenFileName(self, dir=filename, filter=translate_filter(FileFilter.PNG))[0]

    def edit_table(self, text: str) -> str | None:
        """Tyre targets per compound in table editor, None if cancelled"""
        from ._option import CompoundTargetDialog

        dialog = CompoundTargetDialog(self, text)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.result_text()
        return None

    def notify(self, text: str):
        show_toast(self, text)

    def applied(self, names: list[str]):
        """Options saved: edited overlays restarted once saving is finished, other pages follow"""
        show_toast(self, tr("Options saved"))
        run_after_saving(partial(restart_overlays, self.module_control, names))


def restart_overlays(module_control: ModuleControl, names: list[str]):
    """Saved overlays restarted with their new options (closed if switched off), pages & menus refreshed"""
    for name in names:
        module_control.reload(name)
    app_signal.refresh.emit(True)
