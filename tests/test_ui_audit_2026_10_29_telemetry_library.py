"""Imported laps library as a panel of the lap viewer (UI/UX audit 2026-10-29, section 5): logs listed in background,
search, selection, add to viewer, import, rename on a worker thread, laps moved to the lap viewer trash (one undo &
Recently Deleted for recorded & imported laps), panel page loads without QML warnings"""

import os
import threading
import time

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QApplication, QMessageBox

from neopedal.setting import cfg
from neopedal.userfile.lap_library import FOREIGN_MARK
from neopedal.userfile.telemetry_lap import IMPORT_FOLDER
from tests.test_lap_library import import_log


def wait_until(check, timeout: float = 10.0):
    end = time.monotonic() + timeout
    while not check() and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    assert check()


def wait_library(library, timeout: float = 10.0):
    """Process events until imported laps are listed & their files moved (background)"""
    wait_until(lambda: not library.is_refreshing(), timeout)


def held_job(monkeypatch, module, name: str):
    """Library file function held on its worker thread until released: (gate, threads it ran on)"""
    gate = threading.Event()
    threads: list[str] = []
    real = getattr(module, name)

    def held(*args, **kwargs):
        threads.append(threading.current_thread().name)
        assert gate.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, held)
    return gate, threads


@pytest.fixture
def viewer(ui_env, monkeypatch):
    from neopedal.ui.lap_viewer import LapViewer

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    import_log(cfg.path.telemetry, "Spa race", [139.5, 138.2])
    viewer = LapViewer(None)
    yield viewer
    if shiboken6.isValid(viewer):
        viewer.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def opened(viewer):
    """Library part of the viewer, listed (as when its panel opens)"""
    library = viewer.backend.library
    library.open()
    wait_library(library)
    return library


def rows(library) -> list[dict]:
    return [dict(row) for row in library.model.rows]


def group_key(name: str) -> str:
    from neopedal.ui.quick.lap_library_panel import GROUP_PREFIX

    return GROUP_PREFIX + name


# --- List, selection, add to viewer
def test_lists_logs_and_adds_to_viewer(viewer):
    library = opened(viewer)
    listed = rows(library)
    assert [row["kind"] for row in listed] == ["group", "lap", "lap"]  # single log expanded
    group = listed[0]
    assert group["title"] == "Spa race" and group["count"] == 2 and group["time"] == "2:18.200"
    assert group["track"] == "Spa" and group["driver"] == "Pro" and group["imported"].count(":") == 1  # date & time (language format)
    assert [row["best"] for row in listed[1:]] == [False, True]  # best lap of its log flagged
    assert not library.property("empty") and not library.property("noMatch")
    library.select(group["key"], "set")
    assert library.property("selectedCount") == 2 and library.property("renameTarget") == "Spa race"
    library.addSelected()  # log: every lap, fastest as reference
    assert len(viewer.backend.external) == 2
    assert viewer.backend.reference_key.endswith("2m18.200s.csv")
    assert len(viewer.backend.ordered_checked()) == 2
    library.addRow(listed[1]["key"])  # already shown: not added twice
    assert len(viewer.backend.external) == 2


def test_selection_modes_kept_when_listed_again(viewer):
    import_log(cfg.path.telemetry, "Monza", [101.0])
    library = opened(viewer)
    keys = [row["key"] for row in rows(library)]
    assert keys[0] == group_key("Monza") and len(keys) == 2  # two logs: both collapsed
    library.toggleGroup("Spa race")
    keys = [row["key"] for row in rows(library)]
    assert len(keys) == 4
    library.select(keys[2], "set")
    library.select(keys[3], "toggle")
    assert library.property("selectedCount") == 2
    library.select(keys[2], "toggle")
    assert library.property("selectedCount") == 1
    library.select(keys[0], "set")
    library.select(keys[3], "range")  # Shift+click: every listed row between
    assert [row["selected"] for row in rows(library)] == [True, True, True, True]
    library.select(keys[3], "set")
    library.refresh()
    wait_library(library)
    assert [row["selected"] for row in rows(library)] == [False, False, False, True]  # selection kept
    library.selectAll()
    assert library.property("selectedCount") == 3
    library.toggleGroup("Spa race")  # collapsed: its lap rows left out of the model
    assert [row["kind"] for row in rows(library)] == ["group", "group"]


def test_search_every_word(viewer):
    import_log(cfg.path.telemetry, "Monza run", [101.0], track="Monza")
    library = opened(viewer)
    library.setSearch("monza gt3")  # every word, any column
    assert [row["title"] for row in rows(library) if row["kind"] == "group"] == ["Monza run"]
    library.setSearch("spa 2:18")  # lap of a log matching log words
    listed = rows(library)
    assert [row["time"] for row in listed] == ["2:18.200", "2:18.200"]  # log best time, then its matching lap
    library.setSearch("nothing here")
    assert library.property("noMatch") and not rows(library)
    library.setSearch("")
    assert len([row for row in rows(library) if row["kind"] == "group"]) == 2


def test_empty_library(ui_env):
    from neopedal.ui.lap_viewer import LapViewer

    viewer = LapViewer(None)
    try:
        library = viewer.backend.library
        assert not library.property("empty")  # not listed yet: never "nothing" while reading
        library.open()
        wait_library(library)
        assert library.property("empty") and not rows(library)
    finally:
        viewer.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- Rename on a worker thread
def test_rename_in_background_single_write(viewer, monkeypatch):
    from neopedal.ui.quick import lap_library_panel

    library = opened(viewer)
    library.addRow(group_key("Spa race"))
    assert library.nameError("Spa race", "bad/name") and library.nameError("Spa race", " ") != ""
    assert library.nameError("Spa race", "Spa race") == ""
    assert not library.rename("Spa race", "bad/name")
    gate, threads = held_job(monkeypatch, lap_library_panel, "rename_group")
    library.select(group_key("Spa race"), "set")
    assert library.rename("Spa race", "Spa best")
    wait_until(lambda: threads)
    assert threads[0] != threading.current_thread().name
    assert library.property("writing") and library.is_refreshing()
    assert not library.rename("Spa race", "Other")  # second write refused while one runs
    library.deleteSelected()
    assert len(threads) == 1
    gate.set()
    wait_library(library)
    assert not library.property("writing")
    assert rows(library)[0]["title"] == "Spa best" and rows(library)[0]["selected"]  # selection follows
    assert all("Spa best" in entry.file.path for entry in viewer.backend.external)
    assert all(os.path.exists(path) for path in viewer.backend.ordered_checked())
    assert "Spa best" in viewer.backend.reference_key


def test_rename_error_told_once_done(viewer, monkeypatch):
    from neopedal.ui.quick import lap_library_panel

    library = opened(viewer)

    def refused(*args):
        raise PermissionError(13, "file in use")

    monkeypatch.setattr(lap_library_panel, "rename_group", refused)
    assert library.rename("Spa race", "Spa best")
    wait_library(library)
    assert "file in use" in library.property("problem")
    assert rows(library)[0]["title"] == "Spa race" and not library.property("writing")
    library.clearProblem()
    assert library.property("problem") == ""


def test_page_closed_before_rename_done(viewer, monkeypatch):
    from neopedal.ui.quick import lap_library_panel

    library = opened(viewer)
    gate, threads = held_job(monkeypatch, lap_library_panel, "rename_group")
    assert library.rename("Spa race", "Spa best")
    wait_until(lambda: threads)
    viewer.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gate.set()
    wait_until(lambda: not lap_library_panel.file_jobs().running)  # done on a closed page: nothing told, no error
    assert os.path.isdir(os.path.join(cfg.path.telemetry, IMPORT_FOLDER, "Spa best"))


# --- One trash: page undo & Recently Deleted
def test_delete_goes_to_viewer_trash_and_undo(viewer, monkeypatch):
    from neopedal.ui.quick import lap_library_panel

    backend = viewer.backend
    library = opened(viewer)
    lap_rows = [row for row in rows(library) if row["kind"] == "lap"]
    paths = [row["path"] for row in lap_rows]
    library.addRow(lap_rows[0]["key"])  # shown in charts when deleted
    assert paths[0] in backend.checked
    trashed = []
    backend.lapsTrashed.connect(lambda count, label: trashed.append((count, label)))
    gate, threads = held_job(monkeypatch, lap_library_panel, "delete_laps")
    library.select(lap_rows[0]["key"], "set")
    library.deleteSelected()
    wait_until(lambda: threads)
    assert threads[0] != threading.current_thread().name and os.path.exists(paths[0])  # held: not moved yet
    gate.set()
    wait_library(library)
    assert not os.path.exists(paths[0]) and trashed == [(1, trashed[0][1])] and trashed[0][1]
    assert not backend.external and paths[0] not in backend.checked  # dropped from charts
    assert backend.undoText != "" and len([row for row in rows(library) if row["kind"] == "lap"]) == 1

    backend.openTrash()  # Recently Deleted lists it, named by its log
    wait_until(lambda: not backend.trashLoading)
    trash = backend.trashRows
    assert len(trash) == 1 and "Spa race" in trash[0]["track"]

    backend.undoDelete()  # page undo (Ctrl+Z, toast) restores it in its log
    assert os.path.exists(paths[0]) and backend.undoText == ""
    wait_library(library)
    assert len([row for row in rows(library) if row["kind"] == "lap"]) == 2
    assert paths[0] in backend.checked and len(backend.external) == 1  # shown again
    assert not os.listdir(os.path.join(cfg.path.telemetry, ".trash"))  # trash folders removed once empty


def test_foreign_log_restored_from_recently_deleted(viewer):
    backend = viewer.backend
    folder = os.path.join(cfg.path.telemetry, IMPORT_FOLDER, "Spa race")
    with open(os.path.join(folder, FOREIGN_MARK), "w", encoding="utf-8") as file:
        file.write('{"source": "x"}')
    library = opened(viewer)
    assert rows(library)[0]["driver"] == "Pro"
    library.select(group_key("Spa race"), "set")
    library.deleteSelected()
    wait_library(library)
    assert not os.path.exists(folder) and library.property("empty")  # log removed once empty (mark in trash)
    backend._undo.clear()  # deleted in an earlier session: Recently Deleted only
    backend.undoChanged.emit()
    backend.openTrash()
    wait_until(lambda: not backend.trashLoading)
    keys = [row["key"] for row in backend.trashRows]
    assert len(keys) == 2 and all(os.path.basename(key) != FOREIGN_MARK for key in keys)
    backend.restoreTrashed(keys[0])
    assert os.path.isfile(os.path.join(folder, FOREIGN_MARK))  # mark back with the first lap of the log
    wait_until(lambda: len(backend.trashRows) == 1)  # list read again
    library.refresh()
    wait_library(library)
    assert rows(library)[0]["count"] == 1
    backend.restoreTrashed(os.path.join(cfg.path.telemetry, "elsewhere", "x.csv"))  # not a lap of trash: nothing


def test_trash_origin():
    from neopedal.ui.quick.lap_actions import trash_origin

    folder = os.path.join("tele")
    batch = os.path.join(folder, ".trash", "2026-10-29 10-00-00")
    assert trash_origin(folder, os.path.join(batch, "Spa", "a.csv")) == os.path.join(folder, "Spa", "a.csv")
    assert trash_origin(folder, os.path.join(batch, IMPORT_FOLDER, "log", "a.csv")) == \
        os.path.join(folder, IMPORT_FOLDER, "log", "a.csv")
    assert trash_origin(folder, os.path.join(batch, ".cache", "a.csv")) == ""
    assert trash_origin(folder, os.path.join(batch, "Spa", "x", "a.csv")) == ""
    assert trash_origin(folder, os.path.join(folder, ".trash", "batch", "Spa", "a.csv")) == ""
    assert trash_origin(folder, os.path.join(folder, "Spa", "a.csv")) == ""


# --- Import
def test_import_logs_shown_expanded_problems_told(viewer, monkeypatch, tmp_path):
    from neopedal.ui.quick import lap_library_panel
    from tests.test_motec_import import logger_channels, write_logger_ld

    log = tmp_path / "Monza run.ld"
    write_logger_ld(str(log), logger_channels(), venue="Monza", vehicle="LMP2", driver="Ace")
    (tmp_path / "empty.ld").write_bytes(b"not a log")
    library = opened(viewer)
    library.setSearch("spa")
    reset = []
    library.searchReset.connect(lambda: reset.append(True))
    monkeypatch.setattr(lap_library_panel.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *args, **kwargs: ([str(log), str(tmp_path / "empty.ld")], "")))
    library.importLogs()
    assert library.property("importing")
    library.importLogs()  # running: nothing more
    viewer.backend.wait_jobs()  # imports are lap viewer page jobs
    wait_until(lambda: not library.property("importing"))
    wait_library(library)
    assert reset and library.property("problem") != ""  # broken log told
    listed = rows(library)
    groups = [row for row in listed if row["kind"] == "group"]
    assert [row["title"] for row in groups] == ["Monza run", "Spa race"]
    assert groups[0]["open"] and groups[0]["count"] == 3  # complete laps only, new log expanded


def test_lap_infos_read_once_in_background(viewer, monkeypatch):
    from neopedal.userfile import lap_cache

    calls: list[str] = []
    real = lap_cache.read_lap_info

    def reading(path):
        calls.append(threading.current_thread().name)
        return real(path)

    monkeypatch.setattr(lap_cache, "read_lap_info", reading)
    library = viewer.backend.library
    library.open()
    assert library.property("loading")
    wait_library(library)
    assert calls and threading.current_thread().name not in calls
    calls.clear()
    library.refresh()
    wait_library(library)
    assert not calls  # lap infos from index of imported log


# --- Panel page
def test_panel_opens_from_import_menu_without_warnings(viewer):
    from tests.test_lap_viewer import wait_loaded
    from tests.test_lap_viewer_fix_qml import evaluate, find, no_qml_warnings, wait

    with no_qml_warnings():
        viewer.resize(1300, 800)
        wait_loaded(viewer)
        viewer.show()
        wait(0.3)
        view = viewer.view
        panel = view.rootObject().findChild(QObject, "libraryPanel")
        assert panel is not None and not panel.property("visible")
        viewer.backend.openLibrary()  # Import menu "Imported Laps…"
        wait(0.4)
        wait_library(viewer.backend.library)
        wait(0.3)
        assert panel.property("visible")
        lists = find(view, lambda item: item.objectName() == "libraryList")
        assert lists and lists[0].property("count") == 3
        assert evaluate(view, panel, "library.selectedCount") == 0
        viewer.backend.library.select(group_key("Spa race"), "set")
        wait(0.1)
        evaluate(view, panel, "addAndClose()")
        wait(0.4)
        assert not panel.property("visible") and len(viewer.backend.external) == 2
        viewer.backend.openLibrary()
        wait(0.4)
        evaluate(view, panel, "startRename()")
        wait(0.3)
        dialog = view.rootObject().findChild(QObject, "libraryRenameDialog")
        assert dialog.property("visible") and dialog.property("source") == "Spa race"
        evaluate(view, dialog, "close()")
        evaluate(view, panel, "close()")
        wait(0.4)


def test_panel_narrow_hides_detail_columns(viewer):
    from tests.test_lap_viewer import wait_loaded
    from tests.test_lap_viewer_fix_qml import evaluate, no_qml_warnings, wait

    with no_qml_warnings():
        viewer.resize(1300, 800)
        wait_loaded(viewer)
        viewer.show()
        wait(0.3)
        view = viewer.view
        panel = view.rootObject().findChild(QObject, "libraryPanel")
        viewer.backend.openLibrary()
        wait_library(viewer.backend.library)
        wait(0.4)
        assert panel.property("visible") and panel.property("wide")
        assert panel.property("width") <= view.width()
        panel.setProperty("width", evaluate(view, panel, "theme.em * 30"))  # narrow window
        wait(0.2)
        assert not panel.property("wide")  # vehicle, driver, date: row tooltip
        evaluate(view, panel, "close()")
        wait(0.3)
