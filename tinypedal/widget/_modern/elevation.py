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
Elevation Widget, modern design

Track elevation profile over one lap on a chart: soft area under the line, part already driven
in accent color, car as a dot on the profile; faint start, sector & zero elevation lines.
Header with current elevation and chart scale.
"""

from __future__ import annotations

from bisect import bisect_left

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...i18n import tr_overlay as tr
from ...module_info import minfo
from .base import LEFT, RIGHT, ModernOverlay
from .draw import panel, rounded

AREA_ALPHA = (40, 10)  # profile area (text color), top & bottom of chart
PROGRESS_ALPHA = (110, 24)  # driven part area (accent)


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_width", "display_height", "display_margin_top", "display_margin_bottom",
        "display_detail_level", "show_elevation_reading", "show_elevation_scale", "show_elevation_background",
        "show_elevation_progress", "show_elevation_progress_line", "show_elevation_line", "show_zero_elevation_line",
        "show_start_line", "show_sector_line", "show_position_mark",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        self.unit_dist = units.set_unit_distance(self.cfg.units["distance_unit"])
        self.symbol_dist = units.set_symbol_distance(self.cfg.units["distance_unit"])
        pad = unit * 0.35
        width = max(float(wcfg["display_width"]), unit * 5)
        height = max(float(wcfg["display_height"]), unit * 1.5)
        self.show_reading = bool(wcfg["show_elevation_reading"])
        self.show_scale = bool(wcfg["show_elevation_scale"])
        header = unit * 1.15 if self.show_reading or self.show_scale else 0.0
        self.header = QRectF(pad + unit * 0.2, pad * 0.6, width - unit * 0.4, header)
        self.chart = QRectF(pad, pad + header, width, height)
        self.set_size(width + pad * 2, height + pad * 2 + header)
        margin_top = min(max(float(wcfg["display_margin_top"]), 0.0), height / 2)
        margin_bottom = min(max(float(wcfg["display_margin_bottom"]), 0.0), height / 2)
        self.plot = self.chart.adjusted(0, margin_top, 0, -margin_bottom)
        line_w = max(unit * 0.13, 1.5)
        self.pen_line = QPen(theme.text_muted, line_w)
        self.pen_progress = QPen(theme.accent, line_w)
        for pen in (self.pen_line, self.pen_progress):
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.brush_area = self.fade(theme.text, AREA_ALPHA)
        self.brush_progress = self.fade(theme.accent, PROGRESS_ALPHA)
        self.dot = max(unit * 0.28, 3.0)
        self.label_reading = tr("Elevation")
        self.label_scale = tr("Scale")
        self.last_modified = None
        self.line = QPolygonF()
        self.area = QPainterPath()
        self.xs: list[float] = []  # profile x of each point (car dot height)
        self.sector_xs: tuple[float, ...] = ()
        self.zero_y: float | None = None
        self.scale_text = ""

    def fade(self, color: QColor, alphas: tuple[int, int]) -> QBrush:
        """Area fill fading toward chart bottom"""
        gradient = QLinearGradient(0, self.plot.top(), 0, self.chart.bottom())
        gradient.setColorAt(0.0, self.theme.tint(color, alphas[0]))
        gradient.setColorAt(1.0, self.theme.tint(color, alphas[1]))
        return QBrush(gradient)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        modified = minfo.mapping.lastModified
        if modified != self.last_modified:
            self.last_modified = modified
            self.build_profile(minfo.mapping.elevations, minfo.mapping.sectors)
            self.redraw_static()
        progress = api.read.lap.progress()
        x = self.chart.left() + self.chart.width() * min(max(progress, 0.0), 1.0) if progress == progress else self.chart.left()
        reading = ""
        if self.show_reading:
            reading = f"{self.unit_dist(api.read.vehicle.position_vertical()):.1f}{self.symbol_dist}"
        self.refresh((round(x, 1), reading))

    def build_profile(self, elevations, sectors):
        """Profile line & area in chart coordinates (empty if no map)"""
        self.line = QPolygonF()
        self.area = QPainterPath()
        self.xs = []
        self.sector_xs = ()
        self.zero_y = None
        self.scale_text = ""
        if not elevations or len(elevations) < 3:
            return
        plot = self.plot
        scaled, map_range, map_scale = calc.scale_elevation(elevations, plot.width(), plot.height())
        total = len(scaled) - 1
        skip = calc.skip_map_nodes(total, max(int(plot.width()), 1), max(int(self.wcfg["display_detail_level"]), 0))
        start_y = (scaled[0][1] + scaled[-1][1]) / 2  # start & finish nodes meet
        points = [QPointF(plot.left(), plot.bottom() - start_y)]
        last_x = 0.0
        skipped = 0
        for index, (pos_x, pos_y) in enumerate(scaled):
            if index == 0:
                continue
            if index >= total:
                points.append(QPointF(plot.right(), plot.bottom() - start_y))
            elif pos_x > last_x and skipped >= skip:
                points.append(QPointF(plot.left() + pos_x, plot.bottom() - pos_y))
                skipped = 0
                last_x = pos_x
            skipped += 1
        self.line = QPolygonF(points)
        self.xs = [point.x() for point in points]
        area = QPainterPath()
        area.addPolygon(QPolygonF([*points, QPointF(plot.right(), self.chart.bottom()),
                                   QPointF(plot.left(), self.chart.bottom())]))
        area.closeSubpath()
        self.area = area
        if isinstance(sectors, tuple):
            self.sector_xs = tuple(plot.left() + scaled[index][0] for index in sectors if 0 <= index < len(scaled))
        if map_range[2] <= 0 <= map_range[3]:
            self.zero_y = plot.bottom() - map_scale[1] * -map_range[2]
        if map_scale[1]:
            self.scale_text = f"1:{round(self.unit_dist(1 / map_scale[1]), 2)}"

    def profile_y(self, x: float) -> float | None:
        """Profile height at chart x"""
        xs = self.xs
        if len(xs) < 2:
            return None
        index = min(max(bisect_left(xs, x), 1), len(xs) - 1)
        left = self.line.at(index - 1)
        right = self.line.at(index)
        span = right.x() - left.x()
        if span <= 0:
            return right.y()
        fraction = min(max((x - left.x()) / span, 0.0), 1.0)
        return left.y() + (right.y() - left.y()) * fraction

    def paint_static(self, painter: QPainter):
        wcfg = self.wcfg
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        chart = self.chart
        rounded(painter, chart, self.radius(0.3), theme.tint(theme.surface_alt, 200))
        header = self.header
        if self.show_reading:
            self.draw_text(painter, header, self.label_reading, "label", theme.text_muted, LEFT)
        if self.show_scale and self.scale_text:
            value_w = self.text_width("small", self.scale_text)
            self.draw_text(painter, header, self.scale_text, "small", theme.text_dim, RIGHT)
            self.draw_text(painter, header.adjusted(0, 0, -value_w - self.unit * 0.35, 0), self.label_scale, "label",
                           theme.text_muted, RIGHT)
        painter.save()
        painter.setClipRect(chart)
        if wcfg["show_zero_elevation_line"] and self.zero_y is not None:
            pen = QPen(theme.tint(theme.text, 40), 1, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(QPointF(chart.left(), self.zero_y), QPointF(chart.right(), self.zero_y))
        if wcfg["show_sector_line"]:
            color = theme.tint(theme.text, 30)
            for x in self.sector_xs:
                painter.fillRect(QRectF(round(x) - 0.5, chart.top(), 1, chart.height()), color)
        if wcfg["show_start_line"]:
            width = max(self.unit * 0.1, 1.5)
            color = theme.tint(theme.text, 60)
            painter.fillRect(QRectF(chart.left(), chart.top(), width, chart.height()), color)
            painter.fillRect(QRectF(chart.right() - width, chart.top(), width, chart.height()), color)
        if not self.line.isEmpty():
            if wcfg["show_elevation_background"]:
                painter.fillPath(self.area, self.brush_area)
            if wcfg["show_elevation_line"]:
                painter.setPen(self.pen_line)
                painter.drawPolyline(self.line)
        painter.restore()

    def paint(self, painter: QPainter):
        wcfg = self.wcfg
        theme = self.theme
        x, reading = self.state
        chart = self.chart
        if reading:
            label_w = self.text_width("label", self.label_reading)
            self.draw_text(painter, self.header.adjusted(label_w + self.unit * 0.35, 0, 0, 0), reading, "small",
                           theme.text, LEFT)
        if self.line.isEmpty():
            return
        painter.save()
        painter.setClipRect(QRectF(chart.left(), chart.top(), max(x - chart.left(), 0.0), chart.height()))
        if wcfg["show_elevation_progress"]:
            painter.fillPath(self.area, self.brush_progress)
        if wcfg["show_elevation_progress_line"]:
            painter.setPen(self.pen_progress)
            painter.drawPolyline(self.line)
        painter.restore()
        if wcfg["show_position_mark"]:
            painter.fillRect(QRectF(x - 0.5, chart.top(), 1, chart.height()), theme.tint(theme.accent, 110))
            y = self.profile_y(x)
            if y is not None:
                ring = self.dot + max(self.unit * 0.1, 1.0)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(theme.surface)
                painter.drawEllipse(QPointF(x, y), ring, ring)
                painter.setBrush(theme.accent)
                painter.drawEllipse(QPointF(x, y), self.dot, self.dot)
