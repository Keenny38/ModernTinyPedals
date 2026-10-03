"""Fuel calculator: race fuel, pit stops, refill, tyre life, history data, file loading, columns"""

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
    from tinypedal.ui import fuel_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    cfg.units["fuel_unit"] = "Liter"
    monkeypatch.setattr(minfo.history, "consumptionDataSet", HISTORY)
    dialog = fuel_calculator.FuelCalculator(None)
    yield dialog
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_live_history_filled_in(calculator):
    panel = calculator.panel_calculator
    assert panel.input_laptime.to_seconds() == pytest.approx(90.5)  # last valid lap
    assert panel.input_fuel.fuel_used.value() == pytest.approx(3.0)
    assert panel.input_fuel.capacity.value() == pytest.approx(100.0)
    table = calculator.panel_history.table_history
    assert table.rowCount() == 3 and table.item(2, 1).foreground().color().name() == "#ff4400"  # invalid lap red


def test_time_race_needs_one_stop(calculator):
    panel = calculator.panel_calculator
    panel.input_laptime.minutes.setValue(1)
    panel.input_laptime.seconds.setValue(30)
    panel.input_laptime.mseconds.setValue(0)
    panel.input_fuel.capacity.setValue(100)
    panel.input_fuel.fuel_used.setValue(3.0)
    panel.input_fuel.energy_used.setValue(0)
    panel.input_race.pit_seconds.setValue(30)
    panel.input_race.minutes.setValue(60)  # 60 min race at 1:30: about 40 laps, 120 L
    usage = panel.usage_fuel
    assert usage.total_needed.text().endswith("≈ 120") and usage.pit_stops.text().endswith("≈ 1")
    assert float(usage.stint_laps.text()) == pytest.approx(100 / 3, abs=0.01)  # full tank
    assert float(panel.refill_fuel.average_refill.text()) > 0
    assert not panel.input_race.laps.isEnabled()  # time race: laps disabled


def test_lap_race_and_tyre_life(calculator):
    panel = calculator.panel_calculator
    panel.input_race.minutes.setValue(0)
    panel.input_race.laps.setValue(20)
    panel.input_fuel.capacity.setValue(100)
    panel.input_fuel.fuel_used.setValue(2.0)
    panel.input_tyre.start_tread.setValue(100)
    panel.input_tyre.wear_lap.setValue(4.0)  # 25 laps tyre life
    assert panel.usage_fuel.total_needed.text().endswith("≈ 40")
    assert panel.usage_fuel.pit_stops.text().endswith("≈ 0")
    assert float(panel.input_tyre.lifespan_laps.text()) == pytest.approx(25.0)
    assert not panel.input_race.minutes.isEnabled()


def test_start_fuel_limited_to_tank_and_lap_time_carry(calculator):
    panel = calculator.panel_calculator
    panel.input_fuel.capacity.setValue(80)
    panel.refill_fuel.amount_start.setValue(120)
    assert panel.refill_fuel.amount_start.value() == 80
    panel.input_laptime.minutes.setValue(1)
    panel.input_laptime.seconds.setValue(60)  # carried to next minute
    assert panel.input_laptime.minutes.value() == 2 and panel.input_laptime.seconds.value() == 0
    panel.input_laptime.mseconds.setValue(-1)
    assert panel.input_laptime.to_seconds() == pytest.approx(119.9)


def test_selected_history_averaged(calculator, monkeypatch):
    table = calculator.panel_history.table_history
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args)))
    calculator.add_selected_data()  # nothing selected
    assert warnings
    for row in (0, 1):
        for column in (1, 2, 3, 8, 9):
            table.item(row, column).setSelected(True)
    calculator.add_selected_data()
    panel = calculator.panel_calculator
    assert panel.input_fuel.fuel_used.value() == pytest.approx(3.1)
    assert panel.input_fuel.energy_used.value() == pytest.approx(2.55)
    assert panel.input_tyre.wear_lap.value() == pytest.approx(0.45)
    assert panel.input_laptime.to_seconds() == pytest.approx(91.0)


def test_history_panel_toggle_and_columns(calculator, monkeypatch):
    from tinypedal.i18n import untr
    from tinypedal.ui import fuel_calculator

    calculator.button_toggle.setChecked(False)
    assert calculator.panel_history.isHidden() and cfg.user.config["fuel_calculator"]["show_consumption_history"] is False
    calculator.button_toggle.setChecked(True)
    assert not calculator.panel_history.isHidden()

    class PickMenu(QMenu):
        def exec(self, *args):
            return next(action for action in self.actions() if untr(action.text()) == "Tyre Wear")

    monkeypatch.setattr(fuel_calculator, "QMenu", PickMenu)
    shown = cfg.user.config["fuel_calculator"]["show_column_tyre_wear"]
    calculator.table_header_menu(QPoint(1, 1))
    assert cfg.user.config["fuel_calculator"]["show_column_tyre_wear"] is not shown
    assert calculator.panel_history.table_history.isColumnHidden(8) is shown


def test_load_history_file(calculator, monkeypatch, tmp_path):
    from tinypedal.const_file import FileExt
    from tinypedal.ui import fuel_calculator
    from tinypedal.userfile.consumption_history import save_consumption_history_file

    save_consumption_history_file(HISTORY, f"{tmp_path.as_posix()}/", "Spa - GT3")
    path = tmp_path / f"Spa - GT3{FileExt.CONSUMPTION}"
    monkeypatch.setattr(fuel_calculator.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *args, **kwargs: (str(path), "")))
    calculator.load_file_data()
    assert "Spa - GT3" in calculator.status_bar.currentMessage()
    assert calculator.panel_history.table_history.rowCount() == 3
    monkeypatch.setattr(fuel_calculator.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: ("", "")))
    calculator.load_file_data()  # cancelled: nothing changed
    assert calculator.panel_history.table_history.rowCount() == 3


def test_pit_preview_drawn(calculator):
    preview = calculator.panel_calculator.pit_preview
    preview.sync(40.0, 15.0, 15.0)
    preview.resize(60, 400)
    assert not preview.grab().isNull()
