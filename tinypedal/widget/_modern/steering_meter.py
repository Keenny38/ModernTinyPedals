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
Steering meter Widget, modern design

Track with a center mark: bar grows from center toward steering side, bright thumb at wheel
position, faint ticks every scale mark degrees of wheel rotation; steering angle written on
the other half (never under the bar).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from .base import LEFT, RIGHT, ModernOverlay
from .draw import panel, rounded

FILL_ALPHA = 120  # bar from center to thumb


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "bar_width", "bar_height", "show_steering_angle", "manual_steering_range", "show_scale_mark",
        "scale_mark_degree",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        pad = unit * 0.3
        text_pad = unit * 0.35
        self.show_angle = bool(wcfg["show_steering_angle"])
        half = max(float(wcfg["bar_width"]), unit * 1.5)
        if self.show_angle:  # angle fits the half bar it is written on
            half = max(half, self.text_width("value", "888°") + text_pad * 2)
        height = max(float(wcfg["bar_height"]), unit * 1.15 if self.show_angle else unit * 0.5)
        self.track = QRectF(pad, pad, half * 2, height)
        self.set_size(half * 2 + pad * 2, height + pad * 2)
        self.thumb_w = max(unit * 0.2, 2.0)
        self.text_rects = (  # angle written on left half (steering right), else right half
            self.track.adjusted(text_pad, 0, -half - text_pad, 0),
            self.track.adjusted(half + text_pad, 0, -text_pad, 0),
        )
        self.color_fill = theme.tint(theme.accent, FILL_ALPHA)
        self.rot_range = 0.0
        self.mark_gap = 0.0  # pixels between scale marks, 0: none

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.4), self.depth_effects)
        track = self.track
        rounded(painter, track, self.radius(0.25), theme.surface_alt)
        center = track.center().x()
        gap = self.mark_gap
        if gap >= 3:  # ticks at top & bottom of track, every scale mark degrees
            tick_h = max(track.height() * 0.22, 2.0)
            color = theme.text_faint
            offset = gap
            while offset < track.width() / 2 - 1:
                for x in (center - offset, center + offset):
                    painter.fillRect(QRectF(round(x) - 0.5, track.top(), 1, tick_h), color)
                    painter.fillRect(QRectF(round(x) - 0.5, track.bottom() - tick_h, 1, tick_h), color)
                offset += gap
        painter.fillRect(QRectF(round(center) - 0.5, track.top(), 1, track.height()), theme.text_muted)

    def paint(self, painter: QPainter):
        theme = self.theme
        position, angle = self.state
        track = self.track
        center = track.center().x()
        x = center + position * track.width() / 2
        if abs(x - center) >= 1:
            fill = QRectF(min(x, center), track.top(), abs(x - center), track.height())
            rounded(painter, fill, 0, self.color_fill)
        thumb = QRectF(x - self.thumb_w / 2, track.top(), self.thumb_w, track.height())
        rounded(painter, thumb.intersected(track), self.thumb_w / 2, theme.accent)
        if angle:
            right_turn = position > 0
            self.draw_text(painter, self.text_rects[0 if right_turn else 1], angle, "value", theme.text,
                           LEFT if right_turn else RIGHT)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        if wcfg["manual_steering_range"] > 0:
            rot_range = float(wcfg["manual_steering_range"])
        else:
            rot_range = float(api.read.inputs.steering_range_physical())
        if rot_range != self.rot_range:
            self.rot_range = rot_range
            gap = 0.0
            if wcfg["show_scale_mark"] and rot_range > 0:
                gap = max(float(wcfg["scale_mark_degree"]), 10.0) / (rot_range / 2) * self.track.width() / 2
            if gap != self.mark_gap:
                self.mark_gap = gap
                self.redraw_static()
        raw = calc.sym_max(api.read.inputs.steering_raw(), 1.0)
        angle = f"{abs(raw * rot_range / 2):.0f}°" if self.show_angle else ""
        self.refresh((round(raw, 3), angle))
