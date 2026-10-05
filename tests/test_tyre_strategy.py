"""Tyre strategy tests: file validation, planner stints, wear, change time, save, load & export"""

import csv
import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tinypedal.userfile import tyre_strategy
from tinypedal.userfile.tyre_strategy import (
    DEFAULT_TYRE_RULE,
    create_tyre_strategy,
    decode_tyre_name,
    encode_tyre_name,
    load_tyre_strategy_file,
    validate_tyre_strategy,
    verify_tyre_name,
)


# --- File & validation
def test_tyre_name_encoding():
    assert encode_tyre_name("Soft", ("Soft #1", "Soft #2", "Medium #3")) == "Soft #3"
    assert decode_tyre_name("Medium #12") == (3, "Medium", 12)
    assert decode_tyre_name("Unknown #1")[0] == 0
    assert verify_tyre_name("Wet #4")
    assert not verify_tyre_name("Wet 4") and not verify_tyre_name("Wet #x") and not verify_tyre_name("Slick #1")
    assert not verify_tyre_name(None)


def test_validate_tyre_strategy_repairs_data():
    data = validate_tyre_strategy({
        "file_version": "1",
        "tyre_rule": {"maximum_tyre": 8, "unknown": 1},
        "tyre_set": "bad",
        "tyre_stock": ["Soft #1", "Soft #1", "Bad #1", "Medium #2"],
        "tyre_plan": [["Soft #1", "Bad #1", "", "Medium #2"], ["Soft #1"], "row"],
    })
    assert data["file_version"] == tyre_strategy.TYRE_STRATEGY_FILE_VERSION
    assert data["tyre_rule"]["maximum_tyre"] == 8 and "unknown" not in data["tyre_rule"]
    assert set(data["tyre_rule"]) == set(DEFAULT_TYRE_RULE)
    assert data["tyre_set"] == tyre_strategy.DEFAULT_TYRE_SET
    assert data["tyre_stock"] == ["Soft #1", "Medium #2"]  # duplicate & invalid removed
    assert data["tyre_plan"] == [["Soft #1", "", "", "Medium #2"]]


def test_load_tyre_strategy_file(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    (tmp_path / "plan.tyres").write_text(json.dumps(create_tyre_strategy()), encoding="utf-8")
    assert load_tyre_strategy_file("plan.tyres", filepath) == create_tyre_strategy()
    (tmp_path / "list.tyres").write_text("[]", encoding="utf-8")
    assert load_tyre_strategy_file("list.tyres", filepath) is None
    assert load_tyre_strategy_file("missing.tyres", filepath) is None


# --- Planner (tyre plan of race calculator)
@pytest.fixture
def plan(ui_env):
    from tinypedal.ui.quick.race_tyres import TyrePlan

    return TyrePlan()


def add_tyres(plan, compound: str, count: int):
    for _ in range(count):
        plan.add_tyre(compound)


def install(plan, row: int, tyres: tuple[str, str, str, str]):
    """Put tyres on a stint row, as dropping them from tyre stock does"""
    while len(plan.rows) <= row:
        plan.insert_row(-1)
    for corner, tyre_name in enumerate(tyres):
        if tyre_name:
            assert plan.assign(row, corner, tyre_name) == ""


def test_planner_wear_and_change_time(plan):
    add_tyres(plan, "Soft", 4)
    add_tyres(plan, "Medium", 4)
    assert plan.stock[-1] == "Medium #4"
    soft = ("Soft #1", "Soft #2", "Soft #3", "Soft #4")
    install(plan, 0, soft)
    plan.insert_row(1, copy_from=0)  # second stint on same tyres
    plan.insert_row(-1)
    install(plan, 2, ("Medium #1", "Medium #2", "Soft #3", "Soft #4"))  # 2 tyres changed
    assert plan.cells[1][0]["remaining"] == pytest.approx(0.6)  # soft: 40% per stint
    assert plan.cells[2][2]["remaining"] == pytest.approx(0.2)
    assert plan.cells[2][0]["remaining"] == pytest.approx(1.0)
    rows = plan.view()["rows"]
    assert rows[1]["change"] == "N/A" and rows[2]["change"] == "+4.5s"
    assert rows[1]["cells"][0]["dim"] and not rows[2]["cells"][0]["dim"]  # used before: dimmed
    status = plan.status()
    assert status["used"] == 6 and status["stints"] == 3 and status["stock"] == 8 and status["maximum"] == 4
    assert plan.stop_change_times() == [0.0, 4.5] and plan.stop_tyre_changes() == [0, 2]


def test_planner_same_tyre_detection(plan):
    add_tyres(plan, "Soft", 4)
    install(plan, 0, ("Soft #1", "Soft #2", "Soft #3", "Soft #4"))
    assert "already installed" in plan.assign(0, 2, "Soft #1")  # already on front left
    plan.insert_row(-1)
    assert "already used" in plan.assign(1, 0, "Soft #2")  # used on front right before
    assert plan.assign(1, 1, "Soft #2") == ""  # same wheel: fine
    assert plan.assign(1, 0, "Soft #9") != ""  # not in stock


def test_planner_remove_tyre_from_set_clears_table(plan):
    add_tyres(plan, "Hard", 4)
    install(plan, 0, ("Hard #1", "Hard #2", "Hard #3", "Hard #4"))
    plan.remove_tyres(["Hard #1"])
    assert plan.rows[0] == ["", "Hard #2", "Hard #3", "Hard #4"]
    plan.remove_tyres(list(plan.stock))
    assert plan.rows[0] == ["", "", "", ""] and not plan.stock


def test_planner_rows(plan):
    plan.delete_rows([0])  # a plan keeps one row
    assert len(plan.rows) == 1
    plan.insert_row(0)
    plan.insert_row(2)
    assert len(plan.rows) == 3
    plan.delete_rows([1])
    assert len(plan.rows) == 2


def test_planner_save_load_and_export(ui_env, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.ui import race_calculator

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(race_calculator.RaceCalculator, "toast", lambda self, text: None)
    monkeypatch.setattr(race_calculator.RaceCalculator, "confirm", lambda self, text: True)
    page = race_calculator.RaceCalculator(None)
    backend = page.backend
    try:
        backend.setStockCompound("Soft")
        for _ in range(4):
            backend.addTyre()
        for corner, name in enumerate(("Soft #1", "Soft #2", "Soft #3", "Soft #4")):
            backend.assignTyre(0, corner, name)
        assert page.is_modified()
        target = tmp_path / "Spa 6h.tyres"
        monkeypatch.setattr(race_calculator.RaceCalculator, "save_file", lambda self, *args: str(target))
        backend.saveTyrePlan()
        assert not page.is_modified()
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved["tyre_plan"] == [["Soft #1", "Soft #2", "Soft #3", "Soft #4"]]
        assert backend.tyrePlan["name"] == "Spa 6h"
        # Export spreadsheet
        exported = tmp_path / "plan.csv"
        monkeypatch.setattr(race_calculator.RaceCalculator, "save_file", lambda self, *args: str(exported))
        backend.exportTyrePlanCsv()
        rows = list(csv.reader(exported.open(encoding="utf-8")))
        assert ["Soft #1", "1"] in rows
        assert rows[-1][:3] == ["1", "Soft #1", "100.00 - 60.00"]
        # Load in new plan
        backend.newTyrePlan()
        assert not backend.tyres.stock
        monkeypatch.setattr(race_calculator.RaceCalculator, "open_file", lambda self, *args: str(target))
        backend.openTyrePlan()
        assert len(backend.tyres.stock) == 4 and backend.tyres.rows == saved["tyre_plan"]
    finally:
        page.set_unmodified()
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_planner_sort_tyre_list(plan):
    add_tyres(plan, "Medium", 1)
    add_tyres(plan, "Soft", 2)
    install(plan, 0, ("Soft #2", "", "", ""))
    plan.sort_stock(by_stints=False)
    assert plan.stock == ["Soft #1", "Soft #2", "Medium #1"]
    plan.sort_stock(by_stints=True)
    assert plan.stock[0] == "Soft #2"


def test_planner_tread_texts_and_colors():
    from tinypedal.ui.quick.race_tyres import tread_color, tread_text

    assert tread_text(1.0, 0.7) == "New-70%" and tread_text(0.95, 0.65) == "95-65%"
    assert tread_text(0.2, -0.1) == "Blowout" and tread_text(float("nan"), 0.1) == "-"
    assert tread_color(0.95) == "#00AA33" and tread_color(0.1) == "#CC0000" and tread_color(float("nan")) == "#CC0000"


def test_tyre_file_values_type_checked(tmp_path):
    """Wrong types, NaN & Infinity in a tyre file are replaced by defaults"""
    import json

    from tinypedal.userfile.tyre_strategy import DEFAULT_TYRE_RULE, DEFAULT_TYRE_SET, load_tyre_strategy_file

    text = json.dumps({
        "tyre_rule": {"maximum_tyre": 4.5, "tyre_change_time_1": "slow", "tyre_change_time_2": 6.0},
        "tyre_set": {"Soft": 5, "Medium": {"front_left_starting_tread": "full", "rear_left_wear_per_stint": 25}},
        "tyre_stock": ["Soft #1", 7], "tyre_plan": [["Soft #1", 3, "", ""]],
    }).replace('"full"', "NaN").replace("25}", "Infinity}")
    (tmp_path / "plan.tyres").write_text(text, encoding="utf-8")
    data = load_tyre_strategy_file("plan.tyres", f"{tmp_path}/")
    assert data["tyre_rule"]["maximum_tyre"] == DEFAULT_TYRE_RULE["maximum_tyre"]
    assert data["tyre_rule"]["tyre_change_time_1"] == DEFAULT_TYRE_RULE["tyre_change_time_1"]
    assert data["tyre_rule"]["tyre_change_time_2"] == 6.0
    assert data["tyre_set"]["Soft"] == DEFAULT_TYRE_SET["Soft"]
    medium = data["tyre_set"]["Medium"]
    assert medium["front_left_starting_tread"] == DEFAULT_TYRE_SET["Medium"]["front_left_starting_tread"]
    assert medium["rear_left_wear_per_stint"] == DEFAULT_TYRE_SET["Medium"]["rear_left_wear_per_stint"]
    assert data["tyre_stock"] == ["Soft #1"] and data["tyre_plan"] == [["Soft #1", "", "", ""]]


def test_tyre_export_atomic(tmp_path):
    import pytest

    from tinypedal.userfile.tyre_strategy import export_tyre_strategy_file

    (tmp_path / "plan.csv").write_text("old", encoding="utf-8")
    with pytest.raises(OSError):
        export_tyre_strategy_file([["rule"]], [], [["row"]], f"{tmp_path}/missing/", "plan.csv")
    export_tyre_strategy_file([["rule", 1]], [["Soft #1", 1]], [["row"]], f"{tmp_path}/", "plan.csv")
    assert "Soft #1" in (tmp_path / "plan.csv").read_text(encoding="utf-8")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["plan.csv"]
