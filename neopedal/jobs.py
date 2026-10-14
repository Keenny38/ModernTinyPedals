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
Background jobs: work run on worker threads, result handed over on the UI thread (Qt core only)

One job mechanism for the whole app: a Job is submitted to a WorkerPool (daemon threads, started when needed,
idle ones end after a while), its outcome is stored on it, then the app-lifetime Courier hands it over on the UI
thread to its owner (held weakly: deliver_job(job) of a QObject, dropped if the owner was deleted meanwhile).
The worker never touches the owner. Pages use ui.quick.background.BackgroundJobs (per-key single-flight,
cancellation); game requests (game_rest.GameRequest) and app-lifetime objects own their jobs directly.
"""

from __future__ import annotations

import inspect
import logging
import threading
import weakref
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from time import monotonic, perf_counter
from typing import Any, Protocol

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


def weak_callback(callback: Callable | None) -> Callable[[], Any]:
    """Callback held weakly when a bound method: no reference cycle owner <-> jobs (a page without parent is then
    freed at once on the UI thread, never by the garbage collector on a job thread). Returns a function giving the
    callback, None once its object is gone (or if callback is None)."""
    if callback is None:
        return lambda: None
    if inspect.ismethod(callback):
        return weakref.WeakMethod(callback)
    return lambda: callback


class JobOwner(Protocol):
    """Object a job is handed over to on the UI thread (a QObject)"""

    def deliver_job(self, job: Job) -> None: ...


class Job:
    """Job waiting, running or done (outcome), until handed over on the UI thread

    work: called on a worker thread (with the token if cancellable), outcome (True, result) or (False, error).
    done, failed: weak callbacks (see weak_callback) for the owner's use. owner: weak reference to the owner.
    """

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


def execute(job: Job, idle_name: str = WORKER_NAME):
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
        thread.name = idle_name
    work = None
    courier = _courier
    if courier is not None:
        with suppress(RuntimeError):  # app closing: courier deleted, result dropped
            courier.arrived.emit(job)


class WorkerPool:
    """Daemon worker threads (app exit never waits for a job), at most size, idle ones end after a while"""

    def __init__(self, size: int, name: str = WORKER_NAME):
        self.size = size
        self.name = name
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._queue: deque[Job] = deque()
        self._workers = 0
        self._idle = 0
        self._started = 0

    def submit(self, job: Job):
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
            threading.Thread(target=self._work, daemon=True, name=f"{self.name} {number}").start()

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
            execute(job, self.name)
            del job


_page_pool: WorkerPool | None = None
_pool_lock = threading.Lock()


def page_pool() -> WorkerPool:
    """Worker pool shared by every page (BackgroundJobs), created when first needed"""
    global _page_pool
    if _page_pool is None:
        with _pool_lock:
            if _page_pool is None:
                _page_pool = WorkerPool(MAX_WORKERS)
    return _page_pool


class Courier(QObject):
    """Jobs done on worker threads handed to their owner on the UI thread (held weakly: an owner is never kept
    alive, nor freed, by a worker thread)"""

    arrived = Signal(object)

    def __init__(self):
        super().__init__()
        self.arrived.connect(self.hand_over, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def hand_over(self, job: Job):
        owner: JobOwner | None = job.owner()
        if owner is None or not isValid(owner):  # owner deleted (page closed): result dropped
            job.release()
            return
        owner.deliver_job(job)


_courier: Courier | None = None


def get_courier() -> Courier:
    """App-lifetime courier, created on the UI thread (call from the owner's constructor)"""
    global _courier
    if _courier is None or not isValid(_courier):
        _courier = Courier()
        app = QCoreApplication.instance()
        if app is not None and _courier.thread() is not app.thread():
            _courier.moveToThread(app.thread())
    return _courier
