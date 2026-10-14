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
Game Rest API (LMU) asked from app pages, in background: game may take seconds to answer, or not run

Overlays read game Rest API data through the API connector while driving (adapter.lmu_restapi);
pages ask the game themselves, also from the monitor or the menus. GET answers are shared with the
connector & other pages through game_rest_cache (route asked once, recent answer reused).
Qt core only (core modules use it too: hotkeys, game images); ui.game_rest is the same module (older name).
"""

from __future__ import annotations

import http.client
import json
import logging
import threading
import weakref
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any

from PySide6.QtCore import QObject

from .async_request import forget_hostname, resolve_hostname
from .game_rest_cache import lmu_address, rest_cache
from .jobs import Job, WorkerPool, get_courier, weak_callback
from .perf_monitor import timed_call

COMMAND_TIMEOUT = 3.0
SHARED_MAX_AGE = 2.0  # seconds a route answer read by connector or another page is reused
GAME_WORKERS = 4  # worker threads shared by every game request
WORKER_LABEL = "Game request"
GAME_POOL_NAME = "Game requests"  # idle worker threads

logger = logging.getLogger(__name__)


def _nothing() -> None:
    """No callback of job (game request hands its results over itself)"""
    return None


def game_address() -> tuple[str, int] | None:
    """LMU Rest API host & port, None if Rest API access disabled"""
    return lmu_address()


def request_game(resource: str, max_age: float = SHARED_MAX_AGE) -> Any:
    """Json answer of LMU Rest API GET resource without side effect, None if game not running, not in a session
    or access disabled; answer up to max_age old (connector, other page) reused, see game_rest_cache"""
    address = game_address()
    if address is None:
        return None
    return rest_cache.json(resource, max_age, address)


def game_command(method: str, resource: str, body: str | None = None) -> bool:
    """Command to LMU Rest API, True if accepted: "PUT" (empty json if no body), "POST" with json body,
    or "GET" of a resource that acts"""
    address = game_address()
    if address is None:
        return False
    host, port = address
    connection = None
    try:
        connection = http.client.HTTPConnection(resolve_hostname(host, port, COMMAND_TIMEOUT), port,
                                                timeout=COMMAND_TIMEOUT)
        if body is None and method == "PUT":
            body = "{}"
        connection.request(method, resource, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        response.read()
        return response.status < 300
    except OSError:  # connection error: host resolved again next time
        forget_hostname(host, port)
        return False
    except (http.client.HTTPException, ValueError):
        return False
    finally:
        if connection is not None:
            connection.close()


class GameConnection:
    """Connection to LMU Rest API kept open for several requests in a row (one background job)

    get: json answer, None if no answer (game not running) or not json. Game answers some resources
    with an error status & json body outside sessions (watch focus: 400 & -1): body kept.
    send: command, True if accepted (see game_command).
    answered: game answered at least once (running), even with an error status.
    Once the game did not answer, the following requests of the job answer None at once.
    """

    def __init__(self, timeout: float = COMMAND_TIMEOUT, address: tuple[str, int] | None = None):
        # Address of another computer (game running there), else the Rest API address of the app settings
        self.address = address if address is not None else game_address()
        self.timeout = timeout
        self.connection: http.client.HTTPConnection | None = None
        self.failed = self.address is None
        self.answered = False

    def __enter__(self) -> GameConnection:
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def request(self, method: str, resource: str, body: str | None = None) -> tuple[int, bytes]:
        """Status & body of answer, (0, b"") if no answer"""
        if self.failed or self.address is None:
            return 0, b""
        host, port = self.address
        for attempt in range(2):  # connection closed by game since last request: once more on a new one
            try:
                if self.connection is None:
                    self.connection = http.client.HTTPConnection(
                        resolve_hostname(host, port, self.timeout), port, timeout=self.timeout)
                self.connection.request(method, resource, body=body, headers={
                    "Content-Type": "application/json", "Accept": "application/json"})
                response = self.connection.getresponse()
                data = response.read()
                if response.will_close:
                    self.close()
                self.answered = True
                return response.status, data
            except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
                self.close()
                if attempt:
                    break
            except OSError:  # not running: host resolved again next time
                forget_hostname(host, port)
                break
            except (http.client.HTTPException, ValueError):
                break
        self.close()
        self.failed = True
        return 0, b""

    def get(self, resource: str, decode: Callable[[str], Any] | None = None) -> Any:
        """Decoded json answer of resource, None if none (decode: json decoder of answer text, see
        AppendedListDecoder, json.loads if None)"""
        status, data = self.request("GET", resource)
        if not status or not data:
            return None
        try:
            return json.loads(data) if decode is None else decode(data.decode("utf-8"))
        except ValueError:  # also UnicodeDecodeError
            return None

    def send(self, method: str, resource: str, body: str | None = None) -> bool:
        if body is None and method == "PUT":
            body = "{}"
        return 200 <= self.request(method, resource, body)[0] < 300


def _parsed(work: Callable[[], Any], parse: Callable[[Any], Any]) -> Any:
    """Result of work, parsed in background thread"""
    return parse(work())


def callback_name(callback: Callable) -> str:
    """Name of page callback, for performance monitor"""
    return getattr(callback, "__qualname__", None) or type(callback).__name__


def _answers(resources: tuple[str, ...]) -> list:
    """Json answers of resources (None if no answer), default work of a game request"""
    return [request_game(resource) for resource in resources]


# Worker threads of game requests: jobs of pages (ui.quick.background.BackgroundJobs) & game requests use the
# same job mechanism (jobs module: results handed over on the UI thread by the app-lifetime courier, request held
# weakly), on a pool of their own: a game not answering (timeouts of seconds) never holds back file reading of pages
_pool: WorkerPool | None = None
_pool_lock = threading.Lock()


def _game_pool() -> WorkerPool:
    """Worker pool of game requests, created when first needed (connector only needs GameConnection)"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = WorkerPool(GAME_WORKERS, GAME_POOL_NAME)
    return _pool


class GameRequest(QObject):
    """Game asked in background, result handed to callback in UI thread, one request at a time

    Default work: json answers (None if no answer) of resources, as a list (shared cache, see request_game).
    parse: called with work result in the background thread, callback gets its result (pages parse game
    data off the UI thread). Callback taking longer than a frame is reported (perf_monitor.timed_call).
    Requests are done on worker threads shared by every game request (idle ones end after a while); the worker
    never touches the request: result handed over on the UI thread, dropped if the request was deleted meanwhile
    (page closed). on_failed is called when the work or the callback raised (page leaves its waiting state, polls
    again).
    """

    def __init__(self, parent: QObject, resources: Sequence[str], callback: Callable[[Any], None],
                 on_failed: Callable[[], None] | None = None, parse: Callable[[Any], Any] | None = None):
        super().__init__(parent)
        self.resources = tuple(resources)
        self.busy = False
        # Method of page held weakly: no reference cycle, so a page without parent is freed at once, in UI
        # thread (freed by garbage collector on any thread, its file watcher left a dangling socket notifier)
        self._callback: Callable[[], Callable[[Any], None] | None] = weak_callback(callback)
        # Work or callback raised an exception: called instead of / after callback (page leaves its waiting state)
        self._on_failed: Callable[[], Callable[[], None] | None] | None = (
            None if on_failed is None else weak_callback(on_failed))
        self._parse: Callable[[], Callable[[Any], Any] | None] | None = (
            None if parse is None else weak_callback(parse))
        self._serial = 0
        self._ref = weakref.ref(self)
        get_courier()  # created on the UI thread (hands results over)

    def start(self, work: Callable[[], Any] | None = None) -> bool:
        """Ask game (resources, or work done in background), False if still waiting for last answer"""
        if self.busy:
            return False
        self.busy = True
        job = work if work is not None else partial(_answers, self.resources)
        parse = None if self._parse is None else self._parse()
        callback = self._callback()
        self._serial += 1
        name = "game" if callback is None else callback_name(callback)
        _game_pool().submit(Job(self._serial, None, name, WORKER_LABEL,
                                job if parse is None else partial(_parsed, job, parse),
                                _nothing, _nothing, False, self._ref))
        return True

    def answers(self) -> list:
        """Json answers of resources (None if no answer)"""
        return _answers(self.resources)

    def deliver_job(self, job: Job):
        """Job over, on the UI thread (jobs.Courier checked request still exists)"""
        ok, value = job.outcome or (False, None)
        job.release()  # work & result held by job freed on the UI thread
        if ok:
            self._done(value)
            return
        if isinstance(value, BaseException):
            logger.error("GAME REST: request failed", exc_info=(type(value), value, value.__traceback__))
        self.busy = False
        self._notify_failed()

    def _done(self, result: Any):
        self.busy = False
        callback = self._callback()
        if callback is None:
            return
        try:
            timed_call("game_request", callback_name(callback), callback, result)
        except Exception:  # page polls again: a poll re-armed on the callback's last line would stop for good
            logger.exception("GAME REST: %s failed", callback_name(callback))
            self._notify_failed()

    def _notify_failed(self):
        """on_failed of page called (busy left as is: callback may have started next request already)"""
        callback = None if self._on_failed is None else self._on_failed()
        if callback is None:
            return
        try:
            callback()
        except Exception:
            logger.exception("GAME REST: %s failed", callback_name(callback))
