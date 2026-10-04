"""Official corner numbers: circuit found from track name & lap length, corners placed on track bends"""

import math

import pytest

from tinypedal.userfile.track_corners import CIRCUITS, Circuit, bends, find_circuit, place_corners, track_corners, words


def oval_with_bends(length: float, bend_fractions: list[float], step: float = 2.0):
    """Closed track made of straights & sharp 90 degree bends at given lap fractions"""
    distances, xs, ys = [], [], []
    heading, x, y = 0.0, 0.0, 0.0
    turns = sorted(bend_fractions)
    count = int(length / step)
    for index in range(count + 1):
        distance = index * step
        fraction = distance / length
        # Heading turns over 30 m around each bend apex
        for apex in turns:
            if abs(fraction - apex) * length <= 15:
                heading += (math.pi / 2) / (30 / step)
        distances.append(distance)
        xs.append(x)
        ys.append(y)
        x += math.cos(heading) * step
        y += math.sin(heading) * step
    return distances, xs, ys


def test_words_and_find_circuit():
    assert words("Circuit de Spa-Francorchamps") == " circuit de spa francorchamps "
    assert words("Autódromo José Carlos Pace") == " autodromo jose carlos pace "
    assert find_circuit("Circuit de Spa-Francorchamps", 6973).keywords[0] == "spa"
    assert find_circuit("Spa Endurance", 7004) is not None
    assert find_circuit("Espace Raceway", 7004) is None  # "spa" must be a word
    assert find_circuit("Circuit de Spa-Francorchamps", 4000) is None  # other layout
    assert find_circuit("Bahrain International Circuit - Endurance", 6299) is None
    assert find_circuit("Paul Ricard - 1A-V2-Short", 3800) is None
    assert find_circuit("Michelin Raceway Road Atlanta", 4076) is not None
    assert find_circuit("Unknown Ring", 5000) is None
    assert find_circuit("Monza", 0) is None


def test_circuit_data_ordered():
    for circuit in CIRCUITS:
        fractions = [fraction for _, fraction in circuit.corners]
        labels = [label for label, _ in circuit.corners]
        assert all(0 < fraction < 1 for fraction in fractions), circuit.keywords
        assert len(set(labels)) == len(labels), circuit.keywords
        if circuit.keywords != ("laguna seca",):  # Laguna Seca turn 1 is right after start
            assert fractions == sorted(fractions), circuit.keywords


def test_bends_found():
    distances, xs, ys = oval_with_bends(2000.0, [0.2, 0.45, 0.7, 0.95])
    found = bends(distances, xs, ys)
    assert len(found) == 4
    assert found == pytest.approx([0.2, 0.45, 0.7, 0.95], abs=0.006)
    assert bends(distances[:5], xs[:5], ys[:5]) == []  # too short


def test_corners_snap_to_bends_with_start_offset():
    distances, xs, ys = oval_with_bends(2000.0, [0.2, 0.45, 0.7, 0.95])
    # Source measures laps from another line: every corner 2% late, last one 4% late
    circuit = Circuit(("test",), 2000, (("1", 0.22), ("2", 0.47), ("3", 0.72), ("3a", 0.99), ("4", 0.60)))
    corners = place_corners(circuit, distances, xs, ys)
    assert [corner.label for corner in corners] == ["1", "2", "3", "3a", "4"]
    assert [corner.distance / 2000 for corner in corners[:3]] == pytest.approx([0.2, 0.45, 0.7], abs=0.006)
    assert corners[3].distance / 2000 == pytest.approx(0.97, abs=0.001)  # bend too far: offset only
    assert corners[4].distance / 2000 == pytest.approx(0.58, abs=0.001)  # no bend near: offset only
    index = distances.index(400.0)
    assert (corners[0].x, corners[0].y) == pytest.approx((xs[index], ys[index]), abs=10)


def test_track_corners():
    distances, xs, ys = oval_with_bends(4080.0, [0.112, 0.18, 0.238, 0.278, 0.346, 0.482, 0.532, 0.859, 0.92])
    corners, numbered = track_corners("Michelin Raceway Road Atlanta", distances, xs, ys)
    assert numbered and [corner.label for corner in corners][:7] == ["1", "2", "3", "4", "5", "6", "7"]
    assert corners[5].distance == pytest.approx(0.482 * 4080, abs=30)
    names, numbered = track_corners("Circuit de la Sarthe", *oval_with_bends(13626.0, [0.05, 0.14, 0.57]))
    assert not numbered and names[0].label == "Dunlop Curve"
    assert track_corners("Unknown", distances, xs, ys) == ([], True)
    assert track_corners("Monza", [0.0], [0.0], [0.0]) == ([], True)


def test_corner_labels_translated():
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("T10a") == "V10a" and i18n.trm("T5-6") == "V5-6" and i18n.trm("T8a-9") == "V8a-9"
        assert i18n.tr("Porsche Curves") == "Virages Porsche"
    finally:
        i18n.set_language("English")


def test_lap_viewer_uses_official_corners(ui_env):
    """Corners found on laps & map labels named after official corners of circuit"""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QWidget

    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import PlotLap
    from tinypedal.ui.quick.lap_backend import LapViewerBackend
    from tinypedal.userfile.telemetry_lap import LapData

    distances, xs, ys = oval_with_bends(4080.0, [0.112, 0.18, 0.238, 0.278, 0.346, 0.482, 0.532, 0.859, 0.876,
                                                 0.92, 0.96])
    # Slow down in each bend: corners found on speed
    speeds = []
    for distance in distances:
        gap = min(abs(distance / 4080 - apex) for apex in (0.112, 0.346, 0.482, 0.532, 0.859)) * 4080
        speeds.append(120 + min(gap, 100) * 1.2)
    times, elapsed = [], 0.0
    for index, distance in enumerate(distances):
        if index:
            elapsed += (distance - distances[index - 1]) / (speeds[index] / 3.6)
        times.append(elapsed)
    lap = LapData("ra", {"distance": distances, "lap_time": times, "speed_kph": speeds, "pos_x": xs, "pos_y": ys},
                  {"track": "Michelin Raceway Road Atlanta"})
    parent = QWidget()
    backend = LapViewerBackend(parent, cfg.path.telemetry)
    try:
        backend.data.set_laps([PlotLap("a", "a", lap, QColor("red")), PlotLap("b", "b", lap, QColor("blue"))])
        backend.rebuild_chart()
        assert backend.track_name() == "Michelin Raceway Road Atlanta"
        labels = [mark["label"] for mark in backend.cornerMarks]
        assert labels == ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T10a", "T10b", "T11", "T12"]
        assert [point["label"] for point in backend.trackMap["corners"]] == labels  # every official corner
        rows = [row for row in backend.corners if row["kind"] == "corner"]
        assert [row["label"] for row in rows][:2] == ["T1", "T5"]
        assert all(row["label"].startswith("T") for row in rows)
        chip = backend.trackMap["corners"][0]
        assert chip["start"] < 0.112 * 4080 < chip["end"]  # zooms charts on its corner
    finally:
        parent.deleteLater()
