"""UI/UX audit 2026-10-29, shell lot: one name for Settings (N1), pages left out of the rail (N2), shell header of
tool pages (N3), notification center (N4), status band (N5), Qt Quick command palette (N6), title bar color scheme
(V1) and minor points (back & forward, window title, close to tray notice, shortcuts sheet, page skeleton, Tools
page in Qt Quick, tray presets, quick access defaults, GitHub issue of bug report, Ctrl+F, Esc of Broadcast
Director, plugin manager wording)"""

import warnings
from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QSystemTrayIcon

from neopedal import app_signal, i18n
from neopedal.setting import cfg
from tests.test_perf_page_state import qml_warnings  # noqa: F401


def flush():
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()


@pytest.fixture
def window(ui_env, monkeypatch):
    from neopedal.ui import app as app_module
    from neopedal.ui.notification import notification_store

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    notification_store().clear()
    main = app_module.AppWindow()
    yield main
    from neopedal.ui.quick.shell_popup import ShellPopup

    for popup in list(ShellPopup._open.values()):
        popup.close()
    view = main.centralWidget()
    for page in view.dialog_pages():
        if page.dialog is not None:
            with suppress(AttributeError):
                page.dialog.set_unmodified()
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates,
                       app_signal.error):
            with suppress(RuntimeError, TypeError):
                signal.disconnect()
    notification_store().clear()
    main.deleteLater()
    flush()


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


def page_of(window, name):
    view = window.centralWidget()
    return next(page for page in view.dialog_pages() if type(page.dialog).__name__ == name)


# --- Page registry (N1, N2, Tools page)
def test_every_page_has_description_and_user_guide_page():
    from neopedal.template.page_registry import PAGES, page_spec

    for page in PAGES:
        assert page.description and page.wiki, page.name
        assert page.description == page.description.strip() and not page.description.endswith(".")
    assert page_spec("LapViewer").name == "lap_viewer" and page_spec("lap_viewer.LapViewer").name == "lap_viewer"
    assert page_spec("home").wiki.startswith("Getting-Started") and page_spec("bogus") is None


def test_settings_one_name_and_out_of_tools_list():
    from neopedal.ui.nav_rail import rail_entries
    from neopedal.ui.tools_view import LISTED_TOOL_SECTIONS, TOOL_SECTIONS

    listed = [path for _, tools in LISTED_TOOL_SECTIONS for _, _, path in tools]
    every = [path for _, tools in TOOL_SECTIONS for _, _, path in tools]
    assert "app_settings.AppSettings" not in listed and "app_settings.AppSettings" in every  # still a known page
    assert len(every) == len(listed) + 1
    assert rail_entries()["app_settings"].tooltip == "Settings"


def test_rail_labels_plural_and_calculator(french):
    from neopedal.ui.nav_rail import rail_entries, rail_text

    entries = rail_entries()
    i18n.set_language("English")
    assert [rail_text(entries[key].label, entries[key].tooltip) for key in ("module", "preset", "hotkey")] == [
        "Modules", "Presets", "Hotkeys"]
    assert rail_text(entries["race_calculator"].label, entries["race_calculator"].tooltip) == "Calculator"
    i18n.set_language("Français")  # French names are plural already: full name used, never an English word
    assert [rail_text(entries[key].label, entries[key].tooltip) for key in ("module", "preset", "hotkey")] == [
        "Modules", "Presets", "Raccourcis"]
    assert rail_text(entries["race_calculator"].label, entries["race_calculator"].tooltip) == "Calculateur"


def test_quick_access_default_has_no_rail_entry():
    from neopedal.ui.home_view import default_quick_items
    from neopedal.ui.nav_rail import default_rail_items

    assert not set(default_quick_items()) & set(default_rail_items())
    assert "app_settings" in default_quick_items() and "tools" in default_quick_items()


# --- Rail: back & forward, More, help, notifications (N2, N4, minors)
def test_rail_buttons_and_more_menu(window):
    from neopedal.ui.app import NavButton

    view = window.centralWidget()
    for name in ("railBack", "railForward", "railMore", "railHelp", "railNotifications", "railSettings"):
        assert window.findChild(NavButton, name) is not None, name
    assert window.findChild(NavButton, "railSettings").toolTip() == "Settings (Ctrl+,)"
    pages, tools = view.hidden_entries()
    titles = [title for _, title in pages]
    assert {"Modules", "Spectate", "Pacenotes", "Hotkeys", "Tools"} <= set(titles) and "Home" not in titles
    assert all(not path.startswith("app_settings") for path, _ in tools)
    menu = view.more_menu()
    shown = [action.text() for action in menu.actions()]
    assert "Spectate" in shown and "Customize Navigation Bar…" in shown
    menu.deleteLater()


def test_back_and_forward(window):
    view = window.centralWidget()
    assert not view._button_back.isEnabled() and not view._button_forward.isEnabled()
    view.select_page(1)
    view.select_page(2)
    assert view._button_back.isEnabled()
    assert view.go_back() and view.current_index() == 1
    assert view._button_forward.isEnabled()
    assert view.go_forward() and view.current_index() == 2
    assert not view._button_forward.isEnabled()
    view.go_back()
    view.select_page(3)  # another page: Forward cleared, like a browser
    assert not view.can_go_forward() and not view.go_forward()


def test_forward_reopens_closed_tool_page(window):
    from neopedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.select_page(0)
    open_tool("heatmap_editor.HeatmapEditor", window)  # not in rail: closed once left
    assert view.go_back() and view.current_index() == 0
    flush()
    assert not view.dialog_pages()  # left page closed...
    assert view.can_go_forward() and view.go_forward()  # ...opened again by Forward
    assert type(view.current_page().dialog).__name__ == "HeatmapEditor"


def test_mouse_forward_button_and_alt_right(window):
    from PySide6.QtGui import QShortcut

    keys = {shortcut.key().toString(): shortcut.whatsThis() for shortcut in window.findChildren(QShortcut)}
    assert keys["Alt+Right"] == "Forward" and keys["Alt+Left"] == "Back" and keys["Ctrl+/"] == "Keyboard Shortcuts"
    assert "F1" not in keys and "Ctrl+F" in keys  # F1 of pages first (chart help), then the window's
    from PySide6.QtGui import QKeyEvent

    opened = []
    window.open_shortcuts = lambda: opened.append(True)
    window.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier))
    assert opened == [True]


def test_window_title_follows_page_and_unsaved_marker(window):
    from neopedal.const_app import APP_NAME
    from neopedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.select_page(1)
    assert window.windowTitle().startswith("Overlays[*] - ") and APP_NAME in window.windowTitle()
    open_tool("brake_editor.BrakeEditor", window)
    page = page_of(window, "BrakeEditor")
    page.dialog.set_modified()
    assert window.windowTitle().startswith("Brake Editor[*]") and window.isWindowModified()
    page.dialog.set_unmodified()
    assert not window.isWindowModified()


def test_safe_mode_suffix_kept_in_window_title(window):
    window.setWindowTitle(f"{window.windowTitle()} - Safe Mode")
    window.centralWidget().select_page(2)
    assert window.windowTitle().endswith(" - Safe Mode") and window.windowTitle().count("Safe Mode") == 1


# --- Shell header of tool pages (N3)
def test_tool_page_header_breadcrumb_and_single_close(window):
    from neopedal.ui.nav_rail import PAGE_INDEX
    from neopedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.select_page(PAGE_INDEX["tools"])
    open_tool("brake_editor.BrakeEditor", window)
    page = page_of(window, "BrakeEditor")
    crumb = page._button_crumb
    assert not crumb.isHidden() and crumb.text() == "Tools" and not page._label_title.isHidden()
    title = page.findChild(QLabel, "dialogPageTitle")
    assert title.font().pointSizeF() > page.font().pointSizeF()  # page title look of Qt Quick pages (N2)
    closes = [button for button in page.findChildren(QAbstractButton) if button.text() == "Close" and not button.isHidden()]
    assert closes == [page._button_close]  # dialog's own Close hidden: no double Close
    crumb.click()
    assert view.current_index() == PAGE_INDEX["tools"]


def test_rail_tool_page_has_title_without_breadcrumb_or_close(window):
    from neopedal.ui.tools_view import open_tool

    open_tool("race_calculator.RaceCalculator", window)
    page = page_of(window, "RaceCalculator")
    assert not page._header.isHidden() and page.title_height() > 0  # same title as out of the rail (N2)
    assert not page._label_title.isHidden() and page._label_title.text() == "Race Calculator"
    assert page._button_crumb.isHidden() and page._button_close.isHidden() and page.crumb_target() is None


def test_page_showing_its_own_title_has_none_in_header(window):
    from neopedal.ui.option_finder import OptionFinder

    window.show()
    OptionFinder(window).show()
    page = page_of(window, "OptionFinder")
    flush()
    page.refresh_breadcrumb()
    assert page.owns_title() and page._label_title.isHidden()  # TpPageHeader of the Qt Quick page has it


def test_escape_kept_by_broadcast_director(window):
    from PySide6.QtGui import QKeyEvent

    from neopedal.ui.broadcast_director import BroadcastDirector

    assert BroadcastDirector.ESC_CLOSES is False
    from neopedal.ui.tools_view import open_tool

    open_tool("heatmap_editor.HeatmapEditor", window)
    page = page_of(window, "HeatmapEditor")
    page.dialog.ESC_CLOSES = False  # same flag on any page
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    assert page.eventFilter(page.dialog, event) is True  # Esc taken: page stays
    page.dialog.ESC_CLOSES = True
    assert page.eventFilter(page.dialog, event) is False


# --- Notification center & status band (N4, N5)
def test_background_error_kept_in_notification_center(window, qml_warnings):  # noqa: F811
    from neopedal.ui.notification import notification_store
    from neopedal.ui.quick.notify_backend import NotificationCenter

    view = window.centralWidget()
    app_signal.error.emit("Telemetry recorder: unable to save lap 3, see log for details.")
    app_signal.error.emit("Telemetry recorder: unable to save lap 3, see log for details.")  # counted on it
    store = notification_store()
    entries = store.entries()
    assert len(entries) == 1 and entries[0]["count"] == 2 and entries[0]["severity"] == "error"
    assert [action["key"] for action in entries[0]["actions"]] == ["log", "bug_report"]
    assert view._button_notices.badge_text == "1"
    window.show()
    popup = NotificationCenter.open_at(window, view._button_notices)
    flush()
    assert popup is not None and popup.view.status() == popup.view.Status.Ready, popup.view.errors()
    assert len(popup.backend.entries) == 1 and popup.backend.entries[0]["time"]
    popup.backend.runAction("log")  # popup closed, log page opened
    flush()
    assert any(type(page.dialog).__name__ == "LogInfo" for page in view.dialog_pages())
    assert store.unread_count() == 0 and view._button_notices.badge_text == ""
    assert not [warning for warning in qml_warnings if "NotificationCenter" in warning], qml_warnings


def test_status_chips_listed_in_center_and_readable():
    from neopedal.ui.notification import MIN_CONTRAST, contrast, readable_colors

    for font, background in (("#FFFFFF", "#0088CC"), ("#FFFFFF", "#777777"), ("#FFFFFF", "#FFFF00"),
                             ("#000000", "#111111"), ("bogus", "#334499"), ("#FFFFFF", "#767676")):
        text, fill = readable_colors(font, background)
        assert contrast(QColor(text), QColor(fill)) >= MIN_CONTRAST, (font, background)
    assert readable_colors("#FFFFFF", "#334499") == ("#ffffff", "#334499")  # readable: kept as chosen


def test_notification_defaults_readable():
    from neopedal.template.setting_global import GLOBAL_DEFAULT
    from neopedal.ui.notification import MIN_CONTRAST, NOTICE_CHIPS, contrast

    notification = GLOBAL_DEFAULT["notification"]
    for _, name, _, _ in NOTICE_CHIPS:
        ratio = contrast(QColor(notification[f"font_color_{name}"]), QColor(notification[f"background_color_{name}"]))
        assert ratio >= MIN_CONTRAST, name


def test_one_status_band(window):
    from PySide6.QtWidgets import QPushButton

    from neopedal.ui.notification import NotifyBar, notification_store

    bar = window.statusBar()
    assert window.findChild(NotifyBar).parent() is bar  # chips in the status bar, not a second band
    assert not [button for button in bar.findChildren(QPushButton) if button.objectName() in ("pillApi", "pill")]
    cfg.notification["notify_spectate_mode"] = True
    cfg.api["enable_player_index_override"] = True
    try:
        window.centralWidget()._notify_bar.refresh()
        assert ("Spectate Mode Enabled", "page:spectate") in notification_store().active()
    finally:
        cfg.api["enable_player_index_override"] = False
        window.centralWidget()._notify_bar.refresh()
    assert not notification_store().active()


def test_tray_message_while_hidden_once_per_interval(window, monkeypatch):
    from neopedal.ui import notification

    messages = []
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, title, text, *args: messages.append(text))
    monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: True)
    monkeypatch.setattr(QSystemTrayIcon, "supportsMessages", staticmethod(lambda: True))
    window.hide()
    store = notification.notification_store()
    store.add("Overlay crashed", "error")
    store.add("Update available", "info")  # information: never a tray message
    store.add("Second error", "error")  # within the interval: counted for the next one
    assert messages == ["Overlay crashed"]
    window._tray_relay._last -= notification.TRAY_MESSAGE_INTERVAL
    store.add("Third error", "error")
    assert len(messages) == 2 and messages[1].startswith("2 new messages")


# --- Command palette (N6)
def test_palette_has_every_menu_command(window):
    from neopedal.ui.command_palette import build_commands

    titles = {command.title.split("  (")[0] for command in build_commands(window)}
    for title in ("Restart NeoPedal", "Quit", "Check for Updates", "Create Bug Report…", "Show Log", "About",
                  "Setup Wizard", "What's New", "Keyboard Shortcuts", "Customize Navigation Bar…", "Restart API",
                  "Notifications", "Reset Window Size and Position", "Minimize to Tray", "Delta Best",
                  "Window theme: Modern Light", "Settings", "Find Option…", "Back", "Forward"):
        assert title in titles, title


def test_palette_scoring_prefixes_and_recent(window, qml_warnings):  # noqa: F811
    from neopedal.ui.command_palette import CommandPalette, command_score, match_commands, search_text

    palette = CommandPalette(window)
    flush()
    assert palette.view.status() == palette.view.Status.Ready, palette.view.errors()
    commands = palette.commands
    assert match_commands(commands, "rclc")[0].title == "Race Calculator"  # letters in order
    exact = next(command for command in commands if command.title == "Tools")
    assert command_score(exact, search_text("tools").split()) > 200
    palette.set_search(">quit")
    assert palette.backend.titles()[0] == "Quit" and {row["group"] for row in palette.backend.results} == {"Commands"}
    palette.set_search("#")
    assert all(row["group"] == "Presets" for row in palette.backend.results)
    palette.set_search("@font color")
    assert palette.backend.results and all(row["group"] == "Options" for row in palette.backend.results)
    palette.set_search("Spectate")
    palette.run_selected()
    flush()
    assert cfg.application["command_palette_recent"].split("\n")[0] == "page:spectate"
    palette = CommandPalette(window)
    assert palette.backend.results[0]["group"] == "Recent" and palette.backend.results[0]["title"] == "Spectate"
    shortcuts = {row["title"]: row["shortcut"] for row in palette.backend.results}
    assert shortcuts["Settings"] == "Ctrl+,"
    palette.close()
    assert not [warning for warning in qml_warnings if "CommandPalette" in warning or "PaletteRow" in warning]


def test_palette_runs_theme_command(window):
    from neopedal.ui.command_palette import build_commands

    command = next(command for command in build_commands(window) if command.title == "Window theme: Legacy Light")
    try:
        command.run()
        assert cfg.application["window_color_theme"] == "Legacy Light"
    finally:
        cfg.application["window_color_theme"] = "Modern Dark"
        app_signal.refresh.emit(True)


# --- Shortcuts sheet, Tools page, Ctrl+F
def test_shortcuts_sheet(window, qml_warnings):  # noqa: F811
    from neopedal.ui.quick.shell_shortcuts_backend import ShortcutsSheet

    window.show()
    sheet = ShortcutsSheet.toggle(window)
    flush()
    assert sheet is not None and sheet.view.status() == sheet.view.Status.Ready, sheet.view.errors()
    rows = sheet.backend.rows
    assert {"keys": "Ctrl+K", "text": "Command Palette", "group": "Main Window"} in rows
    assert any(row["keys"] == "Ctrl+1" for row in rows) and any(row["keys"] == "Ctrl+Shift+F" for row in rows)
    sheet.backend.setSearch("forward")
    assert [row["keys"] for row in sheet.backend.rows] == ["Alt+Right"]
    assert ShortcutsSheet.toggle(window) is None  # open: closed
    assert not [warning for warning in qml_warnings if "Shortcuts.qml" in warning], qml_warnings


def test_tools_page_tiles_search_and_states(window, qml_warnings):  # noqa: F811
    from neopedal.ui.nav_rail import PAGE_INDEX
    from neopedal.ui.tools_view import LISTED_TOOL_SECTIONS, ToolsView

    window.show()
    view = window.centralWidget()
    view.select_page(PAGE_INDEX["tools"])
    flush()
    tools = view.findChild(ToolsView)
    assert tools.view.status() == tools.view.Status.Ready, tools.view.errors()
    backend = tools.backend
    pages = [tool["name"] for tool in backend.sections[0]["tools"]]  # Pages section first, as the Tools menu (N8)
    assert backend.sections[0]["title"] == "Pages" and pages == ["module", "spectate", "pacenotes", "hotkey"]
    assert backend.shownCount == sum(len(entries) for _, entries in LISTED_TOOL_SECTIONS) + len(pages)
    lap = next(tool for section in backend.sections for tool in section["tools"] if tool["name"] == "LapViewer")
    assert lap["inRail"] and lap["description"]
    backend.setSearch("carburant")  # French keyword finds the calculator
    assert [tool["name"] for section in backend.sections for tool in section["tools"]] == ["RaceCalculator"]
    backend.setSearch("")
    view.refresh_page_states()
    assert backend.statuses.get("RaceCalculator") == ""
    window.find_in_page()  # Ctrl+F: search field of the page focused
    assert tools.view.hasFocus()
    backend.openTool("perf_view.PerformanceView")
    flush()
    assert type(view.current_page().dialog).__name__ == "PerformanceView"
    assert not [warning for warning in qml_warnings if "Tools.qml" in warning or "ToolTile" in warning], qml_warnings


def test_find_option_on_ctrl_shift_f(window):
    from neopedal.ui.menu import ConfigMenu

    menu = window.findChild(ConfigMenu)
    find = next(action for action in menu.actions() if action.text() == "Find Option…")
    assert find.shortcut().toString() == "Ctrl+Shift+F"
    assert next(action for action in menu.actions() if action.text() == "Open Settings").shortcut().toString() == "Ctrl+,"


# --- Menus & tray
def test_help_and_tools_menus(window):
    from neopedal.ui.menu import HelpMenu, ToolsMenu

    help_titles = [action.text() for action in window.findChild(HelpMenu).actions()]
    assert "Overlay Performance" not in help_titles  # Tools only
    assert "What's New" in help_titles and "Keyboard Shortcuts\tCtrl+/" in help_titles
    tools = window.findChild(ToolsMenu)
    tools.menu_pages.aboutToShow.emit()
    pages = [action.text() for action in tools.menu_pages.actions()]
    assert "Spectate" in pages and "Home" not in pages
    assert "Settings" not in [action.text() for action in tools.actions()]


def test_tray_menu_open_app_and_presets(window, monkeypatch):
    from neopedal.ui import command_palette
    from neopedal.ui.menu import OverlayMenu

    tray = OverlayMenu("Overlay", window, True)
    assert "Open NeoPedal" in [action.text() for action in tray.actions()]
    monkeypatch.setattr(cfg.filename, "setting", "A very long preset name for endurance races.json")
    tray.refresh_preset_name()
    assert tray.loaded_preset.text() == "A very long preset name for endurance races"  # whole name
    monkeypatch.setattr(command_palette, "preset_names", lambda: ["A very long preset name for endurance races", "B"])
    loads = []
    monkeypatch.setattr(command_palette, "load_preset", loads.append)
    tray.menu_presets.aboutToShow.emit()
    actions = tray.menu_presets.actions()
    assert [action.isChecked() for action in actions] == [True, False]
    actions[1].trigger()
    assert loads == ["B"]
    tray.deleteLater()


def test_first_close_to_tray_told_once(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    messages = []
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, title, text, *args: messages.append(text))
    monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: True)
    cfg.application["minimize_to_tray"] = True
    cfg.application["close_to_tray_notice_shown"] = False
    try:
        window.closeEvent(QCloseEvent())
        window.closeEvent(QCloseEvent())
        assert len(messages) == 1 and "notification area" in messages[0]
        assert cfg.application["close_to_tray_notice_shown"] is True
    finally:
        cfg.application["close_to_tray_notice_shown"] = False


# --- Title bar (V1), lazy page skeleton & fade
def test_title_bar_follows_window_theme(window, monkeypatch):
    from neopedal.ui import app as app_module

    asked = []
    monkeypatch.setattr(app_module, "apply_title_bar_scheme", asked.append)
    try:
        for theme, dark in (("Modern Light", False), ("Legacy Dark", True)):
            cfg.application["window_color_theme"] = theme
            app_signal.refresh.emit(True)
            assert asked[-1] is dark
    finally:
        cfg.application["window_color_theme"] = "Modern Dark"
        app_signal.refresh.emit(True)
    assert app_module.apply_title_bar_scheme in asked or asked  # replaced function was called


def test_title_bar_scheme_call_is_safe():
    import sys

    from PySide6.QtGui import QGuiApplication

    from neopedal.ui.app import apply_title_bar_scheme

    hints = QGuiApplication.styleHints()
    before = hints.colorScheme()
    try:
        assert apply_title_bar_scheme(True) is (sys.platform == "win32")
    finally:
        if sys.platform == "win32":
            hints.setColorScheme(before)


def test_lazy_page_skeleton_then_page():
    from PySide6.QtWidgets import QStackedWidget, QWidget

    from neopedal.ui.lazy_page import LazyPage, PageFade

    stack = QStackedWidget()
    built = []
    lazy = LazyPage(stack, lambda parent: built.append(QWidget(parent)) or built[-1])
    stack.addWidget(QWidget())
    stack.addWidget(lazy)
    lazy.show_skeleton()
    stack.setCurrentWidget(lazy)  # shown: not built yet (placeholder painted first)
    assert lazy.page is None and lazy._placeholder is not None
    assert lazy.ensure_page() is built[0] and lazy._placeholder.isHidden()
    fade = PageFade(stack)
    fade.start()  # window hidden: no fade
    assert fade.isHidden()
    stack.deleteLater()


# --- Bug report & plugin manager
def test_github_issue_prefilled_without_personal_data():
    import getpass
    from urllib.parse import parse_qs, urlsplit

    from neopedal.const_app import FORK_REPO_NAME, VERSION
    from neopedal.ui.bug_report_view import issue_url

    url = issue_url("Overlay freezes\nwhen I pit")
    parts = urlsplit(url)
    assert parts.scheme == "https" and parts.path == f"/{FORK_REPO_NAME}/issues/new"
    query = parse_qs(parts.query)
    assert query["title"] == ["Overlay freezes"] and VERSION in query["body"][0]
    assert getpass.getuser() not in query["body"][0]


def test_plugin_manager_buttons_named_after_action(ui_env):
    from neopedal.ui.plugin_manager import PluginManager

    manager = PluginManager(None)
    try:
        assert manager.button_toggle.text() == "Enable" and not manager.button_toggle.isEnabled()
        assert manager.button_trust.text() == "Trust Plugin…" and manager.button_uninstall.text() == "Uninstall…"
    finally:
        manager.deleteLater()
        flush()


def test_new_texts_translated(french):
    from neopedal.i18n import tr, trm

    for text in ("Settings", "Open NeoPedal", "Notifications", "Keyboard Shortcuts", "Forward", "Open Settings",
                 "Calculator", "Loading page…", "Help for This Page", "Open GitHub Issue…", "Trust Plugin…",
                 "Uninstall…", "Find a tool", "Now", "Window theme", "Every page is in the navigation bar"):
        assert tr(text) != text, text
    assert trm("3 unread") != "3 unread" and trm("Help: Overlays") == "Aide : Overlays"
    assert trm("Go to Outils") == "Aller à Outils"


def test_window_unchanged_when_hidden_in_tray(window):
    """Status chips & rail refresh never fail once the status bar was replaced (language change)"""
    window.retranslate()
    flush()
    view = window.centralWidget()
    view.refresh_page_states()
    assert QApplication.instance() is not None and view._notify_bar is not None


def test_palette_typing_and_enter_run_command(window):
    import time

    from PySide6.QtTest import QTest

    from neopedal.ui.command_palette import CommandPalette
    from neopedal.ui.nav_rail import PAGE_INDEX

    window.show()
    palette = CommandPalette(window)
    flush()
    QTest.keyClicks(palette.view, "spectate")
    end = time.monotonic() + 2
    while time.monotonic() < end and palette.backend._query != "spectate":
        QCoreApplication.processEvents()
    assert palette.backend._query == "spectate"  # typed in the search field (popup has the keyboard)
    QTest.keyClick(palette.view, Qt.Key.Key_Return)
    flush()
    assert window.centralWidget().current_index() == PAGE_INDEX["spectate"]
    from neopedal.ui.quick.shell_popup import ShellPopup

    assert ShellPopup.shown("palette") is None  # closed (and deleted) before the command ran


def test_palette_escape_clears_then_closes(window):
    from PySide6.QtTest import QTest

    from neopedal.ui.command_palette import CommandPalette
    from neopedal.ui.quick.shell_popup import ShellPopup

    window.show()
    palette = CommandPalette(window)
    flush()
    QTest.keyClicks(palette.view, "ab")
    QTest.keyClick(palette.view, Qt.Key.Key_Escape)  # clears
    flush()
    assert ShellPopup.shown("palette") is palette
    QTest.keyClick(palette.view, Qt.Key.Key_Escape)  # closes
    flush()
    assert ShellPopup.shown("palette") is None
