"""Results & replays page and lap viewer fixes: unreadable results file shown as such (row kept), clear filters
buttons, replay of a lap looked for in background, replays moved to the recycle bin in background (progress, stop),
"/" & Delete keys, lap deletions undone one after another & recently deleted laps restored"""

import os
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, Qt, qInstallMessageHandler
from PySide6.QtTest import QTest

from tests.test_game_info import GAME_ANSWERS, answered, replays_page, wait_requests  # noqa: F401
from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_e2 import START, TRACK, lap_path, write_lap
from tests.test_race_results import PRACTICE_NAME, RACE_NAME, english, results_folder, wait_until  # noqa: F401


def settle(seconds: float = 0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def everything(root) -> list:
    found, stack = [], [root]
    while stack:
        item = stack.pop()
        found.append(item)
        stack.extend(item.childItems())
    return found


def named(root, name: str):
    return next(item for item in everything(root) if item.objectName() == name)


def state_action(root, state: str):
    """Action button of a TpStateView (empty state) found by its objectName"""
    return named(named(root, state), "emptyStateAction")


@pytest.fixture
def qml_messages():
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    yield messages
    qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


# --- 1. & 4. Results page: unreadable file keeps its row with an error, clear filters
@pytest.fixture
def results_page(results_folder, english, monkeypatch, qml_messages):  # noqa: F811
    from neopedal.ui import race_results_viewer
    from neopedal.ui.quick import results_backend

    read = results_backend.read_session

    def reading(path, stamp, names):
        if path.endswith(PRACTICE_NAME):
            raise ValueError("not a results file")
        return read(path, stamp, names)

    monkeypatch.setattr(results_backend, "read_session", reading)
    viewer = race_results_viewer.RaceResultsViewer(None)
    viewer.resize(1300, 800)
    viewer.show()
    assert wait_until(lambda: viewer.backend.loaded_once and viewer.backend.hasSession)
    yield viewer
    viewer.close()
    viewer.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_unreadable_results_file_keeps_row_and_shows_error(results_page):
    backend = results_page.backend
    root = results_page.view.rootObject()
    practice = next(row["key"] for row in backend.sessionModel.rows if row["key"].endswith(PRACTICE_NAME))
    backend.kept.clear()  # full results read with the list: read again when picked
    backend.select(practice)
    assert wait_until(lambda: backend.failedFile != "")
    assert backend.selectedKey == practice and backend.failedFile == PRACTICE_NAME and not backend.hasSession
    settle(0.1)
    state = named(root, "sessionState")
    assert state.property("visible") and state.property("text").startswith(PRACTICE_NAME + "\n")
    assert not state_action(root, "sessionState").property("visible")
    # Another session picked: shown, error gone
    race = next(row["key"] for row in backend.sessionModel.rows if row["key"].endswith(RACE_NAME))
    backend.select(race)
    assert wait_until(lambda: backend.hasSession)
    assert backend.failedFile == "" and backend.selectedKey == race
    # Picked again: read again (still unreadable), filters hiding it pick another session
    backend.kept.clear()
    backend.select(practice)
    assert wait_until(lambda: backend.failedFile != "")
    backend.setKindFilter(3)  # races
    assert wait_until(lambda: backend.hasSession) and backend.failedFile == ""


def test_results_clear_filters(results_page):
    backend = results_page.backend
    root = results_page.view.rootObject()
    search = next(item for item in everything(root)
                  if str(item.property("placeholderText") or "").startswith("Search: track"))
    search.setProperty("text", "nothing like this")
    backend.setSearch("nothing like this")
    backend.setKindFilter(3)
    assert backend.shownCount == 0
    backend.reload()  # files read again: no session left to show
    assert wait_until(lambda: not backend.busy and not backend.hasSession)
    settle(0.1)
    button = state_action(root, "sessionState")
    assert button.property("visible") and button.property("text") == "Clear Filters"
    QMetaObject.invokeMethod(button, "clicked")
    assert wait_until(lambda: backend.hasSession)
    assert (backend.kindFilter, backend.searchText, backend.hideEmpty) == (0, "", False)
    assert backend.shownCount == backend.sessionCount == 3 and search.property("text") == ""
    assert not button.property("visible")
    backend.clearFilters()  # nothing to clear: nothing changes
    assert backend.shownCount == 3


def test_results_slash_focuses_search(results_page):
    root = results_page.view.rootObject()
    search = next(item for item in everything(root)
                  if str(item.property("placeholderText") or "").startswith("Search: track"))
    results_page.activateWindow()
    results_page.view.setFocus()
    settle(0.1)
    QTest.keyClick(results_page.view, Qt.Key.Key_Slash)
    settle(0.1)
    assert search.property("activeFocus") and search.property("text") == ""


# --- 3. & 4. Replays: recycle bin moves in background, progress & stop, clear filters
def test_trash_replays_progress_and_stop(tmp_path, monkeypatch):
    from neopedal.ui.quick import replay_files

    paths = []
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.Vcr"
        path.write_bytes(b"x")
        paths.append(str(path))
    monkeypatch.setattr(replay_files, "QFile", SimpleNamespace(
        moveToTrash=lambda path: not path.endswith("b.Vcr") and os.remove(path) is None))
    progress: list[float] = []
    result = replay_files.trash_replays(paths, progress.append)
    assert result.moved == [paths[0], paths[2]] and result.errors == ["b.Vcr"] and not result.cancelled
    assert progress == pytest.approx([1 / 3, 2 / 3, 1.0])
    cancelled = threading.Event()
    result = replay_files.trash_replays([paths[1], paths[1]], lambda _: cancelled.set(), cancelled)
    assert result.cancelled and result.errors == ["b.Vcr"]  # second file never tried


@pytest.fixture
def replay_files_page(replays_page, tmp_path):  # noqa: F811
    folder = tmp_path / "Replays"
    folder.mkdir()
    for name in ("Algarve P1 1", "Bahrain R1"):
        (folder / f"{name}.Vcr").write_bytes(b"replay")
    answers = dict(GAME_ANSWERS, **{"/rest/watch/replay/getReplayFolder": {"custom": "", "default": str(folder)}})
    backend = answered(replays_page, answers)
    assert backend.replayFolder == str(folder) and backend.replayCount == 2
    return replays_page, folder


def test_replays_trashed_in_background(replay_files_page, monkeypatch):
    from neopedal.ui.quick import replay_files

    page, folder = replay_files_page
    backend = page.backend
    gate = threading.Event()
    threads: list[threading.Thread] = []

    def move(path):
        threads.append(threading.current_thread())
        assert gate.wait(5)
        os.remove(path)
        return True

    monkeypatch.setattr(replay_files, "QFile", SimpleNamespace(moveToTrash=move))
    backend.selectAllReplays()
    backend.deleteReplays("Bahrain R1")
    assert backend.trashing and backend.replayCount == 2  # page never waits for the files
    settle(0.05)
    bar = named(page.view.rootObject(), "trashProgress")
    assert bar.property("visible")
    backend.deleteReplays("Bahrain R1")  # one deletion at a time
    assert backend.noticeError and "still being moved" in backend.noticeText
    gate.set()
    wait_requests(backend.request_trash)
    assert threads and threading.main_thread() not in threads
    assert not backend.trashing and backend.trashProgress == 0.0 and list(folder.iterdir()) == []
    assert backend.replayCount == 0 and backend.noticeText == "2 replay(s) moved to the recycle bin"
    settle(0.05)
    assert not bar.property("visible")
    wait_requests(backend.request_replays)


def test_replays_trash_stopped(replay_files_page, monkeypatch):
    from neopedal.ui.quick import replay_files

    page, folder = replay_files_page
    backend = page.backend

    def move(path):
        backend.trash_cancel.set()  # stopped while the first file moves
        os.remove(path)
        return True

    monkeypatch.setattr(replay_files, "QFile", SimpleNamespace(moveToTrash=move))
    backend.selectAllReplays()
    backend.deleteReplays("Bahrain R1")
    wait_requests(backend.request_trash)
    assert len(list(folder.iterdir())) == 1 and backend.replayCount == 1
    assert backend.noticeError and backend.noticeText == "Deletion stopped, 1 file(s) moved to the recycle bin"
    wait_requests(backend.request_replays)


def test_replays_clear_filters(replay_files_page):
    page, _ = replay_files_page
    backend = page.backend
    page.resize(1300, 800)
    page.show()  # list count told once laid out
    root = page.view.rootObject()
    search = next(item for item in everything(root)
                  if str(item.property("placeholderText") or "").startswith("Search replays"))
    search.setProperty("text", "monza")
    backend.setSearch("monza")
    backend.setSessionFilter(3)
    assert backend.shownCount == 0
    settle(0.1)
    button = state_action(root, "replayListState")
    assert button.property("visible")
    QMetaObject.invokeMethod(button, "clicked")
    settle(0.1)
    assert backend.shownCount == 2 and backend.sessionFilter == 0 and search.property("text") == ""
    assert not button.property("visible")


# --- 2., 5. & 6. Lap viewer: replay lookup in background, undo stack, recently deleted laps, keys
@pytest.fixture
def lap_page(ui_env, monkeypatch):
    """Page with 3 laps of TRACK: lap 1 (90 s), lap 2 (91 s), lap 3 newest (92.5 s)"""
    from PySide6.QtWidgets import QMessageBox, QWidget

    from neopedal.setting import cfg
    from neopedal.ui.quick.lap_backend import LapViewerBackend

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    folder = cfg.path.telemetry.rstrip("/")
    for number, lap_time in ((1, 90.0), (2, 91.0), (3, 92.5)):
        write_lap(folder, number, lap_time, timestamp=START + number * 100)
    parent = QWidget()
    page = LapViewerBackend(parent, cfg.path.telemetry)
    page.refresh()
    wait_loaded(page)
    yield page
    page.release()
    parent.deleteLater()


def test_replay_looked_for_in_background(lap_page, monkeypatch):
    from neopedal.ui.quick import lap_xy

    lap_page.checked = {lap_path(lap_page, 1)}
    lap_page.reference_key = lap_path(lap_page, 1)
    lap_page.load_laps()
    wait_loaded(lap_page)
    threads: list[threading.Thread] = []
    gate = threading.Event()

    def find(folder, moment, replayed):
        threads.append(threading.current_thread())
        assert gate.wait(5)
        return None

    monkeypatch.setattr(lap_xy, "find_replay", find)
    lap_page.openReplay(0.0, "")
    assert lap_page.status == "Looking for the replay of this lap…"  # page never waits for replay files
    lap_page.openReplay(0.0, "")  # lookup running: not asked twice
    gate.set()
    lap_page.wait_jobs()
    assert len(threads) == 1 and threads[0] is not threading.main_thread()
    assert lap_page.status == "No replay recorded with this lap." and not lap_page._replay_lookup


def test_find_replay_reads_files_in_folder(tmp_path, monkeypatch):
    from neopedal import replay
    from neopedal.replay import ReplayInfo
    from neopedal.ui.quick import lap_backend

    folder = str(tmp_path)
    monkeypatch.setattr(replay, "list_replays", lambda path: [
        ReplayInfo(os.path.join(path, "new.tpreplay"), 5000.0, 0, 100.0, "LMU", {}),
        ReplayInfo(os.path.join(path, "race.tpreplay"), 1000.0, 0, 1000.0, "LMU", {}),
    ] if path == folder else [])
    assert lap_backend.find_replay(folder, 1200.0, "") == (os.path.join(folder, "race.tpreplay"), 200.0)
    assert lap_backend.find_replay(folder, 9000.0, "") is None


def test_undo_stack(lap_page, monkeypatch):
    from neopedal.ui.quick import lap_actions

    first, second, third = (lap_path(lap_page, number) for number in (1, 2, 3))
    monkeypatch.setattr(lap_actions, "UNDO_DEPTH", 2)
    for path in (first, second, third):
        lap_page.deleteLap(path)
        wait_loaded(lap_page)
    assert len(lap_page._undo) == 2 and lap_page.undoText.endswith("(1)")  # oldest deletion left in trash only
    lap_page.undoDelete()
    wait_loaded(lap_page)
    assert os.path.exists(third) and not os.path.exists(second)
    lap_page.undoDelete()  # deletion before it
    wait_loaded(lap_page)
    assert os.path.exists(second) and not os.path.exists(first) and lap_page.undoText == ""
    lap_page.undoDelete()  # nothing left on stack
    assert not os.path.exists(first)


def test_recently_deleted_laps(lap_page):
    from neopedal.ui.quick import lap_backend

    first, second = lap_path(lap_page, 1), lap_path(lap_page, 2)
    lap_page.keepLap(first, True)
    lap_page.deleteLaps([first, second])
    wait_loaded(lap_page)
    # Deletion older than trash days (removed by purge_trash): never listed
    old = os.path.join(lap_page.folder, lap_backend.TRASH_FOLDER, "2000-01-01 10-00-00", TRACK)
    os.makedirs(old)
    with open(os.path.join(old, "old.csv"), "w", encoding="utf-8") as file:
        file.write("x")
    lap_page.openTrash()
    assert lap_page.trashLoading
    lap_page.wait_jobs()
    rows = lap_page.trashRows
    assert not lap_page.trashLoading and [row["title"] for row in rows] == ["Lap 2", "Lap 1"]
    assert rows[0]["track"] == TRACK and rows[0]["time"] == "1:31.000" and rows[0]["deleted"]
    lap_page.restoreTrashed(os.path.join(lap_page.folder, "elsewhere", TRACK, "x.csv"))  # not in trash: ignored
    lap_page.restoreTrashed(rows[1]["key"])
    lap_page.wait_jobs()
    wait_loaded(lap_page)
    assert os.path.exists(first) and lap_page.lapActions(first)["kept"]  # kept mark of this session restored
    assert [row["title"] for row in lap_page.trashRows] == ["Lap 2"]
    assert lap_page.undoText.endswith("(1)")  # lap left the deletion it belonged to
    lap_page.undoDelete()
    lap_page.wait_jobs()
    wait_loaded(lap_page)
    assert os.path.exists(second) and lap_page.trashRows == [] and lap_page.undoText == ""


def test_lap_list_keys_and_recently_deleted_dialog(lap_page, qml_messages):
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick import create_quick_view

    first, second = lap_path(lap_page, 1), lap_path(lap_page, 2)
    lap_page.checked = {first, second}
    lap_page.reference_key = first
    lap_page.load_laps()
    wait_loaded(lap_page)
    parent = QWidget()
    try:
        view = create_quick_view(parent, "LapViewer.qml", {"backend": lap_page})
        parent.resize(1300, 800)
        view.resize(1300, 800)
        parent.show()
        parent.activateWindow()
        settle()
        root = view.rootObject()
        search = next(item for item in everything(root)
                      if str(item.property("placeholderText") or "").startswith("Search laps"))
        view.setFocus()
        settle(0.1)
        QTest.keyClick(view, Qt.Key.Key_Slash)
        settle(0.1)
        assert search.property("activeFocus") and search.property("text") == ""
        QTest.keyClick(view, Qt.Key.Key_Delete)  # search field keeps Delete
        settle(0.1)
        assert os.path.exists(first) and os.path.exists(second)
        QTest.keyClick(view, Qt.Key.Key_Escape)  # keys back to charts
        settle(0.1)
        QTest.keyClick(view, Qt.Key.Key_Delete)  # checked laps moved to trash
        wait_loaded(lap_page)
        assert not os.path.exists(first) and not os.path.exists(second)
        dialog = root.findChild(QObject, "recentlyDeleted")
        QMetaObject.invokeMethod(dialog, "open")
        lap_page.wait_jobs()
        settle(0.4)
        assert dialog.property("visible") and len(lap_page.trashRows) == 2
        listing = next(item for item in everything(dialog.property("contentItem")) if item.objectName() == "trashList")
        assert listing.property("count") == 2
    finally:
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
