"""Lap viewer & track map viewer QML, less work per frame with same look: map shapes moved by one transform per
group (drawn at the same place), info card lines keep their texts, value axes left alone without fitted panel,
lap list rows built per row type"""

import shiboken6
from PySide6.QtCore import QPointF
from PySide6.QtQml import QQmlExpression

from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import class_name, find, items, opener, track_maps, wait, warnings  # noqa: F401
from tests.test_track_map_viewer import viewer  # noqa: F401


def evaluate(view, scope, expression: str):
    value = QQmlExpression(view.rootContext(), scope, expression).evaluate()[0]
    return value.toVariant() if hasattr(value, "toVariant") else value


def pointer(item) -> int:
    return shiboken6.getCppPointer(item)[0]


def shapes(root) -> list:
    return [item for item in items(root) if class_name(item).startswith("GpuShape")]


def mapped(shape, target, x: float, y: float) -> tuple[float, float]:
    point = shape.mapToItem(target, QPointF(x, y))
    return point.x(), point.y()


def assert_on_canvas(view, canvas, found: list):
    """Shapes drawn where canvas places world points (screenX / screenY)"""
    assert found
    expected = evaluate(view, canvas, "[screenX(120), screenY(-45)]")
    for shape in found:
        x, y = mapped(shape, canvas, 120, -45)
        assert abs(x - expected[0]) < 1e-3 and abs(y - expected[1]) < 1e-3, (x, y, expected)


# --- Track map viewer: map & elevation shapes grouped under one transform, info card texts kept while playing
def test_track_map_viewer_shapes_and_cards(viewer, warnings):  # noqa: F811
    view, backend = viewer.view, viewer.backend
    viewer.show()
    wait(0.3)
    root = view.rootObject()
    canvas = next(item for item in items(root) if item.property("viewState") is not None)
    evaluate(view, canvas, "setView(3, 40, -25, false)")
    wait(0.1)
    assert_on_canvas(view, canvas, shapes(canvas))
    # Elevation profile: distance along, elevation up
    profile = next(
        item for item in items(root) if item.property("minZ") is not None and item.property("sx") is not None
    )
    sx, sy, height, low = (profile.property(name) for name in ("sx", "sy", "height", "minZ"))
    for shape in shapes(profile):
        x, y = mapped(shape, profile, 500, 5)
        assert abs(x - 500 * sx) < 1e-3 and abs(y - (height - 3 - (5 - low) * sy)) < 1e-3

    cards = [
        item for item in items(root) if item.property("lines") is not None and item.property("accentColor") is not None
    ]
    assert len(cards) == 3

    def lines():  # detail lines of each card: Text items after title & value in its column
        found = {}
        for card in cards:
            column = next(item for item in items(card) if class_name(item).startswith("QQuickColumn"))
            texts = [item for item in column.childItems() if class_name(item).startswith("QQuickText")]
            found.update({pointer(item): item.property("text") for item in texts[2:]})
        return found

    backend.setPosition(100)
    wait(0.1)
    before = lines()
    backend.setPosition(900)
    wait(0.1)
    after = lines()
    assert len(before) == 8 and before.keys() == after.keys()  # same Text items, new texts
    assert before != after
    root.setProperty("playing", True)  # position moved every frame
    wait(0.3)
    root.setProperty("playing", False)
    assert lines().keys() == before.keys() and backend.position != 900


# --- Lap viewer track map & G circle: grouped shapes at the same place as before (one transform each)
def test_lap_viewer_map_and_g_circle_shapes(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    side_map = track_maps(view, False)[0]
    canvas = next(item for item in items(side_map) if item.property("viewState") is not None)
    evaluate(view, canvas, "setView(2.5, -30, 60, false)")
    wait(0.2)
    minimap = [pointer(item) for item in items(canvas) if item.property("side") is not None]
    minimap_shapes = {pointer(shape) for item in items(canvas) if pointer(item) in minimap for shape in shapes(item)}
    map_shapes = [shape for shape in shapes(canvas) if pointer(shape) not in minimap_shapes]
    assert len(map_shapes) > 10  # circuit, laps, zones, trail, driving points
    assert_on_canvas(view, canvas, map_shapes)

    backend.setGEnvelope(True)
    backend.setSideTab(1)
    wait(0.6)
    circle = find(view, lambda item: item.property("gScale") is not None)[0]
    evaluate(view, circle, "zoomAt(2, 40, 30)")
    wait(0.1)
    scale, origin_x, origin_y = (circle.property(name) for name in ("gScale", "originX", "originY"))
    plot = next(item for item in items(circle) if item.property("reach") is not None)  # fills plot (originX / Y)
    offsets = set()
    for shape in shapes(circle):
        x, y = mapped(shape, plot, 0.5, 0.3)
        offset = (round(x - (origin_x + 0.5 * scale), 3), round(y - (origin_y - 0.3 * scale), 3))
        assert offset in ((0.0, 0.0), (0.6, 0.6)), offset  # grip envelope: second line 0.6 pixel apart
        offsets.add(offset)
    assert offsets == {(0.0, 0.0), (0.6, 0.6)}
    backend.setGEnvelope(False)


# --- Value axes: no new object (bindings of every panel run again) when no panel is fitted to visible part
def test_axes_kept_without_fitted_panel(opener, warnings):  # noqa: F811
    dialog = opener()
    view = dialog.view
    chart = find(view, lambda item: item.property("lodTier") is not None)[0]
    assert not any(panel.get("autoscale") for panel in chart.property("panels"))
    evaluate(view, chart, "(Object.defineProperty(yViews, 'probe', {value: 1}), 0)")
    evaluate(view, chart, "setView(maxX * 0.2, maxX * 0.4, false)")
    wait(0.2)  # autoscale timer
    assert evaluate(view, chart, "yViews.probe") == 1  # same object
    evaluate(view, chart, "setAutoscale(0, true)")
    wait(0.2)
    column = chart.property("panels")[0]["column"]
    assert evaluate(view, chart, "yViews.probe") is None and column in evaluate(view, chart, "yViews")
    evaluate(view, chart, "setAutoscale(0, false)")
    wait(0.2)
    assert evaluate(view, chart, "Object.keys(yViews).length") == 0  # fitted axis cleared
    evaluate(view, chart, "(Object.defineProperty(yViews, 'probe', {value: 2}), 0)")
    evaluate(view, chart, "resetView(false)")
    wait(0.2)
    assert evaluate(view, chart, "yViews.probe") == 2


# --- Lap list: session headers & laps built by their own delegate (no hidden layout per row)
def test_lap_list_delegate_per_row_type(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    listing = find(view, lambda item: item.property("model") is backend.lap_model)[0]
    rows = [
        item
        for item in listing.property("contentItem").childItems()
        if item.property("kind") is not None and item.property("visible")
    ]
    sessions = [row for row in rows if row.property("kind") == "session"]
    laps_shown = [row for row in rows if row.property("kind") != "session"]
    assert sessions and laps_shown
    for row in sessions:
        assert row.property("logo") is not None and row.property("checked") is None
        assert not [item for item in items(row) if item.property("sector") is not None]
    for row in laps_shown:
        assert row.property("logo") is None and row.property("path")
        assert len([item for item in items(row) if item.property("sector") is not None]) == 3
