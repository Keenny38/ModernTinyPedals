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
    GET  /stream           -> WebSocket, pushes live telemetry JSON (query: interval=ms)

The required header prevents web pages opened in browser from triggering commands,
as browsers cannot send custom header to other site without CORS approval.
Host header is also verified, to block DNS rebinding (malicious domain resolved to 127.0.0.1).
WebSocket is not covered by CORS, so /stream also rejects browser pages from other origins.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import select
import socket
import struct
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
from urllib.parse import parse_qs, unquote, urlsplit

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


def available_commands() -> dict[str, Callable]:
    """Available commands (same as hotkey commands): name -> function"""
    from .hotkey.command import COMMANDS_GENERAL, COMMANDS_MODULE, COMMANDS_PRESET, COMMANDS_WIDGET

    return dict(chain(COMMANDS_GENERAL, COMMANDS_PRESET, COMMANDS_MODULE, COMMANDS_WIDGET))


def is_allowed_host(host: str | None, port: int) -> bool:
    """Check request Host header, only local host names are allowed (DNS rebinding protection)"""
    if not host:
        return False
    return host.strip().lower() in {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"}


def is_allowed_origin(origin: str | None) -> bool:
    """Allow non-browser clients (no Origin) and local pages only"""
    if origin is None:
        return True
    origin = origin.strip().lower()
    return origin == "null" or urlsplit(origin).hostname in {"127.0.0.1", "localhost"}


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


def default_snapshot() -> dict:
    """Live telemetry, same data as web dashboard"""
    from .web_dashboard import telemetry_snapshot

    return telemetry_snapshot()


class CommandHandler(BaseHTTPRequestHandler):
    """Command request handler"""

    server_version = "TinyPedal"
    commands: dict[str, Callable] = {}
    snapshot: Callable[[], dict] = staticmethod(default_snapshot)
    stopping = threading.Event()

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
        sock = self.connection
        logger.info("REMOTE CONTROL: stream client connected (%sms)", round(interval * 1000))
        try:
            while not self.stopping.is_set():
                try:
                    data = self.snapshot()
                except Exception:  # never break stream on bad telemetry
                    logger.debug("REMOTE CONTROL: snapshot error", exc_info=True)
                    data = {"active": False}
                sock.sendall(websocket_frame(json.dumps(data).encode("utf-8")))
                readable, _, _ = select.select([sock], [], [], interval)
                if readable:
                    opcode, payload = read_websocket_frame(sock)
                    if opcode == WS_OP_CLOSE:
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

    __slots__ = ("_server", "_thread")

    def __init__(self):
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def enable(self):
        """Start server if enabled in setting"""
        setting = cfg.user.config["remote_control"]
        if not setting["enable_remote_control"] or self.running:
            return
        port = int(setting["remote_control_port"])
        CommandHandler.commands = available_commands()
        CommandHandler.stopping.clear()
        try:
            self._server = ThreadingHTTPServer((HOST, port), CommandHandler)
        except OSError as error:
            logger.error("REMOTE CONTROL: unable to listen on %s:%s (%s)", HOST, port, error)
            app_signal.error.emit(f"Remote control: port {port} unavailable ({error.strerror}).")
            return
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="Remote control")
        self._thread.start()
        logger.info("ENABLED: remote control on http://%s:%s", HOST, port)

    def disable(self):
        """Stop server"""
        if self._server is None:
            return
        CommandHandler.stopping.set()  # end open streams
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
        logger.info("DISABLED: remote control")


cmdserver = CommandServer()
