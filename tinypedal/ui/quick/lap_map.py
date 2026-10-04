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
from collections.abc import Sequence
from typing import NamedTuple

from PySide6.QtGui import QColor

from ...userfile.telemetry_lap import LapData, compute_delta, interpolate
from ..lap_viewer import GAIN_WINDOW, gain_color, lap_positions
from .lines import Vertices, band, colored_band

MAP_MODES = ("laps", "gain", "speed", "pedals", "line", "gear", "elevation")
SPEED_COLORS = (QColor("#3B82F6"), QColor("#22C55E"), QColor("#FACC15"), QColor("#EF4444"))  # slow to fast
ELEVATION_COLORS = (QColor("#1E40AF"), QColor("#0D9488"), QColor("#84CC16"), QColor("#EAB308"), QColor("#B45309"))
GEAR_COLORS = tuple(QColor(color) for color in (  # gear 1 to 8 (reverse & neutral grey)
    "#EF4444", "#F97316", "#FACC15", "#84CC16", "#22C55E", "#06B6D4", "#3B82F6", "#A855F7",
))
LINE_COLORS = {"inside": QColor("#3B82F6"), "outside": QColor("#F97316"), "same": QColor("#9CA3AF")}
LINE_FULL_SCALE = 3.0  # meters off reference line shown with full color (line mode)
LINE_SAME = 0.4  # meters off reference line counted as same line
LINE_SEARCH = 60.0  # meters of reference line searched around same distance for nearest point
PEDAL_COLORS = {
    "throttle": QColor("#22C55E"), "brake": QColor("#EF4444"), "both": QColor("#F59E0B"), "coast": QColor("#9CA3AF"),
}
BRAKE_ON = 0.1  # brake pedal fraction counted as braking
BRAKE_GAP = 60.0  # meters, braking points closer than this to previous braking end are the same braking
SLIP_RATIO = 0.12  # wheel speed this much off car speed: locked or spinning wheel
SLIP_SPEED = 40.0  # km/h, slip not checked slower


class MapLine(NamedTuple):
    """Driving line of a lap: positions by increasing distance"""

    distances: list[float]
    xs: list[float]
    ys: list[float]


def map_line(lap: LapData) -> MapLine | None:
    """Positions by strictly increasing distance (bisect & interpolate need sorted distances)"""
    distances: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    last = -math.inf
    for distance, x, y in lap_positions(lap):
        if distance > last:
            distances.append(distance)
            xs.append(x)
            ys.append(y)
            last = distance
    if len(distances) < 2:
        return None
    return MapLine(distances, xs, ys)


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


def line_band(line: MapLine, half_width: float) -> Vertices:
    return band(line.xs, line.ys, half_width)


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


def gain_colors(reference: LapData, compared: LapData, line: MapLine, window: float = GAIN_WINDOW) -> list[QColor]:
    """Compared lap line colored by time lost (red) or gained (green) against reference lap"""
    delta = compute_delta(reference, compared)
    if len(delta) < 2:
        return []
    distances = [point[0] for point in delta]
    deltas = [point[1] for point in delta]
    half = window / 2
    return [
        gain_color((interpolate(distances, deltas, distance + half)
                    - interpolate(distances, deltas, distance - half)) / window)
        for distance in line.distances
    ]


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

    Nearest reference point searched around the same lap distance. Inside or outside from the
    reference line turning direction (straights: side has no meaning, offset kept unsigned positive).
    """
    count = len(reference.xs)
    if count < 3:
        return []
    offsets = []
    for distance, x, y in zip(compared.distances, compared.xs, compared.ys):
        low = max(bisect.bisect_left(reference.distances, distance - LINE_SEARCH), 1)
        high = min(bisect.bisect_right(reference.distances, distance + LINE_SEARCH), count - 1)
        if low >= high:
            offsets.append(0.0)
            continue
        nearest = min(range(low, high), key=lambda index: (reference.xs[index] - x) ** 2 + (reference.ys[index] - y) ** 2)
        before, after = nearest - 1, nearest + 1
        hx, hy = reference.xs[after] - reference.xs[before], reference.ys[after] - reference.ys[before]
        length = math.hypot(hx, hy) or 1.0
        side = (hx * (y - reference.ys[nearest]) - hy * (x - reference.xs[nearest])) / length  # left positive
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
