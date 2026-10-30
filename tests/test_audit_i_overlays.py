"""Audit I, lot C (overlay rendering, edit mode, overlay control): BUG-006, 018, 029, 030, 031, 047 &
PERF-005, 034, 035, 036, 061, 062"""

import inspect
import threading
import time
from math import inf
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtGui import QColor, QKeyEvent

from neopedal.widget import _edit_mode
from tests.test_overlay_edit_mode import editing  # noqa: F401  (fixture)


def key(widget, code):
    QCoreApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier))


def process_events(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


class Cell:
    """Painter cell stand-in: text, colors & repaint count"""

    def __init__(self, last=None, decimals=1, show_reading=True):
        self.last = last
        self.decimals = decimals
        self.show_reading = show_reading
        self.text = ""
        self.fg = ""
        self.bg = ""
        self.paints = 0
        self.inputs: list = []

    def update(self):
        self.paints += 1

    def update_input(self, value):
        self.inputs.append(value)


# BUG-006: handle resize keeps options at 0 (hidden part), scales the others
def test_resize_keeps_zero_sized_options():
    from neopedal.widget._edit_frame import scale_widget_setting

    setting = {"font_size": 10, "bar_height": 0, "mark_bar_width": 0.0, "led_width": 3, "enable": True}
    changed = scale_widget_setting(setting, 2.0, "pedal")
    assert setting["font_size"] == 20 and setting["led_width"] == 6
    assert setting["bar_height"] == 0 and setting["mark_bar_width"] == 0.0  # hidden parts stay hidden
    assert "bar_height" not in changed and setting["enable"] is True


# BUG-018: overlay turned on during the test on screen reads the simulated session too
def test_overlay_test_patches_modules_loaded_later(ui_env, bundled_fonts, monkeypatch):
    from importlib import import_module

    from neopedal.api_control import api
    from neopedal.setting import cfg
    from neopedal.ui import overlay_test
    from neopedal.widget._modern import create_widget, flag

    widget = create_widget(import_module("neopedal.widget.flag"), cfg, "flag")
    monkeypatch.setattr(overlay_test, "overlays", lambda: [widget])
    test = overlay_test.overlay_test()
    try:
        test.start("pits", seconds=60)
        assert flag.api is not api
        flag.api = api  # as a widget module imported after the test started (not patched at start)
        test._update()  # next tick
        assert flag.api is not api, "module loaded during test left on game data"
        test.stop()
        assert flag.api is api  # restored with the others
    finally:
        test.stop(refresh=False)
        widget.deleteLater()
        QCoreApplication.processEvents()


# BUG-029: performance monitor records from several threads without losing samples
def test_perf_monitor_records_from_threads():
    from neopedal.perf_monitor import PerfMonitor

    PerfMonitor.reset()
    count, threads = 2000, 4

    def record():
        for _ in range(count):
            PerfMonitor.record("python", "garbage collection", 0.001)

    workers = [threading.Thread(target=record) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    stats = {(item.name, item.event): item for item in PerfMonitor.stats()}
    assert stats[("python", "garbage collection")].calls == count * threads
    assert isinstance(PerfMonitor._lock, type(threading.Lock()))
    PerfMonitor.reset()


# BUG-030: auto hide toggle wakes the control thread (state read & signalled at once, not after FROZEN_WAIT)
def test_auto_hide_toggle_wakes_overlay_control(ui_env):
    from neopedal.overlay_control import OverlayControl, OverlayToggle, octrl
    from neopedal.setting import cfg

    control = OverlayControl()
    before = cfg.overlay["auto_hide"]
    assert not control._wake.is_set()
    control.toggle.hide()
    assert cfg.overlay["auto_hide"] is not before and control._wake.is_set()
    control.toggle.hide()
    assert cfg.overlay["auto_hide"] is before
    OverlayToggle().hide()  # no control (tests): toggles only
    assert cfg.overlay["auto_hide"] is not before
    # Hotkey command goes through the app control
    from neopedal.hotkey import command

    octrl._wake.clear()
    command.hotkey_overlay_auto_hide()
    assert cfg.overlay["auto_hide"] is before and octrl._wake.is_set()
    octrl._wake.clear()


def test_frozen_wait_ends_on_wake(ui_env, monkeypatch):
    """Control loop waiting FROZEN_WAIT (game data frozen, overlays hidden) reads state again once woken"""
    from neopedal import overlay_control, realtime_state
    from neopedal.api_control import api
    from neopedal.overlay_control import OverlayControl

    for name in ("active", "shown", "paused", "resets", "hidden", "screen_hidden", "session_type", "in_pits"):
        monkeypatch.setattr(realtime_state, name, getattr(realtime_state, name))
    monkeypatch.setattr(overlay_control, "overlay_signal", SimpleNamespace(**{
        name: SimpleNamespace(emit=lambda *args: None) for name in ("hidden", "context", "locked", "paused")}))
    monkeypatch.setattr(overlay_control, "stream_on_air", lambda: False)
    monkeypatch.setattr(overlay_control, "FROZEN_WAIT", 30.0)
    monkeypatch.setattr(overlay_control, "UPDATE_INTERVAL", 0.01)
    reads = []
    monkeypatch.setattr(api.read.state, "active", lambda: False, raising=False)
    monkeypatch.setattr(api.read.state, "paused", lambda: reads.append(1) or True, raising=False)
    monkeypatch.setattr(api.read.state, "resets", lambda: 0, raising=False)
    monkeypatch.setattr(api.read.vehicle, "total_vehicles", lambda: 0, raising=False)
    control = OverlayControl()
    wake = threading.Event()
    thread = threading.Thread(
        target=control._OverlayControl__update_loop, args=(control._event, wake), daemon=True)
    monkeypatch.setattr(control, "_wake", wake)
    thread.start()
    try:
        process_events(0.2)  # second iteration waits FROZEN_WAIT
        state_reads = len(reads)
        control.toggle.hide()
        process_events(0.2)
        assert len(reads) > state_reads, "auto hide toggle did not wake the frozen wait"
    finally:
        control._event.set()
        wake.set()
        thread.join(2)
    assert not thread.is_alive()


# BUG-031: toolbar overlay count follows an overlay turned off while another one is selected
def test_toolbar_count_follows_overlay_turned_off(editing):  # noqa: F811
    start, overlays, _saved = editing
    widget = start()
    other = start("gear", pos=(600, 300))
    controller = _edit_mode.edit_mode()
    assert controller.enter()
    toolbar = controller.toolbar
    assert toolbar.detail == "2 overlays"
    controller.select("speedometer")
    del overlays["gear"]  # out of active overlays, then stopped (module control order)
    other.stop()
    controller.select("")
    assert toolbar.detail == "1 overlay"
    assert widget.isVisible()


# BUG-047: session best lap never reads a slot past the field after a car left
def test_session_best_lap_bounds_index_before_reading(monkeypatch):
    from neopedal.widget import _common
    from neopedal.widget._common import SessionBestLap

    total = [3]
    read = []
    api = SimpleNamespace(read=SimpleNamespace(
        session=SimpleNamespace(identifier=lambda: (1, 0, 0), elapsed=lambda: 100.0),
        vehicle=SimpleNamespace(total_vehicles=lambda: total[0], same_class=lambda index: True),
        timing=SimpleNamespace(best_laptime=lambda index: read.append(index) or 90.0 + index),
    ))
    monkeypatch.setattr(_common, "api", api)
    best = SessionBestLap()
    best.update(False)
    best.update(False)
    assert read == [0, 1]
    total[0] = 2  # last car left
    best.update(False)
    assert read == [0, 1, 0], "stale slot of the car that left was read"
    assert best.update(False) == 90.0


# PERF-005: cells drawn again once their text (and color) changes, not on every change of the raw value
def test_consumption_cell_repaints_on_text_change_only():
    from neopedal.widget._consumption import ConsumptionBars

    widget = SimpleNamespace(bar_width=6)
    cell = Cell(decimals=1)
    update = ConsumptionBars.update_value
    update(widget, cell, 10.01, "#300")
    update(widget, cell, 10.04, "#300")  # same text "10.0"
    assert cell.text == "10.0" and cell.paints == 1 and cell.bg == "#300"
    update(widget, cell, 10.06, "#300")  # "10.1"
    assert cell.paints == 2
    update(widget, cell, 10.06, "#900")  # low amount warning color
    assert cell.paints == 3 and cell.bg == "#900"
    update(widget, cell, -0.01, None, "+")
    assert cell.text == "+0.0" and cell.paints == 4  # never "-0.0"


def test_tyre_wear_cell_repaints_on_text_change_only():
    from neopedal.widget._wear import WearSections

    cell = Cell(last=0)
    style = ("#FFF", "#F00")
    WearSections.show_wear(cell, 85.123, style, False)
    WearSections.show_wear(cell, 85.127, style, False)  # same "85.1"
    assert cell.text == "85.1" and cell.paints == 1 and cell.fg == "#FFF"
    WearSections.show_wear(cell, 85.127, style, True)  # warning color
    assert cell.paints == 2 and cell.fg == "#F00"
    WearSections.show_wear(cell, 84.9, style, True)
    assert cell.text == "84.9" and cell.paints == 3
    # Brake wear keeps set_wear: value is the key, failure text
    WearSections.set_wear(cell, 50.0, style, False, failed=True)
    assert cell.text == "FAIL" and cell.last == 50.0


def test_rain_chance_bar_repaints_on_visible_change_only():
    from neopedal.widget.weather_forecast import Realtime

    widget = SimpleNamespace()
    cell = Cell()
    Realtime.update_rain_chance(widget, cell, 0.50004)
    Realtime.update_rain_chance(widget, cell, 0.50008)  # moved by less than 0.1%
    assert cell.inputs == [0.50004] and cell.text == "50%"
    Realtime.update_rain_chance(widget, cell, 0.5012)
    assert len(cell.inputs) == 2


def test_table_columns_repaint_on_text_change_only():
    from neopedal.widget._columns import DriverTable

    shown = []
    widget = SimpleNamespace(
        blank_state=-1,
        bar_style_stl=[("#1", "#a"), ("#2", "#b")],
        bar_style_lic=[("#1", "#a"), ("#2", "#b"), ("#3", "#c")],
        bar_style_nrg=[("#0", "#a"), ("#1", "#b"), ("#2", "#c"), ("#3", "#d"), ("#4", "#e")],
        bar_style_dmg=[("#0", "#a"), ("#1", "#b"), ("#2", "#c"), ("#3", "#d")],
        nrg_width=4, nrg_decimals=0,
        wcfg={"lift_and_coast_reset_threshold": 3.0, "lift_and_coast_highlight_threshold": 1.0},
        toggle_visibility=lambda target, state: shown.append(state),
    )
    cell = Cell()
    DriverTable.update_stl(widget, cell, 3, 12.31, 0, 1)
    DriverTable.update_stl(widget, cell, 3, 12.84, 0, 1)  # estimate moved, "03/12" unchanged
    assert cell.text == "03/12" and shown == [1]
    DriverTable.update_stl(widget, cell, 3, 13.02, 0, 1)
    assert cell.text == "03/13" and shown == [1, 1]
    cell, shown[:] = Cell(), []
    DriverTable.update_lic(widget, cell, 2.51, 0.0, False, 1)
    DriverTable.update_lic(widget, cell, 2.54, 0.0, False, 1)  # "2.5s" unchanged
    assert cell.text == "2.5s" and cell.fg == "#2" and shown == [1]
    DriverTable.update_lic(widget, cell, 2.54, 0.0, True, 1)  # highlighted player
    assert cell.fg == "#3" and shown == [1, 1]
    cell, shown[:] = Cell(), []
    DriverTable.update_nrg(widget, cell, 0.5531, False, 1)
    DriverTable.update_nrg(widget, cell, 0.5549, False, 1)  # "055%" unchanged
    assert cell.text == "055%" and shown == [1]
    DriverTable.update_nrg(widget, cell, 0.0949, False, 1)  # 10% left: warning color
    assert cell.text == "009%" and cell.fg == "#3" and shown == [1, 1]
    cell, shown[:] = Cell(), []
    DriverTable.update_dmg(widget, cell, 0.731, False, 1)
    DriverTable.update_dmg(widget, cell, 0.739, False, 1)  # same tenth
    assert cell.text == "7" and shown == [1]
    DriverTable.update_dmg(widget, cell, 0.69, False, 1)
    assert cell.text == "6" and shown == [1, 1]


# PERF-034: color strings parsed once (flat style fills)
def test_color_strings_parsed_once():
    from neopedal.widget._painter import _qcolor, as_color

    red = as_color("#FF0000")
    assert isinstance(red, QColor) and red == QColor("#FF0000")
    assert as_color("#FF0000") is red and _qcolor.cache_info().hits >= 1
    assert as_color(Qt.GlobalColor.transparent) is Qt.GlobalColor.transparent
    color = QColor("#00FF00")
    assert as_color(color) is color


# PERF-035: arrow key press refreshes the toolbar once, title area only (fixed tooltips built with the style)
def test_arrow_key_refreshes_toolbar_once_title_only(editing, monkeypatch):  # noqa: F811
    from neopedal.widget._edit_toolbar import EditToolbar

    start, _overlays, _saved = editing
    widget = start()
    controller = _edit_mode.edit_mode()
    assert controller.enter()
    toolbar = controller.toolbar
    assert next(item for item in toolbar.items if item.key == "snap").tip  # fixed tip set with style
    controller.select("speedometer")
    refreshes = []
    original_refresh = EditToolbar.refresh
    monkeypatch.setattr(EditToolbar, "refresh", lambda self: (refreshes.append(1), original_refresh(self)))
    key(widget, Qt.Key.Key_Right)  # undo becomes enabled: whole bar drawn again
    assert len(refreshes) == 1
    updates = []
    monkeypatch.setattr(toolbar, "update", lambda *args: updates.append(args))
    key(widget, Qt.Key.Key_Right)
    assert len(refreshes) == 2
    assert updates and all(len(args) == 1 and isinstance(args[0], QRect) for args in updates)  # title area only
    assert toolbar.detail.startswith(f"X {widget.x()}")
    undo = next(item for item in toolbar.items if item.key == "undo")
    assert undo.enabled and "Move" in undo.tip


# PERF-036: strength of field of classes read again once a second, not on every update
def test_class_levels_cached_between_reads(monkeypatch):
    from neopedal import rank_info
    from neopedal.widget._modern import standings

    calls = []
    monkeypatch.setattr(rank_info, "field_level", lambda names: calls.append(tuple(names)) or len(names))
    clock = [100.0]
    monkeypatch.setattr(standings, "monotonic", lambda: clock[0])
    widget = SimpleNamespace(demo=False, levels_cache=(-inf, -1, {}))
    cars = [SimpleNamespace(driverName=f"D{index}", vehicleClass="GT3" if index < 3 else "LMP2")
            for index in range(5)]
    levels = standings.Realtime.class_levels(widget, cars)
    assert levels == {"GT3": 3, "LMP2": 2} and len(calls) == 2
    clock[0] += 0.5
    assert standings.Realtime.class_levels(widget, cars) is levels and len(calls) == 2
    assert standings.Realtime.class_levels(widget, cars[:4]) == {"GT3": 3, "LMP2": 1}  # car left: read again
    clock[0] += 1.1
    standings.Realtime.class_levels(widget, cars[:4])
    assert len(calls) == 6


# PERF-061: paint serial counted in paint, move, size, show & hide handlers, no event() override
def test_paint_serial_counted_without_event_override(ui_env, bundled_fonts, monkeypatch):
    from importlib import import_module

    from neopedal import realtime_state
    from neopedal.setting import cfg
    from neopedal.widget._base import Base, PaintCounter
    from neopedal.widget._modern import create_widget

    assert "event" not in Base.__dict__
    monkeypatch.setattr(realtime_state, "active", True)
    cfg.overlay["auto_hide"] = False
    cfg.overlay["fixed_position"] = True
    for name in ("gear", "fuel"):  # overlay drawing itself (modern) & overlay of cells (classic)
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if name == "gear" else "Legacy Dark"
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        try:
            widget.start()
            for _ in range(30):
                process_events(0.1)
                if "paint_serial" in widget.__dict__:
                    break
            serial = widget.paint_serial
            assert serial <= PaintCounter.count
            process_events(0.05)
            widget.update()
            process_events(0.05)
            assert widget.paint_serial > serial, name
            serial = widget.paint_serial
            widget.move(widget.x() + 5, widget.y())
            QCoreApplication.processEvents()
            assert widget.paint_serial > serial, name
            serial = widget.paint_serial
            widget.hide()
            QCoreApplication.processEvents()
            assert widget.paint_serial > serial, name
        finally:
            widget.stop()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert "paint_serial" not in widget.__dict__  # not set again after stop: seen closed


# PERF-062: no import statement on the per cell logo path, modules looked up (replaced by tests)
def test_logo_path_imports_once():
    from neopedal.userfile import custom_image, game_images
    from neopedal.widget._modern import table

    for method in (table.TableMixin.brand_logo, table.TableMixin.logos_arrived):
        assert "import" not in inspect.getsource(method)
    assert table.custom_image is custom_image and table.game_images is game_images
