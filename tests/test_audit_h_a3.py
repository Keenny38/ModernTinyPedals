"""Audit lot A3: overlay repaints only on visible change (identical drawing), update errors rate limited,
paused updates clear spotter & notifications"""

import logging
import sys
import threading
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication, QRect
from PySide6.QtGui import QPaintEvent

from neopedal.api_control import api
from neopedal.module_info import minfo
from neopedal.setting import cfg
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


def reader(monkeypatch, group: str, name: str, value):
    """Fake API reader returns value (or calls it, if callable)"""
    func = value if callable(value) else (lambda *args, **kwargs: value)
    monkeypatch.setattr(getattr(api.read, group), name, func)


def count_repaints(widget) -> list:
    """Record update() requests of widget (Python side)"""
    calls: list = []
    widget.update = lambda *args: calls.append(args)
    return calls


# 1. Uncaught exception log rate limit, overlay update stopped after repeated errors
def test_exception_repeats_counts():
    from neopedal.log_handler import ExceptionRepeats

    repeats = ExceptionRepeats()

    def raise_once():
        try:
            raise ValueError("again")
        except ValueError:
            return sys.exc_info()

    logged = []
    for _ in range(2000):
        exc_type, _, exc_tb = raise_once()
        count = repeats.count(exc_type, exc_tb)
        if count:
            logged.append(count)
    assert logged == [1, 10, 100, 1000, 2000]
    exc_type, _, exc_tb = raise_once()
    assert repeats.count(KeyError, exc_tb) == 1  # other type: own count


def test_uncaught_exception_log_rate_limited(caplog):
    from neopedal.log_handler import install_exception_hooks

    logger = logging.getLogger("neopedal.test_hooks_a3")
    saved = sys.excepthook, threading.excepthook
    try:
        install_exception_hooks(logger)
        with caplog.at_level(logging.CRITICAL, logger="neopedal.test_hooks_a3"):
            for _ in range(120):
                try:
                    raise RuntimeError("timer failed")
                except RuntimeError:
                    sys.excepthook(*sys.exc_info())
        messages = [record.getMessage() for record in caplog.records]
        assert messages == ["Uncaught exception", "Uncaught exception (x10)", "Uncaught exception (x100)"]
        assert all(record.exc_info for record in caplog.records)  # traceback kept
    finally:
        sys.excepthook, threading.excepthook = saved


def test_overlay_update_stopped_after_repeated_errors(widgets, monkeypatch, caplog):
    from neopedal import app_signal
    from neopedal.widget._base import MAX_TIMER_ERRORS

    widget = widgets("steering_wheel")
    errors = []
    app_signal.error.connect(errors.append)
    try:
        failing = {"on": True}

        def steering_raw():
            if failing["on"]:
                raise ValueError("bad data")
            return 0.0

        reader(monkeypatch, "inputs", "steering_raw", steering_raw)
        for _ in range(MAX_TIMER_ERRORS - 1):
            with pytest.raises(ValueError):
                widget.timerEvent(None)
        failing["on"] = False
        widget.timerEvent(None)  # success: consecutive count restarts
        assert not widget.timer_failed
        failing["on"] = True
        widget._update_timer.start(1000, widget)
        with caplog.at_level(logging.ERROR):
            for _ in range(MAX_TIMER_ERRORS):
                with pytest.raises(ValueError):  # still raised (logged by excepthook, visible in tests)
                    widget.timerEvent(None)
        assert widget.timer_failed and not widget._update_timer.isActive()
        assert sum("stopped after repeated errors" in record.getMessage() for record in caplog.records) == 1
        assert len(errors) == 1 and errors[0].endswith("stopped after repeated errors, see log for details.")
        widget._Base__toggle_timer(False)  # updates resumed: failed overlay not restarted
        assert not widget._update_timer.isActive()
    finally:
        app_signal.error.disconnect(errors.append)


# 2. Paused updates: spotter bars & notifications cleared
@pytest.mark.parametrize("modern", (False, True))
def test_spotter_cleared_on_pause(widgets, modern):
    from neopedal.widget.spotter import NO_STATE, Side, SpotterState

    widget = widgets("spotter", modern)
    widget.state = SpotterState(left=Side(0.0, 1.0, True, 1.0))
    widget.sides = (Side(0.0, 1.0, True, 1.0), Side())
    repaints = count_repaints(widget)
    widget.post_update()
    assert widget.state == NO_STATE and widget.sides[0] == Side() and repaints
    repaints.clear()
    widget.post_update()
    assert not repaints  # nothing shown: no repaint


@pytest.mark.parametrize("modern", (False, True))
def test_race_notifications_cleared_on_pause(widgets, modern):
    from neopedal.widget.race_notifications import Message

    widget = widgets("race_notifications", modern)
    widget.clock = lambda: 1.0
    widget.add_messages([Message("Penalty")], 1.0)
    widget.timerEvent(None)
    assert widget.state
    repaints = count_repaints(widget)
    widget.post_update()
    assert widget.state == () and not widget.toasts and repaints


# 3. Sector bar being driven: visible steps only
def test_sector_fill_quantized():
    from neopedal.widget._modern.drivers import FILL_STEPS, DriverTable

    class Sectors:
        best = (30.0, 30.0, 30.0)
        last = (0.0, 0.0, 0.0)
        best_lap = (0.0, 0.0, 0.0)
        current = (30.0, 0.0, 0.0)

    fills = {DriverTable.sector_fill(Sectors, 1, 30.0 + 15.0 + offset) for offset in (0.0, 0.01, 0.05, 0.1)}
    assert fills == {0.5}  # time moved, bar drawn the same: row unchanged
    fill = DriverTable.sector_fill(Sectors, 1, 30.0 + 29.99)
    assert fill <= 0.97 and (fill * FILL_STEPS).is_integer()
    assert DriverTable.sector_fill(Sectors, 1, -1.0) == 0.0


# 4. Classic RPM LED, steering & heading: repaint on visible change only
def test_rpm_led_repaints_on_led_change(widgets, monkeypatch):
    widget = widgets("rpm_led", show_rpm_flickering_above_critical=False)
    reader(monkeypatch, "engine", "rpm_max", 10000.0)
    reader(monkeypatch, "engine", "gear_max", 6)
    rpm = {"value": 0.0}
    reader(monkeypatch, "engine", "rpm", lambda: rpm["value"])
    widget.timerEvent(None)
    low = widget.rpm_low
    step = widget.rpm_critical / widget.max_led
    rpm["value"] = low + step * 2.2
    widget.timerEvent(None)
    repaints = count_repaints(widget)
    for offset in (0.1, 0.3, 0.5, 0.7):  # same 3 LEDs lit
        rpm["value"] = low + step * (2.2 + offset)
        widget.timerEvent(None)
    assert not repaints
    rpm["value"] = low + step * 3.2  # fourth LED lit
    widget.timerEvent(None)
    assert len(repaints) == 1
    widget.grab()  # draws with stored rpm


def test_steering_and_heading_repaint_on_visible_change(widgets, monkeypatch):
    steer = {"value": 0.2}
    reader(monkeypatch, "inputs", "steering_raw", lambda: steer["value"])
    reader(monkeypatch, "inputs", "steering_range_physical", 900.0)
    for name in ("steering_wheel", "steering_meter"):
        steer["value"] = 0.2
        widget = widgets(name)
        widget.timerEvent(None)
        repaints = count_repaints(widget)
        for tiny in (0.000001, 0.000002, 0.000003):  # far below 0.1 degree & one pixel
            steer["value"] = 0.2 + tiny
            widget.timerEvent(None)
        assert not repaints, name
        steer["value"] = 0.5
        widget.timerEvent(None)
        assert len(repaints) == 1, name
        widget.grab()
    widget = widgets("heading")
    yaw = {"value": 1.0}
    reader(monkeypatch, "vehicle", "orientation_yaw_radians", lambda: yaw["value"])
    widget.timerEvent(None)
    repaints = count_repaints(widget)
    yaw["value"] = 1.0 + 1e-6
    widget.timerEvent(None)
    assert not repaints
    yaw["value"] = 1.1
    widget.timerEvent(None)
    assert len(repaints) == 1
    widget.grab()


# 5. Damage: no repaint once detached parts state is steady
def test_classic_damage_flash_state_in_timer(widgets, monkeypatch):
    widget = widgets("damage", show_detached_warning_flash=False)
    reader(monkeypatch, "vehicle", "damage_severity", (3, 0, 0, 0, 0, 0, 0, 0))
    widget.timerEvent(None)
    repaints = count_repaints(widget)
    for _ in range(5):
        widget.timerEvent(None)
        widget.grab()  # paint no longer asks for another update
    assert not repaints
    widget = widgets("damage", show_detached_warning_flash=True)
    flash = iter((True, True, False, False, True))
    monkeypatch.setattr(widget, "warn_flash", type("Flash", (), {"send": lambda self, value: next(flash)})())
    repaints = count_repaints(widget)
    for _ in range(5):
        widget.timerEvent(None)
    assert len(repaints) == 3  # on, off, on


def test_modern_damage_dim_phase_no_repaint(widgets, monkeypatch):
    from neopedal.widget._modern import damage

    widget = widgets("damage", modern=True, show_detached_warning_flash=True)
    reader(monkeypatch, "vehicle", "damage_severity", (3, 0, 0, 0, 0, 0, 0, 0))
    period = widget.flash_on + widget.flash_off
    clock = {"now": 1000 * period + widget.flash_on + 0.01}  # dim part of flash
    monkeypatch.setattr(damage, "monotonic", lambda: clock["now"])
    widget.timerEvent(None)
    repaints = count_repaints(widget)
    for _ in range(3):
        clock["now"] += 0.001
        widget.timerEvent(None)
    assert not repaints
    clock["now"] = 1001 * period + widget.flash_on / 2  # bright part: pulsing
    widget.timerEvent(None)
    assert repaints


def test_black_box_damage_pulse_keyed():
    from neopedal.widget._black_box.regions import PULSE_STEPS, RegionMixin

    class Box(RegionMixin):
        alert_pulse = True
        show_damage_panel = True
        damage_detached = (False,) * 4
        damage_puncture = (False,) * 4
        body_damage = (0,) * 8
        strength = 0.675

        def pulse(self):
            return self.strength

    box = Box()
    assert box.damage_pulse_step() == 0
    box.body_damage = (3, 0, 0, 0, 0, 0, 0, 0)
    first = box.damage_pulse_step()
    box.strength += 0.2 / PULSE_STEPS  # too small to see
    assert box.damage_pulse_step() == first
    box.strength = 1.0
    assert box.damage_pulse_step() == PULSE_STEPS


# 6. Delta graph mark on device pixels
def test_delta_graph_mark_on_device_pixels(widgets, monkeypatch):
    widget = widgets("delta_graph")
    reader(monkeypatch, "lap", "progress", 0.3337)
    dpr = widget.devicePixelRatioF()
    _, mark_x, mark_y, _ = widget.read_graph()
    chart = widget.chart
    assert (mark_x * dpr).is_integer() and (mark_y * dpr).is_integer()
    assert abs(mark_x - (chart.left() + 0.3337 * chart.width())) <= 0.5 / dpr


# 7. Chat lines cached, flag limiter keyed on text, edit outline label cached
def test_chat_message_lines_cached():
    from neopedal.widget.chat import chat_lines, message_lines

    message_lines.cache_clear()
    messages = ((100.0, "M. Laurent: sorry for the contact at turn 1"),)
    first = chat_lines(messages, 101.0, 20, 5, 0.0, 5.0, True)
    hits = message_lines.cache_info().hits
    assert chat_lines(messages, 102.0, 20, 5, 0.0, 5.0, True) == first
    assert message_lines.cache_info().hits == hits + 1
    assert message_lines(1.0, "", 20, False) == ("",)


def test_flag_limiter_keyed_on_text(widgets, monkeypatch):
    widget = widgets("flag", show_speed_limiter=True, show_current_speed_while_limiter_on=True)
    reader(monkeypatch, "switch", "speed_limiter", True)
    speed = {"value": 16.0}
    reader(monkeypatch, "vehicle", "speed", lambda: speed["value"])
    widget.timerEvent(None)
    target = widget.bar_limiter
    text = target.text
    repaints = count_repaints(target)
    speed["value"] = 16.00001  # same speed shown
    widget.timerEvent(None)
    assert not repaints and target.text == text
    speed["value"] = 20.0
    widget.timerEvent(None)
    assert repaints and target.text != text


def test_edit_outline_label_cached(ui_env, bundled_fonts):
    from PySide6.QtWidgets import QWidget

    from neopedal.widget._edit_frame import EditOutline

    parent = QWidget()
    parent.resize(200, 100)
    outline = EditOutline(parent, "Steering wheel")
    outline.resize(200, 100)
    outline.grab()
    cache = outline.label_cache
    assert cache is not None and cache[0] == "Steering wheel"
    outline.grab()
    assert outline.label_cache is cache  # not built again
    outline.paintEvent(QPaintEvent(QRect(150, 80, 10, 10)))  # label outside repainted area: skipped
    outline.title = "Heading"
    outline.grab()
    assert outline.label_cache[0] == "Heading"
    parent.deleteLater()


# 8. Gear gauge key: neutral warning repaints with unchanged readings
def test_gear_neutral_warning_repaints(widgets, monkeypatch):
    widget = widgets("gear", neutral_warning_speed_threshold=5, neutral_warning_time_threshold=0.3)
    gear = {"value": 1}
    reader(monkeypatch, "engine", "gear", lambda: gear["value"])
    reader(monkeypatch, "engine", "rpm", 3000.0)
    reader(monkeypatch, "engine", "rpm_max", 8000.0)
    reader(monkeypatch, "vehicle", "speed", 30.0)
    elapsed = {"value": 10.0}
    reader(monkeypatch, "timing", "elapsed", lambda: elapsed["value"])
    widget.timerEvent(None)
    gear["value"] = 0  # shifted to neutral at 10 s
    widget.timerEvent(None)
    gauge = widget.bar_gauge
    calls = []
    original = gauge.update_input
    monkeypatch.setattr(gauge, "update_input", lambda *args: (calls.append(args), original(*args)))
    elapsed["value"] = 10.1
    widget.timerEvent(None)
    assert not calls  # same readings, no warning yet
    elapsed["value"] = 11.0  # in neutral long enough: warning color
    widget.timerEvent(None)
    assert len(calls) == 1 and calls[0][2] == 3


# 9. Track map pit out predictions computed in update, not paint
@pytest.mark.parametrize("modern", (False, True))
def test_track_map_predictions_in_update(widgets, monkeypatch, modern):
    widget = widgets("track_map", modern, show_pitout_prediction=True)
    sample = ((10.0, 20.0, 30.0, False),)
    calls = []

    def predictions(map_data, player):
        calls.append(player)
        return iter(sample)

    monkeypatch.setattr(widget, "pitout_predictions", predictions)
    monkeypatch.setattr(minfo.vehicles, "playerIndex", 0)
    widget.timerEvent(None)
    assert widget.predictions == sample and len(calls) == 1
    widget.grab()
    widget.grab()
    assert len(calls) == 1  # paint draws stored predictions


# 10. No player car (player index -1, spectating): never the last car of the list
def test_player_vehicle_none_when_no_player(monkeypatch):
    from neopedal.widget._common import NO_PLAYER, player_vehicle

    vehicles = minfo.vehicles
    monkeypatch.setattr(vehicles, "playerIndex", -1)
    assert player_vehicle() is NO_PLAYER
    monkeypatch.setattr(vehicles, "playerIndex", 2)
    assert player_vehicle() is vehicles.dataSet[2]


PLAYER_WIDGETS = (
    "radar", "rivals", "track_map", "standings", "relative", "laps_and_position", "pit_stop_estimate",
    "relative_finish_order", "traffic", "navigation",
)


@pytest.mark.parametrize("modern", (False, True))
@pytest.mark.parametrize("name", PLAYER_WIDGETS)
def test_widgets_without_player_car(widgets, monkeypatch, name, modern):
    """Spectating: last car of the list (a real car with 128 cars) never read as player"""
    vehicles = minfo.vehicles
    monkeypatch.setattr(vehicles, "playerIndex", -1)
    last = vehicles.dataSet[-1]
    for attribute, value in (("pitRequested", True), ("speed", 99.0), ("classAheadIndex", 0),
                             ("classBehindIndex", 1), ("qualifyOverall", 9), ("positionOverall", 1)):
        monkeypatch.setattr(last, attribute, value)
    options = {"show_position_change": True} if name == "laps_and_position" else {}
    if name == "track_map":
        options["show_pitout_prediction"] = True
    widget = widgets(name, modern, **options)
    if name == "track_map":
        monkeypatch.setattr(widget, "pitout_predictions", lambda map_data, player: pytest.fail("read last car"))
    widget.timerEvent(None)
    widget.grab()
    if name == "rivals" and not modern:
        assert not any(widget.row_visible)  # no rival rows of last car
    if name == "track_map":
        assert widget.predictions == ()
