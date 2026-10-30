"""Standings overlay audit of 2026-10-30 (audit_overlay_standings_2026-10-30.md): one test per finding fixed"""

# ruff: noqa: F811  (fixtures imported from the audit C tests: redefined as test parameters)

import pytest
from PySide6.QtCore import QTimerEvent
from PySide6.QtGui import QPixmap
from test_module_vehicles_field import field  # noqa: F401 (fixture)
from test_overlay_audit_2026_10_29_C import list_field, make_widget  # noqa: F401 (fixture)
from test_standings_gaps_columns import practice_field

from neopedal.i18n.options import option_help_english, option_help_specific
from neopedal.module import module_vehicles
from neopedal.module.module_relative import calc_standings_index
from neopedal.module_info import minfo
from neopedal.widget._modern.base import laptime_text
from neopedal.widget._modern.drivers import RANK_LETTERS, Context, rank_modules, running_limit
from neopedal.widget._modern.table import CENTER

RACE = Context(in_race=True, player=None, player_pit_request=False, now=1000.0)
PRACTICE = Context(in_race=False, player=None, player_pit_request=False)


# 1 - finished or garage cars: last lap, not an empty pit time
def test_modern_finished_or_garage_car_shows_last_lap(list_field, monkeypatch):
    widget = make_widget("standings", True, monkeypatch)
    try:
        veh = minfo.vehicles.dataSet[2]
        veh.lastLapTime = veh.bestLapTime = 95.5
        veh.isValidLap = True
        veh.lapStartTime = 100.0  # lap start long gone (car in the garage)
        veh.pitTimer.pitting, veh.pitTimer.elapsed = True, 0.0
        veh.inPit, veh.isFinished = 2, False  # in the garage during the race
        assert widget.laptime_cell(veh, RACE).text == laptime_text(95.5)
        veh.inPit, veh.isFinished = 1, True  # finished, driving back to the pits
        veh.pitTimer.elapsed = 12.3
        assert widget.laptime_cell(veh, RACE).text == laptime_text(95.5)
        veh.isFinished = False  # pit lane during the race: pit time
        assert widget.laptime_cell(veh, RACE).text == "PIT 12.3"
    finally:
        widget.deleteLater()


def test_classic_finished_car_shows_last_lap(list_field, monkeypatch):
    widget = make_widget("standings", False, monkeypatch, show_laptime=True, show_best_laptime=False)
    try:
        monkeypatch.setattr(minfo.relative, "standings", [0, 1, -1])
        veh = minfo.vehicles.dataSet[1]
        veh.lastLapTime = veh.bestLapTime = 95.5
        veh.isValidLap = True
        veh.pitTimer.pitting, veh.pitTimer.elapsed, veh.inPit, veh.isFinished = True, 0.0, 2, True
        widget.timerEvent(QTimerEvent(0))
        assert widget.bars_lpt[1].text == "1:35.500"
    finally:
        widget.deleteLater()


# 2 - race gaps of finished cars kept as they were at the line
def test_race_gaps_of_finished_cars_kept(monkeypatch):
    output = practice_field([0.0] * 3, ["LMP2"] * 3)
    output.leaderIndex = 0
    for index, progress in enumerate((10.60, 10.55, 10.50)):
        output.dataSet[index].totalLapProgress = progress
    gaps = {(0, 1): 3.2, (1, 2): 3.6}
    monkeypatch.setattr(module_vehicles, "race_gap", lambda cars, total, ahead, index, now: gaps.get((ahead, index), 0.0))
    cars = output.dataSet[:3]
    cars[0].isFinished = cars[1].isFinished = True  # crossed the line since last update
    module_vehicles.update_race_gaps(output, 100.0)
    assert [car.gapBehindLeader for car in cars] == pytest.approx([0.0, 3.2, 6.8])
    gaps.clear()  # first two cars in the garage: nothing to time anymore
    module_vehicles.update_race_gaps(output, 110.0)
    assert [car.gapBehindNext for car in cars] == pytest.approx([0.0, 3.2, 0.0])  # third car still racing
    assert [car.gapBehindLeader for car in cars] == pytest.approx([0.0, 3.2, 3.2])
    gaps[(1, 2)] = 4.0
    cars[2].isFinished = True
    module_vehicles.update_race_gaps(output, 120.0)
    gaps.clear()
    module_vehicles.update_race_gaps(output, 130.0)
    assert cars[2].gapBehindNext == pytest.approx(4.0) and cars[2].gapBehindLeader == pytest.approx(7.2)
    assert cars[2].gapBehindNextInClass == pytest.approx(4.0) and cars[2].gapBehindLeaderInClass == pytest.approx(7.2)
    for car in cars:  # new session
        car.isFinished = False
    module_vehicles.update_race_gaps(output, 140.0)
    assert [car.gapBehindLeader for car in cars] == [0.0, 0.0, 0.0] and not any(car.gapsFrozen for car in cars)


# 3 - rank column as wide as the widest rank letter (Bronze was elided)
def test_rank_column_fits_every_rank_letter(list_field, monkeypatch):
    widget = make_widget("standings", True, monkeypatch, column_driver_ranks=True)
    try:
        assert widget.rank_width >= max(widget.text_width("value", f"{letter}3") for letter in RANK_LETTERS)
        assert "B" in RANK_LETTERS
    finally:
        widget.deleteLater()


# 4 - option help inherited from Relative (Standings) and Standings & Relative (Rivals)
def test_option_help_inherited():
    text = option_help_english("relative", "show_position")
    assert text and option_help_english("standings", "show_position") == text
    assert option_help_english("rivals", "column_laptime") == option_help_english("relative", "column_laptime") != ""
    assert option_help_specific("standings", "show_running_lap_time")
    assert option_help_english("standings", "time_interval_width")
    assert option_help_english("standings", "mixed_compound_symbol")
    assert "Stops" not in option_help_english("standings", "show_column_headers")


# 5 - classic: brand logo read in background never drawn in a class separator row
def test_classic_logo_not_drawn_in_separator_row(list_field, monkeypatch):
    widget = make_widget("standings", False, monkeypatch, split_gap=5, show_brand_logo=True)
    try:
        minfo.vehicles.dataSet[0].vehicleBrand = minfo.vehicles.dataSet[-1].vehicleBrand = "Porsche"
        monkeypatch.setattr(minfo.relative, "standings", [0, 1, -1, 2, 3, -1])
        widget.timerEvent(QTimerEvent(0))
        pixmap = QPixmap(10, 10)
        widget.brand_logo_arrived("Porsche", pixmap)
        assert widget.bars_brd[0].image is pixmap  # row of car 0
        assert widget.bars_brd[2].image is None  # separator row
        assert widget.bars_brd[5].image is None  # hidden row
    finally:
        widget.deleteLater()


# 6 - strength of field: ranks polled only while class headers show it
@pytest.mark.parametrize(("options", "polled"), [
    ({"show_class_header": False}, False),
    ({"enable_multi_class_split_mode": False, "enable_single_class_exclusive_mode": False}, False),
    ({"show_class_header": True, "enable_multi_class_split_mode": True}, True),
])
def test_sof_polls_ranks_only_when_shown(list_field, monkeypatch, options, polled):
    import neopedal.rank_info as rank_info
    from neopedal.widget._modern import drivers

    calls = []
    monkeypatch.setattr(rank_info, "poll_field", lambda names: calls.append(list(names)))
    monkeypatch.setattr(drivers, "drawing_demo", lambda: False)
    widget = make_widget("standings", True, monkeypatch, show_class_sof=True, column_driver_ranks=False,
                         column_driver_badge=False, **options)
    try:
        assert widget.class_sof == polled
        widget.poll_ranks(minfo.vehicles.dataSet)
        assert bool(calls) == polled
    finally:
        widget.deleteLater()


# 7 - interval outside race: dash while the car ahead has no time
def test_modern_interval_outside_race_without_time_ahead(list_field, monkeypatch):
    widget = make_widget("standings", True, monkeypatch, enable_multi_class_split_mode=True)
    try:
        veh = minfo.vehicles.dataSet[1]
        veh.bestLapTime, veh.positionInClass = 100.0, 2
        veh.gapBehindNextInClass = 0.0  # car ahead without time: vehicles module gives 0
        assert widget.extra_cell("time_interval", veh, PRACTICE, {}).text != "0.0"
        veh.gapBehindNextInClass = 0.5
        assert widget.extra_cell("time_interval", veh, PRACTICE, {}).text == "0.5"
    finally:
        widget.deleteLater()


# 8 - laps behind without sign in the gap column, as the interval column
def test_modern_gap_laps_without_sign(list_field, monkeypatch):
    widget = make_widget("standings", True, monkeypatch, enable_multi_class_split_mode=False)
    try:
        veh = minfo.vehicles.dataSet[5]
        veh.positionOverall, veh.gapBehindLeader, veh.gapBehindNext = 6, 1, 1
        assert widget.gap_cell(veh, RACE).text == widget.extra_cell("time_interval", veh, RACE, {}).text == "1L"
        veh.gapBehindLeader = 2.5
        assert widget.gap_cell(veh, RACE).text == "+2.5"
    finally:
        widget.deleteLater()


# 9 - class column kept with class headers: position badge shows the overall position
@pytest.mark.parametrize(("kept", "expected"), [(True, "4"), (False, "2")])
def test_position_badge_with_class_column_kept(list_field, monkeypatch, kept, expected):
    widget = make_widget("standings", True, monkeypatch, enable_multi_class_split_mode=True, show_class_header=True,
                         show_class_column_with_class_header=kept, column_class=True)
    try:
        veh = minfo.vehicles.dataSet[3]
        veh.positionOverall, veh.positionInClass = 4, 2
        row = widget.driver_row(veh, RACE)
        keys = [column.key for column in widget.table.columns]
        assert row.cells[keys.index("position")].text == expected
        assert ("class" in keys) == kept
    finally:
        widget.deleteLater()


# 10 - gap trend column centered
def test_gap_trend_column_centered(list_field, monkeypatch):
    widget = make_widget("standings", True, monkeypatch, column_gap_trend=True)
    try:
        column = next(column for column in widget.table.columns if column.key == "gap_trend")
        assert column.align == CENTER
    finally:
        widget.deleteLater()


# 11 - places skipped between the top places and the places around the player shown apart
def test_standings_skipped_places_apart():
    class_list = [("GT3", place, place - 1, 100.0, 100.0) for place in range(1, 21)]
    assert calc_standings_index(3, 7, 12, class_list) == [0, 1, 2, -1, 9, 10, 11, 12, -1]
    assert calc_standings_index(3, 7, 2, class_list) == [0, 1, 2, 3, 4, 5, 6, -1]  # contiguous: no gap
    assert calc_standings_index(3, 7, 1, class_list[:5]) == [0, 1, 2, 3, 4, -1]


# 12 - running lap time bounded (car stopped on track or retired), none in the garage
def test_running_time_bounded(list_field, monkeypatch):
    from neopedal.widget._modern.drivers import DriverTable

    veh = minfo.vehicles.dataSet[4]
    veh.classBestLap, veh.bestLapTime, veh.inPit = 95.0, 96.0, 0
    assert running_limit(veh) == pytest.approx(285.0)
    veh.lapStartTime = 1000.0 - 100.0
    assert DriverTable.running_time(veh, RACE) == pytest.approx(100.0)
    veh.lapStartTime = 1000.0 - 290.0
    assert DriverTable.running_time(veh, RACE) == -1.0
    veh.lapStartTime, veh.inPit = 1000.0 - 100.0, 2
    assert DriverTable.running_time(veh, RACE) == -1.0
    veh.classBestLap = veh.bestLapTime = 0.0
    assert running_limit(veh) == 900.0


# 13 - rank modules imported once
def test_rank_modules_imported_once():
    assert rank_modules() is rank_modules()
    assert hasattr(rank_modules()[1], "driver_ranks")


# 2 - timing points of a finished car no longer timed (its drive to the garage would clear or pollute them)
def test_timing_points_kept_once_finished(field, monkeypatch):
    from neopedal.api_control import api

    monkeypatch.setattr(module_vehicles, "_point_times", {})
    assert api.read.session.in_race()
    data = api._api._shmmapi._shmm.data  # simulated shared memory of the field fixture
    record = data.scoring.vehScoringInfo[1]  # leader, 1200 m into its lap
    times_after = {}
    for step, (elapsed, distance, finished) in enumerate((
        (600.0, 1200.0, False), (601.0, 1300.0, False), (602.0, 1400.0, True), (603.0, 1500.0, True),
        (604.0, 1600.0, True),
    )):
        data.scoring.scoringInfo.mCurrentET = elapsed
        record.mLapDist = distance
        record.mFinishStatus = 1 if finished else 0
        module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, elapsed, True)
        times_after[step] = dict(module_vehicles._point_times[1].times)
    assert times_after[1] and times_after[2] != times_after[1]  # timed while racing, and the line crossing
    assert times_after[3] == times_after[2] == times_after[4]  # nothing more once finished
    assert field.dataSet[1].isFinished
