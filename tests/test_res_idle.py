"""Idle CPU & memory: GC policy, lazy server imports, poll worker, rank file parsing, help cache, idle timers"""

import json
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from neopedal import loader, realtime_state


# --- Garbage collection at idle moments
@pytest.fixture
def gc_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(loader.gc, "freeze", lambda: calls.append("freeze"))
    monkeypatch.setattr(loader.gc, "unfreeze", lambda: calls.append("unfreeze"))
    monkeypatch.setattr(loader.gc, "collect", lambda *_: calls.append("collect"))
    timers = []
    from PySide6.QtCore import QTimer

    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda delay, func: timers.append(func)))
    monkeypatch.setattr(loader, "_gc_collect_due", False)
    monkeypatch.setattr(loader, "_gc_frozen", True)
    monkeypatch.setattr(realtime_state, "active", False)
    return SimpleNamespace(calls=calls, timers=timers)


def test_request_idle_collect_coalesced(gc_calls):
    loader.request_idle_collect()
    loader.request_idle_collect()  # page closed twice in a row: one collection
    assert len(gc_calls.timers) == 1 and gc_calls.calls == []
    gc_calls.timers.pop()()
    assert gc_calls.calls == ["unfreeze", "collect", "freeze"] and loader._gc_frozen
    loader.request_idle_collect()  # later page close: collected again
    assert len(gc_calls.timers) == 1


def test_request_idle_collect_waits_for_driving_end(gc_calls, monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    loader.request_idle_collect()
    gc_calls.timers.pop()()
    assert gc_calls.calls == [] and len(gc_calls.timers) == 1  # postponed while driving


def test_request_idle_collect_before_start_finished(gc_calls, monkeypatch):
    monkeypatch.setattr(loader, "_gc_frozen", False)
    loader.request_idle_collect()
    assert gc_calls.timers == []


def test_periodic_collect_only_when_idle_and_due(gc_calls, monkeypatch):
    monkeypatch.setattr(loader, "_gc_last_collect", time.monotonic())
    loader.periodic_idle_collect()  # collected recently
    assert gc_calls.timers == []
    monkeypatch.setattr(loader, "_gc_last_collect", time.monotonic() - loader.IDLE_COLLECT_MS / 1000)
    monkeypatch.setattr(realtime_state, "active", True)
    loader.periodic_idle_collect()  # driving
    assert gc_calls.timers == []
    monkeypatch.setattr(realtime_state, "active", False)
    loader.periodic_idle_collect()
    assert len(gc_calls.timers) == 1


def test_gc_stats_and_allocation_top():
    from neopedal import perf_monitor

    stats = perf_monitor.gc_stats()
    assert stats.frozen >= 0 and stats.tracked >= 0
    assert perf_monitor.allocation_top() == []  # off by default
    perf_monitor.set_allocation_tracing(True)
    try:
        data = [bytearray(1024) for _ in range(200)]
        rows = perf_monitor.allocation_top(5)
        assert rows and rows[0].size_kb > 0 and ":" in rows[0].source and len(data) == 200
    finally:
        perf_monitor.set_allocation_tracing(False)
    assert perf_monitor.allocation_top() == []


# --- Servers & update checker imported only when used
def test_lazy_service_imports_on_first_use():
    service = loader.LazyService("perf_monitor", "PerfMonitor")
    assert service.imported  # already imported by another user
    assert service.enabled is False and service.imported
    assert loader.imported(SimpleNamespace())  # replaced by tests: used as is


def test_loader_import_leaves_servers_unloaded():
    code = ("import sys, neopedal.loader as l; "
            "print(int('neopedal.web_dashboard' in sys.modules), int('neopedal.update' in sys.modules), "
            "int(l.imported(l.webdashboard)), int(l.imported(l.update_checker)))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                            env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["0", "0", "0", "0"]


def test_servers_off_never_imported(ui_env, monkeypatch):
    from neopedal.setting import cfg

    used = []

    class NotImported:
        imported = False

        def __getattr__(self, attr):
            used.append(attr)
            return lambda: None

    for name in ("cmdserver", "webdashboard", "streamoverlay"):
        monkeypatch.setattr(loader, name, NotImported())
    monkeypatch.setitem(cfg.user.config["remote_control"], "enable_remote_control", False)
    monkeypatch.setitem(cfg.user.config["web_dashboard"], "enable_web_dashboard", False)
    monkeypatch.setitem(cfg.user.config["stream_overlay"], "enable_stream_overlay", False)
    loader.enable_servers()
    loader.enable_stream_overlay()
    assert used == []  # off & not imported: never imported
    monkeypatch.setitem(cfg.user.config["web_dashboard"], "enable_web_dashboard", True)
    loader.enable_servers()
    assert used == ["enable"]


# --- Poll worker: no thread per read
def test_poll_worker_runs_reads_on_shared_threads(monkeypatch):
    from neopedal import game_rest_poll
    from neopedal.game_rest_poll import PollWorker

    monkeypatch.setattr(game_rest_poll, "POLL_IDLE_SECONDS", 0.2)
    worker = PollWorker(size=1, name="Test poll")
    done = threading.Event()
    names = []
    for index in range(3):
        worker.submit(lambda index=index: names.append((index, threading.current_thread().name)))
    worker.submit(lambda: 1 / 0)  # error logged, worker keeps running
    worker.submit(done.set)
    assert done.wait(5)
    assert [index for index, _ in names] == [0, 1, 2] and {name for _, name in names} == {"Test poll"}
    assert worker._workers == 1
    deadline = time.monotonic() + 5
    while worker._workers and time.monotonic() < deadline:  # idle thread ends
        time.sleep(0.05)
    assert worker._workers == 0


def test_route_poller_single_flight(monkeypatch):
    from neopedal import game_rest_poll

    submitted = []
    monkeypatch.setattr(game_rest_poll.poll_worker, "submit", submitted.append)
    now = [100.0]
    poller = game_rest_poll.RoutePoller("/route", lambda data: data, None, 1.0,
                                        fetch=lambda: (200, b'{"a": 1}'), clock=lambda: now[0])
    poller.poll()
    now[0] += 5
    poller.poll()  # read still waiting: not submitted twice
    assert len(submitted) == 1
    submitted.pop()()
    assert poller.value == {"a": 1}
    poller.poll()
    assert len(submitted) == 1


def test_rank_watcher_poll_uses_worker(monkeypatch, tmp_path):
    from neopedal import game_rest_poll
    from neopedal.process import driver_ranks as dr

    submitted = []
    monkeypatch.setattr(game_rest_poll.poll_worker, "submit", submitted.append)
    watcher = dr.RankWatcher(lambda: dr.Located("", "", ()), clock=lambda: 50.0)
    watcher.poll()
    watcher.poll()
    assert len(submitted) == 1
    submitted.pop()()
    assert not watcher._busy and watcher.serial == 0


def test_rank_watcher_locates_less_once_found(tmp_path):
    from neopedal.process import driver_ranks as dr
    from tests.test_driver_ranks import storage_text

    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    now = [0.0]
    located = []
    watcher = dr.RankWatcher(lambda: located.append(1) or dr.Located(str(path), "76561190000000001", ()),
                             clock=lambda: now[0])
    watcher.check()
    now[0] += dr.LOCATE_SECONDS + 1
    watcher.check()
    assert len(located) == 1  # file found: game folder & Steam users not read again every minute
    now[0] += dr.LOCATE_FOUND_SECONDS
    watcher.check()
    assert len(located) == 2


# --- Rank storage parsed from bytes
def test_parse_storage_bytes_and_marker():
    from neopedal.process import driver_ranks as dr
    from tests.test_driver_ranks import storage_text

    raw = storage_text().encode()
    assert len(dr.parse_raw(raw)) == 2
    assert dr.parse_storage(json.dumps({"profile": "{}"}).encode()) == []  # no rank key: not parsed
    broken = raw.replace(b"Keenny", b"Kee\xffnny")  # invalid UTF-8 replaced, rest read
    assert len(dr.parse_raw(broken)) == 2
    assert dr.valid_raw(broken) and not dr.valid_raw(raw[:-5])


# --- Option help cache
def test_clear_help_cache():
    from neopedal.i18n import options

    options.option_help("cruise", "enable")
    assert options._help.cache_info().currsize == 1
    options.clear_help_cache()
    assert options._help.cache_info().currsize == 0 and options._help_translations.cache_info().currsize == 0


# --- Idle timers skip work while window minimized or in tray
def test_rail_refresh_skipped_while_minimized(ui_env, monkeypatch):
    from neopedal.ui import app as app_module

    view = app_module.TabView.__new__(app_module.TabView)
    calls = []
    shown = SimpleNamespace(isVisible=lambda: True, isMinimized=lambda: False)
    monkeypatch.setattr(app_module.TabView, "refresh_rail", lambda self: calls.append(1))
    monkeypatch.setattr(app_module.TabView, "window", lambda self: shown)
    view.refresh_rail_shown()
    shown.isMinimized = lambda: True
    view.refresh_rail_shown()
    shown.isMinimized, shown.isVisible = (lambda: False), (lambda: False)  # in tray
    view.refresh_rail_shown()
    assert calls == [1]


def test_screen_change_checked_once_signals_settle(ui_env, monkeypatch):
    from PySide6.QtCore import QTimer

    from neopedal.ui import app as app_module

    window = SimpleNamespace(_screen_timer=QTimer())
    window._screen_timer.setSingleShot(True)
    app_module.AppWindow.screen_setup_changed(window, object())
    assert window._screen_timer.isActive() and window._screen_timer.interval() == app_module.SCREEN_SETTLE_MS
    window._screen_timer.stop()


def test_pace_notes_player_interval_floor():
    from neopedal.template.setting_common import COMMON_DEFAULT
    from neopedal.ui import pace_notes_player

    assert COMMON_DEFAULT["pace_notes_playback"]["update_interval"] == pace_notes_player.MIN_UPDATE_INTERVAL == 50
