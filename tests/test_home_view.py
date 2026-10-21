"""Home page: release notes of running version, cards (game, overlay, preset, counts, last session, driver),
checks, quick access, links to pages (driver stats on a session, telemetry on a corner), Qt Quick page"""

import time
from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QSystemTrayIcon

from neopedal import app_signal, update
from neopedal.setting import cfg
from neopedal.ui import home_view
from neopedal.ui.home_checks import CheckState, home_checks
from neopedal.ui.quick import home_backend
from neopedal.userfile.driver_history import SessionRecord

CHANGELOG = """# Changelog

Intro text.

## 0.20.0 (2026-10-05)

New things.

### Overlays

- **Delta graph** added.

## 0.19.1 (2026-10-05)

- Windows build fixed.
"""


def test_current_release_notes(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    assert home_view.current_release_notes(str(changelog), "0.19.1") == "- Windows build fixed."
    notes = home_view.current_release_notes(str(changelog), "0.20.0+3.g8a0f9f3")  # source checkout after release
    assert notes.startswith("New things.") and "### Overlays" in notes and "0.19.1" not in notes
    assert home_view.current_release_notes(str(changelog), "0.21.0").startswith("New things.")  # newest if none
    assert home_view.current_release_notes(str(tmp_path / "missing.md")) == ""
    assert home_view.base_version("0.19.1+3.g8a0f9f3") == "0.19.1" and home_view.base_version("0.20.0-dev") == "0.20.0"


class FakeLogos:
    def track(self, name, other=""):
        return f"track:{name}"

    def brand(self, vehicle, brand=""):
        return f"brand:{brand or vehicle}"


def test_last_session_card():
    race = SessionRecord(time=1759660000, track="Spa", vehicle="Hyper - Ferrari", vehicle_class="Hyper", session=4,
                         best=123.456, position=3, finish=1)
    card = home_backend.last_session_card(race, FakeLogos())
    assert card["track"] == "Spa" and card["session"] == "Race" and card["best"] == "2:03.456"
    assert card["result"] == "P3" and card["date"] and card["trackLogo"] == "track:Spa"
    assert card["brandLogo"] == "brand:Ferrari"  # brand of "Class - Brand"
    card = home_backend.last_session_card(race._replace(finish=2, best=0.0, vehicle="Hyper"), FakeLogos())
    assert card["result"] == "DNF" and card["best"] == "" and card["brandLogo"] == ""  # class: no brand logo
    assert home_backend.last_session_card(race._replace(vehicle="Oreca 07"), FakeLogos())["brandLogo"] == "brand:Oreca 07"


# --- Checks
def state(**changes) -> CheckState:
    values = {"game": "Le Mans Ultimate", "running": True, "game_window": False, "override": False,
              "spectate": False, "overlays": 5, "recorder": True, "update": ""}
    return CheckState(**{**values, **changes})


def keys(rows: list[dict]) -> list[str]:
    return [row["key"] for row in rows]


def test_checks_ready_while_driving():
    assert keys(home_checks(state())) == ["ready"]
    assert home_checks(state())[0]["level"] == "success"
    rows = home_checks(state(spectate=True, update="1.2.3"))
    assert keys(rows) == ["ready", "spectate", "update"] and rows[2]["text"] == "v1.2.3"  # infos keep ready


def test_checks_game_setup_of_selected_game():
    rows = home_checks(state(running=False))
    assert keys(rows) == ["game"] and "Enable plugins" in rows[0]["text"] and rows[0]["action"] == "api"
    assert "shared memory plugin" in home_checks(state(running=False, game="rFactor 2"))[0]["text"]
    rows = home_checks(state(running=False, game_window=True))  # game open, no data: plugins off
    assert keys(rows) == ["plugin"] and rows[0]["level"] == "error"


def test_checks_most_important_first():
    rows = home_checks(state(override=True, overlays=0, recorder=False))
    assert keys(rows) == ["override", "overlays", "recorder"]  # warnings, then infos; no "ready" with warnings
    assert [row["action"] for row in rows] == ["api", "overlays", "modules"]
    assert keys(home_checks(state(running=False, override=True))) == ["override"]  # forced on: no setup reminder


# --- Page
@pytest.fixture
def home(ui_env, monkeypatch):
    from neopedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    window = app_module.AppWindow()
    window.resize(1300, 900)
    window.show()
    window.centralWidget().set_current_index(0)
    QCoreApplication.processEvents()
    page = window.findChild(home_view.HomeView)
    yield page
    window.hide()
    tray = window.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    window.deleteLater()
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # gone before the next test (window focus)


def wait_until(condition, timeout: float = 10.0):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "not done in time"
        QCoreApplication.processEvents()
        time.sleep(0.005)


def item_texts(view) -> set[str]:
    """Texts of visible QML items of a page"""
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        if not item.property("visible"):
            continue
        text = item.property("text")
        if isinstance(text, str) and text:
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def test_qml_page_shows_cards(home):
    view = home.view
    assert view is not None and view.rootObject() is not None and not view.errors()
    texts = item_texts(view)
    assert {"Game", "Overlay", "Preset", "Overlays", "Module", "Quick Access", "Checks"} <= texts
    assert "Last Session" not in texts and "Session Debrief" not in texts  # nothing driven yet
    assert home.backend.page_visible and home.backend._timer.isActive()


def test_page_reads_nothing_while_hidden(home):
    window = home.window()
    window.centralWidget().set_current_index(1)  # another page
    QCoreApplication.processEvents()
    assert not home.backend.page_visible and not home.backend._timer.isActive()
    window.centralWidget().set_current_index(0)
    QCoreApplication.processEvents()
    assert home.backend._timer.isActive()


def test_release_notes_of_running_version(home, monkeypatch):
    from neopedal.ui.release_notes import ReleaseNotesDialog
    from neopedal.update import ChangelogEntry

    monkeypatch.setattr(home_view, "local_changelog", lambda language="en", filename="": [
        ChangelogEntry(home_view.base_version(), (2026, 10, 19), "### Overlays\n\n- **Delta graph** added.")])
    home.backend.showReleaseNotes()
    QCoreApplication.processEvents()
    dialog = home.window().findChild(ReleaseNotesDialog)
    assert dialog is not None and dialog.isVisible()
    assert [row["title"] for row in dialog.backend.model.rows] == ["Overlays", ""]
    assert not dialog.backend.installVisible  # running version: nothing to install
    assert "19 October 2026" in dialog.backend.detail  # release date of the changelog section
    dialog.close()


def test_game_card_session_and_checks(home, monkeypatch):
    from neopedal.api_control import api

    backend = home.backend
    read = api.read
    monkeypatch.setattr(read.state, "version", lambda: "not running")
    backend.refresh_live()
    assert backend.game["running"] is False and backend.game["status"] == "Not running"
    assert "game" in keys(backend.checks)  # game setup reminder while game not running
    monkeypatch.setattr(read.state, "version", lambda: "1.4200")
    monkeypatch.setattr(read.state, "active", lambda: True)
    monkeypatch.setattr(read.session, "track_name", lambda: "Road Atlanta")
    monkeypatch.setattr(read.session, "session_type", lambda: 4)
    monkeypatch.setattr(read.vehicle, "place", lambda index=None: 3)
    monkeypatch.setattr(read.vehicle, "total_vehicles", lambda: 24)
    monkeypatch.setattr(read.lap, "number", lambda index=None: 12)
    backend.refresh_live()
    game = backend.game
    assert (game["track"], game["session"], game["place"], game["lap"]) == ("Road Atlanta", "Race", "P3/24", "Lap 12")
    assert "game" not in keys(backend.checks)
    QCoreApplication.processEvents()
    assert "Road Atlanta · Race · P3/24 · Lap 12" in item_texts(home.view)


def test_checks_card_actions(home, monkeypatch):
    opened = []
    monkeypatch.setattr(home.backend, "_select_page", opened.append)
    monkeypatch.setattr(home.backend, "openGameSettings", lambda: opened.append("api"))
    for action in ("overlays", "modules", "spectate", "api"):
        home.backend.runCheck(action)
    assert opened == ["widget", "module", "spectate", "api"]


def test_game_window_found_without_data(home, monkeypatch):
    """Le Mans Ultimate open while no data comes: plugins off (window looked for on a worker thread)"""
    from neopedal.api_control import api

    monkeypatch.setattr(type(api), "name", property(lambda self: "Le Mans Ultimate"))
    monkeypatch.setattr(home_backend, "find_game_window", lambda: True)
    monkeypatch.setattr(api.read.state, "version", lambda: "not running")
    backend = home.backend
    backend.refresh_live()
    backend.check_game_window()
    wait_until(lambda: "plugin" in keys(backend.checks))
    assert keys(backend.checks)[0] == "plugin"
    backend.game_window_found(False)
    assert "plugin" not in keys(backend.checks)


def test_overlay_card_lock(home, monkeypatch):
    calls = []
    monkeypatch.setattr(type(home_backend.octrl.toggle), "lock", lambda self: (
        calls.append(1), cfg.overlay.__setitem__("fixed_position", not cfg.overlay["fixed_position"])))
    cfg.overlay["fixed_position"] = True
    home.backend.refresh_live()
    assert home.backend.overlay["locked"] is True
    QCoreApplication.processEvents()
    assert "Unlock Overlay" in item_texts(home.view)
    home.backend.toggleLock()
    QCoreApplication.processEvents()
    assert calls and home.backend.overlay["locked"] is False
    assert {"Lock Overlay", "Drag overlays to move them"} <= item_texts(home.view)


def test_counts_follow_overlays_turned_on(home, monkeypatch):
    monkeypatch.setattr(type(home_backend.wctrl), "number_active", property(lambda self: 0))
    home.backend.refresh_live()
    assert home.backend.counts["overlays"] == 0 and "overlays" in keys(home.backend.checks)


def test_update_header(home, monkeypatch):
    checker = type(update.update_checker)  # home: proxy, update module imported (checked)
    checks = []
    monkeypatch.setattr(checker, "is_checking", lambda self: False)
    monkeypatch.setattr(checker, "is_updates", lambda self: False)
    monkeypatch.setattr(checker, "message", lambda self: "Up to date")
    monkeypatch.setattr(checker, "check", lambda self, manual: checks.append(manual))
    backend = home.backend
    backend.refresh_header()
    assert backend.header["update"] == "" and backend.header["tip"] == "Up to date"
    backend.updateAction()
    assert checks == [True]
    monkeypatch.setattr(checker, "is_updates", lambda self: True)
    monkeypatch.setattr(checker, "latest_version", lambda self: (0, 20, 0))
    backend.updates_changed()
    assert backend.header["update"] == "available" and backend.header["latest"] == "0.20.0"
    assert backend.header["tip"] == ""  # no tooltip of an older check left on the button
    assert "update" in keys(backend.checks)
    QCoreApplication.processEvents()
    assert {"See Update", "Update Available · v0.20.0"} <= item_texts(home.view)
    shown = []
    from neopedal.ui.notification import UpdatesNotifyButton

    monkeypatch.setattr(UpdatesNotifyButton, "show_release_notes", lambda self, *args, **kwargs: shown.append(1))
    backend.updateAction()
    assert shown == [1] and checks == [True]  # update notes shown, no new check


def test_preset_card_switch(home, monkeypatch, tmp_path):
    folder = cfg.path.settings
    for name in ("alpha", "beta"):
        with open(f"{folder}{name}.json", "w", encoding="utf-8") as file:
            file.write("{}")
    rows = home.backend.presetList()
    names = {row["name"] for row in rows}
    assert {"alpha", "beta", "default"} <= names
    assert [row for row in rows if row["loaded"]] == [row for row in rows if row["file"] == cfg.filename.setting]
    loads = []
    monkeypatch.setattr(type(cfg), "set_next_to_load", lambda self, filename: loads.append(filename))
    reloads = []
    app_signal.reload.connect(reloads.append)
    home.backend.loadPreset("alpha.json")
    home.backend.loadPreset("missing.json")  # gone meanwhile: nothing
    home.backend.loadPreset(cfg.filename.setting)  # loaded already: nothing
    assert loads == ["alpha.json"] and reloads == [True]


def test_last_session_and_debrief_hidden_without_history(home, monkeypatch):
    monkeypatch.setattr(home_view, "last_session", lambda: None)
    home.backend._record_read = False
    home.backend.refresh_last_session()
    assert home.backend.lastSession == {} and home.backend.debrief == {}
    record = SessionRecord(time=1759660000, track="Spa", vehicle="Oreca 07", session=2, best=123.456)
    monkeypatch.setattr(home_view, "last_session", lambda: record)
    home.backend.refresh_last_session()
    assert home.backend.lastSession["track"] == "Spa"
    QCoreApplication.processEvents()
    assert "Last Session" in item_texts(home.view)


def test_last_session_opens_its_driver_stats(home, monkeypatch):
    shown = []

    class Viewer:
        class backend:
            @staticmethod
            def show_combo(track, vehicle):
                shown.append((track, vehicle))

    opened = []
    monkeypatch.setattr(home.backend, "open_tool", lambda path: opened.append(path) or Viewer())
    home.backend._record = SessionRecord(time=1.0, track="Spa", vehicle="Hyper - Ferrari")
    home.backend.openLastSession()
    assert opened == ["driver_stats_viewer.DriverStatsViewer"] and shown == [("Spa", "Hyper - Ferrari")]


def test_debrief_corner_opens_telemetry_on_it(home, monkeypatch):
    from neopedal.ui import home_debrief
    from neopedal.ui.quick import lap_focus

    calls = []

    class Viewer:
        backend = object()

    monkeypatch.setattr(home.backend, "open_tool", lambda path: Viewer())
    monkeypatch.setattr(lap_focus, "show_laps", lambda backend, *args: calls.append(args) or True)
    monkeypatch.setattr(home_debrief, "debrief_laps", lambda data: ("ref.lap", "cmp.lap"))
    home.backend._debrief_data = object()
    home.backend._values["debrief"] = {"tips": [{"index": 0, "apex": 812.5}]}
    home.backend.openCorner(0)
    home.backend.openCorner(3)  # gone meanwhile: nothing
    home.backend.openDebrief()
    assert calls == [("ref.lap", "cmp.lap", 812.5), ("ref.lap", "cmp.lap", -1.0)]


# --- Quick access: chosen by user
def test_quick_access_setting():
    entries = home_view.quick_access_entries()
    assert entries["lap_viewer"].kind == "tool" and entries["lap_viewer"].target == "lap_viewer.LapViewer"
    assert entries["preset"].kind == "page" and "home" not in entries
    assert entries["command_palette"].kind == "action"
    assert home_view.parse_quick_items("preset, bogus,preset,fuel_calculator,bug_report") == [
        "preset", "race_calculator", "bug_report"]  # unknown & duplicate dropped, merged tool renamed
    assert home_view.default_quick_items() == [
        "lap_viewer", "race_calculator", "driver_stats_viewer", "layout_editor", "perf_view",
        "race_results_viewer", "widget", "module", "preset", "spectate",
        "hotkey", "tools", "app_settings", "bug_report", "check_updates",
    ]


def test_current_quick_items(ui_env):
    cfg.application["home_quick_access"] = ""
    assert home_view.current_quick_items() == []  # every button removed by user
    cfg.application["home_quick_access"] = "tools,check_updates"
    assert home_view.current_quick_items() == ["tools", "check_updates"]
    del cfg.application["home_quick_access"]
    assert home_view.current_quick_items() == home_view.default_quick_items()


def test_quick_access_editor_updates_buttons(home):
    backend = home.backend
    assert [row["key"] for row in backend.quick] == home_view.default_quick_items()
    assert backend.quick[0]["label"] and [row["shortcut"] for row in backend.quick if row["shortcut"]] == []
    editor = home_view.QuickAccessEditor(None, backend.refresh_quick)
    assert editor.checked_items() == home_view.default_quick_items()
    assert editor.picker.entries["bug_report"].kind == "Actions" and editor.picker.badge_text(0) == "1"
    editor.fill(["preset", "command_palette"])
    editor.saving()
    QCoreApplication.processEvents()
    assert cfg.application["home_quick_access"] == "preset,command_palette"
    assert [row["key"] for row in backend.quick] == ["preset", "command_palette"]
    assert backend.quick[1]["shortcut"] == "Ctrl+K"
    editor.picker.remove("preset")
    editor.picker.remove("command_palette")
    editor.saving()
    QCoreApplication.processEvents()
    assert cfg.application["home_quick_access"] == "" and backend.quick == []
    assert "No quick access button: use Customize... to add tools, pages or actions." in item_texts(home.view)
    editor.close()


def test_quick_entries_run(home, monkeypatch):
    calls = []
    backend = home.backend
    monkeypatch.setattr(backend, "_select_page", lambda key: calls.append(("page", key)))
    monkeypatch.setattr(backend, "open_tool", lambda path: calls.append(("tool", path)))
    monkeypatch.setattr(backend._window, "open_command_palette", lambda: calls.append(("palette",)))
    monkeypatch.setattr(type(update.update_checker), "check", lambda self, manual: calls.append(("check", manual)))
    for key in ("preset", "race_calculator", "command_palette", "check_updates", "bogus"):
        backend.runQuick(key)
    assert calls == [("page", "preset"), ("tool", "race_calculator.RaceCalculator"), ("palette",), ("check", True)]


def test_driver_card(home, monkeypatch):
    """Hidden while nothing is known, shown with ranks once read, opens driver stats"""
    from neopedal import rank_info
    from neopedal.process import driver_ranks as dr
    from neopedal.process import results_index as ri
    from neopedal.ui.home_driver import DriverData

    backend = home.backend
    backend.jobs.cancel("driver")  # profile & results of the page start: never handed over after the test's
    monkeypatch.setattr(backend, "read_driver_data", lambda: None)
    monkeypatch.setattr(rank_info.ranks, "poll", lambda: None)
    monkeypatch.setattr(rank_info.ranks, "player", None)
    monkeypatch.setattr(rank_info.ranks, "others", [])
    backend._driver_key = None
    backend.refresh_driver()
    assert backend.driver == {}
    monkeypatch.setattr(rank_info.ranks, "player", dr.DriverRanks(
        "Keenny Hess", "", "", "", dr.Rank("Gold", 1, 20), None, ""))
    monkeypatch.setattr(rank_info.ranks, "serial", rank_info.ranks.serial + 1)
    backend.refresh_driver()
    assert backend.driver["name"] == "Keenny Hess"
    assert [(row["label"], row["value"]) for row in backend.driver["ranks"]] == [("Driver Rank", "Gold 1")]
    backend.driver_data_read(DriverData(None, ri.RaceRecord(2, 1, 1, 1.5, 2, 0), "Keenny Hess"))
    assert {"label": "Clean Races", "value": "2/2"} in backend.driver["figures"]
    QCoreApplication.processEvents()
    assert {"Driver", "Keenny Hess", "Gold 1", "2/2"} <= item_texts(home.view)
    opened = []
    monkeypatch.setattr(backend, "open_tool", opened.append)
    backend.openDriverStats()
    assert opened == ["driver_stats_viewer.DriverStatsViewer"]
