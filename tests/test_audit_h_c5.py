"""Audit h, lot c5: Broadcast Director page split in parts (game, camera, graphics, timing, log: child QObjects,
QML backend.<part>), app context (neopedal.context, ctx of widgets, modules & pages, app_ctx test fixture)"""

import dataclasses
import gc
import weakref
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject

from tests.test_broadcast_director import car, director_page, poll, race_answers  # noqa: F401

PARTS = ("game", "camera", "graphics", "timing", "log")


# --- Director parts
def test_parts_are_constant_children_of_the_page(director_page):  # noqa: F811
    backend = director_page.backend
    meta = backend.metaObject()
    for name in PARTS:
        part = getattr(backend, name)
        assert part is getattr(backend, f"_{name}") and part.parent() is backend and part.page is backend
        prop = meta.property(meta.indexOfProperty(name))
        assert prop.isValid() and prop.isConstant()


def test_page_settings_keep_every_key(director_page):  # noqa: F811
    keys = set(director_page.backend.page_settings())
    assert keys == {"mode", "min_shot", "max_shot", "battle_gap", "camera_style", "follow_overlays", "seconds_before",
                    "post_roll", "follow_game_cuts", "game_host", "log_events", "graphics", "notes", "championship",
                    "championship_class", "timing", "timing_view", "enabled"}


def test_parentless_page_freed_without_garbage_collector(ui_env):
    """Parts hold their page weakly: a page without parent is freed at once (UI thread), never by the GC"""
    from neopedal.ui.quick.director_backend import DirectorBackend

    gc.collect()
    gc.disable()
    try:
        backend = DirectorBackend(None)
        backend.release()
        timing = weakref.ref(backend.timing)
        ref = weakref.ref(backend)
        del backend
        assert ref() is None and timing() is None
    finally:
        gc.enable()


def test_release_stops_every_part(director_page):  # noqa: F811
    page, backend = director_page, director_page.backend
    backend.graphics.setGraphic("onboard", True)
    poll(page, race_answers(100.0, car(1, 1), car(2, 2)))
    backend.camera.command_queue.append((("PUT", "/rest/x"),))
    backend.graphics._publish_timer.start(10_000)
    backend.release()
    assert not backend.is_open and not backend.game._timer.isActive() and backend.game._connection is None
    assert not backend.graphics._live_timer.isActive() and not backend.graphics._publish_timer.isActive()
    assert backend.camera.command_queue == []


def test_director_panels_load_without_qml_warnings(director_page):  # noqa: F811
    from PySide6.QtCore import qInstallMessageHandler

    page, backend = director_page, director_page.backend
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        poll(page, race_answers(100.0, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0)))
        root = page.view.rootObject()
        for name in ("graphicsPopup", "settingsPopup", "timingTable"):
            item = root.findChild(QObject, name)
            assert item is not None, name
            for tab in (0, 1, 2) if name == "graphicsPopup" else (0,):
                if name == "graphicsPopup":
                    item.setProperty("tab", tab)
                item.setProperty("visible", True)
                QCoreApplication.processEvents()
            item.setProperty("visible", False)
        backend.selectCar(1)
        backend.showLaps(1)
        poll(page, race_answers(101.0, car(1, 1, distance=1090.0), car(2, 2, distance=1050.0)))
        QCoreApplication.processEvents()
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


# --- App context
def test_app_context_is_the_real_globals():
    from neopedal import context
    from neopedal.api_control import api
    from neopedal.module_control import mctrl, wctrl
    from neopedal.module_info import minfo
    from neopedal.overlay_control import octrl
    from neopedal.setting import cfg

    ctx = context.app_context()
    assert (ctx.api, ctx.cfg, ctx.minfo, ctx.mctrl, ctx.wctrl, ctx.octrl) == (api, cfg, minfo, mctrl, wctrl, octrl)
    assert ctx is context.app_context()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.api = None  # type: ignore[misc]
    other = ctx.with_(minfo="fake")
    assert other.minfo == "fake" and ctx.minfo is minfo and other.api is api


def test_app_ctx_swaps_globals_everywhere_and_restores():
    from neopedal import context, loader, module_control
    from tests.conftest import ContextSwap

    real = module_control.mctrl
    fake = SimpleNamespace(names=[])
    swap = ContextSwap()
    ctx = swap.use(mctrl=fake)
    try:
        assert module_control.mctrl is fake and loader.mctrl is fake  # every copy of the global
        assert context.app_context() is ctx and ctx.mctrl is fake and ctx.wctrl is module_control.wctrl
    finally:
        swap.restore()
    assert module_control.mctrl is real and loader.mctrl is real and context.app_context().mctrl is real
    with pytest.raises(TypeError):
        ContextSwap().use(nothing=1)


def test_ctx_of_widgets_modules_and_pages(ui_env, app_ctx):
    from neopedal.module._base import DataModule
    from neopedal.setting import cfg
    from neopedal.ui.quick.page_backend import PageBackend
    from neopedal.widget._base import Base

    ctx = app_ctx(minfo=SimpleNamespace())
    assert DataModule(cfg, "module_force").ctx is ctx
    other = ctx.with_(api=SimpleNamespace())
    assert DataModule(cfg, "module_force", ctx=other).ctx is other
    page = PageBackend(None)
    assert page.ctx is ctx and PageBackend(None, ctx=other).ctx is other
    widget = Base(cfg, "brake_bias")
    try:
        assert widget.ctx is ctx and Base(cfg, "brake_bias", ctx=other).ctx is other
    finally:
        widget.deleteLater()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
