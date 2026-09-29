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
Black box widget, draw tyres & brakes
"""

from __future__ import annotations

import math
from time import monotonic

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from .._painter import fill_chip
from .common import qcolor
from .state import (
    PREFIX_CAMBER,
    PREFIX_CARCASS,
    PREFIX_LOAD,
    PREFIX_RIDE_HEIGHT,
    PREFIX_SLIP_ANGLE,
    PREFIX_WEAR_PER_LAP,
    READING_CAMBER,
    READING_CARCASS,
    READING_COMPOUND,
    READING_END_STINT,
    READING_LOAD,
    READING_PRESSURE,
    READING_RIDE_HEIGHT,
    READING_SLIP_ANGLE,
    READING_STATUS,
    READING_TEMPERATURE,
    READING_WEAR,
    READING_WEAR_PER_LAP,
    TREND_SYMBOLS,
    WheelState,
    fit_readings,
)

SHADOW_COLOR = QColor(0, 0, 0, 90)


class ColorFade:
    """Smooth change from the displayed color to a new one over a duration (seconds)

    Heatmap colors step from one grade to the next; fading hides the step, so a tyre
    warming up reads as a continuous change instead of flickering between two grades.
    """

    __slots__ = ("duration", "start", "source", "target", "target_name")

    def __init__(self, duration: float):
        self.duration = max(duration, 0.0)
        self.start = -math.inf
        self.source = QColor()
        self.target = QColor()
        self.target_name = ""

    def set(self, name: str, now: float):
        """New target color, fading from the color displayed now"""
        if name == self.target_name:
            return
        first = not self.target_name
        self.source = self.color(now)
        self.target = QColor(name)
        self.target_name = name
        self.start = -math.inf if first or self.duration <= 0 else now

    def color_of(self, name: str, now: float) -> QColor:
        """Color displayed now for target color name (starts a fade if the name changed)"""
        self.set(name, now)
        return self.color(now)

    def active(self, now: float) -> bool:
        return now - self.start < self.duration

    def color(self, now: float) -> QColor:
        """Color displayed now"""
        if not self.active(now):
            return self.target
        ratio = (now - self.start) / self.duration
        source, target = self.source, self.target
        return QColor.fromRgbF(
            source.redF() + (target.redF() - source.redF()) * ratio,
            source.greenF() + (target.greenF() - source.greenF()) * ratio,
            source.blueF() + (target.blueF() - source.blueF()) * ratio,
            source.alphaF() + (target.alphaF() - source.alphaF()) * ratio,
        )


class WheelPainter:
    """Draw tyres & brakes"""

    def pulse(self, now: float | None = None) -> float:
        """Alert intensity, 0.35 to 1, pulsing at alert_pulse_frequency (1 if pulse disabled)"""
        if not self.alert_pulse:
            return 1.0
        phase = math.sin(2 * math.pi * self.pulse_frequency * (monotonic() if now is None else now))
        return 0.675 + 0.325 * phase

    def pulsed_pen(self, pen: QPen, strength: float) -> QPen:
        if strength >= 1:
            return pen
        color = QColor(pen.color())
        color.setAlphaF(color.alphaF() * strength)
        pulsed = QPen(pen)
        pulsed.setColor(color)
        return pulsed

    def pulsed_color(self, name: str, strength: float) -> QColor:
        if strength >= 1:
            return qcolor(name)
        color = QColor(name)
        color.setAlphaF(color.alphaF() * strength)
        return color

    def draw_tyre(self, painter: QPainter, rect: QRectF, wheel: WheelState, index: int = 0):
        wcfg = self.wcfg
        local = self.local_tyre
        path = self.path_tyre
        now = monotonic()
        strength = self.pulse(now) if (wheel.warning or wheel.status) else 1.0
        # Tyre turned with wheel angle (left / right)
        painter.save()
        painter.translate(rect.center())
        painter.rotate(wheel.steer)
        if wheel.status == "detached":
            painter.setPen(self.pulsed_pen(self.pen_detached, strength))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()
            painter.setPen(qcolor(wcfg["wheel_detached_color"]))
            self.draw_fit_text(painter, rect, self.text["detached"], self.font())
            return
        if self.depth_effects:  # soft drop shadow, below and right of tyre
            painter.fillPath(path.translated(self.shadow_offset, self.shadow_offset * 1.3), SHADOW_COLOR)
        if wcfg["show_tyre_temperature_bands"]:
            painter.save()
            painter.setClipPath(path)
            band_w = local.width() / 3
            for band, color in enumerate(wheel.ico_colors):
                painter.fillRect(QRectF(local.left() + band * band_w, local.top(), band_w + 0.5, local.height()),
                                 qcolor(color))
            painter.restore()
        else:
            painter.fillPath(path, self.tyre_fades[index].color_of(wheel.tyre_color, now))
        if self.depth_effects:  # rounded rubber look: light on one side, shade on the other
            painter.fillPath(path, self.brush_gloss)
        if wheel.warning:
            painter.setPen(self.pulsed_pen(self.pen_lock if wheel.warning == "lock" else self.pen_spin, strength))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()

        # Text lines (upright): (priority, text, font, weight in height, pill color, text color)
        lines = []
        if wcfg["show_tyre_compound"] and wheel.compound:
            lines.append((READING_COMPOUND, wheel.compound, self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_temperature"]:
            text = self.format_temp(wheel.tyre_temp)
            if self.show_temp_trend:
                text += TREND_SYMBOLS[wheel.temp_trend]
            lines.append((READING_TEMPERATURE, text, self.font(), 1.3, "", self.tyre_phase_color(index, wheel)))
        if wcfg["show_tyre_pressure"]:
            text = f"{self.unit_pres(wheel.pressure):.{self.pres_decimals}f}"
            if self.show_pres_trend:
                text += TREND_SYMBOLS[wheel.pressure_trend]
            color = self.pressure_color(wheel.pressure, index)
            pill = wcfg["tyre_pressure_warning_background_color"] if color else ""
            lines.append((READING_PRESSURE, text, self.font_small, 1.0, pill, color))
        if wcfg["show_tyre_wear"]:
            low = wheel.tread < wcfg["tyre_wear_warning_threshold"]
            lines.append((READING_WEAR, f"{wheel.tread:.0f}%", self.font_small, 1.0,
                          wcfg["tyre_wear_warning_color"] if low else "",
                          wcfg["font_color_tyre_wear_warning"] if low else ""))
        if wcfg["show_tyre_wear_end_stint"] and wheel.tread_end_known:
            lines.append((READING_END_STINT, f"→{max(wheel.tread_end, 0):.0f}%", self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_carcass_temperature"]:
            lines.append((READING_CARCASS, f"{PREFIX_CARCASS}{self.format_temp(wheel.carcass_temp)}",
                          self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_wear_per_lap"]:
            lines.append((READING_WEAR_PER_LAP, f"{PREFIX_WEAR_PER_LAP}{max(wheel.wear_per_lap, 0):.2f}",
                          self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_load"]:
            lines.append((READING_LOAD, f"{PREFIX_LOAD}{wheel.load_ratio:.0f}%", self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_slip_angle"]:
            lines.append((READING_SLIP_ANGLE, f"{PREFIX_SLIP_ANGLE}{wheel.slip_angle:+.1f}",
                          self.font_small, 0.9, "", ""))
        if wcfg["show_wheel_camber"]:
            lines.append((READING_CAMBER, f"{PREFIX_CAMBER}{wheel.camber:+.1f}", self.font_small, 0.9, "", ""))
        if wcfg["show_ride_height"]:
            lines.append((READING_RIDE_HEIGHT, f"{PREFIX_RIDE_HEIGHT}{wheel.ride_height:.0f}",
                          self.font_small, 0.9, "", ""))
        if wheel.status in ("puncture", "flat"):
            text = self.text["puncture" if wheel.status == "puncture" else "flat_spot"]
            color = wcfg["wheel_puncture_color" if wheel.status == "puncture" else "wheel_flat_spot_color"]
            lines.append((READING_STATUS, text, self.font_small, 1.0, color, "#000000"))
        usable = rect.height() * 0.88
        lines = fit_readings(lines, usable, self.unit)
        total = sum(line[3] for line in lines) or 1
        top = rect.top() + rect.height() * 0.06
        for priority, text, font, weight, pill_color, text_color in lines:
            line_rect = QRectF(rect.left(), top, rect.width(), usable * weight / total)
            top += line_rect.height()
            font = self.fitted_font(painter, font, text, line_rect.width() * 0.9, line_rect.height() * 1.1)
            painter.setFont(font)
            if pill_color:
                pill_w = min(painter.fontMetrics().horizontalAdvance(text) + self.unit * 0.3, rect.width() * 0.92)
                pill = QRectF(line_rect.center().x() - pill_w / 2, line_rect.top() + line_rect.height() * 0.08,
                              pill_w, line_rect.height() * 0.84)
                fill_chip(painter, pill, self.pulsed_color(pill_color, strength)
                          if priority == READING_STATUS else pill_color)
            painter.setPen(qcolor(text_color) if text_color else self.pen_temp)
            painter.drawText(line_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.setFont(self.font())

    def tyre_phase_color(self, index: int, wheel: WheelState) -> str:
        """Tyre temperature text color: hot, cold, warming (cold but rising), "" if in window"""
        wcfg = self.wcfg
        _, _, cold, hot = self.wheel_targets[index]
        temp = wheel.tyre_temp
        if temp < -100:  # no data
            return ""
        if 0 < hot <= temp:
            return wcfg["font_color_tyre_temperature_warning"]
        if cold > 0 and temp < cold:
            if wheel.temp_trend > 0:
                return wcfg["font_color_tyre_temperature_warming"]
            return wcfg["font_color_tyre_temperature_cold"]
        return ""

    def brake_phase_color(self, wheel: WheelState) -> str:
        """Brake temperature text color: hot or cold, heatmap color if in window"""
        wcfg = self.wcfg
        if 0 < self.brake_hot <= wheel.brake_temp:
            return wcfg["font_color_brake_temperature_hot"]
        if self.brake_cold > 0 and -100 < wheel.brake_temp < self.brake_cold:
            return wcfg["font_color_brake_temperature_cold"]
        return wheel.brake_color

    def pressure_color(self, pressure: float, index: int = 0) -> str:
        """Text color if pressure out of target range (kPa), "" if in range or disabled

        Target range is the compound one if set in tyre_target_by_compound.
        """
        wcfg = self.wcfg
        if not wcfg["enable_tyre_pressure_target"] or pressure <= 0:
            return ""
        p_min, p_max, _, _ = self.wheel_targets[index]
        if pressure < p_min:
            return wcfg["tyre_pressure_low_color"]
        if pressure > p_max:
            return wcfg["tyre_pressure_high_color"]
        return ""

    def draw_disc(self, painter: QPainter, index: int, rect: QRectF, wheel: WheelState):
        """Brake: thin vertical bar (disc seen from above) next to tyre, colored by brake temperature,
        with temperature (and remaining thickness) written beside it

        The bar turns with the wheel, around the tyre center, so the disc stays bolted to the
        wheel instead of floating beside a steered tyre. Readings stay upright and in place.
        """
        wcfg = self.wcfg
        is_right = index % 2  # FL, FR, RL, RR: odd index is on right side
        bar_w, bar_gap = self.brake_bar_w, self.brake_bar_gap
        if is_right:  # tyre on right side of brake
            bar = QRectF(rect.right() - bar_w, rect.top(), bar_w, rect.height())
            text_rect = QRectF(rect.left(), rect.top(), rect.width() - bar_w - bar_gap, rect.height())
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:
            bar = QRectF(rect.left(), rect.top(), bar_w, rect.height())
            text_rect = QRectF(rect.left() + bar_w + bar_gap, rect.top(), rect.width() - bar_w - bar_gap, rect.height())
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        radius = bar_w / 2
        path = QPainterPath()
        path.addRoundedRect(bar, radius, radius)
        if wheel.steer:
            pivot = self.rects_tyre[index].center()
            painter.save()
            painter.translate(pivot.x(), pivot.y())
            painter.rotate(wheel.steer)
            painter.translate(-pivot.x(), -pivot.y())
            painter.fillPath(path, self.brake_fades[index].color_of(wheel.brake_color, monotonic()))
            painter.restore()
        else:
            painter.fillPath(path, self.brake_fades[index].color_of(wheel.brake_color, monotonic()))
        # Temperature, remaining thickness and pressure share the text area, tallest first
        rows = []
        if wcfg["show_brake_temperature"]:
            rows.append((self.format_temp(wheel.brake_temp), self.font(), self.brake_phase_color(wheel), 1.3))
        if wcfg["show_brake_wear"] and wheel.brake_wear_known:
            low = wheel.brake_wear < wcfg["brake_wear_warning_threshold"]
            color = wcfg["font_color_brake_wear_warning"] if low else wcfg["font_color"]
            rows.append((f"{max(wheel.brake_wear, 0):.0f}%", self.font_small, color, 1.0))
        if wcfg["show_brake_pressure"]:
            rows.append((f"{wheel.brake_pressure:.0f}%", self.font_small,
                         wcfg["brake_pressure_color"], 1.0))
        if not rows:
            return
        total = sum(row[3] for row in rows)
        top = text_rect.top()
        for text, font, color, weight in rows:
            row_h = text_rect.height() * weight / total
            painter.setPen(qcolor(color))
            self.draw_fit_text(painter, QRectF(text_rect.left(), top, text_rect.width(), row_h), text, font, align)
            top += row_h
