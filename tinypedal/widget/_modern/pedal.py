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
Pedal Widget, modern design

One capsule gauge per input (force feedback, clutch, brake, throttle): filled to filtered input
with a soft gradient, raw input as a bright tick, optional reading, short label under.
Force feedback turns orange while clipping.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter

from ...api_control import api
from .base import CENTER, ModernOverlay
from .draw import panel, rounded

PEDALS = (  # key, label, theme color
    ("ffb", "FFB", "text_muted"),
    ("clutch", "C", "accent"),
    ("brake", "B", "negative"),
    ("throttle", "T", "positive"),
)


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "enable_horizontal_style", "bar_length", "bar_width_unfiltered", "bar_width_filtered",
        "show_readings", "show_throttle", "show_throttle_filtered", "show_brake", "show_brake_filtered",
        "show_brake_pressure", "show_clutch", "show_clutch_filtered", "show_ffb_meter",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        shown = {
            "ffb": wcfg["show_ffb_meter"], "clutch": wcfg["show_clutch"],
            "brake": wcfg["show_brake"], "throttle": wcfg["show_throttle"],
        }
        self.keys = tuple(key for key, _, _ in PEDALS if shown[key])
        self.colors = {key: getattr(self.theme, color) for key, _, color in PEDALS}
        self.labels = {key: label for key, label, _ in PEDALS}
        self.horizontal = wcfg["enable_horizontal_style"]
        self.show_readings = wcfg["show_readings"]
        self.max_brake_pressure = 1.0
        length = max(float(wcfg["bar_length"]), 10.0)
        thickness = max(float(wcfg["bar_width_unfiltered"]) + float(wcfg["bar_width_filtered"]), 4.0)
        pad = unit * 0.35
        gap = unit * 0.45
        label = unit * 1.0
        reading = unit * 1.0 if self.show_readings else 0.0
        count = len(self.keys)
        self.rects: dict[str, tuple[QRectF, QRectF, QRectF]] = {}  # track, label, reading
        if self.horizontal:
            label_w = self.text_width("label", "FFB") + unit * 0.3
            reading_w = self.text_width("small", "100") + unit * 0.3 if self.show_readings else 0.0
            row = max(thickness, unit * 1.0)
            for index, key in enumerate(self.keys):
                top = pad + index * (row + gap)
                label_rect = QRectF(pad, top, label_w, row)
                track = QRectF(label_rect.right() + unit * 0.2, top + (row - thickness) / 2, length, thickness)
                reading_rect = QRectF(track.right() + unit * 0.2, top, reading_w, row)
                self.rects[key] = (track, label_rect, reading_rect)
            width = pad * 2 + label_w + unit * 0.2 + length + (unit * 0.2 + reading_w if reading_w else 0)
            height = pad * 2 + count * row + max(count - 1, 0) * gap
        else:
            column = max(thickness, self.text_width("label", "FFB") + unit * 0.2)
            for index, key in enumerate(self.keys):
                left = pad + index * (column + gap)
                reading_rect = QRectF(left, pad, column, reading)
                track = QRectF(left + (column - thickness) / 2, pad + reading, thickness, length)
                label_rect = QRectF(left, track.bottom() + unit * 0.15, column, label)
                self.rects[key] = (track, label_rect, reading_rect)
            width = pad * 2 + count * column + max(count - 1, 0) * gap
            height = pad * 2 + reading + length + unit * 0.15 + label
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for key in self.keys:
            track, label, _ = self.rects[key]
            rounded(painter, track, min(track.width(), track.height()) / 2, theme.surface_raised)
            self.draw_text(painter, label, self.labels[key], "label", theme.text_muted, CENTER, elide=False)

    def paint(self, painter: QPainter):
        theme = self.theme
        for key, (filtered, raw) in zip(self.keys, self.state):
            track, _, reading = self.rects[key]
            color = self.colors[key]
            if key == "ffb" and filtered >= 1:
                color = theme.warning
            self.draw_fill(painter, track, min(max(filtered, 0.0), 1.0), color)
            self.draw_tick(painter, track, min(max(raw, 0.0), 1.0))
            if self.show_readings:
                self.draw_text(painter, reading, f"{filtered * 100:.0f}", "small", theme.text_dim, CENTER, elide=False)

    def draw_fill(self, painter: QPainter, track: QRectF, value: float, color: QColor):
        """Filled part of capsule, brighter toward input end"""
        if value <= 0:
            return
        radius = min(track.width(), track.height()) / 2
        if self.horizontal:
            fill = QRectF(track.left(), track.top(), track.width() * value, track.height())
            gradient = QLinearGradient(fill.left(), 0, fill.right(), 0)
        else:
            height = track.height() * value
            fill = QRectF(track.left(), track.bottom() - height, track.width(), height)
            gradient = QLinearGradient(0, fill.bottom(), 0, fill.top())
        gradient.setColorAt(0.0, color.darker(125))
        gradient.setColorAt(1.0, color.lighter(115))
        rounded(painter, fill, min(radius, min(fill.width(), fill.height()) / 2), QBrush(gradient))

    def draw_tick(self, painter: QPainter, track: QRectF, value: float):
        """Raw input mark"""
        size = max(self.unit * 0.12, 2.0)
        if self.horizontal:
            x = track.left() + (track.width() - size) * value
            tick = QRectF(x, track.top() - size, size, track.height() + size * 2)
        else:
            y = track.bottom() - size - (track.height() - size) * value
            tick = QRectF(track.left() - size, y, track.width() + size * 2, size)
        rounded(painter, tick, size / 2, self.theme.text)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        inputs = api.read.inputs
        values = []
        for key in self.keys:
            if key == "throttle":
                raw = inputs.throttle_raw()
                values.append((inputs.throttle() if wcfg["show_throttle_filtered"] else raw, raw))
            elif key == "brake":
                raw = inputs.brake_raw()
                if not wcfg["show_brake_filtered"]:
                    filtered = raw
                elif wcfg["show_brake_pressure"]:
                    pressure = sum(api.read.brake.pressure())
                    self.max_brake_pressure = max(self.max_brake_pressure, pressure)
                    filtered = pressure / self.max_brake_pressure
                else:
                    filtered = inputs.brake()
                values.append((filtered, raw))
            elif key == "clutch":
                raw = inputs.clutch_raw()
                values.append((inputs.clutch() if wcfg["show_clutch_filtered"] else raw, raw))
            else:
                ffb = abs(inputs.force_feedback())
                values.append((ffb, ffb))
        self.refresh(tuple((round(filtered, 3), round(raw, 3)) for filtered, raw in values))
