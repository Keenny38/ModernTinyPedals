"""Make a small recorded session for tests from a Le Mans Ultimate recording (.tpreplay)

Usage (from project root):
    python tools/make_replay_fixture.py SOURCE OUTPUT [--start S] [--end S] [--rate FPS] [--driver NAME]

Keeps part of the recording (start to end seconds) at a lower frame rate, so a few minutes of driving
fit in a few MB: telemetry of the other cars is dropped (their scoring stays: places, gaps, positions on
track), every frame and Rest API snapshot is compressed at the highest level. The player name is replaced
everywhere (shared memory, scoring stream, Rest API data) and chat messages are removed, so a recording
of your own sessions can be added to the repository without your name.

Recorded sessions of tests are in tests/fixtures/sessions, each with its expected values (.json),
see tests/test_recorded_sessions.py.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from neopedal.const_api import API_LMU_NAME
from neopedal.replay import ReplayFile, ReplayWriter
from pyLMUSharedMemory import lmu_data

DEFAULT_DRIVER = "Test Driver"
FRAME_SIZE = ctypes.sizeof(lmu_data.LMUObjectOut)
TELEMETRY_SIZE = ctypes.sizeof(lmu_data.LMUVehicleTelemetry)


def same_length(name: bytes, size: int) -> bytes:
    """Replacement of name fitted to size bytes (scoring stream keeps its length)"""
    return name[:size].ljust(size, b" ")


def set_text(structure, field: str, text: bytes) -> None:
    """Text field set to text (cut to field size, zero ended)"""
    setattr(structure, field, text[:getattr(type(structure), field).size - 1])


def anonymize_text(value, player: str, driver: str):
    """Player name replaced in every string of Rest API data"""
    if isinstance(value, str):
        return value.replace(player, driver) if player else value
    if isinstance(value, list):
        return [anonymize_text(item, player, driver) for item in value]
    if isinstance(value, dict):
        return {key: anonymize_text(item, player, driver) for key, item in value.items()}
    return value


def strip_frame(frame: bytes, offset: int, driver: bytes) -> tuple[bytes, str]:
    """Frame without telemetry of other cars, player name replaced, returns (frame, player name)"""
    buffer = bytearray(frame[offset:offset + FRAME_SIZE])
    data = lmu_data.LMUObjectOut.from_buffer(buffer)
    scoring = data.scoring
    total = min(max(scoring.scoringInfo.mNumVehicles, 0), len(scoring.vehScoringInfo))
    player = next((vehicle for vehicle in scoring.vehScoringInfo[:total] if vehicle.mIsPlayer), None)
    player_id = player.mID if player is not None else -1
    player_name = bytes(scoring.scoringInfo.mPlayerName).split(b"\0", 1)[0]
    for telemetry in data.telemetry.telemInfo[:data.telemetry.activeVehicles]:
        if telemetry.mID != player_id:
            slot_id = telemetry.mID  # kept: telemetry index of each car still found by id
            ctypes.memset(ctypes.addressof(telemetry), 0, TELEMETRY_SIZE)
            telemetry.mID = slot_id
    if player_name:
        set_text(scoring.scoringInfo, "mPlayerName", driver)
        if player is not None:
            set_text(player, "mDriverName", driver)
    del data, scoring, player  # release buffer exports
    zone = bytes(buffer)
    if player_name:  # anywhere else, such as scoring stream (also after its end mark: older text left in it)
        zone = zone.replace(player_name, same_length(driver, len(player_name)))
    return bytes(frame[:offset]) + zone + bytes(frame[offset + FRAME_SIZE:]), player_name.decode(
        "utf-8", errors="replace")


def make_fixture(source: str, output: str, start: float, end: float, rate: int, driver: str) -> int:
    """Write fixture, return number of frames"""
    replay = ReplayFile(source)
    if replay.header.get("source", API_LMU_NAME) != API_LMU_NAME:
        raise SystemExit(f"{source}: only Le Mans Ultimate recordings are supported")
    offset = replay.zone_offset("shmm")
    end = min(end, replay.duration) if end > 0 else replay.duration
    first, last = replay.index_at(start), replay.index_at(end)
    origin = replay.times[first]
    header = {key: value for key, value in replay.header.items() if key not in ("frame_size", "rate", "created")}
    header["created"] = replay.created + origin
    header["trimmed_from"] = os.path.basename(source)
    header["layout"] = [list(zone) for zone in replay.layout]
    rest = replay.iter_rest(replay.rest_at(origin), replay.rest_at(replay.times[last]))
    next_rest = next(rest, None)
    markers = [marker for marker in replay.markers if origin <= marker.time <= replay.times[last]]
    encoded_driver = driver.encode("utf-8")
    player = ""
    step = 1.0 / rate
    next_time = origin
    temp_name = f"{output}.part"
    with open(temp_name, "wb") as file:
        writer = ReplayWriter(file, replay.frame_size, rate, header, compress_level=9)
        for frame_time, frame in replay.iter_frames(first, last):
            if frame_time + 1e-6 < next_time:
                continue
            next_time += step * max(1, int((frame_time - next_time) / step) + 1)
            frame, name = strip_frame(frame, offset, encoded_driver)
            player = player or name
            writer.write(frame_time - origin, frame)
            while next_rest is not None and next_rest[0] <= frame_time:
                writer.write_rest(max(next_rest[0] - origin, 0.0), {
                    **anonymize_text(next_rest[1], player, driver), "chatMessages": []})
                next_rest = next(rest, None)
            while markers and markers[0].time <= frame_time:
                marker = markers.pop(0)
                writer.write_marker(marker.time - origin, marker.kind, anonymize_text(marker.text, player, driver))
        writer.finish()
    os.replace(temp_name, output)
    return writer.frames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("source", help="recording (.tpreplay) of Le Mans Ultimate")
    parser.add_argument("output", help="fixture file to write")
    parser.add_argument("--start", type=float, default=0.0, help="first second kept")
    parser.add_argument("--end", type=float, default=0.0, help="last second kept (0: end of recording)")
    parser.add_argument("--rate", type=int, default=5, help="frames per second kept")
    parser.add_argument("--driver", default=DEFAULT_DRIVER, help="name replacing player name")
    options = parser.parse_args()
    frames = make_fixture(options.source, options.output, options.start, options.end, max(options.rate, 1),
                          options.driver)
    size = os.path.getsize(options.output)
    print(f"{options.output}: {frames} frames, {size / 1024 / 1024:.1f} MB")
    with open(options.output, "rb") as file:
        info = json.loads(file.readline()[10:]).get("info", {})
    if info:
        print(", ".join(f"{key}: {value}" for key, value in info.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
