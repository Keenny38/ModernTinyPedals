"""Driver stats page never waits for STATS_LOCK (stats module saving): reloads & edits run in order
once free; stats module releases the lock while waiting to load the stats file again"""

import os
import threading
import time

from PySide6.QtCore import QCoreApplication
from test_driver_stats_viewer import OREGA, SPA, backend, dialogs, load_stats, window, write_stats  # noqa: F401

from tinypedal.setting import cfg
from tinypedal.userfile import driver_stats
from tinypedal.userfile.driver_stats import DriverStats


class LockHolder:
    """STATS_LOCK held by another thread (stats module saving) until released"""

    def __init__(self):
        self.taken = threading.Event()
        self.free = threading.Event()
        self.thread = threading.Thread(target=self.hold, daemon=True)
        self.thread.start()
        assert self.taken.wait(5)

    def hold(self):
        with driver_stats.STATS_LOCK:
            self.taken.set()
            self.free.wait(10)

    def release(self):
        self.free.set()
        self.thread.join(5)


def wait_jobs(page, timeout: float = 5):
    end = time.monotonic() + timeout
    while page._locked_jobs:
        assert time.monotonic() < end, "jobs still waiting"
        QCoreApplication.processEvents()
        time.sleep(0.005)


def test_edits_and_reload_wait_without_blocking(backend):  # noqa: F811
    holder = LockHolder()
    try:
        start = time.monotonic()
        backend.reload_stats()
        assert not backend.edit_stats((SPA, "Hyper - Ferrari"), None)  # waits, page not blocked
        assert time.monotonic() - start < 0.5
        assert len(backend._locked_jobs) == 2 and backend.lock_timer.isActive()
        assert "Hyper - Ferrari" in load_stats()[SPA] and not backend.canUndo
    finally:
        holder.release()
    wait_jobs(backend)
    assert "Hyper - Ferrari" not in load_stats()[SPA] and backend.canUndo
    holder = LockHolder()
    try:
        backend.undo()
        assert "Hyper - Ferrari" not in load_stats()[SPA]
    finally:
        holder.release()
    wait_jobs(backend)
    assert "Hyper - Ferrari" in load_stats()[SPA] and backend.canRedo and not backend.canUndo
    backend.redo()  # lock free: done at once
    assert "Hyper - Ferrari" not in load_stats()[SPA] and not backend._locked_jobs


def test_module_save_kept_while_edit_waits(backend):  # noqa: F811
    holder = LockHolder()
    try:
        backend.deleteTrack("Monza")  # waits for module save
    finally:
        holder.release()
    driver_stats.save_driver_stats((SPA, OREGA), DriverStats(valid=5), cfg.path.config)
    wait_jobs(backend)
    saved = load_stats()
    assert "Monza" not in saved and saved[SPA][OREGA]["valid"] == 35  # both kept


def test_release_drops_waiting_jobs(backend):  # noqa: F811
    holder = LockHolder()
    try:
        backend.reload_stats()
        backend.release()
        assert not backend._locked_jobs and not backend.lock_timer.isActive()
    finally:
        holder.release()


def test_module_save_releases_lock_while_retrying(tmp_path, monkeypatch):
    """Unreadable stats file: lock free between load attempts (page edits not held up 0.5 s)"""
    filepath = f"{tmp_path.as_posix()}/"
    with open(f"{filepath}driver.stats", "w", encoding="utf-8") as file:
        file.write("{broken")
    free_between = []
    original_sleep = driver_stats.sleep

    def sleep(seconds):
        result = []

        def other_thread():  # RLock: owner thread could take it anyway
            got = driver_stats.STATS_LOCK.acquire(blocking=False)
            if got:
                driver_stats.STATS_LOCK.release()
            result.append(got)

        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()
        free_between.append(result[0])
        if len(free_between) == 3:  # file repaired by viewer meanwhile
            with open(f"{filepath}driver.stats", "w", encoding="utf-8") as file:
                file.write('{"T": {"Car": {"valid": 2}}}')
        original_sleep(0)

    monkeypatch.setattr(driver_stats, "sleep", sleep)
    driver_stats.save_driver_stats(("T", "Car"), DriverStats(valid=1), filepath)
    assert free_between == [True, True, True]
    assert driver_stats.load_driver_stats(("T", "Car"), filepath).valid == 3  # repaired file used, no reset


def test_module_save_backup_when_never_readable(tmp_path, monkeypatch):
    filepath = f"{tmp_path.as_posix()}/"
    with open(f"{filepath}driver.stats", "w", encoding="utf-8") as file:
        file.write("{broken")
    monkeypatch.setattr(driver_stats, "sleep", lambda seconds: None)
    driver_stats.save_driver_stats(("T", "Car"), DriverStats(valid=1), filepath)
    assert driver_stats.load_driver_stats(("T", "Car"), filepath).valid == 1  # reset after backup
    assert any(name != "driver.stats" for name in os.listdir(filepath))  # backup made


def test_page_uses_stats_written_meanwhile(backend):  # noqa: F811
    stats = load_stats()
    stats["Imola"] = {"GT3 - BMW": {"pb": 101.0}}
    holder = LockHolder()
    try:
        backend.reload_stats()
        write_stats(stats)  # saved before page could read
    finally:
        holder.release()
    wait_jobs(backend)
    assert "Imola" in [track["key"] for track in backend.tracks]
