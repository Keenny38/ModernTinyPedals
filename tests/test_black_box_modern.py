"""Black box widget: incident recorder, event log, layout, visual effects"""

import json
import math

import pytest

from tinypedal.widget._black_box import recorder as rec
from tinypedal.widget._black_box.recorder import Event, EventLog, Recorder, Sample


def sample(time, speed, throttle=0.0, brake=0.0, slip=""):
    return Sample(time, speed, throttle, brake, 3, False, False, slip)


# --- Recorder
def test_recorder_keeps_rolling_window():
    recorder = Recorder(duration=2.0, sample_interval=0.1)
    for step in range(100):
        recorder.add(sample(step * 0.1, 30.0), 0.0)
    assert len(recorder.samples) == 21  # 2 s at 10 Hz, plus the newest
    assert not recorder.incidents


def test_recorder_skips_samples_closer_than_interval():
    recorder = Recorder(sample_interval=0.1)
    recorder.add(sample(0.0, 30.0), 0.0)
    recorder.add(sample(0.05, 30.0), 0.0)
    assert len(recorder.samples) == 1


def test_impact_freezes_after_post_trigger_time():
    recorder = Recorder(duration=5.0, sample_interval=0.1, deceleration_threshold=4.0, post_trigger=1.0)
    time = 0.0
    for _ in range(20):
        recorder.add(sample(time, 50.0), 0.0)
        time += 0.1
    assert recorder.add(sample(time, 40.0), 0.0) is None  # 10 m/s in 0.1 s: about 10 g, pending
    assert recorder.pending is not None
    incident = None
    while incident is None and time < 5:
        time += 0.1
        incident = recorder.add(sample(time, 0.0), 0.0)
    assert incident is not None
    assert incident.reason == "impact"
    assert incident.peak_g > 30  # 40 m/s to 0 in 0.1 s
    assert incident.samples[-1].time - incident.time == pytest.approx(1.0, abs=0.11)
    assert recorder.last_incident is incident


def test_damage_triggers_incident_and_cooldown_merges_repeats():
    recorder = Recorder(duration=4.0, sample_interval=0.1, post_trigger=0.0)
    recorder.add(sample(0.0, 20.0), 0.0)
    assert recorder.add(sample(0.1, 20.0), 1.0).reason == "damage"
    assert recorder.add(sample(0.2, 20.0), 2.0) is None  # same incident, within half duration
    assert recorder.add(sample(3.0, 20.0), 3.0).reason == "damage"  # later: new incident
    assert len(recorder.incidents) == 2


def test_slow_speed_drop_is_not_an_impact():
    recorder = Recorder(sample_interval=0.1, deceleration_threshold=1.0)
    recorder.add(sample(0.0, 3.0), 0.0)
    recorder.add(sample(0.1, 0.0), 0.0)  # stop from walking pace
    assert recorder.pending is None


def test_recorder_ignores_non_finite_samples():
    recorder = Recorder()
    recorder.add(sample(0.0, math.nan), 0.0)
    recorder.add(sample(0.1, math.inf), 0.0)
    recorder.add(sample(0.2, 10.0), math.nan)
    assert not recorder.samples


def test_threshold_zero_disables_impact_detection():
    recorder = Recorder(sample_interval=0.1, deceleration_threshold=0.0)
    recorder.add(sample(0.0, 80.0), 0.0)
    recorder.add(sample(0.1, 0.0), 0.0)
    assert recorder.pending is None


def test_export_incident(tmp_path):
    incident = rec.Incident(10.0, "impact", 6.3, 12, 271.0, (sample(9.0, 50.0, 1.0), sample(10.0, 5.0, 0.0, 1.0)))
    path = rec.export_incident(incident, str(tmp_path / "blackbox"))
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    assert data["reason"] == "impact" and data["lap"] == 12
    assert [s["time"] for s in data["samples"]] == [-1.0, 0.0]
    assert rec.export_incident(incident, str(tmp_path / "blackbox" / "incident.json" / "\0bad")) == ""


# --- Event log
def test_event_log_records_each_event_once():
    log = EventLog(size=3)
    labels = {"puncture": "PUNCT", "flat": "FLAT", "detached": "OFF", "damage": "DAMAGE"}
    log.update(3, 60.0, ["", "", "", ""], 0.0, labels)
    assert not log.events
    log.update(4, 125.0, ["", "", "", "puncture"], 0.0, labels)
    log.update(4, 126.0, ["", "", "", "puncture"], 0.0, labels)  # still punctured: not logged again
    log.update(5, 130.0, ["flat", "", "", "puncture"], 1.0, labels)
    assert [event.text for event in log.events] == ["PUNCT RR", "FLAT FL", "DAMAGE"]
    assert log.events[0].critical and not log.events[1].critical
    log.update(6, 200.0, ["", "", "", ""], 1.0, labels)
    log.update(6, 201.0, ["", "detached", "", ""], 1.0, labels)
    assert len(log.events) == 3 and log.events[-1].text == "OFF FR"  # oldest dropped


def test_format_event():
    assert rec.format_event(Event(12, 271.0, "PUNCT FR", True)) == "L12 04:31 PUNCT FR"
    assert rec.format_event(Event(80, 3725.0, "DAMAGE", False)) == "L80 1:02:05 DAMAGE"
    assert rec.format_event(Event(-1, math.nan, "X", False)) == "L0 00:00 X"


# --- Widget
def new_widget(overrides=None):
    from tinypedal.setting import cfg
    from tinypedal.widget import black_box

    # Layout tests need room for every block, auto resize has its own tests
    cfg.user.setting["black_box"].update({"enable_auto_resize": False, **(overrides or {})})
    return black_box.Realtime(cfg, "black_box")


def test_recorder_panels_add_height(ui_env):
    base = new_widget()
    height = base.height()
    base.deleteLater()
    full = new_widget({"show_incident_recorder": True, "show_event_log": True, "number_of_event_log_lines": 4})
    try:
        assert full.height() > height
        assert not full.rect_trace.isNull()
        assert len(full.event_rows) == 4
        assert full.rect_trace.top() >= full.rect_car_view.bottom()
        assert full.event_rows[0].top() >= full.rect_trace.bottom()
        assert full.event_rows[-1].bottom() <= full.height()
    finally:
        full.deleteLater()


def test_layout_does_not_shadow_qwidget_methods(ui_env):
    widget = new_widget()
    try:
        assert callable(widget.width) and callable(widget.height) and callable(widget.layout)
        assert widget.car_layout.width == widget.width()
    finally:
        widget.deleteLater()


def test_recorder_fed_by_updates_and_trace_drawn(ui_env, monkeypatch):
    from tinypedal.widget._black_box import reader

    clock = [100.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    widget = new_widget({"show_incident_recorder": True, "show_event_log": True,
                         "enable_incident_file_export": False})
    try:
        for _ in range(30):
            widget.timerEvent(None)
            clock[0] += 0.05
        assert len(widget.recorder.samples) >= 25
        widget.grab()  # live trace
        widget.recorder.incidents.append(
            rec.Incident(clock[0] - 0.5, "impact", 5.0, 3, 10.0, tuple(widget.recorder.samples)))
        assert widget.showing_incident()
        widget.event_log.add(3, 10.0, "IMPACT 5.0g", True)
        widget.grab()  # frozen trace, event log
        clock[0] += 1000
        assert not widget.showing_incident()
    finally:
        widget.deleteLater()


def test_incident_logged_and_exported(ui_env, monkeypatch, tmp_path):
    from tinypedal.widget._black_box import reader

    saved = []
    monkeypatch.setattr(reader, "export_incident", lambda incident, folder: saved.append(folder))
    widget = new_widget({"show_incident_recorder": True, "show_event_log": True})
    try:
        widget.recorder.post_trigger = 0.0
        speeds = iter([60.0, 60.0, 10.0])
        clock = iter([1.0, 1.1, 1.2])
        monkeypatch.setattr(reader, "monotonic", lambda: next(clock))
        for speed in speeds:
            widget.update_recorder(speed)
        assert widget.recorder.incidents
        assert widget.event_log.events[-1].text.startswith("IMPACT")
        assert saved and saved[0].endswith("blackbox")
    finally:
        widget.deleteLater()


def test_color_fade(ui_env):
    from PySide6.QtGui import QColor

    from tinypedal.widget._black_box.wheels import ColorFade

    fade = ColorFade(1.0)
    assert fade.color_of("#000000", 0.0) == QColor("#000000")  # first color: no fade
    halfway = fade.color_of("#FFFFFF", 10.0) and fade.color(10.5)
    assert 120 <= halfway.red() <= 135
    assert fade.active(10.5) and not fade.active(11.0)
    assert fade.color(11.0) == QColor("#FFFFFF")
    instant = ColorFade(0.0)
    instant.color_of("#000000", 0.0)
    assert instant.color_of("#FFFFFF", 1.0) == QColor("#FFFFFF")


def test_alerts_pulse_and_keep_repainting(ui_env, monkeypatch):
    widget = new_widget()
    try:
        assert widget.pulse(0.0) == pytest.approx(0.675)
        values = {round(widget.pulse(step / 10), 3) for step in range(10)}
        assert min(values) >= 0.35 and max(values) <= 1.0 and len(values) > 3
        widget.wheels[0].status = "puncture"
        assert widget.animating()
        widget.alert_pulse = False
        assert widget.pulse(0.25) == 1.0
    finally:
        widget.deleteLater()


def test_visual_effects_can_be_disabled(ui_env):
    widget = new_widget({"enable_depth_effects": False,
                         "enable_smooth_transition": False, "enable_alert_pulse": False})
    try:
        assert not widget.depth_effects and not widget.alert_pulse
        assert widget.tyre_fades[0].duration == 0
        widget.timerEvent(None)
        widget.grab()
    finally:
        widget.deleteLater()


def test_robust_with_recorder_and_extreme_values(ui_env):
    widget = new_widget({"show_incident_recorder": True, "show_event_log": True})
    try:
        widget.recorder.samples.extend(sample(float(t), value) for t, value in enumerate((1e308, -5.0, 0.0)))
        widget.event_log.add(10**9, 1e12, "X" * 200, True)
        widget.grab()
    finally:
        widget.deleteLater()


# --- Damage panel (same display as Damage widget), bottom right
def test_damage_panel_geometry():
    from PySide6.QtCore import QRectF

    from tinypedal.widget._black_box.damage import damage_geometry

    rect = QRectF(10, 20, 60, 80)
    shapes = damage_geometry(rect, 16)
    assert len(shapes.parts) == 8 and len(shapes.wheels) == 4
    for part in (*shapes.parts, *shapes.wheels):
        assert rect.contains(part)
    assert not shapes.shell.contains(rect.center())  # shell, hollow middle
    assert shapes.integrity.contains(rect.center())
    assert shapes.caption.bottom() <= shapes.integrity.top() + 0.01 <= shapes.gauge.top()
    for wheel in shapes.wheels:  # integrity reading never covers a wheel
        assert not wheel.intersects(shapes.integrity)


def test_damage_panel_colors_and_integrity(ui_env):
    widget = new_widget()
    try:
        wcfg = widget.wcfg
        assert widget.damage_wheel_color(False, 0.0).name().upper() == wcfg["damage_panel_suspension_color"]
        assert widget.damage_wheel_color(False, 0.5).name().upper() == wcfg["damage_panel_suspension_color_heavy"]
        assert widget.damage_wheel_color(False, 0.9).name().upper() == wcfg["damage_panel_suspension_color_totaled"]
        assert widget.damage_body_color(1).name().upper() == wcfg["damage_panel_body_color_light"]
        widget.body_damage = (2,) * 8
        assert widget.integrity() == 0.0
        widget.damage_aero = 0.25
        assert widget.integrity() == 0.75  # aero integrity when car reports it
    finally:
        widget.deleteLater()


def test_car_silhouette_removed(ui_env):
    from tinypedal.setting import cfg

    assert "show_car_silhouette" not in cfg.default.setting["black_box"]
    widget = new_widget()
    try:
        assert not hasattr(widget, "car") and not hasattr(widget, "draw_car_silhouette")
        widget.grab()
    finally:
        widget.deleteLater()


def test_damage_panel_modern_colors(ui_env):
    widget = new_widget()
    try:
        assert widget.damage_body_color(0).alpha() < 255  # intact body stays faint
        assert widget.damage_body_color(2).alpha() == 255
        assert widget.integrity_color(0.9) == widget.wcfg["damage_panel_suspension_color"]
        assert widget.integrity_color(0.5) == widget.wcfg["damage_panel_body_color_light"]
        assert widget.integrity_color(0.1) == widget.wcfg["damage_panel_body_color_heavy"]
        widget.damage_aero = 0.2
        assert widget.uses_aero_integrity()
        widget.body_damage = (3, 2, 1, 0, 0, 0, 0, 0)
        widget.damage_detached = (True, False, False, False)
        widget.damage_puncture = (False, True, False, False)
        widget.damage_suspension = (0.0, 0.1, 0.5, 0.9)
        widget.impact_visible = True
        widget.grab()  # every state drawn
    finally:
        widget.deleteLater()


# --- Fuel & energy gauges (like Fuel / Virtual Energy widget level bar)
def test_gauges_replace_refuel_rows(ui_env):
    from tinypedal.setting import cfg

    options = cfg.default.setting["black_box"]
    for key in ("show_refuel", "show_refill", "show_fuel_remaining", "show_energy_remaining", "text_refuel"):
        assert key not in options
    widget = new_widget({"show_stint_comparison": False})
    try:
        assert len(widget.bottom_rows) == 2  # one fuel gauge, one energy gauge
    finally:
        widget.deleteLater()


def test_gauge_data_and_low_warning(ui_env, monkeypatch):
    from tinypedal.module_info import minfo

    for name, value in (("capacity", 100.0), ("amountStart", 90.0), ("amountCurrent", 40.0),
                        ("neededRelative", 25.0), ("estimatedLaps", 8.0)):
        monkeypatch.setattr(minfo.fuel, name, value)
    widget = new_widget({"slow_data_update_interval": 0})
    try:
        widget.timerEvent(None)
        gauge = widget.fuel_gauge()
        assert (gauge.level, gauge.capacity, gauge.start, gauge.needed) == (40.0, 100.0, 90.0, 25.0)
        assert gauge.needed_text.startswith("+")
        assert not widget.gauge_low()
        widget.fuel_laps = 1.5
        assert widget.gauge_low() and widget.animating()  # low fuel pulses
        widget.grab()
        widget.fuel_capacity = 0.0  # no data yet: bar without fill, never divides by zero
        widget.grab()
    finally:
        widget.deleteLater()


def test_gauge_marks_positions(ui_env, monkeypatch):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from tinypedal.widget._black_box import panels

    widget = new_widget()
    try:
        marks = []
        original = QPainter.fillRect

        def record(painter, rect, color, *args):
            if isinstance(rect, QRectF) and rect.height() == 20 and rect.width() < 5:
                marks.append(round(rect.center().x()))
            return original(painter, rect, color, *args)

        monkeypatch.setattr(QPainter, "fillRect", record)
        image = QImage(220, 40, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        gauge = panels.Gauge(40.0, 100.0, 90.0, 25.0, 8.0, "40 L", "+25")
        widget.draw_level_gauge(painter, QRectF(10, 10, 200, 20), "Fuel", gauge, "#3D8BFF")
        painter.end()
        assert marks == [190, 140]  # start at 90%, refill at 40 + 25 = 65% of 200 px, from x 10
    finally:
        widget.deleteLater()


def test_old_rows_migrated_to_gauges():
    from tinypedal.setting_preupdate import preupdate_user_setting

    user = {"black_box": {"show_refuel": False, "show_fuel_remaining": True,
                          "show_refill": False, "show_energy_remaining": False}}
    preupdate_user_setting((2, 50, 0), user)
    assert user["black_box"]["show_fuel_gauge"] is True
    assert user["black_box"]["show_energy_gauge"] is False


def test_fuel_gauge_in_liters(ui_env):
    from tinypedal.setting import cfg

    cfg.units["fuel_unit"] = "Gallon"  # global unit ignored: widget default is liter
    try:
        widget = new_widget()
        try:
            widget.fuel, widget.refuel, widget.fuel_laps = 38.2, 12.4, 9.6
            gauge = widget.fuel_gauge()
            assert gauge.text.startswith("38.2 L") and gauge.needed_text == "+12.4 L"
        finally:
            widget.deleteLater()
    finally:
        cfg.units["fuel_unit"] = "Liter"


# --- Data module dependencies
def test_required_modules_follow_options():
    from tinypedal.widget._black_box.modules import required_modules

    assert required_modules({}) == ()
    assert required_modules({"show_delta_best": True, "show_fuel_gauge": True}) == ("module_fuel", "module_delta")
    assert "module_wheels" in required_modules({"show_slip_warning": True})


def test_module_status_refresh_and_notice():
    from tinypedal.widget._black_box.modules import ModuleStatus

    settings = {"module_wheels": {"enable": True}, "module_fuel": {"enable": False}}
    status = ModuleStatus(settings, ("module_wheels", "module_fuel"))
    assert status.ready("module_wheels") and not status.ready("module_fuel")
    assert status.ready("module_delta")  # not required: never reported
    assert status.missing_text() == "Fuel module off"
    version = status.version
    assert not status.refresh()  # nothing changed
    settings["module_wheels"]["enable"] = False
    assert status.refresh() and status.version == version + 1
    assert status.missing_text() == "Wheels, Fuel modules off"


def test_disabled_module_data_not_read_and_cleared(ui_env, monkeypatch):
    from tinypedal.module_info import minfo
    from tinypedal.setting import cfg

    monkeypatch.setattr(minfo.fuel, "amountCurrent", 42.0)
    monkeypatch.setattr(minfo.delta, "deltaBest", -0.5)
    widget = new_widget({"show_delta_best": True, "slow_data_update_interval": 0})
    try:
        widget.timerEvent(None)
        assert widget.fuel == 42.0 and widget.delta_best == -0.5
        cfg.user.setting["module_fuel"]["enable"] = False
        cfg.user.setting["module_delta"]["enable"] = False
        widget.tick = 0  # next update checks module state
        widget.timerEvent(None)
        assert not widget.use_fuel and not widget.use_delta
        assert widget.fuel == 0.0 and widget.delta_best == 0.0  # cleared, never frozen
        assert widget.modules.missing_text() == "Fuel, Delta modules off"
        widget.grab()  # notice drawn
        cfg.user.setting["module_fuel"]["enable"] = True  # turned back on: picked up
        widget.tick = 0
        widget.timerEvent(None)
        assert widget.use_fuel and widget.fuel == 42.0
    finally:
        widget.deleteLater()


def test_enable_required_modules(ui_env, monkeypatch):
    from tinypedal import module_control
    from tinypedal.setting import cfg

    started = []
    monkeypatch.setattr(module_control.ModuleControl, "start", lambda self, name="": started.append(name))
    cfg.user.setting["module_wheels"]["enable"] = False
    widget = new_widget({"enable_required_modules": True})
    try:
        assert started == ["module_wheels"]
        assert cfg.user.setting["module_wheels"]["enable"] is True
        assert not widget.modules.missing
    finally:
        widget.deleteLater()


def test_gauge_survives_non_finite_module_data(ui_env):
    import math

    widget = new_widget()
    try:
        for value in (math.nan, math.inf, -math.inf):
            widget.fuel = widget.fuel_capacity = widget.fuel_start = widget.refuel = value
            widget.grab()  # must not abort Qt
    finally:
        widget.deleteLater()


# --- Dynamic size
def test_debounce_applies_stable_value_only():
    from tinypedal.widget._black_box.sizing import Debounce

    debounce = Debounce("a", delay=2.0)
    assert debounce.update("b", 0.0) == "a"
    assert debounce.update("c", 1.0) == "a"  # new candidate restarts waiting
    assert debounce.update("c", 2.5) == "a"
    assert debounce.update("c", 3.0) == "c"
    assert debounce.update("c", 3.1) == "c"
    assert Debounce("a", 0).update("b", 0.0) == "b"


def test_fit_content():
    from tinypedal.widget._black_box.sizing import fit_content

    assert fit_content(200, 100) == (200, 100, 1.0, 0.0, 0.0)
    both = fit_content(200, 100, 400, 400)
    assert (both.width, both.height, both.scale) == (400, 400, 2.0)
    assert both.offset_x == 0 and both.offset_y == 100  # centered vertically
    width_only = fit_content(200, 100, 100, 0)
    assert (width_only.width, width_only.height, width_only.scale) == (100, 50, 0.5)
    assert fit_content(200, 100, float("nan"), -5).scale == 1.0  # invalid: follow content


def test_anchored_position():
    from tinypedal.widget._black_box.sizing import anchored_position

    assert anchored_position(100, 100, 300, 200, 300, 150, "Top Left") == (100, 100)
    assert anchored_position(100, 100, 300, 200, 250, 150, "Bottom Right") == (150, 150)
    assert anchored_position(100, 100, 300, 200, 200, 200, "Top Center") == (150, 100)


def test_auto_resize_starts_compact_and_grows_with_data(ui_env, monkeypatch):
    from tinypedal.module_info import minfo
    from tinypedal.widget._black_box import reader

    clock = [0.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    widget = new_widget({"enable_auto_resize": True, "slow_data_update_interval": 0, "resize_delay": 1.0,
                         "show_battery_bar": True, "show_damage_panel": False})
    try:
        compact_h, compact_w = widget.height(), widget.width()
        assert not widget.row_energy and not widget.row_battery  # nothing empty before data
        monkeypatch.setattr(minfo.energy, "available", True)
        monkeypatch.setattr(minfo.hybrid, "batteryCharge", 60.0)
        widget.timerEvent(None)  # data arrived: waits for delay
        assert widget.height() == compact_h
        clock[0] = 1.5
        widget.timerEvent(None)
        assert widget.row_energy and widget.row_battery
        assert widget.height() > compact_h and widget.width() > compact_w
        monkeypatch.setattr(minfo.energy, "available", False)  # other car: shrinks again
        clock[0] = 2.0
        widget.timerEvent(None)
        clock[0] = 3.5
        widget.timerEvent(None)
        assert not widget.row_energy
        widget.grab()
    finally:
        widget.deleteLater()


def test_stint_row_appears_with_data(ui_env):
    from tinypedal.widget._black_box.sizing import Presence

    widget = new_widget({"enable_auto_resize": True, "show_stint_comparison": True})
    try:
        assert not widget.row_stint
        widget.stint_wear = 1.2
        assert widget.current_presence().stint
        widget.relayout(widget.current_presence())
        assert widget.row_stint
        widget.relayout(Presence(stint=False))
        assert not widget.row_stint
    finally:
        widget.deleteLater()


def test_auto_resize_disabled_keeps_size(ui_env, monkeypatch):
    from tinypedal.widget._black_box import reader

    clock = [0.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    widget = new_widget({"enable_auto_resize": False, "slow_data_update_interval": 0, "resize_delay": 0})
    try:
        size = widget.size()
        clock[0] = 10.0
        widget.timerEvent(None)
        assert widget.size() == size and widget.row_energy
    finally:
        widget.deleteLater()


def test_fixed_size_scales_content(ui_env):
    widget = new_widget({"fixed_width": 300, "fixed_height": 300})
    try:
        assert (widget.width(), widget.height()) == (300, 300)
        natural = widget.car_layout
        assert widget.fit.scale == pytest.approx(min(300 / natural.width, 300 / natural.height))
        widget.grab()
    finally:
        widget.deleteLater()


def test_block_scales_change_geometry(ui_env):
    base = new_widget({"show_damage_panel": False})  # rows would stretch to panel height
    tyre, row = base.rects_tyre[0].height(), base.bottom_rows[0][0].height()
    base.deleteLater()
    widget = new_widget({"tyre_scale": 1.5, "gauge_row_scale": 2.0, "center_column_scale": 1.5})
    try:
        assert widget.rects_tyre[0].height() == pytest.approx(tyre * 1.5, abs=1)
        assert widget.bottom_rows[0][0].height() == pytest.approx(row * 2, abs=1)
        widget.grab()
    finally:
        widget.deleteLater()


def test_resize_keeps_anchor(ui_env):
    widget = new_widget({"resize_anchor": "Bottom Right", "enable_auto_resize": True})
    try:
        widget.show()
        widget.move(500, 400)
        right, bottom = widget.x() + widget.width(), widget.y() + widget.height()
        from tinypedal.widget._black_box.sizing import Presence

        widget.relayout(Presence(energy_row=False, battery=False, abs=False, tc=False))
        assert widget.x() + widget.width() == right
        assert widget.y() + widget.height() == bottom
    finally:
        widget.close()
        widget.deleteLater()


def test_gear_speed_cluster_fills_center_column(ui_env, monkeypatch):
    widget = new_widget()
    try:
        assert "speed" not in widget.center_order  # drawn inside gear block
        drawn = {}
        monkeypatch.setattr(widget, "draw_center_item", lambda painter, name, rect: drawn.__setitem__(name, rect))
        widget.draw_center(None, widget.rect_center)
        bottom = max(rect.bottom() for rect in drawn.values())
        assert bottom == pytest.approx(widget.rect_center.bottom(), abs=0.5)  # no empty room left
        assert drawn["gear"].height() > widget.item_height("gear")  # gear block took free room
    finally:
        widget.deleteLater()


def test_gear_speed_cluster_can_be_split(ui_env):
    widget = new_widget({"show_gear_speed_cluster": False})
    try:
        assert "speed" in widget.center_order
        widget.grab()
    finally:
        widget.deleteLater()


def test_damage_panel_outside_bottom_right(ui_env):
    """Own column on the outside right, flush with the widget bottom right corner"""
    widget = new_widget({"show_stint_comparison": True})
    try:
        panel = widget.rect_damage
        assert panel.right() == pytest.approx(widget.width(), abs=1)
        assert panel.bottom() == pytest.approx(widget.height(), abs=1)
        content_right = max(rect.right() for rect in widget.rects_tyre)
        assert panel.left() > content_right  # outside the car view
        for _left, right in widget.bottom_rows:
            assert right.right() < panel.left()  # rows keep full content width, beside panel column
    finally:
        widget.deleteLater()


def test_damage_panel_can_be_hidden(ui_env):
    with_panel = new_widget()
    width = with_panel.width()
    with_panel.deleteLater()
    widget = new_widget({"show_damage_panel": False})
    try:
        assert widget.rect_damage.isNull()
        assert widget.width() < width  # no empty column left
    finally:
        widget.deleteLater()


def test_no_background_above_damage_panel(ui_env):
    widget = new_widget()
    try:
        panel = widget.rect_damage
        above = panel.center() - panel.center()  # origin, reused as point type
        above.setX(panel.center().x())
        above.setY(panel.top() - widget.unit)
        assert not widget.path_bg.contains(above)  # transparent above the panel
        assert widget.path_bg.contains(panel.center())  # tab under the panel
        # grab() has no alpha: unpainted room shows window color, never widget background
        image = widget.grab().toImage()
        background = widget.wcfg["background_color"].upper()
        assert image.pixelColor(int(above.x()), int(above.y())).name().upper() != background
        assert image.pixelColor(1, widget.height() // 2).name().upper() == background  # main area painted
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("corner", ["Bottom Right", "Bottom Left", "Top Right", "Top Left"])
def test_damage_panel_any_corner(ui_env, corner):
    widget = new_widget({"damage_panel_position": corner})
    try:
        panel = widget.rect_damage
        width, height = widget.width(), widget.height()
        if corner.endswith("Left"):
            assert panel.left() == 0
            assert panel.right() < min(rect.left() for rect in widget.rects_tyre)  # outside main area
        else:
            assert panel.right() == pytest.approx(width, abs=1)
            assert panel.left() > max(rect.right() for rect in widget.rects_tyre)
        if corner.startswith("Top"):
            assert panel.top() == 0
        else:
            assert panel.bottom() == pytest.approx(height, abs=1)
        assert widget.path_bg.contains(panel.center())  # same background as widget
        widget.grab()
    finally:
        widget.deleteLater()


def test_damage_panel_car_shape():
    from PySide6.QtCore import QRectF

    from tinypedal.widget._black_box.damage import damage_geometry

    rect = QRectF(0, 0, 80, 100)
    shapes = damage_geometry(rect, 16)
    body = shapes.shell.boundingRect()
    for wheel in shapes.wheels:  # wheels stick out beside the body
        assert wheel.right() <= body.left() + 0.5 or wheel.left() >= body.right() - 0.5
    assert shapes.integrity.width() > rect.width() * 0.25  # readable reading in the middle


def test_damage_panel_card_against_widget(ui_env):
    """Own card, right against the black box card: no gap, not merged"""
    widget = new_widget()
    try:
        panel, main = widget.rect_damage, widget.rect_main
        assert panel.left() == pytest.approx(main.right(), abs=0.5)  # touching
        assert widget.path_bg.contains(panel.center()) and widget.path_bg.contains(main.center())
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("corner", ["Bottom Right", "Top Left"])
def test_centering_ignores_damage_panel(ui_env, corner):
    widget = new_widget({"damage_panel_position": corner})
    try:
        area = widget.centering_rect()
        assert area.width() == pytest.approx(widget.width() - widget.rect_damage.width(), abs=1)
        if corner.endswith("Left"):
            assert area.x() == pytest.approx(widget.rect_damage.width(), abs=1)
        else:
            assert area.x() == 0
    finally:
        widget.deleteLater()


def test_center_action_uses_centering_rect(ui_env, monkeypatch):
    """Base overlay: centered part is centering_rect, whole widget by default"""
    from PySide6.QtCore import QRect

    widget = new_widget()
    try:
        screen_w = widget.screen().geometry().width()
        area = widget.centering_rect()
        widget.move((screen_w - area.width()) // 2 - area.x(), 0)
        assert widget.x() + area.x() + area.width() // 2 == pytest.approx(screen_w // 2, abs=1)
        from tinypedal.widget._base import Overlay

        assert Overlay.centering_rect(widget) == QRect(0, 0, widget.width(), widget.height())
    finally:
        widget.deleteLater()
