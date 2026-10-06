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
Weather forecast Widget, modern design

One tile per forecast, now first (accent): time until forecast, weather icon drawn as shapes
(sun, clouds, drizzle, rain, heavy rain, storm), air temperature, rain chance bar with optional
reading. Unavailable forecasts hidden (or shown as dashes).
"""

from __future__ import annotations

from math import cos, pi, sin
from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from ... import units
from ...const_common import ABS_ZERO_CELSIUS, MAX_FORECAST_MINUTES, MAX_FORECASTS
from ...i18n import tr_overlay as tr
from ..weather_forecast import ForecastMixin, forecast_time_text
from .base import CENTER, DASH, ModernOverlay, display_order_options
from .draw import bar, panel, rounded
from .theme import Theme

ROWS = ("estimated_time", "weather_icon", "ambient_temperature", "rain_chance_bar")


class Slot(NamedTuple):
    """Forecast tile of one update"""

    time: str
    sky: int  # sky type, -1 unavailable
    temperature: str
    rain: float  # rain chance, 0 to 1
    rain_text: str


class Realtime(ForecastMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "number_of_forecasts", "show_unavailable_data", "show_estimated_time",
        "show_ambient_temperature", "show_rain_chance_bar", "show_rain_chance_reading",
        *display_order_options("weather_forecast"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.total_slot = min(max(wcfg["number_of_forecasts"], 1), MAX_FORECASTS - 1) + 1
        self.estimated_time = [MAX_FORECAST_MINUTES] * MAX_FORECASTS
        self.reversed = wcfg["layout"] != 0
        self.show_unavailable = bool(wcfg["show_unavailable_data"])
        self.show_rain_reading = bool(wcfg["show_rain_chance_reading"])
        shown = {
            "estimated_time": wcfg["show_estimated_time"],
            "weather_icon": True,
            "ambient_temperature": wcfg["show_ambient_temperature"],
            "rain_chance_bar": wcfg["show_rain_chance_bar"],
        }
        rows = self.display_ordered([key for key in ROWS if shown[key]], key=str)
        heights = {
            "estimated_time": unit * 1.0,
            "weather_icon": unit * 2.3,
            "ambient_temperature": unit * 1.2,
            "rain_chance_bar": unit * (1.05 if self.show_rain_reading else 0.55),
        }
        self.pad = unit * 0.3
        self.gap = unit * 0.2
        inner = unit * 0.3
        self.column_w = max(
            unit * 2.4,
            self.text_width("small", self.widest("small", (tr("now"), "88.8h", "888m"))),
            self.text_width("value", "-888°"),
            self.text_width("small", "100%") if self.show_rain_reading else 0,
        ) + inner * 2
        # Row rects of a tile at left 0 (moved to tile place when drawn)
        self.rows: dict[str, QRectF] = {}
        top = self.pad + unit * 0.2
        for key in rows:
            self.rows[key] = QRectF(inner, top, self.column_w - inner * 2, heights[key])
            top += heights[key]
        self.tile_h = top + unit * 0.15 - self.pad
        self.icon_stroke = max(unit * 0.12, 1.2)
        self.columns = 0
        self.place_columns(self.total_slot)

    def place_columns(self, count: int):
        """Widget size for count tiles"""
        if count != self.columns:
            self.columns = count
            self.set_size(self.pad * 2 + count * self.column_w + (count - 1) * self.gap, self.tile_h + self.pad * 2)
            self.update()

    def tile_left(self, index: int) -> float:
        """Left of tile at index (0 = now), right to left in reversed layout"""
        if self.reversed:
            index = self.columns - 1 - index
        return self.pad + index * (self.column_w + self.gap)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        forecast = self.read_forecast()
        if forecast is None:
            return
        slots = []
        for index, (rain_chance, sky, temperature, minutes) in enumerate(forecast):
            if not 0 <= sky <= 10:
                sky = -1
            if sky < 0 and index > 0 and not self.show_unavailable:
                continue
            if index == 0:
                time_text = tr("now")
            else:
                time_text = forecast_time_text(minutes) if 0 <= minutes < MAX_FORECAST_MINUTES else DASH
            if temperature > ABS_ZERO_CELSIUS:
                temp_text = f"{self.unit_temp(temperature):.0f}°"
            else:
                temp_text = DASH
            rain = min(max(round(rain_chance, 2), 0.0), 1.0)
            slots.append(Slot(time_text, sky, temp_text, rain, f"{rain:.0%}" if sky >= 0 or index == 0 else DASH))
        self.place_columns(len(slots))
        self.refresh(tuple(slots))

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for index in range(self.columns):
            tile = QRectF(self.tile_left(index), self.pad, self.column_w, self.tile_h)
            fill = theme.tint(theme.accent, 34) if index == 0 else theme.tint(theme.surface_alt, 190)
            rounded(painter, tile, self.radius(0.35), fill)

    def paint(self, painter: QPainter):
        theme = self.theme
        rows = self.rows
        unit = self.unit
        for index, slot in enumerate(self.state):
            if index >= self.columns:
                break
            left = self.tile_left(index)
            if "estimated_time" in rows:
                color = theme.accent if index == 0 else theme.text_dim
                self.draw_text(painter, rows["estimated_time"].translated(left, 0), slot.time, "small", color, CENTER)
            if "weather_icon" in rows:
                rect = rows["weather_icon"].translated(left, 0)
                side = min(rect.width(), rect.height())
                icon = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
                if slot.sky < 0:
                    self.draw_text(painter, icon, DASH, "value", theme.text_faint, CENTER)
                else:
                    weather_icon(painter, icon, slot.sky, theme, self.icon_stroke)
            if "ambient_temperature" in rows:
                self.draw_text(painter, rows["ambient_temperature"].translated(left, 0), slot.temperature, "value",
                               theme.text, CENTER)
            if "rain_chance_bar" in rows:
                rect = rows["rain_chance_bar"].translated(left, 0)
                height = max(unit * 0.2, 2.0)
                track = QRectF(rect.left(), rect.bottom() - height - unit * 0.12, rect.width(), height)
                bar(painter, track, slot.rain, theme.accent, theme.surface_raised, height / 2)
                if self.show_rain_reading:
                    reading = QRectF(rect.left(), rect.top(), rect.width(), track.top() - rect.top())
                    color = theme.accent if slot.rain > 0 else theme.text_muted
                    self.draw_text(painter, reading, slot.rain_text, "small", color, CENTER)


# Weather icons, in square rect
def cloud_path(center: QPointF, width: float) -> QPainterPath:
    """Cloud with flat bottom, width wide, centered on center"""
    x, y = center.x(), center.y()
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)  # overlapping bumps stay filled
    path.addEllipse(QPointF(x - width * 0.25, y + width * 0.05), width * 0.17, width * 0.17)
    path.addEllipse(QPointF(x - width * 0.04, y - width * 0.07), width * 0.25, width * 0.25)
    path.addEllipse(QPointF(x + width * 0.22, y + width * 0.01), width * 0.2, width * 0.2)
    path.addRoundedRect(QRectF(x - width * 0.42, y + width * 0.01, width * 0.84, width * 0.21), width * 0.105, width * 0.105)
    return path.simplified()


def draw_sun(painter: QPainter, center: QPointF, radius: float, color: QColor, rays: bool = True):
    """Sun disc with rays"""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(center, radius, radius)
    if rays:
        pen = QPen(color, radius * 0.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for index in range(8):
            angle = index * pi / 4
            painter.drawLine(QPointF(center.x() + cos(angle) * radius * 1.5, center.y() + sin(angle) * radius * 1.5),
                             QPointF(center.x() + cos(angle) * radius * 1.95, center.y() + sin(angle) * radius * 1.95))


def draw_cloud(painter: QPainter, center: QPointF, width: float, fill: QColor, edge: QColor):
    """Cloud with outline (sits over sun & back clouds)"""
    painter.setPen(QPen(edge, max(width * 0.05, 1.0)))
    painter.setBrush(fill)
    painter.drawPath(cloud_path(center, width))


def draw_rain(painter: QPainter, rect: QRectF, count: int, color: QColor, width: float, drops: bool):
    """Drops (round) or streaks (slanted) under cloud"""
    side = rect.width()
    top = rect.top() + side * 0.7
    spacing = side * 0.2
    left = rect.center().x() - spacing * (count - 1) / 2
    if drops:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for index in range(count):
            x = left + index * spacing
            y = top + side * (0.06 if index % 2 else 0.14)
            painter.drawEllipse(QPointF(x, y), side * 0.055, side * 0.055)
        return
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for index in range(count):
        x = left + index * spacing
        painter.drawLine(QPointF(x + side * 0.05, top), QPointF(x - side * 0.05, top + side * 0.24))


def draw_bolt(painter: QPainter, rect: QRectF, color: QColor):
    """Lightning bolt under cloud"""
    side = rect.width()
    x = rect.center().x()
    y = rect.top() + side * 0.6
    points = (
        QPointF(x + side * 0.06, y), QPointF(x - side * 0.1, y + side * 0.2), QPointF(x + side * 0.0, y + side * 0.2),
        QPointF(x - side * 0.08, y + side * 0.4), QPointF(x + side * 0.14, y + side * 0.14),
        QPointF(x + side * 0.03, y + side * 0.14), QPointF(x + side * 0.12, y),
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF(points))


def weather_icon(painter: QPainter, rect: QRectF, sky: int, theme: Theme, stroke: float):
    """Icon of sky type: 0 clear, 1 light clouds, 2 partly cloudy, 3 mostly cloudy, 4 overcast,
    5 drizzle, 6 light rain, 7 rain, 8 rain, 9 heavy rain, 10 storm"""
    side = rect.width()
    cx, cy = rect.center().x(), rect.center().y()
    sun = theme.warning
    if theme.surface.lightnessF() > 0.5:  # light theme: light clouds with darker edge
        cloud, dark, edge = theme.surface_strong, theme.text_faint, theme.text_muted
    else:
        cloud, dark, edge = theme.text_dim, theme.text_muted, theme.surface
    rain = theme.accent
    painter.save()
    if sky == 0:
        draw_sun(painter, QPointF(cx, cy), side * 0.2, sun)
    elif sky == 1:
        draw_sun(painter, QPointF(cx - side * 0.08, cy - side * 0.08), side * 0.17, sun)
        draw_cloud(painter, QPointF(cx + side * 0.16, cy + side * 0.16), side * 0.56, cloud, edge)
    elif sky == 2:
        draw_sun(painter, QPointF(cx - side * 0.16, cy - side * 0.16), side * 0.14, sun)
        draw_cloud(painter, QPointF(cx + side * 0.06, cy + side * 0.06), side * 0.8, cloud, edge)
    elif sky == 3:
        draw_cloud(painter, QPointF(cx, cy), side * 0.9, cloud, edge)
    elif sky == 4:
        draw_cloud(painter, QPointF(cx + side * 0.14, cy - side * 0.14), side * 0.62, dark, edge)
        draw_cloud(painter, QPointF(cx - side * 0.04, cy + side * 0.08), side * 0.84, cloud, edge)
    else:  # rain under cloud
        fill = dark if sky >= 9 else cloud
        draw_cloud(painter, QPointF(cx, cy - side * 0.16), side * 0.9, fill, edge)
        if sky == 5:
            draw_rain(painter, rect, 2, rain, stroke, True)
        elif sky == 6:
            draw_rain(painter, rect, 3, rain, stroke, True)
        elif sky == 7:
            draw_rain(painter, rect, 2, rain, stroke, False)
        elif sky == 8:
            draw_rain(painter, rect, 3, rain, stroke, False)
        elif sky == 9:
            draw_rain(painter, rect, 4, rain, stroke, False)
        else:
            draw_bolt(painter, rect, theme.caution)
    painter.restore()
