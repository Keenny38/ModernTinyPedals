"""Strategy & consumption (phase 2, package B2): median of green flag laps, leader finishing first,
driver of each stint, stints cut by tyre life, plan fuel unit badge & picture copy"""

from types import SimpleNamespace

import pytest

from tests.telemetry_sim import LapSim, fake_reader
from tests.test_race_calculator import host, live_race, page, set_race  # noqa: F401 (host, page: fixtures)
from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.fuel_strategy import (
    PitStop,
    RaceState,
    Strategy,
    StrategyInput,
    estimated_stops,
    plan,
    remaining_input,
    strategy_input_from_values,
    tyre_life,
    tyre_stint_limit,
)
from tinypedal.module import module_fuel
from tinypedal.module_info import DeltaInfo, FuelInfo, VehiclesInfo, minfo


# --- Consumption estimate: median of green flag laps
class FlagLapSim(LapSim):
    """Laps under full course yellow & laps invalidated by game (track limits)"""

    def __init__(self, *args, yellow=(), invalid=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.yellow = set(yellow)
        self.invalid = set(invalid)


@pytest.fixture
def flag_sim(monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(minfo, "delta", DeltaInfo())
    monkeypatch.setattr(minfo, "vehicles", VehiclesInfo())

    def use(sim: FlagLapSim):
        reader = fake_reader(sim)
        reader.vehicle.under_yellow = lambda index=None: sim.lap_index in sim.yellow
        reader.session.yellow_flag_state = lambda: 0
        reader.lap.invalidated = lambda index=None: sim.lap_index in sim.invalid
        monkeypatch.setattr(api, "read", reader)
    return use


def run_laps(sim: FlagLapSim, tmp_path, green_flag_laps: int) -> FuelInfo:
    output = FuelInfo()
    gen = module_fuel.calc_consumption(
        output=output, is_energy=False, filepath=f"{tmp_path}/", extension=".fuel",
        min_delta_distance=5, fuel_density=0.75, green_flag_laps=green_flag_laps)
    while not sim.finished or sim.elapsed < sim.lap_start + 3:
        minfo.delta.lapDistance = sim.distance
        gen.send(0)
        sim.tick()
    return output


# First lap is out lap (not recorded), last lap under yellow: much less fuel used
YELLOW_LAST = dict(lap_times=[90.0] * 6, fuel_per_lap=[3.0, 3.0, 3.1, 2.9, 3.0, 1.2], yellow={5})


def test_last_lap_estimate_drops_under_yellow(flag_sim, tmp_path):
    """Default: last valid lap, a lap under yellow lowers the estimate"""
    sim = FlagLapSim(**YELLOW_LAST)
    flag_sim(sim)
    output = run_laps(sim, tmp_path, 0)
    assert output.consumptionMethod == module_fuel.METHOD_LAST_LAP and output.consumptionLaps == 0
    assert output.estimatedConsumption == pytest.approx(1.2, abs=0.05)


def test_median_of_green_flag_laps(flag_sim, tmp_path):
    sim = FlagLapSim(**YELLOW_LAST)
    flag_sim(sim)
    output = run_laps(sim, tmp_path, 5)
    assert output.consumptionMethod == module_fuel.METHOD_MEDIAN and output.consumptionLaps == 4
    assert output.estimatedConsumption == pytest.approx(3.0, abs=0.05)  # median of 3.0, 3.1, 2.9, 3.0
    assert output.lastLapConsumption == pytest.approx(1.2, abs=0.05)  # last lap still shown as driven


def test_median_leaves_out_invalid_laps(flag_sim, tmp_path):
    sim = FlagLapSim([90.0] * 6, fuel_per_lap=[3.0, 3.0, 3.0, 4.5, 4.5, 3.1], invalid={3, 4})
    flag_sim(sim)
    output = run_laps(sim, tmp_path, 5)
    assert output.consumptionMethod == module_fuel.METHOD_MEDIAN and output.consumptionLaps == 3
    assert output.estimatedConsumption == pytest.approx(3.0, abs=0.05)


def test_median_falls_back_to_last_lap(flag_sim, tmp_path):
    """Fewer than 3 green flag laps: last valid (green flag) lap"""
    sim = FlagLapSim([90.0] * 4, fuel_per_lap=[3.0, 2.8, 1.0, 3.2], yellow={2})
    flag_sim(sim)
    output = run_laps(sim, tmp_path, 5)
    assert output.consumptionMethod == module_fuel.METHOD_LAST_LAP
    assert output.estimatedConsumption == pytest.approx(3.2, abs=0.05)


def test_green_flag_median_needs_minimum_laps():
    from collections import deque

    laps = deque([3.0, 2.0], maxlen=5)
    assert module_fuel.green_flag_median(laps, 3) == 0.0
    laps.append(9.0)
    assert module_fuel.green_flag_median(laps, 3) == 3.0


def test_fuel_module_options(ui_env):
    from tinypedal.setting import cfg

    options = cfg.default.setting["module_fuel"]
    assert options["enable_green_flag_consumption"] is False  # last valid lap by default
    assert options["number_of_green_flag_laps"] == 5


# --- Time race: lap after timer when leader finishes first
@pytest.fixture
def time_race(monkeypatch):
    values = {
        "session.combo_name": "SimTrack - SimCar", "engine.tank_capacity": 100.0, "engine.fuel": 60.0,
        "timing.start": 10.0, "timing.elapsed": 20.0, "timing.current_laptime": 10.0, "lap.distance": 500.0,
        "engine.expected_fuel_consumption": 3.0, "session.remaining": 1000.0,
    }

    class Group:
        def __init__(self, prefix):
            self.prefix = prefix

        def __getattr__(self, name):
            return lambda *args, **kwargs: values.get(f"{self.prefix}.{name}", 0)

    groups = ("session", "lap", "timing", "vehicle", "tyre", "emotor", "engine")
    monkeypatch.setattr(api, "read", SimpleNamespace(**{name: Group(name) for name in groups}))
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(minfo, "delta", DeltaInfo())
    monkeypatch.setattr(minfo, "vehicles", VehiclesInfo())
    minfo.delta.lapTimePace = 100.0


def needed_fuel(tmp_path) -> float:
    output = FuelInfo()
    gen = module_fuel.calc_consumption(output, False, f"{tmp_path}/", ".fuel", 10.0, 0.0)
    gen.send(0)
    return output.neededAbsolute


def test_fuel_laps_left_count_leader_finishing_first(time_race, tmp_path):
    assert needed_fuel(tmp_path) == pytest.approx(30.0)  # 1000 s left at 100 s: 10 laps of 3 L
    minfo.vehicles.finishLapOffsetLeader = 1.0
    assert needed_fuel(tmp_path) == pytest.approx(33.0)  # one lap more after timer
    minfo.vehicles.finishLapOffset = -1.0  # final pit stop part never counted (from fuel module itself)
    assert needed_fuel(tmp_path) == pytest.approx(33.0)


def test_vehicles_module_leader_part_of_offset(ui_env, monkeypatch):
    from tinypedal.module.module_vehicles import update_finish_time
    from tinypedal.module_info import VehicleDataSet

    output = VehiclesInfo()
    output.dataSet = [VehicleDataSet() for _ in range(2)]
    output.totalVehicles, output.leaderIndex, output.playerIndex = 2, 0, 1
    output.dataSet[0].lapTimeHistory.average = 100.0
    for group, name, value in (
        ("session", "finish_type", 0), ("session", "remaining", 450.0), ("vehicle", "pit_stop_time", 0.0),
    ):
        monkeypatch.setattr(getattr(api.read, group), name, lambda *args, value=value, **kwargs: value, raising=False)
    monkeypatch.setattr(api.read.lap, "progress", lambda index=None: 0.9 if index == 0 else 0.2, raising=False)
    monkeypatch.setattr(minfo.delta, "lapTimePace", 100.0)
    update_finish_time(output, max_finish_time_diff=10.0)
    # Leader crosses the line 0.6 lap after the timer: player drives one lap more
    assert output.finishLapOffsetLeader == pytest.approx(1.0)
    assert output.finishLapOffset == pytest.approx(output.finishLapOffsetLeader)  # no final stop
    monkeypatch.setattr(api.read.session, "finish_type", lambda *args, **kwargs: 2, raising=False)
    update_finish_time(output, max_finish_time_diff=10.0)
    assert output.finishLapOffsetLeader == 0.0  # laps & time race: leader in finish time offset


# --- Driver of each stint
def session_id(now: float, laps: int = 0) -> tuple[int, int, int]:
    return 360004, int(now), laps


def test_stop_counter_records_drivers():
    from tinypedal.race_live import StopCounter

    counter = StopCounter()
    counter.update(session_id(0), False, 50, 40, 0, 90, 0, now=0, driver="Alice")
    assert counter.stint_drivers() == ("Alice",)
    counter.update(session_id(10, 5), True, 0.1, 30, 0, 90, 0, now=10, driver="Alice")  # pit entry
    counter.update(session_id(30, 5), True, 0.1, 60, 0, 100, 0, now=30, driver="Bob")  # swapped in the box
    assert counter.stint_drivers() == ("Alice",)  # stop under way: stint of driver at entry
    counter.update(session_id(40, 5), False, 50, 60, 0, 100, 1, now=40, laps=5.0, clock=38.0, driver="Bob")
    assert counter.stops[-1].number == 1 and counter.stops[-1].driver_in == "Alice"
    assert counter.stops[-1].driver_out == "Bob" and counter.stops[-1].lap == 5
    assert counter.stint_drivers() == ("Alice", "Bob")
    # Stop not seen (game count trusted): driver of that stint unknown, driver in the car now known
    assert counter.update(session_id(500, 9), False, 50, 60, 0, 100, 2, now=500, driver="Carl") == 2
    assert counter.stint_drivers() == ("Alice", "Bob", "Carl")
    # New session: drivers forgotten
    counter.update((360005, 0, 0), False, 50, 60, 0, 100, 0, now=600, driver="Dan")
    assert counter.stops == [] and counter.stint_drivers() == ("Dan",)


def test_stint_drivers_with_stops_before_counting():
    from tinypedal.race_live import StopCounter

    counter = StopCounter()
    counter.update(session_id(0, 10), False, 50, 40, 0, 90, 2, now=0, driver="Eve")  # opened after 2 stops
    assert counter.stint_drivers() == ("", "", "Eve")


def test_race_state_carries_stint_drivers(ui_env, monkeypatch):
    from tinypedal.race_live import StopCounter, read_race_state

    live_race(monkeypatch, laps_done=12, stops=0)
    monkeypatch.setattr(api.read.vehicle, "driver_name", lambda index=None: "Alice", raising=False)
    state = read_race_state(float, StopCounter()).state
    assert state is not None and state.stint_drivers == ("Alice",)
    assert RaceState(1, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0).stint_drivers == ()  # older callers


def test_plan_against_race_shows_drivers(page, monkeypatch):  # noqa: F811
    from tinypedal.module_info import StintDataSet

    backend = page.backend
    live_race(monkeypatch, laps_done=20, stops=1)
    monkeypatch.setattr(minfo.history, "stintDataSet", (StintDataSet(15, 1365.0, 46.5, 0.0, 30.0),))
    monkeypatch.setattr(backend.stop_counter, "stint_drivers", lambda: ("Alice <b>", "Bob"))
    set_race(backend, laps=40)
    against = backend.planVsRace
    assert 1 not in against["hidden"] and against["rows"][0][1] == "Alice <b>"
    monkeypatch.setattr(backend.stop_counter, "stint_drivers", lambda: ("",))
    set_race(backend, laps=41)
    assert 1 in backend.planVsRace["hidden"]  # no driver known
    # Live race: driver in the car on summary line (escaped)
    monkeypatch.setattr(backend.stop_counter, "stint_drivers", lambda: ("Alice <b>", "Bob"))
    backend.set_race_state(RaceState(20, 0.0, 1800.0, 0.0, 9.0, 0.0, 0.0, 1, stint_drivers=("Alice <b>", "Bob")))
    assert "(Bob)" in backend.summary["text"]


# --- Stints cut by tyre life
BASE = StrategyInput(laptime=100, race_laps=60, tank_capacity=100, fuel_per_lap=3.0, pit_seconds=60)


def setup_with(**values) -> StrategyInput:
    return StrategyInput(**{**BASE.__dict__, **values})


def test_tyre_life_of_a_set():
    assert tyre_life(BASE, 100.0) == float("inf") and tyre_stint_limit(BASE) == 0
    setup = setup_with(wear_per_lap=4.0, minimum_tread=20.0)
    assert tyre_life(setup, 100.0) == float("inf")  # minimum tread alone does not cut stints
    setup = setup_with(wear_per_lap=4.0, minimum_tread=20.0, tyre_life_stints=True)
    assert tyre_life(setup, 100.0) == pytest.approx(20.0) and tyre_life(setup, 50.0) == pytest.approx(7.5)
    setup = setup_with(tyre_set_laps=25)
    assert tyre_life(setup, 100.0, 10.0) == pytest.approx(15.0) and tyre_stint_limit(setup) == 25


def test_stints_never_longer_than_tyre_set():
    assert plan(BASE).stints == [33, 27] and plan(BASE).limit == "fuel"
    strategy = plan(setup_with(tyre_set_laps=20))
    assert strategy.stints == [20, 20, 20] and strategy.limit == "tyres"
    assert [stop.tyres for stop in strategy.stops] == [True, True]
    assert all(first <= stop.lap <= last for stop, (first, last) in zip(strategy.stops, strategy.windows))


def test_stints_cut_by_tread_down_to_minimum():
    worn = setup_with(wear_per_lap=4.0, minimum_tread=20.0)
    assert plan(worn).stints == [33, 27]  # tyres changed at the stop, stints not cut
    strategy = plan(setup_with(wear_per_lap=4.0, minimum_tread=20.0, tyre_life_stints=True))
    assert strategy.stints == [20, 20, 20] and all(stop.tyres for stop in strategy.stops)


def test_tyres_changed_only_when_they_cannot_last_next_stint():
    strategy = plan(setup_with(tyre_set_laps=70, race_laps=90))
    assert strategy.stints == [33, 33, 24]
    assert [stop.tyres for stop in strategy.stops] == [False, True]  # 66 laps on the first set


def test_tyre_life_with_safety_car_wear():
    strategy = plan(setup_with(tyre_set_laps=20, sc_lap=10, sc_laps=5, sc_wear=0.5))
    assert strategy.stints[0] == 22  # 5 laps at half wear: 2.5 laps more


def test_tyre_life_in_time_race_and_estimate():
    setup = setup_with(race_laps=0, race_minutes=120, tyre_set_laps=25)
    strategy = plan(setup)
    assert max(strategy.stints) <= 25 and strategy.limit == "tyres"
    assert estimated_stops(setup) >= 2


def test_worn_start_tyres_cut_first_stint():
    strategy = plan(setup_with(tyre_set_laps=20, tyre_laps_done=15.0))
    assert strategy.stints[0] == 5 and strategy.stops[0].tyres
    assert plan(setup_with(tyre_set_laps=20, tyre_laps_done=20.0)).stints[0] == 1  # one lap at least


def test_live_race_counts_laps_on_tyres():
    setup = setup_with(tyre_set_laps=20)
    base = Strategy(race_laps=60, stints=[20, 20, 20], stint_seconds=[2000.0] * 3, stint_drivers=[1, 1, 1],
                    stops=[PitStop(20, 60.0, 0.0, True), PitStop(40, 60.0, 0.0, True)])
    rest = remaining_input(setup, base, RaceState(25, 0.0, 2600.0, 0.0, 80.0, 0.0, 90.0, 1))
    assert rest.tyre_laps_done == pytest.approx(5.0)
    rest = remaining_input(setup, base, RaceState(12, 0.0, 1300.0, 0.0, 60.0, 0.0, 90.0, 0))
    assert rest.tyre_laps_done == pytest.approx(12.0)
    assert plan(rest).stints[0] == 8  # tyres of start: 8 laps left


def test_tyre_life_inputs_of_race_plan_values():
    values = {"enable_lap_race": True, "input_race_laps": 60, "input_lap_time": 100, "input_tank_capacity": 100,
              "input_fuel_per_lap": 3.0, "input_tyre_set_laps": 20, "enable_tyre_life_stints": True}
    setup = strategy_input_from_values(values)
    assert setup.tyre_set_laps == 20 and setup.tyre_life_stints
    assert strategy_input_from_values({"input_tyre_set_laps": "x"}).tyre_set_laps == 0


def test_tyre_life_in_plan_input_of_race_plan_widget(page, tmp_path):  # noqa: F811
    """Race plan widget plans again from the plan input kept by the race calculator"""
    import json

    from tinypedal.widget.race_plan import load_plan_input

    backend = page.backend
    set_race(backend, laps=60, tank=100.0, laptime=100.0)
    backend.setInput("input_tyre_set_laps", 20)
    filename = tmp_path / "plan.json"
    filename.write_text(json.dumps(backend.plan_file_data()), encoding="utf-8")
    setup, _ = load_plan_input(str(filename))
    assert setup.tyre_set_laps == 20 and plan(setup).stints == [20, 20, 20]


def test_tyre_life_inputs_in_page(page):  # noqa: F811
    from tinypedal.ui.quick.race_model import checked_inputs, ranged_inputs
    from tinypedal.ui.quick.race_results import PLAN_COLUMNS

    backend = page.backend
    set_race(backend, laps=60, tank=100.0, laptime=100.0)
    assert backend.strategy.limit == "fuel"
    backend.setInput("input_tyre_set_laps", 20)
    pits = next(tile for tile in backend.tiles if tile["key"] == "pits")
    assert backend.strategy.stints == [20, 20, 20] and "tyre life" in pits["detail"]
    assert backend.plan["rows"][1][PLAN_COLUMNS.index("tyres")].startswith("Change")  # tyre change shown in plan
    values = backend.input_values()
    assert values["input_tyre_set_laps"] == 20 and values["enable_tyre_life_stints"] is False
    backend.setInput("input_tyre_set_laps", 0)
    backend.set_values(ranged_inputs({**values, "enable_tyre_life_stints": True}))
    assert backend.values["input_tyre_set_laps"] == 20 and backend.values["enable_tyre_life_stints"]
    assert checked_inputs({})["input_tyre_set_laps"] == 0  # plan saved before: no tyre life


# --- Pit stop plan: fuel unit badge, picture copied
def test_plan_fuel_unit_badge_and_picture_copy(page, host):  # noqa: F811
    from PySide6.QtGui import QGuiApplication

    backend = page.backend
    set_race(backend, laps=40)
    assert backend.fuelSymbol == "L" and backend.plan["columns"][4]["title"] == "Fuel (L)"
    QGuiApplication.clipboard().clear()
    backend.copyPlanImage()
    image = QGuiApplication.clipboard().image()
    assert not image.isNull() and image.width() >= 900 and host.toasts
