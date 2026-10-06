"""Home page: release notes of running version, cards, layout, last session"""

from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QSystemTrayIcon

from tinypedal import app_signal
from tinypedal.setting import cfg
from tinypedal.ui import home_view
from tinypedal.userfile.driver_history import SessionRecord

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


def test_session_record_text():
    race = SessionRecord(time=1759660000, track="Spa", vehicle="Oreca 07", session=4, best=123.456,
                         position=3, finish=1)
    value, detail = home_view.session_record_text(race)
    assert value == "<b>Spa</b>"
    assert "Oreca 07" in detail and "Race" in detail and "Best 2:03.456" in detail and "P3" in detail
    _, detail = home_view.session_record_text(race._replace(finish=2, best=0.0))
    assert "DNF" in detail and "Best" not in detail and "P3" not in detail
    _, detail = home_view.session_record_text(SessionRecord(time=0, track="<b>", vehicle="A & B", session=1))
    assert "A &amp; B" in detail and "Practice" in detail  # escaped rich text


@pytest.fixture
def home(ui_env, monkeypatch):
    from tinypedal.ui import app as app_module

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


def test_release_notes_page_of_running_version(home, monkeypatch):
    from tinypedal.ui.release_notes import ReleaseNotesDialog

    monkeypatch.setattr(home_view, "current_release_notes", lambda **kwargs: "### Overlays\n\n- **Delta graph** added.")
    home.button_notes.click()
    QCoreApplication.processEvents()
    dialog = home.window().findChild(ReleaseNotesDialog)
    assert dialog is not None and dialog.isVisible()
    assert [section.title for section in dialog.themes] == ["Overlays"]
    assert dialog.button_install.isHidden()  # running version: nothing to install
    dialog.close()


def test_game_card_session_and_setup_reminder(home, monkeypatch):
    from tinypedal.api_control import api

    read = api.read
    monkeypatch.setattr(read.state, "version", lambda: "not running")
    home.refresh_live()
    assert not home.card_start.isHidden()  # game setup reminder while game not running
    assert home.card_game.label_detail.text() == "Not running"
    monkeypatch.setattr(read.state, "version", lambda: "1.4200")
    monkeypatch.setattr(read.state, "active", lambda: True)
    monkeypatch.setattr(read.session, "track_name", lambda: "Road Atlanta")
    monkeypatch.setattr(read.session, "session_type", lambda: 4)
    monkeypatch.setattr(read.vehicle, "place", lambda index=None: 3)
    monkeypatch.setattr(read.vehicle, "total_vehicles", lambda: 24)
    monkeypatch.setattr(read.lap, "number", lambda index=None: 12)
    home.refresh_live()
    assert home.card_start.isHidden()
    assert home.card_game.label_detail.text() == "Road Atlanta · Race · P3/24 · Lap 12"


def test_overlay_card_lock_button(home, monkeypatch):
    from tinypedal.ui import home_view as module

    calls = []
    monkeypatch.setattr(type(module.octrl.toggle), "lock", lambda self: (
        calls.append(1), cfg.overlay.__setitem__("fixed_position", not cfg.overlay["fixed_position"])))
    cfg.overlay["fixed_position"] = True
    home.refresh_live()
    assert home.card_overlay.label_value.text() == "<b>Locked</b>" and home.button_lock.text() == "Unlock Overlay"
    home.button_lock.click()
    assert calls and home.button_lock.text() == "Lock Overlay"
    assert "Drag overlays to move them" in home.card_overlay.label_detail.text()


def test_cards_open_pages_and_layout_columns(home, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent

    opened = []
    home.card_preset.on_click = lambda: opened.append("preset")
    point = QPointF(5, 5)
    QCoreApplication.sendEvent(home.card_preset, QMouseEvent(
        QEvent.Type.MouseButtonRelease, point, point, Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    QCoreApplication.sendEvent(home.card_preset, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                                           Qt.KeyboardModifier.NoModifier))
    assert opened == ["preset", "preset"]  # mouse & keyboard
    assert home.card_preset.focusPolicy() == Qt.FocusPolicy.StrongFocus and home.card_game.on_click is None

    column = home_view.UIScaler.size(home_view.COLUMN_WIDTH)
    assert home.column_count(column - 1) == 1 and home.column_count(column * 2) == 2
    assert home.column_count(column * 10) == 3
    for columns in (1, 2, 3):
        home.arrange(columns)
        position = home.grid.getItemPosition(home.grid.indexOf(home.card_widget))
        assert position[:2] == divmod(3, columns)  # 4th card
        if not home.card_start.isHidden():  # reminder spans every column
            assert home.grid.getItemPosition(home.grid.indexOf(home.card_start))[3] == columns
        quick = home.quick_grid.getItemPosition(home.quick_grid.indexOf(home.quick_buttons[-1]))
        assert quick[1] < home_view.QUICK_COLUMNS[columns]


def test_last_session_card(home, monkeypatch):
    monkeypatch.setattr(home_view, "last_session", lambda: None)
    home.refresh_last_session()
    assert home.card_last.isHidden()
    monkeypatch.setattr(home_view, "last_session", lambda: SessionRecord(
        time=1759660000, track="Spa", vehicle="Oreca 07", session=2, best=123.456))
    home.refresh_last_session()
    assert not home.card_last.isHidden() and home.card_last.label_value.text() == "<b>Spa</b>"
    assert home.grid.indexOf(home.card_last) >= 0


def test_update_button(home, monkeypatch):
    checker = type(home_view.update_checker)
    checks = []
    monkeypatch.setattr(checker, "is_checking", lambda self: False)
    monkeypatch.setattr(checker, "is_updates", lambda self: False)
    monkeypatch.setattr(checker, "check", lambda self, manual: checks.append(manual))
    home.refresh_version()
    assert home.chip_update.isHidden() and home.button_update.text() == "Check for Updates"
    home.button_update.click()
    assert checks == [True]
    monkeypatch.setattr(checker, "is_updates", lambda self: True)
    monkeypatch.setattr(checker, "latest_version", lambda self: (0, 20, 0))
    home.refresh_version()
    assert not home.chip_update.isHidden() and "v0.20.0" in home.chip_update.text()
    assert home.button_update.text() == "See Update" and home.button_update.objectName() == "homePrimary"
    shown = []
    from tinypedal.ui.notification import UpdatesNotifyButton

    monkeypatch.setattr(UpdatesNotifyButton, "show_release_notes", lambda self, *args, **kwargs: shown.append(1))
    home.button_update.click()
    assert shown == [1] and checks == [True]  # update notes shown, no new check


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
        "game_replays", "widget", "module", "preset", "spectate",
        "hotkey", "tools", "app_settings", "bug_report", "check_updates",
    ]


def test_current_quick_items(ui_env):
    cfg.application["home_quick_access"] = ""
    assert home_view.current_quick_items() == []  # every button removed by user
    cfg.application["home_quick_access"] = "tools,check_updates"
    assert home_view.current_quick_items() == ["tools", "check_updates"]
    del cfg.application["home_quick_access"]
    assert home_view.current_quick_items() == home_view.default_quick_items()


def test_quick_access_editor_rebuilds_buttons(home):
    assert [button.objectName() for button in home.quick_buttons] == [
        f"quick_{key}" for key in home_view.default_quick_items()]
    editor = home_view.QuickAccessEditor(None, home.build_quick_buttons)
    assert editor.checked_items() == home_view.default_quick_items()
    assert editor.picker.entries["bug_report"].kind == "Actions" and editor.picker.badge_text(0) == "1"
    editor.fill(["preset"])
    editor.picker.add("bug_report")
    editor.picker.add("bug_report")  # already shown: no duplicate
    editor.saving()
    QCoreApplication.processEvents()
    assert cfg.application["home_quick_access"] == "preset,bug_report"
    assert [button.objectName() for button in home.quick_buttons] == ["quick_preset", "quick_bug_report"]
    assert home.label_quick_empty.isHidden()
    editor.picker.remove("preset")
    editor.picker.remove("bug_report")
    editor.saving()
    QCoreApplication.processEvents()
    assert cfg.application["home_quick_access"] == "" and home.quick_buttons == []
    assert not home.label_quick_empty.isHidden()  # hint to add buttons
    editor.close()


def test_quick_entries_run(home, monkeypatch):
    calls = []
    monkeypatch.setattr(home, "_select_page", lambda key: calls.append(("page", key)))
    monkeypatch.setattr(home, "open_tool", lambda path: calls.append(("tool", path)))
    monkeypatch.setattr(home._window, "open_command_palette", lambda: calls.append(("palette",)))
    monkeypatch.setattr(type(home_view.update_checker), "check", lambda self, manual: calls.append(("check", manual)))
    entries = home_view.quick_access_entries()
    for key in ("preset", "race_calculator", "command_palette", "check_updates"):
        home.run_quick_entry(entries[key])
    assert calls == [("page", "preset"), ("tool", "race_calculator.RaceCalculator"), ("palette",), ("check", True)]
