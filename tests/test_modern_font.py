"""Overlay style font options on modern design overlays: modern font on (design font for text,
modern monospace font for values), off (widget font option for all text), applied on reload"""

import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFontMetricsF

from tests.test_settings_page import Host, flush
from tinypedal.setting import cfg
from tinypedal.widget._modern.base import design_font_family, is_value_text

MONO = "JetBrains Mono"
DESIGN = "Barlow Semi Condensed"


@pytest.fixture
def make(ui_env, bundled_fonts):
    """Build modern design widget with overlay style & widget options, deleted after test"""
    from importlib import import_module

    from tinypedal.widget._modern import create_widget

    cfg.overlay["fixed_position"] = True
    created = []

    def build(name: str, style: dict | None = None, **options):
        cfg.user.config["overlay_style"].update({"overlay_theme": "Modern Dark", **(style or {})})
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield build
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


@pytest.mark.parametrize("text", [
    "1:23.456", "+0.12", "-0.041", "88°", "1.850bar", "0 km/h", "73.36/~227.92 (+0)", "x1", "▲ 0.35",
    "55%", "15:47PM", "31.5 / 22.0°C ▲", "14/20", "3.80E",
])
def test_value_texts(text):
    assert is_value_text(text)


@pytest.mark.parametrize("text", ["M. Laurent", "Max 2.02", "GT3", "LMP2", "S1", "P2P", "Rubber 85%", "\u2013", "LAP", ""])
def test_label_texts(text):
    assert not is_value_text(text)


def test_modern_font_on_values_in_modern_font(make):
    widget = make("relative", {"enable_modern_font": True, "modern_font_name": MONO,
                               "modern_design_font_name": DESIGN}, font_name="DejaVu Sans")
    assert widget.font_family == DESIGN and widget.value_family == MONO
    for role in ("value", "strong", "small"):
        assert widget.text_font(role, "1:23.456").family() == MONO
        assert widget.text_font(role, "M. Laurent").family() == DESIGN
        # Widths & digit width measured with font drawing the text (columns fit, no clipping)
        mono = QFontMetricsF(widget.text_font(role, "1:23.456"))
        assert widget.text_width(role, "1:23.456") == mono.horizontalAdvance("1:23.456")
        assert widget.advance(role, "-0.041") == mono.horizontalAdvance("-0.041")
        assert widget.digit_width(role) == mono.horizontalAdvance("0")
        # Monospace digits: every value of same length is as wide
        assert widget.text_width(role, "1:11.111") == widget.text_width(role, "8:88.888")
        # Digits as tall as design text beside them
        design = QFontMetricsF(widget.fonts[role])
        assert mono.capHeight() == pytest.approx(design.capHeight(), rel=0.12)
    # Labels (caps) stay in design font, even numbers
    assert widget.text_font("label", "12").family() == DESIGN
    widget.adjustSize()
    assert not widget.grab().toImage().isNull()


def test_modern_font_on_draws_value_with_modern_font(make, monkeypatch):
    from PySide6.QtGui import QPainter, QPixmap

    widget = make("relative", {"enable_modern_font": True})
    used = []
    monkeypatch.setattr(QPainter, "setFont", lambda painter, font: used.append(font.family()))
    pixmap = QPixmap(200, 40)
    painter = QPainter(pixmap)
    from PySide6.QtCore import QRectF

    widget.draw_text(painter, QRectF(0, 0, 200, 20), "1:23.456", "value")
    widget.draw_text(painter, QRectF(0, 20, 200, 20), "M. Laurent", "value")
    painter.end()
    assert used == [MONO, design_font_family(cfg.user.config["overlay_style"])]


def test_modern_font_off_widget_font_for_all_text(make):
    widget = make("relative", {"enable_modern_font": False}, font_name="DejaVu Sans")
    assert widget.font_family == "DejaVu Sans" and widget.value_family == ""
    for role in ("value", "strong", "label"):
        assert widget.fonts[role].family() == "DejaVu Sans"
        assert widget.text_font(role, "1:23.456").family() == "DejaVu Sans"
        assert widget.font_role(role, "1:23.456") == role
    gear = make("gear", {"enable_modern_font": False}, font_name="DejaVu Sans")
    assert gear.fonts["gear"].family() == "DejaVu Sans"  # design's own family replaced too


def test_restyled_widget_font(make):
    """Restyled classic drawing (Black box): design font on, widget font option off"""
    on = make("black_box", {"enable_modern_font": True}, enable_auto_resize=False)
    assert on.wcfg["font_name"] == design_font_family(cfg.user.config["overlay_style"])
    off = make("black_box", {"enable_modern_font": False}, enable_auto_resize=False)
    assert off.wcfg["font_name"] == cfg.default.setting["black_box"]["font_name"]


def test_font_option_shown_when_modern_font_off(ui_env):
    from tinypedal.widget._modern import design_option_keys

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    keys = list(cfg.user.setting["relative"])
    cfg.user.config["overlay_style"]["enable_modern_font"] = True
    assert "font_name" not in design_option_keys(cfg, "relative", keys)
    cfg.user.config["overlay_style"]["enable_modern_font"] = False
    assert "font_name" in design_option_keys(cfg, "relative", keys)


def test_classic_layout_unchanged(make):
    """Classic layout widgets: modern font name on every font option left at default"""
    on = make("relative", {"enable_modern_font": True, "modern_font_name": MONO}, enable_classic_layout=True)
    assert type(on).__module__ == "tinypedal.widget.relative" and on.wcfg["font_name"] == MONO
    off = make("relative", {"enable_modern_font": False}, enable_classic_layout=True)
    assert off.wcfg["font_name"] == cfg.default.setting["relative"]["font_name"]


def test_font_options_applied_to_running_overlays(ui_env, bundled_fonts):
    """Overlay Style font options saved with Apply: overlays restarted (as at reload) in new fonts"""
    from tinypedal.module_control import wctrl
    from tinypedal.ui.quick.settings_backend import SettingsBackend

    host = Host()
    settings = SettingsBackend(None, host)
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    cfg.user.setting["relative"]["enable"] = True
    cfg.user.setting["relative"]["font_name"] = "DejaVu Sans"
    wctrl.start("relative")
    try:
        old = wctrl.active_modules["relative"]
        assert old.value_family == MONO and old.text_font("value", "1:23.456").family() == MONO
        settings.selectCategory("overlay_style")
        settings.setBool("overlay_style/enable_modern_font", False)
        assert settings.apply() and host.applied_sections == [{"overlay_style"}]
        start = time.monotonic()
        wctrl.close("relative")
        assert time.monotonic() - start < 5
        wctrl.start("relative")
        new = wctrl.active_modules["relative"]
        assert new.value_family == "" and new.font_family == "DejaVu Sans"
        assert new.text_font("value", "1:23.456").family() == "DejaVu Sans"
    finally:
        wctrl.close("relative")
        settings.deleteLater()
        flush()
