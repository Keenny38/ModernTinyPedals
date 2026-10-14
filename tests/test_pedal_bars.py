"""Pedal bars of pedal & trailing widgets: flashing alerts (TC, ABS, wheel lock & slip), trailing bar options"""

import pytest
from PySide6.QtGui import QColor

from neopedal.module_info import minfo
from neopedal.widget import _pedal_alert
from tests.test_modern_graphic_widgets import has_color, reader, update, widgets  # noqa: F401  fixture


@pytest.fixture
def inputs(monkeypatch):
    """Neutral inputs: throttle & brake pressed, no alert, flash in lit phase; returns setter of readers"""
    monkeypatch.setattr(_pedal_alert, "monotonic", lambda: 0.0)  # phase 0: lit
    monkeypatch.setattr(minfo.wheels, "slipRatio", [0.0, 0.0, 0.0, 0.0])
    values = {
        ("inputs", "throttle"): 0.6, ("inputs", "throttle_raw"): 0.6,
        ("inputs", "brake"): 0.5, ("inputs", "brake_raw"): 0.5,
        ("inputs", "clutch"): 0.0, ("inputs", "clutch_raw"): 0.0, ("inputs", "force_feedback"): 0.3,
        ("switch", "tc_active"): False, ("switch", "abs_active"): False,
    }

    def set_values(**changed):
        for key, value in changed.items():
            group, name = key.split("__")
            values[(group, name)] = value
        for (group, name), value in values.items():
            reader(monkeypatch, group, name, value)

    set_values()
    return set_values


TRAILING_BARS = {"show_pedal_bars": True, "show_inverted_trailing": True, "show_inverted_pedal": False}


def test_alerts_by_bar_priority_and_flash(widgets, inputs, monkeypatch):  # noqa: F811
    widget = widgets("pedal", show_wheel_slip_flash=True)
    keys = widget.keys
    alerts = dict(zip(keys, widget.read_alerts()))
    assert alerts["throttle"] == alerts["brake"] == "" == alerts["ffb"] == alerts["clutch"]
    inputs(switch__tc_active=True, switch__abs_active=True)
    alerts = dict(zip(keys, widget.read_alerts()))
    assert alerts["throttle"] == "tc_activation" and alerts["brake"] == "abs_activation"
    assert alerts["ffb"] == alerts["clutch"] == ""
    monkeypatch.setattr(_pedal_alert, "monotonic", lambda: widget.alert_interval * 1.5)  # off phase
    assert set(widget.read_alerts()) == {""}
    monkeypatch.setattr(_pedal_alert, "monotonic", lambda: 0.0)
    # Wheel lock & spin, below TC & ABS in priority
    inputs(switch__tc_active=False, switch__abs_active=False)
    monkeypatch.setattr(minfo.wheels, "slipRatio", [-0.5, 0.0, 0.2, 0.0])
    alerts = dict(zip(keys, widget.read_alerts()))
    assert alerts["throttle"] == "wheel_slip" and alerts["brake"] == "wheel_lock"
    inputs(inputs__brake_raw=0.0, inputs__throttle_raw=0.0)  # pedals released: no lock nor spin
    assert set(widget.read_alerts()) == {""}


def test_alerts_off_by_option(widgets, inputs):  # noqa: F811
    widget = widgets("pedal", show_tc_activation_flash=False, show_abs_activation_flash=False,
                     show_wheel_lock_flash=False, show_wheel_slip_flash=False)
    inputs(switch__tc_active=True, switch__abs_active=True)
    assert not widget.alerts_shown
    assert set(widget.read_alerts()) == {""}


def test_modern_pedal_flashes_alert_color(widgets, inputs):  # noqa: F811
    widget = widgets("pedal", show_ffb_meter=False, show_clutch=False, show_brake_pressure=False)
    image = update(widget)
    assert not has_color(image, widget.theme.blue)
    inputs(switch__abs_active=True)
    image = update(widget)
    assert ("abs_activation" in {pedal[2] for pedal in widget.state})
    assert has_color(image, widget.theme.blue)


def test_classic_pedal_flashes_alert_color(widgets, inputs, monkeypatch):  # noqa: F811
    widget = widgets("pedal", modern=False)
    update(widget)
    assert widget.bar_throttle.alert_color == "" and widget.bar_brake.alert_color == ""
    inputs(switch__tc_active=True)
    update(widget)
    assert widget.bar_throttle.alert_color == widget.wcfg["tc_activation_color"]
    assert widget.bar_brake.alert_color == ""
    monkeypatch.setattr(_pedal_alert, "monotonic", lambda: widget.alert_interval * 1.5)
    update(widget)
    assert widget.bar_throttle.alert_color == ""


@pytest.mark.parametrize("modern", (True, False))
def test_trailing_bar_options(widgets, inputs, modern):  # noqa: F811
    plain = widgets("trailing", modern=modern, show_pedal_bars=False)
    shown = widgets("trailing", modern=modern, **TRAILING_BARS)
    assert plain.bar_keys == ()
    assert shown.bar_keys == ("ffb", "clutch", "brake", "throttle")
    assert shown.width() > plain.width()
    fewer = widgets("trailing", modern=modern, show_clutch_bar=False, show_ffb_bar=False, show_throttle=False,
                    **TRAILING_BARS)
    assert fewer.bar_keys == ("brake", "throttle")  # bar shown without its plot
    assert fewer.width() < shown.width()
    wide = widgets("trailing", modern=modern, show_clutch_bar=False, show_ffb_bar=False, show_throttle=False,
                   pedal_bar_width_filtered=20, pedal_bar_gap=6, **TRAILING_BARS)
    assert wide.width() - fewer.width() >= 2 * 13 + 4 * (2 if not modern else 1)


@pytest.mark.parametrize("modern", (True, False))
def test_trailing_bars_alert_pressure_and_pause(widgets, inputs, monkeypatch, modern):  # noqa: F811
    clock = {"time": 0.0}
    reader(monkeypatch, "timing", "elapsed", lambda: clock["time"])
    widget = widgets("trailing", modern=modern, show_clutch_bar=False, show_ffb_bar=False,
                     show_pedal_bar_brake_pressure=True, **TRAILING_BARS)
    pressure = {"value": [2.0, 2.0, 1.0, 1.0]}
    reader(monkeypatch, "brake", "pressure", lambda: pressure["value"])
    clock["time"] += 0.02
    update(widget)
    bars = dict(zip(widget.bar_keys, widget.read_bars()))
    assert bars["brake"][0] == 1.0 and bars["throttle"][0] == 0.6  # pressure share of peak
    pressure["value"] = [1.0, 1.0, 0.5, 0.5]
    assert dict(zip(widget.bar_keys, widget.read_bars()))["brake"][0] == 0.5
    widget.post_update()  # next car: peak found again
    assert dict(zip(widget.bar_keys, widget.read_bars()))["brake"][0] == 1.0
    # Plot paused (time unchanged): bars still follow inputs & alerts
    update(widget)
    update(widget)
    inputs(switch__abs_active=True)
    image = update(widget)
    if modern:
        assert widget.state[1][0][2] == "abs_activation"
        assert has_color(image, widget.theme.blue)
    else:
        assert widget.bar_values[0][2] == "abs_activation"
        assert has_color(image, QColor(widget.wcfg["abs_activation_color"]))


def test_classic_trailing_bar_layout(widgets, inputs):  # noqa: F811
    right = widgets("trailing", modern=False, **TRAILING_BARS)
    assert right.rect_bars.left() == right.area_width and right.chart_offset == 0
    left = widgets("trailing", modern=False, show_pedal_bars=True, show_inverted_trailing=False)
    assert left.rect_bars.left() == 0 and left.chart_offset == left.rect_bars.width()
    assert left.rect_viewport.left() == left.chart_offset


@pytest.mark.parametrize("modern", (True, False))
@pytest.mark.parametrize("inverted", (False, True))
def test_trailing_bar_readings_and_maximum_indicator(widgets, inputs, modern, inverted):  # noqa: F811
    options = {"show_pedal_bars": True, "show_inverted_pedal": inverted, "show_pedal_bar_readings": False,
               "pedal_bar_maximum_indicator_height": 0}
    plain = widgets("trailing", modern=modern, **options)
    shown = widgets("trailing", modern=modern, **{
        **options, "show_pedal_bar_readings": True, "pedal_bar_maximum_indicator_height": 6})
    assert shown.height() > plain.height()  # room for readings & indicator
    assert shown.width() >= plain.width()  # columns fit readings
    full_at_top = not inverted
    # Classic: reading rect moved by font vertical offset (glyphs placed as other classic overlays), larger on Linux
    offset = 0 if modern else abs(shown.get_font_metrics(shown.bar_font).voffset)
    for track, cap, reading in zip(shown.bar_tracks, shown.max_rects, shown.reading_rects):
        assert cap.height() == 6
        assert (cap.bottom() <= track.top()) if full_at_top else (cap.top() >= track.bottom())
        assert ((reading.top() >= track.bottom() - 1 - offset) if full_at_top
                else (reading.bottom() <= track.top() + 1 + offset))
        assert cap.top() >= 0 and cap.bottom() <= shown.height()
        assert reading.top() >= -2 and reading.bottom() <= shown.height() + 2  # classic: font vertical offset
    inputs(inputs__throttle=1.0, inputs__throttle_raw=1.0)
    image = update(shown)
    if modern:
        assert "100" in {bar[5] for bar in shown.state_key[1]}  # reading drawn
        assert any(bar[3] for bar in shown.state_key[1])  # full travel lights indicator
        assert has_color(image, shown.theme.positive)
    else:
        throttle = shown.bar_keys.index("throttle")
        cap = shown.max_rects[throttle]
        lit = image.pixelColor(int(cap.center().x()), int(cap.center().y()))
        assert lit == QColor(shown.wcfg["throttle_color"])
