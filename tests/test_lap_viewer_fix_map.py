"""Lap viewer audit fixes (track map & corners): game track edges, caches checked again, placement across track,
official corner deltas, reference lap without positions, Le Mans corners, corner table sums, cursor trails, picking"""

import json
import math
import os
import random
from collections import namedtuple

import pytest

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_features import BASE, TRACK, lap_rows, laps, save, viewer  # noqa: F401
from tests.test_lap_viewer_official import ellipse, game_points
from tinypedal.module import module_recorder
from tinypedal.setting import cfg

Corner = namedtuple("Corner", "number start end apex")  # corner found on reference lap (fields used by map)
Row = namedtuple("Row", "corner time_delta")  # corner row of corner table (fields used by map)


def finish_limits(backend):
    """Wait for track limits job & its result"""
    backend.wait_jobs()
    while backend._limits_job is not None:
        backend._limits_job.join()
        backend.check_limits_job()
    backend.wait_jobs()


def save_game_lap(number: int, lap_time: float, timestamp: float, lateral: float, edge: float) -> str:
    """Lap recording game lateral position & track edge (same positions as other test laps)"""
    lateral_index = module_recorder.CSV_HEADER.index("path_lateral")
    rows = []
    for row in lap_rows(lap_time):
        row = list(row)
        row[lateral_index], row[lateral_index + 1] = lateral, edge
        rows.append(tuple(row))
    folder = cfg.path.telemetry.rstrip("/")
    info = {"kind": "lap", "session": "Practice", "vehicle": "Porsche 963", "session_start": BASE}
    module_recorder.save_lap(f"{folder}/", TRACK, number, lap_time, rows, max_saved_laps=99, info=info,
                             timestamp=timestamp)
    return os.path.join(f"{folder}/{TRACK}", module_recorder.lap_filename(number, lap_time, True, timestamp))


def answer_game(monkeypatch, short_name: str = "Atlanta 1.0", center=None) -> list[str]:
    """Game REST API answers (official circuit of test laps), returns asked resources"""
    from tinypedal.userfile import track_geometry

    asked: list[str] = []
    answers = {
        "/rest/race/track": [{"id": "atl", "shortName": short_name, "sceneDesc": "ATL", "length": "1.585"}],
        "/rest/race/track/atl/trackmap": game_points(center or ellipse()),
    }

    def rest_get(host, port, resource, timeout=3):
        asked.append(resource)
        return answers.get(resource)

    monkeypatch.setattr(track_geometry, "rest_get", rest_get)
    return asked


def check_geometry_again(backend):
    """Official circuit of shown track loaded again & checked in background (track opened again)"""
    backend._geometry_track = ""
    backend._geometry_tried.discard(backend.currentTrack)
    backend.start_geometry(backend.currentTrack)
    backend.wait_jobs()


# --- Game track edges (J1)
def laps_around(base, center, half_widths, offsets, sign=1.0):
    """Laps near base line at several offsets: game lateral position from game center path, track edge on car side"""
    from tinypedal.ui.quick import lap_map

    found = []
    for offset in offsets:
        ys = [offset + 0.1 * math.sin(x / 35 + offset) for x in base.xs]
        laterals = [sign * (y - middle) for y, middle in zip(ys, center)]
        edges = [math.copysign(left if y > middle else right, lateral)
                 for y, middle, lateral, (left, right) in zip(ys, center, laterals, half_widths)]
        line = lap_map.MapLine(list(base.distances), list(base.xs), ys)
        found.append(lap_map.LapOffsets(*lap_map.lateral_offsets(base, line), laterals, edges))
    return found


@pytest.mark.parametrize("game_sign", [1.0, -1.0])
def test_game_edges_from_laps_following_base_line(game_sign):
    from tinypedal.ui.quick import lap_map

    xs = [index * 4.0 for index in range(301)]
    base = lap_map.MapLine(list(xs), list(xs), [0.0] * len(xs))  # driving line, not track center
    center = [3.0 * math.sin(x / 60) for x in xs]  # game center path moves around base line as much as laps
    halves = [(6.0, 6.0)] * len(xs)  # 12 m track
    placed = laps_around(base, center, halves, (-1.5, -0.5, 0.0, 0.8, 1.6), game_sign)
    assert lap_map.lateral_sign(placed, len(xs)) == game_sign  # found once over all laps
    limits = lap_map.game_limits_from_offsets(base, placed)
    assert limits is not None
    lefts, rights = lap_map.edge_offsets(base, limits)
    widths = sorted(left - right for left, right in zip(lefts, rights))
    assert widths[len(widths) // 2] == pytest.approx(12.0, abs=0.3)  # not narrowed by a wrong sign on some laps
    assert widths[0] > 11.0
    for index in range(30, 270, 20):
        assert lefts[index] == pytest.approx(center[index] + 6.0, abs=0.4)
        assert rights[index] == pytest.approx(center[index] - 6.0, abs=0.4)
    # Lap alone following base line: sign not told by laps, game convention
    single = laps_around(base, center, halves, (0.0,))
    assert lap_map.lateral_sign(single, len(xs)) == lap_map.GAME_LATERAL_SIGN


def test_game_edges_each_side_seen_or_mirrored():
    from tinypedal.ui.quick import lap_map

    xs = [index * 4.0 for index in range(301)]
    base = lap_map.MapLine(list(xs), list(xs), [0.0] * len(xs))
    placed = laps_around(base, [0.0] * len(xs), [(7.0, 5.0)] * len(xs), (-2.0, -1.0, 1.0, 2.0))  # both seen
    lefts, rights = lap_map.edge_offsets(base, lap_map.game_limits_from_offsets(base, placed))
    assert lefts[150] == pytest.approx(7.0, abs=0.3) and rights[150] == pytest.approx(-5.0, abs=0.3)
    center = [-3.0] * len(xs)  # every lap left of game center path: right edge never seen
    placed = laps_around(base, center, [(6.5, 6.5)] * len(xs), (-1.0, 0.0, 1.0))
    lefts, rights = lap_map.edge_offsets(base, lap_map.game_limits_from_offsets(base, placed))
    assert lefts[150] == pytest.approx(3.5, abs=0.3) and rights[150] == pytest.approx(-9.5, abs=0.3)


# --- Track edges & official circuit caches (J52, J41)
def test_limits_cache_versioned_and_base_key(viewer, monkeypatch):  # noqa: F811
    from tinypedal.ui.quick import lap_map
    from tinypedal.userfile import track_geometry

    backend = viewer.backend
    answer_game(monkeypatch)
    save(5, 71.5, BASE + 500)  # 3 clean laps: track limits
    backend.refresh()
    wait_loaded(viewer)
    finish_limits(backend)
    track = backend.currentTrack
    geometry = backend._geometry
    assert geometry is not None and geometry.name == "Atlanta 1.0" and backend.hasLimits
    saved_geometry = track_geometry.load_geometry(cfg.path.telemetry, track)
    assert saved_geometry is not None and saved_geometry.name == "Atlanta 1.0"  # game version saved
    key = backend.base_key()
    assert "Atlanta 1.0" in key
    backend._geometry = geometry._replace(start=(geometry.start[0] + 30, geometry.start[1]))
    assert backend.base_key() != key  # circuit fetched again from another start: lap placements measured again
    backend._geometry = geometry
    cache = backend.limits_cache_path(track)
    with open(cache, encoding="utf-8") as file:
        saved = json.load(file)
    assert saved["version"] == lap_map.LIMITS_VERSION and saved["base"] == key
    backend._limits, backend._limits_track = None, ""
    backend.start_limits(track)
    assert backend._limits is not None and backend._limits_job is None  # same laps, base & algorithm: cache
    del saved["version"]  # saved by an older algorithm (wrong game edges): computed again
    with open(cache, "w", encoding="utf-8") as file:
        json.dump(saved, file)
    backend._limits, backend._limits_track = None, ""
    backend.start_limits(track)
    assert backend._limits_job is not None
    finish_limits(backend)


def test_saved_circuit_checked_against_laps_and_game_version(viewer, monkeypatch):  # noqa: F811
    from tinypedal.userfile import track_geometry

    backend = viewer.backend
    track = backend.currentTrack
    folder = cfg.path.telemetry
    start = (300.0, 0.0)
    # Saved by an older game version: fetched again while game runs, base of placement changes
    track_geometry.save_geometry(folder, track, track_geometry.TrackGeometry("ATL", 1585, ellipse(), [], start,
                                                                             "Atlanta 0.9"))
    asked = answer_game(monkeypatch, "Atlanta 1.0")
    check_geometry_again(backend)
    assert backend._geometry.name == "Atlanta 1.0"
    assert track_geometry.load_geometry(folder, track).name == "Atlanta 1.0"
    asked.clear()  # current version: kept, only the track list asked
    check_geometry_again(backend)
    assert asked == ["/rest/race/track"] and backend._geometry.name == "Atlanta 1.0"
    # Saved circuit laps no longer lie along (other layout) & game not running: not used
    far = [(x + 5000.0, y, z) for x, y, z in ellipse()]
    track_geometry.save_geometry(folder, track, track_geometry.TrackGeometry("ATL", 1585, far, [], start, "Atlanta 1.0"))
    monkeypatch.setattr(track_geometry, "rest_get", lambda host, port, resource, timeout=3: None)
    check_geometry_again(backend)
    assert backend._geometry is None and backend.base_key() == "lap"
    assert track_geometry.fits(track_geometry.TrackGeometry("ATL", 1585, ellipse(), []), [(300.0, 0.0), (0.0, 200.0)])


def test_circuit_received_after_track_change_still_saved(viewer, monkeypatch):  # noqa: F811
    from tinypedal.userfile import track_geometry

    backend = viewer.backend
    track = backend.currentTrack
    answer_game(monkeypatch)
    backend._geometry_track = ""
    backend._geometry_tried.discard(track)
    backend.start_geometry(track)
    backend._track = "Other - Hyper"  # another track shown meanwhile
    backend.wait_jobs()
    backend._track = track
    assert track_geometry.load_geometry(cfg.path.telemetry, track) is not None  # saved, not asked again
    assert backend._geometry is None  # not applied to the track shown


def test_track_geometry_name_and_layout_versions(tmp_path):
    from tinypedal.userfile import track_geometry

    geometry = track_geometry.TrackGeometry("ATL", 1585, ellipse(), [], (1.0, 2.0), "Atlanta 1.0")
    track_geometry.save_geometry(str(tmp_path), "Atlanta - Hyper", geometry)
    assert track_geometry.load_geometry(str(tmp_path), "Atlanta - Hyper").name == "Atlanta 1.0"
    tracks = [{"id": "a", "shortName": "Atlanta 1.1", "sceneDesc": "ATL"}, {"id": "b", "shortName": "Atlanta 1.1 Event",
                                                                             "sceneDesc": "ATL"},
              {"id": "c", "shortName": "Sebring 1.0", "sceneDesc": "SEB"}, "bad"]
    assert track_geometry.layout_names(tracks, "ATL") == {"Atlanta 1.1", "Atlanta 1.1 Event"}
    far = [(5000.0, 5000.0)] * 5
    assert not track_geometry.fits(geometry, far) and track_geometry.fits(geometry, [])


# --- Placement across track (J2)
def test_recorded_game_placement_kept_measured_only_without(viewer, monkeypatch):  # noqa: F811
    from tinypedal.ui.lap_viewer import CHANNEL_MAP
    from tinypedal.userfile import track_geometry

    backend = viewer.backend
    monkeypatch.setattr(track_geometry, "rest_get", lambda host, port, resource, timeout=3: None)  # no game
    game_lap = save_game_lap(6, 71.2, BASE + 600, -2.0, -6.0)  # 2 m right of game center, right edge 6 m
    backend.refresh()
    wait_loaded(viewer)
    finish_limits(backend)
    assert backend.hasLimits
    backend.checked.add(game_lap)
    backend.load_laps()
    wait_loaded(viewer)
    backend.wait_jobs()
    lap = next(lap for lap in backend.data.laps if lap.key == game_lap)
    other = next(lap for lap in backend.data.laps if lap.key != game_lap)
    assert game_lap not in backend.data.placements and other.key in backend.data.placements  # measured: others only
    laterals = backend.data.series(CHANNEL_MAP["path_lateral"], lap)[1]
    assert laterals and all(value == pytest.approx(-2.0) for value in laterals)  # game values kept
    positions = backend.data.series(CHANNEL_MAP["track_position"], lap)[1]
    assert all(value == pytest.approx(-100 / 3, abs=0.1) for value in positions)
    assert backend.data.series(CHANNEL_MAP["track_position"], other)[1]  # measured between edges
    # No track edges: base line is a driving line, nothing measured (never distance to it as distance to center)
    backend._limits = None
    backend.update_placements()
    assert backend.data.placements == {}
    assert not any(backend.data.series(CHANNEL_MAP["path_lateral"], other)[1])  # recorded zeros (not measured)


# --- Official corner deltas (J26)
def test_official_corner_won_by_corner_covering_it(viewer):  # noqa: F811
    from tinypedal.ui.lap_viewer import signed
    from tinypedal.userfile.track_corners import TrackCorner

    backend = viewer.backend
    backend._official = [TrackCorner("1", 300.0, 0.0, 0.0), TrackCorner("2", 1000.0, 10.0, 10.0)]
    backend._official_numbered = True
    near = Row(Corner(1, 380.0, 460.0, 420.0), 0.10)  # only near official corner 1, found first
    covering = Row(Corner(2, 250.0, 350.0, 300.0), -0.20)  # covers official corner 1
    far = Row(Corner(3, 1500.0, 1560.0, 1530.0), 0.05)  # no official corner within 200 m
    backend._corner_rows = [near, covering, far]
    points = backend.official_points()
    first = points[0]
    assert first["delta"] == signed(-0.20, 2) and first["row"] == 1  # covering corner wins
    assert points[1]["delta"] == "" and points[1]["row"] == -1
    own = {point["row"]: point for point in points[2:]}  # corners left get their own label at apex
    assert set(own) == {0, 2} and own[0]["delta"] == signed(0.10, 2) and own[2]["delta"] == signed(0.05, 2)
    assert own[2]["label"] == "—" and len({point["index"] for point in points}) == len(points)
    line = backend.reference_map_line()
    from tinypedal.ui.quick import lap_map

    assert (own[0]["x"], own[0]["y"]) == pytest.approx(lap_map.point_at(line, 420.0))


# --- Reference lap without positions (J27)
def colored_count(backend) -> int:
    """Vertices of colored map line"""
    from tinypedal.ui.quick.lines import VertexStore

    vertices = VertexStore.get(backend._map["colored"])
    return vertices.vertex_count if vertices is not None else 0


def test_reference_without_positions(viewer, monkeypatch):  # noqa: F811
    from tinypedal.userfile import track_geometry

    backend = viewer.backend
    reference = backend.data.reference
    assert len(backend.data.laps) == 2
    backend._line_cache[reference.key] = (reference.data, None)  # imported log without positions
    backend.rebuild_chart()
    assert len(backend._map_lines) == 1 and backend.reference_map_line() is None
    assert not any(line["reference"] for line in backend._map["lines"])  # compared lap not taken for reference
    road = backend._map_lines[0][0]
    assert backend.mapPick(road.xs[40], road.ys[40], 20.0) == -1.0  # nothing at reference distances
    assert backend.map_sector_labels() == [] and backend.mapBounds(0.0, 500.0) == []
    backend.setPinned(500.0)
    assert backend.mapPin == {}
    backend.setMapMode("gain")  # compared lap colored by time gain
    assert colored_count(backend) > 0
    backend.setMapMode("speed")  # reference lap colors need a reference line
    assert colored_count(backend) == 0
    # Official circuit stands for reference lap line (distances scaled to reference lap)
    backend._geometry = track_geometry.TrackGeometry("ATL", 1585, ellipse(), [], (300.0, 0.0), "Atlanta 1.0")
    backend._line_cache[reference.key] = (reference.data, None)
    backend.rebuild_chart()
    line = backend.reference_map_line()
    assert line is backend._road and backend._corner_rows
    assert backend.mapPick(line.xs[40], line.ys[40], 20.0) == pytest.approx(backend.data.x_at_distance(
        line.distances[40]), abs=1.0)
    assert len(backend.map_corner_points()) == len(backend._corner_rows)
    assert colored_count(backend) > 0  # speed of reference lap along circuit
    assert backend.mapPin
    backend.clearPinned()
    backend.setMapMode("laps")


# --- Le Mans corners (J28)
def test_le_mans_esses_and_indianapolis_on_their_bends():
    from tinypedal.userfile import track_corners

    length = 13624.0
    # Bends of a recorded Le Mans lap (apexes found by track_corners.bends), kinks before Esses & Indianapolis
    bends = (615, 900, 1105, 1500, 1590, 1890, 4130, 6075, 7730, 9645, 9830, 10155, 11780, 12400, 13330)
    step = 5.0
    heading, x, y = 0.0, 0.0, 0.0
    distances, xs, ys = [0.0], [0.0], [0.0]
    for index in range(1, int(length / step) + 1):
        distance = index * step
        heading += sum((0.25 if bend in (1105, 9645) else 0.5) / 30 * step
                       for bend in bends if abs(distance - bend) <= 15)
        x, y = x + math.cos(heading) * step, y + math.sin(heading) * step
        distances.append(distance)
        xs.append(x)
        ys.append(y)
    corners, numbered = track_corners.track_corners("Circuit de la Sarthe", distances, xs, ys)
    placed = {corner.label: corner.distance for corner in corners}
    assert not numbered
    assert placed["Forest Esses"] == pytest.approx(1500, abs=15)  # not the kink near the Dunlop bridge
    assert placed["Indianapolis"] == pytest.approx(9830, abs=15)  # not the kink before it
    assert placed["Dunlop Chicane"] == pytest.approx(900, abs=15) and placed["Arnage"] == pytest.approx(10155, abs=15)


# --- Corner table (J42, J45, J46)
def test_corner_table_sums_and_ideal_gap(viewer, monkeypatch):  # noqa: F811
    from tinypedal.ui.quick import lap_corners
    from tinypedal.userfile.telemetry_lap import LapData

    backend = viewer.backend
    reference = backend.data.reference.data
    compared = backend.compared_lap().data
    assert backend._corner_rows and any(row["kind"] == "total" for row in backend._corners)
    assert backend.sums_comparable(reference, compared)
    assert not backend.sums_comparable(reference, LapData("stub", {"distance": [0.0, 150.0]}))  # stub lap
    monkeypatch.setattr(lap_corners, "total_lap_time", lambda lap: 100.0)  # game timed lap time
    backend._corner_rows = [row._replace(compared=None) for row in backend._corner_rows]  # no compared stats
    backend.build_corners()
    kinds = [row["kind"] for row in backend._corners]
    assert "sum" not in kinds and "total" not in kinds
    ideal = next(row for row in backend._corners if row["kind"] == "ideal")
    assert ideal["bar"] == pytest.approx(backend._ideal.time - 100.0)  # same lap time as ideal lap & Total row


def test_compared_lap_change_recolors_corner_mode(viewer, monkeypatch):  # noqa: F811
    backend = viewer.backend
    backend.setMapMode("corners")
    built = []
    monkeypatch.setattr(backend, "build_colored_line", lambda scale: built.append(scale))
    backend.setCompareKey("another lap")
    assert built
    monkeypatch.undo()
    backend.setMapMode("laps")


# --- Cursor trails & picking (J54, J59)
def test_trail_band_same_shape_as_trail():
    import struct

    from PySide6.QtGui import QColor

    from tinypedal.ui.quick import lap_map
    from tinypedal.ui.quick.lines import COLORED_VERTEX, colored_band, normals

    count = 400
    distances = [index * 1.0 for index in range(count)]
    line = lap_map.MapLine(distances, [100 * math.cos(d / 100) for d in distances],
                           [100 * math.sin(d / 100) for d in distances])
    color = QColor(200, 100, 50)
    xs, ys, alphas = lap_map.trail(line, 100.5, 250.5)
    old = colored_band(xs, ys, [color] * len(xs), 2.0, alphas)
    new = lap_map.trail_band(line, normals(line.xs, line.ys), 100.5, 250.5, (200, 100, 50), 2.0)
    assert new.vertex_count == old.vertex_count and new.colored
    data = bytes(new.data)
    for index in range(new.vertex_count):
        x, y, *rgba = COLORED_VERTEX.unpack_from(data, index * COLORED_VERTEX.size)
        old_x, old_y, *old_rgba = COLORED_VERTEX.unpack_from(old.data, index * COLORED_VERTEX.size)
        assert (x, y) == pytest.approx((old_x, old_y), abs=0.05)
        assert all(abs(first - second) <= 6 for first, second in zip(rgba, old_rgba))  # fading in toward end
    thinned = lap_map.trail_band(line, normals(line.xs, line.ys), 100.5, 250.5, (200, 100, 50), 2.0, min_gap=5.0)
    assert thinned.vertex_count < new.vertex_count / 3  # zoomed out: about a point per pixel
    assert lap_map.trail_band(line, normals(line.xs, line.ys), 50.0, 50.0, (0, 0, 0), 1.0).vertex_count == 0
    assert struct.calcsize("<ff4B") == COLORED_VERTEX.size


def test_line_grid_nearest_same_as_scan():
    from tinypedal.ui.quick import lap_map

    count = 3000
    distances = [index * 4.0 for index in range(count)]
    line = lap_map.MapLine(distances, [1500 * math.cos(d / 1900) + 200 * math.sin(d / 90) for d in distances],
                           [900 * math.sin(d / 1900) for d in distances])
    grid = lap_map.LineGrid(line)
    rng = random.Random(4)

    def scan(x, y, radius):
        best, found = radius * radius, -1
        for index, (px, py) in enumerate(zip(line.xs, line.ys)):
            gap = (px - x) ** 2 + (py - y) ** 2
            if gap < best:
                best, found = gap, index
        return found

    for _ in range(200):
        x, y = rng.uniform(-2500, 2500), rng.uniform(-1500, 1500)
        radius = rng.choice((5.0, 30.0, 300.0, 3000.0, 20000.0))
        found = grid.nearest(x, y, radius)
        expected = scan(x, y, radius)
        if expected < 0:
            assert found == -1
        else:  # same distance (ties may pick another point)
            assert math.dist((line.xs[found], line.ys[found]), (x, y)) == pytest.approx(
                math.dist((line.xs[expected], line.ys[expected]), (x, y)))
    assert lap_map.LineGrid(lap_map.MapLine([], [], [])).nearest(0.0, 0.0, 100.0) == -1
