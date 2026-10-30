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
Navigation Widget
"""

from math import hypot, isfinite
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

from .. import calculation as calc
from ..api_control import api
from ..module_info import NO_TRACK_MAP, TrackMap, minfo
from ._base import Overlay
from ._painter import fill_pixmap

if TYPE_CHECKING:
    from ..template.widget_config_types import NavigationConfig

VIEW_REBUILD = 0.25  # road drawn built again once car moved this fraction of view size (pixels) from where built


def map_segments_near(coords, closed: bool, center_x: float, center_y: float, radius: float) -> QPainterPath | None:
    """Path of map segments passing within radius of center, None if all do (whole map path drawn)

    Runs of consecutive segments, a run never ends at a node within radius: within radius, road drawn the same as
    with whole map path (same segments & joins). Closed map: segment from last node back to first included.
    """
    total = len(coords)
    count = total if closed else total - 1
    if count < 1:
        return None
    limit = radius * radius
    dists = [(pos_x - center_x) ** 2 + (pos_y - center_y) ** 2 for pos_x, pos_y in coords]
    near = []
    for index in range(count):
        next_index = index + 1 if index + 1 < total else 0
        if dists[index] <= limit or dists[next_index] <= limit:
            near.append(True)
            continue
        # Both nodes farther: segment passes within radius only if its point closest to center does
        pos_x1, pos_y1 = coords[index]
        delta_x = coords[next_index][0] - pos_x1
        delta_y = coords[next_index][1] - pos_y1
        length = delta_x * delta_x + delta_y * delta_y
        ratio = ((center_x - pos_x1) * delta_x + (center_y - pos_y1) * delta_y) / length if length else 0.0
        if 0.0 < ratio < 1.0:
            gap_x = pos_x1 + delta_x * ratio - center_x
            gap_y = pos_y1 + delta_y * ratio - center_y
            near.append(gap_x * gap_x + gap_y * gap_y <= limit)
        else:
            near.append(False)
    if all(near):
        return None
    path = QPainterPath()
    first = near.index(False) + 1 if closed else 0  # closed map: runs start after a far segment (none across node 0)
    drawing = False
    for step in range(count):
        index = (first + step) % count
        if near[index]:
            if not drawing:
                path.moveTo(*coords[index])
                drawing = True
            path.lineTo(*coords[index + 1 if index + 1 < total else 0])
        else:
            drawing = False
    return path


class NavigationMixin:
    """Map around car, scale & view turning with car, for classic & modern widget"""

    wcfg: "NavigationConfig"

    def setup_view(self, area_size: int, start_line_length: float | None = None,
                   sector_line_length: float | None = None):
        """View size & scale, car place in view, start & sector line length (default: options)"""
        self.area_size = area_size
        self.global_scale = self.area_size / max(self.wcfg["view_radius"], 5)
        self.area_center = self.area_size * 0.5
        self.view_range = self.wcfg["view_radius"] * 2.5
        self.veh_offset_y = self.area_size * max(self.wcfg["vehicle_offset"], 0)
        self.start_line_length = self.wcfg["start_line_length"] if start_line_length is None else start_line_length
        self.sector_line_length = self.wcfg["sector_line_length"] if sector_line_length is None else sector_line_length
        # Road drawn (see view_map_path): within reach of farthest view corner from car, plus road width & distance
        # car moves before it is built again
        self.view_rebuild = self.area_size * VIEW_REBUILD
        corner_reach = max(hypot(corner_x - self.area_center, corner_y - self.veh_offset_y)
                           for corner_x in (0, self.area_size) for corner_y in (0, self.area_size))
        road_width = max(self.wcfg["map_width"], 2) + max(self.wcfg["map_outline_width"], 0)
        self.view_reach = corner_reach + road_width * 2 + self.view_rebuild
        self.view_center: tuple[float, float] | None = None  # car position on scaled map where road drawn was built
        self.view_path: QPainterPath | None = None  # road drawn, None: whole map
        # Last data
        self.last_veh_data_version: int | None = None
        self.last_modified: float | None = None  # None: nothing drawn yet
        self.map_closed = False  # map loop closed
        self.map_path: QPainterPath | None = None
        self.sfinish_path: QPainterPath | None = None
        self.sector_path: QPainterPath | None = None
        self.track_map: TrackMap = NO_TRACK_MAP  # map drawn (coordinates & sectors of one map)
        self.map_scaled: Any = None  # scaled coordinates of track map
        self.map_size = 1,1
        self.map_offset = 0,0

    def update_map(self, data) -> bool:
        """Map update, whether map changed (data of NO_TRACK_MAP: no map, widget creation)"""
        if self.last_modified != data:
            self.last_modified = data
            # Taken once: coordinates & sectors of the same map
            self.track_map = minfo.mapping.trackMap if data != NO_TRACK_MAP.lastModified else NO_TRACK_MAP
            self.create_map_path(self.track_map.coordinates)
            return True
        return False

    def car_map_point(self) -> tuple[float, float]:
        """Player car position on scaled map"""
        return (api.read.vehicle.position_longitudinal() * self.global_scale - self.map_offset[0],
                api.read.vehicle.position_lateral() * self.global_scale - self.map_offset[1])

    def map_view(self) -> tuple[float, float, float]:
        """Map transform: translation x, y, then rotation (degrees), car at its place in view"""
        # Transform map coordinates
        # Player vehicle orientation yaw radians + 180 deg rotation correction
        plr_ori_rad = api.read.vehicle.orientation_yaw_radians() + 3.14159265
        # x, y position & offset relative to player
        rot_pos_x, rot_pos_y = calc.rotate_coordinate(
            plr_ori_rad,   # plr_ori_rad, rotate view
            *self.car_map_point(),
        )
        return self.area_center - rot_pos_x, self.veh_offset_y - rot_pos_y, calc.degrees(plr_ori_rad)

    def view_map_path(self) -> QPainterPath | None:
        """Map path drawn: road around car (whole map if all of it is near), built again once car moved away from
        where it was built, so a repaint draws a few hundred nodes instead of the whole track"""
        if self.map_path is None or not self.map_scaled:
            return self.map_path
        pos_x, pos_y = self.car_map_point()
        center = self.view_center
        if center is None or not hypot(pos_x - center[0], pos_y - center[1]) <= self.view_rebuild:  # also nan
            if not (isfinite(pos_x) and isfinite(pos_y)):
                return self.map_path
            self.view_center = (pos_x, pos_y)
            self.view_path = map_segments_near(self.map_scaled, self.map_closed, pos_x, pos_y, self.view_reach)
        return self.map_path if self.view_path is None else self.view_path

    def view_position(self, veh_info) -> tuple[float, float]:
        """Opponent position in view (rotated position relative to player)"""
        # Position = raw position * global scale + offset
        return (veh_info.relativeRotatedPositionX * self.global_scale + self.area_center,
                veh_info.relativeRotatedPositionY * self.global_scale + self.veh_offset_y)

    def create_map_path(self, raw_coords=None):
        """Create map path, start & sector lines (line lengths from options)"""
        if raw_coords:
            map_path = QPainterPath()
            dist = calc.distance(raw_coords[0], raw_coords[-1])
            (self.map_scaled, self.map_size, self.map_offset
             ) = calc.zoom_map(raw_coords, self.global_scale)
            for index, coords in enumerate(self.map_scaled):
                if index == 0:
                    map_path.moveTo(*coords)
                else:
                    map_path.lineTo(*coords)
            # Close map loop if start & end distance less than 500 meters
            self.map_closed = dist < 500
            if self.map_closed:
                map_path.closeSubpath()
            # Create start/finish path, once start line known (official circuit shape: not yet)
            if self.track_map.start_known():
                sfinish_path = QPainterPath()
                self.create_sector_path(
                    sfinish_path, self.map_scaled, 0, self.start_line_length)
            else:
                sfinish_path = None
            # Create sectors paths
            sectors_index = self.track_map.sectors
            if isinstance(sectors_index, tuple):
                sector_path = QPainterPath()
                for index in sectors_index:
                    self.create_sector_path(
                        sector_path, self.map_scaled, index, self.sector_line_length
                    )
            else:
                sector_path = None
        else:
            self.map_scaled = None
            self.map_size = 1,1
            self.map_offset = 0,0
            self.map_closed = False
            map_path = None
            sfinish_path = None
            sector_path = None

        self.map_path = map_path
        self.view_center = self.view_path = None  # road drawn built again on new map
        self.sfinish_path = sfinish_path
        self.sector_path = sector_path

    def create_sector_path(self, path, dataset, node_index, length):
        """Create sector line path"""
        max_node = len(dataset) - 1
        pos_x1, pos_y1, pos_x2, pos_y2 = calc.line_intersect_coords(
            dataset[calc.zero_max(node_index, max_node)],  # point a
            dataset[calc.zero_max(node_index + 1, max_node)],  # point b
            1.57079633,  # 90 degree rotation
            length
        )
        path.moveTo(pos_x1, pos_y1)
        path.lineTo(pos_x2, pos_y2)
        return path


class Realtime(NavigationMixin, Overlay):
    """Draw widget"""

    wcfg: "NavigationConfig"

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
        self.setup_view(max(int(self.wcfg["display_size"]), 20))
        self.veh_size = max(int(self.wcfg["vehicle_size"]), 1)

        if self.wcfg["show_circle_vehicle_shape"]:
            self.veh_shape: QRectF | tuple[QPointF, ...] = QRectF(
                -self.veh_size * 0.5,
                -self.veh_size * 0.5,
                self.veh_size,
                self.veh_size,
            )
        else:
            self.veh_shape = (
                QPointF(0, -self.veh_size * 0.6),
                QPointF(self.veh_size * 0.5, self.veh_size * 0.4),
                QPointF(0, self.veh_size * 0.2),
                QPointF(-self.veh_size * 0.5, self.veh_size * 0.4),
            )
        self.veh_text_shape = QRectF(
            -self.veh_size * 0.5,
            -self.veh_size * 0.5 + font_m.voffset,
            self.veh_size,
            self.veh_size,
        )

        # Config canvas
        self.resize(self.area_size, self.area_size)
        self.pixmap_background = QPixmap(self.area_size, self.area_size)
        self.pixmap_mask = QPixmap(self.area_size, self.area_size)

        self.pen_text = {
            "opponent": QPen(self.wcfg["font_color"]),
            "player": QPen(self.wcfg["font_color_player"]),
        }
        self.pen_outline = {
            "opponent": self.set_pen_style(self.wcfg["vehicle_outline_color"], self.wcfg["vehicle_outline_width"]),
            "player": self.set_pen_style(self.wcfg["vehicle_outline_color_player"], self.wcfg["vehicle_outline_width_player"]),
            "map_outline": self.set_pen_style(self.wcfg["map_outline_color"], self.wcfg["map_width"] + self.wcfg["map_outline_width"], True),
            "map": self.set_pen_style(self.wcfg["map_color"], self.wcfg["map_width"], True),
            "sfinish": self.set_pen_style(self.wcfg["start_line_color"], self.wcfg["start_line_width"]),
            "sector": self.set_pen_style(self.wcfg["sector_line_color"], self.wcfg["sector_line_width"]),
        }
        self.brush_overall = {
            "player": self.set_brush_style(self.wcfg["vehicle_color_player"]),
            "leader": self.set_brush_style(self.wcfg["vehicle_color_leader"]),
            "same_lap": self.set_brush_style(self.wcfg["vehicle_color_same_lap"]),
            "laps_ahead": self.set_brush_style(self.wcfg["vehicle_color_laps_ahead"]),
            "laps_behind": self.set_brush_style(self.wcfg["vehicle_color_laps_behind"]),
            "in_pit": self.set_brush_style(self.wcfg["vehicle_color_in_pit"]),
            "yellow": self.set_brush_style(self.wcfg["vehicle_color_yellow"]),
        }

        self.draw_background()
        self.draw_map_mask_pixmap()
        self.update_map(NO_TRACK_MAP.lastModified)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        # Map
        modified = minfo.mapping.lastModified
        self.update_map(modified)

        # Vehicles
        veh_data_version = minfo.vehicles.dataSetVersion
        if self.last_veh_data_version != veh_data_version:
            self.last_veh_data_version = veh_data_version
            self.update()

    # GUI update methods

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Draw map
        self.draw_map_image(painter)
        # Draw vehicles
        self.draw_vehicle(painter, minfo.vehicles.dataSet, minfo.relative.drawOrder)
        # Apply mask
        if self.wcfg["show_fade_out"]:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            painter.drawPixmap(0, 0, self.pixmap_mask)
        # Draw background below map & mask
        if self.wcfg["show_background"] or self.wcfg["show_circle_background"]:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
            painter.drawPixmap(0, 0, self.pixmap_background)

    def draw_background(self):
        """Draw background"""
        if self.wcfg["show_background"]:
            fill_pixmap(self.pixmap_background, self.wcfg["background_color"])
        else:
            self.pixmap_background.fill(Qt.GlobalColor.transparent)

        # Draw circle background
        if self.wcfg["show_circle_background"]:
            painter = QPainter(self.pixmap_background)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            if self.wcfg["circle_outline_width"] > 0:
                pen = QPen()
                pen.setWidthF(self.wcfg["circle_outline_width"])
                pen.setColor(self.wcfg["circle_outline_color"])
                painter.setPen(pen)
            else:
                painter.setPen(Qt.PenStyle.NoPen)

            brush = QBrush(Qt.BrushStyle.SolidPattern)
            brush.setColor(self.wcfg["background_color_circle"])
            painter.setBrush(brush)
            painter.drawEllipse(QRectF(
                self.wcfg["circle_outline_width"],
                self.wcfg["circle_outline_width"],
                (self.area_center - self.wcfg["circle_outline_width"]) * 2,
                (self.area_center - self.wcfg["circle_outline_width"]) * 2,
            ))

    def draw_map_image(self, painter):
        """Draw map image"""
        # Apply center offset & rotation
        offset_x, offset_y, rotation = self.map_view()
        painter.translate(offset_x, offset_y)
        painter.rotate(rotation)

        map_path = self.view_map_path()
        if map_path:
            # Draw map outline
            if self.wcfg["map_outline_width"] > 0:
                painter.setPen(self.pen_outline["map_outline"])
                painter.drawPath(map_path)

            # Draw map
            painter.setPen(self.pen_outline["map"])
            painter.drawPath(map_path)

        # Draw start/finish line
        if self.wcfg["show_start_line"] and self.sfinish_path:
            painter.setPen(self.pen_outline["sfinish"])
            painter.drawPath(self.sfinish_path)

        # Draw sectors line
        if self.wcfg["show_sector_line"] and self.sector_path:
            painter.setPen(self.pen_outline["sector"])
            painter.drawPath(self.sector_path)

        painter.resetTransform()

    def draw_vehicle(self, painter, veh_info, veh_draw_order):
        """Draw vehicles"""
        if self.wcfg["show_circle_vehicle_shape"]:
            draw_shape = painter.drawEllipse
        else:
            draw_shape = painter.drawPolygon

        # Draw vehicle within view range
        total = len(veh_info)
        for index in veh_draw_order:
            if index >= total:  # car left since relative order made
                continue
            data = veh_info[index]
            # Draw player vehicle
            if data.isPlayer:
                painter.setPen(self.pen_outline["player"])
                painter.setBrush(self.color_vehicle(data))
                painter.translate(self.area_center, self.veh_offset_y)
                draw_shape(self.veh_shape)

                if self.wcfg["show_vehicle_class_standings"]:
                    painter.setPen(self.pen_text["player"])
                    painter.drawText(self.veh_text_shape, Qt.AlignmentFlag.AlignCenter, f"{data.positionOverall}")
                painter.resetTransform()

            # Draw opponent vehicle in view range
            elif data.relativeStraightDistance < self.view_range:
                pos_x, pos_y = self.view_position(data)
                painter.translate(pos_x, pos_y)

                if not self.wcfg["show_circle_vehicle_shape"]:
                    painter.rotate(calc.degrees(-data.relativeOrientationRadians))

                painter.setPen(self.pen_outline["opponent"])
                painter.setBrush(self.color_vehicle(data))
                draw_shape(self.veh_shape)

                if self.wcfg["show_vehicle_class_standings"]:
                    if not self.wcfg["show_circle_vehicle_shape"]:
                        painter.resetTransform()
                        painter.translate(pos_x, pos_y)
                    painter.setPen(self.pen_text["opponent"])
                    painter.drawText(self.veh_text_shape, Qt.AlignmentFlag.AlignCenter, f"{data.positionOverall}")
                painter.resetTransform()

    def draw_map_mask_pixmap(self):
        """Map mask pixmap"""
        self.pixmap_mask.fill(Qt.GlobalColor.black)
        painter = QPainter(self.pixmap_mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        rad_gra = QRadialGradient(self.area_center, self.area_center, self.area_center)
        rad_gra.setColorAt(calc.zero_one(self.wcfg["fade_in_radius"]), Qt.GlobalColor.transparent)
        rad_gra.setColorAt(calc.zero_one(self.wcfg["fade_out_radius"]), Qt.GlobalColor.black)
        painter.setBrush(rad_gra)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, self.area_size, self.area_size)

    # Additional methods
    def color_vehicle(self, veh_info):
        """Compare lap differences & set color"""
        if veh_info.isYellow and not veh_info.inPit:
            return self.brush_overall["yellow"]
        if veh_info.inPit and not veh_info.isPlayer:
            return self.brush_overall["in_pit"]
        if veh_info.isPlayer:
            return self.brush_overall["player"]
        if veh_info.positionOverall == 1:
            return self.brush_overall["leader"]
        if veh_info.isLapped > 0:
            return self.brush_overall["laps_ahead"]
        if veh_info.isLapped < 0:
            return self.brush_overall["laps_behind"]
        return self.brush_overall["same_lap"]

    def set_pen_style(self, color: str, width: float, rounded: bool = False):
        """Set pen style"""
        if width > 0:
            pen = QPen()
            pen.setWidthF(width)
            pen.setColor(color)
            if rounded:
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        else:
            pen = QPen(Qt.PenStyle.NoPen)
        return pen

    def set_brush_style(self, color: str):
        """Set brush style"""
        return QBrush(color, Qt.BrushStyle.SolidPattern)
