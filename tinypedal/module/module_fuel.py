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
Fuel module

Consumption per lap estimate: last valid lap (default), or median of the last valid green flag
laps (option): laps under full course yellow or safety car, pit in & out laps and invalid laps
(lap time or track limits) left out, last valid lap used until enough green flag laps are driven.
Game estimate until a lap of car & track is recorded.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from math import ceil
from statistics import median

from .. import calculation as calc
from .. import realtime_state
from ..api_control import api
from ..const_api import API_RF2_NAME
from ..const_common import DELTA_DEFAULT, DELTA_ZERO, FLOAT_INF
from ..const_file import FileExt
from ..module_info import FuelInfo, minfo
from ..userfile.fuel_delta import load_fuel_delta_file, save_fuel_delta_file
from ..validator import generator_init, valid_delta_raw
from ._base import MODULE_STOP, DataModule, round6

# Consumption estimate method in use (FuelInfo.consumptionMethod)
METHOD_GAME = "game"  # game estimate, no lap of car & track recorded yet
METHOD_LAST_LAP = "last_lap"  # last valid lap
METHOD_MEDIAN = "median"  # median of last valid green flag laps
MEDIAN_MIN_LAPS = 3  # green flag laps needed before median replaces last valid lap


class Realtime(DataModule):
    """Fuel usage data"""

    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        _event_wait = self._event.wait
        reset = False
        vehicle_resets = None
        update_interval = self.idle_interval
        green_flag_laps = (
            max(self.mcfg["number_of_green_flag_laps"], 1)
            if self.mcfg["enable_green_flag_consumption"] else 0
        )

        gen_fuel_usage = calc_consumption(
            output=minfo.fuel,
            is_energy=False,
            filepath=self.cfg.path.fuel_delta,
            extension=FileExt.FUEL,
            min_delta_distance=self.mcfg["minimum_delta_distance"],
            fuel_density=max(self.mcfg["fuel_density"], 0.0),
            green_flag_laps=green_flag_laps,
        )
        gen_energy_usage = calc_consumption(
            output=minfo.energy,
            is_energy=True,
            filepath=self.cfg.path.energy_delta,
            extension=FileExt.ENERGY,
            min_delta_distance=self.mcfg["minimum_delta_distance"],
            fuel_density=0.0,
            green_flag_laps=green_flag_laps,
        )

        while not _event_wait(update_interval):
            if realtime_state.active or vehicle_resets != realtime_state.resets:
                vehicle_resets = realtime_state.resets

                if not reset:
                    reset = True
                    update_interval = self.active_interval

                # Calculate fuel
                gen_fuel_usage.send(vehicle_resets)

                # Calculate virtual energy if available
                minfo.energy.available = (api.read.engine.virtual_energy() != 0)
                if minfo.energy.available:
                    gen_energy_usage.send(vehicle_resets)

                    # Update hybrid info
                    minfo.hybrid.fuelEnergyRatio = calc.fuel_to_energy_ratio(
                        minfo.fuel.estimatedConsumption,
                        minfo.energy.estimatedConsumption,
                    )
                    minfo.hybrid.fuelEnergyBias = (
                        minfo.fuel.estimatedLaps - minfo.energy.estimatedLaps
                    )

            else:
                if reset:
                    reset = False
                    update_interval = self.idle_interval

        self.save_on_stop(gen_fuel_usage, gen_energy_usage)


def detect_consumption_type(is_energy: bool) -> Callable:
    """Detect consumption type, return telemetry function"""
    if is_energy:
        return telemetry_energy
    # Pure electric based vehicle
    if (
        api.name == API_RF2_NAME
        and api.read.emotor.battery_charge() > 0
        and (api.read.engine.tank_capacity() == 1 or api.read.engine.tank_capacity() == 0)
    ):
        return telemetry_battery
    # Fuel based vehicle
    return telemetry_fuel


def telemetry_fuel() -> tuple[float, float]:
    """Telemetry fuel"""
    return max(api.read.engine.tank_capacity(), 0.01), api.read.engine.fuel()


def telemetry_battery() -> tuple[float, float]:
    """Telemetry battery, capacity is always 100%"""
    return 100.0, api.read.emotor.battery_charge() * 100


def telemetry_energy() -> tuple[float, float]:
    """Telemetry energy, output in percentage"""
    return 100.0, api.read.engine.virtual_energy() * 100


def expected_fuel() -> float:
    """Fuel consumption per lap estimated by game (liters)"""
    return api.read.engine.expected_fuel_consumption()


def expected_energy() -> float:
    """Energy consumption per lap estimated by game (percent)"""
    return api.read.engine.expected_energy_consumption()


def under_full_course_yellow() -> bool:
    """Full course yellow or safety car: taken at the line, or yellow flag state of session"""
    return api.read.vehicle.under_yellow() or api.read.session.yellow_flag_state() > 0


def green_flag_median(laps: deque[float], minimum: int) -> float:
    """Median consumption of green flag laps, 0 while fewer than minimum laps"""
    if len(laps) < max(minimum, 1):
        return 0.0
    return median(laps)


@generator_init
def calc_consumption(
    output: FuelInfo,
    is_energy: bool,
    filepath: str,
    extension: str,
    min_delta_distance: float,
    fuel_density: float,
    green_flag_laps: int = 0,
):
    """Calculate consumption data

    Args:
        green_flag_laps: estimate from median of this many last valid green flag laps, 0 = from
            last valid lap (laps under yellow & invalid laps count as valid then).
    """
    last_reset = None  # reset check
    delayed_save = False

    combo_name = ""
    delta_array_last: tuple[tuple[float, ...], ...] = ()
    used_last_valid = 0.0
    laptime_pace = 0.0
    use_median = green_flag_laps > 0
    median_min_laps = min(MEDIAN_MIN_LAPS, max(green_flag_laps, 1))
    green_laps: deque[float] = deque(maxlen=max(green_flag_laps, 1))  # kept over resets of same car & track
    green_combo = ""

    while True:
        reset = yield None

        # Reset
        if last_reset != reset:
            # Save data
            if delayed_save:
                save_fuel_delta_file(
                    filepath=filepath,
                    filename=combo_name,
                    extension=extension,
                    dataset=delta_array_last,
                )
                delayed_save = False

            # Delay reset until driving (module stopping: data saved only)
            if reset is MODULE_STOP or not realtime_state.active:
                continue
            last_reset = reset

            # Load data
            output.reset()
            recording = False
            delayed_save = False
            validating = 0.0
            is_pit_lap = 0  # whether pit in or pit out lap
            is_yellow_lap = False  # lap under full course yellow or safety car (median only)
            is_invalid_lap = False  # lap invalidated by game, track limits (median only)

            telemetry_func = detect_consumption_type(is_energy)
            expected_func = expected_energy if is_energy else expected_fuel  # until a lap is recorded
            combo_name = api.read.session.combo_name()
            if green_combo != combo_name:
                green_combo = combo_name
                green_laps.clear()

            delta_array_last, used_last_valid, laptime_pace = load_fuel_delta_file(
                filepath=filepath,
                filename=combo_name,
                extension=extension,
                defaults=(DELTA_DEFAULT, 0.0, 0.0)
            )
            delta_array_raw: list[tuple[float, ...]] = [DELTA_ZERO]  # distance, fuel used, laptime
            delta_array_temp: tuple[tuple[float, ...], ...] = DELTA_DEFAULT  # last lap temp
            delta_fuel = 0.0  # delta fuel consumption compare to last lap

            amount_start = -FLOAT_INF  # start fuel reading
            amount_last = 0.0  # last fuel reading
            amount_need_abs = 0.0  # total fuel (absolute) need to finish race
            amount_need_rel = 0.0  # total additional fuel (relative) need to finish race
            amount_end = 0.0  # amount fuel left at the end of stint before pitting
            used_curr = 0.0  # current lap fuel consumption
            used_last_raw = used_last_valid  # raw usage
            used_est = 0.0  # estimated fuel consumption, for calculation only
            est_runlaps = 0.0  # estimate laps current fuel can last
            est_runmins = 0.0  # estimate minutes current fuel can last
            est_empty = 0.0  # estimate empty capacity at end of current lap
            est_pits_late = 0.0  # estimate end-stint pit stop counts
            est_pits_early = 0.0  # estimate end-lap pit stop counts
            used_est_less = 0.0  # estimate fuel consumption for one less pit stop

            last_elapsed_time = 0.0
            last_lap_stime = FLOAT_INF  # last lap start time
            laps_left = 0.0  # amount laps left at current lap distance
            end_timer_laps_left = 0.0  # amount laps left from start of current lap to end of race timer
            pos_recorded = 0.0  # last recorded vehicle position
            pos_last = 0.0  # last checked vehicle position
            pos_synced_last = 0.0  # estimated vehicle position

        # Read telemetry
        capacity, amount_curr = telemetry_func()
        lap_stime = api.read.timing.start()
        elapsed_time = api.read.timing.elapsed()
        laptime_curr = api.read.timing.current_laptime()
        time_left = api.read.session.remaining()
        in_garage = api.read.vehicle.in_garage()
        pos_curr = api.read.lap.distance()
        laps_done = api.read.lap.completed_laps()
        lap_into = api.read.lap.progress()
        is_pit_lap |= api.read.vehicle.in_pits()
        laptime_pace = minfo.delta.lapTimePace
        pos_synced = minfo.delta.lapDistance

        # Realtime fuel consumption
        if amount_start < amount_curr:
            amount_start = amount_last = amount_curr

        amount_diff = amount_last - amount_curr

        if amount_last < amount_curr:
            if api.read.vehicle.speed() > 1:  # regen check
                used_curr += amount_diff
            else:  # pitstop refilling check
                amount_start = amount_curr
            amount_last = amount_curr
        elif amount_last > amount_curr:
            used_curr += amount_diff
            amount_last = amount_curr

        if last_elapsed_time != elapsed_time:
            time_diff = elapsed_time - last_elapsed_time
            last_elapsed_time = elapsed_time
            if time_diff > 0:
                output.rateOfConsumption = amount_diff / time_diff

        # Lap start & finish detection
        if lap_stime > last_lap_stime:
            # Median: laps under yellow & invalid laps never become reference lap
            green_lap = not (is_yellow_lap or is_invalid_lap)
            if not is_pit_lap and green_lap and valid_delta_raw(delta_array_raw, used_curr, 1):
                delta_array_raw.append((  # set end value
                    round6(pos_last + 10),
                    round6(used_curr),
                    round6(lap_stime - last_lap_stime)
                ))
                delta_array_temp = tuple(delta_array_raw)
                validating = elapsed_time
            delta_array_raw[:] = DELTA_DEFAULT
            pos_last = pos_recorded = pos_curr
            used_last_raw = used_curr
            used_curr = 0
            recording = laptime_curr < 1
            is_pit_lap = 0
            is_yellow_lap = is_invalid_lap = False
        last_lap_stime = lap_stime  # reset

        # Yellow & track limits of lap in progress (yellow taken at the line counts for new lap),
        # track limits read once lap is under way (flag of lap just completed may stay a moment)
        if use_median:
            is_yellow_lap |= under_full_course_yellow()
            if laptime_curr > 1:
                is_invalid_lap |= api.read.lap.invalidated()

        # Distance desync check at start of new lap, reset if higher than normal distance
        if 0 < laptime_curr < 1 and pos_curr > 300:
            pos_last = pos_recorded = pos_curr = 0

        # Update if position value is different & positive
        if 0 <= pos_curr != pos_last:
            if recording and pos_curr - pos_recorded >= min_delta_distance:
                delta_array_raw.append((round6(pos_curr), round6(used_curr)))
                pos_recorded = pos_curr
            pos_last = pos_curr  # reset last position

        # Validating 1s after passing finish line
        if validating:
            timer = elapsed_time - validating
            if timer > 3:  # switch off after 3s
                validating = 0
            elif (timer > 0.3 and  # compare current time
                api.read.timing.last_laptime() > 0):  # is valid laptime
                used_last_valid = used_last_raw
                delta_array_last = delta_array_temp
                delta_array_temp = DELTA_DEFAULT
                delayed_save = True
                validating = 0
                if use_median:  # only green flag laps are validated with median
                    green_laps.append(used_last_raw)

        # Calc delta
        if pos_synced_last != pos_synced:
            pos_synced_last = pos_synced
            # Update delta
            delta_fuel = calc.delta_telemetry(
                delta_array_last,
                pos_synced,
                used_curr,
                laptime_curr > 0.3 and not in_garage,  # 300ms delay
            )

        # Median of green flag laps, else last valid lap, else game estimate (no lap of car &
        # track recorded yet, no delta)
        used_median = green_flag_median(green_laps, median_min_laps) if use_median else 0.0
        if used_median > 0:
            used_ref, method = used_median, METHOD_MEDIAN
        elif used_last_valid > 0:
            used_ref, method = used_last_valid, METHOD_LAST_LAP
        else:
            used_ref, method = max(expected_func(), 0.0), METHOD_GAME

        # Exclude first lap & pit in/out lap (& lap under yellow: slower, using less)
        used_est = calc.end_lap_consumption(
            used_ref, delta_fuel, 0 == is_pit_lap < laps_done and not is_yellow_lap)

        # Total refuel = laps left * last consumption - remaining fuel
        if api.read.session.finish_type(minfo.vehicles.finishAsLap):  # lap-type
            full_laps_left = calc.lap_type_full_laps_remain(
                api.read.lap.maximum(), laps_done)
            laps_left = calc.lap_type_laps_remain(
                full_laps_left, lap_into)
        elif laptime_pace > 0:  # time-type race
            time_left -= minfo.vehicles.finishTimeOffset
            end_timer_laps_left = calc.end_timer_laps_remain(
                lap_into, laptime_pace, time_left)
            # Leader finishing first: lap driven after timer ends (as the strategy plans it)
            full_laps_left = max(ceil(end_timer_laps_left) + round(minfo.vehicles.finishLapOffsetLeader), 0)
            laps_left = calc.time_type_laps_remain(
                full_laps_left, lap_into)

        amount_need_abs = laps_left * used_est

        amount_need_rel = amount_need_abs - amount_curr

        amount_end = calc.end_stint_fuel(
            amount_curr, used_curr, used_est)

        est_runlaps = calc.end_stint_laps(
            amount_curr, used_est)

        est_runmins = calc.end_stint_minutes(
            est_runlaps, laptime_pace)

        est_empty = calc.end_lap_empty_capacity(
            capacity, amount_curr + used_curr, used_ref + delta_fuel)

        est_pits_late = calc.end_stint_pit_counts(
            amount_need_rel, capacity - amount_end)

        est_pits_early = calc.end_lap_pit_counts(
            amount_need_rel, est_empty, capacity - amount_end)

        used_est_less = calc.one_less_pit_stop_consumption(
            est_pits_late, capacity, amount_curr, laps_left)

        output.capacity = capacity
        output.amountStart = amount_start
        output.amountCurrent = amount_curr
        output.amountUsedCurrent = used_curr
        output.amountEndStint = amount_end
        output.neededRelative = amount_need_rel
        output.neededAbsolute = amount_need_abs
        output.lastLapConsumption = used_last_raw
        output.estimatedConsumption = used_ref + delta_fuel
        output.estimatedValidConsumption = used_est
        output.estimatedLaps = est_runlaps
        output.estimatedMinutes = est_runmins
        output.estimatedNumPitStopsEnd = est_pits_late
        output.estimatedNumPitStopsEarly = est_pits_early
        output.deltaConsumption = delta_fuel
        output.oneLessPitConsumption = used_est_less
        output.consumptionMethod = method
        output.consumptionLaps = len(green_laps) if method == METHOD_MEDIAN else 0
        if not is_energy:
            output.weight = fuel_density * amount_curr
