"""Global settings imported from a folder chosen by user, applied on next start"""

import json
import logging
import os
import shutil

import pytest

from neopedal.userfile import settings_import as si


@pytest.fixture(autouse=True)
def empty_report(monkeypatch):
    monkeypatch.setattr(si, "_report", [])


def make_source(folder, config=None):
    (folder / "languages").mkdir(parents=True)
    (folder / "languages" / "de.json").write_text("{}", encoding="utf-8")
    (folder / "shortcuts.json").write_text("{}", encoding="utf-8")
    (folder / "pid.log").write_text("123", encoding="utf-8")
    (folder / "config.lock").write_text("", encoding="utf-8")
    (folder / "config.json").write_text(json.dumps(config or {"application": {"x": 1}}), encoding="utf-8")
    return folder


def make_current(folder):
    folder.mkdir(parents=True)
    (folder / "config.json").write_text('{"current": true}', encoding="utf-8")
    return folder


def test_settings_folder_check(tmp_path):
    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    (tmp_path / "Empty").mkdir()
    assert si.is_settings_folder(str(source), str(current))
    assert not si.is_settings_folder(str(current), str(current))  # own folder
    assert not si.is_settings_folder(str(tmp_path / "Empty"), str(current))  # no settings
    assert not si.is_settings_folder(str(tmp_path / "Missing"), str(current))
    inside = make_source(current / "backup")
    assert not si.is_settings_folder(str(inside), str(current))  # copied into itself


def test_import_applied_on_next_start(tmp_path, caplog):
    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    assert si.request_import(str(current), str(source))
    assert si.read_request(str(current)) == str(source)
    assert si.apply_pending_import(str(current))
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"application": {"x": 1}}
    assert (current / "languages" / "de.json").is_file()
    # Runtime files & request not copied, source untouched, current settings set aside
    assert not (current / "pid.log").exists() and not (current / "config.lock").exists()
    assert not (current / si.REQUEST_FILE).exists()
    assert (source / "pid.log").is_file()
    aside = [name for name in os.listdir(tmp_path) if name.startswith("NeoPedal.before-import-")]
    assert len(aside) == 1
    assert json.loads((tmp_path / aside[0] / "config.json").read_text(encoding="utf-8")) == {"current": True}
    assert not si.apply_pending_import(str(current))  # done once
    with caplog.at_level(logging.INFO):
        si.log_import_report()
    assert "settings copied" in caplog.text and si._report == []


def test_no_request(tmp_path):
    current = make_current(tmp_path / "NeoPedal")
    assert not si.apply_pending_import(str(current))
    assert si._report == []


def test_failed_copy_keeps_current_settings(tmp_path, monkeypatch):
    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    si.request_import(str(current), str(source))

    def broken_copy(src, dst, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(si.shutil, "copytree", broken_copy)
    assert not si.apply_pending_import(str(current))
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"current": True}
    assert not (current / si.REQUEST_FILE).exists()  # not retried at every start
    assert sorted(os.listdir(tmp_path)) == ["NeoPedal", "Other"]


def test_files_in_use_import_tried_again_next_start(tmp_path, monkeypatch):
    """Current folder in use (instance closing, antivirus): request kept for the next starts, at most
    MAX_IMPORT_ATTEMPTS times, then dropped; imported once files are free"""
    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    si.request_import(str(current), str(source))
    rename = os.rename

    def busy_rename(src, dst):
        if os.path.basename(str(src)) == "NeoPedal":
            raise PermissionError(13, "file in use", str(src))
        rename(src, dst)

    monkeypatch.setattr(si.os, "rename", busy_rename)
    for attempt in range(1, si.MAX_IMPORT_ATTEMPTS):
        assert not si.apply_pending_import(str(current))
        assert si.read_request(str(current)) == str(source)  # kept for next start
        assert any(f"attempt {attempt} of" in message for _level, message in si._report)
    monkeypatch.setattr(si.os, "rename", rename)
    assert si.apply_pending_import(str(current))  # files free: imported
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"application": {"x": 1}}
    si._report.clear()


def test_import_dropped_after_last_attempt(tmp_path, monkeypatch):
    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    si.request_import(str(current), str(source))
    rename = os.rename
    monkeypatch.setattr(si.os, "rename", lambda src, dst: (_ for _ in ()).throw(PermissionError(13, "in use"))
                        if os.path.basename(str(src)) == "NeoPedal" else rename(src, dst))
    for _ in range(si.MAX_IMPORT_ATTEMPTS):
        assert not si.apply_pending_import(str(current))
    assert not (current / si.REQUEST_FILE).exists()  # never tried at every start
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"current": True}
    assert not si.is_temporary_error(OSError("copy failed: [Errno 28] No space left"))
    si._report.clear()


def test_unreadable_files_left_out(tmp_path, monkeypatch):
    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    si.request_import(str(current), str(source))
    copytree = shutil.copytree

    def copy_then_fail(src, dst, *args, **kwargs):
        copytree(src, dst, *args, **kwargs)
        raise shutil.Error([(f"{src}/locked.json", f"{dst}/locked.json", "in use")])

    monkeypatch.setattr(si.shutil, "copytree", copy_then_fail)
    assert si.apply_pending_import(str(current))
    assert (current / "shortcuts.json").is_file()
    assert any("locked.json" in message for _, message in si._report)


def test_source_gone_nothing_imported(tmp_path):
    current = make_current(tmp_path / "NeoPedal")
    si.request_import(str(current), str(tmp_path / "Gone"))
    assert not si.apply_pending_import(str(current))
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"current": True}


def test_linux_data_folder_and_user_paths(tmp_path):
    config_base, data_base = tmp_path / "config", tmp_path / "data"
    current = make_current(config_base / "NeoPedal")
    current_data = data_base / "NeoPedal"
    current_data.mkdir(parents=True)
    source_data = data_base / "Other"
    (source_data / "trackmap").mkdir(parents=True)
    (source_data / "trackmap" / "spa.svg").write_text("<svg/>", encoding="utf-8")
    source = make_source(config_base / "Other", {"user_path": {
        "settings_path": f"{(config_base / 'Other').as_posix()}/settings/",
        "track_map_path": f"{source_data.as_posix()}/trackmap/",
        "telemetry_path": "/mnt/other/telemetry/",
    }})
    si.request_import(str(current), str(source))
    assert si.apply_pending_import(str(current), str(current_data))
    assert (current_data / "trackmap" / "spa.svg").is_file()
    config = json.loads((current / "config.json").read_text(encoding="utf-8"))
    assert config["user_path"] == {
        "settings_path": f"{current.as_posix()}/settings/",
        "track_map_path": f"{current_data.as_posix()}/trackmap/",
        "telemetry_path": "/mnt/other/telemetry/",
    }


def test_menu_import_requests_and_restarts(ui_env, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from neopedal.setting import cfg
    from neopedal.ui import settings_import as ui_import

    source = make_source(tmp_path / "Other")
    restarted, warnings = [], []
    monkeypatch.setattr(ui_import.QFileDialog, "getExistingDirectory", lambda *args: str(source))
    monkeypatch.setattr(ui_import.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ui_import.QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(ui_import.QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(ui_import.loader, "restart", lambda: restarted.append(True))
    ui_import.import_settings(None)
    assert restarted and not warnings
    assert si.read_request(cfg.path.config) == str(source)
    os.remove(os.path.join(cfg.path.config, si.REQUEST_FILE))
    # Not a settings folder: warned, nothing asked
    (tmp_path / "Empty").mkdir()
    monkeypatch.setattr(ui_import.QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path / "Empty"))
    ui_import.import_settings(None)
    assert len(warnings) == 1 and len(restarted) == 1
    assert not si.read_request(cfg.path.config)


def test_import_waits_for_other_running_instance(tmp_path, monkeypatch):
    """Import applied at start only once no other instance runs (it would save over imported settings)"""
    from neopedal import main, realtime_state

    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    si.request_import(str(current), str(source))
    monkeypatch.setattr(main, "settings_import_folders", lambda: (str(current), ""))
    monkeypatch.setattr(realtime_state, "singleton", False)
    monkeypatch.setattr(main, "other_instance_running", lambda: True)  # multiple instances allowed, another one running
    main.apply_settings_import()
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"current": True}
    assert si.read_request(str(current)) == str(source)  # kept for next start
    assert any("another NeoPedal is running" in message for _, message in si._report)
    monkeypatch.setattr(realtime_state, "singleton", True)  # single instance check passed: only instance
    main.apply_settings_import()
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"application": {"x": 1}}


def test_every_backup_kept(tmp_path, monkeypatch):
    """Settings set aside by each import kept (told so before importing), an earlier backup can be imported back"""
    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    stamps = iter(("20260101-000000", "20260102-000000"))

    class Clock:
        @staticmethod
        def now():
            class Now:
                @staticmethod
                def strftime(_):
                    return next(stamps)

                @staticmethod
                def isoformat(**_):
                    return ""
            return Now

    monkeypatch.setattr(si, "datetime", Clock)
    si.request_import(str(current), str(source))
    assert si.apply_pending_import(str(current))
    first = tmp_path / "NeoPedal.before-import-20260101-000000"
    si.request_import(str(current), str(first))  # original settings imported back
    assert si.apply_pending_import(str(current))
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"current": True}
    assert first.is_dir() and (tmp_path / "NeoPedal.before-import-20260102-000000").is_dir()


def test_disk_full_copy_not_used(tmp_path, monkeypatch):
    """Copy errors of a failing disk (files cut short): import cancelled, unlike files left out in use"""
    current = make_current(tmp_path / "NeoPedal")
    source = make_source(tmp_path / "Other")
    si.request_import(str(current), str(source))
    copytree = shutil.copytree

    def copy_disk_full(src, dst, *args, **kwargs):
        copytree(src, dst, *args, **kwargs)
        raise shutil.Error([(f"{src}/config.json", f"{dst}/config.json", "[Errno 28] No space left on device")])

    monkeypatch.setattr(si.shutil, "copytree", copy_disk_full)
    assert not si.apply_pending_import(str(current))
    assert json.loads((current / "config.json").read_text(encoding="utf-8")) == {"current": True}
    assert sorted(os.listdir(tmp_path)) == ["NeoPedal", "Other"]


def test_linux_data_put_back_when_settings_not_imported(tmp_path, monkeypatch):
    config_base, data_base = tmp_path / "config", tmp_path / "data"
    current = make_current(config_base / "NeoPedal")
    current_data = data_base / "NeoPedal"
    current_data.mkdir(parents=True)
    (current_data / "mine.txt").write_text("current", encoding="utf-8")
    source_data = data_base / "Other"
    source_data.mkdir(parents=True)
    (source_data / "other.txt").write_text("source", encoding="utf-8")
    source = make_source(config_base / "Other")
    si.request_import(str(current), str(source))
    copytree = shutil.copytree

    def copy_data_only(src, dst, *args, **kwargs):
        if os.path.basename(src) == "Other" and "config" in src:
            raise OSError("disk full")
        return copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(si.shutil, "copytree", copy_data_only)
    assert not si.apply_pending_import(str(current), str(current_data))
    assert sorted(os.listdir(current_data)) == ["mine.txt"]  # data matching current settings
    assert sorted(os.listdir(data_base)) == ["NeoPedal", "Other"]


# --- Preset values out of allowed range brought back at load, preset check lists & repairs them
def test_values_out_of_range_clamped_at_load():
    from neopedal.setting_validator import CLAMPED, PresetValidator
    from neopedal.template.setting_widget import WIDGET_DEFAULT
    from neopedal.userfile.json_setting import copy_setting

    defaults = copy_setting(dict(WIDGET_DEFAULT))
    preset = {"speedometer": {"font_size": 999, "bar_padding": 1000.0, "opacity": 0.5,
                              "display_order_speed": -5, "display_order_speed_minimum": 1}}
    CLAMPED.clear()
    checked = PresetValidator.user_preset(preset, defaults)
    speedometer = checked["speedometer"]
    assert speedometer["font_size"] == 200 and isinstance(speedometer["font_size"], int)
    assert speedometer["bar_padding"] == 10 and speedometer["opacity"] == 0.5
    assert min(value for key, value in speedometer.items() if key.startswith("display_order_")) >= 0
    assert ("font_size", 999, 200) in CLAMPED


def test_preset_check_lists_and_repairs(tmp_path):
    from neopedal.template.setting_widget import WIDGET_DEFAULT
    from neopedal.userfile.json_setting import copy_setting
    from neopedal.userfile.preset_check import check_preset_file

    (tmp_path / "race.json").write_text(json.dumps({
        "speedometer": {"font_size": 999, "no_such_option": 1, "opacity": "high"}, "no_such_overlay": {}}),
        encoding="utf-8")
    checked, changes = check_preset_file("race.json", f"{tmp_path}/", copy_setting(dict(WIDGET_DEFAULT)))
    assert "speedometer: font_size 999 -> 200" in changes
    assert "speedometer: no_such_option unknown or renamed, removed" in changes
    assert any(change.startswith("speedometer: opacity") for change in changes)
    assert "no_such_overlay: unknown, removed" in changes
    assert checked["speedometer"]["font_size"] == 200
    _, again = check_preset_file("race.json", f"{tmp_path}/", copy_setting(dict(WIDGET_DEFAULT)))
    assert again == changes  # file not changed by the check
