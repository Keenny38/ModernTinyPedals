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
Telemetry comparison Widget, modern design

Charts along a distance window around car: reference lap of lap telemetry viewer as soft area & faint
line (also ahead of car), current lap as bright line up to car mark. Header: reference lap time, speed
difference & time delta to reference at car position.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from ...i18n import tr_overlay as tr
from ..telemetry_compare import CENTERED_CHANNELS, PANEL_LABELS, TelemetryCompareMixin, delta_limit, shown_panels
from .base import LEFT, RIGHT, ModernOverlay
from .draw import panel, rounded

CHANNEL_COLORS = {  # theme color of each channel
    "speed_kph": "accent", "throttle": "positive", "brake": "negative", "steering": "warning", "gear": "text",
}
FILLED_CHANNELS = ("speed_kph", "throttle", "brake")  # reference lap drawn as area under its line


class Realtime(TelemetryCompareMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_width", "display_height", "distance_behind", "distance_ahead", "reference_lap_source",
        "decimal_places", "show_reference_lap_time", "show_delta", "show_speed_difference", "show_speed",
        "show_throttle", "show_brake", "show_steering", "show_gear",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        pad = unit * 0.35
        gap = unit * 0.2
        inset = unit * 0.15
        self.show_reference_info = bool(wcfg["show_reference_lap_time"])
        self.show_delta = bool(wcfg["show_delta"])
        self.show_speed_difference = bool(wcfg["show_speed_difference"])
        width = max(float(wcfg["display_width"]), unit * 8)
        height = max(float(wcfg["display_height"]), unit * 1.5)
        header_h = unit * 1.3 if self.show_reference_info or self.show_delta or self.show_speed_difference else 0.0
        self.rect_header = QRectF(pad + unit * 0.2, pad, width - unit * 0.4, header_h)
        top = pad + header_h + (unit * 0.15 if header_h else 0.0)
        self.boxes: dict[str, QRectF] = {}  # panel background
        panels = []
        for key, share, channels in shown_panels(wcfg):
            box = QRectF(pad, top, width, max(height * share, unit * 1.2))
            self.boxes[key] = box
            panels.append((key, box.adjusted(0, inset, 0, -inset), channels))
            top = box.bottom() + gap
        self.setup_compare(pad, width, panels)
        self.set_size(width + pad * 2, top - gap + pad)

        limit = delta_limit(self.decimals)  # widest delta once rounded
        self.delta_w = self.text_width("value", self.widest("value", (
            "+88." + "8" * self.decimals if self.decimals else "+88", f"{limit:+.{self.decimals}f}",
            f"{-limit:+.{self.decimals}f}")))
        self.speed_w = self.text_width("small", f"+888 {self.speed_symbol}")
        self.ref_label = tr("Ref")
        self.ref_label_w = self.text_width("label", self.ref_label) + unit * 0.3
        readings_w = ((self.delta_w + unit * 0.5 if self.show_delta else 0.0)
                      + (self.speed_w + unit * 0.5 if self.show_speed_difference else 0.0))
        self.rect_reference = self.rect_header.adjusted(0, 0, -readings_w, 0)

        line_w = max(unit * 0.09, 1.2)
        colors = {channel: getattr(theme, color) for channel, color in CHANNEL_COLORS.items()}
        self.pens_current = {channel: QPen(color, line_w) for channel, color in colors.items()}
        self.pens_reference = {channel: QPen(theme.tint(color, 130), line_w * 0.8) for channel, color in colors.items()}
        self.fills = {channel: theme.tint(colors[channel], 50) for channel in FILLED_CHANNELS}
        self.pen_mark = QPen(theme.tint(theme.text, 190), max(unit * 0.07, 1.0))
        self.chart_clip = QRectF(self.chart_left, 0, self.chart_right - self.chart_left, self.height())
        self.panel_labels = {key: tr(PANEL_LABELS[key]) for key in self.boxes}
        self.label_rects = {
            key: QRectF(box.left() + unit * 0.25, box.top() + unit * 0.1, box.width() - unit * 0.5, unit * 0.75)
            for key, box in self.boxes.items()
        }
        self.state = (None, None, None)  # drawn before first update too (labels, preview)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(self.read_compare())

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for box in self.boxes.values():
            rounded(painter, box, self.radius(0.3), theme.tint(theme.surface_alt, 200))
        for channel in CENTERED_CHANNELS:
            rect = self.channel_rects.get(channel)
            if rect is not None:
                painter.fillRect(QRectF(rect.left(), rect.center().y() - 0.5, rect.width(), 1), theme.tint(theme.text, 50))

    def paint(self, painter: QPainter):
        theme = self.theme
        painter.save()
        painter.setClipRect(self.chart_clip)
        self.draw_reference(painter)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for channel, line in self.lines:
            painter.setPen(self.pens_current[channel])
            painter.drawPolyline(line)
        painter.restore()
        painter.setPen(self.pen_mark)
        for box in self.boxes.values():
            painter.drawLine(QPointF(self.car_x, box.top()), QPointF(self.car_x, box.bottom()))
        for key, rect in self.label_rects.items():  # over charts: readable on reference areas
            self.draw_text(painter, rect, self.panel_labels[key], "label", theme.text_muted, LEFT)
        self.paint_header(painter, theme)

    def paint_header(self, painter: QPainter, theme):
        header = self.rect_header
        if not header.height():
            return
        if self.show_reference_info:
            left = self.rect_reference
            if self.reference is None:
                self.draw_text(painter, left, tr("No reference lap"), "label", theme.text_muted, LEFT)
            else:
                self.draw_text(painter, left, self.ref_label, "label", theme.text_muted, LEFT)
                rect = left.adjusted(self.ref_label_w, 0, 0, 0)
                self.draw_text(painter, rect, self.reference_laptime(), "dim", theme.text_dim, LEFT)
        _, delta, speed_difference = self.state
        right = header.right()
        if self.show_delta:
            color = theme.text
            if delta:
                color = theme.negative if delta > 0 else theme.positive
            rect = QRectF(right - self.delta_w, header.top(), self.delta_w, header.height())
            self.draw_text(painter, rect, self.delta_text(delta), "value", color, RIGHT, elide=False)
            right = rect.left() - self.unit * 0.5
        if self.show_speed_difference:
            color = theme.text_dim
            if speed_difference:
                color = theme.positive if speed_difference > 0 else theme.negative
            rect = QRectF(right - self.speed_w, header.top(), self.speed_w, header.height())
            self.draw_text(painter, rect, self.speed_text(speed_difference), "small", color, RIGHT, elide=False)
