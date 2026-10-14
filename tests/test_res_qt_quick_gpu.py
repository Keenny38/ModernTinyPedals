"""Qt Quick GPU cost: no window MSAA (chart & map lines in multisampled layers only while shown), track map play
steps about 30 times a second on wall clock time, live replay map idle once shared memory cars stop"""

import inspect
import time

import pytest
from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtQml import QQmlProperty

from neopedal.setting import cfg
from tests.test_game_info import GAME_ANSWERS, answered, replays_page  # noqa: F401
from tests.test_perf_page_state import delete_now, process_events, qml_warnings  # noqa: F401


def layer_on(item) -> bool:
    return bool(QQmlProperty(item, "layer.enabled").read())


def tree(root) -> list:
    stack, found = [root], []
    while stack:
        item = stack.pop()
        found.append(item)
        stack.extend(item.childItems())
    return found


def named(view, name: str):
    return next(item for item in tree(view.rootObject()) if item.objectName() == name)


def test_quick_views_without_window_msaa():
    from neopedal.ui.quick import create_quick_view

    assert inspect.signature(create_quick_view).parameters["samples"].default == 0


def test_track_map_layers_and_play_rate(ui_env, qml_warnings):  # noqa: F811
    from neopedal.ui.track_map_viewer import TrackMapViewer
    from tests.test_track_map_viewer import write_map

    write_map(cfg.path.track_map)
    viewer = TrackMapViewer(None, cfg.path.track_map, "Ring")
    try:
        assert viewer.view.format().samples() <= 0
        viewer.resize(900, 700)
        viewer.show()
        process_events(0.2)
        root, backend = viewer.view.rootObject(), viewer.backend
        assert backend.loaded
        lines = named(viewer.view, "mapLines")
        assert layer_on(lines) and QQmlProperty(lines, "layer.samples").read() == 4
        steps: list[float] = []
        backend.positionChanged.connect(lambda: steps.append(backend.property("position")))
        backend.setPosition(10.0)
        steps.clear()
        start = time.monotonic()
        root.setProperty("playing", True)
        process_events(1.0)
        root.setProperty("playing", False)
        elapsed = time.monotonic() - start
        assert 10 < len(steps) <= elapsed * 30 * 1.3 + 2  # about 30 steps a second, not one per vsync
        speed = root.property("playSpeed")
        assert steps[-1] - 10.0 == pytest.approx(speed * elapsed, rel=0.25)  # moved by wall clock time
        viewer.hide()
        process_events(0.05)
        assert not layer_on(lines)  # layer texture released while hidden
    finally:
        viewer.close()
        delete_now(viewer)


def test_live_map_cars_glide_then_page_idle(replays_page, monkeypatch):  # noqa: F811
    from tests.test_game_replays_perf import has_property
    from tests.test_replay_map_motion import FakeReader

    backend = replays_page.backend
    reader = FakeReader([(7, 120.0, -30.0)])
    monkeypatch.setattr(type(backend), "reader", staticmethod(lambda: reader))
    backend.setPanel(2)
    answered(replays_page, GAME_ANSWERS)
    replays_page.resize(1400, 860)
    replays_page.show()
    process_events(0.5)  # glide from place of game answer to first shared memory place done
    view = replays_page.view
    panel = has_property(view, "liveTracking")[0]
    assert panel.property("liveTracking")
    assert layer_on(named(view, "mapLines"))
    car = {item.property("key"): item for item in has_property(view, "liveStep")}["7"]
    assert car.property("tracked") and car.property("trackPoint") is None
    assert (car.property("worldX"), car.property("worldY")) == (pytest.approx(120.0), pytest.approx(30.0))
    ticker = next(child for child in panel.children() if child.metaObject().className() == "QQmlTimer"
                  and child.property("interval") == 33)
    process_events(0.4)
    assert not ticker.property("running")  # cars still: no tick, no frame
    reader.vehicle.cars = [(7, 140.0, -30.0)]
    backend.read_live_positions()
    QCoreApplication.processEvents()
    assert ticker.property("running")
    process_events(0.1)
    halfway = car.property("worldX")
    assert 120.0 < halfway < 140.0  # glides from shown place
    process_events(0.4)
    assert car.property("worldX") == pytest.approx(140.0) and car.property("worldY") == pytest.approx(30.0)
    assert not ticker.property("running")  # glide done: page idle again
    replays_page.hide()
    process_events(0.05)
    assert not layer_on(named(view, "mapLines"))
    backend.release()


def test_incident_playhead_moves_four_times_a_second(replays_page):  # noqa: F811
    replays_page.backend.setPanel(0)
    replays_page.show()
    process_events(0.3)
    clocks = [child for child in replays_page.view.rootObject().findChildren(QObject)
              if child.metaObject().indexOfProperty("maxGap") >= 0]  # LiveClock timers
    playhead = [clock for clock in clocks if clock.property("triggeredOnStart")]  # incident timeline playhead
    assert playhead and all(clock.property("interval") >= 250 for clock in clocks)
    replays_page.backend.release()
