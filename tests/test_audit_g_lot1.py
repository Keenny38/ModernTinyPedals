"""Audit 2026-10-13 lot 1: page shortcuts while hidden, Esc page release, uncaught exceptions logged,
closed dialogs not kept"""

import logging
import re
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

QML_FOLDER = Path(__file__).resolve().parents[1] / "neopedal" / "ui" / "qml"


def shortcut_blocks(text: str) -> list[str]:
    """Text of each Shortcut { ... } block"""
    blocks = []
    for match in re.finditer(r"\bShortcut\s*\{", text):
        depth, index = 0, match.end() - 1
        while index < len(text):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        blocks.append(text[match.start():index + 1])
    return blocks


def test_qml_shortcuts_only_while_page_shown():
    """Window shortcuts of a hidden page (other page shown) fire too: every QML Shortcut needs the page shown"""
    found = 0
    for path in QML_FOLDER.rglob("*.qml"):
        text = path.read_text(encoding="utf-8")
        for block in shortcut_blocks(text):
            found += 1
            enabled = re.search(r"enabled:\s*([^;\n]+)", block)
            assert enabled, f"{path.name}: Shortcut without enabled: {block}"
            condition = enabled.group(1)
            assert "pageState.active" in condition or "page.keys" in condition, f"{path.name}: {block}"
        if "page.keys" in text:
            assert re.search(r"property bool keys:\s*pageState\.active", text), path.name
    assert found >= 7  # F5 of results & replays page: dialog shortcut (both backends)


class _Page:
    """BaseDialog subclass counting released pages"""

    @staticmethod
    def make():
        from neopedal.ui._common import BaseDialog

        class Page(BaseDialog):
            EMBED_IN_APP = False
            freed = 0

            def free_page(self):
                type(self).freed += 1

            def closeEvent(self, event):
                self.release_page()
                super().closeEvent(event)

        return Page


def flush_deletes():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def test_escape_releases_page_once(ui_env):
    """Esc: QDialog.done() closes & deletes without closeEvent (Qt >= 6.3), page released all the same"""
    page_type = _Page.make()
    dialog = page_type(None)
    dialog.show()
    QApplication.sendEvent(dialog, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert dialog.isHidden()
    assert page_type.freed == 1
    flush_deletes()
    assert page_type.freed == 1


def test_close_releases_page_once(ui_env):
    page_type = _Page.make()
    dialog = page_type(None)
    dialog.show()
    assert dialog.close()
    assert page_type.freed == 1  # closeEvent, then QDialog.closeEvent reject(): not freed twice
    flush_deletes()


class _Recorder:
    """Fake backend: release & every other call recorded in a list shared with the fake view"""

    def __init__(self, name: str, calls: list[str]):
        self.name, self.calls = name, calls

    def release(self):
        self.calls.append(self.name)

    def __getattr__(self, name):  # page_shown, page_hidden, tab... of the real page: no-op
        return lambda *args, **kwargs: None


def fake_page(page_type, calls: list[str]):
    """Page of page_type built without its own __init__: fake QML view & backends recording into calls"""
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui._common import BaseDialog

    class View(QQuickWidget):
        def setSource(self, url):
            calls.append("view" if url.isEmpty() else url.toString())

    page = page_type.__new__(page_type)
    BaseDialog.__init__(page, None)
    page.view = View()  # no parent: kept until the end of the test
    page.backend = _Recorder("backend", calls)
    page.replays = _Recorder("replays", calls)
    page._replays_active = False
    return page


def test_quick_pages_free_view_before_backend(ui_env):
    """Pages with a QML view free it before its backends (bindings never read a released backend), once, on
    close & Esc alike"""
    from neopedal.ui import broadcast_director, driver_stats_viewer, lap_viewer, race_results_viewer
    from neopedal.ui._common import BaseDialog

    for entry in (race_results_viewer.RaceResultsViewer, driver_stats_viewer.DriverStatsViewer,
                  broadcast_director.BroadcastDirector, lap_viewer.LapViewer):
        page_type = entry if isinstance(entry, type) else next(  # singleton_dialog wrapper
            cell.cell_contents for cell in entry.__closure__ if isinstance(cell.cell_contents, type))
        name = page_type.__name__
        assert "reject" not in vars(page_type), name  # BaseDialog.reject releases the page (Esc)
        if name in ("DriverStatsViewer", "BroadcastDirector"):
            assert "free_page" not in vars(page_type), name  # BaseDialog.free_page
        for closing in ("close", "escape"):
            calls: list[str] = []
            page = fake_page(page_type, calls)
            view = page.view
            BaseDialog.show(page)
            if closing == "close":
                assert page.close()
            else:
                QApplication.sendEvent(
                    page, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            assert page.isHidden(), (name, closing)
            flush_deletes()  # deleted page: nothing released again
            if name == "RaceResultsViewer":  # two backends: QML unloaded first
                assert calls[:1] == ["view"] and sorted(calls[1:]) == ["backend", "replays"], (closing, calls)
            elif name == "LapViewer":
                assert sorted(calls) == ["backend", "view"], (closing, calls)
            else:  # BaseDialog.free_page: QML unloaded, then backend released
                assert calls == ["view", "backend"], (name, closing, calls)
            view.deleteLater()


def test_uncaught_exceptions_logged(caplog):
    from neopedal.log_handler import install_exception_hooks

    logger = logging.getLogger("neopedal.test_hooks")
    saved = sys.excepthook, threading.excepthook
    try:
        install_exception_hooks(logger)
        with caplog.at_level(logging.CRITICAL, logger="neopedal.test_hooks"):
            try:
                raise ValueError("slot failed")
            except ValueError:
                sys.excepthook(*sys.exc_info())

            def crash():
                raise RuntimeError("thread failed")

            thread = threading.Thread(target=crash, name="crasher")
            thread.start()
            thread.join()
        messages = [record.getMessage() for record in caplog.records]
        assert "Uncaught exception" in messages
        assert "Uncaught exception in thread crasher" in messages
        assert any(record.exc_info and record.exc_info[0] is RuntimeError for record in caplog.records)
    finally:
        sys.excepthook, threading.excepthook = saved


def test_deleted_dialogs_not_kept(ui_env):
    """Closed (deleted) dialogs forgotten: no page data kept after close"""
    from neopedal.ui._common import DialogSingleton

    page_type = _Page.make()
    dialogs = [page_type(None) for _ in range(3)]
    for dialog in dialogs:
        DialogSingleton.register("audit_test", dialog)
    assert len(DialogSingleton._registered["audit_test"]) == 3
    for dialog in dialogs[:2]:
        dialog.deleteLater()
    flush_deletes()
    assert DialogSingleton._registered["audit_test"] == [dialogs[2]]
    dialogs[2].deleteLater()
    flush_deletes()
    assert DialogSingleton._registered["audit_test"] == []
    del DialogSingleton._registered["audit_test"]


def test_auto_recording_retried_while_previous_closing(monkeypatch):
    """Previous recording still closing its file: automatic recording tried again soon, not next driving"""
    from neopedal import replay_session
    from neopedal.replay import replay

    starts = []
    closing = [True]
    monkeypatch.setattr(replay_session, "api_supported", lambda: True)
    monkeypatch.setattr(type(replay), "recording", property(lambda self: False))
    monkeypatch.setattr(type(replay), "active", property(lambda self: False))
    monkeypatch.setattr(type(replay), "recording_closing", property(lambda self: closing[0]))
    monkeypatch.setattr(replay_session, "start_api_recording", lambda auto=False: starts.append(auto) or "")
    auto = replay_session.AutoReplay(keep=2)
    auto.update(True, 1.0)
    assert starts == [True] and not auto.user_stopped
    auto.update(True, 2.0)
    assert len(starts) == 1  # waits for the closing recorder
    closing[0] = False
    auto.update(True, 1.0 + replay_session.CLOSING_RETRY_DELAY)
    assert len(starts) == 2


def test_recording_closing_follows_closing_thread():
    from neopedal.replay import replay

    assert replay.recording_closing is False
    event = threading.Event()
    thread = threading.Thread(target=event.wait)
    thread.start()
    replay._rec_closing = thread
    try:
        assert replay.recording_closing is True
    finally:
        event.set()
        thread.join()
    assert replay.recording_closing is False
    replay._rec_closing = None
