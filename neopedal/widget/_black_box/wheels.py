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
Black box widget, draw tyres & brakes
"""

from __future__ import annotations

import math
from time import monotonic
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from .._painter import fill_chip
from .common import qcolor
from .drawn import motion_length, motion_steps
from .state import (
    PREFIX_BOTTOMING,
    PREFIX_BUMPS,
    PREFIX_CAMBER,
    PREFIX_CAMBER_SPREAD,
    PREFIX_CARCASS,
    PREFIX_HEAVE,
    PREFIX_LOAD,
    PREFIX_RIDE_HEIGHT,
    PREFIX_SLIP_ANGLE,
    PREFIX_TRAVEL,
    PREFIX_WEAR_PER_LAP,
    READING_BOTTOMING,
    READING_BUMPS,
    READING_CAMBER,
    READING_CAMBER_SPREAD,
    READING_CARCASS,
    READING_COMPOUND,
    READING_END_STINT,
    READING_HEAVE,
    READING_LOAD,
    READING_PRESSURE,
    READING_PRESSURE_RANGE,
    READING_RIDE_HEIGHT,
    READING_SLIP_ANGLE,
    READING_STATUS,
    READING_TEMPERATURE,
    READING_TRAVEL,
    READING_WEAR,
    READING_WEAR_PER_LAP,
    TREND_SYMBOLS,
    WheelState,
    fit_readings,
)

if TYPE_CHECKING:
    from ...template.widget_config_types import BlackBoxConfig

SHADOW_COLOR = QColor(0, 0, 0, 90)
LAPS_SHORT = "L"  # brake laps left
GRAVITY = 9.80665  # N per kg


class ColorFade:
    """Smooth change from the displayed color to a new one over a duration (seconds)

    Heatmap colors step from one grade to the next; fading hides the step, so a tyre
    warming up reads as a continuous change instead of flickering between two grades.
    """

    __slots__ = ("duration", "start", "source", "target", "target_name", "pending")

    def __init__(self, duration: float):
        self.duration = max(duration, 0.0)
        self.start = -math.inf
        self.source = QColor()
        self.target = QColor()
        self.target_name = ""
        self.pending = False  # fade started or still running at last update: final color not repainted yet

    def set(self, name: str, now: float):
        """New target color, fading from the color displayed now"""
        if name == self.target_name:
            return
        first = not self.target_name
        self.source = self.color(now)
        self.target = QColor(name)
        self.target_name = name
        self.start = -math.inf if first or self.duration <= 0 else now
        self.pending = self.start > -math.inf

    def color_of(self, name: str, now: float) -> QColor:
        """Color displayed now for target color name (starts a fade if the name changed)"""
        self.set(name, now)
        return self.color(now)

    def active(self, now: float) -> bool:
        return now - self.start < self.duration

    def needs_repaint(self, now: float) -> bool:
        """Whether to repaint at this update: fading, or fade ended since last update (fade started at
        paint time, last repaint while fading lands short of target: final color painted once more)"""
        active = self.active(now)
        pending, self.pending = self.pending, active
        return active or pending

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

    # Attributes set by black box widget class (widget/black_box.py) or other parts
    alert_pulse: Any
    brake_bar_gap: Any
    brake_bar_w: Any
    brake_cold: Any
    brake_fades: Any
    brake_hot: Any
    brake_wear_laps: Any
    brush_gloss: Any
    depth_effects: Any
    device_scale: Any
    draw_fit_text: Any
    fitted_font: Any
    font: Any
    font_small: Any
    format_temp: Any
    local_tyre: Any
    path_tyre: Any
    pen_detached: Any
    pen_lock: Any
    pen_locked: Any
    pen_spin: Any
    pen_temp: Any
    pres_decimals: Any
    pulse_frequency: Any
    rects_tyre: Any
    shadow_offset: Any
    show_brake_peak: Any
    show_brake_trend: Any
    show_camber_spread: Any
    show_heave: Any
    show_lap_stats: Any
    show_pres_trend: Any
    show_pressure_range: Any
    show_ride_min: Any
    show_temp_trend: Any
    susp_extra: Any
    disc_swing_x: Any
    text: Any
    tick: Any
    tyre_fades: Any
    unit: Any
    unit_pres: Any
    wcfg: BlackBoxConfig
    wheel_reaches: Any
    wheel_targets: Any
    widget_font: Any

    def pulse(self, now: float | None = None) -> float:
        """Alert intensity, 0.35 to 1, pulsing at alert_pulse_frequency (1 if frequency is 0)"""
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
        painter.rotate(self.drawn_steer(index, wheel))
        if wheel.status == "detached":
            painter.setPen(self.pulsed_pen(self.pen_detached, strength))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()
            painter.setPen(qcolor(wcfg["wheel_detached_color"]))
            self.draw_fit_text(painter, rect, self.text["detached"], self.widget_font())
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
        if wheel.surface_hot:  # surface overheating (sliding): hot strip across the tread top
            painter.save()
            painter.setClipPath(path)
            strip = QColor(wcfg["font_color_tyre_temperature_warning"])
            strip.setAlphaF(0.85 * self.pulse(now))
            painter.fillRect(QRectF(local.left(), local.top(), local.width(), local.height() * 0.14), strip)
            painter.restore()
        if self.depth_effects:  # rounded rubber look: light on one side, shade on the other
            painter.fillPath(path, self.brush_gloss)
        if wheel.warning:  # locked wheel: twice as thick as past peak grip
            if wheel.warning == "locked":
                pen = self.pen_locked
            elif wheel.warning == "lock":
                pen = self.pen_lock
            else:
                pen = self.pen_spin
            painter.setPen(self.pulsed_pen(pen, strength))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()

        usable = rect.height() * 0.88
        lines = self.fitted_tyre_lines(index, wheel, usable)
        total = sum(line[3] for line in lines) or 1
        top = rect.top() + rect.height() * 0.06
        for priority, text, font, weight, pill_color, text_color, *badge in lines:
            line_rect = QRectF(rect.left(), top, rect.width(), usable * weight / total)
            top += line_rect.height()
            if badge:  # compound badge on the left of wear: room of the text shared with it
                size = line_rect.height() * 0.84
                gap = size * 0.2
                font = self.fitted_font(painter, font, text, line_rect.width() * 0.9 - size - gap,
                                        line_rect.height() * 1.1)
                painter.setFont(font)
                text_w = painter.fontMetrics().horizontalAdvance(text)
                left = line_rect.center().x() - (size + gap + text_w) / 2
                box = QRectF(left, line_rect.center().y() - size / 2, size, size)
                path = QPainterPath()
                path.addRoundedRect(box, size * 0.2, size * 0.2)
                letter, color, ink = badge[0]
                painter.fillPath(path, qcolor(color))
                painter.setPen(qcolor(ink))
                painter.setFont(self.fitted_font(painter, self.font_small, letter, size * 0.8, size))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, letter)
                painter.setFont(font)
                line_rect = QRectF(box.right() + gap, line_rect.top(), text_w, line_rect.height())
            else:
                font = self.fitted_font(painter, font, text, line_rect.width() * 0.9, line_rect.height() * 1.1)
                painter.setFont(font)
            if pill_color and priority == READING_COMPOUND:  # letter on rounded square, as in Standings
                size = line_rect.height() * 0.84
                box = QRectF(line_rect.center().x() - size / 2, line_rect.center().y() - size / 2, size, size)
                path = QPainterPath()
                path.addRoundedRect(box, size * 0.2, size * 0.2)
                painter.fillPath(path, qcolor(pill_color))
            elif pill_color:
                pill_w =min(painter.fontMetrics().horizontalAdvance(text) + self.unit * 0.3, rect.width() * 0.92)
                pill = QRectF(line_rect.center().x() - pill_w / 2, line_rect.top() + line_rect.height() * 0.08,
                              pill_w, line_rect.height() * 0.84)
                fill_chip(painter, pill, self.pulsed_color(pill_color, strength)
                          if priority == READING_STATUS else pill_color)
            painter.setPen(qcolor(text_color) if text_color else self.pen_temp)
            painter.drawText(line_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.setFont(self.widget_font())

    def fitted_tyre_lines(self, index: int, wheel: WheelState, usable: float) -> list[tuple]:
        """Readings drawn on the tyre (fit_readings), built once per update: by wheel_key, then reused by
        draw_tyre (readings dropped for room never repaint the wheel)"""
        cache = self.__dict__.setdefault("_fitted_lines", {})
        found = cache.get(index)
        if found is not None and found[0] == self.tick and found[1] == usable:
            return found[2]
        lines = fit_readings(self.tyre_lines(index, wheel), usable, self.unit)
        cache[index] = (self.tick, usable, lines)
        return lines

    def tyre_lines(self, index: int, wheel: WheelState) -> list[tuple]:
        """Text lines (upright): (priority, text, font, weight in height, pill color, text color), before
        dropping lines without room (font & weight set by priority). Wear line shown: compound badge drawn
        on its left (7th item: letter, color, ink), so wear & compound never drop each other for room"""
        wcfg = self.wcfg
        lines: list[tuple] = []
        badge = (wheel.compound, wheel.compound_color, wheel.compound_ink) if (
            wcfg["show_tyre_compound"] and wheel.compound) else None
        if badge and not wcfg["show_tyre_wear"]:
            lines.append((READING_COMPOUND, wheel.compound, self.font_small, 0.9, wheel.compound_color,
                          wheel.compound_ink))
        if wcfg["show_tyre_temperature"]:
            text = self.format_temp(wheel.tyre_temp)
            if self.show_temp_trend:
                text += TREND_SYMBOLS[wheel.temp_trend]
            lines.append((READING_TEMPERATURE, text, self.widget_font(), 1.3, "", self.tyre_phase_color(index, wheel)))
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
                          wcfg["font_color_tyre_wear_warning"] if low else "", *((badge,) if badge else ())))
        if self.show_pressure_range and wheel.pressure_min > 0:
            lines.append((READING_PRESSURE_RANGE,
                          f"{self.unit_pres(wheel.pressure_min):.{self.pres_decimals}f}-"
                          f"{self.unit_pres(wheel.pressure_max):.{self.pres_decimals}f}", self.font_small, 0.9, "", ""))
        if self.show_camber_spread:
            lines.append((READING_CAMBER_SPREAD, f"{PREFIX_CAMBER_SPREAD}{wheel.camber_spread:+.0f}",
                          self.font_small, 0.9, "", ""))
        if self.show_ride_min and wheel.ride_height_min > 0:
            lines.append((READING_BOTTOMING, f"{PREFIX_BOTTOMING}{wheel.ride_height_min:.0f}/{wheel.bottoming}",
                          self.font_small, 0.9, "",
                          wcfg["font_color_tyre_temperature_warning"] if wheel.bottoming else ""))
        if self.show_lap_stats:
            lines.append((READING_BUMPS, f"{PREFIX_BUMPS}{wheel.bumps}", self.font_small, 0.9, "",
                          wcfg["suspension_bump_color"] if wheel.bumps else ""))
            if wheel.travel_min >= 0:
                lines.append((READING_TRAVEL, f"{PREFIX_TRAVEL}{wheel.travel_min * 100:.0f}-{wheel.travel_max * 100:.0f}",
                              self.font_small, 0.9, "", ""))
        if self.show_heave:
            lines.append((READING_HEAVE, f"{PREFIX_HEAVE}{wheel.heave:.0f}", self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_wear_end_stint"] and wheel.tread_end_known:
            lines.append((READING_END_STINT, f"→{max(wheel.tread_end, 0):.0f}%", self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_carcass_temperature"]:
            lines.append((READING_CARCASS, f"{PREFIX_CARCASS}{self.format_temp(wheel.carcass_temp)}",
                          self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_wear_per_lap"]:
            lines.append((READING_WEAR_PER_LAP, f"{PREFIX_WEAR_PER_LAP}{max(wheel.wear_per_lap, 0):.2f}",
                          self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_load"]:
            lines.append((READING_LOAD, f"{PREFIX_LOAD}{self.format_load(wheel)}", self.font_small, 0.9, "", ""))
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
        return lines

    def steer_steps(self, index: int, wheel: WheelState) -> int:
        """Wheel angle in motion grid steps of the farthest point wheel part draws from its pivot"""
        return motion_steps(math.radians(wheel.steer) * self.wheel_reaches()[index], self.device_scale())

    def drawn_steer(self, index: int, wheel: WheelState) -> float:
        """Wheel angle as drawn (degrees), see drawn"""
        steps = self.steer_steps(index, wheel)
        if not steps:
            return 0.0
        return math.degrees(motion_length(steps, self.device_scale()) / self.wheel_reaches()[index])

    def wheel_key(self, index: int, wheel: WheelState) -> tuple:
        """What tyre & disc of a wheel show, see drawn"""
        if wheel.status == "detached":
            tyre: tuple = ()
        else:
            tyre = (wheel.ico_colors if self.wcfg["show_tyre_temperature_bands"] else wheel.tyre_color,
                    wheel.surface_hot, wheel.warning,
                    tuple((line[0], line[1], line[4], line[5], *line[6:]) for line in self.fitted_tyre_lines(
                        index, wheel, self.rects_tyre[index].height() * 0.88)))
        disc = (wheel.brake_color, wheel.brake_imbalance,
                tuple((row[0], row[2], row[3]) for row in self.disc_rows(wheel)))
        return self.steer_steps(index, wheel), wheel.status, tyre, disc

    def format_load(self, wheel: WheelState) -> str:
        """Tyre load: share of the car total (default), or absolute load in kg or N

        Absolute load shows aero downforce: the same share at 80 and 250 km/h is a very different load.
        """
        display = self.wcfg["tyre_load_display"]
        if display == "Kilogram":
            return f"{wheel.load / GRAVITY:.0f}"
        if display == "Newton":
            return f"{wheel.load:.0f}"
        return f"{wheel.load_ratio:.0f}%"

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
        skip = bar_w + bar_gap + self.susp_extra + self.disc_swing_x  # bar, suspension, swing room, readings
        if is_right:  # tyre on right side of brake
            bar = QRectF(rect.right() - bar_w, rect.top(), bar_w, rect.height())
            text_rect = QRectF(rect.left(), rect.top(), rect.width() - skip, rect.height())
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:
            bar = QRectF(rect.left(), rect.top(), bar_w, rect.height())
            text_rect = QRectF(rect.left() + skip, rect.top(), rect.width() - skip, rect.height())
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        radius = bar_w / 2
        path = QPainterPath()
        path.addRoundedRect(bar, radius, radius)
        painter.save()
        steer = self.drawn_steer(index, wheel)
        if steer:
            pivot = self.rects_tyre[index].center()
            painter.translate(pivot.x(), pivot.y())
            painter.rotate(steer)
            painter.translate(-pivot.x(), -pivot.y())
        painter.fillPath(path, self.brake_fades[index].color_of(wheel.brake_color, monotonic()))
        if wheel.brake_imbalance:  # far from the other disc of the axle: dashed warning outline
            painter.setPen(QPen(qcolor(wcfg["font_color_brake_temperature_hot"]), max(self.unit * 0.07, 1),
                                Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()
        rows = self.disc_rows(wheel)
        if not rows:
            return
        total = sum(row[3] for row in rows)
        top = text_rect.top()
        for text, font, color, weight in rows:
            row_h = text_rect.height() * weight / total
            painter.setPen(qcolor(color))
            self.draw_fit_text(painter, QRectF(text_rect.left(), top, text_rect.width(), row_h), text, font, align)
            top += row_h

    def disc_rows(self, wheel: WheelState) -> list[tuple]:
        """Temperature, remaining thickness and pressure sharing the text area, tallest first:
        (text, font, color, weight in height), font set by weight"""
        wcfg = self.wcfg
        rows = []
        if wcfg["show_brake_temperature"]:
            text = self.format_temp(wheel.brake_temp)
            if self.show_brake_trend:
                text += TREND_SYMBOLS[wheel.brake_trend]
            rows.append((text, self.widget_font(), self.brake_phase_color(wheel), 1.3))
        if self.show_brake_peak and wheel.brake_peak > 0:  # peak of last braking zone
            peak = wheel.brake_peak
            color = (wcfg["font_color_brake_temperature_hot"] if 0 < self.brake_hot <= peak
                     else wcfg["font_color"])
            rows.append((f"▲{self.format_temp(peak)}", self.font_small, color, 1.0))
        if wcfg["show_brake_wear"] and wheel.brake_wear_known:
            low = wheel.brake_wear < wcfg["brake_wear_warning_threshold"]
            color = wcfg["font_color_brake_wear_warning"] if low else wcfg["font_color"]
            if self.brake_wear_laps and wheel.brake_laps >= 0:
                rows.append((f"{wheel.brake_laps:.0f}{LAPS_SHORT}", self.font_small, color, 1.0))
            else:
                rows.append((f"{max(wheel.brake_wear, 0):.0f}%", self.font_small, color, 1.0))
        if wcfg["show_brake_pressure"]:
            rows.append((f"{wheel.brake_pressure:.0f}%", self.font_small,
                         wcfg["brake_pressure_color"], 1.0))
        return rows
