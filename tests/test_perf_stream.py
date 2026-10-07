"""Stream & VR capture performance: LAN address cache, page signals only on change, paint serial of
overlay windows (unchanged windows not copied again), VR updates skipped while nothing painted"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from test_stream_overlay import FakeOverlay, page_backend, process_events, server  # noqa: F401

from tinypedal import stream_overlay, vr_overlay, web_dashboard
from tinypedal.stream_overlay import FrameStore, OverlayCapture


@pytest.fixture
def lookups(monkeypatch):
    """LAN address lookups counted (fake addresses)"""
    calls = []
    monkeypatch.setattr(web_dashboard, "lookup_local_addresses", lambda: calls.append(1) or ["192.168.1.20"])
    web_dashboard.clear_address_cache()
    yield calls
    web_dashboard.clear_address_cache()


def wait_address_lookup(timeout: float = 5.0):
    """Background LAN address lookup finished"""
    import time

    end = time.monotonic() + timeout
    while web_dashboard._address_refreshing and time.monotonic() < end:
        time.sleep(0.01)
    assert not web_dashboard._address_refreshing


# LAN addresses
def test_local_addresses_cached(lookups, monkeypatch):
    assert web_dashboard.local_addresses(wait=True) == ["192.168.1.20"]
    assert web_dashboard.local_addresses(wait=True) == ["192.168.1.20"]
    assert len(lookups) == 1  # second call from cache
    web_dashboard.local_addresses().append("changed")  # copy returned, cache untouched
    assert web_dashboard.local_addresses() == ["192.168.1.20"]
    assert web_dashboard.local_addresses(max_age=0, wait=True) == ["192.168.1.20"] and len(lookups) == 2  # fresh
    now = web_dashboard.time.monotonic()
    monkeypatch.setattr(web_dashboard.time, "monotonic", lambda: now + web_dashboard.ADDRESS_CACHE_SECONDS + 1)
    web_dashboard.local_addresses(wait=True)
    assert len(lookups) == 3  # expired
    web_dashboard.clear_address_cache()
    web_dashboard.local_addresses(wait=True)
    assert len(lookups) == 4


def test_local_addresses_looked_up_in_background(monkeypatch):
    """GUI thread never waits for host name lookup: last known addresses returned meanwhile,
    signal emitted once changed addresses are found"""
    import threading

    started = threading.Event()
    release = threading.Event()
    threads = []
    found = [["192.168.1.20"]]

    def slow_lookup():
        threads.append(threading.current_thread())
        started.set()
        assert release.wait(5)
        return found[0]

    signaled = []

    def on_addresses():
        signaled.append(1)

    monkeypatch.setattr(web_dashboard, "lookup_local_addresses", slow_lookup)
    web_dashboard.app_signal.addresses.connect(on_addresses)
    web_dashboard.clear_address_cache()
    try:
        assert web_dashboard.local_addresses() == []  # first lookup running: no address yet
        assert started.wait(5) and threads[0] is not threading.main_thread()
        assert web_dashboard.local_addresses() == []  # single lookup at a time
        release.set()
        wait_address_lookup()
        QCoreApplication.processEvents()
        assert web_dashboard.local_addresses() == ["192.168.1.20"] and len(threads) == 1
        assert len(signaled) == 1
        # Expired: old addresses returned while looked up again
        release.clear()
        started.clear()
        found[0] = ["10.0.0.5"]
        assert web_dashboard.local_addresses(max_age=0) == ["192.168.1.20"]
        assert started.wait(5)
        release.set()
        wait_address_lookup()
        QCoreApplication.processEvents()
        assert web_dashboard.local_addresses() == ["10.0.0.5"] and len(signaled) == 2
    finally:
        release.set()
        wait_address_lookup()
        web_dashboard.app_signal.addresses.disconnect(on_addresses)
        web_dashboard.clear_address_cache()


def test_stream_url_without_address_lookup(server, lookups):  # noqa: F811
    from tinypedal.setting import cfg

    cfg.user.config["stream_overlay"]["enable_lan_access"] = True
    try:
        url = server.url("/layout")
        assert not lookups  # this computer address: no LAN lookup
        assert url.startswith(server.base_urls()[0] + "/layout?token=")
        wait_address_lookup()  # looked up in background
        assert server.base_urls()[1:] == [f"http://192.168.1.20:{server.port()}"]
    finally:
        cfg.user.config["stream_overlay"]["enable_lan_access"] = False


def test_page_signals_server_state_only_when_changed(page_backend, server, lookups, monkeypatch):  # noqa: F811
    from tinypedal.setting import cfg

    backend = page_backend
    emitted = []
    backend.serverChanged.connect(lambda: emitted.append(1))
    backend.refresh()
    backend.refresh()
    assert not emitted  # nothing changed: QML bindings (addresses, screen) not evaluated again
    monkeypatch.setattr(server, "watched", lambda: {"layout"})
    backend.refresh()
    assert len(emitted) == 1 and backend.layoutLive
    backend.refresh()
    assert len(emitted) == 1
    cfg.user.config["stream_overlay"]["enable_lan_access"] = True  # changed elsewhere (other page)
    backend.refresh()  # addresses looked up in background
    wait_address_lookup()
    backend.refresh()  # found by next refresh (every second) at the latest
    count = len(emitted)
    assert count in (2, 3) and "192.168.1.20" in backend.lanText
    backend.refresh()
    assert len(emitted) == count and len(lookups) == 1  # addresses cached
    cfg.user.config["stream_overlay"]["enable_lan_access"] = False
    backend.page_shown()
    assert len(emitted) == count + 1  # changed (signaled once)
    backend.page_shown()
    assert len(emitted) == count + 2  # shown: always signaled


# Overlay window paint serial
def window_copies(monkeypatch, module) -> list[str]:
    """Names of overlay windows copied (module.window_image)"""
    copied = []
    original = module.window_image

    def counted(widget):
        copied.append(widget.widget_name)
        return original(widget)

    monkeypatch.setattr(module, "window_image", counted)
    return copied


def test_capture_copies_only_painted_overlays(monkeypatch):
    gear = FakeOverlay("gear", "Screen & Stream")
    fuel = FakeOverlay("fuel", "Screen & Stream")
    for overlay in (gear, fuel):
        overlay.move(10, 10)
        overlay.show()
    process_events(0.1)
    gear.paint_serial = 1
    fuel.paint_serial = 2
    copied = window_copies(monkeypatch, stream_overlay)
    store = FrameStore()
    capture = OverlayCapture(store)
    try:
        store.touch("layout")
        capture.capture()
        assert sorted(copied) == ["fuel", "gear"]
        seq = store.seq
        copied.clear()
        capture.capture()
        assert not copied and store.seq == seq  # nothing painted: no copy, no checksum, nothing sent
        fuel.color = QColor("#ff0000ff")
        fuel.update()
        process_events(0.1)
        fuel.paint_serial = 3
        capture.capture()
        assert copied == ["fuel"] and store.seq > seq
        copied.clear()
        gear.paint_serial = 4  # painted the same: copied, not sent
        seq = store.seq
        capture.capture()
        assert copied == ["gear"]
        del gear.paint_serial  # window not counted: copied every time
        copied.clear()
        capture.capture()
        capture.capture()
        assert copied == ["gear", "gear"]
        # Canvas found once until an overlay moves
        screens = []
        original = stream_overlay.canvas_screen
        monkeypatch.setattr(stream_overlay, "canvas_screen", lambda widgets: screens.append(1) or original(widgets))
        capture.capture()
        capture.capture()
        assert not screens  # found by earlier captures
        fuel.move(30, 30)
        capture.capture()
        capture.capture()
        assert len(screens) == 1
    finally:
        capture.stop()
        for overlay in (gear, fuel):
            overlay.close()
            overlay.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_real_overlay_paint_serial(ui_env, monkeypatch):
    """Overlay window serial changes when its content (child widgets too) is painted or window moves"""
    from importlib import import_module

    from tinypedal import realtime_state
    from tinypedal.setting import cfg
    from tinypedal.widget._base import PaintCounter
    from tinypedal.widget._modern import create_widget

    monkeypatch.setattr(realtime_state, "active", True)
    cfg.overlay["auto_hide"] = False
    cfg.overlay["fixed_position"] = True
    widget = create_widget(import_module("tinypedal.widget.gear"), cfg, "gear")
    try:
        widget.start()
        process_events(0.3)
        serial = widget.paint_serial
        assert serial <= PaintCounter.count
        process_events(0.05)
        widget.update()
        process_events(0.05)
        assert widget.paint_serial > serial
        serial = widget.paint_serial
        widget.move(widget.x() + 5, widget.y())
        QCoreApplication.processEvents()
        assert widget.paint_serial > serial
    finally:
        widget.stop()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# VR overlay
class FakeVR:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append(name)


def test_vr_update_skipped_while_nothing_painted(monkeypatch):
    widget = FakeOverlay("gear", "Screen & Stream")
    widget.move(10, 10)
    widget.show()
    process_events(0.1)
    widget.paint_serial = 1
    monkeypatch.setattr(QApplication, "topLevelWidgets", staticmethod(lambda: [widget]))
    composed = []
    original = vr_overlay.compose_widgets
    monkeypatch.setattr(vr_overlay, "compose_widgets", lambda widgets: composed.append(1) or original(widgets))
    control = vr_overlay.VROverlay()
    fake = FakeVR()
    control._overlay, control._handle, control._visible = fake, 1, True
    try:
        control.update_overlay()
        control.update_overlay()
        assert len(composed) == 1 and fake.calls == ["setOverlayRaw"]  # second tick skipped entirely
        widget.setWindowOpacity(0.5)  # fading
        control.update_overlay()
        assert len(composed) == 2 and fake.calls == ["setOverlayRaw", "setOverlayRaw"]
        widget.paint_serial = 2  # painted the same: composed, not sent again
        control.update_overlay()
        assert len(composed) == 3 and fake.calls == ["setOverlayRaw", "setOverlayRaw"]
        widget.color = QColor("#ff0000ff")
        widget.update()
        process_events(0.1)
        widget.paint_serial = 3
        control.update_overlay()
        assert fake.calls[-1] == "setOverlayRaw" and len(fake.calls) == 3
    finally:
        control._overlay = control._handle = None
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_vr_window_image_matches_grab():
    """Backing store copy (painted window) composes the same image as rendering the window again"""
    widget = FakeOverlay("gear", "Screen & Stream")
    widget.move(10, 10)
    widget.show()
    process_events(0.1)
    try:
        grabbed = vr_overlay.compose_widgets([widget])
        widget.paint_serial = 1
        stored = vr_overlay.compose_widgets([widget])
        assert grabbed is not None and stored is not None
        assert vr_overlay.image_checksum(grabbed) == vr_overlay.image_checksum(stored)
    finally:
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
