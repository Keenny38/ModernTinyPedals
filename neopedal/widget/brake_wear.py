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
Brake Wear Widget
"""

from typing import TYPE_CHECKING

from ..const_common import TEXT_NA
from ..module_info import minfo
from ._data import brake_wear_data
from ._wear import WearSections

if TYPE_CHECKING:
    from ..template.widget_config_types import BrakeWearConfig

SECTIONS = (
    ("remain", "remaining"),  # remaining brake thickness
    ("diff", "wear_difference"),  # wear difference
    ("live", "live_wear_difference"),  # live wear difference
    ("laps", "lifespan_laps"),  # estimated lifespan in laps
    ("mins", "lifespan_minutes"),  # estimated lifespan in minutes
)


class Realtime(WearSections):
    """Draw widget"""

    wcfg: "BrakeWearConfig"

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        self.threshold_remaining = min(max(self.wcfg["warning_threshold_remaining"], 0), 100) * 0.01
        self.set_wear_sections(SECTIONS)
        self.shown = tuple(self.wcfg[f"show_{option}"] for _, option in SECTIONS)  # read on every update
        self.shown_bars = tuple(  # (bars, style) of shown sections
            (getattr(self, f"bars_{name}"), getattr(self, f"bar_style_{name}"))
            for (name, _), shown in zip(SECTIONS, self.shown) if shown)
        self.thresholds = tuple(
            self.wcfg[f"warning_threshold_{name}"] for name in ("remaining", "wear", "laps", "minutes"))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wheels = minfo.wheels
        thickness = self.wcfg["show_thickness"]
        laptime_pace = minfo.delta.lapTimePace
        (show_remaining, show_wear_difference, show_live_wear_difference, show_lifespan_laps,
         show_lifespan_minutes) = self.shown
        _, warn_wear, warn_laps, warn_minutes = self.thresholds

        for idx in range(4):
            # Millimeters (above failure thickness) or percent
            (failed, remaining, _, wear, wear_percent, live, live_percent, laps, minutes,
             usable, available) = brake_wear_data(wheels, idx, thickness, laptime_pace)

            # No game data yet, spectated car
            if not available:
                for bars, style in self.shown_bars:
                    if bars[idx].last is not None:
                        self.set_unavailable(bars[idx], style)
                continue

            # Remaining brake thickness
            if show_remaining:
                if thickness:
                    threshold_remaining = self.threshold_remaining * usable
                else:
                    threshold_remaining = self.threshold_remaining * 100
                target = self.bars_remain[idx]
                if target.last != (remaining, failed):  # drawn again once changed
                    self.set_wear(target, remaining, self.bar_style_remain, remaining <= threshold_remaining, failed)
                    target.last = (remaining, failed)  # failure shown even if nothing left before

            # Wear differences
            if show_wear_difference:
                target = self.bars_diff[idx]
                if target.last != wear:  # drawn again once changed
                    self.set_wear(target, wear, self.bar_style_diff, wear_percent > warn_wear)

            # Live wear difference
            if show_live_wear_difference:
                target = self.bars_live[idx]
                if target.last != live:  # drawn again once changed
                    self.set_wear(target, live, self.bar_style_live, live_percent > warn_wear)

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

    @staticmethod
    def set_unavailable(target, style):
        """Wheel value not available, shown as at start"""
        target.last = None
        target.text = TEXT_NA
        target.fg = style[0]
        target.update()
