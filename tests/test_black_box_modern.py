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

    cfg.user.setting["black_box"].update(overrides or {})
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
def test_damage_panel_bottom_right(ui_env):
    widget = new_widget()
    try:
        panel = widget.rect_damage
        assert not panel.isNull()
        assert panel.right() <= widget.width() and panel.bottom() <= widget.height()
        assert panel.top() >= widget.rect_car_view.bottom()  # below car view
        assert panel.right() > widget.width() - widget.unit  # right edge
        for _left, right in widget.bottom_rows:
            assert right.right() < panel.left()  # rows share the width left of panel
    finally:
        widget.deleteLater()


def test_damage_panel_can_be_hidden(ui_env):
    widget = new_widget({"show_damage_panel": False})
    try:
        assert widget.rect_damage.isNull()
        assert widget.bottom_rows[0][1].right() > widget.width() - widget.unit
    finally:
        widget.deleteLater()


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
