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
Custom overlay themes file (overlay_themes.json in global config folder)

Format:
    {"theme name": {"base": "Modern Dark", "colors": {"FF2200": "CC0000", ...}}}
Colors map classic default color (RGB hex) to theme color, on top of base theme.
"""

from __future__ import annotations

import json
import logging
import re

from . import write_text_file

logger = logging.getLogger(__name__)

FILENAME = "overlay_themes.json"
_rgb = re.compile(r"^[0-9A-F]{6}$")


def validate_themes(data: object, builtin_names: tuple[str, ...]) -> dict[str, dict]:
    """Keep only valid custom themes"""
    themes: dict[str, dict] = {}
    if not isinstance(data, dict):
        return themes
    for name, theme in data.items():
        if not isinstance(name, str) or not name.strip() or name in builtin_names or not isinstance(theme, dict):
            continue
        base = theme.get("base", "Modern Dark")
        if not isinstance(base, str) or base not in builtin_names:
            base = "Modern Dark"
        source_colors = theme.get("colors")
        if not isinstance(source_colors, dict):  # null, list... (hand edited file): no color
            source_colors = {}
        colors = {
            str(source).upper(): str(target).upper()
            for source, target in source_colors.items()
            if _rgb.match(str(source).upper()) and _rgb.match(str(target).upper())
        }
        themes[name.strip()] = {"base": base, "colors": colors}
    return themes


def load_custom_themes(filepath: str, builtin_names: tuple[str, ...]) -> dict[str, dict]:
    """Load custom themes, empty if file missing or invalid"""
    try:
        with open(f"{filepath}{FILENAME}", encoding="utf-8") as file:
            return validate_themes(json.load(file), builtin_names)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as error:  # never blocks startup
        logger.error("USERDATA: invalid %s: %s", FILENAME, error)
        return {}


THEME_FILE_FORMAT = "modern-tiny-pedals-overlay-theme"
MAX_THEME_FILE_SIZE = 1024 * 1024


def export_theme(filename: str, name: str, theme: dict) -> bool:
    """Export one theme to shareable json file"""
    data = {"format": THEME_FILE_FORMAT, "version": 1, "themes": {name: theme}}
    return write_text_file(filename, json.dumps(data, indent=4, sort_keys=True))


def import_themes(filename: str, builtin_names: tuple[str, ...]) -> dict[str, dict]:
    """Read themes from exported file (or overlay_themes.json)

    Raises:
        ValueError: invalid or empty theme file.
        OSError: file error.
    """
    with open(filename, encoding="utf-8") as file:
        content = file.read(MAX_THEME_FILE_SIZE + 1)
    if len(content) > MAX_THEME_FILE_SIZE:
        raise ValueError("file too large")
    try:
        data = json.loads(content)
    except RecursionError as error:  # too deeply nested
        raise ValueError("invalid theme file") from error
    if isinstance(data, dict) and data.get("format") == THEME_FILE_FORMAT:
        data = data.get("themes")
    themes = validate_themes(data, builtin_names)
    if not themes:
        raise ValueError("no valid theme found")
    return themes


def unique_theme_name(name: str, taken) -> str:
    """Theme name not in taken names: name, name (2)..."""
    candidate = name
    index = 2
    while candidate in taken:
        candidate = f"{name} ({index})"
        index += 1
    return candidate


def save_custom_themes(filepath: str, themes: dict[str, dict]) -> bool:
    """Save custom themes"""
    return write_text_file(f"{filepath}{FILENAME}", json.dumps(themes, indent=4, sort_keys=True))
