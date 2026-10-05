"""Lap viewer: official circuit (game REST API), lap cache, placement across track, track events, mini-sectors,
session tab, frame steps, passage times, map zoom cache"""

import math
import os

import pytest

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_features import BASE, laps, save, viewer  # noqa: F401
from tinypedal.setting import cfg
from tinypedal.userfile.telemetry_lap import LapData


def ellipse(step: float = 5.0, rx: float = 300.0, ry: float = 200.0) -> list[tuple[float, float, float]]:
    """Track center path of test laps (x, y map coordinates, elevation), about step meters apart"""
    count = int(2 * math.pi * math.sqrt((rx * rx + ry * ry) / 2) / step)
    return [(rx * math.cos(index / count * math.tau), ry * math.sin(index / count * math.tau), 0.0)
            for index in range(count)]


def game_points(center, pit=()) -> list[dict]:
    """Points as game REST API gives them: x, y (elevation), z (map y negated), type"""
    return ([{"type": 0, "x": x, "y": z, "z": -y} for x, y, z in center]
            + [{"type": 1, "x": x, "y": z, "z": -y} for x, y, z in pit])


# --- Lap cache
def test_lap_cache_reads_lap_again_until_file_changes(laps):  # noqa: F811
    from tinypedal.userfile import lap_cache

    folder = cfg.path.telemetry
    path = laps[1]
    first = lap_cache.load_cached_lap(folder, path)
    target = lap_cache.cache_file(folder, path)
    assert os.path.exists(target)
    cached = lap_cache.load_cached_lap(folder, path)  # from binary cache
    assert cached.columns.keys() == first.columns.keys() and cached.info == first.info
    assert cached.distance == pytest.approx(first.distance)
    assert cached.columns["pos_x"] == pytest.approx(first.columns["pos_x"], abs=1e-3)  # single precision
    stamp = os.stat(path)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 10**9))  # lap file changed: read again
    with open(target, "rb") as file:
        before = file.read()
    lap_cache.load_cached_lap(folder, path)
    with open(target, "rb") as file:
        assert file.read() != before
    assert lap_cache.prune_cache(folder, limit=0) >= 1 and not os.path.exists(target)


# --- Official circuit
def test_track_geometry_parsed_matched_and_saved(tmp_path, monkeypatch):
    from tinypedal.userfile import track_geometry

    assert track_geometry.base_name("Circuit de la Sarthe 1.35") == "circuit de la sarthe"
    assert track_geometry.base_name("Paul Ricard Circuit") == "paul ricard circuit"
    center = ellipse()
    points = [*game_points(center, [(0.0, 50.0, 0.0), (10.0, 50.0, 0.0)]), {"type": 7, "x": 1, "y": 0, "z": 1},
              {"bad": 1}]
    parsed, pit = track_geometry.parse_points(points)
    assert parsed[1] == pytest.approx(center[1]) and len(pit) == 2
    positions = [(x * 1.01, y * 1.01) for x, y, _ in center[::3]]  # laps near center path
    assert track_geometry.fit_error(center, positions) < 5
    bigger = ellipse(rx=360, ry=260)
    assert track_geometry.fit_error(bigger, positions) > 40

    answers = {
        "/rest/race/track": [
            {"id": "big", "shortName": "Atlanta 1.0", "sceneDesc": "ATL_BIG", "length": "2.0"},
            {"id": "small", "shortName": "Atlanta 1.0", "sceneDesc": "ATL", "length": "1.585"},
            {"id": "other", "shortName": "Sebring 1.0", "sceneDesc": "SEB"},
        ],
        "/rest/race/track/big/trackmap": game_points(bigger),
        "/rest/race/track/small/trackmap": game_points(center),
    }
    monkeypatch.setattr(track_geometry, "rest_get", lambda host, port, resource, timeout=3: answers.get(resource))
    found = track_geometry.fetch_geometry("localhost", 6397, "Atlanta", positions)
    assert found is not None and found.layout == "ATL" and found.length == pytest.approx(1585)
    assert found.start == pytest.approx(positions[0])
    assert track_geometry.fetch_geometry("localhost", 6397, "Monza", positions) is None  # no such track
    assert track_geometry.fetch_geometry("localhost", 6397, "Atlanta", [(5000.0, 5000.0)]) is None  # other circuit
    track_geometry.save_geometry(str(tmp_path), "Atlanta - Hyper", found)
    loaded = track_geometry.load_geometry(str(tmp_path), "Atlanta - Hyper")
    assert loaded is not None and loaded.layout == "ATL" and loaded.start == pytest.approx(found.start)
    assert loaded.center[5] == pytest.approx(found.center[5], abs=1e-3)
    assert track_geometry.load_geometry(str(tmp_path), "Unknown") is None


def test_official_line_placement_and_track_events():
    from tinypedal.ui.quick import lap_map

    center = ellipse()
    start = (center[10][0] + 0.5, center[10][1])
    line = lap_map.geometry_line(center, start, 1600.0)
    assert (line.xs[0], line.ys[0]) == pytest.approx(center[10][:2]) and line.distances[-1] == pytest.approx(1600)
    assert (line.xs[-1], line.ys[-1]) == pytest.approx((line.xs[0], line.ys[0]))  # closed loop
    assert lap_map.placement(1.0, 5.0, -5.0) == pytest.approx((4.0, 6.0, 20.0))
    assert lap_map.placement(6.0, 5.0, -5.0)[0] == pytest.approx(-1.0)  # beyond left edge

    assert lap_map.track_events([0, 1, 2, 3, 4, 5, 50, 51, 52], [0, 1, 1, 1, 0, 0, 1, 1, 1]) == [1, 50]
    assert lap_map.track_events([0, 1, 2, 3, 4, 5], [1, 1, 0, 1, 1, 0]) == []  # too short
    count = 40
    distances = [float(index) for index in range(count)]
    surfaces = {f"surface_{wheel}": [0.0] * count for wheel in ("fl", "fr", "rl", "rr")}
    for index in range(10, 16):
        surfaces["surface_fl"][index] = surfaces["surface_rl"][index] = 4.0  # 2 wheels in gravel
        surfaces["surface_fr"][index] = 5.0  # rumble strip: still on track
    lap = LapData("a", {"distance": distances, **surfaces})
    assert lap_map.off_track_events(lap) == [10.0]
    assert lap_map.off_track_events(LapData("a", {"distance": distances})) == []
    laterals = [0.0] * count
    laterals[20:25] = [-6.5] * 5  # 1.5 m beyond 5 m edge
    laterals[30:33] = [5.5] * 3  # half a car width out: still on track
    lap = LapData("a", {"distance": distances, "path_lateral": laterals, "track_edge": [5.0] * count})
    assert lap_map.limits_events(lap) == [20.0]


def test_game_limits_one_side_seen_and_fallback():
    from tinypedal.ui.quick import lap_map

    xs = [index * 2.0 for index in range(251)]
    base = lap_map.MapLine(list(xs), list(xs), [0.0] * len(xs))
    car = [3.0 + 2.0 * math.sin(x / 60) for x in xs]  # always left of center: right edge never seen
    laterals = [y for y in car]
    edges = [6.0] * len(xs)
    line = lap_map.MapLine(list(xs), list(xs), car)
    middle = len(xs) // 2
    limits = lap_map.game_limits(base, [(line, laterals, edges)])
    assert limits is not None
    assert limits.left.ys[middle] == pytest.approx(6.0, abs=0.3)
    assert limits.right.ys[middle] == pytest.approx(6.0 - lap_map.WIDTH_DEFAULT, abs=0.3)  # default width
    short = lap_map.MapLine(xs[:20], xs[:20], car[:20])  # game data on 8% of track
    assert lap_map.game_limits(base, [(short, laterals[:20], edges[:20])]) is None
    fallback = lap_map.limits_at(base, [7.0] * len(xs), [-7.0] * len(xs))
    mixed = lap_map.game_limits(base, [(short, laterals[:20], edges[:20])], fallback)
    assert mixed is not None and mixed.right.ys[middle] == pytest.approx(-7.0, abs=0.3)
    edge_left, edge_right = lap_map.edge_offsets(base, fallback)
    assert edge_left[middle] == pytest.approx(7.0, abs=0.05) and edge_right[middle] == pytest.approx(-7.0, abs=0.05)
    offsets = lap_map.LapOffsets(*lap_map.lateral_offsets(base, line), [], [])
    assert lap_map.limits_from_offsets(base, [offsets], base_included=False) is None  # not enough laps
    assert lap_map.limits_from_offsets(base, [offsets] * 3, base_included=False) is not None


def test_mini_sectors_and_backend_helpers():
    from tinypedal.ui.quick import lap_backend, lap_map

    bounds = lap_map.mini_sector_bounds(2000.0)
    assert len(bounds) == 11 and bounds[-1] == 2000.0  # 10 mini-sectors of 200 m
    assert len(lap_map.mini_sector_bounds(13600.0)) == 69
    times = lap_map.mini_sector_times(bounds, [0.0, 2000.0], [0.0, 100.0])
    assert times == pytest.approx([10.0] * 10)
    assert lap_map.mini_sector_winners([[10, 9, 11], [9.5, 9.5, 0]]) == [1, 0, 0]

    assert len(lap_backend.pit_parts([(0, 0, 0), (5, 0, 0), (400, 0, 0), (405, 0, 0), (900, 0, 0)])) == 2
    assert lap_backend.median_bounds([[10, 20], [12, 22], [100, 300], [1]]) == [12, 22]
    assert lap_backend.median_bounds([[10, 20], [12, 22]]) == [11, 21]

    # Recorded yaw: other sign & offset than map heading, found from driving direction
    count = 600
    angles = [index / count * math.tau for index in range(count)]
    xs, ys = [300 * math.cos(a) for a in angles], [300 * math.sin(a) for a in angles]
    headings = [a + math.pi / 2 for a in angles]  # counterclockwise circle
    lap = LapData("a", {"distance": [a * 300 for a in angles], "pos_x": xs, "pos_y": ys,
                        "speed_kph": [150.0] * count, "yaw": [0.7 - heading for heading in headings]})
    sign, offset = lap_backend.yaw_calibration(lap)
    assert sign == -1.0
    assert math.cos(sign * lap.columns["yaw"][100] + offset - headings[100]) == pytest.approx(1.0, abs=1e-6)
    assert lap_backend.yaw_calibration(LapData("a", {"distance": [0.0]})) == (0.0, 0.0)


# --- Viewer
def official_answers(monkeypatch):
    from tinypedal.userfile import track_geometry

    answers = {
        "/rest/race/track": [{"id": "atl", "shortName": "Atlanta 1.0", "sceneDesc": "ATL", "length": "1.585"}],
        "/rest/race/track/atl/trackmap": game_points(ellipse(), [(250.0, -30.0, 0.0), (245.0, -40.0, 0.0),
                                                                  (-250.0, 30.0, 0.0), (-245.0, 40.0, 0.0)]),
    }
    monkeypatch.setattr(track_geometry, "rest_get", lambda host, port, resource, timeout=3: answers.get(resource))


def test_official_circuit_from_game(viewer, monkeypatch):  # noqa: F811
    from tinypedal.ui.lap_viewer import CHANNEL_MAP
    from tinypedal.userfile import track_geometry

    backend = viewer.backend
    assert backend._geometry is None and not backend.trackMap.get("official")
    official_answers(monkeypatch)
    save(5, 71.5, BASE + 500)  # 3 clean laps: track limits
    backend.refresh()  # game asked again
    wait_loaded(viewer)
    backend.wait_jobs()
    while backend._limits_job is not None:
        backend._limits_job.join()
        backend.check_limits_job()
    track = backend.currentTrack
    assert backend._geometry is not None and backend.trackMap["official"] and backend.trackMap["layout"] == "ATL"
    assert track_geometry.load_geometry(cfg.path.telemetry, track) is not None  # saved: works without game
    assert backend.hasLimits and backend.base_key().startswith("official")
    assert os.listdir(backend.limits_parts_folder(track))  # per lap parts: only new laps computed next time
    assert backend.data.available(CHANNEL_MAP["track_position"])  # measured on map, every lap
    xs, ys = backend.data.series(CHANNEL_MAP["path_lateral"], backend.data.reference)
    assert xs and max(abs(value) for value in ys) < 15
    placement = backend.placementAt(500.0, "")
    assert "m" in placement["text"] and placement["color"]
    card = backend.cornerCard(0)
    assert card["widthTitle"] and "→" in card["laps"][0]["width"]
    assert "Braking points spread" in card["spread"] or card["spread"] == ""
    assert len(backend._pit) == 2  # pit lane parts not joined
    backend._limits, backend._limits_track = None, ""
    backend.start_limits(track)  # same laps & base: read from cache
    assert backend._limits is not None and backend._limits_job is None


def test_viewer_frames_passage_minisectors_session(viewer, laps):  # noqa: F811
    backend = viewer.backend
    times = backend.data.lap_times(backend.data.reference)[1]
    x = backend.stepFrame(500.0, 1)
    assert x > 500.0 and backend.stepFrame(x, -1) < x
    assert backend.stepFrame(backend.maxX, 5) == pytest.approx(backend.maxX, abs=1.0)
    assert backend.data.reference_time_at_x(backend.stepFrame(500.0, 1)) in [pytest.approx(t) for t in times]
    rows = backend.passageTimes(500.0, 1000.0)
    assert len(rows) == 2 and sum(row["best"] for row in rows) == 1 and any(row["gap"] for row in rows)
    backend.setMapMode("minisectors")
    legend = backend.mapLegend
    assert sum(row["count"] for row in legend["mini"]) == legend["sectors"] == 10 and legend["ideal"]
    backend.setMapMode("laps")
    assert all("slip" in point for point in backend.mapCursor(500.0))
    session = backend.sessionData
    assert len(session["laps"]) == 4 and backend.sessions and session["best"] == pytest.approx(70.0)
    assert any(lap["shown"] for lap in session["laps"])
    backend.setSideTab(4)  # values read from lap files in background
    backend.wait_jobs()
    assert backend.sessionData["laps"][0]["wear"] is not None
    backend.setSideTab(0)


def test_map_zoom_steps_cached_and_prepared(viewer):  # noqa: F811
    from tinypedal.ui.quick import lap_backend

    backend = viewer.backend
    for index in range(16):
        backend.setMapView(0, 0, 0.05 * 1.5 ** index)
        assert len(backend._band_cache) <= lap_backend.BAND_CACHE_STEPS
    backend.wait_jobs()
    step = backend._preview_step
    assert step - 1 / lap_backend.ZOOM_BUCKETS in backend._band_cache  # zoom in & out ready
    assert step + 1 / lap_backend.ZOOM_BUCKETS in backend._band_cache
    # Zoom starting: target scale prepared in background, nearest prepared step shown while zoom eases
    view = backend._map_view
    backend.prepareMapScale(0.01)
    backend.wait_jobs()
    target = lap_backend.scale_step(0.01)
    assert target in backend._band_cache
    backend.previewMapScale(0.013)
    assert backend._preview_step == target
    backend.setMapView(0, 0, view[2])  # zoom back where it was: lines of that scale shown again
    assert backend._preview_step == lap_backend.scale_step(view[2])


def test_long_series_reduced_copy(viewer, monkeypatch):  # noqa: F811
    from tinypedal.ui.quick import lap_backend
    from tinypedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    assert all(series["lods"] == [] for panel in backend.panels for series in panel["series"])  # short laps
    monkeypatch.setattr(lap_backend, "LOD_LEVELS", (20, 50, 100000))
    backend.rebuild_chart()
    reduced = [series for panel in backend.panels for series in panel["series"] if series["lods"]]
    assert reduced and all(len(series["lods"]) == 2 for series in reduced)  # level over sample count not made
    (small, small_key), (large, large_key) = reduced[0]["lods"]
    assert small == 20 and large == 50
    assert VertexStore.get(small_key).vertex_count <= 40 + 4 < VertexStore.get(large_key).vertex_count <= 100 + 4


def test_passage_csv_export(viewer, tmp_path):  # noqa: F811
    backend = viewer.backend
    target = tmp_path / "passage.csv"
    assert backend.write_csv(str(target), ".", 500.0, 600.0)
    rows = target.read_text(encoding="utf-8-sig").splitlines()
    assert len(rows) == 102 and rows[1].startswith("500") and rows[-1].startswith("600")
