"""Track map: official circuit of game placed as map (start & sector lines), recording kept through stalls"""

import math
from itertools import pairwise

import pytest

from neopedal.module import module_mapping
from neopedal.module_info import MappingInfo
from neopedal.userfile.track_map import load_track_map_file
from neopedal.userfile.track_map_official import MAX_OFFSET, CircuitPath, OfficialMap
from tests.test_module_mapping_stats_notes import finish_lap, tele  # noqa: F401  (fixture)

LE_MANS = 13626.0  # meters


def oval(length: float, step: float = 5.0, reverse: bool = False) -> list[tuple[float, float, float]]:
    """Closed oval path of about length meters, a point every step meters (x, y, elevation)"""
    count = int(length / step)
    radius_x, radius_y = length / 5.0, length / 8.0
    points = [(radius_x * math.cos(index / count * math.tau), radius_y * math.sin(index / count * math.tau),
               10.0 * math.sin(index / count * math.tau * 3)) for index in range(count)]
    return points[::-1] if reverse else points


def along(path: CircuitPath, arc: float) -> tuple[float, float]:
    x, y, _ = path.point_at(arc)
    return x, y


# --- Official circuit placed as map
def test_start_line_placed_from_a_car_on_track():
    path = CircuitPath(oval(LE_MANS))
    official = OfficialMap.build(path.points, path.length * 1.02)  # game lap distance 2% longer than AI line
    assert official is not None and not official.placed
    start_arc = 1234.0
    for car_arc, distance in ((start_arc + 800.0, 816.0), (start_arc + 900.0, 918.0)):  # 100 m driven
        placed = official.sample(3, *along(path, car_arc), distance)
    assert placed and official.placed
    assert math.dist(official.coords[0], along(path, start_arc)) < 1.0  # node 0 at start line
    assert official.dists[0][0] == 0.0 and official.dists[-1][0] == pytest.approx(path.length * 1.02, abs=15.0)
    assert all(after[0] > before[0] for before, after in pairwise(official.dists))


def test_path_of_other_direction_turned():
    path = CircuitPath(oval(4000.0, reverse=True))  # game path drawn against driving direction
    official = OfficialMap.build(path.points, path.length)
    forward = CircuitPath(path.points[::-1])
    official.sample(0, *along(forward, 500.0), 500.0)
    assert official.sample(0, *along(forward, 600.0), 600.0)
    assert math.dist(official.coords[0], along(forward, 0.0)) < 1.0
    assert math.dist(official.coords[20], along(forward, official.dists[20][0])) < 1.0  # nodes in driving order


def test_cars_off_path_or_not_following_it_ignored(monkeypatch):
    path = CircuitPath(oval(4000.0))
    official = OfficialMap.build(path.points, path.length)
    x, y = along(path, 500.0)
    assert not official.sample(0, x * 1.1, y * 1.1, 500.0)  # pit lane or off track
    calls = []
    project = CircuitPath.project
    monkeypatch.setattr(CircuitPath, "project", lambda *args: calls.append(args) or project(*args))
    assert not official.sample(0, x * 1.1, y * 1.1, 500.0)  # stopped off path: not projected again
    assert not calls
    assert not official.sample(0, *along(path, 600.0), 600.0)  # back on path: first sample only
    assert len(calls) == 1
    monkeypatch.undo()
    assert not official.placed
    official.sample(0, *along(path, 500.0), 500.0)
    assert not official.sample(0, *along(path, 900.0), 600.0)  # cut: 400 m along path for 100 m of lap
    assert not official.placed
    assert path.project(x * 1.1, y * 1.1)[1] > MAX_OFFSET


def test_circuit_of_other_layout_or_too_short_not_used():
    points = oval(4000.0)
    assert OfficialMap.build(points, 5500.0) is None  # game track length far from path length
    assert OfficialMap.build(points[:10], 0.0) is None
    assert OfficialMap.build(None, 4000.0) is None
    assert OfficialMap.build(points, 0.0) is not None  # track length unknown: path length


def test_sector_lines_from_lap_distance():
    path = CircuitPath(oval(4000.0))
    official = OfficialMap.build(path.points, path.length)
    assert not official.sector_crossed(0, 1300.0)  # known before start line: kept
    assert official.sector_indexes() is None
    official.sample(0, *along(path, 100.0), 100.0)
    official.sample(0, *along(path, 200.0), 200.0)
    assert official.sector_crossed(1, 2700.0)
    first, second = official.sector_indexes()
    assert official.dists[first][0] <= 1300.0 < official.dists[first + 1][0]
    assert official.dists[second][0] <= 2700.0 < official.dists[second + 1][0]
    official.sector_distances = [2700.0, 1300.0]  # out of order
    assert official.sector_indexes() is None


@pytest.fixture
def official_recorder(tele, tmp_path, monkeypatch):  # noqa: F811
    """Recorder with official circuit of game (fetched at once instead of in a thread)"""
    path = CircuitPath(oval(4000.0))
    asked = []

    def fetch(track, length):
        asked.append((track, length))
        return path.points

    monkeypatch.setattr(module_mapping, "start_official_fetch", lambda job, track, length: [job(track, length)])
    tele.update({"timing.start": 0.0, "timing.last_laptime": -1.0, "lap.track_length": path.length,
                 "vehicle.total_vehicles": 1})
    output = MappingInfo()
    gen = module_mapping.record_track_map(output, f"{tmp_path.as_posix()}/", official=fetch)
    return gen, output, path, asked


def drive_official(values: dict, gen, path: CircuitPath, distance: float, sector: int = 0):
    values.update({"lap.distance": distance, "lap.sector_index": sector})
    values["vehicle.position_longitudinal"], values["vehicle.position_lateral"] = along(path, distance + 300.0)
    gen.send(1)


def test_official_circuit_shown_then_saved_as_track_map(official_recorder, tele, tmp_path):  # noqa: F811
    gen, output, path, asked = official_recorder
    gen.send(1)  # no map file: circuit asked to game, shape shown at once
    assert asked == [("SimTrack", path.length)]
    shown = output.trackMap
    assert len(shown.coordinates) == len(path.points) and not shown.start_known() and shown.sectors is None
    # A car drives 100 m: start line placed (start 300 m before car's lap distance 0 point)
    drive_official(tele, gen, path, 500.0)
    drive_official(tele, gen, path, 600.0)
    placed = output.trackMap
    assert placed.start_known() and placed.lastModified > shown.lastModified
    assert math.dist(placed.coordinates[0], along(path, 300.0)) < 1.0
    # Player crosses both sector lines: saved as track map, loaded from file next
    drive_official(tele, gen, path, 1300.0, 1)
    assert output.trackMap.sectors is None
    drive_official(tele, gen, path, 2700.0, 2)
    gen.send(1)
    coords, dists, sectors = load_track_map_file(f"{tmp_path.as_posix()}/", "SimTrack")
    assert coords and dists[sectors[0]][0] <= 1300.0 < dists[sectors[0] + 1][0]
    assert output.trackMap.sectors == sectors and output.trackMap.coordinates == coords


def test_official_circuit_kept_after_reset_and_not_asked_again(official_recorder, tele):  # noqa: F811
    gen, output, path, asked = official_recorder
    gen.send(1)
    drive_official(tele, gen, path, 500.0)
    drive_official(tele, gen, path, 600.0)
    placed = output.trackMap
    gen.send(2)  # vehicle reset (back to garage): map shown again, game not asked again
    assert len(asked) == 1
    assert output.trackMap.coordinates == placed.coordinates and output.trackMap.start_known()


def test_sector_line_crossed_in_pit_lane_ignored(official_recorder, tele):  # noqa: F811
    gen, output, path, _ = official_recorder
    gen.send(1)
    drive_official(tele, gen, path, 500.0)
    drive_official(tele, gen, path, 600.0)
    tele["vehicle.in_pits"] = True
    drive_official(tele, gen, path, 1300.0, 1)
    tele["vehicle.in_pits"] = False
    drive_official(tele, gen, path, 2700.0, 2)
    gen.send(1)
    assert output.trackMap.sectors is None  # first line not known: not saved yet


# --- Recording through stalls
def drive_timed(values: dict, gen, lap_start: float, samples: list[tuple[float, float]]):
    """Drive a lap through (lap distance, elapsed time) samples, sector lines at 1/3 & 2/3 of samples"""
    values["timing.start"] = lap_start
    total = len(samples)
    for index, (distance, elapsed) in enumerate(samples):
        values.update({
            "lap.distance": distance,
            "lap.sector_index": 0 if index < total / 3 else (1 if index < total * 2 / 3 else 2),
            "vehicle.position_longitudinal": distance,
            "vehicle.position_lateral": float(index % 7),
            "vehicle.position_vertical": 1.5,
            "timing.current_laptime": 0.5,
            "timing.elapsed": elapsed,
        })
        gen.send(1)


def le_mans_lap(start_time: float, stall_at: int | None = None, stall: float = 1.6) -> list[tuple[float, float]]:
    """Le Mans lap at 94 m/s (340 km/h), a sample every 0.1 s, one stall of app (no sample for stall seconds)"""
    samples = []
    elapsed = start_time
    distance = 0.0
    index = 0
    while distance < LE_MANS - 20:
        step = stall if index == stall_at else 0.1
        elapsed += step
        distance += 94.0 * step
        samples.append((distance, elapsed))
        index += 1
    return samples


@pytest.fixture
def recorder(tele, tmp_path):  # noqa: F811
    output = MappingInfo()
    gen = module_mapping.record_track_map(output, f"{tmp_path.as_posix()}/")
    tele.update({"timing.start": 0.0, "timing.last_laptime": -1.0, "lap.track_length": LE_MANS})
    gen.send(1)
    return gen, output


def test_lap_kept_after_150m_stall_at_le_mans(recorder, tele, tmp_path):  # noqa: F811
    """1.6 s without sample at 340 km/h (150 m): lap shown, not saved, next clean lap saved"""
    gen, output = recorder
    drive_timed(tele, gen, 10.0, le_mans_lap(10.0, stall_at=700))
    finish_lap(tele, gen, 300.0)
    shown = output.trackMap
    assert shown.coordinates and shown.start_known() and shown.sectors is not None
    gaps = [after[0] - before[0] for before, after in pairwise(shown.elevations)]
    assert max(gaps) == pytest.approx(150.4, abs=1.0)  # gap kept in lap
    assert not (tmp_path / "SimTrack.svg").exists()
    drive_timed(tele, gen, 300.0, le_mans_lap(300.0))
    finish_lap(tele, gen, 600.0)
    assert (tmp_path / "SimTrack.svg").exists()
    _, dists, _ = load_track_map_file(f"{tmp_path.as_posix()}/", "SimTrack")
    assert max(after[0] - before[0] for before, after in pairwise(dists)) < 20.0


def test_lap_with_fewer_gaps_replaces_shown_lap(recorder, tele):  # noqa: F811
    gen, output = recorder
    samples = le_mans_lap(10.0, stall_at=300)
    samples[900:] = [(distance + 150.0, elapsed + 1.6) for distance, elapsed in samples[900:]]  # second stall
    drive_timed(tele, gen, 10.0, [sample for sample in samples if sample[0] < LE_MANS - 20])
    finish_lap(tele, gen, 300.0)
    first = output.trackMap
    drive_timed(tele, gen, 300.0, le_mans_lap(300.0, stall_at=500, stall=3.0))  # one gap (282 m)
    finish_lap(tele, gen, 600.0)
    assert output.trackMap.lastModified > first.lastModified


def test_jump_faster_than_any_car_is_teleport(recorder, tele, tmp_path):  # noqa: F811
    """150 m in 0.1 s (back to garage, skipped part of lap): lap not recorded"""
    gen, output = recorder
    samples = le_mans_lap(10.0)
    samples[700:] = [(distance + 150.0, elapsed) for distance, elapsed in samples[700:]]
    drive_timed(tele, gen, 10.0, [sample for sample in samples if sample[0] < LE_MANS - 20])
    finish_lap(tele, gen, 300.0)
    assert output.trackMap.coordinates is None
    assert not (tmp_path / "SimTrack.svg").exists()


def test_gap_longer_than_max_node_gap_is_teleport(recorder, tele):  # noqa: F811
    gen, output = recorder
    drive_timed(tele, gen, 10.0, le_mans_lap(10.0, stall_at=700, stall=5.0))  # 470 m: farther than MAX_NODE_GAP
    finish_lap(tele, gen, 300.0)
    assert output.trackMap.coordinates is None


def test_lap_with_gap_shown_again_after_vehicle_reset(recorder, tele):  # noqa: F811
    gen, output = recorder
    drive_timed(tele, gen, 10.0, le_mans_lap(10.0, stall_at=700))
    finish_lap(tele, gen, 300.0)
    shown = output.trackMap
    gen.send(2)  # back to garage (vehicle reset)
    assert output.trackMap == shown
    tele["session.track_name"] = "OtherTrack"
    gen.send(3)  # other track: not shown
    assert output.trackMap.coordinates is None
