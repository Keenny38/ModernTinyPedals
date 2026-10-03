"""Standings & relative widgets on a full field: every column, class & session variants"""

from importlib import import_module

import pytest
from PySide6.QtCore import QTimerEvent
from PySide6.QtGui import QColor

from tests.test_readers import lmu_api
from tests.test_widget_benchmark import drive, fill_field
from tinypedal.module_info import minfo
from tinypedal.setting import cfg

LIST_WIDGETS = ("standings", "relative")


@pytest.fixture
def field(ui_env, monkeypatch):
    """Default settings (saving disabled), 20 cars field in module data, API reader on in-memory shared memory"""
    from tinypedal.api_control import api

    saved_vehicles = (minfo.vehicles.dataSet, minfo.vehicles.totalVehicles, minfo.vehicles.playerIndex)
    fill_field(20)
    sim, data = lmu_api()
    monkeypatch.setattr(api, "_api", sim)
    monkeypatch.setattr(api, "read", sim.reader())
    yield data
    minfo.vehicles.dataSet, minfo.vehicles.totalVehicles, minfo.vehicles.playerIndex = saved_vehicles


def run_widget(name: str, data, frames: int = 4, **options):
    """Build widget with options, update & paint a few frames, return last image"""
    wcfg = cfg.user.setting[name]
    wcfg.update(options)
    widget = import_module(f"tinypedal.widget.{name}").Realtime(cfg, name)
    widget.adjustSize()
    event = QTimerEvent(0)
    try:
        image = None
        for frame in range(frames):
            drive(data, frame)
            widget.timerEvent(event)
            image = widget.grab().toImage()
        return image
    finally:
        widget.deleteLater()


def visible_pixels(image) -> int:
    step = 3
    return sum(
        1 for y in range(0, image.height(), step) for x in range(0, image.width(), step)
        if QColor(image.pixel(x, y)).alpha() > 0
    )


def all_columns(name: str) -> dict:
    """Every show_* option of widget enabled"""
    return {key: True for key, value in cfg.default.setting[name].items()
            if key.startswith("show_") and isinstance(value, bool)}


@pytest.mark.parametrize("name", LIST_WIDGETS)
@pytest.mark.parametrize("modern", [False, True])
def test_every_column(field, name, modern):
    cfg.user.config["overlay_style"]["enable_modern_style"] = modern
    default = run_widget(name, field)
    full = run_widget(name, field, **all_columns(name))
    assert visible_pixels(full) > 0
    assert full.width() > default.width()  # more columns drawn


@pytest.mark.parametrize("name", LIST_WIDGETS)
def test_race_session_and_class_split(field, name):
    from tinypedal.api_control import api

    field.scoring.scoringInfo.mSession = 10  # race
    assert api.read.session.in_race()
    options = all_columns(name)
    options.update({key: True for key in cfg.default.setting[name] if "split" in key and key.startswith("enable_")})
    image = run_widget(name, field, frames=6, **options)
    assert visible_pixels(image) > 0


@pytest.mark.parametrize("name", LIST_WIDGETS)
def test_small_and_empty_field(field, name):
    fill_field(1)  # player alone
    assert visible_pixels(run_widget(name, field)) > 0
    fill_field(3)
    assert visible_pixels(run_widget(name, field, **all_columns(name))) > 0
