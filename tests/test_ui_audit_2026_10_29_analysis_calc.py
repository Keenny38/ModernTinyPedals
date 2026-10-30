"""UI/UX audit 2026-10-29, race calculator (T6, T7, menus, first use, Prepare Race of driver stats): one Source
control (file or game session), live race proposed while a race runs, Follow Live & Plan From Now in the Live tab,
header on the shared toolbar, menus closed by a second click, first use in 3 questions, race prepared for a track
& vehicle"""

import re
import time

import pytest
from PySide6.QtCore import Q_ARG, QCoreApplication, QMetaObject, QObject

from neopedal.module_info import minfo
from neopedal.race_live import LiveRead
from neopedal.setting import cfg
from tests.test_audit_g_qml_pages import item_named
from tests.test_race_calc_fixes import LAPS, history_file, out  # noqa: F401 (fixtures)
from tests.test_race_calculator import host, page  # noqa: F401


def settle():
    for _ in range(3):
        QCoreApplication.processEvents()


def root_of(page):  # noqa: F811
    page.backend.setGameData(True)
    root = page.ensure_view().rootObject()
    settle()
    return root


def child(root, name):
    """Object of the page (toolbar buttons are Repeater items: not QObject children, found among child items)"""
    found = root.findChild(QObject, name) or item_named(root, name)
    assert found is not None, name
    return found


def choose(segmented, index):
    QMetaObject.invokeMethod(segmented, "choose", Q_ARG("QVariant", index))
    settle()


def closed(menu) -> bool:
    """Menu closed once its fade out is over"""
    deadline = time.monotonic() + 2
    while menu.property("visible") and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return not menu.property("visible")


def click(item):
    QMetaObject.invokeMethod(item, "click")
    settle()


# --- T6: one Source control
def test_source_control_switches_between_file_and_game_session(page, host, out):  # noqa: F811
    backend = page.backend
    root = root_of(page)
    source = child(root, "sourceControl")
    assert backend.header["live"] and source.property("currentIndex") == 1
    # File without files loaded before: file dialog at once
    host.open_path = history_file(out / "Spa.consumption")
    choose(source, 0)
    assert not backend.header["live"] and backend.header["source"] == "Spa"
    assert source.property("currentIndex") == 0
    # Game session: laps of the session & followed values (Load Live), chosen again fills in again
    choose(source, 1)
    assert backend.header["live"] and source.property("currentIndex") == 1
    backend.setInput("input_lap_time", 0)
    minfo.history.consumptionDataSet = LAPS[:5]  # restored by the page fixture (monkeypatch)
    choose(source, 1)
    assert backend.values["input_lap_time"] > 0
    minfo.history.consumptionDataSet = ()
    # File with files loaded before: menu under the control, closed by choosing it again
    menu = child(root, "loadFileMenu")
    choose(source, 0)
    assert menu.property("visible")
    choose(source, 0)
    assert closed(menu)
    assert not page.view.errors(), [error.toString() for error in page.view.errors()]


def test_old_live_controls_gone_from_header():
    from tests.test_ui_audit_analysis import zone_files

    text = zone_files()["RaceCalculator.qml"]
    for gone in ('"Load Live"', '"Follow Live"', '"Live Race"', "labelProbes", "headerLevel", "sourceChip"):
        assert gone not in text, gone
    assert "TpToolbar {" in text and "TpAction {" in text


def test_live_race_proposed_while_a_race_runs(page, host, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import race_files

    backend = page.backend
    root = root_of(page)
    proposal = child(root, "liveRaceProposal")
    read = {"text": ""}
    monkeypatch.setattr(race_files, "read_live", lambda *args, **kwargs: LiveRead(None, False, read["text"]))
    backend.refresh_race_state()
    assert not backend.raceProposal and not proposal.property("visible")
    read["text"] = "3 (+0.20) · 0:05:00 / 0:55:00"  # race under way
    backend.refresh_race_state()
    settle()
    assert backend.raceProposal and proposal.property("visible")
    backend.dismissLiveRace()  # Not Now: not proposed again during this race
    backend.refresh_race_state()
    settle()
    assert not backend.raceProposal and not proposal.property("visible")
    read["text"] = ""  # race over, next race: proposed again
    backend.refresh_race_state()
    read["text"] = "1 (+0.10) · 0:01:00 / 0:59:00"
    backend.refresh_race_state()
    assert backend.raceProposal
    backend.setLiveRace(True)  # accepted: planned from now, no proposal
    assert cfg.user.config["fuel_calculator"]["enable_live_race"] and not backend.raceProposal
    backend.setLiveRace(False)
    backend.setGameData(False)  # calculator off: nothing proposed
    assert not backend.raceProposal


def test_follow_live_and_plan_from_now_switches_in_live_tab(page, host):  # noqa: F811
    backend = page.backend
    root = root_of(page)
    backend.setTab(3)
    settle()
    follow = child(root, "followLiveSwitch")
    live_race = child(root, "liveRaceSwitch")
    assert not follow.property("checkable") and not live_race.property("checkable")  # state from the backend only
    click(follow)
    assert cfg.user.config["fuel_calculator"]["enable_follow_live"] is True and follow.property("checked")
    click(follow)
    assert cfg.user.config["fuel_calculator"]["enable_follow_live"] is False and not follow.property("checked")
    click(live_race)
    assert backend.header["liveRace"] and live_race.property("checked")
    click(live_race)
    assert not backend.header["liveRace"] and not live_race.property("checked")
    assert not page.view.errors(), [error.toString() for error in page.view.errors()]


# --- T7: header on the shared toolbar, menus closed by a second click
def test_header_toolbar_actions(page, host):  # noqa: F811
    backend = page.backend
    root = root_of(page)
    page.resize(1600, 800)
    settle()
    plan_button = child(root, "planButton")
    menu = child(root, "planMenu")
    click(plan_button)
    assert menu.property("visible") and plan_button.property("checked")
    click(plan_button)  # second click closes it
    assert closed(menu)
    switch = child(root, "gameDataSwitch")
    assert switch.property("checked")
    click(switch)  # calculator off: only the on / off action left
    assert not backend.game_data and not switch.property("checked")
    for name in ("undoButton", "redoButton", "planButton", "resetButton", "sourceControl"):
        assert not child(root, name).property("visible"), name
    click(switch)
    assert backend.game_data
    assert not page.view.errors(), [error.toString() for error in page.view.errors()]


def test_race_menus_use_the_toggle_helper():
    """Menus of the calculator open under their button with the spacing token and close on a second click"""
    from tests.test_ui_audit_analysis import zone_files

    for name, text in zone_files().items():
        if not name.startswith("Race") or name == "RaceResults.qml":
            continue
        assert ".height + 4)" not in text and ".height + 2)" not in text, name
        assert not re.search(r"\.visible \? \w+\.close\(\)", text), name  # TpMenu.toggleBelow: second click closes


def test_race_switch_never_breaks_its_binding():
    from tests.test_ui_audit_analysis import zone_files

    text = zone_files()["RaceSwitch.qml"]
    assert "checkable: false" in text and "onClicked:" in text and "onToggled" not in text


# --- First use in 3 questions
def test_quick_setup_on_first_use(ui_env, host, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QEvent

    from neopedal.ui import race_calculator
    from neopedal.ui.quick.race_model import SAVED_INPUTS

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    config = cfg.user.config["fuel_calculator"]
    monkeypatch.setitem(config, "show_quick_setup", True)
    for key, value in SAVED_INPUTS.items():
        monkeypatch.setitem(config, key, value)
    dialog = race_calculator.RaceCalculator(None)
    try:
        backend = dialog.backend
        root = root_of(dialog)
        quick = child(root, "quickSetup")
        content = child(root, "calculatorContent")
        assert backend.header["quickSetup"] and quick.property("visible") and not content.property("visible")
        backend.setInput("input_race_minutes", 60)
        backend.setInput("input_pit_seconds", 35)
        click(child(root, "quickDone"))
        assert not backend.header["quickSetup"] and config["show_quick_setup"] is False
        assert content.property("visible") and not quick.property("visible")
        assert backend.values["input_race_minutes"] == 60 and backend.values["input_pit_seconds"] == 35
        assert not dialog.view.errors(), [error.toString() for error in dialog.view.errors()]
    finally:
        dialog.set_unmodified()
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_quick_setup_never_asked_after_calculator_was_used(ui_env, host, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QEvent

    from neopedal.ui import race_calculator

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(minfo.history, "consumptionDataSet", ())
    config = cfg.user.config["fuel_calculator"]
    monkeypatch.setitem(config, "show_quick_setup", True)
    monkeypatch.setitem(config, "input_race_minutes", 120)  # inputs kept from an earlier version
    dialog = race_calculator.RaceCalculator(None)
    try:
        assert not dialog.backend.header["quickSetup"] and config["show_quick_setup"] is False
    finally:
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- Prepare Race (driver stats): consumption history of the track & class, else lap time
@pytest.mark.parametrize("vehicle", ["Hypercar", "Hypercar - Ferrari"])
def test_prepare_race_loads_history_of_track_and_class(page, host, out, monkeypatch, vehicle):  # noqa: F811
    from neopedal.ui import race_calculator, tools_view

    monkeypatch.setattr(cfg.path, "fuel_delta", f"{out.as_posix()}/")
    history_file(out / "Spa - Hypercar.consumption")
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: page)
    page.backend.setGameData(False)
    assert race_calculator.prepare_race(None, "Spa", vehicle, 120.0)
    backend = page.backend
    assert backend.game_data and not backend.header["live"] and backend.header["source"] == "Spa - Hypercar"
    assert backend.values["input_lap_time"] == pytest.approx(90.99, abs=0.02)  # race pace of the laps, not the PB (120)
    assert "Race prepared for" in host.toasts[-1] and "consumption history loaded" in host.toasts[-1]


def test_prepare_race_without_history_fills_lap_time(page, host, out, monkeypatch):  # noqa: F811
    from neopedal.ui import race_calculator, tools_view

    monkeypatch.setattr(cfg.path, "fuel_delta", f"{out.as_posix()}/")
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: page)
    assert race_calculator.prepare_race(None, "Monza", "GT3 - BMW", 107.5)
    assert page.backend.values["input_lap_time"] == pytest.approx(107.5)
    assert "Lap Time" in host.toasts[-1]
    assert page.backend.prepare_race("Monza", "GT3", 0.0) == []
    assert "Nothing recorded for" in host.toasts[-1]
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: None)
    assert not race_calculator.prepare_race(None, "Monza", "GT3", 0.0)  # page could not open


def test_prepare_race_messages_in_french():
    from neopedal.i18n import fr_messages

    rules = [pattern for pattern, _ in fr_messages.MESSAGE_RULES]
    assert any("Race prepared for" in pattern for pattern in rules)
    assert any("Nothing recorded for" in pattern for pattern in rules)
