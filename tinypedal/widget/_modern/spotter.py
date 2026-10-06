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
Spotter Widget, modern design

Side bars with rounded ends: lit part glows toward screen center, its color going from warning
to loss color as the car alongside gets closer sideways. Green clear signal fading out once a
side is free again, rising warning glow at bottom of bar for a car coming up behind.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath

from .._race_aids import HiddenPreview
from ..spotter import APPROACH_ZONE, CLEAR_STEPS, NO_STATE, Side, SpotterMixin
from .base import ModernOverlay
from .draw import rounded

GLOW_ALPHA = 70  # soft light of lit part, toward screen center
CLEAR_ALPHA = 220
APPROACH_ALPHA = 210
PREVIEW_ALPHA = 140  # bar track while overlay unlocked


def blend(low: QColor, high: QColor, fraction: float) -> QColor:
    """Color between low & high"""
    fraction = min(max(fraction, 0.0), 1.0)
    return QColor.fromRgbF(
        low.redF() + (high.redF() - low.redF()) * fraction,
        low.greenF() + (high.greenF() - low.greenF()) * fraction,
        low.blueF() + (high.blueF() - low.blueF()) * fraction,
    )


class Realtime(HiddenPreview, SpotterMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "bar_width", "bar_height", "horizontal_gap", "vehicle_length", "vehicle_width", "nearby_side_distance",
        "critical_side_distance", "show_clear_signal", "clear_signal_duration", "show_approaching_cars",
        "approaching_distance", "show_bar_background",
    )

    def design_unit(self) -> float:
        """Bar width sets size"""
        return float(self.wcfg["bar_width"])

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.setup_spotter()
        wcfg = self.wcfg
        theme = self.theme
        bar_w = max(float(wcfg["bar_width"]), 1.0)
        bar_h = max(float(wcfg["bar_height"]), 4.0)
        gap = max(float(wcfg["horizontal_gap"]), 0.0)
        self.bars = (QRectF(0, 0, bar_w, bar_h), QRectF(bar_w + gap, 0, bar_w, bar_h))
        self.set_size(bar_w * 2 + gap, bar_h)
        self.bar_radius = bar_w / 2 * min(self.corner, 1.0)
        self.glow = min(bar_w * 0.7, gap / 2)  # toward screen center only (bars sit on screen edges)
        self.show_background = bool(wcfg["show_bar_background"])
        self.color_track = theme.tint(theme.surface_raised, PREVIEW_ALPHA)
        self.color_clear = theme.tint(theme.positive, CLEAR_ALPHA)
        self.updated = False  # bar tracks drawn before first update (picture of Overlays page)
        self.state = NO_STATE

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.updated = True
        self.refresh(self.read_spotter())

    def paintEvent(self, event):
        """Draw while a side is lit, signaled or watched (or overlay unlocked, or not updated yet)"""
        if self.state.shown or self.show_background or self.previewing() or not self.updated:
            super().paintEvent(event)

    def paint(self, painter: QPainter):
        theme = self.theme
        state = self.state
        track = self.show_background or self.previewing() or not self.updated
        for index, (bar, overlap, clear, approach) in enumerate(zip(self.bars, state[:2], state.clear, state.approach)):
            inward = 1 if index == 0 else -1  # glow side
            if track:
                rounded(painter, bar, self.bar_radius, self.color_track)
            if clear:
                painter.setOpacity(clear / CLEAR_STEPS)
                self.glow_part(painter, bar, inward, theme.positive)
                rounded(painter, bar, self.bar_radius, self.color_clear)
                painter.setOpacity(1.0)
            if approach and not (overlap.lit and overlap.bottom >= 1.0):
                self.approach_part(painter, bar, approach)
            if overlap.lit:
                self.lit_part(painter, bar, overlap, inward)

    def lit_part(self, painter: QPainter, bar: QRectF, overlap: Side, inward: int):
        """Part of bar overlapped by car alongside"""
        theme = self.theme
        color = theme.negative if overlap.critical else blend(theme.warning, theme.negative, overlap.closeness * 0.6)
        lit = QRectF(bar.left(), bar.top() + bar.height() * overlap.top, bar.width(),
                     bar.height() * (overlap.bottom - overlap.top))
        self.glow_part(painter, lit, inward, color)
        rounded(painter, lit, self.bar_radius, color)

    def glow_part(self, painter: QPainter, rect: QRectF, inward: int, color: QColor):
        """Soft light beside bar part, toward screen center"""
        if self.glow < 1:
            return
        if inward > 0:
            glow = QRectF(rect.left(), rect.top(), rect.width() + self.glow, rect.height())
            edge_from, edge_to = rect.right(), glow.right()
        else:
            glow = QRectF(rect.left() - self.glow, rect.top(), rect.width() + self.glow, rect.height())
            edge_from, edge_to = rect.left(), glow.left()
        gradient = QLinearGradient(edge_from, 0, edge_to, 0)
        gradient.setColorAt(0.0, self.theme.tint(color, GLOW_ALPHA))
        gradient.setColorAt(1.0, self.theme.tint(color, 0))
        path = QPainterPath()
        radius = min(self.bar_radius + self.glow / 2, glow.width() / 2, glow.height() / 2)
        path.addRoundedRect(glow, radius, radius)
        painter.fillPath(path, QBrush(gradient))

    def approach_part(self, painter: QPainter, bar: QRectF, approach: float):
        """Rising glow at bottom of bar: car coming up behind"""
        zone = bar.height() * APPROACH_ZONE
        gradient = QLinearGradient(0, bar.bottom(), 0, bar.bottom() - zone)
        color = self.theme.warning
        gradient.setColorAt(0.0, self.theme.tint(color, round(APPROACH_ALPHA * approach)))
        gradient.setColorAt(1.0, self.theme.tint(color, 0))
        path = QPainterPath()
        path.addRoundedRect(QRectF(bar.left(), bar.bottom() - zone, bar.width(), zone), self.bar_radius, self.bar_radius)
        painter.fillPath(path, QBrush(gradient))
