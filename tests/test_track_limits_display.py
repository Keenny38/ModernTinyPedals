"""Track limits points shown with the limit of the session in races (1.25/5), without outside races (no penalty)"""

from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.api_control import api
from neopedal.formatter import format_points
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget


def test_format_points():
    assert [format_points(value) for value in (1.25, 1.5, 5.0, 0.0, 2.333)] == ["1.25", "1.5", "5", "0", "2.33"]


@pytest.fixture
def laps_widget(ui_env, bundled_fonts, monkeypatch):
    created = []

    def make(modern: bool):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting["laps_and_position"].update(show_track_limits_points=True)
        widget = create_widget(import_module("neopedal.widget.laps_and_position"), cfg, "laps_and_position")
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize(("in_race", "limit", "expected"), [
    (True, 5.0, "1.25/5"), (True, 2.5, "1.25/2.5"), (True, 0.0, "1.25/"),
    (False, 5.0, "1.25/"),  # qualifying or practice: no penalty, limit not shown
])
def test_limit_shown_in_race_only(laps_widget, monkeypatch, modern, in_race, limit, expected):
    monkeypatch.setattr(api.read.session, "in_race", lambda: in_race)
    monkeypatch.setattr(api.read.session, "cut_points", lambda *args: 1.25)
    monkeypatch.setattr(api.read.session, "limits_points", lambda: limit)
    widget = laps_widget(modern)
    widget.timerEvent(None)
    if modern:
        text = next(value.text for value in widget.state if "/" in value.text and value.text.startswith("1.25"))
    else:
        text = widget.bar_cut_points.text.split()[-1]
    assert text.startswith(expected)
    if limit and in_race:
        assert text == expected
    else:
        assert text != "1.25/5"
