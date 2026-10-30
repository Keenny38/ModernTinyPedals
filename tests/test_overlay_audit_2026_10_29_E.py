"""Overlay audit 2026-10-29, group E: flag, pit lane helper, spotter, radar, race notifications, traffic & vehicles
module (findings 70-94)"""

import math

import pytest
from PySide6.QtGui import QPixmap

from neopedal.const_common import MAX_SECONDS
from neopedal.module_info import minfo
from neopedal.penalty_info import Penalty
from tests import test_race_aid_widgets
from tests.test_race_aid_widgets import make, set_reader

field = test_race_aid_widgets.field  # fixture: default setting, fake reader, field of 20 cars


def chips(widget) -> dict:
    return {chip.key: chip for chip in widget.state}


def update(widget):
    widget.timerEvent(None)


# --- Vehicles module on a simulated LMU field (findings 71, 72, 83, 86)
def lmu_field(monkeypatch, cars):
    """Simulated LMU game: cars (class, lap distance, total laps, speed, in pits, world x, world height),
    car 0 is player, race on 4000 m track"""
    from neopedal.api_control import api
    from neopedal.module_info import VehiclesInfo
    from tests.test_readers import lmu_api

    sim, data = lmu_api()
    info = data.scoring.scoringInfo
    info.mNumVehicles = len(cars)
    info.mLapDist = 4000.0
    info.mCurrentET = 600.0
    info.mSession = 10  # race
    for index, (class_name, distance, laps, speed, in_pits, pos_x, height) in enumerate(cars):
        car = data.scoring.vehScoringInfo[index]
        car.mID = index
        car.mDriverName = f"Driver {index}".encode()
        car.mVehicleClass = class_name.encode()
        car.mPlace = index + 1
        car.mLapDist = distance
        car.mLocalVel.z = -speed
        car.mInPits = in_pits
        car.mTotalLaps = laps
        car.mIsPlayer = index == 0
        car.mEstimatedLapTime = 96.0
        car.mTimeIntoLap = distance / 4000 * 96
        tele = data.telemetry.telemInfo[index]
        tele.mID = index
        tele.mLocalVel.z = -speed
        tele.mElapsedTime = 600.0
        tele.mPos.x, tele.mPos.y = pos_x, height
    monkeypatch.setattr(api, "_api", sim)
    monkeypatch.setattr(api, "read", sim.reader())
    output = VehiclesInfo()
    output.totalVehicles = len(cars)
    return output, data


@pytest.fixture
def module_state(ui_env, monkeypatch):
    from neopedal.module import module_vehicles

    monkeypatch.setattr(module_vehicles, "_index_slot_ids", {})
    monkeypatch.setattr(module_vehicles, "_point_times", {})


def test_blue_flag_gap_and_class_of_same_car(module_state, monkeypatch):
    """Car of player class just behind (not lapping), Hypercar lapping farther behind: blue flag gap & class
    both of the Hypercar, known before blue flag (finding 71)"""
    from neopedal.module import module_vehicles

    output, _ = lmu_field(monkeypatch, (
        ("LMP2", 1000.0, 10, 60.0, False, 0.0, 0.0),
        ("LMP2", 980.0, 10, 60.0, False, 0.0, 0.0),  # 0.48 s behind, same lap
        ("Hyper", 940.0, 11, 65.0, False, 0.0, 0.0),  # 1.44 s behind, a lap ahead
    ))
    module_vehicles.update_vehicle_data(output, 0.9, 0.9, True, 600.0, True)
    assert output.nearestTraffic == pytest.approx(0.48)
    assert output.nearestBlueGap == pytest.approx(1.44) and output.nearestBlueClass == "Hyper"


def test_yellow_flag_leaves_out_cars_stopped_in_pit_lane(module_state, monkeypatch):
    """Car stopped at its pit box is no yellow flag incident (finding 72)"""
    from neopedal.module import module_vehicles

    output, _ = lmu_field(monkeypatch, (
        ("LMP2", 1000.0, 10, 60.0, False, 0.0, 0.0),
        ("GT3", 1040.0, 10, 0.0, True, 0.0, 0.0),  # stopped at pit box 40 m ahead
        ("GT3", 1500.0, 10, 3.0, False, 0.0, 0.0),  # slow on track 500 m ahead
    ))
    module_vehicles.update_vehicle_data(output, 0.9, 0.9, True, 600.0, True)
    assert not output.dataSet[1].isYellow and output.dataSet[2].isYellow
    assert output.nearestYellowAhead == pytest.approx(500.0)


def test_relative_position_follows_player_while_car_telemetry_unchanged(module_state, monkeypatch):
    """Car telemetry not updated: car stays in place (relative to player moving), never follows player; height
    above player (findings 86, 83)"""
    from neopedal.module import module_vehicles

    output, data = lmu_field(monkeypatch, (
        ("LMP2", 1000.0, 10, 60.0, False, 0.0, 10.0),
        ("LMP2", 1100.0, 10, 60.0, False, 30.0, 17.0),  # on bridge 7 m above player
    ))
    module_vehicles.update_vehicle_data(output, 0.9, 0.9, False, 600.0, True)
    car = output.dataSet[1]
    assert car.relativeStraightDistance == pytest.approx(30.0) and car.relativeElevation == pytest.approx(7.0)
    data.telemetry.telemInfo[0].mPos.x = 20.0  # player moved, car telemetry time unchanged
    data.telemetry.telemInfo[0].mElapsedTime = 600.2
    module_vehicles.update_vehicle_data(output, 0.9, 0.9, False, 600.2, True, update_scoring=False)
    assert car.relativeStraightDistance == pytest.approx(10.0)
    # Car moving (two samples): extrapolated to player time from a recent sample, last position once its telemetry
    # stops
    tele = data.telemetry.telemInfo[1]
    tele.mPos.x, tele.mElapsedTime = 31.0, 600.22
    module_vehicles.update_vehicle_data(output, 0.9, 0.9, False, 600.22, True, update_scoring=False)
    assert car.worldVelocityX == pytest.approx(1 / 0.22)
    module_vehicles.update_vehicle_data(output, 0.9, 0.9, False, 600.32, True, update_scoring=False)
    assert car.relativeStraightDistance == pytest.approx(31.0 + 1 / 0.22 * 0.1 - 20.0)
    module_vehicles.update_vehicle_data(output, 0.9, 0.9, False, 610.0, True, update_scoring=False)
    assert car.relativeStraightDistance == pytest.approx(11.0)
    # Car teleported (garage, reset): never extrapolated from that jump
    tele.mPos.x, tele.mElapsedTime = 531.0, 600.3  # 500 m in 0.08 s
    module_vehicles.update_vehicle_data(output, 0.9, 0.9, False, 600.4, True, update_scoring=False)
    assert car.worldVelocityX == 0.0 and car.relativeStraightDistance == pytest.approx(511.0)


# --- Flag: pit closed under full course yellow (finding 70)
def test_pit_lane_open_under_full_course_yellow(ui_env, monkeypatch):
    from neopedal.widget.flag import pit_lane_open

    set_reader(monkeypatch, "session", "pit_open", True)  # session started
    set_reader(monkeypatch, "lap", "behind_leader", 0)
    for state, expected in ((0, True), (1, True), (2, False), (3, True), (4, True), (5, True)):
        set_reader(monkeypatch, "session", "yellow_flag_state", state)
        assert pit_lane_open() is expected, state
    set_reader(monkeypatch, "session", "yellow_flag_state", 3)  # lead lap cars only
    set_reader(monkeypatch, "lap", "behind_leader", 1)
    assert not pit_lane_open()
    set_reader(monkeypatch, "session", "yellow_flag_state", 0)
    set_reader(monkeypatch, "session", "pit_open", False)  # session not started
    assert not pit_lane_open()


@pytest.mark.parametrize("modern", [True, False])
def test_pit_timer_closed_under_full_course_yellow(field, monkeypatch, modern):
    set_reader(monkeypatch, "session", "pit_open", True)
    set_reader(monkeypatch, "session", "yellow_flag_state", 2)
    set_reader(monkeypatch, "vehicle", "in_pits", True)
    set_reader(monkeypatch, "timing", "elapsed", 10.0)
    widget = make("flag", modern, pit_closed_text="NO PIT")
    update(widget)
    set_reader(monkeypatch, "timing", "elapsed", 11.0)
    update(widget)
    if modern:
        assert chips(widget)["pit_timer"].value == "Closed"
    else:
        assert widget.bar_pit_timer.text == "NO PIT"
    widget.deleteLater()


# --- Flag: blue flag lost a moment, traffic & pit timer in garage (findings 73, 74, 75)
def test_blue_flag_time_kept_through_short_gap(ui_env, monkeypatch):
    from neopedal.widget.flag import BlueFlagTimer

    timer = BlueFlagTimer(False)
    set_reader(monkeypatch, "session", "blue_flag", True)
    assert timer.update(True, 10.0) == 0.0
    set_reader(monkeypatch, "session", "blue_flag", False)
    assert timer.update(True, 10.2) == MAX_SECONDS
    set_reader(monkeypatch, "session", "blue_flag", True)
    assert timer.update(True, 10.4) == pytest.approx(0.4)  # same flag
    set_reader(monkeypatch, "session", "blue_flag", False)
    timer.update(True, 10.5)
    set_reader(monkeypatch, "session", "blue_flag", True)
    assert timer.update(True, 12.0) == 0.0  # new flag


def test_alert_not_flashed_again_after_short_gap(field, monkeypatch):
    widget = make("flag", True, new_flag_flash_duration=1.0)
    widget.overlay_started = True
    clock = {"now": 100.0}
    widget.clock = lambda: clock["now"]
    set_reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Drive Thru", 0))
    update(widget)
    clock["now"] = 101.5  # flash over
    update(widget)
    set_reader(monkeypatch, "vehicle", "penalty", Penalty())
    clock["now"] = 101.6
    update(widget)
    set_reader(monkeypatch, "vehicle", "penalty", Penalty(1, "Drive Thru", 0))
    clock["now"] = 101.8  # back after one missing update: same alert
    update(widget)
    assert not chips(widget)["penalty"].flash
    widget.overlay_started = False
    widget.deleteLater()


def test_no_traffic_in_garage(ui_env, monkeypatch):
    from neopedal.widget.flag import TrafficTimer

    monkeypatch.setattr(minfo.vehicles, "nearestTraffic", 1.0)
    timer = TrafficTimer(5.0, 10.0, 5.0, False)
    set_reader(monkeypatch, "vehicle", "in_garage", False)
    assert timer.update(True, 10.0) == 1.0  # pit lane
    set_reader(monkeypatch, "vehicle", "in_garage", True)
    assert timer.update(True, 11.0) == MAX_SECONDS


@pytest.mark.parametrize("modern", [True, False])
def test_pit_timer_counted_from_garage_exit(field, monkeypatch, modern):
    set_reader(monkeypatch, "session", "pit_open", True)
    set_reader(monkeypatch, "vehicle", "in_pits", True)
    set_reader(monkeypatch, "vehicle", "in_garage", False)
    widget = make("flag", modern, pit_in_text="")
    for elapsed in (10.0, 20.0):  # pit lane, then garage
        set_reader(monkeypatch, "timing", "elapsed", elapsed)
        update(widget)
    set_reader(monkeypatch, "vehicle", "in_garage", True)
    update(widget)
    set_reader(monkeypatch, "vehicle", "in_garage", False)  # garage left at 100 s
    set_reader(monkeypatch, "timing", "elapsed", 100.0)
    update(widget)
    set_reader(monkeypatch, "timing", "elapsed", 101.5)
    update(widget)
    if modern:
        assert chips(widget)["pit_timer"].value == "1.50"
    else:
        assert widget.bar_pit_timer.text == "1.50"
    widget.deleteLater()


# --- Flag classic: pit request laps, damage without prefix, dead constant (findings 76, 77, 78)
def test_lap_text():
    from neopedal.widget.flag import lap_text

    assert (lap_text(3.25), lap_text(12.4), lap_text(-0.5)) == ("3.2", "12", "-0.5")
    assert lap_text(math.nan) == "-" and lap_text(math.inf, "x") == "x" and lap_text(1234.0) == "-"


def test_classic_pit_request_laps_unknown(field, monkeypatch):
    monkeypatch.setattr(minfo.fuel, "estimatedLaps", math.nan)
    monkeypatch.setattr(minfo.energy, "available", False)
    set_reader(monkeypatch, "vehicle", "pit_request", True)
    widget = make("flag", False)
    assert widget.pit_in_countdown() == "-  ≤  -"
    widget.deleteLater()


def test_classic_damage_without_prefix(field, monkeypatch):
    set_reader(monkeypatch, "vehicle", "damage_severity", (2,))
    set_reader(monkeypatch, "vehicle", "aero_damage", 0.0)
    widget = make("flag", False, damage_text="")
    widget.show()
    update(widget)
    assert widget.bar_damage.text == "DAMAGE" and not widget.bar_damage.isHidden()
    widget.hide()
    widget.deleteLater()


def test_modern_flag_dead_alerts_constant_removed():
    from neopedal.widget._modern import flag

    assert not hasattr(flag, "ALERTS")


# --- Pit lane helper: shown always, not colored on whole lap (finding 80)
def test_pit_lane_helper_shown_always_not_colored_on_track(field, monkeypatch):
    from neopedal.widget.pit_lane_helper import UNKNOWN
    from tests.test_race_aid_widgets import pit_lane

    monkeypatch.setattr(minfo.mapping, "pitSpeedLimit", 80 / 3.6)
    pit_lane(monkeypatch, 1000.0, in_lane=0, limiter=False, speed=70.0)
    widget = make("pit_lane_helper", True, show_always=True)
    reading = widget.read_pit()
    assert reading.visible and reading.speed_state == UNKNOWN and reading.limiter_state == UNKNOWN
    widget.deleteLater()


# --- Spotter: car straight behind, pit lane, other road level (findings 81, 82, 83)
def test_side_overlap_leaves_out_car_in_player_lane():
    from neopedal.widget.spotter import NO_CAR, side_overlap

    assert side_overlap([(0.3, 3.0)], 4.6, 5.0, 2.6, 1.14) == (NO_CAR, NO_CAR)  # bumper to bumper behind
    left, right = side_overlap([(-2.0, 1.0)], 4.6, 5.0, 2.6, 1.14)
    assert left.lit and right == NO_CAR


def test_spotter_cars_on_track_and_same_road_level(field):
    from neopedal.widget.spotter import SpotterMixin

    cars = [car for car in field.dataSet if not car.isPlayer][:4]
    for car in cars:
        car.relativeRotatedPositionX, car.relativeRotatedPositionY = 2.0, 0.0
        car.relativeStraightDistance = 2.0
        car.inPit, car.speed = 0, 50.0
    cars[0].inPit, cars[0].speed = 1, 0.0  # stopped at pit box
    cars[3].inPit = 1  # moving in pit lane (pit exit blend line): kept
    cars[1].relativeElevation = 7.0  # on bridge above
    cars[2].relativeElevation = 1.5  # banking: same road
    assert sum(1 for _ in SpotterMixin.nearby_cars()) == len(field.dataSet) - 1 - 2


# --- Radar: garage, colors, collision course once (findings 84, 85, 87)
def place_radar_cars(field):
    cars = [car for car in field.dataSet if not car.isPlayer]
    for car in cars:
        car.relativeRotatedPositionX = car.relativeRotatedPositionY = 300.0
        car.inPit = 0
        car.isYellow = False
    return cars


@pytest.mark.parametrize("modern", [True, False])
def test_radar_leaves_out_cars_in_garage(field, monkeypatch, modern):
    cars = place_radar_cars(field)
    cars[0].relativeRotatedPositionX, cars[0].relativeRotatedPositionY = 3.0, 5.0
    cars[0].inPit = 2  # parked in garage beside pit lane
    widget = make("radar", modern, enable_auto_hide=True, enable_radar_fade=False)
    assert not widget.is_nearby(widget.radar_hide_range)
    monkeypatch.setattr(minfo.vehicles, "dataSetVersion", 500)
    widget.radar_changed(1.0)
    assert widget.shown_cars == ()
    widget.deleteLater()


def test_radar_classic_yellow_before_leader(field):
    widget = make("radar", False)
    leader = field.dataSet[0]
    leader.isYellow, leader.inPit = True, 0  # leader stopped on track
    assert widget.color_lap_diff(leader) is widget.brush_veh["yellow"]
    widget.deleteLater()


@pytest.mark.parametrize("modern", [True, False])
def test_radar_collision_course_worked_out_once(field, monkeypatch, modern):
    cars = place_radar_cars(field)
    cars[0].relativeRotatedPositionX, cars[0].relativeRotatedPositionY = 0.0, 8.0
    cars[0].relativeOrientationRadians = 0.0
    cars[0].speed = 80.0  # closing fast from behind
    widget = make("radar", modern, enable_auto_hide=False, show_collision_course=True)
    calls = []
    level = type(widget).collision_level
    monkeypatch.setattr(widget, "collision_level", lambda car: calls.append(car) or level(widget, car))
    monkeypatch.setattr(minfo.vehicles, "dataSetVersion", 600)
    widget.radar_changed(1.0)
    assert widget.shown_cars == ((cars[0], 2),)
    widget.render(QPixmap(widget.size()))
    assert calls == [cars[0]]
    widget.deleteLater()


# --- Race notifications: blue flag & red flag (findings 88, 89)
def test_race_events_blue_flag_race_only_and_red_flag(field, monkeypatch):
    from neopedal.widget.race_notifications import LOSS, RaceEvents
    from tests.test_race_aid_widgets import race

    options = ("show_position_change", "show_position_change_in_class", "show_penalty", "show_class_fastest_lap",
               "show_blue_flag", "show_full_course_yellow", "show_lap_invalidated")
    monkeypatch.setattr(minfo.vehicles, "nearestBlueClass", "Hypercar")
    monkeypatch.setitem(field_classes(), "Hypercar", {"alias": "HY", "color": "#FF0000"})
    events = RaceEvents(dict.fromkeys(options, True))
    race(monkeypatch, in_race=False)  # practice
    events.poll(0.0)
    race(monkeypatch, in_race=False, blue_flag=True)
    assert events.poll(0.1) == []
    race(monkeypatch)
    events.poll(0.2)
    race(monkeypatch, blue_flag=True)
    assert [(m.title, m.detail) for m in events.poll(0.3)] == [("Blue flag", "HY")]  # class alias
    race(monkeypatch, yellow_flag_state=2)
    assert [m.title for m in events.poll(0.4)] == ["Full course yellow"]
    race(monkeypatch, yellow_flag_state=7)
    assert [(m.title, m.kind) for m in events.poll(0.5)] == [("Red flag", LOSS)]
    race(monkeypatch, yellow_flag_state=0)
    assert [m.title for m in events.poll(0.6)] == ["Green flag"]
    race(monkeypatch, yellow_flag_state=7)  # straight from green
    assert [m.title for m in events.poll(0.7)] == ["Red flag"]


def field_classes() -> dict:
    from neopedal.setting import cfg

    return cfg.user.classes


# --- Traffic (findings 91-94)
def test_traffic_cars_leader_and_empty_entries(field, monkeypatch):
    from neopedal.widget.traffic import traffic_cars

    set_reader(monkeypatch, "timing", "estimated_laptime", 96.0)
    monkeypatch.setattr(minfo.relative, "relativeAhead", [(0.0, -1)])  # default entries: no car
    monkeypatch.setattr(minfo.relative, "relativeBehind", [(0.0, -1)])
    monkeypatch.setattr(minfo.vehicles, "leaderIndex", -1)
    assert traffic_cars() == ((0.0, 0.0, -1), (0.0, 0.0, -1), (0.0, 0.0, -1))
    monkeypatch.setattr(minfo.vehicles, "leaderIndex", field.playerIndex)  # player leads: no leader to watch
    assert traffic_cars()[1] == (0.0, 0.0, -1)


def test_classic_traffic_cells_keyed_on_text(field):
    widget = make("traffic", False, decimal_places_time_interval=1)
    time_cell, laps_cell = widget.bar_time[0], widget.bar_laps[0]
    widget.update_time(time_cell, 1.234)
    widget.update_laps(laps_cell, 0.0, 1.0)
    repaints = []
    time_cell.update = laps_cell.update = lambda: repaints.append(1)
    widget.update_time(time_cell, 1.236)  # same text
    widget.update_laps(laps_cell, -0.5, 1.0)  # placeholder both times
    assert not repaints
    widget.update_time(time_cell, 1.36)
    assert time_cell.text == "1.4s" and len(repaints) == 1
    widget.deleteLater()


def test_modern_traffic_without_values_shows_class(field, monkeypatch):
    set_reader(monkeypatch, "timing", "estimated_laptime", 96.0)
    widget = make("traffic", True, show_estimated_laps=False, show_time_interval=False, show_class=True,
                  show_driver_name_instead_of_class=False)
    value = widget.traffic_value((1.5, 3.2, 2), 0.5)
    assert value.text == "LMP2" and not value.sub  # class, no time
    widget.deleteLater()
