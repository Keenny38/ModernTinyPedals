"""Audit 2026-10-30, lot F: race results files, replays, driver stats, Broadcast Director & table editors

Results files parsed as read (never held whole unless damaged), game profile names cached, parse cache released
per page, driver race histories derived from the results index & kept when the Director closes, slot history
dropped with the car that left, stats table without disk access, branding folder listed on a worker, track map
asked again after a missed answer, row names required & stripped, record times bounded, championship points finite.
"""

import math
import os
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.process import championship as champ
from neopedal.process import director as dr
from neopedal.process import driver_history as dh
from neopedal.process import results_file as rf
from neopedal.process import results_index as ri
from neopedal.setting import cfg
from neopedal.userfile.driver_history import SessionRecord, parse_record
from tests.test_broadcast_director import TRACK, car, director_page, field  # noqa: F401
from tests.test_driver_stats_viewer import OREGA, SPA, backend, dialogs, window  # noqa: F401
from tests.test_game_info import GAME_ANSWERS, answered, replays_page  # noqa: F401
from tests.test_res_data_memory import results_xml
from tests.test_ui_editors import compound_editor, editor_env, set_cell  # noqa: F401

RACE_NAME = "2026_10_05_22_34_33-70R1.xml"


def wait_until(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def entry(name, cls, place, status, finish_time, swaps=()):
    return rf.Entry(name, "Team", "Car", "Car", cls, "1", 1, place, 1, place, 10, 90.0, finish_time, 1, status, "",
                    True, False, "", (), tuple(rf.Swap(driver, 1, 5) for driver in swaps))


# --- PERF-042: results file parsed as read, content held whole only when damaged
def test_results_file_parsed_as_read(tmp_path, monkeypatch):
    path = str(tmp_path / RACE_NAME)
    data = results_xml()
    with open(path, "wb") as file:
        file.write(data)
    whole = []
    real = rf._parse_bytes
    monkeypatch.setattr(rf, "_parse_bytes", lambda *args: whole.append(1) or real(*args))
    result = rf.read_results(path, ("ann",), keep=False)
    assert not whole  # DOCTYPE & invalid characters handled chunk by chunk
    assert result == rf.parse_results(data, path, ("ann",))
    assert len(whole) == 1  # content given: parsed as before


def test_damaged_results_file_read_whole_and_repaired(tmp_path, monkeypatch):
    path = str(tmp_path / RACE_NAME)
    with open(path, "wb") as file:
        file.write(results_xml().replace(b"<Name>Bob</Name>", b"<Name>Bob\xe9</Name>"))  # Windows-1252 byte
    whole = []
    real = rf._parse_bytes
    monkeypatch.setattr(rf, "_parse_bytes", lambda *args: whole.append(1) or real(*args))
    result = rf.read_results(path, keep=False)
    assert len(whole) == 1 and any(found.name == "Bobé" for found in result.entries)
    with open(path, "wb") as file:  # root end tag far from the end: found by the whole read
        file.write(results_xml() + b" " * (rf.TAIL_BYTES + 100))
    assert rf.read_results(path, keep=False).entries and len(whole) == 2
    with open(path, "wb") as file:  # game still writing
        file.write(results_xml()[:500])
    with pytest.raises(ValueError):
        rf.read_results(path, keep=False)


# --- PERF-044: game profile names read once while the profile file is unchanged
def test_profile_names_cached_by_file_stamp(tmp_path, monkeypatch):
    rf.forget_lookups()
    results = tmp_path / "UserData" / "Log" / "Results"
    profile = tmp_path / "UserData" / "player"
    results.mkdir(parents=True)
    profile.mkdir(parents=True)
    settings = profile / "Settings.JSON"
    settings.write_text('{"DRIVER": {"Player Name": "Alice", "Player Nick": "Al"}}', encoding="utf-8")
    old = time.time() - 60
    os.utime(settings, (old, old))  # settled: kept
    opened = []
    real_open = open

    def counting_open(*args, **kwargs):
        opened.append(args[0])
        return real_open(*args, **kwargs)

    monkeypatch.setattr(rf, "open", counting_open, raising=False)
    assert rf.profile_player_names(str(results)) == ["Alice", "Al"]
    assert rf.profile_player_names(str(results)) == ["Alice", "Al"]
    assert len(opened) == 1
    settings.write_text('{"DRIVER": {"Player Name": "Bob"}}', encoding="utf-8")
    os.utime(settings, (old + 1, old + 1))  # changed: read again
    assert rf.profile_player_names(str(results)) == ["Bob"] and len(opened) == 2
    rf.forget_lookups()
    assert rf.profile_player_names(str(results)) == ["Bob"] and len(opened) == 3


# --- PERF-046: parse cache released for the files of one page only
def test_forget_results_of_paths_only(tmp_path, monkeypatch):
    rf.forget_results()
    first, second = str(tmp_path / RACE_NAME), str(tmp_path / "2026_10_06_22_34_33-70R1.xml")
    for path in (first, second):
        with open(path, "wb") as file:
            file.write(results_xml())
    rf.read_results(first)
    rf.read_results(second)
    parsed = []
    real = rf._parse_raw
    monkeypatch.setattr(rf, "_parse_raw", lambda *args: parsed.append(1) or real(*args))
    rf.forget_results([first])
    rf.read_results(second)
    assert not parsed  # kept for other readers
    rf.read_results(first)
    assert len(parsed) == 1
    rf.forget_results()
    rf.read_results(second)
    assert len(parsed) == 2


# --- PERF-006 & BUG-034: driver histories from the results index, kept when the Director closes
def test_driver_history_reuses_results_index_files(tmp_path, monkeypatch):
    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {})
    path = str(tmp_path / RACE_NAME)
    with open(path, "wb") as file:
        file.write(results_xml())
    ri.hold_files()
    try:
        ri.scan_results([str(tmp_path)])
        kept = ri.kept_file(path)
        assert kept is not None and kept.cars and [found.drivers for found in kept.cars] == [("Ann",), ("Bob",), ("Ann",)]

        def never(*args, **kwargs):
            raise AssertionError("file parsed again")

        monkeypatch.setattr(rf, "read_results", never)
        history = dh.DriverHistory()
        assert history.scan([str(tmp_path)])
        stats = history.stats("Ann")
        assert stats is not None and stats.starts == 1 and stats.last[0].class_cars == 3
        assert not history.scan([str(tmp_path)])  # unchanged
    finally:
        ri.release_files()


def test_race_cars_finished_by_game_status():
    def result(*entries):
        return rf.SessionResult("x.xml", "LMU", "", "", 1.0, "Race", "Race", "Spa", "Spa", "", 4000.0, "", 60, 0, 10,
                                tuple(entries), ())

    cars = ri.race_cars(result(entry("Ann", "GT3", 1, rf.FINISHED, 0.0, swaps=("Dee",)),
                               entry("Bob", "GT3", 2, "DNF", 0.0), entry("Cid", "GT3", 3, "None", 100.0)))
    assert cars is not None
    assert [(found.drivers, found.finished) for found in cars] == [(("Ann", "Dee"), True), (("Bob",), False),
                                                                   (("Cid",), True)]
    assert ri.race_cars(result()._replace(kind="Qualifying")) is None
    records = dh.race_records("x.xml", 1.0, "Spa", cars)
    assert records["dee"].finished and records["dee"].class_cars == 3 and not records["bob"].finished


def test_director_close_keeps_drivers_history(director_page, monkeypatch, tmp_path):  # noqa: F811
    path = str(tmp_path / RACE_NAME)
    with open(path, "wb") as file:
        file.write(b"x")
    monkeypatch.setattr(rf, "results_files", lambda folder: [path])
    monkeypatch.setattr(dh.history, "read", lambda found: {"ann": dh.RaceRecord(found, 1.0, "Spa", "GT3", 1, True, 3)})
    try:
        assert dh.history.scan([str(tmp_path)])
        director_page.backend.release()
        assert len(dh.history.records("ann")) == 1  # tables kept: files unchanged not read again once opened
        assert not dh.history.scan([str(tmp_path)])
    finally:
        dh.history.clear()


# --- BUG-009: history of a car that left dropped with its state
def test_slot_history_dropped_when_car_leaves():
    watcher = dr.RaceWatcher()
    watcher.update(field(car(1, 1, laps=10), car(2, 2, distance=500.0)), (), 100.0, "RACE1", TRACK)
    watcher.update(field(car(1, 1, laps=11, last=95.0, in_pit=True), car(2, 2, distance=500.0)), (), 101.0, "RACE1",
                   TRACK)
    assert len(watcher.laps[1]) == 1 and watcher.pit_stops[1] and 1 in watcher.sector_best
    watcher.update(field(car(2, 1, distance=500.0)), (), 102.0, "RACE1", TRACK)  # car 1 left
    assert 1 not in watcher.cars and 1 not in watcher.laps and 1 not in watcher.pit_stops and 1 not in watcher.sector_best
    watcher.update(field(car(2, 1, distance=500.0), car(1, 2, laps=3, driver="New Driver")), (), 103.0, "RACE1", TRACK)
    watcher.update(field(car(2, 1, distance=500.0), car(1, 2, laps=4, driver="New Driver", last=99.0)), (), 104.0,
                   "RACE1", TRACK)
    assert [record.lap for record in watcher.laps[1]] == [4]  # nothing of the former car
    assert 1 not in watcher.pit_stops


# --- BUG-032: track map asked again after a missed answer
def test_replays_map_asked_again_after_missed_answer(replays_page):  # noqa: F811
    from neopedal.ui.quick.replays_common import MAP_TRIES

    replays = replays_page.backend
    replays.setPanel(2)
    answered(replays_page, {**GAME_ANSWERS, "/rest/watch/trackmap": None})
    assert replays.map_track is None and not replays.map_center
    asked = replays_page.game.asked
    asked.clear()
    answered(replays_page, GAME_ANSWERS)  # asked again: map shown
    assert "/rest/watch/trackmap" in asked and replays.map_track and replays.map_center
    replays.map_track = None
    for _ in range(MAP_TRIES):  # game has no map of this track: given up, not asked every answer
        answered(replays_page, {**GAME_ANSWERS, "/rest/watch/trackmap": None})
    assert replays.map_track and not replays.map_center
    asked.clear()
    answered(replays_page, GAME_ANSWERS)
    assert "/rest/watch/trackmap" not in asked


# --- BUG-033: row names required, stripped, duplicates told whatever the spaces
def test_editor_row_name_required_and_stripped(compound_editor, editor_env):  # noqa: F811
    editor = compound_editor.backend
    assert not set_cell(compound_editor, 0, 0, "")
    assert not set_cell(compound_editor, 0, 0, "   ")
    assert editor.rows[0][0] == "Soft"
    assert set_cell(compound_editor, 0, 0, " Hard ")
    assert editor.rows[0][0] == "Hard"
    editor.append_rows([editor.new_row("Hard ")])
    assert not editor.verify() and "listed more than once" in editor_env.warnings[-1]
    editor.rows[-1][0] = ""
    assert not editor.verify() and "no name" in editor_env.warnings[-1]
    editor.rows[-1][0] = "Medium"
    assert editor.verify()


# --- BUG-035: championship points never NaN nor infinite
def test_championship_points_finite(ui_env):
    from neopedal.ui.quick import director_shared as ds

    assert champ.points_text(float("nan")) == "-" and champ.points_text(float("inf")) == "-"
    assert champ.points_text(12.0) == "12" and champ.points_text(12.5) == "12.5"
    with open(ds.championship_path(), "w", encoding="utf-8") as file:
        file.write('[{"name": "Cup", "rows": [["A", NaN, "", "", ""], ["B", 5, "", "", ""], ["C", Infinity, "", "", ""]]}]')
    loaded = ds.load_championships()
    assert [row.name for row in loaded[0]["rows"]] == ["B"] and math.isfinite(loaded[0]["rows"][0].points)


# --- BUG-007: record times bounded, dates of records never raise
def test_record_time_bounded_and_days_tolerant():
    from neopedal.ui.quick.stats_analysis import history_years, record_day

    assert parse_record({"time": 1.7e12, "track": "Spa", "vehicle": "X"}) is None  # milliseconds
    assert parse_record({"time": 1.7e9, "track": "Spa", "vehicle": "X"}) is not None
    bad = SessionRecord(1e18, "Spa", "X", 1, 100.0)
    good = SessionRecord(1.7e9, "Spa", "X", 1, 100.0)
    assert record_day(bad) is None and record_day(good) is not None
    assert history_years([bad, good]) == [record_day(good).year]


def test_activity_skips_record_with_time_out_of_range(backend):  # noqa: F811
    backend.history = [SessionRecord(1e18, SPA, OREGA, 1, 100.0, seconds=600.0),
                       SessionRecord(time.time(), SPA, OREGA, 1, 100.0, seconds=600.0)]
    activity = backend.activity_data()
    assert activity and sum(day["level"] > 0 for day in activity["days"]) == 1


# --- PERF-043: stats table without disk access (files listed by the reload job)
def test_stats_table_uses_files_listed_by_reload(backend):  # noqa: F811
    from neopedal.userfile.sector_best import save_sector_best_file

    name = f"{SPA} - LMP2_ELMS"
    save_sector_best_file(cfg.path.sector_best, name, (0, 0, 0), [40.0] * 3, [40.0] * 3, [40.0, 40.2, 40.3],
                          [40.1, 40.5, 40.9])
    backend.reload_stats()
    assert name in backend._sector_times and backend.theory_of(SPA, OREGA) == pytest.approx(120.5)
    backend._sector_times = {}  # not listed: file on disk never looked at row by row
    backend._theory_cache.clear()
    assert backend.theory_of(SPA, OREGA) == 0.0
    folder = os.path.join(cfg.path.telemetry, name)
    assert backend.lap_folder_of(SPA, OREGA) == ""
    os.makedirs(folder)
    assert backend.lap_folder_of(SPA, OREGA) == name  # telemetry folder changed: listed once again
    stamp, folders = backend._lap_folders
    assert name in folders
    backend._lap_folders = (stamp, {})  # listing says none: no check per vehicle
    assert backend.lap_folder_of(SPA, OREGA) == ""


# --- PERF-045: branding folder listed on a worker thread, at once on user actions
def test_branding_listed_off_the_ui_thread(director_page, monkeypatch, tmp_path):  # noqa: F811
    from neopedal import stream_director as sd

    graphics = director_page.backend.graphics
    threads = []
    real = sd.brand_pictures
    monkeypatch.setattr(sd, "brand_pictures", lambda: threads.append(threading.current_thread()) or real())
    graphics._brand = (0.0, ("", []))
    state = graphics.brand_state()
    assert state["logo"] == "" and not threads  # listed in background: last pictures shown meanwhile
    assert wait_until(lambda: not director_page.backend.jobs.is_busy("brand"))
    assert threads and threads[0] is not threading.main_thread()
    picture = tmp_path / "league.png"
    picture.write_bytes(b"\x89PNG fake")
    assert graphics.set_logo(str(picture))
    assert threads[-1] is threading.main_thread()  # folder changed here: listed at once
    assert graphics.brand_state()["logo"].startswith("/api/director/brand/logo.png")
