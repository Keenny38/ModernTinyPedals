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
Broadcast Director game state requests (QML: backend.game): the game asked about once a second while the page is
open (shown or not), one connection kept from answer to answer (game on this computer or another one), answers
handed to the page (DirectorBackend.received_state)
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QTimer, Signal, Slot

from ... import game_rest
from ...adapter.restapi_connector import AppendedListDecoder
from ...game_rest import GameConnection, GameRequest
from ...game_rest_cache import rest_cache
from ...process.game_info import (
    Contact,
    ContactsParser,
    parse_camera,
    parse_contacts,
    parse_focus,
    parse_hud,
    parse_session_end,
    parse_session_state,
    parse_session_time,
    parse_standings,
    standings_time,
)
from . import game_camera as gc
from .director_shared import (
    HIDDEN_POLL_MS,
    HUD_RESOURCE,
    IDLE_POLL_MS,
    LOCAL_HOSTS,
    POLL_MS,
    REPLAY,
    SESSION,
    SHARED_MAX_AGE,
    TRACKMAP_RESOURCE,
    WEATHER_EVERY,
    WEATHER_RESOURCE,
    DirectorPart,
)

if TYPE_CHECKING:
    from .director_backend import DirectorBackend


class SharedConnection:
    """Kept game connection reading first answers of other readers (connector, pages) not older than max_age,
    its own answers shared with them (game_rest_cache); GET routes without side effect only"""

    def __init__(self, connection: GameConnection, max_age: float):
        self.connection = connection
        self.max_age = max_age
        self.shared = False  # an answer of another reader used: game running

    @property
    def answered(self) -> bool:
        return self.connection.answered or self.shared

    def get(self, resource: str, decode: Callable[[str], Any] | None = None) -> Any:
        connection = self.connection
        if connection.failed or connection.address is None:
            return None
        answer = rest_cache.fresh(resource, self.max_age, connection.address)
        if answer is not None and answer.status:
            self.shared = True
            status, data = answer.status, answer.body
        else:
            status, data = connection.request("GET", resource)
            if status:
                rest_cache.store(resource, status, data, connection.address)
        if not status or not data:
            return None
        try:
            return json.loads(data) if decode is None else decode(data.decode("utf-8"))
        except ValueError:  # also UnicodeDecodeError
            return None


def ask_state(connection: GameConnection | SharedConnection, forecast: bool = False,
              trackmap: bool = False, hud: bool = False, decode_incidents: Callable[[str], Any] | None = None,
              contacts_of: Callable[[Any, tuple], tuple[Contact, ...]] = parse_contacts) -> dict[str, Any]:
    """Game state (in background): session, standings, contacts, camera & car followed, weather forecast,
    track outline & HUD parts shown if asked

    Incidents list asked again & again (growing): decoded & parsed incrementally if decode_incidents
    (AppendedListDecoder) & contacts_of (ContactsParser) kept between calls are given.
    """
    active = connection.get(gc.ACTIVE_RESOURCE)
    if active is None:  # not in a session: game running if it answers anything
        connection.get(gc.FOCUS_RESOURCE)
        return {"active": None, "running": connection.answered}
    info = connection.get(gc.SESSION_RESOURCE)
    info = info if isinstance(info, dict) else {}
    standings = parse_standings(connection.get(gc.STANDINGS_RESOURCE))
    length = info.get("lapDistance")
    return {
        "active": active is True, "running": True,
        "standings": standings,
        "contacts": contacts_of(connection.get(gc.INCIDENTS_RESOURCE, decode_incidents), ()),
        "camera": parse_camera(connection.get(gc.CAMERA_RESOURCE)),
        "focus": parse_focus(connection.get(gc.FOCUS_RESOURCE)),
        # Replay: session time of info stays 0, cars tell where the replay is
        "time": standings_time(standings) if active is True else parse_session_time(info),
        "track": str(info.get("trackName") or ""),
        "session": str(info.get("session") or ""),
        "start": info.get("startEventTime") if isinstance(info.get("startEventTime"), (int, float)) else 0,
        "length": float(length) if isinstance(length, (int, float)) and not isinstance(length, bool) and length > 0
        else 0.0,
        "info": parse_session_state(info),
        "end": parse_session_end(info),
        **({"forecast": connection.get(WEATHER_RESOURCE)} if forecast else {}),
        **({"trackmap": connection.get(TRACKMAP_RESOURCE)} if trackmap else {}),
        **({"hud": parse_hud(connection.get(HUD_RESOURCE))} if hud else {}),
    }


class GameStatePoll(DirectorPart):
    """State requests of the page: asked again after each answer (POLL_MS in a session, IDLE_POLL_MS in menus,
    every HIDDEN_POLL_MS while nothing needs fresh answers), game on another computer (game host setting)"""

    hostChanged = Signal()

    def __init__(self, page: DirectorBackend, settings: dict[str, Any]):
        super().__init__(page)
        host = settings.get("game_host")
        self.game_host = host.strip() if isinstance(host, str) else ""  # game on another computer, "" this one
        self.polls = 0  # requests made (forecast & race results read again every so many)
        # Incidents (growing list): only entries added since last answer decoded & parsed
        self._decode_incidents = AppendedListDecoder()
        self._contacts_of = ContactsParser()
        self.need_track = True  # track outline asked with next state (new session)
        self.need_hud = False  # HUD parts of the game asked with next state (HUD menu opened)
        # Connection of state requests, kept from answer to answer: made by their thread, dropped by the page
        # (closed by whichever side stops using it last, see drop_connection)
        self._connection: GameConnection | None = None
        self._connection_used: GameConnection | None = None  # connection the state thread asks the game on
        self._connection_lock = threading.Lock()
        self.request_state = GameRequest(self, (), self.received_state, self.schedule)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.poll_tick)
        self._asked = 0.0  # monotonic time the game was last asked

    def page_settings(self) -> dict[str, Any]:
        return {"game_host": self.game_host}

    def received_state(self, state: dict):
        """Answer of a state request (UI thread): read by the page, which asks again (schedule) on its last line"""
        self.page.received_state(state)

    def stop(self):
        """No more requests (page closed, director off): timer stopped, kept connection dropped"""
        self._timer.stop()
        self.drop_connection()

    @Slot()
    def refresh(self):
        self._timer.stop()
        self.refresh_state()

    def refresh_state(self):
        page = self.page
        if page.is_open and page.is_enabled and self.request_state.start(self.poll_game):
            self._asked = time.monotonic()

    def poll_tick(self):
        """Game asked again; page hidden & nothing needing fresh answers: only every HIDDEN_POLL_MS, checked each
        second so the page shown, a graphics source or automatic cuts get fresh answers at once"""
        if (self.page.state in (SESSION, REPLAY) and not self.needs_fresh()
                and time.monotonic() - self._asked < HIDDEN_POLL_MS / 1000):
            self._timer.start(POLL_MS)
            return
        self.refresh_state()

    def needs_fresh(self) -> bool:
        """Answers wanted every second: page shown, automatic cuts, overlays following the car on air, events log,
        instant replay, broadcast graphics source showing (asked lately)"""
        from ...stream_director import director_feed, live_feed

        page = self.page
        return (page.shown or page.mode == "auto" or page.follow_overlays or page.log.log_events
                or page.instant or director_feed.watched() or live_feed.watched())

    def poll_game(self) -> dict[str, Any]:
        """Game state (background thread of state requests): one connection kept from answer to answer
        (game keeps it alive), a new one once it failed"""
        replaced = None
        with self._connection_lock:
            connection = self._connection
            if connection is None or connection.failed:
                replaced = connection
                address = self.game_address()
                connection = self._connection = (game_rest.GameConnection(address=address) if address is not None
                                                 else game_rest.GameConnection())
            self._connection_used = connection
        if replaced is not None:  # failed one
            replaced.close()
        self.polls += 1
        try:
            return ask_state(SharedConnection(connection, SHARED_MAX_AGE), forecast=self.polls % WEATHER_EVERY == 1,
                             trackmap=self.need_track, hud=self.need_hud,
                             decode_incidents=self._decode_incidents, contacts_of=self._contacts_of)
        finally:
            with self._connection_lock:
                self._connection_used = None
                dropped = self._connection is not connection
            if dropped:  # dropped by the page meanwhile (closed, game host changed, director off): closed here
                connection.close()

    def drop_connection(self):
        """Connection kept from answer to answer dropped (next request makes a new one): closed now, or by the
        state thread once its request is over if it uses it"""
        with self._connection_lock:
            connection, self._connection = self._connection, None
            in_use = connection is not None and connection is self._connection_used
        if connection is not None and not in_use:
            connection.close()

    def game_address(self) -> tuple[str, int] | None:
        """Game on another computer (host of page settings, port of the app Rest API), None: app settings"""
        if self.game_host.lower() in LOCAL_HOSTS:
            return None
        default = game_rest.game_address()
        return self.game_host, default[1] if default is not None else 6397

    def local_game(self) -> bool:
        """Game runs on this computer: its shared memory tells the same session"""
        return self.game_host.lower() in LOCAL_HOSTS

    def schedule(self):
        page = self.page
        if page.is_open and page.is_enabled and not self.request_state.busy:
            self._timer.start(POLL_MS if page.state in (SESSION, REPLAY) else IDLE_POLL_MS)

    @Property(str, notify=hostChanged)
    def gameHost(self) -> str:
        return self.game_host

    @Slot(str)
    def setGameHost(self, host: str):
        """Game on another computer (address), "" for this one: asked again at once on a new connection"""
        host = host.strip()
        if host == self.game_host:
            return
        self.game_host = host
        self.drop_connection()  # state thread makes a new connection at next request
        self.page.save_settings()
        self.hostChanged.emit()
        self.refresh()
