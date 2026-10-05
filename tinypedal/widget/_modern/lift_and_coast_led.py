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
Lift and coast LED Widget, modern design

Capsule LEDs filling with lift & coast progress (purple, brighter when critical); all lit by
wheel lock (red), ABS (blue), wheel slip (yellow) or TC (orange). Horizontal or vertical,
optionally mirrored on two sides.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from ...api_control import api
from ...module_info import minfo
from .base import ModernOverlay
from .draw import panel, rounded

OFF, LOW, CRITICAL, LOCK, ABS, SLIP, TC = range(7)


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "display_orientation", "inner_gap", "show_background", "enable_double_side_led", "double_side_led_gap",
        "number_of_led", "led_width", "led_height", "show_lift_and_coast", "lift_and_coast_multiplier_critical",
        "show_tc_activation", "show_abs_activation", "show_wheel_lock", "wheel_lock_threshold",
        "show_wheel_slip", "wheel_slip_threshold",
    )

    def design_unit(self) -> float:
        return float(min(self.wcfg["led_width"], self.wcfg["led_height"]))

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.count = max(int(wcfg["number_of_led"]), 1)
        led_w = max(float(wcfg["led_width"]), 1.0)
        led_h = max(float(wcfg["led_height"]), 1.0)
        gap = max(float(wcfg["inner_gap"]), 0.0)
        pad = max(min(led_w, led_h) * 0.25, 3.0) if wcfg["show_background"] else max(min(led_w, led_h) * 0.15, 2.0)
        orientation = int(wcfg["display_orientation"]) % 4
        vertical = orientation % 2 == 1
        reverse = orientation in (1, 2)  # bottom to top, right to left
        step_w = led_w + gap
        step_h = led_h + gap
        length = (step_h if vertical else step_w) * self.count - gap
        sides = 2 if wcfg["enable_double_side_led"] else 1
        side_gap = max(float(wcfg["double_side_led_gap"]), 0.0)
        self.leds: list[QRectF] = []
        for side in range(sides):
            offset = side * (length + side_gap)
            side_reverse = reverse != bool(side)  # second side mirrored
            for index in range(self.count):
                position = self.count - 1 - index if side_reverse else index
                if vertical:
                    self.leds.append(QRectF(pad, pad + offset + position * step_h, led_w, led_h))
                else:
                    self.leds.append(QRectF(pad + offset + position * step_w, pad, led_w, led_h))
        total = length * sides + side_gap * (sides - 1)
        if vertical:
            self.set_size(led_w + pad * 2, total + pad * 2)
        else:
            self.set_size(total + pad * 2, led_h + pad * 2)
        self.colors = (
            theme.tint(theme.surface_raised, 230), theme.best, QColor(theme.best).lighter(135),
            theme.negative, theme.blue, theme.caution, theme.warning,
        )
        self.critical = wcfg["lift_and_coast_multiplier_critical"]

    def paint_static(self, painter: QPainter):
        if self.wcfg["show_background"]:
            panel(painter, QRectF(self.rect()), self.theme, self.radius(0.5), self.depth_effects)
        for rect in self.leds:
            rounded(painter, rect, min(rect.width(), rect.height()) / 2 * min(self.corner, 1.0), self.colors[OFF])

    def paint(self, painter: QPainter):
        for index, rect in enumerate(self.leds):
            state = self.state[index % self.count]
            if state == OFF:
                continue
            color = self.colors[state]
            radius = min(rect.width(), rect.height()) / 2 * min(self.corner, 1.0)
            glow = QColor(color)
            glow.setAlpha(60)
            grow = min(min(rect.width(), rect.height()) * 0.15, 4.0)
            rounded(painter, rect.adjusted(-grow, -grow, grow, grow), radius + grow, glow)
            rounded(painter, rect, radius, color)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        lico = api.read.engine.lift_and_coast_progress() if wcfg["show_lift_and_coast"] else -1
        tc_active = wcfg["show_tc_activation"] and api.read.switch.tc_active()
        abs_active = wcfg["show_abs_activation"] and api.read.switch.abs_active()
        slip_ratio = minfo.wheels.slipRatio
        lock = (wcfg["show_wheel_lock"] and not abs_active and api.read.inputs.brake_raw() > 0.02
                and min(slip_ratio) <= -wcfg["wheel_lock_threshold"])
        slip = (wcfg["show_wheel_slip"] and not tc_active and api.read.inputs.throttle_raw() > 0.02
                and max(slip_ratio) >= wcfg["wheel_slip_threshold"])
        if lock:
            states = (LOCK,) * self.count
        elif abs_active:
            states = (ABS,) * self.count
        elif slip:
            states = (SLIP,) * self.count
        elif tc_active:
            states = (TC,) * self.count
        elif lico <= 0:
            states = (OFF,) * self.count
        else:
            lit = lico * self.count
            level = CRITICAL if lico > self.critical else LOW
            states = tuple(level if index < lit else OFF for index in range(self.count))
        self.refresh(states)
