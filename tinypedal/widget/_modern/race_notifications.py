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

Stack of small cards fading out after a few seconds: colored edge & title by kind (gain, loss,
warning, info, best), detail in value font. Nothing drawn while there is no message.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...i18n import tr_overlay as tr
from .._race_aids import HiddenPreview
from ..race_notifications import FADE_STEPS, INFO, PREVIEW_TITLE, TITLES, NotificationsMixin
from .base import LEFT, ModernOverlay
from .draw import accent_edge, panel


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
        pad = unit * 0.45
        self.stripe = max(unit * 0.22, 2.0)
        title_w = max(self.text_width("label", tr(title)) for title in (*TITLES, PREVIEW_TITLE))
        self.detail_w = unit * 10.0
        width = self.stripe + pad * 2 + title_w + unit * 0.6 + self.detail_w
        card_h = unit * 1.75
        gap = unit * 0.25
        self.cards = tuple(QRectF(0, (card_h + gap) * index, width, card_h) for index in range(self.max_toasts))
        self.title_rects = tuple(
            QRectF(card.left() + self.stripe + pad, card.top(), title_w, card_h) for card in self.cards)
        self.detail_rects = tuple(
            QRectF(title.right() + unit * 0.6, card.top(), self.detail_w, card_h)
            for card, title in zip(self.cards, self.title_rects)
        )
        self.set_size(width, (card_h + gap) * self.max_toasts - gap)
        self.kind_colors = (theme.positive, theme.negative, theme.warning, theme.blue, theme.best)
        self.preview = ((tr(PREVIEW_TITLE), "", INFO, FADE_STEPS),)
        self.state = ()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(tuple(
            (tr(message.title), self.elided("value", message.detail, self.detail_w), message.kind, step)
            for message, step in self.read_notifications()
        ))

    def paintEvent(self, event):
        """Draw while a message is shown (or overlay unlocked)"""
        if self.state or self.previewing():
            super().paintEvent(event)

    def paint(self, painter: QPainter):
        theme = self.theme
        shown = self.slot_order(self.state or self.preview)
        radius = self.radius(0.4)
        for index, (title, detail, kind, step) in enumerate(shown, self.first_slot(len(shown))):
            painter.setOpacity(step / FADE_STEPS)
            card = self.cards[index]
            color = self.kind_colors[kind]
            panel(painter, card, theme, radius, self.depth_effects)
            accent_edge(painter, card, color, self.stripe, radius)
            self.draw_text(painter, self.title_rects[index], title, "label", color, LEFT)
            if detail:
                self.draw_text(painter, self.detail_rects[index], detail, "value", theme.text, LEFT)
        painter.setOpacity(1.0)
