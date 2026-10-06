"""Module tests: sectors, stint history, hybrid battery and forces, driven by scripted telemetry"""

from types import SimpleNamespace

import pytest

from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.const_common import MAX_SECONDS
from tinypedal.module import module_force, module_hybrid, module_sectors, module_stint
from tinypedal.module_info import ForceInfo, HistoryInfo, HybridInfo, SectorData, minfo


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
        "session.identifier": (1, 0, 0),
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


# --- Sectors
def drive_sectors(tele: dict, gen, laps: list[tuple[float, float, float]]):
    """Cross sector lines of each lap, as the game reports them"""
    last_laptime, last_s2 = -1.0, -1.0
    for s1, s2, s3 in laps:
        # Sector 1 (current lap sector 1 & 2 not set yet)
        tele.update({"lap.sector_index": 0, "timing.current_sector1": -1.0, "timing.current_sector2": -1.0,
                     "timing.last_laptime": last_laptime, "timing.last_sector2": last_s2})
        gen.send(0)
        # Sector 2
        tele.update({"lap.sector_index": 1, "timing.current_sector1": s1})
        gen.send(0)
        # Sector 3
        tele.update({"lap.sector_index": 2, "timing.current_sector2": s1 + s2})
        gen.send(0)
        last_laptime, last_s2 = s1 + s2 + s3, s1 + s2
    # Cross finish line of last lap
    tele.update({"lap.sector_index": 0, "timing.current_sector1": -1.0, "timing.current_sector2": -1.0,
                 "timing.last_laptime": last_laptime, "timing.last_sector2": last_s2})
    gen.send(0)


def test_sector_best_and_delta(tele, tmp_path):
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    drive_sectors(tele, gen, [(30.0, 40.0, 20.0), (29.0, 41.0, 19.5), (30.5, 39.0, 21.0)])
    # Theoretical best: best of each sector
    assert session.sectorBestTB == pytest.approx([29.0, 39.0, 19.5])
    # Personal best lap: 89.5 (lap 2) sectors
    assert session.sectorBestPB == pytest.approx([29.0, 41.0, 19.5])
    assert session.sectorPrev == pytest.approx([30.5, 39.0, 21.0])
    # Last sector 3 (21.0) against best before it (19.5)
    assert session.deltaSectorBestTB[2] == pytest.approx(1.5)
    assert session.noDeltaSector is False
    assert alltime.sectorBestTB == session.sectorBestTB
    # Saved on next reset
    gen.send(1)
    assert (tmp_path / "SimTrack - SimCar.sector").exists()


def test_sector_best_reloaded_from_file(tele, tmp_path):
    gen = module_sectors.record_sectors(SectorData(), SectorData(), f"{tmp_path}/")
    drive_sectors(tele, gen, [(30.0, 40.0, 20.0), (29.0, 39.0, 19.0)])
    gen.send(1)  # save
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    tele["lap.sector_index"] = 0
    gen.send(0)
    assert alltime.sectorBestTB == pytest.approx([29.0, 39.0, 19.0])


@pytest.mark.parametrize("flag", ["vehicle.in_pits", "lap.invalidated"])
def test_sector_best_s1_s2_ignored_from_pit_or_invalid_lap(tele, tmp_path, flag):
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    tele["timing.current_laptime"] = 5.0
    # Out lap / cut lap: quick S1 & S2, lap time invalid
    tele.update({"timing.start": 10.0, flag: True})
    drive_sectors(tele, gen, [(25.0, 35.0, 20.0)])
    tele[flag] = False
    assert session.sectorPrev[:2] == pytest.approx([25.0, 35.0])
    assert alltime.sectorBestTB[:2] == [MAX_SECONDS, MAX_SECONDS]
    assert session.sectorBestTB[:2] == [MAX_SECONDS, MAX_SECONDS]
    # Next clean lap recorded
    tele["timing.start"] = 90.0
    drive_sectors(tele, gen, [(30.0, 40.0, 20.0)])
    assert alltime.sectorBestTB[:2] == pytest.approx([30.0, 40.0])


def test_sector_first_lap_has_no_delta():
    output = SectorData()
    module_sectors.calc_sector_time(output, 1, 0, -1.0, 30.0, -1.0, -1.0)
    assert output.sectorPrev[0] == 30.0
    assert output.noDeltaSector is True  # no best sector 1 to compare with
    assert output.sectorBestTB[0] == 30.0
    assert output.sectorBestTB[1] == MAX_SECONDS


# --- Stint history
def drive_stint(tele: dict, gen, laps: list[float], fuel_per_lap: float = 2.0, wear_per_lap: float = 0.01,
                start_time: float = 0.0, start_lap: int = 0):
    """Drive laps on track, one generator step per lap plus one at start"""
    elapsed = start_time
    fuel = minfo.fuel.amountCurrent
    wear = tele["tyre.wear"][0]
    tele.update({"vehicle.in_pits": False, "vehicle.speed": 60.0, "timing.start": elapsed,
                 "session.elapsed": elapsed, "lap.number": start_lap})
    gen.send(0)
    for index, laptime in enumerate(laps):
        elapsed += laptime
        fuel -= fuel_per_lap
        wear -= wear_per_lap
        minfo.fuel.amountCurrent = fuel
        tele.update({"timing.start": elapsed, "session.elapsed": elapsed, "lap.number": start_lap + index + 1,
                     "tyre.wear": (wear,) * 4})
        gen.send(0)
    return elapsed


def pit_stop(tele: dict, gen, elapsed: float, refuel: float):
    """Stop in pits and refuel"""
    tele.update({"vehicle.in_pits": True, "vehicle.speed": 0.0, "session.elapsed": elapsed + 1})
    gen.send(0)
    minfo.fuel.amountCurrent += refuel
    tele["session.elapsed"] = elapsed + 20
    gen.send(0)


@pytest.fixture
def stint_env(tele, monkeypatch):
    fuel = SimpleNamespace(amountCurrent=50.0)
    monkeypatch.setattr(minfo, "fuel", fuel)
    monkeypatch.setattr(minfo, "energy", SimpleNamespace(amountCurrent=0.0))
    monkeypatch.setattr(module_stint, "select_compound_symbol", lambda name: "S")
    return tele


def test_stint_totals_and_consistency(stint_env):
    history = HistoryInfo()
    history.stintDataSet.clear()
    gen = module_stint.record_stint_history(history, 60, 3, 50)
    drive_stint(stint_env, gen, [90.0, 91.0, 92.0, 90.0])
    stint = history.stintDataCurrent
    assert stint.totalLaps == 4
    assert stint.totalTime == pytest.approx(363.0)
    assert stint.totalFuel == pytest.approx(8.0)
    assert stint.totalTyreWear == pytest.approx(4.0)  # 1% tread worn per lap, 4 laps
    # First lap after start is an out lap: 3 timed laps, fastest 90, others average 91.5
    assert stint.lapTimeDelta == pytest.approx(1.5)
    assert stint.lapTimeConsistency == pytest.approx(90 / 91.5 * 100)


def test_stint_saved_after_pit_stop(stint_env):
    history = HistoryInfo()
    history.stintDataSet.clear()
    gen = module_stint.record_stint_history(history, 60, 3, 50)
    elapsed = drive_stint(stint_env, gen, [90.0, 90.0, 90.0])
    pit_stop(stint_env, gen, elapsed, refuel=20.0)
    assert history.stintDataVersion == 1
    saved = history.stintDataSet[0]
    assert saved.totalLaps == 3
    assert saved.totalFuel == pytest.approx(6.0)
    # New stint starts from refueled level
    drive_stint(stint_env, gen, [91.0], start_time=elapsed + 20, start_lap=3)
    assert history.stintDataCurrent.totalLaps == 1


def test_stint_cold_tyre_laps_excluded(stint_env):
    history = HistoryInfo()
    gen = module_stint.record_stint_history(history, 60, 3, 100)  # carcass 80 < 100: all laps cold
    drive_stint(stint_env, gen, [90.0, 95.0, 99.0])
    assert history.stintDataCurrent.lapTimeDelta == 0.0
    assert history.stintDataCurrent.lapTimeConsistency == 100.0


# --- Hybrid battery
def drive_hybrid(tele: dict, gen, charges: list[float], states: list[int], step: float = 1.0,
                 lap_start: float = 0.0, elapsed: float = 0.0):
    for charge, state in zip(charges, states):
        elapsed += step
        tele.update({"timing.start": lap_start, "timing.elapsed": elapsed,
                     "emotor.battery_charge": charge / 100, "emotor.state": state,
                     "timing.current_laptime": elapsed - lap_start, "lap.distance": (elapsed - lap_start) * 50})
        gen.send(0)
    return elapsed


def test_hybrid_drain_regen_and_active_timer(tele):
    output = HybridInfo()
    gen = module_hybrid.calc_motor(output, min_delta_distance=5)
    # Deploy (state 2) from 80% to 70%, then regen (state 3) back to 75%
    elapsed = drive_hybrid(tele, gen, [80, 78, 76, 74, 72, 70], [2] * 6)
    assert output.batteryDrain == pytest.approx(10.0)
    assert output.motorActiveTimer == pytest.approx(5.0)
    drive_hybrid(tele, gen, [71, 73, 75], [3] * 3, elapsed=elapsed)
    assert output.batteryRegen == pytest.approx(5.0)
    assert output.motorState == 3
    assert output.motorInactiveTimer == pytest.approx(2.0)  # since first step off deploy
    assert output.batteryCharge == pytest.approx(75.0)


def test_hybrid_lap_totals_move_to_last_lap(tele):
    output = HybridInfo()
    gen = module_hybrid.calc_motor(output, min_delta_distance=5)
    elapsed = drive_hybrid(tele, gen, [80, 75, 70], [2] * 3)
    drive_hybrid(tele, gen, [70, 72], [3] * 2, lap_start=elapsed + 0.5, elapsed=elapsed)  # new lap
    assert output.batteryDrainLast == pytest.approx(10.0)
    assert output.batteryDrain == 0.0
    assert output.batteryRegen == pytest.approx(2.0)


def test_hybrid_state_guessed_when_game_reports_none(tele):
    output = HybridInfo()
    gen = module_hybrid.calc_motor(output, min_delta_distance=5)
    drive_hybrid(tele, gen, [80, 79, 78], [0] * 3)  # draining without motor state
    assert output.motorState == 2
    drive_hybrid(tele, gen, [78] * 7, [0] * 7, elapsed=10)  # steady: back to idle after debounce
    assert output.motorState == 1


# --- Forces
def test_transient_max_holds_then_resets():
    gen = module_force.transient_max(reset_delay=2)
    assert gen.send((1.5, 0.0)) == 1.5
    assert gen.send((1.0, 1.0)) == 1.5  # held
    assert gen.send((0.5, 3.0)) == 0.0  # reset after delay
    assert gen.send((0.8, 3.1)) == 0.8
    gen.send(None)
    assert gen.send((0.1, 3.2)) == 0.1


def test_transient_max_falls_back_to_recent_value():
    gen = module_force.transient_max(reset_delay=2, store_recent=True)
    gen.send((2.0, 0.0))
    gen.send((1.2, 1.0))  # recent lower peak kept as fallback
    assert gen.send((0.3, 3.5)) == 1.2


def test_force_g_downforce_and_braking(tele):
    output = ForceInfo()
    gen = module_force.calc_force(output, g_accel=9.8, max_g_diff=0.2, max_avg_g_samples=5,
                                  max_g_reset_delay=5, max_avg_g_reset_delay=30, max_braking_rate_reset_delay=60)
    tele.update({"timing.elapsed": 10.0, "vehicle.acceleration_lateral": -19.6,
                 "vehicle.acceleration_longitudinal": 29.4, "vehicle.downforce_front": 3000.0,
                 "vehicle.downforce_rear": 1000.0, "inputs.brake_raw": 1.0, "vehicle.impact_time": 0.0})
    gen.send(0)
    assert output.latGForceRaw == pytest.approx(-2.0)
    assert output.maxLatGForce == pytest.approx(2.0)
    assert output.lgtGForceRaw == pytest.approx(3.0)
    assert output.downForceRatio == pytest.approx(0.75)
    assert output.brakingRate == pytest.approx(3.0)
    assert output.transientMaxBrakingRate == pytest.approx(3.0)
    # Braking right after an impact is not counted
    tele.update({"timing.elapsed": 11.0, "vehicle.impact_time": 10.5})
    gen.send(0)
    assert output.brakingRate == 0.0


# --- Session & saved data (audit fixes)
@pytest.fixture
def wall_clock(monkeypatch):
    """Wall clock of session tokens (validator.session_token), set by test"""
    import time
    from types import SimpleNamespace

    from tinypedal import validator

    clock = {"now": 10_300.0}
    monkeypatch.setattr(validator, "time", SimpleNamespace(time=lambda: clock["now"], strftime=time.strftime))
    return clock


def load_sectors(tele: dict, tmp_path, identifier: tuple) -> tuple[SectorData, SectorData]:
    tele.update({"session.identifier": identifier, "lap.sector_index": 0, "timing.last_laptime": -1.0,
                 "timing.last_sector2": -1.0})
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    gen.send(0)
    return session, alltime


def test_sector_session_best_only_reloaded_in_same_session(tele, tmp_path, wall_clock):
    # Session started at 10000 (wall clock), driven at 300 s elapsed
    tele["session.identifier"] = (360001, 300, 3)
    gen = module_sectors.record_sectors(SectorData(), SectorData(), f"{tmp_path}/")
    drive_sectors(tele, gen, [(30.0, 40.0, 20.0), (29.0, 39.0, 19.0)])
    gen.send(1)  # save
    # Same session, later
    wall_clock["now"] = 10_600.0
    session, alltime = load_sectors(tele, tmp_path, (360001, 600, 6))
    assert session.sectorBestTB == pytest.approx([29.0, 39.0, 19.0])
    # Restarted session of same length & type (started at 20000), going out later: not same session
    wall_clock["now"] = 20_500.0
    session, alltime = load_sectors(tele, tmp_path, (360001, 500, 5))
    assert session.sectorBestTB == [MAX_SECONDS] * 3
    assert alltime.sectorBestTB == pytest.approx([29.0, 39.0, 19.0])  # all time best kept


def test_sector_best_invalid_values_ignored(tele, tmp_path):
    (tmp_path / "SimTrack - SimCar.sector").write_text(
        '360001,0,0,1\n"bad",40.0,20.0\n30.0,40.0,20.0\n30.0,-5.0,nan\n"x",40.0\n', encoding="utf-8")
    _session, alltime = load_sectors(tele, tmp_path, (1, 0, 0))
    assert alltime.sectorBestTB == [30.0, MAX_SECONDS, MAX_SECONDS]  # negative S2 never a best, nan dropped
    assert alltime.sectorBestPB == [MAX_SECONDS, 40.0, MAX_SECONDS]


def test_csv_files_with_huge_field_fall_back_to_defaults(tmp_path):
    from tinypedal.userfile.consumption_history import load_consumption_history_file
    from tinypedal.userfile.delta_best import load_delta_best_file
    from tinypedal.userfile.fuel_delta import load_fuel_delta_file
    from tinypedal.userfile.sector_best import load_sector_best_file

    huge = "1" * 200_000 + "\n"  # csv.Error (field larger than field limit), not a ValueError
    for extension in (".sector", ".csv", ".fuel", ".consumption"):
        (tmp_path / f"huge{extension}").write_text(huge, encoding="utf-8")
    folder = f"{tmp_path}/"
    defaults = (1.0, 2.0, 3.0)
    assert load_sector_best_file(folder, "huge", (1, 0, 0, 0.0), defaults) == ([1.0, 2.0, 3.0],) * 4
    assert load_delta_best_file(folder, "huge", ("default", 0.0)) == ("default", 0.0)
    assert load_fuel_delta_file(folder, "huge", ".fuel", ("default", 0.0, 0.0)) == ("default", 0.0, 0.0)
    assert len(load_consumption_history_file(folder, "huge")) == 1  # placeholder


def test_delta_file_with_nan_rejected(tmp_path):
    from tinypedal.userfile.delta_best import load_delta_best_file

    rows = "".join(f"{index * 10.0},{index * 0.5}\n" for index in range(20)) + "200.0,nan\n"
    (tmp_path / "nan.csv").write_text(rows, encoding="utf-8")
    assert load_delta_best_file(f"{tmp_path}/", "nan", ("default", 0.0)) == ("default", 0.0)


def test_consumption_history_line_with_nan_left_out(tmp_path):
    from tinypedal.userfile.consumption_history import load_consumption_history_file

    (tmp_path / "laps.consumption").write_text(
        "lapNumber,lapTimeLast,lastLapUsedFuel\n2,91.0,nan\n1,90.0,3.0\n", encoding="utf-8")
    dataset = load_consumption_history_file(f"{tmp_path}/", "laps")
    assert [lap.lapNumber for lap in dataset] == [1]


def test_sectors_saved_when_module_stops(tele, tmp_path):
    from tinypedal.module._base import MODULE_STOP

    gen = module_sectors.record_sectors(SectorData(), SectorData(), f"{tmp_path}/")
    drive_sectors(tele, gen, [(30.0, 40.0, 20.0), (29.0, 39.0, 19.0)])
    assert not (tmp_path / "SimTrack - SimCar.sector").exists()  # saved on next reset only
    tele["session.combo_name"] = "Other - Car"  # module stopping: data saved, nothing reloaded
    gen.send(MODULE_STOP)
    assert (tmp_path / "SimTrack - SimCar.sector").exists()
    assert not (tmp_path / "Other - Car.sector").exists()


def test_module_save_on_stop_unless_discarded():
    from tinypedal.module._base import MODULE_STOP, DataModule

    sent = []

    class Generator:
        def send(self, value):
            sent.append(value)

    module = DataModule.__new__(DataModule)
    module.discard = False
    module.save_on_stop(Generator(), None)
    assert sent == [MODULE_STOP]
    module.discard = True  # data reset (menu): data not saved
    module.save_on_stop(Generator())
    assert sent == [MODULE_STOP]


def test_consumption_history_replaced_not_changed_in_place(tele, monkeypatch, tmp_path):
    """GUI iterates history while module adds laps: never changed in place (copy on write)"""
    monkeypatch.setattr(minfo, "delta", SimpleNamespace(lapTimeCurrent=5.0, lapTimeLast=90.0, isValidLap=True))
    monkeypatch.setattr(minfo, "fuel", SimpleNamespace(lastLapConsumption=3.0, capacity=100.0))
    monkeypatch.setattr(minfo, "energy", SimpleNamespace(lastLapConsumption=0.0))
    monkeypatch.setattr(minfo, "hybrid", SimpleNamespace(batteryDrainLast=0.0, batteryRegenLast=0.0))
    monkeypatch.setattr(minfo, "wheels", SimpleNamespace(lastLapTreadWear=(1.0, 1.0, 1.0, 1.0)))
    history = HistoryInfo()
    gen = module_stint.record_consumption_history(history, f"{tmp_path}/")
    tele["lap.number"] = 1
    gen.send(0)
    shown = history.consumptionDataSet  # held by GUI
    shown_laps = list(shown)
    tele["lap.number"] = 2
    gen.send(0)
    assert list(shown) == shown_laps
    assert history.consumptionDataSet is not shown and history.consumptionDataSet[0].lapNumber == 2
    assert history.consumptionDataSet.maxlen == shown.maxlen


def test_stint_history_replaced_not_changed_in_place(stint_env):
    history = HistoryInfo()
    shown = history.stintDataSet  # held by GUI
    gen = module_stint.record_stint_history(history, 60, 3, 50)
    elapsed = drive_stint(stint_env, gen, [90.0, 90.0, 90.0])
    pit_stop(stint_env, gen, elapsed, refuel=20.0)
    assert len(shown) == 1 and history.stintDataSet[0].totalLaps == 3


def test_hybrid_net_change_reference_skips_pit_lap(tele):
    output = HybridInfo()
    gen = module_hybrid.calc_motor(output, min_delta_distance=5)
    elapsed = drive_hybrid(tele, gen, [80], [2])  # before first lap start
    # Lap A: recorded, 10% drained
    elapsed = drive_hybrid(tele, gen, [78, 76, 74, 72, 70], [2] * 5, lap_start=elapsed + 0.5, elapsed=elapsed)
    # Lap B: pit lap, 6% regen
    lap_start = elapsed + 0.5
    elapsed = drive_hybrid(tele, gen, [72], [3], lap_start=lap_start, elapsed=elapsed)
    tele["vehicle.in_pits"] = True
    elapsed = drive_hybrid(tele, gen, [74, 76], [3] * 2, lap_start=lap_start, elapsed=elapsed)
    tele["vehicle.in_pits"] = False
    # Lap C: estimate from lap A (reference lap), not from pit lap net change
    drive_hybrid(tele, gen, [76], [1], lap_start=elapsed + 0.5, elapsed=elapsed)
    assert output.batteryNetChange < 0


@pytest.mark.parametrize(("seconds", "short", "full"), [
    (59.9996, "1:00.000", "1:00.000"),  # rounded before minutes split: never "0:60.000"
    (119.9996, "2:00.000", "2:00.000"),  # never "1:60.000"
    (60.0, "1:00.000", "1:00.000"),
    (61.1, "1:01.100", "1:01.100"),
    (95.4321, "1:35.432", "1:35.432"),
    (45.5, "45.500", "0:45.500"),
    (-0.0004, "0.000", "0:00.000"),
])
def test_laptime_format_rounded_before_split(seconds, short, full):
    from tinypedal.calculation import sec2laptime, sec2laptime_full

    assert sec2laptime(seconds) == short
    assert sec2laptime_full(seconds) == full
