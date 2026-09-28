"""Wheel status widget tests"""

from types import SimpleNamespace

import pytest


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
    assert widget.level_text("TC", 5, 3, 2) == "TC 5/3/2"
    assert widget.level_text("TC", 5, -1, 2) == "TC 5/2"  # cut not available
    assert widget.level_text("TC", 5, -1, -1) == "TC 5"
    assert widget.level_text("TC", -1, -1, -1) == "TC"
    assert widget.level_text("ABS", 3) == "ABS 3"


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
    fitted = large.fit_font(painter, large.font_gear, "TC 10/10/10", 20, 100)
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

    cfg.user.setting["wheel_status"].update(display_order_gear=0, display_order_abs=9)
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

    from tinypedal.widget import wheel_status
    from tinypedal.widget._painter import OverlayStyle

    wide = QRectF(0, 0, 100, 20)  # short side is height
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.0)
    assert wheel_status._chip_radius(wide) == 0.0
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.05)  # default
    assert wheel_status._chip_radius(wide) == pytest.approx(10.0)  # full capsule (height / 2)
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.5)  # maximum, still capped at a capsule
    assert wheel_status._chip_radius(wide) == pytest.approx(10.0)


def test_chip_radius_uses_shorter_side(monkeypatch):
    """A narrow/tall rect (battery bar) must round by width, not height, or it turns into a lens"""
    from PySide6.QtCore import QRectF

    from tinypedal.widget import wheel_status
    from tinypedal.widget._painter import OverlayStyle

    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.05)
    tall = QRectF(0, 0, 14, 180)  # short side is width
    assert wheel_status._chip_radius(tall) == pytest.approx(7.0)


def test_fill_chip_square_when_rounding_disabled(monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from tinypedal.widget import wheel_status
    from tinypedal.widget._painter import OverlayStyle

    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.0)
    wheel_status._fill_chip(painter, QRectF(0, 0, 40, 20), "#FF0000")
    painter.end()
    # Square fill: every corner pixel is opaque (a rounded fill would leave corners transparent)
    assert image.pixelColor(0, 0).alpha() == 255
    assert image.pixelColor(39, 19).alpha() == 255


def test_fill_chip_gradient_square_when_rounding_disabled(monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from tinypedal.widget import wheel_status
    from tinypedal.widget._painter import OverlayStyle

    image = QImage(40, 20, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    monkeypatch.setattr(OverlayStyle, "corner_scale", 0.0)
    wheel_status._fill_chip_gradient(painter, QRectF(0, 0, 40, 20), "#00CCFF")
    painter.end()
    assert image.pixelColor(0, 0).alpha() == 255  # square, not rounded


def test_fill_chip_gradient_handles_zero_width(widget):
    """Must not raise on a degenerate (zero-width) bar, e.g. gear/speed rect before first update"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from tinypedal.widget import wheel_status

    image = QImage(10, 10, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    wheel_status._fill_chip_gradient(painter, QRectF(0, 0, 0, 10), "#00CCFF")
    wheel_status._fill_chip_gradient(painter, QRectF(0, 0, 10, 0), "#00CCFF")
    painter.end()  # no exception


def test_led_glow_only_on_lit_leds(widget, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    glows = []
    monkeypatch.setattr(widget, "_fill_led_glow", lambda painter, rect, color: glows.append(color))
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
