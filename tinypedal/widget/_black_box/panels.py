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
Black box widget, draw battery gauge and bottom info rows
"""

from __future__ import annotations

import math
from time import monotonic
from typing import Any, NamedTuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter

from .._painter import fill_chip, fill_chip_gradient, fill_rect
from .common import qcolor
from .state import (
    LAPS_LABEL,
)

HIGHLIGHT_COLOR = QColor(255, 255, 255, 28)


class Gauge(NamedTuple):
    """Fuel or energy level gauge data"""

    level: float
    capacity: float
    start: float  # level at stint start
    needed: float  # amount to add to finish (negative if more than needed)
    laps: float  # estimated laps left
    text: str  # level & laps
    needed_text: str


class PanelPainter:
    """Draw battery gauge and bottom info rows"""

    # Attributes set by black box widget class (widget/black_box.py) or other parts
    battery_charge: Any
    battery_highlight: Any
    battery_scale: Any
    battery_state: Any
    battery_warning: Any
    bottom_rows: Any
    depth_effects: Any
    draw_fit_text: Any
    energy: Any
    energy_available: Any
    energy_capacity: Any
    energy_laps: Any
    energy_start: Any
    font: Any
    font_battery: Any
    font_label: Any
    font_small: Any
    fuel: Any
    fuel_capacity: Any
    fuel_label: Any
    fuel_laps: Any
    fuel_start: Any
    has_hybrid: Any
    need_energy_rows: Any
    need_fuel_rows: Any
    pen_info_label: Any
    pen_text: Any
    pres_decimals: Any
    pulse: Any
    pulsed_color: Any
    refill: Any
    refuel: Any
    row_damper: Any
    row_energy: Any
    row_fuel: Any
    row_stint: Any
    stint_has_previous: Any
    stint_pressure: Any
    stint_pressure_delta: Any
    stint_wear: Any
    stint_wear_delta: Any
    text: Any
    unit: Any
    unit_fuel: Any
    unit_pres: Any
    wcfg: Any
    wheels: Any

    def draw_battery_bar(self, painter: QPainter, rect: QRectF):
        """Full-height battery charge gauge, with a flowing highlight while charging or draining"""
        wcfg = self.wcfg
        fill_chip(painter, rect, wcfg["indicator_inactive_color"])
        charge = min(max(self.battery_charge, 0), 100) / 100
        fill_h = rect.height() * charge
        if fill_h >= 1:
            fill_area = QRectF(rect.left(), rect.bottom() - fill_h, rect.width(), fill_h)
            state = self.battery_state
            if self.battery_warning and self.battery_highlight:  # warning wins over flow color
                color = wcfg["warning_color_low_battery" if self.battery_warning == 1
                             else "warning_color_high_battery"]
            elif state == 3:  # regen
                color = wcfg["battery_charge_color"]
            elif state == 2:  # drain
                color = wcfg["battery_discharge_color"]
            else:  # off or n/a: static, neutral fill
                color = wcfg["battery_idle_color"]
            fill_chip_gradient(painter, fill_area, color)
            if wcfg["enable_battery_bar_animation"] and state in (2, 3):
                self.draw_battery_flow(painter, fill_area, charging=state == 3)
        if wcfg["show_battery_percentage"]:
            # Readout chip rides the fill level (centered on its top edge, kept inside the gauge),
            # own background so it stays legible regardless of the fill color behind it. Chip
            # follows the text size, capped so it never takes more than a third of the gauge.
            label_h = min(self.unit * self.battery_scale * 1.2, rect.height() / 3)
            level_y = rect.bottom() - rect.height() * charge
            label_top = min(max(level_y - label_h / 2, rect.top()), rect.bottom() - label_h)
            label_rect = QRectF(rect.left(), label_top, rect.width(), label_h)
            fill_chip(painter, label_rect, wcfg["info_background_color"])
            painter.setPen(self.pen_text)
            # Dash instead of "0" on a car without hybrid system, so an empty gauge is not
            # mistaken for a flat battery (or for the widget being broken)
            text = f"{self.battery_charge:.0f}" if self.has_hybrid else "-"
            self.draw_fit_text(painter, label_rect, text, self.font_battery)

    def draw_battery_flow(self, painter: QPainter, rect: QRectF, charging: bool):
        """Translucent bands scrolling up while charging, down while draining, suggesting flow"""
        band_h = max(rect.width() * 0.7, 3)
        spacing = band_h * 2.4
        speed = max(self.wcfg["battery_bar_animation_speed"], 0) * 40  # pixels per second
        direction = -1 if charging else 1
        phase = (monotonic() * speed * direction) % spacing
        painter.save()
        painter.setClipRect(rect)
        glow = QColor(255, 255, 255, 55)
        y = rect.top() - spacing + phase
        while y < rect.bottom() + spacing:
            painter.fillRect(QRectF(rect.left(), y, rect.width(), band_h), glow)
            y += spacing
        painter.restore()

    def draw_bottom_rows(self, painter: QPainter):
        """Fuel gauge, virtual energy gauge (full row width), stint comparison"""
        rows = iter(self.bottom_rows)
        if self.row_fuel:
            left, right = next(rows)
            self.draw_level_gauge(
                painter, left.united(right), self.text["fuel"], self.fuel_gauge(), self.wcfg["fuel_gauge_color"])
        if self.row_energy:
            left, right = next(rows)
            if self.energy_available:  # row kept on cars without virtual energy unless auto resize
                self.draw_level_gauge(
                    painter, left.united(right), self.text["energy"], self.energy_gauge(),
                    self.wcfg["energy_gauge_color"])
            else:
                fill_rect(painter, left.united(right), self.wcfg["info_background_color"])
        if self.row_stint:
            (rect_left, rect_right), (left_item, right_item) = next(rows), self.stint_row()
            self.draw_info_row(painter, rect_left, *left_item)
            self.draw_info_row(painter, rect_right, *right_item)
        if self.row_damper:
            left, right = next(rows)
            self.draw_damper_histogram(painter, left.united(right))

    def draw_damper_histogram(self, painter: QPainter, row: QRectF):
        """Time share of damper speed zones this lap, per wheel: fast & slow rebound, slow & fast bump

        The base tool of damper setup: rebound on the left, bump on the right of each wheel,
        slow zones lighter, fast zones in full color.
        """
        wcfg = self.wcfg
        unit = self.unit
        fill_rect(painter, row, wcfg["info_background_color"])
        rebound, bump = QColor(wcfg["suspension_rebound_color"]), QColor(wcfg["suspension_compression_color"])
        colors = (rebound, rebound.lighter(150), bump.lighter(150), bump)
        group_w = row.width() / 4
        label_h = row.height() * 0.35
        align = Qt.AlignmentFlag.AlignCenter
        for index, (name, wheel) in enumerate(zip(("FL", "FR", "RL", "RR"), self.wheels)):
            group = QRectF(row.left() + index * group_w, row.top(), group_w, row.height())
            painter.setPen(self.pen_info_label)
            self.draw_fit_text(painter, QRectF(group.left(), group.top(), group.width(), label_h), name,
                               self.font_label, align)
            area = group.adjusted(unit * 0.2, label_h, -unit * 0.2, -unit * 0.08)
            bar_w = area.width() / 4
            for bin_index, (share, color) in enumerate(zip(wheel.damper_shares, colors)):
                height = area.height() * min(max(share, 0.0), 1.0)
                if height >= 0.5:
                    painter.fillRect(QRectF(area.left() + bin_index * bar_w + bar_w * 0.1, area.bottom() - height,
                                            bar_w * 0.8, height), color)

    def fuel_gauge(self) -> Gauge:
        return Gauge(
            self.fuel, self.fuel_capacity, self.fuel_start, self.refuel, self.fuel_laps,
            f"{self.unit_fuel(self.fuel):.1f} {self.fuel_label} · {self.fuel_laps:.1f} {LAPS_LABEL}",
            f"{self.unit_fuel(self.refuel):+.1f} {self.fuel_label}",
        )

    def energy_gauge(self) -> Gauge:
        return Gauge(
            self.energy, self.energy_capacity, self.energy_start, self.refill, self.energy_laps,
            f"{self.energy:.0f}% · {self.energy_laps:.1f} {LAPS_LABEL}",
            f"{self.refill:+.1f}%",
        )

    def gauge_low(self) -> bool:
        """Any shown gauge below low lap threshold"""
        threshold = self.wcfg["gauge_low_lap_threshold"]
        if self.need_fuel_rows and 0 < self.fuel_laps <= threshold:
            return True
        return bool(self.need_energy_rows and self.energy_available and 0 < self.energy_laps <= threshold)

    def draw_level_gauge(self, painter: QPainter, row: QRectF, label: str, gauge: Gauge, color: str):
        """Level bar like Fuel & Virtual Energy widgets: fill to current level, start & refill marks,
        with label, level & laps, and amount to add written over it"""
        wcfg = self.wcfg
        unit = self.unit
        fill_rect(painter, row, wcfg["info_background_color"])
        low = 0 < gauge.laps <= wcfg["gauge_low_lap_threshold"]
        # Module data may be non finite (division by a near zero consumption): no bar then
        if gauge.capacity > 0 and all(map(math.isfinite, (gauge.level, gauge.capacity, gauge.start, gauge.needed))):
            fill = QColor(self.pulsed_color(wcfg["gauge_low_color"], self.pulse()) if low else qcolor(color))
            fill.setAlpha(min(fill.alpha(), 120))
            ratio = min(max(gauge.level / gauge.capacity, 0.0), 1.0)
            if ratio > 0:  # square fill, the gauge is the row itself
                level_rect = QRectF(row.left(), row.top(), row.width() * ratio, row.height())
                shade = QLinearGradient(level_rect.left(), 0, level_rect.right(), 0)
                shade.setColorAt(0.0, fill.darker(115))
                shade.setColorAt(1.0, fill.lighter(125))
                painter.fillRect(level_rect, shade)
            mark_w = max(unit * 0.09, 2)
            for show, value, mark_color in (
                (wcfg["show_gauge_start_mark"], gauge.start, wcfg["gauge_start_mark_color"]),
                (wcfg["show_gauge_refill_mark"], gauge.level + gauge.needed, wcfg["gauge_refill_mark_color"]),
            ):
                if show and value > 0:
                    x = row.left() + row.width() * min(value / gauge.capacity, 1.0)
                    x = min(max(x - mark_w / 2, row.left()), row.right() - mark_w)
                    painter.fillRect(QRectF(x, row.top(), mark_w, row.height()), qcolor(mark_color))
        if self.depth_effects:
            painter.fillRect(QRectF(row.left(), row.top(), row.width(), max(unit * 0.05, 1)), HIGHLIGHT_COLOR)
        # Text: label left, amount to add right, level & laps before it
        inner = row.adjusted(unit * 0.25, 0, -unit * 0.25, 0)
        align_left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        align_right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.setFont(self.font_label)
        painter.setPen(self.pen_info_label)
        painter.drawText(inner, align_left, label)
        label_w = painter.fontMetrics().horizontalAdvance(label) + unit * 0.3
        needed_w = inner.width() * 0.3
        needed_rect = QRectF(inner.right() - needed_w, inner.top(), needed_w, inner.height())
        painter.setPen(qcolor(wcfg["gauge_refill_mark_color"]) if gauge.needed > 0 else self.pen_text)
        self.draw_fit_text(painter, needed_rect, gauge.needed_text, self.font_small, align_right)
        value_rect = QRectF(inner.left() + label_w, inner.top(),
                            max(needed_rect.left() - unit * 0.3 - inner.left() - label_w, 1), inner.height())
        painter.setPen(qcolor(wcfg["gauge_low_color"]) if low else self.pen_text)
        self.draw_fit_text(painter, value_rect, gauge.text, self.font(), align_right)

    def stint_row(self) -> tuple:
        """Current stint average wear per lap & pressure, with difference to previous stint"""
        wear, pressure = self.stint_wear, self.stint_pressure
        wear_text = f"{wear:.2f}" if wear else "-"
        pres_text = f"{self.unit_pres(pressure):.{self.pres_decimals}f}" if pressure else "-"
        if self.stint_has_previous:
            if self.stint_wear_delta:
                wear_text += f" {self.stint_wear_delta:+.2f}"
            if self.stint_pressure_delta:
                pres_delta = self.unit_pres(pressure) - self.unit_pres(pressure - self.stint_pressure_delta)
                pres_text += f" {pres_delta:+.{self.pres_decimals}f}"
        return (self.text["stint_wear"], wear_text), (self.text["stint_pressure"], pres_text)

    def draw_info_row(self, painter: QPainter, row: QRectF, label: str, value: str, color: str = ""):
        """Info row: label on left, value on right"""
        unit = self.unit
        fill_rect(painter, row, self.wcfg["info_background_color"])
        if self.depth_effects:  # thin light edge on top, panel reads as slightly raised
            painter.fillRect(QRectF(row.left(), row.top(), row.width(), max(unit * 0.05, 1)), HIGHLIGHT_COLOR)
        inner = row.adjusted(unit * 0.25, 0, -unit * 0.25, 0)
        painter.setFont(self.font_label)
        painter.setPen(self.pen_info_label)
        painter.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        label_w = painter.fontMetrics().horizontalAdvance(label)
        painter.setPen(qcolor(color) if color else self.pen_text)
        value_rect = inner.adjusted(label_w + unit * 0.3, 0, 0, 0)
        self.draw_fit_text(painter, value_rect, value, self.font(),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
