"""Audit i, lot E (lap viewer, lap cache, race calculator): lap CSV parsed in chunks into packed columns, cached
lap kept from the parse (no read back), cache columns lost treated as missing (never zeros), open & recent cache
files not pruned, large track folders & lap file moves in background, viewer settings merged in memory, histogram
weights in one pass, MoTeC channel longer than its file truncated, stop counter fuel threshold in liters, real
tyre changes for laps per set, pit menu next stop of a race under way, session recorder close without a 2 s join"""

import csv
import os
import threading
from array import array

import pytest

from neopedal.fuel_strategy import RaceState, StrategyInput, plan, remaining_input
from neopedal.userfile import lap_cache
from neopedal.userfile.telemetry_lap import (
    MAX_INFO_LENGTH,
    SCORING_COLUMNS,
    LapData,
    _chain,
    bounded_lines,
    lap_bounds,
    lap_stem,
    load_lap,
    open_lap_file,
    pack_columns,
    parse_columns,
    parse_info,
    smooth_distance,
    smooth_steps,
)
from tests.test_bug_audit_2026_10_29_lap_race import SimCar
from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_e2 import START, TRACK, lap_path, write_lap
from tests.test_lap_viewer_fix_backend import backend  # noqa: F401 (fixture)
from tests.test_motec_import import write_logger_ld
from tests.test_race_calculator import host, page, set_race  # noqa: F401 (fixtures)
from tests.test_replay_load import replay_view  # noqa: F401 (fixture)

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "lap_small_csv.txt")  # .csv files are git-ignored
GALLON = 3.785411784


# --- PERF-001: lap CSV parsed in chunks straight into packed arrays, same result as the whole-file parse
def old_load_lap(path: str) -> LapData:
    """Parse before the audit: every row kept as text, then float lists, then packed arrays"""
    with open_lap_file(path) as file:
        first = file.readline(MAX_INFO_LENGTH)
        info = parse_info(first)
        lines = bounded_lines(file) if info else _chain(first, bounded_lines(file))
        reader = csv.reader(lines)
        header = next(reader)
        width = len(header)
        rows = [row for row in reader if len(row) == width]
    columns: dict = dict(zip(header, parse_columns(rows, width)))
    start, end = lap_bounds(columns["distance"])
    if start > 0 or end < len(columns["distance"]):
        columns = {name: values[start:end] for name, values in columns.items()}
    times = columns.get("lap_time")
    if times:
        columns["distance"] = smooth_distance(times, columns["distance"])
        for name in SCORING_COLUMNS:
            if name in columns:
                columns[name] = smooth_steps(times, columns[name])
    return LapData(lap_stem(os.path.basename(path)), pack_columns(columns), info or None)


@pytest.mark.parametrize("chunk", [2000, 7, 1])
def test_chunked_parse_same_as_whole_parse(monkeypatch, chunk):
    from neopedal.userfile import telemetry_lap

    monkeypatch.setattr(telemetry_lap, "PARSE_CHUNK", chunk)
    expected = old_load_lap(FIXTURE)
    lap = load_lap(FIXTURE)
    assert lap.name == expected.name and lap.info == expected.info
    assert list(lap.columns) == list(expected.columns)
    for name, values in expected.columns.items():
        found = lap.columns[name]
        assert isinstance(found, array) and found.typecode == values.typecode, name
        assert found.tolist() == values.tolist(), name
    assert len(lap) == 23  # previous & next lap samples trimmed, bad & short rows left out
    assert lap.columns["rpm"].typecode == "f" and lap.columns["lap_time"].typecode == "d"
    assert lap.columns["path_lateral"][1] != lap.columns["path_lateral"][0]  # steps interpolated along time


# --- PERF-023: lap parsed & cached kept from the parse, not read back from the cache file just written
def test_cached_lap_not_read_back_after_save(tmp_path, monkeypatch):
    folder = str(tmp_path)
    write_lap(folder, 1, 90.0)
    path = os.path.join(folder, TRACK, os.listdir(os.path.join(folder, TRACK))[0])
    reads = []
    original = lap_cache.read_cached_lap
    monkeypatch.setattr(lap_cache, "read_cached_lap", lambda *args: reads.append(1) or original(*args))
    lap = lap_cache.load_cached_lap(folder, path)
    assert len(reads) == 1  # cache miss only
    assert isinstance(lap.columns, lap_cache.CachedColumns)
    assert "speed_kph" in lap.columns._loaded and "rpm" not in lap.columns._loaded  # eager kept, others released
    parsed = load_lap(path)
    assert lap.columns["rpm"].tolist() == parsed.columns["rpm"].tolist()  # lazy column read from the file written
    assert set(lap.columns) == set(parsed.columns) and lap.info == parsed.info
    again = lap_cache.load_cached_lap(folder, path)  # from the cache file: same entries
    assert again.columns["rpm"].tolist() == parsed.columns["rpm"].tolist()


# --- BUG-003: columns of a cached lap that cannot be read again are missing, never zeros
def test_lost_cache_columns_are_missing_not_zeros(tmp_path, monkeypatch):
    from PySide6.QtGui import QColor

    from neopedal.ui.lap_viewer import PlotLap
    from neopedal.ui.quick.trace_data import TraceData

    folder = str(tmp_path)
    write_lap(folder, 1, 90.0)
    path = os.path.join(folder, TRACK, os.listdir(os.path.join(folder, TRACK))[0])
    lap = lap_cache.load_cached_lap(folder, path)
    told = []
    lap_cache.set_unreadable_listener(lambda lap_path, reason: told.append((lap_path, reason)))
    try:
        os.remove(lap_cache.cache_file(folder, path))
        os.remove(path)  # lap file gone too: nothing to read the column from
        assert "rpm" in lap.columns
        with pytest.raises(KeyError):
            lap.columns["rpm"]
        assert "rpm" not in lap.columns and "rpm" not in list(lap.columns)
        assert lap.columns["speed_kph"].tolist()  # eager columns still there
        assert told and told[0][0] == path
        plot = PlotLap("k", "Lap 1", lap, QColor("red"), True)
        assert not TraceData.sources_available(["rpm"], plot)
    finally:
        lap_cache.set_unreadable_listener(None)


def test_lost_columns_told_in_page_status(backend):  # noqa: F811
    from PySide6.QtCore import QCoreApplication

    path = lap_path(backend, 1)
    backend._lap_cache[path] = None
    threading.Thread(target=lap_cache.columns_unreadable, args=(path, "gone")).start()  # from a reading thread
    for _ in range(50):
        QCoreApplication.processEvents()
        if "gone" in backend._status:
            break
    assert "could not be read again" in backend._status and path not in backend._lap_cache


# --- PERF-054: cache files of open laps & recently used ones never pruned
def test_prune_keeps_open_and_recent_cache_files(tmp_path):
    import time

    folder = tmp_path / lap_cache.CACHE_FOLDER
    folder.mkdir()
    files = {name: folder / f"{name}.bin" for name in ("old", "open", "recent")}
    for path in files.values():
        path.write_bytes(b"x" * 100)
    old = time.time() - 7200
    for name in ("old", "open"):
        os.utime(files[name], (old, old))
    removed = lap_cache.prune_cache(str(tmp_path), limit=0, keep=[str(files["open"])], recent=1800)
    assert removed == 1 and not files["old"].exists() and files["open"].exists() and files["recent"].exists()
    assert lap_cache.prune_cache(str(tmp_path), limit=0) == 2  # size limit alone: everything


# --- PERF-055: large track folder: file stamps read in a job, not on the page thread
def test_large_track_listed_in_background(backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import lap_library

    threads = []
    original = lap_library.indexed_infos
    monkeypatch.setattr(lap_library, "indexed_infos",
                        lambda *args: threads.append(threading.current_thread()) or original(*args))
    monkeypatch.setattr(lap_library, "LIST_BACKGROUND", 2)
    backend.load_track(TRACK)
    assert backend.reading_infos() and backend.is_loading()
    wait_loaded(backend)
    assert len(backend.entries) == 3 and threads and all(thread is not threading.main_thread() for thread in threads)
    write_lap(backend.folder.rstrip("/"), 4, 93.0, timestamp=START + 400)
    threads.clear()
    backend.auto_refresh()
    assert backend._infos_reading
    wait_loaded(backend)
    assert len(backend.entries) == 4 and threads and all(thread is not threading.main_thread() for thread in threads)


# --- PERF-002: many laps moved to trash or restored on a thread, page busy meanwhile, state applied once moved
def test_many_laps_deleted_and_restored_in_background(backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import lap_actions

    monkeypatch.setattr(lap_actions, "FILES_BACKGROUND", 0)
    paths = [lap_path(backend, 1), lap_path(backend, 2)]
    backend.checked = set(paths)
    backend.deleteLaps(paths)
    assert backend._file_actions == 1 and backend.is_loading()
    wait_loaded(backend)
    assert backend._file_actions == 0
    assert not any(os.path.exists(path) for path in paths) and len(backend.entries) == 1
    assert len(backend._undo) == 1 and len(backend._undo[0]) == 2 and backend.undoText
    backend.undoDelete()
    assert backend._file_actions == 1
    wait_loaded(backend)
    assert all(os.path.exists(path) for path in paths) and len(backend.entries) == 3
    assert set(paths) <= backend.checked and not backend._undo


# --- PERF-022: viewer settings kept in memory by the page, file written once a moment after the last change
def test_viewer_settings_merged_in_memory(backend, monkeypatch):  # noqa: F811
    from neopedal.ui import lap_viewer
    from neopedal.ui.lap_viewer import load_viewer_setting, read_viewer_setting, save_viewer_setting

    writes = []
    original = lap_viewer.write_viewer_setting
    monkeypatch.setattr(lap_viewer, "write_viewer_setting", lambda folder, text: writes.append(1) or original(folder, text))
    backend._settings.flush(wait=True)
    writes.clear()
    for level in (1, 2, 3):
        save_viewer_setting(backend.folder, smoothing=level)
    save_viewer_setting(backend.folder.rstrip("/"), envelope=True)  # same folder spelled otherwise
    assert load_viewer_setting(backend.folder) == {**load_viewer_setting(backend.folder), "smoothing": 3, "envelope": True}
    assert read_viewer_setting(backend.folder).get("smoothing") != 3 and not writes  # not written yet
    backend._settings.flush(wait=True)
    assert len(writes) == 1 and read_viewer_setting(backend.folder)["smoothing"] == 3
    assert read_viewer_setting(backend.folder)["envelope"] is True
    save_viewer_setting(backend.folder, smoothing=0)
    backend.release()  # page closed: pending change written now
    assert read_viewer_setting(backend.folder)["smoothing"] == 0
    save_viewer_setting(backend.folder, smoothing=2)  # no page: written at once
    assert read_viewer_setting(backend.folder)["smoothing"] == 2


# --- PERF-056: histogram time weights in one pass, kept while the same part is shown
def test_histogram_weights_one_pass_and_cached(backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import lap_xy
    from neopedal.ui.quick.lap_xy import time_weights
    from neopedal.userfile.telemetry_lap import interpolate

    backend.checked = {entry.file.path for entry in backend.entries}
    backend.load_laps()
    wait_loaded(backend)
    backend.wait_jobs()
    assert len(backend.data.laps) == 3
    for lap in backend.data.laps:
        distances, _ = backend.xy_samples("throttle", lap)
        own, times = backend.data.lap_times(lap)
        scale = backend.data.scale_of(lap)
        expected = time_weights([interpolate(own, times, distance / scale) for distance in distances])
        assert backend.xy_weights("throttle", lap, distances) == pytest.approx(expected, abs=1e-9)
    shown = backend.histogram("throttle")
    assert len(shown["laps"]) == 3
    monkeypatch.setattr(lap_xy, "resample_sorted", lambda *args: pytest.fail("weights computed again"))
    assert backend.histogram("throttle") == shown


# --- PERF-057: session recorder page closed: no 2 s join of the replay loading thread
def test_recorder_close_does_not_wait_seconds(replay_view, monkeypatch):  # noqa: F811
    waits = []
    monkeypatch.setattr(replay_view.backend.loader, "wait", lambda timeout=None: waits.append(timeout) or True)
    replay_view.backend.release_resources()
    assert waits and all(timeout is not None and timeout <= 0.2 for timeout in waits)


# --- BUG-023: MoTeC channel declaring more samples than the file holds: the part there is read
def test_motec_channel_cut_short_is_read(tmp_path):
    from neopedal.userfile.motec_ld import read_ld

    filename = str(tmp_path / "cut.ld")
    write_logger_ld(filename, [("Ground Speed", "km/h", 10, [100.0] * 50, 641, 2, 2)])
    with open(filename, "r+b") as file:
        file.truncate(os.path.getsize(filename) - 20)  # logger stopped short: last 10 samples missing
    _, channels = read_ld(filename)
    assert [channel.name for channel in channels] == ["Ground Speed"] and len(channels[0].values) == 40
    _, bounded = read_ld(filename, max_seconds=1.0)
    assert len(bounded[0].values) == 11


# --- BUG-022: refuel seen from the same amount whatever the display unit (threshold in liters)
def test_refuel_threshold_in_liters(ui_env, monkeypatch):
    from neopedal.race_live import read_race_state

    car = SimCar(monkeypatch)
    gallons = read_race_state(lambda liters: liters / GALLON, car.counter)
    assert gallons.state is not None and gallons.state.fuel == pytest.approx(30.0 / GALLON)
    car.in_pits, car.speed, car.progress = True, 20.0, 0.98  # rolling through the box: no standing still
    car.tick()
    car.fuel += 1.0  # splash of 1 L (0.26 gallon)
    read_race_state(lambda liters: liters / GALLON, car.counter)
    car.in_pits, car.speed, car.laps, car.progress = False, 60.0, 11, 0.05
    car.clock += 0.5
    state = read_race_state(lambda liters: liters / GALLON, car.counter).state
    assert state is not None and state.stops_done == 1 and state.last_stop_lap == 11
    assert state.tyre_stop_laps == ()  # every stop seen, tyres kept


# --- BUG-041: laps on the tyres of now from the stops seen changing tyres, not from the plan
def test_tyre_changes_seen_used_for_laps_per_set(ui_env, monkeypatch):
    from neopedal.api_control import api

    car = SimCar(monkeypatch)
    car.wear = (0.8, 0.8, 0.8, 0.8)
    monkeypatch.setattr(api.read.tyre, "wear", lambda *args, **kwargs: car.wear)
    car.tick()
    car.in_pits, car.speed, car.progress = True, 20.0, 0.98
    car.tick()
    car.wear = (1.0, 1.0, 1.0, 1.0)  # new tyres
    car.tick()
    car.in_pits, car.speed, car.laps, car.progress = False, 60.0, 11, 0.05
    state = car.tick().state
    assert state is not None and state.stops_done == 1 and state.tyre_stop_laps == (11,)
    assert car.counter.stops[-1].tyres
    car.in_pits, car.speed, car.progress = True, 20.0, 0.98  # second stop: fuel only
    car.tick()
    car.fuel += 20.0
    car.tick()
    car.in_pits, car.speed, car.laps, car.progress = False, 60.0, 12, 0.05
    state = car.tick().state
    assert state.stops_done == 2 and state.tyre_stop_laps == (11,) and not car.counter.stops[-1].tyres

    setup = StrategyInput(laptime=100, race_laps=45, tank_capacity=50, fuel_per_lap=3, pit_seconds=30,
                          wear_per_lap=4.0, minimum_tread=20.0)
    base = plan(setup)
    assert base.stops and base.stops[0].tyres and base.stops[0].lap != 25
    state = RaceState(30, 0.0, 3000.0, 0.0, 40.0, 0.0, 60.0, 1)  # tyre changes unknown: plan
    assert remaining_input(setup, base, state).tyre_laps_done == 30 - base.stops[0].lap
    assert remaining_input(setup, base, state._replace(tyre_stop_laps=(25,))).tyre_laps_done == 5
    assert remaining_input(setup, base, state._replace(tyre_stop_laps=())).tyre_laps_done == 30  # tyres of start
    assert remaining_input(replace_formation(setup), base, state._replace(tyre_stop_laps=(25,))).tyre_laps_done == 5


def replace_formation(setup: StrategyInput) -> StrategyInput:
    from dataclasses import replace

    return replace(setup, formation_laps=1.0)


# --- BUG-004: pit menu set for the next stop of a race under way, even with the live plan off
def test_pit_menu_next_stop_of_race_under_way(page, host, monkeypatch):  # noqa: F811
    from neopedal.api_control import api
    from neopedal.const_api import API_LMU_NAME

    calc = page.backend
    set_race(calc, laptime=90.0, tank=50.0, fuel=3.0, laps=45)
    stops = calc.strategy.stops
    assert len(stops) >= 2 and calc.race_state is None
    calc._race_running = True
    monkeypatch.setattr(api.read.lap, "completed_laps", lambda *args: stops[0].lap + 1)
    assert calc.next_plan_stop() is stops[1]
    calls = []
    monkeypatch.setattr(calc.jobs, "run", lambda name, work, *args, **kwargs: calls.append(work))
    calc.setGamePitMenu()
    assert calls and calls[0].args[0] == pytest.approx(stops[1].fuel_after)
    monkeypatch.setattr(api.read.lap, "completed_laps", lambda *args: stops[-1].lap + 1)
    calc.setGamePitMenu()
    assert len(calls) == 1 and host.toasts and "Every stop of the plan is done" in host.toasts[-1]
    calc._race_running = False  # no race under way: first stop of the plan
    assert calc.next_plan_stop() is stops[0]
    # Button enabled in an LMU session only
    assert calc.pitMenuAvailable is False
    monkeypatch.setattr(type(api), "name", property(lambda self: API_LMU_NAME))
    monkeypatch.setattr(api.read.state, "active", lambda: True)
    calc.update_pit_menu_available()
    assert calc.pitMenuAvailable is True
