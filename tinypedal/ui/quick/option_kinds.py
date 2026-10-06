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
Option kinds of Qt Quick pages: editor of an option key, its choices, value checks & shown value

Same rules (and order) as the editors of config pages, see ui.config.UserConfig._add_option_editor.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, NamedTuple

from ... import regex_pattern as rxp
from ...i18n import tr
from ...validator import is_clock_format, is_hex_color, is_string_number
from ..option_limits import limit_error, option_limit

KIND_BOOL = "bool"
KIND_CHOICE = "choice"
KIND_FONT = "font"  # choice of installed font families
KIND_COLOR = "color"
KIND_PATH = "path"  # folder
KIND_IMAGE = "image"  # image file
KIND_CLOCK = "clock"
KIND_TEXT = "text"
KIND_INTEGER = "integer"
KIND_FLOAT = "float"
NUMBER_KINDS = (KIND_INTEGER, KIND_FLOAT)
MAX_DECIMALS = 4
# Choice lists shown as is (names, not words): others shown translated, English value saved
UNTRANSLATED_CHOICES = (rxp.CFG_API_NAME, rxp.CFG_CHARACTER_ENCODING, rxp.CFG_LANGUAGE, rxp.CFG_FONT_WEIGHT)


class OptionKind(NamedTuple):
    """Editor of an option"""

    kind: str
    choices: tuple[str, ...] = ()  # saved (English) values of a choice list
    translate: bool = False  # choices shown translated


def _choice(choice_dict, key: str) -> OptionKind | None:
    for pattern, choices in choice_dict.items():
        if re.search(pattern, key):
            return OptionKind(KIND_CHOICE, tuple(choices), pattern not in UNTRANSLATED_CHOICES)
    return None


def option_kind(key: str) -> OptionKind:
    """Editor of option key (choices read now: language packs can be added while running)"""
    if re.search(rxp.CFG_BOOL, key):
        return OptionKind(KIND_BOOL)
    choice = _choice(rxp.CHOICE_UNITS, key)
    if choice is not None:
        return choice
    choice = _choice(rxp.CHOICE_COMMON, key)
    if choice is not None:
        return choice
    if re.search(rxp.CFG_COLOR, key):
        return OptionKind(KIND_COLOR)
    if re.search(rxp.CFG_USER_PATH, key):
        return OptionKind(KIND_PATH)
    if re.search(rxp.CFG_USER_IMAGE, key):
        return OptionKind(KIND_IMAGE)
    if re.search(rxp.CFG_FONT_NAME, key):
        return OptionKind(KIND_FONT)
    if re.search(rxp.CFG_HEATMAP, key):
        from ...setting import cfg

        return OptionKind(KIND_CHOICE, tuple(cfg.user.heatmap))
    if re.search(rxp.CFG_CLOCK_FORMAT, key):
        return OptionKind(KIND_CLOCK)
    if "by_compound" in key or re.search(rxp.CFG_STRING, key):
        return OptionKind(KIND_TEXT)
    if re.search(rxp.CFG_INTEGER, key):
        return OptionKind(KIND_INTEGER)
    return OptionKind(KIND_FLOAT)


def value_kind(key: str, default: Any) -> OptionKind:
    """Editor of option key, corrected by its default value type: a number key holding text (access code)
    is edited as text, a text key holding a number as a number"""
    kind = option_kind(key)
    if kind.kind in NUMBER_KINDS and isinstance(default, str):
        return OptionKind(KIND_TEXT)
    if kind.kind == KIND_TEXT and isinstance(default, (int, float)) and not isinstance(default, bool):
        return OptionKind(KIND_INTEGER if isinstance(default, int) else KIND_FLOAT)
    return kind


@lru_cache(maxsize=1)
def font_families() -> tuple[str, ...]:
    """Installed font families (read once: slow with many fonts)"""
    from PySide6.QtGui import QFontDatabase

    return tuple(QFontDatabase.families())


def choice_label(kind: OptionKind, value: Any) -> str:
    """Shown text of a choice value"""
    return tr(str(value)) if kind.translate else str(value)


def number_text(value: Any) -> str:
    """Number without needless decimals: 1.0 -> 1, 0.05 -> 0.05"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:.10g}"


def decimals(*values: Any) -> int:
    """Decimal places needed to show values (numbers of an option: current & default)"""
    places = 0
    for value in values:
        text = number_text(value)
        if "." in text and "e" not in text:
            places = max(places, len(text.split(".", 1)[1]))
    return min(places, MAX_DECIMALS)


def display_text(kind: OptionKind, value: Any) -> str:
    """Option value as shown in a list (option search)"""
    if kind.kind == KIND_BOOL:
        return tr("On") if value else tr("Off")
    if kind.kind == KIND_CHOICE:
        return choice_label(kind, value)
    if kind.kind in NUMBER_KINDS:
        return number_text(value)
    return str(value)


def check_value(key: str, kind: OptionKind, value: Any) -> str:
    """Why value is invalid for option (English, translate with trm), "" if valid

    Folder paths are checked when saved only (checking creates the folder), see parse_path.
    """
    if kind.kind == KIND_BOOL:
        return "" if isinstance(value, bool) else "On or off required"
    if kind.kind in NUMBER_KINDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "Number required"
        if kind.kind == KIND_INTEGER and float(value) % 1 != 0:
            return "Whole number required"
        return limit_error(key, float(value))
    if not isinstance(value, str):
        return "Text required"
    if kind.kind == KIND_COLOR:
        return "" if is_hex_color(value) else "Color as #RRGGBB or #AARRGGBB"
    if kind.kind == KIND_CLOCK:
        return "" if is_clock_format(value) else "Invalid clock format"
    if kind.kind == KIND_IMAGE:
        return "" if not value or os.path.exists(value) else "File not found"
    if kind.kind == KIND_PATH:
        return "" if value.strip() else "Folder required"
    return ""


def parse_number(kind: OptionKind, text: str) -> int | float | None:
    """Typed number (decimal comma accepted), None if not a number"""
    text = text.strip().replace(",", ".")
    if not is_string_number(text):
        return None
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):  # NaN, infinity
        return None
    return int(value) if value.is_integer() else value  # decimal in integer option: see check_value


def parse_path(text: str) -> str | None:
    """Folder path to save (relative if inside app folder, created if missing), None if invalid

    Empty path or drive root would put user data at the root of a drive.
    """
    from ...userfile import set_relative_path, set_user_data_path

    if not text.strip():
        return None
    value = set_relative_path(text.strip())
    full_path = os.path.abspath(value)
    if os.path.dirname(full_path) == full_path:  # drive or file system root
        return None
    if not set_user_data_path(value):
        return None
    return value


def number_range(key: str) -> tuple[float, float]:
    """Allowed range of numeric option (very wide if not limited)"""
    limit = option_limit(key)
    minimum = limit.minimum if limit.minimum is not None else -1e9
    maximum = limit.maximum if limit.maximum is not None else 1e9
    return minimum, maximum
