"""Fuel strategy: pit stop plan, race length of time races, history laps"""

import pytest

from tinypedal.fuel_strategy import (
    StrategyInput,
    history_laps,
    lap_time,
    plan,
    race_laps_for,
    representative_laps,
    saving_target,
    target_consumption,
)
from tinypedal.module_info import ConsumptionDataSet


def test_lap_race_without_stop_loads_exact_fuel():
    strategy = plan(StrategyInput(laptime=90, race_laps=20, tank_capacity=100, fuel_per_lap=2.0))
    assert strategy.stints == [20] and not strategy.stops
    assert strategy.fuel_load == pytest.approx(40)
    with_start = plan(StrategyInput(laptime=90, race_laps=20, tank_capacity=100, fuel_per_lap=2.0, fuel_start=60))
    assert with_start.fuel_load == pytest.approx(60)  # starting fuel given: kept


def test_full_tanks_then_splash():
    strategy = plan(StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0))
    assert strategy.stints == [15, 15, 10]
    assert [stop.lap for stop in strategy.stops] == [15, 30]
    assert strategy.stops[0].fuel == pytest.approx(45)
    assert strategy.stops[1].fuel == pytest.approx(30)  # last stint only
    assert strategy.average_fuel == pytest.approx(37.5)


def test_safety_margin_kept():
    strategy = plan(StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, margin_laps=1))
    assert strategy.max_stint == 14  # one lap of fuel always kept
    assert strategy.fuel_needed == pytest.approx(123)


def test_energy_limits_stints():
    strategy = plan(StrategyInput(laptime=90, race_laps=40, tank_capacity=100, fuel_per_lap=2.0, energy_per_lap=4.0))
    assert strategy.limit == "energy" and strategy.stints == [25, 15]
    assert strategy.stops[0].energy == pytest.approx(60)
    assert strategy.stops[0].fuel == pytest.approx(0)  # 50 L left covers the last 15 laps


def test_time_race_pit_time_costs_laps():
    setup = StrategyInput(laptime=111.9, race_minutes=240, pit_seconds=62, tank_capacity=75, fuel_per_lap=2.95)
    assert race_laps_for(setup, 0) == 129 and race_laps_for(setup, 5) == 126
    strategy = plan(setup)
    assert strategy.race_laps == 126 and len(strategy.stops) == 5  # race length & stops agree


@pytest.mark.parametrize("pit_seconds", [0, 30, 62, 120, 300, 900])
def test_time_race_never_short_of_fuel(pit_seconds):
    setup = StrategyInput(laptime=100.0, race_minutes=180, pit_seconds=pit_seconds, tank_capacity=60, fuel_per_lap=3.1)
    strategy = plan(setup)
    assert sum(strategy.stints) == strategy.race_laps
    assert strategy.race_laps >= race_laps_for(setup, len(strategy.stops))  # covers race with its stops


def test_formation_laps_counted():
    assert race_laps_for(StrategyInput(race_laps=20, formation_laps=1), 0) == 21
    assert race_laps_for(StrategyInput(race_laps=20, formation_laps=0.5), 0) == 21


def test_tyres_changed_before_minimum_tread():
    strategy = plan(StrategyInput(laptime=90, race_laps=60, tank_capacity=45, fuel_per_lap=3.0,
                                  wear_per_lap=2.0, minimum_tread=20))
    # Lap 15: 70 left, 40 after next stint: kept. Lap 30: 40 left, next stint would leave 10: changed
    assert strategy.tyre_stops == [30]


def test_tank_too_small():
    strategy = plan(StrategyInput(laptime=90, race_laps=10, tank_capacity=2, fuel_per_lap=3.0))
    assert not strategy.feasible


def test_not_ready_without_inputs():
    assert not plan(StrategyInput()).ready
    assert not plan(StrategyInput(race_minutes=60, tank_capacity=100, fuel_per_lap=3)).ready  # no lap time


def test_history_laps_and_representative_laps():
    laps = (
        ConsumptionDataSet(9, 1, 100.0, 3.0),
        ConsumptionDataSet(8, 1, 130.0, 2.5),  # pit lap: too slow
        ConsumptionDataSet(7, 0, 99.0, 3.1),  # invalid
        ConsumptionDataSet(6, 1, 101.0, 3.2),
        ConsumptionDataSet(),  # placeholder
    )
    assert len(history_laps(laps)) == 4
    assert [lap.lapNumber for lap in representative_laps(laps)] == [9, 6]
    assert representative_laps((ConsumptionDataSet(),)) == []


def test_energy_only_car():
    strategy = plan(StrategyInput(laptime=90, race_laps=40, energy_per_lap=4.0))
    assert strategy.ready and strategy.limit == "energy" and strategy.stints == [25, 15]
    assert strategy.stops[0].energy == pytest.approx(60) and strategy.stops[0].fuel == 0


def test_refuel_rate_makes_splash_shorter():
    setup = StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, pit_seconds=20, refuel_rate=3.0)
    strategy = plan(setup)
    assert strategy.stops[0].seconds == pytest.approx(20 + 45 / 3)  # full tank
    assert strategy.stops[1].seconds == pytest.approx(20 + 30 / 3)  # splash: shorter
    assert strategy.pit_seconds == pytest.approx(strategy.stops[0].seconds + strategy.stops[1].seconds)


def test_tyres_during_refuel_counts_longest():
    base = dict(laptime=90, race_laps=30, tank_capacity=45, fuel_per_lap=3.0, pit_seconds=20, refuel_rate=3.0,
                tyre_change_seconds=12.0, wear_per_lap=5.0, minimum_tread=40)
    sequential = plan(StrategyInput(**base))
    parallel = plan(StrategyInput(**base, tyres_during_refuel=True))
    assert sequential.stops[0].tyres
    assert sequential.stops[0].seconds == pytest.approx(20 + 15 + 12)
    assert parallel.stops[0].seconds == pytest.approx(20 + 15)  # tyres changed while refuelling


def test_rules_mandatory_stops_and_driver_limit():
    setup = StrategyInput(laptime=100, race_laps=30, tank_capacity=100, fuel_per_lap=2.0)
    assert not plan(setup).stops
    mandatory = plan(StrategyInput(laptime=100, race_laps=30, tank_capacity=100, fuel_per_lap=2.0, minimum_stops=2))
    assert len(mandatory.stops) == 2 and mandatory.stints == [10, 10, 10]
    limited = plan(StrategyInput(laptime=100, race_laps=30, tank_capacity=100, fuel_per_lap=2.0, max_stint_minutes=20))
    assert limited.max_stint == 12 and limited.limit == "stint"  # 20 min at 100 s per lap


def test_drivers_take_turns():
    strategy = plan(StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, pit_seconds=20,
                                  drivers=2, driver_change_seconds=10))
    assert [stop.driver for stop in strategy.stops] == [2, 1]
    assert strategy.stops[0].seconds == pytest.approx(30)


def test_lap_time_follows_fuel_and_track():
    heavy = StrategyInput(laptime=100, tank_capacity=100, fuel_effect=0.3)
    assert lap_time(heavy, 100, 0) == pytest.approx(101.5)  # full tank: +50 units x 0.03 s
    assert lap_time(heavy, 0, 0) == pytest.approx(98.5)
    track = StrategyInput(laptime=100, track_evolution=-0.5)
    assert lap_time(track, 0, 7200) == pytest.approx(99.0)  # 2 hours later


def test_time_race_lap_time_model_changes_laps():
    base = dict(laptime=100, race_minutes=60, tank_capacity=60, fuel_per_lap=3.0, pit_seconds=30)
    constant = plan(StrategyInput(**base))
    faster = plan(StrategyInput(**base, track_evolution=-5.0))
    assert faster.race_laps > constant.race_laps
    assert sum(faster.stint_seconds) + faster.pit_seconds >= 3600 - 1e-6  # race clock reached


def test_saving_target():
    setup = StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0)
    strategy = plan(setup)
    assert len(strategy.stops) == 2
    laps, fuel, _energy, saving = saving_target(setup, strategy)
    assert len(saving.stops) == 1 and laps == 20 and fuel == pytest.approx(45 / 20)
    assert target_consumption(setup, 30) == (pytest.approx(1.5), 0.0)
    assert saving_target(setup, plan(StrategyInput(laptime=90, race_laps=10, tank_capacity=45, fuel_per_lap=3.0))) is None
