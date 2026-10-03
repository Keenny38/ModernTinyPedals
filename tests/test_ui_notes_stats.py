"""Track notes editor & driver stats viewer tests"""

import json
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.setting import cfg
from tinypedal.ui._common import BaseEditor


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


# --- Track notes editor
@pytest.fixture
def notes_editor(dialogs, monkeypatch):
    from tinypedal.ui import track_notes_editor

    monkeypatch.setattr(track_notes_editor, "show_toast", lambda *args, **kwargs: None)
    editor = track_notes_editor.TrackNotesEditor(None)
    yield editor
    close(editor)


def notes_column(editor, column: int) -> list[str]:
    return [editor.table_notes.item(row, column).text() for row in range(editor.table_notes.rowCount())]


def test_notes_edit_sort_tag_and_save(notes_editor, tmp_path, monkeypatch):
    from tinypedal.ui import track_notes_editor
    from tinypedal.userfile.track_notes import HEADER_PACE_NOTES, load_notes_file

    notes_editor.create_pacenotes()
    table = notes_editor.table_notes
    table.item(0, 0).setText("500")
    table.item(0, 1).setText("R3")
    notes_editor.add_notes()
    table.item(1, 0).setText("bad")  # invalid distance reverted
    assert float(table.item(1, 0).text()) == 0
    table.item(1, 0).setText("120.5")
    table.item(1, 1).setText("L2")
    table.selectRow(1)
    notes_editor.add_tag("#pit")
    notes_editor.add_tag("#pit")  # added once
    assert table.item(1, 3).text() == "#pit"
    target = tmp_path / "Spa.tppn"
    monkeypatch.setattr(track_notes_editor.QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(target), "TinyPedal Pace Notes (*.tppn)"))
    notes_editor.saving()  # sorted by distance before saving
    assert notes_column(notes_editor, 1) == ["L2", "R3"]
    notes, _ = load_notes_file(f"{tmp_path.as_posix()}/", "Spa.tppn", HEADER_PACE_NOTES)
    assert [(note["distance"], note["pace note"], note["tags"]) for note in notes] == [
        (120.5, "L2", "#pit"), (500.0, "R3", "")]
    assert not notes_editor.is_modified()


def test_notes_load_offset_and_undo(notes_editor, tmp_path, monkeypatch):
    from tinypedal.ui import track_notes_editor
    from tinypedal.userfile.track_notes import HEADER_TRACK_NOTES, create_notes_metadata, save_notes_file

    notes = [{"distance": 100.0, "track note": "Eau Rouge", "comment": "", "tags": ""},
             {"distance": 900.0, "track note": "Kemmel", "comment": "flat", "tags": ""}]
    save_notes_file(f"{tmp_path.as_posix()}/", "Spa.tptn", HEADER_TRACK_NOTES, notes, create_notes_metadata())
    monkeypatch.setattr(track_notes_editor.QFileDialog, "getOpenFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Spa.tptn"), "TinyPedal Track Notes (*.tptn)"))
    notes_editor.load_tracknotes_file()
    assert notes_column(notes_editor, 1) == ["Eau Rouge", "Kemmel"]
    table = notes_editor.table_notes
    table.clearSelection()
    table.item(0, 0).setSelected(True)
    table.item(1, 0).setSelected(True)
    notes_editor.apply_batch_offset(10, False)
    assert notes_column(notes_editor, 0) == ["110.0", "910.0"]
    notes_editor.undo()
    assert notes_column(notes_editor, 0) == ["100.0", "900.0"]


def test_notes_set_position_from_telemetry(notes_editor, dialogs):
    from tinypedal.api_control import api

    notes_editor.create_tracknotes()
    table = notes_editor.table_notes
    table.clearSelection()
    notes_editor.set_position_from_tele()  # no distance selected
    assert dialogs
    api.read.lap.distance = lambda: 1234.5678
    table.setCurrentCell(0, 0)
    notes_editor.set_position_from_tele()
    assert table.item(0, 0).text() == "1234.57"  # 2 decimals


def test_notes_insert_delete_and_clear_tag(notes_editor):
    notes_editor.create_pacenotes()
    table = notes_editor.table_notes
    table.setCurrentCell(0, 0)
    notes_editor.insert_notes(1)
    notes_editor.insert_notes(0)
    assert table.rowCount() == 3
    table.selectRow(2)
    notes_editor.add_tag("#pit")
    notes_editor.clear_tag()
    assert table.item(2, 3).text() == ""
    notes_editor.delete_notes()
    assert table.rowCount() == 2


def test_notes_sort_without_errors(notes_editor):
    notes_editor.create_pacenotes()
    table = notes_editor.table_notes
    for distance in ("300", "100", "200"):
        notes_editor.add_notes()
        table.item(table.rowCount() - 1, 0).setText(distance)
    notes_editor.sort_notes()
    assert notes_column(notes_editor, 0) == ["0", "100", "200", "300"]


# --- Driver stats viewer
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
def stats_viewer(dialogs, stats_file):
    from tinypedal.api_control import api
    from tinypedal.ui.driver_stats_viewer import DriverStatsViewer

    api.read.session.track_name = lambda: "Spa"
    viewer = DriverStatsViewer(None)
    yield viewer
    close(viewer)


def load_stats():
    with open(f"{cfg.path.config}driver.stats", encoding="utf-8") as file:
        return json.load(file)


def test_stats_viewer_shows_current_track(stats_viewer):
    table = stats_viewer.table_stats
    assert stats_viewer.selected_stats_key == "Spa"
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "LMP2"  # sorted by personal best
    gt3 = 1
    header = stats_viewer.table_header_key
    assert table.item(gt3, header.index("pb")).text() == "2:18.500"
    assert table.item(gt3, header.index("rb")).text() not in ("0", "0.0")  # invalid time shown as no time
    assert table.item(gt3, header.index("seconds")).text() == "2.0"  # hours


def test_stats_viewer_display_units(stats_viewer, monkeypatch):
    from tinypedal.ui import driver_stats_viewer

    monkeypatch.setitem(cfg.units, "odometer_unit", "Kilometer")
    monkeypatch.setitem(cfg.units, "fuel_unit", "Gallon")
    assert driver_stats_viewer.parse_display_value("meters", 125000.0) == 125.0
    assert driver_stats_viewer.parse_display_value("liters", 3.785411784) == pytest.approx(1.0)
    assert driver_stats_viewer.format_header_key("meters") == "Km"
    assert driver_stats_viewer.format_header_key("liters") == "Gallons"
    monkeypatch.setitem(cfg.units, "odometer_unit", "Mile")
    assert driver_stats_viewer.format_header_key("meters") == "Miles"
    assert driver_stats_viewer.format_header_key("races") == "Finishes"


def test_stats_viewer_reset_lap_time(stats_viewer, dialogs):
    header = stats_viewer.table_header_key
    stats_viewer.reset_stat(1, header.index("rb"))  # no lap time
    assert dialogs
    stats_viewer.reset_stat(1, header.index("pb"))
    assert load_stats()["Spa"]["GT3"]["pb"] > 9999


def test_stats_viewer_remove_vehicle_and_track(stats_viewer):
    table = stats_viewer.table_stats
    table.setCurrentCell(0, 0)
    stats_viewer.remove_vehicle()
    assert list(load_stats()["Spa"]) == ["GT3"]
    stats_viewer.delete_stats_key()
    assert "Spa" not in load_stats()
    assert stats_viewer.selected_stats_key == "Monza"
