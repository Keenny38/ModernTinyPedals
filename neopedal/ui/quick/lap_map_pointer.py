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
Lap viewer track map pointing (part of LapViewerBackend, QML backend.mapPointer): mouse over map (driving point,
reference line & lap line under it), position & heading of each lap at cursor, map area following chart zoom

Reads the map the page keeps (map lines of shown laps, picking grids, map angle, points), see PointerHost.
"""

from __future__ import annotations

import bisect
import math
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject, Slot

from ...i18n import tr
from ...userfile.telemetry_lap import LapData, interpolate
from ..lap_viewer import PlotLap, distance_text, signed
from . import lap_map
from .lap_base import PagePart, weak_host

if TYPE_CHECKING:
    from .trace_data import TraceData


def yaw_calibration(lap: LapData) -> tuple[float, float]:
    """Sign & offset turning recorded yaw into map heading (radians): heading = sign * yaw + offset, sign 0 if
    not found (car not pointing where it goes)"""
    columns = lap.columns
    yaws, xs, ys, speeds = columns.get("yaw"), columns.get("pos_x"), columns.get("pos_y"), columns.get("speed_kph")
    if not yaws or not xs or not ys or not speeds:
        return 0.0, 0.0
    samples = []
    for index in range(5, len(yaws) - 5, 5):
        if speeds[index] < 60:
            continue
        dx, dy = xs[index + 5] - xs[index - 5], ys[index + 5] - ys[index - 5]
        if dx * dx + dy * dy < 4:
            continue
        samples.append((math.atan2(dy, dx), yaws[index]))
    if len(samples) < 20:
        return 0.0, 0.0
    best = (math.inf, 0.0, 0.0)
    for sign in (1.0, -1.0):
        offset = math.atan2(sum(math.sin(travel - sign * yaw) for travel, yaw in samples),
                            sum(math.cos(travel - sign * yaw) for travel, yaw in samples))
        error = sum(abs((travel - sign * yaw - offset + math.pi) % math.tau - math.pi)
                    for travel, yaw in samples) / len(samples)
        if error < best[0]:
            best = (error, sign, offset)
    error, sign, offset = best
    return (sign, offset) if error < math.radians(8) else (0.0, 0.0)


class PointerHost(Protocol):
    """What the map pointing part uses of the lap viewer page"""

    data: TraceData
    _map: dict
    _map_angle: float
    _map_lines: list[tuple[lap_map.MapLine, PlotLap]]
    _grids: dict[str, lap_map.LineGrid]

    def cursorState(self, x: float) -> dict: ...
    def placementAt(self, x: float, lap_key: str = "") -> dict: ...
    def reference_grid(self) -> lap_map.LineGrid | None: ...
    def reference_map_line(self) -> lap_map.MapLine | None: ...


class MapPointer(PagePart):
    """Map pointing of lap viewer page (QML backend.mapPointer)"""

    def __init__(self, page: PointerHost, parent: QObject | None = None):
        super().__init__(parent)
        self._page = weak_host(page)
        self._yaw: dict[str, tuple[LapData, float, float]] = {}  # lap key: lap data, yaw sign & offset to map heading
        # Kinds of hovered points (driving points, wheel slips, events), told by map when they change
        self._map_kinds = ["brake", "apex", "exit", "trackout", "lock", "spin", "bottom", "offtrack", "limit"]
        self._line_boxes: tuple = ()  # reference map line, bounding box of each part of it (map follows charts)

    def release(self):
        self.forget()

    def forget(self):
        """Loaded laps released: results kept per lap forgotten (they keep lap data)"""
        self._yaw = {}
        self._line_boxes = ()

    @Slot(float, float, result=list)
    def mapBounds(self, start_x: float, end_x: float) -> list[float]:
        """Map area of reference line between axis positions (map follows chart zoom), empty if none"""
        page = self._page
        reference_line = page.reference_map_line()
        if reference_line is None:
            return []
        if not self._line_boxes or self._line_boxes[0] is not reference_line:  # map follows chart zoom every frame
            self._line_boxes = (reference_line, lap_map.chunk_boxes(reference_line))
        return lap_map.part_bounds(reference_line, self._line_boxes[1], page.data.distance_at_x(start_x),
                                   page.data.distance_at_x(end_x))

    @Slot(float, result=list)
    def mapCursor(self, x: float) -> list[dict]:
        """Position of each lap at axis position, map coordinates (time axis: where each lap is at that time)"""
        return self.map_cursor(x)

    def map_cursor(self, x: float, constant: bool = True) -> list[dict]:
        """Map positions at cursor (see mapCursor), lap color & key left out unless constant (cursorState: QML takes
        them from map laps)"""
        page = self._page
        positions, texts = self.map_positions(x, True)
        points = []
        for index, (lap, (gap, slip)) in enumerate(zip((lap for _, lap in page._map_lines), texts)):
            point = {"x": positions[index * 3], "y": positions[index * 3 + 1], "angle": positions[index * 3 + 2],
                     "gap": gap, "slip": slip}
            if constant:
                point.update(color=lap.color.name(), lap=lap.key)
            points.append(point)
        return points

    def map_positions(self, x: float, texts: bool = False) -> tuple[list[float], list[tuple[str, str]]]:
        """Map position of each lap at cursor as one flat list (x, y, angle in degrees of each lap: playback frames
        move cars without building a dict per lap), gap to reference lap & slip angle texts of each lap if texts"""
        page = self._page
        positions: list[float] = []
        labels: list[tuple[str, str]] = []
        reference = page.data.reference
        reference_distance = page.data.lap_distance_at_x(reference, x) if reference is not None else 0.0
        reference_distance *= page.data.scale_of(reference) if reference is not None else 1.0
        deltas = page.data.reference_deltas
        for line, lap in page._map_lines:
            distance = page.data.lap_distance_at_x(lap, x)  # lap distance (own line)
            travel = math.degrees(lap_map.heading_at(line, distance))
            angle, slip = travel, ""
            heading = self.lap_heading(lap, distance)
            if heading is not None:  # car pointing direction (recorded), driving direction: slip angle
                angle = math.degrees(heading + page._map_angle)
                if texts:
                    drift = (angle - travel + 180) % 360 - 180
                    slip = f"{drift:+.0f}°" if abs(drift) >= 1.5 else ""
            positions += (interpolate(line.distances, line.xs, distance), interpolate(line.distances, line.ys, distance),
                          angle)
            if not texts:
                continue
            along = distance * page.data.scale_of(lap)  # reference distance
            gap = ""  # behind (+) or ahead (-) of reference lap: time on distance axis, meters on time axis
            if lap is not reference:
                if page.data.time_axis:
                    gap = distance_text(reference_distance - along, sign=True)
                elif lap.key in deltas and deltas[lap.key][0]:
                    gap = signed(interpolate(*deltas[lap.key], along), 2, " s")
            labels.append((gap, slip))
        return positions, labels

    def lap_heading(self, lap: PlotLap, distance: float) -> float | None:
        """Car heading on map at distance (radians, map not turned) from recorded yaw, None if not recorded

        Game yaw & map heading differ by a sign and an offset (game axes): both found on each lap from driving
        direction at speed, where car points nearly where it goes.
        """
        page = self._page
        yaws = lap.data.columns.get("yaw")
        if not yaws or not any(yaws):
            return None
        cached = self._yaw.get(lap.key)
        if cached is None or cached[0] is not lap.data:
            cached = (lap.data, *yaw_calibration(lap.data))
            self._yaw = {key: value for key, value in self._yaw.items()
                         if key in {shown.key for shown in page.data.laps}}
            self._yaw[lap.key] = cached
        _, sign, offset = cached
        if sign == 0:
            return None
        distances = lap.data.distance
        index = min(max(bisect.bisect_left(distances, distance), 0), len(yaws) - 1)
        return sign * yaws[index] + offset

    @Slot(float, float, float, result=float)
    def mapPick(self, map_x: float, map_y: float, radius: float) -> float:
        """Axis position of reference line point nearest to map point, -1 if farther than radius"""
        page = self._page
        grid = page.reference_grid()
        distance = grid.project(map_x, map_y, radius) if grid is not None else -1.0  # between samples
        return page.data.x_at_distance(distance) if distance >= 0 else -1.0

    @Slot(float, float, float, result=dict)
    def mapPickLap(self, map_x: float, map_y: float, radius: float) -> dict:
        """Lap line nearest to map point: lap key & axis position of that point on its lap, empty if none"""
        page = self._page
        best, found = radius * radius, None
        for line, lap in page._map_lines:
            grid = page._grids.get(lap.key)
            index = grid.nearest(map_x, map_y, radius) if grid is not None else -1
            if index >= 0:
                gap = (line.xs[index] - map_x) ** 2 + (line.ys[index] - map_y) ** 2
                if gap <= best:
                    best, found = gap, (lap, grid.project(map_x, map_y, radius) if grid is not None else -1.0)
        if found is None:
            return {}
        lap, distance = found
        return {"lap": lap.key, "x": page.data.x_at_lap_distance(lap, distance)}

    @Slot(list)
    def setMapKinds(self, kinds: list):
        """Driving point & wheel slip kinds shown on map (see mapHover), told only when they change"""
        self._map_kinds = [str(kind) for kind in kinds]

    @Slot(float, float, float, float, str, bool, result=dict)
    def mapHover(self, map_x: float, map_y: float, point_radius: float, pick_radius: float, highlight: str,
                 scrub: bool) -> dict:
        """Mouse over map, everything in one call: driving point under mouse among shown kinds (point, empty if
        none), then unless not scrub (no chart or lap playing): axis position of reference line under mouse (x, -1
        if none), and there lap across track (placement, unless a driving point is hovered) & chart cursor state
        (cursor, see cursorState)"""
        page = self._page
        point = self.mapPointAt(map_x, map_y, point_radius, self._map_kinds)
        result: dict = {"point": point}
        if not scrub:
            return result
        position = self.mapPick(map_x, map_y, pick_radius)
        result["x"] = position
        if position >= 0:
            result["placement"] = {} if "tip" in point else page.placementAt(position, highlight)
            result["cursor"] = page.cursorState(position)
        return result

    @Slot(float, float, float, list, result=dict)
    def mapPointAt(self, map_x: float, map_y: float, radius: float, kinds: list) -> dict:
        """Driving point or wheel slip nearest to map point among shown kinds (tooltip), empty if none"""
        page = self._page
        best, found = radius * radius, {}
        for point in page._map.get("points", []) + page._map.get("slips", []):
            if point["kind"] in kinds:
                gap = (point["x"] - map_x) ** 2 + (point["y"] - map_y) ** 2
                if gap <= best:
                    best, found = gap, point
        if found and "tip" not in found:  # wheel slip
            title = tr({"lock": "Front wheel lockup", "spin": "Rear wheelspin"}.get(found["kind"], "Bottoming"))
            found = {**found, "tip": f"{title} · {distance_text(found['distance'])}", "corner": -1}
        return found
