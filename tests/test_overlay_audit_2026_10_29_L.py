"""Overlay audit 2026-10-29, group L: friction circle, slip angle, slip ratio, tyre deflection, wheel camber,
wheel dimension & wheel toe (findings 86-98, 109, 110)"""

import os
import re
from importlib import import_module

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QRegion
from PySide6.QtWidgets import QWidget

from neopedal.api_control import api
from neopedal.module_info import ModuleInfo, minfo
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "customization.md")


@pytest.fixture
def make(ui_env, bundled_fonts):
    """Overlay of modern or classic design"""
    created = []

    def build(name: str, modern: bool, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield build
    for widget in created:
        widget.deleteLater()


def doc_section(title: str) -> str:
    with open(DOCS, encoding="utf-8") as file:
        text = file.read()
    return text.split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


def snapshot(widget) -> QImage:
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.black)
    widget.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return image


# --- Wheel toe: help of real option name (finding 94, P17), toe includes steering (finding 95)
def test_wheel_toe_doc_documents_real_option_names():
    section = doc_section("Wheel toe")
    options = set(re.findall(r"^    (\w+(?:, \w+)*)$", section, re.MULTILINE))
    documented = {name for line in options for name in line.split(", ")}
    assert "toe_angle_smoothing_samples" in documented and "toe_in_smoothing_samples" not in documented
    assert "steering" in section
    from neopedal.template.widget.tyres import WIDGET_TYRES

    assert documented <= set(WIDGET_TYRES["wheel_toe"])  # no help under a name that does not exist


# --- Friction circle classic: trace fades inside buffer as modern design, nothing drawn per tick (86, 87, V29)
def classic_circle(make, **options):
    return make(
        "friction_circle", False, show_dot=False, show_readings=False, show_reference_circle=False,
        show_center_mark=False, show_maximum_average_lateral_g_circle=False, show_circle_background=False,
        show_background=False, trace_color="#FFFF0000", trace_maximum_samples=60, **options)


def trace_red(widget, old: QPointF, new: QPointF) -> tuple[int, int]:
    """Red level of oldest & newest trace samples (old half on top line, new half on bottom line)"""
    widget.data_gforce.clear()
    for index in range(30):
        widget.data_gforce.append(QPointF(old.x() + index, old.y()))
    for index in range(30):
        widget.data_gforce.append(QPointF(new.x() + index, new.y()))
    image = snapshot(widget)
    return QColor(image.pixel(int(old.x()) + 2, int(old.y()))).red(), QColor(image.pixel(int(new.x()) + 25, int(new.y()))).red()


def test_classic_friction_trace_fades_inside_buffer(make):
    widget = classic_circle(make, show_trace_fade_out=True, trace_fade_out_step=0.2)
    oldest, newest = trace_red(widget, QPointF(10, 20), QPointF(10, widget.height() - 20))
    assert newest > 200 and 0 < oldest < newest * 0.4  # oldest part about 1/6 opaque, as modern design
    from neopedal.widget._modern.friction_circle import TRACE_PARTS, trace_alpha

    assert [color.alpha() for color in widget.trace_colors] == [trace_alpha(index, 0.2) for index in range(TRACE_PARTS)]


def test_classic_friction_trace_without_fade_out_is_even(make):
    widget = classic_circle(make, show_trace_fade_out=False)
    oldest, newest = trace_red(widget, QPointF(10, 20), QPointF(10, widget.height() - 20))
    assert len(widget.trace_colors) == 1 and oldest == newest > 200


def test_classic_friction_trace_point_style(make):
    widget = classic_circle(make, show_trace_fade_out=True, trace_style=1, trace_width=4)
    oldest, newest = trace_red(widget, QPointF(10, 20), QPointF(10, widget.height() - 20))
    assert newest > 200 and oldest < newest


def test_classic_friction_tick_only_stores_sample(make, monkeypatch):
    widget = classic_circle(make)
    assert not hasattr(widget, "pixmap_trace")  # no image faded & redrawn on every tick
    monkeypatch.setattr(minfo.force, "lgtGForceRaw", 1.2)
    monkeypatch.setattr(minfo.force, "latGForceRaw", -0.8)
    widget.timerEvent(None)
    assert len(widget.data_gforce) == 1
    widget.vehicle_reset()  # other car followed or session changed: no line from previous car
    assert not widget.data_gforce


def test_modern_friction_trace_cleared_on_vehicle_reset(make):
    widget = make("friction_circle", True)
    widget.trace.append(QPointF(1, 1))
    widget.vehicle_reset()
    assert not widget.trace


# --- Friction circle: modern readings documented (finding 89)
def test_friction_circle_doc_describes_modern_readings():
    section = doc_section("Friction circle")
    line = section.split("    show_readings\n", 1)[1].split("\n", 1)[0]
    assert "Modern design" in line


# --- Demo data as modules give them (findings 90, 98)
def test_demo_data_consistent_with_modules():
    from neopedal.demo_data import set_modules

    info = ModuleInfo()
    set_modules(info)
    wheels = info.wheels
    assert info.force.maxLgtGForce >= 0  # module gives absolute maximum
    assert wheels.frontToeAngleDifference == pytest.approx(wheels.toeAngle[0] - wheels.toeAngle[1])
    assert wheels.rearToeAngleDifference == pytest.approx(wheels.toeAngle[2] - wheels.toeAngle[3])
    front = abs(wheels.averageFrontSlipAngle)
    rear = abs(wheels.averageRearSlipAngle)
    assert wheels.slipAngleDifference == pytest.approx(front - rear, abs=0.01)


# --- Slip angle: threshold documented (finding 91)
def test_slip_angle_threshold_documented():
    section = doc_section("Slip angle")
    assert "minus average rear slip angle" in section and "`1.5`" in section


# --- Gauge bars repaint on visible change only (finding 109)
@pytest.mark.parametrize("name, group, reading, small, large", [
    ("slip_angle", "slipAngle", 3.21, 3.212, 3.4),
    ("slip_ratio", "slipRatio", 0.101, 0.1011, 0.2),
])
def test_classic_wheel_bars_repaint_on_visible_change(make, monkeypatch, name, group, reading, small, large):
    widget = make(name, False)
    bars = getattr(widget, f"bars_{name}")
    calls = []
    monkeypatch.setattr(bars[0], "update_input", lambda value: calls.append(value))
    monkeypatch.setattr(minfo.wheels, group, [reading] * 4)
    widget.timerEvent(None)
    monkeypatch.setattr(minfo.wheels, group, [small] * 4)  # same text, same bar length in pixels
    widget.timerEvent(None)
    assert len(calls) == 1
    monkeypatch.setattr(minfo.wheels, group, [large] * 4)
    widget.timerEvent(None)
    assert len(calls) == 2


def test_classic_slip_angle_color_change_repaints(make, monkeypatch):
    widget = make("slip_angle", False)
    monkeypatch.setattr(minfo.wheels, "slipAngle", [3.0] * 4)
    monkeypatch.setattr(minfo.wheels, "slipAngleDifference", 0.0)
    widget.timerEvent(None)
    monkeypatch.setattr(minfo.wheels, "slipAngleDifference", 5.0)  # understeer, same slip angles
    widget.timerEvent(None)
    assert widget.bars_slip_angle[0].input_color == widget.wcfg["understeer_slip_angle_color"]


def test_classic_tyre_deflection_repaints_on_visible_change(make, monkeypatch):
    widget = make("tyre_deflection", False, decimal_places=1)
    bar = widget.bars_deflect[0]
    calls = []
    monkeypatch.setattr(bar, "update_input", lambda value: calls.append(value))
    readings = iter(((20.01,) * 4, (20.02,) * 4, (0.0,) * 4))
    monkeypatch.setattr(api.read.tyre, "vertical_deflection", lambda *args: next(readings))
    for _ in range(3):
        widget.timerEvent(None)
    assert len(calls) == 2 and bar.bg_color == widget.wcfg["warning_color_lift_off"]


# --- Wheel camber & toe: no "-0.0", rounded not truncated, repaint on visible change (92, 96, 97, 109, 110)
def wheel_angles(monkeypatch, toe=(0.0,) * 4, camber=(0.0,) * 4, toe_diff=(0.0, 0.0), camber_diff=(0.0, 0.0)):
    wheels = minfo.wheels
    monkeypatch.setattr(wheels, "toeAngle", list(toe))
    monkeypatch.setattr(wheels, "camberAngle", list(camber))
    monkeypatch.setattr(wheels, "frontToeAngleDifference", toe_diff[0])
    monkeypatch.setattr(wheels, "rearToeAngleDifference", toe_diff[1])
    monkeypatch.setattr(wheels, "frontCamberAngleDifference", camber_diff[0])
    monkeypatch.setattr(wheels, "rearCamberAngleDifference", camber_diff[1])


SMOOTHING_OFF = {"toe_angle_smoothing_samples": 1, "total_toe_angle_smoothing_samples": 1}
CAMBER_SMOOTHING_OFF = {"camber_smoothing_samples": 1, "camber_difference_smoothing_samples": 1}


def test_classic_toe_rounded_no_negative_zero(make, monkeypatch):
    widget = make("wheel_toe", False, enable_symmetric_toe_angle=False, **SMOOTHING_OFF)
    wheel_angles(monkeypatch, toe=(0.178, -0.001, 0.0, -0.004), toe_diff=(0.178, -0.003))
    widget.timerEvent(None)
    assert [bar.text for bar in widget.bars_toe] == ["+0.18", "+0.00", "+0.00", "+0.00"]
    assert [bar.text for bar in widget.bars_total] == ["0.18", "0.00"]
    negative, positive = widget.bar_style_total
    assert widget.bars_total[0].fg == positive and widget.bars_total[1].fg == negative  # shown sign
    wheel_angles(monkeypatch, toe=(0.178, -0.001, 0.0, -0.004), toe_diff=(0.178, 0.003))
    widget.timerEvent(None)
    assert widget.bars_total[1].fg == negative  # "0.00" both ways: color does not flicker


def test_classic_toe_zero_reading_replaces_na(make, monkeypatch):
    widget = make("wheel_toe", False, **SMOOTHING_OFF)
    wheel_angles(monkeypatch)
    widget.timerEvent(None)
    assert widget.bars_toe[0].text == "+0.00" and widget.bars_total[0].text == "0.00"


def test_classic_toe_repaint_on_visible_change(make, monkeypatch):
    widget = make("wheel_toe", False, **SMOOTHING_OFF)
    bar = widget.bars_toe[0]
    calls = []
    monkeypatch.setattr(bar, "update", lambda: calls.append(bar.text))
    wheel_angles(monkeypatch, toe=(0.101,) * 4)
    widget.timerEvent(None)
    wheel_angles(monkeypatch, toe=(0.102,) * 4)
    widget.timerEvent(None)
    assert calls == ["+0.10"]


def test_classic_camber_no_negative_zero(make, monkeypatch):
    widget = make("wheel_camber", False, **CAMBER_SMOOTHING_OFF)
    wheel_angles(monkeypatch, camber=(-2.5, -0.001, -3.0, -3.0), camber_diff=(-0.01, 0.02))
    widget.timerEvent(None)
    assert widget.bars_camber[1].text == "+0.00"
    assert widget.bars_camber[1].fg == widget.wcfg["font_color_positive_camber"]  # shown as 0: threshold 0
    assert [bar.text for bar in widget.bars_cdiff] == ["+0.0", "+0.0"]


@pytest.mark.parametrize("name, options", [("wheel_toe", SMOOTHING_OFF), ("wheel_camber", CAMBER_SMOOTHING_OFF)])
def test_modern_wheel_angles_no_negative_zero(make, monkeypatch, name, options):
    widget = make(name, True, **options)
    wheel_angles(monkeypatch, toe=(-0.001,) * 4, camber=(-0.001,) * 4, toe_diff=(-0.001, 0.001),
                 camber_diff=(-0.01, 0.01))
    widget.timerEvent(None)
    tiles, centers = widget.state[0], widget.state[1]
    assert all(not tile.texts[0].startswith("-") for tile in tiles)
    assert all(not text.startswith("-") for text in centers)
    if name == "wheel_toe":
        colors = widget.state[2]
        assert colors[0] == colors[1]  # both shown as 0.00: same color


# --- Wheel dimension classic: axle label (finding 93)
def test_classic_wheel_dimension_axle_labels(make, monkeypatch):
    monkeypatch.setattr(minfo.wheels, "wheelRadiusFront", 337.6)
    monkeypatch.setattr(minfo.wheels, "wheelRadiusRear", 351.2)
    widget = make("wheel_dimension", False)
    widget.timerEvent(None)
    texts = [bar.text for bar, *_ in widget.bars_radius]
    assert texts == ["F 338mm", "R 351mm"]
    metrics = widget.bars_radius[0][0].fontMetrics()
    assert all(bar.width() >= metrics.horizontalAdvance(bar.text) for bar, *_ in widget.bars_radius)
