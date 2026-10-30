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
Wind direction Widget

Compass marks turning with car heading (north mark in its own color), arrow of where wind blows
relative to car (up: tailwind) colored by wind strength, dot while calm, wind speed reading.
"""

from math import cos, isfinite, pi, radians, sin
from typing import TYPE_CHECKING

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QPainter, QPen, QPolygonF

from .. import calculation as calc
from .. import units
from ..api_control import api
from ._base import Overlay
from ._painter import fill_rect
from .weather import wind_reading

if TYPE_CHECKING:
    from ..template.widget_config_types import WindDirectionConfig


class WindMixin:
    """Wind reading relative to car, for classic & modern widget"""

    wcfg: "WindDirectionConfig"

    def setup_wind(self):
        """Wind strength thresholds (m/s), ascending"""
        wcfg = self.wcfg
        self.wind_thresholds = tuple(float(value) for value in (
            wcfg["wind_strength_threshold_light"], wcfg["wind_strength_threshold_moderate"],
            wcfg["wind_strength_threshold_strong"], wcfg["wind_strength_threshold_gale"],
            wcfg["wind_strength_threshold_storm"]))

    def read_wind(self) -> tuple[float, float, float | None]:
        """Compass rotation (degrees, car heading), wind speed (m/s), angle of where wind blows relative to
        car (degrees clockwise from car front, None while calm)"""
        compass = calc.degrees(api.read.vehicle.orientation_yaw_radians()) + 180
        speed, angle = wind_reading(self.wcfg["wind_strength_threshold_calm"])
        return compass, speed, angle

    def strength_level(self, speed: float) -> int:
        """Wind strength level: 1 calm (below light threshold), 2 light ... 6 storm"""
        level = 1
        for threshold in self.wind_thresholds:
            if speed < threshold:
                break
            level += 1
        return level


def rim_steps(angle: float, radius: float) -> int:
    """Turn (degrees) as device pixels moved at rim of radius (device pixels), 0 if not finite: repaint key of a
    turned drawing (turns too small to see never repaint). Same key for the same drawing whichever turn: heading
    jitter across north, or a headwind across +-180 degrees, never repaints at every update"""
    if not (isfinite(angle) and isfinite(radius)):
        return 0
    # Turn of 0 to 360 degrees (headwind at 180: no wrap there), rounded, then 360 degrees wrapped to 0 (exact)
    steps = round(radians(angle % 360) * radius)
    full = round(2 * pi * radius)
    return steps % full if full > 0 else steps


def compass_marks(radius: float, margin: float, lengths: tuple[float, float, float]) -> tuple[
        tuple[QLineF, ...], tuple[QLineF, ...], QLineF]:
    """Direction marks around center at 0, 0 before heading rotation: minor (every 30 degrees between
    cardinals), major (east, south, west) & north lines; lengths: minor, major, north end (fraction of start)"""
    start = radius - margin
    minor: list[QLineF] = []
    major: list[QLineF] = []
    for angle in range(30, 360, 30):
        if angle % 90:
            end = start * lengths[0]
            target = minor
        else:
            end = start * lengths[1]
            target = major
        sin_a, cos_a = sin(radians(angle)), cos(radians(angle))
        target.append(QLineF(sin_a * start, -cos_a * start, sin_a * end, -cos_a * end))
    return tuple(minor), tuple(major), QLineF(0, -start, 0, -start * lengths[2])


class Realtime(WindMixin, Overlay):
    """Draw widget"""

    wcfg: "WindDirectionConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)

        # Config font
        font = self.config_font(
            self.wcfg["font_name"],
            self.wcfg["font_size"],
            self.wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        # Config variable
        area_size = max(int(self.wcfg["display_size"] / 2) * 2, 10)
        area_margin = min(max(self.wcfg["display_margin"], 0), int(area_size / 4))
        self.area_center = area_center = area_size * 0.5
        self.decimals = min(max(int(self.wcfg["decimal_places"]), 0), 2)  # same limit as modern design
        self.setup_wind()

        # Config units
        self.unit_speed = units.set_unit_speed(self.cfg.units["wind_speed_unit"])
        self.symbol_speed = units.set_symbol_speed(self.cfg.units["wind_speed_unit"]) if (
            self.wcfg["show_wind_speed_unit"]) else ""

        # Config canvas
        self.resize(area_size, area_size)
        self.rect_bg = QRectF(0, 0, area_size, area_size)
        self.rect_text = QRectF(
            area_size * self.wcfg["wind_speed_offset_x"] - area_center,
            area_size * self.wcfg["wind_speed_offset_y"] - font_m.height * 0.5 + font_m.voffset,
            area_size,
            font_m.height,
        )

        # Arrow shape (pointing up before rotation), dot while calm
        size_calm = area_center / 3
        self.rect_calm = QRectF(-size_calm / 2, -size_calm / 2, size_calm, size_calm)
        self.arrow_shape = QPolygonF((
            QPointF(0, -area_center * self.wcfg["wind_arrow_scale_top"]),
            QPointF(area_center * self.wcfg["wind_arrow_scale_side"], area_center * self.wcfg["wind_arrow_scale_bottom"]),
            QPointF(0, area_center * self.wcfg["wind_arrow_scale_center"]),
            QPointF(-area_center * self.wcfg["wind_arrow_scale_side"], area_center * self.wcfg["wind_arrow_scale_bottom"]),
        ))
        self.brush_arrow = tuple(  # by strength level: arrow color (strength colors off), calm ... storm
            QBrush(color, Qt.BrushStyle.SolidPattern) for color in (
                self.wcfg["wind_arrow_color"], self.wcfg["wind_strength_color_calm"],
                self.wcfg["wind_strength_color_light"], self.wcfg["wind_strength_color_moderate"],
                self.wcfg["wind_strength_color_strong"], self.wcfg["wind_strength_color_gale"],
                self.wcfg["wind_strength_color_storm"])
        )

        # Direction marks
        self.marks = compass_marks(area_center, area_margin, (
            self.wcfg["direction_mark_minor_length"],
            self.wcfg["direction_mark_major_length"],
            self.wcfg["direction_mark_north_length"],
        ))
        self.pen_marks = (
            self.set_pen_style(self.wcfg["direction_mark_minor_color"], self.wcfg["direction_mark_minor_width"]),
            self.set_pen_style(self.wcfg["direction_mark_major_color"], self.wcfg["direction_mark_major_width"]),
            self.set_pen_style(self.wcfg["direction_mark_north_color"], self.wcfg["direction_mark_north_width"]),
        )
        self.pen_text = QPen(self.wcfg["font_color_wind_speed"])
        self.brush_circle = QBrush(self.wcfg["background_color_circle"], Qt.BrushStyle.SolidPattern)

        # Last data: compass rotation, wind speed text, arrow angle (None while calm), strength level
        self.wind_state: tuple[float, str, float | None, int] = (0.0, "", None, 0)
        self.wind_key: tuple | None = None  # wind state as drawn (turns in pixels at rim), decides a repaint
        self.show_marks = bool(self.wcfg["show_direction_mark"])
        self.show_strength = bool(self.wcfg["show_wind_strength_color"])

    def timerEvent(self, event):
        """Update when vehicle on track, repaint once a turn moves the rim by a device pixel (not at every 0.1
        degree: up to 50 Hz while heading jitters)"""
        compass, speed, angle = self.read_wind()
        if not self.show_marks:
            compass = 0.0  # compass not drawn
        text = f"{self.unit_speed(speed):.{self.decimals}f}{self.symbol_speed}"
        level = self.strength_level(speed) if self.show_strength else 0
        rim = self.area_center * self.devicePixelRatioF()
        key = (rim_steps(compass, rim), text, None if angle is None else rim_steps(angle, rim), level)
        if key != self.wind_key:
            self.wind_key = key
            self.wind_state = (round(compass, 1), text, None if angle is None else round(angle, 1), level)
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        compass, text_speed, angle, level = self.wind_state
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Draw background
        if self.wcfg["show_background"]:
            fill_rect(painter, self.rect_bg, self.wcfg["background_color"])
        if self.wcfg["show_circle_background"]:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.brush_circle)
            painter.drawEllipse(self.rect_bg)

        # Draw direction marks, turned with car heading
        painter.translate(self.area_center, self.area_center)
        if self.wcfg["show_direction_mark"]:
            painter.save()
            painter.rotate(compass)
            minor, major, north = self.marks
            painter.setPen(self.pen_marks[0])
            painter.drawLines(minor)
            painter.setPen(self.pen_marks[1])
            painter.drawLines(major)
            painter.setPen(self.pen_marks[2])
            painter.drawLine(north)
            painter.restore()

        # Draw wind arrow, where wind blows relative to car (dot while calm)
        painter.setPen(Qt.PenStyle.NoPen)
        if angle is None:
            painter.setBrush(self.brush_arrow[0])
            painter.drawEllipse(self.rect_calm)
        else:
            painter.rotate(angle)
            painter.setBrush(self.brush_arrow[level])
            painter.drawPolygon(self.arrow_shape)

        # Draw wind speed
        if self.wcfg["show_wind_speed"]:
            painter.resetTransform()
            painter.setPen(self.pen_text)
            painter.drawText(self.rect_text, Qt.AlignmentFlag.AlignCenter, text_speed)

    def set_pen_style(self, color: str, width: float) -> QPen:
        """Set pen style"""
        if width > 0:
            pen = QPen()
            pen.setWidthF(width)
            pen.setColor(color)
        else:
            pen = QPen(Qt.PenStyle.NoPen)
        return pen
