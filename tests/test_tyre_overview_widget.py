"""Tyre overview overlay: one card per tyre with compound & alert, temperatures, pressure against target, wear"""

from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.api_control import api
from neopedal.module_info import minfo
from neopedal.setting import cfg
from neopedal.widget import tyre_overview
from neopedal.widget._modern import create_widget
from neopedal.widget.tyre_overview import (
    DASH,
    PRESSURE_HIGH,
    PRESSURE_LOW,
    PRESSURE_OK,
    TyreOverviewMixin,
    pressure_state,
    tyre_alert,
)


@pytest.fixture
def make(ui_env, bundled_fonts, monkeypatch):
    """Widget on readings of a car in pits on medium tyres, front left punctured"""
    tyre = api.read.tyre
    monkeypatch.setattr(tyre, "surface_temperature_ico", lambda *args: (80, 85, 90, 91, 86, 81, 70, 72, 74, 75, 73, 71))
    monkeypatch.setattr(tyre, "surface_temperature_avg", lambda *args: (85, 86, 72, 73))
    monkeypatch.setattr(tyre, "carcass_temperature", lambda *args: (92.4, 93.0, 80.0, 81.0))
    monkeypatch.setattr(tyre, "inner_temperature_avg", lambda *args: (95.0, 96.0, 82.0, 83.0))
    monkeypatch.setattr(tyre, "pressure", lambda *args: (150.0, 175.0, 200.0, 0.0))
    monkeypatch.setattr(tyre, "compound_class", lambda *args: ("Medium",) * 4)
    monkeypatch.setattr(tyre, "flat", lambda *args: (True, False, False, False))
    monkeypatch.setattr(tyre, "puncture", lambda *args: (False,) * 4)
    monkeypatch.setattr(api.read.wheel, "is_detached", lambda *args: (False,) * 4)
    monkeypatch.setattr(api.read.vehicle, "in_pits", lambda *args: True)
    wheels = minfo.wheels
    for name, value in (("currentTreadDepth", [86.0, 25.0, 90.0, 91.0]), ("estimatedValidTreadWear", [2.0, 5.0, 0.0, 0.01]),
                        ("lockingTreadWear", [0.0, 0.0, 1.5, 0.0])):
        monkeypatch.setattr(wheels, name, value)
    created = []

    def build(modern: bool, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting["tyre_overview"].update(options)
        widget = create_widget(import_module("neopedal.widget.tyre_overview"), cfg, "tyre_overview")
        created.append(widget)
        return widget

    yield build
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def test_pressure_against_target_and_alerts():
    target = (160.0, 190.0)
    assert [pressure_state(value, target) for value in (150, 175, 200, 0)] == [
        PRESSURE_LOW, PRESSURE_OK, PRESSURE_HIGH, PRESSURE_OK]  # no reading: no color
    assert pressure_state(150, (0.0, 0.0)) == PRESSURE_OK  # no range
    assert tyre_alert(True, True, 5.0, 1.0) == "detached"  # most important first
    assert tyre_alert(False, True, 5.0, 1.0) == "puncture"
    assert tyre_alert(False, False, 1.0, 1.0) == "flat"
    assert tyre_alert(False, False, 5.0, 0.0) == ""  # flat spots off


def test_texts():
    assert [TyreOverviewMixin.laps_text(value) for value in (-1.0, 3.25, 12.4, 150.0)] == [DASH, "3.2", "12", "99+"]
    assert TyreOverviewMixin.wear_text(0.0) == DASH and TyreOverviewMixin.wear_text(1.234) == "1.23"
    assert TyreOverviewMixin.remaining_text(86.4) == "86%"


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_cards(make, modern):
    widget = make(modern)
    widget.timerEvent(None)
    front_left, front_right, rear_left, rear_right = widget.state
    assert front_left.alert == "puncture" and rear_left.alert == "flat" and not front_right.alert
    assert front_left.compound == "M" and front_left.compound_color is not None
    assert front_left.temps == (80, 85, 90) and rear_right.temps == (75, 73, 71)  # inner, center, outer
    assert (front_left.carcass, front_left.inner) == (92, 95)
    assert [card.pressure_state for card in widget.state] == [PRESSURE_LOW, PRESSURE_OK, PRESSURE_HIGH, PRESSURE_OK]
    assert front_right.remaining == 25.0 and front_right.laps == 5.0  # 25 % left at 5 % per lap
    assert rear_left.laps == -1.0  # no valid lap yet
    widget.grab()


def test_parts_turned_off(make):
    full_height = make(True).height()
    widget = make(True, show_inner_center_outer=False, show_carcass_temperature=False,
                  show_inner_layer_temperature=False, show_wear=False, show_wear_per_lap=False,
                  show_lifespan_laps=False, show_tyre_alerts=False)
    assert widget.height() < full_height
    widget.timerEvent(None)
    assert widget.state[0].temps == (85,) and not widget.state[0].alert
    assert set(widget.rows[0]) == {"header", "pressure", "range"}  # temperatures drawn on the tyre
    widget.grab()


def test_pressure_target_by_compound_and_rear(make):
    widget = make(True, tyre_target_by_compound="M=140-160; M:R=190-210", tyre_pressure_target_rear_minimum=0.0)
    widget.timerEvent(None)
    states = [card.pressure_state for card in widget.state]
    assert states == [PRESSURE_OK, PRESSURE_HIGH, PRESSURE_OK, PRESSURE_OK]  # front 140-160, rear 190-210
    psi = make(True, tyre_target_by_compound="", tyre_pressure_target_minimum=23.2,
               tyre_pressure_target_maximum=27.6)  # entered in psi: 160 - 190 kPa
    psi.timerEvent(None)
    assert psi.state[0].pressure_state == PRESSURE_LOW


def test_modules_needed_for_wear():
    from neopedal.module_control import overlay_fields

    assert "wheels" in overlay_fields("tyre_overview")  # wheels module (tread wear) started with the overlay


def test_french_labels(make):
    from neopedal.i18n import set_language
    from neopedal.i18n.options import module_label

    set_language("Français")
    try:
        assert module_label("tyre_overview") == "Pneus (vue d'ensemble)"
        widget = make(True)
        assert widget.labels == ("AVG", "AVD", "ARG", "ARD") and widget.alert_labels["puncture"] == "Crevaison"
    finally:
        set_language("English")
    assert tyre_overview.ALERTS["flat"] == "Flat spot"


PARTS = ("show_car_body", "show_wheel_label", "show_alert_highlight", "show_tyre_graphic", "show_tread_grooves",
         "show_layer_labels", "show_pressure_unit", "show_pressure_target_range", "show_tread_gauge")


@pytest.mark.parametrize("part", PARTS)
def test_every_part_switchable(make, part):
    def drawn(**options):
        widget = make(True, **{**dict.fromkeys(PARTS, True), "tyre_target_by_compound": "", **options})
        widget.timerEvent(None)
        return widget.grab().toImage()

    assert drawn() != drawn(**{part: False})


def test_temperatures_in_row_without_tyre_drawing(make):
    widget = make(True, show_tyre_graphic=False, show_tread_gauge=False)
    widget.timerEvent(None)
    assert not widget.tyres[0].isValid() and not widget.gauges[0].isValid()
    assert list(widget.rows[0]) == ["header", "surface", "pressure", "range", "layers", "wear"]
    assert widget.need_wear  # tread left still shown as text
    widget.grab()


def test_classic_caption_and_pressure_unit_switchable(make):
    full = make(False)
    assert full.rows[0] == "caption"
    widget = make(False, show_wheel_label=False, show_tyre_compound=False, show_tyre_alerts=False,
                  show_pressure_unit=False)
    assert "caption" not in widget.rows and widget.height() < full.height()
    widget.timerEvent(None)
    widget.grab()
