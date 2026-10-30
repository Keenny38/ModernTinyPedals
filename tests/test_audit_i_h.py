"""Perf audit 2026-10-18, lot H: wind direction repaint key, Tyre Overview band shapes & cached text widths,
request logs formatted only when logged, class_key cache, Lap Library file moves in background"""

import logging
import os
import threading
import time
from importlib import import_module
from math import degrees, pi, radians

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from neopedal.api_control import api
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget


@pytest.fixture
def make(ui_env, bundled_fonts):
    """Overlay of modern or classic design"""
    created = []

    def build(name: str, modern: bool, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield build
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


# --- Wind direction: repaint once a turn moves the rim by a device pixel
@pytest.fixture
def wind(ui_env, monkeypatch):
    """Wind blowing toward world x, car heading set by yaw"""
    state = {"wind": (5.0, 0.0, 0.0), "yaw": 0.0}
    monkeypatch.setattr(api.read.session, "wind_velocity", lambda *args: state["wind"])
    monkeypatch.setattr(api.read.vehicle, "orientation_yaw_radians", lambda *args: state["yaw"])
    return state


def test_rim_steps():
    from neopedal.widget.wind_direction import rim_steps

    assert rim_steps(0.0, 100.0) == 0
    assert rim_steps(degrees(1 / 100), 100.0) == 1  # one pixel at rim
    assert rim_steps(degrees(0.4 / 100), 100.0) == 0  # less than half a pixel: same key
    assert rim_steps(float("nan"), 100.0) == rim_steps(float("inf"), 100.0) == 0  # invalid reading
    # Same drawing whichever turn (was a jump of a whole turn in pixels: repaint at every update)
    assert rim_steps(359.95, 100.0) == rim_steps(0.01, 100.0) == rim_steps(-0.01, 100.0) == 0  # compass north
    assert rim_steps(179.99, 100.0) == rim_steps(-179.99, 100.0)  # headwind
    assert rim_steps(-90.0, 100.0) == rim_steps(270.0, 100.0)


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_wind_repaints_once_turn_is_visible(make, wind, monkeypatch, modern):
    widget = make("wind_direction", modern)
    repaints = []
    monkeypatch.setattr(widget, "request_update" if modern else "update", lambda *args: repaints.append(1))
    rim = (widget.dial.width() / 2 if modern else widget.area_center) * widget.devicePixelRatioF()
    # At whole pixel steps of rim, within a turn (0 to 360 degrees)
    compass_px, angle_px = round(0.3 * 2 * pi * rim), round(0.7 * 2 * pi * rim)
    reading = {"compass": degrees(compass_px / rim), "angle": degrees(angle_px / rim)}
    monkeypatch.setattr(widget, "read_wind", lambda: (reading["compass"], 5.0, reading["angle"]))

    def drawn():
        return widget.state if modern else widget.wind_state

    widget.timerEvent(None)
    assert len(repaints) == 1
    first = drawn()
    assert first[0] == round(reading["compass"], 1) and first[2] == round(reading["angle"], 1)
    # Heading jitter (was a repaint at every 0.1 degree): less than half a pixel at rim, nothing visible
    for shift in (0.3, -0.3, 0.45):
        reading["compass"] = degrees((compass_px + shift) / rim)
        reading["angle"] = degrees((angle_px - shift) / rim)
        widget.timerEvent(None)
    assert len(repaints) == 1 and drawn() == first
    reading["compass"] = degrees((compass_px + 2) / rim)  # visible turn: repaint, drawn with full precision (0.1 degree)
    widget.timerEvent(None)
    assert len(repaints) == 2 and drawn() == (round(reading["compass"], 1), *drawn()[1:])
    assert drawn()[2] == round(reading["angle"], 1)
    reading["angle"] = degrees((angle_px - 5) / rim)  # arrow turned alone
    widget.timerEvent(None)
    assert len(repaints) == 3
    reading["compass"] = reading["angle"] = float("nan")  # invalid reading: no error
    widget.timerEvent(None)
    monkeypatch.undo()
    assert widget.grab().width() > 0


@pytest.mark.parametrize("modern", [True, False], ids=["modern", "classic"])
def test_wind_compass_ignored_without_direction_marks(make, wind, monkeypatch, modern):
    widget = make("wind_direction", modern, show_direction_mark=False)
    wind["wind"] = (0.05, 0.0, 0.0)  # calm: no arrow, compass not drawn: nothing to repaint as car turns
    widget.timerEvent(None)
    repaints = []
    monkeypatch.setattr(widget, "request_update" if modern else "update", lambda *args: repaints.append(1))
    for yaw in (40, 80, 120):
        wind["yaw"] = radians(yaw)
        widget.timerEvent(None)
    state = widget.state if modern else widget.wind_state
    assert not repaints and state[0] == 0.0 and state[2] is None


# --- Tyre Overview: band shapes built once, cached text widths
@pytest.fixture
def tyres(monkeypatch):
    temps = {"ico": [80, 85, 90, 91, 86, 81, 70, 72, 74, 75, 73, 71]}
    tyre = api.read.tyre
    monkeypatch.setattr(tyre, "surface_temperature_ico", lambda *args: tuple(temps["ico"]))
    monkeypatch.setattr(tyre, "pressure", lambda *args: (150.0, 175.0, 200.0, 0.0))
    monkeypatch.setattr(tyre, "compound_class", lambda *args: ("Medium",) * 4)
    return temps


@pytest.mark.parametrize("depth", [True, False], ids=["depth", "flat"])
def test_tyre_bands_built_once_and_drawn_as_new(make, tyres, depth):
    cfg.user.config["overlay_style"]["enable_depth_effects"] = depth
    make("tyre_overview", True).grab()  # first overlay of a style warms shared caches (drawn a little apart)
    widget = make("tyre_overview", True)
    widget.timerEvent(None)
    widget.grab()
    shapes = widget.band_shapes(0, 3)
    assert len(shapes) == 3 and (shapes[0][2] is not None) == depth
    tyres["ico"] = [60, 100, 120, 40, 86, 81, 70, 72, 74, 75, 73, 71]  # other heat colors
    widget.timerEvent(None)
    image = widget.grab().toImage()
    assert widget.band_shapes(0, 3) is shapes  # not built again
    fresh = make("tyre_overview", True)  # drawn first time with these colors: same picture
    fresh.timerEvent(None)
    fresh.grab()  # (first paint of an overlay draws its texts a little apart)
    assert fresh.grab().toImage() == image
    assert set(widget._band_shapes) == {(index, 3) for index in range(4)}


def test_tyre_bands_shapes_match_tyre(make, tyres):
    widget = make("tyre_overview", True)
    tread, _ = widget.tread_of(1)
    rects = [rect for rect, _, _ in widget.band_shapes(1, 3)]
    assert rects[0].left() == pytest.approx(tread.left()) and rects[-1].right() == pytest.approx(tread.right())
    single = widget.band_shapes(1, 1)  # no surface reading: one band, own shape
    assert len(single) == 1 and single[0][0].width() == pytest.approx(tread.width())


@pytest.mark.parametrize("name, roles", [("tyre_overview", ("small", "label", "big")),
                                         ("corner_coach", ("value",))])
def test_cached_widths_equal_measured_widths(make, name, roles):
    widget = make(name, True)
    for role in roles:
        for text in ("85%", "▼0.12", "12 laps", "2.4 bar", "120 m", "Ab"):
            cased = text.upper() if role in widget._caps_roles else text
            assert widget.advance(role, cased) == widget.text_width(role, text)


# --- Request logs formatted only when logged
@pytest.mark.parametrize("module_name, handler_name", [("neopedal.web_dashboard", "DashboardHandler"),
                                                       ("neopedal.command_server", "CommandHandler")])
def test_request_log_formatted_only_when_debug(module_name, handler_name, monkeypatch):
    module = import_module(module_name)
    handler = getattr(module, handler_name)
    formatted = []

    class Line(str):
        """Request line argument: counted when formatted"""

        def __str__(self):
            formatted.append(1)
            return str.__str__(self)

    calls = []
    monkeypatch.setattr(module.logger, "debug", lambda *args: calls.append(args))
    monkeypatch.setattr(module.logger, "level", logging.INFO)
    monkeypatch.setattr(module.logger, "isEnabledFor", lambda level: level >= logging.INFO)
    handler.log_message(None, "%s %s", Line("GET /?code=secret HTTP/1.1"), "200")
    assert not calls and not formatted  # not formatted nor logged
    monkeypatch.setattr(module.logger, "isEnabledFor", lambda level: True)
    handler.log_message(None, "%s %s", Line("GET /?code=secret HTTP/1.1"), "200")
    assert len(calls) == 1 and formatted
    if module_name.endswith("web_dashboard"):
        assert "secret" not in calls[0][1]  # access code still redacted


# --- class_key cached
def test_class_key_cached():
    from neopedal.module.module_relative import class_key, class_order_rank

    class_key.cache_clear()
    assert class_key("LMP2 ELMS") == class_key("lmp2_elms") == class_key("LMP2-ELMS") == "lmp2elms"
    for _ in range(3):
        class_key("LMP2 ELMS")
    assert class_key.cache_info().hits >= 3 and class_key.cache_info().maxsize == 64
    assert class_order_rank("Hypercar, LMP2 ELMS, lmp2_elms, GT3") == {"hypercar": 0, "lmp2elms": 1, "gt3": 2}


# --- Lap Library: rename, delete & undo on a worker thread
@pytest.fixture
def library(ui_env, monkeypatch):
    """Imported laps library panel of a lap viewer (backend.library), listed; page changes recorded"""
    from neopedal.ui.lap_viewer import LapViewer
    from tests.test_lap_library import import_log, wait_library

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    import_log(cfg.path.telemetry, "Spa race", [139.5, 138.2])
    viewer = LapViewer(None)
    page = viewer.backend.library
    changes: list[dict] = []
    real_changed = viewer.backend.library_changed
    monkeypatch.setattr(viewer.backend, "library_changed", lambda moved: (changes.append(moved), real_changed(moved)))
    page.changes = changes
    page.viewer = viewer
    page.open()
    wait_library(page)
    yield page
    if shiboken6.isValid(viewer):
        viewer.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def held_job(monkeypatch, module, name: str):
    """Library file function held on its worker thread until released: (gate, threads it ran on)"""
    gate = threading.Event()
    threads: list[str] = []
    real = getattr(module, name)

    def held(*args, **kwargs):
        threads.append(threading.current_thread().name)
        assert gate.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, held)
    return gate, threads


def wait_until(check, timeout: float = 10.0):
    end = time.monotonic() + timeout
    while not check() and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    assert check()


def group_row(library) -> dict:
    return dict(library.model.rows[0])


def test_rename_in_background_buttons_disabled_and_single_run(library, monkeypatch):
    from neopedal.ui.quick import lap_library_panel
    from tests.test_lap_library import wait_library

    gate, threads = held_job(monkeypatch, lap_library_panel, "rename_group")
    assert library.rename("Spa race", "Spa best")  # name taken at once, rename runs on a worker thread
    wait_until(lambda: threads)
    assert threads[0] != threading.current_thread().name
    assert library.property("writing")  # rename & delete disabled (panel buttons)
    assert library.is_refreshing()
    assert not library.rename("Spa race", "Other")  # asked again: nothing while a write runs
    library.select(group_row(library)["key"], "set")
    library.deleteSelected()
    assert len(threads) == 1
    gate.set()
    wait_library(library)
    assert not library.property("writing")
    assert group_row(library)["title"] == "Spa best"
    assert len(library.changes) == 1 and all("Spa best" in new for new in library.changes[0].values())


def test_rename_error_told_once_done(library, monkeypatch):
    from neopedal.ui.quick import lap_library_panel
    from tests.test_lap_library import wait_library

    def refused(*args):
        raise PermissionError(13, "file in use")

    monkeypatch.setattr(lap_library_panel, "rename_group", refused)
    assert library.rename("Spa race", "Spa best")
    wait_library(library)
    assert "file in use" in library.property("problem") and not library.changes
    assert not library.property("writing") and group_row(library)["title"] == "Spa race"


def test_delete_and_undo_in_background(library, monkeypatch):
    from neopedal.ui.quick import lap_library_panel
    from tests.test_lap_library import wait_library

    backend = library.viewer.backend
    gate, threads = held_job(monkeypatch, lap_library_panel, "delete_laps")
    paths = [row["path"] for row in library.model.rows if row["kind"] == "lap"]
    library.select(paths[0], "set")
    library.deleteSelected()
    wait_until(lambda: threads)
    assert threads[0] != threading.current_thread().name and library.property("writing")
    assert os.path.exists(paths[0])  # held: not moved yet
    gate.set()
    wait_library(library)
    assert not os.path.exists(paths[0]) and library.changes == [{paths[0]: ""}]
    assert backend.undoText != ""  # one undo with recorded laps (page toast, Ctrl+Z)
    assert group_row(library)["count"] == 1

    backend.undoDelete()
    backend.undoDelete()  # twice: restored once
    assert backend.undoText == ""
    wait_library(library)
    assert os.path.exists(paths[0]) and group_row(library)["count"] == 2


def test_library_closed_before_rename_done_viewer_still_told(library, monkeypatch):
    from neopedal.ui.quick import lap_library_panel

    gate, threads = held_job(monkeypatch, lap_library_panel, "rename_group")
    assert library.rename("Spa race", "Spa best")
    wait_until(lambda: threads)
    library.closed()  # panel closed: page still told of moved laps once done
    gate.set()
    wait_until(lambda: library.changes)
    assert all("Spa best" in new for new in library.changes[0].values())
    wait_until(lambda: not lap_library_panel.file_jobs().running)

