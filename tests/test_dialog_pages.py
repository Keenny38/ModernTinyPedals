"""Main window: customizable navigation rail, dialogs shown as pages inside app"""

from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from tinypedal import app_signal
from tinypedal.setting import cfg


@pytest.fixture
def window(ui_env, monkeypatch):
    from tinypedal.ui import app as app_module

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
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def rail_keys(main) -> list[str]:
    from tinypedal.ui.app import NavButton

    view = main.centralWidget()
    keys = []
    for index in range(view._rail_items.count()):
        button = view._rail_items.itemAt(index).widget()
        if isinstance(button, NavButton):
            keys.append(button.objectName() or f"page:{view._nav.id(button)}")
    return keys


# --- Navigation rail
def test_rail_items_setting():
    from tinypedal.ui.nav_rail import default_rail_items, parse_rail_items

    assert parse_rail_items(" home, nope,fuel_calculator,home ,tools") == ["home", "fuel_calculator", "tools"]
    default = default_rail_items()
    assert "pacenotes" not in default
    assert default[-3:] == ["driver_stats_viewer", "fuel_calculator", "tyre_strategy_planner"]


def test_default_rail(window):
    from tinypedal.ui.nav_rail import PAGE_INDEX

    keys = rail_keys(window)
    assert f"page:{PAGE_INDEX['pacenotes']}" not in keys
    assert "railTool:fuel_calculator.FuelCalculator" in keys
    assert "railTool:tyre_strategy_planner.TyreStrategyPlanner" in keys
    assert "railTool:driver_stats_viewer.DriverStatsViewer" in keys


def test_customize_rail(window):
    from tinypedal.ui.nav_rail import RailEditor

    view = window.centralWidget()
    view.open_rail_editor()
    pages = view.dialog_pages()
    assert len(pages) == 1 and isinstance(pages[0].dialog, RailEditor)  # shown inside app
    editor = pages[0].dialog
    entries = editor.list_entries
    for row in range(entries.count()):
        item = entries.item(row)
        keep = item.data(Qt.ItemDataRole.UserRole) in ("home", "pacenotes", "fuel_calculator")
        item.setCheckState(Qt.CheckState.Checked if keep else Qt.CheckState.Unchecked)
    row = next(row for row in range(entries.count()) if entries.item(row).data(Qt.ItemDataRole.UserRole) == "pacenotes")
    entries.setCurrentRow(row)
    editor.move_current(-row)  # to top
    editor.move_current(-1)  # already first: no change
    editor.saving()
    assert cfg.application["rail_items"] == "pacenotes,home,fuel_calculator"
    assert len(rail_keys(window)) == 3 and rail_keys(window)[2] == "railTool:fuel_calculator.FuelCalculator"
    assert not view.dialog_pages()  # editor page closed
    view._rail_shortcuts[2].activated.emit()  # Ctrl+3: fuel calculator page
    assert type(view.dialog_pages()[0].dialog).__name__ == "FuelCalculator"


def test_rail_editor_reset_and_nothing_checked(window):
    from tinypedal.ui.nav_rail import RailEditor, default_rail_items

    editor = RailEditor(None)
    for row in range(editor.list_entries.count()):
        editor.list_entries.item(row).setCheckState(Qt.CheckState.Unchecked)
    assert editor.checked_items() == []
    editor.fill(default_rail_items())
    assert editor.checked_items() == default_rail_items()
    for row in range(editor.list_entries.count()):
        editor.list_entries.item(row).setCheckState(Qt.CheckState.Unchecked)
    editor.saving()  # empty rail not allowed: default rail
    assert cfg.application["rail_items"] == ",".join(default_rail_items())


# --- Dialog pages
def test_tool_and_config_shown_as_pages(window):
    from tinypedal.ui.config import UserConfig
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.set_current_index(1)
    open_tool("fuel_calculator.FuelCalculator", window)
    open_tool("fuel_calculator.FuelCalculator", window)  # same tool: its page again
    assert [type(page.dialog).__name__ for page in view.dialog_pages()] == ["FuelCalculator"]
    assert not [widget for widget in QApplication.topLevelWidgets() if type(widget).__name__ == "FuelCalculator"]

    def open_config(name):
        UserConfig(parent=window, key_name=name, preset_name="test", config_type="widget",
                   user_setting=cfg.user.setting, default_setting=cfg.default.setting, reload_func=lambda: None).open()

    open_config("speedometer")
    open_config("relative")  # another config: own page, no "already opened" error
    open_config("speedometer")  # same config: shown again, no duplicate
    titles = [page.dialog.windowTitle() for page in view.dialog_pages()]
    assert len(titles) == 3 and len(set(titles)) == 3
    assert view._pages.currentWidget().dialog.key_name == "speedometer"
    # Closing pages one by one shows previous dialog page, then page opened before
    for page in reversed(view.dialog_pages()):
        page.dialog.close()
    assert not view.dialog_pages() and view.current_index() == 1


def test_dialog_from_dialog_stays_popup(window):
    from tinypedal.ui._common import BatchOffset, embedded_host
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    open_tool("heatmap_editor.HeatmapEditor", window)
    editor = view.dialog_pages()[0].dialog
    offset = BatchOffset(editor, lambda *args: None)
    assert embedded_host(offset) is None  # opened from a dialog: small popup over it
    offset.close()


def test_inputs_shown_as_pages(window, monkeypatch):
    """Preset name & theme name inputs: pages too, also when opened from a dialog page"""
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.ui._common import TextInputDialog, embedded_host
    from tinypedal.ui.preset_management import CreatePreset
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    dialog = CreatePreset(view.preset_tab, title="Create new default preset")
    assert embedded_host(dialog) is view
    dialog.close()
    open_tool("theme_editor.ThemeEditor", window)
    editor = view.dialog_pages()[0].dialog
    editor.new_theme()
    pages = view.dialog_pages()
    assert len(pages) == 2 and isinstance(pages[1].dialog, TextInputDialog)
    assert view._pages.currentWidget() is pages[1]
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    pages[1].dialog.edit.setText("Global")
    pages[1].dialog.accepting()  # invalid name: warned, input kept open
    assert warnings and len(view.dialog_pages()) == 2
    pages[1].dialog.edit.setText("Dusk")
    pages[1].dialog.accepting()
    assert view.dialog_pages() == pages[:1] and view._pages.currentWidget() is pages[0]  # back to editor
    assert editor.theme_list.currentText() == "Dusk"
    editor.set_unmodified()


def test_open_pages_indicator(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.ui.app import NavButton
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    fuel = window.findChild(NavButton, "railTool:fuel_calculator.FuelCalculator")
    assert view._button_pages.isHidden()
    open_tool("fuel_calculator.FuelCalculator", window)
    assert view._button_pages.isHidden()  # rail tool: a page like any other, not an open page
    open_tool("heatmap_editor.HeatmapEditor", window)
    open_tool("brake_editor.BrakeEditor", window)
    assert not fuel.isChecked()
    assert not view._button_pages.isHidden() and view._button_pages.toolTip().endswith("2")
    # Close all (open pages menu): editor with unsaved changes asks, cancel keeps it open
    editor = view.dialog_pages()[2].dialog
    editor.set_modified()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Cancel))
    assert not view.close_all_pages(view.other_pages())
    assert len(view.dialog_pages()) == 3 and view._pages.currentWidget().dialog is editor
    editor.set_unmodified()
    assert view.close_all_pages(view.other_pages())
    assert [page.title for page in view.dialog_pages()] == ["Fuel Calculator"]  # rail page kept
    assert view._button_pages.isHidden()


def test_lap_viewer_opened_from_navigation_rail(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.ui.app import NavButton

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    view = window.centralWidget()
    button = window.findChild(NavButton, "railTool:lap_viewer.LapViewer")
    assert button is not None and not button.isChecked()
    button.click()
    # Shown as page inside app, not as separate window, selected in rail like other pages, no close button
    assert not [widget for widget in QApplication.topLevelWidgets() if type(widget).__name__ == "LapViewer"]
    pages = view.dialog_pages()
    assert len(pages) == 1 and type(pages[0].dialog).__name__ == "LapViewer"
    assert view._pages.currentWidget() is pages[0]
    assert button.isChecked() and not [b for b in view._nav.buttons() if b.isChecked()]
    assert pages[0]._button_close.isHidden()
    view.set_current_index(0)  # other page, viewer kept
    assert not button.isChecked() and view._nav.button(0).isChecked()
    button.click()  # its page shown again, no second viewer, no warning
    assert view.dialog_pages() == pages and view._pages.currentWidget() is pages[0]
    assert button.isChecked()
    button.click()  # clicking selected entry keeps it selected
    assert button.isChecked()
    assert not warnings
    pages[0].dialog.close()  # closed: page removed, back to previous page
    assert not view.dialog_pages() and view.current_index() == 0
    assert not button.isChecked()


def test_closed_page_goes_back_to_page_shown_before(window):
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    open_tool("fuel_calculator.FuelCalculator", window)  # rail page kept in background
    view.set_current_index(1)
    open_tool("heatmap_editor.HeatmapEditor", window)
    view.dialog_pages()[-1].dialog.close()
    assert view.current_index() == 1  # widget page, not fuel calculator page


def test_window_grows_for_wide_page_and_restores(window):
    from PySide6.QtCore import QSize

    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    window.resize(QSize(480, 520))
    window.show()
    QCoreApplication.processEvents()
    small = window.size()
    open_tool("driver_stats_viewer.DriverStatsViewer", window)
    page = view.dialog_pages()[0]
    assert page.dialog.minimumWidth() == 0  # window minimum dropped, page scrolls instead
    assert page.preferred_size.width() > small.width()
    screen_width = window.screen().availableGeometry().width()
    assert window.width() == min(page.preferred_size.width() + (small.width() - view._pages.width()), screen_width) \
        or window.width() > small.width()
    grown = window.size()
    view.set_current_index(0)  # browsing pages: no resize back and forth
    assert window.size() == grown
    view.show_page_widget(page)
    assert window.size() == grown
    page.dialog.close()  # page needing it closed: size before
    assert window.width() == small.width()
    assert window.height() == max(small.height(), window.minimumSizeHint().height())
    open_tool("driver_stats_viewer.DriverStatsViewer", window)  # grows again, user resizes: kept
    window.resize(window.width() + 10, window.height())
    view.window_resized_by_user()
    grown = window.size()
    view.dialog_pages()[0].dialog.close()
    assert window.size() == grown


def test_hidden_tool_page_skips_refresh(window, monkeypatch):
    from tinypedal.ui.tools_view import open_tool

    calls = []
    view = window.centralWidget()
    window.show()
    open_tool("perf_view.PerformanceView", window)
    page = view.dialog_pages()[0]
    monkeypatch.setattr(type(page.dialog), "refresh", lambda self: calls.append(1))
    page.dialog.timerEvent(None)
    assert calls == [1]  # shown: refreshed
    view.set_current_index(0)  # other page: tool kept open, hidden
    page.dialog.timerEvent(None)
    assert calls == [1]  # no work while hidden


# --- Open pages reopened at startup
def test_open_pages_saved_and_reopened(window, monkeypatch):
    from tinypedal.ui import app as app_module
    from tinypedal.ui.config import UserConfig
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    open_tool("fuel_calculator.FuelCalculator", window)
    open_tool("brake_editor.BrakeEditor", window)
    UserConfig(parent=window, key_name="speedometer", preset_name="test", config_type="widget",
               user_setting=cfg.user.setting, default_setting=cfg.default.setting,
               reload_func=lambda: None).open()  # config dialogs are not tools: never reopened
    view.show_page_widget(view.dialog_pages()[0])
    assert view.open_page_paths() == ["*fuel_calculator.FuelCalculator", "brake_editor.BrakeEditor"]
    window.save_open_pages()
    assert cfg.application["open_pages"] == "*fuel_calculator.FuelCalculator,brake_editor.BrakeEditor"

    # Next startup: same pages, shown page shown again, window not brought to front
    cfg.application["open_pages"] += ",unknown.Tool"
    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    other = app_module.AppWindow()
    try:
        other_view = other.centralWidget()
        assert not other_view.dialog_pages()  # reopened once window is shown
        QApplication.processEvents()
        assert [page.title for page in other_view.dialog_pages()] == ["Fuel Calculator", "Brake Editor"]
        assert other_view._pages.currentWidget() is other_view.dialog_pages()[0]
        assert not other.isVisible()
    finally:
        for page in other.centralWidget().dialog_pages():
            page.dialog.close()
        other.deleteLater()


def test_open_pages_current_app_page_kept(window):
    from tinypedal.ui.nav_rail import PAGE_INDEX

    view = window.centralWidget()
    view.set_current_index(PAGE_INDEX["preset"])
    view.restore_pages(["track_map_viewer.TrackMapViewer"])  # no page was shown at quit
    assert len(view.dialog_pages()) == 1 and view.current_index() == PAGE_INDEX["preset"]


def test_open_pages_not_remembered_when_disabled(window, monkeypatch):
    from tinypedal.ui.tools_view import open_tool

    open_tool("fuel_calculator.FuelCalculator", window)
    monkeypatch.setitem(cfg.application, "remember_open_pages", False)
    window.save_open_pages()
    assert cfg.application["open_pages"] == ""


def test_language_change_keeps_open_pages(window):
    from tinypedal.ui.tools_view import open_tool

    open_tool("fuel_calculator.FuelCalculator", window)
    window.retranslate()
    assert [type(page.dialog).__name__ for page in window.centralWidget().dialog_pages()] == ["FuelCalculator"]


def test_rail_entries_keep_size_and_scroll(window):
    from tinypedal.ui.app import NavButton
    from tinypedal.ui.nav_rail import PAGE_INDEX

    view = window.centralWidget()
    window.resize(700, 900)
    window.show()
    QApplication.processEvents()
    buttons = [view._rail_items.itemAt(index).widget() for index in range(view._rail_items.count())]
    heights = {button.height() for button in buttons if isinstance(button, NavButton)}
    width = view._rail.width()
    window.resize(700, 420)  # too short for every entry
    QApplication.processEvents()
    assert {button.height() for button in buttons if isinstance(button, NavButton)} == heights
    assert view._rail.width() == width  # no squeeze when scroll bar shows
    bar = view._rail_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    view.set_current_index(PAGE_INDEX["tools"])  # selected entry scrolled into view
    QApplication.processEvents()
    tools = view._nav.button(PAGE_INDEX["tools"])
    top = tools.mapTo(view._rail_scroll.viewport(), tools.rect().topLeft()).y()
    assert 0 <= top <= view._rail_scroll.viewport().height() - tools.height()


def test_rail_tools_have_no_close_buttons(window):
    from PySide6.QtWidgets import QAbstractButton

    from tinypedal.i18n import tr
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()

    def close_buttons(page):
        return [button for button in page.findChildren(QAbstractButton)
                if button.text() == tr("Close") and not button.isHidden()]

    for path in ("lap_viewer.LapViewer", "driver_stats_viewer.DriverStatsViewer",
                 "fuel_calculator.FuelCalculator", "tyre_strategy_planner.TyreStrategyPlanner"):
        open_tool(path, window)
        assert not close_buttons(view._pages.currentWidget()), path
    open_tool("heatmap_editor.HeatmapEditor", window)  # not in rail: title & own close buttons
    assert len(close_buttons(view._pages.currentWidget())) == 2
    # Tool removed from rail: its page gets close buttons back
    lap_page = next(page for page in view.dialog_pages() if page.title == "Lap Telemetry Viewer")
    cfg.application["rail_items"] = "home,widget,tools"
    view.build_rail_items()
    assert len(close_buttons(lap_page)) == 2


def test_escape_does_not_close_rail_tool_page(window):
    from PySide6.QtGui import QKeyEvent

    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()

    def escape(dialog):
        QApplication.sendEvent(dialog, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))

    open_tool("fuel_calculator.FuelCalculator", window)  # in rail: Esc ignored
    escape(view.dialog_pages()[0].dialog)
    assert len(view.dialog_pages()) == 1
    open_tool("heatmap_editor.HeatmapEditor", window)  # not in rail: Esc closes
    escape(view.dialog_pages()[1].dialog)
    assert len(view.dialog_pages()) == 1


def test_language_change_keeps_config_and_edited_pages(window):
    from tinypedal.ui.config import UserConfig
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.set_current_index(1)
    open_tool("fuel_calculator.FuelCalculator", window)
    open_tool("heatmap_editor.HeatmapEditor", window)
    editor = view.dialog_pages()[-1].dialog
    editor.set_modified()  # unsaved edits: page kept as it is
    config = UserConfig(parent=window, key_name="speedometer", preset_name="test", config_type="widget",
                        user_setting=cfg.user.setting, default_setting=cfg.default.setting, reload_func=lambda: None)
    config.open()
    window.retranslate()
    new_view = window.centralWidget()
    assert new_view is not view
    dialogs = [page.dialog for page in new_view.dialog_pages()]
    assert editor in dialogs and config in dialogs  # same dialogs, edits kept
    assert "FuelCalculator" in [type(dialog).__name__ for dialog in dialogs]  # tool reopened translated
    assert new_view._pages.currentWidget().dialog is config  # shown page shown again
    config.close()  # back to page shown before, closing still works
    assert config not in [page.dialog for page in new_view.dialog_pages()]
    editor.set_unmodified()


def test_config_reload_skipped_for_deleted_widget(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui._common import run_after_saving

    calls = []

    class Item(QWidget):
        def reload(self):
            calls.append(1)

    item = Item()
    reload = item.reload
    run_after_saving(reload)
    item.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    run_after_saving(reload)  # widget gone (page rebuilt): skipped, no error
    assert calls == [1]


def test_hotkey_restart_saves_open_pages(window, monkeypatch):
    from tinypedal import loader
    from tinypedal.hotkey.command import hotkey_restart_application
    from tinypedal.ui.tools_view import open_tool

    restarted = []
    monkeypatch.setattr(loader, "restart", lambda: restarted.append(1))
    open_tool("fuel_calculator.FuelCalculator", window)
    window.show()
    hotkey_restart_application()
    assert restarted and cfg.application["open_pages"] == "*fuel_calculator.FuelCalculator"


def test_go_back_to_previous_pages(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.set_current_index(0)
    view.set_current_index(1)
    open_tool("fuel_calculator.FuelCalculator", window)
    view.set_current_index(3)
    assert view.go_back() and type(view._pages.currentWidget().dialog).__name__ == "FuelCalculator"
    assert view.go_back() and view.current_index() == 1  # further back, no ping-pong
    window.mousePressEvent(QMouseEvent(  # mouse back button
        QEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), Qt.MouseButton.BackButton,
        Qt.MouseButton.BackButton, Qt.KeyboardModifier.NoModifier))
    assert view.current_index() == 0 and view._nav.button(0).isChecked()
    assert not view.go_back()  # nothing before


def test_rail_fades_show_hidden_entries(window):
    view = window.centralWidget()
    top, bottom = view._rail_fades
    window.resize(700, 900)
    window.show()
    QApplication.processEvents()
    assert top.isHidden() and bottom.isHidden()  # every entry visible
    window.resize(700, 420)
    QApplication.processEvents()
    bar = view._rail_scroll.verticalScrollBar()
    bar.setValue(bar.minimum())
    assert top.isHidden() and not bottom.isHidden()  # entries hidden below
    bar.setValue(bar.maximum())
    assert not top.isHidden() and bottom.isHidden()
    assert not top.grab().isNull()
