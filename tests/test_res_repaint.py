"""Overlay repaint cost: repaint rate governor, track map / gear / steering wheel repainted only when drawn
in other device pixels, shape cache memory budget, far apart table rows repainted one by one, layout guide
changed parts, failed brand lookups cached"""

from importlib import import_module

import pytest
from PySide6.QtCore import QRect


@pytest.fixture
def make_widget(ui_env, bundled_fonts):
    from neopedal.setting import cfg
    from neopedal.widget._modern import create_widget

    widgets = []

    def make(name: str, modern: bool, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        widgets.append(widget)
        return widget

    yield make
    for widget in widgets:
        widget.deleteLater()


def count_updates(monkeypatch, widget) -> list:
    calls = []
    monkeypatch.setattr(widget, "update", lambda *args: calls.append(args))
    return calls


# Repaint rate governor
def test_request_update_rate_governor(make_widget, monkeypatch):
    from neopedal.widget import _base

    widget = make_widget("track_map", False)
    calls = count_updates(monkeypatch, widget)
    now = [100.0]
    monkeypatch.setattr(_base, "monotonic", lambda: now[0])
    assert type(widget).max_repaint_rate == 25
    widget.request_update()
    assert len(calls) == 1
    now[0] += 0.01  # sooner than 40 ms: deferred
    widget.request_update()
    widget.request_update()
    assert len(calls) == 1
    timer = widget._repaint_timer
    assert timer.isActive() and timer.interval() == 30
    timer.stop()
    widget._deferred_repaint()  # timer fired: final state painted
    assert len(calls) == 2
    now[0] += 0.05
    widget.request_update()
    assert len(calls) == 3


def test_request_update_without_limit(make_widget, monkeypatch):
    widget = make_widget("gear", True)
    calls = count_updates(monkeypatch, widget)
    widget.request_update()
    widget.request_update()
    assert len(calls) == 2 and "_repaint_timer" not in widget.__dict__


def test_deferred_repaint_after_stop_does_nothing(make_widget):
    widget = make_widget("track_map", True)
    calls: list = []
    # Assigned, not monkeypatched: the dict is cleared below, the undo of pytest (delattr since 9.2) would raise
    widget.update = lambda *args: calls.append(args)  # type: ignore[method-assign]
    widget.__dict__.clear()  # unloaded (stopped)
    widget._deferred_repaint()
    assert not calls


# Track map: repaint when a car moves a device pixel
@pytest.mark.parametrize("modern", (False, True))
def test_track_map_repaints_on_visible_move_only(make_widget, monkeypatch, modern):
    import math

    from neopedal.module_info import TrackMap, minfo

    oval = tuple((600 * math.cos(i / 200 * math.tau), 350 * math.sin(i / 200 * math.tau)) for i in range(200))
    monkeypatch.setattr(minfo.mapping, "trackMap", TrackMap(oval, tuple((i * 20.0, 0.0) for i in range(200)),
                                                            (66, 133), 3.0))
    widget = make_widget("track_map", modern)
    widget.max_repaint_rate = 0
    calls = count_updates(monkeypatch, widget)
    monkeypatch.setattr(minfo.relative, "drawOrder", [0, 1])
    car = minfo.vehicles.dataSet[1]
    monkeypatch.setattr(car, "worldPositionX", 600.0)
    monkeypatch.setattr(car, "worldPositionY", 0.0)

    def tick(pos_y: float):
        car.worldPositionY = pos_y
        minfo.vehicles.dataSetVersion += 1
        widget.timerEvent(None)

    monkeypatch.setattr(minfo.vehicles, "dataSetVersion", 1000)
    tick(0.0)
    first = len(calls)
    assert first >= 1
    assert widget.car_positions is not None and [index for index, *_ in widget.car_positions] == [0, 1]
    tick(1e-4)  # far less than a pixel on track map: no repaint
    assert len(calls) == first
    tick(200.0)
    assert len(calls) == first + 1
    widget.timerEvent(None)  # same data
    assert len(calls) == first + 1
    widget.grab()  # paint draws stored positions


def test_track_map_default_interval():
    from neopedal.template.setting_widget import WIDGET_DEFAULT

    assert WIDGET_DEFAULT["track_map"]["update_interval"] == 50
    for name in ("fuel", "virtual_energy", "flag"):
        assert WIDGET_DEFAULT[name]["update_interval"] == 100


# Gear & steering wheel
def test_gear_rpm_bar_repaints_on_pixel_change(make_widget, monkeypatch):
    from neopedal.api_control import api

    widget = make_widget("gear", True, show_rpm_bar=True)
    calls = count_updates(monkeypatch, widget)
    engine = api.read.engine
    monkeypatch.setattr(engine, "rpm_max", lambda: 10000.0)
    rpm = [9000.0]
    monkeypatch.setattr(engine, "rpm", lambda: rpm[0])
    widget.timerEvent(None)
    first = len(calls)
    flicker = widget.flicker
    rpm[0] = 9000.4  # same bar pixel, same zone
    widget.flicker = flicker
    widget.timerEvent(None)
    assert len(calls) == first
    rpm[0] = 9600.0
    widget.flicker = flicker
    widget.timerEvent(None)
    assert len(calls) == first + 1


def test_classic_gear_rpm_bar_repaints_on_pixel_change(make_widget, monkeypatch):
    widget = make_widget("gear", False, show_rpm_bar=True, show_rpm_reading=False)
    bar = widget.bar_rpmbar
    calls = count_updates(monkeypatch, bar)
    widget.rpm_safe, widget.rpm_range = 5000, 5000
    widget.update_rpmbar(bar, 9000.0)
    widget.update_rpmbar(bar, 9000.5)  # less than a pixel
    assert len(calls) == 1
    widget.update_rpmbar(bar, 9500.0)
    assert len(calls) == 2
    widget.update_rpmbar(bar, float("nan"))
    assert len(calls) == 3


@pytest.mark.parametrize("modern", (False, True))
def test_steering_wheel_repaints_on_pixel_change(make_widget, monkeypatch, modern):
    from neopedal.api_control import api

    widget = make_widget("steering_wheel", modern, manual_steering_range=900, show_steering_angle=False)
    calls = count_updates(monkeypatch, widget)
    steering = [0.1]
    monkeypatch.setattr(api.read.inputs, "steering_raw", lambda: steering[0])
    widget.timerEvent(None)
    first = len(calls)
    steering[0] = 0.1 + 0.2 / 450  # 0.2 degree: less than a pixel at rim of a small wheel
    widget.timerEvent(None)
    assert len(calls) == first
    steering[0] = 0.2
    widget.timerEvent(None)
    assert len(calls) == first + 1


# Shape cache memory budget
def test_shape_cache_byte_budget():
    from PySide6.QtGui import QColor

    from neopedal.widget._modern import draw

    draw._shape_cache.clear()
    draw._shape_seen.clear()
    color = QColor(10, 20, 30)
    for size in range(100, 250):  # each about 160 KB at 200 px
        for _ in range(2):  # cached on second sighting
            draw._cached_shape(size, 200, 8, color, 1.0)
    total = sum(key[0] * key[1] * 4 for key in draw._shape_cache)
    assert 0 < total <= draw._SHAPE_CACHE_BYTES
    assert (249, 200, 8.0, color.rgba(), 1.0) in draw._shape_cache  # newest kept
    draw._shape_cache.clear()
    draw._shape_seen.clear()


# Table rows: far apart changed parts repainted one by one
def test_flush_clusters():
    from neopedal.widget._modern.table import MAX_FLUSHES, flush_clusters

    top = QRect(0, 0, 400, 20)
    bottom = QRect(0, 580, 400, 20)
    assert flush_clusters([top]) is None
    assert flush_clusters([top, bottom]) == [top, bottom]  # whole table between them otherwise
    near = QRect(0, 22, 400, 20)
    assert flush_clusters([top, near]) is None  # adjacent rows: one repaint
    assert flush_clusters([top, near, bottom]) == [top.united(near), bottom]
    many = [QRect(0, index * 100, 400, 20) for index in range(MAX_FLUSHES + 1)]
    assert flush_clusters(many) is None


def test_table_far_rows_repainted_one_by_one(make_widget, monkeypatch):
    widget = make_widget("standings", True)
    painted = []
    monkeypatch.setattr(widget, "repaint", lambda rect: painted.append(rect))
    monkeypatch.setattr(widget, "isVisible", lambda: True)
    monkeypatch.setattr(widget, "row_slots", lambda rows: dict(rows))
    monkeypatch.setattr(widget, "logos_arrived", lambda: False)
    monkeypatch.setattr(widget, "changed_rects", lambda top, before, after: [widget.row_update_rect(top)])
    widget.static_layer()
    widget.state = ((0.0, "a"), (400.0, "b"))
    assert widget.refresh_rows(((0.0, "x"), (400.0, "y")))
    assert len(painted) == 2 and all(rect.height() < 100 for rect in painted)


# Layout guide: changed parts only, each repainted on its own
def test_layout_guide_changed_rects(ui_env):
    from neopedal.widget._layout_guide import changed_rects

    edges = [QRect(0, 0, 10, 4)]
    old = (edges, frozenset({(99, 0, 3, 600)}))
    new = ([QRect(1, 0, 10, 4)], frozenset({(99, 0, 3, 600), (199, 0, 3, 600)}))
    assert changed_rects(old, new) == [QRect(0, 0, 11, 4), QRect(199, 0, 3, 600)]  # unchanged line not repainted
    far: tuple[list[QRect], frozenset] = ([QRect(500, 500, 10, 4)], frozenset())
    assert QRect(500, 500, 10, 4) in changed_rects(old, far)
    assert changed_rects(([], frozenset()), new)[0] == QRect(1, 0, 10, 4)


def test_layout_guide_repaints_small_parts(ui_env, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from neopedal.widget import _layout_guide

    target = QWidget()
    target.setGeometry(100, 100, 80, 40)
    guide = _layout_guide.LayoutGuide()
    guide.setGeometry(QRect(0, 0, 800, 600))
    guide._others = [QRect(100, 300, 50, 50)]
    painted = []
    monkeypatch.setattr(guide, "repaint", lambda rect: painted.append(rect))
    monkeypatch.setattr(guide, "isVisible", lambda: True)
    guide.track(target)
    painted.clear()
    target.move(101, 101)  # line x=100 left
    guide.track(target)
    assert painted and all(rect.width() * rect.height() < 800 * 600 / 4 for rect in painted)
    assert QRect(99, 0, 3, 600) in painted  # line gone
    guide.deleteLater()
    target.deleteLater()


# Brands: failed lookup not searched again
def test_brand_failed_lookup_cached(ui_env, monkeypatch):
    from neopedal.api_control import api
    from neopedal.userfile import brands

    brands._no_brand.clear()
    searched = []
    monkeypatch.setattr(api.read.vehicle, "vehicle_model", lambda index=None: "#12 99")
    original = brands.extract_lmu_brand_name

    def extract(value, default):
        searched.append(value)
        return original(value, default)

    monkeypatch.setattr(brands, "extract_lmu_brand_name", extract)
    assert brands.select_brand_name(0, "Car 12") == ""
    assert brands.select_brand_name(0, "Car 12") == ""
    assert len(searched) == 1
    monkeypatch.setattr(api.read.vehicle, "vehicle_model", lambda index=None: "Porsche 963")  # model arrived
    assert brands.select_brand_name(0, "Car 12") == "Porsche"
    brands._no_brand.clear()


def test_extract_brand_name():
    from neopedal.userfile.brands import extract_lmu_brand_name

    assert extract_lmu_brand_name("Porsche 963", "") == "Porsche"
    assert extract_lmu_brand_name("#12 99", "x") == "x"
    assert extract_lmu_brand_name(None, "x") == "x"  # type: ignore[arg-type]
