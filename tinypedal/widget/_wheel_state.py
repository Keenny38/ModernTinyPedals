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
Wheel status Widget, per-wheel state and reading priority

Split out of wheel_status so the widget module holds layout and painting only.
"""

from __future__ import annotations

# Tyre readings, in priority order: the lowest-numbered one is dropped first when the tyre
# box is too small to show them all at a readable size.
READING_COMPOUND = 0
READING_END_STINT = 1
READING_PRESSURE = 2
READING_WEAR = 3
READING_TEMPERATURE = 4
READING_STATUS = 5  # puncture or flat spot, never dropped

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
        "tyre_color", "brake_color", "warning", "status", "suspension_damage",
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
        self.suspension_damage = 0.0  # fraction


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
