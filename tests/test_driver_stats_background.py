"""Driver stats page work off the UI thread: big session history read & edits saved on a worker thread (in
order), history parsed incrementally (lines appended only), logos looked for once, column texts measured once"""

import os
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFontMetricsF

from tests.test_driver_stats_viewer import (  # noqa: F401  (fixtures)
    HISTORY,
    OREGA,
    SPA,
    backend,
    dialogs,
    item_texts,
    load_stats,
    page,
    settle,
    window,
)
from tests.test_perf_stats_lock import LockHolder
from tinypedal.setting import cfg
from tinypedal.ui.quick import game_pictures, stats_backend
from tinypedal.userfile import driver_history
from tinypedal.userfile.driver_history import SessionRecord, read_records, record_line


def history_file(folder: str) -> str:
    return driver_history.history_path(folder)


def write_lines(folder: str, data: bytes, mode: str = "ab"):
    with open(history_file(folder), mode) as file:
        file.write(data)


def record(index: int, **values) -> SessionRecord:
    return SessionRecord(1_700_000_000.0 + index * 60, f"Track {index % 5}", "GT3 - BMW", 1, 100.0 + index % 7,
                         **values)


def lines_of(records) -> bytes:
    return "".join(record_line(entry) for entry in records).encode("utf-8")


def full_read(folder: str) -> list[SessionRecord]:
    """Records as parsed from scratch"""
    driver_history.forget_records(folder)
    return read_records(folder)


@pytest.fixture
def parsed(monkeypatch):
    """Records parsed (parse_record calls)"""
    calls = []
    original = driver_history.parse_record
    monkeypatch.setattr(driver_history, "parse_record", lambda data: calls.append(1) or original(data))
    return calls


# --- Incremental history parsing
def test_appended_lines_parsed_only(tmp_path, parsed):
    folder = str(tmp_path)
    write_lines(folder, lines_of(record(index) for index in range(50)), "wb")
    assert len(read_records(folder)) == 50 and len(parsed) == 50
    parsed.clear()
    assert len(read_records(folder)) == 50 and not parsed  # unchanged: kept
    driver_history.append_record(folder, record(50))
    records = read_records(folder)
    assert len(parsed) == 1 and records == full_read(folder)  # new line only
    records.clear()  # copy: kept records not changed
    assert len(read_records(folder)) == 51


def test_rewritten_file_parsed_again(tmp_path, parsed):
    folder = str(tmp_path)
    many = [record(index) for index in range(30)]
    driver_history.save_history(folder, many)
    read_records(folder)
    parsed.clear()
    driver_history.save_history(folder, [*many[:10], record(99)])  # rewritten (edit, trim): kept as written
    assert read_records(folder) == [*many[:10], record(99)] and not parsed
    assert read_records(folder) == full_read(folder) and len(parsed) == 11
    # Same file changed in place, larger: start differs, parsed again
    parsed.clear()
    write_lines(folder, lines_of([record(5)._replace(best=90.0), *many[1:20]]), "r+b")
    assert read_records(folder) == full_read(folder)
    assert len(parsed) >= 20


def test_unfinished_last_line_and_newlines(tmp_path):
    folder = str(tmp_path)
    write_lines(folder, lines_of([record(1)]).replace(b"\n", b"\r\n") + lines_of([record(2)]), "wb")
    half = record_line(record(3)).encode("utf-8")
    write_lines(folder, half[:20])  # being written
    assert read_records(folder) == [record(1), record(2)] == full_read(folder)
    write_lines(folder, half[20:])
    assert read_records(folder) == [record(1), record(2), record(3)] == full_read(folder)
    write_lines(folder, record_line(record(4)).rstrip("\n").encode("utf-8"))  # no newline at end: kept anyway
    assert read_records(folder)[-1] == record(4) == full_read(folder)[-1]
    driver_history.append_record(folder, record(5))  # put on a line of its own
    assert read_records(folder)[-2:] == [record(4), record(5)] == full_read(folder)[-2:]


def test_out_of_order_and_equal_times_as_full_parse(tmp_path):
    folder = str(tmp_path)
    write_lines(folder, lines_of([record(5), record(1), record(5)._replace(track="Other")]), "wb")
    read_records(folder)
    write_lines(folder, lines_of([record(3), record(5)._replace(track="Last"), record(0)]))
    assert read_records(folder) == full_read(folder)
    assert [entry.track for entry in read_records(folder) if entry.time == record(5).time] == [
        "Track 0", "Other", "Last"]


def test_unreadable_file_not_served_from_cache(tmp_path, monkeypatch):
    folder = str(tmp_path)
    driver_history.save_history(folder, [record(1)])
    assert read_records(folder) == [record(1)]

    def locked_open(file, *args, **kwargs):
        raise PermissionError(13, "locked", file)

    monkeypatch.setattr(driver_history, "open", locked_open, raising=False)
    with pytest.raises(OSError):
        read_records(folder, strict=True)  # never rewritten from records kept
    assert read_records(folder) == []
    monkeypatch.undo()
    os.remove(history_file(folder))
    assert read_records(folder) == []


def test_concurrent_reads_and_appends(tmp_path):
    folder = str(tmp_path)
    errors = []
    done = threading.Event()

    def reader():
        while not done.is_set():
            records = read_records(folder)
            if records != sorted(records, key=lambda entry: entry.time) or len(set(records)) != len(records):
                errors.append(records)

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for thread in threads:
        thread.start()
    for index in range(200):
        driver_history.append_record(folder, record(index))
    done.set()
    for thread in threads:
        thread.join()
    assert not errors and read_records(folder) == full_read(folder) == [record(index) for index in range(200)]


# --- Page: history read & edits saved on a worker thread
@pytest.fixture
def big_history(monkeypatch):
    """Every history read in background, threads reading it recorded"""
    driver_history.save_history(cfg.path.config, HISTORY)
    driver_history.forget_records()
    monkeypatch.setattr(stats_backend, "SYNC_HISTORY_BYTES", 0)
    threads = []
    original = stats_backend.load_history

    def load_history(path, strict=False):
        threads.append(threading.current_thread())
        return original(path, strict)

    monkeypatch.setattr(stats_backend, "load_history", load_history)
    return threads


def test_page_opens_while_history_read_in_background(window, big_history):  # noqa: F811
    stats = stats_backend.DriverStatsBackend(window)
    try:
        assert stats.loading and not stats.hasRows and stats.busy()  # page shown at once, read in background
        settle(stats)
        assert big_history and threading.main_thread() not in big_history
        assert not stats.loading and stats.currentTrack == SPA and stats.row_keys() == ["Hyper - Ferrari", OREGA]
        assert len(stats.history) == len(HISTORY) and stats.trackInfo["subtitle"].startswith("2 vehicles · 4 sessions")
    finally:
        stats.release()
        settle(stats)


def test_changed_history_read_in_background_page_kept(backend, big_history):  # noqa: F811
    backend.reload_stats()
    settle(backend)
    backend.selectRow(OREGA)
    sessions = len(backend.sessions)
    driver_history.append_record(cfg.path.config, SessionRecord(time.time(), SPA, OREGA, 1, 121.9, seconds=900.0))
    holder = LockHolder()  # stats module saving
    try:
        start = time.monotonic()
        backend.reload_stats()
        assert time.monotonic() - start < 0.2 and backend.busy()
        QCoreApplication.processEvents()
        assert len(backend.sessions) == sessions and backend.selectedKey == OREGA  # shown as it was
    finally:
        holder.release()
    settle(backend)
    assert len(backend.sessions) == sessions + 1 and backend.selectedKey == OREGA
    assert threading.main_thread() not in big_history


def test_edit_saved_on_worker_with_history_loaded_once(backend, dialogs, monkeypatch):  # noqa: F811
    driver_history.save_history(cfg.path.config, HISTORY)
    backend.reload_stats()
    calls = []
    real_replace = stats_backend.replace_records

    def replace_records(*args):
        calls.append((threading.current_thread(), args))
        return real_replace(*args)

    monkeypatch.setattr(stats_backend, "replace_records", replace_records)
    backend.selectRow(OREGA)
    backend.removeVehicle()
    assert backend.editing and not backend.canUndo  # saved in background
    settle(backend)
    assert OREGA not in load_stats()[SPA] and backend.canUndo and not backend.editing
    thread, args = calls[0]
    assert thread is not threading.main_thread()
    assert args[3] is not None and len(args[3]) == len(HISTORY)  # history loaded by edit, not read again


def test_rollback_delay_on_worker(backend, dialogs, monkeypatch):  # noqa: F811
    from tinypedal.userfile import json_setting

    driver_history.save_history(cfg.path.config, HISTORY)
    sleeps = []
    real_replace = stats_backend.replace_records
    calls = []

    def flaky_replace(*args):
        calls.append(args)
        if len(calls) > 1:  # rollback fails every time
            raise PermissionError(13, "locked")
        return real_replace(*args)

    monkeypatch.setattr(stats_backend, "replace_records", flaky_replace)

    class Clock:
        """time module, sleep recorded"""

        def __getattr__(self, name):
            return getattr(time, name)

        @staticmethod
        def sleep(seconds):
            sleeps.append(threading.current_thread())

    monkeypatch.setattr(stats_backend, "time", Clock())
    with monkeypatch.context() as patch:
        patch.setattr(json_setting, "save_json_file", lambda *args, **kwargs: None)  # write lost
        backend.selectRow("Hyper - Ferrari")
        backend.removeVehicle()
        settle(backend)
    assert len(sleeps) == stats_backend.ROLLBACK_ATTEMPTS - 1
    assert threading.main_thread() not in sleeps
    assert backend.canUndo and "Undo" in dialogs[-1]  # history changed only


def test_edits_wait_in_order_and_conflicting_ones_refused(backend, dialogs):  # noqa: F811
    holder = LockHolder()
    try:
        backend.selectRow("Hyper - Ferrari")
        backend.removeVehicle()
        assert backend.editing
        backend.deleteTrack(SPA)  # stats shown not up to date: refused
        backend.resetLapTime(OREGA, "pb")
        backend.undo()
        assert [job.kind for job in (backend._running_job, *backend._locked_jobs) if job] == ["edit"]
        assert not any(action["enabled"] for action in backend.rowActions(OREGA, "vehicle")
                       if action["id"] == "remove")
    finally:
        holder.release()
    settle(backend)
    saved = load_stats()
    assert "Hyper - Ferrari" not in saved[SPA] and saved[SPA][OREGA]["pb"] == 121.5
    backend.undo()
    backend.redo()  # undo being saved: refused
    settle(backend)
    assert "Hyper - Ferrari" in load_stats()[SPA] and backend.canRedo and not dialogs


# --- Logos & column widths
def test_logos_looked_for_once(backend, monkeypatch):  # noqa: F811
    asked = []
    monkeypatch.setattr(game_pictures, "track_logo_url", lambda *names: asked.append(names) or "")
    monkeypatch.setattr(game_pictures, "brand_logo_url", lambda *names: asked.append(names) or "")
    backend.logos = game_pictures.LogoCache()
    backend.selectTrack("")
    backend.refresh_table()
    count = len(asked)
    assert count
    for _ in range(3):
        backend.refresh_table()
    backend.selectTrack(SPA)
    backend.selectTrack("")
    assert len(asked) <= count + 2  # vehicle logos of Spa only


def test_pictures_changed_refreshes_only_when_logos_change(backend, monkeypatch):  # noqa: F811
    from tinypedal.userfile.game_images import images

    backend.selectTrack("")
    tracks_signals, refreshes = [], []
    backend.tracksChanged.connect(lambda: tracks_signals.append(1))
    original = type(backend).refresh_table
    monkeypatch.setattr(type(backend), "refresh_table", lambda self: refreshes.append(1) or original(self))
    backend.pictures_changed()
    assert not tracks_signals and not refreshes  # same logos: nothing shown again
    monkeypatch.setattr(game_pictures, "track_logo_url", lambda *names: f"file:///{names[0]}.png")
    monkeypatch.setattr(images, "version", images.version + 1)  # pictures fetched from game
    backend.pictures_changed()
    assert tracks_signals and refreshes
    assert backend.tracks[1]["logo"].endswith(".png") and backend.cell("Monza", "track").logo.endswith("Monza.png")


def test_column_texts_measured_once(backend, monkeypatch):  # noqa: F811
    measured = []

    class Metrics(QFontMetricsF):
        def horizontalAdvance(self, text, *args):
            measured.append(text)
            return super().horizontalAdvance(text, *args)

    monkeypatch.setattr(stats_backend, "QFontMetricsF", Metrics)
    backend._text_widths.clear()
    backend.refresh_table()
    first = len(measured)
    backend.refresh_table()
    assert first and len(measured) == first  # unchanged texts not measured again
    widths = {column["key"]: column["width"] for column in backend.columns}
    backend._text_widths.clear()
    backend.publish_columns()
    assert {column["key"]: column["width"] for column in backend.columns} == widths


def test_table_logos_loaded_only_in_logo_cells(page, monkeypatch):  # noqa: F811
    page.resize(1400, 860)
    page.show()
    stats = page.backend

    def game_logos():
        count, stack = 0, [page.view.rootObject()]
        while stack:
            item = stack.pop()
            if item.property("dragWidths") is not None:  # table
                inner = list(item.childItems())
                while inner:
                    child = inner.pop()
                    count += child.property("fitWidth") is not None  # GameLogo
                    inner.extend(child.childItems())
                continue
            stack.extend(item.childItems())
        return count

    for _ in range(3):
        QCoreApplication.processEvents()
    assert game_logos() == 0  # no logo: no image item in any cell
    monkeypatch.setattr(game_pictures, "brand_logo_url", lambda *names: "file:///logo.png")
    stats.logos = game_pictures.LogoCache()
    stats.refresh_table()
    for _ in range(3):
        QCoreApplication.processEvents()
    assert game_logos() == len(stats.row_keys())  # vehicle column only
    assert "Hyper - Ferrari" in item_texts(page.view)


def visible_texts(view) -> set:
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        if not item.isVisible():
            continue
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def test_page_loading_without_qml_warnings(dialogs, big_history, monkeypatch):  # noqa: F811
    from PySide6.QtCore import QEvent, qInstallMessageHandler

    from tests.test_driver_stats_viewer import STATS, write_stats
    from tinypedal.api_control import api
    from tinypedal.ui.driver_stats_viewer import DriverStatsViewer

    write_stats(STATS)
    monkeypatch.setattr(type(api.read.session), "track_name", lambda self: SPA, raising=False)
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    holder = LockHolder()  # read waits: page shown loading
    viewer = DriverStatsViewer(None)
    try:
        viewer.resize(1400, 860)
        viewer.show()
        for _ in range(3):
            QCoreApplication.processEvents()
        assert viewer.backend.loading and "No stats yet: drive a few laps." not in visible_texts(viewer.view)
        holder.release()
        settle(viewer.backend)
        for _ in range(3):
            QCoreApplication.processEvents()
        assert not viewer.backend.loading and "Lap Time Reference" in item_texts(viewer.view)
    finally:
        holder.release()
        qInstallMessageHandler(previous)
        viewer.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not [text for text in messages if ".qml" in text], messages
