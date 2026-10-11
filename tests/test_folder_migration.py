"""Legacy "TinyPedal" user folder copied to "NeoPedal" folder"""

import json
import logging
import os
import shutil

import pytest

from tinypedal.const_app import CONFIG_ID, LEGACY_CONFIG_ID
from tinypedal.userfile import folder_migration as fm


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    """Empty migration state, user base folders in tmp_path"""
    monkeypatch.setattr(fm, "_folder_ids", {})
    monkeypatch.setattr(fm, "_report", [])
    monkeypatch.setattr(fm, "base_folder", lambda kind: str(tmp_path / kind))
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    return tmp_path


def make_legacy(base, config=None):
    old = base / LEGACY_CONFIG_ID
    (old / "languages").mkdir(parents=True)
    (old / "languages" / "de.json").write_text("{}", encoding="utf-8")
    (old / "shortcuts.json").write_text("{}", encoding="utf-8")
    (old / "pid.log").write_text("123", encoding="utf-8")
    (old / "config.lock").write_text("", encoding="utf-8")
    if config is not None:
        (old / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return old


def test_copy_legacy_folder_once(fresh):
    old = make_legacy(fresh / "config", {"application": {"x": 1}})
    assert fm.user_folder_id("config") == CONFIG_ID
    new = fresh / "config" / CONFIG_ID
    assert (new / "languages" / "de.json").is_file()
    assert json.loads((new / "config.json").read_text(encoding="utf-8")) == {"application": {"x": 1}}
    # Runtime files of a running app not copied, legacy folder untouched
    assert not (new / "pid.log").exists() and not (new / "config.lock").exists()
    assert (old / "pid.log").is_file() and (old / "config.lock").is_file()
    assert not (fresh / "config" / f"{CONFIG_ID}{fm.TEMP_SUFFIX}").exists()


def test_existing_new_folder_never_overwritten(fresh):
    make_legacy(fresh / "config", {"a": 1})
    new = fresh / "config" / CONFIG_ID
    new.mkdir()
    (new / "config.json").write_text('{"b": 2}', encoding="utf-8")
    assert fm.user_folder_id("config") == CONFIG_ID
    assert json.loads((new / "config.json").read_text(encoding="utf-8")) == {"b": 2}
    assert not (new / "languages").exists()
    assert fm._report == []


def test_no_legacy_folder(fresh):
    assert fm.user_folder_id("config") == CONFIG_ID
    assert not (fresh / "config" / CONFIG_ID).exists()  # created by caller
    assert fm._report == []


def test_interrupted_copy_retried(fresh):
    make_legacy(fresh / "config")
    leftover = fresh / "config" / f"{CONFIG_ID}{fm.TEMP_SUFFIX}"
    leftover.mkdir()
    (leftover / "partial.json").write_text("", encoding="utf-8")
    assert fm.user_folder_id("config") == CONFIG_ID
    new = fresh / "config" / CONFIG_ID
    assert (new / "shortcuts.json").is_file() and not (new / "partial.json").exists()
    assert not leftover.exists()


def test_failed_copy_uses_legacy_folder(fresh, monkeypatch, caplog):
    make_legacy(fresh / "config")

    def broken_copy(src, dst, **kwargs):
        os.makedirs(dst)
        raise shutil.Error([(src, dst, "disk full")])

    monkeypatch.setattr(fm.shutil, "copytree", broken_copy)
    assert fm.user_folder_id("config") == LEGACY_CONFIG_ID
    assert fm.user_folder_id("config") == LEGACY_CONFIG_ID  # cached, not retried in same run
    assert not (fresh / "config" / CONFIG_ID).exists()
    assert not (fresh / "config" / f"{CONFIG_ID}{fm.TEMP_SUFFIX}").exists()
    with caplog.at_level(logging.INFO):
        fm.log_migration_report()
    assert "failed" in caplog.text and fm._report == []


def test_user_paths_rewritten(fresh, monkeypatch):
    monkeypatch.setattr(fm.PLATFORM, "WINDOWS", False)
    config_old = (fresh / "config" / LEGACY_CONFIG_ID).as_posix()
    data_old = (fresh / "data" / LEGACY_CONFIG_ID).as_posix()
    make_legacy(fresh / "data")
    make_legacy(fresh / "config", {"user_path": {
        "settings_path": f"{config_old}/settings/",
        "track_map_path": f"{data_old}/trackmap/",
        "telemetry_path": "/mnt/other/telemetry/",
        "pace_notes_path": f"{config_old}x/pacenotes/",  # other folder with same prefix
    }})
    assert fm.user_folder_id("config") == CONFIG_ID
    assert fm.user_folder_id("data") == CONFIG_ID
    config = json.loads((fresh / "config" / CONFIG_ID / "config.json").read_text(encoding="utf-8"))
    assert config["user_path"] == {
        "settings_path": f"{(fresh / 'config' / CONFIG_ID).as_posix()}/settings/",
        "track_map_path": f"{(fresh / 'data' / CONFIG_ID).as_posix()}/trackmap/",
        "telemetry_path": "/mnt/other/telemetry/",
        "pace_notes_path": f"{config_old}x/pacenotes/",
    }
    # Legacy config untouched
    legacy = json.loads((fresh / "config" / LEGACY_CONFIG_ID / "config.json").read_text(encoding="utf-8"))
    assert legacy["user_path"]["settings_path"] == f"{config_old}/settings/"


def test_data_paths_kept_if_data_copy_failed(fresh, monkeypatch):
    monkeypatch.setattr(fm.PLATFORM, "WINDOWS", False)
    data_old = (fresh / "data" / LEGACY_CONFIG_ID).as_posix()
    make_legacy(fresh / "data")
    make_legacy(fresh / "config", {"user_path": {"track_map_path": f"{data_old}/trackmap/"}})
    copytree = shutil.copytree

    def copy_config_only(src, dst, *args, **kwargs):
        if os.path.dirname(src) == str(fresh / "data"):
            raise OSError("denied")
        return copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(fm.shutil, "copytree", copy_config_only)
    assert fm.user_folder_id("config") == CONFIG_ID
    assert fm.user_folder_id("data") == LEGACY_CONFIG_ID
    config = json.loads((fresh / "config" / CONFIG_ID / "config.json").read_text(encoding="utf-8"))
    assert config["user_path"]["track_map_path"] == f"{data_old}/trackmap/"


def test_invalid_config_still_copied(fresh):
    old = make_legacy(fresh / "config")
    (old / "config.json").write_text("{broken", encoding="utf-8")
    assert fm.user_folder_id("config") == CONFIG_ID
    assert (fresh / "config" / CONFIG_ID / "config.json").read_text(encoding="utf-8") == "{broken"
    assert any(level == logging.WARNING for level, _ in fm._report)


def test_global_config_path_uses_new_folder():
    from tinypedal.setting import FilePath

    path = FilePath().config.replace("\\", "/").rstrip("/")
    assert path.endswith(f"/{CONFIG_ID}")


# User choice: keep imported settings, default settings, import again

def config_dirs(base):
    return base / "config" / LEGACY_CONFIG_ID, base / "config" / CONFIG_ID


def test_copy_marked_pending(fresh):
    make_legacy(fresh / "config", {"a": 1})
    fm.user_folder_id("config")
    old, new = config_dirs(fresh)
    state = fm.read_state(str(new))
    assert state["state"] == fm.STATE_PENDING and state["source"] == str(old)
    assert not (old / fm.STATE_FILE).exists()  # legacy folder untouched


def test_no_state_without_legacy_folder(fresh):
    fm.user_folder_id("config")
    assert fm.read_state(str(fresh / "config" / CONFIG_ID)) == {}


def test_default_settings_requested(fresh):
    make_legacy(fresh / "config", {"a": 1})
    fm.user_folder_id("config")
    _, new = config_dirs(fresh)
    assert fm.request_change(str(new), fm.STATE_RESET)
    fm._folder_ids.clear()  # next start
    assert fm.user_folder_id("config") == CONFIG_ID
    assert sorted(path.name for path in new.iterdir()) == [fm.STATE_FILE]  # empty: defaults, not copied again
    assert fm.read_state(str(new))["state"] == fm.STATE_DEFAULT
    aside = [path for path in (fresh / "config").iterdir() if path.name.startswith(f"{CONFIG_ID}.imported-")]
    assert len(aside) == 1 and json.loads((aside[0] / "config.json").read_text(encoding="utf-8")) == {"a": 1}
    fm._folder_ids.clear()  # later starts: nothing more
    fm.user_folder_id("config")
    assert fm.read_state(str(new))["state"] == fm.STATE_DEFAULT


def test_import_again_requested(fresh):
    old = make_legacy(fresh / "config", {"a": 1})
    fm.user_folder_id("config")
    _, new = config_dirs(fresh)
    (new / "config.json").write_text('{"changed": true}', encoding="utf-8")
    (old / "config.json").write_text('{"a": 2}', encoding="utf-8")
    assert fm.request_change(str(new), fm.STATE_REIMPORT)
    fm._folder_ids.clear()
    assert fm.user_folder_id("config") == CONFIG_ID
    assert json.loads((new / "config.json").read_text(encoding="utf-8")) == {"a": 2}
    assert fm.read_state(str(new))["state"] == fm.STATE_KEPT  # asked for it: not asked again
    aside = [path for path in (fresh / "config").iterdir() if ".before-import-" in path.name]
    assert len(aside) == 1 and json.loads((aside[0] / "config.json").read_text(encoding="utf-8")) == {"changed": True}


def test_import_again_without_legacy_folder(fresh):
    old = make_legacy(fresh / "config", {"a": 1})
    fm.user_folder_id("config")
    _, new = config_dirs(fresh)
    shutil.rmtree(old)
    assert not fm.request_change(str(new), fm.STATE_REIMPORT)  # refused at once
    fm.write_state(str(new), fm.STATE_REIMPORT)  # folder removed after the request
    fm._folder_ids.clear()
    assert fm.user_folder_id("config") == CONFIG_ID
    assert json.loads((new / "config.json").read_text(encoding="utf-8")) == {"a": 1}  # kept as is
    assert fm.read_state(str(new))["state"] == fm.STATE_KEPT


def test_request_kept_if_folder_locked(fresh, monkeypatch):
    make_legacy(fresh / "config", {"a": 1})
    fm.user_folder_id("config")
    _, new = config_dirs(fresh)
    fm.request_change(str(new), fm.STATE_RESET)
    rename = os.rename

    def locked(src, dst):
        if str(src) == str(new):
            raise PermissionError("in use")
        return rename(src, dst)

    monkeypatch.setattr(fm.os, "rename", locked)
    fm._folder_ids.clear()
    assert fm.user_folder_id("config") == CONFIG_ID
    assert json.loads((new / "config.json").read_text(encoding="utf-8")) == {"a": 1}  # used as is this run
    assert fm.read_state(str(new))["state"] == fm.STATE_RESET  # retried next start
    assert any(level == logging.ERROR for level, _ in fm._report)


def test_request_change_rejects_other_states(fresh):
    with pytest.raises(ValueError):
        fm.request_change(str(fresh), fm.STATE_KEPT)


def test_invalid_state_file_ignored(fresh):
    folder = fresh / "config" / CONFIG_ID
    folder.mkdir()
    (folder / fm.STATE_FILE).write_text("[1, 2]", encoding="utf-8")
    assert fm.read_state(str(folder)) == {}
    (folder / fm.STATE_FILE).write_text("{broken", encoding="utf-8")
    assert fm.read_state(str(folder)) == {}


def test_newer_tinypedal_settings_noted(fresh):
    make_legacy(fresh / "config", {"preset": {"version": "9.0.0"}})
    fm.user_folder_id("config")
    assert any("newer TinyPedal (9.0.0)" in message for _, message in fm._report)


def test_older_settings_not_noted(fresh):
    make_legacy(fresh / "config", {"preset": {"version": "2.40.0"}})
    fm.user_folder_id("config")
    assert not any("newer TinyPedal" in message for _, message in fm._report)
