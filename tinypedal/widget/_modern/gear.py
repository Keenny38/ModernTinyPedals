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
Gear Widget, modern design

Large gear on a tile tinted by shift zone (shift soon, redline, over-rev or neutral at speed,
flashing above critical RPM), speed with unit, RPM bar above safe RPM, battery & consumption
bars, speed limiter pill.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_common import GEAR_SEQUENCE
from ...module_info import minfo
from .base import CENTER, ModernOverlay
from .draw import bar, panel, readable_on, rounded

NORMAL, SAFE, REDLINE, OVER_REV = 0, 1, 2, 3


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_speed", "show_speed_below_gear", "show_speed_limiter", "show_battery_bar",
        "high_battery_threshold", "low_battery_threshold", "show_rpm_bar", "show_rpm_flickering_above_critical",
        "rpm_multiplier_safe", "rpm_multiplier_redline", "rpm_multiplier_critical",
        "neutral_warning_speed_threshold", "neutral_warning_time_threshold",
        "show_consumption_bar", "show_virtual_energy_if_available", "consumption_progression_exponential_scale",
        "high_consumption_threshold", "maximum_average_consumption_samples",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        size = self.unit  # gear glyph size
        self.unit = max(size * 0.32, 6.0)  # small parts (labels, bars) follow a smaller unit
        self.add_font("gear", size / self.unit * 0.95, "bold", family="Barlow")
        self.add_font("speed", size / self.unit * 0.5, "bold")
        self.add_font("value", 1.0, "semibold")
        self.add_font("label", 0.8, "bold", spacing=106, caps=True)
        self.unit_speed = units.set_unit_speed(self.cfg.units["speed_unit"])
        self.symbol_speed = units.set_symbol_speed(self.cfg.units["speed_unit"])
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.cons_exp = min(max(wcfg["consumption_progression_exponential_scale"], 1), 10)
        self.ema_rate = calc.ema_filter(wcfg["maximum_average_consumption_samples"])
        self.ema_fuel_rate = 0.0
        self.max_fuel_rate = 0.0

        unit = self.unit
        pad = unit * 0.9
        gap = unit * 0.6
        gear_w = self.text_width("gear", "8") + unit * 2.6
        gear_h = self.metrics["gear"].capHeight() + unit * 2.6
        speed_w = max(self.text_width("speed", "888"), self.text_width("label", self.symbol_speed)) + unit * 1.2
        show_speed = wcfg["show_speed"]
        if not show_speed:
            width = gear_w
            self.rect_speed = QRectF()
        elif wcfg["show_speed_below_gear"]:
            width = max(gear_w, speed_w)
            gear_w = width
        else:
            width = gear_w + gap + speed_w
        self.rect_gear = QRectF(pad, pad, gear_w, gear_h)
        if show_speed:
            if wcfg["show_speed_below_gear"]:
                self.rect_speed = QRectF(pad, pad + gear_h + gap * 0.5, width, unit * 3.2)
            else:
                self.rect_speed = QRectF(pad + gear_w + gap, pad, speed_w, gear_h)
        top = max(self.rect_gear.bottom(), self.rect_speed.bottom() if show_speed else 0) + gap
        bar_h = max(unit * 0.55, 3.0)
        thin_h = max(unit * 0.3, 2.0)
        self.rect_rpm = QRectF(pad, top, width, bar_h) if wcfg["show_rpm_bar"] else QRectF()
        top += bar_h + gap * 0.6 if wcfg["show_rpm_bar"] else 0
        self.rect_battery = QRectF(pad, top, width, thin_h) if wcfg["show_battery_bar"] else QRectF()
        top += thin_h + gap * 0.6 if wcfg["show_battery_bar"] else 0
        self.rect_consumption = QRectF(pad, top, width, thin_h) if wcfg["show_consumption_bar"] else QRectF()
        top += thin_h + gap * 0.6 if wcfg["show_consumption_bar"] else 0
        limiter_w = self.text_width("label", "LIMIT") + unit * 1.4
        self.rect_limiter = QRectF(pad + width - limiter_w, pad - unit * 0.4, limiter_w, unit * 1.5)
        self.set_size(width + pad * 2, top - (gap * 0.6 if top > self.rect_gear.bottom() + gap else gap) + pad)

        self.rpm_max = -1.0
        self.rpm_safe = self.rpm_red = self.rpm_crit = 0
        self.rpm_range = 0.0
        self.gear_max = 0
        self.last_gear = 0
        self.shift_start = 0.0
        self.flicker = False

    def post_update(self):
        self.ema_fuel_rate = 0.0
        self.max_fuel_rate = 0.0

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.8), self.depth_effects)
        for rect in (self.rect_rpm, self.rect_battery, self.rect_consumption):
            if not rect.isNull():
                rounded(painter, rect, rect.height() / 2, theme.surface_raised)
        if not self.rect_speed.isNull():
            label = QRectF(self.rect_speed.left(), self.rect_speed.bottom() - self.unit * 2.1,
                           self.rect_speed.width(), self.unit * 1.4)
            self.draw_text(painter, label, self.symbol_speed, "label", theme.text_muted, CENTER, elide=False)

    def paint(self, painter: QPainter):
        theme = self.theme
        gear, speed, zone, rpm_fraction, battery, consumption, limiter = self.state
        fills = {NORMAL: theme.surface_alt, SAFE: theme.positive, REDLINE: theme.warning, OVER_REV: theme.negative}
        fill = fills[zone]
        rounded(painter, self.rect_gear, self.radius(0.7), fill)
        text_color = theme.text if zone == NORMAL else readable_on(fill)
        if gear == "N" and zone == NORMAL:
            text_color = theme.positive
        self.draw_text(painter, self.rect_gear, gear, "gear", text_color, CENTER, elide=False)
        if not self.rect_speed.isNull():
            speed_rect = QRectF(self.rect_speed.left(), self.rect_speed.top(), self.rect_speed.width(),
                                self.rect_speed.height() - self.unit * 1.6)
            self.draw_text(painter, speed_rect, speed, "speed", theme.text, CENTER, elide=False)
        rpm_colors = {NORMAL: theme.text_dim, SAFE: theme.positive, REDLINE: theme.warning, OVER_REV: theme.negative}
        if not self.rect_rpm.isNull():
            bar(painter, self.rect_rpm, rpm_fraction, rpm_colors[zone], None, self.rect_rpm.height() / 2)
        if not self.rect_battery.isNull() and battery is not None:
            level, color_key = battery
            bar(painter, self.rect_battery, level, getattr(theme, color_key), None, self.rect_battery.height() / 2)
        if not self.rect_consumption.isNull():
            level, high = consumption
            bar(painter, self.rect_consumption, level, theme.warning if high else theme.text_dim, None,
                self.rect_consumption.height() / 2)
        if limiter:
            rounded(painter, self.rect_limiter, self.rect_limiter.height() / 2, theme.negative)
            self.draw_text(painter, self.rect_limiter, "LIMIT", "label", readable_on(theme.negative), CENTER, elide=False)

    def zone(self, rpm: float, gear: int, speed: float, shift_time: float) -> int:
        """Shift zone of current RPM"""
        wcfg = self.wcfg
        self.flicker = not self.flicker
        if wcfg["show_rpm_flickering_above_critical"] and self.flicker and gear < self.gear_max and rpm >= self.rpm_crit:
            return NORMAL
        if (not gear and speed > wcfg["neutral_warning_speed_threshold"]
                and shift_time >= wcfg["neutral_warning_time_threshold"]) or rpm > self.rpm_max:
            return OVER_REV
        if rpm >= self.rpm_red:
            return REDLINE
        if rpm >= self.rpm_safe:
            return SAFE
        return NORMAL

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        engine = api.read.engine
        rpm_max = engine.rpm_max()
        if self.rpm_max != rpm_max:
            self.rpm_max = rpm_max
            self.rpm_safe = int(rpm_max * wcfg["rpm_multiplier_safe"])
            self.rpm_red = int(rpm_max * wcfg["rpm_multiplier_redline"])
            self.rpm_crit = int(rpm_max * wcfg["rpm_multiplier_critical"])
            self.rpm_range = rpm_max - self.rpm_safe
            self.gear_max = engine.gear_max()
        gear = engine.gear()
        elapsed = api.read.timing.elapsed()
        if self.last_gear != gear:
            self.last_gear = gear
            self.shift_start = elapsed
        rpm = engine.rpm()
        speed = api.read.vehicle.speed()
        zone = self.zone(rpm, gear, speed, elapsed - self.shift_start)
        rpm_offset = rpm - self.rpm_safe
        rpm_fraction = rpm_offset / self.rpm_range if self.rpm_range > 0 <= rpm_offset else 0.0
        battery = None
        if wcfg["show_battery_bar"] and minfo.hybrid.motorState > 0:
            charge = minfo.hybrid.batteryCharge
            if minfo.hybrid.motorState == 3:
                color_key = "positive"
            elif charge >= wcfg["high_battery_threshold"]:
                color_key = "best"
            elif charge <= wcfg["low_battery_threshold"]:
                color_key = "negative"
            else:
                color_key = "accent"
            battery = (round(charge * 0.01, 3), color_key)
        consumption = (0.0, False)
        if wcfg["show_consumption_bar"]:
            if wcfg["show_virtual_energy_if_available"] and minfo.energy.available:
                rate = minfo.energy.rateOfConsumption
            else:
                rate = self.unit_fuel(minfo.fuel.rateOfConsumption)
            self.ema_fuel_rate = self.ema_rate(self.ema_fuel_rate, rate)
            self.max_fuel_rate = max(self.max_fuel_rate, self.ema_fuel_rate)
            level = rate / self.max_fuel_rate if self.max_fuel_rate else 0.0
            consumption = (round(level ** self.cons_exp, 3), level >= wcfg["high_consumption_threshold"])
        limiter = wcfg["show_speed_limiter"] and bool(api.read.switch.speed_limiter())
        self.refresh((
            GEAR_SEQUENCE(gear, "N"), f"{self.unit_speed(speed):.0f}", zone, round(min(rpm_fraction, 1.0), 3),
            battery, consumption, limiter,
        ))
