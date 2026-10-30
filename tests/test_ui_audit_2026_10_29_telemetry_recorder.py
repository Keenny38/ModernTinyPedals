"""UI/UX audit 2026-10-29, session recorder (section 5): Qt Quick page on the lap viewer's playback bar (one
transport look), one Open action, every feature of the former widget page kept, state told to QML only on change"""

import time

import pytest
from PySide6.QtCore import Q_ARG, QCoreApplication, QEvent, QMetaObject, QObject, Qt, qInstallMessageHandler
from PySide6.QtGui import QKeyEvent

from neopedal.replay import ReplayWriter
from tests.test_replay_load import FRAME_SIZE, wait_loaded, write_long_replay


def write_marked_replay(path, name: str = "marked.tpreplay") -> str:
    """Replay of 10 s (100 frames) with a lap at 2 s and an incident at 6 s"""
    filename = str(path / name)
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, FRAME_SIZE, 10, {"info": {"track": "Spa", "vehicle": "Car", "session": "Race"}})
        frame = bytes(FRAME_SIZE)
        for index in range(100):
            writer.write(index * 0.1, frame)
        writer.write_marker(2.0, "lap", "3")
        writer.write_marker(6.0, "incident", "9g")
        writer.finish()
    return filename


@pytest.fixture
def recorder(ui_env, monkeypatch):
    """Session recorder page (QML), LMU API with small frames, API restart left out"""
    from neopedal.api_control import api
    from neopedal.replay import replay
    from neopedal.ui import replay_view
    from neopedal.ui.quick import session_recorder_backend as module

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    monkeypatch.setattr(module, "restart_api", lambda: None)
    monkeypatch.setattr(type(api), "name", property(lambda self: module.API_LMU_NAME))
    monkeypatch.setattr(type(api), "replay_layout", lambda self: [["shmm", FRAME_SIZE]])
    dialog = replay_view.ReplayView(None)
    dialog.qml_messages = messages
    try:
        yield dialog
    finally:
        qInstallMessageHandler(previous)
        replay.unload()
        dialog.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_list(backend, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while (backend.listing or backend.jobs.running) and time.monotonic() < deadline:
        QCoreApplication.processEvents()
    QCoreApplication.processEvents()


def find(dialog, name: str):
    item = dialog.view.rootObject().findChild(QObject, name)
    assert item is not None, name
    return item


def press(dialog, key, modifiers=Qt.KeyboardModifier.NoModifier):
    dialog.view.rootObject().forceActiveFocus()
    QCoreApplication.sendEvent(dialog.view.quickWindow(), QKeyEvent(QEvent.Type.KeyPress, key, modifiers))


def emit(item, signal: str, *args):
    """QML signal of item emitted (as the bar's buttons do)"""
    assert QMetaObject.invokeMethod(item, signal, Qt.ConnectionType.DirectConnection,
                                    *[Q_ARG(type(arg), arg) for arg in args])


def plain(value):
    """QML list value as a Python list"""
    return list(value.toVariant() if hasattr(value, "toVariant") else value)


def test_page_loads_without_qml_warnings(recorder, tmp_path):
    from neopedal.replay import replay

    root = recorder.view.rootObject()
    assert root is not None and root.objectName() == "sessionRecorder"
    backend = recorder.backend
    write_marked_replay(tmp_path)
    recorder.backend.open_file(write_marked_replay(tmp_path))  # every part shown: replay played, marks, section
    wait_loaded(recorder)
    backend.setSection(0)
    replay.player.seek(5.0)
    backend.setSection(1)
    backend.refreshList()
    wait_list(backend)
    QCoreApplication.processEvents()
    assert recorder.page_minimum_size().width() > 0
    # theme_copy.qml: app theme object (icon font read from the app window module), not this page
    page_messages = [text for text in recorder.qml_messages if ".qml" in text and "theme_copy.qml" not in text]
    assert not page_messages, page_messages


def test_one_open_action_and_list_play(recorder, tmp_path, monkeypatch):
    """Open Replay... is the page's one Open action (file dialog); rows of the list play with their Play
    button, double-click or Enter (no second "Open" button)"""
    from neopedal.replay import replay
    from neopedal.ui.quick import session_recorder_backend as module

    filename = write_marked_replay(tmp_path)
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (filename, ""))
    opens = [item for item in recorder.view.rootObject().findChildren(QObject)
             if item.property("text") in ("Open", "Open Replay…")
             and item.metaObject().indexOfSignal("clicked()") >= 0]  # buttons (not their label)
    assert [item.objectName() for item in opens] == ["openButton"]
    emit(find(recorder, "openButton"), "clicked")
    wait_loaded(recorder)
    assert replay.active and recorder.backend.fileName == "marked.tpreplay"
    recorder.backend.backToGame()
    # Replays of telemetry folder (headers read in background): row opened by its file
    monkeypatch.setattr(module.cfg.path, "telemetry", str(tmp_path))
    recorder.backend.refreshList()
    wait_list(recorder.backend)
    rows = recorder.backend.replays
    assert [(row["track"], row["vehicle"], row["session"], row["duration"]) for row in rows] == [
        ("Spa", "Car", "Race", "0:09")]
    recorder.backend.openFile(rows[0]["file"])
    assert recorder.backend.loadingFile == rows[0]["file"]
    wait_loaded(recorder)
    assert replay.active and recorder.backend.filePath == rows[0]["file"]


def test_transport_runs_replay(recorder, tmp_path):
    """Playback bar of the page drives the replay player: play / pause, 5 s skip, frame steps, speed, loop, seek"""
    from neopedal.replay import replay

    backend = recorder.backend
    bar = find(recorder, "recorderPlayback")
    assert not backend.active and not bar.property("canPlay")
    backend.open_file(write_marked_replay(tmp_path))
    wait_loaded(recorder)
    player = replay.player
    assert bar.property("canPlay") and bar.property("frameButtons")
    assert plain(bar.property("laps")) == [2.0] and plain(bar.property("incidents")) == [6.0]
    emit(bar, "playToggled")
    assert player.paused and backend.paused and not bar.property("playing")
    emit(bar, "seeked", 1.0)
    assert player.position == pytest.approx(1.0)
    emit(bar, "skipped", 5.0)
    assert player.position == pytest.approx(6.0)
    emit(bar, "frameStepped", -1)
    assert player.position == pytest.approx(5.9)
    emit(bar, "speedPicked", 2.0)
    assert player.speed == 2.0 and bar.property("speed") == 2.0
    emit(bar, "loopToggled")
    assert not player.loop and not bar.property("loop")
    assert bar.property("positionText") == backend.positionText == "0:05 / 0:09"
    # Speed & loop kept for the next replay opened
    backend.open_file(write_long_replay(tmp_path, 5))
    wait_loaded(recorder)
    assert replay.player.speed == 2.0 and not replay.player.loop


def test_keys_of_page(recorder, tmp_path):
    """Space play / pause, arrows 5 s, Shift + arrows one frame, , . speed, L loop (as the lap viewer)"""
    from neopedal.replay import replay

    recorder.backend.open_file(write_marked_replay(tmp_path))
    wait_loaded(recorder)
    player = replay.player
    press(recorder, Qt.Key.Key_Space)
    assert player.paused
    player.seek(2.0)
    press(recorder, Qt.Key.Key_Right)
    assert player.position == pytest.approx(7.0)
    press(recorder, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    assert player.position == pytest.approx(6.9)
    press(recorder, Qt.Key.Key_Period)
    assert player.speed == 2.0
    press(recorder, Qt.Key.Key_L)
    assert not player.loop


def test_feature_parity(recorder, tmp_path, monkeypatch):
    """Laps & incidents, section saved to a new file (other name than the open replay), recording state & error,
    API without replay told on the page"""
    from neopedal.api_control import api
    from neopedal.replay import replay
    from neopedal.ui.quick import session_recorder_backend as module

    backend = recorder.backend
    filename = write_marked_replay(tmp_path)
    backend.open_file(filename)
    wait_loaded(recorder)
    assert [item["text"] for item in backend.lapItems] == ["Lap 3 (0:02)"]
    replay.player.set_paused(True)
    backend.gotoLap(0)
    assert replay.player.position == pytest.approx(2.0)
    backend.gotoIncident(1)
    assert replay.player.position == pytest.approx(3.0)  # 3 s before incident
    backend.gotoIncident(-1)
    assert replay.player.position == pytest.approx(3.0)  # only incident: same one
    backend.setSection(1)
    replay.player.seek(1.0)
    backend.setSection(0)
    assert (backend.sectionStart, backend.sectionEnd) == (pytest.approx(1.0), pytest.approx(3.0))
    assert backend.canSave
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName", lambda *args: (filename, ""))
    backend.saveSection()
    assert "another file name" in backend.last_message and not recorder.export.busy
    target = str(tmp_path / "part.tpreplay")
    monkeypatch.setattr(module.QFileDialog, "getSaveFileName", lambda *args: (target, ""))
    backend.saveSection()
    assert recorder.export.wait(10)
    QCoreApplication.processEvents()
    assert backend.sectionText.endswith("frames: part.tpreplay") and backend.canSave
    backend.backToGame()
    assert not backend.active and backend.laps == [] and backend.sectionStart == -1
    # Recording stopped by itself: reason shown as an error
    monkeypatch.setattr(replay, "recording_error", "No space left on device")
    backend.refresh()
    assert backend.recordError and backend.recordText == "Recording stopped: No space left on device"
    # API without shared memory replay: notice, record & open refused with the reason
    monkeypatch.setattr(type(api), "name", property(lambda self: "Other"))
    backend.refresh()
    assert not backend.apiSupported and not backend.canRecord and find(recorder, "apiNotice").property("visible")
    backend.toggleRecording()
    assert not replay.recording and backend.last_message == backend.apiHint


def test_state_emitted_only_on_change(recorder, tmp_path):
    """Paused replay read again: no part told to QML again (polling never rebuilds bindings for nothing)"""
    from neopedal.replay import replay

    backend = recorder.backend
    backend.open_file(write_marked_replay(tmp_path))
    wait_loaded(recorder)
    replay.player.set_paused(True)
    backend.refresh()
    counts = {name: 0 for name in ("recordChanged", "loadChanged", "playerChanged", "markersChanged",
                                   "positionChanged", "sectionChanged")}
    for name in counts:
        getattr(backend, name).connect(lambda name=name: counts.__setitem__(name, counts[name] + 1))
    for _ in range(3):
        backend.refresh()
    assert counts == dict.fromkeys(counts, 0)
    backend.step(1)
    assert counts["positionChanged"] == 1 and counts["markersChanged"] == 0


def test_page_timer_only_while_shown(recorder):
    """Position read a few times a second only while the page is shown"""
    backend = recorder.backend
    backend.page_shown()
    assert backend._timer.isActive()
    backend.page_hidden()
    assert not backend._timer.isActive()
