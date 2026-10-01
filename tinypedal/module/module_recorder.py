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
    <telemetry path>/<track - class>/<date time> lap<number> <lap time>[ invalid].csv[.gz]
First line is lap info ("# " + json), see userfile/telemetry_lap.py.

Also records replay files automatically while driving (optional), see replay_session.py.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from typing import NamedTuple

from .. import app_signal, realtime_state
from ..api_control import api
from ..const_app import VERSION
from ..module_info import minfo
from ..replay import replay
from ..userfile import write_text_file
from ..userfile.telemetry_lap import INFO_PREFIX, best_laps, lap_bounds, lap_files
from ..validator import generator_init
from ._base import DataModule

logger = logging.getLogger(__name__)

WHEELS = ("fl", "fr", "rl", "rr")
CSV_HEADER = (
    "time", "lap_time", "distance", "speed_kph",
    "throttle", "brake", "clutch", "steering",
    "gear", "rpm", "fuel",
    "tyre_temp_fl", "tyre_temp_fr", "tyre_temp_rl", "tyre_temp_rr",
    "tyre_pres_fl", "tyre_pres_fr", "tyre_pres_rl", "tyre_pres_rr",
    "pos_x", "pos_y",
    # Added columns (older files stop at pos_y)
    "pos_z", "accel_lat", "accel_long", "sector", "tc_active", "abs_active", "battery",
    *(f"brake_temp_{wheel}" for wheel in WHEELS),
    *(f"tyre_wear_{wheel}" for wheel in WHEELS),
    *(f"wheel_speed_{wheel}" for wheel in WHEELS),
    *(f"ride_height_{wheel}" for wheel in WHEELS),
    *(f"susp_defl_{wheel}" for wheel in WHEELS),
)
GRAVITY = 9.80665
NO_WHEELS = (0.0, 0.0, 0.0, 0.0)
SESSION_NAMES = ("Test day", "Practice", "Qualify", "Warmup", "Race")
LAP_KIND = "lap"
OUT_LAP_KIND = "out"
IN_LAP_KIND = "in"


class Realtime(DataModule):
    """Telemetry recorder"""

    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        from ..replay_session import AutoReplay

        _event_wait = self._event.wait
        mcfg = self.mcfg
        reset = False
        vehicle_resets = None
        update_interval = self.idle_interval

        record_laps = mcfg["enable_lap_recording"]
        record_during_replay = mcfg["enable_lap_recording_during_replay"]
        gen_recorder = record_telemetry(
            saver=save_lap_background,
            filepath=self.cfg.path.telemetry,
            min_lap_fraction=min(max(mcfg["minimum_lap_distance_percentage"], 0), 100) / 100,
            max_saved_laps=max(int(mcfg["number_of_saved_laps_per_track"]), 1),
            save_invalid=mcfg["save_invalid_laps"],
            keep_best=max(int(mcfg["number_of_best_laps_kept_per_track"]), 0),
            save_out_in=mcfg["enable_out_and_in_lap_recording"],
            compress=mcfg["enable_compressed_lap_files"],
            timestamp=lap_timestamp,
        )
        auto_replay = (
            AutoReplay(int(mcfg["number_of_saved_replays"]))
            if mcfg["enable_auto_replay_recording"] else None
        )

        while not _event_wait(update_interval):
            active = realtime_state.active
            if auto_replay is not None:
                auto_replay.update(bool(active), time.monotonic())
            if replay.active and not record_during_replay:
                active = False  # replayed laps are already recorded
            if active and record_laps:
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

        if auto_replay is not None:
            auto_replay.stop()


LAP_SAVER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Lap saver")


def save_lap_background(pending: PendingLap, options: SaveOptions, valid: bool):
    """Save lap in background, so sampling of next lap is not paused while writing file"""
    LAP_SAVER.submit(pending.save, options, valid)


def save_lap_now(pending: PendingLap, options: SaveOptions, valid: bool):
    """Save lap in current thread"""
    pending.save(options, valid)


def lap_timestamp() -> float:
    """Time of lap for file name, replay time while replaying"""
    player = replay.player
    if player is not None and player.replay.created > 0:
        return player.replay.created + player.position
    return time.time()


def four(values, digits: int, scale: float = 1.0) -> tuple:
    """First 4 wheel values rounded, zeros if unavailable"""
    try:
        return tuple(round(value * scale, digits) for value in values[:4]) if len(values) >= 4 else NO_WHEELS
    except TypeError:
        return NO_WHEELS


def read_sample(lap_start: float) -> tuple:
    """Read one telemetry sample"""
    read = api.read
    elapsed = read.timing.elapsed()
    radius = minfo.wheels.wheelRadius
    try:
        wheel_speed = tuple(
            round(abs(rotation) * wheel_radius * 3.6, 1)
            for rotation, wheel_radius in zip(read.wheel.rotation(), radius)
        ) if len(radius) >= 4 else NO_WHEELS
    except TypeError:
        wheel_speed = NO_WHEELS
    return (
        round(elapsed, 3),
        round(elapsed - lap_start, 3),
        round(read.lap.distance(), 2),
        round(read.vehicle.speed() * 3.6, 2),
        round(read.inputs.throttle_raw(), 3),  # pedal position, without throttle blip or cut on shifts
        round(read.inputs.brake_raw(), 3),
        round(read.inputs.clutch(), 3),
        round(read.inputs.steering(), 3),
        read.engine.gear(),
        round(read.engine.rpm()),
        round(read.engine.fuel(), 3),
        *four(read.tyre.surface_temperature_avg(), 1),
        *four(read.tyre.pressure(), 1),
        round(read.vehicle.position_longitudinal(), 2),
        round(read.vehicle.position_lateral(), 2),
        round(read.vehicle.position_vertical(), 2),
        round(read.vehicle.acceleration_lateral() / GRAVITY, 3),
        round(read.vehicle.acceleration_longitudinal() / GRAVITY, 3),
        read.lap.sector_index(),
        int(bool(read.switch.tc_active())),
        int(bool(read.switch.abs_active())),
        round(read.emotor.battery_charge() * 100, 1),
        *four(read.brake.temperature(), 1),
        *four(read.tyre.wear(), 2, 100),
        *wheel_speed,
        *four(read.wheel.ride_height(), 1),
        *four(read.wheel.suspension_deflection(), 1),
    )


def lap_info(kind: str, rows: list) -> dict:
    """Lap info (track, vehicle, session, weather), saved as first line of lap file"""
    read = api.read
    info: dict = {"kind": kind, "app_version": VERSION}
    try:
        session_type = read.session.session_type()
        info.update({
            "track": read.session.track_name(),
            "combo": read.session.combo_name(),
            "vehicle": read.vehicle.vehicle_name(),
            "class": read.vehicle.class_name(),
            "session": SESSION_NAMES[session_type] if 0 <= session_type < len(SESSION_NAMES) else "",
            "track_length": round(read.lap.track_length(), 1),
            "track_temperature": round(read.session.track_temperature(), 1),
            "ambient_temperature": round(read.session.ambient_temperature(), 1),
            "wetness": round(read.session.wetness_average(), 3),
        })
    except (AttributeError, TypeError, ValueError, IndexError):
        pass
    if rows:
        info["fuel_start"] = rows[0][10]
        info["fuel_end"] = rows[-1][10]
    if replay.player is not None:
        info["replay"] = os.path.basename(replay.player.replay.filename)
    return info


def official_sectors(lap_time: float) -> list[float]:
    """Sector times of last lap from game, empty if not matching lap time"""
    s1 = api.read.timing.last_sector1()
    s12 = api.read.timing.last_sector2()
    if not (0 < s1 < s12 < lap_time):
        return []
    return [s1, s12 - s1, lap_time - s12]


@generator_init
def record_telemetry(
    filepath: str,
    min_lap_fraction: float,
    max_saved_laps: int,
    save_invalid: bool = True,
    keep_best: int = 0,
    save_out_in: bool = False,
    compress: bool = False,
    timestamp: Callable[[], float] = time.time,
    saver: Callable[[PendingLap, SaveOptions, bool], None] = save_lap_now,
):
    """Record telemetry samples, save complete lap after crossing start line

    Lap is verified 1-10s after crossing start line (official last lap time must match
    recorded lap time, same as delta best), then saved, or marked "invalid".
    Send vehicle resets count to record sample, send None to discard current lap.
    Time going backward (replay looping or rewound) also discards current lap.
    """
    last_reset = None
    last_lap_start = None
    last_elapsed = float("-inf")
    lap_complete_start = False  # whether recording started from start line
    started_in_pits = False
    rows: list[tuple] = []
    pending: PendingLap | None = None  # completed lap waiting for validation
    options = SaveOptions(filepath, max_saved_laps, save_invalid, keep_best, compress)

    while True:
        reset = yield None

        elapsed = api.read.timing.elapsed() if reset is not None else last_elapsed
        rewound = elapsed < last_elapsed - 0.001
        if reset is None or reset != last_reset or rewound:  # discard incomplete lap
            if pending is not None:  # left track before validation delay: check lap time now
                save_pending(pending, options, saver, confirmed_lap(pending))
                pending = None
            last_reset = reset
            last_lap_start = None
            last_elapsed = float("-inf")
            lap_complete_start = False
            rows = []
            if reset is None:
                continue

        if elapsed == last_elapsed:
            continue  # game data not updated since last sample
        last_elapsed = elapsed

        # Validate pending lap
        if pending is not None:
            timer = elapsed - pending.finish_time
            last_laptime = api.read.timing.last_laptime()
            if timer > 1 and last_laptime > 0 and abs(last_laptime - pending.lap_time) < 0.001:
                save_pending(pending, options, saver, True)
                pending = None
            elif timer > 10:
                save_pending(pending, options, saver, False)
                pending = None

        in_pits = bool(api.read.vehicle.in_pits())
        lap_start = api.read.timing.start()
        if last_lap_start is None:
            last_lap_start = lap_start
            started_in_pits = in_pits
        elif lap_start > last_lap_start:  # crossed start line
            track_length = api.read.lap.track_length()
            distances = [row[2] for row in rows]
            first, last = lap_bounds(distances)  # without samples of previous lap distance
            max_distance = max(distances[first:last], default=0.0)
            kind = OUT_LAP_KIND if started_in_pits else IN_LAP_KIND if in_pits else LAP_KIND
            if (lap_complete_start and track_length > 0 and max_distance >= track_length * min_lap_fraction
                    and (save_out_in or kind == LAP_KIND)):
                if pending is not None:  # previous lap not verified in time
                    save_pending(pending, options, saver, False)
                pending = PendingLap(
                    combo_name=api.read.session.combo_name(),
                    lap_number=api.read.lap.completed_laps(),
                    lap_time=lap_start - last_lap_start,
                    finish_time=lap_start,
                    rows=rows,
                    info=lap_info(kind, rows),
                    timestamp=timestamp(),
                )
            rows = []
            lap_complete_start = True
            started_in_pits = in_pits
            last_lap_start = lap_start

        rows.append(read_sample(last_lap_start))


def confirmed_lap(pending: PendingLap) -> bool:
    """Whether game last lap time matches recorded lap time"""
    try:
        last_laptime = api.read.timing.last_laptime()
    except (AttributeError, TypeError):
        return False
    return last_laptime > 0 and abs(last_laptime - pending.lap_time) < 0.001


def save_pending(pending: PendingLap, options: SaveOptions, saver, valid: bool):
    """Add official sector times to valid lap, then save"""
    if valid:
        sectors = official_sectors(pending.lap_time)
        if sectors:
            pending.info["sectors"] = [round(value, 3) for value in sectors]
    saver(pending, options, valid)


class SaveOptions(NamedTuple):
    """Lap saving options"""

    filepath: str
    max_saved_laps: int
    save_invalid: bool = True
    keep_best: int = 0
    compress: bool = False


class PendingLap(NamedTuple):
    """Completed lap waiting for validation"""

    combo_name: str
    lap_number: int
    lap_time: float
    finish_time: float
    rows: list
    info: dict
    timestamp: float

    def save(self, options: SaveOptions, valid: bool):
        """Save lap if valid or invalid laps allowed"""
        if not valid and not options.save_invalid:
            logger.info("RECORDER: invalid lap %s not saved", self.lap_number)
            return
        save_lap(
            options.filepath, self.combo_name, self.lap_number, self.lap_time, self.rows,
            options.max_saved_laps, valid, info=self.info, keep_best=options.keep_best,
            compress=options.compress, timestamp=self.timestamp,
        )


def lap_filename(lap_number: int, lap_time: float, valid: bool = True, timestamp: float | None = None,
                 compress: bool = False) -> str:
    """Recorded lap file name"""
    minutes, seconds = divmod(lap_time, 60)
    suffix = "" if valid else " invalid"
    ext = ".csv.gz" if compress else ".csv"
    date = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(timestamp))
    return f"{date} lap{lap_number:03d} {int(minutes)}m{seconds:06.3f}s{suffix}{ext}"


def lap_text(rows: list, info: dict | None = None) -> str:
    """Lap file content"""
    buffer = io.StringIO()
    if info:
        buffer.write(INFO_PREFIX + json.dumps(info) + "\n")
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    writer.writerows(rows)
    return buffer.getvalue()


def write_gzip_file(filename: str, text: str) -> bool:
    """Write compressed text file atomically, returns True if saved"""
    temp_filename = f"{filename}.tmp"
    try:
        with gzip.open(temp_filename, "wb", compresslevel=6) as file:
            file.write(text.encode("utf-8"))
        os.replace(temp_filename, filename)
        return True
    except OSError as error:
        logger.error("RECORDER: failed saving %s: %s", filename, error)
        with suppress(OSError):
            os.remove(temp_filename)
        return False


def save_lap(
    filepath: str, combo_name: str, lap_number: int, lap_time: float, rows: list,
    max_saved_laps: int, valid: bool = True, info: dict | None = None, keep_best: int = 0,
    compress: bool = False, timestamp: float | None = None,
) -> bool:
    """Save lap telemetry to CSV, remove oldest files of same track over limit"""
    folder = os.path.join(filepath, combo_name or "unknown")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as error:
        logger.error("RECORDER: unable to create folder %s: %s", folder, error)
        app_signal.error.emit(f"Telemetry recorder: unable to create folder ({error.strerror}).")
        return False
    filename = lap_filename(lap_number, lap_time, valid, timestamp, compress)
    write = write_gzip_file if compress else write_text_file
    if not write(os.path.join(folder, filename), lap_text(rows, info)):
        app_signal.error.emit(f"Telemetry recorder: unable to save lap {lap_number}, see log for details.")
        return False
    logger.info("RECORDER: saved %s (%s samples)", filename, len(rows))
    remove_old_laps(folder, max_saved_laps, keep_best)
    return True


def remove_old_laps(folder: str, max_saved_laps: int, keep_best: int = 0):
    """Remove oldest recorded laps over limit (per track & class folder), fastest valid laps are kept"""
    try:
        laps = lap_files(folder)
        if len(laps) <= max_saved_laps:
            return
        protected = {lap.path for lap in best_laps(laps, keep_best)}
        laps.sort(key=lambda lap: os.path.getmtime(lap.path))
        excess = len(laps) - max_saved_laps
        for lap in laps:
            if excess <= 0:
                break
            if lap.path in protected:
                continue
            os.remove(lap.path)
            excess -= 1
    except OSError as error:
        logger.error("RECORDER: unable to remove old laps: %s", error)
