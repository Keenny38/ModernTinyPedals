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
Wheel status Widget

Car seen from above, all-in-one view:
tyres (temperature heatmap or inner/center/outer bands, pressure target, wear, end of stint wear,
lock & spin warning, puncture, detached wheel, flat spot, steering angle),
brakes (temperature heatmap, suspension damage), body damage,
center column (ABS, TC, brake bias, pit & limiter, gear, speed, RPM, pedals, ordered by user),
RPM LEDs on top, refuel / refill and fuel / energy remaining at bottom.
"""

from __future__ import annotations

import math
from time import monotonic

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from .. import calculation as calc
from .. import units
from ..api_control import api
from ..const_common import WHEELS_ZERO
from ..module_info import minfo
from ..userfile.heatmap import (
    HEATMAP_DEFAULT_BRAKE,
    HEATMAP_DEFAULT_TYRE,
    load_heatmap_color,
    select_brake_heatmap_name,
    select_compound_symbol,
    select_tyre_heatmap_name,
    set_predefined_brake_name,
)
from ._base import Overlay
from ._common import warning_flash
from ._painter import fill_chip, fill_chip_gradient, fill_glow, fill_rect, fit_font
from ._wheel_state import (
    LAPS_LABEL,
    NO_STATUS,
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
    WheelState,
    fit_readings,
    level_text,
)

LAYOUT_NORMAL = 0  # info column between tyres
LAYOUT_VERTICAL = 1  # info column below tyres
LAYOUT_COMPACT = 2  # tyres & brakes only

CENTER_ITEMS = (
    "abs", "tc", "brake_bias", "brake_migration", "locking", "delta", "laptime",
    "pit_limiter", "gear", "speed", "rpm", "pedals",
)

class Realtime(Overlay):
    """Draw widget"""

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        wcfg = self.wcfg

        # Config font (scaled with display)
        scale = min(max(wcfg["display_scale"], 0.5), 4)
        font = self.config_font(wcfg["font_name"], wcfg["font_size"] * scale, wcfg["font_weight"])
        self.setFont(font)
        font_m = self.get_font_metrics(font)
        self.gear_scale = min(max(wcfg["font_scale_gear"], 0.5), 5)
        self.speed_scale = min(max(wcfg["font_scale_speed"], 0.3), 4)
        self.rpm_scale = min(max(wcfg["font_scale_rpm"], 0.3), 4)
        self.battery_scale = min(max(wcfg["font_scale_battery"], 0.3), 4)
        size = wcfg["font_size"] * scale
        self.font_gear = self.config_font(wcfg["font_name"], size * self.gear_scale, wcfg["font_weight"])
        self.font_speed = self.config_font(wcfg["font_name"], size * self.speed_scale, wcfg["font_weight"])
        self.font_rpm = self.config_font(wcfg["font_name"], size * self.rpm_scale, wcfg["font_weight"])
        self.font_small = self.config_font(wcfg["font_name"], size * 0.75, wcfg["font_weight"])
        self.font_battery = self.config_font(wcfg["font_name"], size * self.battery_scale, wcfg["font_weight"])

        # Config geometry (unit: font line height)
        unit = font_m.height
        self.unit = unit
        self.layout_mode = min(max(int(wcfg["layout"]), 0), 2)
        self.center_order = self.ordered_center_items()
        gap = round(unit * 0.25)
        self.gap = gap
        tyre_w, tyre_h = round(unit * 2.1), round(unit * 2.9)
        # Brake: thin vertical bar next to tyre, temperature written beside it
        brake_w, brake_h = round(unit * 2.1), round(tyre_h * 0.8)
        self.brake_bar_w = max(round(unit * 0.32), 3)
        self.brake_bar_gap = round(unit * 0.15)

        # Room around tyres, so turned tyres do not overlap brakes or widget edges
        self.max_steer = min(max(wcfg["maximum_wheel_angle"], 0), 45) if wcfg["show_wheel_angle"] else 0
        steer_sin = math.sin(math.radians(self.max_steer))
        pad_x = round(tyre_h * steer_sin / 2)
        pad_y = round(tyre_w * steer_sin / 2)
        brake_gap = round(unit * 0.12)  # brake bar close to tyre (turned tyre may touch it at full lock)
        side_w = pad_x + tyre_w + brake_gap + brake_w

        has_center = self.layout_mode != LAYOUT_COMPACT and bool(self.center_order)
        # Only read data that is actually displayed (compact layout skips the whole center column)
        shown = set(self.center_order) if has_center else set()
        self.match_heatmap = bool(wcfg["enable_heatmap_auto_matching"])
        self.show_tyre_wear = bool(wcfg["show_tyre_wear"])
        self.need_switches = bool(shown & {"abs", "tc"})
        self.need_brake_bias = "brake_bias" in shown
        self.need_locking = "locking" in shown
        self.need_brake_migration = "brake_migration" in shown
        self.need_delta = "delta" in shown
        self.need_laptime = "laptime" in shown
        # Justified: speed and RPM use the same label/value rows as brake bias and delta,
        # so every value in the column lines up on the right edge instead of each being centered.
        self.justify_center = self.wcfg["center_column_alignment"] == "Justified"
        self.need_limiter = "pit_limiter" in shown
        self.need_gear = "gear" in shown
        self.need_pedals = "pedals" in shown
        self.need_rpm = "rpm" in shown or bool(wcfg["show_rpm_leds"]) or (
            self.need_gear and bool(wcfg["enable_gear_rpm_color"]))
        center_between = round(unit * 5.2) if has_center and self.layout_mode == LAYOUT_NORMAL else round(unit * 0.8)
        content_w = side_w * 2 + center_between + gap * 2

        # Battery bar: full-height side gauge, outside the tyre/brake columns, left or right
        self.show_battery_bar = bool(wcfg["show_battery_bar"])
        self.battery_bar_left = wcfg["battery_bar_position"] != "Right"
        battery_bar_scale = min(max(wcfg["battery_bar_scale"], 0.3), 4)
        battery_bar_w = max(round(unit * battery_bar_scale), 4) if self.show_battery_bar else 0
        battery_extra = battery_bar_w + gap if self.show_battery_bar else 0
        content_x = battery_extra if self.show_battery_bar and self.battery_bar_left else 0
        width = content_w + battery_extra
        self.battery_low = wcfg["battery_low_threshold"]
        self.battery_high = wcfg["battery_high_threshold"]
        # Flashes a few times on crossing a threshold, then stays highlighted. Without the
        # flash the warning color is simply shown steadily, same as the Battery widget.
        if self.show_battery_bar and wcfg["show_battery_warning_flash"]:
            self.battery_flash = warning_flash(
                wcfg["battery_warning_flash_duration"],
                wcfg["battery_warning_flash_interval"],
                wcfg["number_of_battery_warning_flashes"],
            )
        else:
            self.battery_flash = None

        # Caption (widget name) on top, then RPM LEDs (span full width, above everything else)
        caption_h = round(unit * 0.9) if wcfg["show_caption"] else 0
        self.rect_caption = QRectF(0, 0, width, caption_h)
        self.led_h = round(unit * 0.55) if wcfg["show_rpm_leds"] else 0
        led_y = caption_h + (gap if caption_h else 0)
        top_y = led_y + (self.led_h + gap if self.led_h else 0)
        self.rect_leds = QRectF(
            content_x + round(unit * 0.3), led_y + round(gap * 0.6), content_w - round(unit * 0.6), self.led_h)

        axle_gap = round(unit * 0.9) + pad_y * 2
        if has_center and self.layout_mode == LAYOUT_NORMAL:  # taller if center column needs more room
            axle_gap += max(round(self.center_height() - (pad_y * 2 + tyre_h * 2 + axle_gap)), 0)
        body_h = pad_y + tyre_h * 2 + axle_gap + pad_y

        right_x = content_x + content_w - side_w
        self.rects_tyre = []
        self.rects_disc = []
        self.rects_suspension = []
        # All tyres share the same size, so the rounded path is built once instead of every frame
        tyre_radius = tyre_w * 0.28
        self.path_tyre = QPainterPath()
        self.path_tyre.addRoundedRect(
            QRectF(-tyre_w / 2, -tyre_h / 2, tyre_w, tyre_h), tyre_radius, tyre_radius)
        self.local_tyre = QRectF(-tyre_w / 2, -tyre_h / 2, tyre_w, tyre_h)
        for index in range(4):
            is_right = index % 2
            top = top_y + pad_y + (0 if index < 2 else tyre_h + axle_gap)
            if is_right:
                brake_x = right_x
                tyre_x = right_x + brake_w + brake_gap
            else:
                tyre_x = content_x + pad_x
                brake_x = content_x + pad_x + tyre_w + brake_gap
            brake_top = top + (tyre_h - brake_h) / 2
            self.rects_tyre.append(QRectF(tyre_x, top, tyre_w, tyre_h))
            self.rects_disc.append(QRectF(brake_x, brake_top, brake_w, brake_h))
            text_x = brake_x if is_right else brake_x + self.brake_bar_w + self.brake_bar_gap
            text_w = brake_w - self.brake_bar_w - self.brake_bar_gap
            self.rects_suspension.append(QRectF(text_x, brake_top + brake_h - unit * 0.22, text_w, unit * 0.22))

        # Center column
        inset = round(unit * 0.3)
        bottom_y = top_y + body_h
        if has_center and self.layout_mode == LAYOUT_NORMAL:
            self.rect_center = QRectF(content_x + side_w + gap, top_y, center_between, body_h)
        elif has_center:  # vertical: below tyres, full content width
            self.rect_center = QRectF(content_x + inset, bottom_y + gap, content_w - inset * 2, self.center_height())
            bottom_y = self.rect_center.bottom()
        else:
            self.rect_center = QRectF()
        # Body damage marks along car edges (outside tyres)
        edge = round(unit * 0.08)
        self.rect_body_damage = QRectF(content_x + edge, top_y, content_w - edge * 2, body_h)

        # Bottom rows: refuel & fuel remaining (left), refill & energy remaining (right)
        self.row_h = round(unit * 1.05)
        self.bottom_rows: list[tuple[QRectF, QRectF]] = []
        rows = int(wcfg["show_refuel"] or wcfg["show_refill"]) + int(
            wcfg["show_fuel_remaining"] or wcfg["show_energy_remaining"])
        row_w = (content_w - inset * 2 - gap) / 2
        for row in range(rows):
            row_top = bottom_y + gap + row * (self.row_h + gap)
            self.bottom_rows.append((
                QRectF(content_x + inset, row_top, row_w, self.row_h),
                QRectF(content_x + content_w - inset - row_w, row_top, row_w, self.row_h),
            ))
        height = bottom_y + (rows * (self.row_h + gap) + gap if rows else 0)
        self.rect_bg = QRectF(0, 0, width, height)

        if self.show_battery_bar:
            battery_x = 0 if self.battery_bar_left else content_x + content_w + gap
            self.rect_battery = QRectF(battery_x, top_y, battery_bar_w, bottom_y - top_y)
        else:
            self.rect_battery = QRectF()
        self.resize(int(width), int(height))

        # Config pens & colors
        self.pen_text = QPen(QColor(wcfg["font_color"]))
        self.pen_temp = QPen(QColor(wcfg["font_color_temperature"]))
        outline = max(wcfg["warning_outline_width"], 1)
        self.pen_lock = QPen(QColor(wcfg["wheel_lock_color"]), outline)
        self.pen_spin = QPen(QColor(wcfg["wheel_spin_color"]), outline)
        self.pen_detached = QPen(QColor(wcfg["wheel_detached_color"]), outline, Qt.PenStyle.DashLine)

        # Config units & heatmap
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.unit_pres = units.set_unit_pressure(self.cfg.units["tyre_pressure_unit"])
        self.unit_speed = units.set_unit_speed(self.cfg.units["speed_unit"])
        self.speed_label = {"KPH": "km/h", "MPH": "mph"}.get(self.cfg.units["speed_unit"], "m/s")
        self.unit_fuel = units.set_unit_fuel(self.cfg.units["fuel_unit"])
        self.fuel_label = "gal" if self.cfg.units["fuel_unit"] == "Gallon" else "L"
        self.pres_decimals = 0 if self.cfg.units["tyre_pressure_unit"] == "kPa" else 1
        self.sign_text = "°" if wcfg["show_degree_sign"] else ""
        self.heatmap_tyre = 4 * [self.load_tyre_heatmap(wcfg["heatmap_name_tyre"])]
        self.heatmap_brake = 4 * [self.load_brake_heatmap(wcfg["heatmap_name_brake"])]
        self.temp_warning = wcfg["tyre_temperature_warning_threshold"]  # Celsius, 0 disables
        # Indexed by severity: 1 minor, 2 major, 3 critical (detached). Index 0 is never drawn.
        self.damage_colors = (
            "",
            wcfg["damage_color_minor"],
            wcfg["damage_color_major"],
            wcfg["damage_color_critical"],
        )
        self.lock_threshold = -abs(wcfg["wheel_lock_threshold"])
        self.spin_threshold = abs(wcfg["wheel_spin_threshold"])
        self.min_speed = max(wcfg["slip_warning_minimum_speed"], 0) / 3.6  # km/h to m/s

        # Last data
        self.wheels = [WheelState() for _ in range(4)]
        self.body_damage: tuple = (0,) * 8
        self.abs_active = False
        self.tc_active = False
        self.abs_level = -1
        self.tc_level = -1
        self.tc_cut_level = -1
        self.tc_slip_level = -1
        # Car has ABS/TC if game reports a level (LMU), or once seen active (rF2 does not report level)
        self.abs_seen = False
        self.tc_seen = False
        self.last_vehicle_name = None
        self.brake_bias = 0.0
        self.locking_front = 0.0  # percent of lap distance spent locking a front wheel
        self.locking_rear = 0.0
        self.brake_migration = 0.0  # percent
        self.delta_best = 0.0  # seconds, negative is faster
        self.laptime_current = 0.0  # seconds
        self.in_pits = False
        self.limiter = False
        self.gear = 0
        self.speed = 0.0
        self.rpm = 0.0
        self.rpm_max = 0.0
        self.refuel = 0.0
        self.refill = 0.0
        self.fuel = 0.0
        self.fuel_laps = 0.0
        self.energy = 0.0
        self.energy_laps = 0.0
        self.energy_available = False
        self.throttle = 0.0
        self.brake = 0.0
        self.last_in_pits = -1
        self.last_vehicle = ("", "")
        self.last_compounds: tuple = ("", "", "", "")
        self.battery_charge = 0.0  # percent
        self.battery_state = 0  # 0 n/a, 1 off, 2 drain, 3 regen
        self.battery_warning = 0  # 0 none, 1 low charge, 2 high charge
        self.battery_highlight = True  # warning color shown now (flash phase, or flash disabled)

    # Config helpers
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

    def load_tyre_heatmap(self, name: str):
        return load_heatmap_color(heatmap_name=name, default_name=HEATMAP_DEFAULT_TYRE, swap_style=True,
                                  fg_color=self.wcfg["font_color_temperature"])

    def load_brake_heatmap(self, name: str):
        return load_heatmap_color(heatmap_name=name, default_name=HEATMAP_DEFAULT_BRAKE, swap_style=True,
                                  fg_color=self.wcfg["font_color_temperature"])

    # Update
    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        in_pits = api.read.vehicle.in_pits()  # read once, also used by compound matching
        if self.match_heatmap or wcfg["show_tyre_compound"]:
            self.update_compound_state(in_pits)

        tyre_temp = api.read.tyre.surface_temperature_avg()
        brake_temp = api.read.brake.temperature()
        pressure = api.read.tyre.pressure() if wcfg["show_tyre_pressure"] else WHEELS_ZERO
        tread = api.read.tyre.wear() if self.show_tyre_wear else WHEELS_ZERO  # remaining tread (fraction)
        speed = api.read.vehicle.speed()
        slip_ratio = minfo.wheels.slipRatio
        wheel_angle = minfo.wheels.toeAngle  # degrees, positive to right side of vehicle
        multiplier = wcfg["wheel_angle_multiplier"]
        braking = api.read.inputs.brake_raw() > 0.02 if wcfg["show_slip_warning"] else False
        ico = api.read.tyre.surface_temperature_ico() if wcfg["show_tyre_temperature_bands"] else ()
        detached = api.read.wheel.is_detached() if wcfg["show_tyre_status"] else NO_STATUS
        puncture = api.read.tyre.puncture() if wcfg["show_tyre_status"] else NO_STATUS
        suspension = api.read.wheel.suspension_damage() if wcfg["show_suspension_damage"] else WHEELS_ZERO
        # Diagnostic readings: each reader is skipped unless its own reading is turned on
        carcass = api.read.tyre.carcass_temperature() if wcfg["show_tyre_carcass_temperature"] else WHEELS_ZERO
        ride_height = api.read.wheel.ride_height() if wcfg["show_ride_height"] else WHEELS_ZERO
        brake_pressure = api.read.brake.pressure() if wcfg["show_brake_pressure"] else WHEELS_ZERO
        if wcfg["show_tyre_load"]:
            tyre_load = api.read.tyre.load()
            total_load = sum(tyre_load)
        else:
            tyre_load = WHEELS_ZERO
            total_load = 0.0
        if wcfg["show_tyre_wear_end_stint"]:
            if minfo.energy.available:
                run_laps = min(minfo.fuel.estimatedLaps, minfo.energy.estimatedLaps)
            else:
                run_laps = minfo.fuel.estimatedLaps

        for index, wheel in enumerate(self.wheels):
            wheel.tyre_temp = tyre_temp[index]
            wheel.brake_temp = brake_temp[index]
            wheel.pressure = pressure[index]
            wheel.tread = tread[index] * 100
            wheel.tyre_color = calc.select_grade(self.heatmap_tyre[index], wheel.tyre_temp)[1]
            wheel.brake_color = calc.select_grade(self.heatmap_brake[index], wheel.brake_temp)[1]
            wheel.warning = self.slip_warning(slip_ratio[index], speed, braking)
            wheel.suspension_damage = suspension[index]
            if ico:
                wheel.ico_colors = self.band_colors(index, ico[index * 3:index * 3 + 3])
            wheel.status = self.tyre_status(detached[index], puncture[index], minfo.wheels.lockingTreadWear[index])
            wheel.carcass_temp = carcass[index]
            wheel.ride_height = ride_height[index] * 1000  # meters to millimeters
            wheel.brake_pressure = brake_pressure[index] * 100
            wheel.load_ratio = calc.part_to_whole_ratio(tyre_load[index], total_load) * 100
            if wcfg["show_wheel_camber"]:
                wheel.camber = minfo.wheels.camberAngle[index]
            if wcfg["show_tyre_slip_angle"]:
                wheel.slip_angle = minfo.wheels.slipAngle[index]
            if wcfg["show_tyre_wear_per_lap"]:
                wheel.wear_per_lap = minfo.wheels.estimatedValidTreadWear[index]
            if wcfg["show_tyre_wear_end_stint"]:
                self.update_end_stint_tread(wheel, index, run_laps)
            if wcfg["show_brake_wear"]:
                self.update_brake_wear(wheel, index)
            if self.max_steer:
                steer = wheel_angle[index] * multiplier
                wheel.steer = min(max(steer, -self.max_steer), self.max_steer)

        if wcfg["show_body_damage"]:
            self.body_damage = api.read.vehicle.damage_severity()

        if self.need_switches:
            vehicle_name = api.read.vehicle.vehicle_name()
            if self.last_vehicle_name != vehicle_name:  # new car, detect again
                self.last_vehicle_name = vehicle_name
                self.abs_seen = self.tc_seen = False
            self.abs_active = bool(api.read.switch.abs_active())
            self.tc_active = bool(api.read.switch.tc_active())
            self.abs_seen = self.abs_seen or self.abs_active
            self.tc_seen = self.tc_seen or self.tc_active
            self.abs_level = api.read.switch.abs_level()
            self.tc_level = api.read.switch.tc_level()
            self.tc_cut_level = api.read.switch.tc_cut_level()
            self.tc_slip_level = api.read.switch.tc_slip_level()
        if self.need_brake_bias:
            self.brake_bias = api.read.brake.bias_front()
        if self.need_locking:
            self.locking_front = minfo.wheels.lockingPercentFront * 100
            self.locking_rear = minfo.wheels.lockingPercentRear * 100
        if self.need_brake_migration:
            self.brake_migration = api.read.brake.migration()
        if self.need_delta:
            self.delta_best = minfo.delta.deltaBest
        if self.need_laptime:
            self.laptime_current = minfo.delta.lapTimeCurrent
        self.in_pits = bool(in_pits)
        if self.need_limiter:
            self.limiter = bool(api.read.switch.speed_limiter())
        if self.need_gear:
            self.gear = api.read.engine.gear()
        self.speed = speed
        if self.need_rpm:
            self.rpm = api.read.engine.rpm()
            self.rpm_max = api.read.engine.rpm_max()
        if self.need_pedals:
            self.throttle = api.read.inputs.throttle()
            self.brake = api.read.inputs.brake()
        if self.bottom_rows:
            self.refuel = minfo.fuel.neededRelative
            self.refill = minfo.energy.neededRelative
            self.fuel = minfo.fuel.amountCurrent
            self.fuel_laps = minfo.fuel.estimatedLaps
            self.energy = minfo.energy.amountCurrent
            self.energy_laps = minfo.energy.estimatedLaps
            self.energy_available = minfo.energy.available
        if self.show_battery_bar:
            self.battery_charge = minfo.hybrid.batteryCharge
            self.battery_state = minfo.hybrid.motorState
            self.battery_warning = self.battery_warning_level()
            if self.battery_flash is not None:
                self.battery_highlight = self.battery_flash.send(self.battery_warning)
        self.update()

    def battery_warning_level(self) -> int:
        """Charge warning: 0 none, 1 low, 2 high (never on a car without hybrid system)"""
        if not self.has_hybrid:
            return 0
        if self.battery_charge <= self.battery_low:
            return 1
        if self.battery_charge >= self.battery_high:
            return 2
        return 0

    @staticmethod
    def update_end_stint_tread(wheel: WheelState, index: int, run_laps: float):
        """Estimated remaining tread at end of stint, needs Wheels & Fuel module data"""
        tread_now = minfo.wheels.currentTreadDepth[index]
        wheel.tread_end_known = tread_now > 0 and run_laps > 0
        if wheel.tread_end_known:
            wheel.tread_end = calc.end_stint_tread(
                tread_now, minfo.wheels.estimatedValidTreadWear[index], run_laps)

    @staticmethod
    def update_brake_wear(wheel: WheelState, index: int):
        """Remaining brake thickness (percent of usable thickness), needs Wheels module data"""
        failure = minfo.wheels.failureBrakeThickness[index]
        usable = minfo.wheels.maxBrakeThickness[index] - failure
        wheel.brake_wear_known = usable > 0
        if wheel.brake_wear_known:
            wheel.brake_wear = (minfo.wheels.currentBrakeThickness[index] - failure) * 100 / usable

    @property
    def has_abs(self) -> bool:
        return self.abs_level >= 0 or self.abs_seen

    @property
    def has_tc(self) -> bool:
        return self.tc_level >= 0 or self.tc_seen

    def slip_warning(self, slip_ratio: float, speed: float, braking: bool) -> str:
        """Wheel lock (braking) or wheel spin (accelerating) warning"""
        if not self.wcfg["show_slip_warning"] or speed < self.min_speed:
            return ""
        if braking and slip_ratio < self.lock_threshold:
            return "lock"
        if slip_ratio > self.spin_threshold:
            return "spin"
        return ""

    def tyre_status(self, detached: bool, puncture: bool, locking_wear: float) -> str:
        """Tyre status, most important first"""
        if not self.wcfg["show_tyre_status"]:
            return ""
        if detached:
            return "detached"
        if puncture:
            return "puncture"
        if locking_wear >= self.wcfg["flat_spot_threshold"] > 0:
            return "flat"
        return ""

    def band_colors(self, index: int, temps) -> tuple[str, str, str]:
        """Inner, center, outer temperature colors, from left to right on screen"""
        colors = [calc.select_grade(self.heatmap_tyre[index], temp)[1] for temp in temps]
        inner, center, outer = colors
        if index % 2:  # right wheel: inner side on left
            return inner, center, outer
        return outer, center, inner

    def update_compound_state(self, in_pits):
        """Match heatmap & compound symbol with tyre compound and brake type (checked while in pit)

        Tyre compound and car only change in pit, so this is skipped while driving.
        """
        if not in_pits and self.last_in_pits == in_pits:
            return
        self.last_in_pits = in_pits
        compounds = api.read.tyre.compound_class()
        if self.last_compounds != compounds:
            self.last_compounds = compounds
            for index, compound in enumerate(compounds[:4]):
                if self.match_heatmap:
                    self.heatmap_tyre[index] = self.load_tyre_heatmap(select_tyre_heatmap_name(compound))
                if self.wcfg["show_tyre_compound"]:
                    self.wheels[index].compound = select_compound_symbol(compound)
        if not self.match_heatmap:
            return
        vehicle = (api.read.vehicle.class_name(), api.read.vehicle.vehicle_name())
        if self.last_vehicle != vehicle:
            self.last_vehicle = vehicle
            front = self.load_brake_heatmap(select_brake_heatmap_name(set_predefined_brake_name(*vehicle, True)))
            rear = self.load_brake_heatmap(select_brake_heatmap_name(set_predefined_brake_name(*vehicle, False)))
            self.heatmap_brake = [front, front, rear, rear]

    # Paint
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        wcfg = self.wcfg
        if wcfg["show_background"]:
            fill_rect(painter, self.rect_bg, wcfg["background_color"])
        if not self.rect_caption.isEmpty():
            fill_rect(painter, self.rect_caption, wcfg["background_color_caption"])
            painter.setPen(QColor(wcfg["font_color_caption"]))
            self.draw_fit_text(painter, self.rect_caption, wcfg["caption_text"], self.font_small)
        if self.led_h:
            self.draw_leds(painter, self.rect_leds)
        for index, wheel in enumerate(self.wheels):
            self.draw_tyre(painter, self.rects_tyre[index], wheel)
            self.draw_disc(painter, index, self.rects_disc[index], wheel)
            if wcfg["show_suspension_damage"]:
                self.draw_suspension_damage(painter, self.rects_suspension[index], wheel.suspension_damage)
        if not self.rect_center.isNull():
            self.draw_center(painter, self.rect_center)
        if wcfg["show_body_damage"] and any(self.body_damage):
            self.draw_body_damage(painter, self.rect_body_damage)
        if self.show_battery_bar:
            self.draw_battery_bar(painter, self.rect_battery)
        self.draw_bottom_rows(painter)

    def draw_tyre(self, painter: QPainter, rect: QRectF, wheel: WheelState):
        wcfg = self.wcfg
        local = self.local_tyre
        path = self.path_tyre
        # Tyre turned with wheel angle (left / right)
        painter.save()
        painter.translate(rect.center())
        painter.rotate(wheel.steer)
        if wheel.status == "detached":
            painter.setPen(self.pen_detached)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()
            painter.setPen(QColor(wcfg["wheel_detached_color"]))
            self.draw_fit_text(painter, rect, "OFF", self.font())
            return
        if wcfg["show_tyre_temperature_bands"]:
            painter.save()
            painter.setClipPath(path)
            band_w = local.width() / 3
            for band, color in enumerate(wheel.ico_colors):
                painter.fillRect(QRectF(local.left() + band * band_w, local.top(), band_w + 0.5, local.height()),
                                 QColor(color))
            painter.restore()
        else:
            painter.fillPath(path, QColor(wheel.tyre_color))
        if wheel.warning:
            painter.setPen(self.pen_lock if wheel.warning == "lock" else self.pen_spin)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()

        # Text lines (upright): (priority, text, font, weight in height, pill color, text color)
        lines = []
        if wcfg["show_tyre_compound"] and wheel.compound:
            lines.append((READING_COMPOUND, wheel.compound, self.font_small, 0.9, "", ""))
        if wcfg["show_tyre_temperature"]:
            hot = 0 < self.temp_warning <= wheel.tyre_temp
            lines.append((READING_TEMPERATURE, self.format_temp(wheel.tyre_temp), self.font(), 1.3, "",
                          wcfg["font_color_tyre_temperature_warning"] if hot else ""))
        if wcfg["show_tyre_pressure"]:
            text = f"{self.unit_pres(wheel.pressure):.{self.pres_decimals}f}"
            color = self.pressure_color(wheel.pressure)
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
            text = "PUNCT" if wheel.status == "puncture" else "FLAT"
            color = wcfg["wheel_puncture_color" if wheel.status == "puncture" else "wheel_flat_spot_color"]
            lines.append((READING_STATUS, text, self.font_small, 1.0, color, "#000000"))
        usable = rect.height() * 0.88
        lines = fit_readings(lines, usable, self.unit)
        total = sum(line[3] for line in lines) or 1
        top = rect.top() + rect.height() * 0.06
        for _priority, text, font, weight, pill_color, text_color in lines:
            line_rect = QRectF(rect.left(), top, rect.width(), usable * weight / total)
            top += line_rect.height()
            font = fit_font(painter, font, text, line_rect.width() * 0.9, line_rect.height() * 1.1)
            painter.setFont(font)
            if pill_color:
                pill_w = min(painter.fontMetrics().horizontalAdvance(text) + self.unit * 0.3, rect.width() * 0.92)
                pill = QRectF(line_rect.center().x() - pill_w / 2, line_rect.top() + line_rect.height() * 0.08,
                              pill_w, line_rect.height() * 0.84)
                fill_chip(painter, pill, pill_color)
            painter.setPen(QColor(text_color) if text_color else self.pen_temp)
            painter.drawText(line_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.setFont(self.font())
    def pressure_color(self, pressure: float) -> str:
        """Text color if pressure out of target range (kPa), "" if in range or disabled"""
        wcfg = self.wcfg
        if not wcfg["enable_tyre_pressure_target"] or pressure <= 0:
            return ""
        if pressure < wcfg["tyre_pressure_target_minimum"]:
            return wcfg["tyre_pressure_low_color"]
        if pressure > wcfg["tyre_pressure_target_maximum"]:
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
            painter.fillPath(path, QColor(wheel.brake_color))
            painter.restore()
        else:
            painter.fillPath(path, QColor(wheel.brake_color))
        # Temperature, remaining thickness and pressure share the text area, tallest first
        rows = []
        if wcfg["show_brake_temperature"]:
            rows.append((self.format_temp(wheel.brake_temp), self.font(), wheel.brake_color, 1.3))
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
            painter.setPen(QColor(color))
            self.draw_fit_text(painter, QRectF(text_rect.left(), top, text_rect.width(), row_h), text, font, align)
            top += row_h

    def draw_suspension_damage(self, painter: QPainter, rect: QRectF, damage: float):
        """Suspension damage bar below brake, shown only if damaged"""
        if damage <= 0.005:
            return
        fill_chip(painter, rect, self.wcfg["indicator_inactive_color"])
        if damage >= 0.99:
            color = self.damage_colors[3]
        elif damage >= 0.5:
            color = self.damage_colors[2]
        else:
            color = self.damage_colors[1]
        fill_chip(painter, QRectF(rect.left(), rect.top(), rect.width() * min(damage, 1), rect.height()), color)

    def draw_body_damage(self, painter: QPainter, rect: QRectF):
        """Body damage marks around center (only damaged parts): 3x3 grid without center"""
        thickness = self.unit * 0.16
        third_w, third_h = rect.width() / 3, rect.height() / 3
        positions = (  # (column, row)
            (0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2),
        )
        for severity, (column, row) in zip(self.body_damage, positions):
            if not severity:
                continue
            color = self.damage_colors[min(int(severity), 3)]
            left = rect.left() + column * third_w
            top = rect.top() + row * third_h
            if row == 1:  # left / right side: vertical mark
                x = rect.left() if column == 0 else rect.right() - thickness
                mark = QRectF(x, top + third_h * 0.1, thickness, third_h * 0.8)
            else:  # front / rear: horizontal mark
                y = rect.top() if row == 0 else rect.bottom() - thickness
                mark = QRectF(left + third_w * 0.1, y, third_w * 0.8, thickness)
            fill_rect(painter, mark, color)

    @property
    def has_hybrid(self) -> bool:
        """Car reports a hybrid system, otherwise the gauge has nothing to show

        The Hybrid module falls back to a derived motor state as soon as there is any charge,
        so no state and no charge together means no hybrid system (or no data yet).
        """
        return self.battery_state != 0 or self.battery_charge > 0

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
            # Readout chip fixed at the top, own background so it stays legible regardless of
            # the fill color or level behind it. Chip follows the text size, capped so it never
            # takes more than a third of the gauge.
            label_h = min(self.unit * self.battery_scale * 1.2, rect.height() / 3)
            label_rect = QRectF(rect.left(), rect.top(), rect.width(), label_h)
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
            self.draw_indicator(painter, rect, level_text("ABS", self.abs_level),
                                self.abs_active, wcfg["abs_active_color"])
        elif name == "tc":
            self.draw_indicator(painter, rect,
                                level_text("TC", self.tc_level, self.tc_cut_level, self.tc_slip_level),
                                self.tc_active, wcfg["tc_active_color"])
        elif name == "brake_bias":
            self.draw_info_row(painter, rect, "BB", f"{self.brake_bias * 100:.1f}")
        elif name == "brake_migration":
            self.draw_info_row(painter, rect, "BMIG", f"{self.brake_migration:.1f}")
        elif name == "delta":
            gain = self.delta_best < 0
            color = wcfg["delta_gain_color" if gain else "delta_loss_color"]
            self.draw_info_row(painter, rect, "DELTA", f"{self.delta_best:+.3f}", color)
        elif name == "laptime":
            self.draw_info_row(painter, rect, "TIME", calc.sec2laptime(self.laptime_current)[:8])
        elif name == "locking":
            self.draw_info_row(painter, rect, "LOCK", f"{self.locking_front:.0f}/{self.locking_rear:.0f}")
        elif name == "pit_limiter":
            # Only active indicators, sharing the row
            active = [
                (text, color) for text, color, state in (
                    ("PIT", wcfg["pit_active_color"], self.in_pits),
                    ("LIM", wcfg["limiter_active_color"], self.limiter),
                ) if state
            ]
            gap = unit * 0.2
            item_w = (rect.width() - gap * (len(active) - 1)) / max(len(active), 1)
            for index, (text, color) in enumerate(active):
                item = QRectF(rect.left() + index * (item_w + gap), rect.top(), item_w, rect.height())
                self.draw_indicator(painter, item, text, True, color)
        elif name == "gear":
            painter.setPen(QColor(self.gear_color()))
            self.draw_fit_text(painter, rect, self.gear_text(), self.font_gear)
        elif name == "speed":
            text = f"{self.unit_speed(self.speed):.0f} {self.speed_label}"
            if self.justify_center:
                self.draw_info_row(painter, rect, "SPD", text)
            else:
                painter.setPen(self.pen_text)
                self.draw_fit_text(painter, rect, text, self.font_speed)
        elif name == "rpm":
            text_rect = QRectF(rect.left(), rect.top(), rect.width(), rect.height() - unit * 0.3)
            if self.justify_center:
                self.draw_info_row(painter, text_rect, "RPM", f"{self.rpm:.0f}")
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

    def draw_bottom_rows(self, painter: QPainter):
        """Refuel / refill row, fuel / energy remaining row"""
        wcfg = self.wcfg
        rows = []
        if wcfg["show_refuel"] or wcfg["show_refill"]:
            rows.append((
                ("Refuel", f"{self.unit_fuel(self.refuel):+.1f} {self.fuel_label}") if wcfg["show_refuel"] else None,
                ("Refill", f"{self.refill:+.1f} %") if wcfg["show_refill"] and self.energy_available else None,
            ))
        if wcfg["show_fuel_remaining"] or wcfg["show_energy_remaining"]:
            rows.append((
                ("Fuel", f"{self.unit_fuel(self.fuel):.1f} {self.fuel_label} · {self.fuel_laps:.1f} {LAPS_LABEL}")
                if wcfg["show_fuel_remaining"] else None,
                ("Energy", f"{self.energy:.0f}% · {self.energy_laps:.1f} {LAPS_LABEL}")
                if wcfg["show_energy_remaining"] and self.energy_available else None,
            ))
        for (rect_left, rect_right), (left, right) in zip(self.bottom_rows, rows):
            if left:
                self.draw_info_row(painter, rect_left, *left)
            if right:
                self.draw_info_row(painter, rect_right, *right)

    def draw_info_row(self, painter: QPainter, row: QRectF, label: str, value: str, color: str = ""):
        """Info row: label on left, value on right"""
        unit = self.unit
        fill_rect(painter, row, self.wcfg["info_background_color"])
        inner = row.adjusted(unit * 0.25, 0, -unit * 0.25, 0)
        painter.setFont(self.font_small)
        painter.setPen(QColor(self.wcfg["font_color_info_label"]))
        painter.drawText(inner, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        label_w = painter.fontMetrics().horizontalAdvance(label)
        painter.setPen(QColor(color) if color else self.pen_text)
        value_rect = inner.adjusted(label_w + unit * 0.3, 0, 0, 0)
        self.draw_fit_text(painter, value_rect, value, self.font(),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def gear_text(self) -> str:
        if self.gear > 0:
            return str(self.gear)
        return "R" if self.gear < 0 else "N"
    def draw_indicator(self, painter: QPainter, rect: QRectF, text: str, active: bool, color: str):
        fill_chip(painter, rect, color if active else self.wcfg["indicator_inactive_color"])
        painter.setPen(QColor(self.wcfg["font_color_indicator_active" if active else "font_color_indicator"]))
        self.draw_fit_text(painter, rect.adjusted(rect.width() * 0.04, 0, -rect.width() * 0.04, 0), text, self.font())
    def draw_fit_text(self, painter: QPainter, rect: QRectF, text: str, font: QFont,
                      align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter):
        """Draw text with font adapted to box size"""
        painter.setFont(fit_font(painter, font, text, rect.width() * 0.96, rect.height() * 1.1))
        painter.drawText(rect, align, text)
        painter.setFont(self.font())

    def format_temp(self, value: float) -> str:
        if value < -100:
            return "-"
        return f"{self.unit_temp(value):.0f}{self.sign_text}"
