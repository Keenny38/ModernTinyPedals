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
Lap distance origin of laps not recorded by the app (imported logs) aligned on a reference lap

The app records game lap distance (zero at the start line). An imported log may put its zero meters away from
the line (lap number channel changing late, odometer distance rebased at another place, other logger): the whole
lap is then shifted along the distance axis. The constant offset is measured on the reference lap, from world
positions when both laps have them (exact), else from the speed trace along distance, and only kept when it
clearly matches better than no shift.

An aligned lap is the lap turned around its start line: samples past the line once shifted belong to the other
end of the lap (lap driven from line to line, next lap starting like this one). Lap time follows (lap time at the
line is 0, lap time stays the official lap time): delta, sectors & corners of the aligned lap are those of the
lap driven from the real line.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .corner_analysis import resample_sorted
from .telemetry_lap import (
    LAP_END_METERS,
    LapData,
    interpolate,
    lap_end_distance,
    lap_length,
    lap_time_curve,
    monotonic_distance,
    official_lap_time,
    pack_columns,
)

SEARCH_METERS = 150.0  # offsets searched up to this far, or SEARCH_SHARE of track length if longer
SEARCH_SHARE = 0.05
COARSE_STEP = 4.0  # meters, speed matched on this grid first, then every FINE_STEP around best coarse offset
FINE_STEP = 1.0
COARSE_POINTS = 1500  # at most this many grid points in first search (long track: coarser grid)
MIN_OFFSET = 2.0  # meters, smaller offsets (measurement noise) never applied
SPEED_MIN_GAIN = 1.0  # km/h, RMS speed difference reduced at least this much by the offset...
SPEED_MAX_RATIO = 0.5  # ...and to at most this share of the difference without offset (squared)
POSITION_STEP = 2.0  # meters between reference line points
POSITION_CELL = 20.0  # meters, grid cell of reference line points (nearest point search)
POSITION_SAMPLE = 10.0  # meters between compared lap points matched on reference line
POSITION_MATCH = 12.0  # meters, compared point on reference line if this close to it
POSITION_MIN_SHARE = 0.8  # share of compared points on reference line (same circuit & coordinates)
POSITION_SPREAD = 10.0  # meters, offsets of most points this close to their median (one offset all along)
OFFSET_INFO = "distance_offset"  # lap info: meters added to lap distances (aligned lap)


def is_recorded(lap: LapData) -> bool:
    """Whether lap was recorded by the app (game lap distance from the start line)"""
    return "combo" in lap.meta


def search_window(length: float) -> float:
    """Largest offset searched (meters) on a lap of length"""
    return max(SEARCH_METERS, SEARCH_SHARE * length)


def wrapped(offset: float, length: float) -> float:
    """Offset brought between -length / 2 and length / 2 (lap distance turns around at the line)"""
    return (offset + length / 2) % length - length / 2


def column_on_grid(lap: LapData, column: str, grid: Sequence[float], scale: float = 1.0) -> list[float]:
    """Column along lap distance (multiplied by scale) resampled at grid distances"""
    distances, values = monotonic_distance(lap, column)
    if scale != 1.0:
        distances = [distance * scale for distance in distances]
    return resample_sorted(distances, values, grid)


def has_positions(lap: LapData) -> bool:
    columns = lap.columns
    return all(len(columns.get(name) or ()) == len(lap) and max(columns[name]) > min(columns[name])
               for name in ("pos_x", "pos_z")) if len(lap) >= 2 else False


def projected(grid: Sequence[float], xs: Sequence[float], zs: Sequence[float], index: int, x: float, z: float
              ) -> float:
    """Reference distance of point projected on reference line next to its nearest line point (index)"""
    best_gap, best = math.inf, grid[index]
    for low in (index - 1, index):
        high = low + 1
        if low < 0 or high >= len(grid):
            continue
        dx, dz = xs[high] - xs[low], zs[high] - zs[low]
        span = dx * dx + dz * dz
        share = min(max(((x - xs[low]) * dx + (z - zs[low]) * dz) / span, 0.0), 1.0) if span > 0 else 0.0
        gap = (xs[low] + dx * share - x) ** 2 + (zs[low] + dz * share - z) ** 2
        if gap < best_gap:
            best_gap, best = gap, grid[low] + (grid[high] - grid[low]) * share
    return best


def position_offset(reference: LapData, compare: LapData, scale: float, length: float) -> float | None:
    """Offset (reference meters) from world positions: median of reference distance of nearest reference line
    point minus compared lap distance, None if positions do not match (other coordinates, not the same circuit)"""
    if not has_positions(reference) or not has_positions(compare):
        return None
    grid = [index * POSITION_STEP for index in range(int(length / POSITION_STEP) + 1)]
    xs, zs = column_on_grid(reference, "pos_x", grid), column_on_grid(reference, "pos_z", grid)
    cells: dict[tuple[int, int], list[int]] = {}
    for index, (x, z) in enumerate(zip(xs, zs)):
        cells.setdefault((math.floor(x / POSITION_CELL), math.floor(z / POSITION_CELL)), []).append(index)
    compare_end = lap_end_distance(compare) * scale
    points = [index * POSITION_SAMPLE for index in range(int(compare_end / POSITION_SAMPLE) + 1)]
    if len(points) < 10:
        return None
    own = [point / scale for point in points]
    cxs, czs = column_on_grid(compare, "pos_x", own), column_on_grid(compare, "pos_z", own)
    offsets = []
    for point, x, z in zip(points, cxs, czs):
        cell_x, cell_z = math.floor(x / POSITION_CELL), math.floor(z / POSITION_CELL)
        best, nearest = POSITION_MATCH ** 2, -1
        for near_x in (cell_x - 1, cell_x, cell_x + 1):
            for near_z in (cell_z - 1, cell_z, cell_z + 1):
                for index in cells.get((near_x, near_z), ()):
                    gap = (xs[index] - x) ** 2 + (zs[index] - z) ** 2
                    if gap < best:
                        best, nearest = gap, index
        if nearest >= 0:
            offsets.append(wrapped(projected(grid, xs, zs, nearest, x, z) - point, length))
    if len(offsets) < POSITION_MIN_SHARE * len(points):
        return None
    offsets.sort()
    median = offsets[len(offsets) // 2]
    close = sum(abs(offset - median) <= POSITION_SPREAD for offset in offsets)
    return median if close >= POSITION_MIN_SHARE * len(offsets) else None


def mean_square(values: Sequence[float], others: Sequence[float]) -> float:
    return sum((a - b) * (a - b) for a, b in zip(values, others)) / max(len(values), 1)


def speed_errors(reference: Sequence[float], compare: Sequence[float], shifts: range) -> dict[int, float]:
    """Mean squared speed difference of compared lap moved by each shift (grid steps) along periodic reference"""
    count = len(reference)
    errors = {}
    for shift in shifts:
        start = shift % count
        errors[shift] = mean_square(compare, reference[start:] + reference[:start])
    return errors


def speed_offset(reference: LapData, compare: LapData, scale: float, length: float) -> float:
    """Offset (reference meters) best matching speed along distance, 0 unless clearly better than no offset"""
    if "speed_kph" not in reference.columns or "speed_kph" not in compare.columns:
        return 0.0
    window = search_window(length)
    coarse = max(COARSE_STEP, length / COARSE_POINTS)  # long track: coarser first search (same cost)
    passes = [(coarse, window), (COARSE_STEP, 2 * coarse), (FINE_STEP, 2 * COARSE_STEP)]
    if coarse == COARSE_STEP:
        del passes[1]
    found = 0.0
    for step, around in passes:
        grid = [index * step for index in range(int(length / step))]
        if len(grid) < 10:
            return 0.0
        ref = column_on_grid(reference, "speed_kph", grid)
        own = column_on_grid(compare, "speed_kph", grid, scale)
        own_mean = sum(own) / len(own)
        if own_mean > 0:  # faster or slower lap: same mean speed, trace shape matched
            pace = sum(ref) / len(ref) / own_mean
            own = [value * pace for value in own]
        center = round(found / step)
        reach = int(around / step)
        errors = speed_errors(ref, own, range(center - reach, center + reach + 1))
        best = min(errors, key=errors.__getitem__)
        found = best * step
    unshifted = mean_square(own, ref)
    shifted = errors[best]
    if (abs(found) < MIN_OFFSET or shifted > SPEED_MAX_RATIO * unshifted
            or math.sqrt(unshifted) - math.sqrt(shifted) < SPEED_MIN_GAIN):
        return 0.0
    return float(found)


def is_complete(lap: LapData) -> bool:
    """Whether lap goes from line to line with its lap time (can be turned around its line)"""
    if "lap_time" not in lap.columns or len(lap) < 10 or official_lap_time(lap) <= 0:
        return False
    distances = lap_time_curve(lap)[0]
    if len(distances) < 10 or distances[0] != 0:
        return False
    recorded = lap_length(lap)
    return not recorded or abs(distances[-1] - recorded) <= LAP_END_METERS


def lap_offset(reference: LapData, compare: LapData, scale: float = 1.0) -> float:
    """Meters (reference lap distance) to add to compared lap distances (multiplied by scale) so it lines up with
    reference lap, 0 if lap recorded by the app, not a complete lap or no clear offset"""
    if is_recorded(compare) or not is_complete(compare) or len(reference) < 10:
        return 0.0
    length = lap_end_distance(reference)
    if length <= 0:
        return 0.0
    offset = position_offset(reference, compare, scale, length)
    if offset is None:
        offset = speed_offset(reference, compare, scale, length)
    return offset if abs(offset) >= MIN_OFFSET else 0.0


def shifted_lap(lap: LapData, offset: float) -> LapData:
    """Lap with offset meters (own lap distance) added to its distances, turned around its line: samples moved past
    lap end (or before lap start) taken to the other end, lap time from the shifted line (official lap time kept)"""
    curve_distances, curve_times = lap_time_curve(lap)
    length = curve_distances[-1]
    offset = wrapped(offset, length)
    if not offset or length <= 0:
        return lap
    lap_time = curve_times[-1] or official_lap_time(lap)
    line = length - offset if offset > 0 else -offset  # own distance where shifted lap starts
    line_time = interpolate(curve_distances, curve_times, line)
    distances = lap.distance
    split = next((index for index, distance in enumerate(distances) if distance >= line), len(distances))
    head_shift = offset - length if offset > 0 else offset  # samples after split start the shifted lap
    tail_shift = offset if offset > 0 else offset + length
    columns = {}
    for name, values in lap.columns.items():
        head, tail = values[split:], values[:split]
        if name == "distance":
            head = [value + head_shift for value in head]
            tail = [value + tail_shift for value in tail]
        elif name in ("lap_time", "time"):
            head = [value - line_time for value in head]
            tail = [value + lap_time - line_time for value in tail]
        columns[name] = [*head, *tail]
    info = dict(lap.meta)
    info[OFFSET_INFO] = round(offset + float(info.get(OFFSET_INFO, 0.0) or 0.0), 3)
    return LapData(lap.name, pack_columns(columns), info)


def aligned_lap(reference: LapData, compare: LapData, scale: float = 1.0) -> tuple[LapData, float]:
    """Compared lap aligned on reference lap & offset applied (reference meters), lap itself & 0 if not shifted"""
    offset = lap_offset(reference, compare, scale)
    if not offset:
        return compare, 0.0
    shifted = shifted_lap(compare, offset / scale)
    return (shifted, offset) if shifted is not compare else (compare, 0.0)
