"""Audit lot C2: overlay data split from rendering (pure data functions shared by classic & modern widgets),
shared driver table columns (relative, standings, rivals), float options honoured by pens & shapes"""

import ast
from importlib import import_module
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.module_info import FuelInfo, WheelsInfo
from neopedal.setting import cfg
from neopedal.widget import _data
from neopedal.widget._modern import create_widget


@pytest.fixture
def widgets(ui_env, bundled_fonts):
    """Build widgets by name (classic unless modern=True), deleted after test"""
    created = []

    def make(name: str, modern: bool = False, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


# --- Pure data functions
def test_data_module_has_no_qt():
    """Data functions are pure: no Qt import (testable, usable by any renderer)"""
    with open(_data.__file__, encoding="utf-8") as file:
        tree = ast.parse(file.read())
    imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imported += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any("PySide6" in name or "Qt" in name for name in imported)


def test_run_laps():
    fuel = SimpleNamespace(estimatedLaps=12.0)
    assert _data.run_laps(fuel, SimpleNamespace(available=False, estimatedLaps=3.0)) == 12.0
    assert _data.run_laps(fuel, SimpleNamespace(available=True, estimatedLaps=3.0)) == 3.0
    assert _data.run_laps(fuel, SimpleNamespace(available=True, estimatedLaps=30.0)) == 12.0


def test_consumption_data():
    fuel = FuelInfo()
    fuel.amountCurrent = 50.0
    fuel.neededRelative = 20000.0
    fuel.neededAbsolute = 70.0
    fuel.estimatedLaps = 20000.0
    fuel.oneLessPitConsumption = -1.0
    fuel.estimatedNumPitStopsEnd = 120.0
    fuel.deltaConsumption = -0.2
    double = 2.0.__mul__
    data = _data.consumption_data(fuel, double, False)
    assert data.remaining == 100.0 and data.needed == 9999  # capped
    assert data.laps == 9999 and data.save == 0 and data.pits_end == 99.99 and data.delta == -0.4
    assert _data.consumption_data(fuel, double, True).needed == 140.0
    fuel.amountStart = 80.0
    assert _data.level_data(fuel) == (50.0, 80.0, 20050.0)  # source unit, not converted


def test_tyre_wear_data():
    wheels = WheelsInfo()
    wheels.currentTreadDepth = [80.0, 50.0, 0.0, 10.0]
    wheels.estimatedValidTreadWear = [2.0, 0.0, 1.0, 5.0]
    wheels.estimatedTreadWear = [2.1, 0.1, 1.1, 5.1]
    data = _data.tyre_wear_data(wheels, 0, 120.0, 10.0)
    assert data.remaining == 80.0 and data.wear == 2.1
    assert data.laps == 40.0 and data.minutes == 80.0 and data.end == 60.0
    assert _data.tyre_wear_data(wheels, 1, 120.0, 10.0).laps == 999  # no wear yet
    assert _data.wear_text(80.0) == "80.0" and _data.wear_text(1.234) == "1.23"


def test_brake_wear_data():
    wheels = WheelsInfo()
    wheels.maxBrakeThickness = [30.0, 0.0, 30.0, 30.0]
    wheels.failureBrakeThickness = [5.0, 0.0, 5.0, 5.0]
    wheels.currentBrakeThickness = [15.0, 10.0, 0.0, 3.0]
    wheels.estimatedBrakeWear = [0.5, 0.0, 0.0, 0.0]
    wheels.estimatedValidBrakeWear = [0.5, 0.0, 0.0, 0.0]
    millimeters = _data.brake_wear_data(wheels, 0, True, 100.0)
    assert millimeters.remaining == 10.0 and millimeters.remaining_percent == 40.0 and millimeters.usable == 25.0
    assert millimeters.wear == 0.5 and millimeters.wear_percent == 2.0 and millimeters.laps == 20.0
    percent = _data.brake_wear_data(wheels, 0, False, 100.0)
    assert percent.remaining == 40.0 and percent.wear == 2.0 and percent.laps == 20.0
    assert _data.brake_wear_data(wheels, 1, True, 100.0).usable == 99999999  # invalid thickness bypassed
    assert _data.brake_wear_data(wheels, 2, True, 100.0).failed
    worn = _data.brake_wear_data(wheels, 3, True, 100.0)
    assert not worn.failed and worn.remaining == 0.0  # past failure thickness: nothing left


def test_temperature_texts():
    assert _data.temperature_text(85, float, 2, "°", "-") == "85°"
    assert _data.temperature_text(5, float, 3, "", "-") == "005"
    assert _data.temperature_text(-200, float, 2, "", "n/a") == "n/a"
    assert _data.rate_text(-0.04, 1.0) == "0.0" and _data.rate_text(5.0, 1.8) == "9.0" and _data.rate_text(20, 1.0) == "20"


def test_temperature_rates():
    rates = _data.TemperatureRates(interval=1, samples=1)
    assert rates.update((80.0,) * 4, 10.0) == 0  # first reading: no rate (no spike from 0)
    assert rates.rates == [0.0] * 4
    assert rates.update((80.0,) * 4, 10.05) == 0  # under 0.1 s: skipped
    assert rates.update((82.0, 80.0, 78.0, 80.0), 11.0) == 1
    assert rates.rates[0] > 0 > rates.rates[2] and rates.rates[1] == 0.0
    assert rates.update((50.0,) * 4, 1.0) == 2  # new session: rates cleared
    assert rates.rates == [0.0] * 4 and rates.last_temps is None
    assert rates.update((50.0,) * 4, 2.0) == 0  # first reading of new session


def test_history_helpers():
    assert _data.used_amount(True, 3.5, 2.0, float, "L") == (3.5, "E")
    assert _data.used_amount(True, 3.5, 2.0, float, "") == (3.5, "")
    assert _data.used_amount(False, 3.5, 2.0, 2.0.__mul__, "G") == (4.0, "G")
    assert _data.lap_delta(91.0, 90.0) == 1.0
    assert _data.lap_delta(91.0, 0.0) is None and _data.lap_delta(-1.0, 90.0) is None
    assert _data.cut_number(1.23456, 4) == "1.23" and _data.cut_number(0.5, 4, "+") == "+0.5"


@pytest.mark.parametrize("modern", [False, True])
def test_wear_widgets_read_shared_data(widgets, monkeypatch, modern):
    """Classic & modern tyre wear show values of the same data function"""
    from neopedal.module_info import minfo

    monkeypatch.setattr(minfo.wheels, "currentTreadDepth", [80.0, 70.0, 60.0, 50.0])
    monkeypatch.setattr(minfo.wheels, "estimatedValidTreadWear", [2.0, 2.0, 2.0, 2.0])
    widget = widgets("tyre_wear", modern=modern, show_remaining=True, show_lifespan_laps=True)
    widget.timerEvent(None)
    if modern:
        texts = [tile.texts[0] for section in widget.state for tile in section]
        assert "80.0" in texts and "40.0" in texts
    else:
        assert widget.bars_remain[0].text == "80.0" and widget.bars_laps[0].text == "40.0"


# --- Driver tables: shared columns
@pytest.mark.parametrize("name", ["relative", "standings", "rivals"])
def test_driver_table_every_column(widgets, name):
    """Every column built from the shared table (rivals: no player colors, no fastest lap colors)"""
    from neopedal.widget._columns import COLUMNS

    options = {key: True for key, value in cfg.default.setting[name].items()
               if key.startswith("show_") and isinstance(value, bool)}
    widget = widgets(name, **options)
    widget.timerEvent(None)
    for column_name, column in COLUMNS.items():
        if column.show in options:
            assert len(getattr(widget, f"bars_{column_name}")) == widget.veh_range
    if name == "rivals":
        assert widget.bar_style_psc[1] == widget.bar_style_psc[0]  # player style: default style


def test_relative_empty_row_blank_not_hidden(widgets):
    """Relative: empty rows keep cells (background), text cleared"""
    widget = widgets("relative", show_position=True, show_driver_name=True, show_tyre_compound=True)
    target = widget.bars_drv[0]
    widget.update_drv(target, "Driver", 0, 1)
    assert target.text.strip() == "Driver"
    widget.update_drv(target, "Driver", 0, 0)
    assert target.text == "" and not target.isHidden()
    compounds = widget.bars_tcp[0]
    widget.update_tcp(compounds, ("S", "S", "S", "S"), False, 0)
    assert all(text == "" for text in compounds.compounds)


def test_standings_and_rivals_hide_empty_rows(widgets):
    standings = widgets("standings", show_driver_name=True, split_gap=3)
    standings.show()
    target = standings.bars_drv[0]
    standings.update_drv(target, "Driver", False, 2)
    assert target.isHidden()
    standings.update_drv(target, "Driver", False, 1)  # class gap row
    assert not target.isHidden() and target.height() == 3
    standings.update_drv(target, "Other", False, 0)
    assert not target.isHidden() and target.text.strip() == "Other"
    rivals = widgets("rivals", show_driver_name=True)
    rivals.show()
    rivals.update_drv(rivals.bars_drv[0], "Driver", False, 0)
    assert rivals.bars_drv[0].isHidden()
    rivals.update_drv(rivals.bars_drv[0], "Driver", False, 1)
    assert not rivals.bars_drv[0].isHidden()


# --- Float options honoured (no int truncation)
@pytest.mark.parametrize(("name", "options", "pen", "width"), [
    ("friction_circle", {"trace_width": 1.5}, "pen_trace", 1.5),
    ("damage", {"puncture_outline_width": 2.5}, "pen_puncture", 2.5),
    ("rpm_led", {"led_outline_width": 0.5}, "pen_led", 0.5),
    ("heading", {"yaw_line_width": 1.5}, "pen_yaw", 1.5),
    ("steering_wheel", {"rotation_line_width": 2.5}, "pen_rotation", 2.5),
    ("elevation", {"position_mark_width": 0.5}, "pen_mark", 0.5),
])
def test_pen_width_decimals_kept(widgets, name, options, pen, width):
    widget = widgets(name, **options)
    assert getattr(widget, pen).widthF() == width


def test_default_pen_widths_whole(widgets):
    """Default (integer) widths draw as before"""
    widget = widgets("friction_circle")
    assert widget.pen_trace.widthF() == cfg.default.setting["friction_circle"]["trace_width"]


def test_dot_pixmap_size_rounded(widgets):
    widget = widgets("heading", dot_size=5.75)
    assert widget.pixmap_dot.width() == 12  # round(11.5), whole pixels
    widget = widgets("friction_circle", dot_size=6)
    assert widget.pixmap_dot.width() == 12
