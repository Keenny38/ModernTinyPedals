"""Performance monitor probes: main thread stalls & garbage collection pauses, GC freeze after start"""

import gc
import time

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import loader
from neopedal.perf_monitor import STALL_THRESHOLD, PerfMonitor, _gc_probe


@pytest.fixture(autouse=True)
def app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def monitor():
    PerfMonitor.set_enabled(True)
    yield PerfMonitor
    PerfMonitor.set_enabled(False)
    PerfMonitor.reset()


def events(monitor) -> dict:
    return {(item.name, item.event): item for item in monitor.stats()}


def spin(seconds: float):
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.002)


def test_main_thread_stall_recorded(monitor):
    spin(0.1)  # probe running
    time.sleep(STALL_THRESHOLD * 3)  # event loop blocked
    spin(0.1)
    stall = events(monitor).get(("main_thread", "stall"))
    assert stall is not None
    assert stall.maximum >= STALL_THRESHOLD * 1000


def test_no_stall_when_event_loop_runs(monitor):
    spin(0.3)
    assert ("main_thread", "stall") not in events(monitor)


def test_garbage_collection_recorded(monitor):
    gc.collect()
    assert events(monitor)[("python", "garbage collection")].calls >= 1


def test_probes_removed_when_disabled():
    PerfMonitor.set_enabled(True)
    PerfMonitor.set_enabled(False)
    assert _gc_probe._callback not in gc.callbacks
    PerfMonitor.reset()
    gc.collect()
    spin(0.05)
    assert PerfMonitor.stats() == []


def test_gc_freeze_after_start_and_unfreeze_on_reload(monkeypatch):
    calls = []
    monkeypatch.setattr(loader.gc, "freeze", lambda: calls.append("freeze"))
    monkeypatch.setattr(loader.gc, "unfreeze", lambda: calls.append("unfreeze"))
    monkeypatch.setattr(loader.gc, "collect", lambda *_: calls.append("collect"))
    monkeypatch.setattr(loader, "_gc_frozen", False)
    assert not loader.unfreeze_collected()  # never frozen (tests, start not finished): nothing done
    loader.freeze_collected()
    assert calls == ["collect", "freeze"]
    assert loader.unfreeze_collected()
    assert calls[-1] == "unfreeze"
    assert not loader.unfreeze_collected()
