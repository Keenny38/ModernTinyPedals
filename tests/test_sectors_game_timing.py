"""Sector times as the game reports them: sector index may change before the game sets the time of the sector
just finished (last lap time & sector 2 of lap before still reported), overlays wait for it, never show the
time or gap of lap before
"""

import pytest

from neopedal.calculation import sec2laptime
from neopedal.const_common import MAX_SECONDS
from neopedal.module import module_sectors
from neopedal.module_info import SectorData, minfo
from tests.test_audit_sweep_fixes import reader, widgets  # noqa: F401
from tests.test_module_timing import tele  # noqa: F401


def lap(values, gen, s1: float, s2: float):
    """Sector 2 & 3 of a lap"""
    values.update({"lap.sector_index": 1, "timing.current_sector1": s1})
    gen.send(0)
    values.update({"lap.sector_index": 2, "timing.current_sector2": s1 + s2})
    gen.send(0)


def cross(values, gen, last_laptime: float, last_sector2: float):
    """Finish line crossed, game last lap data as given"""
    values.update({"lap.sector_index": 0, "timing.current_sector1": -1.0, "timing.current_sector2": -1.0,
                 "timing.last_laptime": last_laptime, "timing.last_sector2": last_sector2})
    gen.send(0)


# --- Module
def test_sector3_waits_for_game_last_lap_data(tele, tmp_path):  # noqa: F811
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    cross(tele, gen, -1.0, -1.0)
    lap(tele, gen, 30.0, 40.0)
    cross(tele, gen, 90.0, 70.0)
    assert session.sectorPrev[2] == pytest.approx(20.0)
    assert session.recordedIndex == session.sectorIndex == 0
    lap(tele, gen, 29.0, 40.0)
    # Sector index of new lap reported, last lap time & sector 2 still of lap before
    cross(tele, gen, 90.0, 70.0)
    assert session.sectorIndex == 0
    assert session.recordedIndex == 2  # S3 not recorded yet
    assert session.sectorPrev[2] == pytest.approx(20.0)
    assert session.sectorBestTB[2] == pytest.approx(20.0)
    # Game sets lap just finished
    cross(tele, gen, 88.0, 69.0)
    assert session.recordedIndex == 0
    assert session.sectorPrev == pytest.approx([29.0, 40.0, 19.0])
    assert session.deltaSectorBestTB[2] == pytest.approx(-1.0)
    assert session.sectorBestTB == pytest.approx([29.0, 40.0, 19.0])
    assert alltime.sectorBestPB == pytest.approx([29.0, 40.0, 19.0])


def test_personal_best_sectors_only_from_sectors_of_same_lap(tele, tmp_path):  # noqa: F811
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    cross(tele, gen, -1.0, -1.0)
    lap(tele, gen, 30.0, 40.0)
    cross(tele, gen, 90.0, 70.0)
    assert session.sectorBestPB == pytest.approx([30.0, 40.0, 20.0])
    # S1 of next lap given by game only in sector 3: S1 of lap before never taken as S1 of an 85 s lap
    tele.update({"lap.sector_index": 1, "timing.current_sector1": -1.0})
    gen.send(0)
    tele.update({"lap.sector_index": 2, "timing.current_sector1": 29.5, "timing.current_sector2": 69.0})
    gen.send(0)
    cross(tele, gen, 85.0, 69.0)
    assert session.sectorPrev == pytest.approx([30.0, 39.5, 16.0])  # S1 of lap before
    assert session.sectorBestPB == pytest.approx([30.0, 40.0, 20.0])
    assert session.sectorBestTB == pytest.approx([30.0, 39.5, 16.0])  # S2 & S3 themselves are valid


def drive_laps(values, gen, laps, pits_at_line: bool = False):
    """Laps (S1, S2, S3, sectors with pit lane visit: 0 = S1) from line, lap start time set at each line"""
    start, last_laptime, last_sector2 = 10.0, -1.0, -1.0
    for s1, s2, s3, pits in laps:
        values.update({"timing.start": start, "timing.current_laptime": 5.0, "vehicle.in_pits": 0 in pits})
        cross(values, gen, last_laptime, last_sector2)
        values["vehicle.in_pits"] = 1 in pits
        values.update({"lap.sector_index": 1, "timing.current_sector1": s1})
        gen.send(0)
        values["vehicle.in_pits"] = 2 in pits
        values.update({"lap.sector_index": 2, "timing.current_sector2": s1 + s2})
        gen.send(0)
        start, last_laptime, last_sector2 = start + s1 + s2 + s3, s1 + s2 + s3, s1 + s2
    values.update({"timing.start": start, "vehicle.in_pits": pits_at_line})
    cross(values, gen, last_laptime, last_sector2)


def test_out_lap_sectors_on_track_count(tele, tmp_path):  # noqa: F811
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    # Out lap: S1 from garage through pit lane, S2 & S3 on track; next lap slower in S2 & S3
    drive_laps(tele, gen, [(35.0, 40.0, 20.0, {0}), (30.0, 45.0, 25.0, ())])
    assert session.sectorBestTB == pytest.approx([30.0, 40.0, 20.0])
    assert alltime.sectorBestTB == pytest.approx([30.0, 40.0, 20.0])
    # Personal best sectors never from out lap (95 s with pit lane), from lap after it
    assert session.sectorBestPB == pytest.approx([30.0, 45.0, 25.0])


def test_in_lap_sectors_on_track_count(tele, tmp_path):  # noqa: F811
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    # In lap: S1 & S2 on track, pit lane entered in S3, line crossed in pit lane
    drive_laps(tele, gen, [(30.0, 40.0, 20.0, ()), (29.0, 39.0, 21.0, {2})], pits_at_line=True)
    assert session.sectorBestTB == pytest.approx([29.0, 39.0, 20.0])
    assert session.sectorBestPB == pytest.approx([30.0, 40.0, 20.0])  # 89 s in lap never personal best


def test_pit_lane_at_line_marks_s1_of_new_lap(tele, tmp_path):  # noqa: F811
    session, alltime = SectorData(), SectorData()
    gen = module_sectors.record_sectors(session, alltime, f"{tmp_path}/")
    tele.update({"timing.start": 10.0, "timing.current_laptime": 5.0})
    cross(tele, gen, -1.0, -1.0)
    lap(tele, gen, 30.0, 40.0)
    # Line crossed in pit lane: lap start time updated, sector index of lap before still reported a moment
    tele.update({"timing.start": 100.0, "timing.current_laptime": 0.5, "vehicle.in_pits": True})
    gen.send(0)
    tele["timing.current_laptime"] = 5.0
    cross(tele, gen, 90.0, 70.0)
    # Out lap goes on: S1 in pit lane, S2 & S3 on track
    tele["vehicle.in_pits"] = False
    lap(tele, gen, 45.0, 39.0)
    tele["timing.start"] = 200.0
    cross(tele, gen, 103.0, 84.0)
    # S3 of out lap counts (pit lane at line is its S1, not its S3)
    assert session.sectorBestTB == pytest.approx([30.0, 39.0, 19.0])


def test_no_personal_best_gap_without_personal_best_lap():
    output = SectorData()
    output.sectorBestTB[:] = [30.0, 40.0, 20.0]  # best sectors known, no complete best lap yet
    module_sectors.calc_sector_time(output, 1, 0, -1.0, 29.0, -1.0, -1.0)
    assert output.noDeltaSector is False
    assert output.noDeltaSectorPB is True
    assert output.recordedIndex == output.sectorIndex == 1


# --- Overlays
@pytest.fixture
def sector_data(monkeypatch):
    data = SectorData()
    data.sectorBestTB[:] = [30.0, 40.0, 20.0]
    data.sectorBestPB[:] = [30.0, 40.0, 20.0]
    data.sectorPrev[:] = [30.0, 40.0, 20.0]
    data.noDeltaSector = data.noDeltaSectorPB = False
    monkeypatch.setattr(minfo.sectors, "sessionBest", data)
    monkeypatch.setattr(minfo.sectors, "allTimeBest", data)
    return data


def shown(widget, modern: bool):
    """Sector tiles text, current time text"""
    if modern:
        return [tile[1] for tile in widget.tiles], widget.current[1]
    return [bar.text for bar in widget.bars_time_gap], widget.bar_time_curr.text


def drive(widget, monkeypatch, data, elapsed: float, index: int, recorded: int):
    reader(monkeypatch, "timing", "elapsed", elapsed)
    data.sectorIndex = index
    data.recordedIndex = recorded
    widget.timerEvent(None)


@pytest.mark.parametrize("modern", [True, False])
def test_sector_gap_shown_once_game_sets_sector_time(widgets, monkeypatch, sector_data, modern):  # noqa: F811
    widget = widgets("sectors", modern=modern, target_laptime="Theoretical", enable_all_time_best_sectors=False)
    reader(monkeypatch, "timing", "start", 0.0)
    data = sector_data
    data.sectorPrev[0] = 29.9
    data.deltaSectorBestTB[:] = [-0.1, 0.5, 0.3]  # S2 & S3 gaps of lap before
    drive(widget, monkeypatch, data, 31.0, 1, 1)
    tiles, current = shown(widget, modern)
    assert "-0.100" in tiles[0]
    assert sec2laptime(29.9) in current  # frozen at S1 time
    # Sector 3 reached, sector 2 time not set by game yet: gap of lap before never shown
    drive(widget, monkeypatch, data, 71.0, 2, 1)
    tiles, _ = shown(widget, modern)
    assert all("+0.500" not in text for text in tiles)
    # Game sets sector 2
    data.sectorPrev[1] = 39.8
    data.deltaSectorBestTB[1] = -0.2
    drive(widget, monkeypatch, data, 71.2, 2, 2)
    tiles, current = shown(widget, modern)
    assert "-0.200" in tiles[1]
    assert sec2laptime(29.9 + 39.8) in current  # frozen at S1 + S2 time


@pytest.mark.parametrize("modern", [True, False])
def test_lap_without_game_time_shows_best_sectors_again(widgets, monkeypatch, sector_data, modern):  # noqa: F811
    widget = widgets("sectors", modern=modern, target_laptime="Theoretical", enable_all_time_best_sectors=False,
                     freeze_duration=3)
    reader(monkeypatch, "timing", "start", 0.0)
    data = sector_data
    data.deltaSectorBestTB[:] = [0.1, 0.2, 0.7]
    drive(widget, monkeypatch, data, 71.0, 2, 2)
    tiles, _ = shown(widget, modern)
    assert "+0.200" in tiles[1]
    # Line crossed, game never sets S3 (invalid lap): stale S3 gap (+0.700) never shown
    reader(monkeypatch, "timing", "start", 90.0)
    drive(widget, monkeypatch, data, 90.5, 0, 2)
    assert all("+0.700" not in text for text in shown(widget, modern)[0])
    drive(widget, monkeypatch, data, 94.0, 0, 2)  # freeze duration passed
    tiles, _ = shown(widget, modern)
    assert all(sec2laptime(best) in text for best, text in zip((30.0, 40.0, 20.0), tiles, strict=True))


@pytest.mark.parametrize("modern", [True, False])
def test_no_gap_without_best_to_compare_with(widgets, monkeypatch, sector_data, modern):  # noqa: F811
    widget = widgets("sectors", modern=modern, target_laptime="Personal", enable_all_time_best_sectors=False)
    reader(monkeypatch, "timing", "start", 0.0)
    data = sector_data
    data.sectorBestPB[:] = [MAX_SECONDS] * 3
    data.noDeltaSectorPB = True
    data.deltaSectorBestPB[:] = [0.0, 0.0, 0.0]
    drive(widget, monkeypatch, data, 31.0, 1, 1)
    tiles, _ = shown(widget, modern)
    assert all("+0.000" not in text for text in tiles)
