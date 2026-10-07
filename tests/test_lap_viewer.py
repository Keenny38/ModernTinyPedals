"""Recorded lap loading, delta & viewer tests"""

import pytest

from tinypedal.module import module_recorder
from tinypedal.userfile.telemetry_lap import compute_delta, interpolate, list_laps, list_tracks, load_lap


def write_lap(folder, lap_number, lap_time, samples=300, length=3000.0):
    rows = []
    for index in range(samples + 1):
        progress = index / samples
        rows.append((
            progress * lap_time, progress * lap_time, progress * length, 180.0, 1.0, 0.0, 0.0, 0.1,
            4, 7000, 50.0, 80, 80, 80, 80, 170, 170, 170, 170, 0.0, 0.0,
        ) + (0,) * (len(module_recorder.CSV_HEADER) - 21))
    module_recorder.save_lap(f"{folder}/", "Track - GT3", lap_number, lap_time, rows, max_saved_laps=10)


def wait_loaded(viewer, timeout: float = 10.0):
    """Process events until background lap loading is done"""
    import time

    from PySide6.QtWidgets import QApplication

    end = time.monotonic() + timeout
    while viewer.is_loading() and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    assert not viewer.is_loading()


def flush_deleted():
    """Delete closed dialogs now (singleton dialog is released on destroy)"""
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_interpolate():
    assert interpolate([0, 10], [0, 100], 5) == pytest.approx(50)
    assert interpolate([0, 10], [0, 100], -1) == 0
    assert interpolate([0, 10], [0, 100], 20) == 100


def test_load_and_delta(tmp_path):
    write_lap(tmp_path, 1, 90.0)
    write_lap(tmp_path, 2, 92.0)
    assert list_tracks(f"{tmp_path}/") == ["Track - GT3"]
    laps = list_laps(f"{tmp_path}/", "Track - GT3")
    assert len(laps) == 2 and all(lap.valid for lap in laps)
    lap_90 = load_lap(next(lap.path for lap in laps if "1m30" in lap.filename))
    lap_92 = load_lap(next(lap.path for lap in laps if "1m32" in lap.filename))
    assert lap_90.lap_time == pytest.approx(90.0)
    delta = compute_delta(lap_90, lap_92)
    assert delta[-1][1] == pytest.approx(2.0, abs=0.01)  # 2s slower at finish
    assert delta[len(delta) // 2][1] == pytest.approx(1.0, abs=0.02)  # 1s at half lap


def test_invalid_file(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_lap(str(path))


def test_decimate_minmax_keeps_peaks():
    from tinypedal.userfile.telemetry_lap import decimate_minmax

    xs = [float(index) for index in range(10000)]
    ys = [0.0] * 10000
    ys[5003] = 1.0  # short brake spike
    points = decimate_minmax(xs, ys, 0.0, 10000.0, 100)
    assert len(points) <= 2 * 101 + 2
    assert (5003.0, 1.0) in points
    assert decimate_minmax(xs[:10], ys[:10], 0, 10, 100) == list(zip(xs[:10], ys[:10]))  # few points kept
    assert decimate_minmax([], [], 0, 1, 10) == []


def test_sectors_and_theoretical_best():
    from tinypedal.userfile.telemetry_lap import LapData, sector_bounds, sector_times, theoretical_best

    distance = [float(index) for index in range(0, 3001, 10)]
    lap = LapData("a", {
        "distance": distance,
        "lap_time": [d / 30 for d in distance],
        "sector": [0 if d < 1000 else 1 if d < 2000 else 2 for d in distance],
    })
    assert sector_bounds(lap) == [1000.0, 2000.0]
    assert sector_times(lap) == pytest.approx([33.333, 33.333, 33.333], abs=0.01)
    official = LapData("b", lap.columns, {"sectors": [30.0, 31.0, 32.0]})
    assert sector_times(official) == [30.0, 31.0, 32.0]  # official game sector times first
    total, best = theoretical_best([[30.0, 33.0, 32.0], [31.0, 31.0, 33.0], []])
    assert best == [30.0, 31.0, 32.0] and total == pytest.approx(93.0)
    assert theoretical_best([]) == (0.0, [])


def test_compressed_lap_file_with_info(tmp_path):
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    info = {"kind": "lap", "vehicle": "Car A", "sectors": [1.0, 2.0, 1.9]}
    assert module_recorder.save_lap(
        f"{tmp_path}/", "T - C", 7, 4.9, rows, max_saved_laps=5, info=info, compress=True)
    laps = list_laps(f"{tmp_path}/", "T - C")
    assert len(laps) == 1 and laps[0].filename.endswith(".csv.gz") and laps[0].lap_time == pytest.approx(4.9)
    lap = load_lap(laps[0].path)
    assert lap.meta["vehicle"] == "Car A" and len(lap) == 50
    assert lap.name.endswith("4.900s")


def test_old_lap_file_without_info(tmp_path):
    path = tmp_path / "2026-01-01 10-00-00 lap001 1m30.000s.csv"
    path.write_text("time,lap_time,distance\n0,0,0\n1,1,10\n", encoding="utf-8")
    lap = load_lap(str(path))
    assert lap.meta == {} and len(lap) == 2


def test_lap_bounds_drop_previous_and_next_lap_distance():
    from tinypedal.userfile.telemetry_lap import lap_bounds

    # Lap distance reset late (previous lap distance at start), next lap distance at end
    distances = [3584.0, 3584.0, 5.0, 500.0, 1500.0, 2500.0, 3580.0, 3.0]
    assert lap_bounds(distances) == (2, 7)
    assert lap_bounds([5.0, 500.0, 3000.0]) == (0, 3)  # clean lap kept
    assert lap_bounds([3581.0, 3581.0, 3.0, 50.0, 104.0]) == (2, 5)  # short lap: only start trimmed


def test_smooth_distance_between_game_updates():
    from tinypedal.userfile.telemetry_lap import smooth_distance

    times = [0.0, 0.1, 0.2, 0.3, 0.4]
    assert smooth_distance(times, [0.0, 0.0, 10.0, 10.0, 20.0]) == pytest.approx([0.0, 5.0, 10.0, 15.0, 20.0])
    assert smooth_distance(times, [0.0, 1.0, 2.0, 3.0, 4.0]) == [0.0, 1.0, 2.0, 3.0, 4.0]  # every sample updated


def test_load_lap_with_late_distance_reset(tmp_path):
    """Recorded lap starting with previous lap distance must still plot (was a single point)"""
    from tinypedal.userfile.telemetry_lap import monotonic_distance

    rows = []
    for index in range(500):
        lap_time = index * 0.02
        distance = 3000.0 if index < 5 else round((index // 10) * 10 * 0.6, 2)  # updated every 10 samples
        rows.append((lap_time, lap_time, distance, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4))
    module_recorder.save_lap(f"{tmp_path}/", "T - C", 1, 10.0, rows, max_saved_laps=5)
    lap = load_lap(list_laps(f"{tmp_path}/", "T - C")[0].path)
    assert lap.distance[0] < 10
    assert len(monotonic_distance(lap)[0]) > 400  # nearly every sample on its own distance


def test_delta_limit_ignores_aberrant_lap():
    from tinypedal.ui.lap_viewer import delta_limit

    normal = [0.1 * index / 100 for index in range(100)]  # up to 0.1s
    close = [0.3 * index / 100 for index in range(100)]  # up to 0.3s
    aberrant = [60.0] * 100  # lap cut short
    assert delta_limit([close, aberrant, normal]) == pytest.approx(0.3 * 0.95 * 1.15, abs=0.01)
    assert delta_limit([aberrant]) == pytest.approx(69.0)  # alone: shown entirely
    assert delta_limit([]) == 0.1
    assert delta_limit([[0.0, 0.01]]) == 0.1


def test_sector_lines_at_official_sector_times():
    """Sector column changes late (scoring data at 5 Hz): official times place sector lines exactly"""
    from tinypedal.userfile.telemetry_lap import LapData, sector_bounds

    distance = [float(index) for index in range(0, 3001, 10)]
    columns = {
        "distance": distance,
        "lap_time": [d / 30 for d in distance],  # 30 m/s
        "sector": [0 if d < 1015 else 1 if d < 2015 else 2 for d in distance],  # 15 m late
    }
    assert sector_bounds(LapData("a", columns)) == [1020.0, 2020.0]
    assert sector_bounds(LapData("b", columns, {"sectors": [33.0, 34.0, 33.0]})) == pytest.approx([990.0, 2010.0])
    assert sector_bounds(LapData("c", columns, {"sectors": [33.0, "x", 33.0]})) == [1020.0, 2020.0]  # invalid info


def save_session_lap(folder, number, lap_time, timestamp, session="Practice", start=None, valid=True, kind="lap"):
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    info = {"kind": kind, "session": session, "vehicle": "Porsche 963"}
    if start is not None:
        info["session_start"] = start
    module_recorder.save_lap(f"{folder}/", "Atlanta - Hyper", number, lap_time, rows, max_saved_laps=99,
                             valid=valid, info=info, timestamp=timestamp)


def test_laps_grouped_by_session():
    import time

    from tinypedal.userfile.telemetry_lap import group_sessions, lap_number_of, lap_timestamp_of

    base = time.mktime((2026, 10, 3, 14, 0, 0, 0, 0, -1))
    laps = [  # (file name, info)
        (f"{time.strftime('%Y-%m-%d %H-%M-%S', time.localtime(base + t))} lap{n:03d} 1m30.000s.csv", info)
        for t, n, info in (
            (0, 1, {"session": "Practice"}), (90, 2, {"session": "Practice"}), (180, 3, {"session": "Practice"}),
            (400, 1, {"session": "Practice"}),  # lap number restarts: new session
            (3000, 2, {"session": "Practice"}),  # long break: new session
            (3090, 3, {"session": "Qualify"}),  # other session type
            (9000, 5, {"session": "Race", "session_start": base + 8500}),  # recorded session start
            (9200, 1, {"session": "Race", "session_start": base + 8520}),  # same start (rejoin): same session
            (9400, 6, {"session": "Race", "session_start": base + 9300}),  # restarted session
        )
    ]
    assert lap_number_of(laps[0][0]) == 1 and lap_timestamp_of(laps[0][0]) == base
    assert lap_timestamp_of("unknown.csv") == 0.0 and lap_number_of("unknown.csv") == 0
    groups = group_sessions(laps, lambda lap: lap[0], lambda lap: lap[1])
    numbers = [[lap_number_of(name) for name, _ in group] for group in groups]
    assert numbers == [[6], [5, 1], [3], [2], [1], [1, 2, 3]]  # newest session first, laps in driving order


# --- Viewer page (Qt Quick): state checked through its backend
@pytest.fixture
def open_viewer(ui_env):
    """Open lap viewer dialogs, closed after test"""
    from tinypedal.ui.lap_viewer import LapViewer

    viewers = []

    def opening():
        viewer = LapViewer(None)
        viewers.append(viewer)
        wait_loaded(viewer)  # laps read in background
        return viewer

    yield opening
    import shiboken6

    for viewer in viewers:
        if shiboken6.isValid(viewer):
            viewer.close()
    flush_deleted()


def lap_paths(backend) -> list[str]:
    return [row["path"] for row in backend.lap_rows()]


def test_lap_viewer_dialog(open_viewer):
    from tinypedal.setting import cfg

    write_lap(cfg.path.telemetry.rstrip("/"), 1, 90.0)
    write_lap(cfg.path.telemetry.rstrip("/"), 2, 91.0)
    viewer = open_viewer()
    backend = viewer.backend
    assert backend.currentTrack == "Track - GT3"
    assert backend.data.reference is not None and len(backend.data.compared()) == 1
    assert backend.data.deltas  # delta of compared lap
    assert not viewer.view.errors() and viewer.view.rootObject() is not None
    values = backend.cursorValues(1500.0)
    assert len(values) == len(backend.panels) and backend.cursorTitle(1500.0) == "1500 m"


def test_lap_viewer_multiple_laps(open_viewer):
    from tinypedal.setting import cfg

    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 92.0)
    write_lap(folder, 2, 90.0)
    write_lap(folder, 3, 91.0)
    viewer = open_viewer()
    backend = viewer.backend
    assert "1m30.000s" in backend.reference_key  # best lap is reference
    for path in lap_paths(backend):
        backend.setLapChecked(path, True)
    wait_loaded(viewer)
    assert len(backend.data.laps) == 3
    assert backend.data.reference is not None and "1m30" in backend.data.reference.key
    newest = lap_paths(backend)[-1]  # laps in driving order
    backend.setReference(newest)
    assert backend.data.reference.key == newest and backend.legend[0]["reference"]
    backend.setChannelVisible("rpm", True)
    assert "rpm" in [panel["column"] for panel in backend.panels]
    backend.resetChannels()
    assert "rpm" not in [panel["column"] for panel in backend.panels]


def test_trace_data_many_laps(ui_env, tmp_path):
    from PySide6.QtGui import QColor

    from tinypedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData

    write_lap(tmp_path, 1, 90.0)
    write_lap(tmp_path, 2, 91.0)
    write_lap(tmp_path, 3, 92.0)
    laps = [load_lap(lap.path) for lap in list_laps(f"{tmp_path}/", "Track - GT3")]
    data = TraceData()
    data.set_laps([PlotLap(str(index), lap.name, lap, QColor("red")) for index, lap in enumerate(laps)], "2")
    assert data.reference is not None and data.reference.key == "2"
    assert len(data.deltas) == 2  # one delta per compared lap
    assert data.max_x() == pytest.approx(3000.0)
    speed = CHANNEL_MAP["speed_kph"]
    low, high = data.value_range(speed)
    assert low < 180 < high
    assert [text for _, text in data.values_at(speed, 1500.0)] == ["180", "180", "180"]


def test_lap_viewer_added_file_not_in_theoretical_best(open_viewer, tmp_path, monkeypatch):
    from tinypedal.setting import cfg
    from tinypedal.ui.quick import lap_export

    folder = cfg.path.telemetry.rstrip("/")
    info = {"sectors": [30.0, 30.0, 30.0]}
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    module_recorder.save_lap(f"{folder}/", "Track - GT3", 1, 90.0, rows, 10, info=info)
    other = tmp_path / "other"
    # Same track from another folder (teammate): a lap of another track is never added (other circuit)
    module_recorder.save_lap(f"{other}/", "Track - GT3", 1, 60.0, rows, 10, info={"sectors": [20.0, 20.0, 20.0]})
    other_file = next((other / "Track - GT3").glob("*.csv"))
    monkeypatch.setattr(lap_export.QFileDialog, "getOpenFileNames", lambda *args: ([str(other_file)], ""))
    backend = open_viewer().backend
    backend.addFiles()
    wait_loaded(backend)
    assert [row["kind"] for row in backend.lap_model.rows].count("session") == 2
    assert "1:30.000" in backend.bestText  # added lap sectors left out
    assert len(backend.legend) == 2  # added lap shown


def test_lap_cache_is_bounded(open_viewer, monkeypatch):
    from tinypedal.setting import cfg
    from tinypedal.ui import lap_viewer

    monkeypatch.setattr(lap_viewer, "LAP_CACHE_SIZE", 5)
    folder = cfg.path.telemetry.rstrip("/")
    for lap in range(8):
        write_lap(folder, lap, 90.0 + lap, samples=20)
    backend = open_viewer().backend
    for entry in backend.entries:
        backend.read_lap(entry.file.path)
    assert len(backend._lap_cache) == lap_viewer.LAP_CACHE_SIZE


def test_channel_order_kept(open_viewer):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import load_visible_channels

    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 90.0)
    write_lap(folder, 2, 91.0)
    backend = open_viewer().backend
    columns = list(backend.visible)
    backend.moveChannel(1, len(columns) - 1)  # speed dragged to bottom
    expected = [column for column in columns if column != "speed_kph"] + ["speed_kph"]
    assert [panel["column"] for panel in backend.panels] == expected
    assert load_visible_channels(backend.folder) == expected  # order kept
    backend.setChannelVisible("rpm", True)
    assert backend.visible[-1] == "rpm" and backend.visible[:-1] == expected  # new channel added at bottom


def test_track_map_draws_circuit_from_track_map_file(open_viewer):
    from tinypedal.setting import cfg
    from tinypedal.ui.quick.lines import VertexStore
    from tinypedal.userfile.track_map import save_track_map_file

    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 90.0)  # positions not recorded by helper: (0, 0)
    circuit = tuple((float(x), float(x % 7)) for x in range(0, 500, 10))
    dists = tuple((float(index), 0.0) for index in range(len(circuit)))
    save_track_map_file(cfg.path.track_map, "Track", "0 0 500 10", circuit, dists, (10, 20), 2)
    backend = open_viewer().backend
    assert backend._road.xs == [x for x, _ in circuit]  # "Track - GT3" folder: track map "Track"
    track_map = backend.trackMap
    assert VertexStore.get(track_map["road"]).vertex_count > 10
    assert track_map["lines"] == [] and track_map["maxX"] == 490.0


def test_track_map_circuit_falls_back_to_reference_lap(open_viewer):
    from PySide6.QtGui import QColor

    from tinypedal.ui.lap_viewer import PlotLap
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(0, 101, 10)]
    times = [d / 10 for d in distance]
    reference = LapData("a", {"distance": distance, "lap_time": times, "pos_x": [d + 1 for d in distance],
                              "pos_y": distance})
    other = LapData("b", {"distance": distance, "lap_time": times, "pos_x": [d + 2 for d in distance],
                          "pos_y": distance})
    backend = open_viewer().backend
    backend.data.set_laps([PlotLap("a", "a", reference, QColor("red")), PlotLap("b", "b", other, QColor("blue"))])
    backend.rebuild_chart()
    assert backend._road.xs == [d + 1 for d in distance]  # no track map file: reference lap line
    assert len(backend.trackMap["lines"]) == 2 and backend.trackMap["lines"][0]["reference"]
    backend.data.set_laps([])
    backend.rebuild_chart()
    assert backend.trackMap == {}


def test_hidden_viewer_releases_laps_and_reloads(open_viewer):
    from tinypedal.setting import cfg

    write_lap(cfg.path.telemetry.rstrip("/"), 1, 90.0)
    write_lap(cfg.path.telemetry.rstrip("/"), 2, 91.0)
    viewer = open_viewer()
    backend = viewer.backend
    restored = []
    backend.viewRestored.connect(lambda start, end: restored.append((start, end)))
    viewer.show()
    backend.setChartView(500.0, 1500.0)
    backend.release_laps()  # visible: kept
    assert backend.data.laps and backend._lap_cache
    viewer.hide()
    assert backend._release_timer.isActive()  # released after a while in background
    backend.release_laps()
    backend.setChartView(0.0, 1.0)  # page emptied: chart view reset
    assert not backend.data.laps and not backend._lap_cache and not backend.panels[0]["series"]
    viewer.show()  # same laps & zoom again
    wait_loaded(viewer)
    assert len(backend.data.laps) == 2 and not backend._release_timer.isActive()
    assert restored == [(500.0, 1500.0)]


def test_map_colored_by_time_gain():
    import math

    from tinypedal.ui.lap_viewer import GAIN_COLOR, LOSS_COLOR, gain_color
    from tinypedal.ui.quick import lap_map
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(0, 2001, 10)]
    xs = [500 * math.cos(d / 2000 * math.tau) for d in distance]
    ys = [500 * math.sin(d / 2000 * math.tau) for d in distance]
    reference = LapData("ref", {"distance": distance, "lap_time": [d / 50 for d in distance], "pos_x": xs, "pos_y": ys})
    # Compared: slower on first half (40 m/s), faster on second half (60 m/s)
    times = [d / 40 if d <= 1000 else 25 + (d - 1000) / 60 for d in distance]
    compared = LapData("cmp", {"distance": distance, "lap_time": times, "pos_x": xs, "pos_y": ys})
    line = lap_map.map_line(compared)
    assert line is not None
    colors = dict(zip(line.distances, lap_map.gain_colors(reference, compared, line)))
    assert colors[500.0] == LOSS_COLOR and colors[1500.0] == GAIN_COLOR  # losing then gaining
    assert gain_color(0.0).name() == "#9ca3af"


def test_map_mode_saved(open_viewer):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import load_viewer_setting

    backend = open_viewer().backend
    assert backend.mapMode == "laps"
    backend.setMapMode("speed")
    backend.setMapMode("unknown")  # ignored
    assert backend.mapMode == "speed"
    assert load_viewer_setting(cfg.path.telemetry)["map_color_mode"] == "speed"
    backend.parent().close()
    flush_deleted()
    assert open_viewer().backend.mapMode == "speed"  # remembered


def test_former_time_gain_option_kept(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import save_viewer_setting
    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    save_viewer_setting(cfg.path.telemetry, map_time_gain=True)  # before color modes
    parent = QWidget()
    assert LapViewerBackend(parent, cfg.path.telemetry).mapMode == "gain"
    parent.deleteLater()


def test_lap_list_shows_sessions(open_viewer):
    import time

    from tinypedal.setting import cfg

    folder = cfg.path.telemetry.rstrip("/")
    base = time.mktime((2026, 10, 3, 14, 0, 0, 0, 0, -1))
    for number, lap_time in ((1, 92.0), (2, 90.0), (3, 91.0)):
        save_session_lap(folder, number, lap_time, base + number * 95, start=base)
    save_session_lap(folder, 1, 95.0, base + 7200, session="Race", start=base + 7000, valid=False)
    save_session_lap(folder, 2, 89.5, base + 7300, session="Race", start=base + 7000)
    backend = open_viewer().backend
    rows = backend.lap_model.rows
    sessions = [row for row in rows if row["kind"] == "session"]
    assert [row["title"] for row in sessions] == ["Race  03/10 15:56", "Practice  03/10 14:00"]
    race, practice = sessions
    assert race["time"] == "1:29.500" and race["count"] == 2 and race["info"] == "Porsche 963"
    practice_laps = [row for row in rows if row["session"] == practice["session"] and row["kind"] == "lap"]
    assert [row["title"] for row in practice_laps] == ["Lap 1", "Lap 2", "Lap 3"]
    assert [row["fastest"] for row in practice_laps] == [False, True, False]  # fastest starred
    assert practice_laps[0]["info"] == ""  # vehicle shown once, on session row
    race_laps = [row for row in rows if row["session"] == race["session"] and row["kind"] == "lap"]
    assert "invalid" in race_laps[0]["info"] and race_laps[0]["dim"]
    assert race["session"] in backend.expanded  # reference (best lap) inside
    backend.setReference("")  # session row: no lap
    assert backend.reference_key.endswith("1m29.500s.csv")
