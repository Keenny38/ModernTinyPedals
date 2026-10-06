"""Lap viewer audit fixes (backend state, loading & jobs): jobs lost with worker process, finished jobs handled once,
added laps of shown track listed once, selection & reference kept, analysis reset on track change, deletion while
loading & undo, unreadable laps read again, page hidden while laps are recorded, live mode, G circle built when shown"""

import concurrent.futures
import os
import threading
import time

import pytest
from PySide6.QtWidgets import QMessageBox

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_e2 import START, TRACK, lap_info, lap_path, write_lap


@pytest.fixture
def backend(ui_env, monkeypatch):
    """Page with 3 laps of TRACK: lap 1 fastest (90 s), lap 2 (91 s), lap 3 newest (92.5 s)"""
    from PySide6.QtWidgets import QWidget

    from tinypedal.setting import cfg
    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    folder = cfg.path.telemetry.rstrip("/")
    write_lap(folder, 1, 90.0, timestamp=START + 100)
    write_lap(folder, 2, 91.0, timestamp=START + 200)
    write_lap(folder, 3, 92.5, timestamp=START + 300)
    parent = QWidget()
    page = LapViewerBackend(parent, cfg.path.telemetry)
    page.refresh()
    wait_loaded(page)
    yield page
    page.release()
    parent.deleteLater()


def check(page, *paths, reference=""):
    page.checked = set(paths)
    page.reference_key = reference or paths[0]
    page.load_laps()
    wait_loaded(page)


def shown_keys(page) -> list[str]:
    return [lap.key for lap in page.data.laps]


def lap_rows(page, path: str) -> list[dict]:
    key = os.path.normcase(os.path.abspath(path))
    return [row for row in page.lap_rows() if os.path.normcase(os.path.abspath(row["path"])) == key]


# --- J19. Finished jobs handled once each, a failing result never drops the others
class SteppedHandle:
    """Job alive for `alive` checks, then finished with its name as result"""

    def __init__(self, name: str, alive: int):
        from tinypedal.ui.quick.lap_backend import JobHandle

        self.handle = JobHandle(name)
        self.handle.is_alive = self.is_alive  # type: ignore[method-assign]
        self.handle.result = lambda: name  # type: ignore[method-assign]
        self.alive = alive

    def is_alive(self) -> bool:
        self.alive -= 1
        return self.alive >= 0


def test_job_finishing_during_check_is_handled(backend):
    done: list[str] = []

    def failing(_result):
        raise ValueError("result not handled")

    ending = SteppedHandle("ending", 1)  # alive at first check, finished right after (was in neither list)
    backend.add_job(SteppedHandle("broken", 0).handle, failing)
    backend.add_job(SteppedHandle("first", 0).handle, done.append)
    backend.add_job(ending.handle, done.append)
    backend.check_jobs()
    assert done == ["first"] and [job[0].name for job in backend._jobs] == ["ending"]  # failing result: others done
    backend.check_jobs()
    assert done == ["first", "ending"] and not backend._jobs


# --- J6. Job lost with worker process: imports never run again in page process, other jobs one at a time
def broken_handle(name: str, pool):
    from tinypedal.ui.quick.lap_backend import JobHandle

    future: concurrent.futures.Future = concurrent.futures.Future()
    future.set_exception(concurrent.futures.process.BrokenProcessPool("worker killed"))
    return JobHandle(name, future=future, pool=pool)


def test_worker_death_import_not_run_again_in_page(backend, monkeypatch):
    from tinypedal.ui.quick import lap_backend

    monkeypatch.setattr(lap_backend, "_worker_broken", False)
    pool = lap_backend.worker_pool()
    assert pool is not None
    results: list = []
    ran: list[str] = []

    def running(name: str, result: str):
        def work():
            ran.append(name)
            return result
        return work

    # Victim job listed first, import lost with same worker process: import blamed, worker started again
    backend.add_job(broken_handle("session", pool), lambda result: results.append(("session", result)),
                    running("session", "values"))
    backend.add_job(broken_handle("MoTeC import", pool), lambda result: results.append(("import", result)),
                    running("import", "laps"))
    backend.check_jobs()
    assert ("import", None) in results and "import" not in ran  # told as failed, never read in page process
    assert not lap_backend._worker_broken and lap_backend._worker is None  # new worker for next jobs
    backend.wait_jobs()
    assert ran == ["session"] and ("session", "values") in results  # victim run again in fallback thread
    # Other job lost with worker: worker broken, job run again (fallback thread)
    pool = lap_backend.worker_pool()
    backend.add_job(broken_handle("track limits", pool), lambda result: results.append(("limits", result)),
                    lambda: "edges")
    backend.check_jobs()
    backend.wait_jobs()
    assert lap_backend._worker_broken and ("limits", "edges") in results
    lap_backend.stop_worker(kill=True)


def test_fallback_jobs_run_one_at_a_time(backend, monkeypatch):
    from tinypedal.ui.quick import lap_backend

    monkeypatch.setattr(lap_backend, "_worker_broken", True)  # worker process not available
    lap_backend.stop_worker(kill=True)
    lock = threading.Lock()
    state = {"running": 0, "most": 0}

    def export(index: int) -> str:
        with lock:
            state["running"] += 1
            state["most"] = max(state["most"], state["running"])
        time.sleep(0.03)
        with lock:
            state["running"] -= 1
        return f"lap {index}"

    done: list[str] = []
    for index in range(4):  # every lap of track exported
        backend.run_process_job("MoTeC export", done.append, export, index)
    exports = [job[0].future for job in backend._jobs if job[0].name == "MoTeC export"]
    assert len(exports) == 4 and all(future in lap_backend._export_futures or future.done()
                                     for future in exports)  # waited for at app exit like worker process exports
    backend.wait_jobs()
    assert sorted(done) == ["lap 0", "lap 1", "lap 2", "lap 3"] and state["most"] == 1
    # Page closed: its waiting jobs dropped (exports kept)
    gate = threading.Event()
    backend.run_process_job("session", done.append, gate.wait, 5)
    backend.run_process_job("mini-sectors", done.append, export, 9)
    waiting = backend._jobs[-1][0].future
    backend.release()
    gate.set()
    assert waiting.cancelled()


# --- J17 & J23. Added laps of shown track listed once, laps added again checked again
def test_added_lap_of_shown_track_listed_once(backend):
    from tinypedal.setting import cfg

    path = lap_path(backend, 2)
    picked = os.path.abspath(path).replace("\\", "/")  # file dialog: absolute path, other slashes
    backend.add_external([picked])
    wait_loaded(backend)
    assert not backend.external and path in backend.checked
    assert len(lap_rows(backend, path)) == 1 and shown_keys(backend).count(path) == 1
    # Lap of another class (same circuit) added, then its track shown: listed once, still checked
    other = write_other_track(cfg.path.telemetry.rstrip("/"), "Track - Hyper", 4, 89.0, START + 400)
    backend.add_external([os.path.abspath(other)])
    wait_loaded(backend)
    assert len(backend.external) == 1
    backend.load_track("Track - Hyper")
    wait_loaded(backend)
    assert not backend.external and len(lap_rows(backend, other)) == 1
    track_path = backend.entries[0].file.path
    assert track_path in backend.checked and shown_keys(backend).count(track_path) == 1


def write_other_track(folder: str, combo: str, number: int, lap_time: float, timestamp: float) -> str:
    write_lap(folder, number, lap_time, info=lap_info(combo=combo), combo=combo, timestamp=timestamp)
    track = os.path.join(folder, combo)
    return os.path.join(track, next(name for name in os.listdir(track) if f"lap{number:03d}" in name))


def test_library_lap_picked_again_is_checked(backend, tmp_path):
    other = write_other_track(str(tmp_path / "library"), "Track - GT3", 7, 89.5, START + 50)
    backend.add_from_library([other])
    wait_loaded(backend)
    added = backend.external[0].file.path
    assert backend.reference_key == added
    backend.setLapChecked(added, False)
    wait_loaded(backend)
    assert added not in backend.checked
    backend.add_from_library([other])  # picked again: shown again as reference
    wait_loaded(backend)
    assert added in backend.checked and backend.reference_key == added and len(backend.external) == 1


# --- J18. Saved selection kept when reference is an added lap
def test_selection_kept_with_added_reference(backend, tmp_path):
    from tinypedal.setting import cfg
    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    other = write_other_track(str(tmp_path / "library"), "Track - GT3", 7, 89.5, START + 50)
    backend.add_from_library([other])
    wait_loaded(backend)
    added = backend.external[0].file.path
    own = [lap_path(backend, 2), lap_path(backend, 3)]
    check(backend, added, *own)
    backend.refresh()
    wait_loaded(backend)
    assert backend.checked == {added, *own} and backend.reference_key == added
    # Next page: added lap gone, saved laps shown with fastest of them as reference (not best & newest laps)
    page = LapViewerBackend(backend._window, cfg.path.telemetry)
    page.refresh()
    wait_loaded(page)
    assert page.checked == set(own) and page.reference_key == own[0]
    page.release()


# --- J21. Analysis of former track not carried over
def test_track_change_resets_analysis(backend):
    from tinypedal.setting import cfg

    write_other_track(cfg.path.telemetry.rstrip("/"), "Other - GT3", 4, 89.0, START + 400)
    selected = []
    backend.selectionChanged.connect(lambda: selected.append(backend.selectedCorner))
    backend._align_apex, backend._selected_corner, backend._map_range = 1500.0, 1, (100.0, 200.0)
    backend._compare_key, backend._session_key = lap_path(backend, 2), "session"
    backend.refresh()  # same track: kept
    wait_loaded(backend)
    assert backend._align_apex == 1500.0 and backend._selected_corner == 1 and backend._map_range == (100.0, 200.0)
    backend.load_track("Other - GT3")
    wait_loaded(backend)
    assert backend._align_apex == -1.0 and backend._map_range == (-1.0, -1.0) and not backend.data.offsets
    assert backend._compare_key == "" and backend._session_key == "" and selected == [-1]
    assert backend.alignment == {}


# --- J22 & J40. Deletion while loading, undo restores whole deletion & reference
def test_delete_while_loading(backend, monkeypatch):
    first, second, third = (lap_path(backend, number) for number in (1, 2, 3))
    check(backend, first, second)
    backend._lap_cache.pop(third, None)
    backend.checked = {third}
    backend.reference_key = third
    backend.load_laps()  # third lap read in background
    assert backend._loader is not None
    replace = os.replace
    monkeypatch.setattr(os, "replace", lambda source, target: (_ for _ in ()).throw(PermissionError("locked"))
                        if source == third else replace(source, target))
    backend.deleteLaps([third])  # file locked: nothing moved once loaded
    wait_loaded(backend)
    assert shown_keys(backend) == [third]  # charts follow selection anyway (were left on former laps)
    monkeypatch.setattr(os, "replace", replace)
    # One deletion split between laps being read & others: undo restores all of it
    check(backend, second)
    backend._lap_cache.pop(third, None)
    backend.checked = {second, third}
    backend.load_laps()
    backend.deleteLaps([first, third])
    wait_loaded(backend)
    assert not os.path.exists(first) and not os.path.exists(third) and len(backend._undo) == 2
    assert backend.undoText.endswith("(2)")
    backend.undoDelete()
    wait_loaded(backend)
    assert os.path.exists(first) and os.path.exists(third) and third in backend.checked


def test_undo_restores_reference(backend):
    first, second = lap_path(backend, 1), lap_path(backend, 2)
    check(backend, first, second, reference=first)
    backend.deleteLap(first)
    wait_loaded(backend)
    assert backend.reference_key == second
    backend.undoDelete()
    wait_loaded(backend)
    assert backend.reference_key == first and shown_keys(backend)[0] == first


# --- J38 & J39. Unreadable lap read again, reference never an unreadable lap
def test_unreadable_lap_read_again(backend, monkeypatch):
    first, second = lap_path(backend, 1), lap_path(backend, 2)
    load = backend.load_lap_file
    locked = {first}

    def loading(path):
        if path in locked:
            raise OSError("locked by antivirus")
        return load(path)

    monkeypatch.setattr(backend, "load_lap_file", loading)
    backend._lap_cache.clear()
    check(backend, first, second, reference=first)
    assert shown_keys(backend) == [second] and backend.reference_key == second  # first lap read is reference
    saved = __import__("tinypedal.ui.lap_viewer", fromlist=["x"]).load_viewer_setting(backend.folder)
    assert saved["selections"][TRACK]["reference"] == os.path.basename(second)
    rows = {row["path"]: row for row in backend.lap_rows()}
    assert rows[first]["error"] and rows[second]["reference"]
    backend.setLapChecked(second, True)  # still checked & unreadable: not read again on every change
    wait_loaded(backend)
    assert backend._lap_cache[first] is None
    locked.clear()
    backend.setLapChecked(first, False)
    backend.setLapChecked(first, True)  # checked again: read again
    wait_loaded(backend)
    assert first in shown_keys(backend)
    # Refresh: laps that could not be read are read again
    locked.add(second)
    backend._lap_cache.pop(second)
    check(backend, first, second)
    assert backend._lap_cache[second] is None
    locked.clear()
    backend.refresh()
    wait_loaded(backend)
    assert set(shown_keys(backend)) == {first, second}


# --- J58. Page hidden while laps are recorded: listed & read once shown
def test_hidden_page_updated_once_shown(backend):
    from tinypedal.setting import cfg

    folder = cfg.path.telemetry.rstrip("/")
    backend.page_hidden()
    backend.release_laps()
    assert backend._released and not backend.data.laps
    write_lap(folder, 4, 93.0, timestamp=START + 400)
    rows = len(backend.lap_rows())
    backend.auto_refresh()  # lap recorded while hidden: nothing listed nor read
    assert backend._released and not backend.data.laps and len(backend.lap_rows()) == rows
    backend.page_shown()
    wait_loaded(backend)
    assert len(backend.lap_rows()) == rows + 1 and backend.data.laps and not backend._released


def test_release_once_loading_is_done(backend):
    backend.page_hidden()
    backend._lap_cache.clear()
    backend.load_laps()
    assert backend._loader is not None
    backend._release_timer.stop()
    backend.release_laps()  # loading: released later
    assert not backend._released and backend._release_timer.isActive()
    wait_loaded(backend)
    backend.release_laps()
    assert backend._released and not backend.data.laps
    backend.page_shown()
    wait_loaded(backend)
    assert backend.data.laps


# --- J61. Live mode: new best lap compared, chosen reference kept, lap of another track shown
def test_live_mode_keeps_chosen_reference(backend, tmp_path):
    from tinypedal.setting import cfg

    other = write_other_track(str(tmp_path / "library"), "Track - GT3", 7, 89.5, START + 50)
    backend.setLiveMode(True)
    backend.add_from_library([other])
    wait_loaded(backend)
    added = backend.external[0].file.path
    write_lap(cfg.path.telemetry.rstrip("/"), 4, 88.0, timestamp=START + 400)  # new best lap
    backend.auto_refresh()
    wait_loaded(backend)
    new = lap_path(backend, 4)
    assert backend.reference_key == added and backend.checked == {added, new}
    backend.compareBest(1)  # best lap chosen: follows new laps
    wait_loaded(backend)
    write_lap(cfg.path.telemetry.rstrip("/"), 5, 87.0, timestamp=START + 500)
    backend.auto_refresh()
    wait_loaded(backend)
    assert backend.reference_key == new and backend.checked == {new, lap_path(backend, 5)}


def test_live_mode_shows_lap_of_other_track(backend):
    from tinypedal.setting import cfg

    folder = cfg.path.telemetry.rstrip("/")
    write_other_track(folder, "Other - GT3", 1, 80.0, START + 50)  # older laps on another track
    backend.refresh()
    wait_loaded(backend)
    backend.setLiveMode(True)
    other = os.path.join(backend.folder, "Other - GT3")
    assert any(os.path.normpath(path) == os.path.normpath(other) for path in backend._watcher.directories())
    write_other_track(folder, "Other - GT3", 2, 81.0, START + 400)
    backend.folder_changed(other)  # watched in live mode
    backend.auto_refresh()
    wait_loaded(backend)
    assert backend.currentTrack == "Other - GT3"
    new = lap_path(backend, 2)
    assert backend.checked == {new, lap_path(backend, 1)} and backend.reference_key == lap_path(backend, 1)
    assert "New lap" in backend.status
    # First lap on a new track: shown too
    write_other_track(folder, "New - GT3", 1, 85.0, START + 500)
    backend.auto_refresh()
    wait_loaded(backend)
    assert backend.currentTrack == "New - GT3" and backend.checked == {lap_path(backend, 1)}
    backend.setLiveMode(False)
    assert len(backend._watcher.directories()) == 2  # telemetry & shown track folders only


# --- J53. G circle built only when its tab is shown
def test_gcircle_built_when_shown(backend):
    built = []
    backend.gCircleChanged.connect(lambda: built.append(True))
    backend.setSideTab(0)
    check(backend, lap_path(backend, 1), lap_path(backend, 2))
    assert backend._gcircle_stale and not backend._g_points and not built
    backend.setSideTab(1)
    assert not backend._gcircle_stale and len(backend._gcircle["dots"]) == 2 and built
    key = backend._gcircle["dots"][0]["key"]
    from tinypedal.ui.quick.lines import VertexStore

    assert VertexStore.has(key)
    backend.setSideTab(2)
    check(backend, lap_path(backend, 1))  # hidden: dots of laps still shown kept, others dropped
    assert backend._gcircle_stale and VertexStore.has(key) == (backend._gcircle["dots"][0]["key"] == key)
    assert len(backend.gCircle["dots"]) == 1 and not backend._gcircle_stale  # read: built now
    assert len(backend.gCursor(100.0)) == 1


# --- J56. Panel height, corner sort & map turn: only their part of the page told (QML items of charts kept)
def test_partial_changes_never_redraw_whole_page(backend):
    from tinypedal.ui.lap_viewer import CHANNEL_MAP

    check(backend, *(entry.file.path for entry in backend.entries))
    sent: list[str] = []
    for name in ("chartChanged", "panelsChanged", "cornersChanged", "mapDataChanged"):
        getattr(backend, name).connect(lambda name=name: sent.append(name))
    column = backend.panels[0]["column"]
    assert column in CHANNEL_MAP
    backend.setPanelWeight(column, 2.0)
    backend.setPanelAutoscale(column, True)
    assert sent == ["panelsChanged", "panelsChanged"]
    sent.clear()
    backend.setCornerSort("loss")
    assert sent == ["cornersChanged"]
    sent.clear()
    backend.map_rotated()
    assert "chartChanged" not in sent
    sent.clear()
    backend.alignBraking(-1)  # not aligned: nothing changed
    assert sent == []
    sent.clear()
    backend.chartChanged.emit()  # whole page: every part told too
    assert sorted(sent) == ["chartChanged", "cornersChanged", "mapDataChanged", "panelsChanged"]
