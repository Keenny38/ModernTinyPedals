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
Chat Widget, modern design

Chat feed card, newest message at bottom: sender name in its own color (same color for a sender
all race), message wrapped to card width, optional time. Messages just sent are highlighted
with an accent edge, messages fade out at the end of display duration. Card grows with lines
shown, nothing drawn without message (unless overlay unlocked, or before first update: picture
of Overlays page).
"""

from __future__ import annotations

from time import localtime, strftime, time
from typing import NamedTuple
from zlib import crc32

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ...api_control import api
from ...i18n import tr_overlay as tr
from .._race_aids import HiddenPreview
from ..chat import MAX_LINES
from .base import LEFT, ModernOverlay
from .draw import accent_edge, panel, rounded

FADE_TIME = 1.0  # seconds of fade out at end of display
FADE_STEPS = 8
NAME_TOKENS = ("accent", "positive", "warning", "best", "orange", "blue", "lap_behind", "caution")
NEW_ALPHA = 36  # background tint of new message lines


class Line(NamedTuple):
    """Shown line of a message"""

    time: str  # first line of message only
    name: str  # first line of message only
    text: str
    name_color: int  # NAME_TOKENS index
    new: bool
    step: int  # opacity step
    first: bool  # first line of message


def split_sender(message: str) -> tuple[str, str]:
    """("Name", "message") of "Name: message" (no sender if no name prefix)"""
    name, sep, text = message.partition(": ")
    if not sep or not name or len(name) > 32:
        return "", message
    return name, text


class Realtime(HiddenPreview, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "number_of_lines", "line_width", "maximum_display_duration", "new_message_duration",
        "show_message_time",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.line_count = min(max(int(wcfg["number_of_lines"]), 1), MAX_LINES)
        self.max_duration = float(wcfg["maximum_display_duration"])
        self.new_duration = max(float(wcfg["new_message_duration"]), 0.0)
        self.show_time = bool(wcfg["show_message_time"])
        self.add_font("name", 1.0, "bold")
        self.pad = unit * 0.45
        self.line_h = unit * 1.3
        self.edge = max(unit * 0.18, 2.0)
        self.time_w = self.text_width("small", "88:88") + unit * 0.45 if self.show_time else 0.0
        # Text width: line width option in characters (average character of design font)
        self.text_w = max(int(wcfg["line_width"]), 10) * self.metrics["value"].averageCharWidth()
        self.space_w = self.advance("value", " ")
        width = self.pad * 2 + self.edge + self.time_w + self.text_w
        self.set_size(width, self.line_h * self.line_count + self.pad * 2)
        self.wrap_cache: dict[tuple, tuple[str, ...]] = {}
        self.preview = (Line("", "", tr("Chat"), 0, False, FADE_STEPS, True),)

    # Data
    def wrap(self, name: str, text: str) -> tuple[str, ...]:
        """Message lines fitting text width, first line after sender name"""
        key = (name, text)
        lines = self.wrap_cache.get(key)
        if lines is not None:
            return lines
        first_w = self.text_w - (self.advance("name", name) + self.space_w if name else 0.0)
        lines_list: list[str] = []
        current = ""
        width = first_w
        for word in text.split():
            candidate = f"{current} {word}" if current else word
            if self.advance("value", candidate) <= width or not current:
                if not current and self.advance("value", word) > width:  # word longer than line: cut
                    candidate = self.elided("value", word, width)
                current = candidate
                continue
            lines_list.append(current)
            current = word
            width = self.text_w
        lines_list.append(current)
        lines = tuple(lines_list)
        if len(self.wrap_cache) > 256:
            self.wrap_cache.clear()
        self.wrap_cache[key] = lines
        return lines

    def read_lines(self, messages, now: float) -> tuple[Line, ...]:
        """Lines shown, oldest at top, newest messages kept when lines run out"""
        lines: list[Line] = []
        max_duration = self.max_duration
        for sent, message in reversed(messages):
            age = now - sent
            if 0 < max_duration < age:
                break  # older messages are older still
            name, text = split_sender(message)
            left = max_duration - age
            step = FADE_STEPS if max_duration <= 0 or left >= FADE_TIME else max(round(left / FADE_TIME * FADE_STEPS), 1)
            stamp = strftime("%H:%M", localtime(sent)) if self.show_time else ""
            color = crc32(name.encode("utf-8")) % len(NAME_TOKENS) if name else 0
            new = age < self.new_duration
            wrapped = self.wrap(name, text)
            lines[:0] = [
                Line(stamp if index == 0 else "", name if index == 0 else "", part, color, new, step, index == 0)
                for index, part in enumerate(wrapped)
            ]
            if len(lines) >= self.line_count:
                break
        return tuple(lines[-self.line_count:])

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.refresh(self.read_lines(api.read.session.chat_messages(), time()))

    # Paint
    def paintEvent(self, event):
        """Draw while a message is shown (or overlay unlocked, or not updated yet)"""
        if self.state is None:
            self.state = ()
            super().paintEvent(event)
            self.state = None
        elif self.state or self.previewing():
            super().paintEvent(event)

    def paint(self, painter: QPainter):
        theme = self.theme
        lines = self.state or self.preview
        pad = self.pad
        line_h = self.line_h
        height = line_h * len(lines) + pad * 2
        card = QRectF(0, self.height() - height, self.width(), height)
        panel(painter, card, theme, self.radius(0.5), self.depth_effects)
        text_left = pad + self.edge + self.time_w
        top = card.top() + pad
        for index, line in enumerate(lines):
            row = QRectF(pad, top + line_h * index, card.width() - pad * 2, line_h)
            painter.setOpacity(line.step / FADE_STEPS)
            if line.new:
                rounded(painter, row, 0, theme.tint(theme.accent, NEW_ALPHA))
                accent_edge(painter, row, theme.accent, self.edge, self.edge / 2)
            if line.time:
                self.draw_text(painter, QRectF(pad + self.edge * 2, row.top(), self.time_w, line_h), line.time, "small",
                               theme.text_muted, LEFT)
            left = text_left
            if line.name:
                self.draw_text(painter, QRectF(left, row.top(), self.text_w, line_h), line.name, "name",
                               getattr(theme, NAME_TOKENS[line.name_color]), LEFT)
                left += self.advance("name", line.name) + self.space_w
            self.draw_text(painter, QRectF(left, row.top(), text_left + self.text_w - left, line_h), line.text, "value",
                           theme.text, LEFT)
        painter.setOpacity(1.0)
