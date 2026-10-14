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
Formatter function
"""

from __future__ import annotations

import random
import re
from collections.abc import Mapping
from functools import lru_cache

from .regex_pattern import ABBR_PATTERN, rex_invalid_char


def uppercase_abbr(name: str) -> str:
    """Convert abbreviation name to uppercase"""
    return re.sub(ABBR_PATTERN, upper_matched_abbr, name, flags=re.IGNORECASE)


def upper_matched_abbr(matchobj: re.Match) -> str:
    """Convert abbreviation name to uppercase"""
    return matchobj.group().upper()


# Display names differing from their setting key: key -> shown name (as a key), also as part of other keys
# (hotkeys "black_box_xxx", "widget_black_box"). Setting keys kept, so presets, settings & shortcuts keep working.
DISPLAY_RENAMES: Mapping[str, str] = {
    "black_box": "dashboard_hud",
}


def display_key(name: str, renames: Mapping[str, str] = DISPLAY_RENAMES) -> str:
    """Key of shown name: renamed key replaced where whole words of name (between "_"), other keys unchanged"""
    for old, new in renames.items():
        if old in name:
            name = re.sub(rf"(?<![^_]){old}(?![^_])", new, name)
    return name


def format_module_name(name: str) -> str:
    """Format widget & module name"""
    return uppercase_abbr(
        display_key(name.replace("module_", ""))
        .replace("_", " ")
        .title()
    )


def format_option_name(name: str) -> str:
    """Format option name ("neopedal" in option keys shown as app name)"""
    return uppercase_abbr(
        display_key(name)
        .replace("_", " ")
        .title()
        .replace("Neopedal", "NeoPedal")
    )


def format_points(value: float) -> str:
    """Track limits points: 2 decimal places at most, no trailing zero (1.25, 1.5, 5)"""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def strip_filename_extension(name: str, extension: str) -> str:
    """Strip file name extension"""
    if name.lower().endswith(extension):
        return name[:-len(extension)]
    return name


def rgb_to_gray(rgb: list[int]) -> int:
    """RGB value to gray (0-255)"""
    return (rgb[0] * 3 + rgb[1] * 6 + rgb[2]) // 10


@lru_cache(maxsize=20)
def random_color_class(name: str) -> str:
    """Generate random color for vehicle class

    Own random generator seeded by name: same color every time, global random state left alone
    (also called from server threads, see stream_overlay).
    """
    max_value = 225
    min_value = 25
    target_brightness = 100
    # Generate random RGB color
    rng = random.Random(name)
    rgb = [min_value + 10, max_value - 10, rng.randint(min_value, max_value)]
    rng.seed(name)
    rng.shuffle(rgb)
    # Brightness correction
    brightness = rgb_to_gray(rgb)
    if brightness > target_brightness:
        while brightness > target_brightness:
            ran_index = rng.randint(0, 2)
            if rgb[ran_index] >= min_value:
                rgb[ran_index] -= 5
            else:
                rgb[ran_index] += rng.randint(10, 30)
            brightness = rgb_to_gray(rgb)
    elif brightness < target_brightness:
        while brightness < target_brightness:
            ran_index = rng.randint(0, 2)
            if rgb[ran_index] <= max_value:
                rgb[ran_index] += 5
            else:
                rgb[ran_index] -= rng.randint(10, 30)
            brightness = rgb_to_gray(rgb)
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def driver_display_name(name: str) -> str:
    """Driver name without online tag ("Tobias Mueller#7949" -> "Tobias Mueller"), as every page shows it"""
    return name.split("#", 1)[0].strip() or name.strip()


@lru_cache(maxsize=256)
def shorten_driver_name(name: str) -> str:
    """Short driver name of overlays, pages & stream graphics: "Lena Hartmann" -> "L. Hartmann", "Jan van Dijk" ->
    "J. van Dijk", online tag dropped, case kept ("McLaren" stays)"""
    parts = driver_display_name(name).split()
    if len(parts) > 1:
        return f"{parts[0][:1]}. {' '.join(parts[1:])}"
    return parts[0] if parts else ""


def strip_invalid_char(name: str) -> str:
    """Strip invalid characters, and trailing space & dot (not allowed at end of Windows file name)

    Name made only of invalid characters gives "unknown", empty name stays empty.
    """
    stripped = rex_invalid_char.sub("", name).rstrip(" .")
    if stripped or not name:
        return stripped
    return "unknown"


def class_style(car_class: str, classes: Mapping | None = None) -> tuple[str, str]:
    """Alias & color of vehicle class (vehicle class editor), same on overlays, pages & stream graphics:
    alias is class name if not set, color made from name if not set"""
    if classes is None:
        from .setting import cfg

        classes = cfg.user.classes
    style = classes.get(car_class) if isinstance(classes, Mapping) else None
    if not isinstance(style, Mapping):
        return car_class, random_color_class(car_class)
    alias = style.get("alias")
    color = style.get("color")
    return (str(alias) if alias else car_class), (str(color) if color else random_color_class(car_class))


def class_color(car_class: str, classes: Mapping | None = None) -> str:
    """Color of vehicle class (vehicle class editor), made from name if not set"""
    return class_style(car_class, classes)[1]


def class_alias(car_class: str, classes: Mapping | None = None) -> str:
    """Alias of vehicle class (vehicle class editor), class name if not set"""
    return class_style(car_class, classes)[0] if car_class else ""
