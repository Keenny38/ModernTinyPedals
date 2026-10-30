"""Audit H, lot C3: shared connector update thread, decoder per reader, lap state of data modules,
fuel strategy simulation split in steps (same plans as before)"""

import importlib.util
import os
import random
import subprocess
import sys
import threading
from dataclasses import replace

import pytest

from neopedal import fuel_strategy, realtime_state
from neopedal.adapter import _sync, lmu_connector, lmu_reader, rf2_connector, rf2_reader
from neopedal.module import _base, _lap_state
from neopedal.module._base import MODULE_STOP, PENDING_CHECK, PendingLap
from neopedal.module._lap_state import LOAD, SKIP, UPDATE, LapState
from tests.test_data_notify import ScriptedStop, ScriptedZone, lmu_sync
from tests.test_readers import lmu_api, rf2_api

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_COMMIT = "5d380f4e343b215a7f66eb4eb32a72e3eff01683"  # fuel_strategy.simulate before split in steps


# --- a) One update thread for LMU & rF2 connectors
def test_connectors_share_update_thread():
    for connector in (lmu_connector, rf2_connector):
        assert issubclass(connector.SyncData, _sync.SyncData)
        assert connector.SyncData.__dict__.get("_SyncData__update_loop") is None  # loop of base only
    assert lmu_connector.SyncData.THREAD_NAME == "LMU shared memory"
    assert rf2_connector.SyncData.THREAD_NAME == "rF2 shared memory"
    assert rf2_connector.copy_struct is _sync.copy_struct
    assert lmu_connector.SyncData().tele_map == lmu_connector.NO_TELE_MAP
    assert rf2_connector.SyncData().tele_map == rf2_connector.NO_TELE_MAP


def test_lmu_results_stream_read_by_shared_loop(monkeypatch):
    fresh = _sync.notifier.__class__()
    monkeypatch.setattr(_sync, "notifier", fresh)
    sync, zone, data = lmu_sync()
    streams = []
    monkeypatch.setattr(lmu_connector.LMUResults, "update", lambda self, stream: streams.append(stream))
    data.scoring.scoringInfo.mCurrentET = 1.0
    sync._SyncData__update_loop(ScriptedStop([
        lambda: zone.results.append(True),  # resumed
        lambda: zone.results.append(True),  # stream read
        lambda: zone.results.append(True),  # same timestamp: stream not read again
    ]))
    assert len(streams) == 1 and sync.results.timestamp == 1.0


def test_rf2_has_no_results_stream():
    assert not hasattr(rf2_connector.SyncData(), "results")


def test_lmu_index_maps_rebuilt_on_replaced_structure(monkeypatch):
    """Data structure replaced (replay, reconnect) with copy unchanged: maps rebuilt as before"""
    from pyLMUSharedMemory import lmu_data

    monkeypatch.setattr(_sync, "notifier", _sync.notifier.__class__())
    sync, zone, data = lmu_sync()
    other = lmu_data.LMUObjectOut()
    other.scoring.scoringInfo.mNumVehicles = other.telemetry.activeVehicles = 1
    other.scoring.vehScoringInfo[0].mID = other.telemetry.telemInfo[0].mID = 9
    data.scoring.scoringInfo.mCurrentET = 1.0

    def replace():
        zone.data = other
    sync._SyncData__update_loop(ScriptedStop([lambda: None, replace, lambda: None]))
    assert sync.tele_map[0] is other and sync.tele_map[1] == (0,)


# --- b) Text decoder of each reader, replaced by setup (no module global swapped from GUI thread)
@pytest.mark.parametrize("factory", [lmu_api, rf2_api])
def test_encoding_set_on_readers_of_connector(factory):
    sim, _ = factory()
    read = sim.reader()
    assert all(group.tostr is read.state.tostr for group in read)
    sim.set_encoding("CP1252")
    assert all(group.tostr("\xe9t\xe9 ".encode("cp1252")) == "\xe9t\xe9" for group in read)
    other, _ = factory()
    assert other.reader().vehicle.tostr("\xe9".encode()) == "\xe9"  # other connector: own decoder (utf-8)
    later = sim.reader()  # made after setup: same decoder
    assert later.vehicle.tostr("\xe9".encode("cp1252")) == "\xe9"


def test_reader_modules_have_no_global_decoder():
    assert not hasattr(lmu_reader, "tostr") and not hasattr(rf2_reader, "tostr")


def test_setup_applies_encoding(monkeypatch):
    sim, data = lmu_api()
    read = sim.reader()
    monkeypatch.setattr(type(sim._restapi), "setConnection", lambda self, config: None)
    config = {
        "access_mode": 0, "enable_active_state_override": False, "active_state": False,
        "enable_player_index_override": False, "player_index": -1, "character_encoding": "ISO-8859-1",
    }
    sim.setup(config)
    data.scoring.vehScoringInfo[0].mDriverName = "Jos\xe9".encode("latin-1")
    assert read.vehicle.driver_name() == "Jos\xe9"


# --- c) Reset, lap waiting for validation & checkpoint state of data modules
class Recorder:
    def __init__(self):
        self.resolved = []
        self.saved = 0
        self.state: LapState | None = None

    def on_resolved(self, lap, valid):
        self.resolved.append((lap, valid))

    def save(self):
        self.saved += 1
        self.state.delayed_save = False


def lap_state(**kwargs) -> tuple[LapState, Recorder]:
    recorder = Recorder()
    state = LapState(recorder.on_resolved, recorder.save, **kwargs)
    recorder.state = state
    return state, recorder


@pytest.fixture
def driving(monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    clock = {"now": 0.0}
    monkeypatch.setattr(_lap_state, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(_base, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(_base.PendingLap, "confirmed", lambda self: self.finish == 1.0)
    return clock


def test_lap_state_load_update_and_save_on_reset(driving):
    state, recorder = lap_state()
    assert state.receive(0) == LOAD and state.receive(0) == UPDATE
    state.delayed_save = True
    assert state.receive(1) == LOAD and recorder.saved == 1  # saved before new stint loaded
    assert state.receive(MODULE_STOP) == SKIP and recorder.saved == 1  # nothing left to save
    state.delayed_save = True
    assert state.receive(MODULE_STOP) == SKIP and recorder.saved == 2


def test_lap_state_reset_waits_for_pending_lap(driving, monkeypatch):
    state, recorder = lap_state()
    state.receive(0)
    state.pending = PendingLap(90.0, 2.0)  # not validated yet
    state.delayed_save = True
    monkeypatch.setattr(realtime_state, "active", False)
    assert state.receive(1) == SKIP and state.pending is not None and recorder.saved == 0  # waits
    assert state.receive(PENDING_CHECK) == SKIP and recorder.saved == 0  # reset still waiting
    driving["now"] = _base.PENDING_WAIT + 1  # not validated in time
    assert state.receive(PENDING_CHECK) == SKIP
    assert state.pending is None and recorder.resolved[-1][1] is False and recorder.saved == 1
    monkeypatch.setattr(realtime_state, "active", True)
    assert state.receive(1) == LOAD


def test_lap_state_pending_check_without_reset_only_validates(driving):
    state, recorder = lap_state()
    state.receive(0)
    state.pending = PendingLap(90.0, 1.0)  # validated by game
    assert state.receive(PENDING_CHECK) == SKIP and state.pending is None and recorder.resolved[0][1]
    assert recorder.saved == 0


def test_lap_state_module_stop_never_waits(driving):
    state, recorder = lap_state()
    state.receive(0)
    state.pending = PendingLap(90.0, 2.0)
    assert state.receive(MODULE_STOP) == SKIP and state.pending is None and recorder.resolved[0][1] is False


def test_lap_state_checkpoint(driving):
    state, recorder = lap_state(checkpoint=True)
    driving["now"] = 10.0
    assert state.receive(0) == LOAD and state.next_checkpoint == 10.0 + _base.CHECKPOINT_INTERVAL
    state.delayed_save = True
    assert state.receive(0) == UPDATE and recorder.saved == 0  # not due
    driving["now"] = 11.0 + _base.CHECKPOINT_INTERVAL
    assert state.receive(0) == UPDATE and recorder.saved == 1
    assert state.next_checkpoint == driving["now"] + _base.CHECKPOINT_INTERVAL


def test_lap_state_without_checkpoint_never_saves_while_driving(driving):
    state, recorder = lap_state()
    state.receive(0)
    state.delayed_save = True
    driving["now"] = 10 * _base.CHECKPOINT_INTERVAL
    assert state.receive(0) == UPDATE and recorder.saved == 0


def test_lap_state_delta_mode_pending_check_never_resets(driving, monkeypatch):
    """Delta module: PENDING_CHECK only validates lap, reset applied once driving again"""
    state, _ = lap_state(reset_on_check=False)
    state.receive(0)
    monkeypatch.setattr(realtime_state, "active", False)
    assert state.receive(1) == SKIP  # reset delayed until driving
    monkeypatch.setattr(realtime_state, "active", True)  # active again meanwhile
    assert state.receive(PENDING_CHECK) == SKIP  # still only validation
    assert state.receive(1) == LOAD


def test_modules_use_lap_state():
    from neopedal.module import module_delta, module_fuel, module_sectors, module_stats

    for module in (module_delta, module_fuel, module_sectors, module_stats):
        assert module.LapState is LapState
        assert not hasattr(module, "CHECKPOINT_INTERVAL") and not hasattr(module, "monotonic")


# --- d) Fuel strategy simulation in steps: same plans as before the split
def random_values(rng: random.Random) -> dict:
    pick = rng.choice
    drivers = rng.randint(1, 4)
    race_minutes = pick([0, 0, rng.uniform(20, 1440)])
    return {
        "laptime": pick([0.0, rng.uniform(60, 220), rng.uniform(60, 220)]),
        "race_minutes": race_minutes,
        "race_laps": rng.randint(0, 300) if not race_minutes else 0,
        "formation_laps": pick([0.0, 0.5, 1.0, 1.5]),
        "pit_seconds": rng.uniform(0, 120),
        "tank_capacity": pick([0.0, rng.uniform(20, 120), rng.uniform(20, 120)]),
        "fuel_per_lap": pick([0.0, rng.uniform(0.5, 6), rng.uniform(0.5, 6)]),
        "energy_per_lap": pick([0.0, rng.uniform(1, 10)]),
        "fuel_start": pick([0.0, rng.uniform(1, 120)]),
        "energy_start": pick([0.0, rng.uniform(1, 100)]),
        "margin_laps": pick([0.0, rng.uniform(0, 2)]),
        "margin_fuel": pick([0.0, rng.uniform(0, 5)]),
        "margin_percent": pick([0.0, rng.uniform(0, 10)]),
        "tread_start": rng.uniform(40, 100),
        "fresh_tread": pick([100.0, rng.uniform(80, 100)]),
        "wear_per_lap": pick([0.0, rng.uniform(0.2, 5)]),
        "minimum_tread": pick([0.0, rng.uniform(10, 50)]),
        "tyre_set_laps": pick([0, rng.randint(5, 60)]),
        "tyre_life_stints": pick([False, True]),
        "tyre_laps_done": pick([0.0, rng.uniform(0, 30)]),
        "stop_extra_seconds": pick([(), tuple(rng.uniform(0, 30) for _ in range(rng.randint(1, 8)))]),
        "tyre_change_seconds": pick([0.0, rng.uniform(5, 40)]),
        "refuel_rate": pick([0.0, rng.uniform(0.5, 5)]),
        "energy_rate": pick([0.0, rng.uniform(0.5, 5)]),
        "tyres_during_refuel": pick([False, True]),
        "driver_during_refuel": pick([False, True]),
        "minimum_stops": pick([0, 0, rng.randint(1, 4)]),
        "balanced_stints": pick([False, True]),
        "max_stint_minutes": pick([0.0, rng.uniform(20, 150)]),
        "drivers": drivers,
        "driver_change_seconds": pick([0.0, rng.uniform(5, 40)]),
        "stints_per_driver": rng.randint(1, 3),
        "driver_pace": pick([(), tuple(rng.uniform(-1, 2) for _ in range(drivers))]),
        "driver_max_minutes": pick([(), tuple(pick([0.0, rng.uniform(30, 600)]) for _ in range(drivers))]),
        "driver_min_minutes": pick([(), tuple(pick([0.0, rng.uniform(10, 300)]) for _ in range(drivers))]),
        "fuel_effect": pick([0.0, rng.uniform(0.01, 0.2)]),
        "track_evolution": pick([0.0, rng.uniform(-1, 1)]),
        "saving_seconds": pick([0.0, rng.uniform(0, 1)]),
        "saving_cost": pick([0.0, rng.uniform(0, 1)]),
        "sc_lap": pick([0, rng.randint(1, 120)]),
        "sc_laps": pick([0, rng.randint(1, 8)]),
        "sc_consumption": rng.uniform(0.3, 1),
        "sc_laptime": rng.uniform(1, 2),
        "sc_pit": pick([False, True]),
        "sc_pit_saving": rng.uniform(0, 1),
        "sc_wear": rng.uniform(0.2, 1),
        "rain_lap": pick([0, rng.randint(1, 120)]),
        "rain_laps": pick([0, rng.randint(1, 40)]),
        "rain_consumption": rng.uniform(0.7, 1.1),
        "rain_laptime": rng.uniform(1, 1.3),
        "rain_tyres": pick([False, True]),
        "pit_lap_consumption": pick([1.0, rng.uniform(0.4, 1.2)]),
        "extra_laps": pick([0, 1]),
        "lap_offset": pick([0, 0, rng.randint(1, 60)]),
        "clock_offset": pick([0.0, rng.uniform(0, 7200)]),
        "stops_done": pick([0, rng.randint(0, 5)]),
        "driver_start": rng.randint(1, drivers),
        "driver_stints_done": pick([0, rng.randint(0, 2)]),
        "stint_seconds_done": pick([0.0, rng.uniform(0, 3000)]),
        "driver_seconds_done": pick([(), tuple(rng.uniform(0, 5000) for _ in range(drivers))]),
    }


@pytest.fixture(scope="module")
def golden_module(tmp_path_factory):
    """fuel_strategy of commit before the split, loaded from a temporary folder (skipped if not in history)"""
    try:
        source = subprocess.run(
            ["git", "show", f"{GOLDEN_COMMIT}:neopedal/fuel_strategy.py"],
            cwd=REPO, capture_output=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("golden fuel_strategy not in git history (shallow clone)")
    path = tmp_path_factory.mktemp("golden") / "fuel_strategy_golden.py"
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location("neopedal._fuel_strategy_golden", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # relative import of neopedal.module_info
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def same_repr(strategy) -> str:
    """Plan text of the golden copy: fields added since left out"""
    return repr(replace(strategy, drivers_short=0.0)).replace("drivers_short=0.0, ", "")


def test_simulate_same_plans_as_before_split(golden_module):
    """Minimum driving times left out: they are given whole laps & their driver change since
    (test_race_driver_minimums). Maximum times adding up to less than the race left out: planned
    without them since (test_bug_audit_2026_10_29_lap_race, no more one-lap stints)"""
    rng = random.Random(20261013)
    for _ in range(400):
        values = random_values(rng)
        values["driver_min_minutes"] = ()
        laps, stints = rng.randint(0, 250), rng.choice([0, 0, 1, rng.randint(2, 6)])
        setup = fuel_strategy.StrategyInput(**values)
        if not fuel_strategy.maximum_time_short(setup, laps):
            before = golden_module.simulate(golden_module.StrategyInput(**values), laps, stints)
            after = fuel_strategy.simulate(setup, laps, stints)
            assert same_repr(after) == repr(before), (values, laps, stints)
        if not fuel_strategy.maximum_time_short(setup, fuel_strategy.plan(setup).race_laps):
            before = golden_module.plan(golden_module.StrategyInput(**values))
            after = fuel_strategy.plan(setup)
            assert same_repr(after) == repr(before), values


def test_simulate_steps_small():
    """Simulation split in steps: no function left with the old complexity"""
    run_names = {"_plan_laps", "_usage_functions", "_wear_functions", "_lap_timer", "_stint_functions",
                 "_stint_driver", "_pit_crew", "_tyre_check", "_drive_race", "_driver_issues"}
    assert run_names <= set(vars(fuel_strategy))


def test_update_thread_name_kept(monkeypatch):
    names = []
    monkeypatch.setattr(lmu_connector.SyncData, "_SyncData__update", lambda self, event: names.append(
        threading.current_thread().name))
    sync = lmu_connector.SyncData()
    sync.dataset.shmm = ScriptedZone(lmu_connector.lmu_struct.LMUObjectOut())
    sync.dataset.shmm.create = lambda mode: None
    sync.dataset.shmm.close = lambda: None
    sync.start(0)
    sync._update_thread.join(5)
    sync.stop()
    assert names == ["LMU shared memory"]
