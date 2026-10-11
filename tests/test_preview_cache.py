"""Overlay pictures kept by inputs & shared by pages (widget_preview), store without copies, released when idle"""

import weakref

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from neopedal import app_signal, demo_data
from neopedal.setting import cfg
from neopedal.ui import widget_preview
from neopedal.ui.quick.preview_provider import PreviewProvider, PreviewStore


def solid(color: str, width: int = 40, height: int = 20) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(color))
    return image


def pixels(image: QImage) -> bytes:
    return bytes(image.constBits())[: image.sizeInBytes()]


@pytest.fixture
def draws(ui_env, bundled_fonts, monkeypatch):
    """Pictures drawn (widget name, scale), cache emptied"""
    widget_preview.CACHE.clear()
    monkeypatch.setattr(widget_preview, "_showing", weakref.WeakSet())  # pages of earlier tests not counted
    calls = []
    real = widget_preview.render_widget

    def render(config, name, setting, scale=1.0):
        calls.append((name, scale))
        return real(config, name, setting, scale)

    monkeypatch.setattr(widget_preview, "render_widget", render)
    yield calls
    widget_preview.CACHE.clear()


def test_same_inputs_same_picture_on_any_page(draws):
    from neopedal.ui.quick import overlay_backend, overlay_options_backend, setup_backend

    page = overlay_backend.render_preview("speedometer")
    assert page is not None and draws == [("speedometer", 1.0)]
    options = overlay_options_backend.render_overlay("speedometer", dict(cfg.user.setting["speedometer"]))
    assert options is not None and options.cacheKey() == page.cacheKey()  # fits card: same picture, not drawn
    wizard = setup_backend.render_overlay("speedometer", cfg.user.setting["speedometer"], cfg.user.config["overlay_style"])
    assert wizard is not None and wizard.cacheKey() == page.cacheKey()
    assert len(draws) == 1
    edited = dict(cfg.user.setting["speedometer"], font_size=cfg.user.setting["speedometer"]["font_size"] + 4)
    assert overlay_options_backend.render_overlay("speedometer", edited).cacheKey() != page.cacheKey()
    overlay_options_backend.render_overlay("speedometer", edited, 2.0)
    assert draws[1:] == [("speedometer", 1.0), ("speedometer", 2.0)]
    moved = dict(cfg.user.setting["speedometer"], position_x=999, enable=True)  # never drawn
    assert overlay_options_backend.render_overlay("speedometer", moved).cacheKey() == page.cacheKey()
    assert len(draws) == 3


def test_bigger_overlay_scaled_down_from_kept_picture(draws):
    setting = cfg.user.setting["standings"]
    full = widget_preview.render_image(cfg, "standings", setting)
    small = widget_preview.render_image(cfg, "standings", setting, max_size=QSize(100, 60))
    assert full is not None and small is not None and len(draws) == 1
    ratio = small.devicePixelRatio()
    assert small.width() <= 100 * ratio and small.height() <= 60 * ratio
    again = widget_preview.render_image(cfg, "standings", setting, max_size=QSize(100, 60))
    assert again.cacheKey() == small.cacheKey()


def test_shared_inputs_read_once_per_refresh(draws, monkeypatch):
    reads = []
    real = widget_preview._read_shared
    monkeypatch.setattr(widget_preview, "_read_shared", lambda: reads.append(1) or real())
    widget_preview.inputs_changed()
    first = widget_preview.render_image(cfg, "gear", cfg.user.setting["gear"])
    widget_preview.render_image(cfg, "gear", cfg.user.setting["gear"])
    assert reads == [1] and len(draws) == 1
    monkeypatch.setitem(cfg.units, "speed_unit", "MPH" if cfg.units.get("speed_unit") != "MPH" else "KPH")
    widget_preview.render_image(cfg, "gear", cfg.user.setting["gear"])
    assert reads == [1]  # setting not refreshed yet
    app_signal.refresh.emit(True)
    second = widget_preview.render_image(cfg, "gear", cfg.user.setting["gear"])
    assert reads == [1, 1] and len(draws) == 2 and second.cacheKey() != first.cacheKey()


def test_cache_budget_drops_least_recently_used():
    cache = widget_preview.PictureCache(budget=solid("#000000").sizeInBytes() * 2)
    for key in ("a", "b"):
        cache.put((key,), solid("#ff0000"))
    assert cache.get(("a",))[0]  # used: kept
    cache.put(("c",), solid("#00ff00"))
    assert [cache.get((key,))[0] for key in ("a", "b", "c")] == [True, False, True]
    cache.put(("none",), None)  # overlay without picture: kept, no size
    assert cache.get(("none",)) == (True, None) and cache.size == solid("#000000").sizeInBytes() * 2


def test_dump_reads_dict_changed_by_module_thread_again():
    class Changing(dict):
        failures = 2

        def items(self):
            if Changing.failures:
                Changing.failures -= 1
                raise RuntimeError("dictionary changed size during iteration")
            return super().items()

    assert widget_preview.dump(Changing(b=1, a=2)) == '{"a":2,"b":1}'
    assert widget_preview.dump({1: "x", "y": 2}) == repr({1: "x", "y": 2})  # keys not sortable


def test_released_once_no_page_shows_pictures(draws):
    first, second = object.__new__(type("Page", (), {})), object.__new__(type("Page", (), {}))
    widget_preview.set_showing(first, True)
    widget_preview.set_showing(second, True)
    widget_preview.render_image(cfg, "gear", cfg.user.setting["gear"])
    assert demo_data._session is not None and len(widget_preview.CACHE)
    widget_preview.set_showing(first, False)
    assert not widget_preview.release_idle()  # other page still shows pictures
    widget_preview.set_showing(second, False)
    assert widget_preview.release_idle()
    assert demo_data._session is None and not len(widget_preview.CACHE)


def test_lap_widget_shapes_built_once(draws, monkeypatch):
    """Delta graph replay: trace fed every frame, chart shapes built once, same picture"""
    from contextlib import nullcontext

    from neopedal.widget import delta_graph

    setting = cfg.user.setting["delta_graph"]
    builds = []
    real = delta_graph.DeltaGraphMixin.build_shapes
    monkeypatch.setattr(delta_graph.DeltaGraphMixin, "build_shapes", lambda self: builds.append(1) or real(self))
    widget_preview.render_widget(cfg, "delta_graph", dict(setting))  # painter caches warm
    builds.clear()
    deferred = widget_preview.render_widget(cfg, "delta_graph", dict(setting)).toImage()
    assert len(builds) == 1
    monkeypatch.setattr(demo_data, "shapes_deferred", lambda widget: nullcontext())
    replayed = widget_preview.render_widget(cfg, "delta_graph", dict(setting)).toImage()
    assert len(builds) > 50
    assert deferred.size() == replayed.size() and pixels(deferred) == pixels(replayed)


def test_store_shares_pictures_and_compares_cheaply(monkeypatch):
    from neopedal.ui.quick import preview_provider

    store = PreviewStore()
    image = solid("#123456")
    url = store.put("k", image)
    shared = store.get("k")
    assert shared is not None and shared.cacheKey() == image.cacheKey()  # no deep copy per request
    provided = PreviewProvider(store).requestImage("k?v=1", QSize(), QSize())
    assert provided.cacheKey() == image.cacheKey()
    compared = []
    monkeypatch.setattr(QImage, "__eq__", lambda self, other: compared.append(1) or True)
    assert store.put("k", shared) == url and not compared  # same shared picture: no pixel compare
    monkeypatch.setattr(preview_provider, "COMPARE_LIMIT", 10)
    assert store.put("k", solid("#123456")) != url and not compared  # big picture: new serial, never compared
