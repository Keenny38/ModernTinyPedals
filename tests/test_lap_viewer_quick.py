"""Qt Quick lap viewer: vertex builders, page backend, map geometry & QML page loading"""

import math

import pytest

from tinypedal.module import module_recorder


def write_lap(folder, lap_number, lap_time, samples=400, length=3000.0, speed=180.0):
    """Recorded lap driving around a circle, braking at mid lap"""
    rows = []
    radius = length / (2 * math.pi)
    for index in range(samples + 1):
        progress = index / samples
        angle = progress * 2 * math.pi
        values = {
            "time": progress * lap_time, "lap_time": progress * lap_time, "distance": progress * length,
            "speed_kph": speed - (60.0 if 0.45 < progress < 0.55 else 0.0),
            "throttle": 0.0 if 0.45 < progress < 0.55 else 1.0, "brake": 0.8 if 0.45 < progress < 0.5 else 0.0,
            "gear": 4, "rpm": 7000, "fuel": 50.0, "pos_x": radius * math.cos(angle) + 1,
            "pos_y": radius * math.sin(angle) + 1, "accel_lat": math.sin(angle * 3), "accel_long": -0.5,
        }
        rows.append(tuple(values.get(column, 0) for column in module_recorder.CSV_HEADER))
    module_recorder.save_lap(f"{folder}/", "Track - GT3", lap_number, lap_time, rows, max_saved_laps=10)


@pytest.fixture
def backend(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.setting import cfg
    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 90.0)
    write_lap(folder, 2, 91.0)
    write_lap(folder, 3, 92.5)
    parent = QWidget()
    page = LapViewerBackend(parent, cfg.path.telemetry)
    page.refresh()
    yield page
    page.release()
    parent.deleteLater()


def test_vertex_builders():
    from tinypedal.ui.quick import lines

    strip = lines.line_strip([0.0, 1.0, 2.0], [5.0, 6.0, 7.0])
    assert strip.vertex_count == 3 and list(strip.data) == [0.0, 5.0, 1.0, 6.0, 2.0, 7.0]
    steps = lines.step_strip([0.0, 1.0, 2.0], [3.0, 4.0, 4.0])
    assert steps.vertex_count == 6
    assert list(steps.data[:8]) == [0.0, 3.0, 0.0, 3.0, 1.0, 3.0, 1.0, 4.0]  # held until next point
    road = lines.band([0.0, 10.0, 20.0], [0.0, 0.0, 0.0], 2.0)
    assert road.vertex_count == 6 and road.mode == lines.TRIANGLE_STRIP
    assert sorted({round(value, 3) for value in road.data[1::2]}) == [-2.0, 2.0]  # both road sides
    closed = lines.band([0.0, 10.0, 10.0], [0.0, 0.0, 10.0], 1.0, closed=True)
    assert closed.vertex_count == 8  # first point repeated
    from PySide6.QtGui import QColor

    gain = lines.colored_band([0.0, 1.0], [0.0, 0.0], [QColor("red"), QColor("lime")], 1.0)
    assert gain.colored and gain.vertex_count == 4 and len(gain.data) == 4 * lines.COLORED_VERTEX.size
    assert lines.dots(list(range(10)), list(range(10)), 0.1).vertex_count == 60  # 2 triangles per point
    assert lines.dots(list(range(100)), list(range(100)), 0.1, limit=10).vertex_count == 60
    assert lines.band([1.0], [1.0], 1.0).vertex_count == 0


def test_vertex_store_serial():
    from tinypedal.ui.quick.lines import VertexStore, line_strip

    VertexStore.set("test|a", line_strip([0.0, 1.0], [0.0, 1.0]))
    first = VertexStore.get("test|a").serial
    VertexStore.set("test|a", line_strip([0.0, 1.0], [0.0, 1.0]))
    assert VertexStore.get("test|a").serial > first  # same data stored again is uploaded again
    VertexStore.remove_prefix("test|")
    assert not VertexStore.has("test|a")


def test_backend_lap_list(backend):
    assert backend.tracks == ["Track - GT3"] and backend.currentTrack == "Track - GT3"
    rows = backend.lap_model.rows
    assert [row["kind"] for row in rows] == ["session", "lap", "lap", "lap"]
    assert rows[0]["count"] == 3 and rows[0]["session"] in backend.expanded
    # Fastest lap as reference, compared with newest other valid lap
    reference = next(row for row in rows if row["reference"])
    assert reference["time"] == "1:30.000" and reference["fastest"]
    assert len(backend.checked) == 2
    assert len(backend.legend) == 2 and backend.legend[0]["reference"]
    assert all(row["color"] for row in rows if row["checked"])  # lap color shown in list
    assert backend.lap_model.rowCount() == 4
    assert backend.lap_model.roleNames()


def test_backend_toggle_and_reference(backend):
    from tinypedal.ui.quick.lines import VertexStore

    unchecked = next(row["path"] for row in backend.lap_model.rows if row["kind"] == "lap" and not row["checked"])
    backend.toggleLap(unchecked)
    assert len(backend.legend) == 3
    backend.setReference(unchecked)
    assert backend.legend[0]["reference"] and backend.reference_key == unchecked
    assert next(row for row in backend.lap_model.rows if row["path"] == unchecked)["reference"]
    for panel in backend.panels:
        assert len(panel["series"]) == 3
        counts = [VertexStore.get(series["key"]).vertex_count for series in panel["series"]]
        if panel["column"] == "delta":  # reference lap: no delta to itself
            assert counts[0] == 0 and all(count > 1 for count in counts[1:])
        else:
            assert all(count > 1 for count in counts)
    backend.toggleLap(unchecked)
    assert len(backend.legend) == 2 and backend.reference_key != unchecked
    session = backend.lap_model.rows[0]["session"]
    backend.toggleSession(session)
    assert session not in backend.expanded


def test_backend_channels_and_cursor(backend):
    from tinypedal.ui.lap_viewer import DEFAULT_CHANNELS

    assert [panel["column"] for panel in backend.panels] == list(DEFAULT_CHANNELS)
    delta = next(panel for panel in backend.panels if panel["column"] == "delta")
    assert delta["low"] == -delta["high"]  # symmetric
    throttle = next(panel for panel in backend.panels if panel["column"] == "throttle")
    assert throttle["percent"] and throttle["highText"] == "100%"
    values = backend.cursorValues(1500.0)
    assert len(values) == len(backend.panels)
    speeds = values[[panel["column"] for panel in backend.panels].index("speed_kph")]
    assert [value["text"] for value in speeds] == ["120", "120"]  # braking zone
    assert backend.cursorTitle(1500.0) == "1500 m"
    backend.setChannelVisible("rpm", True)
    assert backend.panels[-1]["column"] == "rpm"
    backend.moveChannel(len(backend.panels) - 1, 0)
    assert backend.panels[0]["column"] == "rpm"
    assert backend.channelMenu[[item["column"] for item in backend.channelMenu].index("rpm")]["visible"]
    backend.setChannelVisible("rpm", False)
    assert "rpm" not in [panel["column"] for panel in backend.panels]
    backend.resetChannels()
    assert [panel["column"] for panel in backend.panels] == list(DEFAULT_CHANNELS)


def test_backend_time_axis(backend):
    distance_keys = {series["key"] for panel in backend.panels for series in panel["series"]}
    backend.setTimeAxis(True)
    assert backend.timeAxis and backend.maxX == pytest.approx(92.5, abs=0.5)  # newest lap compared
    assert distance_keys.isdisjoint(series["key"] for panel in backend.panels for series in panel["series"])
    assert backend.distanceAt(45.0) == pytest.approx(1500.0, rel=0.02)
    assert backend.cursorTitle(45.0).startswith("45s")
    backend.setTimeAxis(False)
    assert backend.maxX == pytest.approx(3000.0, abs=1)


def test_backend_map_corners_gcircle(backend):
    from tinypedal.ui.quick.lines import VertexStore

    track_map = backend.trackMap
    assert VertexStore.get(track_map["road"]).vertex_count > 10 and len(track_map["lines"]) == 2
    points = backend.mapCursor(750.0)  # quarter lap: top of circle
    assert len(points) == 2 and points[0]["y"] > track_map["maxY"] * 0.9
    # Click near reference line point: its axis position
    assert backend.mapPick(points[0]["x"], points[0]["y"], 20.0) == pytest.approx(750.0, abs=10)
    assert backend.mapPick(1e6, 1e6, 20.0) == -1.0
    backend.setMapView(1000.0, 2000.0, 2.0)
    assert VertexStore.get(track_map["lines"][0]["highlight"]).vertex_count > 0
    backend.setMapMode("gain")
    assert VertexStore.get(track_map["colored"]).colored
    corner = next((row for row in backend.corners if row["kind"] == "corner"), None)
    assert corner is not None  # braking zone at mid lap
    start, end = backend.cornerRange(corner["index"])
    assert start < 1500.0 < end
    assert backend.cornerMarks and backend.cornerRange(99) == []
    assert backend.gCircle["limit"] == 2.0 and len(backend.gCircle["dots"]) == 2
    assert len(backend.gCursor(100.0)) == 2


def test_backend_release(backend):
    from tinypedal.ui.quick.lines import VertexStore

    key = backend.panels[0]["series"][0]["key"]
    assert VertexStore.has(key)
    backend.release()
    assert not VertexStore.has(key)


def test_qml_page_loads(backend):
    """Every QML file of the page compiles & binds to backend without error"""
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick import create_quick_view

    parent = QWidget()
    view = create_quick_view(parent, "LapViewer.qml", {"backend": backend})
    try:
        assert not view.errors()
        assert view.rootObject() is not None
    finally:
        parent.deleteLater()


def test_qml_page_loads_with_bundled_modules(backend, tmp_path):
    """Release build bundles only QML_MODULES: pages must load with nothing else on import path"""
    import os
    import shutil

    from PySide6.QtCore import QLibraryInfo
    from PySide6.QtQuickWidgets import QQuickWidget

    from tinypedal.ui.quick import QML_FOLDER, create_quick_view
    from tinypedal.ui.quick.qml_modules import QML_MODULES

    source = QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath)
    for module in QML_MODULES:  # module folder files only, sub modules are listed separately
        target = tmp_path / module
        target.mkdir(parents=True, exist_ok=True)
        for entry in os.scandir(os.path.join(source, module)):
            if entry.is_file():
                shutil.copy2(entry.path, target)
    set_source = QQuickWidget.setSource

    def restricted_source(view, url):
        view.engine().setImportPathList([str(tmp_path), QML_FOLDER])
        set_source(view, url)

    QQuickWidget.setSource = restricted_source
    try:
        from PySide6.QtWidgets import QWidget

        from tinypedal.ui.quick.track_map_backend import TrackMapBackend

        parent = QWidget()
        for page, page_backend in (("LapViewer.qml", backend), ("TrackMapViewer.qml", TrackMapBackend(parent))):
            view = create_quick_view(parent, page, {"backend": page_backend})
            assert not view.errors(), [error.toString() for error in view.errors()]
        parent.deleteLater()
    finally:
        QQuickWidget.setSource = set_source


def test_tool_registered():
    from tinypedal.ui.tools_view import TOOL_SECTIONS

    paths = [path for _, tools in TOOL_SECTIONS for _, _, path in tools]
    assert "lap_viewer.LapViewer" in paths


def test_map_geometry_helpers():
    import math

    from tinypedal.ui.quick import lap_map
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(0, 1001, 5)]
    lap = LapData("a", {
        "distance": distance, "pos_x": [d + 1 for d in distance], "pos_y": [1.0] * len(distance),
        "speed_kph": [100 + d / 10 for d in distance],
        "throttle": [0.0 if 300 < d < 400 else 1.0 for d in distance],
        "brake": [1.0 if 300 < d < 350 else 0.0 for d in distance],
    })
    line = lap_map.map_line(lap)
    assert line is not None and len(line.xs) == len(distance)
    assert len(lap_map.simplify(line, 50.0).xs) == 21  # one point every 50 m
    assert lap_map.simplify(line, 0).xs == line.xs
    part = lap_map.part(line, 100.0, 200.0)
    assert part.distances[0] == 100.0 and part.distances[-1] == 200.0
    assert lap_map.heading_at(line, 500.0) == pytest.approx(0.0)  # driving along x
    x0, y0, x1, y1 = lap_map.cross_mark(line, 500.0, 10.0)
    assert x0 == pytest.approx(x1) and abs(y1 - y0) == pytest.approx(20.0)  # across driving direction
    assert lap_map.braking_points(lap) == [305.0]
    colors, low, high = lap_map.speed_colors(lap, line)
    assert (low, high) == (100.0, 200.0) and colors[0] == lap_map.SPEED_COLORS[0] and colors[-1] == lap_map.SPEED_COLORS[-1]
    pedals = lap_map.pedal_colors(lap, line)
    assert pedals[distance.index(320.0)] == lap_map.PEDAL_COLORS["brake"]
    assert pedals[distance.index(380.0)] == lap_map.PEDAL_COLORS["coast"]
    assert lap_map.map_line(LapData("b", {"distance": distance})) is None  # positions not recorded
    assert lap_map.blend(lap_map.SPEED_COLORS, 2.0) == lap_map.SPEED_COLORS[-1]
    assert not math.isnan(lap_map.heading_at(line, 0.0))


def test_chart_view_kept_inside_lap(backend):
    """Chart zoom & move in QML: view stays inside lap, zoom keeps point under cursor"""
    from PySide6.QtCore import Q_ARG, QMetaObject
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick import create_quick_view

    parent = QWidget()
    view = create_quick_view(parent, "LapViewer.qml", {"backend": backend})
    try:
        stack = [view.rootObject()]
        chart = None
        while stack:
            item = stack.pop()
            if item.property("labelWidth") is not None:
                chart = item
                break
            stack.extend(item.childItems())
        assert chart is not None and chart.property("maxX") == pytest.approx(3000.0)

        def call(name, *args):
            QMetaObject.invokeMethod(chart, name, *(Q_ARG("QVariant", arg) for arg in args))

        call("setView", -100.0, 200.0, False)  # moved before start: kept inside lap
        assert (chart.property("targetStart"), chart.property("targetEnd")) == pytest.approx((0.0, 300.0))
        assert chart.property("zoomed")
        call("setView", 1000.0, 2000.0, False)
        call("zoom", 0.5, 1500.0, False)
        assert (chart.property("targetStart"), chart.property("targetEnd")) == pytest.approx((1250.0, 1750.0))
        call("resetView", False)
        assert not chart.property("zoomed")
        assert backend._chart_view == pytest.approx((0.0, 3000.0))  # view kept by backend
    finally:
        parent.deleteLater()
