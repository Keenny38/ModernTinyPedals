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
Black box widget, incident recorder & event log

Pure logic, no Qt: the recorder keeps a rolling window of driving samples, freezes it when an
impact (hard deceleration) or new damage is detected, and keeps a few seconds after the trigger
so the incident can be looked at afterwards. The event log keeps a short history of notable
events (puncture, flat spot, detached wheel, damage, incident) with lap and session time.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from collections import deque
from itertools import pairwise
from typing import NamedTuple

logger = logging.getLogger(__name__)

GRAVITY = 9.80665
MIN_IMPACT_SPEED = 5.0  # m/s, deceleration below this speed is not an impact (pit stop, spin at rest)
WHEEL_NAMES = ("FL", "FR", "RL", "RR")


class Sample(NamedTuple):
    """One recorded driving sample"""

    time: float  # monotonic seconds
    speed: float  # m/s
    throttle: float  # 0 to 1
    brake: float  # 0 to 1
    gear: int
    abs_active: bool
    tc_active: bool
    slip: str  # "", "lock" or "spin" (worst of 4 wheels)


class Incident(NamedTuple):
    """Frozen recording around an incident"""

    time: float  # monotonic time of trigger
    reason: str  # "impact" or "damage"
    peak_g: float  # highest deceleration (g) in recording
    lap: int
    session_time: float
    samples: tuple[Sample, ...]


class Recorder:
    """Rolling window of samples, frozen around incidents

    Args:
        duration: seconds kept before the trigger.
        sample_interval: minimum seconds between two samples.
        deceleration_threshold: deceleration (g) that counts as an impact, 0 disables.
        post_trigger: seconds still recorded after the trigger.
        max_incidents: incidents kept, oldest dropped first.
    """

    def __init__(
        self,
        duration: float = 15.0,
        sample_interval: float = 0.05,
        deceleration_threshold: float = 4.0,
        post_trigger: float = 2.0,
        max_incidents: int = 10,
    ):
        self.duration = max(duration, 1.0)
        self.sample_interval = max(sample_interval, 0.01)
        self.deceleration_threshold = max(deceleration_threshold, 0.0)
        self.post_trigger = max(post_trigger, 0.0)
        self.samples: deque[Sample] = deque(maxlen=int(self.duration / self.sample_interval) + 1)
        self.incidents: deque[Incident] = deque(maxlen=max(max_incidents, 1))
        self.last_damage = 0.0
        self.last_trigger = -math.inf
        self.pending: tuple[float, str, int, float] | None = None  # (time, reason, lap, session time)

    def reset(self):
        """Clear rolling window (new session), keep frozen incidents"""
        self.samples.clear()
        self.pending = None
        self.last_damage = 0.0

    def add(self, sample: Sample, damage: float, lap: int = 0, session_time: float = 0.0) -> Incident | None:
        """Add sample, return a finished incident once its post trigger time has passed"""
        samples = self.samples
        if samples and sample.time - samples[-1].time < self.sample_interval - 1e-6:
            return None
        if not all(math.isfinite(value) for value in (sample.speed, sample.throttle, sample.brake, damage)):
            return None
        # Trigger: impact from speed drop since previous sample, or damage increase
        reason = ""
        if samples:
            previous = samples[-1]
            if self.deceleration_g(previous, sample) >= self.deceleration_threshold > 0 and (
                previous.speed >= MIN_IMPACT_SPEED
            ):
                reason = "impact"
        if damage > self.last_damage + 1e-6:
            reason = reason or "damage"
        self.last_damage = damage
        samples.append(sample)
        # Several triggers within one recording are the same incident
        if reason and self.pending is None and sample.time - self.last_trigger >= self.duration / 2:
            self.pending = (sample.time, reason, lap, session_time)
            self.last_trigger = sample.time
        if self.pending is not None and sample.time - self.pending[0] >= self.post_trigger:
            return self.freeze()
        return None

    def freeze(self) -> Incident | None:
        """Close pending incident with current window"""
        if self.pending is None:
            return None
        trigger_time, reason, lap, session_time = self.pending
        self.pending = None
        frozen = tuple(self.samples)
        incident = Incident(trigger_time, reason, self.peak_g(frozen), lap, session_time, frozen)
        self.incidents.append(incident)
        return incident

    @staticmethod
    def deceleration_g(previous: Sample, current: Sample) -> float:
        """Deceleration between two samples (g), 0 if accelerating"""
        elapsed = current.time - previous.time
        if elapsed <= 0:
            return 0.0
        return max(previous.speed - current.speed, 0.0) / elapsed / GRAVITY

    @classmethod
    def peak_g(cls, samples) -> float:
        """Highest deceleration (g) in samples"""
        return max(
            (cls.deceleration_g(previous, current) for previous, current in pairwise(samples)),
            default=0.0,
        )

    @property
    def last_incident(self) -> Incident | None:
        return self.incidents[-1] if self.incidents else None


class Event(NamedTuple):
    """Event log entry"""

    lap: int
    session_time: float
    text: str
    critical: bool


class EventLog:
    """Short history of notable events, newest last

    Wheel status and damage are compared with the previous update, so each event is
    logged once when it happens instead of on every update while it lasts.
    """

    def __init__(self, size: int = 5):
        self.events: deque[Event] = deque(maxlen=max(size, 1))
        self.last_status = ["", "", "", ""]
        self.last_damage = 0.0

    def add(self, lap: int, session_time: float, text: str, critical: bool = False):
        self.events.append(Event(lap, session_time, text, critical))

    def update(self, lap: int, session_time: float, statuses, damage: float, labels: dict[str, str]):
        """Log new wheel status (puncture, flat, detached) and damage increase"""
        for index, status in enumerate(statuses):
            if status and status != self.last_status[index]:
                self.add(lap, session_time, f"{labels.get(status, status.upper())} {WHEEL_NAMES[index]}",
                         status != "flat")
            self.last_status[index] = status
        if math.isfinite(damage):
            if damage > self.last_damage + 1e-6:
                self.add(lap, session_time, labels.get("damage", "DAMAGE"), damage >= 1)
            self.last_damage = damage


def format_event(event: Event) -> str:
    """"L12 04:31 PUNCT FR" (session time as minutes:seconds, hours added past one hour)"""
    seconds = max(int(event.session_time), 0) if math.isfinite(event.session_time) else 0
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    clock = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
    return f"L{max(event.lap, 0)} {clock} {event.text}"


def export_incident(incident: Incident, folder: str) -> str:
    """Save incident as JSON file, return file path ("" if failed)

    Sample times are made relative to the trigger, so the file reads -15.0 ... +2.0 seconds.
    """
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        filepath = os.path.join(folder, f"incident-{stamp}-lap{incident.lap}.json")
        data = {
            "reason": incident.reason,
            "peak_deceleration_g": round(incident.peak_g, 2),
            "lap": incident.lap,
            "session_time": round(incident.session_time, 3),
            "samples": [
                {
                    "time": round(sample.time - incident.time, 3),
                    "speed_ms": round(sample.speed, 2),
                    "throttle": round(sample.throttle, 3),
                    "brake": round(sample.brake, 3),
                    "gear": sample.gear,
                    "abs": sample.abs_active,
                    "tc": sample.tc_active,
                    "slip": sample.slip,
                }
                for sample in incident.samples
            ],
        }
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=1)
        return filepath
    except (OSError, ValueError) as error:
        logger.warning("BLACK BOX: unable to save incident: %s", error)
        return ""
