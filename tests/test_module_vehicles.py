"""Vehicles module tests

Gap, qualify position, finish estimate and stint usage feed the relative, standings and
timing widgets. They were untested, and every one of them is easy to get subtly wrong.
"""

import pytest

from tinypedal.api_control import api
from tinypedal.module.module_vehicles import (
    calc_gap_behind_leader,
    calc_gap_behind_next,
    calc_time_gap_behind,
    update_finish_time,
    update_qualify_position,
    update_stint_usage,
)
from tinypedal.module_info import VehicleDataSet, VehiclesInfo


def set_reader(monkeypatch, group, name, value_or_func):
    if callable(value_or_func):
        monkeypatch.setattr(getattr(api.read, group), name, value_or_func, raising=False)
    else:
        monkeypatch.setattr(getattr(api.read, group), name, lambda *a, **k: value_or_func, raising=False)


@pytest.fixture
def field(ui_env):
    """Three vehicles, player last"""
    output = VehiclesInfo()
    output.dataSet = [VehicleDataSet() for _ in range(3)]
    output.totalVehicles = 3
    output.leaderIndex = 0
    output.playerIndex = 2
    return output


# --- Gap behind
def test_no_gap_without_a_car_ahead(ui_env):
    assert calc_time_gap_behind(-1, 0, 0.0) == 0.0


def test_gap_of_a_full_lap_or_more_is_reported_as_laps(ui_env):
    assert calc_time_gap_behind(0, 1, 1.4) == 1
    assert calc_time_gap_behind(0, 1, -2.7) == 2


def test_gap_within_a_lap_is_the_time_difference(ui_env, monkeypatch):
    set_reader(monkeypatch, "timing", "estimated_time_into", lambda index: (30.0, 22.0)[index])
    assert calc_time_gap_behind(0, 1, 0.0) == pytest.approx(8.0)


def test_negative_gap_is_corrected_by_a_lap(ui_env, monkeypatch):
    """During a double-file formation lap the car ahead can momentarily read as behind"""
    set_reader(monkeypatch, "timing", "estimated_time_into", lambda index: (5.0, 95.0)[index])
    set_reader(monkeypatch, "timing", "estimated_laptime", 100.0)
    assert calc_time_gap_behind(0, 1, 0.5) == pytest.approx(10.0)


def test_lapped_cars_report_laps_not_seconds(ui_env, monkeypatch):
    set_reader(monkeypatch, "lap", "behind_next", 2)
    set_reader(monkeypatch, "timing", "behind_next", 9.9)
    assert calc_gap_behind_next(1) == 2
    set_reader(monkeypatch, "lap", "behind_next", 0)
    assert calc_gap_behind_next(1) == pytest.approx(9.9)


def test_gap_to_leader_prefers_laps_too(ui_env, monkeypatch):
    set_reader(monkeypatch, "lap", "behind_leader", 3)
    set_reader(monkeypatch, "timing", "behind_leader", 44.0)
    assert calc_gap_behind_leader(2) == 3
    set_reader(monkeypatch, "lap", "behind_leader", 0)
    assert calc_gap_behind_leader(2) == pytest.approx(44.0)


# --- Qualify position
def test_qualify_position_is_numbered_within_each_class(field, monkeypatch):
    classes = ("GT3", "LMP2", "GT3")
    overall = (4, 1, 2)
    set_reader(monkeypatch, "vehicle", "class_name", lambda index: classes[index])
    set_reader(monkeypatch, "vehicle", "qualification", lambda index: overall[index])

    update_qualify_position(field)

    assert [data.qualifyOverall for data in field.dataSet] == [4, 1, 2]
    # GT3 runners qualified 2nd and 4th overall are 1st and 2nd in class
    assert field.dataSet[2].qualifyInClass == 1
    assert field.dataSet[0].qualifyInClass == 2
    assert field.dataSet[1].qualifyInClass == 1  # only LMP2 entry


# --- Stint usage
def test_stint_estimate_uses_whichever_of_fuel_or_energy_runs_out_first(ui_env):
    data = VehicleDataSet()
    data.fuelHistory.laps = 12.0
    data.energyHistory.laps = 7.0
    data.pitTimer.laps = 3.0

    update_stint_usage(data, fuel_remaining=40.0, energy_remaining=50.0)

    assert data.currentStintLaps == 3.0
    assert data.estimatedStintLaps == pytest.approx(10.0)  # 3 done + 7 left on energy
    assert data.energyRemaining == 50.0


def test_stint_estimate_falls_back_to_fuel_without_energy(ui_env):
    data = VehicleDataSet()
    data.fuelHistory.laps = 12.0
    data.energyHistory.laps = 7.0
    data.pitTimer.laps = 3.0

    update_stint_usage(data, fuel_remaining=40.0, energy_remaining=0.0)

    assert data.estimatedStintLaps == pytest.approx(15.0)
    assert data.energyRemaining == 40.0  # fuel shown in the energy slot


def test_stint_estimate_is_absent_without_either(ui_env):
    data = VehicleDataSet()
    data.pitTimer.laps = 3.0

    update_stint_usage(data, fuel_remaining=0.0, energy_remaining=0.0)

    assert data.estimatedStintLaps == 0.0
    assert data.energyRemaining == -1


# --- Finish estimate
def test_lap_race_finishes_as_lap(field, monkeypatch):
    set_reader(monkeypatch, "session", "finish_type", 1)
    set_reader(monkeypatch, "session", "remaining", 600.0)
    set_reader(monkeypatch, "lap", "remaining", 5.0)
    field.dataSet[0].lapTimeHistory.average = 100.0
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.delta, "lapTimePace", 101.0)

    update_finish_time(field, max_finish_time_diff=10.0)

    assert field.finishTimeOffset == pytest.approx(-500.0)
    assert field.finishAsLap  # player is within the allowed difference


def test_lap_race_finishes_as_time_when_the_player_is_far_off_the_pace(field, monkeypatch):
    set_reader(monkeypatch, "session", "finish_type", 1)
    set_reader(monkeypatch, "session", "remaining", 600.0)
    set_reader(monkeypatch, "lap", "remaining", 5.0)
    field.dataSet[0].lapTimeHistory.average = 100.0
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.delta, "lapTimePace", 130.0)  # 150s slower over 5 laps

    update_finish_time(field, max_finish_time_diff=10.0)

    assert not field.finishAsLap


def test_timed_race_reports_a_lap_offset(field, monkeypatch):
    set_reader(monkeypatch, "session", "finish_type", 0)
    set_reader(monkeypatch, "session", "remaining", 600.0)
    set_reader(monkeypatch, "lap", "progress", 0.5)
    set_reader(monkeypatch, "vehicle", "pit_stop_time", 25.0)
    field.dataSet[0].lapTimeHistory.average = 100.0
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.delta, "lapTimePace", 100.0)

    update_finish_time(field, max_finish_time_diff=10.0)

    assert field.finishAsLap
    assert field.finishTimeOffset == 0.0
    assert isinstance(field.finishLapOffset, (int, float))


def test_player_leading_a_timed_race_has_no_offset(field, monkeypatch):
    set_reader(monkeypatch, "session", "finish_type", 0)
    set_reader(monkeypatch, "session", "remaining", 600.0)
    field.leaderIndex = field.playerIndex

    update_finish_time(field, max_finish_time_diff=10.0)

    assert field.finishLapOffset == 0.0


def test_timed_race_without_valid_lap_pace_has_no_offset(field, monkeypatch):
    """Formation lap & first lap: no leader lap yet (pace MAX_SECONDS), no "+664 laps" offset"""
    from tinypedal.const_common import MAX_SECONDS
    from tinypedal.module_info import minfo

    set_reader(monkeypatch, "session", "finish_type", 0)
    set_reader(monkeypatch, "session", "remaining", 3600.0)
    set_reader(monkeypatch, "lap", "progress", 0.3)
    monkeypatch.setattr(minfo.delta, "lapTimePace", 100.0)
    field.dataSet[0].lapTimeHistory.average = MAX_SECONDS
    update_finish_time(field, max_finish_time_diff=10.0)
    assert field.finishLapOffset == 0.0
    field.dataSet[0].lapTimeHistory.average = 100.0
    monkeypatch.setattr(minfo.delta, "lapTimePace", MAX_SECONDS)  # no valid player lap yet
    update_finish_time(field, max_finish_time_diff=10.0)
    assert field.finishLapOffset == 0.0
