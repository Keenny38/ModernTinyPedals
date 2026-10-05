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
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..async_request import resolve_hostname
from ..const_api import API_LMU_CONFIG
from ..setting import cfg
from ..userfile import track_geometry

COMMAND_TIMEOUT = 3.0


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


def game_command(method: str, resource: str) -> bool:
    """Command to LMU Rest API ("PUT" with empty json, or "GET" of a resource that acts), True if accepted"""
    address = game_address()
    if address is None:
        return False
    host, port = address
    connection = None
    try:
        connection = http.client.HTTPConnection(resolve_hostname(host, port, COMMAND_TIMEOUT), port,
                                                timeout=COMMAND_TIMEOUT)
        body = "{}" if method == "PUT" else None
        connection.request(method, resource, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        response.read()
        return response.status < 300
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        if connection is not None:
            connection.close()


class GameRequest(QObject):
    """Game asked in background, result handed to callback in UI thread, one request at a time

    Default work: json answers (None if no answer) of resources, as a list.
    """

    received = Signal(object)

    def __init__(self, parent: QObject, resources: Sequence[str], callback: Callable[[Any], None]):
        super().__init__(parent)
        self.resources = tuple(resources)
        self.busy = False
        self._callback = callback
        self.received.connect(self._done)

    def start(self, work: Callable[[], Any] | None = None) -> bool:
        """Ask game (resources, or work done in background), False if still waiting for last answer"""
        if self.busy:
            return False
        self.busy = True
        job = work if work is not None else self.answers

        def requesting():
            result = job()
            with suppress(RuntimeError):  # page closed meanwhile
                self.received.emit(result)

        threading.Thread(target=requesting, daemon=True, name="Game request").start()
        return True

    def answers(self) -> list:
        """Json answers of resources (None if no answer)"""
        return [request_game(resource) for resource in self.resources]

    def _done(self, result: Any):
        self.busy = False
        self._callback(result)
