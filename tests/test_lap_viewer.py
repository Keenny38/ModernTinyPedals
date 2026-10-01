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
        ))
    module_recorder.save_lap(f"{folder}/", "Track - GT3", lap_number, lap_time, rows, max_saved_laps=10)


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


def test_trajectory_map(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.lap_viewer import TrajectoryMap
    from tinypedal.userfile.telemetry_lap import LapData

    distance = [float(index) for index in range(0, 101, 10)]
    lap_a = LapData("a", {"distance": distance, "pos_x": [d * 2 for d in distance], "pos_y": [d for d in distance]})
    lap_b = LapData("b", {"distance": distance, "pos_x": [d * 2 + 1 for d in distance], "pos_y": distance})
    parent = QWidget()
    view = TrajectoryMap(parent)
    view.resize(300, 300)
    view.set_laps(lap_a, lap_b)
    view.set_cursor(50.0, (20.0, 60.0))
    assert len(view.positions(lap_a)) == 10  # (0, 0) means position not recorded
    assert not view.grab().isNull()
    assert view.positions(LapData("c", {"distance": distance})) == []  # positions not recorded
    parent.deleteLater()
