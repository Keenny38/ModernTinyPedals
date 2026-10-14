#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Black box widget, draw incident trace & event log

The trace shows the recorder window: throttle and brake as filled areas, speed as a line,
ABS & TC activity as ticks on top, wheel lock & spin as marks at the bottom. Live while
driving, frozen on the last incident for incident_display_duration seconds, with the
trigger moment marked. A frozen incident can be replayed (cursor sweeping the recording with
the values under it) and compared with the previous one (its speed drawn behind, dashed).
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QTransform

from .recorder import format_event, index_of

if TYPE_CHECKING:
    from ...template.widget_config_types import BlackBoxConfig

MIN_SPEED_SCALE = 20.0  # m/s, so a slow crawl is not stretched to full height
REPLAY_HOLD = 1.0  # seconds the replay cursor rests at the end before starting again


def replay_time(start: float, end: float, elapsed: float) -> float:
    """Replay cursor time: sweeps start to end in real time, rests, then loops"""
    span = max(end - start, 0.0)
    return start + min(elapsed % (span + REPLAY_HOLD), span)


def sample_at(samples, time: float):
    """Last sample at or before time (first sample if time is before it)"""
    found = samples[0]
    for sample in samples:
        if sample.time > time:
            break
        found = sample
    return found


def trace_points(samples, x_at, y_of, width: float) -> list[QPointF]:
    """Points of samples; more samples than 4 per pixel column (long recording): first, lowest, highest &
    last of each pixel column only, in time order (same shape drawn, fewer points)"""
    if len(samples) <= width * 4:
        return [QPointF(x_at(sample.time), y_of(sample)) for sample in samples]
    points: list[QPointF] = []
    column = None
    first = low = high = last = (0, 0.0, 0.0)  # sample index, x, y
    for index, sample in enumerate(samples):
        x = x_at(sample.time)
        point = (index, x, y_of(sample))
        if int(x) != column:
            if column is not None:
                points.extend(QPointF(x_, y_) for _, x_, y_ in sorted({first, low, high, last}))
            column = int(x)
            first = low = high = point
        elif point[2] < low[2]:
            low = point
        elif point[2] > high[2]:
            high = point
        last = point
    points.extend(QPointF(x_, y_) for _, x_, y_ in sorted({first, low, high, last}))
    return points


def mark_runs(samples, x_at, active, width: float) -> list[tuple[float, float]]:
    """Left & right x of each run of active samples (marks width wide touching or overlapping)"""
    runs: list[tuple[float, float]] = []
    left = right = None
    for sample in samples:
        if not active(sample):
            continue
        x = x_at(sample.time)
        if right is not None and x <= right:
            right = x + width
        else:
            if left is not None and right is not None:
                runs.append((left, right))
            left, right = x, x + width
    if left is not None and right is not None:
        runs.append((left, right))
    return runs


def translucent(name: str, alpha: int) -> QColor:
    color = QColor(name)
    color.setAlpha(alpha)
    return color


def steering_value(sample) -> float:
    """Steering input clamped to -1..1, 0 if unknown (NaN)"""
    steering = sample.steering
    return min(max(steering, -1.0), 1.0) if steering == steering else 0.0


class TraceStyle(NamedTuple):
    """Trace colors & pens, parsed once per setting"""

    key: tuple
    throttle: QColor
    brake: QColor
    abs_active: QColor
    tc_active: QColor
    wheel_lock: QColor
    wheel_spin: QColor
    speed: QColor
    speed_pen: QPen
    compared_pen: QPen
    steering_pen: QPen
    cursor_pen: QPen
    incident: QColor
    incident_pen: QPen
    recording: QColor
    event: QColor


class TraceShapes(NamedTuple):
    """Trace drawn in widget coordinates: pedal areas, marks (rect, color) in drawing order, speed lines,
    steering line"""

    throttle: QPolygonF
    brake: QPolygonF
    marks: tuple[tuple[QRectF, QColor], ...]
    compared: QPainterPath | None
    speed: QPainterPath
    steering: QPainterPath


class LiveTrace:
    """Live recording as (time, value) polygons: newest samples appended, oldest dropped as the recorder
    drops them, mapped to the trace when drawn"""

    __slots__ = ("last", "throttle", "brake", "speed", "steering", "marked")

    def __init__(self):
        self.last = None
        self.throttle = QPolygonF()
        self.brake = QPolygonF()
        self.speed = QPolygonF()
        self.steering = QPolygonF()
        # Samples with a mark (ABS, TC, wheel slip), in sample order (marks drawn in the same order as
        # trace_marks: touching rows share antialiased edges): marks drawn from these only
        self.marked: deque = deque()

    def sync(self, samples):
        """Follow recorder samples (deque appended right, dropped left; anything else: built again)"""
        last = self.last
        added = []
        found = False
        if last is not None:
            for sample in reversed(samples):
                if sample is last:
                    found = True
                    break
                added.append(sample)
        polygons = (self.throttle, self.brake, self.speed, self.steering)
        if not found:
            for polygon in polygons:
                polygon.clear()
            self.marked.clear()
            added = list(reversed(samples))
        for sample in reversed(added):
            time = sample.time
            self.throttle.append(QPointF(time, min(max(sample.throttle, 0.0), 1.0)))
            self.brake.append(QPointF(time, min(max(sample.brake, 0.0), 1.0)))
            self.speed.append(QPointF(time, max(sample.speed, 0)))
            self.steering.append(QPointF(time, steering_value(sample)))
            if sample.abs_active or sample.tc_active or sample.slip:
                self.marked.append(sample)
        excess = self.throttle.size() - len(samples)
        if excess > 0:
            for polygon in polygons:
                polygon.remove(0, excess)
        if samples:  # times of dropped samples dropped
            first = samples[0].time
            marked = self.marked
            while marked and marked[0].time < first:
                marked.popleft()
        self.last = samples[-1] if samples else None


class TracePainter:
    """Draw incident trace & event log"""

    # Attributes set by black box widget class (widget/black_box.py) or other parts
    browse_incident: Any
    browse_since: Any
    displayed_incident: Any
    draw_fit_text: Any
    event_log: Any
    event_rows: Any
    font_label: Any
    font_small: Any
    incident_replay: Any
    recorder: Any
    recorder_now: Any
    show_previous_incident: Any
    speed_label: Any
    text: Any
    unit: Any
    unit_speed: Any
    wcfg: BlackBoxConfig

    _trace_style: TraceStyle | None = None
    _frozen_trace: tuple | None = None  # incident, previous, layout & style key, shapes
    _live_trace: LiveTrace | None = None

    def draw_trace(self, painter: QPainter, rect: QRectF):
        style = self.trace_style()
        incident = self.displayed_incident()
        samples = incident.samples if incident is not None else self.recorder.samples
        inner = rect.adjusted(self.unit * 0.15, self.unit * 0.15, -self.unit * 0.15, -self.unit * 0.15)
        if len(samples) >= 2 and inner.width() > 2 and inner.height() > 2:
            end = samples[-1].time
            span = max(end - samples[0].time, 1.0) if incident is not None else self.recorder.duration
            start = end - span

            def x_at(time: float) -> float:
                return inner.left() + (time - start) / span * inner.width()

            if incident is not None:
                shapes = self.frozen_trace(incident, inner, x_at, style)
            else:
                shapes = self.live_trace(samples, inner, x_at, start, span, style)
            self.paint_trace_shapes(painter, shapes, style)
            if incident is not None:
                painter.setPen(style.incident_pen)
                trigger_x = x_at(incident.time)
                painter.drawLine(QPointF(trigger_x, rect.top()), QPointF(trigger_x, rect.bottom()))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
                if self.incident_replay:
                    self.draw_replay_cursor(painter, rect, inner, samples, x_at, incident)
        self.draw_trace_caption(painter, rect, incident)

    def trace_style(self) -> TraceStyle:
        """Colors & pens, parsed again only if a color setting or size changed"""
        wcfg = self.wcfg
        key = (
            wcfg["throttle_color"], wcfg["brake_color"], wcfg["abs_active_color"], wcfg["tc_active_color"],
            wcfg["wheel_lock_color"], wcfg["wheel_spin_color"], wcfg["trace_speed_color"],
            wcfg["trace_steering_color"], wcfg["incident_color"], wcfg["font_color_event_log"], self.unit,
        )
        style = self._trace_style
        if style is not None and style.key == key:
            return style
        unit = self.unit
        speed = QColor(wcfg["trace_speed_color"])
        incident = QColor(wcfg["incident_color"])
        style = self._trace_style = TraceStyle(
            key,
            translucent(wcfg["throttle_color"], 95),
            translucent(wcfg["brake_color"], 95),
            QColor(wcfg["abs_active_color"]),
            QColor(wcfg["tc_active_color"]),
            QColor(wcfg["wheel_lock_color"]),
            QColor(wcfg["wheel_spin_color"]),
            speed,
            QPen(speed, max(unit * 0.09, 1.2)),
            QPen(translucent(wcfg["trace_speed_color"], 110), max(unit * 0.07, 1), Qt.PenStyle.DashLine),
            QPen(QColor(wcfg["trace_steering_color"]), max(unit * 0.06, 1)),
            QPen(speed, max(unit * 0.05, 1), Qt.PenStyle.DashLine),
            incident,
            QPen(incident, max(unit * 0.08, 1)),
            translucent(wcfg["incident_color"], 200),
            QColor(wcfg["font_color_event_log"]),
        )
        return style

    def frozen_trace(self, incident, inner: QRectF, x_at, style: TraceStyle) -> TraceShapes:
        """Shapes of a frozen incident, built once while it is shown (replay cursor sweeps over them)"""
        previous = self.compared_incident(incident)
        key = (inner.getRect(), style.key)
        cached = self._frozen_trace
        if cached is not None and cached[0] is incident and cached[1] is previous and cached[2] == key:
            return cached[3]
        shapes = self.trace_shapes(incident.samples, inner, x_at, style, incident, previous)
        self._frozen_trace = (incident, previous, key, shapes)
        return shapes

    def live_trace(self, samples, inner: QRectF, x_at, start: float, span: float, style: TraceStyle) -> TraceShapes:
        """Shapes of the live recording: lines kept as (time, value) polygons, mapped to the trace

        Long recordings too (more samples than pixel columns): Qt draws a few thousand points far faster
        than shapes are built again in Python each repaint.
        """
        live = self._live_trace
        if live is None:
            live = self._live_trace = LiveTrace()
        live.sync(samples)
        left, bottom, height = inner.left(), inner.bottom(), inner.height()
        scale_x = inner.width() / span

        def mapped(polygon: QPolygonF, scale_y: float, base_y: float) -> QPolygonF:
            return QTransform(scale_x, 0, 0, scale_y, left, base_y).map(polygon.translated(-start, 0))

        def area(polygon: QPolygonF) -> QPolygonF:
            points = mapped(polygon, -height, bottom)
            points.prepend(QPointF(points.first().x(), bottom))
            points.append(QPointF(points.last().x(), bottom))
            return points

        top_speed = max(live.speed.boundingRect().bottom(), MIN_SPEED_SCALE)  # highest speed (y = speed)
        speed = QPainterPath()
        speed.addPolygon(mapped(live.speed, -height / top_speed, bottom))
        steering = QPainterPath()
        steering.addPolygon(mapped(live.steering, -height / 2, inner.center().y()))
        return TraceShapes(area(live.throttle), area(live.brake), self.live_marks(inner, live, len(samples), x_at, style),
                           None, speed, steering)

    def live_marks(self, rect: QRectF, live: LiveTrace, count: int, x_at,
                   style: TraceStyle) -> tuple[tuple[QRectF, QColor], ...]:
        """Marks of the live recording (same as trace_marks) from kept times of active samples only"""
        return self.trace_marks(rect, live.marked, x_at, style, count)

    def trace_shapes(self, samples, inner: QRectF, x_at, style: TraceStyle, incident=None,
                     previous=None) -> TraceShapes:
        """Shapes of samples, previous incident speed (aligned on its own trigger) behind"""
        top_speed = max(max(sample.speed for sample in samples), MIN_SPEED_SCALE)
        compared = None
        if previous is not None and incident is not None:
            shift = incident.time - previous.time
            top_speed = max(top_speed, max(sample.speed for sample in previous.samples))
            # Its window may be longer than the shown one (recorder duration changed, early close): trimmed
            left, right = inner.left(), inner.right()
            within = [sample for sample in previous.samples if left <= x_at(sample.time + shift) <= right]
            if within:
                compared = self.trace_speed(inner, within, lambda time: x_at(time + shift), top_speed)
        return TraceShapes(
            self.trace_area(inner, samples, x_at, "throttle"),
            self.trace_area(inner, samples, x_at, "brake"),
            self.trace_marks(inner, samples, x_at, style),
            compared,
            self.trace_speed(inner, samples, x_at, top_speed),
            self.trace_steering(inner, samples, x_at),
        )

    @staticmethod
    def paint_trace_shapes(painter: QPainter, shapes: TraceShapes, style: TraceStyle):
        """Pedal areas, marks, speed lines (compared one behind), steering line"""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(style.throttle)
        painter.drawPolygon(shapes.throttle)
        painter.setBrush(style.brake)
        painter.drawPolygon(shapes.brake)
        for mark, color in shapes.marks:
            painter.fillRect(mark, color)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if shapes.compared is not None:
            painter.setPen(style.compared_pen)
            painter.drawPath(shapes.compared)
        painter.setPen(style.speed_pen)
        painter.drawPath(shapes.speed)
        painter.setPen(style.steering_pen)
        painter.drawPath(shapes.steering)

    def compared_incident(self, incident):
        """Previous incident drawn behind the shown one, None if none or turned off"""
        if incident is None or not self.show_previous_incident:
            return None
        return self.recorder.previous_incident(incident)

    def replay_cursor_time(self, incident) -> float:
        """Time the replay cursor is at: sweep starts when the incident is first shown"""
        samples = incident.samples
        if incident is self.browse_incident:
            shown_since = self.browse_since
        else:
            shown_since = samples[-1].time  # frozen right after its last sample
        return replay_time(samples[0].time, samples[-1].time, self.recorder_now() - shown_since)

    def draw_replay_cursor(self, painter: QPainter, rect: QRectF, inner: QRectF, samples, x_at, incident):
        """Cursor line, and speed, pedals & gear at the cursor at the bottom of the trace"""
        style = self.trace_style()
        time = self.replay_cursor_time(incident)
        sample = sample_at(samples, time)
        x = x_at(time)
        painter.setPen(style.cursor_pen)
        painter.drawLine(QPointF(x, inner.top()), QPointF(x, inner.bottom()))
        speed = self.unit_speed(sample.speed)
        text = (f"{time - incident.time:+.1f}s {speed:.0f}{self.speed_label} "
                f"T{sample.throttle * 100:.0f} B{sample.brake * 100:.0f} "
                f"{'N' if sample.gear == 0 else 'R' if sample.gear < 0 else sample.gear}")
        caption_h = min(self.unit * 0.8, rect.height() / 2)
        row = QRectF(rect.left() + self.unit * 0.25, rect.bottom() - caption_h, rect.width() - self.unit * 0.5,
                     caption_h)
        painter.setPen(style.speed)
        self.draw_fit_text(painter, row, text, self.font_label,
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def trace_area(rect: QRectF, samples, x_at, name: str) -> QPolygonF:
        """Pedal input as a filled area from bottom"""
        bottom, height = rect.bottom(), rect.height()
        points = [QPointF(x_at(samples[0].time), bottom)]
        points.extend(trace_points(
            samples, x_at, lambda sample: bottom - min(max(getattr(sample, name), 0.0), 1.0) * height, rect.width()))
        points.append(QPointF(x_at(samples[-1].time), bottom))
        return QPolygonF(points)

    @staticmethod
    def trace_speed(rect: QRectF, samples, x_at, top_speed: float) -> QPainterPath:
        """Speed line, scaled to top speed"""
        bottom, height = rect.bottom(), rect.height()
        path = QPainterPath()
        path.addPolygon(QPolygonF(trace_points(
            samples, x_at, lambda sample: bottom - min(max(sample.speed, 0) / top_speed, 1) * height, rect.width())))
        return path

    @staticmethod
    def trace_steering(rect: QRectF, samples, x_at) -> QPainterPath:
        """Steering input around the middle line: up is right, down is left"""
        middle = rect.center().y()
        half = rect.height() / 2
        path = QPainterPath()
        path.addPolygon(QPolygonF(trace_points(
            samples, x_at, lambda sample: middle - steering_value(sample) * half, rect.width())))
        return path

    def trace_marks(self, rect: QRectF, samples, x_at, style: TraceStyle,
                    count: int | None = None) -> tuple[tuple[QRectF, QColor], ...]:
        """ABS & TC ticks on top, lock & spin marks at bottom, in drawing order

        Args:
            count: samples of the recording when samples holds its marked ones only (live recording).
        """
        count = len(samples) if count is None else count
        tick = max(self.unit * 0.12, 2)
        width = max(rect.width() / max(count, 1), 1)
        marks: list[tuple[QRectF, QColor]] = []
        if count > rect.width() * 4:  # long recording: one mark per run of samples, not per sample
            top, bottom = rect.top(), rect.bottom() - tick
            for y, color, active in (
                (top, style.abs_active, lambda sample: sample.abs_active),
                (top + tick, style.tc_active, lambda sample: sample.tc_active),
                (bottom, style.wheel_lock, lambda sample: sample.slip == "lock"),
                (bottom, style.wheel_spin, lambda sample: sample.slip and sample.slip != "lock"),
            ):
                marks.extend((QRectF(left, y, right - left, tick), color)
                             for left, right in mark_runs(samples, x_at, active, width))
            return tuple(marks)
        for sample in samples:
            if not (sample.abs_active or sample.tc_active or sample.slip):
                continue
            x = x_at(sample.time)
            if sample.abs_active:
                marks.append((QRectF(x, rect.top(), width, tick), style.abs_active))
            if sample.tc_active:
                marks.append((QRectF(x, rect.top() + tick, width, tick), style.tc_active))
            if sample.slip:
                color = style.wheel_lock if sample.slip == "lock" else style.wheel_spin
                marks.append((QRectF(x, rect.bottom() - tick, width, tick), color))
        return tuple(marks)

    def draw_trace_caption(self, painter: QPainter, rect: QRectF, incident):
        """Incident summary (frozen) or recording mark (live), with incident count"""
        style = self.trace_style()
        caption_h = min(self.unit * 0.8, rect.height() / 2)
        left = QRectF(rect.left() + self.unit * 0.25, rect.top(), rect.width() * 0.7, caption_h)
        right = QRectF(rect.right() - rect.width() * 0.3 - self.unit * 0.25, rect.top(),
                       rect.width() * 0.3, caption_h)
        align_left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        align_right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        count = len(self.recorder.incidents)
        if incident is not None:
            painter.setPen(style.incident)
            text = f"{self.text['impact']} L{incident.lap} {incident.peak_g:.1f}g {incident.direction}".rstrip()
            position = index_of(self.recorder.incidents, incident)
            if count > 1 and position >= 0:  # which one, when browsing with the hotkey
                text += f" {position + 1}/{count}"
            self.draw_fit_text(painter, left, text, self.font_label, align_left)
        else:
            painter.setPen(style.recording)
            self.draw_fit_text(painter, right, f"● {count}" if count else "●", self.font_label, align_right)

    def draw_event_log(self, painter: QPainter):
        """Newest event on top"""
        style = self.trace_style()
        events = list(self.event_log.events)[::-1]
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for row, event in zip(self.event_rows, events):
            painter.setPen(style.incident if event.critical else style.event)
            self.draw_fit_text(painter, row, format_event(event), self.font_small, align)
