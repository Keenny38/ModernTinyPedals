"""Imported laps library: list, rename, delete, add to lap viewer"""

import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from neopedal.userfile.lap_library import delete_laps, group_name_error, list_imported, rename_group
from neopedal.userfile.motec_import import ImportedLap, save_imported_lap
from neopedal.userfile.telemetry_lap import IMPORT_FOLDER


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
    trash = str(tmp_path / "trash")
    deletion = delete_laps(folder, [laps[0], str(outside)], trash)
    assert deletion.deleted == [laps[0]] and not deletion.failed  # library laps only
    assert outside.exists()
    delete_laps(folder, laps[1:], trash)
    assert [name for name, _ in list_imported(folder)] == ["Pro lap"]  # group removed when empty
    assert not os.path.exists(os.path.join(folder, IMPORT_FOLDER, "b_log"))


def test_no_import_folder(tmp_path):
    assert list_imported(str(tmp_path)) == []


# --- Library page & lap viewer
@pytest.fixture
def viewer(ui_env, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.ui.lap_viewer import LapViewer

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    import_log(cfg.path.telemetry, "Spa race", [139.5, 138.2])
    viewer = LapViewer(None)
    yield viewer
    viewer.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_library(library, timeout: float = 10.0):
    """Process events until imported laps are listed (read in background)"""
    import time

    from PySide6.QtWidgets import QApplication

    end = time.monotonic() + timeout
    while library.is_refreshing() and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    assert not library.is_refreshing()


def open_library(viewer):
    """Imported laps library panel of the viewer (backend.library), listed as when opened"""
    viewer.backend.openLibrary()  # Import menu: panel asked to open
    library = viewer.backend.library
    library.open()  # panel shown: logs listed in background
    wait_library(library)
    return library


def library_rows(library) -> list[dict]:
    """Rows listed by the library panel: logs & laps of expanded logs"""
    return [dict(row) for row in library.model.rows]


def test_library_lists_and_adds_to_viewer(viewer):
    library = open_library(viewer)
    group = library_rows(library)[0]
    assert group["title"] == "Spa race" and group["count"] == 2 and len(library_rows(library)) == 3
    assert group["time"] == "2:18.200" and group["track"] == "Spa"
    assert not library.property("empty")
    library.addRow(group["key"])  # group: every lap, fastest as reference
    assert len(viewer.backend.external) == 2
    assert viewer.backend.reference_key.endswith("2m18.200s.csv")
    assert len(viewer.backend.ordered_checked()) == 2
    library.addRow(library_rows(library)[1]["key"])  # already shown: not added twice
    assert len(viewer.backend.external) == 2


def test_library_rename_and_delete_update_viewer(viewer):
    library = open_library(viewer)
    library.addRow(library_rows(library)[0]["key"])
    library.select(library_rows(library)[2]["key"], "set")  # lap selected: its log renamed
    assert library.property("renameTarget") == "Spa race"
    assert not library.rename("Spa race", "bad/name") and library.nameError("Spa race", "bad/name")
    assert library.rename("Spa race", "Spa best")
    wait_library(library)
    assert library_rows(library)[0]["title"] == "Spa best"
    assert all("Spa best" in entry.file.path for entry in viewer.backend.external)
    assert all(os.path.exists(path) for path in viewer.backend.ordered_checked())
    assert "Spa best" in viewer.backend.reference_key

    library.select(library_rows(library)[1]["key"], "set")
    library.deleteSelected()
    wait_library(library)
    assert len(viewer.backend.external) == 1 and library_rows(library)[0]["count"] == 1
    library.select(library_rows(library)[0]["key"], "set")
    library.deleteSelected()
    wait_library(library)
    assert not viewer.backend.external and not library_rows(library)
    assert library.property("empty")


# --- Import, search, drop
def test_library_import_search_and_date(viewer, monkeypatch, tmp_path):
    from neopedal.ui.quick import lap_library_panel
    from tests.test_motec_import import logger_channels, write_logger_ld

    log = tmp_path / "Monza run.ld"
    write_logger_ld(str(log), logger_channels(), venue="Monza", vehicle="LMP2", driver="Ace")
    (tmp_path / "empty.ld").write_bytes(b"not a log")
    library = open_library(viewer)
    monkeypatch.setattr(lap_library_panel.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *args, **kwargs: ([str(log), str(tmp_path / "empty.ld")], "")))
    library.importLogs()
    assert library.property("importing")  # import running in background
    viewer.backend.wait_jobs()  # imports are lap viewer page jobs
    wait_library(library)
    assert not library.property("importing")
    groups = [row for row in library_rows(library) if row["kind"] == "group"]
    assert [row["title"] for row in groups] == ["Monza run", "Spa race"] and library.property("problem")  # broken log
    monza = groups[0]
    assert monza["open"] and monza["count"] == 3  # complete laps only, shown expanded
    assert monza["imported"].endswith(":" + monza["imported"][-2:]) and len(monza["imported"]) > 6  # import date & time

    library.setSearch("monza lmp2")  # every word, any column
    assert [row["title"] for row in library_rows(library) if row["kind"] == "group"] == ["Monza run"]
    library.setSearch("spa 2:18")  # lap of a group matching group words
    listed = library_rows(library)
    assert [row["title"] for row in listed if row["kind"] == "group"] == ["Spa race"]
    assert [row["time"] for row in listed if row["kind"] == "lap"] == ["2:18.200"]
    library.setSearch("")
    assert len([row for row in library_rows(library) if row["kind"] == "group"]) == 2


def test_drop_motec_log_on_app(ui_env, tmp_path, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.ui import file_drop
    from tests.test_motec_import import logger_channels, write_logger_ld

    log = tmp_path / "Shared lap.ld"
    write_logger_ld(str(log), logger_channels())
    assert file_drop.classify(str(log)) == file_drop.DROP_MOTEC

    from PySide6.QtWidgets import QWidget

    window = QWidget()
    try:
        messages = file_drop.handle_drop(window, [str(log)])
        assert "Shared lap" in messages[0] and "Importing" in messages[0]  # read in background by viewer page
        from neopedal.ui._common import BaseDialog
        from tests.test_lap_viewer import wait_loaded

        viewer = next(dialog for dialog in window.findChildren(BaseDialog) if type(dialog).__name__ == "LapViewer")
        wait_loaded(viewer)
        assert len(viewer.backend.external) == 3 and "3 laps" in viewer.backend.status  # shown in lap viewer
        assert list_imported(cfg.path.telemetry)[0][0] == "Shared lap"
        assert "Unable to import" in file_drop.handle_drop(window, [str(tmp_path / "missing.ld")])[0]
        viewer.close()
    finally:
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
