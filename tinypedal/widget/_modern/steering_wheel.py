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
Steering wheel Widget, modern design

Steering wheel drawn as shapes on a round dial (or custom wheel image), turned by steering
input: rim with top center stripe, three spokes, hub. Rotation arc from top around the rim
(while stationary, or always), steering angle reading over the hub.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from ...api_control import api
from ...const_file import ImageFile
from ...userfile.custom_image import image_exists, load_custom_image
from .base import CENTER, ModernOverlay
from .draw import disc, rounded

SPOKES = (90.0, 180.0, 270.0)  # right, bottom, left (degrees clockwise from top)


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_size", "show_custom_steering_wheel", "custom_steering_wheel_image_file",
        "show_steering_angle", "manual_steering_range", "show_degree_sign", "decimal_places",
        "show_rotation_line", "show_rotation_line_while_stationary_only",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        size = max(float(wcfg["display_size"]), 24.0)
        self.set_size(size, size)
        self.dial = QRectF(0, 0, size, size).adjusted(0.5, 0.5, -0.5, -0.5)
        self.center = self.dial.center()
        half = self.dial.width() / 2
        self.arc_width = max(size * 0.05, 2.0)
        arc_gap = max(size * 0.025, 1.0)
        self.arc_radius = half - arc_gap - self.arc_width / 2
        self.rim_width = max(size * 0.075, 2.5)
        self.rim_radius = self.arc_radius - self.arc_width / 2 - arc_gap - self.rim_width / 2
        self.hub_radius = self.rim_radius * 0.34
        self.show_rotation = bool(wcfg["show_rotation_line"])
        self.stationary_only = bool(wcfg["show_rotation_line_while_stationary_only"])
        self.show_angle = bool(wcfg["show_steering_angle"])
        self.decimals = min(max(int(wcfg["decimal_places"]), 0), 2)
        self.degree = "°" if wcfg["show_degree_sign"] else ""

        # Custom wheel image, if user set one that exists
        self.image = None
        image_file = wcfg["custom_steering_wheel_image_file"] if wcfg["show_custom_steering_wheel"] else ""
        if image_file and image_exists(image_file):
            image_size = round((self.rim_radius + self.rim_width / 2) * 2 * self.devicePixelRatioF())
            self.image = load_custom_image(image_file, ImageFile.STEERING_WHEEL, image_size, image_size)
            self.image.setDevicePixelRatio(self.devicePixelRatioF())

        self.pen_rim = QPen(theme.tint(theme.text, 225), self.rim_width)
        self.pen_stripe = QPen(theme.warning, self.rim_width)
        self.pen_stripe.setCapStyle(Qt.PenCapStyle.FlatCap)
        self.pen_spoke = QPen(theme.tint(theme.text, 150), self.rim_radius * 0.2)
        self.pen_spoke.setCapStyle(Qt.PenCapStyle.FlatCap)
        self.pen_arc = QPen(theme.accent, self.arc_width)
        self.pen_arc.setCapStyle(Qt.PenCapStyle.RoundCap)

        # Angle reading over hub
        sample = f"-888.{'8' * self.decimals}" if self.decimals else "-888"
        reading_w = self.text_width("value", sample + self.degree) + unit * 0.6
        reading_h = unit * 1.25
        self.rect_reading = QRectF(self.center.x() - reading_w / 2, self.center.y() - reading_h / 2, reading_w, reading_h)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        if self.wcfg["manual_steering_range"] > 0:
            steering_range = self.wcfg["manual_steering_range"]
        else:
            steering_range = api.read.inputs.steering_range_physical()
        angle = round(api.read.inputs.steering_raw() * steering_range * 0.5, 1)
        show_arc = self.show_rotation and (not self.stationary_only or api.read.vehicle.speed() < 1)
        self.refresh((angle, show_arc))

    def paint_static(self, painter: QPainter):
        disc(painter, self.dial, self.theme, self.depth_effects)

    def paint(self, painter: QPainter):
        theme = self.theme
        angle, show_arc = self.state
        center = self.center
        if show_arc and angle:
            radius = self.arc_radius
            painter.setPen(self.pen_arc)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
                            90 * 16, round(-angle * 16))
        painter.save()
        painter.translate(center)
        painter.rotate(angle)
        if self.image is not None:
            half = self.image.deviceIndependentSize().width() / 2
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(QPointF(-half, -half), self.image)
        else:
            self.draw_wheel(painter)
        painter.restore()
        if self.show_angle:
            rect = self.rect_reading
            rounded(painter, rect, self.radius(0.4), theme.tint(theme.surface, 235))
            text = f"{abs(angle):.{self.decimals}f}{self.degree}"
            self.draw_text(painter, rect, text, "value", theme.text, CENTER, elide=False)

    def draw_wheel(self, painter: QPainter):
        """Wheel shapes around origin, top up"""
        theme = self.theme
        rim = self.rim_radius
        hub = self.hub_radius
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen_spoke)
        for spoke in SPOKES:
            painter.save()
            painter.rotate(spoke)
            painter.drawLine(QPointF(0, -hub * 0.8), QPointF(0, -rim))
            painter.restore()
        painter.setPen(self.pen_rim)
        painter.drawEllipse(QPointF(0, 0), rim, rim)
        painter.setPen(self.pen_stripe)
        painter.drawArc(QRectF(-rim, -rim, rim * 2, rim * 2), 81 * 16, 18 * 16)
        painter.setPen(QPen(theme.tint(theme.text, 70), max(self.rim_width * 0.3, 1.0)))
        painter.setBrush(theme.surface_raised)
        painter.drawEllipse(QPointF(0, 0), hub, hub)
