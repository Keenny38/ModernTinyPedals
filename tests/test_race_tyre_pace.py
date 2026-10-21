"""Race calculator: lap time of used tyres, tyres changed when it pays, compound pace & comparison"""

from dataclasses import replace

import pytest

from neopedal.fuel_strategy import (
    RaceState,
    StrategyInput,
    compare_compounds,
    plan,
    remaining_input,
    stint_extra_seconds,
)

RACE = StrategyInput(laptime=100, race_laps=100, tank_capacity=100, fuel_per_lap=4.0, pit_seconds=30,
                     wear_per_lap=1.0, tyre_change_seconds=20.0)  # 25 laps a tank, tyres never below 0 % in 3 stints


def test_used_tyres_lose_time():
    used = replace(RACE, tread_start=70.0, tyre_deg=0.5)
    assert stint_extra_seconds(used, 0, 70.0) == pytest.approx(1.5)
    assert stint_extra_seconds(used, 0, 100.0) == 0.0
    assert stint_extra_seconds(replace(used, stint_pace=(-0.4, 0.2)), 1, 100.0) == pytest.approx(0.2)
    fresh = plan(replace(RACE, tyre_deg=0.5))
    slow = plan(used)
    assert slow.stint_seconds[0] == pytest.approx(fresh.stint_seconds[0] + 25 * 1.5)


def test_tyres_changed_when_it_pays():
    """Gain over the next 25 laps against 20 s of change: 0.4 s per 10 % changes at each stop,
    0.2 s per 10 % only once tyres lost 50 %"""
    assert [stop.tyres for stop in plan(RACE).stops] == [False, False, False]  # no pace loss: worn to 25 %
    assert [stop.tyres for stop in plan(replace(RACE, tyre_deg=0.4)).stops] == [True, True, True]
    assert [stop.tyres for stop in plan(replace(RACE, tyre_deg=0.2)).stops] == [False, True, False]
    # Changed while refuelling: no time added, always worth it
    concurrent = replace(RACE, tyre_deg=0.05, tyres_during_refuel=True, refuel_rate=2.0)
    assert all(stop.tyres for stop in plan(concurrent).stops)


def test_tyre_plan_changes_kept():
    """Tyre plan given (change time of each stop): its changes, no pace proposal"""
    planned = replace(RACE, tyre_deg=0.4, stop_extra_seconds=(0.0, 0.0, 0.0))
    assert not any(stop.tyres for stop in plan(planned).stops)


def test_stint_pace_live_slice():
    setup = replace(RACE, stint_pace=(0.0, -0.5, 0.3, 0.1))
    base = plan(setup)
    rest = remaining_input(setup, base, RaceState(30, 0.0, 3000.0, 0.0, 80.0, 0.0, 70.0, 1))
    assert rest.stint_pace == (-0.5, 0.3, 0.1)


def test_compare_compounds():
    soft, medium, hard = ("Soft", -0.8, 1.6, 100.0), ("Medium", 0.0, 1.0, 100.0), ("Hard", 0.5, 0.6, 100.0)
    setup = replace(RACE, minimum_tread=30.0, tyre_deg=0.2)
    plans = compare_compounds(setup, [soft, medium, hard])
    assert [item.compound for item in plans] == ["Soft", "Medium", "Hard"]
    by_name = {item.compound: item.strategy for item in plans}
    assert len(by_name["Soft"].tyre_stops) >= len(by_name["Hard"].tyre_stops)
    assert by_name["Soft"].stint_seconds[0] < by_name["Hard"].stint_seconds[0]
    assert compare_compounds(replace(setup, wear_per_lap=0.0), [soft, medium]) == []
    assert compare_compounds(setup, [soft]) == []


def test_compound_comparison_rows():
    from neopedal.ui.quick import race_results

    plans = compare_compounds(RACE, [("Soft", -0.8, 1.6, 100.0), ("Medium", 0.0, 1.0, 100.0)])
    table = race_results.compound_comparison(plans, "Medium")
    assert table["visible"] and table["rows"][1][0] == "Medium (selected)" and table["note"] == ""
    assert table["rows"][table["best"]][-1] == race_results.DASH
    flat = race_results.compound_comparison(compare_compounds(RACE, [("Soft", 0.0, 1.6, 100.0),
                                                                     ("Hard", 0.0, 0.6, 100.0)]))
    assert flat["note"]  # no lap time difference set


def test_tyre_plan_pace_and_options():
    from neopedal.ui.quick.race_tyres import TyrePlan

    tyres = TyrePlan()
    tyres.user_data["tyre_set"]["Soft"]["lap_time_delta"] = -0.6
    tyres.user_data["tyre_set"]["Medium"]["lap_time_delta"] = 0.0
    assert tyres.stint_pace() == ()  # no tyres
    soft = tyres.add_tyre("Soft")
    tyres.rows = [[soft] * 4, [""] * 4]
    assert tyres.stint_pace() == (pytest.approx(-0.6), 0.0)
    options = {name: (pace, wear, tread) for name, pace, wear, tread in tyres.compound_options()}
    assert list(options) == ["Soft", "Medium", "Hard"]
    assert options["Soft"][0] == pytest.approx(-0.6) and options["Soft"][1] == pytest.approx(40 / 30)
    tyres.stock.append(tyres.add_tyre("Ultrasoft"))
    assert [name for name, *_ in tyres.compound_options()] == ["Ultrasoft", "Soft", "Medium", "Hard"]


def test_old_tyre_file_gets_lap_time_delta():
    from neopedal.userfile.tyre_strategy import validate_tyre_strategy

    data = validate_tyre_strategy({"tyre_set": {"Soft": {"front_left_starting_tread": 100}}})
    assert data["tyre_set"]["Soft"]["lap_time_delta"] == 0.0


def test_plan_file_keeps_new_fields(tmp_path):
    """Plan input of the race plan overlay: driver names (texts), tyre pace loss & compound pace kept"""
    import json
    from dataclasses import asdict

    from neopedal.widget.race_plan import load_plan_input

    setup = replace(RACE, tyre_deg=0.3, stint_pace=(0.0, -0.5), driver_names=("Alice", "Bob"), drivers=2,
                    next_stop_extra=12.0)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"version": 1, "setup": asdict(setup), "tyre_changes": [4]}), encoding="utf-8")
    loaded = load_plan_input(str(path))
    assert loaded is not None
    assert loaded[0] == setup and loaded[1] == [4]
