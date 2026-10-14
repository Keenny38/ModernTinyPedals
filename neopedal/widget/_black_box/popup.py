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
Black box widget, setting change pop-up

Driver setting just changed in the car (TC, ABS, brake bias...), see state.SettingChanges: drawn over the
center column (top, middle or bottom), or over the car view in compact layout (no center column). One change:
setting name above its new value (TC / 4/9 with highest level). Two changes at once: one row each. An arrow and
the pop-up color (green up, red down) tell which way the value went. Fades in & out. Own part (see regions): repainted alone, parts below it drawn again.
"""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath

from .._painter import fill_rect
from .state import SettingChange

if TYPE_CHECKING:
    from ...template.widget_config_types import BlackBoxConfig

POPUP_HEIGHT = 2.2  # units, one change (two rows) or two changes (one row each)
COMPACT_POPUP_WIDTH = 6.0  # units, over the car view (compact layout)


class PopupPainter:
    """Draw setting change pop-up"""

    # Attributes set by black box widget class (widget/black_box.py) or other parts
    draw_fit_text: Any
    font_label: Any
    font_popup: Any
    pen_setting_popup: Any
    rect_car_view: Any
    rect_center: Any
    setting_changes: Any
    show_setting_popup: Any
    text: Any
    unit: Any
    wcfg: BlackBoxConfig

    def setting_popup(self) -> tuple[SettingChange, ...]:
        """Changes shown now, newest first (empty: no pop-up)"""
        if not self.show_setting_popup:
            return ()
        return self.setting_changes.current(monotonic())

    def setting_popup_opacity(self) -> float:
        return self.setting_changes.opacity(monotonic()) if self.show_setting_popup else 0.0

    def setting_popup_key(self) -> tuple:
        """What pop-up draws (see drawn): changes as shown, opacity while fading"""
        changes = self.setting_popup()
        if not changes:
            return ()
        return tuple((*change[:4], change.maximum) for change in changes), round(self.setting_popup_opacity(), 2)

    def setting_popup_fading(self) -> bool:
        """Pop-up fading in or out: repainted every update (see animating_parts)"""
        return bool(self.setting_popup()) and self.setting_popup_opacity() < 1

    def setting_popup_area(self) -> QRectF:
        """Room pop-up is placed in: center column, else middle of car view (compact layout)"""
        if not self.rect_center.isNull():
            return self.rect_center
        view = self.rect_car_view
        width = min(view.width() * 0.8, self.unit * COMPACT_POPUP_WIDTH)
        return QRectF(view.center().x() - width / 2, view.top(), width, view.height())

    def setting_popup_rect(self) -> QRectF:
        """Pop-up box, at top, middle or bottom of its room"""
        area = self.setting_popup_area()
        height = min(self.unit * POPUP_HEIGHT, area.height())
        position = self.wcfg["setting_popup_position"]
        if position == "Bottom":
            top = area.bottom() - height
        elif position == "Middle":
            top = area.center().y() - height / 2
        else:
            top = area.top()
        return QRectF(area.left(), top, area.width(), height)

    def draw_setting_popup(self, painter: QPainter):
        changes = self.setting_popup()
        if not changes:
            return
        opacity = self.setting_popup_opacity()
        if opacity <= 0:
            return
        unit = self.unit
        box = self.setting_popup_rect()
        painter.save()
        painter.setOpacity(opacity)
        if len(changes) == 1:
            fill_rect(painter, box, self.setting_popup_color(changes[0]))
        else:  # one band per change, each in the color of its own direction
            band_h = box.height() / len(changes)
            for index, change in enumerate(changes):
                fill_rect(painter, QRectF(box.left(), box.top() + index * band_h, box.width(), band_h),
                          self.setting_popup_color(change))
        painter.setPen(self.pen_setting_popup)
        pad = unit * 0.15
        inner = box.adjusted(pad, unit * 0.05, -pad, -unit * 0.05)
        if len(changes) == 1:
            name, direction = changes[0].name, changes[0].direction
            label = QRectF(inner.left(), inner.top(), inner.width(), inner.height() * 0.36)
            value = QRectF(inner.left(), label.bottom(), inner.width(), inner.bottom() - label.bottom())
            self.draw_fit_text(painter, label, self.setting_label(name), self.font_label)
            arrow = unit * 0.7 if direction else 0.0  # room kept on both sides: value stays centered
            self.draw_fit_text(painter, value.adjusted(arrow, 0, -arrow, 0), self.setting_value(changes[0]),
                               self.font_popup)
            if direction:
                self.draw_direction(painter, QRectF(value.right() - arrow, value.top(), arrow, value.height()),
                                    direction)
        else:
            row_h = inner.height() / len(changes)
            arrow = unit * 0.6
            for index, change in enumerate(changes):
                name, direction = change.name, change.direction
                row = QRectF(inner.left(), inner.top() + index * row_h, inner.width(), row_h)
                name_w = row.width() * 0.4
                self.draw_fit_text(painter, QRectF(row.left(), row.top(), name_w, row.height()),
                                   self.setting_label(name), self.font_label, Qt.AlignmentFlag.AlignLeft
                                   | Qt.AlignmentFlag.AlignVCenter)
                gap = unit * 0.1 if direction else 0.0
                value = QRectF(row.left() + name_w, row.top(), row.width() - name_w - arrow - gap, row.height())
                self.draw_fit_text(painter, value, self.setting_value(change), self.font_popup,
                                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if direction:
                    self.draw_direction(painter, QRectF(value.right() + gap, row.top(), arrow, row.height()),
                                        direction)
        painter.restore()

    def setting_value(self, change: SettingChange) -> str:
        """New value, with highest level if known (4/9); the arrow & color tell which way it went"""
        if change.maximum and not change.event:
            return f"{change.new}/{change.maximum}"
        return change.new

    def setting_popup_color(self, change: SettingChange) -> str:
        """Pop-up (or row) color, by direction of the change if enabled"""
        wcfg = self.wcfg
        if wcfg["enable_setting_popup_direction_color"] and change.direction:
            return wcfg["setting_popup_increase_color" if change.direction > 0 else "setting_popup_decrease_color"]
        return wcfg["setting_popup_color"]

    def setting_label(self, name: str) -> str:
        return self.text.get(name, name.upper())

    def draw_direction(self, painter: QPainter, rect: QRectF, direction: int):
        """Triangle pointing up (value raised) or down, in pop-up text color (drawn: no font glyph needed)"""
        size = min(rect.width() * 0.8, rect.height() * 0.5)
        center = rect.center()
        half = size / 2
        tip = -half if direction > 0 else half
        path = QPainterPath(QPointF(center.x(), center.y() + tip))
        path.lineTo(center.x() + half, center.y() - tip)
        path.lineTo(center.x() - half, center.y() - tip)
        path.closeSubpath()
        painter.fillPath(path, painter.pen().color())
