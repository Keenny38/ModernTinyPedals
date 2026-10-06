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
RPM LED Widget, modern design

Capsule LEDs lighting up progressively (green, yellow, red), all flashing blue at critical RPM
and purple when over-revving, green flash with speed limiter. Unlit LEDs keep a faint tint of
their zone color (zones readable before they light up), lit LEDs glow with a light top shine.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from ...api_control import api
from ...const_common import FLOAT_INF
from .._common import warning_flash
from .base import ModernOverlay
from .draw import panel, rounded

OFF, LOW, SAFE, REDLINE, CRITICAL, OVER_REV, LIMITER = range(7)
GLOW_ALPHA = 60  # soft glow around lit LED
ZONE_ALPHA = 46  # zone color tint of unlit LED
SHINE = QColor(255, 255, 255, 45)  # highlight on top of lit LED


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "enable_double_side_led", "number_of_led", "led_width", "led_height", "inner_gap", "show_background",
        "show_rpm_flickering_above_critical", "rpm_multiplier_low", "rpm_multiplier_safe", "rpm_multiplier_redline",
        "rpm_multiplier_critical", "rpm_multiplier_over_rev", "show_speed_limiter_flash", "speed_limiter_flash_interval",
    )

    def design_unit(self) -> float:
        return float(self.wcfg["led_height"])

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        self.double_side = wcfg["enable_double_side_led"]
        self.max_led = max(int(wcfg["number_of_led"]), 3)
        led_w = max(float(wcfg["led_width"]), 1.0)
        led_h = max(float(wcfg["led_height"]), 1.0)
        gap = max(float(wcfg["inner_gap"]), 0.0)
        pad = max(led_h * 0.3, 3.0) if wcfg["show_background"] else max(led_h * 0.15, 2.0)
        self.colors = (
            theme.tint(theme.surface_raised, 230), theme.positive, theme.caution, theme.negative,
            theme.accent, theme.best, theme.positive,
        )
        self.glows = tuple(theme.tint(color, GLOW_ALPHA) for color in self.colors)
        self.zone_tints = tuple(theme.tint(color, ZONE_ALPHA) for color in self.colors)
        self.zones: tuple[int, ...] = ()  # color of each LED once lit, set with car max RPM
        side_w = led_w * self.max_led + gap * (self.max_led - 1)
        self.leds = [QRectF(pad + (led_w + gap) * index, pad, led_w, led_h) for index in range(self.max_led)]
        width = pad * 2 + side_w
        if self.double_side:  # mirrored set on right side, lighting from right to left
            right = width + gap
            self.leds += [QRectF(right + side_w - led_w - (led_w + gap) * index, pad, led_w, led_h) for index in range(self.max_led)]
            width = right + side_w + pad
        self.set_size(width, led_h + pad * 2)
        self.warn_flash = warning_flash(wcfg["speed_limiter_flash_interval"], wcfg["speed_limiter_flash_interval"], FLOAT_INF) \
            if wcfg["show_speed_limiter_flash"] else None
        self.flicker = False
        self.rpm_max = 0.0
        self.rpm_low = self.rpm_safe = self.rpm_redline = self.rpm_critical = self.rpm_overrev = 0.0
        self.rpm_scale = 0.0
        self.gear_max = 0

    def paint_static(self, painter: QPainter):
        theme = self.theme
        if self.wcfg["show_background"]:
            panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        zones = self.zones
        for index, rect in enumerate(self.leds):
            radius = min(rect.width(), rect.height()) / 2 * min(self.corner, 1.0)
            rounded(painter, rect, radius, self.colors[OFF])
            zone = zones[index % self.max_led] if zones else OFF
            if zone != OFF:
                rounded(painter, rect, radius, self.zone_tints[zone])

    def paint(self, painter: QPainter):
        states = self.state
        for index, rect in enumerate(self.leds):
            state = states[index % self.max_led]
            if state == OFF:
                continue
            color = self.colors[state]
            radius = min(rect.width(), rect.height()) / 2 * min(self.corner, 1.0)
            grow = min(rect.height() * 0.18, 4.0)
            rounded(painter, rect.adjusted(-grow, -grow, grow, grow), radius + grow, self.glows[state])
            rounded(painter, rect, radius, color)
            rounded(painter, QRectF(rect.left() + radius * 0.3, rect.top() + rect.height() * 0.12,
                                    rect.width() - radius * 0.6, rect.height() * 0.3), radius * 0.6, SHINE)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        engine = api.read.engine
        rpm_max = engine.rpm_max()
        if self.rpm_max != rpm_max:
            self.rpm_max = rpm_max
            self.rpm_low = rpm_max * wcfg["rpm_multiplier_low"]
            self.rpm_safe = rpm_max * wcfg["rpm_multiplier_safe"] - self.rpm_low
            self.rpm_redline = rpm_max * wcfg["rpm_multiplier_redline"] - self.rpm_low
            self.rpm_critical = rpm_max * wcfg["rpm_multiplier_critical"] - self.rpm_low
            self.rpm_overrev = rpm_max * wcfg["rpm_multiplier_over_rev"] - self.rpm_low
            self.rpm_scale = self.max_led / max(self.rpm_critical, 0.0000001)
            self.gear_max = engine.gear_max()
            zones = tuple(self.led_state(index / self.rpm_scale) for index in range(self.max_led))
            if zones != self.zones:
                self.zones = zones
                self.redraw_static()
        rpm = engine.rpm() - self.rpm_low
        warn_flash = self.warn_flash
        limiter = warn_flash is not None and bool(api.read.switch.speed_limiter())
        if limiter and warn_flash is not None:
            self.flicker = warn_flash.send(True)
        elif wcfg["show_rpm_flickering_above_critical"] and rpm >= self.rpm_critical and engine.gear() < self.gear_max:
            self.flicker = not self.flicker
        else:
            self.flicker = False
        if limiter:
            states = (LIMITER if self.flicker else OFF,) * self.max_led
        elif rpm >= self.rpm_overrev:
            states = (OFF if self.flicker else OVER_REV,) * self.max_led
        elif rpm >= self.rpm_critical:
            states = (OFF if self.flicker else CRITICAL,) * self.max_led
        elif rpm < 0:
            states = (OFF,) * self.max_led
        else:
            lit = rpm * self.rpm_scale
            states = tuple(self.led_state(index / self.rpm_scale) if index < lit else OFF for index in range(self.max_led))
        self.refresh(states)

    def led_state(self, rpm: float) -> int:
        """Color of LED at rpm (offset by low rpm)"""
        if rpm < self.rpm_safe:
            return LOW
        if rpm < self.rpm_redline:
            return SAFE
        if rpm < self.rpm_critical:
            return REDLINE
        return OFF
