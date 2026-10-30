"""Editor tests: tyre compounds, brakes, tracks info & vehicle brands (add, edit, validate, delete, save)

Editors are table editor pages (quick/table_editor.py): rows edited through the backend as the QML page does.
"""

import json
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from neopedal.setting import cfg
from neopedal.ui._common import BaseEditor


@pytest.fixture
def editor_env(ui_env, monkeypatch):
    """Warnings recorded, no module reload after saving

    Exceptions raised in Qt slots (cell changed...) only print a traceback, they fail the test here.
    """
    warnings = []
    slot_errors = []
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


def column_texts(editor, column: int) -> list[str]:
    """Texts of a column, as shown"""
    backend = editor.backend
    return [backend.display(column, row[column]) for row in backend.rows]


def set_cell(editor, row: int, column: int, text: str) -> bool:
    backend = editor.backend
    return backend.setCell(backend.keys[row], column, text)


def select_rows(editor, *rows: int):
    backend = editor.backend
    backend.select(backend.keys[rows[0]], 0, 0)
    for row in rows[1:]:
        backend.select(backend.keys[row], 0, 1)


# --- Tyre compounds
@pytest.fixture
def compound_editor(editor_env, monkeypatch):
    from neopedal.ui.tyre_compound_editor import TyreCompoundEditor

    monkeypatch.setattr(cfg.user, "compounds", {
        "Soft": {"symbol": "S", "color": "#FF0000", "heatmap": "HEATMAP_DEFAULT_TYRE"},
    }, raising=False)
    editor = TyreCompoundEditor(None)
    yield editor
    close_editor(editor)


def test_compound_add_from_session_then_new_name(compound_editor, editor_env):
    from neopedal.api_control import api

    api.read.vehicle.total_vehicles = lambda: 2
    api.read.tyre.compound_class = lambda index=None: ("Medium", "Medium", "Wet", "Wet") if index else ("Soft",) * 4
    compound_editor.backend.addRow()
    names = column_texts(compound_editor, 0)
    assert names[0] == "Soft" and sorted(names[1:]) == ["Medium", "Wet"]  # missing session compounds only
    compound_editor.backend.addRow()  # nothing new in session: generic name
    compound_editor.backend.addRow()
    names = column_texts(compound_editor, 0)
    assert names[-2:] == ["New Compound Name 1", "New Compound Name 2"]


def test_compound_symbol_one_letter_and_saved(compound_editor, editor_env):
    assert set_cell(compound_editor, 0, 1, "Hard")
    assert column_texts(compound_editor, 1) == ["H"]
    assert set_cell(compound_editor, 0, 1, "")
    assert column_texts(compound_editor, 1) == ["?"]
    assert compound_editor.is_modified()
    compound_editor.applying()
    assert cfg.user.compounds["Soft"]["symbol"] == "?"
    assert cfg.user.compounds["Soft"]["color"] == "#FF0000"
    assert "compounds" in editor_env.saved
    assert not compound_editor.is_modified()


def test_compound_delete_sort_reset(compound_editor, editor_env):
    backend = compound_editor.backend
    assert backend.selectedCount == 0
    backend.deleteSelected()  # nothing selected: nothing done, no warning (Delete disabled in page)
    assert not editor_env.warnings and len(backend.rows) == 1
    backend.append_rows([backend.new_row("Alpha")])
    backend.sortBy(0)
    assert column_texts(compound_editor, 0) == ["Alpha", "Soft"]
    select_rows(compound_editor, 0)
    backend.deleteSelected()
    assert column_texts(compound_editor, 0) == ["Soft"]
    backend.resetToDefault()
    assert len(backend.rows) == len(cfg.default.compounds)


# --- Brakes
@pytest.fixture
def brake_editor(editor_env, monkeypatch):
    from neopedal.ui.brake_editor import BrakeEditor

    monkeypatch.setattr(cfg.user, "brakes", {
        "GT3 - Front Brake": {"failure_thickness": 10.0, "heatmap": "HEATMAP_DEFAULT_BRAKE"},
    }, raising=False)
    editor = BrakeEditor(None)
    yield editor
    close_editor(editor)


def test_brake_thickness_validated_and_saved(brake_editor):
    assert not set_cell(brake_editor, 0, 1, "not a number")
    assert column_texts(brake_editor, 1) == ["10"]  # invalid input refused
    assert set_cell(brake_editor, 0, 1, "12,5")  # decimal comma accepted
    brake_editor.applying()
    assert cfg.user.brakes["GT3 - Front Brake"]["failure_thickness"] == 12.5


def test_brake_add_from_session(brake_editor):
    from neopedal.api_control import api

    api.read.vehicle.total_vehicles = lambda: 1
    api.read.vehicle.class_name = lambda index=None: "LMP2"
    api.read.vehicle.vehicle_name = lambda index=None: "Oreca"
    brake_editor.backend.addRow()
    names = column_texts(brake_editor, 0)
    assert len(names) == 3 and all("LMP2" in name or "Oreca" in name for name in names[1:])
    brake_editor.backend.addRow()  # front & rear already listed
    assert column_texts(brake_editor, 0)[-1] == "New Brake Name 1"


def test_brake_delete_and_reset(brake_editor, editor_env):
    backend = brake_editor.backend
    select_rows(brake_editor, 0)
    backend.deleteSelected()
    assert len(backend.rows) == 0
    backend.resetToDefault()
    backend.sortBy(0)
    assert len(backend.rows) == len(cfg.default.brakes)


# --- Track info
@pytest.fixture
def track_editor(editor_env, monkeypatch):
    from neopedal.ui.track_info_editor import TrackInfoEditor

    monkeypatch.setattr(cfg.user, "tracks", {
        "Spa": {"pit_entry": 6800.0, "pit_exit": 300.0, "pit_speed": 16.67, "speed_trap": 2000.0,
                "sunrise": "06:30", "sunset": "21:15", "preset": "spa_race"},
    }, raising=False)
    monkeypatch.setitem(cfg.user.setting["units"], "distance_unit", "Meter")
    monkeypatch.setitem(cfg.user.setting["units"], "speed_unit", "m/s")
    editor = TrackInfoEditor(None)
    yield editor
    close_editor(editor)


def test_track_info_saved_unchanged(track_editor):
    track_editor.applying()
    assert cfg.user.tracks["Spa"] == {
        "pit_entry": 6800.0, "pit_exit": 300.0, "pit_speed": 16.67, "speed_trap": 2000.0, "orientation": 0.0,
        "sunrise": "06:30", "sunset": "21:15", "preset": "spa_race"}


def test_track_info_clock_and_number_validation(track_editor):
    track_editor.backend._presets = ("other", "spa_race")  # existing presets
    assert set_cell(track_editor, 0, 6, "7:5")
    assert column_texts(track_editor, 6) == ["07:05"]
    assert set_cell(track_editor, 0, 7, "25:70")  # clamped to end of day
    assert column_texts(track_editor, 7) == ["24:00"]
    assert not set_cell(track_editor, 0, 7, "dusk")  # invalid: previous value kept
    assert column_texts(track_editor, 7) == ["24:00"]
    assert not set_cell(track_editor, 0, 1, "x")
    assert column_texts(track_editor, 1) == ["6800"]
    assert set_cell(track_editor, 0, 5, "-90")  # track map orientation
    assert not set_cell(track_editor, 0, 8, "missing")  # primary preset: existing presets only
    assert set_cell(track_editor, 0, 8, "  other  ")
    track_editor.applying()
    assert cfg.user.tracks["Spa"]["sunrise"] == "07:05"
    assert cfg.user.tracks["Spa"]["orientation"] == -90.0
    assert cfg.user.tracks["Spa"]["preset"] == "other"


def test_track_info_add_current_track(track_editor):
    from neopedal.api_control import api

    api.read.session.track_name = lambda: "Monza"
    track_editor.backend.addRow()
    track_editor.backend.addRow()  # Monza listed: generic name
    assert column_texts(track_editor, 0) == ["Spa", "Monza", "New Track Name 1"]
    track_editor.applying()
    assert cfg.user.tracks["Monza"]["sunrise"] == "06:00"  # defaults


def test_track_info_speed_trap_from_telemetry(track_editor, editor_env):
    from neopedal.api_control import api

    backend = track_editor.backend
    asked = []
    track_editor.ask = lambda title, text, action_text, on_result: asked.append((title, text, on_result))
    key = backend.keys[0]
    api.read.session.track_name = lambda: "Monza"
    backend.cellAction(key, 4)  # other track
    assert len(editor_env.warnings) == 1
    api.read.session.track_name = lambda: "Spa"
    api.read.vehicle.in_pits = lambda: True
    backend.cellAction(key, 4)  # in pits
    assert len(editor_env.warnings) == 2 and not asked
    api.read.vehicle.in_pits = lambda: False
    api.read.lap.distance = lambda: 1234.56789
    backend.cellAction(key, 4)
    assert asked and asked[0][0] == "Set from Telemetry" and "1234.5679" in asked[0][1]
    assert column_texts(track_editor, 4) == ["2000"]  # set once confirmed
    asked[0][2](True)
    assert column_texts(track_editor, 4) == ["1234.5679"]
    backend.cellAction(key, 3)  # pit speed: no cell action
    assert len(asked) == 1


def test_track_info_delete_sort_reset(track_editor):
    backend = track_editor.backend
    backend.append_rows([backend.new_row("Aragon")])
    backend.sortBy(0)
    assert column_texts(track_editor, 0) == ["Aragon", "Spa"]
    select_rows(track_editor, 1)
    backend.deleteSelected()
    assert column_texts(track_editor, 0) == ["Aragon"]
    backend.resetToDefault()
    assert len(backend.rows) == len(cfg.default.tracks)


# --- Heatmap
@pytest.fixture
def heatmap_editor(editor_env):
    from neopedal.ui.heatmap_editor import HeatmapEditor

    editor = HeatmapEditor(None)
    yield editor
    close_editor(editor)


def test_heatmap_add_sort_and_save(heatmap_editor):
    backend = heatmap_editor.backend
    rows = len(backend.rows)
    backend.addRow()
    assert len(backend.rows) == rows + 1
    assert set_cell(heatmap_editor, 0, 0, "999")  # moved to the end when sorted
    backend.sortBy(0)
    assert column_texts(heatmap_editor, 0)[rows] == "999"
    heatmap_editor.applying()
    assert "999.0" in cfg.user.heatmap[backend.selected_key]


def test_heatmap_reset_is_undoable(heatmap_editor):
    backend = heatmap_editor.backend
    default_rows = len(backend.rows)
    select_rows(heatmap_editor, 0)
    backend.deleteSelected()
    assert len(backend.rows) == default_rows - 1
    heatmap_editor.set_unmodified()
    backend.resetToDefault()
    assert len(backend.rows) == default_rows and heatmap_editor.is_modified()
    heatmap_editor.undo()
    assert len(backend.rows) == default_rows - 1


# --- Vehicle brands
@pytest.fixture
def brand_editor(editor_env, monkeypatch):
    from neopedal.ui.vehicle_brand_editor import VehicleBrandEditor

    monkeypatch.setattr(cfg.user, "brands", {"Ferrari 296 #51": "Ferrari"}, raising=False)
    editor = VehicleBrandEditor(None)
    yield editor
    close_editor(editor)


def test_brand_import_lmu_file_keeps_user_names(brand_editor, editor_env, tmp_path, monkeypatch):
    data = [{"desc": "Ferrari 296 #51", "manufacturer": "Scuderia"}, {"desc": "Porsche 963 #6", "manufacturer": "Porsche"}]
    filename = tmp_path / "vehicles.json"
    filename.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(brand_editor, "open_file", lambda file_filter: str(filename))
    brand_editor.backend.importFrom(3)  # JSON file
    brand_editor.applying()
    assert cfg.user.brands == {"Ferrari 296 #51": "Ferrari", "Porsche 963 #6": "Porsche"}  # user entry wins


def test_brand_import_rf2_format(brand_editor):
    brand_editor.backend.import_vehicles([{"name": "Oreca 07 #22 1.0", "manufacturer": "Oreca", "vehFile": "x"}])
    assert len(brand_editor.backend.rows) == 2
    assert column_texts(brand_editor, 0)[0] == "Oreca 07 #22"  # version cut
    assert brand_editor.is_modified()  # imported data asks to be saved on close


def test_reset_is_one_undo_step(brand_editor):
    backend = brand_editor.backend
    backend.resetToDefault()
    assert len(backend.rows) == len(cfg.default.brands)
    brand_editor.undo()
    assert column_texts(brand_editor, 0) == ["Ferrari 296 #51"]
    brand_editor.redo()
    assert len(backend.rows) == len(cfg.default.brands)


def test_brand_import_invalid_file(brand_editor, editor_env, tmp_path, monkeypatch):
    filename = tmp_path / "bad.json"
    filename.write_text('[{"other": 1}]', encoding="utf-8")
    monkeypatch.setattr(brand_editor, "open_file", lambda file_filter: str(filename))
    brand_editor.backend.importFrom(3)
    assert editor_env.warnings and len(brand_editor.backend.rows) == 1


def test_brand_import_from_restapi_unreachable(brand_editor, editor_env, monkeypatch):
    from neopedal.ui import vehicle_brand_editor

    def refused(*args):
        raise OSError("refused")

    monkeypatch.setattr(vehicle_brand_editor, "resolve_hostname", refused)
    brand_editor.backend.importFrom(0)
    # Request runs in background: warning shown once its answer comes back
    deadline = time.monotonic() + 5
    while not editor_env.warnings and time.monotonic() < deadline:
        QCoreApplication.processEvents()
    assert editor_env.warnings


def test_brand_add_delete_sort_reset(brand_editor):
    from neopedal.api_control import api

    backend = brand_editor.backend
    api.read.vehicle.total_vehicles = lambda: 1
    api.read.vehicle.vehicle_name = lambda index=None: "Alpine A424 #35"
    api.read.vehicle.vehicle_model = lambda index=None: "Alpine A424"
    backend.addRow()
    backend.addRow()
    assert column_texts(brand_editor, 0) == ["Ferrari 296 #51", "Alpine A424 #35", "New Vehicle Name 1"]
    backend.sortBy(1)  # by brand name
    assert column_texts(brand_editor, 1)[0] <= column_texts(brand_editor, 1)[-1]
    select_rows(brand_editor, 0)
    backend.deleteSelected()
    assert len(backend.rows) == 2
    backend.resetToDefault()
    assert len(backend.rows) == len(cfg.default.brands)


# --- Bulk actions: one undo step, rows read once (not after every cell)
def count_reads(editor, monkeypatch) -> list:
    """Snapshots read for undo history"""
    reads: list = []
    original = editor._undo_capture

    def reading():
        reads.append(1)
        return original()

    monkeypatch.setattr(editor, "_undo_capture", reading)
    return reads


def test_brand_add_from_session_is_one_undo_step(brand_editor, monkeypatch):
    from neopedal.api_control import api

    backend = brand_editor.backend
    api.read.vehicle.total_vehicles = lambda: 40
    api.read.vehicle.vehicle_name = lambda index=None: f"Car #{index}"
    api.read.vehicle.vehicle_model = lambda index=None: "Model"
    reads = count_reads(brand_editor, monkeypatch)
    backend.addRow()
    assert len(backend.rows) == 41 and brand_editor.is_modified()
    assert len(reads) <= 2
    brand_editor.undo()
    assert column_texts(brand_editor, 0) == ["Ferrari 296 #51"]
    brand_editor.redo()
    assert len(backend.rows) == 41
    backend.addRow()  # all listed already: new name entry
    assert column_texts(brand_editor, 0)[-1] == "New Vehicle Name 1"


def test_batch_replace_is_one_undo_step(brand_editor, monkeypatch):
    backend = brand_editor.backend
    backend.import_vehicles([{"desc": f"Car #{index}", "manufacturer": "Acme"} for index in range(30)])
    before = column_texts(brand_editor, 1)
    reads = count_reads(brand_editor, monkeypatch)
    assert backend.replace(1, "Acme", "Globex", False, False) == 30
    assert column_texts(brand_editor, 1).count("Globex") == 30
    assert len(reads) <= 2
    brand_editor.undo()
    assert column_texts(brand_editor, 1) == before


def test_class_and_compound_add_from_session_one_undo_step(compound_editor, monkeypatch):
    from neopedal.api_control import api

    backend = compound_editor.backend
    api.read.vehicle.total_vehicles = lambda: 3
    api.read.tyre.compound_class = lambda index=None: (f"C{index}", f"C{index}", "Wet", "Wet")
    reads = count_reads(compound_editor, monkeypatch)
    backend.addRow()
    assert column_texts(compound_editor, 0)[0] == "Soft" and len(backend.rows) == 5  # Soft + C0..C2 + Wet
    assert backend.currentIndex == 4  # last added selected
    assert len(reads) <= 2
    compound_editor.undo()
    assert column_texts(compound_editor, 0) == ["Soft"]


def test_brake_add_from_session_one_undo_step(brake_editor, monkeypatch):
    from neopedal.api_control import api

    backend = brake_editor.backend
    api.read.vehicle.total_vehicles = lambda: 2
    api.read.vehicle.class_name = lambda index=None: "LMP2"
    api.read.vehicle.vehicle_name = lambda index=None: f"Oreca {index}"
    rows = len(backend.rows)
    backend.addRow()
    assert len(backend.rows) > rows
    assert backend.currentIndex == len(backend.rows) - 1
    brake_editor.undo()
    assert len(backend.rows) == rows
