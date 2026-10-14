"""Overlays repaint only when what they draw changes: radar, pedals, delta best, classic relative, table cells"""

from importlib import import_module

import pytest
from PySide6.QtCore import QTimerEvent

from neopedal import calculation as calc
from neopedal.module_info import minfo
from tests.test_modern_graphic_widgets import reader, render, widgets  # noqa: F401  (fixture)


def count_updates(monkeypatch, widget) -> list:
    """update() calls of widget (still repainting)"""
    calls: list = []
    original = widget.update

    def update(*args):
        calls.append(args)
        original(*args)

    monkeypatch.setattr(widget, "update", update)
    return calls


def tick(widget):
    """One update timer tick on new vehicle data"""
    minfo.vehicles.dataSetVersion = (minfo.vehicles.dataSetVersion or 0) + 1
    widget.timerEvent(QTimerEvent(0))


# --- Radar
@pytest.mark.parametrize("modern", [True, False])
def test_radar_repaints_only_when_cars_in_range_move(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("radar", modern=modern, enable_auto_hide=False, show_vehicle_orientation=True)
    cars = minfo.vehicles.dataSet
    for car in cars:
        car.relativeRotatedPositionX = car.relativeRotatedPositionY = 500.0  # out of range
    updates = count_updates(monkeypatch, widget)
    tick(widget)
    assert len(updates) == 1  # first data
    for _ in range(3):  # nobody in range: nothing new to draw
        tick(widget)
    assert len(updates) == 1
    car = next(car for car in cars if not car.isPlayer)
    half_pixel = 1 / (widget.global_scale * 2)  # meters
    car.relativeRotatedPositionX, car.relativeRotatedPositionY = 3.0, 10 * half_pixel
    tick(widget)
    assert len(updates) == 2
    car.relativeRotatedPositionY += 0.2 * half_pixel  # under half a pixel
    car.relativeOrientationRadians += 0.001  # under a degree
    tick(widget)
    assert len(updates) == 2
    car.relativeRotatedPositionY += 2 * half_pixel
    tick(widget)
    assert len(updates) == 3
    car.inPit = 1  # color
    tick(widget)
    assert len(updates) == 4
    image = render(widget)
    assert not image.isNull()


@pytest.mark.parametrize("modern", [True, False])
def test_radar_hidden_repaints_once(widgets, monkeypatch, modern):  # noqa: F811
    widget = widgets("radar", modern=modern, enable_auto_hide=True, enable_radar_fade=False)
    monkeypatch.setattr(minfo.vehicles, "nearestLine", 999.0)  # nobody near
    reader(monkeypatch, "timing", "elapsed", 100.0)
    updates = count_updates(monkeypatch, widget)
    tick(widget)
    reader(monkeypatch, "timing", "elapsed", 110.0)  # auto hide time passed
    tick(widget)
    assert not widget.show_radar
    count = len(updates)
    for _ in range(3):
        tick(widget)
    assert len(updates) == count


def test_radar_key_ignores_invalid_values(widgets):  # noqa: F811
    widget = widgets("radar", enable_auto_hide=False)
    car = next(car for car in minfo.vehicles.dataSet if not car.isPlayer)
    car.relativeRotatedPositionX, car.relativeRotatedPositionY = 2.0, 2.0
    car.relativeOrientationRadians = float("nan")
    assert widget.radar_key(1.0)  # no error


# --- Pedals
def pedal_inputs(monkeypatch, value: float):
    for name in ("throttle", "throttle_raw", "brake", "brake_raw", "clutch", "clutch_raw", "force_feedback"):
        reader(monkeypatch, "inputs", name, value)
    reader(monkeypatch, "brake", "pressure", (value,) * 4)


def test_pedal_sub_pixel_changes_never_repaint(widgets, monkeypatch):  # noqa: F811
    widget = widgets("pedal", show_brake_pressure=False)
    updates = count_updates(monkeypatch, widget)
    pedal_inputs(monkeypatch, 0.5)
    widget.timerEvent(QTimerEvent(0))
    assert len(updates) == 1
    track = widget.rects[widget.keys[0]][0]
    length = track.width() if widget.horizontal else track.height()
    state = widget.state
    pedal_inputs(monkeypatch, 0.5 + 0.3 / length)  # a third of a pixel
    widget.timerEvent(QTimerEvent(0))
    assert len(updates) == 1 and widget.state == state  # state drawn kept
    pedal_inputs(monkeypatch, 0.5 + 2 / length)
    widget.timerEvent(QTimerEvent(0))
    assert len(updates) == 2 and widget.state != state
    pedal_inputs(monkeypatch, float("nan"))
    widget.timerEvent(QTimerEvent(0))  # no error
    assert not render(widget).isNull()


# --- Delta best
def test_deltabest_repaints_on_displayed_change(widgets, monkeypatch):  # noqa: F811
    deltabest = import_module("neopedal.widget._modern.deltabest")
    monkeypatch.setattr(deltabest, "delta_shown", lambda source: True)
    monkeypatch.setattr(minfo.delta, "lapTimeCurrent", 60.0)
    widget = widgets("deltabest", decimal_places=2, show_game_deltabest_if_available=False,
                     show_invalid_lap_indicator=False, enable_animated_deltabest=True)
    source = f"delta{widget.source}"
    updates = count_updates(monkeypatch, widget)

    def show(delta: float):
        monkeypatch.setattr(minfo.delta, source, delta)
        widget.timerEvent(QTimerEvent(0))

    show(0.121)
    assert len(updates) == 1
    show(0.1212)  # same text, bar moved a fraction of a pixel
    assert len(updates) == 1 and widget.state[0] == 0.121
    show(0.128)  # "+0.13"
    assert len(updates) == 2
    show(-0.128)  # color & side
    assert len(updates) == 3
    show(float("inf"))
    assert widget.state[0] == 0.0


# --- Classic relative
def test_classic_relative_formats_once_changed(widgets, monkeypatch):  # noqa: F811
    widget = widgets("relative", modern=False)
    target = widget.bars_lpt[0]
    updates = count_updates(monkeypatch, target)
    widget.update_lpt(target, (True, 1, round(12.31, 1)), False, False, 1)
    assert target.text == f"PIT{12.31:>5.1f}" and len(updates) == 1
    widget.update_lpt(target, (True, 1, round(12.34, 1)), False, False, 1)  # same tenth
    assert len(updates) == 1
    widget.update_lpt(target, (True, 0, -1.0), False, False, 1)
    assert target.text == widget.set_laptime(-1.0)[:8]
    widget.update_lpt(target, (False, False, 95.123), False, False, 1)
    assert target.text == f"*{calc.sec2laptime_full(95.123)}"[:8]
    gap = widget.bars_gap[0]
    gap_updates = count_updates(monkeypatch, gap)
    widget.update_gap(gap, 1.2341, False, 1)
    text = gap.text
    widget.update_gap(gap, 1.2342, False, 1)  # same text
    assert len(gap_updates) == 1 and gap.text == text
    widget.update_gap(gap, 2.5, False, 1)
    assert len(gap_updates) == 2


def test_laptime_text_cached():
    calc.sec2laptime_full.cache_clear()
    assert calc.sec2laptime_full(95.1234) == "1:35.123" == calc.sec2laptime_full(95.1234)
    assert calc.sec2laptime_full.cache_info().hits == 1
    assert calc.sec2laptime_full(-0.0) == calc.sec2laptime_full(0.0) == "0:00.000"
    assert calc.sec2laptime_full(float("nan")) == "nan:000nan"  # as before cache (no error)
    assert calc.sec2laptime(61) == calc.sec2laptime(61.0) == "1:01.000"


# --- Table cells
def test_table_repaints_changed_cells_only(ui_env, bundled_fonts, monkeypatch):
    from neopedal.setting import cfg
    from tests.test_modern_table_rows import new_table, sample

    widget = new_table(cfg, "standings")
    field, context = sample(widget)
    widget.show_field(field, context)
    widget.grab()  # painted once: static layer made
    updates = count_updates(monkeypatch, widget)
    assert widget.refresh_rows(widget.state) is False
    car = field.vehicles[0]
    car.lastLapTime += 1.0
    widget.show_field(field, context)
    assert len(updates) == 1 and len(updates[0]) == 1
    rect = updates[0][0]
    column = next(index for index, column in enumerate(widget.table.columns) if column.key == "laptime")
    left = widget.table.x[column]
    assert rect.left() < left and rect.right() > left + widget.table.columns[column].width - 1
    assert rect.width() < widget.width() / 2 and rect.height() < widget.table.row_height + 4
    car.inPit = 1  # pit pill may overflow its cell: whole row
    widget.show_field(field, context)
    assert updates[-1][0].width() == widget.width()


# --- Bars & gauges: key with lengths in device pixels, drawn values unchanged
def test_gauge_tiles_repaint_on_visible_change(widgets, monkeypatch):  # noqa: F811
    widget = widgets("suspension_travel")
    if "travel_ratio" not in widget.keys:
        pytest.skip("travel ratio not shown")
    wheels = minfo.wheels
    for name, value in (("minSuspensionPosition", 0.0), ("maxSuspensionPosition", 0.1), ("motionRatio", 1.0),
                        ("currentSuspensionPosition", 0.05), ("staticSuspensionPosition", 0.05)):
        monkeypatch.setattr(wheels, name, [value] * 4)
    updates = count_updates(monkeypatch, widget)
    widget.timerEvent(QTimerEvent(0))
    assert len(updates) == 1
    state = widget.state
    for name in ("currentSuspensionPosition", "staticSuspensionPosition"):  # ratio 0.499: same texts, sub-pixel
        monkeypatch.setattr(wheels, name, [0.0501] * 4)
    widget.timerEvent(QTimerEvent(0))
    assert len(updates) == 1 and widget.state is state
    monkeypatch.setattr(wheels, "staticSuspensionPosition", [0.06] * 4)
    widget.timerEvent(QTimerEvent(0))
    assert len(updates) == 2


def test_stat_bar_key(widgets):  # noqa: F811
    from neopedal.widget._modern.stats import Value

    widget = widgets("differential")
    length = widget.slots[0].value.width()
    key = widget.pixel_key((Value("50%", bar=0.5), Value("-", bar=-1.0)), [length, length], "bar")
    assert key[0].text == "50%" and key[0].bar == round(0.5 * length) and key[1].bar < 0
    assert key == widget.pixel_key((Value("50%", bar=0.5 + 0.2 / length), Value("-")), [length, length], "bar")


def test_rivals_lap_time_formatted_once_changed(widgets, monkeypatch):  # noqa: F811
    from neopedal.widget.rivals import lap_time_key, pit_time_key

    widget = widgets("rivals", modern=False)
    target = widget.bars_lpt[0]
    widget.update_lpt(target, pit_time_key(1, 12.31), False, False, 1)
    assert target.text == f"PIT{12.31:>5.1f}"
    last = target.last
    widget.update_lpt(target, pit_time_key(1, 12.34), False, False, 1)  # same tenth: same data
    assert target.last is last
    widget.update_lpt(target, pit_time_key(0, 0.04), False, False, 1)
    assert target.text == "OUT  0.0"
    widget.update_lpt(target, lap_time_key(float("nan")), False, False, 1)
    assert target.text == widget.set_laptime(-1.0)[:8]
    widget.update_lpt(target, lap_time_key(95.123, False), False, False, 1)
    assert target.text == f"*{calc.sec2laptime_full(95.123)}"[:8]
