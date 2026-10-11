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
Speed delta Widget

Speed difference to all time best, session best, stint best and last lap at same lap distance, smoothed
(speed_delta_smoothing_samples), positive when faster. A dash while there is no reference lap yet or no comparison on this lap (out lap
from pit lane or garage, in pit lane before start line).
"""

from __future__ import annotations

from .. import calculation as calc
from .. import units
from ..module_info import minfo
from ._base import Overlay
from ._common import delta_shown

# Reference laps: (option key, delta source of delta module, speed delta attribute, modern label)
REFERENCES = (
    ("all_time_best", "Best", "speedDeltaBest", "Best"),
    ("session_best", "Session", "speedDeltaSession", "Session"),
    ("stint_best", "Stint", "speedDeltaStint", "Stint"),
    ("last_lap", "Last", "speedDeltaLast", "Last"),
)


class SpeedDeltas:
    """Speed difference to each reference lap in speed unit (+ faster), smoothed (exponential moving average of
    samples updates, 1: none), None if not shown (smoothing starts again once shown)"""

    def __init__(self, unit_speed, samples: int):
        self.unit_speed = unit_speed
        self.ema = calc.ema_filter(max(int(samples), 1))
        self.smoothed: dict[str, float | None] = {key: None for key, *_ in REFERENCES}

    def read(self) -> dict[str, float | None]:
        delta = minfo.delta
        smoothed = self.smoothed
        for key, source, attribute, _ in REFERENCES:
            if not delta_shown(source):
                smoothed[key] = None
                continue
            value = self.unit_speed(getattr(delta, attribute))
            last = smoothed[key]
            smoothed[key] = value if last is None else self.ema(last, value)
        return dict(smoothed)


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
        self.decimals = max(int(self.wcfg["decimal_places"]), 0)
        self.display_range = calc.decimal_strip(self.wcfg["speed_delta_display_range"], self.decimals)
        self.speeds = SpeedDeltas(units.set_unit_speed(self.cfg.units["speed_unit"]),
                                  self.wcfg["speed_delta_smoothing_samples"])
        symbol = units.set_symbol_speed(self.cfg.units["speed_unit"])
        self.unit_text = f" {symbol}" if self.wcfg["show_speed_unit"] else ""
        self.max_padding = 4 + self.decimals + (self.decimals > 0)
        text_def = "-"

        shown = [key for key, *_ in REFERENCES if self.wcfg[f"show_{key}"]]
        prefix_just = max((len(self.wcfg[f"prefix_{key}"]) for key in shown), default=0) if self.wcfg["layout"] == 0 else 0
        self.prefixes = {key: self.wcfg[f"prefix_{key}"].ljust(prefix_just) for key in shown}
        self.bars = {}
        for key in shown:
            text = f"{self.prefixes[key]}{text_def:>{self.max_padding}}{self.unit_text}"
            sample = f"{self.prefixes[key]}{'8' * self.max_padding}{self.unit_text}"
            bar = self.set_rawtext(
                text=text,
                width=font_m.width * len(sample) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg[f"font_color_{key}"],
                bg_color=self.wcfg[f"background_color_{key}"],
                last=0,
            )
            self.set_primary_orient(target=bar, column=self.wcfg[f"display_order_{key}"])
            self.bars[key] = bar

    def timerEvent(self, event):
        """Update when vehicle on track"""
        values = self.speeds.read()
        for key, bar in self.bars.items():
            self.update_speed_delta(bar, values[key], self.prefixes[key])

    # GUI update methods
    def update_speed_delta(self, target, data: float | None, prefix: str):
        """Update speed difference"""
        if data is not None:
            data = round(calc.sym_max(data, self.display_range), self.decimals)
        if target.last != data:
            target.last = data
            if data is None:  # no reference lap, or no comparison on this lap
                text = f"{'-':>{self.max_padding}}"
            else:
                text = f"{data:>+{self.max_padding}.{self.decimals}f}"
            target.text = f"{prefix}{text}{self.unit_text}"
            target.update()
