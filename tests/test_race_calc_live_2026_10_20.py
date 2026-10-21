"""Race calculator, race under way: real drivers & driving time of the stints ended

Driver of each stint from the driver names (team order of the calculator drivers, else the plan
made before the race), driving time of the stints ended from the race clock of the stops seen.
"""

from dataclasses import replace

from neopedal.fuel_strategy import RaceState, StrategyInput, driver_numbers, plan, remaining_input
from neopedal.race_live import StopCounter
from tests.test_race_calculator import host  # noqa: F401 (fixture)

THREE = StrategyInput(laptime=100, race_minutes=360, tank_capacity=100, fuel_per_lap=4.0, pit_seconds=40,
                      drivers=3, driver_change_seconds=10, driver_min_minutes=(100, 100, 100))


def session_id(now: float, laps: int = 0) -> tuple[int, int, int]:
    return 360004, int(now), laps


def test_stop_counter_stint_seconds():
    counter = StopCounter()
    counter.update(session_id(0), False, 50, 40, 0, 90, 0, now=0, clock=0.0, driver="Alice")
    counter.update(session_id(10, 25), True, 20, 4, 0, 90, 0, now=10, laps=24.9, clock=2500.0, driver="Alice")
    counter.update(session_id(11, 25), True, 0.1, 4, 0, 90, 0, now=11, laps=24.9, clock=2510.0, driver="Alice")
    counter.update(session_id(13, 25), True, 0.1, 60, 0, 90, 1, now=13, laps=24.9, clock=2530.0, driver="Bob")
    counter.update(session_id(20, 25), False, 40, 90, 0, 90, 1, now=20, laps=25.0, clock=2560.0, driver="Bob")
    assert counter.stint_seconds() == (2500.0,)
    counter.update(session_id(30, 40), True, 20, 4, 0, 90, 1, now=30, laps=39.9, clock=4060.0, driver="Bob")
    counter.update(session_id(32, 40), True, 0.1, 60, 0, 90, 1, now=32, laps=39.9, clock=4070.0, driver="Bob")
    counter.update(session_id(40, 40), False, 40, 90, 0, 90, 2, now=40, laps=40.0, clock=4100.0, driver="Bob")
    assert counter.stint_seconds() == (2500.0, 1500.0)
    # Stop not seen (game count trusted): its stint unknown
    counter.update(session_id(500, 60), False, 50, 60, 0, 100, 3, now=500, driver="Carl")
    assert counter.stint_seconds() == (2500.0, 1500.0, -1.0)


def test_driver_numbers_team_order_first():
    base = plan(THREE)
    assert base.stint_drivers[:3] == [1, 2, 3]
    # Plan order: first name seen at stint takes the planned driver
    assert driver_numbers(("Alice", "Alice", "Bob"), base, 3) == [1, 1, 3]
    # Team order known: Bob is driver 2 whatever the plan
    assert driver_numbers(("Alice", "Alice", "Bob"), base, 3, ("Alice", "Bob", "Carl")) == [1, 1, 2]
    assert driver_numbers(("alice", "", "Dan"), base, 3, ("Alice", "Bob", "Carl")) == [1, 0, 3]
    # More names than drivers: unknown
    assert driver_numbers(("A", "B", "C", "D"), base, 3) == [1, 2, 3, 0]


def test_rest_of_race_follows_real_drivers():
    """Alice drove a double stint where the plan had Bob: Bob still needs his whole minimum"""
    setup = replace(THREE, driver_names=("Alice", "Bob", "Carl"))
    base = plan(setup)
    state = RaceState(50, 0.0, 5100.0, 16500.0, 50.0, 0.0, 0.0, 2, last_stop_lap=48, last_stop_clock=4950.0,
                      stint_drivers=("Alice", "Alice", "Bob"), stint_seconds=(2400.0, 2400.0))
    rest = remaining_input(setup, base, state)
    assert rest.driver_start == 2  # Bob in the car
    assert rest.driver_seconds_done[0] == 4800.0  # Alice: both stints seen
    assert rest.driver_seconds_done[1] == rest.stint_seconds_done == 150.0  # Bob: stint in progress
    assert rest.driver_seconds_done[2] == 0.0
    assert rest.driver_stints_done == 0
    rest_plan = plan(rest)
    assert rest_plan.ready and not any(kind == "min" for _, kind in rest_plan.driver_issues)


def test_rest_of_race_without_names_keeps_plan():
    base = plan(THREE)
    state = RaceState(30, 0.0, 3100.0, 18500.0, 50.0, 0.0, 0.0, 1)
    rest = remaining_input(THREE, base, state)
    assert rest.driver_start == base.driver_of(1)
    assert rest.driver_seconds_done[0] == base.stint_seconds[0]


def test_driver_names_from_values():
    from neopedal.fuel_strategy import strategy_input_from_values

    values = {"input_drivers": 2, "input_driver_names": "Alice\n Bob \nCarl"}
    assert strategy_input_from_values(values).driver_names == ("Alice", "Bob")
    assert strategy_input_from_values({"input_drivers": 2}).driver_names == ()


# --- Penalties & pending repair
TIMED = StrategyInput(laptime=100, race_minutes=60, tank_capacity=100, fuel_per_lap=4.0, pit_seconds=40,
                      refuel_rate=2.0)


def test_penalty_costs_race_time():
    base = plan(TIMED)
    state = RaceState(10, 0.0, 1000.0, 2600.0, 60.0, 0.0, 0.0, 0)
    plain = remaining_input(TIMED, base, state)
    penalty = remaining_input(TIMED, base, state._replace(penalties=1, penalty_seconds=10.0))
    assert state._replace(penalties=1, penalty_seconds=10.0).penalty_loss(40) == 50.0
    assert plain.race_minutes * 60 - penalty.race_minutes * 60 == 50.0
    assert plan(penalty).race_laps <= plan(plain).race_laps
    # Lap race: same laps
    laps = replace(TIMED, race_minutes=0, race_laps=40)
    assert remaining_input(laps, plan(laps), state._replace(penalties=2)).race_laps == 30


def test_repair_lengthens_next_stop_only():
    base = plan(TIMED)
    state = RaceState(10, 0.0, 1000.0, 2600.0, 20.0, 0.0, 0.0, 0)
    plain = plan(remaining_input(TIMED, base, state))
    repaired = plan(remaining_input(TIMED, base, state._replace(repair_seconds=30.0)))
    assert plain.stops and repaired.stops
    def lost(stop):  # time of the stop but refuelling (race shorter: less fuel)
        return stop.seconds - stop.refuel_seconds

    assert lost(repaired.stops[0]) == lost(plain.stops[0]) + 30.0
    assert all(lost(a) == lost(b) for a, b in zip(plain.stops[1:], repaired.stops[1:]))


def test_replan_key_follows_penalties_and_repair():
    state = RaceState(10, 0.3, 1000.0, 2600.0, 20.0, 0.0, 0.0, 1)
    assert state.replan_key() != state._replace(penalties=1).replan_key()
    assert state.replan_key() != state._replace(repair_seconds=12.0).replan_key()
    assert state.replan_key() == state._replace(lap_progress=0.6).replan_key()


def test_summary_shows_penalty_and_repair():
    from neopedal.ui.quick import race_results

    base = plan(TIMED)
    state = RaceState(10, 0.0, 1000.0, 2600.0, 20.0, 0.0, 0.0, 0, penalties=1, penalty_seconds=10.0,
                      repair_seconds=30.0)
    rest = plan(remaining_input(TIMED, base, state))
    text = race_results.summary(rest, state, 40.0)["text"]
    assert "1 penalty(ies) to serve: 50 s counted" in text and "repair 30 s at next stop" in text


def test_race_state_reads_penalty_and_repair(ui_env, monkeypatch):
    from neopedal.api_control import api
    from neopedal.penalty_info import Penalty
    from neopedal.race_live import read_race_state
    from tests.test_race_calculator import live_race

    live_race(monkeypatch, laps_done=12, stops=0)
    monkeypatch.setattr(api.read.vehicle, "number_penalties", lambda index=None: 1, raising=False)
    monkeypatch.setattr(api.read.vehicle, "penalty", lambda index=None: Penalty(1, "Stop/Go", 10), raising=False)
    monkeypatch.setattr(api.read.vehicle, "repair_time", lambda: 25.0, raising=False)
    state = read_race_state(float, StopCounter()).state
    assert state is not None
    assert (state.penalties, state.penalty_seconds, state.repair_seconds) == (1, 10.0, 25.0)
    monkeypatch.setattr(api.read.vehicle, "penalty", lambda index=None: Penalty(1, "Drive Thru", 0), raising=False)
    assert read_race_state(float, StopCounter()).state.penalty_seconds == 0.0


# --- Race plan overlay: lap time & consumption of the race so far
def history(count: int, fuel: float = 4.5, laptime: float = 90.0, energy: float = 0.0):
    from neopedal.module_info import ConsumptionDataSet

    return tuple(ConsumptionDataSet(lapNumber=30 - index, isValidLap=1, lapTimeLast=laptime, lastLapUsedFuel=fuel,
                                    lastLapUsedEnergy=energy, capacityFuel=45.0) for index in range(count))


def test_measured_input():
    from neopedal.fuel_strategy import measured_input

    setup = StrategyInput(laptime=100, race_laps=40, tank_capacity=45, fuel_per_lap=3.0)
    assert measured_input(setup, history(2)) == setup  # fewer than 3 laps: kept
    measured = measured_input(setup, history(5))
    assert (measured.laptime, measured.fuel_per_lap, measured.energy_per_lap) == (90.0, 4.5, 0.0)
    assert measured_input(setup, history(5), lambda liters: liters / 2).fuel_per_lap == 2.25  # display unit
    energy_only = StrategyInput(laptime=100, race_laps=40, energy_per_lap=3.0)
    measured = measured_input(energy_only, history(5, energy=4.0))
    assert (measured.fuel_per_lap, measured.energy_per_lap) == (0.0, 4.0)  # no fuel planned for that car


def test_race_plan_widget_live_consumption(ui_env, monkeypatch, host):  # noqa: F811
    from neopedal.module_info import minfo
    from neopedal.setting import cfg
    from tests.test_race_calculator import closed_page, live_race, race_plan_widget, set_race

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    closed_page(lambda backend: set_race(backend, laps=40))  # 3.0 per lap, 15 laps a tank
    monkeypatch.setattr(minfo.history, "consumptionDataSet", history(5))  # 4.5 per lap in the race
    live_race(monkeypatch, laps_done=20, fuel=9.0, stops=1)
    cfg.user.setting["race_plan"]["enable_live_replan"] = True
    cfg.user.setting["race_plan"]["enable_live_consumption"] = False
    widget = race_plan_widget(monkeypatch, completed=20)
    try:
        assert widget.bar_next_stop.text == "PIT L23(3)"  # 9.0 at 3.0 per lap
    finally:
        widget.deleteLater()
    cfg.user.setting["race_plan"]["enable_live_consumption"] = True
    widget = race_plan_widget(monkeypatch, completed=20)
    try:
        assert widget.bar_next_stop.text == "PIT L22(2)"  # 9.0 at 4.5 per lap
    finally:
        widget.deleteLater()
