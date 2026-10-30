"""Track map widget: recorded map with sectors, cars, safety car, pit out prediction, official circuit shape, no map"""

import math

import pytest
from PySide6.QtCore import QTimerEvent
from PySide6.QtGui import QColor

from neopedal.module_info import NO_TRACK_MAP, TrackMap, minfo
from neopedal.setting import cfg
from tests.test_list_widgets import visible_pixels
from tests.test_readers import lmu_api
from tests.test_widget_benchmark import fill_field

NODES = 200
LENGTH = 4000.0


@pytest.fixture
def track(ui_env, bundled_fonts, monkeypatch):
    """Recorded oval map, 20 cars on it, best lap delta data, API reader on in-memory shared memory"""
    from neopedal.api_control import api

    saved = (minfo.vehicles.dataSet, minfo.vehicles.totalVehicles, minfo.vehicles.playerIndex)
    mapping, delta = minfo.mapping, minfo.delta
    saved_map = (mapping.trackMap, mapping.pitEntryPosition, mapping.pitExitPosition, delta.deltaBestData,
                 delta.lapTimePace)
    coords = tuple((600 * math.cos(i / NODES * math.tau), 350 * math.sin(i / NODES * math.tau)) for i in range(NODES))
    mapping.trackMap = TrackMap(coords, tuple((i / NODES * LENGTH, 5 * math.sin(i / 20)) for i in range(NODES)),
                                (66, 133), 1.0)
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
    (mapping.trackMap, mapping.pitEntryPosition, mapping.pitExitPosition, delta.deltaBestData,
     delta.lapTimePace) = saved_map


def render(**options):
    from neopedal.widget.track_map import Realtime

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


@pytest.mark.parametrize("name", ["track_map", "_modern.track_map"])
def test_no_map_text_instead_of_circle(track, name):
    """No track map yet: a line of text, no made-up circle with cars placed by lap progress"""
    from importlib import import_module

    minfo.mapping.trackMap = TrackMap(lastModified=2.0)
    cfg.user.setting["track_map"].update(show_vehicle_class_standings=True, show_background=False)
    widget = import_module(f"neopedal.widget.{name}").Realtime(cfg, "track_map")
    try:
        widget.timerEvent(QTimerEvent(0))
        assert widget.map_scaled is None
        assert widget.vehicle_positions() == ()  # no car drawn
        assert widget.no_map_text() == "Track map after one lap"
        image = widget.grab().toImage()
        blank = image.pixel(0, 0)
        drawn = sum(1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
                    if image.pixel(x, y) != blank)
        assert 0 < drawn < 1500  # text only (circle road & 20 cars: far more)
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("name", ["track_map", "_modern.track_map", "navigation", "_modern.navigation",
                                  "elevation", "_modern.elevation"])
def test_official_circuit_shape_without_start_and_sectors(track, name):
    """Official circuit before start line & sector lines known (no distances, no sectors): map drawn, no line"""
    from importlib import import_module

    shape = minfo.mapping.trackMap.coordinates
    minfo.mapping.trackMap = TrackMap(shape, None, None, 3.0)
    widget_name = name.rsplit(".", 1)[-1]
    cfg.user.setting[widget_name].update(show_start_line=True, show_sector_line=True)
    widget = import_module(f"neopedal.widget.{name}").Realtime(cfg, widget_name)
    try:
        widget.timerEvent(QTimerEvent(0))
        widget.grab()
        assert widget.track_map.coordinates == shape
        if widget_name == "track_map":
            assert widget.map_scaled and widget.car_positions  # cars placed by world position
            assert widget.update_safetycar() is None and not widget.update_predictions()  # need distances
        if widget_name == "navigation":
            assert widget.sfinish_path is None and widget.sector_path is None
    finally:
        widget.deleteLater()


def test_map_drawn_is_one_snapshot(track):
    """Map published while overlay draws: overlay keeps coordinates & sectors of the map it took"""
    from neopedal.widget.track_map import Realtime

    widget = Realtime(cfg, "track_map")
    try:
        widget.timerEvent(QTimerEvent(0))
        drawn = widget.track_map
        minfo.mapping.trackMap = TrackMap(drawn.coordinates[:50], drawn.elevations[:50], (10, 20), 9.0)
        assert widget.track_map is drawn and widget.track_map.sectors == (66, 133)  # until next update
        widget.timerEvent(QTimerEvent(0))
        assert widget.track_map.sectors == (10, 20) and len(widget.map_scaled) == 50
    finally:
        widget.deleteLater()


def test_open_map_not_closed(track):
    minfo.mapping.trackMap = minfo.mapping.trackMap._replace(  # point to point stage
        coordinates=tuple((i * 10.0, 0.5 * i) for i in range(NODES)))
    widget, _ = render()
    assert not widget.circular_map


@pytest.mark.parametrize("name", ["track_map", "elevation"])
def test_sector_index_out_of_map_skipped(track, name):
    """Sector index past last node (edited map file, or file of another layout): map still drawn, line skipped"""
    from importlib import import_module

    minfo.mapping.trackMap = minfo.mapping.trackMap._replace(sectors=(66, NODES + 50))
    wcfg = cfg.user.setting[name]
    wcfg.update(show_sector_line=True, show_start_line=True)
    widget = import_module(f"neopedal.widget.{name}").Realtime(cfg, name)
    try:
        widget.timerEvent(QTimerEvent(0))  # raised IndexError (map image left half drawn)
        assert visible_pixels(widget.grab().toImage()) > 100
    finally:
        widget.deleteLater()


def test_track_orientation_added_to_display_orientation(track, monkeypatch):
    """Orient column of track info editor turns this track's map, on top of display_orientation"""
    from neopedal.widget.track_map import Realtime

    monkeypatch.setattr(minfo.mapping, "orientation", 0.0)
    cfg.user.setting["track_map"].update(display_orientation=30)
    widget = Realtime(cfg, "track_map")
    try:
        widget.timerEvent(QTimerEvent(0))
        assert widget.map_orient == pytest.approx(math.radians(30))
        assert not widget.map_changed(minfo.mapping.lastModified)  # same map, same orientation
        minfo.mapping.orientation = 300.0  # edited in track info editor: map drawn again at once
        widget.timerEvent(QTimerEvent(0))
        assert widget.map_orient == pytest.approx(math.radians(330))
        assert widget.map_changed(NO_TRACK_MAP.lastModified)  # no map: track orientation ignored
        assert widget.last_orientation == 0.0
    finally:
        widget.deleteLater()
