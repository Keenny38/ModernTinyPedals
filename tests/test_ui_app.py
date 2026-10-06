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
    from tinypedal.ui.tools_view import TOOL_SECTIONS, ToolCard, ToolsView

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    cfg.application["last_page_index"] = app_module.PAGE_INDEX["tools"]
    window = app_module.AppWindow()
    try:
        view = window.centralWidget()
        assert view.current_index() == app_module.PAGE_INDEX["tools"]  # restored
        cards = view.findChild(ToolsView).findChildren(ToolCard)  # home page quick access has tool cards too
        assert len(cards) == sum(len(tools) for _, tools in TOOL_SECTIONS)
        if os.environ.get("RAIL_SHOT"):
            window.resize(560, 820)
            window.show()
            QCoreApplication.processEvents()
            window.grab().save(os.environ["RAIL_SHOT"])
            view.set_current_index(app_module.PAGE_INDEX["home"])
            QCoreApplication.processEvents()
            window.grab().save(os.environ["RAIL_SHOT"].replace(".png", "_home.png"))
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


def test_lazy_imported_packages_bundled():
    """PyInstaller only follows static imports: packages imported by name must be collected,
    or their dialogs and widgets are missing from the release build and fail silently"""
    import os

    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "build_pyinstaller.py"), encoding="utf-8") as file:
        build_script = file.read()
    for package in ("tinypedal.ui", "tinypedal.widget", "tinypedal.module"):
        assert f'"--collect-submodules={package}"' in build_script, package


def test_window_color_themes(ui_env):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from tinypedal.ui import palette_theme, resolve_color_theme, set_style_palette

    assert resolve_color_theme("Modern Dark") == resolve_color_theme("Legacy Dark") == "Dark"
    assert resolve_color_theme("Modern Light") == resolve_color_theme("Legacy Light") == "Light"
    windows = {}
    try:
        for theme in ("Modern Dark", "Modern Light", "Legacy Dark", "Legacy Light"):
            set_style_palette(theme)
            assert palette_theme() == resolve_color_theme(theme)
            windows[theme] = QApplication.palette().color(QPalette.ColorRole.Window).name().upper()
    finally:
        set_style_palette("Modern Dark")
    assert windows["Legacy Dark"] == "#202124" and windows["Modern Dark"] == "#111318"  # TinyPedal 2.50 colors
    assert len(set(windows.values())) == 4


def test_app_icon_follows_os_dark_mode(ui_env, monkeypatch):
    """White & gold icon for dark mode, black & gold for light mode, switched live"""
    from PySide6.QtGui import QPixmap

    from tinypedal.const_file import ImageFile
    from tinypedal.ui import app as app_module
    from tinypedal.ui import app_icon_file, system_dark_mode

    assert app_icon_file(False) == ImageFile.APP_ICON
    assert app_icon_file(True) == ImageFile.APP_ICON_DARK
    assert not QPixmap(ImageFile.APP_ICON).isNull()
    assert not QPixmap(ImageFile.APP_ICON_DARK).isNull()
    assert isinstance(system_dark_mode(), bool)

    loaded = []
    monkeypatch.setattr(app_module, "app_icon_file", lambda dark: loaded.append(dark) or app_icon_file(dark))
    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    monkeypatch.setattr(app_module, "system_dark_mode", lambda: False)
    window = app_module.AppWindow()
    try:
        assert loaded == [False]
        monkeypatch.setattr(app_module, "system_dark_mode", lambda: True)
        app_signal.refresh.emit(True)
        app_signal.refresh.emit(True)  # icon only reloaded on mode change
        assert loaded == [False, True]
        tray_icon = window.findChild(QSystemTrayIcon)
        if tray_icon is not None:
            assert tray_icon.icon().cacheKey() == QApplication.windowIcon().cacheKey()
    finally:
        window.deleteLater()
        QCoreApplication.processEvents()


def test_command_palette(ui_env, monkeypatch):
    from tinypedal.ui import app as app_module
    from tinypedal.ui.command_palette import CommandPalette, match_commands

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    window = app_module.AppWindow()
    try:
        palette = CommandPalette(window)
        titles = [command.title for command in palette.commands]
        assert "Race Calculator" in titles and "Tools" in titles
        # Accent & case insensitive, words in any order
        assert match_commands(palette.commands, "calculator RACE")[0].title == "Race Calculator"
        # Former fuel calculator & tyre strategy planner names find the merged tool
        assert match_commands(palette.commands, "fuel calculator")[0].title == "Race Calculator"
        assert match_commands(palette.commands, "stratégie pneus")[0].title == "Race Calculator"
        palette.edit_search.setText("hotkey")
        assert palette.list_results.count() >= 1
        palette.edit_search.setText("font size speed")  # options found too
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


def test_file_drop_rejects_style_and_global_files(ui_env, tmp_path):
    import json

    import pytest

    from tinypedal.ui import file_drop

    classes = tmp_path / "classes.json"
    classes.write_text(json.dumps({"GT3": {"alias": "GT3"}}), encoding="utf-8")
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"something": {"a": 1}}), encoding="utf-8")
    for path in (classes, other):
        with pytest.raises(ValueError):
            file_drop.import_preset_file(str(path), cfg.path.settings)


def test_plugin_manager_status_badges(ui_env, monkeypatch):
    from types import SimpleNamespace

    from tinypedal.plugin_loader import PLUGIN_ERRORS, UNTRUSTED_ERROR
    from tinypedal.ui import plugin_manager

    names = ["plugin_ok", "plugin_bad", "plugin_new", "plugin_unsafe"]
    monkeypatch.setattr(plugin_manager, "discover_plugins", lambda: names)
    monkeypatch.setattr(plugin_manager, "wctrl", SimpleNamespace(names=["plugin_ok", "plugin_bad", "plugin_unsafe"]))
    monkeypatch.setitem(PLUGIN_ERRORS, "plugin_bad", "SyntaxError")
    monkeypatch.setitem(PLUGIN_ERRORS, "plugin_unsafe", UNTRUSTED_ERROR)
    dialog = plugin_manager.PluginManager(None)
    try:
        rows = {dialog.table.item(row, 0).text(): row for row in range(dialog.table.rowCount())}
        badge = {name: dialog.table.item(row, 1).data(plugin_manager.ROLE_BADGE) for name, row in rows.items()}
        colors = plugin_manager.BADGE_COLORS
        assert badge == {"ok": colors["loaded"], "bad": colors["error"], "new": colors["restart"],
                         "unsafe": colors["untrusted"]}
        assert dialog.table.item(rows["ok"], 0).data(plugin_manager.ROLE_BADGE) is None  # name: plain text
        dialog.table.selectRow(rows["bad"])
        assert dialog.selected_name() == "plugin_bad"
        assert dialog.label_detail.text() == "SyntaxError"
        assert not dialog.grab().isNull()  # badges painted
    finally:
        from PySide6.QtCore import QCoreApplication, QEvent

        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # frees single instance dialog
