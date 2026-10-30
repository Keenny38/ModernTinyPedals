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
Remote control command server (Stream Deck, button box, SimHub, Companion...)

Local HTTP server, disabled by default, only listens on 127.0.0.1:
    GET  /commands         -> list available command names (JSON)
    POST /command/<name>   -> run command, requires "X-NeoPedal" request header ("X-NeoPedal" also accepted)
    GET  /stream           -> WebSocket, pushes live telemetry JSON
                              query: interval=ms, fields=speed,gear (only these fields),
                              changes=1 (only fields changed since last message, nothing if none)
                              client text message {"fields": [...] or null, "changes": bool} updates options

The required header prevents web pages opened in browser from triggering commands,
as browsers cannot send custom header to other site without CORS approval.
Optional access token (enable_access_token, off by default): header value must then be the token, for commands
and the stream (stream also accepts ?token=, browsers cannot set WebSocket headers), so other programs or other
Windows users of this computer cannot run commands nor read telemetry.
Without a token, commands with an app-wide effect (quit or restart the app, restart or switch the API, load a
preset: TOKEN_REQUIRED_COMMANDS) are refused with 403 "token required": any local process could otherwise close
the app or change its preset mid-race. Overlay, module, spectate & director commands stay available.
Host header is also verified, to block DNS rebinding (malicious domain resolved to 127.0.0.1).
WebSocket is not covered by CORS, so /stream also rejects browser pages from other origins,
and "null" origin (sandboxed frame of any web site, page opened from a local file): only pages
of the app's own local servers (remote control, web dashboard, stream overlay ports, on
http(s)://localhost or 127.0.0.1) and clients without Origin can read telemetry.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import re
import secrets
import select
import socket
import socketserver
import struct
import sys
import threading
from collections.abc import Callable, Collection
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
from time import monotonic
from urllib.parse import parse_qs, unquote, urlsplit

from PySide6.QtCore import QTimer

from . import app_signal
from .const_app import LEGACY_NAME
from .const_file import ConfigType
from .http_limits import DeadlineReader
from .log_handler import ErrorThrottle
from .setting import cfg
from .validator import load_json_strict

logger = logging.getLogger(__name__)
snapshot_errors = ErrorThrottle()  # stream pushes snapshots every 100 ms: warning once a minute

HOST = "127.0.0.1"
REQUIRED_HEADER = "X-NeoPedal"
LEGACY_HEADER = f"X-{LEGACY_NAME}"  # still accepted: tools set up before the NeoPedal name
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_OP_TEXT = 0x1
WS_OP_CLOSE = 0x8
WS_OP_PING = 0x9
WS_OP_PONG = 0xA
SERVE_POLL_INTERVAL = 0.5  # s, server loop stop check (waited by a worker thread on stop, never by the GUI)
STOP_WAIT_SECONDS = SERVE_POLL_INTERVAL + 1.0  # stop(wait=True) & wait_servers_stopped wait this at most
# New server on the port of one still stopping (GUI: address or HTTPS setting changed) waits this at most for the
# previous socket to close (milliseconds: stop wakes the serving loop at once), then is tried again by BindRetry
CLOSING_WAIT_SECONDS = 0.5
CLOSING_RETRY_MS = 100  # previous server of the port still closing: listening tried again this soon (no report)
SHUTDOWN_WAKE_SECONDS = 0.05  # serving loop woken again this often until shutdown() returns
STREAM_INTERVAL = 100  # ms, default push interval
STREAM_KEEPALIVE = 2.0  # s, same telemetry sent again at most this often (full data stream: unchanged data held)
STREAM_INTERVAL_RANGE = (20, 5000)
SNAPSHOT_TICK_MS = STREAM_INTERVAL_RANGE[0]  # telemetry snapshot & its JSON shared by stream clients within a tick
# Port unavailable: listening tried again this often while enabled. Windows holds a port bound exclusively
# until connections accepted by the previous server are gone (TIME_WAIT, up to 4 minutes after app restart)
BIND_RETRY_MS = 5000
# Open connections refused above these (slow or idle clients never use up threads & memory),
# connections from this computer are only counted in server limit (browser sources, local tools)
MAX_CONNECTIONS = 64
MAX_CONNECTIONS_PER_ADDRESS = 16
REQUEST_SECONDS = 10  # request (line, headers, body) received in this time once started, or connection closed
MAX_POST_BODY = 65536  # bytes of command request body read (ignored), more never read
TOKEN_BYTES = 18  # random bytes of a generated access token (24 characters)
MIN_TOKEN_LENGTH = 16  # shorter access token in config replaced by a generated one
# Commands run only with an access token (see module doc): app closed or restarted, API restarted or switched,
# preset loaded (preset_1..10 shortcuts too, see token_required)
TOKEN_REQUIRED_COMMANDS = frozenset((
    "quit_application", "restart_application", "restart_api", "select_next_api", "select_previous_api",
    "reload_preset", "load_next_preset", "load_previous_preset",
))
TOKEN_REQUIRED_PREFIX = "preset_"


def token_required(name: str) -> bool:
    """Command refused without an access token (app-wide effect)"""
    return name in TOKEN_REQUIRED_COMMANDS or name.startswith(TOKEN_REQUIRED_PREFIX)


def is_loopback(address: str) -> bool:
    """Client address of this computer"""
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


class PortClosing(OSError):
    """Previous server of the port still closing its socket: listening tried again soon (BindRetry), no report"""

    def __init__(self, port: int):
        super().__init__(errno.EADDRINUSE, f"port {port} still closing")


class LocalHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server, port held exclusively on Windows, open connections tracked & limited

    SO_REUSEADDR on Windows lets a second server bind a listening port in use,
    SO_EXCLUSIVEADDRUSE makes bind fail instead (port unavailable reported).

    Connections above max_connections (or max_connections_per_address from another computer) are closed
    at once, never given a thread.

    server_close() only closes the listening socket: stop() also ends open (keep-alive, streaming)
    connections, and sets this server's own stopping event (a new server never clears it).

    A server made on the port of one still stopping (same port turned off & on again by the GUI) waits for its
    socket to close for CLOSING_WAIT_SECONDS at most (milliseconds: shutdown() wakes the serving loop at once
    instead of waiting its poll interval), then raises PortClosing: BindRetry tries again soon, nothing reported.
    """

    daemon_threads = True
    max_connections = MAX_CONNECTIONS
    max_connections_per_address = MAX_CONNECTIONS_PER_ADDRESS

    if sys.platform == "win32":
        allow_reuse_address = False

    _closing: dict[int, threading.Event] = {}  # port: closed event of a server stopping (worker thread)
    _closing_lock = threading.Lock()

    def serve_forever(self, poll_interval: float = SERVE_POLL_INTERVAL):
        """Serve until stop(): its worker thread waits up to poll_interval for the serving loop"""
        super().serve_forever(poll_interval)

    def server_bind(self):
        """Bind without host name lookup: HTTPServer looks up server_name (getfqdn, never used here),
        which blocks the GUI thread with a slow DNS, and raises UnicodeDecodeError (not OSError) for a
        non ASCII Windows computer name"""
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port

    def __init__(self, server_address, *args, **kwargs):
        self.stopping = threading.Event()  # long running handlers (stream) end when set
        self.closed = threading.Event()  # listening socket & connections closed (set by stop's worker thread)
        self._connections: dict[socket.socket, str] = {}  # open connection: client address
        self._connections_lock = threading.Lock()
        port = self.port_of(server_address)
        with LocalHTTPServer._closing_lock:
            closing = LocalHTTPServer._closing.get(port)
        # Same port turned off & on again: previous server's socket closed first (GUI thread never held long)
        if closing is not None and not closing.wait(CLOSING_WAIT_SECONDS):
            raise PortClosing(port)
        super().__init__(server_address, *args, **kwargs)

    @staticmethod
    def port_of(server_address) -> int:
        try:
            return int(server_address[1])
        except (IndexError, TypeError, ValueError):
            return -1

    def verify_request(self, request, client_address):
        """Accept connection if under limits (refused connection closed by caller)"""
        address = str(client_address[0])
        with self._connections_lock:
            if self.stopping.is_set():  # stopping: never a new client (nor the wake connection of shutdown)
                refused = "stopping"
            elif len(self._connections) >= self.max_connections:
                refused = "server"
            elif not is_loopback(address) and sum(
                    1 for client in self._connections.values() if client == address
            ) >= self.max_connections_per_address:
                refused = "address"
            else:
                self._connections[request] = address
                return True
        logger.debug("%s: connection from %s refused (%s)", type(self).__name__, address,
                     refused if refused == "stopping" else f"{refused} connection limit")
        return False

    def shutdown_request(self, request):
        with self._connections_lock:
            self._connections.pop(request, None)
        super().shutdown_request(request)

    def shutdown(self):
        """End the serving loop now: BaseServer.shutdown only sets a flag the loop checks after its select wakes
        (up to poll_interval later), so a loopback connection to the listening socket wakes it at once. The
        connection is never served: the flag is checked before accepting, and verify_request refuses connections
        once stopping is set (stop() sets it before calling this).
        """
        finish = super().shutdown
        waiter = threading.Thread(target=finish, daemon=True, name=f"{type(self).__name__} shutdown")
        waiter.start()
        while waiter.is_alive():
            self.__wake_serving()
            waiter.join(SHUTDOWN_WAKE_SECONDS)

    def __wake_serving(self):
        host, port = self.server_address[:2]
        if host in ("", "0.0.0.0"):
            host = "127.0.0.1"
        with suppress(OSError, ValueError):  # socket closed already, port not reachable: loop wakes by itself
            socket.create_connection((str(host), int(port)), timeout=SHUTDOWN_WAKE_SECONDS).close()

    def close_connections(self):
        """Shut down open client connections (handler threads see connection closed)"""
        with self._connections_lock:
            connections = tuple(self._connections)
            self._connections.clear()
        for sock in connections:
            with suppress(OSError):  # TLS socket: plain socket shutdown, TLS state left to handler thread
                socket.socket.shutdown(sock, socket.SHUT_RDWR)

    def stop(self, wait: bool = False):
        """Stop serving, close listening socket & open connections in a worker thread (serving loop ends within
        SERVE_POLL_INTERVAL, never waited by the GUI thread). Handlers see stopping set at once.

        Args:
            wait: return once closed (app quitting, tests).
        """
        self.stopping.set()
        port = self.port_of(self.server_address)
        with LocalHTTPServer._closing_lock:
            LocalHTTPServer._closing[port] = self.closed
        self.close_connections()  # clients see the end at once (again once listening socket closed)
        worker = threading.Thread(target=self.__close, args=(port,), daemon=True, name=f"{type(self).__name__} stop")
        worker.start()
        if wait:
            self.closed.wait(STOP_WAIT_SECONDS)

    def __close(self, port: int):
        try:
            self.shutdown()
            self.server_close()
            self.close_connections()
        except Exception:  # never left half closed silently
            logger.debug("%s: stop failed", type(self).__name__, exc_info=True)
        finally:
            self.closed.set()
            with LocalHTTPServer._closing_lock:
                if LocalHTTPServer._closing.get(port) is self.closed:
                    del LocalHTTPServer._closing[port]


def wait_servers_stopped(timeout: float = STOP_WAIT_SECONDS) -> bool:
    """Servers stopping (see LocalHTTPServer.stop) closed, False if one is still closing after timeout"""
    deadline = monotonic() + timeout
    with LocalHTTPServer._closing_lock:
        events = list(LocalHTTPServer._closing.values())
    return all(event.wait(max(deadline - monotonic(), 0)) for event in events)


class BoundedRequestHandler(BaseHTTPRequestHandler):
    """Request handler, a started request (line, headers, body) received within REQUEST_SECONDS

    Socket timeout alone lets a client sending a byte now and then hold a connection forever (slowloris).
    Waiting for next request of a kept connection (keep-alive) only bounded by socket timeout.
    Server header never tells the Python version.
    """

    request_seconds: float = REQUEST_SECONDS
    server_version = "NeoPedal"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def setup(self):
        super().setup()
        self.rfile.close()  # replaced, reads bounded by request deadline
        self._reader = DeadlineReader(self.connection)
        self.rfile = io.BufferedReader(self._reader)

    def handle_one_request(self):
        self._reader.deadline = None
        try:
            self.rfile.peek(1)  # type: ignore[attr-defined]  # next request started (idle: socket timeout)
        except TimeoutError:
            self.close_connection = True
            return
        self._reader.deadline = monotonic() + self.request_seconds
        try:
            super().handle_one_request()
        finally:
            self._reader.deadline = None


class BindRetry:
    """Server listening tried again later while its port is unavailable, error reported once per address

    Args:
        name: server name in error message.
        start: called to listen again (server enable).
    """

    __slots__ = ("name", "_start", "_timer", "_failed")

    def __init__(self, name: str, start: Callable[[], None]):
        self.name = name
        self._start = start
        self._timer: QTimer | None = None
        self._failed: tuple | None = None  # unavailable address reported (not at every retry)

    @property
    def failing(self) -> bool:
        """Last listening attempt failed (port unavailable)"""
        return self._failed is not None

    def failed(self, address: tuple[str, int], error: Exception):
        """Bind failed: report (once for this address), try again later if port may become available

        Previous server of the port still closing (PortClosing): tried again at once (CLOSING_RETRY_MS), not
        reported (normal while a setting changes), nor remembered as a failure.
        """
        if isinstance(error, PortClosing):
            logger.debug("%s: port %s still closing, listening tried again soon", self.name.upper(), address[1])
            self._schedule(CLOSING_RETRY_MS)
            return
        if self._failed != address:
            self._failed = address
            logger.error("%s: unable to listen on %s:%s (%s)", self.name.upper(), *address, error)
            app_signal.error.emit(f"{self.name}: port {address[1]} unavailable ({bind_error_text(error)}).")
        if isinstance(error, OSError):  # OverflowError (port out of range) never changes
            self._schedule(BIND_RETRY_MS)

    def _schedule(self, delay_ms: int):
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._start)
        self._timer.start(delay_ms)

    def listening(self):
        """Listening: nothing tried again, next failure reported, status shown again if listening after failure"""
        failed = self._failed is not None
        self.stop()
        if failed:
            logger.info("%s: listening again", self.name.upper())
            app_signal.servers.emit()

    def stop(self):
        """Server disabled: nothing tried again, next failure reported"""
        self._failed = None
        if self._timer is not None:
            self._timer.stop()


def available_commands() -> dict[str, Callable]:
    """Available commands (same as hotkey commands): name -> function"""
    from .hotkey.command import COMMANDS_GENERAL, COMMANDS_MODULE, COMMANDS_PRESET, COMMANDS_WIDGET

    return dict(chain(COMMANDS_GENERAL, COMMANDS_PRESET, COMMANDS_MODULE, COMMANDS_WIDGET))


# Secret values of a request query (web dashboard access code, stream overlay token): never logged
SECRET_QUERY = re.compile(r"([?&](?:code|token|access_code|access_token)=)[^&\s#\"']*", re.IGNORECASE)


def redact_secret_query(text: str) -> str:
    """Text (request line, URL) with access code & token query values replaced"""
    return SECRET_QUERY.sub(r"\1<redacted>", text)


def bind_error_text(error: Exception) -> str:
    """Server bind error reason (OverflowError has no strerror)"""
    return getattr(error, "strerror", None) or str(error)


# Host header: name or IPv4 address, or [IPv6 address], optional port (no user info, no path)
HOST_HEADER = re.compile(r"(\[[0-9a-fA-F:.]+\]|[A-Za-z0-9._-]+)(?::([0-9]{1,5}))?")
LOOPBACK_NAMES = frozenset(("localhost", "127.0.0.1"))


def own_host_names() -> frozenset[str]:
    """Names of this computer a LAN device can open a page with (computer name, its .local mDNS name), lower case

    Never a DNS lookup (socket.gethostname only): called on the GUI thread.
    """
    names: set[str] = set()
    try:
        name = socket.gethostname().strip().lower().rstrip(".")
    except (OSError, UnicodeError):
        return frozenset()
    if name:
        short = name.split(".", 1)[0]
        names.update((name, short, f"{short}.local"))
    return frozenset(names)


def is_allowed_host(host: str | None, port: int, lan: bool = False, names: Collection[str] = ()) -> bool:
    """Check request Host header (DNS rebinding protection): a malicious domain resolved to this computer is refused

    Allowed: localhost & loopback addresses; with LAN access, also any IP address (DNS rebinding needs a domain
    name) and names of this computer (names, see own_host_names). Port, if given, must be the server port.

    Args:
        lan: server reachable from the local network.
        names: own host names allowed with LAN access (lower case).
    """
    if not host:
        return False
    match = HOST_HEADER.fullmatch(host.strip())
    if match is None:
        return False
    name, port_text = match.group(1).lower(), match.group(2)
    if port_text is not None and int(port_text) != port:
        return False
    if name.startswith("["):
        name = name[1:-1]
    else:
        name = name.rstrip(".")  # "localhost." is the same name
    if name in LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return lan and name in names
    return address.is_loopback or lan


# Local servers of the app whose pages may read the stream: setting section, port option
OWN_PAGE_PORTS = (
    ("remote_control", "remote_control_port"),
    ("web_dashboard", "web_dashboard_port"),
    ("stream_overlay", "stream_overlay_port"),
)
DEFAULT_PORTS = {"http": 80, "https": 443}


# Server object of each page server (module, instance): its port allowed only while it runs
PAGE_SERVERS = {
    "web_dashboard": ("web_dashboard", "webdashboard"),
    "stream_overlay": ("stream_overlay", "streamoverlay"),
}


def own_server_running(section: str) -> bool:
    """Server of section running: remote control (serving the stream itself) always, others while listening (a
    server turned off or not started leaves its port to any other program, its pages never allowed)"""
    names = PAGE_SERVERS.get(section)
    if names is None:
        return True
    module = sys.modules.get(f"{__package__}.{names[0]}")  # never imported: never started
    return bool(getattr(getattr(module, names[1], None), "running", False))


def own_page_ports() -> set[int]:
    """Ports of the app's own local servers running (current setting)"""
    config = getattr(cfg.user, "config", None) or {}
    ports = set()
    for section, key in OWN_PAGE_PORTS:
        if not own_server_running(section):
            continue
        with suppress(KeyError, TypeError, ValueError):
            ports.add(int(config[section][key]))
    return ports


def is_allowed_origin(origin: str | None, ports: Collection[int] | None = None) -> bool:
    """Allow non-browser clients (no Origin) and pages of the app's own local servers only

    Origin "null" (sandboxed frame of any site, local file) and other local pages (any program
    serving a page on another port of this computer) are refused.

    Args:
        ports: allowed ports, None for ports of own servers in current setting.
    """
    if origin is None:
        return True
    try:
        parts = urlsplit(origin.strip().lower())
        port = parts.port or DEFAULT_PORTS.get(parts.scheme)
    except ValueError:  # invalid port
        return False
    if parts.scheme not in DEFAULT_PORTS or parts.hostname not in {"127.0.0.1", "localhost"}:
        return False
    return port in (own_page_ports() if ports is None else ports)


def websocket_accept(key: str) -> str:
    """Sec-WebSocket-Accept value for client key"""
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def websocket_frame(payload: bytes, opcode: int = WS_OP_TEXT) -> bytes:
    """Encode unmasked server frame"""
    size = len(payload)
    if size < 126:
        head = struct.pack("!BB", 0x80 | opcode, size)
    elif size < 65536:
        head = struct.pack("!BBH", 0x80 | opcode, 126, size)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 127, size)
    return head + payload


def read_exact(sock: socket.socket, size: int) -> bytes:
    """Read exactly size bytes, raise ConnectionError if closed"""
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("connection closed")
        data += chunk
    return data


class FrameSource:
    """Client bytes of a WebSocket: those the request reader buffered past the upgrade request first (a client
    sending its first frames without waiting for the 101 answer), then the socket"""

    __slots__ = ("sock", "buffered")

    def __init__(self, sock: socket.socket, buffered: bytes = b""):
        self.sock = sock
        self.buffered = buffered

    def ready(self, timeout: float) -> bool:
        """Frame bytes available (buffered, or readable on the socket within timeout seconds)"""
        if self.buffered:
            return True
        readable, _, _ = select.select([self.sock], [], [], max(timeout, 0.0))
        return bool(readable)

    def read_exact(self, size: int) -> bytes:
        """Read exactly size bytes, raise ConnectionError if closed"""
        data, self.buffered = self.buffered[:size], self.buffered[size:]
        if len(data) < size:
            data += read_exact(self.sock, size - len(data))
        return data


def unmask(data: bytes, mask: bytes) -> bytes:
    """Client payload unmasked (XOR with the 4 byte mask): whole-integer XOR, no Python loop per byte"""
    size = len(data)
    if not size:
        return data
    key = (mask * (size // 4 + 1))[:size]
    return (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(size, "big")


def read_websocket_frame(source: socket.socket | FrameSource) -> tuple[int, bytes]:
    """Read one client frame (masked), return opcode & payload"""
    if not isinstance(source, FrameSource):
        source = FrameSource(source)
    first, second = source.read_exact(2)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", source.read_exact(2))[0]
    elif size == 127:
        size = struct.unpack("!Q", source.read_exact(8))[0]
    if size > 65536:
        raise ConnectionError("frame too large")
    mask = source.read_exact(4) if second & 0x80 else bytes(4)
    return first & 0x0F, unmask(source.read_exact(size), mask)


def stream_interval(path: str) -> float:
    """Push interval (seconds) from ?interval=ms query"""
    query = parse_qs(urlsplit(path).query)
    try:
        interval = int(query.get("interval", [str(STREAM_INTERVAL)])[0])
    except ValueError:
        interval = STREAM_INTERVAL
    low, high = STREAM_INTERVAL_RANGE
    return min(max(interval, low), high) / 1000


class StreamOptions:
    """Stream subscription: selected fields, changes only"""

    __slots__ = ("fields", "changes", "last")

    def __init__(self, fields: list[str] | None = None, changes: bool = False):
        self.fields = set(fields) if fields else None
        self.changes = changes
        self.last: dict = {}

    @classmethod
    def from_path(cls, path: str) -> StreamOptions:
        """Options from ?fields=a,b&changes=1 query"""
        query = parse_qs(urlsplit(path).query)
        fields = [name for value in query.get("fields", []) for name in value.split(",") if name]
        changes = query.get("changes", ["0"])[0].lower() in ("1", "true", "yes")
        return cls(fields, changes)

    def update(self, message: bytes) -> bool:
        """Update options from client JSON message, ignore invalid message (also nested too deeply)

        Returns:
            True if options were updated (data sent at once).
        """
        try:
            data = load_json_strict(message)
        except ValueError:  # UnicodeDecodeError & RecursionError too
            return False
        if not isinstance(data, dict):
            return False
        if "fields" in data:
            fields = data["fields"]
            # Names only: str() of a nested list could recurse too deeply
            names = {name for name in fields if isinstance(name, str)} if isinstance(fields, list) else set()
            self.fields = names or None
        if "changes" in data:
            self.changes = bool(data["changes"])
        self.last = {}  # send full data after change
        return True

    def payload(self, data: dict) -> dict | None:
        """Data to send, None if nothing changed (changes only)"""
        if self.fields is not None:
            data = {name: value for name, value in data.items() if name in self.fields}
        if not self.changes:
            return data
        changed = {name: value for name, value in data.items() if self.last.get(name, ...) != value}
        self.last = data
        return changed or None


def default_snapshot() -> dict:
    """Live telemetry, same data as web dashboard"""
    from .web_dashboard import telemetry_snapshot

    return telemetry_snapshot()


class SnapshotCache:
    """Telemetry snapshot (~40 API reads) & its JSON shared by every stream client within a tick (SNAPSHOT_TICK_MS):
    N clients cost one snapshot & one encoding per tick, not N. Snapshot errors never break a stream."""

    __slots__ = ("_lock", "_key", "_data", "_encoded")

    def __init__(self):
        self._lock = threading.Lock()
        self._key: tuple | None = None  # (snapshot function, tick)
        self._data: dict = {}
        self._encoded: bytes | None = None

    def data(self, snapshot: Callable[[], dict], now: float) -> dict:
        """Snapshot of the tick of now (monotonic seconds), shared: never modified by callers"""
        key = (snapshot, int(now * 1000) // SNAPSHOT_TICK_MS)
        with self._lock:
            if key == self._key:
                return self._data
        try:
            data = snapshot()
        except Exception:  # never break stream on bad telemetry
            snapshot_errors.log(logger, "REMOTE CONTROL: snapshot error")
            data = {"active": False}
        with self._lock:
            if key != self._key:  # two clients computed the same tick at once: either one kept
                self._key, self._data, self._encoded = key, data, None
            return self._data

    def encoded(self, data: dict) -> bytes:
        """JSON of data, encoded once per tick if data is the shared snapshot"""
        with self._lock:
            if data is self._data and self._encoded is not None:
                return self._encoded
        encoded = json.dumps(data).encode("utf-8")
        with self._lock:
            if data is self._data:
                self._encoded = encoded
        return encoded


snapshot_cache = SnapshotCache()


class CommandHandler(BoundedRequestHandler):
    """Command request handler"""

    timeout = 15  # idle client releases its thread
    stream_timeout = 5  # WebSocket send timeout, server can stop a stream to a stalled client
    commands: dict[str, Callable] = {}
    snapshot: Callable[[], dict] = staticmethod(default_snapshot)
    token = ""  # access token required in X-NeoPedal header, "" if not required (header only needed)

    def check_host(self) -> bool:
        """Verify Host header, send 403 if not allowed"""
        if is_allowed_host(self.headers.get("Host"), getattr(self.server, "server_port", 0)):
            return True
        self.send_json(403, {"error": "host not allowed"})
        return False

    def header_value(self) -> str | None:
        """Value of X-NeoPedal (or legacy) header, None if not sent"""
        value = self.headers.get(REQUIRED_HEADER)
        return value if value is not None else self.headers.get(LEGACY_HEADER)

    def token_ok(self, value: str | None) -> bool:
        """Header (or query) value matches access token, any value if no token required"""
        if value is None:
            return False
        token = self.token
        if not token:
            return True
        return hmac.compare_digest(value.strip().encode("utf-8"), token.encode("utf-8"))

    def do_GET(self):
        """List commands"""
        if not self.check_host():
            return
        route = urlsplit(self.path).path.rstrip("/")
        if route == "/commands":
            names = sorted(self.commands)
            self.send_json(200, {"commands": names, "token_required": [name for name in names if token_required(name)]})
        elif route == "/stream":
            self.stream()
        else:
            self.send_json(404, {"error": "not found"})

    def read_body(self) -> None:
        """Read (and ignore) request body, so client gets the response instead of a connection reset"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:  # bad header: no body read
            return
        length = min(length, MAX_POST_BODY)
        if length > 0:
            with suppress(OSError):  # client gone or too slow (handler timeout)
                self.rfile.read(length)

    def do_POST(self):
        """Run command"""
        self.read_body()
        if not self.check_host():
            return
        route = urlsplit(self.path).path
        if not route.startswith("/command/"):
            self.send_json(404, {"error": "not found"})
            return
        value = self.header_value()
        if value is None:
            self.send_json(403, {"error": f"missing {REQUIRED_HEADER} header"})
            return
        if not self.token_ok(value):
            self.send_json(403, {"error": f"invalid access token in {REQUIRED_HEADER} header"})
            return
        name = unquote(route[len("/command/"):]).strip("/")
        command = self.commands.get(name)
        if command is None:
            self.send_json(404, {"error": f"unknown command: {name}"})
            return
        if not self.token and token_required(name):  # app-wide effect: never for any local process
            logger.warning("REMOTE CONTROL: %s refused, access token required (Remote control settings)", name)
            self.send_json(403, {"error": "token required", "command": name,
                                 "detail": "enable the access token in Remote control settings to run this command"})
            return
        app_signal.hotkey.emit(command)  # run in main (GUI) thread
        logger.info("REMOTE CONTROL: %s", name)
        self.send_json(200, {"ok": True, "command": name})

    def stream(self):
        """Upgrade to WebSocket and push telemetry until client leaves or server stops"""
        key = self.headers.get("Sec-WebSocket-Key")
        if self.headers.get("Upgrade", "").lower() != "websocket" or not key:
            self.send_json(426, {"error": "websocket upgrade required"})
            return
        if not is_allowed_origin(self.headers.get("Origin")):
            self.send_json(403, {"error": "origin not allowed"})
            return
        if self.token:  # header, or query of a browser page (WebSocket of browsers sends no custom header)
            value = self.header_value()
            if value is None:
                value = parse_qs(urlsplit(self.path).query).get("token", [None])[0]
            if not self.token_ok(value):
                self.send_json(403, {"error": "invalid access token"})
                return
        self.protocol_version = "HTTP/1.1"  # WebSocket clients require 1.1 status line
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", websocket_accept(key))
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        interval = stream_interval(self.path)
        options = StreamOptions.from_path(self.path)
        sock = self.connection
        source = FrameSource(sock, self.buffered_input())  # frames sent before the 101 answer never lost
        sock.settimeout(self.stream_timeout)  # client not reading: sendall times out (OSError), never blocks
        # Event of this server: a server started again (reload, port changed) never revives an old stream
        stopping: threading.Event = getattr(self.server, "stopping", None) or threading.Event()
        logger.info("REMOTE CONTROL: stream client connected (%sms)", round(interval * 1000))
        last_sent = b""  # full data stream: same message held, sent again every STREAM_KEEPALIVE (game closed)
        sent_at = 0.0
        snapshot = self.snapshot
        try:
            # Frames sent with the upgrade request (options message): applied before the first data
            if self.read_client_frames(source, options, monotonic()) == WS_OP_CLOSE:
                return
            while not stopping.is_set():
                now = monotonic()
                data = snapshot_cache.data(snapshot, now)  # shared by every client of this tick
                message = options.payload(data)
                if message is not None:
                    encoded = snapshot_cache.encoded(message) if message is data else json.dumps(message).encode()
                    if options.changes or encoded != last_sent or now - sent_at >= STREAM_KEEPALIVE:
                        sock.sendall(websocket_frame(encoded))
                        last_sent, sent_at = encoded, now
                # Client frames read until the next send is due: a chatty client never makes the loop spin
                received = self.read_client_frames(source, options, now + interval)
                if received == WS_OP_CLOSE:
                    return
                if received == WS_OP_TEXT:
                    last_sent = b""  # data sent at once after an options message
        except (OSError, ValueError):
            pass  # client gone (ConnectionError is an OSError)
        finally:
            logger.info("REMOTE CONTROL: stream client disconnected")

    def read_client_frames(self, source: FrameSource, options: StreamOptions, until: float) -> int | None:
        """Client frames read & answered until monotonic time until (pings answered, options applied)

        Returns:
            WS_OP_CLOSE once the client closed (close answered), WS_OP_TEXT once options changed (read stops,
            data is sent at once), None when until passed.
        """
        while True:
            remaining = until - monotonic()
            if (remaining <= 0 and not source.buffered) or not source.ready(remaining):
                return None  # until passed (buffered bytes of frames already received are read anyway)
            opcode, payload = read_websocket_frame(source)
            if opcode == WS_OP_TEXT:
                if options.update(payload):
                    return WS_OP_TEXT
            elif opcode == WS_OP_CLOSE:
                self.connection.sendall(websocket_frame(payload[:2], WS_OP_CLOSE))
                return WS_OP_CLOSE
            elif opcode == WS_OP_PING:
                self.connection.sendall(websocket_frame(payload, WS_OP_PONG))
        return None

    def buffered_input(self) -> bytes:
        """Bytes the request reader buffered past the request (frames of a client not waiting for the 101 answer):
        read without waiting (socket made non blocking for the check), reads of the stream never bounded by the
        request deadline"""
        self._reader.deadline = None
        sock = self.connection
        timeout = sock.gettimeout()
        sock.settimeout(0.0)
        try:
            buffered = self.rfile.peek(1)  # type: ignore[attr-defined]  # whole buffer, b"" if empty (no wait)
            return self.rfile.read(len(buffered)) if buffered else b""
        except (OSError, ValueError):
            return b""
        finally:
            sock.settimeout(timeout)

    def send_json(self, status: int, data: dict):
        """Send json response"""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Silence default stderr access log"""
        if logger.isEnabledFor(logging.DEBUG):  # every request: no formatting while not logged
            logger.debug("REMOTE CONTROL: %s", redact_secret_query(format % args))  # stream ?token=


class CommandServer:
    """Command server control"""

    __slots__ = ("_server", "_thread", "_port", "_retry")

    def __init__(self):
        self._server: LocalHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port: int | None = None
        self._retry = BindRetry("Remote control", self.enable)

    @property
    def running(self) -> bool:
        return self._server is not None

    @staticmethod
    def access_token() -> str:
        """Access token required in X-NeoPedal header, "" if not required (enable_access_token off)

        Generated & saved when missing or shorter than MIN_TOKEN_LENGTH.
        """
        setting = cfg.user.config["remote_control"]
        if not setting.get("enable_access_token", False):
            return ""
        token = str(setting.get("access_token", "")).strip()
        if len(token) < MIN_TOKEN_LENGTH:
            if token:
                logger.warning("REMOTE CONTROL: access token shorter than %s characters replaced by a new one",
                               MIN_TOKEN_LENGTH)
            token = secrets.token_urlsafe(TOKEN_BYTES)
            setting["access_token"] = token
            cfg.save(config_type=ConfigType.CONFIG)
        return token

    def enable(self):
        """Start server if enabled in setting, stop it if not (server kept if port unchanged)

        Server kept across reload: a server stopped then started again can find its port still held
        by connections it accepted (Windows), and connected stream clients would be dropped.
        Access token applied to the running server (streams already connected kept).
        """
        setting = cfg.user.config["remote_control"]
        if not setting["enable_remote_control"]:
            self.disable()
            return
        port = int(setting["remote_control_port"])
        if self._server is not None and self._port != port:
            self.disable()
        CommandHandler.commands = available_commands()
        CommandHandler.token = self.access_token()
        if self._server is not None:
            return
        try:
            self._server = LocalHTTPServer((HOST, port), CommandHandler)
        except (OSError, OverflowError) as error:  # OverflowError: port out of range
            self._retry.failed((HOST, port), error)
            return
        self._retry.listening()
        self._port = port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="Remote control")
        self._thread.start()
        logger.info("ENABLED: remote control on http://%s:%s", HOST, port)

    def disable(self):
        """Stop server, end open streams"""
        self._retry.stop()
        if self._server is None:
            return
        self._server.stop()
        self._server = None
        self._thread = None
        self._port = None
        logger.info("DISABLED: remote control")


cmdserver = CommandServer()
