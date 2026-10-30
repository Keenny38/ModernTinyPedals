"""Overlay audit 2026-10-29, group F: track map, elevation, heading, navigation, weather, weather forecast,
wind direction & black box (numbers of the audit report)"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, QTimerEvent

from neopedal.module import module_mapping
from neopedal.module_info import NO_TRACK_MAP, MappingInfo, TrackMap, minfo
from neopedal.setting import cfg
from neopedal.userfile.track_map import save_track_map_file
from tests.test_black_box_modern import new_widget
from tests.test_modern_graphic_widgets import oval, reader, render, update, widgets  # noqa: F401  (fixtures)
from tests.test_module_mapping_stats_notes import tele  # noqa: F401  (fixture)


# --- 95: map of another track with the same file time loaded, never the previous track's map kept
def test_track_map_of_other_track_with_same_file_time_loaded(tele, tmp_path):  # noqa: F811
    filepath = f"{tmp_path.as_posix()}/"
    save_track_map_file(filepath, "TrackA", "0 0 10 10", ((0.0, 0.0), (5.0, 5.0)), ((0.0, 0.0), (10.0, 1.0)),
                        (0, 1), decimals=1)
    save_track_map_file(filepath, "TrackB", "0 0 10 10", ((1.0, 1.0), (7.0, 3.0)), ((0.0, 0.0), (10.0, 1.0)),
                        (0, 1), decimals=1)
    stamp = os.path.getmtime(tmp_path / "TrackA.svg")
    os.utime(tmp_path / "TrackB.svg", (stamp, stamp))  # unpacked map pack: same file times
    output = MappingInfo()
    gen = module_mapping.record_track_map(output, filepath)
    tele["session.track_name"] = "TrackA"
    gen.send(1)
    assert output.coordinates == ((0.0, 0.0), (5.0, 5.0))
    tele["session.track_name"] = "TrackB"
    gen.send(2)
    assert output.coordinates == ((1.0, 1.0), (7.0, 3.0))
    gen.send(3)  # same track again: map kept, not loaded again
    assert output.coordinates == ((1.0, 1.0), (7.0, 3.0))


# --- 96: track info editor saves then reloads modules: new mapping module reads edited orientation while driving
def test_track_orientation_edited_read_by_restarted_mapping_module(tele, ui_env):  # noqa: F811
    output = MappingInfo()
    gen = module_mapping.record_track_info(output)
    gen.send(1)
    assert output.orientation == 0.0
    cfg.user.tracks["SimTrack"] = {**cfg.user.tracks.get("SimTrack", {}), "orientation": 90.0}  # editor applied
    restarted = module_mapping.record_track_info(output)
    restarted.send(1)
    assert output.orientation == 90.0


# --- 97: track map cars key built again only with new vehicles data (or pixel ratio, nearby cars)
@pytest.mark.parametrize("modern", [True, False])
def test_track_map_cars_key_only_built_on_new_vehicles_data(widgets, oval, monkeypatch, modern):  # noqa: F811
    widget = widgets("track_map", modern=modern)
    built = []
    original = type(widget).vehicles_key

    def spy(self, positions, ratio):
        built.append(1)
        return original(self, positions, ratio)

    monkeypatch.setattr(type(widget), "vehicles_key", spy)
    minfo.vehicles.dataSetVersion = 1
    for _ in range(3):
        widget.timerEvent(QTimerEvent(0))
    assert len(built) == 1
    minfo.vehicles.dataSetVersion = 2
    widget.timerEvent(QTimerEvent(0))
    assert len(built) == 2


# --- 98: without map, map drawn once at creation, not again by first update
@pytest.mark.parametrize("name, method", [
    ("track_map", "create_map_path"), ("navigation", "create_map_path"), ("elevation", "create_elevation_path")])
@pytest.mark.parametrize("modern", [True, False])
def test_no_map_drawn_once_at_start(widgets, monkeypatch, name, method, modern):  # noqa: F811
    if name == "elevation" and modern:
        pytest.skip("modern elevation builds its profile on first update only")
    monkeypatch.setattr(minfo.mapping, "trackMap", NO_TRACK_MAP)
    module = __import__(f"neopedal.widget.{name}", fromlist=["Realtime"])
    owner = module.TrackMapMixin if name == "track_map" else (
        module.NavigationMixin if name == "navigation" else module.Realtime)
    calls = []
    original = getattr(owner, method)

    def spy(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(owner, method, spy)
    widget = widgets(name, modern=modern)
    widget.timerEvent(QTimerEvent(0))
    widget.timerEvent(QTimerEvent(0))
    assert len(calls) == 1


# --- 99 & 100: classic elevation reading repainted at standstill, car mark on profile scale
@pytest.fixture
def profile(monkeypatch):
    """Map whose first node is 100 m past start line, last 100 m before it (4000 m lap)"""
    nodes = 39
    monkeypatch.setattr(minfo.mapping, "trackMap", TrackMap(
        tuple((float(i), float(i % 5)) for i in range(nodes)),
        tuple((100.0 + i * 100.0, float(i % 7)) for i in range(nodes)), (12, 25), 5.0))


def test_classic_elevation_reading_repainted_at_standstill(widgets, profile, monkeypatch):  # noqa: F811
    widget = widgets("elevation", modern=False, show_elevation_reading=True)
    reader(monkeypatch, "lap", "distance", 1000.0)
    reader(monkeypatch, "vehicle", "position_vertical", 12.0)
    widget.timerEvent(None)
    first = widget.reading_text
    repaints = []
    monkeypatch.setattr(widget, "update", lambda *args: repaints.append(1))
    reader(monkeypatch, "vehicle", "position_vertical", 14.5)  # car stopped, elevation reading changed
    widget.timerEvent(None)
    assert widget.reading_text != first and "14.5" in widget.reading_text
    assert repaints == [1]
    widget.timerEvent(None)
    assert repaints == [1]


@pytest.mark.parametrize("modern", [True, False])
def test_elevation_mark_on_profile_scale(widgets, profile, monkeypatch, modern):  # noqa: F811
    widget = widgets("elevation", modern=modern)
    reader(monkeypatch, "lap", "progress", 100.0 / 4000.0)
    reader(monkeypatch, "lap", "distance", 100.0)  # first profile node: chart left (lap progress is not)
    widget.timerEvent(None)
    if modern:
        assert widget.state[0] == pytest.approx(widget.plot.left(), abs=0.06)  # state rounded to 0.1
    else:
        assert widget.veh_pos == 0
    reader(monkeypatch, "lap", "distance", 3950.0)  # past last node: chart right
    widget.timerEvent(None)
    if modern:
        assert widget.state[0] == pytest.approx(widget.plot.right(), abs=0.06)
    else:
        assert widget.veh_pos == widget.display_width


def test_profile_x_limits():
    from neopedal.widget.elevation import profile_x

    assert profile_x(float("nan"), 100.0, 0.1, 380.0) == 0.0
    assert profile_x(-50.0, 100.0, 0.1, 380.0) == 0.0
    assert profile_x(2000.0, 100.0, 0.1, 380.0) == pytest.approx(190.0)
    assert profile_x(float("inf"), 100.0, 0.1, 380.0) == 380.0


# --- 101: first heading reading never points from world origin
def test_heading_first_reading_without_travel_direction(ui_env, monkeypatch):
    from neopedal.widget.heading import HeadingMixin

    reader(monkeypatch, "vehicle", "speed", 30.0)
    reader(monkeypatch, "vehicle", "orientation_yaw_radians", 0.0)
    reader(monkeypatch, "vehicle", "position_longitudinal", 1000.0)
    reader(monkeypatch, "vehicle", "position_lateral", 500.0)
    heading = SimpleNamespace()
    HeadingMixin.setup_heading(heading)
    HeadingMixin.read_heading(heading)
    assert heading.yaw_angle == 0.0 and heading.last_pos == (1000.0, 500.0)
    reader(monkeypatch, "vehicle", "position_lateral", 501.0)  # driving along lateral axis
    HeadingMixin.read_heading(heading)
    assert heading.last_pos == (1000.0, 501.0)
    assert abs(HeadingMixin.display_yaw_angle(heading, heading.yaw_angle)) < 180


# --- 102: navigation draws road around car only, same picture as whole map
@pytest.mark.parametrize("modern", [True, False])
def test_navigation_draws_road_around_car_same_picture(widgets, oval, monkeypatch, modern):  # noqa: F811
    reader(monkeypatch, "vehicle", "position_longitudinal", 600.0)
    reader(monkeypatch, "vehicle", "position_lateral", 0.0)
    reader(monkeypatch, "vehicle", "orientation_yaw_radians", 0.6)
    culled = widgets("navigation", modern=modern)
    whole = widgets("navigation", modern=modern)
    whole.view_map_path = lambda: whole.map_path  # whole map drawn, as before
    image = update(culled)
    assert image == update(whole)
    path = culled.view_map_path()
    assert path is not culled.map_path and 0 < path.elementCount() < culled.map_path.elementCount() / 2
    # Built again only once car moved away from where built
    reader(monkeypatch, "vehicle", "position_longitudinal", 599.0)
    assert culled.view_map_path() is path
    reader(monkeypatch, "vehicle", "position_longitudinal", -600.0)
    rebuilt = culled.view_map_path()
    assert rebuilt is not path
    assert update(culled) == update(whole)


def test_map_segments_near():
    from neopedal.widget.navigation import map_segments_near

    square = ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0))
    assert map_segments_near(square, True, 50.0, 50.0, 1000.0) is None  # all near: whole map
    # Long segment passing near center, both its nodes far: kept
    path = map_segments_near(((-500.0, 0.0), (500.0, 0.0), (500.0, 900.0)), False, 0.0, 10.0, 50.0)
    assert path is not None and path.elementCount() == 2
    # Closed loop: run across first node kept in one piece (closing segment & first segment joined)
    path = map_segments_near(square, True, 0.0, 0.0, 30.0)
    points = [QPointF(path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount())]
    assert points == [QPointF(0.0, 100.0), QPointF(0.0, 0.0), QPointF(100.0, 0.0)]


# --- 103: view radius is the distance across the view (documented, users' views kept)
def test_navigation_view_radius_spans_view_width(widgets):  # noqa: F811
    widget = widgets("navigation", modern=False, view_radius=500, display_size=300)
    assert widget.area_size / widget.global_scale == pytest.approx(500.0)
    docs = (Path(__file__).resolve().parent.parent / "docs" / "customization.md").read_text(encoding="utf-8")
    assert "`500` shows `500` meters from left to right edge" in docs


# --- 104: classic temperature rounded, never cut
def test_temperature_text_rounded_not_cut():
    from neopedal.widget.weather import temperature_text

    assert temperature_text(25.99, 4, 1) == "26.0"
    assert temperature_text(5.37, 4, 1) == "05.4"
    assert temperature_text(5.0, 2, 0) == "05"
    assert temperature_text(-12.0, 2, 0) == "-12"
    assert temperature_text(-12.34, 4, 1) == "-12"
    assert temperature_text(-5.34, 4, 1) == "-5.3"
    assert temperature_text(100.4, 5, 1) == "100.4"


def test_classic_weather_temperature_reading(widgets, monkeypatch):  # noqa: F811
    widget = widgets("weather", modern=False, show_temperature=True, decimal_places_temperature=1, show_trend=False)
    reader(monkeypatch, "session", "track_temperature", 25.99)
    reader(monkeypatch, "session", "ambient_temperature", 5.37)
    widget.timerEvent(None)
    assert widget.bar_temp.text.startswith("26.0(05.4)")


# --- 105: no wind arrow beside a 0 speed reading
def test_wind_arrow_hidden_while_reading_shows_zero(widgets, monkeypatch):  # noqa: F811
    from neopedal.widget.weather import wind_arrow_angle

    assert wind_arrow_angle(0.4, 30.0) is None
    assert wind_arrow_angle(0.6, 30.0) == 30.0
    reader(monkeypatch, "session", "wind_velocity", (0.4, 0.0, 0.0))  # above calm threshold (0.3 m/s)
    cfg.units["wind_speed_unit"] = "m/s"
    classic = widgets("weather", modern=False, show_wind_speed=True)
    classic.timerEvent(None)
    assert classic.bar_wind.last[1] == "-"
    modern = widgets("weather", show_wind=True)
    assert modern.wind()[1] is None


# --- 107: forecast node less than 30 seconds away still shown
def test_forecast_node_seconds_away_not_skipped(ui_env, monkeypatch):
    from neopedal.process.weather import WeatherNode
    from neopedal.widget.weather_forecast import ForecastMixin

    reader(monkeypatch, "session", "end", 3600.0)
    reader(monkeypatch, "session", "elapsed", 720.0 - 25.0)  # node at 20 % in 25 seconds
    forecast = SimpleNamespace(estimated_time=[0.0] * 5)
    nodes = tuple(WeatherNode(start=round(index * 0.2, 1)) for index in range(5))
    assert ForecastMixin.set_forecast_time(forecast, nodes) == 0
    assert forecast.estimated_time[1] == 0
    reader(monkeypatch, "session", "elapsed", 721.0)  # passed
    assert ForecastMixin.set_forecast_time(forecast, nodes) == 1


# --- 108: cloud outline made once per width
def test_cloud_path_made_once_per_width():
    from neopedal.widget._modern.weather_forecast import cloud_path, cloud_shape

    cloud_shape.cache_clear()
    first = cloud_path(QPointF(10.0, 20.0), 30.0)
    second = cloud_path(QPointF(50.0, 20.0), 30.0)
    assert cloud_shape.cache_info().misses == 1
    assert second.boundingRect().translated(-40.0, 0.0) == first.boundingRect()
    assert first.boundingRect().center().x() == pytest.approx(10.0 + 30.0 * -0.01, abs=1.0)


# --- 109: classic wind speed decimals limited as modern design
def test_classic_wind_direction_reading(widgets, monkeypatch):  # noqa: F811
    cfg.units["wind_speed_unit"] = "m/s"
    reader(monkeypatch, "session", "wind_velocity", (3.2, 0.0, 0.0))
    widget = widgets("wind_direction", modern=False, decimal_places=6, show_wind_speed_unit=True)
    widget.timerEvent(None)
    assert widget.wind_state[1] == "3.20m/s"  # classic: unit right after reading (compact, as weather)


# --- 110 & 111: joining another session resets black box, stint averages forgotten on new session or car
def test_black_box_new_session_on_other_session_stamp(ui_env, monkeypatch):
    from neopedal.api_control import api

    elapsed = [500.0]
    stamp = [360000 + 1]
    monkeypatch.setattr(api.read.session, "elapsed", lambda: elapsed[0])
    monkeypatch.setattr(api.read.session, "identifier", lambda: (stamp[0], int(elapsed[0]), 0))
    widget = new_widget({"show_incident_recorder": True, "slow_data_update_interval": 0})
    try:
        widget.timerEvent(None)
        assert widget.recorder.samples
        widget.stint.previous = (0.1, 170.0)
        widget.check_new_session()
        assert widget.recorder.samples and widget.stint.previous is not None  # same session
        elapsed[0] = 4000.0  # joined a race further on: session time went forward
        stamp[0] = 864000 + 10
        widget.check_new_session()
        assert not widget.recorder.samples
        assert widget.stint.previous is None
    finally:
        widget.deleteLater()


def test_black_box_stint_forgotten_on_car_change(ui_env):
    widget = new_widget()
    try:
        widget.vehicle_name = "car A"
        widget.update_stint(False)
        widget.stint.previous = (0.1, 170.0)
        widget.update_stint(False)
        assert widget.stint_has_previous
        widget.vehicle_name = "car B"
        widget.update_stint(False)
        assert not widget.stint_has_previous and widget.stint.previous is None
    finally:
        widget.deleteLater()


# --- 112: modern black box LED colors made once per LED count
def test_modern_black_box_led_colors_cached(ui_env):
    from neopedal.widget import black_box
    from neopedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    cfg.user.setting["black_box"].update({"enable_auto_resize": False})
    widget = create_widget(black_box, cfg, "black_box")
    try:
        colors = widget.led_colors(10)
        assert widget.led_colors(10) is colors
        zones = colors[2]
        assert len(zones) == 10 and zones[0] is not zones[-1]
        assert widget.led_colors(12) is not colors
        render(widget)
    finally:
        widget.deleteLater()


# --- 113: black box logs named after the overlay
def test_black_box_log_prefix():
    folder = Path(__file__).resolve().parent.parent / "neopedal" / "widget" / "_black_box"
    for name in ("recorder.py", "modules.py"):
        assert "DASHBOARD HUD" not in (folder / name).read_text(encoding="utf-8")
