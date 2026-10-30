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
Engine temperature Widget, modern design

Oil & water temperature (overheat highlight), rate of change (heating orange, cooling blue)
and net change over last lap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from .base import LEFT, STEADY, ModernOverlay
from .stats import Stat, StatsMixin, Value

if TYPE_CHECKING:
    from ...template.widget_config_types import EngineTemperatureConfig

SUB_GAP = "  "  # between rate of change & net change


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    wcfg: EngineTemperatureConfig

    options = (
        "font_size", "layout", "overheat_threshold_oil", "overheat_threshold_water", "show_oil_temperature",
        "show_water_temperature", "show_rate_of_change", "show_net_change_per_lap", "rate_of_change_interval",
        "rate_of_change_smoothing_samples", "show_game_overheating_warning",
        "display_order_oil_temperature", "display_order_water_temperature",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.temp_scale = 1.8 if self.cfg.units["temperature_unit"] == "Fahrenheit" else 1.0
        self.rate_interval = min(max(wcfg["rate_of_change_interval"], 1), 60)
        self.ema_rate = calc.ema_filter(wcfg["rate_of_change_smoothing_samples"])
        self.show_sub = wcfg["show_rate_of_change"] or wcfg["show_net_change_per_lap"]
        stats = []
        if wcfg["show_oil_temperature"]:
            stats.append(Stat("oil", "Oil", "888.8°", sub_sample="▲88.8  Δ+88.8"))
        if wcfg["show_water_temperature"]:
            stats.append(Stat("water", "Water", "888.8°", sub_sample="▲88.8  Δ+88.8"))
        stats = self.display_ordered(stats, names={"oil": "oil_temperature", "water": "water_temperature"})
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0, show_sub=self.show_sub)
        self.set_size(width, height)
        self.rates = {"oil": 0.0, "water": 0.0}
        self.last_temps: dict[str, float | None] = {"oil": None, "water": None}
        self.lap_start_temps = {"oil": 0.0, "water": 0.0}
        self.net = {"oil": 0.0, "water": 0.0}
        self.last_elapsed = 0.0
        self.last_lap_start = -1.0

    def post_update(self):
        """Rate of change restarts from next reading (no rate against stale temperature)"""
        self.reset_rates()

    def reset_rates(self):
        """Clear rate of change & last temperature (new session or paused timer)"""
        self.rates = {"oil": 0.0, "water": 0.0}
        self.last_temps = {"oil": None, "water": None}

    def reset_net(self):
        """Clear net change per lap (new session: no change against last session temperature)"""
        self.lap_start_temps = {"oil": 0.0, "water": 0.0}
        self.net = {"oil": 0.0, "water": 0.0}

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        values = self.state
        self.draw_stats(painter, tuple(value._replace(sub="") for value in values))
        # Rate of change & net change per lap after it, each colored by its own sign
        gap = self.text_width("small", SUB_GAP)
        for slot, value in zip(self.slots, values):
            if not value.sub or slot.sub.width() <= 0:
                continue
            parts = value.sub.split(SUB_GAP)
            widths = [self.text_width("small", text) for text in parts]
            if self.stats_vertical:
                left = slot.sub.left()
            else:
                left = slot.sub.center().x() - (sum(widths) + gap * (len(parts) - 1)) / 2
            for text, width in zip(parts, widths):
                self.draw_text(painter, QRectF(left, slot.sub.top(), width, slot.sub.height()), text, "small",
                               self.change_color(text), LEFT, elide=False)
                left += width + gap

    def change_color(self, text: str):
        """Heating orange, cooling blue, steady dim (rate of change ▲ / ▼, net change Δ+ / Δ-)"""
        mark = text[1:2] if text.startswith("Δ") else text[:1]
        if mark in ("▲", "+"):
            return self.theme.orange
        if mark in ("▼", "-"):
            return self.theme.lap_behind
        return self.theme.text_dim

    def change_text(self, value: float) -> str:
        """Temperature difference"""
        change = abs(value) * self.temp_scale
        return f"{change:.0f}" if change > 9.94 else f"{change:.1f}"

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        theme = self.theme
        engine = api.read.engine
        lap_start = api.read.timing.start()
        elapsed = api.read.timing.elapsed()
        interval = 0.0
        if self.last_elapsed > elapsed:  # new session
            self.last_elapsed = elapsed
            self.reset_rates()
            self.reset_net()
        elif elapsed - self.last_elapsed >= 0.1:
            interval = self.rate_interval / (elapsed - self.last_elapsed)
            self.last_elapsed = elapsed
        new_lap = self.last_lap_start != lap_start
        self.last_lap_start = lap_start
        overheating = wcfg["show_game_overheating_warning"] and engine.overheating()  # game warning
        values = []
        for key in self.keys:
            temp = engine.oil_temperature() if key == "oil" else engine.water_temperature()
            if interval:
                last = self.last_temps[key]
                if last is not None:  # first reading: no rate yet (from 0 would be a fake spike)
                    self.rates[key] = self.ema_rate(self.rates[key], (temp - last) * interval)
                self.last_temps[key] = temp
            if new_lap:
                start = self.lap_start_temps[key]
                self.net[key] = temp - start if temp > 0 < start else 0.0
                self.lap_start_temps[key] = temp
            hot = temp >= wcfg[f"overheat_threshold_{key}"] or overheating
            rate = self.change_text(self.rates[key])
            steady = rate == STEADY
            parts = []
            if wcfg["show_rate_of_change"]:
                parts.append(rate if steady else f"{'▲' if self.rates[key] > 0 else '▼'}{rate}")
            if wcfg["show_net_change_per_lap"]:
                net = self.change_text(self.net[key])
                parts.append(f"Δ{net}" if net == STEADY else f"Δ{'+' if self.net[key] > 0 else '-'}{net}")
            if steady:
                rate_color = theme.text_dim
            else:
                rate_color = theme.orange if self.rates[key] > 0 else theme.lap_behind
            values.append(Value(
                f"{self.unit_temp(temp):.1f}°", theme.negative if hot else None, theme.tint(theme.negative, 55) if hot else None,
                SUB_GAP.join(parts), rate_color,  # colors of each part from its text when drawn
            ))
        self.refresh(tuple(values))
