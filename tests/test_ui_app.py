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


def test_tool_paths_resolve():
    """Every lazily imported tool dialog exists"""
    from importlib import import_module

    from tinypedal.ui.tools_view import TOOL_SECTIONS

    for _, tools in TOOL_SECTIONS:
        for _, _, dialog_path in tools:
            module_name, class_name = dialog_path.rsplit(".", 1)
            assert hasattr(import_module(f"tinypedal.ui.{module_name}"), class_name), dialog_path


def test_system_color_theme(ui_env):
    from tinypedal.ui import resolve_color_theme

    assert resolve_color_theme("Dark") == "Dark"
    assert resolve_color_theme("Light") == "Light"
    assert resolve_color_theme("System") in ("Dark", "Light")


def test_command_palette(ui_env, monkeypatch):
    from tinypedal.ui import app as app_module
    from tinypedal.ui.command_palette import CommandPalette, match_commands

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    window = app_module.AppWindow()
    try:
        palette = CommandPalette(window)
        titles = [command.title for command in palette.commands]
        assert "Fuel Calculator" in titles and "Tools" in titles
        # Accent & case insensitive, words in any order
        assert match_commands(palette.commands, "calculator FUEL")[0].title == "Fuel Calculator"
        palette.edit_search.setText("hotkey")
        assert palette.list_results.count() >= 1
        palette.edit_search.setText("font color speed")  # options found too
        assert any("\u2192" in palette.list_results.item(row).text() for row in range(palette.list_results.count()))
        palette.edit_search.setText("Tools")
        palette.run_selected()  # first match is the page
        assert window.centralWidget().current_index() == app_module.PAGE_INDEX["tools"]
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


def test_widget_categories(ui_env):
    from tinypedal.module_control import wctrl
    from tinypedal.template.setting_widget import WIDGET_FILENAME
    from tinypedal.ui.module_view import CATEGORY_OTHER, ModuleList, widget_category

    assert widget_category("tyre_pressure") == "Tyres & Wheels"
    assert widget_category("brake_wear") == "Brakes"
    assert widget_category("plugin_xyz") == CATEGORY_OTHER
    others = [name for name in WIDGET_FILENAME if widget_category(name) == CATEGORY_OTHER]
    assert len(others) <= 3  # new built-in widgets belong to a category
    view = ModuleList(None, wctrl)
    view.category_box.setCurrentIndex(view.category_box.findData("Brakes"))
    shown = [name for name, item in view.items.items() if not item.isHidden()]
    assert shown and all(name.startswith("brake_") for name in shown)
    view.deleteLater()


def test_toast(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.toast import show_toast

    window = QWidget()
    window.resize(400, 300)
    toast = show_toast(window, "Saved <b>file</b>", duration=10)
    assert toast is not None and toast.parentWidget() is window
    assert toast.y() + toast.height() <= window.height()
    assert show_toast(None, "nothing") is None
    window.deleteLater()
    QCoreApplication.processEvents()


def test_file_drop(ui_env, tmp_path):
    import json
    import os
    import zipfile

    import pytest

    from tinypedal.ui import file_drop

    preset = tmp_path / "My Preset.json"
    preset.write_text(json.dumps({"speedometer": {"enable": True}}), encoding="utf-8")
    assert file_drop.classify(str(preset)) == file_drop.DROP_PRESET
    folder = cfg.path.settings
    assert file_drop.import_preset_file(str(preset), folder) == "My Preset.json"
    assert file_drop.import_preset_file(str(preset), folder) == "My Preset (2).json"  # never overwrite
    assert os.path.exists(os.path.join(folder, "My Preset (2).json"))
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        file_drop.import_preset_file(str(bad), folder)
    plugin = tmp_path / "plugin.zip"
    with zipfile.ZipFile(plugin, "w") as package:
        package.writestr("plugin_x/widget.py", "")
        package.writestr("plugin_x/setting.json", "{}")
    assert file_drop.classify(str(plugin)) == file_drop.DROP_PLUGIN
    package_zip = tmp_path / "package.zip"
    with zipfile.ZipFile(package_zip, "w") as package:
        package.writestr("manifest.json", "{}")
    assert file_drop.classify(str(package_zip)) == file_drop.DROP_PACKAGE
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as package:
        package.writestr("readme.txt", "")
    assert file_drop.classify(str(other)) == ""
