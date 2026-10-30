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
Pace notes Widget
"""

from typing import TYPE_CHECKING

from ..i18n import tr_overlay
from ..module_info import NotesInfo, minfo
from ..userfile.track_notes import COLUMN_DISTANCE, COLUMN_PACENOTE
from ._base import Overlay
from .track_notes import TrackNotesMixin

if TYPE_CHECKING:
    from ..template.widget_config_types import PaceNotesConfig


class PaceNotesMixin(TrackNotesMixin):
    """Current pace note & auto hide, for classic & modern widget"""

    NOTE_COLUMN = COLUMN_PACENOTE

    def notes_data(self) -> NotesInfo:
        return minfo.pacenotes


class Realtime(PaceNotesMixin, Overlay):
    """Draw widget"""

    wcfg: "PaceNotesConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        layout = self.set_grid_layout(gap=self.wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(
            self.wcfg["font_name"],
            self.wcfg["font_size"],
            self.wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        # Config variable
        bar_padx = self.set_padding(self.wcfg["font_size"], self.wcfg["bar_padding"])
        notes_width = max(int(self.wcfg["pace_notes_width"]), 1)
        comments_width = max(int(self.wcfg["comments_width"]), 1)
        debugging_width = max(int(self.wcfg["debugging_width"]), 1)

        # Base style
        if self.wcfg["show_background"]:
            bg_color_notes = self.wcfg["background_color_pace_notes"]
            bg_color_comments = self.wcfg["background_color_comments"]
            bg_color_debugging = self.wcfg["background_color_debugging"]
        else:
            bg_color_notes = ""
            bg_color_comments = ""
            bg_color_debugging = ""

        # Pace notes
        if self.wcfg["show_pace_notes"]:
            self.bar_notes = self.set_rawtext(
                text=tr_overlay("PACE NOTES"),
                width=font_m.width * notes_width + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_pace_notes"],
                bg_color=bg_color_notes,
                alignment=self.set_text_alignment(self.wcfg["pace_notes_text_alignment"]),
            )
            self.set_primary_orient(
                target=self.bar_notes,
                column=self.wcfg["display_order_pace_notes"],
            )

        # Comments
        if self.wcfg["show_comments"]:
            self.base_height = font_m.height
            self.bar_comments = self.set_rawtext(
                text=tr_overlay("COMMENTS"),
                width=font_m.width * comments_width + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_comments"],
                bg_color=bg_color_comments,
                alignment=self.set_text_alignment(self.wcfg["comments_text_alignment"]),
            )
            self.set_primary_orient(
                target=self.bar_comments,
                column=self.wcfg["display_order_comments"],
            )

        # Debugging info
        if self.wcfg["show_debugging"]:
            self.bar_debugging = self.set_rawtext(
                text=tr_overlay("DEBUGGING"),
                width=font_m.width * debugging_width + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_debugging"],
                bg_color=bg_color_debugging,
                alignment=self.set_text_alignment(self.wcfg["debugging_text_alignment"]),
            )
            self.set_primary_orient(
                target=self.bar_debugging,
                column=self.wcfg["display_order_debugging"],
            )

        # Last data
        self.setup_notes()
        self.last_auto_hide = False

    def timerEvent(self, event):
        """Update when vehicle on track"""
        notes_current, notes_next, in_pits = self.read_notes()
        self.update_auto_hide(self.notes_hidden)
        if self.notes_hidden:
            return

        if self.wcfg["show_pace_notes"]:
            self.update_notes(self.bar_notes, self.note_text(notes_current, in_pits))

        if self.wcfg["show_comments"]:
            self.update_comments(self.bar_comments, self.comment_text(notes_current, in_pits))

        if self.wcfg["show_debugging"]:
            curr_distance = notes_current.get(COLUMN_DISTANCE, 0)
            next_distance = notes_next.get(COLUMN_DISTANCE, 0)
            self.update_debugging(self.bar_debugging, curr_distance, next_distance)

    # GUI update methods
    def update_notes(self, target, data):
        """Pace notes"""
        if target.last != data:
            target.last = data
            target.text = data
            target.update()

    def update_comments(self, target, data):
        """Comments"""
        if target.last != data:
            target.last = data
            if self.wcfg["enable_comments_line_break"]:
                line_break_count = data.count("\\n") + 1
                data = data.replace("\\n", "\n")
                target.setFixedHeight(self.base_height * line_break_count)
            target.text = data
            target.update()

    def update_debugging(self, target, *data):
        """Debugging info"""
        if target.last != data:
            target.last = data
            target.text = f"{data[0]:.2f}m >> {data[1]:.2f}m"
            target.update()

    def update_auto_hide(self, auto_hide):
        """Auto hide"""
        if self.last_auto_hide != auto_hide:
            self.last_auto_hide = auto_hide
            if self.wcfg["show_pace_notes"]:
                self.bar_notes.setHidden(auto_hide)
            if self.wcfg["show_comments"]:
                self.bar_comments.setHidden(auto_hide)
            if self.wcfg["show_debugging"]:
                self.bar_debugging.setHidden(auto_hide)
