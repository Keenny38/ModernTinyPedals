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
Layout guide: visual grid & alignment lines while dragging overlay widget
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

COLOR_GRID = QColor(255, 255, 255, 28)
COLOR_GUIDE = QColor(56, 169, 245, 230)
COLOR_OUTLINE = QColor(56, 169, 245, 160)
ALIGN_TOLERANCE = 1  # pixel


def alignment_lines(target: QRect, others: list[QRect], screen: QRect) -> tuple[set[int], set[int]]:
    """Find aligned vertical (x) & horizontal (y) lines between target and other rects

    Checks edges and centers of target against edges and centers of other rects & screen.
    """
    def x_points(rect: QRect) -> tuple[float, ...]:
        return rect.left(), rect.left() + rect.width(), rect.left() + rect.width() / 2

    def y_points(rect: QRect) -> tuple[float, ...]:
        return rect.top(), rect.top() + rect.height(), rect.top() + rect.height() / 2

    ref_x = {screen.left() + screen.width() / 2}
    ref_y = {screen.top() + screen.height() / 2}
    for rect in others:
        ref_x.update(x_points(rect))
        ref_y.update(y_points(rect))
    lines_x = {round(x) for x in x_points(target) for ref in ref_x if abs(x - ref) <= ALIGN_TOLERANCE}
    lines_y = {round(y) for y in y_points(target) for ref in ref_y if abs(y - ref) <= ALIGN_TOLERANCE}
    return lines_x, lines_y


class LayoutGuide(QWidget):
    """Transparent full screen guide window, shown only while dragging"""

    def __init__(self):
        super().__init__()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._target = QRect()
        self._others: list[QRect] = []
        self._grid_size = 0

    def begin(self, widget: QWidget, grid_size: int = 0):
        """Show guide on widget screen"""
        screen = widget.screen()
        self.setGeometry(screen.geometry())
        self._grid_size = grid_size if grid_size >= 4 else 0
        self._others = [
            other.geometry()
            for other in QApplication.topLevelWidgets()
            if hasattr(other, "widget_name") and other is not widget and other.isVisible()
            and other.screen() is screen
        ]
        self.track(widget)
        self.show()
        widget.raise_()  # keep dragged widget above guide

    def track(self, widget: QWidget):
        """Update dragged widget position"""
        self._target = widget.geometry()
        self.update()

    def end(self):
        """Hide guide"""
        self.hide()
        self._others = []

    def paintEvent(self, event):
        """Draw grid, alignment lines, dragged widget outline"""
        painter = QPainter(self)
        origin = self.geometry().topLeft()
        width = self.width()
        height = self.height()
        # Grid
        if self._grid_size:
            painter.setPen(QPen(COLOR_GRID, 1))
            for x in range(-origin.x() % self._grid_size, width, self._grid_size):
                painter.drawLine(x, 0, x, height)
            for y in range(-origin.y() % self._grid_size, height, self._grid_size):
                painter.drawLine(0, y, width, y)
        # Alignment lines
        lines_x, lines_y = alignment_lines(self._target, self._others, self.geometry())
        pen_guide = QPen(COLOR_GUIDE, 1, Qt.PenStyle.DashLine)
        painter.setPen(pen_guide)
        for x in lines_x:
            painter.drawLine(x - origin.x(), 0, x - origin.x(), height)
        for y in lines_y:
            painter.drawLine(0, y - origin.y(), width, y - origin.y())
        # Dragged widget outline
        painter.setPen(QPen(COLOR_OUTLINE, 1))
        painter.drawRect(self._target.translated(-origin.x(), -origin.y()).adjusted(-1, -1, 0, 0))


_guide: LayoutGuide | None = None


def layout_guide() -> LayoutGuide:
    """Shared layout guide window (created on first use)"""
    global _guide
    if _guide is None:
        _guide = LayoutGuide()
    return _guide
