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
Deltabest Widget
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import calculation as calc
from ..api_control import api
from ..module_info import minfo
from ._base import Overlay
from ._common import delta_shown, game_deltabest, lap_delta_shown, lap_reference
from ._painter import fill_rect

if TYPE_CHECKING:
    from ..template.widget_config_types import DeltabestConfig

NO_DELTA_COLOR = "#888888"  # dash while no delta (no reference lap, or out lap)


class Realtime(Overlay):
    """Draw widget"""

    wcfg: DeltabestConfig

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)

        # Config font
        font = self.config_font(
            self.wcfg["font_name"],
            self.wcfg["font_size"],
            self.wcfg["font_weight"],
        )
        self.setFont(font)
        font_m = self.get_font_metrics(font)

        # Config variable
        self.delta_source = f"delta{self.wcfg['deltabest_source']}"
        self.bar_range = max(float(self.wcfg["delta_bar_display_range"]), 0.001)  # 0 = division by zero
        bar_gap = self.wcfg["bar_gap"]
        padx = round(font_m.width * self.wcfg["bar_padding_horizontal"])
        pady = round(font_m.capital * self.wcfg["bar_padding_vertical"])
        self.dbar_length = int(self.wcfg["delta_bar_length"] * 0.5)
        dbar_height = int(self.wcfg["delta_bar_height"])

        self.decimals = max(self.wcfg["decimal_places"], 1)
        self.delta_display_range = calc.decimal_strip(self.wcfg["delta_display_range"], self.decimals)
        self.max_padding = 4 + self.decimals
        self.delta_width = font_m.width * self.max_padding + padx * 2
        # Delta bar at least as wide as delta text (0 or negative length: widget of no width)
        self.dbar_length = max(self.dbar_length, int(self.delta_width * 0.5 + 0.5))
        delta_height = font_m.capital + pady * 2

        if self.wcfg["layout"] == 0:
            pos_y1 = 0
        else:
            pos_y1 = delta_height + bar_gap

        if self.wcfg["show_delta_bar"]:
            pos_x2 = self.dbar_length - self.delta_width * 0.5
        else:
            pos_x2 = 0

        if self.wcfg["layout"] == 0 and self.wcfg["show_delta_bar"]:
            pos_y2 = dbar_height + bar_gap
        else:
            pos_y2 = 0

        self.rect_deltabar = QRectF(0, pos_y1, self.dbar_length * 2, dbar_height)
        self.rect_deltapos = QRectF(0, pos_y1, self.dbar_length, dbar_height)
        self.rect_delta = QRectF(pos_x2, pos_y2, self.delta_width, delta_height)
        self.rect_text_delta = self.rect_delta.adjusted(0, font_m.voffset, 0, 0)

        self.freeze_duration = min(max(self.wcfg["freeze_duration"], 0), 30)
        self.source = self.wcfg["deltabest_source"]
        self.game_delta = self.wcfg["show_game_deltabest_if_available"]
        self.show_bar = self.wcfg["show_delta_bar"]
        # Colors parsed once (not on every repaint)
        self.delta_color = (QColor(self.wcfg["background_color_time_gain"]),
                            QColor(self.wcfg["background_color_time_loss"]))
        self.no_delta_color = QColor(NO_DELTA_COLOR)
        self.bar_color = QColor(self.wcfg["background_color_delta_bar"])
        self.box_color = QColor(self.wcfg["background_color_deltabest"])

        # Config canvas
        if self.wcfg["show_delta_bar"]:
            self.resize(self.dbar_length * 2, dbar_height + bar_gap + delta_height)
        else:
            self.resize(self.delta_width, delta_height)

        self.pen_text = QPen()
        # Lap invalidated by game: outline of delta box in time loss color
        outline_width = max(round(font_m.capital * 0.15), 2)
        self.pen_invalid = QPen(QColor(self.delta_color[1]), outline_width)
        self.pen_invalid.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        self.outline_inset = outline_width / 2

        # Last data
        self.delta_best: float | None = 0.0  # None: no delta (no reference lap, or out lap)
        self.invalid = False
        self.state: tuple | None = None  # as drawn: delta text, loss, bar position (device pixels), invalid
        self.last_laptime = 0.0
        self.new_lap = True

    def timerEvent(self, event):
        """Update when vehicle on track"""
        temp_best: float | None
        if minfo.delta.lapTimeCurrent < self.freeze_duration:
            temp_best = minfo.delta.lapTimeLast - self.last_laptime if lap_delta_shown(self.last_laptime) else None
            self.new_lap = True
        else:
            if self.new_lap:  # reference of lap under way, as live delta (game delta: game best lap)
                self.last_laptime = lap_reference(self.source, self.game_delta)
                self.new_lap = False

            if delta_shown(self.source):  # else no reference lap, or out lap
                temp_best = getattr(minfo.delta, self.delta_source)
                if self.game_delta:
                    temp_best = game_deltabest(temp_best)
            else:
                temp_best = None

        invalid = self.wcfg["show_invalid_lap_highlight"] and api.read.lap.invalidated()
        # Repainted only when drawing changes: text as displayed, color, bar moved a device pixel
        bar_position = 0
        if self.show_bar and temp_best is not None:
            delta_pos = self.delta_position(self.bar_range, temp_best, self.dbar_length)
            bar_position = round(delta_pos * self.devicePixelRatioF())
        state = (self.delta_text(temp_best), temp_best is not None and temp_best > 0, bar_position, invalid)
        if self.state != state:
            self.state = state
            self.delta_best = temp_best
            self.invalid = invalid
            self.update()

    # GUI update methods
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        delta = 0.0 if self.delta_best is None else self.delta_best
        delta_pos = self.delta_position(
            self.bar_range,
            delta,
            self.dbar_length)
        highlight_color = self.no_delta_color if self.delta_best is None else self.delta_color[delta > 0]

        # Draw deltabar
        if self.show_bar:
            self.rect_deltapos.setLeft(delta_pos)
            fill_rect(painter, self.rect_deltabar, self.bar_color)
            # Time gain: bar left edge right of center (negative width), normalized so corners & shading apply
            fill_rect(painter, self.rect_deltapos.normalized(), highlight_color)

            if self.wcfg["enable_animated_deltabest"]:
                pos_x = calc.zero_max(
                    delta_pos - self.delta_width * 0.5,
                    self.dbar_length * 2 - self.delta_width,
                )
                self.rect_delta.moveLeft(pos_x)
                self.rect_text_delta.moveLeft(pos_x)

        # Draw delta readings
        if self.wcfg["swap_style"]:
            self.pen_text.setColor(self.box_color)
            bg_color = highlight_color
        else:
            self.pen_text.setColor(highlight_color)
            bg_color = self.box_color

        fill_rect(painter, self.rect_delta, bg_color)
        painter.setPen(self.pen_text)
        painter.drawText(self.rect_text_delta, Qt.AlignmentFlag.AlignCenter, self.delta_text(self.delta_best))
        if self.invalid:
            inset = self.outline_inset
            painter.setPen(self.pen_invalid)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect_delta.adjusted(inset, inset, -inset, -inset))

    def delta_text(self, delta: float | None) -> str:
        """Delta as displayed (never -0.000), dash if none"""
        if delta is None:
            return "-"
        return f"{calc.sym_max(delta, self.delta_display_range):+z.{self.decimals}f}"[:self.max_padding]

    # Additional methods
    def delta_position(self, rng, delta, length):
        """Delta position"""
        return (1 - calc.sym_max(delta, rng) / rng) * length
