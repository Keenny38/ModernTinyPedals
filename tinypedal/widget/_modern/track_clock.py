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
Track clock Widget, modern design

Track time of day, time scale, countdown to next sunrise or sunset.
"""

from __future__ import annotations

from time import gmtime, strftime

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ...api_control import api
from ...const_common import TEXT_NA
from ...i18n import tr_overlay
from ...module_info import minfo
from .base import ModernOverlay, clock_samples, display_order_options
from .stats import Stat, StatsMixin, Value

# Sunlight phase index (see module_mapping.set_sunlight_phase) -> label, is night coming
PHASES = {0: ("Sunrise", False), 1: ("Midday", False), 2: ("Sunset", True), 3: ("Midnight", True)}


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "show_track_clock", "enable_track_clock_synchronization",
        "track_clock_time_scale", "track_clock_format", "show_time_scale",
        "show_sunlight_phase_countdown", "enable_time_scaled_countdown",
        *display_order_options("track_clock"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        stats = []
        if wcfg["show_track_clock"]:
            sample = self.widest("strong", clock_samples(wcfg["track_clock_format"]))
            stats.append(Stat("track_clock", "Track time", sample, "strong", self.theme.warning))
        if wcfg["show_time_scale"]:
            stats.append(Stat("time_scale", "Scale", "x88"))
        if wcfg["show_sunlight_phase_countdown"]:
            phase = self.widest("small", (tr_overlay(label).upper() for label, _ in PHASES.values()))
            stats.append(Stat("countdown", "Next phase", "-88:88:88", sub_sample=phase))
        stats = self.display_ordered(stats, names={"countdown": "sunlight_phase_countdown"})
        self.keys = tuple(stat.key for stat in stats)
        self.time_scale_override = max(int(wcfg["track_clock_time_scale"]), 0)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0, show_sub=wcfg["show_sunlight_phase_countdown"])
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        if self.wcfg["enable_track_clock_synchronization"]:
            time_scale = api.read.session.time_scale()
        else:
            time_scale = self.time_scale_override
        track_time = api.read.session.track_time()
        if track_time < 0:
            track_time = calc.clock_time(api.read.session.elapsed(), api.read.session.start(), time_scale)
        track_time = calc.zero_max(track_time, 86400)
        values = []
        for key in self.keys:
            if key == "track_clock":
                values.append(Value(strftime(self.wcfg["track_clock_format"], gmtime(track_time))))
            elif key == "time_scale":
                values.append(Value(f"x{time_scale}" if 0 <= time_scale <= 60 else TEXT_NA, theme.text_dim))
            elif key == "countdown":
                countdown, phase = self.next_phase(track_time, time_scale)
                label, night = PHASES.get(phase, ("Sunrise", False))
                values.append(Value(f"-{calc.sec2countdown(abs(countdown))}", theme.text,
                                    sub=tr_overlay(label).upper(), sub_color=theme.blue if night else theme.warning))
        self.refresh(tuple(values))

    def next_phase(self, track_time: float, time_scale: float) -> tuple[float, int]:
        """Countdown to next sunlight phase, phase index"""
        sun_phases = minfo.mapping.sunlightPhases
        if sun_phases is None:
            return 0.0, 0
        for next_time, next_index in sun_phases:  # noqa: B007, used after loop
            if next_time > track_time:
                break
        else:
            next_time, next_index = sun_phases[0]
        if track_time > next_time:
            next_time += 86400
        countdown = next_time - track_time
        if not self.wcfg["enable_time_scaled_countdown"] and time_scale > 0:
            countdown /= time_scale
        return countdown, next_index
