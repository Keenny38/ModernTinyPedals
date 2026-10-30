"""Audit I, lot A: settings persistence, saving thread, start-up logging & file imports

BUG-001, BUG-008, BUG-015, BUG-019, BUG-020, BUG-021, BUG-052, PERF-009, PERF-017, PERF-019, PERF-020,
PERF-021, PERF-068. Each test is a case that failed before its fix.
"""

import errno
import json
import logging
import os
import threading
import time
import zipfile
from copy import deepcopy
from types import SimpleNamespace

import pytest

from neopedal import setting as setting_module
from neopedal.const_file import ConfigType
from neopedal.setting import Setting
from neopedal.userfile import json_setting


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


def read_json(path: str):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


# --- BUG-001: saver thread never a daemon, settings flushed at close
def test_saver_thread_not_daemon_when_started_from_daemon_thread(config):
    """Module threads (daemon) call cfg.save(): the saver inherited the flag and was killed at exit"""
    config.load_user()
    started = []
    real_thread = threading.Thread

    class SpyThread(real_thread):
        def start(self):
            started.append(self)
            super().start()

    setting_module.threading.Thread = SpyThread
    try:
        worker = real_thread(target=lambda: config.save(delay=0), daemon=True)
        worker.start()
        worker.join(5)
        wait_saved(config)
    finally:
        setting_module.threading.Thread = real_thread
    savers = [thread for thread in started if thread.name == "Setting saver"]
    assert savers and not any(thread.daemon for thread in savers)


def test_close_flushes_queued_saves(monkeypatch):
    """Quit never waited for the saving thread (restart did): data saved by stopped modules written at close"""
    from neopedal import loader, safe_mode
    from neopedal.setting import cfg

    calls = []
    monkeypatch.setattr(loader, "write_pending", lambda: calls.append("write_pending"))
    monkeypatch.setattr(loader, "unload_modules", lambda *args, **kwargs: calls.append("unload_modules"))
    monkeypatch.setattr(loader, "replay", SimpleNamespace(stop_recording=lambda: None, wait_closed=lambda t: True))
    monkeypatch.setattr(loader, "api", SimpleNamespace(stop=lambda: None, close=lambda: calls.append("api.close")))
    monkeypatch.setattr(safe_mode, "clear_marker", lambda path: None)
    monkeypatch.setattr(type(cfg), "flush", lambda self, *args: calls.append("cfg.flush"))
    loader.close()
    assert calls.index("unload_modules") < calls.index("api.close") < calls.index("cfg.flush")


# --- BUG-052: a failure before the saving loop leaves is_saving set forever
def test_saving_signal_failure_never_locks_saving_state(config, monkeypatch):
    config.load_user()
    monkeypatch.setattr(threading, "excepthook", lambda args: None)  # thread error expected, not reported

    def broken_emit(state):
        if state:
            raise RuntimeError("signal receiver gone")

    monkeypatch.setattr(setting_module, "app_signal", SimpleNamespace(saving=SimpleNamespace(emit=broken_emit)))
    config.save(delay=0)
    end = time.monotonic() + 5
    while config.is_saving and time.monotonic() < end:
        time.sleep(0.01)
    assert not config.is_saving  # next save starts a new saver


# --- BUG-008: backup copy refused for a moment, failed save tried again
def test_backup_copy_retried_on_permission_error(tmp_path, monkeypatch):
    folder = f"{tmp_path.as_posix()}/"
    with open(f"{folder}data.json", "w", encoding="utf-8") as file:
        json.dump({"old": True}, file)
    monkeypatch.setattr(json_setting, "sleep", lambda _: None)
    real_copy = json_setting.shutil.copyfile
    attempts = []

    def flaky_copy(src, dst):
        attempts.append(src)
        if len(attempts) < 3:  # antivirus holds the file for two tries
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_copy(src, dst)

    monkeypatch.setattr(json_setting.shutil, "copyfile", flaky_copy)
    assert json_setting.save_and_verify_json_file({"new": True}, "data.json", folder)
    assert len(attempts) == 3 and read_json(f"{folder}data.json") == {"new": True}


def test_failed_save_queued_again(config, monkeypatch):
    """Backup failed: data was dropped from the queue, lost if it was the last save (quit)"""
    config.load_user()
    monkeypatch.setattr(setting_module, "sleep", lambda _: None)
    real_save = setting_module.save_and_verify_json_file
    calls = []

    def failing_once(**kwargs):
        calls.append(kwargs["filename"])
        if len(calls) == 1:
            return False  # backup refused (see _save_with_backup)
        return real_save(**kwargs)

    monkeypatch.setattr(setting_module, "save_and_verify_json_file", failing_once)
    config.user.setting["overlay"]["fixed_position"] = True
    config.save(delay=0)
    wait_saved(config)
    assert calls == [config.filename.setting] * 2
    assert read_json(f"{config.path.settings}default.json")["overlay"]["fixed_position"] is True


def test_save_given_up_after_retries_tells_user(config, monkeypatch):
    config.load_user()
    monkeypatch.setattr(setting_module, "sleep", lambda _: None)
    calls = []
    monkeypatch.setattr(setting_module, "save_and_verify_json_file", lambda **kwargs: calls.append(1) is None and False)
    notices = []
    monkeypatch.setattr(json_setting, "_show_notice", notices.append)
    config.save(delay=0)
    wait_saved(config)
    assert len(calls) == setting_module.SAVE_RETRY_ATTEMPTS
    assert len(notices) == 1 and "default.json" in notices[0]
    assert config._save_queue == {} and not config.is_saving


def test_unreadable_file_never_queued_again(config, monkeypatch):
    """A file not readable at load is skipped on purpose (user data kept): no retry loop"""
    config.load_user()
    calls = []
    monkeypatch.setattr(setting_module, "save_and_verify_json_file", lambda **kwargs: calls.append(1) is None and False)
    monkeypatch.setattr(setting_module, "is_unreadable_file", lambda filename, filepath: True)
    config.save(delay=0)
    wait_saved(config)
    assert calls == [1]


# --- BUG-015: instance lock messages logged before log handlers existed (lost)
def test_log_stream_attached_before_single_instance_check(monkeypatch):
    from neopedal import main
    from neopedal.log_handler import BoundedLogStream

    handlers_before = main.logger.handlers[:]
    level_before = main.logger.level
    stream = BoundedLogStream()
    monkeypatch.setattr(main, "log_stream", stream)

    def lock_check(flag):
        main.logger.warning("Single instance lock still held by previous instance, started anyway")
        raise SystemExit  # rest of start not needed

    monkeypatch.setattr(main, "single_instance_check", lock_check)
    try:
        with pytest.raises(SystemExit):
            main.start_app(SimpleNamespace(single_instance=1, log_level=1, safe_mode=False))
    finally:
        for handler in main.logger.handlers[:]:
            if handler not in handlers_before:
                main.logger.removeHandler(handler)
        main.logger.setLevel(level_before)
    assert "started anyway" in stream.getvalue()


# --- BUG-019: clamped values list grew for the whole session
def test_clamped_values_hold_last_validation_only():
    from neopedal.setting_validator import CLAMPED, PresetValidator
    from neopedal.template.setting_widget import WIDGET_DEFAULT
    from neopedal.userfile.json_setting import copy_setting

    defaults = copy_setting(dict(WIDGET_DEFAULT))
    for _ in range(3):
        PresetValidator.user_preset({"speedometer": {"font_size": 999}}, defaults)
    assert CLAMPED == [("font_size", 999, 200)]
    PresetValidator.user_preset({"speedometer": {"font_size": 20}}, defaults)
    assert CLAMPED == []


# --- BUG-020: huge JSON integer raised OverflowError in float()
def test_catalog_with_huge_time_stamp_loads(tmp_path, monkeypatch):
    from neopedal.setting import cfg
    from neopedal.userfile import game_images

    monkeypatch.setattr(cfg.path, "game_image", f"{tmp_path.as_posix()}/")
    with open(tmp_path / game_images.CATALOG_FILE, "w", encoding="utf-8") as file:
        file.write('{"vehicles": [], "tracks": {}, "missing": {"/a.svg": 1' + "0" * 400 + ', "/b.svg": 1700000000,'
                   ' "/c.svg": -5, "/d.svg": true}}')
    cache = game_images.GameImages()
    cache.load_catalog()
    assert cache.missing == {"/b.svg": 1700000000.0}


def test_trash_entry_with_huge_deletion_time_is_invalid(tmp_path):
    from neopedal.userfile import preset_trash

    folder = tmp_path / "entry"
    folder.mkdir()
    (folder / "race.json").write_text("{}", encoding="utf-8")
    (folder / preset_trash.INFO_FILENAME).write_text(
        '{"filename": "race.json", "deleted": 1' + "0" * 400 + ', "references": {}}', encoding="utf-8")
    assert preset_trash.read_entry(str(folder)) is None
    assert preset_trash.list_trash(str(tmp_path)) == []  # entry folder is not a trash folder here: no crash either


# --- BUG-021: atomic_write discarded data silently, caller logged "saved" inside the block
def test_atomic_write_tells_failure(tmp_path):
    from neopedal.userfile import atomic_write

    with atomic_write(str(tmp_path / "missing" / "file.txt")) as file:
        file.write("data")
    assert file.failed is True
    with atomic_write(str(tmp_path / "file.txt")) as file:
        file.write("data")
    assert file.failed is False and (tmp_path / "file.txt").read_text(encoding="utf-8") == "data"


def test_car_setup_not_logged_saved_when_write_failed(tmp_path, caplog):
    from neopedal.userfile.car_setup import save_car_setup_file

    with caplog.at_level(logging.INFO, logger="neopedal.userfile.car_setup"):
        save_car_setup_file(f"{tmp_path.as_posix()}/missing/", "setup", ("[GENERAL]", "a=1"))
        save_car_setup_file(f"{tmp_path.as_posix()}/", "setup", ("[GENERAL]", "a=1"))
    saved = [record.message for record in caplog.records if "saved" in record.message]
    assert saved == ["USERDATA: setup.svm saved"]
    assert (tmp_path / "setup.svm").read_bytes() == b"[GENERAL]\r\na=1\r\n"


# --- PERF-009: only files held for a moment are retried, shorter wait at reload
def test_permanent_access_error_not_retried(tmp_path, monkeypatch):
    folder = f"{tmp_path.as_posix()}/"
    os.mkdir(f"{folder}user.json")  # a folder in place of the file: IsADirectoryError / EACCES forever
    sleeps = []
    monkeypatch.setattr(json_setting, "sleep", sleeps.append)
    monkeypatch.setattr(json_setting, "_unreadable_files", set())
    real_open = open

    def folder_open(file, *args, **kwargs):
        if str(file).endswith("user.json"):
            raise IsADirectoryError(errno.EISDIR, "Is a directory")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", folder_open)
    started = time.monotonic()
    loaded = json_setting.load_setting_json_file("user.json", folder, {"a": {"b": 1}}, validator=lambda u, d: u)
    assert loaded == {"a": {"b": 1}} and sleeps == [] and time.monotonic() - started < 1
    assert json_setting.is_unreadable_file("user.json", folder)


def test_transient_errors_only():
    assert json_setting.is_transient_access_error(PermissionError(errno.EACCES, "denied"))
    assert not json_setting.is_transient_access_error(OSError(errno.EISDIR, "folder"))
    assert not json_setting.is_transient_access_error(OSError(errno.EIO, "disk"))
    held = OSError(errno.EACCES, "sharing violation", "x", 32)
    assert json_setting.is_transient_access_error(held)
    assert not json_setting.is_transient_access_error(OSError(errno.EACCES, "other", "x", 123))


def test_reload_waits_less_for_held_files(config, monkeypatch):
    timeouts = []
    real_read = setting_module.read_setting_json_file

    def spy(**kwargs):
        timeouts.append(kwargs.get("access_timeout"))
        return real_read(**kwargs)

    monkeypatch.setattr(setting_module, "read_setting_json_file", spy)
    config.load_user()  # start
    config.load_user()  # reload, on the GUI thread
    assert timeouts == [json_setting.ACCESS_TIMEOUT, json_setting.RELOAD_ACCESS_TIMEOUT]
    assert json_setting.RELOAD_ACCESS_TIMEOUT < 0.5


# --- PERF-017: package import on the GUI thread, one fsync per entry
def test_package_import_flushes_folders_once(tmp_path, monkeypatch):
    from neopedal.userfile import preset_package

    package = tmp_path / "pack.zip"
    with zipfile.ZipFile(package, "w") as zip_file:
        zip_file.writestr("manifest.json", json.dumps({"format": preset_package.PACKAGE_FORMAT, "version": 1,
                                                       "preset": "a.json"}))
        zip_file.writestr("presets/a.json", "{}")
        zip_file.writestr("presets/b.json", "{}")
        zip_file.writestr("styles/classes.json", "{}")
        zip_file.writestr("tracknotes/track.tptn", "notes")
    settings = tmp_path / "settings"
    notes = tmp_path / "tracknotes"
    settings.mkdir()
    notes.mkdir()
    writes, synced = [], []
    real_replace = preset_package.atomic_replace
    monkeypatch.setattr(preset_package, "atomic_replace",
                        lambda path, data, **kwargs: writes.append(kwargs.get("fsync")) or real_replace(path, data, **kwargs))
    monkeypatch.setattr(preset_package, "sync_folder", synced.append)
    result = preset_package.import_preset_package(
        str(package), f"{settings.as_posix()}/", overwrite_styles=True, notes_paths={"tracknotes": str(notes)})
    assert result.presets == ["a.json", "b.json"] and result.styles == ["classes.json"] and result.notes == 1
    assert writes == [False, False, True, False]  # new files not flushed one by one, replaced style file is
    assert sorted(os.path.normcase(folder) for folder in synced) == sorted(
        os.path.normcase(folder) for folder in (settings.as_posix(), str(notes)))


# --- PERF-019: catalog rewritten for each missing picture of a burst
def test_catalog_saved_once_after_burst_of_missing_pictures(tmp_path, monkeypatch):
    from neopedal.process import game_images as gi
    from neopedal.setting import cfg
    from neopedal.userfile import game_images

    monkeypatch.setattr(cfg.path, "game_image", f"{tmp_path.as_posix()}/")
    monkeypatch.setattr(game_images, "fetch_from_game", lambda resource, max_body=None: (404, b"<html>"))
    cache = game_images.GameImages()
    saves = []
    real_save = cache.save_catalog
    monkeypatch.setattr(cache, "save_catalog", lambda: saves.append(1) or real_save())
    cache._jobs.put((gi.BRAND, "Later"))  # more fetches queued: a burst
    assert not cache.fetch_picture(gi.BRAND, "Nobody")
    assert saves == [] and cache._catalog_dirty
    cache._jobs.get()  # queue drained
    assert not cache.fetch_picture(gi.BRAND, "Other")
    assert saves == [1] and not cache._catalog_dirty
    saved = read_json(os.path.join(cache.folder, game_images.CATALOG_FILE))
    assert set(saved["missing"]) == {gi.image_path(gi.BRAND, "Nobody"), gi.image_path(gi.BRAND, "Other")}


# --- PERF-020: unchanged settings rewritten (backup, write, read back) at each start & save
def test_unchanged_file_not_rewritten(tmp_path, monkeypatch):
    folder = f"{tmp_path.as_posix()}/"
    data = {"widget": {"enable": True}}
    assert json_setting.save_and_verify_json_file(data, "data.json", folder)
    path = f"{folder}data.json"
    old_time = os.path.getmtime(path) - 100
    os.utime(path, (old_time, old_time))
    writes = []
    monkeypatch.setattr(json_setting, "save_json_file", lambda *args, **kwargs: writes.append(1))
    monkeypatch.setattr(json_setting, "create_backup_file", lambda *args, **kwargs: writes.append(1))
    assert json_setting.save_and_verify_json_file(data, "data.json", folder)
    assert writes == []  # neither backup nor write
    assert os.path.getmtime(path) > old_time  # most recent preset is still the one loaded last
    assert read_json(path) == data


def test_start_saves_only_files_changed_by_loading(config):
    config.load_user()  # preset missing: created
    assert config.save_loaded() and config.filename.setting in config._save_queue
    wait_saved(config)
    assert not config.save_loaded()  # queued once
    config.load_user()  # file as saved: nothing to write
    assert not config.save_loaded() and config._save_queue == {}
    with open(f"{config.path.settings}default.json", "w", encoding="utf-8") as file:
        json.dump({"overlay": {"fixed_position": True}}, file)  # edited by hand: repaired by validator
    config.load_user()
    assert config.save_loaded()
    wait_saved(config)
    assert read_json(f"{config.path.settings}default.json")["overlay"]["fixed_position"] is True


def test_global_settings_saved_only_when_changed(config):
    config.load_global()  # config & shortcuts missing: written
    assert config.save_loaded(ConfigType.CONFIG) and config.save_loaded(ConfigType.SHORTCUTS)
    wait_saved(config)
    config.load_global()
    assert not config.save_loaded(ConfigType.CONFIG) and not config.save_loaded(ConfigType.SHORTCUTS)


# --- PERF-021: style files written with fsync on the GUI thread at reload, without backup nor verification
def test_style_repaired_at_reload_saved_by_saving_thread(config, monkeypatch):
    config.load_user()  # start: styles created at once
    classes = f"{config.path.settings}{config.filename.classes}"
    assert os.path.exists(classes)
    with open(classes, "w", encoding="utf-8") as file:
        json.dump({"GT3": {}}, file)  # keys missing: repaired by validator
    writes, saved = [], []
    monkeypatch.setattr(setting_module, "save_json_file", lambda *args, **kwargs: writes.append(args[1]))
    real_save = setting_module.save_and_verify_json_file
    monkeypatch.setattr(setting_module, "save_and_verify_json_file",
                        lambda **kwargs: saved.append((kwargs["filename"], threading.current_thread().name))
                        or real_save(**kwargs))
    config.load_user()  # reload on GUI thread
    assert writes == []  # not written on this thread
    assert config.flush(timeout=5)
    wait_saved(config)
    assert (config.filename.classes, "Setting saver") in saved  # queued: backup, write & read back
    assert "color" in read_json(classes)["GT3"]


# --- PERF-068: settings import copied recorded laps, pictures & trash before any window
def test_settings_import_skips_data_folders(tmp_path):
    from neopedal.userfile import settings_import as si

    source = tmp_path / "old"
    for folder in ("settings", "telemetry", "gameimage", "settings/trash", "pacenotes"):
        (source / folder).mkdir(parents=True)
    (source / "config.json").write_text("{}", encoding="utf-8")
    (source / "settings" / "default.json").write_text("{}", encoding="utf-8")
    (source / "settings" / "trash" / "x.json").write_text("{}", encoding="utf-8")
    (source / "telemetry" / "lap.csv.gz").write_bytes(b"x" * 1000)
    (source / "gameimage" / "logo.png").write_bytes(b"x")
    (source / "pacenotes" / "track.tppn").write_text("notes", encoding="utf-8")
    target = tmp_path / "config"
    si.replace_folder(str(source), str(target), "20260101-000000")
    assert sorted(os.listdir(target)) == ["config.json", "pacenotes", "settings"]
    assert os.listdir(target / "settings") == ["default.json"]
