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
Edit mode toolbar: floating bar on game screen while overlays are edited (see _edit_mode)

Drawn like the modern overlays (overlay theme colors, design font), dragged by its grip, never
takes focus from the game or from the selected overlay (arrow keys keep moving it).
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from ..const_file import FontFile
from ..i18n import tr
from ..i18n.options import module_label
from ..setting import cfg
from ._edit_frame import EDIT_COLOR
from ._edit_mode import step_text
from ._modern.theme import build_theme
from ._snapping import fit_on_screens

if TYPE_CHECKING:
    from ._edit_mode import EditMode

ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
SHADOW = 10  # margin around bar for its shadow
BAR_HEIGHT = 46
PADDING = 6
BUTTON_HEIGHT = 32
TITLE_WIDTH = 200
TOP_OFFSET = 14  # default place: top center of primary screen

# Items: key, kind, icon glyph (Segoe Fluent Icons / MDL2 Assets), label shown next to icon
GRIP, TITLE, SEPARATOR, TOGGLE, BUTTON, PRIMARY, CLOSE = range(7)
ITEMS = (
    ("grip", GRIP, "", ""),
    ("title", TITLE, "\uE70F", ""),  # edit (pencil)
    ("", SEPARATOR, "", ""),
    ("snap", TOGGLE, "\uE8B3", "Snap"),  # select all (dashed boxes)
    ("grid", TOGGLE, "\uE80A", "Grid"),  # grid view
    ("guides", TOGGLE, "\uEB3C", "Guides"),  # ruler & set square
    ("", SEPARATOR, "", ""),
    ("undo", BUTTON, "\uE7A7", ""),
    ("redo", BUTTON, "\uE7A6", ""),
    ("", SEPARATOR, "", ""),
    ("overlays", BUTTON, "\uE8A9", "Overlays"),  # view all (four squares)
    ("done", PRIMARY, "\uE73E", "Done"),  # check
    ("close", CLOSE, "\uE711", ""),  # cancel (x)
)
FALLBACK_TEXT = {"undo": "Undo", "redo": "Redo", "close": "\u2715"}  # no icon font (Linux)
CLICKABLE = frozenset((TOGGLE, BUTTON, PRIMARY, CLOSE))


def icon_font_family() -> str:
    """Installed icon font (Windows 10 / 11), "" if none: labels are shown instead"""
    families = set(QFontDatabase.families())
    return next((family for family in ICON_FONTS if family in families), "")


class ToolItem:
    """Toolbar entry"""

    __slots__ = ("key", "kind", "glyph", "label", "rect", "checked", "enabled", "tip")

    def __init__(self, key: str, kind: int, glyph: str, label: str):
        self.key = key
        self.kind = kind
        self.glyph = glyph
        self.label = label
        self.rect = QRect()
        self.checked = False
        self.enabled = True
        self.tip = ""


class EditToolbar(QWidget):
    """Floating edit mode toolbar"""

    def __init__(self, controller: EditMode):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowTitle(tr("Edit Overlays"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setMouseTracking(True)
        self.controller = controller
        self.items = [ToolItem(*spec) for spec in ITEMS]
        self.hovered: ToolItem | None = None
        self.pressed: ToolItem | None = None
        self.placed = False  # moved to default place once, then kept where user drags it
        self._drag_offset: QPoint | None = None
        self.title = ""
        self.detail = ""
        self.icon_family = icon_font_family()
        style = cfg.user.config["overlay_style"]
        self.theme = build_theme(style, surface_alpha=242)
        family = style.get("modern_design_font_name") or FontFile.DESIGN_FAMILY
        self.font_label = self.make_font(family, 14, QFont.Weight.DemiBold)
        self.font_title = self.make_font(family, 15, QFont.Weight.Bold)
        self.font_detail = self.make_font(family, 12, QFont.Weight.Medium)
        self.font_icon = self.make_font(self.icon_family, 16, QFont.Weight.Normal)
        self.relayout()

    @staticmethod
    def make_font(family: str, size: int, weight: QFont.Weight) -> QFont:
        font = QFont(family) if family else QFont()
        font.setPixelSize(size)
        font.setWeight(weight)
        font.setFeature(QFont.Tag("tnum"), 1)  # fixed width digits: position does not jitter
        return font

    # Content
    def text_of(self, item: ToolItem) -> str:
        """Label shown next to icon (or alone without icon font)"""
        if item.label:
            return tr(item.label)
        if not self.icon_family:
            return tr(FALLBACK_TEXT.get(item.key, ""))
        return ""

    def relayout(self):
        """Place items from left to right, size bar to fit"""
        metrics = QFontMetrics(self.font_label)
        x = SHADOW + PADDING
        top = SHADOW + (BAR_HEIGHT - BUTTON_HEIGHT) // 2
        for item in self.items:
            if item.kind == GRIP:
                width = 16
            elif item.kind == TITLE:
                width = TITLE_WIDTH
            elif item.kind == SEPARATOR:
                width = 11
            else:
                text = self.text_of(item)
                icon = 18 if self.icon_family and item.glyph else 0
                text_width = metrics.horizontalAdvance(text) if text else 0
                width = icon + text_width + (6 if icon and text else 0) + (24 if text else 16)
                if item.kind == CLOSE:
                    width = max(width, 30)
            item.rect = QRect(x, top, width, BUTTON_HEIGHT)
            x += width + (2 if item.kind in CLICKABLE else 0)
        self.setFixedSize(x + PADDING + SHADOW, BAR_HEIGHT + 2 * SHADOW)

    def refresh(self):
        """Read toggles, history & selection again"""
        from ._edit_mode import active_overlays

        overlays = active_overlays()
        history = self.controller.history
        undo, redo = history.peek_undo(), history.peek_redo()
        states = {
            "snap": cfg.application.get("enable_magnetic_snap", True),
            "grid": cfg.overlay["enable_grid_move"],
            "guides": cfg.application["show_layout_guides"],
        }
        tips = {
            "title": tr("Drag an overlay to move it, its corner to resize it. Arrow keys move the selected "
                        "overlay (Shift: 10 pixels). Right click an overlay for more."),
            "snap": tr("Snap to screen edges & other overlays (hold Ctrl to move freely)"),
            "grid": tr("Grid Move"),
            "guides": tr("Alignment guides & position while dragging"),
            "undo": f"{tr('Undo')}{step_text(undo)} (Ctrl+Z)",
            "redo": f"{tr('Redo')}{step_text(redo)} (Ctrl+Y)",
            "overlays": tr("Active overlays"),
            "done": tr("Lock overlays & leave edit mode"),
            "close": tr("Hide toolbar (overlays stay unlocked)"),
        }
        for item in self.items:
            item.checked = bool(states.get(item.key, False))
            item.tip = tips.get(item.key, "")
            if item.key == "undo":
                item.enabled = undo is not None
            elif item.key == "redo":
                item.enabled = redo is not None
        selected = overlays.get(self.controller.selected)
        if selected is not None:
            geometry = selected.geometry()
            self.title = module_label(self.controller.selected)
            self.detail = (f"X {geometry.x()}   Y {geometry.y()}   \u00B7   "
                           f"{geometry.width()} \u00D7 {geometry.height()}")
        else:
            count = len(overlays)
            self.title = tr("Edit Overlays")
            self.detail = f"{count} overlay{'s' if count != 1 else ''}"
        self.update()

    # Placement
    def show_on_screen(self):
        """Show at top center of primary screen first, then where user left it (if still on a screen)"""
        screens = [screen.availableGeometry() for screen in QGuiApplication.screens()]
        if not self.placed or fit_on_screens(QRect(self.pos(), self.size()), screens) is not None:
            screen = QGuiApplication.primaryScreen()
            area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
            self.move(area.x() + (area.width() - self.width()) // 2, area.y() + TOP_OFFSET)
            self.placed = True
        self.show()
        self.raise_()

    # Painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        theme = self.theme
        bar = QRectF(SHADOW, SHADOW, self.width() - 2 * SHADOW, BAR_HEIGHT)
        # Soft shadow below bar
        painter.setPen(Qt.PenStyle.NoPen)
        for spread, alpha in ((8, 10), (5, 18), (2, 34)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(bar.adjusted(-spread, -spread + 3, spread, spread + 3), 12 + spread, 12 + spread)
        painter.setBrush(theme.surface)
        painter.setPen(QPen(theme.border, 1))
        painter.drawRoundedRect(bar.adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
        for item in self.items:
            if item.kind == GRIP:
                self.draw_grip(painter, item)
            elif item.kind == TITLE:
                self.draw_title(painter, item)
            elif item.kind == SEPARATOR:
                painter.setPen(QPen(theme.border, 1))
                center = item.rect.center().x() + 0.5
                painter.drawLine(QPointF(center, item.rect.top() + 5), QPointF(center, item.rect.bottom() - 4))
            else:
                self.draw_button(painter, item)

    def draw_grip(self, painter: QPainter, item: ToolItem):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.theme.text_faint)
        center = item.rect.center()
        for column in (-3, 3):
            for row in (-6, 0, 6):
                painter.drawEllipse(QRectF(center.x() + column - 1.5, center.y() + row - 1.5, 3, 3))

    def draw_title(self, painter: QPainter, item: ToolItem):
        rect = item.rect
        text_left = rect.left()
        if self.icon_family:
            painter.setFont(self.font_icon)
            painter.setPen(EDIT_COLOR)
            painter.drawText(QRect(rect.left(), rect.top(), 22, rect.height()), Qt.AlignmentFlag.AlignCenter,
                             item.glyph)
            text_left += 28
        width = rect.right() - text_left
        painter.setFont(self.font_title)
        painter.setPen(self.theme.text)
        title = QFontMetrics(self.font_title).elidedText(self.title, Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(text_left, rect.top() - 1, width, rect.height() // 2 + 2),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, title)
        painter.setFont(self.font_detail)
        painter.setPen(self.theme.text_dim)
        detail = QFontMetrics(self.font_detail).elidedText(self.detail, Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(text_left, rect.top() + rect.height() // 2 + 1, width, rect.height() // 2),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, detail)

    def draw_button(self, painter: QPainter, item: ToolItem):
        theme = self.theme
        rect = QRectF(item.rect)
        hovered = item is self.hovered and item.enabled
        pressed = item is self.pressed and hovered
        foreground = theme.text_dim
        background: QColor | None = None
        if item.kind == PRIMARY:
            background = QColor(EDIT_COLOR).lighter(118 if hovered else 100)
            if pressed:
                background = QColor(EDIT_COLOR).darker(115)
            foreground = QColor("#FFFFFF")
        elif item.checked:
            background = theme.tint(EDIT_COLOR, 92 if hovered else 66)
            foreground = theme.text
        elif hovered:
            hover_color = theme.negative if item.kind == CLOSE else theme.text
            background = theme.tint(hover_color, 44 if pressed else 26)
            foreground = theme.text
        if not item.enabled:
            foreground = theme.text_faint
        if background is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(rect, 7, 7)
        text = self.text_of(item)
        left = rect.left() + (12 if text else 0)
        if self.icon_family and item.glyph:
            painter.setFont(self.font_icon)
            painter.setPen(foreground)
            icon_rect = QRectF(left, rect.top(), 18, rect.height()) if text else rect
            painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, item.glyph)
            left += 24
        if text:
            painter.setFont(self.font_label)
            painter.setPen(foreground)
            painter.drawText(QRectF(left, rect.top(), rect.right() - left - 10, rect.height()),
                             Qt.AlignmentFlag.AlignCenter if not (self.icon_family and item.glyph)
                             else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    # Mouse
    def item_at(self, pos: QPoint) -> ToolItem | None:
        for item in self.items:
            if item.rect.contains(pos):
                return item
        return None

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            item = self.item_at(event.pos())
            if item is not None and item.tip:
                QToolTip.showText(event.globalPos(), item.tip, self, item.rect)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        item = self.item_at(event.position().toPoint())
        if item is None or item.kind in (GRIP, TITLE, SEPARATOR):  # drag toolbar by its bar
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif item.enabled:
            self.pressed = item
            self.update()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            return
        item = self.item_at(event.position().toPoint())
        if item is not None and item.kind not in CLICKABLE:
            item = None
        if item is not self.hovered:
            self.hovered = item
            self.setCursor(Qt.CursorShape.PointingHandCursor if item is not None and item.enabled
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self._drag_offset = None
            self.unsetCursor()
            return
        item, self.pressed = self.pressed, None
        self.update()
        if item is not None and item is self.item_at(event.position().toPoint()) and item.enabled:
            self.trigger(item.key)

    def leaveEvent(self, event):
        if self.hovered is not None:
            self.hovered = None
            self.update()

    # Actions
    def trigger(self, key: str):
        """Run toolbar action"""
        from ..overlay_control import octrl
        from ._edit_mode import toggle_application_option

        controller = self.controller
        if key == "snap":
            toggle_application_option("enable_magnetic_snap")
        elif key == "grid":
            octrl.toggle.grid()
            self.refresh()
        elif key == "guides":
            toggle_application_option("show_layout_guides")
        elif key == "undo":
            controller.undo()
        elif key == "redo":
            controller.redo()
        elif key == "overlays":
            self.show_overlay_menu()
        elif key == "done":
            octrl.toggle.lock()
        elif key == "close":
            controller.leave()

    def show_overlay_menu(self):
        """Active overlays (uncheck to turn off, undoable), and Overlays page of the app"""
        from ._edit_mode import active_overlays

        menu = QMenu(self)
        names = sorted(active_overlays(), key=lambda name: module_label(name).lower())
        for name in names:
            action = menu.addAction(module_label(name))
            action.setCheckable(True)
            action.setChecked(True)
            action.triggered.connect(partial(disable_overlay, name))
        if names:
            menu.addSeparator()
        menu.addAction(tr("All Overlays..."), open_overlays_page)
        item = next(item for item in self.items if item.key == "overlays")
        menu.exec(self.mapToGlobal(item.rect.bottomLeft() + QPoint(0, 6)))
        menu.deleteLater()


def disable_overlay(name: str, *_):
    """Turn overlay off, undoable"""
    from ._edit_mode import apply_values, edit_mode

    edit_mode().record(name, "Disable", {"enable": True}, {"enable": False})
    apply_values(name, {"enable": False})


def open_overlays_page():
    """Show Overlays page of main window"""
    from PySide6.QtWidgets import QApplication, QMainWindow

    for window in QApplication.topLevelWidgets():
        if isinstance(window, QMainWindow) and hasattr(window, "show_app"):
            from ..ui.nav_rail import PAGE_INDEX

            select_page = getattr(window.centralWidget(), "set_current_index", None)
            if callable(select_page) and "widget" in PAGE_INDEX:
                select_page(PAGE_INDEX["widget"])
            window.show_app()
            return
