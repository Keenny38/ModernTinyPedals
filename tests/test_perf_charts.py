"""Results positions & stats charts: hover, pick, reveal & resize frames repaint nothing heavy"""

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
        self.views = []  # plot sizes lines were asked for

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

    @Slot(float, float, float, float, float)
    def setChartView(self, width, height, thin, thick, wide):
        self.views.append((width, height))

    @Slot(int, result=list)
    def placesAt(self, lap):
        return [s["places"][lap] if 0 <= lap < len(s["places"]) else 0 for s in self._positions["series"]]


def positions_data(cars=20, laps=40):
    series = []
    for car in range(cars):
        places = [(car + lap) % cars + 1 for lap in range(laps + 1)]
        series.append({"key": str(car), "name": f"Car {car}", "number": str(car), "color": "#4488CC",
                       "player": car == 3, "places": places, "last": [laps, places[-1]], "thin": f"thin{car}",
                       "thick": f"thick{car}", "wide": f"wide{car}" if car == 3 else ""})
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

    from neopedal.ui.quick import PageState, Theme, Translator, qml_folder_imports, register_types, theme_copy

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    views = []

    def make(body: str, backend: QObject):
        register_types()
        wrapper = tmp_path / f"wrapper{len(views)}.qml"
        wrapper.write_text(
            f'import QtQuick\n{qml_folder_imports()}\n{body}\n', encoding="utf-8")
        view = QQuickWidget()
        view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        context = view.rootContext()
        context.setContextProperty("theme", theme_copy(view.engine(), Theme(view)))
        context.setContextProperty("i18n", Translator(view))
        context.setContextProperty("backend", backend)
        context.setContextProperty("pageState", PageState(view))
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


def items_of(root):
    """Visual items under root (Repeater delegates included)"""
    found, todo = [], list(root.childItems())
    while todo:
        item = todo.pop()
        found.append(item)
        todo.extend(item.childItems())
    return found


def shapes(root):
    """GpuShape items of chart: key, visible"""
    return {item.property("key"): item.isVisible() for item in items_of(root)
            if item.metaObject().className().startswith("GpuShape") and item.property("key")}


def test_positions_lines_on_gpu(chart_view):
    """No canvas: lines built once plot size settles (resize frames only scale them), hover & pick show lines"""
    make, _ = chart_view
    backend = FakeResults(positions_data())
    view = make("ResultsPositions { }", backend)
    settle(0.9)  # reveal animation done
    chart = view.rootObject()
    assert not [item for item in items_of(chart) if "Canvas" in item.metaObject().className()]
    plot = (round(chart.property("plotWidth")), round(chart.property("plotHeight")))
    assert backend.views and backend.views[-1] == plot
    lines = shapes(chart)
    assert lines["thin0"] and not lines.get("thin3") and lines["wide3"]  # player drawn wide, not dimmed
    # nearest car from place table: car 0 is P1 at lap 0
    plot_x, plot_y = chart.property("plotX"), chart.property("plotY")
    assert chart.nearest(plot_x, plot_y) == 0
    assert chart.nearest(plot_x, plot_y - 1000) == -1
    chart.setProperty("hovered", 5)
    settle(0.05)
    assert shapes(chart).get("thick5")
    backend.selectEntry("2")
    settle(0.05)
    lines = shapes(chart)
    assert chart.property("picked") == 2 and lines.get("thick2") is not None and not lines["thin2"]
    asked = len(backend.views)
    for width in range(700, 900, 25):  # resize frames: lines scaled, not built again
        view.resize(width, 520)
        settle(0.01)
    assert len(backend.views) <= asked + 2  # 8 frames
    settle(0.5)
    plot = (round(chart.property("plotWidth")), round(chart.property("plotHeight")))
    assert backend.views[-1] == plot and len(backend.views) <= asked + 3  # once size settled


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
    hover = chart.findChild(QObject, "statsHover")
    dot = chart.findChild(QObject, "statsHoverDot")
    settle(0.8)  # reveal animation: no data repaint per frame
    wait_for(lambda: data_paints[0] >= 1, view)
    assert 1 <= data_paints[0] <= 2
    plot_x, plot_width = chart.property("plotX"), chart.property("plotWidth")
    assert chart.nearest(plot_x + plot_width * 4 / 9 + 1) == 4
    assert chart.nearest(-1000) == -1
    painted = data_paints[0]
    assert not hover.property("visible")
    chart.setProperty("hovered", 4)  # new personal best: accent dot
    settle()
    assert hover.property("visible") and hover.property("stroke") > 0
    chart.setProperty("hovered", 5)  # guide & dot moved, nothing painted
    settle()
    center = dot.property("x") + dot.property("width") / 2
    assert abs(center - chart.px(points[5]["x"])) < 0.5 and hover.property("stroke") == 0
    chart.setProperty("hovered", -1)
    settle()
    assert not hover.property("visible") and data_paints[0] == painted
