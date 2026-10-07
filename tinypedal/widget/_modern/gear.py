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
flashing above critical RPM), speed with unit, RPM bar above safe RPM, battery (hybrid car only)
& consumption bars with optional readings, speed limiter pill (outlined reminder in pit lane
while car limiter is off).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...const_common import GEAR_SEQUENCE
from ...i18n import tr_overlay
from ...module_info import minfo
from .base import CENTER, LEFT, RIGHT, ModernOverlay
from .draw import bar, panel, readable_on, rounded

NORMAL, SAFE, REDLINE, OVER_REV = 0, 1, 2, 3
LIMITER_OFF, LIMITER_ON, LIMITER_REMINDER = 0, 1, 2
READING_ALIGN = {"left": LEFT, "right": RIGHT, "1": LEFT, "2": RIGHT}  # else center


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_speed", "show_speed_below_gear", "show_speed_limiter", "speed_limiter_text",
        "show_speed_limiter_reminder", "show_battery_bar",
        "high_battery_threshold", "low_battery_threshold", "show_battery_reading", "decimal_places_battery",
        "battery_reading_text_alignment", "show_rpm_bar", "show_rpm_flickering_above_critical",
        "rpm_multiplier_safe", "rpm_multiplier_redline", "rpm_multiplier_critical",
        "neutral_warning_speed_threshold", "neutral_warning_time_threshold",
        "show_rpm_reading", "decimal_places_rpm", "rpm_reading_text_alignment",
        "show_consumption_bar", "show_virtual_energy_if_available", "consumption_progression_exponential_scale",
        "high_consumption_threshold", "maximum_average_consumption_samples",
        "show_consumption_reading", "decimal_places_consumption", "consumption_reading_text_alignment",
        "display_order_battery", "display_order_rpm", "display_order_consumption",
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
        # Bar readings fit (wider digits of modern font): widest reading widens speed, else gear part
        samples = {"rpm": 88888, "battery": 100, "consumption": 8}
        reading_w = max((self.text_width("value", f"{samples[key]:.{max(int(wcfg[f'decimal_places_{key}']), 0)}f}")
                         + unit * 1.2 for key in samples if wcfg[f"show_{key}_reading"]), default=0.0)
        if not show_speed:
            gear_w = max(gear_w, reading_w)
        elif wcfg["show_speed_below_gear"]:
            speed_w = max(speed_w, reading_w)
        else:
            speed_w = max(speed_w, reading_w - gear_w - gap)
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
        self.text_limiter = self.user_text("speed_limiter_text", tr_overlay("LIMIT"))
        # Bar readings: decimal places & alignment, None if not shown
        self.readings: dict[str, tuple[int, Qt.AlignmentFlag] | None] = {
            key: (max(int(wcfg[f"decimal_places_{key}"]), 0),
                  READING_ALIGN.get(str(wcfg[f"{key}_reading_text_alignment"]).lower(), CENTER))
            if wcfg[f"show_{key}_reading"] else None
            for key in ("rpm", "battery", "consumption")
        }
        if show_speed:  # in place of speed unit (never over speed digits): centered on unit label
            limiter_w = min(self.text_width("label", self.text_limiter) + unit * 1.4, self.rect_speed.width())
            label_center = self.speed_label_rect().center()
            # Speed below gear: short speed part, pill at its bottom (unit label overlaps digits area)
            top = (self.rect_speed.bottom() - unit * 1.5 if wcfg["show_speed_below_gear"]
                   else label_center.y() - unit * 0.75)
            self.rect_limiter = QRectF(label_center.x() - limiter_w / 2, top, limiter_w, unit * 1.5)
        else:
            limiter_w = min(self.text_width("label", self.text_limiter) + unit * 1.4, width)
            self.rect_limiter = QRectF(pad + width - limiter_w, pad - unit * 0.4, limiter_w, unit * 1.5)
        self.content_width = width
        self.bars_top = max(self.rect_gear.bottom(), self.rect_speed.bottom() if show_speed else 0) + gap
        self.battery_shown = False  # battery bar of hybrid car only (electric motor available)
        self.place_bars()

        self.rpm_max = -1.0
        self.rpm_safe = self.rpm_red = self.rpm_crit = 0
        self.rpm_range = 0.0
        self.gear_max = 0
        self.last_gear = 0
        self.shift_start = 0.0
        self.flicker = False

    def place_bars(self):
        """RPM, battery & consumption bars under gear, widget height"""
        wcfg = self.wcfg
        unit = self.unit
        pad = unit * 0.9
        gap = unit * 0.6
        width = self.content_width
        top = self.bars_top
        reading_h = unit * 1.45  # bar with reading on it
        heights = {
            "rpm": reading_h if self.readings["rpm"] else max(unit * 0.55, 3.0),
            "battery": reading_h if self.readings["battery"] else max(unit * 0.3, 2.0),
            "consumption": reading_h if self.readings["consumption"] else max(unit * 0.3, 2.0),
        }
        shown = {
            "rpm": wcfg["show_rpm_bar"],
            "battery": wcfg["show_battery_bar"] and self.battery_shown,
            "consumption": wcfg["show_consumption_bar"],
        }
        rects = {key: QRectF() for key in shown}
        for key in self.display_ordered(list(shown), key=str):
            if shown[key]:
                rects[key] = QRectF(pad, top, width, heights[key])
                top += heights[key] + gap * 0.6
        self.rect_rpm, self.rect_battery, self.rect_consumption = rects["rpm"], rects["battery"], rects["consumption"]
        self.set_size(width + pad * 2, top - (gap * 0.6 if top > self.rect_gear.bottom() + gap else gap) + pad)

    def post_update(self):
        self.ema_fuel_rate = 0.0
        self.max_fuel_rate = 0.0

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.8), self.depth_effects)
        for rect in (self.rect_rpm, self.rect_battery, self.rect_consumption):
            if not rect.isNull():
                rounded(painter, rect, rect.height() / 2, theme.surface_raised)

    def speed_label_rect(self) -> QRectF:
        """Speed unit label, under speed digits"""
        return QRectF(self.rect_speed.left(), self.rect_speed.bottom() - self.unit * 2.1,
                      self.rect_speed.width(), self.unit * 1.4)

    def paint(self, painter: QPainter):
        theme = self.theme
        gear, speed, zone, rpm_fraction, battery, consumption, limiter, readings = self.state
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
            if limiter == LIMITER_OFF:  # else speed limiter pill in its place
                self.draw_text(painter, self.speed_label_rect(), self.symbol_speed, "label", theme.text_muted,
                               CENTER, elide=False)
        rpm_colors = {NORMAL: theme.text_dim, SAFE: theme.positive, REDLINE: theme.warning, OVER_REV: theme.negative}
        rpm_text, battery_text, consumption_text = readings
        if not self.rect_rpm.isNull():
            self.draw_bar(painter, self.rect_rpm, rpm_fraction, rpm_colors[zone], "rpm", rpm_text)
        if not self.rect_battery.isNull() and battery is not None:
            level, color_key = battery
            self.draw_bar(painter, self.rect_battery, level, getattr(theme, color_key), "battery", battery_text)
        if not self.rect_consumption.isNull():
            level, high = consumption
            self.draw_bar(painter, self.rect_consumption, level, theme.warning if high else theme.text_dim,
                          "consumption", consumption_text)
        if limiter == LIMITER_ON:
            rounded(painter, self.rect_limiter, self.rect_limiter.height() / 2, theme.negative)
            self.draw_text(painter, self.rect_limiter, self.text_limiter, "label", readable_on(theme.negative), CENTER)
        elif limiter == LIMITER_REMINDER:  # in pit lane, limiter off: outlined
            box = self.rect_limiter
            rounded(painter, box, box.height() / 2, theme.warning)
            inset = max(self.unit * 0.18, 1.5)
            inner = box.adjusted(inset, inset, -inset, -inset)
            rounded(painter, inner, inner.height() / 2, theme.surface)
            self.draw_text(painter, box, self.text_limiter, "label", theme.warning, CENTER)

    def draw_bar(self, painter: QPainter, rect: QRectF, level: float, color, key: str, text: str):
        """Bar, reading on it if shown (fill tinted so reading stays readable)"""
        reading = self.readings[key]
        if reading is None:
            bar(painter, rect, level, color, None, rect.height() / 2)
            return
        bar(painter, rect, level, self.theme.tint(color, 150), None, rect.height() / 2)
        inset = self.unit * 0.6
        self.draw_text(painter, rect.adjusted(inset, 0, -inset, 0), text, "value", self.theme.text, reading[1],
                       elide=False)

    def reading_text(self, key: str, value: float) -> str:
        """Bar reading text, empty if not shown"""
        reading = self.readings[key]
        return f"{value:.{reading[0]}f}" if reading is not None else ""

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
        battery_text = consumption_text = ""
        hybrid = minfo.hybrid.motorState > 0  # electric motor available
        if wcfg["show_battery_bar"] and hybrid != self.battery_shown:  # bar hidden for other cars
            self.battery_shown = hybrid
            self.place_bars()
        if wcfg["show_battery_bar"] and hybrid:
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
            battery_text = self.reading_text("battery", charge)
        consumption = (0.0, False)
        if wcfg["show_consumption_bar"]:
            if wcfg["show_virtual_energy_if_available"] and minfo.energy.available:
                rate = minfo.energy.rateOfConsumption
            else:
                rate = self.unit_fuel(minfo.fuel.rateOfConsumption)
            self.ema_fuel_rate = self.ema_rate(self.ema_fuel_rate, rate)
            self.max_fuel_rate = max(self.max_fuel_rate, self.ema_fuel_rate)
            # Negative while refuelling: clamp (negative ** fractional exponent is complex)
            level = min(max(rate / self.max_fuel_rate, 0.0), 1.0) if self.max_fuel_rate > 0 else 0.0
            consumption = (round(level ** self.cons_exp, 3), level >= wcfg["high_consumption_threshold"])
            consumption_text = self.reading_text("consumption", rate)
        self.refresh((
            GEAR_SEQUENCE(gear, "N"), f"{self.unit_speed(speed):.0f}", zone, round(min(rpm_fraction, 1.0), 3),
            battery, consumption, self.limiter_state(),
            (self.reading_text("rpm", rpm), battery_text, consumption_text),
        ))

    def limiter_state(self) -> int:
        """Speed limiter on (switched on or active), or reminder: in pit lane with car limiter off"""
        if not self.wcfg["show_speed_limiter"]:
            return LIMITER_OFF
        switch = api.read.switch
        if switch.speed_limiter() or switch.speed_limiter_active():
            return LIMITER_ON
        if (self.wcfg["show_speed_limiter_reminder"] and switch.speed_limiter_available()
                and api.read.vehicle.in_pits() and api.read.vehicle.speed() > 1):
            return LIMITER_REMINDER
        return LIMITER_OFF
