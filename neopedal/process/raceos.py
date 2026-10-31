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
Player Driver Rank & Safety Rank of RaceControl (Le Mans Ultimate online service), without Qt

The game menu stopped keeping ranks in its storage file (2026-10): it reads them online. Same requests
as the game menu (web UI of the game, "RaceOS" client):
    1. GET <game Rest API>/rest/profile/getAuthSessionTicket -> {"authSessionTicket": "<Steam ticket>"}
    2. POST https://raceos.gg/authenticate {"token": ticket, "game": "lmu", "platform": "steam"}
       -> {"accessToken", "expiresAt", "player": {name, driverRank, safetyRank, profile, platforms...}, "banned"}
       (404: no RaceControl account)
Ranks of that sign in answer are current (checked live 2026-10-17: DR progress 36.96, elo 2060), while
GET //api/v1/player with the token gives an old copy (progress 40 of 5 days before, elo 0): signed in again
for each read (the game menu asks a new ticket every 25 minutes too).
Other drivers (token of a sign in, header "Game-Authorization: Bearer <accessToken>"):
    POST api/v1/players {"usernames": [...]} -> [player] (same values as race entry lists; daily race lists give
    only races to come, not the one being run: never used)
Read only: no websocket, nothing sent but the ticket. Ticket & token never logged nor saved (memory only).
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import IO, TYPE_CHECKING, Any, NamedTuple

from ..validator import json_loads_checked
from .driver_ranks import DriverRanks, parse_rank

if TYPE_CHECKING:
    import http.client
    import urllib.request

RACEOS_HOST = "raceos.gg"
RACEOS_URL = f"https://{RACEOS_HOST}"
AUTH_URL = f"{RACEOS_URL}/authenticate"
TICKET_ROUTE = "/rest/profile/getAuthSessionTicket"
TIMEOUT = 8.0  # seconds per connection step & read
REQUEST_SECONDS = 20.0  # answer (status, headers, body) read in this time at most once request sent
MAX_BODY = 4 * 1024 * 1024
RETRY_SECONDS = 300.0  # first wait after a failed sign in, doubled each failure
RETRY_MAX_SECONDS = 3600.0
NO_ACCOUNT_SECONDS = 3600.0  # no RaceControl account: tried again this late
TOKEN_MARGIN = 120.0  # token of a sign in used for other reads until this many seconds before it expires
TOKEN_SECONDS = 1500.0  # token lifetime if expiry not given or unreadable (game menu: new ticket every 25 min)
FLIGHT_WAIT = 30.0  # caller waits this long at most for the answer of a sign in running (its requests time out sooner)

logger = logging.getLogger(__name__)

# (method, url, body, headers, timeout) -> status (0: no answer), body
Http = Callable[[str, str, bytes | None, dict[str, str], float], tuple[int, bytes]]


def is_raceos_url(url: str) -> bool:
    """Address of RaceControl over HTTPS (redirect allowed to it only: requests carry the sign in token)"""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        return parts.scheme == "https" and parts.hostname == RACEOS_HOST and parts.port in (None, 443)
    except ValueError:  # invalid port
        return False


def _opener(seconds: float) -> urllib.request.OpenerDirector:
    """urllib opener: answers read within seconds of each connection, redirects followed only to https://raceos.gg
    (urllib keeps the Game-Authorization header on a redirect to another host, and allows http)"""
    import http.client
    import urllib.request

    from ..http_limits import deadline_response_class

    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str,
                             headers: http.client.HTTPMessage, newurl: str) -> urllib.request.Request | None:
            if not is_raceos_url(newurl):
                logger.info("RACEOS: redirect to another address refused")
                return None  # redirect answer handed to caller (HTTPError), never followed
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    class Connection(http.client.HTTPSConnection):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.response_class = deadline_response_class(seconds)  # type: ignore[assignment]

    class Handler(urllib.request.HTTPSHandler):
        def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
            return self.do_open(Connection, req, context=self._context)  # type: ignore[attr-defined]

    return urllib.request.build_opener(Redirect, Handler)


def http_request(method: str, url: str, body: bytes | None, headers: dict[str, str],
                 timeout: float) -> tuple[int, bytes]:
    """Status & body of request (error statuses too), (0, b"") if no answer, or not read in REQUEST_SECONDS, or body
    above MAX_BODY; https://raceos.gg only (redirects too)"""
    import http.client
    import urllib.error
    import urllib.request

    from ..http_limits import read_body

    if not is_raceos_url(url):
        return 0, b""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _opener(max(REQUEST_SECONDS, timeout)).open(request, timeout=timeout) as response:
            return response.status, read_body(response.read, MAX_BODY, response.length)
    except urllib.error.HTTPError as error:
        try:
            return error.code, read_body(error.read, MAX_BODY, getattr(error.fp, "length", None))
        except (OSError, ValueError, http.client.HTTPException):
            return error.code, b""
        finally:
            error.close()
    except (OSError, ValueError, http.client.HTTPException):  # offline, refused, cut off, too large (ValueError)
        return 0, b""


def _json(body: bytes) -> Any:
    try:
        return json_loads_checked(body)
    except (ValueError, RecursionError):  # UnicodeDecodeError too, RecursionError: nested too deeply
        return None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_time(value: Any) -> float:
    """Seconds since epoch of ISO 8601 text (UTC if no zone), NaN if unreadable"""
    if not isinstance(value, str) or not value:
        return math.nan
    text = value.strip().replace("Z", "+00:00")
    head, dot, rest = text.partition(".")  # nanoseconds given (Go service): microseconds kept
    if dot:
        digits = len(rest) - len(rest.lstrip("0123456789"))
        text = f"{head}.{rest[:min(digits, 6)]}{rest[digits:]}"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return math.nan
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.timestamp()


class SignIn(NamedTuple):
    """Answer of a sign in: token for other reads, its expiry (seconds since epoch), ranks of player"""

    token: str
    expiry: float
    player: DriverRanks | None


def player_ranks(data: Any) -> DriverRanks | None:
    """Ranks of RaceControl player data, None if no rank"""
    if not isinstance(data, dict):
        return None
    driver, safety = parse_rank(data.get("driverRank")), parse_rank(data.get("safetyRank"))
    if driver is None and safety is None:
        return None
    profile = data.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    steam_id = ""
    platforms = data.get("platforms")
    if isinstance(platforms, list):
        for platform in platforms:
            if isinstance(platform, dict) and platform.get("platform") == "steam":
                value = platform.get("id")
                steam_id = str(value) if isinstance(value, int) and not isinstance(value, bool) else _text(value)
                break
    return DriverRanks(
        name=_text(data.get("name")) or _text(data.get("username")),
        steam_id=steam_id,
        driver_id=_text(data.get("id")),
        nationality=_text(profile.get("nationality")),
        driver=driver,
        safety=safety,
        badge=_text(profile.get("badge")),
    )


class _Flight:
    """Sign in running (one at a time): callers asking meanwhile wait for its answer"""

    __slots__ = ("done", "generation", "result")

    def __init__(self, generation: int):
        self.generation = generation  # client generation when started: answer dropped if changed meanwhile
        self.done = threading.Event()
        self.result: SignIn | None = None


class RaceOSClient:
    """RaceControl reads: player ranks signed in with a new game ticket for each read (current ranks), token of
    last sign in kept a while for other reads (blocking calls)

    One sign in at a time (single flight): a caller asking while one runs waits for its answer instead of signing in
    again. Lock held only to read & change state, never during requests (forget & token never wait for the network).

    Args:
        ticket: function giving a Steam ticket of the game ("" if game not running or no answer).
        http: request function (tests).
        clock: time function (tests).
        user_agent: User-Agent header.
        wall_clock: time function giving seconds since epoch (tests).
    """

    def __init__(self, ticket: Callable[[], str], http: Http = http_request,
                 clock: Callable[[], float] = time.monotonic, user_agent: str = "NeoPedal",
                 wall_clock: Callable[[], float] = time.time):
        self._ticket = ticket
        self._http = http
        self._clock = clock
        self._wall_clock = wall_clock
        self._user_agent = user_agent
        self._lock = threading.Lock()
        self._account = ""  # game account (SteamID64) of last sign in
        self._retry_time = -1.0  # no sign in before this time (failed before), -1 if none
        self._retry_wait = RETRY_SECONDS
        self._refused_wait = RETRY_SECONDS  # wait after a refused new token, doubled each refusal until a read
        self._sign_ins = 0  # sign ins done: token of a request new (signed in for it) or kept
        self._signed: SignIn | None = None  # last sign in (token kept in memory only)
        self._generation = 0  # incremented when state forgotten (option off, account switched): running sign in dropped
        self._flight: _Flight | None = None  # sign in running, None if none
        self.no_account = False  # service answered: no RaceControl account for this player

    def forget(self) -> None:
        """Failures & token forgotten (option turned off): signed in at once next time (sign in running dropped)"""
        with self._lock:
            self._account, self._retry_time, self._retry_wait = "", -1.0, RETRY_SECONDS
            self._refused_wait = RETRY_SECONDS
            self._signed = None
            self._generation += 1

    def fetch(self, account: str = "") -> DriverRanks | None:
        """Ranks of player of game account in use ("" if unknown), None if not read (offline, game not running,
        no account, waiting after a failure)"""
        signed = self.sign_in(account)
        return signed.player if signed is not None else None

    def token(self, account: str = "") -> str:
        """Token of last sign in while valid, else of a new sign in, "" if not signed in"""
        with self._lock:
            signed = self._signed
            if (signed is not None and account == self._account
                    and self._wall_clock() < signed.expiry - TOKEN_MARGIN):
                return signed.token
        signed = self.sign_in(account)
        return signed.token if signed is not None else ""

    def sign_in(self, account: str = "") -> SignIn | None:
        """New sign in with a game ticket (answer of the one running if any), None if not signed in"""
        with self._lock:
            if account != self._account:  # Steam account switched: failures & token of other account forgotten
                self._account, self._retry_time, self._retry_wait = account, -1.0, RETRY_SECONDS
                self._refused_wait = RETRY_SECONDS
                self._signed = None
                self.no_account = False
                self._generation += 1
            now = self._clock()
            if self._retry_time >= 0 and now < self._retry_time:
                return None
            flight = self._flight
            joined = flight is not None and flight.generation == self._generation
            if not joined:  # none running (or one of a forgotten state, its answer dropped): this one signs in
                flight = self._flight = _Flight(self._generation)
        assert flight is not None
        if joined:
            flight.done.wait(FLIGHT_WAIT)
            return flight.result
        try:
            flight.result = self._sign_in(now, flight.generation)
        finally:
            with self._lock:
                if self._flight is flight:
                    self._flight = None
            flight.done.set()
        return flight.result

    def _sign_in(self, now: float, generation: int) -> SignIn | None:
        """Requests of a sign in started at clock time now (no lock held), answer applied unless state forgotten
        meanwhile (generation changed)"""
        try:
            ticket = self._ticket()
        except Exception:  # any error of game request: game not running
            ticket = ""
        if not ticket:  # game not running: tried again next time asked (no wait, no request made)
            return None
        body = json.dumps({"token": ticket, "game": "lmu", "platform": "steam"}).encode()
        headers = {"User-Agent": self._user_agent, "Accept": "application/json",
                   "Content-Type": "application/json"}
        status, answer = self._http("POST", AUTH_URL, body, headers, TIMEOUT)
        data = _json(answer) if status == 200 else None
        token = _text(data.get("accessToken")) if isinstance(data, dict) else ""
        signed = None
        if token:
            assert isinstance(data, dict)
            expiry = parse_time(data.get("expiresAt"))
            if math.isnan(expiry):
                expiry = self._wall_clock() + TOKEN_SECONDS
            signed = SignIn(token, expiry, player_ranks(data.get("player")))
        with self._lock:
            if generation != self._generation:  # option turned off or account switched meanwhile: answer dropped
                return None
            if status == 404:
                logger.info("RACEOS: no RaceControl account for this player")
                self.no_account = True
                self._retry_time = now + NO_ACCOUNT_SECONDS
                return None
            if signed is None:
                logger.info("RACEOS: sign in failed (status %s)", status)
                self._retry_time = now + self._retry_wait
                self._retry_wait = min(self._retry_wait * 2, RETRY_MAX_SECONDS)
                return None
            self._retry_time, self._retry_wait = -1.0, RETRY_SECONDS
            self.no_account = False
            self._signed = signed
            self._sign_ins += 1
            return signed

    def get(self, path: str, account: str = "") -> Any:
        """JSON answer of a RaceControl GET (path without leading slash), None if not read"""
        return self._request("GET", path, None, account)

    def post(self, path: str, payload: Any, account: str = "") -> Any:
        """JSON answer of a RaceControl POST of JSON payload (path without leading slash), None if not read"""
        return self._request("POST", path, json.dumps(payload).encode(), account)

    def _request(self, method: str, path: str, body: bytes | None, account: str) -> Any:
        sign_ins = self._sign_ins
        token = self.token(account)
        new_token = self._sign_ins != sign_ins
        if not token:
            return None
        headers = {"User-Agent": self._user_agent, "Accept": "application/json",
                   "Game-Authorization": f"Bearer {token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, answer = self._http(method, f"{RACEOS_URL}/{path}", body, headers, TIMEOUT)
        if status in (401, 403):  # token refused: new sign in next time
            with self._lock:
                self._signed = None
                if new_token:  # refused at once (account refused by the service): waited, never every check
                    self._retry_time = self._clock() + self._refused_wait
                    self._refused_wait = min(self._refused_wait * 2, RETRY_MAX_SECONDS)
        elif status == 200:
            with self._lock:
                self._refused_wait = RETRY_SECONDS
        if status != 200:
            logger.info("RACEOS: %s not read (status %s)", path.split("?", 1)[0], status)
            return None
        return _json(answer)


def game_ticket(fetch: Callable[[str], tuple[int, bytes]]) -> str:
    """Steam ticket of game (fetch: GET route of game Rest API -> status & body), "" if none"""
    status, body = fetch(TICKET_ROUTE)
    data = _json(body) if status == 200 else None
    return _text(data.get("authSessionTicket")) if isinstance(data, dict) else ""
