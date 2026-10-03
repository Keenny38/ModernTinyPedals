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
Corner by corner lap comparison

Corners are found on reference lap speed: each corner is a speed minimum, between the speed
peaks before and after it (hysteresis, so small speed changes are not corners). For each lap:
minimum speed, braking point, full throttle point and time spent between the two peaks.
"""

from __future__ import annotations

from typing import NamedTuple

from .telemetry_lap import LapData, interpolate, monotonic_distance

GRID_STEP = 5.0  # meters between resampled points
SMOOTH_POINTS = 5  # moving average width (25 m), removes speed noise
SPEED_HYSTERESIS = 10.0  # km/h, speed drop & rise needed to count a corner
BRAKE_ON = 0.1  # brake pedal fraction counted as braking
FULL_THROTTLE = 0.9  # throttle pedal fraction counted as full throttle


class Corner(NamedTuple):
    """Corner of reference lap (lap distances)"""

    number: int
    start: float  # speed peak before corner
    apex: float  # minimum speed
    end: float  # speed peak after corner


class CornerStats(NamedTuple):
    """Lap driving in a corner, distances are -1 if not found"""

    min_speed: float  # km/h
    apex: float  # distance of minimum speed
    brake_point: float  # first braking before minimum speed
    throttle_point: float  # first full throttle after minimum speed
    time: float  # seconds from corner start to end


class CornerComparison(NamedTuple):
    """Corner stats of reference & compared lap (None if no compared lap)"""

    corner: Corner
    reference: CornerStats
    compared: CornerStats | None

    @property
    def time_delta(self) -> float | None:
        """Time lost (positive) or gained (negative) by compared lap"""
        return None if self.compared is None else self.compared.time - self.reference.time


def resample(lap: LapData, column: str, grid: list[float]) -> list[float] | None:
    """Column values at grid distances, None if column not recorded"""
    if column not in lap.columns or len(lap) < 2:
        return None
    distances, values = monotonic_distance(lap, column)
    if len(distances) < 2:
        return None
    return [interpolate(distances, values, distance) for distance in grid]


def smooth(values: list[float], points: int = SMOOTH_POINTS) -> list[float]:
    """Centered moving average"""
    half = points // 2
    count = len(values)
    result = []
    for index in range(count):
        window = values[max(index - half, 0):min(index + half + 1, count)]
        result.append(sum(window) / len(window))
    return result


def lap_grid(lap: LapData, step: float = GRID_STEP) -> list[float]:
    """Distances every step meters along lap"""
    if len(lap) < 2:
        return []
    length = max(lap.distance)
    return [index * step for index in range(int(length / step) + 1)]


def find_corners(lap: LapData, hysteresis: float = SPEED_HYSTERESIS) -> list[Corner]:
    """Corners of lap from its speed, in lap order"""
    grid = lap_grid(lap)
    speeds = resample(lap, "speed_kph", grid)
    if not speeds:
        return []
    speeds = smooth(speeds)
    # Speed peaks & minimums in turn, each one confirmed once speed moved hysteresis away from it.
    # A peak keeps first & last grid index of its top speed: a corner starts where top speed ends
    # (braking), the previous corner ends where top speed is reached.
    extremes: list[tuple[bool, int, int]] = []  # (is minimum, first index, last index)
    seeking_minimum = False
    first = last = 0
    for index, speed in enumerate(speeds):
        if seeking_minimum:
            if speed < speeds[first]:
                first = last = index
            elif speed > speeds[first] + hysteresis:
                extremes.append((True, first, last))
                seeking_minimum, first, last = False, index, index
        elif speed > speeds[last]:
            first = last = index
        elif speed == speeds[last]:
            last = index
        elif speed < speeds[last] - hysteresis:
            extremes.append((False, first, last))
            seeking_minimum, first, last = True, index, index
    if not seeking_minimum:
        extremes.append((False, first, last))  # last peak
    corners: list[Corner] = []
    end_index = len(grid) - 1
    for position, (is_minimum, minimum, _) in enumerate(extremes):
        if not is_minimum:
            continue
        start = extremes[position - 1][2] if position > 0 else 0
        end = extremes[position + 1][1] if position + 1 < len(extremes) else end_index
        corners.append(Corner(len(corners) + 1, grid[start], grid[minimum], grid[end]))
    return corners


def corner_stats(lap: LapData, corner: Corner) -> CornerStats | None:
    """Lap driving between corner start & end, None if lap has no speed"""
    grid = [distance for distance in lap_grid(lap) if corner.start <= distance <= corner.end]
    speeds = resample(lap, "speed_kph", grid)
    times = resample(lap, "lap_time", [corner.start, corner.end])
    if not speeds or not times:
        return None
    lowest = min(range(len(speeds)), key=speeds.__getitem__)
    brake = resample(lap, "brake", grid)
    throttle = resample(lap, "throttle", grid)
    brake_point = -1.0
    if brake:
        brake_point = next((grid[index] for index in range(lowest + 1) if brake[index] >= BRAKE_ON), -1.0)
    throttle_point = -1.0
    if throttle:
        throttle_point = next(
            (grid[index] for index in range(lowest, len(grid)) if throttle[index] >= FULL_THROTTLE), -1.0)
    return CornerStats(speeds[lowest], grid[lowest], brake_point, throttle_point, times[1] - times[0])


def compare_corners(
    reference: LapData, compared: LapData | None = None, hysteresis: float = SPEED_HYSTERESIS,
) -> list[CornerComparison]:
    """Corner stats of reference lap, and of compared lap on the same corners"""
    result = []
    for corner in find_corners(reference, hysteresis):
        ref_stats = corner_stats(reference, corner)
        if ref_stats is None:
            continue
        other = corner_stats(compared, corner) if compared is not None else None
        result.append(CornerComparison(corner, ref_stats, other))
    return result


def lap_time_delta(reference: LapData, compared: LapData) -> float:
    """Lap time difference (compared - reference)"""
    return compared.lap_time - reference.lap_time


def straights_delta(rows: list[CornerComparison], reference: LapData, compared: LapData) -> float:
    """Time lost on straights: lap delta not spent in corners (between top speed & braking)"""
    corners = sum(row.time_delta or 0.0 for row in rows)
    return lap_time_delta(reference, compared) - corners
