"""Lap viewer phase 2 (package E2): value zoom & autoscale, math channels, laps aligned on braking point, time base
CSV, foreign laps, similar conditions reference, setup differences, corner report"""

import math
import os
import time

import pytest

from tests.test_lap_viewer import wait_loaded
from tinypedal.module import module_recorder

TRACK = "Track - GT3"
START = 1_700_000_000  # session start of test laps


def lap_info(**values) -> dict:
    """Lap info of a recorded lap of test circuit, values changed"""
    info = {"kind": "lap", "track": "Track", "combo": "Track", "vehicle": "Car A", "class": "GT3",
            "session": "Practice", "track_length": 3000.0, "track_temperature": 30.0, "wetness": 0.0,
            "session_start": START, "fuel_start": 50.0, "fuel_end": 48.0}
    info.update(values)
    return info


def write_lap(folder, number, lap_time, brake=0.45, info=None, samples=400, length=3000.0, bias=56.0, combo=TRACK,
              timestamp=None):
    """Recorded lap around a circle, braking from brake share of lap to mid lap, slow corner at mid lap"""
    rows = []
    radius = length / (2 * math.pi)
    for index in range(samples + 1):
        progress = index / samples
        angle = progress * 2 * math.pi
        values = {
            "time": progress * lap_time, "lap_time": progress * lap_time, "distance": progress * length,
            "speed_kph": 180.0 - (60.0 if brake < progress < 0.55 else 0.0),
            "throttle": 0.0 if brake < progress < 0.55 else min(1.0, progress * 4),
            "brake": 0.8 if brake < progress < 0.5 else 0.0,
            "gear": 4, "rpm": 7000, "fuel": 50.0, "pos_x": radius * math.cos(angle) + 1,
            "pos_y": radius * math.sin(angle) + 1, "accel_lat": math.sin(angle * 3), "accel_long": -0.5,
            "steering": 0.2, "yaw": (angle + math.pi) % math.tau - math.pi, "brake_bias": bias,
            "tc_level": 3, "abs_level": -1, "engine_map": 1,
        }
        rows.append(tuple(values.get(column, 0) for column in module_recorder.CSV_HEADER))
    module_recorder.save_lap(f"{folder}/", combo, number, lap_time, rows, max_saved_laps=50,
                             info=info if info is not None else lap_info(), timestamp=timestamp)


@pytest.fixture(autouse=True)
def no_math_channels_left():
    """Math channels of a test never stay in CHANNEL_MAP (other tests list every channel)"""
    yield
    from tinypedal.ui.lap_viewer import set_math_channels

    set_math_channels([])


@pytest.fixture
def backend(ui_env):
    from PySide6.QtWidgets import QWidget

    from tinypedal.setting import cfg
    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 90.0, brake=0.45, info=lap_info(setup="aaaa1111", setup_name="Quali"), timestamp=START + 100)
    write_lap(folder, 2, 91.0, brake=0.43, info=lap_info(track_temperature=34.5, setup="bbbb2222"), bias=55.0,
              timestamp=START + 200)
    write_lap(folder, 3, 92.5, brake=0.44, info=lap_info(track_temperature=31.0, setup="aaaa1111"),
              timestamp=START + 300)
    parent = QWidget()
    page = LapViewerBackend(parent, cfg.path.telemetry)
    page.refresh()
    wait_loaded(page)
    yield page
    page.release()
    parent.deleteLater()


def lap_path(page, number: int) -> str:
    return next(entry.file.path for entry in page.entries if f"lap{number:03d}" in entry.file.filename)


def show(page, *numbers, reference=None):
    page.checked = {lap_path(page, number) for number in numbers}
    page.reference_key = lap_path(page, reference or numbers[0])
    page.load_laps()
    wait_loaded(page)
    page.wait_jobs()


# 1. Value zoom & autoscale of each panel
def test_value_axis_and_autoscale(backend):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import load_viewer_setting

    show(backend, 1, 2)
    speed = next(panel for panel in backend.panels if panel["column"] == "speed_kph")
    assert speed["autoscale"] is False and speed["ticks"]
    whole = backend.autoscaleAxis("speed_kph", 0.0, 3000.0)
    assert whole["low"] < 120.0 < 180.0 < whole["high"]  # corner & straight speed with margin
    straight = backend.autoscaleAxis("speed_kph", 100.0, 900.0)  # flat out: flat line kept in middle
    assert straight["low"] < 180.0 < straight["high"] and straight["high"] - straight["low"] < 20
    assert straight["lowText"] and straight["highText"]
    corner = backend.autoscaleAxis("speed_kph", 1500.0, 1600.0)
    assert corner["low"] < 120.0 < corner["high"] < 140.0  # corner speed only
    entry = backend.autoscaleAxis("speed_kph", 1200.0, 1500.0)
    assert entry["low"] < 120.0 and entry["high"] > 180.0  # both speeds in view
    zoomed = backend.valueAxis("throttle", 0.5, 1.0)
    assert zoomed["lowText"] == "50%" and zoomed["highText"] == "100%" and len(zoomed["ticks"]) == 3
    assert backend.valueAxis("unknown", 0, 1) == {} and backend.valueAxis("speed_kph", 2, 1) == {}
    backend.setPanelAutoscale("speed_kph", True)
    assert next(panel for panel in backend.panels if panel["column"] == "speed_kph")["autoscale"]
    assert load_viewer_setting(cfg.path.telemetry)["panel_autoscale"] == ["speed_kph"]
    backend.setPanelAutoscale("speed_kph", False)
    assert load_viewer_setting(cfg.path.telemetry)["panel_autoscale"] == []


# 2. Math channels
def test_math_expression_parser_is_safe():
    from tinypedal.ui.quick import math_channels as mc

    assert mc.expression_error("abs(steering) * 2 + max(speed_kph, 100) / d(brake) - pi") == ""
    for expression, error in (
        ("", "Empty expression"), ("speed_kph ** 2", "Not allowed: only + - * /"),
        ("__import__('os').system('x')", "Not allowed: only abs, min, max & d functions"),
        ("speed_kph.real", "Not allowed: only channels, numbers, + - * / abs min max d"),
        ("speed_kph[0]", "Not allowed: only channels, numbers, + - * / abs min max d"),
        ("lambda: 1", "Not allowed: only channels, numbers, + - * / abs min max d"),
        ("'text'", "Not allowed: only numbers"), ("True", "Not allowed: only numbers"),
        ("abs(1, 2)", "abs() takes one value"), ("min()", "min() takes one value or more"),
        ("speed_kph +", "Syntax error"), ("1" + "+1" * 200, "Expression too long"),
        ("(" * 100 + "1" + ")" * 100, ""),
    ):
        assert mc.expression_error(expression) == error, expression
    assert mc.expression_error("speed + 1", lambda name: name == "speed_kph") == "Unknown channel: speed"
    assert mc.input_names(mc.parse_expression("d(brake) * max(throttle, brake) + g")) == ["brake", "throttle"]
    values = mc.evaluate("max(-d(brake), 0) * 100", {"brake": [1.0, 1.0, 0.5, 0.0]}, [0.0, 0.1, 0.2, 0.3], 4)
    assert values == pytest.approx([0.0, 250.0, 500.0, 500.0])  # centered, one-sided at lap start & end
    assert mc.evaluate("min(x)", {"x": [3.0, 1.0, 2.0]}, [0, 1, 2], 3) == [1.0, 1.0, 1.0]
    assert mc.evaluate("x / 0 + 1e308 * 10", {"x": [1.0]}, [0], 1) == [0.0]  # no infinite values
    assert mc.evaluate("2 * 3", {}, [0, 1], 2) == [6.0, 6.0]
    assert mc.unwrapped([3.1, -3.1]) == pytest.approx([3.1, -3.1 + math.tau])
    assert mc.name_error("Rate", ["rate"]) == "Name already used" and mc.name_error(" x", []) == "Name needed"
    assert mc.name_error("a|b", []) and not mc.name_error("Brake Release Rate", [])
    channels = mc.parse_channels([{"name": "A", "expression": "brake"}, {"name": "a", "expression": "1"},
                                  {"name": "B", "expression": "x ** 2"}, "bad", {"name": 3}])
    assert channels == [mc.MathChannel("A", "brake", "")]


def test_math_channels_on_charts(backend):
    from tinypedal.setting import cfg
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, load_viewer_setting

    show(backend, 1, 2)
    assert backend.checkMathChannel("", "Release", "max(-d(brake), 0) * 100") == ""
    assert backend.checkMathChannel("", "Bad", "nothing * 2") == "Unknown channel: nothing"
    assert backend.saveMathChannel("", "Release", "max(-d(brake), 0) * 100", "%/s") == ""
    assert backend.saveMathChannel("", "release", "brake", "") == "Name already used"
    column = "math:Release"
    assert column in backend.visible and column in CHANNEL_MAP
    panel = next(panel for panel in backend.panels if panel["column"] == column)
    assert panel["available"] and panel["unit"] == "%/s" and panel["series"]
    lap = backend.data.laps[0]
    xs, ys = backend.data.series(CHANNEL_MAP[column], lap)
    assert len(xs) == len(ys) > 100 and max(ys) > 0 and min(ys) >= 0  # brake released at mid lap only
    menu = [item for item in backend.channelMenu if item["column"] == column]
    assert menu and menu[0]["visible"] and menu[0]["group"] == "Math Channels"
    assert any(row["column"] == column for row in backend.xyChannels)
    assert "yaw_rate" in backend.mathInputs and "brake" in backend.mathInputs
    saved = load_viewer_setting(cfg.path.telemetry)
    assert saved["math_channels"] == [{"name": "Release", "expression": "max(-d(brake), 0) * 100", "unit": "%/s"}]
    # Changed expression: drawn again (new vertex key)
    old_key = panel["series"][0]["key"]
    assert backend.saveMathChannel("Release", "Release", "max(-d(brake), 0) * 50", "%/s") == ""
    new_panel = next(panel for panel in backend.panels if panel["column"] == column)
    assert new_panel["series"][0]["key"] != old_key
    assert max(backend.data.series(CHANNEL_MAP[column], lap)[1]) == pytest.approx(max(ys) / 2)
    # Built-in understeer angle: yaw rate from recorded heading
    assert backend.addMathPreset(0) == ""
    understeer = CHANNEL_MAP["math:Understeer Angle"]
    assert backend.data.available(understeer)
    values = backend.data.series(understeer, lap)[1]
    assert all(math.isfinite(value) for value in values)
    assert backend.addMathPreset(0) == "Name already used"
    # Removed: gone from charts & settings
    backend.removeMathChannel("Release")
    assert column not in backend.visible and column not in CHANNEL_MAP
    assert [item["name"] for item in load_viewer_setting(cfg.path.telemetry)["math_channels"]] == ["Understeer Angle"]


def test_math_channels_restored_with_viewer(backend):
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    backend.saveMathChannel("", "Twice", "speed_kph * 2", "")
    parent = QWidget()
    other = LapViewerBackend(parent, backend.folder)
    try:
        assert "math:Twice" in other.visible and other.mathChannels[0]["name"] == "Twice"
    finally:
        other.release()
        parent.deleteLater()


# 3. Laps aligned on braking point
def test_laps_aligned_on_braking_point(backend):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP

    show(backend, 1, 2, 3)
    assert backend.corners and backend.alignment == {}
    index = next(row["index"] for row in backend.corners if row["kind"] == "corner")
    brake = CHANNEL_MAP["brake"]
    lap2 = next(lap for lap in backend.data.laps if lap.key == lap_path(backend, 2))
    before = backend.data.series(brake, lap2)[0][0]
    backend.alignBraking(index)
    info = backend.alignment
    assert info["index"] == index and len(info["laps"]) == 2
    offset = backend.data.offsets[lap2.key]
    assert offset == pytest.approx(60.0, abs=10.0)  # brakes 2% of 3000 m earlier: shifted forward
    xs = backend.data.series(brake, lap2)[0]
    assert xs[0] == pytest.approx(before + offset)
    assert backend.data.series(brake, lap2, aligned=False)[0][0] == pytest.approx(before)  # place on track kept
    legend = {row["key"]: row["offset"] for row in backend.legend}
    assert legend[lap2.key].startswith("+") and legend[lap_path(backend, 1)] == ""
    series = next(panel for panel in backend.panels if panel["column"] == "brake")["series"]
    assert any("|o" in item["key"] for item in series)  # shifted series drawn apart
    assert backend.data.lap_distance_at_x(lap2, 1000.0) == pytest.approx(1000.0 - offset)
    backend.setTimeAxis(True)  # time axis: never shifted
    assert backend.data.shift_of(lap2) == 0.0
    backend.setTimeAxis(False)
    backend.alignBrakingAt(backend.data.x_at_distance(1500.0))
    assert backend.alignment["index"] == index
    backend.alignBraking(-1)
    assert backend.alignment == {} and backend.data.offsets == {}


# 4. CSV on time base
def test_csv_on_time_base(backend, tmp_path):
    show(backend, 1, 2)
    target = tmp_path / "time.csv"
    assert backend.write_csv(str(target), ".", time_base=True)
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("Time (s),")
    times = [float(line.split(",")[0]) for line in lines[1:]]
    assert times[:3] == pytest.approx([0.0, 0.02, 0.04])
    assert times[-1] == pytest.approx(91.0, abs=0.03)  # longest lap
    assert backend.write_csv(str(tmp_path / "distance.csv"), ".")
    assert (tmp_path / "distance.csv").read_text(encoding="utf-8-sig").splitlines()[2].startswith("1,")


# 7. Laps imported from another driver's folder
def test_import_foreign_laps(backend, tmp_path):
    from tinypedal.userfile import lap_library

    other = tmp_path / "Teammate"
    write_lap(str(other), 7, 89.5, info=lap_info(vehicle="Car B"), timestamp=START + 50)
    write_lap(str(other), 8, 89.0, info=lap_info(track="Other", combo="Other", track_length=4000.0),
              combo="Other - GT3", timestamp=START + 60)
    write_lap(str(other), 9, 88.0, info=lap_info(**{"class": "Hyper"}), combo="Track - Hyper", timestamp=START + 70)
    hidden = other / ".trash"
    hidden.mkdir()
    (hidden / "x lap001 1m30.000s.csv").write_text("x", encoding="utf-8")
    backend.import_folder(str(other), background=False)
    wait_loaded(backend)  # status of import shown again once lap is read
    foreign = [entry for entry in backend.external if entry.foreign]
    assert len(foreign) == 1 and "lap007" in foreign[0].file.filename
    assert foreign[0].file.path in backend.checked  # fastest foreign lap shown
    assert lap_library.is_foreign(foreign[0].file.path)
    assert "1 foreign lap(s) imported from Teammate" in backend.status and "2 skipped" in backend.status
    rows = [row for row in backend.lap_model.rows if row["path"] == foreign[0].file.path]
    assert rows and "foreign" in rows[0]["info"]
    headers = [row for row in backend.lap_model.rows if row["kind"] == "session" and "foreign laps" in row["info"]]
    assert headers
    groups = lap_library.list_imported(backend.folder)
    assert [name for name, _ in groups] == ["Teammate"]
    from tinypedal.ui.lap_library import LapLibrary

    backend.openLibrary()  # imported laps library: group of another driver's laps told apart
    library = next(widget for widget in backend._window.findChildren(LapLibrary))
    assert library.tree.topLevelItem(0).text(library.COL_DRIVER) == "foreign laps"
    library.close()
    backend.import_folder(str(other), background=False)  # imported again: new group
    assert [name for name, _ in lap_library.list_imported(backend.folder)] == ["Teammate", "Teammate (2)"]
    backend.import_folder(backend.folder, background=False)
    assert "own telemetry folder" in backend.status
    assert lap_library.compatible_lap(lap_info(), lap_info(**{"class": "LMP2"}), "GT3") == "class"
    assert lap_library.compatible_lap(lap_info(), {}, "GT3", os.path.join("x", "Track - LMP2", "a.csv")) == "class"
    assert lap_library.compatible_lap(lap_info(), lap_info(track_length=3600.0), "GT3") == "circuit"


# 8. Reference lap driven in similar conditions
def test_reference_in_similar_conditions(backend):
    from tinypedal.ui.quick.lap_conditions import lap_compound, similar_best

    show(backend, 1, 3, reference=1)  # lap 3 looked at (31 °C): lap 1 (30 °C) is fastest within 3 °C
    backend.compareSimilarConditions()
    assert backend.reference_key == lap_path(backend, 1) and lap_path(backend, 3) in backend.checked
    assert "Reference in similar conditions" in backend.status
    show(backend, 3, 2, reference=3)  # lap 2 at 34.5 °C: no lap within 3 °C
    backend.compareSimilarConditions()
    assert "No other clean lap" in backend.status and backend.reference_key == lap_path(backend, 3)
    backend.setSimilarTolerance(5)
    assert backend.similarTolerance == 5 and [row["value"] for row in backend.similarTolerances] == [1, 2, 3, 5, 8]
    backend.compareSimilarConditions()
    assert backend.reference_key == lap_path(backend, 1)
    assert lap_compound({"compound": ["Soft", "Soft"]}) == "Soft" and lap_compound({}) == ""
    assert lap_compound({"tyre_compound": "Medium"}) == "Medium"
    entries = backend.entries
    wet = {**entries[0].info, "wetness": 0.6}
    assert similar_best(entries, wet, 3) is None  # dry laps only
    soft = {"track_temperature": 30.0, "compound": "Soft"}
    medium = [entry._replace(info={**entry.info, "compound": "Medium"}) for entry in entries]
    assert similar_best(medium, soft, 10) is None and similar_best(entries, soft, 10) is not None


# 9. Setup differences
def test_setup_differences(backend):
    from tinypedal.ui.quick.lap_conditions import setup_diff

    show(backend, 1, 2, 3, reference=1)
    diff = backend.setupDiff("", lap_path(backend, 2))
    assert diff["state"] == "different" and diff["a"] and diff["b"]
    rows = {row["name"]: row for row in diff["rows"]}
    assert rows["Brake Bias"]["differs"] and rows["Brake Bias"]["a"] == "56.0" and rows["Brake Bias"]["b"] == "55.0"
    assert not rows["TC Level"]["differs"] and "ABS Level" not in rows  # car without ABS setting (-1)
    assert rows["Setup"]["a"] == "Quali" and rows["Setup"]["b"] == "—"
    same = backend.setupDiff("", lap_path(backend, 3))
    assert same["state"] == "same" and "Same setup" in same["note"]
    assert backend.setupDiff("", lap_path(backend, 1)) == {}  # same lap
    assert setup_diff({}, {}, None, None) == {"state": "unknown", "rows": []}
    assert backend.isCompared(lap_path(backend, 2)) and not backend.isCompared(lap_path(backend, 1))


# 10. Corner report
def test_corner_report(backend, tmp_path):
    from tinypedal.ui.quick.corner_report import build_report

    show(backend, 1, 2)
    image = backend.corner_map_image()
    assert image is not None and not image.isNull() and image.width() > 100
    target = tmp_path / "report.html"
    assert backend.write_report(str(target))
    text = target.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>") and "data:image/png;base64," in text
    assert 'src="http' not in text and "href=" not in text and "<script" not in text  # nothing outside the file
    assert "<table>" in text and "Total" in text
    pdf = tmp_path / "report.pdf"
    assert backend.write_report(str(pdf))
    assert pdf.read_bytes()[:4] == b"%PDF"
    escaped = build_report("<b>", "", [{"label": "<i>", "color": "#fff"}], ["A"], ["a"], [{"a": "<x>", "aColor": "loss"}],
                           [{"label": "T1", "loss": "+0.1", "causes": ["<y>"]}], "Coach")
    assert "<h1>&lt;b&gt;</h1>" in escaped and "&lt;x&gt;" in escaped and "&lt;i&gt;" in escaped
    assert 'class="loss"' in escaped and "&lt;y&gt;" in escaped


# 6. Mini-sector consistency on map
def test_mini_sector_spread_and_job(backend):
    from tinypedal.userfile.lap_geometry import mini_sector_job, mini_sector_spread

    assert mini_sector_spread([[1.0, 2.0], [1.0, 2.2], [1.0, 2.4]]) == pytest.approx([0.0, 0.2])
    assert mini_sector_spread([[1.0], [1.1]]) == [-1.0]  # under 3 laps
    assert mini_sector_spread([[1.0, 0.0], [1.2, 0.0], [1.4, 0.0]])[1] == -1.0  # no time there
    paths = [lap_path(backend, number) for number in (1, 2)]
    found = mini_sector_job(backend.folder, [*paths, "missing.csv"], [0.0, 1500.0, 3000.0], 3000.0)
    assert set(found) == set(paths)
    assert sum(found[paths[0]]) == pytest.approx(90.0, abs=0.05) and len(found[paths[1]]) == 2


def test_consistency_map(backend):
    show(backend, 1)
    backend.setMapMode("consistency")
    backend.wait_jobs()  # laps of session not shown: mini-sector times read in background
    legend = backend.mapLegend
    assert legend["consistency"] and legend["scope"] == "session" == backend.consistencyScope
    assert backend._consistency["laps"] == 3 and max(backend._consistency["spreads"]) > 0
    assert legend["low"] and legend["high"] and "3 laps" in legend["text"]
    assert backend._map["colored"] and backend.trackMap
    backend.setConsistencyScope("shown")  # one lap shown: not enough
    assert "3 clean laps" in backend.mapLegend["text"] and "low" not in backend.mapLegend
    lap2 = next(entry for entry in backend.entries if entry.file.path == lap_path(backend, 2))
    lap2.info["kind"] = "in"  # pit entry after lap 1: stint of lap 1 ends there
    backend.setConsistencyScope("stint")
    assert backend.consistency_paths() == [lap_path(backend, 1)]
    backend.setConsistencyScope("bad")
    assert backend.consistencyScope == "stint"
    from tinypedal.ui.quick import lap_map
    from tinypedal.userfile.lap_geometry import MapLine

    line = MapLine([0.0, 500.0, 1500.0, 2500.0], [0.0] * 4, [0.0] * 4)
    colors = lap_map.spread_colors(line, [0.0, 1000.0, 2000.0, 3000.0], [0.1, -1.0, 0.3])
    assert colors[0] == lap_map.CONSISTENCY_COLORS[0] and colors[-1] == lap_map.CONSISTENCY_COLORS[-1]
    assert colors[2].name() == "#9ca3af"  # unknown spread


def test_map_g_circle_and_xy_zoom(backend):
    """Map keys zoom & move, G circle & XY scatter zoom, lap filter of a view"""
    from PySide6.QtCore import Q_ARG, QCoreApplication, QMetaObject, qInstallMessageHandler
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick import create_quick_view

    show(backend, 1, 2)
    scatter = backend.scatter("speed_kph", "throttle")
    assert scatter["xRange"][0] < scatter["xRange"][1]
    ticks = backend.axisTicks("speed_kph", 120.0, 140.0)
    assert [tick["value"] for tick in ticks] == [120.0, 125.0, 130.0, 135.0, 140.0]
    assert backend.axisTicks("speed_kph", 2.0, 1.0) == [] and backend.axisTicks("nothing", 0, 1) == []
    assert all("lap" in row for row in backend.histogram("throttle")["laps"])
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    parent = QWidget()
    try:
        for page in ("GCircle.qml", "XYView.qml", "LapFilter.qml"):
            view = create_quick_view(parent, page, {"backend": backend})
            view.resize(600, 500)
            view.show()
            for _ in range(5):
                QCoreApplication.processEvents()
            assert not view.errors(), page
            root = view.rootObject()
            if page == "GCircle.qml":
                QMetaObject.invokeMethod(root, "zoomAt", Q_ARG("QVariant", 2.0), Q_ARG("QVariant", 300.0),
                                         Q_ARG("QVariant", 250.0))
                assert root.property("zoom") == pytest.approx(2.0)
                QMetaObject.invokeMethod(root, "resetZoom")
                assert root.property("zoom") == 1.0 and root.property("centerX") == 0.0
            if page == "XYView.qml":
                QMetaObject.invokeMethod(root, "zoomAt", Q_ARG("QVariant", 4.0), Q_ARG("QVariant", 0.0),
                                         Q_ARG("QVariant", 0.0))
                assert root.property("zoomed") and root.property("viewX") == 0.0
                assert root.property("xTicks").toVariant()  # values of part shown
            if page == "LapFilter.qml":
                QMetaObject.invokeMethod(root, "toggle", Q_ARG("QVariant", lap_path(backend, 2)))
                assert root.property("hidden").toVariant() == {lap_path(backend, 2): True}
        view = create_quick_view(parent, "MapCanvas.qml", {})
        canvas = view.rootObject()
        canvas.setProperty("width", 400.0)
        canvas.setProperty("height", 400.0)
        canvas.setProperty("maxX", 1000.0)
        canvas.setProperty("maxY", 1000.0)
        from PySide6.QtCore import Q_RETURN_ARG, Qt

        def key(name: str) -> bool:
            return QMetaObject.invokeMethod(canvas, "handleKey", Q_RETURN_ARG("QVariant"),
                                            Q_ARG("QVariant", int(getattr(Qt.Key, name))))

        assert not key("Key_Left") and canvas.property("targetZoom") == 1.0  # whole map: nothing to move
        assert key("Key_Plus") and canvas.property("targetZoom") == pytest.approx(1.5)
        assert key("Key_Left") and canvas.property("targetPanX") > 0
        assert key("Key_Minus") and canvas.property("targetZoom") == pytest.approx(1.0)
        assert not key("Key_A")
    finally:
        qInstallMessageHandler(previous)
        parent.deleteLater()
    # Tabs loaded alone have no chart (Connections to it warn): page itself checked in test below
    assert not [text for text in messages if ".qml" in text and "Connections" not in text
                and "Unable to assign [undefined] to QObject*" not in text], messages


def test_qml_page_loads_with_new_parts(backend):
    """Lap viewer page with math channels editor & setup differences loads without warning"""
    from PySide6.QtCore import QCoreApplication, qInstallMessageHandler
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick import create_quick_view

    show(backend, 1, 2)
    backend.saveMathChannel("", "Twice", "speed_kph * 2", "")
    backend.setPanelAutoscale("speed_kph", True)
    backend.alignBraking(0)
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    parent = QWidget()
    try:
        view = create_quick_view(parent, "LapViewer.qml", {"backend": backend})
        view.resize(1400, 900)
        view.show()
        for _ in range(10):
            QCoreApplication.processEvents()
        assert not view.errors()
        stack, chart = [view.rootObject()], None
        while stack:
            item = stack.pop()
            if item.property("yViews") is not None:
                chart = item
            stack.extend(item.childItems())
        assert chart is not None
        for _ in range(30):  # autoscale timer
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert "speed_kph" in chart.property("yViews").toVariant()  # autoscaled panel range
        # Math channels editor & setup differences opened (popups of page)
        from PySide6.QtCore import Q_ARG, QMetaObject, QObject

        editor = view.rootObject().findChild(QObject, "mathEditor")
        QMetaObject.invokeMethod(editor, "open")
        QMetaObject.invokeMethod(editor, "edit", Q_ARG("QVariant", {"name": "Twice", "expression": "speed_kph * 2",
                                                                    "unit": ""}))
        QMetaObject.invokeMethod(editor, "check")
        assert editor.property("editing") == "Twice" and editor.property("error") == ""
        diff = view.rootObject().findChild(QObject, "setupDiff")
        QMetaObject.invokeMethod(diff, "show", Q_ARG("QVariant", lap_path(backend, 2)))
        assert diff.property("visible")
        for _ in range(10):
            QCoreApplication.processEvents()
        backend.setMapMode("consistency")  # map legend of consistency mode
        for tab in (1, 2, 5, 0):  # G circle, corners, XY tabs created with chart
            backend.setSideTab(tab)
            for _ in range(5):
                QCoreApplication.processEvents()
    finally:
        qInstallMessageHandler(previous)
        parent.deleteLater()
    assert not [text for text in messages if ".qml" in text], messages
