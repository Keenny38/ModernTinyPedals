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
Option limits: range & type of numeric options by option key pattern

Checked by config pages while typing (invalid field highlighted with a short reason, Save
disabled), see UserConfig. Only options whose meaning is known are listed: other numbers
are only checked for being a number.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import NamedTuple


class OptionLimit(NamedTuple):
    """Allowed values of a numeric option"""

    minimum: float | None = None
    maximum: float | None = None
    integer: bool = False  # whole number only


NO_LIMIT = OptionLimit()

# Option key pattern (regex), limit: matched in order, first match wins
OPTION_LIMITS: tuple[tuple[str, OptionLimit], ...] = (
    # Column positions, set by display order dialog
    ("^display_order_", NO_LIMIT),
    ("^opacity$", OptionLimit(0, 1)),
    ("_port$", OptionLimit(1, 65535, True)),
    ("^minimum_update_interval$", OptionLimit(1, 1000, True)),
    ("update_interval$", OptionLimit(1, 60000, True)),
    ("^auto_compact_display_scale$", OptionLimit(0, 10)),  # 0 = off
    ("^(display|overlay)_scale$", OptionLimit(0.1, 10)),
    ("_scale$", OptionLimit(0)),
    ("^font_size", OptionLimit(1, 999, True)),
    ("^decimal_places", OptionLimit(0, 9, True)),
    ("^maximum_(loading|saving)_attempts$", OptionLimit(1, 100, True)),
    ("^number_of_automatic_backups$", OptionLimit(0, 1000, True)),
    ("^number_of_days_to_keep_deleted_presets$", OptionLimit(1, 3650, True)),
    ("^(snap_distance|snap_gap|grid_move_size)$", OptionLimit(0, 1000, True)),
    ("_samples$", OptionLimit(1, None, True)),
    ("_history_count$", OptionLimit(1, None, True)),
    ("(^|_)(bar|horizontal|vertical|inner|split|led)_gap$", OptionLimit(0)),
    ("^display_margin", OptionLimit(0)),
    ("_size$", OptionLimit(0)),
)


@lru_cache(maxsize=1024)
def option_limit(key: str) -> OptionLimit:
    """Limit of option key, NO_LIMIT if not listed"""
    for pattern, limit in OPTION_LIMITS:
        if re.search(pattern, key):
            return limit
    return NO_LIMIT


def format_number(value: float) -> str:
    """Number without needless decimals"""
    return f"{value:g}"


def limit_error(key: str, value: float) -> str:
    """Why value breaks limit of option (English, translate with trm), "" if within limit"""
    limit = option_limit(key)
    if limit.integer and value % 1 != 0:
        return "Whole number required"
    minimum, maximum = limit.minimum, limit.maximum
    if minimum is not None and maximum is not None and not minimum <= value <= maximum:
        return f"Between {format_number(minimum)} and {format_number(maximum)}"
    if minimum is not None and value < minimum:
        return f"Minimum {format_number(minimum)}"
    if maximum is not None and value > maximum:
        return f"Maximum {format_number(maximum)}"
    return ""
