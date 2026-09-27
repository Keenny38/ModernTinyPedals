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
Preset comparison: list different options between two presets, copy values
"""

from __future__ import annotations

from typing import Any, NamedTuple

POSITION_KEYS = frozenset(("position_x", "position_y"))


class Difference(NamedTuple):
    """Option with different value"""

    section: str
    key: str
    value_a: Any
    value_b: Any


def diff_presets(preset_a: dict, preset_b: dict, ignore_position: bool = False) -> list[Difference]:
    """Different options between two (validated) presets, sorted by section & key"""
    output: list[Difference] = []
    for section in sorted(set(preset_a) | set(preset_b)):
        options_a = preset_a.get(section, {})
        options_b = preset_b.get(section, {})
        if not isinstance(options_a, dict) or not isinstance(options_b, dict):
            continue
        for key in sorted(set(options_a) | set(options_b)):
            if ignore_position and key in POSITION_KEYS:
                continue
            value_a = options_a.get(key)
            value_b = options_b.get(key)
            if value_a != value_b:
                output.append(Difference(section, key, value_a, value_b))
    return output


def copy_values(target: dict, source: dict, items: list[tuple[str, str]]) -> int:
    """Copy option values (section, key) from source to target preset, returns number copied"""
    count = 0
    for section, key in items:
        if key not in source.get(section, {}):
            continue
        target.setdefault(section, {})[key] = source[section][key]
        count += 1
    return count
