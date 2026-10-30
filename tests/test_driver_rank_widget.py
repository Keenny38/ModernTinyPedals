"""Driver rank overlay: Driver Rank & Safety Rank of game menu file, track limits of session"""

from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal import rank_info
from neopedal.api_control import api
from neopedal.process.driver_ranks import DriverRanks, Rank
from neopedal.setting import cfg
from neopedal.widget._modern import create_widget

PLAYER = DriverRanks("Keenny Hess", "1", "", "FR", Rank("Silver", 2, 40), Rank("Platinum", 3, 50))


@pytest.fixture
def make(ui_env, bundled_fonts, monkeypatch):
    created = []
    monkeypatch.setattr(rank_info.ranks, "poll", lambda: None)  # never looks for the game folder
    monkeypatch.setattr(api.read.session, "cut_points", lambda *args: 1.25)
    monkeypatch.setattr(api.read.session, "limits_points", lambda: 5.0)
    monkeypatch.setattr(api.read.session, "in_race", lambda: True)

    def build(modern: bool, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
        cfg.user.setting["driver_rank"].update(options)
        widget = create_widget(import_module("neopedal.widget.driver_rank"), cfg, "driver_rank")
        created.append(widget)
        return widget

    yield build
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def test_classic(make, monkeypatch):
    monkeypatch.setattr(rank_info.ranks, "player", PLAYER)
    widget = make(False)
    widget.timerEvent(None)
    texts = {key: bar.text for key, bar in widget.bars.items()}
    # Cells fit track limits of 10 characters (10.25/12.5) with progress shown too
    assert texts == {"driver_rank": "DR    S2  40%", "safety_rank": "SR    P3  50%", "track_limits": "TL     1.25/5"}
    monkeypatch.setattr(rank_info.ranks, "player", None)  # unknown: dash
    widget.timerEvent(None)
    assert widget.bars["driver_rank"].text.endswith("-")


def test_classic_without_progress(make, monkeypatch):
    monkeypatch.setattr(rank_info.ranks, "player", PLAYER)
    widget = make(False, show_progress=False, show_track_limits=False)
    widget.timerEvent(None)
    assert set(widget.bars) == {"driver_rank", "safety_rank"}
    assert widget.bars["safety_rank"].text.endswith("Platinum 3")


def test_modern(make, monkeypatch):
    monkeypatch.setattr(rank_info.ranks, "player", PLAYER)
    widget = make(True)
    widget.timerEvent(None)
    driver, safety, limits = widget.state
    assert (driver.text, driver.sub, driver.bar) == ("Silver 2", "40%", 0.4)
    assert (safety.text, safety.sub, safety.bar) == ("Platinum 3", "50%", 0.5)
    assert limits.text == "1.25/5"
    widget.grab()
    monkeypatch.setattr(rank_info.ranks, "player", None)
    widget.timerEvent(None)
    assert widget.state[0].text != "Silver 2"


def test_no_limit_outside_race(make, monkeypatch):
    monkeypatch.setattr(api.read.session, "in_race", lambda: False)  # practice & qualifying: no penalty
    widget = make(True)
    widget.timerEvent(None)
    limits = widget.state[-1]
    assert limits.text.startswith("1.25/") and limits.text != "1.25/5"
    assert limits.color == widget.theme.warning
