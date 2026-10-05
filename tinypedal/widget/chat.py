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
Chat Widget

Chat messages of game (LMU Rest API), newest at bottom, long messages wrapped, each message
hidden some seconds after it was sent, newest messages highlighted a moment.
"""

from __future__ import annotations

import textwrap
from time import localtime, strftime, time

from PySide6.QtCore import Qt

from ..api_control import api
from ._base import Overlay

MAX_LINES = 20


def chat_lines(messages, now: float, line_width: int, line_count: int, max_duration: float,
               new_duration: float, show_time: bool) -> tuple[tuple[str, bool], ...]:
    """Lines shown (text, newly sent), oldest at top, newest messages kept when lines run out

    Args:
        messages: (Unix time, text) of each message, oldest first.
        max_duration: seconds a message stays shown, 0 or less: always.
        new_duration: seconds a message is highlighted after sent.
    """
    lines: list[tuple[str, bool]] = []
    for sent, text in reversed(messages):
        age = now - sent
        if 0 < max_duration < age:
            break  # older messages are older still
        if show_time:
            text = f"{strftime('%H:%M', localtime(sent))} {text}"
        wrapped = textwrap.wrap(text, line_width) or [""]
        is_new = age < new_duration
        lines[:0] = [(line, is_new) for line in wrapped]
        if len(lines) >= line_count:
            break
    return tuple(lines[-line_count:])


class Realtime(Overlay):
    """Draw widget"""

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
        self.line_width = max(int(self.wcfg["line_width"]), 10)
        self.line_count = min(max(int(self.wcfg["number_of_lines"]), 1), MAX_LINES)
        self.max_duration = float(self.wcfg["maximum_display_duration"])
        self.new_duration = max(float(self.wcfg["new_message_duration"]), 0.0)
        self.show_time = bool(self.wcfg["show_message_time"])
        self.color_message = self.wcfg["font_color_message"]
        self.color_new_message = self.wcfg["font_color_new_message"]
        time_width = 6 if self.show_time else 0  # "12:34 " before message

        # Message lines
        bars = self.set_rawtext(
            text="",
            width=font_m.width * (self.line_width + time_width + 1) + bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.color_message,
            bg_color=self.wcfg["background_color_message"],
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            count=self.line_count,
        )
        self.bars = bars if isinstance(bars, tuple) else (bars,)
        for index, bar in enumerate(self.bars):
            layout.addWidget(bar, index, 0)
            bar.hide()

        # Last data
        self.last_lines: tuple = ()

    def timerEvent(self, event):
        """Update when vehicle on track"""
        lines = chat_lines(
            api.read.session.chat_messages(), time(), self.line_width, self.line_count,
            self.max_duration, self.new_duration, self.show_time)
        if lines != self.last_lines:
            self.last_lines = lines
            self.update_lines(lines)

    # GUI update methods
    def update_lines(self, lines: tuple[tuple[str, bool], ...]):
        """Lines filled from bottom, unused lines hidden"""
        unused = self.line_count - len(lines)
        for index, bar in enumerate(self.bars):
            if index < unused:
                bar.hide()
                continue
            text, is_new = lines[index - unused]
            bar.text = f" {text}"
            bar.fg = self.color_new_message if is_new else self.color_message
            bar.show()
            bar.update()
