"""Audit I, lot G: local servers, game Rest API, TLS, VR & local security

BUG-025 token required for app-wide commands, BUG-026 route parser failure, BUG-027 rest cache eviction,
BUG-028 private key access, BUG-045 TLS context replaced (never changed in service), BUG-046 frames pipelined
with the upgrade request, BUG-053 commands never sent twice, PERF-027 server restart without GUI wait,
PERF-028 shared stream snapshot & deadline, PERF-029 unresolved host kept, PERF-030 no fsync, PERF-031 results
scan cached, PERF-033 vectorized unmask, PERF-059 SteamVR start off the GUI thread, PERF-060 file lane,
PERF-067 fingerprint memo
"""

import asyncio
import base64
import http.client
import json
import logging
import os
import socket
import ssl
import struct
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import app_signal, command_server
from neopedal.command_server import (
    BindRetry,
    CommandHandler,
    CommandServer,
    FrameSource,
    LocalHTTPServer,
    PortClosing,
    SnapshotCache,
    unmask,
)
from neopedal.setting import cfg
from neopedal.userfile import tls_cert
from neopedal.userfile.json_setting import copy_setting


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def process_events(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def ws_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Masked client frame"""
    mask = os.urandom(4)
    body = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return struct.pack("!BB", 0x80 | opcode, 0x80 | len(payload)) + mask + body


def ws_upgrade(path: str, port: int) -> bytes:
    key = base64.b64encode(os.urandom(16)).decode()
    return (
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    ).encode()


def ws_response(sock: socket.socket) -> bytes:
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(1)
    return response


def ws_read(sock: socket.socket) -> tuple[int, bytes]:
    first, second = command_server.read_exact(sock, 2)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", command_server.read_exact(sock, 2))[0]
    return first & 0x0F, command_server.read_exact(sock, size)


@pytest.fixture
def remote(monkeypatch):
    """Remote control server on a free port, without access token: (port, commands received)"""
    cfg.default.set_default()
    config = copy_setting(cfg.default.config)
    port = free_port()
    config["remote_control"].update(enable_remote_control=True, remote_control_port=port)
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    received = []
    app_signal.hotkey.connect(received.append)
    control = CommandServer()
    control.enable()
    yield port, received
    control.disable()
    app_signal.hotkey.disconnect(received.append)


def post_command(port: int, name: str) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("POST", f"/command/{name}", headers={"X-NeoPedal": "1"})
    response = connection.getresponse()
    data = json.loads(response.read())
    connection.close()
    return response.status, data


# --- BUG-025: app-wide commands refused without an access token
@pytest.mark.parametrize("name", ["quit_application", "restart_application", "restart_api", "load_next_preset",
                                  "preset_1", "reload_preset"])
def test_app_wide_command_requires_token(remote, name):
    port, received = remote
    status, data = post_command(port, name)
    assert status == 403 and data["error"] == "token required" and data["command"] == name
    QCoreApplication.processEvents()
    assert received == []  # never run


def test_overlay_command_still_runs_without_token(remote):
    port, received = remote
    status, data = post_command(port, "overlay_lock")
    assert status == 200 and data["ok"]
    QCoreApplication.processEvents()
    assert len(received) == 1
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", "/commands")
    listed = json.loads(connection.getresponse().read())
    connection.close()
    assert "quit_application" in listed["token_required"] and "overlay_lock" not in listed["token_required"]


def test_app_wide_command_runs_with_token(remote):
    port, received = remote
    CommandHandler.token = "secret-token-of-16-chars"
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", "/command/quit_application", headers={"X-NeoPedal": "secret-token-of-16-chars"})
        assert connection.getresponse().status == 200
        connection.close()
    finally:
        CommandHandler.token = ""
    QCoreApplication.processEvents()
    assert len(received) == 1


# --- BUG-046: frames sent right after the upgrade request (before the 101 answer) are not lost
def test_frames_pipelined_with_upgrade_request_applied(remote, monkeypatch):
    port, _ = remote
    monkeypatch.setattr(CommandHandler, "snapshot", staticmethod(lambda: {"speed": 100, "gear": 3}))
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    with sock:
        # Options message in the same packet as the request: buffered by the request reader with the headers
        sock.sendall(ws_upgrade("/stream?interval=20", port) + ws_frame(command_server.WS_OP_TEXT,
                                                                       b'{"fields": ["gear"]}'))
        assert ws_response(sock).startswith(b"HTTP/1.1 101")
        opcode, payload = ws_read(sock)
        assert opcode == command_server.WS_OP_TEXT and json.loads(payload) == {"gear": 3}  # not lost: applied
        # Ping pipelined too (partly buffered frames would have desynchronized the stream: "frame too large")
        sock.sendall(ws_frame(command_server.WS_OP_PING, b"hi"))
        frames = [ws_read(sock) for _ in range(4)]
        assert (command_server.WS_OP_PONG, b"hi") in frames


def test_frame_source_reads_buffered_bytes_first():
    a, b = socket.socketpair()
    with a, b:
        frame = ws_frame(command_server.WS_OP_TEXT, b"hello world")
        source = FrameSource(a, frame[:5])  # start of the frame buffered, rest on the socket
        b.sendall(frame[5:])
        assert source.ready(1.0)
        assert command_server.read_websocket_frame(source) == (command_server.WS_OP_TEXT, b"hello world")
        assert not source.ready(0.0)


# --- PERF-033: unmask without a Python loop per byte
@pytest.mark.parametrize("size", [0, 1, 3, 4, 5, 1000, 65536])
def test_unmask_matches_byte_loop(size):
    data, mask = os.urandom(size), os.urandom(4)
    expected = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    assert unmask(data, mask) == expected


# --- PERF-028: snapshot shared per tick, loop never spins on a chatty client
def test_snapshot_shared_within_tick():
    calls = []

    def snapshot():
        calls.append(1)
        return {"n": len(calls)}

    cache = SnapshotCache()
    tick = command_server.SNAPSHOT_TICK_MS / 1000
    first = cache.data(snapshot, 100.0)
    assert cache.data(snapshot, 100.0 + tick / 2) is first and len(calls) == 1  # same tick: one snapshot
    assert cache.encoded(first) is cache.encoded(first) == b'{"n": 1}'  # encoded once
    assert cache.data(snapshot, 100.0 + tick * 2) is not first and len(calls) == 2
    assert cache.encoded({"other": 1}) == b'{"other": 1}'  # a client's filtered message encoded apart


def test_two_stream_clients_share_one_snapshot(remote, monkeypatch):
    port, _ = remote
    calls = []
    monkeypatch.setattr(CommandHandler, "snapshot", staticmethod(lambda: calls.append(1) or {"tick": 1}))
    monkeypatch.setattr(command_server, "snapshot_cache", SnapshotCache())
    socks = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(2)]
    try:
        for sock in socks:
            sock.sendall(ws_upgrade("/stream?interval=100", port))
            ws_response(sock)
        for sock in socks:
            ws_read(sock)  # first message of each
        calls.clear()
        time.sleep(0.55)
        # Two clients at 100 ms: about 5 ticks each, one snapshot per tick (was one per client per tick: 11 or
        # more). A slow runner lets the two loops drift into different ticks now and then.
        assert 3 <= len(calls) <= 10, len(calls)
    finally:
        for sock in socks:
            sock.close()


def test_chatty_client_never_spins_the_stream_loop(remote, monkeypatch):
    port, _ = remote
    calls = []
    monkeypatch.setattr(CommandHandler, "snapshot", staticmethod(lambda: calls.append(1) or {"tick": 1}))
    monkeypatch.setattr(command_server, "snapshot_cache", SnapshotCache())
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    with sock:
        sock.sendall(ws_upgrade("/stream?interval=100", port))
        ws_response(sock)
        ws_read(sock)
        calls.clear()
        start = time.monotonic()
        for _ in range(50):
            sock.sendall(ws_frame(command_server.WS_OP_PING, b"x"))
        pongs = 0
        while pongs < 50 and time.monotonic() - start < 5:
            if ws_read(sock)[0] == command_server.WS_OP_PONG:
                pongs += 1
        elapsed = time.monotonic() - start
        assert pongs == 50
        # Frames answered within the interval, snapshot only at each deadline (was once per frame: 50+)
        assert len(calls) <= elapsed / 0.1 + 3, (len(calls), elapsed)


# --- PERF-027: server made on the port of one still closing never holds the GUI thread
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass


def test_stop_wakes_serving_loop_at_once():
    server = LocalHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)  # loop waiting in select (poll interval 0.5 s)
    server.stop()
    assert server.closed.wait(0.3)  # was up to SERVE_POLL_INTERVAL
    thread.join(1)
    assert not thread.is_alive()


def test_port_still_closing_raises_instead_of_waiting(monkeypatch):
    monkeypatch.setattr(command_server, "CLOSING_WAIT_SECONDS", 0.05)
    port = free_port()
    never = threading.Event()
    with LocalHTTPServer._closing_lock:
        LocalHTTPServer._closing[port] = never
    try:
        start = time.monotonic()
        with pytest.raises(PortClosing) as error:
            LocalHTTPServer(("127.0.0.1", port), Handler)
        assert time.monotonic() - start < 0.5 and isinstance(error.value, OSError)
    finally:
        with LocalHTTPServer._closing_lock:
            LocalHTTPServer._closing.pop(port, None)


def test_bind_retry_tries_again_soon_without_report_while_port_closing(monkeypatch):
    monkeypatch.setattr(command_server, "CLOSING_RETRY_MS", 20)
    errors = []
    starts = []
    app_signal.error.connect(errors.append)
    retry = BindRetry("Test", lambda: starts.append(1))
    try:
        retry.failed(("127.0.0.1", 1234), PortClosing(1234))
        assert not retry.failing and not errors  # normal while a setting changes: nothing reported
        process_events(0.2)
        assert starts == [1]  # listening tried again soon
        retry.failed(("127.0.0.1", 1234), OSError(98, "in use"))
        assert retry.failing and len(errors) == 1  # a real failure still reported
    finally:
        retry.stop()
        app_signal.error.disconnect(errors.append)


def test_server_turned_off_and_on_listens_again_at_once(monkeypatch):
    """Same port stopped & started by the GUI: previous socket closed within milliseconds, new server listening"""
    cfg.default.set_default()
    config = copy_setting(cfg.default.config)
    config["remote_control"].update(enable_remote_control=True, remote_control_port=free_port())
    monkeypatch.setattr(cfg.user, "config", config, raising=False)
    control = CommandServer()
    try:
        control.enable()
        start = time.monotonic()
        control.disable()
        control.enable()
        assert control.running and time.monotonic() - start < 0.4
    finally:
        control.disable()


# --- BUG-026: route parser failure: same body never parsed again, log never flooded
def test_route_parser_failure_logged_once_and_body_not_parsed_again(monkeypatch, caplog):
    from neopedal import game_rest_poll
    from neopedal.game_rest_poll import RoutePoller
    from neopedal.log_handler import ErrorThrottle

    monkeypatch.setattr(game_rest_poll, "parse_errors", ErrorThrottle())
    parsed = []

    def parse(data):
        parsed.append(data)
        if data.get("bad"):
            raise KeyError("missing")
        return data

    answers = [(200, b'{"bad": 1}'), (200, b'{"bad": 1}'), (200, b'{"bad": 1}'), (200, b'{"ok": 1}')]
    poller = RoutePoller("/rest/x", parse, {"empty": True}, 10.0, lambda: answers.pop(0))
    caplog.set_level(logging.DEBUG, logger=game_rest_poll.logger.name)
    for _ in range(3):
        poller.check()  # never raises to the poll worker
    assert parsed == [{"bad": 1}] and poller.value == {"empty": True}  # same body parsed once, value kept
    levels = [record.levelno for record in caplog.records if "parse failed" in record.getMessage()]
    assert levels == [logging.WARNING]
    poller.check()
    assert poller.value == {"ok": 1}


# --- BUG-027: rest cache full: a route being asked is never dropped (no second identical request)
def test_rest_cache_eviction_keeps_pending_route(monkeypatch):
    from neopedal import game_rest_cache
    from neopedal.game_rest_cache import GameRestCache

    monkeypatch.setattr(game_rest_cache, "MAX_ROUTES", 2)
    address = ("localhost", 6397)
    release = threading.Event()
    asked = []

    def fetch(_address, route, _timeout):
        asked.append(route)
        if route == "/slow":
            assert release.wait(5)
        return 200, b"{}"

    clock = [100.0]
    cache = GameRestCache(fetch, lambda: clock[0])
    thread = threading.Thread(target=cache.answer, args=("/slow", 1.0, address), daemon=True)
    thread.start()
    while asked != ["/slow"]:
        time.sleep(0.005)
    pending = cache._routes[(address, "/slow")]
    clock[0] += 0.1
    cache.answer("/old", 1.0, address)
    clock[0] += 0.1
    cache.answer("/new", 1.0, address)  # full: oldest idle route dropped, the pending one kept
    assert (address, "/old") not in cache._routes and cache._routes[(address, "/slow")] is pending
    waiter = threading.Thread(target=cache.answer, args=("/slow", 1.0, address), daemon=True)
    waiter.start()
    time.sleep(0.05)
    release.set()
    thread.join(2)
    waiter.join(2)
    assert asked.count("/slow") == 1  # second caller waited for the first request


# --- BUG-053: a command is never sent twice after the game closed the connection
class ScriptedConnection:
    """http.client.HTTPConnection fake: request() & getresponse() behaviour scripted per connection"""

    script: list[tuple[str, str]] = []  # (on request, on response): "ok" or "disconnect"
    made: list[str] = []
    sent: list[tuple[str, str]] = []

    def __init__(self, host, port, timeout=None):
        self.step = self.script.pop(0)
        self.made.append(host)
        self.response_class = None

    def request(self, method, resource, body=None, headers=None):
        if self.step[0] == "disconnect":
            raise BrokenPipeError("closed")
        self.sent.append((method, resource))

    def getresponse(self):
        if self.step[1] == "disconnect":
            raise http.client.RemoteDisconnected("closed")
        return types.SimpleNamespace(status=200, length=2, read=lambda size=-1: b"{}", will_close=False)

    def close(self):
        pass


@pytest.fixture
def scripted(monkeypatch):
    from neopedal import game_rest

    monkeypatch.setattr(game_rest.http.client, "HTTPConnection", ScriptedConnection)
    monkeypatch.setattr(game_rest, "resolve_hostname", lambda host, port, timeout: host)
    monkeypatch.setattr(game_rest, "read_body", lambda read, max_body, length: read())
    ScriptedConnection.made, ScriptedConnection.sent = [], []
    return game_rest


def test_get_sent_again_after_remote_disconnect(scripted):
    ScriptedConnection.script = [("ok", "disconnect"), ("ok", "ok")]
    connection = scripted.GameConnection(address=("localhost", 6397))
    assert connection.request("GET", "/rest/a") == (200, b"{}")
    assert [method for method, _ in ScriptedConnection.sent] == ["GET", "GET"]


def test_post_not_sent_again_after_remote_disconnect(scripted):
    ScriptedConnection.script = [("ok", "disconnect"), ("ok", "ok")]
    connection = scripted.GameConnection(address=("localhost", 6397))
    assert connection.request("POST", "/rest/garage/PitMenu", "[]") == (0, b"")  # failed: caller decides
    assert ScriptedConnection.sent == [("POST", "/rest/garage/PitMenu")]  # once: game may have acted


def test_post_sent_again_when_kept_connection_refused_the_send(scripted):
    ScriptedConnection.script = [("ok", "ok"), ("ok", "ok")]
    connection = scripted.GameConnection(address=("localhost", 6397))
    assert connection.request("GET", "/rest/a")[0] == 200
    connection.connection.step = ("disconnect", "ok")  # game closed the kept connection meanwhile
    assert connection.request("POST", "/rest/b", "{}") == (200, b"{}")  # nothing written: new connection
    assert ScriptedConnection.sent == [("GET", "/rest/a"), ("POST", "/rest/b")]


# --- PERF-029: game not running: unresolved host kept for its hold, warning once a period
def test_forget_hostname_keeps_unresolved_entry(monkeypatch):
    from neopedal import async_request
    from neopedal.async_request import clear_resolved_hosts, forget_hostname, resolve_hostname

    probes = []

    async def probe(hostnames, port, timeout=3):
        probes.append(1)
        return ""

    monkeypatch.setattr(async_request, "localhost_resolve", probe)
    clear_resolved_hosts()
    try:
        assert resolve_hostname("localhost", 6397, 1) == "localhost" and len(probes) == 1
        forget_hostname("localhost", 6397)  # connection refused: only tells again the game is not running
        assert resolve_hostname("localhost", 6397, 1) == "localhost" and len(probes) == 1  # not probed again
        async_request._store_hostname("localhost", 6397, "127.0.0.1")
        forget_hostname("localhost", 6397)  # resolved address dropped: probed again
        resolve_hostname("localhost", 6397, 1)
        assert len(probes) == 2
    finally:
        clear_resolved_hosts()


def test_unresolved_hostname_warned_once_a_period(monkeypatch, caplog):
    from neopedal import async_request
    from neopedal.log_handler import ErrorThrottle

    monkeypatch.setattr(async_request, "_unresolved_warning", ErrorThrottle(60.0))
    caplog.set_level(logging.DEBUG, logger=async_request.logger.name)
    port = free_port()  # nothing listens
    for _ in range(3):
        assert asyncio.run(async_request.localhost_resolve({"127.0.0.1"}, port, 1.0)) == ""
    levels = [record.levelno for record in caplog.records if "unable to resolve" in record.getMessage()]
    assert levels == [logging.WARNING, logging.DEBUG, logging.DEBUG]


# --- PERF-060: ranks file read on a lane of its own
def test_file_read_runs_on_file_lane():
    from neopedal.game_rest_poll import FileRead, PollWorker

    worker = PollWorker(size=1, name="Lane test", file_lane=True)
    names = {}
    done = threading.Event()
    def file_read():
        names["file"] = threading.current_thread().name
        done.set()

    worker.submit(lambda: names.setdefault("route", threading.current_thread().name))
    worker.submit(FileRead(file_read))
    assert done.wait(5)
    deadline = time.monotonic() + 5
    while "route" not in names and time.monotonic() < deadline:
        time.sleep(0.01)
    assert names["route"] == "Lane test" and names["file"] == "Lane test (files)"


def test_rank_watcher_reads_on_file_lane(monkeypatch):
    from neopedal import game_rest_poll
    from neopedal.process import driver_ranks as dr

    assert game_rest_poll.poll_worker.files is not None
    submitted = []
    monkeypatch.setattr(game_rest_poll.poll_worker, "submit", submitted.append)
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()), clock=lambda: 50.0)
    watcher.poll()
    assert len(submitted) == 1 and isinstance(submitted[0], game_rest_poll.FileRead)
    submitted[0]()
    assert not watcher._busy


# --- BUG-028 / PERF-030: private key accessible by this user only, no disk flush on the GUI thread
def test_private_key_access_restricted(tmp_path, monkeypatch):
    from neopedal import vr_shared

    restricted = []
    monkeypatch.setattr(vr_shared, "restrict_to_user", lambda path, mode=0o700: restricted.append((path, mode)))
    monkeypatch.setattr(os, "fsync", lambda fd: pytest.fail("fsync on a regenerable file"))
    cert_file, key_file = tls_cert.cert_paths(str(tmp_path))
    tls_cert.create_certificate(cert_file, key_file, ["127.0.0.1"])
    assert restricted == [(f"{key_file}.tmp", 0o600)]  # set before the rename (kept by it), never on the cert
    assert os.path.exists(key_file) and os.path.exists(cert_file)


def test_private_key_restriction_failure_not_fatal(tmp_path, monkeypatch, caplog):
    from neopedal import vr_shared

    def failing(path, mode=0o700):
        raise PermissionError("no ACL here")

    monkeypatch.setattr(vr_shared, "restrict_to_user", failing)
    caplog.set_level(logging.WARNING, logger=tls_cert.logger.name)
    tls_cert.server_context(str(tmp_path), [])  # certificate made & loaded anyway
    assert any("not restricted" in record.getMessage() for record in caplog.records)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DACL")
def test_restrict_to_user_works_on_a_file(tmp_path):
    from neopedal.vr_shared import restrict_to_user

    path = tmp_path / "key.pem"
    path.write_bytes(b"secret")
    restrict_to_user(str(path), 0o600)  # was documented for folders only
    assert path.read_bytes() == b"secret"  # still ours


# --- PERF-067: fingerprint read & parsed once per certificate file
def test_fingerprint_cached_by_certificate_file(tmp_path, monkeypatch):
    from cryptography import x509

    folder = str(tmp_path)
    tls_cert.server_context(folder, [])
    loads = []
    real = x509.load_pem_x509_certificate
    monkeypatch.setattr(x509, "load_pem_x509_certificate", lambda data, *args: loads.append(1) or real(data, *args))
    first = tls_cert.fingerprint(folder)
    assert len(first.split(":")) == 32 and len(loads) == 1
    assert tls_cert.fingerprint(folder) == first and len(loads) == 1  # not read again
    tls_cert.server_context(folder, ["192.0.2.10"])  # new certificate (covers() reads the old one: counted)
    before = len(loads)
    assert tls_cert.fingerprint(folder) != first and len(loads) == before + 1
    assert tls_cert.fingerprint(str(tmp_path / "none")) == ""


# --- BUG-045: certificate update replaces the listening socket's context, the served one is never changed
def test_certificate_update_replaces_listening_context(ui_env, monkeypatch):
    from neopedal import web_dashboard
    from neopedal.web_dashboard import DashboardHandler, WebDashboard

    known = ["192.0.2.10"]
    monkeypatch.setattr(web_dashboard, "local_addresses", lambda max_age=0, wait=False: list(known))
    port = free_port()
    cfg.user.config["web_dashboard"].update(
        enable_web_dashboard=True, web_dashboard_port=port, access_code="TESTCODE",
        enable_https=True, enable_lan_access=True)
    server = WebDashboard()
    try:
        server.enable()
        listening = server._server.socket
        old = listening.context
        assert isinstance(listening, ssl.SSLSocket) and server._context is old
        known.append("192.0.2.11")
        server.update_certificate(server._server)  # as the background thread does
        new = listening.context
        assert new is not old and server._context is new  # old context untouched, kept by its connections
        context = ssl.create_default_context(cafile=tls_cert.cert_paths(cfg.path.config)[0])
        connection = http.client.HTTPSConnection("192.0.2.11", port, context=context, timeout=5)
        connection.sock = context.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=5),
                                              server_hostname="192.0.2.11")
        connection.request("GET", "/api/telemetry", headers={"X-Access-Code": "TESTCODE"})
        assert connection.getresponse().status == 200  # accepted with the new context
        connection.close()
        server.update_certificate(server._server)  # same addresses: context made again, server kept
        assert server.running
    finally:
        server.disable()
        DashboardHandler.secure = False


# --- PERF-031: results folders listed & candidates stat'ed again only once a folder changed
def test_results_scan_cached_while_folders_unchanged(ui_env, tmp_path, monkeypatch):
    from neopedal import i18n, stream_overlay
    from neopedal.process import results_file as rf

    i18n.set_language("English")
    folder = tmp_path / "Results"
    folder.mkdir()
    xml = (
        '<?xml version="1.0"?><rFactorXML version="1.0"><RaceResults><TrackVenue>Monza</TrackVenue>'
        '<TrackCourse>Monza</TrackCourse><TrackEvent>Monza</TrackEvent><Race><MostLapsCompleted>2'
        '</MostLapsCompleted><Driver><Name>Alice</Name><VehName>Car</VehName><CarClass>GT3</CarClass>'
        '<CarNumber>1</CarNumber><Position>1</Position><ClassPosition>1</ClassPosition><LapsCompleted>2'
        '</LapsCompleted><BestLapTime>100.0</BestLapTime><FinishStatus>Finished Normally</FinishStatus>'
        '<Lap num="1" et="10" fuel="0.5">100.0</Lap><Lap num="2" et="110" fuel="0.4">100.0</Lap>'
        '</Driver></Race></RaceResults></rFactorXML>'
    )
    (folder / "2026_09_21_20_00_00-12R1.xml").write_text(xml, encoding="utf-8")
    old = time.time() - 60
    os.utime(folder, (old, old))  # folder settled (not changed lately)
    with open(os.path.join(cfg.path.config, rf.PAGE_SETTINGS_FILE), "w", encoding="utf-8") as file:
        json.dump({"folder": str(folder)}, file)
    listings = []
    real = rf.results_files
    monkeypatch.setattr(rf, "results_files", lambda path: listings.append(path) or real(path))
    stats = []
    real_stat = os.stat
    monkeypatch.setattr(os, "stat", lambda path, *args, **kwargs: stats.append(str(path)) or real_stat(
        path, *args, **kwargs))
    cache = stream_overlay.ResultsCache()
    first = stream_overlay.results_snapshot(cache, "race")
    assert first["available"] and first["title"] == "Monza" and len(listings) == 1
    stats.clear()
    assert stream_overlay.results_snapshot(cache, "race") is first  # page data built once per result
    assert len(listings) == 1  # folder unchanged: not listed again
    assert [path for path in stats if path.endswith(".xml")] == [str(folder / "2026_09_21_20_00_00-12R1.xml")]
    # New results file: folder changed, listed again, newer result found
    (folder / "2026_09_21_21_00_00-12R1.xml").write_text(xml.replace("Monza", "Spa"), encoding="utf-8")
    os.utime(folder, (old + 1, old + 1))
    second = stream_overlay.results_snapshot(cache, "race")
    assert second["title"] == "Spa" and len(listings) == 2


# --- PERF-059: SteamVR init & overlay creation off the GUI thread, adopted by it
class FakeIVROverlay:
    def __init__(self, log):
        self.log = log

    def createOverlay(self, key, name):
        self.log.append(("createOverlay", threading.current_thread().name))
        return 42

    def setOverlayWidthInMeters(self, handle, width):
        self.log.append(("setOverlayWidthInMeters", handle, width))

    def setOverlayTransformAbsolute(self, handle, origin, matrix):
        self.log.append(("setOverlayTransformAbsolute", handle))

    def setOverlayTransformTrackedDeviceRelative(self, handle, device, matrix):
        self.log.append(("setOverlayTransformTrackedDeviceRelative", handle))

    def showOverlay(self, handle):
        self.log.append(("showOverlay", handle))

    def hideOverlay(self, handle):
        self.log.append(("hideOverlay", handle))

    def destroyOverlay(self, handle):
        self.log.append(("destroyOverlay", handle))


class HmdMatrix34_t:
    def __init__(self):
        self.m = [[0.0] * 4 for _ in range(3)]


def fake_openvr(log, gate: threading.Event | None = None):
    module = types.ModuleType("openvr")
    module.VRApplication_Overlay = 2
    module.TrackingUniverseSeated = 0
    module.k_unTrackedDeviceIndex_Hmd = 0
    module.HmdMatrix34_t = HmdMatrix34_t

    def init(app_type):
        if gate is not None:
            assert gate.wait(5)
        log.append(("init", threading.current_thread().name))
        return object()

    module.init = init
    module.shutdown = lambda: log.append(("shutdown",))
    module.IVROverlay = lambda: FakeIVROverlay(log)
    return module


VR_SETTING = {"overlay_width_meters": 0.8, "distance_meters": 1.0, "vertical_offset_meters": -0.2,
              "horizontal_offset_meters": 0.0, "enable_attach_to_headset": False}


def test_steamvr_start_runs_off_the_calling_thread(monkeypatch):
    from neopedal.vr_overlay import SteamVRStart

    log = []
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log))
    start = SteamVRStart(VR_SETTING)
    assert start.wait(5)
    result = start.take()
    assert result is not None and result[3] == 42 and start.take() is None
    assert log[0] == ("init", "SteamVR start") and log[1] == ("createOverlay", "SteamVR start")
    assert log[-1] == ("showOverlay", 42)


def test_steamvr_start_dropped_before_done_is_released_by_its_thread(monkeypatch):
    from neopedal.vr_overlay import SteamVRStart

    log = []
    gate = threading.Event()
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log, gate))
    start = SteamVRStart(VR_SETTING)
    assert not start.done()
    start.drop()  # disabled while SteamVR still starting
    gate.set()
    assert start.wait(5) and start.take() is None
    assert log[-2:] == [("destroyOverlay", 42), ("shutdown",)]  # overlay never left behind in SteamVR


def test_steamvr_start_failure_released(monkeypatch):
    from neopedal.vr_overlay import SteamVRStart

    log = []
    module = fake_openvr(log)

    def failing(app_type):
        log.append(("init", "fail"))
        raise RuntimeError("SteamVR closing")

    module.init = failing
    monkeypatch.setitem(sys.modules, "openvr", module)
    start = SteamVRStart(VR_SETTING)
    assert start.wait(5) and start.take() is None and isinstance(start.error, RuntimeError)
    assert log == [("init", "fail")]  # nothing to shut down after a failed init


def test_vr_overlay_adopts_background_start_on_gui_thread(ui_env, monkeypatch):
    from neopedal import vr_overlay
    from neopedal.vr_overlay import VROverlay

    class SyncCheck:
        running = True

        def done(self):
            return True

    monkeypatch.setattr(vr_overlay, "SteamVRCheck", SyncCheck)
    monkeypatch.setattr(vr_overlay, "STEAMVR_START_WAIT_S", 0.0)  # slow SteamVR: adopted on a later tick
    log = []
    gate = threading.Event()
    monkeypatch.setitem(sys.modules, "openvr", fake_openvr(log, gate))
    cfg.user.config["vr_overlay"].update(enable_vr_overlay=True, enable_vr_mirror_window=False)
    control = VROverlay()
    try:
        control.enable()
        assert control.running and control._handle is None and control._steamvr_start is not None
        control.update_overlay()  # still starting: nothing adopted, no second start
        assert control._handle is None and log == []
        gate.set()
        assert control._steamvr_start.wait(5)
        control.update_overlay()  # GUI tick: overlay adopted
        assert control._handle == 42 and control._steamvr_start is None
        assert log[0] == ("init", "SteamVR start")
    finally:
        control.disable()
    assert log[-2:] == [("destroyOverlay", 42), ("shutdown",)]
