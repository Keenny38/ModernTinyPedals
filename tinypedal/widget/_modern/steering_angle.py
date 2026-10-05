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
Steering angle Widget, modern design

Steering wheel angle, front wheel angle, steering ratio, Ackermann percentage, slip angle
difference (oversteer blue, understeer orange), yaw rate, turning radius (and under slip).
"""

from __future__ import annotations

from PySide6.QtGui import QPainter

from ... import calculation as calc
from ... import units
from ...api_control import api
from ...module_info import minfo
from .base import ModernOverlay, display_order_options
from .stats import Stat, StatsMixin, Value

ITEMS = (
    ("steering_angle", "Steering", "+888°"),
    ("front_wheel_angle", "Wheel", "+88.8°"),
    ("steering_ratio", "Ratio", "88.8:1"),
    ("ackermann_percentage", "Ackermann", "+888%"),
    ("slip_angle_difference", "Slip diff", "+88.8°"),
    ("yaw_rate", "Yaw rate", "+888°/s"),
    ("turning_radius", "Radius", "+8888m"),
    ("turning_radius_under_slip_angle", "Slip radius", "+8888m"),
)


class Realtime(StatsMixin, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "layout", "wheel_track_front", "wheelbase", "manual_steering_range",
        "minimum_oversteer_slip_angle_difference", "minimum_understeer_slip_angle_difference",
        "show_inverted_yaw_rate_sign", *(f"show_{key}" for key, _, _ in ITEMS),
        *display_order_options("steering_angle"),
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        self.unit_dist = units.set_unit_distance(self.cfg.units["distance_unit"])
        self.symbol_dist = units.set_symbol_distance(self.cfg.units["distance_unit"])
        self.wheeltrack_front = max(wcfg["wheel_track_front"], 1)
        self.wheelbase = max(wcfg["wheelbase"], 1)
        self.ema_slip = 0.0
        stats = [Stat(key, label, sample) for key, label, sample in ITEMS if wcfg[f"show_{key}"]]
        stats = self.display_ordered(stats)
        self.keys = tuple(stat.key for stat in stats)
        width, height = self.build_stats(stats, vertical=wcfg["layout"] == 0)
        self.set_size(width, height)

    def paint_static(self, painter: QPainter):
        self.paint_stats_static(painter)

    def paint(self, painter: QPainter):
        self.draw_stats(painter, self.state)

    def radius_text(self, angle: float) -> str:
        """Turning radius of front wheel angle"""
        radius = calc.sym_max(self.unit_dist(calc.turning_radius(angle, self.wheelbase) * 0.001), 9999)
        return f"{radius:+.0f}{self.symbol_dist}"

    def timerEvent(self, event):
        """Update when vehicle on track"""
        wcfg = self.wcfg
        theme = self.theme
        wheels = minfo.wheels
        if wcfg["manual_steering_range"] > 0:
            steering_range = wcfg["manual_steering_range"]
        else:
            steering_range = api.read.inputs.steering_range_physical()
        steer = api.read.inputs.steering_raw() * steering_range * 0.5
        wheel = wheels.averageFrontToeAngle
        values = []
        for key in self.keys:
            if key == "steering_angle":
                values.append(Value(f"{steer:+.0f}°"))
            elif key == "front_wheel_angle":
                values.append(Value(f"{wheel:+.1f}°"))
            elif key == "steering_ratio":
                values.append(Value(f"{abs(calc.steering_ratio(steer, wheel)):.2f}"[:4] + ":1", theme.text_dim))
            elif key == "ackermann_percentage":
                percent = calc.ackermann_percentage(wheels.toeAngle[0], wheels.toeAngle[1], self.wheeltrack_front, self.wheelbase)
                values.append(Value(f"{0.0 if abs(percent) > 9.99 else percent:+.0%}", theme.warning))
            elif key == "slip_angle_difference":
                self.ema_slip += 0.2 * (wheels.slipAngleDifference - self.ema_slip)
                if self.ema_slip > wcfg["minimum_understeer_slip_angle_difference"]:
                    color = theme.warning
                elif self.ema_slip < wcfg["minimum_oversteer_slip_angle_difference"]:
                    color = theme.blue
                else:
                    color = None
                values.append(Value(f"{self.ema_slip:+.1f}°", color, theme.tint(color, 55) if color is not None else None))
            elif key == "yaw_rate":
                yaw = -wheels.yawRate if wcfg["show_inverted_yaw_rate_sign"] else wheels.yawRate
                values.append(Value(f"{calc.degrees(yaw):+.0f}°/s"))
            elif key == "turning_radius":
                values.append(Value(self.radius_text(wheel), theme.text_dim))
            elif key == "turning_radius_under_slip_angle":
                slip = wheels.averageFrontSlipAngle - wheels.averageRearSlipAngle
                values.append(Value(self.radius_text(wheel + slip), theme.text_dim))
        self.refresh(tuple(values))
