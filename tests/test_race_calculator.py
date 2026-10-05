"""Race calculator: fuel strategy & tyre plan linked in one page, former tools redirected, live race,
race plan files, share code, plan of car & track, QML page"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tinypedal.module_info import minfo
from tinypedal.setting import cfg


class Host:
    """Dialogs answered by the test: warnings & toasts kept, questions answered yes"""

    def __init__(self):
        self.warnings: list[str] = []
        self.toasts: list[str] = []
        self.open_path = ""
        self.save_path = ""
        self.text = ("", False)
        self.asked: list[str] = []


@pytest.fixture
def host(monkeypatch):
    from tinypedal.ui import race_calculator
    from tinypedal.ui.quick import race_backend

    found = Host()
    monkeypatch.setattr(race_calculator.RaceCalculator, "warn", lambda self, text: found.warnings.append(text))
    monkeypatch.setattr(race_calculator.RaceCalculator, "toast", lambda self, text: found.toasts.append(text))
    monkeypatch.setattr(race_calculator.RaceCalculator, "confirm", lambda self, text: found.asked.append(text) or True)
    monkeypatch.setattr(race_calculator.RaceCalculator, "open_file", lambda self, *args: found.open_path)
    monkeypatch.setattr(race_calculator.RaceCalculator, "save_file", lambda self, *args: found.save_path)
    monkeypatch.setattr(race_calculator.RaceCalculator, "ask_text", lambda self, *args: found.text)
    monkeypatch.setattr(race_backend, "SCENARIO_DELAY_MS", 0)  # scenarios at once, not after a pause
    return found


@pytest.fixture
def page(ui_env, monkeypatch, host):
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    dialog = race_calculator.RaceCalculator(None)
    yield dialog
    dialog.set_unmodified()
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def set_race(backend, laptime=90.0, tank=45.0, fuel=3.0, minutes=0, laps=0, pit=0.0, wear=0.0, minimum=0.0,
             energy=0.0):
    backend.set_values({
        "input_lap_time": laptime, "input_tank_capacity": tank, "input_fuel_per_lap": fuel,
        "input_energy_per_lap": energy, "input_pit_seconds": pit, "input_race_minutes": minutes,
        "input_race_laps": laps, "enable_lap_race": laps > 0, "input_wear_per_lap": wear,
        "input_minimum_tread": minimum,
    })


def tile(backend, key: str) -> dict:
    return next(item for item in backend.tiles if item["key"] == key)


def cell(backend, row: int, column: str) -> str:
    from tinypedal.ui.quick.race_results import PLAN_COLUMNS

    return backend.plan["rows"][row][PLAN_COLUMNS.index(column)]


def test_one_page_three_tabs(page):
    from tinypedal.ui.quick.race_backend import TABS

    backend = page.backend
    assert TABS == ("fuel", "tyres", "team")
    backend.setTab(1)
    assert backend.header["tab"] == 1 and cfg.user.config["fuel_calculator"]["race_tab"] == 1
    backend.setTab(7)  # out of range: kept
    assert backend.header["tab"] == 1
    backend.setTab(0)


def test_tyre_plan_rows_follow_stints(page):
    backend = page.backend
    tyres = backend.tyres
    assert not tyres.linked and backend.tyrePlan["rows"][0]["label"] == "1"  # manual plan
    set_race(backend, laps=40)  # 15, 15, 10 laps
    assert tyres.linked and len(tyres.rows) == 3
    assert backend.tyrePlan["rows"][2]["label"] == "3  (31-40)"
    assert not page.is_modified()  # not a user edit
    set_race(backend, laps=20)
    assert len(tyres.rows) == 2
    backend.resetValues()  # no strategy: manual plan again, rows kept
    assert not tyres.linked and len(tyres.rows) == 2


def test_proposed_tyre_changes(page):
    backend = page.backend
    set_race(backend, laps=40, wear=4.0, minimum=20)
    assert backend.proposed_tyre_rows == [1, 2]  # 40% tread used per stint
    backend.setStockCompound("Medium")
    backend.setTyreRule("maximum_tyre", 12)
    backend.proposeChanges()
    rows = backend.tyres.rows
    assert rows[0] == ["Medium #1", "Medium #2", "Medium #3", "Medium #4"]
    assert rows[1][0] == "Medium #5" and rows[2][0] == "Medium #9"
    assert page.is_modified()
    # Strategy shows the plan's changes: stop 1 & 2 with 4 tyres, tile counts tyres
    assert backend.strategy.tyre_changes == [4, 4]
    assert cell(backend, 1, "tyres") == "Change (4)"
    assert tile(backend, "tyres")["value"] == "12 / 12" and not tile(backend, "tyres")["warning"]
    # Proposing again: no extra stock (tyres of last proposal reused or removed)
    backend.proposeChanges()
    assert len(backend.tyres.stock) == 12


def test_proposal_within_tyres_allowed(page):
    backend = page.backend
    set_race(backend, laps=40, wear=4.0, minimum=20)  # 60% per 15 laps stint
    backend.setStockCompound("Medium")
    backend.setTyreRule("maximum_tyre", 8)  # one change only
    backend.proposeChanges()
    rows = backend.tyres.rows
    assert rows[1][0] == "Medium #5" and rows[2][0] == "Medium #5"  # last stint on worn tyres
    assert len(backend.tyres.stock) == 8
    assert "3" in backend.tyrePlan["proposal"]  # stint 3 short of tyres
    assert tile(backend, "tyres")["value"] == "8 / 8"


def test_proposal_reuses_worn_tyres(page):
    backend = page.backend
    set_race(backend, laps=40)
    backend.setStockCompound("Hard")  # 20% per stint
    backend.setTyreRule("maximum_tyre", 4)
    backend.setInput("input_minimum_tread", 70)  # second stint would want new tyres: none allowed
    backend.proposeChanges()
    rows = backend.tyres.rows
    assert rows[0] == rows[1] == rows[2] == ["Hard #1", "Hard #2", "Hard #3", "Hard #4"]  # nothing better


def test_two_tyre_change_when_rears_wear_more(page):
    backend = page.backend
    set_race(backend, laps=40)
    backend.tyres.user_data["tyre_set"]["Medium"].update(rear_left_wear_per_stint=50, rear_right_wear_per_stint=50)
    backend.setStockCompound("Medium")
    backend.setTyreRule("maximum_tyre", 20)
    backend.setInput("input_minimum_tread", 30)
    backend.proposeChanges()
    rows = backend.tyres.rows
    assert rows[1][:2] == rows[0][:2] and rows[1][2:] != rows[0][2:]  # rears only
    assert backend.tyres.stop_change_times()[0] == pytest.approx(4.5)  # 2 tyres change time


def test_tyre_change_time_costs_laps_in_time_race(page):
    backend = page.backend
    set_race(backend, laptime=100.0, tank=60.0, fuel=3.0, minutes=60, pit=30)
    laps_without = backend.strategy.race_laps
    stops = len(backend.strategy.stops)
    assert stops and backend.tyres.stop_change_times() == [0.0] * stops  # no tyre plan: no tyre time
    backend.setTyreRule("tyre_change_time_4", 80.0)
    backend.setTyreRule("maximum_tyre", 40)
    backend.proposeChanges()  # new tyres at start only (no wear): no change at stops
    assert backend.strategy.race_laps == laps_without
    backend.set_values({"input_wear_per_lap": 5.0, "input_minimum_tread": 10})
    backend.proposeChanges()  # tyres changed at stop: 80 s more in the pits
    assert backend.tyres.stop_change_times()[0] == pytest.approx(80.0)
    assert backend.strategy.race_laps < laps_without


def test_tyre_plan_kept_between_sessions(page, monkeypatch):
    from tinypedal.ui import race_calculator

    backend = page.backend
    set_race(backend, laps=40)
    backend.proposeChanges()
    rows = [list(row) for row in backend.tyres.rows]
    asked = []
    monkeypatch.setattr(race_calculator.QMessageBox, "question", staticmethod(lambda *args, **kwargs: asked.append(1)))
    page.close()
    assert not asked  # saved automatically: nothing asked
    other = race_calculator.RaceCalculator(None)
    try:
        assert other.backend.tyres.rows == rows
    finally:
        other.close()
        other.deleteLater()


def test_rows_kept_aside_while_typing(page):
    backend = page.backend
    set_race(backend, laps=40)  # 3 stints
    backend.setTyreRule("maximum_tyre", 12)
    backend.proposeChanges()
    before = [list(row) for row in backend.tyres.rows]
    backend.setInput("input_race_laps", 4)  # 1 stint for a moment: rows kept aside, not lost
    assert len(backend.tyres.rows) == 1
    backend.setInput("input_race_laps", 40)
    assert backend.tyres.rows == before


def test_tyre_plan_undo_redo(page):
    backend = page.backend
    set_race(backend, laps=40)
    before = [list(row) for row in backend.tyres.rows]
    backend.proposeChanges()
    proposed = [list(row) for row in backend.tyres.rows]
    assert proposed != before
    backend.undo()
    assert backend.tyres.rows == before
    backend.redo()
    assert backend.tyres.rows == proposed


def test_former_tools_open_race_calculator(ui_env):
    from tinypedal.ui.nav_rail import parse_rail_items
    from tinypedal.ui.tools_view import RENAMED_TOOLS

    assert set(RENAMED_TOOLS.values()) == {"race_calculator.RaceCalculator"}
    assert parse_rail_items("tyre_strategy_planner") == ["race_calculator"]


def test_linked_wear_from_wear_per_lap(page):
    backend = page.backend
    set_race(backend, laps=40)  # stints of 15, 15, 10 laps
    backend.setStockCompound("Soft")  # compound: 40% per stint
    backend.setInput("input_measured_compound", list(backend.measuredCompounds).index("Soft"))  # no scaling
    backend.proposeChanges()  # same tyres all race
    cells = backend.tyres.cells
    assert cells[2][0]["remaining"] == pytest.approx(1.0 - 0.8)  # compound wear per stint
    backend.setInput("input_wear_per_lap", 2.0)  # measured: 2% per lap
    cells = backend.tyres.cells
    assert cells[1][0]["remaining"] == pytest.approx(1.0 - 0.30)  # 15 laps
    assert cells[2][0]["end"] == pytest.approx(1.0 - 0.80)  # 15 + 15 + 10 laps
    assert backend.tyrePlan["rows"][1]["cells"][0]["text"] == "70-40%"


def test_wear_scaled_by_compound(page):
    backend = page.backend
    set_race(backend, laps=40)
    backend.setStockCompound("Hard")  # 20% per stint
    backend.setInput("input_measured_compound", list(backend.measuredCompounds).index("Medium"))  # 30% per stint
    backend.proposeChanges()
    backend.setInput("input_wear_per_lap", 3.0)
    assert backend.tyres.cells[1][0]["remaining"] == pytest.approx(1.0 - 0.30)  # 15 laps x 2%
    assert backend.tyres.wear_factor() == pytest.approx(2 / 3)


def test_stock_compound_drives_proposed_stops(page):
    backend = page.backend
    # Default: compound of measured wear, wear per lap used as measured
    assert backend.tyres.compound == backend.tyres.measured
    assert backend.tyres.wear_factor() == pytest.approx(1.0)
    set_race(backend, laps=40, wear=2.0, minimum=40)  # 30% per 15 laps stint: change at 2nd stop only
    assert backend.proposed_tyre_rows == [2]
    backend.setStockCompound("Ultrasoft")  # wears 80/30 as much
    assert backend.proposed_tyre_rows == [1, 2]  # strategy follows the compound at once


def test_race_plan_loaded_in_one_calculation(page, host, tmp_path):
    backend = page.backend
    set_race(backend, laps=40)
    backend.setTyreRule("maximum_tyre", 12)
    backend.proposeChanges()
    rows = [list(row) for row in backend.tyres.rows]
    target = tmp_path / "plan.race-plan"
    host.save_path = str(target)
    backend.saveRacePlan()
    backend.setInput("input_race_laps", 4)  # 1 stint: rows of this plan kept aside
    calculations = backend.calculations
    host.open_path = str(target)
    backend.openRacePlan()
    assert backend.calculations == calculations + 1
    assert backend.tyres.rows == rows and not backend.tyres.spare_rows


def test_starting_tread_from_tyre_plan(page):
    backend = page.backend
    set_race(backend, laps=40)
    backend.setStockCompound("Q-Soft")  # 90% starting tread
    backend.proposeChanges()
    assert backend.tyres.start_tread(100.0) == pytest.approx(90.0)
    assert backend.tyres.fresh_tread() == pytest.approx(90.0)


def test_tyre_cells_assigned_and_checked(page, host):
    backend = page.backend
    for _ in range(4):
        backend.addTyre()
    assert backend.tyres.stock == ["Medium #1", "Medium #2", "Medium #3", "Medium #4"]
    backend.assignTyre(0, 0, "Medium #1")
    assert backend.tyres.rows[0][0] == "Medium #1" and page.is_modified()
    backend.assignTyre(0, 1, "Medium #1")  # same tyre on two wheels of a stint
    assert backend.tyres.rows[0][1] == "" and "already installed" in host.toasts[-1]
    backend.addRow()
    backend.assignTyre(1, 1, "Medium #1")  # restricted allocation: stays on its wheel
    assert backend.tyres.rows[1][1] == "" and "already used" in host.toasts[-1]
    backend.setTyreRule("enable_restricted_allocation", False)
    backend.assignTyre(1, 1, "Medium #1")
    assert backend.tyres.rows[1][1] == "Medium #1"
    backend.clearTyre(1, 1)
    assert backend.tyres.rows[1] == ["", "", "", ""]
    backend.duplicateRow(0)
    assert backend.tyres.rows[1][0] == "Medium #1" and len(backend.tyres.rows) == 3
    backend.insertRow(0, True)
    assert backend.tyres.rows[0] == ["", "", "", ""] and len(backend.tyres.rows) == 4
    backend.deleteRow(0)
    backend.clearRow(0)
    assert backend.tyres.rows[0] == ["", "", "", ""]
    backend.assignTyre(0, 0, "Soft #9")  # not in stock
    assert backend.tyres.rows[0][0] == ""


def test_tyre_stock_sorted_and_cleaned(page, host):
    backend = page.backend
    backend.setStockCompound("Medium")
    backend.addTyre()
    backend.setStockCompound("Soft")
    backend.addTyre()
    backend.addTyre()
    backend.assignTyre(0, 0, "Soft #2")
    backend.sortStock(False)  # compound order
    assert backend.tyres.stock == ["Soft #1", "Soft #2", "Medium #1"]
    backend.sortStock(True)  # stints run first
    assert backend.tyres.stock[0] == "Soft #2"
    stock = {item["name"]: item["stints"] for item in backend.tyrePlan["stock"]}
    assert stock["Soft #2"] == 1 and stock["Medium #1"] == 0
    backend.removeUnusedTyres()
    assert backend.tyres.stock == ["Soft #2"]
    backend.removeTyre("Soft #2")  # off the plan too
    assert not backend.tyres.stock and backend.tyres.rows[0][0] == ""
    backend.addTyre()
    backend.clearTyres()
    assert not backend.tyres.stock


def test_tyre_rules_kept_in_range(page):
    backend = page.backend
    backend.setTyreRule("maximum_tyre", 10 ** 9)
    backend.setTyreRule("tyre_change_time_1", float("nan"))
    backend.setTyreRule("tyre_change_time_2", "slow")  # not a number: ignored
    backend.setTyreRule("unknown", 3)
    rule = backend.tyrePlan["rule"]
    assert rule["maximum_tyre"] == 999 and rule["tyre_change_time_1"] == 0.0
    assert rule["tyre_change_time_2"] == 4.5 and "unknown" not in rule


def test_race_plan_widget(ui_env, monkeypatch, host):
    from tinypedal.api_control import api
    from tinypedal.ui import race_calculator
    from tinypedal.widget import race_plan

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    page = race_calculator.RaceCalculator(None)  # plan made in race calculator, kept in config
    backend = page.backend
    set_race(backend, laps=40, wear=4.0, minimum=20)  # stops at laps 15 & 30
    backend.setTyreRule("maximum_tyre", 12)
    backend.proposeChanges()
    page.set_unmodified()
    page.close()
    page.deleteLater()

    cfg.user.setting["race_plan"]["show_energy"] = True
    widget = race_plan.Realtime(cfg, "race_plan")
    try:
        monkeypatch.setattr(type(api.read.lap), "completed_laps", lambda self, index=None: 13, raising=False)
        widget.timerEvent(None)
        assert widget.bar_next_stop.text == "PIT L15(2)"
        window_color = widget.bar_next_stop.bg  # 2 laps to go: pit window color
        assert widget.bar_refuel.text == "+45.0L"
        assert widget.bar_tyres.text == "TYRE 4"
        assert widget.bar_stops_left.text == "STOP 2/2"
        monkeypatch.setattr(type(api.read.lap), "completed_laps", lambda self, index=None: 35, raising=False)
        widget.timerEvent(None)
        assert widget.bar_next_stop.text == "PIT END" and widget.bar_stops_left.text == "STOP 0/2"
        assert widget.bar_next_stop.bg != window_color
    finally:
        widget.deleteLater()


def live_race(monkeypatch, laps_done=20, fuel=9.0, stops=1, in_pits=False, combo="Spa - GT3"):
    """Game in a race: player car state"""
    from tinypedal.api_control import api

    values = {
        (api.read.state, "active"): True, (api.read.session, "combo_name"): combo,
        (api.read.session, "session_type"): 4, (api.read.session, "in_race"): True,
        (api.read.session, "elapsed"): 1800.0, (api.read.session, "start"): 0.0,
        (api.read.session, "remaining"): 0.0, (api.read.lap, "completed_laps"): laps_done,
        (api.read.lap, "progress"): 0.0, (api.read.engine, "fuel"): fuel,
        (api.read.engine, "virtual_energy"): 0.0, (api.read.tyre, "wear"): (1.0, 1.0, 1.0, 1.0),
        (api.read.vehicle, "number_pitstops"): stops, (api.read.vehicle, "in_pits"): in_pits,
    }
    for (group, name), value in values.items():
        monkeypatch.setattr(group, name, lambda *args, value=value, **kwargs: value, raising=False)


def test_live_race_plans_rest_of_race(page, monkeypatch):
    backend = page.backend
    set_race(backend, laps=40)  # stops at 15 & 30
    rows = len(backend.tyres.rows)
    live_race(monkeypatch, laps_done=20, fuel=9.0, stops=1)  # 3 laps of fuel left
    backend.setLiveRace(True)
    assert backend.strategy.first_lap == 20 and [stop.lap for stop in backend.strategy.stops] == [23, 38]
    assert "Live Race" in backend.summary["text"] and cell(backend, 0, "stop") == "Now"
    assert cell(backend, 1, "stop") == "2"  # stop 2 of the race
    assert len(backend.tyres.rows) == rows  # tyre plan of the race kept
    backend.setLiveRace(False)
    assert backend.strategy.first_lap == 0 and [stop.lap for stop in backend.strategy.stops] == [15, 30]


def test_plan_of_car_and_track_opened_again(page, host, monkeypatch):
    from tinypedal.ui import race_calculator

    backend = page.backend
    live_race(monkeypatch, laps_done=0)
    set_race(backend, laps=40)
    backend.saveComboPlan()
    backend.setInput("input_race_laps", 25)  # other plan meanwhile
    other = race_calculator.RaceCalculator(None)  # car & track driven: its plan opened
    try:
        assert other.backend.values["input_race_laps"] == 40
        assert any("Race plan of Spa - GT3 opened" in text for text in host.toasts)
    finally:
        other.set_unmodified()
        other.close()
        other.deleteLater()


def test_page_keeps_inputs_of_race_plan(page, monkeypatch, tmp_path):
    from tinypedal.module_info import ConsumptionDataSet
    from tinypedal.ui import race_calculator

    backend = page.backend
    set_race(backend, laptime=100.0, laps=40)
    target = tmp_path / "plan.race-plan"
    backend.save_race_plan(str(target))
    assert backend.load_race_plan(str(target))
    laps = tuple(ConsumptionDataSet(10 - index, 1, 90.0, 2.5) for index in range(5))
    monkeypatch.setattr(minfo.history, "consumptionDataSet", laps)
    other = race_calculator.RaceCalculator(None)  # live laps shown, plan inputs kept
    try:
        assert other.backend.values["input_lap_time"] == pytest.approx(100.0)
        assert len(other.backend.history["rows"]) == 5
        other.backend.loadLive()  # asked: live laps filled in
        assert other.backend.values["input_lap_time"] == pytest.approx(90.0)
        assert cfg.user.config["fuel_calculator"]["enable_plan_inputs"] is False
    finally:
        other.set_unmodified()
        other.close()
        other.deleteLater()


def test_tyre_plan_not_refreshed_for_same_stints(page, monkeypatch):
    backend = page.backend
    set_race(backend, laps=40)
    refreshed = []
    real_refresh = backend.tyres.refresh
    monkeypatch.setattr(backend.tyres, "refresh", lambda: refreshed.append(1) or real_refresh())
    backend.setInput("input_pit_seconds", 45)  # lap race: same stints
    assert not refreshed
    backend.setInput("input_race_laps", 50)
    assert refreshed and len(backend.tyres.rows) == 4


def race_plan_widget(monkeypatch, completed: int, in_pits: bool = False):
    from tinypedal.api_control import api
    from tinypedal.widget import race_plan

    monkeypatch.setattr(api.read.lap, "completed_laps", lambda *args, **kwargs: completed, raising=False)
    monkeypatch.setattr(api.read.vehicle, "in_pits", lambda *args, **kwargs: in_pits, raising=False)
    widget = race_plan.Realtime(cfg, "race_plan")
    widget.timerEvent(None)
    return widget


def closed_page(set_values):
    """Race calculator opened, inputs set, closed: plan input written for the race plan widget"""
    from tinypedal.ui import race_calculator

    page = race_calculator.RaceCalculator(None)
    set_values(page.backend)
    page.set_unmodified()
    page.close()
    page.deleteLater()


def test_race_plan_widget_same_plan_as_calculator(ui_env, monkeypatch, host):
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())

    def values(backend):
        set_race(backend, laps=40, wear=2.0, minimum=40)  # measured on medium: tyres at stop 2 only
        backend.setStockCompound("Ultrasoft")  # wears more: stops 1 & 2
        assert backend.proposed_tyre_rows == [1, 2]

    closed_page(values)
    widget = race_plan_widget(monkeypatch, completed=13)
    try:
        assert widget.bar_tyres.text == "TYRE 4"  # stop 1 with tyres, as in the race calculator
    finally:
        widget.deleteLater()


def test_race_plan_widget_in_pits_and_live(ui_env, monkeypatch, host):
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    closed_page(lambda backend: set_race(backend, laps=40))  # stops at 15 & 30
    cfg.user.setting["race_plan"]["enable_live_replan"] = False
    widget = race_plan_widget(monkeypatch, completed=15, in_pits=True)  # line crossed before the box
    try:
        assert widget.bar_next_stop.text == "PIT L15(0)" and widget.bar_stops_left.text == "STOP 2/2"
    finally:
        widget.deleteLater()
    cfg.user.setting["race_plan"]["enable_live_replan"] = True
    live_race(monkeypatch, laps_done=20, fuel=9.0, stops=1)
    widget = race_plan_widget(monkeypatch, completed=20)
    try:
        assert widget.bar_next_stop.text == "PIT L23(3)"  # rest of race: 3 laps of fuel left
        assert widget.bar_stops_left.text == "STOP 2/3"
    finally:
        widget.deleteLater()


def test_inputs_undo_redo(page):
    backend = page.backend
    set_race(backend, laps=40)
    backend.setInput("input_race_laps", 50)
    backend.undo()
    assert backend.values["input_race_laps"] == 40 and backend.strategy.race_laps == 40
    backend.redo()
    assert backend.values["input_race_laps"] == 50


def test_live_race_status_shown(page, monkeypatch):
    from tinypedal.api_control import api

    backend = page.backend
    backend.setLiveRace(True)
    assert backend.header["liveStatus"] == "waiting for the race"
    live_race(monkeypatch, laps_done=20, fuel=9.0, stops=1)
    set_race(backend, laps=40)
    backend.refresh_race_state()
    assert backend.header["liveStatus"] == "from lap 21"
    assert "9.0 L" in backend.header["liveTip"]  # values read from the game, to check them
    monkeypatch.setattr(api.read.vehicle, "in_pits", lambda *args, **kwargs: True, raising=False)
    backend.refresh_race_state()
    assert "in the pits" in backend.header["liveStatus"]


def test_share_code_round_trip(page, host):
    from PySide6.QtGui import QGuiApplication

    backend = page.backend
    set_race(backend, laps=40)
    backend.copyShareCode()
    code = QGuiApplication.clipboard().text()
    assert code.startswith("TPRP1:") and "\n" not in code and host.toasts
    backend.setInput("input_race_laps", 25)
    host.text = (code[:30] + "\n" + code[30:], True)  # wrapped by a chat
    backend.pasteShareCode()
    assert backend.values["input_race_laps"] == 40
    host.text = ("nope", True)
    backend.pasteShareCode()
    assert host.warnings and backend.values["input_race_laps"] == 40
    host.text = ("", False)  # cancelled
    backend.pasteShareCode()
    assert len(host.warnings) == 1


def test_plan_against_race_and_rivals(page, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.module_info import StintDataSet

    backend = page.backend
    live_race(monkeypatch, laps_done=20)
    stints = (StintDataSet(), StintDataSet(15, 1365.0, 46.5, 0.0, 30.0))  # newest first, placeholder
    monkeypatch.setattr(minfo.history, "stintDataSet", stints)
    set_race(backend, laps=40)
    against = backend.planVsRace
    assert against["visible"] and against["rows"][0][2] == "15 / 15"
    assert against["rows"][0][4] == "3.100 / 3.000"
    names = ("You", "Rival A", "Rival B")
    for name, function in (
        ("total_vehicles", lambda *args, **kwargs: 3), ("player_index", lambda *args, **kwargs: 0),
        ("same_class", lambda index=None: True), ("driver_name", lambda index=None: names[index]),
        ("number_pitstops", lambda index=None, **kwargs: (1, 2, 1)[index]),
        ("place", lambda index=None: (2, 1, 3)[index]), ("in_pits", lambda index=None: index == 2),
    ):
        monkeypatch.setattr(api.read.vehicle, name, function, raising=False)
    monkeypatch.setattr(api.read.lap, "completed_laps", lambda index=None: (20, 21, 19)[index or 0], raising=False)
    backend.refresh_rivals()
    rivals = backend.rivals
    assert rivals["visible"] and len(rivals["rows"]) == 3
    assert rivals["rows"][0][1] == "Rival A" and rivals["rows"][2][3] == "1 (pit)" and rivals["player"] == 1


def test_race_plan_widget_pit_menu_and_target(ui_env, monkeypatch, host):
    from tinypedal.api_control import api

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    closed_page(lambda backend: set_race(backend, laps=40))  # stops at 15 (45 L after) & 30 (30 L after)
    cfg.user.setting["race_plan"]["enable_live_replan"] = False
    monkeypatch.setattr(api.read.vehicle, "absolute_refill", lambda *args, **kwargs: 45.0, raising=False)
    monkeypatch.setattr(api.read.engine, "fuel", lambda *args, **kwargs: 12.0, raising=False)
    monkeypatch.setattr(minfo.fuel, "lastLapConsumption", 3.1)
    widget = race_plan_widget(monkeypatch, completed=11)  # 4 laps to stop at 15
    try:
        assert widget.bar_pit_menu.text == "MENU OK"
        assert widget.bar_target.text == "TGT 3.00"  # 12 L for 4 laps
        assert widget.bar_target.last[1] == widget.wcfg["warning_color_target"]  # last lap used 3.1
        monkeypatch.setattr(api.read.vehicle, "absolute_refill", lambda *args, **kwargs: 30.0, raising=False)
        widget.timerEvent(None)
        assert widget.bar_pit_menu.text == "MENU 30>45L"
    finally:
        widget.deleteLater()
    widget = race_plan_widget(monkeypatch, completed=14, in_pits=True)  # line after the pit box
    try:
        assert widget.bar_next_stop.text == "PIT L15(1)"
    finally:
        widget.deleteLater()


def test_sections_folded_and_kept(page):
    backend = page.backend
    backend.setSectionCollapsed("pace", True)
    backend.setSectionCollapsed("rain", True)
    assert backend.header["collapsed"] == ["pace", "rain"]
    backend.setSectionCollapsed("pace", False)
    assert cfg.user.config["fuel_calculator"]["collapsed_sections"] == "rain"


# QML page
def find_item(root, name: str):
    """First item of the QML page with a property of that name"""
    stack = [root]
    while stack:
        item = stack.pop()
        if item.property(name) is not None:
            return item
        stack.extend(item.childItems())
    return None


def test_qml_page_loads_and_shows_results(page):
    page.show()  # QML page built when first shown, layouts done while shown
    view = page.ensure_view()
    assert view is not None and not view.errors() and view.rootObject() is not None
    set_race(page.backend, laps=40, wear=4.0, minimum=20)
    QCoreApplication.processEvents()
    timeline = find_item(view.rootObject(), "barWidth")
    assert timeline is not None
    page.resize(1200, 800)
    view.resize(1200, 800)
    QCoreApplication.processEvents()
    labels = timeline.property("labels").toVariant() if hasattr(timeline.property("labels"), "toVariant") \
        else timeline.property("labels")
    assert [label["text"] for label in labels] == ["Lap 15", "Lap 30"]


def test_timeline_labels_never_overlap(page):
    from itertools import pairwise

    page.show()
    view = page.ensure_view()
    page.backend.set_values({"input_lap_time": 100, "input_race_minutes": 1440, "input_tank_capacity": 20,
                             "input_fuel_per_lap": 3.0, "enable_lap_race": False})
    assert len(page.backend.strategy.stops) > 100  # 24 h: many stops
    view.resize(600, 600)
    QCoreApplication.processEvents()
    timeline = find_item(view.rootObject(), "barWidth")
    labels = timeline.property("labels")
    labels = labels.toVariant() if hasattr(labels, "toVariant") else labels
    assert labels and all(first["x"] + first["width"] <= second["x"] + 0.01
                          for first, second in pairwise(labels))


def test_qml_page_loads_with_bundled_modules(page, tmp_path):
    """Release build bundles only QML_MODULES: the page must load with nothing else on import path"""
    import os
    import shutil

    from PySide6.QtCore import QLibraryInfo
    from PySide6.QtQuickWidgets import QQuickWidget

    from tinypedal.ui.quick import QML_FOLDER
    from tinypedal.ui.quick.qml_modules import QML_MODULES

    source = QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath)
    for module in QML_MODULES:
        target = tmp_path / module
        target.mkdir(parents=True, exist_ok=True)
        for entry in os.scandir(os.path.join(source, module)):
            if entry.is_file():
                shutil.copy2(entry.path, target)
    set_source = QQuickWidget.setSource

    def restricted_source(view, url):
        view.engine().setImportPathList([str(tmp_path), QML_FOLDER])
        set_source(view, url)

    QQuickWidget.setSource = restricted_source
    try:
        view = page.ensure_view()
        assert not view.errors(), [error.toString() for error in view.errors()]
        page.backend.setTab(1)  # tabs built when first shown
        page.backend.setTab(2)
        QCoreApplication.processEvents()
        assert not view.errors()
    finally:
        QQuickWidget.setSource = set_source


def test_qml_page_translated(ui_env, monkeypatch, host):
    """Texts of the QML page in app language, every text of its QML files translated"""
    import glob
    import re

    from tinypedal import i18n
    from tinypedal.i18n.fr import TRANSLATION
    from tinypedal.ui import race_calculator
    from tinypedal.ui.quick import QML_FOLDER

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    pattern = re.compile(r'i18n\.tr\("((?:[^"\\]|\\.)*)"\)')
    missing = []
    for name in glob.glob(f"{QML_FOLDER}/Race*.qml"):
        with open(name, encoding="utf-8") as file:
            missing += [text for text in pattern.findall(file.read()) if text not in TRANSLATION]
    assert not missing
    i18n.set_language("Français")
    page = race_calculator.RaceCalculator(None)
    try:
        view = page.ensure_view()
        page.backend.setTab(1)
        QCoreApplication.processEvents()
        texts, stack = set(), [view.rootObject()]
        while stack:
            item = stack.pop()
            text = item.property("text")
            if isinstance(text, str):
                texts.add(text)
            stack.extend(item.childItems())
        assert {"Tour et consommation", "Plan d'arrêts", "Marge de sécurité", "Plan pneus"} <= texts
        assert "Lap & Consumption" not in texts
    finally:
        i18n.set_language("English")
        page.set_unmodified()
        page.close()
        page.deleteLater()
