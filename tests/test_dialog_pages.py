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


def settle():
    """Run pending events, also timers started meanwhile (pages left for another one closed...)"""
    for _ in range(3):
        QApplication.processEvents()


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

    assert parse_rail_items(" home, nope,race_calculator,home ,tools") == ["home", "race_calculator", "tools"]
    # Former fuel calculator & tyre strategy planner entries: merged race calculator, once
    assert parse_rail_items("fuel_calculator,tools,tyre_strategy_planner") == ["race_calculator", "tools"]
    assert default_rail_items() == [
        "home", "widget", "driver_stats_viewer", "race_results_viewer", "game_replays",
        "lap_viewer", "spectate", "race_calculator", "preset", "app_settings",
    ]


def test_default_rail(window):
    from tinypedal.ui.nav_rail import PAGE_INDEX

    keys = rail_keys(window)
    assert f"page:{PAGE_INDEX['pacenotes']}" not in keys
    assert "railTool:race_calculator.RaceCalculator" in keys
    assert not [key for key in keys if "fuel_calculator" in key or "tyre_strategy_planner" in key]
    assert "railTool:driver_stats_viewer.DriverStatsViewer" in keys


def test_customize_rail(window):
    from tinypedal.ui.nav_rail import RailEditor

    view = window.centralWidget()
    view.open_rail_editor()
    pages = view.dialog_pages()
    assert len(pages) == 1 and isinstance(pages[0].dialog, RailEditor)  # shown inside app
    editor = pages[0].dialog
    editor.fill(["home", "pacenotes", "race_calculator"])
    editor.list_entries.setCurrentRow(1)  # pace notes
    editor.move_current(-1)  # to top
    editor.move_current(-1)  # already first: no change
    assert editor.checked_items() == ["pacenotes", "home", "race_calculator"] and editor.is_modified()
    editor.button_save.click()
    assert cfg.application["rail_items"] == "pacenotes,home,race_calculator"
    assert len(rail_keys(window)) == 3 and rail_keys(window)[2] == "railTool:race_calculator.RaceCalculator"
    assert not view.dialog_pages()  # editor page closed
    view._rail_shortcuts[2].activated.emit()  # Ctrl+3: race calculator page
    assert type(view.dialog_pages()[0].dialog).__name__ == "RaceCalculator"


def test_rail_editor_reset_and_nothing_checked(window):
    from tinypedal.ui.nav_rail import RailEditor, default_rail_items

    editor = RailEditor(None)
    editor.fill([])
    assert editor.checked_items() == [] and not editor.picker.label_empty.isHidden()
    editor.reset()
    assert editor.checked_items() == default_rail_items()
    editor.fill([])
    editor.saving()  # empty rail not allowed: default rail
    assert cfg.application["rail_items"] == ",".join(default_rail_items())


# --- Dialog pages
def test_tool_and_config_shown_as_pages(window):
    from tinypedal.ui.config import UserConfig
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.set_current_index(1)
    open_tool("race_calculator.RaceCalculator", window)
    open_tool("race_calculator.RaceCalculator", window)  # same tool: its page again
    assert [type(page.dialog).__name__ for page in view.dialog_pages()] == ["RaceCalculator"]
    assert not [widget for widget in QApplication.topLevelWidgets() if type(widget).__name__ == "RaceCalculator"]

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


def test_lap_viewer_page_releases_vertices(window):
    """Qt Quick page shown inside app like widget tools, page vertices released when closed"""
    from tinypedal.ui.quick.lines import VertexStore, line_strip
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    open_tool("lap_viewer.LapViewer", window)
    pages = view.dialog_pages()
    assert [type(page.dialog).__name__ for page in pages] == ["LapViewer"]
    dialog = pages[0].dialog
    assert not dialog.view.errors() and dialog.view.rootObject() is not None
    VertexStore.set(dialog.backend.prefix + "test", line_strip([0.0, 1.0], [0.0, 1.0]))
    dialog.close()
    assert not view.dialog_pages()
    assert not VertexStore.has(dialog.backend.prefix + "test")


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
    """Preset name & other name inputs: pages too, also when opened from a dialog page"""
    from tinypedal.ui._common import TextInputDialog, embedded_host
    from tinypedal.ui.preset_management import CreatePreset
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    dialog = CreatePreset(view.preset_tab, title="Create new default preset")
    assert embedded_host(dialog) is view
    dialog.close()
    open_tool("heatmap_editor.HeatmapEditor", window)
    editor = view.dialog_pages()[0].dialog
    names = []
    TextInputDialog(editor, "New", "Name:", lambda text: names.append(text) or text != "Taken").show()
    pages = view.dialog_pages()
    assert len(pages) == 2 and isinstance(pages[1].dialog, TextInputDialog)
    assert view._pages.currentWidget() is pages[1]
    pages[1].dialog.edit.setText("Taken")
    pages[1].dialog.accepting()  # refused name: input kept open
    assert len(view.dialog_pages()) == 2
    pages[1].dialog.edit.setText("Dusk")
    pages[1].dialog.accepting()
    assert view.dialog_pages() == pages[:1] and view._pages.currentWidget() is pages[0]  # back to editor
    assert names == ["Taken", "Dusk"]


def test_open_pages_indicator(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.ui.app import NavButton
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    fuel = window.findChild(NavButton, "railTool:race_calculator.RaceCalculator")
    assert view._button_pages.isHidden()
    open_tool("race_calculator.RaceCalculator", window)
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
    assert [page.title for page in view.dialog_pages()] == ["Race Calculator"]  # rail page kept
    assert view._button_pages.isHidden()


def test_left_pages_closed(window):
    """Page left for another one is closed (no pages piling up behind), rail tools are kept"""
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    open_tool("race_calculator.RaceCalculator", window)
    open_tool("heatmap_editor.HeatmapEditor", window)
    open_tool("brake_editor.BrakeEditor", window)
    settle()
    assert [page.title for page in view.dialog_pages()] == ["Race Calculator", "Brake Editor"]
    assert view._button_pages.isHidden()  # nothing behind shown page
    view.set_current_index(1)
    settle()
    assert [page.title for page in view.dialog_pages()] == ["Race Calculator"]
    assert view.go_back() and view._pages.currentWidget().title == "Race Calculator"  # closed pages skipped


def test_left_page_with_unsaved_changes_kept(window):
    from PySide6.QtGui import QColor

    from tinypedal.ui.app import status_color
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    open_tool("brake_editor.BrakeEditor", window)
    editor = view.dialog_pages()[0].dialog
    editor.set_modified()
    view.set_current_index(1)
    settle()
    assert [page.dialog for page in view.dialog_pages()] == [editor]  # kept, closing would ask to save
    assert not view._button_pages.isHidden() and view._button_pages.dot_color == QColor(status_color("warning"))
    editor.set_unmodified()  # saved meanwhile: closed as any page left
    settle()
    assert not view.dialog_pages() and view._button_pages.isHidden()


def test_page_opened_from_page_keeps_it_open(window):
    """Input page opened from a page (new name): page it was opened from kept behind it"""
    from tinypedal.ui._common import TextInputDialog
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    open_tool("heatmap_editor.HeatmapEditor", window)
    editor = view.dialog_pages()[0].dialog
    TextInputDialog(editor, "New", "Name:", lambda text: True).show()
    settle()
    pages = view.dialog_pages()
    assert len(pages) == 2 and isinstance(pages[1].dialog, TextInputDialog) and pages[1].opener is pages[0]
    assert view._button_pages.isHidden()  # editor is not left behind, input is shown over it
    view.set_current_index(1)  # both left
    settle()
    assert not view.dialog_pages()


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
    open_tool("race_calculator.RaceCalculator", window)  # rail page kept in background
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
    open_tool("race_calculator.RaceCalculator", window)
    open_tool("brake_editor.BrakeEditor", window)
    UserConfig(parent=window, key_name="speedometer", preset_name="test", config_type="widget",
               user_setting=cfg.user.setting, default_setting=cfg.default.setting,
               reload_func=lambda: None).open()  # config dialogs are not tools: never reopened
    view.show_page_widget(view.dialog_pages()[0])
    assert view.open_page_paths() == ["*race_calculator.RaceCalculator", "brake_editor.BrakeEditor"]
    window.save_open_pages()
    assert cfg.application["open_pages"] == "*race_calculator.RaceCalculator,brake_editor.BrakeEditor"
    settle()  # pages left for another one closed, remembered at once
    assert view.open_page_paths() == ["*race_calculator.RaceCalculator"]
    assert cfg.application["open_pages"] == "*race_calculator.RaceCalculator"

    # Next startup: shown page (shown again) & rail tools reopened, window not brought to front
    cfg.application["open_pages"] = (
        "race_calculator.RaceCalculator,*brake_editor.BrakeEditor,heatmap_editor.HeatmapEditor,unknown.Tool")
    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    other = app_module.AppWindow()
    try:
        other_view = other.centralWidget()
        assert not other_view.dialog_pages()  # reopened once window is shown
        QApplication.processEvents()
        assert [page.title for page in other_view.dialog_pages()] == ["Race Calculator", "Brake Editor"]
        assert other_view._pages.currentWidget() is other_view.dialog_pages()[1]
        assert not other.isVisible()
    finally:
        for page in other.centralWidget().dialog_pages():
            page.dialog.close()
        other.deleteLater()


def test_open_pages_current_app_page_kept(window):
    from tinypedal.ui.nav_rail import PAGE_INDEX

    view = window.centralWidget()
    view.set_current_index(PAGE_INDEX["preset"])
    # No page was shown at quit: rail tool reopened, other tool left for another page not reopened
    view.restore_pages(["race_calculator.RaceCalculator", "track_map_viewer.TrackMapViewer"])
    assert [page.title for page in view.dialog_pages()] == ["Race Calculator"]
    assert view.current_index() == PAGE_INDEX["preset"]


def test_open_pages_not_remembered_when_disabled(window, monkeypatch):
    from tinypedal.ui.tools_view import open_tool

    open_tool("race_calculator.RaceCalculator", window)
    monkeypatch.setitem(cfg.application, "remember_open_pages", False)
    window.save_open_pages()
    assert cfg.application["open_pages"] == ""


def test_language_change_keeps_open_pages(window):
    from tinypedal.ui.tools_view import open_tool

    open_tool("race_calculator.RaceCalculator", window)
    window.retranslate()
    assert [type(page.dialog).__name__ for page in window.centralWidget().dialog_pages()] == ["RaceCalculator"]


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
    view.set_current_index(PAGE_INDEX["preset"])  # selected entry (last one) scrolled into view
    QApplication.processEvents()
    preset = view._nav.button(PAGE_INDEX["preset"])
    top = preset.mapTo(view._rail_scroll.viewport(), preset.rect().topLeft()).y()
    assert 0 <= top <= view._rail_scroll.viewport().height() - preset.height()


def test_rail_tools_have_no_close_buttons(window):
    from PySide6.QtWidgets import QAbstractButton

    from tinypedal.i18n import tr
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()

    def close_buttons(page):
        return [button for button in page.findChildren(QAbstractButton)
                if button.text() == tr("Close") and not button.isHidden()]

    for path in ("lap_viewer.LapViewer", "driver_stats_viewer.DriverStatsViewer",
                 "race_calculator.RaceCalculator"):
        open_tool(path, window)
        assert not close_buttons(view._pages.currentWidget()), path
    open_tool("heatmap_editor.HeatmapEditor", window)  # not in rail: title & own close buttons
    assert len(close_buttons(view._pages.currentWidget())) == 2
    # Tool removed from rail: its page gets close buttons back
    lap_page = next(page for page in view.dialog_pages() if page.title == "Lap Telemetry Viewer")
    cfg.application["rail_items"] = "home,widget,tools"
    view.build_rail_items()
    assert len(close_buttons(lap_page)) == 1  # title close button (Qt Quick page has no own button)


def test_escape_does_not_close_rail_tool_page(window):
    from PySide6.QtGui import QKeyEvent

    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()

    def escape(dialog):
        QApplication.sendEvent(dialog, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))

    open_tool("race_calculator.RaceCalculator", window)  # in rail: Esc ignored
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
    open_tool("race_calculator.RaceCalculator", window)
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
    assert "RaceCalculator" in [type(dialog).__name__ for dialog in dialogs]  # tool reopened translated
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
    open_tool("race_calculator.RaceCalculator", window)
    window.show()
    hotkey_restart_application()
    assert restarted and cfg.application["open_pages"] == "*race_calculator.RaceCalculator"


def test_go_back_to_previous_pages(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    view.set_current_index(0)
    view.set_current_index(1)
    open_tool("race_calculator.RaceCalculator", window)
    view.set_current_index(3)
    assert view.go_back() and type(view._pages.currentWidget().dialog).__name__ == "RaceCalculator"
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


def test_shown_page_remembered_without_quit(window):
    """Page shown is saved at once: a restart after a crash or a shutdown reopens it"""
    from tinypedal.ui.tools_view import open_tool

    view = window.centralWidget()
    QApplication.processEvents()  # startup pages restored: tracking on
    assert view.track_pages
    view.set_current_index(3)
    view.set_current_index(1)
    assert view.go_back() and cfg.application["last_page_index"] == 3  # not only rail clicks
    open_tool("race_calculator.RaceCalculator", window)
    assert cfg.application["open_pages"] == "*race_calculator.RaceCalculator"  # tool page shown
    view.set_current_index(2)
    assert cfg.application["open_pages"] == "race_calculator.RaceCalculator"
    assert cfg.application["last_page_index"] == 2


def test_last_tool_page_shown_at_next_startup(window, monkeypatch):
    from tinypedal.ui import app as app_module
    from tinypedal.ui.tools_view import open_tool

    QApplication.processEvents()
    open_tool("race_calculator.RaceCalculator", window)  # left shown, app killed (no quit)
    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    other = app_module.AppWindow()
    try:
        QApplication.processEvents()
        current = other.centralWidget()._pages.currentWidget()
        assert type(current.dialog).__name__ == "RaceCalculator"
    finally:
        for page in other.centralWidget().dialog_pages():
            if page.dialog is not None:
                page.dialog.close()
        other.deleteLater()


def test_quit_keeps_saved_pages(window, monkeypatch):
    from tinypedal import loader
    from tinypedal.ui.tools_view import open_tool

    QApplication.processEvents()
    open_tool("race_calculator.RaceCalculator", window)
    monkeypatch.setattr(loader, "close", lambda: None)
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
    monkeypatch.setattr(type(window), "save_window_state", lambda self: None, raising=False)
    monkeypatch.setattr(window, "_AppWindow__break_signal", lambda: None, raising=False)
    window.quit_app()  # pages closed after saving: closing them does not overwrite
    assert cfg.application["open_pages"] == "*race_calculator.RaceCalculator"


def test_former_tool_pages_reopen_as_race_calculator(window, monkeypatch):
    from tinypedal.ui import app as app_module

    cfg.application["open_pages"] = "*fuel_calculator.FuelCalculator,tyre_strategy_planner.TyreStrategyPlanner"
    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    other = app_module.AppWindow()
    try:
        QApplication.processEvents()
        pages = other.centralWidget().dialog_pages()
        assert [type(page.dialog).__name__ for page in pages] == ["RaceCalculator"]  # merged: once
        assert other.centralWidget()._pages.currentWidget() is pages[0]
    finally:
        for page in other.centralWidget().dialog_pages():
            if page.dialog is not None:
                page.dialog.close()
        other.deleteLater()


def test_language_change_with_timer_pages_open(window):
    """Pages with a refresh timer deleted by a language change stop it (timer firing on a deleted page crashed)"""
    import time

    from tinypedal.ui.tools_view import open_tool

    window.show()
    open_tool("perf_view.PerformanceView", window)
    open_tool("replay_view.ReplayView", window)
    language = cfg.application["language"]
    cfg.application["language"] = "Français"
    window.retranslate()
    try:
        deadline = time.monotonic() + 1.5  # performance page refreshes every second
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
    finally:
        cfg.application["language"] = language
        window.retranslate()  # back to English for other tests


def test_language_change_unloads_qml_before_backends(window):
    """Pages deleted by a language change: QML views unloaded first (was: hundreds of
    "Cannot read property ... of null" errors, QML bindings reading deleted backends)"""
    import time

    from PySide6.QtCore import qInstallMessageHandler

    from tinypedal.ui.tools_view import open_tool

    window.show()
    for path in ("driver_stats_viewer.DriverStatsViewer", "game_replays.GameReplays",
                 "race_results_viewer.RaceResultsViewer", "track_map_viewer.TrackMapViewer"):
        open_tool(path, window)
        QApplication.processEvents()
    errors = []
    previous = qInstallMessageHandler(
        lambda mode, context, message: errors.append(message) if "of null" in message else None)
    language = cfg.application["language"]
    try:
        cfg.application["language"] = "Français"
        window.retranslate()
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            QApplication.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            time.sleep(0.02)
    finally:
        qInstallMessageHandler(previous)
        cfg.application["language"] = language
        window.retranslate()  # back to English for other tests
    assert not errors, errors[:5]


def test_quit_unloads_qml_views(window, monkeypatch):
    """Quit: QML views unloaded before their backends are deleted with the window"""
    from PySide6.QtQuickWidgets import QQuickWidget

    from tinypedal import loader
    from tinypedal.ui.nav_rail import PAGE_INDEX
    from tinypedal.ui.tools_view import open_tool

    window.show()
    view = window.centralWidget()
    for key in ("widget", "module", "preset", "spectate"):  # Qt Quick pages
        view.select_page(PAGE_INDEX[key])
        QApplication.processEvents()
    open_tool("driver_stats_viewer.DriverStatsViewer", window)
    QApplication.processEvents()
    monkeypatch.setattr(loader, "close", lambda: None)
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
    monkeypatch.setattr(type(window), "save_window_state", lambda self: None, raising=False)
    monkeypatch.setattr(window, "_AppWindow__break_signal", lambda: None, raising=False)
    views = window.findChildren(QQuickWidget)
    assert any(not view.source().isEmpty() for view in views)
    window.quit_app()
    assert all(view.source().isEmpty() for view in window.findChildren(QQuickWidget))
