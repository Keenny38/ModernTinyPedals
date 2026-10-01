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
Toast: short non-blocking message at the bottom of a window, fades out by itself
"""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from ._common import UIScaler

FADE_MS = 180
MIN_DISPLAY_MS = 2500
MS_PER_CHARACTER = 45  # longer messages stay longer


class Toast(QLabel):
    """Floating message label, child of target window"""

    def __init__(self, window: QWidget, text: str, duration: int = 0):
        super().__init__(text, window)
        self._window = window
        self.setObjectName("toast")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMaximumWidth(max(UIScaler.size(14), round(window.width() * 0.85)))
        padding = UIScaler.pixel(10)
        self.setContentsMargins(padding, padding // 2, padding, padding // 2)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        window.installEventFilter(self)
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self.fade_to(1.0)
        plain_length = len(self.text())
        QTimer.singleShot(duration or max(MIN_DISPLAY_MS, plain_length * MS_PER_CHARACTER), self.hide_toast)

    def place(self):
        """Bottom center of window"""
        window = self._window
        margin = UIScaler.pixel(16)
        self.move((window.width() - self.width()) // 2, window.height() - self.height() - margin * 3)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.place()
        return False

    def fade_to(self, value: float):
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(value)
        self._fade.start()

    def hide_toast(self):
        self.fade_to(0.0)
        self._fade.finished.connect(self.close)


def show_toast(widget: QWidget | None, text: str, duration: int = 0) -> Toast | None:
    """Show toast in window of widget, text can contain html"""
    if widget is None:
        return None
    return Toast(widget.window(), text, duration)
