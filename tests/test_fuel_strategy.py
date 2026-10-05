"""Fuel strategy: pit stop plan, race length of time races, history laps"""

from dataclasses import replace

import pytest

from tinypedal.fuel_strategy import (
    StrategyInput,
    history_laps,
    lap_time,
    plan,
    race_laps_for,
    representative_laps,
    saving_target,
    strategy_input_from_values,
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


def test_mandatory_stops_always_met():
    # Race laps not a multiple of stints: still every stop (stints even capped at 2 laps gave 3)
    uneven = plan(StrategyInput(laptime=100, race_laps=7, tank_capacity=100, fuel_per_lap=2.0, minimum_stops=4))
    assert len(uneven.stops) == 4 and uneven.stints == [2, 2, 1, 1, 1] and uneven.limit == "stops"
    # Time race: stops cost laps, stints spread over the shorter race
    timed = plan(StrategyInput(laptime=60, race_minutes=10, pit_seconds=120, tank_capacity=100, fuel_per_lap=2.0,
                               minimum_stops=2))
    assert len(timed.stops) == 2 and timed.stints == [2, 2, 2]


def test_tyres_follow_stint_actually_driven():
    # Driver limit: 10 laps stints, 20% wear each: tyres last 2 stints above 50%, not changed at lap 10
    strategy = plan(StrategyInput(laptime=60, race_laps=40, tank_capacity=100, fuel_per_lap=2.0,
                                  max_stint_minutes=10, wear_per_lap=2.0, minimum_tread=50))
    assert strategy.stints == [10, 10, 10, 10] and strategy.tyre_stops == [20]


def test_no_fuel_effect_without_fuel():
    base = dict(laptime=100, race_laps=10, tank_capacity=100, energy_per_lap=4.0)
    assert plan(StrategyInput(**base, fuel_effect=0.5)).stint_seconds == plan(StrategyInput(**base)).stint_seconds


def test_saving_target_bounded_by_stint_limit(monkeypatch):
    from tinypedal import fuel_strategy

    calls = []
    real_plan = fuel_strategy.plan
    monkeypatch.setattr(fuel_strategy, "plan", lambda setup: calls.append(1) or real_plan(setup))
    # 24 h with a driver limit: stints already at the limit, saving fuel cannot save a stop
    setup = StrategyInput(laptime=90, race_minutes=1440, pit_seconds=60, tank_capacity=100, fuel_per_lap=2.0,
                          max_stint_minutes=45)
    assert saving_target(setup, real_plan(setup)) is None and len(calls) <= 1  # one tank for all: still stops
    # Fuel limited 24 h: found by halving, few plans
    setup = StrategyInput(laptime=90, race_minutes=1440, pit_seconds=60, tank_capacity=100, fuel_per_lap=2.0)
    strategy = real_plan(setup)
    laps, _fuel, _energy, saving = saving_target(setup, strategy)
    assert len(saving.stops) < len(strategy.stops) and len(calls) <= 14
    assert len(real_plan(replace(setup, fuel_per_lap=100 / (laps - 1))).stops) == len(strategy.stops)  # fewest laps


def test_strategy_input_ignores_non_finite_values():
    setup = strategy_input_from_values({"input_lap_time": float("nan"), "input_race_laps": float("inf"),
                                        "enable_lap_race": True, "input_tank_capacity": 50})
    assert setup.laptime == 0 and setup.race_laps == 0 and setup.tank_capacity == 50


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


def test_start_amount_below_one_lap_is_not_a_stop():
    strategy = plan(StrategyInput(laptime=90, race_laps=20, tank_capacity=100, fuel_per_lap=3.0, fuel_start=2.0))
    assert not strategy.ready and strategy.impossible and strategy.problem == "start" and not strategy.stops
    assert plan(StrategyInput(laptime=90, race_laps=10, tank_capacity=2, fuel_per_lap=3.0)).problem == "tank"


def test_driver_limit_counts_real_lap_times():
    # Heavier car is slower: 30 min limit never passed although laps at full tank take longer
    strategy = plan(StrategyInput(laptime=100, race_laps=60, tank_capacity=100, fuel_per_lap=1.0,
                                  max_stint_minutes=30, fuel_effect=1.0))
    assert max(strategy.stint_seconds) <= 30 * 60 and sum(strategy.stints) == 60


def test_rolling_start_uses_half_a_lap_of_fuel():
    strategy = plan(StrategyInput(laptime=90, race_laps=20, formation_laps=0.5, tank_capacity=100, fuel_per_lap=3.0))
    assert strategy.race_laps == 21 and strategy.fuel_needed == pytest.approx(61.5)
    assert strategy.fuel_load == pytest.approx(61.5)
    longer = plan(StrategyInput(laptime=90, race_laps=40, formation_laps=0.5, tank_capacity=45, fuel_per_lap=3.0))
    assert longer.stints[0] == 15  # half a lap of fuel left: formation lap & 14.5 race laps... 15 laps in all


def test_balanced_stints_keep_stops():
    base = dict(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0)
    assert plan(StrategyInput(**base)).stints == [15, 15, 10]
    balanced = plan(StrategyInput(**base, balanced_stints=True))
    assert balanced.stints == [14, 13, 13] and len(balanced.stops) == 2


def test_safety_margin_units():
    base = dict(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0)
    in_laps = plan(StrategyInput(**base, margin_laps=1))
    in_fuel = plan(StrategyInput(**base, margin_fuel=3.0))
    assert in_fuel.stints == in_laps.stints and in_fuel.fuel_needed == pytest.approx(in_laps.fuel_needed)
    in_percent = plan(StrategyInput(**base, margin_percent=10))
    assert in_percent.fuel_needed == pytest.approx(40 * 3.3) and in_percent.max_stint == 13


def test_saving_target_with_partial_start_fuel():
    setup = StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, fuel_start=30)
    strategy = plan(setup)
    assert strategy.stints == [10, 15, 15]
    target = saving_target(setup, strategy)
    assert target is not None and len(target.strategy.stops) == 1  # 30 L & a full tank last 40 laps
    assert 30 / target.fuel + 45 / target.fuel >= 40 - 1e-6


def test_pit_windows_and_clock():
    strategy = plan(StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0))
    assert strategy.windows == [(10, 15), (25, 30)]
    assert strategy.stops[0].clock == pytest.approx(15 * 90)


def test_safety_car_scenario():
    base = dict(laptime=100, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, pit_seconds=60)
    normal = plan(StrategyInput(**base))
    slow = plan(StrategyInput(**base, sc_lap=10, sc_laps=4, sc_consumption=0.5))
    assert slow.stints[0] == 17 and slow.fuel_needed < normal.fuel_needed  # 4 laps at half consumption
    assert slow.race_seconds > normal.race_seconds  # slower laps
    pit = plan(StrategyInput(**base, sc_lap=10, sc_laps=4, sc_pit=True, sc_pit_saving=0.5))
    assert pit.stops[0].lap == 10 and pit.stops[0].safety_car
    assert pit.stops[0].seconds == pytest.approx(30)  # half the pit lane time lost under safety car


def test_drivers_pace_limits_and_turns():
    base = dict(laptime=100, race_laps=60, tank_capacity=40, fuel_per_lap=2.0, drivers=2, driver_change_seconds=10)
    paced = plan(StrategyInput(**base, driver_pace=(0.0, 2.0)))
    assert paced.stint_seconds[0] == pytest.approx(20 * 100) and paced.stint_seconds[1] == pytest.approx(20 * 102)
    double = plan(StrategyInput(**base, stints_per_driver=2))
    assert double.stint_drivers == [1, 1, 2] and [stop.seconds for stop in double.stops] == [0, 10]
    capped = plan(StrategyInput(**base, driver_max_minutes=(40.0, 0.0), driver_min_minutes=(0.0, 50.0)))
    assert capped.stint_drivers == [1, 2, 2] and capped.driver_seconds[0] <= 40 * 60
    assert (2, "min") not in capped.driver_issues  # 2nd driver drives 40 laps: over 50 min


def test_saving_cost_and_comparison():
    from tinypedal.fuel_strategy import compare_strategies, race_result

    setup = StrategyInput(laptime=100, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, pit_seconds=60,
                          saving_cost=0.5)
    strategy = plan(setup)
    target = saving_target(setup, strategy)
    assert target.strategy.saving_seconds == pytest.approx(0.5 * (1 - target.fuel / 3.0) * 10)
    variants = compare_strategies(setup, strategy)
    assert [variant.stops for variant in variants] == [0, 1, 2, 3] and variants[2].current
    best = min(variants, key=lambda variant: race_result(variant.strategy))
    assert best.stops == 1  # 25% saving costs 1.25 s x 40 laps < 60 s stop; 0 stop saves too much


def test_rest_of_race_from_live_state():
    from tinypedal.fuel_strategy import RaceState, remaining_input

    setup = StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0)
    base = plan(setup)
    state = RaceState(laps_done=20, lap_progress=0.0, elapsed=1800, seconds_left=0, fuel=9.0, energy=0,
                      tread=0, stops_done=1)
    rest = plan(remaining_input(setup, base, state))
    assert rest.first_lap == 20 and rest.race_laps == 20
    assert [stop.lap for stop in rest.stops] == [23, 38] and rest.stops[0].fuel == pytest.approx(45)  # 9 L: 3 laps
    timed = StrategyInput(laptime=100, race_minutes=60, tank_capacity=60, fuel_per_lap=3.0)
    rest = plan(remaining_input(timed, plan(timed), RaceState(18, 0.5, 1850, 1750, 10.0, 0, 0, 0)))
    assert rest.first_lap == 18 and rest.race_laps == 18 and rest.stops[0].lap == 21


def test_pace_estimate_from_history():
    from tinypedal.fuel_strategy import estimate_pace

    laps = []
    number = 1
    for stint in range(3):
        for lap in range(10):  # 0.3 s per 10 L burned, track 0.6 s faster per hour
            hours = sum(item.lapTimeLast for item in laps) / 3600
            laps.append(ConsumptionDataSet(number, 1, 100.0 - 0.03 * 3.0 * lap - 0.6 * hours, 3.0))
            number += 1
        if stint < 2:  # in & out laps: 40 s lost
            laps.append(ConsumptionDataSet(number, 1, 120.0, 3.0))
            laps.append(ConsumptionDataSet(number + 1, 1, 120.0, 1.0))
            number += 2
    estimate = estimate_pace(list(reversed(laps)))
    assert estimate.pit_stops == 2 and estimate.pit_seconds == pytest.approx(40, abs=2)
    assert estimate.fuel_effect == pytest.approx(0.3, abs=0.02) and estimate.fuel_laps == 30
    assert estimate.track_evolution == pytest.approx(-0.6, abs=0.1)


def test_plans_cached_but_copied():
    setup = StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0)
    first = plan(setup)
    first.stops.clear()
    assert len(plan(setup).stops) == 2  # change of a copy never reaches the cache


def test_safety_car_after_finish_ignored():
    strategy = plan(StrategyInput(laptime=100, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, sc_lap=500, sc_laps=4))
    assert strategy.safety_car == (0, 0)


def test_pit_windows_follow_real_lap_times():
    # 30 min limit, heavier car slower: 17 laps at most, window never later than that
    strategy = plan(StrategyInput(laptime=100, race_laps=60, tank_capacity=100, fuel_per_lap=1.0,
                                  max_stint_minutes=30, fuel_effect=1.0))
    assert strategy.stints[:3] == [17, 17, 17] and strategy.windows[0] == (9, 17)


def test_minimum_driving_time_given():
    # No stop needed for fuel: 2nd driver gets 20 min anyway
    strategy = plan(StrategyInput(laptime=100, race_laps=30, tank_capacity=100, fuel_per_lap=2.0, drivers=2,
                                  driver_min_minutes=(0, 20)))
    assert strategy.stint_drivers == [1, 2] and strategy.driver_seconds[1] >= 20 * 60 and not strategy.driver_issues


def test_tyre_wear_under_safety_car():
    base = dict(laptime=100, race_laps=40, tank_capacity=200, fuel_per_lap=1.0, wear_per_lap=3.0, minimum_tread=40,
                minimum_stops=1)
    assert plan(StrategyInput(**base)).tyre_stops == [20]  # 60% per stint of 20 laps
    slow = plan(StrategyInput(**base, sc_lap=2, sc_laps=20, sc_wear=0.0))  # laps 2-21 without wear
    assert slow.tyre_stops == []  # 97% left at the stop, 40% at the finish


def test_leader_finishes_first_one_lap_more():
    base = dict(laptime=100, race_minutes=60, tank_capacity=100, fuel_per_lap=3.0)
    leader = plan(StrategyInput(**base))
    behind = plan(StrategyInput(**base, extra_laps=1))
    assert behind.race_laps == leader.race_laps + 1 and behind.fuel_needed == pytest.approx(leader.fuel_needed + 3)


def test_in_and_out_laps_use_less():
    base = dict(laptime=90, race_laps=40, tank_capacity=47, fuel_per_lap=3.0)
    assert plan(StrategyInput(**base)).stints[0] == 15
    pit_laps = plan(StrategyInput(**base, pit_lap_consumption=0.5))
    assert pit_laps.stints[0] == 16  # 15 laps & an in lap at half consumption: 46.5 L


def test_rain_scenario_stops_for_tyres():
    base = dict(laptime=100, race_laps=40, tank_capacity=200, fuel_per_lap=2.0, pit_seconds=30,
                tyre_change_seconds=20)
    rain = plan(StrategyInput(**base, rain_lap=10, rain_laps=10, rain_laptime=1.2, rain_tyres=True))
    assert [(stop.lap, stop.reason, stop.tyres) for stop in rain.stops] == [(10, "rain", True), (19, "dry", True)]
    assert rain.stops[0].tyre_seconds == pytest.approx(20) and rain.rain == (10, 19)
    assert rain.windows == [(10, 10), (19, 19)]  # set by scenario: no window
    assert rain.stint_seconds[1] == pytest.approx(9 * 120)  # laps 11-19 in the wet


def test_stop_keeps_amount_after_refill():
    strategy = plan(StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0))
    assert [stop.fuel_after for stop in strategy.stops] == [pytest.approx(45), pytest.approx(30)]


def test_time_race_back_and_forth_keeps_longest_of_it():
    # Lap time model: lengths alternate around 900 laps; the longest of them kept, not the 960 laps
    # of a race without stop (87 stops planned instead of 82)
    setup = StrategyInput(laptime=90, race_minutes=1440, tank_capacity=45, fuel_per_lap=4.0, pit_seconds=120,
                          fuel_effect=0.3, track_evolution=-0.4)
    strategy = plan(setup)
    assert 900 <= strategy.race_laps <= 905 and len(strategy.stops) <= 82


def test_consumption_target_to_stop():
    from tinypedal.fuel_strategy import target_to_stop

    setup = StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0, margin_laps=1)
    assert target_to_stop(setup, 30.0, 9) == pytest.approx((30 - 3) / 9)


def test_stop_counter():
    from tinypedal.race_live import StopCounter

    counter = StopCounter()
    session = (1, 1, 1)
    assert counter.update(session, False, 50, 40, 0, 90, 0, now=0) == 0
    # Drive-through counted by the game: not a stop
    counter.update(session, True, 16, 40, 0, 90, 1, now=1)
    assert counter.update(session, False, 50, 40, 0, 90, 1, now=2) == 0
    # Real stop, game counts at exit
    counter.update(session, True, 0.1, 30, 0, 90, 1, now=10)
    counter.update(session, True, 0.1, 60, 0, 100, 1, now=30)
    assert counter.update(session, False, 50, 60, 0, 100, 2, now=40) == 1
    # Stop not seen (page hidden): game count trusted
    assert counter.update(session, False, 50, 60, 0, 100, 3, now=500) == 2
