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
Remote control command server (Stream Deck, button box, SimHub, Companion...)

Local HTTP server, disabled by default, only listens on 127.0.0.1:
    GET  /commands         -> list available command names (JSON)
    POST /command/<name>   -> run command, requires "X-TinyPedal" request header
    GET  /stream           -> WebSocket, pushes live telemetry JSON
                              query: interval=ms, fields=speed,gear (only these fields),
                              changes=1 (only fields changed since last message, nothing if none)
                              client text message {"fields": [...] or null, "changes": bool} updates options

The required header prevents web pages opened in browser from triggering commands,
as browsers cannot send custom header to other site without CORS approval.
Host header is also verified, to block DNS rebinding (malicious domain resolved to 127.0.0.1).
WebSocket is not covered by CORS, so /stream also rejects browser pages from other origins,
and "null" origin (sandboxed frame of any web site, page opened from a local file): only pages
served from http://localhost or http://127.0.0.1 (and clients without Origin) can read telemetry.
"""

from __future__ import annotations

import base64
import hashlib
import io
import ipaddress
import json
import logging
import select
import socket
import socketserver
import struct
import sys
import threading
from collections.abc import Callable
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
from time import monotonic
from urllib.parse import parse_qs, unquote, urlsplit

from PySide6.QtCore import QTimer

from . import app_signal
from .setting import cfg

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
REQUIRED_HEADER = "X-TinyPedal"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_OP_TEXT = 0x1
WS_OP_CLOSE = 0x8
WS_OP_PING = 0x9
WS_OP_PONG = 0xA
STREAM_INTERVAL = 100  # ms, default push interval
STREAM_INTERVAL_RANGE = (20, 5000)
# Port unavailable: listening tried again this often while enabled. Windows holds a port bound exclusively
# until connections accepted by the previous server are gone (TIME_WAIT, up to 4 minutes after app restart)
BIND_RETRY_MS = 5000
# Open connections refused above these (slow or idle clients never use up threads & memory),
# connections from this computer are only counted in server limit (browser sources, local tools)
MAX_CONNECTIONS = 64
MAX_CONNECTIONS_PER_ADDRESS = 16
REQUEST_SECONDS = 10  # request (line, headers, body) received in this time once started, or connection closed


def is_loopback(address: str) -> bool:
    """Client address of this computer"""
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


class LocalHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server, port held exclusively on Windows, open connections tracked & limited

    SO_REUSEADDR on Windows lets a second server bind a listening port in use,
    SO_EXCLUSIVEADDRUSE makes bind fail instead (port unavailable reported).

    Connections above max_connections (or max_connections_per_address from another computer) are closed
    at once, never given a thread.

    server_close() only closes the listening socket: stop() also ends open (keep-alive, streaming)
    connections, and sets this server's own stopping event (a new server never clears it).
    """

    daemon_threads = True
    max_connections = MAX_CONNECTIONS
    max_connections_per_address = MAX_CONNECTIONS_PER_ADDRESS

    if sys.platform == "win32":
        allow_reuse_address = False

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

    def __init__(self, *args, **kwargs):
        self.stopping = threading.Event()  # long running handlers (stream) end when set
        self._connections: dict[socket.socket, str] = {}  # open connection: client address
        self._connections_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    def verify_request(self, request, client_address):
        """Accept connection if under limits (refused connection closed by caller)"""
        address = str(client_address[0])
        with self._connections_lock:
            if len(self._connections) >= self.max_connections:
                refused = "server"
            elif not is_loopback(address) and sum(
                    1 for client in self._connections.values() if client == address
            ) >= self.max_connections_per_address:
                refused = "address"
            else:
                self._connections[request] = address
                return True
        logger.debug("%s: connection from %s refused (%s connection limit)", type(self).__name__, address, refused)
        return False

    def shutdown_request(self, request):
        with self._connections_lock:
            self._connections.pop(request, None)
        super().shutdown_request(request)

    def close_connections(self):
        """Shut down open client connections (handler threads see connection closed)"""
        with self._connections_lock:
            connections = tuple(self._connections)
            self._connections.clear()
        for sock in connections:
            with suppress(OSError):  # TLS socket: plain socket shutdown, TLS state left to handler thread
                socket.socket.shutdown(sock, socket.SHUT_RDWR)

    def stop(self):
        """Stop serving, close listening socket & open connections"""
        self.stopping.set()
        self.shutdown()
        self.server_close()
        self.close_connections()


class DeadlineReader(socket.SocketIO):
    """Socket reader, reads fail (TimeoutError) once deadline passed (each read also bounded by socket timeout)"""

    def __init__(self, sock: socket.socket):
        super().__init__(sock, "rb")
        self.deadline: float | None = None  # monotonic time, None: socket timeout only

    def readinto(self, buffer):
        deadline = self.deadline
        if deadline is None:
            return super().readinto(buffer)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("request not received in time")
        sock = self._sock  # type: ignore[attr-defined]
        timeout = sock.gettimeout()
        if timeout is not None and timeout <= remaining:
            return super().readinto(buffer)
        sock.settimeout(remaining)
        try:
            return super().readinto(buffer)
        finally:
            sock.settimeout(timeout)


class BoundedRequestHandler(BaseHTTPRequestHandler):
    """Request handler, a started request (line, headers, body) received within REQUEST_SECONDS

    Socket timeout alone lets a client sending a byte now and then hold a connection forever (slowloris).
    Waiting for next request of a kept connection (keep-alive) only bounded by socket timeout.
    """

    request_seconds: float = REQUEST_SECONDS

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
        """Bind failed: report (once for this address), try again later if port may become available"""
        if self._failed != address:
            self._failed = address
            logger.error("%s: unable to listen on %s:%s (%s)", self.name.upper(), *address, error)
            app_signal.error.emit(f"{self.name}: port {address[1]} unavailable ({bind_error_text(error)}).")
        if isinstance(error, OSError):  # OverflowError (port out of range) never changes
            if self._timer is None:
                self._timer = QTimer()
                self._timer.setSingleShot(True)
                self._timer.timeout.connect(self._start)
            self._timer.start(BIND_RETRY_MS)

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


def bind_error_text(error: Exception) -> str:
    """Server bind error reason (OverflowError has no strerror)"""
    return getattr(error, "strerror", None) or str(error)


def is_allowed_host(host: str | None, port: int) -> bool:
    """Check request Host header, only local host names are allowed (DNS rebinding protection)"""
    if not host:
        return False
    return host.strip().lower() in {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"}


def is_allowed_origin(origin: str | None) -> bool:
    """Allow non-browser clients (no Origin) and pages served from local host only

    Origin "null" (sandboxed frame of any site, local file) is refused.
    """
    if origin is None:
        return True
    return urlsplit(origin.strip().lower()).hostname in {"127.0.0.1", "localhost"}


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


def read_websocket_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Read one client frame (masked), return opcode & payload"""
    first, second = read_exact(sock, 2)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", read_exact(sock, 2))[0]
    elif size == 127:
        size = struct.unpack("!Q", read_exact(sock, 8))[0]
    if size > 65536:
        raise ConnectionError("frame too large")
    mask = read_exact(sock, 4) if second & 0x80 else bytes(4)
    payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(read_exact(sock, size)))
    return first & 0x0F, payload


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

    def update(self, message: bytes) -> None:
        """Update options from client JSON message, ignore invalid message"""
        try:
            data = json.loads(message)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        if "fields" in data:
            fields = data["fields"]
            self.fields = {str(name) for name in fields} if isinstance(fields, list) and fields else None
        if "changes" in data:
            self.changes = bool(data["changes"])
        self.last = {}  # send full data after change

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


class CommandHandler(BoundedRequestHandler):
    """Command request handler"""

    server_version = "TinyPedal"
    timeout = 15  # idle client releases its thread
    stream_timeout = 5  # WebSocket send timeout, server can stop a stream to a stalled client
    commands: dict[str, Callable] = {}
    snapshot: Callable[[], dict] = staticmethod(default_snapshot)

    def check_host(self) -> bool:
        """Verify Host header, send 403 if not allowed"""
        if is_allowed_host(self.headers.get("Host"), getattr(self.server, "server_port", 0)):
            return True
        self.send_json(403, {"error": "host not allowed"})
        return False

    def do_GET(self):
        """List commands"""
        if not self.check_host():
            return
        route = urlsplit(self.path).path.rstrip("/")
        if route == "/commands":
            self.send_json(200, {"commands": sorted(self.commands)})
        elif route == "/stream":
            self.stream()
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        """Run command"""
        if not self.check_host():
            return
        if not self.path.startswith("/command/"):
            self.send_json(404, {"error": "not found"})
            return
        if self.headers.get(REQUIRED_HEADER) is None:
            self.send_json(403, {"error": f"missing {REQUIRED_HEADER} header"})
            return
        name = unquote(self.path[len("/command/"):]).strip("/")
        command = self.commands.get(name)
        if command is None:
            self.send_json(404, {"error": f"unknown command: {name}"})
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
        sock.settimeout(self.stream_timeout)  # client not reading: sendall times out (OSError), never blocks
        # Event of this server: a server started again (reload, port changed) never revives an old stream
        stopping: threading.Event = getattr(self.server, "stopping", None) or threading.Event()
        logger.info("REMOTE CONTROL: stream client connected (%sms)", round(interval * 1000))
        try:
            while not stopping.is_set():
                try:
                    data = self.snapshot()
                except Exception:  # never break stream on bad telemetry
                    logger.debug("REMOTE CONTROL: snapshot error", exc_info=True)
                    data = {"active": False}
                message = options.payload(data)
                if message is not None:
                    sock.sendall(websocket_frame(json.dumps(message).encode("utf-8")))
                readable, _, _ = select.select([sock], [], [], interval)
                if readable:
                    opcode, payload = read_websocket_frame(sock)
                    if opcode == WS_OP_TEXT:
                        options.update(payload)
                    elif opcode == WS_OP_CLOSE:
                        sock.sendall(websocket_frame(payload[:2], WS_OP_CLOSE))
                        break
                    if opcode == WS_OP_PING:
                        sock.sendall(websocket_frame(payload, WS_OP_PONG))
        except (OSError, ValueError):
            pass  # client gone (ConnectionError is an OSError)
        logger.info("REMOTE CONTROL: stream client disconnected")

    def send_json(self, status: int, data: dict):
        """Send json response"""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Silence default stderr access log"""
        logger.debug("REMOTE CONTROL: %s", format % args)


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

    def enable(self):
        """Start server if enabled in setting, stop it if not (server kept if port unchanged)

        Server kept across reload: a server stopped then started again can find its port still held
        by connections it accepted (Windows), and connected stream clients would be dropped.
        """
        setting = cfg.user.config["remote_control"]
        if not setting["enable_remote_control"]:
            self.disable()
            return
        port = int(setting["remote_control_port"])
        if self._server is not None and self._port != port:
            self.disable()
        CommandHandler.commands = available_commands()
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
