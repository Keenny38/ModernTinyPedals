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
