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
Black box widget, per-wheel state, reading priority and pure helpers (trend, stint, profiles)
"""

from __future__ import annotations

import math
from collections import deque

from ...template.widget.black_box_ui import (  # noqa: F401  re-exported for widget & tests
    COMPACT_HIDDEN,
    DISPLAY_PROFILES,
    class_target,
    display_overrides,
    parse_class_targets,
    parse_compound_targets,
)

# Tyre readings, in priority order: the lowest-numbered one is dropped first when the tyre
# box is too small to show them all at a readable size. The diagnostic readings sit below the
# ones a driver watches lap to lap, so enabling one never pushes out temperature or pressure.
READING_RIDE_HEIGHT = 0
READING_CAMBER = 1
READING_SLIP_ANGLE = 2
READING_LOAD = 3
READING_CARCASS = 4
READING_WEAR_PER_LAP = 5
READING_COMPOUND = 6
READING_END_STINT = 7
READING_PRESSURE = 8
READING_WEAR = 9
READING_TEMPERATURE = 10
READING_STATUS = 11  # puncture or flat spot, never dropped

# Several readings are percentages or degrees, so each carries a one-character prefix to tell
# them apart in a box only wide enough for four or five characters.
PREFIX_CAMBER = "C"
PREFIX_SLIP_ANGLE = "S"
PREFIX_LOAD = "L"
PREFIX_CARCASS = "K"
PREFIX_WEAR_PER_LAP = "▼"  # down arrow: tread lost per lap
PREFIX_RIDE_HEIGHT = "H"

# A reading below this fraction of a line height is no longer legible at a glance
MIN_READING_SCALE = 0.62

NO_STATUS = (False, False, False, False)
LAPS_LABEL = "lap"  # short unit for estimated laps left

NEUTRAL_COLOR = "#444444"


class WheelState:
    """Drawing state of one wheel"""

    __slots__ = (
        "steer", "tread", "tread_end", "tread_end_known", "tyre_temp", "ico_colors", "brake_temp",
        "brake_wear", "brake_wear_known", "pressure", "compound",
        "tyre_color", "brake_color", "warning", "status",
        "camber", "slip_angle", "load_ratio", "carcass_temp", "wear_per_lap", "ride_height",
        "brake_pressure", "temp_trend", "pressure_trend", "brake_trend", "load", "susp_travel", "susp_static", "susp_velocity",
        "susp_offset", "susp_wheel_offset", "susp_bump", "susp_airborne", "susp_estimated", "susp_damage",
    )

    def __init__(self):
        self.steer = 0.0  # displayed wheel angle (degrees, positive = right)
        self.tread = 100.0  # remaining tyre tread (percent)
        self.tread_end = 0.0  # estimated remaining tread at end of stint (percent)
        self.tread_end_known = False  # estimate needs Wheels & Fuel module data
        self.brake_wear = 100.0  # remaining brake thickness (percent)
        self.brake_wear_known = False  # brake thickness needs Wheels module data
        self.compound = ""  # tyre compound symbol
        self.tyre_temp = 0.0
        self.ico_colors = (NEUTRAL_COLOR,) * 3  # left to right bands
        self.brake_temp = 0.0
        self.pressure = 0.0  # kPa
        self.tyre_color = NEUTRAL_COLOR
        self.brake_color = NEUTRAL_COLOR
        self.warning = ""  # "", "lock", "spin"
        self.status = ""  # "", "detached", "puncture", "flat"
        self.camber = 0.0  # degrees, negative = top of wheel leaning inward
        self.slip_angle = 0.0  # degrees
        self.load_ratio = 0.0  # share of the car's total tyre load (percent)
        self.carcass_temp = 0.0  # Celsius
        self.wear_per_lap = 0.0  # estimated tread lost over a full lap (percent)
        self.ride_height = 0.0  # millimeters
        self.brake_pressure = 0.0  # percent of maximum
        self.temp_trend = 0  # tyre temperature: 1 rising, -1 falling, 0 steady or unknown
        self.pressure_trend = 0  # tyre pressure: same as above
        self.brake_trend = 0  # brake disc temperature: same as above
        self.load = 0.0  # tyre load (Newtons)
        self.susp_travel = 0.0  # suspension compression within its range: 0 full droop, 1 bump stop
        self.susp_static = -1.0  # static position within range, -1 if unknown
        self.susp_velocity = 0.0  # damper speed (mm/s), positive = compression, negative = rebound
        self.susp_offset = 0.0  # spring: millimeters from static position, positive = compressed
        self.susp_wheel_offset = 0.0  # wheel: millimeters from static position (spring / motion ratio)
        self.susp_bump = False  # bump stop reached (force above spring line)
        self.susp_airborne = False  # wheel in the air (no tyre load)
        self.susp_estimated = True  # static position unknown: offset from an estimated rest position
        self.susp_damage = 0.0  # suspension damage (fraction), 0 intact, 1 totaled

    def signature(self) -> tuple:
        """Displayed state, floats rounded, so a repaint is skipped when nothing visible changed"""
        # Suspension moves continuously: finer steps, so its motion stays smooth
        return tuple(rounded(getattr(self, name), 0 if name == "susp_velocity" else 2 if name.startswith("susp") else 1) for name in self.__slots__)


def rounded(value, digits: int = 1):
    """Float rounded for change detection, unchanged if not finite or not a float"""
    if isinstance(value, float) and math.isfinite(value):
        return round(value, digits)
    return value


def fit_readings(lines: list, usable: float, line_height: float) -> list:
    """Drop the least important tyre readings until the rest fit at a readable size

    Enabling every reading at once would otherwise squeeze them all below the point
    where they can be read at a glance, which is worse than showing fewer of them.
    """
    min_height = line_height * MIN_READING_SCALE
    while len(lines) > 1:
        total = sum(line[3] for line in lines)
        if usable * min(line[3] for line in lines) / total >= min_height:
            break
        lines.pop(min(range(len(lines)), key=lambda index: lines[index][0]))
    return lines


def level_text(name: str, *levels: int) -> str:
    """Indicator text with available levels, ex. "TC 5/3/2" (TC, cut, slip)"""
    available = [str(level) for level in levels if level >= 0]
    return f"{name} {'/'.join(available)}" if available else name


# Trend arrows appended to a reading
TREND_SYMBOLS = {1: "↑", -1: "↓", 0: ""}


class Trend:
    """Rising / falling detection over a time window (seconds)

    Compares the newest value with the oldest one still inside the window. Needs at least
    half a window of history, so a trend is never shown right after a reset.
    """

    __slots__ = ("window", "threshold", "samples")

    def __init__(self, window: float, threshold: float):
        self.window = max(window, 0.5)
        self.threshold = max(threshold, 0.001)
        self.samples: deque[tuple[float, float]] = deque()

    def reset(self):
        self.samples.clear()

    def update(self, now: float, value: float, valid: bool = True) -> int:
        """Add sample, return 1 rising, -1 falling, 0 steady or not enough history"""
        samples = self.samples
        if not valid:
            samples.clear()
            return 0
        samples.append((now, value))
        while len(samples) > 1 and now - samples[1][0] >= self.window:
            samples.popleft()
        oldest_time, oldest_value = samples[0]
        if now - oldest_time < self.window * 0.5:
            return 0
        diff = value - oldest_value
        if diff >= self.threshold:
            return 1
        if diff <= -self.threshold:
            return -1
        return 0


class SteerConvention:
    """How the game signs wheel angles, learned from steering input

    Wheel toe may be signed in the vehicle frame (both front wheels same sign when steering) or
    per wheel as toe-in (left & right opposite), and positive may mean left or right. Once
    STEER_VOTES steered samples agree, angles are turned into screen angles (positive = right).
    """

    __slots__ = ("mirror", "same", "invert", "keep")

    def __init__(self):
        self.reset()

    def reset(self):
        self.mirror = self.same = self.invert = self.keep = 0

    def update(self, front_left: float, front_right: float, steering: float):
        """Vote with front wheel angles (degrees) and steering input (-1 left to 1 right)"""
        if not (math.isfinite(front_left) and math.isfinite(front_right) and math.isfinite(steering)):
            return
        if abs(steering) < STEER_MIN_INPUT or abs(front_left) < STEER_MIN_ANGLE or abs(front_right) < STEER_MIN_ANGLE:
            return  # straight: static toe only, too small to tell
        if front_left * front_right < 0:
            self.mirror += 1
        else:
            self.same += 1
        if front_left * steering < 0:
            self.invert += 1
        else:
            self.keep += 1

    @property
    def mirrored(self) -> bool:
        """Right side wheels signed the other way (toe-in per wheel)"""
        return self.mirror >= STEER_VOTES and self.mirror > self.same

    @property
    def inverted(self) -> bool:
        """Positive angle means left"""
        return self.invert >= STEER_VOTES and self.invert > self.keep

    def screen_angle(self, index: int, angle: float) -> float:
        """Wheel angle on screen (degrees, positive = right) for game angle of wheel index"""
        if self.mirrored and index % 2:
            angle = -angle
        return -angle if self.inverted else angle


class StintTracker:
    """Average tread wear per lap and tyre pressure of the current and previous stint

    A stint ends when the car enters the pits after having driven, so its averages
    become the reference the next stint is compared with.
    """

    __slots__ = ("wear_sum", "wear_count", "pressure_sum", "pressure_count", "previous")

    def __init__(self):
        self.wear_sum = self.pressure_sum = 0.0
        self.wear_count = self.pressure_count = 0
        self.previous: tuple[float, float] | None = None

    def update(self, in_pits: bool, wear_per_lap: float, pressure: float):
        """Add a sample while driving, close the stint on entering the pits"""
        if in_pits:
            if self.wear_count or self.pressure_count:
                self.previous = self.current()
                self.wear_sum = self.pressure_sum = 0.0
                self.wear_count = self.pressure_count = 0
            return
        if wear_per_lap > 0:
            self.wear_sum += wear_per_lap
            self.wear_count += 1
        if pressure > 0:
            self.pressure_sum += pressure
            self.pressure_count += 1

    def current(self) -> tuple[float, float]:
        """(wear per lap, pressure) averages of current stint, 0 if no sample yet"""
        wear = self.wear_sum / self.wear_count if self.wear_count else 0.0
        pressure = self.pressure_sum / self.pressure_count if self.pressure_count else 0.0
        return wear, pressure


# Damper speed: finite difference of ~50 Hz telemetry is noisy, smoothed over this time (seconds)
DAMPER_FILTER_TIME = 0.06
# Tint reached at the low / high speed damper knee: low speed (body roll & pitch) stays a light
# tint, high speed (kerbs & bumps) reaches the full color
LOW_SPEED_TINT = 0.4
# Bump stop: spring line learned below this fraction of the travel seen, from this many samples
BUMP_LEARN_FRACTION = 0.6
BUMP_MIN_SAMPLES = 40
BUMP_DECAY = 0.999  # old samples fade out, so a setup change is learned again
STEER_VOTES = 15  # steered samples needed to settle how the game signs wheel angles
STEER_MIN_INPUT = 0.15  # steering input (fraction) that counts as steering
STEER_MIN_ANGLE = 1.0  # degrees, above static toe
AIRBORNE_LOAD = 50.0  # Newtons, tyre load below this with the car moving: wheel in the air


def damper_tint(velocity: float, low_speed: float, full_speed: float) -> float:
    """Tint amount (0 to 1) for a damper speed (mm/s), two zones like a real damper

    Low speed (below low_speed, body motion) is tinted up to LOW_SPEED_TINT, high speed
    (kerbs, bumps) from there to full tint at full_speed.
    """
    speed = abs(velocity) if math.isfinite(velocity) else 0.0
    low_speed = max(low_speed, 1.0)
    if speed <= low_speed:
        return LOW_SPEED_TINT * speed / low_speed
    return LOW_SPEED_TINT + (1 - LOW_SPEED_TINT) * min((speed - low_speed) / max(full_speed - low_speed, 1.0), 1.0)


class SuspensionTravel:
    """Live suspension position as a fraction of its travel, and damper speed

    Travel range comes from Wheels module (filtered min & max) when available, otherwise it
    is learned from positions seen since the car changed. Damper speed is the position change
    over time (mm/s), smoothed over DAMPER_FILTER_TIME.
    """

    __slots__ = ("low", "high", "last_position", "last_time", "velocity", "reference", "estimated")

    def __init__(self):
        self.reset()

    def reset(self):
        self.low = math.inf
        self.high = -math.inf
        self.last_position = math.nan
        self.last_time = math.nan
        self.velocity = 0.0
        self.reference = math.nan  # position at rest, averaged, when static position is unknown
        self.estimated = True  # offset measured from an estimated rest position

    def update(self, position: float, now: float, low: float = 0.0, high: float = 0.0) -> tuple[float, float]:
        """Return (travel 0 to 1, damper speed mm/s) for position (mm, larger = compressed)

        Args:
            position: suspension deflection (mm).
            now: time (seconds).
            low, high: travel range from Wheels module, ignored unless high > low.
        """
        if not math.isfinite(position):
            return 0.0, 0.0
        self.low = min(self.low, position)
        self.high = max(self.high, position)
        if not (math.isfinite(low) and math.isfinite(high) and high - low > 1.0):
            low, high = self.low, self.high
        span = high - low
        travel = min(max((position - low) / span, 0.0), 1.0) if span > 1.0 else 0.5
        elapsed = now - self.last_time
        if 0 < elapsed < 0.5 and math.isfinite(self.last_position):
            speed = (position - self.last_position) / elapsed
            self.velocity += (speed - self.velocity) * (1 - math.exp(-elapsed / DAMPER_FILTER_TIME))
        else:  # first sample, or a gap (pause): no speed
            self.velocity = 0.0
        self.last_position = position
        self.last_time = now
        return travel, self.velocity

    def offset(self, position: float, static: float = 0.0) -> float:
        """Millimeters from static position (positive = compressed), 1:1 with the car

        Static position from Wheels module when known, otherwise a slow average of positions,
        which settles on the position at rest (estimated is then True).
        """
        if not math.isfinite(position):
            return 0.0
        if math.isfinite(static) and static > 0:
            self.estimated = False
            return position - static
        self.estimated = True
        if math.isfinite(self.reference):
            self.reference += (position - self.reference) * 0.002
        else:
            self.reference = position
        return position - self.reference

    def ratio(self, position: float, low: float = 0.0, high: float = 0.0) -> float:
        """Fraction of travel for a position (static mark), -1 if unknown"""
        if not (math.isfinite(low) and math.isfinite(high) and high - low > 1.0):
            low, high = self.low, self.high
        if not (math.isfinite(position) and high - low > 1.0) or position <= 0:
            return -1.0
        return min(max((position - low) / (high - low), 0.0), 1.0)


def wheel_offset(spring_offset: float, motion_ratio: float) -> float:
    """Wheel travel (mm) from spring travel: the spring moves motion_ratio times the wheel

    Unknown or implausible ratio (not learned yet) keeps spring travel.
    """
    if math.isfinite(motion_ratio) and 0.2 <= motion_ratio <= 2.0:
        return spring_offset / motion_ratio
    return spring_offset


class BumpStop:
    """Bump stop contact, from suspension (pushrod) force

    A spring alone gives a force growing linearly with deflection. That line is learned from
    samples at low damper speed (little damper force) in the lower part of the travel seen.
    Once the bump rubber is reached the force rises well above the line: that is the contact,
    not a fraction of some travel range.
    """

    __slots__ = ("weight", "sx", "sy", "sxx", "sxy", "count", "low", "high")

    def __init__(self):
        self.reset()

    def reset(self):
        self.weight = self.sx = self.sy = self.sxx = self.sxy = 0.0
        self.count = 0
        self.low = math.inf
        self.high = -math.inf

    def line(self) -> tuple[float, float] | None:
        """(force at 0 mm, spring rate N/mm) of learned spring line, None if not learned yet"""
        if self.count < BUMP_MIN_SAMPLES:
            return None
        denominator = self.weight * self.sxx - self.sx * self.sx
        if denominator <= 1e-9:
            return None
        rate = (self.weight * self.sxy - self.sx * self.sy) / denominator
        if rate <= 0:
            return None
        return (self.sy - rate * self.sx) / self.weight, rate

    def update(self, position: float, force: float, velocity: float, low_speed: float, margin: float) -> bool:
        """Learn spring line, return True while force is above it by more than margin (fraction)"""
        if not (math.isfinite(position) and math.isfinite(force) and math.isfinite(velocity)):
            return False
        self.low = min(self.low, position)
        self.high = max(self.high, position)
        span = self.high - self.low
        if span <= 2.0:
            return False
        upper = position > self.low + span * BUMP_LEARN_FRACTION
        slow = abs(velocity) <= low_speed
        if slow and not upper:
            self.weight = self.weight * BUMP_DECAY + 1
            self.sx = self.sx * BUMP_DECAY + position
            self.sy = self.sy * BUMP_DECAY + force
            self.sxx = self.sxx * BUMP_DECAY + position * position
            self.sxy = self.sxy * BUMP_DECAY + position * force
            self.count += 1
        # Damper force hides the spring force at high damper speed: only judged up to twice low speed
        if not upper or abs(velocity) > low_speed * 2:
            return False
        line = self.line()
        if line is None:
            return False
        predicted = line[0] + line[1] * position
        return predicted > 0 and force > predicted * (1 + max(margin, 0.0))
