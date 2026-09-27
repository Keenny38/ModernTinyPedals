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
Telemetry recorder module

Record player telemetry of each complete lap to CSV file:
    <telemetry path>/<track - class>/<date time> lap<number> <lap time>[ invalid].csv
"""

from __future__ import annotations

import csv
import io
import logging
import os
from time import localtime, strftime
from typing import NamedTuple

from .. import app_signal, realtime_state
from ..api_control import api
from ..userfile import write_text_file
from ..validator import generator_init
from ._base import DataModule

logger = logging.getLogger(__name__)

CSV_HEADER = (
    "time", "lap_time", "distance", "speed_kph",
    "throttle", "brake", "clutch", "steering",
    "gear", "rpm", "fuel",
    "tyre_temp_fl", "tyre_temp_fr", "tyre_temp_rl", "tyre_temp_rr",
    "tyre_pres_fl", "tyre_pres_fr", "tyre_pres_rl", "tyre_pres_rr",
    "pos_x", "pos_y",
)


class Realtime(DataModule):
    """Telemetry recorder"""

    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        _event_wait = self._event.wait
        reset = False
        vehicle_resets = None
        update_interval = self.idle_interval

        gen_recorder = record_telemetry(
            filepath=self.cfg.path.telemetry,
            min_lap_fraction=min(max(self.mcfg["minimum_lap_distance_percentage"], 0), 100) / 100,
            max_saved_laps=max(int(self.mcfg["number_of_saved_laps_per_track"]), 1),
            save_invalid=self.mcfg["save_invalid_laps"],
        )

        while not _event_wait(update_interval):
            if realtime_state.active:
                if not reset:
                    reset = True
                    update_interval = self.active_interval
                if vehicle_resets != realtime_state.resets:
                    vehicle_resets = realtime_state.resets
                gen_recorder.send(vehicle_resets)
            else:
                if reset:
                    reset = False
                    update_interval = self.idle_interval
                    gen_recorder.send(None)  # discard incomplete lap


def read_sample(lap_start: float) -> tuple:
    """Read one telemetry sample"""
    elapsed = api.read.timing.elapsed()
    temps = api.read.tyre.surface_temperature_avg()
    pressures = api.read.tyre.pressure()
    return (
        round(elapsed, 3),
        round(elapsed - lap_start, 3),
        round(api.read.lap.distance(), 2),
        round(api.read.vehicle.speed() * 3.6, 2),
        round(api.read.inputs.throttle(), 3),
        round(api.read.inputs.brake(), 3),
        round(api.read.inputs.clutch(), 3),
        round(api.read.inputs.steering(), 3),
        api.read.engine.gear(),
        round(api.read.engine.rpm()),
        round(api.read.engine.fuel(), 3),
        *(round(value, 1) for value in temps[:4]),
        *(round(value, 1) for value in pressures[:4]),
        round(api.read.vehicle.position_longitudinal(), 2),
        round(api.read.vehicle.position_lateral(), 2),
    )


@generator_init
def record_telemetry(filepath: str, min_lap_fraction: float, max_saved_laps: int, save_invalid: bool = True):
    """Record telemetry samples, save complete lap after crossing start line

    Lap is verified 1-10s after crossing start line (official last lap time must match
    recorded lap time, same as delta best), then saved, or marked "invalid".
    Send vehicle resets count to record sample, send None to discard current lap.
    """
    last_reset = None
    last_lap_start = None
    lap_complete_start = False  # whether recording started from start line
    rows: list[tuple] = []
    pending: PendingLap | None = None  # completed lap waiting for validation

    while True:
        reset = yield None

        if reset is None or reset != last_reset:  # discard incomplete lap
            if pending is not None:  # session ended before validation
                pending.save(filepath, max_saved_laps, valid=False, save_invalid=save_invalid)
                pending = None
            last_reset = reset
            last_lap_start = None
            lap_complete_start = False
            rows = []
            if reset is None:
                continue

        # Validate pending lap
        if pending is not None:
            timer = api.read.timing.elapsed() - pending.finish_time
            last_laptime = api.read.timing.last_laptime()
            if timer > 1 and last_laptime > 0 and abs(last_laptime - pending.lap_time) < 0.001:
                pending.save(filepath, max_saved_laps, valid=True, save_invalid=save_invalid)
                pending = None
            elif timer > 10:
                pending.save(filepath, max_saved_laps, valid=False, save_invalid=save_invalid)
                pending = None

        lap_start = api.read.timing.start()
        if last_lap_start is None:
            last_lap_start = lap_start
        elif lap_start > last_lap_start:  # crossed start line
            track_length = api.read.lap.track_length()
            max_distance = max((row[2] for row in rows), default=0.0)
            if lap_complete_start and track_length > 0 and max_distance >= track_length * min_lap_fraction:
                if pending is not None:  # previous lap not verified in time
                    pending.save(filepath, max_saved_laps, valid=False, save_invalid=save_invalid)
                pending = PendingLap(
                    combo_name=api.read.session.combo_name(),
                    lap_number=api.read.lap.completed_laps(),
                    lap_time=lap_start - last_lap_start,
                    finish_time=lap_start,
                    rows=rows,
                )
            rows = []
            lap_complete_start = True
            last_lap_start = lap_start

        rows.append(read_sample(last_lap_start))


class PendingLap(NamedTuple):
    """Completed lap waiting for validation"""

    combo_name: str
    lap_number: int
    lap_time: float
    finish_time: float
    rows: list

    def save(self, filepath: str, max_saved_laps: int, valid: bool, save_invalid: bool):
        """Save lap if valid or invalid laps allowed"""
        if not valid and not save_invalid:
            logger.info("RECORDER: invalid lap %s not saved", self.lap_number)
            return
        save_lap(filepath, self.combo_name, self.lap_number, self.lap_time, self.rows, max_saved_laps, valid)


def lap_filename(lap_number: int, lap_time: float, valid: bool = True) -> str:
    """Recorded lap file name"""
    minutes, seconds = divmod(lap_time, 60)
    suffix = "" if valid else " invalid"
    return f"{strftime('%Y-%m-%d %H-%M-%S', localtime())} lap{lap_number:03d} {int(minutes)}m{seconds:06.3f}s{suffix}.csv"


def save_lap(
    filepath: str, combo_name: str, lap_number: int, lap_time: float, rows: list,
    max_saved_laps: int, valid: bool = True,
) -> bool:
    """Save lap telemetry to CSV, remove oldest files of same track over limit"""
    folder = os.path.join(filepath, combo_name or "unknown")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as error:
        logger.error("RECORDER: unable to create folder %s: %s", folder, error)
        app_signal.error.emit(f"Telemetry recorder: unable to create folder ({error.strerror}).")
        return False
    filename = lap_filename(lap_number, lap_time, valid)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    writer.writerows(rows)
    if not write_text_file(os.path.join(folder, filename), buffer.getvalue()):
        app_signal.error.emit(f"Telemetry recorder: unable to save lap {lap_number}, see log for details.")
        return False
    logger.info("RECORDER: saved %s (%s samples)", filename, len(rows))
    remove_old_laps(folder, max_saved_laps)
    return True


def remove_old_laps(folder: str, max_saved_laps: int):
    """Remove oldest recorded laps over limit (per track & class folder)"""
    try:
        files = [
            os.path.join(folder, name)
            for name in os.listdir(folder)
            if name.endswith(".csv")
        ]
        files.sort(key=os.path.getmtime)
        for old_file in files[:-max_saved_laps]:
            os.remove(old_file)
    except OSError as error:
        logger.error("RECORDER: unable to remove old laps: %s", error)
