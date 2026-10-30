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
Lap viewer track map (mixin of LapViewerBackend): circuit, driving lines & markers, colored line, zoom steps built
in background, placement across track. Corner labels & points (lap_map_marks), mouse over map & lap positions at
cursor (lap_map_pointer) and consistency mode (lap_consistency) are page parts reading the map kept here.
"""

from __future__ import annotations

import bisect
import math
import os
import threading
from array import array
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from PySide6.QtCore import Slot
from PySide6.QtGui import QColor

from ...i18n import tr
from ...setting import cfg
from ...userfile.lap_geometry import Yielder
from ...userfile.telemetry_lap import interpolate
from ...userfile.track_map import load_track_map_file
from ..lap_viewer import (
    TRACK_WIDTH,
    PlotLap,
    distance_text,
    distance_unit,
    localized,
    save_viewer_setting,
)
from . import lap_map
from .lap_base import BackendBase, keys_match
from .lines import (
    VertexStore,
    Vertices,
    band,
    band_part,
    markers,
    merge_strips,
    normals,
    range_indexes,
    segments,
)

LINE_WIDTH = 1.2  # half width of driving lines on map, pixels
ZOOMED_WIDTH = 2.2  # half width of zoomed part & colored line, pixels
MAP_OPTIONS = {  # track map display options & default
    "apex": True,  # minimum speed point of each lap in each corner
    "exit": True,  # full throttle point of each lap after each apex
    "arrows": True,  # driving direction arrows
    "sectors": True,  # sector times & gap of compared lap
    "values": False,  # speed next to driving points
    "track": True,  # view follows vehicles while playing lap or moving cursor with keys
    "trackout": True,  # point where each lap comes closest to corner outside edge (track limits needed)
    "zones": False,  # braking & throttle application zones of reference (or highlighted) lap
    "trail": True,  # last seconds of each lap behind cursor
    "limits": True,  # track edges guessed from every recorded lap of the circuit
    "colorblind": False,  # gain / loss in blue & orange instead of green & red
    "distances": True,  # distance marks along circuit
    "offtrack": True,  # where 2 wheels or more go on grass, dirt or gravel (recorded wheel surface)
    "limit": True,  # where car goes beyond track edge (four wheels out)
    "spread": False,  # braking points range of shown laps in each corner
    "pit": True,  # pit lane (official circuit map)
    "minimap": True,  # whole circuit in a corner when zoomed in
}
MARKER_PIXELS = {  # driving point marker size across (pixels) & shape
    "brake": (11, "diamond"), "apex": (11, "dot"), "exit": (15, "triangle"), "trackout": (10, "square"),
    "lock": (13, "ring"), "spin": (14, "hollow_triangle"), "offtrack": (13, "hollow_diamond"), "limit": (12, "cross"),
    "bottom": (13, "hollow_square"),
}
OUTLINE_PIXELS = 3  # marker outline (map background color) around each marker
ARROW_PIXELS = 11  # driving direction arrows
TRAIL_SECONDS = 3.0  # cursor trail length (lap time)
ZOOM_BUCKETS = 2  # map scale steps per doubling: thick lines & markers built once per step (cached)
BAND_CACHE_STEPS = 10  # map scale steps kept (least recently used dropped)
CIRCUIT_LOCK = threading.Lock()  # circuit shapes cache filled & trimmed by several map jobs at once
MINIMAP_PIXELS = 150  # minimap size across (thin lines sized for it)
PREFETCH_DELAY = 400  # ms map view stays still before neighbor scales are built
MILE = 1609.344  # meters
PIT_PART_GAP = 20.0  # meters between pit lane points: separate parts (not joined by a line)
ROAD_GRID = "|road"  # mouse picking grid of official circuit when it stands for reference lap line (not a lap key)
TRAIL_GAP = 1.5  # pixels between cursor trail points kept (built on every cursor move: fewer points zoomed out)


def scale_step(meters_per_pixel: float) -> float:
    """Map scale rounded to steps (ZOOM_BUCKETS per doubling): thick lines built once per step"""
    return round(math.log2(max(meters_per_pixel, 1e-3)) * ZOOM_BUCKETS) / ZOOM_BUCKETS


def pit_parts(points: list[tuple[float, float, float]]) -> list[list[tuple[float, float, float]]]:
    """Pit lane points split where consecutive points are far apart, parts of 2 points or more"""
    parts: list[list[tuple[float, float, float]]] = []
    for point in points:
        if not parts or math.hypot(point[0] - parts[-1][-1][0], point[1] - parts[-1][-1][1]) > PIT_PART_GAP:
            parts.append([])
        parts[-1].append(point)
    return [part for part in parts if len(part) > 1]


def frame_normals(frame: dict[str, Any], lap: PlotLap, line: lap_map.MapLine) -> lap_map.PackedNormals:
    """Normals of lap line turned like map from map frame (see MapView.map_frame), computed ones left in frame"""
    cached = frame["normals"].get(lap.key)
    if cached is None or cached[0] is not lap.data or cached[1] != frame["angle"] or cached[2] != len(line.xs):
        cached = (lap.data, frame["angle"], len(line.xs), lap_map.PackedNormals(line.xs, line.ys))
        frame["normals"][lap.key] = frame["new"]["normals"][lap.key] = cached
    return cached[3]


def track_length_of(lap: PlotLap | None) -> float:
    """Track length of lap info, else lap distance at lap end, 0 if no lap"""
    if lap is None or not len(lap.data):
        return 0.0
    length = lap.data.meta.get("track_length")
    return float(length) if isinstance(length, (int, float)) and length > 0 else lap.data.distance[-1]


def prepare_placements(laps: Sequence[PlotLap], reference: PlotLap | None, limits: lap_map.TrackLimits | None,
                       geometry: Any, official_line: tuple, line_cache: Mapping[str, tuple]) -> dict:
    """Driving lines of laps about to be shown, base line, track edges along it & placement of each lap measured in
    background (loading thread, same as MapView.update_base): kept by MapView.keep_placements, page state never
    touched (state it needs given: track limits, official circuit, official line & driving lines known)"""
    lines: dict[str, tuple] = {}
    for lap in laps:
        cached = line_cache.get(lap.key)
        if cached is None or cached[0] is not lap.data:
            cached = (lap.data, lap_map.map_line(lap.data))
        lines[lap.key] = cached
    official = None
    if geometry is not None:  # see official_base
        length = track_length_of(reference)
        key = (geometry, length or geometry.length)
        if not official_line or not keys_match(official_line[0], key):
            official_line = (key, lap_map.geometry_line(geometry.center, geometry.start, length or geometry.length))
        official = official_line[1]
    line = lines[reference.key][1] if reference is not None else None
    base = official if official is not None else line
    prepared: dict = {"lines": lines, "official": official_line, "edges": (), "offsets": {}, "placements": {},
                      "limits": limits, "geometry": geometry}
    if limits is None or base is None or len(base.xs) <= 2:
        return prepared
    pause = Yielder() if threading.current_thread() is not threading.main_thread() else None
    edges = lap_map.edge_offsets(base, limits, pause)
    prepared["edges"] = ((base, limits), edges)
    for lap in laps if edges[0] else ():
        line = lines[lap.key][1]
        if line is None or any(lap.data.columns.get("track_edge") or ()):  # game values recorded
            continue
        sides, indexes = lap_map.lateral_offsets(base, line, pause)
        prepared["offsets"][lap.key] = (
            (lap.data, len(base.xs), base.xs[0], base.ys[0], base.distances[-1]), line, sides, indexes)
        if sides:
            prepared["placements"][lap.key] = ((sides, edges), MapView.lap_placements((line, sides, indexes), *edges))
    return prepared


class MapView(BackendBase):
    """Track map of lap viewer page"""

    def keep_placements(self, prepared: dict):
        """Driving lines & lap placements measured in background (see prepare_placements) kept where they match shown
        laps, official circuit & track limits (cache keys), so update_base finds them, else measured again"""
        shown = {lap.key: lap.data for lap in self.data.laps}
        for key, value in prepared["lines"].items():
            cached = self._line_cache.get(key)
            if shown.get(key) is value[0] and (cached is None or cached[0] is not value[0]):
                self._line_cache[key] = value
        official, geometry = prepared["official"], self._geometry
        if official and geometry is not None:
            length = self.reference_length()
            key = (geometry, length or geometry.length)
            if keys_match(official[0], key) and not (self._official_line and keys_match(self._official_line[0], key)):
                self._official_line = official
        reference = self.data.reference
        line = self.lap_line(reference) if reference is not None else None  # cached: no line computed
        base = self.official_base(self.reference_length())
        base = base if base is not None else line
        if base is None or len(base.xs) < 3:
            return
        edges = prepared["edges"]
        if edges and edges[0][0] is base and edges[0][1] is self._limits:
            self._edges_cache = edges
        for key, value in prepared["offsets"].items():
            if key in shown and keys_match(value[0], (shown[key], len(base.xs), base.xs[0], base.ys[0],
                                                      base.distances[-1])):
                self._lap_offsets[key] = value
        self._prepared_placements = prepared["placements"]  # used once by update_placements (cache keys checked)

    def placements_current(self, prepared: dict) -> bool:
        """Whether lap placements measured in background used current track limits & official circuit"""
        return prepared["limits"] is self._limits and prepared["geometry"] is self._geometry

    def place_laps(self):
        """Lap placement on map measured in background (track limits or official circuit changed), then charts & map
        built again: page stays responsive"""
        if not self.data.laps:
            return
        reference = self.data.reference
        args = (list(self.data.laps), reference, self._limits, self._geometry, self._official_line,
                dict(self._line_cache))

        def placed(prepared):
            self._placing -= 1
            if prepared is not None:
                self.keep_placements(prepared)
            self.rebuild_chart()

        self._placing += 1
        self.run_job("lap placement", lambda: prepare_placements(*args), placed)

    @Slot(bool)
    def setMapShown(self, shown: bool):
        """Track map shown or hidden (side panel tab, focus mode): cursor trails built only when shown"""
        self._map_shown = max(self._map_shown + (1 if shown else -1), 0)

    @Slot(float, float)
    def setMapRange(self, start_x: float, end_x: float):
        """Chart markers A & B shown on map (negative: none)"""
        if start_x < 0 or end_x < 0:
            view = (-1.0, -1.0)
        else:
            low, high = sorted((start_x, end_x))
            view = (self.data.distance_at_x(low), self.data.distance_at_x(high))
        if view != self._map_range:
            self._map_range = view
            if self._map:
                self.build_map_overlays(self._map_view[2])
                self.bump_revision()

    @Slot(float, float, float, float, float, float, result=list)
    def mapVisibleRange(self, x0: float, y0: float, x1: float, y1: float, center_x: float, center_y: float) -> list:
        """Axis range of reference line part shown in map view around view center (charts follow map), empty if none"""
        line, grid = self.reference_map_line(), self.reference_grid()
        found = lap_map.visible_range(line, (x0, y0, x1, y1), (center_x, center_y), grid) \
            if line is not None and grid is not None else None
        if found is None or found[1] - found[0] < 20:
            return []
        return [self.data.x_at_distance(found[0]), self.data.x_at_distance(found[1])]

    def build_trails(self, x: float):
        """Last seconds of each lap behind cursor, fading in (trail option)

        Trail of a lap built again only once that lap moved about a pixel on map (cursor moves of a few meters, laps
        stopped past their end: same trails; playback: only laps that moved, not every lap each frame).
        """
        if not self._map or not self._map_options.get("trail") or not self._map_shown:
            self._trail_state = None
            return
        meters_per_pixel = self._map_view[2]
        ends = [self.data.lap_distance_at_x(lap, x) for _, lap in self._map_lines]
        state = self._trail_state
        if state is None or state[0] is not self._map or state[1] != meters_per_pixel or len(state[2]) != len(ends):
            built = [math.nan] * len(ends)  # other map or scale: every trail built
        else:
            built = list(state[2])
        changed = False
        for index, ((line, lap), keys, end) in enumerate(zip(self._map_lines, self._map["lines"], ends)):
            if abs(end - built[index]) < meters_per_pixel:  # nan (not built): False
                continue
            built[index] = end
            distances, times = self.data.lap_times(lap)
            if not distances:
                continue
            changed = True
            start = interpolate(times, distances, interpolate(distances, times, end) - TRAIL_SECONDS)
            bright = lap.color.lighter(165)  # stands out over its own driving line
            VertexStore.set(keys["trail"], lap_map.trail_band(
                line, self.line_normals(lap, line), start, end, (bright.red(), bright.green(), bright.blue()),
                meters_per_pixel * 3.2, meters_per_pixel * TRAIL_GAP))
        self._trail_state = (self._map, meters_per_pixel, built)
        if changed:
            self._trail_revision += 1
            self.trailChanged.emit()

    @Slot(float, str, result=dict)
    def placementAt(self, x: float, lap_key: str = "") -> dict:
        """Lap (highlighted, else reference) across track at axis position: room to each edge & track position"""
        lap = next((lap for lap in self.data.laps if lap.key == lap_key), self.data.reference)
        if lap is None:
            return {}
        distance = self.data.lap_distance_at_x(lap, x)
        found = self.lap_placement(lap, distance)
        if found is None:
            return {}
        left, right, percent = found
        side = tr("left") if percent > 0 else tr("right")
        texts = [distance_text(distance), f"{abs(percent):.0f}% {side}" if abs(percent) >= 5 else tr("track middle")]
        for room, label in ((left, tr("Left edge")), (right, tr("Right edge"))):
            texts.append(f"{label} {distance_text(room, 1)}" if room >= 0
                         else f"{label} {tr('beyond')} {distance_text(-room, 1)}")
        return {"text": " · ".join(texts), "color": lap.color.name(), "out": left < 0 or right < 0}

    # Track map
    def track_outline(self) -> list[tuple[float, float]]:
        """Circuit coordinates from track map file (recorded by Mapping module), empty if none"""
        laps = self.data.laps
        if not laps:
            return []
        track = str(laps[0].data.meta.get("track", ""))
        if not track:  # older lap files: "<track> - <class>" folder
            track = os.path.basename(os.path.dirname(laps[0].key)).rsplit(" - ", 1)[0]
        if track not in self._outline_cache:
            coords, _, _ = load_track_map_file(cfg.path.track_map, track)
            self._outline_cache[track] = [(float(x), float(y)) for x, y in coords] if coords else []
        return self._outline_cache[track]

    def lap_line(self, lap: PlotLap) -> lap_map.MapLine | None:
        """Driving line of lap (not turned), computed once per loaded lap (official corners & map)"""
        cached = self._line_cache.get(lap.key)
        if cached is None or cached[0] is not lap.data:
            cached = (lap.data, lap_map.map_line(lap.data))
            self._line_cache = {key: value for key, value in self._line_cache.items()
                                if key in {shown.key for shown in self.data.laps}}
            self._line_cache[lap.key] = cached
        return cached[1]

    def map_angle(self, road: lap_map.MapLine) -> float:
        """Map rotation: auto orientation (longest extent along longest view side) & quarter turns

        Map drawn y down: positive angle turns clockwise on screen.
        Auto orientation turns the least possible from game orientation.
        """
        angle = self._map_quarters * math.pi / 2
        if self._map_auto_orient and len(road.xs) > 2:
            turn = -lap_map.principal_angle(road.xs, road.ys)  # -90 to 90 degrees
            if self._map_aspect < 1:  # tall view: longest extent vertical
                turn += math.pi / 2 if turn < 0 else -math.pi / 2
            angle += turn
        return angle

    def rotate_point(self, x: float, y: float) -> tuple[float, float]:
        if not self._map_angle:
            return x, y
        cos, sin = math.cos(self._map_angle), math.sin(self._map_angle)
        return x * cos - y * sin, x * sin + y * cos

    def reference_map_line(self) -> lap_map.MapLine | None:
        """Line along reference lap distances on map (turned like map): reference lap line, else official circuit
        (distances scaled to reference lap) when reference lap has no positions (imported log), None if neither:
        what is placed at reference distances (corner labels, sectors, chart range, pin, picking) left out"""
        reference = self.data.reference
        if reference is None:
            return None
        for line, lap in self._map_lines:
            if lap is reference:
                return line
        official = self.official_base(self.reference_length())
        if official is not None and self._road.distances is official.distances:  # map circuit: official one turned
            return self._road
        return None

    def reference_grid(self) -> lap_map.LineGrid | None:
        """Mouse picking grid of reference map line, None if none"""
        reference = self.data.reference
        if reference is not None and any(lap is reference for _, lap in self._map_lines):
            return self._grids.get(reference.key)
        return self._grids.get(ROAD_GRID)

    def guide_line(self) -> lap_map.MapLine:
        """Line distance marks, start line & direction arrows follow: reference map line, else first lap line, else
        circuit"""
        line = self.reference_map_line()
        if line is not None:
            return line
        return self._map_lines[0][0] if self._map_lines else self._road

    def build_map(self):
        """Circuit, driving lines, start & sector marks, corners, braking points of displayed laps

        Shapes sized for map scale are built in background (see build_map_bands): shapes of former map stay shown
        until then if circuit & map rotation are the same, else none.
        """
        shown_before = self._band_cache.get(self._preview_step) if self._band_cache_applied else None
        placed_before = (self._map_angle, self.road_key(self._road))
        lines = []
        for lap in self.data.laps:
            line = self.lap_line(lap)
            if line is not None:
                lines.append((line, lap))
        official = self.official_base(self.reference_length())
        outline = self.track_outline() if official is None else []
        if official is not None:  # official circuit from game
            road = official
        elif outline:
            road = lap_map.MapLine(list(range(len(outline))), [x for x, _ in outline], [y for _, y in outline])
        elif lines:
            road = lines[0][0]
        else:
            self._map_lines = []
            self._map = {}
            self.map_lap_model.sync([], "lap")
            return
        self._map_angle = self.map_angle(road)
        self._road = lap_map.rotate_line(road, self._map_angle)
        self._road_numbered = official is None and bool(outline)
        self._map_lines = [(self.turned_line(lap, line), lap) for line, lap in lines]
        geometry = self._geometry
        self._pit = [  # pit lane parts (game gives pit entry & exit roads apart)
            lap_map.rotate_line(lap_map.MapLine(list(range(len(part))), [p[0] for p in part], [p[1] for p in part]),
                                self._map_angle)
            for part in pit_parts(geometry.pit if geometry is not None else [])
        ]
        self._band_cache = OrderedDict()
        self._band_generation += 1
        self._preview_step = math.nan
        self._band_cache_applied = False
        if shown_before and placed_before != (self._map_angle, self.road_key(self._road)):  # never at a wrong place
            for key, vertices in shown_before.items():
                if isinstance(vertices, Vertices):
                    VertexStore.set(key, vertices._replace(data=array("f"), vertex_count=0))
        shown = {lap.key for _, lap in self._map_lines}
        self._normals = {name: value for name, value in self._normals.items() if name in shown}
        self._turned = {name: value for name, value in self._turned.items() if name in shown}
        self._lap_shapes = {key: value for key, value in list(self._lap_shapes.items()) if key[0] in shown}
        grids = self._grids  # mouse picking grid of each lap line, kept while lap & rotation stay the same
        self._grids = {lap.key: grids[lap.key] if lap.key in grids and grids[lap.key].line is line
                       else lap_map.LineGrid(line) for line, lap in self._map_lines}
        reference_line = self.reference_map_line()
        if reference_line is not None and reference_line is self._road:  # official circuit stands for reference line
            kept = grids.get(ROAD_GRID)
            self._grids[ROAD_GRID] = kept if kept is not None and kept.line is self._road else lap_map.LineGrid(self._road)
        drawn = [self._road, *(line for line, _ in self._map_lines)]  # map bounds: of every line drawn
        limits = self.shown_limits()
        if limits is not None:
            drawn += [limits.left, limits.right]
        drawn += self._pit
        xs = [bound for line in drawn if line.xs for bound in (min(line.xs), max(line.xs))]  # lines packed: never joined
        ys = [bound for line in drawn if line.ys for bound in (min(line.ys), max(line.ys))]
        events = self._map_marks.event_points()
        self._map = {
            "road": self.prefix + "map|road", "edge": self.prefix + "map|edge", "colored": self.prefix + "map|colored",
            "marks": self.prefix + "map|marks", "pit": self.prefix + "map|pit", "mini": self.prefix + "map|mini",
            "spread": self.prefix + "map|spread", "official": official is not None,
            "layout": geometry.layout if geometry is not None and official is not None else "",
            "events": events, "violations": self._map_marks.violation_counts(events),
            "lines": [
                {"key": f"{self.prefix}map|{lap.key}", "highlight": f"{self.prefix}map|{lap.key}|zoom",
                 "trail": f"{self.prefix}map|{lap.key}|trail",
                 "color": lap.color.name(), "reference": lap is self.data.reference, "lap": lap.key}
                for _, lap in self._map_lines
            ],
            "markers": [
                {"lap": lap.key, "color": lap.color.name(), "reference": lap is self.data.reference,
                 "shapes": [{"kind": kind, "fill": f"{self.prefix}mk|{lap.key}|{kind}",
                             "outline": f"{self.prefix}mk|{lap.key}|{kind}|o"} for kind in MARKER_PIXELS],
                 "brakeZones": f"{self.prefix}zone|{lap.key}|brake",
                 "throttleZones": f"{self.prefix}zone|{lap.key}|throttle"}
                for _, lap in self._map_lines
            ],
            "arrowsKey": self.prefix + "map|arrows",
            "rangeKey": self.prefix + "map|range", "selectedKey": self.prefix + "map|selected",
            "ticks": self.distance_marks(),
            "limits": limits is not None,
            "minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys),
            "corners": self._map_marks.corner_points(),
            "points": self._map_marks.driving_points(),
            "slips": self._map_marks.slip_points(),
            "sectors": self._map_marks.sector_labels(),
            "arrows": [{"x": x, "y": y, "angle": angle} for x, y, angle in self.direction_marks()],
            "start": self.start_mark(),
        }
        self.map_lap_model.sync([{**line, **marker} for line, marker in zip(self._map["lines"], self._map["markers"])],
                                "lap")
        self.build_minimap()
        self.build_map_bands()
        self.pinChanged.emit()  # kept position on map turned with it

    @staticmethod
    def road_key(road: lap_map.MapLine) -> tuple:
        """Circuit line told apart from another (turned like map)"""
        return (len(road.xs), road.xs[0], road.ys[0], road.xs[-1], road.ys[-1]) if road.xs else ()

    def distance_marks(self) -> list[dict]:
        """Distance marks along guide line, none along circuit of track map file (no meters)"""
        line = self.guide_line()
        return [] if line is self._road and self._road_numbered else self.map_ticks(line)

    @staticmethod
    def map_ticks(line: lap_map.MapLine) -> list[dict]:
        """Distance marks along map line in user unit: every 500 m (km on long laps), or every quarter mile (half)"""
        long_lap = len(line.distances) > 1 and line.distances[-1] > 8000
        if distance_unit()[1] == "ft":
            step, divider, symbol = MILE * (0.5 if long_lap else 0.25), MILE, "mi"
        else:
            step, divider, symbol = 1000.0 if long_lap else 500.0, 1000.0, "km"
        return [{"x": x, "y": y, "label": f"{localized(f'{distance / divider:g}')} {symbol}"}
                for x, y, distance in lap_map.distance_ticks(line, step)]

    def shown_limits(self) -> lap_map.TrackLimits | None:
        """Track edges turned like map, None if not guessed or option off"""
        if self._limits is None or not self._map_options.get("limits"):
            return None
        return lap_map.TrackLimits(lap_map.rotate_line(self._limits.left, self._map_angle),
                                   lap_map.rotate_line(self._limits.right, self._map_angle))

    def start_mark(self) -> list[float]:
        """Start line across circuit (reference line start), x0 y0 x1 y1"""
        line = self.guide_line()
        if line is self._road and self.reference_map_line() is None:  # track map file (distances: point numbers)
            road = self._road
            if len(road.xs) < 2:
                return []
            dx, dy = road.xs[1] - road.xs[0], road.ys[1] - road.ys[0]
            length = max((dx * dx + dy * dy) ** 0.5, 1e-6)
            nx, ny = -dy / length * TRACK_WIDTH, dx / length * TRACK_WIDTH
            return [road.xs[0] - nx, road.ys[0] - ny, road.xs[0] + nx, road.ys[0] + ny]
        return list(lap_map.cross_mark(line, line.distances[0] + 1, TRACK_WIDTH))

    # Lap placement across track: offset from base line (official circuit path, else reference lap) & track edges
    def reference_length(self) -> float:
        return track_length_of(self.data.reference)

    def lap_offsets(self, lap: PlotLap) -> tuple[lap_map.MapLine, list[float], list[int]] | None:
        """Offset of each lap line point from base line (left positive) & nearest base point, cached"""
        line = self.lap_line(lap)
        base = self._base
        if line is None or len(base.xs) < 3:
            return None
        key = (lap.data, len(base.xs), base.xs[0], base.ys[0], base.distances[-1])
        cached = self._lap_offsets.get(lap.key)
        if cached is None or not keys_match(cached[0], key):
            sides, indexes = lap_map.lateral_offsets(base, line)
            cached = (key, line, sides, indexes)
            shown = {shown_lap.key for shown_lap in self.data.laps}
            self._lap_offsets = {name: value for name, value in self._lap_offsets.items() if name in shown}
            self._lap_offsets[lap.key] = cached
        return cached[1], cached[2], cached[3]

    def update_base(self):
        """Line lap placement is measured from: official circuit path (game driving line), else reference lap line"""
        reference = self.data.reference
        official = self.official_base(self.reference_length())
        line = self.lap_line(reference) if reference is not None else None
        self._base_official = official is not None
        self._base = official if official is not None else (line if line is not None else lap_map.MapLine([], [], []))
        self.update_placements()

    def update_placements(self):
        """Track edges along base line & placement of each shown lap (track position & distance to center charts)

        Measured between track edges for laps without game values only (game lateral position & track edge recorded
        are exact). Never without track edges: base line is a driving line, not the track center.
        """
        base = self._base
        if self._limits is not None and len(base.xs) > 2:
            key = (base, self._limits)
            if not self._edges_cache or not keys_match(self._edges_cache[0], key):
                self._edges_cache = (key, lap_map.edge_offsets(base, self._limits))
            self._edges = self._edges_cache[1]
        else:
            self._edges = ([], [])
        lefts, rights = self._edges
        placements: dict[str, tuple[list[float], list[float], list[float]]] = {}
        cache: dict[str, tuple[tuple, tuple]] = {}
        if lefts:
            for lap in self.data.laps:
                if any(lap.data.columns.get("track_edge") or ()):  # game values recorded
                    continue
                found = self.lap_offsets(lap)
                if found is None or not found[1]:
                    continue
                placement_key = (found[1], self._edges)
                cached = self._placements.get(lap.key)
                if cached is None or not keys_match(cached[0], placement_key):
                    cached = self._prepared_placements.get(lap.key)  # measured in background (loading laps)
                if cached is None or not keys_match(cached[0], placement_key):
                    cached = (placement_key, self.lap_placements(found, lefts, rights))
                cache[lap.key] = cached
                placements[lap.key] = cached[1]
        unchanged = cache.keys() == self._placements.keys() and all(
            cache[name] is self._placements[name] for name in cache)
        self._placements = cache
        self._prepared_placements = {}
        if not unchanged or self.data.placements.keys() != placements.keys():  # charts drawn again only if changed
            self.data.set_placements(placements)

    @staticmethod
    def lap_placements(found: tuple, lefts: list[float], rights: list[float]) -> tuple:
        """Lap distances, distance to track middle (m, left positive like game) & track position (%) of each lap line
        point, between track edges (left & right edge offsets along base line)"""
        line, sides, indexes = found
        centers = [side - (lefts[index] + rights[index]) / 2 for side, index in zip(sides, indexes)]
        percents = [max(min(lap_map.placement(side, lefts[index], rights[index])[2], 150.0), -150.0)
                    for side, index in zip(sides, indexes)]
        return list(line.distances[:len(sides)]), centers, percents

    def lap_placement(self, lap: PlotLap, distance: float) -> tuple[float, float, float] | None:
        """Lap at distance: room to left edge, to right edge (m), track position (%), None if edges unknown"""
        lefts, rights = self._edges
        found = self.lap_offsets(lap) if lefts else None
        if found is None or not found[1]:
            return None
        line, sides, indexes = found
        position = min(max(bisect.bisect_left(line.distances, distance), 0), len(sides) - 1)
        if position > 0 and abs(line.distances[position - 1] - distance) < abs(line.distances[position] - distance):
            position -= 1
        index = indexes[position]
        return lap_map.placement(sides[position], lefts[index], rights[index])

    def lap_events(self, lap: PlotLap) -> list[tuple[float, str]]:
        """Off track moments (wheel surface) & track limits exceeded (game edge, else game edges of track)"""
        key = (lap.data, self._limits, self._limits_source, len(self._base.xs))
        cached = self._events.get(lap.key)
        if cached is not None and keys_match(cached[0], key):
            return cached[1]
        events = [(distance, "offtrack") for distance in lap_map.off_track_events(lap.data)]
        limits = lap_map.limits_events(lap.data)
        recorded = any(lap.data.columns.get("track_edge") or ())
        lefts, rights = self._edges
        if not recorded and self._limits_source == "game" and lefts:  # older lap, game edges known from others
            found = self.lap_offsets(lap)
            if found is not None:
                line, sides, indexes = found
                limits = lap_map.track_events(line.distances, [
                    side > lefts[index] + lap_map.CAR_HALF_WIDTH or side < rights[index] - lap_map.CAR_HALF_WIDTH
                    for side, index in zip(sides, indexes)])
        events += [(distance, "limit") for distance in limits]
        events.sort()
        shown = {shown_lap.key for shown_lap in self.data.laps}
        self._events = {name: value for name, value in self._events.items() if name in shown}
        self._events[lap.key] = (key, events)
        return events

    # Mini-sectors: lap split in equal parts, fastest shown lap in each part
    def mini_sectors(self) -> dict:
        """Mini-sectors of shown laps: bounds, winner of each, times, ideal time (invalid laps never win)"""
        return self.data.mini_sectors()

    def consistency_read(self):
        """Consistency mode laps or scope changed (mini-sector times read in background): map colored again"""
        if self._map and self._map_mode == "consistency":
            self.build_colored_line(self._map_view[2])
            self.bump_revision()
        self.mapChanged.emit()

    def build_map_bands(self):
        """Thick lines & markers sized for current map zoom, zoomed part, colored line

        Map scale rounded to steps: what does not depend on chart zoom is built once per step & cached,
        zooming back to a step already seen costs nothing.
        """
        if not self._map:
            return
        start, end, meters_per_pixel = self._map_view
        step = scale_step(meters_per_pixel)
        shown: float | None = step
        cached = self._band_cache.get(step)
        if cached is None:  # built in background (shown once ready), nearest built scale shown meanwhile if any
            self.prepare_step(step)
            shown = min(self._band_cache, key=lambda cached_step: abs(cached_step - step), default=None)
            cached = self._band_cache[shown] if shown is not None else None
        if shown is not None and cached is not None:
            self._band_cache.move_to_end(shown)
            self.trim_band_cache()
            if shown != self._preview_step or not self._band_cache_applied:
                for key, vertices in cached.items():
                    VertexStore.set(key, vertices)  # type: ignore[arg-type]
                self._band_cache_applied = True
            self._preview_step = shown
            self._prefetch_step = step
            self._prefetch_timer.start()  # neighbor scales once map stays still (threads would slow zoom frames)
        zoomed = end > start
        for (line, lap), keys in zip(self._map_lines, self._map["lines"]):
            scale = self.data.scale_of(lap)
            indexes = range_indexes(line.distances, start / scale, end / scale) if zoomed else range(0)
            VertexStore.set(keys["highlight"], band_part(line.xs, line.ys, self.line_normals(lap, line), indexes,
                                                         meters_per_pixel * ZOOMED_WIDTH))
        self.build_map_overlays(meters_per_pixel)
        self.build_colored_line(meters_per_pixel)

    def prefetch_steps(self, step: float):
        """Thick lines of next zoom steps in & out built in background: zoom preview always ready"""
        for neighbor in (step - 1 / ZOOM_BUCKETS, step + 1 / ZOOM_BUCKETS):
            self.prepare_step(neighbor)

    def prepare_step(self, step: float):
        """Thick lines of map scale step built in background, shown once ready if it is the scale shown"""
        generation = self._band_generation
        if step in self._band_cache or (generation, step) in self._prefetching or not self._map:
            return
        self._prefetching.add((generation, step))  # a step of a former map being built never stops this one
        frame = self.map_frame()  # page state read here: job never reads it

        def done(shapes):
            self._prefetching.discard((generation, step))
            if shapes is None or generation != self._band_generation or step in self._band_cache:
                return
            self._band_cache[step] = shapes  # kept like recently used, shown step kept newest
            if self._preview_step in self._band_cache:
                self._band_cache.move_to_end(self._preview_step)
            self.keep_frame_caches(frame)
            self.trim_band_cache()
            if self._map and step == scale_step(self._map_view[2]) and step != self._preview_step:
                self.build_map_bands()  # map waits at this scale: exact thickness now

        def building() -> dict[str, object]:  # map built again meanwhile: stops at next pause
            pause = Yielder(cancelled=lambda: generation != self._band_generation)
            return self.scale_shapes(2 ** step, frame, pause)

        self.run_job("map zoom step", building, done)

    def trim_band_cache(self):
        """Least recently used scale steps dropped over BAND_CACHE_STEPS, lap shapes & colored lines of dropped steps
        too (shown step kept)"""
        while len(self._band_cache) > BAND_CACHE_STEPS:
            self._band_cache.popitem(last=False)
        steps = set(self._band_cache)
        steps.add(scale_step(self._map_view[2]))
        if any(scale_step(key[1]) not in steps for key in self._lap_shapes):
            self._lap_shapes = {key: value for key, value in self._lap_shapes.items() if scale_step(key[1]) in steps}
        if any(step not in steps for step in self._colored_steps):
            self._colored_steps = {step: value for step, value in self._colored_steps.items() if step in steps}

    def build_minimap(self):
        """Whole circuit as thin lines for minimap (built once per map)"""
        road = self._road
        span = max(self._map["maxX"] - self._map["minX"], self._map["maxY"] - self._map["minY"], 1.0)
        meters = span / MINIMAP_PIXELS
        VertexStore.set(self._map["mini"], band(road.xs, road.ys, meters * 1.6) if len(road.xs) > 1 else band([], [], 1))

    def build_map_overlays(self, meters_per_pixel: float):
        """Chart markers A-B range & selected corner along reference line"""
        line = self.reference_map_line() or lap_map.MapLine([], [], [])
        start, end = self._map_range
        shown = lap_map.part(line, start, end) if end > start else lap_map.MapLine([], [], [])
        VertexStore.set(self._map["rangeKey"], lap_map.line_band(shown, meters_per_pixel * 7))
        selected = lap_map.MapLine([], [], [])
        if 0 <= self._selected_corner < len(self.corner_rows()):
            corner = self.corner_rows()[self._selected_corner].corner
            selected = lap_map.part(line, corner.start, corner.end)
        VertexStore.set(self._map["selectedKey"], lap_map.line_band(selected, meters_per_pixel * 9))

    def map_frame(self) -> dict[str, Any]:
        """What shapes sized for a map scale are built from, read on page thread (see scale_shapes): background builds
        never read page state, per lap caches copied (new entries kept by keep_frame_caches)"""
        reference = self.data.reference
        reference_line = self.reference_map_line()
        return {
            "map": dict(self._map), "lines": list(self._map_lines), "road": self._road, "angle": self._map_angle,
            "limits": self._limits, "show_limits": bool(self._map_options.get("limits")), "edges": self._edges,
            "reference": reference, "hysteresis": self._corner_table.sensitivity(), "sectors": tuple(self.data.sector_lines),
            "pit": list(self._pit), "reference_line": reference_line, "guide": self.guide_line(),
            "spreads": list(self._map_marks.brake_spreads().values()), "lap_shapes": dict(self._lap_shapes),
            "normals": dict(self._normals), "zones": dict(self._zones), "arrows": self._arrows,
            "edge_normals": self._edge_normals, "new": {"normals": {}, "zones": {}, "lap_shapes": {}},
        }

    def keep_frame_caches(self, frame: dict[str, Any]):
        """Per lap results computed by a background build (see map_frame) kept for laps still shown"""
        new = frame["new"]
        shown = {lap.key: lap.data for _, lap in self._map_lines}
        if new["zones"]:  # braking & throttle zones of each lap computed once per loaded lap (every scale uses them)
            self._zones = {key: value for key, value in self._zones.items() if key in shown}
        for name, cache in (("normals", self._normals), ("zones", self._zones)):
            for key, value in new[name].items():
                if shown.get(key) is value[0]:
                    cache[key] = value
        for key, value in new["lap_shapes"].items():
            if shown.get(key[0]) is value[0][0]:
                self._lap_shapes[key] = value
        if "arrows" in new and new["arrows"][0] is self.guide_line():
            self._arrows = new["arrows"]
        if "edge_normals" in new and keys_match(new["edge_normals"][0], (self._limits, self._map_angle)):
            self._edge_normals = new["edge_normals"]

    def scale_shapes(self, meters_per_pixel: float, frame: dict[str, Any] | None = None,
                     pause: Callable[[], None] | None = None) -> dict[str, object]:
        """Vertices of everything sized in pixels for map scale: road, lines, marks, markers, zones, arrows

        Built from frame (see map_frame, taken now if not given): thread job never reads page state, per lap results
        it computes left in frame["new"]. pause: called now & then (thread: Yielder, may stop a stale build).
        """
        frame = frame if frame is not None else self.map_frame()
        if pause is None:
            pause = Yielder() if threading.current_thread() is not threading.main_thread() else (lambda: None)
        map_keys, map_lines, angle, new = frame["map"], frame["lines"], frame["angle"], frame["new"]
        shapes: dict[str, object] = {}
        road = frame["road"]
        road_half = max(TRACK_WIDTH / 2, meters_per_pixel * 4)  # visible when zoomed out
        # Circuit (road, edges) does not depend on laps shown: kept per scale while circuit & rotation stay
        limits = frame["limits"] if frame["show_limits"] else None
        circuit_key = (meters_per_pixel, angle, limits, road.xs[0] if road.xs else 0.0, len(road.xs))
        cached_circuit = self._circuit_shapes.get(meters_per_pixel)
        if cached_circuit is not None and keys_match(cached_circuit[0], circuit_key):
            shapes[map_keys["road"]], shapes[map_keys["edge"]] = cached_circuit[1]
        else:
            shapes[map_keys["road"]], shapes[map_keys["edge"]] = self.circuit_shapes(
                road, road_half, meters_per_pixel, frame)
            with CIRCUIT_LOCK:
                self._circuit_shapes[meters_per_pixel] = (
                    circuit_key, (shapes[map_keys["road"]], shapes[map_keys["edge"]]))
                while len(self._circuit_shapes) > BAND_CACHE_STEPS * 2:
                    self._circuit_shapes.pop(next(iter(self._circuit_shapes)), None)
        reference = frame["reference"].data if frame["reference"] is not None else None
        # Lap shapes depend on map rotation, corners of reference lap & track edges (driving points, track-out,
        # events): not on other laps shown
        lap_key = (angle, reference, frame["hysteresis"], frame["limits"], frame["edges"])
        built: set[str] = set()
        for _, lap in map_lines:
            cached = frame["lap_shapes"].get((lap.key, meters_per_pixel))
            if cached is not None and keys_match(cached[0], (lap.data, *lap_key)):
                shapes.update(cached[1])  # lap shown before at this scale: nothing built
                built.add(lap.key)
        for (line, lap), keys in zip(map_lines, map_keys["lines"]):
            if lap.key in built:
                continue
            pause()
            shapes[keys["key"]] = band_part(line.xs, line.ys, frame_normals(frame, lap, line),
                                            lap_map.kept_indexes(line, meters_per_pixel * 0.75),
                                            meters_per_pixel * LINE_WIDTH)
        marks = []
        reference_line = frame["reference_line"]
        if reference_line is not None:
            for distance in frame["sectors"]:  # sector boundaries across road
                marks.append(lap_map.cross_mark(reference_line, distance, road_half * 1.6))
        shapes[map_keys["marks"]] = segments(marks)
        # Markers: one buffer per lap & kind, outline (map background color) drawn under fill
        points: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
        for point in map_keys.get("points", []) + map_keys.get("slips", []) + map_keys.get("events", []):
            points.setdefault((point["lap"], point["kind"]), []).append(
                (point["x"], point["y"], math.radians(point.get("angle", 0.0))))
        for item in map_keys["markers"]:
            if item["lap"] in built:
                continue
            pause()
            for shape in item["shapes"]:
                pixels, form = MARKER_PIXELS[shape["kind"]]
                found = points.get((item["lap"], shape["kind"]), [])
                shapes[shape["fill"]] = markers(found, form, pixels * meters_per_pixel)
                outline = "dot" if form in ("dot", "ring") else form.replace("hollow_", "")
                shapes[shape["outline"]] = markers(found, outline, (pixels + OUTLINE_PIXELS * 2) * meters_per_pixel)
        # Braking & throttle application zones of each lap
        for (line, lap), keys, item in zip(map_lines, map_keys["lines"], map_keys["markers"]):
            if lap.key in built:
                continue
            pause()
            zones = frame["zones"].get(lap.key)
            if zones is None or zones[0] is not lap.data:
                zones = frame["zones"][lap.key] = new["zones"][lap.key] = (lap.data, lap_map.pedal_zones(lap.data))
            braking, applying = zones[1]
            line_normals = frame_normals(frame, lap, line)
            shapes[item["brakeZones"]] = lap_map.zones_band(line, braking, meters_per_pixel * 6, line_normals)
            shapes[item["throttleZones"]] = lap_map.zones_band(line, applying, meters_per_pixel * 6, line_normals)
            own = [keys["key"], item["brakeZones"], item["throttleZones"]]
            own += [key for shape in item["shapes"] for key in (shape["fill"], shape["outline"])]
            new["lap_shapes"][(lap.key, meters_per_pixel)] = ((lap.data, *lap_key), {key: shapes[key] for key in own})
        guide = frame["guide"]
        if not frame["arrows"] or frame["arrows"][0] is not guide:
            frame["arrows"] = new["arrows"] = (guide, lap_map.direction_marks(guide))
        arrows = [(x, y, math.radians(angle)) for x, y, angle in frame["arrows"][1]]
        shapes[map_keys["arrowsKey"]] = markers(arrows, "triangle", ARROW_PIXELS * meters_per_pixel)
        pits = [band(part.xs, part.ys, meters_per_pixel * 1.2) for part in frame["pit"]]
        shapes[map_keys["pit"]] = merge_strips(pits) if pits else band([], [], 1)
        # Braking points range of shown laps in each corner, along reference line
        spreads = []
        if reference_line is not None and len(map_lines) > 1 and frame["spreads"]:
            reference_lap = frame["reference"]
            reference_normals = frame_normals(frame, reference_lap, reference_line) if reference_lap is not None and any(
                lap is reference_lap for _, lap in map_lines) else normals(reference_line.xs, reference_line.ys)
            for low, high in frame["spreads"]:
                if high - low >= 1:
                    spreads.append(band_part(reference_line.xs, reference_line.ys, reference_normals,
                                             range_indexes(reference_line.distances, low, high), meters_per_pixel * 6))
        shapes[map_keys["spread"]] = merge_strips(spreads) if spreads else band([], [], 1)
        return shapes

    def circuit_shapes(self, road: lap_map.MapLine, road_half: float, meters_per_pixel: float,
                       frame: dict[str, Any]) -> tuple:
        """Road & road edge (or track edges) sized for map scale"""
        if frame["limits"] is not None and frame["show_limits"]:  # road between guessed track edges, thin edge lines
            limits = lap_map.TrackLimits(lap_map.rotate_line(frame["limits"].left, frame["angle"]),
                                         lap_map.rotate_line(frame["limits"].right, frame["angle"]))
            key = (frame["limits"], frame["angle"])
            if not frame["edge_normals"] or not keys_match(frame["edge_normals"][0], key):
                frame["edge_normals"] = frame["new"]["edge_normals"] = (key, (
                    lap_map.PackedNormals(limits.left.xs, limits.left.ys),
                    lap_map.PackedNormals(limits.right.xs, limits.right.ys)))
            keep = lap_map.kept_indexes(limits.left, meters_per_pixel * 0.75)
            edges = [band_part(edge.xs, edge.ys, edge_normals, keep, meters_per_pixel * 1.1)
                     for edge, edge_normals in zip((limits.left, limits.right), frame["edge_normals"][1])]
            return lap_map.limits_band(limits, keep), merge_strips(edges)
        closed = len(road.xs) > 2 and (road.xs[0] - road.xs[-1]) ** 2 + (road.ys[0] - road.ys[-1]) ** 2 < 50 ** 2
        simple_road = lap_map.simplify(road, meters_per_pixel * 0.75)
        return (band(simple_road.xs, simple_road.ys, road_half, closed),
                band(simple_road.xs, simple_road.ys, road_half + meters_per_pixel * 1.5, closed))

    def direction_marks(self) -> list[tuple[float, float, float]]:
        """Driving direction arrows along reference line (or circuit), once per line"""
        line = self.guide_line()
        if not self._arrows or self._arrows[0] is not line:
            self._arrows = (line, lap_map.direction_marks(line))
        return self._arrows[1]

    def turned_line(self, lap: PlotLap, line: lap_map.MapLine) -> lap_map.MapLine:
        """Lap line turned like map, once per lap & map rotation (same object: kept caches stay valid)"""
        cached = self._turned.get(lap.key)
        if cached is None or cached[0] is not lap.data or cached[1] != self._map_angle:
            cached = self._turned[lap.key] = (lap.data, self._map_angle, lap_map.rotate_line(line, self._map_angle))
        return cached[2]

    def line_normals(self, lap: PlotLap, line: lap_map.MapLine) -> lap_map.PackedNormals:
        """Normals of lap line turned like map: same at every map scale, computed once per lap & map rotation"""
        cached = self._normals.get(lap.key)
        if cached is None or cached[0] is not lap.data or cached[1] != self._map_angle or cached[2] != len(line.xs):
            cached = (lap.data, self._map_angle, len(line.xs), lap_map.PackedNormals(line.xs, line.ys))
            self._normals[lap.key] = cached
        return cached[3]

    def build_colored_line(self, meters_per_pixel: float):
        """Line of current color mode: compared lap by time gain, reference lap by speed or pedals

        Colors depend on laps & options only: computed once, map zoom only simplifies the line again.
        """
        key = self._map["colored"]
        mode = self._map_mode
        lines = self._map_lines
        if mode == "laps" or not lines:
            self._speed_range = (0.0, 0.0)
            self._colored_shown = None
            VertexStore.set(key, lap_map.colored_line(lap_map.MapLine([], [], []), [], 0))
            return
        color_key = self.color_key(mode)
        if self._color_lines and keys_match(self._color_lines[0], color_key):
            line, colors, self._speed_range = self._color_lines[1]
        else:
            line, colors = self.line_colors(mode, lines)
            self._color_lines = (color_key, (line, colors, self._speed_range))
            self._colored_steps = {}
        if line is None:
            self._colored_shown = None
            VertexStore.set(key, lap_map.colored_line(lap_map.MapLine([], [], []), [], 0))
            return
        step = scale_step(meters_per_pixel)
        vertices = self._colored_steps.get(step)
        if vertices is None:  # built once per map scale step (chart zoom & pan reuse it)
            scale = 2 ** step
            simple = lap_map.simplify(line, scale * 0.5)
            if simple is not line and colors:  # colors of kept points
                index = {distance: number for number, distance in enumerate(line.distances)}
                colors = [colors[index[distance]] for distance in simple.distances]
            vertices = self._colored_steps[step] = lap_map.colored_line(simple, colors, scale * ZOOMED_WIDTH)
        if self._colored_shown is not vertices or not VertexStore.has(key):  # not uploaded again on chart zoom
            VertexStore.set(key, vertices)
            self._colored_shown = vertices

    def color_key(self, mode: str) -> tuple:
        """What colored line of map mode depends on (colors computed again only if it changes)"""
        reference = self.data.reference.data if self.data.reference is not None else None
        compared = self.compared_lap()
        compared_data = compared.data if compared is not None else None
        colorblind = bool(self._map_options.get("colorblind"))
        line = self.reference_map_line()  # reference lap line, or official circuit standing for it
        if mode == "gain":
            return (mode, reference, compared_data, self.data.delta_window, colorblind, self._map_angle)
        if mode == "line":
            return (mode, reference, compared_data, line, self._map_angle)
        if mode == "corners":
            return (mode, reference, self._corner_table.key, colorblind, line, self._map_angle)
        if mode == "minisectors":
            return (mode, tuple(lap.data for _, lap in self._map_lines), tuple(lap.color.rgba() for _, lap in self._map_lines),
                    tuple(lap.clean for _, lap in self._map_lines), line, self._map_angle)
        if mode == "consistency":  # spreads found again (laps read in background meanwhile)
            found = self._map_consistency.measure()
            return (mode, reference, tuple(found.get("spreads", [])), line, self._map_angle)
        if mode == "pedals":
            return (mode, reference, colorblind, line, self._map_angle)
        return (mode, reference, line, self._map_angle)

    def line_colors(self, mode: str, lines: list[tuple[lap_map.MapLine, PlotLap]],
                    ) -> tuple[lap_map.MapLine | None, list[QColor]]:
        """Colored line of map mode & its color at each point, None if nothing to color

        Compared lap line in gain & line modes, else reference map line (reference lap line, official circuit if
        reference lap has no positions; line mode needs reference lap line).
        """
        self._speed_range = (0.0, 0.0)
        reference = self.data.reference
        compared = self.compared_lap()
        found = next(((line, lap) for line, lap in lines if compared is not None and lap is compared), None)
        reference_line = self.reference_map_line()
        if mode in ("gain", "line"):
            if found is None or reference is None:
                return None, []
        elif reference_line is None or reference is None:
            return None, []
        else:
            line, lap = reference_line, reference
        if mode == "gain":
            delta = self.data.reference_deltas.get(found[1].key) if found is not None else None
            if found is None or not delta:
                return None, []
            line, lap = found
            colors = lap_map.gain_colors_from_delta(delta[0], delta[1], line, self.data.scale_of(lap),
                                                    self.data.delta_window, bool(self._map_options.get("colorblind")))
        elif mode == "corners":  # reference line colored corner by corner by compared lap time delta
            corners = [(row.corner.start, row.corner.end, row.time_delta) for row in self.corner_rows()
                       if row.time_delta is not None]
            colors = lap_map.corner_delta_colors(line, corners, bool(self._map_options.get("colorblind")))
        elif mode == "minisectors":  # reference line colored by fastest shown lap of each mini-sector
            mini = self.mini_sectors()
            if not mini:
                return None, []
            bounds, winners = mini["bounds"], mini["winners"]
            neutral = QColor("#9CA3AF")
            laps = self.data.laps
            colors = []
            for distance in line.distances:
                sector = min(max(bisect.bisect_right(bounds, distance) - 1, 0), len(winners) - 1)
                winner = winners[sector] if winners else -1
                colors.append(laps[winner].color if 0 <= winner < len(laps) else neutral)
        elif mode == "consistency":  # reference line colored by spread of each mini-sector time over laps
            spread = self._map_consistency.found
            if not any(value >= 0 for value in spread.get("spreads", [])):
                return None, []
            colors = lap_map.spread_colors(line, spread["bounds"], spread["spreads"])
        elif mode == "line":  # compared lap line: inside or outside of reference lap line
            if (found is None or reference is None or reference_line is None
                    or not any(lap is reference for _, lap in lines)):
                return None, []
            line, lap = found
            colors = lap_map.line_colors(self.line_offsets(reference_line, reference, line, lap))
        else:
            if mode == "speed":
                colors, low, high = lap_map.speed_colors(lap.data, line)
                self._speed_range = (low, high)
            elif mode == "elevation":
                colors, low, high = lap_map.elevation_colors(lap.data, line)
                self._speed_range = (low, high)
            elif mode == "gear":
                colors = lap_map.gear_colors(lap.data, line)
            else:
                colors = lap_map.pedal_colors(lap.data, line, bool(self._map_options.get("colorblind")))
        return line, colors

    def line_offsets(self, reference_line: lap_map.MapLine, reference: PlotLap, line: lap_map.MapLine,
                     lap: PlotLap) -> list[float]:
        """Compared line distance to reference line, cached (slow, map zoom rebuilds colored line)"""
        key = (reference.key, reference.data, lap.key, lap.data)  # offsets do not change when map turns
        cached = self._line_offsets.get("key")
        if cached is None or not keys_match(cached, key):
            self._line_offsets = {"key": key, "offsets": lap_map.line_offsets(reference_line, line)}
        return self._line_offsets["offsets"]

    @Slot(str, bool)
    def setMapOption(self, name: str, enabled: bool):
        """Track map display option: apex, exit, arrows, sectors, values"""
        if name in self._map_options and self._map_options[name] != enabled:
            self._map_options[name] = enabled
            save_viewer_setting(self.folder, map_options=self._map_options)
            if self._map and name == "limits":
                self.build_map()
                self.bump_revision()
                self.chartChanged.emit()
            elif self._map and name == "colorblind" and self._map_mode in ("gain", "corners", "pedals"):
                self.build_colored_line(self._map_view[2])
                self.bump_revision()
            self.mapChanged.emit()

    @Slot(float, float, float)
    def setMapView(self, start_x: float, end_x: float, meters_per_pixel: float):
        """Charts zoom (axis range, equal if not zoomed) & map scale: map lines rebuilt"""
        start, end = (self.data.distance_at_x(start_x), self.data.distance_at_x(end_x)) if end_x > start_x else (0, 0)
        view = (start, end, max(meters_per_pixel, 1e-3))
        if view != self._map_view or scale_step(view[2]) != self._preview_step:  # zoom preview showed another step
            self._map_view = view
            self.build_map_bands()
            self.bump_revision()

    @Slot(float)
    def previewMapScale(self, meters_per_pixel: float):
        """Map zoom easing: thick lines of nearest scale step already built shown at once (nothing built)"""
        if not self._map:
            return
        wanted = scale_step(meters_per_pixel)
        # Nearest step already built (target step is prepared as soon as zoom starts, see prepareMapScale)
        step = min(self._band_cache, key=lambda cached_step: abs(cached_step - wanted), default=math.nan)
        if math.isnan(step) or step == self._preview_step or (
                not math.isnan(self._preview_step) and abs(self._preview_step - wanted) <= abs(step - wanted)):
            return
        cached = self._band_cache[step]
        self._preview_step = step
        for key, vertices in cached.items():
            VertexStore.set(key, vertices)  # type: ignore[arg-type]

    @Slot(float)
    def prepareMapScale(self, meters_per_pixel: float):
        """Map zoom starting toward a scale: its thick lines built in background (shown while zoom eases)"""
        if not self._map:
            return
        self.prepare_step(scale_step(meters_per_pixel))

    @Slot(str)
    def setMapMode(self, mode: str):
        if mode in lap_map.MAP_MODES and mode != self._map_mode:
            self._map_mode = mode
            save_viewer_setting(self.folder, map_color_mode=mode)
            if self._map:
                self.build_colored_line(self._map_view[2])
                self.bump_revision()
            self.mapChanged.emit()

    @Slot(bool)
    def setMapFollow(self, enabled: bool):
        self._map_follow = enabled
        save_viewer_setting(self.folder, map_follow_zoom=enabled)
        self.mapChanged.emit()

    @Slot(bool)
    def setMapBraking(self, enabled: bool):
        self._map_braking = enabled
        save_viewer_setting(self.folder, map_braking_points=enabled)
        self.mapChanged.emit()

    @Slot(bool)
    def setMapSlip(self, enabled: bool):
        self._map_slip = enabled
        save_viewer_setting(self.folder, map_slip_points=enabled)
        self.mapChanged.emit()

    def map_rotated(self):
        """Map built again turned (orientation changed)"""
        if self.data.laps:
            self.build_map()
            self.bump_revision()
            self.mapDataChanged.emit()
        self.mapChanged.emit()

    @Slot()
    def rotateMap(self):
        """Turn map a quarter clockwise"""
        self._map_quarters = (self._map_quarters + 1) % 4
        save_viewer_setting(self.folder, map_rotation=self._map_quarters)
        self.map_rotated()

    @Slot(bool)
    def setMapAutoOrient(self, enabled: bool):
        self._map_auto_orient = enabled
        save_viewer_setting(self.folder, map_auto_orient=enabled)
        self.map_rotated()

    @Slot(float)
    def setMapAspect(self, aspect: float):
        """Map view width / height: auto orientation follows view shape"""
        tall = aspect < 1
        changed = tall != (self._map_aspect < 1)
        self._map_aspect = aspect
        if changed and self._map_auto_orient:
            self.map_rotated()
