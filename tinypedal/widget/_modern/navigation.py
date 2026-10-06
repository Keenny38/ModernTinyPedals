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
Navigation Widget, modern design

Round view of track around car, turning with car heading: road with edge lines, start line,
sector lines (accent), cars as arrows (or dots) colored by race status, optional positions;
player car glowing at its place in view; view fades out at its edge.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPen, QPixmap, QRadialGradient

from ... import calculation as calc
from ...module_info import minfo
from ..navigation import NavigationMixin
from .base import CENTER, ModernOverlay
from .cars import car_colors, chevron, status_color
from .draw import disc, readable_on, rounded


class Realtime(NavigationMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_size", "view_radius", "vehicle_size", "vehicle_offset", "map_width",
        "show_fade_out", "fade_in_radius", "fade_out_radius", "show_start_line", "show_sector_line",
        "show_vehicle_class_standings", "show_circle_vehicle_shape",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        self.add_font("place", 0.6, "bold")
        size = max(int(wcfg["display_size"]), 40)
        road = max(float(wcfg["map_width"]), 2.0)
        self.setup_view(size, road * 1.9, road * 1.6)
        self.set_size(size, size)
        self.dial = QRectF(0, 0, size, size).adjusted(0.5, 0.5, -0.5, -0.5)
        self.colors = car_colors(theme)
        self.circle_shape = bool(wcfg["show_circle_vehicle_shape"])
        self.show_places = bool(wcfg["show_vehicle_class_standings"])
        self.car_size = max(float(wcfg["vehicle_size"]), 4.0)
        self.car_path = chevron(self.car_size)
        self.place_h = self.metrics["place"].height() * 1.1
        self.place_w = self.text_width("place", "88") + unit * 0.35

        # Road: edge lines (wide, light), asphalt over them
        self.pen_edge = QPen(theme.tint(theme.text, 170), road + max(road * 0.4, 2.0))
        self.pen_road = QPen(theme.text_faint, road)
        for pen in (self.pen_edge, self.pen_road):
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen_start = QPen(theme.text, max(road * 0.45, 2.0))
        self.pen_sector = QPen(theme.accent, max(road * 0.35, 1.5))
        for pen in (self.pen_start, self.pen_sector):
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen_car = QPen(theme.tint(theme.surface, 220), max(self.car_size * 0.07, 1.0))
        self.pen_car.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.layer: QPixmap | None = None
        self.alpha_mask: QPixmap | None = None
        self.update_map(-1)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        if self.update_map(minfo.mapping.lastModified):
            self.update()
        self.refresh(minfo.vehicles.dataSetVersion)

    def view_mask(self, ratio: float) -> QPixmap:
        """Round view, fading out toward edge (alpha mask)"""
        mask = self.alpha_mask
        if mask is not None and mask.devicePixelRatio() == ratio:
            return mask
        size = self.width()
        mask = QPixmap(max(round(size * ratio), 1), max(round(size * ratio), 1))
        mask.setDevicePixelRatio(ratio)
        mask.fill(Qt.GlobalColor.transparent)
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self.dial.width() / 2
        if self.wcfg["show_fade_out"]:
            gradient = QRadialGradient(self.dial.center(), radius)
            fade_out = calc.zero_one(self.wcfg["fade_out_radius"])
            gradient.setColorAt(min(calc.zero_one(self.wcfg["fade_in_radius"]), fade_out), Qt.GlobalColor.black)
            gradient.setColorAt(fade_out, Qt.GlobalColor.transparent)
            painter.setBrush(gradient)
        else:
            painter.setBrush(Qt.GlobalColor.black)
        painter.drawEllipse(self.dial.adjusted(1, 1, -1, -1))
        painter.end()
        self.alpha_mask = mask
        return mask

    def paint_static(self, painter: QPainter):
        disc(painter, self.dial, self.theme, self.depth_effects)

    def paint(self, painter: QPainter):
        ratio = self.devicePixelRatioF()
        layer = self.layer
        if layer is None or layer.devicePixelRatio() != ratio or layer.deviceIndependentSize() != self.size():
            layer = self.layer = QPixmap(max(round(self.width() * ratio), 1), max(round(self.height() * ratio), 1))
            layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        view = QPainter(layer)
        view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        view.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.draw_map(view)
        self.draw_cars(view)
        view.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        view.drawPixmap(0, 0, self.view_mask(ratio))
        view.end()
        painter.drawPixmap(0, 0, layer)
        self.draw_player(painter)

    def draw_map(self, painter: QPainter):
        """Road, start & sector lines around car"""
        if not self.map_path:
            return
        offset_x, offset_y, rotation = self.map_view()
        painter.save()
        painter.translate(offset_x, offset_y)
        painter.rotate(rotation)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self.pen_edge)
        painter.drawPath(self.map_path)
        painter.setPen(self.pen_road)
        painter.drawPath(self.map_path)
        if self.wcfg["show_sector_line"] and self.sector_path:
            painter.setPen(self.pen_sector)
            painter.drawPath(self.sector_path)
        if self.wcfg["show_start_line"] and self.sfinish_path:
            painter.setPen(self.pen_start)
            painter.drawPath(self.sfinish_path)
        painter.restore()

    def draw_cars(self, painter: QPainter):
        """Opponents in view range"""
        veh_info = minfo.vehicles.dataSet
        painter.setPen(self.pen_car)
        for index in minfo.relative.drawOrder:
            data = veh_info[index]
            if data.isPlayer or data.relativeStraightDistance >= self.view_range:
                continue
            pos_x, pos_y = self.view_position(data)
            color = status_color(self.colors, data)
            painter.setBrush(color)
            if self.circle_shape:
                radius = self.car_size / 2
                painter.drawEllipse(QPointF(pos_x, pos_y), radius, radius)
            else:
                painter.save()
                painter.translate(pos_x, pos_y)
                painter.rotate(calc.degrees(-data.relativeOrientationRadians))
                painter.drawPath(self.car_path)
                painter.restore()
            if self.show_places:
                self.draw_place(painter, pos_x, pos_y, data.positionOverall, color)
                painter.setPen(self.pen_car)

    def draw_player(self, painter: QPainter):
        """Player car at its place in view, with glow"""
        theme = self.theme
        pos = QPointF(self.area_center, self.veh_offset_y)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.tint(theme.accent, 50))
        painter.drawEllipse(pos, self.car_size * 0.95, self.car_size * 0.95)
        painter.setPen(QPen(theme.text, max(self.car_size * 0.08, 1.2)))
        painter.setBrush(theme.accent)
        if self.circle_shape:
            painter.drawEllipse(pos, self.car_size / 2, self.car_size / 2)
        else:
            painter.save()
            painter.translate(pos)
            painter.drawPath(self.car_path)
            painter.restore()
        if self.show_places:
            player = minfo.vehicles.dataSet[minfo.vehicles.playerIndex]
            self.draw_place(painter, pos.x(), pos.y(), player.positionOverall, theme.accent)

    def draw_place(self, painter: QPainter, pos_x: float, pos_y: float, place: int, color):
        """Position number: inside dot, or in small badge beside arrow"""
        if self.circle_shape:
            size = self.car_size
            rect = QRectF(pos_x - size / 2, pos_y - size / 2, size, size)
            self.draw_text(painter, rect, f"{place}", "place", readable_on(color), CENTER, elide=False)
            return
        rect = QRectF(pos_x + self.car_size * 0.45, pos_y - self.car_size * 0.55 - self.place_h / 2,
                      self.place_w, self.place_h)
        rounded(painter, rect, self.place_h / 2, color)
        self.draw_text(painter, rect, f"{place}", "place", readable_on(color), CENTER, elide=False)
