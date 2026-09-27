"""Main window tests (headless): build, live language switch"""

from contextlib import suppress

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QSystemTrayIcon

from tinypedal import app_signal
from tinypedal.i18n import current_language, set_language
from tinypedal.setting import cfg


def menu_titles(window):
    return [action.text() for action in window.menuBar().actions()]


def test_live_language_switch(ui_env, monkeypatch):
    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["language"] = "English"
    set_language("English")
    window = app_module.AppWindow()
    try:
        assert "Config" in menu_titles(window)
        window.centralWidget().set_current_index(2)
        cfg.application["language"] = "Français"
        app_signal.refresh.emit(True)
        QCoreApplication.processEvents()  # rebuild is deferred
        assert current_language() == "fr"
        titles = menu_titles(window)
        assert "Config" not in titles and "Aide" in titles
        assert window.centralWidget().current_index() == 2  # same tab kept
        # Refresh signal still works after rebuild (old widgets disconnected)
        app_signal.refresh.emit(True)
        QCoreApplication.processEvents()
        cfg.application["language"] = "English"
        app_signal.refresh.emit(True)
        QCoreApplication.processEvents()
        assert "Help" in menu_titles(window)
    finally:
        set_language("English")
        tray = window.findChild(QSystemTrayIcon)
        if tray:
            tray.hide()
        for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
            with suppress(RuntimeError, TypeError):
                signal.disconnect()
        window.deleteLater()
        QCoreApplication.processEvents()
