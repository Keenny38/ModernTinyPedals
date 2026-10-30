#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
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
Global font override (Settings page, Global Font Override category): font of every overlay changed at once

Pure functions (no Qt): the changes a choice makes to a preset, a preview of the font sizes it gives,
and the changes applied / undone. Choices: font name & weight ("no change" or a value), font size &
vertical offset added (bounded, see template.option_limits), auto font offset ("no change", "enable",
"disable"). A choice is applied once: the page puts its fields back to "no change" after Apply.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

from ... import regex_pattern as rxp
from ...template.option_limits import clamp_to_limit

NO_CHANGE = "no change"
AUTO_OFFSET_CHOICES = (NO_CHANGE, "enable", "disable")


class FontChoice(NamedTuple):
    """Global font override choices (neutral values change nothing)"""

    font_name: str = NO_CHANGE
    font_size_addend: int = 0
    font_weight: str = NO_CHANGE
    enable_auto_font_offset: str = NO_CHANGE
    font_offset_vertical_addend: int = 0

    def is_neutral(self) -> bool:
        return self == FontChoice()


NEUTRAL = FontChoice()
CHOICE_KEYS = FontChoice._fields

Change = tuple[str, str]  # (section, option key)


def option_change(key: str, value: Any, choice: FontChoice) -> tuple[bool, Any]:
    """(changed, new value) of one preset option for choice"""
    if re.search(rxp.CFG_FONT_NAME, key):
        return (choice.font_name != NO_CHANGE and value != choice.font_name), choice.font_name
    if re.search(rxp.CFG_FONT_WEIGHT, key):
        return (choice.font_weight != NO_CHANGE and value != choice.font_weight), choice.font_weight
    if "font_size" in key:
        if not choice.font_size_addend or isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, value
        new = clamp_to_limit(key, max(value + choice.font_size_addend, 1))
        return new != value, new
    if key == "enable_auto_font_offset":
        if choice.enable_auto_font_offset == NO_CHANGE:
            return False, value
        new = choice.enable_auto_font_offset == "enable"
        return new != value, new
    if key == "font_offset_vertical":
        if not choice.font_offset_vertical_addend or isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, value
        new = clamp_to_limit(key, value + choice.font_offset_vertical_addend)
        return new != value, new
    return False, value


def font_changes(setting: dict, choice: FontChoice) -> dict[Change, Any]:
    """New value of every option of preset setting changed by choice"""
    changes: dict[Change, Any] = {}
    if choice.is_neutral():
        return changes
    for section, options in setting.items():
        if not isinstance(options, dict):
            continue
        for key, value in options.items():
            changed, new = option_change(key, value, choice)
            if changed:
                changes[section, key] = new
    return changes


def apply_changes(setting: dict, changes: dict[Change, Any]) -> dict[Change, Any]:
    """Write changes into preset setting, returns the values replaced (undo), options gone skipped"""
    replaced: dict[Change, Any] = {}
    for (section, key), value in changes.items():
        options = setting.get(section)
        if isinstance(options, dict) and key in options:
            replaced[section, key] = options[key]
            options[key] = value
    return replaced


def font_sizes(setting: dict) -> list[int | float]:
    """Font sizes of every overlay of preset setting"""
    return [
        value for options in setting.values() if isinstance(options, dict)
        for key, value in options.items()
        if "font_size" in key and isinstance(value, (int, float)) and not isinstance(value, bool)
    ]


class Preview(NamedTuple):
    """What a choice changes: font sizes before & after (smallest, largest), sections & options changed"""

    size_now: tuple[float, float]
    size_after: tuple[float, float]
    sections: int
    options: int


def preview(setting: dict, choice: FontChoice) -> Preview:
    """Font sizes of preset now & once choice is applied"""
    changes = font_changes(setting, choice)
    now = font_sizes(setting)
    after = [
        changes.get((section, key), value)
        for section, options in setting.items() if isinstance(options, dict)
        for key, value in options.items()
        if "font_size" in key and isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return Preview(
        (min(now), max(now)) if now else (0, 0),
        (min(after), max(after)) if after else (0, 0),
        len({section for section, _ in changes}),
        len(changes),
    )
