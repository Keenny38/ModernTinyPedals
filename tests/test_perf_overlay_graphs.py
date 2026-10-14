"""Overlay graphs drawn from kept shapes: trailing polygons updated sample by sample, black box trace (frozen
incident shapes built once, live recording as polygons mapped to the trace), fitted fonts keyed by font object;
pictures identical to shapes built point by point"""

import math
import random
from collections import deque

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QImage, QPainter, QPolygonF

from neopedal.widget._black_box.recorder import Incident, Sample
from neopedal.widget._black_box.trace import LiveTrace, TracePainter
from tests.test_modern_graphic_widgets import oval, reader, render, widgets  # noqa: F401  (fixture)

TRACE_COLORS = {
    "throttle_color": "#00FF00", "brake_color": "#FF0000", "abs_active_color": "#FFFF00",
    "tc_active_color": "#00FFFF", "wheel_lock_color": "#FF00FF", "wheel_spin_color": "#FF8800",
    "trace_speed_color": "#FFFFFF", "trace_steering_color": "#4488FF", "incident_color": "#FF2222",
    "font_color_event_log": "#CCCCCC",
}


class Trace(TracePainter):
    """Trace painter without widget"""

    unit = 13.0

    def __init__(self):
        self.wcfg = dict(TRACE_COLORS)


def random_sample(rng: random.Random, time: float) -> Sample:
    steering = math.nan if rng.random() < 0.05 else rng.uniform(-1.3, 1.3)
    return Sample(time, rng.uniform(-1, 80), rng.uniform(-0.1, 1.1), rng.uniform(-0.1, 1.1), rng.randint(-1, 6),
                  rng.random() < 0.2, rng.random() < 0.2, rng.choice(("", "", "lock", "spin")), steering)


def painted(trace: Trace, shapes, size=(420, 140)) -> QImage:
    image = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    trace.paint_trace_shapes(painter, shapes, trace.trace_style())
    painter.end()
    return image


def live_frame(trace: Trace, samples, inner: QRectF, duration: float):
    """Live shapes (kept polygons) and shapes built point by point, same window"""
    end = samples[-1].time
    start = end - duration

    def x_at(time: float) -> float:
        return inner.left() + (time - start) / duration * inner.width()

    style = trace.trace_style()
    return (trace.live_trace(samples, inner, x_at, start, duration, style),
            trace.trace_shapes(samples, inner, x_at, style))


def test_live_trace_polygons_follow_recorder_and_match_point_by_point():
    rng = random.Random(7)
    trace = Trace()
    samples: deque[Sample] = deque(maxlen=61)
    inner = QRectF(3.7, 2.1, 401.3, 121.9)
    time = 51234.5678
    differing = 0
    for _ in range(150):
        for _ in range(rng.choice((1, 1, 1, 2, 3))):  # several samples between two paints too
            time += 0.05
            samples.append(random_sample(rng, time))
        if len(samples) < 2:
            continue
        live, built = live_frame(trace, samples, inner, 3.0)
        kept = trace._live_trace
        assert kept is not None and kept.throttle.size() == len(samples)
        assert kept.throttle.first().x() == samples[0].time and kept.speed.last().x() == samples[-1].time
        differing += painted(trace, live) != painted(trace, built)
    assert differing == 0


def test_live_trace_appends_only_new_samples():
    rng = random.Random(3)
    samples: deque[Sample] = deque((random_sample(rng, 100 + index * 0.05) for index in range(40)), maxlen=40)
    live = LiveTrace()
    live.sync(samples)
    polygon = live.throttle
    first_points = [polygon.at(index) for index in range(polygon.size())]
    samples.append(random_sample(rng, 102.0))
    live.sync(samples)
    assert live.throttle is polygon and polygon.size() == 40
    assert [polygon.at(index) for index in range(39)] == first_points[1:]  # kept, not built again
    samples.clear()  # new session: built again
    samples.extend(random_sample(rng, 200 + index * 0.05) for index in range(5))
    live.sync(samples)
    assert polygon.size() == 5 and polygon.first().x() == 200


def test_live_trace_long_recording_kept_as_polygons():
    """More samples than pixel columns: kept polygons too (Qt draws them, no Python rebuild each paint),
    same picture as pixel columns thinned out but for antialiased edges"""
    rng = random.Random(5)
    trace = Trace()
    samples = deque(random_sample(rng, 10 + index * 0.05) for index in range(300))
    inner = QRectF(0, 0, 40, 50)  # fewer than 4 pixels per sample
    live, built = live_frame(trace, samples, inner, 15.0)
    assert trace._live_trace is not None and trace._live_trace.speed.size() == len(samples)
    live_image, built_image = painted(trace, live, (50, 60)), painted(trace, built, (50, 60))
    differing = sum(
        max(abs(a - b) for a, b in zip(live_image.pixelColor(x, y).getRgb(), built_image.pixelColor(x, y).getRgb()))
        > 96 for x in range(50) for y in range(60))
    assert differing < 50 * 60 * 0.02  # thin lines on other pixel rows here and there


def test_frozen_trace_built_once_while_shown():
    rng = random.Random(11)
    trace = Trace()
    trace.show_previous_incident = True
    first = Incident(105.0, "impact", 5.0, 2, 80.0, tuple(random_sample(rng, 100 + i * 0.05) for i in range(200)))
    second = Incident(205.0, "impact", 5.0, 3, 180.0, tuple(random_sample(rng, 200 + i * 0.05) for i in range(200)))
    trace.recorder = type("Recorder", (), {"previous_incident": lambda self, incident: first})()
    inner = QRectF(2, 2, 400, 120)
    built = []
    original = trace.trace_shapes
    trace.trace_shapes = lambda *args, **kwargs: (built.append(1), original(*args, **kwargs))[1]
    end, start = second.samples[-1].time, second.samples[0].time
    span = end - start

    def x_at(time: float) -> float:
        return inner.left() + (time - (end - span)) / span * inner.width()

    style = trace.trace_style()
    shapes = trace.frozen_trace(second, inner, x_at, style)
    assert shapes.compared is not None
    for _ in range(5):  # replay cursor frames
        assert trace.frozen_trace(second, inner, x_at, style) is shapes
    assert len(built) == 1
    assert trace.frozen_trace(second, QRectF(2, 2, 300, 120), x_at, style) is not shapes  # resized
    trace.wcfg["throttle_color"] = "#0000FF"
    assert trace.trace_style() is not style  # color setting changed: parsed again
    assert len(built) == 2


def test_trace_style_parsed_once():
    trace = Trace()
    style = trace.trace_style()
    assert trace.trace_style() is style
    assert style.throttle.alpha() == 95 and style.recording.alpha() == 200


def test_fitted_font_keyed_by_font_object(ui_env):
    from neopedal.widget._black_box.base import PaintBase

    class Fonts(PaintBase):
        def __init__(self):
            self.widget = QFont("Arial")
            self.widget.setPixelSize(20)

        def font(self):
            return QFont(self.widget)  # new copy every call, as QWidget.font()

    fonts = Fonts()
    image = QImage(50, 50, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    label = QFont("Arial")
    label.setPixelSize(16)
    first = fonts.fitted_font(painter, fonts.font(), "12345", 10, 10)
    assert fonts.fitted_font(painter, fonts.font(), "12345", 10, 10) is first  # copies share entries
    fitted = fonts.fitted_font(painter, label, "12345", 10, 10)
    assert fonts.fitted_font(painter, label, "12345", 10, 10) is fitted
    assert fonts.widget_font() is fonts.widget_font()
    assert len(fonts._fitted_fonts) == 2
    painter.end()


def test_polygon_remove_range():
    """QPolygonF.remove(index, count) drops the oldest points (used by LiveTrace)"""
    polygon = QPolygonF([QPointF(index, 0) for index in range(5)])
    polygon.remove(0, 2)
    assert polygon.size() == 3 and polygon.first().x() == 2


# --- Delta graph
class Graph:
    """Delta graph geometry without widget"""

    def __init__(self, show_previous=True):
        from neopedal.widget.delta_graph import DeltaGraphMixin

        class Mixin(DeltaGraphMixin):
            wcfg = {"deltabest_source": "Best", "delta_display_range": 2.0, "decimal_places": 2,
                    "show_previous_lap": show_previous, "show_position_mark": True}

        self.mixin = Mixin()
        self.mixin.setup_graph(QRectF(1.5, 20.25, 301.0, 80.0))


def polygons(shapes) -> list[list[tuple[float, float]]]:
    return [[(point.x(), point.y()) for point in polygon.toList()] for polygon in shapes]


def test_delta_graph_shapes_extended_match_built_from_whole_trace():
    from neopedal.widget._race_aids import line_polygons
    from neopedal.widget.delta_graph import area_polygons

    rng = random.Random(21)
    graph = Graph().mixin
    trace = graph.trace
    lap, progress = 0, 0.0
    previous_builds = 0
    for step in range(4000):
        roll = rng.random()
        if roll < 0.004:
            lap += 1
            progress = 0.0
        elif roll < 0.006:
            progress = max(progress - rng.uniform(0, 0.3), 0.0)  # reset, or moved back
        elif roll < 0.01:
            progress += rng.uniform(0.02, 0.06)  # skipped slots, more than filled
        elif roll < 0.04:
            progress = max(progress - rng.uniform(0.002, 0.008), 0.0)  # one slot back: last samples changed
        elif progress > 1.0:
            progress = 0.0
            lap += rng.random() < 0.5  # lap counter before or after progress wrap
        else:
            progress += rng.uniform(0.0, 0.006)
        delta = math.nan if rng.random() < 0.03 else rng.uniform(-3, 3)
        previous_version = trace.previous_version
        if not trace.update(lap, progress, delta):
            continue
        shapes = graph.build_shapes()
        previous_builds += trace.previous_version != previous_version
        span = graph.delta_range
        assert polygons(shapes.gain) == polygons(area_polygons(trace.current, graph.chart, span, -1)), step
        assert polygons(shapes.loss) == polygons(area_polygons(trace.current, graph.chart, span, 1)), step
        assert polygons(shapes.line) == polygons(line_polygons(trace.current, graph.chart, -span, span)), step
        assert polygons(shapes.previous) == polygons(line_polygons(trace.previous, graph.chart, -span, span)), step
    assert previous_builds > 5


def test_delta_graph_previous_lap_built_once_per_lap(monkeypatch):
    from neopedal.widget import delta_graph

    graph = Graph().mixin
    built = []
    real = delta_graph.line_polygons
    monkeypatch.setattr(delta_graph, "line_polygons", lambda *args: built.append(1) or real(*args))
    for lap in range(3):
        for slot in range(100):
            graph.trace.update(lap, slot / 100, 0.1)
            graph.build_shapes()
    assert len(built) == 3  # once per lap (first lap: empty previous lap)
    runs = graph.lap_shapes.runs
    assert len(runs) == 1 and runs[0][2].size() == graph.trace.last_slot + 1  # extended, one run


# --- Modern trailing & track map (widgets)
def old_trailing_paint(widget, painter: QPainter):
    """Trailing drawn point by point from samples (drawing before kept polygons)"""
    area = widget.plot_area
    height = area.height()
    start_x, step = (area.right(), -widget.step) if widget.newest_right else (area.left(), widget.step)
    base_y, scale = (area.bottom(), -height) if widget.top_is_full else (area.top(), height)
    painter.save()
    painter.setClipRect(widget.chart)
    for plot in widget.plots:
        if plot.dots:
            points = [QPointF(start_x + index * step, base_y + value * scale)
                      for index, value in enumerate(plot.samples) if value >= 0]
            if points:
                painter.setPen(plot.pen)
                painter.drawPoints(QPolygonF(points))
            continue
        points = [QPointF(start_x + index * step, base_y + min(max(value, 0.0), 1.0) * scale)
                  for index, value in enumerate(plot.samples)]
        if len(points) < 2:
            continue
        if plot.fill is not None:
            area_points = [*points, QPointF(points[-1].x(), base_y), QPointF(points[0].x(), base_y)]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(plot.fill)
            painter.drawPolygon(QPolygonF(area_points))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(plot.pen)
        painter.drawPolyline(QPolygonF(points))
    painter.restore()


@pytest.mark.parametrize("inverted", [False, True])
def test_trailing_kept_polygons_same_picture(widgets, monkeypatch, inverted):  # noqa: F811
    from PySide6.QtCore import QTimerEvent

    widget = widgets("trailing", show_wheel_lock=True, show_tc_activation=True, show_abs_activation=True,
                     show_clutch=True, show_steering=True, show_speed=True, show_inverted_trailing=inverted,
                     show_inverted_pedal=inverted, display_width=137)
    rng = random.Random(9)
    monkeypatch.setattr(widget, "plot_paused", lambda: False)
    monkeypatch.setattr(widget, "read_inputs", lambda: [
        rng.uniform(-0.3, 1.3) if rng.random() < 0.7 else -1.0 for _ in widget.plot_names])
    capacity = widget.plots[0].samples.maxlen
    for frame in range(capacity * 2 + 5):
        widget.timerEvent(QTimerEvent(0))
        if frame % 37 and frame != capacity * 2 + 4:
            continue
        for plot in widget.plots:  # points kept: samples in chart, dots only for drawn samples
            drawn = sum(1 for value in plot.samples if value >= 0) if plot.dots else len(plot.samples)
            assert plot.points.size() == drawn
        kept = render(widget)
        widget.paint = lambda painter: old_trailing_paint(widget, painter)
        built = render(widget)
        del widget.paint
        assert kept == built, frame


class SendCounter:
    """Safety car interpolation generator, sends counted"""

    def __init__(self, generator):
        self.generator = generator
        self.sends = 0

    def send(self, value):
        self.sends += 1
        return self.generator.send(value)


@pytest.mark.parametrize("modern", [True, False])
def test_track_map_safety_car_advanced_per_update_not_per_paint(widgets, oval, monkeypatch, modern):  # noqa: F811
    from PySide6.QtCore import QTimerEvent

    from tests.test_modern_graphic_widgets import update

    widget = widgets("track_map", modern=modern, show_safety_car=True)
    distance = {"value": 1000.0}
    clock = {"time": 10.0}
    reader(monkeypatch, "timing", "elapsed", lambda: clock["time"])
    reader(monkeypatch, "lap", "safety_car_active", True)
    reader(monkeypatch, "lap", "safety_car_distance", lambda: distance["value"])
    counter = widget.gen_position_interp = SendCounter(widget.gen_position_interp)
    update(widget)
    sends = counter.sends
    position = widget.safetycar_pos
    assert sends == 1 and position is not None
    for _ in range(3):  # expose, edit mode, nearby cars changed: paint only reads the position
        render(widget)
    assert counter.sends == sends and widget.safetycar_pos == position
    repaints = []
    # Repaint requests (request_update: 25 Hz governor may defer the repaint itself, tested in test_res_repaint)
    monkeypatch.setattr(widget, "request_update", lambda *args: repaints.append(args))
    for tick in range(1, 4):  # distance from game, then estimated between two game updates
        clock["time"] += 0.1
        distance["value"] = 1000.0 + (tick > 1) * 20.0
        widget.timerEvent(QTimerEvent(0))  # same vehicles data version: repaint requested for the safety car
    assert counter.sends == sends + 3 and repaints and widget.safetycar_pos != position
    reader(monkeypatch, "lap", "safety_car_active", False)
    widget.timerEvent(QTimerEvent(0))
    assert widget.safetycar_pos is None and counter.sends == sends + 3
