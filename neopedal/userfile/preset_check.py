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
Preset check: what loading a preset file changes (unknown or invalid options, values out of allowed range,
same or negative display orders, options of an older version updated), then its repaired settings
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from ..setting_validator import PresetValidator


def check_preset(raw: Mapping[str, Any], dict_def: dict) -> tuple[dict, list[str]]:
    """Repaired preset & changes made by loading it ("section: option old -> new"), empty if none"""
    original = copy.deepcopy(dict(raw))
    checked = PresetValidator.user_preset(copy.deepcopy(dict(raw)), dict_def)
    changes: list[str] = []
    for section, options in original.items():
        if section not in checked:
            changes.append(f"{section}: unknown, removed")
            continue
        new = checked[section]
        if not isinstance(options, dict):
            if isinstance(new, dict):
                changes.append(f"{section}: invalid, default used")
            continue
        if not isinstance(new, dict):
            continue
        for key, value in options.items():
            if key not in new:
                changes.append(f"{section}: {key} unknown or renamed, removed")
            elif new[key] != value:
                changes.append(f"{section}: {key} {_text(value)} -> {_text(new[key])}")
    return checked, changes


def check_preset_file(filename: str, filepath: str, dict_def: dict) -> tuple[dict, list[str]]:
    """Check of a preset file

    Raises:
        OSError: file unreadable.
        ValueError: not a JSON preset.
    """
    with open(f"{filepath}{filename}", encoding="utf-8-sig") as file:
        raw = json.load(file)
    if not isinstance(raw, dict):
        raise ValueError("not a preset")
    return check_preset(raw, dict_def)


def _text(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 40 else f"{text[:37]}..."
