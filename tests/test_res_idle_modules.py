"""Idle data modules (hybrid, mapping, sectors, wheels, stint, stats) wait for activity state change instead of
polling at idle interval, keep checking a lap waiting for validation, stop promptly, update again once active"""

import threading
import time

import pytest

from neopedal import realtime_state
from neopedal.api_control import api
from neopedal.module import _base
from tests.test_perf_modules import fake_reader, wait_until

# Module name: generator factories replaced by recording generators
MODULES = {
    "module_hybrid": ("calc_motor",),
    "module_mapping": ("record_track_map", "record_track_info"),
    "module_sectors": ("record_sectors",),
    "module_wheels": (
        "calc_wheel_rotation", "calc_tyre_wear", "calc_brake_wear",
        "calc_suspension_travel", "calc_vehicle_weight", "calc_wheel_angle"),
    "module_stint": ("record_stint_history", "record_consumption_history"),
    "module_stats": ("record_driver_stats", "auto_backup_car_setup"),
}
STATE_NAMES = ("active", "resets", "singleton", "spectating", "overriding")


def recording_generator(sends: list, waiting: list):
    """Generator recording values sent, yields waiting[0] (lap waiting for validation)"""
    def generator():
        while True:
            sends.append((yield waiting[0]))

    gen = generator()
    next(gen)
    return gen


@pytest.fixture
def idle_state(monkeypatch):
    for name in STATE_NAMES:
        monkeypatch.setattr(realtime_state, name, getattr(realtime_state, name), raising=False)
    realtime_state.active = False
    realtime_state.resets = 0
    realtime_state.singleton = True
    realtime_state.spectating = False
    realtime_state.overriding = False
    monkeypatch.setattr(api, "read", fake_reader({"tele": 1.0, "scor": 10.0, "player": 0, "total": 1}))
    return realtime_state


def start_module(monkeypatch, name: str, waiting: list):
    import importlib

    from neopedal.setting import cfg

    mod = importlib.import_module(f"neopedal.module.{name}")
    sends: list = []
    for factory in MODULES[name]:
        monkeypatch.setattr(mod, factory, lambda *args, **kwargs: recording_generator(sends, waiting))
    waits: list = []
    for method in ("wait_update", "wait_fixed"):
        original = getattr(_base.DataModule, method)

        def counted(self, interval, _original=original):
            if threading.current_thread().name == f"module:{name}":
                waits.append(interval)
            return _original(self, interval)

        monkeypatch.setattr(_base.DataModule, method, counted)
    module = mod.Realtime(cfg, name)
    module.active_interval = 0.005
    module.idle_interval = 0.01
    module._max_wait = 0.01
    module.start()
    return module, sends, waits


@pytest.mark.parametrize("name", tuple(MODULES))
def test_idle_module_waits_state_change(ui_env, idle_state, monkeypatch, name):
    module, sends, waits = start_module(monkeypatch, name, [False])
    try:
        time.sleep(0.4)  # not on track: ~40 wakeups at idle interval before
        # First tick (modules following resets: one reset check at start), then idle
        assert len(waits) <= 5, waits
        assert waits[-1] == _base.WAIT_STATE_CHANGE
        # Driving: woken at once, data updated at active interval
        before = len(sends)
        realtime_state.active = True
        realtime_state.notify_change()
        assert wait_until(lambda: len(sends) > before, 2.0)
        # Track left: idle again
        realtime_state.active = False
        realtime_state.notify_change()
        assert wait_until(lambda: waits[-1] == _base.WAIT_STATE_CHANGE, 2.0)
        count = len(waits)
        time.sleep(0.3)
        assert len(waits) - count <= 1
        # Vehicle reset while idle (modules following resets): woken & reset sent
        if name not in ("module_hybrid", "module_wheels"):
            before = len(sends)
            realtime_state.resets += 1
            realtime_state.notify_change()
            assert wait_until(lambda: len(sends) > before, 2.0)
    finally:
        started = time.monotonic()
        module.stop()
        assert module.wait_closed(5) and time.monotonic() - started < 1.0


@pytest.mark.parametrize("name", ("module_sectors", "module_stats"))
def test_lap_waiting_validation_keeps_idle_interval(ui_env, idle_state, monkeypatch, name):
    from neopedal.module._base import PENDING_CHECK

    waiting = [True]
    realtime_state.active = True
    module, sends, waits = start_module(monkeypatch, name, waiting)
    try:
        assert wait_until(lambda: len(sends) >= 1, 2.0)
        realtime_state.active = False  # left track just after line: lap waiting for validation
        realtime_state.notify_change()
        assert wait_until(lambda: sends.count(PENDING_CHECK) >= 5, 2.0)  # checked at idle interval
        waiting[0] = False  # validated
        assert wait_until(lambda: waits[-1] == _base.WAIT_STATE_CHANGE, 2.0)
        count = sends.count(PENDING_CHECK)
        time.sleep(0.2)
        assert sends.count(PENDING_CHECK) == count
    finally:
        module.stop()
        assert module.wait_closed(5)
