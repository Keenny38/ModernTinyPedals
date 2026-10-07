"""Replay files loaded in background: event loop keeps running, stale loads dropped, cancel on close"""

import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from tests.test_lap_viewer_features import laps, viewer  # noqa: F401
from tinypedal import replay as replay_module
from tinypedal.replay import SCAN_CHECK_STEP, ReplayControl, ReplayLoadCancelled, ReplayWriter

FRAME_SIZE = 256  # small frames: API restart not tested here, layout checked with API layout below


def write_long_replay(path, frames: int, name: str = "long.tpreplay") -> str:
    """Replay of many frames to index"""
    filename = str(path / name)
    frame = bytes(FRAME_SIZE)
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, FRAME_SIZE, 30)
        for index in range(frames):
            writer.write(index / 30, frame)
        writer.finish()
    return filename


def wait_loaded(dialog, timeout: float = 10.0):
    assert dialog.loader.wait(timeout)
    QCoreApplication.processEvents()  # finished signal from loading thread


@pytest.fixture
def replay_view(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.replay import replay
    from tinypedal.ui import replay_view as module

    monkeypatch.setattr(module, "restart_api", lambda: None)
    monkeypatch.setattr(type(api), "name", property(lambda self: module.API_LMU_NAME))
    monkeypatch.setattr(type(api), "replay_layout", lambda self: [["shmm", FRAME_SIZE]])
    dialog = module.ReplayView(None)
    yield dialog
    replay.unload()
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def spy_open(monkeypatch) -> list:
    """Files opened by replay module"""
    opened = []

    def spy(*args, **kwargs):
        file = open(*args, **kwargs)  # noqa: SIM115
        opened.append(file)
        return file

    monkeypatch.setattr(replay_module, "open", spy, raising=False)
    return opened


def test_scan_cancelled_closes_file(tmp_path, monkeypatch):
    filename = write_long_replay(tmp_path, SCAN_CHECK_STEP * 2)
    opened = spy_open(monkeypatch)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ReplayLoadCancelled):
        ReplayControl.prepare(filename, cancel=cancel)
    assert opened and all(file.closed for file in opened)
    progress = []
    replay_file = ReplayControl.prepare(filename, progress=lambda done, total: progress.append((done, total)))
    assert len(replay_file) == SCAN_CHECK_STEP * 2 and progress and progress[0][0] < progress[0][1]
    replay_file.close()


def test_long_replay_loads_without_blocking_event_loop(replay_view, tmp_path):
    from tinypedal.replay import replay

    filename = write_long_replay(tmp_path, SCAN_CHECK_STEP * 20)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(replay_view.loader.busy))
    timer.start(1)
    replay_view.open_file(filename)
    assert not replay.active and replay_view.loader.busy  # returned at once, file scanned in background
    replay_view.refresh()
    assert replay_view.label_file.text().startswith("Loading replay long.tpreplay:")
    assert not replay_view.button_record.isEnabled()
    deadline = time.monotonic() + 20
    while replay_view.loader.busy and time.monotonic() < deadline:
        QCoreApplication.processEvents()
    timer.stop()
    assert replay.active and len(replay.player.replay) == SCAN_CHECK_STEP * 20
    assert True in ticks  # event loop kept running while loading
    replay_view.refresh()
    assert replay_view.label_file.text() == "long.tpreplay" and replay_view.button_play.isEnabled()


def test_stale_load_ignored(replay_view, tmp_path, monkeypatch):
    from tinypedal.replay import replay

    first = write_long_replay(tmp_path, 10, "first.tpreplay")
    second = write_long_replay(tmp_path, 20, "second.tpreplay")
    gate = threading.Event()
    prepared = []
    prepare = ReplayControl.prepare

    def slow_prepare(filename, *args):
        if filename == first:
            assert gate.wait(10)  # first file still loading when second one is opened
        replay_file = prepare(filename, *args)
        prepared.append(replay_file)
        return replay_file

    monkeypatch.setattr(replay, "prepare", slow_prepare)
    called = []
    replay_view.open_file(first, lambda: called.append(first))
    replay_view.open_file(second, lambda: called.append(second))
    gate.set()
    wait_loaded(replay_view)
    QCoreApplication.processEvents()
    assert replay.player.replay.filename == second and called == [second]
    stale = next(replay_file for replay_file in prepared if replay_file.filename == first)
    assert stale._file.closed  # result of replaced loading dropped, file closed
    # Stale result already queued when another loading started: dropped too
    late = prepare(first)
    replay_view.loader._done.emit(0, late, None)
    assert late._file.closed and replay.player.replay.filename == second


def test_load_error_reported(replay_view, tmp_path, monkeypatch):
    from tinypedal.replay import replay
    from tinypedal.ui import replay_view as module

    bad = tmp_path / "bad.tpreplay"
    bad.write_bytes(b"not a replay")
    warnings = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda parent, title, text: warnings.append(text))
    called = []
    replay_view.open_file(str(bad), lambda: called.append(True))
    wait_loaded(replay_view)
    assert warnings and warnings[0].startswith("Unable to open replay file:")
    assert not replay.active and not called and not replay_view.loader.busy
    monkeypatch.setattr(type(module.api), "replay_layout", lambda self: [["shmm", FRAME_SIZE + 1]])
    replay_view.open_file(write_long_replay(tmp_path, 5))
    wait_loaded(replay_view)
    assert "another game data structure" in warnings[1] and not replay.active


def test_close_during_load_stops_thread(replay_view, tmp_path, monkeypatch):
    from tinypedal.replay import replay

    filename = write_long_replay(tmp_path, SCAN_CHECK_STEP * 4)
    opened = spy_open(monkeypatch)
    scanning = threading.Event()
    prepare = ReplayControl.prepare

    def paused_prepare(filename, api_name, layout, cancel, progress):
        def pause(done, total):
            scanning.set()
            cancel.wait(10)  # scanning paused until loading cancelled

        return prepare(filename, api_name, layout, cancel, pause)

    monkeypatch.setattr(replay, "prepare", paused_prepare)
    replay_view.open_file(filename)
    assert scanning.wait(10)
    replay_view.close()  # cancels loading, waits for thread
    assert not replay_view.loader._threads and not replay_view.loader.busy
    QCoreApplication.processEvents()
    assert not replay.active
    assert opened and all(file.closed for file in opened)


def test_lap_viewer_open_replay_seeks_after_load(viewer, tmp_path, monkeypatch):  # noqa: F811
    from tinypedal.api_control import api
    from tinypedal.replay import replay
    from tinypedal.ui import replay_view as module
    from tinypedal.ui._common import BaseDialog

    filename = write_long_replay(tmp_path, SCAN_CHECK_STEP * 3)
    monkeypatch.setattr(module, "restart_api", lambda: None)
    monkeypatch.setattr(type(api), "name", property(lambda self: module.API_LMU_NAME))
    monkeypatch.setattr(type(api), "replay_layout", lambda self: [["shmm", FRAME_SIZE]])
    backend = viewer.backend
    monkeypatch.setattr(backend, "replay_target", lambda lap, x: (filename, 42.0))
    view = None
    try:
        backend.openReplay(0.0, "")
        view = next(widget for widget in viewer.findChildren(BaseDialog) if type(widget).__name__ == "ReplayView")
        assert not replay.active and backend.status == "Loading replay…"
        wait_loaded(view)
        player = replay.player
        assert player is not None and player.replay.filename == filename
        assert player.paused and player.position == pytest.approx(42.0, abs=0.05)
        assert "Replay: long.tpreplay" in backend.status
        player.seek(0.0)
        backend.openReplay(0.0, "")  # same replay already played: position shown at once
        assert replay.player is player and player.position == pytest.approx(42.0, abs=0.05)
    finally:
        replay.unload()
        if view is not None:
            view.close()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
