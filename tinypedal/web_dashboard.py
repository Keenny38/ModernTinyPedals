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
Web dashboard: show live telemetry on phone or tablet (browser), disabled by default

    GET  /                            dashboard page (session cookie), or login form
    POST /login                       login form, access code in request body
    GET  /?code=<access code>         login link shown in app, redirects to "/" with session cookie
    GET  /api/telemetry               live data (JSON), requires session cookie or "X-Access-Code" header

Listens on 127.0.0.1 only, unless LAN access is enabled. Access code is always required,
and repeated wrong codes from same address are blocked for a while.
Access code is exchanged for a random session cookie, so it is not kept in page address or scripts.
Session expires when unused for a while, and after a few days anyway.
HTTPS (self-signed certificate, see userfile.tls_cert) can be enabled, otherwise traffic is plain HTTP,
so only enable LAN access on a trusted network.

Page in app language (built at each request), values in units of the user (speed, temperature,
fuel), virtual energy instead of fuel for a car using it (as fuel widgets). Telemetry fields of
before keep their units (km/h, Celsius, liters: also sent by command server stream), values shown
are in "display".
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import socket
import threading
import time
from html import escape
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import app_signal, units
from .command_server import BindRetry, LocalHTTPServer
from .const_api import API_LMU_NAME
from .const_file import ConfigType
from .i18n import current_language, tr
from .setting import cfg
from .userfile.tls_cert import server_context

logger = logging.getLogger(__name__)

MAX_FAILURES = 10
LOCKOUT_SECONDS = 60
FAILURE_WINDOW_SECONDS = 600  # failure count is forgotten after this time
MAX_SESSIONS = 32
SESSION_IDLE_SECONDS = 12 * 3600  # session expires when unused (no dashboard open) for this time
SESSION_MAX_SECONDS = 7 * 24 * 3600  # session expires after this time anyway
MAX_FORM_SIZE = 1024
SESSION_COOKIE = "tp_session"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O, 1/I


def generate_access_code(length: int = 8) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


ADDRESS_CACHE_SECONDS = 30.0  # LAN addresses asked again after this time (pages refresh every second)
_address_lock = threading.Lock()
_address_cache: tuple[float, list[str]] | None = None  # monotonic time, addresses


def local_addresses(max_age: float = ADDRESS_CACHE_SECONDS) -> list[str]:
    """LAN IPv4 addresses of this computer (cached for max_age seconds: host name lookup can be slow)"""
    global _address_cache
    now = time.monotonic()
    with _address_lock:
        cached = _address_cache
        if cached is not None and now - cached[0] < max_age:
            return list(cached[1])
    addresses = lookup_local_addresses()
    with _address_lock:
        _address_cache = (now, addresses)
    return list(addresses)


def clear_address_cache():
    """Next local_addresses() looks up addresses again"""
    global _address_cache
    with _address_lock:
        _address_cache = None


def lookup_local_addresses() -> list[str]:
    """LAN IPv4 addresses of this computer (lookup now)"""
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = str(info[4][0])
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    try:  # address of default route (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(addresses)


def _safe(func, default=0.0):
    try:
        return func()
    except (AttributeError, TypeError, ValueError, IndexError, KeyError, ZeroDivisionError):
        return default  # API not ready, missing data


def _quad(func) -> list[float]:
    """Four wheel values, zeros if unavailable"""
    values = _safe(func, ())
    try:
        return [round(float(value), 1) for value in values[:4]] or [0.0] * 4
    except (TypeError, ValueError):
        return [0.0] * 4


def unit_names() -> dict[str, str]:
    """Units setting of user (defaults if not loaded yet)"""
    try:
        setting = cfg.units
    except (AttributeError, KeyError, TypeError):
        setting = {}
    return {
        "speed": str(setting.get("speed_unit", "KPH")),
        "temperature": str(setting.get("temperature_unit", "Celsius")),
        "fuel": str(setting.get("fuel_unit", "Liter")),
    }


def display_values(speed: float, tyre_temp: list[float], brake_temp: list[float], track_temp: float) -> dict:
    """Values shown on dashboard in units of the user (speed in m/s, temperatures in Celsius),
    virtual energy (%) instead of fuel for a car using it, as fuel widgets"""
    from .module_info import minfo

    names = unit_names()
    to_speed = units.set_unit_speed(names["speed"])
    to_temperature = units.set_unit_temperature(names["temperature"])
    energy = bool(minfo.energy.available)
    if energy:
        to_fuel, fuel_unit, source = units.pass_value, "%", minfo.energy
    else:
        to_fuel = units.set_unit_fuel(names["fuel"])
        fuel_unit, source = units.set_symbol_fuel(names["fuel"]), minfo.fuel
    return {
        "speed": round(to_speed(speed), 1),
        "speed_unit": units.set_symbol_speed(names["speed"]),
        "temperature_unit": units.set_symbol_temperature(names["temperature"]),
        "tyre_temp": [round(to_temperature(value), 1) for value in tyre_temp],
        "brake_temp": [round(to_temperature(value), 1) for value in brake_temp],
        "track_temp": round(to_temperature(track_temp), 1),
        "energy": energy,
        "fuel": round(to_fuel(source.amountCurrent), 2),
        "fuel_unit": fuel_unit,
        "fuel_laps": round(source.estimatedLaps, 1),
        "fuel_per_lap": round(to_fuel(source.estimatedConsumption), 3),
    }


def delta_available() -> bool:
    """Delta best can be shown: best lap exists, current lap comparable (not an out lap)"""
    from .widget._common import delta_shown

    return delta_shown("Best")


def official_delta(read) -> float | None:
    """Delta to best lap computed by game (LMU), None when not available"""
    from .api_control import api

    if not _safe(lambda: api.name == API_LMU_NAME, False):
        return None
    return round(_safe(read.timing.delta_best), 3)


def telemetry_snapshot() -> dict:
    """Current telemetry for dashboard"""
    from .api_control import api
    from .module_info import minfo

    read = api.read
    if read is None:
        return {"active": False}
    fuel = minfo.fuel
    delta = minfo.delta
    speed = _safe(read.vehicle.speed)
    tyre_temp = _quad(read.tyre.surface_temperature_avg)
    brake_temp = _quad(read.brake.temperature)
    track_temp = round(_safe(read.session.track_temperature), 1)
    return {
        "active": bool(_safe(read.state.active, False)),
        "speed": round(speed * 3.6, 1),
        "gear": _safe(read.engine.gear, 0),
        "rpm": round(_safe(read.engine.rpm)),
        "rpm_max": round(_safe(read.engine.rpm_max)),
        "throttle": round(_safe(read.inputs.throttle), 3),
        "brake": round(_safe(read.inputs.brake), 3),
        "position": _safe(read.vehicle.place, 0),
        "vehicles": _safe(read.vehicle.total_vehicles, 0),
        "lap": _safe(read.lap.number, 0),
        "delta_best": round(delta.deltaBest, 3),
        "delta_available": delta_available(),
        "lap_current": round(delta.lapTimeCurrent, 3),
        "lap_last": round(delta.lapTimeLast, 3),
        "lap_best": round(delta.lapTimeBest, 3),
        "fuel": round(fuel.amountCurrent, 2),
        "fuel_laps": round(fuel.estimatedLaps, 1),
        "fuel_per_lap": round(fuel.estimatedConsumption, 3),
        "tyre_temp": tyre_temp,
        "brake_temp": brake_temp,
        "track_temp": track_temp,
        "time_remaining": round(_safe(read.session.remaining)),
        "track": _safe(read.session.track_name, ""),
        "delta_official": official_delta(read),
        "lap_invalid": bool(_safe(read.lap.invalidated, False)),
        "display": display_values(speed, tyre_temp, brake_temp, track_temp),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    """Dashboard request handler

    HTTP/1.1 keep-alive: page polls telemetry every 150 ms on one connection, instead of a new connection
    (and TLS handshake) per request, each left in TIME_WAIT. Every response sends Content-Length.
    """

    server_version = "TinyPedal"
    protocol_version = "HTTP/1.1"
    timeout = 15  # idle client never holds a handler thread (socket timeout, no streaming endpoint)
    access_code = ""
    failures: dict[str, list[float]] = {}  # address: [count, blocked until, last failure]
    sessions: dict[str, list[float]] = {}  # session token: [created time, last used time]
    lock = threading.Lock()
    secure = False  # HTTPS: TLS handshake in handler thread, secure cookie

    def setup(self):
        if self.secure:  # handshake here, so a slow client never blocks accepting others
            self.request.settimeout(10)
            self.request.do_handshake()
        super().setup()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/telemetry":
            if self.authorized(self.headers.get("X-Access-Code", "")):
                try:
                    body = json.dumps(telemetry_snapshot()).encode("utf-8")
                except Exception:  # never drop connection on data error
                    logger.debug("WEB DASHBOARD: snapshot error", exc_info=True)
                    body = b'{"active": false}'
                self.send_body(200, body, "application/json")
            return
        if url.path in ("/", "/index.html"):
            code = parse_qs(url.query).get("code", [""])[0]
            if code:  # link with code (shown in app), exchange for session cookie & remove code from address bar
                if self.authorized(code, html=True):
                    self.send_redirect_with_session()
                return
            if self.has_session():
                self.send_body(200, dashboard_html().encode("utf-8"), "text/html; charset=utf-8")
            else:
                self.send_body(401, login_html().encode("utf-8"), "text/html; charset=utf-8")
            return
        self.send_body(404, b"not found", "text/plain")

    def do_POST(self):
        """Login form, access code sent in request body (not kept in browser history)"""
        if urlparse(self.path).path != "/login":
            self.send_body(404, b"not found", "text/plain")
            return
        try:  # never read more than form size (negative length reads until connection closed)
            declared = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True  # body length unknown: never read as next request
            self.send_body(400, b"invalid request", "text/plain")
            return
        length = max(min(declared, MAX_FORM_SIZE), 0)
        if length != declared:
            self.close_connection = True  # rest of body left unread: never read as next request
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        if self.authorized(form.get("code", [""])[0].strip(), html=True):
            self.send_redirect_with_session()

    def has_session(self) -> bool:
        """Check session cookie"""
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return False
        now = time.monotonic()
        with self.lock:
            self.purge_sessions(now)
            for token, times in self.sessions.items():
                if hmac.compare_digest(morsel.value, token):
                    times[1] = now  # last used
                    return True
        return False

    def new_session(self) -> str:
        """Create session token, least recently used session is dropped if limit reached"""
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self.lock:
            self.purge_sessions(now)
            if len(self.sessions) >= MAX_SESSIONS:
                del self.sessions[min(self.sessions, key=lambda name: self.sessions[name][1])]
            self.sessions[token] = [now, now]
        return token

    @classmethod
    def purge_sessions(cls, now: float):
        """Forget expired sessions: unused for a while, or too old"""
        expired = [
            token for token, (created, last_used) in cls.sessions.items()
            if now - last_used > SESSION_IDLE_SECONDS or now - created > SESSION_MAX_SECONDS
        ]
        for token in expired:
            del cls.sessions[token]

    def authorized(self, code: str, html: bool = False) -> bool:
        """Check session cookie or access code, block address after repeated failures"""
        if not code:  # no guess made, not counted as failure
            if self.has_session():
                return True
            self.send_unauthorized(html)
            return False
        address = self.client_address[0]
        now = time.monotonic()
        with self.lock:
            self.purge_failures(now)
            count, until, _ = self.failures.get(address, [0, 0.0, 0.0])
            if until > now:
                self.send_body(429, b"too many attempts, try again later", "text/plain")
                return False
            if code and hmac.compare_digest(code.encode("utf-8"), self.access_code.encode("utf-8")):
                self.failures.pop(address, None)
                return True
            count += 1
            self.failures[address] = [count, now + LOCKOUT_SECONDS if count >= MAX_FAILURES else 0.0, now]
        self.send_unauthorized(html)
        return False

    def send_unauthorized(self, html: bool):
        if html:
            self.send_body(401, login_html().encode("utf-8"), "text/html; charset=utf-8")
        else:
            self.send_body(401, b'{"error": "invalid access code"}', "application/json")

    @classmethod
    def purge_failures(cls, now: float):
        """Forget addresses without active lockout & no recent failure (keeps dict bounded)"""
        expired = [
            address for address, (_, until, last) in cls.failures.items()
            if until <= now and now - last > FAILURE_WINDOW_SECONDS
        ]
        for address in expired:
            del cls.failures[address]

    def send_redirect_with_session(self):
        token = self.new_session()
        self.send_response(303)
        self.send_header("Location", "/")
        secure = "; Secure" if self.secure else ""
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; Max-Age={SESSION_MAX_SECONDS}; HttpOnly; SameSite=Strict{secure}",
        )
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_connection_header()
        self.end_headers()

    def send_connection_header(self):
        """Client told connection is not kept (body left unread, HTTP/1.0 client)"""
        if self.close_connection:
            self.send_header("Connection", "close")

    def send_body(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_connection_header()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.debug("WEB DASHBOARD: %s", format % args)


class DashboardServer(LocalHTTPServer):
    """Dashboard HTTP server, client errors (failed TLS handshake, dropped connection) only logged

    Open (keep-alive) connections ended by stop().
    """

    def handle_error(self, request, client_address):
        logger.debug("WEB DASHBOARD: request from %s failed", client_address[0], exc_info=True)


class WebDashboard:
    """Web dashboard server control"""

    __slots__ = ("_server", "_thread", "_key", "_retry")

    def __init__(self):
        self._server: DashboardServer | None = None
        self._thread: threading.Thread | None = None
        self._key: tuple | None = None  # listening setup of running server: address, HTTPS, LAN addresses
        self._retry = BindRetry("Web dashboard", self.enable)

    @property
    def running(self) -> bool:
        return self._server is not None

    @staticmethod
    def access_code() -> str:
        """Access code, generated and saved on first use"""
        setting = cfg.user.config["web_dashboard"]
        code = str(setting["access_code"]).strip()
        if len(code) < 6:
            code = generate_access_code()
            setting["access_code"] = code
            cfg.save(config_type=ConfigType.CONFIG)
        return code

    @staticmethod
    def host() -> str:
        return "0.0.0.0" if cfg.user.config["web_dashboard"]["enable_lan_access"] else "127.0.0.1"

    @staticmethod
    def port() -> int:
        return int(cfg.user.config["web_dashboard"]["web_dashboard_port"])

    def urls(self) -> list[str]:
        """Dashboard addresses with access code"""
        code = self.access_code()
        hosts = local_addresses() if cfg.user.config["web_dashboard"]["enable_lan_access"] else []
        scheme = "https" if self.use_https() else "http"
        return [f"{scheme}://{host}:{self.port()}/?code={code}" for host in ("127.0.0.1", *hosts)]

    @staticmethod
    def use_https() -> bool:
        return bool(cfg.user.config["web_dashboard"]["enable_https"])

    def enable(self):
        """Start server if enabled in setting, stop it if not (server kept if listening setup unchanged)

        Server kept across reload: a server stopped then started again can find its port still held
        by connections it accepted (Windows). Sessions kept unless access code changed.
        """
        if not cfg.user.config["web_dashboard"]["enable_web_dashboard"]:
            self.disable()
            return
        code = self.access_code()
        if code != DashboardHandler.access_code:  # logins made with old code end
            with DashboardHandler.lock:
                DashboardHandler.access_code = code
                DashboardHandler.failures = {}
                DashboardHandler.sessions = {}
        host, port, secure = self.host(), self.port(), self.use_https()
        # HTTPS certificate covers LAN addresses: made again (server started again) if they changed
        addresses = local_addresses(max_age=0) if secure and host != "127.0.0.1" else []
        key = (host, port, secure, tuple(addresses))
        if self._server is not None and self._key != key:
            self.disable()
        if self._server is not None:
            return
        try:
            server = DashboardServer((host, port), DashboardHandler)
        except (OSError, OverflowError) as error:  # OverflowError: port out of range
            self._retry.failed((host, port), error)
            return
        self._retry.stop()
        if secure:
            try:
                context = server_context(cfg.path.config, addresses)
            except (OSError, ValueError, ImportError) as error:
                logger.error("WEB DASHBOARD: unable to set up HTTPS (%s)", error)
                app_signal.error.emit(f"Web dashboard: unable to set up HTTPS ({error}).")
                server.server_close()
                return
            server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
        DashboardHandler.secure = secure
        self._server = server
        self._key = key
        self._thread = threading.Thread(target=server.serve_forever, daemon=True, name="Web dashboard")
        self._thread.start()
        scheme = "https" if secure else "http"
        logger.info("ENABLED: web dashboard on %s://%s:%s", scheme, host, port)
        if host != "127.0.0.1" and not secure:
            logger.warning("WEB DASHBOARD: LAN access enabled, traffic is not encrypted (plain HTTP)")

    def disable(self):
        """Stop server, end open connections"""
        self._retry.stop()
        if self._server is None:
            return
        self._server.stop()
        self._server = None
        self._thread = None
        self._key = None
        logger.info("DISABLED: web dashboard")


webdashboard = WebDashboard()

# Page text (English, translated in app language when page is served): "@@key@@" in page
LOGIN_LABELS = {
    "access_code": "Access code",
}
PAGE_LABELS = {
    "title": "Modern Tiny Pedals Dashboard",
    "connecting": "Connecting…",
    "gear_speed": "Gear · Speed",
    "delta": "Delta best",
    "official": "Official delta",
    "position": "Position",
    "lap_current": "Current lap",
    "invalid": "Invalid lap",
    "lap_last": "Last lap",
    "lap_best": "Best Lap",
    "fuel": "Fuel · laps left",
    "pedals": "Throttle · Brake",
    "tyre": "Tyre",
    "brake": "Brake",
    "remain": "Time left",
}
# Text set by page script ("@@texts@@" in page, JSON)
SCRIPT_TEXTS = {
    "expired": "Session expired",
    "waiting": "Waiting for session…",
    "on_track": "On Track",
    "lost": "Connection lost, retrying…",
    "laps": "laps",
    "fuel": "Fuel · laps left",
    "energy": "Energy · laps left",
}


def page_language() -> str:
    """Language of page (html lang attribute): app language"""
    return current_language().replace("_", "-")


def fill_page(template: str, labels: dict[str, str], texts: dict[str, str] | None = None) -> str:
    """Page in app language: labels escaped for html, script text as JSON (never closing script)"""
    page = template.replace("@@lang@@", escape(page_language()))
    for key, text in labels.items():
        page = page.replace(f"@@{key}@@", escape(tr(text)))
    if texts is not None:
        data = json.dumps({key: tr(text) for key, text in texts.items()}, ensure_ascii=False)
        page = page.replace("@@texts@@", data.replace("<", "\\u003c"))
    return page


def login_html() -> str:
    return fill_page(LOGIN_HTML, LOGIN_LABELS)


def dashboard_html() -> str:
    return fill_page(DASHBOARD_HTML, PAGE_LABELS, SCRIPT_TEXTS)


LOGIN_HTML = """<!doctype html><html lang="@@lang@@"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Modern Tiny Pedals</title>
<style>body{background:#0e1116;color:#e9ecf1;font-family:system-ui,sans-serif;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}form{display:flex;gap:8px}
input,button{font-size:20px;padding:10px;border-radius:8px;border:1px solid #373e4c;background:#1b1f27;color:#e9ecf1}
</style></head><body><form method="post" action="/login"><input name="code" placeholder="@@access_code@@" autofocus
autocomplete="off"><button>OK</button></form></body></html>"""

DASHBOARD_HTML = """<!doctype html><html lang="@@lang@@"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0e1116"><title>@@title@@</title>
<style>
:root{--bg:#0e1116;--panel:#1b1f27;--line:#2a303c;--text:#e9ecf1;--muted:#9aa3b2;
--green:#34c759;--red:#ff4d4f;--blue:#38bdf8;--yellow:#ffd43b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums}
main{display:grid;gap:10px;padding:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.label{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.05em}
.value{font-size:34px;font-weight:700;line-height:1.2}.big{grid-column:span 2}
.huge{font-size:84px;text-align:center}.bar{height:12px;border-radius:6px;background:var(--line);overflow:hidden;margin-top:6px}
.bar>div{height:100%;width:0}.grid4{display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:22px}
#status{padding:6px 12px;color:var(--muted);font-size:13px}.pos{color:var(--green)}.neg{color:var(--red)}
.unit{font-size:18px;color:var(--muted)}.badge{display:none;margin-left:6px;padding:1px 6px;border-radius:6px;
background:var(--red);color:var(--bg);font-size:12px;letter-spacing:0}
</style></head><body>
<div id="status">@@connecting@@</div>
<main>
<div class="card big"><div class="label">@@gear_speed@@</div>
<div class="value huge"><span id="gear">N</span> <span id="speed" style="font-size:48px">0</span>
<span class="unit" id="speedunit"></span></div>
<div class="bar"><div id="rpmbar" style="background:var(--blue)"></div></div></div>
<div class="card"><div class="label">@@delta@@</div><div class="value" id="delta">+0.000</div></div>
<div class="card" id="officialcard" style="display:none"><div class="label">@@official@@</div>
<div class="value" id="official">+0.000</div></div>
<div class="card"><div class="label">@@position@@</div><div class="value" id="position">-</div></div>
<div class="card"><div class="label">@@lap_current@@<span class="badge" id="invalid">@@invalid@@</span></div>
<div class="value" id="lapcur">-:--.---</div></div>
<div class="card"><div class="label">@@lap_last@@</div><div class="value" id="laplast">-:--.---</div></div>
<div class="card"><div class="label">@@lap_best@@</div><div class="value" id="lapbest">-:--.---</div></div>
<div class="card"><div class="label" id="fueltitle">@@fuel@@</div>
<div class="value"><span id="fuel">0</span> <span class="unit" id="fuelunit"></span></div>
<div class="unit" id="fuellaps">0.0</div></div>
<div class="card"><div class="label">@@pedals@@</div>
<div class="bar"><div id="thr" style="background:var(--green)"></div></div>
<div class="bar"><div id="brk" style="background:var(--red)"></div></div></div>
<div class="card"><div class="label">@@tyre@@ <span id="tyreunit"></span></div><div class="grid4" id="tyres"></div></div>
<div class="card"><div class="label">@@brake@@ <span id="brakeunit"></span></div><div class="grid4" id="brakes"></div></div>
<div class="card"><div class="label">@@remain@@</div><div class="value" id="remain">--:--</div></div>
</main>
<script>
const T=@@texts@@;
const $=id=>document.getElementById(id);
const lap=t=>{if(!(t>0))return"-:--.---";const m=Math.floor(t/60);return m+":"+(t-m*60).toFixed(3).padStart(6,"0")};
const hms=t=>{if(!(t>0))return"--:--";t=Math.floor(t);const h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=t%60;
return(h?h+":"+String(m).padStart(2,"0"):m)+":"+String(s).padStart(2,"0")};
const quad=v=>v.map(x=>"<div>"+Math.round(x)+"</div>").join("");
const signed=x=>(x>=0?"+":"")+x.toFixed(3);
async function tick(){
try{const r=await fetch("/api/telemetry",{credentials:"same-origin",cache:"no-store"});
if(r.status===401){$("status").textContent=T.expired;return setTimeout(()=>location.replace("/"),1500)}
if(!r.ok)throw new Error(r.status);const d=await r.json();const v=d.display||{};
$("status").textContent=d.active?(d.track||T.on_track):T.waiting;
$("gear").textContent=d.gear>0?d.gear:(d.gear<0?"R":"N");$("speed").textContent=Math.round(v.speed||0);
$("speedunit").textContent=v.speed_unit||"";
$("rpmbar").style.width=(d.rpm_max>0?Math.min(d.rpm/d.rpm_max,1)*100:0)+"%";
const dl=d.delta_best||0;const shown=d.delta_available!==false;$("delta").textContent=shown?signed(dl):"\u2013";$("delta").className="value "+(shown?(dl>0?"neg":"pos"):"");
const off=d.delta_official;const official=typeof off==="number";
$("officialcard").style.display=official?"":"none";
if(official){$("official").textContent=signed(off);$("official").className="value "+(off>0?"neg":"pos")}
$("position").textContent=d.position?d.position+"/"+d.vehicles:"-";
$("invalid").style.display=d.lap_invalid?"inline-block":"none";
$("lapcur").textContent=lap(d.lap_current);$("laplast").textContent=lap(d.lap_last);$("lapbest").textContent=lap(d.lap_best);
$("fueltitle").textContent=v.energy?T.energy:T.fuel;
$("fuel").textContent=(v.fuel||0).toFixed(1);$("fuelunit").textContent=v.fuel_unit||"";
$("fuellaps").textContent=(v.fuel_laps||0).toFixed(1)+" "+T.laps;
$("thr").style.width=(d.throttle*100)+"%";$("brk").style.width=(d.brake*100)+"%";
$("tyreunit").textContent=$("brakeunit").textContent=v.temperature_unit||"";
$("tyres").innerHTML=quad(v.tyre_temp||[]);$("brakes").innerHTML=quad(v.brake_temp||[]);
$("remain").textContent=hms(d.time_remaining);setTimeout(tick,150)}
catch(e){$("status").textContent=T.lost;setTimeout(tick,2000)}}
tick();
</script></body></html>"""
