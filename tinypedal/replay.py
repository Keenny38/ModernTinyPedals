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

Records raw LMU shared memory frames to a file, and plays them back through
the regular LMU API, so every widget & module can run without the game.

File format (.tpreplay):
    header line: b"TPREPLAY1 " + json (frame size, rate, created) + b"\\n"
    frames: struct FRAME_HEADER (elapsed seconds, keyframe flag, payload size) + payload
    payload: zlib of full frame (keyframe), or zlib of frame XOR previous frame.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import threading
import time
import zlib
from collections.abc import Callable
from typing import Any, BinaryIO

logger = logging.getLogger(__name__)

MAGIC = b"TPREPLAY1 "
FILE_EXT = ".tpreplay"
FRAME_HEADER = struct.Struct("<dBI")
KEYFRAME_INTERVAL = 100  # frames between full frames, bounds seeking cost
DEFAULT_RATE = 30  # recorded frames per second
SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0)


def no_update() -> None:
    """Update placeholder while replay is not feeding frames"""


def xor_bytes(data: bytes, base: bytes) -> bytes:
    """XOR two equal size byte strings"""
    size = len(data)
    return (int.from_bytes(data, "little") ^ int.from_bytes(base, "little")).to_bytes(size, "little")


class ReplayWriter:
    """Write frames to replay file"""

    def __init__(self, file: BinaryIO, frame_size: int, rate: int):
        self._file = file
        self._frame_size = frame_size
        self._last = b""
        self._count = 0
        header = {"frame_size": frame_size, "rate": rate, "created": time.time()}
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
        payload = zlib.compress(raw, 1)
        self._file.write(FRAME_HEADER.pack(elapsed, keyframe, len(payload)))
        self._file.write(payload)
        self._last = frame
        self._count += 1


class ReplayFile:
    """Read replay file, frames are kept compressed in memory"""

    def __init__(self, filename: str):
        self.filename = filename
        with open(filename, "rb") as file:
            line = file.readline()
            if not line.startswith(MAGIC):
                raise ValueError("not a TinyPedal replay file")
            header = json.loads(line[len(MAGIC):])
            self.frame_size = int(header["frame_size"])
            self.rate = int(header.get("rate", DEFAULT_RATE))
            self.times: list[float] = []
            self.keyframes: list[bool] = []
            self._payloads: list[bytes] = []
            while True:
                head = file.read(FRAME_HEADER.size)
                if len(head) < FRAME_HEADER.size:
                    break  # end of file, or truncated frame from interrupted recording
                elapsed, keyframe, size = FRAME_HEADER.unpack(head)
                payload = file.read(size)
                if len(payload) < size:
                    break
                self.times.append(elapsed)
                self.keyframes.append(bool(keyframe))
                self._payloads.append(payload)
        if not self._payloads or not self.keyframes[0]:
            raise ValueError("replay file contains no frame")
        self._index = -1
        self._frame = b""

    def __len__(self) -> int:
        return len(self._payloads)

    @property
    def duration(self) -> float:
        """Replay duration (seconds)"""
        return self.times[-1]

    def index_at(self, elapsed: float) -> int:
        """Last frame index at elapsed time"""
        lo, hi = 0, len(self.times) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.times[mid] <= elapsed:
                lo = mid
            else:
                hi = mid - 1
        return lo

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
            self._frame = zlib.decompress(self._payloads[start])
        while self._index < index:
            self._index += 1
            raw = zlib.decompress(self._payloads[self._index])
            self._frame = raw if self.keyframes[self._index] else xor_bytes(raw, self._frame)
        return self._frame


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
            return self.replay.frame(self.replay.index_at(self._current()))


class ReplayMMap:
    """Drop-in replacement of shared memory MMapControl, fed by replay player"""

    __slots__ = ("_struct", "_buffer", "_player", "update", "data")

    def __init__(self, data_struct: Any, player: ReplayPlayer):
        self._struct = data_struct
        self._player = player
        self._buffer = bytearray(player.current_frame())
        self.update: Callable[[], None] = no_update
        self.data: Any = data_struct.from_buffer(self._buffer)

    def create(self, access_mode: int = 0) -> None:
        """Start feeding frames"""
        self.update = self.__update
        logger.info("replay: ACTIVE: %s", os.path.basename(self._player.replay.filename))

    def close(self) -> None:
        """Keep a final copy, same as MMapControl"""
        self.data = self._struct.from_buffer_copy(self._buffer)
        self.update = no_update

    def __update(self) -> None:
        self._buffer[:] = self._player.current_frame()


class ReplayControl:
    """Replay & recording state, shared by API connector and user interface"""

    def __init__(self):
        self.player: ReplayPlayer | None = None
        self._rec_thread: threading.Thread | None = None
        self._rec_event = threading.Event()
        self.recording_file = ""
        self.recorded_frames = 0

    # Replay
    @property
    def active(self) -> bool:
        """Is replaying"""
        return self.player is not None

    def load(self, filename: str) -> ReplayPlayer:
        """Load replay file, raise OSError or ValueError on invalid file"""
        self.player = ReplayPlayer(ReplayFile(filename))
        logger.info("replay: loaded %s (%s frames)", filename, len(self.player.replay))
        return self.player

    def unload(self) -> None:
        """Leave replay mode"""
        self.player = None

    # Recording
    @property
    def recording(self) -> bool:
        """Is recording"""
        return self._rec_thread is not None and self._rec_thread.is_alive()

    def start_recording(self, filename: str, source: Callable[[], Any], rate: int = DEFAULT_RATE) -> None:
        """Record frames from source (returns ctypes structure or None) until stopped"""
        if self.recording:
            return
        self._rec_event.clear()
        self.recording_file = filename
        self.recorded_frames = 0
        self._rec_thread = threading.Thread(
            target=self.__recording, args=(filename, source, rate), daemon=True, name="Replay recorder"
        )
        self._rec_thread.start()

    def stop_recording(self) -> None:
        """Stop recording and wait for file to close"""
        self._rec_event.set()
        if self._rec_thread is not None:
            self._rec_thread.join(5)
            self._rec_thread = None

    def __recording(self, filename: str, source: Callable[[], Any], rate: int) -> None:
        interval = 1 / max(rate, 1)
        start = time.monotonic()
        writer = None
        try:
            with open(filename, "wb") as file:
                while not self._rec_event.wait(interval):
                    data = source()
                    if data is None:
                        continue
                    frame = bytes(data)
                    if writer is None:
                        writer = ReplayWriter(file, len(frame), rate)
                        start = time.monotonic()
                    writer.write(time.monotonic() - start, frame)
                    self.recorded_frames = writer.frames
        except (OSError, ValueError):
            logger.exception("replay: recording failed, %s", filename)
        logger.info("replay: recorded %s frames to %s", self.recorded_frames, filename)


replay = ReplayControl()
