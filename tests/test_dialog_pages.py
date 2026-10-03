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
    assert fuel.dot_color is None and view._button_pages.isHidden()
    open_tool("fuel_calculator.FuelCalculator", window)
    open_tool("heatmap_editor.HeatmapEditor", window)
    assert fuel.dot_color is not None  # open in background
    assert not view._button_pages.isHidden() and view._button_pages.toolTip().endswith("2")
    # Close all: editor with unsaved changes asks, cancel keeps it open
    editor = view.dialog_pages()[1].dialog
    editor.set_modified()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Cancel))
    assert not view.close_all_pages()
    assert len(view.dialog_pages()) == 2 and view._pages.currentWidget().dialog is editor
    editor.set_unmodified()
    assert view.close_all_pages()
    assert not view.dialog_pages() and fuel.dot_color is None and view._button_pages.isHidden()


def test_lap_viewer_opened_from_navigation_rail(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.ui.app import NavButton

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    view = window.centralWidget()
    button = window.findChild(NavButton, "railTool:lap_viewer.LapViewer")
    assert button is not None and not button.isCheckable()
    button.click()
    # Shown as page inside app, not as separate window
    assert not [widget for widget in QApplication.topLevelWidgets() if type(widget).__name__ == "LapViewer"]
    pages = view.dialog_pages()
    assert len(pages) == 1 and type(pages[0].dialog).__name__ == "LapViewer"
    assert view._pages.currentWidget() is pages[0]
    view.set_current_index(0)  # other page, viewer kept open
    button.click()  # already open: its page shown again, no second viewer, no warning
    assert view.dialog_pages() == pages and view._pages.currentWidget() is pages[0]
    assert not warnings
    pages[0].dialog.close()  # closed: page removed, back to previous page
    assert not view.dialog_pages() and view.current_index() == 0


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
    view.set_current_index(0)  # back to app page: size before (taller rail if needed: open pages button)
    assert window.width() == small.width()
    assert window.height() == max(small.height(), window.minimumSizeHint().height())
    view.show_page_widget(page)  # grows again, user resizes: kept when leaving
    window.resize(window.width() + 10, window.height())
    view.window_resized_by_user()
    grown = window.size()
    view.set_current_index(0)
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
