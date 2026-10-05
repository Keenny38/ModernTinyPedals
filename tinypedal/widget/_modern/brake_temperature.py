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
Brake temperature Widget, modern design

Brake temperature per wheel in heatmap color of brake (matched to vehicle), average while
braking under it.
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...userfile.heatmap import HEATMAP_DEFAULT_BRAKE, select_brake_heatmap_name, set_predefined_brake_name
from .base import DASH, ModernOverlay
from .quad import QuadMixin, Section, Tile, heat_color, heatmap, reload_heatmaps


class Realtime(QuadMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_degree_sign", "leading_zero", "enable_heatmap_auto_matching", "heatmap_name",
        "show_average", "average_sampling_duration", "off_brake_duration",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.sign = "°" if wcfg["show_degree_sign"] else ""
        self.leading_zero = min(max(int(wcfg["leading_zero"]), 1), 3)
        self.show_average = wcfg["show_average"]
        self.off_brake_duration = max(wcfg["off_brake_duration"], 0)
        interval = max(wcfg["update_interval"], 0.01)
        samples = int(min(max(wcfg["average_sampling_duration"], 1), 600) / (interval * 0.001))
        self.ema_temp = calc.ema_filter(samples)
        self.averages = [0.0] * 4
        reload_heatmaps()  # new widget: latest saved heatmaps
        steps = heatmap(wcfg["heatmap_name"], HEATMAP_DEFAULT_BRAKE)
        self.heat = [steps] * 4
        self.last_in_pits = -1
        self.last_vehicle = None
        self.last_elapsed = 0.0
        self.off_brake_timer = 0.0
        section = Section(widget_name, "", f"8888{self.sign}", sub=self.show_average)
        self.set_size(*self.build_quads([section], show_labels=False))

    def paint_static(self, painter: QPainter):
        self.paint_quads_static(painter)

    def paint(self, painter: QPainter):
        self.draw_quads(painter, (self.state,))

    def text(self, value: float) -> str:
        """Temperature text"""
        if value < -100:
            return DASH
        return f"{self.unit_temp(value):0{self.leading_zero}.0f}{self.sign}"

    def update_heatmap(self):
        """Front & rear brake heatmap matched to vehicle (while in pits)"""
        in_pits = api.read.vehicle.in_pits()
        if not (in_pits or self.last_in_pits != in_pits):
            return
        self.last_in_pits = in_pits
        if not self.wcfg["enable_heatmap_auto_matching"]:
            return
        vehicle = api.read.vehicle.vehicle_name()
        if self.last_vehicle == vehicle:
            return
        self.last_vehicle = vehicle
        class_name = api.read.vehicle.class_name()
        front = heatmap(select_brake_heatmap_name(set_predefined_brake_name(class_name, vehicle, True)), HEATMAP_DEFAULT_BRAKE)
        rear = heatmap(select_brake_heatmap_name(set_predefined_brake_name(class_name, vehicle, False)), HEATMAP_DEFAULT_BRAKE)
        self.heat = [front, front, rear, rear]

    def timerEvent(self, event):
        """Update when vehicle on track"""
        self.update_heatmap()
        temps = api.read.brake.temperature()
        if self.show_average:  # average while braking or just after
            elapsed = api.read.timing.elapsed()
            if self.last_elapsed != elapsed:
                self.last_elapsed = elapsed
                if self.off_brake_timer > elapsed or api.read.inputs.brake_raw() > 0.01:
                    self.off_brake_timer = elapsed
                if elapsed - self.off_brake_timer <= self.off_brake_duration:
                    for index in range(4):
                        self.averages[index] = self.ema_temp(self.averages[index], temps[index])
        tiles = []
        for index in range(4):
            temp = round(temps[index])
            average = self.averages[index]
            sub = f"Ø {self.text(average) if average > 0 else DASH}" if self.show_average else ""
            tiles.append(Tile((self.text(temp),), (heat_color(self.heat[index], temp) if temp > -100 else None,), sub=sub))
        self.refresh(tuple(tiles))
