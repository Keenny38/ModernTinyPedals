"""Standings: best lap gaps outside race, gaps in class in single class mode, track limits & energy columns"""

import json

import pytest

from neopedal.const_common import MAX_SECONDS
from neopedal.module import module_vehicles
from neopedal.module_info import VehiclesInfo
from neopedal.process import driver_ranks as dr
from tests.test_modern_table_rows import new_table, sample
from tests.test_module_vehicles_field import field  # noqa: F401 (fixture)


def practice_field(bests: list[float], classes: list[str]) -> VehiclesInfo:
    """Cars in best lap order (place = index + 1), class indexes as relative module sets them"""
    output = VehiclesInfo()
    output.totalVehicles = len(bests)
    leaders: dict[str, int] = {}
    last_of_class: dict[str, int] = {}
    for index, (best, class_name) in enumerate(zip(bests, classes)):
        car = output.dataSet[index]
        car.positionOverall = index + 1
        car.bestLapTime = best
        car.classLeaderIndex = leaders.setdefault(class_name, index)
        car.classAheadIndex = last_of_class.get(class_name, -1)
        last_of_class[class_name] = index
    return output


def test_best_lap_gaps_outside_race():
    output = practice_field([90.0, 91.5, 100.2, 101.0, -1.0], ["LMP2", "LMP2", "GT3", "GT3", "GT3"])
    module_vehicles.update_best_lap_gaps(output)
    cars = output.dataSet[:5]
    assert [car.gapBehindNext for car in cars] == pytest.approx([0.0, 1.5, 8.7, 0.8, 0.0])
    assert [car.gapBehindLeader for car in cars] == pytest.approx([0.0, 1.5, 10.2, 11.0, 0.0])
    assert [car.gapBehindNextInClass for car in cars] == pytest.approx([0.0, 1.5, 0.0, 0.8, 0.0])
    assert [car.gapBehindLeaderInClass for car in cars] == pytest.approx([0.0, 1.5, 0.0, 0.8, 0.0])
    assert module_vehicles.best_lap_gap(95.0, MAX_SECONDS) == 0.0


def test_vehicle_data_outside_race_uses_best_laps(field):  # noqa: F811
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, False)
    cars = field.dataSet[:4]
    # places 2, 1, 3, 4 with best laps 95, 96, 97, 98: no gap shown when faster than car ahead
    assert [car.gapBehindNext for car in cars] == pytest.approx([0.0, 0.0, 2.0, 1.0])
    assert cars[3].gapBehindLeader == pytest.approx(2.0)


def test_vehicle_data_reads_track_limits_points(field, monkeypatch):  # noqa: F811
    from neopedal.api_control import api

    monkeypatch.setattr(type(api.read.session), "cut_points", lambda self, index=None: 0.5 * (index or 0))
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    assert [car.trackLimitsPoints for car in field.dataSet[:4]] == [0.0, 0.5, 1.0, 1.5]


def column_cells(widget, key: str) -> list:
    from neopedal.widget._modern.table import Row

    index = [column.key for column in widget.table.columns].index(key)
    return [row.cells[index] for row in widget.state if isinstance(row, Row)]


def test_track_limits_column(ui_env, bundled_fonts):
    from neopedal.setting import cfg
    from neopedal.widget._modern.table import TEXT

    cfg.user.setting["standings"]["column_track_limits"] = True
    widget = new_table(cfg, "standings")
    sample_cars, context = sample(widget)
    widget.show_field(sample_cars, context)
    limits = column_cells(widget, "track_limits")
    theme = widget.theme
    assert all(cell.kind == TEXT for cell in limits)
    shown = {cell.text: cell.color for cell in limits}
    assert shown["1.25"] == theme.warning and shown["4.25"] == theme.negative  # limit 5: red from 4
    widget.deleteLater()


def test_gaps_in_class_in_single_class_mode(ui_env, bundled_fonts):
    from neopedal.setting import cfg

    setting = cfg.user.setting["standings"]
    setting["enable_multi_class_split_mode"] = False
    setting["enable_single_class_exclusive_mode"] = True
    widget = new_table(cfg, "standings")
    assert widget.class_gap and widget.class_interval
    setting["enable_single_class_exclusive_mode"] = False
    combined = new_table(cfg, "standings")
    assert not combined.class_gap and not combined.class_interval
    widget.deleteLater()
    combined.deleteLater()


def test_race_gap_sign_and_interval_without_lap_time(ui_env, bundled_fonts):
    from neopedal.setting import cfg
    from neopedal.widget._modern.drivers import Context
    from neopedal.widget._modern.rows import DASH

    widget = new_table(cfg, "standings")
    sample_cars, context = sample(widget)
    car = next(car for car in sample_cars.vehicles if car.positionInClass > 1)
    assert widget.gap_cell(car, context).text.startswith("+")
    car.gapBehindLeaderInClass = car.gapBehindLeader = 2  # laps behind: no sign, as the interval column
    assert widget.gap_cell(car, context).text == "2L"
    practice = Context(in_race=False, player=context.player, player_pit_request=False)
    car.bestLapTime = -1.0
    assert widget.extra_cell("time_interval", car, practice, {}).text == DASH
    widget.deleteLater()


def test_track_limits_red_in_races_only(ui_env, bundled_fonts):
    from neopedal.setting import cfg

    widget = new_table(cfg, "standings")
    widget.limit = 5.0
    theme = widget.theme
    assert widget.track_limits_cell(4.25, True).color == theme.negative
    assert widget.track_limits_cell(4.25, False).color == theme.warning  # no penalty in practice & qualifying
    widget.deleteLater()


def test_ranks_of_event_registration_deep_in_file():
    """Game file layout: team members 13 levels deep, nationality in "profile" of registration driver"""
    member = {"state": "accepted", "driverId": "c", "name": "Olivier D",
              "safetyRank": {"rank": "Platinum", "tier": 2, "progress": 40}}
    driver = {"steamId": "7656", "name": "Keenny Hess", "profile": {"nationality": "FR"},
              "driverRank": {"rank": "Silver", "tier": 2, "progress": 40}}
    events = {"state": {"registeredOnlineEvents": [{"event": {"registrations": [
        {"driver": driver, "team": {"lineup": {"drivers": [member]}}}]}}]}}
    text = json.dumps({"http://127.0.0.1:6397": {"lmu.cs.registeredEvents": json.dumps(events)}})
    drivers = dr.parse_storage(text)
    assert dr.find_driver(drivers, name="Olivier D").safety == dr.Rank("Platinum", 2, 40)
    assert dr.find_driver(drivers, name="Keenny Hess").nationality == "FR"


def test_column_headers(ui_env, bundled_fonts):
    from neopedal.i18n import tr_overlay
    from neopedal.setting import cfg

    widget = new_table(cfg, "standings")
    assert widget.table.header > 0  # on by default
    labels = {column.key: column.label for column in widget.table.columns}
    assert labels["driver_name"] == "Driver" and labels["time_gap"] == "Gap"
    for column in widget.table.columns:  # column at least as wide as its label
        if column.label:
            assert column.width >= widget.text_width("label", tr_overlay(column.label)) - 0.01
    cfg.user.setting["standings"]["show_column_headers"] = False
    plain = new_table(cfg, "standings")
    assert plain.table.header == 0 and plain.table.height(3) < widget.table.height(3)
    widget.deleteLater()
    plain.deleteLater()


USAGE = {  # /rest/strategy/usage layout: energy left at end of each lap
    "Bart Busser": [{"lap": 0, "pit": False, "stint": 1, "ve": 1.0},
                    {"lap": 1, "pit": True, "stint": 1, "ve": 0.5},  # refill: left out
                    {"lap": 2, "pit": False, "stint": 1, "ve": 0.465},
                    {"lap": 3, "pit": False, "stint": 1, "ve": 0.43},
                    {"lap": 4, "pit": False, "stint": 1, "ve": 0.39}],
    "Oskar G": [{"lap": 1, "pit": False, "stint": 1, "ve": 0.8}, {"lap": 2, "pit": False, "stint": 1, "ve": 1.0}],
    "Con M": [{"lap": 1, "pit": False, "stint": 1, "ve": 0.0}, {"lap": 2, "pit": False, "stint": 1, "ve": 0.0}],
    "Keenny Hess": [{"lap": 0, "pit": False, "stint": 1, "ve": 1.0, "fuel": 0.725, "tyres": [100.0] * 4}],
    "Nobody": None,
}


def test_energy_usage_per_lap():
    from neopedal.energy_usage import EnergyUsage, parse_usage

    found = parse_usage(USAGE)
    assert set(found) == {"bart busser"}  # refill without pit flag, no virtual energy, one lap: left out
    assert found["bart busser"].last == pytest.approx(0.04)
    assert found["bart busser"].average == pytest.approx((0.035 + 0.035 + 0.04) / 3)
    assert parse_usage(None) == {} and parse_usage([]) == {}
    usage = EnergyUsage(lambda: (200, json.dumps(USAGE).encode()))
    usage.check()
    assert usage.usage(" BART BUSSER").last == pytest.approx(0.04) and usage.usage("Con M") is None


def test_energy_per_lap_column(ui_env, bundled_fonts, monkeypatch):
    from neopedal.energy_usage import LapUsage, energy_usage
    from neopedal.setting import cfg
    from neopedal.widget._modern.rows import DASH

    setting = cfg.user.setting["standings"]
    setting["column_energy_per_lap"] = True
    widget = new_table(cfg, "standings")
    sample_cars, context = sample(widget)
    widget.show_field(sample_cars, context)  # simulated values in previews
    texts = [cell.text for cell in column_cells(widget, "energy_per_lap")]
    assert any(text.endswith("%") for text in texts) and DASH in texts  # LMP2: no virtual energy
    cars = {car.driverName: car for car in sample_cars.vehicles}
    monkeypatch.setattr(energy_usage, "value", {"g. romano": LapUsage(0.0412, 0.0385)})
    widget.demo = False
    assert widget.energy_per_lap_cell(cars["G. Romano"]).text == "4.1%"  # last lap
    assert widget.energy_per_lap_cell(cars["B. Clarke"]).text == DASH
    setting["show_energy_per_lap_average"] = True
    average = new_table(cfg, "standings")
    average.demo = False
    assert average.energy_per_lap_cell(cars["G. Romano"]).text == "3.9%"  # average of last 5 laps
    assert average.table.columns[[c.key for c in average.table.columns].index("energy_per_lap")].label == "E/Lap" or \
        not average.table.header
    widget.deleteLater()
    average.deleteLater()


def test_route_poller_keeps_value_until_usable_answer():
    from neopedal.game_rest_poll import RoutePoller

    answers = [(200, b'{"a": 1}'), (500, b""), (200, b"{bad"), (200, b"null"), (0, b"")]
    now = [0.0]
    poller = RoutePoller("/rest/x", lambda data: data or {}, {}, 10.0, lambda: answers.pop(0), lambda: now[0])
    poller.check()
    assert poller.value == {"a": 1}
    poller.check()  # server error: value kept
    poller.check()  # not JSON: value kept
    assert poller.value == {"a": 1}
    poller.check()  # null outside a session
    assert poller.value == {}
    poller.value = {"b": 2}
    poller.check()  # game not running
    assert poller.value == {}


def test_race_gaps_from_timing_points():
    """Time behind = now - time the car ahead passed the same point: exact for cars of different speed, where
    game estimate (same estimated lap time for every car) is off"""
    from neopedal.module.module_vehicles import PointTimes, time_behind

    ahead, behind = PointTimes(), PointTimes()
    speed_ahead, speed_behind = 1 / 240, 1 / 260  # laps per second (Hypercar, GT3 pace)
    start_ahead, start_behind = 3.50, 3.42
    for step in range(600):  # 5 updates per second, 2 minutes
        now = step * 0.2
        ahead.update(start_ahead + now * speed_ahead, now)
        behind.update(start_behind + now * speed_behind, now)
    now = 599 * 0.2
    progress = start_behind + now * speed_behind
    exact = now - (progress - start_ahead) / speed_ahead
    assert time_behind(ahead, progress, now) == pytest.approx(exact, abs=0.01)
    assert time_behind(ahead, progress + 0.5, now) is None  # point not passed yet
    assert time_behind(None, progress, now) is None
    ahead.update(1.0, now + 1)  # went back (session restart): times dropped
    assert not ahead.times and time_behind(ahead, progress, now) is None


def test_race_gap_of_car_closer_than_a_timing_point():
    """Car ahead past the point but not the next one yet (cars 0.1 s apart): timed up to its last update, never the
    estimate fallback (values jumped between two methods)"""
    from neopedal.module.module_vehicles import TIMING_POINTS, PointTimes, time_behind

    ahead = PointTimes()
    speed = 1 / 60  # laps per second: a timing point every 0.6 s
    for step in range(99):
        now = step * 0.2
        ahead.update(5.0 + now * speed, now)
    progress_ahead = 5.0 + now * speed
    behind = progress_ahead - 0.1 * speed  # 0.1 s behind
    assert int(behind * TIMING_POINTS) == int(progress_ahead * TIMING_POINTS)  # next point not passed by car ahead
    assert time_behind(ahead, behind, now) == pytest.approx(0.1, abs=0.005)
    assert time_behind(ahead, progress_ahead + 0.001, now) is None  # not passed yet


def test_race_gaps_overall_and_class_timed_the_same_way(monkeypatch):
    """Overall gaps (game estimate before) and class gaps (timed) agree: same pair of cars, same interval"""
    output = practice_field([0.0] * 4, ["Hyper", "LMP2", "LMP2", "LMP2"])
    output.leaderIndex = 0
    speed = 1 / 60
    starts = [5.30, 5.20, 5.19, 4.10]  # car 3 lapped
    monkeypatch.setattr(module_vehicles, "_point_times", {})
    for step in range(100):
        now = step * 0.2
        for index, start in enumerate(starts):
            progress = start + now * speed
            output.dataSet[index].totalLapProgress = progress
            module_vehicles._point_times.setdefault(index, module_vehicles.PointTimes()).update(progress, now)
    estimate = module_vehicles.calc_time_gap_behind
    monkeypatch.setattr(module_vehicles, "calc_time_gap_behind", lambda ahead, behind, lap_diff: (
        estimate(ahead, behind, lap_diff) if abs(lap_diff) >= 1 else pytest.fail("timed gap expected")))
    module_vehicles.update_race_gaps(output, 99 * 0.2)
    cars = output.dataSet[:4]
    assert cars[0].gapBehindNext == cars[0].gapBehindLeader == cars[0].gapBehindNextInClass == 0.0  # leader
    assert cars[1].gapBehindNext == pytest.approx(6.0, abs=0.01)  # 0.1 lap behind car ahead overall
    assert cars[2].gapBehindNext == pytest.approx(cars[2].gapBehindNextInClass) == pytest.approx(0.6, abs=0.01)
    assert cars[2].gapBehindLeader == pytest.approx(6.6, abs=0.01)
    assert cars[2].gapBehindLeader == cars[1].gapBehindLeader + cars[2].gapBehindNext  # adds up exactly
    assert cars[2].gapBehindLeaderInClass == pytest.approx(0.6, abs=0.01)
    assert cars[3].gapBehindNext == cars[3].gapBehindNextInClass == 1 and cars[3].gapBehindLeader == 1  # laps


def test_race_gap_to_leader_is_sum_of_intervals(monkeypatch):
    """Car ahead lost time since it passed the point (screenshot: interval 3.6, gaps +3.2 & +6.2): gap to leader
    is gap of car ahead + interval, not timed apart at another point"""
    output = practice_field([0.0] * 3, ["LMP2"] * 3)
    output.leaderIndex = 0
    for index, progress in enumerate((5.60, 5.55, 5.50)):
        output.dataSet[index].totalLapProgress = progress
    gaps = {(0, 1): 3.2, (1, 2): 3.6, (0, 2): 6.2}  # timed apart: 3.2 + 3.6 != 6.2
    monkeypatch.setattr(module_vehicles, "race_gap", lambda cars, total, ahead, index, now: gaps.get((ahead, index), 0.0))
    module_vehicles.update_race_gaps(output, 100.0)
    cars = output.dataSet[:3]
    assert [car.gapBehindNext for car in cars] == pytest.approx([0.0, 3.2, 3.6])
    assert [car.gapBehindLeader for car in cars] == pytest.approx([0.0, 3.2, 6.8])
    assert [car.gapBehindLeaderInClass for car in cars] == pytest.approx([0.0, 3.2, 6.8])


def test_time_column_colors_and_energy_decimals(ui_env, bundled_fonts):
    from neopedal.setting import cfg
    from neopedal.widget._modern.drivers import Context

    cfg.user.setting["standings"]["show_running_lap_time"] = False  # best lap outside race
    widget = new_table(cfg, "standings")
    sample_cars, context = sample(widget)
    theme = widget.theme
    car = next(car for car in sample_cars.vehicles if not car.isClassFastestLastLap and car.isValidLap)
    car.bestLapTime = car.lastLapTime
    assert widget.laptime_cell(car, context).color == theme.positive  # personal best
    car.bestLapTime = car.lastLapTime - 0.5
    assert widget.laptime_cell(car, context).color == theme.caution  # personal best not improved: yellow
    practice = Context(in_race=False, player=context.player, player_pit_request=False)
    car.classBestLapTime = car.classBestLap = car.bestLapTime
    assert widget.laptime_cell(car, practice).color == theme.best  # class best lap outside race
    assert widget.row_style.energy_cell(0.4567).text == "46%"  # no decimal by default, as relative & rivals
    cfg.user.setting["standings"]["decimal_places_energy_remaining"] = 1
    fine = new_table(cfg, "standings")
    assert fine.row_style.energy_cell(0.4567).text == "45.7%"
    widget.deleteLater()
    fine.deleteLater()


def test_lap_sectors_as_game_live_timing():
    """Personal bests from completed laps only (sector beaten during lap counts once lap completed), sectors
    shown: last lap while S1 is driven, else completed sectors of current lap; outside races none on out lap,
    best lap while pitting"""
    from neopedal.module_info import LapSectors, split_sectors

    assert split_sectors(30.0, 65.0, 100.0) == pytest.approx((30.0, 35.0, 35.0))
    assert split_sectors(30.0, 65.0, -1.0) == pytest.approx((30.0, 35.0, 0.0))  # invalid lap: no S3
    sectors = LapSectors()
    sectors.update(3, 0, 0, 0, 30.0, 65.0, 100.0, True, 29.0, 63.0, 98.0)  # first update: in pit lane
    assert sectors.best == pytest.approx([29.0, 34.0, 35.0])  # game best lap & last lap meanwhile
    sectors.update(3, 1, 28.5, 0, 30.0, 65.0, 100.0, False, 29.0, 63.0, 98.0)  # left pit lane, S1 done
    assert sectors.current == (28.5, 0.0) and sectors.best[0] == 29.0  # lap not completed: no new best yet
    assert sectors.shown(True, False) == ((28.5, 0.0, 0.0), 1)
    assert sectors.shown(False, False) == ((0.0, 0.0, 0.0), -1)  # practice: out lap hidden
    assert sectors.shown(False, True) == (pytest.approx((29.0, 34.0, 35.0)), -1)  # pitting: best lap
    sectors.update(4, 0, 0, 0, 28.5, 62.0, 96.0, False, 28.5, 62.0, 96.0)  # out lap completed
    assert sectors.last_kind == "OUT" and sectors.best == pytest.approx([28.5, 33.5, 34.0])
    assert sectors.shown(True, False) == (pytest.approx((28.5, 33.5, 34.0)), -1)  # S1: last lap shown
    sectors.update(4, 2, 28.0, 61.0, 28.5, 62.0, 96.0, True, 28.5, 62.0, 96.0)  # pit entry in S3
    sectors.update(5, 0, 0, 0, 28.0, 61.0, 99.0, True, 28.5, 62.0, 96.0)
    assert sectors.last_kind == "IN" and sectors.previous_kind == "OUT"


def test_class_best_sectors_and_lap():
    from neopedal.module.module_vehicles import update_class_best_sectors

    output = practice_field([90.0, 91.0, 100.0], ["LMP2", "LMP2", "GT3"])
    for car, bests in zip(output.dataSet[:3], ([30.0, 31.0, 29.0], [29.5, 32.0, 0.0], [33.0, 30.5, 33.0])):
        car.sectors.best = bests
    for car, class_name in zip(output.dataSet[:3], ("LMP2", "LMP2", "GT3")):
        car.vehicleClass = class_name
    update_class_best_sectors(output)
    assert output.dataSet[1].classBestSectors == (29.5, 31.0, 29.0) and output.dataSet[1].classBestLap == 90.0
    assert output.dataSet[2].classBestSectors == (33.0, 30.5, 33.0) and output.dataSet[2].classBestLap == 100.0
    sectors = output.dataSet[0].sectors
    sectors.sector, sectors.current = 2, (29.2, 30.8)  # S1 & S2 beaten in lap being driven: best of class at once
    update_class_best_sectors(output)
    assert output.dataSet[1].classBestSectors == (29.2, 30.8, 29.0)
    assert sectors.best == [30.0, 31.0, 29.0]  # personal bests from completed laps only


def test_running_lap_clock():
    """Player telemetry time (smooth), scoring time once telemetry is frozen or stale (garage, monitor, spectating)"""
    from neopedal.widget._modern.drivers import session_now

    assert session_now(1000.15, 1000.0) == 1000.15
    assert session_now(980.0, 1000.0) == 1000.0  # telemetry frozen: scoring time goes on
    assert session_now(0.0, 1000.0) == 1000.0
    assert session_now(1000.15, 0.0) == 1000.15
    assert session_now(3000.0, 12.0) == 12.0  # other session


def test_laptime_cell_parts(ui_env, bundled_fonts):
    from neopedal.setting import cfg
    from neopedal.widget._modern.base import laptime_text
    from neopedal.widget._modern.drivers import Context, delta_text, lap_trend, running_text
    from neopedal.widget._modern.table import LAPTIME

    assert delta_text(0.345) == "+0.345" and delta_text(12.345) == "+12.3"
    assert lap_trend(100.0, 99.5) == 1 and lap_trend(100.0, 100.5) == -1 and lap_trend(0, 99.0) == 0
    assert running_text(83.47) == "1:23.5"
    widget = new_table(cfg, "standings")
    cars, context = sample(widget)
    theme = widget.theme
    car = next(car for car in cars.vehicles if car.isValidLap and not car.isClassFastestLastLap
               and not car.sectors.last_kind and car.sectors.sector == 0)
    car.bestLapTime = car.lastLapTime - 0.25
    cell = widget.laptime_cell(car, context)  # no session time: completed lap
    assert cell.kind == LAPTIME and cell.text == laptime_text(car.lastLapTime) and len(cell.extra.sectors) == 3
    car.lapStartTime = 100.0
    after_line = [widget.laptime_cell(car, Context(True, context.player, False, now=100.0 + seconds)).text
                  for seconds in (1.0, 5.0, 9.0)]
    # Lap, delta, then running time (other car of standings: whole seconds)
    assert after_line == [laptime_text(car.lastLapTime), "+0.250", "0:09"]
    car.lapStartTime = 0.0
    best = car.sectors.best
    car.sectors.last = (best[0], best[1], best[2] + 1.0)
    car.classBestSectors = (best[0], best[1] - 0.5, 0.0)
    parts = widget.sector_parts(car, context)
    assert [color for color, _ in parts] == [theme.best, theme.positive, theme.caution]  # purple, green, yellow (as app)
    car.sectors.sector, car.sectors.current = 1, (best[0] - 0.3, 0.0)  # S1 beaten during lap: green at once
    car.classBestSectors = (best[0] - 1.0, best[1] - 0.5, 0.0)
    parts = widget.sector_parts(car, context, running=best[0] - 0.3 + best[1] / 2)
    assert parts[0][0] == theme.positive and parts[1] == (theme.text_dim, pytest.approx(0.5)) and parts[2][0] is None
    car.classBestSectors = (best[0] - 0.3, best[1] - 0.5, 0.0)  # best of class (sectors of laps driven count)
    assert widget.sector_parts(car, context)[0][0] == theme.best
    car.sectors.current = (best[0] + 0.3, 0.0)
    assert widget.sector_parts(car, context)[0][0] == theme.caution  # personal best not improved: yellow
    car.sectors.sector = 0
    car.sectors.last_kind = "OUT"
    assert widget.laptime_cell(car, context).text == "OUT"
    car.sectors.last_kind = ""
    car.isValidLap = False
    cell = widget.laptime_cell(car, context)
    assert cell.color == theme.negative and not cell.text.startswith("*")  # invalid lap in red
    car.lapStartTime = 100.0
    assert widget.laptime_cell(car, Context(True, context.player, False, now=183.47)).text == "1:23"  # running
    assert widget.laptime_cell(car, Context(True, context.player, False, now=104.0)).text != "0:04.0"  # result first
    assert widget.table.columns[[column.key for column in widget.table.columns].index("laptime")].width < \
        widget.time_width + widget.unit * 1.2  # one time slot & trend arrow
    cfg.user.setting["standings"]["show_running_lap_time"] = False
    result = new_table(cfg, "standings")
    assert result.laptime_cell(car, Context(True, context.player, False, now=183.47)).text not in ("1:23", "1:23.5")
    car.isValidLap = True
    in_turn = [result.laptime_cell(car, Context(True, context.player, False, now=now)).text for now in (1.0, 5.0)]
    assert in_turn == [laptime_text(car.lastLapTime), "+0.250"]  # no running time: lap time & delta in turn
    widget.deleteLater()
    result.deleteLater()


def test_sector_bests_of_current_session_only():
    """Personal & class bests compared within the session: new session (laps back, session change) starts them over"""
    from neopedal.module.module_vehicles import reset_session_timing
    from neopedal.module_info import LapSectors, VehiclesInfo

    sectors = LapSectors()
    sectors.update(5, 0, 0, 0, 30.0, 65.0, 100.0, False)
    sectors.update(6, 0, 0, 0, 29.0, 63.0, 97.0, False)
    assert sectors.best == pytest.approx([29.0, 34.0, 34.0])
    sectors.update(1, 0, 0, 0, 31.0, 67.0, 103.0, False)  # next session: laps back
    assert sectors.best == pytest.approx([31.0, 36.0, 36.0])  # its own lap only, practice bests dropped
    output = VehiclesInfo()
    output.totalVehicles = 1
    car = output.dataSet[0]
    car.sectors, car.classBestSectors, car.classBestLap = sectors, (29.0, 34.0, 34.0), 97.0
    reset_session_timing(output)
    assert car.sectors.best == [0.0, 0.0, 0.0] and car.classBestSectors == (0.0, 0.0, 0.0) and car.classBestLap == 0.0
