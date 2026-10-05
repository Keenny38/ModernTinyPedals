"""Race calculator: fuel strategy & tyre plan linked in one page, former tools redirected"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.ui._common import BaseEditor


@pytest.fixture
def page(ui_env, monkeypatch):
    from tinypedal.ui import fuel_calculator, race_calculator, tyre_strategy_planner

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(fuel_calculator, "SCENARIO_DELAY_MS", 0)  # scenarios at once, not after a pause
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(tyre_strategy_planner, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    dialog = race_calculator.RaceCalculator(None)
    yield dialog
    dialog.set_unmodified()
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def set_race(calc, laptime=90.0, tank=45.0, fuel=3.0, minutes=0, laps=0, pit=0.0, wear=0.0, minimum=0.0):
    with calc.batch():
        calc.input_laptime.set_seconds(laptime)
        calc.input_fuel.capacity.setValue(tank)
        calc.input_fuel.fuel_used.setValue(fuel)
        calc.input_fuel.energy_used.setValue(0)
        calc.input_race.pit_seconds.setValue(pit)
        calc.input_race.minutes.setValue(minutes)
        calc.input_race.laps.setValue(laps)
        calc.input_race.set_lap_race(laps > 0)
        calc.input_tyre.wear_lap.setValue(wear)
        calc.input_tyre.minimum_tread.setValue(minimum)


def test_one_page_three_tabs(page):
    from tinypedal.i18n import tr

    assert [page.tabs.tabText(index) for index in range(page.tabs.count())] == [tr("Fuel"), tr("Tyres"), tr("Team")]
    calc = page.panel_calculator
    assert not page.tabs.isAncestorOf(calc.card_race) and not page.tabs.isAncestorOf(calc.tiles)  # shared on top
    assert page.tabs.widget(1).isAncestorOf(calc.card_tyre_input)  # tyre wear in tyre tab
    assert page.tabs.widget(1).isAncestorOf(calc.card_tyre_life)


def test_tyre_plan_rows_follow_stints(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    assert not planner.linked and not planner.tyre_plan_panel.row_buttons.isHidden()  # manual plan
    set_race(calc, laps=40)  # 15, 15, 10 laps
    table = planner.tyre_plan
    assert planner.linked and table.rowCount() == 3
    assert table.verticalHeaderItem(2).text() == "3  (31-40)"
    assert planner.tyre_plan_panel.row_buttons.isHidden()  # rows set by strategy
    assert not page.is_modified()  # not a user edit
    set_race(calc, laps=20)
    assert table.rowCount() == 2
    calc.reset_inputs()  # no strategy: manual plan again, rows kept
    assert not planner.linked and table.rowCount() == 2


def test_proposed_tyre_changes(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40, wear=4.0, minimum=20)
    assert calc.proposed_tyre_rows == [1, 2]  # 40% tread used per stint
    planner.tyre_set_panel._tyre_selector.setCurrentText("Medium")
    planner.tyre_rule_panel._max_tyre.setValue(12)
    planner.propose_changes()
    plan_rows = planner.tyre_plan.export_to_list()
    assert plan_rows[0] == ["Medium #1", "Medium #2", "Medium #3", "Medium #4"]
    assert plan_rows[1][0] == "Medium #5" and plan_rows[2][0] == "Medium #9"
    assert page.is_modified()
    # Strategy shows the plan's changes: stop 1 & 2 with 4 tyres, tile counts tyres
    assert calc.strategy.tyre_changes == [4, 4]
    assert calc.table_plan.item(1, 6).text() == "Change (4)"
    assert calc.tile_tyres.label_value.text() == "12 / 12"
    assert not calc.tile_tyres.label_value.property("warning")
    # Proposing again: no extra stock (tyres of last proposal reused or removed)
    planner.propose_changes()
    assert planner.tyre_set.count() == 12


def test_proposal_within_tyres_allowed(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40, wear=4.0, minimum=20)  # 60% per 15 laps stint
    planner.tyre_set_panel._tyre_selector.setCurrentText("Medium")
    planner.tyre_rule_panel._max_tyre.setValue(8)  # one change only
    planner.propose_changes()
    rows = planner.tyre_plan.export_to_list()
    assert rows[1][0] == "Medium #5" and rows[2][0] == "Medium #5"  # last stint on worn tyres
    assert planner.tyre_set.count() == 8
    label = planner.tyre_plan_panel.label_proposal
    assert not label.isHidden() and "3" in label.text()  # stint 3 short of tyres
    assert calc.tile_tyres.label_value.text() == "8 / 8"


def test_proposal_reuses_worn_tyres(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)
    planner.tyre_set_panel._tyre_selector.setCurrentText("Hard")  # 20% per stint
    planner.tyre_rule_panel._max_tyre.setValue(4)
    calc.input_tyre.minimum_tread.setValue(70)  # second stint would want new tyres: none allowed
    planner.propose_changes()
    rows = planner.tyre_plan.export_to_list()
    assert rows[0] == rows[1] == rows[2] == ["Hard #1", "Hard #2", "Hard #3", "Hard #4"]  # nothing better


def test_two_tyre_change_when_rears_wear_more(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)
    planner.user_data["tyre_set"]["Medium"].update(rear_left_wear_per_stint=50, rear_right_wear_per_stint=50)
    planner.tyre_set_panel._tyre_selector.setCurrentText("Medium")
    planner.tyre_rule_panel._max_tyre.setValue(20)
    calc.input_tyre.minimum_tread.setValue(30)
    planner.propose_changes()
    rows = planner.tyre_plan.export_to_list()
    assert rows[1][:2] == rows[0][:2] and rows[1][2:] != rows[0][2:]  # rears only
    assert planner.stop_change_times()[0] == pytest.approx(4.5)  # 2 tyres change time


def test_tyre_change_time_costs_laps_in_time_race(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laptime=100.0, tank=60.0, fuel=3.0, minutes=60, pit=30)
    laps_without = calc.strategy.race_laps
    stops = len(calc.strategy.stops)
    assert stops and planner.stop_change_times() == [0.0] * stops  # no tyre plan: no tyre time
    planner.tyre_rule_panel._change_time_4.setValue(80.0)
    planner.tyre_rule_panel._max_tyre.setValue(40)
    planner.propose_changes()  # new tyres at start only (no wear): no change at stops
    assert calc.strategy.race_laps == laps_without
    calc.input_tyre.wear_lap.setValue(5.0)
    calc.input_tyre.minimum_tread.setValue(10)
    planner.propose_changes()  # tyres changed at stop: 80 s more in the pits
    assert planner.stop_change_times()[0] == pytest.approx(80.0)
    assert calc.strategy.race_laps < laps_without


def test_tyre_plan_kept_between_sessions(page, monkeypatch):
    from tinypedal.ui import race_calculator

    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)
    planner.propose_changes()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *args, **kwargs: asked.append(1) or QMessageBox.StandardButton.Cancel))
    page.close()
    assert not asked  # saved automatically: nothing asked
    other = race_calculator.RaceCalculator(None)
    try:
        assert other.tyre_planner.tyre_plan.export_to_list() == planner.tyre_plan.export_to_list()
    finally:
        other.deleteLater()


def test_rows_kept_aside_while_typing(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)  # 3 stints
    planner.tyre_rule_panel._max_tyre.setValue(12)
    planner.propose_changes()
    before = planner.tyre_plan.export_to_list()
    calc.input_race.laps.setValue(4)  # 1 stint for a moment: rows kept aside, not lost
    assert planner.tyre_plan.rowCount() == 1
    calc.input_race.laps.setValue(40)
    assert planner.tyre_plan.export_to_list() == before
    assert not calc.input_race.laps.keyboardTracking()  # typing applied on Enter / leaving box


def test_tyre_plan_undo_redo(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)
    before = planner.tyre_plan.export_to_list()
    planner.propose_changes()
    proposed = planner.tyre_plan.export_to_list()
    assert proposed != before
    page.undo()
    assert planner.tyre_plan.export_to_list() == before
    page.redo()
    assert planner.tyre_plan.export_to_list() == proposed


def test_former_tools_open_race_calculator(ui_env):
    from tinypedal.ui.nav_rail import parse_rail_items
    from tinypedal.ui.tools_view import RENAMED_TOOLS

    assert set(RENAMED_TOOLS.values()) == {"race_calculator.RaceCalculator"}
    assert parse_rail_items("tyre_strategy_planner") == ["race_calculator"]


def test_linked_wear_from_wear_per_lap(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)  # stints of 15, 15, 10 laps
    planner.tyre_set_panel._tyre_selector.setCurrentText("Soft")  # compound: 40% per stint
    planner.combo_measured.setCurrentText("Soft")  # wear measured on soft: no scaling
    planner.propose_changes()  # same tyres all race
    table = planner.tyre_plan
    assert table.cellWidget(2, 0).remaining == pytest.approx(1.0 - 0.8)  # compound wear per stint
    calc.input_tyre.wear_lap.setValue(2.0)  # measured: 2% per lap
    assert table.cellWidget(1, 0).remaining == pytest.approx(1.0 - 0.30)  # 15 laps
    assert table.cellWidget(2, 0).end == pytest.approx(1.0 - 0.80)  # 15 + 15 + 10 laps


def test_wear_scaled_by_compound(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)
    planner.tyre_set_panel._tyre_selector.setCurrentText("Hard")  # 20% per stint
    planner.combo_measured.setCurrentText("Medium")  # 30% per stint: hard wears 2/3 of it
    planner.propose_changes()
    calc.input_tyre.wear_lap.setValue(3.0)
    assert planner.tyre_plan.cellWidget(1, 0).remaining == pytest.approx(1.0 - 0.30)  # 15 laps x 2%
    assert planner.wear_factor() == pytest.approx(2 / 3)


def test_stock_compound_drives_proposed_stops(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    # Default: compound of measured wear, wear per lap used as measured
    assert planner.tyre_set_panel.selected_tyre() == planner.combo_measured.currentText()
    assert planner.wear_factor() == pytest.approx(1.0)
    set_race(calc, laps=40, wear=2.0, minimum=40)  # 30% per 15 laps stint: change at 2nd stop only
    assert calc.proposed_tyre_rows == [2]
    planner.tyre_set_panel._tyre_selector.setCurrentText("Ultrasoft")  # wears 80/30 as much
    assert calc.proposed_tyre_rows == [1, 2]  # strategy follows the compound at once


def test_race_plan_loaded_in_one_calculation(page, monkeypatch, tmp_path):
    from tinypedal.ui import race_calculator

    calc, planner = page.panel_calculator, page.tyre_planner
    monkeypatch.setattr(race_calculator, "show_toast", lambda *args, **kwargs: None)
    set_race(calc, laps=40)
    planner.tyre_rule_panel._max_tyre.setValue(12)
    planner.propose_changes()
    rows = planner.tyre_plan.export_to_list()
    target = tmp_path / "plan.race-plan"
    monkeypatch.setattr(race_calculator.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *args, **kwargs: (str(target), "")))
    page.save_race_plan()
    calc.input_race.laps.setValue(4)  # 1 stint: rows of this plan kept aside
    calculations = []
    real_calculate = calc.calculate
    monkeypatch.setattr(calc, "calculate", lambda: calculations.append(1) or real_calculate())
    monkeypatch.setattr(race_calculator.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *args, **kwargs: (str(target), "")))
    page.load_race_plan()
    assert len(calculations) == 1
    assert planner.tyre_plan.export_to_list() == rows and not planner._spare_rows


def test_starting_tread_from_tyre_plan(page):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)
    planner.tyre_set_panel._tyre_selector.setCurrentText("Q-Soft")  # 90% starting tread
    planner.propose_changes()
    assert planner.start_tread(100.0) == pytest.approx(90.0)
    assert planner.fresh_tread() == pytest.approx(90.0)


def test_race_plan_widget(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.ui import race_calculator
    from tinypedal.widget import race_plan

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    page = race_calculator.RaceCalculator(None)  # plan made in race calculator, kept in config
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40, wear=4.0, minimum=20)  # stops at laps 15 & 30
    planner.tyre_rule_panel._max_tyre.setValue(12)
    planner.propose_changes()
    planner.autosave()
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
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)  # stops at 15 & 30
    rows = planner.tyre_plan.rowCount()
    live_race(monkeypatch, laps_done=20, fuel=9.0, stops=1)  # 3 laps of fuel left
    page.check_live_race.setChecked(True)
    assert calc.strategy.first_lap == 20 and [stop.lap for stop in calc.strategy.stops] == [23, 38]
    assert "Live Race" in calc.label_strategy.text() and calc.table_plan.item(0, 0).text() == "Now"
    assert calc.table_plan.item(1, 0).text() == "2"  # stop 2 of the race
    assert planner.tyre_plan.rowCount() == rows  # tyre plan of the race kept
    page.check_live_race.setChecked(False)
    assert calc.strategy.first_lap == 0 and [stop.lap for stop in calc.strategy.stops] == [15, 30]


def test_plan_of_car_and_track_opened_again(page, monkeypatch):
    from tinypedal.ui import race_calculator

    calc = page.panel_calculator
    toasts = []
    monkeypatch.setattr(race_calculator, "show_toast", lambda parent, text: toasts.append(text))
    live_race(monkeypatch, laps_done=0)
    set_race(calc, laps=40)
    page.save_combo_plan()
    calc.input_race.laps.setValue(25)  # other plan meanwhile
    other = race_calculator.RaceCalculator(None)  # car & track driven: its plan opened
    try:
        assert other.panel_calculator.input_race.laps.value() == 40
        assert any("Race plan of Spa - GT3 opened" in text for text in toasts)
    finally:
        other.set_unmodified()
        other.close()
        other.deleteLater()


def test_page_keeps_inputs_of_race_plan(page, monkeypatch, tmp_path):
    from tinypedal.module_info import ConsumptionDataSet
    from tinypedal.ui import race_calculator

    calc = page.panel_calculator
    monkeypatch.setattr(race_calculator, "show_toast", lambda *args, **kwargs: None)
    set_race(calc, laptime=100.0, laps=40)
    target = tmp_path / "plan.race-plan"
    page.save_race_plan(str(target))
    assert page.load_race_plan(str(target))
    laps = tuple(ConsumptionDataSet(10 - index, 1, 90.0, 2.5) for index in range(5))
    monkeypatch.setattr(minfo.history, "consumptionDataSet", laps)
    other = race_calculator.RaceCalculator(None)  # live laps shown, plan inputs kept
    try:
        assert other.panel_calculator.input_laptime.to_seconds() == pytest.approx(100.0)
        assert other.panel_history.table_history.rowCount() == 5
        other.load_live_data()  # asked: live laps filled in
        assert other.panel_calculator.input_laptime.to_seconds() == pytest.approx(90.0)
        assert cfg.user.config["fuel_calculator"]["enable_plan_inputs"] is False
    finally:
        other.set_unmodified()
        other.close()
        other.deleteLater()


def test_tyre_plan_not_refreshed_for_same_stints(page, monkeypatch):
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40)
    refreshed = []
    real_update = planner.update_tyre_wear
    monkeypatch.setattr(planner, "update_tyre_wear", lambda *args: refreshed.append(1) or real_update())
    calc.input_race.pit_seconds.setValue(45)  # lap race: same stints
    assert not refreshed
    calc.input_race.laps.setValue(50)
    assert refreshed and planner.tyre_plan.rowCount() == 4


def race_plan_widget(monkeypatch, completed: int, in_pits: bool = False):
    from tinypedal.api_control import api
    from tinypedal.widget import race_plan

    monkeypatch.setattr(api.read.lap, "completed_laps", lambda *args, **kwargs: completed, raising=False)
    monkeypatch.setattr(api.read.vehicle, "in_pits", lambda *args, **kwargs: in_pits, raising=False)
    widget = race_plan.Realtime(cfg, "race_plan")
    widget.timerEvent(None)
    return widget


def test_race_plan_widget_same_plan_as_calculator(ui_env, monkeypatch):
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    page = race_calculator.RaceCalculator(None)
    calc, planner = page.panel_calculator, page.tyre_planner
    set_race(calc, laps=40, wear=2.0, minimum=40)  # measured on medium: tyres at stop 2 only
    planner.tyre_set_panel._tyre_selector.setCurrentText("Ultrasoft")  # wears more: stops 1 & 2
    assert calc.proposed_tyre_rows == [1, 2]
    page.close()  # plan input written for the widget
    page.deleteLater()
    widget = race_plan_widget(monkeypatch, completed=13)
    try:
        assert widget.bar_tyres.text == "TYRE 4"  # stop 1 with tyres, as in the race calculator
    finally:
        widget.deleteLater()


def test_race_plan_widget_in_pits_and_live(ui_env, monkeypatch):
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    page = race_calculator.RaceCalculator(None)
    set_race(page.panel_calculator, laps=40)  # stops at 15 & 30
    page.close()
    page.deleteLater()
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
    calc = page.panel_calculator
    set_race(calc, laps=40)
    calc.input_race.laps.setValue(50)
    page.undo()
    assert calc.input_race.laps.value() == 40 and calc.strategy.race_laps == 40
    page.redo()
    assert calc.input_race.laps.value() == 50


def test_live_race_status_shown(page, monkeypatch):
    from tinypedal.api_control import api

    page.check_live_race.setChecked(True)
    assert page.label_live.text() == "waiting for the race"
    live_race(monkeypatch, laps_done=20, fuel=9.0, stops=1)
    set_race(page.panel_calculator, laps=40)
    page.refresh_race_state()
    assert page.label_live.text() == "from lap 21"
    assert "9.0 L" in page.label_live.toolTip()  # values read from the game, to check them
    monkeypatch.setattr(api.read.vehicle, "in_pits", lambda *args, **kwargs: True, raising=False)
    page.refresh_race_state()
    assert "in the pits" in page.label_live.text()


def test_share_code_round_trip(page, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from tinypedal.ui import race_calculator

    calc = page.panel_calculator
    monkeypatch.setattr(race_calculator, "show_toast", lambda *args, **kwargs: None)
    set_race(calc, laps=40)
    page.copy_share_code()
    code = QGuiApplication.clipboard().text()
    assert code.startswith("TPRP1:") and "\n" not in code
    calc.input_race.laps.setValue(25)
    monkeypatch.setattr(race_calculator.QInputDialog, "getText",
                        staticmethod(lambda *args, **kwargs: (code[:30] + "\n" + code[30:], True)))  # wrapped
    page.paste_share_code()
    assert calc.input_race.laps.value() == 40
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args)))
    monkeypatch.setattr(race_calculator.QInputDialog, "getText", staticmethod(lambda *args, **kwargs: ("nope", True)))
    page.paste_share_code()
    assert warnings and calc.input_race.laps.value() == 40


def test_plan_against_race_and_rivals(page, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.module_info import StintDataSet

    calc = page.panel_calculator
    live_race(monkeypatch, laps_done=20)
    stints = (StintDataSet(), StintDataSet(15, 1365.0, 46.5, 0.0, 30.0))  # newest first, placeholder
    monkeypatch.setattr(minfo.history, "stintDataSet", stints)
    set_race(calc, laps=40)
    table = calc.card_plan_vs_race.table
    assert not calc.card_plan_vs_race.isHidden() and table.item(0, 1).text() == "15 / 15"
    assert table.item(0, 3).text() == "3.100 / 3.000"
    names = ("You", "Rival A", "Rival B")
    for name, function in (
        ("total_vehicles", lambda *args, **kwargs: 3), ("player_index", lambda *args, **kwargs: 0),
        ("same_class", lambda index=None: True), ("driver_name", lambda index=None: names[index]),
        ("number_pitstops", lambda index=None, **kwargs: (1, 2, 1)[index]),
        ("place", lambda index=None: (2, 1, 3)[index]), ("in_pits", lambda index=None: index == 2),
    ):
        monkeypatch.setattr(api.read.vehicle, name, function, raising=False)
    monkeypatch.setattr(api.read.lap, "completed_laps", lambda index=None: (20, 21, 19)[index or 0], raising=False)
    page.refresh_rivals()
    rivals = calc.card_rivals.table
    assert not calc.card_rivals.isHidden() and rivals.rowCount() == 3
    assert rivals.item(0, 1).text() == "Rival A" and rivals.item(2, 3).text() == "1 (pit)"


def test_race_plan_widget_pit_menu_and_target(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    page = race_calculator.RaceCalculator(None)
    set_race(page.panel_calculator, laps=40)  # stops at 15 (45 L after) & 30 (30 L after)
    page.close()
    page.deleteLater()
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
