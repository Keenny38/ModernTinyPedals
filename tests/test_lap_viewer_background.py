"""Lap viewer work off the page thread: chart series & map shapes built in background (same results as built at once),
lap infos read in background (track open, new lap files, imported laps library), single lap exports as jobs, lap marks
saved once per folder"""

import os
import re
import threading

import pytest
from PySide6.QtWidgets import QMessageBox

from tests.test_lap_library import import_log, wait_library
from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_e2 import START, TRACK, write_lap
from tests.test_lap_viewer_fix_backend import backend  # noqa: F401


def off_thread(calls: list[bool]) -> bool:
    """Every recorded call ran off the page thread (and there was one)"""
    return bool(calls) and not any(calls)


def record_threads(owner, name: str, calls: list[bool], only=None):
    """Record whether each call of owner.name runs on the page (main) thread, only calls passing only(args)"""
    method = getattr(owner, name)

    def recorded(*args, **kwargs):
        if only is None or only(*args):
            calls.append(threading.current_thread() is threading.main_thread())
        return method(*args, **kwargs)

    return recorded


def panel_vertices(page) -> dict[str, bytes]:
    """Vertex data of chart panels (series, reduced copies, envelopes) by key without page prefix"""
    from neopedal.ui.quick.lines import VertexStore

    keys = [key for panel in page._panels for series in panel["series"]
            for key in [series["key"], *(lod for _, lod in series["lods"])]]
    keys += [panel["envelope"] for panel in page._panels if panel["envelope"]]
    # Ideal lap delta version left out (counts ideal lap deltas computed)
    return {re.sub(r"\|i\d+", "|i", key.removeprefix(page.prefix)): bytes(VertexStore.get(key).data) for key in keys}


def series_values(page) -> dict[tuple, tuple]:
    """Chart series values of shown laps for visible channels"""
    from neopedal.ui.lap_viewer import CHANNEL_MAP

    return {(lap.key, part): tuple(tuple(values) for values in page.data.series(CHANNEL_MAP[part], lap))
            for lap in page.data.laps for column in page.visible
            for part in CHANNEL_MAP[column].parts or (column,)}


# --- Chart series built in background (settings changed), same as built at once
@pytest.mark.parametrize("change", ["smoothing", "envelope", "channel", "ideal", "window"])
def test_chart_built_in_background_same_as_at_once(backend, monkeypatch, change):  # noqa: F811
    from neopedal.ui import lap_viewer

    page = backend
    page.checked = {entry.file.path for entry in page.entries}  # 3 laps (envelope)
    page.load_laps()
    wait_loaded(page)

    def apply(on: bool):
        if change == "smoothing":
            page.setSmoothing(2 if on else 0)
        elif change == "envelope":
            page.setEnvelope(on)
        elif change == "channel":
            page.setChannelVisible("rpm", on)
        elif change == "ideal":
            page.setIdealDelta(on)
        else:
            page.setDeltaWindow(80 if on else 40)

    monkeypatch.setattr(lap_viewer, "BACKGROUND_CHART_SAMPLES", 10 ** 9)  # built at once
    apply(True)
    assert not page.is_loading()
    expected, values = panel_vertices(page), series_values(page)
    apply(False)
    monkeypatch.setattr(lap_viewer, "BACKGROUND_CHART_SAMPLES", 1)  # any change built in background
    calls: list[bool] = []
    monkeypatch.setattr(page, "chart_vertices", record_threads(page, "chart_vertices", calls,
                                                               lambda data, *_: data is not page.data))
    before = page.panels
    apply(True)
    assert page.is_loading() and page.panels is before  # former charts kept until series are built
    page.wait_jobs()
    assert not page.is_loading() and off_thread(calls)
    assert panel_vertices(page) == expected and series_values(page) == values


def test_chart_settings_waiting_applied_together(backend, monkeypatch):  # noqa: F811
    """Settings changed while series are built: older build dropped, every setting applied once built"""
    from neopedal.ui import lap_viewer
    from neopedal.ui.lap_viewer import SMOOTHING_LEVELS

    page = backend
    monkeypatch.setattr(lap_viewer, "BACKGROUND_CHART_SAMPLES", 1)
    adopted = []
    adopt = page.data.adopt
    monkeypatch.setattr(page.data, "adopt", lambda snapshot: adopted.append(adopt(snapshot)) or adopted[-1])
    page.setSmoothing(1)
    page.setDeltaWindow(80)
    assert page.data.smoothing == 0 and page.data.delta_window == 40  # charts shown keep former settings
    assert page.smoothing == 1 and page.deltaWindow == 80  # options show picked values at once
    page.wait_jobs()
    assert page.data.smoothing == SMOOTHING_LEVELS[1] and page.data.delta_window == 80
    assert adopted == [True]  # first build dropped: series of both settings built by second one
    page.setTimeAxis(True)
    assert not page.timeAxis  # charts switched once built
    page.setTimeAxis(False)  # switched back meanwhile
    page.wait_jobs()
    assert not page.timeAxis and not page.data.time_axis


def test_time_axis_switched_in_background(backend, monkeypatch):  # noqa: F811
    from neopedal.ui import lap_viewer

    page = backend
    restored = []
    page.viewRestored.connect(lambda start, end: restored.append((start, end)))
    page.setChartView(1000.0, 2000.0)  # zoomed: same part of lap kept in view
    monkeypatch.setattr(lap_viewer, "BACKGROUND_CHART_SAMPLES", 1)
    page.setTimeAxis(True)
    assert not page.timeAxis and not restored
    page.wait_jobs()
    assert page.timeAxis and page._panels_axis
    assert restored and restored[-1][0] == pytest.approx(page.data.x_at_distance(1000.0))


def test_laps_shown_prepared_by_loading_thread(backend, monkeypatch):  # noqa: F811
    """Laps loaded in background: trace data set & chart series built by loading thread, same as set at once"""
    from neopedal.ui.lap_viewer import CHANNEL_MAP
    from neopedal.ui.quick.trace_data import TraceData

    page = backend
    paths = [entry.file.path for entry in page.entries]
    calls: list[bool] = []
    monkeypatch.setattr(page, "chart_vertices", record_threads(page, "chart_vertices", calls,
                                                               lambda data, *_: data is not page.data))
    adopted = []
    adopt_laps = page.data.adopt_laps
    monkeypatch.setattr(page.data, "adopt_laps", lambda *args: adopted.append(adopt_laps(*args)) or adopted[-1])
    page._lap_cache.clear()  # read again: loading thread
    page.checked = set(paths)
    page.reference_key = paths[1]
    page.load_laps()
    assert page.is_loading()
    wait_loaded(page)
    assert adopted == [True] and off_thread(calls)
    assert page.data.laps[0].key == paths[1] and all(lap.label for lap in page.data.laps)
    expected = TraceData()
    expected.set_smoothing(page.data.smoothing)
    expected.set_laps(list(page.data.laps), paths[1])
    for lap in page.data.laps:
        for column in page.visible:
            for part in CHANNEL_MAP[column].parts or (column,):
                assert list(page.data.series(CHANNEL_MAP[part], lap)[1]) == pytest.approx(
                    list(expected.series(CHANNEL_MAP[part], lap)[1]))
    assert panel_vertices(page)


def test_trace_data_snapshot_adopted_unless_changed(ui_env):
    from neopedal.ui.quick.trace_data import TraceData

    data = TraceData()
    snapshot = data.snapshot()
    snapshot.set_smoothing(5)
    snapshot._series[("lap", "speed_kph", False, 0.0)] = ([0.0], [1.0])
    assert data.smoothing == 0 and not data._series  # own caches
    assert data.adopt(snapshot) and data.smoothing == 5 and data._series
    other = data.snapshot()
    data.set_delta_window(80.0)  # changed meanwhile: snapshot too old
    assert not data.adopt(other) and data.delta_window == 80.0


# --- Track map: shapes sized for map scale built in background
def test_map_first_scale_built_in_background(backend, monkeypatch):  # noqa: F811
    from neopedal.ui.quick.lines import VertexStore

    page = backend
    calls: list[bool] = []
    monkeypatch.setattr(page, "scale_shapes", record_threads(page, "scale_shapes", calls))
    page.rebuild_chart_now()
    assert page._map and not page._band_cache and page.map_pending()  # never built on page thread
    page.wait_jobs()
    assert off_thread(calls) and page._band_cache and not page.map_pending()
    assert VertexStore.get(page.trackMap["road"]).vertex_count > 10


# --- Lap infos read in background
def test_track_infos_and_new_laps_read_in_background(ui_env, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from neopedal.setting import cfg
    from neopedal.ui.quick.lap_backend import LapViewerBackend
    from neopedal.userfile import lap_cache

    folder = cfg.path.telemetry.rstrip("/")
    for number in (1, 2):
        write_lap(folder, number, 90.0 + number, timestamp=START + number * 100)
    calls: list[bool] = []
    monkeypatch.setattr(lap_cache, "read_lap_info", record_threads(lap_cache, "read_lap_info", calls))
    parent = QWidget()
    page = LapViewerBackend(parent, cfg.path.telemetry)
    try:
        page.refresh()
        assert page.reading_infos() and page.is_loading() and not page.entries  # 2 new lap files: read in background
        wait_loaded(page)
        page.wait_jobs()  # index saved in background
        assert len(page.entries) == 2 and off_thread(calls)
        assert os.path.isfile(page.info_index_path(TRACK))
        write_lap(folder, 3, 92.5, timestamp=START + 300)  # recorded while shown
        calls.clear()
        page.auto_refresh()
        assert page.reading_infos() and len(page.entries) == 2  # listed once read
        wait_loaded(page)
        assert len(page.entries) == 3 and off_thread(calls)
    finally:
        page.release()
        parent.deleteLater()


def test_library_reads_lap_infos_once_in_background(ui_env, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent

    from neopedal.setting import cfg
    from neopedal.ui.lap_viewer import LapViewer
    from neopedal.userfile import lap_cache

    import_log(cfg.path.telemetry, "Spa race", [139.5, 138.2])
    calls: list[bool] = []
    monkeypatch.setattr(lap_cache, "read_lap_info", record_threads(lap_cache, "read_lap_info", calls))
    viewer = LapViewer(None)
    try:
        library = viewer.backend.library  # imported laps library panel
        library.open()
        assert library.is_refreshing() and library.model.rowCount() == 0
        wait_library(library)
        rows = [dict(row) for row in library.model.rows]
        assert len(rows) == 3 and rows[0]["track"] == "Spa" and off_thread(calls)
        library.select(rows[2]["key"], "set")
        calls.clear()
        library.refresh()
        wait_library(library)
        assert not calls  # lap infos from index of imported log
        rows = [dict(row) for row in library.model.rows]
        assert rows[2]["selected"] and rows[0]["driver"] == "Pro"  # selection kept
    finally:
        viewer.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# --- Single lap exports in background
def test_motec_and_delta_best_exports_are_jobs(backend, monkeypatch, tmp_path):  # noqa: F811
    from neopedal.setting import cfg
    from neopedal.ui.quick import lap_export

    page = backend
    target = tmp_path / "lap.ld"
    monkeypatch.setattr(lap_export.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    page.exports.exportMotec(page.reference_key)
    assert page.is_loading() and "MoTeC export" in [handle.name for handle, *_ in page._jobs]
    page.wait_jobs()
    assert target.exists() and page.status == "Exported: lap.ld" and not page.is_loading()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    calls: list[bool] = []
    monkeypatch.setattr(lap_export, "load_cached_lap", record_threads(lap_export, "load_cached_lap", calls))
    path = page.entries[0].file.path
    page._lap_cache.pop(path, None)  # read by job
    page.exports.exportDeltaBest(path)
    assert "delta best" in [handle.name for handle, *_ in page._jobs]
    page.wait_jobs()
    assert off_thread(calls) and os.path.isfile(os.path.join(cfg.path.delta_best, f"{TRACK}.csv"))
    assert "Delta best of" in page.status


# --- Lap marks: one marks file read & save per folder
def test_marks_saved_once_per_folder(tmp_path, monkeypatch):
    from neopedal.userfile import lap_marks

    folder = tmp_path / "Track - GT3"
    folder.mkdir()
    paths = [str(folder / f"lap{number}.csv") for number in range(4)]
    saves = []
    save_marks = lap_marks.save_marks
    monkeypatch.setattr(lap_marks, "save_marks", lambda *args: saves.append(args[0]) or save_marks(*args))
    assert lap_marks.set_marks(paths, kept=True, note=" fast ")
    assert len(saves) == 1
    assert all(mark == {"kept": True, "note": "fast"} for mark in lap_marks.load_marks(str(folder)).values())
    assert lap_marks.remove_marks(paths[:3]) and len(saves) == 2
    assert list(lap_marks.load_marks(str(folder))) == ["lap3.csv"]
    assert lap_marks.remove_marks([str(folder / "other.csv")]) and len(saves) == 2  # nothing removed: not saved
