"""Recorded lap loading, delta & viewer tests"""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from tinypedal.module import module_recorder
from tinypedal.userfile.telemetry_lap import compute_delta, interpolate, list_laps, list_tracks, load_lap


def write_lap(folder, lap_number, lap_time, samples=300, length=3000.0):
    rows = []
    for index in range(samples + 1):
        progress = index / samples
        rows.append((
            progress * lap_time, progress * lap_time, progress * length, 180.0, 1.0, 0.0, 0.0, 0.1,
            4, 7000, 50.0, 80, 80, 80, 80, 170, 170, 170, 170, 0.0, 0.0,
        ) + (0,) * (len(module_recorder.CSV_HEADER) - 21))
    module_recorder.save_lap(f"{folder}/", "Track - GT3", lap_number, lap_time, rows, max_saved_laps=10)


def flush_deleted():
    """Delete closed dialogs now (singleton dialog is released on destroy)"""
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_interpolate():
    assert interpolate([0, 10], [0, 100], 5) == pytest.approx(50)
    assert interpolate([0, 10], [0, 100], -1) == 0
    assert interpolate([0, 10], [0, 100], 20) == 100


def test_load_and_delta(tmp_path):
    write_lap(tmp_path, 1, 90.0)
    write_lap(tmp_path, 2, 92.0)
    assert list_tracks(f"{tmp_path}/") == ["Track - GT3"]
    laps = list_laps(f"{tmp_path}/", "Track - GT3")
    assert len(laps) == 2 and all(lap.valid for lap in laps)
    lap_90 = load_lap(next(lap.path for lap in laps if "1m30" in lap.filename))
    lap_92 = load_lap(next(lap.path for lap in laps if "1m32" in lap.filename))
    assert lap_90.lap_time == pytest.approx(90.0)
    delta = compute_delta(lap_90, lap_92)
    assert delta[-1][1] == pytest.approx(2.0, abs=0.01)  # 2s slower at finish
    assert delta[len(delta) // 2][1] == pytest.approx(1.0, abs=0.02)  # 1s at half lap


def test_invalid_file(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_lap(str(path))


def test_lap_viewer_dialog(ui_env, tmp_path, monkeypatch):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import LapViewer

    write_lap(cfg.path.telemetry.rstrip("/"), 1, 90.0)
    write_lap(cfg.path.telemetry.rstrip("/"), 2, 91.0)
    viewer = LapViewer(None)
    try:
        assert viewer.combo_track.currentText() == "Track - GT3"
        assert viewer.plot.lap_a is not None and viewer.plot.lap_b is not None
        assert viewer.plot.delta
        viewer.plot.resize(800, 500)
        image = viewer.plot.grab()
        assert not image.isNull()
        event = QMouseEvent(
            QMouseEvent.Type.MouseMove, QPointF(400, 100), QPointF(400, 100),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        )
        viewer.plot.mouseMoveEvent(event)
        assert " m " in viewer.label_cursor.text()
    finally:
        viewer.close()
        flush_deleted()


def test_trajectory_map(ui_env):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.lap_viewer import PlotLap, TrajectoryMap
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(0, 101, 10)]
    lap_a = LapData("a", {"distance": distance, "pos_x": [d * 2 for d in distance], "pos_y": [d for d in distance]})
    lap_b = LapData("b", {"distance": distance, "pos_x": [d * 2 + 1 for d in distance], "pos_y": distance})
    parent = QWidget()
    view = TrajectoryMap(parent)
    view.resize(300, 300)
    view.set_laps([PlotLap("a", "a", lap_a, QColor("red")), PlotLap("b", "b", lap_b, QColor("blue"))])
    view.set_cursor(50.0, (20.0, 60.0))
    assert len(view.positions(lap_a)) == 10  # (0, 0) means position not recorded
    assert not view.grab().isNull()
    assert view.positions(LapData("c", {"distance": distance})) == []  # positions not recorded
    parent.deleteLater()


def test_gcircle(ui_env):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.lap_viewer import GCircle, PlotLap
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(100)]
    lap = LapData("a", {"distance": distance, "accel_lat": [1.5] * 100, "accel_long": [-0.5] * 100})
    parent = QWidget()
    view = GCircle(parent)
    view.resize(200, 200)
    view.set_laps([PlotLap("a", "a", lap, QColor("red"))])
    view.set_cursor(50.0, (10.0, 60.0))
    assert not view.grab().isNull()
    parent.deleteLater()


def test_decimate_minmax_keeps_peaks():
    from tinypedal.userfile.telemetry_lap import decimate_minmax

    xs = [float(index) for index in range(10000)]
    ys = [0.0] * 10000
    ys[5003] = 1.0  # short brake spike
    points = decimate_minmax(xs, ys, 0.0, 10000.0, 100)
    assert len(points) <= 2 * 101 + 2
    assert (5003.0, 1.0) in points
    assert decimate_minmax(xs[:10], ys[:10], 0, 10, 100) == list(zip(xs[:10], ys[:10]))  # few points kept
    assert decimate_minmax([], [], 0, 1, 10) == []


def test_sectors_and_theoretical_best():
    from tinypedal.userfile.telemetry_lap import LapData, sector_bounds, sector_times, theoretical_best

    distance = [float(index) for index in range(0, 3001, 10)]
    lap = LapData("a", {
        "distance": distance,
        "lap_time": [d / 30 for d in distance],
        "sector": [0 if d < 1000 else 1 if d < 2000 else 2 for d in distance],
    })
    assert sector_bounds(lap) == [1000.0, 2000.0]
    assert sector_times(lap) == pytest.approx([33.333, 33.333, 33.333], abs=0.01)
    official = LapData("b", lap.columns, {"sectors": [30.0, 31.0, 32.0]})
    assert sector_times(official) == [30.0, 31.0, 32.0]  # official game sector times first
    total, best = theoretical_best([[30.0, 33.0, 32.0], [31.0, 31.0, 33.0], []])
    assert best == [30.0, 31.0, 32.0] and total == pytest.approx(93.0)
    assert theoretical_best([]) == (0.0, [])


def test_trace_plot_many_laps_and_navigation(ui_env, tmp_path):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.lap_viewer import PlotLap, TracePlot

    write_lap(tmp_path, 1, 90.0)
    write_lap(tmp_path, 2, 91.0)
    write_lap(tmp_path, 3, 92.0)
    laps = [load_lap(lap.path) for lap in list_laps(f"{tmp_path}/", "Track - GT3")]
    parent = QWidget()
    plot = TracePlot(parent)
    plot.resize(800, 500)
    plot.set_laps([PlotLap(str(index), lap.name, lap, QColor("red")) for index, lap in enumerate(laps)], "2")
    assert plot.reference is not None and plot.reference.key == "2"
    assert len(plot.deltas) == 2  # one delta per compared lap
    plot.set_channels(["delta", "speed_kph", "rpm", "tyre_temp_fl", "unknown"])
    assert [channel.column for channel in plot.channels] == ["delta", "speed_kph", "rpm", "tyre_temp_fl"]
    assert not plot.grab().isNull()
    cache = plot._cache
    plot.cursor_distance = 500.0
    plot.repaint()
    assert plot._cache is cache  # cursor move keeps cached charts
    assert "rpm" not in plot.cursor_values().lower() or "RPM" in plot.cursor_values()
    plot.zoom(0.5, 1500.0)
    assert plot.zoomed() and plot.view_end - plot.view_start == pytest.approx(1500.0)
    plot.set_view(-100.0, 200.0)  # moved before start: kept inside lap
    assert plot.view_start == 0.0 and plot.view_end == pytest.approx(300.0)
    plot.reset_view()
    assert not plot.zoomed()
    parent.deleteLater()


def test_compressed_lap_file_with_info(tmp_path):
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    info = {"kind": "lap", "vehicle": "Car A", "sectors": [1.0, 2.0, 1.9]}
    assert module_recorder.save_lap(
        f"{tmp_path}/", "T - C", 7, 4.9, rows, max_saved_laps=5, info=info, compress=True)
    laps = list_laps(f"{tmp_path}/", "T - C")
    assert len(laps) == 1 and laps[0].filename.endswith(".csv.gz") and laps[0].lap_time == pytest.approx(4.9)
    lap = load_lap(laps[0].path)
    assert lap.meta["vehicle"] == "Car A" and len(lap) == 50
    assert lap.name.endswith("4.900s")


def test_old_lap_file_without_info(tmp_path):
    path = tmp_path / "2026-01-01 10-00-00 lap001 1m30.000s.csv"
    path.write_text("time,lap_time,distance\n0,0,0\n1,1,10\n", encoding="utf-8")
    lap = load_lap(str(path))
    assert lap.meta == {} and len(lap) == 2


def test_lap_viewer_multiple_laps(ui_env, monkeypatch):
    from PySide6.QtCore import Qt

    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import LapViewer

    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 92.0)
    write_lap(folder, 2, 90.0)
    write_lap(folder, 3, 91.0)
    viewer = LapViewer(None)
    try:
        assert "1m30.000s" in viewer.reference_key  # best lap is reference
        for item in viewer.lap_items():
            item.setCheckState(0, Qt.CheckState.Checked)
        assert len(viewer.plot.laps) == 3
        assert viewer.plot.reference is not None and "1m30" in viewer.plot.reference.key
        newest = viewer.lap_items()[-1]  # laps in driving order
        viewer.set_reference_item(newest)
        assert viewer.plot.reference.key == newest.data(0, Qt.ItemDataRole.UserRole)
        viewer.toggle_channel("rpm", True)
        assert "rpm" in [channel.column for channel in viewer.plot.channels]
        viewer.reset_channels()
        assert "rpm" not in [channel.column for channel in viewer.plot.channels]
    finally:
        viewer.close()
        flush_deleted()


def test_lap_bounds_drop_previous_and_next_lap_distance():
    from tinypedal.userfile.telemetry_lap import lap_bounds

    # Lap distance reset late (previous lap distance at start), next lap distance at end
    distances = [3584.0, 3584.0, 5.0, 500.0, 1500.0, 2500.0, 3580.0, 3.0]
    assert lap_bounds(distances) == (2, 7)
    assert lap_bounds([5.0, 500.0, 3000.0]) == (0, 3)  # clean lap kept
    assert lap_bounds([3581.0, 3581.0, 3.0, 50.0, 104.0]) == (2, 5)  # short lap: only start trimmed


def test_smooth_distance_between_game_updates():
    from tinypedal.userfile.telemetry_lap import smooth_distance

    times = [0.0, 0.1, 0.2, 0.3, 0.4]
    assert smooth_distance(times, [0.0, 0.0, 10.0, 10.0, 20.0]) == pytest.approx([0.0, 5.0, 10.0, 15.0, 20.0])
    assert smooth_distance(times, [0.0, 1.0, 2.0, 3.0, 4.0]) == [0.0, 1.0, 2.0, 3.0, 4.0]  # every sample updated


def test_load_lap_with_late_distance_reset(tmp_path):
    """Recorded lap starting with previous lap distance must still plot (was a single point)"""
    from tinypedal.userfile.telemetry_lap import monotonic_distance

    rows = []
    for index in range(500):
        lap_time = index * 0.02
        distance = 3000.0 if index < 5 else round((index // 10) * 10 * 0.6, 2)  # updated every 10 samples
        rows.append((lap_time, lap_time, distance, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4))
    module_recorder.save_lap(f"{tmp_path}/", "T - C", 1, 10.0, rows, max_saved_laps=5)
    lap = load_lap(list_laps(f"{tmp_path}/", "T - C")[0].path)
    assert lap.distance[0] < 10
    assert len(monotonic_distance(lap)[0]) > 400  # nearly every sample on its own distance


def test_lap_viewer_added_file_not_in_theoretical_best(ui_env, tmp_path, monkeypatch):
    from tinypedal.setting import cfg
    from tinypedal.ui import lap_viewer

    folder = cfg.path.telemetry.rstrip("/")
    info = {"sectors": [30.0, 30.0, 30.0]}
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    module_recorder.save_lap(f"{folder}/", "Track - GT3", 1, 90.0, rows, 10, info=info)
    other = tmp_path / "other"
    module_recorder.save_lap(f"{other}/", "Other - GT3", 1, 60.0, rows, 10, info={"sectors": [20.0, 20.0, 20.0]})
    other_file = next((other / "Other - GT3").glob("*.csv"))
    monkeypatch.setattr(lap_viewer.QFileDialog, "getOpenFileNames", lambda *args: ([str(other_file)], ""))
    viewer = lap_viewer.LapViewer(None)
    try:
        viewer.add_files()
        assert viewer.lap_list.topLevelItemCount() == 2
        assert "1:30.000" in viewer.label_best.text()  # other track sectors left out
    finally:
        viewer.close()
        flush_deleted()


def test_lap_cache_is_bounded(ui_env, monkeypatch):
    from tinypedal.setting import cfg
    from tinypedal.ui import lap_viewer

    monkeypatch.setattr(lap_viewer, "LAP_CACHE_SIZE", 5)
    folder = cfg.path.telemetry.rstrip("/")
    for lap in range(8):
        write_lap(folder, lap, 90.0 + lap, samples=20)
    viewer = lap_viewer.LapViewer(None)
    try:
        for entry in viewer.entries:
            viewer.read_lap(entry.file.path)
        assert len(viewer._lap_cache) == lap_viewer.LAP_CACHE_SIZE
    finally:
        viewer.close()
        flush_deleted()


def test_side_views_keep_cached_drawing_on_cursor_move(ui_env):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.lap_viewer import GCircle, PlotLap, TrajectoryMap
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(100)]
    lap = LapData("a", {
        "distance": distance, "pos_x": [d + 1 for d in distance], "pos_y": [d * 2 + 1 for d in distance],
        "accel_lat": [1.0] * 100, "accel_long": [-1.0] * 100,
    })
    parent = QWidget()
    for view_class in (TrajectoryMap, GCircle):
        view = view_class(parent)
        view.resize(200, 200)
        view.set_laps([PlotLap("a", "a", lap, QColor("red"))])
        view.grab()
        cache = view._cache
        view.set_cursor(40.0, (0.0, 0.0))
        view.grab()
        assert view._cache is cache  # cursor drawn over cached laps
        view.set_cursor(40.0, (10.0, 50.0))
        view.grab()
        assert view._cache is not cache  # zoom redraws laps
    parent.deleteLater()


def test_delta_limit_ignores_aberrant_lap():
    from tinypedal.ui.lap_viewer import delta_limit

    normal = [0.1 * index / 100 for index in range(100)]  # up to 0.1s
    close = [0.3 * index / 100 for index in range(100)]  # up to 0.3s
    aberrant = [60.0] * 100  # lap cut short
    assert delta_limit([close, aberrant, normal]) == pytest.approx(0.3 * 0.95 * 1.15, abs=0.01)
    assert delta_limit([aberrant]) == pytest.approx(69.0)  # alone: shown entirely
    assert delta_limit([]) == 0.1
    assert delta_limit([[0.0, 0.01]]) == 0.1


def mouse(kind, x, y, button=None, modifiers=None):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    button = button or Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else button
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons,
                       modifiers or Qt.KeyboardModifier.NoModifier)


def test_drag_channel_name_reorders_channels(ui_env):
    from PySide6.QtGui import QMouseEvent

    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import LapViewer, load_visible_channels

    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 90.0)
    write_lap(folder, 2, 91.0)
    viewer = LapViewer(None)
    try:
        plot = viewer.plot
        plot.resize(800, 600)
        columns = [channel.column for channel in plot.channels]
        rect = plot.plot_rect()
        panels = plot.panels(rect)
        x = rect.left() / 2  # channel name area
        speed_y = panels[1][1].center().y()
        steering_y = panels[-1][1].center().y()
        plot.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, x, speed_y))
        plot.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, x, steering_y))
        assert not plot.grab().isNull()  # move indicator drawn
        plot.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, x, steering_y))
        expected = [column for column in columns if column != "speed_kph"] + ["speed_kph"]
        assert [channel.column for channel in plot.channels] == expected
        assert viewer.visible_channels == expected
        assert load_visible_channels(viewer.filepath) == expected  # order kept
        viewer.toggle_channel("rpm", True)
        assert viewer.visible_channels[-1] == "rpm"  # new channel added at bottom, order kept
        assert viewer.visible_channels[:-1] == expected
    finally:
        viewer.close()
        flush_deleted()


def test_track_map_zoom_and_move(ui_env):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.lap_viewer import PlotLap, TrajectoryMap
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(100)]
    lap = LapData("a", {"distance": distance, "pos_x": [d + 1 for d in distance], "pos_y": [d * 2 + 1 for d in distance]})
    parent = QWidget()
    view = TrajectoryMap(parent)
    view.resize(200, 200)
    view.set_laps([PlotLap("a", "a", lap, QColor("red"))])
    mouse_at = QPointF(150, 50)
    before = view.to_screen(80.0, 161.0)

    def wheel(delta):
        view.wheelEvent(QWheelEvent(
            mouse_at, mouse_at, QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))

    wheel(120)
    assert view.zoom == pytest.approx(1.25)
    after = view.to_screen(80.0, 161.0)
    # Point under mouse stays under mouse, others move away from it
    assert (after - mouse_at).manhattanLength() == pytest.approx((before - mouse_at).manhattanLength() * 1.25, rel=0.01)
    view.grab()
    cache = view._cache
    view.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, 100, 100))
    view.mouseMoveEvent(mouse(QMouseEvent.Type.MouseMove, 110, 95))
    view.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, 110, 95))
    assert view.to_screen(80.0, 161.0) == after + QPointF(10, -5)
    view.grab()
    assert view._cache is not cache  # zoomed or moved view redrawn
    for _ in range(3):
        wheel(-120)
    assert view.zoom == 1.0 and view.pan == QPointF()  # zoomed out: whole map, centered
    wheel(120)
    view.mouseDoubleClickEvent(None)
    assert view.zoom == 1.0
    parent.deleteLater()


def test_track_map_draws_circuit_from_track_map_file(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import LapViewer
    from tinypedal.userfile.track_map import save_track_map_file

    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 90.0)  # positions not recorded by helper: (0, 0)
    circuit = tuple((float(x), float(x % 7)) for x in range(0, 500, 10))
    dists = tuple((float(index), 0.0) for index in range(len(circuit)))
    save_track_map_file(cfg.path.track_map, "Track", "0 0 500 10", circuit, dists, (10, 20), 2)
    viewer = LapViewer(None)
    try:
        assert viewer.trajectory.road == list(circuit)  # "Track - GT3" folder: track map "Track"
        viewer.trajectory.resize(200, 400)
        assert not viewer.trajectory.grab().isNull()
    finally:
        viewer.close()
        flush_deleted()


def test_track_map_circuit_falls_back_to_reference_lap(ui_env):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.lap_viewer import PlotLap, TrajectoryMap
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(0, 101, 10)]
    reference = LapData("a", {"distance": distance, "pos_x": [d + 1 for d in distance], "pos_y": distance})
    other = LapData("b", {"distance": distance, "pos_x": [d + 2 for d in distance], "pos_y": distance})
    parent = QWidget()
    view = TrajectoryMap(parent)
    view.resize(200, 200)
    view.set_laps([PlotLap("a", "a", reference, QColor("red")), PlotLap("b", "b", other, QColor("blue"))])
    assert view.road == [(d + 1, d) for d in distance]  # no track map file: reference lap line
    assert not view.grab().isNull()
    view.set_laps([])
    assert view.road == []
    parent.deleteLater()


def test_sector_lines_at_official_sector_times():
    """Sector column changes late (scoring data at 5 Hz): official times place sector lines exactly"""
    from tinypedal.userfile.telemetry_lap import LapData, sector_bounds

    distance = [float(index) for index in range(0, 3001, 10)]
    columns = {
        "distance": distance,
        "lap_time": [d / 30 for d in distance],  # 30 m/s
        "sector": [0 if d < 1015 else 1 if d < 2015 else 2 for d in distance],  # 15 m late
    }
    assert sector_bounds(LapData("a", columns)) == [1020.0, 2020.0]
    assert sector_bounds(LapData("b", columns, {"sectors": [33.0, 34.0, 33.0]})) == pytest.approx([990.0, 2010.0])
    assert sector_bounds(LapData("c", columns, {"sectors": [33.0, "x", 33.0]})) == [1020.0, 2020.0]  # invalid info


def test_hidden_viewer_releases_laps_and_reloads(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import LapViewer

    write_lap(cfg.path.telemetry.rstrip("/"), 1, 90.0)
    write_lap(cfg.path.telemetry.rstrip("/"), 2, 91.0)
    viewer = LapViewer(None)
    try:
        viewer.show()
        viewer.plot.set_view(500.0, 1500.0)
        viewer.release_laps()  # visible: kept
        assert viewer.plot.laps and viewer._lap_cache
        viewer.hide()
        assert viewer._release_timer.isActive()  # released after a while in background
        viewer.release_laps()
        assert not viewer.plot.laps and not viewer._lap_cache
        viewer.show()  # same laps & zoom again
        assert len(viewer.plot.laps) == 2 and not viewer._release_timer.isActive()
        assert (viewer.plot.view_start, viewer.plot.view_end) == (500.0, 1500.0)
    finally:
        viewer.close()
        flush_deleted()


def test_trajectory_colored_by_time_gain(ui_env):
    import math

    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.lap_viewer import GAIN_COLOR, LOSS_COLOR, PlotLap, TrajectoryMap
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(0, 2001, 10)]
    xs = [500 * math.cos(d / 2000 * math.tau) for d in distance]
    ys = [500 * math.sin(d / 2000 * math.tau) for d in distance]
    reference = LapData("ref", {"distance": distance, "lap_time": [d / 50 for d in distance], "pos_x": xs, "pos_y": ys})
    # Compared: slower on first half (40 m/s), faster on second half (60 m/s)
    times = [d / 40 if d <= 1000 else 25 + (d - 1000) / 60 for d in distance]
    compared = LapData("cmp", {"distance": distance, "lap_time": times, "pos_x": xs, "pos_y": ys})
    parent = QWidget()
    view = TrajectoryMap(parent)
    view.resize(300, 300)
    laps = [PlotLap("ref", "ref", reference, QColor("white")), PlotLap("cmp", "cmp", compared, QColor("cyan"))]
    view.set_laps(laps)
    assert not view._gain  # off by default
    view.set_show_gain(True)
    rates = {round(d): rate for d, _, _, rate in view._gain}
    assert rates[500] > 0 > rates[1500]  # losing then gaining
    assert view.gain_color(rates[500]) == LOSS_COLOR and view.gain_color(rates[1500]) == GAIN_COLOR
    assert view.gain_color(0.0) == QColor("#9CA3AF")
    image = view.grab().toImage()
    colors = {image.pixelColor(x, y).name() for x in range(0, 300, 2) for y in range(0, 300, 2)}
    assert LOSS_COLOR.name() in colors and GAIN_COLOR.name() in colors
    view.set_laps(laps[:1])  # reference only: plain line
    assert not view._gain
    parent.deleteLater()


def test_viewer_time_gain_option_saved(ui_env):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import LapViewer, load_viewer_setting

    viewer = LapViewer(None)
    try:
        viewer.check_gain.setChecked(True)
        assert viewer.trajectory.show_gain
        assert load_viewer_setting(cfg.path.telemetry)["map_time_gain"] is True
    finally:
        viewer.close()
        flush_deleted()


def save_session_lap(folder, number, lap_time, timestamp, session="Practice", start=None, valid=True, kind="lap"):
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    info = {"kind": kind, "session": session, "vehicle": "Porsche 963"}
    if start is not None:
        info["session_start"] = start
    module_recorder.save_lap(f"{folder}/", "Atlanta - Hyper", number, lap_time, rows, max_saved_laps=99,
                             valid=valid, info=info, timestamp=timestamp)


def test_laps_grouped_by_session():
    import time

    from tinypedal.userfile.telemetry_lap import group_sessions, lap_number_of, lap_timestamp_of

    base = time.mktime((2026, 10, 3, 14, 0, 0, 0, 0, -1))
    laps = [  # (file name, info)
        (f"{time.strftime('%Y-%m-%d %H-%M-%S', time.localtime(base + t))} lap{n:03d} 1m30.000s.csv", info)
        for t, n, info in (
            (0, 1, {"session": "Practice"}), (90, 2, {"session": "Practice"}), (180, 3, {"session": "Practice"}),
            (400, 1, {"session": "Practice"}),  # lap number restarts: new session
            (3000, 2, {"session": "Practice"}),  # long break: new session
            (3090, 3, {"session": "Qualify"}),  # other session type
            (9000, 5, {"session": "Race", "session_start": base + 8500}),  # recorded session start
            (9200, 1, {"session": "Race", "session_start": base + 8520}),  # same start (rejoin): same session
            (9400, 6, {"session": "Race", "session_start": base + 9300}),  # restarted session
        )
    ]
    assert lap_number_of(laps[0][0]) == 1 and lap_timestamp_of(laps[0][0]) == base
    assert lap_timestamp_of("unknown.csv") == 0.0 and lap_number_of("unknown.csv") == 0
    groups = group_sessions(laps, lambda lap: lap[0], lambda lap: lap[1])
    numbers = [[lap_number_of(name) for name, _ in group] for group in groups]
    assert numbers == [[6], [5, 1], [3], [2], [1], [1, 2, 3]]  # newest session first, laps in driving order


def test_lap_list_shows_sessions(ui_env):
    import time

    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import LapViewer

    folder = cfg.path.telemetry.rstrip("/")
    base = time.mktime((2026, 10, 3, 14, 0, 0, 0, 0, -1))
    for number, lap_time in ((1, 92.0), (2, 90.0), (3, 91.0)):
        save_session_lap(folder, number, lap_time, base + number * 95, start=base)
    save_session_lap(folder, 1, 95.0, base + 7200, session="Race", start=base + 7000, valid=False)
    save_session_lap(folder, 2, 89.5, base + 7300, session="Race", start=base + 7000)
    viewer = LapViewer(None)
    try:
        sessions = viewer.session_items()
        assert [item.text(0) for item in sessions] == ["Race  03/10 15:56", "Practice  03/10 14:00"]
        race, practice = sessions
        assert race.text(1) == "1:29.500" and race.text(5) == "2 laps, Porsche 963"
        assert [practice.child(i).text(0) for i in range(3)] == ["Lap 1", "Lap 2", "Lap 3"]
        assert practice.child(0).text(5) == ""  # vehicle shown once, on session row
        assert "invalid" in race.child(0).text(5)
        assert race.isExpanded()  # reference (best lap) inside
        viewer.set_reference_item(race)  # session row: no lap
        assert viewer.reference_key.endswith("1m29.500s.csv")
        assert set(viewer.checked_paths()) <= {item.data(0, Qt.ItemDataRole.UserRole) for item in viewer.lap_items()}
    finally:
        viewer.close()
        flush_deleted()
