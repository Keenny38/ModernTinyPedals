"""Race calculator, fuel side: race fuel, pit stop plan, refill, tyre life, history data, file loading,
columns, export, saving target & scenarios"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tests.test_race_calculator import cell, host, tile  # noqa: F401 (host: fixture)
from tinypedal.module_info import ConsumptionDataSet, minfo
from tinypedal.setting import cfg

HISTORY = (
    ConsumptionDataSet(12, 1, 90.5, 3.0, 2.5, 1.0, 0.5, 0.4, 100.0),
    ConsumptionDataSet(11, 1, 91.5, 3.2, 2.6, 1.1, 0.4, 0.5, 100.0),
    ConsumptionDataSet(10, 0, 99.0, 3.6, 2.9, 1.2, 0.3, 0.6, 100.0),  # invalid lap
)


@pytest.fixture
def calculator(ui_env, monkeypatch, host):  # noqa: F811
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    cfg.units["fuel_unit"] = "Liter"
    monkeypatch.setattr(minfo.history, "consumptionDataSet", HISTORY)
    dialog = race_calculator.RaceCalculator(None)
    yield dialog.backend
    dialog.set_unmodified()
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def set_race(backend, laptime=90.0, tank=100.0, fuel=3.0, energy=0.0, minutes=0, laps=0, pit=0.0):
    backend.set_values({
        "input_lap_time": laptime, "input_tank_capacity": tank, "input_fuel_per_lap": fuel,
        "input_energy_per_lap": energy, "input_pit_seconds": pit, "input_race_minutes": minutes,
        "input_race_laps": laps, "enable_lap_race": laps > 0,
    })


def detail(backend, key: str) -> dict:
    return next(row for row in backend.details["rows"] if row["key"] == key)


def history_rows(backend) -> list[dict]:
    return backend.history["rows"]


def select(backend, *numbers: str):
    """Laps of history selected by lap number"""
    backend.clearLapSelection()
    for number in numbers:
        row = next(row for row in history_rows(backend) if row["cells"][0] == number)
        backend.selectLap(row["serial"], 1)


def test_live_history_filled_in(calculator):
    values = calculator.values
    assert values["input_lap_time"] == pytest.approx(91.0)  # average of valid laps
    assert values["input_fuel_per_lap"] == pytest.approx(3.1)
    assert values["input_tank_capacity"] == pytest.approx(100.0)
    assert "2" in calculator.notes["fillSource"]
    rows = history_rows(calculator)
    assert len(rows) == 3 and not rows[2]["valid"] and calculator.history["invalidColor"] == "#FF4400"


def test_time_race_needs_one_stop(calculator):
    set_race(calculator, minutes=60, pit=30)  # 60 min race at 1:30: 40 laps, 120 L
    assert detail(calculator, "total_needed")["fuel"].endswith("≈ 120")
    assert detail(calculator, "pit_stops")["fuel"].endswith("≈ 1")
    assert float(detail(calculator, "stint_laps")["fuel"]) == pytest.approx(100 / 3, abs=0.01)  # full tank
    assert float(detail(calculator, "average_refill")["fuel"]) == pytest.approx(20.0)  # splash for last 7 laps


def test_lap_race_and_tyre_life(calculator):
    set_race(calculator, laps=20, fuel=2.0)
    calculator.set_values({"input_tread_start": 100, "input_wear_per_lap": 4.0})  # 25 laps tyre life
    assert detail(calculator, "total_needed")["fuel"].endswith("≈ 40")
    assert detail(calculator, "pit_stops")["fuel"].endswith("≈ 0")
    assert detail(calculator, "one_less_stint")["fuel"] == "-"  # no stop: nothing to save
    life = calculator.tyreLife
    assert float(life["laps"]) == pytest.approx(25.0)
    assert life["wearStint"] == "80.00 %"  # 20 whole laps
    refill = tile(calculator, "refill")
    assert refill["title"] == "Fuel to Load" and refill["value"] == "40.0 L"  # no stop: exact start fuel


def test_start_fuel_limited_to_tank_and_inputs_in_range(calculator):
    calculator.setInput("input_tank_capacity", 80)
    assert calculator.setInput("input_fuel_start", 120) == 80
    calculator.setInput("input_tank_capacity", 50)  # lowered after: starting fuel follows
    assert calculator.values["input_fuel_start"] == 50
    assert calculator.setInput("input_drivers", 30) == 9 and calculator.setInput("input_drivers", 0) == 1
    assert calculator.setInput("input_fuel_per_lap", 3.14159) == pytest.approx(3.142)  # decimals of field
    assert calculator.setInput("input_race_laps", 12.6) == 13 and isinstance(calculator.values["input_race_laps"], int)
    assert calculator.setInput("input_pit_seconds", float("nan")) == 0
    assert calculator.setInput("enable_rain", 1) is True
    assert calculator.setInput("unknown", 3) is None


def test_lap_time_and_start_time_typed(calculator):
    assert calculator.setLapTime("1:59.95") == "1:59.950"
    assert calculator.stepLapTime(0.1) == "2:00.050"  # carried to next minute
    assert calculator.setLapTime("95,5") == "1:35.500"  # seconds, decimal comma
    assert calculator.setLapTime("nope") == "1:35.500"  # not a lap time: kept
    calculator.setLapTime("0.05")
    assert calculator.stepLapTime(-1) == "0:00.000"  # never below zero
    assert calculator.setStartTime(True, "14:30") == "14:30"
    assert calculator.values["input_race_start_minutes"] == 14 * 60 + 30
    assert calculator.setStartTime(True, "25:00") == "14:30"  # not a time: kept
    assert calculator.setStartTime(True, "0830") == "08:30"
    assert calculator.setStartTime(False, "08:30") == "" and calculator.values["input_race_start_minutes"] == -1


def test_selected_history_averaged(calculator, host):  # noqa: F811
    calculator.clearLapSelection()
    calculator.addSelectedLaps()  # nothing selected
    assert len(host.warnings) == 1
    select(calculator, "10")  # invalid lap only
    calculator.addSelectedLaps()
    assert len(host.warnings) == 2
    select(calculator, "12", "11", "10")
    calculator.addSelectedLaps()
    values = calculator.values
    assert values["input_fuel_per_lap"] == pytest.approx(3.1)  # invalid lap left out
    assert values["input_energy_per_lap"] == pytest.approx(2.55)
    assert values["input_wear_per_lap"] == pytest.approx(0.45)
    assert values["input_lap_time"] == pytest.approx(91.0)
    added = calculator.notes["historyAdded"]
    assert "2" in added and "1" in added


def test_history_selection_modes(calculator):
    rows = history_rows(calculator)
    serials = [row["serial"] for row in rows]
    calculator.selectLap(serials[0], 0)
    calculator.selectLap(serials[2], 2)  # range
    assert calculator.historySelection == sorted(serials)
    calculator.selectLap(serials[1], 1)  # toggled off
    assert calculator.historySelection == sorted((serials[0], serials[2]))
    calculator.selectLap(serials[1], 0)  # alone
    assert calculator.historySelection == [serials[1]]
    calculator.selectAllLaps()
    assert len(calculator.historySelection) == 3


def test_history_panel_toggle_and_columns(calculator):
    calculator.setShowHistory(False)
    assert not calculator.header["showHistory"] and cfg.user.config["fuel_calculator"]["show_consumption_history"] is False
    calculator.setShowHistory(True)
    assert calculator.header["showHistory"]
    shown = cfg.user.config["fuel_calculator"]["show_column_tyre_wear"]
    calculator.toggleHistoryColumn("show_column_tyre_wear")
    assert cfg.user.config["fuel_calculator"]["show_column_tyre_wear"] is not shown
    column = next(column for column in calculator.history["columns"] if column["key"] == "tyre")
    assert column["visible"] is not shown
    menu = {item["option"]: item for item in calculator.history["menu"]}
    assert menu["show_column_tyre_wear"]["title"] == "Tyre Wear" and len(menu) == 6
    calculator.toggleHistoryColumn("input_lap_time")  # not a column: ignored
    assert cfg.user.config["fuel_calculator"]["input_lap_time"] == pytest.approx(91.0)


@pytest.mark.parametrize("extension", ["consumption", "csv"])
def test_load_history_file(calculator, host, tmp_path, extension):  # noqa: F811
    from tinypedal.const_file import FileExt
    from tinypedal.userfile.consumption_history import save_consumption_history_file

    save_consumption_history_file(HISTORY, f"{tmp_path.as_posix()}/", "Spa - GT3")
    path = tmp_path / f"Spa - GT3{FileExt.CONSUMPTION}"
    if extension == "csv":  # same content, other extension: the chosen file is read
        path = path.rename(tmp_path / "Spa - GT3.csv")
    host.open_path = str(path)
    calculator.loadFile()
    header = calculator.header
    assert header["source"] == "Spa - GT3" and not header["live"] and not calculator.live_source
    assert len(history_rows(calculator)) == 3
    host.open_path = ""
    calculator.loadFile()  # cancelled: nothing changed
    assert len(history_rows(calculator)) == 3


def test_file_laps_keep_their_tank(calculator, host, monkeypatch, tmp_path):  # noqa: F811
    from tinypedal.api_control import api
    from tinypedal.userfile.consumption_history import save_consumption_history_file

    save_consumption_history_file(HISTORY, f"{tmp_path.as_posix()}/", "Monza - LMP2")
    monkeypatch.setattr(type(api.read.engine), "tank_capacity", lambda self, index=None: 120.0, raising=False)
    host.open_path = str(tmp_path / "Monza - LMP2.consumption")
    calculator.loadFile()  # laps of another car than the live one (120 L)
    assert calculator.values["input_tank_capacity"] == pytest.approx(100)


def test_invalid_history_file_warned(calculator, host, tmp_path):  # noqa: F811
    path = tmp_path / "broken.consumption"
    path.write_text("not,a,history\n", encoding="utf-8")
    host.open_path = str(path)
    calculator.loadFile()
    assert host.warnings and "broken" in host.warnings[0]
    assert calculator.live_source and len(history_rows(calculator)) == 3  # kept


def test_key_figures_strategy_and_plan(calculator):
    set_race(calculator, minutes=60, pit=30)
    assert tile(calculator, "fuel")["value"] == "120 L"
    assert tile(calculator, "pits")["value"] == "1"
    assert tile(calculator, "stint")["value"] == "33 laps"
    assert tile(calculator, "refill")["value"] == "20.0 L"  # last stop is a splash, not a full tank
    assert not tile(calculator, "energy")["visible"]  # no energy used: energy tile & column muted
    assert detail(calculator, "total_needed")["energy"] == "-" and not calculator.details["energyEnabled"]
    assert [stop["lap"] for stop in calculator.timeline["stops"]] == [33]
    assert "Stop at lap 33" in calculator.summary["text"]
    plan = calculator.plan
    assert len(plan["rows"]) == 2  # start, stop 1
    assert cell(calculator, 1, "lap") == "33" and cell(calculator, 1, "fuel") == "20.0"
    assert cell(calculator, 1, "time") == "0:49"  # race time of the stop (33 laps of 90 s)
    assert "energy" in plan["hidden"] and "driver" in plan["hidden"]
    calculator.setInput("input_energy_per_lap", 4.0)  # energy runs out first: 25 laps per stint
    assert tile(calculator, "energy")["visible"]
    assert tile(calculator, "pits")["detail"] == "limited by energy"
    assert [stop["lap"] for stop in calculator.timeline["stops"]] == [25]


def test_fuel_and_energy_share_race_length(calculator):
    # 4 h at 1:51.9, pits cost 62 s: energy & fuel details for the same 126 laps
    set_race(calculator, laptime=111.9, tank=75, fuel=2.95, energy=3.4, minutes=240, pit=62)
    strategy = calculator.strategy
    assert strategy.race_laps == 126 and len(strategy.stops) == 5
    assert detail(calculator, "total_needed")["fuel"].startswith(f"{126 * 2.95:.2f}")
    assert detail(calculator, "total_needed")["energy"].startswith(f"{126 * 3.4:.2f}")
    assert strategy.stops[-1].fuel < 5  # splash on last stop


def test_safety_margin_and_tyre_stops(calculator):
    set_race(calculator, laps=20, fuel=2.0)
    calculator.setInput("input_safety_margin", 1.0)
    assert detail(calculator, "total_needed")["fuel"].endswith("≈ 42")  # one lap more
    assert tile(calculator, "fuel")["value"] == "42 L"
    calculator.setInput("input_safety_margin", 0)
    set_race(calculator, laps=40, tank=45, fuel=3.0)
    calculator.set_values({"input_wear_per_lap": 4.0, "input_minimum_tread": 20})
    assert calculator.strategy.tyre_stops == [15, 30]
    assert "Tyres at lap 15, 30" in calculator.summary["text"]
    assert cell(calculator, 1, "tyres") == "Change"
    assert [stop["tyres"] for stop in calculator.timeline["stops"]] == [True, True]


def test_infeasible_tank_warned(calculator):
    set_race(calculator, laps=10, tank=2, fuel=3.0)
    assert not calculator.strategy.feasible
    assert tile(calculator, "pits")["warning"] and calculator.summary["warning"]
    assert "Tank too small" in calculator.summary["text"]


def test_copy_plan(calculator, host):  # noqa: F811
    from PySide6.QtGui import QGuiApplication

    set_race(calculator, minutes=60, pit=30)
    calculator.copyPlanText()
    text = QGuiApplication.clipboard().text()
    assert "Stop 1 · Lap 33 · 0:49 · +20.0 L" in text and "Window 7-33" in text and host.toasts


def test_plan_export_formats(calculator, host, tmp_path):  # noqa: F811
    from PySide6.QtGui import QGuiApplication

    set_race(calculator, minutes=60, pit=30)
    calculator.copyPlanMarkdown()
    text = QGuiApplication.clipboard().text()
    assert text.startswith("**Pit Stop Plan") and "```" in text and "Energy" not in text  # hidden column left out
    target = tmp_path / "plan.csv"
    host.save_path = str(target)
    calculator.exportPlanCsv()
    rows = target.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("Stop,Lap,Window,Time") and rows[2].startswith("1,33,7-33,0:49")
    image = tmp_path / "plan.png"
    host.save_path = str(image)
    calculator.savePlanImage()
    assert image.stat().st_size > 0


def test_plan_picture_copied(calculator, host):  # noqa: F811
    from PySide6.QtGui import QGuiApplication

    set_race(calculator, laps=40, tank=45)
    calculator.set_values({"input_drivers": 2, "enable_safety_car": True, "input_sc_lap": 10})
    QGuiApplication.clipboard().clear()
    calculator.copyPlanImage()
    image = QGuiApplication.clipboard().image()
    assert not image.isNull() and image.width() >= 900 and host.toasts[-1] == "Plan image copied"


def test_inputs_saved_and_restored(calculator):
    from tinypedal.ui import race_calculator

    set_race(calculator, laps=30, fuel=2.5, pit=45)
    calculator.setInput("input_safety_margin", 0.5)
    config = cfg.user.config["fuel_calculator"]
    assert config["input_race_laps"] == 30 and config["enable_lap_race"] is True
    assert config["input_safety_margin"] == pytest.approx(0.5)
    minfo.history.consumptionDataSet = ()  # nothing live: saved inputs stay
    dialog = race_calculator.RaceCalculator(None)
    try:
        values = dialog.backend.values
        assert values["enable_lap_race"] and values["input_race_laps"] == 30
        assert values["input_pit_seconds"] == pytest.approx(45)
        assert values["input_fuel_per_lap"] == pytest.approx(2.5)
    finally:
        dialog.close()
        dialog.deleteLater()


def test_reset_to_zero(calculator):
    set_race(calculator, laps=30, fuel=2.5, pit=45)
    calculator.resetValues()
    values = calculator.values
    assert values["input_lap_time"] == 0 and values["input_fuel_per_lap"] == 0
    assert values["input_race_laps"] == 0 and values["input_pit_seconds"] == 0
    assert values["input_tread_start"] == 100  # new tyres
    assert tile(calculator, "fuel")["value"] == "-" and not calculator.notes["fillSource"]


def test_one_calculation_per_batch(calculator):
    calculations = calculator.calculations
    calculator.fill_in_data(HISTORY)  # several inputs at once
    assert calculator.calculations == calculations + 1
    calculator.setInput("input_race_laps", 7)
    assert calculator.calculations == calculations + 2
    calculator.setInput("input_race_laps", 7)  # same value: nothing to calculate
    assert calculator.calculations == calculations + 2


def test_live_race_length_filled(calculator, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.ui.quick.race_model import live_race_length

    session = api.read.session
    monkeypatch.setattr(type(session), "session_type", lambda self: 4, raising=False)
    monkeypatch.setattr(type(session), "finish_type", lambda self, as_lap=None: 0, raising=False)
    monkeypatch.setattr(type(session), "start", lambda self: 0.0, raising=False)
    monkeypatch.setattr(type(session), "end", lambda self: 6 * 3600.0, raising=False)
    assert live_race_length() == ("minutes", 360)
    calculator.loadLive()
    assert not calculator.values["enable_lap_race"] and calculator.values["input_race_minutes"] == 360
    monkeypatch.setattr(type(session), "finish_type", lambda self, as_lap=None: 1, raising=False)
    monkeypatch.setattr(type(api.read.lap), "maximum", lambda self: 50, raising=False)
    calculator.loadLive()
    assert calculator.values["enable_lap_race"] and calculator.values["input_race_laps"] == 50


def test_live_history_follows_new_laps(calculator, monkeypatch):
    fuel_used = calculator.values["input_fuel_per_lap"]
    calculator.set_active(True)
    new_lap = ConsumptionDataSet(13, 1, 90.0, 2.8, 2.4, 1.0, 0.5, 0.4, 100.0)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", (new_lap, *HISTORY))
    calculator.refresh_live()
    rows = history_rows(calculator)
    assert len(rows) == 4 and rows[0]["cells"][0] == "13"
    assert calculator.values["input_fuel_per_lap"] == fuel_used  # inputs untouched


def test_empty_inputs_show_dashes(ui_env, monkeypatch, host):  # noqa: F811
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", (ConsumptionDataSet(),))  # placeholder only
    dialog = race_calculator.RaceCalculator(None)
    try:
        backend = dialog.backend
        assert detail(backend, "total_needed")["fuel"] == "-"
        assert tile(backend, "fuel")["value"] == "-"
        assert backend.tyreLife["laps"] == "-"  # no wear entered
        assert not backend.timeline["ready"] and not backend.timeline["stops"]
        assert backend.history["empty"] and not backend.history["rows"]  # placeholder not shown
        assert not backend.plan["ready"]
        assert backend.fuelLevels == []
    finally:
        dialog.close()
        dialog.deleteLater()


def test_history_sorted_and_valid_only(calculator):
    calculator.sortHistory(1)  # by lap time, numbers by value
    assert [row["cells"][0] for row in history_rows(calculator)] == ["12", "11", "10"]
    calculator.sortHistory(2)
    calculator.sortHistory(2)  # by fuel, clicked again: other way
    assert history_rows(calculator)[0]["cells"][2] == "3.600"
    assert calculator.history["sortColumn"] == 2 and not calculator.history["sortAscending"]
    select(calculator, "10")
    calculator.setValidOnly(True)
    assert len(history_rows(calculator)) == 2 and cfg.user.config["fuel_calculator"]["enable_valid_laps_only"] is True
    assert calculator.historySelection == []  # hidden lap not selected any more
    calculator.setValidOnly(False)
    assert len(history_rows(calculator)) == 3


def test_delete_live_history(calculator, monkeypatch, tmp_path):
    from collections import deque

    from tinypedal.api_control import api

    history = deque(HISTORY, 100)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", history)
    monkeypatch.setattr(type(api.read.session), "combo_name", lambda self: "Spa - GT3", raising=False)
    calculator.loadLive()
    select(calculator, "12")
    calculator.deleteSelectedLaps()
    assert len(history) == 2 and len(history_rows(calculator)) == 2
    saved = tmp_path / "fuel_delta" / "Spa - GT3.consumption"
    assert saved.exists()
    calculator.deleteAllLaps()  # whole history
    assert not history_rows(calculator) and calculator.history["empty"]
    assert len(history) == 1 and history[0] == ConsumptionDataSet()  # placeholder: module keeps reading [0]
    assert not saved.exists()


def test_delete_from_file_history(calculator, host, tmp_path):  # noqa: F811
    from tinypedal.userfile.consumption_history import load_consumption_history_file, save_consumption_history_file

    save_consumption_history_file(HISTORY, f"{tmp_path.as_posix()}/", "Monza - LMP2")
    host.open_path = str(tmp_path / "Monza - LMP2.consumption")
    calculator.loadFile()
    calculator.delete_laps({0, 1})  # first two laps of history data
    kept = [lap for lap in load_consumption_history_file(f"{tmp_path.as_posix()}/", "Monza - LMP2") if lap.lapTimeLast]
    assert [lap.lapNumber for lap in kept] == [10]  # one lap left (saved with placeholder)
    assert "2 lap(s) deleted" in calculator.notes["historyAdded"]


def test_new_inputs_saved_and_used(calculator):
    set_race(calculator, laps=40, tank=45, fuel=3.0, pit=20)
    calculator.set_values({"input_refuel_rate": 3.0, "input_drivers": 2, "input_driver_change_seconds": 10})
    config = cfg.user.config["fuel_calculator"]
    assert config["input_refuel_rate"] == 3.0 and config["input_drivers"] == 2
    stop = calculator.strategy.stops[0]
    assert stop.seconds == pytest.approx(20 + 15 + 10) and stop.driver == 2
    assert "driver" not in calculator.plan["hidden"] and cell(calculator, 1, "driver") == "2"
    assert cell(calculator, 1, "seconds") == "45.0"
    text = calculator.plan_text()
    assert "Driver 2" in text and "45.0 s" in text and "s in the pits" in text


def test_saving_target_card(calculator):
    set_race(calculator, laps=40, tank=45, fuel=3.0)  # 2 stops
    assert "20 laps per stint, 1 stop(s)" in calculator.scenarios["oneLess"]
    calculator.setInput("input_target_stint_laps", 40)
    assert "0 stop(s) with this target" in calculator.scenarios["target"]
    # Details show the same consumption as the card (one stop less, safety margin kept)
    calculator.setInput("input_safety_margin", 1.0)
    assert "2.143 L per lap" in calculator.scenarios["oneLess"]
    assert detail(calculator, "one_less_stint")["fuel"] == "2.143"


def test_starting_fuel_clamped_in_one_calculation(calculator):
    set_race(calculator, laps=40, tank=100)
    calculator.setInput("input_fuel_start", 80)
    calculations = calculator.calculations
    calculator.setInput("input_tank_capacity", 50)
    assert calculator.values["input_fuel_start"] == 50 and calculator.calculations == calculations + 1


def test_energy_only_page(calculator):
    set_race(calculator, laps=40, tank=0, fuel=0, energy=4.0)
    assert calculator.strategy.ready and not tile(calculator, "fuel")["visible"] and tile(calculator, "energy")["visible"]
    assert detail(calculator, "total_needed")["fuel"] == "-"
    assert tile(calculator, "refill")["value"] == "60.0 %"


def test_follow_live(calculator, monkeypatch):
    calculator.set_active(True)
    calculator.setFollowLive(True)
    assert cfg.user.config["fuel_calculator"]["enable_follow_live"] is True and calculator.header["followLive"]
    new_laps = tuple(ConsumptionDataSet(20 + i, 1, 88.0, 2.5, 2.0, 1.0, 0.5, 0.4, 100.0) for i in range(5))
    monkeypatch.setattr(minfo.history, "consumptionDataSet", new_laps)
    calculator.refresh_live_history()
    assert calculator.values["input_fuel_per_lap"] == pytest.approx(2.5)  # inputs follow new laps


def test_race_plan_file(calculator, host, tmp_path):  # noqa: F811
    set_race(calculator, laps=30, fuel=2.5, pit=45)
    calculator.proposeChanges()
    rows = [list(row) for row in calculator.tyres.rows]
    target = tmp_path / "Le Mans.race-plan"
    host.save_path = str(target)
    calculator.saveRacePlan()
    assert target.exists() and host.toasts
    calculator.resetValues()
    calculator.newTyrePlan()
    host.open_path = str(target)
    calculator.openRacePlan()
    assert calculator.values["input_race_laps"] == 30 and calculator.values["input_pit_seconds"] == pytest.approx(45)
    assert calculator.tyres.rows == rows and calculator.tyres.name == "Untitled plan"
    # Invalid file: warned, nothing changed
    bad = tmp_path / "bad.race-plan"
    bad.write_text("{}", encoding="utf-8")
    host.open_path = str(bad)
    calculator.openRacePlan()
    assert host.warnings and calculator.values["input_race_laps"] == 30


def test_fuel_tile_back_after_energy_only_car(calculator):
    set_race(calculator, laps=40, tank=0, fuel=0, energy=4.0)
    assert not tile(calculator, "fuel")["visible"]
    set_race(calculator, laps=0, tank=100, fuel=3.0)  # fuel car, race not set yet
    assert tile(calculator, "fuel")["visible"]


def test_details_full_tank_and_refuel_stops(calculator):
    set_race(calculator, laps=10, tank=100, fuel=3.0)  # race fits in one tank
    assert detail(calculator, "stint_laps")["fuel"] == "33.33"  # a full tank, not the race
    assert detail(calculator, "pit_stops")["title"] == "Refuel Stops" and tile(calculator, "pits")["title"] == "Pit Stops"


def test_start_fuel_below_one_lap_warned(calculator):
    set_race(calculator, laps=20, tank=100, fuel=3.0)
    calculator.setInput("input_fuel_start", 2.0)
    assert not calculator.strategy.stops and "Starting fuel" in calculator.summary["text"]


def test_start_time_window_balanced_margin_unit(calculator):
    set_race(calculator, laps=40, tank=45, fuel=3.0)
    calculator.setStartTime(True, "14:00")
    assert cell(calculator, 1, "time") == "14:22" and cell(calculator, 1, "window") == "10-15"  # 15 laps of 90 s
    calculator.setInput("enable_balanced_stints", True)
    assert calculator.strategy.stints == [14, 13, 13]
    calculator.setInput("input_safety_margin_kind", 1)  # fuel units
    calculator.setInput("input_safety_margin", 3.0)
    assert calculator.strategy.max_stint == 14 and calculator.marginSpec["suffix"] == "L"
    assert calculator.marginSpec["max"] == 9999
    config = cfg.user.config["fuel_calculator"]
    assert config["input_safety_margin_kind"] == 1 and config["enable_balanced_stints"] is True
    assert config["input_race_start_minutes"] == 14 * 60
    calculator.setInput("input_safety_margin", 500)
    calculator.setInput("input_safety_margin_kind", 0)  # laps: kept in range of laps
    assert calculator.values["input_safety_margin"] == 99


def test_timeline_details_and_safety_car(calculator):
    set_race(calculator, laps=40, tank=45, fuel=3.0, pit=60)
    timeline = calculator.timeline
    stop = timeline["stops"][0]
    assert stop["pos"] == pytest.approx(15 / 40) and "Stop 1" in stop["tip"] and "Pit Window 10-15" in stop["tip"]
    assert "Stint 1" in timeline["stints"][0]["tip"] and timeline["stints"][0]["laps"] == 15
    calculator.set_values({"enable_safety_car": True, "input_sc_lap": 10, "input_sc_laps": 4, "enable_sc_pit": True})
    assert calculator.strategy.safety_car == (10, 4) and calculator.strategy.stops[0].lap == 10
    assert "Without safety car" in calculator.scenarios["safetyCar"]
    assert "Safety Car 10-13" in calculator.summary["text"]
    band = calculator.timeline["bands"][0]
    assert band["start"] == pytest.approx(9 / 40) and band["end"] == pytest.approx(13 / 40)


def test_drivers_and_comparison_cards(calculator):
    assert not calculator.driverTimes["visible"]
    set_race(calculator, laps=60, tank=40, fuel=2.0, pit=60)
    calculator.setInput("input_drivers", 2)
    calculator.setDriverValue(1, 0, 2.0)  # 2nd driver 2 s slower
    calculator.setDriverValue(0, 2, 40)  # 1st driver: 40 min at most
    assert calculator.driverTimes["visible"]
    assert calculator.strategy.stint_drivers == [1, 2, 2]
    assert cfg.user.config["fuel_calculator"]["input_driver_table"] == "0:0:40,2:0:0"
    assert calculator.inputs["drivers_table"][1][0] == 2.0
    rows = calculator.driverTimes["rows"]
    assert len(rows) == 2 and rows[0][1] == "1"
    comparison = calculator.scenarios["comparison"]
    assert comparison["visible"] and len(comparison["rows"]) >= 2
    assert {stint["color"] for stint in calculator.timeline["stints"]} == {"#4C9AFF", "#F5A623"}  # driver colors
    calculator.setInput("input_saving_cost", 0.5)
    assert "Saving Cost" in calculator.scenarios["oneLess"]
    assert calculator.setDriverValue(0, 0, 99) == 9.0 and calculator.setDriverValue(12, 0, 1) == 0.0


def test_estimate_from_history(calculator):
    laps = []
    number = 1
    for stint in range(3):
        for lap in range(10):
            laps.append(ConsumptionDataSet(number, 1, 100.0 - 0.09 * lap, 3.0))
            number += 1
        if stint < 2:
            laps += [ConsumptionDataSet(number, 1, 125.0, 3.0), ConsumptionDataSet(number + 1, 1, 125.0, 1.0)]
            number += 2
    calculator.refresh_history(list(reversed(laps)))
    calculator.estimateFromHistory()
    assert calculator.values["input_pit_seconds"] == pytest.approx(50, abs=1)
    assert calculator.values["input_fuel_effect"] == pytest.approx(0.3, abs=0.02)
    assert "Pit Stop Time" in calculator.notes["estimate"]


def test_history_serials_kept_for_new_laps(calculator):
    first = history_rows(calculator)[0]["serial"]
    select(calculator, "12")
    newer = ConsumptionDataSet(13, 1, 89.5, 2.9, 2.4, 1.0, 0.5, 0.4, 100.0)
    calculator.refresh_history((newer, *HISTORY))
    rows = history_rows(calculator)
    assert len(rows) == 4 and rows[0]["cells"][0] == "13" and rows[1]["serial"] == first  # laps before kept
    assert calculator.historySelection == [first]  # selection kept
    assert calculator.selected_indexes() == {1}


def test_new_scenario_inputs_saved(calculator):
    set_race(calculator, minutes=60, pit=30)
    laps = calculator.strategy.race_laps
    calculator.set_values({
        "enable_leader_finish": True, "input_pit_lap_consumption": 80, "input_sc_wear": 30, "enable_rain": True,
        "input_rain_lap": 10, "input_rain_laps": 5,
    })
    assert calculator.strategy.rain == (10, 14) and calculator.strategy.race_laps < laps + 1  # wet laps slower
    assert [stop.reason for stop in calculator.strategy.stops][:2] == ["rain", "dry"]
    assert cell(calculator, 1, "stop") == "1 Wet" and cell(calculator, 2, "stop") == "2 Dry"
    assert "Without rain" in calculator.scenarios["rain"]
    config = cfg.user.config["fuel_calculator"]
    assert config["enable_leader_finish"] is True and config["input_pit_lap_consumption"] == 80
    assert config["enable_rain"] is True and config["input_rain_lap"] == 10 and config["input_sc_wear"] == 30


def test_start_at_midnight(calculator):
    set_race(calculator, laps=40, tank=45, fuel=3.0)
    calculator.setStartTime(True, "00:00")
    assert calculator.values["input_race_start_minutes"] == 0 and cell(calculator, 1, "time") == "00:22"
    calculator.setStartTime(False, "00:00")
    assert calculator.values["input_race_start_minutes"] == -1 and cell(calculator, 1, "time") == "0:22"


def test_scenarios_deferred_while_changing_quickly(calculator, monkeypatch):
    from tinypedal.ui.quick import race_backend

    set_race(calculator, laps=40, tank=45, fuel=3.0)
    monkeypatch.setattr(race_backend, "SCENARIO_DELAY_MS", 150)
    calls = []
    real = calculator.update_scenarios
    monkeypatch.setattr(calculator, "update_scenarios", lambda: calls.append(1) or real())
    calculator._last_calculation = 0.0
    calculator.setInput("input_fuel_per_lap", 3.1)  # after a pause: at once
    assert calls == [1]
    calculator.setInput("input_fuel_per_lap", 3.2)  # arrow held: once settled
    calculator.setInput("input_fuel_per_lap", 3.3)
    assert calls == [1] and calculator._scenario_timer.isActive()


def test_export_folder_remembered(calculator, monkeypatch, tmp_path):
    from tinypedal.ui import race_calculator

    set_race(calculator, laps=40, tank=45, fuel=3.0)
    folder = tmp_path / "plans"
    folder.mkdir()
    asked = []

    def save_dialog(self, directory, file_filter):
        asked.append(directory)
        return str(folder / "plan.csv")

    monkeypatch.setattr(race_calculator.RaceCalculator, "save_file", save_dialog)
    calculator.exportPlanCsv()
    calculator.exportPlanCsv()
    assert asked[1].replace("\\", "/").startswith(folder.as_posix())


def test_full_history_shifted(calculator):
    laps = [ConsumptionDataSet(100 - index, 1, 90.0, 3.0) for index in range(100)]  # full history
    calculator.refresh_history(laps)
    select(calculator, "50")
    selected = list(calculator.historySelection)
    calculator.refresh_history([ConsumptionDataSet(101, 1, 90.0, 3.0), *laps[:-1]])  # newest in, oldest out
    numbers = {row["cells"][0] for row in history_rows(calculator)}
    assert len(numbers) == 100 and "101" in numbers and "1" not in numbers
    assert calculator.historySelection == selected  # same lap still selected
    select(calculator, "101")
    assert calculator.selected_indexes() == {0}


def test_fuel_levels_follow_stops(calculator):
    set_race(calculator, laps=40, tank=45, fuel=3.0)  # stops at 15 & 30
    levels = calculator.fuelLevels
    assert levels[0] == [0.0, 1.0]  # full tank at start
    assert levels[1][0] == pytest.approx(15 / 40) and levels[1][1] == pytest.approx(0.0, abs=0.01)  # empty at stop
    assert levels[2][1] == pytest.approx(1.0)  # full after stop
    assert levels[-1][0] == 1.0 and 0 <= levels[-1][1] <= 1


def test_game_estimate_and_team_fill_in(calculator, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.process.team_usage import StintUsage

    monkeypatch.setattr(api.read.engine, "expected_fuel_consumption", lambda: 2.78)
    monkeypatch.setattr(api.read.engine, "expected_energy_consumption", lambda: 3.26)
    monkeypatch.setattr(api.read.engine, "tank_capacity", lambda *args: 120.0)
    calculator.fill_in_data([])
    assert calculator.values["input_fuel_per_lap"] == pytest.approx(2.78, abs=0.01)
    assert calculator.values["input_tank_capacity"] == pytest.approx(120.0)
    assert "Game estimate" in calculator.notes["fillSource"]
    calculator.show_team_stints([StintUsage("A", 1, 1, 6, 4, 0.03, 0.04, 0.5)], 100.0)
    calculator.fillInTeam()
    assert calculator.values["input_fuel_per_lap"] == pytest.approx(3.0)
    assert calculator.values["input_energy_per_lap"] == pytest.approx(4.0)
