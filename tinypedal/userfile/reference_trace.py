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
Reference lap trace for live comparison (telemetry comparison overlay)

Reference lap is a recorded lap of current track & class (telemetry recorder files), chosen like
in lap telemetry viewer: lap set as reference in viewer, fastest valid lap, or last recorded lap.
Its channels are resampled at fixed distance steps from lap start: overlay reads a distance window
by index (no search on each update), and lap time along distance for delta.

Laps are found & loaded in a background thread (ReferenceLoader), checked again every few seconds
(new lap recorded, reference changed in viewer).
"""

from __future__ import annotations

import logging
import math
import os
from array import array
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from typing import NamedTuple

from .corner_analysis import resample_sorted
from .lap_cache import file_stamp, load_cached_lap
from .telemetry_lap import (
    DISTANCE_SCALE_MIN,
    LapFile,
    interpolate,
    lap_files,
    lap_length,
    lap_time_curve,
    monotonic_distance,
    official_lap_time,
    read_lap_info,
    viewer_reference_name,
)

logger = logging.getLogger(__name__)

SOURCES = ("Viewer", "Best", "Last")
CHANNELS = ("speed_kph", "throttle", "brake", "steering", "gear")
STEPPED_CHANNELS = frozenset(("gear",))  # whole values: nearest value instead of a value in between
MIN_STEP = 0.25  # meters between resampled values at least
MAX_SAMPLES = 200_000  # resampled values per channel at most (very long track & small step)
CHECK_INTERVAL = 3.0  # seconds between checks of reference lap file
SHIFT_SPEED = 10.0  # km/h, neutral gear above it is a gear shift
_executor: ThreadPoolExecutor | None = None


def same_layout(lap: LapFile, track_length: float) -> bool:
    """Whether lap was recorded on current track layout: recorded track length (lap info) within 1% of game track
    length (see same_circuit), True if a length is unknown (older lap without lap info)"""
    if not track_length > 0:
        return True
    length = read_lap_info(lap.path).get("track_length")
    if not isinstance(length, (int, float)) or isinstance(length, bool) or not length > 0:
        return True
    return abs(length / track_length - 1) <= DISTANCE_SCALE_MIN


def reference_file(filepath: str, track: str, source: str, track_length: float = 0.0) -> LapFile | None:
    """Recorded lap of track folder used as reference, None if track has no lap

    Viewer: lap set as reference in lap viewer, Best: fastest valid lap, Last: newest lap (valid or not).
    Without viewer reference, fastest valid lap is used, without valid lap, newest lap.
    Game track length (0 if unknown): laps of another layout of the same track name (other track length) never
    used, None if no lap of current layout.
    """
    laps = lap_files(os.path.join(filepath, track))
    if not laps:
        return None

    def first(candidates: list[LapFile]) -> LapFile | None:  # lap info read only until a lap matches
        return next((lap for lap in candidates if same_layout(lap, track_length)), None)

    if source == "Last":
        return first(laps)
    if source == "Viewer":
        name = viewer_reference_name(filepath, track)
        found = first([lap for lap in laps if lap.filename == name]) if name else None
        if found is not None:
            return found
    timed = sorted((lap for lap in laps if lap.valid and lap.lap_time > 0), key=lambda lap: lap.lap_time)
    return first(timed) or first(laps)


class ReferenceTrace(NamedTuple):
    """Reference lap channels resampled along lap distance"""

    path: str
    stamp: tuple[int, int]  # lap file size & modification time: loaded again once changed
    name: str  # lap file name without extension
    lap_time: float  # seconds, 0 if unknown
    valid: bool
    length: float  # lap length (meters)
    step: float  # meters between resampled values
    channels: dict[str, array]  # values from lap start, one per step
    curve: tuple[Sequence[float], Sequence[float]]  # lap time curve: distances & lap times

    def at(self, channel: str, index: int) -> float:
        """Resampled value at index, wrapped around lap (index of next lap reads from lap start), nan if
        channel not recorded"""
        values = self.channels.get(channel)
        if not values:
            return math.nan
        return values[index % len(values)]

    def value(self, channel: str, distance: float) -> float:
        """Value at lap distance (wrapped around lap), nan if channel not recorded"""
        values = self.channels.get(channel)
        if not values or not math.isfinite(distance):
            return math.nan
        position = distance / self.step
        index = math.floor(position)
        count = len(values)
        first, second = values[index % count], values[(index + 1) % count]
        fraction = position - index
        if channel in STEPPED_CHANNELS:
            return first if fraction < 0.5 else second
        return first + (second - first) * fraction

    def time_at(self, distance: float) -> float:
        """Reference lap time at lap distance, nan if outside lap or lap time not recorded"""
        distances, times = self.curve
        if len(distances) < 2 or not 0 <= distance <= self.length:
            return math.nan
        return interpolate(distances, times, distance)


def held_gear(gear: float, last_gear: float, speed_kph: float) -> float:
    """Gear shown: neutral while shifting at speed (game gives 0 for a moment) keeps last gear"""
    if gear <= 0 < last_gear and speed_kph > SHIFT_SPEED:
        return last_gear
    return gear


def held_gears(gears: Sequence[float], speeds: Sequence[float]) -> list[float]:
    """Gears of lap without neutral while shifting"""
    result = []
    last = 0.0
    for gear, speed in zip(gears, speeds):
        last = held_gear(gear, last, speed)
        result.append(last)
    return result


def load_trace(filepath: str, lap: LapFile, step: float) -> ReferenceTrace:
    """Recorded lap resampled every step meters, raises OSError or ValueError"""
    stamp = file_stamp(lap.path)
    data = load_cached_lap(filepath, lap.path)
    length = lap_length(data) or max(data.distance, default=0.0)
    if not length > 0:
        raise ValueError("no lap distance")
    step = max(step, MIN_STEP, length / MAX_SAMPLES)
    count = max(int(length // step), 2)
    step = length / count  # whole steps over lap: values wrapped around lap (next lap) stay at their distance
    grid = [index * step for index in range(count)]
    channels: dict[str, array] = {}
    for name in CHANNELS:
        if name not in data.columns:
            continue
        distances, values = monotonic_distance(data, name)
        if len(distances) < 2:
            continue
        if name == "gear" and "speed_kph" in data.columns:
            values = held_gears(values, monotonic_distance(data, "speed_kph")[1])
        resampled = resample_sorted(distances, values, grid)
        if name in STEPPED_CHANNELS:
            resampled = [float(round(value)) for value in resampled]
        channels[name] = array("f", resampled)
    if not channels:
        raise ValueError("no telemetry channel")
    return ReferenceTrace(
        path=lap.path,
        stamp=stamp,
        name=data.name,
        lap_time=official_lap_time(data) or data.lap_time,
        valid=lap.valid,
        length=length,
        step=step,
        channels=channels,
        curve=lap_time_curve(data),
    )


def executor() -> ThreadPoolExecutor:
    """Single background thread shared by loaders: one lap file read at a time"""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Reference lap")
    return _executor


def stop_loading():
    """End background thread (overlay closed): check in progress finishes, next check starts a new thread"""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


class ReferenceLoader:
    """Reference trace of current track, found & loaded in background thread

    Call poll() on each update: takes result of finished check, starts next check when due.
    """

    def __init__(self, filepath: str, source: str, step: float):
        self.filepath = filepath
        self.source = source if source in SOURCES else SOURCES[0]
        self.step = step
        self.trace: ReferenceTrace | None = None
        self.version = 0  # changed when trace changes
        self.track = ""
        self.track_length = 0.0  # game track length (laps of another layout never used), 0 if unknown
        self._job: Future | None = None
        self._job_track = ""
        self._job_length = 0.0
        self._next_check = 0.0
        self._failed: tuple[str, tuple[int, int]] | None = None  # lap file not loadable (same file not retried)

    def poll(self, track: str, now: float, track_length: float = 0.0) -> bool:
        """Update with track folder name (empty if none), monotonic time & game track length (0 if unknown: last known
        length kept), True if trace changed"""
        changed = False
        if (isinstance(track_length, (int, float)) and track_length > 0  # unknown (0): last known length kept
                and abs(track_length - self.track_length) > DISTANCE_SCALE_MIN * track_length):
            if self.track_length and self.trace is not None:  # another layout of the same track name
                self.trace = None
                changed = True
            self.track_length = float(track_length)
            self._next_check = 0.0
        if track != self.track:
            self.track = track
            self._next_check = 0.0
            if self.trace is not None:
                self.trace = None
                changed = True
        job = self._job
        if job is not None and job.done():
            self._job = None
            trace = None
            if not job.cancelled():
                error = job.exception()
                if error is None:
                    trace = job.result()
                else:
                    logger.error("REFERENCE LAP: check failed: %s", error)
            if (self._job_track, self._job_length) == (self.track, self.track_length) and trace is not self.trace:
                self.trace = trace
                changed = True
        if self._job is None and track and now >= self._next_check:
            self._next_check = now + CHECK_INTERVAL
            self._job_track = track
            self._job_length = self.track_length
            self._job = executor().submit(self.find, track, self.trace, self.track_length)
        if changed:
            self.version += 1
        return changed

    def find(self, track: str, current: ReferenceTrace | None, track_length: float = 0.0) -> ReferenceTrace | None:
        """Reference trace of track: current one if same lap file unchanged, else loaded, None if no lap of current
        layout (track length) (background thread)"""
        lap = reference_file(self.filepath, track, self.source, track_length)
        if lap is None:
            return None
        try:
            stamp = file_stamp(lap.path)
        except OSError:  # removed meanwhile
            return None
        if current is not None and current.path == lap.path and current.stamp == stamp:
            return current
        if self._failed == (lap.path, stamp):
            return None
        try:
            trace = load_trace(self.filepath, lap, self.step)
        except (OSError, ValueError) as error:
            self._failed = (lap.path, stamp)
            logger.warning("REFERENCE LAP: unable to load %s: %s", lap.filename, error)
            return None
        logger.info("REFERENCE LAP: %s (%s)", trace.name, self.source)
        return trace
