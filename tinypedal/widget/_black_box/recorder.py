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

import csv
import json
import logging
import math
import os
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from typing import NamedTuple

logger = logging.getLogger(__name__)

GRAVITY = 9.80665
MIN_IMPACT_SPEED = 5.0  # m/s, deceleration below this speed is not an impact (pit stop, spin at rest)
# Deceleration measured over this window (seconds): one ~20 ms telemetry step is noisy enough to
# read 4 g under normal braking, a real impact stays far above the threshold over 150 ms
DECELERATION_WINDOW = 0.15
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
    steering: float = 0.0  # steering input, -1 left to 1 right
    slips: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)  # slip ratio per wheel
    loads: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)  # tyre load per wheel (Newtons)


class Incident(NamedTuple):
    """Frozen recording around an incident"""

    time: float  # monotonic time of trigger
    reason: str  # "impact" (reported by game), "decel" (hard speed drop) or "damage"
    peak_g: float  # highest deceleration (g) in recording
    lap: int
    session_time: float
    samples: tuple[Sample, ...]
    direction: str = ""  # arrow toward the impact reported by game, "" if unknown


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
        damage_threshold: float = 0.0,
    ):
        self.duration = max(duration, 1.0)
        self.sample_interval = max(sample_interval, 0.01)
        self.deceleration_threshold = max(deceleration_threshold, 0.0)
        self.post_trigger = max(post_trigger, 0.0)
        self.damage_threshold = max(damage_threshold, 1e-6)  # smaller damage increase is ignored
        self.samples: deque[Sample] = deque(maxlen=int(self.duration / self.sample_interval) + 1)
        self.incidents: deque[Incident] = deque(maxlen=max(max_incidents, 1))
        self.last_damage = 0.0
        self.last_trigger = -math.inf
        self.pending: tuple[float, str, int, float] | None = None  # (time, reason, lap, session time)
        self.direction = ""  # direction of the pending impact

    def reset(self) -> Incident | None:
        """Clear rolling window (new session), keep frozen incidents

        An incident still recording its post trigger seconds is closed first, not lost.
        """
        incident = self.freeze()
        self.samples.clear()
        self.last_damage = 0.0
        return incident

    def add(
        self, sample: Sample, damage: float, lap: int = 0, session_time: float = 0.0, impact: bool = False,
        direction: str = "",
    ) -> Incident | None:
        """Add sample, return a finished incident once its post trigger time has passed

        Args:
            impact: game reported a new impact (contact with car or wall) since last sample.
        """
        samples = self.samples
        if samples and sample.time - samples[-1].time < self.sample_interval - 1e-6:
            return None
        if not all(math.isfinite(value) for value in (sample.speed, sample.throttle, sample.brake, damage)):
            return None
        # Trigger: impact reported by game, hard speed drop over the window, or damage increase
        reason = "impact" if impact else ""
        if not reason and samples:
            previous = self.window_start(sample.time)
            if previous is not None and self.deceleration_g(previous, sample) >= self.deceleration_threshold > 0 and (
                previous.speed >= MIN_IMPACT_SPEED
            ):
                reason = "decel"
        if damage > self.last_damage + self.damage_threshold:
            reason = reason or "damage"
            self.last_damage = damage
        elif damage < self.last_damage:  # repaired, or new session
            self.last_damage = damage
        samples.append(sample)
        # Several triggers within one recording are the same incident
        if reason and self.pending is None and sample.time - self.last_trigger >= self.duration / 2:
            self.pending = (sample.time, reason, lap, session_time)
            self.direction = direction if impact else ""
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
        incident = Incident(trigger_time, reason, self.peak_g(frozen), lap, session_time, frozen, self.direction)
        self.incidents.append(incident)
        return incident

    def window_start(self, now: float) -> Sample | None:
        """Newest sample at least DECELERATION_WINDOW old, None if none is yet"""
        for previous in reversed(self.samples):
            if now - previous.time >= DECELERATION_WINDOW - 1e-6:
                return previous
        return None

    @staticmethod
    def deceleration_g(previous: Sample, current: Sample) -> float:
        """Deceleration between two samples (g), 0 if accelerating"""
        elapsed = current.time - previous.time
        if elapsed <= 0:
            return 0.0
        return max(previous.speed - current.speed, 0.0) / elapsed / GRAVITY

    @classmethod
    def peak_g(cls, samples) -> float:
        """Highest deceleration (g) in samples, each measured over DECELERATION_WINDOW"""
        peak = 0.0
        start = 0
        for current in samples:
            while start + 1 < len(samples) and current.time - samples[start + 1].time >= DECELERATION_WINDOW - 1e-6:
                start += 1
            previous = samples[start]
            if current.time - previous.time >= DECELERATION_WINDOW - 1e-6:
                peak = max(peak, cls.deceleration_g(previous, current))
        return peak

    @property
    def last_incident(self) -> Incident | None:
        return self.incidents[-1] if self.incidents else None

    def previous_incident(self, incident: Incident) -> Incident | None:
        """Incident recorded just before this one, None if it is the oldest"""
        position = index_of(self.incidents, incident)
        return self.incidents[position - 1] if position > 0 else None


def index_of(items, item) -> int:
    """Position of this very object (identity, not equality: incidents hold hundreds of samples), -1 if absent"""
    for position, value in enumerate(items):
        if value is item:
            return position
    return -1


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

    def __init__(self, size: int = 5, damage_threshold: float = 0.0):
        self.events: deque[Event] = deque(maxlen=max(size, 1))
        self.last_status = ["", "", "", ""]
        self.last_damage = 0.0
        self.damage_threshold = max(damage_threshold, 1e-6)  # smaller damage increase is not logged

        self.last_values: dict[str, float] = {}  # race readings of last update, see rose

    def reset(self):
        """New session: forget last wheel status, damage & race readings, keep logged events"""
        self.last_status = ["", "", "", ""]
        self.last_damage = 0.0
        self.last_values.clear()

    def rose(self, key: str, value: float, step: float = 0.0) -> bool:
        """Reading went up by more than step since last update (first reading only sets the reference)"""
        last = self.last_values.get(key)
        if not math.isfinite(value):
            return False
        self.last_values[key] = value
        return last is not None and value > last + step

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
            if damage > self.last_damage + self.damage_threshold:
                self.add(lap, session_time, labels.get("damage", "DAMAGE"), damage >= 1)
                self.last_damage = damage
            elif damage < self.last_damage:  # repaired, or new session
                self.last_damage = damage


class RaceReadings(NamedTuple):
    """Race readings logged when they change, None when not logged"""

    yellow: bool | None = None  # yellow flag in any sector
    blue: bool | None = None  # blue flag for player
    in_pits: bool | None = None
    penalties: int | None = None
    cut_points: float | None = None  # track limits points
    limit_points: float = 0.0  # track limits points per penalty, 0 if unknown
    oil_hot: bool | None = None
    water_hot: bool | None = None
    oil: float = 0.0  # Celsius
    water: float = 0.0


def log_race_events(log: EventLog, lap: int, session_time: float, readings: RaceReadings,
                    labels: dict[str, str], temperature=lambda value: f"{value:.0f}"):
    """Log flags, pit lane entry & exit, penalties, track limits and engine overheat once each time they start"""
    def add(text: str, critical: bool = False):
        log.add(lap, session_time, text, critical)

    if readings.yellow is not None and log.rose("yellow", readings.yellow):
        add(labels.get("yellow", "YELLOW"))
    if readings.blue is not None and log.rose("blue", readings.blue):
        add(labels.get("blue", "BLUE"))
    if readings.in_pits is not None:
        if log.rose("pit_in", readings.in_pits):
            add(labels.get("pit_in", "PIT IN"))
        if log.rose("pit_out", not readings.in_pits):
            add(labels.get("pit_out", "PIT OUT"))
    if readings.penalties is not None and log.rose("penalties", readings.penalties):
        add(f"{labels.get('penalty', 'PENALTY')} {readings.penalties}", True)
    if readings.cut_points is not None and log.rose("cut_points", readings.cut_points, 0.01):
        limit = f"/{readings.limit_points:g}" if readings.limit_points > 0 else ""
        add(f"{labels.get('track_limits', 'LIMITS')} {readings.cut_points:g}{limit}",
            readings.limit_points > 0 and readings.cut_points >= readings.limit_points)
    for key, hot, value in (("oil", readings.oil_hot, readings.oil), ("water", readings.water_hot, readings.water)):
        if hot is not None and log.rose(f"{key}_hot", hot):
            add(f"{labels.get(key, key.upper())} {labels.get('overheat', 'HOT')} {temperature(value)}", True)


def format_event(event: Event) -> str:
    """"L12 04:31 PUNCT FR" (session time as minutes:seconds, hours added past one hour)"""
    seconds = max(int(event.session_time), 0) if math.isfinite(event.session_time) else 0
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    clock = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
    return f"L{max(event.lap, 0)} {clock} {event.text}"


EXPORT_FORMATS = ("JSON", "CSV", "Both")


def incident_rows(incident: Incident) -> list[dict]:
    """Samples as flat rows, times relative to the trigger (-15.0 ... +2.0 seconds)"""
    rows = []
    for sample in incident.samples:
        row = {
            "time": round(sample.time - incident.time, 3),
            "speed_ms": round(sample.speed, 2),
            "throttle": round(sample.throttle, 3),
            "brake": round(sample.brake, 3),
            "steering": round(sample.steering, 3),
            "gear": sample.gear,
            "abs": sample.abs_active,
            "tc": sample.tc_active,
            "slip": sample.slip,
        }
        for name, slip, load in zip(WHEEL_NAMES, sample.slips, sample.loads):
            row[f"slip_ratio_{name.lower()}"] = round(slip, 3)
            row[f"load_n_{name.lower()}"] = round(load)
        rows.append(row)
    return rows


def export_incident(incident: Incident, folder: str, export_format: str = "JSON") -> str:
    """Save incident as JSON and/or CSV file, return last file path ("" if failed)

    CSV opens directly in a spreadsheet or telemetry tool, JSON keeps the incident summary.
    """
    try:
        os.makedirs(folder, exist_ok=True)
        base = unique_base(folder, f"incident-{time.strftime('%Y%m%d-%H%M%S')}-lap{incident.lap}")
        rows = incident_rows(incident)
        filepath = ""
        if export_format in ("JSON", "Both"):
            filepath = f"{base}.json"
            data = {
                "reason": incident.reason,
                "direction": incident.direction,
                "peak_deceleration_g": round(incident.peak_g, 2),
                "lap": incident.lap,
                "session_time": round(incident.session_time, 3),
                "samples": rows,
            }
            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=1)
        if export_format in ("CSV", "Both") and rows:
            filepath = f"{base}.csv"
            with open(filepath, "w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        return filepath
    except (OSError, ValueError) as error:
        logger.warning("BLACK BOX: unable to save incident: %s", error)
        return ""


def unique_base(folder: str, name: str) -> str:
    """File path without extension, numbered when an export of the same second already uses it"""
    base = os.path.join(folder, name)
    number = 1
    while any(os.path.exists(f"{base}{ext}") for ext in (".json", ".csv")):
        number += 1
        base = os.path.join(folder, f"{name}-{number}")
    return base


class ExportQueue:
    """Saves incidents on a background thread: writing files never stalls the widget update"""

    def __init__(self):
        self.executor: ThreadPoolExecutor | None = None

    def submit(self, incident: Incident, folder: str, export_format: str) -> Future:
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="BlackBoxExport")
        return self.executor.submit(export_incident, incident, folder, export_format)


EXPORT_QUEUE = ExportQueue()  # one worker: exports of the same second get numbered names in turn


def open_folder(folder: str) -> bool:
    """Open folder in the file manager, created if missing"""
    try:
        os.makedirs(folder, exist_ok=True)
        if hasattr(os, "startfile"):  # Windows
            os.startfile(folder)  # pylint: disable=no-member
            return True
    except OSError as error:
        logger.warning("BLACK BOX: unable to open incident folder: %s", error)
        return False
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


class IncidentBrowse:
    """Requests to show the next older incident, from the black_box_next_incident hotkey

    The hotkey runs outside the widget: it only counts requests, the widget picks them up.
    """

    requests = 0


def request_next_incident():
    IncidentBrowse.requests += 1
