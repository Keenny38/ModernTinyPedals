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
Widget performance monitor
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import wraps
from time import monotonic, perf_counter
from typing import NamedTuple

import psutil


class PerfStats(NamedTuple):
    """Performance stats of a widget event (milliseconds)"""

    name: str
    event: str
    calls: int
    rate: float  # calls per second
    average: float
    maximum: float
    total: float


class PerfMonitor:
    """Widget performance monitor (update & paint time), disabled by default"""

    enabled = False
    _data: dict[tuple[str, str], list[float]] = {}  # (name, event): [calls, total, max]
    _start_time = monotonic()

    @classmethod
    def set_enabled(cls, enabled: bool):
        """Enable or disable monitoring, reset data when enabled"""
        if enabled and not cls.enabled:
            cls.reset()
        cls.enabled = enabled

    @classmethod
    def reset(cls):
        """Reset data"""
        cls._data = {}
        cls._start_time = monotonic()

    @classmethod
    def record(cls, name: str, event: str, seconds: float):
        """Record event time"""
        data = cls._data.get((name, event))
        if data is None:
            cls._data[(name, event)] = [1, seconds, seconds]
        else:
            data[0] += 1
            data[1] += seconds
            if seconds > data[2]:
                data[2] = seconds

    @classmethod
    def stats(cls) -> list[PerfStats]:
        """Get stats, sorted by total time (most expensive first)"""
        duration = max(monotonic() - cls._start_time, 0.001)
        output = [
            PerfStats(
                name=name,
                event=event,
                calls=int(calls),
                rate=calls / duration,
                average=total / calls * 1000,
                maximum=peak * 1000,
                total=total * 1000,
            )
            for (name, event), (calls, total, peak) in list(cls._data.items())
        ]
        output.sort(key=lambda item: item.total, reverse=True)
        return output


def _owner_name(widget) -> str:
    """Overlay widget name, or parent overlay name for sub widget (bar, gauge)"""
    name = getattr(widget, "widget_name", None)
    if name is None:
        name = getattr(widget.window(), "widget_name", None) or type(widget).__name__
    return name


def timed_event(func: Callable, event: str) -> Callable:
    """Wrap widget event method (self, event) to record time while monitor is enabled"""

    @wraps(func)
    def wrapper(self, qt_event):
        if not PerfMonitor.enabled:
            return func(self, qt_event)
        start = perf_counter()
        try:
            return func(self, qt_event)
        finally:
            PerfMonitor.record(_owner_name(self), event, perf_counter() - start)

    wrapper.timed = True  # type: ignore[attr-defined]
    return wrapper


class ThreadStats(NamedTuple):
    """CPU usage of a thread (module, connector, GUI)"""

    name: str
    cpu_percent: float  # percent of one CPU core
    cpu_seconds: float  # total CPU time


class ProcessStats(NamedTuple):
    """CPU & memory usage of whole app"""

    cpu_percent: float  # percent of one CPU core
    memory_mb: float
    threads: int


def thread_names() -> dict[int, str]:
    """Native thread id: thread name"""
    names = {}
    for thread in threading.enumerate():
        if thread.native_id is None:
            continue
        name = thread.name
        if thread is threading.main_thread():
            name = "Main (GUI, widgets)"
        elif name.startswith("module:"):
            name = f"Module {name[7:].removeprefix('module_').replace('_', ' ')}"
        names[thread.native_id] = name
    return names


class ProcessMonitor:
    """Sample CPU usage per thread & memory usage, call sample() periodically"""

    def __init__(self):
        self._process = psutil.Process()
        self._last_time = monotonic()
        self._last_threads: dict[int, float] = self._thread_times()
        self._last_total = self._total_time()

    def _thread_times(self) -> dict[int, float]:
        try:
            return {thread.id: thread.user_time + thread.system_time for thread in self._process.threads()}
        except (psutil.Error, OSError):
            return {}

    def _total_time(self) -> float:
        try:
            times = self._process.cpu_times()
            return times.user + times.system
        except (psutil.Error, OSError):
            return 0.0

    def sample(self) -> tuple[ProcessStats, list[ThreadStats]]:
        """CPU usage since last sample, sorted by CPU usage"""
        now = monotonic()
        elapsed = max(now - self._last_time, 0.001)
        threads_now = self._thread_times()
        total_now = self._total_time()
        names = thread_names()
        stats = [
            ThreadStats(
                name=names.get(thread_id, f"Thread {thread_id}"),
                cpu_percent=max(cpu - self._last_threads.get(thread_id, cpu), 0.0) / elapsed * 100,
                cpu_seconds=cpu,
            )
            for thread_id, cpu in threads_now.items()
        ]
        stats.sort(key=lambda item: item.cpu_percent, reverse=True)
        try:
            memory = self._process.memory_info().rss / 1024 / 1024
        except (psutil.Error, OSError):
            memory = 0.0
        process = ProcessStats(
            cpu_percent=max(total_now - self._last_total, 0.0) / elapsed * 100,
            memory_mb=memory,
            threads=len(threads_now),
        )
        self._last_time, self._last_threads, self._last_total = now, threads_now, total_now
        return process, stats
