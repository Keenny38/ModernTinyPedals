"""UI/UX audit 2026-10-29, telemetry zone, wave 2: shared components adopted (TpTransportButton in the playback bar,
dialogs & toasts of backends in the page through TpDialogHost, menus under their buttons with toggleBelow, text roles)"""

import os

import pytest
from PySide6.QtWidgets import QMessageBox

from neopedal.ui.quick import qml_path
from neopedal.ui.quick.dialogs import page_bridge
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import find, named, opener, wait, warnings  # noqa: F401

PAGES = ("LapViewer", "TrackMapViewer", "TrackNotesEditor", "SessionRecorder")


def source(name: str) -> str:
    with open(qml_path(name + ".qml"), encoding="utf-8") as file:
        return file.read()


@pytest.fixture
def asked_in_page(monkeypatch):
    """Questions not answered by the test: the page's own dialog answers them"""
    from neopedal.ui._common import ORIGINAL_DIALOG_METHODS

    monkeypatch.setattr(QMessageBox, "question", ORIGINAL_DIALOG_METHODS["question"])


# --- Static: one transport look, one dialog host per page, menus under their buttons
def test_playback_bar_uses_shared_transport_buttons():
    text = source("PlaybackBar")
    assert "TpTransportButton {" in text and "TpButton {\n        objectName: \"playButton\"" not in text
    assert text.count("TpTransportButton {") == 6  # frames, back, play, forward, loop
    assert "primary: true" in text and "current: bar.loop" in text


def test_pages_host_backend_dialogs_and_toasts():
    for name in PAGES:
        text = source(name)
        assert text.rstrip().endswith("}") and "TpDialogHost {" in text, name
        assert "TpToast {" not in text, name  # page toast of the host only
    for name in ("LapViewer", "TrackNotesEditor", "TrackMapViewer", "TrackMap"):
        text = source(name)
        assert "popup(source, 0, source.height" not in text and ".height + theme.space1)" not in text, name


def test_backends_ask_through_page_dialogs():
    root = os.path.join(os.path.dirname(qml_path("LapViewer.qml")), "..", "..", "quick")
    for name in ("lap_actions", "lap_export", "lap_track_notes", "track_map_backend"):
        with open(os.path.join(root, name + ".py"), encoding="utf-8") as file:
            text = file.read()
        assert "TextInputDialog" not in text and "confirm_action" not in text and "QMessageBox" not in text, name


# --- Lap viewer: lap note, delete confirmation & trashed laps toast in the page
def test_lap_note_asked_in_page(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    path = backend.entries[0].file.path
    backend.editNote(path)
    wait(0.2)
    bridge = page_bridge(dialog)
    assert bridge is not None and bridge.current["kind"] == "text"  # TpDialogHost dialog, not a page swap
    assert not [widget for widget in dialog.window().findChildren(QMessageBox) if widget.isVisible()]
    bridge.answer(bridge.current["id"], True, "Late on brakes")
    wait(0.2)
    assert backend.lap_marks(path).get("note") == "Late on brakes" and bridge.current["id"] == 0


def test_delete_laps_at_once_with_undo_in_page(opener, warnings, asked_in_page):  # noqa: F811
    """Laps go to the app trash (undoable): never confirmed, however many; one toast with Undo, no status line"""
    dialog = opener()
    backend = dialog.backend
    paths = [entry.file.path for entry in backend.entries[:2]]
    backend.deleteLaps(paths)
    wait(0.4)
    bridge = page_bridge(dialog)
    assert bridge.current["id"] == 0  # nothing asked
    assert not any(os.path.exists(path) for path in paths) and backend.undoText != ""
    assert "trash" not in backend.status  # told once: the toast
    toast = named(dialog.view, "bridgeToast")  # page toast: count told, Undo restores them
    assert toast.property("shown") and "2" in toast.property("text") and toast.property("actionText") == "Undo"
    bridge.toastAction()
    wait(0.4)
    assert all(os.path.exists(path) for path in paths) and backend.undoText == ""
    assert "restored" in toast.property("text") and "restored" not in backend.status


def test_track_note_asked_in_page(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    backend.trackNotes.ask("Note", "", lambda text: True)
    wait(0.2)
    bridge = page_bridge(dialog)
    assert bridge.current["kind"] == "text" and bridge.current["title"] == "Track Note"
    bridge.answer(bridge.current["id"], False)


# --- Track Map Viewer: map errors in the page
def test_missing_map_told_in_page(ui_env, tmp_path):
    from neopedal.ui.track_map_viewer import TrackMapViewer

    page = TrackMapViewer(None)
    page.resize(1000, 700)
    page.show()
    wait(0.4)
    try:
        assert not page.backend.load_map(str(tmp_path) + "/", "Nowhere")
        bridge = page_bridge(page)
        assert bridge.current["kind"] == "alert" and "Nowhere" in bridge.current["text"]
        bridge.answer(bridge.current["id"], True)
    finally:
        page.close()


# --- Session recorder & track notes editor: page toasts of the host
def test_recorder_messages_in_host_toast(ui_env):
    from neopedal.ui import replay_view

    dialog = replay_view.ReplayView(None)
    dialog.resize(1100, 700)
    dialog.show()
    wait(0.4)
    try:
        dialog.backend.show_message("Choose <another> name", True)
        wait(0.2)
        toast = named(dialog.view, "bridgeToast")
        assert toast.property("shown") and toast.property("level") == "error"
        assert "&lt;another&gt;" in toast.property("text")  # plain text escaped (toast reads markup)
    finally:
        dialog.close()


def test_notes_editor_toast_undo_and_replace_asked_in_page(ui_env, tmp_path, asked_in_page):
    from neopedal.ui.track_notes_editor import TrackNotesEditor

    page = TrackNotesEditor(None)
    page.resize(1100, 700)
    page.show()
    wait(0.4)
    backend = page.backend
    try:
        backend.addRow()
        before = len(backend.rows)
        backend.selectAll()
        backend.deleteSelected()
        wait(0.2)
        toast = named(page.view, "bridgeToast")
        assert toast.property("shown") and toast.property("actionText") == "Undo"
        page_bridge(page).toastAction()
        wait(0.2)
        assert len(backend.rows) == before  # Undo of the toast restores the notes
        target = tmp_path / "Ring.tppn"
        target.write_text("", encoding="utf-8")
        assert not backend.confirm_replace(str(target), "Replace it?")  # asked in the page, nothing written yet
        bridge = page_bridge(page)
        assert bridge.current["kind"] == "confirm" and bridge.current["acceptText"] == "Replace"
        bridge.answer(bridge.current["id"], True)
        wait(0.2)
        assert target.read_text(encoding="utf-8") != ""
    finally:
        page.set_unmodified()
        page.close()
