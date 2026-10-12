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
