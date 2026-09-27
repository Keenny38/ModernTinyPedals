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

The required header prevents web pages opened in browser from triggering commands,
as browsers cannot send custom header to other site without CORS approval.
Host header is also verified, to block DNS rebinding (malicious domain resolved to 127.0.0.1).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
from urllib.parse import unquote

from . import app_signal
from .setting import cfg

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
REQUIRED_HEADER = "X-TinyPedal"


def available_commands() -> dict[str, Callable]:
    """Available commands (same as hotkey commands): name -> function"""
    from .hotkey.command import COMMANDS_GENERAL, COMMANDS_MODULE, COMMANDS_PRESET, COMMANDS_WIDGET

    return dict(chain(COMMANDS_GENERAL, COMMANDS_PRESET, COMMANDS_MODULE, COMMANDS_WIDGET))


def is_allowed_host(host: str | None, port: int) -> bool:
    """Check request Host header, only local host names are allowed (DNS rebinding protection)"""
    if not host:
        return False
    return host.strip().lower() in {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"}


class CommandHandler(BaseHTTPRequestHandler):
    """Command request handler"""

    server_version = "TinyPedal"
    commands: dict[str, Callable] = {}

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
        if self.path.rstrip("/") == "/commands":
            self.send_json(200, {"commands": sorted(self.commands)})
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
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
        logger.info("DISABLED: remote control")


cmdserver = CommandServer()
