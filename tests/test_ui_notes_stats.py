"""Track notes editor & driver stats viewer tests"""

import json
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from neopedal.setting import cfg
from neopedal.ui._common import BaseEditor
from neopedal.ui.quick import stats_common
from tests.test_driver_stats_viewer import opens_on_game_track, settle


@pytest.fixture
def dialogs(ui_env, monkeypatch):
    """Confirm every question, record warnings, fail on exception raised in Qt slots"""
    warnings = []
    slot_errors = []
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: slot_errors.append(exc_info[1]))
    yield warnings
    assert not slot_errors


def close(editor):
    editor.set_unmodified()
    editor.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- Track notes editor (Qt Quick page, state in quick/track_notes_backend.py)
@pytest.fixture
def notes_editor(dialogs):
    from neopedal.ui import track_notes_editor

    editor = track_notes_editor.TrackNotesEditor(None)
    yield editor.backend
    close(editor)


def notes_column(backend, column: str) -> list:
    return [row[column] for row in backend.rows]


def row_key(backend, index: int) -> int:
    return backend.rows[index]["key"]


def test_notes_edit_sort_tag_and_save(notes_editor, tmp_path, monkeypatch):
    from neopedal.ui.quick import track_notes_backend
    from neopedal.userfile.track_notes import HEADER_PACE_NOTES, load_notes_file

    backend = notes_editor
    backend.create("Pace Notes")
    backend.setValue(row_key(backend, 0), "distance", "500")
    backend.setValue(row_key(backend, 0), "note", "R3")
    backend.addRow()
    assert not backend.setValue(row_key(backend, 1), "distance", "bad")  # invalid distance refused
    assert backend.rows[1]["distance"] == 0
    backend.setValue(row_key(backend, 1), "distance", "120.5")
    backend.setValue(row_key(backend, 1), "note", "L2")
    backend.select(row_key(backend, 1), 0)
    backend.addTag("#pit")
    backend.addTag("#pit")  # added once
    assert backend.rows[1]["tags"] == "#pit"
    target = tmp_path / "Spa.tppn"
    monkeypatch.setattr(track_notes_backend.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(target), "NeoPedal Pace Notes (*.tppn)"))
    assert backend.save()  # sorted by distance before saving
    assert notes_column(backend, "note") == ["L2", "R3"]
    notes, _ = load_notes_file(f"{tmp_path.as_posix()}/", "Spa.tppn", HEADER_PACE_NOTES)
    assert [(note["distance"], note["pace note"], note["tags"]) for note in notes] == [
        (120.5, "L2", "#pit"), (500.0, "R3", "")]
    assert not backend.modified


def test_notes_load_offset_and_undo(notes_editor, tmp_path, monkeypatch):
    from neopedal.ui.quick import track_notes_backend
    from neopedal.userfile.track_notes import HEADER_TRACK_NOTES, create_notes_metadata, save_notes_file

    backend = notes_editor
    notes = [{"distance": 100.0, "track note": "Eau Rouge", "comment": "", "tags": ""},
             {"distance": 900.0, "track note": "Kemmel", "comment": "flat", "tags": ""}]
    save_notes_file(f"{tmp_path.as_posix()}/", "Spa.tptn", HEADER_TRACK_NOTES, notes, create_notes_metadata())
    monkeypatch.setattr(track_notes_backend.QFileDialog, "getOpenFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Spa.tptn"), "NeoPedal Track Notes (*.tptn)"))
    backend.openNotes("Track Notes")
    assert notes_column(backend, "note") == ["Eau Rouge", "Kemmel"]
    backend.selectAll()
    backend.applyOffset(10, False)
    assert notes_column(backend, "distance") == [110.0, 910.0]
    backend.undo()
    assert notes_column(backend, "distance") == [100.0, 900.0]


def test_notes_set_position_from_telemetry(notes_editor):
    from neopedal.api_control import api

    backend = notes_editor
    backend.create("Track Notes")
    told = []
    backend.message.connect(lambda text, error, undo: told.append(error))
    backend.clearSelection()
    assert not backend.setPositionFromTelemetry()  # no note selected
    assert told == [True]
    api.read.lap.distance = lambda: 1234.5678
    backend.select(row_key(backend, 0), 0)
    assert backend.setPositionFromTelemetry()
    assert backend.rows[0]["distance"] == 1234.57  # 2 decimals


def test_notes_insert_delete_and_clear_tag(notes_editor):
    backend = notes_editor
    backend.create("Pace Notes")
    backend.select(row_key(backend, 0), 0)
    backend.insertRow(1)
    backend.insertRow(0)
    assert backend.rowCount == 3
    backend.select(row_key(backend, 2), 0)
    backend.addTag("#pit")
    backend.clearTags()
    assert backend.rows[2]["tags"] == ""
    assert backend.deleteSelected() == 1
    assert backend.rowCount == 2


def test_notes_sort_without_errors(notes_editor):
    backend = notes_editor
    backend.create("Pace Notes")
    for distance in ("300", "100", "200"):
        backend.addRow()
        backend.setValue(row_key(backend, backend.rowCount - 1), "distance", distance)
    backend.sortRows()
    assert notes_column(backend, "distance") == [0, 100, 200, 300]


# --- Driver stats viewer (Qt Quick page, state in quick/stats_backend.py)
@pytest.fixture
def stats_file(ui_env):
    stats = {
        "Spa": {
            "GT3": {"pb": 138.5, "qb": 139.0, "rb": 0, "meters": 125000.0, "seconds": 7200.0, "liters": 80.0,
                    "valid": 50, "invalid": 3, "penalties": 1, "races": 2, "wins": 1, "podiums": 2},
            "LMP2": {"pb": 128.0},
        },
        "Monza": {"GT3": {"pb": 107.2}},
    }
    with open(f"{cfg.path.config}driver.stats", "w", encoding="utf-8") as file:
        json.dump(stats, file)
    return stats


@pytest.fixture
def stats_viewer(dialogs, stats_file, monkeypatch):
    from neopedal.api_control import api
    from neopedal.ui._common import BaseDialog
    from neopedal.ui.driver_stats_viewer import DriverStatsViewer

    monkeypatch.setattr(BaseDialog, "confirm_operation", lambda self, *args, **kwargs: True)
    api.read.session.track_name = lambda: "Spa"
    opens_on_game_track(monkeypatch)
    viewer = DriverStatsViewer(None)
    yield viewer.backend
    viewer.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def load_stats():
    with open(f"{cfg.path.config}driver.stats", encoding="utf-8") as file:
        return json.load(file)


def test_stats_viewer_shows_game_track(stats_viewer):
    assert stats_viewer.selected_stats_key == "Spa"
    assert stats_viewer.row_keys() == ["LMP2", "GT3"]  # sorted by personal best
    assert stats_viewer.cell("GT3", "pb").text == "2:18.500"
    assert stats_viewer.cell("GT3", "rb").text not in ("0", "0.0")  # invalid time shown as no time
    assert stats_viewer.cell("GT3", "seconds").text == "2 h 00 min"  # driving time
    assert stats_viewer.rows.rowCount() == 2


def test_stats_viewer_display_units(stats_viewer, monkeypatch):

    monkeypatch.setitem(cfg.units, "odometer_unit", "Kilometer")
    monkeypatch.setitem(cfg.units, "fuel_unit", "Gallon")
    assert stats_common.parse_display_value("meters", 125000.0) == 125.0
    assert stats_common.parse_display_value("liters", 3.785411784) == pytest.approx(1.0)
    assert stats_common.format_header_key("meters") == "Km"
    assert stats_common.format_header_key("liters") == "Gallons"
    monkeypatch.setitem(cfg.units, "odometer_unit", "Mile")
    assert stats_common.format_header_key("meters") == "Miles"
    assert stats_common.format_header_key("races") == "Finishes"


def test_stats_viewer_reset_lap_time(stats_viewer, dialogs):
    stats_viewer.resetLapTime("GT3", "rb")  # no lap time
    settle(stats_viewer)
    assert dialogs
    stats_viewer.resetLapTime("GT3", "pb")
    settle(stats_viewer)
    assert load_stats()["Spa"]["GT3"]["pb"] > 9999


def test_stats_viewer_remove_vehicle_and_track(stats_viewer):
    stats_viewer.selectRow("LMP2")
    stats_viewer.removeVehicle()
    settle(stats_viewer)
    assert list(load_stats()["Spa"]) == ["GT3"]
    stats_viewer.deleteTrack("")
    settle(stats_viewer)
    assert "Spa" not in load_stats()
    assert stats_viewer.selected_stats_key == "Monza"
