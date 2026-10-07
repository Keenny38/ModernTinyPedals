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
MoTeC i2 log file (.ld) export of recorded laps, and reading of .ld files

Layout follows the community documented .ld format (see "ldparser" project):
header, event, venue, vehicle, then linked list of channel descriptors, then
channel data at a fixed rate per channel. Written as little endian float32, read as
float or integer (LMU & rF2 built-in loggers store scaled integers).
"""

from __future__ import annotations

import logging
import os
import struct
import time
from array import array
from bisect import bisect_right
from collections.abc import Collection, Sequence
from itertools import pairwise
from typing import NamedTuple

from .telemetry_lap import LapData, interpolate, lap_time_of, lap_timestamp_of

logger = logging.getLogger(__name__)

HEAD = struct.Struct(
    "<I4xII20xI24xHHHI8sHHI4x16s16x16s16x64s64s64x64s64x1024xI66x64s126x"
)
EVENT = struct.Struct("<64s64s1024sH")
VENUE = struct.Struct("<64s1034xH")
VEHICLE = struct.Struct("<64s128xI32s32s")
CHANNEL = struct.Struct("<IIIIHHHHhhhh32s8s12s40x")

WHEELS = ("fl", "fr", "rl", "rr")
LD_MARKER = 0x40
DTYPE_FLOAT = 0x07
DTYPE_INTEGERS = (0x00, 0x03, 0x05)  # scaled by shift, multiplier, scale & decimal places
DTYPE_SIZE_32 = 4

class ExportChannel(NamedTuple):
    """Recorder CSV column written as MoTeC channel: value * scale + offset"""

    column: str
    name: str
    short_name: str
    unit: str
    scale: float = 1.0
    offset: float = 0.0
    step: bool = False  # held between samples (gear, sector, on/off), never interpolated


def wheel_exports(column: str, name: str, short_name: str, unit: str, scale: float = 1.0,
                  offset: float = 0.0) -> tuple[ExportChannel, ...]:
    """Channel of each wheel ("{wheel}" in column & names replaced by wheel)"""
    return tuple(
        ExportChannel(column.format(wheel=wheel), name.format(wheel=wheel.upper()),
                      short_name.format(wheel=wheel.upper()), unit, scale, offset)
        for wheel in WHEELS
    )


# Recorder CSV columns, MoTeC channel names as LMU built-in logger names them where it logs the same value
CHANNEL_MAP = (
    ExportChannel("lap_time", "Lap Time", "LapT", "s"),
    ExportChannel("distance", "Lap Distance", "LapD", "m"),
    ExportChannel("speed_kph", "Ground Speed", "Spd", "km/h"),
    ExportChannel("throttle", "Throttle Pos", "Thr", "%", 100.0),
    ExportChannel("brake", "Brake Pos", "Brk", "%", 100.0),
    ExportChannel("clutch", "Clutch Pos", "Clu", "%", 100.0),
    ExportChannel("steering", "Steering Pos", "Str", "%", 100.0),
    ExportChannel("gear", "Gear", "Gear", "", step=True),
    ExportChannel("rpm", "Engine RPM", "RPM", "rpm"),
    ExportChannel("fuel", "Fuel Level", "Fuel", "l"),
    *wheel_exports("tyre_temp_{wheel}", "Tyre Temp {wheel}", "TT{wheel}", "C"),
    *wheel_exports("tyre_pres_{wheel}", "Tyre Pres {wheel}", "TP{wheel}", "kPa"),
    ExportChannel("pos_x", "Pos X", "PosX", "m"),
    ExportChannel("pos_y", "Pos Y", "PosY", "m"),
    ExportChannel("pos_z", "Pos Z", "PosZ", "m"),
    ExportChannel("accel_lat", "G Force Lat", "GLat", "G"),
    ExportChannel("accel_long", "G Force Long", "GLong", "G"),
    ExportChannel("sector", "Sector", "Sect", "", step=True),
    ExportChannel("tc_active", "TC Active", "TCAct", "", step=True),
    ExportChannel("abs_active", "ABS Active", "ABSAct", "", step=True),
    ExportChannel("battery", "Battery Charge", "Batt", "%"),
    *wheel_exports("brake_temp_{wheel}", "Brake Temp {wheel}", "BT{wheel}", "C"),
    # Worn percent, as LMU logs it (recorder: remaining percent)
    *wheel_exports("tyre_wear_{wheel}", "Tyre Wear {wheel}", "TW{wheel}", "%", -1.0, 100.0),
    *wheel_exports("wheel_speed_{wheel}", "Wheel Speed {wheel}", "WS{wheel}", "km/h"),
    *wheel_exports("ride_height_{wheel}", "Ride Height {wheel}", "RH{wheel}", "mm"),
    *wheel_exports("susp_defl_{wheel}", "Damper Pos {wheel}", "DP{wheel}", "mm"),
    *wheel_exports("tyre_temp_in_{wheel}", "Tyre Temp {wheel} Inner", "TTI{wheel}", "C"),
    *wheel_exports("tyre_temp_mid_{wheel}", "Tyre Temp {wheel} Centre", "TTC{wheel}", "C"),
    *wheel_exports("tyre_temp_out_{wheel}", "Tyre Temp {wheel} Outer", "TTO{wheel}", "C"),
    *wheel_exports("tyre_load_{wheel}", "Tyre Load {wheel}", "TL{wheel}", "N", 1000.0),  # kN to N
    ExportChannel("path_lateral", "Path Lateral", "PathL", "m"),
    ExportChannel("track_edge", "Track Edge", "TrkEdge", "m"),
    ExportChannel("brake_bias", "Brake Bias Rear", "BBRear", "%", -1.0, 100.0),  # recorder: front percent
    ExportChannel("water_temp", "Eng Water Temp", "WatT", "C"),
    ExportChannel("oil_temp", "Eng Oil Temp", "OilT", "C"),
)
HEADER_DATE_FORMATS = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%y %H:%M:%S")


class Channel(NamedTuple):
    """Channel to write, samples at fixed frequency (read: packed doubles)"""

    name: str
    short_name: str
    unit: str
    frequency: int
    values: Sequence[float]


class LdInfo(NamedTuple):
    """Session information, timestamp: log start (local date & time of header), 0 if unknown"""

    driver: str = ""
    vehicle: str = ""
    venue: str = ""
    session: str = ""
    comment: str = ""
    timestamp: float = 0.0


def encode(text: str, size: int) -> bytes:
    """Encode text to fixed size, null padded field"""
    return text.encode("latin-1", "replace")[:size - 1]


def write_ld(filename: str, channels: list[Channel], info: LdInfo) -> None:
    """Write MoTeC .ld file"""
    event_ptr = HEAD.size
    venue_ptr = event_ptr + EVENT.size
    vehicle_ptr = venue_ptr + VENUE.size
    meta_ptr = vehicle_ptr + VEHICLE.size
    data_ptr = meta_ptr + CHANNEL.size * len(channels)
    local = time.localtime(info.timestamp or time.time())

    with open(filename, "wb") as file:
        file.write(HEAD.pack(
            LD_MARKER, meta_ptr if channels else 0, data_ptr if channels else 0, event_ptr,
            1, 0x4240, 0xF, 0x1F44, b"ADL", 420, 0xADB0, len(channels),
            time.strftime("%d/%m/%Y", local).encode(), time.strftime("%H:%M:%S", local).encode(),
            encode(info.driver, 64), encode(info.vehicle, 64), encode(info.venue, 64),
            0xC81A4, encode(info.comment, 64),
        ))
        file.write(EVENT.pack(encode(info.venue, 64), encode(info.session, 64), b"", venue_ptr))
        file.write(VENUE.pack(encode(info.venue, 64), vehicle_ptr))
        file.write(VEHICLE.pack(encode(info.vehicle, 64), 0, b"", b""))

        offset = data_ptr
        for index, channel in enumerate(channels):
            prev_ptr = meta_ptr + CHANNEL.size * (index - 1) if index > 0 else 0
            next_ptr = meta_ptr + CHANNEL.size * (index + 1) if index < len(channels) - 1 else 0
            file.write(CHANNEL.pack(
                prev_ptr, next_ptr, offset, len(channel.values),
                0x2EE1 + index, DTYPE_FLOAT, DTYPE_SIZE_32, channel.frequency,
                0, 1, 1, 0,  # shift, multiplier, scale, decimal places: value = raw
                # Unit in both fields: MoTeC files seen in the wild store it in the 8 bytes field
                # documented as short name, community docs place it in the next 12 bytes field
                encode(channel.name, 32), encode(channel.unit, 8), encode(channel.unit, 12),
            ))
            offset += len(channel.values) * DTYPE_SIZE_32
        for channel in channels:
            file.write(array("f", channel.values).tobytes())


def raw_typecode(dtype_a: int, size: int) -> str:
    """Array type code of channel samples, "" if not supported"""
    if dtype_a == DTYPE_FLOAT:
        return {2: "e", 4: "f", 8: "d"}.get(size, "")
    if dtype_a in DTYPE_INTEGERS:
        return {2: "h", 4: "i"}.get(size, "")
    return ""


def header_time(date: str, clock: str) -> float:
    """Log start from header date ("dd/mm/yyyy") & time, local time, 0 if unknown"""
    for pattern in HEADER_DATE_FORMATS:
        try:
            return time.mktime(time.strptime(f"{date} {clock}", pattern))
        except (ValueError, OverflowError):
            continue
    return 0.0


def read_ld(
    filename: str, names: Collection[str] | None = None, max_seconds: float = 0.0,
) -> tuple[LdInfo, list[Channel]]:
    """Read MoTeC .ld file: float & integer channels (only channels named in names if set, any case), integers
    scaled to their unit

    Channels read one by one from file, samples kept packed (doubles): a game log has about 180 channels, an hour of
    them is millions of samples. Raises OSError or ValueError if not a readable .ld file. Channels of unknown type,
    or reaching past end of file, are skipped.

    Args:
        max_seconds: read channels up to this time only (memory bound of very long logs), 0 = whole channels.
    """
    wanted = {name.lower() for name in names} if names is not None else None

    def text(raw: bytes) -> str:
        return raw.split(b"\0", 1)[0].decode("latin-1").strip()

    with open(filename, "rb") as file:
        file_size = os.fstat(file.fileno()).st_size

        def read_at(offset: int, length: int) -> bytes:
            file.seek(offset)
            return file.read(length)

        try:
            head = HEAD.unpack(read_at(0, HEAD.size))
        except struct.error as error:
            raise ValueError("not a MoTeC ld file") from error
        if head[0] != LD_MARKER:
            raise ValueError("not a MoTeC ld file")
        meta_ptr, event_ptr = head[1], head[3]
        session = ""
        if 0 < event_ptr <= file_size - EVENT.size:
            session = text(EVENT.unpack(read_at(event_ptr, EVENT.size))[1])
        info = LdInfo(driver=text(head[14]), vehicle=text(head[15]), venue=text(head[16]), session=session,
                      comment=text(head[18]), timestamp=header_time(text(head[12]), text(head[13])))
        channels = []
        seen = set()
        while meta_ptr and meta_ptr not in seen and meta_ptr <= file_size - CHANNEL.size:
            seen.add(meta_ptr)  # corrupted list could loop
            chan = CHANNEL.unpack(read_at(meta_ptr, CHANNEL.size))
            meta_ptr = chan[1]
            name = text(chan[12])
            if wanted is not None and name.lower() not in wanted:
                continue
            data_ptr, count, dtype_a, size, frequency = chan[2], chan[3], chan[5], chan[6], chan[7]
            typecode = raw_typecode(dtype_a, size)
            if not typecode or frequency <= 0 or data_ptr + count * size > file_size:
                continue
            if max_seconds > 0:
                count = min(count, int(frequency * max_seconds) + 1)
            raw: array | tuple
            try:
                data = read_at(data_ptr, count * size)
                if typecode == "e":  # half float: no array type, read by struct
                    raw = struct.unpack(f"<{count}e", data)
                else:
                    raw = array(typecode)
                    raw.frombytes(data)
            except (ValueError, struct.error) as error:  # channel left out, others still read
                logger.warning("MOTEC: channel %s skipped: %s", name, error)
                continue
            shift, multiplier, scale, decimals = chan[8], chan[9], chan[10], chan[11]
            if (shift, multiplier, scale, decimals) == (0, 1, 1, 0) or not scale:
                values = array("d", raw)
            else:  # value = raw * multiplier * 10^-decimals / scale + shift
                factor = multiplier * 10.0 ** -decimals / scale
                values = array("d", (sample * factor + shift for sample in raw))
            unit = text(chan[14]) or text(chan[13])
            channels.append(Channel(name, text(chan[13]), unit, frequency, values))
    return info, channels


def sample_rate(times: list[float]) -> int:
    """Median sample rate (Hz) of recorded samples"""
    steps = sorted(b - a for a, b in pairwise(times) if b > a)
    if not steps:
        return 1
    return min(max(round(1 / steps[len(steps) // 2]), 1), 1000)


def lap_channels(lap: LapData) -> list[Channel]:
    """Resample recorded lap columns to fixed rate MoTeC channels"""
    times = lap.columns.get("lap_time", [])
    if len(times) < 2:
        raise ValueError("not enough telemetry samples")
    # Keep increasing time only (drop duplicated samples)
    keep = [0]
    for index in range(1, len(times)):
        if times[index] > times[keep[-1]]:
            keep.append(index)
    xs = [times[index] for index in keep]
    rate = sample_rate(xs)
    count = int((xs[-1] - xs[0]) * rate) + 1
    ticks = [xs[0] + step / rate for step in range(count)]
    # Held channels: sample at or before each tick (a gear is never 2.5)
    held = [max(bisect_right(xs, tick) - 1, 0) for tick in ticks]
    channels = []
    for export in CHANNEL_MAP:
        values = lap.columns.get(export.column)
        if values is None:
            continue
        ys = [values[index] * export.scale + export.offset for index in keep]
        if export.step:
            samples = [ys[index] for index in held]
        else:
            samples = [interpolate(xs, ys, tick) for tick in ticks]
        channels.append(Channel(export.name, export.short_name, export.unit, rate, samples))
    return channels


def export_lap(lap: LapData, filename: str, venue: str = "", timestamp: float = 0.0) -> None:
    """Export recorded lap to MoTeC .ld file, vehicle, session & driver from lap info if recorded

    Lap name (date, lap number & time) kept as comment: imported back with the same name. Log date is lap start,
    from lap name (lap end) if dated, else timestamp.
    """
    meta = lap.meta
    finished = lap_timestamp_of(lap.name)
    lap_time = lap_time_of(f"{lap.name}.csv") or lap.lap_time  # name is file name without extension
    info = LdInfo(
        driver=str(meta.get("driver", "")),
        vehicle=str(meta.get("vehicle", "")),
        venue=str(meta.get("track") or venue),
        session=str(meta.get("session", "")),
        comment=lap.name,
        timestamp=finished - lap_time if finished > 0 else timestamp,
    )
    write_ld(filename, lap_channels(lap), info)


def export_lap_job(folder: str, path: str, target: str, venue: str = "") -> str:
    """Export recorded lap file to MoTeC .ld file (worker process job: lap read from binary cache of folder),
    returns error text ("" if exported)

    Written to a temporary file renamed once complete: job stopped at app exit leaves no partial .ld file.
    """
    import os
    from contextlib import suppress

    from .lap_cache import load_cached_lap

    temporary = f"{target}.tmp"
    try:
        export_lap(load_cached_lap(folder, path), temporary, venue=venue, timestamp=os.path.getmtime(path))
        os.replace(temporary, target)
    except (OSError, ValueError) as error:
        logger.error("MOTEC: unable to export %s: %s", path, error)
        with suppress(OSError):
            os.remove(temporary)
        return error_text(error)
    return ""


def import_ld_job(filename: str, folder: str) -> tuple[list[str], str]:
    """Import complete laps of MoTeC .ld file to folder (worker process job: a long log takes seconds to read),
    returns lap file paths & error text ("" if imported)"""
    from .motec_import import import_ld_file

    try:
        return import_ld_file(filename, folder), ""
    except (OSError, ValueError, MemoryError) as error:  # memory: huge log (or sizes made up by a broken file)
        logger.error("MOTEC: unable to import %s: %s", filename, error)
        return [], error_text(error)


def error_text(error: Exception) -> str:
    """Short reason of a failed export or import"""
    return (error.strerror if isinstance(error, OSError) and error.strerror else str(error)) or type(error).__name__
