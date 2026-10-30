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
Pedal bar alerts: throttle bar flashes while TC active or wheels spinning, brake bar while ABS
active or wheels locking; brake pressure as share of peak (pedal & trailing widgets, classic & modern design)
"""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from ..api_control import api
from ..module_info import minfo
from ._common import FAST_FLASH_MINIMUM, flash_lit

if TYPE_CHECKING:
    from ..template.widget_config_types import PedalConfig, TrailingConfig

# Bar: its alerts, first active one flashes; alert name is prefix of its options
# (show_<alert>_flash, <alert>_color)
BAR_ALERTS = {
    "throttle": ("tc_activation", "wheel_slip"),
    "brake": ("abs_activation", "wheel_lock"),
}
ALERT_THEME_COLORS = {  # modern design: theme color of alert
    "tc_activation": "warning",
    "abs_activation": "blue",
    "wheel_lock": "caution",
    "wheel_slip": "best",
}
PEDAL_PRESSED = 0.02  # raw pedal input above which wheel lock & slip count


def wheel_lock() -> float:
    """Wheel lock of most locked wheel (0 to 1): its negative slip ratio, 0 while every wheel turns at least at
    ground speed (positive slip on all wheels is spin, not lock)"""
    return min(max(-min(minfo.wheels.slipRatio), 0.0), 1.0)


class PedalAlertMixin:
    """Alert of each pedal bar, flashing at alert_flash_interval"""

    wcfg: PedalConfig | TrailingConfig
    max_brake_pressure = 0.01  # peak brake pressure seen on followed car

    def vehicle_reset(self):
        """Peak brake pressure found again for next car or session (kept across pit stops)"""
        self.max_brake_pressure = 0.01

    def brake_pressure_share(self) -> float:
        """Brake pressure (sum of 4 wheels) as share of peak seen on followed car"""
        pressure = sum(api.read.brake.pressure())
        if pressure > self.max_brake_pressure:
            self.max_brake_pressure = pressure
        return pressure / self.max_brake_pressure

    def setup_alerts(self, keys: tuple[str, ...]):
        """Alerts of bars (keys: bar names in drawn order)"""
        wcfg = self.wcfg
        self.alert_interval = max(float(wcfg["alert_flash_interval"]), FAST_FLASH_MINIMUM)
        self.bar_alerts = tuple(
            tuple(alert for alert in BAR_ALERTS.get(key, ()) if wcfg[f"show_{alert}_flash"]) for key in keys)
        self.alerts_shown = any(self.bar_alerts)

    def read_alerts(self) -> tuple[str, ...]:
        """Alert lit now on each bar ("" none, or off phase of flash)"""
        if not self.alerts_shown or not flash_lit(monotonic(), self.alert_interval, minimum=FAST_FLASH_MINIMUM):
            return ("",) * len(self.bar_alerts)
        active: dict[str, bool] = {}
        return tuple(
            next((alert for alert in alerts if self.alert_active(alert, active)), "")
            for alerts in self.bar_alerts)

    def alert_active(self, alert: str, active: dict[str, bool]) -> bool:
        """Whether alert active now (read once per update, kept in active)"""
        state = active.get(alert)
        if state is None:
            if alert == "tc_activation":
                state = api.read.switch.tc_active()
            elif alert == "abs_activation":
                state = api.read.switch.abs_active()
            elif alert == "wheel_lock":
                state = (api.read.inputs.brake_raw() > PEDAL_PRESSED
                         and wheel_lock() >= self.wcfg["wheel_lock_threshold"])
            else:
                state = (api.read.inputs.throttle_raw() > PEDAL_PRESSED
                         and min(max(minfo.wheels.slipRatio), 1) >= self.wcfg["wheel_slip_threshold"])
            active[alert] = bool(state)
        return state
