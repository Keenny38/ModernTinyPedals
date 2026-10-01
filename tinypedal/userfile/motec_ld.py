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
MoTeC i2 log file (.ld) export of recorded laps

Layout follows the community documented .ld format (see "ldparser" project):
header, event, venue, vehicle, then linked list of channel descriptors, then
channel data as little endian float32 at a fixed rate per channel.
"""

from __future__ import annotations

import struct
import time
from array import array
from itertools import pairwise
from typing import NamedTuple

from .telemetry_lap import LapData, interpolate

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
DTYPE_SIZE_32 = 4

# Recorder CSV column: MoTeC channel name, short name, unit, scale factor
CHANNEL_MAP = (
    ("lap_time", "Lap Time", "LapT", "s", 1.0),
    ("distance", "Lap Distance", "LapD", "m", 1.0),
    ("speed_kph", "Ground Speed", "Spd", "km/h", 1.0),
    ("throttle", "Throttle Pos", "Thr", "%", 100.0),
    ("brake", "Brake Pos", "Brk", "%", 100.0),
    ("clutch", "Clutch Pos", "Clu", "%", 100.0),
    ("steering", "Steering Pos", "Str", "%", 100.0),
    ("gear", "Gear", "Gear", "", 1.0),
    ("rpm", "Engine RPM", "RPM", "rpm", 1.0),
    ("fuel", "Fuel Level", "Fuel", "l", 1.0),
    ("tyre_temp_fl", "Tyre Temp FL", "TTFL", "C", 1.0),
    ("tyre_temp_fr", "Tyre Temp FR", "TTFR", "C", 1.0),
    ("tyre_temp_rl", "Tyre Temp RL", "TTRL", "C", 1.0),
    ("tyre_temp_rr", "Tyre Temp RR", "TTRR", "C", 1.0),
    ("tyre_pres_fl", "Tyre Pres FL", "TPFL", "kPa", 1.0),
    ("tyre_pres_fr", "Tyre Pres FR", "TPFR", "kPa", 1.0),
    ("tyre_pres_rl", "Tyre Pres RL", "TPRL", "kPa", 1.0),
    ("tyre_pres_rr", "Tyre Pres RR", "TPRR", "kPa", 1.0),
    ("pos_x", "Pos X", "PosX", "m", 1.0),
    ("pos_y", "Pos Y", "PosY", "m", 1.0),
    ("pos_z", "Pos Z", "PosZ", "m", 1.0),
    ("accel_lat", "G Force Lat", "GLat", "G", 1.0),
    ("accel_long", "G Force Long", "GLong", "G", 1.0),
    ("sector", "Sector", "Sect", "", 1.0),
    ("tc_active", "TC Active", "TCAct", "", 1.0),
    ("abs_active", "ABS Active", "ABSAct", "", 1.0),
    ("battery", "Battery Charge", "Batt", "%", 1.0),
    *((f"brake_temp_{wheel}", f"Brake Temp {wheel.upper()}", f"BT{wheel.upper()}", "C", 1.0) for wheel in WHEELS),
    *((f"tyre_wear_{wheel}", f"Tyre Wear {wheel.upper()}", f"TW{wheel.upper()}", "%", 1.0) for wheel in WHEELS),
    *((f"wheel_speed_{wheel}", f"Wheel Speed {wheel.upper()}", f"WS{wheel.upper()}", "km/h", 1.0) for wheel in WHEELS),
    *((f"ride_height_{wheel}", f"Ride Height {wheel.upper()}", f"RH{wheel.upper()}", "mm", 1.0) for wheel in WHEELS),
    *((f"susp_defl_{wheel}", f"Damper Pos {wheel.upper()}", f"DP{wheel.upper()}", "mm", 1.0) for wheel in WHEELS),
)


class Channel(NamedTuple):
    """Channel to write, samples at fixed frequency"""

    name: str
    short_name: str
    unit: str
    frequency: int
    values: list[float]


class LdInfo(NamedTuple):
    """Session information"""

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


def read_ld(filename: str) -> tuple[LdInfo, list[Channel]]:
    """Read MoTeC .ld file written by write_ld (float channels only)"""
    with open(filename, "rb") as file:
        data = file.read()
    head = HEAD.unpack_from(data, 0)
    if head[0] != LD_MARKER:
        raise ValueError("not a MoTeC ld file")
    meta_ptr, event_ptr = head[1], head[3]

    def text(raw: bytes) -> str:
        return raw.rstrip(b"\0").decode("latin-1")

    event = EVENT.unpack_from(data, event_ptr)
    info = LdInfo(driver=text(head[14]), vehicle=text(head[15]), venue=text(head[16]),
                  session=text(event[1]), comment=text(head[18]))
    channels = []
    while meta_ptr:
        chan = CHANNEL.unpack_from(data, meta_ptr)
        values = array("f")
        values.frombytes(data[chan[2]:chan[2] + chan[3] * DTYPE_SIZE_32])
        unit = text(chan[14]) or text(chan[13])
        channels.append(Channel(text(chan[12]), text(chan[13]), unit, chan[7], values.tolist()))
        meta_ptr = chan[1]
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
    channels = []
    for column, name, short_name, unit, scale in CHANNEL_MAP:
        values = lap.columns.get(column)
        if values is None:
            continue
        ys = [values[index] * scale for index in keep]
        channels.append(Channel(name, short_name, unit, rate, [interpolate(xs, ys, tick) for tick in ticks]))
    return channels


def export_lap(lap: LapData, filename: str, venue: str = "", timestamp: float = 0.0) -> None:
    """Export recorded lap to MoTeC .ld file, vehicle & session from lap info if recorded"""
    meta = lap.meta
    info = LdInfo(
        vehicle=str(meta.get("vehicle", "")),
        venue=str(meta.get("track") or venue),
        session=str(meta.get("session", "")),
        comment=lap.name,
        timestamp=timestamp,
    )
    write_ld(filename, lap_channels(lap), info)
