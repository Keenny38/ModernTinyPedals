"""Game Replays track map oriented like overlay & lap viewer maps: positions (x, -z) drawn y down (no vertical
flip), else circuit mirrored top to bottom"""

from PySide6.QtCore import QCoreApplication
from PySide6.QtQuick import QQuickItem

from tests.test_game_info import GAME_ANSWERS, answered, replays_page  # noqa: F401


def map_canvas(view) -> QQuickItem:
    canvases = [item for item in view.rootObject().findChildren(QQuickItem)
                if item.metaObject().indexOfProperty("flipY") >= 0
                and item.metaObject().indexOfProperty("viewState") >= 0]
    assert len(canvases) == 1
    return canvases[0]


def test_replay_map_not_flipped(replays_page):  # noqa: F811
    backend = replays_page.backend
    backend.setPanel(2)
    answered(replays_page, GAME_ANSWERS)
    QCoreApplication.processEvents()
    view = replays_page.view
    assert not view.errors(), [error.toString() for error in view.errors()]
    canvas = map_canvas(view)
    assert canvas.property("flipY") is False  # same as TrackMap.qml & TrackMapViewer.qml
    # Car at game z = 400 (map y -400) above car at z = 0 on screen, as on overlay track map (y down)
    cars = {row["key"]: row for row in backend.mapCars.rows}
    assert cars["7"]["mapY"] == -400.0
    matrix = canvas.property("matrix")
    assert matrix.row(1).y() > 0  # y scale positive: map y down on screen
