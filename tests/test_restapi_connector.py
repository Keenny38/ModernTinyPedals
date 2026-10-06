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
        if self.path not in RESOURCES:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(RESOURCES[self.path]).encode()  # None: "null", game outside session
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


# --- Audit fixes (package A)
def config(port, **extra) -> dict:
    return {
        "enable_restapi_access": True, "restapi_update_interval": 100, "url_host": "127.0.0.1", "url_port": port,
        "connection_timeout": 1.0, "connection_retry": 0, "connection_retry_delay": 0, **extra,
    }


def test_valid_json_value_accepts_json_numbers():
    from tinypedal.adapter.restapi_connector import valid_json_value

    assert valid_json_value(35, 0.0) == 35.0 and isinstance(valid_json_value(35, 0.0), float)  # was 0.0
    assert valid_json_value(12.5, 0.0) == 12.5
    assert valid_json_value(True, 0.0) == 0.0  # bool is not a number
    assert valid_json_value(float("nan"), -1.0) == -1.0
    assert valid_json_value(10**400, 0.0) == 0.0
    assert valid_json_value(4.0, 1) == 4 and valid_json_value(4.5, 1) == 1 and valid_json_value(False, 1) == 1
    assert valid_json_value(True, False) is True and valid_json_value(1, False) is False
    assert valid_json_value("x", "") == "x" and valid_json_value(3, "") == ""


def test_lmu_numbers_from_json_ints():
    from tinypedal.adapter import lmu_restapi

    data = lmu_restapi.RestAPIData()
    tasks = {task.path: task for task in lmu_restapi.lmu_restapi_tasks()}
    for res in tasks["/rest/strategy/pitstop-estimate"].outputs:
        res.update(data, {"total": 35, "damage": 12})
    assert data.pitStopTime == 35.0 and data.repairTime == 12.0
    assert tasks["/rest/chat/"].max_interval == 1.0  # chat & contacts not delayed up to 5s
    assert tasks["/rest/watch/getIncidentsList/1"].max_interval == 1.0


def test_absolute_refilling_without_settings():
    from tinypedal.process.vehicle import absolute_refilling

    assert absolute_refilling([{"name": "FUEL:"}], 0.0) == 0.0  # KeyError used to stop the task
    assert absolute_refilling([{"name": "FUEL:", "currentSetting": 1, "settings": [{}, {"text": "40 L"}]}], 0.0) == 40.0


def test_bad_entry_does_not_stop_updates(server, monkeypatch, caplog):
    def broken(data, default):
        raise KeyError("settings")

    tasks = (RestAPITask("/rest/car", (
        ResOutput("broken", -1.0, broken, ("car", "speed")),
        ResOutput("speed", 0.0, parse_float, ("car", "speed")),
    ), "enable_car", True, 0.1),)
    monkeypatch.setattr(realtime_state, "active", True)
    data = SimpleNamespace(broken=-1.0, speed=0.0)
    connector = RestAPIConnector(tasks, data)
    connector.setConnection(config(server))
    connector.start()
    try:
        assert wait_until(lambda: data.speed == 55.5)
        monkeypatch.setitem(RESOURCES, "/rest/car", {"car": {"speed": 70.0}})
        assert wait_until(lambda: data.speed == 70.0)  # repeated updates go on
        assert data.broken == -1.0
        status = connector.status()[0]
        assert status.state == "active" and status.error == "parser error" and status.updated > 0
    finally:
        monkeypatch.setattr(realtime_state, "active", False)
        connector.stop()
    assert sum("unable to parse broken" in record.message for record in caplog.records) == 1  # warned once


def test_null_answer_polled_again(server, monkeypatch):
    """Game answers null around session changes: resource requested again, not abandoned"""
    from tinypedal.adapter import restapi_connector

    monkeypatch.setattr(restapi_connector, "retry_delay", lambda attempt, retry, delay: 0.05)
    monkeypatch.setitem(RESOURCES, "/rest/session", None)
    monkeypatch.setattr(realtime_state, "active", True)
    data = SimpleNamespace(session="")
    tasks = (RestAPITask("/rest/session", (ResOutput("session", "", lambda d, default: str(d), ("name",)),),
                         "enable_session", False, 0.1),)
    connector = RestAPIConnector(tasks, data)
    connector.setConnection(config(server))
    connector.start()
    try:
        assert wait_until(lambda: connector.status()[0].state == "missing")
        assert connector.status()[0].error == "no data"
        monkeypatch.setitem(RESOURCES, "/rest/session", {"name": "Race"})
        assert wait_until(lambda: data.session == "Race")
        assert connector.status()[0].state == "active"
    finally:
        monkeypatch.setattr(realtime_state, "active", False)
        connector.stop()


def test_retry_delay_grows_to_limit():
    from tinypedal.adapter.restapi_connector import MISSING_RETRY_MAX, retry_delay

    assert [retry_delay(attempt, 3, 1.0) for attempt in (1, 3)] == [1.0, 1.0]
    assert retry_delay(4, 3, 1.0) == 2.0 and retry_delay(50, 3, 1.0) == MISSING_RETRY_MAX


def test_unchanged_data_interval_limit(monkeypatch):
    import asyncio

    from tinypedal.adapter import restapi_connector

    connector = RestAPIConnector((), SimpleNamespace())
    state = restapi_connector.TaskState()
    intervals = []

    async def same_data(self, *args):
        return 1

    async def sleep(seconds):
        intervals.append(seconds)
        if len(intervals) >= 12:
            state.cancel = True

    monkeypatch.setattr(RestAPIConnector, "output_resource", same_data)
    monkeypatch.setattr(restapi_connector.asyncio, "sleep", sleep)
    asyncio.run(connector.update_repeat(None, b"", "/x", (), state, 0.2, 1.0))
    assert intervals[0] == 0.2 and intervals[1] > 0.2 and max(intervals) == 1.0


def test_stop_does_not_wait_for_host_resolving(monkeypatch):
    """API restart from user interface: stop never waits for probing (up to 3s)"""
    import asyncio

    from tinypedal.adapter import restapi_connector

    async def slow_resolve(host, port, timeout=3):
        await asyncio.sleep(10)
        return host

    monkeypatch.setattr(restapi_connector, "resolve_hostname_async", slow_resolve)
    monkeypatch.setattr(realtime_state, "active", True)
    connector = RestAPIConnector(TASKS, SimpleNamespace())
    connector.setConnection(config(1))
    connector.start()
    time.sleep(0.7)  # resolving
    start = time.monotonic()
    connector.stop()
    assert time.monotonic() - start < 1.5
    assert not connector._update_thread.is_alive()


def test_dead_after_repeated_errors_resets_data(monkeypatch):
    import threading

    from tinypedal.adapter import restapi_connector

    output = ResOutput("speed", 0.0, parse_float)
    data = SimpleNamespace(speed=90.0)
    connector = RestAPIConnector((RestAPITask("/rest/car", (output,), "", True, 0.1),), data)
    state = restapi_connector.TaskState()
    state.active_tasks["/rest/car"] = (output,)
    monkeypatch.setattr(restapi_connector, "run_supervised", lambda *args: False)
    connector._RestAPIConnector__update(threading.Event(), state)
    assert data.speed == 0.0  # no frozen value left
    assert connector.status()[0].state == "dead"


def test_session_start_hook_clears_rf2_setup_parts():
    from tinypedal import api_connector
    from tinypedal.process import garage

    garage._rf2_setup_parts["VM_OIL_RADIATOR"] = {"value": 1}  # incomplete setup of previous car
    sim = api_connector.SimRF2()
    sim._restapi._on_start()
    assert not garage._rf2_setup_parts
    assert api_connector.SimLMULegacy()._restapi._taskset[0].path == "/rest/sessions/weather"
    assert any(task.path == "/rest/chat/" for task in api_connector.SimLMULegacy()._restapi._taskset)


def test_health_lists_rest_resources():
    from tinypedal import api_connector
    from tinypedal.adapter import lmu_restapi

    health = api_connector.SimLMU().health()
    assert health.data_age == -1.0 and not health.replaying and not health.error
    assert len(health.rest) == len(lmu_restapi.lmu_restapi_tasks())
    assert {status.state for status in health.rest} == {"idle"}


# --- Audit fixes (thread & task state)
def test_host_resolving_cancelled_by_brief_leave_retried(server, monkeypatch):
    """Resolving cancelled while briefly off track: tasks launched again once back on track"""
    import asyncio

    from tinypedal.adapter import restapi_connector

    calls = []

    async def resolve(host, port, timeout=3):
        calls.append(host)
        if len(calls) == 1:  # active flicker during first resolving
            realtime_state.active = False
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                realtime_state.active = True
                raise
        return host

    monkeypatch.setattr(restapi_connector, "resolve_hostname_async", resolve)
    monkeypatch.setattr(realtime_state, "active", True)
    data = SimpleNamespace(speed=0.0, gear=0.0, missing=-1.0, session="", other="x", off="d")
    connector = RestAPIConnector(TASKS, data)
    connector.setConnection(config(server))
    connector.start()
    try:
        assert wait_until(lambda: data.speed == 55.5)  # was default the whole stint
        assert len(calls) >= 2
    finally:
        monkeypatch.setattr(realtime_state, "active", False)
        connector.stop()


def test_each_thread_has_own_task_state(monkeypatch):
    """Previous thread still stopping never shares cancel state & active tasks with the new one"""
    runs = []
    monkeypatch.setattr(
        RestAPIConnector, "_RestAPIConnector__update", lambda self, event, state: runs.append((event, state)))
    connector = RestAPIConnector(TASKS, SimpleNamespace())
    connector.setConnection(config(1))
    connector.start()
    connector.stop()
    connector.start()
    connector.stop()
    assert len(runs) == 2
    (event1, state1), (event2, state2) = runs
    assert event1 is not event2 and state1 is not state2
    assert state1.active_tasks is not state2.active_tasks
