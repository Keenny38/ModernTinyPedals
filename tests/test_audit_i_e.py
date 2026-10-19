"""Performance audit 2026-10-18, lot E (lap viewer core): playback values about 10 times a second (cars every step,
exact values once stopped), lap filter reads the legend once, status signal only on change, live mode track folders
listed in background, minimap part shown outside its multisampled layer, track picker rows kept while searching"""

import json
import os
import threading

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, Qt
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest
from shiboken6 import Shiboken

from neopedal.setting import cfg
from tests.test_audit_g_qml_pages import item_of_type, objects_of_type, pump, wait_until
from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_e2 import START
from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_backend import backend, write_other_track  # noqa: F401
from tests.test_lap_viewer_fix_qml import chart_of, evaluate, find, named, opener, wait, warnings  # noqa: F401
from tests.test_perf_page_state import qml_warnings  # noqa: F401
from tests.test_track_map_viewer import wait_jobs, write_map


def js(view, scope, expression: str):
    return json.loads(evaluate(view, scope, f"JSON.stringify({expression})"))


def flat_map(points: list[dict]) -> list[float]:
    return [value for point in points for value in (point["x"], point["y"], point["angle"])]


def pointer(item) -> int:
    return Shiboken.getCppPointer(item)[0]


# --- B4: playback full states about 10 a second, cars every step, exact values once stopped
def count_steps(page, monkeypatch) -> dict:
    calls = {"full": 0, "light": 0}
    step = page.playbackStep

    def counted(seconds, full):
        calls["full" if full else "light"] += 1
        return step(seconds, full)

    monkeypatch.setattr(page, "playbackStep", counted)  # QML calls it through instance
    return calls


def test_playback_full_state_every_third_step(opener, warnings, monkeypatch):  # noqa: F811
    dialog = opener()
    view, page = dialog.view, dialog.backend
    page.setSideTab(0)
    wait(0.3)
    chart = chart_of(view)
    calls = count_steps(page, monkeypatch)
    evaluate(view, chart, "togglePlay()")
    assert chart.property("playing")
    wait(1.0)
    evaluate(view, chart, "togglePlay()")
    assert calls["full"] >= 1 and calls["light"] >= calls["full"]  # first step full, then 2 light per full
    assert calls["full"] <= 10 * 1.0 * 1.6 + 3  # about 10 full states a second
    x = chart.property("cursorX")
    wait(0.1)
    assert chart.property("cursorTitle") == page.cursorTitle(x)  # paused: values of last frame
    assert js(view, chart, "cursorMapXY") == pytest.approx(flat_map(page.mapCursor(x)))


def test_playback_end_and_skip_give_full_state(opener, warnings, monkeypatch):  # noqa: F811
    dialog = opener()
    view, page = dialog.view, dialog.backend
    page.setSideTab(0)
    wait(0.3)
    chart = chart_of(view)
    evaluate(view, chart, "togglePlay()")
    wait(0.2)
    evaluate(view, chart, "skipTime(1)")
    assert chart.property("playFull") == 0  # next step sends a full state
    evaluate(view, chart, "playTime = playTo - 0.05")  # ends within a step or two
    assert wait_until(lambda: not chart.property("playing"), 3.0)
    wait(0.1)
    x = chart.property("cursorX")
    assert x == pytest.approx(page.xAtReferenceTime(chart.property("playTo")))
    assert chart.property("cursorTitle") == page.cursorTitle(x)  # last frame values exact
    assert js(view, chart, "cursorMapXY") == pytest.approx(flat_map(page.mapCursor(x)))
    calls = count_steps(page, monkeypatch)
    evaluate(view, chart, "togglePlay()")  # played again from start: first step full
    wait(0.05)
    evaluate(view, chart, "togglePlay()")
    assert calls["full"] >= 1


# --- B9: lap filter reads the legend once per chart change
def test_lap_filter_single_and_forget_removed(opener, warnings):  # noqa: F811
    dialog = opener()
    view, page = dialog.view, dialog.backend
    page.setSideTab(1)
    wait(0.3)
    lap_filter = find(view, lambda item: item.property("single") is not None and item.property("marks") is not None)[0]
    keys = [entry["key"] for entry in page.legend]
    assert len(keys) >= 2 and lap_filter.property("single") is False
    evaluate(view, lap_filter, f"toggle({json.dumps(keys[0])})")
    assert evaluate(view, lap_filter, f"shown({json.dumps(keys[0])})") is False
    assert evaluate(view, lap_filter, f"shown({json.dumps(keys[1])})") is True
    page.setLapChecked(keys[0], False)  # hidden lap no longer compared: forgotten
    wait_loaded(dialog)
    wait(0.2)
    assert js(view, lap_filter, "hidden") == {}
    if len(page.legend) == 1:
        assert lap_filter.property("single") is True and not lap_filter.property("visible")


# --- Status signal only when status text or busy indicator change
def test_status_told_only_when_changed(backend):  # noqa: F811
    told: list[str] = []
    backend.statusChanged.connect(lambda: told.append(backend.status))
    backend.set_status("Hello", False)
    backend.set_status("Hello", False)
    assert told == ["Hello"] and not backend._status_timer.isActive()
    backend.set_status("Hello")  # transient now: cleared later, nothing new shown
    assert told == ["Hello"] and backend._status_timer.isActive()
    backend._status_timer.timeout.emit()
    assert told == ["Hello", ""]

    class Running:
        @staticmethod
        def is_alive():
            return True

    backend._loader, backend._load_total, backend._loaded = Running(), 3, {}
    try:
        for _ in range(5):  # load timer checks progress every 30 ms
            backend.check_background_load()
        assert told[2:] == ["Loading laps: 0/3"] and backend.loading
        backend._loaded = {"a": None}
        backend.check_background_load()
        assert told[3:] == ["Loading laps: 1/3"]
    finally:
        backend._loader = None
        backend._load_timer.stop()
    backend.set_status("Loading laps: 1/3", False)  # same text, busy indicator off: told
    assert len(told) == 5 and not backend.loading
    backend._infos_reading = True
    backend.notify_status()
    assert len(told) == 6 and backend.loading
    backend._infos_reading = False
    backend.notify_status()


# --- Live mode: other track folders listed in background, listings kept, no change lost while listing
def normal(path: str) -> str:
    return os.path.normpath(path)


@pytest.fixture
def tracks(backend):  # noqa: F811
    folder = cfg.path.telemetry.rstrip("/")
    others = [normal(os.path.join(folder, f"Other{number} - GT3")) for number in range(3)]
    for number in range(3):
        write_other_track(folder, f"Other{number} - GT3", 1, 80.0, START + 50)
    backend.refresh()
    wait_loaded(backend)
    return others


def spy_listings(page, monkeypatch) -> list[tuple[str, bool]]:
    listed: list[tuple[str, bool]] = []
    entries = page.folder_entries

    def spying(folder):
        listed.append((normal(folder), threading.current_thread() is threading.main_thread()))
        return entries(folder)

    monkeypatch.setattr(page, "folder_entries", spying)
    return listed


def test_live_mode_lists_track_folders_in_background(backend, tracks, monkeypatch):  # noqa: F811
    listed = spy_listings(backend, monkeypatch)
    backend.setLiveMode(True)
    watched = {normal(path) for path in backend._watcher.directories()}
    assert set(tracks) <= watched  # watched at once
    backend.wait_jobs()
    assert sorted(path for path, _ in listed) == sorted(tracks)  # telemetry & shown folders kept their listing
    assert not any(main for _, main in listed)  # never on page thread
    assert all(backend._watched[path] for path in tracks) and not backend._listing
    listed.clear()
    backend._watcher.directoryChanged.disconnect(backend.folder_changed)  # lap caches written: folder changes
    try:
        backend.watch_folders()  # track loaded again: watched folders keep their listing
        backend.load_track(backend.currentTrack)
        wait_loaded(backend)
        backend.wait_jobs()
    finally:
        backend._watcher.directoryChanged.connect(backend.folder_changed)
    assert listed == []
    backend.setLiveMode(False)
    assert not set(tracks) & set(backend._watched)
    assert len(backend._watcher.directories()) == 2


def test_lap_written_while_folder_listed_is_new(backend, tracks):  # noqa: F811
    backend.setLiveMode(True)
    assert set(tracks) <= backend._listing  # listing running (result handled by page thread later)
    folder = cfg.path.telemetry.rstrip("/")
    write_other_track(folder, "Other1 - GT3", 2, 81.0, START + 400)
    backend.folder_changed(tracks[1])
    assert "Other1 - GT3" in backend._new_lap_tracks  # unknown former listing: lap there may be new
    newer = backend._watched[tracks[1]]
    assert len(newer) == 2
    backend.wait_jobs()
    assert backend._watched[tracks[1]] == newer  # older background listing never replaces it
    backend._watch_timer.stop()


def test_listing_of_folder_no_longer_watched_dropped(backend, tracks):  # noqa: F811
    backend.setLiveMode(True)
    backend.setLiveMode(False)
    backend.wait_jobs()
    assert not set(tracks) & set(backend._watched) and not backend._listing


# --- Minimap: part shown & clicks outside the multisampled layer
def test_minimap_view_box_outside_layer(opener, warnings):  # noqa: F811
    dialog = opener()
    view, page = dialog.view, dialog.backend
    page.setSideTab(0)
    wait(0.3)
    minimaps = find(view, lambda item: item.property("side") is not None and item.property("mapScale") is not None)
    assert minimaps
    for minimap in minimaps:
        inside = [item for item in minimap.childItems() if item.property("x0") is not None
                  or "MouseArea" in item.metaObject().className()]
        assert not inside  # layer holds circuit only
        over = [item for item in minimap.parentItem().childItems() if item.z() == minimap.z()
                and any(child.property("x0") is not None for child in item.childItems())]
        assert len(over) == 1
        assert (over[0].x(), over[0].y(), over[0].width(), over[0].height()) == (
            minimap.x(), minimap.y(), minimap.width(), minimap.height())
        assert over[0].z() == minimap.z()
        box = next(child for child in over[0].childItems() if child.property("x0") is not None)
        assert box.property("antialiasing") is True


# --- Track picker: rows filtered in a model, delegates of kept rows stay
def test_track_list_model_search():
    from neopedal.ui.quick.lap_backend import TrackListModel

    model = TrackListModel()
    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))
    names = ["Spa - GT3", "Monza - GT3", "Le Mans - Hyper", "Sebring - GT3"]
    model.set_entries([{"key": name, "label": name, "logo": "", "date": "", "current": False} for name in names])
    assert [row["key"] for row in model.rows] == names
    model.setSearch("  GT3 ")  # any case, spaces around left out
    assert [row["key"] for row in model.rows] == ["Spa - GT3", "Monza - GT3", "Sebring - GT3"]
    model.setSearch("gt3 ")
    model.setSearch("SEB")
    assert [row["key"] for row in model.rows] == ["Sebring - GT3"]
    assert model.indexOf("Sebring - GT3") == 0 and model.indexOf("Spa - GT3") == -1
    assert model.keyAt(0) == "Sebring - GT3" and model.keyAt(1) is None
    model.setSearch("")
    assert [row["key"] for row in model.rows] == names and not resets  # rows removed & inserted, never reset


def test_track_rows_made_again_only_on_change(backend, monkeypatch):  # noqa: F811
    built: list[int] = []
    entries = backend.track_model.set_entries
    def counted(rows):
        built.append(1)
        entries(rows)

    monkeypatch.setattr(backend.track_model, "set_entries", counted)
    assert [row["key"] for row in backend.track_model.rows] == backend.tracks
    backend.tracksChanged.emit()  # same tracks
    assert not built
    backend.pictures_changed()  # circuit logos may have changed
    assert built == [1]


def test_lap_viewer_track_picker_uses_model(laps, opener, warnings):  # noqa: F811
    write_other_track(cfg.path.telemetry.rstrip("/"), "Other - GT3", 1, 80.0, START + 50)
    dialog = opener()
    view, page = dialog.view, dialog.backend
    picker = named(view, "trackBox")
    assert len(page.tracks) == 2
    QMetaObject.invokeMethod(picker, "openSearch")
    wait(0.3)
    lists = objects_of_type(picker, "QQuickListView")
    assert lists and lists[0].property("count") == 2
    assert lists[0].property("currentIndex") == page.tracks.index(page.currentTrack)
    search = next(item for item in objects_of_type(picker, "TpSearchField"))
    search.setProperty("text", "OTHER")
    QTest.keyClick(view, Qt.Key.Key_Down)  # search applied at once (typing settled), row 0 stays current
    assert [row["key"] for row in page.track_model.rows] == ["Other - GT3"] and lists[0].property("count") == 1
    QTest.keyClick(view, Qt.Key.Key_Return)  # search field has focus: row picked
    wait_loaded(dialog)
    assert page.currentTrack == "Other - GT3"
    assert [row["key"] for row in page.track_model.rows] == ["Other - GT3"]  # until picker opens again
    QMetaObject.invokeMethod(picker, "openSearch")
    wait(0.3)
    assert len(page.track_model.rows) == 2 and lists[0].property("currentIndex") == 1
    QTest.keyClick(view, Qt.Key.Key_Escape)


@pytest.fixture
def map_viewer(ui_env, qml_warnings):  # noqa: F811
    from neopedal.ui.track_map_viewer import TrackMapViewer

    dialog = TrackMapViewer(None)
    dialog.resize(900, 700)
    wait_jobs(dialog.backend)
    yield dialog
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not qml_warnings


def test_track_picker_rows_kept_while_searching(map_viewer):
    root, page = map_viewer.view.rootObject(), map_viewer.backend
    for name in ("Alpha", "Ring North", "Ring South"):
        write_map(cfg.path.track_map, name)
    map_viewer.show()
    pump(0.1)
    picker = item_of_type(root, "TrackPicker")
    QMetaObject.invokeMethod(picker, "openSearch")
    assert wait_until(lambda: len(page.tracks) == 3)
    listing = objects_of_type(picker, "QQuickListView")[0]
    assert wait_until(lambda: listing.property("count") == 3)
    pump(0.1)

    def row_item(index: int):
        return QQmlExpression(map_viewer.view.rootContext(), listing, f"itemAtIndex({index})").evaluate()[0]

    north = row_item(1)
    assert north is not None and north.property("label") == "Ring North"
    picker.setProperty("filter", "RING")
    pump(0.1)
    assert listing.property("count") == 2
    kept = row_item(0)
    assert kept is not None and pointer(kept) == pointer(north)  # same delegate, moved up
    assert QQmlExpression(map_viewer.view.rootContext(), picker, "keyAt(1)").evaluate()[0] == page.tracks[2]["key"]
    assert QQmlExpression(map_viewer.view.rootContext(), picker, "keyAt(2)").evaluate()[0] is None
    picker.setProperty("filter", "")
    pump(0.1)
    assert listing.property("count") == 3

    def run(expression: str):
        return QQmlExpression(map_viewer.view.rootContext(), picker, expression).evaluate()[0]

    # Tracks reordered, one renamed, one added, one gone: rows follow in order (moved, changed, inserted, removed)
    run('tracks = [{"key": "c", "label": "C"}, {"key": "a", "label": "A2", "current": true}, {"key": "b", "label": "B"}]')
    pump(0.1)
    run('tracks = [{"key": "a", "label": "A", "logo": "", "date": "x"}, {"key": "b", "label": "B"}, {"key": "c", "label": "C"}]')
    pump(0.1)
    first = row_item(0)
    assert first.property("label") == "A" and first.property("date") == "x"
    run('tracks = [{"key": "c", "label": "C"}, {"key": "a", "label": "A2", "current": true}, {"key": "d", "label": "D"}]')
    pump(0.1)
    assert [run(f"keyAt({index})") for index in range(4)] == ["c", "a", "d", None]
    assert row_item(1).property("label") == "A2" and row_item(1).property("current") is True
    assert pointer(row_item(1)) == pointer(first)  # row "a" kept (moved & changed in place)
    assert run('rowOf("d")') == 2 and run('rowOf("b")') == -1
    QTest.keyClick(map_viewer.view, Qt.Key.Key_Escape)
