"""Session debrief: stint laps, pace, theoretical best, personal best, corners to work on"""

import pytest

from neopedal.userfile.driver_history import SessionRecord
from neopedal.userfile.session_debrief import (
    DebriefLap,
    build_debrief,
    corner_tips,
    pace_of,
    stint_folder,
    theoretical_best,
)
from tests.test_lap_viewer_e2 import lap_info, write_lap

START = 1_700_000_000.0  # stint start
TRACK, CLASS = "Track", "GT3"


def record(end: float = START + 600, best: float = 90.0, seconds: float = 600.0, **values) -> SessionRecord:
    data = {"time": end, "track": TRACK, "vehicle": "GT3 - Brand", "session": 1, "best": best, "valid": 3,
            "invalid": 1, "meters": 15000.0, "seconds": seconds, "vehicle_class": CLASS}
    data.update(values)
    return SessionRecord(**data)


def lap(time: float, valid: bool = True, sectors=(), fuel: float = 2.0) -> DebriefLap:
    return DebriefLap(path=f"{time}", number=1, time=time, valid=valid, sectors=tuple(sectors), fuel=fuel)


def save(folder, number, lap_time, timestamp, brake=0.45, valid=True, **info):
    """Lap of stint (combo "Track - GT3"), info values changed"""
    from neopedal.module import module_recorder

    if valid:
        write_lap(folder, number, lap_time, brake=brake, info=lap_info(**info), timestamp=timestamp,
                  combo=f"{TRACK} - {CLASS}")
    else:  # invalid lap: same lap, file marked invalid
        rows = [tuple(0 for _ in module_recorder.CSV_HEADER)] * 3
        module_recorder.save_lap(f"{folder}/", f"{TRACK} - {CLASS}", number, lap_time, rows, 50, valid=False,
                                 info=lap_info(**info), timestamp=timestamp)


def test_pace_and_consistency_of_laps_close_to_best():
    laps = [lap(90.0), lap(90.4), lap(90.8), lap(99.0), lap(89.0, valid=False)]
    pace, spread, count = pace_of(laps, 90.0)
    assert count == 3  # 99 s (over 103%) and invalid lap left out
    assert pace == pytest.approx(90.4)
    assert spread == pytest.approx(0.3266, abs=0.001)
    assert pace_of([lap(90.0)], 90.0) == (0.0, 0.0, 1)  # one lap: no pace


def test_theoretical_best_sums_best_sectors_of_valid_laps():
    laps = [lap(90.0, sectors=(30.0, 30.5, 29.5)), lap(90.2, sectors=(29.8, 30.9, 29.5)),
            lap(85.0, valid=False, sectors=(25.0, 30.0, 30.0))]
    assert theoretical_best(laps) == pytest.approx(29.8 + 30.5 + 29.5)
    assert theoretical_best([lap(90.0)]) == 0.0


def test_stint_folder_needs_class():
    assert stint_folder("telemetry", record()).endswith("Track - GT3")
    assert stint_folder("telemetry", record(vehicle_class="")) == ""  # older record: laps unknown


def test_debrief_of_stint_against_older_personal_best(tmp_path):
    folder = str(tmp_path)
    save(folder, 5, 89.5, START - 86400, brake=0.47)  # yesterday: personal best lap (brakes later)
    save(folder, 1, 91.0, START + 100, sectors=[30.2, 30.6, 30.2], fuel_start=50.0, fuel_end=47.9)
    save(folder, 2, 90.0, START + 200, brake=0.45, sectors=[30.0, 30.4, 29.6], fuel_start=47.9, fuel_end=45.8)
    save(folder, 3, 90.5, START + 300, sectors=[29.9, 30.7, 29.9], fuel_start=45.8, fuel_end=43.7)
    save(folder, 4, 95.0, START + 400, valid=False)
    save(folder, 1, 80.0, START + 5000)  # later stint: not this one
    earlier = record(end=START - 86000, best=89.5)
    debrief = build_debrief(record(), [earlier, record()], folder)
    assert [item.number for item in debrief.laps] == [1, 2, 3, 4]
    assert debrief.best == 90.0
    assert debrief.pace == pytest.approx(90.5)
    assert debrief.pace_laps == 3
    assert debrief.theoretical == pytest.approx(29.9 + 30.4 + 29.6)
    assert debrief.previous_best == 89.5 and debrief.previous_stint_best == 89.5
    assert not debrief.new_personal_best
    assert debrief.gain == pytest.approx(0.5)
    assert debrief.fuel_per_lap == pytest.approx(2.1)
    assert debrief.reference_kind == "personal_best"
    assert debrief.reference_path.endswith("lap005 1m29.500s.csv")
    assert debrief.compared_path == debrief.best_path
    tips = corner_tips(debrief.reference_path, debrief.compared_path, TRACK)
    assert tips  # brakes earlier than personal best lap in the slow corner
    assert tips[0].loss > 0
    assert tips[0].causes[0][0] == "brake_early"


def test_debrief_of_new_personal_best_compares_typical_lap(tmp_path):
    folder = str(tmp_path)
    save(folder, 5, 92.0, START - 86400)  # older laps all slower
    save(folder, 1, 90.0, START + 100, brake=0.45)
    save(folder, 2, 90.6, START + 200, brake=0.43)
    save(folder, 3, 90.9, START + 300, brake=0.43)
    debrief = build_debrief(record(), [record(end=START - 86000, best=92.0), record()], folder)
    assert debrief.new_personal_best
    assert debrief.gain == pytest.approx(-2.0)
    assert debrief.reference_kind == "stint_best"
    assert debrief.reference_path == debrief.best_path
    assert "lap002" in debrief.compared_path or "lap003" in debrief.compared_path


def test_debrief_without_recorded_laps(tmp_path):
    debrief = build_debrief(record(best=0.0), [], str(tmp_path))
    assert debrief.laps == () and debrief.best == 0.0 and debrief.pace == 0.0
    assert not debrief.new_personal_best
    assert debrief.reference_kind == "" and corner_tips("", "", TRACK) == []


def test_first_lap_time_ever_is_personal_best(tmp_path):
    assert build_debrief(record(best=91.0), [], str(tmp_path)).new_personal_best
    assert build_debrief(record(best=91.0), [], str(tmp_path), personal_best=91.0).new_personal_best


def test_faster_personal_best_of_stats_counts_without_history(tmp_path):
    """History without the older faster stint (dropped over limit, imported stats): stats best still counts"""
    debrief = build_debrief(record(best=91.0), [], str(tmp_path), personal_best=90.2)
    assert not debrief.new_personal_best
    assert debrief.previous_best == 90.2 and debrief.gain == pytest.approx(0.8)
    known = build_debrief(record(best=91.0), [record(end=START - 1000, best=90.0)], str(tmp_path), personal_best=90.0)
    assert known.previous_best == 90.0
