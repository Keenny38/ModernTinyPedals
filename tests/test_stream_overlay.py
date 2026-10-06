"""Stream overlays: frames store & capture, browser sources server, stream only overlays, stream overlays page"""

import json
import os
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget
from test_race_results import PRACTICE_XML, RACE_NAME, RACE_XML, write_results

from tinypedal import stream_overlay
from tinypedal.process import results_file as rf
from tinypedal.stream_overlay import FrameStore, OverlayCapture, Placement


def image(width=40, height=20, color="#80ff0000") -> QImage:
    picture = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    picture.fill(QColor(color))
    return picture


def parse_bundle(data: bytes) -> tuple[dict, list[bytes]]:
    length = struct.unpack(">I", data[:4])[0]
    head = json.loads(data[4:4 + length])
    offset = 4 + length
    payloads = []
    for entry in head["overlays"]:
        payloads.append(data[offset:offset + entry["size"]])
        offset += entry["size"]
    assert offset == len(data)
    return head, payloads


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def process_events(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


# Frames
def test_store_bundle():
    store = FrameStore()
    head, payloads = parse_bundle(store.bundle("layout", 0, "zraw", timeout=0.01))  # nothing captured yet
    assert head == {"seq": 0, "canvas": [0, 0], "overlays": []} and payloads == []
    store.publish({"gear": image(), "fuel": image(10, 10, "#ff00ff00")},
                  [Placement("gear", 5, 6, 0.9), Placement("fuel", 100, 50, 1.0)], (1920, 1080))
    head, payloads = parse_bundle(store.bundle("layout", 0, "zraw"))
    assert head["seq"] == 1 and head["canvas"] == [1920, 1080]
    assert [(entry["name"], entry["x"], entry["y"], entry["w"], entry["h"], entry["opacity"]) for entry in head["overlays"]] == [
        ("gear", 5, 6, 40, 20, 0.9), ("fuel", 100, 50, 10, 10, 1.0)]
    pixels = zlib.decompress(payloads[0])
    assert len(pixels) == 40 * 20 * 4
    assert tuple(pixels[:4]) == (255, 0, 0, 128)  # RGBA, not premultiplied
    # One overlay, PNG
    head, payloads = parse_bundle(store.bundle("fuel", 0, "png"))
    assert [entry["name"] for entry in head["overlays"]] == ["fuel"] and payloads[0].startswith(b"\x89PNG")
    # Nothing new: request waits, then unchanged images have no data
    started = time.monotonic()
    head, payloads = parse_bundle(store.bundle("layout", 1, "zraw", timeout=0.2))
    assert time.monotonic() - started >= 0.15
    assert [entry["size"] for entry in head["overlays"]] == [0, 0]
    # Only changed image sent, overlay gone removed
    store.publish({"gear": image(40, 20, "#ff0000ff")}, [Placement("gear", 5, 6, 0.9)], (1920, 1080))
    head, payloads = parse_bundle(store.bundle("layout", 1, "zraw"))
    assert [entry["name"] for entry in head["overlays"]] == ["gear"] and head["overlays"][0]["size"] > 0
    # Same state again: no new frame
    seq = store.seq
    store.publish({}, [Placement("gear", 5, 6, 0.9)], (1920, 1080))
    assert store.seq == seq
    # Moved: new frame without image data
    store.publish({}, [Placement("gear", 7, 6, 0.9)], (1920, 1080))
    head, payloads = parse_bundle(store.bundle("layout", seq, "zraw"))
    assert head["overlays"][0]["x"] == 7 and head["overlays"][0]["size"] == 0
    # Client of a server started before: everything sent again
    head, payloads = parse_bundle(store.bundle("layout", 999, "zraw"))
    assert head["overlays"][0]["size"] > 0
    store.clear()
    head, _ = parse_bundle(store.bundle("layout", 0, "zraw"))
    assert head["overlays"] == []


def test_store_watched(monkeypatch):
    store = FrameStore()
    assert store.watched() == set()
    store.touch("layout")
    store.touch("gear")
    assert store.watched() == {"layout", "gear"}
    store.publish({"fuel": image()}, [Placement("fuel", 0, 0, 1.0)], (100, 100))
    assert store.watched_overlays() == {"layout", "gear", "fuel"}
    now = time.monotonic()
    monkeypatch.setattr(stream_overlay.time, "monotonic", lambda: now + stream_overlay.WATCH_SECONDS + 1)
    assert store.watched() == set()
    for number in range(stream_overlay.MAX_VIEWS + 5):  # bounded
        store.touch(f"view{number}")
    assert len(store._requests) == stream_overlay.MAX_VIEWS


def test_visibility_choices():
    assert stream_overlay.stream_visibility({"stream_visibility": "Stream Only"}) == "Stream Only"
    assert stream_overlay.stream_visibility({"stream_visibility": "bogus"}) == "Screen & Stream"
    assert stream_overlay.stream_visibility(None) == "Screen & Stream"
    assert not stream_overlay.shown_on_stream({"stream_visibility": "Screen Only"})
    assert stream_overlay.stream_only({"stream_visibility": "Stream Only"})


class FakeOverlay(QWidget):
    """Overlay window: widget name & options, painted color"""

    def __init__(self, name: str, visibility: str, color: str = "#c0ff8000"):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.widget_name = name
        self.wcfg = {"stream_visibility": visibility, "opacity": 0.8}
        self.color = QColor(color)
        self.resize(60, 30)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.color)


def test_capture(monkeypatch):
    shown = FakeOverlay("gear", "Screen & Stream")
    only = FakeOverlay("fuel", "Stream Only")
    hidden = FakeOverlay("radar", "Screen Only")
    for overlay in (shown, only, hidden):
        overlay.move(10, 10)
        overlay.show()
    shown.setWindowOpacity(0.5)
    only.setWindowOpacity(0.0)
    process_events(0.1)
    store = FrameStore()
    capture = OverlayCapture(store)
    try:
        capture.capture()  # nobody watching: nothing captured
        assert store.seq == 0
        store.touch("gear")
        capture.capture()
        head, payloads = parse_bundle(store.bundle("layout", 0, "zraw"))
        assert [entry["name"] for entry in head["overlays"]] == ["gear"]  # only overlay watched
        assert head["overlays"][0]["opacity"] == pytest.approx(0.5, abs=0.01)  # window opacity (fading)
        store.touch("layout")
        capture.capture()
        head, payloads = parse_bundle(store.bundle("layout", 0, "zraw"))
        entries = {entry["name"]: entry for entry in head["overlays"]}
        assert set(entries) == {"gear", "fuel"}  # screen only overlay never on stream
        assert entries["fuel"]["opacity"] == 0.8  # stream only: overlay opacity, window transparent on screen
        pixels = zlib.decompress(payloads[list(entries).index("fuel")])
        assert len(pixels) == entries["fuel"]["w"] * entries["fuel"]["h"] * 4
        # Painted premultiplied: back to straight alpha, 128 * 192 / 255 rounds to 127 or 128 by Qt version
        assert tuple(pixels[:4]) == pytest.approx((255, 128, 0, 192), abs=1)
        # Unchanged images not sent again
        seq = store.seq
        capture.capture()
        assert store.seq == seq
        only.color = QColor("#ff0000ff")
        only.update()
        process_events(0.1)
        capture.capture()
        head, _ = parse_bundle(store.bundle("layout", seq, "zraw"))
        assert {entry["name"]: entry["size"] > 0 for entry in head["overlays"]} == {"gear": False, "fuel": True}
        # Overlay hidden (auto hide): removed from stream
        shown.hide()
        capture.capture()
        head, _ = parse_bundle(store.bundle("layout", 0, "zraw"))
        assert [entry["name"] for entry in head["overlays"]] == ["fuel"]
        # Nobody watching any more: images dropped
        now = time.monotonic()
        monkeypatch.setattr(stream_overlay.time, "monotonic", lambda: now + stream_overlay.WATCH_SECONDS + 1)
        capture.capture()
        head, _ = parse_bundle(store.bundle("layout", 0, "zraw", timeout=0.01))
        assert head["overlays"] == []
    finally:
        capture.stop()
        for overlay in (shown, only, hidden):
            overlay.close()
            overlay.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_window_image_fallback_renders_widget():
    overlay = FakeOverlay("gear", "Screen & Stream")
    try:
        picture = stream_overlay.window_image(overlay)  # never shown: no backing store
        assert picture is not None and picture.width() >= 60
        assert picture.pixelColor(5, 5).alpha() == 192
    finally:
        overlay.deleteLater()


# Overlay window opacity
def test_stream_only_overlay_transparent_on_screen(ui_env, monkeypatch):
    from importlib import import_module

    from tinypedal import realtime_state
    from tinypedal.setting import cfg
    from tinypedal.widget._modern import create_widget

    monkeypatch.setattr(realtime_state, "active", True)
    cfg.overlay["auto_hide"] = False
    cfg.overlay["fixed_position"] = True
    cfg.user.setting["gear"]["stream_visibility"] = "Stream Only"
    widget = create_widget(import_module("tinypedal.widget.gear"), cfg, "gear")
    try:
        widget.start()
        assert widget.screen_opacity() == 0.0
        assert widget.windowOpacity() == 0.0
        widget._Base__refresh_visibility()  # fade in: shown, still transparent (never hidden by fade end)
        process_events(0.4)
        assert widget.isVisible() and widget.windowOpacity() == 0.0
        cfg.overlay["fixed_position"] = False  # unlocked: visible to move it
        assert widget.screen_opacity() == pytest.approx(widget.wcfg["opacity"])
        cfg.user.setting["gear"]["stream_visibility"] = "Screen & Stream"
    finally:
        cfg.overlay["fixed_position"] = True
        widget.stop()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# Race results source
def test_results_snapshot(ui_env, tmp_path, monkeypatch):
    from tinypedal import i18n
    from tinypedal.setting import cfg

    i18n.set_language("English")
    folder = tmp_path / "Results"
    write_results(folder, {
        RACE_NAME: RACE_XML,
        "2026_09_21_20_00_00-12R1.xml": PRACTICE_XML.replace("Practice1", "Race").format(laps=0),  # newer, no lap
        "2026_09_21_21_00_00-12P1.xml": PRACTICE_XML.format(laps=3),
    })
    with open(os.path.join(cfg.path.config, rf.PAGE_SETTINGS_FILE), "w", encoding="utf-8") as file:
        json.dump({"folder": str(folder)}, file)
    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {})
    cache = stream_overlay.ResultsCache()
    data = stream_overlay.results_snapshot(cache, "race")
    assert data["available"] and data["title"] == "24 Heures du Mans" and data["race"]  # race without lap skipped
    assert [row["driver"] for row in data["rows"]] == ["Alice Driver", "Bob Racer", "Carl Slow"]
    alice, bob, carl = data["rows"]
    assert (alice["gap"], bob["gap"], carl["gap"], carl["gapTone"]) == ("4:57.800", "+4.700", "DNF", "loss")
    assert alice["fastest"] and alice["classFastest"] and carl["classFastest"] and not carl["fastest"]
    assert (carl["classPos"], carl["classGap"]) == (1, "DNF")
    assert [item["name"] for item in data["classes"]] == ["Hyper", "GT3"]
    assert data["labels"]["best"] == "Best Lap"
    assert cache.latest("race") is cache.latest("race")  # file read once
    practice = stream_overlay.results_snapshot(cache, "any")
    assert practice["title"] == "Monza" and not practice["race"]
    assert stream_overlay.results_snapshot(cache, "qualifying") == {"available": False, "labels": data["labels"]}


# Server
@pytest.fixture
def server(ui_env, monkeypatch):
    from tinypedal.setting import cfg

    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {})
    port = free_port()
    cfg.user.config["stream_overlay"].update({
        "enable_stream_overlay": True, "stream_overlay_port": port, "access_token": "", "enable_lan_access": False})
    cfg.user.setting["gear"]["enable"] = True
    cfg.user.setting["radar"]["enable"] = True
    cfg.user.setting["radar"]["stream_visibility"] = "Screen Only"
    control = stream_overlay.StreamOverlay()
    control.enable()
    assert control.running
    yield control
    control.disable()
    assert not control.running


def get(url: str) -> tuple[int, bytes, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def test_server_routes(server):
    token = server.access_token()
    assert len(token) >= 16  # generated & saved
    base = server.base_urls()[0]
    status, body, headers = get(f"{base}/layout")
    assert status == 403
    status, body, _ = get(f"{base}/layout?token=wrong")
    assert status == 403
    status, body, headers = get(server.url("/layout"))
    assert status == 200 and b'const VIEW="layout"' in body
    assert headers["Referrer-Policy"] == "no-referrer" and "connect-src 'self'" in headers["Content-Security-Policy"]
    status, body, _ = get(server.url("/overlay/gear"))
    assert status == 200 and b'const VIEW="gear"' in body
    assert get(server.url("/overlay/../config"))[0] == 404
    status, body, _ = get(server.url("/"))
    assert b"/overlay/gear?token=" in body and b"/overlay/radar" not in body  # screen only overlay not listed
    status, body, _ = get(server.url("/api/frames", "view=gear&seq=0"))
    head, _ = parse_bundle(body)
    assert status == 200 and head["overlays"] == []
    assert "gear" in server.watched()
    assert get(server.url("/api/frames", "view=../x"))[0] == 400
    status, body, _ = get(server.url("/api/results"))
    assert status == 200 and json.loads(body)["available"] is False
    status, body, _ = get(server.url("/results"))
    assert status == 200 and b"/api/results" in body
    assert get(server.url("/nothing"))[0] == 404
    status, body, headers = get(f"{base}/fonts/BarlowSemiCondensed-Bold.ttf")  # no token needed
    assert status == 200 and headers["Content-Type"] == "font/ttf" and len(body) > 1000
    assert get(f"{base}/fonts/..%2Fconfig.json")[0] == 404
    # New token: old addresses refused
    old = server.url("/layout")
    server.new_access_token()
    assert get(old)[0] == 403
    assert get(server.url("/layout"))[0] == 200


def test_server_settings_change(server):
    from tinypedal.setting import cfg

    old_base = server.base_urls()[0]
    port = free_port()
    cfg.user.config["stream_overlay"]["stream_overlay_port"] = port
    server.enable()  # new address: server started again there
    assert server.running and server.base_urls()[0].endswith(f":{port}")
    assert get(server.url("/layout"))[0] == 200
    with pytest.raises(OSError):
        urllib.request.urlopen(f"{old_base}/layout", timeout=2)
    cfg.user.config["stream_overlay"]["enable_stream_overlay"] = False
    server.enable()
    assert not server.running


def test_disable_closes_open_connections(server):
    """Keep-alive client (OBS) stops receiving frames once server is stopped"""
    import http.client
    from urllib.parse import urlsplit

    url = urlsplit(server.url("/api/frames", "view=gear&seq=0"))
    connection = http.client.HTTPConnection("127.0.0.1", server.port(), timeout=5)
    try:
        connection.request("GET", f"{url.path}?{url.query}")
        response = connection.getresponse()
        response.read()
        assert response.status == 200 and not response.will_close  # connection kept open
        server.disable()
        with pytest.raises((OSError, http.client.HTTPException)):
            connection.request("GET", "/layout")
            connection.getresponse().read()
    finally:
        connection.close()


def test_port_unavailable(ui_env, monkeypatch):
    from tinypedal import app_signal
    from tinypedal.setting import cfg

    errors = []
    app_signal.error.connect(errors.append)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        cfg.user.config["stream_overlay"].update({
            "enable_stream_overlay": True, "stream_overlay_port": busy.getsockname()[1]})
        control = stream_overlay.StreamOverlay()
        control.enable()
        assert not control.running and errors
        control.disable()
    app_signal.error.disconnect(errors.append)


# Page
@pytest.fixture
def page_backend(server, monkeypatch):
    from tinypedal.ui.quick.stream_backend import StreamOverlaysBackend

    slot_errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: slot_errors.append(exc_info[1]))
    monkeypatch.setattr(stream_overlay, "streamoverlay", server)
    from tinypedal.ui.quick import stream_backend

    monkeypatch.setattr(stream_backend, "streamoverlay", server)
    backend = StreamOverlaysBackend()
    backend.page_shown()
    yield backend
    backend.release()
    backend.deleteLater()
    assert not slot_errors


def test_page_backend(page_backend, monkeypatch):
    from tinypedal import i18n
    from tinypedal.setting import cfg
    from tinypedal.widget import _base

    i18n.set_language("English")
    backend = page_backend
    assert backend.enabled and backend.running and backend.statusText == "Ready"
    rows = {row["key"]: row for row in backend.overlayModel.rows}
    assert rows["radar"]["visibility"] == 2 and rows["gear"]["visibility"] == 0
    assert "token=" in backend.layoutUrl and backend.overlayUrl("gear").endswith(
        f"/overlay/gear?token={cfg.user.config['stream_overlay']['access_token']}")
    assert "class=all&rows=15&cycle=10" in backend.resultsUrl
    backend.setResultsClass(1)
    backend.setResultsRows(0)
    backend.setResultsSession(2)
    assert "class=cycle&rows=10&cycle=10&session=any" in backend.resultsUrl
    from tinypedal.ui.quick.stream_backend import load_page_settings

    assert load_page_settings()["results_class"] == "cycle"
    reloaded = []
    monkeypatch.setattr(_base, "reload_widget", reloaded.append)
    backend.setVisibility("gear", 1)
    assert cfg.user.setting["gear"]["stream_visibility"] == "Stream Only" and reloaded == ["gear"]
    backend.setVisibility("gear", 9)  # out of range ignored
    assert cfg.user.setting["gear"]["stream_visibility"] == "Stream Only"
    backend.setFrameRate(2)
    assert cfg.user.config["stream_overlay"]["frame_rate"] == 60 and backend.frameRateIndex == 2
    old_token = cfg.user.config["stream_overlay"]["access_token"]
    backend.newToken()
    assert cfg.user.config["stream_overlay"]["access_token"] != old_token and backend.noticeText
    backend.copy(backend.layoutUrl)
    from PySide6.QtGui import QGuiApplication

    assert QGuiApplication.clipboard().text() == backend.layoutUrl
    backend.setEnabled(False)
    assert not backend.running and backend.statusText == "Server off"


def test_page_loads(page_backend):
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtQuickWidgets import QQuickWidget

    from tinypedal.ui.stream_overlay_view import StreamOverlaysView

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        view = StreamOverlaysView(None)
        view.resize(1200, 800)
        view.show()
        process_events(0.2)
        assert view.view.status() == QQuickWidget.Status.Ready, view.view.errors()
        view.resize(600, 700)
        process_events(0.1)
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


def test_server_game_pictures(server):
    from tinypedal.setting import cfg

    folder = os.path.join(cfg.path.game_image, "brand")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "Aston Martin.svg"), "wb") as file:
        file.write(b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="2"/>')
    base = server.base_urls()[0]
    assert get(f"{base}/pictures/brand/Aston%20Martin.svg")[0] == 403  # token needed
    status, body, headers = get(server.url("/pictures/brand/Aston%20Martin.svg"))
    assert status == 200 and headers["Content-Type"] == "image/svg+xml" and body.startswith(b"<svg")
    assert get(server.url("/pictures/brand/Missing.svg"))[0] == 404
    assert get(server.url("/pictures/brand/..%2F..%2Fconfig.json"))[0] == 404
    status, body, _ = get(server.url("/results"))
    assert b"/pictures/" not in body and b'id="tlogo"' in body  # logos given by results data


def test_port_out_of_range_reported(ui_env):
    """OverflowError at bind reported like a busy port, never crashes app start"""
    from tinypedal import app_signal
    from tinypedal.setting import cfg

    errors = []
    app_signal.error.connect(errors.append)
    try:
        cfg.user.config["stream_overlay"].update({"enable_stream_overlay": True, "stream_overlay_port": 70000})
        control = stream_overlay.StreamOverlay()
        control.enable()
        assert not control.running
        assert errors and "port 70000 unavailable" in errors[0]
        control.disable()
    finally:
        app_signal.error.disconnect(errors.append)
