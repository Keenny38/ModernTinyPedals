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
Layout guide: visual grid, alignment lines & position while dragging overlay widget

Full screen transparent window: only the parts that change (dragged outline, lines, position label)
are drawn again on each mouse move, and the window is released once the drag ends (its screen size
image is not kept in memory).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget

COLOR_GRID = QColor(255, 255, 255, 28)
COLOR_GUIDE = QColor(56, 169, 245, 230)
COLOR_OUTLINE = QColor(56, 169, 245, 160)
COLOR_LABEL = QColor(20, 24, 30, 225)
COLOR_LABEL_TEXT = QColor(240, 244, 248)
ALIGN_TOLERANCE = 1  # pixel
LABEL_GAP = 6  # pixels between dragged widget & position label


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
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._target = QRect()
        self._others: list[QRect] = []
        self._lines: tuple[set[int], set[int]] = (set(), set())
        self._grid_size = 0
        self._grid_brush: QBrush | None = None
        self._label = ""
        self._label_rect = QRect()
        self._label_font = QFont(self.font())
        self._label_font.setPixelSize(12)
        self._label_font.setBold(True)
        self._label_metrics = QFontMetrics(self._label_font)

    def begin(self, widget: QWidget, grid_size: int = 0):
        """Show guide on widget screen"""
        screen = widget.screen()
        self.setGeometry(screen.geometry())
        self._grid_size = grid_size if grid_size >= 4 else 0
        self._grid_brush = grid_brush(self._grid_size) if self._grid_size else None
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
        """Update dragged widget position, only changed parts drawn again"""
        old_parts = self.changing_parts()
        self._target = widget.geometry()
        self._lines = alignment_lines(self._target, self._others, self.geometry())
        self._label = f"X {self._target.x()}   Y {self._target.y()}"
        self._label_rect = self.label_geometry()
        if self.isVisible():
            self.update(old_parts.united(self.changing_parts()))

    def changing_parts(self) -> QRegion:
        """Area drawn for current position: dragged outline, alignment lines, label (local coordinates)"""
        if self._target.isNull():
            return QRegion()
        origin = self.geometry().topLeft()
        region = QRegion(self._target.translated(-origin).adjusted(-2, -2, 2, 2))
        region += self._label_rect.adjusted(-1, -1, 1, 1)
        lines_x, lines_y = self._lines
        for x in lines_x:
            region += QRect(x - origin.x() - 1, 0, 3, self.height())
        for y in lines_y:
            region += QRect(0, y - origin.y() - 1, self.width(), 3)
        return region

    def label_geometry(self) -> QRect:
        """Position label below dragged widget (above it at bottom of screen), local coordinates"""
        origin = self.geometry().topLeft()
        target = self._target.translated(-origin)
        width = self._label_metrics.horizontalAdvance(self._label) + 16
        height = self._label_metrics.height() + 8
        top = target.bottom() + 1 + LABEL_GAP
        if top + height > self.height():
            top = target.top() - LABEL_GAP - height
        left = min(max(target.left(), 0), max(self.width() - width, 0))
        return QRect(left, max(top, 0), width, height)

    def end(self):
        """Hide guide"""
        self.hide()
        self._others = []
        self._target = QRect()

    def paintEvent(self, event):
        """Draw grid, alignment lines, dragged widget outline, position (clipped to changed parts)"""
        painter = QPainter(self)
        origin = self.geometry().topLeft()
        width = self.width()
        height = self.height()
        # Grid: tiled pattern, lines on desktop coordinates multiple of grid size
        if self._grid_brush is not None:
            size = self._grid_size
            painter.setBrushOrigin(QPoint(-origin.x() % size, -origin.y() % size))
            painter.fillRect(event.rect(), self._grid_brush)
        # Alignment lines
        lines_x, lines_y = self._lines
        painter.setPen(QPen(COLOR_GUIDE, 1, Qt.PenStyle.DashLine))
        for x in lines_x:
            painter.drawLine(x - origin.x(), 0, x - origin.x(), height)
        for y in lines_y:
            painter.drawLine(0, y - origin.y(), width, y - origin.y())
        if self._target.isNull():
            return
        # Dragged widget outline
        painter.setPen(QPen(COLOR_OUTLINE, 1))
        painter.drawRect(self._target.translated(-origin.x(), -origin.y()).adjusted(-1, -1, 0, 0))
        # Position label
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(COLOR_LABEL)
        painter.drawRoundedRect(self._label_rect, 5, 5)
        painter.setFont(self._label_font)
        painter.setPen(COLOR_LABEL_TEXT)
        painter.drawText(self._label_rect, Qt.AlignmentFlag.AlignCenter, self._label)


def grid_brush(size: int) -> QBrush:
    """Tile of grid: one vertical & one horizontal line"""
    tile = QPixmap(size, size)
    tile.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tile)
    painter.setPen(QPen(COLOR_GRID, 1))
    painter.drawLine(0, 0, 0, size - 1)
    painter.drawLine(1, 0, size - 1, 0)
    painter.end()
    return QBrush(tile)


_guide: LayoutGuide | None = None


def layout_guide() -> LayoutGuide:
    """Shared layout guide window (created on first use)"""
    global _guide
    if _guide is None:
        _guide = LayoutGuide()
    return _guide


def end_layout_guide():
    """Hide & release layout guide window, if shown"""
    global _guide
    guide, _guide = _guide, None
    if guide is not None:
        guide.end()
        guide.deleteLater()
