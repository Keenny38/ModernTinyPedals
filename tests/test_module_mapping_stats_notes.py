"""Module tests: track map & pit lane mapping, driver stats, car setup backup, track & pace notes"""

from types import SimpleNamespace

import pytest

from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.module import module_mapping, module_notes, module_stats
from tinypedal.module_info import MappingInfo, NotesData, StatsInfo
from tinypedal.userfile import car_setup, driver_stats, track_notes
from tinypedal.userfile.track_map import load_track_map_file


class Group(SimpleNamespace):
    """Reader group: values from telemetry dict, unknown methods return 0"""

    def __init__(self, tele: dict, prefix: str):
        super().__init__()
        self._tele = tele
        self._prefix = prefix

    def __getattr__(self, name):
        key = f"{self._prefix}.{name}"

        def reader(index=None, *args, **kwargs):
            value = self._tele.get(key, 0)
            if callable(value):
                return value(index)
            return value
        return reader


@pytest.fixture
def tele(ui_env, monkeypatch):
    """Scripted api.read in isolated setting: set tele["group.method"] values between generator steps"""
    values: dict = {
        "session.track_name": "SimTrack",
        "vehicle.class_name": "GT3",
        "vehicle.vehicle_name": "SimCar #1",
        "lap.track_length": 4000.0,
    }
    groups = ("session", "lap", "timing", "vehicle", "inputs", "switch", "engine")
    monkeypatch.setattr(api, "read", SimpleNamespace(**{name: Group(values, name) for name in groups}))
    monkeypatch.setattr(realtime_state, "active", True)
    return values


# --- Mapping: track info (pit lane)
def test_sunlight_phase_sorted_by_time():
    # Midday halfway from sunrise to sunset, midnight halfway from sunset to next sunrise (01:00)
    assert module_mapping.set_sunlight_phase("06:00", "20:00") == (
        (1 * 3600, 3), (6 * 3600, 0), (13 * 3600, 1), (20 * 3600, 2))


def test_pit_lane_entry_exit_and_speed_saved(tele, ui_env):
    from tinypedal.setting import cfg

    output = MappingInfo()
    gen = module_mapping.record_track_info(output)
    tele.update({"vehicle.in_pits": False, "vehicle.speed": 50.0, "lap.distance": 3500.0})
    gen.send(1)
    # Enter pits at 3800 m
    tele.update({"vehicle.in_pits": True, "lap.distance": 3800.0})
    gen.send(1)
    assert output.pitEntryPosition == 3800.0
    # Limiter on, full throttle, speed settles at limit (delta under 0.1 m/s)
    tele.update({"switch.speed_limiter": 1, "inputs.throttle_raw": 1.0, "inputs.brake_raw": 0.0})
    for index, speed in enumerate((16.60, 16.65, 16.68)):
        tele.update({"vehicle.speed": speed, "lap.distance": 3810.0 + index})
        gen.send(1)
    assert output.pitSpeedLimit == pytest.approx(16.68)
    # Exit pits after start line at 300 m: lane length wraps around lap
    tele.update({"vehicle.in_pits": False, "switch.speed_limiter": 0, "vehicle.speed": 20.0, "lap.distance": 300.0})
    gen.send(1)
    assert output.pitExitPosition == 300.0
    assert output.pitLaneLength == pytest.approx(500.0)
    assert output.pitPassTime == pytest.approx(500.0 / 16.68)
    # Saved to tracks preset on next reset
    gen.send(2)
    assert cfg.user.tracks["SimTrack"]["pit_entry"] == 3800.0
    assert cfg.user.tracks["SimTrack"]["pit_exit"] == 300.0
    assert cfg.user.tracks["SimTrack"]["pit_speed"] == pytest.approx(16.68)
    assert "tracks" in ui_env  # saved config types (Setting.save replaced by a recorder)


def test_pit_speed_ignored_while_braking(tele):
    output = MappingInfo()
    gen = module_mapping.record_track_info(output)
    tele.update({"vehicle.in_pits": True, "switch.speed_limiter": 1, "inputs.throttle_raw": 1.0,
                 "inputs.brake_raw": 0.5, "vehicle.speed": 16.0, "lap.distance": 10.0})
    gen.send(1)
    tele.update({"vehicle.speed": 16.05, "lap.distance": 11.0})
    gen.send(1)
    assert output.pitSpeedLimit == 0.0


def test_track_info_waits_for_driving(tele, monkeypatch):
    output = MappingInfo()
    monkeypatch.setattr(realtime_state, "active", False)
    gen = module_mapping.record_track_info(output)
    gen.send(1)
    assert output.sunlightPhases is None  # nothing loaded until driving
    monkeypatch.setattr(realtime_state, "active", True)
    gen.send(1)
    assert output.sunlightPhases is not None


def test_pit_lane_calibration_saved_when_module_stops(tele, ui_env):
    from tinypedal.module._base import MODULE_STOP
    from tinypedal.setting import cfg

    output = MappingInfo()
    gen = module_mapping.record_track_info(output)
    tele.update({"vehicle.in_pits": False, "vehicle.speed": 50.0, "lap.distance": 3500.0})
    gen.send(1)
    tele.update({"vehicle.in_pits": True, "lap.distance": 3800.0})
    gen.send(1)
    assert "SimTrack" not in cfg.user.tracks or cfg.user.tracks["SimTrack"].get("pit_entry") != 3800.0
    tele["session.track_name"] = "Other"  # module stopping (quit, preset reload): saved, nothing reloaded
    gen.send(MODULE_STOP)
    assert cfg.user.tracks["SimTrack"]["pit_entry"] == 3800.0
    assert "Other" not in cfg.user.tracks


# --- Mapping: track map
def drive_map_lap(tele: dict, gen, lap_start: float, points: int = 40, length: float = 4000.0):
    """Drive one lap around a square, crossing sector lines at 1/3 & 2/3"""
    tele["timing.start"] = lap_start
    for index in range(points):
        distance = length * index / points
        tele.update({
            "lap.distance": distance,
            "lap.sector_index": 0 if index < points / 3 else (1 if index < points * 2 / 3 else 2),
            "vehicle.position_longitudinal": float(index),
            "vehicle.position_lateral": float(index % 7),
            "vehicle.position_vertical": 1.5,
            "timing.current_laptime": 0.5,
        })
        gen.send(1)


def test_track_map_recorded_validated_and_saved(tele, tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    output = MappingInfo()
    gen = module_mapping.record_track_map(output, filepath)
    tele.update({"timing.start": 0.0, "timing.last_laptime": -1.0})
    gen.send(1)  # no map file yet
    assert output.coordinates is None
    drive_map_lap(tele, gen, lap_start=10.0)
    # Cross finish line, valid lap time, 2 seconds into next lap
    tele.update({"timing.start": 100.0, "timing.current_laptime": 2.0, "timing.last_laptime": 90.0})
    gen.send(1)
    gen.send(1)  # saved & loaded on next step
    coords, dists, sectors = load_track_map_file(filepath, "SimTrack")
    assert coords is not None and len(coords) == 39  # lap distance 0 skipped (same as start position)
    assert dists[0] == pytest.approx((100.0, 1.5))
    assert sectors == (12, 25)  # last point before each sector line
    assert output.coordinates == coords
    assert output.sectors == sectors


def test_track_map_discarded_without_valid_lap_time(tele, tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    output = MappingInfo()
    gen = module_mapping.record_track_map(output, filepath)
    tele.update({"timing.start": 0.0, "timing.last_laptime": -1.0})
    gen.send(1)
    drive_map_lap(tele, gen, lap_start=10.0)
    # Invalid lap (no last lap time), validation window passes
    tele.update({"timing.start": 100.0, "timing.current_laptime": 2.0})
    gen.send(1)
    tele["timing.current_laptime"] = 9.0
    gen.send(1)
    gen.send(1)
    assert not (tmp_path / "SimTrack.svg").exists()


def test_track_map_discarded_for_pit_lap(tele, tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    output = MappingInfo()
    gen = module_mapping.record_track_map(output, filepath)
    tele.update({"timing.start": 0.0, "timing.last_laptime": -1.0})
    gen.send(1)
    tele["vehicle.in_pits"] = True  # lap through pit lane
    drive_map_lap(tele, gen, lap_start=10.0)
    tele["vehicle.in_pits"] = False
    tele.update({"timing.start": 100.0, "timing.current_laptime": 2.0, "timing.last_laptime": 90.0})
    gen.send(1)
    gen.send(1)
    assert not (tmp_path / "SimTrack.svg").exists()
    # Next lap without pit visit is saved
    drive_map_lap(tele, gen, lap_start=100.0)
    tele.update({"timing.start": 190.0, "timing.current_laptime": 2.0, "timing.last_laptime": 90.0})
    gen.send(1)
    gen.send(1)
    assert (tmp_path / "SimTrack.svg").exists()


def test_existing_track_map_not_recorded_again(tele, tmp_path):
    from tinypedal.userfile.track_map import save_track_map_file

    filepath = f"{tmp_path.as_posix()}/"
    save_track_map_file(filepath, "SimTrack", "0 0 10 10", ((0.0, 0.0), (5.0, 5.0)), ((0.0, 0.0), (10.0, 1.0)),
                        (0, 1), decimals=1)
    output = MappingInfo()
    gen = module_mapping.record_track_map(output, filepath)
    gen.send(1)
    assert output.coordinates == ((0.0, 0.0), (5.0, 5.0))
    assert output.lastModified > 0


# --- Stats
@pytest.fixture
def stats_env(tele, tmp_path):
    tele.update({
        "timing.start": 0.0, "timing.elapsed": 0.0, "timing.last_laptime": -1.0,
        "vehicle.in_pits": False, "vehicle.speed": 50.0, "vehicle.position_xyz": (0.0, 0.0, 0.0),
        "engine.fuel": 50.0, "session.session_type": 4, "vehicle.number_penalties": 0, "vehicle.finish_state": 0,
        "vehicle.place": 2, "vehicle.total_vehicles": 1,
    })
    return tele, f"{tmp_path.as_posix()}/"


def drive_stats_lap(tele: dict, gen, lap_start: float, laptime: float, fuel_used: float = 2.5):
    """Drive a lap in 3 steps, 1 km per step"""
    for step in range(1, 4):
        tele.update({
            "timing.elapsed": lap_start + laptime * step / 3,
            "vehicle.position_xyz": (1000.0 * (lap_start / laptime * 3 + step), 0.0, 0.0),
            "engine.fuel": tele["engine.fuel"] - fuel_used / 3,
        })
        gen.send(1)
    # Cross finish line
    tele.update({"timing.start": lap_start + laptime, "timing.last_laptime": laptime})
    tele["timing.elapsed"] = lap_start + laptime + 3
    gen.send(1)


def test_driver_stats_recorded_and_saved(stats_env):
    tele, filepath = stats_env
    output = StatsInfo()
    gen = module_stats.record_driver_stats(output, filepath, "Class", max_moved_distance=1500, podium_by_class=False)
    gen.send(1)
    tele["vehicle.position_xyz"] = (0.0, 0.0, 0.0)
    drive_stats_lap(tele, gen, 0.0, 90.0)
    drive_stats_lap(tele, gen, 90.0, 89.0)
    # Penalty, then finish 1st
    tele["vehicle.number_penalties"] = 1
    gen.send(1)
    tele.update({"vehicle.finish_state": 1, "vehicle.place": 1})
    gen.send(1)
    assert output.metersDriven > 5000
    gen.send(2)  # saved on reset
    stats = driver_stats.load_driver_stats(("SimTrack", "GT3"), filepath)
    assert stats.valid == 2
    assert stats.rb == pytest.approx(89.0) and stats.pb == pytest.approx(89.0)
    assert stats.qb == driver_stats.DriverStats().qb  # no qualifying lap
    assert stats.liters == pytest.approx(5.0)
    assert stats.penalties == 1
    assert (stats.races, stats.wins, stats.podiums) == (1, 1, 1)
    assert stats.seconds > 170


def test_driver_stats_starts_finish_position_and_history(stats_env):
    from tinypedal.userfile import driver_history

    tele, filepath = stats_env
    tele.update({"session.pre_race": True, "vehicle.place": 3})
    output = StatsInfo()
    gen = module_stats.record_driver_stats(output, filepath, "Class", max_moved_distance=1500, podium_by_class=False)
    gen.send(1)
    tele["vehicle.position_xyz"] = (0.0, 0.0, 0.0)
    gen.send(1)
    tele["session.pre_race"] = False  # green flag
    drive_stats_lap(tele, gen, 0.0, 90.0)
    tele["vehicle.finish_state"] = 1
    gen.send(1)
    tele["vehicle.class_name"] = "LMP2"  # next session vehicle already shown when saved
    gen.send(2)
    stats = driver_stats.load_driver_stats(("SimTrack", "GT3"), filepath)
    assert (stats.starts, stats.races, stats.dnf, stats.positions, stats.placed) == (1, 1, 0, 3, 1)
    assert (stats.wins, stats.podiums) == (0, 1)
    # Second race: retired
    tele.update({"vehicle.finish_state": 0, "session.pre_race": False})
    gen.send(2)
    tele["vehicle.finish_state"] = 2
    gen.send(2)
    gen.send(3)
    stats = driver_stats.load_driver_stats(("SimTrack", "LMP2"), filepath)
    assert (stats.starts, stats.races, stats.dnf) == (1, 0, 1)
    records = driver_history.load_history(filepath)
    assert [(record.vehicle, record.session, record.finish, record.position, record.vehicle_class)
            for record in records] == [
        ("GT3", 4, 1, 3, "GT3")]  # second stint: not driven (no time, no lap), not recorded
    assert records[0].best == pytest.approx(90.0) and records[0].valid == 1


def test_driver_stats_teleport_not_counted(stats_env):
    tele, filepath = stats_env
    output = StatsInfo()
    gen = module_stats.record_driver_stats(output, filepath, "Vehicle", max_moved_distance=100, podium_by_class=False)
    gen.send(1)
    tele["vehicle.position_xyz"] = (0.0, 0.0, 0.0)
    gen.send(1)
    tele["vehicle.position_xyz"] = (50.0, 0.0, 0.0)
    gen.send(1)
    tele["vehicle.position_xyz"] = (5000.0, 0.0, 0.0)  # back to pits, reset to track...
    gen.send(1)
    assert output.metersDriven == pytest.approx(50.0)


def test_stats_keys_by_classification(tele, monkeypatch):
    monkeypatch.setattr(module_stats, "select_brand_name", lambda vehicle_name: "Brand")
    assert module_stats.stats_keys("Class") == ("SimTrack", "GT3")
    assert module_stats.stats_keys("Class - Brand") == ("SimTrack", "GT3 - Brand")
    assert module_stats.stats_keys("Vehicle") == ("SimTrack", "SimCar #1")
    monkeypatch.setattr(module_stats, "select_brand_name", lambda vehicle_name: "")
    assert module_stats.stats_keys("Class - Brand") == ("SimTrack", "GT3")


def test_finish_position_in_class(tele):
    classes = ("GT3", "LMP2", "GT3", "GT3")
    places = (3, 1, 2, 4)
    tele.update({
        "vehicle.total_vehicles": 4,
        "vehicle.class_name": lambda index: "GT3" if index is None else classes[index],
        "vehicle.place": lambda index: 3 if index is None else places[index],
    })
    assert module_stats.finish_position(False) == 3
    assert module_stats.finish_position(True) == 2  # 2nd of 3 GT3


def test_save_driver_stats_keeps_best_and_adds_totals(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    keys = ("Track", "Car")
    driver_stats.save_driver_stats(keys, driver_stats.DriverStats(pb=90.0, valid=3, meters=1000.0), filepath)
    driver_stats.save_driver_stats(keys, driver_stats.DriverStats(pb=91.0, valid=2, meters=500.0), filepath)
    stats = driver_stats.load_driver_stats(keys, filepath)
    assert stats.pb == 90.0 and stats.valid == 5 and stats.meters == 1500.0
    driver_stats.save_driver_stats(("", "Car"), driver_stats.DriverStats(valid=9), filepath)  # invalid key ignored
    assert driver_stats.load_driver_stats(keys, filepath).valid == 5


def test_load_driver_stats_converts_value_type(tmp_path):
    """Hand-edited or damaged value (null, text, bool) converted or reverted to default, never kept"""
    import json

    filepath = f"{tmp_path.as_posix()}/"
    stats_file = {"Track": {"Car": {"pb": None, "meters": "12.5", "valid": "12.5", "wins": True, "races": "3", "x": 1}}}
    (tmp_path / f"driver{driver_stats.FileExt.STATS}").write_text(json.dumps(stats_file), encoding="utf-8")
    stats = driver_stats.load_driver_stats(("Track", "Car"), filepath)
    default = driver_stats.DriverStats()
    assert stats.pb == default.pb and stats.meters == 12.5 and stats.races == 3
    assert stats.valid == default.valid and stats.wins == 1
    assert all(type(getattr(stats, key)) is type(getattr(default, key)) for key in vars(default))


def test_load_driver_stats_rejects_nan_and_inf(tmp_path):
    """"nan"/"inf" text or NaN/Infinity literal: default, as a nan best lap would never improve"""
    filepath = f"{tmp_path.as_posix()}/"
    (tmp_path / f"driver{driver_stats.FileExt.STATS}").write_text(
        '{"Track": {"Car": {"pb": "nan", "qb": NaN, "rb": "-inf", "meters": Infinity, "seconds": "12.5",'
        ' "valid": "inf"}}}', encoding="utf-8")
    stats = driver_stats.load_driver_stats(("Track", "Car"), filepath)
    default = driver_stats.DriverStats()
    assert (stats.pb, stats.qb, stats.rb, stats.meters) == (default.pb, default.qb, default.rb, default.meters)
    assert stats.seconds == 12.5 and stats.valid == default.valid


def test_save_driver_stats_fixes_wrong_types(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    (tmp_path / "driver.stats").write_text('{"Track": {"Car": {"pb": -1, "valid": "4"}}}', encoding="utf-8")
    driver_stats.save_driver_stats(("Track", "Car"), driver_stats.DriverStats(pb=95.0, valid=1), filepath)
    stats = driver_stats.load_driver_stats(("Track", "Car"), filepath)
    assert stats.pb == 95.0  # invalid time replaced
    assert stats.valid == 5


def test_save_driver_stats_backs_up_unreadable_file(tmp_path, monkeypatch):
    monkeypatch.setattr(driver_stats, "sleep", lambda seconds: None)
    filepath = f"{tmp_path.as_posix()}/"
    (tmp_path / "driver.stats").write_text("not json", encoding="utf-8")
    driver_stats.save_driver_stats(("Track", "Car"), driver_stats.DriverStats(valid=1), filepath)
    assert driver_stats.load_driver_stats(("Track", "Car"), filepath).valid == 1
    assert any(path.name.startswith("driver.stats") and path.name != "driver.stats" for path in tmp_path.iterdir())


def test_validate_stats_file():
    data = {"Track": {"Car": 1, "Other": {}}, "Bad": []}
    assert driver_stats.validate_stats_file(data) == {"Track": {"Car": {}, "Other": {}}, "Bad": {}}


# --- Car setup backup
def test_car_setup_name_and_lap_time():
    assert car_setup.set_car_setup_laptime(83.456) == "1-23-456"
    assert car_setup.set_car_setup_laptime(float("inf")) == "0-00-000"
    assert car_setup.set_car_setup_filename("LMU", "", "Spa: GP", "GT3") == "LMU - Spa GP - GT3"


def test_auto_backup_car_setup_renamed_with_best_lap(tele, tmp_path, monkeypatch):
    filepath = f"{tmp_path.as_posix()}/"
    monkeypatch.setattr(module_stats, "select_brand_name", lambda vehicle_name: "Brand")
    monkeypatch.setattr(module_stats, "strftime", lambda *args: "2026-10-03 10-00-00")
    tele.update({"vehicle.in_pits": False, "vehicle.setup": ("[GENERAL]", "Wing=3"), "timing.last_laptime": -1.0})
    gen = module_stats.auto_backup_car_setup(filepath)
    gen.send(1)
    saved = list(tmp_path.glob("*.svm"))
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8").splitlines() == ["[GENERAL]", "Wing=3"]
    for laptime in (92.5, 91.25, 93.0):
        tele["timing.last_laptime"] = laptime
        gen.send(1)
    gen.send(2)  # back to garage
    names = [path.name for path in tmp_path.glob("*.svm")]
    assert len(names) == 1 and names[0].endswith(" - 1-31-250.svm")


def test_car_setup_file_helpers(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    car_setup.save_car_setup_file(filepath, "one", ("only one line",))
    assert not (tmp_path / "one.svm").exists()  # needs at least 2 lines
    car_setup.save_car_setup_file(filepath, "two", ("a", "b"))
    car_setup.rename_car_setup_file(filepath, "two", "three")
    assert (tmp_path / "three.svm").exists()
    car_setup.rename_car_setup_file(filepath, "missing", "other")  # logged, no error
    car_setup.remove_car_setup_file(filepath, "three")
    assert not (tmp_path / "three.svm").exists()


# --- Notes
NOTES = [
    {"distance": 100.0, "pace note": "L3", "comment": "", "tags": ""},
    {"distance": 400.0, "pace note": "Pit in", "comment": "", "tags": "#pit"},
    {"distance": 500.0, "pace note": "R2", "comment": "", "tags": ""},
    {"distance": 900.0, "pace note": "Hairpin", "comment": "", "tags": ""},
]


def test_filter_notes_and_tags():
    assert [note["pace note"] for note in module_notes.filter_notes(NOTES)] == ["L3", "R2", "Hairpin"]
    assert [note["pace note"] for note in module_notes.filter_tags(NOTES, "#pit")] == ["Pit in"]
    assert module_notes.filter_notes([]) == () and module_notes.filter_tags(None, "#pit") == ()
    assert module_notes.reference_position(()) == ()


def test_notes_selector_current_and_next_note():
    output = NotesData()
    gen = module_notes.notes_selector(output, module_notes.filter_notes(NOTES))
    gen.send(50.0)  # before first note: last note of lap is current, first is next
    assert output.currentNote["pace note"] == "Hairpin" and output.nextNote["pace note"] == "L3"
    gen.send(150.0)
    assert output.currentIndex == 0 and output.nextNote["pace note"] == "R2"
    gen.send(500.0)
    assert output.currentNote["pace note"] == "R2" and output.nextIndex == 2
    gen.send(950.0)  # after last note: next is first note of next lap
    assert output.currentNote["pace note"] == "Hairpin" and output.nextIndex == 0


def test_notes_selector_without_notes():
    assert module_notes.notes_selector(NotesData(), ()) is None


def test_pace_notes_manual_file_selector(tmp_path):
    filename = tmp_path / "custom.tppn"
    track_notes.save_notes_file(f"{tmp_path.as_posix()}/", "custom.tppn", track_notes.HEADER_PACE_NOTES, NOTES,
                                track_notes.create_notes_metadata())
    config = {"enable_manual_file_selector": True, "pace_notes_file_name": str(filename)}
    notes = module_notes.load_pace_notes_file(config, "ignored/", "ignored", track_notes.HEADER_PACE_NOTES,
                                              track_notes.parse_csv_notes_only, ".tppn")
    assert [note["distance"] for note in notes] == [100.0, 400.0, 500.0, 900.0]


def test_notes_csv_roundtrip_with_metadata(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    metadata = track_notes.create_notes_metadata()
    metadata.update({"TITLE": "Spa", "AUTHOR": "Me"})
    unsorted = [NOTES[2], NOTES[0], {"distance": "bad", "pace note": "x", "comment": "", "tags": ""}]
    track_notes.save_notes_file(filepath, "spa", track_notes.HEADER_PACE_NOTES, unsorted, metadata, extension=".tppn")
    notes, meta = track_notes.load_notes_file(filepath, "spa", track_notes.HEADER_PACE_NOTES, extension=".tppn")
    assert [note["pace note"] for note in notes] == ["L3", "R2"]  # sorted, invalid distance dropped
    assert meta["TITLE"] == "Spa" and meta["AUTHOR"] == "Me"


def test_notes_gpl_roundtrip(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    notes = [{"distance": 120.4, "pace note": "left3", "comment": "careful"},
             {"distance": 80.0, "pace note": "right2", "comment": ""}]
    metadata = track_notes.create_notes_metadata()
    metadata["AUTHOR"] = "Lee"
    track_notes.save_notes_file(filepath, "track.ini", track_notes.HEADER_PACE_NOTES, notes, metadata,
                                writer=track_notes.write_gpl_notes)
    loaded, meta = track_notes.load_notes_file(filepath, "track.ini", track_notes.HEADER_PACE_NOTES,
                                               parser=track_notes.parse_gpl_notes)
    assert [(note["distance"], note["pace note"], note["comment"]) for note in loaded] == [
        (80.0, "right2", ""), (120.0, "left3", "careful")]
    assert meta["AUTHOR"] == "Lee"


def test_notes_invalid_or_missing_file(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    (tmp_path / "bad.tptn").write_text("no header here\n1,2\n", encoding="utf-8")
    assert track_notes.load_notes_file(filepath, "bad", track_notes.HEADER_TRACK_NOTES, extension=".tptn") is None
    assert track_notes.load_notes_file(filepath, "missing", track_notes.HEADER_TRACK_NOTES) is None
    track_notes.save_notes_file(filepath, "empty", track_notes.HEADER_TRACK_NOTES, [], {})
    assert not (tmp_path / "empty").exists()


def test_notes_file_filters_headers_and_parsers():
    from tinypedal.const_file import FileFilter

    assert track_notes.set_notes_filter(track_notes.NOTESTYPE_PACE).startswith(FileFilter.TPPN)
    assert track_notes.set_notes_filter(track_notes.NOTESTYPE_TRACK).startswith(FileFilter.TPTN)
    assert track_notes.set_notes_header(track_notes.NOTESTYPE_PACE) == track_notes.HEADER_PACE_NOTES
    assert track_notes.set_notes_header(track_notes.NOTESTYPE_TRACK) == track_notes.HEADER_TRACK_NOTES
    assert track_notes.set_notes_header_by_filter(FileFilter.TPTN) == track_notes.HEADER_TRACK_NOTES
    assert track_notes.set_notes_header_by_filter(FileFilter.GPLINI) == track_notes.HEADER_PACE_NOTES
    assert track_notes.set_notes_header_by_filter(FileFilter.CSV) == ()
    assert track_notes.set_notes_parser(FileFilter.GPLINI) is track_notes.parse_gpl_notes
    assert track_notes.set_notes_writer(FileFilter.TPPN) is track_notes.write_csv_notes
