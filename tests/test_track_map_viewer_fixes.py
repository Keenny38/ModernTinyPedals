"""Track Map Viewer fixes: failed map named & map shown kept, loading state, recorded maps list, dropped files"""

import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, Qt, QUrl
from PySide6.QtTest import QTest

from neopedal.setting import cfg
from tests.test_audit_g_qml_pages import item_named, item_of_type, objects_of_type, pump, wait_until
from tests.test_perf_page_state import qml_warnings  # noqa: F401
from tests.test_track_map_viewer import wait_jobs, write_map


@pytest.fixture
def warnings(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text, *args: shown.append(text))
    return shown


@pytest.fixture
def viewer(ui_env, qml_warnings):  # noqa: F811
    from neopedal.ui.track_map_viewer import TrackMapViewer

    write_map(cfg.path.track_map)
    dialog = TrackMapViewer(None, cfg.path.track_map, "Ring")
    dialog.resize(900, 700)
    wait_jobs(dialog.backend)
    assert dialog.backend.loaded
    yield dialog
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not qml_warnings


@pytest.fixture
def empty_viewer(ui_env, qml_warnings):  # noqa: F811
    from neopedal.ui.track_map_viewer import TrackMapViewer

    dialog = TrackMapViewer(None)
    dialog.resize(900, 700)
    wait_jobs(dialog.backend)
    yield dialog
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not qml_warnings


# --- 1 & 2: failed load names the file that failed, map shown kept
def test_failed_read_names_file_and_keeps_map(viewer, warnings, monkeypatch, tmp_path):
    from neopedal.ui.quick import track_map_backend
    from neopedal.ui.quick.lines import VertexStore

    backend = viewer.backend
    backend.setPosition(500.0)
    before = (backend.geometry, backend.raw_coords, backend.view, backend.current, backend.map_file)
    road = VertexStore.get(backend.key("road"))
    write_map(f"{tmp_path.as_posix()}/", "Broken")

    def broken(filepath, filename):
        raise ValueError("bad map")

    monkeypatch.setattr(track_map_backend, "read_geometry", broken)
    changed = []
    backend.mapChanged.connect(lambda: changed.append(1))
    assert backend.load_map(f"{tmp_path.as_posix()}/", "Broken")
    wait_jobs(backend)
    assert len(warnings) == 1
    assert f"{tmp_path.as_posix()}/Broken.svg" in warnings[0] and "Ring" not in warnings[0]  # was "" + previous name
    assert not backend.loading and not changed
    assert (backend.geometry, backend.raw_coords, backend.view, backend.current, backend.map_file) == before
    assert backend.mapName == "Ring" and backend.position == 500.0
    assert VertexStore.get(backend.key("road")) is road  # vertices of map shown not released


def test_invalid_map_keeps_map_shown(viewer, warnings, tmp_path):
    backend = viewer.backend
    (tmp_path / "Logo.svg").write_text('<svg><path d="M0 0"/></svg>', encoding="utf-8")
    geometry = backend.geometry
    backend.load_map(f"{tmp_path.as_posix()}/", "Logo")
    wait_jobs(backend)
    assert len(warnings) == 1 and "Logo.svg" in warnings[0]
    assert backend.geometry is geometry and backend.loaded and backend.mapName == "Ring"


def test_failed_first_map_leaves_page_empty(empty_viewer, warnings, tmp_path):
    backend = empty_viewer.backend
    (tmp_path / "Logo.svg").write_text("<svg></svg>", encoding="utf-8")
    backend.load_map(f"{tmp_path.as_posix()}/", "Logo")
    wait_jobs(backend)
    assert warnings and not backend.loaded and backend.mapName == "" and backend.view == {}


# --- 3: loading state replaces empty state while reading
def test_loading_state_while_reading(empty_viewer):
    root, backend = empty_viewer.view.rootObject(), empty_viewer.backend
    state = item_named(root, "mapState")  # one TpStateView: loading wins over empty
    assert state.property("visible") and state.property("empty") and not state.property("loading")
    write_map(cfg.path.track_map)
    backend.load_map(cfg.path.track_map, "Ring")
    assert backend.loading
    assert state.property("visible") and state.property("loading")
    wait_jobs(backend)
    assert backend.loaded and not state.property("visible")


# --- 4: recorded maps of app folder (track picker)
def test_track_list_of_app_folder(viewer):
    from neopedal.ui.quick.track_map_backend import map_path

    backend = viewer.backend
    folder = cfg.path.track_map
    write_map(folder, "alpha")
    with open(f"{folder}notes.txt", "w", encoding="utf-8") as file:
        file.write("not a map")
    os.mkdir(f"{folder}folder.svg")  # folder with map extension: not listed
    backend.refreshTracks()
    assert backend.tracksLoading
    wait_jobs(backend)
    tracks = backend.tracks
    assert not backend.tracksLoading
    assert [entry["label"] for entry in tracks] == ["alpha", "Ring"]  # by name, any case
    assert tracks[1]["key"] == map_path(folder, "Ring") == backend.currentTrack
    assert all(entry["date"] not in ("", "-") and entry["current"] is False and "logo" in entry for entry in tracks)
    assert backend.currentLabel == "Ring" and not backend.allTracks
    backend.selectTrack(tracks[0]["key"])
    wait_jobs(backend)
    assert backend.mapName == "alpha" and backend.currentTrack == tracks[0]["key"]
    changed = []
    backend.tracksChanged.connect(lambda: changed.append(1))
    backend.refreshTracks()  # same maps: list not shown again (picker selection kept)
    wait_jobs(backend)
    assert not changed and backend.tracks == tracks


def test_track_list_missing_folder(empty_viewer, monkeypatch, tmp_path):
    from neopedal.ui.quick.track_map_backend import list_track_maps

    assert list_track_maps(f"{(tmp_path / 'missing').as_posix()}/") == []
    backend = empty_viewer.backend
    assert backend.tracks == [] and not backend.tracksLoading
    assert backend.currentTrack == "" and backend.currentLabel == "Choose a track map"


def test_track_picker_in_viewer(empty_viewer):
    root, backend = empty_viewer.view.rootObject(), empty_viewer.backend
    empty_viewer.show()
    pump(0.1)
    picker = item_of_type(root, "TrackPicker")
    assert picker is not None and picker.property("emptyText") == "No track map recorded yet"
    write_map(cfg.path.track_map, "Ring")  # recorded while page open: listed when picker opens
    QMetaObject.invokeMethod(picker, "openSearch")
    assert wait_until(lambda: len(backend.tracks) == 1)
    lists = objects_of_type(picker, "QQuickListView")
    assert lists and wait_until(lambda: lists[0].property("count") == 1)
    QTest.keyClick(empty_viewer.view, Qt.Key.Key_Return)  # first row picked
    assert wait_until(lambda: not backend.jobs.running and backend.loaded)
    assert backend.mapName == "Ring"
    assert wait_until(lambda: root.property("activeFocus"))  # left / right keys back to position


# --- 5: track map files dropped on page
def test_dropped_files(empty_viewer, tmp_path):
    from neopedal.ui.quick.track_map_backend import is_map_file

    backend = empty_viewer.backend
    write_map(f"{tmp_path.as_posix()}/", "Dropped")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    svg = QUrl.fromLocalFile(str(tmp_path / "Dropped.svg"))
    text = QUrl.fromLocalFile(str(tmp_path / "notes.txt"))
    missing = QUrl.fromLocalFile(str(tmp_path / "Missing.svg"))
    assert backend.droppedMap([text]) == "" and backend.droppedMap([missing]) == ""
    assert backend.droppedMap([QUrl("https://example.com/map.svg")]) == ""  # not a local file
    assert os.path.samefile(backend.droppedMap([text, svg]), tmp_path / "Dropped.svg")
    assert backend.droppedMap([svg.toString()]) != ""  # url text (QML url list)
    (tmp_path / "Upper.SVG").write_text("<svg></svg>", encoding="utf-8")
    assert not is_map_file(str(tmp_path)) and is_map_file(str(tmp_path / "Upper.SVG"))
    assert not backend.openDropped([text]) and not backend.loading
    assert backend.openDropped([svg])
    wait_jobs(backend)
    assert backend.loaded and backend.mapName == "Dropped"
    assert item_of_type(empty_viewer.view.rootObject(), "TpDropZone") is not None  # shared drop area (S15)
