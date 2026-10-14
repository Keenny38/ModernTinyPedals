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
Tyre Wear Widget
"""

from typing import TYPE_CHECKING

from ..module_info import minfo
from ._data import run_laps, tyre_wear_data
from ._wear import WearSections

if TYPE_CHECKING:
    from ..template.widget_config_types import TyreWearConfig

SECTIONS = (
    ("remain", "remaining"),  # remaining tyre tread
    ("diff", "wear_difference"),  # wear difference
    ("live", "live_wear_difference"),  # live wear difference
    ("lock", "flat_spot"),  # flat spot wear
    ("laps", "lifespan_laps"),  # estimated lifespan in laps
    ("mins", "lifespan_minutes"),  # estimated lifespan in minutes
    ("end", "end_stint_remaining"),  # estimated end stint remaining tyre tread
)


class Realtime(WearSections):
    """Draw widget"""

    wcfg: "TyreWearConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        self.set_wear_sections(SECTIONS)
        self.shown = tuple(self.wcfg[f"show_{option}"] for _, option in SECTIONS)  # read on every update
        self.thresholds = tuple(
            self.wcfg[f"warning_threshold_{name}"] for name in ("remaining", "wear", "laps", "minutes"))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wheels = minfo.wheels
        laptime_pace = minfo.delta.lapTimePace
        est_runlaps = run_laps(minfo.fuel, minfo.energy)
        (show_remaining, show_wear_difference, show_live_wear_difference, show_flat_spot, show_lifespan_laps,
         show_lifespan_minutes, show_end_stint_remaining) = self.shown
        warn_remaining, warn_wear, warn_laps, warn_minutes = self.thresholds

        for idx in range(4):
            remaining, wear, live, flat_spot, laps, minutes, end = tyre_wear_data(
                wheels, idx, laptime_pace, est_runlaps)

            # Remaining tyre tread
            if show_remaining:
                target = self.bars_remain[idx]
                if target.last != remaining:  # drawn again once changed
                    self.set_wear(target, remaining, self.bar_style_remain, remaining <= warn_remaining)

            # Wear differences
            if show_wear_difference:
                target = self.bars_diff[idx]
                if target.last != wear:  # drawn again once changed
                    self.set_wear(target, wear, self.bar_style_diff, wear > warn_wear)

            # Live wear difference
            if show_live_wear_difference:
                target = self.bars_live[idx]
                if target.last != live:  # drawn again once changed
                    self.set_wear(target, live, self.bar_style_live, live > warn_wear)

            # Flat spot wear
            if show_flat_spot:
                target = self.bars_lock[idx]
                if target.last != flat_spot:  # drawn again once changed
                    self.set_wear(target, flat_spot, self.bar_style_lock, flat_spot > warn_wear)

            # Estimated lifespan in laps
            if show_lifespan_laps:
                target = self.bars_laps[idx]
                if target.last != laps:  # drawn again once changed
                    self.set_wear(target, laps, self.bar_style_laps, laps <= warn_laps)

            # Estimated lifespan in minutes
            if show_lifespan_minutes:
                target = self.bars_mins[idx]
                if target.last != minutes:  # drawn again once changed
                    self.set_wear(target, minutes, self.bar_style_mins, minutes <= warn_minutes)

            # Estimated end stint remaining tyre tread
            if show_end_stint_remaining:
                target = self.bars_end[idx]
                if target.last != end:  # drawn again once changed
                    self.set_wear(target, end, self.bar_style_end, end <= warn_remaining)
