"""Web dashboard tests (localhost only)"""

import http.client
import http.cookiejar
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from tinypedal.setting import cfg
from tinypedal.userfile import tls_cert
from tinypedal.web_dashboard import (
    FAILURE_WINDOW_SECONDS,
    MAX_SESSIONS,
    DashboardHandler,
    WebDashboard,
    generate_access_code,
)

PORT = 18338


@pytest.fixture
def dashboard(ui_env):
    config = cfg.user.config["web_dashboard"]
    config.update(enable_web_dashboard=True, web_dashboard_port=PORT, access_code="TESTCODE")
    server = WebDashboard()
    server.enable()
    yield server
    server.disable()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(path, headers=None, data=None, opener=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", headers=headers or {}, data=data)
    try:
        with (opener or urllib.request.build_opener()).open(req, timeout=5) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers


def get(path, headers=None, opener=None):
    status, body, _ = request(path, headers, opener=opener)
    return status, body


def browser():
    """Opener that keeps cookies, like a browser"""
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def test_page_requires_code(dashboard):
    status, body = get("/")
    assert status == 401 and b"Access code" in body
    status, body = get("/?code=TESTCODE", opener=browser())
    assert status == 200 and b"Modern Tiny Pedals Dashboard" in body


def test_code_link_redirects_to_clean_url(dashboard):
    status, _, headers = request("/?code=TESTCODE", opener=urllib.request.build_opener(NoRedirect))
    assert status == 303 and headers["Location"] == "/"
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "TESTCODE" not in cookie


def test_login_form_post(dashboard):
    opener = browser()
    status, body = get("/", opener=opener)
    assert status == 401 and b'method="post"' in body and b"code=" not in body.split(b"<form")[0]
    data = urllib.parse.urlencode({"code": "TESTCODE"}).encode()
    status, body, _ = request("/login", data=data, opener=opener)
    assert status == 200 and b"Modern Tiny Pedals Dashboard" in body
    assert b"X-Access-Code" not in body  # page script uses session cookie, no code
    # Session cookie grants API access
    assert get("/api/telemetry", opener=opener)[0] == 200


def test_login_form_wrong_code(dashboard):
    data = urllib.parse.urlencode({"code": "WRONG"}).encode()
    status, body, _ = request("/login", data=data, opener=browser())
    assert status == 401 and b"Access code" in body
    DashboardHandler.failures.clear()


def test_forged_session_rejected(dashboard):
    assert get("/api/telemetry", {"Cookie": "tp_session=forged"})[0] == 401
    assert get("/", {"Cookie": "tp_session=forged"})[0] == 401


def test_telemetry_api(dashboard):
    assert get("/api/telemetry")[0] == 401
    status, body = get("/api/telemetry", {"X-Access-Code": "TESTCODE"})
    assert status == 200
    data = json.loads(body)
    assert {"speed", "gear", "delta_best", "fuel_laps", "tyre_temp"} <= set(data)


def test_lockout_after_failures(dashboard):
    for _ in range(10):
        get("/api/telemetry", {"X-Access-Code": "WRONG"})
    status, _ = get("/api/telemetry", {"X-Access-Code": "TESTCODE"})
    assert status == 429  # blocked even with right code
    DashboardHandler.failures.clear()


def test_missing_code_not_counted_as_failure(dashboard):
    for _ in range(15):  # dashboard polling after server restart must not lock user out
        get("/api/telemetry")
    assert get("/api/telemetry", {"X-Access-Code": "TESTCODE"})[0] == 200


def test_failures_purged():
    now = time.monotonic()
    DashboardHandler.failures = {
        "old": [3, 0.0, now - FAILURE_WINDOW_SECONDS - 1],
        "recent": [3, 0.0, now],
        "locked": [10, now + 30, now - FAILURE_WINDOW_SECONDS - 1],
    }
    DashboardHandler.purge_failures(now)
    assert set(DashboardHandler.failures) == {"recent", "locked"}
    DashboardHandler.failures = {}


def test_session_limit(dashboard):
    opener_first = browser()
    get("/?code=TESTCODE", opener=opener_first)
    for _ in range(MAX_SESSIONS):
        get("/?code=TESTCODE", opener=browser())
    assert len(DashboardHandler.sessions) == MAX_SESSIONS
    assert get("/api/telemetry", opener=opener_first)[0] == 401  # oldest session dropped


@pytest.mark.parametrize("length", ["-1", "abc"])
def test_login_body_size_bounded(dashboard, length):
    """Negative or invalid length never makes server read until connection closed (before login)"""
    client = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    try:
        client.putrequest("POST", "/login")
        client.putheader("Content-Length", length)
        client.endheaders()
        client.send(b"code=WRONG")
        status = client.getresponse().status  # answered without waiting for more data
    finally:
        client.close()
    assert status in (400, 401)
    DashboardHandler.failures.clear()


def test_session_expires_when_unused(dashboard):
    from tinypedal.web_dashboard import SESSION_IDLE_SECONDS, SESSION_MAX_SECONDS

    opener = browser()
    get("/?code=TESTCODE", opener=opener)
    assert get("/api/telemetry", opener=opener)[0] == 200
    now = time.monotonic()
    for times in DashboardHandler.sessions.values():
        times[:] = [now - 3600, now - 60]  # used a minute ago: kept, last use updated
    assert get("/api/telemetry", opener=opener)[0] == 200
    assert next(iter(DashboardHandler.sessions.values()))[1] > now - 1
    for times in DashboardHandler.sessions.values():
        times[:] = [now - 3600, now - SESSION_IDLE_SECONDS - 1]  # unused for too long
    assert get("/api/telemetry", opener=opener)[0] == 401
    assert not DashboardHandler.sessions
    get("/?code=TESTCODE", opener=opener)
    for times in DashboardHandler.sessions.values():
        times[:] = [now - SESSION_MAX_SECONDS - 1, now]  # in use, but too old
    assert get("/api/telemetry", opener=opener)[0] == 401


def test_access_code_generated(ui_env):
    cfg.user.config["web_dashboard"]["access_code"] = ""
    code = WebDashboard.access_code()
    assert len(code) == 8 and cfg.user.config["web_dashboard"]["access_code"] == code
    assert generate_access_code() != generate_access_code()


def test_localhost_only_by_default(ui_env):
    assert WebDashboard.host() == "127.0.0.1"
    cfg.user.config["web_dashboard"]["enable_lan_access"] = True
    assert WebDashboard.host() == "0.0.0.0"


# --- HTTPS (self-signed certificate)

@pytest.fixture
def https_dashboard(ui_env):
    config = cfg.user.config["web_dashboard"]
    config.update(enable_web_dashboard=True, web_dashboard_port=PORT, access_code="TESTCODE", enable_https=True)
    server = WebDashboard()
    server.enable()
    yield server
    server.disable()
    DashboardHandler.secure = False


def https_client() -> http.client.HTTPSConnection:
    context = ssl.create_default_context(cafile=tls_cert.cert_paths(cfg.path.config)[0])
    return http.client.HTTPSConnection("127.0.0.1", PORT, context=context, timeout=5)


def test_https_serves_with_trusted_certificate(https_dashboard):
    assert https_dashboard.urls()[0].startswith("https://127.0.0.1")
    client = https_client()  # verifies certificate & 127.0.0.1 address against it
    client.request("GET", "/api/telemetry", headers={"X-Access-Code": "TESTCODE"})
    response = client.getresponse()
    assert response.status == 200
    assert "active" in json.loads(response.read())
    client.request("GET", "/?code=TESTCODE")
    response = client.getresponse()
    response.read()
    assert "Secure" in response.headers["Set-Cookie"]
    client.close()


def test_https_rejects_plain_http(https_dashboard):
    with pytest.raises((urllib.error.URLError, http.client.HTTPException, ConnectionError, OSError)):
        get("/api/telemetry", {"X-Access-Code": "TESTCODE"})


def test_certificate_reused_and_renewed_for_new_address(tmp_path):
    folder = str(tmp_path)
    tls_cert.server_context(folder, [])
    first = tls_cert.fingerprint(folder)
    assert len(first.split(":")) == 32
    tls_cert.server_context(folder, [])
    assert tls_cert.fingerprint(folder) == first  # reused, browser keeps trusting it
    tls_cert.server_context(folder, ["192.168.1.50"])
    assert tls_cert.fingerprint(folder) != first  # new LAN address not covered
    assert tls_cert.covers(tls_cert.cert_paths(folder)[0], ["127.0.0.1", "192.168.1.50"])


def test_https_error_reported_when_certificate_fails(ui_env, monkeypatch):
    from tinypedal import web_dashboard

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(web_dashboard, "server_context", broken)
    cfg.user.config["web_dashboard"].update(enable_web_dashboard=True, web_dashboard_port=PORT, enable_https=True)
    server = WebDashboard()
    server.enable()
    assert not server.running
    DashboardHandler.secure = False


def test_idle_client_disconnected(dashboard, monkeypatch):
    """Plain HTTP client sending nothing never holds a handler thread (socket timeout)"""
    import socket

    assert DashboardHandler.timeout == 15
    monkeypatch.setattr(DashboardHandler, "timeout", 0.5)
    with socket.create_connection(("127.0.0.1", PORT), timeout=5) as client:
        start = time.monotonic()
        assert client.recv(1024) == b""  # closed by server, no request sent
        assert time.monotonic() - start < 4


def test_port_out_of_range_reported(ui_env):
    """OverflowError at bind reported like a busy port, never crashes app start"""
    from tinypedal import app_signal

    errors = []
    app_signal.error.connect(errors.append)
    try:
        cfg.user.config["web_dashboard"].update(enable_web_dashboard=True, web_dashboard_port=70000, enable_https=False)
        server = WebDashboard()
        server.enable()
        assert not server.running
        assert errors and "port 70000 unavailable" in errors[0]
    finally:
        app_signal.error.disconnect(errors.append)
