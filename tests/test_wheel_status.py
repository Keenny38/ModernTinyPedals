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
