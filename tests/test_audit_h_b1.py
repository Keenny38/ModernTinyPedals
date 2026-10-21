"""Audit h, lot b1: dead code removed & duplicates shared, same behaviour: date texts of pages (one helper per
format), race calculator inputs of config template, option editor texts, table editors (table & button row)"""

import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QMessageBox, QPushButton

from neopedal.setting import cfg
from neopedal.ui._common import BaseEditor
from neopedal.ui.quick import stats_common, stats_overview
from tests.test_race_calculator import host, page  # noqa: F401 (fixtures)

STAMP = time.mktime((2025, 10, 9, 18, 5, 7, 0, 0, -1))  # local time


# --- Date texts
def test_fixed_date_formats_same_text_as_before():
    from neopedal.ui.quick import formatting as fm

    local = time.localtime(STAMP)
    assert fm.iso_minutes(STAMP) == time.strftime("%Y-%m-%d %H:%M", local) == "2025-10-09 18:05"
    assert fm.iso_day(STAMP) == "2025-10-09"
    assert fm.file_stamp(STAMP) == "2025-10-09 18-05-07"
    assert fm.day_month(STAMP) == "09/10"
    assert fm.day_month_minutes(STAMP) == "09/10 18:05"
    assert fm.day_month_year_minutes(STAMP) == "09/10/2025 18:05"
    assert fm.clock_minutes(STAMP) == "18:05"
    assert fm.clock_seconds(STAMP) == "18:05:07"
    # No date: "" where pages showed nothing
    assert fm.day_month(0) == fm.day_month_minutes(0) == fm.day_month_minutes(-1.0) == ""
    # Now when no timestamp given
    assert len(fm.clock_seconds()) == 8 and len(fm.file_stamp()) == 19 and len(fm.iso_day()) == 10


def test_language_date_formats_kept(monkeypatch):
    from neopedal.ui.quick import formatting as fm

    monkeypatch.setattr(fm, "current_language", lambda: "en")
    assert fm.format_date(0) == "-"
    assert fm.date_text(0) == ""
    assert fm.day_text(0, QDate.currentDate()) == "Unknown Date"
    noon = time.mktime((*time.localtime()[:3], 12, 0, 0, 0, 0, -1))
    assert fm.day_text(noon, QDate.currentDate()) == "Today"
    assert fm.date_text(STAMP).endswith(" 18:05") and len(fm.date_text(STAMP)) > len(" 18:05")
    assert fm.format_date(STAMP) not in ("", "-")


def test_pages_use_shared_date_helpers():
    """Former module functions still reachable where tests & pages import them"""
    from neopedal.ui.quick import formatting, replays_backend, results_backend

    assert stats_common.format_date is formatting.format_date
    assert stats_overview.date_locale is formatting.date_locale
    assert replays_backend.day_text is formatting.day_text
    assert replays_backend.date_text is formatting.date_text
    assert results_backend.clock_minutes is formatting.clock_minutes


def test_lap_labels_date_unchanged(monkeypatch):
    """Lap viewer session title & lap label: day/month (& time), nothing without a lap date"""
    from neopedal.ui.quick import formatting

    assert formatting.day_month_minutes(STAMP) == time.strftime("%d/%m %H:%M", time.localtime(STAMP))
    assert formatting.day_month(STAMP) == time.strftime("%d/%m", time.localtime(STAMP))


# --- Race calculator inputs
def test_saved_inputs_from_config_template():
    from neopedal.template.setting_global import FUEL_CALCULATOR_INPUTS, GLOBAL_DEFAULT
    from neopedal.ui.quick.race_model import SAVED_INPUTS

    config = GLOBAL_DEFAULT["fuel_calculator"]
    keys = list(config)
    start = keys.index("input_lap_time")
    # Inputs kept at their former place in config (key order of saved config file)
    assert keys[start - 1] == "show_column_tank_capacity"
    assert keys[start:start + len(FUEL_CALCULATOR_INPUTS)] == list(FUEL_CALCULATOR_INPUTS)
    assert keys[start + len(FUEL_CALCULATOR_INPUTS)] == "input_measured_compound"
    assert all(config[key] == value for key, value in FUEL_CALCULATOR_INPUTS.items())
    # Saved inputs: every one in config, tyre life ones last (same order as before), same defaults & types
    assert list(SAVED_INPUTS) == list(FUEL_CALCULATOR_INPUTS)
    assert list(SAVED_INPUTS)[-3:] == ["enable_leader_finish", "input_tyre_set_laps", "enable_tyre_life_stints"]
    assert SAVED_INPUTS["input_tyre_set_laps"] == 0 and SAVED_INPUTS["enable_tyre_life_stints"] is False
    assert SAVED_INPUTS["input_race_start_minutes"] == -1 and SAVED_INPUTS["enable_rain_tyres"] is True
    assert type(SAVED_INPUTS["input_drivers"]) is int and type(SAVED_INPUTS["input_lap_time"]) is float


# --- Option editors
def test_option_value_texts_shared():
    from neopedal.ui.quick import option_kinds, overlay_options_backend, settings_backend
    from neopedal.ui.quick.option_kinds import KIND_CHOICE, KIND_FLOAT, KIND_TEXT, OptionKind

    for module in (overlay_options_backend, settings_backend):
        assert module.choice_values is option_kinds.choice_values
        assert module.display_value is option_kinds.display_value
    assert option_kinds.display_value(OptionKind(KIND_FLOAT), 2.0) == "2"
    assert option_kinds.display_value(OptionKind(KIND_FLOAT), 0.05) == "0.05"
    assert option_kinds.display_value(OptionKind(KIND_TEXT), 2.0) == "2.0"
    assert option_kinds.choice_values(OptionKind(KIND_CHOICE, ("A", "B"))) == ("A", "B")


# --- Table editors
@pytest.fixture
def editor_env(ui_env, monkeypatch):
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(BaseEditor, "reloading", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    slot_errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: slot_errors.append(exc_info[1]))
    yield ui_env
    assert not slot_errors


def button_texts(editor) -> list[str]:
    layout = editor.layout()
    row = next(layout.itemAt(index).layout() for index in reversed(range(layout.count()))
               if isinstance(layout.itemAt(index).layout(), QHBoxLayout))
    return [row.itemAt(index).widget().text() for index in range(row.count())
            if isinstance(row.itemAt(index).widget(), QPushButton)]


def fixed_widths(table) -> dict[int, int]:
    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert table.verticalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
    return {column: table.columnWidth(column) for column in range(table.columnCount())
            if header.sectionResizeMode(column) == QHeaderView.ResizeMode.Fixed}


TAIL = ["Reset", "Undo", "Redo", "Apply", "Save", "Close"]
EDITORS = (
    ("brake_editor", "BrakeEditor", "table_brakes", ["Add", "Sort", "Delete"], {1: 7, 2: 12}),
    ("track_info_editor", "TrackInfoEditor", "table_tracks", ["Add", "Sort", "Delete"], None),
    ("vehicle_class_editor", "VehicleClassEditor", "table_classes", ["Add", "Sort", "Delete"], {2: 7}),
    ("tyre_compound_editor", "TyreCompoundEditor", "table_compounds", ["Add", "Sort", "Delete", "Replace"],
     {1: 5, 2: 7, 3: 12}),
    ("vehicle_brand_editor", "VehicleBrandEditor", "table_brands",
     ["Import from", "Add", "Sort", "Delete", "Replace"], {}),
)


@pytest.mark.parametrize("module_name, class_name, table_name, leading, widths", EDITORS)
def test_table_editor_layout_unchanged(editor_env, module_name, class_name, table_name, leading, widths):
    import importlib

    from neopedal.ui import UIScaler

    module = importlib.import_module(f"neopedal.ui.{module_name}")
    editor = getattr(module, class_name)(None)
    try:
        assert button_texts(editor) == leading + TAIL
        table = getattr(editor, table_name)
        headers = [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())]
        assert headers and all(headers)
        if widths is None:  # tracks: every column but name fixed, orientation & clock columns narrower
            widths = {column: 5 if 5 <= column <= 7 else 8 for column in range(1, table.columnCount())}
        assert fixed_widths(table) == {column: UIScaler.size(width) for column, width in widths.items()}
        assert table.verticalHeader().isHidden() == (class_name == "VehicleClassEditor")
    finally:
        editor.set_unmodified()
        editor.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_editor_buttons_actions(editor_env, monkeypatch):
    """Apply, Reset & Save buttons run the editor's actions, Close closes"""
    from neopedal.ui.brake_editor import BrakeEditor

    calls = []
    monkeypatch.setattr(BrakeEditor, "applying", lambda self: calls.append("apply"))
    monkeypatch.setattr(BrakeEditor, "reset_setting", lambda self: calls.append("reset"))
    monkeypatch.setattr(BrakeEditor, "saving", lambda self: calls.append("save"))
    cfg.user.brakes = {}
    editor = BrakeEditor(None)
    try:
        layout = editor.layout()
        row = layout.itemAt(layout.count() - 1).layout()
        buttons = {row.itemAt(index).widget().text(): row.itemAt(index).widget() for index in range(row.count())
                   if isinstance(row.itemAt(index).widget(), QPushButton)}
        for text in ("Apply", "Reset", "Save"):
            buttons[text].click()
        assert calls == ["apply", "reset", "save"]
    finally:
        editor.set_unmodified()
        editor.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_removed_dead_code_gone():
    """Functions without caller removed (kept out: no import of a removed name comes back)"""
    from neopedal import calculation, formatter, units
    from neopedal.ui import _common, lap_viewer
    from neopedal.widget._modern import draw

    for module, names in (
        (calculation, ("mean_iter", "arc_length", "sec2hourminute", "binary_search_higher", "search_column_key",
                       "wheel_rotation_ratio", "time_type_full_laps_remain", "relative_time_gap")),
        (formatter, ("laptime_string_to_seconds",)),
        (units, ("meter_to_millimeter", "kelvin_to_celsius")),
        (_common, ("add_vertical_separator", "NumericTableItem")),
        (lap_viewer, ("save_visible_channels", "lap_positions", "format_csv_number")),
        (draw, ("center_bar",)),
    ):
        assert not [name for name in names if hasattr(module, name)]
    # Kept helpers still there
    assert calculation.binary_search_lower([1, 2, 3], 2.5, 0, 2) == 1
    assert units.set_unit_temperature("Fahrenheit")(100) == pytest.approx(212)


def test_tyre_life_inputs_kept_after_settings_reload(page):  # noqa: F811
    """Laps per tyre set & stints cut by tyre life saved in config survive validation of the config at next start
    (keys unknown to the config template were dropped)"""
    import copy

    from neopedal.setting_validator import PresetValidator

    backend = page.backend
    backend.setInput("input_tyre_set_laps", 20)
    backend.setInput("enable_tyre_life_stints", True)
    backend.save_inputs()
    saved = copy.deepcopy(dict(cfg.user.config))
    assert saved["fuel_calculator"]["input_tyre_set_laps"] == 20
    validated = PresetValidator.global_preset(saved, copy.deepcopy(dict(cfg.default.config)))
    assert validated["fuel_calculator"]["input_tyre_set_laps"] == 20
    assert validated["fuel_calculator"]["enable_tyre_life_stints"] is True
    # Wrong types still dropped, default restored
    saved["fuel_calculator"]["input_tyre_set_laps"] = "x"
    saved["fuel_calculator"]["enable_tyre_life_stints"] = "true"
    validated = PresetValidator.global_preset(saved, copy.deepcopy(dict(cfg.default.config)))
    assert validated["fuel_calculator"]["input_tyre_set_laps"] == 0
    assert validated["fuel_calculator"]["enable_tyre_life_stints"] is False
