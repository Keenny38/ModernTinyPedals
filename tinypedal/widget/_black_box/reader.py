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
Black box widget, read telemetry into widget state, decide when to repaint
"""

from __future__ import annotations

from time import monotonic

from ... import calculation as calc
from ...api_control import api
from ...const_common import WHEELS_ZERO
from ...module_info import minfo
from ...userfile.heatmap import (
    HEATMAP_DEFAULT_BRAKE,
    HEATMAP_DEFAULT_TYRE,
    load_heatmap_color,
    select_brake_heatmap_name,
    select_compound_symbol,
    select_tyre_heatmap_name,
    set_predefined_brake_name,
)
from .recorder import Sample, export_incident
from .state import (
    NO_STATUS,
    WheelState,
    rounded,
)


class DataReader:
    """Read telemetry into widget state, decide when to repaint"""

    def load_tyre_heatmap(self, name: str):
        return load_heatmap_color(heatmap_name=name, default_name=HEATMAP_DEFAULT_TYRE, swap_style=True,
                                  fg_color=self.wcfg["font_color_temperature"])

    def load_brake_heatmap(self, name: str):
        return load_heatmap_color(heatmap_name=name, default_name=HEATMAP_DEFAULT_BRAKE, swap_style=True,
                                  fg_color=self.wcfg["font_color_temperature"])

    def timerEvent(self, event):
        """Update when vehicle on track"""
        slow = self.tick % self.slow_every == 0
        self.tick += 1
        in_pits = api.read.vehicle.in_pits()  # read once, also used by compound matching
        if self.need_compound:
            self.update_compound_state(in_pits)
        if slow:
            self.update_slow(in_pits)
        self.update_fast(in_pits)

        state = self.render_state()
        if state != self.last_state or self.animating():
            self.last_state = state
            self.update()

    def update_slow(self, in_pits):
        """Slow changing data: temperatures, pressure, wear, damage, fuel"""
        wcfg = self.wcfg
        tyre_temp = api.read.tyre.surface_temperature_avg()
        brake_temp = api.read.brake.temperature()
        pressure = api.read.tyre.pressure() if self.need_pressure else WHEELS_ZERO
        tread = api.read.tyre.wear() if self.show_tyre_wear else WHEELS_ZERO  # remaining tread (fraction)
        ico = api.read.tyre.surface_temperature_ico() if wcfg["show_tyre_temperature_bands"] else ()
        if wcfg["show_tyre_status"]:
            detached = api.read.wheel.is_detached()
            puncture = api.read.tyre.puncture()
            locking_wear = minfo.wheels.lockingTreadWear
        else:
            detached = puncture = NO_STATUS
            locking_wear = WHEELS_ZERO
        if self.need_damage_total or self.show_damage_panel:
            suspension = api.read.wheel.suspension_damage()
        else:
            suspension = WHEELS_ZERO
        carcass = api.read.tyre.carcass_temperature() if wcfg["show_tyre_carcass_temperature"] else WHEELS_ZERO
        if wcfg["show_tyre_wear_end_stint"]:
            if minfo.energy.available:
                run_laps = min(minfo.fuel.estimatedLaps, minfo.energy.estimatedLaps)
            else:
                run_laps = minfo.fuel.estimatedLaps
        need_wear_per_lap = wcfg["show_tyre_wear_per_lap"] or self.show_stint
        now = monotonic()

        for index, wheel in enumerate(self.wheels):
            wheel.tyre_temp = tyre_temp[index]
            wheel.brake_temp = brake_temp[index]
            wheel.pressure = pressure[index]
            wheel.tread = tread[index] * 100
            wheel.tyre_color = calc.select_grade(self.heatmap_tyre[index], wheel.tyre_temp)[1]
            wheel.brake_color = calc.select_grade(self.heatmap_brake[index], wheel.brake_temp)[1]
            if ico:
                wheel.ico_colors = self.band_colors(index, ico[index * 3:index * 3 + 3])
            wheel.status = self.tyre_status(detached[index], puncture[index], locking_wear[index])
            wheel.carcass_temp = carcass[index]
            if need_wear_per_lap:
                wheel.wear_per_lap = minfo.wheels.estimatedValidTreadWear[index]
            if wcfg["show_tyre_wear_end_stint"]:
                self.update_end_stint_tread(wheel, index, run_laps)
            if wcfg["show_brake_wear"]:
                self.update_brake_wear(wheel, index)
            if self.need_temp_trend:
                wheel.temp_trend = self.temp_trends[index].update(now, wheel.tyre_temp, wheel.tyre_temp > -100)
            if self.show_pres_trend:
                wheel.pressure_trend = self.pres_trends[index].update(now, wheel.pressure, wheel.pressure > 0)

        if self.need_damage_total or self.show_damage_panel:
            self.body_damage = api.read.vehicle.damage_severity()
        if self.show_damage_panel:
            self.update_damage_panel(suspension)
        if self.need_damage_total:
            self.damage_total = float(sum(self.body_damage)) + float(sum(suspension))
        if self.show_event_log:
            self.event_log.update(
                api.read.lap.number(), api.read.session.elapsed(),
                [wheel.status for wheel in self.wheels], self.damage_total, self.event_labels,
            )
        if self.show_stint:
            self.update_stint(bool(in_pits))
        if self.need_fuel_rows:
            self.refuel = minfo.fuel.neededRelative
            self.fuel_capacity = minfo.fuel.capacity
            self.fuel_start = minfo.fuel.amountStart
            self.fuel = minfo.fuel.amountCurrent
            self.fuel_laps = minfo.fuel.estimatedLaps
        if self.need_energy_rows:
            self.refill = minfo.energy.neededRelative
            self.energy_capacity = minfo.energy.capacity
            self.energy_start = minfo.energy.amountStart
            self.energy = minfo.energy.amountCurrent
            self.energy_laps = minfo.energy.estimatedLaps
            self.energy_available = minfo.energy.available

    def update_fast(self, in_pits):
        """Fast changing data: slip, steering, center column, battery"""
        wcfg = self.wcfg
        speed = api.read.vehicle.speed()
        if self.need_slip:
            slip_ratio = minfo.wheels.slipRatio
            braking = api.read.inputs.brake_raw() > 0.02
        # Diagnostic readings: each reader is skipped unless its own reading is turned on
        ride_height = api.read.wheel.ride_height() if wcfg["show_ride_height"] else WHEELS_ZERO
        brake_pressure = api.read.brake.pressure() if wcfg["show_brake_pressure"] else WHEELS_ZERO
        if wcfg["show_tyre_load"]:
            tyre_load = api.read.tyre.load()
            total_load = sum(tyre_load)
        else:
            tyre_load = WHEELS_ZERO
            total_load = 0.0
        if self.max_steer:
            wheel_angle = minfo.wheels.toeAngle  # degrees, positive to right side of vehicle
            multiplier = wcfg["wheel_angle_multiplier"]

        for index, wheel in enumerate(self.wheels):
            if self.need_slip:
                wheel.warning = self.slip_warning(slip_ratio[index], speed, braking)
            wheel.ride_height = ride_height[index] * 1000  # meters to millimeters
            wheel.brake_pressure = brake_pressure[index] * 100
            wheel.load_ratio = calc.part_to_whole_ratio(tyre_load[index], total_load) * 100
            if wcfg["show_wheel_camber"]:
                wheel.camber = minfo.wheels.camberAngle[index]
            if wcfg["show_tyre_slip_angle"]:
                wheel.slip_angle = minfo.wheels.slipAngle[index]
            if self.max_steer:
                steer = wheel_angle[index] * multiplier
                wheel.steer = min(max(steer, -self.max_steer), self.max_steer)

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
        if self.show_recorder:
            self.update_recorder(speed)
        if self.show_battery_bar:
            self.battery_charge = minfo.hybrid.batteryCharge
            self.battery_state = minfo.hybrid.motorState
            self.battery_warning = self.battery_warning_level()
            if self.battery_flash is not None:
                self.battery_highlight = self.battery_flash.send(self.battery_warning)

    def update_damage_panel(self, suspension):
        """Wheel, tyre & aero damage, last impact (same data as the Damage widget)"""
        self.damage_suspension = tuple(suspension)
        self.damage_detached = tuple(api.read.wheel.is_detached())
        self.damage_puncture = tuple(api.read.tyre.puncture())
        self.damage_aero = api.read.vehicle.aero_damage()
        if not self.wcfg["show_damage_panel_impact_cone"]:
            return
        impact_time = api.read.vehicle.impact_time()
        if self.impact_time is None:  # impact before widget started: not shown
            self.impact_time = impact_time
        elif impact_time != self.impact_time:
            self.impact_time = impact_time
            self.impact_position = api.read.vehicle.impact_position()
            self.impact_visible = True
        if self.impact_visible and (
            api.read.timing.elapsed() - self.impact_time > self.wcfg["damage_panel_impact_cone_duration"]
        ):
            self.impact_visible = False

    def update_recorder(self, speed: float):
        """Feed incident recorder, log & save incident once recorded"""
        recorder = self.recorder
        now = monotonic()
        warnings = [wheel.warning for wheel in self.wheels]
        slip = "lock" if "lock" in warnings else "spin" if "spin" in warnings else ""
        last_time = recorder.samples[-1].time if recorder.samples else None
        incident = recorder.add(
            Sample(now, speed, self.throttle, self.brake, self.gear, self.abs_active, self.tc_active, slip),
            self.damage_total,
            api.read.lap.number(),
            api.read.session.elapsed(),
        )
        if recorder.samples and recorder.samples[-1].time != last_time:
            self.trace_version += 1
        if incident is None:
            return
        self.event_log.add(
            incident.lap, incident.session_time,
            f"{self.event_labels['impact']} {incident.peak_g:.1f}g", incident.peak_g >= 10,
        )
        if self.export_folder:
            export_incident(incident, self.export_folder)

    def showing_incident(self, now: float | None = None) -> bool:
        """Trace shows last incident (frozen) instead of live recording"""
        incident = self.recorder.last_incident
        if incident is None or self.incident_display_time <= 0:
            return False
        return (monotonic() if now is None else now) - incident.time < self.incident_display_time

    def update_stint(self, in_pits: bool):
        """Average tread wear per lap & pressure of 4 wheels, compared with previous stint"""
        pressures = [wheel.pressure for wheel in self.wheels if wheel.pressure > 0]
        wears = [wheel.wear_per_lap for wheel in self.wheels if wheel.wear_per_lap > 0]
        self.stint.update(
            in_pits,
            sum(wears) / len(wears) if wears else 0.0,
            sum(pressures) / len(pressures) if pressures else 0.0,
        )
        self.stint_wear, self.stint_pressure = self.stint.current()
        previous = self.stint.previous
        self.stint_has_previous = previous is not None
        if previous is not None:
            self.stint_wear_delta = self.stint_wear - previous[0] if self.stint_wear and previous[0] else 0.0
            self.stint_pressure_delta = (
                self.stint_pressure - previous[1] if self.stint_pressure and previous[1] else 0.0)

    def render_state(self) -> tuple:
        """Everything the paint depends on, rounded to display precision, to skip repaint if unchanged"""
        return (
            tuple(wheel.signature() for wheel in self.wheels),
            self.body_damage, self.abs_active, self.tc_active, self.abs_level, self.tc_level,
            self.tc_cut_level, self.tc_slip_level, self.abs_seen, self.tc_seen,
            rounded(self.brake_bias, 4), rounded(self.locking_front, 0), rounded(self.locking_rear, 0),
            rounded(self.brake_migration, 1), rounded(self.delta_best, 3), rounded(self.laptime_current, 2),
            self.in_pits, self.limiter, self.gear, rounded(self.speed, 1), rounded(self.rpm, 0), self.rpm_max,
            rounded(self.throttle, 3), rounded(self.brake, 3),
            rounded(self.refuel, 1), rounded(self.refill, 1), rounded(self.fuel, 1), rounded(self.fuel_laps, 1),
            rounded(self.fuel_capacity, 1), rounded(self.fuel_start, 1),
            rounded(self.energy_capacity, 1), rounded(self.energy_start, 1),
            rounded(self.energy, 0), rounded(self.energy_laps, 1), self.energy_available,
            rounded(self.battery_charge, 0), self.battery_state, self.battery_warning, self.battery_highlight,
            rounded(self.stint_wear, 2), rounded(self.stint_wear_delta, 2),
            rounded(self.stint_pressure, 1), rounded(self.stint_pressure_delta, 1), self.stint_has_previous,
            self.trace_version if self.show_recorder and not self.showing_incident() else -1,
            len(self.recorder.incidents), self.show_recorder and self.showing_incident(),
            len(self.event_log.events),
            self.damage_detached, self.damage_puncture, rounded(self.damage_aero, 2),
            tuple(rounded(value, 2) for value in self.damage_suspension), self.impact_visible,
            self.impact_position if self.impact_visible else None,
            self.event_log.events[-1] if self.event_log.events else None,
        )

    def animating(self) -> bool:
        """Something moves on screen without data change: shift flash, battery flow"""
        wcfg = self.wcfg
        if self.rpm_max > 0 and self.rpm / self.rpm_max >= wcfg["rpm_redline_ratio"] and (
            self.led_h or ("gear" in self.center_order and wcfg["enable_gear_rpm_color"]
                           and wcfg["enable_shift_flash"])
        ):
            return True
        now = monotonic()
        if self.smooth_transition and any(
            fade.active(now) for fade in (*self.tyre_fades, *self.brake_fades)
        ):
            return True
        if self.alert_pulse and any(wheel.warning or wheel.status for wheel in self.wheels):
            return True
        if self.alert_pulse and self.gauge_low():
            return True
        if self.alert_pulse and self.show_damage_panel and (
            any(self.damage_detached) or any(self.damage_puncture) or max(self.body_damage, default=0) >= 3
        ):
            return True
        return bool(self.show_battery_bar and wcfg["enable_battery_bar_animation"]
                    and self.battery_state in (2, 3))

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

    @property
    def has_hybrid(self) -> bool:
        """Car reports a hybrid system, otherwise the gauge has nothing to show

        The Hybrid module falls back to a derived motor state as soon as there is any charge,
        so no state and no charge together means no hybrid system (or no data yet).
        """
        return self.battery_state != 0 or self.battery_charge > 0

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
                symbol = select_compound_symbol(compound)
                self.wheels[index].compound = symbol  # shown only if show_tyre_compound
                self.wheel_targets[index] = self.compound_target(compound, symbol)
        if not self.match_heatmap:
            return
        vehicle = (api.read.vehicle.class_name(), api.read.vehicle.vehicle_name())
        if self.last_vehicle != vehicle:
            self.last_vehicle = vehicle
            front = self.load_brake_heatmap(select_brake_heatmap_name(set_predefined_brake_name(*vehicle, True)))
            rear = self.load_brake_heatmap(select_brake_heatmap_name(set_predefined_brake_name(*vehicle, False)))
            self.heatmap_brake = [front, front, rear, rear]

    def compound_target(self, compound: str, symbol: str) -> tuple:
        """(pressure min, pressure max, cold, hot) of compound, matched by symbol or full name"""
        target = self.compound_targets.get(symbol.upper()) or self.compound_targets.get(compound.upper())
        if target is None:
            return self.default_targets
        p_min, p_max, t_min, t_max = target
        return (
            p_min, p_max,
            self.default_targets[2] if t_min is None else t_min,
            self.default_targets[3] if t_max is None else t_max,
        )
