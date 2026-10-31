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
Shared cache of game Rest API GET routes (LMU), so the connector, pages & tools reading the same route
share one request & one parse

    rest_cache.answer(route, max_age)            Answer (status, body, time, digest): kept one if not older than
                                                 max_age, else asked now; callers asking a route already being
                                                 asked wait for that request (one request per route at a time)
    rest_cache.fresh(route, max_age)             kept Answer not older than max_age, None (never asks, never waits)
    rest_cache.store(route, status, body)        answer read elsewhere (connector) handed to other readers
    rest_cache.json(route, max_age)              decoded json of a 200 answer (new object each call), None if none
    rest_cache.prune()                           answers older than STALE_AGE dropped (also done while used)

Every call takes address (host, port), default: LMU Rest API address of app settings (None: access disabled,
nothing asked). Only GET routes without side effect may be read through the cache. Values handed out are
shared: never modified by callers. Answers older than STALE_AGE are dropped (a page closed or a route asked once
no longer holds its last body).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from .const_api import API_LMU_CONFIG
from .validator import json_loads_checked

Address = tuple[str, int]
Fetch = Callable[[Address, str, float], tuple[int, bytes]]

DEFAULT_MAX_AGE = 1.0  # seconds an answer is reused
REQUEST_TIMEOUT = 3.0  # seconds per request
MAX_ROUTES = 256  # routes kept (bounded: route names hold ids)
STALE_AGE = 30.0  # seconds: older answers dropped (no reader asks for them any more)
PRUNE_EVERY = 5.0  # seconds between stale answer checks while the cache is used


class Answer(NamedTuple):
    """Game answer of a route

    Attributes:
        status: HTTP status, 0 if game did not answer (not running).
        body: answer body.
        time: monotonic time of answer.
        digest: hash of body (same body, same digest).
    """

    status: int
    body: bytes
    time: float
    digest: int

    @property
    def ok(self) -> bool:
        """Status 200 with a body"""
        return self.status == 200 and bool(self.body)


NO_ANSWER = Answer(0, b"", 0.0, hash(b""))


def lmu_address() -> Address | None:
    """LMU Rest API host & port of app settings, None if Rest API access disabled"""
    from .setting import cfg  # not loaded with connector modules

    setting = cfg.user.setting.get(API_LMU_CONFIG, {})
    if not setting.get("enable_restapi_access", True):
        return None
    return str(setting.get("url_host", "localhost")), int(setting.get("url_port", 6397))


def fetch_game(address: Address, route: str, timeout: float) -> tuple[int, bytes]:
    """Status & body of GET route, (0, b"") if game does not answer"""
    from .game_rest import GameConnection  # imports this module: imported when first needed

    with GameConnection(timeout=timeout, address=address) as connection:
        return connection.request("GET", route)


class _Route:
    """Answer & request in progress of a route"""

    __slots__ = ("answer", "pending")

    def __init__(self):
        self.answer: Answer | None = None
        self.pending: threading.Event | None = None  # request in progress


class GameRestCache:
    """Answers of game routes, see module doc (thread safe)

    Args:
        fetch: (address, route, timeout) -> (status, body), default fetch_game (tests: fake game).
        clock: monotonic time function (tests).
    """

    def __init__(self, fetch: Fetch | None = None, clock: Callable[[], float] | None = None,
                 timeout: float = REQUEST_TIMEOUT):
        self.fetch = fetch  # None: fetch_game
        self._clock = clock or time.monotonic
        self.timeout = timeout
        self._lock = threading.Lock()
        self._routes: dict[tuple[Address, str], _Route] = {}
        self._pruned = self._clock()
        self.requests = 0  # requests sent (tests, monitor)

    def _prune_locked(self, now: float) -> None:
        self._pruned = now
        stale = [key for key, entry in self._routes.items()
                 if entry.pending is None and (entry.answer is None or now - entry.answer.time > STALE_AGE)]
        for key in stale:
            del self._routes[key]

    def prune(self) -> None:
        """Answers older than STALE_AGE dropped (requests in progress kept)"""
        now = self._clock()
        with self._lock:
            self._prune_locked(now)

    def _route(self, address: Address, route: str) -> _Route:
        now = self._clock()
        with self._lock:
            if now - self._pruned >= PRUNE_EVERY:
                self._prune_locked(now)
            entry = self._routes.get((address, route))
            if entry is None:
                if len(self._routes) >= MAX_ROUTES:
                    self._prune_locked(now)
                    if len(self._routes) >= MAX_ROUTES:
                        self._evict_locked()
                entry = self._routes[(address, route)] = _Route()
            return entry

    def _evict_locked(self) -> None:
        """Oldest answered route without request in progress dropped (a pending route keeps its waiters & answer
        sharing: dropping it would start a second identical request)"""
        idle = [(entry.answer.time if entry.answer is not None else 0.0, key)
                for key, entry in self._routes.items() if entry.pending is None]
        if idle:
            del self._routes[min(idle)[1]]

    def fresh(self, route: str, max_age: float = DEFAULT_MAX_AGE, address: Address | None = None) -> Answer | None:
        """Kept answer not older than max_age, None if none (never asks)"""
        address = address or lmu_address()
        if address is None:
            return None
        with self._lock:
            entry = self._routes.get((address, route))
            answer = entry.answer if entry is not None else None
        # max_age 0: never kept, even with a coarse clock (Windows: 15.6 ms steps, age often 0)
        if answer is not None and max_age > 0 and self._clock() - answer.time <= max_age:
            return answer
        return None

    def store(self, route: str, status: int, body: bytes, address: Address | None = None) -> Answer:
        """Keep answer read elsewhere (connector), for other readers of route"""
        answer = Answer(status, body, self._clock(), hash(body))
        address = address or lmu_address()
        if address is not None:
            entry = self._route(address, route)
            with self._lock:
                entry.answer = answer
        return answer

    def answer(self, route: str, max_age: float = DEFAULT_MAX_AGE, address: Address | None = None) -> Answer:
        """Answer of route not older than max_age: kept one, the one another caller is asking, or asked now
        (blocking: call from a background thread)"""
        address = address or lmu_address()
        if address is None:
            return NO_ANSWER
        entry = self._route(address, route)
        while True:
            with self._lock:
                answer = entry.answer
                if answer is not None and max_age > 0 and self._clock() - answer.time <= max_age:  # 0: ask
                    return answer
                pending = entry.pending
                if pending is None:
                    pending = entry.pending = threading.Event()
                    break
            # Other caller asking: its answer is fresh, kept one if it takes too long
            done = pending.wait(self.timeout * 2 + 1)
            with self._lock:
                answer = entry.answer
            if not done:
                return answer or NO_ANSWER
            if answer is not None:
                return answer
        status, body = 0, b""
        try:
            status, body = (self.fetch or fetch_game)(address, route, self.timeout)
        except Exception:  # unexpected connection error: no answer, asked again next time
            pass
        finally:  # waiting callers released whatever happened
            answer = Answer(status, body, self._clock(), hash(body))
            with self._lock:
                self.requests += 1
                entry.answer = answer
                entry.pending = None
            pending.set()
        return answer

    def json(self, route: str, max_age: float = DEFAULT_MAX_AGE, address: Address | None = None) -> Any:
        """Decoded json of status 200 answer (new object each call), None if no answer or not json"""
        answer = self.answer(route, max_age, address)
        if not answer.ok:
            return None
        try:
            return json_loads_checked(answer.body)
        except (ValueError, RecursionError):  # RecursionError: nested too deeply
            return None

    def forget(self, route: str | None = None) -> None:
        """Drop kept answers of route (every route if None): asked again next time"""
        with self._lock:
            if route is None:
                self._routes.clear()
                return
            for key in [key for key in self._routes if key[1] == route]:
                del self._routes[key]


rest_cache = GameRestCache()
