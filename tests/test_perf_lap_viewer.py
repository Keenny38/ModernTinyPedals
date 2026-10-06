"""Lap viewer per frame work: one view assignment per frame, cursor values worked out once per update,
corner labels placed for scale only, hidden side tabs skipped, backend lists built once"""

import json

import pytest

from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import chart_of, evaluate, find, opener, track_maps, wait, warnings  # noqa: F401


def js(view, scope, expression: str):
    """Value of a QML expression as Python data"""
    return json.loads(evaluate(view, scope, f"JSON.stringify({expression})"))


def test_view_set_at_once_and_cursor_panels(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    evaluate(view, chart, "setView(500, 900, false)")
    wait(0.05)
    assert chart.property("viewStart") == pytest.approx(chart.property("targetStart"))
    assert chart.property("viewEnd") == pytest.approx(chart.property("targetEnd"))
    evaluate(view, chart, "setView(300, 700, true)")  # eased: one range per frame
    wait(0.8)
    assert chart.property("viewStart") == pytest.approx(chart.property("targetStart"))
    assert evaluate(view, chart, "xOf(viewStart)") == pytest.approx(0)

    # Cursor values: count, rows & compact text worked out once per update
    evaluate(view, chart, "setCursor(800, 'key')")
    wait(0.05)
    panels = evaluate(view, chart, "panels.length")
    assert evaluate(view, chart, "cursorPanels.length") == panels > 0
    for index in range(int(panels)):
        texts = js(view, chart, f"cursorValues[{index}].map(function(value) {{ return value.text }})")
        assert evaluate(view, chart, f"valueCount({index})") == sum(1 for text in texts if text)
        for series, _ in enumerate(texts):
            expected = sum(1 for text in texts[:series] if text)
            assert evaluate(view, chart, f"valueRow({index}, {series})") == expected
        colors = js(view, chart, f"cursorValues[{index}].map(function(value) {{ return value.color }})")
        compact = [f"<font color='{color}'>{text}</font>" for text, color in zip(texts, colors) if text]
        assert evaluate(view, chart, f"compactValues({index})") == " ".join(compact[:4])
    evaluate(view, chart, "setCursor(NaN)")
    assert evaluate(view, chart, "cursorPanels.length") == 0 and evaluate(view, chart, "valueCount(0)") == 0
    assert backend.sectorLines is backend.sectorLines  # cached until charts change


def test_corner_labels_kept_while_moving(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    if not backend.cornerMarks:
        pytest.skip("no corners")
    evaluate(view, chart, "setView(0, 1200, false)")
    wait(0.1)
    shown = evaluate(view, chart, "JSON.stringify(cornerLabelShown)")
    scale = chart.property("labelScale")
    assert scale == pytest.approx(chart.property("viewScale"))
    evaluate(view, chart, "setView(250, 1450, false)")  # moved, same zoom: same labels
    wait(0.1)
    assert evaluate(view, chart, "JSON.stringify(cornerLabelShown)") == shown
    assert chart.property("labelScale") == pytest.approx(scale)
    evaluate(view, chart, "resetView(false)")  # zoomed out: placed again for whole lap
    wait(0.1)
    assert chart.property("labelScale") == pytest.approx(chart.property("viewScale"))


def test_hidden_side_tabs_skip_cursor_positions(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    chart = chart_of(view)
    backend.setSideTab(0)
    wait(0.3)
    state = backend.cursorState(500.0)
    assert state["map"] and state["g"] == []  # map shown, G circle hidden: not worked out
    evaluate(view, chart, "setCursor(500, 'key')")
    wait(0.05)
    assert evaluate(view, chart, "cursorMap.length") > 0 and evaluate(view, chart, "cursorG.length") == 0
    backend.setSideTab(1)  # G circle shown: cursor asked again
    wait(0.5)
    assert evaluate(view, chart, "cursorG.length") > 0
    assert backend.cursorState(500.0)["map"] == []  # map hidden
    backend.setSideTab(0)
    wait(0.5)
    assert evaluate(view, chart, "cursorMap.length") > 0


def test_trails_built_again_after_a_pixel(opener, warnings):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    if not backend._map or not backend._map_options.get("trail") or not backend._map_shown:
        pytest.skip("no map trail")
    backend.build_trails(600.0)
    revision = backend.trailRevision
    meters_per_pixel = backend._map_view[2]
    backend.build_trails(600.0 + meters_per_pixel * 0.2)  # less than a pixel: same trails
    assert backend.trailRevision == revision
    backend.build_trails(600.0 + meters_per_pixel * 5)
    assert backend.trailRevision == revision + 1


def test_map_labels_placed_for_scale_only(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(0)
    backend.setMapOption("distances", True)
    wait(0.3)
    side_map = track_maps(view, False)[0]
    canvas = find(view, lambda item: item.property("targetZoom") is not None and item.property("feet") is not None)[0]
    evaluate(view, canvas, "setView(3, 0, 0, false)")
    wait(0.3)
    shown = evaluate(view, side_map, "JSON.stringify(labelShown)")
    scale = side_map.property("labelScale")
    evaluate(view, canvas, "setView(3, 40, -25, false)")  # moved only
    wait(0.3)
    assert side_map.property("labelScale") == scale
    assert evaluate(view, side_map, "JSON.stringify(labelShown)") == shown
    # Distance marks placed from map origin: same screen place as screenX / screenY
    ticks = backend.trackMap.get("ticks") or []
    if ticks:
        marks = [item for item in find(view, lambda item: item.property("text") == ticks[0]["label"])]
        assert marks
        point = marks[0].parentItem().mapToItem(canvas, 0, 0)
        assert point.x() == pytest.approx(evaluate(view, canvas, f"screenX({ticks[0]['x']})"), abs=0.01)
        assert point.y() == pytest.approx(evaluate(view, canvas, f"screenY({ticks[0]['y']})"), abs=0.01)


def test_compared_laps_cached(opener):  # noqa: F811
    dialog = opener()
    backend = dialog.backend
    first = backend.comparedLaps
    assert first is backend.comparedLaps
    backend.chartChanged.emit()
    assert backend.comparedLaps == first and backend.comparedLaps is not first
