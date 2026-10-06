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
Deltabest Widget, modern design

Delta to reference lap: large signed number in gain or loss color, on a pill that slides
along a center bar (time gain fills right, loss fills left). Pill outlined in loss color while
game invalidated current lap (track limits). A dash while there is no reference lap or no
delta to show (out lap from pit lane or garage, in pit lane before start line).
"""

from __future__ import annotations

from math import isfinite

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen

from ... import calculation as calc
from ...api_control import api
from ...module_info import minfo
from .._common import delta_shown, game_deltabest, lap_delta_shown
from .base import CENTER, DASH, ModernOverlay
from .draw import panel, readable_on, rounded


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "decimal_places", "deltabest_source", "show_game_deltabest_if_available",
        "swap_style", "show_delta_bar", "delta_bar_length", "delta_bar_display_range",
        "delta_display_range", "freeze_duration", "enable_animated_deltabest", "show_invalid_lap_indicator",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.add_font("delta", 1.45, "bold")
        self.source = wcfg["deltabest_source"]
        self.laptime_source = f"lapTime{wcfg['deltabest_source']}"
        self.delta_source = f"delta{wcfg['deltabest_source']}"
        self.decimals = max(int(wcfg["decimal_places"]), 1)
        self.delta_range = calc.decimal_strip(wcfg["delta_display_range"], self.decimals)
        self.bar_range = max(float(wcfg["delta_bar_display_range"]), 0.001)
        self.freeze_duration = min(max(wcfg["freeze_duration"], 0), 30)
        self.animated = wcfg["enable_animated_deltabest"] and wcfg["show_delta_bar"]
        self.game_delta = wcfg["show_game_deltabest_if_available"]
        self.swap_style = wcfg["swap_style"]
        self.show_invalid = wcfg["show_invalid_lap_indicator"]

        pad = unit * 0.35
        sample = "+" + "8" * 2 + "." + "8" * self.decimals
        self.pill_w = self.text_width("delta", sample) + unit * 1.0
        pill_h = unit * 1.9
        bar_h = max(unit * 0.38, 4.0) if wcfg["show_delta_bar"] else 0
        gap = unit * 0.3 if bar_h else 0
        width = max(float(wcfg["delta_bar_length"]), self.pill_w + pad * 2) if bar_h else self.pill_w + pad * 2
        height = pad * 2 + pill_h + gap + bar_h
        bar_top, pill_top = (pad, pad + bar_h + gap) if wcfg["layout"] == 0 else (pad + pill_h + gap, pad)
        self.rect_bar = QRectF(pad, bar_top, width - pad * 2, bar_h)
        self.rect_pill = QRectF((width - self.pill_w) / 2, pill_top, self.pill_w, pill_h)
        self.set_size(width, height)

        self.delta_best = 0.0
        self.last_laptime = 0.0
        self.new_lap = True

    def timerEvent(self, event):
        """Update when vehicle on track"""
        info = minfo.delta
        delta: float | None
        if info.lapTimeCurrent < self.freeze_duration:  # lap just completed against reference
            last = self.last_laptime
            delta = info.lapTimeLast - last if lap_delta_shown(last) else None
            self.new_lap = True
        else:
            if self.new_lap:
                self.last_laptime = getattr(info, self.laptime_source)
                self.new_lap = False
            delta = getattr(info, self.delta_source) if delta_shown(self.source) else None
            if delta is not None and self.game_delta:
                delta = game_deltabest(delta)
        invalid = self.show_invalid and api.read.lap.invalidated()
        if delta is not None:
            delta = round(delta, self.decimals + 1) if isfinite(delta) else 0.0
        self.refresh((delta, invalid))

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        if self.rect_bar.height():
            rounded(painter, self.rect_bar, self.rect_bar.height() / 2, theme.surface_raised)

    def paint(self, painter: QPainter):
        theme = self.theme
        delta, invalid = self.state
        if delta is None:  # no reference lap, or no delta on this lap
            pill = self.rect_pill
            rounded(painter, pill, self.radius(0.4), theme.tint(theme.text_dim, 30))
            self.draw_text(painter, pill, DASH, "delta", theme.text_dim, CENTER, elide=False)
            if self.rect_bar.height():
                center = self.rect_bar.center().x()
                bar = self.rect_bar
                painter.fillRect(QRectF(center - 1, bar.top() - bar.height() * 0.35, 2, bar.height() * 1.7),
                                 theme.text_dim)
            return
        color = theme.negative if delta > 0 else theme.positive
        bar = self.rect_bar
        fraction = calc.sym_max(delta, self.bar_range) / self.bar_range  # -1 to 1, gain < 0
        center = bar.center().x()
        if bar.height():
            length = bar.width() / 2 * abs(fraction)
            fill = QRectF(center - length if delta > 0 else center, bar.top(), length, bar.height())
            rounded(painter, fill, bar.height() / 2, color)
            painter.fillRect(QRectF(center - 1, bar.top() - bar.height() * 0.35, 2, bar.height() * 1.7), theme.text_dim)
        pill = QRectF(self.rect_pill)
        if self.animated:
            left = center - fraction * bar.width() / 2 - pill.width() / 2
            pill.moveLeft(min(max(left, bar.left()), bar.right() - pill.width()))
        text = f"{calc.sym_max(delta, self.delta_range):+.{self.decimals}f}"
        if self.swap_style:  # delta color as pill fill
            rounded(painter, pill, self.radius(0.4), color)
            self.draw_text(painter, pill, text, "delta", readable_on(color), CENTER, elide=False)
        else:
            rounded(painter, pill, self.radius(0.4), theme.tint(color, 46))
            self.draw_text(painter, pill, text, "delta", color, CENTER, elide=False)
        if invalid:  # lap invalidated by game: loss colored outline
            width = max(self.unit * 0.14, 2.0)
            pen = QPen(theme.negative, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            radius = max(min(self.radius(0.4), pill.height() / 2) - width / 2, 0)
            inner = pill.adjusted(width / 2, width / 2, -width / 2, -width / 2)
            painter.drawRoundedRect(inner, radius, radius)
