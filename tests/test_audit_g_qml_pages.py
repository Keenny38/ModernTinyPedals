"""Audit G, QML pages: director note field saved for the driver edited, laps popup not opened again while
closing, hold countdown timer stopped once run out, car rows recycled without color animation; replay
camera & HUD checks kept on the game state; Overlay Options Apply & Ctrl+S commit the field being edited,
preview not drawn while its panel is hidden; keyboard focus back to the list after a popup or menu closes
(driver stats, race results, race history)"""

import time

import pytest
from PySide6.QtCore import QCoreApplication, QMetaObject, QObject, QPoint, Qt
from PySide6.QtTest import QTest

from neopedal.setting import cfg
from tests.test_broadcast_director import car, director_page, poll, race_answers  # noqa: F401
from tests.test_driver_stats_viewer import dialogs, page  # noqa: F401
from tests.test_game_info import GAME_ANSWERS, answered, replays_page, wait_requests  # noqa: F401
from tests.test_overlay_options import options, window  # noqa: F401
from tests.test_perf_page_state import qml_warnings  # noqa: F401


def pump(seconds: float = 0.0, count: int = 5):
    end = time.monotonic() + seconds
    while True:
        for _ in range(count):
            QCoreApplication.processEvents()
        if time.monotonic() >= end:
            return
        time.sleep(0.01)


def wait_until(condition, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def items_of(root) -> list:
    found, stack = [], [root]
    while stack:
        item = stack.pop()
        found.append(item)
        stack.extend(item.childItems())
    return found


def item_named(root, name: str):
    return next((item for item in items_of(root) if item.objectName() == name), None)


def item_of_type(root, type_name: str):
    return next((item for item in items_of(root) if type_name in item.metaObject().className()), None)


def objects_of_type(root, type_name: str) -> list:
    return [obj for obj in root.findChildren(QObject) if type_name in obj.metaObject().className()]


def click(view, item):
    center = item.mapToScene(item.boundingRect().center())
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(round(center.x()), round(center.y())))


def leave_focus_on_window(view):
    """Focus on the window content item, as Qt leaves it when it has nothing to give focus back to"""
    quick = view.quickWindow()
    for _ in range(10):  # focus dropped up the focus scopes
        item = quick.activeFocusItem()
        if item is None or item == quick.contentItem():
            break
        item.setFocus(False)
    assert quick.activeFocusItem() == quick.contentItem()


def menu_closes_to(view, menu, target):
    """Menu opened then closed: keyboard focus on target item, not left on the window"""
    leave_focus_on_window(view)
    QMetaObject.invokeMethod(menu, "open")
    assert wait_until(lambda: menu.property("opened"))
    assert not target.property("activeFocus")
    QMetaObject.invokeMethod(menu, "close")
    return wait_until(lambda: not menu.property("visible") and target.property("activeFocus"))


# --- Broadcast Director
def shown_director(director, *cars):
    poll(director, race_answers(100.0, *cars))
    director.resize(1500, 950)
    director.show()
    pump(0.1)
    return director.backend, director.view.rootObject()


def test_note_saved_for_driver_edited_and_binding_kept(qml_warnings, director_page):  # noqa: F811
    backend, root = shown_director(director_page, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0))
    backend.selectCar(1)
    pump()
    field = item_named(root, "noteField")
    assert field is not None and field.property("text") == ""
    field.forceActiveFocus()
    QTest.keyClicks(director_page.view, "Fast starter")
    backend.sheetCarChanged.emit()  # logo or picture arrived while typing: typed text kept
    pump()
    assert field.property("text") == "Fast starter"
    backend.selectCar(2)  # other car picked while typing: note saved for the driver edited
    pump()
    assert backend.notes == {"Driver 1": "Fast starter"}
    assert field.property("text") == "" and not field.property("activeFocus")
    backend.setDriverNote("Driver 2", "Pole sitter")
    pump()
    assert field.property("text") == "Pole sitter"
    # Esc: note put back, nothing saved, text still follows the sheet
    field.forceActiveFocus()
    QTest.keyClicks(director_page.view, " again")
    QTest.keyClick(director_page.view, Qt.Key.Key_Escape)
    pump()
    assert field.property("text") == "Pole sitter" and backend.notes["Driver 2"] == "Pole sitter"
    backend.setDriverNote("Driver 2", "Rookie")
    pump()
    assert field.property("text") == "Rookie"
    # Enter saves, edit continued afterwards not overwritten by the sheet
    field.forceActiveFocus()
    QTest.keyClicks(director_page.view, " driver")
    QTest.keyClick(director_page.view, Qt.Key.Key_Return)
    pump()
    assert backend.notes["Driver 2"] == "Rookie driver"
    QTest.keyClicks(director_page.view, "!")
    backend.sheetCarChanged.emit()
    pump()
    assert field.property("text") == "Rookie driver!"
    backend.selectCar(1)
    pump()
    assert backend.notes == {"Driver 1": "Fast starter", "Driver 2": "Rookie driver!"}
    assert field.property("text") == "Fast starter"
    backend.selectCar(1)  # sheet closed: nothing more saved
    pump()
    assert backend.notes == {"Driver 1": "Fast starter", "Driver 2": "Rookie driver!"}
    assert not qml_warnings, qml_warnings


def test_laps_popup_not_opened_again_while_closing(qml_warnings, director_page):  # noqa: F811
    backend, root = shown_director(director_page, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0))
    popup = objects_of_type(root, "DirectorLaps")[0]
    backend.showLaps(1)
    assert wait_until(lambda: popup.property("opened"))
    QMetaObject.invokeMethod(popup, "close")
    assert not backend.lapsOpen  # at once, not after the exit transition
    backend.lapsChanged.emit()  # lap answer during the exit transition
    assert wait_until(lambda: not popup.property("visible"))
    pump(0.3)
    assert not popup.property("visible") and not backend.lapsOpen
    backend.showLaps(2)
    assert wait_until(lambda: popup.property("opened"))
    backend.showLaps(-1)
    assert wait_until(lambda: not popup.property("visible"))
    assert not qml_warnings, qml_warnings


def test_hold_countdown_timer_stops_once_run_out(director_page, monkeypatch):  # noqa: F811
    backend, root = shown_director(director_page, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0))
    backend.setMode(2)  # automatic
    hold = [time.time() + 0.6]
    monkeypatch.setattr(backend, "hold_end", lambda: hold[0])
    backend.cutToCar(2)
    backend.update_on_air()
    pump()
    text = next(item for item in items_of(root) if item.metaObject().indexOfProperty("remaining") >= 0)
    timer = objects_of_type(text, "Timer")[0]
    assert backend.onAir["holdMs"] > 0 and timer.property("running")
    assert wait_until(lambda: not timer.property("running"), 3.0)  # was: woke every 500 ms for ever
    hold[0] = time.time() + 5
    backend.update_on_air()
    pump()
    assert timer.property("running") and text.property("visible")


def test_car_rows_recycled_without_color_animation(director_page):  # noqa: F811
    _, root = shown_director(director_page, *(car(slot, slot, distance=1000.0 - slot * 30) for slot in range(1, 9)))
    cars = item_named(root, "carList")
    rows = [item for item in items_of(cars) if item.metaObject().indexOfProperty("tyreRear") >= 0]
    assert rows and all(row.property("live") is True for row in rows)


# --- Game Replays: camera & HUD menu checks
def test_camera_and_hud_checks_follow_game_when_clicked(qml_warnings, replays_page, monkeypatch):  # noqa: F811
    backend = answered(replays_page, GAME_ANSWERS)
    replays_page.resize(1400, 860)
    replays_page.show()
    pump()
    backend.refresh_state()  # answers of page shown first
    wait_requests(backend.request_state)
    backend._timer.stop()  # game state not read again while checking
    monkeypatch.setattr(backend, "send", lambda *commands: None)
    root = replays_page.view.rootObject()
    timing = root.findChild(QObject, "hud_timing")
    chat = root.findChild(QObject, "hud_chat")
    assert chat.property("checked")
    QMetaObject.invokeMethod(chat, "trigger")
    QCoreApplication.processEvents()
    assert not chat.property("checked") and backend.hudState["chat"] is False
    backend.hud = {**backend.hud, "timing": True}
    backend.hudChanged.emit()
    QCoreApplication.processEvents()
    assert timing.property("checked")
    state = backend.state
    backend.state = "offline"  # toggle refused: check kept on game state
    try:
        QMetaObject.invokeMethod(timing, "trigger")
        QCoreApplication.processEvents()
        assert timing.property("checked") and backend.hudState["timing"] is True
    finally:
        backend.state = state
    current = root.findChild(QObject, "camera_" + backend.cameraKey)
    assert current.property("checked")
    QMetaObject.invokeMethod(current, "trigger")  # current camera chosen again: still checked
    pump()
    assert current.property("checked")
    assert not qml_warnings, qml_warnings


# --- Overlay Options
def option_page(main, key):
    from neopedal.ui.overlay_options import open_overlay_options

    opened = open_overlay_options(main, "speedometer", key)
    opened.view.setFocus()
    QTest.qWait(150)
    pump()
    return opened


def number_field(opened, label):
    return next(item for item in items_of(opened.view.rootObject())
                if "NumberField" in item.metaObject().className() and item.property("tip") == label)


def test_ctrl_s_commits_number_being_typed(window, monkeypatch):  # noqa: F811
    from neopedal.i18n.options import option_label
    from neopedal.ui import overlay_options

    monkeypatch.setattr(overlay_options, "run_after_saving", lambda callback: None)
    key = "speed_minimum_reset_cooldown"
    options_page = option_page(window, key)
    field = number_field(options_page, option_label(key))
    field.forceActiveFocus()
    QTest.keyClicks(options_page.view, "7")  # focused field selects its text: replaced, no Enter
    pump()
    assert options_page.backend.is_modified()  # typed number taken at each key, as on the Settings page
    assert window.centralWidget().save_current_page()  # Ctrl+S
    assert cfg.user.setting["speedometer"][key] == 7 and not options_page.backend.is_modified()


def test_apply_button_commits_color_being_typed(window, monkeypatch):  # noqa: F811
    """Another edit pending (Apply shown), color typed without Enter, Apply clicked: color saved too"""
    from neopedal.i18n.options import option_label
    from neopedal.ui import overlay_options

    monkeypatch.setattr(overlay_options, "run_after_saving", lambda callback: None)
    cfg.user.setting["speedometer"]["enable_classic_layout"] = True  # colors are options of classic design
    key = "font_color_speed"
    options_page = option_page(window, key)
    options_page.backend.setNumber("speedometer/opacity", 0.5)
    pump(0.5)  # bar of unsaved changes shown
    root = options_page.view.rootObject()
    field = next(item for item in items_of(root) if "TpTextField" in item.metaObject().className()
                 and item.property("tip") == option_label(key))
    field.forceActiveFocus()
    QMetaObject.invokeMethod(field, "selectAll")
    QTest.keyClicks(options_page.view, "#FF0000")
    pump()
    assert options_page.backend.pendingCount == 2  # typed color taken at each key, as on the Settings page
    apply = next(item for item in items_of(root) if "TpButton" in item.metaObject().className()
                 and item.property("text") == "Apply")
    click(options_page.view, apply)
    pump()
    assert cfg.user.setting["speedometer"]["opacity"] == 0.5
    assert cfg.user.setting["speedometer"][key] == "#FF0000" and not options_page.backend.is_modified()


def test_preview_not_drawn_while_panel_hidden(options):  # noqa: F811
    options.selectOverlay("speedometer")
    options.set_active(True)
    options.render_preview()
    timer = options._preview_timer
    options.setPreviewVisible(False)
    assert not timer.isActive()
    options.setNumber("speedometer/font_size", cfg.user.setting["speedometer"]["font_size"] + 3)
    options.selectOverlay("fuel")
    assert not timer.isActive()  # edits & overlay change: nothing drawn
    options.setPreviewVisible(True)
    assert timer.isActive()  # drawn once shown again
    options.render_preview()
    assert options.previewState == 2


def test_preview_panel_visibility_told_to_backend(window):  # noqa: F811
    options_page = option_page(window, "")
    window.resize(1800, 1000)
    assert wait_until(lambda: options_page.backend._preview_visible)
    window.resize(700, window.height())  # narrow: preview panel hidden
    assert wait_until(lambda: not options_page.backend._preview_visible)
    window.resize(1600, window.height())
    assert wait_until(lambda: options_page.backend._preview_visible)


# --- Keyboard focus back after popups & menus
def test_driver_stats_focus_back_to_table(page):  # noqa: F811
    page.resize(1400, 860)
    page.show()
    pump(0.1)
    root = page.view.rootObject()
    table = item_of_type(root, "StatsTable")
    assert wait_until(lambda: table.property("activeFocus"))
    QTest.keyClick(page.view, Qt.Key.Key_Slash)  # track search popup: focus given back by Qt
    assert wait_until(lambda: not table.property("activeFocus"))
    QTest.keyClick(page.view, Qt.Key.Key_Escape)
    assert wait_until(lambda: table.property("activeFocus"))
    leave_focus_on_window(page.view)  # nothing to give back: table focused
    QMetaObject.invokeMethod(item_of_type(root, "TrackPicker"), "openSearch")
    assert wait_until(lambda: not table.property("activeFocus"))
    QTest.keyClick(page.view, Qt.Key.Key_Escape)
    assert wait_until(lambda: table.property("activeFocus"))
    menus = [menu for menu in objects_of_type(root, "TpMenu") if menu.property("title") in ("", None)
             and "TpMenuItem" not in menu.metaObject().className()]  # menus, not their entries
    assert len(menus) >= 6  # toolbar menus, row & header menus
    for menu in menus:
        assert menu_closes_to(page.view, menu, table), menu


def test_results_session_list_focus_back_after_folder_menu(ui_env):
    from neopedal.ui.race_results_viewer import RaceResultsViewer

    viewer = RaceResultsViewer(None)
    try:
        viewer.resize(1400, 800)
        viewer.show()
        assert wait_until(lambda: viewer.backend.loaded_once)
        pump(0.1)
        panel = item_of_type(viewer.view.rootObject(), "ResultsSessionList")
        listed = item_of_type(panel, "QQuickListView")
        menu = objects_of_type(panel, "TpMenu")[0]
        assert menu_closes_to(viewer.view, menu, listed)
    finally:
        viewer.close()
        viewer.deleteLater()
        pump()


@pytest.mark.usefixtures("ui_env")
def test_race_history_focus_back_after_column_menu(monkeypatch):
    from neopedal.module_info import minfo
    from neopedal.ui import race_calculator
    from tests.test_race_calculator import Host

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    found = Host()
    monkeypatch.setattr(race_calculator.RaceCalculator, "warn", lambda self, text: found.warnings.append(text))
    dialog = race_calculator.RaceCalculator(None)
    try:
        dialog.resize(1400, 900)
        dialog.show()
        view = dialog.ensure_view()
        pump(0.2)
        panel = item_of_type(view.rootObject(), "RaceHistory")
        if panel is None:
            pytest.skip("race history panel not built in this tab")
        listed = item_of_type(panel, "QQuickListView")
        menu = objects_of_type(panel, "TpMenu")[0]
        assert menu_closes_to(view, menu, listed)
    finally:
        dialog.set_unmodified()
        dialog.close()
        dialog.deleteLater()
        pump()

