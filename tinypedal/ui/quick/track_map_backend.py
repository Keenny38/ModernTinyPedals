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
Track Map Viewer page state: track map file, position along track, curve & slope at position

Map coordinates are track map file (SVG) coordinates: meters, y down. Line widths of config are meters
(drawn at least a few pixels wide when zoomed out).
"""

from __future__ import annotations

import logging
import math
import os

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QWidget

from ... import calculation as calc
from ...const_file import ConfigType, FileExt, FileFilter
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.track_corners import TrackCorner, track_corners
from ...userfile.track_map import load_track_map_file
from ..lap_viewer import distance_unit
from ..track_map_geometry import config_grades, curve_at, curve_description, node_at
from .game_pictures import notifier, track_logo_url
from .lines import VertexStore, area, band, circle, colored_band, line_strip, merge_strips, segments

logger = logging.getLogger(__name__)

SECTOR_COLORS = (QColor("#38BDF8"), QColor("#A78BFA"), QColor("#F472B6"))
OVERLAYS = (  # (config key, menu text)
    ("show_map_info", "Map Info"),
    ("show_position_info", "Position Info"),
    ("show_curve_info", "Curve Info"),
    ("show_slope_info", "Slope Info"),
    ("show_center_mark", "Center Mark"),
    ("show_distance_circle", "Distance Circle"),
    ("show_osculating_circle", "Osculating Circle"),
    ("show_curve_section", "Curve Section"),
    ("show_highlighted_coordinates", "Highlighted Coordinates"),
    ("show_elevation_profile", "Elevation Profile"),
)
COLOR_KEYS = (
    "start_line_color", "sector_line_color", "curve_section_color", "osculating_circle_color",
    "highlighted_coordinates_color", "distance_circle_color", "center_mark_color",
)


class TrackMapBackend(QObject):
    """Track Map Viewer page state (QML context property "backend")"""

    mapChanged = Signal()
    logoChanged = Signal()  # map loaded, or circuit logo fetched from game
    positionChanged = Signal()
    configChanged = Signal()
    revisionChanged = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        notifier().changed.connect(self.logoChanged)
        self.mapChanged.connect(self.logoChanged)
        self._window = parent
        self.prefix = f"track_map_{id(self)}|"
        self.raw_coords: list[tuple[float, float]] = []
        self.raw_dists: list[tuple[float, float]] = []
        self.sectors: tuple[int, int] = (0, 0)
        self.map_name = ""
        self.map_length = 0.0
        self.curve_nodes = 10
        self.corners: list[TrackCorner] = []  # official corner numbers (or names) of circuit
        self.corners_numbered = True
        self._position = 0.0
        self._current: dict = {}
        self._meters_per_pixel = 1.0
        self._revision = 0
        self.ecfg = cfg.user.config["track_map_viewer"]
        self.grades = config_grades(self.ecfg)

    def release(self):
        VertexStore.remove_prefix(self.prefix)

    def key(self, name: str) -> str:
        return self.prefix + name

    def bump_revision(self):
        self._revision += 1
        self.revisionChanged.emit()

    # Properties
    @Property(int, notify=revisionChanged)
    def revision(self) -> int:
        return self._revision

    @Property(bool, notify=mapChanged)
    def loaded(self) -> bool:
        return bool(self.raw_coords)

    @Property(str, notify=mapChanged)
    def mapName(self) -> str:
        return self.map_name

    @Property(str, notify=logoChanged)
    def trackLogo(self) -> str:
        """Circuit logo of game for map name (track name)"""
        return track_logo_url(self.map_name) if self.map_name else ""

    @Property(float, notify=mapChanged)
    def length(self) -> float:
        return self.map_length

    @Property(int, notify=mapChanged)
    def nodes(self) -> int:
        return len(self.raw_coords)

    @Property(str, notify=mapChanged)
    def distanceUnit(self) -> str:
        """User distance unit symbol: m or ft"""
        return distance_unit()[1]

    @Property(float, notify=mapChanged)
    def distanceScale(self) -> float:
        """User distance unit per meter"""
        return distance_unit()[0]

    @Property(dict, notify=mapChanged)
    def view(self) -> dict:
        """Map bounds, vertex keys, sector lengths & elevation range"""
        if not self.raw_coords:
            return {}
        xs = [x for x, _ in self.raw_coords]
        ys = [y for _, y in self.raw_coords]
        heights = [height for _, height in self.raw_dists]
        bounds = self.sector_bounds()
        return {
            "minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys),
            "road": self.key("road"), "edge": self.key("edge"), "sectors": self.key("sectors"),
            "start": self.key("start"), "sectorLines": self.key("sector_lines"),
            "section": self.key("section"), "circle": self.key("circle"), "radius": self.key("radius"),
            "elevation": self.key("elevation"), "elevationLine": self.key("elevation_line"),
            "minZ": min(heights), "maxZ": max(heights),
            "sectorStarts": [0.0, *bounds], "sectorLengths": [
                end - start for start, end in zip([0.0, *bounds], [*bounds, self.map_length])],
            "sectorColors": [color.name() for color in SECTOR_COLORS],
            "corners": [
                {"x": corner.x, "y": corner.y, "label": self.corner_text(corner.label), "distance": corner.distance}
                for corner in self.corners
            ],
        }

    @Property(float, notify=positionChanged)
    def position(self) -> float:
        return self._position

    @Property(dict, notify=positionChanged)
    def current(self) -> dict:
        """Position, curve & slope at position"""
        return self._current

    @Property(int, notify=positionChanged)
    def curveNodes(self) -> int:
        return self.curve_nodes

    @Property(dict, notify=configChanged)
    def overlays(self) -> dict:
        return {key: bool(self.ecfg.get(key, True)) for key, _ in OVERLAYS}

    @Property(list, notify=configChanged)
    def overlayMenu(self) -> list[dict]:
        return [{"key": key, "text": tr(text), "checked": bool(self.ecfg.get(key, True))} for key, text in OVERLAYS]

    @Property(dict, notify=configChanged)
    def colors(self) -> dict:
        return {key: str(self.ecfg[key]) for key in COLOR_KEYS}

    @Property(dict, notify=configChanged)
    def settings(self) -> dict:
        """Position step, distance circles (meters), center mark size (pixels), position marker size"""
        return {
            "step": max(int(self.ecfg["position_increment_step"]), 1),
            "circles": [radius for radius in (self.ecfg[f"distance_circle_{index}_radius"] for index in range(10))
                        if radius > 0],
            "centerMark": float(self.ecfg["center_mark_radius"]),
            "marker": float(self.ecfg["highlighted_coordinates_size"]),
        }

    # Map file
    @Slot()
    def openMap(self):
        filename, _ = QFileDialog.getOpenFileName(self._window, dir=cfg.path.track_map, filter=FileFilter.SVG)
        if filename:
            self.load_map(os.path.dirname(filename) + "/", os.path.splitext(os.path.basename(filename))[0])

    def load_map(self, filepath: str, filename: str) -> bool:
        """Load track map file made by Mapping module, warning if missing or invalid"""
        from PySide6.QtWidgets import QMessageBox

        if not os.path.exists(f"{filepath}{filename}{FileExt.SVG}"):
            QMessageBox.warning(self._window, tr("Error"), trm(f"Cannot find track map for<br><b>{filename}</b><br>"))
            return False
        coords, dists, sectors = load_track_map_file(filepath=filepath, filename=filename)
        if not coords or len(coords) <= 9 or not dists:
            self.raw_coords, self.raw_dists, self.map_name, self.map_length = [], [], "", 0.0
            VertexStore.remove_prefix(self.prefix)
            self.mapChanged.emit()
            QMessageBox.warning(self._window, tr("Error"), trm(
                "Unable to load track map file from<br>"
                f"<b>{filepath}{filename}{FileExt.SVG}</b><br><br>"
                "Only support SVG file that generated with TinyPedal."))
            return False
        self.raw_coords = [(float(x), float(y)) for x, y in coords]
        self.raw_dists = [(float(distance), float(height)) for distance, height in dists]
        self.sectors = (int(sectors[0]), int(sectors[1])) if sectors else (0, 0)
        self.map_name = filename
        self.map_length = self.raw_dists[-1][0]
        nodes = sorted(zip(self.raw_dists, self.raw_coords))  # first node can be lap end
        self.corners, self.corners_numbered = track_corners(
            filename, [node[0][0] for node in nodes], [node[1][0] for node in nodes], [node[1][1] for node in nodes])
        self.build_static()
        self.build_scaled()
        self._position = 0.0
        self.update_position()
        self.bump_revision()
        self.mapChanged.emit()
        return True

    def corner_text(self, label: str) -> str:
        """Official corner shown: "T5" ("V5" in French), or translated name"""
        return trm(f"T{label}") if self.corners_numbered else tr(label)

    def corner_at(self, distance: float) -> str:
        """Official corner at track distance (nearest within 150 m), "" if none"""
        nearest = min(self.corners, key=lambda corner: abs(corner.distance - distance), default=None)
        if nearest is None or abs(nearest.distance - distance) > 150:
            return ""
        return self.corner_text(nearest.label)

    def sector_bounds(self) -> list[float]:
        """Track distance of sector 2 & 3 start"""
        nodes = len(self.raw_dists)
        return [self.raw_dists[min(index, nodes - 1)][0] for index in self.sectors if 0 < index < nodes]

    def is_closed(self) -> bool:
        return calc.distance(self.raw_coords[0], self.raw_coords[-1]) < 500

    def build_static(self):
        """Elevation profile (distance, elevation), by increasing distance (first node can be lap end)"""
        profile = sorted(self.raw_dists)
        distances = [distance for distance, _ in profile]
        heights = [height for _, height in profile]
        base = min(heights)
        VertexStore.set(self.key("elevation"), area(distances, heights, base))
        VertexStore.set(self.key("elevation_line"), line_strip(distances, heights))

    def width(self, meters: float, min_pixels: float = 2.0) -> float:
        """Half line width: config width in meters, at least some pixels when zoomed out"""
        return max(meters, min_pixels * self._meters_per_pixel) / 2

    def build_scaled(self):
        """Lines depending on map scale: road, outline, sectors, start & sector lines"""
        if not self.raw_coords:
            return
        xs = [x for x, _ in self.raw_coords]
        ys = [y for _, y in self.raw_coords]
        closed = self.is_closed()
        road = self.width(float(self.ecfg["map_width"]), 5.0)
        outline = road + self.width(float(self.ecfg["map_outline_width"]), 2.0)
        VertexStore.set(self.key("road"), band(xs, ys, road, closed))
        VertexStore.set(self.key("edge"), band(xs, ys, outline, closed))
        nodes = len(xs)
        starts = [0, *[index for index in self.sectors if 0 < index < nodes]]
        colors = []
        for index in range(nodes):
            sector = sum(1 for start in starts[1:] if index >= start)
            colors.append(SECTOR_COLORS[min(sector, 2)])
        if closed:
            xs, ys, colors = [*xs, xs[0]], [*ys, ys[0]], [*colors, colors[-1]]
        VertexStore.set(self.key("sectors"), colored_band(xs, ys, colors, self.width(0.0, 2.0)))
        start = self.cross_line(0, float(self.ecfg["start_line_length"]))
        VertexStore.set(self.key("start"), band(start[0::2], start[1::2], self.width(
            float(self.ecfg["start_line_width"]) / 2, 3.0)))
        sector_lines = [self.cross_line(index, float(self.ecfg["sector_line_length"])) for index in starts[1:]]
        half = self.width(float(self.ecfg["sector_line_width"]) / 2, 3.0)
        VertexStore.set(self.key("sector_lines"), merge_strips(
            [band(line[0::2], line[1::2], half) for line in sector_lines]))

    def cross_line(self, index: int, length: float) -> list[float]:
        """Line across track at node: x0, y0, x1, y1"""
        nodes = len(self.raw_coords)
        point_a = self.raw_coords[index % nodes]
        point_b = self.raw_coords[(index + 1) % nodes]
        return list(calc.line_intersect_coords(point_a, point_b, math.pi / 2, length))

    # Position along track
    @Slot(float)
    def setPosition(self, distance: float):
        self._position = max(0.0, min(float(distance), self.map_length))
        self.update_position()

    @Slot(int)
    def setCurveNodes(self, nodes: int):
        self.curve_nodes = max(3, min(int(nodes), 9999))
        self.update_position()

    @Slot(float, float, float, result=float)
    def pick(self, x: float, y: float, radius: float) -> float:
        """Track distance of node nearest to map point, -1 if farther than radius"""
        best, nearest = radius * radius, -1
        for index, (node_x, node_y) in enumerate(self.raw_coords):
            gap = (node_x - x) ** 2 + (node_y - y) ** 2
            if gap < best:
                best, nearest = gap, index
        return self.raw_dists[nearest][0] if nearest >= 0 else -1.0

    def update_position(self):
        """Curve section, osculating circle & info at position"""
        if not self.raw_coords:
            self._current = {}
            self.positionChanged.emit()
            return
        index = node_at(self.raw_dists, self._position)
        info = curve_at(self.raw_coords, self.raw_dists, self.map_length, self.curve_nodes, index)
        x, y = self.raw_coords[index]
        distance, height = self.raw_dists[index]
        length_desc = calc.select_grade(self.grades["length"], info.length)
        curve_desc = curve_description(info.radius, info.direction, self.grades["curve"])
        slope_desc = calc.select_grade(self.grades["slope"], abs(info.slope_percent))
        section_x = [point[0] for point in info.section]
        section_y = [point[1] for point in info.section]
        VertexStore.set(self.key("section"), band(section_x, section_y, self.width(
            float(self.ecfg["curve_section_width"]), 3.0)))
        circle_x, circle_y = circle(*info.center, info.radius) if info.radius < 1e5 else ([], [])
        VertexStore.set(self.key("circle"), band(circle_x, circle_y, self.width(
            float(self.ecfg["osculating_circle_width"]), 1.5)))
        first, last = info.section[0], info.section[-1]
        VertexStore.set(self.key("radius"), segments([
            (info.center[0], info.center[1], first[0], first[1]),
            (info.center[0], info.center[1], last[0], last[1]),
        ] if info.radius < 1e5 else []))
        self._current = {
            "node": index + 1, "distance": distance, "x": x, "y": y, "z": height,
            "yaw": math.degrees(info.yaw), "curveLength": info.length, "lengthDesc": tr(length_desc),
            "radius": info.radius, "radiusDesc": " ".join(tr(word) for word in curve_desc.split(" ")),
            "angle": info.angle, "direction": info.direction,
            "slope": info.slope_percent * 100, "slopeAngle": info.slope_angle, "slopeDelta": info.height_delta,
            "slopeDesc": tr(slope_desc), "centerX": info.center[0], "centerY": info.center[1],
            "sector": 1 + sum(1 for start in self.sector_bounds() if distance >= start),
            "corner": self.corner_at(distance),
        }
        self.bump_revision()
        self.positionChanged.emit()

    @Slot(float)
    def setScale(self, meters_per_pixel: float):
        """Map zoom settled: lines with a minimum pixel width rebuilt"""
        meters_per_pixel = max(meters_per_pixel, 1e-3)
        if abs(meters_per_pixel - self._meters_per_pixel) > 1e-6:
            self._meters_per_pixel = meters_per_pixel
            self.build_scaled()
            self.update_position()

    # Config
    @Slot(str, bool)
    def setOverlay(self, key: str, shown: bool):
        if key in dict(OVERLAYS):
            self.ecfg[key] = shown
            cfg.save(config_type=ConfigType.CONFIG)
            self.configChanged.emit()

    @Slot()
    def openConfig(self):
        from ..config import UserConfig

        UserConfig(
            parent=self._window,
            key_name="track_map_viewer",
            preset_name=cfg.filename.config,
            config_type=ConfigType.CONFIG,
            user_setting=cfg.user.config,
            default_setting=cfg.default.config,
            reload_func=self.reload_config,
        ).open()

    def reload_config(self):
        """Config edited: grades, widths & colors"""
        self.ecfg = cfg.user.config["track_map_viewer"]
        self.grades = config_grades(self.ecfg)
        if self.raw_coords:
            self.build_scaled()
            self.update_position()
        self.configChanged.emit()
