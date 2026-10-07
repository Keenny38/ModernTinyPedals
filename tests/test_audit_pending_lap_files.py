"""Audit fixes: lap completed just before leaving track (back to garage at end of qualifying) still
validated & saved (delta best, fuel reference, driver stats, sectors); user files locked at load
(antivirus, cloud sync) never overwritten by worse or partial data"""

from __future__ import annotations

import builtins
import os
from types import SimpleNamespace

import pytest

from tests.telemetry_sim import LapSim, fake_reader
from tests.test_delta_session import STEP, TRACK, Driver, Game, lap_rows
from tinypedal import realtime_state, validator
from tinypedal.api_control import api
from tinypedal.const_common import DELTA_DEFAULT, MAX_SECONDS
from tinypedal.module import _base, module_fuel, module_sectors, module_stats, module_stint
from tinypedal.module._base import MODULE_STOP, PENDING_CHECK, PENDING_WAIT, PendingLap
from tinypedal.module_info import (
    ConsumptionDataSet,
    DeltaInfo,
    FuelInfo,
    HistoryInfo,
    SectorData,
    StatsInfo,
    VehiclesInfo,
    minfo,
)
from tinypedal.userfile import consumption_history, delta_best, driver_stats, sector_best
from tinypedal.userfile.consumption_history import (
    load_consumption_history_file,
    read_consumption_history_file,
    save_consumption_history_file,
)
from tinypedal.userfile.delta_best import (
    load_delta_best_file,
    read_delta_best_file,
    read_delta_session_file,
    save_delta_best_file,
)
from tinypedal.userfile.fuel_delta import load_fuel_delta_file
from tinypedal.userfile.sector_best import read_sector_best_file, save_sector_best_file


@pytest.fixture
def clock(monkeypatch):
    """Wall & monotonic clocks running with game time"""
    now = {"now": 10_000.0}
    monkeypatch.setattr(validator, "time", SimpleNamespace(time=lambda: now["now"]))
    monkeypatch.setattr(_base, "monotonic", lambda: now["now"])
    return now


class Group(SimpleNamespace):
    """Reader group: values from telemetry dict, unknown methods return 0"""

    def __init__(self, tele: dict, prefix: str):
        super().__init__()
        self._tele = tele
        self._prefix = prefix

    def __getattr__(self, name):
        key = f"{self._prefix}.{name}"
        return lambda *args, **kwargs: self._tele.get(key, 0)


@pytest.fixture
def tele(monkeypatch):
    """Scripted api.read: set tele["group.method"] values between generator steps"""
    values: dict = {
        "session.combo_name": "SimTrack - SimCar",
        "session.track_name": "SimTrack",
        "session.identifier": (1, 0, 0),
        "vehicle.class_name": "GT3",
    }
    groups = ("session", "lap", "timing", "vehicle", "tyre", "emotor", "engine", "inputs")
    monkeypatch.setattr(api, "read", SimpleNamespace(**{name: Group(values, name) for name in groups}))
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(realtime_state, "active", True)
    return values


class ModuleLoop:
    """Update loop of fuel, stats & sectors modules: generator fed while driving or once on vehicle reset,
    then with PENDING_CHECK while a lap waits for validation"""

    def __init__(self, gen, resets: int = 0):
        self.gen = gen
        self.resets = resets
        self.sent = None
        self.waiting = False

    def update(self):
        if realtime_state.active or self.sent != self.resets:
            self.sent = self.resets
            self.waiting = self.gen.send(self.resets)
        elif self.waiting:
            self.waiting = self.gen.send(PENDING_CHECK)


# --- Pending lap
def test_pending_lap_resolved_by_game_lap_time_or_deadline(tele, clock):
    lap = PendingLap(97.0, 100.0)
    tele["timing.last_laptime"] = 98.0  # previous lap: scoring not updated yet
    assert lap.resolve() is None and lap.deadline == clock["now"] + PENDING_WAIT
    tele["timing.last_laptime"] = 97.0004
    assert lap.resolve() is True
    lap = PendingLap(97.0, 100.0)
    tele["timing.last_laptime"] = -1.0  # invalid lap
    assert lap.resolve() is None
    assert lap.resolve(final=True) is False  # module stopping: never waits
    clock["now"] += PENDING_WAIT
    assert lap.resolve() is False


# --- Delta best
class LoopDriver(Driver):
    """Delta module fed as its update loop does: while driving, PENDING_CHECK while inactive & waiting"""

    waiting = False

    def tick(self, seconds: float = STEP):
        self.game.elapsed += seconds
        self.game.clock["now"] += seconds
        if realtime_state.active:
            self.output.lapDistance = self.game.distance
            self.waiting = self.gen.send(self.resets)
        elif self.waiting:
            self.waiting = self.gen.send(PENDING_CHECK)


@pytest.fixture
def delta_driver(monkeypatch, tmp_path, clock):
    game = Game(clock)
    monkeypatch.setattr(api, "read", game.reader())
    monkeypatch.setattr(realtime_state, "active", True)
    return LoopDriver(game, f"{tmp_path}/")


def finish_lap_and_leave(driver: LoopDriver, laptime: float, leave_after: float = 0.3, scoring_delay: float = 1.5,
                         garage_seconds: float = 5.0, valid: bool = True, active_in_garage: bool = False):
    """Cross the line, back to garage (escape) a moment later: game starts a new lap, last lap time later"""
    game = driver.game
    start = game.lap_start
    while game.elapsed + STEP - start < laptime:
        game.distance = (game.elapsed - start) / laptime * TRACK
        driver.tick()
    driver.tick(start + laptime - game.elapsed)  # finish line
    line = game.elapsed
    game.lap_start = line
    game.distance = 0.0
    game.laps += 1
    while game.elapsed - line < leave_after:
        driver.tick()
    # Back to garage: player inactive (or still active in garage), vehicle reset, new lap started
    realtime_state.active = active_in_garage
    driver.resets += 1
    game.lap_start = game.elapsed
    game.in_pits, game.speed, game.distance = True, 0.0, -245.0
    while game.elapsed - line < garage_seconds:
        if valid and game.elapsed - line >= scoring_delay:
            game.last_laptime = laptime
        driver.tick()


def delta_best_laptime(driver: LoopDriver) -> float:
    return load_delta_best_file(driver.folder, "Track - GT3", (DELTA_DEFAULT, MAX_SECONDS))[1]


def test_delta_best_saved_when_leaving_just_after_line(delta_driver):
    driver = delta_driver
    for laptime in (100.0, 98.0):  # first lap partial (not timed)
        driver.lap(laptime)
    assert driver.output.lapTimeBest == 98.0
    finish_lap_and_leave(driver, 97.0)
    assert not driver.waiting  # validated while inactive
    assert delta_best_laptime(driver) == 97.0
    realtime_state.active = True  # back on track: data reset & reloaded
    driver.tick()
    assert driver.output.lapTimeBest == 97.0
    assert driver.output.lapTimeSession == 97.0  # (stint best reset: stopped in garage)


def test_delta_best_saved_when_reset_seen_while_active(delta_driver):
    """Still active in garage: reset waits for validation of lap just completed (not the garage lap)"""
    driver = delta_driver
    for laptime in (100.0, 98.0):
        driver.lap(laptime)
    finish_lap_and_leave(driver, 97.0, active_in_garage=True)
    assert delta_best_laptime(driver) == 97.0
    assert driver.output.lapTimeBest == 97.0 and driver.output.lapTimeSession == 97.0


def test_delta_lap_never_validated_waits_bounded_time(delta_driver):
    driver = delta_driver
    for laptime in (100.0, 98.0):
        driver.lap(laptime)
    finish_lap_and_leave(driver, 97.0, valid=False, active_in_garage=True, garage_seconds=3.0)
    assert driver.waiting  # reset delayed while lap may still be validated
    finish_time = driver.game.elapsed
    while driver.game.elapsed - finish_time < PENDING_WAIT:
        driver.tick()
    assert not driver.waiting
    assert driver.output.lapTimeBest == 98.0 and delta_best_laptime(driver) == 98.0


def test_delta_lap_validated_on_module_stop(delta_driver):
    driver = delta_driver
    for laptime in (100.0, 98.0):
        driver.lap(laptime)
    finish_lap_and_leave(driver, 97.0, scoring_delay=10.0, garage_seconds=0.5)
    assert driver.waiting
    driver.game.last_laptime = 97.0
    driver.gen.send(MODULE_STOP)  # app closed in garage
    assert delta_best_laptime(driver) == 97.0


# --- Fuel reference consumption
class LaggedSim(LapSim):
    """Game last lap time updated a moment after the line (scoring slower than telemetry)"""

    def __init__(self, *args, lag: float = 1.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.lag = lag
        self.previous_laptime = -1.0

    def tick(self):
        last = self.last_laptime
        super().tick()
        if last != self.last_laptime:
            self.previous_laptime = last

    def reported_laptime(self) -> float:
        if self.elapsed - self.lap_start < self.lag:
            return self.previous_laptime
        return self.last_laptime


@pytest.fixture
def fuel_sim(monkeypatch, clock):
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(minfo, "delta", DeltaInfo())
    monkeypatch.setattr(minfo, "vehicles", VehiclesInfo())
    sim = LaggedSim([90.0] * 3, fuel_per_lap=[3.0, 3.0, 2.8])
    reader = fake_reader(sim)
    reader.timing.last_laptime = lambda index=None: sim.reported_laptime()
    monkeypatch.setattr(api, "read", reader)
    return sim


def test_fuel_reference_saved_when_leaving_just_after_line(fuel_sim, tmp_path, clock):
    sim = fuel_sim
    gen = module_fuel.calc_consumption(FuelInfo(), False, f"{tmp_path}/", ".fuel", 5, 0.75)
    loop = ModuleLoop(gen)

    def step():
        minfo.delta.lapDistance = sim.distance
        loop.update()
        sim.tick()
        clock["now"] += sim.step

    while not sim.finished or sim.elapsed < sim.lap_start + 0.2:  # last lap done 0.2s ago
        step()
    realtime_state.active = False  # back to garage
    loop.resets += 1
    for _ in range(150):  # 3s in garage
        step()
    assert not loop.waiting
    _, used_last, _ = load_fuel_delta_file(f"{tmp_path}/", "SimTrack - SimCar", ".fuel", ((), 0.0, 0.0))
    assert used_last == pytest.approx(2.8, abs=0.01)  # last lap, not lap before (3.0)


# --- Driver stats
def drive_stats_lap(tele: dict, loop: ModuleLoop, lap_start: float, laptime: float, report: bool = True):
    """Drive a lap in 3 steps, then cross the line (game last lap time reported at line if report)"""
    for step in range(1, 4):
        tele.update({
            "timing.elapsed": lap_start + laptime * step / 3,
            "vehicle.position_xyz": (1000.0 * (lap_start / laptime * 3 + step), 0.0, 0.0),
        })
        loop.update()
    tele["timing.start"] = lap_start + laptime
    tele["timing.elapsed"] = lap_start + laptime + 0.3
    if report:
        tele["timing.last_laptime"] = laptime
    loop.update()


def test_driver_stats_best_lap_saved_when_leaving_just_after_line(tele, tmp_path, clock):
    tele.update({
        "timing.start": 0.0, "timing.elapsed": 0.0, "timing.last_laptime": -1.0, "vehicle.speed": 50.0,
        "vehicle.position_xyz": (0.0, 0.0, 0.0), "engine.fuel": 50.0, "session.session_type": 2,
    })
    filepath = f"{tmp_path}/"
    gen = module_stats.record_driver_stats(StatsInfo(), filepath, "Class", 1500, False)
    loop = ModuleLoop(gen, resets=1)
    loop.update()
    drive_stats_lap(tele, loop, 0.0, 90.0)
    tele["timing.elapsed"] = 93.0  # lap counted 2s after line
    loop.update()
    drive_stats_lap(tele, loop, 90.0, 89.0, report=False)  # new personal best, scoring not updated yet
    realtime_state.active = False  # back to garage
    loop.resets += 1
    loop.update()
    assert loop.waiting
    tele["timing.last_laptime"] = 89.0
    clock["now"] += 1.0
    loop.update()
    assert not loop.waiting
    stats = driver_stats.load_driver_stats(("SimTrack", "GT3"), filepath)
    assert stats.valid == 2
    assert stats.pb == pytest.approx(89.0) and stats.qb == pytest.approx(89.0)


# --- Sectors
def test_sector3_saved_when_leaving_just_after_line(tele, tmp_path, clock):
    tele.update({
        "timing.start": 0.0, "timing.current_laptime": 5.0, "lap.sector_index": 0,
        "timing.last_laptime": -1.0, "timing.last_sector2": -1.0,
    })
    filepath = f"{tmp_path}/"
    loop = ModuleLoop(module_sectors.record_sectors(SectorData(), SectorData(), filepath))
    loop.update()
    tele.update({"lap.sector_index": 1, "timing.current_sector1": 30.0})
    loop.update()
    tele.update({"lap.sector_index": 2, "timing.current_sector2": 70.0})
    loop.update()
    # Line crossed, game lap time & sector 2 of lap not reported yet
    tele.update({"timing.start": 90.0, "timing.current_laptime": 0.2, "lap.sector_index": 0,
                 "timing.current_sector1": -1.0, "timing.current_sector2": -1.0})
    loop.update()
    realtime_state.active = False  # back to garage
    loop.resets += 1
    loop.update()
    assert loop.waiting
    tele.update({"timing.last_laptime": 90.0, "timing.last_sector2": 70.0})
    loop.update()
    assert not loop.waiting
    (_, _, alltime_tb, alltime_pb), _ = read_sector_best_file(
        filepath, "SimTrack - SimCar", (1, 0, 0), (MAX_SECONDS,) * 3)
    assert alltime_tb == pytest.approx([30.0, 40.0, 20.0])
    assert alltime_pb == pytest.approx([30.0, 40.0, 20.0])


# --- Locked files
def lock_file(monkeypatch, module, path) -> dict:
    """File of path not accessible (locked by antivirus, cloud sync) by module while state["locked"]"""
    state = {"locked": True}
    real_open = builtins.open
    target = os.path.abspath(path)

    def fake_open(file, *args, **kwargs):
        if state["locked"] and os.path.abspath(str(file)) == target:
            raise PermissionError(13, "file locked", str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(module, "open", fake_open, raising=False)
    return state


def test_readers_tell_locked_from_missing_file(tmp_path, monkeypatch):
    folder = f"{tmp_path}/"
    save_delta_best_file(folder, "Locked", lap_rows(95.0))
    (tmp_path / "Locked.session").write_text("{}", encoding="utf-8")
    lock_file(monkeypatch, delta_best, tmp_path / "Locked.csv")
    lock_file(monkeypatch, sector_best, tmp_path / "Locked.sector")
    (tmp_path / "Locked.sector").write_text("", encoding="utf-8")
    assert read_delta_best_file(folder, "Locked", ("default", 0.0)) == (("default", 0.0), False)
    assert read_delta_best_file(folder, "Missing", ("default", 0.0)) == (("default", 0.0), True)
    assert read_sector_best_file(folder, "Locked", (1, 0, 0), (1.0, 2.0, 3.0))[1] is False
    assert read_sector_best_file(folder, "Missing", (1, 0, 0), (1.0, 2.0, 3.0))[1] is True
    assert read_delta_session_file(folder, "Missing", (1, 0, 0, 0), 0)[1] is True
    assert load_delta_best_file(folder, "Locked", ("default", 0.0)) == ("default", 0.0)  # former signature


def test_invalid_delta_best_file_backed_up_once(tmp_path):
    folder = f"{tmp_path}/"
    (tmp_path / "Bad.csv").write_text("not,a,delta\n", encoding="utf-8")
    for _ in range(3):  # loaded at each vehicle reset
        assert read_delta_best_file(folder, "Bad", ("default", 0.0), backup=True) == (("default", 0.0), True)
    assert len([name for name in os.listdir(tmp_path) if name.startswith("Bad.csv.")]) == 1


def test_locked_delta_best_never_replaced_by_slower_lap(delta_driver, monkeypatch, tmp_path):
    folder = f"{tmp_path}/"
    save_delta_best_file(folder, "Track - GT3", lap_rows(95.0))
    lock = lock_file(monkeypatch, delta_best, tmp_path / "Track - GT3.csv")
    driver = delta_driver
    driver.start_module()  # all time best not accessible: none in module
    for laptime in (100.0, 98.0):
        driver.lap(laptime)
    assert driver.output.lapTimeBest == 98.0
    lock["locked"] = False
    assert delta_best_laptime(driver) == 95.0  # still locked when 98 s lap was saved: file kept
    driver.lap(97.0)  # file readable again: its faster lap kept & used
    assert delta_best_laptime(driver) == 95.0 and driver.output.lapTimeBest == 95.0
    driver.lap(94.0)
    assert delta_best_laptime(driver) == 94.0 and driver.output.lapTimeBest == 94.0


def test_missing_delta_best_created(delta_driver):
    for laptime in (100.0, 98.0):
        delta_driver.lap(laptime)
    assert delta_best_laptime(delta_driver) == 98.0


def test_locked_sector_file_merged_never_replaced(tele, tmp_path, monkeypatch):
    from tests.test_module_timing import drive_sectors

    folder = f"{tmp_path}/"
    best = [28.0, 38.0, 18.0]
    save_sector_best_file(folder, "SimTrack - SimCar", (9, 0, 0), best, best, best, best)
    lock = lock_file(monkeypatch, sector_best, tmp_path / "SimTrack - SimCar.sector")
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, folder)
    drive_sectors(tele, gen, [(30.0, 40.0, 20.0), (29.0, 41.0, 19.5)])
    gen.send(1)  # saved on reset: still locked, not saved
    lock["locked"] = False
    assert read_sector_best_file(folder, "SimTrack - SimCar", (1, 0, 0), (MAX_SECONDS,) * 3)[0][2] == best
    lock["locked"] = True
    gen.send(2)  # reloaded: still locked
    drive_sectors(tele, gen, [(27.0, 40.0, 20.0), (29.0, 41.0, 19.5)])
    lock["locked"] = False  # readable again when saved: best sectors of file kept
    gen.send(3)
    (_, _, alltime_tb, alltime_pb), _ = read_sector_best_file(
        folder, "SimTrack - SimCar", (1, 0, 0), (MAX_SECONDS,) * 3)
    assert alltime_tb == [27.0, 38.0, 18.0]  # new S1 best only
    assert alltime_pb == best  # personal best lap of file faster


def test_missing_sector_file_created(tele, tmp_path):
    from tests.test_module_timing import drive_sectors

    gen = module_sectors.record_sectors(SectorData(), SectorData(), f"{tmp_path}/")
    drive_sectors(tele, gen, [(30.0, 40.0, 20.0), (29.0, 41.0, 19.5)])
    gen.send(1)
    assert (tmp_path / "SimTrack - SimCar.sector").exists()


@pytest.fixture
def history_env(tele, monkeypatch):
    monkeypatch.setattr(minfo, "delta", SimpleNamespace(lapTimeCurrent=5.0, lapTimeLast=90.0, isValidLap=True))
    monkeypatch.setattr(minfo, "fuel", SimpleNamespace(lastLapConsumption=3.0, capacity=100.0))
    monkeypatch.setattr(minfo, "energy", SimpleNamespace(lastLapConsumption=0.0))
    monkeypatch.setattr(minfo, "hybrid", SimpleNamespace(batteryDrainLast=0.0, batteryRegenLast=0.0))
    monkeypatch.setattr(minfo, "wheels", SimpleNamespace(lastLapTreadWear=(1.0, 1.0, 1.0, 1.0)))
    return tele


SAVED_LAPS = [ConsumptionDataSet(lapNumber=number, lapTimeLast=90.0 + number, lastLapUsedFuel=3.0)
              for number in (3, 2, 1)]


def test_locked_consumption_history_never_replaced(history_env, tmp_path, monkeypatch):
    folder = f"{tmp_path}/"
    save_consumption_history_file(SAVED_LAPS, folder, "SimTrack - SimCar")
    lock = lock_file(monkeypatch, consumption_history, tmp_path / "SimTrack - SimCar.consumption")
    history = HistoryInfo()
    gen = module_stint.record_consumption_history(history, folder)
    history_env["lap.number"] = 10
    gen.send(0)
    minfo.delta.lapTimeCurrent = 20.0  # no lap recorded after reset
    gen.send(1)  # saved on reset: still locked, not saved
    lock["locked"] = False
    assert load_consumption_history_file(folder, "SimTrack - SimCar") == tuple(SAVED_LAPS)
    lock["locked"] = True
    gen.send(2)  # reloaded: still locked
    history_env["lap.number"] = 11
    minfo.delta.lapTimeCurrent = 5.0
    gen.send(2)
    minfo.delta.lapTimeCurrent = 20.0
    lock["locked"] = False  # readable again when saved: laps of file kept
    gen.send(3)
    laps = load_consumption_history_file(folder, "SimTrack - SimCar")
    assert [lap.lapNumber for lap in laps] == [11, 3, 2, 1]
    assert [lap.lapNumber for lap in history.consumptionDataSet] == [11, 3, 2, 1]


def test_missing_consumption_history_created(history_env, tmp_path):
    history = HistoryInfo()
    gen = module_stint.record_consumption_history(history, f"{tmp_path}/")
    history_env["lap.number"] = 1
    gen.send(0)
    gen.send(1)
    laps, readable = read_consumption_history_file(f"{tmp_path}/", "SimTrack - SimCar")
    assert readable and laps[0].lapNumber == 1
