"""Laps and position & Session overlays: same laps left count (timed & lap races, both designs)

Timed race ends on crossing the line after the timer: both overlays round the finish lap up to a whole lap,
from the same completed laps & lap progress (game scoring). Widgets are built on default settings (ui_env) with a
neutral API reader. Nothing is ever asked to a real game.
"""

from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.api_control import api
from neopedal.module_info import minfo
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget


@pytest.fixture
def widgets(ui_env, bundled_fonts):
    """Build widgets by name (modern design unless modern=False), deleted after test"""
    created = []

    def make(name: str, modern: bool = True, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def reader(monkeypatch, group: str, name: str, value):
    """Neutral API reader returns value"""
    monkeypatch.setattr(getattr(api.read, group), name, lambda *args, **kwargs: value)


def race(monkeypatch, lap_race: bool, progress: float, laptime: float, remaining: float):
    """Player on lap 6 (5 done) of a 20 laps race, or of a timed race at 100 s pace"""
    reader(monkeypatch, "session", "finish_type", lap_race)
    reader(monkeypatch, "lap", "number", 6)  # telemetry: lap being driven
    reader(monkeypatch, "lap", "completed_laps", 5)
    reader(monkeypatch, "lap", "maximum", 20)
    reader(monkeypatch, "lap", "remaining", 20 - 5 - progress)
    reader(monkeypatch, "lap", "progress", progress)
    reader(monkeypatch, "timing", "current_laptime", laptime)
    reader(monkeypatch, "session", "remaining", remaining)
    monkeypatch.setattr(minfo.vehicles, "finishTimeOffset", 0.0)
    monkeypatch.setattr(minfo.vehicles, "finishLapOffset", 0.0)
    monkeypatch.setattr(minfo.delta, "lapTimePace", 100.0)


def laps_left_shown(widgets, modern: bool) -> tuple[float, float]:
    """Laps left from Laps and position (total - done) & from Session"""
    laps = widgets("laps_and_position", modern=modern, show_laps=True, show_predicted_extra_laps=False)
    session = widgets("session", modern=modern, show_estimated_laps=True, show_predicted_extra_laps=False)
    if modern:
        text_laps = laps.laps_value().text
        text_left = session.laps_left(api.read.session.remaining())
    else:
        laps.timerEvent(None)
        session.timerEvent(None)
        text_laps = laps.bar_laps.text.removeprefix(laps.prefix_laps).strip()
        text_left = session.bar_estimated_laps.text.removeprefix(session.prefix_estimated_laps).strip()
    done, total = text_laps.split("/")
    return float(total.lstrip("~")) - float(done), float(text_left)


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize("case", [
    (False, 0.5, 50.0, 1030.0),  # timed: timer ends 10.8 laps from lap start -> finish line after 11 laps
    (False, 0.25, 25.0, 1000.0),
    (False, 0.6, 60.0, 0.0),  # timer ended: current lap is the last one
    (False, 0.98, 98.0, 1030.0),
    (True, 0.4, 40.0, 0.0),  # lap race
    (True, 0.98, 98.0, 0.0),
])
def test_laps_left_same_in_both_overlays(widgets, monkeypatch, modern, case):
    race(monkeypatch, *case)
    from_laps, from_session = laps_left_shown(widgets, modern)
    assert from_laps == pytest.approx(from_session, abs=0.006)


def test_timed_race_total_is_finish_lap(widgets, monkeypatch):
    race(monkeypatch, False, 0.5, 50.0, 1030.0)
    laps = widgets("laps_and_position", show_laps=True, show_predicted_extra_laps=False)
    assert laps.laps_value().text == "5.50/~16.00"  # 5 done + 11 laps to the flag
    session = widgets("session", show_estimated_laps=True, show_predicted_extra_laps=False)
    assert session.laps_left(1030.0) == "10.500"


@pytest.mark.parametrize("modern", [True, False])
def test_lap_race_counts_completed_laps(widgets, monkeypatch, modern):
    race(monkeypatch, True, 0.5, 50.0, 0.0)
    from_laps, from_session = laps_left_shown(widgets, modern)
    assert from_session == pytest.approx(14.5, abs=0.006)  # 20 - 5 done - half lap: lap being driven not counted
    assert from_laps == pytest.approx(14.5, abs=0.006)
