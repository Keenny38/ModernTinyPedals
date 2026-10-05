"""Every widget, both designs, with on/off options all on, all off and in random mixes

A widget reading an option to show a part it never built for that option (or the other way
round) fails here: options are switched together in combinations no default preset has.
Random mixes are seeded, so a failure is reproduced by running the same mode again.
"""

import random
import traceback
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication, QTimerEvent

from tests.test_readers import lmu_api
from tests.test_widget_benchmark import drive, fill_field
from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.template.widget import WIDGET_DISPLAY_ORDER
from tinypedal.widget._modern import create_widget

FIELD_SIZE = 20
FRAMES = 3
RANDOM_MIXES = 8
MODES = ("on", "off", *(f"random{seed}" for seed in range(RANDOM_MIXES)))
SKIPPED_OPTIONS = {"enable", "enable_classic_layout"}  # design is chosen by test
FIELD_ATTRIBUTES = {
    minfo.vehicles: (
        "dataSet", "dataSetVersion", "totalVehicles", "playerIndex", "leaderIndex", "leaderBestLapTime",
        "nearestLine", "nearestTraffic", "totalCompletedLaps",
    ),
    minfo.relative: ("standings", "drawOrder", "relativeAhead", "relativeBehind"),
}


@pytest.fixture
def live(ui_env, bundled_fonts, monkeypatch):
    """API reader on in-memory shared memory, field of cars in data module output"""
    from tinypedal.api_control import api

    sim, data = lmu_api()
    monkeypatch.setattr(api, "_api", sim)
    monkeypatch.setattr(api, "read", sim.reader())
    for owner, names in FIELD_ATTRIBUTES.items():
        for name in names:  # restored after test
            monkeypatch.setattr(owner, name, getattr(owner, name))
    fill_field(FIELD_SIZE)
    return data


def switch_options(options: dict, mode: str, rng: random.Random):
    for key, value in options.items():
        if isinstance(value, bool) and key not in SKIPPED_OPTIONS:
            options[key] = {"on": True, "off": False}.get(mode, rng.random() < 0.5)


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
@pytest.mark.parametrize("mode", MODES)
def test_widget_option_sweep(live, mode, modern):
    cfg.user.config["overlay_style"]["enable_modern_style"] = modern
    failures = []
    event = QTimerEvent(0)
    for name in WIDGET_DISPLAY_ORDER:
        switch_options(cfg.user.setting[name], mode, random.Random(f"{mode}-{name}"))
        widget = None
        try:
            widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
            widget.adjustSize()
            for frame in range(FRAMES):
                drive(live, frame)
                widget.timerEvent(event)
                widget.grab()
        except Exception:  # collect every widget, report them together
            failures.append(f"{name}: {traceback.format_exc(limit=-2)}")
        finally:
            if widget is not None:
                widget.deleteLater()
    QCoreApplication.processEvents()
    assert not failures, f"options {mode}:\n" + "\n".join(failures)
