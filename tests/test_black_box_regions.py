"""Black box widget: only changed parts repainted, result identical to a full repaint"""

import os
import random
import subprocess
import sys

import pytest
from PySide6.QtCore import QEvent, QRect
from PySide6.QtGui import QImage, QRegion
from PySide6.QtWidgets import QApplication

from neopedal.widget._black_box.regions import WHEEL_PARTS

CONFIGS = {
    "default": {},
    "fixed_width": {"fixed_width": 333, "show_damage_panel": True, "show_incident_recorder": True,
                    "show_event_log": True, "show_battery_bar": True},
    "fixed_height": {"fixed_height": 271},
    "everything": {
        "show_suspension": True, "enable_wheel_suspension_motion": True, "show_wheel_angle": True,
        "show_damage_panel": True, "show_incident_recorder": True, "show_event_log": True,
        "show_battery_bar": True, "show_stint_comparison": True, "show_damper_histogram": True,
        "show_tyre_load": True, "show_ride_height": True, "show_brake_pressure": True,
    },
    "vertical": {"layout": 1, "show_damage_panel": True, "damage_panel_position": "Top Left"},
    "alerts": {"alert_pulse_frequency": 1.5, "smooth_transition_duration": 0.5, "show_damage_panel": True,
               "show_suspension": True, "show_battery_bar": True},
}


class Game:
    """Readings of a fake game, changed by tests"""

    def __init__(self):
        self.values = {
            "tyre": dict(surface_temperature_avg=(80.0, 81.0, 95.0, 70.0),
                         inner_temperature_avg=(80.0, 81.0, 95.0, 70.0), carcass_temperature=(75.0,) * 4,
                         load=(3000.0, 3000.0, 3500.0, 3500.0), pressure=(170.0, 171.0, 190.0, 150.0),
                         wear=(0.9, 0.8, 0.5, 0.2), surface_temperature_ico=(70.0, 80.0, 90.0) * 4,
                         compound_class=("", "", "", "")),
            "brake": dict(temperature=(400.0, 410.0, 300.0, 810.0), bias_front=0.56, pressure=(0.5, 0.5, 0.4, 0.4)),
            "vehicle": dict(speed=30.0, in_pits=False, vehicle_name="car", class_name="GT3",
                            damage_severity=(0, 1, 0, 0, 2, 0, 2, 0), aero_damage=-1.0, impact_time=0.0),
            "session": dict(elapsed=100.0),
            "lap": dict(number=3),
            "wheel": dict(is_detached=(False, False, False, False), suspension_damage=(0.0, 0.0, 0.6, 0.0),
                          suspension_deflection=(40.0, 45.0, 50.0, 55.0), toe=(0.05, 0.05, 0.0, 0.0),
                          suspension_force=(4000.0, 4000.0, 4500.0, 4500.0), ride_height=(50.0,) * 4),
            "inputs": dict(brake_raw=0.9, throttle_raw=0.4, brake=0.9, throttle=0.4, steering=0.2),
            "engine": dict(gear=3, rpm=6000.0, rpm_max=8000.0, oil_temperature=100.0, water_temperature=85.0),
            "switch": dict(abs_active=True, tc_active=False, abs_level=4, tc_level=3, tc_cut_level=-1,
                           tc_slip_level=-1, speed_limiter=1, headlights=1, ignition_starter=1, motor_map_level=2),
        }

    def install(self, monkeypatch):
        from neopedal.api_control import api
        from neopedal.module_info import minfo
        from neopedal.widget._black_box import center, panels, reader, regions, wheels

        for module in (wheels, center, panels, reader, regions):
            monkeypatch.setattr(module, "monotonic", lambda: 1000.0)
        for group, readers in self.values.items():
            target = getattr(api.read, group)
            for name in readers:
                monkeypatch.setattr(target, name, self.reader(group, name), raising=False)
        monkeypatch.setattr(minfo.wheels, "slipRatio", [0.0, 0.0, 0.0, 0.0])

    def reader(self, group, name):
        return lambda *args, **kwargs: self.values[group][name]


def new_widget(cfg, overrides, modern=False):
    from neopedal.widget import black_box
    from neopedal.widget._modern import black_box as modern_black_box

    setting = cfg.user.setting["black_box"]
    setting.update(enable_heatmap_auto_matching=False, slow_data_update_interval=0, enable_auto_resize=False,
                   alert_pulse_frequency=0, smooth_transition_duration=0, enable_required_modules=False)
    setting.update(overrides)
    return (modern_black_box.Realtime if modern else black_box.Realtime)(cfg, "black_box")


def full_image(widget) -> QImage:
    return widget.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)


# Text rasterizer variance allowed: on Linux (FreeType) the antialiased edge of a large glyph (gear digit) comes out a
# few levels apart after another part changed, in full repaints too (not a partial repaint fault). A stale part
# (old text or color left on screen) differs far more
EDGE_LEVELS = 24  # largest channel difference of a pixel
EDGE_PIXELS = 400  # pixels allowed to differ by that much


def images_match(screen: QImage, full: QImage) -> bool:
    """Same pixels, or only antialiased edges a few levels apart (see EDGE_LEVELS)"""
    if screen == full:
        return True
    if screen.size() != full.size():
        return False
    count = 0
    for y in range(full.height()):
        for x in range(full.width()):
            a, b = screen.pixel(x, y), full.pixel(x, y)
            if a == b:
                continue
            if max(abs((a >> shift & 0xFF) - (b >> shift & 0xFF)) for shift in (0, 8, 16, 24)) > EDGE_LEVELS:
                return False
            count += 1
            if count > EDGE_PIXELS:
                return False
    return True


def screen_matches_full(widget) -> bool:
    """Window as last painted on screen (backing store) same as a full repaint"""
    full = full_image(widget)
    screen = widget.backingStore().paintDevice().copy(0, 0, full.width(), full.height())
    return images_match(screen.convertToFormat(QImage.Format.Format_ARGB32), full)


def test_images_match_allows_edge_variance_only(ui_env):
    full = QImage(40, 20, QImage.Format.Format_ARGB32)
    full.fill(0xFF303640)
    edge = full.copy()
    for x in range(30):
        edge.setPixel(x, 5, 0xFF38393A)  # a few levels off: antialiased edge
    assert images_match(edge, full)
    stale = full.copy()
    stale.setPixel(3, 3, 0xFFF9AC21)  # old glyph pixel: far off
    assert not images_match(stale, full)
    many = QImage(40, 20, QImage.Format.Format_ARGB32)
    many.fill(0xFF323640)  # small difference over a whole area: not just edges
    assert EDGE_PIXELS < 40 * 20 and not images_match(many, full)


def process_events():
    for _ in range(5):
        QApplication.processEvents()


def changes(game: Game):
    """Changes touching most parts, one at a time"""
    values = game.values
    yield "speed", lambda: values["vehicle"].update(speed=55.0)
    yield "rpm", lambda: values["engine"].update(rpm=6900.0)
    yield "tyre", lambda: values["tyre"].update(inner_temperature_avg=(80.0, 99.0, 95.0, 70.0))
    yield "brake", lambda: values["brake"].update(temperature=(400.0, 410.0, 900.0, 810.0))
    yield "bias", lambda: values["brake"].update(bias_front=0.58)
    yield "abs", lambda: values["switch"].update(abs_active=False)
    yield "lights", lambda: values["switch"].update(headlights=0)
    yield "engine", lambda: values["engine"].update(water_temperature=99.0)
    yield "damage", lambda: values["vehicle"].update(damage_severity=(0, 2, 0, 0, 2, 0, 2, 1))
    yield "suspension", lambda: values["wheel"].update(suspension_deflection=(30.0, 45.0, 50.0, 70.0))
    yield "steer", lambda: values["wheel"].update(toe=(0.2, 0.2, 0.0, 0.0))
    yield "detached", lambda: values["wheel"].update(is_detached=(False, False, True, False))
    yield "gear", lambda: values["engine"].update(gear=4)


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("config", sorted(CONFIGS))
def test_partial_repaint_matches_full_repaint(ui_env, bundled_fonts, monkeypatch, config, modern, translucent=True):
    from neopedal.setting import cfg

    monkeypatch.setitem(cfg.compatibility, "enable_translucent_background", translucent)
    game = Game()
    game.install(monkeypatch)
    widget = new_widget(cfg, CONFIGS[config], modern)
    regions = []
    paint = widget.paint_content
    monkeypatch.setattr(widget, "paint_content", lambda region=None: (regions.append(region), paint(region)))
    try:
        widget.timerEvent(None)
        full_image(widget)  # shapes drawn from cache from second paint on (see _painter): first paint not on screen
        widget.show()
        process_events()
        assert screen_matches_full(widget)
        partial = 0
        for name, change in changes(game):
            change()
            regions.clear()
            widget.timerEvent(None)
            full_image(widget)  # shapes of new size cached first, as for the full repaint compared with
            regions.clear()
            process_events()
            assert regions, f"{name}: nothing repainted"
            # Whole widget only if window system asked (expose), or bounding rect of parts at fractional scale
            partial += all(region is not None for region in regions)
            assert screen_matches_full(widget), f"{name}: partial repaint differs"
        if widget.devicePixelRatioF().is_integer():
            assert partial >= 8
    finally:
        widget.hide()
        widget.deleteLater()


def test_unchanged_parts_skipped(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg

    game = Game()
    game.install(monkeypatch)
    widget = new_widget(cfg, CONFIGS["everything"])
    if not widget.devicePixelRatioF().is_integer():
        pytest.skip("fractional screen scale: bounding rect of parts repainted")
    calls = []
    monkeypatch.setattr(widget, "update", lambda *args: calls.append(args))
    widget.timerEvent(None)
    assert calls == [()]  # first update: whole widget
    calls.clear()
    widget.timerEvent(None)
    assert not calls  # nothing changed
    game.values["vehicle"]["speed"] = 50.0
    widget.timerEvent(None)
    rects = widget.part_rects()
    assert calls == repainted(widget, "center")  # speed only
    calls.clear()
    game.values["tyre"]["inner_temperature_avg"] = (90.0, 81.0, 95.0, 70.0)
    widget.timerEvent(None)
    assert calls == repainted(widget, "wheel0")
    assert QRect(rects["wheel0"]) in [rect for rect, in calls] or QRegion(rects["wheel0"]).subtracted(
        sum((QRegion(rect) for rect, in calls), QRegion())).isEmpty()
    widget.last_state = ()  # forced: whole widget
    calls.clear()
    widget.timerEvent(None)
    assert calls == [()]


def repainted(widget, name: str) -> list[tuple]:
    """Update calls repainting part name (rects widened over gradient shapes they would cut)"""
    return [(rect,) for rect in widget.uncut([widget.part_rects()[name]])]


def test_paint_skips_parts_outside_region(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg

    game = Game()
    game.install(monkeypatch)
    widget = new_widget(cfg, CONFIGS["everything"])
    widget.timerEvent(None)
    drawn = []

    def spy(name, original):
        return lambda *args, **kwargs: (drawn.append(name), original(*args, **kwargs))

    for method in ("draw_tyre", "draw_center", "draw_trace", "draw_damage_panel", "draw_event_log",
                   "draw_battery_bar", "draw_damper_histogram"):
        monkeypatch.setattr(widget, method, spy(method, getattr(widget, method)))
    widget.grab()
    assert drawn.count("draw_tyre") == 4 and "draw_trace" in drawn and "draw_event_log" in drawn
    drawn.clear()
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    widget.render(image, sourceRegion=QRegion(widget.part_rects()["center"]))
    assert "draw_center" in drawn
    assert "draw_trace" not in drawn and "draw_damage_panel" not in drawn and "draw_event_log" not in drawn
    assert "draw_battery_bar" not in drawn and "draw_damper_histogram" not in drawn


def test_part_rects_inside_widget_and_cover_wheels(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg

    game = Game()
    game.install(monkeypatch)
    for overrides in CONFIGS.values():
        widget = new_widget(cfg, overrides)
        widget.timerEvent(None)
        rects = widget.part_rects()
        assert set(rects) == set(widget.part_states())
        for name, rect in rects.items():
            assert rect.isEmpty() or QRect(widget.rect()).contains(rect), name
        for index, name in enumerate(WHEEL_PARTS):  # tyre & disc inside their part
            fit = widget.fit
            tyre = widget.rects_tyre[index]
            mapped = QRect(round(fit.offset_x + tyre.x() * fit.scale), round(fit.offset_y + tyre.y() * fit.scale),
                           round(tyre.width() * fit.scale), round(tyre.height() * fit.scale))
            assert rects[name].contains(mapped.adjusted(1, 1, -1, -1)), name
        widget.deleteLater()


def test_only_animated_parts_repainted(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg

    game = Game()
    game.values["wheel"]["is_detached"] = (False, False, False, True)  # pulsing tyre
    game.install(monkeypatch)
    widget = new_widget(cfg, {"alert_pulse_frequency": 1.5})
    calls = []
    monkeypatch.setattr(widget, "update", lambda *args: calls.append(args))
    widget.timerEvent(None)
    calls.clear()
    widget.show_damage_panel = False  # detached wheel pulses there too
    for _ in range(2):  # no data change: pulsing wheel only, every update
        widget.timerEvent(None)
        assert calls == repainted(widget, "wheel3")
        calls.clear()
    assert widget.animating() and widget.animating_parts() == {"wheel3"}


def test_partial_repaint_of_opaque_window(ui_env, bundled_fonts, monkeypatch):
    """Translucent background off (compatibility): window background filled by Qt in repainted region"""
    test_partial_repaint_matches_full_repaint(ui_env, bundled_fonts, monkeypatch, "everything", True, False)


def test_color_fade_repainted_at_final_color(ui_env, bundled_fonts, monkeypatch):
    """Fade starts when painted, repaints decided at update: once ended, wheel repainted one more time
    (last repaint while fading was short of final color)"""
    from neopedal.setting import cfg
    from neopedal.widget._black_box import regions, wheels

    game = Game()
    game.install(monkeypatch)
    clock = [1000.0]
    for module in (wheels, regions):
        monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    widget = new_widget(cfg, {"smooth_transition_duration": 0.5})
    calls = []
    monkeypatch.setattr(widget, "update", lambda *args: calls.append(args))
    widget.timerEvent(None)
    widget.grab()  # first colors: no fade
    game.values["tyre"]["inner_temperature_avg"] = (110.0, 81.0, 95.0, 70.0)
    game.values["tyre"]["surface_temperature_avg"] = (110.0, 81.0, 95.0, 70.0)
    game.values["brake"]["temperature"] = (900.0, 410.0, 300.0, 810.0)
    calls.clear()
    widget.timerEvent(None)
    rect = repainted(widget, "wheel0")[0]
    assert rect in calls
    widget.grab()  # fade starts at paint
    assert widget.tyre_fades[0].active(clock[0]) or widget.brake_fades[0].active(clock[0])
    for step in range(1, 5):  # fading: repainted every update
        clock[0] = 1000.0 + step * 0.12
        calls.clear()
        widget.timerEvent(None)
        assert rect in calls
        widget.grab()
    clock[0] = 1000.6  # fade ended since last update: final color painted once more
    calls.clear()
    widget.timerEvent(None)
    assert rect in calls
    widget.grab()
    clock[0] = 1000.7
    calls.clear()
    widget.timerEvent(None)
    assert rect not in calls


def test_color_fade_shorter_than_update_interval_repainted(ui_env):
    from neopedal.widget._black_box.wheels import ColorFade

    fade = ColorFade(0.05)
    fade.color_of("#000000", 0.0)
    assert not fade.needs_repaint(0.0)
    fade.color_of("#FFFFFF", 0.01)  # started at paint, ended before next update
    assert fade.needs_repaint(0.2)
    assert not fade.needs_repaint(0.3)


# --- Change keys of drawn values (see _black_box.drawn): randomized data, every screen scale
RANDOM_CONFIGS = {
    "default": {},
    "everything": CONFIGS["everything"],
    "fixed_width": CONFIGS["fixed_width"],
    "readings": {
        "layout": 1, "show_tyre_load": True, "tyre_load_display": "Newton", "show_tyre_slip_angle": True,
        "show_tyre_carcass_temperature": True, "show_brake_pressure": True, "show_rpm": True,
        "show_delta_best": True, "show_laptime": True, "show_brake_heat_balance": True, "show_clutch_bar": True,
        "show_gear_speed_cluster": False, "override_unit_temperature": "Fahrenheit",
        "override_unit_speed": "MPH", "override_unit_tyre_pressure": "psi", "show_damper_histogram": True,
    },
}
SCALES = ("1.25", "1.5", "2")


def random_change(game: Game, rng: random.Random):
    """One random data change: large jumps, saturated pedals, and moves below display precision"""
    values = game.values
    tiny = rng.choice((1e-7, 1e-4, 0.004))
    kind = rng.randrange(14)
    if kind == 0:
        speed = values["vehicle"]["speed"]
        values["vehicle"]["speed"] = rng.choice((speed + tiny, rng.uniform(0, 90)))
    elif kind == 1:
        rpm = values["engine"]["rpm"]
        values["engine"]["rpm"] = rng.choice((rpm + tiny * 100, rng.uniform(0, 8400), 7900.0))
    elif kind == 2:
        values["engine"]["gear"] = rng.randint(-1, 7)
    elif kind == 3:
        throttle, brake = rng.choice((0.0, 1.0, rng.random())), rng.choice((0.0, 1.0, rng.random()))
        values["inputs"].update(throttle=throttle, throttle_raw=throttle, brake=brake, brake_raw=brake)
    elif kind == 4:
        toe = values["wheel"]["toe"]
        values["wheel"]["toe"] = rng.choice((
            tuple(value + tiny * 0.01 for value in toe), (rng.uniform(-0.1, 0.1),) * 2 + toe[2:]))
        values["inputs"]["steering"] = rng.uniform(-1, 1)
    elif kind == 5:
        deflection = values["wheel"]["suspension_deflection"]
        values["wheel"]["suspension_deflection"] = rng.choice((
            tuple(value + tiny for value in deflection), tuple(rng.uniform(25, 75) for _ in range(4))))
    elif kind == 6:
        temps = tuple(rng.uniform(40, 120) for _ in range(4))
        values["tyre"].update(surface_temperature_avg=temps, inner_temperature_avg=temps)
    elif kind == 7:
        values["brake"]["temperature"] = tuple(rng.uniform(100, 1000) for _ in range(4))
    elif kind == 8:
        values["tyre"].update(pressure=tuple(rng.uniform(140, 200) for _ in range(4)),
                              wear=tuple(rng.random() for _ in range(4)),
                              load=tuple(rng.uniform(1000, 6000) for _ in range(4)))
    elif kind == 9:
        values["engine"].update(oil_temperature=rng.uniform(80, 130), water_temperature=rng.uniform(70, 120))
    elif kind == 10:
        bias = values["brake"]["bias_front"]
        values["brake"]["bias_front"] = rng.choice((bias + tiny * 0.01, rng.uniform(0.5, 0.6)))
    elif kind == 11:
        values["switch"].update(abs_active=rng.random() < 0.5, tc_active=rng.random() < 0.5,
                                headlights=rng.randint(0, 1), ignition_starter=rng.randint(0, 1),
                                speed_limiter=rng.randint(0, 1))
    elif kind == 12:
        values["vehicle"]["damage_severity"] = tuple(rng.choice((0, 0, 1, 2)) for _ in range(8))
    else:
        values["wheel"]["suspension_damage"] = tuple(rng.choice((0.0, 0.2, 0.5, 0.95)) for _ in range(4))


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("config", sorted(RANDOM_CONFIGS))
def test_random_changes_partial_repaint_matches_full(ui_env, bundled_fonts, monkeypatch, config, modern):
    """After any sequence of data changes, the window as repainted part by part equals a full repaint"""
    from neopedal.setting import cfg

    monkeypatch.setitem(cfg.compatibility, "enable_translucent_background", True)
    rng = random.Random(f"{config}-{modern}")
    game = Game()
    game.install(monkeypatch)
    widget = new_widget(cfg, RANDOM_CONFIGS[config], modern)
    try:
        widget.timerEvent(None)
        full_image(widget)
        widget.show()
        process_events()
        skipped = 0
        for step in range(40):
            for _ in range(rng.randint(1, 3)):
                random_change(game, rng)
            before = widget.last_parts
            widget.timerEvent(None)
            skipped += sum(state == before.get(name) for name, state in widget.last_parts.items())
            full_image(widget)  # shapes of new size cached first, as for the full repaint compared with
            process_events()
            assert screen_matches_full(widget), f"step {step}: partial repaint differs"
        assert skipped  # parts left alone
    finally:
        widget.hide()
        widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # gone before the next test


@pytest.mark.parametrize("scale", SCALES)
def test_random_changes_partial_repaint_at_screen_scale(scale):
    """Same at 125, 150 & 200 % screen scale (own process: scale set before the application starts)"""
    run_scaled(f"{__file__}::test_random_changes_partial_repaint_matches_full", scale)


def run_scaled(test: str, scale: str):
    """Run test in a process at screen scale"""
    if os.environ.get("QT_SCALE_FACTOR"):
        pytest.skip("run inside a scaled run")
    env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:cov", test],
        env=env, capture_output=True, text=True, timeout=600, cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    # Summary, not exit code: interpreter exit may crash on Windows once tests are done (widgets left over)
    summary = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    assert " passed" in summary and " failed" not in summary and " error" not in summary, (
        result.stdout[-4000:] + result.stderr[-2000:])


def test_display_precision_keys(ui_env, bundled_fonts, monkeypatch):
    """Changes below what is drawn repaint nothing: RPM within a lit LED step, speed within its shown digit,
    tyre load not shown, wheel angle & travel noise below the motion grid"""
    from neopedal.setting import cfg

    game = Game()
    game.install(monkeypatch)
    widget = new_widget(cfg, {"show_suspension": True, "enable_wheel_suspension_motion": True,
                              "show_wheel_angle": True, "show_rpm": False, "show_tyre_load": False,
                              "show_gear_speed_cluster": False, "show_pedal_bars": False,
                              "enable_gear_rpm_color": False})
    if not widget.devicePixelRatioF().is_integer():
        pytest.skip("fractional screen scale: bounding rect of parts repainted")
    calls = []
    monkeypatch.setattr(widget, "update", lambda *args: calls.append(args))
    widget.timerEvent(None)
    calls.clear()
    values = game.values
    for name, change in (
        ("rpm", lambda: values["engine"].update(rpm=6001.0)),
        ("speed", lambda: values["vehicle"].update(speed=30.01)),
        ("load", lambda: values["tyre"].update(load=(3100.0, 3000.0, 3500.0, 3500.0))),
        ("toe", lambda: values["wheel"].update(toe=(0.05 + 1e-7, 0.05 + 1e-7, 0.0, 0.0))),
        ("travel", lambda: values["wheel"].update(suspension_deflection=(40.0 + 1e-5, 45.0, 50.0, 55.0))),
    ):
        change()
        widget.timerEvent(None)
        assert not calls, name
    before = widget.last_parts
    values["engine"]["rpm"] = 7000.0  # more LEDs lit, below redline (no flash)
    widget.timerEvent(None)
    assert {name for name, state in widget.last_parts.items() if state != before[name]} == {"leds"}
    assert calls == repainted(widget, "leds")
