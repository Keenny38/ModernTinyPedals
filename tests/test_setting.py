"""Setting class: preset loading, saving queue, file lists, API selection"""

import json
import os
import time
from copy import deepcopy

import pytest

from tinypedal import setting as setting_module
from tinypedal.const_file import ConfigType, FileExt
from tinypedal.setting import Setting, snapshot_dict
from tinypedal.userfile.json_setting import copy_setting


@pytest.fixture
def config(tmp_path):
    """Setting instance with default global config, all paths in tmp folder"""
    instance = Setting()
    instance.default.set_default()
    instance.user.config = deepcopy(dict(instance.default.config))
    instance.user.filelock = {}
    for name in ("config", "settings"):
        folder = tmp_path / name
        folder.mkdir()
        setattr(instance.path, name, f"{folder.as_posix()}/")
    return instance


def wait_saved(instance: Setting, timeout: float = 5):
    end = time.monotonic() + timeout
    while instance.is_saving or instance._save_queue:
        assert time.monotonic() < end, "saving not finished"
        time.sleep(0.01)


def read_json(filename: str):
    with open(filename, encoding="utf-8") as file:
        return json.load(file)


def touch(folder: str, filename: str, mtime: float | None = None):
    path = f"{folder}{filename}"
    with open(path, "w", encoding="utf-8") as file:
        file.write("{}")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


# Load
def test_load_user_missing_files_uses_defaults(config):
    config.load_user()
    assert config.filename.setting == f"default{FileExt.JSON}"
    assert set(config.user.setting) == set(config.default.setting)
    assert config.user.setting is not config.default.setting
    # Style presets are written on first load
    for name in ("brakes", "classes", "compounds", "heatmap", "tracks"):
        assert os.path.exists(f"{config.path.settings}{getattr(config.filename, name)}"), name


def test_load_user_next_preset(config):
    touch(config.path.settings, "race.json")
    config.set_next_to_load("race.json")
    config.load_user()
    assert config.is_loaded("race.json")
    assert config._setting_to_load == ""  # consumed
    config.load_user()
    assert config.is_loaded("race.json")  # stays on loaded preset


def test_load_user_keeps_valid_values_and_repairs_missing(config):
    widget = next(name for name, value in config.default.setting.items() if "enable" in value)
    enabled = not config.default.setting[widget]["enable"]
    touch(config.path.settings, "default.json")
    with open(f"{config.path.settings}default.json", "w", encoding="utf-8") as file:
        json.dump({widget: {"enable": enabled}}, file)
    config.load_user()
    assert config.user.setting[widget]["enable"] is enabled
    # Missing options & sections are restored from default
    assert set(config.user.setting[widget]) == set(config.default.setting[widget])
    assert set(config.user.setting) == set(config.default.setting)


def test_load_user_corrupted_preset_recovers(config):
    config.user.config["application"]["maximum_loading_attempts"] = 1
    with open(f"{config.path.settings}default.json", "w", encoding="utf-8") as file:
        file.write('{"overlay": ')
    config.load_user()
    assert set(config.user.setting) == set(config.default.setting)
    assert any(name.startswith(f"default.json{FileExt.BACKUP}") for name in os.listdir(config.path.settings))


# Save
def test_save_roundtrip(config):
    config.load_user()
    config.user.setting["overlay"]["fixed_position"] = True
    config.save(delay=0)
    wait_saved(config)
    saved = read_json(f"{config.path.settings}default.json")
    assert saved["overlay"]["fixed_position"] is True
    assert config.version_update == 1


def test_save_global_config_to_config_path(config):
    config.user.config["application"]["show_at_startup"] = False
    config.save(delay=0, config_type=ConfigType.CONFIG)
    wait_saved(config)
    assert read_json(f"{config.path.config}config.json")["application"]["show_at_startup"] is False
    assert not os.path.exists(f"{config.path.settings}config.json")


def test_save_multiple_files_in_one_thread(config):
    config.load_user()
    config.save(delay=5)
    config.save(delay=5, config_type=ConfigType.CLASSES)
    config.save(delay=5)  # duplicate, ignored
    assert len(config._save_queue) == 2
    wait_saved(config)
    assert config.version_update == 1  # single saving thread


def test_save_locked_file_skipped(config):
    config.load_user()
    config.user.filelock = {"default.json": {"version": "1"}}
    config.save(delay=0)
    wait_saved(config)
    assert not os.path.exists(f"{config.path.settings}default.json")


def test_save_invalid_config_type(config):
    config.save(delay=0, config_type="not_a_type")
    wait_saved(config)
    assert config._save_queue == {}


def test_save_error_does_not_lock_saving_state(config, monkeypatch):
    config.load_user()

    def broken_save(**kwargs):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(setting_module, "save_and_verify_json_file", broken_save)
    config.save(delay=0)
    wait_saved(config)
    assert not config.is_saving  # next save can run


def test_save_creates_versioned_backup_for_presets(config):
    config.load_user()
    config.user.config["application"]["number_of_automatic_backups"] = 3
    config.save(delay=0)
    wait_saved(config)
    config.save(delay=0)  # file exists now, backup created before overwrite
    wait_saved(config)
    assert any("-auto-" in name for name in os.listdir(config.path.settings))


def test_create_preset(config):
    config.create("new.json")
    assert set(read_json(f"{config.path.settings}new.json")) == set(config.default.setting)


# File lists
def test_preset_files_sorting_and_filtering(config):
    now = time.time()
    touch(config.path.settings, "b_preset.json", now - 30)
    touch(config.path.settings, "A_preset.json", now - 20)
    touch(config.path.settings, "c_preset.json", now - 10)
    touch(config.path.settings, "brakes.json", now)  # style preset, not user preset
    touch(config.path.settings, "notes.txt", now)
    assert config.preset_files() == ["c_preset", "A_preset", "b_preset"]  # newest first
    assert config.preset_files(reverse=False) == ["b_preset", "A_preset", "c_preset"]
    assert config.preset_files(by_date=False, reverse=False) == ["A_preset", "b_preset", "c_preset"]


def test_preset_files_fallback(config):
    assert config.preset_files() == ["default"]


def test_backup_files(config):
    now = time.time()
    touch(config.path.settings, f"a.json{FileExt.BACKUP}-1", now - 10)
    touch(config.path.settings, f"a.json{FileExt.BACKUP}-2", now)
    touch(config.path.settings, "a.json", now)
    assert config.backup_files(config.path.settings) == [f"a.json{FileExt.BACKUP}-2", f"a.json{FileExt.BACKUP}-1"]
    assert config.backup_files(config.path.config) == []


def test_primary_preset_name(config):
    touch(config.path.settings, "race.json")
    assert config.get_primary_preset_name("race") == "race.json"
    assert config.get_primary_preset_name("missing") == ""
    touch(config.path.settings, "brakes.json")
    assert config.get_primary_preset_name("brakes") == ""  # reserved name


# API selection & limits
def test_api_name_from_global_or_preset(config):
    config.load_user()
    config.telemetry["enable_api_selection_from_preset"] = False
    config.api_name = "global api"
    assert config.telemetry["api_name"] == "global api" and config.api_name == "global api"
    config.telemetry["enable_api_selection_from_preset"] = True
    config.api_name = "preset api"
    assert config.user.setting["preset"]["api_name"] == "preset api" and config.api_name == "preset api"
    assert config.telemetry["api_name"] == "global api"  # untouched


def test_attempt_limits_have_minimum(config):
    config.application["maximum_saving_attempts"] = 0
    config.application["maximum_loading_attempts"] = 0
    assert config.max_saving_attempts == 3
    assert config.max_loading_attempts == 1


# Snapshot
def test_snapshot_dict_retries_on_concurrent_change():
    class Flaky:
        calls = 0

        def __deepcopy__(self, memo):
            Flaky.calls += 1
            if Flaky.calls < 3:
                raise RuntimeError("dictionary changed size during iteration")
            return "copied"

    assert snapshot_dict({"a": Flaky()}) == {"a": "copied"}
    assert Flaky.calls == 3


def test_snapshot_dict_is_deep():
    original = {"a": {"b": [1]}}
    copied = snapshot_dict(original)
    copied["a"]["b"].append(2)
    assert original == {"a": {"b": [1]}}
    assert copy_setting(original)["a"] is not original["a"]


def test_flush_waits_for_queued_save(config):
    config.load_user()
    config.user.setting["overlay"]["fixed_position"] = True
    config.save(delay=500)  # would take ~5 seconds without flush
    assert config.flush(timeout=5)
    assert not config.is_saving
    assert read_json(f"{config.path.settings}default.json")["overlay"]["fixed_position"] is True


def test_flush_without_pending_save(config):
    assert config.flush(timeout=0.1)


def test_app_version_does_not_drive_setting_migrations(monkeypatch):
    """App version (0.x) is independent from setting format version (2.x): no old migration rerun"""
    from tinypedal import setting_validator, version
    from tinypedal.template.setting_global import GLOBAL_DEFAULT

    assert GLOBAL_DEFAULT["preset"]["version"] == version.SETTING_VERSION
    calls = []
    monkeypatch.setattr(setting_validator, "preupdate_user_setting", lambda *args: calls.append(args))
    monkeypatch.setattr(version, "__version__", "0.11.0")
    user = {"preset": {"version": version.SETTING_VERSION}}
    setting_validator.PresetValidator.user_preset(user, {"preset": {"version": ""}})
    assert calls == []
