"""Core fixes 2026-10-18: stint history per combo, refuel consumption rate, no stale leader index,
unqualified cars last, regen up to full battery, tyre trend per car & session, BOM settings file,
atomic single instance lock"""

import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from neopedal import main, realtime_state
from neopedal.api_control import api
from neopedal.const_common import MAX_SECONDS
from neopedal.module import module_fuel, module_hybrid, module_stint, module_vehicles
from neopedal.module_info import DeltaInfo, FuelInfo, HistoryInfo, HybridInfo, VehicleDataSet, VehiclesInfo, minfo
from neopedal.widget.tyre_temp_trend import TemperatureTrend
from tests.test_module_vehicles_field import CARS, field  # noqa: F401 (field: fixture)
from tests.test_race_aid_widgets import field as race_field  # noqa: F401 (fixture)
from tests.test_race_aid_widgets import make, set_reader


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
        "session.combo_name": "SimTrack - LMP2",
        "session.pre_race": False,
        "tyre.wear": (1.0, 1.0, 1.0, 1.0),
        "tyre.compound_class": ("", "", "", ""),
        "tyre.carcass_temperature": (80.0, 80.0, 80.0, 80.0),
    }
    groups = ("session", "lap", "timing", "vehicle", "tyre", "emotor", "engine", "inputs")
    monkeypatch.setattr(api, "read", SimpleNamespace(**{name: Group(values, name) for name in groups}))
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(realtime_state, "active", True)
    return values


# --- 1. Stint history kept per combo (track & class), across sessions of same combo
@pytest.fixture
def stint_env(tele, monkeypatch):
    monkeypatch.setattr(minfo, "fuel", SimpleNamespace(amountCurrent=50.0))
    monkeypatch.setattr(minfo, "energy", SimpleNamespace(amountCurrent=0.0))
    monkeypatch.setattr(module_stint, "select_compound_symbol", lambda name: "S")
    return tele


def drive_stint(tele: dict, gen, laps: int, reset: int, start_time: float = 0.0) -> float:
    """Drive laps of 90 s on track (2 L per lap), one generator step per lap plus one at start"""
    elapsed = start_time
    tele.update({"vehicle.in_pits": False, "vehicle.speed": 60.0, "timing.start": elapsed,
                 "session.elapsed": elapsed, "lap.number": 0})
    gen.send(reset)
    for lap in range(1, laps + 1):
        elapsed += 90.0
        minfo.fuel.amountCurrent -= 2.0
        tele.update({"timing.start": elapsed, "session.elapsed": elapsed, "lap.number": lap})
        gen.send(reset)
    return elapsed


def saved_stints(history: HistoryInfo) -> list[int]:
    return [stint.totalLaps for stint in history.stintDataSet if stint.totalLaps > 0]


def test_stints_kept_when_session_changes_on_same_combo(stint_env):
    history = HistoryInfo()
    gen = module_stint.record_stint_history(history, 60, 3, 50)
    drive_stint(stint_env, gen, 3, reset=0)  # practice
    drive_stint(stint_env, gen, 2, reset=1)  # race: practice stint saved on reset
    drive_stint(stint_env, gen, 1, reset=2)
    assert saved_stints(history) == [2, 3]


def test_stints_cleared_when_combo_changes(stint_env):
    history = HistoryInfo()
    gen = module_stint.record_stint_history(history, 60, 3, 50)
    drive_stint(stint_env, gen, 3, reset=0)
    drive_stint(stint_env, gen, 3, reset=1)
    assert saved_stints(history) == [3]
    version = history.stintDataVersion
    shown = history.stintDataSet  # held by GUI: never changed in place
    stint_env["session.combo_name"] = "OtherTrack - LMP2"
    drive_stint(stint_env, gen, 1, reset=2)  # stint driven on previous combo dropped too
    assert saved_stints(history) == []
    assert history.stintDataVersion > version  # overlays redraw
    assert saved_stints(SimpleNamespace(stintDataSet=shown)) == [3]
    assert history.stintDataCurrent.totalLaps == 1  # current stint of new combo
    stint_env["session.combo_name"] = "OtherTrack - GT3"  # other class: other combo
    drive_stint(stint_env, gen, 4, reset=3)
    drive_stint(stint_env, gen, 1, reset=4)
    assert saved_stints(history) == [4]  # stint of this combo only


def test_stint_combo_read_once_driving(stint_env, monkeypatch):
    """Reset while not driving: combo checked once driving (game data of new session loaded)"""
    history = HistoryInfo()
    gen = module_stint.record_stint_history(history, 60, 3, 50)
    drive_stint(stint_env, gen, 3, reset=0)
    drive_stint(stint_env, gen, 1, reset=1)
    monkeypatch.setattr(realtime_state, "active", False)
    stint_env["session.combo_name"] = ""  # no game data
    gen.send(2)
    assert saved_stints(history) == [1, 3]  # combo unknown yet
    stint_env["session.combo_name"] = "OtherTrack - LMP2"
    monkeypatch.setattr(realtime_state, "active", True)
    gen.send(2)
    assert saved_stints(history) == []


def test_reset_stint_never_reuses_a_version():
    history = HistoryInfo()
    history.stintDataVersion = 3
    history.reset_stint()
    assert history.stintDataVersion == 4 and len(history.stintDataSet) == 1


# --- 2. Consumption rate never negative while refuelling
@pytest.fixture
def fuel_env(tele, monkeypatch):
    tele.update({"engine.tank_capacity": 100.0, "engine.fuel": 60.0, "timing.elapsed": 20.0,
                 "vehicle.speed": 50.0})
    monkeypatch.setattr(minfo, "delta", DeltaInfo())
    monkeypatch.setattr(minfo, "vehicles", VehiclesInfo())
    return tele


def test_refuel_rate_zero_regen_rate_kept(fuel_env, tmp_path):
    output = FuelInfo()
    gen = module_fuel.calc_consumption(output, False, f"{tmp_path}/", ".fuel", 10.0, 0.0)
    gen.send(0)

    def step(elapsed: float, fuel: float, speed: float) -> float:
        fuel_env.update({"timing.elapsed": elapsed, "engine.fuel": fuel, "vehicle.speed": speed})
        gen.send(0)
        return output.rateOfConsumption

    assert step(21.0, 59.5, 50.0) == pytest.approx(0.5)
    assert step(22.0, 59.5, 0.0) == pytest.approx(0.0)  # stopped in pits
    assert step(23.0, 64.5, 0.0) == 0.0  # refuelling: no negative rate
    assert step(24.0, 69.5, 0.0) == 0.0
    assert step(25.0, 68.5, 50.0) == pytest.approx(1.0)
    assert step(26.0, 68.8, 50.0) == pytest.approx(-0.3)  # regen while moving: negative, as before


# --- 3. Leader index never stale
def test_no_leader_found_resets_leader_index(field):  # noqa: F811
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    assert field.leaderIndex == 1
    data = api._api._shmmapi._shmm.data
    data.scoring.vehScoringInfo[1].mPlace = 5  # no place 1 in scoring (other session starting)
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.1, True)
    assert field.leaderIndex == -1 and field.leaderBestLapTime == MAX_SECONDS
    data.scoring.vehScoringInfo[1].mPlace = 1
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, False, 600.2, True)  # high priority only
    assert field.leaderIndex == -1  # leader read with low priority data
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.3, True)
    assert field.leaderIndex == 1


def test_leader_index_default_and_reset():
    output = VehiclesInfo()
    assert output.leaderIndex == -1
    output.leaderIndex, output.leaderBestLapTime = 3, 90.0
    module_vehicles.reset_leader(output)
    assert output.leaderIndex == -1 and output.leaderBestLapTime == MAX_SECONDS


class NoNegativeIndex(list):
    """Vehicle data set where a negative index (stale "no car" index) fails the test"""

    def __getitem__(self, index):
        if isinstance(index, int) and index < 0:
            raise AssertionError(f"vehicle data read at index {index}")
        return super().__getitem__(index)


@pytest.mark.parametrize("finish_type", [0, 1, 2])
def test_finish_time_without_leader(ui_env, monkeypatch, finish_type):
    output = VehiclesInfo()
    output.dataSet = NoNegativeIndex(VehicleDataSet() for _ in range(3))  # type: ignore[assignment]
    output.totalVehicles = 3
    output.playerIndex = 0
    monkeypatch.setattr(api.read.session, "finish_type", lambda: finish_type)
    monkeypatch.setattr(api.read.session, "remaining", lambda: 600.0)
    monkeypatch.setattr(minfo.delta, "lapTimePace", 100.0)
    module_vehicles.update_finish_time(output, 30.0)
    assert output.finishLapOffset == 0.0 and output.finishLapOffsetLeader == 0.0


@pytest.mark.parametrize(("name", "modern"), [
    ("relative_finish_order", True), ("relative_finish_order", False), ("traffic", False),  # modern traffic: checked
])
def test_widgets_without_leader(race_field, monkeypatch, name, modern):  # noqa: F811
    minfo.vehicles.dataSet = NoNegativeIndex(minfo.vehicles.dataSet)
    minfo.vehicles.leaderIndex = -1

    def progress(index=None):
        assert index is None or index >= 0
        return 0.5

    set_reader(monkeypatch, "lap", "progress", progress)
    set_reader(monkeypatch, "timing", "estimated_laptime", 0.0)
    widget = make(name, modern)
    widget.timerEvent(None)
    widget.deleteLater()


# --- 4. Unqualified cars (qualification 0 or -1) after qualified ones
def test_unqualified_cars_placed_last(field):  # noqa: F811
    cars_info = api._api._shmmapi._shmm.data.scoring.vehScoringInfo
    cars_info[1].mQualification = 0  # leader joined late: not qualified
    cars_info[2].mQualification = -1  # invalid
    module_vehicles.update_qualify_position(field)
    cars = field.dataSet[:len(CARS)]
    # Qualified: player 3rd, slow car 4th; unqualified after them, in vehicle order
    assert [car.qualifyOverall for car in cars] == [3, 5, 6, 4]
    assert [car.qualifyInClass for car in cars] == [1, 2, 2, 1]


def test_no_car_qualified(field):  # noqa: F811
    for car in api._api._shmmapi._shmm.data.scoring.vehScoringInfo[:len(CARS)]:
        car.mQualification = 0
    module_vehicles.update_qualify_position(field)
    cars = field.dataSet[:len(CARS)]
    assert [car.qualifyOverall for car in cars] == [1, 2, 3, 4]
    assert [car.qualifyInClass for car in cars] == [1, 2, 1, 2]


# --- 5. Regen of the step reaching a full battery counted
def drive_hybrid(tele: dict, gen, charges: list[float], states: list[int], elapsed: float = 0.0) -> float:
    for charge, state in zip(charges, states):
        elapsed += 1.0
        tele.update({"timing.elapsed": elapsed, "emotor.battery_charge": charge / 100, "emotor.state": state,
                     "timing.current_laptime": elapsed, "lap.distance": elapsed * 50})
        gen.send(0)
    return elapsed


def test_regen_up_to_full_battery_counted(tele):
    output = HybridInfo()
    gen = module_hybrid.calc_motor(output, min_delta_distance=5)
    drive_hybrid(tele, gen, [96, 98, 100, 100], [3] * 4)
    assert output.batteryRegen == pytest.approx(4.0)


# --- 6. Tyre temperature trend of one car in one session
def test_trend_cleared_when_car_or_session_changes():
    trend = TemperatureTrend(60.0, False, 5)
    trend.follow((1, 7, "Car A"))
    for step in range(10):
        trend.update(100.0 + step, 3, (80.0,) * 4)
    assert len(trend.samples[0]) == 10
    trend.follow((1, 7, "Car A"))  # same car & session: kept
    assert len(trend.samples[0]) == 10
    trend.follow((1, 7, "Car B"))  # other car
    assert not trend.samples[0]
    trend.update(200.0, 3, (80.0,) * 4)
    trend.follow((2, 7, "Car B"))  # other session, starting at later elapsed time
    trend.update(300.0, 0, (80.0,) * 4)
    assert len(trend.samples[0]) == 1
    laps = TemperatureTrend(60.0, True, 3)
    laps.follow((1, 7, "Car A"))
    for lap in range(3):
        for step in range(3):
            laps.update(lap * 10 + step, lap, (70.0,) * 4)
    assert len(laps.samples[0]) == 2
    laps.follow((1, 8, "Car A"))  # other slot (spectated car)
    laps.update(100.0, 3, (70.0,) * 4)
    laps.update(110.0, 4, (70.0,) * 4)  # first lap of new car not averaged with laps of previous one
    assert len(laps.samples[0]) == 1


@pytest.mark.parametrize("modern", [True, False])
def test_tyre_trend_widget_follows_car(race_field, monkeypatch, modern):  # noqa: F811
    clock = {"elapsed": 0.0}
    car = {"name": "Car A"}
    set_reader(monkeypatch, "timing", "elapsed", lambda *args, **kwargs: clock["elapsed"])
    set_reader(monkeypatch, "tyre", "surface_temperature_avg", (80.0, 80.0, 80.0, 80.0))
    set_reader(monkeypatch, "vehicle", "vehicle_name", lambda *args, **kwargs: car["name"])
    widget = make("tyre_temp_trend", modern, trend_duration=60)
    for step in range(5):
        clock["elapsed"] = 1000.0 + step * 2
        widget.timerEvent(None)
    assert len(widget.trend.samples[0]) == 5
    car["name"] = "Car B"  # vehicle name read again only after a vehicle reset
    widget.timerEvent(None)
    assert len(widget.trend.samples[0]) == 5
    monkeypatch.setattr(realtime_state, "resets", realtime_state.resets + 1)
    clock["elapsed"] = 2000.0  # later elapsed time: never seen as a restart
    widget.timerEvent(None)
    assert len(widget.trend.samples[0]) == 1
    widget.deleteLater()


# --- 7. Race results page settings read with BOM
def test_chosen_results_folder_with_bom(tmp_path):
    from neopedal.process import results_file

    results_file.forget_lookups()
    (tmp_path / results_file.PAGE_SETTINGS_FILE).write_text('\ufeff{"folder": "D:/Results"}', encoding="utf-8")
    assert results_file.chosen_results_folder(f"{tmp_path}/") == "D:/Results"


# --- 8. Single instance: one atomic OS lock per config folder
HOLDER = """
import os, sys
name, path = sys.argv[1], sys.argv[2]
if sys.platform == "win32":
    import ctypes
    handle = ctypes.WinDLL("kernel32").CreateMutexW(None, False, "Local" + chr(92) + name)
else:
    import fcntl
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
print("locked", flush=True)
sys.stdin.readline()
"""


def release_lock():
    lock = main._instance_lock
    if lock is None:
        return
    if sys.platform == "win32":
        import ctypes

        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(lock))
    else:
        os.close(lock)
    main._instance_lock = None


@pytest.fixture
def instance(ui_env, monkeypatch):
    """Lock taken during test released after it (kept until process ends otherwise), config folder of test"""
    monkeypatch.setattr(main, "_instance_lock", None)
    monkeypatch.setattr(realtime_state, "singleton", realtime_state.singleton)
    monkeypatch.delenv("NEOPEDAL_RESTART", raising=False)
    yield
    release_lock()


@contextmanager
def other_instance():
    """Lock of config folder held by another process until context exits"""
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, main.instance_lock_name(), main.instance_lock_file()],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "locked"
        yield process
    finally:
        process.stdin.close()
        process.wait(10)


def refused(monkeypatch) -> list:
    """Already running dialog shown instead of starting"""
    shown: list = []
    monkeypatch.setattr(main, "QApplication", lambda args: SimpleNamespace(setWindowIcon=lambda icon: None,
                                                                            setDesktopFileName=lambda name: None))
    monkeypatch.setattr(main.QMessageBox, "warning", lambda *args: shown.append(args[2]))
    return shown


def test_lock_taken_once(instance):
    assert not main.other_instance_running()
    assert main.acquire_instance_lock()
    assert main._instance_lock is not None
    held = main._instance_lock
    assert not main.lock_instance()  # second try (as another instance would) fails
    assert main._instance_lock == held
    assert main.other_instance_running()  # probe never takes the lock
    release_lock()
    assert not main.other_instance_running()
    assert main.lock_instance()


def test_instances_started_together_only_one_gets_lock(instance):
    """Check & take in one step: lock taken by exactly one of instances racing for it"""
    barrier = threading.Barrier(8)
    results: list[bool] = []

    def start():
        barrier.wait()
        results.append(main.lock_instance())

    threads = [threading.Thread(target=start) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(results) == [False] * 7 + [True]


def test_second_instance_refused_until_first_exits(instance, monkeypatch):
    shown = refused(monkeypatch)
    with other_instance():
        assert main.other_instance_running()
        with pytest.raises(SystemExit):
            main.single_instance_check(True)
        assert "already running" in shown[0] and main._instance_lock is None
    main.single_instance_check(True)  # first instance exited: lock released by OS
    assert realtime_state.singleton and main._instance_lock is not None


def test_restarted_instance_waits_for_previous_one(instance, monkeypatch):
    refused(monkeypatch)
    monkeypatch.setenv("NEOPEDAL_RESTART", "TRUE")
    with other_instance() as previous:
        timer = threading.Timer(0.3, previous.stdin.close)  # previous instance exits a moment later
        timer.start()
        main.single_instance_check(True)
        timer.join()
    assert main._instance_lock is not None and "NEOPEDAL_RESTART" not in os.environ


def test_restarted_instance_let_in_if_previous_one_stays(instance, monkeypatch, caplog):
    monkeypatch.setattr(main, "INSTANCE_LOCK_RESTART_WAIT", 0.2)
    monkeypatch.setenv("NEOPEDAL_RESTART", "TRUE")
    with other_instance(), caplog.at_level("WARNING", logger="neopedal"):
        main.single_instance_check(True)  # never refused
    assert main._instance_lock is None and "started anyway" in caplog.text


def test_single_instance_off_takes_no_lock(instance, monkeypatch):
    monkeypatch.setattr(realtime_state, "singleton", True)
    main.single_instance_check(False)
    assert not realtime_state.singleton and main._instance_lock is None
    assert not main.other_instance_running()


def test_lock_not_available_never_blocks_start(instance, monkeypatch, caplog):
    """Lock failing (no runtime folder, OS refusal): single instance not enforced, app starts"""
    def failing():
        raise PermissionError("denied")

    monkeypatch.setattr(main, "lock_instance", failing)
    with caplog.at_level("WARNING", logger="neopedal"):
        main.single_instance_check(True)
    assert "Single instance lock not available" in caplog.text


def test_lock_name_per_config_folder(instance, monkeypatch, tmp_path):
    from neopedal.setting import cfg

    name = main.instance_lock_name()
    assert name.startswith("NeoPedal-") and name == main.instance_lock_name()
    monkeypatch.setattr(cfg.path, "config", f"{tmp_path.as_posix()}/portable/")
    assert main.instance_lock_name() != name
