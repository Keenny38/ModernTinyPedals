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
Background jobs of pages: file reading & heavy work off the UI thread, result handed back on the UI thread

Rule of pages: no file read or work longer than a frame (16 ms) on the UI thread. A page runs such work with
BackgroundJobs.run(name, work, done): work runs on a shared pool of worker threads, done(result) is called on
the UI thread. Worker threads & hand-over on the UI thread: core jobs module (also used by game requests).
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import QObject

# Job primitives live in the core jobs module (Qt core only): names kept here for older imports
from ...jobs import (  # noqa: F401
    IDLE_SECONDS,
    MAX_WORKERS,
    SLOW_JOB,
    WORKER_NAME,
    Job,
    JobCancelled,
    JobToken,
    WorkerPool,
    get_courier,
    page_pool,
    weak_callback,
)

logger = logging.getLogger(__name__)


def _owner_gone(live: dict[int, Job], pending: dict[str, Job], _ref: weakref.ref):
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
        self._live: dict[int, Job] = {}  # serial: job started & not handed over (or dropped) yet
        self._active: dict[str, Job] = {}  # key: job of key running
        self._pending: dict[str, Job] = {}  # key: job of key waiting for the running one
        self._ref = weakref.ref(self, partial(_owner_gone, self._live, self._pending))
        get_courier()

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
        job = Job(serial, key, name, self.label, work, weak_callback(done), weak_callback(failed), cancellable,
                  self._ref)
        self._live[serial] = job
        self._running += 1
        if key is None:
            page_pool().submit(job)
        elif key in self._active:
            self._active[key].token.cancel()  # superseded: result dropped, stops early if cancellable
            replaced = self._pending.pop(key, None)
            if replaced is not None:
                self._drop(replaced)
            self._pending[key] = job
        else:
            self._active[key] = job
            page_pool().submit(job)
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

    def _drop(self, job: Job):
        """Waiting job dropped, never run"""
        job.token.cancel()
        if self._live.pop(job.serial, None) is not None:
            self._running -= 1
        job.release()

    def deliver_job(self, job: Job):
        """Job over (UI thread, see jobs.Courier): next waiting job of its key started, result handed over unless cancelled"""
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
                page_pool().submit(following)
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
