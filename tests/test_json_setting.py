"""Setting file functions: load, save, verify, backup & restore"""

import json
import os
import time

import pytest

from tinypedal.const_file import FileExt
from tinypedal.userfile import json_setting
from tinypedal.userfile.json_setting import (
    copy_setting,
    create_backup_file,
    create_versioned_backup,
    load_setting_json_file,
    load_style_json_file,
    rename_preset_backups,
    restore_backup_file,
    save_and_verify_json_file,
    set_backup_timestamp,
    verify_json_file,
)

DEFAULT = {"widget": {"enable": False, "size": 10}, "module": {"enable": True}}


def keep_all(user: dict, default: dict) -> dict:
    """Validator that accepts user data as is"""
    return user


@pytest.fixture
def folder(tmp_path) -> str:
    return f"{tmp_path.as_posix()}/"


def write(folder: str, filename: str, content: str):
    with open(f"{folder}{filename}", "w", encoding="utf-8") as file:
        file.write(content)


def read_json(folder: str, filename: str):
    with open(f"{folder}{filename}", encoding="utf-8") as file:
        return json.load(file)


def backups(folder: str, filename: str) -> list[str]:
    return sorted(name for name in os.listdir(folder) if name.startswith(f"{filename}{FileExt.BACKUP}"))


# Copy
def test_copy_setting_nested_is_independent():
    copied = copy_setting(DEFAULT)
    copied["widget"]["size"] = 99
    assert DEFAULT["widget"]["size"] == 10


def test_copy_setting_flat():
    flat = {"a": 1, "b": 2}
    copied = copy_setting(flat)
    assert copied == flat and copied is not flat
    assert copy_setting({}) == {}


def test_backup_timestamp():
    assert set_backup_timestamp(timestamp=False) == FileExt.BACKUP
    stamp = set_backup_timestamp()
    assert stamp.startswith(f"{FileExt.BACKUP}-") and len(stamp) > len(FileExt.BACKUP) + 20


# Load user preset
def test_load_missing_file_returns_default_copy(folder):
    loaded = load_setting_json_file("missing.json", folder, DEFAULT, validator=keep_all, max_attempts=1)
    assert loaded == DEFAULT
    loaded["widget"]["size"] = 1
    assert DEFAULT["widget"]["size"] == 10  # default never modified


def test_load_valid_file_uses_validator(folder):
    write(folder, "user.json", json.dumps({"widget": {"enable": True}}))
    calls = []

    def validator(user, default):
        calls.append((user, default))
        return {**default, **user}

    loaded = load_setting_json_file("user.json", folder, DEFAULT, validator=validator, max_attempts=1)
    assert loaded["widget"] == {"enable": True} and loaded["module"] == {"enable": True}
    assert len(calls) == 1


def test_load_corrupted_file_falls_back_and_keeps_backup(folder, monkeypatch):
    monkeypatch.setattr(json_setting, "sleep", lambda _: None)
    write(folder, "user.json", '{"widget": {"enable": tru')
    loaded = load_setting_json_file("user.json", folder, DEFAULT, validator=keep_all, max_attempts=3)
    assert loaded == DEFAULT
    saved_backups = backups(folder, "user.json")
    assert len(saved_backups) == 1  # broken file kept for user to recover
    with open(f"{folder}{saved_backups[0]}", encoding="utf-8") as file:
        assert file.read().startswith('{"widget"')


def test_load_validator_error_falls_back(folder, monkeypatch):
    monkeypatch.setattr(json_setting, "sleep", lambda _: None)
    write(folder, "user.json", "[1, 2, 3]")  # valid JSON, wrong type

    def validator(user, default):
        return {key: user[key] for key in default}  # TypeError on list

    assert load_setting_json_file("user.json", folder, DEFAULT, validator=validator, max_attempts=2) == DEFAULT


# Load style preset
def test_load_style_missing_file_creates_default(folder):
    loaded = load_style_json_file("style.json", folder, {"A": {"color": "#FFF"}}, max_attempts=1)
    assert loaded == {"A": {"color": "#FFF"}}
    assert read_json(folder, "style.json") == loaded


def test_load_style_updated_by_validator_saved_with_backup(folder):
    write(folder, "style.json", json.dumps({"A": {}}))

    def validator(style):
        style["A"]["color"] = "#000"
        return True  # modified

    loaded = load_style_json_file("style.json", folder, {}, validator=validator, max_attempts=1)
    assert loaded == {"A": {"color": "#000"}}
    assert read_json(folder, "style.json") == loaded
    assert len(backups(folder, "style.json")) == 1


def test_load_style_unchanged_not_rewritten(folder):
    write(folder, "style.json", '{"A":{}}')
    load_style_json_file("style.json", folder, {}, validator=lambda style: False, max_attempts=1)
    with open(f"{folder}style.json", encoding="utf-8") as file:
        assert file.read() == '{"A":{}}'
    assert backups(folder, "style.json") == []


def test_load_style_corrupted_falls_back(folder, monkeypatch):
    monkeypatch.setattr(json_setting, "sleep", lambda _: None)
    write(folder, "style.json", "{broken")
    loaded = load_style_json_file("style.json", folder, {"A": {}}, max_attempts=2)
    assert loaded == {"A": {}}
    assert read_json(folder, "style.json") == {"A": {}}  # repaired
    assert len(backups(folder, "style.json")) == 1  # broken file kept


# Verify
def test_verify_json_file(folder):
    write(folder, "data.json", json.dumps(DEFAULT))
    assert verify_json_file(DEFAULT, "data.json", folder)
    assert verify_json_file(None, "data.json", folder)  # load check only
    assert not verify_json_file({"other": 1}, "data.json", folder)
    assert not verify_json_file(None, "missing.json", folder)
    write(folder, "bad.json", "{")
    assert not verify_json_file(None, "bad.json", folder)


# Save
def test_save_creates_new_file(folder):
    save_and_verify_json_file(DEFAULT, "new.json", folder, max_attempts=3)
    assert read_json(folder, "new.json") == DEFAULT
    assert backups(folder, "new.json") == []


def test_save_overwrites_and_removes_temporary_backup(folder):
    write(folder, "data.json", json.dumps({"old": True}))
    save_and_verify_json_file(DEFAULT, "data.json", folder, max_attempts=3)
    assert read_json(folder, "data.json") == DEFAULT
    assert backups(folder, "data.json") == []


def test_save_compact(folder):
    save_and_verify_json_file({"a": [1, 2]}, "compact.json", folder, compact_json=True)
    with open(f"{folder}compact.json", encoding="utf-8") as file:
        assert file.read() == '{"a":[1,2]}'


def test_save_failure_restores_previous_file(folder, monkeypatch):
    monkeypatch.setattr(json_setting, "sleep", lambda _: None)
    monkeypatch.setattr(json_setting, "verify_json_file", lambda *args, **kwargs: False)
    write(folder, "data.json", json.dumps({"old": True}))
    save_and_verify_json_file(DEFAULT, "data.json", folder, max_attempts=3)
    assert read_json(folder, "data.json") == {"old": True}  # previous content restored
    assert backups(folder, "data.json") == []


def test_save_aborted_if_backup_fails(folder, monkeypatch):
    write(folder, "data.json", json.dumps({"old": True}))
    monkeypatch.setattr(json_setting, "create_backup_file", lambda *args, **kwargs: False)
    save_and_verify_json_file(DEFAULT, "data.json", folder)
    assert read_json(folder, "data.json") == {"old": True}  # untouched


def test_save_failure_and_restore_failure_keeps_renamed_backup(folder, monkeypatch):
    monkeypatch.setattr(json_setting, "sleep", lambda _: None)
    monkeypatch.setattr(json_setting, "verify_json_file", lambda *args, **kwargs: False)
    monkeypatch.setattr(json_setting, "restore_backup_file", lambda *args, **kwargs: False)
    write(folder, "data.json", json.dumps({"old": True}))
    save_and_verify_json_file(DEFAULT, "data.json", folder, max_attempts=2)
    # Temporary backup deleted, renamed copy kept so previous content can be recovered by user
    kept = backups(folder, "data.json")
    assert len(kept) == 1
    assert read_json(folder, kept[0]) == {"old": True}


# Backup helpers
def test_backup_and_restore(folder):
    assert not create_backup_file("missing.json", folder)
    write(folder, "data.json", '{"v": 1}')
    assert create_backup_file("data.json", folder, ".bak")
    write(folder, "data.json", '{"v": 2}')
    assert restore_backup_file("data.json", folder, ".bak")
    assert read_json(folder, "data.json") == {"v": 1}
    assert not restore_backup_file("data.json", folder, ".missing")


def test_versioned_backup_interval_and_pruning(folder):
    assert not create_versioned_backup("data.json", folder)  # no source file
    write(folder, "data.json", "{}")
    assert not create_versioned_backup("data.json", folder, max_count=0)  # disabled
    assert create_versioned_backup("data.json", folder, max_count=2, min_interval=600)
    assert not create_versioned_backup("data.json", folder, max_count=2, min_interval=600)  # too soon
    for _ in range(3):
        time.sleep(0.002)  # unique timestamp
        assert create_versioned_backup("data.json", folder, max_count=2, min_interval=0)
    assert len(backups(folder, "data.json")) == 2  # oldest removed


def test_rename_preset_backups(folder):
    write(folder, f"old.json{FileExt.BACKUP}-1", "{}")
    write(folder, f"old.json{FileExt.BACKUP}-auto-2", "{}")
    write(folder, f"new.json{FileExt.BACKUP}-1", "{}")  # existing target, not overwritten
    write(folder, "other.json.bak", "{}")
    assert rename_preset_backups(folder, "old.json", "new.json") == 1
    assert sorted(os.listdir(folder)) == sorted([
        f"old.json{FileExt.BACKUP}-1",
        f"new.json{FileExt.BACKUP}-1",
        f"new.json{FileExt.BACKUP}-auto-2",
        "other.json.bak",
    ])
    assert rename_preset_backups(f"{folder}missing/", "a", "b") == 0


# Audit fixes: atomic saving, backups
def test_save_never_leaves_truncated_file(folder, monkeypatch):
    """Write failing half-way (full disk, power loss): previous file kept as is"""
    write(folder, "config.json", json.dumps({"old": True}))

    def fail_half_way(data, file, **kwargs):
        file.write('{"new": ')
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json_setting.json, "dump", fail_half_way)
    json_setting.save_json_file({"new": True}, "config.json", folder)
    assert read_json(folder, "config.json") == {"old": True}
    assert sorted(os.listdir(folder)) == ["config.json"]  # no temporary file left


def test_save_invalid_data_leaves_no_backup(folder):
    write(folder, "data.json", json.dumps({"old": True}))
    save_and_verify_json_file({"bad": object()}, "data.json", folder, max_attempts=3)
    assert read_json(folder, "data.json") == {"old": True}
    assert sorted(os.listdir(folder)) == ["data.json"]  # backup & temporary file removed


def test_failed_backup_copy_removed(folder, monkeypatch):
    write(folder, "data.json", json.dumps({"old": True}))
    monkeypatch.setattr(json_setting.filecmp, "cmp", lambda *args, **kwargs: False)  # copy differs
    assert not create_backup_file("data.json", folder, f"{FileExt.BACKUP}-1")
    assert sorted(os.listdir(folder)) == ["data.json"]
    write(folder, f"data.json{FileExt.BACKUP}", "{}")  # backup made before: kept
    assert not create_backup_file("data.json", folder)
    assert os.path.exists(f"{folder}data.json{FileExt.BACKUP}")


def test_versioned_backup_interval_from_backup_time(folder):
    """Backup gets its own time (not preset modified time), so interval counts from backup"""
    write(folder, "data.json", "{}")
    os.utime(f"{folder}data.json", (time.time() - 7200, time.time() - 7200))  # preset saved 2 hours ago
    assert create_versioned_backup("data.json", folder, max_count=5, min_interval=600)
    assert not create_versioned_backup("data.json", folder, max_count=5, min_interval=600)
    assert len(backups(folder, "data.json")) == 1


def test_versioned_backup_failed_copy_removed(folder, monkeypatch):
    write(folder, "data.json", "{}")

    def fail_copy(source, target):
        with open(target, "w", encoding="utf-8") as file:
            file.write("{")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(json_setting.shutil, "copyfile", fail_copy)
    assert not create_versioned_backup("data.json", folder, max_count=5, min_interval=0)
    assert sorted(os.listdir(folder)) == ["data.json"]


def test_backups_follow_case_only_rename(folder, monkeypatch):
    """Windows: "race.json" renamed "Race.json", backup name exists as same file but is renamed too"""
    write(folder, f"race.json{FileExt.BACKUP}-1", "{}")
    monkeypatch.setattr(json_setting.os.path, "exists", lambda path: True)  # case insensitive file system
    monkeypatch.setattr(json_setting.os.path, "normcase", str.lower)
    assert rename_preset_backups(folder, "race.json", "Race.json") == 1
    assert os.listdir(folder) == [f"Race.json{FileExt.BACKUP}-1"]
