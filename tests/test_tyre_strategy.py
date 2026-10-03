"""Tyre strategy tests: file validation, planner stints, wear, change time, save, load & export"""

import csv
import json
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.ui._common import BaseEditor, table_item
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


# --- Planner
@pytest.fixture
def planner(ui_env, monkeypatch, tmp_path):
    from tinypedal.ui import tyre_strategy_planner

    slot_errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: slot_errors.append(exc_info[1]))
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(tyre_strategy_planner, "show_toast", lambda *args, **kwargs: None)
    editor = tyre_strategy_planner.TyreStrategyPlanner(None)
    yield editor
    editor.set_unmodified()
    editor.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not slot_errors


def install(planner, row: int, tyres: tuple[str, str, str, str]):
    """Put tyres on a stint row, as dropping them from tyre list does"""
    table = planner.tyre_plan
    for column, tyre_name in enumerate(tyres):
        table_item(table, row, column).setText(tyre_name)
        table._add_stats(row, column)
    table.refresh.emit(True)


def add_tyres(planner, compound: str, count: int):
    planner.tyre_set_panel._tyre_selector.setCurrentText(compound)
    for _ in range(count):
        planner.add_tyre_to_set()


def test_planner_wear_and_change_time(planner):
    add_tyres(planner, "Soft", 4)
    add_tyres(planner, "Medium", 4)
    assert planner.tyre_set.tyre_in_stock()[-1] == "Medium #4"
    soft = ("Soft #1", "Soft #2", "Soft #3", "Soft #4")
    install(planner, 0, soft)
    planner.tyre_plan.setCurrentCell(0, 0)
    planner.duplicate_row()  # second stint on same tyres
    planner.tyre_plan.append_row()
    install(planner, 2, ("Medium #1", "Medium #2", "Soft #3", "Soft #4"))  # 2 tyres changed
    table = planner.tyre_plan
    assert table.cellWidget(1, 0).remaining == pytest.approx(0.6)  # soft: 40% per stint
    assert table.cellWidget(2, 2).remaining == pytest.approx(0.2)
    assert table.cellWidget(2, 0).remaining == pytest.approx(1.0)
    assert table.item(1, 4).text() == "N/A"
    assert table.item(2, 4).text() == "+4.5s"
    assert planner.tyre_set.count_used() == 6
    assert "Stints: 3" in planner.tyre_status_bar._stints.text()
    assert "Stock: 8 / 4 (invalid)" in planner.tyre_status_bar._tyre_stock.text()


def test_planner_same_tyre_detection(planner):
    add_tyres(planner, "Soft", 4)
    install(planner, 0, ("Soft #1", "Soft #2", "Soft #3", "Soft #4"))
    table = planner.tyre_plan
    assert table._same_row("Soft #1", 0, 2) == 0  # already on front left
    table.append_row()
    assert table._same_allocation("Soft #2", 1, 0) == 1  # used on front right before
    assert table._same_allocation("Soft #9", 1, 0) == 0


def test_planner_remove_tyre_from_set_clears_table(planner):
    add_tyres(planner, "Hard", 4)
    install(planner, 0, ("Hard #1", "Hard #2", "Hard #3", "Hard #4"))
    planner.tyre_set.item(0).setSelected(True)
    planner.remove_tyre_from_set()
    assert planner.tyre_plan.export_to_list()[0] == ["", "Hard #2", "Hard #3", "Hard #4"]
    planner.remove_all_tyres()
    assert planner.tyre_plan.export_to_list()[0] == ["", "", "", ""]
    assert planner.tyre_set.count() == 0


def test_planner_rows(planner):
    table = planner.tyre_plan
    table.clearSelection()
    planner.delete_row()  # nothing selected: warning only
    assert table.rowCount() == 1
    table.setCurrentCell(0, 0)
    planner.insert_row_above()
    planner.insert_row_below()
    assert table.rowCount() == 3
    table.selectRow(1)
    planner.delete_row()
    assert table.rowCount() == 2


def test_planner_save_load_and_export(planner, tmp_path, monkeypatch):
    from tinypedal.ui import tyre_strategy_planner

    add_tyres(planner, "Soft", 4)
    install(planner, 0, ("Soft #1", "Soft #2", "Soft #3", "Soft #4"))
    target = tmp_path / "Spa 6h.tyres"
    monkeypatch.setattr(tyre_strategy_planner.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    planner.saving()
    assert not planner.is_modified()
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["tyre_plan"] == [["Soft #1", "Soft #2", "Soft #3", "Soft #4"]]
    assert planner.tyre_plan_panel.filename() == "Spa 6h"
    # Export spreadsheet
    exported = tmp_path / "plan.csv"
    monkeypatch.setattr(tyre_strategy_planner.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(exported), ""))
    planner.export_as_csv()
    rows = list(csv.reader(exported.open(encoding="utf-8")))
    assert ["Soft #1", "1"] in rows
    assert rows[-1][:3] == ["1", "Soft #1", "100.00 - 60.00"]
    # Load in new plan
    planner.create_new_file()
    assert planner.tyre_set.count() == 0
    monkeypatch.setattr(tyre_strategy_planner.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(target), ""))
    planner.load_from_file()
    assert planner.tyre_set.count() == 4
    assert planner.tyre_plan.export_to_list() == saved["tyre_plan"]


def test_planner_sort_tyre_list(planner):
    add_tyres(planner, "Medium", 1)
    add_tyres(planner, "Soft", 2)
    install(planner, 0, ("Soft #2", "", "", ""))
    planner.tyre_set.sort_by_compound()
    assert planner.tyre_set.tyre_in_stock() == ("Soft #1", "Soft #2", "Medium #1")
    planner.tyre_set.sort_by_stints()
    assert planner.tyre_set.tyre_in_stock()[0] == "Soft #2"
