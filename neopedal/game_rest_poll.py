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
Route of game Rest API (Le Mans Ultimate) read in background while asked for

A widget calls poll() on each update: the route is read again on a background poll worker once interval
passed (never blocking), its parsed value kept in value. Answers shared with other readers of the route
(game_rest_cache), body parsed only once changed. Only GET routes without side effect.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Generic, TypeVar

from .game_rest_cache import rest_cache

T = TypeVar("T")
logger = logging.getLogger(__name__)
POLL_WORKERS = 2  # threads shared by background reads of pollers (game routes, driver ranks file)
POLL_IDLE_SECONDS = 30.0  # poll thread left without read this long ends (started again when needed)


class PollWorker:
    """Daemon threads (at most size) running background reads of pollers in turn, started when needed, idle ones
    end after a while: no thread made per read. Never touches Qt (usable without app)."""

    def __init__(self, size: int = POLL_WORKERS, name: str = "Background poll"):
        self.size = size
        self.name = name
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._queue: deque[Callable[[], object]] = deque()
        self._workers = 0
        self._idle = 0

    def submit(self, work: Callable[[], object]):
        """Run work on a poll thread (errors logged)"""
        with self._lock:
            self._queue.append(work)
            start = len(self._queue) > self._idle and self._workers < self.size
            if start:
                self._workers += 1
            else:
                self._wake.notify()
        if start:
            try:
                threading.Thread(target=self._work, daemon=True, name=self.name).start()
            except RuntimeError:  # interpreter closing: no thread
                with self._lock:
                    self._workers -= 1

    def _work(self):
        while True:
            with self._lock:
                deadline = time.monotonic() + POLL_IDLE_SECONDS
                while not self._queue:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._workers -= 1
                        return
                    self._idle += 1
                    self._wake.wait(remaining)
                    self._idle -= 1
                work = self._queue.popleft()
            try:
                work()
            except Exception:
                logger.exception("%s: read failed", self.name)
            del work


poll_worker = PollWorker()


def fetch_route(route: str, max_age: float = 0.0) -> tuple[int, bytes]:
    """Status & body of game answer (shared answer up to max_age old), (0, b"") if game does not answer"""
    answer = rest_cache.answer(route, max_age)
    return answer.status, answer.body


class RoutePoller(Generic[T]):
    """Parsed value of a game route, read in background

    Args:
        route: GET route of game Rest API.
        parse: JSON data -> value (any data, null outside a session).
        empty: value while game does not run.
        interval: seconds between reads.
        fetch: function giving status & body of route (tests).
        clock: time function (tests).
        bytes_per_second: body bytes read & parsed per second at most, longer interval for a large body
            (0: fixed interval).
    """

    def __init__(self, route: str, parse: Callable[[Any], T], empty: T, interval: float,
                 fetch: Callable[[], tuple[int, bytes]] | None = None, clock: Callable[[], float] | None = None,
                 bytes_per_second: float = 0.0):
        self.route = route
        self._parse = parse
        self._empty = empty
        self._interval = interval
        self._bytes_per_second = bytes_per_second
        self._wait = interval  # seconds until next read, interval scaled with last body size
        self._fetch = fetch or (lambda: fetch_route(route, interval / 2))
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._busy = False  # read waiting or running on poll worker
        self._checked = -interval
        self._digest: int | None = None  # hash of body parsed into value
        self.value: T = empty

    def poll(self) -> None:
        """Read route in background if due (non blocking)"""
        now = self._clock()
        with self._lock:
            if self._busy or now - self._checked < self._wait:
                return
            self._checked = now
            self._busy = True
        poll_worker.submit(self._check_polled)

    def _check_polled(self) -> None:
        try:
            self.check()
        finally:
            self._busy = False

    def check(self) -> None:
        """Read route (blocking): value kept while game answers nothing usable"""
        try:
            status, body = self._fetch()
        except Exception:  # any connection error: try again next time
            return
        if status == 0:  # game not running: no session
            self._digest = None
            self._wait = self._interval
            self.value = self._empty
            return
        if status != 200:
            return
        if self._bytes_per_second > 0:  # large body (long race): read & parsed less often
            self._wait = max(self._interval, len(body) / self._bytes_per_second)
        digest = hash(body)  # cached by bytes: shared answer hashed once
        if digest == self._digest:  # same body: value unchanged
            return
        try:
            data = json.loads(body)
        except ValueError:
            return
        self.value = self._parse(data)
        self._digest = digest
