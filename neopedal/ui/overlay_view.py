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
Overlays page: every overlay as a card with its preview (or a compact row), search & filters

Qt Quick page (qml/Overlays.qml), state & actions in quick/overlay_backend.py. The QML page is
created when first shown: no QML engine started at launch while another page is shown. The screen view
can show a screenshot of the game under the overlays: captured here (window hidden meanwhile) or picked
from a file.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEventLoop, Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from ..i18n import tr
from ..module_control import ModuleControl, wctrl
from .quick.overlay_backend import OverlayBackend

CAPTURE_DELAY_MS = 250  # window hidden this long before screen captured (compositor fade out)


class OverlayView(QWidget):
    """Overlays page"""

    def __init__(self, parent, module_control: ModuleControl = wctrl):
        super().__init__(parent)
        self.module_control = module_control
        self.backend = OverlayBackend(
            self, module_control, self.open_config, self.confirm, self.show_log,
            self.export_settings, self.import_settings, self.open_presets,
            capture_screen=self.capture_screen, pick_screenshot=self.pick_screenshot, ask=self.ask)
        self.view: QQuickWidget | None = None  # see ensure_view
        self._creating = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        # Ctrl+Z: last switch, batch switch or move of this page undone, as the Undo of its toast (the search
        # field keeps its own undo while focused: shortcut override)
        self.shortcut_undo = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self, self.backend.undo)
        self.shortcut_undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def ensure_view(self) -> QQuickWidget | None:
        """QML page, created on first use"""
        if self.view is None and not self._creating:
            from .quick import create_quick_view
            from .quick.preview_provider import install_provider as install_preview_provider

            self._creating = True  # page shown again while QML loads: one page only
            try:
                view = create_quick_view(self, "Overlays.qml", {"backend": self.backend}, samples=0)
                install_preview_provider(view.engine())  # overlay pictures (image://overlaypreview)
            finally:
                self._creating = False
            view.setAcceptDrops(False)  # preset & plugin files dropped go to main window
            self._layout.addWidget(view)
            view.show()  # child added to a shown page is not shown by itself
            self.setFocusProxy(view)
            self.view = view
        return self.view

    def showEvent(self, event):
        self.ensure_view()
        self.backend.set_active(True)
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.set_active(False)  # no preview rendered while racing with window hidden
        super().hideEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.release_page()

    def release_page(self):
        """Page closed or released (see LazyPage.release): QML deleted, then the backend's jobs, timers &
        deferred work stopped

        QML torn down by the event loop (deleteLater), never by setSource(QUrl()) here: Qt's image reader
        thread may be in the Python preview provider (async overlay pictures), waiting for the GIL this call
        holds while Qt waits for that thread (deadlock). The event loop runs without the GIL. The backend
        (child of this page) outlives the QML bound to it.
        """
        if self.view is not None:
            view, self.view = self.view, None
            view.hide()
            view.deleteLater()
        self.backend.release()

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Setting, preset or overlay state changed elsewhere (hotkey, tray, other page)"""
        self.backend.refresh()

    def open_config(self, name: str):
        """Overlay Options page at overlay (saved options restart it & refresh this page)"""
        from .overlay_options import open_overlay_options

        open_overlay_options(self, name)

    def confirm(self, text: str) -> bool:
        from ._common import confirm_action

        return confirm_action(self, tr("Confirm"), text, tr("Confirm"))

    def ask(self, text: str, action_text: str, on_result):
        """Question in the page (TpDialogHost), else a dialog: Cancel, then the action button"""
        from .quick import dialogs

        dialogs.confirm(self, tr("Confirm"), text, action_text, on_result)

    def export_settings(self, names: list[str]):
        """Settings of picked overlays saved as package file (saved values)"""
        from .overlay_share import export_overlay_settings

        export_overlay_settings(self, names)

    def import_settings(self):
        """Overlay settings package imported as pending edits of Overlay Options page"""
        from .overlay_share import import_overlay_settings

        import_overlay_settings(self)

    def open_presets(self):
        """Presets page of main window"""
        host = self.parentWidget()
        while host is not None and not hasattr(host, "select_preset_tab"):
            host = host.parentWidget()
        if host is not None:
            host.select_preset_tab()

    def capture_screen(self, name: str) -> QImage | None:
        """Picture of the screen of this name, without the app window (hidden meanwhile, shown again after)"""
        screen = next((screen for screen in QGuiApplication.screens() if screen.name() == name), None)
        if screen is None:
            return None
        window = self.window()
        window.hide()
        # Hidden window may still be on screen (fade out): short wait, user input left for later
        wait = QEventLoop()
        QTimer.singleShot(CAPTURE_DELAY_MS, wait.quit)
        wait.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        if not shiboken6.isValid(window):
            return None
        captured = shiboken6.isValid(self) and shiboken6.isValid(screen)  # not closed or removed meanwhile
        grabbed = screen.grabWindow(0) if captured else None
        window.show()
        window.raise_()
        window.activateWindow()
        if grabbed is None or grabbed.isNull():
            return None
        return grabbed.toImage() if isinstance(grabbed, QPixmap) else grabbed

    def pick_screenshot(self) -> str:
        """Screenshot file of the game, "" if cancelled"""
        from ._common import translate_filter

        filename, _ = QFileDialog.getOpenFileName(
            self, tr("Load Screenshot…"), "", translate_filter("Images (*.png *.jpg *.jpeg *.bmp)"))
        return filename

    def show_log(self):
        from .log_info import LogInfo

        LogInfo(self.window()).show()
