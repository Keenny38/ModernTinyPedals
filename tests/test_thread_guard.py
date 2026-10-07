"""Thread supervisor tests"""

import threading

from tinypedal import thread_guard


def _crashing_target(clock, run_time, crashes):
    """Target that runs run_time (fake clock) then crashes, crashes times, then exits normally"""
    calls = []

    def target():
        calls.append(clock[0])
        clock[0] += run_time
        if len(calls) <= crashes:
            raise RuntimeError("sporadic error")

    return target, calls


def test_restart_budget_reset_after_healthy_run(monkeypatch):
    """Sporadic crashes hours apart never exhaust the restart budget"""
    clock = [0.0]
    monkeypatch.setattr(thread_guard, "monotonic", lambda: clock[0])
    target, calls = _crashing_target(clock, thread_guard.HEALTHY_RUN + 1, crashes=5)
    assert thread_guard.run_supervised(target, "test", threading.Event(), max_restarts=3, restart_delay=0)
    assert len(calls) == 6


def test_crash_loop_stops_after_max_restarts(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(thread_guard, "monotonic", lambda: clock[0])
    target, calls = _crashing_target(clock, 1.0, crashes=5)
    assert not thread_guard.run_supervised(target, "test", threading.Event(), max_restarts=3, restart_delay=0)
    assert len(calls) == 4


def test_no_restart_once_stopped(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(thread_guard, "monotonic", lambda: clock[0])
    target, calls = _crashing_target(clock, thread_guard.HEALTHY_RUN + 1, crashes=5)
    event = threading.Event()
    event.set()
    assert not thread_guard.run_supervised(target, "test", event, max_restarts=3, restart_delay=0)
    assert len(calls) == 1
