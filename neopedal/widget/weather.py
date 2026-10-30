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
Weather Widget
"""

from math import atan2, hypot
from typing import TYPE_CHECKING

from .. import calculation as calc
from .. import units
from ..api_control import api
from ..const_common import TEXT_TREND_SIGN
from ..module_info import minfo
from ._base import Overlay

if TYPE_CHECKING:
    from ..template.widget_config_types import WeatherConfig

WIND_CALM = 0.3  # m/s, no direction shown below
WIND_ARROWS = "↑→↓←"  # where wind blows relative to car: up (tailwind), right, down, left


class Realtime(Overlay):
    """Draw widget"""

    wcfg: "WeatherConfig"

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
        prefix_wetness_just = max(len(self.wcfg["prefix_wetness_dry"]), len(self.wcfg["prefix_wetness_wet"]))
        decimals = min(max(self.wcfg["decimal_places_temperature"], 0), 6)

        self.prefix_rain = self.wcfg["prefix_rain"]
        self.prefix_dry = self.wcfg["prefix_wetness_dry"].ljust(prefix_wetness_just)
        self.prefix_wet = self.wcfg["prefix_wetness_wet"].ljust(prefix_wetness_just)
        self.temp_cut = 2 + (self.cfg.units["temperature_unit"] == "Fahrenheit") + (decimals != 0) + decimals
        self.temp_decimals = decimals

        self.rubber_median_laps = max(int(self.wcfg["rubber_median_laps"]), 100)
        self.rubber_time_scale = (
            self.wcfg["rubber_time_scale_practice"],  # testday
            self.wcfg["rubber_time_scale_practice"],  # practice
            self.wcfg["rubber_time_scale_qualifying"],  # qualifying
            self.wcfg["rubber_time_scale_race"],  # warmup (shared with race)
            self.wcfg["rubber_time_scale_race"],  # race
        )
        self.rubber_starting = (
            self.wcfg["starting_rubber_practice"],  # testday
            self.wcfg["starting_rubber_practice"],  # practice
            self.wcfg["starting_rubber_qualifying"],  # qualifying
            self.wcfg["starting_rubber_race"],  # warmup (shared with race)
            self.wcfg["starting_rubber_race"],  # race
        )

        # Config units
        self.unit_temp = units.set_unit_temperature(self.cfg.units["temperature_unit"])
        self.symbol_temp = units.set_symbol_temperature(self.cfg.units["temperature_unit"])

        # Track temperature
        self.bar_style_trend = (
            self.wcfg["font_color_trend_constant"],
            self.wcfg["font_color_trend_increasing"],
            self.wcfg["font_color_trend_decreasing"],
        )

        if self.wcfg["show_temperature"]:
            layout_temp = self.set_grid_layout()
            temp_sample = temperature_text(0, self.temp_cut, decimals)
            text_temp = f"{temp_sample}({temp_sample}){self.symbol_temp}"
            self.bar_temp = self.set_rawtext(
                text=text_temp,
                width=font_m.width * len(text_temp) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_temperature"],
                bg_color=self.wcfg["background_color_temperature"],
                last=0,
            )
            layout_temp.addWidget(self.bar_temp, 0, 0)
            self.set_primary_orient(
                target=layout_temp,
                column=self.wcfg["display_order_temperature"],
                option=None,
                default=1,
            )

            if self.wcfg["show_trend"]:
                self.bar_temp_trend = self.set_rawtext(
                    text=TEXT_TREND_SIGN[0],
                    width=font_m.width + bar_padx,
                    fixed_height=font_m.height,
                    offset_y=font_m.voffset,
                    fg_color=self.bar_style_trend[0],
                    bg_color=self.wcfg["background_color_temperature"],
                    last=0,
                )
                layout_temp.addWidget(self.bar_temp_trend, 0, 1)

        # Rain precipitation
        if self.wcfg["show_rain"]:
            layout_rain = self.set_grid_layout()
            text_rain = f"{self.prefix_rain}  0%"
            self.bar_rain = self.set_rawtext(
                text=text_rain,
                width=font_m.width * len(text_rain) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_rain"],
                bg_color=self.wcfg["background_color_rain"],
                last=0,
            )
            layout_rain.addWidget(self.bar_rain, 0, 0)
            self.set_primary_orient(
                target=layout_rain,
                column=self.wcfg["display_order_rain"],
                option=None,
                default=1,
            )

            if self.wcfg["show_trend"]:
                self.bar_raininess_trend = self.set_rawtext(
                    text=TEXT_TREND_SIGN[0],
                    width=font_m.width + bar_padx,
                    fixed_height=font_m.height,
                    offset_y=font_m.voffset,
                    fg_color=self.bar_style_trend[0],
                    bg_color=self.wcfg["background_color_rain"],
                    last=0,
                )
                layout_rain.addWidget(self.bar_raininess_trend, 0, 1)

        # Surface wetness
        if self.wcfg["show_wetness"]:
            layout_wetness = self.set_grid_layout()
            text_wetness = f"{self.prefix_dry}  0%"
            self.bar_wetness = self.set_rawtext(
                text=text_wetness,
                width=font_m.width * len(text_wetness) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_wetness"],
                bg_color=self.wcfg["background_color_wetness"],
                last=0,
            )
            layout_wetness.addWidget(self.bar_wetness, 0, 0)
            self.set_primary_orient(
                target=layout_wetness,
                column=self.wcfg["display_order_wetness"],
                option=None,
                default=1,
            )

            if self.wcfg["show_trend"]:
                self.bar_wetness_trend = self.set_rawtext(
                    text=TEXT_TREND_SIGN[0],
                    width=font_m.width + bar_padx,
                    fixed_height=font_m.height,
                    offset_y=font_m.voffset,
                    fg_color=self.bar_style_trend[0],
                    bg_color=self.wcfg["background_color_wetness"],
                    last=0,
                )
                layout_wetness.addWidget(self.bar_wetness_trend, 0, 1)

        # Wind speed & direction
        if self.wcfg["show_wind_speed"]:
            self.unit_speed = units.set_unit_speed(self.cfg.units["wind_speed_unit"])
            self.symbol_speed = units.set_symbol_speed(self.cfg.units["wind_speed_unit"])
            text_wind = f"{self.wcfg['prefix_wind']} {WIND_ARROWS[0]}888{self.symbol_speed}"
            self.bar_wind = self.set_rawtext(
                text=text_wind,
                width=font_m.width * len(text_wind) + bar_padx,
                fixed_height=font_m.height,
                offset_y=font_m.voffset,
                fg_color=self.wcfg["font_color_wind"],
                bg_color=self.wcfg["background_color_wind"],
            )
            self.set_primary_orient(
                target=self.bar_wind,
                column=self.wcfg["display_order_wind"],
                option=None,
                default=1,
            )

        # Last data
        self.temp_trend = TrendTimer(self.wcfg["temperature_trend_interval"])
        self.rain_trend = TrendTimer(self.wcfg["raininess_trend_interval"])
        self.wet_trend = TrendTimer(self.wcfg["wetness_trend_interval"])

    def timerEvent(self, event):
        """Update when vehicle on track"""
        lap_etime = api.read.timing.elapsed()

        # Track temperature
        if self.wcfg["show_temperature"]:
            temp_track = api.read.session.track_temperature()
            temp_air = api.read.session.ambient_temperature()
            temperature = temp_track + temp_air
            # Temperature
            # Both readings compared (sum unchanged when one goes up as much as the other goes down)
            self.update_temperature(self.bar_temp, (temp_track, temp_air), temp_track, temp_air)
            # Temperature trend
            if self.wcfg["show_trend"]:
                temp_trend = self.temp_trend.update(round(temperature, 1), lap_etime)
                self.update_temperature_trend(self.bar_temp_trend, temp_trend)

        # Rain precipitation
        if self.wcfg["show_rain"]:
            raininess = round(api.read.session.raininess(), 2)
            # Rain percentage
            self.update_raininess(self.bar_rain, raininess)
            # Rain trend
            if self.wcfg["show_trend"]:
                rain_trend = self.rain_trend.update(raininess, lap_etime)
                self.update_raininess_trend(self.bar_raininess_trend, rain_trend)

        # Surface wetness
        if self.wcfg["show_wetness"]:
            wet_min, wet_max, wet_avg = api.read.session.wetness()
            # Wetness percentage
            if wet_avg >= 0.01 or not self.wcfg["show_rubber_coverage_while_dry"]:
                self.update_wetness(self.bar_wetness, wet_avg)
            # Rubber coverage percentage
            else:
                session_type = api.read.session.session_type()
                rubber_scale = self.rubber_time_scale[session_type]
                laps_session = rubber_to_laps(self.rubber_starting[session_type], self.rubber_median_laps)
                if rubber_scale > 0:  # time-scaled coverage
                    laps_session += (minfo.vehicles.totalCompletedLaps * rubber_scale)
                self.update_rubber(self.bar_wetness, laps_session)
            # Wet trend
            if self.wcfg["show_trend"]:
                wetness = wet_min + wet_max + wet_avg
                wet_trend = self.wet_trend.update(wetness, lap_etime)
                self.update_wetness_trend(self.bar_wetness_trend, wet_trend)

        # Wind speed & direction
        if self.wcfg["show_wind_speed"]:
            speed, angle = wind_reading()
            speed = self.unit_speed(speed)
            angle = wind_arrow_angle(speed, angle)
            arrow = "-" if angle is None else WIND_ARROWS[round(angle / 90) % 4]
            self.update_wind(self.bar_wind, f"{speed:>3.0f}", arrow)

    # GUI update methods
    def update_temperature(self, target, data, track, air):
        """Track & ambient temperature"""
        if target.last != data:
            target.last = data
            track_temp = temperature_text(self.unit_temp(track), self.temp_cut, self.temp_decimals)
            air_temp = temperature_text(self.unit_temp(air), self.temp_cut, self.temp_decimals)
            target.text = f"{track_temp}({air_temp}){self.symbol_temp}"
            target.update()

    def update_temperature_trend(self, target, data):
        """Temperature trend"""
        if target.last != data:
            target.last = data
            target.text = TEXT_TREND_SIGN[data]
            target.fg = self.bar_style_trend[data]
            target.update()

    def update_raininess(self, target, data):
        """Rain percentage"""
        if target.last != data:
            target.last = data
            percent_rain = f"{data:>3.0%}"
            target.text = f"{self.prefix_rain} {percent_rain:.3}"
            target.update()

    def update_raininess_trend(self, target, data):
        """Raininess trend"""
        if target.last != data:
            target.last = data
            target.text = TEXT_TREND_SIGN[data]
            target.fg = self.bar_style_trend[data]
            target.update()

    def update_wetness(self, target, data):
        """Surface wetness percentage"""
        if target.last != data:
            target.last = data
            percent_wet = f"{data:>3.0%}"
            target.text = f"{self.prefix_wet} {percent_wet:.3}"
            target.update()

    def update_rubber(self, target, data):
        """Surface rubber coverage percentage"""
        if target.last != data:
            target.last = data
            percent_rubber = f"{laps_to_rubber(data, self.rubber_median_laps):>3.0%}"
            target.text = f"{self.prefix_dry} {percent_rubber:.3}"
            target.update()

    def update_wetness_trend(self, target, data):
        """Surface wetness trend"""
        if target.last != data:
            target.last = data
            target.text = TEXT_TREND_SIGN[data]
            target.fg = self.bar_style_trend[data]
            target.update()

    def update_wind(self, target, speed, arrow):
        """Wind speed, arrow of where wind blows relative to car"""
        if target.last != (speed, arrow):
            target.last = (speed, arrow)
            target.text = f"{self.wcfg['prefix_wind']} {arrow}{speed:.3}{self.symbol_speed}"
            target.update()


def wind_reading(calm: float = WIND_CALM) -> tuple[float, float | None]:
    """Wind speed (m/s) & angle of where wind blows relative to car (degrees clockwise from car front),
    None while calm (speed below calm, m/s)"""
    wind_x, _, wind_z = api.read.session.wind_velocity()
    speed = hypot(wind_x, wind_z)
    if speed < calm:
        return speed, None
    # Same view as radar: world plane rotated to car heading (x right, y behind)
    yaw = api.read.vehicle.orientation_yaw_radians()
    right, behind = calc.rotate_coordinate(yaw - 3.14159265, wind_x, -wind_z)
    return speed, calc.degrees(atan2(right, -behind))


def temperature_text(value: float, width: int, decimals: int) -> str:
    """Temperature zero padded to width, decimals dropped (rounded, never cut) while wider than width"""
    while True:
        text = f"{value:0{width}.{decimals}f}" if value >= 0 else f"{value:.{decimals}f}"  # no zero after minus
        if decimals <= 0 or len(text) <= width:
            return text
        decimals -= 1


def wind_arrow_angle(speed: float, angle: float | None) -> float | None:
    """Wind arrow angle, None (no arrow, as while calm) when whole speed reading shows 0 (speed in display unit):
    never "0 m/s" with an arrow"""
    return None if f"{speed:.0f}" in ("0", "-0") else angle


def laps_to_rubber(value: float, median_laps: int = 2000) -> float:
    """Convert laps to rubber coverage (percent)"""
    max_laps = median_laps * 2
    if value > max_laps:
        return 1.0
    if value > median_laps:
        return 0.75 + (value - median_laps) / median_laps / 4
    if value > 0:
        return value * 0.75 / median_laps
    return 0.0


def rubber_to_laps(value: float, median_laps: int = 2000) -> float:
    """Convert rubber coverage (percent) to laps"""
    max_laps = median_laps * 2
    if value >= 1:
        return max_laps
    if value > 0.75:
        return median_laps + (value - 0.75) * median_laps * 4
    if value > 0:
        return value * median_laps / 0.75
    return 0


class TrendTimer:
    """Trend timer"""

    __slots__ = (
        "_trend_interval",
        "_last_reading",
        "_trend",
        "_timer",
    )

    def __init__(self, trend_interval: float) -> None:
        """
        Args:
            trend_interval: trend reset interval (seconds).
        """
        self._trend_interval = trend_interval
        self._last_reading = 0.0
        self._trend = 0
        self._timer = 0.0

    def update(self, reading: float, elapsed_time: float) -> int:
        """Update trend

        Args:
            reading: value.
            elapsed_time: current lap elapsed time.

        Returns:
            Trend, 0 = constant, 1 = increasing, -1 = decreasing.
        """
        if self._last_reading < reading:
            self._timer = elapsed_time
            self._trend = 1  # increased
        elif self._last_reading > reading:
            self._timer = elapsed_time
            self._trend = -1  # decreased
        elif elapsed_time - self._timer > self._trend_interval:
            self._timer = elapsed_time
            self._trend = 0  # no change
        self._last_reading = reading

        if self._timer > elapsed_time:
            self._timer = elapsed_time
        return self._trend
