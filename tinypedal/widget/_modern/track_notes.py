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
Track notes Widget, modern design

Card with accent edge: current track note in bold, comments under it (one line per line
break), debugging distances. Sections stacked (or side by side), hidden while auto hidden.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...userfile.track_notes import COLUMN_DISTANCE
from ..track_notes import TrackNotesMixin
from .base import CENTER, LEFT, RIGHT, ModernOverlay, display_order_options
from .draw import accent_edge, panel

SECTIONS = (  # key, font role, color token
    ("track_notes", "strong", "text"),
    ("comments", "small", "text_dim"),
    ("debugging", "small", "text_muted"),
)
ALIGN = {"left": LEFT, "right": RIGHT}  # else center


class Realtime(TrackNotesMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_background", "enable_auto_hide_if_not_available", "maximum_display_duration",
        "show_pit_notes_while_in_pit", "pit_notes_text", "pit_comments_text", "show_track_notes",
        "track_notes_uppercase", "track_notes_width", "track_notes_text_alignment", "show_comments",
        "enable_comments_line_break", "comments_width", "comments_text_alignment", "show_debugging",
        "debugging_width", "debugging_text_alignment", *display_order_options("track_notes"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.setup_notes()
        self.keys = tuple(self.display_ordered([key for key, _, _ in SECTIONS if wcfg[f"show_{key}"]], key=str))
        self.roles = {key: role for key, role, _ in SECTIONS}
        self.colors = {key: getattr(self.theme, token) for key, _, token in SECTIONS}
        self.aligns = {key: ALIGN.get(str(wcfg[f"{key}_text_alignment"]).lower(), CENTER) for key, _, _ in SECTIONS}
        self.widths = {key: self.digit_width(self.roles[key]) * max(int(wcfg[f"{key}_width"]), 1) for key, _, _ in SECTIONS}
        self.horizontal = wcfg["layout"] != 0
        self.show_background = bool(wcfg["show_background"])
        self.line_break = bool(wcfg["enable_comments_line_break"])
        self.uppercase = bool(wcfg["track_notes_uppercase"])
        self.comment_lines = 0
        self.sections: dict[str, QRectF] = {}
        self.place_sections(1)

    def place_sections(self, comment_lines: int):
        """Section rects & widget size for number of comment lines"""
        if comment_lines == self.comment_lines:
            return
        self.comment_lines = comment_lines
        unit = self.unit
        pad = unit * 0.35
        edge = unit * 0.3 if self.show_background else 0.0
        inner = unit * 0.5
        heights = {"track_notes": unit * 1.5, "comments": unit * 1.1 * comment_lines + unit * 0.3, "debugging": unit * 1.2}
        left = pad + edge
        top = pad
        width = height = 0.0
        for key in self.keys:
            section_w = self.widths[key] + inner * 2
            rect = QRectF(left, top, section_w, heights[key])
            self.sections[key] = rect
            if self.horizontal:
                left += section_w
                height = max(height, heights[key])
            else:
                top += heights[key]
                width = max(width, section_w)
        if self.horizontal:
            width = left - pad - edge
        else:
            height = top - pad
            for key in self.keys:  # same width stacked
                self.sections[key].setWidth(width)
        self.set_size(width + pad * 2 + edge, max(height, unit) + pad * 2)
        self.update()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        notes_current, notes_next, in_pits = self.read_notes()
        if self.notes_hidden:
            self.refresh(None)
            return
        texts: list[tuple[str, ...]] = []
        for key in self.keys:
            if key == "track_notes":
                text = self.note_text(notes_current, in_pits)
                texts.append((text.upper() if self.uppercase else text,))
            elif key == "comments":
                text = self.comment_text(notes_current, in_pits)
                texts.append(tuple(text.split("\\n")) if self.line_break else (text.replace("\\n", " "),))
            else:
                current = notes_current.get(COLUMN_DISTANCE, 0)
                following = notes_next.get(COLUMN_DISTANCE, 0)
                texts.append((f"{current:.2f}m » {following:.2f}m",))
        if "comments" in self.keys:
            self.place_sections(len(texts[self.keys.index("comments")]))
        self.refresh(tuple(texts))

    def paintEvent(self, event):
        """Nothing shown while auto hidden"""
        if self.notes_hidden:
            return
        super().paintEvent(event)

    def paint_static(self, painter: QPainter):
        theme = self.theme
        if not self.show_background:
            return
        rect = QRectF(self.rect())
        panel(painter, rect, theme, self.radius(0.5), self.depth_effects)
        unit = self.unit
        accent_edge(painter, QRectF(unit * 0.3, unit * 0.35, rect.width(), rect.height() - unit * 0.7),
                    theme.accent, max(unit * 0.16, 2.0), self.radius(0.3))
        divider = theme.tint(theme.text, 26)
        for index, key in enumerate(self.keys):
            if not index:
                continue
            section = self.sections[key]
            if self.horizontal:
                painter.fillRect(QRectF(section.left() - 0.5, section.top() + unit * 0.3, 1,
                                        section.height() - unit * 0.6), divider)
            else:
                painter.fillRect(QRectF(section.left() + unit * 0.4, section.top() - 0.5,
                                        section.width() - unit * 0.8, 1), divider)

    def paint(self, painter: QPainter):
        inner = self.unit * 0.5
        for key, lines in zip(self.keys, self.state):
            section = self.sections[key].adjusted(inner, 0, -inner, 0)
            role = self.roles[key]
            if len(lines) > 1:
                line_h = (section.height() - self.unit * 0.3) / len(lines)
                top = section.top() + self.unit * 0.15
            else:
                line_h = section.height()
                top = section.top()
            for line in lines:
                self.draw_text(painter, QRectF(section.left(), top, section.width(), line_h), line, role,
                               self.colors[key], self.aligns[key])
                top += line_h
