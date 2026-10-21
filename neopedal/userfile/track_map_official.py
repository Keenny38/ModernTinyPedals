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
Official circuit of game (LMU REST API) as track map, until a lap is recorded

Circuit path of game (AI driving line, closed loop, a point every 5 meters, see track_geometry) has no start line
nor sector lines. Its shape is shown as soon as fetched; start line placed from a car on track (its position along
path & its lap distance, twice: driving direction), path then turned to start there with lap distances scaled to
game track length; sector lines placed at lap distance where player crosses them. Saved as recorded track map
(mapping module) once start & both sector lines are known.
"""

from __future__ import annotations

import logging
import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence

logger = logging.getLogger(__name__)

MIN_POINTS = 20  # fewer points: not a circuit path
MAX_OFFSET = 15.0  # meters from path: farther is pit lane, off track or another layout
MIN_TRAVEL = 50.0  # lap distance driven by a car between its two samples (direction along path)
MAX_TRAVEL = 400.0  # farther: samples of another lap or after a teleport, sampled again
LENGTH_TOLERANCE = 0.1  # path length within 10% of game track length, else another layout
TRACKMAP_ROUTE = "/rest/watch/trackmap"  # circuit of current session, null outside sessions

Point = tuple[float, float, float]  # x, y (map coordinates), elevation


class CircuitPath:
    """Closed circuit path: points, length along path of each point, nearest point of path"""

    __slots__ = ("points", "arcs", "length")

    def __init__(self, points: Sequence[Point]):
        nodes = list(points)
        if len(nodes) > 2 and math.hypot(nodes[0][0] - nodes[-1][0], nodes[0][1] - nodes[-1][1]) < 1.0:
            nodes.pop()  # loop closed by a copy of first point
        self.points = nodes
        arcs = [0.0]
        for index, (x0, y0, _) in enumerate(nodes):
            x1, y1, _ = nodes[(index + 1) % len(nodes)]  # last segment back to first point
            arcs.append(arcs[-1] + math.hypot(x1 - x0, y1 - y0))
        self.arcs = arcs  # one more than points: arcs[-1] is loop length
        self.length = arcs[-1]

    def project(self, x: float, y: float) -> tuple[float, float]:
        """Length along path of nearest point of path & distance to it"""
        nodes = self.points
        total = len(nodes)
        best_gap = math.inf
        best_arc = 0.0
        for index in range(total):
            x0, y0, _ = nodes[index]
            x1, y1, _ = nodes[index + 1 if index + 1 < total else 0]
            dx, dy = x1 - x0, y1 - y0
            segment = dx * dx + dy * dy
            fraction = 0.0 if segment <= 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / segment))
            gap_x, gap_y = x0 + dx * fraction - x, y0 + dy * fraction - y
            gap = gap_x * gap_x + gap_y * gap_y
            if gap < best_gap:
                best_gap = gap
                best_arc = self.arcs[index] + fraction * (self.arcs[index + 1] - self.arcs[index])
        return best_arc, math.sqrt(best_gap)

    def point_at(self, arc: float) -> Point:
        """Point of path at length along path (wrapped around loop)"""
        arc %= self.length
        index = max(bisect_right(self.arcs, arc) - 1, 0)
        x0, y0, z0 = self.points[index]
        x1, y1, z1 = self.points[(index + 1) % len(self.points)]
        segment = self.arcs[index + 1] - self.arcs[index]
        fraction = (arc - self.arcs[index]) / segment if segment > 0 else 0.0
        return x0 + (x1 - x0) * fraction, y0 + (y1 - y0) * fraction, z0 + (z1 - z0) * fraction


class OfficialMap:
    """Official circuit placed as track map (see module doc)

    Args:
        path: circuit path of game.
        track_length: game track length (meters), lap distances scaled to it.
    """

    __slots__ = ("path", "scale", "coords", "dists", "sector_distances", "_samples")

    def __init__(self, path: CircuitPath, track_length: float):
        self.path = path
        self.scale = track_length / path.length if track_length > 0 else 1.0
        self.coords: tuple[tuple[float, float], ...] = tuple((x, y) for x, y, _ in path.points)
        self.dists: tuple[tuple[float, float], ...] | None = None  # lap distance & elevation, once start placed
        self.sector_distances: list[float] = [-1.0, -1.0]  # lap distance of each sector line, -1 unknown
        self._samples: dict[int, tuple[float, float]] = {}  # car: lap distance & length along path

    @classmethod
    def build(cls, points: Sequence[Point] | None, track_length: float) -> OfficialMap | None:
        """Official map of circuit points, None if too few or length far from game track length (other layout)"""
        if not points or len(points) < MIN_POINTS:
            return None
        path = CircuitPath(points)
        if path.length <= 0:
            return None
        if track_length > 0 and abs(path.length - track_length) > track_length * LENGTH_TOLERANCE:
            logger.info("TRACK MAP: official circuit %.0f m long, track %.0f m: not used", path.length, track_length)
            return None
        return cls(path, track_length)

    @property
    def placed(self) -> bool:
        """Start line placed"""
        return self.dists is not None

    def sample(self, car: int, x: float, y: float, lap_distance: float) -> bool:
        """Position & lap distance of a car on track (not in pit lane), True when start line placed by it now

        Path projected only for a first sample of car & once it drove MIN_TRAVEL (cheap otherwise, also for a car
        stopped off path).
        """
        if self.dists is not None or not lap_distance >= 0:
            return False
        first = self._samples.get(car)
        if first is not None and 0 <= lap_distance - first[0] < MIN_TRAVEL:
            return False
        arc, offset = self.path.project(x, y)
        if offset > MAX_OFFSET:  # pit lane, off track or not this circuit: projected again once car drove on
            self._samples[car] = (lap_distance, -1.0)
            return False
        if first is None or first[1] < 0 or not 0 < lap_distance - first[0] <= MAX_TRAVEL:
            self._samples[car] = (lap_distance, arc)
            return False
        length = self.path.length
        driven = (lap_distance - first[0]) / self.scale
        tolerance = driven * 0.25 + 5.0
        if abs((arc - first[1]) % length - driven) <= tolerance:
            self.place(arc, lap_distance)
        elif abs((first[1] - arc) % length - driven) <= tolerance:  # path given in other direction
            self.path = CircuitPath(self.path.points[::-1])
            self.place(self.path.project(x, y)[0], lap_distance)
        else:  # car did not follow path (cut, spin): sampled again
            self._samples[car] = (lap_distance, arc)
            return False
        self._samples.clear()
        return True

    def place(self, arc: float, lap_distance: float) -> None:
        """Start line placed from length along path of a car at lap distance: nodes from start line"""
        path = self.path
        length = path.length
        start = (arc - lap_distance / self.scale) % length
        first = bisect_left(path.arcs, start) % len(path.points)  # first node at or after start line
        x, y, z = path.point_at(start)
        coords = [(x, y)]
        dists = [(0.0, z)]
        for step in range(len(path.points)):
            index = (first + step) % len(path.points)
            along = (path.arcs[index] - start) % length
            if along < 0.5 or along > length - 0.5:  # start line node itself
                continue
            x, y, z = path.points[index]
            coords.append((x, y))
            dists.append((along * self.scale, z))
        self.coords = tuple(coords)
        self.dists = tuple(dists)

    def sector_crossed(self, sector: int, lap_distance: float) -> bool:
        """Lap distance where player crossed sector line (0: first, 1: second), True when both known now"""
        if not 0 <= sector <= 1 or not lap_distance > 0:
            return False
        known = self.sector_indexes() is not None
        self.sector_distances[sector] = lap_distance
        return not known and self.sector_indexes() is not None

    def sector_indexes(self) -> tuple[int, int] | None:
        """Node index before each sector line (as recorded maps), None until start & both lines known in order"""
        dists = self.dists
        first, second = self.sector_distances
        if dists is None or not 0 < first < second:
            return None
        values = [dist for dist, _ in dists]
        indexes = (bisect_right(values, first) - 1, bisect_right(values, second) - 1)
        if not 0 < indexes[0] < indexes[1] < len(dists) - 1:
            return None
        return indexes


def fetch_official_points(track_name: str, track_length: float) -> list[Point] | None:
    """Circuit path of current session from game (blocking: background thread), else of layout of track name
    closest to track length, None if game does not answer or Rest API access disabled"""
    from ..game_rest_cache import lmu_address, rest_cache
    from .track_geometry import fetch_geometry, parse_points

    address = lmu_address()
    if address is None:
        return None
    points = rest_cache.json(TRACKMAP_ROUTE, max_age=10.0, address=address)
    if isinstance(points, list):
        center = parse_points(points)[0]
        if len(center) >= MIN_POINTS:
            return center
    geometry = fetch_geometry(address[0], address[1], track_name, (), track_length)
    return geometry.center if geometry is not None else None
