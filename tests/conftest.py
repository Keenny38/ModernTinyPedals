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


_TEXT_READERS = ("version", "track_name", "combo_name", "class_name", "driver_name", "vehicle_name")
# Groups whose readers return one value per wheel (FL, FR, RL, RR). Same method name means a
# different shape depending on the group (Vehicle.position_vertical is a scalar, Wheel's is a set).
_WHEEL_GROUPS = ("tyre", "brake", "wheel")
# Readers of a wheel group that still return a single value
_WHEEL_GROUP_SCALARS = ("bias_front", "migration", "offroad", "is_wheel_locked")


class _FakeGroup:
    """API reader group, any method returns a neutral value of the expected shape"""

    def __init__(self, group_name: str = ""):
        self._group_name = group_name

    def __getattr__(self, name):
        wheel_set = self._group_name in _WHEEL_GROUPS and name not in _WHEEL_GROUP_SCALARS

        def reader(*args, **kwargs):
            if name in _TEXT_READERS:
                return "test"
            if name == "surface_temperature_ico":
                return (0,) * 12
            if name == "damage_severity":
                return (0,) * 8
            if wheel_set:
                return ("",) * 4 if name in ("compound_class", "compound_name") else (0,) * 4
            return 0
        return reader


class _FakeReader:
    """API reader (no game running)

    Groups are cached, so tests can monkeypatch a single reader (api.read.tyre.wear, ...).
    """

    def __getattr__(self, name):
        group = _FakeGroup(name)
        setattr(self, name, group)  # cache, so the same object is returned next time
        return group
