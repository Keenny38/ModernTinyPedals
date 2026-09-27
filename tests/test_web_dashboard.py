"""Web dashboard tests (localhost only)"""

import json
import urllib.error
import urllib.request

import pytest

from tinypedal.setting import cfg
from tinypedal.web_dashboard import DashboardHandler, WebDashboard, generate_access_code

PORT = 18338


@pytest.fixture
def dashboard(ui_env):
    config = cfg.user.config["web_dashboard"]
    config.update(enable_web_dashboard=True, web_dashboard_port=PORT, access_code="TESTCODE")
    server = WebDashboard()
    server.enable()
    yield server
    server.disable()


def get(path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_page_requires_code(dashboard):
    status, body = get("/")
    assert status == 401 and b"Access code" in body
    status, body = get("/?code=TESTCODE")
    assert status == 200 and b"TinyPedal Dashboard" in body


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


def test_access_code_generated(ui_env):
    cfg.user.config["web_dashboard"]["access_code"] = ""
    code = WebDashboard.access_code()
    assert len(code) == 8 and cfg.user.config["web_dashboard"]["access_code"] == code
    assert generate_access_code() != generate_access_code()


def test_localhost_only_by_default(ui_env):
    assert WebDashboard.host() == "127.0.0.1"
    cfg.user.config["web_dashboard"]["enable_lan_access"] = True
    assert WebDashboard.host() == "0.0.0.0"
