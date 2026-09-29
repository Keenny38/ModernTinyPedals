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
Black box widget, draw RPM LEDs and center column items
"""

from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from .._painter import fill_chip, fill_chip_gradient, fill_glow
from .common import CENTER_ITEMS, LAYOUT_NORMAL, LAYOUT_VERTICAL, qcolor
from .state import (
    level_text,
)


class CenterPainter:
    """Draw RPM LEDs and center column items"""

    def ordered_center_items(self) -> list[str]:
        """Enabled center items sorted by display order"""
        enabled = {
            "abs": self.wcfg["show_abs_indicator"],
            "tc": self.wcfg["show_tc_indicator"],
            "brake_bias": self.wcfg["show_brake_bias"],
            "brake_migration": self.wcfg["show_brake_migration"],
            "locking": self.wcfg["show_wheel_locking"],
            "delta": self.wcfg["show_delta_best"],
            "laptime": self.wcfg["show_laptime"],
            "pit_limiter": self.wcfg["show_pit_limiter_indicator"],
            "gear": self.wcfg["show_gear"],
            "speed": self.wcfg["show_speed"],
            "rpm": self.wcfg["show_rpm"],
            "pedals": self.wcfg["show_pedal_bars"],
        }
        items = [name for name in CENTER_ITEMS if enabled[name]]
        return sorted(items, key=lambda name: (self.wcfg[f"display_order_{name}"], CENTER_ITEMS.index(name)))

    def item_height(self, name: str) -> float:
        """Height of center item (without gap)"""
        unit = self.unit
        if name == "gear":
            return unit * 0.95 * self.gear_scale
        if name == "speed":
            return unit * 1.05 * self.speed_scale
        if name == "rpm":
            return unit * 1.05 * self.rpm_scale + unit * 0.3
        if name == "pedals":
            return unit * 0.7
        return unit * 1.05

    def center_height(self) -> float:
        """Height needed by center column (ABS & TC counted as shown)"""
        gap = self.unit * 0.2
        return sum(self.item_height(name) + gap for name in self.center_order)

    def draw_leds(self, painter: QPainter, rect: QRectF):
        """RPM LEDs: light up from green to red, all flash over shift point, soft glow when lit"""
        wcfg = self.wcfg
        count = min(max(int(wcfg["number_of_rpm_leds"]), 3), 20)
        ratio = self.rpm / self.rpm_max if self.rpm_max > 0 else 0
        start = min(max(wcfg["rpm_led_start_ratio"], 0), 0.95)
        redline = max(wcfg["rpm_redline_ratio"], start + 0.01)
        over = ratio >= redline
        flash_off = over and self.flash_off()
        gap = rect.height() * 0.3
        led_w = (rect.width() - gap * (count - 1)) / count
        inactive = wcfg["indicator_inactive_color"]
        glow_pad = rect.height() * 0.35
        for led in range(count):
            led_rect = QRectF(rect.left() + led * (led_w + gap), rect.top(), led_w, rect.height())
            threshold = start + led / count * (redline - start)
            if over:
                lit = not flash_off
                color = wcfg["rpm_led_shift_color"] if lit else inactive
            elif ratio >= threshold:
                lit = True
                position = led / max(count - 1, 1)
                key = "rpm_led_low_color" if position < 0.5 else "rpm_led_mid_color" if position < 0.8 else "rpm_led_high_color"
                color = wcfg[key]
            else:
                lit = False
                color = inactive
            if lit:
                fill_glow(painter, led_rect.adjusted(-glow_pad, -glow_pad, glow_pad, glow_pad), color)
            fill_chip(painter, led_rect, color)

    def flash_off(self) -> bool:
        """Flash state (off phase) for shift warning"""
        interval = max(self.wcfg["shift_flash_interval"], 0.05)
        return int(monotonic() / interval) % 2 == 1

    def visible_center_items(self) -> list[str]:
        """Center items to draw now: ABS & TC only if car has them, pit & limiter only while active"""
        return [
            name for name in self.center_order
            if not (
                (name == "abs" and not self.has_abs)
                or (name == "tc" and not self.has_tc)
                or (name == "pit_limiter" and not (self.in_pits or self.limiter))
            )
        ]

    def draw_center(self, painter: QPainter, rect: QRectF):
        """Center column, items in user defined order

        Column height is reserved for every enabled item, so the widget never resizes during a
        session. Hidden items leave free space, which is shared above and below in vertical layout.
        """
        gap = self.unit * 0.2
        items = self.visible_center_items()
        top = rect.top()
        if self.layout_mode == LAYOUT_VERTICAL:
            used = sum(self.item_height(name) + gap for name in items)
            top += max(rect.height() - used, 0) / 2
        for name in items:
            height = self.item_height(name)
            if name == "pedals":  # pedals stick to bottom in normal layout
                item_top = rect.bottom() - height if self.layout_mode == LAYOUT_NORMAL and name == items[-1] else top
            else:
                item_top = top
            self.draw_center_item(painter, name, QRectF(rect.left(), item_top, rect.width(), height))
            top += height + gap

    def draw_center_item(self, painter: QPainter, name: str, rect: QRectF):
        wcfg = self.wcfg
        unit = self.unit
        if name == "abs":
            self.draw_indicator(painter, rect, level_text(self.text["abs"], self.abs_level),
                                self.abs_active, wcfg["abs_active_color"])
        elif name == "tc":
            self.draw_indicator(painter, rect,
                                level_text(self.text["tc"], self.tc_level, self.tc_cut_level, self.tc_slip_level),
                                self.tc_active, wcfg["tc_active_color"])
        elif name == "brake_bias":
            self.draw_info_row(painter, rect, self.text["brake_bias"], f"{self.brake_bias * 100:.1f}")
        elif name == "brake_migration":
            self.draw_info_row(painter, rect, self.text["brake_migration"], f"{self.brake_migration:.1f}")
        elif name == "delta":
            gain = self.delta_best < 0
            color = wcfg["delta_gain_color" if gain else "delta_loss_color"]
            self.draw_info_row(painter, rect, self.text["delta"], f"{self.delta_best:+.3f}", color)
        elif name == "laptime":
            self.draw_info_row(painter, rect, self.text["laptime"], calc.sec2laptime(self.laptime_current)[:8])
        elif name == "locking":
            self.draw_info_row(painter, rect, self.text["locking"], f"{self.locking_front:.0f}/{self.locking_rear:.0f}")
        elif name == "pit_limiter":
            # Only active indicators, sharing the row
            active = [
                (text, color) for text, color, state in (
                    (self.text["pit"], wcfg["pit_active_color"], self.in_pits),
                    (self.text["limiter"], wcfg["limiter_active_color"], self.limiter),
                ) if state
            ]
            gap = unit * 0.2
            item_w = (rect.width() - gap * (len(active) - 1)) / max(len(active), 1)
            for index, (text, color) in enumerate(active):
                item = QRectF(rect.left() + index * (item_w + gap), rect.top(), item_w, rect.height())
                self.draw_indicator(painter, item, text, True, color)
        elif name == "gear":
            painter.setPen(qcolor(self.gear_color()))
            self.draw_fit_text(painter, rect, self.gear_text(), self.font_gear)
        elif name == "speed":
            text = f"{self.unit_speed(self.speed):.0f} {self.speed_label}"
            if self.justify_center:
                self.draw_info_row(painter, rect, self.text["speed"], text)
            else:
                painter.setPen(self.pen_text)
                self.draw_fit_text(painter, rect, text, self.font_speed)
        elif name == "rpm":
            text_rect = QRectF(rect.left(), rect.top(), rect.width(), rect.height() - unit * 0.3)
            if self.justify_center:
                self.draw_info_row(painter, text_rect, self.text["rpm"], f"{self.rpm:.0f}")
            else:
                painter.setPen(self.pen_text)
                self.draw_fit_text(painter, text_rect, f"{self.rpm:.0f} rpm", self.font_rpm)
            bar = QRectF(rect.left(), text_rect.bottom(), rect.width(), unit * 0.3)
            fill_chip(painter, bar, wcfg["indicator_inactive_color"])
            if self.rpm_max > 0 and self.rpm > 0:
                ratio = min(self.rpm / self.rpm_max, 1)
                color = wcfg["rpm_redline_color" if ratio >= wcfg["rpm_redline_ratio"] else "rpm_bar_color"]
                fill_chip_gradient(painter, QRectF(bar.left(), bar.top(), bar.width() * ratio, bar.height()), color)
        elif name == "pedals":
            gap = unit * 0.1
            bar_h = (rect.height() - gap) / 2
            for index, (value, color) in enumerate(
                ((self.throttle, wcfg["throttle_color"]), (self.brake, wcfg["brake_color"]))
            ):
                back = QRectF(rect.left(), rect.top() + index * (bar_h + gap), rect.width(), bar_h)
                fill_chip(painter, back, wcfg["indicator_inactive_color"])
                if value > 0.001:
                    fill_chip_gradient(
                        painter, QRectF(back.left(), back.top(), back.width() * min(value, 1), bar_h), color)

    def gear_color(self) -> str:
        """Gear text color by RPM: low, mid, shift (flash over shift point)"""
        wcfg = self.wcfg
        if not wcfg["enable_gear_rpm_color"] or self.rpm_max <= 0:
            return wcfg["font_color_gear"]
        ratio = self.rpm / self.rpm_max
        if ratio >= wcfg["rpm_redline_ratio"]:
            if wcfg["enable_shift_flash"] and self.flash_off():
                return wcfg["font_color_gear"]
            return wcfg["gear_color_shift"]
        if ratio >= wcfg["gear_mid_rpm_ratio"]:
            return wcfg["gear_color_mid"]
        return wcfg["gear_color_low"]

    def gear_text(self) -> str:
        if self.gear > 0:
            return str(self.gear)
        return "R" if self.gear < 0 else "N"

    def draw_indicator(self, painter: QPainter, rect: QRectF, text: str, active: bool, color: str):
        fill_chip(painter, rect, color if active else self.wcfg["indicator_inactive_color"])
        painter.setPen(self.pen_indicator_active if active else self.pen_indicator)
        self.draw_fit_text(painter, rect.adjusted(rect.width() * 0.04, 0, -rect.width() * 0.04, 0), text, self.font())
