#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
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

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from .recorder import format_event, index_of

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


def translucent(name: str, alpha: int) -> QColor:
    color = QColor(name)
    color.setAlpha(alpha)
    return color


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
    wcfg: Any

    def draw_trace(self, painter: QPainter, rect: QRectF):
        wcfg = self.wcfg
        incident = self.displayed_incident()
        samples = incident.samples if incident is not None else tuple(self.recorder.samples)
        inner = rect.adjusted(self.unit * 0.15, self.unit * 0.15, -self.unit * 0.15, -self.unit * 0.15)
        if len(samples) >= 2 and inner.width() > 2 and inner.height() > 2:
            end = samples[-1].time
            span = max(end - samples[0].time, 1.0) if incident is not None else self.recorder.duration
            start = end - span

            def x_at(time: float) -> float:
                return inner.left() + (time - start) / span * inner.width()

            self.draw_trace_area(painter, inner, samples, x_at, "throttle", wcfg["throttle_color"])
            self.draw_trace_area(painter, inner, samples, x_at, "brake", wcfg["brake_color"])
            self.draw_trace_marks(painter, inner, samples, x_at)
            previous = self.compared_incident(incident)
            top_speed = max(max(sample.speed for sample in samples), MIN_SPEED_SCALE)
            if previous is not None:  # aligned on its own trigger
                shift = incident.time - previous.time
                top_speed = max(top_speed, max(sample.speed for sample in previous.samples))
                self.draw_trace_speed(painter, inner, previous.samples, lambda time: x_at(time + shift),
                                      top_speed, compared=True)
            self.draw_trace_speed(painter, inner, samples, x_at, top_speed)
            self.draw_trace_steering(painter, inner, samples, x_at)
            if incident is not None:
                pen = QPen(QColor(wcfg["incident_color"]), max(self.unit * 0.08, 1))
                painter.setPen(pen)
                trigger_x = x_at(incident.time)
                painter.drawLine(QPointF(trigger_x, rect.top()), QPointF(trigger_x, rect.bottom()))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
                if self.incident_replay:
                    self.draw_replay_cursor(painter, rect, inner, samples, x_at, incident)
        self.draw_trace_caption(painter, rect, incident)

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
        wcfg = self.wcfg
        time = self.replay_cursor_time(incident)
        sample = sample_at(samples, time)
        x = x_at(time)
        painter.setPen(QPen(QColor(wcfg["trace_speed_color"]), max(self.unit * 0.05, 1), Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x, inner.top()), QPointF(x, inner.bottom()))
        speed = self.unit_speed(sample.speed)
        text = (f"{time - incident.time:+.1f}s {speed:.0f}{self.speed_label} "
                f"T{sample.throttle * 100:.0f} B{sample.brake * 100:.0f} "
                f"{'N' if sample.gear == 0 else 'R' if sample.gear < 0 else sample.gear}")
        caption_h = min(self.unit * 0.8, rect.height() / 2)
        row = QRectF(rect.left() + self.unit * 0.25, rect.bottom() - caption_h, rect.width() - self.unit * 0.5,
                     caption_h)
        painter.setPen(QColor(wcfg["trace_speed_color"]))
        self.draw_fit_text(painter, row, text, self.font_label,
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def draw_trace_area(painter: QPainter, rect: QRectF, samples, x_at, name: str, color: str):
        """Pedal input as a filled area from bottom"""
        points = [QPointF(x_at(samples[0].time), rect.bottom())]
        for sample in samples:
            value = min(max(getattr(sample, name), 0.0), 1.0)
            points.append(QPointF(x_at(sample.time), rect.bottom() - value * rect.height()))
        points.append(QPointF(x_at(samples[-1].time), rect.bottom()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(translucent(color, 95))
        painter.drawPolygon(QPolygonF(points))

    def draw_trace_speed(self, painter: QPainter, rect: QRectF, samples, x_at, top_speed: float,
                         compared: bool = False):
        """Speed line, scaled to top speed (compared incident: dashed & faded, behind)"""
        path = QPainterPath()
        for index, sample in enumerate(samples):
            point = QPointF(x_at(sample.time), rect.bottom() - min(max(sample.speed, 0) / top_speed, 1) * rect.height())
            if index:
                path.lineTo(point)
            else:
                path.moveTo(point)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if compared:
            pen = QPen(translucent(self.wcfg["trace_speed_color"], 110), max(self.unit * 0.07, 1), Qt.PenStyle.DashLine)
        else:
            pen = QPen(QColor(self.wcfg["trace_speed_color"]), max(self.unit * 0.09, 1.2))
        painter.setPen(pen)
        painter.drawPath(path)

    def draw_trace_steering(self, painter: QPainter, rect: QRectF, samples, x_at):
        """Steering input around the middle line: up is right, down is left"""
        middle = rect.center().y()
        path = QPainterPath()
        for index, sample in enumerate(samples):
            steering = min(max(sample.steering, -1.0), 1.0) if sample.steering == sample.steering else 0.0
            point = QPointF(x_at(sample.time), middle - steering * rect.height() / 2)
            if index:
                path.lineTo(point)
            else:
                path.moveTo(point)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self.wcfg["trace_steering_color"]), max(self.unit * 0.06, 1)))
        painter.drawPath(path)

    def draw_trace_marks(self, painter: QPainter, rect: QRectF, samples, x_at):
        """ABS & TC ticks on top, lock & spin marks at bottom"""
        wcfg = self.wcfg
        tick = max(self.unit * 0.12, 2)
        width = max(rect.width() / max(len(samples), 1), 1)
        # Colors parsed once per frame, not once per sample (hundreds while ABS or TC active)
        abs_color = QColor(wcfg["abs_active_color"])
        tc_color = QColor(wcfg["tc_active_color"])
        lock_color = QColor(wcfg["wheel_lock_color"])
        spin_color = QColor(wcfg["wheel_spin_color"])
        for sample in samples:
            x = x_at(sample.time)
            if sample.abs_active:
                painter.fillRect(QRectF(x, rect.top(), width, tick), abs_color)
            if sample.tc_active:
                painter.fillRect(QRectF(x, rect.top() + tick, width, tick), tc_color)
            if sample.slip:
                color = lock_color if sample.slip == "lock" else spin_color
                painter.fillRect(QRectF(x, rect.bottom() - tick, width, tick), color)

    def draw_trace_caption(self, painter: QPainter, rect: QRectF, incident):
        """Incident summary (frozen) or recording mark (live), with incident count"""
        wcfg = self.wcfg
        caption_h = min(self.unit * 0.8, rect.height() / 2)
        left = QRectF(rect.left() + self.unit * 0.25, rect.top(), rect.width() * 0.7, caption_h)
        right = QRectF(rect.right() - rect.width() * 0.3 - self.unit * 0.25, rect.top(),
                       rect.width() * 0.3, caption_h)
        align_left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        align_right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        count = len(self.recorder.incidents)
        if incident is not None:
            painter.setPen(QColor(wcfg["incident_color"]))
            text = f"{self.text['impact']} L{incident.lap} {incident.peak_g:.1f}g {incident.direction}".rstrip()
            position = index_of(self.recorder.incidents, incident)
            if count > 1 and position >= 0:  # which one, when browsing with the hotkey
                text += f" {position + 1}/{count}"
            self.draw_fit_text(painter, left, text, self.font_label, align_left)
        else:
            painter.setPen(translucent(wcfg["incident_color"], 200))
            self.draw_fit_text(painter, right, f"● {count}" if count else "●", self.font_label, align_right)

    def draw_event_log(self, painter: QPainter):
        """Newest event on top"""
        wcfg = self.wcfg
        events = list(self.event_log.events)[::-1]
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for row, event in zip(self.event_rows, events):
            painter.setPen(QColor(wcfg["incident_color"] if event.critical else wcfg["font_color_event_log"]))
            self.draw_fit_text(painter, row, format_event(event), self.font_small, align)
