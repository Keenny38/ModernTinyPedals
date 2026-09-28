"""Wheel status widget tests"""

from types import SimpleNamespace

import pytest

# Safe at module level: conftest builds the QApplication before collection
from tinypedal.widget import _painter as painter_mod
from tinypedal.widget import _wheel_state as wheel_state
from tinypedal.widget import wheel_status


@pytest.fixture
def widget(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.module_info import minfo
    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    fake = SimpleNamespace(
        tyre=SimpleNamespace(
            surface_temperature_avg=lambda: (80.0, 81.0, 82.0, 83.0),
            pressure=lambda: (170.0, 171.0, 172.0, 173.0),
            wear=lambda: (0.9, 0.8, 0.5, 0.2),
            surface_temperature_ico=lambda: (70.0, 80.0, 90.0) * 4,
            puncture=lambda: (False, False, False, True),
            compound_class=lambda: ("", "", "", ""),
        ),
        brake=SimpleNamespace(temperature=lambda: (400.0, 410.0, 300.0, 310.0), bias_front=lambda: 0.56),
        vehicle=SimpleNamespace(
            speed=lambda: 30.0, in_pits=lambda: False, vehicle_name=lambda: "car",
            class_name=lambda: "GT3",
            damage_severity=lambda: (0, 1, 0, 0, 3, 0, 0, 0),
        ),
        wheel=SimpleNamespace(
            is_detached=lambda: (False, True, False, False), suspension_damage=lambda: (0.0, 0.0, 0.6, 0.0),
        ),
        inputs=SimpleNamespace(brake_raw=lambda: 0.9, throttle=lambda: 0.0, brake=lambda: 0.9),
        engine=SimpleNamespace(gear=lambda: -1, rpm=lambda: 6000.0, rpm_max=lambda: 8000.0),
        switch=SimpleNamespace(
            abs_active=lambda: True, tc_active=lambda: False, abs_level=lambda: 4, tc_level=lambda: -1,
            tc_cut_level=lambda: -1, tc_slip_level=lambda: -1, speed_limiter=lambda: 1,
        ),
    )
    monkeypatch.setattr(api, "read", fake)
    monkeypatch.setattr(minfo.wheels, "slipRatio", [-0.4, 0.0, 0.0, 0.0])
    cfg.user.setting["wheel_status"]["enable_heatmap_auto_matching"] = False
    instance = wheel_status.Realtime(cfg, "wheel_status")
    yield instance
    instance.deleteLater()


def test_update_state(widget):
    widget.timerEvent(None)
    assert widget.abs_active and not widget.tc_active
    assert widget.abs_level == 4
    assert widget.wheels[0].warning == "lock"  # braking with -40% slip
    assert widget.wheels[1].warning == ""
    assert widget.wheels[0].tyre_color.startswith("#")
    assert widget.format_temp(-273) == "-"


def test_spin_warning(widget):
    assert widget.slip_warning(0.5, 30.0, braking=False) == "spin"
    assert widget.slip_warning(-0.5, 30.0, braking=False) == ""  # no lock without braking
    assert widget.slip_warning(-0.5, 1.0, braking=True) == ""  # too slow


def test_paint(widget):
    widget.timerEvent(None)
    image = widget.grab().toImage()
    assert image.width() > 100 and image.height() > 50


def test_abs_tc_shown_only_if_car_has_them(widget, monkeypatch):
    from tinypedal.api_control import api

    widget.timerEvent(None)
    assert widget.has_abs  # level 4 reported
    assert not widget.has_tc  # level -1 and never active: car without TC
    # rF2: no level reported, detected once active
    monkeypatch.setattr(api.read.switch, "tc_active", lambda: True)
    widget.timerEvent(None)
    assert widget.has_tc
    # Different car: detect again
    monkeypatch.setattr(api.read.switch, "tc_active", lambda: False)
    monkeypatch.setattr(api.read.vehicle, "vehicle_name", lambda: "other car")
    widget.timerEvent(None)
    assert not widget.has_tc


def test_tyres_turn_with_wheel_angle(widget, monkeypatch):
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.wheels, "toeAngle", [-10.0, 8.0, 0.5, 40.0])
    widget.timerEvent(None)
    assert widget.wheels[0].steer == pytest.approx(-20.0)  # left, x2 multiplier
    assert widget.wheels[1].steer == pytest.approx(16.0)  # right
    assert widget.wheels[3].steer == pytest.approx(30.0)  # limited to maximum
    widget.grab()  # draws turned tyres


def test_tc_text_with_cut_and_slip(widget):
    assert wheel_state.level_text("TC", 5, 3, 2) == "TC 5/3/2"
    assert wheel_state.level_text("TC", 5, -1, 2) == "TC 5/2"  # cut not available
    assert wheel_state.level_text("TC", 5, -1, -1) == "TC 5"
    assert wheel_state.level_text("TC", -1, -1, -1) == "TC"
    assert wheel_state.level_text("ABS", 3) == "ABS 3"


def test_tyre_wear(widget):
    widget.timerEvent(None)
    assert [round(wheel.tread) for wheel in widget.wheels] == [90, 80, 50, 20]
    widget.grab()  # draws wear, 20% highlighted (below 30% threshold)


def test_driving_info(widget, monkeypatch):
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.fuel, "neededRelative", 12.34)
    monkeypatch.setattr(minfo.energy, "neededRelative", 8.5)
    monkeypatch.setattr(minfo.energy, "available", False)
    widget.timerEvent(None)
    assert widget.gear_text() == "R"
    assert widget.rpm == 6000.0 and widget.speed == 30.0
    assert widget.refuel == 12.34 and not widget.energy_available  # refill hidden without virtual energy
    widget.gear = 0
    assert widget.gear_text() == "N"
    widget.grab()


def test_text_sizes_and_fit(ui_env):
    from PySide6.QtGui import QPainter, QPixmap

    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    cfg.user.setting["wheel_status"].update(font_scale_gear=3.0, font_scale_speed=1.5, font_scale_rpm=1.0)
    large = wheel_status.Realtime(cfg, "wheel_status")
    cfg.user.setting["wheel_status"].update(font_scale_gear=1.0, font_scale_speed=0.8, font_scale_rpm=0.5)
    small = wheel_status.Realtime(cfg, "wheel_status")
    assert large.font_gear.pixelSize() > small.font_gear.pixelSize()
    assert large.height() > small.height()  # widget adapts to text sizes
    pixmap = QPixmap(10, 10)
    painter = QPainter(pixmap)
    fitted = painter_mod.fit_font(painter, large.font_gear, "TC 10/10/10", 20, 100)
    assert fitted.pixelSize() < large.font_gear.pixelSize()  # reduced to fit width
    painter.end()
    large.deleteLater()
    small.deleteLater()


def test_tyre_status_and_damage(widget):
    widget.timerEvent(None)
    assert widget.wheels[1].status == "detached"
    assert widget.wheels[3].status == "puncture"
    assert widget.wheels[2].suspension_damage == 0.6
    assert widget.body_damage[4] == 3
    assert widget.limiter
    widget.grab()


def test_temperature_bands_order(widget):
    widget.heatmap_tyre = [((0.0, ("", "#A")), (75.0, ("", "#B")), (85.0, ("", "#C")))] * 4
    left = widget.band_colors(0, (70.0, 80.0, 90.0))  # inner, center, outer
    right = widget.band_colors(1, (70.0, 80.0, 90.0))
    assert left == ("#C", "#B", "#A")  # left wheel: outer on left side
    assert right == ("#A", "#B", "#C")  # right wheel: inner on left side


def test_pressure_target(widget):
    assert widget.pressure_color(150) == widget.wcfg["tyre_pressure_low_color"]
    assert widget.pressure_color(175) == ""
    assert widget.pressure_color(200) == widget.wcfg["tyre_pressure_high_color"]


def test_gear_color_and_leds(widget):
    widget.rpm_max = 8000
    widget.rpm = 5000
    assert widget.gear_color() == widget.wcfg["gear_color_low"]
    widget.rpm = 7000
    assert widget.gear_color() == widget.wcfg["gear_color_mid"]
    widget.rpm = 7900
    assert widget.gear_color() in (widget.wcfg["gear_color_shift"], widget.wcfg["font_color_gear"])  # flashing
    widget.grab()


def test_display_order_and_layouts(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    cfg.user.setting["wheel_status"].update(display_order_gear=0, display_order_abs=99)
    widget = wheel_status.Realtime(cfg, "wheel_status")
    assert widget.center_order[0] == "gear" and widget.center_order[-1] == "abs"
    sizes = {}
    for layout in (0, 1, 2):
        cfg.user.setting["wheel_status"]["layout"] = layout
        instance = wheel_status.Realtime(cfg, "wheel_status")
        sizes[layout] = (instance.width(), instance.height())
        instance.deleteLater()
    assert sizes[1][1] > sizes[0][1]  # vertical: taller
    assert sizes[2][0] < sizes[0][0]  # compact: narrower
    widget.deleteLater()


def test_pit_limiter_only_when_active(widget, monkeypatch):
    from PySide6.QtCore import QRectF

    drawn = []
    monkeypatch.setattr(widget, "draw_indicator", lambda painter, rect, text, active, color: drawn.append(text))
    widget.timerEvent(None)  # limiter on, not in pit
    widget.draw_center_item(None, "pit_limiter", QRectF(0, 0, 100, 20))
    assert drawn == ["LIM"]
    widget.limiter = False
    drawn.clear()
    widget.grab()
    assert "PIT" not in drawn and "LIM" not in drawn


# --- Fixed bugs (regression)
def test_last_rpm_led_is_reachable(widget):
    """Top LED must light before redline, where all LEDs switch to shift colour"""
    wcfg = widget.wcfg
    count = min(max(int(wcfg["number_of_rpm_leds"]), 3), 20)
    start = min(max(wcfg["rpm_led_start_ratio"], 0), 0.95)
    redline = max(wcfg["rpm_redline_ratio"], start + 0.01)
    thresholds = [start + led / count * (redline - start) for led in range(count)]
    assert max(thresholds) < redline, "top LED never lights in progressive mode"
    assert thresholds[0] >= start  # first LED not lit below start ratio
    assert thresholds == sorted(thresholds)


def test_end_stint_tread_hidden_while_unknown(widget, monkeypatch):
    """Without Wheels & Fuel module data, no estimate is shown (used to display "0%")"""
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.wheels, "currentTreadDepth", [0.0] * 4)
    monkeypatch.setattr(minfo.fuel, "estimatedLaps", 0.0)
    widget.timerEvent(None)
    assert not any(wheel.tread_end_known for wheel in widget.wheels)
    # With data, estimate is known and computed
    monkeypatch.setattr(minfo.wheels, "currentTreadDepth", [90.0] * 4)
    monkeypatch.setattr(minfo.wheels, "estimatedValidTreadWear", [2.0] * 4)
    monkeypatch.setattr(minfo.fuel, "estimatedLaps", 10.0)
    monkeypatch.setattr(minfo.energy, "available", False)
    widget.timerEvent(None)
    assert all(wheel.tread_end_known for wheel in widget.wheels)
    assert widget.wheels[0].tread_end == pytest.approx(70.0)  # 90 - 2 * 10
    widget.grab()


def test_display_scale_is_clamped(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    cfg.user.setting["wheel_status"]["display_scale"] = 100.0
    huge = wheel_status.Realtime(cfg, "wheel_status")
    cfg.user.setting["wheel_status"]["display_scale"] = 4.0
    limit = wheel_status.Realtime(cfg, "wheel_status")
    assert (huge.width(), huge.height()) == (limit.width(), limit.height())  # clamped to 4
    huge.deleteLater()
    limit.deleteLater()


def test_pressure_warning_has_own_color(widget):
    """Pressure pill must not depend on the tyre wear warning colour"""
    assert "tyre_pressure_warning_background_color" in widget.wcfg
    assert widget.wcfg["tyre_pressure_warning_background_color"] != widget.wcfg["font_color_tyre_wear_warning"]
    widget.wcfg["show_tyre_pressure"] = True
    widget.wcfg["tyre_wear_warning_color"] = "#123456"
    widget.timerEvent(None)
    widget.grab()  # pressure out of range draws its own pill colour


# --- New features
def test_brake_wear(widget, monkeypatch):
    from tinypedal.module_info import minfo

    widget.wcfg["show_brake_wear"] = True
    monkeypatch.setattr(minfo.wheels, "maxBrakeThickness", [0.03] * 4)
    monkeypatch.setattr(minfo.wheels, "failureBrakeThickness", [0.01] * 4)
    monkeypatch.setattr(minfo.wheels, "currentBrakeThickness", [0.025, 0.02, 0.011, 0.01])
    widget.timerEvent(None)
    assert all(wheel.brake_wear_known for wheel in widget.wheels)
    # (current - failure) / (max - failure)
    assert [round(wheel.brake_wear) for wheel in widget.wheels] == [75, 50, 5, 0]
    widget.grab()


def test_brake_wear_unknown_without_module(widget, monkeypatch):
    from tinypedal.module_info import minfo

    widget.wcfg["show_brake_wear"] = True
    monkeypatch.setattr(minfo.wheels, "maxBrakeThickness", [0.0] * 4)
    monkeypatch.setattr(minfo.wheels, "failureBrakeThickness", [0.0] * 4)
    widget.timerEvent(None)
    assert not any(wheel.brake_wear_known for wheel in widget.wheels)
    widget.grab()  # nothing drawn instead of a wrong percentage


def test_tyre_compound_symbol(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    cfg.user.setting["wheel_status"].update(show_tyre_compound=True, enable_heatmap_auto_matching=False)
    cfg.user.compounds["GT3 - Soft"] = {"symbol": "S", "heatmap": "tyre_default"}
    monkeypatch.setattr(api.read.tyre, "compound_class", lambda: ("GT3 - Soft",) * 4)
    monkeypatch.setattr(api.read.vehicle, "in_pits", lambda: True)
    widget = wheel_status.Realtime(cfg, "wheel_status")
    try:
        widget.timerEvent(None)
        assert [wheel.compound for wheel in widget.wheels] == ["S"] * 4
        widget.grab()
    finally:
        widget.deleteLater()


def test_tyre_temperature_warning(widget):
    widget.wcfg["tyre_temperature_warning_threshold"] = 100
    widget.temp_warning = 100
    widget.timerEvent(None)
    widget.grab()  # 80 C, below threshold
    widget.temp_warning = 50
    widget.grab()  # above threshold, warning colour


def test_caption(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    cfg.user.setting["wheel_status"]["show_caption"] = False
    plain = wheel_status.Realtime(cfg, "wheel_status")
    cfg.user.setting["wheel_status"]["show_caption"] = True
    titled = wheel_status.Realtime(cfg, "wheel_status")
    assert titled.height() > plain.height()
    assert not titled.rect_caption.isEmpty() and plain.rect_caption.isEmpty()
    titled.grab()
    plain.deleteLater()
    titled.deleteLater()


def test_laps_label_on_info_rows(widget, monkeypatch):
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.fuel, "estimatedLaps", 4.5)
    monkeypatch.setattr(minfo.energy, "available", True)
    rows = []
    monkeypatch.setattr(widget, "draw_info_row", lambda painter, rect, label, value: rows.append((label, value)))
    widget.timerEvent(None)
    widget.draw_bottom_rows(None)
    fuel_row = next(value for label, value in rows if label == "Fuel")
    assert fuel_row.endswith("lap"), fuel_row  # laps had no unit before


# --- Layout & performance
def test_vertical_layout_centers_hidden_items(ui_env):
    from PySide6.QtCore import QRectF

    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    cfg.user.setting["wheel_status"]["layout"] = 1
    widget = wheel_status.Realtime(cfg, "wheel_status")
    try:
        widget.abs_seen = widget.tc_seen = False
        widget.abs_level = widget.tc_level = -1
        widget.in_pits = widget.limiter = False
        hidden = widget.visible_center_items()
        assert "abs" not in hidden and "pit_limiter" not in hidden
        drawn = []
        widget.draw_center_item = lambda painter, name, rect: drawn.append((name, rect.top()))
        widget.draw_center(None, QRectF(0, 0, 100, 500))
        assert drawn[0][1] > 0  # free space shared above, not all left at the bottom
    finally:
        widget.deleteLater()


def test_compact_layout_skips_center_data(ui_env, monkeypatch):
    """Compact layout draws no center column, so its data must not be read every tick"""
    from tinypedal.api_control import api
    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    calls = []
    for name in ("abs_level", "tc_level", "tc_cut_level", "tc_slip_level", "speed_limiter"):
        monkeypatch.setattr(api.read.switch, name, lambda _name=name: calls.append(_name) or 0)
    monkeypatch.setattr(api.read.brake, "bias_front", lambda: calls.append("bias_front") or 0.5)
    cfg.user.setting["wheel_status"]["layout"] = 2
    widget = wheel_status.Realtime(cfg, "wheel_status")
    try:
        widget.timerEvent(None)
        assert calls == []
    finally:
        widget.deleteLater()


def test_pits_read_once_per_update(widget, monkeypatch):
    from tinypedal.api_control import api

    calls = []
    monkeypatch.setattr(api.read.vehicle, "in_pits", lambda: calls.append(1) or False)
    widget.wcfg["show_tyre_compound"] = True  # also needs pit state, must reuse the same read
    widget.timerEvent(None)
    assert len(calls) == 1


# --- Visual polish: capsule-shaped chips (LEDs, badges, gauge bars), gradient bars, LED glow
def test_chip_radius_respects_corner_scale(monkeypatch):
    """Chips render square if the user disabled rounded corners, full capsule at the default"""
    from PySide6.QtCore import QRectF

    from tinypedal.widget._painter import OverlayStyle

    wide = QRectF(0, 0, 100, 20)  # short side is height
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.0)
    assert painter_mod.chip_radius(wide) == 0.0
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.05)  # default
    assert painter_mod.chip_radius(wide) == pytest.approx(10.0)  # full capsule (height / 2)
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.5)  # maximum, still capped at a capsule
    assert painter_mod.chip_radius(wide) == pytest.approx(10.0)


def test_chip_radius_uses_shorter_side(monkeypatch):
    """A narrow/tall rect (battery bar) must round by width, not height, or it turns into a lens"""
    from PySide6.QtCore import QRectF

    from tinypedal.widget._painter import OverlayStyle

    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.05)
    tall = QRectF(0, 0, 14, 180)  # short side is width
    assert painter_mod.chip_radius(tall) == pytest.approx(7.0)


def test_fill_chip_square_when_rounding_disabled(monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from tinypedal.widget._painter import OverlayStyle

    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.0)
    painter_mod.fill_chip(painter, QRectF(0, 0, 40, 20), "#FF0000")
    painter.end()
    # Square fill: every corner pixel is opaque (a rounded fill would leave corners transparent)
    assert image.pixelColor(0, 0).alpha() == 255
    assert image.pixelColor(39, 19).alpha() == 255


def test_fill_chip_gradient_square_when_rounding_disabled(monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from tinypedal.widget._painter import OverlayStyle

    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.0)
    painter_mod.fill_chip_gradient(painter, QRectF(0, 0, 40, 20), "#00CCFF")
    painter.end()
    assert image.pixelColor(0, 0).alpha() == 255  # square, not rounded


def test_fill_chip_gradient_handles_zero_width(widget):
    """Must not raise on a degenerate (zero-width) bar, e.g. gear/speed rect before first update"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter


    image = QImage(10, 10, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter_mod.fill_chip_gradient(painter, QRectF(0, 0, 0, 10), "#00CCFF")
    painter_mod.fill_chip_gradient(painter, QRectF(0, 0, 10, 0), "#00CCFF")
    painter.end()  # no exception


def test_led_glow_only_on_lit_leds(widget, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    glows = []
    monkeypatch.setattr(wheel_status, "fill_glow", lambda painter, rect, color: glows.append(color))
    widget.wcfg["number_of_rpm_leds"] = 5
    widget.rpm_max = 8000.0
    image = QImage(100, 10, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    widget.rpm = 0.0  # no LED lit
    widget.draw_leds(painter, QRectF(0, 0, 100, 10))
    assert glows == []
    widget.rpm = 6000.0  # some LEDs lit
    glows.clear()
    widget.draw_leds(painter, QRectF(0, 0, 100, 10))
    painter.end()
    assert glows
    widget.grab()  # full paint with glow enabled, must not raise


# --- Battery bar (charge/discharge gauge, positioned left or right of the widget)
def new_widget(overrides=None):
    from tinypedal.setting import cfg
    from tinypedal.widget import wheel_status

    if overrides:
        cfg.user.setting["wheel_status"].update(overrides)
    return wheel_status.Realtime(cfg, "wheel_status")


def test_battery_bar_hidden_by_default(widget):
    assert not widget.show_battery_bar
    assert widget.rect_battery.isEmpty()


def test_battery_bar_adds_width_on_left(ui_env):
    base = new_widget({"show_battery_bar": False})
    base_width = base.width()
    base.deleteLater()
    left = new_widget({"show_battery_bar": True, "battery_bar_position": "Left"})
    try:
        assert left.width() > base_width
        assert left.rect_battery.left() == 0  # flush against the left edge
        assert left.rects_tyre[0].left() > left.rect_battery.right()  # content pushed right
    finally:
        left.deleteLater()


def test_battery_bar_position_right(ui_env):
    right = new_widget({"show_battery_bar": True, "battery_bar_position": "Right"})
    try:
        assert right.rects_tyre[0].left() < right.rect_battery.left()  # content stays first
        assert right.rect_battery.right() == pytest.approx(right.width(), abs=1)
    finally:
        right.deleteLater()


def test_battery_bar_spans_car_view_height(ui_env):
    """Same vertical extent as the car view (tyres/center column), matching rect_body_damage,
    not stretched into the caption/LED row above or the bottom info rows below"""
    instance = new_widget({"show_battery_bar": True})
    try:
        assert instance.rect_battery.top() == pytest.approx(instance.rect_body_damage.top())
        assert instance.rect_battery.bottom() == pytest.approx(instance.rect_body_damage.bottom())
        assert instance.rect_battery.bottom() < instance.bottom_rows[0][0].top()
    finally:
        instance.deleteLater()


def test_battery_data_not_read_when_disabled(widget, monkeypatch):
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.hybrid, "batteryCharge", 88.0)
    monkeypatch.setattr(minfo.hybrid, "motorState", 3)
    widget.timerEvent(None)
    assert widget.battery_charge == 0.0  # unchanged, never read
    assert widget.battery_state == 0


def test_battery_data_read_when_enabled(widget, monkeypatch):
    from tinypedal.module_info import minfo

    widget.show_battery_bar = True
    monkeypatch.setattr(minfo.hybrid, "batteryCharge", 42.5)
    monkeypatch.setattr(minfo.hybrid, "motorState", 2)
    widget.timerEvent(None)
    assert widget.battery_charge == 42.5
    assert widget.battery_state == 2


@pytest.mark.parametrize("state", [0, 1, 2, 3])
@pytest.mark.parametrize("charge", [-10.0, 0.0, 55.0, 100.0, 150.0])
def test_battery_bar_draws_without_crash(ui_env, state, charge):
    instance = new_widget({"show_battery_bar": True})
    try:
        instance.battery_charge = charge
        instance.battery_state = state
        instance.grab()  # full paint, must not raise regardless of value/state combination
    finally:
        instance.deleteLater()


def test_battery_flow_direction_differs_charge_vs_drain(ui_env, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    instance = new_widget({"show_battery_bar": True})
    try:
        monkeypatch.setattr("tinypedal.widget.wheel_status.monotonic", lambda: 12.345)
        rect = QRectF(0, 0, 16, 120)

        def render(charging):
            image = QImage(16, 120, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            instance.draw_battery_flow(painter, rect, charging=charging)
            painter.end()
            return image

        charging_img = render(True)
        draining_img = render(False)
        # Same instant, opposite flow direction: band pattern must differ
        different = any(
            charging_img.pixelColor(x, y) != draining_img.pixelColor(x, y)
            for x in (2, 8, 14) for y in range(0, 120, 5)
        )
        assert different
    finally:
        instance.deleteLater()


def test_battery_bar_width_and_text_size_configurable(ui_env):
    narrow = new_widget({"show_battery_bar": True, "battery_bar_scale": 0.55, "font_scale_battery": 0.75})
    narrow_size = (narrow.rect_battery.width(), narrow.font_battery.pixelSize(), narrow.width())
    narrow.deleteLater()
    wide = new_widget({"show_battery_bar": True, "battery_bar_scale": 1.8, "font_scale_battery": 1.3})
    try:
        assert wide.rect_battery.width() > narrow_size[0]
        assert wide.font_battery.pixelSize() > narrow_size[1]
        assert wide.width() > narrow_size[2]  # widget grows with the bar
    finally:
        wide.deleteLater()


def test_battery_bar_width_and_text_size_clamped(ui_env):
    """Out-of-range values must not produce a giant or invisible gauge"""
    huge = new_widget({"show_battery_bar": True, "battery_bar_scale": 99.0, "font_scale_battery": 99.0})
    limit = new_widget({"show_battery_bar": True, "battery_bar_scale": 4.0, "font_scale_battery": 4.0})
    tiny = new_widget({"show_battery_bar": True, "battery_bar_scale": 0.0, "font_scale_battery": 0.0})
    try:
        assert huge.rect_battery.width() == limit.rect_battery.width()
        assert huge.font_battery.pixelSize() == limit.font_battery.pixelSize()
        assert tiny.rect_battery.width() >= 4  # still visible
        assert tiny.font_battery.pixelSize() > 0
    finally:
        for instance in (huge, limit, tiny):
            instance.deleteLater()


def test_battery_no_hybrid_system_detected(widget):
    """No state and no charge means no hybrid system, shown as a dash instead of 0%"""
    widget.battery_state = 0
    widget.battery_charge = 0.0
    assert not widget.has_hybrid
    widget.battery_charge = 30.0  # charge reported before the state is known
    assert widget.has_hybrid
    widget.battery_charge = 0.0
    widget.battery_state = 1  # motor off, but the car does have a hybrid system
    assert widget.has_hybrid


def disc_pixels(instance, index, steer, color="#00FF00"):
    """Bounding box of the brake disc bar as actually painted, in widget coordinates"""
    from PySide6.QtGui import QColor, QImage, QPainter

    wheel = instance.wheels[index]
    wheel.brake_color = color
    wheel.steer = steer
    image = QImage(instance.width(), instance.height(), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    instance.wcfg["show_brake_temperature"] = False  # bar only, no text pixels
    instance.draw_disc(painter, index, instance.rects_disc[index], wheel)
    painter.end()
    target = QColor(color).rgb()
    points = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).rgb() == target
    ]
    assert points, "brake disc not painted"
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def test_brake_disc_turns_with_wheel(ui_env):
    """Disc must stay bolted to the wheel instead of floating beside a steered tyre"""
    instance = new_widget({"show_wheel_angle": True, "maximum_wheel_angle": 30})
    try:
        straight = disc_pixels(instance, 0, 0.0)
        turned = disc_pixels(instance, 0, 30.0)
        assert turned != straight, "disc did not move with the wheel"
        # A tilted bar covers a wider band than an upright one
        assert (turned[2] - turned[0]) > (straight[2] - straight[0])
        # Opposite lock mirrors it
        other = disc_pixels(instance, 0, -30.0)
        assert other != turned
    finally:
        instance.deleteLater()


def test_brake_disc_keeps_its_gap_to_the_tyre(ui_env):
    """Turning about the tyre centre keeps the wheel assembly rigid: same distance, no overlap"""
    import math

    instance = new_widget({"show_wheel_angle": True, "maximum_wheel_angle": 30})
    try:
        tyre_centre = instance.rects_tyre[0].center()

        def distance(steer):
            left, top, right, bottom = disc_pixels(instance, 0, steer)
            cx, cy = (left + right) / 2, (top + bottom) / 2
            return math.hypot(cx - tyre_centre.x(), cy - tyre_centre.y())

        assert distance(30.0) == pytest.approx(distance(0.0), abs=1.5)
        assert distance(-30.0) == pytest.approx(distance(0.0), abs=1.5)
    finally:
        instance.deleteLater()


def test_brake_disc_static_without_wheel_angle(ui_env):
    """With wheel angle off nothing steers, so the disc stays upright"""
    instance = new_widget({"show_wheel_angle": False})
    try:
        assert instance.max_steer == 0
        instance.timerEvent(None)
        assert all(wheel.steer == 0 for wheel in instance.wheels)
        instance.grab()
    finally:
        instance.deleteLater()


def test_battery_warning_levels(ui_env):
    instance = new_widget({"show_battery_bar": True, "battery_low_threshold": 10,
                           "battery_high_threshold": 95})
    try:
        instance.battery_state = 2  # hybrid car, draining
        for charge, expected in ((50.0, 0), (10.0, 1), (4.0, 1), (95.0, 2), (99.0, 2), (94.0, 0)):
            instance.battery_charge = charge
            assert instance.battery_warning_level() == expected, charge
        # A car without hybrid system never warns, even though charge reads 0
        instance.battery_state = 0
        instance.battery_charge = 0.0
        assert instance.battery_warning_level() == 0
    finally:
        instance.deleteLater()


def test_battery_warning_flashes_then_stays_highlighted(ui_env, monkeypatch):
    """Flashes a few times to catch the eye, then holds the warning color"""
    from tinypedal.module_info import minfo

    instance = new_widget({
        "show_battery_bar": True, "show_battery_warning_flash": True,
        "battery_warning_flash_duration": 0.2, "battery_warning_flash_interval": 0.2,
        "number_of_battery_warning_flashes": 3, "battery_low_threshold": 10,
    })
    try:
        monkeypatch.setattr(minfo.hybrid, "batteryCharge", 5.0)
        monkeypatch.setattr(minfo.hybrid, "motorState", 2)
        clock = [1000.0]
        monkeypatch.setattr("tinypedal.widget._common.monotonic", lambda: clock[0])
        seen = []
        for _ in range(40):  # 4 seconds at 0.1s steps, past the 3 flashes
            instance.timerEvent(None)
            seen.append(instance.battery_highlight)
            clock[0] += 0.1
        assert instance.battery_warning == 1
        assert False in seen[:20], "never turned off, so it did not flash"
        assert all(seen[-5:]), "did not settle to a steady warning after flashing"
    finally:
        instance.deleteLater()


def test_battery_warning_steady_when_flash_disabled(ui_env, monkeypatch):
    from tinypedal.module_info import minfo

    instance = new_widget({"show_battery_bar": True, "show_battery_warning_flash": False,
                           "battery_low_threshold": 10})
    try:
        assert instance.battery_flash is None
        monkeypatch.setattr(minfo.hybrid, "batteryCharge", 5.0)
        monkeypatch.setattr(minfo.hybrid, "motorState", 2)
        for _ in range(5):
            instance.timerEvent(None)
            assert instance.battery_highlight  # warning colour shown without blinking
        instance.grab()
    finally:
        instance.deleteLater()


def test_battery_warning_color_overrides_flow_color(ui_env):
    """A low/high warning must win over the charge/discharge colour"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    instance = new_widget({"show_battery_bar": True, "battery_low_threshold": 10,
                           "enable_battery_bar_animation": False})
    try:
        def render(warning):
            instance.battery_charge = 8.0
            instance.battery_state = 2  # draining
            instance.battery_warning = warning
            instance.battery_highlight = True
            image = QImage(20, 100, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            instance.draw_battery_bar(painter, QRectF(0, 0, 20, 100))
            painter.end()
            return image.pixelColor(10, 96)  # inside the fill, near the bottom

        assert render(1) != render(0)
    finally:
        instance.deleteLater()


def test_battery_bar_idle_states_have_no_flow(ui_env, monkeypatch):
    """States other than drain/regen (n/a, off) must not animate"""
    calls = []
    instance = new_widget({"show_battery_bar": True})
    try:
        monkeypatch.setattr(instance, "draw_battery_flow", lambda *a, **k: calls.append(1))
        for state in (0, 1):
            instance.battery_state = state
            instance.battery_charge = 50.0
            instance.grab()
        assert calls == []
        instance.battery_state = 2
        instance.grab()
        assert calls
    finally:
        instance.deleteLater()


# --- Readability guard and configurable damage colours
def test_readings_dropped_when_box_too_crowded(ui_env):
    """Enabling every tyre reading must not squeeze them all into unreadable slivers"""
    instance = new_widget({
        "show_tyre_compound": True, "show_tyre_temperature": True, "show_tyre_pressure": True,
        "show_tyre_wear": True, "show_tyre_wear_end_stint": True,
    })
    try:
        from tinypedal.widget._wheel_state import (
            MIN_READING_SCALE,
            READING_COMPOUND,
            READING_END_STINT,
            READING_PRESSURE,
            READING_STATUS,
            READING_TEMPERATURE,
            READING_WEAR,
        )

        usable = instance.rects_tyre[0].height() * 0.88
        # Six readings, least important first
        lines = [
            (READING_COMPOUND, "S", instance.font_small, 0.9, "", ""),
            (READING_END_STINT, "→12%", instance.font_small, 0.9, "", ""),
            (READING_PRESSURE, "145", instance.font_small, 1.0, "", ""),
            (READING_WEAR, "28%", instance.font_small, 1.0, "", ""),
            (READING_TEMPERATURE, "90", instance.font(), 1.3, "", ""),
            (READING_STATUS, "FLAT", instance.font_small, 1.0, "", ""),
        ]
        kept = wheel_state.fit_readings(list(lines), usable, instance.unit)
        assert len(kept) < len(lines), "nothing was dropped"
        # What survives is the most important, and is readable
        priorities = [line[0] for line in kept]
        assert READING_STATUS in priorities and READING_TEMPERATURE in priorities
        assert READING_COMPOUND not in priorities
        total = sum(line[3] for line in kept)
        assert usable * min(line[3] for line in kept) / total >= instance.unit * MIN_READING_SCALE
        # Display order is preserved
        assert priorities == sorted(priorities, key=lambda p: [line[0] for line in lines].index(p))
    finally:
        instance.deleteLater()


def test_few_readings_are_all_kept(ui_env):
    instance = new_widget({})
    try:
        usable = instance.rects_tyre[0].height() * 0.88
        lines = [
            (4, "90", instance.font(), 1.3, "", ""),
            (3, "28%", instance.font_small, 1.0, "", ""),
        ]
        assert wheel_state.fit_readings(list(lines), usable, instance.unit) == lines
    finally:
        instance.deleteLater()


def test_damage_colors_configurable(ui_env):
    instance = new_widget({"damage_color_minor": "#111111", "damage_color_major": "#222222",
                           "damage_color_critical": "#333333"})
    try:
        assert instance.damage_colors == ("", "#111111", "#222222", "#333333")
        instance.body_damage = (1, 2, 3, 0, 0, 0, 0, 0)
        for wheel in instance.wheels:
            wheel.suspension_damage = 0.7
        instance.grab()  # both damage drawings use the options
    finally:
        instance.deleteLater()


# --- Diagnostic readings (camber, load, carcass temperature, wear per lap, ride height,
# --- slip angle, brake pressure, wheel locking). All opt-in: default presets must not change.
DIAGNOSTIC_OPTIONS = (
    "show_tyre_wear_per_lap",
    "show_tyre_carcass_temperature",
    "show_tyre_load",
    "show_tyre_slip_angle",
    "show_wheel_camber",
    "show_ride_height",
    "show_brake_pressure",
    "show_wheel_locking",
)


def test_diagnostic_readings_are_opt_in(widget):
    for option in DIAGNOSTIC_OPTIONS:
        assert widget.wcfg[option] is False, f"{option} must default to off"


def test_diagnostic_readings_skip_their_readers_when_off(widget, monkeypatch):
    """A reading that is off must not cost a shared-memory read every frame"""
    from tinypedal.api_control import api

    called = []

    def spy(tag):
        def reader(*args, **kwargs):
            called.append(tag)
            return (0.0,) * 4
        return reader

    for group, name in (
        ("tyre", "carcass_temperature"), ("tyre", "load"),
        ("wheel", "ride_height"), ("brake", "pressure"),
    ):
        monkeypatch.setattr(getattr(api.read, group), name, spy(f"{group}.{name}"), raising=False)
    widget.timerEvent(None)
    assert not called, f"read while hidden: {called}"


def test_diagnostic_readings_reach_wheel_state(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.module_info import minfo

    monkeypatch.setattr(api.read.tyre, "carcass_temperature", lambda: (91.0, 92.0, 93.0, 94.0), raising=False)
    monkeypatch.setattr(api.read.tyre, "load", lambda: (1000.0, 1000.0, 500.0, 500.0), raising=False)
    monkeypatch.setattr(api.read.wheel, "ride_height", lambda: (0.032, 0.033, 0.058, 0.059), raising=False)
    monkeypatch.setattr(api.read.brake, "pressure", lambda: (0.8, 0.8, 0.4, 0.4), raising=False)
    monkeypatch.setattr(minfo.wheels, "camberAngle", [-3.2, -3.1, -2.4, -2.3])
    monkeypatch.setattr(minfo.wheels, "slipAngle", [4.1, -2.0, 0.8, 0.9])
    monkeypatch.setattr(minfo.wheels, "estimatedValidTreadWear", [0.82, 0.79, 0.55, 0.57])
    instance = new_widget(dict.fromkeys(DIAGNOSTIC_OPTIONS, True))
    try:
        instance.timerEvent(None)
        front_left, rear_left = instance.wheels[0], instance.wheels[2]
        assert front_left.carcass_temp == 91.0
        assert front_left.ride_height == pytest.approx(32.0)  # meters converted to millimeters
        assert front_left.brake_pressure == pytest.approx(80.0)
        assert front_left.load_ratio == pytest.approx(100 / 3)  # share of the car's total load
        assert rear_left.load_ratio == pytest.approx(100 / 6)
        assert front_left.camber == pytest.approx(-3.2)
        assert front_left.slip_angle == pytest.approx(4.1)
        assert front_left.wear_per_lap == pytest.approx(0.82)
        instance.grab()
    finally:
        instance.deleteLater()


def test_wheel_locking_is_a_center_item(ui_env, monkeypatch):
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.wheels, "lockingPercentFront", 0.12)
    monkeypatch.setattr(minfo.wheels, "lockingPercentRear", 0.04)
    instance = new_widget({"show_wheel_locking": True})
    try:
        assert "locking" in instance.center_order
        assert instance.need_locking
        instance.timerEvent(None)
        assert instance.locking_front == pytest.approx(12.0)
        assert instance.locking_rear == pytest.approx(4.0)
        instance.grab()
    finally:
        instance.deleteLater()


def test_wheel_locking_not_read_when_hidden(widget):
    assert not widget.need_locking
    widget.timerEvent(None)
    assert widget.locking_front == 0.0


def test_diagnostic_readings_yield_to_the_core_ones(ui_env):
    """A crowded box drops camber or ride height before it drops temperature or pressure"""
    instance = new_widget(dict.fromkeys(DIAGNOSTIC_OPTIONS, True))
    try:
        from tinypedal.widget._wheel_state import (
            READING_CAMBER,
            READING_RIDE_HEIGHT,
            READING_STATUS,
            READING_TEMPERATURE,
        )

        lines = [
            (READING_RIDE_HEIGHT, "H32", instance.font_small, 0.9, "", ""),
            (READING_CAMBER, "C-3.2", instance.font_small, 0.9, "", ""),
            (READING_TEMPERATURE, "90", instance.font(), 1.3, "", ""),
            (READING_STATUS, "FLAT", instance.font_small, 1.0, "", ""),
        ]
        usable = instance.unit * 1.5  # far too little room for four lines
        kept = [line[0] for line in wheel_state.fit_readings(list(lines), usable, instance.unit)]
        assert READING_TEMPERATURE in kept and READING_STATUS in kept
        assert READING_RIDE_HEIGHT not in kept and READING_CAMBER not in kept
    finally:
        instance.deleteLater()


def test_brake_column_shares_rows_between_readings(ui_env, monkeypatch):
    """Brake temperature, thickness and pressure are drawn without overlapping"""
    from PySide6.QtCore import QRectF

    instance = new_widget({"show_brake_temperature": True, "show_brake_pressure": True})
    try:
        drawn = []
        monkeypatch.setattr(
            instance, "draw_fit_text",
            lambda painter, rect, text, font, align=None: drawn.append(QRectF(rect)),
        )
        from PySide6.QtGui import QImage, QPainter

        image = QImage(200, 200, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        instance.draw_disc(painter, 0, instance.rects_disc[0], instance.wheels[0])
        painter.end()
        assert len(drawn) == 2
        assert drawn[0].bottom() == pytest.approx(drawn[1].top())  # stacked, no overlap
        assert drawn[1].bottom() <= instance.rects_disc[0].bottom() + 0.01
    finally:
        instance.deleteLater()


# --- Center column: brake migration, delta to best, lap time, justified alignment
def test_new_center_items_read_their_data(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.module_info import minfo

    monkeypatch.setattr(api.read.brake, "migration", lambda: 2.5, raising=False)
    monkeypatch.setattr(minfo.delta, "deltaBest", -0.234)
    monkeypatch.setattr(minfo.delta, "lapTimeCurrent", 92.5)
    instance = new_widget({"show_brake_migration": True, "show_delta_best": True, "show_laptime": True})
    try:
        assert {"brake_migration", "delta", "laptime"} <= set(instance.center_order)
        instance.timerEvent(None)
        assert instance.brake_migration == pytest.approx(2.5)
        assert instance.delta_best == pytest.approx(-0.234)
        assert instance.laptime_current == pytest.approx(92.5)
        instance.grab()
    finally:
        instance.deleteLater()


def test_new_center_items_are_opt_in(widget):
    for option in ("show_brake_migration", "show_delta_best", "show_laptime"):
        assert widget.wcfg[option] is False
    assert not widget.need_brake_migration
    assert not widget.need_delta
    assert not widget.need_laptime


def test_delta_row_colors_gain_and_loss(ui_env, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    instance = new_widget({"show_delta_best": True})
    try:
        colors = []
        monkeypatch.setattr(
            instance, "draw_info_row",
            lambda painter, rect, label, value, color="": colors.append(color),
        )
        image = QImage(200, 200, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        rect = QRectF(0, 0, 80, 20)
        instance.delta_best = -0.5
        instance.draw_center_item(painter, "delta", rect)
        instance.delta_best = 0.5
        instance.draw_center_item(painter, "delta", rect)
        painter.end()
        assert colors == [instance.wcfg["delta_gain_color"], instance.wcfg["delta_loss_color"]]
    finally:
        instance.deleteLater()


def test_justified_alignment_uses_label_value_rows(ui_env, monkeypatch):
    """Justified puts speed and RPM in the same rows as the other readings, so values line up"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    for alignment, expected in (("Centered", []), ("Justified", ["SPD", "RPM"])):
        instance = new_widget({"center_column_alignment": alignment})
        try:
            labels: list[str] = []
            monkeypatch.setattr(
                instance, "draw_info_row",
                lambda painter, rect, label, value, color="", _out=labels: _out.append(label),
            )
            image = QImage(200, 200, QImage.Format.Format_ARGB32)
            painter = QPainter(image)
            for name in ("speed", "rpm"):
                instance.draw_center_item(painter, name, QRectF(0, 0, 80, 20))
            painter.end()
            assert labels == expected, alignment
        finally:
            instance.deleteLater()


def test_center_alignment_option_is_a_valid_choice():
    """Unmatched choice options are rejected by the config dialog, as bar_position once was"""
    from tinypedal import regex_pattern as rxp

    assert rxp.CHOICE_COMMON[rxp.CFG_COLUMN_ALIGNMENT] == ("Centered", "Justified")
