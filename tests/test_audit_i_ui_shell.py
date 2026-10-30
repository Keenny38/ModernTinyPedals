"""Audit I, lot D1 (app shell, Settings pages, option search, palette): PERF-007/008/016/032/037/049/050/051/064/066,
BUG-016/017/036/040/048/049/051"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import suppress
from functools import partial

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QApplication, QStackedWidget, QSystemTrayIcon, QWidget

from neopedal import app_signal
from neopedal.setting import cfg


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


class Host:
    """Settings host: records what is applied"""

    def __init__(self):
        self.applied_sections: list[set[str]] = []
        self.restart: list[list[str]] = []

    def confirm(self, text):
        return True

    def pick_color(self, color):
        return ""

    def pick_folder(self, folder):
        return ""

    def pick_image(self, filename):
        return ""

    def open_folder(self, folder):
        pass

    def applied(self, sections, restart):
        self.applied_sections.append(sections)
        self.restart.append(restart)

    def open_link(self, name):
        pass


@pytest.fixture
def settings(ui_env):
    from neopedal.ui.quick.settings_backend import SettingsBackend

    backend = SettingsBackend(None, Host())
    yield backend
    backend.deleteLater()
    flush()


@pytest.fixture
def window(ui_env, monkeypatch):
    from neopedal import loader
    from neopedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    monkeypatch.setattr(loader, "reload", lambda **kwargs: None)
    monkeypatch.setattr(loader, "restart", lambda *args, **kwargs: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            backend = getattr(page.dialog, "backend", None)
            if backend is not None and hasattr(backend, "discard"):
                backend.discard()
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    main.deleteLater()
    flush()


# --- PERF-007: saved config sections applied by what reads them, not by a reload of the whole app
def test_saved_sections_refresh_or_restart_only_what_reads_them(ui_env, monkeypatch):
    from neopedal.ui import app_settings, menu
    from neopedal.ui.quick import settings_backend

    switched, reloaded_overlays, refreshed = [], [], []
    monkeypatch.setattr(settings_backend, "apply_switch", switched.append)
    from types import SimpleNamespace

    from neopedal import module_control

    monkeypatch.setattr(module_control, "wctrl", SimpleNamespace(
        reload=lambda name="", discard=False: reloaded_overlays.append(name)))
    app_signal.refresh.connect(refreshed.append)
    try:
        # Window options: refreshed, nothing restarted (overlays & modules kept running)
        app_settings.apply_saved_sections({"application"}, ["application/minimize_to_tray"])()
        assert refreshed == [True] and not switched and not reloaded_overlays
        app_settings.apply_saved_sections({"notification"})()
        assert len(refreshed) == 2
        # Overlay style: overlays restarted, modules & servers kept
        app_settings.apply_saved_sections({"overlay_style", "application"}, ["overlay_style/overlay_theme"])()
        assert reloaded_overlays == [""] and len(refreshed) == 3
        # Servers & VR layer: their switch applied (enable() reads the new port, token...)
        app_settings.apply_saved_sections({"web_dashboard", "remote_control", "vr_overlay"})()
        assert switched == [settings_backend.SWITCH_SERVERS, settings_backend.SWITCH_VR]
        # Sections read at start by the API, modules or overlays: whole app reloaded, as before
        for sections, options in (({"user_path"}, ()), ({"compatibility"}, ()), ({"application", "telemetry"}, ()),
                                  ({"application"}, ["application/minimum_update_interval"])):
            assert app_settings.apply_saved_sections(sections, options) is menu.menu_reload_preset, sections
    finally:
        app_signal.refresh.disconnect(refreshed.append)


def test_find_option_switch_of_window_option_never_reloads_app(ui_env, monkeypatch):
    from neopedal import loader
    from neopedal.const_file import ConfigType
    from neopedal.ui import menu
    from neopedal.ui.option_finder import OptionEntry, reload_function

    reloads = []
    monkeypatch.setattr(loader, "reload", lambda **kwargs: reloads.append(kwargs))
    refreshed = []
    app_signal.refresh.connect(refreshed.append)
    try:
        reload_function(OptionEntry("application", "minimize_to_tray", ConfigType.CONFIG, "", ""))()
        assert refreshed == [True] and not reloads
        assert reload_function(OptionEntry("user_path", "settings_path", ConfigType.CONFIG, "", "")) is (
            menu.menu_reload_preset)
        reload_function(OptionEntry("units", "distance_unit", ConfigType.SETTING, "", ""))()
        assert reloads == [{"reload_preset": False}]  # preset section: fast reload as before
    finally:
        app_signal.refresh.disconnect(refreshed.append)


def test_settings_page_reports_saved_option_ids(settings):
    settings.setBool("application/minimize_to_tray", not cfg.application["minimize_to_tray"])
    assert settings.apply()
    assert settings.applied_options == ["application/minimize_to_tray"]


# --- PERF-008: open page shown again instead of a second copy built & thrown away
def test_find_option_opened_twice_builds_one_page(window):
    from neopedal.ui.option_finder import OptionFinder

    first = OptionFinder(window)  # singleton_dialog wrapper of the class
    first.show()
    flush()
    finder_class = type(first)
    built = []
    original_init = finder_class.__init__
    finder_class.__init__ = lambda self, parent: built.append(parent) or original_init(self, parent)  # type: ignore[method-assign]
    try:
        second = OptionFinder(window)
        second.show()  # open page: shown again, never a window nor a modal
    finally:
        finder_class.__init__ = original_init  # type: ignore[method-assign]
    assert second is first and not built and first.in_app_page
    pages = [page for page in window.centralWidget().dialog_pages() if isinstance(page.dialog, finder_class)]
    assert len(pages) == 1 and window.centralWidget()._pages.currentWidget() is pages[0]


def test_whats_new_opened_twice_reads_changelog_once(window, monkeypatch):
    from neopedal.ui import home_view
    from neopedal.ui.release_notes import ReleaseNotesDialog, running_version_dialog

    reads = []
    real = home_view.local_changelog
    monkeypatch.setattr(home_view, "local_changelog", lambda *args, **kwargs: reads.append(1) or real(*args, **kwargs))
    first = running_version_dialog(window)
    first.open()
    flush()
    before = len(reads)
    second = running_version_dialog(window)
    second.open()
    assert second is first and len(reads) == before
    assert len([page for page in window.centralWidget().dialog_pages() if isinstance(page.dialog, ReleaseNotesDialog)]) == 1


# --- PERF-016: message rules whose literal text is missing are skipped, same translations
def test_message_rule_literals_and_same_translation():
    from neopedal import i18n

    assert i18n.pattern_literal("^Preset imported: ") == "Preset imported: "
    assert i18n.pattern_literal(r"Saving section: (\d+)%") == "Saving section: "
    assert i18n.pattern_literal(r"\bLap (\d+)") == "Lap "
    for pattern in ("(?i)delete", "foo|bar", "a*b", "^$", "[Ff]ile"):  # no literal every match holds
        assert i18n.pattern_literal(pattern) == "", pattern
    i18n.set_language("Français")
    try:
        assert len(i18n._message_literals) == len(i18n._message_rules) and any(i18n._message_literals)
        for text in ("Saving section: 45%", "<b>Disable</b> all modules?", "Unknown message stays",
                     "Replay recording stopped: [Errno 28] No space left on device"):
            expected = text
            for pattern, replacement in i18n._message_rules:  # every rule run
                expected = pattern.sub(replacement, expected)
            assert i18n.trm(text) == expected
    finally:
        i18n.set_language("English")


# --- PERF-032: dashboard addresses dialog never waits for the host name lookup
def test_dashboard_addresses_dialog_without_dns_wait(window, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QMessageBox

    from neopedal import loader
    from neopedal.ui.menu import ConfigMenu

    asked = []
    dashboard = SimpleNamespace(
        urls=lambda wait=False: asked.append(wait) or ["http://127.0.0.1:1/?code=1"],
        access_code=lambda: "1234", use_https=lambda: False)
    monkeypatch.setattr(loader, "webdashboard", dashboard, raising=False)
    cfg.user.config["web_dashboard"]["enable_web_dashboard"] = True
    shown = []

    def exec_(message):
        shown.append(message.text())
        app_signal.addresses.emit()  # lookup finished while the dialog is open: addresses refreshed
        shown.append(message.text())

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    menu = next(action.menu() for action in window.menuBar().actions() if isinstance(action.menu(), ConfigMenu))
    menu.show_web_dashboard_address()
    assert asked == [False, False] and len(shown) == 2 and "1234" in shown[0]
    app_signal.addresses.emit()  # dialog closed: no longer updated
    assert asked == [False, False]


# --- PERF-037 + BUG-048: palette results in a list model, first result selected on every new result list
def test_palette_results_model_and_qml(window):
    from neopedal.ui.command_palette import CommandPalette
    from neopedal.ui.quick.models import DictListModel

    palette = CommandPalette(window)
    flush()
    assert palette.view.status() == palette.view.Status.Ready, palette.view.errors()
    backend = palette.backend
    assert isinstance(backend.resultsModel, DictListModel) and isinstance(backend.results, list)
    keys = [row["key"] for row in backend.model.rows]
    assert len(keys) == len(set(keys)) and backend.model.rowCount() == len(backend.results)
    palette.set_search("hot")
    assert backend.model.rows[0]["title"] == backend.results[0]["title"] and backend.results[0]["key"]
    root = palette.view.rootObject()
    lists = [child for child in root.findChildren(QObject) if child.metaObject().className().startswith("QQuickListView")]
    assert lists and lists[0].property("currentIndex") == 0
    lists[0].setProperty("currentIndex", 3)  # hovered row
    palette.set_search("hotk")  # other results: first one selected again
    flush()
    assert lists[0].property("currentIndex") == 0
    palette.set_search("zzzzzzzz")
    flush()
    assert lists[0].property("count") == 0 and lists[0].property("currentIndex") == -1
    palette.close()


# --- PERF-049: option help texts kept while an option page is open, freed later
def test_help_cache_kept_while_another_option_page_is_open(ui_env, monkeypatch):
    from neopedal.i18n import options
    from neopedal.ui import app_settings

    options.option_help("cruise", "enable")
    assert options._help.cache_info().currsize == 1
    options.hold_help_cache()
    options.hold_help_cache()
    delayed = []
    monkeypatch.setattr(app_settings, "QTimer", type("T", (), {"singleShot": staticmethod(
        lambda delay, callback: delayed.append(callback))}))
    app_settings.release_help_texts()  # one page closed, the other still open: nothing scheduled
    assert not delayed and options.help_cache_held()
    app_settings.release_help_texts()  # last page closed: freed after the delay, unless a page opened meanwhile
    assert len(delayed) == 1 and not options.help_cache_held()
    options.hold_help_cache()
    delayed[0]()
    assert options._help.cache_info().currsize == 1  # page opened again before the delay: kept
    assert options.release_help_cache()
    delayed[0]()
    assert options._help.cache_info().currsize == 0


# --- PERF-050: local changelog read once while its files are unchanged
def test_local_changelog_cached_by_file_time(tmp_path, monkeypatch):
    from neopedal.ui import home_view

    english = tmp_path / "CHANGELOG.md"
    english.write_text("## 1.0.0 (2026-01-01)\n- a\n", encoding="utf-8")
    reads = []
    real = home_view.read_changelog_entries
    monkeypatch.setattr(home_view, "read_changelog_entries", lambda filename: reads.append(filename) or real(filename))
    first = home_view.local_changelog("fr", str(english))
    second = home_view.local_changelog("fr", str(english))
    assert first == second and len(first) == 1 and len(reads) == 2  # English & French files, once
    second.clear()  # a copy: the cache is never changed by callers
    assert home_view.local_changelog("fr", str(english)) == first and len(reads) == 2
    english.write_text("## 1.0.1 (2026-01-02)\n- b\n## 1.0.0 (2026-01-01)\n- a\n", encoding="utf-8")
    os.utime(english, ns=(os.stat(english).st_atime_ns, os.stat(english).st_mtime_ns + 10_000_000))
    assert len(home_view.local_changelog("fr", str(english))) == 2 and len(reads) == 4  # changed: read again


# --- PERF-051: rail polled every few seconds, not every second
def test_rail_poll_interval(window):
    from neopedal.ui.app_tab_view import RAIL_POLL_MS

    assert RAIL_POLL_MS >= 2000 and window.centralWidget()._rail_timer.interval() == RAIL_POLL_MS


# --- PERF-064: option search ranks the shown results only, same order as a full sort
def test_option_ranking_heap_matches_full_sort(ui_env):
    from neopedal.ui.option_finder import cached_index, matching_options, rank_options, search_options, search_words

    entries = cached_index()
    words = search_words("e")
    found = matching_options(entries, words)
    assert len(found) > 1000
    assert rank_options(found, words, 50) == rank_options(found, words, 0)[:50] == search_options(entries, "e", 50)
    assert search_options(entries, "e", 0) == rank_options(found, words, 0)


def test_option_help_english_cached(ui_env):
    from neopedal.i18n import options

    options.clear_help_cache()
    options.option_help_english("relative", "font_color")
    options.option_help_english("relative", "font_color")
    assert options.option_help_english.cache_info().hits >= 1
    options.clear_help_cache()
    assert options.option_help_english.cache_info().currsize == 0


def test_palette_commands_fold_title_once(window):
    from neopedal.ui.command_palette import build_commands, command_score, search_text

    commands = build_commands(window)
    assert commands and all(command.folded for command in commands)
    tools = next(command for command in commands if command.title == "Tools")
    assert command_score(tools, search_text("tools").split()) > 200


# --- PERF-066: a key typed updates its row alone, the rest once typing pauses
def test_typing_updates_edited_row_only(settings, monkeypatch):
    key = "application/update_repository"
    rebuilt, states = [], []
    monkeypatch.setattr(settings, "update_rows", lambda: rebuilt.append(1))
    settings.stateChanged.connect(lambda: states.append(1))
    settings.typeText(key, "some")
    settings.typeText(key, "someone/fork ")
    row = next(row for row in settings.model.rows if row["key"] == key)
    assert row["text"] == "someone/fork " and row["changed"] and settings.pendingCount == 1
    assert not rebuilt and not states and settings._typing_timer.isActive()
    settings._typing_timer.timeout.emit()  # typing paused
    assert rebuilt == [1] and states and not settings._typing_timer.isActive()
    settings.setText(key, "someone/fork")  # field left: everything updated at once
    assert rebuilt == [1, 1]


# --- BUG-016: test sound never lists a network folder
def test_test_sound_never_lists_network_folder(monkeypatch):
    from neopedal.ui import pace_notes_view

    listed = []
    monkeypatch.setattr(os, "listdir", lambda folder: listed.append(folder) or [])
    assert pace_notes_view.test_sound_file("\\\\server\\share\\sounds\\", "wav") == ""
    assert pace_notes_view.test_sound_file("//server/share/", "wav") == ""
    assert not listed
    pace_notes_view.test_sound_file(os.path.join(os.getcwd(), "sounds") + os.sep, "wav")
    assert listed  # local folder listed


# --- BUG-017 + BUG-040: plugin loader
def _make_plugin(folder, name, code="Realtime = object\n"):
    path = folder / name
    path.mkdir(parents=True)
    (path / "setting.json").write_text('{"font_color": "#FFFFFF"}', encoding="utf-8")
    (path / "widget.py").write_text(code, encoding="utf-8")
    return path


@pytest.fixture
def trust_file(monkeypatch, tmp_path):
    from neopedal import plugin_loader

    filename = tmp_path / "plugin_trust.json"
    monkeypatch.setattr(plugin_loader, "trust_filename", lambda: str(filename))
    return filename


def test_unreadable_plugin_is_not_reported_untrusted(tmp_path, trust_file, monkeypatch):
    from neopedal import plugin_loader

    _make_plugin(tmp_path, "locked")
    plugin_loader.trust_plugin("plugin_locked", str(tmp_path))

    def refuse(path):
        raise PermissionError(13, "locked by antivirus", path)

    monkeypatch.setattr(plugin_loader, "plugin_contents", refuse)
    plugin_loader.load_plugin_widget("neopedal.widget", "plugin_locked", str(tmp_path))
    error = plugin_loader.PLUGIN_ERRORS.pop("plugin_locked")
    assert error.startswith(plugin_loader.UNREADABLE_ERROR) and "locked by antivirus" in error
    assert error != plugin_loader.UNTRUSTED_ERROR
    sys.modules.pop("neopedal.widget.plugin_locked", None)


def test_bytecode_of_untrusted_plugin_left_alone(tmp_path, trust_file):
    from neopedal import plugin_loader

    path = _make_plugin(tmp_path, "stranger")
    cache = path / "__pycache__"
    cache.mkdir()
    (cache / "widget.cpython-311.pyc").write_bytes(b"not approved yet")
    plugin_loader.load_plugin_widget("neopedal.widget", "plugin_stranger", str(tmp_path))
    assert plugin_loader.PLUGIN_ERRORS.pop("plugin_stranger") == plugin_loader.UNTRUSTED_ERROR
    assert (cache / "widget.cpython-311.pyc").exists()  # nothing deleted in a folder the user never approved
    plugin_loader.trust_plugin("plugin_stranger", str(tmp_path))
    plugin_loader.load_plugin_widget("neopedal.widget", "plugin_stranger", str(tmp_path))
    assert "plugin_stranger" not in plugin_loader.PLUGIN_ERRORS and not cache.exists()  # trusted: cleaned
    sys.modules.pop("neopedal.widget.plugin_stranger", None)


def test_linked_plugin_folder_refused(tmp_path, trust_file):
    from neopedal import plugin_loader

    target = _make_plugin(tmp_path / "elsewhere", "linked")
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    link = plugins / "linked"
    made = False
    if sys.platform == "win32":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True).returncode == 0
    if not made:
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("no link made")
    assert plugin_loader.is_link_folder(str(link)) and not plugin_loader.is_link_folder(str(target))
    (target / "__pycache__").mkdir()
    (target / "__pycache__" / "widget.cpython-311.pyc").write_bytes(b"x")
    plugin_loader.load_plugin_widget("neopedal.widget", "plugin_linked", str(plugins))
    assert plugin_loader.PLUGIN_ERRORS.pop("plugin_linked") == plugin_loader.LINK_ERROR
    assert (target / "__pycache__" / "widget.cpython-311.pyc").exists()
    sys.modules.pop("neopedal.widget.plugin_linked", None)


# --- BUG-036: page factory raising: error shown once, not raised again at every show
def test_lazy_page_factory_error_shown_once(ui_env, caplog):
    from neopedal.ui.lazy_page import LazyPage

    calls = []

    def factory(parent):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("broken page module")
        return QWidget(parent)

    stack = QStackedWidget()
    page = LazyPage(stack, factory)
    stack.addWidget(page)
    try:
        stack.show()
        QCoreApplication.processEvents()
        assert page.page is None and page.build_failed() and calls == [1]
        assert "broken page module" in caplog.text
        assert page._placeholder is not None and "failed" in page._placeholder.text() and page._placeholder.isVisible()
        page.hide()
        page.show()  # shown again: not tried again (same exception, blank page before)
        QCoreApplication.processEvents()
        assert calls == [1] and page.ensure_page() is None
        page.show_skeleton()  # error text kept
        assert "failed" in page._placeholder.text()
        assert page.retry_build() is not None and calls == [1, 1] and not page.build_failed()
        assert not page._placeholder.isVisible()
    finally:
        stack.deleteLater()
        flush()


# --- BUG-049: queued dialog callbacks never run on a released page
def test_dialog_callbacks_skip_deleted_view_and_unwrap_partial(ui_env):
    from neopedal.ui.quick import dialogs

    class Backend(QObject):
        def __init__(self):
            super().__init__()
            self.calls = []

        def method(self, *args):
            self.calls.append(args)

    backend = Backend()
    assert dialogs.callback_owner(partial(partial(backend.method, 1), 2)) is backend
    assert dialogs.callback_owner(lambda: None) is None
    dialogs._call_alive(partial(backend.method, 1), 2)
    assert backend.calls == [(1, 2)]
    backend.deleteLater()
    flush()
    dialogs._call_alive(partial(Backend.method, backend, 3))  # unbound: no owner, runs (nothing to check)
    view = QWidget()
    bridge = dialogs.DialogBridge(view)
    bridge.attach()
    results = []
    bridge.request("confirm", {"title": "t", "text": "x"}, on_result=lambda chosen: results.append(chosen))
    bridge.request("alert", {"title": "t", "text": "x"}, on_result=lambda *args: results.append(("closed", args)))
    bridge.answer(bridge.current["id"], True)
    bridge.answer(bridge.current["id"], True)
    QCoreApplication.processEvents()
    assert results == [True, ("closed", ())]  # alert callback called without argument
    bridge.request("confirm", {"title": "t", "text": "x"}, on_result=lambda chosen: results.append(("late", chosen)))
    bridge.answer(bridge.current["id"], True)
    view.deleteLater()  # page closed before the queued callback ran
    flush()
    QCoreApplication.processEvents()
    assert results == [True, ("closed", ())]


def test_alert_on_closed_called_without_argument(ui_env):
    from neopedal.ui.quick import dialogs

    view = QWidget()
    bridge = dialogs.DialogBridge(view)
    bridge.attach()
    view.show()
    closed = []
    dialogs.alert(view, "Title", "Text", on_closed=lambda: closed.append(1))
    assert bridge.current["kind"] == "alert"
    bridge.answer(bridge.current["id"], True)
    QCoreApplication.processEvents()
    assert closed == [1]
    view.deleteLater()
    flush()


# --- BUG-051: released pages free their backend, not only their widgets
def test_lazy_page_release_calls_release_page_or_backend(ui_env):
    from neopedal.ui.lazy_page import LazyPage

    released = []

    class WithReleasePage(QWidget):
        def release_page(self):
            released.append("page")

    class WithBackend(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.backend = type("B", (), {"release": lambda self: released.append("backend")})()

    stack = QStackedWidget()
    pages = [LazyPage(stack, WithReleasePage), LazyPage(stack, WithBackend)]
    for page in pages:
        stack.addWidget(page)
        page.ensure_page()
    try:
        assert all(page.release() for page in pages) and released == ["page", "backend"]
    finally:
        stack.deleteLater()
        flush()


@pytest.mark.parametrize("module_name, class_name, args", [
    ("overlay_view", "OverlayView", ()),
    ("module_view", "ModuleList", ("mctrl",)),
    ("preset_view", "PresetList", ()),
    ("hotkey_view", "HotkeyList", ()),
    ("pace_notes_view", "PaceNotesControl", ()),
])
def test_main_pages_release_backend(ui_env, module_name, class_name, args):
    from importlib import import_module

    from neopedal.module_control import mctrl

    module = import_module(f"neopedal.ui.{module_name}")
    parent = QWidget()
    page = getattr(module, class_name)(parent, *(mctrl if arg == "mctrl" else arg for arg in args))
    try:
        assert callable(page.release_page)
        page.release_page()
        backend = page.backend
        if backend is not None and hasattr(backend, "_page_released"):
            assert backend._page_released
        page.release_page()  # twice: no error
    finally:
        parent.deleteLater()
        flush()


def test_home_page_release_backend(ui_env):
    from neopedal.ui.home_view import HomeView

    parent = QWidget()
    page = HomeView(parent, QApplication.activeWindow() or parent, lambda key: None)
    try:
        page.release_page()
        assert page.backend._page_released
    finally:
        parent.deleteLater()
        flush()
