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
Recorded lap telemetry (CSV from telemetry recorder module)
"""

from __future__ import annotations

import csv
import logging
import os
from bisect import bisect_left
from typing import NamedTuple

logger = logging.getLogger(__name__)


class LapFile(NamedTuple):
    """Recorded lap file"""

    filename: str
    path: str
    valid: bool


class LapData(NamedTuple):
    """Lap telemetry columns"""

    name: str
    columns: dict[str, list[float]]

    @property
    def distance(self) -> list[float]:
        return self.columns["distance"]

    @property
    def lap_time(self) -> float:
        times = self.columns.get("lap_time", [])
        return times[-1] if times else 0.0

    def __len__(self) -> int:
        return len(self.columns.get("distance", ()))


def list_tracks(filepath: str) -> list[str]:
    """Track & class folders with recorded laps"""
    try:
        return sorted(
            name for name in os.listdir(filepath)
            if os.path.isdir(os.path.join(filepath, name))
        )
    except OSError:
        return []


def list_laps(filepath: str, track: str) -> list[LapFile]:
    """Recorded laps of track, newest first"""
    folder = os.path.join(filepath, track)
    try:
        names = [name for name in os.listdir(folder) if name.endswith(".csv")]
    except OSError:
        return []
    names.sort(reverse=True)
    return [LapFile(name, os.path.join(folder, name), not name.endswith(" invalid.csv")) for name in names]


def load_lap(path: str) -> LapData:
    """Load lap CSV file, raises OSError or ValueError if invalid"""
    columns: dict[str, list[float]] = {}
    with open(path, newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader, None)
        if not header or "distance" not in header:
            raise ValueError("not a TinyPedal telemetry file")
        for name in header:
            columns[name] = []
        values = tuple(columns.values())
        for row in reader:
            if len(row) != len(header):
                continue
            try:
                numbers = [float(value) for value in row]
            except ValueError:
                continue
            for column, number in zip(values, numbers):
                column.append(number)
    if not columns["distance"]:
        raise ValueError("no telemetry sample")
    return LapData(os.path.splitext(os.path.basename(path))[0], columns)


def interpolate(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation of y at x (xs sorted ascending)"""
    index = bisect_left(xs, x)
    if index <= 0:
        return ys[0]
    if index >= len(xs):
        return ys[-1]
    x0, x1 = xs[index - 1], xs[index]
    if x1 <= x0:
        return ys[index]
    return ys[index - 1] + (ys[index] - ys[index - 1]) * (x - x0) / (x1 - x0)


def monotonic_distance(lap: LapData) -> tuple[list[float], list[float]]:
    """Distance & lap time samples with increasing distance only (ignore reset glitches)"""
    distances: list[float] = []
    times: list[float] = []
    last = float("-inf")
    for distance, lap_time in zip(lap.distance, lap.columns["lap_time"]):
        if distance > last:
            distances.append(distance)
            times.append(lap_time)
            last = distance
    return distances, times


def compute_delta(reference: LapData, compare: LapData) -> list[tuple[float, float]]:
    """Time delta (compare - reference) along distance, positive = compare slower"""
    ref_dist, ref_time = monotonic_distance(reference)
    cmp_dist, cmp_time = monotonic_distance(compare)
    if len(ref_dist) < 2 or not cmp_dist:
        return []
    return [
        (distance, lap_time - interpolate(ref_dist, ref_time, distance))
        for distance, lap_time in zip(cmp_dist, cmp_time)
    ]
