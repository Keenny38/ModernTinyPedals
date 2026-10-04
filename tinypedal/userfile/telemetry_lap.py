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

File name: <date time> lap<number> <lap time>[ invalid].csv (or .csv.gz if compressed).
Optional first line: "# " + json lap info (track, vehicle, session, weather, sectors, kind...).
Then CSV header line and samples.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
import re
import time
from bisect import bisect_left
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import IO, NamedTuple, TypeVar

logger = logging.getLogger(__name__)

LAP_EXTS = (".csv.gz", ".csv")
INFO_PREFIX = "# "
IMPORT_FOLDER = ".imported"  # laps imported from other files (MoTeC), not a track folder
_lap_time_name = re.compile(r" lap\d+ (\d+)m(\d+(?:\.\d+)?)s(?: invalid)?$")
_lap_number_name = re.compile(r"(?:^| )lap(\d+) ")
SESSION_START_TOLERANCE = 120  # seconds, laps whose recorded session start differ less are same session
SESSION_GAP = 1800  # seconds without lap: new session (laps recorded without session start)
DISTANCE_SCALE_MIN = 0.01  # lap lengths differing less are the same (no distance scaling for delta)
DISTANCE_SCALE_MAX = 0.10  # lap lengths differing more are not the same lap (lap cut short)
EntryType = TypeVar("EntryType")


def lap_stem(filename: str) -> str:
    """File name without lap file extension"""
    for ext in LAP_EXTS:
        if filename.endswith(ext):
            return filename[:-len(ext)]
    return os.path.splitext(filename)[0]


def is_lap_file(filename: str) -> bool:
    """Whether file name is a recorded lap file"""
    return filename.endswith(LAP_EXTS)


def lap_time_of(filename: str) -> float:
    """Lap time from file name, 0 if unknown"""
    match = _lap_time_name.search(lap_stem(filename))
    if not match:
        return 0.0
    return int(match.group(1)) * 60 + float(match.group(2))


def lap_number_of(filename: str) -> int:
    """Lap number from file name, 0 if unknown"""
    match = _lap_number_name.search(lap_stem(filename))
    return int(match.group(1)) if match else 0


def lap_timestamp_of(filename: str) -> float:
    """Time lap was recorded, from file name date ("YYYY-MM-DD HH-MM-SS ..."), 0 if unknown"""
    try:
        return time.mktime(time.strptime(filename[:19], "%Y-%m-%d %H-%M-%S"))
    except (ValueError, OverflowError):
        return 0.0


def group_sessions(
    entries: Sequence[EntryType], filename: Callable[[EntryType], str], info: Callable[[EntryType], dict],
) -> list[list[EntryType]]:
    """Group laps by session, newest session first, laps in driving order

    Same session: same recorded session start (laps from this version), otherwise
    (older laps) same session type, lap number going up, and less than SESSION_GAP between laps.
    """
    ordered = sorted(entries, key=lambda entry: (lap_timestamp_of(filename(entry)), lap_number_of(filename(entry))))
    groups: list[list[EntryType]] = []
    last = None
    for entry in ordered:
        if last is None or not same_session(last, entry, filename, info):
            groups.append([])
        groups[-1].append(entry)
        last = entry
    groups.reverse()
    return groups


def same_session(previous, entry, filename: Callable, info: Callable) -> bool:
    """Whether lap was driven in same session as previous lap"""
    start_a, start_b = info(previous).get("session_start"), info(entry).get("session_start")
    if isinstance(start_a, (int, float)) and isinstance(start_b, (int, float)):
        return abs(start_a - start_b) < SESSION_START_TOLERANCE
    if info(previous).get("session", "") != info(entry).get("session", ""):
        return False
    if lap_number_of(filename(entry)) <= lap_number_of(filename(previous)):
        return False
    return lap_timestamp_of(filename(entry)) - lap_timestamp_of(filename(previous)) < SESSION_GAP


def is_valid_name(filename: str) -> bool:
    """Whether file name is not marked invalid"""
    return not lap_stem(filename).endswith(" invalid")


class LapFile(NamedTuple):
    """Recorded lap file"""

    filename: str
    path: str
    valid: bool
    lap_time: float = 0.0


class LapData(NamedTuple):
    """Lap telemetry columns"""

    name: str
    columns: dict[str, list[float]]
    info: dict | None = None  # lap info from file first line

    @property
    def distance(self) -> list[float]:
        return self.columns["distance"]

    @property
    def lap_time(self) -> float:
        times = self.columns.get("lap_time", [])
        return times[-1] if times else 0.0

    @property
    def meta(self) -> dict:
        """Lap info, empty if not recorded"""
        return self.info or {}

    def __len__(self) -> int:
        return len(self.columns.get("distance", ()))


def list_tracks(filepath: str) -> list[str]:
    """Track & class folders with recorded laps (hidden folders left out, see IMPORT_FOLDER)"""
    try:
        return sorted(
            name for name in os.listdir(filepath)
            if not name.startswith(".") and os.path.isdir(os.path.join(filepath, name))
        )
    except OSError:
        return []


def lap_files(folder: str) -> list[LapFile]:
    """Recorded lap files of folder, newest first"""
    try:
        names = [name for name in os.listdir(folder) if is_lap_file(name)]
    except OSError:
        return []
    names.sort(reverse=True)
    return [
        LapFile(name, os.path.join(folder, name), is_valid_name(name), lap_time_of(name))
        for name in names
    ]


def list_laps(filepath: str, track: str) -> list[LapFile]:
    """Recorded laps of track, newest first"""
    return lap_files(os.path.join(filepath, track))


def best_laps(laps: list[LapFile], count: int) -> list[LapFile]:
    """Fastest valid laps, fastest first"""
    timed = sorted((lap for lap in laps if lap.valid and lap.lap_time > 0), key=lambda lap: lap.lap_time)
    return timed[:max(count, 0)]


def open_lap_file(path: str) -> IO[str]:
    """Open lap file as text, compressed or not"""
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
    return open(path, newline="", encoding="utf-8")


def read_lap_info(path: str) -> dict:
    """Lap info (first line) only, empty if none"""
    try:
        with open_lap_file(path) as file:
            return parse_info(file.readline())
    except (OSError, EOFError, gzip.BadGzipFile, UnicodeDecodeError):
        return {}


def parse_info(line: str) -> dict:
    """Lap info from file first line, empty if not an info line"""
    if not line.startswith(INFO_PREFIX):
        return {}
    try:
        info = json.loads(line[len(INFO_PREFIX):])
    except ValueError:
        return {}
    return info if isinstance(info, dict) else {}


def load_lap(path: str) -> LapData:
    """Load lap CSV file, raises OSError or ValueError if invalid"""
    try:
        with open_lap_file(path) as file:
            first = file.readline()
            info = parse_info(first)
            lines = file if info else _chain(first, file)
            reader = csv.reader(lines)
            header = next(reader, None)
            if not header or "distance" not in header:
                raise ValueError("not a TinyPedal telemetry file")
            width = len(header)
            rows = [row for row in reader if len(row) == width]
    except (EOFError, gzip.BadGzipFile, UnicodeDecodeError, csv.Error) as error:
        raise ValueError(f"unreadable file: {error}") from error
    columns = dict(zip(header, parse_columns(rows, width)))
    if not columns["distance"]:
        raise ValueError("no telemetry sample")
    start, end = lap_bounds(columns["distance"])
    if start > 0 or end < len(columns["distance"]):
        columns = {name: values[start:end] for name, values in columns.items()}
    times = columns.get("lap_time")
    if times:
        columns["distance"] = smooth_distance(times, columns["distance"])
    return LapData(lap_stem(os.path.basename(path)), columns, info or None)


def parse_columns(rows: list[list[str]], width: int) -> list[list[float]]:
    """Text rows to number columns, rows with a non number value left out

    Whole columns are converted at once (C loops), row by row only if a value is not a number.
    """
    try:
        return [list(map(float, column)) for column in zip(*rows)] if rows else [[] for _ in range(width)]
    except ValueError:
        pass
    numbers = []
    for row in rows:
        try:
            numbers.append([float(value) for value in row])
        except ValueError:
            continue
    return [list(column) for column in zip(*numbers)] if numbers else [[] for _ in range(width)]


def lap_bounds(distances: list[float]) -> tuple[int, int]:
    """Index range of samples that belong to lap (start, end)

    Lap distance is reset a bit after lap start time (game updates scoring less often than
    telemetry): first samples may still carry previous lap distance (near track length),
    and last samples may already carry next lap distance (near 0). These samples are left out.
    """
    count = len(distances)
    if count < 3:
        return 0, count
    half = max(distances) / 2
    start = 0
    while start < count - 1 and distances[start] > half:
        start += 1
    if start >= count - 1:  # never reset: keep everything
        start = 0
    end = count
    if max(distances[start:]) > half:  # lap went far: low distances at end belong to next lap
        while end - 1 > start and distances[end - 1] < half:
            end -= 1
    return start, end


def smooth_distance(times: list[float], distances: list[float]) -> list[float]:
    """Distance interpolated along time between distance updates

    Game updates lap distance less often than other telemetry (about 5 times per second),
    so several samples share the same distance. Each sample gets its own distance instead,
    so charts along distance keep every sample.
    """
    count = len(distances)
    changes = [0] + [index for index in range(1, count) if distances[index] != distances[index - 1]]
    if len(changes) < 2 or len(changes) == count:
        return distances
    result = list(distances)
    for first, last in pairwise(changes):
        t0, t1 = times[first], times[last]
        d0, d1 = distances[first], distances[last]
        if t1 <= t0 or d1 < d0:
            continue  # reset glitch, keep raw values
        for index in range(first + 1, last):
            result[index] = d0 + (d1 - d0) * (times[index] - t0) / (t1 - t0)
    return result


def _chain(first: str, rest):
    yield first
    yield from rest


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


def monotonic_distance(lap: LapData, column: str = "lap_time") -> tuple[list[float], list[float]]:
    """Distance & column samples with increasing distance only (ignore reset glitches)"""
    distances: list[float] = []
    values: list[float] = []
    last = float("-inf")
    for distance, value in zip(lap.distance, lap.columns[column]):
        if distance > last:
            distances.append(distance)
            values.append(value)
            last = distance
    return distances, values


def distance_scale(reference: LapData, compare: LapData) -> float:
    """Factor bringing compared lap distances to reference lap length, 1 if lengths match

    Recorded laps use track distance (same length every lap). An imported log may use driven
    distance, a bit longer or shorter: its distances are scaled so corners line up. Lengths more
    than 10% apart are not the same lap (cut short): left unscaled.
    """
    if len(reference) < 2 or len(compare) < 2:
        return 1.0
    ref_length, cmp_length = max(reference.distance), max(compare.distance)
    if ref_length <= 0 or cmp_length <= 0:
        return 1.0
    ratio = ref_length / cmp_length
    return ratio if DISTANCE_SCALE_MIN < abs(ratio - 1) < DISTANCE_SCALE_MAX else 1.0


def compute_delta(reference: LapData, compare: LapData) -> list[tuple[float, float]]:
    """Time delta (compare - reference) along distance, positive = compare slower

    Compared lap distances scaled to reference lap length if they differ (see distance_scale).
    """
    ref_dist, ref_time = monotonic_distance(reference)
    cmp_dist, cmp_time = monotonic_distance(compare)
    if len(ref_dist) < 2 or not cmp_dist:
        return []
    scale = distance_scale(reference, compare)
    if scale != 1.0:
        cmp_dist = [distance * scale for distance in cmp_dist]
    return [
        (distance, lap_time - interpolate(ref_dist, ref_time, distance))
        for distance, lap_time in zip(cmp_dist, cmp_time)
    ]


def delta_rate(distances: list[float], deltas: list[float], window: float = 40.0) -> list[float]:
    """Time lost (positive) or gained per 100 m along delta, measured over window meters"""
    if len(distances) < 2:
        return [0.0] * len(distances)
    half = window / 2
    return [
        (interpolate(distances, deltas, distance + half) - interpolate(distances, deltas, distance - half))
        / window * 100
        for distance in distances
    ]


def official_sector_times(lap: LapData) -> list[float]:
    """Sector times from game, recorded in lap info, empty if none"""
    official = lap.meta.get("sectors")
    if isinstance(official, list) and len(official) == 3 and all(
            isinstance(value, (int, float)) and value > 0 for value in official):
        return [float(value) for value in official]
    return []


def sector_bounds(lap: LapData) -> list[float]:
    """Lap distances where sector 2 & 3 start, empty if unknown

    Distance at official sector times if recorded: the sector column comes from scoring data,
    updated about 5 times per second, so it changes up to 0.2s (10-15 meters) after the line.
    """
    official = official_sector_times(lap)
    if official and "lap_time" in lap.columns and len(lap) >= 2:
        distances, times = monotonic_distance(lap)
        if len(times) >= 2:
            return [interpolate(times, distances, official[0]), interpolate(times, distances, official[0] + official[1])]
    sectors = lap.columns.get("sector")
    if not sectors:
        return []
    bounds = []
    for target in (1, 2):
        for distance, previous, sector in zip(lap.distance[1:], sectors, sectors[1:]):
            if previous < target <= sector:
                bounds.append(distance)
                break
    return bounds if len(bounds) == 2 else []


def sector_times(lap: LapData) -> list[float]:
    """Sector 1, 2, 3 times, official times from lap info if recorded, else from samples"""
    official = official_sector_times(lap)
    if official:
        return official
    bounds = sector_bounds(lap)
    if not bounds or len(lap) < 2:
        return []
    distances, times = monotonic_distance(lap)
    t1, t2 = (interpolate(distances, times, bound) for bound in bounds)
    total = lap.lap_time
    result = [t1, t2 - t1, total - t2]
    return result if all(value > 0 for value in result) else []


def theoretical_best(sector_list: list[list[float]]) -> tuple[float, list[float]]:
    """Best sum of sectors (total, best of each sector) from sector times of laps, (0, []) if none"""
    complete = [sectors for sectors in sector_list if len(sectors) == 3]
    if not complete:
        return 0.0, []
    best = [min(sectors[index] for sectors in complete) for index in range(3)]
    return sum(best), best


def decimate_minmax(
    xs: list[float], ys: list[float], start: float, end: float, buckets: int,
) -> list[tuple[float, float]]:
    """Points of xs range [start, end] reduced to min & max of each bucket (keeps peaks)

    Includes one point before & after range, so lines reach plot edges.
    """
    if not xs:
        return []
    first = max(bisect_left(xs, start) - 1, 0)
    last = min(bisect_left(xs, end) + 1, len(xs))
    count = last - first
    buckets = max(buckets, 1)
    if count <= buckets * 2:
        return list(zip(xs[first:last], ys[first:last]))
    points: list[tuple[float, float]] = []
    span = (end - start) / buckets or 1.0
    bucket = None
    low_index = high_index = first
    for index in range(first, last):
        current = int((xs[index] - start) // span)
        if current != bucket:
            if bucket is not None:
                points.extend(_bucket_points(xs, ys, low_index, high_index))
            bucket = current
            low_index = high_index = index
        elif ys[index] < ys[low_index]:
            low_index = index
        elif ys[index] > ys[high_index]:
            high_index = index
    points.extend(_bucket_points(xs, ys, low_index, high_index))
    return points


def _bucket_points(xs, ys, low_index, high_index):
    if low_index == high_index:
        return ((xs[low_index], ys[low_index]),)
    if low_index < high_index:
        return (xs[low_index], ys[low_index]), (xs[high_index], ys[high_index])
    return (xs[high_index], ys[high_index]), (xs[low_index], ys[low_index])
