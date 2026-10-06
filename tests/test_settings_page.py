"""Settings page (config.json): categories & groups, editors by option kind, pending edits checked while typing,
undo & redo, reset, search through every category, apply (saved, app reloaded), status cards, page in app"""

from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon

from tinypedal import app_signal
from tinypedal.const_file import ConfigType
from tinypedal.setting import cfg


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


class Host:
    """Settings host: answers & records"""

    def __init__(self):
        self.answer = True
        self.questions: list[str] = []
        self.applied_sections: list[set[str]] = []
        self.restart: list[list[str]] = []
        self.color = "#123456"
        self.folder = ""
        self.opened: list[str] = []
        self.links: list[str] = []

    def confirm(self, text):
        self.questions.append(text)
        return self.answer

    def pick_color(self, color):
        return self.color

    def pick_folder(self, folder):
        return self.folder

    def pick_image(self, filename):
        return ""

    def open_folder(self, folder):
        self.opened.append(folder)

    def applied(self, sections, restart):
        self.applied_sections.append(sections)
        self.restart.append(restart)

    def open_link(self, name):
        self.links.append(name)


@pytest.fixture
def settings(ui_env):
    from tinypedal.ui.quick.settings_backend import SettingsBackend

    host = Host()
    backend = SettingsBackend(None, host)
    backend.host = host
    yield backend
    backend.deleteLater()
    flush()


def row(backend, key: str) -> dict:
    return next(row for row in backend.model.rows if row["key"] == key)


def test_every_global_option_shown_once(settings):
    from tinypedal.ui.config import HIDDEN_OPTIONS
    from tinypedal.ui.quick.settings_backend import CATEGORIES

    for category in CATEGORIES:
        expected = [key for key in cfg.user.config[category.key] if key not in HIDDEN_OPTIONS.get(category.key, ())]
        shown = [info.key for info in settings._infos.values() if info.section == category.key]
        assert sorted(shown) == sorted(expected), category.key
        for _, keys in category.groups:  # group lists name real options only
            assert set(keys) <= set(cfg.user.config[category.key]), category.key
    assert "application/home_quick_access" not in settings._infos  # edited by Home page
    assert "application/position_x" not in settings._infos


def test_groups_and_editor_kinds(settings):
    rows = settings.model.rows
    assert rows[0]["group"] == "Interface" and rows[0]["first"]
    language = row(settings, "application/language")
    assert language["kind"] == "choice" and "Français" in language["choices"]
    from tinypedal import regex_pattern as rxp

    theme = row(settings, "application/window_color_theme")
    themes = list(rxp.CHOICE_COMMON[rxp.CFG_WINDOW_COLOR_THEME])
    assert theme["choices"] == themes  # English: shown as saved
    assert theme["choiceIndex"] == themes.index(cfg.application["window_color_theme"])
    snap = row(settings, "application/snap_distance")
    assert snap["kind"] == "integer" and snap["minimum"] == 0 and snap["maximum"] == 1000 and snap["decimals"] == 0
    settings.selectCategory("overlay_style")
    radius = row(settings, "overlay_style/corner_radius_scale")
    assert radius["kind"] == "float" and radius["decimals"] == 2 and radius["step"] == pytest.approx(0.01)
    assert row(settings, "overlay_style/modern_font_name")["kind"] == "font"
    settings.selectCategory("user_path")
    paths = settings.model.rows
    assert all(item["kind"] == "path" for item in paths) and paths[0]["group"] == ""  # page title says it
    settings.selectCategory("notification")
    color = row(settings, "notification/font_color_locked_preset")
    assert color["kind"] == "color" and color["color"] == "#FFFFFF" and color["help"] == ""  # generic help skipped
    assert settings.previews["Preset Locked"]["background"] == "#777777"


def test_pending_edits_undo_redo_discard(settings):
    key = "application/show_at_startup"
    saved = cfg.application["show_at_startup"]
    settings.setBool(key, not saved)
    assert settings.pendingCount == 1 and settings.is_modified() and row(settings, key)["changed"]
    assert cfg.application["show_at_startup"] == saved  # nothing saved yet
    settings.setBool(key, saved)  # back to saved value: nothing pending
    assert settings.pendingCount == 0 and settings.canUndo
    settings.undo()
    assert settings.pendingCount == 1
    settings.redo()
    assert settings.pendingCount == 0
    settings.setNumber("application/snap_distance", 25.4)
    assert row(settings, "application/snap_distance")["number"] == 25  # whole number option
    settings.discard()
    assert settings.pendingCount == 0 and not settings.is_modified()


def test_invalid_values_block_apply(settings):
    key = "notification/font_color_locked_preset"
    settings.setText(key, "#12")
    assert settings.errorCount == 1 and "RRGGBB" in settings.firstError
    settings.selectCategory("application")
    assert settings.apply() is False and settings.category == "notification"  # first error shown
    assert cfg.notification["font_color_locked_preset"] == "#FFFFFF"
    settings.setText(key, "#00ff00")
    assert settings.errorCount == 0 and row(settings, key)["color"] == "#00FF00"
    assert settings.apply() is True
    assert cfg.notification["font_color_locked_preset"] == "#00FF00"
    assert settings.host.applied_sections == [{"notification"}] and not settings.canUndo


def test_number_text_and_choice_edits_applied(settings, ui_env):
    from tinypedal import regex_pattern as rxp

    themes = list(rxp.CHOICE_COMMON[rxp.CFG_WINDOW_COLOR_THEME])
    other = next(theme for theme in themes if theme != cfg.application["window_color_theme"])
    settings.setChoice("application/window_color_theme", themes.index(other))
    settings.setText("application/update_repository", "someone/fork")
    settings.setNumber("application/number_of_days_to_keep_deleted_presets", 7)
    settings.setChoice("application/language", 99)  # out of range: ignored
    assert settings.pendingCount == 3
    assert settings.categories[0]["changed"] == 3
    assert settings.apply()
    assert cfg.application["window_color_theme"] == other and cfg.application["update_repository"] == "someone/fork"
    assert cfg.application["number_of_days_to_keep_deleted_presets"] == 7
    assert ConfigType.CONFIG in ui_env and settings.host.applied_sections == [{"application"}]


def test_typed_text_taken_while_typing(settings):
    key = "application/update_repository"
    settings.typeText(key, "some")
    settings.typeText(key, "someone/fork ")  # shown as typed, not reformatted
    assert settings.pendingCount == 1 and row(settings, key)["text"] == "someone/fork "
    settings.setText(key, "someone/fork")  # field left: value taken as is
    assert row(settings, key)["text"] == "someone/fork"
    settings.undo()  # keys typed in a row: one undo step
    assert settings.pendingCount == 0 and row(settings, key)["text"] == cfg.application["update_repository"]
    color = "notification/font_color_locked_preset"
    settings.selectCategory("notification")
    settings.typeText(color, "#12")
    assert settings.errorCount == 1 and row(settings, color)["text"] == "#12"  # checked as typed
    settings.typeText(color, "#123456")
    assert settings.errorCount == 0 and settings._pending[color] == "#123456"
    settings.revertOption(color)  # Esc: saved value back
    assert color not in settings._pending and row(settings, color)["text"] == "#FFFFFF"
    settings.typeText("application/snap_distance", "25")
    assert settings.apply() and cfg.application["snap_distance"] == 25


def test_options_read_at_startup_offer_restart(settings):
    assert row(settings, "application/enable_high_dpi_scaling")["applies"] == "restart"
    assert row(settings, "application/show_at_startup")["applies"] == "next_start"
    assert row(settings, "application/snap_gap")["applies"] == ""
    settings.setBool("application/enable_high_dpi_scaling", not cfg.application["enable_high_dpi_scaling"])
    settings.setBool("application/show_at_startup", not cfg.application["show_at_startup"])
    assert settings.apply()
    assert settings.host.restart == [["Enable High DPI Scaling"]]


def test_reset_option_and_category(settings):
    cfg.application["snap_gap"] = 5
    settings.refresh()
    assert row(settings, "application/snap_gap")["modified"]
    settings.resetOption("application/snap_gap")
    assert settings.pendingCount == 1 and row(settings, "application/snap_gap")["number"] == 0
    cfg.application["grid_move_size"] = 3
    settings.host.answer = False
    settings.resetCategory()
    assert settings.pendingCount == 1 and settings.host.questions  # cancelled
    settings.host.answer = True
    settings.resetCategory()
    assert settings.pendingCount == 2
    settings.apply()
    assert cfg.application["snap_gap"] == 0 and cfg.application["grid_move_size"] == 8


def test_search_through_every_category(settings):
    settings.setSearch("PORT")
    keys = [item["key"] for item in settings.model.rows]
    assert keys == ["remote_control/remote_control_port", "web_dashboard/web_dashboard_port",
                    "stream_overlay/stream_overlay_port"]
    assert settings.matchCount == 3 and settings.searching
    matches = {entry["key"]: entry["matches"] for entry in settings.categories}
    assert matches["remote_control"] == 1 and matches["application"] == 0
    assert settings.model.rows[0]["group"] == "Remote Control"
    settings.selectCategory("vr_overlay")  # leaves search
    assert not settings.searching and settings.searchText == ""


def test_focus_option_from_search(settings):
    flashed = []
    settings.highlightChanged.connect(lambda: flashed.append(settings.highlightKey))
    settings.focus_option("vr_overlay", "distance_meters")
    assert settings.category == "vr_overlay" and flashed[-1] == "vr_overlay/distance_meters"


def test_folder_checked_when_applied(settings, tmp_path):
    key = "user_path/telemetry_path"
    settings.setText(key, "   ")
    assert settings.errorCount == 1  # empty folder
    root = tmp_path.anchor
    settings.setText(key, root)
    assert settings.apply() is False and settings.errorCount == 1  # drive root refused
    folder = (tmp_path / "laps").as_posix()
    settings.setText(key, folder)
    assert settings.apply() is True
    assert cfg.user.config["user_path"]["telemetry_path"].rstrip("/") == folder
    assert (tmp_path / "laps").is_dir()
    settings.host.folder = (tmp_path / "other").as_posix()
    settings.browse(key)
    assert settings.pendingCount == 1


def test_color_picked_and_folders_opened(settings):
    settings.pickColor("compatibility/background_color_global")
    assert settings._pending["compatibility/background_color_global"] == "#123456"
    settings.openFolder("user_path/settings_path")
    settings.openConfigFolder()
    settings.openLink("units")
    assert len(settings.host.opened) == 2 and settings.host.links == ["units"]


def test_refresh_follows_saved_changes(settings):
    settings.setBool("application/minimize_to_tray", not cfg.application["minimize_to_tray"])
    cfg.application["minimize_to_tray"] = not cfg.application["minimize_to_tray"]  # same value saved elsewhere
    settings.refresh()
    assert settings.pendingCount == 0


def test_status_cards(settings):
    web = settings.webDashboard
    assert web["enabled"] is False and web["urls"] == []
    cfg.user.config["web_dashboard"]["enable_web_dashboard"] = True
    cfg.user.config["web_dashboard"]["access_code"] = "ABCDEFGH"
    web = settings.webDashboard
    assert web["urls"][0].startswith("http://127.0.0.1:8338/?code=ABCDEFGH") and web["code"] == "ABCDEFGH"
    cfg.user.config["web_dashboard"]["enable_web_dashboard"] = False
    remote = settings.remoteControl
    assert remote["stream"] == "ws://127.0.0.1:8337/stream" and "X-TinyPedal" in remote["command"]


# Page in app
@pytest.fixture
def window(ui_env, monkeypatch):
    from tinypedal import loader
    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    # Applied settings restart overlays, modules & servers: not in tests (overlay control thread
    # left running would auto hide the overlays of later tests)
    monkeypatch.setattr(loader, "reload", lambda **kwargs: None)
    monkeypatch.setattr(loader, "restart", lambda *args, **kwargs: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            backend = getattr(page.dialog, "backend", None)
            if backend is not None and hasattr(backend, "discard"):
                backend.discard()  # closed without question
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    main.deleteLater()
    flush()


def settings_pages(window):
    from tinypedal.ui.app_settings import AppSettings

    return [page for page in window.centralWidget().dialog_pages() if isinstance(page.dialog, AppSettings)]


def test_config_menu_entries_open_one_page_at_category(window):
    from tinypedal.ui.menu import open_config_application

    first = open_config_application(window, "web_dashboard")
    assert first.backend.category == "web_dashboard" and len(settings_pages(window)) == 1
    second = open_config_application(window, "user_path")
    flush()
    assert second is first and first.backend.category == "user_path" and len(settings_pages(window)) == 1
    assert not first.view.errors(), [error.toString() for error in first.view.errors()]
    assert settings_pages(window)[0].title == "Config"


def test_page_unsaved_marker_ctrl_s_and_close(window, monkeypatch):
    from tinypedal.ui import app_settings
    from tinypedal.ui.menu import open_config_application

    reloads = []
    monkeypatch.setattr(app_settings, "run_after_saving", lambda callback: reloads.append(callback))
    page = open_config_application(window)
    page.backend.setNumber("application/snap_gap", 4)
    assert page.is_marked_modified() and settings_pages(window)[0].is_modified()
    assert window.centralWidget().save_current_page()  # Ctrl+S
    assert cfg.application["snap_gap"] == 4 and reloads and not page.is_marked_modified()
    page.backend.setNumber("application/snap_gap", 6)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Cancel))
    page.close()
    assert settings_pages(window)  # cancelled: kept
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard))
    page.close()
    flush()
    assert not settings_pages(window) and cfg.application["snap_gap"] == 4


@pytest.mark.filterwarnings("ignore:libpyside. Failed to disconnect:RuntimeWarning")  # closed twice
def test_page_closed_again_while_asking_to_save(window, monkeypatch):
    """Close event delivered again during save question (nested event loop): no error"""
    from PySide6.QtGui import QCloseEvent

    from tinypedal.ui.menu import open_config_application

    page = open_config_application(window)
    page.backend.setNumber("application/snap_gap", 6)
    nested = []

    def question(*args, **kwargs):
        if not nested:
            nested.append(True)
            page.closeEvent(QCloseEvent())  # second close while first one asks
        return QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    event = QCloseEvent()
    page.closeEvent(event)
    assert nested and event.isAccepted() and page.view is None
    page.close()
    flush()
    assert not settings_pages(window)


def test_undo_history_capped(settings):
    """Category reset & discard keep at most 100 undo steps, like single edits"""
    cfg.application["snap_gap"] = 5
    settings.refresh()
    settings.host.answer = True
    for step in range(120):
        settings.setNumber("application/snap_distance", 10 + step % 2)
        settings.discard()
    assert len(settings._undo) <= 100
    settings._undo[:] = [settings._snapshot()] * 150
    settings.resetCategory()
    assert len(settings._undo) <= 100
    settings.discard()


def test_page_rebuilt_in_new_language(window):
    from tinypedal import i18n
    from tinypedal.ui.menu import open_config_application

    page = open_config_application(window)
    page.backend.setNumber("application/snap_gap", 4)  # pending edit kept
    i18n.set_language("Français")
    try:
        page.refresh()  # page shown: rebuilt now
        assert settings_pages(window)[0].title == "Réglages" and not page._stale
        assert page.backend.pendingCount == 1 and not page.view.errors()
        assert page.backend.categoryInfo["label"] == "Application"
    finally:
        i18n.set_language("English")
        page.refresh_now()
        page.backend.discard()


def test_config_page_in_navigation_bar_and_tools(window):
    from tinypedal.ui.home_view import default_quick_items
    from tinypedal.ui.menu import open_config_application
    from tinypedal.ui.nav_rail import default_rail_items, rail_entries
    from tinypedal.ui.tools_view import TOOL_KEYWORDS, TOOL_SECTIONS, open_tool

    entry = rail_entries()["app_settings"]
    assert entry.dialog == "app_settings.AppSettings" and entry.label == "Config"
    assert "app_settings" in default_rail_items() and "app_settings" in default_quick_items()
    assert any(path == "app_settings.AppSettings" for _, tools in TOOL_SECTIONS for _, _, path in tools)
    assert "reglages" in TOOL_KEYWORDS["app_settings.AppSettings"]
    page = open_tool("app_settings.AppSettings", window)  # navigation bar entry, Tools page, quick access
    page.backend.selectCategory("vr_overlay")
    assert open_config_application(window, "") is page and page.backend.category == "vr_overlay"  # gear, Ctrl+,
    assert open_tool("app_settings.AppSettings", window) is page and len(settings_pages(window)) == 1
    view = window.centralWidget()
    assert view.is_rail_page(settings_pages(window)[0])  # kept like other pages, no close button
    view.select_page(0)  # other page shown: page kept open with its category
    assert settings_pages(window) and page.backend.category == "vr_overlay"


def test_ctrl_comma_opens_config_page(window):
    from PySide6.QtGui import QAction, QKeySequence

    actions = [action for action in window.findChildren(QAction) if action.shortcut() == QKeySequence("Ctrl+,")]
    assert len(actions) == 1
    actions[0].trigger()
    assert settings_pages(window)


def test_number_typed_in_page_applied_without_enter(window):
    """Number typed in its field then Ctrl+S (or Apply): taken although field kept focus"""
    from PySide6.QtTest import QTest

    from tinypedal.i18n.options import option_label
    from tinypedal.ui.menu import open_config_application

    page = open_config_application(window, "application")
    page.view.setFocus()
    page.backend.focus_option("application", "snap_distance")  # rows made for the part shown: scrolled to it
    QTest.qWait(150)
    for _ in range(10):
        QCoreApplication.processEvents()
    label = option_label("snap_distance")
    stack, field = [page.view.rootObject()], None
    while stack and field is None:
        item = stack.pop()
        if "NumberField" in item.metaObject().className() and item.property("tip") == label:
            field = item
        stack.extend(item.childItems())
    assert field is not None
    field.forceActiveFocus()
    QTest.keyClicks(page.view, "37")  # focused field selects its text: replaced
    for _ in range(5):
        QCoreApplication.processEvents()
    assert page.backend.pendingCount == 1  # unsaved changes bar shown while typing
    assert page.apply_edits() and cfg.application["snap_distance"] == 37


def test_refresh_deferred_while_hidden(window):
    from tinypedal.ui.menu import open_config_application

    page = open_config_application(window, "application")
    calls = []
    page.backend.refresh = lambda: calls.append(1)
    window.centralWidget().select_page(0)  # home page shown, config page kept behind it
    page.refresh()
    assert calls == [] and page._stale  # hidden: nothing read
    open_config_application(window, "")  # shown again: read once
    assert calls == [1] and not page._stale


PAGE_QML = (
    "Settings", "SettingRow", "Presets", "PresetRow", "PresetDetails", "Spectate", "SpectateRow", "OptionFinder",
    "OptionResultRow", "TpSearchField", "TpTextField", "TpDialog", "Pill", "EmptyState",
)


def test_page_qml_bundled_modules_and_translated():
    """Release build bundles only QML_MODULES; every text of the pages has a French translation"""
    import re

    from tinypedal.i18n.fr import TRANSLATION
    from tinypedal.ui.quick import QML_FOLDER
    from tinypedal.ui.quick.qml_modules import QML_MODULES
    from tinypedal.ui.quick.settings_backend import CATEGORIES

    pattern = re.compile(r'i18n\.tr\("((?:[^"\\]|\\.)*)"\)')
    missing = []
    for name in PAGE_QML:
        with open(f"{QML_FOLDER}/{name}.qml", encoding="utf-8") as file:
            text = file.read()
        modules = re.findall(r"^import ([A-Za-z.]+)", text, flags=re.MULTILINE)
        assert modules and all(module.replace(".", "/") in QML_MODULES for module in modules), (name, modules)
        missing += [found for found in pattern.findall(text) if found not in TRANSLATION]
    for category in CATEGORIES:
        missing += [text for text in (category.label, category.description, *(title for title, _ in category.groups))
                    if text not in TRANSLATION]
    assert not missing


def test_config_page_never_grows_window(window):
    """Page layout follows its width: opening it keeps window size"""
    from tinypedal.ui.menu import open_config_application

    window.resize(700, 520)
    window.show()
    QCoreApplication.processEvents()
    size = window.size()
    open_config_application(window, "application")
    QCoreApplication.processEvents()
    assert window.size() == size


def test_language_change_keeps_window_size(window):
    """View rebuilt in new language: window not grown again for reopened pages (measured once laid out),
    back to its size once the wide page that grew it closes"""
    from tinypedal import i18n
    from tinypedal.ui.tools_view import open_tool

    window.resize(760, 560)  # room for config page, not for driver stats
    window.show()
    QCoreApplication.processEvents()
    small = window.size()
    open_tool("driver_stats_viewer.DriverStatsViewer", window)
    open_tool("app_settings.AppSettings", window)
    QCoreApplication.processEvents()
    grown = window.size()
    assert grown.width() > small.width()
    cfg.application["language"] = "Français"
    try:
        window.retranslate()
        for _ in range(5):
            QCoreApplication.processEvents()
        assert window.size() == grown
        view = window.centralWidget()
        stats = next(page for page in view.dialog_pages() if type(page.dialog).__name__ == "DriverStatsViewer")
        stats.dialog.close()
        flush()
        assert window.size() == small
    finally:
        cfg.application["language"] = "English"
        i18n.set_language("English")
