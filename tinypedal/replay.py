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
Shared memory recording & replay

Records raw shared memory frames (LMU, or rF2 & LMU legacy) to a file, and plays them back
through the regular API, so every widget & module can run without the game.

File format (.tpreplay):
    header line: b"TPREPLAY2 " + json + b"\\n", json: format version, frame size, rate, created,
        source API, zone layout ([name, structure size], ...), info.
    frames: struct FRAME_HEADER (elapsed seconds, frame type, payload size, payload CRC32) + payload
    frame type 0 or 1 (keyframe): zlib of frame XOR previous frame, or of full frame (keyframe).
    frame type 2: zlib of json Rest API data snapshot (weather forecast, damage...), written when changed.
    frame type 3: json marker {"kind": "lap" or "incident"..., "text": str}.
    frame type 4: json summary {"duration", "frames"}, written when recording ends,
        followed by trailer struct TRAILER (summary frame offset, b"TPIX").
A frame is every shared memory zone back to back, as listed in header "layout" ([name, size], ...).
Frames are read from file on demand, only their position is kept in memory.

Format 1 (b"TPREPLAY1 ", still read): frame header without CRC, LMU files without layout
(single "shmm" zone of frame size).
"""

from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import re
import struct
import threading
import time
import zlib
from array import array
from bisect import bisect_right
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from typing import Any, BinaryIO, NamedTuple

from .const_api import API_LMU_NAME, API_LMULEGACY_NAME, API_RF2_NAME

logger = logging.getLogger(__name__)

FORMAT_VERSION = 2
MAGIC = b"TPREPLAY2 "
MAGIC_V1 = b"TPREPLAY1 "
FILE_EXT = ".tpreplay"
FRAME_HEADER = struct.Struct("<dBII")  # elapsed, frame type, payload size, payload CRC32
FRAME_HEADER_V1 = struct.Struct("<dBI")  # format 1: no CRC
TRAILER = struct.Struct("<Q4s")
TRAILER_MAGIC = b"TPIX"
KEYFRAME_INTERVAL = 100  # frames between full frames, bounds seeking cost
REST_FRAME = 2  # frame type of Rest API data snapshot
MARKER_FRAME = 3  # frame type of marker (lap, incident)
SUMMARY_FRAME = 4  # frame type of summary, last frame of complete recording
REST_INTERVAL = 1.0  # seconds between Rest API data checks
DEFAULT_RATE = 30  # recorded frames per second
MAX_GAP = 1.0  # seconds, longer gaps between recorded frames (inactive, paused) are removed
SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0)
MAX_FRAME_SIZE = 64 * 1024 * 1024  # bound of header frame size (largest shared memory is a few MB)
MAX_EXTRA_SIZE = 16 * 1024 * 1024  # bound of Rest API snapshot, marker & summary payload
EXPORT_PROGRESS_STEP = 100  # frames between export progress calls
SCAN_CHECK_STEP = 2000  # frames between cancel checks & progress calls while scanning replay file


# Replay source API names that share shared memory structures
REPLAY_FAMILIES = (
    (API_LMU_NAME,),
    (API_RF2_NAME, API_LMULEGACY_NAME),
)


def replay_compatible(source: str, api_name: str) -> bool:
    """Whether replay recorded from source API can be played with API"""
    if source == api_name:
        return True
    return any(source in family and api_name in family for family in REPLAY_FAMILIES)


class ReplayLoadCancelled(Exception):
    """Replay file loading cancelled (other file opened, window closed)"""


class ReplayMismatch(ValueError):
    """Replay recorded with an API or shared memory structure that current API cannot play

    Attributes:
        source: API name replay was recorded with.
        reason: "source" (other API), or "layout" (other structure size: older game or app version).
    """

    def __init__(self, message: str, source: str, reason: str):
        super().__init__(message)
        self.source = source
        self.reason = reason


def replay_mismatch(replay_file: ReplayFile, api_name: str, layout: Sequence[Sequence]) -> ReplayMismatch | None:
    """Why replay cannot be played with API of zone layout, None if it can

    Zone names & structure sizes must match exactly: a smaller frame cannot fill the structure,
    a larger one would be read with shifted offsets. Older files without layout are a single
    LMU zone of frame size, so only exact size match is accepted for them too.
    """
    if not replay_compatible(replay_file.source, api_name):
        return ReplayMismatch(
            f"recorded with {replay_file.source} API, not {api_name}", replay_file.source, "source")
    expected = [(str(name), int(size)) for name, size in layout]
    if replay_file.layout != expected:
        return ReplayMismatch(
            f"recorded data structure {replay_file.layout} differs from {expected}", replay_file.source, "layout")
    return None


def no_update() -> None:
    """Update placeholder while replay is not feeding frames"""


def rest_snapshot(dataset: Any) -> dict:
    """Rest API data set to json compatible dict (tuples & named tuples to lists)"""
    def plain(value):
        if isinstance(value, (tuple, list)):
            return [plain(item) for item in value]
        return value

    return {name: plain(getattr(dataset, name)) for name in getattr(type(dataset), "__slots__", ())}


def apply_rest_snapshot(dataset: Any, data: dict) -> None:
    """Set Rest API data set from snapshot, keeping value types (named tuples, tuples)"""
    for name in getattr(type(dataset), "__slots__", ()):
        if name not in data:
            continue
        current, value = getattr(dataset, name), data[name]
        if isinstance(current, tuple) and isinstance(value, list):
            if current and isinstance(current[0], tuple) and hasattr(current[0], "_fields"):
                node_type = type(current[0])
                value = tuple(node_type(*item) for item in value)
            else:
                value = tuple(value)
        setattr(dataset, name, value)


def xor_bytes(data: bytes, base: bytes) -> bytes:
    """XOR two equal size byte strings"""
    size = len(data)
    return (int.from_bytes(data, "little") ^ int.from_bytes(base, "little")).to_bytes(size, "little")


class Marker(NamedTuple):
    """Replay marker"""

    time: float
    kind: str  # "lap", "incident"
    text: str


class ReplayWriter:
    """Write frames to replay file (current format)"""

    def __init__(self, file: BinaryIO, frame_size: int, rate: int, header_extra: dict | None = None):
        """
        Args:
            header_extra: source API name, zone layout ([name, size], ...), info...
        """
        self._file = file
        self._frame_size = frame_size
        self._last = b""
        self._last_rest = b""
        self._count = 0
        self._elapsed = 0.0
        header = {"frame_size": frame_size, "rate": rate, "created": time.time(), **(header_extra or {})}
        header["format"] = FORMAT_VERSION  # current format, also when header copied from older file
        file.write(MAGIC + json.dumps(header).encode("utf-8") + b"\n")

    @property
    def frames(self) -> int:
        """Number of written frames"""
        return self._count

    def write(self, elapsed: float, frame: bytes) -> None:
        """Write frame"""
        if len(frame) != self._frame_size:
            raise ValueError(f"frame size {len(frame)} != {self._frame_size}")
        keyframe = self._count % KEYFRAME_INTERVAL == 0
        raw = frame if keyframe else xor_bytes(frame, self._last)
        self._write(elapsed, int(keyframe), zlib.compress(raw, 1))
        self._last = frame
        self._count += 1
        self._elapsed = elapsed

    def write_rest(self, elapsed: float, data: dict) -> bool:
        """Write Rest API data snapshot if changed since last one, returns True if written"""
        encoded = json.dumps(data).encode("utf-8")
        if encoded == self._last_rest:
            return False
        self._last_rest = encoded
        self._write(elapsed, REST_FRAME, zlib.compress(encoded, 1))
        return True

    def write_marker(self, elapsed: float, kind: str, text: str = "") -> None:
        """Write marker (lap, incident)"""
        self._write(elapsed, MARKER_FRAME, json.dumps({"kind": kind, "text": text}).encode("utf-8"))

    def finish(self, extra: dict | None = None) -> None:
        """Write summary & trailer, so replay list can read duration without scanning file"""
        offset = self._file.tell()
        summary = {"duration": self._elapsed, "frames": self._count, **(extra or {})}
        self._write(self._elapsed, SUMMARY_FRAME, json.dumps(summary).encode("utf-8"))
        self._file.write(TRAILER.pack(offset, TRAILER_MAGIC))

    def _write(self, elapsed: float, frame_type: int, payload: bytes) -> None:
        self._file.write(FRAME_HEADER.pack(elapsed, frame_type, len(payload), zlib.crc32(payload)))
        self._file.write(payload)


def read_header(file: BinaryIO) -> dict:
    """Read replay header line, raise ValueError if not a replay file

    Header "format" is set from file magic (1 or 2).
    """
    line = file.readline(1024 * 1024)
    if line.startswith(MAGIC):
        version = FORMAT_VERSION
    elif line.startswith(MAGIC_V1):
        version = 1
    else:
        raise ValueError("not a TinyPedal replay file")
    try:
        header = json.loads(line[len(MAGIC):])
    except ValueError as error:
        raise ValueError("invalid replay header") from error
    if not isinstance(header, dict):
        raise ValueError("invalid replay header")
    frame_size = header.get("frame_size")
    if not isinstance(frame_size, int) or isinstance(frame_size, bool) or not 0 < frame_size <= MAX_FRAME_SIZE:
        raise ValueError("invalid replay header")
    # Other fields read as numbers or text: wrong type (null, list...) is an invalid file, not a TypeError
    if not (finite_number(header.get("created", 0.0)) and finite_number(header.get("rate", DEFAULT_RATE))
            and isinstance(header.get("source", ""), str)):
        raise ValueError("invalid replay header")
    header["format"] = version
    return header


def finite_number(value: Any) -> bool:
    """Whether value is a finite number (bool excluded)"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # integer too large for float
        return False


def frame_header_of(header: dict) -> struct.Struct:
    """Frame header structure of replay format"""
    return FRAME_HEADER_V1 if header.get("format", 1) < 2 else FRAME_HEADER


def read_summary(file: BinaryIO, frame_header: struct.Struct = FRAME_HEADER) -> dict:
    """Summary of complete recording from file trailer, empty if missing (interrupted recording)"""
    try:
        size = file.seek(0, os.SEEK_END)
        if size < TRAILER.size + frame_header.size:
            return {}
        file.seek(size - TRAILER.size)
        offset, magic = TRAILER.unpack(file.read(TRAILER.size))
        end = size - TRAILER.size  # summary frame ends at trailer
        if magic != TRAILER_MAGIC or offset + frame_header.size > end:
            return {}
        file.seek(offset)
        fields = frame_header.unpack(file.read(frame_header.size))
        frame_type, length = fields[1], fields[2]
        # Bound length: a corrupt trailer must not make a huge read
        if frame_type != SUMMARY_FRAME or length > min(MAX_EXTRA_SIZE, end - offset - frame_header.size):
            return {}
        payload = file.read(length)
        if len(fields) > 3 and zlib.crc32(payload) != fields[3]:
            return {}
        summary = json.loads(payload)
    except (OSError, ValueError, struct.error):
        return {}
    return summary if isinstance(summary, dict) else {}


class ReplayInfo(NamedTuple):
    """Replay file info for replay list"""

    filename: str
    created: float
    size: int
    duration: float  # -1 if unknown (interrupted recording)
    source: str
    info: dict  # track, vehicle, class, session


def read_replay_info(filename: str) -> ReplayInfo:
    """Read replay header & summary only (fast), raise OSError or ValueError on invalid file"""
    with open(filename, "rb") as file:
        header = read_header(file)
        summary = read_summary(file, frame_header_of(header))
        size = file.seek(0, os.SEEK_END)
    info = header.get("info")
    duration = summary.get("duration", -1.0)
    return ReplayInfo(
        filename=filename,
        created=float(header.get("created", 0.0)),
        size=size,
        duration=float(duration) if finite_number(duration) else -1.0,
        source=str(header.get("source", API_LMU_NAME)),
        info=info if isinstance(info, dict) else {},
    )


def same_file(filename: str, other: str) -> bool:
    """Whether both names point to same file (case, links), compared by name if either is missing"""
    try:
        return os.path.samefile(filename, other)
    except (OSError, ValueError):
        return os.path.normcase(os.path.realpath(filename)) == os.path.normcase(os.path.realpath(other))


def list_replays(folder: str) -> list[ReplayInfo]:
    """Replay files of folder, newest first"""
    try:
        names = [name for name in os.listdir(folder) if name.endswith(FILE_EXT)]
    except OSError:
        return []
    replays = []
    for name in names:
        try:
            replays.append(read_replay_info(os.path.join(folder, name)))
        except (OSError, ValueError, TypeError):  # one bad file never hides the others
            continue
    replays.sort(key=lambda item: item.created, reverse=True)
    return replays


def remove_old_replays(folder: str, prefix: str | re.Pattern, keep: int) -> list[str]:
    """Remove oldest replay files over limit, return removed file names

    Args:
        prefix: file name prefix, or pattern matching whole file name (other files never removed).
    """
    if isinstance(prefix, str):
        def matched(name: str) -> bool:
            return name.startswith(prefix) and name.endswith(FILE_EXT)
    else:
        def matched(name: str) -> bool:
            return prefix.fullmatch(name) is not None
    removed: list[str] = []
    try:
        files = [os.path.join(folder, name) for name in os.listdir(folder) if matched(name)]
        files.sort(key=os.path.getmtime)
    except OSError as error:
        logger.error("replay: unable to remove old replays: %s", error)
        return removed
    for old_file in files[:-max(keep, 1)]:
        try:
            os.remove(old_file)
            removed.append(os.path.basename(old_file))
        except OSError as error:  # open elsewhere: removed next time
            logger.error("replay: unable to remove old replay: %s", error)
    return removed


class ReplayFile:
    """Read replay file, frames are read from file on demand

    Damaged files are read up to the damage: a zero-filled tail (power loss) or invalid frame
    header ends the file, a frame failing CRC or decompression is skipped (replay holds last good
    frame until next keyframe).
    """

    def __init__(
        self, filename: str, cancel: threading.Event | None = None,
        progress: Callable[[int, int], None] | None = None,
    ):
        """Open replay file and index its frames (seconds for a long recording, see ReplayControl.prepare)

        Args:
            cancel: set to stop scanning (any thread), raises ReplayLoadCancelled, file closed.
            progress: called with (bytes scanned, file size) every SCAN_CHECK_STEP frames.
        """
        self.filename = filename
        self._file = open(filename, "rb")  # noqa: SIM115 (kept open, frames are read on demand)
        try:
            self._scan(cancel, progress)
        except Exception:
            self._file.close()
            raise
        self._lock = threading.Lock()  # file reading
        self._frame_lock = threading.Lock()  # decoding state (current frame)
        self._index = -1
        self._frame = bytes(self.frame_size)  # zero frame until first good frame decoded
        self._broken = True  # previous frame unavailable: wait for keyframe
        self._corrupt: set[int] = set()

    def _scan(self, cancel: threading.Event | None, progress: Callable[[int, int], None] | None):
        file = self._file
        header = read_header(file)
        self.header = header
        self.format = int(header.get("format", 1))
        self.frame_size = int(header["frame_size"])
        self.rate = int(header.get("rate", DEFAULT_RATE))
        self.created = float(header.get("created", 0.0))
        self.source = str(header.get("source", API_LMU_NAME))  # API name, older files are LMU
        info = header.get("info")
        self.info: dict = info if isinstance(info, dict) else {}
        try:
            self.layout: list[tuple[str, int]] = [
                (str(name), int(size)) for name, size in header.get("layout", [["shmm", self.frame_size]])]
        except (TypeError, ValueError) as error:
            raise ValueError("invalid zone layout") from error
        if sum(size for _, size in self.layout) != self.frame_size:
            raise ValueError("invalid zone layout")
        # Frame index in packed arrays (a long recording has hundreds of thousands of frames)
        self.times = array("d")
        self.keyframes = bytearray()  # 1 if keyframe
        self._offsets = array("q")
        self._sizes = array("q")
        self._crcs = array("I")  # payload CRC of each frame (format 2)
        self.rest_times: list[float] = []
        self.rest_data: list[dict] = []
        self.markers: list[Marker] = []
        self.summary: dict = {}
        self.damaged = False  # file ends with damaged data (power loss, disk error)
        frame_header = frame_header_of(header)
        has_crc = frame_header is FRAME_HEADER
        max_frame = self.frame_size + self.frame_size // 100 + 1024  # zlib worst case (incompressible)
        file_size = os.fstat(file.fileno()).st_size
        position = file.tell()
        last_time = float("-inf")
        countdown = SCAN_CHECK_STEP
        while True:
            countdown -= 1
            if not countdown:
                countdown = SCAN_CHECK_STEP
                if cancel is not None and cancel.is_set():
                    raise ReplayLoadCancelled(self.filename)
                if progress is not None:
                    progress(position, file_size)
            head = file.read(frame_header.size)
            if len(head) < frame_header.size:
                break  # end of file, or truncated frame from interrupted recording
            fields = frame_header.unpack(head)
            elapsed, frame_type, size = fields[0], fields[1], fields[2]
            # Zero-filled tail has zero size, garbage has unknown type, goes back in time or above size bound
            if frame_type <= 1:
                valid = 0 < size <= max_frame and math.isfinite(elapsed) and elapsed >= last_time - 0.001
            else:
                valid = frame_type <= SUMMARY_FRAME and size <= MAX_EXTRA_SIZE and math.isfinite(elapsed)
            if not valid:
                self._damaged_at(position)
                break
            position += frame_header.size
            if position + size > file_size:
                break  # truncated frame from interrupted recording
            if frame_type <= 1:
                last_time = elapsed
                self.times.append(elapsed)
                self.keyframes.append(1 if frame_type else 0)
                self._offsets.append(position)
                self._sizes.append(size)
                if has_crc:
                    self._crcs.append(fields[3])
                file.seek(size, os.SEEK_CUR)
            else:
                payload = file.read(size)
                if has_crc and zlib.crc32(payload) != fields[3]:
                    logger.warning("replay: %s: damaged data frame skipped", os.path.basename(self.filename))
                else:
                    self._read_extra(elapsed, frame_type, payload)
            position += size
        if not self._offsets or not self.keyframes[0]:
            raise ValueError("replay file contains no frame")
        self.markers.sort(key=lambda marker: marker.time)

    def _damaged_at(self, position: int):
        self.damaged = True
        logger.warning(
            "replay: %s: damaged data at byte %s, later frames ignored", os.path.basename(self.filename), position)

    def _read_extra(self, elapsed: float, frame_type: int, payload: bytes):
        try:
            if frame_type == REST_FRAME:
                data = json.loads(zlib.decompress(payload))
                if isinstance(data, dict):
                    self.rest_times.append(elapsed)
                    self.rest_data.append(data)
            elif frame_type == MARKER_FRAME:
                data = json.loads(payload)
                if isinstance(data, dict):
                    self.markers.append(Marker(elapsed, str(data.get("kind", "")), str(data.get("text", ""))))
            elif frame_type == SUMMARY_FRAME:
                data = json.loads(payload)
                if isinstance(data, dict):
                    self.summary = data
        except (zlib.error, ValueError):
            pass

    def close(self) -> None:
        """Close file"""
        self._file.close()

    def __del__(self):
        # Closed when last reader (player, API shared memory zones) is gone, see ReplayControl.unload
        file = getattr(self, "_file", None)
        if file is not None:
            file.close()

    def __len__(self) -> int:
        return len(self._offsets)

    @property
    def duration(self) -> float:
        """Replay duration (seconds)"""
        return self.times[-1]

    def index_at(self, elapsed: float) -> int:
        """Last frame index at elapsed time"""
        return max(bisect_right(self.times, elapsed) - 1, 0)

    def zone_offset(self, name: str) -> int:
        """Byte offset of shared memory zone in frame"""
        offset = 0
        for zone, size in self.layout:
            if zone == name:
                return offset
            offset += size
        raise ValueError(f"zone {name} not in replay")

    def rest_at(self, elapsed: float) -> int:
        """Index of last Rest API snapshot at elapsed time, -1 if none"""
        return bisect_right(self.rest_times, elapsed) - 1

    def markers_of(self, kind: str) -> list[Marker]:
        """Markers of kind, in time order"""
        return [marker for marker in self.markers if marker.kind == kind]

    def _payload(self, index: int) -> bytes:
        with self._lock:
            self._file.seek(self._offsets[index])
            return self._file.read(self._sizes[index])

    def _decode(self, index: int, previous: bytes) -> bytes | None:
        """Decoded frame, None if damaged (CRC, decompression or size)"""
        payload = self._payload(index)
        raw = b""
        if not self._crcs or zlib.crc32(payload) == self._crcs[index]:
            with suppress(zlib.error):
                raw = zlib.decompress(payload)
        if len(raw) != self.frame_size:
            if index not in self._corrupt:
                self._corrupt.add(index)
                logger.warning(
                    "replay: %s: damaged frame %s skipped, until next keyframe", os.path.basename(self.filename), index)
            return None
        return raw if self.keyframes[index] else xor_bytes(raw, previous)

    def frame(self, index: int) -> bytes:
        """Get decoded frame, sequential access is fast, seeking starts from nearest keyframe

        Thread safe. A damaged frame is skipped: last good frame is kept until next keyframe.
        """
        with self._frame_lock:
            index = min(max(index, 0), len(self) - 1)
            if index == self._index:
                return self._frame
            if index < self._index or index - self._index > KEYFRAME_INTERVAL:
                start = index
                while not self.keyframes[start]:
                    start -= 1
                self._index = start - 1
                self._broken = True
            while self._index < index:
                self._index += 1
                if self._broken and not self.keyframes[self._index]:
                    continue  # no previous frame to apply difference to
                frame = self._decode(self._index, self._frame)
                if frame is None:
                    self._broken = True
                else:
                    self._frame = frame
                    self._broken = False
            return self._frame

    def iter_frames(self, first: int, last: int) -> Iterator[tuple[float, bytes]]:
        """Decoded frames (time, frame) of index range, independent of playback position

        Damaged frames (and following ones until next keyframe) are skipped.
        """
        start = first
        while not self.keyframes[start]:
            start -= 1
        frame = b""
        broken = True
        for index in range(start, last + 1):
            if broken and not self.keyframes[index]:
                continue
            decoded = self._decode(index, frame)
            if decoded is None:
                broken = True
                continue
            frame, broken = decoded, False
            if index >= first:
                yield self.times[index], frame

    def export(
        self, filename: str, start: float, end: float, progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Save part of replay (start to end seconds) to new file, return number of frames

        Args:
            progress: called with (frames done, frames total) every EXPORT_PROGRESS_STEP frames (any thread).
        """
        first, last = self.index_at(start), self.index_at(end)
        if last < first:
            first, last = last, first
        origin = self.times[first]
        end_time = self.times[last]
        header = {key: value for key, value in self.header.items() if key not in ("frame_size", "rate", "created")}
        header["created"] = self.created + origin
        header["trimmed_from"] = os.path.basename(self.filename)
        header["layout"] = [list(zone) for zone in self.layout]  # format 1 LMU files had no layout
        rest = [(t, data) for t, data in zip(self.rest_times, self.rest_data) if origin < t <= end_time]
        initial_rest = self.rest_at(origin)
        if initial_rest >= 0:
            rest.insert(0, (origin, self.rest_data[initial_rest]))
        markers = [marker for marker in self.markers if origin <= marker.time <= end_time]
        total = last - first + 1
        if same_file(filename, self.filename):
            raise ValueError("cannot replace open replay file")
        # Written to temporary file, then replaces target: existing file never left truncated on error
        temp_name = f"{filename}.part"
        try:
            with open(temp_name, "wb") as file:
                writer = ReplayWriter(file, self.frame_size, self.rate, header)
                for frame_time, frame in self.iter_frames(first, last):
                    writer.write(frame_time - origin, frame)
                    while rest and rest[0][0] <= frame_time:
                        writer.write_rest(rest[0][0] - origin, rest.pop(0)[1])
                    while markers and markers[0].time <= frame_time:
                        marker = markers.pop(0)
                        writer.write_marker(marker.time - origin, marker.kind, marker.text)
                    if progress is not None and writer.frames % EXPORT_PROGRESS_STEP == 0:
                        progress(writer.frames, total)
                writer.finish()
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, filename)
        except BaseException:
            with suppress(OSError):
                os.remove(temp_name)
            raise
        return writer.frames


class ReplayPlayer:
    """Play replay file against wall clock"""

    def __init__(self, replay: ReplayFile, clock: Callable[[], float] = time.monotonic):
        self.replay = replay
        self._clock = clock
        self._lock = threading.Lock()
        self._position = 0.0  # replay time at last anchor
        self._anchor = clock()
        self.speed = 1.0
        self.paused = False
        self.loop = True
        self.last_frame = b""  # frame of current update, read by every shared memory zone

    @property
    def position(self) -> float:
        """Current replay time (seconds)"""
        with self._lock:
            return self._current()

    def _current(self) -> float:
        position = self._position
        if not self.paused:
            position += (self._clock() - self._anchor) * self.speed
        duration = self.replay.duration
        if position > duration:
            position = position % duration if self.loop and duration > 0 else duration
        return position

    def _reanchor(self, position: float) -> None:
        self._position = position
        self._anchor = self._clock()

    def seek(self, position: float) -> None:
        """Jump to replay time"""
        with self._lock:
            self._reanchor(min(max(position, 0.0), self.replay.duration))

    def step(self, frames: int) -> None:
        """Pause and move by number of frames (negative = backward)"""
        with self._lock:
            times = self.replay.times
            index = min(max(self.replay.index_at(self._current()) + frames, 0), len(times) - 1)
            self.paused = True
            self._reanchor(times[index])

    def set_paused(self, paused: bool) -> None:
        """Pause or resume"""
        with self._lock:
            self._reanchor(self._current())
            self.paused = paused

    def set_speed(self, speed: float) -> None:
        """Set playback speed"""
        with self._lock:
            self._reanchor(self._current())
            self.speed = speed

    def current_frame(self) -> bytes:
        """Frame at current replay time

        Decoded outside player lock: decoding after backward seek takes up to KEYFRAME_INTERVAL
        frames, position reads (user interface) must not wait for it.
        """
        with self._lock:
            index = self.replay.index_at(self._current())
        self.last_frame = self.replay.frame(index)
        return self.last_frame

    def current_rest(self) -> int:
        """Index of Rest API snapshot at current replay time, -1 if none"""
        with self._lock:
            return self.replay.rest_at(self._current())


class ReplayMMap:
    """Drop-in replacement of shared memory MMapControl, fed by replay player

    Reads one zone of recorded frame (at offset). If rest_target is set, Rest API data set is
    also updated from recorded snapshots.
    """

    __slots__ = (
        "_primary", "_struct", "_buffer", "_player", "_offset", "_end", "_rest_target", "_rest_index", "update", "data",
    )

    def __init__(
        self, data_struct: Any, player: ReplayPlayer, offset: int = 0, rest_target: Any = None, primary: bool = True,
    ):
        """
        Args:
            primary: first zone updated each cycle reads new frame, others reuse it (all zones from same frame).
        """
        self._primary = primary
        self._struct = data_struct
        self._player = player
        self._offset = offset
        self._end = offset + ctypes.sizeof(data_struct)
        if self._end > player.replay.frame_size:
            raise ValueError("replay frame smaller than shared memory structure")
        self._buffer = bytearray(player.current_frame()[offset:self._end])
        self._rest_target = rest_target
        self._rest_index = -1
        self.update: Callable[[], None] = no_update
        self.data: Any = data_struct.from_buffer(self._buffer)

    @property
    def paused(self) -> bool:
        """Whether replay is paused (data held on purpose, not a frozen game)"""
        return self._player.paused

    def create(self, *_args) -> None:
        """Start feeding frames"""
        self.update = self.__update
        logger.info("replay: ACTIVE: %s", os.path.basename(self._player.replay.filename))

    def close(self) -> None:
        """Keep a final copy, same as MMapControl"""
        self.data = self._struct.from_buffer_copy(self._buffer)
        self.update = no_update

    def __update(self) -> None:
        player = self._player
        frame = player.current_frame() if self._primary or not player.last_frame else player.last_frame
        self._buffer[:] = frame[self._offset:self._end]
        if self._rest_target is not None:
            index = self._player.current_rest()
            if index != self._rest_index and index >= 0:
                apply_rest_snapshot(self._rest_target, self._player.replay.rest_data[index])
            self._rest_index = index


class RecordingSources(NamedTuple):
    """Data sources of recording

    frame: returns ctypes structure or bytes of every zone, or None if unavailable.
    rest: returns Rest API data snapshot, or None.
    active: returns False while frames should be skipped (menus, garage), None = always record.
    lap: returns current lap number (lap markers), None = no lap markers.
    info: returns track, vehicle, session info for header, read at first recorded frame.
    """

    frame: Callable[[], Any]
    rest: Callable[[], dict | None] | None = None
    active: Callable[[], bool] | None = None
    lap: Callable[[], int] | None = None
    info: Callable[[], dict] | None = None


class ReplayControl:
    """Replay & recording state, shared by API connector and user interface"""

    def __init__(self):
        self.player: ReplayPlayer | None = None
        self._rec_thread: threading.Thread | None = None
        self._rec_event = threading.Event()
        self._rec_lock = threading.Lock()  # recording started & stopped from GUI and recorder module
        self._markers: list[tuple[str, str, float]] = []
        self._markers_lock = threading.Lock()
        self.recording_file = ""
        self.recorded_frames = 0
        self.recording_elapsed = 0.0

    # Replay
    @property
    def active(self) -> bool:
        """Is replaying"""
        return self.player is not None

    def load(self, filename: str, api_name: str = "", layout: Sequence[Sequence] | None = None) -> ReplayPlayer:
        """Load replay file and play it, raise OSError or ValueError on invalid file

        Blocks while file is scanned: user interface loads in background with prepare & activate.

        Args:
            api_name: API to play replay with, checked with layout if given.
            layout: shared memory zones of API ([name, size], ...).

        Raises:
            ReplayMismatch: replay cannot be played with API.
        """
        self.unload()
        return self.activate(self.prepare(filename, api_name, layout))

    @staticmethod
    def prepare(
        filename: str, api_name: str = "", layout: Sequence[Sequence] | None = None,
        cancel: threading.Event | None = None, progress: Callable[[int, int], None] | None = None,
    ) -> ReplayFile:
        """Open & check replay file without playing it (any thread), raise OSError or ValueError on invalid file

        Args:
            api_name, layout: see load.
            cancel, progress: see ReplayFile.

        Raises:
            ReplayMismatch: replay cannot be played with API.
            ReplayLoadCancelled: cancel set while scanning, file closed.
        """
        replay_file = ReplayFile(filename, cancel, progress)
        if api_name and layout is not None:
            mismatch = replay_mismatch(replay_file, api_name, layout)
            if mismatch is not None:
                replay_file.close()
                logger.warning("replay: %s not loaded: %s", filename, mismatch)
                raise mismatch
        return replay_file

    def activate(self, replay_file: ReplayFile) -> ReplayPlayer:
        """Play prepared replay file (replaces replay being played)"""
        self.player = ReplayPlayer(replay_file)
        logger.info("replay: loaded %s (%s frames)", replay_file.filename, len(replay_file))
        return self.player

    def unload(self) -> None:
        """Leave replay mode

        File is not closed here: API keeps reading frames from player until it is restarted,
        file closes once player is released.
        """
        self.player = None

    # Recording
    @property
    def recording(self) -> bool:
        """Is recording"""
        return self._rec_thread is not None and self._rec_thread.is_alive()

    def add_marker(self, kind: str, text: str = "", ago: float = 0.0) -> bool:
        """Add marker at current recording time minus ago seconds (any thread), returns True if recording"""
        if not self.recording:
            return False
        with self._markers_lock:
            self._markers.append((kind, text, max(ago, 0.0)))
        return True

    def start_recording(
        self,
        filename: str,
        source: Callable[[], Any] | RecordingSources,
        rate: int = DEFAULT_RATE,
        rest_source: Callable[[], dict | None] | None = None,
        header_extra: dict | None = None,
    ) -> bool:
        """Record frames from source until stopped, returns False if already recording

        Args:
            source: frame source (see RecordingSources.frame), or every recording source.
            rest_source: returns Rest API data snapshot, or None.
            header_extra: source API name & zone layout.
        """
        with self._rec_lock:
            if self.recording:
                return False
            sources = source if isinstance(source, RecordingSources) else RecordingSources(source, rest_source)
            # Own stop event for each recording, a previous recorder still closing its file never resumes
            self._rec_event = threading.Event()
            with self._markers_lock:
                self._markers.clear()
            self.recording_file = filename
            self.recorded_frames = 0
            self.recording_elapsed = 0.0
            self._rec_thread = threading.Thread(
                target=self.__recording, args=(filename, sources, rate, header_extra, self._rec_event),
                daemon=True, name="Replay recorder",
            )
            self._rec_thread.start()
            return True

    def stop_recording(self) -> None:
        """Stop recording and wait for file to close"""
        with self._rec_lock:
            self._rec_event.set()
            if self._rec_thread is not None:
                self._rec_thread.join(5)
                self._rec_thread = None

    def __recording(
        self, filename: str, sources: RecordingSources, rate: int, header_extra: dict | None,
        stop_event: threading.Event,
    ) -> None:
        interval = 1 / max(rate, 1)
        last_time = 0.0
        last_rest = -REST_INTERVAL
        last_lap = None
        elapsed = 0.0
        writer = None
        try:
            with open(filename, "wb") as file:
                try:
                    while not stop_event.wait(interval):
                        if sources.active is not None and not sources.active():
                            continue
                        data = sources.frame()
                        if data is None:
                            continue
                        frame = bytes(data)
                        now = time.monotonic()
                        if writer is None:
                            extra = dict(header_extra or {})
                            if sources.info is not None:
                                extra["info"] = sources.info()
                            writer = ReplayWriter(file, len(frame), rate, extra)
                        else:
                            step = now - last_time
                            elapsed += step if step < MAX_GAP else interval  # remove skipped time
                        last_time = now
                        writer.write(elapsed, frame)
                        self.recorded_frames = writer.frames
                        self.recording_elapsed = elapsed
                        if sources.lap is not None:
                            lap = sources.lap()
                            if lap != last_lap:
                                writer.write_marker(elapsed, "lap", str(lap))
                                last_lap = lap
                        with self._markers_lock:
                            markers, self._markers = self._markers, []
                        for kind, text, ago in markers:
                            writer.write_marker(max(elapsed - ago, 0.0), kind, text)
                        if sources.rest is not None and elapsed - last_rest >= REST_INTERVAL:
                            last_rest = elapsed
                            rest = sources.rest()
                            if rest is not None:
                                writer.write_rest(elapsed, rest)
                finally:
                    if writer is not None:  # summary & trailer even after error: file stays complete
                        with suppress(OSError, ValueError):
                            writer.finish()
        except Exception:  # never leave recorder thread with unexpected error unlogged
            logger.exception("replay: recording failed, %s", filename)
        logger.info("replay: recorded %s frames to %s", self.recorded_frames, filename)
        if writer is None:  # nothing recorded (game never active)
            with suppress(OSError):
                os.remove(filename)


replay = ReplayControl()
