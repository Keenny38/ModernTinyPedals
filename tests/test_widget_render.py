"""Visual regression test: render every overlay widget (classic & modern style)

Rendered images are saved to "tests/_render/" (uploaded as CI artifact) for visual review.
Test fails if a widget raises error, renders empty, or modern style clips widget size badly.
"""

import os
import pkgutil
from importlib import import_module

import pytest
from PySide6.QtGui import QColor, QImage

from tinypedal.setting import cfg
from tinypedal.template.widget.modern import MODERN_DESIGNS
from tinypedal.userfile.json_setting import copy_setting
from tinypedal.widget._modern import create_widget

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "_render")
WIDGET_NAMES = sorted(
    module.name
    for module in pkgutil.iter_modules(import_module("tinypedal.widget").__path__)
    if not module.name.startswith("_")
)


@pytest.fixture(scope="module")
def default_setting(bundled_fonts):
    """Use factory default settings only (never read or write user files)"""
    from tinypedal.api_control import api

    cfg.default.set_default()
    backup = {name: getattr(cfg.user, name, None) for name in cfg.user.__slots__}
    for name in cfg.user.__slots__:
        setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)))
    try:
        api.connect()
        api.start()
    except Exception as error:  # shared memory not available on this platform
        pytest.skip(f"API not available: {error}")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    yield cfg
    api.stop()
    for name, value in backup.items():
        if value is not None:
            setattr(cfg.user, name, value)


def render(name: str, modern: bool) -> QImage:
    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
    widget.adjustSize()
    image = widget.grab().toImage()
    widget.deleteLater()
    return image


def is_blank(image: QImage) -> bool:
    """Check if image has no visible pixel (sampled)"""
    step = max(1, min(image.width(), image.height()) // 16)
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            if QColor(image.pixel(x, y)).alpha() > 0:
                return False
    return True


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    """Same system clock text in every render: visual diff compares renders of two commits"""
    from tinypedal.widget import session
    from tinypedal.widget._modern import session as modern_session

    for module in (session, modern_session):
        monkeypatch.setattr(module, "strftime", lambda fmt, *args: "15:04PM" if "%" in fmt else fmt)


@pytest.mark.parametrize("name", WIDGET_NAMES)
def test_render_widget(default_setting, name):
    classic = render(name, modern=False)
    modern = render(name, modern=True)
    classic.save(os.path.join(OUTPUT_DIR, f"{name}_classic.png"))
    modern.save(os.path.join(OUTPUT_DIR, f"{name}_modern.png"))
    if classic.width() <= 4 or classic.height() <= 4:
        pytest.skip("widget has no visible size without live data")
    assert not is_blank(modern), "modern style renders blank widget"
    if name in MODERN_DESIGNS:  # own layout (labels, panels): only a sane size
        assert 24 <= modern.width() <= 1600 and 16 <= modern.height() <= 1200
        return
    # Modern font is narrower, size should never collapse or explode compared to classic
    assert 0.4 < modern.width() / classic.width() < 2.0
    assert 0.4 < modern.height() / classic.height() < 2.0


def test_perf_monitor_wraps_mixin_events_once():
    """Update time of widgets whose timerEvent comes from a mixin (Black box) is recorded, once"""
    from tinypedal.widget._base import Overlay

    class Mixin:
        def timerEvent(self, event):
            return "mixin"

    class Widget(Mixin, Overlay):
        pass

    class SubWidget(Widget):
        pass

    assert getattr(Widget.timerEvent, "timed", False)
    assert Widget.timerEvent.__wrapped__ is Mixin.timerEvent
    assert SubWidget.timerEvent is Widget.timerEvent  # not wrapped twice


def test_visual_diff_tool(tmp_path):
    import sys

    from PySide6.QtGui import QColor, QImage

    sys.path.insert(0, "tools")
    from visual_diff import compare_folders, summary

    base, new, diff = tmp_path / "base", tmp_path / "new", tmp_path / "diff"
    base.mkdir()
    new.mkdir()
    for folder, color in ((base, "#000000"), (new, "#000000")):
        image = QImage(20, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        image.save(str(folder / "same.png"))
    changed = QImage(20, 10, QImage.Format.Format_ARGB32)
    changed.fill(QColor("#000000"))
    changed.save(str(base / "changed.png"))
    for x in range(10):
        changed.setPixelColor(x, 5, QColor("#FFFFFF"))
    changed.save(str(new / "changed.png"))
    QImage(30, 10, QImage.Format.Format_ARGB32).save(str(new / "added.png"))
    differences, added, removed = compare_folders(str(base), str(new), str(diff))
    assert [result.name for result in differences] == ["changed.png"]
    assert added == ["added.png"] and removed == []
    assert (diff / "changed.png").exists()
    assert "changed.png" in summary(differences, added, removed)
