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
import re
from collections import deque

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
        "brake_pressure", "temp_trend", "pressure_trend", "susp_travel", "susp_static", "susp_velocity",
        "susp_offset",
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
        self.susp_travel = 0.0  # suspension compression within its range: 0 full droop, 1 bump stop
        self.susp_static = -1.0  # static position within range, -1 if unknown
        self.susp_velocity = 0.0  # compression speed, -1 fast rebound to 1 fast compression
        self.susp_offset = 0.0  # millimeters from static position, positive = compressed

    def signature(self) -> tuple:
        """Displayed state, floats rounded, so a repaint is skipped when nothing visible changed"""
        # Suspension moves continuously: finer steps, so its motion stays smooth
        return tuple(rounded(getattr(self, name), 2 if name.startswith("susp") else 1) for name in self.__slots__)


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


# Compound targets: "S=160-190/75-100; W=150-175" (pressure kPa, then optional temperature Celsius)
_rex_target = re.compile(
    r"^\s*([^=\s]+)\s*=\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)"
    r"(?:\s*/\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?))?\s*$"
)


def parse_compound_targets(text: str) -> dict[str, tuple[float, float, float | None, float | None]]:
    """Per compound symbol: (pressure min, pressure max, temperature min, temperature max)

    Invalid entries are ignored, so a typo only loses that one compound.
    """
    targets = {}
    for entry in re.split(r"[;,]", text or ""):
        matched = _rex_target.match(entry)
        if not matched:
            continue
        symbol, p_min, p_max, t_min, t_max = matched.groups()
        targets[symbol.upper()] = (
            float(p_min), float(p_max),
            float(t_min) if t_min is not None else None,
            float(t_max) if t_max is not None else None,
        )
    return targets


# Display profiles: override a group of show options at once ("Custom" keeps user values)
_DIAGNOSTICS = (
    "show_tyre_carcass_temperature", "show_tyre_load", "show_tyre_slip_angle",
    "show_wheel_camber", "show_ride_height", "show_tyre_wear_per_lap",
)
DISPLAY_PROFILES: dict[str, dict[str, bool]] = {
    "Minimal": {
        **dict.fromkeys(_DIAGNOSTICS, False),
        "show_tyre_pressure": False, "show_tyre_wear_end_stint": False, "show_tyre_compound": False,
        "show_brake_wear": False, "show_brake_pressure": False, "show_brake_migration": False,
        "show_wheel_locking": False, "show_delta_best": False, "show_laptime": False,
        "show_fuel_gauge": False, "show_energy_gauge": False, "show_stint_comparison": False,
        "show_tyre_temperature_trend": False, "show_tyre_pressure_trend": False,
    },
    "Sprint": {
        **dict.fromkeys(_DIAGNOSTICS, False),
        "show_tyre_pressure": True, "show_tyre_wear": True, "show_tyre_wear_end_stint": False,
        "show_delta_best": True, "show_laptime": True, "show_rpm_leds": True,
        "show_fuel_gauge": False, "show_energy_gauge": False, "show_stint_comparison": False,
    },
    "Endurance": {
        "show_tyre_pressure": True, "show_tyre_wear": True, "show_tyre_wear_end_stint": True,
        "show_tyre_wear_per_lap": True, "show_tyre_compound": True, "show_brake_wear": True,
        "show_fuel_gauge": True, "show_energy_gauge": True, "show_stint_comparison": True,
        "show_tyre_temperature_trend": True, "show_tyre_pressure_trend": True,
    },
}

# Secondary elements hidden by auto compact mode, when the widget is scaled down
COMPACT_HIDDEN = (
    *_DIAGNOSTICS, "show_tyre_wear_end_stint", "show_tyre_compound", "show_brake_wear",
    "show_brake_pressure", "show_caption", "show_stint_comparison",
    "show_tyre_temperature_trend", "show_tyre_pressure_trend",
)


def display_overrides(wcfg) -> dict[str, bool]:
    """Options overridden by display profile, then by auto compact mode"""
    overrides = dict(DISPLAY_PROFILES.get(wcfg["display_profile"], {}))
    threshold = wcfg["auto_compact_display_scale"]
    if 0 < wcfg["display_scale"] < threshold:
        overrides.update(dict.fromkeys(COMPACT_HIDDEN, False))
    return overrides


class SuspensionTravel:
    """Live suspension position as a fraction of its travel, and compression speed

    Travel range comes from Wheels module (filtered min & max) when available, otherwise it
    is learned from positions seen since the car changed. Speed is the position change over
    time, scaled so velocity_scale (mm/s) reads as full speed.
    """

    __slots__ = ("low", "high", "last_position", "last_time", "velocity_scale", "reference")

    def __init__(self, velocity_scale: float = 200.0):
        self.velocity_scale = max(velocity_scale, 1.0)
        self.reset()

    def reset(self):
        self.low = math.inf
        self.high = -math.inf
        self.last_position = math.nan
        self.last_time = math.nan
        self.reference = math.nan  # position at rest, averaged, when static position is unknown

    def update(self, position: float, now: float, low: float = 0.0, high: float = 0.0) -> tuple[float, float]:
        """Return (travel 0 to 1, velocity -1 to 1) for position (mm, larger = compressed)

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
        if elapsed > 0 and math.isfinite(self.last_position):
            speed = (position - self.last_position) / elapsed
            velocity = min(max(speed / self.velocity_scale, -1.0), 1.0)
        else:
            velocity = 0.0
        self.last_position = position
        self.last_time = now
        return travel, velocity

    def offset(self, position: float, static: float = 0.0) -> float:
        """Millimeters from static position (positive = compressed), 1:1 with the car

        Static position from Wheels module when known, otherwise a slow average of positions,
        which settles on the position at rest.
        """
        if not math.isfinite(position):
            return 0.0
        if math.isfinite(static) and static > 0:
            return position - static
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
