"""Remote control command server tests (localhost only)"""

import json
import urllib.error
import urllib.request

import pytest
from PySide6.QtCore import QCoreApplication

from tinypedal import app_signal
from tinypedal.command_server import CommandServer
from tinypedal.setting import cfg
from tinypedal.userfile.json_setting import copy_setting

PORT = 18337


@pytest.fixture
def server(monkeypatch):
    cfg.default.set_default()
    config = copy_setting(cfg.default.config)
    config["remote_control"].update(enable_remote_control=True, remote_control_port=PORT)
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    received = []
    app_signal.hotkey.connect(received.append)
    control = CommandServer()
    control.enable()
    yield received
    control.disable()
    app_signal.hotkey.disconnect(received.append)


def request(path, method="GET", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_list_commands(server):
    status, data = request("/commands")
    assert status == 200
    assert "overlay_lock" in data["commands"]


def test_run_command_requires_header(server):
    status, _ = request("/command/overlay_lock", method="POST")
    assert status == 403
    assert server == []


def test_run_command(server):
    status, data = request("/command/overlay_lock", method="POST", headers={"X-TinyPedal": "1"})
    assert status == 200 and data["ok"]
    QCoreApplication.processEvents()  # command is queued to main thread
    assert len(server) == 1 and callable(server[0])


def test_unknown_command(server):
    status, _ = request("/command/format_disk", method="POST", headers={"X-TinyPedal": "1"})
    assert status == 404


def test_dns_rebinding_blocked(server):
    status, data = request(
        "/command/overlay_lock", method="POST", headers={"X-TinyPedal": "1", "Host": f"evil.example:{PORT}"}
    )
    assert status == 403 and "host" in data["error"]
    assert server == []
    status, _ = request("/commands", headers={"Host": "attacker.test"})
    assert status == 403


def test_allowed_hosts():
    from tinypedal.command_server import is_allowed_host

    assert is_allowed_host(f"localhost:{PORT}", PORT)
    assert is_allowed_host(f"127.0.0.1:{PORT}", PORT)
    assert not is_allowed_host(f"127.0.0.1.evil.test:{PORT}", PORT)
    assert not is_allowed_host(None, PORT)
