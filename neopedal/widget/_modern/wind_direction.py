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
Wind direction Widget, modern design

Round dial: compass ticks turning with car heading (north in red), arrow of where wind blows
relative to car (up: tailwind) colored by wind strength (calm blue to storm purple), dot while
calm, wind speed in a chip below center.
"""

from __future__ import annotations

from math import cos, radians, sin
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF

from ... import units
from ..wind_direction import WindMixin, rim_steps
from .base import CENTER, ModernOverlay
from .draw import disc, rounded

if TYPE_CHECKING:
    from ...template.widget_config_types import WindDirectionConfig


class Realtime(WindMixin, ModernOverlay):
    """Draw widget"""

    wcfg: WindDirectionConfig

    options = (
        "font_size", "display_size", "show_wind_strength_color", "wind_strength_threshold_calm",
        "wind_strength_threshold_light", "wind_strength_threshold_moderate", "wind_strength_threshold_strong",
        "wind_strength_threshold_gale", "wind_strength_threshold_storm", "show_wind_speed", "show_wind_speed_unit",
        "decimal_places", "show_direction_mark",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        self.add_font("north", 0.62, "bold")
        self.add_font("reading", 0.78, "bold")
        size = max(float(wcfg["display_size"]), unit * 4.5)
        self.set_size(size, size)
        self.dial = QRectF(0, 0, size, size).adjusted(1, 1, -1, -1)
        self.center = self.dial.center()
        outer = self.dial.width() / 2
        self.decimals = min(max(int(wcfg["decimal_places"]), 0), 2)
        self.setup_wind()
        self.show_marks = bool(wcfg["show_direction_mark"])
        self.show_strength = bool(wcfg["show_wind_strength_color"])
        wind_unit = self.cfg.units["wind_speed_unit"]
        self.unit_speed = units.set_unit_speed(wind_unit)
        self.symbol_speed = f" {units.set_symbol_speed(wind_unit)}" if wcfg["show_wind_speed_unit"] else ""
        # Calm, light, moderate, strong, gale, storm (index: strength level - 1)
        self.strength_colors = (theme.blue, theme.positive, theme.caution, theme.orange, theme.negative, theme.best)

        # Compass ticks every 30 degrees (turned with heading when drawn), north letter
        self.ticks_minor = QPainterPath()
        self.ticks_major = QPainterPath()
        top = outer - unit * 0.18
        for angle in range(30, 360, 30):
            major = angle % 90 == 0
            length = unit * (0.42 if major else 0.26)
            path = self.ticks_major if major else self.ticks_minor
            sin_a, cos_a = sin(radians(angle)), cos(radians(angle))
            path.moveTo(sin_a * top, -cos_a * top)
            path.lineTo(sin_a * (top - length), -cos_a * (top - length))
        self.pen_minor = QPen(theme.tint(theme.text, 70), max(unit * 0.06, 1.0))
        self.pen_major = QPen(theme.tint(theme.text, 150), max(unit * 0.09, 1.2))
        self.north_radius = top - unit * 0.42
        self.north_box = self.metrics["north"].height()

        # Arrow pointing up before rotation, dot while calm
        reach = max(self.north_radius - self.north_box * 0.6, unit)
        self.arrow = QPolygonF((
            QPointF(0, -reach * 0.95),
            QPointF(reach * 0.5, reach * 0.55),
            QPointF(0, reach * 0.2),
            QPointF(-reach * 0.5, reach * 0.55),
        ))
        self.calm_radius = max(reach * 0.22, 2.5)

        # Wind speed chip below center
        sample = f"88.{'8' * self.decimals}" if self.decimals else "88"
        chip_w = self.text_width("reading", sample + self.symbol_speed) + unit * 0.6
        chip_h = self.metrics["reading"].height() + unit * 0.2
        self.chip = QRectF(self.center.x() - chip_w / 2, self.center.y() + reach * 0.62, chip_w, chip_h)

    def timerEvent(self, event):
        """Update when vehicle on track, repaint once a turn moves the dial rim by a device pixel (not at every 0.1
        degree: up to 50 Hz while heading jitters)"""
        compass, speed, angle = self.read_wind()
        if not self.show_marks:
            compass = 0.0  # compass not drawn
        text = f"{self.unit_speed(speed):.{self.decimals}f}{self.symbol_speed}"
        level = self.strength_level(speed) if self.show_strength else 0
        rim = self.dial.width() / 2 * self.devicePixelRatioF()  # device pixels
        self.refresh_keyed(
            (round(compass, 1), text, None if angle is None else round(angle, 1), level),
            (rim_steps(compass, rim), text, None if angle is None else rim_steps(angle, rim), level),
        )

    def paint_static(self, painter: QPainter):
        disc(painter, self.dial, self.theme, self.depth_effects)

    def paint(self, painter: QPainter):
        theme = self.theme
        compass, text, angle, level = self.state
        center = self.center
        # Compass ticks & north letter turned by heading
        if self.wcfg["show_direction_mark"]:
            painter.save()
            painter.translate(center)
            painter.rotate(compass)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(self.pen_minor)
            painter.drawPath(self.ticks_minor)
            painter.setPen(self.pen_major)
            painter.drawPath(self.ticks_major)
            painter.restore()
            turned = radians(compass)
            pos = QPointF(center.x() + sin(turned) * self.north_radius, center.y() - cos(turned) * self.north_radius)
            side = self.north_box
            self.draw_text(painter, QRectF(pos.x() - side / 2, pos.y() - side / 2, side, side), "N", "north",
                           theme.negative, CENTER, elide=False)
        # Wind arrow (dot while calm)
        color = self.strength_colors[level - 1] if level else theme.text
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color if angle is not None else theme.text_muted)
        if angle is None:
            painter.drawEllipse(center, self.calm_radius, self.calm_radius)
        else:
            painter.save()
            painter.translate(center)
            painter.rotate(angle)
            painter.drawPolygon(self.arrow)
            painter.restore()
        # Wind speed
        if self.wcfg["show_wind_speed"]:
            rounded(painter, self.chip, self.radius(0.35), theme.tint(theme.surface, 225))
            self.draw_text(painter, self.chip, text, "reading", theme.text, CENTER)
