"""Race results linked to driver stats history (classification, incidents, game version, lap times to
complete, driver card) & to game replays (replay button of race results page)"""

import json
import os
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from neopedal.process import player_profile as pp
from neopedal.process import results_file as rf
from neopedal.process import results_index as ri
from neopedal.setting import cfg
from neopedal.userfile import driver_history
from neopedal.userfile.driver_history import SessionRecord, parse_record, record_line
from tests.test_driver_stats_viewer import OREGA, SPA, STATS, backend, dialogs, settle, window  # noqa: F401
from tests.test_race_results import PRACTICE_XML, RACE_NAME, RACE_XML, wait_until, write_results

END = 1_790_001_000.0  # results file written


def race(names=("alice driver",)) -> rf.SessionResult:
    return rf.parse_results(RACE_XML.encode("utf-8"), RACE_NAME, list(names))


def summary(**changes) -> ri.ResultSummary:
    found = ri.summarize(race(), END, ["alice driver"])
    assert found is not None
    return found._replace(**changes)


# Results summed up for player
@pytest.mark.parametrize(("text", "version"), [
    ("1.4200", "1.42"), ("1.420", "1.42"), ("1.4150", "1.415"), ("1.4000", "1.40"), ("v2.1", "2.10"),
    ("unknown", ""), ("", ""), ("0", ""), ("beta 3", "beta 3"), (None, ""),
])
def test_game_version_text(text, version):
    assert ri.game_version_text(text) == version


def test_session_code():
    assert ri.session_code("c:/x/2026_10_05_22_34_33-70R1.xml") == "R"
    assert ri.session_code("2026_10_05-04q1.xml") == "Q"
    assert ri.session_code("notes.xml") == ""


def test_summarize_player_session():
    found = summary()
    assert (found.kind, found.code, found.track, found.venue) == ("Race", "R", "24 Heures du Mans", "Circuit de la Sarthe")
    assert found.game_version == "1.42" and found.start == 1790000600 and found.end == END
    assert (found.cars, found.class_cars, found.position, found.class_position) == (3, 2, 1, 1)
    assert found.gap_time == 0 and found.gap_laps == 0  # class leader
    assert (found.contacts, found.impacts, found.penalties, found.track_limits) == (1, 0, 0, 0.0)
    assert found.best_lap == pytest.approx(97.9)


def test_summarize_other_driver_gap_and_incidents():
    found = ri.summarize(race(("bob racer",)), END, ["bob racer"])
    assert found is not None and found.driver == "Bob Racer"
    assert found.gap_time == pytest.approx(4.7) and found.gap_laps == 0  # finish times
    assert (found.contacts, found.penalties, found.track_limits) == (1, 1, 0.5)


def test_own_laps_in_team_race():
    """Teammate laps & incidents left out: Zed Partner drove lap 1 of Alice's car"""
    found = ri.summarize(race(("zed partner",)), END, ["zed partner"])
    assert found is not None and found.best_lap == pytest.approx(100.9)
    assert found.contacts == 0  # contact was Alice's


def test_summarize_without_player():
    assert ri.summarize(race(()), END) is None  # several humans online, no profile name: not found


def test_read_summaries_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {})
    folder = tmp_path / "Results"
    practice = "2026_09_21_18_00_00-10P1.xml"
    write_results(folder, {RACE_NAME: RACE_XML, practice: PRACTICE_XML.format(laps=3),
                           "2026_09_21_17_00_00-11P1.xml": "<broken"})
    ri.forget_summaries()
    found = ri.read_summaries([str(folder)])
    assert [item.kind for item in found] == ["Practice"]  # race without player (online), broken file skipped
    calls = []
    monkeypatch.setattr(rf, "read_results", lambda *args: calls.append(args))
    assert ri.read_summaries([str(folder)]) == found and not calls  # files unchanged: not read again
    os.remove(folder / practice)
    assert ri.read_summaries([str(folder)]) == []
    ri.forget_summaries()


# Stints of driver stats history linked to sessions
def test_match_session_by_time_kind_track_and_vehicle():
    found = summary(car="Toyota GR010", vehicle="Car A #1", car_class="Hyper")
    sessions = [found]
    match = ri.match_session
    assert match(END + 60, 4, "24 Heures du Mans", sessions) is found  # stint saved after results written
    assert match(found.start + 100, 4, "circuit de la sarthe", sessions) is found  # venue, any case
    assert match(found.start - 600, 4, "24 Heures du Mans", sessions) is None  # before session
    assert match(END + ri.STINT_AFTER_END + 1, 4, "24 Heures du Mans", sessions) is None
    assert match(END, 1, "24 Heures du Mans", sessions) is None  # practice stint
    assert match(END, 4, "Monza", sessions) is None
    assert match(END, 4, "24 Heures du Mans", sessions, "Hyper - Toyota", "Hyper") is found
    assert match(END, 4, "24 Heures du Mans", sessions, "Hyper", "Hyper") is found  # class key
    assert match(END, 4, "24 Heures du Mans", sessions, "Car A #1") is found  # vehicle name key
    assert match(END, 4, "24 Heures du Mans", sessions, "Hyper - BMW", "Hyper") is None  # next car driven
    assert match(END, 4, "24 Heures du Mans", sessions, "GT3 - Toyota", "GT3") is None


def test_match_latest_session_started_before_stint():
    first = summary(path="a.xml", start=1000.0, end=2000.0)
    second = summary(path="b.xml", start=2500.0, end=3500.0)
    assert ri.match_session(2400.0, 4, "24 Heures du Mans", [first, second]) is first
    assert ri.match_session(2600.0, 4, "24 Heures du Mans", [first, second]) is second


# Replays of sessions
def test_match_replays_closest_once(tmp_path):
    sessions = [ri.ReplaySession("r1.xml", "Road Atlanta", "Road Atlanta", "R", 1000.0),
                ri.ReplaySession("q1.xml", "Road Atlanta", "Road Atlanta", "Q", 1000.0),
                ri.ReplaySession("r2.xml", "Road Atlanta", "Road Atlanta", "R", 1100.0)]
    replays = [ri.ReplayFile("Road Atlanta R1 1", "a", 1230.0),
               ri.ReplayFile("Road Atlanta R1 2", "b", 1050.0),  # closest to both races: first one
               ri.ReplayFile("Road Atlanta Q1 1", "c", 5000.0),  # too late
               ri.ReplayFile("Monza R1 1", "d", 1000.0),
               ri.ReplayFile("my copy", "e", 1000.0)]
    found = ri.match_replays(sessions, replays)
    assert {path: replay.name for path, replay in found.items()} == {
        "r1.xml": "Road Atlanta R1 2", "r2.xml": "Road Atlanta R1 1"}  # each replay once
    assert "q1.xml" not in found  # qualifying replay saved too late
    assert ri.replay_key("Silverstone - ELMS P1 12") == ("silverstone - elms", "P")
    assert ri.replay_key("nothing") == ("", "")


def test_session_replays_from_game_folder(tmp_path):
    root = tmp_path / "Le Mans Ultimate"
    results = root / "UserData" / "Log" / "Results"
    replays = root / "UserData" / "Replays"
    write_results(results, {RACE_NAME: RACE_XML})
    replays.mkdir(parents=True)
    replay = replays / "24 Heures du Mans R1 3.Vcr"
    replay.write_bytes(b"vcr")
    (replays / "_vcr1.tmp").write_bytes(b"")
    written = os.path.getmtime(results / RACE_NAME)
    os.utime(replay, (written + 120, written + 120))
    session = ri.ReplaySession(str(results / RACE_NAME), "24 Heures du Mans", "Circuit de la Sarthe", "R", written)
    found = ri.session_replays([session])
    assert found[session.path].name == "24 Heures du Mans R1 3"
    assert ri.replay_folder(str(tmp_path / "x" / "y" / "z")) == ""
    assert ri.list_replay_files(str(tmp_path / "missing")) == []


# Lap times of stats completed from results
def test_best_lap_fixes():
    stats = {"24 Heures du Mans": {"Hyper - Toyota": {"pb": 99.0, "rb": 97.0}, "Hyper - Ferrari": {"pb": 90.0}}}
    lmu = summary(game="LMU", car="Toyota GR010", vehicle="Car A #1")
    fixes = ri.best_lap_fixes([lmu], stats, {}, "Class - Brand", {})
    assert [(fix.vehicle, fix.stat, fix.current) for fix in fixes] == [("Hyper - Toyota", "pb", 99.0)]  # rb faster
    assert fixes[0].laptime == pytest.approx(97.9) and fixes[0].path == RACE_NAME
    assert ri.best_lap_fixes([lmu._replace(game="rFactor 2")], stats, {}, "Class - Brand", {}) == []
    assert ri.best_lap_fixes([lmu._replace(best_lap=0.0)], stats, {}, "Class - Brand", {}) == []
    # Vehicle key of history record linked to session, else brands preset
    linked = ri.best_lap_fixes([lmu], stats, {RACE_NAME: "Hyper - Ferrari"}, "Class - Brand", {})
    assert [(fix.vehicle, fix.stat) for fix in linked] == [("Hyper - Ferrari", "rb")]  # PB 90.0 faster
    preset = ri.best_lap_fixes([lmu._replace(car="Prototype")], stats, {}, "Class - Brand", {"Car A #1": "Toyota"})
    assert [fix.vehicle for fix in preset] == ["Hyper - Toyota"]
    qualifying = ri.best_lap_fixes([lmu._replace(kind="Qualifying")], {"24 Heures du Mans": {"Hyper": {}}}, {},
                                   "Class", {})
    assert [(fix.stat, fix.current) for fix in qualifying] == [("pb", 0.0), ("qb", 0.0)]


def test_vehicle_key():
    found = summary(car="Ferrari 499P", vehicle="499P Custom #397", car_class="Hyper")
    keys = ["Hyper - Ferrari", "Hyper - BMW", "Hyper", "499P Custom #397"]
    assert ri.vehicle_key(found, keys, "Class - Brand", {}) == "Hyper - Ferrari"
    assert ri.vehicle_key(found, keys, "Class", {}) == "Hyper"
    assert ri.vehicle_key(found, keys, "Vehicle", {}) == "499P Custom #397"
    assert ri.vehicle_key(found, ["Hyper - BMW"], "Class - Brand", {}) == ""
    assert ri.vehicle_key(found, keys, "Class - Brand", {"499P Custom #397": "Lamborghini"}) == ""


# Game version in session history
def test_history_game_version():
    record = SessionRecord(1.0, "Spa", "GT3", game_version="1.42")
    line = record_line(record)
    assert '"game_version":"1.42"' in line
    assert parse_record(json.loads(line)) == record
    assert "game_version" not in record_line(record._replace(game_version=""))
    assert parse_record({"time": 1.0, "track": "Spa", "vehicle": "GT3", "game_version": 5}).game_version == ""


# Driver profile of game & Steam picture
def test_player_profile(tmp_path, monkeypatch):
    root = tmp_path / "Le Mans Ultimate"
    (root / "UserData" / "player").mkdir(parents=True)
    (root / "UserData" / "player" / "Settings.JSON").write_text(json.dumps({
        "DRIVER": {"Player Name": "Alice Driver", "Player Nick": "Ali", "Nationality": "fr"},
        "CUSTOMLIVERY": {"teamName": "Team A", "vehicleNumber": "7"}}), encoding="utf-8")
    steam = tmp_path / "Steam"
    (steam / "config" / "avatarcache").mkdir(parents=True)
    (steam / "config" / "loginusers.vdf").write_text(
        '"users"\n{\n\t"76561190000000001"\n\t{\n\t\t"MostRecent"\t\t"0"\n\t}\n'
        '\t"76561190000000002"\n\t{\n\t\t"MostRecent"\t\t"1"\n\t}\n}\n', encoding="utf-8")
    (steam / "config" / "avatarcache" / "76561190000000002.png").write_bytes(b"png")
    monkeypatch.setattr(rf, "steam_folder", lambda: str(steam))
    profile = pp.player_profile((str(root / "UserData" / "Log" / "Results"),))
    assert profile is not None
    assert (profile.name, profile.nickname, profile.nationality, profile.team, profile.number) == (
        "Alice Driver", "Ali", "FR", "Team A", "7")
    assert profile.avatar.endswith("76561190000000002.png")
    assert pp.steam_avatar("") == "" and pp.steam_avatar(str(tmp_path / "none")) == ""
    assert pp.read_profile(str(tmp_path / "none")) is None
    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {})
    assert pp.player_profile() is None


# Driver stats page
def results_data(*summaries, profile=None):
    from neopedal.ui.quick.stats_backend import ResultsData

    return ResultsData(list(summaries), profile)


def spa_race(**changes) -> ri.ResultSummary:
    values = {"track": SPA, "venue": SPA, "kind": "Race", "game": "LMU", "car_class": "LMP2_ELMS", "car": "Oreca 07",
              "vehicle": "Oreca #22", "start": 1_700_199_000.0, "end": 1_700_199_900.0, "class_position": 2,
              "class_cars": 12, "position": 5, "cars": 30, "contacts": 2, "penalties": 1, "gap_time": 3.5}
    return summary(**{**values, **changes})


def test_stats_sessions_from_results(backend):  # noqa: F811
    from neopedal.ui.quick import stats_backend

    driver_history.save_history(cfg.path.config, [
        SessionRecord(1_700_100_000.0, SPA, OREGA, 2, 121.5, valid=4, game_version="1.41"),
        SessionRecord(1_700_200_000.0, SPA, OREGA, 4, 122.0, valid=20, vehicle_class="LMP2_ELMS"),
    ])
    backend.reload_stats()
    settle(backend)
    backend.results_loaded(results_data(spa_race()))
    backend.selectTrack(SPA)
    backend.selectRow(OREGA)
    race_row, qualifying_row = backend.sessions
    assert race_row["results"] == spa_race().path and race_row["rank"] == "P2/12"
    assert race_row["version"] == "1.42" and race_row["incidents"] == 3
    assert "Position P5 of 30" in race_row["tip"] and "+3.500" in race_row["tip"]
    assert qualifying_row["version"] == "1.41" and qualifying_row["results"] == ""  # no results file
    assert "set on" in backend.progression["info"] and "Version 1.41" in backend.progression["info"]
    assert stats_backend.gap_text(spa_race(gap_laps=2)) == "+2 laps"
    assert stats_backend.summary_rank(spa_race(class_position=0)) == ""


def test_stats_driver_card_and_fixes(backend, monkeypatch):  # noqa: F811
    settle(backend)  # results of this computer read at first load (none in tests)
    profile = pp.PlayerProfile("Alice Driver", "Ali", "FR", "Team A", "7", "")
    backend.results_loaded(results_data(
        spa_race(best_lap=120.0, class_position=1, status=rf.FINISHED),  # faster than PB 121.5
        spa_race(path="b.xml", start=1_700_300_000.0, end=1_700_301_000.0, class_position=3, status="DNF",
                 contacts=0, penalties=0, best_lap=0.0),
        profile=profile))
    backend.selectTrack("")
    driver = backend.driver
    assert driver["visible"] and driver["name"] == "Alice Driver" and driver["initials"] == "AD"
    assert driver["detail"] == "France · Team A · #7" and driver["avatar"] == ""
    figures = {figure["label"]: figure["value"] for figure in driver["figures"]}
    assert figures["Races"] == "2" and figures["Wins"] == "1" and figures["Podiums"] == "1"
    assert figures["Clean Races"] == "1/2" and figures["Avg. Finish"] == "P1.0"
    assert driver["fixes"] == 2  # PB & race best of Oreca
    backend.completeLapTimes()
    settle(backend)
    with open(f"{cfg.path.config}driver.stats", encoding="utf-8") as file:
        saved = json.load(file)
    assert saved[SPA][OREGA]["pb"] == pytest.approx(120.0) and saved[SPA][OREGA]["rb"] == pytest.approx(120.0)
    assert saved[SPA][OREGA]["qb"] == STATS[SPA][OREGA]["qb"]
    assert backend.driver["fixes"] == 0
    backend.undo()
    settle(backend)
    with open(f"{cfg.path.config}driver.stats", encoding="utf-8") as file:
        assert json.load(file)[SPA][OREGA]["pb"] == STATS[SPA][OREGA]["pb"]
    backend.selectTrack(SPA)
    backend.selectRow(OREGA)
    assert backend.best_lap_result(SPA, OREGA, 120.0) is not None


def test_stats_open_results(backend, monkeypatch):  # noqa: F811
    from neopedal.ui import tools_view

    opened = []
    page = SimpleNamespace(backend=SimpleNamespace(open_path=opened.append))
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: page)
    backend.openResults("")
    backend.openResults("c:/results/a.xml")
    assert opened == ["c:/results/a.xml"]


# Race results page: replay button, session opened from driver stats
@pytest.fixture
def lmu_results(tmp_path, ui_env, monkeypatch):
    """Results & replay of an LMU install"""
    root = tmp_path / "Le Mans Ultimate"
    folder = root / "UserData" / "Log" / "Results"
    write_results(folder, {RACE_NAME: RACE_XML, "2026_09_21_18_00_00-10P1.xml": PRACTICE_XML.format(laps=5)})
    (root / "UserData" / "Replays").mkdir(parents=True)
    replay = root / "UserData" / "Replays" / "24 Heures du Mans R1 1.Vcr"
    replay.write_bytes(b"vcr")
    written = os.path.getmtime(folder / RACE_NAME)
    os.utime(replay, (written + 60, written + 60))
    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {"LMU": str(folder)})
    from neopedal.ui.quick.results_backend import RaceResultsBackend

    page = RaceResultsBackend()
    page.page_shown()
    assert wait_until(lambda: page.loaded_once)
    yield page, folder
    page.release()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_results_replay_button(lmu_results, monkeypatch):
    from neopedal.ui import tools_view

    page, folder = lmu_results
    assert page.sessionHeader["replay"] == "24 Heures du Mans R1 1"
    assert [row["replay"] for row in page.sessionModel.rows] == [True, False]
    watched = []
    replays = SimpleNamespace(backend=SimpleNamespace(watch_named=watched.append))
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: replays)
    page.watchReplay()
    assert watched == ["24 Heures du Mans R1 1"]
    page.select(str(folder / "2026_09_21_18_00_00-10P1.xml"))
    assert wait_until(lambda: page.sessionHeader.get("replay") == "")
    page.watchReplay()  # no replay: nothing opened
    assert watched == ["24 Heures du Mans R1 1"]


def test_results_open_path(lmu_results):
    page, folder = lmu_results
    page.setKindFilter(3)  # practice: race hidden
    page.open_path(str(folder / RACE_NAME))
    assert wait_until(lambda: page.hasSession and page.selectedKey.endswith(RACE_NAME))
    assert page.kindFilter == 0
    from neopedal.ui.quick.results_backend import load_page_settings

    assert load_page_settings()["kind"] == 3  # filter of user kept for next time
    page.open_path(str(folder / "missing.xml"))  # not a session: read again, nothing shown instead
    assert wait_until(lambda: not page.loading)
    assert page.selectedKey.endswith(RACE_NAME)


def test_results_open_path_before_loaded(ui_env, tmp_path, monkeypatch):
    folder = tmp_path / "Results"
    write_results(folder, {RACE_NAME: RACE_XML, "2026_09_21_18_00_00-10P1.xml": PRACTICE_XML.format(laps=5)})
    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {"LMU": str(folder)})
    from neopedal.ui.quick.results_backend import RaceResultsBackend

    page = RaceResultsBackend()
    try:
        page.open_path(str(folder / "2026_09_21_18_00_00-10P1.xml"))  # older session, page not shown yet
        assert wait_until(lambda: page.hasSession)
        assert page.selectedKey.endswith("10P1.xml")
    finally:
        page.release()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# Game replays page: replay asked by race results page
def test_watch_named_waits_for_replays_list():
    from neopedal.ui.quick.replays_backend import GameReplaysBackend

    notices, watched, asked = [], [], []
    known = {"Spa R1 1"}
    fake = SimpleNamespace(
        pending_watch="", replays_answered=False, notify=lambda text, error=False: notices.append(text),
        watchReplay=watched.append, ask_replays=lambda: asked.append(1),
        replay_of=lambda name: name if name in known else None)
    fake.watch_pending = lambda: GameReplaysBackend.watch_pending(fake)
    GameReplaysBackend.watch_named(fake, "Spa R1 1")
    assert fake.pending_watch == "Spa R1 1" and asked and not watched
    fake.watch_pending()  # game did not answer
    assert notices and "Start Le Mans Ultimate" in notices[-1] and fake.pending_watch == ""
    fake.replays_answered = True
    GameReplaysBackend.watch_named(fake, "Spa R1 1")
    assert watched == ["Spa R1 1"]
    fake.pending_watch = "Gone R1 1"
    fake.watch_pending()
    assert "Replay not found" in notices[-1]
    fake.pending_watch = "Spa R1 1"
    fake.watch_pending()
    assert watched == ["Spa R1 1", "Spa R1 1"]
