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

Channels are resampled to one time base, then split into laps by "Lap Number" changes
(or by lap distance going back to start). Only complete laps are imported.
"""

from __future__ import annotations

import csv
import json
import os
import time
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import NamedTuple

from .motec_ld import Channel, LdInfo, read_ld
from .telemetry_lap import INFO_PREFIX

MAX_RATE = 50  # Hz, recorder samples at most this often
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


class Source(NamedTuple):
    """Recorder column read from first found MoTeC channel name, unit to scale factor"""

    column: str
    names: tuple[str, ...]
    scale: Callable[[str], float] = _one
    step: bool = False  # hold value (gear, sector) instead of linear interpolation
    wraps: bool = False  # lap distance: back to 0 at start line


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
    Source("battery", ("Battery Charge", "Battery Charge Level")),
    *(Source(f"brake_temp_{wheel.lower()}", (f"Brake Temp {wheel}",)) for wheel in WHEELS),
    *(Source(f"tyre_wear_{wheel.lower()}", (f"Tyre Wear {wheel}",), _percent) for wheel in WHEELS),
    *(Source(f"wheel_speed_{wheel.lower()}", (f"Wheel Speed {wheel}",), _speed_kph) for wheel in WHEELS),
    *(Source(f"ride_height_{wheel.lower()}", (f"Ride Height {wheel}",)) for wheel in WHEELS),
    *(Source(f"susp_defl_{wheel.lower()}", (f"Damper Pos {wheel}", f"Susp Pos {wheel}")) for wheel in WHEELS),
)
# Tyre surface temperature: one channel (exported by this app), or average of inner, centre & outer
TYRE_TEMP_NAMES = tuple(
    (f"tyre_temp_{wheel.lower()}", f"Tyre Temp {wheel}",
     tuple(f"Tyre Temp {wheel} {part}" for part in ("Inner", "Centre", "Outer")))
    for wheel in WHEELS
)
LAP_NUMBER_NAMES = ("Lap Number", "Lap", "Laps")


class ImportedLap(NamedTuple):
    """Complete lap of MoTeC log"""

    number: int
    lap_time: float
    columns: dict[str, list[float]]  # recorder columns, "lap_time" & "distance" always set
    info: dict


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


def nearest(times: list[float], target: float, limit: float = 1.0) -> float:
    """Nearest time to target within limit seconds, target if none"""
    best = min(times, key=lambda value: abs(value - target), default=target)
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


def lap_starts(times: list[float], lap_numbers: list[float] | None, distances: list[float] | None) -> list[int]:
    """Sample indexes where a new lap starts"""
    starts = []
    if lap_numbers:
        for index in range(1, len(times)):
            if lap_numbers[index] > lap_numbers[index - 1]:
                starts.append(index)
        return starts
    if distances:
        top = max(distances)
        for index in range(1, len(times)):
            if distances[index - 1] - distances[index] > top / 2:  # back to start line
                starts.append(index)
    return starts


def import_laps(filename: str) -> tuple[LdInfo, list[ImportedLap]]:
    """Complete laps of MoTeC .ld file, raises OSError or ValueError if file cannot be read"""
    info, channel_list = read_ld(filename)
    channels = {channel.name.lower(): channel for channel in channel_list}
    sources = [(source, find_channel(channels, source.names)) for source in SOURCES]
    found = [(source, channel) for source, channel in sources if channel is not None]
    lap_time_channel = find_channel(channels, ("Lap Time",))
    if not found and lap_time_channel is None:
        raise ValueError("no telemetry channel")
    # One time base at the fastest used channel rate (max 50 Hz), over the longest channel
    used = [channel for _, channel in found]
    rate = min(max(channel.frequency for channel in used), MAX_RATE) if used else MAX_RATE
    duration = max(len(channel.values) / channel.frequency for channel in channel_list if channel.frequency > 0)
    count = int(duration * rate)
    times = [index / rate for index in range(count)]
    if count < 2:
        raise ValueError("log too short")

    distance_channel = next((channel for source, channel in found if source.wraps), None)
    track_length = estimate_track_length(distance_channel.values) if distance_channel is not None else 0.0
    columns: dict[str, list[float]] = {}
    for source, channel in found:
        factor = source.scale(channel.unit)
        wrap_length = track_length if source.wraps else 0.0
        values = [sample_at(channel, t, source.step, wrap_length) * factor for t in times]
        if source.column.startswith("tyre_wear_") and is_worn_percent(channel.values):
            values = [100.0 - value for value in values]  # LMU logs worn %, recorder remaining %
        columns[source.column] = values
    for column, single, parts in TYRE_TEMP_NAMES:
        tyre_temp = find_channel(channels, (single,))
        if tyre_temp is not None:
            columns[column] = [sample_at(tyre_temp, t) for t in times]
            continue
        part_channels = [find_channel(channels, (name,)) for name in parts]
        if all(part is not None for part in part_channels):
            columns[column] = [
                sum(sample_at(part, t) for part in part_channels if part is not None) / len(part_channels)
                for t in times
            ]

    lap_number_channel = find_channel(channels, LAP_NUMBER_NAMES)
    lap_numbers = [sample_at(lap_number_channel, t, True) for t in times] if lap_number_channel else None
    if lap_numbers is None and lap_time_channel is not None and "distance" in columns:
        # Single lap file (exported by this app): whole log is one lap
        lap_time = lap_time_channel.values[-1]
        laps = [build_lap(info, filename, 1, times, columns, 0, count, lap_time)] if lap_time > 0 else []
        return info, laps
    starts = lap_starts(times, lap_numbers, columns.get("distance"))
    # Lap start & end at start line crossing (between samples), else at lap number change
    crossings = line_crossings(distance_channel, track_length) if distance_channel is not None else []
    laps = []
    for first, last in pairwise(starts):
        number = int(lap_numbers[first]) if lap_numbers else len(laps) + 1
        start_time = nearest(crossings, times[first])
        lap_time = nearest(crossings, times[last]) - start_time
        laps.append(build_lap(info, filename, number, times, columns, first, last, lap_time, start_time))
    return info, [lap for lap in laps if "distance" in lap.columns]


def build_lap(
    info: LdInfo, filename: str, number: int, times: list[float], columns: dict[str, list[float]],
    first: int, last: int, lap_time: float, start_time: float | None = None,
) -> ImportedLap:
    """Lap columns (with log time & lap time from start_time, first sample time if None) between sample indexes"""
    if start_time is None:
        start_time = times[first]
    lap_columns = {
        "time": [round(t, 3) for t in times[first:last]],
        "lap_time": [round(max(t - start_time, 0.0), 3) for t in times[first:last]],
    }
    for column, values in columns.items():
        lap_columns[column] = values[first:last]
    if "distance" not in lap_columns and "speed_kph" in lap_columns:  # no distance channel: from speed
        distance = 0.0
        distances = []
        step = times[1] - times[0] if len(times) > 1 else 0.0
        for speed in lap_columns["speed_kph"]:
            distances.append(distance)
            distance += speed / 3.6 * step
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
    if lap_columns.get("distance"):
        lap_info["track_length"] = round(max(lap_columns["distance"]), 1)
    return ImportedLap(number, lap_time, lap_columns, {key: value for key, value in lap_info.items() if value != ""})


def lap_file_name(lap: ImportedLap, timestamp: float) -> str:
    """Recorded lap file name of imported lap (same pattern as recorder)"""
    minutes, seconds = divmod(lap.lap_time, 60)
    date = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(timestamp))
    return f"{date} lap{lap.number:03d} {int(minutes)}m{seconds:06.3f}s.csv"


def save_imported_lap(lap: ImportedLap, folder: str, timestamp: float) -> str:
    """Save imported lap as recorded lap file, returns file path"""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, lap_file_name(lap, timestamp))
    header = list(lap.columns)
    with open(path, "w", newline="", encoding="utf-8") as file:
        file.write(INFO_PREFIX + json.dumps(lap.info) + "\n")
        writer = csv.writer(file)
        writer.writerow(header)
        for row in zip(*(lap.columns[name] for name in header)):
            writer.writerow([round(value, 4) for value in row])
    return path


def import_ld_file(filename: str, folder: str) -> list[str]:
    """Import complete laps of .ld file to folder (one sub folder per log), returns lap file paths"""
    _, laps = import_laps(filename)
    target = os.path.join(folder, os.path.splitext(os.path.basename(filename))[0])
    timestamp = os.path.getmtime(filename)
    return [save_imported_lap(lap, target, timestamp) for lap in laps]
