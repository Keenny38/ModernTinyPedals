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
Background jobs of pages: file reading & heavy work off the UI thread, result handed back on the UI thread

Rule of pages: no file read or work longer than a frame (16 ms) on the UI thread. A page runs such work with
BackgroundJobs.run(name, work, done): work runs on a shared pool of worker threads, done(result) is called on
the UI thread.
"""

from __future__ import annotations

import inspect
import logging
import threading
import weakref
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from functools import partial
from time import monotonic, perf_counter
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, Slot
from shiboken6 import isValid

logger = logging.getLogger(__name__)

SLOW_JOB = 2.0  # seconds, jobs longer than this are logged (a page waits for their result)
MAX_WORKERS = 4  # worker threads shared by every page
IDLE_SECONDS = 30.0  # worker thread left without job this long ends (started again when needed)
WORKER_NAME = "Page jobs"


class JobCancelled(Exception):
    """Raised by JobToken.check in a cancelled job: job ends, nothing handed over"""


class JobToken:
    """Cancellation of one job, given to work started with run(..., cancellable=True)

    Cancelled when a newer job of the same key is started, or by cancel(key) / cancel_all() (page closed).
    Work checks it between steps: token.check() raises JobCancelled, or token.cancelled read.
    """

    __slots__ = ("_cancelled",)

    def __init__(self):
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        self._cancelled = True

    def check(self):
        """Raise JobCancelled if cancelled"""
        if self._cancelled:
            raise JobCancelled


def _weak(callback: Callable | None) -> Callable[[], Callable | None]:
    """Callback held weakly when a bound method: no reference cycle page <-> jobs (a page without parent is then
    freed at once on the UI thread, never by the garbage collector on a job thread)"""
    if callback is None:
        return lambda: None
    if inspect.ismethod(callback):
        return weakref.WeakMethod(callback)
    return lambda: callback


class _Job:
    """Job waiting, running or done (outcome), until handed over on the UI thread"""

    __slots__ = ("cancellable", "done", "failed", "key", "label", "name", "outcome", "owner", "serial", "token",
                 "work")

    def __init__(self, serial: int, key: str | None, name: str, label: str, work: Callable, done: Callable,
                 failed: Callable, cancellable: bool, owner: weakref.ref):
        self.serial = serial
        self.key = key
        self.name = name
        self.label = label
        self.work: Callable | None = work
        self.done = done
        self.failed = failed
        self.cancellable = cancellable
        self.owner = owner
        self.token = JobToken()
        self.outcome: tuple | None = None

    def release(self):
        """Work & result freed (called on the UI thread: objects they hold are never freed on a worker thread)"""
        self.work = None
        self.outcome = None


def _execute(job: _Job):
    """Run on a worker thread: outcome stored on job (no local reference kept), job sent to the UI thread"""
    work = job.work
    if job.token.cancelled or work is None:
        job.outcome = (False, JobCancelled())
    else:
        thread = threading.current_thread()
        thread.name = f"{job.label} {job.name}"
        start = perf_counter()
        try:
            job.outcome = (True, work(job.token) if job.cancellable else work())
        except BaseException as error:  # handed to failed callback or logged on UI thread
            job.outcome = (False, error)
        seconds = perf_counter() - start
        if seconds > SLOW_JOB and not job.token.cancelled:
            logger.info("%s: %s took %.1f s", job.label, job.name, seconds)
        thread.name = WORKER_NAME
    work = None
    courier = _courier
    if courier is not None:
        with suppress(RuntimeError):  # app closing: courier deleted, result dropped
            courier.arrived.emit(job)


class _WorkerPool:
    """Daemon worker threads (app exit never waits for a job), at most size, idle ones end after a while"""

    def __init__(self, size: int):
        self.size = size
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._queue: deque[_Job] = deque()
        self._workers = 0
        self._idle = 0
        self._started = 0

    @property
    def workers(self) -> int:
        return self._workers

    def submit(self, job: _Job):
        with self._lock:
            self._queue.append(job)
            start = len(self._queue) > self._idle and self._workers < self.size
            if start:
                self._workers += 1
                self._started += 1
                number = self._started
            else:
                self._wake.notify()
        if start:
            threading.Thread(target=self._work, daemon=True, name=f"{WORKER_NAME} {number}").start()

    def _work(self):
        while True:
            with self._lock:
                deadline = monotonic() + IDLE_SECONDS
                while not self._queue:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        self._workers -= 1
                        return
                    self._idle += 1
                    self._wake.wait(remaining)
                    self._idle -= 1
                job = self._queue.popleft()
            _execute(job)
            del job


_POOL = _WorkerPool(MAX_WORKERS)


class _Courier(QObject):
    """Jobs done on worker threads handed to their BackgroundJobs on the UI thread (held weakly: a page is never
    kept alive, nor freed, by a worker thread)"""

    arrived = Signal(object)

    def __init__(self):
        super().__init__()
        self.arrived.connect(self.hand_over, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def hand_over(self, job: _Job):
        owner = job.owner()
        if owner is None or not isValid(owner):  # jobs object deleted (page closed): result dropped
            job.release()
            return
        owner._deliver(job)


_courier: _Courier | None = None


def _get_courier() -> _Courier:
    global _courier
    if _courier is None or not isValid(_courier):
        _courier = _Courier()
        app = QCoreApplication.instance()
        if app is not None and _courier.thread() is not app.thread():
            _courier.moveToThread(app.thread())
    return _courier


def _owner_gone(live: dict[int, _Job], pending: dict[str, _Job], _ref: weakref.ref):
    """Jobs object freed: its jobs cancelled (waiting ones never run)"""
    for job in live.values():
        job.token.cancel()
    pending.clear()


class BackgroundJobs(QObject):
    """Jobs of a page run on shared worker threads, done callbacks called on the UI thread

    Jobs started with a key run one at a time: a job started while one of its key runs waits, replacing any job
    of that key already waiting (only the newest waiting one runs). The running job is then superseded: its token
    is cancelled and its result dropped (ex. page reloaded twice in a row: only the last reload is handed over).
    Jobs without key all run and are all handed over.
    """

    def __init__(self, parent: QObject | None = None, label: str = "Page"):
        super().__init__(parent)
        self.label = label
        self._serial = 0
        self._running = 0
        self._live: dict[int, _Job] = {}  # serial: job started & not handed over (or dropped) yet
        self._active: dict[str, _Job] = {}  # key: job of key running
        self._pending: dict[str, _Job] = {}  # key: job of key waiting for the running one
        self._ref = weakref.ref(self, partial(_owner_gone, self._live, self._pending))
        _get_courier()

    @property
    def running(self) -> int:
        """Jobs started and not handed over yet (waiting ones too)"""
        return self._running

    def is_busy(self, key: str) -> bool:
        """Whether a job of key runs (not cancelled) or waits"""
        if key in self._pending:
            return True
        active = self._active.get(key)
        return active is not None and not active.token.cancelled

    def run(self, name: str, work: Callable[..., Any], done: Callable[[Any], None] | None = None,
            failed: Callable[[BaseException], None] | None = None, key: str | None = None,
            cancellable: bool = False) -> int:
        """Run work on a worker thread, done(result) on the UI thread, failed(error) instead if work raised

        Args:
            name: job name (thread name, log).
            work: function run on a worker thread, must not touch Qt GUI objects.
            done: called with work result on the UI thread (held weakly when a bound method).
            failed: called with the error on the UI thread, else error logged.
            key: jobs of key run one at a time, only the newest waiting one runs, only last one handed over.
            cancellable: work called with a JobToken (work(token)), to stop early once cancelled.

        Returns:
            Job serial.
        """
        self._serial += 1
        serial = self._serial
        job = _Job(serial, key, name, self.label, work, _weak(done), _weak(failed), cancellable, self._ref)
        self._live[serial] = job
        self._running += 1
        if key is None:
            _POOL.submit(job)
        elif key in self._active:
            self._active[key].token.cancel()  # superseded: result dropped, stops early if cancellable
            replaced = self._pending.pop(key, None)
            if replaced is not None:
                self._drop(replaced)
            self._pending[key] = job
        else:
            self._active[key] = job
            _POOL.submit(job)
        return serial

    def cancel(self, key: str) -> bool:
        """Job of key cancelled (result dropped) & waiting one dropped, True if there was any"""
        found = False
        active = self._active.get(key)
        if active is not None and not active.token.cancelled:
            active.token.cancel()
            found = True
        waiting = self._pending.pop(key, None)
        if waiting is not None:
            self._drop(waiting)
            found = True
        return found

    def cancel_all(self):
        """Every job cancelled, results dropped (ex. page closed)"""
        for job in self._live.values():
            job.token.cancel()
        for job in list(self._pending.values()):
            self._drop(job)
        self._pending.clear()

    def _drop(self, job: _Job):
        """Waiting job dropped, never run"""
        job.token.cancel()
        if self._live.pop(job.serial, None) is not None:
            self._running -= 1
        job.release()

    def _deliver(self, job: _Job):
        """Job over (UI thread): next waiting job of its key started, result handed over unless cancelled"""
        if self._live.pop(job.serial, None) is None:
            job.release()
            return
        self._running -= 1
        key = job.key
        if key is not None and self._active.get(key) is job:
            del self._active[key]
            following = self._pending.pop(key, None)
            if following is not None:
                self._active[key] = following
                _POOL.submit(following)
        ok, value = job.outcome or (False, JobCancelled())
        cancelled = job.token.cancelled or (not ok and isinstance(value, JobCancelled))
        job.release()
        if cancelled:
            return
        if ok:
            callback = job.done()
            if callback is not None:
                callback(value)
            return
        callback = job.failed()
        if callback is not None:
            callback(value)
        else:
            logger.error("%s: %s failed", self.label, job.name, exc_info=(type(value), value, value.__traceback__))
