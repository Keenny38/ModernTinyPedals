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
Track map Widget
"""

from collections.abc import Callable
from math import isfinite
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap, QStaticText, QTransform

from .. import calculation as calc
from ..api_control import api
from ..demo_state import drawing_demo
from ..formatter import random_color_class
from ..i18n import tr_overlay
from ..module_info import NO_TRACK_MAP, TrackMap, minfo
from ..userfile.corner_coach import MapCorners, map_corners
from ..validator import vehicle_position_interp
from ._base import Overlay
from ._painter import fill_pixmap, fill_rect

if TYPE_CHECKING:
    from ..template.widget_config_types import TrackMapConfig


class TrackMapMixin:
    """Map geometry, car, safety car & pit out prediction positions, official corners, for classic & modern widget"""

    wcfg: "TrackMapConfig"

    def setup_map(self, area_size: int, area_margin: int):
        """Map area & options, last data"""
        self.show_position_in_class = self.wcfg["enable_multi_class_styling"] and self.wcfg["show_position_in_class"]
        self.display_detail_level = max(self.wcfg["display_detail_level"], 0)
        self.area_size = area_size
        self.area_margin = area_margin
        self.temp_map_size = self.area_size - self.area_margin * 2

        if self.wcfg["show_pitout_prediction"]:
            self.show_while_requested = self.wcfg["show_pitout_prediction_while_requested_pitstop"]
            self.prediction_count = min(max(self.wcfg["number_of_prediction"], 1), 20)
            self.pitout_time_offset = max(self.wcfg["pitout_time_offset"], 0)
            self.min_pit_time = self.wcfg["pitout_duration_minimum"] + self.pitout_time_offset
            self.pit_time_increment = max(self.wcfg["pitout_duration_increment"], 1)
            self.auto_pit_time: float = -1
            if self.wcfg["enable_fixed_pitout_prediction"]:
                self.fixed_pit_times = tuple(sorted(set(self.set_fixed_pit_time())))

        if self.wcfg["show_safety_car"]:
            self.gen_position_interp = vehicle_position_interp()
        self.safetycar_pos: tuple[float, float] | None = None  # set by update_safetycar, read by paint
        # Pit out predictions, set by update_predictions, read by paint (None: not updated yet, picture)
        self.predictions: tuple | None = None
        # Official corners of recorded map, set by update_corners (None: not placed yet)
        self.show_corner_numbers = bool(self.wcfg["show_corner_numbers"])
        self.map_corners: MapCorners | None = None

        # Last data
        self.last_modified: float = 0
        self.last_orientation = 0.0
        self.last_veh_data_version: int | None = None
        # Car positions, set by update (vehicle_positions), read by paint (None: not updated yet, picture)
        self.car_positions: tuple[tuple[int, float, float], ...] | None = None
        self.track_map: TrackMap = NO_TRACK_MAP  # map drawn (coordinates, distances & sectors of one map)
        self.circular_map = False  # closed loop map
        self.map_scaled: Any = None  # scaled coordinates of track map, None without map
        self.map_range = (0, 10, 0, 10)
        self.map_scale = 1.0
        self.map_offset = (0, 0)
        self.map_orient = 0.0  # radians

    def map_changed(self, modified: float) -> bool:
        """True once per new track map or new orientation of track (modified -1: no map)"""
        orientation = minfo.mapping.orientation if modified != -1 else 0.0
        if self.last_modified == modified and self.last_orientation == orientation:
            return False
        self.last_modified = modified
        self.last_orientation = orientation
        return True

    def take_map(self, modified: float) -> TrackMap:
        """Track map to draw (taken once: coordinates, distances & sectors of the same map), none if modified -1"""
        self.track_map = minfo.mapping.trackMap if modified != -1 else NO_TRACK_MAP
        return self.track_map

    def no_map_text(self) -> str:
        """Text shown without track map (no circle: cars placed on a made-up track would mislead)"""
        return tr_overlay("Track map after one lap")

    def create_map_path(self, raw_coords=None):
        """Create map path (sector paths: one per sector, whole map if sector lines not known yet)"""
        map_sector_paths = []
        sectors_index = self.track_map.sectors
        if raw_coords:
            dist = calc.distance(raw_coords[0], raw_coords[-1])
            # Overlay orientation plus orientation of this track (track info editor), -90 is 270
            angle = int(self.wcfg["display_orientation"] + minfo.mapping.orientation) % 360
            self.map_orient = calc.radians(angle)
            (self.map_scaled, self.map_range, self.map_scale, self.map_offset
             ) = calc.scale_map(raw_coords, self.area_size, self.area_margin, angle)

            total_nodes = len(self.map_scaled) - 1
            skip_node = calc.skip_map_nodes(total_nodes, self.temp_map_size * 3, self.display_detail_level)
            last_skip = 0

            sectors_indexes = (0, *sectors_index) if isinstance(sectors_index, tuple) else (0,)
            map_sector_path = QPainterPath()  # replaced at index 0 (always a sector start)
            # Map sector path
            for index, coords in enumerate(self.map_scaled):
                if index in sectors_indexes:
                    last_skip = 0
                    if index > 0:  # close previous sector path
                        map_sector_path.lineTo(*coords)
                    # Create new sector path
                    map_sector_path = QPainterPath()
                    map_sector_path.moveTo(*coords)
                    # Add to sector path list
                    map_sector_paths.append(map_sector_path)
                elif index >= total_nodes:  # don't skip last node
                    map_sector_path.lineTo(*coords)
                elif last_skip >= skip_node:
                    map_sector_path.lineTo(*coords)
                    last_skip = 0
                last_skip += 1

            # Map full path
            map_full_path = QPainterPath()
            for index, coords in enumerate(self.map_scaled):
                if index in sectors_indexes:
                    last_skip = 0
                    if index == 0:
                        map_full_path.moveTo(*coords)
                    else:
                        map_full_path.lineTo(*coords)
                elif index >= total_nodes:  # don't skip last node
                    map_full_path.lineTo(*coords)
                elif last_skip >= skip_node:
                    map_full_path.lineTo(*coords)
                    last_skip = 0
                last_skip += 1

            # Close map loop if start & end distance less than 500 meters
            if dist < 500:
                map_sector_path.lineTo(*self.map_scaled[0])
                map_full_path.closeSubpath()
                self.circular_map = True
            else:
                self.circular_map = False

        # No map yet: nothing drawn (text instead)
        else:
            map_full_path = QPainterPath()
            self.map_scaled = None
            self.circular_map = False
            self.map_orient = 0
        return map_sector_paths, map_full_path

    def map_line(self, index: int, length: float) -> tuple[float, float, float, float]:
        """Line across recorded map at node index (start or sector line): x1, y1, x2, y2"""
        return calc.line_intersect_coords(
            self.map_scaled[index],  # point a
            self.map_scaled[index + 1],  # point b
            1.57079633,  # 90 degree rotation
            length
        )

    def map_position(self, veh_info) -> tuple[float, float]:
        """Car position on recorded map"""
        return self.map_point(veh_info.worldPositionX, veh_info.worldPositionY)

    def map_point(self, pos_x: float, pos_y: float) -> tuple[float, float]:
        """World position on recorded map"""
        # Position = coords * scale - (min_range * scale - offset)
        x_offset = self.map_range[0] * self.map_scale - self.map_offset[0]  # min range x, offset x
        y_offset = self.map_range[2] * self.map_scale - self.map_offset[1]  # min range y, offset y
        if self.map_orient:
            rot_x, rot_y = calc.rotate_coordinate(self.map_orient, pos_x, pos_y)
            return rot_x * self.map_scale - x_offset, rot_y * self.map_scale - y_offset
        return pos_x * self.map_scale - x_offset, pos_y * self.map_scale - y_offset

    def update_corners(self) -> bool:
        """Official corners of recorded map (placed in background thread, at once for overlay pictures), True when
        newly placed"""
        if not (self.show_corner_numbers and self.map_scaled):
            return False
        corners = map_corners(api.read.session.track_name(), self.track_map, drawing_demo())
        if corners is None or corners is self.map_corners:
            return False
        self.map_corners = corners
        return True

    def corner_labels(self, size_of: Callable[[str], tuple[float, float]],
                      clearance: float) -> list[tuple[str, QRectF]]:
        """Official corner labels outside their bend, clear of road (clearance from road center), a label over an
        earlier one left out: text & rect (size_of: label width & height of text)"""
        corners = self.map_corners
        if not corners or not self.map_scaled:
            return []
        placed: list[tuple[str, QRectF]] = []
        for corner, text in zip(corners.corners, corners.texts()):
            pos_x, pos_y = self.map_point(corner.x, corner.y)
            out_x, out_y = corner.out_x, corner.out_y
            if self.map_orient:
                out_x, out_y = calc.rotate_coordinate(self.map_orient, out_x, out_y)
            width, height = size_of(text)
            reach = clearance + abs(out_x) * width / 2 + abs(out_y) * height / 2
            rect = QRectF(pos_x + out_x * reach - width / 2, pos_y + out_y * reach - height / 2, width, height)
            if not any(rect.intersects(other) for _, other in placed):
                placed.append((text, rect))
        return placed

    def vehicle_positions(self) -> tuple[tuple[int, float, float], ...]:
        """Index & position on track map of each car in draw order (none without map), computed once per update,
        drawn by paint"""
        if not self.map_scaled:
            return ()
        veh_info = minfo.vehicles.dataSet
        total = len(veh_info)  # draw order of relative can list a car vehicles data no longer has (car left)
        position = self.map_position
        return tuple((index, *position(veh_info[index])) for index in minfo.relative.drawOrder if 0 <= index < total)

    def place_number(self, veh_info) -> int:
        """Overall or class position of car"""
        if self.show_position_in_class:
            return veh_info.positionInClass
        return veh_info.positionOverall

    def update_safetycar(self) -> tuple[float, float] | None:
        """Safety car position shown (None if none), interpolation advanced once per update (not per paint)"""
        position = None
        if self.wcfg["show_safety_car"] and self.map_scaled and api.read.lap.safety_car_active():
            found = self.safetycar_position(self.map_scaled)
            if found is not None:
                position = (found[0], found[1])
        self.safetycar_pos = position
        return position

    def safetycar_position(self, map_data) -> tuple[float, float] | None:
        """Safety car position on recorded map, None without map or lap distance data"""
        # Verify data set
        if not map_data:  # x, y coords
            return None
        dist_data = self.track_map.elevations
        if not dist_data:  # distance, z coords (none before start line known)
            return None
        dist_end_index = min(len(dist_data), len(map_data)) - 1
        # Interpolate safety car distance
        safetycar_dist = self.gen_position_interp.send((api.read.timing.elapsed(), api.read.lap.safety_car_distance()))
        # Interpolate safety car coordinates
        index_higher = calc.binary_search_higher_column(
            dist_data, safetycar_dist, 0, dist_end_index)
        if index_higher > 0:
            index_lower = index_higher - 1
            return calc.distance_interp_coordinate(
                map_data[index_higher][0],
                map_data[index_lower][0],
                map_data[index_higher][1],
                map_data[index_lower][1],
                dist_data[index_higher][0],
                dist_data[index_lower][0],
                safetycar_dist,
            )
        return map_data[0]

    def update_predictions(self) -> tuple:
        """Pit out predictions shown: ((x, y, pit time, auto estimated), ...), computed once per update (game
        data read, auto pit time set), not per paint"""
        predictions: tuple = ()
        if self.wcfg["show_pitout_prediction"]:
            index = minfo.vehicles.playerIndex
            if 0 <= index < len(minfo.vehicles.dataSet):  # none without player car (spectating)
                predictions = tuple(self.pitout_predictions(self.map_scaled, minfo.vehicles.dataSet[index]))
        self.predictions = predictions
        return predictions

    def shown_predictions(self) -> tuple:
        """Pit out predictions to draw: from last update, computed now before first update (overlay picture)"""
        if self.predictions is None:
            return self.update_predictions()
        return self.predictions

    def pitout_predictions(self, map_data, plr_veh_info):
        """Pit out prediction positions on recorded map: (x, y, pit time, auto estimated)"""
        # Skip drawing
        if not plr_veh_info.inPit:
            if not self.show_while_requested:  # if not in pit
                return
            if not plr_veh_info.pitRequested:  # not requested pit
                return

        # Verify data set
        if not map_data:  # x, y coords
            return
        dist_data = self.track_map.elevations
        if not dist_data:  # distance, z coords (none before start line known)
            return
        deltabest_data = minfo.delta.deltaBestData  # distance, seconds
        deltabest_max_index = len(deltabest_data) - 1
        if deltabest_max_index < 2:
            return
        laptime_best = deltabest_data[-1][1]
        laptime_pace = minfo.delta.lapTimePace
        if laptime_best < 1 or laptime_pace < 1:
            return

        laptime_scale = laptime_best / laptime_pace
        dist_end_index = min(len(dist_data), len(map_data)) - 1

        # Calculate pit timer & target time
        if plr_veh_info.pitRequested and not plr_veh_info.inPit:  # out pit lane
            pitin_time = target_node_time(minfo.mapping.pitEntryPosition, deltabest_data, deltabest_max_index, laptime_scale)
            pos_curr_time = target_node_time(api.read.lap.distance(), deltabest_data, deltabest_max_index, laptime_scale)
            pit_timer = pos_curr_time - pitin_time
            target_pit_time = self.min_pit_time
        else:  # in pit lane
            pit_timer = plr_veh_info.pitTimer.elapsed
            target_pit_time = target_pitstop_duration(pit_timer, self.min_pit_time, self.pit_time_increment)

        # Find time_into from deltabest_data, scale to match laptime_pace
        pitout_time = target_node_time(minfo.mapping.pitExitPosition, deltabest_data, deltabest_max_index, laptime_scale)
        pitout_time_extend = pit_timer + pitout_time

        for pit_time, auto_prediction in self.get_target_pit_time(target_pit_time, pit_timer, plr_veh_info.inPit):
            # Calc estimated pitout_time_into based on laptime_pace
            offset_time_into = pitout_time_extend - pit_time
            pitout_time_into = (offset_time_into - offset_time_into // laptime_pace * laptime_pace) * laptime_scale
            # Find estimated distance from deltabest_data
            index_higher = calc.binary_search_higher_column(
                deltabest_data, pitout_time_into, 0, deltabest_max_index, 1)
            if index_higher > 0:
                index_lower = index_higher - 1
                estimate_dist = calc.linear_interp(
                    pitout_time_into,
                    deltabest_data[index_lower][1],
                    deltabest_data[index_lower][0],
                    deltabest_data[index_higher][1],
                    deltabest_data[index_higher][0],
                )
            else:
                estimate_dist = 0

            dist_node_index = calc.binary_search_higher_column(dist_data, estimate_dist, 0, dist_end_index)
            pos_x, pos_y = map_data[dist_node_index]
            yield pos_x, pos_y, pit_time, auto_prediction

    def pitstop_duration_text(self, pit_time: float) -> str:
        """Pit stop duration of prediction"""
        return f"{min(pit_time - self.pitout_time_offset, 999):.0f}"

    def get_target_pit_time(self, target_pit_time: float, pit_timer: float, in_pit: bool):
        """Generate target pit time"""
        max_prediction = self.prediction_count
        pass_time = minfo.mapping.pitPassTime

        # Fixed time
        if self.wcfg["enable_fixed_pitout_prediction"]:
            valid_count = 0
            for fixed_time in self.fixed_pit_times:
                if valid_count >= max_prediction:
                    break
                fixed_time += pass_time
                if fixed_time > pit_timer:
                    valid_count += 1
                    yield fixed_time, False
        # Auto incremented time
        else:
            increment = self.pit_time_increment
            for idx in range(max_prediction):
                yield target_pit_time + increment * idx, False

        # Auto estimated time
        if self.wcfg["enable_auto_pitout_prediction"]:
            if in_pit != 1:
                est_stop_time = api.read.vehicle.pit_stop_time()
                if est_stop_time > 0:
                    est_stop_time += max(self.wcfg["auto_prediction_additional_pitstop_time"], 0)
                self.auto_pit_time = est_stop_time + pass_time + self.pitout_time_offset
            if self.auto_pit_time > pit_timer:
                yield self.auto_pit_time, True

    def set_fixed_pit_time(self):
        """Set fixed target pit time"""
        for idx in range(1, 11):
            fixed_time = self.wcfg[f"fixed_pitstop_duration_{idx}"]
            if fixed_time >= 0:
                yield fixed_time + self.pitout_time_offset


class Realtime(TrackMapMixin, Overlay):
    """Draw widget"""

    wcfg: "TrackMapConfig"
    max_repaint_rate = 25  # whole window repainted when any car moves

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

        # Config canvas
        area_size = max(self.wcfg["area_size"], 100)
        self.setup_map(area_size, min(max(self.wcfg["area_margin"], 0), int(area_size/4)))

        self.resize(self.area_size, self.area_size)
        self.pixmap_map = QPixmap(self.area_size, self.area_size)

        self.pen_text = {
            "opponent": QPen(self.wcfg["font_color"]),
            "player": QPen(self.wcfg["font_color_player"]),
            "safety_car": QPen(self.wcfg["font_color_safety_car"]),
            "pitstop_duration": QPen(self.wcfg["font_color_pitstop_duration"]),
        }
        self.pen_outline = {
            "opponent": self.set_pen_style(self.wcfg["vehicle_outline_color"], self.wcfg["vehicle_outline_width"]),
            "laps_ahead": self.set_pen_style(self.wcfg["vehicle_outline_color_laps_ahead"], self.wcfg["vehicle_outline_width_laps_ahead"]),
            "laps_behind": self.set_pen_style(self.wcfg["vehicle_outline_color_laps_behind"], self.wcfg["vehicle_outline_width_laps_behind"]),
            "player": self.set_pen_style(self.wcfg["vehicle_outline_color_player"], self.wcfg["vehicle_outline_width_player"]),
            "safety_car": self.set_pen_style(self.wcfg["vehicle_outline_color_safety_car"], self.wcfg["vehicle_outline_width_safety_car"]),
            "prediction": self.set_pen_style(self.wcfg["prediction_outline_color"], self.wcfg["prediction_outline_width"]),
            "auto_prediction": self.set_pen_style(self.wcfg["auto_prediction_outline_color"], self.wcfg["auto_prediction_outline_width"]),
            "proximity": self.set_pen_style(self.wcfg["proximity_circle_color"], self.wcfg["proximity_circle_width"]),
        }
        self.brush_classes = {}
        self.brush_overall = {
            "player": self.set_brush_style(self.wcfg["vehicle_color_player"]),
            "leader": self.set_brush_style(self.wcfg["vehicle_color_leader"]),
            "in_pit": self.set_brush_style(self.wcfg["vehicle_color_in_pit"]),
            "yellow": self.set_brush_style(self.wcfg["vehicle_color_yellow"]),
            "laps_ahead": self.set_brush_style(self.wcfg["vehicle_color_laps_ahead"]),
            "laps_behind": self.set_brush_style(self.wcfg["vehicle_color_laps_behind"]),
            "same_lap": self.set_brush_style(self.wcfg["vehicle_color_same_lap"]),
            "safety_car": self.set_brush_style(self.wcfg["vehicle_color_safety_car"]),
        }

        veh_size_base = self.wcfg["font_size"] + round(font_m.width * self.wcfg["bar_padding"])
        veh_size_opt = veh_size_base * max(self.wcfg["vehicle_scale"], 1.0)
        veh_size_plr = veh_size_base * max(self.wcfg["vehicle_scale_player"], 1.0)
        veh_size_sc = veh_size_base * max(self.wcfg["vehicle_scale_safety_car"], 1.0)

        self.veh_shape = QRectF(-veh_size_opt * 0.5, -veh_size_opt * 0.5, veh_size_opt, veh_size_opt)
        self.veh_shape_player = QRectF(-veh_size_plr * 0.5, -veh_size_plr * 0.5, veh_size_plr, veh_size_plr)
        self.veh_shape_safetycar = QRectF(-veh_size_sc * 0.5, -veh_size_sc * 0.5, veh_size_sc, veh_size_sc)
        self.veh_text_shape = QRectF(-veh_size_base * 0.5, -veh_size_base * 0.5 + font_m.voffset, veh_size_base, veh_size_base)

        # Per car drawing options & place number text laid out once per number
        self.show_proximity = self.wcfg["show_proximity_circle"]
        self.show_standings = self.wcfg["show_vehicle_class_standings"]
        self.place_texts: dict[int, tuple[QPointF, QStaticText] | None] = {}

        if self.wcfg["show_pitout_prediction"]:
            self.pit_text_shape = QRectF(
                -veh_size_base * 0.5 - 2,
                font_m.voffset - veh_size_opt * 0.5 - veh_size_base - 3,
                veh_size_base + 4,
                veh_size_base,
            )

        if self.wcfg["show_proximity_circle"]:
            self.rect_proximity = QRectF()

        if self.show_corner_numbers:
            self.corner_voffset = font_m.voffset
            self.pen_corner = QPen(self.wcfg["font_color_corner_numbers"])
            self.brush_corner = QBrush(self.wcfg["background_color_corner_numbers"], Qt.BrushStyle.SolidPattern)
        self.map_shapes: tuple[list, Any] = ([], None)  # map sector paths & full path (map image drawn again)
        self.update_map(-1)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        # Map
        self.update_map(minfo.mapping.lastModified)
        if self.update_corners():
            self.draw_map_image(*self.map_shapes, self.circular_map)
            self.update()

        # Vehicles, safety car & pit out predictions: repaint when drawn in other device pixels or style
        ratio = self.devicePixelRatioF()
        veh_data_version = minfo.vehicles.dataSetVersion
        if self.last_veh_data_version != veh_data_version or self.car_positions is None:
            self.last_veh_data_version = veh_data_version
            self.car_positions = self.vehicle_positions()
        safetycar = self.update_safetycar()
        show_duration = self.wcfg["show_pitout_prediction"] and self.wcfg["show_pitstop_duration"]
        key = (
            self.vehicles_key(self.car_positions, ratio),
            safetycar and device_point(*safetycar, ratio),
            tuple((device_point(pos_x, pos_y, ratio), show_duration and self.pitstop_duration_text(pit_time), auto)
                  for pos_x, pos_y, pit_time, auto in self.update_predictions()),
        )
        if self.changed("cars", key):
            self.request_update()

    def vehicles_key(self, positions: tuple, ratio: float) -> tuple:
        """Cars as drawn: position in device pixels, outline & fill style, place number"""
        veh_info = minfo.vehicles.dataSet
        show_standings = self.show_standings
        key = []
        for index, pos_x, pos_y in positions:
            data = veh_info[index]
            key.append((
                device_point(pos_x, pos_y, ratio), data.isPlayer, id(self.outline_vehicle(data)),
                id(self.color_vehicle(data)), show_standings and self.place_number(data),
            ))
        return tuple(key)

    # GUI update methods
    def update_map(self, data):
        """Map update"""
        if self.map_changed(data):
            map_sector_paths, map_full_path = self.create_map_path(self.take_map(data).coordinates)
            self.map_shapes = (map_sector_paths, map_full_path)
            self.map_corners = None  # placed again on new map
            self.draw_map_image(map_sector_paths, map_full_path, self.circular_map)
            self.car_positions = None  # map scale changed
            if self.wcfg["show_proximity_circle"]:
                self.update_proximity_rect()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap_map)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        positions = self.car_positions
        if positions is None:  # not updated yet (overlay picture)
            positions = self.vehicle_positions()
        if self.map_scaled:
            self.draw_vehicle_on_map(painter, minfo.vehicles.dataSet, positions)
            if self.safetycar_pos is not None:
                self.draw_safetycar_on_map(painter, self.map_scaled)
        if self.wcfg["show_pitout_prediction"]:
            self.draw_pitout_prediction(painter)

    def draw_map_image(self, map_sector_paths: list, map_full_path, circular_map=True):
        """Draw map image separately"""
        if self.wcfg["show_background"]:
            fill_pixmap(self.pixmap_map, self.wcfg["background_color"])
        else:
            self.pixmap_map.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.pixmap_map)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Draw map inner background
        if self.wcfg["show_map_background"] and circular_map:
            brush = QBrush(Qt.BrushStyle.SolidPattern)
            brush.setColor(self.wcfg["background_color_map"])
            painter.setBrush(brush)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(map_full_path)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # Set map pen style
        pen = QPen()
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)

        # Draw map outline
        if self.wcfg["map_outline_width"] > 0:
            pen.setWidthF(self.wcfg["map_width"] + self.wcfg["map_outline_width"])
            pen.setColor(self.wcfg["map_outline_color"])
            painter.setPen(pen)
            painter.drawPath(map_full_path)

        # Draw map
        map_colors = (
            self.wcfg["map_color_sector_1"],
            self.wcfg["map_color_sector_2"],
            self.wcfg["map_color_sector_3"],
        )
        pen.setWidthF(self.wcfg["map_width"])
        for map_sector_path, map_color in zip(map_sector_paths, map_colors):
            pen.setColor(map_color)
            painter.setPen(pen)
            painter.drawPath(map_sector_path)

        # Draw sector line
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        if self.map_scaled:
            # SF line (line across first 2 nodes), once start line known (official circuit shape: not yet)
            if self.wcfg["show_start_line"] and len(self.map_scaled) > 1 and self.track_map.start_known():
                pen.setWidthF(self.wcfg["start_line_width"])
                pen.setColor(self.wcfg["start_line_color"])
                painter.setPen(pen)
                pos_x1, pos_y1, pos_x2, pos_y2 = self.map_line(0, self.wcfg["start_line_length"])
                painter.drawLine(int(pos_x1), int(pos_y1), int(pos_x2), int(pos_y2))

            # Sector lines
            sectors_index = self.track_map.sectors
            if self.wcfg["show_sector_line"] and isinstance(sectors_index, tuple):
                pen.setWidthF(self.wcfg["sector_line_width"])
                pen.setColor(self.wcfg["sector_line_color"])
                painter.setPen(pen)

                for index in sectors_index:
                    if not 0 <= index < len(self.map_scaled) - 1:  # index out of map (edited or other map file)
                        continue
                    pos_x1, pos_y1, pos_x2, pos_y2 = self.map_line(index, self.wcfg["sector_line_length"])
                    painter.drawLine(int(pos_x1), int(pos_y1), int(pos_x2), int(pos_y2))

            if self.show_corner_numbers:
                self.draw_corner_numbers(painter)
        else:
            painter.setFont(self.font())
            painter.setPen(QPen(self.wcfg["font_color"]))
            painter.drawText(QRectF(self.area_margin, self.area_margin, self.temp_map_size, self.temp_map_size),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.no_map_text())

    def draw_corner_numbers(self, painter):
        """Draw official corner numbers (or names) outside their bend"""
        painter.setFont(self.font())
        metrics = QFontMetricsF(self.font())
        height = metrics.height()

        def size_of(text: str) -> tuple[float, float]:
            return max(metrics.horizontalAdvance(text) + height * 0.5, height), height

        clearance = (self.wcfg["map_width"] + max(self.wcfg["map_outline_width"], 0)) * 0.5 + 2
        for text, rect in self.corner_labels(size_of, clearance):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.brush_corner)
            painter.drawRoundedRect(rect, height * 0.25, height * 0.25)
            painter.setPen(self.pen_corner)
            painter.drawText(rect.translated(0, self.corner_voffset), Qt.AlignmentFlag.AlignCenter, text)

    def draw_vehicle_on_map(self, painter, veh_info, positions):
        """Draw vehicles on track map (index & position in draw order, see vehicle_positions)"""
        for index, pos_x, pos_y in positions:
            data = veh_info[index]
            painter.translate(pos_x, pos_y)

            painter.setPen(self.outline_vehicle(data))
            painter.setBrush(self.color_vehicle(data))

            if data.isPlayer:
                painter.drawEllipse(self.veh_shape_player)
                if self.show_proximity:
                    painter.setPen(self.pen_outline["proximity"])
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(self.rect_proximity)
            else:
                painter.drawEllipse(self.veh_shape)

            # Draw text standings
            if self.show_standings:
                if data.isPlayer:
                    painter.setPen(self.pen_text["player"])
                else:
                    painter.setPen(self.pen_text["opponent"])
                self.draw_place_number(painter, self.place_number(data))
            painter.resetTransform()

    def draw_place_number(self, painter, place: int):
        """Draw place number centered in car shape, static text laid out once per number"""
        if place in self.place_texts:
            cached = self.place_texts[place]
        else:
            cached = self.place_texts[place] = self.create_place_text(place)
        if cached is None:  # text exceeds car shape: clipped as drawText does
            painter.drawText(self.veh_text_shape, Qt.AlignmentFlag.AlignCenter, f"{place}")
        else:
            painter.drawStaticText(*cached)

    def create_place_text(self, place: int) -> tuple[QPointF, QStaticText] | None:
        """Position & static text of place number, None if glyphs exceed car shape (clipped by drawText)"""
        text = f"{place}"
        metrics = QFontMetricsF(self.font())
        rect = metrics.boundingRect(self.veh_text_shape, Qt.AlignmentFlag.AlignCenter, text)
        ink = metrics.tightBoundingRect(text).translated(rect.left(), rect.top() + metrics.ascent())
        if not self.veh_text_shape.contains(ink.adjusted(-1, -1, 1, 1)):  # 1 pixel antialiasing margin
            return None
        static_text = QStaticText(text)
        static_text.setTextFormat(Qt.TextFormat.PlainText)
        static_text.prepare(QTransform(), self.font())
        return rect.topLeft(), static_text

    def draw_safetycar_on_map(self, painter, map_data):
        """Draw safety car on map (position set by update_safetycar)"""
        position = self.safetycar_pos
        if position is None:
            return
        painter.translate(*position)
        painter.setPen(self.pen_outline["safety_car"])
        painter.setBrush(self.brush_overall["safety_car"])
        painter.drawEllipse(self.veh_shape_safetycar)
        painter.setPen(self.pen_text["safety_car"])
        painter.drawText(self.veh_text_shape, Qt.AlignmentFlag.AlignCenter, self.wcfg["safety_car_text"])
        painter.resetTransform()

    def draw_pitout_prediction(self, painter):
        """Draw pitout prediction circles (positions set by update_predictions)"""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for pos_x, pos_y, pit_time, auto_prediction in self.shown_predictions():
            painter.translate(pos_x, pos_y)
            painter.setPen(self.pen_outline["auto_prediction" if auto_prediction else "prediction"])
            painter.drawEllipse(self.veh_shape)

            # Draw text pitstop duration
            if self.wcfg["show_pitstop_duration"]:
                fill_rect(painter, self.pit_text_shape, self.wcfg["background_color_pitstop_duration"])
                painter.setPen(self.pen_text["pitstop_duration"])
                painter.drawText(self.pit_text_shape, Qt.AlignmentFlag.AlignCenter, self.pitstop_duration_text(pit_time))

            painter.resetTransform()

    def classes_style(self, class_name: str) -> QBrush:
        """Get vehicle class style from brush cache"""
        if class_name in self.brush_classes:
            return self.brush_classes[class_name]
        # Get vehicle class style from user defined dictionary
        styles = self.cfg.user.classes.get(class_name)
        if styles is not None:
            color = styles["color"]
        else:
            color = random_color_class(class_name)
        brush = QBrush(color, Qt.BrushStyle.SolidPattern)
        # Add to brush cache
        self.brush_classes[class_name] = brush
        return brush

    def update_proximity_rect(self):
        """Update proximity circle rect"""
        proxi_radius = max(self.wcfg["proximity_circle_radius"], 1)
        proxi_x = -proxi_radius * self.map_scale
        proxi_y = proxi_radius * 2 * self.map_scale
        self.rect_proximity.setRect(proxi_x, proxi_x, proxi_y, proxi_y)

    # Additional methods
    def outline_vehicle(self, veh_info):
        """Set vehicle outline"""
        if veh_info.isPlayer:
            return self.pen_outline["player"]
        if self.wcfg["show_lap_difference_outline"]:
            if veh_info.isLapped > 0:
                return self.pen_outline["laps_ahead"]
            if veh_info.isLapped < 0:
                return self.pen_outline["laps_behind"]
        return self.pen_outline["opponent"]

    def color_vehicle(self, veh_info):
        """Set vehicle color"""
        if veh_info.isYellow and not veh_info.inPit:
            return self.brush_overall["yellow"]
        if veh_info.inPit and not veh_info.isPlayer:
            return self.brush_overall["in_pit"]
        if self.wcfg["enable_multi_class_styling"]:
            if self.wcfg["show_custom_player_color_in_multi_class"] and veh_info.isPlayer:
                return self.brush_overall["player"]
            return self.classes_style(veh_info.vehicleClass)
        if veh_info.isPlayer:
            return self.brush_overall["player"]
        if veh_info.positionOverall == 1:
            return self.brush_overall["leader"]
        if veh_info.isLapped > 0:
            return self.brush_overall["laps_ahead"]
        if veh_info.isLapped < 0:
            return self.brush_overall["laps_behind"]
        return self.brush_overall["same_lap"]

    def set_pen_style(self, color: str, width: float):
        """Set pen style"""
        if width > 0:
            pen = QPen()
            pen.setWidthF(width)
            pen.setColor(color)
        else:
            pen = QPen(Qt.PenStyle.NoPen)
        return pen

    def set_brush_style(self, color: str):
        """Set brush style"""
        return QBrush(color, Qt.BrushStyle.SolidPattern)


def target_pitstop_duration(pit_timer: float, min_pit_time: float, pit_time_increment: float) -> float:
    """Target pitstop duration = min pit duration + pit duration increment * number of increments"""
    overflow_increments = max(pit_timer - min_pit_time + pit_time_increment, 0) // pit_time_increment
    return min_pit_time + pit_time_increment * overflow_increments


def device_point(pos_x: float, pos_y: float, ratio: float) -> tuple[int, int]:
    """Position in device pixels (0 if not finite): repaint key of a drawn position"""
    x, y = pos_x * ratio, pos_y * ratio
    return (round(x) if isfinite(x) else 0), (round(y) if isfinite(y) else 0)


def target_node_time(position: float, delta_data: tuple, max_index: int, laptime_scale: float) -> float:
    """Calculate target node time from target position and deltabest dataset"""
    pitin_node_index = calc.binary_search_higher_column(delta_data, position, 0, max_index, 0)
    return delta_data[pitin_node_index][1] / laptime_scale
