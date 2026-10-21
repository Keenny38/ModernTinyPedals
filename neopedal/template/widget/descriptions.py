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
Overlay descriptions: what each built-in overlay shows, in one short sentence (Overlays page)

English texts, translated with i18n.tr (French in i18n/fr.py). Plain data: no Qt import.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

OVERLAY_DESCRIPTIONS: Mapping[str, str] = MappingProxyType({
    "acceleration": "Acceleration times over a speed range you set: current, last, best and delta.",
    "battery": "Battery charge of hybrid cars: level, drain, regeneration and net change per lap.",
    "brake_bias": "Brake bias, change from baseline and live brake migration.",
    "brake_performance": "Braking rate in g and wheel lock time per lap.",
    "brake_pressure": "Brake pressure applied on each wheel, as bars.",
    "brake_temperature": "Temperature of each brake disc, colored by heatmap.",
    "brake_wear": "Wear of each brake and laps left (LMU).",
    "chat": "Chat messages of the game, newest at bottom (LMU).",
    "corner_coach": "Next corner against your reference lap: braking point and apex speed.",
    "cruise": "Compass, elevation, odometer and distance into lap.",
    "damage": "Car damage drawn on the car: body, aero, suspension and wheels.",
    "damage_stats": "Integrity left of aero, body, suspension and tyres, in numbers.",
    "delta_graph": "Delta to reference lap along the lap, as a graph.",
    "deltabest": "Live delta to your best lap, with a bar.",
    "deltabest_extended": "Live delta to several references at once: best, session, stint, last lap.",
    "differential": "Differential locking on power and coast.",
    "driver_rank": "Your Driver Rank, Safety Rank and track limits points (LMU).",
    "drs": "DRS (rear flap) availability and use.",
    "electric_motor": "Electric motor temperature, RPM, torque, power and regeneration level.",
    "elevation": "Elevation profile of the lap with your car on it.",
    "engine": "Engine oil & water temperatures, turbo, RPM, torque and power.",
    "engine_temperature": "Oil & water temperatures, their trend and overheating warning.",
    "flag": "Flags, pit state, penalties, start lights and warnings, as chips.",
    "force": "G forces, downforce ratio and car weight.",
    "friction_circle": "G force drawn in a circle, with recent trace.",
    "fuel": "Fuel left, use per lap, laps left, refuel needed and pit stops.",
    "fuel_energy_saver": "Target fuel or energy use per lap to stretch the stint by one or more laps.",
    "gap_trend": "Gaps to cars ahead and behind, and how they change lap after lap.",
    "gear": "Gear, speed, RPM bar and speed limiter.",
    "heading": "Car yaw, slip angle and heading lines.",
    "instrument": "Dashboard lights: headlights, ignition, clutch, wheel lock and spin.",
    "laps_and_position": "Lap number, overall & class position and track limits points.",
    "lap_time_history": "Lap times of the last laps with delta, fuel and wear.",
    "lift_and_coast_led": "LEDs for lift and coast, TC & ABS activation, wheel slip & lock (LMU).",
    "navigation": "Zoomed track map centered on your car, with cars around.",
    "onboard_setting": "Onboard settings: ABS, TC, brake migration, motor map, anti-roll bars (LMU).",
    "pace_notes": "Pace notes of the current track, shown as you drive.",
    "pedal": "Throttle, brake & clutch inputs and force feedback.",
    "pit_lane_helper": "Pit lane help: speed limit, limiter and distances, shown near and in the pit lane.",
    "pit_stop_estimate": "Estimated pit stop duration, refill and pit occupancy (LMU).",
    "push_to_pass": "Push to pass charge and activation timer.",
    "race_notifications": "Short race messages: positions, penalties, fastest laps, flags.",
    "race_plan": "Next pit stop of your Race Calculator plan: lap, fuel, tyres.",
    "radar": "Cars around you seen from above, with overlap warnings.",
    "rake_angle": "Rake angle of the car from ride heights.",
    "relative": "Cars just ahead and behind you on track, with gaps.",
    "relative_finish_order": "Estimated finish order between the leader and you, with refuel needed.",
    "ride_height": "Ride height of each corner of the car, as bars.",
    "rivals": "Cars ahead and behind you in your class, by standings.",
    "roll_angle": "Front and rear roll angles of the car.",
    "rpm_led": "Shift lights by RPM.",
    "sectors": "Sector times against your best and the session best.",
    "session": "Session name and time left, system clock and estimated laps.",
    "slip_angle": "Slip angle of each tyre, as bars.",
    "slip_ratio": "Slip ratio of each tyre, as bars.",
    "speed_delta": "Speed difference to reference laps at the same point of the lap.",
    "speedometer": "Speed, with recent minimum & maximum and fastest speed.",
    "spotter": "Side bars lit while a car is alongside.",
    "standings": "Race standings of every car, by class.",
    "steering_angle": "Steering and wheel angles, steering ratio and turning radius.",
    "steering_meter": "Steering input as a bar from center.",
    "steering_wheel": "Steering wheel turning with your inputs.",
    "stint_history": "Past stints: laps, time, fuel, tyre wear and consistency.",
    "stint_timer": "Stint time and driving time of each driver, for endurance races.",
    "suspension_force": "Suspension force of each corner and front & rear ratio.",
    "suspension_position": "Suspension position of each corner, as bars.",
    "suspension_travel": "Suspension travel used: bump, rebound and live position.",
    "system_performance": "CPU and memory use of the computer and of the app.",
    "telemetry_compare": "Live speed, pedals & steering against your reference lap.",
    "timing": "Lap times: current, last, best, session best and estimated.",
    "track_clock": "Track time of day, time scale and sunlight phase.",
    "track_map": "Track map with every car on it.",
    "track_notes": "Track notes of the current track, shown as you drive.",
    "traffic": "Nearest traffic: slower cars ahead and faster cars catching you.",
    "trailing": "Pedals, steering and force feedback drawn over the last seconds.",
    "tyre_carcass": "Tyre carcass temperature of each tyre.",
    "tyre_deflection": "Vertical deflection of each tyre, as bars.",
    "tyre_inner_layer": "Inner layer temperature of each tyre.",
    "tyre_load": "Load on each tyre and its share.",
    "tyre_overview": "Every tyre reading in one card per tyre: temperatures, pressure, wear.",
    "tyre_pressure": "Pressure of each tyre and compound.",
    "tyre_temp_trend": "Surface temperature trend of each tyre, as small charts.",
    "tyre_temperature": "Surface temperature of each tyre, colored by heatmap.",
    "tyre_wear": "Tyre tread left, wear per lap and laps left.",
    "virtual_energy": "Virtual energy left, use per lap, laps left and refill needed.",
    "weather": "Track & air temperatures, rain, wetness and wind.",
    "weather_forecast": "Weather forecast of the session: rain chance and temperatures.",
    "weight_distribution": "Weight distribution: front to rear, left to right and cross weight.",
    "wheel_camber": "Camber angle of each wheel.",
    "black_box": "All-in-one HUD: tyre & brake temperatures, lock & spin, ABS, TC, bias, pedals.",
    "wheel_dimension": "Front and rear tyre radius measured while driving.",
    "wheel_toe": "Toe angle of each wheel.",
    "wind_direction": "Wind direction and speed relative to your car.",
})
