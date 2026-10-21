"""Audit G: user & game data files read safely (ranks, BOM, brands, OpenXR layer, incidents, REST, packages,
layout profiles, notes, tyre names, decimals)"""

import asyncio
import json
import os
import zipfile
from types import SimpleNamespace
from typing import Any

import pytest

from neopedal.process import driver_ranks as dr
from neopedal.userfile import json_setting


@pytest.fixture
def folder(tmp_path) -> str:
    return f"{tmp_path.as_posix()}/"


# --- 8. Driver ranks: half-written storage file never blanks ranks
def test_rank_watcher_keeps_values_while_file_written(tmp_path, monkeypatch):
    from tests.test_driver_ranks import storage_text

    path = tmp_path / dr.STORAGE_FILE
    path.write_text(storage_text(), encoding="utf-8")
    watcher = dr.RankWatcher(lambda: dr.Located(str(path), "76561190000000001", ()))
    watcher.check()
    assert watcher.player is not None and watcher.serial == 1
    player, drivers = watcher.player, watcher.drivers
    # Game writing the file: half-written JSON, values kept, read again next poll
    path.write_text(storage_text()[:40], encoding="utf-8")
    os.utime(path, (1_900_000_000, 1_900_000_000))
    watcher.check()
    assert watcher.player == player and watcher.drivers == drivers and watcher.serial == 1
    path.write_text("", encoding="utf-8")  # truncated before writing
    os.utime(path, (1_900_000_001, 1_900_000_001))
    watcher.check()
    assert watcher.player == player and watcher.serial == 1
    # Locked file (read error): values kept
    with monkeypatch.context() as patch:
        patch.setattr(dr, "read_raw", lambda name: None)
        os.utime(path, (1_900_000_002, 1_900_000_002))
        watcher.check()
    assert watcher.player == player and watcher.serial == 1
    # Written: same modification time read again (not marked as read before)
    path.write_text(storage_text(), encoding="utf-8")
    os.utime(path, (1_900_000_002, 1_900_000_002))
    watcher.check()
    assert watcher.player == player and watcher.updated == 1_900_000_002
    # Valid file without any rank: published (not a half-written file)
    path.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    os.utime(path, (1_900_000_003, 1_900_000_003))
    watcher.check()
    assert watcher.player is None and watcher.drivers == [] and watcher.serial == 2
    # Missing file: values cleared as before
    path.write_text(storage_text(), encoding="utf-8")
    os.utime(path, (1_900_000_004, 1_900_000_004))
    watcher.check()
    assert watcher.player is not None
    os.remove(path)
    watcher.check()
    assert watcher.player is None and watcher.drivers == [] and watcher.updated == 0.0


def test_read_raw_and_storage_of_missing_file(tmp_path):
    assert dr.read_raw(str(tmp_path / "missing.json")) is None
    assert dr.read_storage(str(tmp_path / "missing.json")) == []
    assert dr.valid_raw(b"{}") and not dr.valid_raw(b"") and not dr.valid_raw(b'{"a": ')


# --- 9. JSON files saved with a UTF-8 BOM (Notepad, PowerShell 5.1) read as is
def write_bom(filename: str, data) -> None:
    with open(filename, "w", encoding="utf-8-sig") as file:
        json.dump(data, file)


def test_setting_and_style_with_bom_loaded(folder):
    write_bom(f"{folder}race.json", {"widget": {"enable": True}})
    loaded = json_setting.load_setting_json_file(
        "race.json", folder, {"widget": {"enable": False}}, validator=lambda user, default: user)
    assert loaded == {"widget": {"enable": True}}
    write_bom(f"{folder}classes.json", {"Hypercar": {"color": "#FF0000"}})
    loaded = json_setting.load_style_json_file("classes.json", folder, {})
    assert loaded == {"Hypercar": {"color": "#FF0000"}}
    assert not any(".backup" in name for name in os.listdir(folder))  # never seen as corrupted


def test_driver_stats_with_bom_loaded(folder):
    from neopedal.userfile.driver_stats import load_stats_json_file

    write_bom(f"{folder}driver.stats", {"track": {"car": {"laps": 3}}})
    assert load_stats_json_file(folder, "driver", ".stats", show_log=False) == {"track": {"car": {"laps": 3}}}


def test_tyre_strategy_and_layout_profile_with_bom_loaded(folder):
    from neopedal.userfile.layout_profile import load_profiles
    from neopedal.userfile.tyre_strategy import create_tyre_strategy, load_tyre_strategy_file

    write_bom(f"{folder}plan.tyres", create_tyre_strategy())
    assert load_tyre_strategy_file("plan.tyres", folder) is not None
    write_bom(f"{folder}race.layouts", {"1920x1080+0+0": {"gear": [1, 2]}})
    assert load_profiles(f"{folder}race.layouts") == {"1920x1080+0+0": {"gear": [1, 2]}}


# --- 10. Style file of another JSON type (list...) & invalid brands
@pytest.mark.parametrize("content", ("[1, 2]", '"text"', "3", "null"))
def test_style_not_object_falls_back_to_default(folder, content):
    with open(f"{folder}brands.json", "w", encoding="utf-8") as file:
        file.write(content)
    loaded = json_setting.load_style_json_file("brands.json", folder, {"A": "B"})
    assert loaded == {"A": "B"}
    with open(f"{folder}brands.json", encoding="utf-8") as file:
        assert json.load(file) == {"A": "B"}  # default saved
    assert any(".backup" in name for name in os.listdir(folder))  # user file kept as backup


def test_brands_validator_drops_invalid_entries(folder):
    from neopedal.setting_validator import StyleValidator

    brands = {"Car A": "Brand A", "Car B": 1, "Car C": None, "Car D": {"x": 1}}
    assert StyleValidator.brands(brands)
    assert brands == {"Car A": "Brand A"}
    assert not StyleValidator.brands(brands)  # nothing more to fix
    with open(f"{folder}brands.json", "w", encoding="utf-8") as file:
        json.dump({"Car A": "Brand A", "Car B": ["x"]}, file)
    loaded = json_setting.load_style_json_file(
        "brands.json", folder, {}, validator=StyleValidator.brands)
    assert loaded == {"Car A": "Brand A"}


def test_setting_loads_brands_with_validator(folder):
    """Setting loads user brands.json validated: invalid entries dropped, valid ones kept"""
    from neopedal.setting import Setting

    config = Setting()
    config.default.set_default()
    config.path.settings = folder
    with open(f"{folder}{config.filename.brands}", "w", encoding="utf-8") as file:
        json.dump({"Car A": "Brand A", "Car B": ["x"], "Car C": None, "Car D": "Brand D"}, file)
    config.load_styles()
    assert config.user.brands == {"Car A": "Brand A", "Car D": "Brand D"}


# --- 11. OpenXR layer disabled by user stays disabled after unregister & register (reload, restart)
def test_unregister_keeps_layer_disabled_by_user(tmp_path):
    from neopedal import vr_shared
    from tests.test_vr_shared import OTHER_LAYER, FakeWinreg

    manifest = os.path.abspath(str(tmp_path / vr_shared.LAYER_MANIFEST))
    reg = FakeWinreg({OTHER_LAYER: 0, manifest: 1})
    assert vr_shared.unregister_layer(reg) == 0
    assert reg.keys[vr_shared.REGISTRY_KEY] == {OTHER_LAYER: 0, manifest: 1}
    assert vr_shared.register_layer(manifest, reg)
    assert reg.keys[vr_shared.REGISTRY_KEY] == {OTHER_LAYER: 0, manifest: 1}  # never enabled again
    # Enabled entries removed, disabled one kept
    old = os.path.abspath(str(tmp_path / "old" / vr_shared.LAYER_MANIFEST))
    reg = FakeWinreg({OTHER_LAYER: 0, manifest: 0, old: 2})
    assert vr_shared.unregister_layer(reg) == 1
    assert reg.keys[vr_shared.REGISTRY_KEY] == {OTHER_LAYER: 0, old: 2}


# --- 28. Incidents of drivers with names cut in shared memory (31 bytes)
def incident_stream(*names: bytes) -> bytes:
    return b"\n".join(
        b'<Incident et="1.0">' + name + b"(12) reported contact (0.40) with another vehicle Other(3)</Incident>"
        for name in names)


def test_incidents_of_long_driver_name():
    from neopedal.adapter.lmu_connector import DRIVER_NAME_SIZE, LMUResults

    assert DRIVER_NAME_SIZE == 32
    long_name = "Jean-Baptiste Émile Lefèvre-Dupont".encode()
    cut_inside = "Jean-Baptiste Lefèvre-Dupontaéé".encode()  # 31st byte inside a character
    assert len(long_name) > 31 and len(cut_inside[:31].decode("utf-8", "ignore").encode()) == 30
    results = LMUResults()
    results.update(incident_stream(long_name, long_name, cut_inside, b"Short Name"))
    assert results.get(long_name[:31])["contact_vehicle"] == 2
    assert results.get(cut_inside[:31])["contact_vehicle"] == 1
    assert results.get(b"Short Name")["contact_vehicle"] == 1
    assert results.get(b"Short")["contact_vehicle"] == 0  # short name never matched by start
    assert results.get(b"x" * 31) is LMUResults.DEFAULT
    assert results.get(b"") is LMUResults.DEFAULT


# --- 29. REST resource failing several times in a row: values reset, never stale
class FakeConnection:
    def __init__(self, *answers):
        self.answers = list(answers)

    async def get(self, request):
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def test_rest_values_reset_after_failures_in_a_row():
    from neopedal.adapter import restapi_connector
    from neopedal.adapter.restapi_connector import ResOutput, RestAPIConnector, RestAPITask

    data = SimpleNamespace(value=0)
    task = RestAPITask("/rest/test", (ResOutput("value", 0, lambda value, default: value, ("v",)),), "", True, 0.2)
    connector = RestAPIConnector((task,), data)
    connector.setConnection({"restapi_update_interval": 100, "url_host": "localhost", "url_port": 6397,
                             "enable_restapi_access": True})

    def output(answer, last_hash):
        connection: Any = FakeConnection(answer)
        return asyncio.run(connector.output_resource(connection, b"", task.path, task.outputs, last_hash))

    assert restapi_connector.FAILURES_BEFORE_RESET == 3
    good = output(b'{"v": 7}', -1)
    assert data.value == 7
    # Transient errors: values kept
    assert output(b"", good) == good and output(OSError("refused"), good) == good
    assert data.value == 7
    # Success resets the count
    assert output(b'{"v": 7}', good) == good
    assert output(TimeoutError(), good) == good and output(b"not json", good) == good and data.value == 7
    # Third failure in a row: reset to default, same answer as before applied again next time
    assert output(b"", good) == -1 and data.value == 0
    assert output(b"", -1) == -1 and data.value == 0
    assert output(b'{"v": 7}', -1) == good and data.value == 7
    assert connector.status()[0].state == "active"


# --- 36. Package entries of names Windows cannot write skipped, rest imported
def test_package_import_skips_invalid_windows_names(tmp_path):
    from neopedal.userfile.preset_package import PACKAGE_FORMAT, import_preset_package, is_windows_filename

    package = tmp_path / "names.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": PACKAGE_FORMAT, "version": 1}))
        for name in ("bad:name", 'q"uote', "a*b", "what?", "pipe|x", "lt<x", "gt>x", "NUL", "com1"):
            zf.writestr(f"presets/{name}.json", "{}")
        zf.writestr("presets/good.json", "{}")
        zf.writestr("tracknotes/Le:Mans.tptn", "notes")
        zf.writestr("tracknotes/Monza.tptn", "notes")
    target, notes = tmp_path / "dst", tmp_path / "notes"
    target.mkdir()
    notes.mkdir()
    result = import_preset_package(str(package), f"{target}/", notes_paths={"tracknotes": str(notes)})
    assert result.presets == ["good.json"] and result.notes == 1
    assert len(result.skipped) == 10
    assert sorted(path.name for path in target.iterdir()) == ["good.json"]
    assert sorted(path.name for path in notes.iterdir()) == ["Monza.tptn"]
    assert is_windows_filename("Le Mans (24h).tptn") and not is_windows_filename("name.") \
        and not is_windows_filename("tab\tname") and not is_windows_filename("aux.json")


# --- 37. Layout profiles: most recent kept (file order is recency, never sorted)
def test_layout_profiles_pruned_by_recency(tmp_path):
    from neopedal.userfile.layout_profile import MAX_PROFILES, load_profiles, store_layout, sync_layout

    filename = str(tmp_path / "race.layouts")
    names = ("gear",)
    setting = {"gear": {"position_x": 1, "position_y": 2}}
    keys = [f"k{index:02d}" for index in range(MAX_PROFILES + 30, 29, -1)]  # newest sorts first
    for key in keys[:MAX_PROFILES]:
        store_layout(setting, names, filename, key)
    # Oldest one used again: most recent now
    assert not sync_layout(setting, names, filename, keys[0])
    assert list(load_profiles(filename))[-1] == keys[0]
    store_layout(setting, names, filename, keys[MAX_PROFILES])
    profiles = load_profiles(filename)
    assert len(profiles) == MAX_PROFILES
    assert keys[0] in profiles and keys[MAX_PROFILES] in profiles and keys[1] not in profiles


# --- 38 & 39. Track notes: bad GPL line skipped, metadata with quotes & commas kept
def test_gpl_notes_bad_distance_line_skipped():
    from neopedal.userfile import track_notes

    lines = ("left.mp3, 100; fast\n", "right.mp3, 2OO; typo\n", "hairpin.mp3, ; empty\n", "crest.mp3, 300\n")
    notes, _ = track_notes.parse_gpl_notes(lines, ("distance", "pace_note", "comment"))
    assert [note["distance"] for note in notes] == [100.0, 300.0]


def test_notes_metadata_unchanged_after_saves(folder):
    from neopedal.userfile import track_notes

    header = track_notes.HEADER_PACE_NOTES
    metadata = {"TITLE": 'Le "Mans", 24h', "AUTHOR": '"Rob"', "DATE": "", "DESCRIPTION": "two\nlines"}
    notes = [{"distance": 10.0, "pace note": "left", "comment": "a, b", "tags": ""}]
    for _ in range(3):
        track_notes.save_notes_file(folder, "notes.tppn", header, notes, metadata)
        notes, metadata = track_notes.load_notes_file(folder, "notes.tppn", header)
    assert metadata == {"TITLE": 'Le "Mans", 24h', "AUTHOR": '"Rob"', "DATE": "", "DESCRIPTION": "two lines"}
    assert notes[0]["comment"] == "a, b"
    # Files of earlier versions (value always quoted) read as before
    with open(f"{folder}old.tppn", "w", encoding="utf-8", newline="") as file:
        file.write('NEOPEDAL PACE NOTES FILE VERSION,2\r\n\r\nTITLE,"Monza, GP"\r\nAUTHOR,"Rob"\r\nDATE,""\r\n'
                   'DESCRIPTION,plain\r\n\r\ndistance,pace note,comment,tags\r\n10.0,left,,\r\n')
    notes, metadata = track_notes.load_notes_file(folder, "old.tppn", header)
    assert metadata == {"TITLE": "Monza, GP", "AUTHOR": "Rob", "DATE": "", "DESCRIPTION": "plain"}
    assert notes[0]["pace note"] == "left"


# --- 40. Tyre names: ASCII digits only
def test_tyre_name_non_ascii_digits_refused():
    from neopedal.userfile.tyre_strategy import decode_tyre_name, verify_tyre_name

    assert verify_tyre_name("Soft #12") and decode_tyre_name("Soft #12")[2] == 12
    for name in ("Soft #²", "Soft #1²", "Soft #٣", "Soft #", "Soft #-1", "Soft # 1"):
        assert not verify_tyre_name(name)


# --- 41. Decimals stripped, also of values written with an exponent
@pytest.mark.parametrize(("value", "decimals", "expected"), (
    (1.5e-05, 3, 0.0), (1.5e-05, 6, 0.000015), (1.239, 2, 1.23), (0.29, 2, 0.29), (-1.29, 1, -1.2),
    (2.0, 0, 2.0), (5, 2, 5), (1.5e16, 1, 1.5e16), (1e30, 2, 1e30),
))
def test_decimal_strip(value, decimals, expected):
    from neopedal.calculation import decimal_strip

    assert decimal_strip(value, decimals) == expected


def test_decimal_strip_not_finite():
    import math

    from neopedal.calculation import decimal_strip

    assert math.isnan(decimal_strip(float("nan"), 1)) and decimal_strip(float("inf"), 1) == float("inf")
