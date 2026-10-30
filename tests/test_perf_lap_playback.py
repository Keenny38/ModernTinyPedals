"""Lap viewer per frame work (audit lot 7): one backend call per playback frame (cursor line & cars every frame, values
about 30 times a second), trails built again only for laps that moved, steering arc as scene graph geometry, tooltips
built only while hovered, Show menu chips kept on toggles, histogram bars read by index with one mouse area, corner
labels moved with map, session chart drawn as GPU shapes"""

import json
import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQml import QQmlEngine, QQmlProperty
from PySide6.QtTest import QTest

from neopedal.ui.quick.lines import VertexStore, Vertices
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import (  # noqa: F401
    center_of,
    chart_of,
    class_name,
    evaluate,
    find,
    items,
    named,
    opener,
    track_maps,
    wait,
    warnings,
)


def js(view, scope, expression: str):
    """Value of a QML expression as Python data"""
    return json.loads(evaluate(view, scope, f"JSON.stringify({expression})"))


def tooltip_text(item) -> str:
    return QQmlProperty(item, "ToolTip.text", QQmlEngine.contextForObject(item)).read()


def stored(key: str) -> Vertices:
    vertices = VertexStore.get(key)
    assert vertices is not None
    return vertices


def flat_map(points: list[dict]) -> list[float]:
    return [value for point in points for value in (point["x"], point["y"], point["angle"])]


# --- Playback: one call per frame
def test_playback_step_light_and_full(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    seconds = backend.referenceLapTime / 2
    x = backend.xAtReferenceTime(seconds)
    step = backend.playbackStep(seconds, False)
    assert set(step) == {"x", "mapXY", "gXY"} and step["x"] == pytest.approx(x)
    assert backend._map_shown and step["mapXY"] == pytest.approx(flat_map(backend.mapPointer.mapCursor(x)))
    assert step["gXY"] == []  # G circle hidden: not worked out
    full = backend.playbackStep(seconds, True)
    assert set(full) == {"x", "state"} and full["state"] is backend.cursorState(x)  # same state (cached)
    backend.setSideTab(1)
    wait(0.3)
    step = backend.playbackStep(seconds, False)
    flat_g = [value for point in backend.gCursor(x) for value in (point["x"], point["y"])]
    assert step["gXY"] == pytest.approx(flat_g) and len(flat_g) > 0
    if not backend._map_shown:
        assert step["mapXY"] == []


def test_playback_frames_move_cars_values_at_30hz(opener, warnings, monkeypatch):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    chart = chart_of(view)
    calls = {"full": 0, "light": 0}
    cursor_state, map_positions = backend.cursorState, backend.mapPointer.map_positions

    def counted_state(x):
        calls["full"] += 1
        return cursor_state(x)

    def counted_positions(x, texts=False):
        if not texts:
            calls["light"] += 1
        return map_positions(x, texts)

    monkeypatch.setattr(backend, "cursorState", counted_state)  # playbackStep calls it through instance
    monkeypatch.setattr(backend.mapPointer, "map_positions", counted_positions)
    evaluate(view, chart, "togglePlay()")
    assert chart.property("playing")
    wait(1.0)
    frames = calls["full"] + calls["light"]
    assert frames > 5
    assert calls["full"] <= 30 * 1.0 * 1.6 + 3  # about 30 full states a second, whatever the frame rate
    count = int(evaluate(view, chart, "cursorMap.length"))
    assert count > 0 and int(evaluate(view, chart, "cursorMapXY.length")) == count * 3
    evaluate(view, chart, "togglePlay()")  # paused: values of last played frame
    wait(0.1)
    x = chart.property("cursorX")
    assert chart.property("cursorTitle") == backend.cursorTitle(x)
    expected = flat_map(backend.mapPointer.mapCursor(x))
    assert js(view, chart, "cursorMapXY") == pytest.approx(expected)
    # Cars placed from flat positions
    side_map = track_maps(view, False)[0]
    canvas = find(view, lambda item: item.property("targetZoom") is not None and item.property("feet") is not None)[0]
    cars = [item for item in items(side_map) if item.property("placed") is not None and item.property("at") is not None]
    assert len(cars) == count
    first = next(car for car in cars if car.property("at") == 0)
    assert first.property("x") == pytest.approx(evaluate(view, canvas, f"screenX({expected[0]})"), abs=0.01)
    assert first.property("y") == pytest.approx(evaluate(view, canvas, f"screenY({expected[1]})"), abs=0.01)


def test_trails_built_again_only_for_moved_laps(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    if not backend._map or not backend._map_options.get("trail") or not backend._map_shown:
        pytest.skip("no map trail")
    lines = backend._map["lines"]
    if len(lines) < 2:
        pytest.skip("one lap shown")
    backend.build_trails(600.0)
    serials = [stored(line["trail"]).serial for line in lines]
    revision = backend.trailRevision
    state = backend._trail_state
    built = list(state[2])
    built[1] = math.nan  # lap 1 not built yet: only its trail built again
    backend._trail_state = (state[0], state[1], built)
    backend.build_trails(600.0)
    after = [stored(line["trail"]).serial for line in lines]
    assert after[1] != serials[1] and [serial for index, serial in enumerate(after) if index != 1] == [
        serial for index, serial in enumerate(serials) if index != 1]
    assert backend.trailRevision == revision + 1
    backend.build_trails(600.0)  # nothing moved: nothing built
    assert backend.trailRevision == revision + 1


# --- Steering wheel arc: scene graph geometry (no Canvas)
def test_arc_triangles():
    from neopedal.ui.quick.lines import arc_triangles

    assert len(arc_triangles(50, 50, 40, 0.3, 4)) == 0  # under half a degree: nothing
    assert len(arc_triangles(50, 50, 0, 90, 4)) == 0
    for sweep in (90.0, -200.0, 720.0):
        data = arc_triangles(50, 50, 40, sweep, 4)
        points = list(zip(data[0::2], data[1::2]))
        assert len(points) % 3 == 0 and points
        assert all(abs(math.hypot(x - 50, y - 50) - 40) <= 2 + 2.01 for x, y in points)  # band & caps
        # Arc starts at top & turns clockwise for a positive sweep (screen y down)
        side = [x - 50 for x, y in points if math.hypot(x - 50, y - 50) > 41.5 and y < 50 - 20]
        assert side and (max(side) > 5 if sweep > 0 else min(side) < -5)


def test_steering_arc_item_in_simple_view(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSimpleView(True)
    wait(0.3)
    chart = chart_of(view)
    evaluate(view, chart, f"setCursor({chart.property('maxX') / 3}, 'pin')")
    wait(0.2)
    simple = find(view, lambda item: class_name(item).startswith("SimpleView"))[0]
    arcs = [item for item in items(simple) if class_name(item) == "ArcItem"]
    assert arcs and not [item for item in items(simple) if "Canvas" in class_name(item)]
    assert all(arc.property("radius") > 0 and arc.property("thickness") > 0 for arc in arcs)
    tooltips = [item for item in items(simple) if item.property("entries") is not None
                and item.property("titleText") is not None]
    assert tooltips  # bar & wheel items: tooltip text built only while hovered
    for item in tooltips:
        assert tooltip_text(item) == ""


# --- Show menu: chips kept on toggles
def test_show_menu_chips_kept_on_toggle(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    button = named(view, "showButton")
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center_of(button))
    wait(0.5)
    channels = named(view, "showList")
    chips = [item for item in items(channels) if item.objectName() == "showChip"]
    told = []
    backend.dashboard.channelsChanged.connect(lambda: told.append(1))
    target = next(chip for chip in chips if chip.isVisible() and not chip.property("shown"))
    key = target.property("channel")
    backend.setChannelVisible(key, True)
    wait(0.3)
    after = [item for item in items(channels) if item.objectName() == "showChip"]
    assert after == chips and target.property("shown") and not told  # same chips, catalog not sent again
    backend.setChannelVisible(key, False)
    wait(0.3)
    assert not target.property("shown")
    assert key not in backend.dashboard.shownChannels and backend.dashboard.channels is backend.dashboard.channels


# --- Histogram: bars read by index, one mouse area
def test_histogram_bars_and_hover(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(5)
    wait(0.3)
    xy = find(view, lambda item: class_name(item).startswith("XYView"))[0]
    xy.setProperty("mode", "histogram")
    evaluate(view, xy, "update()")
    wait(0.3)
    area = find(view, lambda item: item.property("barsOffset") is not None)[0]
    bins = int(evaluate(view, area, "bins.length"))
    laps_shown = int(evaluate(view, area, "laps.length"))
    assert bins > 0 and laps_shown > 0
    bars = [item for item in items(area) if class_name(item).startswith("QQuickRectangle")
            and item.property("lap") is not None]
    assert len(bars) == bins * laps_shown
    assert not [item for item in items(area) if class_name(item).startswith("QQuickMouseArea")
                and item.parentItem() is not area]  # no mouse area per bar
    tallest = max(bars, key=lambda item: item.height())
    center = tallest.mapToItem(area, QPointF(tallest.width() / 2, tallest.height() / 2))
    found = js(view, area, f"barAt({center.x()}, {center.y()})")
    bin_item = tallest.parentItem()
    assert found[0] == int(bin_item.property("binIndex"))
    assert js(view, area, f"barAt({center.x()}, -5)") == [-1, -1]  # above bar
    hovered = named(view, "histogramHover")  # set by mouse area from barAt
    assert tooltip_text(hovered) == "" and hovered.property("binIndex") == -1
    hovered.setProperty("binIndex", found[0])
    hovered.setProperty("lapIndex", found[1])
    wait(0.05)
    assert tooltip_text(hovered) != ""
    assert hovered.mapToScene(QPointF(0, 0)).x() == pytest.approx(tallest.mapToScene(QPointF(0, 0)).x(), abs=0.5)
    assert hovered.height() == pytest.approx(tallest.height(), abs=0.5)


# --- Corner labels moved with map: no binding per label on each move frame
def test_corner_labels_move_with_map(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    container = named(view, "cornerLabels")
    labels = [item for item in container.childItems() if item.property("selected") is not None]
    if not labels:
        pytest.skip("no corners")
    canvas = find(view, lambda item: item.property("targetZoom") is not None and item.property("feet") is not None)[0]
    label = labels[0]
    before = (label.x(), label.y())
    scene = label.mapToScene(QPointF(0, 0))
    evaluate(view, canvas, "setView(1, 40, -25, false)")  # moved only
    wait(0.2)
    assert (label.x(), label.y()) == before  # label itself not moved: container is
    moved = label.mapToScene(QPointF(0, 0))
    assert moved.x() - scene.x() == pytest.approx(40, abs=0.5) and moved.y() - scene.y() == pytest.approx(-25, abs=0.5)


# --- Session chart: GPU shapes, one hover item
def test_session_shapes_geometry():
    from neopedal.ui.quick.lap_session import session_shapes

    def lap(time, valid=True, shown=False, fuel=-1.0, wear=-1.0, outlier=False):
        return {"time": time, "valid": valid, "shown": shown, "color": "#ff0000" if shown else "", "fuel": fuel,
                "wear": wear, "outlier": outlier, "limits": -1, "offtrack": -1}

    view = {"width": 500, "padLeft": 50, "padRight": 10, "top": 6, "bottom": 200, "low": 60, "high": 80,
            "stripTops": [220, 280], "stripHeight": 50, "em": 10, "best": 70, "window": "#000000",
            "text": "#ffffff", "bestColor": "#ffd700", "fuelColor": "#3B82F6", "wearColor": "#F59E0B"}
    rows = [lap(70, fuel=2.0), lap(71, shown=True, fuel=1.0), lap(0), lap(72, valid=False, fuel=1.5, wear=0.5),
            lap(73), lap(74, outlier=True, wear=0.2)]
    shapes = session_shapes(rows, view)
    assert shapes["segments"].vertex_count == 6 * 2  # laps 1-2 & 5-6 joined (3: no time, 4: invalid)
    assert shapes["points"].colored and shapes["bars"].colored
    # Points: 5 laps with a time, ring & fill for valid ones (4), ring only for invalid one
    ring, disc = 20 * 6, 20 * 3
    assert shapes["points"].vertex_count == 5 * ring + 4 * disc
    assert shapes["bars"].vertex_count == 6 * (3 + 2)  # 3 fuel bars, 2 wear bars
    data = shapes["segments"].data
    xs = list(data[0::2])
    plot = 500 - 50 - 10
    assert min(xs) == pytest.approx(50 + 0.5 / 6 * plot, abs=1)  # first lap point x (centered in its slot)


def test_session_tab_drawn_as_shapes(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(4)
    wait(0.6)
    shapes = named(view, "sessionShapes")
    keys = [item.property("key") for item in shapes.childItems()]
    assert len(keys) == 3 and all(keys)
    assert stored(keys[1]).vertex_count > 0  # lap points
    session = find(view, lambda item: class_name(item).startswith("SessionView"))[0]
    points = [item for item in items(session) if item.property("grow") is not None]
    assert len(points) == 1  # hovered lap only
