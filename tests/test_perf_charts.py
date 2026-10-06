"""Results positions & stats charts: hover and reveal frames repaint only the small hover layer"""

import time

import pytest
from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QEvent,
    QObject,
    QUrl,
    Signal,
    Slot,
    qInstallMessageHandler,
)
from PySide6.QtGui import QCursor


class FakeResults(QObject):
    driverChanged = Signal()
    positionsChanged = Signal()

    def __init__(self, positions):
        super().__init__()
        self._positions = positions
        self._selected = ""

    @Property(dict, notify=positionsChanged)
    def positions(self):
        return self._positions

    @Property(str, notify=driverChanged)
    def selectedEntry(self):
        return self._selected

    @Slot(str)
    def selectEntry(self, key):
        self._selected = key
        self.driverChanged.emit()


def positions_data(cars=20, laps=40):
    series = []
    for car in range(cars):
        points = [[lap, (car + lap) % cars + 1] for lap in range(laps + 1)]
        series.append({"key": str(car), "name": f"Car {car}", "number": str(car), "color": "#4488CC",
                       "player": car == 3, "points": points})
    return {"series": series, "laps": laps, "places": cars}


def settle(seconds=0.1):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def wait_for(condition, view=None, timeout=5.0):
    """Process events until condition is true (Canvas paints later under load, full test suite)

    A QQuickWidget may not render a frame on its own in a long offscreen run: a grab renders one,
    running paints already requested (no extra paint).
    """
    end = time.monotonic() + timeout
    grab_at = time.monotonic() + 0.3
    while not condition() and time.monotonic() < end:
        QCoreApplication.processEvents()
        if view is not None and time.monotonic() > grab_at:
            view.grabFramebuffer()
            grab_at = time.monotonic() + 0.3
        time.sleep(0.005)
    settle(0.05)


@pytest.fixture
def chart_view(ui_env, tmp_path):
    """Chart component in a QQuickWidget with app theme & translator"""
    from PySide6.QtQuickWidgets import QQuickWidget

    from tinypedal.ui.quick import QML_FOLDER, Theme, Translator, register_types, theme_copy

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    views = []

    def make(body: str, backend: QObject):
        register_types()
        wrapper = tmp_path / f"wrapper{len(views)}.qml"
        wrapper.write_text(
            f'import QtQuick\nimport "{QUrl.fromLocalFile(QML_FOLDER).toString()}"\n{body}\n', encoding="utf-8")
        view = QQuickWidget()
        view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        context = view.rootContext()
        context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
        context.setContextProperty("i18n", Translator(view))
        context.setContextProperty("backend", backend)
        view.setSource(QUrl.fromLocalFile(str(wrapper)))
        assert not view.errors(), [error.toString() for error in view.errors()]
        view.resize(900, 500)
        QCursor.setPos(-10000, -10000)  # cursor left over the chart by an earlier test would hover a car
        view.show()
        views.append((view, backend))
        return view

    yield make, messages
    for view, _backend in views:
        view.close()
        view.setSource(QUrl())  # page gone before its backend
        view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


def paint_counter(root, name):
    canvas = root.findChild(QObject, name)
    assert canvas is not None, name

    class Count:
        def __getitem__(self, index):
            return canvas.property("paints")

    return Count()


def test_positions_hover_repaints_top_layer_only(chart_view):
    make, _ = chart_view
    backend = FakeResults(positions_data())
    view = make("ResultsPositions { }", backend)
    settle(0.9)  # reveal animation done
    chart = view.rootObject()
    low = paint_counter(chart, "positionsDimLow")
    high = paint_counter(chart, "positionsDimHigh")
    top = paint_counter(chart, "positionsTop")
    wait_for(lambda: low[0] >= 1, view)
    assert low[0] >= 1 and high[0] == 0  # only the layer shown is painted
    low_start, top_start = low[0], top[0]
    # nearest car from place table: car 0 is P1 at lap 0
    plot_x, plot_y = chart.property("plotX"), chart.property("plotY")
    assert chart.nearest(plot_x, plot_y) == 0
    assert chart.nearest(plot_x, plot_y - 1000) == -1
    chart.setProperty("hovered", 5)
    wait_for(lambda: top[0] > top_start and high[0] >= 1, view)
    assert top[0] > top_start and high[0] == 1  # dim layer of hover painted once
    for index in (6, 7, 8):
        chart.setProperty("hovered", index)
        settle(0.02)
    chart.setProperty("hovered", -1)
    settle()
    assert high[0] == 1 and low[0] == low_start  # other cars never painted again on hover
    backend.selectEntry("2")
    wait_for(lambda: high[0] >= 2, view)
    assert chart.property("picked") == 2 and high[0] == 2  # car picked: dim lines painted without it
    assert low[0] == low_start  # dim level of nothing highlighted not needed while a car is picked


def test_stats_chart_hover_and_reveal(chart_view):
    make, _ = chart_view
    points = [{"x": index / 9, "y": index % 3 / 3, "pbY": 0.2, "newPb": index == 4, "clipped": index == 7,
               "tip": f"Session {index}"} for index in range(10)]
    data = {"points": points, "ticks": [{"y": 0.5, "text": "1:30"}], "limits": [], "dates": [], "pbY": 0.2,
            "top": "1:29"}
    view = make("StatsChart { }", QObject())
    chart = view.rootObject()
    chart.setProperty("chartData", data)
    data_paints = paint_counter(chart, "statsData")
    hover_paints = paint_counter(chart, "statsHover")
    settle(0.8)  # reveal animation: no data repaint per frame
    wait_for(lambda: data_paints[0] >= 1, view)
    assert 1 <= data_paints[0] <= 2
    plot_x, plot_width = chart.property("plotX"), chart.property("plotWidth")
    assert chart.nearest(plot_x + plot_width * 4 / 9 + 1) == 4
    assert chart.nearest(-1000) == -1
    painted, hovered = data_paints[0], hover_paints[0]
    chart.setProperty("hovered", 4)
    settle()
    chart.setProperty("hovered", 5)
    wait_for(lambda: hover_paints[0] >= hovered + 2, view)
    assert data_paints[0] == painted and hover_paints[0] == hovered + 2
