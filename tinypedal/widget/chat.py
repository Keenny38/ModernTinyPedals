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

Chat messages of game (LMU Rest API), newest at bottom (or at top), long messages wrapped, each message
hidden some seconds after it was sent (also while not driving: overlay updates paused), newest
messages highlighted a moment.
"""

from __future__ import annotations

import textwrap
from time import localtime, strftime, time

from PySide6.QtCore import Qt, QTimer

from ..api_control import api
from ._base import Overlay

MAX_LINES = 20
EXPIRE_MS = 250  # messages hidden at end of display duration checked at this interval while updates are paused
# Sample conversation of overlay pictures & placement in edit mode: (seconds ago, message), player SAMPLE_PLAYER
SAMPLE_PLAYER = "L. Garnier"
SAMPLE_MESSAGES = (
    (26.0, "Race Control: Full course yellow in sector 2"),
    (19.0, "M. Laurent: sorry for the contact at turn 1"),
    (13.0, f"{SAMPLE_PLAYER}: no worries, have a good race"),
    (7.0, "J. Hartmann: letting you by on the straight"),
    (2.0, "N. Fischer joined the session"),
)


def sample_messages(now: float) -> tuple[tuple[float, str], ...]:
    """Sample conversation as game messages (Unix time, text), oldest first"""
    return tuple((now - age, text) for age, text in SAMPLE_MESSAGES)


def chat_lines(messages, now: float, line_width: int, line_count: int, max_duration: float,
               new_duration: float, show_time: bool, newest_at_top: bool = False) -> tuple[tuple[str, bool], ...]:
    """Lines shown (text, newly sent), oldest at top (newest at top if newest_at_top), newest messages kept
    when lines run out (lines of a message always in reading order)

    Args:
        messages: (Unix time, text) of each message, oldest first.
        max_duration: seconds a message stays shown, 0 or less: always.
        new_duration: seconds a message is highlighted after sent.
    """
    blocks: list[list[tuple[str, bool]]] = []  # newest message first
    total = 0
    for sent, text in reversed(messages):
        age = now - sent
        if 0 < max_duration < age:
            break  # older messages are older still
        if show_time:
            text = f"{strftime('%H:%M', localtime(sent))} {text}"
        wrapped = textwrap.wrap(text, line_width) or [""]
        is_new = age < new_duration
        blocks.append([(line, is_new) for line in wrapped])
        total += len(wrapped)
        if total >= line_count:
            break
    return stack_blocks(blocks, line_count, newest_at_top)


def stack_blocks(blocks: list[list], line_count: int, newest_at_top: bool) -> tuple:
    """Lines of messages (blocks, newest first) in shown order, oldest message cut when lines run out:
    its first lines dropped at top (newest at bottom), its last lines dropped at bottom (newest at top)"""
    if newest_at_top:
        return tuple(line for block in blocks for line in block)[:line_count]
    lines = tuple(line for block in reversed(blocks) for line in block)
    return lines[-line_count:] if line_count else ()


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
        self.newest_at_top = self.wcfg["scroll_direction"] == "Downward"
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
        self.last_messages: tuple = ()  # kept hidden at end of display duration while updates are paused
        self._expire_timer = QTimer(self)
        self._expire_timer.setInterval(EXPIRE_MS)
        self._expire_timer.timeout.connect(self.expire)

    def show_sample(self):
        """Sample conversation (overlay pictures)"""
        lines = chat_lines(sample_messages(time()), time(), self.line_width, self.line_count, 0.0,
                           self.new_duration, self.show_time, self.newest_at_top)
        self.last_lines = lines
        self.update_lines(lines)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self._expire_timer.stop()
        self.last_messages = api.read.session.chat_messages()
        self.show_lines(self.last_messages)

    def stop(self):
        """Stop and close widget: fading out stopped too (started by update pause while stopping)"""
        timer = self._expire_timer
        super().stop()
        timer.stop()

    def post_update(self):
        """Overlay updates paused (not driving): messages shown still hidden at end of display duration"""
        if self.last_lines and self.max_duration > 0:
            self._expire_timer.start()

    def expire(self):
        """Messages shown read again at current time (updates paused), stopped once none left"""
        self.show_lines(self.last_messages)
        if not self.last_lines:
            self._expire_timer.stop()

    def show_lines(self, messages):
        """Lines of messages at current time, shown if changed"""
        lines = chat_lines(
            messages, time(), self.line_width, self.line_count,
            self.max_duration, self.new_duration, self.show_time, self.newest_at_top)
        if lines != self.last_lines:
            self.last_lines = lines
            self.update_lines(lines)

    # GUI update methods
    def update_lines(self, lines: tuple[tuple[str, bool], ...]):
        """Lines filled from bottom (from top if newest at top), unused lines hidden"""
        unused = 0 if self.newest_at_top else self.line_count - len(lines)
        for index, bar in enumerate(self.bars):
            line = index - unused
            if not 0 <= line < len(lines):
                bar.hide()
                continue
            text, is_new = lines[line]
            bar.text = f" {text}"
            bar.fg = self.color_new_message if is_new else self.color_message
            bar.show()
            bar.update()
