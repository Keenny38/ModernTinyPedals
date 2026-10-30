"""UI/UX audit 2026-10-29, telemetry lot: track & pace notes editor rebuilt as a Qt Quick page (TrackNotesEditor.qml,
quick/track_notes_backend.py): page loads, every feature of the old editor, Save vs Save As, notes file changed by
another editor (lap viewer track notes) never silently overwritten in either place"""

import os
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neopedal import i18n
from neopedal.setting import cfg
from neopedal.userfile.track_notes import (
    HEADER_PACE_NOTES,
    HEADER_TRACK_NOTES,
    create_notes_metadata,
    load_notes_file,
    save_notes_file,
)
from tests.test_perf_page_state import qml_warnings  # noqa: F401
from tests.test_track_map_viewer import wait_jobs, write_map


@pytest.fixture
def dialogs(ui_env, monkeypatch):
    """Questions answered Discard (tests set others), warnings recorded, exceptions in Qt slots fail the test"""
    warnings, errors = [], []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard))
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: errors.append(exc_info[1]))
    yield warnings
    assert not errors


@pytest.fixture
def editor(dialogs, qml_warnings):  # noqa: F811
    from neopedal.ui.track_notes_editor import TrackNotesEditor

    page = TrackNotesEditor(None)
    page.resize(1100, 700)
    yield page
    page.set_unmodified()
    assert page.close()  # closed (not left open by a nested close)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not [text for text in qml_warnings if "TrackNotes" in text], qml_warnings


def answer(monkeypatch, button):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: button))


def save_to(monkeypatch, path, shown_filter="NeoPedal Pace Notes (*.tppn)"):
    asked = []

    def picked(*args, **kwargs):
        asked.append(kwargs.get("dir", ""))
        return str(path), shown_filter

    monkeypatch.setattr(QFileDialog, "getSaveFileName", picked)
    return asked


def texts(backend, column="note"):
    return [row[column] for row in backend.rows]


def keys(backend):
    return [row["key"] for row in backend.rows]


def test_page_loads_without_qml_warnings(editor, qml_warnings):  # noqa: F811
    root = editor.view.rootObject()
    assert not editor.view.errors() and root is not None
    backend = editor.backend
    assert backend.notesType == "Pace Notes" and backend.rowCount == 1 and not backend.modified
    assert backend.notes.rowCount() == 1
    for name in ("fileToolbar", "notesToolbar", "mapToolbar", "notesList", "notesMap", "metaDialog",
                 "replaceDialog", "offsetDialog"):
        assert root.findChild(QObjectType(), name) is not None, name
    assert not qml_warnings, qml_warnings


def QObjectType():
    from PySide6.QtCore import QObject

    return QObject


def item_named(root, name: str):
    """Item of page by object name (Repeater items: visual children, not object children)"""
    stack = [root]
    while stack:
        item = stack.pop()
        if item.objectName() == name:
            return item
        stack.extend(item.childItems())
    return None


@pytest.mark.parametrize("language", ["English", "Français"])
def test_list_rows_and_buttons_follow_backend(dialogs, qml_warnings, language):  # noqa: F811
    from neopedal.ui.track_notes_editor import TrackNotesEditor

    i18n.set_language(language)
    page = TrackNotesEditor(None)
    try:
        page.resize(900, 600)
        page.show()
        QCoreApplication.processEvents()
        root = page.view.rootObject()
        notes_list = root.findChild(QObjectType(), "notesList")
        backend = page.backend
        backend.addRow()
        backend.addRow()
        QCoreApplication.processEvents()
        assert notes_list.property("count") == 3
        delete = item_named(root, "deleteButton")
        assert delete is not None and delete.property("enabled")  # new row selected
        backend.clearSelection()
        QCoreApplication.processEvents()
        assert not delete.property("enabled")  # disabled, never a "No data selected" warning
        backend.toggleMap()
        QCoreApplication.processEvents()
        assert not backend.mapShown
        page.resize(560, 600)  # narrow window: map above notes
        backend.toggleMap()
        QCoreApplication.processEvents()
        assert not [text for text in qml_warnings if "TrackNotes" in text], qml_warnings
    finally:
        i18n.set_language("English")
        page.set_unmodified()
        page.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_rows_edit_select_sort_tag_delete_undo(editor):
    backend = editor.backend
    first = keys(backend)[0]
    assert backend.setValue(first, "distance", "500") and backend.setValue(first, "note", "R3")
    assert not backend.setValue(first, "distance", "bad") and backend.rows[0]["distance"] == 500  # value kept
    assert not backend.setValue(first, "distance", "inf")
    assert backend.setValue(first, "distance", "1234,567")  # decimal comma, 2 decimals
    assert backend.rows[0]["distance"] == 1234.57
    backend.addRow()
    second = keys(backend)[1]
    backend.setValue(second, "distance", "120.5")
    backend.setValue(second, "note", "L2")
    assert backend.selectedCount == 1 and backend.currentIndex == 1  # new row current
    backend.addTag("#pit")
    backend.addTag("#pit")  # added once
    assert backend.rows[1]["tags"] == "#pit" and backend.notes.rows[1]["pit"]
    backend.sortRows()
    assert texts(backend) == ["L2", "R3"]
    assert backend.modified and backend.canUndo
    backend.select(first, 0)
    backend.select(second, Qt.KeyboardModifier.ControlModifier.value)
    assert backend.selectedCount == 2
    messages = []
    backend.message.connect(lambda text, error, undo: messages.append((text, error, undo)))
    assert backend.deleteSelected() == 2 and backend.rowCount == 0
    assert messages[-1][2]  # toast offers Undo
    backend.undo()
    assert texts(backend) == ["L2", "R3"] and keys(backend) == [second, first]  # same rows (delegates kept)
    backend.redo()
    assert backend.rowCount == 0
    backend.undo()
    backend.select(second, 0)
    backend.clearTags()
    assert backend.rows[0]["tags"] == ""


def test_insert_rows_around_current_and_shift_range(editor):
    backend = editor.backend
    first = keys(backend)[0]
    backend.select(first, 0)
    backend.insertRow(1)  # below
    backend.insertRow(0)  # above the new current row
    assert backend.rowCount == 3 and keys(backend)[0] == first
    backend.select(keys(backend)[0], 0)
    backend.select(keys(backend)[2], Qt.KeyboardModifier.ShiftModifier.value)
    assert backend.selectedCount == 3
    backend.clearSelection()
    assert backend.selectedCount == 0 and backend.currentIndex == -1
    backend.insertRow(0)  # no current row: at top
    assert backend.currentIndex == 0


def test_offset_scale_replace_and_metadata(editor):
    backend = editor.backend
    first = keys(backend)[0]
    backend.setValue(first, "distance", "100")
    backend.setValue(first, "note", "Turn one")
    backend.addRow()
    second = keys(backend)[1]
    backend.setValue(second, "distance", "900")
    backend.setValue(second, "note", "turn ONE")
    backend.selectAll()
    assert backend.applyOffset(10, False) == 2
    assert [row["distance"] for row in backend.rows] == [110.0, 910.0]
    backend.select(first, 0)
    backend.applyOffset(2, True)  # scale mode
    assert [row["distance"] for row in backend.rows] == [220.0, 910.0]
    assert backend.columnValues("note") == ["Turn one", "turn ONE"] and backend.columnValues("tags") == []
    assert backend.replaceText("note", "one", "1", True, False) == 1  # match case
    assert texts(backend) == ["Turn 1", "turn ONE"]
    assert backend.replaceText("note", "turn one", r"\1", False, True) == 1  # whole text, plain replacement
    assert texts(backend) == ["Turn 1", r"\1"]
    backend.undo()
    assert texts(backend) == ["Turn 1", "turn ONE"]  # one undo step per replace
    backend.set_modified(False)
    backend.setMetadata({key: value for key, value in backend.metadata.items()})  # nothing changed
    assert not backend.modified
    backend.setMetadata({"AUTHOR": "Steven"})
    assert backend.metadata["AUTHOR"] == "Steven" and backend.modified
    assert [field["key"] for field in backend.metadataFields] == ["TITLE", "AUTHOR", "DATE", "DESCRIPTION"]


def test_save_as_then_save_to_same_file(editor, tmp_path, monkeypatch):
    backend = editor.backend
    first = keys(backend)[0]
    backend.setValue(first, "distance", "500")
    backend.setValue(first, "note", "R3")
    backend.addRow()
    backend.setValue(keys(backend)[1], "distance", "120.5")
    backend.setValue(keys(backend)[1], "note", "L2")
    target = tmp_path / "Spa.tppn"
    asked = save_to(monkeypatch, target)
    assert editor.save_action()()  # Ctrl+S on new notes: file name asked
    assert len(asked) == 1 and asked[0].startswith(cfg.path.pace_notes)
    notes, _ = load_notes_file(f"{tmp_path.as_posix()}/", "Spa.tppn", HEADER_PACE_NOTES)
    assert [(note["distance"], note["pace note"]) for note in notes] == [(120.5, "L2"), (500.0, "R3")]
    assert not backend.modified and backend.fileName == "Spa.tppn"
    assert backend.filePath == os.path.normpath(target)
    backend.setValue(keys(backend)[0], "comment", "brake late")
    assert editor.is_modified()
    assert editor.save_action()()  # Ctrl+S again: same file, no name asked
    assert len(asked) == 1
    notes, _ = load_notes_file(f"{tmp_path.as_posix()}/", "Spa.tppn", HEADER_PACE_NOTES)
    assert notes[0]["comment"] == "brake late"
    # Name changed: Save writes that file in the folder of the open file (extension kept)
    backend.setFileName("Spa wet")
    assert backend.save() and (tmp_path / "Spa wet.tppn").exists() and len(asked) == 1
    # Save As asks again, from the folder of the open file
    other = tmp_path / "copy.tppn"
    asked = save_to(monkeypatch, other)
    assert backend.saveAs() and other.exists()
    assert os.path.normpath(asked[0]) == os.path.normpath(str(tmp_path / "Spa wet.tppn"))


def test_save_errors_keep_notes(editor, dialogs, tmp_path, monkeypatch):
    from neopedal.ui.quick import track_notes_backend

    backend = editor.backend
    backend.setValue(keys(backend)[0], "note", "R3")
    save_to(monkeypatch, tmp_path / "missing folder" / "Spa.tppn")
    assert not backend.save()
    assert dialogs and "Unable to save notes at:" in dialogs[-1] and backend.modified
    save_to(monkeypatch, tmp_path / "Spa.tppn")

    def read_only(**kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(track_notes_backend, "save_notes_file", read_only)
    answer(monkeypatch, QMessageBox.StandardButton.Save)
    assert editor.close() is False  # saving failed on close: page kept open
    assert backend.modified and texts(backend) == ["R3"]
    backend.deleteSelected()
    monkeypatch.undo()
    messages = []
    backend.message.connect(lambda text, error, undo: messages.append((text, error)))
    save_to(monkeypatch, tmp_path / "empty.tppn")
    assert not backend.save() and messages[-1] == ("Nothing to save.", True)


def test_open_track_notes_and_gpl_format(editor, tmp_path, monkeypatch):
    backend = editor.backend
    notes = [{"distance": 900.0, "track note": "Kemmel", "comment": "flat", "tags": ""},
             {"distance": 100.0, "track note": "Eau Rouge", "comment": "", "tags": "#pit"}]
    metadata = {**create_notes_metadata(), "AUTHOR": "me"}
    save_notes_file(f"{tmp_path.as_posix()}/", "Spa.tptn", HEADER_TRACK_NOTES, notes, metadata)
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *args, **kwargs: (str(tmp_path / "Spa.tptn"), "NeoPedal Track Notes (*.tptn)"))
    backend.openNotes("Track Notes")
    assert backend.notesType == "Track Notes" and texts(backend) == ["Eau Rouge", "Kemmel"]
    assert backend.metadata["AUTHOR"] == "me" and not backend.modified and not backend.canUndo
    assert backend.columnLabels == ["Distance", "Track Note", "Comment", "Tags"]
    # Invalid file: warned, notes kept
    (tmp_path / "bad.tptn").write_text("nothing", encoding="utf-8")
    assert not backend.load_file(str(tmp_path / "bad.tptn"), "Track Notes")
    assert texts(backend) == ["Eau Rouge", "Kemmel"]
    # Saved as GPL pace notes (.ini): pace note column from note column
    target = tmp_path / "spa.ini"
    save_to(monkeypatch, target, "GPL Pace Notes (*.ini)")
    assert backend.saveAs()
    content = target.read_text(encoding="utf-8")
    assert "Eau Rouge.mp3, 100;" in content and "Kemmel.mp3, 900; flat" in content


def test_set_position_from_map_and_telemetry(editor, monkeypatch):
    from neopedal.api_control import api

    backend = editor.backend
    messages = []
    backend.message.connect(lambda text, error, undo: messages.append((text, error)))
    backend.clearSelection()
    assert not backend.setPositionFromTelemetry() and messages[-1][1]  # no note selected: told
    monkeypatch.setattr(api.read.lap, "distance", lambda: 1234.5678, raising=False)
    backend.select(keys(backend)[0], 0)
    assert backend.setPositionFromTelemetry()
    assert backend.rows[0]["distance"] == 1234.57
    assert not backend.setPositionFromMap()  # no map loaded
    write_map(cfg.path.track_map)
    backend.trackMap.load_map(cfg.path.track_map, "Ring")
    wait_jobs(backend.trackMap)
    backend.trackMap.setPosition(300)
    assert backend.setPositionFromMap() and backend.rows[0]["distance"] == 300
    assert [mark["key"] for mark in backend.marks] == keys(backend)  # place on map
    backend.setValue(keys(backend)[0], "distance", "5000")  # off map: no mark
    assert backend.marks == []
    backend.setValue(keys(backend)[0], "distance", "50")
    backend.setMarksShown(False)
    assert backend.marks == [] and not backend.marksShown
    backend.setMarksShown(True)
    assert len(backend.marks) == 1
    backend.showOnMap()
    assert backend.trackMap.position == 50


def test_map_of_notes_name_loaded(dialogs, monkeypatch):
    from neopedal.api_control import api
    from neopedal.ui.track_notes_editor import TrackNotesEditor

    write_map(cfg.path.track_map, "Spa")
    monkeypatch.setattr(api.read.session, "track_name", lambda: "Spa", raising=False)
    page = TrackNotesEditor(None)
    try:
        wait_jobs(page.backend.trackMap)
        assert page.backend.fileName == "Spa" and page.backend.trackMap.mapName == "Spa"
    finally:
        page.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- Notes file changed by another editor (lap viewer track notes): never silently overwritten
def opened_track_notes(backend, folder):
    path = os.path.join(folder, "Atlanta.tptn")
    save_notes_file(f"{folder}/", "Atlanta.tptn", HEADER_TRACK_NOTES,
                    [{"distance": 300.0, "track note": "Brake", "comment": "", "tags": ""}], create_notes_metadata())
    assert backend.load_file(path, "Track Notes")
    return path


def read_text(path) -> str:
    with open(path, encoding="utf-8") as file:
        return file.read()


def touch_later(path, text="900,Kerb,,\r\n"):
    with open(path, "a", encoding="utf-8", newline="") as file:
        file.write(text)
    os.utime(path, (os.path.getmtime(path) + 5,) * 2)


def test_editor_reads_again_or_asks_before_replacing(editor, monkeypatch):
    backend = editor.backend
    path = opened_track_notes(backend, cfg.path.track_notes.rstrip("/"))
    backend.page_shown()
    touch_later(path)
    backend.check_disk()  # nothing edited here: read again
    assert texts(backend) == ["Brake", "Kerb"] and not backend.diskChangedWarning
    backend.setValue(keys(backend)[0], "note", "Brake late")
    touch_later(path, "1200,Hairpin,,\r\n")
    backend.check_disk()  # edited here: warned, nothing lost
    assert backend.diskChangedWarning and texts(backend) == ["Brake late", "Kerb"]
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *args, **kwargs: asked.append(args[2]) or QMessageBox.StandardButton.Cancel))
    assert not backend.save()  # replace refused: file left as the other editor wrote it
    assert asked and "changed by another editor" in asked[-1]
    assert "Hairpin" in read_text(path)
    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    assert backend.save() and not backend.diskChangedWarning
    assert "Hairpin" not in read_text(path)


def test_editor_change_seen_while_hidden_checked_when_shown(editor):
    backend = editor.backend
    path = opened_track_notes(backend, cfg.path.track_notes.rstrip("/"))
    backend.page_hidden()
    touch_later(path)
    backend.file_touched(path)  # hidden: checked once shown
    assert texts(backend) == ["Brake"]
    backend.page_shown()
    assert texts(backend) == ["Brake", "Kerb"]


def test_lap_viewer_notes_merge_changes_of_editor(ui_env):
    """Lap viewer track notes: a file changed by the editor since read is read again before a note is saved, the
    note added or changed in it (other notes kept)"""
    from neopedal.ui.quick import lap_track_notes

    path = lap_track_notes.notes_path("Atlanta")
    save_notes_file(cfg.path.track_notes, "Atlanta.tptn", HEADER_TRACK_NOTES,
                    [{"distance": 300.0, "track note": "Brake", "comment": "", "tags": ""}], create_notes_metadata())

    from types import SimpleNamespace

    from PySide6.QtCore import QObject, Signal

    class Page(QObject):
        chartChanged = Signal()
        mapDataChanged = Signal()
        mapCornersChanged = Signal()
        data = SimpleNamespace(reference=None)

        def __init__(self):
            super().__init__()
            self.status = []

        def reference_map_line(self):
            return None

        def set_status(self, text, transient=True):
            self.status.append(text)

    page = Page()
    notes = lap_track_notes.TrackNotes(page)
    notes.read("Atlanta")
    original = notes._notes[0]
    touch_later(path)  # editor added a note meanwhile
    assert notes.update(lambda current: [*current, {"distance": 600.0, "track note": "Turn in", "comment": "",
                                                    "tags": ""}])
    saved, _ = load_notes_file(cfg.path.track_notes, "Atlanta", HEADER_TRACK_NOTES, extension=".tptn")
    assert [note["track note"] for note in saved] == ["Brake", "Turn in", "Kerb"]
    touch_later(path, "1200,Hairpin,,\r\n")
    assert notes.update(lap_track_notes.replace_note(original, "Brake late"))  # note found again by content
    saved, _ = load_notes_file(cfg.path.track_notes, "Atlanta", HEADER_TRACK_NOTES, extension=".tptn")
    assert [note["track note"] for note in saved] == ["Brake late", "Turn in", "Kerb", "Hairpin"]
    # Note removed by the editor meanwhile: nothing written, told
    gone = notes._notes[0]
    save_notes_file(cfg.path.track_notes, "Atlanta.tptn", HEADER_TRACK_NOTES,
                    [{"distance": 900.0, "track note": "Kerb", "comment": "", "tags": ""}], create_notes_metadata())
    os.utime(path, (os.path.getmtime(path) + 10,) * 2)
    assert not notes.update(lap_track_notes.replace_note(gone, "Again"))
    assert page.status
    saved, _ = load_notes_file(cfg.path.track_notes, "Atlanta", HEADER_TRACK_NOTES, extension=".tptn")
    assert [note["track note"] for note in saved] == ["Kerb"]


def test_labels_translated_without_key_lookup(editor, monkeypatch):
    i18n.set_language("Français")
    try:
        backend = editor.backend
        backend.create("Pace Notes")
        assert backend.columnLabels == ["Distance", "Note de pilotage", "Commentaire", "Étiquettes"]
        assert "notes de pilotage" in backend.statusText
        assert backend.namePlaceholder == "Nom des notes de pilotage"
        assert [column["label"] for column in backend.textColumns] == ["Note de pilotage", "Commentaire"]
        assert [column["key"] for column in backend.textColumns] == ["note", "comment"]  # keys, never untr
        assert {field["label"] for field in backend.metadataFields} == {"Titre :", "Auteur :", "Date :",
                                                                        "Description :"}
    finally:
        i18n.set_language("English")
    from neopedal.ui import track_notes_editor

    assert "untr" not in read_text(track_notes_editor.__file__)


def test_page_in_app_window_saves_and_closes(dialogs, monkeypatch, tmp_path):
    """Opened from Tools as a page of the app window: Ctrl+S saves it, unsaved changes keep it open on Cancel,
    closed (and removed) once discarded"""
    from neopedal.ui import app as app_module
    from neopedal.ui.tools_view import open_tool

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    window = app_module.AppWindow()
    try:
        window.show()
        open_tool("track_notes_editor.TrackNotesEditor", window)
        view = window.centralWidget()
        page = view.find_dialog_page("TrackNotesEditor")
        assert page is not None
        editor = page.dialog
        editor.backend.setValue(editor.backend.rows[0]["key"], "note", "R3")
        assert page.is_modified()
        asked = save_to(monkeypatch, tmp_path / "Spa.tppn")
        assert window.save_current_page() and len(asked) == 1 and not editor.is_modified()
        editor.backend.setValue(editor.backend.rows[0]["key"], "note", "R4")
        answer(monkeypatch, QMessageBox.StandardButton.Cancel)
        assert not editor.close() and view.find_dialog_page("TrackNotesEditor") is not None
        answer(monkeypatch, QMessageBox.StandardButton.Discard)
        assert editor.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        assert view.find_dialog_page("TrackNotesEditor") is None
    finally:
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()


def test_registry_entry_opens_page(dialogs):
    from neopedal.template.page_registry import page_spec

    module_name, class_name = page_spec("track_notes_editor").dialog.split(".")
    module = __import__(f"neopedal.ui.{module_name}", fromlist=[class_name])
    page = getattr(module, class_name)(None)
    try:
        assert page.view.rootObject() is not None
    finally:
        page.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
