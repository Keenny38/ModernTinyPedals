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
Pace notes Widget, modern design

Same card as track notes: current pace note in bold, comments under it (one line per line
break), debugging distances. Sections stacked (or side by side), hidden while auto hidden.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..pace_notes import PaceNotesMixin
from .base import display_order_options
from .track_notes import Realtime as TrackNotes

if TYPE_CHECKING:
    from ...template.widget_config_types import PaceNotesConfig


class Realtime(PaceNotesMixin, TrackNotes):
    """Draw widget"""

    wcfg: PaceNotesConfig  # type: ignore[assignment]  # track notes card, pace notes options

    NOTES_KEY = "pace_notes"
    options = (
        "font_size", "layout", "show_background", "enable_auto_hide_if_not_available", "maximum_display_duration",
        "show_pit_notes_while_in_pit", "pit_notes_text", "pit_comments_text", "show_pace_notes",
        "pace_notes_width", "pace_notes_text_alignment", "show_comments",
        "enable_comments_line_break", "comments_width", "comments_text_alignment", "show_debugging",
        "debugging_width", "debugging_text_alignment", *display_order_options("pace_notes"),
    )
