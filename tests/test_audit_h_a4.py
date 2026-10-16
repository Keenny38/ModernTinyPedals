"""Audit h, lot a4: replay zip bomb bounded, unavailable user path not saved over, settings of a newer
build kept, file replace retried (antivirus, cloud sync) through one file layer, results file with a
Windows-1252 byte read, backup list while saving, NaN stats & ranks, BOM in json, settings import cleanup"""

import json
import math
import os
import tracemalloc
import zlib

import pytest

from neopedal import replay as rp
from neopedal import userfile
from neopedal.process import driver_ranks as dr
from neopedal.process import results_file as rf
from neopedal.replay import REST_FRAME, ReplayFile, ReplayWriter, bounded_decompress


# --- 1. Replay: decompression bounded (zip bomb)
def test_bounded_decompress_stops_at_limit():
    bomb = zlib.compress(bytes(50_000_000), 9)  # 50 MB of zeros in ~50 KB
    tracemalloc.start()
    try:
        with pytest.raises(zlib.error):
            bounded_decompress(bomb, 64)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 5_000_000  # never decompressed whole
    assert bounded_decompress(zlib.compress(b"abcd"), 4) == b"abcd"
    with pytest.raises(zlib.error):
        bounded_decompress(zlib.compress(b"abcd")[:-3], 4)  # incomplete stream


def test_replay_frame_and_rest_bomb_skipped(tmp_path, monkeypatch):
    filename = str(tmp_path / "bomb.tpreplay")
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, 64, 10)
        writer.write(0.0, bytes(range(64)))
        writer.write_rest(0.0, {"a": 1})
        writer._write(0.1, 1, zlib.compress(bytes(100_000), 9))  # keyframe decompressing far over frame size
        writer._write(0.1, REST_FRAME, zlib.compress(json.dumps({"b": "x" * 10_000}).encode(), 9))
        writer.finish()
    monkeypatch.setattr(rp, "MAX_REST_SIZE", 1000)
    replay = ReplayFile(filename)
    assert replay.frame(0) == bytes(range(64))
    assert replay.frame(1) == bytes(range(64))  # damaged frame skipped: last good frame kept
    assert 1 in replay._corrupt
    assert replay.rest(0) == {"a": 1}
    assert replay._rest_frame(1) is None


# --- 2. User path unavailable: default used for this session only
def test_unavailable_user_path_not_saved_over(tmp_path):
    from neopedal.setting import FilePath

    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    unavailable = f"{blocker}/sub/"  # parent is a file: like a drive not mounted
    default = f"{tmp_path}/default/"
    user_path = {"telemetry_path": unavailable}
    path = FilePath.__new__(FilePath)
    path.update(user_path, {"telemetry_path": default})
    assert path.telemetry == default
    assert user_path == {"telemetry_path": unavailable}  # user choice kept (saved as is)
    assert os.path.isdir(default)


def test_user_data_path_created_with_parents(tmp_path):
    nested = str(tmp_path / "a" / "b" / "c")
    assert userfile.set_user_data_path(nested) == nested
    assert os.path.isdir(nested)


# --- 3. Settings of a newer build: version & unknown options kept, no one-time updates run again
def test_newer_preset_version_and_options_kept(monkeypatch):
    from neopedal import setting_validator as sv
    from neopedal import version

    calls = []
    monkeypatch.setattr(sv, "preupdate_global_setting", lambda *args: calls.append(args))
    dict_def = {"preset": {"version": "0.0.0"}, "section": {"known": 1}}
    newer = {"preset": {"version": "999.0.0"}, "section": {"known": 1, "future": 5}, "future_section": {"x": 1}}
    result = sv.PresetValidator.global_preset(newer, dict_def)
    assert result["preset"]["version"] == "999.0.0"
    assert result["section"]["future"] == 5
    assert result["future_section"] == {"x": 1}
    assert not calls
    older = {"preset": {"version": "0.0.1"}, "section": {"known": 1, "removed": 5}, "old_section": {}}
    result = sv.PresetValidator.global_preset(older, dict_def)
    assert result["preset"]["version"] == version.SETTING_VERSION
    assert result == {"preset": {"version": version.SETTING_VERSION}, "section": {"known": 1}}
    assert len(calls) == 1


# --- 4. One file layer: replace retried, atomic write, json read
@pytest.fixture
def flaky_replace(monkeypatch):
    real_replace = os.replace
    failures = {"left": 2, "calls": 0}

    def replace(src, dst):
        failures["calls"] += 1
        if failures["left"] > 0:
            failures["left"] -= 1
            raise PermissionError(13, "Access is denied (WinError 5)")
        real_replace(src, dst)

    monkeypatch.setattr(userfile, "REPLACE_RETRY_DELAY", 0.001)
    monkeypatch.setattr(os, "replace", replace)
    return failures


def test_replace_retried_on_permission_error(tmp_path, flaky_replace):
    target = tmp_path / "data.json"
    assert userfile.write_text_file(str(target), "abc")
    assert target.read_bytes() == b"abc"
    assert flaky_replace["calls"] == 3
    flaky_replace["left"] = 2
    assert userfile.write_json(str(target), {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    flaky_replace["left"] = 2
    with userfile.atomic_write(str(target)) as file:
        file.write("text")
    assert target.read_text(encoding="utf-8") == "text"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["data.json"]  # no temporary file


def test_replace_gives_up_after_attempts(tmp_path, flaky_replace):
    target = tmp_path / "data.bin"
    target.write_bytes(b"old")
    flaky_replace["left"] = 99
    with pytest.raises(PermissionError):
        userfile.atomic_replace(str(target), b"new")
    assert flaky_replace["calls"] == userfile.REPLACE_ATTEMPTS
    assert target.read_bytes() == b"old"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["data.bin"]


def test_cache_writers_never_leave_fixed_temp_file(tmp_path, monkeypatch):
    """Badge icon & game picture caches: unique temporary file, removed on error"""
    from neopedal.userfile import badge_icons

    def fail(*args):
        raise OSError(28, "No space left on device")

    target = tmp_path / "icons" / "a.svg"
    icons = badge_icons.BadgeIcons()
    monkeypatch.setattr(icons, "icon_file", lambda key: str(target))
    monkeypatch.setattr(badge_icons, "download", lambda url: b"<svg/>")
    monkeypatch.setattr(userfile, "replace_retry", fail)
    assert not icons.fetch("a")
    assert list((tmp_path / "icons").iterdir()) == []
    monkeypatch.undo()
    monkeypatch.setattr(icons, "icon_file", lambda key: str(target))
    monkeypatch.setattr(badge_icons, "download", lambda url: b"<svg/>")
    assert icons.fetch("a")
    assert target.read_bytes() == b"<svg/>"


def test_read_json(tmp_path):
    path = tmp_path / "a.json"
    path.write_bytes(b'\xef\xbb\xbf{"a": 1}')  # BOM of Notepad
    assert userfile.read_json(str(path)) == {"a": 1}
    path.write_text('{"a": NaN}', encoding="utf-8")
    assert userfile.read_json(str(path), default={}) == {}
    assert math.isnan(userfile.read_json(str(path), strict=False)["a"])
    path.write_text('{"a": 1e999}', encoding="utf-8")
    assert userfile.read_json(str(path)) is None
    path.write_text("[1]", encoding="utf-8")
    assert userfile.read_json(str(path)) == [1]
    assert userfile.read_json(str(path), dict_only=True, default={}) == {}
    assert userfile.read_json(str(tmp_path / "missing.json"), default=5) == 5


def test_arrays_file_written_alike(tmp_path):
    from array import array

    from neopedal.userfile.lap_cache import read_arrays_file, write_arrays_file

    target = str(tmp_path / "lap.bin")
    write_arrays_file(target, {"v": 1}, {"x": array("d", [1.0, 2.5]), "n": array("i", [3])})
    values, arrays = read_arrays_file(target)
    assert values == {"v": 1} and list(arrays["x"]) == [1.0, 2.5] and list(arrays["n"]) == [3]
    assert sorted(os.listdir(tmp_path)) == ["lap.bin"]


# --- 5. Results file: one Windows-1252 byte in a file declared UTF-8
def test_results_with_cp1252_byte_read():
    from tests.test_race_results import RACE_NAME, RACE_XML

    data = RACE_XML.encode("utf-8").replace(b"Test Server", b"Caf\xe9 Server").replace(
        b"<TrackVenue>Circuit de la Sarthe", "<TrackVenue>Circuit é".encode())
    result = rf.parse_results(data, RACE_NAME)
    assert result.server == "Café Server"
    assert result.venue == "Circuit é"  # valid UTF-8 kept
    assert len(result.entries) == len(rf.parse_results(RACE_XML.encode("utf-8"), RACE_NAME).entries)
    with pytest.raises(ValueError):
        rf.parse_results(b"<rFactorXML><RaceResults>\xe9<Race></RaceResults></rFactorXML>")
    assert rf.repair_utf8(b"\x81ok\xc3\xa9") == "�oké".encode()


# --- 6. Preset & backup lists while a save runs
def test_backup_list_skips_save_in_progress_and_vanished_files(tmp_path, monkeypatch):
    from neopedal import setting
    from neopedal.setting import cfg
    from neopedal.userfile import json_setting

    folder = f"{tmp_path}/"
    (tmp_path / "race.json").write_text("{}", encoding="utf-8")
    (tmp_path / "race.json.backup").write_text("{}", encoding="utf-8")
    seen = []
    real_save = json_setting.save_json_file

    def save_json_file(*args, **kwargs):
        seen.append(cfg.backup_files(folder))
        return real_save(*args, **kwargs)

    monkeypatch.setattr(json_setting, "save_json_file", save_json_file)
    assert json_setting.save_and_verify_json_file({"a": 1}, "race.json", folder)
    assert seen == [["race.json.backup"]]  # temporary backup of the save not listed
    real_mtime = os.path.getmtime

    def vanished(path):
        if path.endswith("race.json.backup"):
            raise FileNotFoundError(path)
        return real_mtime(path)

    monkeypatch.setattr(setting.os.path, "getmtime", vanished)
    assert cfg.backup_files(folder) == []
    assert setting.file_mtime(str(tmp_path / "missing")) is None


def test_preset_list_skips_vanished_file(tmp_path, monkeypatch):
    from neopedal import setting
    from neopedal.setting import cfg

    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    real_mtime = os.path.getmtime
    monkeypatch.setattr(cfg.path, "settings", f"{tmp_path}/")
    monkeypatch.setattr(setting.os.path, "getmtime",
                        lambda path: (_ for _ in ()).throw(FileNotFoundError(path)) if path.endswith("b.json")
                        else real_mtime(path))
    assert cfg.preset_files() == ["a"]


# --- 7. Driver stats: NaN & infinity loaded from file reset
def test_driver_stats_non_finite_reset(monkeypatch):
    from neopedal.userfile import driver_stats as ds

    saved = []
    monkeypatch.setattr(ds, "save_stats_json_file", lambda **kwargs: saved.append(kwargs["stats_user"]))
    stats = {"track": {"car": {"pb": float("nan"), "meters": float("inf")}}}
    ds.add_driver_stats(stats, ("track", "car"), ds.DriverStats(pb=90.0, meters=100.0), "", "driver")
    assert stats["track"]["car"]["pb"] == 90.0
    assert stats["track"]["car"]["meters"] == 100.0
    assert saved


# --- 8. Driver ranks: infinity never kills the thread, history line never glued
def test_ranks_non_finite_and_history_separator(tmp_path):
    assert dr._int(float("inf")) == 0 and dr._int(float("nan")) == 0 and dr._int(2.0) == 2
    assert dr.parse_rank({"rank": "Gold", "tier": float("inf"), "progress": 5}) == dr.Rank("Gold", 0, 5)
    path = tmp_path / "ranks_history.jsonl"
    path.write_bytes(b'{"time": 1, "driver": ["Gold", Infinity, 5], "safety": null}\n{"time": 2, "dri')  # crash
    entry = dr.HistoryEntry(3.0, dr.Rank("Silver", 2, 40), None)
    assert dr.append_history(str(path), entry)
    entries = dr.read_history(str(path))
    assert [item.time for item in entries] == [1.0, 3.0]
    assert entries[0].driver == dr.Rank("Gold", 0, 5)
    assert entries[1].driver == dr.Rank("Silver", 2, 40)


# --- 9. UTF-8 BOM accepted
def test_bom_language_pack_and_package_json(tmp_path):
    from neopedal.i18n import LANGUAGE_PACK_FORMAT, read_language_pack
    from neopedal.userfile.preset_package import is_json_dict

    pack = tmp_path / "de.json"
    pack.write_bytes(b"\xef\xbb\xbf" + json.dumps(
        {"format": LANGUAGE_PACK_FORMAT, "name": "Deutsch", "code": "de", "ui": {"Close": "Schliessen"}}).encode())
    assert read_language_pack(str(pack))["ui"] == {"Close": "Schliessen"}
    assert is_json_dict(b'\xef\xbb\xbf{"a": 1}')
    assert not is_json_dict(b'{"a": NaN}')


# --- 10. Settings import: rename failure cleaned up, one previous folder kept, lap cache not copied
def test_import_rename_failure_cleans_copy(tmp_path, monkeypatch):
    from neopedal.userfile import settings_import as si

    monkeypatch.setattr(si, "_report", [])
    source = tmp_path / "Other"
    (source / ".lap_cache").mkdir(parents=True)
    (source / ".lap_cache" / "x.bin").write_bytes(b"x")
    (source / "config.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "NeoPedal"
    target.mkdir()
    (target / "config.json").write_text('{"current": true}', encoding="utf-8")
    real_rename = os.rename

    def locked(src, dst):
        if str(src) == str(target):
            raise PermissionError(13, "file in use by another process")
        real_rename(src, dst)

    monkeypatch.setattr(si.os, "rename", locked)
    with pytest.raises(OSError):
        si.replace_folder(str(source), str(target), "20260101-000000")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["NeoPedal", "Other"]  # no .importing left
    assert (target / "config.json").read_text(encoding="utf-8") == '{"current": true}'
    monkeypatch.undo()
    (tmp_path / "NeoPedal.before-import-20250101-000000").mkdir()
    (tmp_path / "NeoPedal.before-import-20250601-000000").mkdir()
    aside = si.replace_folder(str(source), str(target), "20260101-000000")
    assert sorted(path.name for path in tmp_path.iterdir()) == [  # earlier backups kept (never deleted)
        "NeoPedal", "NeoPedal.before-import-20250101-000000", "NeoPedal.before-import-20250601-000000",
        "NeoPedal.before-import-20260101-000000", "Other"]
    assert os.path.basename(aside) == "NeoPedal.before-import-20260101-000000"
    assert not (target / ".lap_cache").exists()  # cache rebuilt from laps
    assert (target / "config.json").read_text(encoding="utf-8") == "{}"
