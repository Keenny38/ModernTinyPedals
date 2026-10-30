"""UI/UX audit 2026-10-29, driver stats (T8, T9, weekly progress): tabs Overview / Progression / Compare with at
most 3 cards beside the table, filters as removable chips, official races & rivals opening a menu (stats, recorded
laps, race calculator, results), menus closed by a second click, progress of the last days (pure function shared
with the Home page)"""

import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QObject, qInstallMessageHandler

from neopedal.process import results_file as rf
from neopedal.process import results_index as ri
from neopedal.setting import cfg
from neopedal.ui.quick import stats_analysis, stats_overview
from neopedal.ui.quick.stats_analysis import parse_goals, weekly_progress
from neopedal.userfile import driver_history
from neopedal.userfile.driver_history import SessionRecord
from tests.test_driver_stats_viewer import (  # noqa: F401  (fixtures)
    OREGA,
    SPA,
    backend,
    dialogs,
    item_texts,
    page,
    settle,
    window,
)

DAY = 86400.0
NOW = 1_800_000_000.0
FERRARI = "Hyper - Ferrari"


def record(days_ago: float, track: str = SPA, vehicle: str = OREGA, best: float = 0.0, **values) -> SessionRecord:
    return SessionRecord(NOW - days_ago * DAY, track, vehicle, 1, best, **values)


# --- Weekly progress (pure function)
def test_weekly_progress_nothing_driven():
    assert weekly_progress([], {}, NOW) == []
    assert weekly_progress([record(10, best=120.0)], {f"{SPA}|{OREGA}": 119.0}, NOW) == []  # older than 7 days


def test_weekly_progress_summary_records_and_goals():
    records = [
        record(20, best=122.0),  # before the week: previous best
        record(3, best=121.6, valid=10, invalid=2, seconds=1800.0, meters=50000.0),
        record(1, best=121.4, valid=5, seconds=600.0),  # new personal best of the week (best of the week)
        record(2, "Monza", "GT3 - BMW", best=107.0, valid=8, seconds=900.0),  # first lap time here
        record(4, SPA, FERRARI, best=118.95),  # goal 119.0 reached this week
        record(5, "Imola", "GT3 - BMW", best=100.3),  # goal 100.0 near (0.3 s)
        record(-1, best=110.0),  # after now: ignored
    ]
    goals = {f"{SPA}|{FERRARI}": 119.0, "Imola|GT3 - BMW": 100.0, f"{SPA}|{OREGA}": 115.0}
    items = weekly_progress(records, goals, NOW)
    assert items == weekly_progress(list(reversed(records)), goals, NOW)  # same answer whatever the order
    summary = items[0]
    assert summary == {"kind": "summary", "sessions": 5, "laps": 25, "seconds": 3300.0, "meters": 50000.0,
                       "tracks": 3, "vehicles": 4}
    kinds = [item["kind"] for item in items]
    assert kinds == ["summary", "goal_reached", "record", "record", "record", "record", "goal_near"]
    reached = items[1]
    assert reached["track"] == SPA and reached["vehicle"] == FERRARI and reached["goal"] == 119.0
    records_found = {(item["track"], item["vehicle"]): item for item in items if item["kind"] == "record"}
    oreca = records_found[(SPA, OREGA)]
    assert oreca["best"] == 121.4 and oreca["previous"] == 122.0 and oreca["gain"] == pytest.approx(0.6)
    assert records_found[("Monza", "GT3 - BMW")]["previous"] == 0.0  # first lap time
    assert [item["time"] for item in items if item["kind"] == "record"] == sorted(
        (item["time"] for item in items if item["kind"] == "record"), reverse=True)  # newest first
    near = items[-1]
    assert near["track"] == "Imola" and near["gap"] == pytest.approx(0.3)
    # Oreca 6.4 s from its goal: not near; goal reached before the week: not told again
    assert weekly_progress([record(20, SPA, FERRARI, best=118.0), record(1, SPA, FERRARI, best=118.5)],
                           goals, NOW)[1:] == []


def test_weekly_progress_uses_stats_best_and_period():
    goals = {f"{SPA}|{OREGA}": 120.0}
    records = [record(2, best=121.0)]
    assert [item["kind"] for item in weekly_progress(records, goals, NOW)] == ["summary", "record"]  # 1 s: not near
    items = weekly_progress(records, goals, NOW, bests={(SPA, OREGA): 120.2})  # completed from results files
    assert items[-1]["kind"] == "goal_near" and items[-1]["best"] == 120.2
    assert weekly_progress(records, goals, NOW, days=1) == []
    assert weekly_progress(records, goals, NOW, near=2.0)[-1]["gap"] == pytest.approx(1.0)


def test_parse_goals():
    assert parse_goals({"a|b": 100.5, "c|d": 0, "e|f": "1:40", "g|h": -2}) == {"a|b": 100.5}
    assert parse_goals(None) == {} and parse_goals([]) == {}


# --- Backend: tab, filter chips, rivals & official races menu, weekly card
@pytest.fixture
def stats(backend):  # noqa: F811
    now = time.time()
    history = [SessionRecord(now - 20 * DAY, SPA, OREGA, 1, 122.0, valid=4),
               SessionRecord(now - 2 * DAY, SPA, OREGA, 1, 121.5, valid=6, seconds=1200.0, wetness=0.4, online=1,
                             game_version="1.42"),
               SessionRecord(now - DAY, SPA, FERRARI, 2, 119.0, valid=3, seconds=600.0, wetness=0.0, online=0,
                             game_version="1.41")]
    driver_history.save_history(cfg.path.config, history)
    backend.reload_stats()
    settle(backend)
    return backend


def test_stats_tab_kept_and_bounded(stats):
    assert stats.statsTab == 0
    stats.setStatsTab(2)
    assert stats.statsTab == 2 and stats.viewer_config()["stats_tab"] == 2
    stats.setStatsTab(5)
    stats.setStatsTab(-1)
    assert stats.statsTab == 2
    stats.viewer_config()["stats_tab"] = "x"  # edited by hand: first tab
    assert stats.statsTab == 0


def test_filter_chips_removed_one_by_one(stats):
    stats.selectTrack(SPA)
    stats.selectRow(OREGA)
    assert stats.filterChips == []
    stats.setConditionFilter(2)
    stats.setOnlineFilter(1)
    stats.setVersionFilter(1)
    chips = stats.filterChips
    assert [chip["key"] for chip in chips] == ["road", "server", "version"]
    assert chips[0]["text"] == "Wet Road" and chips[2]["text"].startswith("Since v")
    stats.clearFilter("server")
    assert [chip["key"] for chip in stats.filterChips] == ["road", "version"] and stats.filtered
    stats.clearFilter("unknown")
    stats.clearFilter("road")
    stats.clearFilter("version")
    assert stats.filterChips == [] and not stats.filtered


def test_weekly_card_rows_open_their_combo(stats):
    stats.selectTrack("")
    weekly = stats.weekly
    assert weekly["summary"].startswith("2 sessions") and "30 min" in weekly["summary"]
    kinds = {row["kind"] for row in weekly["rows"]}
    assert kinds == {"record"} and all(row["track"] == SPA for row in weekly["rows"])
    oreca = next(row for row in weekly["rows"] if row["vehicle"] == OREGA)
    assert oreca["detail"].startswith("New personal best 2:01.500") and oreca["tone"] == "gain"
    assert weekly is stats.weekly_card()  # made again only when something changed


def test_rivals_menu_on_last_race_together(stats, monkeypatch):
    ann = ri.Rival("Ann", 2, rf.FINISHED, 119.0)
    base = {"path": "", "game": "LMU", "start": 0.0, "end": 0.0, "kind": "Race", "code": "R", "track": SPA,
            "venue": "", "game_version": "1.42", "setting": "Multiplayer", "server": "", "cars": 20, "class_cars": 10,
            "driver": "Me", "vehicle": "", "car": "", "car_class": "LMP2_ELMS", "position": 5, "class_position": 3,
            "status": rf.FINISHED, "best_lap": 120.0, "laps": 20, "gap_laps": 0, "gap_time": 1.0, "contacts": 0,
            "impacts": 0, "penalties": 0, "track_limits": 0.0, "rivals": (ann,)}
    stats.results = [ri.ResultSummary(**{**base, "path": "old.xml", "end": 10.0, "track": "Monza"}),
                     ri.ResultSummary(**{**base, "path": "last.xml", "end": 20.0})]
    stats._linked = {"last.xml": OREGA}
    stats._results_serial += 1
    stats.selectTrack("")
    rival = stats.rivals[0]
    assert (rival["path"], rival["track"], rival["vehicle"]) == ("last.xml", SPA, OREGA)
    found = stats_analysis.rivals(stats.results)[0]
    assert found.path == "last.xml" and found.track == SPA
    monkeypatch.setattr(stats_overview, "race_preparation", lambda: None)  # calculator without it: entry disabled
    actions = {action["id"]: action for action in stats.comboActions(SPA, OREGA, "last.xml")}
    assert list(actions) == ["stats", "laps", "prepare", "results"]
    assert actions["stats"]["enabled"] and not actions["laps"]["enabled"] and not actions["prepare"]["enabled"]
    opened = []
    monkeypatch.setattr(type(stats), "openResults", lambda self, path: opened.append(path))
    stats.runComboAction("results", SPA, OREGA, "last.xml")
    assert opened == ["last.xml"]
    stats.runComboAction("stats", SPA, OREGA, "")
    assert stats.currentTrack == SPA and stats.selectedKey == OREGA
    assert "results" not in {action["id"] for action in stats.comboActions("Unknown", "", "")}
    assert not stats.comboActions("Unknown", "", "")[0]["enabled"]  # track not in stats


def test_prepare_race_with_calculator_function(stats, monkeypatch):
    calls = []
    monkeypatch.setattr(stats_overview, "race_preparation",
                        lambda: lambda parent, track, vehicle, lap_time: calls.append((track, vehicle, lap_time)) or True)
    actions = {action["id"]: action for action in stats.comboActions(SPA, OREGA, "")}
    assert actions["prepare"]["enabled"] and "results" not in actions
    stats.runComboAction("prepare", SPA, OREGA, "")
    stats.runComboAction("prepare", SPA, "", "")  # track only
    assert calls == [(SPA, OREGA, 121.5), (SPA, "", 0.0)]

    def broken(*_args):
        raise RuntimeError("calculator page error")

    monkeypatch.setattr(stats_overview, "race_preparation", lambda: broken)
    assert stats.prepare_race(SPA, OREGA) is False  # logged, page keeps working


def test_race_preparation_lookup(monkeypatch):
    from neopedal.ui import race_calculator

    monkeypatch.setattr(race_calculator, "prepare_race", lambda *args: True, raising=False)
    assert stats_overview.race_preparation() is race_calculator.prepare_race
    monkeypatch.delattr(race_calculator, "prepare_race")
    assert stats_overview.race_preparation() is None


def test_open_laps_of_another_track(stats, monkeypatch):
    import os

    from neopedal.ui import tools_view

    folder = f"{SPA} - Hyper"
    lap_backend = SimpleNamespace(tracks=[folder], currentTrack="", refresh=lambda: None, entries=[],
                                  setReference=lambda path: None)
    opened = []
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: opened.append(path) or SimpleNamespace(backend=lap_backend))
    stats.selectTrack("")
    assert not stats.open_laps(SPA, FERRARI) and opened == []  # nothing recorded: warning, viewer not opened
    os.makedirs(os.path.join(cfg.path.telemetry, folder))
    assert stats.lap_folder_of(SPA, FERRARI) == folder and stats.lap_folder_of(SPA, "") == folder
    assert stats.open_laps(SPA, FERRARI) and lap_backend.currentTrack == folder


# --- Page: tabs, 3 cards at most beside the table, menus, French
def side_cards(view) -> list:
    """Titles of the section cards shown in the side column"""
    side = view.rootObject().findChild(QObject, "statsSide")
    assert side is not None
    found, stack = [], list(side.property("contentItem").childItems())
    while stack:
        item = stack.pop()
        if not item.isVisible():
            continue
        if item.property("busy") is not None and isinstance(item.property("count"), str):  # TpSectionCard
            found.append(item.property("title"))
            continue
        stack.extend(item.childItems())
    return found


@pytest.mark.parametrize("language", ["English", "Français"])
def test_every_tab_without_qml_warnings(dialogs, language, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QEvent

    from neopedal import i18n
    from neopedal.api_control import api
    from neopedal.ui.driver_stats_viewer import DriverStatsViewer
    from tests.test_driver_stats_viewer import STATS, write_stats

    monkeypatch.setattr(stats_overview, "online_enabled", lambda: True)
    event = stats_analysis.Upcoming("beginner", "Daily", time.time() + 3600, SPA, "", ())
    monkeypatch.setattr(stats_overview, "read_official_races", lambda: ([event], {}))
    now = time.time()
    driver_history.save_history(cfg.path.config, [SessionRecord(now - DAY, SPA, OREGA, 1, 121.0, valid=4),
                                                  SessionRecord(now - 30 * DAY, SPA, OREGA, 1, 122.0)])
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    write_stats(STATS)
    monkeypatch.setattr(type(api.read.session), "track_name", lambda self: SPA, raising=False)
    i18n.set_language(language)
    viewer = DriverStatsViewer(None)  # page texts in the language set
    try:
        viewer.resize(1400, 860)
        viewer.show()
        backend = viewer.backend
        backend.reload_stats()
        settle(backend)
        backend.setUpcomingEnabled(True)
        settle(backend)
        for track in (SPA, ""):
            backend.selectTrack(track)
            for tab in (0, 1, 2):
                backend.setStatsTab(tab)
                for _ in range(3):
                    QCoreApplication.processEvents()
                cards = side_cards(viewer.view)
                assert len(cards) <= 3, (track, tab, cards)
                if tab == 1 and track:
                    assert cards == []  # progression card takes the whole width under the table
        backend.selectTrack(SPA)
        backend.selectRow(OREGA)
        backend.setStatsTab(1)
        backend.setConditionFilter(1)
        for _ in range(3):
            QCoreApplication.processEvents()
        chips = viewer.view.rootObject().findChild(QObject, "statsFilterChips")
        assert chips is not None and chips.property("visible")
        texts = item_texts(viewer.view)
        if language == "English":
            assert {"Overview", "Compare", "This Week", "Friends & Codes", "Dry Road"} <= texts
        else:
            assert {"Vue d'ensemble", "Comparaison", "Cette semaine", "Amis et codes", "Sur piste sèche"} <= texts
        backend.clearFilters()
        backend.setStatsTab(0)
        viewer.resize(860, 640)  # narrow: cards below the table
        for _ in range(3):
            QCoreApplication.processEvents()
        assert not viewer.view.errors()
    finally:
        i18n.set_language("English")
        qInstallMessageHandler(previous)
        viewer.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not [text for text in messages if ".qml" in text], messages


def test_menu_closed_by_second_click(page):  # noqa: F811
    from PySide6.QtCore import Q_ARG, QMetaObject, Qt

    page.resize(1400, 860)
    page.show()
    QCoreApplication.processEvents()
    root = page.view.rootObject()
    menu = root.findChild(QObject, "statsComboMenu")
    toolbar = root.findChild(QObject, "statsToolbar")
    assert menu is not None and toolbar is not None

    def popup():
        QMetaObject.invokeMethod(root, "popupBelow", Qt.ConnectionType.DirectConnection,
                                 Q_ARG("QVariant", menu), Q_ARG("QVariant", toolbar))
        QCoreApplication.processEvents()

    popup()
    assert menu.property("visible")
    popup()  # second click on the same button: closed
    assert not menu.property("visible") or not menu.property("opened")
    for _ in range(30):
        QCoreApplication.processEvents()
    assert not menu.property("opened")
