"""UI backends audit fixes (package G): director feed at its limit, stats selection while arrow key held,
settings page opened twice, float option limits, log auto refresh, MoTeC drop import, reset data error,
PDF report on locked file, track map load failure, layout editor screen capture"""

import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QMessageBox, QWidget

from neopedal.process import director as dr
from neopedal.setting import cfg
from tests.test_audit_c_app import answers, flush_deleted  # noqa: F401  (fixture)
from tests.test_audit_c_app import window as app_window  # noqa: F401  (fixture: main window)
from tests.test_broadcast_director import director_page  # noqa: F401  (fixture)
from tests.test_driver_stats_viewer import backend, dialogs, page, settle, window  # noqa: F401  (fixtures)


# Point 7: feed made again when an older event comes at the feed limit
def contact(index: int, time: float) -> dr.Event:
    return dr.Event(f"contact|{index}", dr.CONTACT, time, (1, 2), ("A", "B"), "GT3")


def test_feed_rebuilt_at_limit_with_older_event(director_page):  # noqa: F811
    director = director_page.backend
    director.add_events([contact(index, 100.0 + index) for index in range(dr.FEED_LIMIT)])
    assert director._feed_model.rowCount() == dr.FEED_LIMIT
    last_key = director.events[-1].key
    director.add_events([contact(9999, 50.0)])  # contact told late: older than every event kept
    assert len(director.events) == dr.FEED_LIMIT and director.events[-1].key == last_key  # same size & last key
    keys = [row["key"] for row in director._feed_model.rows]
    assert "contact|9999" in keys and len(keys) == dr.FEED_LIMIT
    assert sum(1 for row in director._feed_model.rows if row["unseen"]) == director._unseen
    revision = director._events_revision
    director.add_events([contact(9999, 50.0)])  # known event: nothing changed
    assert director._events_revision == revision
    director.new_session()
    assert director._feed_model.rowCount() == 0


# Point 14: selected row told at once while arrow key held (details only once it settles)
def test_selected_key_told_during_keyboard_burst(backend):  # noqa: F811
    keys = backend.row_keys()
    assert len(keys) >= 2
    backend.selectRow(keys[0])
    told, details = [], []
    backend.selectedKeyChanged.connect(lambda: told.append(backend.selectedKey))
    backend.selectionChanged.connect(lambda: details.append(True))
    backend.moveSelection(1)  # first key press: details at once
    backend.moveSelection(-1)  # held: burst, details delayed
    assert told == [keys[1], keys[0]] and backend.selectedKey == keys[0]
    assert len(details) == 1 and backend.selection_timer.isActive()
    backend.selection_timer.stop()
    backend.publish_selection()  # timer fired: details of row shown, key unchanged (not told again)
    assert told == [keys[1], keys[0]] and len(details) == 2


def test_stats_table_highlight_follows_burst(page):  # noqa: F811
    settle(page.backend)
    stats = page.backend
    root = page.view.rootObject()
    stack, table = [root], None
    while stack and table is None:
        item = stack.pop()
        if item.property("sortKey") is not None and item.property("selectedKey") is not None:
            table = item
        stack.extend(item.childItems())
    assert table is not None
    keys = stats.row_keys()
    if len(keys) < 2:
        pytest.skip("one row only")
    stats.selectRow(keys[0])
    stats.moveSelection(1)
    stats.moveSelection(-1)  # burst
    assert table.property("selectedKey") == keys[0]  # Enter & Menu key act on this row


# Point 13: settings page opened again: no second page built
def test_settings_opened_twice_builds_one_page(app_window, monkeypatch):  # noqa: F811
    from neopedal.ui import app as app_module
    from neopedal.ui import app_settings

    built = []
    original = app_settings.AppSettings.__init__

    def init(self, parent):
        built.append(self)
        original(self, parent)

    monkeypatch.setattr(app_settings.AppSettings, "__init__", init)
    first = app_settings.open_app_settings(app_window)
    second = app_settings.open_app_settings(app_window, "application")
    assert second is first and len(built) == 1
    # Copy made anyway (opened by other code): its QML unloaded before deleted
    released = []
    monkeypatch.setattr(app_module, "release_quick_views", lambda dialog: released.append(dialog))
    copy = app_settings.AppSettings(app_window)
    copy.open()
    assert released == [copy] and copy.shown_dialog() is first
    flush_deleted()


# Point 30: float option never infinite
def test_float_edit_rejects_infinite(ui_env):
    from neopedal.ui._option import FloatEdit

    edit = FloatEdit(None)
    try:
        for text in ("1e999", "-1e999", "nan", "inf"):
            edit.setText(text)
            assert edit.validate() is None and edit.invalid_reason() == "Number required", text
        edit.setText("2.5")
        assert edit.validate() == 2.5
        edit.setText("3.0")
        assert edit.validate() == 3 and isinstance(edit.validate(), int)
    finally:
        edit.deleteLater()
        flush_deleted()


# Point 31: log auto refresh adds new text only
def test_log_auto_refresh_appends_tail(ui_env, monkeypatch):
    from neopedal.log_handler import BoundedLogStream
    from neopedal.ui import log_info

    stream = BoundedLogStream(max_chars=200)
    monkeypatch.setattr(log_info, "log_stream", stream)
    stream.write("first line\n")
    dialog = log_info.LogInfo(None)
    try:
        view = dialog.log_view
        assert view.toPlainText() == "first line\n"
        replaced = []
        original = view.setPlainText
        def set_text(text):
            replaced.append(text)
            original(text)

        monkeypatch.setattr(view, "setPlainText", set_text)
        stream.write("second line\n")
        dialog.append_log()
        assert view.toPlainText() == stream.getvalue() and not replaced  # appended
        dialog.append_log()  # nothing new
        assert view.toPlainText() == stream.getvalue() and not replaced
        for index in range(60):  # old lines dropped by stream: view rebuilt once twice the limit
            stream.write(f"line {index:03d}\n")
            dialog.append_log()
        assert replaced and view.toPlainText().endswith(stream.getvalue())
        assert len(view.toPlainText()) <= 2 * stream.max_chars
        monkeypatch.setattr(type(dialog), "confirm_operation", lambda self, *args, **kwargs: True)
        dialog.clear_log()  # log cleared, then written: new text shown alone
        stream.write("after clear\n")
        dialog.append_log()
        assert view.toPlainText() == "after clear\n"
    finally:
        dialog.close()
        flush_deleted()


# Point 32: MoTeC drop without lap viewer: memory error reported
def test_motec_drop_fallback_memory_error(ui_env, monkeypatch, tmp_path):
    from neopedal.ui import lap_viewer, tools_view

    log = tmp_path / "huge.ld"
    log.write_bytes(b"x")
    monkeypatch.setattr(tools_view, "open_tool", lambda *args: None)

    def huge(*args):
        raise MemoryError

    monkeypatch.setattr(lap_viewer, "import_ld_file", huge)
    host = QWidget()
    try:
        message = lap_viewer.import_motec_log(host, str(log))
        assert "Unable to import" in message and "MemoryError" in message
    finally:
        host.deleteLater()
        flush_deleted()


# Point 33: reset data file that cannot be deleted
def test_reset_data_delete_error(ui_env, monkeypatch, tmp_path, answers):  # noqa: F811
    from neopedal.ui import menu

    (tmp_path / "Spa.svg").write_text("x", encoding="utf-8")
    answers.reply = QMessageBox.StandardButton.Yes

    def locked(path):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(menu.os, "remove", locked)
    reset = menu.ResetDataMenu("Reset", None)
    try:
        done = reset._ResetDataMenu__confirmation(  # type: ignore[attr-defined]
            data_type="track map", extension="svg", filepath=f"{tmp_path}{os.sep}", filename="Spa")
        assert done is False
        assert answers.warnings and "Unable to reset" in answers.warnings[0] and "Permission denied" in answers.warnings[0]
    finally:
        reset.deleteLater()
        flush_deleted()


# Point 34: PDF report written to temporary file, moved in place
def test_pdf_report_locked_target(ui_env, monkeypatch, tmp_path):
    from neopedal.ui.quick import lap_export

    document = QTextDocument()
    document.setHtml("<h1>Corners</h1><p>Report</p>")
    folder = tmp_path / "reports"
    folder.mkdir()
    target = folder / "report.pdf"
    lap_export.write_pdf(document, str(target))
    assert target.read_bytes().startswith(b"%PDF") and os.listdir(folder) == ["report.pdf"]
    target.write_bytes(b"old")

    def locked(source, destination):
        raise PermissionError(13, "Permission denied", destination)

    monkeypatch.setattr(lap_export.os, "replace", locked)
    with pytest.raises(OSError):
        lap_export.write_pdf(document, str(target))
    assert target.read_bytes() == b"old" and os.listdir(folder) == ["report.pdf"]  # temporary file removed


# Point 35: track map file not loaded: nothing drawn
def test_track_map_load_failure_clears_map(ui_env, monkeypatch):
    from neopedal.ui import track_map_widget
    from tests.test_track_map_viewer import write_map

    write_map(cfg.path.track_map)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    parent = QWidget()
    view = track_map_widget.MapView(parent)
    view.resize(400, 300)
    try:
        view.load_trackmap(cfg.path.track_map, "Ring")
        assert view.raw_coords and view.map_path is not None
        monkeypatch.setattr(track_map_widget, "load_track_map_file",
                            lambda **kwargs: ([(0.0, 0.0)] * 5, [(0.0, 0.0)] * 5, [0, 0]))
        view.load_trackmap(cfg.path.track_map, "Ring")  # too few points
        assert view.raw_coords is None and view.raw_dists is None and view.map_path is None
        assert view.map_nodes == 0
        assert not view.grab().isNull()  # painted without map
    finally:
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# Point 60: screen captured once window is gone from screen
def test_capture_waits_then_shows_window(ui_env, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from neopedal.ui import layout_editor

    monkeypatch.setattr(layout_editor, "CAPTURE_DELAY_MS", 20)
    editor = layout_editor.LayoutEditor(None)
    editor.show()
    screen = QGuiApplication.primaryScreen()
    grabbed = []

    def grab(self, *args):
        grabbed.append(editor.isVisible())
        return QImage()

    monkeypatch.setattr(type(screen), "grabWindow", grab)
    try:
        editor.capture_screen()
        assert grabbed == [False] and editor.isVisible()
    finally:
        editor.close()
        flush_deleted()
