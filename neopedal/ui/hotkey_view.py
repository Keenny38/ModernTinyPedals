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
Hotkeys page: global hotkey switch, key bindings by section (search, assigned only), key capture in a dialog

Qt Quick page (qml/config/Hotkeys.qml), state, key capture & actions in quick/hotkey_backend.py. The QML page is
created when first shown.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Slot
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .quick.hotkey_backend import HotkeyBackend


class HotkeyList(QWidget):
    """Hotkeys page"""

    def __init__(self, parent):
        super().__init__(parent)
        self.backend = HotkeyBackend(self, self.window)
        self.backend.notice.connect(self.show_notice)
        self.view: QQuickWidget | None = None  # see ensure_view
        self._creating = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def ensure_view(self) -> QQuickWidget | None:
        """QML page, created on first use"""
        if self.view is None and not self._creating:
            from .quick import create_quick_view

            self._creating = True  # page shown again while QML loads: one page only
            try:
                view = create_quick_view(self, "Hotkeys.qml", {"backend": self.backend}, samples=0)
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
        self.backend.page_shown()
        super().showEvent(event)

    def hideEvent(self, event):
        self.backend.page_hidden()  # key capture left open: global hotkeys back on
        super().hideEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        self.release_page()

    def release_page(self):
        """Page closed or released (see LazyPage.release): QML gone before the backend it binds to, then the
        backend released (key capture closed)"""
        if self.view is not None:
            view, self.view = self.view, None
            view.setSource(QUrl())
            view.deleteLater()
        self.backend.release()

    @Slot(str, bool)
    def show_notice(self, text: str, undoable: bool):
        """Toast of the page (TpDialogHost), Undo of the last clear"""
        from ..i18n import tr
        from .toast import show_toast

        show_toast(self, text, action_text=tr("Undo") if undoable else "",
                   action=self.backend.undo if undoable else None)

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Global hotkey switch, bindings or presets changed elsewhere: rows read again (once shown if hidden)"""
        self.backend.refresh()
