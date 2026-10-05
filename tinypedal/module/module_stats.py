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
Stats module
"""

from __future__ import annotations

from time import localtime, strftime, time

from .. import calculation as calc
from .. import realtime_state
from ..api_control import api
from ..const_common import FLOAT_INF
from ..module_info import StatsInfo, minfo
from ..userfile.brands import select_brand_name
from ..userfile.car_setup import (
    rename_car_setup_file,
    save_car_setup_file,
    set_car_setup_filename,
    set_car_setup_laptime,
)
from ..userfile.driver_history import append_record, session_record, worth_recording
from ..userfile.driver_stats import DriverStats, load_driver_stats, save_driver_stats
from ..validator import generator_init
from ._base import MODULE_STOP, DataModule


class Realtime(DataModule):
    """Delta time data"""

    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        _event_wait = self._event.wait
        reset = False
        vehicle_resets = None
        update_interval = self.idle_interval

        gen_auto_backup_car_setup = auto_backup_car_setup(
            filepath=self.cfg.path.car_setups,
        )
        gen_record_driver_stats = record_driver_stats(
            output=minfo.stats,
            filepath=self.cfg.path.config,
            vehicle_classification=self.mcfg["vehicle_classification"],
            max_moved_distance=1500 * update_interval,
            podium_by_class=self.mcfg["enable_podium_by_class"]
        )

        while not _event_wait(update_interval):

            # Ignore stats while in spectate or override mode
            if not realtime_state.singleton or realtime_state.spectating or realtime_state.overriding:
                if reset:
                    reset = False  # make sure stats not saved
                    update_interval = self.idle_interval
                continue

            if realtime_state.active or vehicle_resets != realtime_state.resets:
                vehicle_resets = realtime_state.resets

                if not reset:
                    reset = True
                    update_interval = self.active_interval

                gen_record_driver_stats.send(vehicle_resets)

                if self.cfg.telemetry["enable_auto_backup_car_setup"]:
                    gen_auto_backup_car_setup.send(vehicle_resets)

            else:
                if reset:
                    reset = False
                    update_interval = self.idle_interval

        self.save_on_stop(gen_record_driver_stats, gen_auto_backup_car_setup)


def stats_keys(vehicle_classification: str) -> tuple[str, str]:
    """Stats key names"""
    if vehicle_classification == "Class":
        name = api.read.vehicle.class_name()
    elif vehicle_classification == "Class - Brand":
        brand_name = select_brand_name(vehicle_name=api.read.vehicle.vehicle_name())
        class_name = api.read.vehicle.class_name()
        if brand_name:
            name = f"{class_name} - {brand_name}"
        else:  # fallback to class name
            name = class_name
    else:
        name = api.read.vehicle.vehicle_name()
    return api.read.session.track_name(), name


def finish_position(podium_by_class: bool) -> int:
    """Get finish position"""
    # Overall position
    plr_place = api.read.vehicle.place()
    if not podium_by_class:
        return plr_place
    # Position in class
    veh_total = api.read.vehicle.total_vehicles()
    plr_class = api.read.vehicle.class_name()
    total_class_vehicle = 0
    place_higher = 0
    for index in range(veh_total):
        if api.read.vehicle.class_name(index) == plr_class:
            total_class_vehicle += 1
            if api.read.vehicle.place(index) > plr_place:
                place_higher += 1
    return total_class_vehicle - place_higher


@generator_init
def record_driver_stats(
    output: StatsInfo,
    filepath: str,
    vehicle_classification: str,
    max_moved_distance: float,
    podium_by_class: bool,
):
    """Record driver stats, and history record of each stint (track, vehicle, session, best lap, result)"""
    last_reset = None  # reset check
    delayed_save = False

    default_stats = DriverStats()
    driver_stats = DriverStats()
    loaded_stats = default_stats
    key_list = ("", "")
    vehicle_class = ""
    session_type = 0
    finish_place = 0
    finish_state = 0

    while True:
        reset = yield None

        # Reset
        if last_reset != reset:
            # Save data (keys of stint start: track & vehicle may already be the next ones)
            if delayed_save:
                save_driver_stats(
                    key_list=key_list,
                    stats_update=driver_stats,
                    filepath=filepath,
                )
                if all(key_list) and worth_recording(driver_stats.valid, driver_stats.invalid, driver_stats.seconds):
                    append_record(filepath, session_record(
                        track=key_list[0], vehicle=key_list[1], session=session_type,
                        best=driver_stats.pb, valid=driver_stats.valid, invalid=driver_stats.invalid,
                        meters=driver_stats.meters, seconds=driver_stats.seconds,
                        position=finish_place, finish=finish_state, time=time(), vehicle_class=vehicle_class,
                    ))
                delayed_save = False

            # Delay reset until driving (module stopping: data saved only)
            if reset is MODULE_STOP or not realtime_state.active:
                continue
            last_reset = reset

            # Load driver stats
            driver_stats = DriverStats()
            key_list = stats_keys(vehicle_classification)
            vehicle_class = api.read.vehicle.class_name()
            loaded_stats = load_driver_stats(
                key_list=key_list,
                filepath=filepath,
            )
            delayed_save = True

            is_pit_lap = 0
            last_lap_stime = FLOAT_INF
            last_lap_etime = FLOAT_INF
            last_best_laptime = FLOAT_INF
            last_raw_laptime = FLOAT_INF
            last_num_penalties = 99999
            fuel_last = 0.0
            last_finish_state = 99999
            gps_last = (FLOAT_INF, FLOAT_INF, FLOAT_INF)
            race_started = False
            finish_place = 0
            finish_state = 0

        # General
        lap_stime = api.read.timing.start()
        lap_etime = api.read.timing.elapsed()
        is_pit_lap |= api.read.vehicle.in_pits()
        session_type = api.read.session.session_type()

        # Best lap time
        last_valid_laptime = api.read.timing.last_laptime()
        if (last_best_laptime > last_valid_laptime > 1 and
            abs(last_valid_laptime - last_raw_laptime) < 0.001):  # validate lap time
            last_best_laptime = last_valid_laptime
            # Personal best (any session)
            if driver_stats.pb > last_valid_laptime:
                driver_stats.pb = last_valid_laptime
            # Qualifying best
            if session_type == 2:
                if driver_stats.qb > last_valid_laptime:
                    driver_stats.qb = last_valid_laptime
            # Race best
            elif session_type == 4 and driver_stats.rb > last_valid_laptime:
                driver_stats.rb = last_valid_laptime

        # Driven distance
        gps_curr = api.read.vehicle.position_xyz()
        if gps_last != gps_curr:
            moved_distance = calc.distance(gps_last, gps_curr)
            if moved_distance < max_moved_distance:
                driver_stats.meters += moved_distance
            gps_last = gps_curr

        # Laps complete
        if last_lap_stime > lap_stime:
            last_lap_stime = lap_stime
        elif last_lap_stime < lap_stime and lap_etime - lap_stime > 2:
            last_raw_laptime = lap_stime - last_lap_stime
            if last_valid_laptime > 0: # valid lap check
                driver_stats.valid += 1  # 1 lap at a time
            elif not is_pit_lap:  # only count non-pit invalid lap
                driver_stats.invalid += 1
            is_pit_lap = 0
            last_lap_stime = lap_stime

        # Seconds spent
        if last_lap_etime > lap_etime:
            last_lap_etime = lap_etime
        elif last_lap_etime < lap_etime:
            if api.read.vehicle.speed() > 1:  # while speed > 1m/s
                driver_stats.seconds += lap_etime - last_lap_etime
            last_lap_etime = lap_etime

        # Fuel consumed (liter)
        fuel_curr = api.read.engine.fuel()
        if fuel_last < fuel_curr:
            fuel_last = fuel_curr
        elif fuel_last > fuel_curr:
            driver_stats.liters += fuel_last - fuel_curr
            fuel_last = fuel_curr

        # Race session stats
        if session_type == 4:
            # Race start: once per stint, after green flag
            if not race_started and not api.read.session.pre_race():
                race_started = True
                driver_stats.starts += 1

            # Penalties
            num_penalties = api.read.vehicle.number_penalties()
            if last_num_penalties > num_penalties:
                last_num_penalties = num_penalties
            elif last_num_penalties < num_penalties:
                driver_stats.penalties += num_penalties - last_num_penalties
                last_num_penalties = num_penalties

            # Finish place
            curr_finish_state = api.read.vehicle.finish_state()
            if last_finish_state > curr_finish_state:
                last_finish_state = curr_finish_state
            elif 0 == last_finish_state < curr_finish_state:
                last_finish_state = finish_state = curr_finish_state
                if curr_finish_state == 1:  # finished
                    driver_stats.races += 1
                    finish_place = finish_position(podium_by_class)
                    if finish_place > 0:
                        driver_stats.positions += finish_place
                        driver_stats.placed += 1
                    if finish_place == 1:
                        driver_stats.wins += 1
                    if finish_place <= 3:
                        driver_stats.podiums += 1
                elif curr_finish_state in (2, 3):  # DNF, DQ
                    driver_stats.dnf += 1

        # Output stats data
        output.metersDriven = driver_stats.meters + loaded_stats.meters


@generator_init
def auto_backup_car_setup(filepath: str):
    """Auto backup car setup"""
    last_reset = None  # reset check
    data_available = False

    best_laptime = FLOAT_INF
    temp_data: tuple = ()
    data_hash = 0
    last_data_hash = 0
    temp_filename = ""

    while True:
        reset = yield None

        # Reset
        if last_reset != reset:
            # Save data
            if data_available:
                # Rename temporary file with additional info after back to garage
                if temp_filename:
                    rename_car_setup_file(
                        filepath=filepath,
                        old_filename=temp_filename,
                        new_filename=f"{temp_filename} - {set_car_setup_laptime(best_laptime)}",
                    )
                data_available = False

            # Delay reset until driving (module stopping: data saved only)
            if reset is MODULE_STOP or not realtime_state.active:
                continue
            last_reset = reset

            best_laptime = FLOAT_INF
            temp_filename = ""

        # Get setup data while not in pits
        if not api.read.vehicle.in_pits():
            # Stint best time
            if data_available:
                last_valid_laptime = api.read.timing.last_laptime()
                if 0 < last_valid_laptime < best_laptime:
                    best_laptime = last_valid_laptime
            else:
                temp_data = api.read.vehicle.setup()
                if temp_data:
                    data_available = True
                    data_hash = hash(temp_data)
                    # Save temporary file first
                    if last_data_hash != data_hash:
                        temp_filename = set_car_setup_filename(
                            api.alias,
                            strftime("%Y-%m-%d %H-%M-%S", localtime()),
                            api.read.session.track_name(),
                            api.read.vehicle.class_name(),
                            select_brand_name(vehicle_name=api.read.vehicle.vehicle_name()),
                        )
                        save_car_setup_file(
                            filepath=filepath,
                            filename=temp_filename,
                            dataset=temp_data,
                        )
                    # Reset
                    temp_data = ()
                    last_data_hash = data_hash
