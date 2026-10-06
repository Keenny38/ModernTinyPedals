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
Instrument Widget, modern design

Row (or column) of indicator tiles, icons drawn as shapes: headlights (green while on),
ignition (lit while on, amber tile while engine stalled), clutch (lit with auto clutch, accent
tile while pressed), wheel lock (red tile) & wheel slip (orange tile) while over threshold.
Off indicators stay dim.
"""

from __future__ import annotations

from math import cos, pi, sin
from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from ...api_control import api
from ..instrument import InstrumentMixin
from .base import ModernOverlay, display_order_options
from .draw import panel, readable_on, rounded

ITEMS = ("headlights", "ignition", "clutch", "wheel_lock", "wheel_slip")


class Light(NamedTuple):
    """Indicator state of one update"""

    lit: bool  # icon bright
    fill: QColor | None = None  # tile color while warning
    icon: QColor | None = None  # icon color while lit (default: text)


class Realtime(InstrumentMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "layout", "icon_size", "show_headlights", "show_ignition", "stalling_rpm_threshold", "show_clutch",
        "show_wheel_lock", "wheel_lock_threshold", "show_wheel_slip", "wheel_slip_threshold",
        *display_order_options("instrument"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.keys = tuple(self.display_ordered([key for key in ITEMS if wcfg[f"show_{key}"]], key=str))
        tile = max(float(wcfg["icon_size"]), 16.0)
        pad = unit * 0.25
        gap = unit * 0.2
        horizontal = wcfg["layout"] != 0
        self.tiles = []
        for index in range(len(self.keys)):
            offset = pad + index * (tile + gap)
            self.tiles.append(QRectF(offset, pad, tile, tile) if horizontal else QRectF(pad, offset, tile, tile))
        count = max(len(self.keys), 1)
        length = pad * 2 + count * tile + (count - 1) * gap
        if horizontal:
            self.set_size(length, tile + pad * 2)
        else:
            self.set_size(tile + pad * 2, length)
        self.stroke = max(tile * 0.075, 1.2)

    def design_unit(self) -> float:
        """Icon size option sets size"""
        return max(float(self.wcfg["icon_size"]), 16.0) * 0.5

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        lights = []
        for key in self.keys:
            if key == "headlights":
                lights.append(Light(bool(api.read.switch.headlights()), icon=theme.positive))
            elif key == "ignition":
                ignition = self.read_ignition()
                lights.append(Light(ignition > 0, theme.warning if ignition == 1 else None))
            elif key == "clutch":
                clutch = self.read_clutch()
                lights.append(Light(clutch >= 2, theme.accent if clutch % 2 else None))
            elif key == "wheel_lock":
                locking = self.wheel_locking()
                lights.append(Light(locking, theme.negative if locking else None))
            else:
                slipping = self.wheel_slipping()
                lights.append(Light(slipping, theme.orange if slipping else None))
        self.refresh(tuple(lights))

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)

    def paint(self, painter: QPainter):
        theme = self.theme
        radius = self.radius(0.35)
        for key, rect, light in zip(self.keys, self.tiles, self.state):
            if light.fill is not None:
                rounded(painter, rect, radius, light.fill)
                color = readable_on(light.fill)
            else:
                rounded(painter, rect, radius, theme.tint(theme.surface_alt, 200))
                color = (light.icon or theme.text) if light.lit else theme.text_faint
            ICONS[key](painter, rect.adjusted(rect.width() * 0.18, rect.height() * 0.18,
                                              -rect.width() * 0.18, -rect.height() * 0.18), color, self.stroke)


# Icons, drawn in square rect
def stroke_pen(color: QColor, width: float) -> QPen:
    """Icon line pen, round ends"""
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def icon_headlights(painter: QPainter, rect: QRectF, color: QColor, width: float):
    """Lamp (half disc on right) with beams to left"""
    side = rect.width()
    cy = rect.center().y()
    lamp_x = rect.left() + side * 0.5
    half_h = side * 0.36
    lamp = QPainterPath()
    lamp.moveTo(lamp_x, cy - half_h)
    lamp.cubicTo(lamp_x + side * 0.62, cy - half_h, lamp_x + side * 0.62, cy + half_h, lamp_x, cy + half_h)
    lamp.closeSubpath()
    painter.setPen(stroke_pen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(lamp)
    right = lamp_x - side * 0.12
    left = rect.left() + side * 0.02
    for offset in (-0.5, 0.0, 0.5):
        y = cy + half_h * offset
        painter.drawLine(QPointF(left, y + side * 0.06), QPointF(right, y))


def icon_ignition(painter: QPainter, rect: QRectF, color: QColor, width: float):
    """Power symbol: ring open at top, bar through gap"""
    side = rect.width()
    center = rect.center()
    radius = side * 0.4
    painter.setPen(stroke_pen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ring = QRectF(center.x() - radius, center.y() - radius + side * 0.05, radius * 2, radius * 2)
    painter.drawArc(ring, 125 * 16, 290 * 16)
    painter.drawLine(QPointF(center.x(), rect.top() + side * 0.02), QPointF(center.x(), center.y()))


def icon_clutch(painter: QPainter, rect: QRectF, color: QColor, width: float):
    """Cog wheel with center hole"""
    side = rect.width()
    center = rect.center()
    outer = side * 0.48
    root = side * 0.34
    teeth = 8
    path = QPainterPath()
    for index in range(teeth * 4):
        angle = index / (teeth * 4) * 2 * pi
        radius = outer if index % 4 in (1, 2) else root
        point = QPointF(center.x() + cos(angle) * radius, center.y() + sin(angle) * radius)
        if index:
            path.lineTo(point)
        else:
            path.moveTo(point)
    path.closeSubpath()
    hole = side * 0.15
    path.addEllipse(center, hole, hole)
    path.setFillRule(Qt.FillRule.OddEvenFill)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)


def icon_wheel_lock(painter: QPainter, rect: QRectF, color: QColor, width: float):
    """Brake warning: ring with exclamation mark, arcs both sides"""
    side = rect.width()
    center = rect.center()
    radius = side * 0.3
    painter.setPen(stroke_pen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(center, radius, radius)
    outer = side * 0.48
    arcs = QRectF(center.x() - outer, center.y() - outer, outer * 2, outer * 2)
    painter.drawArc(arcs, 140 * 16, 80 * 16)
    painter.drawArc(arcs, -40 * 16, 80 * 16)
    painter.drawLine(QPointF(center.x(), center.y() - radius * 0.55), QPointF(center.x(), center.y() + radius * 0.12))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    dot = width * 0.62
    painter.drawEllipse(QPointF(center.x(), center.y() + radius * 0.5), dot, dot)


def icon_wheel_slip(painter: QPainter, rect: QRectF, color: QColor, width: float):
    """Skid marks: two waves"""
    side = rect.width()
    painter.setPen(stroke_pen(color, width))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    top = rect.top() + side * 0.04
    bottom = rect.bottom() - side * 0.04
    swing = side * 0.13
    for x in (rect.left() + side * 0.3, rect.left() + side * 0.7):
        path = QPainterPath(QPointF(x, top))
        third = (bottom - top) / 3
        path.cubicTo(x + swing, top + third * 0.5, x + swing, top + third, x, top + third * 1.5)
        path.cubicTo(x - swing, top + third * 2, x - swing, top + third * 2.5, x, bottom)
        painter.drawPath(path)


ICONS = {
    "headlights": icon_headlights,
    "ignition": icon_ignition,
    "clutch": icon_clutch,
    "wheel_lock": icon_wheel_lock,
    "wheel_slip": icon_wheel_slip,
}
