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
Corner coach Widget, modern design

Card with one row per part: next corner (name & distance to apex), braking (distance to reference braking point,
then braked on point, early or late, colored), apex (last corner driven: minimum speed & difference to reference
lap in gain or loss color). "No reference lap" across the card while track has no recorded lap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from ..corner_coach import BRAKE_EARLY, BRAKE_LATE, BRAKE_NOW, BRAKE_ON_POINT, CoachView, CornerCoachMixin
from .base import CENTER, LEFT, RIGHT, ModernOverlay
from .draw import panel, rounded

if TYPE_CHECKING:
    from ...template.widget_config_types import CornerCoachConfig


class Realtime(CornerCoachMixin, ModernOverlay):
    """Draw widget"""

    wcfg: CornerCoachConfig

    options = (
        "font_size", "reference_lap_source", "show_next_corner", "show_braking_point", "show_apex_speed",
        "braking_point_tolerance",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.setup_coach()
        unit = self.unit
        pad = unit * 0.35
        row_h = unit * 1.35
        gap = unit * 0.15
        self.caption_w = max(self.text_width("label", caption) for caption in self.captions.values()) + unit * 0.6
        self.speed_w = self.text_width("small", f"888 {self.speed_symbol}")
        self.delta_w = self.text_width("value", "+88")
        width = max(unit * 11.5, self.caption_w + self.speed_w + self.delta_w + unit * 4)
        self.boxes: dict[str, QRectF] = {}
        top = pad
        for row in self.rows:
            self.boxes[row] = QRectF(pad, top, width, row_h)
            top += row_h + gap
        self.status_box = QRectF(pad, pad, width, top - gap - pad)
        self.set_size(width + pad * 2, top - gap + pad)
        self.state = CoachView()  # drawn before first update too (preview)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(self.read_coach())

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.panel_radius(), self.depth_effects)
        for box in self.boxes.values():
            rounded(painter, box, self.radius(0.3), theme.tint(theme.surface_alt, 200))

    def paint(self, painter: QPainter):
        theme = self.theme
        state = self.state
        if state.status:
            rounded(painter, self.status_box, self.radius(0.3), theme.tint(theme.surface_alt, 230))
            self.draw_text(painter, self.status_box, state.status, "small", theme.text_muted, CENTER)
            return
        inset = self.unit * 0.3
        for row, box in self.boxes.items():
            inner = box.adjusted(inset, 0, -inset, 0)
            self.draw_text(painter, inner, self.captions[row], "label", theme.text_muted, LEFT)
            body = inner.adjusted(self.caption_w, 0, 0, 0)
            if row == "next":
                distance_w = self.advance("value", state.distance) + self.unit * 0.4  # cached
                self.draw_text(painter, body, state.distance, "value", theme.text, RIGHT, elide=False)
                self.draw_text(painter, body.adjusted(0, 0, -distance_w, 0), state.corner, "strong", theme.text, LEFT)
            elif row == "brake":
                self.draw_text(painter, body, state.brake, "value", self.brake_color(state.brake_kind), RIGHT)
            elif state.apex_speed:
                delta = QRectF(body.right() - self.delta_w, body.top(), self.delta_w, body.height())
                speed = QRectF(delta.left() - self.unit * 0.35 - self.speed_w, body.top(), self.speed_w, body.height())
                self.draw_text(painter, delta, state.apex_delta, "value", self.gain_color(state.apex_gain), RIGHT,
                               elide=False)
                self.draw_text(painter, speed, state.apex_speed, "small", theme.text_dim, RIGHT, elide=False)
                self.draw_text(painter, body.adjusted(0, 0, -(body.right() - speed.left()) - self.unit * 0.3, 0),
                               state.apex_corner, "dim", theme.text, LEFT)

    def brake_color(self, kind: str) -> QColor:
        theme = self.theme
        if kind == BRAKE_ON_POINT:
            return theme.positive
        if kind in (BRAKE_NOW, BRAKE_EARLY, BRAKE_LATE):  # as classic design (warning color)
            return theme.warning
        return theme.text

    def gain_color(self, gain: int) -> QColor:
        theme = self.theme
        if gain > 0:
            return theme.positive
        if gain < 0:
            return theme.negative
        return theme.text
