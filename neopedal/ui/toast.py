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
Toast: short non-blocking message at the bottom of a window, fades out by itself

Shown in the page's TpToast when the shown page of the window is a QML page with a TpDialogHost (quick/dialogs),
else as a widget toast. Both: same durations (toast_duration, TpToast.shownTime), kept while hovered, level told by
icon or border color, announced to screen readers.
"""

import sys
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from . import safe_markup
from ._common import FocusRingButton, UIScaler

FADE_MS = 180
# Durations of TpToast.shownTime (keep both the same): long enough to read, errors longer, a button (undo) longer
MIN_DISPLAY_MS = 3000
MS_PER_CHARACTER = 55
READ_START_MS = 1500
ERROR_FACTOR = 1.5
ACTION_EXTRA_MS = 3000
ACTION_RECHECK_MS = 1000  # kept while hovered or button focused, checked again then
LEVELS = ("info", "success", "warning", "error")


def toast_duration(text_length: int, error: bool = False, action: bool = False) -> int:
    """Time (ms) a toast stays: same as TpToast.shownTime"""
    shown = max(MIN_DISPLAY_MS, text_length * MS_PER_CHARACTER + READ_START_MS) * (ERROR_FACTOR if error else 1)
    return round(shown + (ACTION_EXTRA_MS if action else 0))


def announce(widget: QWidget, text: str):
    """Screen readers read text now (an alert), as TpToast (Accessible.AlertMessage)"""
    from PySide6.QtGui import QAccessible, QAccessibleEvent

    if not QAccessible.isActive():
        return
    try:
        from PySide6.QtGui import QAccessibleAnnouncementEvent  # Qt 6.8

        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(widget, text))
    except ImportError:
        QAccessible.updateAccessibility(QAccessibleEvent(widget, QAccessible.Event.Alert))


def plain_text(markup: str) -> str:
    """Text of a toast without markup (screen readers, duration)"""
    from PySide6.QtGui import QTextDocumentFragment

    return QTextDocumentFragment.fromHtml(markup).toPlainText()


def _setup(toast: QWidget, level: str, duration: int) -> QTimer:
    """Look & hide timer of a toast (stopped while hovered, see enterEvent / leaveEvent), started"""
    toast.setObjectName("toast")
    toast.setProperty("level", level if level in LEVELS else "info")  # border color (style sheet)
    toast.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    toast.setCursor(Qt.CursorShape.PointingHandCursor)  # click: hidden
    timer = QTimer(toast)
    timer.setSingleShot(True)
    timer.timeout.connect(toast.hide_if_idle)  # type: ignore[attr-defined]
    timer.start(duration)
    return timer


class Toast(QLabel):
    """Floating message label, child of target window: hidden by a click, kept while hovered"""

    def __init__(self, window: QWidget, text: str, duration: int = 0, level: str = "info"):
        super().__init__(text, window)
        self._window = window
        self._hiding = False
        plain = plain_text(self.text())
        self._duration = duration or toast_duration(len(plain), level == "error")
        self._timer = _setup(self, level, self._duration)
        self.setAccessibleName(plain)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
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
        announce(self, plain)

    def place(self):
        """Bottom center of window"""
        window = self._window
        margin = UIScaler.pixel(16)
        self.move((window.width() - self.width()) // 2, window.height() - self.height() - margin * 3)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.place()
        return False

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self._hiding:
            self._timer.stop()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self._hiding:
            self._timer.start(self._duration)

    def mousePressEvent(self, event):
        self.hide_toast()

    def fade_to(self, value: float):
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(value)
        self._fade.start()

    def is_busy(self) -> bool:
        """Hovered: kept shown"""
        return self.underMouse()

    def hide_if_idle(self):
        if self.is_busy():
            self._timer.start(ACTION_RECHECK_MS)
            return
        self.hide_toast()

    def hide_toast(self):
        if self._hiding:
            return
        self._hiding = True
        self._timer.stop()
        self.fade_to(0.0)
        self._fade.finished.connect(self.close)


class ActionToast(QFrame):
    """Floating message with a button (undo...), child of target window

    Stays while hovered or while its button has keyboard focus, then fades out.
    Action runs once, toast then hides.
    """

    def __init__(self, window: QWidget, text: str, action_text: str, action: Callable[[], object], duration: int = 0,
                 level: str = "info"):
        super().__init__(window)
        self._window = window
        self._action: Callable[[], object] | None = action
        self._hiding = False
        plain = plain_text(text)
        self._duration = duration or toast_duration(len(plain), level == "error", action=True)
        self._timer = _setup(self, level, self._duration)
        self.setAccessibleName(plain)
        self.setAccessibleDescription(action_text)
        self.label = QLabel(text, self)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.button = FocusRingButton(action_text, self)
        self.button.clicked.connect(self.run_action)
        self.button.setCursor(Qt.CursorShape.ArrowCursor)
        layout = QHBoxLayout(self)
        padding = UIScaler.pixel(10)
        layout.setContentsMargins(padding, padding // 2, padding // 2, padding // 2)
        layout.setSpacing(padding)
        layout.addWidget(self.label, stretch=1)
        layout.addWidget(self.button)
        max_width = max(UIScaler.size(18), round(window.width() * 0.85))
        self.setMaximumWidth(max_width)
        # Short message on one line, long one wrapped
        self.label.setMinimumWidth(min(
            self.label.sizeHint().width(), max_width - self.button.sizeHint().width() - padding * 3))
        self.label.setWordWrap(True)

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
        announce(self, plain)

    def place(self):
        """Bottom center of window"""
        window = self._window
        margin = UIScaler.pixel(16)
        self.move((window.width() - self.width()) // 2, window.height() - self.height() - margin * 3)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.place()
        return False

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self._hiding:
            self._timer.stop()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self._hiding and not self.button.hasFocus():
            self._timer.start(self._duration)

    def mousePressEvent(self, event):
        self.hide_toast()

    def fade_to(self, value: float):
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(value)
        self._fade.start()

    def is_busy(self) -> bool:
        """Hovered or button focused: kept shown"""
        return self.underMouse() or self.button.hasFocus()

    def hide_if_idle(self):
        if self.is_busy():
            self._timer.start(ACTION_RECHECK_MS)
            return
        self.hide_toast()

    def hide_toast(self):
        if self._hiding:
            return
        self._hiding = True
        self._timer.stop()
        self.fade_to(0.0)
        self._fade.finished.connect(self.close)

    def run_action(self):
        """Run action once, then hide"""
        action, self._action = self._action, None
        self.button.setEnabled(False)
        self.hide_toast()
        if action is not None:
            action()


def show_toast(
    widget: QWidget | None, text: str, duration: int = 0,
    action_text: str = "", action: Callable[[], object] | None = None, level: str = "",
) -> QWidget | None:
    """Show toast in window of widget, text can contain <b>, <i>, <br> & <code> (see safe_markup: names & errors
    in it are never read as markup)

    Shown in the page's TpToast when the shown page of the window is a QML page with a TpDialogHost (None
    returned), else a widget toast (returned).

    Args:
        duration: ms shown, 0: from text length (toast_duration).
        action_text: button text (translated), toast with button if set with action.
        action: called when button is clicked (undo...).
        level: "info", "success", "warning" or "error" (shown longer): border color & icon. Default: an accent
            border (widget toast), a check (page toast).
    """
    if widget is None:
        return None
    # QML pages exist once quick.dialogs is loaded (create_quick_view): never loaded here for widget toasts only
    dialogs = sys.modules.get(f"{__package__}.quick.dialogs")
    if dialogs is not None and dialogs.page_toast(
            widget, text, level or "success", duration, action_text, action):
        return None
    text = safe_markup(text)
    window = widget.window()
    # One toast at a time: the new message replaces the shown one (same place, never stacked over it)
    shown: list[Toast | ActionToast] = [*window.findChildren(Toast), *window.findChildren(ActionToast)]
    for previous in shown:
        if previous.parent() is window:
            previous.hide_toast()
    if action_text and action is not None:
        return ActionToast(window, text, action_text, action, duration, level or "info")
    return Toast(window, text, duration, level or "info")
