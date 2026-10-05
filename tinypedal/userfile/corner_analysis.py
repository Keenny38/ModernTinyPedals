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

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from itertools import pairwise
from typing import NamedTuple

from .telemetry_lap import LapData, interpolate, monotonic_distance, official_lap_time

GRID_STEP = 5.0  # meters between resampled points
SMOOTH_POINTS = 5  # moving average width (25 m), removes speed noise
SPEED_HYSTERESIS = 10.0  # km/h, speed drop & rise needed to count a corner
BRAKE_ON = 0.1  # brake pedal fraction counted as braking
FULL_THROTTLE = 0.9  # throttle pedal fraction counted as full throttle
PEDAL_OFF = 0.05  # pedal fraction counted as released (coasting)
PEDAL_ON = 0.1  # pedal fraction counted as pressed (overlap)
STEERING_ON = 0.05  # steering fraction counted as turning (trail braking)
BRAKE_RELEASE = 15.0  # meters off brake ending a braking (earlier taps are not the corner braking point)


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
    trail_braking: float = 0.0  # seconds braking while turning
    coasting: float = 0.0  # seconds with no pedal pressed
    overlap: float = 0.0  # seconds with throttle & brake pressed together
    entry_speed: float = 0.0  # km/h at corner start (top speed before braking)
    exit_speed: float = 0.0  # km/h at corner end
    apex_gear: int = 0  # gear at minimum speed, 0 if not recorded
    peak_brake: float = 0.0  # highest brake pedal fraction


class CornerComparison(NamedTuple):
    """Corner stats of reference & compared lap (None if no compared lap)"""

    corner: Corner
    reference: CornerStats
    compared: CornerStats | None

    @property
    def time_delta(self) -> float | None:
        """Time lost (positive) or gained (negative) by compared lap"""
        return None if self.compared is None else self.compared.time - self.reference.time


def resample(lap: LapData, column: str, grid: list[float], scale: float = 1.0) -> list[float] | None:
    """Column values at grid distances (ascending, lap distances multiplied by scale), None if column not recorded"""
    if column not in lap.columns or len(lap) < 2:
        return None
    distances, values = monotonic_distance(lap, column)
    if len(distances) < 2:
        return None
    if scale != 1.0:
        distances = [distance * scale for distance in distances]
    return resample_sorted(distances, values, grid)


def resample_sorted(distances: Sequence[float], values: Sequence[float], grid: Sequence[float]) -> list[float]:
    """Linear interpolation at ascending grid distances in one pass (no bisect per point)"""
    result = []
    count = len(distances)
    index = 1
    for distance in grid:
        if distance <= distances[0]:
            result.append(values[0])
            continue
        while index < count and distances[index] < distance:
            index += 1
        if index >= count:
            result.append(values[-1])
            continue
        x0, x1 = distances[index - 1], distances[index]
        if x1 <= x0:
            result.append(values[index])
        else:
            result.append(values[index - 1] + (values[index] - values[index - 1]) * (distance - x0) / (x1 - x0))
    return result


class ResampledLap:
    """Lap columns resampled once on its distance grid, sliced for each corner

    Each column is resampled over the whole lap at first use, so comparing every corner costs
    one pass per column instead of one per corner.
    Distances are multiplied by scale (reference lap length, see telemetry_lap.distance_scale): an imported
    lap measured on driven distance is compared at the same corners as the reference lap.
    """

    def __init__(self, lap: LapData, step: float = GRID_STEP, scale: float = 1.0):
        self.lap = lap
        self.scale = scale
        self.grid = lap_grid(lap, step, scale)
        self._columns: dict[str, list[float] | None] = {}
        self._monotonic: dict[str, tuple[Sequence[float], Sequence[float]]] = {}
        self._times: tuple[Sequence[float], Sequence[float]] | None = None

    def column(self, name: str) -> list[float] | None:
        if name not in self._columns:  # from samples (shared with crossing & minimum searches)
            distances, values = self.samples(name)
            self._columns[name] = resample_sorted(distances, values, self.grid) \
                if self.grid and len(distances) >= 2 else None
        return self._columns[name]

    def indexes(self, start: float, end: float) -> tuple[int, int]:
        """Grid index range [first, last) between distances"""
        return bisect_left(self.grid, start), bisect_right(self.grid, end)

    def value_at(self, name: str, distance: float) -> float | None:
        """Column value at distance, None if column not recorded"""
        distances, values = self.samples(name)
        if not distances:
            return None
        return interpolate(distances, values, distance)

    def samples(self, name: str) -> tuple[Sequence[float], Sequence[float]]:
        """Recorded samples of column by increasing distance (empty if not recorded)"""
        if name not in self._monotonic:
            self._monotonic[name] = self.scaled(monotonic_distance(self.lap, name)) if name in self.lap.columns \
                else ([], [])
        return self._monotonic[name]

    def scaled(self, samples: tuple[Sequence[float], Sequence[float]]) -> tuple[Sequence[float], Sequence[float]]:
        """Samples with distances multiplied by lap scale"""
        if self.scale == 1.0:
            return samples
        return [distance * self.scale for distance in samples[0]], samples[1]

    def crossing(self, name: str, start: float, end: float, threshold: float) -> float:
        """First distance in [start, end] where column reaches threshold, between recorded samples
        (finer than grid step), -1 if not reached
        """
        distances, values = self.samples(name)
        if not distances:
            return -1.0
        index = max(bisect_left(distances, start), 1)
        while index < len(distances) and distances[index] <= end:
            if values[index] >= threshold:
                before, after = values[index - 1], values[index]
                if before >= threshold or after == before:
                    return max(distances[index - 1] if before >= threshold else distances[index], start)
                fraction = (threshold - before) / (after - before)
                return max(distances[index - 1] + (distances[index] - distances[index - 1]) * fraction, start)
            index += 1
        return -1.0

    def minimum(self, name: str, start: float, end: float) -> tuple[float, float] | None:
        """Distance & value of lowest recorded sample in [start, end], None if no sample there"""
        distances, values = self.samples(name)
        low, high = bisect_left(distances, start), bisect_right(distances, end)
        if low >= high:
            return None
        index = min(range(low, high), key=values.__getitem__)
        return distances[index], values[index]

    def time_at(self, distance: float) -> float | None:
        """Lap time at distance, None if lap time not recorded"""
        if self._times is None:
            self._times = self.scaled(monotonic_distance(self.lap)) if "lap_time" in self.lap.columns else ([], [])
        distances, times = self._times
        if len(distances) < 2:
            return None
        return interpolate(distances, times, distance)


def smooth(values: list[float], points: int = SMOOTH_POINTS) -> list[float]:
    """Centered moving average"""
    half = points // 2
    count = len(values)
    result = []
    for index in range(count):
        window = values[max(index - half, 0):min(index + half + 1, count)]
        result.append(sum(window) / len(window))
    return result


def lap_grid(lap: LapData, step: float = GRID_STEP, scale: float = 1.0) -> list[float]:
    """Distances every step meters along lap (lap length multiplied by scale)"""
    if len(lap) < 2:
        return []
    length = max(lap.distance) * scale
    return [index * step for index in range(int(length / step) + 1)]


def find_corners(lap: LapData | ResampledLap, hysteresis: float = SPEED_HYSTERESIS) -> list[Corner]:
    """Corners of lap from its speed, in lap order

    A lap ending at the speed it starts with is a loop: speeds are read from top speed (a straight) once
    around, so a corner across the start line is found once (not lost, nor split in two). Such a corner
    keeps its part on the apex side of the line (the other part belongs to previous or next lap).
    """
    sampled = lap if isinstance(lap, ResampledLap) else ResampledLap(lap)
    grid = sampled.grid
    speeds = sampled.column("speed_kph")
    if not speeds:
        return []
    speeds = smooth(speeds)
    count = len(speeds)
    circular = count > 10 and abs(speeds[0] - speeds[-1]) < hysteresis
    offset = max(range(count), key=speeds.__getitem__) if circular else 0
    order = [(offset + index) % count for index in range(count)]
    extremes = speed_extremes([speeds[index] for index in order], hysteresis)
    found: list[tuple[float, float, float]] = []
    end_index = count - 1
    for position, (is_minimum, minimum, _) in enumerate(extremes):
        if not is_minimum:
            continue
        start = order[extremes[position - 1][2] if position > 0 else 0]
        end = order[extremes[position + 1][1] if position + 1 < len(extremes) else end_index]
        apex = order[minimum]
        if not start <= apex <= end:  # across start line: part on apex side of the line
            if apex >= start:
                end = end_index
            else:
                start = 0
        found.append((grid[start], grid[apex], grid[end]))
    found.sort(key=lambda corner: corner[1])
    return [Corner(number + 1, *corner) for number, corner in enumerate(found)]


def speed_extremes(speeds: list[float], hysteresis: float) -> list[tuple[bool, int, int]]:
    """Speed peaks & minimums in turn: (is minimum, first index, last index)"""
    # Each one confirmed once speed moved hysteresis away from it.
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
    return extremes


def corner_stats(lap: LapData | ResampledLap, corner: Corner) -> CornerStats | None:
    """Lap driving between corner start & end, None if lap has no speed"""
    sampled = lap if isinstance(lap, ResampledLap) else ResampledLap(lap)
    first, last = sampled.indexes(corner.start, corner.end)
    all_speeds = sampled.column("speed_kph")
    start_time, end_time = sampled.time_at(corner.start), sampled.time_at(corner.end)
    if not all_speeds or first >= last or start_time is None or end_time is None:
        return None

    def part(name: str) -> list[float] | None:
        values = sampled.column(name)
        return values[first:last] if values else None

    grid = sampled.grid[first:last]
    speeds = all_speeds[first:last]
    lowest = min(range(len(speeds)), key=speeds.__getitem__)
    brake, throttle = part("brake"), part("throttle")
    step = sampled.grid[1] - sampled.grid[0] if len(sampled.grid) > 1 else GRID_STEP
    # Points found on grid, then placed between recorded samples (grid step would move them up to 5 m)
    apex, min_speed = grid[lowest], speeds[lowest]
    exact = sampled.minimum("speed_kph", grid[lowest] - step, grid[lowest] + step)
    if exact is not None:
        apex, min_speed = exact
    brake_point = -1.0
    if brake:
        found = braking_start(brake, lowest, step)
        if found >= 0:
            brake_point = sampled.crossing("brake", grid[found] - step, grid[found], BRAKE_ON)
            if brake_point < 0:
                brake_point = grid[found]
    throttle_point = -1.0
    if throttle:
        found = next((index for index in range(lowest, len(grid)) if throttle[index] >= FULL_THROTTLE), -1)
        if found >= 0:
            throttle_point = sampled.crossing("throttle", max(grid[found] - step, apex), grid[found], FULL_THROTTLE)
            if throttle_point < 0:
                throttle_point = grid[found]
    trail, coast, overlap = count_driving_times(part("lap_time"), part("steering"), brake, throttle)
    gears = part("gear")
    return CornerStats(
        min_speed, apex, brake_point, throttle_point, end_time - start_time, trail, coast, overlap,
        entry_speed=speeds[0], exit_speed=speeds[-1], apex_gear=round(gears[lowest]) if gears else 0,
        peak_brake=max(brake) if brake else 0.0,
    )


def braking_start(brake: list[float], lowest: int, step: float) -> int:
    """Grid index where braking for apex starts, -1 if none: last braking before apex, followed back over short
    releases (a brake tap earlier on the straight is another braking)"""
    last = next((index for index in range(lowest, -1, -1) if brake[index] >= BRAKE_ON), -1)
    if last < 0:
        return -1
    found, released = last, 0.0
    for index in range(last - 1, -1, -1):
        if brake[index] >= BRAKE_ON:
            found, released = index, 0.0
        else:
            released += step
            if released > BRAKE_RELEASE:
                break
    return found


def driving_times(
    lap: LapData, grid: list[float], brake: list[float] | None, throttle: list[float] | None,
) -> tuple[float, float, float]:
    """Seconds of trail braking, coasting & pedal overlap along grid (0 if pedals not recorded)"""
    return count_driving_times(resample(lap, "lap_time", grid), resample(lap, "steering", grid), brake, throttle)


def count_driving_times(
    times: list[float] | None, steering: list[float] | None, brake: list[float] | None,
    throttle: list[float] | None,
) -> tuple[float, float, float]:
    """Seconds of trail braking, coasting & pedal overlap from samples on the same grid"""
    if not times or brake is None or throttle is None:
        return 0.0, 0.0, 0.0
    steering = steering or [0.0] * len(times)
    trail = coast = overlap = 0.0
    for index in range(len(times) - 1):
        step = max(times[index + 1] - times[index], 0.0)
        pressed_brake, pressed_throttle = brake[index], throttle[index]
        if pressed_brake >= BRAKE_ON and abs(steering[index]) >= STEERING_ON:
            trail += step
        if pressed_brake < PEDAL_OFF and pressed_throttle < PEDAL_OFF:
            coast += step
        if pressed_brake >= PEDAL_ON and pressed_throttle >= PEDAL_ON:
            overlap += step
    return trail, coast, overlap


def compare_corners(
    reference: LapData | ResampledLap, compared: LapData | ResampledLap | None = None,
    hysteresis: float = SPEED_HYSTERESIS, scale: float = 1.0,
) -> list[CornerComparison]:
    """Corner stats of reference lap, and of compared lap on the same corners (its distances multiplied by scale)

    Resampled laps can be given (kept by caller): columns are not resampled again.
    """
    sampled_reference = reference if isinstance(reference, ResampledLap) else ResampledLap(reference)
    sampled_compared = compared if compared is None or isinstance(compared, ResampledLap) \
        else ResampledLap(compared, scale=scale)
    result = []
    for corner in find_corners(sampled_reference, hysteresis):
        ref_stats = corner_stats(sampled_reference, corner)
        if ref_stats is None:
            continue
        other = corner_stats(sampled_compared, corner) if sampled_compared is not None else None
        result.append(CornerComparison(corner, ref_stats, other))
    return result


def total_lap_time(lap: LapData) -> float:
    """Lap time timed by game if known, else last recorded sample (a few hundredths short of the line)"""
    return official_lap_time(lap) or lap.lap_time


def lap_time_delta(reference: LapData, compared: LapData) -> float:
    """Lap time difference (compared - reference)"""
    return total_lap_time(compared) - total_lap_time(reference)


def straights_delta(rows: list[CornerComparison], reference: LapData, compared: LapData) -> float:
    """Time lost on straights: lap delta not spent in corners (between top speed & braking)"""
    corners = sum(row.time_delta or 0.0 for row in rows)
    return lap_time_delta(reference, compared) - corners


class IdealLap(NamedTuple):
    """Best time of each lap part among laps (corners & straights between them)"""

    time: float  # sum of best part times
    bounds: list[float]  # part limits (reference lap distances): 0, corner start, corner end... lap end
    best: list[int]  # index (in laps) of fastest lap in each part


def ideal_lap(laps: Sequence[LapData | ResampledLap], corners: list[Corner], scales: Sequence[float] = ()) -> IdealLap | None:
    """Fastest time of every corner & straight among laps, None if under 2 laps with lap time

    Corner distances are reference lap distances: each lap distances multiplied by its scale (1 if not given),
    resampled laps (kept by caller) carry their own scale.
    """
    sampled = [lap if isinstance(lap, ResampledLap) else ResampledLap(lap, scale=scales[index] if index < len(scales)
               else 1.0) for index, lap in enumerate(laps)]
    datas = [item.lap for item in sampled]
    timed = [index for index, lap in enumerate(datas) if lap.lap_time > 0 and "lap_time" in lap.columns and len(lap) >= 2]
    if len(timed) < 2 or not corners:
        return None
    bounds = [0.0]
    for corner in corners:
        for distance in (corner.start, corner.end):
            if distance > bounds[-1]:
                bounds.append(distance)
    length = max(datas[0].distance)
    if length > bounds[-1]:
        bounds.append(length)
    times = []
    for index in timed:
        points = [0.0, *(sampled[index].time_at(distance) or 0.0 for distance in bounds[1:-1]), total_lap_time(datas[index])]
        times.append([max(end - start, 0.0) for start, end in pairwise(points)])
    best = [min(range(len(timed)), key=lambda position: times[position][part]) for part in range(len(bounds) - 1)]
    total = sum(times[position][part] for part, position in enumerate(best))
    return IdealLap(total, bounds, [timed[position] for position in best])


# Coaching: where compared lap loses most time & why
COACH_MIN_LOSS = 0.03  # seconds lost in a corner worth a tip
COACH_BRAKE = 5.0  # meters of braking point difference worth telling
COACH_SPEED = 2.0  # km/h of minimum / exit speed difference worth telling
COACH_THROTTLE = 5.0  # meters of full throttle point difference worth telling
COACH_TIME = 0.1  # seconds of coasting / pedal overlap difference worth telling


class CoachTip(NamedTuple):
    """Corner where compared lap loses time: corner row index, time lost, causes (kind, value) most telling first

    Kinds: brake_early, brake_late (meters), min_speed (km/h lower), throttle_late (meters),
    coasting, overlap (seconds more), exit_speed (km/h lower).
    """

    row: int
    loss: float
    causes: list[tuple[str, float]]


def coaching_tips(rows: Sequence[CornerComparison], limit: int = 3) -> list[CoachTip]:
    """Corners where compared lap loses most time against reference lap, with likely causes"""
    tips = []
    for index, row in enumerate(rows):
        ref, comp = row.reference, row.compared
        loss = row.time_delta
        if comp is None or loss is None or loss < COACH_MIN_LOSS:
            continue
        causes: list[tuple[str, float, float]] = []  # kind, value, weight (most telling first)
        if ref.brake_point >= 0 and comp.brake_point >= 0:
            gap = comp.brake_point - ref.brake_point
            if gap <= -COACH_BRAKE:
                causes.append(("brake_early", -gap, -gap / COACH_BRAKE))
            elif gap >= COACH_BRAKE * 2 and comp.min_speed < ref.min_speed - COACH_SPEED:  # braked too late: overshoot
                causes.append(("brake_late", gap, gap / COACH_BRAKE / 2))
        speed_gap = ref.min_speed - comp.min_speed
        if speed_gap >= COACH_SPEED:
            causes.append(("min_speed", speed_gap, speed_gap / COACH_SPEED))
        if ref.throttle_point >= 0 and comp.throttle_point >= 0:
            gap = comp.throttle_point - ref.throttle_point
            if gap >= COACH_THROTTLE:
                causes.append(("throttle_late", gap, gap / COACH_THROTTLE))
        for kind, more in (("coasting", comp.coasting - ref.coasting), ("overlap", comp.overlap - ref.overlap)):
            if more >= COACH_TIME:
                causes.append((kind, more, more / COACH_TIME))
        exit_gap = ref.exit_speed - comp.exit_speed
        if exit_gap >= COACH_SPEED * 1.5:
            causes.append(("exit_speed", exit_gap, exit_gap / COACH_SPEED / 1.5))
        causes.sort(key=lambda cause: -cause[2])
        tips.append(CoachTip(index, loss, [(kind, value) for kind, value, _ in causes]))
    tips.sort(key=lambda tip: -tip.loss)
    return tips[:limit]
