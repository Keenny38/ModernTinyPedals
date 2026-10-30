"""UI/UX audit 2026-10-29, results & replays (T4, T5, T9, empty states, menus, comments): podium gold & track limits
in warning, replay tab only for a session with its own replay (player of that replay only, the replays list keeps
the player), track stats & lap telemetry links, comments on the player's session from the results file"""

import os
import re
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, qInstallMessageHandler

from neopedal.process import results_file as rf
from neopedal.process.results_file import Entry, Lap, SessionResult
from neopedal.ui.quick import results_comments as rc
from neopedal.ui.quick.results_telemetry import lap_folders, recorded_laps
from tests.test_race_results import RACE_NAME, RACE_XML, english, wait_until  # noqa: F401  (fixture)
from tests.test_results_replays_lap_fixes import everything, named, settle
from tests.test_results_replays_page import REPLAY, page  # noqa: F401  (fixture)

ANALYSIS = os.path.join("neopedal", "ui", "qml", "analysis")
START = 1_790_000_600.0


def lap(number: int, time_: float, position: int = 1, start: float = -1.0, pit: bool = False) -> Lap:
    return Lap(number, position, time_, start, (0.0, 0.0, 0.0), 0.0, "Medium", pit, -1.0, 0.0, -1.0, 0.0, ())


def entry(name: str, laps: list[Lap], car_class: str = "GT3", grid: int = 1, class_grid: int = 0,
          player: bool = False, best: float = 0.0) -> Entry:
    best = best or min((item.time for item in laps if item.time > 0), default=0.0)
    return Entry(name, "", name, "Car", car_class, "1", grid, laps[-1].position if laps else 0, class_grid or grid, 0,
                 len(laps), best, 0.0, sum(item.pit for item in laps), "Finished Normally", "", True, player, "",
                 tuple(laps), ())


def session(entries: list[Entry], kind: str = "Race") -> SessionResult:
    return SessionResult("x.xml", "LMU", "", "", START, kind, kind, "Spa", "Spa-Francorchamps", "", 7000.0, "1.42",
                         60, 0, 20, tuple(entries), ())


def steady(base: float, count: int, step: float = 0.0, first_place: int = 1) -> list[Lap]:
    """Race laps from lap 1: standing start lap 3 s slower, then base + step per lap"""
    laps = [lap(1, base + 3.0, first_place, 0.0)]
    clock = base + 3.0
    for number in range(2, count + 1):
        time_ = base + step * (number - 2)
        laps.append(lap(number, time_, first_place, clock))
        clock += time_
    return laps


# --- Comments on the player's session (pure functions)
def test_pace_comment_against_class_median(english):  # noqa: F811
    player = entry("Me", steady(100.0, 8), player=True, grid=3)
    others = [entry(f"Car {n}", steady(100.0 + n * 0.5, 8), grid=n) for n in (1, 2, 4)]
    slow_other_class = entry("Proto", steady(90.0, 8), car_class="LMP2")
    comment = rc.pace_comment(session([player, *others, slow_other_class]), player)
    assert comment is not None
    assert comment["title"] == "Race pace" and comment["value"] == "1:40.000" and comment["tone"] == "gain"
    # class median of 100.0, 100.5, 101.0, 102.0: 100.75 -> 0.75 s faster, first of 4 in class (LMP2 left out)
    assert comment["detail"].startswith("\u22120.750 s vs class median") and "1 / 4 in class" in comment["detail"]


def test_pace_comment_needs_class_cars_and_clean_laps(english):  # noqa: F811
    player = entry("Me", steady(100.0, 8), player=True)
    assert rc.pace_comment(session([player, entry("Other", steady(101.0, 8))]), player) is None  # 2 cars only
    short = entry("Me", steady(100.0, 3), player=True)  # 2 laps after the start: no race pace
    others = [entry(f"Car {n}", steady(101.0, 8)) for n in range(3)]
    assert rc.pace_comment(session([short, *others]), short) is None
    # Yellow flag lap (slower than 107 %) & pit laps left out of the pace
    laps = steady(100.0, 8)
    laps[4] = laps[4]._replace(time=130.0)
    laps[6] = laps[6]._replace(pit=True, time=125.0)
    assert rc.clean_times(laps, True) == [100.0] * 5
    # Qualifying: best laps compared, on the median
    quali = [entry(f"Car {n}", [lap(1, 100.0 + n * 0.02)], player=n == 1) for n in range(3)]
    comment = rc.pace_comment(session(quali, "Qualifying"), quali[1])
    assert comment is not None and comment["title"] == "Best Lap" and comment["tone"] == ""
    assert comment["detail"].startswith("on the class median")


def test_start_comment_places_on_lap_1(english):  # noqa: F811
    player = entry("Me", steady(100.0, 4, first_place=2), player=True, grid=5)
    comment = rc.start_comment(session([player]), player)
    assert comment == {"glyph": rc.GLYPH_START, "title": "Lap 1", "value": "P5 → P2",
                       "detail": "+3 places gained", "tone": "gain"}
    lost = entry("Me", steady(100.0, 4, first_place=6), player=True, grid=5)
    assert rc.start_comment(session([lost]), lost)["detail"] == "\u22121 place lost"
    same = entry("Me", steady(100.0, 4, first_place=5), player=True, grid=5)
    assert rc.start_comment(session([same]), same)["tone"] == ""
    assert rc.start_comment(session([player], "Practice"), player) is None
    assert rc.start_comment(session([player._replace(grid=0)]), player._replace(grid=0)) is None


def test_start_comment_in_class_when_several_classes(english):  # noqa: F811
    # Overall P1 & P2 at the end of lap 1 are prototypes: player P3 overall is P1 in GT3, started P2 in class
    protos = [entry(f"Proto {n}", steady(90.0, 3, first_place=n), car_class="LMP2", grid=n) for n in (1, 2)]
    rival = entry("Rival", steady(100.0, 3, first_place=4), grid=3, class_grid=1)
    player = entry("Me", steady(100.0, 3, first_place=3), player=True, grid=4, class_grid=2)
    comment = rc.start_comment(session([*protos, player, rival]), player)
    assert comment["value"] == "P2 → P1" and comment["detail"] == "+1 place gained · GT3"


def test_stint_trends(english):  # noqa: F811
    # Stint 1: laps 1-8 (lap 8 through the pit lane), stint 2 from lap 9 (out lap left out)
    laps = steady(100.0, 14, step=0.1)
    laps[7] = laps[7]._replace(pit=True)
    trends = rc.stint_trends(laps)
    assert [(first, last) for first, last, _ in trends] == [(1, 8), (9, 14)]
    assert trends[0][2] == pytest.approx(0.1) and trends[1][2] == pytest.approx(0.1)
    comment = rc.stint_comment(session([entry("Me", laps, player=True)]), entry("Me", laps, player=True))
    assert comment["value"] == "+0.10 s/lap" and comment["detail"] == "Laps 1-8: +0.10 s · 9-14: +0.10 s"
    assert rc.stint_trends(steady(100.0, 4)) == []  # too short
    assert rc.trend([(1.0, 5.0)]) == 0.0


def test_session_comments_of_player_only(english):  # noqa: F811
    player = entry("Me", steady(100.0, 8), player=True, grid=3)
    others = [entry(f"Car {n}", steady(100.5, 8), grid=n) for n in (1, 2, 4)]
    comments = rc.session_comments(session([player, *others]))
    assert [comment["title"] for comment in comments] == ["Race pace", "Lap 1", "Lap time trend"]
    assert rc.session_comments(session(others)) == [] and rc.session_comments(None) == []


def test_session_comments_french(ui_env):
    from neopedal import i18n

    i18n.set_language("Français")
    try:
        player = entry("Me", steady(100.0, 8, step=0.05, first_place=2), player=True, grid=3)
        others = [entry(f"Car {n}", steady(100.5, 8), grid=n) for n in (1, 2, 4)]
        texts = {comment["title"]: comment for comment in rc.session_comments(session([player, *others]))}
        assert set(texts) == {"Rythme de course", "Tour 1", "Évolution du temps au tour"}
        assert texts["Tour 1"]["detail"] == "+1 place gagnée"
        assert "dans la catégorie" in texts["Rythme de course"]["detail"]
        assert "0,05" in texts["Évolution du temps au tour"]["value"]  # French decimal comma
    finally:
        i18n.set_language("English")


# --- Recorded laps of a results lap (lap viewer link)
def lap_file(folder, saved: float, number: int, seconds: float, invalid: bool = False) -> str:
    minutes, rest = divmod(seconds, 60)
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(saved))
    name = f"{stamp} lap{number:03d} {int(minutes)}m{rest:06.3f}s{' invalid' if invalid else ''}.csv"
    path = folder / name
    path.write_text("x", encoding="utf-8")
    return str(path)


def test_recorded_laps_matched_by_time_and_lap_time(tmp_path):
    laps = [lap(1, 103.2, start=0.0), lap(2, 100.4, start=103.2), lap(3, 0.0, start=203.6), lap(4, 101.0, start=310.0)]
    player = entry("Me", laps, player=True)
    result = session([player])
    assert lap_folders(result, player) == ["Spa - GT3", "Spa-Francorchamps - GT3"]
    folder = tmp_path / "Spa-Francorchamps - GT3"  # game track name: venue
    folder.mkdir()
    first = lap_file(folder, START + 103.2 + 2, 1, 103.2)
    second = lap_file(folder, START + 203.6 + 1, 2, 100.41)  # telemetry lap time a few ms apart
    untimed = lap_file(folder, START + 310.0 + 1, 3, 106.4, invalid=True)  # ends as lap 4 starts
    lap_file(folder, START + 411.0 + 1, 4, 99.0)  # other lap time: not lap 4
    lap_file(folder, START - 86400, 2, 100.4)  # other session (a day before)
    (tmp_path / "Spa - GT3").mkdir()
    lap_file(tmp_path / "Spa - GT3", START + 203.6 + 300, 2, 100.4)  # saved too long after the lap end
    assert recorded_laps(str(tmp_path), result, player) == {1: first, 2: second, 3: untimed}
    assert recorded_laps(str(tmp_path / "none"), result, player) == {}
    assert recorded_laps(str(tmp_path), result._replace(time=0.0), player) == {}


# --- Podium gold, purple best, track limits in warning
def test_podium_gold_personal_best_green(english, ui_env):  # noqa: F811
    from neopedal.ui.quick import results_backend as rb

    result = rf.parse_results(RACE_XML.encode("utf-8"), RACE_NAME, ["bob racer"])  # Bob: P2 in Hyper
    bob = result.player_entry
    # Race podium gold, silver, bronze (rule shared with Stats: results_text.place_tone)
    assert rb.player_result_text(result, bob) == ("P2", "silver")
    tiles = {item["label"]: item for item in rb.summary_tiles(result)}
    assert tiles["Position"]["tone"] == "silver"
    assert rb.player_result_text(result, bob._replace(position=3, class_position=3))[1] == "bronze"
    assert rb.player_result_text(result._replace(kind="Practice"), bob)[1] == ""  # no podium out of races
    assert rb.player_result_text(result, bob._replace(position=4, class_position=4)) == ("P4", "")
    rows = rb.lap_rows(result, bob)  # own best green, session best purple
    assert {row["timeTone"] for row in rows} <= {"gain", "purple", "dim", ""} and rows[0]["telemetry"] is False


def qml(name: str) -> str:
    with open(os.path.join(ANALYSIS, name), encoding="utf-8") as file:
        return file.read()


def test_track_limits_in_warning_with_their_letter():
    text = qml("ResultsEvents.qml")
    color = text[text.index("function kindColor"):text.index("function kindLetter")]
    assert "purple" not in color and 'kind === "track_limits" ? theme.warning' in color
    assert 'kind === "track_limits" ? "T"' in text  # shape of the kind kept without color


RESULTS_FILES = ("RaceResults.qml", "ResultsEvents.qml", "ResultsSessionList.qml", "ResultsLaps.qml", "ReplayList.qml",
                 "ReplayView.qml", "ResultsComments.qml", "ResultsTable.qml", "ResultsPositions.qml")


def test_switches_keep_their_binding_and_menus_toggle_below():
    for name in RESULTS_FILES:
        text = qml(name)
        assert "onToggled" not in text, name
        assert not re.search(r"\.height \+ [0-9]\)", text), name  # menu gap: theme.space1
        assert not re.search(r"\.visible \? \w+\.close\(\)", text), name  # TpMenu.toggleBelow: second click closes


def test_empty_states_use_tp_state_view():
    results = qml("RaceResults.qml")
    assert "TpLoadingState" not in results and 'objectName: "sessionState"' in results
    replays = qml("ReplayList.qml")
    assert "TpLoadingState" not in replays and 'objectName: "replayListState"' in replays


def test_watch_replay_french_label_fixed():
    from neopedal.i18n.fr import TRANSLATION

    assert TRANSLATION["Watch Replay"] == "Regarder le rejeu"
    assert "Revoir le rejeu" not in TRANSLATION.values()


# --- Replay tab of a session (T5) & links (T9) on the page
def test_replay_tab_only_with_the_session_replay(page):  # noqa: F811
    from neopedal.ui.quick.results_backend import REPLAY_TAB

    dialog, folder = page
    results, replays = dialog.backend, dialog.replays
    dialog.show()
    assert wait_until(lambda: results.loaded_once and results.hasSession)
    root = dialog.view.rootObject()
    assert results.sessionHeader["replay"] == REPLAY and REPLAY_TAB in results.tabKeys
    # Session without replay (practice): no replay tab, replay tab picked before falls back to the first tab
    results.setTab(REPLAY_TAB)
    assert results.shownTab == REPLAY_TAB
    results.select(str(folder / "2026_09_21_18_00_00-10P1.xml"))
    assert wait_until(lambda: results.selectedKey.endswith("10P1.xml") and results.hasSession)
    assert results.tabKeys == [0, 2, 3] and results.shownTab == 0
    assert not replays._shown  # game never asked for a replay tab not shown
    settle(0.3)  # toolbar of one action (fractional width): its text kept, never icon only for a rounded pixel
    assert named(root, "trackStatsButton").property("text") == "Track Stats"
    # Replays list: the player is always there (game replay or live session)
    results.setListMode(1)
    assert REPLAY_TAB in results.tabKeys and replays._shown
    results.setListMode(0)
    # Session with its replay: tab back, the game shows another replay: never shown under the session
    results.select(str(folder / RACE_NAME))
    assert wait_until(lambda: results.selectedKey.endswith(RACE_NAME) and results.shownTab == REPLAY_TAB)
    settle(0.1)
    state = named(root, "sessionReplayState")
    assert state.property("visible") and not replays.playingReplay
    replays.state, replays.playing = "replay", "Algarve P1 1"  # another replay open from the replays list
    replays.statusChanged.emit()
    replays.playbackChanged.emit()
    settle(0.05)
    assert state.property("visible")
    # Its own replay open: the player
    replays.playing = REPLAY
    replays.playbackChanged.emit()
    settle(0.05)
    assert replays.playingReplay == REPLAY and not state.property("visible")
    assert any(item.objectName() == "replayToolbar" and item.property("visible") for item in everything(root))
    # Replay opening (command not answered): spinner, no button
    replays.state = "menu"
    replays.statusChanged.emit()
    replays.playbackChanged.emit()
    settle(0.05)
    assert replays.openingReplay == REPLAY and state.property("visible") and state.property("loading")
    assert not dialog.view.errors()


def test_other_replay_told_in_replays_list(page):  # noqa: F811
    dialog, _folder = page
    results, replays = dialog.backend, dialog.replays
    dialog.show()
    assert wait_until(lambda: results.loaded_once and results.hasSession)
    results.setListMode(1)
    root = dialog.view.rootObject()
    replays.selected_replay = REPLAY
    replays.state, replays.playing = "replay", "Algarve P1 1"
    replays.selectionChanged.emit()
    replays.statusChanged.emit()
    replays.playbackChanged.emit()
    results.setTab(4)
    settle(0.1)
    notice = named(root, "otherReplayNotice")
    assert notice.property("visible")
    replays.playing = REPLAY
    replays.playbackChanged.emit()
    settle(0.05)
    assert not notice.property("visible")


def test_track_stats_and_lap_telemetry_links(page, monkeypatch, tmp_path):  # noqa: F811
    from types import SimpleNamespace

    from neopedal.ui import toast, tools_view
    from neopedal.ui.quick import lap_focus

    dialog, _folder = page
    results = dialog.backend
    dialog.show()
    assert wait_until(lambda: results.loaded_once and results.hasSession)
    opened, shown, combos, messages = [], [], [], []
    stats = SimpleNamespace(show_results_combo=lambda *args: combos.append(args))
    viewer = SimpleNamespace(backend=stats)
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: opened.append(path) or viewer)
    monkeypatch.setattr(lap_focus, "show_laps", lambda backend, path: shown.append(path) or True)
    results.openTrackStats()  # no player found in this file (two people, no profile name): track only
    assert results.result.player_entry is None
    assert opened == ["driver_stats_viewer.DriverStatsViewer"] and combos == [("24 Heures du Mans", "Circuit de la Sarthe")]
    first, *others = results.result.entries
    results.result = results.result._replace(entries=(first._replace(player=True), *others))
    results.openTrackStats()  # player's car too
    assert combos[-1] == ("24 Heures du Mans", "Circuit de la Sarthe", "Hyper", first.car, first.vehicle)
    opened.clear()
    # Lap not recorded: told, nothing opened
    monkeypatch.setattr(toast, "show_toast", lambda widget, text, **kwargs: messages.append((text, kwargs)))
    results.openLapTelemetry(2)
    assert messages[0][1] == {"level": "warning"} and not opened
    # Recorded lap: lap viewer opened on it, button shown on its row
    path = tmp_path / "lap.csv"
    path.write_text("x", encoding="utf-8")
    results.recorded_found(((results.shown_key, results.selected_entry), {2: str(path)}))
    assert results.lapColumns["telemetry"] is True
    assert [row["telemetry"] for row in results.lapModel.rows] == [False, True, False]
    results.openLapTelemetry(2)
    assert opened[-1] == "lap_viewer.LapViewer" and shown == [str(path)]
    results.setTab(2)
    settle(0.1)
    buttons = [item for item in everything(dialog.view.rootObject()) if item.objectName() == "lapTelemetryButton"]
    assert buttons and sum(bool(item.property("visible")) for item in buttons) == 1
    QMetaObject.invokeMethod(next(item for item in buttons if item.property("visible")), "clicked")
    assert shown == [str(path), str(path)]


def test_results_combo_of_stats():
    from neopedal.ui.quick.stats_core import results_combo

    stats = {"24 Heures du Mans": {"Hyper - Ferrari": {}, "Hyper": {}, "Car B #2": {}}, "Spa": {"GT3": {}}}
    assert results_combo(stats, "24 heures du mans", "Circuit", "Hyper", "Ferrari 499P", "Car B #2") == (
        "24 Heures du Mans", "Car B #2")
    del stats["24 Heures du Mans"]["Car B #2"]
    assert results_combo(stats, "24 Heures du Mans", "", "Hyper", "Ferrari 499P", "Car B #2") == (
        "24 Heures du Mans", "Hyper - Ferrari")
    assert results_combo(stats, "Le Mans", "24 Heures du Mans", "Hyper", "Toyota", "Car A") == (
        "24 Heures du Mans", "Hyper")
    assert results_combo(stats, "Monza", "", "GT3") is None
    assert results_combo(stats, "Spa", "", "") == ("Spa", "")


@pytest.fixture
def french(ui_env):
    from neopedal import i18n

    i18n.set_language("Français")  # before the page is built (page fixture after this one)
    yield
    i18n.set_language("English")


def test_page_in_french_and_narrow(french, page):  # noqa: F811
    dialog, _folder = page
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        dialog.show()
        assert wait_until(lambda: dialog.backend.loaded_once and dialog.backend.hasSession)
        for tab in (0, 1, 2, 3, 4):
            dialog.backend.setTab(tab)
            settle(0.05)
        dialog.resize(760, 600)
        settle(0.1)
        dialog.backend.setListMode(1)
        settle(0.1)
        root = dialog.view.rootObject()
        toolbar = named(root, "sessionToolbar")
        assert toolbar.property("visible")
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages
    assert not dialog.view.errors()


@pytest.fixture(autouse=True)
def _flush():
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
