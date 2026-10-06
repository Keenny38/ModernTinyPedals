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
Game Rest API (LMU) asked from app pages, in background: game may take seconds to answer, or not run

Overlays read game Rest API data through the API connector while driving (adapter.lmu_restapi);
pages ask the game themselves, also from the monitor or the menus.
"""

from __future__ import annotations

import http.client
import inspect
import json
import logging
import queue
import threading
import weakref
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..async_request import forget_hostname, resolve_hostname
from ..const_api import API_LMU_CONFIG
from ..setting import cfg
from ..userfile import track_geometry

COMMAND_TIMEOUT = 3.0

logger = logging.getLogger(__name__)


def game_address() -> tuple[str, int] | None:
    """LMU Rest API host & port, None if Rest API access disabled"""
    setting = cfg.user.setting.get(API_LMU_CONFIG, {})
    if not setting.get("enable_restapi_access", True):
        return None
    return str(setting.get("url_host", "localhost")), int(setting.get("url_port", 6397))


def request_game(resource: str) -> Any:
    """Json answer of LMU Rest API, None if game not running, not in a session or access disabled"""
    address = game_address()
    if address is None:
        return None
    return track_geometry.rest_get(*address, resource)


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

    def __init__(self, timeout: float = COMMAND_TIMEOUT):
        self.address = game_address()
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

    def get(self, resource: str) -> Any:
        status, data = self.request("GET", resource)
        if not status or not data:
            return None
        try:
            return json.loads(data)
        except ValueError:
            return None

    def send(self, method: str, resource: str, body: str | None = None) -> bool:
        if body is None and method == "PUT":
            body = "{}"
        return 200 <= self.request(method, resource, body)[0] < 300


def _serve(jobs: queue.SimpleQueue, received: Any, failed: Any):
    """Jobs of a game request done one after another on the same thread (until None)"""
    while (job := jobs.get()) is not None:
        try:
            result = job()
        except Exception:  # request ended, next one can start
            logger.exception("GAME REST: request failed")
            with suppress(RuntimeError):
                failed.emit()
            continue
        finally:
            job = None  # work (may hold its page) dropped once done, not kept until next request
        with suppress(RuntimeError):  # page closed meanwhile
            received.emit(result)
        result = None


class GameRequest(QObject):
    """Game asked in background, result handed to callback in UI thread, one request at a time

    Default work: json answers (None if no answer) of resources, as a list.
    Requests are done on a thread of their own, kept for next requests (pages ask every few seconds).
    """

    received = Signal(object)
    failed = Signal()

    def __init__(self, parent: QObject, resources: Sequence[str], callback: Callable[[Any], None]):
        super().__init__(parent)
        self.resources = tuple(resources)
        self.busy = False
        # Method of page held weakly: no reference cycle, so a page without parent is freed at once, in UI
        # thread (freed by garbage collector on any thread, its file watcher left a dangling socket notifier)
        self._callback: Callable[[], Callable[[Any], None] | None] = (
            weakref.WeakMethod(callback) if inspect.ismethod(callback) else lambda: callback)
        self._jobs: queue.SimpleQueue | None = None
        self.received.connect(self._done)
        self.failed.connect(self._failed)

    def start(self, work: Callable[[], Any] | None = None) -> bool:
        """Ask game (resources, or work done in background), False if still waiting for last answer"""
        if self.busy:
            return False
        self.busy = True
        if self._jobs is None:
            jobs = self._jobs = queue.SimpleQueue()
            threading.Thread(target=_serve, args=(jobs, self.received, self.failed), daemon=True,
                             name="Game request").start()
            self.destroyed.connect(lambda *_: jobs.put(None))  # thread ends with request
        self._jobs.put(work if work is not None else self.answers)
        return True

    def answers(self) -> list:
        """Json answers of resources (None if no answer)"""
        return [request_game(resource) for resource in self.resources]

    def _done(self, result: Any):
        self.busy = False
        callback = self._callback()
        if callback is not None:
            callback(result)

    def _failed(self):
        self.busy = False
