"""Main window tests (headless): build, live language switch, app-wide style"""

from contextlib import suppress

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from tinypedal import app_signal
from tinypedal.i18n import current_language, set_language
from tinypedal.setting import cfg


def menu_titles(window):
    return [action.text() for action in window.menuBar().actions()]


def test_style_applied_at_application_level(ui_env, monkeypatch):
    """Style must be set on QApplication, not just AppWindow, so QMessageBox and other
    Qt-built top-level windows are also styled (they are not visual children of AppWindow)"""
    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    app_instance = QApplication.instance()
    assert app_instance is not None
    app_instance.setStyleSheet("")  # style may already be cached from a previous test
    window = app_module.AppWindow()
    try:
        style = app_instance.styleSheet()
        assert "QPushButton" in style and "QComboBox" in style and "QCheckBox" in style
        assert window.styleSheet() == ""  # not set on the window itself anymore
    finally:
        window.deleteLater()
        QCoreApplication.processEvents()


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


def test_navigation_rail(ui_env, monkeypatch):
    """Tools page, quick toggles & remembered page"""
    import os

    from tinypedal.ui import app as app_module
    from tinypedal.ui.tools_view import TOOL_SECTIONS, ToolCard

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    cfg.application["last_page_index"] = app_module.PAGE_INDEX["tools"]
    window = app_module.AppWindow()
    try:
        view = window.centralWidget()
        assert view.current_index() == app_module.PAGE_INDEX["tools"]  # restored
        cards = view.findChildren(ToolCard)
        assert len(cards) == sum(len(tools) for _, tools in TOOL_SECTIONS)
        if os.environ.get("RAIL_SHOT"):
            window.resize(560, 820)
            window.show()
            QCoreApplication.processEvents()
            window.grab().save(os.environ["RAIL_SHOT"])
        view.select_page(app_module.PAGE_INDEX["preset"])
        assert cfg.application["last_page_index"] == app_module.PAGE_INDEX["preset"]
        lock = view._toggles["fixed_position"]
        state = cfg.overlay["fixed_position"]
        lock.click()
        assert cfg.overlay["fixed_position"] is (not state)
        assert lock.isChecked() is (not state)
    finally:
        cfg.application["last_page_index"] = 0
        tray = window.findChild(QSystemTrayIcon)
        if tray:
            tray.hide()
        for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
            with suppress(RuntimeError, TypeError):
                signal.disconnect()
        window.deleteLater()
        QCoreApplication.processEvents()
