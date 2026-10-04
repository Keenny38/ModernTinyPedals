"""Race calculator, fuel side: race fuel, pit stop plan, refill, tyre life, history data, file loading, columns"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QMenu, QMessageBox

from tinypedal.module_info import ConsumptionDataSet, minfo
from tinypedal.setting import cfg

HISTORY = (
    ConsumptionDataSet(12, 1, 90.5, 3.0, 2.5, 1.0, 0.5, 0.4, 100.0),
    ConsumptionDataSet(11, 1, 91.5, 3.2, 2.6, 1.1, 0.4, 0.5, 100.0),
    ConsumptionDataSet(10, 0, 99.0, 3.6, 2.9, 1.2, 0.3, 0.6, 100.0),  # invalid lap
)


@pytest.fixture
def calculator(ui_env, monkeypatch):
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    cfg.units["fuel_unit"] = "Liter"
    monkeypatch.setattr(minfo.history, "consumptionDataSet", HISTORY)
    dialog = race_calculator.RaceCalculator(None)
    yield dialog
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def set_race(panel, laptime=90.0, tank=100.0, fuel=3.0, energy=0.0, minutes=0, laps=0, pit=0.0):
    with panel.batch():
        panel.input_laptime.set_seconds(laptime)
        panel.input_fuel.capacity.setValue(tank)
        panel.input_fuel.fuel_used.setValue(fuel)
        panel.input_fuel.energy_used.setValue(energy)
        panel.input_race.pit_seconds.setValue(pit)
        panel.input_race.minutes.setValue(minutes)
        panel.input_race.laps.setValue(laps)
        panel.input_race.set_lap_race(laps > 0)


def test_live_history_filled_in(calculator):
    panel = calculator.panel_calculator
    assert panel.input_laptime.to_seconds() == pytest.approx(91.0)  # average of valid laps
    assert panel.input_fuel.fuel_used.value() == pytest.approx(3.1)
    assert panel.input_fuel.capacity.value() == pytest.approx(100.0)
    assert "2" in panel.label_fill_source.text()
    table = calculator.panel_history.table_history
    assert table.rowCount() == 3 and table.item(2, 1).foreground().color().name() == "#ff4400"  # invalid lap red


def test_time_race_needs_one_stop(calculator):
    panel = calculator.panel_calculator
    set_race(panel, minutes=60, pit=30)  # 60 min race at 1:30: 40 laps, 120 L
    usage = panel.usage_fuel
    assert usage.total_needed.text().endswith("≈ 120") and usage.pit_stops.text().endswith("≈ 1")
    assert float(usage.stint_laps.text()) == pytest.approx(100 / 3, abs=0.01)  # full tank
    assert float(panel.refill_fuel.average_refill.text()) == pytest.approx(20.0)  # splash for last 7 laps
    assert panel.input_race.laps.isHidden()  # time race: laps field hidden


def test_lap_race_and_tyre_life(calculator):
    panel = calculator.panel_calculator
    set_race(panel, laps=20, fuel=2.0)
    panel.input_tyre.start_tread.setValue(100)
    panel.input_tyre.wear_lap.setValue(4.0)  # 25 laps tyre life
    assert panel.usage_fuel.total_needed.text().endswith("≈ 40")
    assert panel.usage_fuel.pit_stops.text().endswith("≈ 0")
    assert panel.usage_fuel.one_less_stint.text() == "-"  # no stop: nothing to save
    assert float(panel.input_tyre.lifespan_laps.text()) == pytest.approx(25.0)
    assert panel.input_tyre.wear_stint.text() == "80.00 %"  # 20 whole laps
    assert panel.input_race.minutes.isHidden()
    assert panel.tile_refill.label_title.text() == "Fuel to Load"  # no stop: exact start fuel
    assert panel.tile_refill.label_value.text() == "40.0 L"


def test_start_fuel_limited_to_tank_and_lap_time_carry(calculator):
    panel = calculator.panel_calculator
    panel.input_fuel.capacity.setValue(80)
    panel.refill_fuel.amount_start.setValue(120)
    assert panel.refill_fuel.amount_start.value() == 80
    panel.input_fuel.capacity.setValue(50)  # lowered after: starting fuel follows
    assert panel.refill_fuel.amount_start.value() == 50
    panel.input_laptime.minutes.setValue(1)
    panel.input_laptime.seconds.setValue(60)  # carried to next minute
    assert panel.input_laptime.minutes.value() == 2 and panel.input_laptime.seconds.value() == 0
    panel.input_laptime.mseconds.setValue(-1)
    assert panel.input_laptime.to_seconds() == pytest.approx(119.9)


def test_selected_history_averaged(calculator, monkeypatch):
    table = calculator.panel_history.table_history
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args)))
    table.clearSelection()
    calculator.add_selected_data()  # nothing selected
    assert len(warnings) == 1
    table.selectRow(2)  # invalid lap only
    calculator.add_selected_data()
    assert len(warnings) == 2
    table.clearSelection()
    for row in (0, 1, 2):
        for column in (1, 2, 3, 8, 9):
            table.item(row, column).setSelected(True)
    calculator.add_selected_data()
    panel = calculator.panel_calculator
    assert panel.input_fuel.fuel_used.value() == pytest.approx(3.1)  # invalid lap left out
    assert panel.input_fuel.energy_used.value() == pytest.approx(2.55)
    assert panel.input_tyre.wear_lap.value() == pytest.approx(0.45)
    assert panel.input_laptime.to_seconds() == pytest.approx(91.0)
    assert "2" in calculator.panel_history.label_added.text() and "1" in calculator.panel_history.label_added.text()


def test_history_panel_toggle_and_columns(calculator, monkeypatch):
    from tinypedal.i18n import untr
    from tinypedal.ui import race_calculator

    calculator.button_toggle.setChecked(False)
    assert calculator.panel_history.isHidden() and cfg.user.config["fuel_calculator"]["show_consumption_history"] is False
    calculator.button_toggle.setChecked(True)
    assert not calculator.panel_history.isHidden()

    class PickMenu(QMenu):
        def exec(self, *args):
            return next(action for action in self.actions() if untr(action.text()) == "Tyre Wear")

    monkeypatch.setattr(race_calculator, "QMenu", PickMenu)
    shown = cfg.user.config["fuel_calculator"]["show_column_tyre_wear"]
    calculator.table_header_menu(QPoint(1, 1))
    assert cfg.user.config["fuel_calculator"]["show_column_tyre_wear"] is not shown
    assert calculator.panel_history.table_history.isColumnHidden(8) is shown
    calculator.column_menu(QPoint(1, 1))  # same menu from Columns button
    assert cfg.user.config["fuel_calculator"]["show_column_tyre_wear"] is shown


@pytest.mark.parametrize("extension", ["consumption", "csv"])
def test_load_history_file(calculator, monkeypatch, tmp_path, extension):
    from tinypedal.const_file import FileExt
    from tinypedal.ui import race_calculator
    from tinypedal.userfile.consumption_history import save_consumption_history_file

    save_consumption_history_file(HISTORY, f"{tmp_path.as_posix()}/", "Spa - GT3")
    path = tmp_path / f"Spa - GT3{FileExt.CONSUMPTION}"
    if extension == "csv":  # same content, other extension: the chosen file is read
        path = path.rename(tmp_path / "Spa - GT3.csv")
    monkeypatch.setattr(race_calculator.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *args, **kwargs: (str(path), "")))
    calculator.load_file_data()
    assert "Spa - GT3" in calculator.status_bar.currentMessage()
    assert "Spa - GT3" in calculator.label_source.text() and not calculator.live_source
    assert calculator.panel_history.table_history.rowCount() == 3
    monkeypatch.setattr(race_calculator.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: ("", "")))
    calculator.load_file_data()  # cancelled: nothing changed
    assert calculator.panel_history.table_history.rowCount() == 3


def test_invalid_history_file_warned(calculator, monkeypatch, tmp_path):
    from tinypedal.ui import race_calculator

    path = tmp_path / "broken.consumption"
    path.write_text("not,a,history\n", encoding="utf-8")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args)))
    monkeypatch.setattr(race_calculator.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *args, **kwargs: (str(path), "")))
    calculator.load_file_data()
    assert warnings and "broken" in warnings[0][2]
    assert calculator.live_source and calculator.panel_history.table_history.rowCount() == 3  # kept


def test_pit_preview_drawn(calculator):
    from tinypedal.fuel_strategy import StrategyInput, plan

    preview = calculator.panel_calculator.pit_preview
    preview.set_strategy(plan(StrategyInput(laptime=90, race_laps=40, tank_capacity=45, fuel_per_lap=3.0,
                                            wear_per_lap=4, minimum_tread=20)))
    assert preview.pit_laps == [15, 30]
    preview.resize(600, 80)
    assert not preview.grab().isNull()


def test_key_figures_strategy_and_plan(calculator):
    panel = calculator.panel_calculator
    set_race(panel, minutes=60, pit=30)
    assert panel.tile_fuel.label_value.text() == "120 L"
    assert panel.tile_pits.label_value.text() == "1"
    assert panel.tile_stint.label_value.text() == "33 laps"
    assert panel.tile_refill.label_value.text() == "20.0 L"  # last stop is a splash, not a full tank
    assert panel.tile_energy.isHidden()  # no energy used: energy tile & column muted
    assert panel.usage_energy.total_needed.text() == "-" and not panel.usage_energy.total_needed.isEnabled()
    assert panel.pit_preview.pit_laps == [33]
    assert "Stop at lap 33" in panel.label_strategy.text()
    plan_table = panel.table_plan
    assert plan_table.rowCount() == 2  # start, stop 1
    assert plan_table.item(1, 1).text() == "33" and plan_table.item(1, 2).text() == "20.0"
    panel.input_fuel.energy_used.setValue(4.0)  # energy runs out first: 25 laps per stint
    assert not panel.tile_energy.isHidden()
    assert panel.tile_pits.label_detail.text() == "limited by energy"
    assert panel.pit_preview.pit_laps == [25]


def test_fuel_and_energy_share_race_length(calculator):
    panel = calculator.panel_calculator
    # 4 h at 1:51.9, pits cost 62 s: energy & fuel details for the same 126 laps
    set_race(panel, laptime=111.9, tank=75, fuel=2.95, energy=3.4, minutes=240, pit=62)
    strategy = panel.strategy
    assert strategy.race_laps == 126 and len(strategy.stops) == 5
    assert panel.usage_fuel.total_needed.text().startswith(f"{126 * 2.95:.2f}")
    assert panel.usage_energy.total_needed.text().startswith(f"{126 * 3.4:.2f}")
    assert strategy.stops[-1].fuel < 5  # splash on last stop


def test_safety_margin_and_tyre_stops(calculator):
    panel = calculator.panel_calculator
    set_race(panel, laps=20, fuel=2.0)
    panel.input_race.margin.setValue(1.0)
    assert panel.usage_fuel.total_needed.text().endswith("≈ 42")  # one lap more
    assert panel.tile_fuel.label_value.text() == "42 L"
    panel.input_race.margin.setValue(0)
    set_race(panel, laps=40, tank=45, fuel=3.0)
    panel.input_tyre.wear_lap.setValue(4.0)
    panel.input_tyre.minimum_tread.setValue(20)
    assert panel.strategy.tyre_stops == [15, 30]
    assert "Tyres at lap 15, 30" in panel.label_strategy.text()
    assert panel.table_plan.item(1, 4).text() == "Change"


def test_infeasible_tank_warned(calculator):
    panel = calculator.panel_calculator
    set_race(panel, laps=10, tank=2, fuel=3.0)
    assert not panel.strategy.feasible
    assert panel.tile_pits.label_value.property("warning")
    assert panel.label_strategy.property("warning")


def test_copy_plan(calculator):
    from PySide6.QtGui import QGuiApplication

    panel = calculator.panel_calculator
    set_race(panel, minutes=60, pit=30)
    panel.button_copy.click()
    text = QGuiApplication.clipboard().text()
    assert "Stop 1 · Lap 33 · +20.0 L" in text


def test_inputs_saved_and_restored(calculator):
    from tinypedal.ui import race_calculator

    panel = calculator.panel_calculator
    set_race(panel, laps=30, fuel=2.5, pit=45)
    panel.input_race.margin.setValue(0.5)
    config = cfg.user.config["fuel_calculator"]
    assert config["input_race_laps"] == 30 and config["enable_lap_race"] is True
    assert config["input_safety_margin"] == pytest.approx(0.5)
    minfo.history.consumptionDataSet = ()  # nothing live: saved inputs stay
    dialog = race_calculator.RaceCalculator(None)
    try:
        other = dialog.panel_calculator
        assert other.input_race.lap_race and other.input_race.laps.value() == 30
        assert other.input_race.pit_seconds.value() == pytest.approx(45)
        assert other.input_fuel.fuel_used.value() == pytest.approx(2.5)
    finally:
        dialog.deleteLater()


def test_reset_to_zero(calculator):
    panel = calculator.panel_calculator
    set_race(panel, laps=30, fuel=2.5, pit=45)
    calculator.reset_values()
    assert panel.input_laptime.to_seconds() == 0 and panel.input_fuel.fuel_used.value() == 0
    assert panel.input_race.laps.value() == 0 and panel.input_race.pit_seconds.value() == 0
    assert panel.input_tyre.start_tread.value() == 100  # new tyres
    assert panel.tile_fuel.label_value.text() == "-"


def test_one_calculation_per_batch(calculator, monkeypatch):
    panel = calculator.panel_calculator
    calls = []
    original = panel.calculate
    monkeypatch.setattr(panel, "calculate", lambda: (calls.append(1), original())[1])
    panel.fill_in_data(HISTORY)  # several inputs at once
    assert len(calls) == 1
    calls.clear()
    panel.input_laptime.seconds.setValue(60)  # carried over: still one calculation
    assert len(calls) == 1


def test_live_race_length_filled(calculator, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.ui import race_calculator

    session = api.read.session
    monkeypatch.setattr(type(session), "session_type", lambda self: 4, raising=False)
    monkeypatch.setattr(type(session), "finish_type", lambda self, as_lap=None: 0, raising=False)
    monkeypatch.setattr(type(session), "start", lambda self: 0.0, raising=False)
    monkeypatch.setattr(type(session), "end", lambda self: 6 * 3600.0, raising=False)
    assert race_calculator.live_race_length() == ("minutes", 360)
    calculator.load_live_data()
    race = calculator.panel_calculator.input_race
    assert not race.lap_race and race.minutes.value() == 360
    monkeypatch.setattr(type(session), "finish_type", lambda self, as_lap=None: 1, raising=False)
    monkeypatch.setattr(type(api.read.lap), "maximum", lambda self: 50, raising=False)
    calculator.load_live_data()
    assert race.lap_race and race.laps.value() == 50


def test_live_history_follows_new_laps(calculator, monkeypatch):
    table = calculator.panel_history.table_history
    fuel_used = calculator.panel_calculator.input_fuel.fuel_used.value()
    monkeypatch.setattr(calculator, "isVisible", lambda: True)
    new_lap = ConsumptionDataSet(13, 1, 90.0, 2.8, 2.4, 1.0, 0.5, 0.4, 100.0)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", (new_lap, *HISTORY))
    calculator.refresh_live_history()
    assert table.rowCount() == 4 and table.item(0, 0).text() == "13"
    assert calculator.panel_calculator.input_fuel.fuel_used.value() == fuel_used  # inputs untouched


def test_empty_inputs_show_dashes(ui_env, monkeypatch):
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", (ConsumptionDataSet(),))  # placeholder only
    dialog = race_calculator.RaceCalculator(None)
    try:
        panel = dialog.panel_calculator
        assert panel.usage_fuel.total_needed.text() == "-"
        assert panel.tile_fuel.label_value.text() == "-"
        assert panel.input_tyre.lifespan_laps.text() == "-"  # no wear entered
        assert panel.pit_preview.pit_laps == []
        history = dialog.panel_history
        assert history.table_history.isHidden() and not history.label_empty.isHidden()  # placeholder not shown
        assert not history.button_adddata.isEnabled()
        assert not panel.button_copy.isEnabled()
        assert not panel.pit_preview.grab().isNull()  # empty timeline hint
    finally:
        dialog.deleteLater()


def test_history_moves_below_on_narrow_page(calculator):
    from PySide6.QtWidgets import QBoxLayout

    from tinypedal.ui._common import UIScaler
    from tinypedal.ui.race_calculator import WIDE_PAGE

    calc = calculator.panel_calculator
    wide = max(UIScaler.size(WIDE_PAGE), calc.wide_top_width() + calculator.MARGIN * 2)
    calculator.show()  # resize events delivered to shown widget only
    calculator.resize(wide + 50, 600)
    QCoreApplication.processEvents()
    assert calculator.layout_body.direction() == QBoxLayout.Direction.LeftToRight
    assert calc.layout_tiles.itemAtPosition(1, 0) is None  # key figures on one row
    calculator.resize(UIScaler.size(WIDE_PAGE) - 50, 600)
    QCoreApplication.processEvents()
    assert calculator.width() < wide  # page narrows (own minimum, not the wide layout one)
    assert calculator.layout_body.direction() == QBoxLayout.Direction.TopToBottom
    assert calc.card_race.grid.itemAtPosition(1, 0) is not None  # race setup wrapped on two rows


def test_source_chip_and_french_labels(calculator):
    from tinypedal import i18n
    from tinypedal.ui import race_calculator

    assert "Live" in calculator.label_source.text()
    i18n.set_language("Français")
    try:
        dialog = race_calculator.RaceCalculator(None)
        texts = {label.text() for label in dialog.findChildren(race_calculator.QLabel)}
        assert {"Tour et consommation", "Stratégie", "Capacité du réservoir", "Plein moyen",
                "Plan d'arrêts", "Marge de sécurité"} <= texts
        assert "Tank Capacity:" not in texts
        dialog.deleteLater()
    finally:
        i18n.set_language("English")


def test_history_sorted_and_valid_only(calculator):
    from PySide6.QtCore import Qt

    table = calculator.panel_history.table_history
    table.sortItems(1, Qt.SortOrder.AscendingOrder)  # by lap time, numbers by value
    assert [table.item(row, 0).text() for row in range(3)] == ["12", "11", "10"]
    table.sortItems(2, Qt.SortOrder.DescendingOrder)  # by fuel
    assert table.item(0, 2).text() == "3.600"
    calculator.panel_history.check_valid_only.setChecked(True)
    hidden = [table.isRowHidden(row) for row in range(3)]
    assert hidden.count(True) == 1 and cfg.user.config["fuel_calculator"]["enable_valid_laps_only"] is True
    calculator.panel_history.check_valid_only.setChecked(False)
    assert not any(table.isRowHidden(row) for row in range(3))


def test_delete_live_history(calculator, monkeypatch, tmp_path):
    from collections import deque

    from tinypedal.api_control import api

    history = deque(HISTORY, 100)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", history)
    monkeypatch.setattr(type(api.read.session), "combo_name", lambda self: "Spa - GT3", raising=False)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    from tinypedal.ui._common import BaseEditor
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    calculator.load_live_data()
    panel = calculator.panel_history
    panel.table_history.selectRow(0)
    calculator.delete_laps(panel.selected_indexes())
    assert len(history) == 2 and panel.table_history.rowCount() == 2
    saved = tmp_path / "fuel_delta" / "Spa - GT3.consumption"
    assert saved.exists()
    calculator.delete_laps(None)  # whole history
    assert panel.table_history.rowCount() == 0
    assert len(history) == 1 and history[0] == ConsumptionDataSet()  # placeholder: module keeps reading [0]
    assert not saved.exists()


def test_delete_from_file_history(calculator, monkeypatch, tmp_path):
    from tinypedal.ui import race_calculator
    from tinypedal.ui._common import BaseEditor
    from tinypedal.userfile.consumption_history import load_consumption_history_file, save_consumption_history_file

    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    save_consumption_history_file(HISTORY, f"{tmp_path.as_posix()}/", "Monza - LMP2")
    path = tmp_path / "Monza - LMP2.consumption"
    monkeypatch.setattr(race_calculator.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *args, **kwargs: (str(path), "")))
    calculator.load_file_data()
    calculator.delete_laps({0, 1})  # first two laps of history data
    kept = [lap for lap in load_consumption_history_file(f"{tmp_path.as_posix()}/", "Monza - LMP2") if lap.lapTimeLast]
    assert [lap.lapNumber for lap in kept] == [10]  # one lap left (saved with placeholder)


def test_new_inputs_saved_and_used(calculator):
    panel = calculator.panel_calculator
    set_race(panel, laps=40, tank=45, fuel=3.0, pit=20)
    with panel.batch():
        panel.input_pit.refuel_rate.setValue(3.0)
        panel.input_rules.drivers.setValue(2)
        panel.input_pit.driver_change.setValue(10)
    config = cfg.user.config["fuel_calculator"]
    assert config["input_refuel_rate"] == 3.0 and config["input_drivers"] == 2
    stop = panel.strategy.stops[0]
    assert stop.seconds == pytest.approx(20 + 15 + 10) and stop.driver == 2
    table = panel.table_plan
    assert not table.isColumnHidden(5) and table.item(1, 5).text() == "2"
    assert table.item(1, 6).text() == "45.0"
    text = panel.plan_text()
    assert "Driver 2" in text and "45.0 s" in text and "s in the pits" in text


def test_saving_target_card(calculator):
    panel = calculator.panel_calculator
    set_race(panel, laps=40, tank=45, fuel=3.0)  # 2 stops
    assert "20 laps per stint, 1 stop(s)" in panel.label_one_less.text()
    panel.input_target.setValue(40)
    assert "0 stop(s) with this target" in panel.label_target.text()


def test_energy_only_page(calculator):
    panel = calculator.panel_calculator
    set_race(panel, laps=40, tank=0, fuel=0, energy=4.0)
    assert panel.strategy.ready and panel.tile_fuel.isHidden() and not panel.tile_energy.isHidden()
    assert panel.usage_fuel.total_needed.text() == "-"
    assert panel.tile_refill.label_value.text() == "60.0 %"


def test_follow_live(calculator, monkeypatch):
    panel = calculator.panel_calculator
    monkeypatch.setattr(calculator, "isVisible", lambda: True)
    calculator.check_follow.setChecked(True)
    assert cfg.user.config["fuel_calculator"]["enable_follow_live"] is True
    new_laps = tuple(ConsumptionDataSet(20 + i, 1, 88.0, 2.5, 2.0, 1.0, 0.5, 0.4, 100.0) for i in range(5))
    monkeypatch.setattr(minfo.history, "consumptionDataSet", new_laps)
    calculator.refresh_live_history()
    assert panel.input_fuel.fuel_used.value() == pytest.approx(2.5)  # inputs follow new laps


def test_race_plan_file(calculator, monkeypatch, tmp_path):
    from tinypedal.ui import race_calculator

    panel = calculator.panel_calculator
    monkeypatch.setattr(race_calculator, "show_toast", lambda *args, **kwargs: None)
    set_race(panel, laps=30, fuel=2.5, pit=45)
    calculator.tyre_planner.propose_changes()
    rows = calculator.tyre_planner.tyre_plan.export_to_list()
    target = tmp_path / "Le Mans.race-plan"
    monkeypatch.setattr(race_calculator.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *args, **kwargs: (str(target), "")))
    calculator.save_race_plan()
    assert target.exists()
    calculator.reset_values()
    calculator.tyre_planner.create_new_file()
    monkeypatch.setattr(race_calculator.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *args, **kwargs: (str(target), "")))
    calculator.load_race_plan()
    assert panel.input_race.laps.value() == 30 and panel.input_race.pit_seconds.value() == pytest.approx(45)
    assert calculator.tyre_planner.tyre_plan.export_to_list() == rows
    # Invalid file: warned, nothing changed
    bad = tmp_path / "bad.race-plan"
    bad.write_text("{}", encoding="utf-8")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args)))
    monkeypatch.setattr(race_calculator.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *args, **kwargs: (str(bad), "")))
    calculator.load_race_plan()
    assert warnings and panel.input_race.laps.value() == 30


def test_timeline_labels_never_overlap(calculator):
    from tinypedal.fuel_strategy import StrategyInput, plan

    preview = calculator.panel_calculator.pit_preview
    preview.set_strategy(plan(StrategyInput(laptime=100, race_minutes=1440, tank_capacity=20, fuel_per_lap=3.0)))
    assert len(preview.pit_laps) > 100  # 24 h: many stops
    preview.resize(600, 80)
    assert not preview.grab().isNull()
