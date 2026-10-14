"""Audit fixes (G): reload failure, recording restart, installer signature, local servers stop & session
cookie, LAN address wait, widget caches (session best, notifications, rivals, tyre trend, fuel units),
modern partial paint & black box clock kept on rebuild"""

import inspect
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QRegion

from neopedal import loader, update, web_dashboard
from neopedal.api_control import api
from neopedal.command_server import SERVE_POLL_INTERVAL, LocalHTTPServer
from neopedal.const_common import MAX_SECONDS
from neopedal.module_info import minfo
from neopedal.replay import ReplayControl
from neopedal.setting import cfg
from neopedal.web_dashboard import DashboardHandler
from neopedal.widget._black_box import persist
from neopedal.widget._black_box import reader as bb_reader
from tests.test_modern_graphic_widgets import reader, widgets  # noqa: F401  (fixture)


def cell():
    """Classic table cell stand-in"""
    return SimpleNamespace(last=None, text="", update=lambda: None)


# --- 21: session best checks every car once, never one past the last
@pytest.mark.parametrize("modern", [True, False])
def test_session_best_index_wraps_at_last_car(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("timing", modern=modern, show_session_best=True,
                     show_session_best_from_same_class_only=False)
    asked = []
    times = {0: 92.0, 1: 91.0, 2: 93.0, 3: 50.0}  # 3: stale row of a car that left

    def best_laptime(index=None):
        if index is None:  # player personal best
            return 95.0
        asked.append(index)
        return times[index]

    reader(monkeypatch, "vehicle", "total_vehicles", 3)
    reader(monkeypatch, "timing", "best_laptime", best_laptime)
    for _ in range(9):
        if modern:
            widget.session_best()
        else:
            widget.timerEvent(None)
    assert set(asked) == {0, 1, 2}
    best = widget.laptime_session_best if modern else widget.laptime_sbst
    assert best == 91.0


# --- 22: failed reload never runs its callbacks later, queued reload still runs
@pytest.mark.parametrize("queued", [None, True])
def test_failed_reload_drops_callbacks(monkeypatch, app_ctx, queued):
    def broken(*args, **kwargs):
        raise RuntimeError("broken preset")

    reloads = []
    app_ctx(wctrl=SimpleNamespace(wait_stopping=lambda: None), mctrl=SimpleNamespace(wait_stopping=lambda: None))
    monkeypatch.setattr(loader, "finish_reload", broken)
    monkeypatch.setattr(loader, "reload", lambda *args: reloads.append(args))
    called = []
    state = loader._reload
    try:
        state.running = True
        state.preset = False
        state.queued = queued
        state.callbacks.append(lambda: called.append(1))
        loader.complete_reload()  # error logged, not raised into the timer slot
        assert not state.running and state.queued is None
        assert state.callbacks == [] and called == []
        assert reloads == ([(True, False)] if queued else [])
    finally:
        loader.cancel_reload()


# --- 23: recording not restarted while the previous recorder thread still writes
class StuckThread:
    def __init__(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        pass


def test_recording_refused_while_previous_still_closing(tmp_path):
    control = ReplayControl()
    stuck = StuckThread()
    control._rec_thread = stuck  # type: ignore[assignment]
    control.stop_recording()
    assert not control.recording
    assert not control.start_recording(str(tmp_path / "next.tpreplay"), lambda: None, rate=100)
    stuck.alive = False  # finished closing
    assert control.start_recording(str(tmp_path / "next.tpreplay"), lambda: None, rate=100)
    control.stop_recording()
    assert not control.recording


# --- 24: unknown signature refused for a custom update repository
@pytest.mark.parametrize("repo, refused", [("someone/fork", True), (update.FORK_REPO_NAME, False)])
def test_unknown_signature_custom_repository(monkeypatch, repo, refused):
    monkeypatch.setattr(update, "installer_signature", lambda path: update.SIGNATURE_UNKNOWN)
    if refused:
        with pytest.raises(update.UnsignedInstallerError):
            update.verify_installer("Setup.exe", repo)
    else:
        update.verify_installer("Setup.exe", repo)


# --- 25: local servers stop quickly (serving loop waited by a worker thread, never by the GUI thread)
def test_local_server_short_poll_interval():
    assert inspect.signature(LocalHTTPServer.serve_forever).parameters["poll_interval"].default == SERVE_POLL_INTERVAL
    assert SERVE_POLL_INTERVAL <= 1.0
    server = LocalHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)  # serving loop waiting in select
    start = time.monotonic()
    server.stop()
    assert time.monotonic() - start < 0.1
    assert server.closed.wait(SERVE_POLL_INTERVAL + 1)
    thread.join(1)
    assert not thread.is_alive()


# --- 26: non ASCII session cookie rejected, no TypeError
def test_non_ascii_session_cookie(monkeypatch):
    token = "abc"
    now = time.monotonic()
    monkeypatch.setattr(DashboardHandler, "sessions", {token: [now, now]})
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.headers = {"Cookie": "tp_session=été"}  # type: ignore[assignment]
    assert not handler.has_session()
    handler.headers = {"Cookie": f"tp_session={token}"}  # type: ignore[assignment]
    assert handler.has_session()


# --- 27: urls(wait=True) waits a bounded time for LAN addresses, cached ones returned after
def test_address_wait_bounded(monkeypatch):
    release = threading.Event()

    def slow_lookup():
        assert release.wait(5)
        return ["10.0.0.5"]

    monkeypatch.setattr(web_dashboard, "ADDRESS_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(web_dashboard, "lookup_local_addresses", slow_lookup)
    web_dashboard.clear_address_cache()
    try:
        web_dashboard._store_addresses(["192.168.1.20"])
        start = time.monotonic()
        assert web_dashboard.local_addresses(max_age=0, wait=True) == ["192.168.1.20"]
        assert time.monotonic() - start < 1.0
    finally:
        release.set()
        end = time.monotonic() + 5
        while web_dashboard._address_refreshing and time.monotonic() < end:
            time.sleep(0.01)
        web_dashboard.clear_address_cache()
    assert web_dashboard._address_done.is_set()


def test_address_wait_returns_fresh_lookup(monkeypatch):
    monkeypatch.setattr(web_dashboard, "lookup_local_addresses", lambda: ["10.0.0.7"])
    web_dashboard.clear_address_cache()
    try:
        assert web_dashboard.local_addresses(wait=True) == ["10.0.0.7"]
    finally:
        web_dashboard.clear_address_cache()


# --- 42: race restart (same session identifier) resets class best
def test_race_notifications_reset_on_restart(ui_env, monkeypatch):
    from neopedal.widget.race_notifications import RaceEvents

    elapsed = [1000.0]
    monkeypatch.setattr(api.read.session, "identifier", lambda: ("race", 0, 0))
    monkeypatch.setattr(api.read.session, "elapsed", lambda: elapsed[0])
    events = RaceEvents(defaultdict(bool))
    events.poll(0.0)
    events.class_best = 90.0
    elapsed[0] = 998.0  # small step back (replay jitter): kept
    events.poll(0.1)
    assert events.class_best == 90.0
    elapsed[0] = 5.0  # restarted
    events.poll(0.2)
    assert events.class_best == MAX_SECONDS


# --- 43: rivals interval cell rebuilt only when shown value changes
def test_rivals_interval_keyed_on_shown_value(widgets, monkeypatch):  # noqa: F811
    widget = widgets("rivals", modern=False, show_time_interval=True, decimal_places_time_interval=1)
    vehicles = minfo.vehicles
    player = vehicles.dataSet[vehicles.playerIndex]
    ahead = next(index for index, car in enumerate(vehicles.dataSet) if car is not player)
    monkeypatch.setattr(player, "classAheadIndex", ahead)
    monkeypatch.setattr(player, "classBehindIndex", -1)
    monkeypatch.setattr(vehicles.dataSet[ahead], "positionOverall", 1)
    monkeypatch.setattr(player, "positionOverall", 2)
    monkeypatch.setattr(player, "gapBehindNextInClass", 1.231)
    widget.timerEvent(None)
    target = widget.bars_int[0]
    last = target.last
    assert last[0] == 1.2
    monkeypatch.setattr(player, "gapBehindNextInClass", 1.234)  # same tenth
    widget.timerEvent(None)
    assert target.last is last
    monkeypatch.setattr(player, "gapBehindNextInClass", 1.26)
    widget.timerEvent(None)
    assert target.last[0] == 1.3 and target.text.strip() == "-1.3"


# --- 44: tyre trend repaints when charts rebuilt for a new optimal temperature
def test_tyre_trend_state_follows_chart_rebuild(widgets, monkeypatch):  # noqa: F811
    widget = widgets("tyre_temp_trend", modern=False, show_optimal_temperature=True)
    reader(monkeypatch, "tyre", "optimal_temperature", (90.0,) * 4)
    first = widget.read_trend(widget.chart_rects)
    assert widget.read_trend(widget.chart_rects) == first
    reader(monkeypatch, "tyre", "optimal_temperature", (95.0,) * 4)
    assert widget.read_trend(widget.chart_rects) != first


# --- 45: fuel cells follow unit sign / energy type with same value
@pytest.mark.parametrize("name", ["stint_history", "lap_time_history"])
def test_fuel_cell_sign_change(widgets, name):  # noqa: F811
    widget = widgets(name, modern=False)
    target = cell()
    widget.update_fuel(target, 10.0, "L")
    assert target.text.endswith("L")
    widget.update_fuel(target, 10.0, "%")
    assert target.text.endswith("%")


def test_refill_cell_energy_type_change(widgets):  # noqa: F811
    cfg.units["fuel_unit"] = "Gallon"
    widget = widgets("relative_finish_order", modern=False)
    target = cell()
    widget.update_refill(target, 40.0, False)
    fuel_text = target.text
    widget.update_refill(target, 40.0, True)  # energy: no fuel unit conversion
    assert target.text != fuel_text and target.last == (40.0, True)


# --- 46: static layer built during a partial paint has every row
def test_static_layer_built_whole_in_partial_paint(widgets, monkeypatch):  # noqa: F811
    widget = widgets("lap_time_history")
    regions = []
    original = widget.paint_static

    def paint_static(painter):
        regions.append(widget.paint_region)
        original(painter)

    monkeypatch.setattr(widget, "paint_static", paint_static)
    widget.redraw_static()
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    widget.render(image, QPoint(), QRegion(QRect(0, 0, widget.width(), max(widget.height() // 3, 1))))
    assert regions == [None]


# --- 47: black box clock continued by rebuilt widget (incident times kept)
@pytest.fixture
def black_box_memory():
    persist.MEMORY.clear()
    yield
    persist.MEMORY.clear()


def test_black_box_clock_kept_on_rebuild(ui_env, monkeypatch, black_box_memory):
    from neopedal.widget import black_box

    clock = [100.0]
    paused = [False]
    monkeypatch.setattr(bb_reader, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api.read.state, "paused", lambda: paused[0])
    cfg.user.setting["black_box"]["enable_auto_resize"] = False
    first = black_box.Realtime(cfg, "black_box")
    preview = black_box.Realtime(cfg, "black_box")
    try:
        first.overlay_started = True
        assert first.recorder_now() == 100.0
        paused[0] = True
        clock[0] = 110.0
        assert first.recorder_now() == 110.0
        clock[0] = 140.0
        paused[0] = False
        assert first.recorder_now() == 110.0  # 30 s paused
        paused[0] = True
        preview.recorder_now()  # preview never shares its clock
        paused[0] = False
        assert persist.kept_clock("black_box") == (None, 30.0)
    finally:
        first.deleteLater()
        preview.deleteLater()
    second = black_box.Realtime(cfg, "black_box")
    try:
        clock[0] = 141.0
        assert second.recorder_now() == 111.0  # old clock continued
    finally:
        second.deleteLater()
