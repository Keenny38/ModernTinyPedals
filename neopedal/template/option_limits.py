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
    ("_percentage_threshold$", OptionLimit(0, 100)),
    ("^background_opacity_percentage$", OptionLimit(0, 100)),
    ("^overlay_opacity_percentage$", OptionLimit(10, 100)),  # 0 would hide every overlay
    ("_port$", OptionLimit(1, 65535, True)),
    ("^minimum_update_interval$", OptionLimit(1, 1000, True)),
    ("update_interval$", OptionLimit(1, 60000, True)),
    ("^auto_compact_display_scale$", OptionLimit(0, 10)),  # 0 = off
    ("^(display|overlay)_scale$", OptionLimit(0.1, 10)),
    # Sizes with an upper limit: larger ones make overlays of tens of thousands of pixels (memory, crash)
    ("^global_scale$", OptionLimit(0.1, 50)),  # radar pixels per meter
    ("^font_scale_", OptionLimit(0, 10)),
    ("^(status_icon|damage_panel|battery_bar|trace_height)_scale$", OptionLimit(0, 20)),
    ("^font_size", OptionLimit(1, 200, True)),
    ("padding", OptionLimit(0, 10)),  # bar padding: font size multiplier
    ("^radar_radius$", OptionLimit(5, 200)),
    ("^number_of_led$", OptionLimit(1, 100, True)),
    ("^decimal_places", OptionLimit(0, 9, True)),
    ("^maximum_(loading|saving)_attempts$", OptionLimit(1, 100, True)),
    ("^maximum_vehicles_per_split_others$", OptionLimit(0, 126, True)),  # 0 = other classes hidden
    ("^number_of_automatic_backups$", OptionLimit(0, 1000, True)),
    ("^number_of_days_to_keep_deleted_presets$", OptionLimit(1, 3650, True)),
    ("^number_of_hours_between_update_checks$", OptionLimit(0, 168, True)),  # 0 = startup only
    ("^(snap_distance|snap_gap|grid_move_size)$", OptionLimit(0, 1000, True)),
    ("^minimum_node_distance$", OptionLimit(0.1, 50)),  # track map recording: meters between nodes
    ("_samples$", OptionLimit(1, 10000, True)),
    ("_history_count$", OptionLimit(1, 100, True)),  # rows of history overlays (designs show 100 at most)
    ("(^|_)(bar|horizontal|vertical|inner|split|led)_gap$", OptionLimit(0, 2000)),
    ("^display_margin", OptionLimit(0, 2000)),
    # Counts of drawn items: designs draw that many (large counts: huge overlays)
    ("^number_of_(rpm_leds|led)$", OptionLimit(1, 100, True)),
    ("^number_of_delta_laptime$", OptionLimit(2, 5, True)),
    ("^number_of_prediction$", OptionLimit(0, 10, True)),
    ("^number_of_(event_log_lines|notifications|lines|forecasts)$", OptionLimit(1, 50, True)),
    ("^number_of_", OptionLimit(0, 1000, True)),
    # Pixel sizes & positions inside overlays (screen position_x/y: any screen layout, not limited)
    ("^(position|mirror_position)_[xy]$", NO_LIMIT),
    ("^(edge_|radar_)?fade_(in|out)_radius$", OptionLimit(0, 1)),  # fraction of radius
    ("_radius$", OptionLimit(0, 5000)),
    ("(_|^)(width|height|length)$", OptionLimit(0, 4000)),
    ("_size$", OptionLimit(0, 4000)),
    ("^(area|inner|rotation_line)_margin$", OptionLimit(0, 2000)),
    ("_offset(_[xy])?$", OptionLimit(-4000, 4000)),
    ("_scale$", OptionLimit(0, 1000)),
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


def clamp_to_limit(key: str, value: float) -> float:
    """Value within limit of option (same type: whole number kept as int)"""
    limit = option_limit(key)
    clamped = value
    if limit.minimum is not None and clamped < limit.minimum:
        clamped = limit.minimum
    if limit.maximum is not None and clamped > limit.maximum:
        clamped = limit.maximum
    if clamped == value:
        return value
    if isinstance(value, int) and float(clamped).is_integer():
        return int(clamped)
    return float(clamped)
