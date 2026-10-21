"""Home page links into other pages: telemetry viewer on the debrief laps & a corner, driver stats on the last
session track & car"""

import os
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.setting import cfg
from neopedal.ui.quick.lap_focus import CORNERS_TAB, corner_at, show_laps
from tests.test_driver_stats_viewer import OREGA, SPA, backend, dialogs, settle, window  # noqa: F401
from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_e2 import START, lap_info, write_lap


def wait_until(condition, timeout: float = 10.0):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "not done in time"
        QCoreApplication.processEvents()
        time.sleep(0.005)


def corner(start: float, apex: float, end: float):
    return SimpleNamespace(corner=SimpleNamespace(start=start, apex=apex, end=end))


def test_corner_at_lap_distance():
    rows = [corner(100, 150, 200), corner(400, 450, 500)]
    assert corner_at(rows, 160) == 0 and corner_at(rows, 480) == 1
    assert corner_at(rows, 300) == 0 and corner_at(rows, 420.5) == 1  # between corners: nearest apex
    assert corner_at([], 100) == -1


@pytest.fixture
def lap_page(ui_env):
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick.lap_backend import LapViewerBackend

    folder = cfg.path.telemetry.rstrip("/")
    for number, lap_time, brake in ((1, 90.0, 0.45), (2, 91.0, 0.43), (3, 92.5, 0.44)):
        write_lap(folder, number, lap_time, brake=brake, info=lap_info(), timestamp=START + 100 * number)
    parent = QWidget()
    page = LapViewerBackend(parent, cfg.path.telemetry)
    page.refresh()
    wait_loaded(page)
    yield page
    page.release()
    parent.deleteLater()


def lap_path(page, number: int) -> str:
    return next(entry.file.path for entry in page.entries if f"lap{number:03d}" in entry.file.filename)


def test_telemetry_opens_debrief_laps_on_a_corner(lap_page):
    from neopedal.ui.quick.lap_actions import path_key

    reference, compared = lap_path(lap_page, 1), lap_path(lap_page, 3)
    lap_page.setSideTab(0)
    # Debrief paths are made from the telemetry setting (other slashes on Windows): matched to the listed laps
    separator = "\\" if os.name == "nt" else "/"  # a backslash is a file name character elsewhere
    assert show_laps(lap_page, reference.replace("\\", "/"), compared.replace("/", separator), 1560.0)
    wait_loaded(lap_page)
    wait_until(lambda: lap_page.cornerTable.focusRequest >= 0)
    assert lap_page.checked == {reference, compared} and lap_page.reference_key == reference
    assert lap_page.sideTab == CORNERS_TAB
    index = lap_page.cornerTable.focusRequest
    row = lap_page.corner_rows()[index].corner
    assert row.start <= 1560.0 <= row.end and lap_page.selectedCorner == index
    assert lap_page.cornerTable.takeFocus() == index and lap_page.cornerTable.focusRequest == -1  # zoomed once
    assert path_key(lap_page.compared_lap().key) == path_key(compared)


def test_telemetry_page_zooms_charts_on_the_corner(lap_page):
    """Lap viewer page shown: Corners tab opened, charts zoomed on the corner (QML takes the request once)"""
    from PySide6.QtWidgets import QWidget

    from neopedal.ui.quick import create_quick_view

    parent = QWidget()
    parent.resize(1400, 900)
    view = create_quick_view(parent, "LapViewer.qml", {"backend": lap_page})
    view.resize(1400, 900)
    parent.show()
    try:
        assert not view.errors()
        QCoreApplication.processEvents()
        assert show_laps(lap_page, lap_path(lap_page, 1), lap_path(lap_page, 3), 1560.0)
        wait_loaded(lap_page)
        wait_until(lambda: lap_page.zoom_distances() != (0.0, 0.0))  # corner list built, then charts zoomed
        start, end = lap_page.zoom_distances()
        row = lap_page.corner_rows()[lap_page.selectedCorner].corner
        assert start <= row.start < row.end <= end and end - start < 1500  # corner & margins, not whole lap
        assert lap_page.cornerTable.focusRequest == -1
    finally:
        parent.hide()
        view.setSource(view.source().__class__())
        parent.deleteLater()


def test_telemetry_opens_laps_without_corner(lap_page):
    reference = lap_path(lap_page, 2)
    assert show_laps(lap_page, reference)
    wait_loaded(lap_page)
    assert lap_page.checked == {reference} and lap_page.cornerTable.focusRequest == -1
    assert not show_laps(lap_page, "C:/elsewhere/lap.csv", "", 10.0)  # not a lap of a track folder


def test_driver_stats_open_on_session_track_and_car(backend):  # noqa: F811
    backend.show_combo(SPA, OREGA)
    assert backend.selected_stats_key == SPA and backend.selectedKey == OREGA
    backend.selectTrack("")
    backend.show_combo("Unknown track", OREGA)  # no stats: page left as it is
    assert backend.selected_stats_key == ""


def test_driver_stats_session_shown_once_read(backend):  # noqa: F811
    backend.selectTrack("")
    backend._loaded = False  # stats being read (page just opened)
    backend.show_combo(SPA, OREGA)
    assert backend.selected_stats_key == ""
    backend._loaded = True
    backend.reload_stats()
    settle(backend)
    assert backend.selected_stats_key == SPA and backend.selectedKey == OREGA
