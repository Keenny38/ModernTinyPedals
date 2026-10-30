"""Race calculator team tab: line-up typed before the race, driver planned for each stint, names of the
LMU team taking the place of the names typed (2026-10-29)"""

from dataclasses import replace

import pytest
from PySide6.QtCore import QObject

from neopedal.fuel_strategy import (
    RaceState,
    StrategyInput,
    parse_stint_drivers,
    plan,
    remaining_input,
    stint_drivers_text,
    strategy_input_from_values,
)
from neopedal.ui.quick.race_team_plan import merge_team_names, names_alike, team_names, team_names_text
from tests.test_perf_page_state import qml_warnings  # noqa: F401 (fixture)
from tests.test_race_calc_cards_qml import watched_page  # noqa: F401 (fixture)
from tests.test_race_calculator import host, page, set_race  # noqa: F401 (fixtures)
from tests.test_race_live_data import REFUEL_SCREEN

THREE = StrategyInput(laptime=100, race_minutes=360, tank_capacity=100, fuel_per_lap=4.0, pit_seconds=40,
                      drivers=3, driver_change_seconds=10)


# --- Names of the LMU team
def test_names_alike():
    assert names_alike("Keenny", "Keenny Hess") and names_alike("hess", "K Hess")
    assert names_alike("Flo V.", "Flo Veninski")  # word in common
    assert not names_alike("Bob", "Antoine Dumontier") and not names_alike("", "A")
    assert names_alike("Al", "al") and not names_alike("Al", "Alice")  # short names: same only


@pytest.mark.parametrize(("typed", "game", "merged"), [
    # Same or close names keep their place, other game names take places of names matching none, in order
    (["Driver A", "Keenny", "Flo"], ["Flo Veninski", "Antoine Dumontier", "Keenny Hess"],
     ["Antoine Dumontier", "Keenny Hess", "Flo Veninski"]),
    # Places not named filled after names typed matching none
    (["", "Bob", ""], ["Alice", "Bob", "Carl"], ["Alice", "Bob", "Carl"]),
    (["Pilot 1", "", "Pilot 3"], ["Alice", "Carl"], ["Alice", "", "Carl"]),
    # More game drivers than places: added after; fewer: names typed matching none kept
    (["Alice"], ["Bob", "alice"], ["alice", "Bob"]),
    (["Alice", "Bob", "Carl"], ["Bob"], ["Alice", "Bob", "Carl"]),
    ([], ["Alice", "Alice", " "], ["Alice"]),
])
def test_merge_team_names(typed, game, merged):
    assert merge_team_names(typed, game) == merged
    assert merge_team_names(merged, game) == merged  # names of the game: nothing changes again


def test_team_names_text():
    assert team_names("Alice\n\n Bob \n\n") == ["Alice", "", "Bob"]
    assert team_names_text(["Alice", "", "Bob", "", ""]) == "Alice\n\nBob"
    assert team_names("") == [] and team_names(None) == []  # type: ignore[arg-type]


# --- Plan: driver planned for each stint
def test_stint_drivers_text():
    assert parse_stint_drivers("2, 0,x,1,12,0,0") == (2, 0, 0, 1)
    assert stint_drivers_text([3, 0, 1, 0, 0]) == "3,0,1" and stint_drivers_text([0, 0]) == ""


def test_plan_follows_planned_drivers():
    free = plan(THREE)
    assert free.stint_drivers[:3] == [1, 2, 3]
    planned = plan(replace(THREE, stint_drivers=(2, 2, 0, 3), driver_start=2))
    assert planned.stint_drivers[:4] == [2, 2, 3, 3] and planned.stops[0].driver == 2
    assert len(planned.stops) == len(free.stops)  # one driver change less: same stops
    # Driver out of range (team made smaller): chosen by the plan
    assert plan(replace(THREE, stint_drivers=(0, 7))).stint_drivers[1] == 2


def test_planned_drivers_checked_not_planned_by_minimums():
    """Minimum driving times: drivers planned for stints get them checked (issues), not changed"""
    setup = replace(THREE, driver_min_minutes=(0, 0, 150))
    free = plan(setup)
    assert not free.driver_issues  # driver 3 given driving time by the plan
    planned = plan(replace(setup, stint_drivers=(1, 2, 1, 2, 1, 2, 1, 2)))
    assert 3 not in planned.stint_drivers[:8] and (3, "min") in planned.driver_issues
    # Only the first stint planned: plan still meets the minimums
    assert not plan(replace(setup, stint_drivers=(2,), driver_start=2)).driver_issues


def test_planned_drivers_from_values():
    values = {"input_drivers": 3, "input_stint_drivers": "3,0,1"}
    setup = strategy_input_from_values(values)
    assert setup.stint_drivers == (3, 0, 1) and setup.driver_start == 3
    assert strategy_input_from_values({**values, "input_drivers": 1}).stint_drivers == ()


def test_rest_of_race_keeps_planned_drivers():
    setup = replace(THREE, stint_drivers=(1, 3, 3, 2), driver_names=("Alice", "Bob", "Carl"))
    base = plan(setup)
    assert base.stint_drivers[:4] == [1, 3, 3, 2]
    state = RaceState(30, 0.0, 3100.0, 18500.0, 50.0, 0.0, 0.0, 1, stint_drivers=("Alice", "Bob"))
    rest = remaining_input(setup, base, state)
    assert rest.stint_drivers == (3, 3, 2) and rest.driver_start == 2  # Bob in the car, not Carl as planned
    assert plan(rest).stint_drivers[1:3] == [3, 2]


# --- Page: line-up & stints of the team tab
def plan_view(backend) -> dict:
    return backend.teamPlan


def test_line_up_typed_added_removed(page):  # noqa: F811
    backend = page.backend
    set_race(backend, minutes=360, tank=100, fuel=4.0, laptime=100, pit=40)
    backend.addDriver()
    backend.addDriver()
    assert backend.values["input_drivers"] == 3
    backend.setDriverName(0, "  Alice  ")
    backend.setDriverName(2, "Carl\nX")
    backend.setDriverName(5, "Nobody")  # no such driver
    assert backend.values["input_driver_names"] == "Alice\n\nCarl X"
    view = plan_view(backend)
    assert [driver["name"] for driver in view["drivers"]] == ["Alice", "", "Carl X"]
    assert view["drivers"][1]["placeholder"] == "Driver 2" and view["choices"] == ["Auto", "Alice", "Driver 2", "Carl X"]
    assert sum(driver["stints"] for driver in view["drivers"]) == len(backend.strategy.stints)
    # Names in the plan, timeline & driving times
    assert backend.plan["rows"][0][7] == "Alice" and "Carl X" in str(backend.timeline["stints"])
    assert backend.driverTimes["rows"][1][0] == "2"
    # Driver 2 removed: Carl moves up with his pace, stints planned for him follow, Bob's chosen again
    backend.setInput("input_driver_table", "0:0:0,1:0:0,2:0:0")
    backend.setInput("input_stint_drivers", "3,2,1,3")
    backend.removeDriver(1)
    assert backend.values["input_drivers"] == 2
    assert backend.values["input_driver_names"] == "Alice\nCarl X"
    assert backend.values["input_driver_table"] == "0:0:0,2:0:0"
    assert backend.values["input_stint_drivers"] == "2,0,1,2"
    backend.removeDriver(1)
    backend.removeDriver(0)  # last driver kept
    assert backend.values["input_drivers"] == 1 and plan_view(backend)["team"] is False
    page.undo()
    assert backend.values["input_drivers"] == 2  # one undo step per removal


def test_stint_drivers_set_kept_cleared(page):  # noqa: F811
    backend = page.backend
    set_race(backend, minutes=360, tank=100, fuel=4.0, laptime=100, pit=40)
    backend.setInput("input_drivers", 3)
    rows = plan_view(backend)["stints"]
    assert [row["driver"] for row in rows[:3]] == [1, 2, 3] and all(row["planned"] == 0 for row in rows)
    assert all(row["kind"] == "plan" and row["laps"] and row["timing"] for row in rows)
    backend.setStintDriver(1, 3)
    backend.setStintDriver(2, 9)  # no such driver: nothing
    assert backend.values["input_stint_drivers"] == "0,3"
    rows = plan_view(backend)["stints"]
    assert rows[1]["planned"] == 3 and rows[1]["driver"] == 3 and plan_view(backend)["planned"] is True
    assert backend.strategy.stint_drivers[1] == 3
    backend.setStintDriver(1, 0)
    assert backend.values["input_stint_drivers"] == ""
    backend.keepStintDrivers()
    kept = parse_stint_drivers(backend.values["input_stint_drivers"])
    assert list(kept) == backend.strategy.stint_drivers[:len(kept)] and all(kept)
    backend.clearStintDrivers()
    assert backend.values["input_stint_drivers"] == "" and plan_view(backend)["planned"] is False


def test_game_team_names_replace_names_typed(page):  # noqa: F811
    backend = page.backend
    set_race(backend, minutes=360, tank=100, fuel=4.0, laptime=100, pit=40)
    backend.set_values({"input_drivers": 2, "input_driver_names": "Keenny\nMe 2", "input_stint_drivers": "2,1"})
    backend.received_garage([REFUEL_SCREEN, None, None])  # 4 drivers in the LMU team
    names = team_names(backend.values["input_driver_names"])
    assert names[:2] == ["Keenny Hess", "Flo Veninski"]  # close name kept its place, other one replaced
    assert set(names) == {"Flo Veninski", "Antoine Dumontier", "Keenny Hess", "Olivier Demolliens"}
    assert backend.values["input_drivers"] == 2 and backend.values["input_stint_drivers"] == "2,1"
    view = plan_view(backend)
    assert [driver["fromGame"] for driver in view["drivers"]] == [True, True]
    assert view["stints"][0]["name"] == "Flo Veninski" and "Keenny Hess" in view["gameTeam"]
    backend.addDriver()  # third name of the team already there
    assert plan_view(backend)["drivers"][2]["name"] in ("Antoine Dumontier", "Olivier Demolliens")
    # Name typed over a game name: replaced again by the game name left
    backend.setDriverName(1, "Nickname")
    backend.received_garage([REFUEL_SCREEN, None, None])
    assert team_names(backend.values["input_driver_names"])[1] == "Flo Veninski"


def test_team_stints_names_kept(page):  # noqa: F811
    from neopedal.process.team_usage import StintUsage

    backend = page.backend
    backend.set_values({"input_drivers": 2, "input_driver_names": "A\nB"})
    stint = StintUsage("Bob Real", 1, 1, 10, 9, 0.05, 0.0, 1.0)
    backend.received_team(([stint], 100.0))
    assert team_names(backend.values["input_driver_names"]) == ["Bob Real", "B"]


def test_race_under_way_stints_done(page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_files
    from tests.test_race_calculator import live_race

    backend = page.backend
    set_race(backend, laptime=90.0, tank=45.0, fuel=3.0, laps=60)
    backend.set_values({"input_drivers": 2, "input_driver_names": "Alice\nBob"})
    live_race(monkeypatch, laps_done=20, fuel=9.0, stops=1)
    monkeypatch.setattr(race_files.RaceFiles, "race_stint_drivers", lambda self: ("Alice", "Alice"))
    backend.setLiveRace(True)
    rows = plan_view(backend)["stints"]
    assert rows[0]["kind"] == "done" and rows[0]["name"] == "Alice" and rows[0]["number"] == 1
    assert rows[1]["kind"] == "current" and rows[1]["number"] == 2
    assert all(row["kind"] == "plan" for row in rows[2:])


def test_team_tab_qml(watched_page, qml_warnings):  # noqa: F811
    from tests.test_audit_g_qml_pages import item_named
    from tests.test_race_calc_cards_qml import settle

    page = watched_page  # noqa: F811
    backend = page.backend
    set_race(backend, minutes=360, tank=100, fuel=4.0, laptime=100, pit=40)
    backend.set_values({"input_drivers": 3, "input_driver_names": "Alice\nBob"})
    view = page.ensure_view()
    backend.setTab(2)
    for size in ((1300, 860), (700, 860)):  # cards side by side, then one below the other
        page.resize(*size)
        settle()
        assert not view.errors(), [error.toString() for error in view.errors()]
        root = view.rootObject()
        assert root.findChild(QObject, "teamLineUp") is not None
        name = item_named(root, "driverName1")
        assert name is not None and name.property("text") == "Bob"
        assert item_named(root, "driverName2").property("placeholderText") == "Driver 3"
        box = item_named(root, "stintDriver1")
        assert box is not None and box.property("count") == 4 and box.property("currentIndex") == 0
    backend.setStintDriver(1, 1)
    settle()
    assert item_named(root, "stintDriver1").property("currentIndex") == 1
    backend.setDriverName(1, "Bobby")
    settle()
    assert item_named(root, "driverName1").property("text") == "Bobby"
    backend.setInput("input_drivers", 1)  # one driver: no stint plan
    settle()
    assert item_named(root, "stintDriver0") is None or not item_named(root, "stintDriver0").property("visible")
    assert not qml_warnings, qml_warnings
