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
Race notifications Widget, modern design

Stack of toast cards fading out after a few seconds: icon badge in kind color (gain, loss,
warning, info, best) showing what happened (arrow, flag, stopwatch, penalty, invalid lap),
title over detail, thin bar at bottom shrinking with time left. Nothing drawn while there is no
message (unless overlay unlocked, or before first update: picture of Overlays page).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from ...i18n import tr_overlay as tr
from .._race_aids import HiddenPreview
from ..race_notifications import FADE_STEPS, GAIN, INFO, PREVIEW_TITLE, TITLES, NotificationsMixin
from .base import LEFT, ModernOverlay
from .draw import panel, rounded, triangle

BADGE_ALPHA = 48  # icon badge background (kind color)
TIME_BAR_ALPHA = 150
TIME_STEPS = 50  # time left bar steps (widget redrawn only on step change)
# Message title -> icon
ICONS = {
    "Position": "arrow", "Class position": "arrow", "Penalty": "penalty", "Fastest lap": "stopwatch",
    "Blue flag": "flag", "Full course yellow": "flag", "Green flag": "flag", "Lap invalidated": "cross",
    PREVIEW_TITLE: "info",
}


def draw_icon(painter: QPainter, rect: QRectF, icon: str, kind: int, color: QColor) -> None:
    """Notification icon centered in rect (line icons, stroke relative to size)"""
    side = min(rect.width(), rect.height())
    center = rect.center()
    stroke = max(side * 0.11, 1.2)
    pen = QPen(color, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.save()
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    half = side * 0.32
    if icon == "arrow":
        painter.restore()
        triangle(painter, QRectF(center.x() - half, center.y() - half, half * 2, half * 2), kind == GAIN, color)
        return
    if icon == "flag":
        pole_x = center.x() - half * 0.8
        painter.drawLine(QPointF(pole_x, center.y() - half), QPointF(pole_x, center.y() + half))
        cloth = QPainterPath(QPointF(pole_x, center.y() - half))
        cloth.cubicTo(QPointF(pole_x + half * 0.6, center.y() - half * 1.3), QPointF(pole_x + half * 1.1, center.y() - half * 0.5),
                      QPointF(pole_x + half * 1.8, center.y() - half * 0.8))
        cloth.lineTo(QPointF(pole_x + half * 1.8, center.y() + half * 0.1))
        cloth.cubicTo(QPointF(pole_x + half * 1.1, center.y() + half * 0.4), QPointF(pole_x + half * 0.6, center.y() - half * 0.4),
                      QPointF(pole_x, center.y()))
        cloth.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(cloth)
    elif icon == "stopwatch":
        radius = half * 0.92
        dial = QPointF(center.x(), center.y() + half * 0.12)
        painter.drawEllipse(dial, radius, radius)
        painter.drawLine(QPointF(dial.x(), dial.y() - radius), QPointF(dial.x(), dial.y() - radius - half * 0.3))
        painter.drawLine(dial, QPointF(dial.x() + radius * 0.45, dial.y() - radius * 0.45))
    elif icon == "cross":
        painter.drawLine(QPointF(center.x() - half * 0.75, center.y() - half * 0.75),
                         QPointF(center.x() + half * 0.75, center.y() + half * 0.75))
        painter.drawLine(QPointF(center.x() + half * 0.75, center.y() - half * 0.75),
                         QPointF(center.x() - half * 0.75, center.y() + half * 0.75))
    else:  # penalty "!" or info "i": stroke & dot
        dot = stroke * 0.75
        if icon == "penalty":
            painter.drawLine(QPointF(center.x(), center.y() - half), QPointF(center.x(), center.y() + half * 0.3))
            dot_y = center.y() + half * 0.85
        else:
            painter.drawLine(QPointF(center.x(), center.y() - half * 0.15), QPointF(center.x(), center.y() + half))
            dot_y = center.y() - half * 0.7
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(center.x(), dot_y), dot, dot)
    painter.restore()


class Realtime(HiddenPreview, NotificationsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "display_duration", "number_of_notifications", "show_position_change",
        "show_position_change_in_class", "show_penalty", "show_class_fastest_lap", "show_blue_flag",
        "show_full_course_yellow", "show_lap_invalidated",
    )
    update_while_hidden = True  # race state followed while hidden (no stale message when shown)

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.setup_notifications()
        unit = self.unit
        theme = self.theme
        pad = unit * 0.4
        card_h = unit * 2.5
        badge = card_h - pad * 2
        gap = unit * 0.3
        title_w = max(self.text_width("label", tr(title)) for title in (*TITLES, PREVIEW_TITLE))
        self.text_w = max(unit * 10.0, title_w)
        width = pad * 2 + badge + unit * 0.55 + self.text_w
        self.cards = tuple(QRectF(0, (card_h + gap) * index, width, card_h) for index in range(self.max_toasts))
        self.badges = tuple(QRectF(pad, card.top() + pad, badge, badge) for card in self.cards)
        left = pad + badge + unit * 0.55
        line_h = badge / 2
        self.title_rects = tuple(QRectF(left, rect.top(), self.text_w, line_h) for rect in self.badges)
        self.detail_rects = tuple(QRectF(left, rect.top() + line_h, self.text_w, line_h) for rect in self.badges)
        self.single_rects = tuple(QRectF(left, rect.top(), self.text_w, badge) for rect in self.badges)
        self.bar_h = max(unit * 0.12, 1.5)
        self.set_size(width, (card_h + gap) * self.max_toasts - gap)
        self.kind_colors = (theme.positive, theme.negative, theme.warning, theme.blue, theme.best)
        self.badge_colors = tuple(theme.tint(color, BADGE_ALPHA) for color in self.kind_colors)
        self.bar_colors = tuple(theme.tint(color, TIME_BAR_ALPHA) for color in self.kind_colors)
        self.preview = ((PREVIEW_TITLE, tr(PREVIEW_TITLE), "", INFO, FADE_STEPS, 1.0),)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        shown = self.read_notifications()
        now = self.clock()
        duration = self.duration
        self.refresh(tuple(
            (message.title, tr(message.title), self.elided("value", message.detail, self.text_w), message.kind, step,
             round(min(max((duration - (now - toast.start)) / duration, 0.0), 1.0) * TIME_STEPS) / TIME_STEPS)
            for (message, step), toast in zip(shown, reversed(self.toasts))
        ))

    def paintEvent(self, event):
        """Draw while a message is shown (or overlay unlocked, or not updated yet)"""
        if self.state is None:
            self.state = ()
            super().paintEvent(event)
            self.state = None
        elif self.state or self.previewing():
            super().paintEvent(event)

    def paint(self, painter: QPainter):
        theme = self.theme
        shown = self.slot_order(self.state or self.preview)
        radius = self.radius(0.45)
        for index, (key, title, detail, kind, step, left) in enumerate(shown, self.first_slot(len(shown))):
            painter.setOpacity(step / FADE_STEPS)
            card = self.cards[index]
            color = self.kind_colors[kind]
            panel(painter, card, theme, radius, self.depth_effects)
            badge = self.badges[index]
            rounded(painter, badge, self.radius(0.35), self.badge_colors[kind])
            draw_icon(painter, badge, ICONS.get(key, "info"), kind, color)
            if detail:
                self.draw_text(painter, self.title_rects[index], title, "label", color, LEFT)
                self.draw_text(painter, self.detail_rects[index], detail, "value", theme.text, LEFT)
            else:
                self.draw_text(painter, self.single_rects[index], title, "strong", color, LEFT)
            if left > 0:
                track = QRectF(card.left() + radius, card.bottom() - self.bar_h, card.width() - radius * 2, self.bar_h)
                rounded(painter, QRectF(track.left(), track.top(), track.width() * left, self.bar_h),
                        self.bar_h / 2, self.bar_colors[kind])
        painter.setOpacity(1.0)
