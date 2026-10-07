"""Regression tests for audit fixes"""

import os

from tinypedal import calculation as calc
from tinypedal.userfile import atomic_write
from tinypedal.userfile.track_geometry import rest_get as real_rest_get  # replaced by conftest in tests


def test_distance_interp_between_points():
    # Halfway between (0, 0) at 100m and (10, 20) at 200m
    pos = calc.distance_interp_coordinate(10, 0, 20, 0, 200, 100, 150)
    assert pos == (5, 10)


def test_distance_interp_edge_cases():
    # Before start point, same distance points (no division by zero), past end point
    assert calc.distance_interp_coordinate(10, 0, 20, 0, 200, 100, 90) == (0, 0)
    assert calc.distance_interp_coordinate(10, 0, 20, 0, 100, 100, 100) == (0, 0)
    assert calc.distance_interp_coordinate(10, 0, 20, 0, 200, 100, 300) == (10, 20)


def test_tri_coords_angle_collinear_no_domain_error():
    # Floating point error can push cos above 1.0
    assert calc.tri_coords_angle(0.1 + 0.2 - 0.3, 1.0000000000000002, 1.0) >= 0


def test_scale_elevation_flat_track():
    coords = ((0.0, 5.0), (100.0, 5.0), (200.0, 5.0))
    calc.scale_elevation(coords, 300, 100)  # no ZeroDivisionError


def test_atomic_write(tmp_path):
    target = tmp_path / "data.csv"
    with atomic_write(str(target), newline="") as file:
        file.write("a,b\n")
    assert target.read_text(encoding="utf-8") == "a,b\n"
    assert not os.path.exists(f"{target}.tmp")


def test_atomic_write_keeps_old_file_on_error(tmp_path):
    target = tmp_path / "data.csv"
    target.write_text("old", encoding="utf-8")
    missing_dir_target = tmp_path / "missing" / "data.csv"
    with atomic_write(str(missing_dir_target)) as file:  # error is logged, not raised
        file.write("new")
    assert target.read_text(encoding="utf-8") == "old"


def test_versioned_backup(tmp_path, monkeypatch):
    from tinypedal.userfile import json_setting

    folder = f"{tmp_path}/"
    (tmp_path / "preset.json").write_text("{}", encoding="utf-8")
    assert json_setting.create_versioned_backup("preset.json", folder, max_count=2, min_interval=600)
    # Throttled: no second backup within interval
    assert not json_setting.create_versioned_backup("preset.json", folder, max_count=2, min_interval=600)
    # Keep only max_count backups
    for index in range(4):
        monkeypatch.setattr(json_setting, "set_backup_timestamp", lambda prefix, i=index: f"{prefix}-9999-{i}")
        json_setting.create_versioned_backup("preset.json", folder, max_count=2, min_interval=0)
    backups = sorted(p.name for p in tmp_path.iterdir() if ".backup-auto-" in p.name)
    assert backups == ["preset.json.backup-auto-9999-2", "preset.json.backup-auto-9999-3"]
    # Disabled
    assert not json_setting.create_versioned_backup("preset.json", folder, max_count=0)


def test_versioned_backup_without_interval_ignores_clock_resolution(tmp_path, monkeypatch):
    """No interval: backup file time ahead of time() (coarse clock, Python 3.11 on Windows) never throttles"""
    from tinypedal.userfile import json_setting

    folder = f"{tmp_path}/"
    (tmp_path / "preset.json").write_text("{}", encoding="utf-8")
    assert json_setting.create_versioned_backup("preset.json", folder, max_count=5, min_interval=0)
    backup = next(p for p in tmp_path.iterdir() if ".backup-auto-" in p.name)
    monkeypatch.setattr(json_setting, "time", lambda: backup.stat().st_mtime - 0.01)  # clock behind file time
    monkeypatch.setattr(json_setting, "set_backup_timestamp", lambda prefix: f"{prefix}-9999-0")
    assert json_setting.create_versioned_backup("preset.json", folder, max_count=5, min_interval=0)
    assert not json_setting.create_versioned_backup("preset.json", folder, max_count=5, min_interval=600)


def test_backup_timestamps_unique_with_coarse_clock(tmp_path, monkeypatch):
    """Equal clock readings (15 ms clock of Python 3.11 on Windows) never give the same backup name"""
    from tinypedal.userfile import driver_stats, json_setting

    monkeypatch.setattr(json_setting, "time", lambda: 1_700_000_000.5)
    first, second = json_setting.set_backup_timestamp(), json_setting.set_backup_timestamp()
    assert first != second and len(first) == len(second) == len(".backup-2023-11-14-22-13-20-500000")
    # Backup of an unreadable stats file is not overwritten by the temporary backup of the save
    monkeypatch.setattr(driver_stats, "sleep", lambda seconds: None)
    (tmp_path / "driver.stats").write_text("not json", encoding="utf-8")
    driver_stats.save_driver_stats(("Track", "Car"), driver_stats.DriverStats(valid=1), f"{tmp_path.as_posix()}/")
    backups = [path for path in tmp_path.iterdir() if path.name != "driver.stats"]
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "not json"


# --- Package B audit fixes: calculations
def test_session_time_rounds_whole_time():
    assert calc.sec2sessiontime(599.6) == "00:10:00"  # was "00:09:00" (minutes floored, seconds rounded)
    assert calc.sec2sessiontime(599.4) == "00:09:59"
    assert calc.sec2sessiontime(3599.5) == "01:00:00"
    assert calc.sec2sessiontime(0) == "00:00:00"
    assert calc.sec2countdown(59.6) == "0:01:00"
    assert calc.sec2countdown(7322.2) == "2:02:02"
    assert calc.sec2countdown(float("nan")) == "0:00:00"
    assert calc.sec2sessiontime(float("inf")) == "00:00:00"


def test_end_lap_pit_counts():
    assert calc.end_lap_pit_counts(0.0, 0.0, 100.0) == 0  # no fuel needed, full tank: no stop (was 1)
    assert calc.end_lap_pit_counts(-10.0, 20.0, 100.0) == 0
    assert calc.end_lap_pit_counts(10.0, 0.0, 100.0) == 1.1  # needed, tank full: this stint + 10% of a tank
    assert calc.end_lap_pit_counts(10.0, 20.0, 100.0) == 0.5
    assert calc.end_lap_pit_counts(70.0, 20.0, 100.0) == 1.5


def test_pace_note_offset_wraps_into_lap():
    from tinypedal.module.module_notes import offset_position

    assert offset_position(4950.0, 100.0, 5000.0) == 50.0  # note after finish line on time
    assert offset_position(10.0, -50.0, 5000.0) == 4960.0
    assert offset_position(100.0, 50.0, 0.0) == 150.0  # track length unknown


# --- Session
def test_same_session_rule():
    from tinypedal.validator import is_same_session, session_token

    saved = session_token((360004, 300, 3), now=10_300.0)  # session started at 10000
    assert saved == (360004, 300, 3, 10_300.0)
    assert is_same_session(saved, session_token((360004, 301, 3), now=10_301.0))
    assert is_same_session(saved, session_token((360004, 900, 9), now=11_000.0))  # paused 100 s
    assert not is_same_session(saved, session_token((360004, 100, 1), now=10_400.0))  # back in time: restart
    assert not is_same_session(saved, session_token((360004, 500, 5), now=20_500.0))  # restart, out later
    assert not is_same_session(saved, session_token((360005, 301, 3), now=10_301.0))  # other session type
    assert not is_same_session(None, saved)
    assert not is_same_session((360004, 300, 3), saved)  # old saved id without time read


def test_invalid_save_name():
    from tinypedal.validator import invalid_save_name

    assert invalid_save_name("") and invalid_save_name(" - GT3") and invalid_save_name("Track - ")
    assert invalid_save_name("Track -")  # class name missing, trailing space stripped
    assert not invalid_save_name("Track - GT3")


def test_strict_json_for_untrusted_text():
    import pytest

    from tinypedal.validator import load_json_strict

    assert load_json_strict('{"a": 1.5, "b": [1, 2]}') == {"a": 1.5, "b": [1, 2]}
    for text in ('{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e999}', "{broken", "[" * 100_000):
        with pytest.raises(ValueError):  # too deeply nested: ValueError, not RecursionError
            load_json_strict(text)


def test_value_type_accepts_int_as_float():
    from tinypedal.validator import valid_value_type

    assert valid_value_type(2, 0.0) == 2.0 and isinstance(valid_value_type(2, 0.0), float)
    assert valid_value_type(True, 0.0) == 0.0 and valid_value_type("2", -1.0) == -1.0
    assert valid_value_type(3, 1) == 3 and valid_value_type(1.5, 1) == 1
    assert valid_value_type(True, False) is True and valid_value_type(1, False) is False


def test_game_rest_connection_error_forgets_resolved_host(monkeypatch):
    from tinypedal import async_request

    forgotten = []
    monkeypatch.setattr(async_request, "forget_hostname", lambda host, port: forgotten.append((host, port)))

    def refused(host, port, timeout):
        raise ConnectionRefusedError

    monkeypatch.setattr(async_request, "resolve_hostname", refused)
    assert real_rest_get("localhost", 6397, "/rest/race/track") is None
    assert forgotten == [("localhost", 6397)]


def test_game_command_connection_error_forgets_resolved_host(monkeypatch):
    from tinypedal.ui import game_rest

    forgotten = []
    monkeypatch.setattr(game_rest, "forget_hostname", lambda host, port: forgotten.append((host, port)))
    monkeypatch.setattr(game_rest, "game_address", lambda: ("localhost", 6397))

    def refused(host, port, timeout):
        raise ConnectionRefusedError

    monkeypatch.setattr(game_rest, "resolve_hostname", refused)
    assert game_rest.game_command("PUT", "/rest/watch/replayCommand/VCRCOMMAND_STOP") is False
    assert forgotten == [("localhost", 6397)]


def test_wear_lifespan_never_negative():
    assert calc.wear_lifespan_in_laps(-5.0, 2.0) == 0
    assert calc.wear_lifespan_in_mins(-5.0, 2.0, 90.0) == 0
    assert calc.wear_lifespan_in_laps(10.0, 2.0) == 5.0


def test_consumption_history_save_result(tmp_path):
    from tinypedal.module_info import ConsumptionDataSet
    from tinypedal.userfile.consumption_history import save_consumption_history_file

    laps = [ConsumptionDataSet(2, 1, 90.0), ConsumptionDataSet(1, 1, 91.0)]
    assert save_consumption_history_file(laps, f"{tmp_path}/", "Spa - GT3")
    assert not save_consumption_history_file(laps, f"{tmp_path}/missing/", "Spa - GT3")  # error logged
    assert not save_consumption_history_file(laps[:1], f"{tmp_path}/", "Spa - GT3")  # nothing to save


def test_file_name_without_trailing_space_or_dot():
    from tinypedal.formatter import strip_invalid_char

    assert strip_invalid_char("Spa - ") == "Spa -"
    assert strip_invalid_char("Spa - LMP2.") == "Spa - LMP2"
    assert strip_invalid_char('Spa: "GT3"') == "Spa GT3"
    assert strip_invalid_char("...") == "unknown"
    assert strip_invalid_char("") == ""  # no session: stays empty


# --- Files
def test_atomic_write_flushed_to_disk(tmp_path, monkeypatch):
    from tinypedal import userfile

    synced = []
    monkeypatch.setattr(userfile.os, "fsync", lambda fileno: synced.append(fileno))
    with atomic_write(str(tmp_path / "data.txt")) as file:
        file.write("data")
    assert userfile.write_text_file(str(tmp_path / "text.txt"), "text")
    assert len(synced) == 2


def test_atomic_write_can_raise(tmp_path):
    import pytest

    with pytest.raises(OSError), atomic_write(str(tmp_path / "missing" / "data.txt"), raise_error=True) as file:
        file.write("data")


def test_car_setup_save_error_logged_not_raised(tmp_path):
    from tinypedal.userfile.car_setup import save_car_setup_file

    save_car_setup_file(f"{tmp_path}/missing/", "setup", ("line 1", "line 2"))  # no folder: logged only
    save_car_setup_file(f"{tmp_path}/", "setup", ("line 1", "line 2"))
    assert (tmp_path / "setup.svm").read_bytes() == b"line 1\r\nline 2\r\n"
    assert not (tmp_path / "setup.svm.tmp").exists()


def test_tyre_strategy_and_notes_saved_atomically(tmp_path):
    import pytest

    from tinypedal.userfile.track_notes import save_notes_file
    from tinypedal.userfile.tyre_strategy import create_tyre_strategy, save_tyre_strategy_file

    folder = f"{tmp_path}/"
    (tmp_path / "plan.tyres").write_text("old", encoding="utf-8")
    with pytest.raises(TypeError):  # data not serializable: previous file kept, not truncated
        save_tyre_strategy_file({"x": object()}, "plan.tyres", folder)
    assert (tmp_path / "plan.tyres").read_text(encoding="utf-8") == "old"
    save_tyre_strategy_file(create_tyre_strategy(), "plan.tyres", folder)
    assert "tyre_rule" in (tmp_path / "plan.tyres").read_text(encoding="utf-8")
    with pytest.raises(OSError):
        save_tyre_strategy_file(create_tyre_strategy(), "plan.tyres", f"{tmp_path}/missing/")
    header = ("distance", "pace note", "comment")
    save_notes_file(folder, "notes.tppn", header, [{"distance": 10.0, "pace note": "left", "comment": ""}], {})
    assert "left" in (tmp_path / "notes.tppn").read_text(encoding="utf-8")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["notes.tppn", "plan.tyres"]


# --- Log
def test_log_stream_keeps_latest_text_only():
    import logging

    from tinypedal.log_handler import BoundedLogStream

    stream = BoundedLogStream(max_chars=100)
    logger = logging.getLogger("test_bounded_log")
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        for index in range(50):
            logger.warning("line %02d", index)
    finally:
        logger.removeHandler(handler)
    text = stream.getvalue()
    assert len(text) <= 100 and text.endswith("line 49\n") and "line 00" not in text
    position = stream.tell()
    stream.write("x" * 500)  # single text over limit: its end kept
    assert stream.getvalue() == "x" * 100 and stream.tell() == position + 500
    assert list(stream) == ["x" * 100]
    stream.truncate(0)
    stream.seek(0)
    assert stream.getvalue() == ""


def test_logging_level_0_console_and_unwritable_log_file(tmp_path, capsys):
    """Level 0: warning & error still printed to console; level 2: unwritable log file
    does not stop startup (console output kept)"""
    import logging

    from tinypedal.log_handler import set_logging_level

    logger = logging.getLogger("test_log_level_0")
    try:
        set_logging_level(logger, f"{tmp_path}/", "test.log", log_level=0)
        logger.info("info hidden")
        logger.warning("warning shown")
        out = capsys.readouterr().out
        assert "warning shown" in out and "info hidden" not in out
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()

    logger = logging.getLogger("test_log_level_2")
    try:
        set_logging_level(logger, f"{tmp_path}/missing/", "test.log", log_level=2)
        logger.info("still logging")
        out = capsys.readouterr().out
        assert "still logging" in out and "unable to create test.log" in out
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
