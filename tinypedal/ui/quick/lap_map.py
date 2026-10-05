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
Lap viewer track map geometry: driving lines, coloring modes, braking points, sector & start marks

Coordinates are game positions (meters, y up). Line widths are given in pixels and converted
with current map scale (meters per pixel): thick lines are rebuilt when map zoom settles.
"""

from __future__ import annotations

import bisect
import math
from array import array
from collections.abc import Sequence
from itertools import pairwise

from PySide6.QtGui import QColor

from ...userfile.corner_analysis import resample_sorted
from ...userfile.lap_geometry import (  # noqa: F401  (re-exported: lap_map.MapLine...)
    CAR_HALF_WIDTH,
    EVENT_GAP,
    EVENT_SAMPLES,
    GAME_MIN_COVERAGE,
    GAME_OFF_TRACK,
    LIMITS_MARGIN,
    LIMITS_MAX_OFFSET,
    LIMITS_MAX_WIDTH,
    LIMITS_MIN_LAPS,
    LIMITS_MIN_WIDTH,
    LIMITS_SMOOTH,
    LINE_SEARCH,
    OFF_ROAD_SURFACES,
    OFF_TRACK_WHEELS,
    SAME_DISTANCE,
    WIDTH_DEFAULT,
    LapOffsets,
    MapLine,
    TrackLimits,
    _filled,
    _normal,
    _smooth,
    edge_offsets,
    game_limits,
    game_limits_from_offsets,
    lateral_offsets,
    limits_at,
    limits_events,
    limits_from_offsets,
    map_line,
    map_line_indexes,
    off_track_events,
    placement,
    track_events,
    track_limits,
)
from ...userfile.telemetry_lap import LapData, compute_delta, distance_scale, interpolate
from ..lap_viewer import GAIN_FULL_SCALE, GAIN_WINDOW, gain_color
from .lines import TRIANGLE_STRIP, Vertices, band, band_part, colored_band, merge_strips, range_indexes

MAP_MODES = ("laps", "gain", "speed", "pedals", "line", "gear", "elevation", "corners", "minisectors")
SPEED_COLORS = (QColor("#3B82F6"), QColor("#22C55E"), QColor("#FACC15"), QColor("#EF4444"))  # slow to fast
ELEVATION_COLORS = (QColor("#1E40AF"), QColor("#0D9488"), QColor("#84CC16"), QColor("#EAB308"), QColor("#B45309"))
GEAR_COLORS = tuple(QColor(color) for color in (  # gear 1 to 8 (reverse & neutral grey)
    "#EF4444", "#F97316", "#FACC15", "#84CC16", "#22C55E", "#06B6D4", "#3B82F6", "#A855F7",
))
LINE_COLORS = {"inside": QColor("#3B82F6"), "outside": QColor("#F97316"), "same": QColor("#9CA3AF")}
LINE_FULL_SCALE = 3.0  # meters off reference line shown with full color (line mode)
LINE_SAME = 0.4  # meters off reference line counted as same line
PEDAL_COLORS = {
    "throttle": QColor("#22C55E"), "brake": QColor("#EF4444"), "both": QColor("#F59E0B"), "coast": QColor("#9CA3AF"),
}
BRAKE_ON = 0.1  # brake pedal fraction counted as braking
BRAKE_GAP = 60.0  # meters, braking points closer than this to previous braking end are the same braking
SLIP_RATIO = 0.12  # wheel speed this much off car speed: locked or spinning wheel
SLIP_SPEED = 40.0  # km/h, slip not checked slower
TRACKOUT_AFTER = 120.0  # meters after corner end searched for track-out point
FULL_THROTTLE = 0.9  # throttle fraction counted as full throttle
ZONE_MIN = 5.0  # meters, shorter pedal zones left out
ZONE_MERGE = 10.0  # meters, braking zones closer than this are one zone
GRID_CELL = 20.0  # meters, mouse picking grid cell
MINI_SECTOR_LENGTH = 200.0  # meters, mini-sector length (rounded to whole lap)
MINI_SECTORS_MIN = 10


def simplify(line: MapLine, min_gap: float) -> MapLine:
    """Points at least min_gap apart (meters): thick lines built from fewer points when zoomed out"""
    if min_gap <= 0 or len(line.xs) < 3:
        return line
    distances, xs, ys = [line.distances[0]], [line.xs[0]], [line.ys[0]]
    gap = min_gap * min_gap
    for distance, x, y in zip(line.distances[1:-1], line.xs[1:-1], line.ys[1:-1]):
        if (x - xs[-1]) ** 2 + (y - ys[-1]) ** 2 >= gap:
            distances.append(distance)
            xs.append(x)
            ys.append(y)
    distances.append(line.distances[-1])
    xs.append(line.xs[-1])
    ys.append(line.ys[-1])
    return MapLine(distances, xs, ys)


def part(line: MapLine, start: float, end: float) -> MapLine:
    """Line between two distances"""
    low, high = bisect.bisect_left(line.distances, start), bisect.bisect_right(line.distances, end)
    return MapLine(line.distances[low:high], line.xs[low:high], line.ys[low:high])


def point_at(line: MapLine, distance: float) -> tuple[float, float]:
    return interpolate(line.distances, line.xs, distance), interpolate(line.distances, line.ys, distance)


def heading_at(line: MapLine, distance: float, span: float = 8.0) -> float:
    """Driving direction (radians) at distance"""
    x0, y0 = point_at(line, distance - span)
    x1, y1 = point_at(line, distance + span)
    return math.atan2(y1 - y0, x1 - x0)


def line_band(line: MapLine, half_width: float, line_normals: Sequence[tuple[float, float]] | None = None) -> Vertices:
    return band(line.xs, line.ys, half_width, line_normals=line_normals)


def blend(colors: Sequence[QColor], amount: float) -> QColor:
    """Color along evenly spaced color stops, amount 0 to 1"""
    amount = min(max(amount, 0.0), 1.0) * (len(colors) - 1)
    index = min(int(amount), len(colors) - 2)
    low, high, fraction = colors[index], colors[index + 1], amount - index
    return QColor(
        round(low.red() + (high.red() - low.red()) * fraction),
        round(low.green() + (high.green() - low.green()) * fraction),
        round(low.blue() + (high.blue() - low.blue()) * fraction),
    )


def gain_colors(reference: LapData, compared: LapData, line: MapLine, window: float = GAIN_WINDOW,
                colorblind: bool = False) -> list[QColor]:
    """Compared lap line colored by time lost (red) or gained (green) against reference lap"""
    delta = compute_delta(reference, compared)
    return gain_colors_from_delta([point[0] for point in delta], [point[1] for point in delta], line,
                                  distance_scale(reference, compared), window, colorblind)


def gain_colors_from_delta(distances: Sequence[float], deltas: Sequence[float], line: MapLine, scale: float = 1.0,
                           window: float = GAIN_WINDOW, colorblind: bool = False) -> list[QColor]:
    """Compared lap line colored by time lost or gained, from its delta along reference distance

    Line distances are compared lap distances (multiplied by scale: reference distance).
    """
    if len(distances) < 2:
        return []
    half = window / 2
    along = [distance * scale for distance in line.distances]  # increasing: resampled in one pass each
    ahead = resample_sorted(distances, deltas, [distance + half for distance in along])
    behind = resample_sorted(distances, deltas, [distance - half for distance in along])
    return [gain_color((first - second) / window, colorblind) for first, second in zip(ahead, behind)]


def channel_at(lap: LapData, column: str, line: MapLine) -> list[float]:
    values = lap.columns.get(column)
    if not values:
        return []
    return [interpolate(lap.distance, values, distance) for distance in line.distances]


def speed_colors(lap: LapData, line: MapLine) -> tuple[list[QColor], float, float]:
    """Line colored by speed, slowest blue to fastest red, with speed range (km/h)"""
    speeds = channel_at(lap, "speed_kph", line)
    if not speeds:
        return [], 0.0, 0.0
    low, high = min(speeds), max(speeds)
    span = max(high - low, 1.0)
    return [blend(SPEED_COLORS, (speed - low) / span) for speed in speeds], low, high


def pedal_colors(lap: LapData, line: MapLine) -> list[QColor]:
    """Line colored by pedals: throttle green, brake red, both amber, coasting grey"""
    throttles, brakes = channel_at(lap, "throttle", line), channel_at(lap, "brake", line)
    if not throttles or not brakes:
        return []
    colors = []
    for throttle, brake in zip(throttles, brakes):
        if brake > BRAKE_ON and throttle > 0.1:
            colors.append(PEDAL_COLORS["both"])
        elif brake > BRAKE_ON:
            colors.append(PEDAL_COLORS["brake"])
        elif throttle > 0.1:
            colors.append(blend((PEDAL_COLORS["coast"], PEDAL_COLORS["throttle"]), throttle))
        else:
            colors.append(PEDAL_COLORS["coast"])
    return colors


def gear_colors(lap: LapData, line: MapLine) -> list[QColor]:
    """Line colored by gear (one color per gear)"""
    gears = lap.columns.get("gear")
    if not gears:
        return []
    neutral = QColor("#9CA3AF")
    return [
        GEAR_COLORS[gear - 1] if 1 <= (gear := round(interpolate(lap.distance, gears, distance))) <= len(GEAR_COLORS)
        else neutral
        for distance in line.distances
    ]


def elevation_colors(lap: LapData, line: MapLine) -> tuple[list[QColor], float, float]:
    """Line colored by elevation, lowest blue to highest brown, with elevation range (meters)"""
    heights = channel_at(lap, "pos_z", line)
    if not heights or max(heights) - min(heights) < 0.5:  # not recorded (zeros) or flat
        return [], 0.0, 0.0
    low, high = min(heights), max(heights)
    return [blend(ELEVATION_COLORS, (height - low) / (high - low)) for height in heights], low, high


def line_offsets(reference: MapLine, compared: MapLine) -> list[float]:
    """Distance of each compared line point to reference line: positive toward corner inside

    Inside or outside from the reference line turning direction (straights: side has no meaning,
    offset kept unsigned positive).
    """
    sides, indexes = lateral_offsets(reference, compared)
    offsets = []
    for side, nearest in zip(sides, indexes):
        turn = turning(reference, nearest)
        if abs(turn) < 0.002:  # straight
            offsets.append(abs(side) if abs(side) >= LINE_SAME else 0.0)
        else:
            offsets.append(side if turn > 0 else -side)
    return offsets


def turning(line: MapLine, index: int, span: int = 6) -> float:
    """Heading change per meter around point (left positive), 0 at line ends"""
    before, after = index - span, index + span
    if before < 1 or after >= len(line.xs) - 1:
        return 0.0
    first = math.atan2(line.ys[index] - line.ys[before], line.xs[index] - line.xs[before])
    second = math.atan2(line.ys[after] - line.ys[index], line.xs[after] - line.xs[index])
    change = (second - first + math.pi) % math.tau - math.pi
    meters = max((line.distances[after] - line.distances[before]) / 2, 1.0)  # between segment middles
    return change / meters


def line_colors(offsets: list[float]) -> list[QColor]:
    """Line mode colors: blue inside of reference line, orange outside, grey on same line"""
    neutral = LINE_COLORS["same"]
    colors = []
    for offset in offsets:
        amount = 0.0 if abs(offset) < LINE_SAME else min((abs(offset) - LINE_SAME) / LINE_FULL_SCALE, 1.0)
        target = LINE_COLORS["inside"] if offset > 0 else LINE_COLORS["outside"]
        colors.append(QColor(
            round(neutral.red() + (target.red() - neutral.red()) * amount),
            round(neutral.green() + (target.green() - neutral.green()) * amount),
            round(neutral.blue() + (target.blue() - neutral.blue()) * amount),
        ))
    return colors


def direction_marks(line: MapLine, count: int = 14) -> list[tuple[float, float, float]]:
    """Driving direction arrows evenly along line: x, y, heading (degrees, screen y down)"""
    if len(line.distances) < 3:
        return []
    start, end = line.distances[0], line.distances[-1]
    step = (end - start) / count
    marks = []
    for index in range(count):
        distance = start + step * (index + 0.5)
        x, y = point_at(line, distance)
        marks.append((x, y, math.degrees(heading_at(line, distance))))
    return marks


def colored_line(line: MapLine, colors: list[QColor], half_width: float) -> Vertices:
    return colored_band(line.xs, line.ys, colors, half_width)


def braking_points(lap: LapData) -> list[float]:
    """Distances where braking starts (brake pressed after a while off it)"""
    brakes = lap.columns.get("brake")
    if not brakes:
        return []
    points: list[float] = []
    last_on = -math.inf
    braking = False
    for distance, brake in zip(lap.distance, brakes):
        if brake > BRAKE_ON:
            if not braking and distance - last_on > BRAKE_GAP:
                points.append(distance)
            braking = True
            last_on = distance
        else:
            braking = False
    return points


def slip_events(lap: LapData) -> list[tuple[float, str]]:
    """Distances where front wheels lock under braking ("lock") or rear wheels spin on throttle ("spin")

    Wheel slip from wheel speed against car speed, one event per slip episode.
    """
    columns = lap.columns
    needed = ("speed_kph", "brake", "throttle", *(f"wheel_speed_{wheel}" for wheel in ("fl", "fr", "rl", "rr")))
    if not all(column in columns for column in needed):
        return []
    events: list[tuple[float, str]] = []
    last = {"lock": -math.inf, "spin": -math.inf}
    active = {"lock": False, "spin": False}
    for index, distance in enumerate(lap.distance):
        speed = columns["speed_kph"][index]
        if speed < SLIP_SPEED:
            active = {"lock": False, "spin": False}
            continue
        front = min(columns["wheel_speed_fl"][index], columns["wheel_speed_fr"][index])
        rear = max(columns["wheel_speed_rl"][index], columns["wheel_speed_rr"][index])
        if not rear and not max(columns["wheel_speed_fl"][index], columns["wheel_speed_fr"][index]):
            continue  # every wheel at 0 while moving: wheel speed not recorded
        states = {
            "lock": columns["brake"][index] > BRAKE_ON and (front - speed) / speed < -SLIP_RATIO,
            "spin": columns["throttle"][index] > 0.3 and (rear - speed) / speed > SLIP_RATIO,
        }
        for kind, slipping in states.items():
            if slipping and not active[kind] and distance - last[kind] > BRAKE_GAP:
                events.append((distance, kind))
            if slipping:
                last[kind] = distance
            active[kind] = slipping
    return events


def rotate_line(line: MapLine, angle: float) -> MapLine:
    """Driving line turned around origin (radians, counterclockwise)"""
    if not angle:
        return line
    cos, sin = math.cos(angle), math.sin(angle)
    return MapLine(line.distances, [x * cos - y * sin for x, y in zip(line.xs, line.ys)],
                   [x * sin + y * cos for x, y in zip(line.xs, line.ys)])


def principal_angle(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Direction of longest extent of points (radians), 0 if too few points"""
    count = len(xs)
    if count < 3:
        return 0.0
    mean_x, mean_y = sum(xs) / count, sum(ys) / count
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return 0.5 * math.atan2(2 * sxy, sxx - syy)


def cross_mark(line: MapLine, distance: float, half_length: float) -> tuple[float, float, float, float]:
    """Line across driving direction at distance: x0, y0, x1, y1"""
    x, y = point_at(line, distance)
    angle = heading_at(line, distance) + math.pi / 2
    dx, dy = math.cos(angle) * half_length, math.sin(angle) * half_length
    return x - dx, y - dy, x + dx, y + dy


# Track limits: from the spread of every recorded lap of the circuit


def geometry_line(points: Sequence[tuple[float, float, float]], start: tuple[float, float] | None = None,
                  length: float = 0.0) -> MapLine:
    """Official track center path as closed line from point nearest to lap start, distances scaled to lap length

    Lap distance (game) & center path length differ slightly: scaled distances keep lap & path aligned.
    """
    if len(points) < 3:
        return MapLine([], [], [])
    first = 0
    if start is not None:
        first = min(range(len(points)), key=lambda index: (points[index][0] - start[0]) ** 2
                    + (points[index][1] - start[1]) ** 2)
    ordered = list(points[first:]) + list(points[:first + 1])  # closed: back to first point
    xs = [point[0] for point in ordered]
    ys = [point[1] for point in ordered]
    distances = [0.0]
    for index in range(1, len(xs)):
        distances.append(distances[-1] + max(math.hypot(xs[index] - xs[index - 1], ys[index] - ys[index - 1]), 1e-3))
    if length > 0 and distances[-1] > 0:
        scale = length / distances[-1]
        distances = [distance * scale for distance in distances]
    return MapLine(distances, xs, ys)


def mini_sector_bounds(length: float) -> list[float]:
    """Mini-sector start distances (equal length, about MINI_SECTOR_LENGTH each) and lap end"""
    count = max(MINI_SECTORS_MIN, round(length / MINI_SECTOR_LENGTH))
    return [length * index / count for index in range(count + 1)]


def mini_sector_times(bounds: Sequence[float], distances: Sequence[float], times: Sequence[float]) -> list[float]:
    """Time taken in each mini-sector (lap distances & lap times, same distance scale as bounds)"""
    if len(distances) < 2:
        return []
    distances, times = list(distances), list(times)  # copied once, not for each bound
    at = [interpolate(distances, times, bound) for bound in bounds]
    return [second - first for first, second in pairwise(at)]


def mini_sector_winners(times_by_lap: Sequence[Sequence[float]]) -> list[int]:
    """Index of fastest lap in each mini-sector (-1 if no lap has a time there)"""
    count = max((len(times) for times in times_by_lap), default=0)
    winners = []
    for index in range(count):
        best, winner = math.inf, -1
        for lap, times in enumerate(times_by_lap):
            if index < len(times) and 0 < times[index] < best:
                best, winner = times[index], lap
        winners.append(winner)
    return winners


def limits_band(limits: TrackLimits, keep: list[int]) -> Vertices:
    """Road between track edges as triangle strip, points kept (simplified for map scale)"""
    data = array("f")
    for index in keep:
        data.extend((limits.left.xs[index], limits.left.ys[index], limits.right.xs[index], limits.right.ys[index]))
    return Vertices(data, len(keep) * 2 if len(keep) > 1 else 0, TRIANGLE_STRIP)


def kept_indexes(line: MapLine, min_gap: float) -> list[int]:
    """Point indexes at least min_gap apart (same simplification as simplify)"""
    if len(line.xs) < 3 or min_gap <= 0:
        return list(range(len(line.xs)))
    kept = [0]
    gap = min_gap * min_gap
    for index in range(1, len(line.xs) - 1):
        last = kept[-1]
        if (line.xs[index] - line.xs[last]) ** 2 + (line.ys[index] - line.ys[last]) ** 2 >= gap:
            kept.append(index)
    kept.append(len(line.xs) - 1)
    return kept


def trackout_point(reference: MapLine, lap_line: MapLine, limits_offsets: tuple[list[float], list[float]],
                   apex: float, end: float, turn: float) -> float:
    """Distance where lap comes closest to corner outside edge after apex, -1 if not found

    limits_offsets: left & right edge offsets at each reference point. Outside is the right edge in a
    left turn (turn > 0), the left edge in a right turn.
    """
    lefts, rights = limits_offsets
    if not lefts:
        return -1.0
    window = part(lap_line, apex, end + TRACKOUT_AFTER)
    if len(window.xs) < 3:
        return -1.0
    sides, indexes = lateral_offsets(reference, window)
    best, found = math.inf, -1.0
    for distance, side, index in zip(window.distances, sides, indexes):
        room = side - rights[index] if turn > 0 else lefts[index] - side
        if room < best:
            best, found = room, distance
    return found


def trackout_from_offsets(distances: Sequence[float], sides: Sequence[float], indexes: Sequence[int],
                          edges: tuple[Sequence[float], Sequence[float]], apex: float, end: float, turn: float) -> float:
    """Same as trackout_point from lap placement already measured (offsets from base line & nearest base point,
    edge offsets along base line): no line search again, -1 if not found"""
    lefts, rights = edges
    if not lefts:
        return -1.0
    first = bisect.bisect_left(distances, apex)
    last = bisect.bisect_right(distances, end + TRACKOUT_AFTER, lo=first)
    last = min(last, len(sides))
    if last - first < 3:
        return -1.0
    best, found = math.inf, -1.0
    for position in range(first, last):
        index = indexes[position]
        room = sides[position] - rights[index] if turn > 0 else lefts[index] - sides[position]
        if room < best:
            best, found = room, distances[position]
    return found


# Pedal zones
def pedal_zones(lap: LapData) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Braking zones & throttle application zones (pedal rising to full) of lap: (start, end) distances"""
    columns = lap.columns
    brakes, throttles = columns.get("brake"), columns.get("throttle")
    braking: list[tuple[float, float]] = []
    applying: list[tuple[float, float]] = []
    if not brakes or not throttles:
        return braking, applying
    brake_start = apply_start = None
    last = -math.inf
    for distance, brake, throttle in zip(lap.distance, brakes, throttles):
        if distance <= last:
            continue
        last = distance
        if brake > BRAKE_ON:
            if brake_start is None:
                if braking and distance - braking[-1][1] <= ZONE_MERGE:  # short release: same braking
                    brake_start = braking.pop()[0]
                else:
                    brake_start = distance
            brake_end = distance
        elif brake_start is not None:
            if brake_end - brake_start >= ZONE_MIN:
                braking.append((brake_start, brake_end))
            brake_start = None
        if apply_start is None and 0.1 < throttle < FULL_THROTTLE and brake <= BRAKE_ON:
            apply_start = distance
        elif apply_start is not None:
            if throttle >= FULL_THROTTLE:
                if distance - apply_start >= ZONE_MIN:
                    applying.append((apply_start, distance))
                apply_start = None
            elif throttle <= 0.1 or brake > BRAKE_ON:  # lifted again: not an application
                apply_start = None
    if brake_start is not None and brake_end - brake_start >= ZONE_MIN:
        braking.append((brake_start, brake_end))
    return braking, applying


def zones_band(line: MapLine, zones: Sequence[tuple[float, float]], half_width: float,
               line_normals: Sequence[tuple[float, float]] | None = None) -> Vertices:
    """Thick line along each zone, one buffer (normals of whole line reused if given)"""
    strips = []
    for start, end in zones:
        indexes = range_indexes(line.distances, start, end)
        if line_normals is not None:
            strips.append(band_part(line.xs, line.ys, line_normals, indexes, half_width))
        else:
            strips.append(line_band(part(line, start, end), half_width))
    return merge_strips([strip for strip in strips if strip.vertex_count >= 3])


# Corner delta mode
def corner_delta_colors(line: MapLine, corners: Sequence[tuple[float, float, float]],
                        colorblind: bool = False) -> list[QColor]:
    """Reference line colored corner by corner: (start, end, time delta) each, straights neutral

    Largest corner delta shown with full color.
    """
    scale = max((abs(delta) for _, _, delta in corners), default=0.0)
    neutral = QColor("#6B7280")
    colors = []
    for distance in line.distances:
        color = neutral
        for start, end, delta in corners:
            if start <= distance <= end and scale > 0:
                color = gain_color(delta / scale * GAIN_FULL_SCALE, colorblind)
                break
        colors.append(color)
    return colors


# Mouse picking
class LineGrid:
    """Points of a line by grid cell: nearest point to mouse without scanning the whole line"""

    def __init__(self, line: MapLine, cell: float = GRID_CELL):
        self.line = line
        self.cell = cell
        self.cells: dict[tuple[int, int], list[int]] = {}
        for index, (x, y) in enumerate(zip(line.xs, line.ys)):
            self.cells.setdefault((int(x // cell), int(y // cell)), []).append(index)

    def nearest(self, x: float, y: float, radius: float) -> int:
        """Index of nearest point within radius, -1 if none"""
        reach = int(radius // self.cell) + 1
        column, row = int(x // self.cell), int(y // self.cell)
        best, found = radius * radius, -1
        xs, ys = self.line.xs, self.line.ys
        for cell_x in range(column - reach, column + reach + 1):
            for cell_y in range(row - reach, row + reach + 1):
                for index in self.cells.get((cell_x, cell_y), ()):
                    gap = (xs[index] - x) ** 2 + (ys[index] - y) ** 2
                    if gap < best:
                        best, found = gap, index
        return found


    def project(self, x: float, y: float, radius: float) -> float:
        """Distance of point projected on line next to nearest point (between samples), -1 if none near"""
        index = self.nearest(x, y, radius)
        if index < 0:
            return -1.0
        line = self.line
        best, found = math.inf, line.distances[index]
        for first in (index - 1, index):
            second = first + 1
            if first < 0 or second >= len(line.xs):
                continue
            dx, dy = line.xs[second] - line.xs[first], line.ys[second] - line.ys[first]
            length = dx * dx + dy * dy
            fraction = 0.0 if length <= 0 else min(max(((x - line.xs[first]) * dx + (y - line.ys[first]) * dy) / length, 0.0), 1.0)
            px, py = line.xs[first] + dx * fraction, line.ys[first] + dy * fraction
            gap = (px - x) ** 2 + (py - y) ** 2
            if gap < best:
                best = gap
                found = line.distances[first] + (line.distances[second] - line.distances[first]) * fraction
        return found


def distance_ticks(line: MapLine) -> list[tuple[float, float, float]]:
    """Distance marks along line: x, y, distance (every 500 m, every km on long laps)"""
    if len(line.distances) < 2:
        return []
    step = 1000.0 if line.distances[-1] > 8000 else 500.0
    ticks = []
    distance = step
    while distance < line.distances[-1] - step * 0.3:
        x, y = point_at(line, distance)
        ticks.append((x, y, distance))
        distance += step
    return ticks


def visible_range(line: MapLine, view: tuple[float, float, float, float], center: tuple[float, float],
                  grid: LineGrid) -> tuple[float, float] | None:
    """Part of line shown in map view around its point nearest to view center: start & end distances

    Map view (x0, y0, x1, y1) may show several parts of the circuit (straights side by side): the part
    under the view center is taken, followed both ways while inside view.
    """
    x0, y0, x1, y1 = view
    xs, ys = line.xs, line.ys

    def inside(index: int) -> bool:
        return x0 <= xs[index] <= x1 and y0 <= ys[index] <= y1

    middle = grid.nearest(center[0], center[1], max(x1 - x0, y1 - y0))
    if middle < 0 or not inside(middle):  # view center off track: longest part of line shown
        best, middle, run_start = 0.0, -1, -1
        for index in range(len(xs) + 1):
            if index < len(xs) and inside(index):
                if run_start < 0:
                    run_start = index
            elif run_start >= 0:
                length = line.distances[index - 1] - line.distances[run_start]
                if length > best:
                    best, middle = length, (run_start + index - 1) // 2
                run_start = -1
        if middle < 0:
            return None
    first = last = middle
    while first > 0 and inside(first - 1):
        first -= 1
    while last < len(xs) - 1 and inside(last + 1):
        last += 1
    return line.distances[first], line.distances[last]


# Cursor trail
def trail(line: MapLine, start: float, end: float) -> tuple[list[float], list[float], list[float]]:
    """Points of line between distances (end point included) with alpha fading in toward end"""
    if end <= start or len(line.xs) < 2:
        return [], [], []
    inside = part(line, start, end)
    xs, ys = list(inside.xs), list(inside.ys)
    distances = list(inside.distances)
    for distance in (start, end):
        x, y = point_at(line, distance)
        if distance == start:
            xs.insert(0, x)
            ys.insert(0, y)
            distances.insert(0, distance)
        else:
            xs.append(x)
            ys.append(y)
            distances.append(distance)
    span = max(end - start, 1e-6)
    return xs, ys, [((distance - start) / span) ** 1.5 for distance in distances]
