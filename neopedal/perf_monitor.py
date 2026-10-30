#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
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

import gc
import logging
import threading
from collections.abc import Callable
from contextlib import suppress
from functools import wraps
from time import monotonic, perf_counter
from typing import TYPE_CHECKING, Any, NamedTuple

import psutil

if TYPE_CHECKING:
    from .api_connector import ConnectorHealth

logger = logging.getLogger(__name__)


class PerfStats(NamedTuple):
    """Performance stats of a widget event (milliseconds)"""

    name: str
    event: str
    calls: int
    rate: float  # calls per second
    average: float
    maximum: float
    total: float


STALL_INTERVAL = 0.025  # seconds between main thread checks while monitoring
STALL_THRESHOLD = 0.05  # seconds a check came late: main thread blocked (window & overlays frozen)
SLOW_CALL = 0.016  # seconds: UI thread callback longer than a frame (60 Hz) reported
SLOW_CALL_LOG_INTERVAL = 60.0  # seconds between warnings of the same slow callback


class PerfMonitor:
    """Widget performance monitor (update & paint time), disabled by default

    While enabled, also records main thread stalls (event loop blocked longer than STALL_THRESHOLD)
    and Python garbage collection pauses, as events of "main_thread" and "python".
    """

    enabled = False
    _data: dict[tuple[str, str], list[float]] = {}  # (name, event): [calls, total, max]
    _start_time = monotonic()
    # Records come from several threads at once (GUI events, GC callback on any thread, stall timer) while stats
    # & reset read or replace the data: samples would be lost or counted on a dropped dict without a lock
    _lock = threading.Lock()

    @classmethod
    def set_enabled(cls, enabled: bool):
        """Enable or disable monitoring, reset data when enabled"""
        if enabled and not cls.enabled:
            cls.reset()
        cls.enabled = enabled
        _gc_probe.set_enabled(enabled)
        _stall_probe.set_enabled(enabled)

    @classmethod
    def reset(cls):
        """Reset data"""
        with cls._lock:
            cls._data = {}
            cls._start_time = monotonic()

    @classmethod
    def record(cls, name: str, event: str, seconds: float):
        """Record event time (any thread)"""
        with cls._lock:
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
        with cls._lock:
            duration = max(monotonic() - cls._start_time, 0.001)
            rows = [(key, tuple(values)) for key, values in cls._data.items()]
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
            for (name, event), (calls, total, peak) in rows
        ]
        output.sort(key=lambda item: item.total, reverse=True)
        return output


class _GcProbe:
    """Python garbage collection pauses (any thread), callback registered only while monitoring"""

    def __init__(self):
        self._start = 0.0

    def set_enabled(self, enabled: bool):
        registered = self._callback in gc.callbacks
        if enabled and not registered:
            gc.callbacks.append(self._callback)
        elif not enabled and registered:
            gc.callbacks.remove(self._callback)

    def _callback(self, phase: str, _info: dict):
        if phase == "start":
            self._start = perf_counter()
        elif self._start:
            PerfMonitor.record("python", "garbage collection", perf_counter() - self._start)
            self._start = 0.0


class _StallProbe:
    """Main thread stalls: a timer checked every STALL_INTERVAL, late by more than STALL_THRESHOLD = blocked"""

    def __init__(self):
        self._timer = None
        self._last = 0.0

    def set_enabled(self, enabled: bool):
        from PySide6.QtCore import QCoreApplication, Qt, QThread, QTimer

        app = QCoreApplication.instance()
        if enabled:
            if self._timer is not None or app is None or QThread.currentThread() is not app.thread():
                return
            timer = self._timer = QTimer()
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.setInterval(round(STALL_INTERVAL * 1000))
            timer.timeout.connect(self._check)
            self._last = perf_counter()
            timer.start()
        elif self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

    def _check(self):
        now = perf_counter()
        late = now - self._last - STALL_INTERVAL
        self._last = now
        if late > STALL_THRESHOLD:
            PerfMonitor.record("main_thread", "stall", late)


_gc_probe = _GcProbe()
_stall_probe = _StallProbe()
_slow_calls: dict[tuple[str, str], float] = {}  # (name, event): time of last warning


def timed_call(name: str, event: str, func: Callable[..., Any], *args) -> Any:
    """Call func(*args): time recorded while monitor is enabled, warning logged (once a minute per name & event,
    debug in between) when it took longer than SLOW_CALL (UI thread blocked for more than a frame)"""
    start = perf_counter()
    try:
        return func(*args)
    finally:
        elapsed = perf_counter() - start
        if PerfMonitor.enabled:
            PerfMonitor.record(name, event, elapsed)
        if elapsed > SLOW_CALL:
            now = monotonic()
            last = _slow_calls.get((name, event))
            warn = last is None or now - last >= SLOW_CALL_LOG_INTERVAL
            if warn:
                _slow_calls[(name, event)] = now
            logger.log(logging.WARNING if warn else logging.DEBUG,
                       "slow callback: %s %s took %.0f ms", name, event, elapsed * 1000)


def _owner_name(widget) -> str:
    """Overlay widget name, or parent overlay name for sub widget (bar, gauge)"""
    name = getattr(widget, "widget_name", None)
    if name is None:
        name = getattr(widget.window(), "widget_name", None) or type(widget).__name__
    return name


def timed_event(func: Callable, event: str, after: Callable[[Any], None] | None = None) -> Callable:
    """Wrap widget event method (self, event) to record time while monitor is enabled

    Args:
        after: called with the widget after every call, monitor enabled or not (ex. overlay paint serial count,
            see widget._base.count_paint), in the same wrapper: no second wrapper on the hot path.
    """

    @wraps(func)
    def wrapper(self, qt_event):
        if not PerfMonitor.enabled:
            if after is None:
                return func(self, qt_event)
            try:
                return func(self, qt_event)
            finally:
                after(self)
        start = perf_counter()
        try:
            return func(self, qt_event)
        finally:
            elapsed = perf_counter() - start
            try:
                name = self._perf_owner
            except AttributeError:  # first call: owner overlay found once
                name = _owner_name(self)
                with suppress(AttributeError):  # slots class: looked up every time
                    self._perf_owner = name
            PerfMonitor.record(name, event, elapsed)
            if after is not None:
                after(self)

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


class GcStats(NamedTuple):
    """Python garbage collection state"""

    frozen: int  # objects moved out of garbage collection (gc.freeze, see loader.freeze_collected)
    tracked: int  # objects waiting in generations for next collections


def gc_stats() -> GcStats:
    """Frozen & tracked object counts"""
    return GcStats(gc.get_freeze_count(), sum(gc.get_count()))


class AllocationRow(NamedTuple):
    """Python memory allocated by a source line (tracemalloc)"""

    source: str  # "file:line"
    size_kb: float
    allocations: int  # blocks allocated


def set_allocation_tracing(enabled: bool, frames: int = 1):
    """Trace Python memory allocations (off by default: slows down every allocation & uses memory itself)"""
    import tracemalloc

    if enabled and not tracemalloc.is_tracing():
        tracemalloc.start(frames)
    elif not enabled and tracemalloc.is_tracing():
        tracemalloc.stop()


def allocation_top(limit: int = 10) -> list[AllocationRow]:
    """Source lines holding most Python memory since tracing started, empty if not tracing"""
    import tracemalloc

    if not tracemalloc.is_tracing():
        return []
    snapshot = tracemalloc.take_snapshot().filter_traces((
        tracemalloc.Filter(False, tracemalloc.__file__),
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
    ))
    return [
        AllocationRow(f"{stat.traceback[0].filename}:{stat.traceback[0].lineno}", stat.size / 1024, stat.count)
        for stat in snapshot.statistics("lineno")[:limit]
    ]


class EndpointRow(NamedTuple):
    """Rest API resource status for display"""

    path: str
    state: str  # see adapter.restapi_connector.EndpointStatus
    age: float  # seconds since last answer, -1 if never
    error: str  # last error, empty if none


def connection_health() -> ConnectorHealth | None:
    """Game data connection state of connected API (shared memory, Rest API), None if not connected"""
    from .api_control import api

    return api.health()


def endpoint_rows(health: ConnectorHealth, now: float | None = None) -> list[EndpointRow]:
    """Rest API resource status rows, sorted by path"""
    if now is None:
        now = monotonic()
    return sorted(
        EndpointRow(
            path=status.path,
            state=status.state,
            age=now - status.updated if status.updated > 0 else -1.0,
            error=status.error,
        )
        for status in health.rest
    )
