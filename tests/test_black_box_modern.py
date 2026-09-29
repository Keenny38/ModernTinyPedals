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
    assert incident.peak_g > 15  # 40 m/s to 0, measured over the 150 ms window (2 samples here)
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
    monkeypatch.setattr(reader, "export_incident", lambda incident, folder, export_format="JSON": saved.append(folder))
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
                         "smooth_transition_duration": 0, "alert_pulse_frequency": 0})
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
    assert "module_wheels" in required_modules({"show_suspension": True})  # range, static, motion ratio


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


# --- Suspension (coilover beside brakes)
def test_suspension_travel_uses_module_range():
    from tinypedal.widget._black_box.state import DAMPER_FILTER_TIME, SuspensionTravel

    travel = SuspensionTravel()
    assert travel.update(50.0, 0.0, 20.0, 80.0) == (0.5, 0.0)  # first sample: no speed yet
    position, velocity = travel.update(60.0, 0.1, 20.0, 80.0)  # 10 mm in 0.1 s = 100 mm/s
    assert position == pytest.approx(40 / 60)
    assert velocity == pytest.approx(100 * (1 - math.exp(-0.1 / DAMPER_FILTER_TIME)))  # smoothed, mm/s
    for step in range(2, 12):  # steady 100 mm/s: filter settles on it
        velocity = travel.update(60.0 + (step - 1) * 10, step / 10, 20.0, 400.0)[1]
    assert velocity == pytest.approx(100, rel=0.01)
    assert travel.update(0.0, 5.0, 20.0, 80.0)[1] == 0.0  # long gap (pause): no speed
    assert travel.update(200.0, 5.1, 20.0, 80.0)[0] == 1.0  # clamped at end of range
    assert travel.ratio(35.0, 20.0, 80.0) == pytest.approx(0.25)


def test_damper_speed_tint_has_low_and_high_speed_zones():
    from tinypedal.widget._black_box.state import LOW_SPEED_TINT, damper_tint

    assert damper_tint(0.0, 50, 150) == 0.0
    assert damper_tint(25.0, 50, 150) == pytest.approx(LOW_SPEED_TINT / 2)  # body motion: light tint
    assert damper_tint(-50.0, 50, 150) == pytest.approx(LOW_SPEED_TINT)  # knee, rebound same as bump
    assert damper_tint(100.0, 50, 150) == pytest.approx(LOW_SPEED_TINT + (1 - LOW_SPEED_TINT) / 2)
    assert damper_tint(900.0, 50, 150) == 1.0  # kerb strike: full color
    assert damper_tint(math.nan, 50, 150) == 0.0


def test_wheel_travel_from_motion_ratio():
    from tinypedal.widget._black_box.state import wheel_offset

    assert wheel_offset(10.0, 0.5) == pytest.approx(20.0)  # pushrod: wheel moves twice the spring
    assert wheel_offset(10.0, 0.0) == 10.0  # ratio not learned yet: spring travel
    assert wheel_offset(10.0, 50.0) == 10.0  # implausible ratio ignored


def test_bump_stop_from_force_above_spring_line():
    from tinypedal.widget._black_box.state import BUMP_MIN_SAMPLES, BumpStop

    bump = BumpStop()
    rate, preload = 100.0, 1000.0  # N/mm, N
    bump.update(50.0, preload + rate * 50, 10.0, 50.0, 0.3)  # travel seen up to 50 mm
    for step in range(BUMP_MIN_SAMPLES * 3):  # slow motion over 0 to 29 mm: pure spring
        position = step % 30
        assert not bump.update(position, preload + rate * position, 10.0, 50.0, 0.3)
    line = bump.line()
    assert line == pytest.approx((preload, rate))
    assert not bump.update(45.0, preload + rate * 45, 10.0, 50.0, 0.3)  # deep but on the spring line
    assert bump.update(45.0, (preload + rate * 45) * 1.6, 10.0, 50.0, 0.3)  # bump rubber loaded
    assert not bump.update(45.0, (preload + rate * 45) * 1.6, 400.0, 50.0, 0.3)  # damper force: not judged
    assert not bump.update(10.0, (preload + rate * 10) * 1.6, 10.0, 50.0, 0.3)  # low in travel: never bump
    bump.reset()
    assert bump.line() is None and not bump.update(45.0, 9000.0, 0.0, 50.0, 0.3)


def test_suspension_travel_learns_range_without_module():
    import math

    from tinypedal.widget._black_box.state import SuspensionTravel

    travel = SuspensionTravel()
    assert travel.update(40.0, 0.0)[0] == 0.5  # no range yet
    travel.update(20.0, 0.1)
    travel.update(60.0, 0.2)
    assert travel.update(30.0, 0.3)[0] == pytest.approx(0.25)
    assert travel.update(math.nan, 0.4) == (0.0, 0.0)
    travel.reset()
    assert travel.ratio(30.0) == -1.0  # unknown after car change


def test_suspension_beside_brake_bar(ui_env):
    widget = new_widget()
    try:
        for index, (susp, disc) in enumerate(zip(widget.rects_susp, widget.rects_disc)):
            assert not susp.isNull()
            assert disc.left() <= susp.left() and susp.right() <= disc.right()  # inside brake column
            if index % 2:  # right side: bar next to tyre on the right, spring just left of it
                assert susp.right() < disc.right() - widget.brake_bar_w + 0.5
            else:
                assert susp.left() > disc.left() + widget.brake_bar_w - 0.5
    finally:
        widget.deleteLater()


def test_suspension_hidden_frees_room(ui_env):
    shown = new_widget()
    width = shown.width()
    shown.deleteLater()
    widget = new_widget({"show_suspension": False})
    try:
        assert widget.width() < width and widget.rects_susp[0].isNull()
        widget.grab()
    finally:
        widget.deleteLater()


def test_suspension_live_and_dynamic(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.module_info import minfo
    from tinypedal.widget._black_box import reader

    clock = [0.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    monkeypatch.setattr(minfo.wheels, "minSuspensionPosition", [20.0] * 4)
    monkeypatch.setattr(minfo.wheels, "maxSuspensionPosition", [80.0] * 4)
    monkeypatch.setattr(minfo.wheels, "staticSuspensionPosition", [40.0] * 4)
    monkeypatch.setattr(minfo.wheels, "motionRatio", [0.5, 0.5, 1.0, 0.0])
    positions = [(50.0, 50.0, 50.0, 50.0)]
    loads = [(3000.0, 3000.0, 3000.0, 3000.0)]
    monkeypatch.setattr(api.read.wheel, "suspension_deflection", lambda: positions[0])
    monkeypatch.setattr(api.read.wheel, "suspension_force", lambda: (4000.0,) * 4, raising=False)
    monkeypatch.setattr(api.read.tyre, "load", lambda: loads[0], raising=False)
    monkeypatch.setattr(api.read.vehicle, "speed", lambda: 40.0)
    widget = new_widget()
    try:
        widget.alert_pulse = True
        widget.timerEvent(None)
        front_left = widget.wheels[0]
        assert front_left.susp_travel == pytest.approx(0.5)
        assert front_left.susp_static == pytest.approx(1 / 3)
        assert front_left.susp_offset == pytest.approx(10.0)  # spring 10 mm compressed
        assert front_left.susp_wheel_offset == pytest.approx(20.0)  # wheel: 10 mm / 0.5 motion ratio
        assert not front_left.susp_estimated  # static position from Wheels module
        positions[0] = (79.0, 50.0, 30.0, 50.0)
        loads[0] = (3000.0, 0.0, 3000.0, 3000.0)  # front right in the air
        clock[0] = 0.05
        widget.timerEvent(None)
        front_left, front_right, rear_left, _ = widget.wheels
        assert front_left.susp_velocity > 0 and rear_left.susp_velocity < 0
        assert front_right.susp_airborne and not front_left.susp_airborne
        assert not front_left.susp_bump  # deep in travel, but no force rise: not a bump stop
        assert widget.animating()  # airborne wheel pulses
        airborne = widget.spring_color(front_right)
        assert widget.spring_color(rear_left) != airborne
        widget.grab()
    finally:
        widget.deleteLater()


def test_spring_shortens_when_compressed():
    from tinypedal.widget._black_box.suspension import spring_length

    assert spring_length(100, 0) == 100
    assert spring_length(100, 1) == pytest.approx(20)
    assert spring_length(100, 5) == pytest.approx(20)  # clamped


def test_suspension_offset_is_real_millimeters():
    from tinypedal.widget._black_box.state import SuspensionTravel

    travel = SuspensionTravel()
    assert travel.offset(62.0, 50.0) == pytest.approx(12.0)  # 12 mm compressed from static
    assert travel.offset(45.0, 50.0) == pytest.approx(-5.0)  # 5 mm extended
    unknown = SuspensionTravel()
    assert unknown.offset(40.0) == 0.0  # no static: first position taken as rest position
    assert unknown.offset(50.0) == pytest.approx(10.0, abs=0.1)


def test_suspension_moves_one_to_one_with_tyre_scale(ui_env):
    from tinypedal.widget._black_box.suspension import TYRE_DIAMETER_MM, spring_length_real

    widget = new_widget()
    try:
        tyre_h = widget.rects_tyre[0].height()
        assert widget.susp_pixels_per_mm == pytest.approx(tyre_h / TYRE_DIAMETER_MM)
        full = 100.0
        rest = spring_length_real(full, 0, widget.susp_pixels_per_mm)
        moved = spring_length_real(full, 20, widget.susp_pixels_per_mm)  # 20 mm compression
        assert rest - moved == pytest.approx(20 * tyre_h / TYRE_DIAMETER_MM)
    finally:
        widget.deleteLater()
    magnified = new_widget({"suspension_motion_scale": 4.0})
    try:
        assert magnified.susp_pixels_per_mm == pytest.approx(4 * tyre_h / TYRE_DIAMETER_MM)
    finally:
        magnified.deleteLater()


def test_suspension_turns_with_wheel(ui_env, monkeypatch):
    """Anchored to its wheel: same rotation around tyre center as tyre & disc"""
    from PySide6.QtGui import QImage, QPainter

    widget = new_widget()
    try:
        rotations = []
        original = QPainter.rotate
        monkeypatch.setattr(QPainter, "rotate", lambda painter, angle: (rotations.append(angle),
                                                                         original(painter, angle))[1])
        wheel = widget.wheels[0]
        wheel.steer = 12.0
        image = QImage(widget.size(), QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        widget.draw_suspension(painter, widget.rects_susp[0], wheel, 0)
        painter.end()
        assert rotations == [12.0]
        rotations.clear()
        wheel.steer = 0.0
        painter = QPainter(image)
        widget.draw_suspension(painter, widget.rects_susp[0], wheel, 0)
        painter.end()
        assert rotations == []  # straight: no rotation
    finally:
        widget.deleteLater()


def test_tyre_and_disc_move_with_suspension(ui_env, monkeypatch):
    """Tyre & disc move by the real wheel travel (not spring travel), 1:1"""
    from tinypedal.widget._black_box.suspension import TYRE_DIAMETER_MM

    widget = new_widget()
    try:
        wheel = widget.wheels[0]
        assert widget.wheel_shift(0, wheel) == 0.0  # static position
        wheel.susp_offset = 5.0  # spring 5 mm...
        wheel.susp_wheel_offset = 10.0  # ...wheel 10 mm compressed: goes up by wheel travel
        expected = -10 * widget.rects_tyre[0].height() / TYRE_DIAMETER_MM
        assert widget.wheel_shift(0, wheel) == pytest.approx(expected)
        wheel.susp_wheel_offset = -10.0  # droop: goes down
        assert widget.wheel_shift(0, wheel) == pytest.approx(-expected)
        wheel.susp_wheel_offset = 10.0
        shifts = []
        monkeypatch.setattr(widget, "draw_tyre", lambda painter, *args: shifts.append(painter.transform().dy()))
        widget.grab()
        assert shifts and shifts[0] == pytest.approx(expected)
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("overrides", [{"enable_wheel_suspension_motion": False}, {"show_suspension": False}])
def test_wheels_fixed_when_motion_off(ui_env, overrides):
    widget = new_widget(overrides)
    try:
        widget.wheels[0].susp_offset = widget.wheels[0].susp_wheel_offset = 30.0
        assert widget.wheel_shift(0, widget.wheels[0]) == 0.0
    finally:
        widget.deleteLater()


def test_wheel_mount_at_tyre_center(ui_env):
    """At static position, the suspension wheel mount is at the tyre (hub) & disc center"""
    from tinypedal.widget._black_box.suspension import STATIC_LENGTH, spring_frame

    widget = new_widget()
    try:
        for index in range(4):
            _, top, full = spring_frame(widget.rects_susp[index])
            mount_y = top + full * STATIC_LENGTH
            assert mount_y == pytest.approx(widget.rects_tyre[index].center().y(), abs=0.5)
            assert mount_y == pytest.approx(widget.rects_disc[index].center().y(), abs=0.5)
    finally:
        widget.deleteLater()


# --- Realistic dynamics: recorder, brakes by class, tyre temperature source, slip
def test_game_impact_triggers_incident():
    recorder = Recorder(duration=5.0, sample_interval=0.05, deceleration_threshold=4.0, post_trigger=0.5)
    recorder.add(sample(0.0, 40.0), 0.0)
    recorder.add(sample(0.05, 39.9), 0.0, impact=True)  # light contact: no speed drop, game reports it
    assert recorder.pending is not None and recorder.pending[1] == "impact"


def test_braking_noise_is_not_an_impact():
    """Hypercar braking at 3.5 g with a noisy 20 ms step (one step alone reads over 4 g)"""
    recorder = Recorder(duration=5.0, sample_interval=0.02, deceleration_threshold=4.0)
    speed, time = 80.0, 0.0
    for step in range(100):
        time += 0.02
        drop = 3.5 * rec.GRAVITY * 0.02 * (1.4 if step % 2 else 0.6)  # jitter around 3.5 g
        speed -= drop
        recorder.add(sample(time, speed), 0.0)
    assert recorder.pending is None and not recorder.incidents


def test_recorder_uses_game_impact_time(ui_env, monkeypatch):
    from tinypedal.api_control import api

    impact = [10.0]
    monkeypatch.setattr(api.read.vehicle, "impact_time", lambda: impact[0])
    widget = new_widget({"show_incident_recorder": True})
    try:
        widget.update_recorder(30.0)  # impact before widget started: ignored
        assert widget.recorder.pending is None
        impact[0] = 55.0
        widget.recorder.samples[-1] = widget.recorder.samples[-1]._replace(time=-1.0)  # next sample not skipped
        widget.update_recorder(30.0)
        assert widget.recorder.pending is not None and widget.recorder.pending[1] == "impact"
    finally:
        widget.deleteLater()


def test_brake_window_by_car_class(ui_env):
    from tinypedal.widget._black_box.state import class_target, parse_class_targets

    targets = parse_class_targets("Hypercar=400-950; GT3=250-650; LMGT3=260-640; broken")
    assert class_target(targets, "LMGT3") == (260.0, 640.0)  # longest name wins
    assert class_target(targets, "hypercar") == (400.0, 950.0)
    assert class_target(targets, "GTE") is None
    widget = new_widget({"brake_temperature_cold_threshold": 100, "brake_temperature_hot_threshold": 500})
    try:
        widget.update_brake_window("Hypercar")
        assert (widget.brake_cold, widget.brake_hot) == (400, 950)  # carbon disc window
        widget.update_brake_window("GT3")
        assert (widget.brake_cold, widget.brake_hot) == (250, 650)  # iron disc window
        widget.update_brake_window("Unknown class")
        assert (widget.brake_cold, widget.brake_hot) == (100, 500)  # fallback thresholds
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("source, reader", [
    ("Inner layer", "inner_temperature_avg"), ("Carcass", "carcass_temperature"),
    ("Surface", "surface_temperature_avg"),
])
def test_tyre_temperature_source(ui_env, monkeypatch, source, reader):
    from tinypedal.api_control import api

    for name in ("inner_temperature_avg", "carcass_temperature", "surface_temperature_avg"):
        value = 95.0 if name == reader else 40.0
        monkeypatch.setattr(api.read.tyre, name, lambda value=value: (value,) * 4, raising=False)
    widget = new_widget({"tyre_temperature_source": source})
    try:
        assert widget.read_tyre_temperature() == (95.0,) * 4
    finally:
        widget.deleteLater()


def test_slip_ratio_against_each_wheel_ground_speed():
    from tinypedal.module.module_wheels import wheel_ground_speed

    assert wheel_ground_speed(-31.0, 30.0) == 31.0  # outer wheel in a corner, sign of game axis dropped
    assert wheel_ground_speed(0.0, 30.0) == 30.0  # not reported: vehicle speed
    assert wheel_ground_speed(math.nan, 30.0) == 30.0


# --- Steering convention, slip levels, load, brake trend, tyre size, estimated rest position
@pytest.mark.parametrize("front_left, front_right, mirrored, inverted", [
    (12.0, 10.0, False, False),  # vehicle frame, positive right: as is
    (12.0, -10.0, True, False),  # toe-in per wheel: right side flipped
    (-12.0, -10.0, False, True),  # vehicle frame, positive left: all flipped
    (-12.0, 10.0, True, True),
])
def test_steer_convention_learned_from_steering(front_left, front_right, mirrored, inverted):
    from tinypedal.widget._black_box.state import STEER_VOTES, SteerConvention

    convention = SteerConvention()
    convention.update(front_left, front_right, 0.5)
    assert convention.screen_angle(1, front_right) == front_right  # not settled yet: game angle
    for _ in range(STEER_VOTES):
        convention.update(front_left, front_right, 0.5)  # steering right
        convention.update(0.3, 0.3, 0.0)  # straight: static toe, no vote
    assert (convention.mirrored, convention.inverted) == (mirrored, inverted)
    assert convention.screen_angle(0, front_left) > 0 and convention.screen_angle(1, front_right) > 0
    convention.reset()
    assert not convention.mirrored and not convention.inverted


def test_slip_past_peak_and_locked_wheel(ui_env):
    widget = new_widget({"wheel_lock_threshold": 0.15, "wheel_locked_threshold": 0.8})
    try:
        assert widget.slip_warning(-0.1, 30.0, True) == ""  # around peak grip
        assert widget.slip_warning(-0.3, 30.0, True) == "lock"  # past peak
        assert widget.slip_warning(-0.95, 30.0, True) == "locked"  # wheel stopped
        assert widget.slip_warning(0.3, 30.0, False) == "spin"
        widget.wheels[0].warning = "locked"
        widget.grab()
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("display, text", [("Percent", "25%"), ("Kilogram", "408"), ("Newton", "4000")])
def test_tyre_load_display(ui_env, display, text):
    widget = new_widget({"tyre_load_display": display})
    try:
        wheel = widget.wheels[0]
        wheel.load, wheel.load_ratio = 4000.0, 25.0
        assert widget.format_load(wheel) == text
    finally:
        widget.deleteLater()


def test_brake_temperature_trend(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.widget._black_box import reader

    clock = [0.0]
    temps = [300.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api.read.brake, "temperature", lambda: (temps[0],) * 4)
    widget = new_widget({"show_brake_temperature_trend": True, "slow_data_update_interval": 0})
    try:
        for step in range(30):  # braking zone: +200 C per second
            clock[0] = step * 0.1
            temps[0] = 300.0 + step * 20
            widget.timerEvent(None)
        assert widget.wheels[0].brake_trend == 1
        widget.grab()
    finally:
        widget.deleteLater()


def test_tyre_diameter_from_wheel_radius(ui_env):
    from tinypedal.widget._black_box.suspension import TYRE_DIAMETER_MM

    widget = new_widget()
    try:
        base = widget.susp_pixels_per_mm
        widget.update_tyre_diameters([0.355, 0.355, 0.0, 9.0])  # hypercar front, rear not learned
        assert widget.tyre_diameters == (710, 710, TYRE_DIAMETER_MM, TYRE_DIAMETER_MM)
        assert widget.pixels_per_mm(0) == pytest.approx(base * TYRE_DIAMETER_MM / 710)
        assert widget.pixels_per_mm(2) == pytest.approx(base)
    finally:
        widget.deleteLater()


def test_estimated_rest_position_flagged():
    from tinypedal.widget._black_box.state import SuspensionTravel

    travel = SuspensionTravel()
    travel.offset(40.0)
    assert travel.estimated  # no static position: averaged
    travel.offset(40.0, 38.0)
    assert not travel.estimated


def test_vehicle_name_read_with_slow_data_only(ui_env, monkeypatch):
    from tinypedal.api_control import api

    calls = []
    monkeypatch.setattr(api.read.vehicle, "vehicle_name", lambda: calls.append(1) or "car")
    widget = new_widget({"slow_data_update_interval": 1000, "update_interval": 20})
    try:
        for _ in range(10):
            widget.timerEvent(None)
        assert len(calls) == 1  # 10 updates, one slow update
    finally:
        widget.deleteLater()


# --- Bug fixes: new session impact, slip before radius is known
def test_new_session_impact_time_is_not_an_impact(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.widget._black_box.reader import is_new_impact

    assert is_new_impact(55.0, 10.0)
    assert not is_new_impact(0.0, 120.0)  # session restart: time stamp back to 0
    assert not is_new_impact(30.0, 120.0)  # new session, older stamp
    assert not is_new_impact(math.nan, 10.0)
    impact = [120.0]
    monkeypatch.setattr(api.read.vehicle, "impact_time", lambda: impact[0])
    widget = new_widget({"show_incident_recorder": True})
    try:
        widget.update_recorder(30.0)
        impact[0] = 0.0  # new session
        widget.recorder.samples[-1] = widget.recorder.samples[-1]._replace(time=-1.0)
        widget.update_recorder(30.0)
        assert widget.recorder.pending is None
        widget.update_damage_panel((0.0,) * 4)
        widget.update_damage_panel((0.0,) * 4)
        assert not widget.impact_visible
    finally:
        widget.deleteLater()


def test_no_slip_before_wheel_radius_is_known():
    from tinypedal import calculation as calc

    assert calc.slip_ratio(50.0, 0.0, 30.0) == 0  # radius not learned: not a locked wheel
    assert calc.slip_ratio(50.0, 0.33, 30.0) == pytest.approx(50 * 0.33 / 30 - 1)


def test_wheel_mount_moves_with_tyre(ui_env):
    """Spring wheel mount and tyre move by the same wheel travel: the corner stays in one piece"""
    from tinypedal.widget._black_box.suspension import STATIC_LENGTH, spring_frame, spring_length_real

    widget = new_widget()
    try:
        wheel = widget.wheels[0]
        wheel.susp_offset, wheel.susp_wheel_offset = 5.0, 12.0  # motion ratio about 0.4
        _, top, full = spring_frame(widget.rects_susp[0])
        mount_shift = top + spring_length_real(full, wheel.susp_wheel_offset, widget.pixels_per_mm(0)) - (
            top + full * STATIC_LENGTH)
        assert mount_shift == pytest.approx(widget.wheel_shift(0, wheel))
    finally:
        widget.deleteLater()


def test_suspension_damage_on_coilover(ui_env, monkeypatch):
    from tinypedal.api_control import api

    monkeypatch.setattr(api.read.wheel, "suspension_damage", lambda: (0.0, 0.2, 0.5, 0.95), raising=False)
    widget = new_widget({"show_damage_panel": False, "slow_data_update_interval": 0})
    try:
        widget.alert_pulse = True
        widget.timerEvent(None)
        intact, medium, heavy, totaled = widget.wheels
        assert [wheel.susp_damage for wheel in widget.wheels] == [0.0, 0.2, 0.5, 0.95]
        assert widget.suspension_damage_color(intact) is None
        assert widget.suspension_damage_color(medium) == widget.damage_wheel_color(False, 0.2)
        assert widget.suspension_damage_color(heavy) != widget.suspension_damage_color(medium)
        assert widget.suspension_totaled(totaled) and not widget.suspension_totaled(heavy)
        assert widget.animating()  # totaled suspension pulses
        widget.grab()
    finally:
        widget.deleteLater()
    hidden = new_widget({"show_coilover_damage": False})  # new name: old key hid removed suspension bars
    try:
        hidden.wheels[0].susp_damage = 0.95
        assert hidden.suspension_damage_color(hidden.wheels[0]) is None
        assert not hidden.suspension_totaled(hidden.wheels[0])
    finally:
        hidden.deleteLater()


# --- Tyres: camber spread, rear pressure window, pressure range, surface overheat, wear forecast
def test_camber_spread_inner_minus_outer():
    from tinypedal.widget._black_box.state import camber_spread

    # left / center / right of the car: inner side of a left wheel is on its right
    assert camber_spread(0, 80.0, 85.0, 90.0) == pytest.approx(10.0)  # FL inner hotter
    assert camber_spread(1, 90.0, 85.0, 80.0) == pytest.approx(10.0)  # FR inner (its left) hotter
    assert camber_spread(1, 80.0, 85.0, 90.0) == pytest.approx(-10.0)
    assert camber_spread(0, -273.0, 0.0, 90.0) == 0.0  # no data


def test_rear_pressure_window(ui_env):
    widget = new_widget({"tyre_pressure_target_rear_minimum": 170, "tyre_pressure_target_rear_maximum": 200,
                         "tyre_target_by_compound": "S=160-190; S:R=175-205"})
    try:
        assert widget.wheel_targets[0][:2] == (160, 190)
        assert widget.wheel_targets[2][:2] == (170, 200)  # rear default window
        assert widget.pressure_color(195, 2) == ""  # in rear window, high at front
        assert widget.pressure_color(195, 0) == widget.wcfg["tyre_pressure_high_color"]
        assert widget.compound_target("Soft", "S", rear=True)[:2] == (175, 205)  # compound rear entry
        assert widget.compound_target("Soft", "S")[:2] == (160, 190)
        assert widget.compound_target("Medium", "M", rear=True)[:2] == (170, 200)
    finally:
        widget.deleteLater()


def test_pressure_range_of_stint():
    from tinypedal.widget._black_box.state import PressureRange

    stint = PressureRange()
    for pressure in (170.0, 183.0, 0.0, 176.0, math.nan):
        stint.update(pressure)
    assert (stint.low, stint.high) == (170.0, 183.0)
    stint.reset()
    assert (stint.low, stint.high) == (0.0, 0.0)


def test_setup_readings_reach_wheels(ui_env, monkeypatch):
    from tinypedal.api_control import api

    monkeypatch.setattr(api.read.tyre, "surface_temperature_ico", lambda: (80.0, 85.0, 90.0) * 4, raising=False)
    monkeypatch.setattr(api.read.tyre, "surface_temperature_avg", lambda: (125.0,) * 4, raising=False)
    monkeypatch.setattr(api.read.tyre, "inner_temperature_avg", lambda: (95.0,) * 4, raising=False)
    monkeypatch.setattr(api.read.tyre, "pressure", lambda: (178.0,) * 4, raising=False)
    monkeypatch.setattr(api.read.wheel, "third_spring_deflection", lambda: (12.0, 12.0, 20.0, 20.0), raising=False)
    widget = new_widget({
        "show_tyre_camber_spread": True, "show_tyre_pressure_range": True, "show_third_spring": True,
        "tyre_temperature_warning_threshold": 110, "slow_data_update_interval": 0,
    })
    try:
        widget.timerEvent(None)
        front_left = widget.wheels[0]
        assert front_left.camber_spread == pytest.approx(10.0)
        assert front_left.surface_hot  # surface 125 over 110, rubber below 95
        assert (front_left.pressure_min, front_left.pressure_max) == (178.0, 178.0)
        assert front_left.heave == 12.0 and widget.wheels[2].heave == 20.0
        widget.grab()
    finally:
        widget.deleteLater()


def test_wear_forecast_laps_without_fuel_module(ui_env, monkeypatch):
    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.wheels, "currentTreadDepth", [8.0] * 4)
    monkeypatch.setattr(minfo.wheels, "estimatedValidTreadWear", [0.5] * 4)
    widget = new_widget({"tyre_wear_forecast_laps": 10.0, "slow_data_update_interval": 0})
    try:
        widget.use_fuel = False
        widget.timerEvent(None)
        assert widget.wheels[0].tread_end_known
    finally:
        widget.deleteLater()


# --- Brakes: peak per braking zone, laps left, imbalance, front / rear heat
def test_brake_peak_of_braking_zone():
    from tinypedal.widget._black_box.state import BrakePeak

    peak = BrakePeak()
    for temperature in (400.0, 650.0, 812.0, 790.0):
        peak.update(temperature, True)
    assert peak.update(700.0, False) == 812.0  # zone over: its peak kept
    assert peak.update(500.0, False) == 812.0
    peak.update(600.0, True)
    assert peak.update(550.0, False) == 600.0  # next zone


def test_brake_laps_left():
    from tinypedal.widget._black_box.state import brake_laps_left

    assert brake_laps_left(30.0, 20.0, 0.5) == pytest.approx(20.0)
    assert brake_laps_left(30.0, 20.0, 0.0) == -1.0  # wear per lap not measured yet
    assert brake_laps_left(19.0, 20.0, 0.5) == 0.0


def test_brake_imbalance_and_heat_balance(ui_env, monkeypatch):
    from tinypedal.api_control import api

    monkeypatch.setattr(api.read.brake, "temperature", lambda: (700.0, 450.0, 400.0, 420.0))
    widget = new_widget({"show_brake_heat_balance": True, "brake_imbalance_threshold": 150,
                         "slow_data_update_interval": 0})
    try:
        widget.timerEvent(None)
        front_left, front_right, rear_left, rear_right = widget.wheels
        assert front_left.brake_imbalance and front_right.brake_imbalance
        assert not rear_left.brake_imbalance and not rear_right.brake_imbalance
        assert widget.brake_heat_balance == pytest.approx(575.0 - 410.0)
        assert "brake_heat" in widget.center_order
        widget.grab()
    finally:
        widget.deleteLater()


# --- Suspension: lap statistics, damper histogram
def test_lap_stats_counts_and_resets():
    from tinypedal.widget._black_box.state import LapStats

    stats = LapStats()
    for ride in (30.0, 4.0, 3.0, 20.0, 2.0, 25.0):  # two dips under 5 mm
        stats.update_ride(ride, 5.0)
    assert (stats.ride_min, stats.bottoming) == (2.0, 2)
    for bump in (False, True, True, False, True):
        stats.update_bump(bump)
    assert stats.bumps == 2
    for travel in (0.4, 0.1, 0.9):
        stats.update_travel(travel)
    assert (stats.travel_min, stats.travel_max) == (0.1, 0.9)
    for velocity in (-200.0, -20.0, 20.0, 20.0):
        stats.update_damper(velocity, 0.1, 50.0)
    assert stats.damper_shares() == pytest.approx((0.25, 0.25, 0.5, 0.0))
    stats.reset()
    assert stats.bumps == 0 and stats.damper_shares() == (0.0,) * 4


def test_lap_stats_reset_on_new_lap(ui_env, monkeypatch):
    from tinypedal.api_control import api

    lap = [5]
    monkeypatch.setattr(api.read.lap, "number", lambda: lap[0])
    monkeypatch.setattr(api.read.wheel, "ride_height", lambda: (3.0,) * 4, raising=False)
    widget = new_widget({"show_ride_height_minimum": True, "show_suspension_lap_stats": True,
                         "show_damper_histogram": True})
    try:
        widget.timerEvent(None)
        assert widget.wheels[0].bottoming == 1 and widget.wheels[0].ride_height_min == 3.0
        lap[0] = 6
        monkeypatch.setattr(api.read.wheel, "ride_height", lambda: (30.0,) * 4, raising=False)
        widget.timerEvent(None)
        assert widget.wheels[0].bottoming == 0 and widget.wheels[0].ride_height_min == 30.0
        assert widget.row_damper
        widget.grab()
    finally:
        widget.deleteLater()


# --- Recorder: channels, CSV, damage threshold, browse, session, direction
def test_export_csv_and_json(tmp_path):
    incident = rec.Incident(10.0, "impact", 6.3, 4, 250.0, (
        Sample(9.9, 40.0, 1.0, 0.0, 5, False, False, "", 0.2, (0.01, 0.0, 0.03, 0.02), (4000, 4100, 4500, 4400)),
        Sample(10.0, 30.0, 0.0, 1.0, 5, True, False, "lock", -0.1),
    ), "↗")
    path = rec.export_incident(incident, str(tmp_path), "Both")
    assert path.endswith(".csv")
    with open(path, encoding="utf-8") as file:
        lines = file.read().splitlines()
    assert lines[0].startswith("time,speed_ms,throttle,brake,steering") and "load_n_rr" in lines[0]
    assert len(lines) == 3
    with open(path[:-4] + ".json", encoding="utf-8") as file:
        data = json.load(file)
    assert data["direction"] == "↗" and data["samples"][0]["slip_ratio_rl"] == 0.03


def test_small_damage_steps_not_logged():
    log = EventLog(5, damage_threshold=0.02)
    for damage in (0.005, 0.01, 0.015):  # creeping up on kerbs
        log.update(1, 10.0, ["", "", "", ""], damage, {})
    assert not log.events
    log.update(1, 11.0, ["", "", "", ""], 0.05, {})
    assert len(log.events) == 1
    recorder = Recorder(duration=5.0, sample_interval=0.05, damage_threshold=0.02)
    recorder.add(sample(0.0, 30.0), 0.0)
    recorder.add(sample(0.1, 30.0), 0.01)
    assert recorder.pending is None
    recorder.add(sample(0.2, 30.0), 0.05)
    assert recorder.pending is not None and recorder.pending[1] == "damage"


def test_impact_arrow_matches_damage_cone():
    from tinypedal.widget._black_box.state import impact_arrow

    assert impact_arrow(180.0) == "↑"  # cone drawn up: front
    assert impact_arrow(0.0) == "↓"  # rear
    assert impact_arrow(90.0) == "→"
    assert impact_arrow(math.nan) == ""


def test_browse_incidents_with_hotkey(ui_env, monkeypatch):
    from tinypedal.widget._black_box import reader
    from tinypedal.widget._black_box.recorder import request_next_incident

    clock = [100.0]
    monkeypatch.setattr(reader, "monotonic", lambda: clock[0])
    widget = new_widget({"show_incident_recorder": True, "incident_display_duration": 20})
    try:
        for index in range(3):
            widget.recorder.incidents.append(rec.Incident(float(index), "impact", 5.0, index, 0.0, (
                sample(float(index), 30.0), sample(index + 0.5, 10.0))))
        assert widget.displayed_incident() is None  # last one too old: live trace
        request_next_incident()
        widget.timerEvent(None)
        assert widget.displayed_incident().lap == 2  # newest first
        request_next_incident()
        widget.timerEvent(None)
        assert widget.displayed_incident().lap == 1
        widget.grab()
        clock[0] += 25
        assert widget.displayed_incident() is None  # back to live after display duration
    finally:
        widget.deleteLater()


def test_new_session_clears_recording(ui_env, monkeypatch):
    from tinypedal.api_control import api

    elapsed = [500.0]
    monkeypatch.setattr(api.read.session, "elapsed", lambda: elapsed[0])
    widget = new_widget({"show_incident_recorder": True, "slow_data_update_interval": 0})
    try:
        widget.timerEvent(None)
        assert widget.recorder.samples
        elapsed[0] = 3.0  # new session
        widget.recorder.samples.append(widget.recorder.samples[-1])
        widget.check_new_session()
        assert not widget.recorder.samples
    finally:
        widget.deleteLater()


def test_tyre_diameters_reset_on_car_change(ui_env):
    from tinypedal.widget._black_box.suspension import TYRE_DIAMETER_MM

    widget = new_widget()
    try:
        widget.update_tyre_diameters([0.355] * 4)
        widget.vehicle_name = "other car"
        widget.update_suspension(30.0)
        assert widget.tyre_diameters == (TYRE_DIAMETER_MM,) * 4
    finally:
        widget.deleteLater()


def test_every_new_option_draws(ui_env):
    widget = new_widget({key: True for key in (
        "show_tyre_camber_spread", "show_tyre_pressure_range", "show_brake_peak_temperature",
        "show_brake_heat_balance", "show_suspension_lap_stats", "show_damper_histogram",
        "show_ride_height_minimum", "show_third_spring", "show_incident_recorder", "show_brake_wear",
    )} | {"brake_wear_display": "Laps", "incident_export_format": "CSV"})
    try:
        wheel = widget.wheels[0]
        wheel.pressure_min, wheel.pressure_max, wheel.brake_peak, wheel.brake_laps = 170.0, 183.0, 812.0, 12.0
        wheel.ride_height_min, wheel.bottoming, wheel.bumps = 18.0, 2, 3
        wheel.travel_min, wheel.travel_max, wheel.surface_hot, wheel.brake_imbalance = 0.1, 0.9, True, True
        wheel.damper_shares = (0.1, 0.4, 0.4, 0.1)
        wheel.brake_wear_known = True
        widget.grab()
    finally:
        widget.deleteLater()
