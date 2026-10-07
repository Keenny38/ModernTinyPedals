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
MoTeC .ld import: laps of a MoTeC log (LMU & rF2 built-in logger, files exported by this app)
converted to recorded lap files, so they can be compared in the lap telemetry viewer.

Only channels the viewer shows are read. Laps are found by "Lap Number" changes (or lap distance going
back to start, or lap time going back to 0), then each lap is resampled to one time base. Only complete laps are
imported. A log with neither (exported by this app) is one lap.
"""

from __future__ import annotations

import csv
import json
import math
import os
import time
from array import array
from bisect import bisect_left
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from itertools import pairwise
from typing import NamedTuple

from .motec_ld import Channel, LdInfo, read_ld
from .telemetry_lap import INFO_PREFIX, is_lap_file, lap_number_of, lap_time_of, lap_timestamp_of

MAX_RATE = 50  # Hz, recorder samples at most this often
MAX_LOG_SECONDS = 6 * 3600  # longer logs (or sizes made up by a broken file) read up to this time
LINE_MATCH_SECONDS = 3.0  # lap number change matched to a line crossing this close (slow channel, logger delay)
COMMENT_LAP_TIME_TOLERANCE = 1.0  # seconds, lap time of comment (lap name) used if this close to log lap time
WHEELS = ("FL", "FR", "RL", "RR")


def _speed_kph(unit: str) -> float:
    unit = unit.lower()
    if unit in ("m/s", "ms"):
        return 3.6
    if unit == "mph":
        return 1.609344
    return 1.0


def _fraction(unit: str) -> float:
    return 0.01 if unit == "%" else 1.0


def _pressure_kpa(unit: str) -> float:
    unit = unit.lower()
    if unit == "psi":
        return 6.894757
    if unit == "bar":
        return 100.0
    return 1.0


def _percent(unit: str) -> float:
    return 100.0 if unit in ("", "ratio") else 1.0


def _one(_unit: str) -> float:
    return 1.0


def _kilonewton(unit: str) -> float:
    return 0.001 if unit.lower() == "n" else 1.0


class Source(NamedTuple):
    """Recorder column read from first found MoTeC channel name, unit to scale factor"""

    column: str
    names: tuple[str, ...]
    scale: Callable[[str], float] = _one
    step: bool = False  # hold value (gear, sector) instead of linear interpolation
    wraps: bool = False  # lap distance: back to 0 at start line
    complement: bool = False  # percent of the other side (rear brake bias): 100 - value


SOURCES = (
    Source("distance", ("Lap Distance", "Lap Dist", "Distance"), wraps=True),
    Source("speed_kph", ("Ground Speed", "Speed", "Vehicle Speed"), _speed_kph),
    Source("throttle", ("Throttle Pos", "Throttle"), _fraction),
    Source("brake", ("Brake Pos", "Brake"), _fraction),
    Source("clutch", ("Clutch Pos", "Clutch"), _fraction),
    Source("steering", ("Steering Pos", "Steering"), _fraction),
    Source("gear", ("Gear",), step=True),
    Source("rpm", ("Engine RPM", "RPM")),
    Source("fuel", ("Fuel Level",)),
    *(Source(f"tyre_pres_{wheel.lower()}", (f"Tyre Pres {wheel}", f"Tyre Pressure {wheel}"), _pressure_kpa)
      for wheel in WHEELS),
    Source("pos_x", ("Pos X",)),
    Source("pos_y", ("Pos Y",)),
    Source("pos_z", ("Pos Z",)),
    Source("accel_lat", ("G Force Lat",)),
    Source("accel_long", ("G Force Long",)),
    Source("sector", ("Sector", "Current Sector"), step=True),
    Source("tc_active", ("TC Active",), step=True),
    Source("abs_active", ("ABS Active",), step=True),
    Source("battery", ("Battery Charge", "Battery Charge Level")),
    *(Source(f"brake_temp_{wheel.lower()}", (f"Brake Temp {wheel}",)) for wheel in WHEELS),
    *(Source(f"tyre_wear_{wheel.lower()}", (f"Tyre Wear {wheel}",), _percent) for wheel in WHEELS),
    *(Source(f"wheel_speed_{wheel.lower()}", (f"Wheel Speed {wheel}",), _speed_kph) for wheel in WHEELS),
    *(Source(f"ride_height_{wheel.lower()}", (f"Ride Height {wheel}",)) for wheel in WHEELS),
    *(Source(f"susp_defl_{wheel.lower()}", (f"Damper Pos {wheel}", f"Susp Pos {wheel}")) for wheel in WHEELS),
    # Tread temperature of inner, middle & outer edge (camber)
    *(Source(f"tyre_temp_{part}_{wheel.lower()}", (f"Tyre Temp {wheel} {name}",))
      for part, name in (("in", "Inner"), ("mid", "Centre"), ("out", "Outer")) for wheel in WHEELS),
    *(Source(f"tyre_load_{wheel.lower()}", (f"Tyre Load {wheel}",), _kilonewton) for wheel in WHEELS),
    Source("path_lateral", ("Path Lateral",)),
    Source("track_edge", ("Track Edge",)),
    Source("brake_bias", ("Brake Bias Rear",), complement=True),  # recorder: front percent
    Source("water_temp", ("Eng Water Temp", "Water Temp")),
    Source("oil_temp", ("Eng Oil Temp", "Oil Temp")),
)
# Tyre surface temperature: one channel (exported by this app), or average of inner, centre & outer
TYRE_TEMP_NAMES = tuple(
    (f"tyre_temp_{wheel.lower()}", f"Tyre Temp {wheel}",
     tuple(f"Tyre Temp {wheel} {part}" for part in ("Inner", "Centre", "Outer")))
    for wheel in WHEELS
)
LAP_NUMBER_NAMES = ("Lap Number", "Lap", "Laps")
LAP_TIME_NAMES = ("Lap Time",)
# Every channel read from a log (others never decoded)
USED_NAMES = frozenset(
    name.lower() for name in (
        *(name for source in SOURCES for name in source.names),
        *(name for _, single, parts in TYRE_TEMP_NAMES for name in (single, *parts)),
        *LAP_NUMBER_NAMES, *LAP_TIME_NAMES,
    )
)


class ImportedLap(NamedTuple):
    """Complete lap of MoTeC log"""

    number: int
    lap_time: float
    columns: dict[str, Sequence[float]]  # recorder columns, "lap_time" & "distance" always set
    info: dict
    finished: float = 0.0  # real time at lap end (file name date), 0 if log has no date


def sample_at(channel: Channel, seconds: float, step: bool = False, wrap_length: float = 0.0) -> float:
    """Channel value at log time, linear interpolation (or held value) between samples"""
    values = channel.values
    position = seconds * channel.frequency
    if position <= 0:
        return values[0]
    index = int(position)
    if index >= len(values) - 1:
        return values[-1]
    if step:
        return values[index]
    fraction = position - index
    low, high = values[index], values[index + 1]
    if wrap_length > 0 and low - high > wrap_length / 2:  # crossed start line between samples
        value = low + (high + wrap_length - low) * fraction
        return value - wrap_length if value >= wrap_length else value
    return low + (high - low) * fraction


def resample(
    channel: Channel, first: int, last: int, rate: int, step: bool = False, wrap_length: float = 0.0,
    scale: float = 1.0, offset: float = 0.0,
) -> array:
    """Channel values * scale + offset at time base ticks first to last (tick / rate seconds), as sample_at"""
    values = channel.values
    frequency = channel.frequency
    end = len(values) - 1
    half = wrap_length / 2
    result = array("d", bytes(8 * max(last - first, 0)))
    for slot in range(len(result)):
        position = (first + slot) / rate * frequency
        index = int(position)
        if position <= 0:
            value = values[0]
        elif index >= end:
            value = values[-1]
        elif step:
            value = values[index]
        else:
            low = values[index]
            high = values[index + 1]
            if wrap_length > 0 and low - high > half:  # crossed start line between samples
                value = low + (high + wrap_length - low) * (position - index)
                if value >= wrap_length:
                    value -= wrap_length
            else:
                value = low + (high - low) * (position - index)
        result[slot] = value * scale + offset
    return result


def first_tick(seconds: float, rate: int) -> int:
    """First time base tick at or after log time"""
    return max(math.ceil(seconds * rate - 1e-9), 0)


def estimate_track_length(distances: Sequence[float]) -> float:
    """Track length from lap distance samples: last sample before line is half a step short on average"""
    top = max(distances)
    steps = sorted(after - before for before, after in pairwise(distances) if 0 < after - before < top / 2)
    return top + (steps[len(steps) // 2] / 2 if steps else 0.0)


def line_crossings(channel: Channel, length: float) -> list[float]:
    """Log times of start line crossings, interpolated between lap distance samples"""
    values = channel.values
    times = []
    for index in range(1, len(values)):
        before, after = values[index - 1], values[index]
        if before - after > length / 2:
            to_line = max(length - before, 0.0)
            fraction = to_line / (to_line + max(after, 0.0)) if to_line + after > 0 else 0.0
            times.append((index - 1 + fraction) / channel.frequency)
    return times


def lap_time_crossings(channel: Channel) -> list[float]:
    """Log times of start line crossings from lap time going back to 0 (time since line at sample after it)"""
    values = channel.values
    times = []
    for index in range(1, len(values)):
        before, after = values[index - 1], values[index]
        if before - after > max(before / 2, 1.0):
            times.append(index / channel.frequency - max(after, 0.0))
    return times


def log_start_crossing(channel: Channel | None) -> float | None:
    """Start line crossing at log start (lap time near 0 at first sample), None if log started mid lap"""
    if channel is None or not 0 <= channel.values[0] <= 1 / channel.frequency + 0.05:
        return None
    return -channel.values[0]


def nearest(times: Sequence[float], target: float, limit: float = 1.0) -> float:
    """Nearest time to target within limit seconds (times ascending), target if none"""
    index = bisect_left(times, target)
    best = min(times[max(index - 1, 0):index + 1], key=lambda value: abs(value - target), default=target)
    return best if abs(best - target) <= limit else target


def is_worn_percent(values: Sequence[float]) -> bool:
    """Whether tyre wear channel is worn percent (going up), not remaining percent (going down)"""
    if values[-1] != values[0]:
        return values[-1] > values[0]
    return values[0] < 50  # no wear during log: new tyre is near 0% worn, 100% remaining


def find_channel(channels: dict[str, Channel], names: Sequence[str]) -> Channel | None:
    """First channel found by name (case-insensitive) with samples"""
    for name in names:
        channel = channels.get(name.lower())
        if channel is not None and channel.values:
            return channel
    return None


def lap_number(value: float) -> int:
    return int(value) if math.isfinite(value) else 0


def read_log_laps(filename: str) -> tuple[LdInfo, Iterator[ImportedLap]]:
    """Log info & its complete laps, each lap resampled when reached (a long log is never resampled whole)

    Raises OSError or ValueError if file cannot be read.
    """
    info, channel_list = read_ld(filename, USED_NAMES)
    channels = {channel.name.lower(): channel for channel in channel_list}
    sources = [(source, find_channel(channels, source.names)) for source in SOURCES]
    found = [(source, channel) for source, channel in sources if channel is not None]
    lap_number_channel = find_channel(channels, LAP_NUMBER_NAMES)
    lap_time_channel = find_channel(channels, LAP_TIME_NAMES)
    if not found and lap_time_channel is None:
        raise ValueError("no telemetry channel")
    # One time base at the fastest used channel rate (max 50 Hz), over channels laps are found from (a channel
    # longer than others, or a broken size, never makes the time base longer)
    rate = min(max((channel.frequency for _, channel in found), default=MAX_RATE), MAX_RATE)
    distance_channel = next((channel for source, channel in found if source.wraps), None)
    timing = [channel for channel in (lap_number_channel, lap_time_channel, distance_channel) if channel is not None]
    duration = max(len(channel.values) / channel.frequency for channel in timing or [channel for _, channel in found])
    count = int(min(duration, MAX_LOG_SECONDS) * rate)
    if count < 2:
        raise ValueError("log too short")

    track_length = estimate_track_length(distance_channel.values) if distance_channel is not None else 0.0
    crossings = line_crossings(distance_channel, track_length) if distance_channel is not None else []
    wear_worn = {source.column for source, channel in found
                 if source.column.startswith("tyre_wear_") and is_worn_percent(channel.values)}

    def build(number: int, first: int, last: int, lap_time: float, start_time: float | None,
              rebase: bool = False) -> ImportedLap:
        """Lap between time base ticks, distance from 0 at lap start if rebase (odometer distance)"""
        start = first / rate if start_time is None else start_time
        columns: dict[str, Sequence[float]] = {}
        for source, channel in found:
            scale = source.scale(channel.unit)
            offset = 0.0
            if source.complement or source.column in wear_worn:  # LMU logs worn %, recorder remaining %
                scale, offset = -scale, 100.0
            wrap_length = track_length if source.wraps and crossings else 0.0
            if source.wraps and rebase:
                offset = -sample_at(channel, start) * scale
            columns[source.column] = resample(channel, first, last, rate, source.step, wrap_length, scale, offset)
        for column, single, _ in TYRE_TEMP_NAMES:
            tyre_temp = find_channel(channels, (single,))
            inner, middle, outer = (columns.get(column.replace("tyre_temp_", f"tyre_temp_{part}_"))
                                    for part in ("in", "mid", "out"))
            if tyre_temp is not None:
                columns[column] = resample(tyre_temp, first, last, rate)
            elif inner is not None and middle is not None and outer is not None:  # average of tread edges & centre
                columns[column] = array("d", ((a + b + c) / 3 for a, b, c in zip(inner, middle, outer)))
        finished = start + lap_time + info.timestamp if info.timestamp > 0 else 0.0
        return build_lap(info, filename, number, rate, columns, first, last, lap_time, start, finished)

    def laps() -> Iterator[ImportedLap]:
        # Start line crossings: from lap distance going back to 0, else from lap time going back to 0 (odometer
        # distance: rebased at the line, not at the late lap number change)
        line = crossings or (lap_time_crossings(lap_time_channel) if lap_time_channel is not None else [])
        if lap_number_channel is not None:  # lap start & end at line crossing (between samples), else at lap change
            values = lap_number_channel.values
            frequency = lap_number_channel.frequency
            starts = [(index / frequency, lap_number(values[index]))
                      for index in range(1, len(values)) if values[index] > values[index - 1]]
            for (change, number), (next_change, _) in pairwise(starts):
                # Lap number changes up to a sample (logger rate) & a logger delay after the line: lap samples from
                # line to line, else lap distance zero & lap time origin would be meters past the line
                start_time = nearest(line, change, LINE_MATCH_SECONDS)
                end_time = nearest(line, next_change, LINE_MATCH_SECONDS)
                first, last = first_tick(start_time, rate), first_tick(end_time, rate)
                if last > count:
                    break
                yield build(number, first, last, end_time - start_time, start_time, rebase=not crossings)
            return
        if not line:
            if lap_time_channel is not None:  # single lap file (exported by this app): whole log is one lap
                yield single_lap()
            return
        log_start = log_start_crossing(lap_time_channel)
        if log_start is not None and line[0] - log_start > 1.0:  # log started at line: first lap complete
            line = [log_start, *line]
        for number, (start_time, end_time) in enumerate(pairwise(line), 1):
            first, last = first_tick(start_time, rate), first_tick(end_time, rate)
            if last > count:
                break
            yield build(number, first, last, end_time - start_time, start_time, rebase=not crossings)

    def single_lap() -> ImportedLap:
        """Lap number, lap time & date from comment (lap name, written by export) if it matches the log"""
        assert lap_time_channel is not None
        lap_time = lap_time_channel.values[-1]
        named_time = lap_time_of(f"{info.comment}.csv")
        named = named_time > 0 and abs(named_time - lap_time) <= COMMENT_LAP_TIME_TOLERANCE
        lap = build(lap_number_of(f"{info.comment}.csv") if named else 1, 0, count,
                    named_time if named else lap_time, None)
        finished = lap_timestamp_of(info.comment) if named else 0.0
        if finished > 0:
            lap.info["finished"] = round(finished, 3)
            lap = lap._replace(finished=finished)
        return lap

    return info, (lap for lap in laps() if lap.lap_time > 0 and "distance" in lap.columns)


def import_laps(filename: str) -> tuple[LdInfo, list[ImportedLap]]:
    """Complete laps of MoTeC .ld file, raises OSError or ValueError if file cannot be read"""
    info, laps = read_log_laps(filename)
    return info, list(laps)


def build_lap(
    info: LdInfo, filename: str, number: int, rate: int, columns: dict[str, Sequence[float]],
    first: int, last: int, lap_time: float, start_time: float | None = None, finished: float = 0.0,
) -> ImportedLap:
    """Lap of columns resampled between time base ticks first & last, with log time & lap time from start_time
    (first tick time if None), finished: real time at lap end if known"""
    times = [index / rate for index in range(first, last)]
    if start_time is None:
        start_time = first / rate
    lap_columns: dict[str, Sequence[float]] = {
        "time": array("d", (round(t, 3) for t in times)),
        "lap_time": array("d", (round(max(t - start_time, 0.0), 3) for t in times)),
    }
    lap_columns.update(columns)
    if "distance" not in lap_columns and "speed_kph" in lap_columns:  # no distance channel: from speed
        distance = 0.0
        distances = array("d")
        for speed in lap_columns["speed_kph"]:
            distances.append(distance)
            distance += speed / 3.6 / rate
        lap_columns["distance"] = distances
    lap_info = {
        "kind": "lap",
        "source": "MoTeC",
        "imported_from": os.path.basename(filename),
        "lap_number": number,
        "track": info.venue,
        "vehicle": info.vehicle,
        "driver": info.driver,
        "session": info.session,
    }
    if finished > 0:  # lap end from log date (lap viewer finds replay recorded then)
        lap_info["finished"] = round(finished, 3)
    if lap_columns.get("distance"):  # rounded up: last sample never past track length
        lap_info["track_length"] = math.ceil(round(max(lap_columns["distance"]) * 10, 6)) / 10
    return ImportedLap(number, lap_time, lap_columns, {key: value for key, value in lap_info.items() if value != ""},
                       finished)


def lap_file_name(lap: ImportedLap, timestamp: float) -> str:
    """Recorded lap file name of imported lap (same pattern as recorder), dated at lap end if known, else timestamp"""
    minutes, seconds = divmod(lap.lap_time, 60)
    date = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(lap.finished or timestamp))
    return f"{date} lap{lap.number:03d} {int(minutes)}m{seconds:06.3f}s.csv"


def save_imported_lap(lap: ImportedLap, folder: str, timestamp: float) -> str:
    """Save imported lap as recorded lap file, returns file path

    Written to a temporary file renamed once complete: import stopped at app exit leaves no partial lap.
    """
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, lap_file_name(lap, timestamp))
    temporary = f"{path}.tmp"
    header = list(lap.columns)
    try:
        with open(temporary, "w", newline="", encoding="utf-8") as file:
            file.write(INFO_PREFIX + json.dumps(lap.info) + "\n")
            writer = csv.writer(file)
            writer.writerow(header)
            for row in zip(*(lap.columns[name] for name in header)):
                writer.writerow([round(value, 4) for value in row])
        os.replace(temporary, path)
    except OSError:
        with suppress(OSError):
            os.remove(temporary)
        raise
    return path


def undated_name(filename: str) -> str:
    """Lap file name without its date (lap number & time), empty if not dated"""
    return filename[20:] if lap_timestamp_of(filename) > 0 else ""


def import_ld_file(filename: str, folder: str) -> list[str]:
    """Import complete laps of .ld file to folder (one sub folder per log), returns lap file paths

    Laps already imported from the log (same lap number & time) are not written again: their paths are returned.
    """
    _, laps = read_log_laps(filename)
    target = os.path.join(folder, os.path.splitext(os.path.basename(filename))[0])
    timestamp = os.path.getmtime(filename)
    try:
        present = {undated_name(name): os.path.join(target, name) for name in os.listdir(target) if is_lap_file(name)}
    except OSError:  # first import of log
        present = {}
    paths = []
    for lap in laps:
        key = undated_name(lap_file_name(lap, timestamp))
        if key not in present:
            present[key] = save_imported_lap(lap, target, timestamp)
        paths.append(present[key])
    return paths
