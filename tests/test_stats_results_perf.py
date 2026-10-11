"""Driver stats & race results work off the UI thread: history linked to results files in background (indexed
matcher, same matches as match_session), results files parsed once for both pages (released once no page uses
them), session history cache never waited for on close, parts of the stats page told only when changed, race
results reads debounced & single-flight, long race charts built in background"""

import random
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.process import results_file as rf
from neopedal.process import results_index as ri
from neopedal.setting import cfg
from neopedal.userfile import driver_history
from neopedal.userfile.driver_history import SessionRecord, record_line
from tests.test_driver_stats_viewer import OREGA, SPA, backend, dialogs, settle, window, write_stats  # noqa: F401
from tests.test_race_results import (  # noqa: F401
    RACE_NAME,
    RACE_XML,
    english,
    results_folder,
    wait_until,
    write_results,
)

UI_BUDGET = 0.05  # seconds a slot may hold the UI thread (generous: slow CI machines)
HISTORY_RECORDS = 50000
RESULTS = 500
TRACKS = [f"Track {number}" for number in range(40)]
BASE = ri.ResultSummary("", "LMU", 0.0, 0.0, "Race", "R", "", "", "1.42", "", "", 20, 10, "Me", "Car #1", "Car", "GT3",
                        1, 1, "Finished Normally", 100.0, 10, 0, 0.0, 0, 0, 0, 0.0)


def timed(call) -> float:
    start = time.perf_counter()
    call()
    return time.perf_counter() - start


def synthetic_summaries(count: int = RESULTS, seed: int = 1) -> list[ri.ResultSummary]:
    rng = random.Random(seed)
    summaries = []
    for number in range(count):
        start = 1_700_000_000 + number * 3000 + rng.random() * 100
        track = rng.choice(TRACKS)
        summaries.append(BASE._replace(
            path=f"{number}.xml", start=start, end=start + rng.choice((600, 1800, 7200)),
            kind=rng.choice(("Practice", "Qualifying", "Race", "Warmup")), track=track,
            venue=rng.choice((track, f"{track} Venue", "")), car_class=rng.choice(("GT3", "Hyper")),
            vehicle=rng.choice(("Car #1", "Other #2")), best_lap=95.0 + rng.random() * 10))
    summaries.sort(key=lambda summary: (summary.start, summary.path))
    return summaries


def synthetic_records(count: int, seed: int = 2) -> list[SessionRecord]:
    rng = random.Random(seed)
    return [SessionRecord(1_700_000_000.0 + index * 30 + rng.random() * 60, rng.choice([*TRACKS, " track 3 venue"]),
                          rng.choice(("GT3 - Car", "Hyper", "Car #1", "")) or "GT3", rng.randrange(-1, 6),
                          100.0 + index % 7, vehicle_class=rng.choice(("", "GT3", "Hyper")))
            for index in range(count)]


# --- Indexed matcher: same sessions as match_session
def test_matcher_same_as_match_session():
    summaries = synthetic_summaries()
    records = synthetic_records(20000)
    matcher, links, linked = ri.link_records(records, summaries)
    for record in records:
        expected = ri.match_session(record.time, record.session, record.track, summaries, record.vehicle,
                                    record.vehicle_class)
        assert links[record] is expected
        assert matcher.match(record.time, record.session, record.track, record.vehicle,
                             record.vehicle_class) is expected
    assert any(found is not None for found in links.values())  # matches tested, not only misses
    expected_linked = {}
    for record in records:
        if links[record] is not None:
            expected_linked[links[record].path] = record.vehicle
    assert linked == expected_linked


def test_matcher_equal_start_times_and_bounds():
    first = BASE._replace(path="a.xml", start=1000.0, end=2000.0, track="T", venue="T")
    same = BASE._replace(path="b.xml", start=1000.0, end=2100.0, track="T", venue="V")
    sessions = [first, same]
    matcher = ri.SessionMatcher(sessions)
    for time_value in (900.0, 940.0, 940.0001, 1000.0, 2100.0 + ri.STINT_AFTER_END, 2100.0 + ri.STINT_AFTER_END + 1):
        for track in ("T", " t ", "V", "", "X"):
            assert matcher.match(time_value, 4, track) is ri.match_session(time_value, 4, track, sessions)


def test_matcher_timing():
    summaries = synthetic_summaries()
    records = synthetic_records(HISTORY_RECORDS)
    elapsed = timed(lambda: ri.link_records(records, summaries))
    assert elapsed < 1.0  # match_session over every record: about 1 s on a fast machine


# --- Results files parsed once for both pages, released once no page uses them
def test_results_parsed_once_for_both_pages(results_folder, monkeypatch):  # noqa: F811
    from neopedal.ui.quick.results_backend import load_results

    ri.forget_summaries()
    calls = []
    real = rf.read_results
    monkeypatch.setattr(rf, "read_results", lambda *args: calls.append(args[0]) or real(*args))
    folders = (str(results_folder),)
    summaries = ri.read_summaries(folders)  # driver stats page
    parsed = len(calls)
    assert parsed == 3 and summaries
    calls.clear()
    loaded = load_results(folders, {})  # race results page: list from files kept, newest sessions read in full
    assert len(calls) <= 3 and all(info is not None for _, info in loaded.files.values())
    assert len(loaded.full) == 3
    calls.clear()
    load_results(folders, loaded.files)  # page knows every file: nothing read
    ri.read_summaries(folders)
    assert not calls
    ri.forget_summaries()


def test_results_released_with_last_page(results_folder, monkeypatch):  # noqa: F811
    folders = (str(results_folder),)
    monkeypatch.setattr(ri, "_holders", 0)  # pages of other tests never closed
    ri.forget_summaries()
    ri.hold_files()
    ri.hold_files()
    ri.read_summaries(folders)
    assert ri.kept_files() == 3
    ri.release_files()
    assert ri.kept_files() == 3  # a page still open
    ri.release_files()
    assert ri.kept_files() == 0


def test_scan_running_while_released_keeps_nothing(results_folder, monkeypatch):  # noqa: F811
    ri.forget_summaries()
    started, go_on = threading.Event(), threading.Event()
    real = rf.read_results

    def slow(*args):
        started.set()
        go_on.wait(5)
        return real(*args)

    monkeypatch.setattr(rf, "read_results", slow)
    thread = threading.Thread(target=ri.read_summaries, args=((str(results_folder),),))
    thread.start()
    assert started.wait(5)
    assert timed(ri.forget_summaries) < 0.05  # page closed: never waits for the scan
    go_on.set()
    thread.join(5)
    assert ri.kept_files() == 0


# --- Session history cache: page close never waits for a parse, late parse keeps nothing
def test_forget_records_never_waits_for_parse(tmp_path):
    folder = str(tmp_path)
    driver_history.save_history(folder, [SessionRecord(1_700_000_000.0 + index, "T", "C") for index in range(100)])
    driver_history.forget_records(folder)
    holder = threading.Thread(target=lambda: None)
    with driver_history._parsed_lock:  # parse running on a worker thread
        assert timed(lambda: driver_history.forget_records(folder)) < 0.05
    holder.start()
    holder.join()
    generation = driver_history.records_generation()
    driver_history.forget_records(folder)  # page closed while a parse ran: its records not kept
    driver_history.keep_records(driver_history.history_path(folder), driver_history._ParsedFile(
        (0, 0, 0), 0, b"", b"", [], []), generation)
    assert driver_history.kept_records(driver_history.history_path(folder)) is None


def test_written_records_kept_as_parsed(tmp_path):
    folder = str(tmp_path)
    records = [SessionRecord(1_700_000_000.0 + index, "Tré", "C", 1, 100.123456, 2, 1, 1000.98765, 61.0004,
                             vehicle_class="GT3" if index % 2 else "") for index in range(300)]
    written = driver_history.write_records(folder, records)
    kept = driver_history.read_records(folder)  # from records written
    driver_history.forget_records(folder)
    assert kept == driver_history.read_records(folder)  # same as parsed from file (values rounded as written)
    assert len(written) == 300 and kept[0].best == 100.123


# --- Driver stats page: big history & many results files
@pytest.fixture
def big_page(window, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import stats_backend

    stats = {track: {f"GT3 - Car {number}": {"pb": 100.0 + number, "seconds": 600.0, "valid": 5}
                     for number in range(25)} for track in TRACKS}
    write_stats(stats)
    rng = random.Random(3)
    path = driver_history.history_path(cfg.path.config)
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write("".join(record_line(SessionRecord(
            1_700_000_000.0 + index * 60, rng.choice(TRACKS), f"GT3 - Car {index % 25}", rng.choice((1, 2, 4)),
            100.0 + index % 7, vehicle_class="GT3")) for index in range(HISTORY_RECORDS - 1)))
    driver_history.forget_records()
    summaries = synthetic_summaries()
    reads = []
    monkeypatch.setattr(ri, "read_summaries", lambda folders: reads.append(threading.current_thread()) or summaries)
    monkeypatch.setattr(stats_backend, "player_profile", lambda folders: None)
    page = stats_backend.DriverStatsBackend(window)
    settle(page, timeout=60)
    page.reads = reads
    yield page
    page.release()
    settle(page, timeout=60)
    driver_history.forget_records()


def test_big_history_links_made_in_background(big_page):
    page = big_page
    assert len(page.history) == HISTORY_RECORDS - 1 and page.reads
    assert threading.main_thread() not in page.reads
    assert page._linked is not None and len(page._record_results) >= len(set(page.history)) - 1
    for track in ("", TRACKS[3], TRACKS[7], ""):
        assert timed(lambda track=track: page.selectTrack(track)) < UI_BUDGET * 2
    assert timed(page.refresh_table) < UI_BUDGET * 2  # theme switched
    page.selectTrack(TRACKS[3])
    page.selectRow("GT3 - Car 4")
    assert page.sessions and timed(lambda: page.selectRow("GT3 - Car 5")) < UI_BUDGET


def test_fixes_and_track_info_not_made_again_per_refresh(big_page, monkeypatch):
    page = big_page
    calls = []
    real = ri.best_lap_fixes
    monkeypatch.setattr(ri, "best_lap_fixes", lambda *args: calls.append(1) or real(*args))
    page.refresh_table()
    page.selectTrack(TRACKS[1])
    assert not calls  # results & stats unchanged
    count = sum(1 for record in page.history if record.track == TRACKS[1])
    assert page.trackInfo["subtitle"].startswith(f"25 vehicles · {count} sessions")
    page.selectTrack("")
    assert f"{len(page.history)} sessions" in page.trackInfo["subtitle"]


def test_parts_told_only_when_changed(big_page):
    page = big_page
    page.selectTrack("")
    told = []
    for name in ("statsChanged", "driverChanged", "activityChanged", "recentChanged", "tilesChanged",
                 "levelsChanged", "trackInfoChanged", "columnsChanged", "selectionChanged", "sortChanged",
                 "friendChanged"):
        getattr(page, name).connect(lambda name=name: told.append(name))
    page.refresh_table()  # nothing changed (stats saved with same values)
    assert not told


def test_per_lap_reload_of_big_stats_in_background(big_page, monkeypatch):
    from neopedal.ui.quick import stats_backend

    page = big_page
    monkeypatch.setattr(stats_backend, "SYNC_STATS_BYTES", 1)
    threads = []
    real = stats_backend.load_stats_json_file
    monkeypatch.setattr(stats_backend, "load_stats_json_file",
                        lambda **kwargs: threads.append(threading.current_thread()) or real(**kwargs))
    assert timed(page.reload_stats) < UI_BUDGET
    settle(page, timeout=60)
    assert threads and threading.main_thread() not in threads


def test_sort_by_last_driven_reads_nothing(big_page, monkeypatch):
    from neopedal.ui.quick import stats_backend

    page = big_page
    reads = []
    monkeypatch.setattr(stats_backend, "load_stats_json_file", lambda **kwargs: reads.append(1))
    page.selectTrack("")
    page.setSortRecent(True)
    keys = [entry["key"] for entry in page.tracks[1:]]
    assert keys == sorted(keys, key=lambda key: page.track_last_driven.get(key, 0.0), reverse=True)
    assert page.row_keys() == keys and not reads
    page.setSortRecent(False)
    assert [entry["key"] for entry in page.tracks[1:]] == sorted(keys, key=str.lower)


def test_history_released_while_hidden(big_page):
    page = big_page
    page.page_hidden()
    assert page.hidden_timer.isActive()
    page.release_history()  # hidden a while
    assert not page.history and not page._record_results
    assert driver_history.kept_records(driver_history.history_path(cfg.path.config)) is None
    page.page_shown()
    settle(page, timeout=60)
    assert len(page.history) == HISTORY_RECORDS - 1 and page._record_results


def test_friend_read_in_background(backend, tmp_path, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import stats_backend, stint_analysis

    friend = tmp_path / "friend.json"
    stint_analysis.write_history_json(str(friend), stint_analysis.history_document(
        [SessionRecord(1_700_000_000.0, SPA, OREGA, 1, 120.0)], {SPA: {OREGA: {"pb": 120.0}}}, {}, "Max"))
    threads = []
    real = stats_backend.load_friend
    monkeypatch.setattr(stats_backend, "load_friend", lambda name: threads.append(threading.current_thread()) or
                        real(name))
    backend.load_friend_file(str(friend), chosen=True)
    assert not backend.friend["visible"]
    settle(backend)
    assert backend.friend["visible"] and backend.friend["name"] == "Max"
    assert threads and threading.main_thread() not in threads
    assert backend.viewer_config().get("friend_file") == str(friend)
    backend.clearFriend()
    assert not backend.friend["visible"]


# --- Race results: selection reads debounced & one at a time, long race chart in background
def race_files(folder, count):
    for day in range(count):
        write_results(folder, {f"2026_08_{day + 1:02d}_19_10_00-12R1.xml":
                               RACE_XML.replace("1790000600", str(1780000000 + day * 86400))})


@pytest.fixture
def results_page(results_folder, english):  # noqa: F811
    from PySide6.QtCore import QEvent

    from neopedal.ui.quick.results_backend import RaceResultsBackend

    race_files(results_folder, 12)
    page = RaceResultsBackend()
    page.page_shown()
    assert wait_until(lambda: page.loaded_once)
    yield page
    page.release()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_held_arrow_keys_read_once(results_page, monkeypatch):
    from neopedal.ui.quick import results_backend

    page = results_page
    page.kept.clear()
    reads = []
    real = results_backend.read_session
    monkeypatch.setattr(results_backend, "read_session", lambda *args: reads.append(args[0]) or real(*args))
    for _ in range(8):  # Down held
        assert timed(lambda: page.moveSelection(1)) < UI_BUDGET
    target = page.selectedKey
    assert target == page.sessionModel.rows[8]["key"] and not reads
    assert wait_until(lambda: page.result is not None and page.result.path == target)
    assert reads == [target]


def test_superseded_read_kept(results_page):
    page = results_page
    page.kept.clear()
    rows = page.sessionModel.rows
    page.select(rows[3]["key"])
    page.start_read()  # read started at once
    page.select(rows[4]["key"])  # picked meanwhile
    assert wait_until(lambda: page.result is not None and page.result.path == rows[4]["key"])
    assert rows[3]["key"] in page.kept  # read passed by: shown at once if picked again
    page.select(rows[3]["key"])
    assert page.result.path == rows[3]["key"]


def test_long_race_chart_built_in_background(results_page, monkeypatch):
    from neopedal.ui.quick import results_backend
    from neopedal.ui.quick.lines import VertexStore

    page = results_page
    monkeypatch.setattr(results_backend, "SYNC_CHART_POINTS", 0)
    threads = []
    real = results_backend.positions_chart
    monkeypatch.setattr(results_backend, "positions_chart",
                        lambda *args: threads.append(threading.current_thread()) or real(*args))
    page.setChartView(400, 200, 1.5, 3, 4)
    page.refresh_chart()
    assert page.positions["series"] == []  # built meanwhile
    assert wait_until(lambda: bool(page.positions["series"]))
    assert threads and threading.main_thread() not in threads
    assert VertexStore.has(page.positions["series"][0]["thin"])
    page.setChartView(500, 200, 1.5, 3, 4)  # lines built again in background for new size
    serial = VertexStore.get(page.positions["series"][0]["thin"]).serial
    assert wait_until(lambda: VertexStore.get(page.positions["series"][0]["thin"]).serial != serial)


def test_events_merged_once_per_session(results_page, monkeypatch):
    from neopedal.ui.quick import results_backend

    page = results_page
    calls = []
    real = results_backend.merged_contacts
    monkeypatch.setattr(results_backend, "merged_contacts", lambda events: calls.append(1) or real(events))
    page._events = (None, [], [])
    page.refresh_events()
    page.setEventKind(1)
    page.setEventMine(True)
    assert len(calls) == 1 and page.eventCounts[0] == 5


def test_typing_search_only_filters_rows(results_page, monkeypatch):
    from neopedal.ui.quick import results_backend

    page = results_page
    built = []
    real = results_backend.session_row
    monkeypatch.setattr(results_backend, "session_row", lambda *args, **kwargs: built.append(1) or real(*args, **kwargs))
    for text in ("s", "sa", "sar", "sarthe", ""):
        page.setSearch(text)
    assert not built and page.shownCount == len(page.sessionModel.rows) > 1
