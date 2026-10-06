"""Main window size: default size, kept inside screens, saved size, maximized state, pages growing window"""

from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from tinypedal import app_signal
from tinypedal.setting import cfg


def settle():
    for _ in range(3):
        QApplication.processEvents()


def close_windows(*windows):
    for main in windows:
        for page in main.centralWidget().dialog_pages():
            if page.dialog is not None:
                page.dialog.close()
        tray = main.findChild(QSystemTrayIcon)
        if tray:
            tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    for main in windows:
        main.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


@pytest.fixture
def make_window(ui_env):
    """Main window built with given application options, window state set as at startup"""
    from tinypedal.ui.app import AppWindow

    windows = []

    def build(**options):
        cfg.application["show_setup_wizard_at_startup"] = False
        cfg.application.update(options)
        main = AppWindow()
        settle()
        windows.append(main)
        return main

    yield build
    close_windows(*windows)


def screen_area() -> QRect:
    return QGuiApplication.primaryScreen().availableGeometry()


# --- Geometry helpers
def test_fit_rect_moves_then_shrinks():
    from tinypedal.ui.window_geometry import fit_rect

    area = QRect(0, 0, 1000, 800)
    assert fit_rect(QRect(100, 100, 300, 200), area) == QRect(100, 100, 300, 200)  # inside: kept
    assert fit_rect(QRect(900, 700, 300, 200), area) == QRect(700, 600, 300, 200)  # past right & bottom
    assert fit_rect(QRect(-50, -20, 300, 200), area) == QRect(0, 0, 300, 200)  # title bar off screen
    assert fit_rect(QRect(200, 100, 1500, 900), area) == QRect(0, 0, 1000, 800)  # larger than area


def test_screen_for_rect_outside_screens_is_nearest_screen():
    from tinypedal.ui.window_geometry import screen_for

    screen = QGuiApplication.primaryScreen()
    geometry = screen.geometry()
    assert screen_for(QRect(geometry.center(), QSize(100, 100))) is screen
    far_away = QRect(geometry.right() + 5000, geometry.bottom() + 5000, 400, 300)  # screen unplugged
    assert screen_for(far_away) is screen


def test_default_frame_rect_centered_within_screen(make_window):
    from tinypedal.ui.window_geometry import DEFAULT_SCREEN_RATIO, default_frame_rect

    main = make_window()
    area = screen_area()
    frame = default_frame_rect(main)
    assert area.contains(frame)
    assert abs(frame.center().x() - area.center().x()) <= 1
    assert abs(frame.center().y() - area.center().y()) <= 1
    assert frame.width() <= max(round(area.width() * DEFAULT_SCREEN_RATIO), main.minimumSizeHint().width())
    assert frame.width() >= main.minimumSizeHint().width()


# --- Startup
def test_first_launch_comfortable_size_centered(make_window):
    main = make_window(window_width=0, window_height=0, position_x=0, position_y=0)
    area = screen_area()
    hint = main.minimumSizeHint()
    assert main.width() >= hint.width() and main.height() >= hint.height()  # not squeezed to a minimum
    assert main.width() > hint.width() or main.width() >= area.width() * 0.8
    assert area.contains(main.frameGeometry())
    assert abs(main.frameGeometry().center().x() - area.center().x()) <= 1


def test_window_never_smaller_than_its_layout(make_window):
    main = make_window()
    main.resize(10, 10)
    settle()
    hint = main.minimumSizeHint()
    assert main.width() >= hint.width() and main.height() >= hint.height()  # pages never cut


def test_pages_never_squeezed(make_window):
    from tinypedal.ui.window_geometry import page_minimum_size

    main = make_window(window_width=200, window_height=150)  # saved size too small: minimum kept
    settle()
    view = main.centralWidget()
    minimum = page_minimum_size()
    assert view._pages.width() >= minimum.width() and view._pages.height() >= minimum.height()
    main.resize(10, 10)
    settle()
    assert view._pages.width() >= minimum.width() and view._pages.height() >= minimum.height()
    assert view._rail.width() == view._rail.sizeHint().width()  # rail never squeezed either


def test_qml_tool_pages_ask_larger_minimum():
    from tinypedal.ui.driver_stats_viewer import DriverStatsViewer
    from tinypedal.ui.window_geometry import page_minimum_size

    minimum = DriverStatsViewer.page_minimum_size()  # French notes of cards cut below it
    assert minimum.width() > page_minimum_size().width() and minimum.height() > page_minimum_size().height()


def test_shown_page_keeps_its_own_minimum(make_window):
    from tinypedal.ui.tools_view import open_tool
    from tinypedal.ui.window_geometry import max_content_size, page_minimum_size

    main = make_window()
    main.showNormal()
    settle()
    view = main.centralWidget()
    base = view._pages.minimumSize()
    open_tool("lap_viewer.LapViewer", main)  # three panels with their own minimum width
    settle()
    page = view.dialog_pages()[-1]
    assert page.minimum_size.width() > page_minimum_size().width()
    bars = main.size() - view._pages.size()
    largest = max_content_size(main) - bars  # window still fits its screen
    assert view._pages.minimumWidth() == min(page.minimum_size.width(), largest.width())
    assert view._pages.minimumWidth() > base.width()
    main.resize(10, 10)
    settle()
    assert view._pages.width() >= view._pages.minimumWidth()
    view.set_current_index(0)  # other page: base minimum only
    settle()
    assert view._pages.minimumSize() == base


def test_saved_size_and_position_restored(make_window):
    area = screen_area()
    main = make_window(window_width=700, window_height=600, position_x=area.x() + 30, position_y=area.y() + 40)
    assert main.size() == QSize(700, 600)
    assert main.pos() == QPoint(area.x() + 30, area.y() + 40)


def test_off_screen_window_brought_back(make_window):
    area = screen_area()
    main = make_window(
        window_width=700, window_height=600, position_x=area.right() + 3000, position_y=area.bottom() + 3000)
    assert area.contains(main.frameGeometry())
    main = make_window(window_width=area.width() + 900, window_height=area.height() + 600, position_x=area.x() + 50)
    assert area.contains(main.frameGeometry())  # larger than screen (resolution lowered): shrunk


def test_maximized_state_restored_and_kept_when_shown_again(make_window):
    main = make_window(window_maximized=True, window_width=700, window_height=600)
    assert main.isMaximized()
    main.hide()  # minimized to tray
    main.show_app()
    settle()
    assert main.isMaximized()
    main = make_window(window_maximized=True, remember_size=False)
    assert not main.isMaximized()  # follows remember_size


# --- Saving
def test_save_window_state(make_window, ui_env):
    main = make_window()
    main.showNormal()
    main.resize(710, 610)
    main.move(screen_area().topLeft() + QPoint(20, 25))
    settle()
    ui_env.clear()
    main.save_window_state()
    assert (cfg.application["window_width"], cfg.application["window_height"]) == (710, 610)
    assert (cfg.application["position_x"], cfg.application["position_y"]) == (main.x(), main.y())
    assert cfg.application["window_maximized"] is False
    assert ui_env == ["config"]
    ui_env.clear()
    main.save_window_state()
    assert not ui_env  # unchanged: not saved again
    main.showMaximized()
    settle()
    main.save_window_state()
    assert cfg.application["window_maximized"] is True
    assert (cfg.application["window_width"], cfg.application["window_height"]) == (710, 610)  # normal size kept


def test_window_state_saved_shortly_after_change(make_window, ui_env):
    main = make_window()
    main.showNormal()
    settle()
    ui_env.clear()
    main.resize(main.width() + 20, main.height())
    assert main._geometry_timer.isActive()  # saved once changes settle, not after quit only
    main._geometry_timer.timeout.emit()
    assert cfg.application["window_width"] == main.width()
    assert ui_env == ["config"]


def test_window_state_not_tracked_before_startup_state_set(ui_env, monkeypatch):
    from tinypedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    try:
        main.resize(600, 500)
        assert not main._geometry_timer.isActive()
    finally:
        close_windows(main)


# --- Pages growing window
def test_grown_window_kept_on_screen_and_moved_back(make_window):
    from tinypedal.ui.tools_view import open_tool

    area = screen_area()
    main = make_window(window_width=480, window_height=420)
    main.showNormal()
    start = QPoint(area.right() - main.frameGeometry().width() - 10, area.y() + 10)  # near right edge
    main.move(start)
    settle()
    size = main.size()  # at least window layout minimum
    view = main.centralWidget()
    open_tool("race_results_viewer.RaceResultsViewer", main)
    settle()
    assert main.width() > size.width()  # grown for wide page
    assert area.contains(main.frameGeometry())  # moved left instead of going past screen edge
    view.dialog_pages()[0].dialog.close()
    settle()
    assert main.size() == size
    assert main.pos() == start  # moved back


def test_grown_size_never_saved_as_window_size(make_window):
    from tinypedal.ui.tools_view import open_tool

    main = make_window(window_width=480, window_height=420)
    main.showNormal()
    settle()
    size, base_pos = main.size(), main.pos()
    open_tool("race_results_viewer.RaceResultsViewer", main)
    settle()
    assert main.width() > size.width()
    main.save_window_state()  # quit while page is open: page grows window again when reopened
    assert (cfg.application["window_width"], cfg.application["window_height"]) == (size.width(), size.height())
    assert (cfg.application["position_x"], cfg.application["position_y"]) == (base_pos.x(), base_pos.y())
    view = main.centralWidget()
    view.window_resized_by_user()  # size chosen by user is kept
    main.save_window_state()
    assert cfg.application["window_width"] == main.width()


def test_moved_by_user_keeps_position_when_page_closes(make_window):
    from tinypedal.ui.tools_view import open_tool

    main = make_window(window_width=480, window_height=420)
    main.showNormal()
    settle()
    size = main.size()
    open_tool("race_results_viewer.RaceResultsViewer", main)
    settle()
    view = main.centralWidget()
    moved = screen_area().topLeft() + QPoint(5, 5)
    main.move(moved)
    view.window_moved_by_user()
    view.dialog_pages()[0].dialog.close()
    settle()
    assert main.size() == size  # size restored
    assert main.pos() == moved  # position chosen by user kept


def test_reset_window_size(make_window, ui_env):
    from tinypedal.ui.tools_view import open_tool
    from tinypedal.ui.window_geometry import default_frame_rect

    main = make_window(window_width=480, window_height=420)
    main.showNormal()
    open_tool("race_results_viewer.RaceResultsViewer", main)
    settle()
    main.reset_window_size()
    settle()
    expected = default_frame_rect(main)
    assert main.frameGeometry() == expected
    assert cfg.application["window_width"] == main.width()
    assert main.centralWidget().window_base_geometry() == (None, None)  # page closing keeps reset size
    main.showMaximized()
    settle()
    main.reset_window_size()  # maximized: back to normal first
    settle()
    assert not main.isMaximized()
    assert main.frameGeometry() == expected


def test_reset_window_size_in_window_menu_and_palette(make_window):
    from tinypedal.ui.command_palette import build_commands

    main = make_window()
    menu = next(action.menu() for action in main.menuBar().actions() if action.text() == "Window")
    assert "Reset Window Size and Position" in [action.text() for action in menu.actions()]
    assert any(command.title == "Reset Window Size and Position" for command in build_commands(main))
