"""Overlay audit 2026-10-29, group C: relative, relative finish order, rivals & standings (findings 42-56)"""

from importlib import import_module

import pytest
from PySide6.QtCore import QTimerEvent

from neopedal.const_common import MAX_SECONDS
from neopedal.module_info import minfo
from neopedal.setting import cfg
from tests.test_module_relative import FIELD, entry
from tests.test_module_relative import field as relative_field  # noqa: F401  (fixture)
from tests.test_readers import lmu_api
from tests.test_widget_benchmark import fill_field


@pytest.fixture
def list_field(ui_env, monkeypatch):
    """Default settings, 8 cars field in module data, API reader on in-memory shared memory"""
    from neopedal.api_control import api

    saved = (minfo.vehicles.dataSet, minfo.vehicles.totalVehicles, minfo.vehicles.playerIndex)
    fill_field(8)
    sim, data = lmu_api()
    monkeypatch.setattr(api, "_api", sim)
    monkeypatch.setattr(api, "read", sim.reader())
    yield data
    minfo.vehicles.dataSet, minfo.vehicles.totalVehicles, minfo.vehicles.playerIndex = saved


def make_widget(name: str, modern: bool, monkeypatch, **options):
    """Widget of design with options"""
    from neopedal.widget._modern import create_widget

    monkeypatch.setitem(cfg.user.config["overlay_style"], "overlay_theme", "Modern Dark" if modern else "Legacy Dark")
    for key, value in options.items():
        monkeypatch.setitem(cfg.user.setting[name], key, value)
    return create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)


# 42 - gap trend from scratch when the followed car changes, first gap no change
def test_relative_delta_first_gap_is_reference(relative_field):  # noqa: F811
    from neopedal.module.module_relative import get_vehicles_info
    from neopedal.module_info import DeltaTimeInterval

    ahead = tuple(DeltaTimeInterval() for _ in FIELD)
    behind = tuple(DeltaTimeInterval() for _ in FIELD)
    get_vehicles_info(len(FIELD), 0, False, True, ahead, behind, [-1] * len(FIELD))
    assert ahead[3].last == pytest.approx(5.0)
    assert ahead[3].short == behind[3].short == 0.0  # not a 5 s change from 0


def test_relative_delta_reset_when_followed_car_changes(relative_field, monkeypatch):  # noqa: F811
    from neopedal.api_control import api
    from neopedal.module.module_relative import Realtime

    deltas = minfo.relative.relativeDeltaAhead
    seen: list[float] = []
    module = Realtime(cfg, "module_relative")

    def follow_other_car():
        seen.append(deltas[2].short)
        monkeypatch.setattr(api.read.vehicle, "player_index", lambda: 1)

    steps = iter((
        lambda: None,  # first tick
        lambda: setattr(deltas[2], "short", 0.5),  # trend measured, no new data: kept
        follow_other_car,
    ))

    def wait(interval):
        step = next(steps, None)
        if step is None:
            seen.append(deltas[2].short)
            return True
        step()
        return False

    module._event.wait = wait
    module.update_data()
    assert seen == [0.5, 0.0]


# 43 - few cars: each car shown once
def relative_rows(gaps: list[float], max_ahead=3, max_behind=3, laptime=100.0):
    from neopedal.widget.relative import relative_data

    ahead = sorted(((gap, index) for index, gap in enumerate(gaps)), reverse=True)
    behind = sorted(((gap - laptime, index) for index, gap in enumerate(gaps)), reverse=True)
    return [index for _, index in relative_data(ahead, behind, 99, max_ahead, max_behind)]


def test_relative_few_cars_shown_once_on_nearest_side():
    rows = relative_rows([90.0, 70.0, 30.0, 10.0])  # cars 0, 1 nearer behind, 2, 3 nearer ahead
    assert rows == [-1, 2, 3, 99, 0, 1, -1]
    assert relative_rows([5.0, 10.0, 15.0, 20.0, 25.0]) == [2, 1, 0, 99, 4, 3, -1]  # all near ahead: rows allow 3
    assert relative_rows([50.0]) == [-1, -1, 0, 99, -1, -1, -1]


def test_relative_large_field_unchanged():
    gaps = [5.0 + index * 12.0 for index in range(8)]
    # 3 nearest ahead (smallest gaps), 3 nearest behind (largest gaps), as upstream
    assert relative_rows(gaps) == [2, 1, 0, 99, 7, 6, 5]


# 44 - class colors of many classes cached
def test_random_class_color_cached_for_many_classes():
    from neopedal.formatter import random_color_class

    assert random_color_class.cache_info().maxsize >= 128
    names = [f"Mod class {number}" for number in range(60)]
    colors = [random_color_class(name) for name in names]
    hits = random_color_class.cache_info().hits
    assert [random_color_class(name) for name in names] == colors
    assert random_color_class.cache_info().hits == hits + len(names)


# 45 - empty rows of classic relative: no class pill nor pit status of last car
def test_classic_relative_empty_rows_cleared(list_field, monkeypatch):
    widget = make_widget("relative", False, monkeypatch, show_class=True, show_pit_status=True)
    try:
        last = minfo.vehicles.dataSet[-1]
        last.inPit, last.vehicleClass = 1, "GT3"
        event = QTimerEvent(0)
        widget.timerEvent(event)
        assert widget.bars_cls[0].text  # car in row
        monkeypatch.setattr(minfo.relative, "relativeAhead", [(1.2, 3)])  # rows 0 & 1 empty now
        widget.timerEvent(event)
        assert widget.bars_cls[0].text == "" and widget.bars_pit[0].text == ""
        assert widget.bars_cls[0].bg == cfg.user.setting["relative"]["background_color_class"]
        assert widget.bars_drv[2].text.strip()  # car still shown
    finally:
        widget.deleteLater()


# 49 & 50 - rivals: ahead by row, class leader keeps rival behind in second row
def test_classic_rivals_ahead_by_row_and_blank_top_row(list_field, monkeypatch):
    widget = make_widget("rivals", False, monkeypatch, show_time_interval=True, show_class=True)
    try:
        cars = minfo.vehicles.dataSet
        player = cars[minfo.vehicles.playerIndex]
        for car in cars:
            car.positionOverall = 1  # start of session: same places
        player.gapBehindNextInClass = 1.234
        cars[player.classAheadIndex].gapBehindNextInClass = 9.876
        event = QTimerEvent(0)
        widget.timerEvent(event)
        assert widget.bars_int[0].text.strip().startswith("-1.2")  # car ahead: player's interval
        assert widget.bars_int[1].text.strip().startswith("+")
        player.classAheadIndex = -1  # player leads class
        widget.timerEvent(event)
        assert widget.bars_drv[0].text == "" and not widget.bars_drv[0].isHidden()  # blank, kept in place
        assert widget.bars_int[0].text.strip() == "" and widget.bars_cls[0].text == ""
        assert widget.bars_drv[1].text.strip() == cars[player.classBehindIndex].driverName
        player.classBehindIndex = -1  # last of class too
        widget.timerEvent(event)
        assert widget.bars_drv[1].isHidden()
    finally:
        widget.deleteLater()


def test_modern_rivals_ahead_by_row(list_field, monkeypatch):
    widget = make_widget("rivals", True, monkeypatch, column_time_interval=True)
    try:
        cars = minfo.vehicles.dataSet
        player = cars[minfo.vehicles.playerIndex]
        for car in cars:
            car.positionOverall = 1
        player.gapBehindNextInClass = 1.234
        rows: list[dict] = []
        monkeypatch.setattr(widget, "driver_row", lambda veh, ctx, **extra: rows.append(extra))
        ctx = widget.context()
        widget.show_rows(cars, ctx)
        assert [extra["ahead"] for extra in rows] == [True, False]
        cell = widget.extra_cell("time_interval", cars[player.classAheadIndex], ctx, rows[0])
        assert cell.text == "-1.2" or cell.text.startswith("-1.23")
    finally:
        widget.deleteLater()


# 51 - classic standings: class separator stays empty
def test_classic_standings_separator_stays_empty(list_field, monkeypatch):
    widget = make_widget("standings", False, monkeypatch, split_gap=5, show_laptime=True)
    try:
        monkeypatch.setattr(minfo.relative, "standings", [0, 1, -1, 2, 3, -1])
        event = QTimerEvent(0)
        widget.timerEvent(event)
        assert widget.bars_drv[2].text == "" and widget.bars_drv[2].maximumHeight() == 5
        minfo.vehicles.dataSet[-1].lastLapTime = 101.5  # values of row (data of index -1) change
        minfo.vehicles.dataSet[-1].driverName = "Someone Else"
        widget.timerEvent(event)
        assert widget.bars_drv[2].text == "" and widget.bars_lpt[2].text == ""
        assert widget.bars_drv[3].text.strip()
    finally:
        widget.deleteLater()


# 52 & 55 - modern standings: best lap outside race, other cars' running time in whole seconds
def test_modern_standings_best_lap_outside_race(list_field, monkeypatch):
    from neopedal.widget._modern.base import laptime_text
    from neopedal.widget._modern.drivers import Context

    widget = make_widget("standings", True, monkeypatch, show_running_lap_time=True, column_best_laptime=False)
    try:
        veh = minfo.vehicles.dataSet[0]
        veh.bestLapTime = veh.classBestLapTime = veh.classBestLap = 95.123
        cell = widget.laptime_cell(veh, Context(in_race=False, player=None, player_pit_request=False, now=500.0))
        assert cell.text == laptime_text(95.123)
        assert cell.color == widget.theme.best
    finally:
        widget.deleteLater()


@pytest.mark.parametrize(("name", "other_text"), [("standings", "1:23"), ("relative", "1:23.5")])
def test_running_time_of_other_cars(list_field, monkeypatch, name, other_text):
    from neopedal.widget._modern.drivers import Context, running_text

    widget = make_widget(name, True, monkeypatch, show_running_lap_time=True)
    try:
        ctx = Context(in_race=True, player=None, player_pit_request=False, now=1000.0)
        cars = minfo.vehicles.dataSet
        for car in cars:
            car.lapStartTime = 1000.0 - 83.46
        other = next(car for car in cars if not car.isPlayer)
        player = next(car for car in cars if car.isPlayer)
        assert widget.laptime_cell(other, ctx).text == other_text
        assert widget.laptime_cell(player, ctx).text == "1:23.5"  # player's always precise
    finally:
        widget.deleteLater()
    assert running_text(59.99, tenths=False) == "0:59"
    assert running_text(60.0, tenths=False) == "1:00"


# 53 & 54 - module standings
def test_hidden_classes_leave_no_empty_group():
    from neopedal.module.module_relative import standings_index_from_all_classes

    classes = [entry("GT3", 3, 0, best=101.0), entry("GT3", 4, 1, best=101.0),
               entry("HY", 1, 2, best=95.0), entry("HY", 2, 3, best=95.0)]
    assert list(standings_index_from_all_classes(3, classes, "GT3", 1, 0, 5)) == [[0, 1, -1]]


def test_class_best_is_fastest_of_class(ui_env):
    from neopedal.module.module_relative import sort_class_collection, update_position_in_class

    sorted_veh_class = [
        entry("GT3", 1, 0, best=MAX_SECONDS, last=MAX_SECONDS),  # leader without time (lap 1)
        entry("GT3", 2, 1, best=110.0, last=110.0),
        entry("HY", 3, 2, best=96.0, last=96.0),
        entry("HY", 4, 3, best=95.0, last=95.0),
    ]
    update_position_in_class(sorted_veh_class, plr_index=1)
    veh_data = minfo.vehicles.dataSet
    assert [veh_data[index].classBestLapTime for index in range(4)] == [110.0, 110.0, 95.0, 95.0]
    assert sort_class_collection(sorted_veh_class[:2]) == 110.0
    assert sort_class_collection(sorted_veh_class[2:]) == 95.0


# 56 - classic standings: no time, preview display modes
def test_classic_standings_gap_without_time(list_field, monkeypatch):
    widget = make_widget("standings", False, monkeypatch)
    try:
        assert widget.gap_key_best(0.0, 95.0) == "-"
        assert widget.gap_key_best(95.5, 95.0) == 0.5
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("mode", ["exclusive", "combined", "split"])
def test_preview_standings_follow_display_mode(ui_env, mode):
    from neopedal.demo_data import FIELD as DEMO_FIELD
    from neopedal.demo_data import PLAYER, DemoSession

    setting = dict(cfg.user.setting["standings"])
    setting["enable_single_class_exclusive_mode"] = mode == "exclusive"
    setting["enable_multi_class_split_mode"] = mode == "split"
    standings = DemoSession(setting).minfo.relative.standings
    cars = [index for index in standings if index >= 0]
    player_class = DEMO_FIELD[PLAYER][2]
    assert PLAYER in cars and standings[-1] == -1
    if mode == "exclusive":
        assert all(DEMO_FIELD[index][2] == player_class for index in cars)
    elif mode == "combined":
        assert cars == sorted(cars)  # overall order, no class gap: a gap only where places are skipped
        inner = [position for position, index in enumerate(standings[:-1]) if index == -1]
        assert all(standings[position + 1] > standings[position - 1] + 1 for position in inner)
    else:
        assert standings.count(-1) > 1  # gap after each class


# 47 & 48 - relative finish order (modern): labels translated, last column key rounded as shown
def test_relative_finish_order_labels_and_pit_time_key(list_field, monkeypatch):
    from neopedal.widget._modern import relative_finish_order as rfo

    monkeypatch.setattr(rfo, "tr_overlay", lambda text: f"<{text}>")
    widget = make_widget("relative_finish_order", True, monkeypatch)
    try:
        player = minfo.vehicles.dataSet[minfo.vehicles.playerIndex]
        player.pitTimer.elapsed = 12.7
        widget.timerEvent(QTimerEvent(0))
        race_type, energy_type = widget.state[:2]
        assert race_type in ("<TIME>", "<LAPS>") and energy_type in ("<FUEL>", "<NRG>")
        assert widget.state[-1][1] == 13  # 12.7 shown as 13
    finally:
        widget.deleteLater()
