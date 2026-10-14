"""Audit h, lot a1b: replay copy never leaves a .part file, page settings written once changes pause (shared
PageSettings), director keep-alive connections always closed, lap viewer fallback thread frees its last job,
track map rebuilt when zoomed while loading, camera table & game click shared (game_camera)"""

import gc
import json
import threading
import time
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject

from neopedal.setting import cfg
from tests.test_broadcast_director import director_page  # noqa: F401
from tests.test_game_info import replays_page  # noqa: F401
from tests.test_track_map_viewer import viewer, wait_jobs  # noqa: F401


def process_events(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def wait_until(condition, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return condition()


# --- 1. Replay copy: .part removed whatever stops the copy
@pytest.fixture
def copy_files(tmp_path, monkeypatch):
    from neopedal.ui.quick import replay_files

    monkeypatch.setattr(replay_files, "CHUNK_SIZE", 100)
    folder, source = tmp_path / "Replays", tmp_path / "Downloads"
    folder.mkdir()
    source.mkdir()
    (source / "Spa R1 1.Vcr").write_bytes(b"x" * 1000)
    return replay_files, folder, source


def test_copy_progress_error_removes_part(copy_files):
    replay_files, folder, source = copy_files

    def progress(value: float):  # page deleted meanwhile: signal emit raises RuntimeError
        raise RuntimeError("Internal C++ object already deleted")

    with pytest.raises(RuntimeError):
        replay_files.copy_replays([str(source / "Spa R1 1.Vcr")], str(folder), progress)
    assert list(folder.iterdir()) == []


def test_copy_cancelled_while_copying_removes_part(copy_files):
    replay_files, folder, source = copy_files
    cancelled = threading.Event()
    result = replay_files.copy_replays([str(source / "Spa R1 1.Vcr")], str(folder), lambda _: cancelled.set(),
                                       cancelled)
    assert result.cancelled and result.added == [] and list(folder.iterdir()) == []


def test_copy_progress_of_closed_page_dropped(ui_env):
    from neopedal.ui.quick import replays_backend

    class Page(QObject):
        def __init__(self):
            super().__init__()
            self.progress: list[float] = []

        def set_copy_progress(self, value: float):
            self.progress.append(value)

    page = Page()
    progress = replays_backend.copy_reporter(page)
    thread = threading.Thread(target=progress, args=(0.5,))  # copy thread: page never touched there
    thread.start()
    thread.join()
    assert page.progress == [] and wait_until(lambda: page.progress == [0.5])  # handed over on the UI thread
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # page closed during the copy
    thread = threading.Thread(target=progress, args=(0.75,))
    thread.start()
    thread.join()
    process_events(0.05)  # dropped, nothing raised


# --- 2. & 7. Page settings written once changes pause
def test_replays_seconds_before_written_once(replays_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import page_settings, replays_backend

    backend = replays_page.backend
    writes: list[tuple[str, dict]] = []
    real = page_settings.write_settings
    monkeypatch.setattr(page_settings, "write_settings", lambda name, data: writes.append((name, data)) or real(
        name, data))
    for seconds in range(6, 16):  # SpinBox arrow held
        backend.setSecondsBefore(seconds)
    backend.setPanel(1)
    backend.setIncidentFilter(1)
    assert writes == [] and backend.page_file.pending
    process_events(page_settings.SAVE_DELAY_MS / 1000 + 0.3)
    writes[:] = [write for write in writes if write[0] == "game_replays.json"]  # results tab & list of fixture apart
    assert len(writes) == 1 and writes[0][0] == "game_replays.json" and writes[0][1]["seconds_before"] == 15
    backend.setSecondsBefore(20)
    assert replays_backend.load_page_settings()["seconds_before"] == 20  # read: changes of open page written first
    backend.setSecondsBefore(21)
    backend.release()  # page closing: written at once
    assert len(writes) == 3 and writes[-1][1]["seconds_before"] == 21 and not backend.page_file.pending


def test_page_settings_file(ui_env):
    from neopedal.ui.quick import page_settings

    path = page_settings.settings_path("test_page.json")
    assert page_settings.load_settings("test_page.json") == {}  # missing
    with open(path, "w", encoding="utf-8-sig") as file:  # edited by hand, with BOM
        file.write('{"a": 1}')
    assert page_settings.load_settings("test_page.json") == {"a": 1}
    with open(path, "w", encoding="utf-8") as file:
        file.write("[1, 2]")
    assert page_settings.load_settings("test_page.json") == {}  # not a dict
    data = {"name": "Équipe", "values": [1, 2], "nested": {"x": True}}
    page_settings.write_settings("test_page.json", data)
    with open(path, encoding="utf-8") as file:  # same format as before (pages written their own file)
        assert file.read() == json.dumps(data, indent=1, ensure_ascii=False)


def test_page_settings_debounce_quit_and_weak_page(ui_env):
    from neopedal.ui.quick import page_settings

    class Page(QObject):
        def __init__(self):
            super().__init__()
            self.value = 0
            self.file = page_settings.PageSettings("test_debounce.json", 50, self, self.collect)

        def collect(self) -> dict:
            return {"value": self.value}

    page = Page()
    for value in range(1, 6):
        page.value = value
        page.file.save()
    assert page_settings.load_settings("test_debounce.json") == {"value": 5}  # read flushes first
    page.value = 6
    page.file.save()
    page_settings.flush_all()  # app quitting
    assert page_settings.load_settings("test_debounce.json") == {"value": 6} and not page.file.pending
    page.value = 7
    page.file.save()
    assert wait_until(lambda file=page.file: not file.pending)  # written once changes paused
    assert page_settings.load_settings("test_debounce.json") == {"value": 7}
    page.file.save({"value": 70})  # settings as given (page state changed later not written)
    page.value = 71
    page.file.flush()
    assert page_settings.load_settings("test_debounce.json") == {"value": 70}
    page.value = 7
    page.file.save_now()
    # Page never kept alive by its settings, deleted page skipped at quit
    page.value = 8
    page.file.save()
    ref = weakref.ref(page)
    page.deleteLater()
    del page
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert ref() is None
    page_settings.flush_all()
    assert page_settings.load_settings("test_debounce.json") == {"value": 7}


def test_results_folder_written_at_once(ui_env, monkeypatch, tmp_path):
    from neopedal.process import results_file
    from neopedal.ui.quick import results_backend

    backend = results_backend.RaceResultsBackend()
    try:
        monkeypatch.setattr(results_backend.QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
        backend.chooseFolder()
        assert not backend.page_file.pending  # read by other pages from the file: written at once
        assert results_file.chosen_results_folder(cfg.path.config) == str(tmp_path)
        backend.setTab(1)
        assert backend.page_file.pending
    finally:
        backend.release()
        backend.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert results_backend.load_page_settings()["tab"] == 1


# --- 3. Director keep-alive connection closed when dropped
class FakeConnection:
    def __init__(self):
        self.closed = 0
        self.failed = False

    def close(self):
        self.closed += 1


def test_director_connection_dropped_while_used_closed_after(director_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import director_game as dgame

    backend = director_page.backend
    used = FakeConnection()
    backend.game._connection = used

    def ask_state(connection, **kwargs):
        backend.game.drop_connection()  # page closing / game host changed while the state thread asks the game
        assert used.closed == 0  # in use: left to the state thread
        return {}

    monkeypatch.setattr(dgame, "ask_state", ask_state)
    assert backend.game.poll_game() == {}
    assert used.closed == 1 and backend.game._connection is None
    # Not in use: closed at once
    idle = FakeConnection()
    backend.game._connection = idle
    backend.game.setGameHost("192.168.1.30")
    assert idle.closed == 1 and backend.game._connection is None
    # Failed one replaced by the state thread: closed
    failed = FakeConnection()
    failed.failed = True
    backend.game._connection = failed
    monkeypatch.setattr(dgame, "ask_state", lambda connection, **kwargs: {})
    made = []
    monkeypatch.setattr(dgame.game_rest, "GameConnection", lambda **kwargs: made.append(FakeConnection()) or made[-1])
    backend.game.poll_game()
    assert failed.closed == 1 and backend.game._connection is made[0] and made[0].closed == 0
    backend.release()
    assert made[0].closed == 1


# --- 4. Lap viewer fallback thread: last job freed while waiting
def test_fallback_thread_frees_last_job():
    from neopedal.ui.quick import lap_backend

    class Data:
        pass

    data = Data()
    data_ref = weakref.ref(data)
    handle = lap_backend.start_fallback_job("test job", lambda arg: Data(), data)
    del data
    result = handle.future.result(timeout=5)
    result_ref = weakref.ref(result)
    del handle, result
    assert wait_until(lambda: gc.collect() is not None and data_ref() is None and result_ref() is None)


# --- 5. Track map zoomed while loading
def test_track_map_zoomed_while_loading(viewer):  # noqa: F811
    from neopedal.ui.quick.lines import VertexStore, band

    backend = viewer.backend
    assert backend.load_map(cfg.path.track_map, "Ring")
    backend.setScale(20.0)  # zoom settled while map read
    wait_jobs(backend)
    process_events(0.05)
    wait_jobs(backend)
    road = VertexStore.get(backend.view["road"])
    xs = [x for x, _ in backend.raw_coords]
    ys = [y for _, y in backend.raw_coords]
    expected = band(xs, ys, backend.width(float(backend.ecfg["map_width"]), 5.0), closed=True)
    assert list(road.data) == pytest.approx(list(expected.data))


# --- 6. Camera table & game click shared
def test_camera_table_and_game_click_shared(monkeypatch):
    from neopedal.ui.quick import director_backend, game_camera, game_window, replays_backend

    assert replays_backend.CAMERAS is game_camera.CAMERAS and replays_backend.camera_group is game_camera.camera_group
    assert director_backend.gc is game_camera
    clicks: list = []
    monkeypatch.setattr(game_window, "find_game_window", lambda: (42, 1920, 1080))
    monkeypatch.setattr(game_window, "middle_click", lambda found: clicks.append(found) or True)
    assert game_camera.click_game_ui()
    assert wait_until(lambda: clicks == [(42, 1920, 1080)])
    assert not game_camera.click_game_ui(local=False)  # game on another computer: no window of this one
    monkeypatch.setattr(game_window, "find_game_window", lambda: (0, 0, 0))
    assert not game_camera.click_game_ui()
    assert len(clicks) == 1
