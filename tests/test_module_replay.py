"""Module tests, replaying simulated laps through real module code"""

from types import SimpleNamespace

import pytest

from tests.telemetry_sim import LapSim, fake_reader
from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.module import module_delta, module_fuel
from tinypedal.module_info import DeltaInfo, FuelInfo, minfo


@pytest.fixture
def sim_api(monkeypatch):
    """Patch api reader & active state, return function to set simulator"""
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))

    def use(sim: LapSim):
        monkeypatch.setattr(api, "read", fake_reader(sim))
    return use


def run_delta(sim: LapSim, tmp_path, on_tick=None) -> DeltaInfo:
    """Run delta module generators through simulated laps"""
    output = DeltaInfo()
    gen_distance = module_delta.calc_delta_distance(output=output)
    gen_time = module_delta.calc_delta_time(
        output=output,
        filepath=f"{tmp_path}/",
        min_delta_distance=5,
        delta_smoothing_samples=1,
        laptime_pace_samples=5,
        laptime_pace_margin=5,
    )
    while not sim.finished or sim.elapsed < sim.lap_start + 3:  # keep running 3s after finish
        gen_distance.send(0)
        gen_time.send(0)
        if on_tick:
            on_tick(sim, output)
        sim.tick()
    return output


def test_delta_best_lap(sim_api, tmp_path):
    sim = LapSim([92.0, 90.0, 91.0])
    sim_api(sim)
    samples = []

    def check(sim, output):
        # Record delta at mid-lap of 3rd lap (1s slower than best lap 90s at same pace profile)
        if sim.lap_index == 2 and 0.49 < sim.lap_progress < 0.51:
            samples.append(output.deltaBest)

    output = run_delta(sim, tmp_path, check)
    assert output.lapTimeBest == pytest.approx(90.0, abs=0.05)
    assert output.lapTimeLast == pytest.approx(91.0, abs=0.05)
    # Half lap into 91s lap vs 90s best: about +0.5s
    assert samples
    assert sum(samples) / len(samples) == pytest.approx(0.5, abs=0.1)
    # Best lap saved to delta best file
    assert (tmp_path / "SimTrack - SimCar.csv").exists()


def test_delta_best_file_reloaded(sim_api, tmp_path):
    first = LapSim([99.0, 90.0, 95.0])  # first lap is out lap (not timed from start line)
    sim_api(first)
    run_delta(first, tmp_path)  # first session, store best lap file
    sim = LapSim([93.0])
    sim_api(sim)
    output = run_delta(sim, tmp_path)
    assert output.lapTimeBest == pytest.approx(90.0, abs=0.05)  # from file


def test_fuel_consumption(sim_api, tmp_path, monkeypatch):
    sim = LapSim([90.0, 90.0, 90.0], fuel_per_lap=[2.0, 2.5, 3.0], fuel_start=40.0)
    sim_api(sim)
    monkeypatch.setattr(minfo, "delta", DeltaInfo())
    output = FuelInfo()
    gen = module_fuel.calc_consumption(
        output=output,
        is_energy=False,
        filepath=f"{tmp_path}/",
        extension=".fuel",
        min_delta_distance=5,
        fuel_density=0.75,
    )
    while not sim.finished or sim.elapsed < sim.lap_start + 3:
        minfo.delta.lapDistance = sim.distance
        gen.send(0)
        sim.tick()
    assert output.lastLapConsumption == pytest.approx(3.0, abs=0.05)
    assert output.amountCurrent == pytest.approx(40.0 - 7.5, abs=0.05)
    assert output.weight == pytest.approx(0.75 * output.amountCurrent, abs=0.01)


def test_telemetry_recorder(sim_api, tmp_path):
    from tinypedal.module import module_recorder

    sim = LapSim([95.0, 90.0, 91.0])  # first lap is out lap (not complete), 2 complete laps saved
    sim_api(sim)
    gen = module_recorder.record_telemetry(filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10)
    while not sim.finished or sim.elapsed < sim.lap_start + 2:  # validated 1s after crossing line
        gen.send(0)
        sim.tick()
    files = sorted((tmp_path / "SimTrack - SimCar").glob("*.csv"))
    assert len(files) == 2
    assert not any("invalid" in file.name for file in files)
    assert "1m30.000s" in files[0].name or "1m30.000s" in files[1].name
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("time,lap_time,distance,speed_kph")
    assert len(lines) > 4000  # 90s at 50Hz


class InvalidLapSim(LapSim):
    """All laps invalid (track limits), game reports no last lap time"""

    def tick(self):
        super().tick()
        self.last_laptime = -1.0


def test_telemetry_recorder_invalid_lap(sim_api, tmp_path):
    from tinypedal.module import module_recorder

    sim = InvalidLapSim([95.0, 90.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10)
    while not sim.finished or sim.elapsed < sim.lap_start + 11:  # not validated within 10s
        gen.send(0)
        sim.tick()
    files = list((tmp_path / "SimTrack - SimCar").glob("*.csv"))
    assert len(files) == 1 and files[0].name.endswith(" invalid.csv")


def test_telemetry_recorder_limit_per_track(tmp_path):
    from tinypedal.module import module_recorder

    for lap in range(5):
        module_recorder.save_lap(f"{tmp_path}/", "TrackA - GT3", lap, 90.0 + lap, [], max_saved_laps=3)
    module_recorder.save_lap(f"{tmp_path}/", "TrackB - GT3", 1, 80.0, [], max_saved_laps=3)
    assert len(list((tmp_path / "TrackA - GT3").glob("*.csv"))) == 3
    assert len(list((tmp_path / "TrackB - GT3").glob("*.csv"))) == 1
