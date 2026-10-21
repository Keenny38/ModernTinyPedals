"""Bridge granularity of pages: option rows, overlay cards, option finder, replay clocks, live race header, messages
with a time (few model reads, reused rows not animated from the previous row, cached translations)"""

import re
from contextlib import suppress

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QSystemTrayIcon

from neopedal import app_signal
from neopedal.setting import cfg
from tests.test_perf_page_state import qml_warnings  # noqa: F401


def flush():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def qml_text(name: str) -> str:
    from neopedal.ui.quick import qml_path

    with open(qml_path(name), encoding="utf-8") as file:
        return file.read()


@pytest.fixture
def window(ui_env, monkeypatch):
    from neopedal.ui import app as app_module

    monkeypatch.setattr(app_module.AppWindow, "set_window_state", lambda self: None)
    cfg.application["show_setup_wizard_at_startup"] = False
    main = app_module.AppWindow()
    yield main
    for page in main.centralWidget().dialog_pages():
        if page.dialog is not None:
            backend = getattr(page.dialog, "backend", None)
            if backend is not None and hasattr(backend, "discard"):
                backend.discard()  # closed without question
            page.dialog.close()
    tray = main.findChild(QSystemTrayIcon)
    if tray:
        tray.hide()
    for signal in (app_signal.hotkey, app_signal.refresh, app_signal.quitapp, app_signal.reload, app_signal.updates):
        with suppress(RuntimeError, TypeError):
            signal.disconnect()
    main.deleteLater()
    flush()


def settle(seconds: float = 0.3):
    from PySide6.QtTest import QTest

    QTest.qWait(int(seconds * 1000))
    flush()


def test_overlay_switch_reads_few_values_per_row(window, qml_warnings):  # noqa: F811
    """Rows of another overlay: hot roles fed once as required properties, not read by every binding"""
    from neopedal.ui.overlay_options import open_overlay_options
    from neopedal.ui.quick.models import DictListModel

    page = open_overlay_options(window, "speedometer")
    assert page is not None and not page.view.errors()
    page.resize(1200, 900)
    page.show()
    settle()
    backend = page.backend
    calls = []
    model = backend.rows
    original = DictListModel.data

    def counting(index, role=0):
        calls.append(role)
        return original(model, index, role)

    model.data = counting  # instance attribute: called by Qt instead of the class method
    try:
        for name in ("fuel", "relative", "speedometer"):
            backend.selectOverlay(name)
            settle(0.15)
    finally:
        del model.data
    shown = sum(1 for item in walk(page.view.rootObject()) if item.metaObject().className().startswith(
        "OverlayOptionRow"))
    assert shown > 0
    per_row = len(calls) / shown / 3
    assert per_row < 24, per_row  # was 28.7 with a model read per binding
    assert not [text for text in qml_warnings if "OverlayOptionRow" in text], qml_warnings
    rows = backend.rows.rows
    checked = 0
    for item in walk(page.view.rootObject()):
        if not item.metaObject().className().startswith("OverlayOptionRow") or not item.property("settled"):
            continue  # pooled: not shown
        values = rows[item.property("index")]
        for name in ("kind", "label", "help", "text", "error", "locked", "dimmed", "modified", "first"):
            assert item.property(name) == values[name], (name, item.property(name), values[name])
        checked += 1
    assert checked > 3  # reused rows show the values of their new option


def walk(root):
    stack = [root]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.childItems())


def behaviors(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if re.match(r"\s*Behavior on ", line)]


def test_reused_rows_do_not_animate_from_previous_row():
    """Animated values of a row reused for another option, card or result: set at once (no fade or turn)"""
    option_row = behaviors(qml_text("OverlayOptionRow.qml"))
    assert len(option_row) >= 4 and all("row.settled" in line for line in option_row), option_row
    result_row = qml_text("OptionResultRow.qml")
    assert all("!row.recycling" in line for line in behaviors(result_row))
    assert "ListView.onPooled" in result_row and "opacity = 1" in result_row
    for name in ("OverlayCard.qml", "OverlayListRow.qml"):
        pooled = qml_text(name).split("GridView.onPooled: {", 1)[1].split("}", 1)[0]
        assert "opacity = 1" in pooled and "scale = 1" in pooled, name
    finder = qml_text("OptionFinder.qml")
    assert "reuseItems: true" in finder and "displaced: count > 30 ? null" in finder


def test_option_finder_rows_reused_while_typing(ui_env, qml_warnings):  # noqa: F811
    from neopedal.ui.option_finder import OptionFinder

    page = OptionFinder(None)
    try:
        assert not page.view.errors(), [error.toString() for error in page.view.errors()]
        page.resize(900, 700)
        page.show()
        for text in ("color", "font", "snap gap", "opacity"):
            page.set_search(text)
            settle(0.05)
        settle(0.4)  # add transitions done
        rows = page.backend.model.rows
        shown = [item for item in walk(page.view.rootObject())
                 if item.metaObject().className().startswith("OptionResultRow") and not item.property("recycling")]
        assert shown and len(rows) > 30
        for item in shown:
            assert item.property("key") == rows[item.property("index")]["key"]
            assert item.opacity() == 1
    finally:
        page.close()
        flush()
    assert not [text for text in qml_warnings if ".qml" in text], qml_warnings


def test_option_index_built_once_per_settings_version(ui_env, monkeypatch):
    """Find Option opened again: option index (every option, folded text) reused until settings change"""
    from neopedal.ui import option_finder
    from neopedal.ui.quick import finder_backend

    built = []
    original = option_finder.build_index
    monkeypatch.setattr(option_finder, "build_index", lambda: built.append(1) or original())
    monkeypatch.setattr(option_finder, "_cached_index", None)
    first = finder_backend.FinderBackend(None, lambda entry: None)
    second = finder_backend.FinderBackend(None, lambda entry: None)
    assert len(built) == 1 and second.entries is first.entries
    cfg.version_update += 1  # settings saved
    third = finder_backend.FinderBackend(None, lambda entry: None)
    assert len(built) == 2 and third.optionCount == first.optionCount
    for backend in (first, second, third):
        backend.deleteLater()
    flush()


def test_replay_clock_timers_read_cached_values():
    """Replay clocks & playhead tick 4-10 times a second: values of last game answer kept in QML, not read from
    Python at each tick"""
    for name in ("ReplayView.qml", "IncidentPanel.qml"):
        text = qml_text(name)
        for block in text.split("Timer {")[1:]:
            body = block.split("}", 1)[0]
            if "onTriggered" in body:
                for role in ("replayTime", "replayRate", "timeReceived", "liveTime"):
                    assert f"replays.{role}" not in body, (name, role)
        assert "readonly property real timeReceived: replays.timeReceived" in text, name


def test_updated_time_message_translated_from_cache(ui_env):
    """Message with the time of day: fixed part translated (cached), time added after"""
    import time
    import types

    from PySide6.QtWidgets import QWidget

    from neopedal import i18n
    from neopedal.ui.quick import formatting
    from neopedal.ui.quick.race_backend import RaceBackend
    from neopedal.ui.quick.replays_backend import GameReplaysBackend

    parent = QWidget()
    replays = GameReplaysBackend(parent)  # type: ignore[arg-type]
    team = types.SimpleNamespace(  # race calculator team tab: only what received_team uses
        team_request=types.SimpleNamespace(busy=True), team_status="", unit_fuel=lambda value: value,
        show_team_stints=lambda stints, capacity: None, team_status_changed=lambda: None)

    def team_status() -> str:
        RaceBackend.received_team(team, ([], 0.0))  # type: ignore[arg-type]
        return team.team_status

    def replays_status() -> str:
        replays.mark_updated()
        return replays.updated

    i18n.set_language("Français")
    try:
        for status in (team_status, replays_status):
            texts = []
            before = i18n._translate_message.cache_info()
            for stamp in (43201.0, 43202.0):  # two times of day, same message
                clock = types.SimpleNamespace(strftime=time.strftime, localtime=lambda _=None, at=stamp: time.gmtime(at))
                with pytest.MonkeyPatch.context() as patch:
                    patch.setattr(formatting, "time", clock)
                    texts.append(status())
            after = i18n._translate_message.cache_info()
            assert texts == ["Mis à jour depuis le jeu à 12:00:01", "Mis à jour depuis le jeu à 12:00:02"], status
            assert after.currsize - before.currsize <= 1, status  # one entry for every time of day
            assert after.hits > before.hits, status  # second time of day: template read from cache
    finally:
        i18n.set_language("English")
        parent.deleteLater()
        flush()
