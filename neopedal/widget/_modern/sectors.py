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
Sectors Widget, modern design

Top: target lap time (theoretical or personal best) or gap at last sector, and current time.
Bottom: one tile per sector, best sector time, or gap to it (gain or loss tint) after crossing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from ...const_common import MAX_SECONDS, PREV_SECTOR_INDEX, SECTOR_ABBR_ID
from ...module_info import SECTOR_CLASS_BEST, SECTOR_SLOWER, minfo, sector_color
from ...validator import valid_sectors
from .._common import player_vehicle
from .base import CENTER, DASH, LEFT, NO_LAPTIME, RIGHT, ModernOverlay, laptime_text, signed
from .draw import panel, rounded

if TYPE_CHECKING:
    from ...template.widget_config_types import SectorsConfig

NEUTRAL, GAIN, LOSS, CLASS_BEST = 0, 1, 2, 3  # loss: slower (gold), class best: best sector of class (purple)


class Realtime(ModernOverlay):
    """Draw widget"""

    wcfg: SectorsConfig

    options = (
        "font_size", "enable_all_time_best_sectors", "target_laptime", "freeze_duration",
        "show_formatted_sector_time", "extra_digits",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        unit = self.unit
        self.theoretical = wcfg["target_laptime"] == "Theoretical"
        self.target_label = "TB" if self.theoretical else "PB"
        # Characters of times as classic design: sector 7, lap 8, gap 9, plus extra digits (default 2: whole times)
        self.extra = max(int(wcfg["extra_digits"]), 0)
        self.add_font("time", 1.2, "bold")

        pad = unit * 0.3
        gap = unit * 0.2
        tile_w = self.text_width("value", self.sector_text("+8:88.888")) + unit * 0.9
        width = pad * 2 + tile_w * 3 + gap * 2
        top_h = unit * 1.75
        tile_h = unit * 2.2
        self.rect_target = QRectF(pad, pad, (width - pad * 2 - gap) / 2, top_h)
        self.rect_current = QRectF(self.rect_target.right() + gap, pad, self.rect_target.width(), top_h)
        tile_top = pad + top_h + gap
        self.rect_tiles = tuple(QRectF(pad + (tile_w + gap) * index, tile_top, tile_w, tile_h) for index in range(3))
        self.set_size(width, tile_top + tile_h + pad)

        # Display state
        self.target = (self.target_label, NO_LAPTIME, NEUTRAL)
        self.current = (SECTOR_ABBR_ID[0], NO_LAPTIME)
        self.tiles = [(SECTOR_ABBR_ID[index], "", NEUTRAL) for index in range(3)]
        self.last_sector_index = -1
        self.last_target_time = MAX_SECONDS
        self.freeze_timer_start = 0.0
        self.sector_start = 0.0  # game time when sector index changed
        self.sector_shown = True  # time of sector just finished shown (or not given by game)
        self.sector_late = False  # time of sector just finished not set within freeze duration, still awaited

    def post_update(self):
        self.last_sector_index = -1  # resumed: synced again, sector just finished long ago never shown
        self.last_target_time = MAX_SECONDS
        self.freeze_timer_start = 0.0
        self.sector_start = 0.0
        self.sector_shown = True
        self.sector_late = False

    def timerEvent(self, event):
        """Update when vehicle on track"""
        lap_start = api.read.timing.start()
        lap_elapsed = api.read.timing.elapsed()
        laptime_current = max(lap_elapsed - lap_start, 0)
        data = minfo.sectors.allTimeBest if self.wcfg["enable_all_time_best_sectors"] else minfo.sectors.sessionBest
        if data.sectorIndex < 0:  # sector data reset, sector not known yet
            self.last_sector_index = -1  # synced again once known
            return
        sector_best = data.sectorBestTB if self.theoretical else data.sectorBestPB
        delta_best = data.deltaSectorBestTB if self.theoretical else data.deltaSectorBestPB

        if self.last_sector_index < 0:
            # Started, resumed or data reset: target & best sectors of current data, no sector just finished
            self.last_sector_index = data.sectorIndex
            self.sector_shown = True
            self.last_target_time = calc.accumulated_sum(sector_best, data.sectorIndex)
            self.end_freeze(0, sector_best)
        elif self.last_sector_index != data.sectorIndex:  # sector changed
            self.last_sector_index = data.sectorIndex
            self.sector_start = lap_elapsed
            self.sector_shown = False
            self.sector_late = False
            self.freeze_timer_start = 0.0

        if not self.sector_shown:
            if data.recordedIndex == data.sectorIndex:  # time of sector just finished set by game: show & freeze
                self.sector_shown = True
                self.freeze_timer_start = lap_elapsed
                self.show_sector_gap(data, sector_best, delta_best)
                prev_index = PREV_SECTOR_INDEX[data.sectorIndex]
                if valid_sectors(data.sectorPrev[prev_index]):  # freeze previous sector time
                    total = calc.accumulated_sum(data.sectorPrev, prev_index)
                    if total < MAX_SECONDS:
                        laptime_current = total
                self.current = (SECTOR_ABBR_ID[prev_index], self.lap_text(laptime_current))
            elif not self.sector_late and lap_elapsed - self.sector_start >= self.freeze_time(
                    data.sectorPrev[data.sectorIndex]):
                # No sector time from game yet (lap without valid time, or set late): best sectors back at line,
                # gap still shown if game sets it before next sector (as module waits for it)
                self.sector_late = True
                self.last_target_time = calc.accumulated_sum(sector_best, data.sectorIndex)
                self.end_freeze(data.sectorIndex, sector_best)

        if self.freeze_timer_start:
            if lap_elapsed - self.freeze_timer_start >= self.freeze_time(data.sectorPrev[data.sectorIndex]):
                self.freeze_timer_start = 0.0
                self.end_freeze(data.sectorIndex, sector_best)
        else:
            self.current = (SECTOR_ABBR_ID[data.sectorIndex], self.lap_text(laptime_current, running=True))
        self.refresh((self.target, self.current, tuple(self.tiles)))

    def end_freeze(self, sector_index: int, sector_best):
        """Target time of current sector, best sectors back once finish line crossed"""
        target = self.last_target_time
        self.target = (self.target_label, self.lap_text(target), NEUTRAL)
        if sector_index == 0:
            self.restore_best_sectors(sector_best)

    def show_sector_gap(self, data, sector_best, delta_best):
        """Gap to target at sector just finished, gap to its best sector on its tile (none without best)"""
        prev_index = PREV_SECTOR_INDEX[data.sectorIndex]
        self.last_target_time = calc.accumulated_sum(sector_best, data.sectorIndex)
        if data.noDeltaSector if self.theoretical else data.noDeltaSectorPB:  # no best to compare with
            self.end_freeze(-1, sector_best)
            return
        gap = calc.accumulated_sum(delta_best, prev_index)
        self.target = (self.target_label, signed(gap, 3)[:9 + self.extra], GAIN if gap < 0 else LOSS)
        sector_gap = delta_best[prev_index]
        kind = GAIN if sector_gap < 0 else LOSS
        player = player_vehicle()  # best sector of class in session: purple, as driver lists & track map
        if sector_color(data.sectorPrev[prev_index], prev_index, player.sectors,
                        player.classBestSectors) == SECTOR_CLASS_BEST:
            kind = CLASS_BEST
        self.tiles[prev_index] = (SECTOR_ABBR_ID[prev_index], self.sector_text(signed(sector_gap, 3)), kind)

    def restore_best_sectors(self, sector_time):
        """Best sector times"""
        for index in range(3):
            if valid_sectors(sector_time[index]):
                if self.wcfg["show_formatted_sector_time"]:
                    text = self.sector_text(calc.sec2laptime(sector_time[index]))
                else:
                    text = self.sector_text(f"{sector_time[index]:.3f}")
            else:
                text = ""
            self.tiles[index] = (SECTOR_ABBR_ID[index], text, NEUTRAL)

    def lap_text(self, seconds: float, running: bool = False) -> str:
        """Lap time (as every overlay), cut as classic design (8 characters plus extra digits)"""
        return laptime_text(seconds, running=running)[:8 + self.extra]

    def sector_text(self, text: str) -> str:
        """Sector time or gap, cut as classic design (7 characters plus extra digits)"""
        return text[:7 + self.extra]

    def freeze_time(self, seconds: float) -> float:
        """Freeze duration, at most half of sector time"""
        max_freeze = seconds * 0.5 if valid_sectors(seconds) else 3
        return calc.zero_max(self.wcfg["freeze_duration"], max_freeze)

    def paint_static(self, painter: QPainter):
        theme = self.theme
        panel(painter, QRectF(self.rect()), theme, self.panel_radius(), self.depth_effects)
        for rect in (self.rect_target, self.rect_current):
            rounded(painter, rect, self.radius(0.3), theme.tint(theme.surface_alt, 170))

    def paint(self, painter: QPainter):
        theme = self.theme
        (label, text, kind), (cur_label, cur_text), tiles = self.state
        inner = self.unit * 0.45
        colors = (theme.text_dim, theme.positive, getattr(theme, SECTOR_SLOWER), theme.best)
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
