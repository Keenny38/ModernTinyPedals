"""rF2 REST API tasks: task set & values read from a local HTTP server answering like the game"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from neopedal import realtime_state
from neopedal.adapter.restapi_connector import RestAPIConnector
from neopedal.adapter.rf2_restapi import RestAPIData, rf2_restapi_tasks
from neopedal.const_api import API_RF2_CONFIG
from neopedal.process.garage import reset_rf2_setup_parts
from neopedal.process.weather import FORECAST_DEFAULT
from neopedal.template.setting_api import API_DEFAULT


def weather_node(sky: int, temperature: float, rain: float) -> dict:
    return {
        "WNV_SKY": {"currentValue": sky},
        "WNV_TEMPERATURE": {"currentValue": temperature},
        "WNV_RAIN_CHANCE": {"currentValue": rain},
    }


def session_forecast(offset: int) -> dict:
    return {
        node: weather_node(index + offset, 20.0 + index, index * 10)
        for index, node in enumerate(("START", "NODE_25", "NODE_50", "NODE_75", "FINISH"))
    }


RESOURCES = {
    "/rest/sessions/weather": {
        "PRACTICE": session_forecast(0), "QUALIFY": session_forecast(1), "RACE": session_forecast(2),
    },
    "/rest/sessions/setting/SESSSET_race_timescale": {"currentValue": 4},
    "/rest/sessions/setting/SESSSET_private_qual": {"currentValue": 1},
    # garage endpoints not answered (404): no car setup exported
}


class GameHandler(BaseHTTPRequestHandler):
    requested: list[str] = []

    def do_GET(self):  # http.server API name
        self.requested.append(self.path)
        if self.path not in RESOURCES:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps(RESOURCES[self.path]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def game_server():
    GameHandler.requested = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), GameHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def wait_until(check, timeout=10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_task_set_matches_data_and_options():
    tasks = rf2_restapi_tasks()
    paths = [task.path for task in tasks]
    assert len(paths) == len(set(paths)) and all(path.startswith("/rest/") for path in paths)
    data = RestAPIData()
    options = API_DEFAULT[API_RF2_CONFIG]
    for task in tasks:
        assert options[task.condition] is True  # condition is an option of rF2 API, on by default
        assert not task.repeated and task.interval > 0
        for output in task.outputs:
            assert hasattr(data, output.name)
            assert getattr(data, output.name) == output.default  # data starts at task default


def test_garage_tasks_share_setup_output():
    garage = [task for task in rf2_restapi_tasks() if task.path.startswith("/rest/garage/")]
    assert len(garage) == 9
    assert {task.outputs[0].name for task in garage} == {"lastCarSetup"}


def test_values_read_from_game(game_server, monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    data = RestAPIData()
    connector = RestAPIConnector(rf2_restapi_tasks(), data, on_start=reset_rf2_setup_parts)
    connector.setConnection({
        **API_DEFAULT[API_RF2_CONFIG],
        "url_host": "127.0.0.1", "url_port": game_server, "restapi_update_interval": 100,
        "connection_timeout": 1, "connection_retry": 0, "connection_retry_delay": 0,
    })
    connector.start()
    try:
        assert wait_until(lambda: data.timeScale == 4 and data.privateQualifying == 1
                          and data.forecastRace != FORECAST_DEFAULT)
        race = data.forecastRace
        assert len(race) == 5
        assert [node.start for node in race] == [0.0, 0.2, 0.4, 0.6, 0.8]
        assert race[0].sky_type == 2 and race[4].temperature == 24.0
        assert race[3].rain_chance == pytest.approx(0.3)
        assert data.forecastPractice[0].sky_type == 0 and data.forecastQualify[0].sky_type == 1
        assert data.lastCarSetup == ()  # garage not answered: nothing exported
        assert wait_until(lambda: "/rest/garage/tires" in GameHandler.requested)
    finally:
        monkeypatch.setattr(realtime_state, "active", False)  # leaving track: data back to defaults
        assert wait_until(lambda: data.timeScale == 1 and data.forecastRace == FORECAST_DEFAULT)
        connector.stop()


def test_disabled_option_never_requested(game_server, monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    data = RestAPIData()
    connector = RestAPIConnector(rf2_restapi_tasks(), data)
    connector.setConnection({
        **API_DEFAULT[API_RF2_CONFIG],
        "url_host": "127.0.0.1", "url_port": game_server, "restapi_update_interval": 100,
        "connection_timeout": 1, "connection_retry": 0, "connection_retry_delay": 0,
        "enable_weather_info": False, "enable_garage_setup_info": False,
    })
    connector.start()
    try:
        assert wait_until(lambda: data.timeScale == 4)
        assert data.forecastRace == FORECAST_DEFAULT
        assert not any(path.startswith(("/rest/sessions/weather", "/rest/garage/")) for path in GameHandler.requested)
    finally:
        monkeypatch.setattr(realtime_state, "active", False)
        connector.stop()
