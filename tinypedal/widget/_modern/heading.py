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
Heading Widget, modern design

Round dial: compass ring turning with car heading under a fixed mark (north in red, ticks
every 10 degrees), car axis, direction of travel (accent) & front slip angle (orange) lines
from center; yaw angle (car heading to direction of travel) & front slip angle readings in
chips, values in their line color.
"""

from __future__ import annotations

from math import cos, radians, sin

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF

from ...i18n import tr_overlay as tr
from ..heading import HeadingMixin
from .base import CENTER, ModernOverlay
from .draw import disc, rounded

CARDINALS = ((0, "N"), (90, "E"), (180, "S"), (270, "W"))


class Realtime(HeadingMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_size", "show_degree_sign", "decimal_places", "show_yaw_angle_reading",
        "show_slip_angle_reading", "show_yaw_line", "show_direction_line", "show_slip_angle_line", "show_dot",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        self.add_font("cardinal", 0.72, "bold")
        self.add_font("chip", 0.52, "bold", spacing=106, caps=True)
        self.add_font("reading", 0.85, "bold")
        size = max(float(wcfg["display_size"]), unit * 6)
        self.set_size(size, size)
        self.dial = QRectF(0, 0, size, size).adjusted(1, 1, -1, -1)
        self.center = self.dial.center()
        self.outer = self.dial.width() / 2
        self.band = unit * 1.15  # compass ring width
        self.inner = self.outer - self.band
        self.decimals = min(max(int(wcfg["decimal_places"]), 0), 2)
        self.degree = "°" if wcfg["show_degree_sign"] else ""
        self.setup_heading()

        # Compass ticks (turned with heading when drawn)
        self.ticks_minor = QPainterPath()
        self.ticks_major = QPainterPath()
        for angle in range(0, 360, 10):
            major = angle % 30 == 0
            length = unit * (0.42 if major else 0.24)
            path = self.ticks_major if major else self.ticks_minor
            sin_a, cos_a = sin(radians(angle)), cos(radians(angle))
            top = self.outer - unit * 0.18
            path.moveTo(sin_a * top, -cos_a * top)
            path.lineTo(sin_a * (top - length), -cos_a * (top - length))
        self.pen_minor = QPen(theme.tint(theme.text, 70), max(unit * 0.06, 1.0))
        self.pen_major = QPen(theme.tint(theme.text, 150), max(unit * 0.09, 1.2))
        self.cardinal_radius = self.outer - unit * 1.0
        self.cardinal_box = self.metrics["cardinal"].height()

        # Lines from center: car axis (fixed), direction of travel, slip angle (turned)
        width = max(unit * 0.16, 1.5)
        self.lines = []
        for key, color, head, tail in (
            ("show_yaw_line", theme.tint(theme.text, 150), 0.92, 0.25),
            ("show_slip_angle_line", theme.warning, 0.72, 0.2),
            ("show_direction_line", theme.accent, 0.92, 0.25),
        ):
            if wcfg[key]:
                pen = QPen(color, width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                line = QLineF(0, self.inner * tail, 0, -self.inner * head)
                self.lines.append((key, pen, line))

        # Fixed heading mark at top
        mark = unit * 0.38
        top = self.center.y() - self.outer + unit * 0.02
        self.mark = QPolygonF((
            QPointF(self.center.x() - mark, top), QPointF(self.center.x() + mark, top),
            QPointF(self.center.x(), top + mark * 1.15),
        ))

        # Reading chips side by side in lower half: label over value
        sample = f"188.{'8' * self.decimals}" if self.decimals else "188"
        sample += self.degree
        self.chips = []
        readings = [(key, tr(label)) for key, label in (("yaw", "Yaw"), ("slip", "Front slip"))
                    if wcfg[f"show_{'yaw_angle' if key == 'yaw' else 'slip_angle'}_reading"]]
        label_h = unit * 0.62
        value_h = unit * 0.95
        chip_h = label_h + value_h + unit * 0.2
        widths = [max(self.text_width("chip", label), self.text_width("reading", sample)) + unit * 0.6
                  for _, label in readings]
        gap = unit * 0.2
        row_w = sum(widths) + gap * max(len(widths) - 1, 0)
        left = self.center.x() - row_w / 2
        # Below center, corners kept inside compass ring when room allows
        room = (max(self.inner - unit * 0.15, 0) ** 2 - (row_w / 2) ** 2) ** 0.5 if row_w / 2 < self.inner else 0.0
        top = self.center.y() + max(min(self.inner * 0.3, room - chip_h), unit * 0.45)
        for (key, label), width in zip(readings, widths):
            box = QRectF(left, top, width, chip_h)
            label_rect = QRectF(left + unit * 0.3, top + unit * 0.12, width - unit * 0.6, label_h)
            value_rect = QRectF(left + unit * 0.3, label_rect.bottom(), width - unit * 0.6, value_h)
            self.chips.append((key, label, box, label_rect, value_rect))
            left += width + gap

    def timerEvent(self, event):
        """Update when vehicle on track"""
        heading = round(self.read_heading(), 1)
        yaw = round(self.display_yaw_angle(self.yaw_angle), 1)
        slip = round(self.slip_angle, 1)
        self.refresh((heading, round(self.yaw_angle, 1), yaw, slip))

    def paint_static(self, painter: QPainter):
        theme = self.theme
        disc(painter, self.dial, theme, self.depth_effects)
        face = self.dial.adjusted(self.band, self.band, -self.band, -self.band)
        disc(painter, face, theme, False, theme.tint(theme.surface_alt, 230))

    def paint(self, painter: QPainter):
        theme = self.theme
        heading, direction, yaw, slip = self.state
        center = self.center
        # Compass ring turned by heading
        painter.save()
        painter.translate(center)
        painter.rotate(heading)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen_minor)
        painter.drawPath(self.ticks_minor)
        painter.setPen(self.pen_major)
        painter.drawPath(self.ticks_major)
        painter.restore()
        side = self.cardinal_box
        for angle, letter in CARDINALS:
            turned = radians(angle + heading)
            pos = QPointF(center.x() + sin(turned) * self.cardinal_radius, center.y() - cos(turned) * self.cardinal_radius)
            rect = QRectF(pos.x() - side / 2, pos.y() - side / 2, side, side)
            color = theme.negative if letter == "N" else theme.text
            self.draw_text(painter, rect, letter, "cardinal", color, CENTER, elide=False)
        # Fixed heading mark
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.accent)
        painter.drawPolygon(self.mark)
        # Lines from center
        angles = {"show_yaw_line": 0.0, "show_direction_line": direction, "show_slip_angle_line": slip}
        for key, pen, line in self.lines:
            painter.save()
            painter.translate(center)
            painter.rotate(angles[key])
            painter.setPen(pen)
            painter.drawLine(line)
            painter.restore()
        if self.wcfg["show_dot"]:
            dot = max(self.unit * 0.26, 2.5)
            painter.setPen(QPen(theme.surface, max(self.unit * 0.08, 1.0)))
            painter.setBrush(theme.text)
            painter.drawEllipse(center, dot, dot)
        # Readings
        for key, label, box, label_rect, value_rect in self.chips:
            rounded(painter, box, self.radius(0.35), theme.tint(theme.surface, 225))
            self.draw_text(painter, label_rect, label, "chip", theme.text_muted, CENTER)
            if key == "yaw":
                text, color = self.angle_text(yaw), theme.accent
            else:
                text, color = self.angle_text(slip), theme.warning
            self.draw_text(painter, value_rect, text, "reading", color, CENTER)

    def angle_text(self, angle: float) -> str:
        """Angle reading (absolute)"""
        return f"{abs(angle):.{self.decimals}f}{self.degree}"
