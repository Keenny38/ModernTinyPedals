"""Race calculator: safety car risk (chance, stops saved, stop under it or stay out for each stint)"""

from dataclasses import replace
from math import exp

import pytest

from neopedal.fuel_strategy import StrategyInput, plan, safety_car_risk

SIX_HOURS = StrategyInput(laptime=100, race_minutes=360, tank_capacity=100, fuel_per_lap=4.0, pit_seconds=60,
                          refuel_rate=2.0, sc_consumption=0.5, sc_laptime=1.5, sc_pit_saving=0.5)


def test_risk_of_six_hours():
    strategy = plan(SIX_HOURS)
    risk = safety_car_risk(SIX_HOURS, strategy, 0.5, 4)
    assert risk.chance == pytest.approx(1 - exp(-0.5 * strategy.race_seconds / 3600))
    assert len(risk.windows) == len(strategy.stints)
    assert [(window.first, window.last) for window in risk.windows] == strategy.stint_bounds()
    # Mid-stint safety car: stopping under it saves half the pit lane time
    assert any(window.gain > 0 for window in risk.windows)
    assert 0.0 <= risk.fewer_stops <= 1.0


def test_no_risk():
    strategy = plan(SIX_HOURS)
    assert safety_car_risk(SIX_HOURS, strategy, 0.0, 4) is None
    assert safety_car_risk(SIX_HOURS, strategy, 0.5, 0) is None
    assert safety_car_risk(replace(SIX_HOURS, laptime=0), plan(replace(SIX_HOURS, laptime=0)), 0.5, 4) is None


def test_risk_ignores_scenario_of_the_plan():
    """Safety car scenario of the plan left out: risk of the race as planned without it"""
    with_scenario = replace(SIX_HOURS, sc_lap=50, sc_laps=5, sc_pit=True)
    assert safety_car_risk(with_scenario, plan(with_scenario), 0.5, 4) == safety_car_risk(
        SIX_HOURS, plan(SIX_HOURS), 0.5, 4)


def test_risk_view():
    from neopedal.ui.quick import race_results

    risk = safety_car_risk(SIX_HOURS, plan(SIX_HOURS), 0.5, 4)
    view = race_results.safety_car_risk_view(risk)
    assert view["visible"] and "chance of a safety car at least" in view["text"]
    assert len(view["rows"]) == len(risk.windows)
    assert {row[1] for row in view["rows"]} <= {"Stop under it", "Stay out"}
    assert view["rows"][0][0] == f"1 ({risk.windows[0].first}-{risk.windows[0].last})"
    assert not race_results.safety_car_risk_view(None)["visible"]
    assert not race_results.safety_car_risk_view(risk, enabled=False)["visible"]


def test_scenarios_carry_risk():
    from neopedal.ui.quick.race_backend import scenario_results

    strategy = plan(SIX_HOURS)
    scenarios = scenario_results(strategy, SIX_HOURS, SIX_HOURS, 0, False, False, "L", (), "", 0.5, 4)
    assert scenarios["risk"]["visible"]
    assert not scenario_results(strategy, SIX_HOURS, SIX_HOURS, 0, False, False, "L")["risk"]["visible"]
