"""Security audit 2026-10-29, lot D: local servers (Host/Origin checks, lockout budget, sessions, remote control
token, Server header, deep JSON), size & time limits of game & RaceControl answers, RaceControl redirects"""

import http.client
import http.cookiejar
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import command_server, http_limits
from neopedal.command_server import CommandHandler, CommandServer, StreamOptions, is_allowed_host, own_host_names
from neopedal.setting import Setting, cfg
from neopedal.userfile.json_setting import copy_setting
from neopedal.web_dashboard import (
    GLOBAL_MAX_FAILURES,
    MIN_CODE_LENGTH,
    DashboardHandler,
    WebDashboard,
    same_origin,
)
from tests.test_command_server import PORT as REMOTE_PORT
from tests.test_command_server import ws_connect
from tests.test_web_dashboard import PORT as DASHBOARD_PORT
from tests.test_web_dashboard import NoRedirect, browser, dashboard, request  # noqa: F401

DEEP_JSON = b"[" * 32000 + b"]" * 32000  # RecursionError in json.loads (64 KB: under request & frame limits)


# --- Host header allowlist (DNS rebinding), shared by remote control & web dashboard
def test_host_allowlist_loopback_lan_and_own_names():
    port = 8338
    for host in ("127.0.0.1", "localhost", f"localhost:{port}", "LOCALHOST.", f"127.0.0.1:{port}", "127.0.0.2",
                 f"[::1]:{port}"):
        assert is_allowed_host(host, port), host
    for host in ("evil.test", f"evil.test:{port}", f"127.0.0.1.evil.test:{port}", f"evil.test@127.0.0.1:{port}",
                 "127.0.0.1:8339", "192.168.1.20", f"192.168.1.20:{port}", "desktop-pc", "", None, "a b",
                 "127.0.0.1/x", "localhost:99999"):
        assert not is_allowed_host(host, port), host
    names = frozenset({"desktop-pc", "desktop-pc.local"})
    for host in (f"192.168.1.20:{port}", "10.0.0.5", f"[fe80::1]:{port}", f"desktop-pc:{port}",
                 f"DESKTOP-PC.local:{port}"):
        assert is_allowed_host(host, port, lan=True, names=names), host
    for host in (f"evil.test:{port}", f"desktop-pc.evil.test:{port}", "192.168.1.20:1"):
        assert not is_allowed_host(host, port, lan=True, names=names), host


def test_own_host_names(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "Desktop-PC.home.lan")
    assert own_host_names() == {"desktop-pc.home.lan", "desktop-pc", "desktop-pc.local"}

    def failing():
        raise OSError

    monkeypatch.setattr(socket, "gethostname", failing)
    assert own_host_names() == frozenset()


def test_same_origin():
    assert same_origin("http://192.168.1.20:8338", "192.168.1.20:8338", False)
    assert same_origin("HTTP://LOCALHOST:8338", "localhost:8338", False)
    assert same_origin("https://192.168.1.20:8338", "192.168.1.20:8338", True)
    assert same_origin("http://localhost", "localhost:80", False)  # default port
    assert not same_origin("http://192.168.1.20:8338", "192.168.1.20:8338", True)  # scheme of server
    assert not same_origin("http://127.0.0.1:9999", "127.0.0.1:8338", False)  # other local server
    assert not same_origin("https://evil.test", "127.0.0.1:8338", False)
    assert not same_origin("null", "127.0.0.1:8338", False)
    assert not same_origin("http://127.0.0.1:x", "127.0.0.1:8338", False)
    assert not same_origin("http://127.0.0.1:8338", None, False)


# --- Web dashboard: Host & cross-site checks
def raw(method, path, headers, body=b""):
    client = http.client.HTTPConnection("127.0.0.1", DASHBOARD_PORT, timeout=5)
    try:
        client.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for name, value in headers.items():
            client.putheader(name, value)
        client.putheader("Content-Length", str(len(body)))
        client.endheaders(body)
        response = client.getresponse()
        return response.status, response.read(), response.headers
    finally:
        client.close()


def test_dashboard_refuses_foreign_host(dashboard):  # noqa: F811
    host = f"127.0.0.1:{DASHBOARD_PORT}"
    assert raw("GET", "/?code=TESTCODE", {"Host": f"rebind.evil.test:{DASHBOARD_PORT}"})[0] == 403
    assert raw("GET", "/api/telemetry", {"Host": "rebind.evil.test", "X-Access-Code": "TESTCODE"})[0] == 403
    form = b"code=TESTCODE"
    assert raw("POST", "/login", {"Host": "rebind.evil.test"}, form)[0] == 403
    assert raw("GET", "/api/telemetry", {"Host": host, "X-Access-Code": "TESTCODE"})[0] == 200
    # LAN address of this computer: refused while LAN access is off, allowed with it (phones open the IP address)
    lan_host = f"192.168.1.20:{DASHBOARD_PORT}"
    assert raw("GET", "/api/telemetry", {"Host": lan_host, "X-Access-Code": "TESTCODE"})[0] == 403
    DashboardHandler.lan = True
    try:
        assert raw("GET", "/api/telemetry", {"Host": lan_host, "X-Access-Code": "TESTCODE"})[0] == 200
        assert raw("GET", "/api/telemetry", {"Host": "rebind.evil.test", "X-Access-Code": "TESTCODE"})[0] == 403
    finally:
        DashboardHandler.lan = False


def test_dashboard_cross_site_login_refused_and_never_counted(dashboard):  # noqa: F811
    host = f"127.0.0.1:{DASHBOARD_PORT}"
    for _ in range(12):  # more than the lockout count (10): a web page posting wrong codes
        status, _, _ = raw("POST", "/login", {"Host": host, "Origin": "https://evil.test"}, b"code=WRONG")
        assert status == 403
        status, body, _ = raw("GET", "/?code=WRONG", {"Host": host, "Sec-Fetch-Site": "cross-site"})
        assert status == 401 and b"Access code" in body  # login form shown, code never checked
        assert raw("POST", "/login", {"Host": host, "Sec-Fetch-Site": "same-site"}, b"code=WRONG")[0] == 403
        assert raw("POST", "/login", {"Host": host, "Origin": "null"}, b"code=WRONG")[0] == 403
    assert not DashboardHandler.failures
    # Right code from another site is not accepted either (typed in the login form instead)
    assert raw("GET", "/?code=TESTCODE", {"Host": host, "Sec-Fetch-Site": "cross-site"})[0] == 401
    # Own login form (same origin), link opened from the app (no Origin, Sec-Fetch-Site none)
    status, _, headers = raw("POST", "/login", {"Host": host, "Origin": f"http://{host}",
                                                "Sec-Fetch-Site": "same-origin"}, b"code=TESTCODE")
    assert status == 303 and "Set-Cookie" in headers
    status, _, headers = raw("GET", "/?code=TESTCODE", {"Host": host, "Sec-Fetch-Site": "none"})
    assert status == 303 and "Set-Cookie" in headers


def test_dashboard_login_from_urllib_still_works(dashboard):  # noqa: F811
    """Phone browsers & urllib: Host is the address opened, no Origin on a navigation"""
    opener = browser()
    data = urllib.parse.urlencode({"code": "TESTCODE"}).encode()
    status, body, _ = request("/login", data=data, opener=opener)
    assert status == 200 and b"NeoPedal Dashboard" in body


# --- Web dashboard: lockout budget of every LAN address together
def unit_handler(address: str) -> DashboardHandler:
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.client_address = (address, 50000)
    return handler


@pytest.fixture
def lockout(monkeypatch):
    statuses = []
    monkeypatch.setattr(DashboardHandler, "failures", {})
    monkeypatch.setattr(DashboardHandler, "access_code", "TESTCODE")
    monkeypatch.setattr(DashboardHandler, "global_failures", deque(maxlen=GLOBAL_MAX_FAILURES))
    monkeypatch.setattr(DashboardHandler, "global_until", 0.0)
    monkeypatch.setattr(DashboardHandler, "send_body", lambda self, status, *args: statuses.append(status))
    return statuses


def test_global_failure_budget_blocks_lan_not_this_computer(lockout, caplog):
    with caplog.at_level(logging.WARNING, logger="neopedal.web_dashboard"):
        for index in range(GLOBAL_MAX_FAILURES):  # one wrong code from each of many addresses (IPv6, devices)
            assert not unit_handler(f"10.0.{index // 200}.{index % 200 + 1}").authorized("WRONG")
    assert "logins blocked" in caplog.text
    assert DashboardHandler.global_until > time.monotonic()
    # Every LAN address blocked, right code too (sessions not concerned), this computer never
    lockout.clear()
    assert not unit_handler("10.9.9.9").authorized("TESTCODE") and lockout == [429]
    assert unit_handler("127.0.0.1").authorized("TESTCODE")
    # Wrong codes of this computer never count in the LAN budget
    DashboardHandler.global_until = 0.0
    for _ in range(5):
        unit_handler("127.0.0.1").authorized("WRONG")
    assert not DashboardHandler.global_failures
    assert unit_handler("10.9.9.9").authorized("TESTCODE")


def test_global_budget_forgets_old_failures(lockout):
    from neopedal.web_dashboard import GLOBAL_LOCKOUT_SECONDS, GLOBAL_WINDOW_SECONDS

    now = 1000.0
    for _ in range(GLOBAL_MAX_FAILURES * 2):  # slow guessing: under budget of the window
        now += GLOBAL_WINDOW_SECONDS / GLOBAL_MAX_FAILURES * 1.5
        DashboardHandler.count_global_failure(now)
    assert DashboardHandler.global_until == 0.0
    for _ in range(GLOBAL_MAX_FAILURES):  # fast guessing
        now += 1
        DashboardHandler.count_global_failure(now)
    assert now < DashboardHandler.global_until <= now + GLOBAL_LOCKOUT_SECONDS


# --- Web dashboard: access code length
def test_short_access_code_replaced(ui_env, caplog):
    setting = cfg.user.config["web_dashboard"]
    setting["access_code"] = "ABC123"  # hand-set code of before (6 characters were accepted)
    with caplog.at_level(logging.WARNING, logger="neopedal.web_dashboard"):
        code = WebDashboard.access_code()
    assert len(code) >= MIN_CODE_LENGTH and code != "ABC123" and setting["access_code"] == code
    assert "replaced" in caplog.text
    setting["access_code"] = "MYCODE12"
    assert WebDashboard.access_code() == "MYCODE12"  # 8 characters kept


def test_short_codes_refused_by_settings_page():
    from neopedal.ui.quick.option_kinds import KIND_TEXT, OptionKind, check_value

    kind = OptionKind(KIND_TEXT)
    assert check_value("access_code", kind, "ABC123")
    assert check_value("access_code", kind, "") == "" and check_value("access_code", kind, "ABCDEFGH") == ""
    assert check_value("access_token", kind, "short")
    assert check_value("access_token", kind, "") == "" and check_value("access_token", kind, "x" * 16) == ""


# --- Web dashboard: session bound to client address, cookie lifetime
def test_session_only_valid_from_its_address(dashboard):  # noqa: F811
    opener = browser()
    status, _, _ = request("/?code=TESTCODE", opener=opener)
    assert status == 200 and request("/api/telemetry", opener=opener)[0] == 200
    for session in DashboardHandler.sessions.values():
        session.address = "192.168.1.30"  # cookie copied to (or sent from) another device
    assert request("/api/telemetry", opener=opener)[0] == 401


def test_local_login_cookie_ends_with_browser(dashboard, monkeypatch):  # noqa: F811
    from neopedal import web_dashboard

    status, _, headers = request("/?code=TESTCODE", opener=urllib.request.build_opener(NoRedirect))
    cookie = headers["Set-Cookie"]
    assert status == 303 and "Max-Age" not in cookie and "Expires" not in cookie
    assert next(iter(DashboardHandler.sessions.values())).local
    monkeypatch.setattr(web_dashboard, "is_local_client", lambda address: False)  # phone on the LAN
    status, _, headers = request("/?code=TESTCODE", opener=urllib.request.build_opener(NoRedirect))
    assert f"Max-Age={web_dashboard.SESSION_MAX_SECONDS}" in headers["Set-Cookie"]


def test_local_session_lifetime_shorter():
    from neopedal.web_dashboard import LOCAL_SESSION_MAX_SECONDS, SESSION_MAX_SECONDS, Session

    now = 10_000_000.0
    local, lan = Session(now, "127.0.0.1", True), Session(now, "192.168.1.30", False)
    for session in (local, lan):
        session.last_used = now + LOCAL_SESSION_MAX_SECONDS + 1
    assert local.expired(now + LOCAL_SESSION_MAX_SECONDS + 1)
    assert not lan.expired(now + LOCAL_SESSION_MAX_SECONDS + 1)
    lan.last_used = now + SESSION_MAX_SECONDS + 1
    assert lan.expired(now + SESSION_MAX_SECONDS + 1)


# --- Server header: no Python version (every server)
def test_server_header_hides_python_version(dashboard):  # noqa: F811
    _, _, headers = request("/")
    assert headers["Server"] == "NeoPedal"


# --- Remote control: optional access token, nosniff
@pytest.fixture
def remote(monkeypatch):
    def start(**options):
        cfg.default.set_default()
        config = copy_setting(cfg.default.config)
        config["remote_control"].update(
            {"enable_remote_control": True, "remote_control_port": REMOTE_PORT, **options})
        monkeypatch.setattr(cfg.user, "config", config, raising=False)
        monkeypatch.setattr(Setting, "save", lambda self, *args, **kwargs: None)
        control = CommandServer()
        control.enable()
        controls.append(control)
        return config["remote_control"], control

    controls: list[CommandServer] = []
    received: list = []
    from neopedal import app_signal

    app_signal.hotkey.connect(received.append)
    monkeypatch.setattr(CommandHandler, "snapshot", staticmethod(lambda: {"tick": 1}))
    yield start, received
    for control in controls:
        control.disable()
    CommandHandler.token = ""
    app_signal.hotkey.disconnect(received.append)


def command(headers):
    req = urllib.request.Request(f"http://127.0.0.1:{REMOTE_PORT}/command/overlay_lock", method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.headers, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, error.headers, json.loads(error.read())


def test_remote_control_without_token_unchanged(remote):
    start, _ = remote
    setting, _ = start()
    assert not setting["enable_access_token"] and CommandServer.access_token() == ""
    status, headers, _ = command({"X-NeoPedal": "anything"})
    assert status == 200
    assert headers["X-Content-Type-Options"] == "nosniff" and headers["Server"] == "NeoPedal"
    sock, _, response = ws_connect(port=REMOTE_PORT)
    sock.close()
    assert response.startswith("HTTP/1.1 101")


def test_remote_control_token_required(remote):
    start, received = remote
    setting, control = start(enable_access_token=True, access_token="short")
    token = setting["access_token"]
    assert len(token) >= command_server.MIN_TOKEN_LENGTH and token != "short"  # generated, saved
    assert CommandHandler.token == token
    for value in ("1", "", token + "x", token[:-1]):
        status, headers, data = command({"X-NeoPedal": value})
        assert status == 403 and "token" in data["error"] and headers["X-Content-Type-Options"] == "nosniff"
    assert command({})[0] == 403
    assert command({"X-NeoPedal": token})[0] == 200
    assert command({command_server.LEGACY_HEADER: token})[0] == 200
    QCoreApplication.processEvents()
    assert len(received) == 2
    # Telemetry stream: header, or ?token= of a browser page
    for path, header, upgraded in (
            ("/stream", "", False), ("/stream?token=wrong", "", False), (f"/stream?token={token}", "", True),
            ("/stream", f"X-NeoPedal: {token}\r\n", True), ("/stream", "X-NeoPedal: 1\r\n", False)):
        sock, _, response = ws_connect(path, header, port=REMOTE_PORT)
        sock.close()
        assert response.startswith("HTTP/1.1 101") == upgraded, (path, header)
    # List of command names needs no token
    with urllib.request.urlopen(f"http://127.0.0.1:{REMOTE_PORT}/commands", timeout=5) as response:
        assert response.status == 200
    # Token kept once long enough, turned off: header presence only again
    assert CommandServer.access_token() == token
    setting["enable_access_token"] = False
    control.enable()  # running server takes setting of a reload
    assert CommandHandler.token == "" and command({"X-NeoPedal": "1"})[0] == 200


def test_token_query_redacted_in_log():
    assert "secret" not in command_server.redact_secret_query("GET /stream?token=secret HTTP/1.1")


# --- Deep JSON (RecursionError) from clients
def test_stream_options_ignore_too_deep_json():
    options = StreamOptions(["speed"], changes=True)
    options.update(DEEP_JSON)
    options.update(b'{"fields": [' + b"[" * 30000 + b"]" * 30000 + b"]}")
    options.update(b"\xff\xfe")
    assert options.fields == {"speed"} and options.changes
    options.update(b'{"fields": ["gear", 3, ["x"]], "changes": false}')
    assert options.fields == {"gear"} and not options.changes


def test_director_layout_too_deep_json():
    from neopedal import stream_director

    with pytest.raises(ValueError):
        stream_director.save_layout(DEEP_JSON)


def test_stream_layout_post_too_deep_json(ui_env, monkeypatch, caplog):
    from neopedal import stream_overlay
    from neopedal.process import results_file as rf
    from tests.test_stream_overlay import free_port

    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {})
    cfg.user.config["stream_overlay"].update({"enable_stream_overlay": True, "stream_overlay_port": free_port(),
                                              "access_token": "x" * 24, "enable_lan_access": False})
    control = stream_overlay.StreamOverlay()
    control.enable()
    try:
        base = f"{control.base_urls()[0]}"
        with caplog.at_level(logging.ERROR):
            for path in ("/api/layout", "/api/director/layout"):
                assert post(f"{base}{path}?token={'x' * 24}", DEEP_JSON) == 400
        assert "Traceback" not in caplog.text and not [record for record in caplog.records
                                                       if record.levelno >= logging.ERROR]
    finally:
        control.disable()


def post(url: str, body: bytes) -> int:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


# --- Size & time limits of answers (game Rest API, RaceControl)
def test_read_body_limits():
    data = b"x" * 200_000
    stream = iter([data[i:i + 70_000] for i in range(0, len(data), 70_000)] + [b""])
    calls = []

    def read(amount):
        calls.append(amount)
        return next(stream)[:amount]

    with pytest.raises(http_limits.BodyTooLarge):
        http_limits.read_body(read, 100_000)
    assert sum(calls) <= 100_001 + http_limits.READ_CHUNK  # never read much past the limit
    with pytest.raises(http_limits.BodyTooLarge):
        http_limits.read_body(lambda amount: pytest.fail("read"), 10, length=11)  # declared length: nothing read
    chunks = iter([b"ab", b"cd", b""])
    assert http_limits.read_body(lambda amount: next(chunks), 4) == b"abcd"


class FakeGameServer:
    """Program listening on the game port: answers set by test (raw bytes), sent slowly if asked"""

    def __init__(self, answer: bytes, trickle: float = 0.0):
        self.answer = answer
        self.trickle = trickle
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.stop.is_set():
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            with client:
                try:
                    client.recv(65536)
                    if not self.trickle:
                        client.sendall(self.answer)
                        self.stop.wait(0.2)
                        continue
                    for byte in self.answer:  # a byte now and then: each read within socket timeout
                        if self.stop.wait(self.trickle):
                            return
                        client.sendall(bytes((byte,)))
                except OSError:
                    pass

    def close(self):
        self.stop.set()
        self.sock.close()
        self.thread.join(5)


def test_game_answer_too_large_not_read(monkeypatch):
    from neopedal import game_rest

    monkeypatch.setattr(game_rest, "resolve_hostname", lambda host, port, timeout: host)
    server = FakeGameServer(b"HTTP/1.1 200 OK\r\nContent-Length: 999999999999\r\n\r\n" + b"x" * 1000)
    try:
        start = time.monotonic()
        with game_rest.GameConnection(timeout=2, address=("127.0.0.1", server.port)) as connection:
            assert connection.request("GET", "/x") == (game_rest.STATUS_TOO_LARGE, b"")
            assert connection.connection is None  # rest of body never read as next answer
        assert time.monotonic() - start < 2
    finally:
        server.close()
    # Body without length above the limit (until connection closed)
    server = FakeGameServer(b"HTTP/1.0 200 OK\r\n\r\n" + b"x" * 5000)
    try:
        with game_rest.GameConnection(timeout=2, address=("127.0.0.1", server.port)) as connection:
            assert connection.request("GET", "/x", max_body=1000) == (game_rest.STATUS_TOO_LARGE, b"")
    finally:
        server.close()


def test_game_answer_sent_slowly_ends_at_deadline(monkeypatch):
    from neopedal import game_rest

    monkeypatch.setattr(game_rest, "resolve_hostname", lambda host, port, timeout: host)
    monkeypatch.setattr(game_rest, "REQUEST_SECONDS", 0.6)
    server = FakeGameServer(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" + b"x" * 100, trickle=0.05)
    try:
        start = time.monotonic()
        with game_rest.GameConnection(timeout=0.2, address=("127.0.0.1", server.port)) as connection:
            assert connection.request("GET", "/x") == (0, b"")  # each byte within 0.2 s, answer not within 0.6 s
        assert time.monotonic() - start < 2
    finally:
        server.close()


def test_game_answer_normal(monkeypatch):
    from neopedal import game_rest

    monkeypatch.setattr(game_rest, "resolve_hostname", lambda host, port, timeout: host)
    server = FakeGameServer(b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\n[1, 2]\n")
    try:
        with game_rest.GameConnection(address=("127.0.0.1", server.port)) as connection:
            assert connection.get("/x") == [1, 2]
    finally:
        server.close()


def test_too_large_picture_not_asked_again(ui_env, monkeypatch):
    from neopedal.process import game_images as gi
    from neopedal.userfile import game_images

    asked = []

    def fetch(resource, max_body=None):
        asked.append(max_body)
        return game_images.STATUS_TOO_LARGE, b""

    monkeypatch.setattr(game_images, "fetch_from_game", fetch)
    cache = game_images.GameImages()
    assert not cache.fetch_picture(gi.BRAND, "Toyota")
    assert asked == [game_images.MAX_PICTURE_BYTES] and cache.missing  # read capped, marked missing


def test_game_rest_status_too_large_matches_pictures():
    from neopedal import game_rest
    from neopedal.userfile import game_images

    assert game_images.STATUS_TOO_LARGE == game_rest.STATUS_TOO_LARGE


# --- RaceControl: https://raceos.gg only, redirects too
def test_raceos_url_check():
    from neopedal.process import raceos

    assert raceos.is_raceos_url(raceos.AUTH_URL) and raceos.is_raceos_url("https://raceos.gg:443/api/v1/players")
    for url in ("http://raceos.gg/x", "https://raceos.gg.evil.test/x", "https://evil.test/raceos.gg",
                "https://user@evil.test/", "https://raceos.gg:8443/x", "https://raceos.gg:x/", "ftp://raceos.gg/"):
        assert not raceos.is_raceos_url(url), url
    assert raceos.http_request("GET", "http://raceos.gg/x", None, {}, 1) == (0, b"")  # never sent


def test_raceos_redirect_to_other_host_refused():
    from neopedal.process import raceos

    opener = raceos._opener(5)
    handler = next(item for item in opener.handlers if isinstance(item, urllib.request.HTTPRedirectHandler))
    req = urllib.request.Request(raceos.AUTH_URL, headers={"Game-Authorization": "Bearer secret"})
    headers = http.client.HTTPMessage()
    for url in ("http://raceos.gg/authenticate", "https://evil.test/steal"):
        assert handler.redirect_request(req, None, 302, "Found", headers, url) is None
    followed = handler.redirect_request(req, None, 302, "Found", headers, "https://raceos.gg/v2/authenticate")
    assert followed is not None and followed.full_url == "https://raceos.gg/v2/authenticate"
    assert any(isinstance(item, urllib.request.HTTPSHandler) and type(item) is not urllib.request.HTTPSHandler
               for item in opener.handlers)  # answers read with deadline & size limit


def test_raceos_request_through_https_opener(monkeypatch, tmp_path):
    """Opener of RaceControl requests reads answers (urllib closes the connection socket once headers are read:
    deadline reader keeps it open), refuses a redirect to another host, never reads a too large answer"""
    import http.server
    import ssl

    from neopedal.process import raceos
    from neopedal.userfile import tls_cert

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "https://evil.test/steal")
                self.send_header("Content-Length", "0")
            elif self.path == "/large":
                self.send_response(200)
                self.send_header("Content-Length", str(raceos.MAX_BODY + 1))
            else:
                self.send_response(200)
                self.send_header("Content-Length", "9")
            self.end_headers()
            if self.path == "/ok":
                self.wfile.write(b'{"ok": 1}')

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = tls_cert.server_context(str(tmp_path), []).wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"https://127.0.0.1:{server.server_address[1]}"
    trusted = ssl.create_default_context(cafile=tls_cert.cert_paths(str(tmp_path))[0])
    monkeypatch.setattr(ssl, "_create_default_https_context", lambda *args, **kwargs: trusted)
    monkeypatch.setattr(raceos, "is_raceos_url", lambda url: url.startswith(base))
    headers = {"Game-Authorization": "Bearer secret"}
    try:
        assert raceos.http_request("GET", f"{base}/ok", None, headers, 5) == (200, b'{"ok": 1}')
        assert raceos.http_request("GET", f"{base}/redirect", None, headers, 5) == (302, b"")
        assert raceos.http_request("GET", f"{base}/large", None, headers, 5) == (0, b"")
    finally:
        server.shutdown()
        server.server_close()
