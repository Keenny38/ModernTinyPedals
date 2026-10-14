"""Background jobs of pages: work off the UI thread, result handed back on the UI thread"""

import gc
import logging
import threading
import time
from functools import partial

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject

from neopedal import jobs as job_module  # job primitives (worker threads) in core jobs module
from neopedal.ui.quick.background import MAX_WORKERS, WORKER_NAME, BackgroundJobs, JobCancelled, JobToken


@pytest.fixture(autouse=True)
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        QCoreApplication.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.005)


def test_result_handed_on_ui_thread():
    jobs = BackgroundJobs()
    seen = {}

    def work():
        seen["work_thread"] = threading.current_thread()
        return 42

    def done(result):
        seen["result"] = result
        seen["done_thread"] = threading.current_thread()

    jobs.run("answer", work, done)
    wait_for(lambda: "result" in seen)
    assert seen["result"] == 42
    assert seen["work_thread"] is not threading.main_thread()
    assert seen["done_thread"] is threading.main_thread()
    assert jobs.running == 0


def test_failed_callback_gets_error():
    jobs = BackgroundJobs()
    errors = []

    def work():
        raise ValueError("bad file")

    jobs.run("broken", work, lambda _: errors.append("done"), errors.append)
    wait_for(lambda: errors)
    assert isinstance(errors[0], ValueError)


def test_failure_without_callback_logged(caplog):
    jobs = BackgroundJobs(label="Test page")
    jobs.run("broken", lambda: 1 / 0)
    wait_for(lambda: jobs.running == 0)
    assert "Test page: broken failed" in caplog.text


def test_only_last_job_of_key_handed_over():
    jobs = BackgroundJobs()
    release = threading.Event()
    results = []
    jobs.run("load", lambda: release.wait(5) and "old", results.append, key="load")
    jobs.run("load", lambda: "new", results.append, key="load")
    assert jobs.is_busy("load")
    release.set()
    wait_for(lambda: results)
    wait_for(lambda: jobs.running == 0)
    assert results == ["new"]
    assert not jobs.is_busy("load")


def test_page_method_held_weakly():
    class Page:
        def __init__(self):
            self.results = []

        def done(self, result):
            self.results.append(result)

    jobs = BackgroundJobs()
    page = Page()
    release = threading.Event()
    jobs.run("load", lambda: release.wait(5), page.done)
    del page  # page gone before the result: dropped, no error
    release.set()
    wait_for(lambda: jobs.running == 0)


# --- Scheduler: shared bounded pool, single flight & coalescing per key, cooperative cancellation
def test_shared_pool_bounded_and_every_job_without_key_handed_over():
    jobs = BackgroundJobs()
    release = threading.Event()
    lock = threading.Lock()
    state = {"now": 0, "most": 0}
    results = []

    def work(number):
        with lock:
            state["now"] += 1
            state["most"] = max(state["most"], state["now"])
        release.wait(5)
        with lock:
            state["now"] -= 1
        return number

    for number in range(MAX_WORKERS * 3):
        jobs.run("job", partial(work, number), results.append)
    wait_for(lambda: state["now"] == MAX_WORKERS)
    time.sleep(0.05)
    assert state["most"] == MAX_WORKERS and jobs.running == MAX_WORKERS * 3
    release.set()
    wait_for(lambda: jobs.running == 0)
    assert sorted(results) == list(range(MAX_WORKERS * 3))
    assert state["most"] == MAX_WORKERS
    assert all(thread.daemon for thread in threading.enumerate() if thread.name.startswith(WORKER_NAME))


def test_key_single_flight_newest_waiting_job_only():
    jobs = BackgroundJobs()
    release = threading.Event()
    ran, results = [], []
    running = threading.Event()

    def slow():
        running.set()
        release.wait(5)
        ran.append("first")
        return "first"

    def quick(name):
        ran.append(name)
        return name

    jobs.run("load", slow, results.append, key="load")
    running.wait(5)
    for name in ("second", "third", "last"):
        jobs.run("load", partial(quick, name), results.append, key="load")
    assert jobs.is_busy("load") and jobs.running == 2  # running one & newest waiting one
    time.sleep(0.05)
    assert ran == []  # waiting job never runs alongside the running one
    release.set()
    wait_for(lambda: jobs.running == 0)
    assert ran == ["first", "last"]  # intermediate jobs never ran
    assert results == ["last"]  # superseded running job not handed over
    assert not jobs.is_busy("load")


def test_superseded_cancellable_job_stops_early():
    jobs = BackgroundJobs()
    started = threading.Event()
    seen = {}
    results, errors = [], []

    def long_work(token):
        started.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            token.check()
            time.sleep(0.005)
        return "too late"

    jobs.run("load", long_work, results.append, errors.append, key="load", cancellable=True)
    started.wait(5)
    begin = time.monotonic()
    jobs.run("load", lambda token: seen.setdefault("token", token) and "new", results.append, errors.append,
             key="load", cancellable=True)
    wait_for(lambda: results)
    assert time.monotonic() - begin < 2  # old job stopped at its next check
    assert results == ["new"] and errors == []  # JobCancelled silently dropped
    assert isinstance(seen["token"], JobToken) and not seen["token"].cancelled
    wait_for(lambda: jobs.running == 0)


def test_cancel_key_and_cancel_all_drop_results():
    jobs = BackgroundJobs()
    release = threading.Event()
    results, errors = [], []
    jobs.run("load", lambda: release.wait(5) and "a", results.append, errors.append, key="a")
    jobs.run("load", lambda: "a2", results.append, errors.append, key="a")
    jobs.run("load", lambda: release.wait(5) and "b", results.append, errors.append, key="b")
    jobs.run("load", lambda: release.wait(5) and "c", results.append, errors.append)
    assert jobs.cancel("a")
    assert not jobs.is_busy("a") and jobs.is_busy("b")
    assert not jobs.cancel("a")  # nothing left to cancel
    jobs.cancel_all()
    assert not jobs.is_busy("b")
    release.set()
    wait_for(lambda: jobs.running == 0)
    assert results == [] and errors == []
    jobs.run("load", lambda: "after", results.append, key="a")  # key usable again
    wait_for(lambda: results)
    assert results == ["after"]


def test_token_check_raises_once_cancelled():
    token = JobToken()
    token.check()
    token.cancel()
    assert token.cancelled
    with pytest.raises(JobCancelled):
        token.check()


def test_waiting_jobs_of_deleted_jobs_object_never_run():
    blockers = BackgroundJobs()
    release = threading.Event()
    started = []
    for _ in range(MAX_WORKERS):
        blockers.run("block", lambda: started.append(1) or release.wait(5))
    wait_for(lambda: len(started) == MAX_WORKERS)  # every worker busy: next job waits in queue
    jobs = BackgroundJobs()
    ran, results = [], []
    jobs.run("queued", lambda: ran.append(1), results.append)
    jobs.run("keyed", lambda: ran.append(2), results.append, key="k")
    del jobs
    gc.collect()
    release.set()
    wait_for(lambda: blockers.running == 0)
    time.sleep(0.05)
    QCoreApplication.processEvents()
    assert ran == [] and results == []


def test_result_dropped_when_jobs_object_deleted_meanwhile():
    parent = QObject()
    jobs = BackgroundJobs(parent)
    release = threading.Event()
    results = []
    jobs.run("load", lambda: release.wait(5), results.append)
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    release.set()
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert results == []


def test_slow_job_logged(caplog, monkeypatch):
    monkeypatch.setattr(job_module, "SLOW_JOB", 0.0)
    jobs = BackgroundJobs(label="Test page")
    with caplog.at_level(logging.INFO, logger=job_module.__name__):
        jobs.run("slow", lambda: time.sleep(0.01))
        wait_for(lambda: jobs.running == 0)
    assert "Test page: slow took" in caplog.text
