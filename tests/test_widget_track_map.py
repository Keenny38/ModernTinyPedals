"""Track map widget: recorded map with sectors, cars, safety car, pit out prediction, temporary circle map"""

import math

import pytest
from PySide6.QtCore import QTimerEvent
from PySide6.QtGui import QColor

from tests.test_list_widgets import visible_pixels
from tests.test_readers import lmu_api
from tests.test_widget_benchmark import fill_field
from tinypedal.module_info import minfo
from tinypedal.setting import cfg

NODES = 200
LENGTH = 4000.0


@pytest.fixture
def track(ui_env, monkeypatch):
    """Recorded oval map, 20 cars on it, best lap delta data, API reader on in-memory shared memory"""
    from tinypedal.api_control import api

    saved = (minfo.vehicles.dataSet, minfo.vehicles.totalVehicles, minfo.vehicles.playerIndex)
    mapping, delta = minfo.mapping, minfo.delta
    saved_map = (mapping.coordinates, mapping.elevations, mapping.sectors, mapping.lastModified,
                 mapping.pitEntryPosition, mapping.pitExitPosition, delta.deltaBestData, delta.lapTimePace)
    coords = tuple((600 * math.cos(i / NODES * math.tau), 350 * math.sin(i / NODES * math.tau)) for i in range(NODES))
    mapping.coordinates = coords
    mapping.elevations = tuple((i / NODES * LENGTH, 5 * math.sin(i / 20)) for i in range(NODES))
    mapping.sectors = (66, 133)
    mapping.lastModified = 1.0
    mapping.pitEntryPosition = LENGTH * 0.95
    mapping.pitExitPosition = LENGTH * 0.05
    delta.deltaBestData = tuple((i / 100 * LENGTH, i / 100 * 90.0) for i in range(101))
    delta.lapTimePace = 91.0
    fill_field(20)
    for index, data in enumerate(minfo.vehicles.dataSet):  # cars spread on the map
        data.worldPositionX, data.worldPositionY = coords[index * 9 % NODES]
        data.isLapped = (index % 3) - 1
        data.isYellow = index == 5
        data.inPit = int(index == 7)
    sim, shared = lmu_api()
    monkeypatch.setattr(api, "_api", sim)
    monkeypatch.setattr(api, "read", sim.reader())
    yield shared
    minfo.vehicles.dataSet, minfo.vehicles.totalVehicles, minfo.vehicles.playerIndex = saved
    (mapping.coordinates, mapping.elevations, mapping.sectors, mapping.lastModified,
     mapping.pitEntryPosition, mapping.pitExitPosition, delta.deltaBestData, delta.lapTimePace) = saved_map


def render(**options):
    from tinypedal.widget.track_map import Realtime

    wcfg = cfg.user.setting["track_map"]
    wcfg.update(options)
    widget = Realtime(cfg, "track_map")
    try:
        widget.timerEvent(QTimerEvent(0))
        return widget, widget.grab().toImage()
    finally:
        widget.deleteLater()


def colors(image) -> set[str]:
    return {QColor(image.pixel(x, y)).name() for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
            if QColor(image.pixel(x, y)).alpha() > 0}


def test_recorded_map_with_cars(track):
    widget, image = render(display_orientation=0, enable_multi_class_styling=False)
    assert widget.map_scaled and widget.circular_map  # closed loop map
    assert visible_pixels(image) > 100
    assert any(QColor(name).red() > 220 and QColor(name).green() < 120 and QColor(name).blue() < 100
               for name in colors(image))  # player car (red) drawn


@pytest.mark.parametrize("options", [
    {"display_orientation": 90, "show_vehicle_class_standings": True, "show_proximity_circle": True},
    {"enable_multi_class_styling": True, "show_custom_player_color_in_multi_class": True,
     "show_lap_difference_outline": True},
    {"show_background": True, "display_detail_level": 5},
])
def test_map_options(track, options):
    _, image = render(**options)
    assert visible_pixels(image) > 100


def test_safety_car_and_pitout_prediction(track):
    track.scoring.scoringInfo.mSession = 10  # race
    player = minfo.vehicles.dataSet[minfo.vehicles.playerIndex]
    player.inPit = 1
    player.pitTimer.elapsed = 12.0
    for auto in (False, True):
        widget, image = render(show_safety_car=True, show_pitout_prediction=True, show_pitstop_duration=True,
                               enable_fixed_pitout_prediction=auto, enable_auto_pitout_prediction=auto)
        assert visible_pixels(image) > 100
        times = list(widget.get_target_pit_time(20.0, 12.0, True))
        assert times and all(time > 12.0 for time, _ in times)


def test_temporary_circle_map_without_recorded_map(track):
    minfo.mapping.coordinates = None
    widget, image = render(show_vehicle_class_standings=True)
    assert widget.map_scaled is None
    assert visible_pixels(image) > 50


def test_open_map_not_closed(track):
    minfo.mapping.coordinates = tuple((i * 10.0, 0.5 * i) for i in range(NODES))  # point to point stage
    widget, _ = render()
    assert not widget.circular_map
