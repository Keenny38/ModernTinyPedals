"""UI thread budget: page slots on big data return within a frame budget, heavy work runs in background

Regression guard of the work moved off the UI thread: a 50000 sessions history (Driver Stats) and long laps
(lap viewer chart settings, reference change). Each slot is timed on the UI thread only (background results
handed over later are not counted). Budget kept generous (slow CI machines): before the work moved off the UI
thread these slots took 0.15 s to 1 s on a fast machine.
"""

import gc
import time

import pytest

from neopedal.setting import cfg
from neopedal.userfile import driver_history
from neopedal.userfile.driver_history import SessionRecord, record_line
from tests.test_driver_stats_viewer import backend, dialogs, settle, window  # noqa: F401  (fixtures)
from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_e2 import START, write_lap

UI_BUDGET = 0.05  # seconds a slot may hold the UI thread
HISTORY_RECORDS = driver_history.MAX_RECORDS - 1  # one appended stays under the limit
LAP_SAMPLES = 20000


def timed(call) -> float:
    # Garbage of the whole test run collected first: a full collection of Python 3.11 / 3.13 (no incremental GC)
    # over the heap of thousands of tests landing in the slot took up to 0.7 s on CI, never the slot itself
    gc.collect()
    start = time.perf_counter()
    call()
    return time.perf_counter() - start


@pytest.fixture
def big_history():
    records = (SessionRecord(1_700_000_000.0 + index * 60, f"Track {index % 40}", f"GT3 - Car {index % 25}", 1,
                             100.0 + index % 7) for index in range(HISTORY_RECORDS))
    path = driver_history.history_path(cfg.path.config)
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write("".join(record_line(entry) for entry in records))
    driver_history.forget_records()
    yield path
    driver_history.forget_records()


def test_driver_stats_reload_within_budget(window, big_history):  # noqa: F811
    from neopedal.ui.quick.stats_backend import DriverStatsBackend

    start = time.perf_counter()
    page = DriverStatsBackend(window)
    opened = time.perf_counter() - start
    try:
        assert opened < UI_BUDGET * 2  # page built, history read in background
        settle(page, timeout=60)
        assert len(page.history) == HISTORY_RECORDS
        driver_history.append_record(cfg.path.config, SessionRecord(time.time(), "Track 1", "GT3 - Car 1", 1, 99.0))
        assert timed(page.reload_stats) < UI_BUDGET  # end of stint while page shown
        settle(page, timeout=60)
        assert len(page.history) == HISTORY_RECORDS + 1
    finally:
        page.release()
        settle(page, timeout=60)


@pytest.fixture
def long_laps(ui_env):
    """Lap viewer with 4 long laps checked & loaded"""
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick.lap_backend import LapViewerBackend

    folder = cfg.path.telemetry.rstrip("/")
    for number in range(1, 5):
        write_lap(folder, number, 90.0 + number, samples=LAP_SAMPLES, length=13600.0, timestamp=START + number * 100)
    parent = QWidget()
    page = LapViewerBackend(parent, cfg.path.telemetry)
    page.refresh()
    wait_loaded(page)
    page.checked = {entry.file.path for entry in page.entries}
    page.load_laps()
    wait_loaded(page)
    page.wait_jobs()
    yield page
    page.release()
    parent.deleteLater()


def test_lap_viewer_settings_within_budget(long_laps):
    page = long_laps
    assert len(page.data.laps) == 4
    changes = (
        lambda: page.setTimeAxis(True),
        lambda: page.setSmoothing(2),
        lambda: page.setEnvelope(True),
        lambda: page.setChannelVisible("rpm", True),
        lambda: page.setDeltaWindow(80),
    )
    for change in changes:
        assert timed(change) < UI_BUDGET
        page.wait_jobs()
        assert not page.is_loading()


def test_overlay_preview_within_budget(ui_env, bundled_fonts):
    """Overlay picture of a lap history widget at max zoom: drawn within budget, same inputs reused at once"""
    from neopedal.ui import widget_preview

    widget_preview.CACHE.clear()
    try:
        setting = cfg.user.setting["delta_graph"]
        assert timed(lambda: widget_preview.render_image(cfg, "delta_graph", setting, 3.0)) < UI_BUDGET * 2
        assert timed(lambda: widget_preview.render_image(cfg, "delta_graph", setting, 3.0)) < UI_BUDGET / 10
    finally:
        widget_preview.CACHE.clear()


def test_overlays_page_refresh_while_hidden_within_budget(ui_env, bundled_fonts):
    """Hotkey, tray toggle or config save while the Overlays page is built but hidden: rows only"""
    from neopedal.module_control import wctrl
    from neopedal.ui.quick.overlay_backend import OverlayBackend

    page = OverlayBackend(None, wctrl, lambda name: None, lambda text: False)
    try:
        page.set_active(False)
        assert max(timed(page.refresh) for _ in range(5)) < UI_BUDGET / 5
    finally:
        page.deleteLater()
