"""Game Replays map: cars on track moved along the track between game answers, with the playback clock"""

import pytest
from PySide6.QtCore import QCoreApplication

from tests.test_game_info import GAME_ANSWERS, answered, replays_page  # noqa: F401
from tinypedal.process.game_info import Standing
from tinypedal.ui.quick.track_path import TrackPath


def loop() -> TrackPath:
    return TrackPath([0, 100, 100, 0], [0, 0, 50, 50], True)  # rectangle, 300 m


def test_track_path_projection_wrap_and_points():
    path = loop()
    assert path.length == pytest.approx(300)
    s, gap, segment = path.project(50, 2)
    assert (s, gap, segment) == (pytest.approx(50), pytest.approx(2), 0)
    assert path.project(2, 40, hint=0)[0] == pytest.approx(260)  # far from hint: whole path searched
    assert path.delta(290, 10) == pytest.approx(20) and path.delta(10, 290) == pytest.approx(-20)  # shortest way
    assert path.point(310) == (pytest.approx(10), pytest.approx(0))  # wrapped
    assert path.point(275) == (pytest.approx(0), pytest.approx(25))  # closing segment
    line = TrackPath([0, 100], [0, 0], False)
    assert line.point(150) == (100, 0) and line.delta(90, 10) == -80  # open path: clamped, no wrap


def car(x, y, into_lap, in_pit=False, slot=7) -> Standing:
    return Standing(slot, 1, "A", "7", "GT3", "Car", "", 3, 100.0, 100.0, 0.0, 0, 0, in_pit, 0, "", False, False,
                    lap_start=1000.0, into_lap=into_lap, estimated=30.0, x=x, y=y)


def test_car_moves_along_track_with_measured_speed(replays_page):  # noqa: F811
    backend = replays_page.backend
    backend.track_path = TrackPath([0, 1000, 1000, 0], [0, 0, 500, 500], True)  # 3000 m
    backend._car_tracks.clear()
    first = backend.car_track(car(200, 10, 5.0))
    assert first["onTrack"] and first["pathS"] == pytest.approx(200) and first["sampleTime"] == 1005.0
    assert first["speed"] == pytest.approx(100.0) and first["correction"] == 0  # track length / estimated lap time
    assert backend.car_track(car(200, 10, 5.0)) == first  # same answer again: unchanged
    second = backend.car_track(car(360, 0, 7.0))  # 160 m in 2 s
    assert second["speed"] == pytest.approx((100.0 + 80.0) / 2)
    assert second["correction"] == pytest.approx(400 - 360)  # shown at 400 m (expected), eases to 360 m
    jump = backend.car_track(car(1000, 300, 8.0))  # seek: far from expected place
    assert jump["correction"] == 0 and jump["speed"] == pytest.approx(90.0)  # 940 m/s: not a speed
    assert not backend.car_track(car(1000, 300, 9.0, in_pit=True))["onTrack"]  # pit lane: glides to its position
    assert not backend.car_track(car(5000, 5000, 10.0))["onTrack"]  # off track
    backend.release()


def test_map_cars_moved_by_clock_on_page(replays_page):  # noqa: F811
    import copy

    answers = copy.deepcopy(GAME_ANSWERS)
    answers["/rest/watch/standings"][1].update(lapStartET=1700.0, timeIntoLap=40.0, estimatedLapTime=100.0)
    backend = replays_page.backend
    backend.setPanel(2)
    answered(replays_page, answers)
    replays_page.resize(1400, 860)
    replays_page.show()
    for _ in range(10):
        QCoreApplication.processEvents()
    row = next(row for row in backend.mapCars.rows if row["key"] == "7")
    assert row["onTrack"], row
    from tests.test_game_replays_perf import has_property

    view = replays_page.view
    panel = has_property(view, "hasPath")[0]
    assert panel.property("hasPath")
    cars = {item.property("key"): item for item in has_property(view, "trackPoint")}
    item = cars["7"]
    panel.setProperty("clock", row["sampleTime"])
    panel.setProperty("now", row["receivedMs"] + 1000)  # easing done
    start = (item.property("worldX"), item.property("worldY"))
    panel.setProperty("clock", row["sampleTime"] + 1.0)  # one second of playback later
    moved = (item.property("worldX"), item.property("worldY"))
    path = backend.track_path
    expected = path.point(row["pathS"] + row["speed"] * 1.0)
    assert moved != start
    assert moved == (pytest.approx(expected[0], abs=0.01), pytest.approx(expected[1], abs=0.01))
    assert not view.errors()
    backend.release()


class FakeVehicle:
    def __init__(self, cars):
        self.cars = cars  # (slot, x, z)

    def total_vehicles(self):
        return len(self.cars)

    def slot_id(self, index):
        return self.cars[index][0]

    def position_xyz(self, index):
        return self.cars[index][1], 0.0, self.cars[index][2]


class FakeReader:
    def __init__(self, cars):
        self.vehicle = FakeVehicle(cars)


def test_map_cars_follow_shared_memory_like_director(replays_page, monkeypatch):  # noqa: F811
    backend = replays_page.backend
    reader = FakeReader([(7, 120.0, -30.0), (99, 1.0, 1.0)])
    monkeypatch.setattr(type(backend), "reader", staticmethod(lambda: reader))
    backend.setPanel(2)
    answered(replays_page, GAME_ANSWERS)
    replays_page.resize(1400, 860)
    replays_page.show()
    for _ in range(10):
        QCoreApplication.processEvents()
    assert backend.live_wanted() and backend._live_timer.isActive()
    assert backend.mapLive["7"] == [120.0, 30.0]  # map y is -z, like the game trackmap
    from tests.test_game_replays_perf import has_property

    view = replays_page.view
    panel = has_property(view, "liveTracking")[0]
    assert panel.property("liveTracking")
    item = {item.property("key"): item for item in has_property(view, "trackPoint")}["7"]
    assert item.property("tracked") and item.property("trackPoint") is None  # not moved along track by guess
    reader.vehicle.cars = [(5, 1.0, 1.0)]  # shared memory of another session: not used
    backend.read_live_positions()
    assert backend.mapLive == {} and not panel.property("liveTracking")
    reader.vehicle.cars = [(7, 120.0, -30.0)]
    backend.read_live_positions()
    backend.setPanel(0)  # map hidden: no more reading
    assert not backend._live_timer.isActive() and backend.mapLive == {}
    backend.release()
    assert not backend._live_timer.isActive()
