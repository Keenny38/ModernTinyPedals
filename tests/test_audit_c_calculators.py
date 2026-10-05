"""Race calculator audit fixes: failed saves warned, fuel unit of plans & share codes,
huge & nan values of files, tyre planner texts translated"""

import base64
import json
import os
import zlib

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

from tinypedal import i18n
from tinypedal.module_info import ConsumptionDataSet, minfo
from tinypedal.setting import cfg
from tinypedal.ui._common import BaseEditor

HISTORY = (
    ConsumptionDataSet(12, 1, 90.5, 3.0, 2.5, 1.0, 0.5, 0.4, 100.0),
    ConsumptionDataSet(11, 1, 91.5, 3.2, 2.6, 1.1, 0.4, 0.5, 100.0),
    ConsumptionDataSet(10, 1, 92.0, 3.1, 2.7, 1.2, 0.3, 0.6, 100.0),
)


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


class Warnings(list):
    """Warning texts shown, toasts in toasts"""

    def __init__(self):
        super().__init__()
        self.toasts: list[str] = []


@pytest.fixture
def warnings(monkeypatch):
    """Warning texts & toasts (no modal box offscreen), questions answered yes"""
    from tinypedal.ui import race_calculator

    found = Warnings()
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda parent, title, text, *args, **kwargs:
                                                             found.append(text)))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(race_calculator, "show_toast", lambda parent, text: found.toasts.append(text))
    return found


@pytest.fixture
def make_page(ui_env, monkeypatch, warnings):
    """Race calculator page in a fuel unit (closed after test)"""
    from tinypedal.ui.quick import race_backend

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(race_backend, "SCENARIO_DELAY_MS", 0)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    pages = []

    def make(unit: str = "Liter"):
        from tinypedal.ui import race_calculator

        cfg.units["fuel_unit"] = unit
        page = race_calculator.RaceCalculator(None)
        pages.append(page)
        return page

    yield make
    for page in pages:
        page.set_unmodified()
        page.close()
        page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def failing_replace(*args, **kwargs):
    raise PermissionError(13, "Permission denied (file open in another program)")


def answer_files(monkeypatch, path):
    """File dialogs of the page answered with path"""
    from tinypedal.ui import race_calculator

    answer = staticmethod(lambda *args, **kwargs: (str(path), ""))
    monkeypatch.setattr(race_calculator.QFileDialog, "getOpenFileName", answer)
    monkeypatch.setattr(race_calculator.QFileDialog, "getSaveFileName", answer)


# Item 10: failed saves warned, never reported as done
def test_race_plan_save_failure_warned(make_page, warnings, monkeypatch, tmp_path):
    page = make_page()
    target = tmp_path / "plan.race-plan"
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", failing_replace)  # target locked
        page.backend.save_race_plan(str(target))
    assert warnings and "Unable to save race plan" in warnings[0]
    assert not warnings.toasts  # no "saved" toast
    assert not target.exists() and not list(tmp_path.glob("*.tmp"))


def test_race_plan_saved_once_writable(make_page, warnings, tmp_path):
    page = make_page()
    target = tmp_path / "plan.race-plan"
    page.backend.save_race_plan(str(target))
    assert not warnings and warnings.toasts
    assert json.loads(target.read_text(encoding="utf-8"))["fuel_unit"] == "Liter"


def test_delete_laps_failure_warned(make_page, warnings, monkeypatch, tmp_path):
    from tinypedal.ui.quick import race_backend
    from tinypedal.userfile.consumption_history import load_consumption_history_file, save_consumption_history_file

    backend = make_page().backend
    folder = f"{tmp_path.as_posix()}/"
    save_consumption_history_file(HISTORY, folder, "Monza - LMP2")
    path = tmp_path / "Monza - LMP2.consumption"
    answer_files(monkeypatch, path)
    backend.loadFile()
    assert len(backend.history["rows"]) == 3
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", failing_replace)  # file locked: not rewritten
        backend.delete_laps({0})
    assert warnings and "Unable to save consumption history" in warnings[-1]
    assert len(backend.history["rows"]) == 3 and "deleted" not in backend.notes["historyAdded"]
    assert len(load_consumption_history_file(folder, "Monza - LMP2")) == 3
    with monkeypatch.context() as patch:
        patch.setattr(race_backend.os, "remove", failing_replace)  # whole history: file locked
        backend.delete_laps(None)  # warned, no PermissionError
    assert len(warnings) == 2 and path.exists() and len(backend.history["rows"]) == 3
    backend.delete_laps({0})  # writable again: deleted & saved
    assert len(warnings) == 2 and len(backend.history["rows"]) == 2
    assert len(load_consumption_history_file(folder, "Monza - LMP2")) == 2


def test_plan_export_failures_warned(make_page, warnings, monkeypatch, tmp_path):
    backend = make_page().backend
    backend.set_values({"input_lap_time": 90.0, "input_tank_capacity": 100.0, "input_fuel_per_lap": 3.0,
                        "input_race_minutes": 60, "enable_lap_race": False})
    locked = tmp_path / "locked.csv"
    locked.mkdir()  # cannot be written as a file
    answer_files(monkeypatch, locked)
    backend.exportPlanCsv()  # no PermissionError
    assert len(warnings) == 1 and "Unable to export" in warnings[0]
    image = tmp_path / "locked.png"
    image.mkdir()
    answer_files(monkeypatch, image)
    backend.savePlanImage()  # QImage.save failed: warned
    assert len(warnings) == 2 and "Unable to save picture" in warnings[1]
    assert cfg.user.config["fuel_calculator"].get("export_path", "") != f"{tmp_path.as_posix()}/"


def test_tyre_plan_save_failures_warned(make_page, warnings, monkeypatch, tmp_path):
    page = make_page()
    backend = page.backend
    backend.setPlanName("Le Mans")
    backend.setTyreRule("maximum_tyre", 12)  # edited: modified
    assert page.is_modified()
    locked = tmp_path / "locked.tyres"
    locked.mkdir()
    answer_files(monkeypatch, locked)
    backend.saveTyrePlan()  # no PermissionError
    assert len(warnings) == 1 and "Unable to save tyre strategy file" in warnings[0]
    assert backend.tyrePlan["name"] == "Le Mans" and page.is_modified()
    assert not warnings.toasts
    backend.exportTyrePlanCsv()
    assert len(warnings) == 2 and "Unable to export" in warnings[1]
    assert not warnings.toasts


# Item 11: fuel unit of race plans & share codes, nan refused
def set_fuel_inputs(backend):
    from tinypedal.fuel_strategy import MARGIN_UNITS

    backend.set_values({
        "input_lap_time": 90.0, "input_tank_capacity": 100.0, "input_fuel_per_lap": 3.0,
        "input_energy_per_lap": 2.5, "input_fuel_start": 50.0, "input_refuel_rate": 2.0,
        "input_safety_margin_kind": MARGIN_UNITS.index("fuel"), "input_fuel_effect": 0.3,
        "input_race_laps": 40, "enable_lap_race": True,
    })
    backend.setInput("input_safety_margin", 5.0)


def paste(page, monkeypatch, code: str):
    from tinypedal.ui import race_calculator

    monkeypatch.setattr(race_calculator.QInputDialog, "getText", staticmethod(lambda *args, **kwargs: (code, True)))
    page.backend.pasteShareCode()


def test_share_code_converted_to_fuel_unit(make_page, warnings, monkeypatch):
    from tinypedal.ui.quick.race_model import decode_share_code, encode_share_code

    litre = make_page("Liter")
    set_fuel_inputs(litre.backend)
    litre.backend.copyShareCode()
    code = QGuiApplication.clipboard().text()
    assert decode_share_code(code)["fuel_unit"] == "Liter"

    gallon = make_page("Gallon")
    paste(gallon, monkeypatch, code)
    values = gallon.backend.values
    assert not warnings
    assert values["input_tank_capacity"] == pytest.approx(26.42)  # 100 L
    assert values["input_fuel_per_lap"] == pytest.approx(0.793)  # 3 L
    assert values["input_fuel_start"] == pytest.approx(13.21)  # 50 L
    assert values["input_refuel_rate"] == pytest.approx(0.53)  # 2 L/s
    assert values["input_safety_margin"] == pytest.approx(1.32)  # 5 L kept in the tank
    assert values["input_fuel_effect"] == pytest.approx(1.136)  # per 10 gal
    assert values["input_energy_per_lap"] == pytest.approx(2.5)  # energy: same %
    assert values["input_race_laps"] == 40
    assert gallon.backend.race_plan_data()["fuel_unit"] == "Gallon"

    # Gallon code opened by a litre user
    other = make_page("Liter")
    paste(other, monkeypatch, encode_share_code(gallon.backend.race_plan_data()))
    assert other.backend.values["input_tank_capacity"] == pytest.approx(100.01, abs=0.02)

    # Code without unit (before fuel unit was kept): litres
    data = litre.backend.race_plan_data()
    del data["fuel_unit"]
    paste(gallon, monkeypatch, encode_share_code(data))
    assert gallon.backend.values["input_tank_capacity"] == pytest.approx(26.42)
    assert not warnings


def test_plan_file_without_unit_kept_in_page_unit(make_page, warnings, tmp_path):
    """Own plan file saved before fuel unit was kept: in fuel unit of page, not converted"""
    gallon = make_page("Gallon")
    set_fuel_inputs(gallon.backend)
    data = gallon.backend.race_plan_data()
    del data["fuel_unit"]
    target = tmp_path / "old.race-plan"
    target.write_text(json.dumps(data), encoding="utf-8")
    capacity = gallon.backend.values["input_tank_capacity"]
    other = make_page("Gallon")
    assert other.backend.load_race_plan(str(target))
    assert other.backend.values["input_tank_capacity"] == pytest.approx(capacity)
    assert not warnings


def test_share_code_with_nan_refused(make_page, warnings, monkeypatch):
    from tinypedal.ui.quick.race_model import RACE_PLAN_FORMAT, SHARE_CODE_PREFIX, decode_share_code

    page = make_page()
    set_fuel_inputs(page.backend)
    for number in ("NaN", "Infinity", "-Infinity", "1e999"):
        text = f'{{"format":"{RACE_PLAN_FORMAT}","inputs":{{"input_tank_capacity":{number}}}}}'
        code = SHARE_CODE_PREFIX + base64.urlsafe_b64encode(zlib.compress(text.encode())).decode()
        with pytest.raises(ValueError):
            decode_share_code(code)
        paste(page, monkeypatch, code)
    assert len(warnings) == 4 and all(text == "Invalid race plan share code." for text in warnings)
    assert page.backend.values["input_tank_capacity"] == pytest.approx(100.0)  # nothing applied
    assert not warnings.toasts
    paste(page, monkeypatch, SHARE_CODE_PREFIX + base64.urlsafe_b64encode(zlib.compress(b"[1]")).decode())
    assert len(warnings) == 5  # not a race plan: warned too


# Item 23: huge & nan values of files
def test_huge_plan_values_not_half_applied(make_page, warnings):
    from tinypedal.ui.quick.race_model import RACE_PLAN_FORMAT

    backend = make_page().backend
    inputs = {
        "input_lap_time": 1e300, "input_race_minutes": 1e300, "input_race_laps": 10 ** 400,
        "enable_lap_race": True, "input_pit_seconds": 30.0, "input_drivers": 10 ** 20,
        "input_sc_lap": -1e300, "input_safety_margin_kind": 10 ** 30, "input_fuel_start": -(10 ** 500),
    }
    tyre_rule = {"maximum_tyre": 10 ** 30, "enable_restricted_allocation": True, "tyre_change_time_1": 1e300,
                 "tyre_change_time_2": 4.5, "tyre_change_time_3": 12.0, "tyre_change_time_4": 12.0}
    data = {"format": RACE_PLAN_FORMAT, "inputs": inputs, "tyre_strategy": {"tyre_rule": tyre_rule}}
    assert backend.apply_race_plan(data, "Huge")  # no OverflowError
    values = backend.values
    assert values["input_race_laps"] == 9999 and values["input_race_minutes"] == 9999
    assert values["input_pit_seconds"] == pytest.approx(30.0)  # applied with the huge ones
    assert values["input_drivers"] == 9 and values["input_safety_margin_kind"] == 0
    assert values["input_sc_lap"] == 1 and values["input_fuel_start"] == 0
    assert values["input_lap_time"] <= 9999 * 60
    rule = backend.tyrePlan["rule"]
    assert rule["maximum_tyre"] == 999 and rule["tyre_change_time_1"] == pytest.approx(99.0)
    assert backend.tyrePlan["name"] == "Huge"


def test_nan_tread_of_tyre_file_shown(make_page, warnings, monkeypatch, tmp_path):
    from tinypedal.userfile.tyre_strategy import create_tyre_strategy

    backend = make_page().backend
    data = create_tyre_strategy()
    data["tyre_set"]["Medium"]["front_left_starting_tread"] = float("nan")
    data["tyre_set"]["Medium"]["front_right_wear_per_stint"] = float("inf")
    data["tyre_set"]["Medium"]["rear_left_wear_per_stint"] = "worn"
    data["tyre_rule"]["tyre_change_time_4"] = float("nan")
    path = tmp_path / "nan.tyres"
    path.write_text(json.dumps(data), encoding="utf-8")  # NaN & Infinity written as JSON allows
    answer_files(monkeypatch, path)
    backend.openTyrePlan()
    assert not warnings
    medium = backend.tyres.user_data["tyre_set"]["Medium"]
    assert medium["front_left_starting_tread"] == 100  # default of compound
    assert medium["front_right_wear_per_stint"] == 30 and medium["rear_left_wear_per_stint"] == 30
    assert backend.tyres.full_change_seconds() == pytest.approx(12.0)
    backend.setStockCompound("Medium")
    backend.proposeChanges()
    cells = backend.tyrePlan["rows"][0]["cells"]
    assert all(cell["name"] and cell["text"] for cell in cells)


def test_nan_tread_view_values():
    from tinypedal.ui.quick.race_tyres import tread_color, tread_text

    for percent, wear in ((float("nan"), 0.1), (float("-inf"), 0.0), (-1e300, 0.1), (0.5, float("nan"))):
        assert tread_text(percent, percent - wear)  # no ValueError / OverflowError
        assert tread_color(percent).startswith("#")


# Item 29: tyre planner texts translated
def test_tyre_planner_texts_translated(french):
    from tinypedal.ui.quick.race_tyres import TyrePlan, tread_text

    assert tread_text(1.0, 0.7) == "Neuf-70%" and tread_text(0.2, -0.1) == "Éclaté"
    plan = TyrePlan()
    for _ in range(6):
        plan.add_tyre("Medium")
    plan.insert_row(-1)
    plan.assign(0, 0, "Medium #1")
    plan.assign(1, 0, "Medium #2")
    view = plan.view()
    assert view["rows"][0]["change"] == "N/D" and view["rows"][1]["change"] == "+4.5s"
    status = view["status"]
    assert i18n.trm(f"Stock: {status['stock']} / {status['maximum']} ({i18n.tr('invalid')})") == (
        "Stock : 6 / 4 (invalide)")
    assert plan.assign(1, 1, "Medium #2").startswith("<b>Medium #2</b>")
    assert "already" not in plan.assign(1, 1, "Medium #2")  # message translated


def test_calculator_messages_translated(french):
    trm = i18n.trm
    assert trm("Cannot open selected file.<br><br>Invalid tyre strategy file.") == (
        "Impossible d'ouvrir le fichier sélectionné.<br><br>Fichier de stratégie pneus invalide.")
    assert trm("Unable to save race plan:<br><b>C:/plans/Spa.race-plan</b>") == (
        "Impossible d'enregistrer le plan de course :<br><b>C:/plans/Spa.race-plan</b>")
    assert trm("Unable to save consumption history: Spa - GT3.consumption") == (
        "Impossible d'enregistrer l'historique de consommation : Spa - GT3.consumption")
    assert trm("Unable to save tyre strategy file:<br><br>[Errno 13] Permission denied: 'x.tyres'") == (
        "Impossible d'enregistrer la stratégie pneus :<br><br>[Errno 13] Permission denied: 'x.tyres'")
    assert trm("Unable to export: [Errno 13] Permission denied: 'C:/plan.csv'") == (
        "Impossible d'exporter : [Errno 13] Permission denied: 'C:/plan.csv'")
    assert trm("Unable to save picture: C:/plan.png") == "Impossible d'enregistrer l'image : C:/plan.png"
    assert trm("New-100%") == "Neuf-100%"
    assert i18n.tr("N/A") == "N/D" and i18n.tr("Blowout") == "Éclaté"
