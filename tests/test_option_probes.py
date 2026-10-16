"""Options of every overlay checked together, both designs (were one-off probes of the options audit)

- Every option of the default preset is read somewhere in the overlay code: no dead option shown.
- Every number option at the limits the Overlay Options page accepts: overlay made, updated & drawn without
  error, too big ones cut by the overlay size guard (see widget._base.MAX_OVERLAY_SIDE), never a crash.
- Dependencies & section toggles of the page name on/off options of the same overlay.
- Display orders: swapping two shown items moves them on the overlay picture.

A crash (not an exception) in Qt drawing is reported by faulthandler (see conftest) with the widget & option:
the option under test is printed before each drawing (shown with pytest -s).
"""

from __future__ import annotations

import ast
import itertools
import re
import sys
import traceback
from importlib import import_module
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QTimerEvent

from neopedal.setting import cfg
from neopedal.template.setting_widget import WIDGET_DEFAULT
from neopedal.template.widget import WIDGET_DISPLAY_ORDER
from tests.test_widget_benchmark import drive
from tests.test_widget_option_sweep import live, reference_loading  # noqa: F401  # fixtures

SOURCE = Path(__file__).resolve().parent.parent / "neopedal"
DESIGNS = pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
FIXED_OPTIONS = {"enable", "enable_classic_layout", "position_x", "position_y"}
UNLIMITED_TRY = 1000  # number options without limit: tried at +/- this


# Options read in code ------------------------------------------------------------------------------------
def code_references() -> tuple[set[str], list[re.Pattern]]:
    """String literals of overlay code (widgets, modules, option rules of templates), and patterns of option
    names built at run time (f-strings with a fixed part, prefixes tested by str.startswith)

    Page code (ui), translations & default presets (template, but *_ui.py & modern.py) left out: an option
    only listed there is shown, never used.
    """
    literals: set[str] = set()
    patterns: list[re.Pattern] = []
    for path in SOURCE.rglob("*.py"):
        part = path.relative_to(SOURCE).parts[0]
        if part in ("ui", "i18n") or (part == "template" and not (
                path.name.endswith("_ui.py") or path.name == "modern.py")):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
            elif isinstance(node, ast.JoinedStr):
                fixed = [value.value for value in node.values if isinstance(value, ast.Constant)]
                if sum(map(len, fixed)) >= 5:  # not a bare f"{name}" (would match anything)
                    patterns.append(re.compile("^" + "".join(
                        re.escape(value.value) if isinstance(value, ast.Constant) else r"\w+"
                        for value in node.values) + "$"))
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "startswith" and node.args and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str) and len(node.args[0].value) >= 5):
                patterns.append(re.compile("^" + re.escape(node.args[0].value)))
    return literals, patterns


def test_every_option_read_in_code():
    literals, patterns = code_references()
    unread = {
        name: keys for name, options in WIDGET_DEFAULT.items()
        if (keys := [key for key in options if key not in literals and not any(p.match(key) for p in patterns)])
    }
    assert not unread, f"options never read by overlay code (dead options shown on the page): {unread}"


# Number options at their limits --------------------------------------------------------------------------
def limit_tries(key: str, value: float) -> list[float]:
    from neopedal.ui.quick.option_kinds import number_range

    low, high = number_range(key)
    low = low if low > -1e8 else -UNLIMITED_TRY
    high = high if high < 1e8 else UNLIMITED_TRY
    tries = [low, high, 0] if low <= 0 <= high else [low, high]
    if isinstance(value, int):
        tries = [round(number) for number in tries]
    return [number for number in dict.fromkeys(tries) if number != value]


def draw(live_data, name: str, values: dict) -> tuple[int, int]:
    """Overlay made with values, updated & drawn (picture skipped if over size guard: cut when started)"""
    from neopedal.widget._base import limited_size
    from neopedal.widget._modern import create_widget

    setting = cfg.user.setting[name]
    saved = dict(setting)
    setting.clear()
    setting.update(values)
    widget = None
    try:
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        widget.adjustSize()
        event = QTimerEvent(0)
        for frame in range(2):
            drive(live_data, frame)
            widget.timerEvent(event)
        width, height = widget.width(), widget.height()
        if limited_size(width, height) is None:
            widget.grab()
        return width, height
    finally:
        if widget is not None:
            widget.deleteLater()
            QCoreApplication.processEvents()  # freed now (big pictures)
        setting.clear()
        setting.update(saved)


def number_keys(name: str, values: dict) -> list[str]:
    from neopedal.ui.quick.option_kinds import KIND_FLOAT, KIND_INTEGER, option_kind
    from neopedal.ui.quick.overlay_options_backend import build_layout

    return [key for key in build_layout(name, values).keys
            if key not in FIXED_OPTIONS and key in values and not isinstance(values[key], bool)
            and option_kind(key).kind in (KIND_INTEGER, KIND_FLOAT)]


def set_design(name: str, modern: bool) -> dict:
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    values = dict(cfg.user.setting[name])
    values["enable_classic_layout"] = not modern
    return values


@DESIGNS
@pytest.mark.parametrize("name", WIDGET_DISPLAY_ORDER)
def test_number_options_at_limits(live, name, modern):  # noqa: F811
    base = set_design(name, modern)
    failures = []
    for key in number_keys(name, base):
        for value in limit_tries(key, base[key]):
            print(f"{name} {key}={value!r}", file=sys.__stderr__, flush=True)  # last line before a crash
            try:
                draw(live, name, dict(base, **{key: value}))
            except Exception:  # every option, reported together
                failures.append(f"{key}={value!r}: {traceback.format_exc(limit=-2)}")
    assert not failures, "\n".join(failures)


# Page dependencies -------------------------------------------------------------------------------------
@DESIGNS
@pytest.mark.parametrize("name", WIDGET_DISPLAY_ORDER)
def test_dependencies_name_on_off_options(ui_env, name, modern):
    from neopedal.ui.quick.overlay_options_backend import build_layout

    values = set_design(name, modern)
    layout = build_layout(name, values)
    wrong = {key: parent for key, parent in layout.dependencies.items()  # (shared tables: options of others)
             if parent and key in values and (not isinstance(values.get(parent), bool) or parent == key)}
    toggles = {section.title: section.toggle for section in layout.sections
               if getattr(section, "toggle", "") and not isinstance(values.get(section.toggle), bool)}
    assert not wrong, f"dependencies on missing or not on/off options: {wrong}"
    assert not toggles, f"sections led by missing or not on/off options: {toggles}"


# Display orders ----------------------------------------------------------------------------------------
# Swaps not seen on the preview picture: both items blank or alike on simulated data, or not drawn there
SAME_ON_PREVIEW = {
    ("pedal", False): {"ffb", "clutch", "brake"},  # empty bars (no input on preview data)
    ("roll_angle", False): {"roll_angle_front", "roll_angle_rear"},  # same angle front & rear
    ("trailing", False): {  # traces on the same plot: order is which is drawn on top, apart on preview data
        "abs_activation", "tc_activation", "brake", "throttle", "wheel_slip", "wheel_lock", "clutch", "ffb",
        "steering", "speed", "slip_angle_difference"},
    ("black_box", False): {"laptime", "pit_limiter", "gear", "speed", "rpm"},  # limiter off, speed in gear block
}


def picture(name: str, values: dict) -> tuple[int, int, bytes]:
    from neopedal.ui.widget_preview import render_widget

    image = render_widget(cfg, name, values).toImage()
    return image.width(), image.height(), bytes(image.constBits())


@DESIGNS
def test_display_orders_move_items(ui_env, bundled_fonts, modern):
    """Every two shown items next to each other swapped: overlay picture changed (was: some orders ignored,
    or applied from the other design's values)"""
    from neopedal.ui.quick.overlay_options_backend import build_layout

    ignored = []
    for name in WIDGET_DISPLAY_ORDER:
        base = set_design(name, modern)
        orders = sorted((key for key in build_layout(name, base).keys
                         if key.startswith("display_order_") and key in base), key=lambda key: base[key])
        if len(orders) < 2:
            continue
        for key, value in base.items():  # every item shown
            if isinstance(value, bool) and key.startswith(("show_", "column_")):
                base[key] = True
        alike = SAME_ON_PREVIEW.get((name, modern), set())
        reference = picture(name, base)
        for first, second in itertools.pairwise(orders):
            if {first[14:], second[14:]} <= alike:
                continue
            swapped = dict(base, **{first: base[second], second: base[first]})
            if picture(name, swapped) == reference:
                ignored.append(f"{name}: {first} <-> {second}")
    assert not ignored, "display orders swapped, overlay unchanged:\n" + "\n".join(ignored)
