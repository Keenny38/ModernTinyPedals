"""Modern track map: road of each sector colored by player's last time in it, cars close to player ringed"""

from importlib import import_module
from types import SimpleNamespace

import pytest

from tinypedal.const_common import MAX_SECONDS


def sectors(last, best, delta_pb):
    return SimpleNamespace(sectorPrev=last, sectorBestTB=best, deltaSectorBestPB=delta_pb)


def test_sector_performance_colors():
    from tinypedal.widget._modern.track_map import sector_performance

    data = sectors(last=[30.0, 41.2, MAX_SECONDS], best=[30.0, 40.9, 28.0], delta_pb=[-0.2, -0.1, 0.0])
    assert sector_performance(data) == ("best", "positive", None)  # best, faster than best lap sector, no time
    data = sectors(last=[30.3, 41.5, 28.6], best=[30.0, 40.9, 28.0], delta_pb=[0.3, 0.2, 0.0])
    assert sector_performance(data) == ("warning", "warning", "warning")  # slower


def test_nearby_vehicles_within_threshold(monkeypatch):
    from tinypedal.module_info import minfo
    from tinypedal.widget._modern.track_map import nearby_vehicles

    monkeypatch.setattr(minfo.relative, "relativeAhead", [(0.4, 3), (1.6, 4), (30.0, 5)])
    monkeypatch.setattr(minfo.relative, "relativeBehind", [(-0.9, 6), (-1.2, 7)])
    assert nearby_vehicles(1.0) == {3, 6}
    assert nearby_vehicles(0.0) == frozenset()  # highlight off


@pytest.fixture
def track_map(ui_env, bundled_fonts):
    from tinypedal.setting import cfg
    from tinypedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    widgets = []

    def make(**options):
        cfg.user.setting["track_map"].update(options)
        widget = create_widget(import_module("tinypedal.widget.track_map"), cfg, "track_map")
        widgets.append(widget)
        return widget

    yield make
    for widget in widgets:
        widget.deleteLater()


def test_sector_colors_drawn_once_player_completes_sector(track_map, monkeypatch):
    from PySide6.QtCore import QTimerEvent

    from tinypedal.module_info import minfo

    data = sectors(last=[30.0, MAX_SECONDS, MAX_SECONDS], best=[30.0, 41.0, 28.0], delta_pb=[-0.1, 0.0, 0.0])
    monkeypatch.setattr(minfo.sectors, "sessionBest", data)
    widget = track_map(show_sector_performance=True)
    redraws = []
    monkeypatch.setattr(widget, "update_map", lambda data: None)  # track itself unchanged
    monkeypatch.setattr(widget, "redraw_static", lambda: redraws.append(1))
    widget.timerEvent(QTimerEvent(0))
    assert widget.sector_colors == ("best", None, None) and redraws == [1]
    widget.timerEvent(QTimerEvent(0))
    assert redraws == [1]  # same sector times: static layer kept
    data.sectorPrev = [30.0, 41.5, MAX_SECONDS]
    widget.timerEvent(QTimerEvent(0))
    assert widget.sector_colors == ("best", "warning", None) and redraws == [1, 1]
    off = track_map(show_sector_performance=False)
    off.timerEvent(QTimerEvent(0))
    assert off.sector_colors == ()


def test_nearby_cars_ringed(track_map, monkeypatch):
    from PySide6.QtCore import QTimerEvent

    from tinypedal.module_info import minfo

    monkeypatch.setattr(minfo.relative, "relativeAhead", [(0.5, 2)])
    monkeypatch.setattr(minfo.relative, "relativeBehind", [(-3.0, 4)])
    widget = track_map(show_nearby_vehicle_highlight=True, nearby_vehicle_threshold=1.0)
    widget.timerEvent(QTimerEvent(0))
    assert widget.nearby == {2}
    off = track_map(show_nearby_vehicle_highlight=False)
    off.timerEvent(QTimerEvent(0))
    assert off.nearby == frozenset()


def test_preview_draws_sector_colors(ui_env, bundled_fonts):
    """Overlay picture of simulated race: sector colors & nearby ring drawn"""
    from tinypedal.setting import cfg
    from tinypedal.ui.widget_preview import render_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
    image = render_widget(cfg, "track_map", cfg.user.setting["track_map"]).toImage()

    def purple(color) -> bool:
        return color.alpha() > 200 and color.red() > 120 and color.blue() > 200 and color.green() < 120

    shown = sum(1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
                if purple(image.pixelColor(x, y)))
    assert shown > 0  # session best sector of simulated race
