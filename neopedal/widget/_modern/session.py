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
Session Widget, modern design

Session type, system clock, remaining session time, estimated remaining laps.
"""

from __future__ import annotations

from itertools import islice
from time import strftime
from typing import TYPE_CHECKING

from PySide6.QtGui import QColor, QPainter

from ... import calculation as calc
from ...api_control import api
from ...demo_state import drawing_demo
from ...i18n import tr_overlay
from ...module_info import minfo
from .._common import player_race_laps, system_clock_samples
from .base import DASH, ModernOverlay, signed
from .stats import Stat, StatsMixin, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import SessionConfig

SESSION_NAMES = ("TEST", "PRACTICE", "QUALIFY", "WARMUP", "RACE")
# Custom session name options (classic), same order as SESSION_NAMES
SESSION_TEXT_OPTIONS = (
    "session_text_testday", "session_text_practice", "session_text_qualify", "session_text_warmup", "session_text_race",
)


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: SessionConfig

    options = (
        "font_size", "layout", "show_session_name", *SESSION_TEXT_OPTIONS, "show_system_clock",
        "system_clock_format", "show_session_time", "show_estimated_laps", "show_predicted_extra_laps",
        "display_order_session_name", "display_order_system_clock", "display_order_session_time",
        "display_order_estimated_laps", "show_field_level", "display_order_field_level",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        theme = self.theme
        # Session names changed by user, else design names (translated)
        self.session_names = tuple(
            self.user_text(key, tr_overlay(name)) for key, name in zip(SESSION_TEXT_OPTIONS, SESSION_NAMES)
        )
        stats = []
        if wcfg["show_session_name"]:
            sample = self.widest("strong", self.session_names)
            stats.append(Stat("session_name", "Session", sample, "strong"))
        if wcfg["show_system_clock"]:
            sample = self.widest("value", system_clock_samples(wcfg["system_clock_format"]))
            stats.append(Stat("system_clock", "Clock", sample))
        if wcfg["show_session_time"]:
            stats.append(Stat("session_time", "Remaining", "~88:88:88", "strong", theme.accent))
        if wcfg["show_estimated_laps"]:
            sample = "888.888 (+8)" if wcfg["show_predicted_extra_laps"] else "888.888"
            stats.append(Stat("estimated_laps", "Laps left", sample))
        if wcfg["show_field_level"]:
            stats.append(Stat("field_level", "Field DR/SR", "P3 · P3"))
        stats = self.display_ordered(stats)
        self.keys = tuple(stat.key for stat in stats)
        self.rank_colors: dict[str, QColor] = {}
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        theme = self.theme
        remaining = api.read.session.remaining()
        offset = minfo.vehicles.finishTimeOffset
        est_remaining = remaining - offset
        values = []
        for key in self.keys:
            if key == "session_name":
                index = api.read.session.session_type()
                name = self.session_names[index] if 0 <= index < len(self.session_names) else ""
                values.append(Value(name, theme.positive if index == 4 else theme.text))
            elif key == "system_clock":
                values.append(Value(strftime(self.wcfg["system_clock_format"]), theme.text_dim))
            elif key == "session_time":
                if offset:
                    text = f"~{calc.sec2countdown(max(est_remaining, 0))}"
                else:
                    text = calc.sec2sessiontime(max(remaining, 0))
                values.append(Value(text))
            elif key == "estimated_laps":
                values.append(Value(self.laps_left(est_remaining)))
            elif key == "field_level":
                values.append(self.field_level_value())
        self.refresh(tuple(values))

    def field_level_value(self) -> Value:
        """Average driver & safety rank of drivers of online race found in RaceControl entries, dashes if none"""
        from ...process import driver_ranks as dr

        theme = self.theme
        driver: dr.Rank | None
        safety: dr.Rank | None
        if drawing_demo():
            driver, safety = dr.Rank("Silver", 3, 0), dr.Rank("Gold", 1, 0)
        else:
            from ...rank_info import field_level, poll_field

            # Cars of session only: slots beyond keep drivers of a former (bigger) session
            names = [veh.driverName for veh in islice(minfo.vehicles.dataSet, minfo.vehicles.totalVehicles)]
            poll_field(names)
            level = field_level(names)
            driver, safety = level.driver, level.safety
        if driver is None and safety is None:
            return Value(f"{DASH} · {DASH}", theme.text_dim)
        text = f"{driver.short if driver else DASH} · {safety.short if safety else DASH}"
        if driver is None:
            return Value(text, theme.text)
        colors = self.rank_colors
        if not colors:  # rank colors made once
            colors.update((name, QColor(color)) for name, color in
                          (dr.RANK_COLORS_LIGHT if theme.light else dr.RANK_COLORS).items())
        return Value(text, colors.get(driver.name.casefold(), theme.text))

    def laps_left(self, est_remaining: float) -> str:
        """Estimated remaining laps"""
        laps_done, lap_total = player_race_laps(est_remaining)
        laps = max(lap_total - laps_done, 0)
        text = f"{laps:.3f}"[:7]
        if self.wcfg["show_predicted_extra_laps"]:
            return f"{text} ({signed(minfo.vehicles.finishLapOffset)})"
        return text
