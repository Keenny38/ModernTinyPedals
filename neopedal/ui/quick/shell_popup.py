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
Popup of the main window showing a Qt Quick page (command palette, notification center, keyboard shortcuts):
frameless, closed by a click outside, Esc or the page itself, deleted once closed (its engine freed)
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from . import create_quick_view

REOPEN_GUARD = 0.3  # seconds: click on the button that opened it closes it (no reopening at once)


class ShellBackend(QObject):
    """Base of shell popup backends: closeRequested asks the popup to close (after the QML handler is done)"""

    closeRequested = Signal()

    def popup_closed(self):
        """Popup closed (by click outside, Esc or close request): override to save state"""


class ShellPopup(QWidget):
    """Popup window hosting qml_name with backend (context "backend"), one per kind at a time

    Args:
        window: main window (popup owner, placed over it).
        backend: page state, made a child of the popup (deleted with it).
        size: popup size.
    """

    _open: dict[str, ShellPopup] = {}  # kind: popup shown
    _closed_at: dict[str, float] = {}  # kind: monotonic time of last close

    def __init__(self, window: QWidget, kind: str, qml_name: str, backend: ShellBackend, size: QSize):
        super().__init__(window, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.kind = kind
        self.backend = backend
        backend.setParent(self)
        # Close asked by the page: once its handler returned (closing under a QML handler aborts Qt)
        backend.closeRequested.connect(self.close, Qt.ConnectionType.QueuedConnection)
        self.view = create_quick_view(self, qml_name, {"backend": backend})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setFocusProxy(self.view)
        self.resize(size)

    @classmethod
    def shown(cls, kind: str) -> ShellPopup | None:
        return cls._open.get(kind)

    @classmethod
    def just_closed(cls, kind: str) -> bool:
        """Closed a moment ago: the click on its button closed it, not reopened"""
        return time.monotonic() - cls._closed_at.get(kind, -REOPEN_GUARD) < REOPEN_GUARD

    def popup(self, position: QPoint):
        """Show at position (top left), kept inside the screen of the main window"""
        previous = self._open.get(self.kind)
        if previous is not None and previous is not self:
            previous.close()
        self._open[self.kind] = self
        screen = (self.parentWidget() or self).screen()
        area: QRect = screen.availableGeometry() if screen is not None else QRect(position, self.size())
        x = max(area.left(), min(position.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(position.y(), area.bottom() - self.height() + 1))
        self.move(x, y)
        self.show()
        self.activateWindow()
        self.view.setFocus(Qt.FocusReason.PopupFocusReason)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:  # not taken by the page (a field clearing its text takes it)
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._open.get(self.kind) is self:
            del self._open[self.kind]
        self._closed_at[self.kind] = time.monotonic()
        self.backend.popup_closed()
        self.view.setSource(QUrl())  # QML unloaded before its backend is deleted
        super().closeEvent(event)
        window = self.parentWidget()
        if window is not None and window.isVisible():
            QTimer.singleShot(0, window, window.activateWindow)  # keyboard back to the main window


def centered_top(window: QWidget, size: QSize, top_ratio: float = 0.12) -> QPoint:
    """Position of a popup of size: centered over window, a bit below its top"""
    frame = window.geometry()
    return QPoint(frame.center().x() - size.width() // 2, frame.top() + round(frame.height() * top_ratio))


def popup_size(window: QWidget, width_em: float, height_em: float) -> QSize:
    """Popup size in em of the app font, at most 90% of the window"""
    em = QFontMetrics(QApplication.font()).height()
    frame = window.geometry()
    return QSize(min(round(width_em * em), round(frame.width() * 0.9)),
                 min(round(height_em * em), round(frame.height() * 0.9)))
