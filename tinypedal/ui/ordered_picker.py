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
Ordered picker: choose & order entries (navigation bar, home quick access, display order)

Shown entries on the left, in order: numbered, dragged to reorder, move up / down & remove
buttons on each row (Alt+Up / Alt+Down, Delete). Available entries on the right, grouped by
kind, with search: added by their + button, double-click or Enter. Stacked when narrow.
Rows are drawn by a delegate: icon glyph, label, kind pill, buttons.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ._common import UIScaler

ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
ROLE_KEY = Qt.ItemDataRole.UserRole
ROLE_HEADER = Qt.ItemDataRole.UserRole + 1  # section title row of available list
# Row buttons: name: (icon font glyph, fallback text, tooltip)
BUTTONS = {
    "up": ("", "▲", "Move Up"),
    "down": ("", "▼", "Move Down"),
    "remove": ("", "✕", "Remove"),
    "add": ("", "+", "Add"),
}
STACK_WIDTH = 44  # UIScaler size: lists side by side from this picker width, stacked below


def icon_font_family() -> str:
    """Installed icon font (Windows 10 / 11), "" if none: letters are drawn instead"""
    families = set(QFontDatabase.families())
    return next((family for family in ICON_FONTS if family in families), "")


class PickerEntry(NamedTuple):
    """Entry that can be shown & ordered"""

    key: str
    label: str  # translated
    glyph: str = ""  # icon font glyph
    letter: str = ""  # drawn without icon font
    kind: str = ""  # translated group name: section of available list (plural: "Tools")
    removable: bool = True  # False: always shown, only reordered
    tag: str = ""  # translated pill of shown row (singular: "Tool"), kind if not set


class RowDelegate(QStyledItemDelegate):
    """Row card: (grip, number badge) icon, label, kind pill, buttons"""

    def __init__(self, picker: OrderedPicker, shown: bool):
        super().__init__(picker)
        self.picker = picker
        self.shown = shown

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        line = option.fontMetrics.height()
        if index.data(ROLE_HEADER):
            return QSize(line * 8, round(line * 1.9))
        return QSize(line * 12, round(line * 2.4))

    def buttons(self, index: QModelIndex | QPersistentModelIndex) -> tuple[str, ...]:
        """Buttons of row"""
        if index.data(ROLE_HEADER):
            return ()
        if not self.shown:
            return ("add",)
        entry = self.picker.entries.get(index.data(ROLE_KEY))
        if entry is not None and not entry.removable:
            return ("up", "down")
        return ("up", "down", "remove")

    def button_rects(self, rect: QRectF, index: QModelIndex | QPersistentModelIndex) -> dict[str, QRectF]:
        """Button areas, right aligned in row"""
        size = rect.height() * 0.72
        gap = rect.height() * 0.08
        top = rect.center().y() - size / 2
        right = rect.right() - rect.height() * 0.22
        rects = {}
        for name in reversed(self.buttons(index)):
            rects[name] = QRectF(right - size, top, size, size)
            right -= size + gap
        return rects

    def card_rect(self, option: QStyleOptionViewItem) -> QRectF:
        margin = max(UIScaler.pixel(2), 2)
        return QRectF(option.rect).adjusted(margin, margin, -margin, -margin)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex | QPersistentModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = option.palette
        text_color = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText)
        muted = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
        accent = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight)
        if index.data(ROLE_HEADER):  # section title of available list
            font = QFont(option.font)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(muted)
            area = QRectF(option.rect).adjusted(UIScaler.pixel(6), 0, 0, -UIScaler.pixel(2))
            painter.drawText(area, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft, index.data())
            painter.restore()
            return
        card = self.card_rect(option)
        radius = card.height() * 0.22
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        fill = QColor(accent if hover or selected else text_color)
        fill.setAlphaF(0.14 if selected else 0.08 if hover else 0.035)
        border = QColor(accent if selected else palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Mid))
        painter.setPen(border)
        painter.setBrush(fill)
        painter.drawRoundedRect(card, radius, radius)

        left = card.left() + card.height() * 0.25
        height = card.height()
        if self.shown:
            # Grip dots: row can be dragged
            dot = max(height * 0.055, 1.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(muted)
            for column in range(2):
                for row in range(3):
                    painter.drawEllipse(QPointF(left + column * dot * 2.6, card.center().y() + (row - 1) * dot * 2.6),
                                        dot / 2 * 1.3, dot / 2 * 1.3)
            left += dot * 2.6 + height * 0.25
            # Position badge (number or shortcut)
            badge = self.picker.badge_text(index.row())
            if badge:
                font = QFont(option.font)
                font.setPointSizeF(font.pointSizeF() * 0.82)
                font.setBold(True)
                widest = self.picker.widest_badge()
                width = max(QFontMetricsF(font).horizontalAdvance(widest) + height * 0.3, height * 0.56)
                badge_rect = QRectF(left, card.center().y() - height * 0.22, width, height * 0.44)
                badge_fill = QColor(accent)
                badge_fill.setAlphaF(0.22)
                painter.setBrush(badge_fill)
                painter.drawRoundedRect(badge_rect, badge_rect.height() / 2, badge_rect.height() / 2)
                painter.setFont(font)
                painter.setPen(accent)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
                left = badge_rect.right() + height * 0.25
        # Icon
        entry = self.picker.entries.get(index.data(ROLE_KEY))
        icon_size = height * 0.62
        if entry is not None and (entry.glyph or entry.letter):
            if self.picker.icon_family and entry.glyph:
                icon_font = QFont(self.picker.icon_family)
                glyph = entry.glyph
            else:
                icon_font = QFont(option.font)
                icon_font.setBold(True)
                glyph = entry.letter or entry.label[:1]
            icon_font.setPixelSize(max(round(icon_size * 0.62), 8))
            painter.setFont(icon_font)
            painter.setPen(accent)
            painter.drawText(QRectF(left, card.top(), icon_size, height), Qt.AlignmentFlag.AlignCenter, glyph)
            left += icon_size + height * 0.2
        # Buttons (hovered one highlighted)
        rects = self.button_rects(card, index)
        right = min((rect.left() for rect in rects.values()), default=card.right()) - height * 0.2
        view = self.parent_view()
        mouse = view.viewport().mapFromGlobal(QCursor.pos()) if view is not None else None
        for name, rect in rects.items():
            under = mouse is not None and rect.contains(QPointF(mouse))
            enabled = self.button_enabled(name, index)
            if under and enabled:
                hover_fill = QColor(accent)
                hover_fill.setAlphaF(0.22)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(hover_fill)
                painter.drawRoundedRect(rect, rect.height() * 0.25, rect.height() * 0.25)
            glyph, fallback, _ = BUTTONS[name]
            font = QFont(self.picker.icon_family) if self.picker.icon_family else QFont(option.font)
            font.setPixelSize(max(round(rect.height() * (0.42 if self.picker.icon_family else 0.55)), 7))
            painter.setFont(font)
            color = QColor(accent if name == "add" else text_color)
            if not enabled:
                color = muted
            elif not (under or hover or selected):
                color.setAlphaF(0.55)
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph if self.picker.icon_family else fallback)
        # Kind pill
        tag = entry.tag or entry.kind if entry is not None else ""
        if self.shown and tag and self.picker.show_kind:
            font = QFont(option.font)
            font.setPointSizeF(font.pointSizeF() * 0.8)
            metrics = QFontMetricsF(font)
            width = metrics.horizontalAdvance(tag) + height * 0.36
            pill = QRectF(right - width, card.center().y() - height * 0.2, width, height * 0.4)
            if pill.left() > left + height * 2:
                pill_fill = QColor(text_color)
                pill_fill.setAlphaF(0.08)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(pill_fill)
                painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
                painter.setFont(font)
                painter.setPen(muted)
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, tag)
                right = pill.left() - height * 0.2
        # Label
        painter.setFont(option.font)
        painter.setPen(text_color)
        label_rect = QRectF(left, card.top(), max(right - left, 0), height)
        label = QFontMetricsF(option.font).elidedText(index.data(), Qt.TextElideMode.ElideRight, label_rect.width())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        painter.restore()

    def parent_view(self) -> QListWidget | None:
        return self.picker.shown_list if self.shown else self.picker.available_list

    def button_enabled(self, name: str, index: QModelIndex | QPersistentModelIndex) -> bool:
        if name == "up":
            return index.row() > 0
        if name == "down":
            return index.row() < index.model().rowCount() - 1
        return True

    def helpEvent(self, event, view, option, index):
        """Tooltip of button under mouse"""
        if event.type() == QEvent.Type.ToolTip and index.isValid():
            for name, rect in self.button_rects(self.card_rect(option), index).items():
                if rect.contains(QPointF(event.pos())):
                    from PySide6.QtWidgets import QToolTip

                    QToolTip.showText(event.globalPos(), tr(BUTTONS[name][2]), view)
                    return True
        return super().helpEvent(event, view, option, index)

    def editorEvent(self, event, model, option, index) -> bool:
        """Click on row button runs it"""
        if event.type() == QEvent.Type.MouseMove:
            view = self.parent_view()
            if view is not None:
                view.viewport().update()  # button hover
            return False
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            for name, rect in self.button_rects(self.card_rect(option), index).items():
                if rect.contains(event.position()) and self.button_enabled(name, index):
                    self.picker.run_button(name, index.data(ROLE_KEY))
                    return True
        return super().editorEvent(event, model, option, index)


class ShownList(QListWidget):
    """Shown entries: drag to reorder, Alt+Up / Alt+Down move, Delete removes"""

    def __init__(self, picker: OrderedPicker):
        super().__init__(picker)
        self.picker = picker

    def keyPressEvent(self, event):
        item = self.currentItem()
        modifiers = event.modifiers()
        if item is not None and modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier):
            if event.key() == Qt.Key.Key_Up:
                self.picker.move_entry(item.data(ROLE_KEY), -1)
                return
            if event.key() == Qt.Key.Key_Down:
                self.picker.move_entry(item.data(ROLE_KEY), 1)
                return
        if item is not None and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.picker.remove(item.data(ROLE_KEY))
            return
        super().keyPressEvent(event)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.picker.order_changed()


class AvailableList(QListWidget):
    """Available entries: Enter or double-click adds"""

    def __init__(self, picker: OrderedPicker):
        super().__init__(picker)
        self.picker = picker
        self.itemDoubleClicked.connect(lambda item: self.picker.add(item.data(ROLE_KEY)))

    def keyPressEvent(self, event):
        item = self.currentItem()
        if item is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.picker.add(item.data(ROLE_KEY))
            return
        super().keyPressEvent(event)


class OrderedPicker(QWidget):
    """Shown entries in order & available entries to add

    Args:
        entries: every entry by key, available list follows this order (grouped by kind).
        shown: keys of shown entries, in order.
        badge: text of position badge of shown row index ("" none), numbers by default.
        show_kind: kind pill on shown rows.
    """

    changed = Signal()  # shown entries or their order changed by user

    def __init__(self, parent, entries: dict[str, PickerEntry], shown: list[str], icon_family: str = "",
                 badge: Callable[[int], str] | None = None, show_kind: bool = True,
                 empty_text: str = ""):
        super().__init__(parent)
        self.entries = entries
        self.icon_family = icon_family
        self.badge = badge
        self.show_kind = show_kind
        self.can_hide = any(entry.removable for entry in entries.values())

        # Shown entries
        self.label_shown = QLabel(self)
        self.label_shown.setObjectName("pickerTitle")
        self.shown_list = ShownList(self)
        self.shown_list.setObjectName("pickerList")
        self.shown_list.setItemDelegate(RowDelegate(self, shown=True))
        self.shown_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.shown_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.shown_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.shown_list.setMouseTracking(True)
        self.shown_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.label_empty = QLabel(empty_text or tr("Nothing shown: add entries from the list."), self)
        self.label_empty.setObjectName("pickerEmpty")
        self.label_empty.setWordWrap(True)
        self.label_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shown_card = QFrame(self)
        shown_card.setObjectName("pickerCard")
        layout_shown = QVBoxLayout(shown_card)
        margin = UIScaler.pixel(8)
        layout_shown.setContentsMargins(margin, margin, margin, margin)
        layout_shown.setSpacing(UIScaler.pixel(6))
        layout_shown.addWidget(self.label_shown)
        layout_shown.addWidget(self.label_empty)
        layout_shown.addWidget(self.shown_list, stretch=1)

        # Available entries
        self.available_card = QFrame(self)
        self.available_card.setObjectName("pickerCard")
        self.label_available = QLabel(tr("Available"), self.available_card)
        self.label_available.setObjectName("pickerTitle")
        self.edit_search = QLineEdit(self.available_card)
        self.edit_search.setPlaceholderText(tr("Search..."))
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.textChanged.connect(self.filter_available)
        self.available_list = AvailableList(self)
        self.available_list.setObjectName("pickerList")
        self.available_list.setItemDelegate(RowDelegate(self, shown=False))
        self.available_list.setMouseTracking(True)
        self.available_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.label_all_shown = QLabel(tr("Every entry is shown."), self.available_card)
        self.label_all_shown.setObjectName("pickerEmpty")
        self.label_all_shown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout_available = QVBoxLayout(self.available_card)
        layout_available.setContentsMargins(margin, margin, margin, margin)
        layout_available.setSpacing(UIScaler.pixel(6))
        layout_available.addWidget(self.label_available)
        layout_available.addWidget(self.edit_search)
        layout_available.addWidget(self.label_all_shown)
        layout_available.addWidget(self.available_list, stretch=1)
        self.available_card.setHidden(not self.can_hide)

        self.layout_main = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.layout_main.setContentsMargins(0, 0, 0, 0)
        self.layout_main.setSpacing(UIScaler.pixel(10))
        self.layout_main.addWidget(shown_card, stretch=1)
        self.layout_main.addWidget(self.available_card, stretch=1)
        self.set_shown(shown, notify=False)

    # Content
    def badge_text(self, row: int) -> str:
        return self.badge(row) if self.badge is not None else str(row + 1)

    def widest_badge(self) -> str:
        """Longest badge text of shown rows: same badge width on every row"""
        return max((self.badge_text(row) for row in range(self.shown_list.count())), key=len, default="")

    def shown_keys(self) -> list[str]:
        """Keys of shown entries, in order"""
        return [self.shown_list.item(row).data(ROLE_KEY) for row in range(self.shown_list.count())]

    def set_shown(self, keys: list[str], notify: bool = True, current: str = ""):
        """Show entries in order (unknown keys left out, entries that cannot be hidden kept at end)"""
        valid = [key for key in dict.fromkeys(keys) if key in self.entries]
        valid += [key for key, entry in self.entries.items() if not entry.removable and key not in valid]
        self.shown_list.clear()
        for key in valid:
            item = QListWidgetItem(self.entries[key].label)
            item.setData(ROLE_KEY, key)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.shown_list.addItem(item)
            if key == current:
                self.shown_list.setCurrentItem(item)
        self.fill_available()
        self.refresh_titles()
        if notify:
            self.changed.emit()

    def fill_available(self):
        """Entries not shown, grouped by kind (section titles)"""
        shown = set(self.shown_keys())
        self.available_list.clear()
        kind = None
        for key, entry in self.entries.items():
            if key in shown or not entry.removable:
                continue
            if entry.kind and entry.kind != kind:
                kind = entry.kind
                header = QListWidgetItem(entry.kind)
                header.setData(ROLE_HEADER, True)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.available_list.addItem(header)
            item = QListWidgetItem(entry.label)
            item.setData(ROLE_KEY, key)
            self.available_list.addItem(item)
        self.filter_available(self.edit_search.text())

    def filter_available(self, text: str):
        """Hide entries not matching search words, and sections left empty"""
        words = text.lower().split()
        header: QListWidgetItem | None = None
        header_used = False
        any_shown = False
        for row in range(self.available_list.count()):
            item = self.available_list.item(row)
            if item.data(ROLE_HEADER):
                if header is not None:
                    header.setHidden(not header_used)
                header, header_used = item, False
                continue
            entry = self.entries[item.data(ROLE_KEY)]
            match = all(word in f"{entry.label} {entry.kind} {entry.key}".lower() for word in words)
            item.setHidden(not match)
            header_used = header_used or match
            any_shown = any_shown or match
        if header is not None:
            header.setHidden(not header_used)
        self.label_all_shown.setText(tr("No entry found.") if words else tr("Every entry is shown."))
        self.label_all_shown.setHidden(any_shown)

    def refresh_titles(self):
        count = self.shown_list.count()
        self.label_shown.setText(f"{tr('Shown')} ({count})")
        self.label_empty.setHidden(count > 0)
        self.shown_list.viewport().update()

    # Changes by user
    def run_button(self, name: str, key: str):
        if name == "up":
            self.move_entry(key, -1)
        elif name == "down":
            self.move_entry(key, 1)
        elif name == "remove":
            self.remove(key)
        elif name == "add":
            self.add(key)

    def add(self, key: str):
        """Add entry at end of shown entries"""
        if key not in self.entries or key in self.shown_keys():
            return
        self.set_shown([*self.shown_keys(), key], current=key)
        self.shown_list.scrollToItem(self.shown_list.currentItem())

    def remove(self, key: str):
        entry = self.entries.get(key)
        if entry is None or not entry.removable:
            return
        keys = self.shown_keys()
        if key not in keys:
            return
        row = keys.index(key)
        keys.remove(key)
        self.set_shown(keys, current=keys[min(row, len(keys) - 1)] if keys else "")

    def move_entry(self, key: str, step: int):
        """Move shown entry up (-1) or down (1), selection kept on it"""
        keys = self.shown_keys()
        if key not in keys:
            return
        row = keys.index(key)
        target = row + step
        if not 0 <= target < len(keys):
            return
        keys.insert(target, keys.pop(row))
        self.set_shown(keys, current=key)

    def move_selected(self, step: int):
        item = self.shown_list.currentItem()
        if item is not None:
            self.move_entry(item.data(ROLE_KEY), step)

    def order_changed(self):
        """Dragged to new place"""
        self.refresh_titles()
        self.changed.emit()

    # Layout
    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = (QBoxLayout.Direction.LeftToRight if event.size().width() >= UIScaler.size(STACK_WIDTH)
                     else QBoxLayout.Direction.TopToBottom)
        if self.layout_main.direction() != direction:
            self.layout_main.setDirection(direction)
