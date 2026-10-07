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
Layout editor: place & align overlay widgets on a game screenshot
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr, trm
from ..i18n.options import module_label
from ..module_control import wctrl
from ..setting import cfg
from ..widget._base import store_screen_layout
from ..widget._layout_guide import COLOR_GUIDE, alignment_lines
from ._common import BaseDialog, CompactButton, UIScaler, singleton_dialog, translate_filter

SNAP_DISTANCE = 8  # screen pixel
COLOR_BOX = QColor(255, 255, 255, 50)
COLOR_BOX_EDGE = QColor(255, 255, 255, 170)
COLOR_SELECTED = QColor(56, 169, 245, 90)
COLOR_BACKGROUND = QColor(24, 24, 24)


def virtual_screen() -> QRect:
    """Bounding rect of all screens, in desktop coordinates"""
    rect = QRect()
    for screen in QGuiApplication.screens():
        rect = rect.united(screen.geometry())
    return rect if rect.isValid() else QRect(0, 0, 1920, 1080)


def screen_geometries() -> list[QRect]:
    """Geometry of each screen, in desktop coordinates"""
    return [screen.geometry() for screen in QGuiApplication.screens()] or [virtual_screen()]


def screen_for_image(size: QSize, screens: Sequence[tuple[QRect, float]], fallback: QRect) -> QRect:
    """Geometry of the screen a screenshot of this pixel size was taken on, else fallback

    Args:
        size: screenshot size in pixels.
        screens: (geometry, device pixel ratio) of each screen.
        fallback: geometry used when no screen has the screenshot size.
    """
    for geometry, ratio in screens:
        if size in (geometry.size(), (geometry.size().toSizeF() * ratio).toSize()):
            return QRect(geometry)
    return QRect(fallback)


def snap_position(
    target: QRect, others: list[QRect], screen: QRect | Sequence[QRect], distance: int = SNAP_DISTANCE
) -> QPoint:
    """Snap target top-left so its edges or center line up with other rects or screen edges & center

    Each axis snaps to the closest reference within distance, else keeps its position.
    Screen can be a single rect or the geometry of each screen (multi-monitor).
    """
    def best_offset(points: tuple[float, ...], refs: set[float]) -> float:
        best = 0.0
        best_gap = distance + 1.0
        for point in points:
            for ref in refs:
                gap = abs(ref - point)
                if gap < best_gap:
                    best_gap = gap
                    best = ref - point
        return best if best_gap <= distance else 0.0

    ref_x: set[float] = set()
    ref_y: set[float] = set()
    for rect in [screen] if isinstance(screen, QRect) else screen:
        ref_x.update((rect.left(), rect.left() + rect.width(), rect.center().x() + 0.5))
        ref_y.update((rect.top(), rect.top() + rect.height(), rect.center().y() + 0.5))
    for rect in others:
        ref_x.update((rect.left(), rect.left() + rect.width(), rect.left() + rect.width() / 2))
        ref_y.update((rect.top(), rect.top() + rect.height(), rect.top() + rect.height() / 2))
    left, top, width, height = target.left(), target.top(), target.width(), target.height()
    offset_x = best_offset((left, left + width, left + width / 2), ref_x)
    offset_y = best_offset((top, top + height, top + height / 2), ref_y)
    return QPoint(round(left + offset_x), round(top + offset_y))


class LayoutCanvas(QWidget):
    """Scaled view of desktop with draggable widget boxes"""

    selectionChanged = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(UIScaler.size(40), UIScaler.size(22.5))
        self.screen_rect = virtual_screen()  # area shown
        self.screens = screen_geometries()  # snapping & guides per screen
        self.background = QPixmap()
        self.background_rect = QRect(self.screen_rect)  # desktop area covered by background
        self.boxes: dict[str, QRect] = {}
        self.selected = ""
        self.snap = True
        self._drag_offset = QPoint()
        self._guides: tuple[set[int], set[int]] = (set(), set())

    # Coordinates
    def view_rect(self) -> QRectF:
        """Area of widget showing the desktop, keeping aspect ratio"""
        screen = self.screen_rect
        scale = min(self.width() / screen.width(), self.height() / screen.height())
        width, height = screen.width() * scale, screen.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def scale(self) -> float:
        return self.view_rect().width() / self.screen_rect.width()

    def to_view(self, rect: QRect) -> QRectF:
        view, scale = self.view_rect(), self.scale()
        return QRectF(
            view.left() + (rect.left() - self.screen_rect.left()) * scale,
            view.top() + (rect.top() - self.screen_rect.top()) * scale,
            rect.width() * scale,
            rect.height() * scale,
        )

    def to_screen(self, pos: QPointF) -> QPoint:
        view, scale = self.view_rect(), self.scale()
        return QPoint(
            round((pos.x() - view.left()) / scale + self.screen_rect.left()),
            round((pos.y() - view.top()) / scale + self.screen_rect.top()),
        )

    def set_background(self, pixmap: QPixmap, screen: QRect):
        """Show screenshot over one screen, view limited to that screen"""
        self.screen_rect = QRect(screen)
        self.background_rect = QRect(screen)
        self.background = pixmap
        self.update()

    # Editing
    def box_at(self, pos: QPoint) -> str:
        for name in reversed(tuple(self.boxes)):  # topmost (last drawn) first
            if self.boxes[name].contains(pos):
                return name
        return ""

    def select(self, name: str):
        self.selected = name
        self.selectionChanged.emit(name)
        self.update()

    def move_selected(self, top_left: QPoint, snap: bool):
        rect = QRect(self.boxes[self.selected])
        rect.moveTopLeft(top_left)
        others = [box for name, box in self.boxes.items() if name != self.selected]
        if snap:
            rect.moveTopLeft(snap_position(rect, others, self.screens))
        self.boxes[self.selected] = rect
        lines_x: set[int] = set()
        lines_y: set[int] = set()
        for screen in self.screens:
            screen_x, screen_y = alignment_lines(rect, others, screen)
            lines_x |= screen_x
            lines_y |= screen_y
        self._guides = (lines_x, lines_y)
        self.selectionChanged.emit(self.selected)
        self.update()

    def mousePressEvent(self, event):
        pos = self.to_screen(event.position())
        self.select(self.box_at(pos))
        if self.selected:
            self._drag_offset = pos - self.boxes[self.selected].topLeft()

    def mouseMoveEvent(self, event):
        if self.selected and event.buttons() & Qt.MouseButton.LeftButton:
            snap = self.snap and not event.modifiers() & Qt.KeyboardModifier.AltModifier
            self.move_selected(self.to_screen(event.position()) - self._drag_offset, snap)

    def mouseReleaseEvent(self, event):
        self._guides = (set(), set())
        self.update()

    def keyPressEvent(self, event):
        steps = {
            Qt.Key.Key_Left: QPoint(-1, 0),
            Qt.Key.Key_Right: QPoint(1, 0),
            Qt.Key.Key_Up: QPoint(0, -1),
            Qt.Key.Key_Down: QPoint(0, 1),
        }
        step = steps.get(Qt.Key(event.key()))
        if not self.selected or step is None:
            super().keyPressEvent(event)
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step *= 10
        self.move_selected(self.boxes[self.selected].topLeft() + step, snap=False)

    # Drawing
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        view = self.view_rect()
        painter.fillRect(self.rect(), self.palette().window())
        painter.fillRect(view, COLOR_BACKGROUND)
        if not self.background.isNull():
            painter.drawPixmap(self.to_view(self.background_rect), self.background, QRectF(self.background.rect()))
        # Screen edges
        painter.setPen(QPen(COLOR_BOX_EDGE, 1, Qt.PenStyle.DotLine))
        for screen in QGuiApplication.screens():
            painter.drawRect(self.to_view(screen.geometry()))
        # Widget boxes
        font = painter.font()
        font.setPointSizeF(max(font.pointSizeF() * 0.8, 6))
        painter.setFont(font)
        for name, rect in self.boxes.items():
            box = self.to_view(rect)
            selected = name == self.selected
            painter.fillRect(box, COLOR_SELECTED if selected else COLOR_BOX)
            painter.setPen(QPen(COLOR_GUIDE if selected else COLOR_BOX_EDGE, 2 if selected else 1))
            painter.drawRect(box)
            painter.drawText(box.adjusted(3, 1, -3, -1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             module_label(name))
        # Alignment guides
        painter.setPen(QPen(COLOR_GUIDE, 1, Qt.PenStyle.DashLine))
        lines_x, lines_y = self._guides
        for x in lines_x:
            left = self.to_view(QRect(x, 0, 1, 1)).left()
            painter.drawLine(QPointF(left, view.top()), QPointF(left, view.bottom()))
        for y in lines_y:
            top = self.to_view(QRect(0, y, 1, 1)).top()
            painter.drawLine(QPointF(view.left(), top), QPointF(view.right(), top))


@singleton_dialog("layout_editor")
class LayoutEditor(BaseDialog):
    """Place overlay widgets on a screenshot, apply positions to preset"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Layout Editor"))
        self.canvas = LayoutCanvas(self)
        self.canvas.selectionChanged.connect(self.show_selection)
        self.label_info = QLabel(self)

        button_load = CompactButton(tr("Load Screenshot..."))
        button_load.clicked.connect(self.load_screenshot)
        button_capture = CompactButton(tr("Capture Screen"))
        button_capture.clicked.connect(self.capture_screen)
        self.button_snap = CompactButton(tr("Snap"))
        self.button_snap.setCheckable(True)
        self.button_snap.setChecked(True)
        self.button_snap.toggled.connect(self.toggle_snap)
        layout_top = QHBoxLayout()
        layout_top.addWidget(button_load)
        layout_top.addWidget(button_capture)
        layout_top.addWidget(self.button_snap)
        layout_top.addStretch(1)

        button_reset = CompactButton(tr("Reset"))
        button_reset.clicked.connect(self.load_widgets)
        button_apply = CompactButton(tr("Apply"))
        button_apply.clicked.connect(self.apply)
        button_save = CompactButton(tr("Save"))
        button_save.clicked.connect(self.save)
        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.close)
        layout_button = QHBoxLayout()
        layout_button.addWidget(self.label_info, stretch=1)
        layout_button.addWidget(button_reset)
        layout_button.addWidget(button_apply)
        layout_button.addWidget(button_save)
        layout_button.addWidget(button_close)

        layout_main = QVBoxLayout(self)
        layout_main.addLayout(layout_top)
        layout_main.addWidget(QLabel(tr(
            "Drag widgets to move, arrow keys to nudge (Shift: 10 px), hold Alt to move without snapping."
        )))
        layout_main.addWidget(self.canvas, stretch=1)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.resize(UIScaler.size(64), UIScaler.size(44))
        self.load_widgets()

    def load_widgets(self):
        """Read positions & sizes of running widgets"""
        self.canvas.boxes = {
            name: QRect(widget.geometry())
            for name, widget in wctrl.active_modules.items()
            if hasattr(widget, "geometry")
        }
        self.canvas.select("")
        if not self.canvas.boxes:
            self.label_info.setText(tr("No widget enabled."))

    def show_selection(self, name: str):
        if not name:
            self.label_info.setText(trm(f"{len(self.canvas.boxes)} widgets"))
            return
        rect = self.canvas.boxes[name]
        self.label_info.setText(f"{module_label(name)}: x {rect.x()}, y {rect.y()}  ({rect.width()} x {rect.height()})")

    def toggle_snap(self, checked: bool):
        self.canvas.snap = checked

    def load_screenshot(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, tr("Load Screenshot..."), "", translate_filter("Images (*.png *.jpg *.jpeg *.bmp)")
        )
        if filename:
            pixmap = QPixmap(filename)
            if pixmap.isNull():
                self.label_info.setText(tr("Unable to load image."))
            else:
                current = self.screen() or QGuiApplication.primaryScreen()
                fallback = current.geometry() if current is not None else virtual_screen()
                screens = [(screen.geometry(), screen.devicePixelRatio()) for screen in QGuiApplication.screens()]
                self.canvas.set_background(pixmap, screen_for_image(pixmap.size(), screens, fallback))

    def capture_screen(self):
        """Capture primary screen, without this dialog (or main window when shown as page)"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        # Hiding a page closes it (unapplied moves lost): main window is hidden instead
        window = self.window() if self.in_app_page else self
        window.hide()
        QGuiApplication.processEvents()
        pixmap = screen.grabWindow(0)
        window.show()
        window.raise_()
        window.activateWindow()
        if not pixmap.isNull():
            self.canvas.set_background(pixmap, screen.geometry())

    def apply(self) -> int:
        """Move widgets & update preset, return number of moved widgets"""
        moved = 0
        for name, rect in self.canvas.boxes.items():
            widget = wctrl.active_modules.get(name)
            wcfg = cfg.user.setting.get(name)
            if widget is None or wcfg is None:
                continue
            if (wcfg["position_x"], wcfg["position_y"]) != (rect.x(), rect.y()):
                wcfg["position_x"] = rect.x()
                wcfg["position_y"] = rect.y()
                widget.move(rect.x(), rect.y())
                moved += 1
        if moved:
            cfg.save()
            store_screen_layout(cfg)
        self.label_info.setText(trm(f"{moved} widgets moved"))
        return moved

    def save(self):
        self.apply()
        self.accept()
