"""Modules CPU while driving: data wait, derived wake order, vehicles per car work, shared scoring pass,
recorder stationary samples"""

import logging
import threading
import time
from itertools import pairwise
from types import SimpleNamespace

import pytest

from neopedal import realtime_state
from neopedal.adapter.data_notify import DataNotifier
from neopedal.api_control import api
from neopedal.module import _base, module_recorder, module_relative, module_vehicles
from neopedal.module_info import DeltaTimeInterval
from neopedal.module_info import ScoringSnapshot as Snapshot
from tests.telemetry_sim import fake_reader
from tests.test_module_vehicles_field import CARS, count_calls, field  # noqa: F401  (fixture)


@pytest.fixture
def notifier(monkeypatch):
    fresh = DataNotifier()
    monkeypatch.setattr(_base, "notifier", fresh)
    return fresh


@pytest.fixture
def derived(monkeypatch):
    from neopedal.module import module_delta

    fresh = _base.DerivedUpdates()
    monkeypatch.setattr(_base, "derived_updates", fresh)
    monkeypatch.setattr(module_delta, "derived_updates", fresh)
    return fresh


def make_module(cls=_base.DataModule, active=0.05, idle=0.4, max_wait=0.3):
    module = cls.__new__(cls)
    module.module_name = "module_test"
    module.closed = True
    module.discard = False
    module._event = threading.Event()
    module._done = threading.Event()
    module._done.set()
    module._wake = threading.Event()
    module._wake_derived = threading.Event()
    module._wake_state = threading.Event()
    module._next_update = 0.0
    module.active_interval = active
    module.idle_interval = idle
    module._max_wait = max_wait
    return module


# --- Data wait: once per sample, update interval kept
def test_data_wait_keeps_update_interval_when_data_comes_early(notifier):
    notifier.attach()
    module = make_module(active=0.08)
    module._wake.set()  # data waiting
    started = time.monotonic()
    assert module.wait_update(0.08) is False
    assert time.monotonic() - started < 0.05  # first update at once
    module._wake.set()  # next sample right after update
    assert module.wait_update(0.08) is False
    assert time.monotonic() - started >= 0.075  # not before update interval
    assert not module._wake.is_set()


def test_data_wait_stops_while_keeping_interval(notifier):
    notifier.attach()
    module = make_module(active=0.08)
    module._next_update = time.monotonic() + 5.0
    module._wake.set()
    threading.Timer(0.05, module.stop).start()
    started = time.monotonic()
    assert module.wait_update(0.08) is True
    assert time.monotonic() - started < 1.0


def test_fixed_interval_without_connector_or_at_idle_interval(notifier):
    module = make_module()
    started = time.monotonic()
    assert module.wait_update(0.05) is False
    assert time.monotonic() - started >= 0.045
    notifier.attach()
    module._wake.set()
    started = time.monotonic()
    assert module.wait_update(0.4) is False  # idle interval: fixed polling, data wait not used
    assert time.monotonic() - started >= 0.35


# --- Idle module: woken by activity state change, not every idle interval
def test_idle_module_waits_state_change_and_stops_promptly(ui_env, notifier):
    loops = []

    class Idle(_base.DataModule):
        __slots__ = ()

        def update_data(self):
            while not self.wait_update(_base.WAIT_STATE_CHANGE):
                loops.append(time.monotonic())

    module = make_module(Idle)
    notifier.attach()
    module.start()
    try:
        assert wait_until(lambda: len(loops) == 1)  # first update at once (state read)
        for _ in range(20):
            notifier.notify()  # game data while idle (replay, spectating): never wakes idle module
        time.sleep(0.4)
        assert len(loops) == 1
        realtime_state.notify_change()  # driving started
        assert wait_until(lambda: len(loops) == 2)
        time.sleep(0.3)
        assert len(loops) == 2  # at most one wake per IDLE_WAIT (5 s) without state change
    finally:
        started = time.monotonic()
        module.stop()
        assert module.wait_closed(5) and time.monotonic() - started < 1.0
    assert module._wake_state not in realtime_state._wakes


def wait_until(check, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.01)
    return False


# --- Derived modules (fuel, notes): woken by delta module update only while it updates
class Derived(_base.DataModule):
    WAKE_ON_DERIVED = True
    __slots__ = ()


def test_derived_module_waits_delta_update_not_game_data(notifier, derived):
    notifier.attach()
    derived.set_active(True)
    module = make_module(Derived, active=0.01, max_wait=0.3)
    module._wake.set()  # game data notified: not followed while delta module updates
    started = time.monotonic()
    assert module.wait_update(0.01) is False
    assert time.monotonic() - started >= 0.25  # longest wait
    derived.subscribe(module._wake_derived)
    threading.Timer(0.05, derived.publish).start()
    started = time.monotonic()
    assert module.wait_update(0.01) is False
    assert time.monotonic() - started < 0.25  # woken by delta update
    derived.set_active(False)  # delta stopped: back to game data
    module._wake.set()
    started = time.monotonic()
    assert module.wait_update(0.01) is False
    assert time.monotonic() - started < 0.25


def test_derived_module_stop_wakes_wait(notifier, derived):
    derived.set_active(True)
    module = make_module(Derived, active=0.01, max_wait=30.0)
    threading.Timer(0.05, module.stop).start()
    started = time.monotonic()
    assert module.wait_update(0.01) is True
    assert time.monotonic() - started < 1.0


def test_derived_stamp_follows_delta_updates(derived, monkeypatch):
    monkeypatch.setattr(_base, "data_stamp", lambda: ("data",))
    monkeypatch.setattr(realtime_state, "resets", 3)
    delta = SimpleNamespace(lapDistance=12.5)
    assert _base.derived_stamp(delta) == (("data",), 12.5)
    derived.set_active(True)
    first = _base.derived_stamp(delta)
    assert first == (0, 3)
    assert _base.derived_stamp(delta) == first  # no delta update: skipped
    derived.publish()
    assert _base.derived_stamp(delta) != first


def test_delta_module_publishes_updates(ui_env, derived, monkeypatch):
    from neopedal.module import module_delta
    from neopedal.module_info import minfo
    from neopedal.setting import cfg

    stamps = iter(range(100))
    monkeypatch.setattr(module_delta, "calc_delta_distance", lambda output: SimpleNamespace(send=lambda _: None))
    monkeypatch.setattr(module_delta, "calc_delta_time", lambda **kwargs: SimpleNamespace(send=lambda _: False))
    monkeypatch.setattr(module_delta, "data_stamp", lambda: next(stamps))
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(minfo.delta, "lapDistance", 0.0)
    states = []
    waits = iter(range(4))

    def wait(interval):
        states.append((derived.active, derived.sequence))
        return next(waits) >= 3

    module = module_delta.Realtime(cfg, "module_delta")
    monkeypatch.setattr(module_delta.Realtime, "wait_update", lambda self, interval: wait(interval))
    module.update_data()
    assert states == [(False, 0), (True, 1), (True, 2), (True, 3)]
    assert not derived.active  # module stopped: fuel & notes follow game data again


# --- Vehicles module per car work
def far_field(field):  # noqa: F811
    """Telemetry positions: car 1 at 10 m, car 2 (in pits) at 100 m, car 3 at 500 m from player"""
    data = api._api._shmmapi._shmm.data
    for index, x in enumerate((0.0, 10.0, 100.0, 500.0)):
        data.telemetry.telemInfo[index].mPos.x = x
    return data


def test_far_cars_telemetry_read_less_often(field, monkeypatch):  # noqa: F811
    data = far_field(field)
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    assert field.dataSet[3].relativeStraightDistance == pytest.approx(500.0)
    for index in range(len(CARS)):
        data.telemetry.telemInfo[index].mElapsedTime = 600.02
    positions = count_calls(monkeypatch, "vehicle", "position_longitudinal")
    module_vehicles.update_vehicle_data(
        field, 1.0, 1.0, False, 600.02, True, update_scoring=False, update_far=False, near_range=300.0)
    assert sorted(index for index in positions if index is not None) == [1, 2]  # car 3 far
    positions.clear()
    module_vehicles.update_vehicle_data(
        field, 1.0, 1.0, False, 600.04, True, update_scoring=False, update_far=True, near_range=300.0)
    assert 3 in positions  # far update
    positions.clear()
    data.telemetry.telemInfo[3].mPos.x = 400.0
    module_vehicles.update_vehicle_data(
        field, 1.0, 1.0, False, 600.06, True, update_scoring=False, update_far=True, near_range=300.0)
    assert 3 not in positions  # car telemetry unchanged since
    data.telemetry.telemInfo[3].mElapsedTime = 600.08
    module_vehicles.update_vehicle_data(
        field, 1.0, 1.0, False, 600.08, True, update_scoring=False, update_far=True, near_range=300.0)
    assert 3 in positions and field.dataSet[3].relativeStraightDistance == pytest.approx(400.0)


def test_speed_read_with_scoring_only(field, monkeypatch):  # noqa: F811
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    speeds = count_calls(monkeypatch, "vehicle", "speed")
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, False, 600.01, True, update_scoring=False)
    assert [index for index in speeds if index is not None] == [2]  # car in pits (pit timer)
    assert field.dataSet[3].isYellow and field.dataSet[3].speed == pytest.approx(3.0)


def test_names_read_again_in_turn_or_in_pits(field, monkeypatch):  # noqa: F811
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    names = count_calls(monkeypatch, "vehicle", "driver_name")
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.2, True, name_turn=1)
    assert sorted(index for index in names if index is not None) == [1, 2]  # turn, in pits
    assert [car.driverName for car in field.dataSet[:len(CARS)]] == [car[0] for car in CARS]
    names.clear()
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.4, True)  # every car (other session)
    assert sorted(index for index in names if index is not None) == [0, 1, 2, 3]


def test_names_read_for_car_first_seen_after_reset(field, monkeypatch):  # noqa: F811
    monkeypatch.setattr(module_vehicles, "_index_slot_ids", {})
    field.dataSet[3].driverName = "Previous session"
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True, name_turn=0)
    assert field.dataSet[3].driverName == "Slow"


def test_near_range_follows_enabled_overlays():
    assert module_vehicles.near_range_of({}) == module_vehicles.NEAR_RANGE
    setting = {"navigation": {"enable": True, "view_radius": 500}, "radar": {"enable": False, "radar_radius": 900}}
    assert module_vehicles.near_range_of(setting) == 1250.0
    setting["radar"]["enable"] = True
    assert module_vehicles.near_range_of(setting) == 1800.0
    assert module_vehicles.near_range_of({"radar": {"enable": True, "radar_radius": "x"}}) == 300.0


def test_vehicles_full_rate_only_while_shown(ui_env, monkeypatch):
    from neopedal.setting import cfg

    monkeypatch.setattr(_base, "notifier", DataNotifier())  # fixed interval polling
    monkeypatch.setattr(module_vehicles, "update_vehicle_data", lambda *args, **kwargs: None)
    monkeypatch.setattr(module_vehicles, "update_qualify_position", lambda output: None)
    monkeypatch.setattr(api, "read", SimpleNamespace(
        timing=SimpleNamespace(elapsed=lambda index=None: 1.0),
        session=SimpleNamespace(elapsed=lambda: 2.0, in_race=lambda: False),
        vehicle=SimpleNamespace(player_index=lambda: 0, total_vehicles=lambda: 0),
    ))
    monkeypatch.setattr(realtime_state, "paused", False)
    module = module_vehicles.Realtime(cfg, "module_vehicles")
    module.active_interval, module.idle_interval = 0.01, 0.4
    intervals = []

    def wait(interval):
        intervals.append(interval)
        realtime_state.shown = len(intervals) == 2
        return len(intervals) > 3

    monkeypatch.setattr(realtime_state, "shown", False)
    module._event.wait = wait
    module.update_data()
    assert intervals == [0.4, 0.4, 0.01, 0.4]


# --- Relative module: scoring data read once by vehicles module
def test_relative_same_output_from_vehicles_scoring_pass(field):  # noqa: F811
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    snapshot = field.scoringSnapshot
    assert isinstance(snapshot, Snapshot) and snapshot.scoringTime == pytest.approx(600.0)
    assert len(snapshot.rows) == len(CARS)

    def info(rows, show_in_garage):
        deltas = (tuple(DeltaTimeInterval() for _ in range(8)), tuple(DeltaTimeInterval() for _ in range(8)))
        return module_relative.get_vehicles_info(
            len(CARS), 0, show_in_garage, False, *deltas, None, rows)

    for show_in_garage in (False, True):
        assert info(snapshot.rows, show_in_garage) == info(None, show_in_garage)


def test_scoring_snapshot_only_on_low_priority_update(field):  # noqa: F811
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, False, 600.0, True)
    assert field.scoringSnapshot is None


# --- Recorder: stopped car
def stop_sim():
    return SimpleNamespace(elapsed=0.0, lap_start=0.0, last_laptime=-1.0, distance=0.0, lap_progress=0.0,
                           lap_index=0, track_length=1000.0, speed=50.0, fuel=50.0)


def drive(gen, sim, seconds: float, speed: float, step: float = 0.02):
    for _ in range(round(seconds / step)):
        sim.elapsed = round(sim.elapsed + step, 6)
        sim.speed = speed
        sim.distance += speed * step
        gen.send(0)


@pytest.fixture
def recorder(monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    sim = stop_sim()
    monkeypatch.setattr(api, "read", fake_reader(sim))
    saved = []
    gen = module_recorder.record_telemetry(
        filepath="", min_lap_fraction=0.0, max_saved_laps=10,
        saver=lambda pending, options, valid: saved.append(pending))
    return sim, gen, saved


def cross_line(gen, sim, step: float = 0.02):
    sim.elapsed = round(sim.elapsed + step, 6)
    sim.lap_start = sim.elapsed
    sim.distance = 0.0
    return gen.send(0)  # whether a completed lap waits for validation


def test_recorder_keeps_few_samples_while_stopped(recorder):
    sim, gen, saved = recorder
    gen.send(0)
    drive(gen, sim, 0.1, 50.0)
    cross_line(gen, sim)
    drive(gen, sim, 2.0, 50.0)  # 100 samples
    drive(gen, sim, 10.0, 0.0)  # stopped: one sample per second
    drive(gen, sim, 2.0, 50.0)
    started = sim.lap_start
    cross_line(gen, sim)
    sim.last_laptime = sim.lap_start - started
    drive(gen, sim, 1.1, 50.0)
    assert len(saved) == 1
    rows = saved[0].rows
    assert 200 < len(rows) <= 200 + 1 + 10 + 2
    times = list(rows.column(0))
    gaps = [later - earlier for earlier, later in pairwise(times)]
    assert max(gaps) <= module_recorder.STOPPED_SAMPLE_INTERVAL + 0.03  # last sample of stop kept within 1 s


def test_recorder_drops_lap_too_long(recorder, monkeypatch, caplog):
    monkeypatch.setattr(module_recorder, "MAX_LAP_ROWS", 50)
    sim, gen, saved = recorder
    gen.send(0)
    drive(gen, sim, 0.1, 50.0)
    cross_line(gen, sim)
    with caplog.at_level(logging.WARNING):
        drive(gen, sim, 1.2, 50.0)  # 60 samples
    assert any("dropped" in record.getMessage() for record in caplog.records)
    assert cross_line(gen, sim) is False  # dropped lap never saved
    drive(gen, sim, 0.5, 50.0)
    started = sim.lap_start
    assert cross_line(gen, sim) is True  # next lap recorded from line
    sim.last_laptime = sim.lap_start - started
    drive(gen, sim, 1.1, 50.0)
    assert len(saved) == 1 and len(saved[0].rows) == 26
