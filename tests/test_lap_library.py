"""Imported laps library: list, rename, delete, add to lap viewer"""

import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from tinypedal.userfile.lap_library import delete_laps, group_name_error, list_imported, rename_group
from tinypedal.userfile.motec_import import ImportedLap, save_imported_lap
from tinypedal.userfile.telemetry_lap import IMPORT_FOLDER


def import_log(filepath: str, log: str, lap_times: list[float], track: str = "Spa") -> list[str]:
    """Imported laps of a log, as saved by MoTeC import"""
    paths = []
    for number, lap_time in enumerate(lap_times, 1):
        samples = 50
        columns = {
            "time": [lap_time * index / samples for index in range(samples + 1)],
            "lap_time": [lap_time * index / samples for index in range(samples + 1)],
            "distance": [7000.0 * index / samples for index in range(samples + 1)],
            "speed_kph": [200.0] * (samples + 1),
        }
        info = {"kind": "lap", "source": "MoTeC", "track": track, "vehicle": "GT3 Car", "driver": "Pro"}
        lap = ImportedLap(number, lap_time, columns, info)
        paths.append(os.path.normpath(save_imported_lap(lap, os.path.join(filepath, IMPORT_FOLDER, log), 1.0e9)))
    return paths


# --- Files
def test_list_rename_delete(tmp_path):
    folder = str(tmp_path)
    import_log(folder, "b_log", [139.5, 138.2])
    first = import_log(folder, "A_log", [137.9])
    os.makedirs(os.path.join(folder, IMPORT_FOLDER, "empty"))
    groups = list_imported(folder)
    assert [name for name, _ in groups] == ["A_log", "b_log"]  # empty group left out
    assert [lap.lap_time for lap in groups[1][1]] == pytest.approx([139.5, 138.2])  # lap order

    assert group_name_error(folder, "A_log", "b_log") == "exists"
    assert group_name_error(folder, "A_log", "a_LOG") == ""  # case change of same group
    for name in ("", " x", "a/b", "c:d", ".hidden"):
        assert group_name_error(folder, "A_log", name) == "invalid"
    moved = rename_group(folder, "A_log", "Pro lap")
    assert list(moved) == first and os.path.exists(moved[first[0]])
    assert [name for name, _ in list_imported(folder)] == ["b_log", "Pro lap"]

    laps = [lap.path for lap in list_imported(folder)[0][1]]
    outside = tmp_path / "own.csv"
    outside.write_text("x", encoding="utf-8")
    assert delete_laps(folder, [laps[0], str(outside)]) == {laps[0]: ""}  # library laps only
    assert outside.exists()
    delete_laps(folder, laps[1:])
    assert [name for name, _ in list_imported(folder)] == ["Pro lap"]  # group removed when empty
    assert not os.path.exists(os.path.join(folder, IMPORT_FOLDER, "b_log"))


def test_no_import_folder(tmp_path):
    assert list_imported(str(tmp_path)) == []


# --- Library page & lap viewer
@pytest.fixture
def viewer(ui_env, monkeypatch):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import LapViewer

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    import_log(cfg.path.telemetry, "Spa race", [139.5, 138.2])
    viewer = LapViewer(None)
    yield viewer
    viewer.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def open_library(viewer):
    from tinypedal.ui.lap_library import LapLibrary

    viewer.open_library()
    return next(widget for widget in viewer.findChildren(LapLibrary) if widget.isVisible())


def test_library_lists_and_adds_to_viewer(viewer):
    library = open_library(viewer)
    group = library.tree.topLevelItem(0)
    assert group.text(library.COL_NAME) == "Spa race" and group.childCount() == 2
    assert group.text(library.COL_TIME) == "2:18.200" and group.text(library.COL_TRACK) == "Spa"
    assert not library.label_empty.isVisibleTo(library)
    library.add_to_viewer([group])  # group: every lap, fastest as reference
    assert len(viewer.external) == 2
    assert viewer.reference_key.endswith("2m18.200s.csv")
    assert len(viewer.checked_paths()) == 2
    library.add_to_viewer([group.child(0)])  # already shown: not added twice
    assert len(viewer.external) == 2
    library.close()


def test_library_rename_and_delete_update_viewer(viewer, monkeypatch):
    from tinypedal.ui import lap_library

    library = open_library(viewer)
    library.add_to_viewer([library.tree.topLevelItem(0)])
    inputs = []
    monkeypatch.setattr(lap_library.TextInputDialog, "show", lambda self: inputs.append(self))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))

    library.tree.topLevelItem(0).child(1).setSelected(True)  # lap selected: its log renamed
    library.rename()
    assert not inputs[0]._on_accept("bad/name") and warnings
    assert inputs[0]._on_accept("Spa best")
    assert library.tree.topLevelItem(0).text(library.COL_NAME) == "Spa best"
    assert all("Spa best" in entry.file.path for entry in viewer.external)
    assert all(os.path.exists(path) for path in viewer.checked_paths())
    assert "Spa best" in viewer.reference_key

    library.tree.clearSelection()
    library.tree.topLevelItem(0).child(0).setSelected(True)
    library.delete()
    assert len(viewer.external) == 1 and library.tree.topLevelItem(0).childCount() == 1
    library.tree.topLevelItem(0).setSelected(True)
    library.delete()
    assert not viewer.external and library.tree.topLevelItemCount() == 0
    assert library.label_empty.isVisibleTo(library)
    library.close()


# --- Import, search, drop
def test_library_import_search_and_date(viewer, monkeypatch, tmp_path):
    from tests.test_motec_import import logger_channels, write_logger_ld
    from tinypedal.ui import lap_library

    log = tmp_path / "Monza run.ld"
    write_logger_ld(str(log), logger_channels(), venue="Monza", vehicle="LMP2", driver="Ace")
    (tmp_path / "empty.ld").write_bytes(b"not a log")
    library = open_library(viewer)
    monkeypatch.setattr(lap_library.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *args, **kwargs: ([str(log), str(tmp_path / "empty.ld")], "")))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    library.import_logs()
    names = [item.text(library.COL_NAME) for item in library.top_items()]
    assert names == ["Monza run", "Spa race"] and warnings  # broken log reported
    monza = library.top_items()[0]
    assert monza.isExpanded() and monza.childCount() == 3  # complete laps only
    assert monza.text(library.COL_DATE)[:2] == "20"  # import date

    library.edit_filter.setText("monza lmp2")  # every word, any column
    assert not monza.isHidden() and library.top_items()[1].isHidden()
    library.edit_filter.setText("spa 2:18")  # lap of a group matching group words
    spa = library.top_items()[1]
    visible = [spa.child(index).text(library.COL_TIME) for index in range(spa.childCount())
               if not spa.child(index).isHidden()]
    assert not spa.isHidden() and visible == ["2:18.200"] and monza.isHidden()
    library.edit_filter.clear()
    assert not monza.isHidden() and not spa.isHidden()
    library.close()


def test_drop_motec_log_on_app(ui_env, tmp_path, monkeypatch):
    from tests.test_motec_import import logger_channels, write_logger_ld
    from tinypedal.setting import cfg
    from tinypedal.ui import file_drop

    log = tmp_path / "Shared lap.ld"
    write_logger_ld(str(log), logger_channels())
    assert file_drop.classify(str(log)) == file_drop.DROP_MOTEC

    from PySide6.QtWidgets import QWidget

    window = QWidget()
    try:
        messages = file_drop.handle_drop(window, [str(log)])
        assert "Shared lap" in messages[0] and "3 laps" in messages[0]
        from tinypedal.ui._common import BaseDialog

        viewer = next(dialog for dialog in window.findChildren(BaseDialog) if type(dialog).__name__ == "LapViewer")
        assert len(viewer.external) == 3  # shown in lap viewer
        assert list_imported(cfg.path.telemetry)[0][0] == "Shared lap"
        assert "Unable to import" in file_drop.handle_drop(window, [str(tmp_path / "missing.ld")])[0]
        viewer.close()
    finally:
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
