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
Visual edit mode of unlocked overlay: outline & name of each widget, corner handle to resize it

Resizing scales pixel size options of widget (font size, bar size...), see _style.SCALED_OPTION.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ._style import SCALED_OPTION

EDIT_COLOR = QColor("#2F8CFF")
HANDLE_SIZE = 14
SCALE_RANGE = (0.3, 4.0)


def scale_widget_setting(setting: dict, factor: float) -> dict:
    """Pixel size options of widget setting multiplied by factor, returns changed options"""
    factor = min(max(factor, SCALE_RANGE[0]), SCALE_RANGE[1])
    changed = {}
    for key, value in setting.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not SCALED_OPTION.search(key):
            continue
        new_value = max(round(value * factor), 1) if isinstance(value, int) else round(value * factor, 3)
        if new_value != value:
            changed[key] = new_value
    setting.update(changed)
    return changed


def drag_factor(size: tuple[int, int], offset: QPoint) -> float:
    """Scale factor from handle drag offset, aspect ratio kept (largest change wins)"""
    width, height = max(size[0], 1), max(size[1], 1)
    ratio_x = (width + offset.x()) / width
    ratio_y = (height + offset.y()) / height
    factor = ratio_x if abs(ratio_x - 1) >= abs(ratio_y - 1) else ratio_y
    return min(max(factor, SCALE_RANGE[0]), SCALE_RANGE[1])


class EditOutline(QWidget):
    """Dashed outline & widget name, drawn over widget, ignores mouse"""

    def __init__(self, parent: QWidget, title: str):
        super().__init__(parent)
        self.title = title
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pen = QPen(EDIT_COLOR, 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(rect)
        if self.height() < 30:  # name would hide content of thin widget, shown as tooltip instead
            return
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        text_width = painter.fontMetrics().horizontalAdvance(self.title) + 8
        label = QRect(0, 0, min(text_width, self.width()), 15)
        painter.fillRect(label, EDIT_COLOR)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(label, Qt.AlignmentFlag.AlignCenter, self.title)


class ResizeGhost(QWidget):
    """Top level preview of new widget size while dragging handle"""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.factor = 1.0

    def paintEvent(self, event):
        painter = QPainter(self)
        fill = QColor(EDIT_COLOR)
        fill.setAlphaF(0.15)
        painter.fillRect(self.rect(), fill)
        painter.setPen(QPen(EDIT_COLOR, 2))
        painter.drawRect(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        font = QFont(self.font())
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self.factor:.0%}")


class ResizeHandle(QWidget):
    """Bottom right corner handle, drag to scale widget"""

    def __init__(self, parent: QWidget, on_resized: Callable[[float], None]):
        super().__init__(parent)
        self.target = parent
        self.on_resized = on_resized
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setFixedSize(HANDLE_SIZE, HANDLE_SIZE)
        self.setToolTip(f"{parent.windowTitle()}: drag to resize")
        self._press: QPoint | None = None
        self._ghost: ResizeGhost | None = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(EDIT_COLOR)
        size = self.width()
        painter.drawPolygon([QPoint(size, 0), QPoint(size, size), QPoint(0, size)])

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._ghost = ResizeGhost()
            self.update_ghost(QPoint())
            self._ghost.show()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press is not None:
            self.update_ghost(event.globalPosition().toPoint() - self._press)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._press is None:
            return
        factor = drag_factor(self.parent_size(), event.globalPosition().toPoint() - self._press)
        self._press = None
        if self._ghost is not None:
            self._ghost.close()
            self._ghost.deleteLater()
            self._ghost = None
        event.accept()
        if abs(factor - 1) >= 0.02:
            self.on_resized(factor)

    def parent_size(self) -> tuple[int, int]:
        return self.target.width(), self.target.height()

    def update_ghost(self, offset: QPoint):
        if self._ghost is None:
            return
        parent = self.target
        factor = drag_factor(self.parent_size(), offset)
        self._ghost.factor = factor
        top_left = parent.mapToGlobal(QPoint(0, 0))
        self._ghost.setGeometry(
            top_left.x(), top_left.y(), max(round(parent.width() * factor), 20), max(round(parent.height() * factor), 20))
        self._ghost.update()


class EditFrame(QObject):
    """Outline & resize handle attached to widget, follows widget size"""

    def __init__(self, widget: QWidget, title: str, on_resized: Callable[[float], None]):
        super().__init__(widget)
        self.widget = widget
        self.outline = EditOutline(widget, title)
        self.handle = ResizeHandle(widget, on_resized)
        widget.installEventFilter(self)
        self.place()

    def eventFilter(self, watched, event):
        widget = getattr(self, "widget", None)  # attribute gone while widget is being deleted
        if widget is not None and watched is widget and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.place()
        return False

    def place(self):
        widget = self.widget
        self.outline.setGeometry(widget.rect())
        self.handle.move(widget.width() - HANDLE_SIZE, widget.height() - HANDLE_SIZE)
        self.outline.raise_()
        self.handle.raise_()

    def set_visible(self, visible: bool):
        self.outline.setVisible(visible)
        self.handle.setVisible(visible)
        if visible:
            self.place()
