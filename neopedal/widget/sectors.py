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
Sectors Widget
"""

from typing import TYPE_CHECKING

from .. import calculation as calc
from ..api_control import api
from ..const_common import (
    MAX_SECONDS,
    PREV_SECTOR_INDEX,
    SECTOR_ABBR_ID,
    TEXT_NOLAPTIME,
)
from ..module_info import minfo
from ..validator import valid_sectors
from ._base import Overlay

if TYPE_CHECKING:
    from ..template.widget_config_types import SectorsConfig

# Running time formatted uncached: new value every update, would evict lap times of tables from cache
running_laptime = calc.sec2laptime.__wrapped__


class Realtime(Overlay):
    """Draw widget"""

    wcfg: "SectorsConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        bar_gap = self.wcfg["bar_gap"]
        layout = self.set_grid_layout(gap=bar_gap)
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
        if self.wcfg["target_laptime"] == "Theoretical":
            self.prefix_best = "TB"
        else:
            self.prefix_best = "PB"
        self.extra_width = max(int(self.wcfg["extra_digits"]), 0)

        # Target time
        layout_laptime = self.set_grid_layout(gap=bar_gap)
        self.bar_style_time_target = (
            self.wcfg["font_color_time_loss"],
            self.wcfg["font_color_time_gain"],
            self.wcfg["font_color_target_time"],
        )
        self.bar_time_target = self.set_rawtext(
            text=f"{self.prefix_best}{TEXT_NOLAPTIME:>{9 + self.extra_width}}",
            width=font_m.width * (11 + self.extra_width) + bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.bar_style_time_target[2],
            bg_color=self.wcfg["background_color_target_time"],
        )
        layout_laptime.addWidget(self.bar_time_target, 0, 0)

        # Current time
        self.bar_time_curr = self.set_rawtext(
            text=f"{TEXT_NOLAPTIME:>{11 + self.extra_width}}",
            width=font_m.width * (11 + self.extra_width) + bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.wcfg["font_color_current_time"],
            bg_color=self.wcfg["background_color_current_time"],
        )
        layout_laptime.addWidget(self.bar_time_curr, 0, 1)

        # Gap to best sector time
        layout_sector = self.set_grid_layout(gap=bar_gap)
        self.bar_style_gap = (
            (
                self.wcfg["font_color_sector_highlighted"],
                self.wcfg["background_color_time_loss"],
            ),
            (
                self.wcfg["font_color_sector_highlighted"],
                self.wcfg["background_color_time_gain"],
            ),
            (
                self.wcfg["font_color_sector"],
                self.wcfg["background_color_sector"],
            ),
        )
        self.bars_time_gap = self.set_rawtext(
            width=font_m.width * (7 + self.extra_width) + bar_padx,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.bar_style_gap[2][0],
            bg_color=self.bar_style_gap[2][1],
            count=3,
        )
        for idx, bar_time_gap in enumerate(self.bars_time_gap):
            bar_time_gap.text = SECTOR_ABBR_ID[idx]
            layout_sector.addWidget(bar_time_gap, 0, idx)

        layout.addLayout(layout_laptime, self.wcfg["display_order_target_time"], 1)
        layout.addLayout(layout_sector, self.wcfg["display_order_sector_time"], 1)

        # Last data
        self.last_sector_idx = -1  # previous recorded sector index value
        self.last_target_time = MAX_SECONDS
        self.freeze_timer_start = 0.0  # sector timer start
        self.sector_start = 0.0  # game time when sector index changed
        self.sector_shown = True  # time of sector just finished shown (or not given by game)
        self.sector_late = False  # time of sector just finished not set within freeze duration, still awaited

    def post_update(self):
        self.last_sector_idx = -1  # resumed: synced again, sector just finished long ago never shown
        self.last_target_time = MAX_SECONDS
        self.freeze_timer_start = 0
        self.sector_start = 0.0
        self.sector_shown = True
        self.sector_late = False

    def timerEvent(self, event):
        """Update when vehicle on track"""
        # Read Sector data
        lap_stime = api.read.timing.start()
        lap_etime = api.read.timing.elapsed()
        laptime_curr = max(lap_etime - lap_stime, 0)

        if self.wcfg["enable_all_time_best_sectors"]:
            data = minfo.sectors.allTimeBest
        else:
            data = minfo.sectors.sessionBest
        if data.sectorIndex < 0:  # sector data reset, sector not known yet
            self.last_sector_idx = -1  # synced again once known
            return

        theoretical = self.wcfg["target_laptime"] == "Theoretical"
        sector_best = data.sectorBestTB if theoretical else data.sectorBestPB

        if self.last_sector_idx < 0:
            # Started, resumed or data reset: target & best sectors of current data, no sector just finished
            self.last_sector_idx = data.sectorIndex
            self.sector_shown = True
            self.last_target_time = calc.accumulated_sum(sector_best, data.sectorIndex)
            self.end_freeze(0, sector_best)
        elif self.last_sector_idx != data.sectorIndex:
            # Sector changed (time of sector just finished may be set by game a bit later)
            self.last_sector_idx = data.sectorIndex
            self.sector_start = lap_etime
            self.sector_shown = False
            self.sector_late = False
            self.freeze_timer_start = 0

        if not self.sector_shown:
            if data.recordedIndex == data.sectorIndex:  # time of sector just finished recorded
                # Activate freeze timer
                self.sector_shown = True
                self.freeze_timer_start = lap_etime

                # Previous sector index
                prev_s_idx = PREV_SECTOR_INDEX[data.sectorIndex]

                # Update (time target) gap & sector gap, none without best to compare with
                self.last_target_time = calc.accumulated_sum(sector_best, data.sectorIndex)
                if data.noDeltaSector if theoretical else data.noDeltaSectorPB:
                    self.update_time_target(self.bar_time_target, self.last_target_time)
                else:
                    delta_best = data.deltaSectorBestTB if theoretical else data.deltaSectorBestPB
                    self.update_time_target_gap(self.bar_time_target, delta_best, prev_s_idx)
                    self.update_sector_gap(self.bars_time_gap[prev_s_idx], delta_best[prev_s_idx])

                # Freeze previous sector time
                if valid_sectors(data.sectorPrev[prev_s_idx]):  # valid previous sector time
                    sum_sectortime = calc.accumulated_sum(data.sectorPrev, prev_s_idx)
                    if sum_sectortime < MAX_SECONDS:  # bypass invalid value
                        laptime_curr = sum_sectortime
                self.update_time_curr(self.bar_time_curr, laptime_curr, prev_s_idx)
            elif not self.sector_late and lap_etime - self.sector_start >= self.freeze_duration(
                    data.sectorPrev[data.sectorIndex]):
                # No sector time from game yet (lap without valid time, or set late): best sectors back at line,
                # gap still shown if game sets it before next sector (as module waits for it)
                self.sector_late = True
                self.last_target_time = calc.accumulated_sum(sector_best, data.sectorIndex)
                self.end_freeze(data.sectorIndex, sector_best)

        # Update freeze timer
        if self.freeze_timer_start:
            # Stop freeze timer after duration
            freeze_time = self.freeze_duration(data.sectorPrev[data.sectorIndex])
            if lap_etime - self.freeze_timer_start >= freeze_time:
                self.freeze_timer_start = 0  # stop timer
                self.end_freeze(data.sectorIndex, sector_best)
        else:
            # Update current sector time
            self.update_time_curr(self.bar_time_curr, laptime_curr, data.sectorIndex)

    def end_freeze(self, sector_index, sector_best):
        """Target time of current sector, best sector times restored when finish line crossed"""
        self.update_time_target(self.bar_time_target, self.last_target_time)
        if sector_index == 0:
            self.restore_best_sector(sector_best)

    # GUI update methods
    def update_sector_gap(self, target, data):
        """Gap to best sector time"""
        if target.last != data:
            target.last = data
            target.text = f"{data:+z.3f}"[:7 + self.extra_width]
            target.fg, target.bg = self.bar_style_gap[data < 0]
            target.update()

    def update_time_curr(self, target, data, prev_s_idx):
        """Current sector time text"""
        if target.last != data:
            target.last = data
            target.text = f"{SECTOR_ABBR_ID[prev_s_idx]}{running_laptime(data)[:8 + self.extra_width]:>{9 + self.extra_width}}"
            target.update()

    def update_time_target(self, target, seconds):
        """Target sector time text"""
        if seconds < MAX_SECONDS:  # bypass invalid value
            text_laptime = f"{self.prefix_best}{calc.sec2laptime(seconds)[:8 + self.extra_width]:>{9 + self.extra_width}}"
        else:
            text_laptime = f"{self.prefix_best}{TEXT_NOLAPTIME:>{9 + self.extra_width}}"
        target.text = text_laptime
        target.fg = self.bar_style_time_target[2]
        target.update()

    def update_time_target_gap(self, target, delta_sec, sec_index):
        """Target sector time gap"""
        sector_gap = calc.accumulated_sum(delta_sec, sec_index)
        target.text = f"{self.prefix_best}{sector_gap:>+{9 + self.extra_width}.3f}"[:11 + self.extra_width]
        target.fg = self.bar_style_time_target[sector_gap < 0]
        target.update()

    def restore_best_sector(self, sector_time):
        """Restore best sector time"""
        for idx, bar_time_gap in enumerate(self.bars_time_gap):
            if valid_sectors(sector_time[idx]):
                if self.wcfg["show_formatted_sector_time"]:
                    text_s = calc.sec2laptime(sector_time[idx])[:7 + self.extra_width]
                else:
                    text_s = f"{sector_time[idx]:.3f}"[:7 + self.extra_width]
            else:
                text_s = SECTOR_ABBR_ID[idx]
            bar_time_gap.text = text_s
            bar_time_gap.last = None  # same gap as last lap shown again
            bar_time_gap.fg, bar_time_gap.bg = self.bar_style_gap[2]
            bar_time_gap.update()

    # Sector data update methods
    def freeze_duration(self, seconds):
        """Set freeze duration"""
        if valid_sectors(seconds):
            max_freeze = seconds * 0.5
        else:
            max_freeze = 3
        return calc.zero_max(self.wcfg["freeze_duration"], max_freeze)
