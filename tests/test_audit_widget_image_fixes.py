"""Audit fixes: overlay readings (gear, damage, pit lane, steering, elevation, lap history, notifications,
delta graph, weather), resize ghost, readable logo copies & game pictures fetching

Widgets are built on default settings (ui_env) with a neutral API reader, then single readers and
data module outputs are set to the case under test. Nothing is ever asked to a real game.
"""

import json
import math
import os
import random
import threading
from collections import deque
from importlib import import_module
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QHideEvent, QImage, QMouseEvent
from PySide6.QtWidgets import QWidget

from tinypedal.api_control import api
from tinypedal.module_info import ConsumptionDataSet, minfo
from tinypedal.process import game_images as gi
from tinypedal.setting import cfg
from tinypedal.userfile import custom_image, game_images
from tinypedal.widget._modern import create_widget


@pytest.fixture
def widgets(ui_env, bundled_fonts):
    """Build widgets by name (modern design unless modern=False), deleted after test"""
    created = []

    def make(name: str, modern: bool = True, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def reader(monkeypatch, group: str, name: str, value):
    """Neutral API reader returns value"""
    monkeypatch.setattr(getattr(api.read, group), name, lambda *args, **kwargs: value)


# --- Gear: consumption rate negative while refuelling (negative ** fractional exponent: complex)
@pytest.mark.parametrize("modern", [True, False])
def test_gear_negative_consumption_rate_while_refuelling(widgets, monkeypatch, modern):
    widget = widgets("gear", modern=modern, show_consumption_bar=True,
                     consumption_progression_exponential_scale=1.5)
    monkeypatch.setattr(minfo.fuel, "rateOfConsumption", 2.0)
    widget.timerEvent(None)
    monkeypatch.setattr(minfo.fuel, "rateOfConsumption", -3.0)
    for _ in range(3):
        widget.timerEvent(None)  # raised TypeError (complex) on every update
    widget.grab()


# --- Damage: impact of previous session (game impact time kept, elapsed restarted) not shown
def test_modern_damage_old_session_impact_hidden(widgets, monkeypatch):
    widget = widgets("damage", show_last_impact_cone=True, last_impact_cone_duration=5)
    reader(monkeypatch, "vehicle", "impact_time", 500.0)
    for elapsed in (10.0, 501.0):  # old impact, also once elapsed catches up with it
        reader(monkeypatch, "timing", "elapsed", elapsed)
        widget.timerEvent(None)
        assert not widget.impact_visible
    reader(monkeypatch, "vehicle", "impact_time", 600.0)  # new impact
    reader(monkeypatch, "timing", "elapsed", 601.0)
    widget.timerEvent(None)
    assert widget.impact_visible
    reader(monkeypatch, "timing", "elapsed", 610.0)
    widget.timerEvent(None)
    assert not widget.impact_visible


def test_classic_damage_old_session_impact_hidden(widgets, monkeypatch):
    widget = widgets("damage", modern=False, show_last_impact_cone=True, last_impact_cone_duration=5)
    reader(monkeypatch, "vehicle", "impact_time", 500.0)
    reader(monkeypatch, "timing", "elapsed", 10.0)
    widget.timerEvent(None)
    assert widget.last_impact_expired  # was shown: 10 - 500 < duration
    reader(monkeypatch, "vehicle", "impact_time", 600.0)
    reader(monkeypatch, "timing", "elapsed", 601.0)
    widget.timerEvent(None)
    assert not widget.last_impact_expired


# --- Pit lane helper shown always: box approach reset away from pit lane
@pytest.mark.parametrize("modern", [True, False])
def test_pit_lane_helper_shown_always_resets_box_approach(widgets, monkeypatch, modern):
    from tinypedal.widget.pit_lane_helper import DASH

    widget = widgets("pit_lane_helper", modern=modern, show_always=True)
    reader(monkeypatch, "lap", "distance", 100.0)
    reader(monkeypatch, "lap", "track_length", 4000.0)
    reader(monkeypatch, "lap", "pit_box_distance", 300.0)
    reader(monkeypatch, "vehicle", "in_paddock", 0)
    reader(monkeypatch, "vehicle", "pit_request", False)
    widget.box_reference, widget.box_passed = 800.0, True  # left from previous pit stop
    reading = widget.read_pit()
    assert reading.visible
    assert widget.box_reference == 0.0 and not widget.box_passed
    assert reading.box != DASH  # distance shown, was stuck on dash


# --- Steering meter: rotation range read without scale marks (angle reading was 0)
def test_classic_steering_meter_range_without_scale_marks(widgets, monkeypatch):
    widget = widgets("steering_meter", modern=False, show_scale_mark=False, manual_steering_range=900)
    widget.timerEvent(None)
    assert widget.rot_range == 900


# --- Elevation: whole pixel position, traveled part not drawn at lap start
def test_classic_elevation_position_whole_pixels(widgets, monkeypatch):
    widget = widgets("elevation", modern=False, show_elevation_progress=True, show_elevation_progress_line=True)
    reader(monkeypatch, "lap", "progress", 0.0)
    widget.timerEvent(None)
    assert widget.veh_pos == 0
    widget.grab()  # source width 0 drew whole lap as traveled
    reader(monkeypatch, "lap", "progress", 0.5001)
    widget.timerEvent(None)
    assert isinstance(widget.veh_pos, int) and widget.veh_pos == int(widget.display_width * 0.5001)
    reader(monkeypatch, "lap", "progress", math.nan)
    widget.timerEvent(None)
    assert widget.veh_pos == 0
    widget.grab()


# --- Lap time history (classic): oldest lap has no lap to compare with
def test_classic_lap_time_history_oldest_delta(widgets, monkeypatch):
    widget = widgets("lap_time_history", modern=False, show_delta=True, show_empty_history=False)
    laps = deque([ConsumptionDataSet(lapNumber=2, isValidLap=1, lapTimeLast=89.3),
                  ConsumptionDataSet(lapNumber=1, isValidLap=1, lapTimeLast=89.9)])
    widget.update_laps_history(laps)
    assert widget.bars_delta[1].text == "-0.60"
    assert set(widget.bars_delta[2].text) <= set("-.")  # dash placeholder, was +89.90 against empty lap


# --- Edit frame: size preview window never left on screen
def test_resize_ghost_closed_on_new_press_and_hide(ui_env):
    from tinypedal.widget._edit_frame import ResizeHandle

    parent = QWidget()
    parent.resize(100, 50)
    handle = ResizeHandle(parent, lambda factor: None)

    def press():
        handle.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(1, 1), QPointF(1, 1), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))

    press()
    first = handle._ghost
    assert first is not None and first.isVisible()
    press()  # release of first drag lost
    assert not first.isVisible() and handle._ghost is not first
    second = handle._ghost
    assert second is not None
    handle.hideEvent(QHideEvent())
    assert handle._ghost is None and not second.isVisible() and not handle.dragging
    parent.deleteLater()
    QCoreApplication.processEvents()


# --- Race notifications: class best never goes up (holder leaving), no false fastest lap on return
def test_class_best_not_raised_when_holder_leaves(monkeypatch):
    from tinypedal.widget.race_notifications import RaceEvents

    def car(best):
        return SimpleNamespace(vehicleClass="GT3", bestLapTime=best, driverName="Driver")

    def field(*cars):
        monkeypatch.setattr(minfo, "vehicles", SimpleNamespace(
            playerIndex=0, dataSet=list(cars), totalVehicles=len(cars)))

    events = RaceEvents({"show_class_fastest_lap": True})
    messages: list = []
    field(car(91.0), car(90.0))
    events.poll_class_best(messages)
    field(car(91.0))  # 90.0 holder disconnected
    events.poll_class_best(messages)
    assert events.class_best == 90.0
    field(car(91.0), car(90.0))  # back
    events.poll_class_best(messages)
    assert messages == []
    field(car(91.0), car(89.5))
    events.poll_class_best(messages)
    assert [message.title for message in messages] == ["Fastest lap"]


# --- Delta graph: lap counter going up before progress wraps completes the lap once
def test_delta_graph_lap_counter_before_progress_wrap(widgets, monkeypatch):
    from tinypedal.widget import delta_graph

    widget = widgets("delta_graph")
    monkeypatch.setattr(delta_graph, "delta_shown", lambda source: True)
    monkeypatch.setattr(minfo.delta, widget.delta_source, 0.2)
    reader(monkeypatch, "lap", "completed_laps", 1)
    for step in range(5, 99, 2):
        reader(monkeypatch, "lap", "progress", step / 100)
        reader(monkeypatch, "timing", "current_laptime", step)
        widget.read_graph()
    lap_samples = sum(1 for value in widget.trace.current if math.isfinite(value))
    assert lap_samples > widget.trace.samples // 2
    # Lap counter first, progress still at end of lap
    reader(monkeypatch, "lap", "completed_laps", 2)
    reader(monkeypatch, "lap", "progress", 0.995)
    reader(monkeypatch, "timing", "current_laptime", 0.05)
    widget.read_graph()
    reader(monkeypatch, "lap", "progress", 0.01)
    reader(monkeypatch, "timing", "current_laptime", 0.6)
    widget.read_graph()
    previous = sum(1 for value in widget.trace.previous if math.isfinite(value))
    assert previous >= lap_samples  # was lost: lap completed a second time on progress wrap


# --- Weather (classic): temperatures compared as pair, not sum
def test_classic_weather_temperature_change_with_same_sum(widgets, monkeypatch):
    widget = widgets("weather", modern=False, show_temperature=True, show_trend=False)
    reader(monkeypatch, "session", "track_temperature", 30.0)
    reader(monkeypatch, "session", "ambient_temperature", 20.0)
    widget.timerEvent(None)
    text = widget.bar_temp.text
    reader(monkeypatch, "session", "track_temperature", 31.0)
    reader(monkeypatch, "session", "ambient_temperature", 19.0)
    widget.timerEvent(None)
    assert widget.bar_temp.text != text


# --- Readable logo copies: whole-image recolor, same pixels as per-pixel reference
def reference_readable_copy(image: QImage, light_background: bool) -> QImage:
    """Previous per-pixel algorithm (reference)"""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            alpha = color.alpha()
            if not alpha:
                continue
            if light_background and custom_image.is_light_part(color):
                on_light = custom_image.ON_LIGHT
                image.setPixelColor(x, y, QColor(on_light.red(), on_light.green(), on_light.blue(), alpha))
            elif not light_background and custom_image.is_dark_part(color):
                hue = color.hsvHue()
                image.setPixelColor(x, y, QColor.fromHsv(
                    max(hue, 0), color.hsvSaturation() // 2, custom_image.ON_DARK_VALUE, alpha))
    return image


@pytest.mark.parametrize("source_format", [QImage.Format.Format_ARGB32, QImage.Format.Format_ARGB32_Premultiplied,
                                           QImage.Format.Format_RGB32])
@pytest.mark.parametrize("light_background", [True, False])
def test_readable_copy_matches_per_pixel_reference(source_format, light_background):
    rng = random.Random(7)
    image = QImage(23, 17, QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            kind = rng.random()
            if kind < 0.3:  # dark, gray & navy parts
                value = rng.randrange(0, 100)
                color = QColor(value, value, min(value + rng.randrange(0, 60), 255), rng.choice((0, 1, 128, 255)))
            elif kind < 0.6:  # white & light gray parts
                value = rng.randrange(190, 256)
                color = QColor(value, max(value - rng.randrange(0, 40), 0), value, rng.choice((0, 64, 255)))
            else:
                color = QColor(rng.randrange(256), rng.randrange(256), rng.randrange(256), rng.randrange(256))
            image.setPixelColor(x, y, color)
    image = image.convertToFormat(source_format)
    expected = reference_readable_copy(image, light_background)
    result = custom_image.readable_copy(image, light_background)
    assert result.format() == expected.format() == QImage.Format.Format_ARGB32
    assert result == expected
    assert custom_image.readable_copy(QImage(), light_background).isNull()


def test_logo_for_background_made_once_atomically_across_threads(ui_env, monkeypatch, tmp_path):
    monkeypatch.setattr(custom_image, "_tinted", {})
    black = QImage(200, 100, QImage.Format.Format_ARGB32)
    black.fill(QColor(0, 0, 0))
    path = str(tmp_path / "black.png")
    assert black.save(path)
    results = []
    threads = [threading.Thread(target=lambda: results.append(custom_image.logo_for_background(path, False)))
               for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(results)) == 1 and results[0] != path and os.path.isfile(results[0])
    folder = os.path.dirname(results[0])
    assert os.listdir(folder) == [os.path.basename(results[0])]  # no temporary file left
    assert QImage(results[0]).pixelColor(5, 5).value() == custom_image.ON_DARK_VALUE


# --- Game pictures: names percent-encoded, only "not found" remembered, empty game lists read again
class FakeGame:
    def __init__(self):
        self.answers: dict[str, tuple[int, bytes]] = {}
        self.asked: list[str] = []

    def __call__(self, resource: str) -> tuple[int, bytes]:
        resource.encode("ascii")  # real connection fails on a non-ASCII path
        self.asked.append(resource)
        return self.answers.get(resource, (404, b"<html>not found</html>"))


@pytest.fixture
def game(ui_env, monkeypatch):
    fake = FakeGame()
    monkeypatch.setattr(game_images, "fetch_from_game", fake)
    cache = game_images.GameImages()
    monkeypatch.setattr(game_images, "images", cache)
    return fake, cache


def test_game_picture_path_percent_encoded(game):
    fake, cache = game
    fake.answers["/start/images/manufacturer/Brand=Citro%C3%ABn%20DS.svg"] = (200, b"<svg/>")
    assert cache.fetch_picture(gi.BRAND, "Citroën DS")
    assert fake.asked == ["/start/images/manufacturer/Brand=Citro%C3%ABn%20DS.svg"]


@pytest.mark.parametrize("answer, remembered", [
    ((404, b"<html>not found</html>"), True),
    ((200, b"PK\x03\x04 not a picture"), True),
    ((500, b"error"), False),
    ((503, b""), False),
    ((200, b""), False),
])
def test_game_picture_missing_only_when_not_found(game, answer, remembered):
    fake, cache = game
    resource = gi.image_path(gi.BRAND, "Nobody")
    fake.answers[resource] = answer
    assert not cache.fetch_picture(gi.BRAND, "Nobody")
    assert (resource in cache.missing) is remembered


def test_empty_game_lists_read_again_later(game):
    fake, cache = game
    for route in (gi.VEHICLES_ROUTE, gi.CARS_ROUTE, gi.TRACKS_ROUTE):
        fake.answers[route] = (200, b"null")  # outside a session
    assert not cache.read_game_lists()
    assert not cache._catalog_read and cache._catalog_retry > 0  # asked again after a delay
    fake.answers[gi.CARS_ROUTE] = (200, json.dumps([{"desc": "BMW Team WRT #46", "manufacturer": "BMW"}]).encode())
    assert cache.read_game_lists()
    assert cache._catalog_read and cache.brand("BMW Team WRT #46") == "BMW"
