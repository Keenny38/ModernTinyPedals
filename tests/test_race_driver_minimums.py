"""Race calculator: minimum driving times of drivers

Each driver short of its minimum is given whole laps and its driver change (no stint just short of
it, then one more stint), and minimums adding up to more than the race leaves to drive are planned
without them (no plan of one-lap stints), the time over shown.
"""

from dataclasses import replace

from neopedal import fuel_strategy as fs
from neopedal.ui.quick import race_results

SIX_HOURS = fs.StrategyInput(
    laptime=210, race_minutes=360, formation_laps=0.5, pit_seconds=35, tank_capacity=100, fuel_per_lap=4.0,
    energy_per_lap=3.5, refuel_rate=2.0, energy_rate=1.5, wear_per_lap=0.5, minimum_tread=20, drivers=3,
    driver_change_seconds=10, fuel_effect=0.3, track_evolution=-0.2, saving_cost=0.4, driver_pace=(0, 0.3, 0.6),
)


def driven_minutes(strategy: fs.Strategy) -> list[float]:
    return [seconds / 60 for seconds in strategy.driver_seconds]


def test_minimums_met_with_fewest_stops():
    """3 x 100 min of 6 h, 87 min stints: each driver needs 2 stints, 5 stops (was 6, driver 3 short)"""
    strategy = fs.plan(replace(SIX_HOURS, driver_min_minutes=(100, 100, 100)))
    assert strategy.feasible and not strategy.driver_issues and not strategy.drivers_short
    assert len(strategy.stops) == 5
    assert min(driven_minutes(strategy)) >= 100


def test_minimums_close_to_race_met():
    strategy = fs.plan(replace(SIX_HOURS, driver_min_minutes=(110, 110, 110)))
    assert not strategy.driver_issues
    assert min(driven_minutes(strategy)) >= 110


def test_minimums_over_race_planned_without_them():
    """3 x 240 min of 6 h: plan of the race without minimums (was 84 one-lap stints), time over kept"""
    setup = replace(SIX_HOURS, driver_min_minutes=(240, 240, 240))
    strategy = fs.plan(setup)
    free = fs.plan(replace(setup, driver_min_minutes=()))
    assert len(strategy.stops) == len(free.stops) < 10
    assert min(strategy.stints) > 1
    assert strategy.drivers_short > 300 * 60  # 720 min asked of less than 360 min driven
    assert {kind for _, kind in strategy.driver_issues} == {"min"}
    summary = race_results.summary(strategy, None)
    assert "over the race" in summary["text"] and summary["warning"]
    times = race_results.driver_times(strategy, 3, [(0.0, 240.0, 0.0)] * 3)
    assert "more than the race" in times["note"]


def test_minimums_over_race_with_pit_time():
    """24 h, 3 x 475 min = 1425 min: fits the clock, but 17 stops leave less to drive"""
    setup = replace(SIX_HOURS, race_minutes=1440, driver_min_minutes=(475, 475, 475), driver_pace=())
    strategy = fs.plan(setup)
    assert strategy.drivers_short > 0
    assert len(strategy.stops) == len(fs.plan(replace(setup, driver_min_minutes=())).stops)


def test_minimum_short_counts_driver_changes():
    setup = replace(SIX_HOURS, driver_min_minutes=(120, 120, 120))  # 360 min: driver changes don't fit
    assert fs.minimum_time_short(setup, 103) > 0
    assert fs.minimum_time_short(replace(setup, driver_min_minutes=(100, 100, 100)), 103) == 0
    lap_race = replace(setup, race_minutes=0, race_laps=100)  # 100 laps of 210 s = 350 min
    assert fs.minimum_time_short(lap_race, 100) == 10 * 60
    assert fs.minimum_time_short(replace(setup, drivers=1), 103) == 0


def test_live_driving_time_done_counts():
    """Race under way: driving time done counts toward minimums"""
    setup = replace(SIX_HOURS, race_minutes=120, driver_min_minutes=(100, 100, 100),
                    driver_seconds_done=(100 * 60, 100 * 60, 50 * 60))
    assert fs.minimum_time_short(setup, 34) == 0
    strategy = fs.plan(setup)
    assert not strategy.driver_issues
