"""Overlays on screen shown a few seconds in a race situation of the simulated session (Overlay Options)"""

from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.setting import cfg


@pytest.fixture
def running_flag(ui_env, bundled_fonts, monkeypatch):
    """Flag overlay (modern) running, listed as active"""
    from neopedal.ui import overlay_test
    from neopedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    widget = create_widget(import_module("neopedal.widget.flag"), cfg, "flag")
    monkeypatch.setattr(overlay_test, "overlays", lambda: [widget])
    yield widget
    overlay_test.overlay_test().stop(refresh=False)
    widget.deleteLater()
    QCoreApplication.processEvents()


def test_overlays_read_simulated_situation_then_game_again(running_flag):
    from neopedal.api_control import api
    from neopedal.ui.overlay_test import overlay_test
    from neopedal.widget._modern import flag

    test = overlay_test()
    events = []
    test.changed.connect(lambda: events.append(test.running))
    test.start("pits", seconds=60)
    assert test.running and flag.api is not api  # simulated session read
    captions = {chip.caption for chip in running_flag.state}
    assert running_flag.captions["limiter"] in captions  # limiter on in pit lane
    test.stop()
    assert not test.running and flag.api is api and events == [True, False]


def test_test_ends_by_itself(running_flag, monkeypatch):
    from neopedal.ui.overlay_test import overlay_test

    test = overlay_test()
    test.start("flags", seconds=0.01)
    assert test._end.isActive()
    test._end.timeout.emit()
    assert not test.running


def test_page_button_starts_and_stops_test(running_flag, monkeypatch):
    from neopedal.demo_data import SCENARIOS
    from neopedal.ui.quick.overlay_options_backend import OverlayOptionsBackend
    from tests.test_overlay_options import Control, Host

    host = Host()
    backend = OverlayOptionsBackend(None, host, Control())
    backend.host = host
    try:
        backend.setPreviewScenario(SCENARIOS.index("damage"))
        backend.testOnScreen()
        assert backend.testing and host.notices
        backend.testOnScreen()  # again: stopped
        assert not backend.testing
    finally:
        backend.close()
        backend.deleteLater()
