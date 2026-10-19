"""Global overlay opacity (overlay style "overlay_opacity_percentage")

- Multiplies each overlay opacity: on screen (fade target), on stream (stream only & screen hidden), VR reads
  window opacity. Default 100 keeps each overlay opacity unchanged.
- Each overlay opacity option (preset, context menu) stays its own value, never saved multiplied.
"""

import math

import pytest

from neopedal import realtime_state
from neopedal.setting import cfg
from neopedal.stream_overlay import stream_opacity
from neopedal.template.option_limits import limit_error, option_limit
from neopedal.template.setting_global import GLOBAL_DEFAULT
from neopedal.widget._style import overlay_opacity_scale
from tests.test_audit_sweep_fixes import widgets  # noqa: F401


def test_default_keeps_overlay_opacity():
    assert GLOBAL_DEFAULT["overlay_style"]["overlay_opacity_percentage"] == 100
    assert overlay_opacity_scale(GLOBAL_DEFAULT["overlay_style"]) == 1.0
    assert overlay_opacity_scale({}) == 1.0  # config saved before the option existed


@pytest.mark.parametrize("percent, scale", [(80, 0.8), (100, 1.0), (10, 0.1), (5, 0.1), (150, 1.0), (0, 0.1)])
def test_percent_to_scale(percent, scale):
    assert overlay_opacity_scale({"overlay_opacity_percentage": percent}) == pytest.approx(scale)


@pytest.mark.parametrize("value", ["80", None, True, math.nan])
def test_invalid_percent_unchanged(value):
    assert overlay_opacity_scale({"overlay_opacity_percentage": value}) == 1.0


def test_range_registered():
    limit = option_limit("overlay_opacity_percentage")
    assert (limit.minimum, limit.maximum) == (10, 100)
    assert limit_error("overlay_opacity_percentage", 5)
    assert limit_error("overlay_opacity_percentage", 101)
    assert not limit_error("overlay_opacity_percentage", 80)


def test_listed_in_settings_page():
    from neopedal.ui.quick.settings_backend import CATEGORIES

    category = next(category for category in CATEGORIES if category.key == "overlay_style")
    assert "overlay_opacity_percentage" in [key for _, group in category.groups for key in group]


def test_overlay_opacity_multiplied_on_screen(widgets, monkeypatch):  # noqa: F811
    monkeypatch.setitem(cfg.user.config["overlay_style"], "overlay_opacity_percentage", 80)
    monkeypatch.setitem(cfg.user.config["overlay_style"], "enable_fade_animation", False)
    widget = widgets("timing", opacity=0.9)
    assert widget.screen_opacity() == pytest.approx(0.72)
    widget.apply_placement()  # applied without fade
    assert widget.windowOpacity() == pytest.approx(0.72, abs=0.01)
    assert cfg.user.setting["timing"]["opacity"] == 0.9  # own value kept, never saved multiplied


def test_stream_opacity_multiplied_while_screen_hidden(widgets, monkeypatch):  # noqa: F811
    monkeypatch.setitem(cfg.user.config["overlay_style"], "overlay_opacity_percentage", 50)
    widget = widgets("timing", opacity=0.8)
    monkeypatch.setattr(realtime_state, "screen_hidden", True)
    assert stream_opacity(widget) == pytest.approx(0.4)


def test_default_overlay_opacity_unchanged(widgets):  # noqa: F811
    widget = widgets("timing", opacity=0.9)
    assert widget.screen_opacity() == pytest.approx(0.9)
