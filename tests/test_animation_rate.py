"""Animation step follows the refresh rate of the main window screen"""

import sys
import time

import pytest
from PySide6.QtCore import QVariantAnimation
from PySide6.QtWidgets import QApplication, QWidget

from neopedal.ui import animation_rate
from neopedal.ui.animation_rate import DEFAULT_INTERVAL, AnimationRate, interval_for


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(("refresh", "interval"), [
    (0.0, DEFAULT_INTERVAL), (float("nan"), DEFAULT_INTERVAL), (-1.0, DEFAULT_INTERVAL),
    (30.0, 16), (59.94, 16), (60.0, 16), (75.0, 13), (120.0, 8), (144.0, 7), (165.0, 6), (240.0, 4), (360.0, 4),
])
def test_interval_for(refresh, interval):
    assert interval_for(refresh) == interval


def test_follows_window_screen(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(animation_rate, "_load_setter", lambda: calls.append)
    window = QWidget()
    try:
        rate = AnimationRate(window)
        screen = window.screen()
        expected = interval_for(screen.refreshRate())
        assert rate.interval == expected
        assert calls == ([] if expected == DEFAULT_INTERVAL else [expected])
        rate.follow_screen(screen)  # same screen: nothing set again
        assert len(calls) == (0 if expected == DEFAULT_INTERVAL else 1)
        rate.follow_screen(None)  # screen gone: Qt default
        assert rate.interval == DEFAULT_INTERVAL
        assert calls[-1:] == ([] if expected == DEFAULT_INTERVAL else [DEFAULT_INTERVAL])
    finally:
        window.deleteLater()


def test_unavailable_setter_keeps_default(qapp, monkeypatch):
    monkeypatch.setattr(animation_rate, "_load_setter", lambda: None)
    window = QWidget()
    try:
        rate = AnimationRate(window)
        rate.apply()
        assert rate.interval == DEFAULT_INTERVAL
    finally:
        window.deleteLater()


@pytest.mark.skipif(sys.platform != "win32", reason="Qt Core exports looked up on Windows only")
def test_setter_changes_qt_animation_step(qapp):
    setter = animation_rate._load_setter()
    assert setter is not None  # PySide6 Qt Core exports QUnifiedTimer (64-bit MSVC build)
    steps = []
    animation = QVariantAnimation()
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setDuration(400)
    animation.valueChanged.connect(lambda _: steps.append(time.perf_counter()))
    try:
        setter(4)
        animation.start()
        deadline = time.perf_counter() + 0.3
        while time.perf_counter() < deadline:
            qapp.processEvents()
        # default 16 ms step: about 18 steps in 300 ms, 4 ms step: well above
        assert len(steps) > 24
    finally:
        animation.stop()
        setter(DEFAULT_INTERVAL)
