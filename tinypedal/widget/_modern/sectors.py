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
Sectors Widget, modern design

Top: target lap time (theoretical or personal best) or gap at last sector, and current time.
Bottom: one tile per sector, best sector time, or gap to it (gain or loss tint) after crossing.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from ...const_common import MAX_SECONDS, PREV_SECTOR_INDEX, SECTOR_ABBR_ID, TEXT_NOLAPTIME
from ...module_info import minfo
from ...validator import valid_sectors
from .base import CENTER, DASH, LEFT, RIGHT, ModernOverlay
from .draw import panel, rounded

NEUTRAL, GAIN, LOSS = 0, 1, 2


class Realtime(ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "enable_all_time_best_sectors", "target_laptime", "freeze_duration",
        "show_formatted_sector_time",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.theoretical = wcfg["target_laptime"] == "Theoretical"
        self.target_label = "TB" if self.theoretical else "PB"
        self.add_font("time", 1.2, "bold")

        pad = unit * 0.3
        gap = unit * 0.2
        tile_w = self.text_width("value", "+8:88.888") + unit * 0.9
        width = pad * 2 + tile_w * 3 + gap * 2
        top_h = unit * 1.75
        tile_h = unit * 2.2
        self.rect_target = QRectF(pad, pad, (width - pad * 2 - gap) / 2, top_h)
        self.rect_current = QRectF(self.rect_target.right() + gap, pad, self.rect_target.width(), top_h)
        tile_top = pad + top_h + gap
        self.rect_tiles = tuple(QRectF(pad + (tile_w + gap) * index, tile_top, tile_w, tile_h) for index in range(3))
        self.set_size(width, tile_top + tile_h + pad)

        # Display state
        self.target = (self.target_label, TEXT_NOLAPTIME, NEUTRAL)
        self.current = (SECTOR_ABBR_ID[0], TEXT_NOLAPTIME)
        self.tiles = [(SECTOR_ABBR_ID[index], "", NEUTRAL) for index in range(3)]
        self.last_sector_index = -1
        self.last_target_time = MAX_SECONDS
        self.freeze_timer_start = 0.0

    def post_update(self):
        self.last_sector_index = -1
        self.last_target_time = MAX_SECONDS
        self.freeze_timer_start = 0.0

    def timerEvent(self, event):
        """Update when vehicle on track"""
        lap_start = api.read.timing.start()
        lap_elapsed = api.read.timing.elapsed()
        laptime_current = max(lap_elapsed - lap_start, 0)
        data = minfo.sectors.allTimeBest if self.wcfg["enable_all_time_best_sectors"] else minfo.sectors.sessionBest
        sector_best = data.sectorBestTB if self.theoretical else data.sectorBestPB
        delta_best = data.deltaSectorBestTB if self.theoretical else data.deltaSectorBestPB

        if self.last_sector_index != data.sectorIndex:  # sector changed
            self.freeze_timer_start = lap_elapsed
            self.last_sector_index = data.sectorIndex
            prev_index = PREV_SECTOR_INDEX[data.sectorIndex]
            self.last_target_time = calc.accumulated_sum(sector_best, data.sectorIndex)
            gap = calc.accumulated_sum(delta_best, prev_index)
            self.target = (self.target_label, f"{gap:+.3f}", GAIN if gap < 0 else LOSS)
            if not data.noDeltaSector:
                sector_gap = delta_best[prev_index]
                self.tiles[prev_index] = (SECTOR_ABBR_ID[prev_index], f"{sector_gap:+.3f}", GAIN if sector_gap < 0 else LOSS)
            if valid_sectors(data.sectorPrev[prev_index]):  # freeze previous sector time
                total = calc.accumulated_sum(data.sectorPrev, prev_index)
                if total < MAX_SECONDS:
                    laptime_current = total
            self.current = (SECTOR_ABBR_ID[prev_index], calc.sec2laptime(laptime_current))

        if self.freeze_timer_start:
            if lap_elapsed - self.freeze_timer_start >= self.freeze_time(data.sectorPrev[data.sectorIndex]):
                self.freeze_timer_start = 0.0
                target = self.last_target_time
                self.target = (self.target_label, calc.sec2laptime(target) if target < MAX_SECONDS else TEXT_NOLAPTIME, NEUTRAL)
                if data.sectorIndex == 0:  # crossed finish line: show best sectors again
                    self.restore_best_sectors(sector_best)
        else:
            self.current = (SECTOR_ABBR_ID[data.sectorIndex], calc.sec2laptime(laptime_current))
        self.refresh((self.target, self.current, tuple(self.tiles)))

    def restore_best_sectors(self, sector_time):
        """Best sector times"""
        for index in range(3):
            if valid_sectors(sector_time[index]):
                if self.wcfg["show_formatted_sector_time"]:
                    text = calc.sec2laptime(sector_time[index])
                else:
                    text = f"{sector_time[index]:.3f}"
            else:
                text = ""
            self.tiles[index] = (SECTOR_ABBR_ID[index], text, NEUTRAL)

    def freeze_time(self, seconds: float) -> float:
        """Freeze duration, at most half of sector time"""
        max_freeze = seconds * 0.5 if valid_sectors(seconds) else 3
        return calc.zero_max(self.wcfg["freeze_duration"], max_freeze)

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        for rect in (self.rect_target, self.rect_current):
            rounded(painter, rect, self.radius(0.3), theme.tint(theme.surface_alt, 170))

    def paint(self, painter: QPainter):
        theme = self.theme
        (label, text, kind), (cur_label, cur_text), tiles = self.state
        inner = self.unit * 0.45
        colors = (theme.text_dim, theme.positive, theme.warning)
        # Target & current time
        target = self.rect_target.adjusted(inner, 0, -inner, 0)
        self.draw_text(painter, target, label, "label", theme.text_muted, LEFT)
        self.draw_text(painter, target, text, "value", colors[kind], RIGHT)
        current = self.rect_current.adjusted(inner, 0, -inner, 0)
        self.draw_text(painter, current, cur_label, "label", theme.accent, LEFT)
        self.draw_text(painter, current, cur_text, "time", theme.text, RIGHT)
        # Sector tiles
        for rect, (sector, value, kind) in zip(self.rect_tiles, tiles):
            if kind == NEUTRAL:
                rounded(painter, rect, self.radius(0.3), theme.tint(theme.surface_alt, 170))
            else:
                rounded(painter, rect, self.radius(0.3), theme.tint(colors[kind], 60))
                rounded(painter, QRectF(rect.left(), rect.bottom() - self.unit * 0.14, rect.width(), self.unit * 0.14),
                        self.unit * 0.07, colors[kind])
            label_rect = QRectF(rect.left(), rect.top() + self.unit * 0.15, rect.width(), self.unit * 0.8)
            self.draw_text(painter, label_rect, sector, "label", theme.text_muted, CENTER)
            value_rect = QRectF(rect.left(), label_rect.bottom(), rect.width(), rect.height() - label_rect.height() - self.unit * 0.3)
            self.draw_text(painter, value_rect, value or DASH, "value",
                           theme.text if kind != NEUTRAL else (theme.text_dim if value else theme.text_faint), CENTER)
