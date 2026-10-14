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
    for path in QML_FOLDER.glob("*.qml"):
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


def test_quick_pages_free_view_before_backend():
    """Pages with a QML view free it in free_page (closeEvent & Esc), not only in closeEvent"""
    import inspect

    from neopedal.ui import broadcast_director, driver_stats_viewer, lap_viewer, race_results_viewer
    from neopedal.ui._common import BaseDialog

    default = inspect.getsource(BaseDialog.free_page)  # QML view unloaded, then PageBackend.release
    assert default.index("view.setSource(QUrl())") < default.index("release()")
    for module in (race_results_viewer, driver_stats_viewer, broadcast_director, lap_viewer):
        source = inspect.getsource(module)
        if module is race_results_viewer:  # two backends: QML unloaded first
            free_page = source[source.index("    def free_page(self):"):]
            free_page = free_page[:free_page.index("\n\n")]
            assert free_page.index("self.view.setSource(QUrl())") < free_page.index("self.replays.release()")
            assert free_page.index("self.view.setSource(QUrl())") < free_page.index("self.backend.release()")
        elif module is not lap_viewer:
            assert "def free_page(" not in source, module  # BaseDialog.free_page
        else:
            free_page = source[source.index("    def free_page(self):"):]
            free_page = free_page[:free_page.index("\n\n")]
            assert "self.view.setSource(QUrl())" in free_page and "self.backend.release()" in free_page, module
        assert "self.release_page()" in source[source.index("    def closeEvent(self, event):"):], module
        assert "def reject(" not in source, module  # BaseDialog.reject releases the page


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
