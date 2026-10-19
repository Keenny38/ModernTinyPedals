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
Corner coach: corners of reference lap compared live, official corners of recorded track map

Reference lap (lap telemetry viewer reference, see reference_trace) is prepared once per lap file in the
background thread of reference laps: corners found on its speed (corner_analysis), each with its braking
point & minimum speed, named after official corners of circuit (track_corners). While driving,
CornerTracker follows current lap corner by corner (braking point, minimum speed) from car samples.

Official corners of the recorded track map (track map & elevation overlays) are placed in the same
background thread, once per map.
"""

from __future__ import annotations

import logging
import math
from bisect import bisect_right
from collections.abc import Sequence
from concurrent.futures import Future
from typing import NamedTuple, Protocol

from ..i18n import tr, trm
from .corner_analysis import BRAKE_ON, BRAKE_RELEASE, CornerComparison, ResampledLap, compare_corners
from .lap_cache import load_cached_lap
from .lap_geometry import map_line
from .reference_trace import ReferenceTrace, executor
from .telemetry_lap import interpolate
from .track_corners import TrackCorner, track_corners

logger = logging.getLogger(__name__)

NAME_RANGE = 200.0  # meters, official corner farther from apex of a corner found on lap does not name it
BRAKE_LOOKBACK = 200.0  # meters before reference braking point where braking for the corner is looked for
JUMP_AHEAD = 150.0  # meters, car moving farther in one update moved elsewhere (garage, reset)
JUMP_BACK = 30.0  # meters, same backward (smaller moves back are position corrections, ignored)
OUTWARD_SPAN = 25.0  # meters before & after a map corner giving the outside of its bend

Points = Sequence[tuple[float, float]] | None  # recorded track map nodes: world positions, or distances & elevations


class TrackMapData(Protocol):
    """Recorded track map (module_info.MappingInfo)"""

    @property
    def coordinates(self) -> Points: ...
    @property
    def elevations(self) -> Points: ...
    @property
    def lastModified(self) -> float: ...


# Official corner names (lap viewer & overlays)
def official_text(label: str, numbered: bool) -> str:
    """Official corner shown: "T5" ("V5" in French), or translated name"""
    return trm(f"T{label}") if numbered else tr(label)


def official_inside(official: Sequence[TrackCorner], start: float, end: float) -> list[TrackCorner]:
    """Official corners between lap distances start & end"""
    return [corner for corner in official if start <= corner.distance <= end]


def corner_name(official: Sequence[TrackCorner], numbered: bool, start: float, apex: float, end: float) -> str:
    """Corner found on a lap (start, apex & end distances) named after official corners it covers: "T5", "T5-6",
    names; nearest official corner within NAME_RANGE of apex if it covers none; "" if none"""
    if not official:
        return ""
    inside = official_inside(official, start, end)
    if not inside:
        nearest = min(official, key=lambda corner: abs(corner.distance - apex))
        if abs(nearest.distance - apex) > NAME_RANGE:
            return ""
        inside = [nearest]
    if len(inside) == 1:
        return official_text(inside[0].label, numbered)
    if numbered:
        return trm(f"T{inside[0].label}-{inside[-1].label}")
    return " / ".join(tr(corner.label) for corner in inside)


# Reference lap
class CoachCorner(NamedTuple):
    """Corner of reference lap (lap distances)"""

    label: str  # official number or name, else number of corner found on lap
    start: float  # speed peak before corner
    apex: float  # minimum speed
    end: float  # speed peak after corner
    brake: float  # reference braking point, -1 if reference lap does not brake there
    min_speed: float  # km/h, reference minimum speed


class CoachReference(NamedTuple):
    """Reference lap prepared for corner coach"""

    path: str  # lap file
    stamp: tuple[int, int]  # lap file size & modification time
    length: float  # lap length (meters)
    corners: tuple[CoachCorner, ...]  # in lap order


def track_of(meta: dict, folder: str) -> str:
    """Track name of lap: from lap info, else from track folder ("<track> - <class>")"""
    return str(meta.get("track", "")) or folder.rsplit(" - ", 1)[0]


def coach_corners(rows: Sequence[CornerComparison], official: Sequence[TrackCorner],
                  numbered: bool) -> tuple[CoachCorner, ...]:
    """Corners of reference lap (corner_analysis.compare_corners rows) named after official corners"""
    corners = []
    for row in rows:
        corner, stats = row.corner, row.reference
        label = corner_name(official, numbered, corner.start, corner.apex, corner.end) or trm(f"T{corner.number}")
        corners.append(CoachCorner(label, corner.start, corner.apex, corner.end, stats.brake_point, stats.min_speed))
    return tuple(corners)


def map_geometry(coordinates: Points, elevations: Points) -> tuple[list[float], list[float], list[float]] | None:
    """Nodes of recorded track map (minfo.mapping world positions & elevation distances) by increasing distance:
    distances, xs, ys; None without map"""
    if not coordinates or not elevations:
        return None
    nodes = sorted((float(distance), float(x), float(y)) for (distance, _), (x, y) in zip(elevations, coordinates))
    if len(nodes) < 2:
        return None
    return [node[0] for node in nodes], [node[1] for node in nodes], [node[2] for node in nodes]


def prepare_reference(filepath: str, trace: ReferenceTrace, folder: str, coordinates: Points = None,
                      elevations: Points = None) -> CoachReference:
    """Corners of reference lap with braking points & minimum speeds (background thread), raises OSError or
    ValueError

    Official corners are placed on the driving line of the lap, or on the recorded track map (coordinates &
    elevations of minfo.mapping) for a lap without positions (imported log).
    """
    data = load_cached_lap(filepath, trace.path)
    rows = compare_corners(ResampledLap(data))
    line = map_line(data)
    geometry = (line.distances, line.xs, line.ys) if line is not None else map_geometry(coordinates, elevations)
    official: list[TrackCorner] = []
    numbered = True
    if geometry is not None:
        official, numbered = track_corners(track_of(data.meta, folder), *geometry)
    return CoachReference(trace.path, trace.stamp, trace.length, coach_corners(rows, official, numbered))


class ReferenceCorners:
    """Corner coach reference prepared in background thread of reference laps, once per reference lap file

    Call poll() on each update with reference trace of ReferenceLoader.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.reference: CoachReference | None = None
        self.version = 0  # changed when reference changes
        self._job: Future | None = None
        self._job_trace: ReferenceTrace | None = None
        self._failed: ReferenceTrace | None = None  # trace not preparable (same trace not retried)

    def poll(self, trace: ReferenceTrace | None, folder: str, coordinates: Points = None,
             elevations: Points = None) -> bool:
        """Update with current reference trace, its track folder & recorded track map (see prepare_reference), True if
        reference changed"""
        reference = self.reference
        if trace is None:
            self._job = self._job_trace = None
            return self.set_reference(None)
        if reference is not None and (reference.path, reference.stamp) == (trace.path, trace.stamp):
            return False
        job = self._job
        if job is not None and self._job_trace is trace:
            if not job.done():
                return self.set_reference(None)
            self._job = None
            if not job.cancelled():  # cancelled: thread ended by an overlay closing, prepared again below
                error = job.exception()
                if error is None:
                    return self.set_reference(job.result())
                self._failed = trace
                logger.warning("CORNER COACH: unable to prepare reference lap %s: %s", trace.name, error)
        if self._failed is trace:
            return self.set_reference(None)
        self._job_trace = trace
        self._job = executor().submit(prepare_reference, self.filepath, trace, folder, coordinates, elevations)
        return self.set_reference(None)

    def set_reference(self, reference: CoachReference | None) -> bool:
        if reference is self.reference:
            return False
        self.reference = reference
        self.version += 1
        return True


# Current lap
class CornerResult(NamedTuple):
    """Minimum speed of current lap in a corner against reference lap"""

    label: str
    min_speed: float  # km/h
    reference_speed: float  # km/h


class CoachState(NamedTuple):
    """Next corner & last corner driven"""

    label: str  # next corner
    to_corner: float  # meters to apex of next corner
    to_brake: float | None  # meters to reference braking point of next corner, None if reference does not brake
    brake_gap: float | None  # meters braked later (positive) or earlier than reference, None while not braked
    last: CornerResult | None  # last corner driven


class CornerTracker:
    """Current lap driven corner by corner against reference lap corners, fed a car sample on each update

    Braking for next corner is looked for from BRAKE_LOOKBACK before reference braking point up to corner apex: last
    braking, a brake tap earlier (released over BRAKE_RELEASE before braking again) is not the corner braking point,
    as on reference lap. Minimum speed is taken between corner start & end, given once corner end is passed (corner
    entered before its apex: not after a reset in the middle of it).
    """

    def __init__(self, corners: Sequence[CoachCorner] = (), length: float = 0.0):
        self.corners: tuple[CoachCorner, ...] = ()
        self.length = 0.0
        self.last: CornerResult | None = None
        self.reset(corners, length)

    def reset(self, corners: Sequence[CoachCorner], length: float) -> None:
        """New reference corners (lap length in meters, 0 if unknown), last result forgotten"""
        self.corners = tuple(corners)
        self.length = length if length > 0 else max((corner.end for corner in self.corners), default=0.0)
        self.apexes = [corner.apex for corner in self.corners]
        self.starts = [corner.start for corner in self.corners]
        self.last = None
        self.clear()

    def clear(self) -> None:
        """Current lap driving forgotten (car moved elsewhere)"""
        self.last_distance = math.nan
        self.last_brake = 0.0
        self.next = -1  # index of next corner
        self.brake_gap: float | None = None  # braking for next corner, against reference braking point
        self.released_gap: float | None = None  # position (against reference braking point) brake was released
        self.current = -1  # corner car is in (between start & end), -1 if none
        self.current_min = math.inf
        self.current_valid = False

    def offset(self, distance: float, target: float) -> float:
        """Signed meters from target to distance, shortest way around lap (positive: distance after target)"""
        gap = distance - target
        length = self.length
        if length > 0:
            gap = (gap + length / 2) % length - length / 2
        return gap

    def next_corner(self, distance: float) -> int:
        """Index of first corner with apex after distance (first corner of next lap after last apex)"""
        index = bisect_right(self.apexes, distance)
        return index if index < len(self.apexes) else 0

    def corner_at(self, distance: float) -> int:
        """Index of corner between its start & end at distance, -1 if none"""
        index = bisect_right(self.starts, distance) - 1
        if index >= 0 and distance <= self.corners[index].end:
            return index
        return -1

    def update(self, distance: float, speed: float, brake: float) -> None:
        """Car sample: lap distance (meters), speed (km/h), brake pedal (fraction)"""
        if not self.corners or not math.isfinite(distance):
            return
        last = self.last_distance
        if math.isfinite(last):
            moved = self.offset(distance, last)
            if -JUMP_BACK < moved < 0:  # position correction: wait until car is past last position again
                return
            if not 0 <= moved < JUMP_AHEAD:  # car moved elsewhere
                self.finish(valid=False)
                self.clear()
                last = math.nan
        self.last_distance = distance
        index = self.next_corner(distance)
        if index != self.next:  # apex passed: braking for next corner looked for
            self.next = index
            self.brake_gap = self.released_gap = None
        self.follow_braking(distance, brake, last)
        self.follow_speed(distance, speed)
        self.last_brake = brake

    def follow_braking(self, distance: float, brake: float, last: float) -> None:
        """Braking point of next corner (against reference braking point)"""
        reference = self.corners[self.next].brake
        if reference < 0:
            return
        gap = self.offset(distance, reference)
        if gap < -BRAKE_LOOKBACK:
            return
        if brake >= BRAKE_ON:
            if self.brake_gap is None or (self.released_gap is not None and gap - self.released_gap > BRAKE_RELEASE):
                if math.isfinite(last) and self.last_brake < BRAKE_ON and brake > self.last_brake:
                    # Between samples where pedal crossed threshold (finer than update distance)
                    moved = self.offset(distance, last)
                    gap -= moved * (brake - BRAKE_ON) / (brake - self.last_brake)
                self.brake_gap = gap
            self.released_gap = None
        elif self.brake_gap is not None and self.released_gap is None:
            self.released_gap = gap

    def follow_speed(self, distance: float, speed: float) -> None:
        """Minimum speed of corner car is in, result once corner left"""
        inside = self.corner_at(distance)
        if inside != self.current:
            self.finish()
            self.current = inside
            self.current_min = math.inf
            self.current_valid = inside >= 0 and distance <= self.corners[inside].apex
        if inside >= 0 and math.isfinite(speed):
            self.current_min = min(self.current_min, speed)

    def finish(self, valid: bool = True) -> None:
        """Corner car was in left: result if driven from before its apex"""
        index = self.current
        self.current = -1
        if not (valid and index >= 0 and self.current_valid and math.isfinite(self.current_min)):
            return
        corner = self.corners[index]
        self.last = CornerResult(corner.label, self.current_min, corner.min_speed)

    def state(self, distance: float) -> CoachState | None:
        """Next corner & last corner driven at lap distance, None without corners or position"""
        if not self.corners or not math.isfinite(distance):
            return None
        index = self.next if self.next >= 0 else self.next_corner(distance)
        corner = self.corners[index]
        to_corner = -self.offset(distance, corner.apex)
        if to_corner < 0 and self.length > 0:  # apex of next lap more than half a lap ahead
            to_corner += self.length
        to_brake = -self.offset(distance, corner.brake) if corner.brake >= 0 else None
        return CoachState(corner.label, to_corner, to_brake, self.brake_gap, self.last)


# Official corners of recorded track map
class MapCorner(NamedTuple):
    """Official corner on recorded track map"""

    label: str  # number ("10a") or name
    distance: float  # meters from start line
    x: float  # world position
    y: float
    out_x: float  # unit vector toward outside of the bend (world axes)
    out_y: float


class MapCorners(NamedTuple):
    """Official corners of recorded track map, empty if circuit unknown"""

    corners: tuple[MapCorner, ...]
    numbered: bool  # False: corners are names

    def texts(self) -> tuple[str, ...]:
        """Corner labels on maps: "T5" ("V5" in French, not read as a car position), or translated name"""
        return tuple(official_text(corner.label, self.numbered) for corner in self.corners)


NO_MAP_CORNERS = MapCorners((), True)


def place_map_corners(track_name: str, coordinates: Sequence[tuple[float, float]],
                      elevations: Sequence[tuple[float, float]]) -> MapCorners:
    """Official corners of circuit on recorded track map: world positions & elevation distances of its nodes"""
    geometry = map_geometry(coordinates, elevations)
    if geometry is None:
        return NO_MAP_CORNERS
    distances, xs, ys = geometry
    found, numbered = track_corners(track_name, distances, xs, ys)
    corners = []
    for corner in found:
        # Bend bulges outward from chord between points before & after apex
        before, after = corner.distance - OUTWARD_SPAN, corner.distance + OUTWARD_SPAN
        mid_x = (interpolate(distances, xs, before) + interpolate(distances, xs, after)) / 2
        mid_y = (interpolate(distances, ys, before) + interpolate(distances, ys, after)) / 2
        out_x, out_y = corner.x - mid_x, corner.y - mid_y
        size = math.hypot(out_x, out_y)
        if size > 1e-6:
            out_x, out_y = out_x / size, out_y / size
        else:  # straight: placed on one side
            out_x, out_y = 0.0, -1.0
        corners.append(MapCorner(corner.label, corner.distance, corner.x, corner.y, out_x, out_y))
    return MapCorners(tuple(corners), numbered)


_map_result: tuple[tuple, MapCorners] | None = None  # map key, corners placed
_map_job: tuple[tuple, Future] | None = None  # map key, placing in background thread


def map_corners(track_name: str, mapping: TrackMapData, wait: bool = False) -> MapCorners | None:
    """Official corners of recorded track map (mapping: minfo.mapping of overlay), placed once per map in background
    thread of reference laps, shared by overlays; None while being placed (wait: placed now, for overlay pictures)"""
    global _map_result, _map_job
    coordinates, elevations = mapping.coordinates, mapping.elevations
    if not coordinates or not elevations:
        return NO_MAP_CORNERS
    key = (track_name, mapping.lastModified, len(coordinates))
    if _map_result is not None and _map_result[0] == key:
        return _map_result[1]
    if wait:
        corners = place_map_corners(track_name, coordinates, elevations)
        _map_result = (key, corners)
        return corners
    if _map_job is not None and _map_job[0] == key:
        job = _map_job[1]
        if not job.done():
            return None
        _map_job = None
        if not job.cancelled():  # cancelled: thread ended by an overlay closing, placed again below
            error = job.exception()
            if error is not None:
                logger.warning("CORNER NUMBERS: unable to place corners of %s: %s", track_name, error)
            corners = job.result() if error is None else NO_MAP_CORNERS
            _map_result = (key, corners)
            return corners
    _map_job = (key, executor().submit(place_map_corners, track_name, coordinates, elevations))
    return None
