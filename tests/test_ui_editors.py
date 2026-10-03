"""Editor tests: tyre compounds, brakes, tracks info & vehicle brands (add, edit, validate, delete, save)"""

import json
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.setting import cfg
from tinypedal.ui._common import BaseEditor


@pytest.fixture
def editor_env(ui_env, monkeypatch):
    """Editors confirm every question, warnings recorded, no module reload after saving

    Exceptions raised in Qt slots (cell changed...) only print a traceback, they fail the test here.
    """
    warnings = []
    slot_errors = []
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(BaseEditor, "reloading", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: slot_errors.append(exc_info[1]))
    yield SimpleEnv(saved=ui_env, warnings=warnings)
    assert not slot_errors


class SimpleEnv:
    def __init__(self, saved, warnings):
        self.saved = saved
        self.warnings = warnings


def close_editor(editor):
    editor.set_unmodified()
    editor.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def column_texts(table, column: int) -> list[str]:
    return [table.item(row, column).text() for row in range(table.rowCount())]


# --- Tyre compounds
@pytest.fixture
def compound_editor(editor_env, monkeypatch):
    from tinypedal.ui.tyre_compound_editor import TyreCompoundEditor

    monkeypatch.setattr(cfg.user, "compounds", {
        "Soft": {"symbol": "S", "color": "#FF0000", "heatmap": "HEATMAP_DEFAULT_TYRE"},
    }, raising=False)
    editor = TyreCompoundEditor(None)
    yield editor
    close_editor(editor)


def test_compound_add_from_session_then_new_name(compound_editor, editor_env):
    from tinypedal.api_control import api

    api.read.vehicle.total_vehicles = lambda: 2
    api.read.tyre.compound_class = lambda index=None: ("Medium", "Medium", "Wet", "Wet") if index else ("Soft",) * 4
    compound_editor.add_compound()
    names = column_texts(compound_editor.table_compounds, 0)
    assert names[0] == "Soft" and sorted(names[1:]) == ["Medium", "Wet"]  # missing session compounds only
    compound_editor.add_compound()  # nothing new in session: generic name
    compound_editor.add_compound()
    names = column_texts(compound_editor.table_compounds, 0)
    assert names[-2:] == ["New Compound Name 1", "New Compound Name 2"]


def test_compound_symbol_one_letter_and_saved(compound_editor, editor_env):
    table = compound_editor.table_compounds
    table.item(0, 1).setText("Hard")
    assert table.item(0, 1).text() == "H"
    table.item(0, 1).setText("")
    assert table.item(0, 1).text() == "?"
    assert compound_editor.is_modified()
    compound_editor.applying()
    assert cfg.user.compounds["Soft"]["symbol"] == "?"
    assert cfg.user.compounds["Soft"]["color"] == "#FF0000"
    assert "compounds" in editor_env.saved
    assert not compound_editor.is_modified()


def test_compound_delete_sort_reset(compound_editor, editor_env):
    table = compound_editor.table_compounds
    compound_editor.delete_compound()  # nothing selected
    assert editor_env.warnings
    compound_editor.add_compound_entry(1, "Alpha")
    compound_editor.sort_compound()
    assert column_texts(table, 0) == ["Alpha", "Soft"]
    table.selectRow(0)
    compound_editor.delete_compound()
    assert column_texts(table, 0) == ["Soft"]
    compound_editor.reset_setting()
    assert table.rowCount() == len(cfg.default.compounds)


# --- Brakes
@pytest.fixture
def brake_editor(editor_env, monkeypatch):
    from tinypedal.ui.brake_editor import BrakeEditor

    monkeypatch.setattr(cfg.user, "brakes", {
        "GT3 - Front Brake": {"failure_thickness": 10.0, "heatmap": "HEATMAP_DEFAULT_BRAKE"},
    }, raising=False)
    editor = BrakeEditor(None)
    yield editor
    close_editor(editor)


def test_brake_thickness_validated_and_saved(brake_editor):
    table = brake_editor.table_brakes
    table.item(0, 1).setText("not a number")
    assert table.item(0, 1).text() == "10.0"  # invalid input reverted
    table.item(0, 1).setText("12.5")
    brake_editor.applying()
    assert cfg.user.brakes["GT3 - Front Brake"]["failure_thickness"] == 12.5


def test_brake_add_from_session(brake_editor):
    from tinypedal.api_control import api

    api.read.vehicle.total_vehicles = lambda: 1
    api.read.vehicle.class_name = lambda index=None: "LMP2"
    api.read.vehicle.vehicle_name = lambda index=None: "Oreca"
    brake_editor.add_brake()
    names = column_texts(brake_editor.table_brakes, 0)
    assert len(names) == 3 and all("LMP2" in name or "Oreca" in name for name in names[1:])
    brake_editor.add_brake()  # front & rear already listed
    assert column_texts(brake_editor.table_brakes, 0)[-1] == "New Brake Name 1"


def test_brake_delete_and_reset(brake_editor, editor_env):
    brake_editor.table_brakes.selectRow(0)
    brake_editor.delete_brake()
    assert brake_editor.table_brakes.rowCount() == 0
    brake_editor.reset_setting()
    brake_editor.sort_brake()
    assert brake_editor.table_brakes.rowCount() == len(cfg.default.brakes)


# --- Track info
@pytest.fixture
def track_editor(editor_env, monkeypatch):
    from tinypedal.ui.track_info_editor import TrackInfoEditor

    monkeypatch.setattr(cfg.user, "tracks", {
        "Spa": {"pit_entry": 6800.0, "pit_exit": 300.0, "pit_speed": 16.67, "speed_trap": 2000.0,
                "sunrise": "06:30", "sunset": "21:15", "preset": "spa_race"},
    }, raising=False)
    editor = TrackInfoEditor(None)
    yield editor
    close_editor(editor)


def test_track_info_saved_unchanged(track_editor):
    track_editor.applying()
    assert cfg.user.tracks["Spa"] == {
        "pit_entry": 6800.0, "pit_exit": 300.0, "pit_speed": 16.67, "speed_trap": 2000.0,
        "sunrise": "06:30", "sunset": "21:15", "preset": "spa_race"}


def test_track_info_clock_and_number_validation(track_editor):
    table = track_editor.table_tracks
    table.item(0, 5).setText("7:5")
    assert table.item(0, 5).text() == "07:05"
    table.item(0, 6).setText("25:70")  # clamped to end of day
    assert table.item(0, 6).text() == "24:00"
    table.item(0, 6).setText("dusk")  # invalid: previous value kept
    assert table.item(0, 6).text() == "24:00"
    table.item(0, 1).setText("x")
    assert table.item(0, 1).text() == "6800.0"
    table.item(0, 7).setText("  other  ")
    track_editor.applying()
    assert cfg.user.tracks["Spa"]["sunrise"] == "07:05"
    assert cfg.user.tracks["Spa"]["preset"] == "other"


def test_track_info_add_current_track(track_editor):
    from tinypedal.api_control import api

    api.read.session.track_name = lambda: "Monza"
    track_editor.add_track()
    track_editor.add_track()  # Monza listed: generic name
    assert column_texts(track_editor.table_tracks, 0) == ["Spa", "Monza", "New Track Name 1"]
    track_editor.applying()
    assert cfg.user.tracks["Monza"]["sunrise"] == "06:00"  # defaults


def test_track_info_speed_trap_from_telemetry(track_editor, editor_env):
    from tinypedal.api_control import api

    table = track_editor.table_tracks
    track_editor.set_position_from_tele()  # nothing selected
    assert len(editor_env.warnings) == 1
    table.setCurrentCell(0, 4)
    api.read.session.track_name = lambda: "Monza"
    track_editor.set_position_from_tele()  # other track
    assert len(editor_env.warnings) == 2
    api.read.session.track_name = lambda: "Spa"
    api.read.vehicle.in_pits = lambda: True
    track_editor.set_position_from_tele()  # in pits
    assert len(editor_env.warnings) == 3
    api.read.vehicle.in_pits = lambda: False
    api.read.lap.distance = lambda: 1234.56789
    track_editor.set_position_from_tele()
    assert table.item(0, 4).text() == "1234.5679"


def test_track_info_delete_sort_reset(track_editor):
    track_editor.add_track_entry(1, "Aragon", {})
    track_editor.sort_track()
    assert column_texts(track_editor.table_tracks, 0) == ["Aragon", "Spa"]
    track_editor.table_tracks.selectRow(1)
    track_editor.delete_track()
    assert column_texts(track_editor.table_tracks, 0) == ["Aragon"]
    track_editor.reset_setting()
    assert track_editor.table_tracks.rowCount() == len(cfg.default.tracks)


# --- Heatmap
@pytest.fixture
def heatmap_editor(editor_env):
    from tinypedal.ui.heatmap_editor import HeatmapEditor

    editor = HeatmapEditor(None)
    yield editor
    close_editor(editor)


def test_heatmap_add_sort_and_save(heatmap_editor):
    table = heatmap_editor.table_heatmap
    rows = table.rowCount()
    heatmap_editor.add_temperature()
    assert table.rowCount() == rows + 1
    table.item(0, 0).setText("999")  # moved to the end when sorted
    heatmap_editor.sort_temperature()
    assert table.item(rows, 0).text() == "999"
    heatmap_editor.applying()
    assert "999.0" in cfg.user.heatmap[heatmap_editor.selected_heatmap_key]


def test_heatmap_reset_is_undoable(heatmap_editor):
    table = heatmap_editor.table_heatmap
    default_rows = table.rowCount()
    table.selectRow(0)
    heatmap_editor.delete_temperature(0)
    assert table.rowCount() == default_rows - 1
    heatmap_editor.set_unmodified()
    heatmap_editor.reset_heatmap()
    assert table.rowCount() == default_rows and heatmap_editor.is_modified()
    heatmap_editor.undo()
    assert table.rowCount() == default_rows - 1


# --- Vehicle brands
@pytest.fixture
def brand_editor(editor_env, monkeypatch):
    from tinypedal.ui.vehicle_brand_editor import VehicleBrandEditor

    monkeypatch.setattr(cfg.user, "brands", {"Ferrari 296 #51": "Ferrari"}, raising=False)
    editor = VehicleBrandEditor(None)
    yield editor
    close_editor(editor)


def test_brand_import_lmu_file_keeps_user_names(brand_editor, editor_env, tmp_path, monkeypatch):
    from tinypedal.ui import vehicle_brand_editor

    data = [{"desc": "Ferrari 296 #51", "manufacturer": "Scuderia"}, {"desc": "Porsche 963 #6", "manufacturer": "Porsche"}]
    filename = tmp_path / "vehicles.json"
    filename.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(vehicle_brand_editor.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(filename), ""))
    brand_editor.import_from_file()
    brand_editor.applying()
    assert cfg.user.brands == {"Ferrari 296 #51": "Ferrari", "Porsche 963 #6": "Porsche"}  # user entry wins


def test_brand_import_rf2_format(brand_editor):
    brand_editor.parse_brand_data([{"name": "Oreca 07 #22", "manufacturer": "Oreca", "vehFile": "x"}])
    assert brand_editor.table_brands.rowCount() == 2
    assert brand_editor.is_modified()  # imported data asks to be saved on close


def test_reset_is_one_undo_step(brand_editor):
    """Reset rebuilt table from old table data (reset did nothing), see BaseEditor.replace_table_data"""
    brand_editor.reset_setting()
    assert brand_editor.table_brands.rowCount() == len(cfg.default.brands)
    brand_editor.undo()
    assert column_texts(brand_editor.table_brands, 0) == ["Ferrari 296 #51"]
    brand_editor.redo()
    assert brand_editor.table_brands.rowCount() == len(cfg.default.brands)


def test_brand_import_invalid_file(brand_editor, editor_env, tmp_path, monkeypatch):
    from tinypedal.ui import vehicle_brand_editor

    filename = tmp_path / "bad.json"
    filename.write_text('[{"other": 1}]', encoding="utf-8")
    monkeypatch.setattr(vehicle_brand_editor.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(filename), ""))
    brand_editor.import_from_file()
    assert editor_env.warnings and brand_editor.table_brands.rowCount() == 1


def test_brand_import_from_restapi_unreachable(brand_editor, editor_env, monkeypatch):
    from tinypedal.ui import vehicle_brand_editor

    def refused(*args):
        raise OSError("refused")

    monkeypatch.setattr(vehicle_brand_editor, "resolve_hostname", refused)
    brand_editor.import_from_lmu()
    assert editor_env.warnings


def test_brand_add_delete_sort_reset(brand_editor):
    from tinypedal.api_control import api

    api.read.vehicle.total_vehicles = lambda: 1
    api.read.vehicle.vehicle_name = lambda index=None: "Alpine A424 #35"
    api.read.vehicle.vehicle_model = lambda index=None: "Alpine A424"
    brand_editor.add_brand()
    brand_editor.add_brand()
    table = brand_editor.table_brands
    assert column_texts(table, 0) == ["Ferrari 296 #51", "Alpine A424 #35", "New Vehicle Name 1"]
    brand_editor.sort_brand()  # by brand name
    assert column_texts(table, 1)[0] <= column_texts(table, 1)[-1]
    table.selectRow(0)
    brand_editor.delete_brand()
    assert table.rowCount() == 2
    brand_editor.reset_setting()
    assert table.rowCount() == len(cfg.default.brands)
