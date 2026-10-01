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
    header line: b"TPREPLAY1 " + json (frame size, rate, created, source API, zone layout, info) + b"\\n"
    frames: struct FRAME_HEADER (elapsed seconds, frame type, payload size) + payload
    frame type 0 or 1 (keyframe): zlib of frame XOR previous frame, or of full frame (keyframe).
    frame type 2: zlib of json Rest API data snapshot (weather forecast, damage...), written when changed.
    frame type 3: json marker {"kind": "lap" or "incident"..., "text": str}.
    frame type 4: json summary {"duration", "frames"}, written when recording ends,
        followed by trailer struct TRAILER (summary frame offset, b"TPIX").
A frame is every shared memory zone back to back, as listed in header "layout" ([name, size], ...).
Frames are read from file on demand, only their position is kept in memory.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import struct
import threading
import time
import zlib
from bisect import bisect_right
from collections.abc import Callable, Iterator
from contextlib import suppress
from typing import Any, BinaryIO, NamedTuple

from .const_api import API_LMU_NAME, API_LMULEGACY_NAME, API_RF2_NAME

logger = logging.getLogger(__name__)

MAGIC = b"TPREPLAY1 "
FILE_EXT = ".tpreplay"
FRAME_HEADER = struct.Struct("<dBI")
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
    """Write frames to replay file"""

    def __init__(self, file: BinaryIO, frame_size: int, rate: int, header_extra: dict | None = None):
        self._file = file
        self._frame_size = frame_size
        self._last = b""
        self._last_rest = b""
        self._count = 0
        self._elapsed = 0.0
        header = {"frame_size": frame_size, "rate": rate, "created": time.time(), **(header_extra or {})}
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
        self._file.write(FRAME_HEADER.pack(elapsed, frame_type, len(payload)))
        self._file.write(payload)


def read_header(file: BinaryIO) -> dict:
    """Read replay header line, raise ValueError if not a replay file"""
    line = file.readline()
    if not line.startswith(MAGIC):
        raise ValueError("not a TinyPedal replay file")
    try:
        header = json.loads(line[len(MAGIC):])
    except ValueError as error:
        raise ValueError("invalid replay header") from error
    if not isinstance(header, dict) or "frame_size" not in header:
        raise ValueError("invalid replay header")
    return header


def read_summary(file: BinaryIO) -> dict:
    """Summary of complete recording from file trailer, empty if missing (interrupted recording)"""
    try:
        size = file.seek(0, os.SEEK_END)
        if size < TRAILER.size + FRAME_HEADER.size:
            return {}
        file.seek(size - TRAILER.size)
        offset, magic = TRAILER.unpack(file.read(TRAILER.size))
        if magic != TRAILER_MAGIC or offset >= size:
            return {}
        file.seek(offset)
        _, frame_type, length = FRAME_HEADER.unpack(file.read(FRAME_HEADER.size))
        if frame_type != SUMMARY_FRAME:
            return {}
        summary = json.loads(file.read(length))
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
        summary = read_summary(file)
        size = file.seek(0, os.SEEK_END)
    info = header.get("info")
    return ReplayInfo(
        filename=filename,
        created=float(header.get("created", 0.0)),
        size=size,
        duration=float(summary.get("duration", -1.0)),
        source=str(header.get("source", API_LMU_NAME)),
        info=info if isinstance(info, dict) else {},
    )


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
        except (OSError, ValueError):
            continue
    replays.sort(key=lambda item: item.created, reverse=True)
    return replays


def remove_old_replays(folder: str, prefix: str, keep: int) -> list[str]:
    """Remove oldest replay files starting with prefix over limit, return removed file names"""
    removed = []
    try:
        files = [
            os.path.join(folder, name) for name in os.listdir(folder)
            if name.startswith(prefix) and name.endswith(FILE_EXT)
        ]
        files.sort(key=os.path.getmtime)
        for old_file in files[:-max(keep, 1)]:
            os.remove(old_file)
            removed.append(os.path.basename(old_file))
    except OSError as error:
        logger.error("replay: unable to remove old replays: %s", error)
    return removed


class ReplayFile:
    """Read replay file, frames are read from file on demand"""

    def __init__(self, filename: str):
        self.filename = filename
        self._file = open(filename, "rb")  # noqa: SIM115 (kept open, frames are read on demand)
        try:
            self._scan()
        except Exception:
            self._file.close()
            raise
        self._lock = threading.Lock()
        self._index = -1
        self._frame = b""

    def _scan(self):
        file = self._file
        header = read_header(file)
        self.header = header
        self.frame_size = int(header["frame_size"])
        self.rate = int(header.get("rate", DEFAULT_RATE))
        self.created = float(header.get("created", 0.0))
        self.source = str(header.get("source", API_LMU_NAME))  # API name, older files are LMU
        info = header.get("info")
        self.info: dict = info if isinstance(info, dict) else {}
        self.layout: list[tuple[str, int]] = [
            (str(name), int(size)) for name, size in header.get("layout", [["shmm", self.frame_size]])]
        if sum(size for _, size in self.layout) != self.frame_size:
            raise ValueError("invalid zone layout")
        self.times: list[float] = []
        self.keyframes: list[bool] = []
        self._offsets: list[int] = []
        self._sizes: list[int] = []
        self.rest_times: list[float] = []
        self.rest_data: list[dict] = []
        self.markers: list[Marker] = []
        self.summary: dict = {}
        file_size = os.fstat(file.fileno()).st_size
        position = file.tell()
        while True:
            head = file.read(FRAME_HEADER.size)
            if len(head) < FRAME_HEADER.size:
                break  # end of file, or truncated frame from interrupted recording
            elapsed, frame_type, size = FRAME_HEADER.unpack(head)
            position += FRAME_HEADER.size
            if position + size > file_size:
                break
            if frame_type <= 1:
                self.times.append(elapsed)
                self.keyframes.append(bool(frame_type))
                self._offsets.append(position)
                self._sizes.append(size)
                file.seek(size, os.SEEK_CUR)
            else:
                payload = file.read(size)
                self._read_extra(elapsed, frame_type, payload)
            position += size
        if not self._offsets or not self.keyframes[0]:
            raise ValueError("replay file contains no frame")
        self.markers.sort(key=lambda marker: marker.time)

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

    def _decode(self, index: int, previous: bytes) -> bytes:
        raw = zlib.decompress(self._payload(index))
        return raw if self.keyframes[index] else xor_bytes(raw, previous)

    def frame(self, index: int) -> bytes:
        """Get decoded frame, sequential access is fast, seeking starts from nearest keyframe"""
        index = min(max(index, 0), len(self) - 1)
        if index == self._index:
            return self._frame
        if index < self._index or index - self._index > KEYFRAME_INTERVAL:
            start = index
            while not self.keyframes[start]:
                start -= 1
            self._index = start
            self._frame = self._decode(start, b"")
        while self._index < index:
            self._index += 1
            self._frame = self._decode(self._index, self._frame)
        return self._frame

    def iter_frames(self, first: int, last: int) -> Iterator[tuple[float, bytes]]:
        """Decoded frames (time, frame) of index range, independent of playback position"""
        start = first
        while not self.keyframes[start]:
            start -= 1
        frame = b""
        for index in range(start, last + 1):
            frame = self._decode(index, frame)
            if index >= first:
                yield self.times[index], frame

    def export(self, filename: str, start: float, end: float) -> int:
        """Save part of replay (start to end seconds) to new file, return number of frames"""
        first, last = self.index_at(start), self.index_at(end)
        if last < first:
            first, last = last, first
        origin = self.times[first]
        end_time = self.times[last]
        header = {key: value for key, value in self.header.items() if key not in ("frame_size", "rate", "created")}
        header["created"] = self.created + origin
        header["trimmed_from"] = os.path.basename(self.filename)
        rest = [(t, data) for t, data in zip(self.rest_times, self.rest_data) if origin < t <= end_time]
        initial_rest = self.rest_at(origin)
        if initial_rest >= 0:
            rest.insert(0, (origin, self.rest_data[initial_rest]))
        markers = [marker for marker in self.markers if origin <= marker.time <= end_time]
        with open(filename, "wb") as file:
            writer = ReplayWriter(file, self.frame_size, self.rate, header)
            for frame_time, frame in self.iter_frames(first, last):
                writer.write(frame_time - origin, frame)
                while rest and rest[0][0] <= frame_time:
                    writer.write_rest(rest[0][0] - origin, rest.pop(0)[1])
                while markers and markers[0].time <= frame_time:
                    marker = markers.pop(0)
                    writer.write_marker(marker.time - origin, marker.kind, marker.text)
            writer.finish()
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
        """Frame at current replay time"""
        with self._lock:
            self.last_frame = self.replay.frame(self.replay.index_at(self._current()))
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

    def load(self, filename: str) -> ReplayPlayer:
        """Load replay file, raise OSError or ValueError on invalid file"""
        self.unload()
        self.player = ReplayPlayer(ReplayFile(filename))
        logger.info("replay: loaded %s (%s frames)", filename, len(self.player.replay))
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
    ) -> None:
        """Record frames from source until stopped

        Args:
            source: frame source (see RecordingSources.frame), or every recording source.
            rest_source: returns Rest API data snapshot, or None.
            header_extra: source API name & zone layout.
        """
        if self.recording:
            return
        sources = source if isinstance(source, RecordingSources) else RecordingSources(source, rest_source)
        self._rec_event.clear()
        with self._markers_lock:
            self._markers.clear()
        self.recording_file = filename
        self.recorded_frames = 0
        self.recording_elapsed = 0.0
        self._rec_thread = threading.Thread(
            target=self.__recording, args=(filename, sources, rate, header_extra),
            daemon=True, name="Replay recorder",
        )
        self._rec_thread.start()

    def stop_recording(self) -> None:
        """Stop recording and wait for file to close"""
        self._rec_event.set()
        if self._rec_thread is not None:
            self._rec_thread.join(5)
            self._rec_thread = None

    def __recording(self, filename: str, sources: RecordingSources, rate: int, header_extra: dict | None) -> None:
        interval = 1 / max(rate, 1)
        last_time = 0.0
        last_rest = -REST_INTERVAL
        last_lap = None
        elapsed = 0.0
        writer = None
        try:
            with open(filename, "wb") as file:
                while not self._rec_event.wait(interval):
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
                if writer is not None:
                    writer.finish()
        except (OSError, ValueError):
            logger.exception("replay: recording failed, %s", filename)
        logger.info("replay: recorded %s frames to %s", self.recorded_frames, filename)
        if writer is None:  # nothing recorded (game never active)
            with suppress(OSError):
                os.remove(filename)


replay = ReplayControl()
