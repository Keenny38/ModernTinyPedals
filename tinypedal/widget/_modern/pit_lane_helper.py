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
Pit lane helper Widget, modern design

Stat tiles shown near & in pit lane: speed in gain or loss color against pit speed limit,
limiter state on colored tile (red when in pit lane without limiter), distance to pit box
with filling bar, planned services. Nothing drawn while hidden.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ...i18n import tr_overlay as tr
from .._race_aids import HiddenPreview
from ..pit_lane_helper import DANGER, DASH, OK, WARNING, PitLaneMixin, PitReading
from .base import ModernOverlay
from .stats import Stat, StatsMixin, Value


class Realtime(HiddenPreview, PitLaneMixin, StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_always", "approach_distance", "show_speed", "show_limiter_state",
        "show_pit_box_distance", "show_planned_services",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.setup_pit()
        samples = {
            "speed": "888",
            "limit": "888",
            "limiter": self.widest("value", (tr("On"), tr("Off"), DASH)),
            "box": f"88888{self.symbol_dist}",
            "stop": "888s",
            "refuel": f"+888{self.widest('value', (self.symbol_fuel, '%'))}",
            "repair": "888s",
        }
        stats = [
            Stat(key, label, samples[key], "strong" if key in ("speed", "limiter") else "value")
            for (key, _), label in zip(self.items, self.labels())
        ]
        self.keys = tuple(stat.key for stat in stats)
        columns = 4 if len(stats) > 4 else 0
        self.set_size(*self.build_stats(stats, columns=columns))
        self.state = (False, self.values(PitReading()))

    def timerEvent(self, event):
        """Update when vehicle on track"""
        reading = self.read_pit()
        self.refresh((reading.visible, self.values(reading)))

    def paintEvent(self, event):
        """Draw while shown (or overlay unlocked)"""
        if self.state[0] or self.previewing():
            super().paintEvent(event)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state[1])

    def values(self, state: PitReading) -> tuple[Value, ...]:
        """Stat values of readings"""
        theme = self.theme
        values = []
        for key in self.keys:
            if key == "speed":
                if state.speed_state == DANGER:
                    values.append(Value(state.speed, theme.negative, theme.tint(theme.negative, 70)))
                elif state.speed_state == OK:
                    values.append(Value(state.speed, theme.positive))
                else:
                    values.append(Value(state.speed))
            elif key == "limiter":
                if state.limiter_state == OK:
                    values.append(Value(state.limiter, theme.positive, theme.tint(theme.positive, 60)))
                elif state.limiter_state == WARNING:
                    values.append(Value(state.limiter, theme.warning, theme.tint(theme.warning, 60)))
                elif state.limiter_state == DANGER:
                    values.append(Value(state.limiter, theme.text, theme.tint(theme.negative, 150)))
                else:
                    values.append(Value(state.limiter, theme.text_faint))
            elif key == "box":
                values.append(Value(state.box, theme.text, bar=state.box_fraction, bar_color=theme.accent))
            else:
                text = getattr(state, key)
                values.append(Value(text, theme.text if text != DASH else theme.text_faint))
        return tuple(values)
