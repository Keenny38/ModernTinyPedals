"""Remote control command server tests (localhost only)"""

import base64
import json
import os
import socket
import struct
import sys
import urllib.error
import urllib.request

import pytest
from PySide6.QtCore import QCoreApplication

from tinypedal import app_signal, command_server
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


# Live telemetry stream (WebSocket)

def ws_connect(path="/stream?interval=20", headers="", port=PORT):
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n{headers}\r\n"
    ).encode())
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(1)
    return sock, key, response.decode()


def ws_read(sock):
    first, second = command_server.read_exact(sock, 2)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", command_server.read_exact(sock, 2))[0]
    return first & 0x0F, command_server.read_exact(sock, size)


def ws_send(sock, opcode, payload=b""):
    mask = os.urandom(4)
    body = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(struct.pack("!BB", 0x80 | opcode, 0x80 | len(payload)) + mask + body)


@pytest.fixture
def stream_data(monkeypatch):
    counter = iter(range(1000))
    monkeypatch.setattr(command_server.CommandHandler, "snapshot", staticmethod(lambda: {"tick": next(counter)}))


def test_stream_pushes_json(server, stream_data):
    sock, key, response = ws_connect()
    with sock:
        assert response.startswith("HTTP/1.1 101")
        assert command_server.websocket_accept(key) in response
        ticks = [json.loads(ws_read(sock)[1])["tick"] for _ in range(3)]
        assert ticks == sorted(ticks) and len(set(ticks)) == 3
        ws_send(sock, command_server.WS_OP_PING, b"hi")
        frames = [ws_read(sock) for _ in range(3)]
        assert (command_server.WS_OP_PONG, b"hi") in frames
        ws_send(sock, command_server.WS_OP_CLOSE, b"\x03\xe8")
        while (frame := ws_read(sock))[0] != command_server.WS_OP_CLOSE:
            pass
        assert frame[1] == b"\x03\xe8"


def test_stream_rejects_foreign_origin(server, stream_data):
    sock, _, response = ws_connect(headers="Origin: https://evil.example\r\n")
    sock.close()
    assert response.split()[1] == "403"


def test_stream_requires_upgrade(server):
    assert request("/stream")[0] == 426


def test_stream_ends_when_server_stops(stream_data, monkeypatch):
    cfg.default.set_default()
    config = copy_setting(cfg.default.config)
    config["remote_control"].update(enable_remote_control=True, remote_control_port=PORT)
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    control = CommandServer()
    control.enable()
    sock, _, _ = ws_connect()
    with sock:
        ws_read(sock)
        control.disable()
        with pytest.raises((ConnectionError, OSError)):
            for _ in range(100):
                ws_read(sock)


@pytest.mark.parametrize(("origin", "allowed"), [
    (None, True), ("http://localhost:8080", True), ("http://127.0.0.1", True),
    ("https://evil.example", False), ("http://localhost.evil.example", False),
    ("null", False), (" NULL ", False),  # sandboxed frame of any site can send "null"
])
def test_allowed_origin(origin, allowed):
    assert command_server.is_allowed_origin(origin) is allowed


def test_stream_interval_bounds():
    assert command_server.stream_interval("/stream") == 0.1
    assert command_server.stream_interval("/stream?interval=1") == 0.02
    assert command_server.stream_interval("/stream?interval=abc") == 0.1
    assert command_server.stream_interval("/stream?interval=99999") == 5.0


def test_stream_options_fields_and_changes():
    options = command_server.StreamOptions.from_path("/stream?fields=speed,gear&changes=1")
    assert options.fields == {"speed", "gear"} and options.changes
    assert options.payload({"speed": 100, "gear": 3, "rpm": 7000}) == {"speed": 100, "gear": 3}  # first: full
    assert options.payload({"speed": 100, "gear": 3, "rpm": 7100}) is None  # nothing changed
    assert options.payload({"speed": 101, "gear": 3}) == {"speed": 101}
    options.update(b'{"fields": null, "changes": false}')
    assert options.fields is None and not options.changes
    assert options.payload({"speed": 101, "rpm": 1}) == {"speed": 101, "rpm": 1}
    options.update(b"not json")  # ignored
    assert options.fields is None
    plain = command_server.StreamOptions.from_path("/stream")
    assert plain.fields is None and not plain.changes


def test_stream_subscription_message(server, monkeypatch):
    monkeypatch.setattr(
        command_server.CommandHandler, "snapshot", staticmethod(lambda: {"speed": 100, "gear": 3}))
    sock, _, _ = ws_connect("/stream?interval=20&fields=speed")
    with sock:
        assert json.loads(ws_read(sock)[1]) == {"speed": 100}
        ws_send(sock, command_server.WS_OP_TEXT, b'{"fields": ["gear"]}')
        for _ in range(20):
            if json.loads(ws_read(sock)[1]) == {"gear": 3}:
                break
        else:
            pytest.fail("subscription not updated")


@pytest.mark.skipif(sys.platform != "win32", reason="SO_EXCLUSIVEADDRUSE is Windows only")
def test_port_held_exclusively():
    """Second server on a port in use refused (SO_REUSEADDR alone allows it on Windows)"""
    from http.server import BaseHTTPRequestHandler

    first = command_server.LocalHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        with pytest.raises(OSError):
            command_server.LocalHTTPServer(("127.0.0.1", first.server_address[1]), BaseHTTPRequestHandler)
    finally:
        first.server_close()


def test_idle_client_disconnected(server, monkeypatch):
    """Client sending nothing never holds a handler thread (socket timeout)"""
    import time

    assert command_server.CommandHandler.timeout == 15
    monkeypatch.setattr(command_server.CommandHandler, "timeout", 0.5)
    with socket.create_connection(("127.0.0.1", PORT), timeout=5) as client:
        start = time.monotonic()
        assert client.recv(1024) == b""  # closed by server, no request sent
        assert time.monotonic() - start < 4


def test_stream_to_stalled_client_ends(server, monkeypatch, caplog):
    """Client not reading: send times out, stream thread ends (disable can stop it)"""
    import logging
    import time

    monkeypatch.setattr(command_server.CommandHandler, "stream_timeout", 0.3)
    monkeypatch.setattr(command_server.CommandHandler, "snapshot", staticmethod(lambda: {"x": "a" * 1_000_000}))
    caplog.set_level(logging.INFO, logger=command_server.logger.name)
    sock, _, response = ws_connect()
    with sock:
        assert response.startswith("HTTP/1.1 101")
        deadline = time.monotonic() + 10
        while "stream client disconnected" not in caplog.text and time.monotonic() < deadline:
            time.sleep(0.05)
    assert "stream client disconnected" in caplog.text


@pytest.mark.parametrize("port", [70000, -1])
def test_port_out_of_range_reported(port, monkeypatch):
    """OverflowError at bind reported like a busy port, never crashes app start"""
    cfg.default.set_default()
    config = copy_setting(cfg.default.config)
    config["remote_control"].update(enable_remote_control=True, remote_control_port=port)
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    errors = []
    app_signal.error.connect(errors.append)
    try:
        control = CommandServer()
        control.enable()
        assert not control.running
        assert errors and f"port {port} unavailable" in errors[0]
    finally:
        app_signal.error.disconnect(errors.append)


def test_listening_signaled_only_after_failure():
    """Listening on first try: no signal; listening after a failure: signaled once"""
    signaled = []

    def on_listening():
        signaled.append(1)

    app_signal.servers.connect(on_listening)
    errors = []
    app_signal.error.connect(errors.append)
    try:
        retry = command_server.BindRetry("Test", lambda: None)
        retry.listening()
        assert not signaled
        retry.failed(("127.0.0.1", 70000), OverflowError("port out of range"))  # never tried again
        retry.listening()
        retry.listening()
        assert len(signaled) == 1
        retry.failed(("127.0.0.1", 70000), OverflowError("port out of range"))
        retry.stop()  # disabled: not listening
        assert len(signaled) == 1
    finally:
        app_signal.servers.disconnect(on_listening)
        app_signal.error.disconnect(errors.append)


def test_bind_error_text():
    assert command_server.bind_error_text(OSError(98, "Address in use")) == "Address in use"
    assert command_server.bind_error_text(OverflowError("port must be 0-65535.")) == "port must be 0-65535."


# Reload, stop, listening tried again
def process_events(seconds: float):
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def remote_config(monkeypatch, **options):
    cfg.default.set_default()
    config = copy_setting(cfg.default.config)
    config["remote_control"].update({"enable_remote_control": True, "remote_control_port": PORT, **options})
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    return config["remote_control"]


def assert_closed_soon(sock, seconds=3.0):
    """Server ended the connection (EOF or reset) before timeout, frames still pushed meanwhile are skipped"""
    import time

    sock.settimeout(0.2)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if sock.recv(65536) == b"":
                return
        except TimeoutError:
            continue
        except OSError:
            return  # reset
    pytest.fail("connection still open")


def mock_loader(monkeypatch, **kept):
    """Loader with every part mocked except the given ones, calls recorded"""
    from types import SimpleNamespace

    from tinypedal import loader

    calls = []
    for name in ("octrl", "mctrl", "wctrl", "kctrl", "cmdserver", "webdashboard", "streamoverlay", "api"):
        if name in kept:
            monkeypatch.setattr(loader, name, kept[name])
            continue
        monkeypatch.setattr(loader, name, SimpleNamespace(**{
            action: (lambda *args, _name=name, _action=action: calls.append(f"{_name}.{_action}"))
            for action in ("enable", "disable", "suspend", "start", "close", "stop", "restart", "connect")}))
    monkeypatch.setattr(loader, "vroverlay", lambda: SimpleNamespace(enable=lambda: None, disable=lambda: None))
    monkeypatch.setattr(loader, "sync_screen_layout", lambda: None)
    return loader, calls


def test_stream_ended_by_disable_when_enabled_again(stream_data, monkeypatch):
    """Server stopped then started again at once (reload, port change): stream of the old server ends,
    never kept pushing (stop event shared by servers was cleared again, connection never closed)"""
    remote_config(monkeypatch)
    control = CommandServer()
    control.enable()
    try:
        sock, _, _ = ws_connect("/stream?interval=5000")
        with sock:
            ws_read(sock)
            control.disable()
            control.enable()
            assert control.running
            assert_closed_soon(sock)
    finally:
        control.disable()


def test_reload_keeps_remote_control_listening(stream_data, monkeypatch):
    """App reload (settings Apply, preset loaded): server kept, connected stream client (SimHub) still served

    Windows binds the port exclusively (no address reuse): a server stopped & started again while a client
    was connected could not listen again, remote control lost until next restart.
    """
    monkeypatch.setattr(command_server.LocalHTTPServer, "allow_reuse_address", False)  # as on Windows
    port = free_port()  # never held by connections of previous tests
    remote_config(monkeypatch, remote_control_port=port)
    control = CommandServer()
    loader, calls = mock_loader(monkeypatch, cmdserver=control)
    control.enable()
    try:
        sock, _, _ = ws_connect(port=port)
        with sock:
            ws_read(sock)
            loader.reload()
            assert "wctrl.start" in calls and control.running
            assert json.loads(ws_read(sock)[1])  # same connection still served
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/commands", timeout=5) as response:
            assert response.status == 200
    finally:
        control.disable()


def test_reload_applies_remote_control_setting(monkeypatch):
    """Port changed: server listens on new port, old one closed; turned off: server stopped"""
    setting = remote_config(monkeypatch)
    control = CommandServer()
    loader, _ = mock_loader(monkeypatch, cmdserver=control)
    control.enable()
    try:
        new_port = free_port()
        setting["remote_control_port"] = new_port
        loader.reload()
        assert control.running
        with urllib.request.urlopen(f"http://127.0.0.1:{new_port}/commands", timeout=5) as response:
            assert response.status == 200
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", PORT), timeout=2).close()
        setting["enable_remote_control"] = False
        loader.reload()
        assert not control.running
    finally:
        control.disable()


def test_quit_stops_servers(monkeypatch):
    """Quit & app restart (close): servers stopped, not kept as on reload"""
    remote_config(monkeypatch)
    control = CommandServer()
    loader, calls = mock_loader(monkeypatch, cmdserver=control)
    control.enable()
    try:
        loader.unload_modules()
        assert not control.running
        assert "webdashboard.disable" in calls and "streamoverlay.disable" in calls
    finally:
        control.disable()


def test_listening_tried_again_until_port_free(monkeypatch):
    """Port held (Windows: connections of a stopped server, up to minutes): server started once free,
    error reported once"""
    monkeypatch.setattr(command_server, "BIND_RETRY_MS", 20)
    errors = []
    listening = []

    def on_listening():
        listening.append(1)

    app_signal.error.connect(errors.append)
    app_signal.servers.connect(on_listening)
    control = CommandServer()
    busy = socket.socket()
    try:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        remote_config(monkeypatch, remote_control_port=busy.getsockname()[1])
        control.enable()
        process_events(0.1)
        assert not control.running and len(errors) == 1 and not listening
        busy.close()
        import time

        end = time.monotonic() + 3
        while not control.running and time.monotonic() < end:
            process_events(0.02)
        assert control.running and len(errors) == 1
        assert len(listening) == 1  # status shown again (settings card)
        control.enable()  # already listening: not signaled again
        assert len(listening) == 1
    finally:
        busy.close()
        control.disable()
        app_signal.error.disconnect(errors.append)
        app_signal.servers.disconnect(on_listening)
    process_events(0.1)
    assert not control.running  # disabled: not tried again


# Connection limits, request deadline (slow clients never use up threads)
@pytest.fixture
def local_server(monkeypatch):
    """Command handler on an ephemeral port, server object returned"""
    import threading

    monkeypatch.setattr(command_server.CommandHandler, "commands", {"overlay_lock": lambda: None})
    httpd = command_server.LocalHTTPServer(("127.0.0.1", 0), command_server.CommandHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.stop()


def test_connections_over_limit_refused(local_server, monkeypatch):
    """Connections above server limit closed at once, accepted again once one is closed"""
    import time

    monkeypatch.setattr(local_server, "max_connections", 3)
    port = local_server.server_port
    held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(3)]
    try:
        end = time.monotonic() + 3
        while len(local_server._connections) < 3 and time.monotonic() < end:
            time.sleep(0.01)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as extra:
            assert_closed_soon(extra, 2)
        held.pop().close()
        end = time.monotonic() + 3
        while len(local_server._connections) > 2 and time.monotonic() < end:
            time.sleep(0.01)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(f"GET /commands HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
            assert client.recv(1024).startswith(b"HTTP/1.0 200")
    finally:
        for sock in held:
            sock.close()


def test_connections_per_address_limited(local_server, monkeypatch):
    """Another computer (LAN) holds a few connections only, this computer counted in server limit only"""
    monkeypatch.setattr(local_server, "max_connections_per_address", 2)
    sockets = [socket.socket() for _ in range(6)]
    try:
        assert local_server.verify_request(sockets[0], ("192.168.1.5", 50000))
        assert local_server.verify_request(sockets[1], ("192.168.1.5", 50001))
        assert not local_server.verify_request(sockets[2], ("192.168.1.5", 50002))
        assert local_server.verify_request(sockets[3], ("192.168.1.6", 50000))  # other address
        assert local_server.verify_request(sockets[4], ("127.0.0.1", 50000))
        assert local_server.verify_request(sockets[5], ("127.0.0.1", 50001))
        local_server.shutdown_request(sockets[0])  # closed: slot of address free again
        assert local_server.verify_request(sockets[2], ("192.168.1.5", 50002))
    finally:
        for sock in sockets:
            sock.close()


@pytest.mark.parametrize("partial", [
    b"GET /commands HTTP/1.1\r\n",  # headers sent slowly
    b"POST /command/overlay_lock HTTP/1.1\r\nHost: 127.0.0.1\r\nX-TinyPedal: 1\r\n",
])
def test_slow_request_closed_at_deadline(local_server, monkeypatch, partial):
    """Client sending a byte now and then (each read under socket timeout) closed once request deadline passed"""
    import time

    monkeypatch.setattr(command_server.CommandHandler, "request_seconds", 0.5)
    with socket.create_connection(("127.0.0.1", local_server.server_port), timeout=5) as client:
        client.sendall(partial)
        start = time.monotonic()
        client.settimeout(0.1)
        closed = False
        while time.monotonic() - start < 4:
            try:
                client.sendall(b"X")  # header line never ending
                if client.recv(1024) == b"":
                    closed = True
                    break
            except TimeoutError:
                continue
            except OSError:
                closed = True
                break
        assert closed and time.monotonic() - start < 3


def test_keep_alive_idle_not_bounded_by_request_deadline(local_server, monkeypatch):
    """Kept connection waiting longer than request deadline between requests stays open (socket timeout)"""
    import http.client
    import time

    monkeypatch.setattr(command_server.CommandHandler, "request_seconds", 0.3)
    monkeypatch.setattr(command_server.CommandHandler, "protocol_version", "HTTP/1.1")
    port = local_server.server_port
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        for _ in range(2):
            client.request("GET", "/commands", headers={"Host": f"127.0.0.1:{port}"})
            response = client.getresponse()
            assert response.status == 200 and json.loads(response.read())
            assert not response.will_close
            time.sleep(0.6)
        sock = client.sock
        client.request("GET", "/commands", headers={"Host": f"127.0.0.1:{port}"})
        assert client.getresponse().status == 200
        assert client.sock is sock  # same connection
    finally:
        client.close()
