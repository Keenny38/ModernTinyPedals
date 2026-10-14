"""Qt Quick pages left hidden a while released (window shown), live pages kept, built again when shown"""

from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget

from neopedal import app_signal
from neopedal.setting import cfg


def flush_deleted():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class QuickPage(QWidget):
    """Page holding a Qt Quick view (source never set: no engine work)"""

    built = 0

    def __init__(self, parent):
        super().__init__(parent)
        from PySide6.QtQuickWidgets import QQuickWidget

        QVBoxLayout(self).addWidget(QQuickWidget(self))
        QuickPage.built += 1


def test_hidden_quick_page_released_after_delay(ui_env):
    from neopedal.ui.lazy_page import IdlePageRelease, LazyPage

    QuickPage.built = 0
    clock = FakeClock()
    stack = QStackedWidget()
    pages = [LazyPage(stack, QuickPage) for _ in range(3)]
    for page in pages:
        stack.addWidget(page)
    calls = []

    def release(page):
        calls.append(page)
        return page.release()

    try:
        stack.show()
        QCoreApplication.processEvents()
        idle = IdlePageRelease(stack, release, delay_ms=60_000, clock=clock)
        stack.setCurrentIndex(1)  # page 0 left
        clock.now += 30
        stack.setCurrentIndex(2)  # page 1 left later
        assert idle._timer.isActive()
        clock.now += 40  # page 0 hidden 70 s, page 1 hidden 40 s
        idle.check()
        assert pages[0].page is None and pages[1].page is not None and pages[2].page is not None
        assert calls == [pages[0]]
        clock.now += 30
        idle.check()
        assert pages[1].page is None and pages[2].page is not None  # shown page never released
        assert not idle._timer.isActive()  # nothing hidden left to watch
        flush_deleted()
        built = QuickPage.built
        stack.setCurrentIndex(0)  # shown again: built again
        QCoreApplication.processEvents()
        assert pages[0].page is not None and QuickPage.built == built + 1
        assert idle._timer.isActive()  # page 2 left: watched
    finally:
        stack.deleteLater()
        flush_deleted()


def test_hidden_page_kept_when_shown_again_or_refused(ui_env):
    from neopedal.ui.lazy_page import IdlePageRelease, LazyPage

    clock = FakeClock()
    stack = QStackedWidget()
    pages = [LazyPage(stack, QuickPage) for _ in range(3)]
    for page in pages:
        stack.addWidget(page)
    answers = {pages[1]: False, pages[2]: None}  # kept for now, kept until shown again
    calls = []

    def release(page):
        calls.append(page)
        return answers.get(page, page.release())

    try:
        stack.show()
        QCoreApplication.processEvents()
        idle = IdlePageRelease(stack, release, delay_ms=60_000, clock=clock)
        stack.setCurrentIndex(1)
        stack.setCurrentIndex(2)
        stack.setCurrentIndex(0)  # page 0 shown again before delay: no longer timed
        clock.now += 120
        idle.check()
        assert calls == [pages[1], pages[2]] and pages[0].page is not None
        calls.clear()
        idle.check()
        assert calls == [pages[1]]  # refused page tried again, page kept until shown again not
    finally:
        stack.deleteLater()
        flush_deleted()


# --- Main window: app pages & tool pages of navigation rail
@pytest.fixture
def window(ui_env, monkeypatch):
    from neopedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    main.deleteLater()
    flush_deleted()
    QCoreApplication.processEvents()


def test_rail_tool_page_released_live_page_kept(window, monkeypatch):
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui.nav_rail import PAGE_INDEX
    from neopedal.ui.tools_view import open_tool

    view = window.centralWidget()
    clock = FakeClock()
    monkeypatch.setattr(view._idle_release, "_clock", clock)
    window.show()
    QApplication.processEvents()
    open_tool("lap_viewer.LapViewer", window)
    open_tool("race_calculator.RaceCalculator", window)  # follows live race: kept
    for page in view.dialog_pages():
        view.show_page_widget(page, bring_to_front=False)
        QApplication.processEvents()
    assert all(page.dialog.findChild(QQuickWidget) is not None for page in view.dialog_pages())
    view.set_current_index(PAGE_INDEX["home"])
    QApplication.processEvents()
    assert [page.title for page in view.dialog_pages()] == ["Lap Telemetry Viewer", "Race Calculator"]
    clock.now += 11 * 60
    view._idle_release.check()
    flush_deleted()
    QApplication.processEvents()
    assert [page.title for page in view.dialog_pages()] == ["Race Calculator"]
    # Still open for the user: remembered for next startup, not twice once reopened
    assert view.open_page_paths(released=True) == ["race_calculator.RaceCalculator", "lap_viewer.LapViewer"]
    assert view.open_page_paths() == ["race_calculator.RaceCalculator"]
    window.save_open_pages()
    assert cfg.application["open_pages"] == "race_calculator.RaceCalculator,lap_viewer.LapViewer"
    open_tool("lap_viewer.LapViewer", window)  # rail entry: built again
    QApplication.processEvents()
    assert len(view.dialog_pages()) == 2
    assert sorted(path.removeprefix("*") for path in view.open_page_paths(released=True)) == [
        "lap_viewer.LapViewer", "race_calculator.RaceCalculator"]
    assert view._idle_released == []


def test_live_pages_released_once_turned_off(window, monkeypatch):
    """Race Calculator & Broadcast Director kept hidden while on; turned off (even while hidden): freed"""
    from neopedal.ui.nav_rail import PAGE_INDEX
    from neopedal.ui.tools_view import open_tool

    view = window.centralWidget()
    clock = FakeClock()
    monkeypatch.setattr(view._idle_release, "_clock", clock)
    window.show()
    QApplication.processEvents()
    open_tool("race_calculator.RaceCalculator", window)
    open_tool("broadcast_director.BroadcastDirector", window)
    pages = {page.title: page for page in view.dialog_pages()}
    assert sorted(pages) == ["Broadcast Director", "Race Calculator"]
    calculator, director = pages["Race Calculator"].dialog, pages["Broadcast Director"].dialog
    calculator.backend.setGameData(True)
    director.backend.setEnabled(True)
    view.set_current_index(PAGE_INDEX["home"])
    QApplication.processEvents()
    clock.now += 11 * 60
    view._idle_release.check()
    flush_deleted()
    assert sorted(page.title for page in view.dialog_pages()) == ["Broadcast Director", "Race Calculator"]
    calculator.backend.setGameData(False)  # turned off while hidden (hotkey, palette)
    clock.now += 60
    view._idle_release.check()
    flush_deleted()
    QApplication.processEvents()
    assert [page.title for page in view.dialog_pages()] == ["Broadcast Director"]
    director.backend.setEnabled(False)
    clock.now += 60
    view._idle_release.check()
    flush_deleted()
    QApplication.processEvents()
    assert view.dialog_pages() == []
    assert sorted(view._idle_released) == ["broadcast_director.BroadcastDirector", "race_calculator.RaceCalculator"]


def test_app_page_released_and_built_again(window, monkeypatch):
    from PySide6.QtQuickWidgets import QQuickWidget

    from neopedal.ui.nav_rail import PAGE_INDEX

    view = window.centralWidget()
    clock = FakeClock()
    monkeypatch.setattr(view._idle_release, "_clock", clock)
    window.show()
    QApplication.processEvents()
    quick_keys = []
    for key in ("widget", "preset", "hotkey"):
        view.set_current_index(PAGE_INDEX[key])
        QApplication.processEvents()
        if view._lazy_pages[key].page.findChild(QQuickWidget) is not None:
            quick_keys.append(key)
    assert quick_keys and "hotkey" not in quick_keys
    view.set_current_index(PAGE_INDEX["home"])
    QApplication.processEvents()
    clock.now += 5 * 60
    view._idle_release.check()
    assert all(view._lazy_pages[key].page is not None for key in ("widget", "preset", "hotkey"))  # too early
    clock.now += 6 * 60
    view._idle_release.check()
    for key in ("widget", "preset", "hotkey"):
        assert (view._lazy_pages[key].page is None) == (key in quick_keys), key  # widget pages kept
    flush_deleted()
    for key in quick_keys:
        view.set_current_index(PAGE_INDEX[key])  # shown again: built again
        QApplication.processEvents()
        assert view._lazy_pages[key].page is not None
        assert view._lazy_pages[key].page.findChild(QQuickWidget) is not None
