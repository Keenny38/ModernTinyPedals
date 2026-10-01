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
Layout profiles: widget positions remembered per screen setup (single screen, triple screen...)

Stored next to preset as "<preset name>.layouts" (not ".json", so not listed as preset):
    {"1920x1080+0+0": {"speedometer": [x, y], ...}, "5760x1080+0+0": {...}}
When preset is loaded with a known screen setup, its widget positions are restored.
"""

from __future__ import annotations

import json
import logging
import os

from . import write_text_file

logger = logging.getLogger(__name__)

FILE_EXTENSION = ".layouts"
MAX_PROFILES = 20


def screen_key() -> str:
    """Screen setup identifier: geometry of every screen, sorted"""
    from PySide6.QtGui import QGuiApplication

    geometries = sorted(
        (rect.x(), rect.y(), rect.width(), rect.height())
        for rect in (screen.geometry() for screen in QGuiApplication.screens())
    )
    return ";".join(f"{width}x{height}+{x}+{y}" for x, y, width, height in geometries)


def profile_filename(settings_path: str, preset_filename: str) -> str:
    """Layout profile file of preset"""
    return os.path.join(settings_path, f"{os.path.splitext(preset_filename)[0]}{FILE_EXTENSION}")


def widget_positions(setting: dict, widget_names) -> dict[str, list[int]]:
    """Positions of every widget in preset setting"""
    positions = {}
    for name in widget_names:
        options = setting.get(name)
        if isinstance(options, dict) and "position_x" in options and "position_y" in options:
            positions[name] = [int(options["position_x"]), int(options["position_y"])]
    return positions


def apply_positions(setting: dict, positions: dict) -> bool:
    """Set widget positions from profile, returns True if any changed"""
    changed = False
    for name, position in positions.items():
        options = setting.get(name)
        if not isinstance(options, dict) or not isinstance(position, list) or len(position) != 2:
            continue
        x, y = position
        if not isinstance(x, int) or not isinstance(y, int):
            continue
        if (options.get("position_x"), options.get("position_y")) != (x, y):
            options["position_x"], options["position_y"] = x, y
            changed = True
    return changed


def load_profiles(filename: str) -> dict[str, dict]:
    """Load layout profiles, empty if missing or invalid"""
    try:
        with open(filename, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        logger.error("USERDATA: invalid layout profile %s: %s", filename, error)
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, dict)}


def save_profiles(filename: str, profiles: dict[str, dict]) -> bool:
    """Save layout profiles, keep most recent ones"""
    if len(profiles) > MAX_PROFILES:
        profiles = dict(list(profiles.items())[-MAX_PROFILES:])
    return write_text_file(filename, json.dumps(profiles, indent=4, sort_keys=True))


def sync_layout(setting: dict, widget_names, filename: str, key: str) -> bool:
    """Restore positions of screen setup if known, then store current positions

    Returns:
        True if preset positions changed (preset needs saving).
    """
    profiles = load_profiles(filename)
    changed = key in profiles and apply_positions(setting, profiles[key])
    if changed:
        logger.info("LAYOUT: restored widget positions for screen setup %s", key)
    store_layout(setting, widget_names, filename, key, profiles)
    return changed


def store_layout(setting: dict, widget_names, filename: str, key: str, profiles: dict | None = None):
    """Store current widget positions for screen setup"""
    if profiles is None:
        profiles = load_profiles(filename)
    positions = widget_positions(setting, widget_names)
    if profiles.get(key) == positions:
        return
    profiles.pop(key, None)  # most recent last
    profiles[key] = positions
    save_profiles(filename, profiles)
