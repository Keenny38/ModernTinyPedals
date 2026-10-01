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
Replay recording from current telemetry API (manual from replay window, or automatic from recorder module)
"""

from __future__ import annotations

import logging
import os
import time

from . import realtime_state
from .api_control import api
from .replay import FILE_EXT, REPLAY_FAMILIES, RecordingSources, remove_old_replays, replay
from .setting import cfg

logger = logging.getLogger(__name__)

MANUAL_PREFIX = "replay-"
AUTO_PREFIX = "replay-auto-"  # only automatic recordings are removed over limit
SESSION_NAMES = ("Test day", "Practice", "Qualify", "Warmup", "Race")


def api_supported() -> bool:
    """Whether current API can record & replay shared memory"""
    return any(api.name in family for family in REPLAY_FAMILIES)


def recording_info() -> dict:
    """Track, vehicle & session of recording, for replay list"""
    read = api.read
    try:
        session_type = read.session.session_type()
        return {
            "track": read.session.track_name(),
            "vehicle": read.vehicle.vehicle_name(),
            "class": read.vehicle.class_name(),
            "session": SESSION_NAMES[session_type] if 0 <= session_type < len(SESSION_NAMES) else "",
        }
    except (AttributeError, TypeError, ValueError, IndexError):
        return {}


def skip_inactive_frames() -> bool:
    """Recorder module option: skip frames outside driving (menus, garage)"""
    return bool(cfg.user.setting.get("module_recorder", {}).get("enable_replay_skip_inactive_frames", True))


def start_api_recording(auto: bool = False) -> str:
    """Start recording current API to telemetry folder, return file name"""
    folder = cfg.path.telemetry or "."
    os.makedirs(folder, exist_ok=True)
    prefix = AUTO_PREFIX if auto else MANUAL_PREFIX
    filename = os.path.join(folder, time.strftime(f"{prefix}%Y-%m-%d-%H-%M-%S{FILE_EXT}"))
    sources = RecordingSources(
        frame=api.raw_data,
        rest=api.rest_data,
        active=(lambda: bool(realtime_state.active)) if skip_inactive_frames() else None,
        lap=lambda: api.read.lap.number(),
        info=recording_info,
    )
    replay.start_recording(filename, sources, header_extra=api.replay_header())
    return filename


class AutoReplay:
    """Start recording when driving starts, stop after a while outside driving

    A recording started from replay window is left alone; one stopped from replay window
    is not restarted until next driving.
    """

    def __init__(self, keep: int, stop_delay: float = 10.0):
        self.keep = max(keep, 1)
        self.stop_delay = stop_delay
        self.started = False  # recording started by this
        self.user_stopped = False
        self.inactive_since: float | None = None

    def update(self, active: bool, now: float) -> None:
        """Update with driving state"""
        if replay.active or not api_supported():
            return
        if self.started and not replay.recording:  # stopped from replay window
            self.started = False
            self.user_stopped = True
        if active:
            self.inactive_since = None
            if not replay.recording and not self.user_stopped:
                filename = start_api_recording(auto=True)
                self.started = True
                logger.info("RECORDER: automatic replay recording %s", os.path.basename(filename))
            return
        self.user_stopped = False
        if self.started:
            if self.inactive_since is None:
                self.inactive_since = now
            elif now - self.inactive_since >= self.stop_delay:
                self.stop()

    def stop(self) -> None:
        """Stop automatic recording, remove oldest automatic recordings over limit"""
        if not self.started:
            return
        self.started = False
        self.inactive_since = None
        replay.stop_recording()
        for name in remove_old_replays(cfg.path.telemetry or ".", AUTO_PREFIX, self.keep):
            logger.info("RECORDER: removed old replay %s", name)
