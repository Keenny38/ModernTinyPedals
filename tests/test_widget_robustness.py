"""Every widget must survive degenerate telemetry.

Readers sanitise game data, so nan/inf should never reach a widget in practice. This guards
the consequence rather than the likelihood: a nan reaching an int conversion inside a paint
path aborts the process at the C++ level, taking the whole overlay down with it.
"""

import math
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication

from tinypedal.module_info import minfo
from tinypedal.setting import cfg
from tinypedal.template.widget import WIDGET_DISPLAY_ORDER
from tinypedal.widget._modern import create_widget

EXTREME_VALUES = {
    "zero": 0.0,
    "nan": math.nan,
    "inf": math.inf,
    "huge": 1e12,
    "negative": -9999.0,
}
FUZZED_GROUPS = ("wheels", "hybrid", "fuel", "energy", "delta", "force", "stint")


def fill_module_output(monkeypatch, value):
    """Set every float output of the data modules to one extreme value"""
    for group_name in FUZZED_GROUPS:
        group = getattr(minfo, group_name, None)
        if group is None:
            continue
        for slot in getattr(type(group), "__slots__", ()):
            try:
                current = getattr(group, slot)
            except AttributeError:
                continue
            if isinstance(current, float):
                monkeypatch.setattr(group, slot, value)
            elif isinstance(current, list) and current and isinstance(current[0], float):
                monkeypatch.setattr(group, slot, [value] * len(current))


@pytest.mark.parametrize("mode", list(EXTREME_VALUES))
def test_widgets_survive_extreme_values(ui_env, monkeypatch, mode):
    fill_module_output(monkeypatch, EXTREME_VALUES[mode])
    failures = []
    for name in WIDGET_DISPLAY_ORDER:
        widget = None
        try:
            widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
            widget.timerEvent(None)
            widget.grab()
        except Exception as error:  # collect every widget, report them together
            failures.append(f"{name}: {error!r}")
        finally:
            if widget is not None:
                # Run deletion from code named after the widget: if it crashes the process,
                # the faulthandler traceback shows File "<delete name>", naming the culprit
                code = compile("widget.deleteLater(); QCoreApplication.processEvents()", f"<delete {name}>", "exec")
                exec(code, {"widget": widget, "QCoreApplication": QCoreApplication})  # free it now
    assert not failures, f"{mode} values broke: " + "; ".join(failures)


def test_calculation_helpers_reject_non_finite():
    """Helpers feeding round()/floor()/tan() must not pass nan or inf through"""
    from tinypedal import calculation as calc

    assert calc.end_stint_laps(math.nan, 2.0) == 0
    assert calc.end_stint_laps(10.0, math.nan) == 0
    assert calc.end_stint_laps(10.0, math.inf) == 0
    assert calc.end_stint_laps(10.0, 2.0) == 5.0  # still works normally
    assert calc.turning_radius(math.inf, 2.8) == 0.0
    assert calc.turning_radius(math.nan, 2.8) == 0.0
    assert calc.ackermann_percentage(math.inf, math.inf, 1.6, 2.8) == 0.0
    assert calc.ackermann_percentage(math.nan, 0.0, 1.6, 2.8) == 0.0
