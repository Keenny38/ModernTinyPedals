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
Spectate page: spectate mode, spectated driver, drivers of the session

Qt Quick page (qml/Spectate.qml), state & actions in quick/spectate_backend.py. The QML page is
created when first shown, drivers are read only while it is shown.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Slot
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .quick.spectate_backend import SpectateBackend


class SpectateList(QWidget):
    """Spectate page"""

    def __init__(self, parent):
        super().__init__(parent)
        self.backend = SpectateBackend(self)
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
                view = create_quick_view(self, "Spectate.qml", {"backend": self.backend}, samples=0)
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
        self.backend.set_active(False)  # nothing read while another page (or the race) is shown
        super().hideEvent(event)

    def closeEvent(self, event):
        super().closeEvent(event)
        if self.view is not None:  # QML gone before the backend it binds to
            view, self.view = self.view, None
            view.setSource(QUrl())
            view.deleteLater()

    @Slot(bool)  # type: ignore[operator]
    def refresh(self, *_):
        """Spectate mode or driver changed elsewhere (hotkey, API menu): shown state only, nothing saved"""
        self.backend.refresh()
