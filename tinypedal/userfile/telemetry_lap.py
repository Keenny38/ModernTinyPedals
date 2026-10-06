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
import math
import os
import re
import threading
import time
import zlib
from array import array
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from functools import lru_cache
from itertools import pairwise
from typing import IO, NamedTuple, TypeVar

logger = logging.getLogger(__name__)

LAP_EXTS = (".csv.gz", ".csv")
INFO_PREFIX = "# "
IMPORT_FOLDER = ".imported"  # laps imported from other files (MoTeC), not a track folder
VIEWER_SETTING = ".lap_viewer.json"  # lap viewer settings (see ui.lap_viewer), lap selection of each track
_lap_time_name = re.compile(r" lap\d+ (\d+)m(\d+(?:\.\d+)?)s(?: invalid)?$")
_lap_number_name = re.compile(r"(?:^| )lap(\d+) ")
SESSION_START_TOLERANCE = 120  # seconds, laps whose recorded session start differ less are same session
SESSION_GAP = 1800  # seconds without lap: new session (laps recorded without session start)
SCORING_COLUMNS = ("path_lateral", "track_edge")  # game scoring data, updated less often than telemetry
SCORING_GAP = 1.0  # seconds, longer holds between scoring updates are not interpolated
DISTANCE_SCALE_MIN = 0.01  # recorded track lengths differing more are another circuit (see same_circuit)
DISTANCE_SCALE_TOLERANCE = 0.001  # lap end distances differing less are the same (no distance scaling)
DISTANCE_SCALE_MAX = 0.10  # lap lengths differing more are not the same lap (lap cut short)
EXACT_COLUMNS = ("time", "lap_time", "distance")  # double precision, others single (mm precision, half size)
LAP_END_SECONDS = 1.0  # lap start & end added to lap time curve only if first / last sample this close in time
LAP_END_METERS = 60.0  # and in distance (farther: lap cut short, not a late game update)
LAP_END_OVERSHOOT = 1.0  # meters, last samples this far past track length (rounded imported length) end the lap
EntryType = TypeVar("EntryType")
Column = list | array  # lap column values: packed array once loaded (8 times less memory than a list)


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


@lru_cache(maxsize=8192)
def lap_timestamp_of(filename: str) -> float:
    """Time lap was recorded, from file name date ("YYYY-MM-DD HH-MM-SS ..."), 0 if unknown (cached: lap lists
    sort & group by it often)"""
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
    """Lap telemetry columns (packed arrays once loaded from file, lists when built in code)"""

    name: str
    columns: dict[str, Column]
    info: dict | None = None  # lap info from file first line

    @property
    def distance(self) -> Column:
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


WINDOWS_RESERVED_NAMES = frozenset((
    "CON", "PRN", "AUX", "NUL", *(f"COM{index}" for index in range(10)), *(f"LPT{index}" for index in range(10)),
))


def lap_folder_name(combo_name: str) -> str:
    """Folder name of track & class laps, valid on every system ("unknown" if empty)

    Windows silently drops trailing spaces & dots of a folder name, then files cannot be
    written in it ("Track - " when class is empty).
    """
    name = combo_name.strip().rstrip(". ")
    if name.endswith(" -"):  # empty class name
        name = name[:-2].rstrip(". ")
    if name.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        name = f"{name}_"
    return name or "unknown"


def viewer_reference_name(filepath: str, track: str) -> str:
    """File name of lap set as reference in lap viewer for track folder (last selection), empty if none"""
    try:
        with open(os.path.join(filepath, VIEWER_SETTING), encoding="utf-8") as file:
            setting = json.load(file)
    except (OSError, ValueError):
        return ""
    selections = setting.get("selections") if isinstance(setting, dict) else None
    selection = selections.get(track) if isinstance(selections, dict) else None
    name = selection.get("reference") if isinstance(selection, dict) else None
    return name if isinstance(name, str) else ""


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
    except (OSError, EOFError, gzip.BadGzipFile, zlib.error, UnicodeDecodeError):  # corrupt .gz: zlib.error
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
    except (EOFError, gzip.BadGzipFile, zlib.error, UnicodeDecodeError, csv.Error) as error:
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
        for name in SCORING_COLUMNS:  # updated about 5 times per second by game: values between updates
            if name in columns:
                columns[name] = smooth_steps(times, columns[name])
    return LapData(lap_stem(os.path.basename(path)), pack_columns(columns), info or None)


def pack_columns(columns: Mapping[str, Column]) -> dict[str, Column]:
    """Columns as packed arrays: double precision for time & distance, single for others

    A list keeps a float object per value (about 32 bytes), an array 4 or 8 bytes: a loaded lap takes
    a few MB instead of tens.
    """
    return {
        name: values if isinstance(values, array) and values.typecode == column_type(name)
        else array(column_type(name), values)
        for name, values in columns.items()
    }


def column_type(name: str) -> str:
    """Array type code of lap column"""
    return "d" if name in EXACT_COLUMNS else "f"


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


def smooth_steps(times: list[float], values: list[float]) -> list[float]:
    """Values interpolated along time between game updates (value held between updates otherwise)"""
    count = len(values)
    changes = [0] + [index for index in range(1, count) if values[index] != values[index - 1]]
    if len(changes) < 2 or len(changes) == count:
        return values
    result = list(values)
    for first, last in pairwise(changes):
        t0, t1 = times[first], times[last]
        if t1 <= t0 or t1 - t0 > SCORING_GAP:  # long hold (pits, pause): kept as is
            continue
        v0, v1 = values[first], values[last]
        for index in range(first + 1, last):
            result[index] = v0 + (v1 - v0) * (times[index] - t0) / (t1 - t0)
    return result


def median_sector_bounds(laps: Sequence[LapData]) -> list[float]:
    """Sector 2 & 3 start distances: median over laps with official sector times (one lap off does not move them)"""
    bounds = [found for lap in laps if official_sector_times(lap) and len(found := sector_bounds(lap)) == 2]
    if not bounds:
        return []
    middle = len(bounds) // 2
    return [sorted(values)[middle] if len(bounds) % 2 else sum(sorted(values)[middle - 1:middle + 1]) / 2
            for values in zip(*bounds)]


def _chain(first: str, rest):
    yield first
    yield from rest


def interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
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


INCREASING_CACHE = 64  # distance columns whose increasing samples are remembered
_increasing: OrderedDict[int, tuple[Column, int, array | None, Column]] = OrderedDict()
_increasing_lock = threading.Lock()


def increasing_indexes(distances: Column) -> list[int] | None:
    """Indexes of samples whose distance goes forward (reset glitches left out), None if every sample does

    Found once per distance column (loaded lap columns never change): every channel of a lap, corners,
    lap times... reuse it instead of walking the lap again.
    """
    indexes = increasing_samples(distances)[0]
    return None if indexes is None else list(indexes)


def increasing_samples(distances: Column) -> tuple[array | None, Column]:
    """Indexes of samples whose distance goes forward (None if every sample does) & their distances (column itself
    if every sample does), found once per distance column: every channel of a lap shares the same distances"""
    key = id(distances)
    with _increasing_lock:
        cached = _increasing.get(key)
        if cached is not None and cached[0] is distances and cached[1] == len(distances):
            _increasing.move_to_end(key)
            return cached[2], cached[3]
    indexes = array("i")  # packed: a few bytes per sample, kept for 64 laps
    last = float("-inf")
    for index, distance in enumerate(distances):
        if distance > last:
            indexes.append(index)
            last = distance
    result = None if len(indexes) == len(distances) else indexes
    kept = distances if result is None else picked(distances, indexes)
    with _increasing_lock:
        _increasing[key] = (distances, len(distances), result, kept)
        while len(_increasing) > INCREASING_CACHE:
            _increasing.popitem(last=False)
    return result, kept


def picked(values: Column, indexes: Sequence[int]) -> Column:
    """Values at indexes, packed array kept packed (4 or 8 bytes a value instead of a float object)"""
    if isinstance(values, array):
        return array(values.typecode, map(values.__getitem__, indexes))
    return [values[index] for index in indexes]


def monotonic_distance(lap: LapData, column: str = "lap_time") -> tuple[Sequence[float], Sequence[float]]:
    """Distance & column samples with increasing distance only (ignore reset glitches)

    Lap columns themselves are returned when every sample goes forward (no copy), else the same distances for
    every column of lap: never change them.
    """
    distances, values = lap.distance, lap.columns[column]
    indexes, kept = increasing_samples(distances)
    count = min(len(distances), len(values))
    if indexes is None:
        if count == len(distances) == len(values):
            return distances, values
        return distances[:count], values[:count]
    if count < len(distances):  # shorter column (lap built in code)
        inside = [index for index in indexes if index < count]
        return picked(distances, inside), picked(values, inside)
    return kept, picked(values, indexes)


def official_lap_time(lap: LapData) -> float:
    """Lap time timed by game: from lap file name, else sum of official sector times, 0 if unknown"""
    match = _lap_time_name.search(lap.name)
    if match:
        return int(match.group(1)) * 60 + float(match.group(2))
    return sum(official_sector_times(lap))


def lap_length(lap: LapData) -> float:
    """Track length recorded in lap info, 0 if unknown"""
    length = lap.meta.get("track_length")
    return float(length) if isinstance(length, (int, float)) and not isinstance(length, bool) and length > 0 else 0.0


def lap_time_curve(lap: LapData) -> tuple[Sequence[float], Sequence[float]]:
    """Distances & lap times (increasing distance) from line to line, empty if lap time not recorded

    Game resets lap distance a bit after the line and updates it about 5 times per second (see lap_bounds &
    smooth_distance): first sample comes up to 0.2 s after lap start, last one up to 20 m before lap end. Lap
    start (0, 0) & lap end (track length, official lap time) are added when that close: delta at the line is the
    lap time gap, mini-sectors add up to lap time. Samples beyond them (distance still before the line at lap
    start, not updated yet past lap time at lap end, or a bit past rounded track length of an imported lap) are
    left out.
    """
    if "lap_time" not in lap.columns or len(lap) < 2:
        return [], []
    distances, times = monotonic_distance(lap)
    count = len(distances)
    if count < 2:
        return distances, times
    first = 0
    while first < count - 2 and distances[first] <= 0 and times[first] <= LAP_END_SECONDS:
        first += 1
    start = 0 < distances[first] <= LAP_END_METERS and 0 < times[first] <= LAP_END_SECONDS
    if not start:
        first = 0
    end_distance, end_time = lap_length(lap), official_lap_time(lap)
    last = count
    if end_distance > 0 and end_time > 0:
        while (last - 2 > first and (times[last - 1] >= end_time or distances[last - 1] >= end_distance)
               and -LAP_END_OVERSHOOT <= end_distance - distances[last - 1] <= LAP_END_METERS):
            last -= 1
    end = 0 < end_distance - distances[last - 1] <= LAP_END_METERS and 0 < end_time - times[last - 1] <= LAP_END_SECONDS
    if not end:
        last = count
    if not start and not end:
        return distances, times
    return (_padded(distances[first:last], 0.0 if start else None, end_distance if end else None),
            _padded(times[first:last], 0.0 if start else None, end_time if end else None))


def _padded(values: Sequence[float], first: float | None, last: float | None) -> Sequence[float]:
    """Values with a value added before and after (None: not added), packed array kept packed"""
    head = [first] if first is not None else []
    tail = [last] if last is not None else []
    if isinstance(values, array):
        return array(values.typecode, head) + values + array(values.typecode, tail)
    return [*head, *values, *tail]


def same_circuit(reference: LapData, lap: LapData) -> bool:
    """Whether lap was driven on the circuit of reference lap: same game track name & length when recorded

    Track names are compared only between laps recorded by the app (game names, not MoTeC venue names).
    An imported log measures driven distance: its length may be up to 10% off (see distance_scale).
    """
    recorded = "combo" in reference.meta and "combo" in lap.meta
    names = str(reference.meta.get("track", "")), str(lap.meta.get("track", ""))
    if recorded and all(names) and names[0] != names[1]:
        return False
    lengths = lap_length(reference), lap_length(lap)
    if all(lengths):
        return abs(lengths[0] / lengths[1] - 1) <= (DISTANCE_SCALE_MIN if recorded else DISTANCE_SCALE_MAX)
    return True


def distance_scale(reference: LapData, compare: LapData) -> float:
    """Factor bringing compared lap distances to reference lap length, 1 if lengths match

    Recorded laps use track distance (same length every lap). An imported log may use driven
    distance, a bit longer or shorter: its distances are scaled so corners line up. Lap lengths are
    lap end distances (track length once lap reaches the line, see lap_end_distance). Lengths more
    than 10% apart are not the same lap (cut short): left unscaled.
    """
    if len(reference) < 2 or len(compare) < 2 or same_track_distance(reference.meta, compare.meta):
        return 1.0
    return length_ratio(lap_end_distance(reference), lap_end_distance(compare))


def same_track_distance(reference_info: Mapping, compare_info: Mapping) -> bool:
    """Whether both laps were recorded by the app on the same track length (game track distance: never scaled,
    even if one lap stops before the line)"""
    if "combo" not in reference_info or "combo" not in compare_info:
        return False
    length = reference_info.get("track_length")
    return (isinstance(length, (int, float)) and not isinstance(length, bool) and length > 0
            and compare_info.get("track_length") == length)


def length_ratio(reference_end: float, compare_end: float) -> float:
    """Reference lap end distance over compared lap end distance, 1 if within DISTANCE_SCALE_TOLERANCE (same
    length) or beyond DISTANCE_SCALE_MAX (lap cut short)"""
    if reference_end <= 0 or compare_end <= 0:
        return 1.0
    ratio = reference_end / compare_end
    return ratio if DISTANCE_SCALE_TOLERANCE < abs(ratio - 1) < DISTANCE_SCALE_MAX else 1.0


def lap_end_distance(lap: LapData) -> float:
    """Lap distance at lap end: track length if lap reaches the line (see lap_time_curve), else last sample going
    forward, 0 if no sample"""
    distances = lap_time_curve(lap)[0] if "lap_time" in lap.columns else ()
    if not len(distances) and len(lap):
        distances = increasing_samples(lap.distance)[1]
    return distances[-1] if len(distances) else 0.0


def compute_delta(reference: LapData, compare: LapData) -> list[tuple[float, float]]:
    """Time delta (compare - reference) along distance, positive = compare slower, empty if a lap has no lap time

    Compared lap distances scaled to reference lap length if they differ (see distance_scale). Both laps from
    line to line (see lap_time_curve): delta at lap end is the lap time gap.
    """
    ref_dist, ref_time = lap_time_curve(reference)
    return delta_to_curve(ref_dist, ref_time, compare, distance_scale(reference, compare))


def delta_to_curve(ref_dist: Sequence[float], ref_time: Sequence[float], compare: LapData,
                   scale: float = 1.0) -> list[tuple[float, float]]:
    """Time delta of compared lap against a lap time curve (reference distances & times, ideal lap...),
    compared lap distances multiplied by scale (reference lap length), one point per lap_time_curve point"""
    cmp_dist, cmp_time = lap_time_curve(compare)
    if len(ref_dist) < 2 or not cmp_dist:
        return []
    if scale != 1.0:
        cmp_dist = [distance * scale for distance in cmp_dist]
    return [
        (distance, lap_time - interpolate(ref_dist, ref_time, distance))
        for distance, lap_time in zip(cmp_dist, cmp_time)
    ]


def delta_rate(distances: Sequence[float], deltas: Sequence[float], window: float = 40.0) -> list[float]:
    """Time lost (positive) or gained per 100 m along delta, measured over window meters (shorter at lap start
    & end: over the part of window inside lap)"""
    if len(distances) < 2:
        return [0.0] * len(distances)
    half = window / 2
    first, last = distances[0], distances[-1]
    rates = []
    for distance in distances:
        low, high = max(distance - half, first), min(distance + half, last)
        rates.append((interpolate(distances, deltas, high) - interpolate(distances, deltas, low)) / (high - low) * 100
                     if high > low else 0.0)
    return rates


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
        distances, times = lap_time_curve(lap)
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
    """Sector 1, 2, 3 times, official times from lap info if recorded, else from samples (empty without lap time)"""
    official = official_sector_times(lap)
    if official:
        return official
    bounds = sector_bounds(lap)
    distances, times = lap_time_curve(lap)
    if not bounds or len(distances) < 2:
        return []
    t1, t2 = (interpolate(distances, times, bound) for bound in bounds)
    total = official_lap_time(lap) or lap.lap_time
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
    xs: Sequence[float], ys: Sequence[float], start: float, end: float, buckets: int,
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


def csv_number(value: float, decimal: str = ".") -> str:
    """Number with up to 4 decimals, locale decimal separator"""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", decimal) if decimal != "." else text


def resampled_columns(grid: Sequence[float], series: Sequence[tuple[Sequence[float], Sequence[float]]],
                      ) -> list[list[float | None]]:
    """Each series (distances & values by increasing distance) at grid distances, None outside series"""
    from .corner_analysis import resample_sorted

    columns: list[list[float | None]] = []
    for xs, ys in series:
        if len(xs) < 2:
            columns.append([None] * len(grid))
            continue
        low, high = bisect_left(grid, xs[0]), bisect_right(grid, xs[-1])
        inside: list[float | None] = list(resample_sorted(xs, ys, grid[low:high]))  # one pass, no search per point
        columns.append([None] * low + inside + [None] * (len(grid) - high))
    return columns


def export_series_csv(filename: str, header: list[str], start: float, end: float,
                      series: Sequence[tuple[Sequence[float], Sequence[float]]], decimal: str = ".",
                      step: float = 1.0) -> str:
    """Series resampled every step (meter, or seconds on time base) from start to end & written to CSV (worker
    process job: page thread does no resampling), returns error text ("" if written)"""
    if step == 1.0:
        grid = [float(meter) for meter in range(max(math.ceil(start), 0), int(end) + 1)]
    else:
        first = max(math.ceil(start / step - 1e-9), 0)
        grid = [round(index * step, 6) for index in range(first, int(end / step + 1e-9) + 1)]
    return write_lap_csv(filename, header, grid, resampled_columns(grid, series), decimal)


def write_lap_csv(filename: str, header: list[str], grid: list[float], columns: list[list[float | None]],
                  decimal: str = ".") -> str:
    """Write resampled lap values to CSV (decimal comma: semicolon separator, for Excel), returns error text

    Written to a temporary file renamed once complete: job stopped at app exit leaves no partial file.
    """
    delimiter = ";" if decimal == "," else ","
    temporary = f"{filename}.tmp"
    try:
        with open(temporary, "w", newline="", encoding="utf-8-sig") as file:  # BOM: Excel reads UTF-8
            writer = csv.writer(file, delimiter=delimiter)
            writer.writerow(header)
            for index, distance in enumerate(grid):
                writer.writerow([csv_number(distance, decimal), *(
                    "" if column[index] is None else csv_number(column[index], decimal)  # type: ignore[arg-type]
                    for column in columns)])
        os.replace(temporary, filename)
    except OSError as error:
        logger.error("LAP CSV: unable to export %s: %s", filename, error)
        with suppress(OSError):
            os.remove(temporary)
        return error.strerror or str(error)
    return ""
