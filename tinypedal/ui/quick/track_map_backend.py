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
from bisect import bisect_right
from dataclasses import dataclass

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
from .background import BackgroundJobs
from .game_pictures import notifier, track_logo_url
from .lines import (
    VertexStore,
    Vertices,
    area,
    band,
    circle,
    colored_band,
    line_strip,
    merge_strips,
    normals,
    segments,
)

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
SCALED_WIDTHS = (
    "map_width", "map_outline_width", "start_line_length", "start_line_width", "sector_line_length",
    "sector_line_width",
)


@dataclass(frozen=True)
class MapGeometry:
    """Track map file read & everything not depending on zoom, computed once per map (off the UI thread)"""

    name: str
    coords: list[tuple[float, float]]
    dists: list[tuple[float, float]]
    sectors: tuple[int, int]
    length: float
    corners: list[TrackCorner]
    numbered: bool
    closed: bool
    starts: list[int]  # node index of sector 2 & 3 start
    bounds: list[float]  # track distance of sector 2 & 3 start
    loop_xs: list[float]  # line drawn: first node again at end of closed track
    loop_ys: list[float]
    loop_normals: list[tuple[float, float]]
    loop_sectors: list[int]  # sector (0-2) of each node of line drawn
    elevation: Vertices
    elevation_line: Vertices


def half_width(meters: float, min_pixels: float, meters_per_pixel: float) -> float:
    """Half line width: config width in meters, at least some pixels when zoomed out"""
    return max(meters, min_pixels * meters_per_pixel) / 2


def cross_line(coords: list[tuple[float, float]], index: int, length: float) -> list[float]:
    """Line across track at node: x0, y0, x1, y1"""
    nodes = len(coords)
    point_a = coords[index % nodes]
    point_b = coords[(index + 1) % nodes]
    return list(calc.line_intersect_coords(point_a, point_b, math.pi / 2, length))


def read_geometry(filepath: str, filename: str) -> MapGeometry | None:
    """Track map file read with its corners, normals, sectors & elevation profile, None if invalid"""
    coords, dists, sectors = load_track_map_file(filepath=filepath, filename=filename)
    if not coords or len(coords) <= 9 or not dists:
        return None
    raw_coords = [(float(x), float(y)) for x, y in coords]
    raw_dists = [(float(distance), float(height)) for distance, height in dists]
    sector_nodes = (int(sectors[0]), int(sectors[1])) if sectors else (0, 0)
    nodes = sorted(zip(raw_dists, raw_coords))  # first node can be lap end
    corners, numbered = track_corners(
        filename, [node[0][0] for node in nodes], [node[1][0] for node in nodes], [node[1][1] for node in nodes])
    count = len(raw_coords)
    starts = [index for index in sector_nodes if 0 < index < count]
    sorted_starts = sorted(starts)
    node_sectors = [min(bisect_right(sorted_starts, index), 2) for index in range(count)]
    xs = [x for x, _ in raw_coords]
    ys = [y for _, y in raw_coords]
    closed = calc.distance(raw_coords[0], raw_coords[-1]) < 500
    if closed:
        xs, ys, node_sectors = [*xs, xs[0]], [*ys, ys[0]], [*node_sectors, node_sectors[-1]]
    profile = sorted(raw_dists)  # elevation profile by increasing distance
    distances = [distance for distance, _ in profile]
    heights = [height for _, height in profile]
    return MapGeometry(
        name=filename, coords=raw_coords, dists=raw_dists, sectors=sector_nodes, length=raw_dists[-1][0],
        corners=corners, numbered=numbered, closed=closed, starts=starts,
        bounds=[raw_dists[min(index, len(raw_dists) - 1)][0] for index in sector_nodes if 0 < index < len(raw_dists)],
        loop_xs=xs, loop_ys=ys, loop_normals=normals(xs, ys), loop_sectors=node_sectors,
        elevation=area(distances, heights, min(heights)), elevation_line=line_strip(distances, heights),
    )


def scaled_lines(geometry: MapGeometry, widths: dict[str, float], meters_per_pixel: float) -> dict[str, Vertices]:
    """Lines depending on map scale: road, outline, sectors, start & sector lines (by key name)"""
    xs, ys, line_normals = geometry.loop_xs, geometry.loop_ys, geometry.loop_normals
    road = half_width(widths["map_width"], 5.0, meters_per_pixel)
    outline = road + half_width(widths["map_outline_width"], 2.0, meters_per_pixel)
    start = cross_line(geometry.coords, 0, widths["start_line_length"])
    sector_lines = [cross_line(geometry.coords, index, widths["sector_line_length"]) for index in geometry.starts]
    half = half_width(widths["sector_line_width"] / 2, 3.0, meters_per_pixel)
    return {
        "road": band(xs, ys, road, line_normals=line_normals),
        "edge": band(xs, ys, outline, line_normals=line_normals),
        "sectors": colored_band(xs, ys, [SECTOR_COLORS[sector] for sector in geometry.loop_sectors],
                                half_width(0.0, 2.0, meters_per_pixel)),
        "start": band(start[0::2], start[1::2], half_width(widths["start_line_width"] / 2, 3.0, meters_per_pixel)),
        "sector_lines": merge_strips([band(line[0::2], line[1::2], half) for line in sector_lines]),
    }


class TrackMapBackend(QObject):
    """Track Map Viewer page state (QML context property "backend")

    Shapes are drawn again when their vertices change (VertexStore tells them): no global revision.
    """

    mapChanged = Signal()
    logoChanged = Signal()  # map loaded, or circuit logo fetched from game
    positionChanged = Signal()
    currentChanged = Signal()  # node at position (curve, slope & info) or curve nodes changed
    configChanged = Signal()
    loadingChanged = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        notifier().changed.connect(self.logoChanged)
        self.mapChanged.connect(self.logoChanged)
        self._window = parent
        self.jobs = BackgroundJobs(self, "Track map viewer")
        self.prefix = f"track_map_{id(self)}|"
        self.geometry: MapGeometry | None = None
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
        self._shown: tuple | None = None  # (node, curve nodes, scale) of curve shown
        self._meters_per_pixel = 1.0
        self._loading = False
        self._released = False
        self.ecfg = cfg.user.config["track_map_viewer"]
        self.grades = config_grades(self.ecfg)

    def release(self):
        self._released = True  # jobs still running: their result dropped
        self.geometry = None
        VertexStore.remove_prefix(self.prefix)

    def key(self, name: str) -> str:
        return self.prefix + name

    # Properties
    @Property(bool, notify=mapChanged)
    def loaded(self) -> bool:
        return bool(self.raw_coords)

    @Property(bool, notify=loadingChanged)
    def loading(self) -> bool:
        """Map file read in background"""
        return self._loading

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

    @Property(dict, notify=currentChanged)
    def current(self) -> dict:
        """Position, curve & slope at position"""
        return self._current

    @Property(int, notify=currentChanged)
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
        """Load track map file made by Mapping module (read in background), warning if missing or invalid

        Returns:
            False if file missing, else True (map shown once read, or warned if invalid).
        """
        from PySide6.QtWidgets import QMessageBox

        if not os.path.exists(f"{filepath}{filename}{FileExt.SVG}"):
            QMessageBox.warning(self._window, tr("Error"), trm(f"Cannot find track map for<br><b>{filename}</b><br>"))
            return False
        widths, scale = self.scaled_widths(), self._meters_per_pixel

        def work() -> tuple:
            geometry = read_geometry(filepath, filename)
            return filepath, filename, geometry, scaled_lines(geometry, widths, scale) if geometry else {}

        self.set_loading(True)
        self.jobs.run("read map", work, self.map_read, self.map_failed, key="map")
        return True

    def set_loading(self, loading: bool):
        if loading != self._loading:
            self._loading = loading
            self.loadingChanged.emit()

    def map_failed(self, error: BaseException):
        logger.error("Track map viewer: unable to read map", exc_info=(type(error), error, error.__traceback__))
        self.map_read(("", self.map_name, None, {}))

    def map_read(self, result: tuple):
        """Map read in background: shown (or warned if invalid)"""
        from PySide6.QtWidgets import QMessageBox

        if self._released:
            return
        self.set_loading(False)
        filepath, filename, geometry, lines = result
        if geometry is None:
            self.geometry = None
            self.raw_coords, self.raw_dists, self.map_name, self.map_length = [], [], "", 0.0
            self._shown = None
            VertexStore.remove_prefix(self.prefix)
            self.mapChanged.emit()
            QMessageBox.warning(self._window, tr("Error"), trm(
                "Unable to load track map file from<br>"
                f"<b>{filepath}{filename}{FileExt.SVG}</b><br><br>"
                "Only support SVG file that generated with NeoPedal or TinyPedal."))
            return
        self.geometry = geometry
        self.raw_coords, self.raw_dists, self.sectors = geometry.coords, geometry.dists, geometry.sectors
        self.map_name, self.map_length = geometry.name, geometry.length
        self.corners, self.corners_numbered = geometry.corners, geometry.numbered
        VertexStore.set(self.key("elevation"), geometry.elevation)
        VertexStore.set(self.key("elevation_line"), geometry.elevation_line)
        self.store_lines(lines)
        self._position = 0.0
        self._shown = None
        self.update_position()
        self.mapChanged.emit()

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
        return list(self.geometry.bounds) if self.geometry is not None else []

    def width(self, meters: float, min_pixels: float = 2.0) -> float:
        """Half line width: config width in meters, at least some pixels when zoomed out"""
        return half_width(meters, min_pixels, self._meters_per_pixel)

    def scaled_widths(self) -> dict[str, float]:
        """Config widths & lengths of lines depending on scale (read on UI thread, used by background job)"""
        return {key: float(self.ecfg[key]) for key in SCALED_WIDTHS}

    def build_scaled(self):
        """Lines depending on map scale (road, outline, sectors, start & sector lines) built in background"""
        geometry = self.geometry
        if geometry is None:
            return
        widths, scale = self.scaled_widths(), self._meters_per_pixel
        self.jobs.run("scale lines", lambda: (geometry, scaled_lines(geometry, widths, scale)), self.scaled_built,
                      key="scaled")

    def scaled_built(self, result: tuple):
        geometry, lines = result
        if geometry is self.geometry and not self._released:  # else other map loaded meanwhile
            self.store_lines(lines)

    def store_lines(self, lines: dict[str, Vertices]):
        for name, vertices in lines.items():
            VertexStore.set(self.key(name), vertices)

    # Position along track
    @Slot(float)
    def setPosition(self, distance: float):
        self._position = max(0.0, min(float(distance), self.map_length))
        self.update_position()

    @Slot(int)
    def setCurveNodes(self, nodes: int):
        self.curve_nodes = max(3, min(int(nodes), 9999))
        self.update_position(force=True)

    @Slot(float, float, float, result=float)
    def pick(self, x: float, y: float, radius: float) -> float:
        """Track distance of node nearest to map point, -1 if farther than radius"""
        best, nearest = radius * radius, -1
        for index, (node_x, node_y) in enumerate(self.raw_coords):
            gap = (node_x - x) ** 2 + (node_y - y) ** 2
            if gap < best:
                best, nearest = gap, index
        return self.raw_dists[nearest][0] if nearest >= 0 else -1.0

    def update_position(self, force: bool = False):
        """Curve section, osculating circle & info at position, built again only when node, curve nodes or
        scale changed (playback moves position every frame, nodes are meters apart)"""
        if not self.raw_coords:
            self._current = {}
            self._shown = None
            self.positionChanged.emit()
            self.currentChanged.emit()
            return
        index = node_at(self.raw_dists, self._position)
        shown = (index, self.curve_nodes, self._meters_per_pixel)
        if shown == self._shown and not force:
            self.positionChanged.emit()
            return
        self._shown = shown
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
        bounds = self.geometry.bounds if self.geometry is not None else []
        self._current = {
            "node": index + 1, "distance": distance, "x": x, "y": y, "z": height,
            "yaw": math.degrees(info.yaw), "curveLength": info.length, "lengthDesc": tr(length_desc),
            "radius": info.radius, "radiusDesc": " ".join(tr(word) for word in curve_desc.split(" ")),
            "angle": info.angle, "direction": info.direction,
            "slope": info.slope_percent * 100, "slopeAngle": info.slope_angle, "slopeDelta": info.height_delta,
            "slopeDesc": tr(slope_desc), "centerX": info.center[0], "centerY": info.center[1],
            "sector": 1 + sum(1 for start in bounds if distance >= start),
            "corner": self.corner_at(distance),
        }
        self.positionChanged.emit()
        self.currentChanged.emit()

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
            self.update_position(force=True)
        self.configChanged.emit()
