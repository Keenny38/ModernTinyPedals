"""REST API connector against a local HTTP server: one time & repeated resources, missing data, reset on stop"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from tinypedal import realtime_state
from tinypedal.adapter.restapi_connector import (
    ResOutput,
    RestAPIConnector,
    RestAPITask,
    reset_to_default,
)

RESOURCES = {
    "/rest/car": {"car": {"speed": 55.5, "gear": 4}},
    "/rest/session": {"name": "Race"},
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # http.server API name
        data = RESOURCES.get(self.path)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def parse_float(data, default):
    return float(data) if isinstance(data, (int, float)) else default


TASKS = (
    RestAPITask("/rest/car", (
        ResOutput("speed", 0.0, parse_float, ("car", "speed")),
        ResOutput("gear", 0.0, parse_float, ("car", "gear")),
        ResOutput("missing", -1.0, parse_float, ("car", "fuel")),
    ), "enable_car", True, 0.1),
    RestAPITask("/rest/session", (ResOutput("session", "", lambda data, default: str(data), ("name",)),),
                "enable_session", False, 0.1),
    RestAPITask("/rest/none", (ResOutput("other", "x", lambda data, default: data, ("a",)),),
                "enable_none", False, 0.1),
    RestAPITask("/rest/disabled", (ResOutput("off", "d", lambda data, default: data),), "enable_off", True, 0.1),
)


def wait_until(check, timeout=10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_connector_updates_and_resets(server, monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    data = SimpleNamespace(speed=0.0, gear=0.0, missing=-1.0, session="", other="x", off="d")
    connector = RestAPIConnector(TASKS, data)
    connector.setConnection({
        "enable_restapi_access": True, "restapi_update_interval": 100, "url_host": "127.0.0.1", "url_port": server,
        "connection_timeout": 1.0, "connection_retry": 0, "connection_retry_delay": 0,
        "enable_off": False,  # task condition off: never requested
    })
    connector.start()
    try:
        assert wait_until(lambda: data.speed == 55.5 and data.session == "Race")
        assert data.gear == 4.0 and data.missing == -1.0  # missing key: default
        assert data.other == "x" and data.off == "d"  # 404 & disabled task: defaults
        monkeypatch.setitem(RESOURCES, "/rest/car", {"car": {"speed": 80.0, "gear": 5}})  # repeated task follows
        assert wait_until(lambda: data.speed == 80.0)
    finally:
        monkeypatch.setattr(realtime_state, "active", False)  # leaving track: tasks cancelled, data reset
        assert wait_until(lambda: data.speed == 0.0 and data.session == "")
        connector.stop()


def test_disabled_access_never_starts():
    connector = RestAPIConnector(TASKS, SimpleNamespace())
    connector.setConnection({"enable_restapi_access": False, "restapi_update_interval": 10})
    connector.start()
    assert connector._update_thread is None
    connector.stop()


def test_output_update_and_reset():
    output = ResOutput("value", 1.5, parse_float, ("a", "b"))
    data = SimpleNamespace(value=0.0)
    assert output.update(data, {"a": {"b": 3}}) and data.value == 3.0
    assert not output.update(data, {"a": "text"}) and data.value == 1.5  # not a dict on the way
    assert not output.update(data, {"a": {}}) and data.value == 1.5
    data.value = 9.0
    active = {"/x": (output,)}
    reset_to_default(data, active)
    assert data.value == 1.5 and not active
