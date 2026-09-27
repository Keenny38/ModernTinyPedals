"""Pytest shared setup"""

import os
import sys

import pytest

# Run from repository root, headless Qt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

# QApplication must exist before collecting tests, as UI modules read font metrics on import
QT_APP = QApplication.instance() or QApplication(sys.argv)



@pytest.fixture
def ui_env(monkeypatch, tmp_path):
    """Isolated setting for UI tests: default presets, data paths in tmp folder, saving disabled"""
    from tinypedal.setting import FilePath, Preset, Setting, cfg
    from tinypedal.userfile.json_setting import copy_setting

    cfg.default.set_default()
    for name in Preset.__slots__:
        monkeypatch.setattr(cfg.user, name, copy_setting(dict(getattr(cfg.default, name))), raising=False)
    for name in FilePath.__slots__:
        folder = tmp_path / name
        folder.mkdir()
        monkeypatch.setattr(cfg.path, name, f"{folder.as_posix()}/")
    (tmp_path / "settings" / "default.json").write_text("{}", encoding="utf-8")
    # API connected but not started, reader returns neutral values
    from tinypedal.api_control import api

    api.connect()
    monkeypatch.setattr(api, "read", _FakeReader())
    saved = []
    monkeypatch.setattr(Setting, "save", lambda self, *args, **kwargs: saved.append(kwargs.get("config_type", "setting")))
    return saved


class _FakeGroup:
    """API reader group, any method returns neutral value"""

    def __getattr__(self, name):
        def reader(*args, **kwargs):
            if name in ("version", "track_name", "combo_name", "class_name", "driver_name", "vehicle_name"):
                return "test"
            return 0
        return reader


class _FakeReader:
    """API reader (no game running)"""

    def __getattr__(self, name):
        return _FakeGroup()
