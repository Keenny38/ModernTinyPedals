"""Memory use: code & pages loaded when used, released while hidden, bounded caches"""

import sys
from contextlib import suppress
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QSystemTrayIcon, QWidget

from tinypedal import app_signal
from tinypedal.const_file import ConfigType
from tinypedal.setting import cfg


def flush_deleted():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- Overlay & module code imported when first started
class Recorder:
    """Module target whose modules are created (imported) on first access"""

    def __init__(self, names):
        self.__all__ = list(names)
        self.loaded = []

    def __getattr__(self, name):
        if name.startswith("_") or name not in self.__dict__.get("__all__", ()):
            raise AttributeError(name)
        self.loaded.append(name)

        class Realtime:
            closed = True

            def __init__(self, config, widget_name):
                self.name = widget_name

            def start(self):
                pass

            def stop(self, discard=False):
                pass

        return SimpleNamespace(Realtime=Realtime)


def test_disabled_module_never_imported(ui_env, monkeypatch):
    from tinypedal.module_control import ModuleControl

    target = Recorder(["module_on", "module_off"])
    monkeypatch.setitem(cfg.user.setting, "module_on", {"enable": True})
    monkeypatch.setitem(cfg.user.setting, "module_off", {"enable": False})
    control = ModuleControl(target, ConfigType.MODULE)
    assert target.loaded == [] and control.number_total == 2  # names known without importing
    control.start()
    assert target.loaded == ["module_on"]
    control.close()
    control.start()
    assert target.loaded == ["module_on"]  # imported once


def test_modern_design_does_not_import_classic_widget(ui_env, monkeypatch):
    from tinypedal import module_control

    target = Recorder(["speedometer"])
    monkeypatch.setitem(cfg.user.setting, "speedometer", {"enable": True})
    modern = Recorder(["speedometer"])
    monkeypatch.setattr(module_control, "uses_modern_design", lambda config, name: True)
    monkeypatch.setattr(module_control, "modern_module", lambda name: getattr(modern, name))
    control = module_control.ModuleControl(target, ConfigType.WIDGET)
    control.start()
    assert modern.loaded == ["speedometer"] and target.loaded == []
    control.close()


def test_widget_module_failing_to_import_is_skipped(ui_env, monkeypatch):
    from tinypedal.module_control import ModuleControl

    class Broken:
        __all__ = ["module_broken"]

        def __getattr__(self, name):
            raise ImportError("broken widget code")

    monkeypatch.setitem(cfg.user.setting, "module_broken", {"enable": True})
    control = ModuleControl(Broken(), ConfigType.MODULE)
    control.start()  # logged, app goes on
    assert control.number_active == 0


def test_widget_package_imports_submodule_on_access():
    from tinypedal import widget

    module = widget.speedometer
    assert module is sys.modules["tinypedal.widget.speedometer"]
    with pytest.raises(AttributeError):
        widget.not_a_widget  # noqa: B018


def test_preview_of_modern_design_skips_classic_widget(ui_env, monkeypatch):
    from tinypedal.ui import widget_preview
    from tinypedal.widget import _modern

    imported = []
    monkeypatch.setattr(_modern, "uses_modern_design", lambda config, name: True)
    monkeypatch.setattr(widget_preview, "import_module", lambda name: imported.append(name))
    pixmap = widget_preview.render_widget(cfg, "speedometer", dict(cfg.user.setting["speedometer"]))
    assert not pixmap.isNull() and imported == []


# --- Pace notes player only while playback enabled
def test_pace_notes_player_only_while_enabled(ui_env, monkeypatch):
    from tinypedal.ui.pace_notes_view import PaceNotesPlayback

    setting = cfg.user.setting["pace_notes_playback"]
    monkeypatch.setitem(setting, "enable", False)
    holder = QWidget()
    try:
        playback = PaceNotesPlayback(holder)
        assert playback.player is None  # Qt Multimedia not needed
        playback.reset_playback()  # no player: nothing to do
        playback.set_volume(50)
        setting["enable"] = True
        playback.refresh()
        player = playback.player
        assert player is not None and player.mcfg is setting
        playback.refresh()
        assert playback.player is player  # kept while enabled
        setting["enable"] = False
        playback.refresh()
        assert playback.player is None
    finally:
        holder.deleteLater()
        flush_deleted()


# --- Main window pages built when first shown, released while window hidden
class CountingPage(QLabel):
    built = 0
    refreshed = 0

    def __init__(self, parent):
        super().__init__("page", parent)
        CountingPage.built += 1

    def refresh(self):
        CountingPage.refreshed += 1


@pytest.fixture
def counting():
    CountingPage.built = CountingPage.refreshed = 0
    return CountingPage


def test_lazy_page_built_once_when_shown(ui_env, counting):
    from tinypedal.ui.lazy_page import LazyPage

    lazy = LazyPage(None, counting)
    try:
        lazy.refresh()
        assert counting.built == 0 and counting.refreshed == 0  # nothing built, nothing refreshed
        lazy.show()
        QCoreApplication.processEvents()
        assert counting.built == 1 and counting.refreshed == 1  # refreshed once built
        assert lazy.ensure_page() is lazy.page and counting.built == 1
        lazy.refresh()
        assert counting.refreshed == 2
    finally:
        lazy.deleteLater()
        flush_deleted()


def test_lazy_page_shown_while_building_is_built_once(ui_env):
    """Page creating its view when shown (Qt Quick page) re-enters showEvent of placeholder"""
    from tinypedal.ui.lazy_page import LazyPage

    built = []

    class SelfShowingPage(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            built.append(self)

        def showEvent(self, event):
            lazy.showEvent(event)  # as Qt does when a native view is created while showing
            super().showEvent(event)

    lazy = LazyPage(None, SelfShowingPage)
    try:
        lazy.show()
        QCoreApplication.processEvents()
        assert len(built) == 1 and lazy.page is built[0]
    finally:
        lazy.deleteLater()
        flush_deleted()


def test_lazy_page_released_and_built_again(ui_env, counting):
    from tinypedal.ui.lazy_page import LazyPage

    lazy = LazyPage(None, counting)
    try:
        page = lazy.ensure_page()
        assert lazy.release() and lazy.page is None
        assert not lazy.release()  # nothing built
        flush_deleted()
        lazy.show()
        QCoreApplication.processEvents()
        assert counting.built == 2 and lazy.page is not None and lazy.page is not page
    finally:
        lazy.deleteLater()
        flush_deleted()


def test_lazy_page_release_clears_qml_before_backend(ui_env, tmp_path):
    """Released page: Qt Quick view emptied before deletion, QML bindings never read the
    backend (child created before the view, so deleted first by Qt)"""
    from PySide6.QtCore import Property, QObject, QUrl, qInstallMessageHandler
    from PySide6.QtQuickWidgets import QQuickWidget

    from tinypedal.ui.lazy_page import LazyPage

    class Backend(QObject):
        @Property(int, constant=True)
        def count(self):
            return 3

    qml = tmp_path / "Page.qml"
    qml.write_text("import QtQuick\nItem { property int shown: backend.count + 1 }\n", encoding="utf-8")

    def factory(parent):
        page = QWidget(parent)
        page.backend = Backend(page)  # created before view, as page backends
        view = QQuickWidget(page)
        view.rootContext().setContextProperty("backend", page.backend)
        view.setSource(QUrl.fromLocalFile(str(qml)))
        assert view.rootObject().property("shown") == 4
        return page

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    lazy = LazyPage(None, factory)
    try:
        lazy.ensure_page()
        assert lazy.release()
        flush_deleted()
        QCoreApplication.processEvents()
    finally:
        qInstallMessageHandler(previous)
        lazy.deleteLater()
        flush_deleted()
    assert not [text for text in messages if "TypeError" in text or "null" in text], messages


def test_pages_released_while_window_hidden(ui_env, counting):
    from tinypedal.ui.lazy_page import LazyPage, PageRelease

    window = QWidget()
    window.resize(200, 200)
    lazy = LazyPage(window, counting)
    try:
        window.show()
        QCoreApplication.processEvents()
        release = PageRelease(window, [lazy], delay_ms=10)
        assert lazy.page is not None and not release._timer.isActive()  # shown: kept
        window.hide()
        assert release._timer.isActive()
        release.release()
        assert lazy.page is None
        flush_deleted()
        release.destroy_window()
        assert not window.testAttribute(Qt.WidgetAttribute.WA_WState_Created)  # graphics freed
        window.show()  # created again by Qt
        QCoreApplication.processEvents()
        assert not release._timer.isActive() and lazy.page is not None
        release.release()  # shown again: nothing released
        assert lazy.page is not None
    finally:
        window.deleteLater()
        flush_deleted()


def test_hidden_window_kept_with_qt_quick_page_open(ui_env):
    from tinypedal.ui.lazy_page import PageRelease

    window = QWidget()
    try:
        window.show()
        QCoreApplication.processEvents()
        release = PageRelease(window, [])
        from PySide6.QtQuickWidgets import QQuickWidget

        QQuickWidget(window)  # open tool page keeps its graphics
        window.hide()
        release.destroy_window()
        assert window.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
    finally:
        window.deleteLater()
        flush_deleted()


@pytest.fixture
def app_window(ui_env, monkeypatch):
    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    cfg.application["last_page_index"] = app_module.PAGE_INDEX["module"]
    window = app_module.AppWindow()
    yield window
    cfg.application["last_page_index"] = 0
    tray = window.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    window.deleteLater()
    QCoreApplication.processEvents()


def test_only_shown_page_built_at_startup(app_window):
    from tinypedal.ui import app as app_module

    view = app_window.centralWidget()
    built = {key for key, page in view._lazy_pages.items() if page.page is not None}
    assert built == {"module"}
    assert view.preset_tab is view._lazy_pages["preset"].page  # built when asked for
    view.set_current_index(app_module.PAGE_INDEX["hotkey"])
    assert view._lazy_pages["hotkey"].page is not None


def test_ui_font_family_set_on_app_font_not_style_sheet(ui_env):
    from tinypedal.main import UI_FONT_FAMILIES, set_app_font
    from tinypedal.ui import set_style_window

    fonts = []
    set_app_font(SimpleNamespace(font=lambda: QFont("System UI"), setFont=fonts.append))
    font = fonts[0]  # app font: every widget & page, created any time
    assert font.families() == [*UI_FONT_FAMILIES, "System UI"]  # system UI font last
    assert font.pointSize() == 10
    assert "Segoe UI Variable" not in set_style_window(10)  # style sheet font-family: memory


# --- Modern overlay text cache in proportion to texts drawn
def test_text_cache_follows_texts_drawn(ui_env, bundled_fonts, monkeypatch):
    from importlib import import_module

    from tinypedal.widget._modern import base

    widget = import_module("tinypedal.widget._modern.speedometer").Realtime(cfg, "speedometer")
    try:
        monkeypatch.setattr(base, "TEXT_CACHE_MIN", 4)
        monkeypatch.setattr(base, "TEXT_CACHE_PER_DRAW", 2)
        widget._text_cache.clear()
        widget._last_texts_drawn = 1  # few texts drawn: few kept
        for value in range(10):
            widget.static_text("value", str(value))
        assert len(widget._text_cache) == 4
        widget._last_texts_drawn = 3  # more texts drawn per paint: more kept
        for value in range(10, 20):
            widget.static_text("value", str(value))
        assert len(widget._text_cache) == 6
        assert widget.text_cache_size() == 6
        widget._last_texts_drawn = 10_000
        assert widget.text_cache_size() == base.TEXT_CACHE_SIZE  # bounded
        widget.state = None
        widget.resize(100, 50)
        widget.grab()  # paint counts texts drawn
        assert widget._last_texts_drawn == widget._texts_drawn
    finally:
        widget.deleteLater()
        flush_deleted()
