"""Map canvas view: zoom & move applied at once (matrix and screen positions updated once per eased frame),
zoom / panX / panY still readable & writable"""

import pytest

from tests.test_lap_viewer_features import laps  # noqa: F401
from tests.test_lap_viewer_fix_qml import evaluate, find, opener, wait, warnings  # noqa: F401


def canvas_of(view):
    return find(view, lambda item: item.property("viewState") is not None and item.property("feet") is not None)[0]


def counting(view, canvas):
    """Change counts of view state, matrix, zoom & pan (JS object read back later)"""
    return evaluate(view, canvas, """(function() {
        var counts = {"state": 0, "matrix": 0, "tx": 0, "zoom": 0, "panX": 0}
        viewStateChanged.connect(function() { counts.state++ })
        matrixChanged.connect(function() { counts.matrix++ })
        txChanged.connect(function() { counts.tx++ })
        zoomChanged.connect(function() { counts.zoom++ })
        panXChanged.connect(function() { counts.panX++ })
        return counts
    })()""")


def count(counts, name: str) -> int:
    return counts.property(name).toInt()


def test_eased_zoom_updates_matrix_once_per_frame(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    canvas = canvas_of(view)
    counts = counting(view, canvas)
    evaluate(view, canvas, "zoomAt(3, width / 3, height / 3)")  # eased zoom at a point: zoom & pan change
    wait(1.0)
    frames = count(counts, "state")
    assert frames > 2
    assert count(counts, "matrix") == frames  # once per frame, not once per zoom, panX & panY
    assert count(counts, "tx") <= frames
    assert canvas.property("zoom") == pytest.approx(3.0)
    assert canvas.property("viewState").toVariant() == pytest.approx(
        [canvas.property("zoom"), canvas.property("panX"), canvas.property("panY")])
    # Screen & world positions agree with matrix
    scale, tx = canvas.property("mapScale"), canvas.property("tx")
    assert evaluate(view, canvas, "screenX(100)") == pytest.approx(100 * scale + tx)
    assert evaluate(view, canvas, "worldX(screenX(123.5))") == pytest.approx(123.5)
    assert evaluate(view, canvas, "worldY(screenY(-42))") == pytest.approx(-42)


def test_zoom_and_pan_still_writable(opener, warnings):  # noqa: F811
    dialog = opener()
    view, backend = dialog.view, dialog.backend
    backend.setSideTab(0)
    wait(0.3)
    canvas = canvas_of(view)
    evaluate(view, canvas, "zoom = 2")
    evaluate(view, canvas, "panX = 30")
    evaluate(view, canvas, "panY = -10")
    assert canvas.property("viewState").toVariant() == pytest.approx([2, 30, -10])
    assert canvas.property("mapScale") == pytest.approx(canvas.property("baseScale") * 2)
    assert canvas.property("tx") == pytest.approx(
        canvas.property("width") / 2 - canvas.property("centerX") * canvas.property("mapScale") + 30)
    evaluate(view, canvas, "reset(false)")
    assert canvas.property("viewState").toVariant() == pytest.approx([1, 0, 0])
    assert canvas.property("zoom") == 1 and canvas.property("panX") == 0
