"""Corner by corner lap comparison tests"""

from itertools import pairwise

import pytest

from tinypedal.userfile.corner_analysis import compare_corners, corner_stats, find_corners, smooth
from tinypedal.userfile.telemetry_lap import LapData

# Track profile: (distance, speed km/h) points, straight then 2 corners then straight
PROFILE = ((0, 250), (400, 250), (500, 100), (700, 220), (800, 220), (900, 150), (1100, 240), (1500, 240))


def speed_at(distance: float, profile=PROFILE) -> float:
    for (d0, s0), (d1, s1) in pairwise(profile):
        if d0 <= distance <= d1:
            return s0 + (s1 - s0) * (distance - d0) / (d1 - d0)
    return profile[-1][1]


def make_lap(profile=PROFILE, brake_offset=0.0, throttle_offset=0.0, step=2.0) -> LapData:
    """Lap driven at profile speed: braking where speed drops, full throttle where it rises"""
    distances = [index * step for index in range(int(1500 / step) + 1)]
    speeds = [speed_at(distance, profile) for distance in distances]
    lap_time, times = 0.0, []
    for index in range(len(distances)):
        if index:
            lap_time += step / ((speeds[index] + speeds[index - 1]) / 2 / 3.6)
        times.append(lap_time)
    braking = [speed_at(distance + 2 - brake_offset, profile) < speed_at(distance - brake_offset, profile)
               for distance in distances]
    throttle = [1.0 if speed_at(distance + 2 - throttle_offset, profile) >= speed_at(distance - throttle_offset, profile)
                else 0.0 for distance in distances]
    return LapData("lap", {
        "distance": distances,
        "lap_time": times,
        "speed_kph": speeds,
        "brake": [1.0 if value else 0.0 for value in braking],
        "throttle": throttle,
    })


def test_find_corners():
    corners = find_corners(make_lap())
    assert [corner.number for corner in corners] == [1, 2]
    assert corners[0].apex == pytest.approx(500, abs=10) and corners[1].apex == pytest.approx(900, abs=10)
    assert corners[0].start == pytest.approx(400, abs=15) and corners[0].end == pytest.approx(750, abs=60)
    assert corners[0].end <= corners[1].start == pytest.approx(800, abs=15)  # straight between them left out
    assert corners[1].end == pytest.approx(1100, abs=15)


def test_small_speed_changes_are_not_corners():
    wavy = ((0, 250), (300, 245), (600, 252), (900, 246), (1500, 250))  # under 10 km/h hysteresis
    assert find_corners(make_lap(wavy)) == []
    assert find_corners(LapData("x", {"distance": [0.0, 10.0]})) == []  # no speed recorded


def test_corner_stats():
    lap = make_lap()
    corner = find_corners(lap)[0]
    stats = corner_stats(lap, corner)
    assert stats.min_speed == pytest.approx(100, abs=3)
    assert stats.apex == pytest.approx(500, abs=10)
    assert stats.brake_point == pytest.approx(400, abs=15)
    assert stats.throttle_point == pytest.approx(500, abs=15)
    assert stats.time > 0


def test_compare_corners_time_and_points():
    reference = make_lap()
    slower = ((0, 250), (400, 250), (500, 90), (700, 220), (800, 220), (900, 150), (1100, 240), (1500, 240))
    compared = make_lap(slower, brake_offset=-20)  # brakes earlier, slower in corner 1
    rows = compare_corners(reference, compared)
    assert len(rows) == 2
    assert rows[0].time_delta > 0.05  # time lost in corner 1
    assert rows[1].time_delta == pytest.approx(0, abs=0.01)
    assert rows[0].compared.min_speed == pytest.approx(90, abs=3)
    assert rows[0].compared.brake_point < rows[0].reference.brake_point  # earlier braking
    total = sum(row.time_delta for row in rows)
    assert total == pytest.approx(compared.lap_time - reference.lap_time, abs=0.02)  # straights equal
    assert compare_corners(reference)[0].compared is None and compare_corners(reference)[0].time_delta is None


def test_smooth():
    assert smooth([0, 10, 0, 10, 0], 3) == pytest.approx([5, 10 / 3, 20 / 3, 10 / 3, 5])


def test_lap_viewer_corner_tab(ui_env, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent

    from tinypedal.ui import lap_viewer

    viewer = lap_viewer.LapViewer(None)
    try:
        reference = lap_viewer.PlotLap("a", "a", make_lap(), lap_viewer.COLOR_A)
        slower = make_lap(((0, 250), (400, 250), (500, 90), (700, 220), (800, 220), (900, 150), (1100, 240),
                           (1500, 240)))
        compared = lap_viewer.PlotLap("b", "b", slower, lap_viewer.COLOR_B)
        viewer.plot.set_laps([reference, compared], "a")
        viewer.corners.set_laps(viewer.plot.lap_a, viewer.plot.lap_b)
        table = viewer.corners.table
        assert table.topLevelItemCount() == 2
        assert table.topLevelItem(0).text(1).startswith("+")  # time lost
        assert "100 / 90" in table.topLevelItem(0).text(2)
        viewer.corners.select_row(table.topLevelItem(1))
        corner = viewer.corners.rows[1].corner
        assert (viewer.plot.view_start, viewer.plot.view_end) == pytest.approx((corner.start, corner.end))
        viewer.corners.set_laps(viewer.plot.lap_a, None)  # reference only: its own values
        assert table.topLevelItem(0).text(2) == "100"
        viewer.corners.set_laps(None, None)
        assert table.topLevelItemCount() == 0
    finally:
        viewer.close()
        viewer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
