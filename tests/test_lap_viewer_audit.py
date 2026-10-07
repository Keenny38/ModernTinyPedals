"""Lap viewer, track map & driver stats audit fixes: lap ends in delta & mini-sectors, damaged files, laps without
lap time, markers on time axis, session tab, other circuit, plain data caches, background MoTeC import, vertices,
units & decimals, QML warnings"""

import gc
import gzip
import os
import pickle
import struct
import time
from array import array
from itertools import pairwise

import pytest
from PySide6.QtCore import Q_ARG, QCoreApplication, QEvent, QMetaObject, qInstallMessageHandler

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_features import BASE, TRACK, lap_rows, laps, save, viewer  # noqa: F401
from tinypedal.module import module_recorder
from tinypedal.setting import cfg
from tinypedal.userfile.telemetry_lap import LapData

LENGTH = 1000.0
_UNPICKLED: list[bool] = []


def _unpickled():
    """Called if a pickled cache file were loaded (it never is)"""
    _UNPICKLED.append(True)
    return {}


class Payload:
    def __reduce__(self):
        return _unpickled, ()


def lap_name(number: int, lap_time: float) -> str:
    minutes, seconds = divmod(lap_time, 60)
    return f"2026-10-03 17-34-45 lap{number:03d} {int(minutes)}m{seconds:06.3f}s"


def game_lap(number: int, lap_time: float, first: float = 0.15, stale: float = 0.2, late: float = 0.0,
             start_distance: float | None = None, track: str = "Road Atlanta", length: float = LENGTH) -> LapData:
    """Lap at constant speed sampled like the game: first sample after the line, distance not updated in the
    last `stale` seconds, a distance update measured before the line arriving `late` seconds past lap time"""
    speed = length / lap_time
    times, distances = [], []
    if start_distance is not None:  # game distance still a bit before the line just after lap start
        times.append(0.01)
        distances.append(start_distance)
    elapsed = first
    while elapsed <= lap_time + 1e-9:
        times.append(round(elapsed, 3))
        distances.append(speed * min(elapsed, lap_time - stale))
        elapsed += 0.01
    if late:
        times.append(lap_time + late)
        distances.append(length - 3.0)
    columns = {"lap_time": times, "distance": distances, "speed_kph": [speed * 3.6] * len(times)}
    info = {"kind": "lap", "combo": f"{track} - Hyper", "track": track, "track_length": length}
    return LapData(lap_name(number, lap_time), columns, info)


def wait_events(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def flush_deleted():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- 1. Delta, mini-sectors & ideal lap from line to line
def test_lap_time_curve_from_line_to_line():
    from tinypedal.userfile.telemetry_lap import lap_time_curve

    distances, times = lap_time_curve(game_lap(1, 20.0))
    assert (distances[0], times[0]) == (0.0, 0.0)  # lap start added (first sample 0.15 s after the line)
    assert (distances[-1], times[-1]) == (LENGTH, 20.0)  # lap end: track length at official lap time
    assert all(second > first for first, second in pairwise(distances))
    # Distance before the line at lap start & update arriving past lap time left out
    distances, times = lap_time_curve(game_lap(2, 25.0, late=0.05, start_distance=-0.5))
    assert (distances[0], times[0]) == (0.0, 0.0) and (distances[-1], times[-1]) == (LENGTH, 25.0)
    assert all(second > first for first, second in pairwise(times))
    # Lap cut short (far from the line): no lap end added
    assert lap_time_curve(game_lap(3, 20.0, stale=3.0))[0][-1] < LENGTH - 100
    assert lap_time_curve(LapData("x", {"distance": [0.0, 1.0]})) == ([], [])


def test_delta_at_line_is_lap_time_gap():
    from tinypedal.userfile.telemetry_lap import compute_delta, sector_times

    reference, compared = game_lap(1, 20.0, first=0.2), game_lap(2, 21.5, first=0.05, late=0.03)
    delta = compute_delta(reference, compared)
    assert delta[0] == (0.0, 0.0)
    assert delta[-1][0] == LENGTH and delta[-1][1] == pytest.approx(1.5, abs=1e-9)  # was up to 0.19 s off
    lap = game_lap(1, 20.0)
    sectors = [0.0 if distance < 300 else 1.0 if distance < 600 else 2.0 for distance in lap.distance]
    times = sector_times(LapData(lap.name, {**lap.columns, "sector": sectors}, lap.info))
    assert sum(times) == pytest.approx(20.0) and times[0] == pytest.approx(6.0, abs=0.02)


def test_mini_sectors_add_up_to_lap_time(ui_env):
    from tinypedal.ui.lap_viewer import PlotLap, lap_color
    from tinypedal.ui.quick.trace_data import TraceData
    from tinypedal.userfile.telemetry_lap import official_lap_time

    timed = [game_lap(1, 20.0, first=0.2), game_lap(2, 20.4, first=0.02, late=0.04), game_lap(3, 20.2, stale=0.1)]
    data = TraceData()
    data.set_laps([PlotLap(lap.name, lap.name, lap, lap_color(index)) for index, lap in enumerate(timed)],
                  timed[0].name)
    mini = data.mini_sectors()
    assert mini["bounds"][0] == 0.0 and mini["bounds"][-1] == LENGTH  # track length, not last sample distance
    for lap, times in zip(timed, mini["times"]):
        assert sum(times) == pytest.approx(official_lap_time(lap), abs=1e-6)  # was up to 0.37 s short
    assert mini["ideal"] == pytest.approx(20.0, abs=1e-6)  # constant speed: fastest lap wins everywhere
    assert data.max_x() == LENGTH
    data.set_time_axis(True)
    assert data.max_x() == pytest.approx(20.4) and data.x_at_distance(0.0) == 0.0


# --- 2. Damaged compressed lap file
def damaged_lap(folder: str, name: str) -> str:
    rows = "".join(f"{index * 0.01:.3f},{index * 0.01:.3f},{index * 0.5:.2f}\n" for index in range(3000))
    data = bytearray(gzip.compress(("time,lap_time,distance\n" + rows).encode()))
    data[20:28] = b"\xff" * 8  # deflate stream broken: zlib.error, not OSError
    path = os.path.join(folder, name)
    with open(path, "wb") as file:
        file.write(bytes(data))
    return path


def test_damaged_gzip_lap_read_as_unreadable(tmp_path):
    from tinypedal.userfile.telemetry_lap import load_lap, read_lap_info

    path = damaged_lap(str(tmp_path), "lap.csv.gz")
    assert read_lap_info(path) == {}
    with pytest.raises(ValueError):
        load_lap(path)


def test_damaged_lap_flagged_once_not_loaded_again(viewer, laps):  # noqa: F811
    backend = viewer.backend
    name = "2026-10-03 14-08-20 lap005 1m10.000s.csv.gz"
    damaged_lap(os.path.dirname(laps[0]), name)
    backend.refresh()
    wait_loaded(viewer)
    path = next(entry.file.path for entry in backend.entries if entry.file.filename == name)
    starts = []
    original = backend.load_in_background
    backend.load_in_background = lambda paths: (starts.append(paths), original(paths))[1]
    backend.setLapChecked(path, True)
    wait_loaded(viewer)
    wait_events(0.2)  # loader thread & its timer stay stopped (was 33 loads per second)
    assert backend._loader is None and not backend._load_timer.isActive() and len(starts) <= 1
    row = next(row for row in backend.lap_rows() if row["path"] == path)
    assert row["error"] and path in backend._failed


def test_track_limits_not_cached_with_unreadable_lap(ui_env, tmp_path):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick.lap_backend import LapViewerBackend
    from tinypedal.userfile.lap_geometry import track_limits_job

    folder = cfg.path.telemetry.rstrip("/")
    paths = [save(number, 70.0 + number, BASE + number * 100) for number in (2, 3, 4)]
    broken = damaged_lap(os.path.dirname(paths[0]), "2026-10-03 14-00-00 lap001 1m09.000s.csv.gz")
    result = track_limits_job(folder, str(tmp_path / "parts"), os.path.dirname(paths[0]), [broken, *paths], None,
                              "lap")
    assert result["unreadable"] == [os.path.basename(broken)]
    assert result["limits"] is not None  # best readable lap used as base
    parent = QWidget()
    backend = LapViewerBackend(parent, cfg.path.telemetry)
    try:
        backend.refresh()
        wait_loaded(backend)
        end = time.monotonic() + 60
        while backend._limits_job is not None and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert backend._limits_job is None and backend._limits is not None
        assert not os.path.exists(backend.limits_cache_path(TRACK))  # failed: computed again next time
    finally:
        backend.release()
        parent.deleteLater()


# --- 3. Lap file without lap time
def test_lap_without_lap_time_never_breaks_charts(viewer, tmp_path):  # noqa: F811
    from tinypedal.userfile.telemetry_lap import compute_delta, load_lap, sector_times

    path = tmp_path / "other" / "no time.csv"
    path.parent.mkdir()
    path.write_text("distance,speed_kph,sector\n" + "".join(
        f"{meter},{150 + meter % 50},{0 if meter < 600 else 1 if meter < 1300 else 2}\n"
        for meter in range(0, 2001, 5)), encoding="utf-8")
    lap = load_lap(str(path))
    backend = viewer.backend
    reference = backend.data.reference.data
    assert compute_delta(reference, lap) == [] and compute_delta(lap, reference) == [] and sector_times(lap) == []
    backend.add_external([str(path)])
    wait_loaded(viewer)
    assert len(backend.legend) == 3
    backend.setIdealDelta(True)
    backend.setTimeAxis(True)
    assert backend.cursorValues(5.0) and backend.maxX > 0
    no_time = next(index for index, lap in enumerate(backend.data.laps) if "lap_time" not in lap.data.columns)
    mini = backend.data.mini_sectors()
    assert mini["times"][no_time] == [] and no_time not in mini["winners"]
    backend.setTimeAxis(False)
    backend.setIdealDelta(False)


# --- 4. Markers & zoom history kept as reference distances
def chart_item(view):
    stack = [view.rootObject()]
    while stack:
        item = stack.pop()
        if item.property("labelWidth") is not None:
            return item
        stack.extend(item.childItems())
    return None


def test_markers_and_zoom_history_follow_time_axis(viewer):  # noqa: F811
    backend = viewer.backend
    chart = chart_item(viewer.view)

    def call(name, *args):
        QMetaObject.invokeMethod(chart, name, *(Q_ARG("QVariant", arg) for arg in args))

    call("setMarker", "A", 1200.0)
    call("setMarker", "B", 1500.0)
    assert chart.property("hasRange") and chart.property("markerA") == pytest.approx(1200.0)
    call("setView", 500.0, 1000.0, False)
    wait_events(0.85)  # zoom kept in history
    backend.setTimeAxis(True)
    QCoreApplication.processEvents()
    assert chart.property("markerA") == pytest.approx(backend.xAtDistance(1200.0))
    assert chart.property("markerB") < chart.property("maxX")  # seconds now, never meters read as seconds
    assert backend._map_range == pytest.approx((1200.0, 1500.0), abs=0.5)  # same track part on map
    call("resetView", False)
    wait_events(0.85)
    call("stepHistory", -1)
    assert chart.property("targetStart") == pytest.approx(backend.xAtDistance(500.0), abs=0.05)
    backend.setTimeAxis(False)
    QCoreApplication.processEvents()
    assert chart.property("markerA") == pytest.approx(1200.0, abs=0.5)


# --- 5. Session tab values read when shown
def test_session_values_read_for_session_chosen_while_busy(ui_env, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.ui.lap_viewer import LapViewer, save_viewer_setting

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    folder = cfg.path.telemetry.rstrip("/")
    for number, start in ((1, BASE), (2, BASE), (1, BASE + 7200), (2, BASE + 7200)):
        info = {"kind": "lap", "session": "Practice", "session_start": start}
        module_recorder.save_lap(f"{folder}/", TRACK, number, 70.0 + number, lap_rows(70.0 + number),
                                 max_saved_laps=99, info=info, timestamp=start + number * 100)
    save_viewer_setting(folder, side_tab=4)  # page opened on session tab
    page = LapViewer(None)
    backend = page.backend
    try:
        assert backend._session_busy and backend.sessionData["busy"]  # read at once, busy indicator shown
        other = next(item["key"] for item in backend.sessions if item["key"] != backend.sessionKey)
        backend.setSession(other)  # chosen while first session is read: read once that job is done
        backend.wait_jobs()
        wait_loaded(page)
        backend.wait_jobs()
        assert not backend._session_busy
        paths = [entry.file.path for entry in backend.entries]
        assert len(paths) == 4 and all(path in backend._session_extra for path in paths)
    finally:
        page.close()
        flush_deleted()


# --- 8. Laps of another circuit (opened alone: viewer switches to it, never compared with laps of shown track)
def test_other_circuit_lap_never_compared(ui_env, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from tinypedal.ui.lap_viewer import LapViewer
    from tinypedal.userfile.telemetry_lap import same_circuit

    assert not same_circuit(game_lap(1, 70.0), game_lap(2, 70.0, track="Monza"))
    assert not same_circuit(game_lap(1, 70.0), game_lap(2, 70.0, length=LENGTH * 1.05))
    imported = game_lap(2, 70.0, length=LENGTH * 1.05)
    imported = LapData(imported.name, imported.columns, {key: value for key, value in imported.meta.items()
                                                         if key != "combo"})
    assert same_circuit(game_lap(1, 70.0), imported)  # imported log on driven distance: a bit longer
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    folder = cfg.path.telemetry.rstrip("/")
    for number, lap_time in ((1, 71.0), (2, 70.0)):
        info = {"kind": "lap", "session": "Practice", "combo": TRACK, "track": "Atlanta", "track_length": 2000.0,
                "session_start": BASE}
        module_recorder.save_lap(f"{folder}/", TRACK, number, lap_time, lap_rows(lap_time), max_saved_laps=99,
                                 info=info, timestamp=BASE + number * 100)
    info = {"kind": "lap", "session": "Practice", "combo": "Monza - Hyper", "track": "Monza", "track_length": 2100.0}
    module_recorder.save_lap(f"{tmp_path}/", "Monza - Hyper", 3, 60.0, lap_rows(60.0, slow=1.3), max_saved_laps=99,
                             info=info, timestamp=BASE)
    path = os.path.join(str(tmp_path / "Monza - Hyper"), module_recorder.lap_filename(3, 60.0, True, BASE))
    page = LapViewer(None)
    backend = page.backend
    try:
        wait_loaded(page)
        atlanta = [lap.key for lap in backend.data.laps]
        assert len(atlanta) == 2
        path = os.path.normpath(path)
        backend.add_external([path])  # lap of another circuit: shown alone, laps of Atlanta no longer listed
        wait_loaded(page)
        assert backend.status == "Showing Monza: lap from another circuit"
        assert [lap.key for lap in backend.data.laps] == [path] and backend.reference_key == path
        assert not any(row["path"] in atlanta for row in backend.lap_rows())
        assert backend.currentTrack == "" and backend.trackLabel == "Monza"
        backend.currentTrack = TRACK  # back to Atlanta: its laps, Monza lap never compared with them
        wait_loaded(page)
        assert sorted(lap.key for lap in backend.data.laps) == sorted(atlanta) and path not in backend.checked
        backend.setReference(path)  # never reference lap of laps of current track (other circuit telemetry)
        wait_loaded(page)
        assert "not usable as reference" in backend.status
        assert sorted(lap.key for lap in backend.data.laps) == sorted(atlanta) and path not in backend.checked
    finally:
        page.close()
        flush_deleted()


# --- 9. Damaged driver history & MoTeC half float channel
def test_driver_history_survives_damaged_lines(tmp_path):
    from tinypedal.userfile import driver_history
    from tinypedal.userfile.driver_history import SessionRecord, append_record, read_records

    good = driver_history.record_line(SessionRecord(time=1000.0, track="Spa", vehicle="GT3", best=130.0))
    with open(driver_history.history_path(str(tmp_path)), "wb") as file:
        file.write(good.encode())
        file.write(b'{"time": 1100, "track": "Sp\xe9a", "vehicle": "GT3"}\n')  # not UTF-8
        file.write(b'{"time": 1200, "track": "Spa", "vehicle": "GT3", "best": Infinity, "valid": Infinity}\n')
        file.write(b'{"time": 1300, "track": "Spa", "vehi')  # cut short by a crash
    append_record(str(tmp_path), SessionRecord(time=1400.0, track="Monza", vehicle="GT3", best=110.0))
    records = read_records(str(tmp_path))
    assert [record.time for record in records] == [1000.0, 1100.0, 1200.0, 1400.0]  # appended record kept
    assert records[2].best == 0.0 and records[2].valid == 0  # Infinity read as unknown
    assert records[-1].track == "Monza"


def test_motec_half_float_channel_read(tmp_path):
    from tinypedal.userfile.motec_ld import CHANNEL, EVENT, HEAD, LD_MARKER, VEHICLE, VENUE, read_ld

    values = [0.5, 1.25, -2.0, 100.0]
    filename = str(tmp_path / "half.ld")
    event_ptr = HEAD.size
    venue_ptr = event_ptr + EVENT.size
    vehicle_ptr = venue_ptr + VENUE.size
    meta_ptr = vehicle_ptr + VEHICLE.size
    data_ptr = meta_ptr + CHANNEL.size * 2
    with open(filename, "wb") as file:
        file.write(HEAD.pack(LD_MARKER, meta_ptr, data_ptr, event_ptr, 1, 0x4240, 0xF, 0x1F44, b"ADL", 420, 0xADB0, 2,
                             b"24/09/2026", b"14:05:12", b"", b"", b"Spa", 0, b""))
        file.write(EVENT.pack(b"Spa", b"Practice", b"", venue_ptr))
        file.write(VENUE.pack(b"Spa", vehicle_ptr))
        file.write(VEHICLE.pack(b"", 0, b"", b""))
        file.write(CHANNEL.pack(0, meta_ptr + CHANNEL.size, data_ptr, len(values), 0, 0x07, 2, 10, 0, 1, 1, 0,
                                b"Half", b"m", b""))
        file.write(CHANNEL.pack(meta_ptr, 0, data_ptr + len(values) * 2, len(values), 1, 0x07, 4, 10, 0, 1, 1, 0,
                                b"Single", b"m", b""))
        file.write(struct.pack(f"<{len(values)}e", *values))
        file.write(array("f", values).tobytes())
    _, channels = read_ld(filename)
    assert [channel.name for channel in channels] == ["Half", "Single"]  # half float no longer fails import
    assert list(channels[0].values) == values


# --- 10. Plain data caches: pickled files never loaded
def test_pickled_caches_ignored_and_rebuilt(ui_env, tmp_path, monkeypatch):
    from tinypedal.userfile import lap_cache, lap_geometry

    path = save(2, 70.0, BASE + 200)
    folder = cfg.path.telemetry.rstrip("/")
    target = lap_cache.cache_file(folder, path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as file:
        pickle.dump(Payload(), file)
    _UNPICKLED.clear()
    lap = lap_cache.load_cached_lap(folder, path)
    assert not _UNPICKLED and len(lap) > 100
    with open(target, "rb") as file:
        assert file.read(4) == lap_cache.ARRAYS_MAGIC  # rebuilt as plain data
    again = lap_cache.load_cached_lap(folder, path)
    assert again.columns["distance"] == lap.columns["distance"] and again.info == lap.info
    assert all(isinstance(column, array) for column in again.columns.values())
    parts = tmp_path / "parts"
    parts.mkdir()
    with open(parts / (os.path.basename(path) + ".bin"), "wb") as file:
        pickle.dump(Payload(), file)
    base = lap_geometry.map_line(lap)
    part = lap_geometry.limits_part(folder, str(parts), path, base, "official|test|1")
    assert part is not None and not _UNPICKLED

    def not_read(*args):
        raise AssertionError("lap read again")

    monkeypatch.setattr(lap_geometry, "load_cached_lap", not_read)
    saved = lap_geometry.limits_part(folder, str(parts), path, base, "official|test|1")  # from saved part
    assert saved[0].indexes == part[0].indexes and saved[0].sides == pytest.approx(part[0].sides, abs=1e-3)
    assert saved[1] == part[1]
    assert lap_cache.read_arrays_file(str(parts / "missing.bin")) is None
    (parts / "bad.bin").write_bytes(lap_cache.ARRAYS_HEAD.pack(lap_cache.ARRAYS_MAGIC, 1, 10_000) + b"{}")
    assert lap_cache.read_arrays_file(str(parts / "bad.bin")) is None


# --- 7. Community lap times download never stays busy
def test_reference_download_failure_resets_state(ui_env, monkeypatch):
    import http.client

    from PySide6.QtWidgets import QWidget

    from tests.test_lap_reference import SHEET
    from tinypedal.ui.quick.stats_backend import DriverStatsBackend
    from tinypedal.userfile import lap_reference

    def cut_off(url, timeout=15):
        raise http.client.IncompleteRead(b"partial")

    monkeypatch.setattr(lap_reference, "fetch_sheet", cut_off)
    parent = QWidget()
    backend = DriverStatsBackend(parent)
    try:
        backend.download_reference(force=True)
        end = time.monotonic() + 5
        while backend.downloading and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert not backend.downloading and backend.reference_error  # update button enabled again
    finally:
        backend.release()
        parent.deleteLater()
    table = lap_reference.parse_lap_references(SHEET + "\n" + "x" * 200_000)  # CSV error: rows read so far kept
    assert table.entries


def test_fetch_sheet_cut_off_response_is_os_error(monkeypatch):
    import http.client
    import urllib.request

    from tinypedal.userfile import lap_reference

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            raise http.client.IncompleteRead(b"partial")

    monkeypatch.undo()  # real fetch_sheet (tests replace it by an offline one)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(OSError):
        lap_reference.fetch_sheet(lap_reference.DEFAULT_SHEET_URL)


# --- 12 & 14. Vertices of former settings, timers of closed page
def test_former_vertices_dropped_and_watchers_pruned(viewer):  # noqa: F811
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend

    def page_keys() -> int:
        return sum(1 for key in VertexStore._data if key.startswith(backend.prefix))

    before = page_keys()
    for level in (2, 4, 0):
        backend.setSmoothing(level)
    backend.setTimeAxis(True)
    backend.setTimeAxis(False)
    assert page_keys() <= before + 2  # was growing with every smoothing level & axis change

    class Item:
        def update(self):
            pass

    item = Item()
    VertexStore.watch("audit|key", item)
    del item
    gc.collect()
    VertexStore.prune_watchers("audit|")
    assert "audit|key" not in VertexStore._watchers


def test_release_stops_page_timers(viewer, monkeypatch):  # noqa: F811
    from tinypedal.ui.quick import lap_backend

    monkeypatch.setattr(lap_backend, "_worker_broken", False)
    backend = viewer.backend
    backend.run_process_job("sleep", lambda _: None, time.sleep, 0.3)
    backend.release()
    assert not backend._job_timer.isActive() and not backend._limits_timer.isActive() and not backend._jobs
    wait_events(0.2)
    assert not lap_backend._worker_broken  # killed worker never seen as broken by a late check


# --- 13. CSV export resampled by worker
def test_export_series_csv_resamples(tmp_path):
    from tinypedal.userfile.telemetry_lap import export_series_csv

    filename = str(tmp_path / "laps.csv")
    assert export_series_csv(filename, ["Distance (m)", "a", "b"], 0.0, 30.0,
                             [([10.0, 20.0], [1.0, 2.0]), ([0.0], [5.0])]) == ""
    with open(filename, encoding="utf-8-sig") as file:
        rows = [line.strip().split(",") for line in file]
    assert len(rows) == 32 and rows[1] == ["0", "", ""] and rows[16] == ["15", "1.5", ""] and rows[31][1] == ""


def test_csv_export_in_background(viewer, tmp_path):  # noqa: F811
    filename = str(tmp_path / "export.csv")
    viewer.backend.write_csv(filename, ".", background=True)
    viewer.backend.wait_jobs()
    with open(filename, encoding="utf-8-sig") as file:
        assert len(file.readlines()) > 1000


# --- 6 & 13. Driver stats: theme switch, backups listed once
def test_stats_level_colors_follow_theme_and_backups_cached(ui_env, monkeypatch):
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication, QWidget

    from tests.test_driver_stats_viewer import OREGA, SPA, STATS, write_stats
    from tests.test_lap_reference import SHEET
    from tinypedal.ui.quick import stats_backend
    from tinypedal.userfile import lap_reference

    calls = []
    original = stats_backend.list_stats_backups
    monkeypatch.setattr(stats_backend, "list_stats_backups", lambda path: (calls.append(path), original(path))[1])
    write_stats(STATS)
    lap_reference.save_cache(cfg.path.config, SHEET)
    parent = QWidget()
    backend = stats_backend.DriverStatsBackend(parent)
    app = QApplication.instance()
    saved = app.palette()
    try:
        backend.selectTrack(SPA)
        for _ in range(3):
            backend.refresh_table()
            assert isinstance(backend.backups, list)
        assert len(calls) == 1  # not listed again on every table refresh
        light, dark = QPalette(saved), QPalette(saved)
        light.setColor(QPalette.ColorRole.Window, QColor("#F0F0F0"))
        dark.setColor(QPalette.ColorRole.Window, QColor("#202020"))
        app.setPalette(light)
        QCoreApplication.processEvents()
        light_color = backend.cell(OREGA, "level").color
        app.setPalette(dark)
        QCoreApplication.processEvents()
        dark_color = backend.cell(OREGA, "level").color
        assert light_color and dark_color and light_color != dark_color  # colored again for new theme
    finally:
        app.setPalette(saved)
        backend.release()
        parent.deleteLater()


# --- 15 & 16. QML pages load without warning, help keys
def test_qml_pages_without_warnings(viewer):  # noqa: F811
    from PySide6.QtWidgets import QWidget

    from tests.test_driver_stats_viewer import OREGA, SPA, STATS, write_stats
    from tests.test_lap_reference import SHEET
    from tinypedal.ui.quick import create_quick_view
    from tinypedal.ui.quick.stats_backend import DriverStatsBackend
    from tinypedal.ui.quick.track_map_backend import TrackMapBackend
    from tinypedal.userfile import lap_reference

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    parent = QWidget()
    try:
        write_stats(STATS)
        lap_reference.save_cache(cfg.path.config, SHEET)
        stats = DriverStatsBackend(parent)
        stats.selectTrack(SPA)
        stats.selectRow(OREGA)  # progression chart shown
        for page, backend in (("LapViewer.qml", viewer.backend), ("DriverStats.qml", stats),
                              ("TrackMapViewer.qml", TrackMapBackend(parent))):
            view = create_quick_view(parent, page, {"backend": backend})
            view.resize(1400, 900)
            view.show()
            for _ in range(10):
                QCoreApplication.processEvents()
            assert not view.errors()
        stack, minimap = [viewer.view.rootObject()], None
        while stack:
            item = stack.pop()
            if item.property("mapScale") is not None and item.property("side") is not None:
                minimap = item
            stack.extend(item.childItems())
        assert minimap is not None and minimap.property("scale") == 1.0  # Item.scale no longer overridden
        stats.release()
    finally:
        qInstallMessageHandler(previous)
        parent.deleteLater()
    qml = [text for text in messages if ".qml" in text or "Connections" in text]
    assert not qml, qml


def test_help_lists_every_map_key():
    from tinypedal import i18n
    from tinypedal.ui.quick import QML_FOLDER

    with open(os.path.join(QML_FOLDER, "LapViewer.qml"), encoding="utf-8") as file:
        help_text = file.read()
    with open(os.path.join(QML_FOLDER, "TrackMap.qml"), encoding="utf-8") as file:
        map_text = file.read()
    assert '["1-9", i18n.tr("Line coloring")]' in help_text and '["G", ' in help_text and '["X", ' in help_text
    assert "1-8" not in help_text and "1-8 coloring" not in map_text and "G off track, X track limits" in map_text
    i18n.set_language("Français")
    try:
        assert "1-9" in i18n.tr("Keys: F fit, +/- zoom, arrows move, R turn, 1-9 coloring, B C S O points, "
                                "L lockups, G off track, X track limits, Z zones, T trail, M ruler")
    finally:
        i18n.set_language("English")


# --- 17. Units & decimals
def test_distance_unit_and_decimal_separator(viewer, monkeypatch):  # noqa: F811
    from tinypedal import i18n
    from tinypedal.ui import lap_viewer
    from tinypedal.ui.quick import Theme

    backend = viewer.backend
    assert backend.cursorTitle(1500.0) == "1500 m" and backend.distanceUnit == "m"
    monkeypatch.setitem(cfg.user.setting["units"], "distance_unit", "Feet")
    backend.units_refresh()
    assert backend.cursorTitle(1500.0) == "4921 ft" and backend.distanceUnit == "ft"
    assert backend.distanceScale == pytest.approx(3.2808, abs=1e-3)
    assert backend.deltaWindowTexts[1] == "131 ft"
    assert lap_viewer.display_units()["length"][1] == "in"  # ride height & suspension in inches
    assert backend.data.unit_of(lap_viewer.CHANNEL_MAP["ride_height_fl"]) == "in"
    assert backend.map_ticks(backend._map_lines[0][0])[0]["label"] == "0.25 mi"
    i18n.set_language("Français")
    try:
        assert lap_viewer.number_text(1.5, 1) == "1,5" and lap_viewer.format_value(1.25) == "1,25"
        assert lap_viewer.signed(-0.5, 1) == chr(0x2212) + "0,5" and lap_viewer.format_laptime(70.5) == "1:10.500"
        assert lap_viewer.distance_text(10.0, sign=True) == "+33 ft"
        assert Theme().decimalPoint == ","
        assert i18n.trm(f"Coasting {lap_viewer.number_text(1.5, 1)} s longer") == "Roue libre 1,5 s de plus"
        assert i18n.trm(f"Brakes {lap_viewer.distance_text(12.0)} earlier") == "Freine 39 ft plus tôt"
    finally:
        i18n.set_language("English")
    assert lap_viewer.number_text(1.5, 1) == "1.5"


def test_session_temperature_in_user_unit(viewer, monkeypatch):  # noqa: F811
    backend = viewer.backend
    monkeypatch.setitem(cfg.user.setting["units"], "temperature_unit", "Fahrenheit")
    entry = backend.entries[0]
    monkeypatch.setitem(entry.info, "track_temperature", 30.0)
    row = next(row for row in backend.sessionData["laps"] if row["path"] == entry.file.path)
    assert row["temp"] == pytest.approx(86.0) and backend.sessionData["temperatureUnit"] == "°F"


# --- 11. MoTeC import job
def test_import_ld_job_reports_error(tmp_path):
    from tinypedal.userfile.motec_ld import import_ld_job

    paths, error = import_ld_job(str(tmp_path / "missing.ld"), str(tmp_path / "out"))
    assert paths == [] and error
    bad = tmp_path / "bad.ld"
    bad.write_bytes(b"not a log")
    assert import_ld_job(str(bad), str(tmp_path / "out"))[1] == "not a MoTeC ld file"
