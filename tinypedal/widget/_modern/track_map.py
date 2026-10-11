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
Track map Widget, modern design

Track drawn as road with dark edge (readable over any background, optional panel), checkered
start line, sector marks in accent. Cars as dots with position, filled with class color (multi
class) or race status color, player larger with ring, proximity ring around player. Safety car
pill, pit out prediction rings (accent: estimated stop) with stop duration badges. Temporary
circle map until track is recorded. Sector performance: road of each sector colored by player's last
time in it (purple: session best sector, green: faster than sector of best lap, amber: slower). Cars
close to player on track (time gap within threshold) ringed.
"""

from __future__ import annotations

from math import atan2, degrees

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from ...api_control import api
from ...const_common import MAX_SECONDS
from ...module_info import minfo
from ..track_map import TrackMapMixin
from .base import CENTER, ModernOverlay
from .cars import car_colors, status_color
from .draw import panel, readable_on, rounded
from .rows import class_style

CHECKER_SQUARES = 4  # squares across road per row of start line
SECTOR_BEST, SECTOR_FASTER, SECTOR_SLOWER = "best", "positive", "warning"  # theme colors of sector performance
SAME_TIME = 0.0005  # seconds: sector time this close to best sector is best sector


def sector_performance(sectors) -> tuple[str | None, ...]:
    """Theme color of each sector by player's last time in it (session sectors), None if no time yet:
    session best sector, faster than sector of personal best lap, slower"""
    colors: list[str | None] = []
    for last, best, delta in zip(sectors.sectorPrev, sectors.sectorBestTB, sectors.deltaSectorBestPB):
        if not 0 < last < MAX_SECONDS:
            colors.append(None)
        elif last <= best + SAME_TIME:
            colors.append(SECTOR_BEST)
        elif delta < 0:
            colors.append(SECTOR_FASTER)
        else:
            colors.append(SECTOR_SLOWER)
    return tuple(colors)


def nearby_vehicles(threshold: float) -> frozenset[int]:
    """Indexes of cars within threshold seconds ahead of or behind player on track"""
    if threshold <= 0:
        return frozenset()
    relative = minfo.relative
    return frozenset(
        [index for gap, index in relative.relativeAhead if 0 < gap <= threshold]
        + [index for gap, index in relative.relativeBehind if -threshold <= gap < 0])


class Realtime(TrackMapMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "display_orientation", "display_detail_level", "area_size", "area_margin", "map_width",
        "show_background", "show_start_line", "show_sector_line", "show_proximity_circle", "proximity_circle_radius",
        "show_vehicle_class_standings", "enable_multi_class_styling", "show_custom_player_color_in_multi_class",
        "show_position_in_class", "vehicle_scale_player", "vehicle_scale", "show_lap_difference_outline",
        "show_safety_car", "vehicle_scale_safety_car", "safety_car_text", "show_pitout_prediction",
        "show_pitout_prediction_while_requested_pitstop", "number_of_prediction", "pitout_time_offset",
        "pitout_duration_minimum", "pitout_duration_increment", "enable_auto_pitout_prediction",
        "auto_prediction_additional_pitstop_time", "enable_fixed_pitout_prediction",
        *(f"fixed_pitstop_duration_{index}" for index in range(1, 11)), "show_pitstop_duration",
        "show_sector_performance", "show_nearby_vehicle_highlight", "nearby_vehicle_threshold",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        theme = self.theme
        self.add_font("place", 0.7, "bold")
        area_size = max(int(wcfg["area_size"]), 100)
        self.setup_map(area_size, min(max(int(wcfg["area_margin"]), 0), area_size // 4))
        self.set_size(area_size, area_size)
        self.colors = car_colors(theme)
        self.class_colors: dict[str, QColor] = {}
        self.show_places = bool(wcfg["show_vehicle_class_standings"])
        self.multi_class = bool(wcfg["enable_multi_class_styling"])
        self.player_color_in_class = bool(wcfg["show_custom_player_color_in_multi_class"])
        self.lap_outline = bool(wcfg["show_lap_difference_outline"])
        self.show_proximity = bool(wcfg["show_proximity_circle"])
        self.show_safety_car = bool(wcfg["show_safety_car"])
        self.show_prediction = bool(wcfg["show_pitout_prediction"])
        self.safety_car_text = self.user_text("safety_car_text", "SC")
        self.show_sector_performance = bool(wcfg["show_sector_performance"])
        self.nearby_threshold = (max(float(wcfg["nearby_vehicle_threshold"]), 0.0)
                                 if wcfg["show_nearby_vehicle_highlight"] else 0.0)
        self.sector_colors: tuple[str | None, ...] = ()
        self.nearby: frozenset[int] = frozenset()

        # Car dots: fit 2 digit position
        base = max(self.text_width("place", "88") + unit * 0.45, unit * 1.2) / 2
        self.dot = base * max(float(wcfg["vehicle_scale"]), 1.0)
        self.dot_player = base * max(float(wcfg["vehicle_scale_player"]), 1.0) * 1.15
        self.dot_safety = base * max(float(wcfg["vehicle_scale_safety_car"]), 1.0)
        self.pen_dot = QPen(theme.tint(theme.surface, 220), max(unit * 0.09, 1.0))
        self.pen_player = QPen(theme.text, max(unit * 0.14, 1.5))
        self.pen_lap = {
            1: QPen(theme.lap_ahead, max(unit * 0.14, 1.5)),
            -1: QPen(theme.blue, max(unit * 0.14, 1.5)),
        }

        # Road: dark edge, road over it
        road = max(float(wcfg["map_width"]), 1.0)
        self.road = road
        self.pen_edge = QPen(theme.tint(theme.surface, 230), road + max(road * 0.7, 3.0))
        self.pen_road = QPen(theme.text, road)
        for pen in (self.pen_edge, self.pen_road):
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen_sector = QPen(theme.accent, max(road * 0.6, 2.0))
        self.pen_sector.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen_proximity = QPen(theme.tint(theme.text, 90), max(unit * 0.08, 1.0))
        self.pen_proximity.setDashPattern((3.0, 3.0))
        width = max(unit * 0.14, 1.5)
        self.pen_nearby = QPen(theme.warning, width)
        self.pen_prediction = QPen(theme.negative, width)
        self.pen_auto_prediction = QPen(theme.positive, width)

        # Pit stop duration badge, above prediction ring
        badge_w = self.text_width("place", "888") + unit * 0.5
        badge_h = self.metrics["place"].height() + unit * 0.2
        self.badge = QRectF(-badge_w / 2, -self.dot - unit * 0.2 - badge_h, badge_w, badge_h)
        safety_w = max(self.text_width("place", self.safety_car_text) + unit * 0.6, self.dot_safety * 2)
        self.safety_rect = QRectF(-safety_w / 2, -self.dot_safety, safety_w, self.dot_safety * 2)

        self.map_paths: tuple[QPainterPath, ...] = ()
        self.sector_paths: tuple[QPainterPath, ...] = ()
        self.update_map(-1)

    def update_map(self, data):
        """Map update: paths & static layer"""
        if self.last_modified != data:
            self.last_modified = data
            raw_data = minfo.mapping.coordinates if data != -1 else None
            sector_paths, map_full_path = self.create_map_path(raw_data)
            self.map_paths = (map_full_path,)
            self.sector_paths = tuple(sector_paths) if self.map_scaled else ()
            self.redraw_static()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.update_map(minfo.mapping.lastModified)
        if self.show_sector_performance:
            colors = sector_performance(minfo.sectors.sessionBest)
            if colors != self.sector_colors:  # player completed a sector
                self.sector_colors = colors
                self.redraw_static()
        nearby = nearby_vehicles(self.nearby_threshold)
        if nearby != self.nearby:
            self.nearby = nearby
            self.update()
        self.refresh(minfo.vehicles.dataSetVersion)

    def paint_static(self, painter: QPainter):
        theme = self.theme
        if self.wcfg["show_background"]:
            panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for pen in (self.pen_edge, self.pen_road):
            painter.setPen(pen)
            for path in self.map_paths:
                painter.drawPath(path)
        if self.show_sector_performance:
            self.draw_sector_performance(painter)
        if self.map_scaled:
            sectors = minfo.mapping.sectors
            if self.wcfg["show_sector_line"] and isinstance(sectors, tuple):
                painter.setPen(self.pen_sector)
                for index in sectors:
                    if 0 <= index < len(self.map_scaled) - 1:
                        x1, y1, x2, y2 = self.map_line(index, self.road * 1.4)
                        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            if self.wcfg["show_start_line"] and len(self.map_scaled) > 1:
                (x1, y1), (x2, y2) = self.map_scaled[0], self.map_scaled[1]
                self.draw_start_line(painter, QPointF(x1, y1), degrees(atan2(y2 - y1, x2 - x1)))
        elif self.wcfg["show_start_line"]:
            self.draw_start_line(painter, QPointF(self.area_margin, self.area_size * 0.5), 90.0)

    def draw_sector_performance(self, painter: QPainter):
        """Road of each sector timed in its sector performance color"""
        theme = self.theme
        for path, color in zip(self.sector_paths, self.sector_colors):
            if color is None:
                continue
            pen = QPen(getattr(theme, color), self.road)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPath(path)

    def draw_start_line(self, painter: QPainter, pos: QPointF, direction: float):
        """Checkered line across road at pos, road heading direction (degrees)"""
        theme = self.theme
        length = max(self.road * 3.2, self.unit * 0.9)
        square = length / CHECKER_SQUARES
        painter.save()
        painter.translate(pos)
        painter.rotate(direction)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.tint(theme.surface, 230))
        painter.drawRect(QRectF(-square - 1, -length / 2 - 1, square * 2 + 2, length + 2))
        for row in range(2):
            for column in range(CHECKER_SQUARES):
                light = (row + column) % 2 == 0
                painter.setBrush(theme.text if light else theme.surface)
                painter.drawRect(QRectF(-square + row * square, -length / 2 + column * square, square, square))
        painter.restore()

    def paint(self, painter: QPainter):
        veh_info = minfo.vehicles.dataSet
        draw_order = minfo.relative.drawOrder
        on_map = bool(self.map_scaled)
        player = None
        for index in draw_order:
            data = veh_info[index]
            if on_map:
                pos_x, pos_y = self.map_position(data)
            else:
                pos_x, pos_y = self.circle_position(data, self.unit)
            if data.isPlayer:
                player = (data, pos_x, pos_y)
                continue
            self.draw_car(painter, data, pos_x, pos_y, index in self.nearby and not data.inPit)
        if player is not None:  # player on top
            data, pos_x, pos_y = player
            if on_map and self.show_proximity:
                radius = max(self.wcfg["proximity_circle_radius"], 1) * self.map_scale
                painter.setPen(self.pen_proximity)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(pos_x, pos_y), radius, radius)
            self.draw_car(painter, data, pos_x, pos_y)
        if on_map and self.show_safety_car and api.read.lap.safety_car_active():
            self.draw_safety_car(painter)
        if self.show_prediction and veh_info:
            self.draw_predictions(painter, veh_info[minfo.vehicles.playerIndex])

    def car_color(self, veh_info) -> QColor:
        """Class color (multi class) or race status color"""
        if self.multi_class and not (veh_info.isYellow and not veh_info.inPit) and not (
                veh_info.inPit and not veh_info.isPlayer):
            if veh_info.isPlayer and self.player_color_in_class:
                return self.colors.player
            color = self.class_colors.get(veh_info.vehicleClass)
            if color is None:
                color = self.class_colors[veh_info.vehicleClass] = class_style(
                    self.cfg, veh_info.vehicleClass, self.theme)[1]
            return color
        return status_color(self.colors, veh_info)

    def draw_car(self, painter: QPainter, data, pos_x: float, pos_y: float, nearby: bool = False):
        """Car dot with position, ringed if close to player"""
        color = self.car_color(data)
        center = QPointF(pos_x, pos_y)
        if nearby:
            ring = self.dot + max(self.unit * 0.22, 2.0)
            painter.setPen(self.pen_nearby)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, ring, ring)
        if data.isPlayer:
            radius = self.dot_player
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.theme.tint(self.theme.accent, 60))
            painter.drawEllipse(center, radius * 1.5, radius * 1.5)
            painter.setPen(self.pen_player)
        else:
            radius = self.dot
            if self.lap_outline and data.isLapped:
                painter.setPen(self.pen_lap[1 if data.isLapped > 0 else -1])
            else:
                painter.setPen(self.pen_dot)
        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)
        if self.show_places:
            rect = QRectF(pos_x - radius, pos_y - radius, radius * 2, radius * 2)
            self.draw_text(painter, rect, f"{self.place_number(data)}", "place", readable_on(color), CENTER, elide=False)

    def draw_safety_car(self, painter: QPainter):
        """Safety car pill"""
        position = self.safetycar_position(self.map_scaled)
        if position is None:
            return
        theme = self.theme
        rect = self.safety_rect.translated(*position)
        painter.setPen(self.pen_dot)
        painter.setBrush(theme.caution)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        self.draw_text(painter, rect, self.safety_car_text, "place", readable_on(theme.caution), CENTER, elide=False)

    def draw_predictions(self, painter: QPainter, player):
        """Pit out prediction rings, stop duration badges"""
        theme = self.theme
        show_duration = self.wcfg["show_pitstop_duration"]
        for pos_x, pos_y, pit_time, auto in self.pitout_predictions(self.map_scaled, player):
            painter.setPen(self.pen_auto_prediction if auto else self.pen_prediction)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(pos_x, pos_y), self.dot, self.dot)
            if show_duration:
                badge = self.badge.translated(pos_x, pos_y)
                fill = theme.positive if auto else theme.surface
                rounded(painter, badge, self.radius(0.3), theme.tint(fill, 235))
                self.draw_text(painter, badge, self.pitstop_duration_text(pit_time), "place",
                               readable_on(fill) if auto else theme.text, CENTER, elide=False)
