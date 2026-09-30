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
Black box widget, headlights & engine status icons between front and rear wheels
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient

from .common import qcolor


def headlight_path(box: QRectF) -> tuple[QPainterPath, list[tuple[QPointF, QPointF]]]:
    """Low beam symbol: lamp dome facing right, beams on the left slanting down"""
    w, h = box.width(), box.height()
    lamp = QPainterPath()
    flat_x = box.left() + w * 0.42
    lamp.moveTo(flat_x, box.top() + h * 0.12)
    lamp.cubicTo(box.right() + w * 0.02, box.top() + h * 0.08,
                 box.right() + w * 0.02, box.bottom() - h * 0.08,
                 flat_x, box.bottom() - h * 0.12)
    lamp.closeSubpath()
    beams = []
    for step in range(4):
        y = box.top() + h * (0.2 + step * 0.2)
        beams.append((QPointF(flat_x - w * 0.1, y), QPointF(box.left(), y + h * 0.12)))
    return lamp, beams


def engine_path(box: QRectF) -> QPainterPath:
    """Engine block outline (check engine style): cap, block, side intake & exhaust"""
    w, h = box.width(), box.height()
    x, y = box.left(), box.top()
    points = (
        (0.30, 0.10), (0.62, 0.10), (0.62, 0.22), (0.50, 0.22), (0.50, 0.30),
        (0.78, 0.30), (0.86, 0.42), (0.94, 0.42), (0.94, 0.34), (1.00, 0.34),
        (1.00, 0.80), (0.94, 0.80), (0.94, 0.70), (0.86, 0.70), (0.76, 0.90),
        (0.22, 0.90), (0.14, 0.74), (0.06, 0.74), (0.06, 0.84), (0.00, 0.84),
        (0.00, 0.44), (0.06, 0.44), (0.06, 0.56), (0.14, 0.56), (0.14, 0.30),
        (0.40, 0.30), (0.40, 0.22), (0.30, 0.22),
    )
    path = QPainterPath()
    path.moveTo(x + points[0][0] * w, y + points[0][1] * h)
    for px, py in points[1:]:
        path.lineTo(x + px * w, y + py * h)
    path.closeSubpath()
    return path


class StatusPainter:
    """Headlights & engine icons stacked between front and rear wheels, on one side"""

    def side_gap(self, right: bool) -> QRectF:
        """Free room between front and rear wheel on one side (null if too small)"""
        front, rear = (1, 3) if right else (0, 2)
        rects = [rect for index in (front, rear)
                 for rect in (self.rects_tyre[index], self.rects_disc[index], self.rects_susp[index])
                 if not rect.isNull()]
        if not rects:
            return QRectF()
        left = min(rect.left() for rect in rects)
        width = max(rect.right() for rect in rects) - left
        margin = self.unit * 0.25
        top = self.rects_tyre[front].bottom() + margin
        bottom = self.rects_tyre[rear].top() - margin
        if bottom - top < self.unit * 1.2:
            return QRectF()
        return QRectF(left, top, width, bottom - top)

    def draw_status_icons(self, painter: QPainter):
        """Both icons stacked in one side gap: headlights on top, engine below"""
        wcfg = self.wcfg
        show_lights = wcfg["show_headlights_indicator"]
        show_engine = wcfg["show_engine_status"]
        if not self.rects_tyre or not (show_lights or show_engine):
            return
        gap = self.side_gap(wcfg["status_icons_side"] == "Right")
        if gap.isNull():
            return
        unit = self.unit
        size = min(gap.width() * 0.5, unit * 1.2 * max(wcfg["status_icon_scale"], 0.2))
        row_h = unit * 0.5
        spacing = unit * 0.3
        # Heights: lights icon, engine icon + text rows (2 temperatures, or 1 state text)
        engine_rows = 2 if self.ignition == 2 else 1
        blocks = []
        if show_lights:
            blocks.append(("lights", size))
        if show_engine:
            blocks.append(("engine", size + row_h * engine_rows + unit * 0.1))
        total = sum(height for _, height in blocks) + spacing * (len(blocks) - 1)
        scale = min(gap.height() / total, 1) if total else 1
        top = gap.top() + (gap.height() - total * scale) / 2
        for name, height in blocks:
            icon = size * scale
            box = QRectF(gap.center().x() - icon / 2, top, icon, icon)
            if name == "lights":
                self.draw_headlights_icon(painter, box)
            else:
                self.draw_engine_icon(painter, box, QRectF(gap.left(), box.bottom() + unit * 0.1 * scale,
                                                           gap.width(), row_h * scale))
            top += (height + spacing) * scale

    def draw_icon_glow(self, painter: QPainter, box: QRectF, color: str):
        """Soft radial halo behind a lit icon"""
        halo = QColor(color)
        gradient = QRadialGradient(box.center(), box.width() * 0.75)
        halo.setAlpha(90)
        gradient.setColorAt(0.0, halo)
        halo.setAlpha(0)
        gradient.setColorAt(1.0, halo)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        pad = box.width() * 0.3
        painter.drawEllipse(box.adjusted(-pad, -pad, pad, pad))

    def draw_headlights_icon(self, painter: QPainter, box: QRectF):
        wcfg = self.wcfg
        on = self.headlights
        color = wcfg["headlights_active_color"] if on else wcfg["indicator_inactive_color"]
        painter.save()
        if on:
            self.draw_icon_glow(painter, box, color)
        lamp, beams = headlight_path(box)
        stroke = max(box.width() * 0.09, 1.5)
        pen = QPen(qcolor(color), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(qcolor(color) if on else Qt.BrushStyle.NoBrush)
        painter.drawPath(lamp)
        for start, end in beams:
            painter.drawLine(start, end)
        painter.restore()

    def engine_color(self) -> str:
        wcfg = self.wcfg
        if self.ignition == 0:
            return wcfg["engine_off_color"]
        if self.ignition == 1:
            return wcfg["engine_ignition_color"]
        if self.engine_hot():
            return wcfg["engine_warning_color"]
        return wcfg["engine_running_color"]

    def engine_hot(self) -> bool:
        wcfg = self.wcfg
        return (self.oil_temp >= wcfg["engine_oil_warning_temperature"]
                or self.water_temp >= wcfg["engine_water_warning_temperature"])

    def draw_engine_icon(self, painter: QPainter, box: QRectF, row: QRectF):
        """Engine icon in box, state text or oil & water temperatures in rows from row"""
        wcfg = self.wcfg
        color = self.engine_color()
        running = self.ignition == 2
        painter.save()
        if self.engine_hot() and running or self.ignition == 1:
            self.draw_icon_glow(painter, box, color)
        stroke = max(box.width() * 0.08, 1.2)
        painter.setPen(QPen(qcolor(color), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        fill = QColor(color)
        fill.setAlpha(60 if running else 0)
        painter.setBrush(fill)
        painter.drawPath(engine_path(box))
        painter.restore()
        if not running:
            painter.setPen(qcolor(color))
            text = self.text["engine_off"] if self.ignition == 0 else self.text["ignition"]
            self.draw_fit_text(painter, row, text, self.font_label)
            return
        for label, value, warning in (
            (self.text["oil"], self.oil_temp, wcfg["engine_oil_warning_temperature"]),
            (self.text["water"], self.water_temp, wcfg["engine_water_warning_temperature"]),
        ):
            painter.setPen(qcolor(wcfg["engine_warning_color"]) if value >= warning else self.pen_text)
            self.draw_fit_text(painter, row, f"{label} {self.unit_temp(value):.0f}{self.sign_text}", self.font_label)
            row = row.translated(0, row.height())
