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
Radar Widget, modern design

Round radar fading out at its edge: rings every 10 meters, axis & diagonal guides, player car
(accent) in center, cars around colored by race status with windscreen toward their heading.
Side glow toward nearest car alongside (amber, red when close), collision course band ahead of
fast closing cars. Auto hide & fade out with distance of nearest car kept from classic radar.
"""

from __future__ import annotations

from itertools import islice

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient

from ... import calculation as calc
from ...module_info import minfo
from ..radar import IndicatorDimension, RadarMixin
from .base import ModernOverlay
from .cars import car_colors, status_color
from .draw import disc

RING_STEP = 10  # meters between distance rings


class Realtime(RadarMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "global_scale", "radar_radius", "vehicle_length", "vehicle_width", "show_vehicle_orientation",
        "show_edge_fade_out", "edge_fade_in_radius", "edge_fade_out_radius", "show_overlap_indicator",
        "show_overlap_indicator_in_cone_style", "overlap_cone_angle", "overlap_nearby_range_multiplier",
        "overlap_critical_range_multiplier", "indicator_size_multiplier", "show_collision_course",
        "collision_course_minimum_speed_difference", "collision_course_speed_increment_per_meter",
        "collision_course_nearby_range_multiplier", "collision_course_critical_range_multiplier",
        "show_center_mark", "show_angle_mark", "show_distance_circle", "enable_radar_fade",
        "radar_fade_in_radius", "radar_fade_out_radius", "enable_auto_hide", "enable_auto_hide_in_private_qualifying",
        "auto_hide_time_threshold", "auto_hide_minimum_distance_ahead", "auto_hide_minimum_distance_behind",
        "auto_hide_minimum_distance_side", "vehicle_maximum_visible_distance_ahead",
        "vehicle_maximum_visible_distance_behind", "vehicle_maximum_visible_distance_side",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.setup_radar()
        size = self.area_size
        self.set_size(size, size)
        self.center = QPointF(self.area_center, self.area_center)
        self.colors = car_colors(theme)
        scale = self.global_scale
        car_w = self.veh_width * scale
        car_l = self.veh_length * scale
        self.car_rect = QRectF(-car_w / 2, -car_l / 2, car_w, car_l)
        self.car_radius = min(car_w, car_l) * 0.3
        self.glass = QRectF(-car_w * 0.36, -car_l * 0.26, car_w * 0.72, car_l * 0.2)  # windscreen
        self.glass_color = theme.tint(theme.surface, 150)
        self.pen_car = QPen(theme.tint(theme.surface, 200), max(car_w * 0.06, 1.0))
        self.show_orientation = bool(wcfg["show_vehicle_orientation"])
        self.show_overlap = bool(wcfg["show_overlap_indicator"])
        self.show_collision = bool(wcfg["show_collision_course"])
        self.cone_style = bool(wcfg["show_overlap_indicator_in_cone_style"])
        self.nearby = theme.warning
        self.critical = theme.negative
        self.coll_rect = self.car_rect.adjusted(0, -size * 1.5, 0, -car_l / 2)
        self.coll_colors = (theme.tint(theme.warning, 70), theme.tint(theme.negative, 90))
        if self.cone_style:
            angle = max(wcfg["overlap_cone_angle"], 10)
            self.cone_left = round(calc.asym_max(180 - angle / 2, 90, 180) * 16), round(angle * 16)
            self.cone_right = round(calc.asym_max(0 - angle / 2, -270, 90) * 16), round(angle * 16)
            self.cone_brushes = tuple(self.cone_brush(color) for color in (self.nearby, self.critical))
        self.alpha_mask: QPixmap | None = None

    def design_unit(self) -> float:
        """Radar size sets size"""
        return max(self.area_size_option() / 30, 6.0)

    def area_size_option(self) -> float:
        """Radar size from options (before radar setup)"""
        radius = max(self.wcfg["radar_radius"], 5)
        return round(radius * max(self.wcfg["global_scale"], 5 / radius)) * 2

    def cone_brush(self, color: QColor) -> QBrush:
        """Cone indicator fill: color fading out from center"""
        gradient = QRadialGradient(self.center, self.area_center)
        gradient.setColorAt(0.1, self.theme.tint(color, 200))
        gradient.setColorAt(1.0, self.theme.tint(color, 0))
        return QBrush(gradient)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        veh_data_version = minfo.vehicles.dataSetVersion
        if self.last_veh_data_version != veh_data_version:
            self.last_veh_data_version = veh_data_version
            show_radar = self.is_radar_visible()
            if show_radar or self.show_radar != show_radar:
                self.show_radar = show_radar
                self.update()

    def edge_mask(self, ratio: float) -> QPixmap:
        """Edge fade: transparent center, opaque toward edge (erases what is under it)"""
        mask = self.alpha_mask
        if mask is not None and mask.devicePixelRatio() == ratio:
            return mask
        size = self.area_size
        mask = QPixmap(max(round(size * ratio), 1), max(round(size * ratio), 1))
        mask.setDevicePixelRatio(ratio)
        mask.fill(Qt.GlobalColor.black)
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        gradient = QRadialGradient(self.center, self.area_center)
        fade_out = calc.zero_one(self.wcfg["edge_fade_out_radius"])
        gradient.setColorAt(min(calc.zero_one(self.wcfg["edge_fade_in_radius"]), fade_out), Qt.GlobalColor.transparent)
        gradient.setColorAt(fade_out, Qt.GlobalColor.black)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QRectF(0, 0, size, size))
        painter.end()
        self.alpha_mask = mask
        return mask

    def paintEvent(self, event):
        """Background & player car, cars, edge fade, radar fade"""
        if not self.show_radar:
            return
        self._texts_drawn = 0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, self.static_layer())
        self.draw_cars(painter)
        if self.wcfg["show_edge_fade_out"]:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            painter.drawPixmap(0, 0, self.edge_mask(self.devicePixelRatioF()))
        alpha = self.radar_alpha()
        if alpha < 1:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            painter.fillRect(self.rect(), QColor(0, 0, 0, round(alpha * 255)))

    def paint_static(self, painter: QPainter):
        theme = self.theme
        wcfg = self.wcfg
        size = self.area_size
        center = self.center
        disc(painter, QRectF(0.5, 0.5, size - 1, size - 1), theme, self.depth_effects,
             theme.tint(theme.surface, 200))
        guide = QPen(theme.tint(theme.text, 26), 1)
        guide.setCosmetic(True)
        painter.setPen(guide)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = self.area_center
        if wcfg["show_distance_circle"]:
            for meters in range(RING_STEP, int(self.radar_radius) + 1, RING_STEP):
                ring = meters * self.global_scale
                if ring < radius - 1:
                    painter.drawEllipse(center, ring, ring)
        guide.setColor(theme.tint(theme.text, 18))
        painter.setPen(guide)
        if wcfg["show_center_mark"]:
            painter.drawLine(QPointF(0, center.y()), QPointF(size, center.y()))
            painter.drawLine(QPointF(center.x(), 0), QPointF(center.x(), size))
        if wcfg["show_angle_mark"]:
            offset = radius * 0.7071
            painter.drawLine(QPointF(center.x() - offset, center.y() - offset), QPointF(center.x() + offset, center.y() + offset))
            painter.drawLine(QPointF(center.x() - offset, center.y() + offset), QPointF(center.x() + offset, center.y() - offset))
        # Player car, glow under it
        glow = QRadialGradient(center, self.car_rect.height() * 1.1)
        glow.setColorAt(0.0, theme.tint(theme.accent, 70))
        glow.setColorAt(1.0, theme.tint(theme.accent, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, self.car_rect.height() * 1.1, self.car_rect.height() * 1.1)
        painter.save()
        painter.translate(center)
        self.draw_car(painter, self.colors.player)
        painter.restore()

    def draw_car(self, painter: QPainter, color: QColor):
        """Car body & windscreen at origin, front up"""
        painter.setPen(self.pen_car)
        painter.setBrush(color)
        painter.drawRoundedRect(self.car_rect, self.car_radius, self.car_radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.glass_color)
        painter.drawRoundedRect(self.glass, self.car_radius * 0.5, self.car_radius * 0.5)

    def draw_cars(self, painter: QPainter):
        """Opponents in radar range, overlap indicator under them"""
        indicator = self.indicator_dimension
        visible = self.visible_range
        scale = self.global_scale
        center = self.area_center
        nearest_left = -indicator.max_range_x
        nearest_right = indicator.max_range_x
        cars = []
        for veh_info in islice(minfo.vehicles.dataSet, minfo.vehicles.totalVehicles):
            if veh_info.isPlayer:
                continue
            # -x = left, +x = right, -y = ahead, +y = behind
            pos_x = veh_info.relativeRotatedPositionX
            pos_y = veh_info.relativeRotatedPositionY
            if not (visible.behind > pos_y > -visible.ahead and -visible.side < pos_x < visible.side):
                continue
            if self.show_overlap and abs(pos_x) < indicator.max_range_x and abs(pos_y) < indicator.max_range_y:
                if -indicator.min_range_x > pos_x > nearest_left:
                    nearest_left = pos_x
                if indicator.min_range_x < pos_x < nearest_right:
                    nearest_right = pos_x
            cars.append(veh_info)
        if self.show_overlap:
            self.draw_overlap(painter, nearest_left, nearest_right, indicator)
        for veh_info in cars:
            painter.save()
            painter.translate(veh_info.relativeRotatedPositionX * scale + center,
                              veh_info.relativeRotatedPositionY * scale + center)
            if self.show_orientation:
                painter.rotate(calc.degrees(-veh_info.relativeOrientationRadians))
            if self.show_collision:
                level = self.collision_level(veh_info)
                if level:
                    painter.fillRect(self.coll_rect, self.coll_colors[level - 1])
            self.draw_car(painter, status_color(self.colors, veh_info))
            painter.restore()

    def draw_overlap(self, painter: QPainter, nearest_left: float, nearest_right: float, indicator: IndicatorDimension):
        """Glow toward nearest car alongside, stronger as it gets closer"""
        for nearest, left_side in ((nearest_left, True), (nearest_right, False)):
            distance = abs(nearest)
            if distance >= indicator.max_range_x:
                continue
            alpha = min(max(1 - (distance - indicator.min_range_x) / indicator.max_range_x, 0.0), 1.0)
            color = self.critical if distance <= indicator.crit_range else self.nearby
            painter.setOpacity(alpha)
            if self.cone_style:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.cone_brushes[distance <= indicator.crit_range])
                start, span = self.cone_left if left_side else self.cone_right
                painter.drawPie(QRectF(0, 0, self.area_size, self.area_size), start, span)
            else:
                x = nearest * self.global_scale + self.area_center
                width = indicator.width
                if left_side:  # glow from car edge outward (left)
                    band = QRectF(x + indicator.offset - width, 0, width, self.area_size)
                    gradient = QLinearGradient(band.right(), 0, band.left(), 0)
                else:
                    band = QRectF(x - indicator.offset, 0, width, self.area_size)
                    gradient = QLinearGradient(band.left(), 0, band.right(), 0)
                gradient.setColorAt(0.0, self.theme.tint(color, 0))
                gradient.setColorAt(0.08, self.theme.tint(color, 210))
                gradient.setColorAt(1.0, self.theme.tint(color, 0))
                painter.fillRect(band, gradient)
            painter.setOpacity(1.0)
