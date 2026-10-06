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

import math
from collections.abc import Sequence
from time import monotonic
from typing import Any

from ... import calculation as calc
from ...api_control import api
from ...const_common import WHEELS_ZERO
from ...module_info import minfo
from ...process.game_info import IMMOVABLE, player_contacts
from ...replay import replay
from ...userfile.heatmap import (
    HEATMAP_DEFAULT_BRAKE,
    HEATMAP_DEFAULT_TYRE,
    load_heatmap_color,
    select_brake_heatmap_name,
    select_compound_symbol,
    select_tyre_heatmap_name,
    set_predefined_brake_name,
)
from .._common import tyre_punctured
from .common import REAR_MAX_STEER
from .recorder import EXPORT_QUEUE, IncidentBrowse, RaceReadings, Sample, index_of, log_race_events
from .sizing import Presence
from .state import (
    AIRBORNE_LOAD,
    NO_STATUS,
    WheelState,
    brake_laps_left,
    camber_spread,
    class_target,
    impact_arrow,
    rounded,
    wheel_offset,
)
from .suspension import TYRE_DIAMETER_MM

MIN_AIRBORNE_SPEED = 5.0  # m/s, below this a light tyre load is a car at rest or jacked up


def is_new_impact(impact_time: float, last_time: float) -> bool:
    """Game impact time stamp moved forward: a new impact

    It goes back to 0 (or lower) on a new session or restart, which is not an impact.
    """
    return math.isfinite(impact_time) and impact_time > 0 and impact_time > last_time


CONTACT_REPEAT_SECONDS = 2.0  # contacts with the same car closer in time: one contact
CONTACT_RECENT_SECONDS = 10.0  # contacts older than this when first seen are not logged


class DataReader:
    """Read telemetry into widget state, decide when to repaint"""

    # Attributes set by black box widget class (widget/black_box.py) or other parts
    alert_pulse: Any
    auto_resize: Any
    battery_flash: Any
    battery_high: Any
    battery_low: Any
    bottoming_threshold: Any
    brake_class_targets: Any
    brake_fades: Any
    brake_imbalance_threshold: Any
    brake_peaks: Any
    brake_trends: Any
    center_order: Any
    compound_targets: Any
    default_brake_window: Any
    default_targets: Any
    default_targets_rear: Any
    event_labels: Any
    event_log: Any
    export_folder: Any
    export_format: Any
    gauge_low: Any
    heatmap_tyre: Any
    incident_display_time: Any
    incident_replay: Any
    lap_stats: Any
    led_h: Any
    lock_threshold: Any
    locked_threshold: Any
    log_contact_events: Any
    contacts_logged: Any
    contacts_seen: Any
    contacts_session_time: Any
    log_engine_events: Any
    log_flag_events: Any
    log_penalty_events: Any
    log_pit_events: Any
    log_race_events: Any
    match_heatmap: Any
    max_steer: Any
    min_speed: Any
    module_check_every: Any
    modules: Any
    need_brake_bias: Any
    need_brake_heat: Any
    need_brake_migration: Any
    need_motor_map: Any
    need_compound: Any
    need_damage_total: Any
    need_delta: Any
    need_energy_rows: Any
    need_engine: Any
    need_fuel_rows: Any
    need_gear: Any
    need_lap_stats: Any
    need_laptime: Any
    need_lights: Any
    need_limiter: Any
    need_locking: Any
    need_pedals: Any
    need_pressure: Any
    need_rpm: Any
    need_slip: Any
    need_switches: Any
    need_temp_trend: Any
    paused_total: Any
    pres_trends: Any
    presence: Any
    pressure_ranges: Any
    recorder: Any
    relayout: Any
    resize_debounce: Any
    show_battery_bar: Any
    show_brake_peak: Any
    show_brake_trend: Any
    show_camber_spread: Any
    show_damage_panel: Any
    show_event_log: Any
    show_heave: Any
    show_pres_trend: Any
    show_pressure_range: Any
    show_recorder: Any
    show_stint: Any
    show_surface_overheat: Any
    show_susp_damage: Any
    show_suspension: Any
    show_tyre_wear: Any
    sign_text: Any
    slow_every: Any
    smooth_transition: Any
    spin_threshold: Any
    steer_convention: Any
    stint: Any
    susp_bump_margin: Any
    susp_bumps: Any
    susp_low_speed: Any
    susp_travels: Any
    suspension_totaled: Any
    temp_trends: Any
    tick: Any
    trace_version: Any
    tyre_fades: Any
    tyre_temp_source: Any
    unit_temp: Any
    update: Any
    wcfg: Any
    wear_forecast_laps: Any
    wheel_targets: Any
    wheels: Any

    # Widget state written here, initialized by BlackBox (declared for type checking)
    browse_seen: int
    last_state: tuple
    last_pits_state: bool | None
    heatmap_brake: list
    steer_vehicle: str | None
    last_vehicle_name: str | None
    impact_time: float | None
    recorder_impact_time: float | None
    impact_direction: str
    pause_start: float | None
    last_session_elapsed: float
    last_fast_time: float
    brake_cold: float
    brake_hot: float
    brake_class: str | None
    susp_vehicle: str | None
    last_in_pits: int
    last_compounds: tuple
    last_vehicle: tuple[str, str]
    tyre_diameters: tuple[float, ...]

    def load_tyre_heatmap(self, name: str):
        return load_heatmap_color(heatmap_name=name, default_name=HEATMAP_DEFAULT_TYRE, swap_style=True,
                                  fg_color=self.wcfg["font_color_temperature"])

    def load_brake_heatmap(self, name: str):
        # Text & disc mark color on panel (first color: darkened on light overlay themes)
        return load_heatmap_color(heatmap_name=name, default_name=HEATMAP_DEFAULT_BRAKE)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        slow = self.tick % self.slow_every == 0
        if self.tick % self.module_check_every == 0 and self.modules.refresh():
            self.apply_module_status()
        self.tick += 1
        in_pits = api.read.vehicle.in_pits()  # read once, also used by compound matching
        if slow:  # car only changes in pit: read with slow data, used by every part
            self.vehicle_name = api.read.vehicle.vehicle_name()
        if self.need_compound:
            self.update_compound_state(in_pits)
        if slow:
            self.update_slow(in_pits)
        self.update_fast(in_pits)
        if IncidentBrowse.requests != self.browse_seen:
            self.browse_seen = IncidentBrowse.requests
            self.browse_next_incident()

        if self.auto_resize and slow:
            self.update_presence()
        state = self.render_state()
        if state != self.last_state or self.animating():
            self.last_state = state
            self.update()

    def update_slow(self, in_pits):
        """Slow changing data: temperatures, pressure, wear, damage, fuel"""
        wcfg = self.wcfg
        tyre_temp = self.read_tyre_temperature()
        brake_temp = api.read.brake.temperature()
        pressure = api.read.tyre.pressure() if self.need_pressure else WHEELS_ZERO
        tread = api.read.tyre.wear() if self.show_tyre_wear else WHEELS_ZERO  # remaining tread (fraction)
        self.check_new_session()
        ico = (api.read.tyre.surface_temperature_ico()
               if wcfg["show_tyre_temperature_bands"] or self.show_camber_spread else ())
        if self.show_surface_overheat:
            surface = tyre_temp if self.tyre_temp_source == "Surface" else api.read.tyre.surface_temperature_avg()
        leaving = self.last_pits_state is not None and self.last_pits_state and not in_pits
        self.last_pits_state = bool(in_pits)
        braking = self.show_brake_peak and api.read.inputs.brake_raw() > 0.05
        if wcfg["show_tyre_status"]:
            detached = api.read.wheel.is_detached()
            puncture = tyre_punctured()
            locking_wear = minfo.wheels.lockingTreadWear if self.use_wheels else WHEELS_ZERO
        else:
            detached = puncture = NO_STATUS
            locking_wear = WHEELS_ZERO
        if self.need_damage_total or self.show_damage_panel or self.show_susp_damage:
            suspension = api.read.wheel.suspension_damage()
        else:
            suspension = WHEELS_ZERO
        carcass = api.read.tyre.carcass_temperature() if wcfg["show_tyre_carcass_temperature"] else WHEELS_ZERO
        # End of stint wear: over tyre_wear_forecast_laps if set, else over laps left in tank
        end_stint = wcfg["show_tyre_wear_end_stint"] and self.use_wheels and (
            self.use_fuel or self.wear_forecast_laps > 0)
        if end_stint:
            if self.wear_forecast_laps > 0:
                run_laps = self.wear_forecast_laps
            elif minfo.energy.available:
                run_laps = min(minfo.fuel.estimatedLaps, minfo.energy.estimatedLaps)
            else:
                run_laps = minfo.fuel.estimatedLaps
        need_wear_per_lap = (wcfg["show_tyre_wear_per_lap"] or self.show_stint) and self.use_wheels
        brake_wear = wcfg["show_brake_wear"] and self.use_wheels
        now = monotonic()

        for index, wheel in enumerate(self.wheels):
            wheel.tyre_temp = tyre_temp[index]
            wheel.brake_temp = brake_temp[index]
            wheel.pressure = pressure[index]
            wheel.tread = tread[index] * 100
            wheel.tyre_color = calc.select_grade(self.heatmap_tyre[index], wheel.tyre_temp)[1]
            wheel.brake_color = calc.select_grade(self.heatmap_brake[index], wheel.brake_temp)[0]
            if ico:
                temps = ico[index * 3:index * 3 + 3]
                if wcfg["show_tyre_temperature_bands"]:
                    wheel.ico_colors = self.band_colors(index, temps)
                wheel.camber_spread = camber_spread(index, *temps)
            if self.show_surface_overheat:
                hot = self.wheel_targets[index][3]
                wheel.surface_hot = 0 < hot <= surface[index] and wheel.tyre_temp < hot
            if self.show_pressure_range:
                if leaving:  # new stint
                    self.pressure_ranges[index].reset()
                if not in_pits:
                    self.pressure_ranges[index].update(wheel.pressure)
                wheel.pressure_min = self.pressure_ranges[index].low
                wheel.pressure_max = self.pressure_ranges[index].high
            if self.show_brake_peak:
                wheel.brake_peak = self.brake_peaks[index].update(wheel.brake_temp, braking)
            wheel.status = self.tyre_status(detached[index], puncture[index], locking_wear[index])
            wheel.carcass_temp = carcass[index]
            if self.show_susp_damage:
                damage = suspension[index]
                wheel.susp_damage = min(max(damage, 0.0), 1.0) if math.isfinite(damage) else 0.0
            if need_wear_per_lap:
                wheel.wear_per_lap = minfo.wheels.estimatedValidTreadWear[index]
            if end_stint:
                self.update_end_stint_tread(wheel, index, run_laps)
            if brake_wear:
                self.update_brake_wear(wheel, index)
            if self.need_temp_trend:
                wheel.temp_trend = self.temp_trends[index].update(now, wheel.tyre_temp, wheel.tyre_temp > -100)
            if self.show_pres_trend:
                wheel.pressure_trend = self.pres_trends[index].update(now, wheel.pressure, wheel.pressure > 0)
            if self.show_brake_trend:
                wheel.brake_trend = self.brake_trends[index].update(now, wheel.brake_temp, wheel.brake_temp > -100)
        if self.show_suspension and self.use_wheels:
            self.update_tyre_diameters(minfo.wheels.wheelRadius)
        if self.brake_imbalance_threshold > 0 and wcfg["show_brake_temperature"]:
            self.update_brake_imbalance()
        if self.need_brake_heat:
            front = (self.wheels[0].brake_temp + self.wheels[1].brake_temp) / 2
            rear = (self.wheels[2].brake_temp + self.wheels[3].brake_temp) / 2
            self.brake_heat_balance = front - rear if math.isfinite(front - rear) else 0.0

        if self.brake_class_targets and wcfg["show_brake_temperature"]:
            self.update_brake_window(api.read.vehicle.class_name())
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
        if self.need_fuel_rows and self.use_fuel:
            self.refuel = minfo.fuel.neededRelative
            self.fuel_capacity = minfo.fuel.capacity
            self.fuel_start = minfo.fuel.amountStart
            self.fuel = minfo.fuel.amountCurrent
            self.fuel_laps = minfo.fuel.estimatedLaps
        if self.need_energy_rows and self.use_fuel:
            self.refill = minfo.energy.neededRelative
            self.energy_capacity = minfo.energy.capacity
            self.energy_start = minfo.energy.amountStart
            self.energy = minfo.energy.amountCurrent
            self.energy_laps = minfo.energy.estimatedLaps
            self.energy_available = minfo.energy.available

    def read_tyre_temperature(self) -> tuple[float, ...]:
        """Tyre temperature that colors the tyre & drives its warnings (tyre_temperature_source)

        Surface reacts within milliseconds to a slide and cools on every straight; the inner layer
        (default) and carcass follow the temperature the rubber actually works at, so the color
        tells whether the tyre is in its window instead of flickering with each corner.
        """
        source = self.tyre_temp_source
        if source == "Surface":
            return api.read.tyre.surface_temperature_avg()
        if source == "Carcass":
            return api.read.tyre.carcass_temperature()
        return api.read.tyre.inner_temperature_avg()

    def update_fast(self, in_pits):
        """Fast changing data: slip, steering, center column, battery"""
        wcfg = self.wcfg
        speed = api.read.vehicle.speed()
        need_slip = self.need_slip and self.use_wheels
        steer = bool(self.max_steer)
        camber = wcfg["show_wheel_camber"] and self.use_wheels
        slip_angle = wcfg["show_tyre_slip_angle"] and self.use_wheels
        if need_slip:
            slip_ratio = minfo.wheels.slipRatio
            braking = api.read.inputs.brake_raw() > 0.02
        # Diagnostic readings: each reader is skipped unless its own reading is turned on
        ride_height = (api.read.wheel.ride_height()
                       if wcfg["show_ride_height"] or self.need_lap_stats else WHEELS_ZERO)
        heave = api.read.wheel.third_spring_deflection() if self.show_heave else WHEELS_ZERO
        brake_pressure = api.read.brake.pressure() if wcfg["show_brake_pressure"] else WHEELS_ZERO
        if wcfg["show_tyre_load"]:
            tyre_load = api.read.tyre.load()  # Newtons
            total_load = sum(tyre_load)
        else:
            tyre_load = WHEELS_ZERO
            total_load = 0.0
        if steer:  # real wheel angle 1:1, from game (radians), signed as learned by steer convention
            if self.steer_vehicle != self.vehicle_name:  # new car: learn again
                self.steer_vehicle = self.vehicle_name
                self.steer_convention.reset()
            wheel_angle = [math.degrees(angle) if math.isfinite(angle) else 0.0 for angle in api.read.wheel.toe()]
            self.steer_convention.update(wheel_angle[0], wheel_angle[1], api.read.inputs.steering())

        for index, wheel in enumerate(self.wheels):
            if need_slip:
                wheel.warning = self.slip_warning(slip_ratio[index], speed, braking)
            wheel.ride_height = ride_height[index]  # millimeters (converted by API)
            wheel.heave = heave[index]
            wheel.brake_pressure = brake_pressure[index] * 100
            wheel.load_ratio = calc.part_to_whole_ratio(tyre_load[index], total_load) * 100
            wheel.load = tyre_load[index]
            if camber:
                wheel.camber = minfo.wheels.camberAngle[index]
            if slip_angle:
                wheel.slip_angle = minfo.wheels.slipAngle[index]
            if steer:
                angle = self.steer_convention.screen_angle(index, wheel_angle[index])
                limit = self.max_steer if index < 2 else min(self.max_steer, REAR_MAX_STEER)  # room sized per axle
                wheel.steer = min(max(angle, -limit), limit)

        if self.need_switches:
            vehicle_name = self.vehicle_name
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
        if self.need_locking and self.use_wheels:
            self.locking_front = minfo.wheels.lockingPercentFront * 100
            self.locking_rear = minfo.wheels.lockingPercentRear * 100
        if self.need_brake_migration:
            self.brake_migration = api.read.brake.migration()
        if self.need_motor_map:
            self.motor_map_level = api.read.switch.motor_map_level()
        if self.need_delta and self.use_delta:
            self.delta_best = self.read_delta()
        if self.need_laptime and self.use_delta:
            self.laptime_current = minfo.delta.lapTimeCurrent
        self.in_pits = bool(in_pits)
        if self.need_limiter:
            self.limiter = bool(api.read.switch.speed_limiter())
        if self.need_lights:
            self.headlights = bool(api.read.switch.headlights())
        if self.need_engine:
            self.ignition = api.read.switch.ignition_starter() * (
                1 + (api.read.engine.rpm() > self.wcfg["stalling_rpm_threshold"]))
            self.oil_temp = api.read.engine.oil_temperature()
            self.water_temp = api.read.engine.water_temperature()
        if self.need_gear:
            self.gear = api.read.engine.gear()
        self.speed = speed
        if self.need_rpm:
            self.rpm = api.read.engine.rpm()
            self.rpm_max = api.read.engine.rpm_max()
        if self.need_pedals:
            self.read_pedals()
        if self.show_suspension:
            self.update_suspension(speed)
        if self.need_lap_stats:
            self.update_lap_stats()
        if self.show_recorder:
            self.update_recorder(speed)
        if self.log_race_events:
            self.update_race_events(in_pits)
        if self.log_contact_events:
            self.update_contact_events()
        if self.show_battery_bar and self.use_hybrid:
            self.battery_charge = minfo.hybrid.batteryCharge
            self.battery_state = minfo.hybrid.motorState
            self.battery_warning = self.battery_warning_level()
            if self.battery_flash is not None:
                self.battery_highlight = self.battery_flash.send(self.battery_warning)

    def read_delta(self) -> float:
        """Delta against the lap chosen in deltabest_source: best, session best, stint best or last lap"""
        source = self.wcfg["deltabest_source"]
        if source == "Session":
            return minfo.delta.deltaSession
        if source == "Stint":
            return minfo.delta.deltaStint
        if source == "Last":
            return minfo.delta.deltaLast
        return minfo.delta.deltaBest

    def read_pedals(self):
        """Pedals as pressed by the driver (Raw), or as the car receives them (Filtered: after
        game filtering, auto blip, traction control throttle cut, ABS)"""
        inputs = api.read.inputs
        if self.wcfg["pedal_input_source"] == "Filtered":
            self.throttle, self.brake = inputs.throttle(), inputs.brake()
            if self.wcfg["show_clutch_bar"]:
                self.clutch = inputs.clutch()
        else:
            self.throttle, self.brake = inputs.throttle_raw(), inputs.brake_raw()
            if self.wcfg["show_clutch_bar"]:
                self.clutch = inputs.clutch_raw()

    def current_presence(self) -> Presence:
        """Blocks the current car & data have, blocks without data are dropped from layout"""
        return Presence(
            fuel_row=self.use_fuel,
            energy_row=self.use_fuel and self.energy_available,
            battery=self.use_hybrid and self.has_hybrid,
            abs=self.has_abs,
            tc=self.has_tc,
            stint=self.stint_wear > 0 or self.stint_pressure > 0 or self.stint_has_previous,
        )

    def update_presence(self):
        """Relayout once a presence change stayed stable for resize_delay"""
        target = self.resize_debounce.update(self.current_presence(), monotonic())
        if target != self.presence:
            self.relayout(target)
            self.last_state = ()  # repaint

    def apply_module_status(self):
        """Use data of enabled modules only, clear data of the others so nothing stays frozen"""
        modules = self.modules
        self.use_wheels = modules.ready("module_wheels")
        self.use_fuel = modules.ready("module_fuel")
        self.use_delta = modules.ready("module_delta")
        self.use_hybrid = modules.ready("module_hybrid")
        if not self.use_wheels:
            for wheel in self.wheels:
                wheel.warning = ""
                wheel.steer = wheel.camber = wheel.slip_angle = wheel.wear_per_lap = 0.0
                wheel.tread_end_known = wheel.brake_wear_known = False
                if wheel.status == "flat":
                    wheel.status = ""
            self.locking_front = self.locking_rear = 0.0
        if not self.use_fuel:
            self.fuel = self.fuel_capacity = self.fuel_start = self.refuel = self.fuel_laps = 0.0
            self.energy = self.energy_capacity = self.energy_start = self.refill = self.energy_laps = 0.0
            self.energy_available = False
        if not self.use_delta:
            self.delta_best = self.laptime_current = 0.0
        if not self.use_hybrid:
            self.battery_charge = 0.0
            self.battery_state = self.battery_warning = 0

    def update_damage_panel(self, suspension):
        """Wheel, tyre & aero damage, last impact (same data as the Damage widget)"""
        self.damage_suspension = tuple(suspension)
        self.damage_detached = tuple(api.read.wheel.is_detached())
        self.damage_puncture = tyre_punctured()
        self.damage_aero = api.read.vehicle.aero_damage()
        if not self.wcfg["show_damage_panel_impact_cone"]:
            return
        impact_time = api.read.vehicle.impact_time()
        if self.impact_time is None or not is_new_impact(impact_time, self.impact_time):
            self.impact_time = impact_time  # before widget started, or new session: not shown
        elif impact_time != self.impact_time:
            self.impact_time = impact_time
            self.impact_position = api.read.vehicle.impact_position()
            self.impact_visible = True
        if self.impact_visible and (
            api.read.timing.elapsed() - self.impact_time > self.wcfg["damage_panel_impact_cone_duration"]
        ):
            self.impact_visible = False

    def recorder_now(self) -> float:
        """Recorder clock: monotonic seconds, stopped while the game is paused

        A pause leaves no gap in the recording, and a frozen incident stays on screen
        as long as the pause lasts.
        """
        now = monotonic()
        paused = bool(api.read.state.paused())
        if paused and self.pause_start is None:
            self.pause_start = now
        elif not paused and self.pause_start is not None:
            self.paused_total += now - self.pause_start
            self.pause_start = None
        return (self.pause_start if self.pause_start is not None else now) - self.paused_total

    def update_recorder(self, speed: float):
        """Feed incident recorder, log & save incident once recorded"""
        recorder = self.recorder
        now = self.recorder_now()
        if self.pause_start is not None:  # paused: nothing happens on track
            return
        warnings = [wheel.warning for wheel in self.wheels]
        slip = "lock" if ("lock" in warnings or "locked" in warnings) else "spin" if "spin" in warnings else ""
        last_time = recorder.samples[-1].time if recorder.samples else None
        impact_time = api.read.vehicle.impact_time()
        impact = self.recorder_impact_time is not None and is_new_impact(impact_time, self.recorder_impact_time)
        self.recorder_impact_time = impact_time  # impact before widget started: not an incident
        if impact:  # same direction as the damage panel cone
            self.impact_direction = impact_arrow(calc.degrees(calc.oriyaw(*api.read.vehicle.impact_position())))
        slips = tuple(minfo.wheels.slipRatio) if self.use_wheels else WHEELS_ZERO
        incident = recorder.add(
            Sample(now, speed, self.throttle, self.brake, self.gear, self.abs_active, self.tc_active, slip,
                   api.read.inputs.steering(), slips, tuple(api.read.tyre.load())),
            self.damage_total,
            api.read.lap.number(),
            api.read.session.elapsed(),
            impact,
            self.impact_direction,
        )
        if recorder.samples and recorder.samples[-1].time != last_time:
            self.trace_version += 1
        if incident is not None:
            self.record_incident(incident)

    def record_incident(self, incident):
        """Log incident, show it first, save it in the background"""
        direction = f" {incident.direction}" if incident.direction else ""
        self.event_log.add(
            incident.lap, incident.session_time,
            f"{self.event_labels['impact']} {incident.peak_g:.1f}g{direction}", incident.peak_g >= 10,
        )
        self.browse_incident = None  # a new incident is shown first
        # Marker at trigger time in replay being recorded, see Session recorder window
        latest = incident.samples[-1].time if incident.samples else incident.time
        replay.add_marker("incident", f"{incident.peak_g:.1f}g", latest - incident.time)
        if self.export_folder:
            EXPORT_QUEUE.submit(incident, self.export_folder, self.export_format)

    def update_race_events(self, in_pits):
        """Event log: flags, pit lane, penalties, track limits, engine overheat"""
        wcfg = self.wcfg
        flags = self.log_flag_events
        penalties = self.log_penalty_events
        engine = self.log_engine_events
        if engine:
            oil = api.read.engine.oil_temperature()
            water = api.read.engine.water_temperature()
        else:
            oil = water = 0.0
        readings = RaceReadings(
            yellow=bool(api.read.session.yellow_flag()) if flags else None,
            blue=bool(api.read.session.blue_flag()) if flags else None,
            in_pits=bool(in_pits) if self.log_pit_events else None,
            penalties=api.read.vehicle.number_penalties() if penalties else None,
            cut_points=api.read.session.cut_points() if penalties else None,
            limit_points=api.read.session.limits_points() if penalties else 0.0,
            oil_hot=oil >= wcfg["engine_oil_warning_temperature"] if engine else None,
            water_hot=water >= wcfg["engine_water_warning_temperature"] if engine else None,
            oil=oil, water=water,
        )
        log_race_events(
            self.event_log, api.read.lap.number(), api.read.session.elapsed(), readings, self.event_labels,
            lambda value: f"{self.unit_temp(value):.0f}{self.sign_text}",
        )

    def update_contact_events(self):
        """Event log: contacts of player with other cars & walls, from game contact list (LMU),
        each contact once as it happens (contacts from before widget started not logged)"""
        now = api.read.session.elapsed()
        if now < self.contacts_session_time:  # new session
            self.contacts_logged.clear()
        self.contacts_session_time = now
        contacts = api.read.session.contacts()
        if contacts is self.contacts_seen:  # list unchanged
            return
        self.contacts_seen = contacts
        for time, other in player_contacts(contacts, api.read.vehicle.driver_name()):
            # Same contact reported again (or by the other car), or contacts in a row: logged once
            if time <= self.contacts_logged.get(other, -1.0) + CONTACT_REPEAT_SECONDS:
                continue
            self.contacts_logged[other] = time
            if now - time > CONTACT_RECENT_SECONDS:  # already over when first seen
                continue
            labels = self.event_labels
            text = labels["wall"] if other == IMMOVABLE else f"{labels['contact']} {other}"
            self.event_log.add(api.read.lap.number(), time, text)

    def displayed_incident(self, now: float | None = None):
        """Incident the trace shows frozen: picked with the hotkey, or the last one, for
        incident_display_duration seconds; None while showing the live recording"""
        if self.incident_display_time <= 0 or not self.recorder.incidents:
            return None
        now = self.recorder_now() if now is None else now
        if self.browse_incident is not None and now - self.browse_since < self.incident_display_time:
            return self.browse_incident
        last = self.recorder.last_incident
        return last if last is not None and now - last.time < self.incident_display_time else None

    def showing_incident(self, now: float | None = None) -> bool:
        """Trace shows an incident (frozen) instead of live recording"""
        return self.displayed_incident(now) is not None

    def browse_next_incident(self):
        """Hotkey: show the next older incident, back to the newest after the oldest"""
        incidents = list(self.recorder.incidents)
        if not incidents:
            return
        now = self.recorder_now()
        shown = self.displayed_incident(now)
        position = index_of(incidents, shown) if shown is not None else -1
        position = len(incidents) if position < 0 else position
        self.browse_incident = incidents[position - 1] if position > 0 else incidents[-1]
        self.browse_since = now
        self.last_state = ()  # repaint

    def check_new_session(self):
        """New session (session time going back): recorder & event log forget the old session,
        lap statistics and stint pressure range start again"""
        elapsed = api.read.session.elapsed()
        if math.isfinite(elapsed) and elapsed < self.last_session_elapsed - 1:
            incident = self.recorder.reset()  # incident still recording is kept, not lost
            if incident is not None:
                self.record_incident(incident)
            self.event_log.reset()
            for stats in self.lap_stats:
                stats.reset()
            for pressure_range in self.pressure_ranges:
                pressure_range.reset()
            self.stats_lap = None
        self.last_session_elapsed = elapsed if math.isfinite(elapsed) else 0.0

    def update_lap_stats(self):
        """Per wheel over the current lap: lowest ride height, bottoming, bump stop contacts,
        travel used, damper speed histogram (reset on each new lap)"""
        lap = api.read.lap.number()
        if lap != self.stats_lap:
            self.stats_lap = lap
            for stats in self.lap_stats:
                stats.reset()
        now = monotonic()
        elapsed = now - self.last_fast_time
        self.last_fast_time = now
        for wheel, stats in zip(self.wheels, self.lap_stats):
            stats.update_ride(wheel.ride_height, self.bottoming_threshold)
            wheel.ride_height_min = stats.ride_min
            wheel.bottoming = stats.bottoming
            if self.show_suspension:
                stats.update_bump(wheel.susp_bump)
                stats.update_travel(wheel.susp_travel)
                stats.update_damper(wheel.susp_velocity, elapsed, self.susp_low_speed)
                wheel.bumps = stats.bumps
                wheel.travel_min, wheel.travel_max = stats.travel_min, stats.travel_max
                wheel.damper_shares = stats.damper_shares()

    def update_brake_imbalance(self):
        """Axle discs far apart in temperature (sticking caliper, blocked duct), both warm enough"""
        floor = max(self.brake_cold, 100)
        for left, right in ((0, 1), (2, 3)):
            temp_left, temp_right = self.wheels[left].brake_temp, self.wheels[right].brake_temp
            flagged = (abs(temp_left - temp_right) >= self.brake_imbalance_threshold
                       and max(temp_left, temp_right) >= floor)
            self.wheels[left].brake_imbalance = self.wheels[right].brake_imbalance = flagged

    def update_suspension(self, speed: float):
        """Live suspension: spring & wheel offset from static position, damper speed, bump stop, airborne

        Range, static position and motion ratio from Wheels module when on, else learned per car
        (reset on car change).
        """
        vehicle = self.vehicle_name
        if vehicle != self.susp_vehicle:
            self.susp_vehicle = vehicle
            for travel in self.susp_travels:
                travel.reset()
            for bump in self.susp_bumps:
                bump.reset()
            self.tyre_diameters = (TYRE_DIAMETER_MM,) * 4  # learned again for the new car
        positions = api.read.wheel.suspension_deflection()
        forces = api.read.wheel.suspension_force()
        loads = api.read.tyre.load()
        now = monotonic()
        if self.use_wheels:
            lows: Sequence[float]
            highs: Sequence[float]
            statics: Sequence[float]
            ratios: Sequence[float]
            lows = minfo.wheels.minSuspensionPosition
            highs = minfo.wheels.maxSuspensionPosition
            statics = minfo.wheels.staticSuspensionPosition
            ratios = minfo.wheels.motionRatio
        else:
            lows = highs = statics = ratios = WHEELS_ZERO
        moving = speed > MIN_AIRBORNE_SPEED
        for index, wheel in enumerate(self.wheels):
            tracker = self.susp_travels[index]
            wheel.susp_travel, wheel.susp_velocity = tracker.update(positions[index], now, lows[index], highs[index])
            wheel.susp_static = tracker.ratio(statics[index], lows[index], highs[index])
            wheel.susp_offset = tracker.offset(positions[index], statics[index])
            wheel.susp_estimated = tracker.estimated
            wheel.susp_wheel_offset = wheel_offset(wheel.susp_offset, ratios[index])
            wheel.susp_airborne = moving and loads[index] < AIRBORNE_LOAD
            wheel.susp_bump = not wheel.susp_airborne and self.susp_bumps[index].update(
                positions[index], forces[index], wheel.susp_velocity, self.susp_low_speed, self.susp_bump_margin)

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
            rounded(self.brake_migration, 1), self.motor_map_level, rounded(self.delta_best, 3), rounded(self.laptime_current, 2),
            self.in_pits, self.limiter, self.headlights, self.ignition,
            rounded(self.oil_temp, 0), rounded(self.water_temp, 0), self.gear, rounded(self.speed, 1), rounded(self.rpm, 0), self.rpm_max,
            rounded(self.throttle, 3), rounded(self.brake, 3), rounded(self.clutch, 3),
            rounded(self.refuel, 1), rounded(self.refill, 1), rounded(self.fuel, 1), rounded(self.fuel_laps, 1),
            rounded(self.fuel_capacity, 1), rounded(self.fuel_start, 1),
            rounded(self.energy_capacity, 1), rounded(self.energy_start, 1),
            rounded(self.energy, 0), rounded(self.energy_laps, 1), self.energy_available,
            rounded(self.battery_charge, 0), self.battery_state, self.battery_warning, self.battery_highlight,
            rounded(self.stint_wear, 2), rounded(self.stint_wear_delta, 2),
            rounded(self.stint_pressure, 1), rounded(self.stint_pressure_delta, 1), self.stint_has_previous,
            self.trace_version if self.show_recorder and not self.showing_incident() else -1,
            len(self.recorder.incidents), self.show_recorder and self.showing_incident(),
            len(self.event_log.events), self.modules.version,
            self.damage_detached, self.damage_puncture, rounded(self.damage_aero, 2),
            tuple(rounded(value, 2) for value in self.damage_suspension), self.impact_visible,
            self.impact_position if self.impact_visible else None,
            self.event_log.events[-1] if self.event_log.events else None,
            self.brake_cold, self.brake_hot, tuple(self.wheel_targets), rounded(self.brake_heat_balance, 0),
            self.browse_incident.time if self.browse_incident is not None else None,
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
        if self.incident_replay and self.show_recorder and self.showing_incident():  # replay cursor
            return True
        if self.alert_pulse and any(wheel.warning or wheel.status for wheel in self.wheels):
            return True
        if self.alert_pulse and self.gauge_low():
            return True
        if self.alert_pulse and self.show_suspension and any(
            wheel.susp_bump or wheel.susp_airborne or self.suspension_totaled(wheel) for wheel in self.wheels
        ):
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
            current = minfo.wheels.currentBrakeThickness[index]
            wheel.brake_wear = (current - failure) * 100 / usable
            wheel.brake_laps = brake_laps_left(current, failure, minfo.wheels.estimatedValidBrakeWear[index])

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
        if braking and slip_ratio < self.locked_threshold:
            return "locked"
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
        """Band colors from left to right on screen

        Game reports each tyre left / center / right of the car (not inner / outer), which is
        already left to right seen from above: outer band of a left tyre is on the left.
        """
        left, center, right = (calc.select_grade(self.heatmap_tyre[index], temp)[1] for temp in temps)
        return left, center, right

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
                self.wheel_targets[index] = self.compound_target(compound, symbol, index >= 2)
        if not self.match_heatmap:
            return
        vehicle = (api.read.vehicle.class_name(), self.vehicle_name)
        if self.last_vehicle != vehicle:
            self.last_vehicle = vehicle
            front = self.load_brake_heatmap(select_brake_heatmap_name(set_predefined_brake_name(*vehicle, True)))
            rear = self.load_brake_heatmap(select_brake_heatmap_name(set_predefined_brake_name(*vehicle, False)))
            self.heatmap_brake = [front, front, rear, rear]

    def update_tyre_diameters(self, radii):
        """Tyre diameter (mm) per wheel from rolling radius learned by Wheels module, for 1:1 motion

        Kept at TYRE_DIAMETER_MM until a plausible radius is learned (0.25 to 0.45 m).
        """
        diameters = tuple(
            round(radius * 2000) if math.isfinite(radius) and 0.25 <= radius <= 0.45 else TYRE_DIAMETER_MM
            for radius in radii
        )
        if diameters != self.tyre_diameters:
            self.tyre_diameters = diameters

    def update_brake_window(self, class_name: str):
        """Brake cold & hot thresholds of the car class (brake_target_by_class), else defaults"""
        if class_name == self.brake_class:
            return
        self.brake_class = class_name
        target = class_target(self.brake_class_targets, class_name)
        self.brake_cold, self.brake_hot = target if target is not None else self.default_brake_window

    def compound_target(self, compound: str, symbol: str, rear: bool = False) -> tuple:
        """(pressure min, pressure max, cold, hot) of compound, matched by symbol or full name

        Rear wheels use the "symbol:R" entry when there is one (own rear pressure window).
        """
        target = None
        if rear:
            target = (self.compound_targets.get(f"{symbol.upper()}:R")
                      or self.compound_targets.get(f"{compound.upper()}:R"))
        target = target or self.compound_targets.get(symbol.upper()) or self.compound_targets.get(compound.upper())
        if target is None:
            return self.default_targets_rear if rear else self.default_targets
        p_min, p_max, t_min, t_max = target
        return (
            p_min, p_max,
            self.default_targets[2] if t_min is None else t_min,
            self.default_targets[3] if t_max is None else t_max,
        )
