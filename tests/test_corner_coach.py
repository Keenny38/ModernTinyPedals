"""Corner coach overlay (reference corners prepared in background, current lap followed corner by corner, both
designs) & official corner numbers on track map & elevation overlays"""

import math
from concurrent.futures import Future
from importlib import import_module

import pytest

from neopedal.module_info import minfo
from neopedal.setting import cfg
from neopedal.userfile import corner_coach
from neopedal.userfile.corner_analysis import Corner, CornerComparison, CornerStats
from neopedal.userfile.corner_coach import (
    CoachCorner,
    CoachReference,
    CornerResult,
    CornerTracker,
    MapCorners,
    ReferenceCorners,
    coach_corners,
    corner_name,
    map_corners,
    place_map_corners,
    prepare_reference,
)
from neopedal.userfile.reference_trace import ReferenceLoader, stop_loading
from neopedal.userfile.track_corners import TrackCorner
from neopedal.widget._modern import create_widget
from tests.test_race_aid_widgets import grab, is_blank, set_reader
from tests.test_telemetry_compare import LENGTH, TRACK, wait_reference, write_lap

CORNERS = (  # label, start, apex, end, braking point, minimum speed
    CoachCorner("T1", 100.0, 200.0, 300.0, 150.0, 90.0),
    CoachCorner("T2", 300.0, 400.0, 500.0, -1.0, 150.0),  # flat out
    CoachCorner("T3", 600.0, 800.0, 950.0, 700.0, 80.0),
)
OFFICIAL = [TrackCorner("1", 210.0, 0, 0), TrackCorner("2", 380.0, 0, 0), TrackCorner("3", 420.0, 0, 0)]


@pytest.fixture(autouse=True)
def loading_thread():
    """Background thread of reference laps ended after each test, shared map corners forgotten"""
    yield
    stop_loading()
    corner_coach._map_result = corner_coach._map_job = None


@pytest.fixture
def french():
    from neopedal.i18n import set_language

    set_language("Français")
    yield
    set_language("English")


def drive(tracker: CornerTracker, start: float, end: float, speed=lambda distance: 200.0,
          brake=lambda distance: 0.0, step: float = 4.0):
    """Car samples every step meters from start to end"""
    distance = start
    while distance <= end:
        tracker.update(distance, speed(distance), brake(distance))
        distance += step


# Corner names
def test_corner_named_after_official_corners():
    assert corner_name(OFFICIAL, True, 150, 200, 250) == "T1"
    assert corner_name(OFFICIAL, True, 350, 400, 450) == "T2-3"  # covers two
    assert corner_name(OFFICIAL, True, 230, 260, 240) == "T1"  # covers none: nearest within range
    assert corner_name(OFFICIAL, True, 900, 1000, 1100) == ""  # none near
    assert corner_name([], True, 150, 200, 250) == ""
    names = [TrackCorner("Dunlop Curve", 210.0, 0, 0), TrackCorner("Dunlop Chicane", 230.0, 0, 0)]
    assert corner_name(names, False, 200, 215, 240) == "Dunlop Curve / Dunlop Chicane"


def test_corners_found_on_lap_keep_their_number_without_official_one():
    def row(number: int, start: float, apex: float, end: float) -> CornerComparison:
        stats = CornerStats(min_speed=80.0 + number, apex=apex, brake_point=start + 20, throttle_point=-1, time=3.0)
        return CornerComparison(Corner(number, start, apex, end), stats, None)

    corners = coach_corners([row(1, 150, 200, 250), row(2, 900, 1000, 1100)], OFFICIAL, True)
    assert [corner.label for corner in corners] == ["T1", "T2"]  # official T1, else number found on lap
    assert corners[0] == CoachCorner("T1", 150, 200, 250, 170, 81.0)


def test_french_corner_numbers(french):
    assert corner_name(OFFICIAL, True, 150, 200, 250) == "V1"
    assert MapCorners((corner_coach.MapCorner("10a", 0, 0, 0, 1, 0),), True).texts() == ("V10a",)
    assert MapCorners((corner_coach.MapCorner("Dunlop Curve", 0, 0, 0, 1, 0),), False).texts() == ("Courbe Dunlop",)


# Current lap
def test_brake_point_ahead_then_braked_against_reference():
    tracker = CornerTracker(CORNERS, 1000.0)
    drive(tracker, 0, 40)
    state = tracker.state(40)
    assert (state.label, state.to_corner, state.to_brake, state.brake_gap) == ("T1", 160.0, 110.0, None)
    # Braked 8 m after reference point (pedal crosses threshold between samples: finer than a sample)
    drive(tracker, 44, 196, brake=lambda distance: 0.8 if distance >= 158 else 0.0)
    state = tracker.state(196)
    assert state.brake_gap == pytest.approx(6.5, abs=0.01)  # 0 at 156, 0.8 at 160: threshold crossed at 156.5
    assert state.to_brake < 0


def test_brake_tap_on_straight_is_not_the_braking_point():
    tracker = CornerTracker(CORNERS, 1000.0)

    def brake(distance: float) -> float:
        return 0.5 if 0 <= distance - 600 <= 8 or distance >= 712 else 0.0  # tap, released 100 m, braking

    drive(tracker, 500, 760, brake=brake)
    assert tracker.state(760).brake_gap == pytest.approx(8.8, abs=0.01)  # braking from 708.8, not tap at 600


def test_apex_speed_given_once_corner_left():
    tracker = CornerTracker(CORNERS, 1000.0)
    drive(tracker, 80, 296, speed=lambda distance: 80 + abs(distance - 200) * 0.5)
    assert tracker.state(296).last is None  # still in corner
    drive(tracker, 300, 320)
    assert tracker.last == CornerResult("T1", 80.0, 90.0)
    state = tracker.state(320)
    assert state.label == "T2" and state.to_brake is None  # reference does not brake there


def test_corner_entered_after_apex_gives_no_result():
    tracker = CornerTracker(CORNERS, 1000.0)
    drive(tracker, 250, 340)  # reset into the middle of T1
    assert tracker.last is None
    drive(tracker, 80, 120)  # car moved back (garage): driving forgotten
    assert tracker.state(120).brake_gap is None


def test_next_corner_wraps_around_lap():
    tracker = CornerTracker(CORNERS, 1000.0)
    drive(tracker, 590, 996, speed=lambda distance: 100.0)
    assert tracker.last == CornerResult("T3", 100.0, 80.0)
    state = tracker.state(996)
    assert state.label == "T1" and state.to_corner == pytest.approx(204.0)  # next lap
    assert state.to_brake == pytest.approx(154.0)
    drive(tracker, 0, 156, brake=lambda distance: 1.0 if distance >= 152 else 0.0)  # over lap line: same drive
    assert tracker.state(156).brake_gap == pytest.approx(-1.6, abs=0.01)  # braked 1.6 m early


def test_position_correction_ignored():
    tracker = CornerTracker(CORNERS, 1000.0)
    drive(tracker, 120, 160, brake=lambda distance: 1.0 if distance >= 150 else 0.0)
    gap = tracker.brake_gap
    tracker.update(150.0, 200.0, 0.0)  # game position corrected back a few meters
    assert tracker.brake_gap == gap and tracker.last_distance == 160.0


# Reference lap prepared in background
def test_reference_prepared_from_recorded_lap(tmp_path):
    folder = tmp_path / TRACK
    write_lap(str(folder), "10-00-00", 60.0)
    loader = ReferenceLoader(str(tmp_path), "Best", 10.0)
    wait_reference(loader)
    reference = prepare_reference(str(tmp_path), loader.trace, TRACK)
    assert reference.length == pytest.approx(LENGTH) and len(reference.corners) == 1
    corner = reference.corners[0]
    assert corner.label == "T1" and corner.apex == pytest.approx(500, abs=5)  # no official corner: number
    assert corner.brake == pytest.approx(400, abs=5) and corner.min_speed == pytest.approx(120, abs=1)


def test_reference_corners_polled_once_per_lap(tmp_path, monkeypatch):
    calls = []

    def prepare(filepath, trace, folder, coordinates=None, elevations=None):
        calls.append((trace.path, folder, coordinates))
        return CoachReference(trace.path, trace.stamp, trace.length, CORNERS)

    monkeypatch.setattr(corner_coach, "prepare_reference", prepare)
    write_lap(str(tmp_path / TRACK), "10-00-00", 60.0)
    loader = ReferenceLoader(str(tmp_path), "Best", 10.0)
    wait_reference(loader)
    prepared = ReferenceCorners(str(tmp_path))
    assert prepared.poll(loader.trace, TRACK, ((0.0, 0.0),), ((0.0, 0.0),)) is False  # preparing
    prepared._job.result(timeout=10)
    assert prepared.poll(loader.trace, TRACK) is True and prepared.reference.corners == CORNERS
    assert prepared.poll(loader.trace, TRACK) is False and len(calls) == 1  # same lap file: not prepared again
    assert calls[0][1:] == (TRACK, ((0.0, 0.0),))
    assert prepared.poll(None, TRACK) is True and prepared.reference is None  # no reference lap any more


def test_cancelled_preparation_started_again(tmp_path, monkeypatch):
    write_lap(str(tmp_path / TRACK), "10-00-00", 60.0)
    loader = ReferenceLoader(str(tmp_path), "Best", 10.0)
    wait_reference(loader)
    prepared = ReferenceCorners(str(tmp_path))
    cancelled = Future()
    cancelled.cancel()
    prepared._job, prepared._job_trace = cancelled, loader.trace  # thread ended by another overlay closing
    prepared.poll(loader.trace, TRACK)
    assert prepared._job is not cancelled
    prepared._job.result(timeout=10)
    assert prepared.poll(loader.trace, TRACK) is True and prepared.reference is not None


def test_reference_loader_keeps_trace_when_check_cancelled(tmp_path):
    write_lap(str(tmp_path / TRACK), "10-00-00", 60.0)
    loader = ReferenceLoader(str(tmp_path), "Best", 10.0)
    wait_reference(loader)
    trace = loader.trace
    cancelled = Future()
    cancelled.cancel()
    loader._job = cancelled
    assert loader.poll(TRACK, 1.0) is False  # check started again, trace kept
    assert loader.trace is trace and loader._job is not cancelled


# Official corners of recorded track map
def demo_mapping():
    from neopedal.demo_data import TRACK_POINTS, TRACK_SECTORS
    from neopedal.module_info import MappingInfo

    mapping = MappingInfo()
    mapping.coordinates = tuple((point[1], point[2]) for point in TRACK_POINTS)
    mapping.elevations = tuple((point[0], point[3]) for point in TRACK_POINTS)
    mapping.sectors = TRACK_SECTORS
    mapping.lastModified = 5.0
    return mapping


def test_map_corners_placed_outside_their_bend():
    from neopedal.demo_data import TRACK_NAME

    mapping = demo_mapping()
    found = place_map_corners(TRACK_NAME, mapping.coordinates, mapping.elevations)
    assert found.numbered and [corner.label for corner in found.corners][:3] == ["1", "2", "3"]
    for corner in found.corners:
        assert math.hypot(corner.out_x, corner.out_y) == pytest.approx(1.0)
    assert place_map_corners("Unknown Raceway", mapping.coordinates, mapping.elevations).corners == ()


def test_map_corners_shared_and_placed_in_background():
    from neopedal.demo_data import TRACK_NAME

    mapping = demo_mapping()
    assert map_corners(TRACK_NAME, mapping) is None  # placing
    corner_coach._map_job[1].result(timeout=10)
    found = map_corners(TRACK_NAME, mapping)
    assert found is not None and found.corners
    assert map_corners(TRACK_NAME, mapping) is found  # once per map
    mapping.lastModified = 6.0
    assert map_corners(TRACK_NAME, mapping, wait=True) is not found  # new map, placed now (overlay picture)
    mapping.coordinates = None
    assert map_corners(TRACK_NAME, mapping).corners == ()


# Overlay
@pytest.fixture
def make(ui_env, bundled_fonts, monkeypatch):
    """Widget at 40 m into lap at 200 km/h, delta module off (lap distance from game)"""
    set_reader(monkeypatch, "lap", "distance", 40.0)
    set_reader(monkeypatch, "vehicle", "speed", 200 / 3.6)
    set_reader(monkeypatch, "inputs", "brake_raw", 0.0)
    cfg.user.setting["module_delta"]["enable"] = False
    created = []

    def build(modern: bool, reference: CoachReference | None = None, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting["corner_coach"].update(options)
        widget = create_widget(import_module("neopedal.widget.corner_coach"), cfg, "corner_coach")
        if reference is not None:
            monkeypatch.setattr(widget, "poll_reference", lambda: reference)
        created.append(widget)
        return widget

    yield build
    for widget in created:
        widget.deleteLater()


REFERENCE = CoachReference("lap.csv", (1, 1), 1000.0, CORNERS)


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_no_reference_lap(make, modern):
    widget = make(modern)
    widget.timerEvent(None)
    assert widget.state.status == "No reference lap"
    assert not is_blank(grab(widget))


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_coaching_texts(make, modern):
    widget = make(modern, REFERENCE)
    widget.timerEvent(None)
    state = widget.state
    assert (state.status, state.corner, state.distance, state.brake) == ("", "T1", "160 m", "110 m")
    widget.tracker.last = CornerResult("T3", 76.0, 80.0)
    widget.timerEvent(None)
    assert (widget.state.apex_corner, widget.state.apex_speed, widget.state.apex_delta) == ("T3", "76 km/h", "-4")
    assert widget.state.apex_gain == -1
    assert not is_blank(grab(widget))


def test_braking_texts(make):
    widget = make(True, REFERENCE)
    widget.timerEvent(None)
    for gap, text in ((2.0, "On point"), (12.0, "10 m late"), (-21.0, "20 m early")):
        widget.tracker.brake_gap = gap
        assert widget.view(widget.tracker.state(40.0)).brake == text
    widget.tracker.brake_gap = None
    assert widget.view(widget.tracker.state(180.0)).brake == "Now"  # reference braking point passed
    widget.tracker.update(320.0, 150.0, 0.0)
    assert widget.view(widget.tracker.state(320.0)).brake == "No braking"


def test_rows_switchable(make):
    full = make(True, REFERENCE)
    widget = make(True, REFERENCE, show_braking_point=False, show_apex_speed=False)
    assert widget.rows == ("next",) and widget.height() < full.height()
    classic = make(False, REFERENCE, show_next_corner=False, show_braking_point=True, show_apex_speed=True)
    assert classic.rows == ("brake", "apex")


def test_french_labels(make, french):
    from neopedal.i18n.options import module_label

    assert module_label("corner_coach") == "Coach de virages"
    widget = make(True)
    widget.timerEvent(None)
    assert widget.state.status == "Aucun tour de référence"
    assert widget.captions == {"next": "Suivant", "brake": "Frein", "apex": "Corde"}


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_preview_on_simulated_race(ui_env, bundled_fonts, modern):
    from neopedal.ui.widget_preview import render_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    image = render_widget(cfg, "corner_coach", dict(cfg.user.setting["corner_coach"])).toImage()
    assert not image.isNull() and image.width() > 100


def test_registered_everywhere():
    from neopedal.i18n.options import load_data
    from neopedal.template.setting_widget import WIDGET_DEFAULT
    from neopedal.template.widget.modern import MODERN_DESIGNS
    from neopedal.ui.quick.overlay_backend import widget_category

    assert WIDGET_DEFAULT["corner_coach"]["enable"] is False
    assert "corner_coach" in MODERN_DESIGNS and "corner_coach" in load_data("fr_options.json")
    assert widget_category("corner_coach") == "Driver Inputs"
    for name in ("track_map", "elevation"):
        assert WIDGET_DEFAULT[name]["show_corner_numbers"] is False  # renders unchanged by default


# Corner numbers on track map & elevation
@pytest.mark.parametrize("name", ["track_map", "elevation"])
@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_corner_numbers_drawn_when_on(ui_env, bundled_fonts, monkeypatch, name, modern):
    from neopedal.ui.widget_preview import render_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    calls = []
    real = corner_coach.map_corners
    for module in ("neopedal.widget.track_map", "neopedal.widget.elevation", "neopedal.widget._modern.elevation"):
        monkeypatch.setattr(import_module(module), "map_corners", lambda *args: calls.append(args) or real(*args))
    setting = dict(cfg.user.setting[name])
    off = render_widget(cfg, name, {**setting, "show_corner_numbers": False}).toImage()
    assert not calls  # option off: corners never placed
    on = render_widget(cfg, name, {**setting, "show_corner_numbers": True}).toImage()
    assert calls and calls[0][2] is True  # overlay picture: placed at once
    assert on != off


def test_corner_numbers_follow_new_map(ui_env, bundled_fonts, monkeypatch):
    """Corners placed in background: map drawn again once placed, forgotten when map changes"""
    from neopedal.demo_data import TRACK_NAME

    mapping = demo_mapping()
    monkeypatch.setattr(minfo, "mapping", mapping)
    set_reader(monkeypatch, "session", "track_name", TRACK_NAME)
    cfg.user.config["overlay_style"]["overlay_theme"] = "Legacy Dark"
    cfg.user.setting["track_map"]["show_corner_numbers"] = True
    widget = create_widget(import_module("neopedal.widget.track_map"), cfg, "track_map")
    widget.timerEvent(None)
    assert widget.map_corners is None  # placing
    corner_coach._map_job[1].result(timeout=10)
    widget.timerEvent(None)
    assert widget.map_corners is not None and widget.map_corners.corners
    labels = widget.corner_labels(lambda text: (20.0, 10.0), 4.0)
    assert labels and all(not a.intersects(b) for index, (_, a) in enumerate(labels) for _, b in labels[index + 1:])
    mapping.lastModified = 7.0
    widget.timerEvent(None)
    assert widget.map_corners is None  # new map: placed again
    widget.deleteLater()
