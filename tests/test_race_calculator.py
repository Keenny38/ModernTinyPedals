"""Race calculator: fuel strategy & tyre plan linked in one page, former tools redirected"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.ui._common import BaseEditor


@pytest.fixture
def page(ui_env, monkeypatch):
    from tinypedal.ui import race_calculator, tyre_strategy_planner

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
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


def test_one_page_two_tabs(page):
    from tinypedal.i18n import tr

    assert [page.tabs.tabText(index) for index in range(page.tabs.count())] == [tr("Fuel"), tr("Tyres")]
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
    assert calc.table_plan.item(1, 4).text() == "Change (4)"
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
