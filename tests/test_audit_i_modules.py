"""Audit I, lot B2: real-time data modules

PitTimer first lap (BUG-005), disable_all without blocking the GUI (PERF-004), data saver thread for module
files (PERF-003, PERF-026), lap file streamed to disk (PERF-015, PERF-025), data modules imported on first use
(PERF-024), relative module following vehicles module (PERF-058), virtual energy presence (BUG-042), lap time
history from scoring lap start (BUG-043), car count published after rows (BUG-044), electric car weight (BUG-024).
"""

from __future__ import annotations

import gzip
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import realtime_state
from neopedal.api_control import api
from neopedal.const_file import ConfigType
from neopedal.module import (
    _base,
    _lap_state,
    module_fuel,
    module_recorder,
    module_relative,
    module_stint,
    module_vehicles,
)
from neopedal.module._base import MODULE_STOP, PENDING_CHECK
from neopedal.module_control import ModuleControl
from neopedal.module_info import (
    ConsumptionDataSet,
    DeltaInfo,
    FuelInfo,
    HistoryInfo,
    PitTimer,
    ScoringSnapshot,
    VehiclesInfo,
    minfo,
)
from neopedal.setting import cfg
from neopedal.userfile import data_saver
from neopedal.userfile.data_saver import pending_saves, queue_save, wait_data_saver
from tests.telemetry_sim import LapSim, fake_reader
from tests.test_module_vehicles_field import CARS, field  # noqa: F401  (fixture)


def spin_until(condition, seconds: float = 5.0) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.002)
    return condition()


# --- BUG-005: a car on its first lap (grid start, new session, app started) is not pitting
def test_pit_timer_first_lap_is_not_a_pit_lap():
    timer = PitTimer()
    timer.update(0, 10.0, 0, 50.0)  # grid start, first sample
    assert not timer.pitting and timer.laps == 0
    timer.update(0, 100.0, 1, 50.0)
    assert not timer.pitting and timer.laps == 1
    # Real pit stop (stopped over 1 s, in pit lane over 2 s): pitting during the stop & the out lap
    for seconds in (200.0, 201.5, 203.0):
        timer.update(1, seconds, 2, 0.0)
    assert timer.pitting
    timer.update(0, 210.0, 2, 30.0)  # out lap, pit lane left
    assert timer.pitting and timer.laps == 0
    timer.update(0, 300.0, 3, 50.0)  # next lap
    assert not timer.pitting and timer.laps == 1


def test_pit_timer_new_session_forgets_pit_visit():
    timer = PitTimer()
    for seconds in (200.0, 201.5, 203.0):
        timer.update(1, seconds, 5, 0.0)
    timer.update(0, 210.0, 5, 30.0)
    assert timer.pitting
    timer.update(0, 5.0, 0, 50.0)  # laps start over: new session, car on track from the grid
    assert not timer.pitting and timer.laps == 0
    timer.update(2, 6.0, 0, 0.0)  # car in garage: out lap once it leaves
    timer.update(0, 20.0, 0, 20.0)
    assert timer.pitting


# --- PERF-004: disable all modules from GUI thread never waits for module stop work (saving)
class SlowModule:
    """Data module whose stop work finishes once released"""

    def __init__(self):
        self.closed = False
        self.done = threading.Event()

    def stop(self, discard=False):
        pass

    def finish(self):
        self.closed = True
        self.done.set()

    def wait_closed(self, timeout):
        return self.done.wait(timeout)


@pytest.fixture
def control(ui_env, monkeypatch):
    from neopedal import module_control

    control = ModuleControl(SimpleNamespace(__all__=["module_a", "module_b"]), ConfigType.MODULE)
    fakes = {name: SlowModule() for name in ("module_a", "module_b")}
    control._active_modules.update(fakes)
    for name in fakes:
        monkeypatch.setitem(cfg.user.setting, name, {"enable": True})
    return control, fakes, module_control  # ui_env: setting never saved


def test_disable_all_polls_stopping_modules_on_gui_thread(control):
    control, fakes, module_control = control
    control._stop_timeout = 0.0  # anything the fixture left
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module_control, "event_loop_running", lambda: True)
        started = time.perf_counter()
        control.disable_all()
    assert time.perf_counter() - started < 0.5  # never waits for the modules
    assert not control.active_modules and control.stopping()
    assert all(not cfg.user.setting[name]["enable"] for name in fakes)
    for fake in fakes.values():
        fake.finish()
    assert spin_until(lambda: not control.stopping())  # polled by timer, forgotten once stopped


def test_disable_all_waits_without_event_loop(control):
    control, fakes, module_control = control
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module_control, "event_loop_running", lambda: False)
        threading.Timer(0.1, lambda: [fake.finish() for fake in fakes.values()]).start()
        control.disable_all()
    assert all(fake.closed for fake in fakes.values()) and not control.stopping()


# --- PERF-003: module files written on the data saver thread, in order; synchronous on module stop
@pytest.fixture
def saver_blocked():
    """Data saver thread held until released: queued saves wait"""
    release = threading.Event()
    data_saver.DATA_SAVER.submit(release.wait, 10)
    yield release
    release.set()
    assert wait_data_saver(10)


def test_queue_save_runs_in_background_in_order(saver_blocked):
    calls: list = []
    queue_save(calls.append, 1)
    queue_save(calls.append, 2, sync=False)
    assert calls == [] and pending_saves() >= 2  # returned at once, nothing written yet
    assert not wait_data_saver(0.05)
    saver_blocked.set()
    assert wait_data_saver(5)
    assert calls == [1, 2] and pending_saves() == 0


def test_queue_save_sync_waits_its_turn(saver_blocked):
    calls: list = []
    queue_save(calls.append, "queued before")
    threading.Timer(0.1, saver_blocked.set).start()
    queue_save(calls.append, "stop", sync=True)
    assert calls == ["queued before", "stop"]  # written on return, after earlier saves (same file order kept)


def test_queue_save_error_logged(caplog):
    def broken():
        raise KeyError("broken")

    with caplog.at_level("ERROR", logger=data_saver.__name__):
        queue_save(broken)
        assert wait_data_saver(5)
    assert any("saving failed" in record.getMessage() and record.exc_info for record in caplog.records)


def test_lap_state_sync_save_on_stop_and_inactive(monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    state = _lap_state.LapState(lambda lap, valid: None, lambda: None, checkpoint=True)
    assert state.receive(1) == _lap_state.LOAD and not state.sync_save  # reset while driving: queued
    assert state.receive(1) == _lap_state.UPDATE and not state.sync_save  # checkpoint while driving: queued
    assert state.receive(PENDING_CHECK) == _lap_state.SKIP and state.sync_save  # player inactive
    assert state.receive(MODULE_STOP) == _lap_state.SKIP and state.sync_save  # module stop


@pytest.fixture
def fuel_sim(monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(minfo, "delta", DeltaInfo())
    monkeypatch.setattr(minfo, "vehicles", VehiclesInfo())
    sim = LapSim(lap_times=[90.0] * 4, fuel_per_lap=3.0)
    monkeypatch.setattr(api, "read", fake_reader(sim))
    return sim


def drive(sim: LapSim, gen, reset: int = 0, laps: int | None = None):
    """Drive laps (all if None), 3 s past the last line so the lap is validated"""
    end = len(sim.lap_times) if laps is None else min(sim.lap_index + laps, len(sim.lap_times))
    while sim.lap_index < end or sim.elapsed < sim.lap_start + 3:
        minfo.delta.lapDistance = sim.distance
        gen.send(reset)
        sim.tick()
        if sim.finished and sim.elapsed >= sim.lap_start + 3:
            break


def test_fuel_module_queues_saves_while_driving_and_writes_on_stop(fuel_sim, tmp_path, monkeypatch):
    saves: list[tuple[str, bool]] = []

    def spy(saver, *args, sync=False, **kwargs):
        saves.append((saver.__name__, sync))
        saver(*args, **kwargs)

    monkeypatch.setattr(module_fuel, "queue_save", spy)
    gen = module_fuel.calc_consumption(FuelInfo(), False, f"{tmp_path}/", ".fuel", 5, 0.75)
    drive(fuel_sim, gen, reset=0, laps=2)
    gen.send(1)  # vehicle reset while driving: reference lap saved (queued), then loaded back
    assert saves == [("save_fuel_delta_file", False)]
    drive(fuel_sim, gen, reset=1)  # rest of the lap in progress (partial, not a reference), then a full lap
    gen.send(MODULE_STOP)
    assert saves[-1] == ("save_fuel_delta_file", True)  # module stop: written before module reports stopped
    assert (tmp_path / "SimTrack - SimCar.fuel").exists()


# --- PERF-026: stint module reads a history file not accessible at load outside consumptionLock
@pytest.fixture
def history_env(monkeypatch):
    class Group(SimpleNamespace):
        def __init__(self, values, prefix):
            super().__init__()
            self._values, self._prefix = values, prefix

        def __getattr__(self, name):
            return lambda *args, **kwargs: self._values.get(f"{self._prefix}.{name}", 0)

    values = {"session.combo_name": "SimTrack - SimCar", "lap.completed_laps": 1}
    groups = ("session", "lap", "timing", "vehicle", "tyre")
    monkeypatch.setattr(api, "read", SimpleNamespace(**{name: Group(values, name) for name in groups}))
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(minfo, "delta", SimpleNamespace(lapTimeCurrent=5.0, lapTimeLast=90.0, isValidLap=True))
    monkeypatch.setattr(minfo, "fuel", SimpleNamespace(lastLapConsumption=3.0, capacity=100.0, lastLapPartial=False))
    monkeypatch.setattr(minfo, "energy", SimpleNamespace(lastLapConsumption=0.0))
    monkeypatch.setattr(minfo, "hybrid", SimpleNamespace(batteryDrainLast=0.0, batteryRegenLast=0.0))
    monkeypatch.setattr(minfo, "wheels", SimpleNamespace(lastLapTreadWear=(1.0, 1.0, 1.0, 1.0)))
    return values


def test_locked_history_read_outside_lock_then_merged(history_env, tmp_path, monkeypatch):
    history = HistoryInfo()
    reads: list[bool] = []  # lock held during each read
    saved = (ConsumptionDataSet(lapNumber=7, lapTimeLast=95.0, lastLapUsedFuel=3.1), ConsumptionDataSet())

    def read(filepath, filename, extension=".consumption", backup=False):
        reads.append(history.consumptionLock.locked())
        return ((ConsumptionDataSet(),), False) if len(reads) == 1 else (saved, True)  # locked at load only

    monkeypatch.setattr(module_stint, "read_consumption_history_file", read)
    gen = module_stint.record_consumption_history(history, f"{tmp_path}/")
    gen.send(0)  # load (file locked), lap 1 recorded
    assert history.consumptionDataSet[0].lapNumber == 1
    gen.send(1)  # reset: file read again (readable now) & merged, history written, then loaded back
    assert reads == [False, False, False]  # Race Calculator (UI thread) never waits for the disk under the lock
    from neopedal.userfile.consumption_history import load_consumption_history_file

    laps = load_consumption_history_file(f"{tmp_path}/", "SimTrack - SimCar")
    assert [lap.lapNumber for lap in laps] == [1, 7]  # recorded lap, then laps of the file kept


# --- PERF-015 / PERF-025: lap file streamed into the temporary file, same bytes as before
def lap_rows(count: int) -> list[tuple]:
    return [(index * 0.02, index * 0.02, index * 1.5, 100.0 + index, *([0.0] * (len(module_recorder.CSV_HEADER) - 4)))
            for index in range(count)]


@pytest.mark.parametrize("compress", [False, True])
def test_write_lap_file_streams_same_content(tmp_path, compress, monkeypatch):
    rows, info = lap_rows(600), {"kind": "lap", "track": "Le Mans"}
    expected = module_recorder.lap_text(rows, info).encode("utf-8")
    flushed: list = []
    monkeypatch.setattr(module_recorder, "flush_to_disk", lambda file: flushed.append(file.name))
    target = str(tmp_path / ("lap.csv.gz" if compress else "lap.csv"))
    assert module_recorder.write_lap_file(target, rows, info, compress)
    with open(target, "rb") as file:
        content = gzip.decompress(file.read()) if compress else file.read()
    assert content == expected
    assert len(flushed) == 1 and flushed[0].endswith(".tmp") and not list(tmp_path.glob("*.tmp"))


def test_save_lap_never_builds_whole_text(ui_env, tmp_path, monkeypatch):
    def no_text(*args, **kwargs):
        raise AssertionError("lap text materialized")

    monkeypatch.setattr(module_recorder, "lap_text", no_text)
    monkeypatch.setattr(module_recorder, "cache_lap", lambda *args: None)
    assert module_recorder.save_lap(str(tmp_path), "Track - GT3", 3, 95.0, lap_rows(50), 10, info={"kind": "lap"})
    files = list(tmp_path.rglob("*.csv"))
    assert len(files) == 1 and files[0].read_text(encoding="utf-8").startswith("# {")


def test_write_lap_file_error_removes_temp(tmp_path):
    assert not module_recorder.write_lap_file(str(tmp_path / "missing" / "lap.csv"), lap_rows(2))
    assert not list(tmp_path.rglob("*.tmp"))


# --- PERF-024: data modules imported on first use, not with the package
IMPORT_CHECK = """
import sys
import neopedal.module
assert "neopedal.module.module_recorder" not in sys.modules, "package imports every module"
from neopedal import module_control
assert "neopedal.module.module_recorder" not in sys.modules, "module_control imports every module"
assert "neopedal.module.module_stats" not in sys.modules
code, is_package = module_control.module_code("neopedal.module.module_recorder")
assert code is not None and not is_package, "code scan needs the module imported"
assert "neopedal.module.module_recorder" not in sys.modules
loaded = module_control.mctrl.module_of("module_sectors")
assert loaded.Realtime and "neopedal.module.module_sectors" in sys.modules
assert neopedal.module.module_delta.Realtime and neopedal.module.module_sectors is loaded
try:
    neopedal.module.module_nope
except AttributeError:
    pass
else:
    raise AssertionError("unknown module attribute")
print("ok")
"""


def test_data_modules_imported_on_first_use(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_CHECK], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0 and result.stdout.strip().endswith("ok"), result.stderr[-2000:]


# --- PERF-058: relative module follows scoring passes of vehicles module (snapshot read once, no race)
@pytest.fixture
def vehicles_updates(monkeypatch):
    fresh = _base.DerivedUpdates()
    for module in (_base, module_relative, module_vehicles):
        monkeypatch.setattr(module, "vehicles_updates", fresh)
    return fresh


def test_scoring_snapshot_followed_while_vehicles_module_runs(vehicles_updates):
    rows = tuple((False, False, 10.0 * index, "GT3", index + 1, 100.0, 101.0) for index in range(3))
    snapshot = ScoringSnapshot(600.0, rows)
    # Vehicles module stopped: only a snapshot of the current scoring sample
    assert module_relative.scoring_snapshot(snapshot, 3, 600.0) is snapshot
    assert module_relative.scoring_snapshot(snapshot, 3, 600.2) is None
    # Vehicles module running: its last pass followed even when game has a newer sample (woken by its publish)
    vehicles_updates.set_active(True)
    assert module_relative.scoring_snapshot(snapshot, 3, 600.2) is snapshot
    assert module_relative.scoring_snapshot(snapshot, 4, 600.0) is None  # car joined: read from game
    assert module_relative.scoring_snapshot(None, 3, 600.0) is None


def test_vehicles_module_publishes_scoring_pass(field, vehicles_updates):  # noqa: F811
    woken = threading.Event()
    vehicles_updates.subscribe(woken)
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, False, 600.0, True)  # high priority only
    assert vehicles_updates.sequence == 0 and not woken.is_set()
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.1, True)
    assert vehicles_updates.sequence == 1 and woken.is_set()
    assert field.scoringSnapshot is not None and len(field.scoringSnapshot.rows) == len(CARS)


def test_relative_module_woken_by_vehicles_publish(ui_env, vehicles_updates):
    module = module_relative.Realtime(cfg, "module_relative")
    assert module.WAKE_ON_VEHICLES
    module._max_wait = 0.3
    vehicles_updates.set_active(True)
    module._wake.set()  # game data notified: not what this module waits for now
    started = time.monotonic()
    threading.Timer(0.1, vehicles_updates.publish).start()
    module._event.clear()
    vehicles_updates.subscribe(module._wake_derived)  # as __tasks does
    assert module.wait_update(0.05) is False
    assert 0.08 <= time.monotonic() - started < 0.28  # woken by publish, not by game data nor max wait


# --- BUG-042: virtual energy stays available while driving, absent only after a while idle at 0
def test_energy_presence_never_drops_while_driving():
    presence = module_fuel.EnergyPresence()
    assert not presence.update(0.0, True, 0.0)  # car without virtual energy: never present
    assert presence.update(0.5, False, 1.0)
    assert presence.update(0.0, False, 2.0)  # energy run down (or telemetry not matched yet): kept
    assert presence.update(0.0, False, 60.0)
    assert presence.update(0.0, True, 61.0)  # stopped: countdown starts
    assert presence.update(0.0, True, 61.0 + module_fuel.ENERGY_ABSENT_DELAY - 0.1)
    assert presence.update(0.0, False, 62.0)  # moving again: countdown dropped
    assert presence.update(0.0, True, 63.0)
    assert not presence.update(0.0, True, 63.0 + module_fuel.ENERGY_ABSENT_DELAY)  # other car, in garage
    assert presence.update(0.9, True, 70.0)  # car with energy again


def test_energy_presence_starts_from_module_output():
    assert module_fuel.EnergyPresence(True).update(0.0, False, 0.0)  # module restarted mid-stint: kept


# --- BUG-043: lap time history of a car without telemetry (scoring lap start)
def test_lap_time_history_from_scoring_lap_start(field):  # noqa: F811
    sync = api._api._shmmapi
    data = sync._shmm.data
    scoring = data.scoring.vehScoringInfo[1]
    data.telemetry.telemInfo[1].mLapStartET = 0.0  # no telemetry for this car (EMPTY_TELE)
    scoring.mLapStartET = 500.0
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    assert field.dataSet[1].lapStartTime == 500.0
    scoring.mLapStartET = 596.0  # new lap, scoring only
    data.scoring.scoringInfo.mCurrentET = 605.0
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 605.0, True)
    assert field.dataSet[1].lapTimeHistory.last == pytest.approx(96.0)


# --- BUG-044: car count published once rows of every listed car are updated
def test_total_vehicles_published_after_rows(field):  # noqa: F811
    field.totalVehicles = len(CARS) - 1  # a car joins this tick
    real = module_vehicles.select_brand_name
    seen: list[tuple[int, int]] = []

    def brand_name(index, vehicle_name):  # called while the row of each car is filled
        seen.append((index, field.totalVehicles))
        return real(index, vehicle_name)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module_vehicles, "select_brand_name", brand_name)
        module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True, veh_total=len(CARS))
    assert (len(CARS) - 1, len(CARS) - 1) in seen  # joined car's row filled while old count still published
    assert field.totalVehicles == len(CARS) and field.dataSet[len(CARS) - 1].driverName == CARS[-1][0]
    assert field.playerIndex == 0


# --- BUG-024: battery charge (percent) of an electric car weighs nothing
def test_electric_car_has_no_fuel_weight(fuel_sim, tmp_path, monkeypatch):
    api.read.emotor.battery_charge = lambda index=None: 0.8
    monkeypatch.setattr(module_fuel, "detect_consumption_type", lambda is_energy: module_fuel.telemetry_battery)
    output = FuelInfo()
    gen = module_fuel.calc_consumption(output, False, f"{tmp_path}/", ".fuel", 5, 0.75)
    gen.send(0)
    assert output.amountCurrent == pytest.approx(80.0) and output.weight == 0.0
    monkeypatch.setattr(module_fuel, "detect_consumption_type", lambda is_energy: module_fuel.telemetry_fuel)
    gen = module_fuel.calc_consumption(output, False, f"{tmp_path}/", ".fuel", 5, 0.75)
    gen.send(0)
    assert output.weight == pytest.approx(0.75 * fuel_sim.fuel)
