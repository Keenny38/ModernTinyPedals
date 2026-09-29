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
Black box Widget

Car seen from above, all-in-one view:
tyres (temperature heatmap or inner/center/outer bands, pressure target, wear, end of stint wear,
lock & spin warning, puncture, detached wheel, flat spot, steering angle),
brakes (temperature heatmap), damage panel (same as Damage widget),
center column (ABS, TC, brake bias, pit & limiter, gear, speed, RPM, pedals, ordered by user),
RPM LEDs on top, fuel & virtual energy gauges at bottom (level, start & refill marks),
incident recorder (speed, throttle & brake trace frozen around impacts) and event log.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap

from .. import units
from ._base import Overlay
from ._black_box.base import PaintBase
from ._black_box.center import CenterPainter
from ._black_box.common import LAYOUT_COMPACT
from ._black_box.damage import DamagePainter, damage_geometry
from ._black_box.layout import LayoutInput, build_layout
from ._black_box.panels import PanelPainter
from ._black_box.reader import DataReader
from ._black_box.recorder import EventLog, Recorder
from ._black_box.state import (
    StintTracker,
    Trend,
    WheelState,
    display_overrides,
    parse_compound_targets,
)
from ._black_box.trace import TracePainter
from ._black_box.wheels import ColorFade, WheelPainter
from ._common import warning_flash
from ._style import StyledConfig


class Realtime(
    DataReader, WheelPainter, CenterPainter, PanelPainter, DamagePainter, TracePainter, PaintBase, Overlay
):
    """Draw widget

    Data reading and each painted part live in their own mixin, see _black_box package.
    """

    def __init__(self, config, widget_name):
        # Assign base setting
        super().__init__(config, widget_name)
        # Display profile & auto compact mode override show options, never saved to file
        overrides = display_overrides(self.wcfg)
        if overrides:
            self.wcfg = StyledConfig(self.wcfg, overrides)
        wcfg = self.wcfg

        self.config_fonts(wcfg)
        self.config_data_needs(wcfg)
        self.config_geometry(wcfg)
        self.config_style(wcfg)
        self.config_units(wcfg)
        self.config_thresholds(wcfg)
        self.config_recorder(wcfg)
        self.reset_data()

    # Config
    def config_fonts(self, wcfg):
        """Fonts, scaled with display"""
        scale = min(max(wcfg["display_scale"], 0.5), 4)
        size = wcfg["font_size"] * scale
        name, weight = wcfg["font_name"], wcfg["font_weight"]
        font = self.config_font(name, size, weight)
        self.setFont(font)
        self.unit = self.get_font_metrics(font).height
        self.gear_scale = min(max(wcfg["font_scale_gear"], 0.5), 5)
        self.speed_scale = min(max(wcfg["font_scale_speed"], 0.3), 4)
        self.rpm_scale = min(max(wcfg["font_scale_rpm"], 0.3), 4)
        self.battery_scale = min(max(wcfg["font_scale_battery"], 0.3), 4)
        self.font_gear = self.config_font(name, size * self.gear_scale, weight)
        self.font_speed = self.config_font(name, size * self.speed_scale, weight)
        self.font_rpm = self.config_font(name, size * self.rpm_scale, weight)
        self.font_small = self.config_font(name, size * 0.75, weight)
        self.font_battery = self.config_font(name, size * self.battery_scale, weight)
        # Labels: smaller, lighter and slightly spaced, so values stand out
        self.font_label = QFont(self.font_small)
        self.font_label.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        self.font_label.setWeight(QFont.Weight.Normal)

    def config_data_needs(self, wcfg):
        """Only read data that is actually displayed (compact layout skips the whole center column)"""
        self.layout_mode = min(max(int(wcfg["layout"]), 0), 2)
        self.center_order = self.ordered_center_items()
        self.has_center = self.layout_mode != LAYOUT_COMPACT and bool(self.center_order)
        shown = set(self.center_order) if self.has_center else set()
        self.show_recorder = bool(wcfg["show_incident_recorder"])
        self.show_event_log = bool(wcfg["show_event_log"])
        self.match_heatmap = bool(wcfg["enable_heatmap_auto_matching"])
        self.show_tyre_wear = bool(wcfg["show_tyre_wear"])
        self.need_switches = bool(shown & {"abs", "tc"}) or self.show_recorder
        self.need_brake_bias = "brake_bias" in shown
        self.need_locking = "locking" in shown
        self.need_brake_migration = "brake_migration" in shown
        self.need_delta = "delta" in shown
        self.need_laptime = "laptime" in shown
        # Justified: speed and RPM use the same label/value rows as brake bias and delta,
        # so every value in the column lines up on the right edge instead of each being centered.
        self.justify_center = wcfg["center_column_alignment"] == "Justified"
        self.need_limiter = "pit_limiter" in shown
        self.need_gear = "gear" in shown or self.show_recorder
        self.need_pedals = "pedals" in shown or self.show_recorder
        self.need_rpm = "rpm" in shown or bool(wcfg["show_rpm_leds"]) or (
            "gear" in shown and bool(wcfg["enable_gear_rpm_color"]))
        self.need_slip = bool(wcfg["show_slip_warning"])
        self.show_stint = bool(wcfg["show_stint_comparison"])
        self.need_pressure = bool(wcfg["show_tyre_pressure"]) or self.show_stint
        self.compound_targets = parse_compound_targets(wcfg["tyre_target_by_compound"])
        self.need_compound = self.match_heatmap or bool(wcfg["show_tyre_compound"]) or bool(self.compound_targets)
        self.need_fuel_rows = bool(wcfg["show_fuel_gauge"])
        self.need_energy_rows = bool(wcfg["show_energy_gauge"])
        self.show_damage_panel = bool(wcfg["show_damage_panel"])
        self.need_damage_total = self.show_recorder or self.show_event_log
        # Slow changing data (temperatures, pressure, wear, damage, fuel) is read every N updates
        slow_interval = max(wcfg["slow_data_update_interval"], 0)
        self.slow_every = max(round(slow_interval / max(wcfg["update_interval"], 1)), 1)
        self.tick = 0

    def config_geometry(self, wcfg):
        """Widget geometry, see _black_box.layout"""
        self.show_battery_bar = bool(wcfg["show_battery_bar"])
        self.battery_bar_left = wcfg["battery_bar_position"] != "Right"
        self.max_steer = min(max(wcfg["maximum_wheel_angle"], 0), 45) if wcfg["show_wheel_angle"] else 0
        bottom_rows = int(self.need_fuel_rows) + int(self.need_energy_rows) + int(self.show_stint)
        layout = build_layout(LayoutInput(
            unit=self.unit,
            layout_mode=self.layout_mode,
            has_center=self.has_center,
            center_height=self.center_height(),
            max_steer=self.max_steer,
            show_caption=bool(wcfg["show_caption"]),
            show_leds=bool(wcfg["show_rpm_leds"]),
            show_battery_bar=self.show_battery_bar,
            battery_bar_left=self.battery_bar_left,
            battery_bar_scale=min(max(wcfg["battery_bar_scale"], 0.3), 4),
            bottom_rows=bottom_rows,
            trace_height_scale=min(max(wcfg["trace_height_scale"], 1), 8) if self.show_recorder else 0,
            event_lines=min(max(wcfg["number_of_event_log_lines"], 1), 10) if self.show_event_log else 0,
            damage_panel_scale=min(max(wcfg["damage_panel_scale"], 2), 10) if self.show_damage_panel else 0,
        ))
        self.car_layout = layout
        # Painting code reads geometry as widget attributes (width & height stay QWidget methods)
        for name, value in vars(layout).items():
            if name not in ("width", "height"):
                setattr(self, name, value)
        self.damage_shapes = damage_geometry(layout.rect_damage, self.unit)
        self.resize(int(layout.width), int(layout.height))

    def config_style(self, wcfg):
        """Pens, visual effects & caches"""
        self.pen_text = QPen(QColor(wcfg["font_color"]))
        self.pen_temp = QPen(QColor(wcfg["font_color_temperature"]))
        self.outline_width = max(wcfg["warning_outline_width"], 1)
        self.pen_lock = QPen(QColor(wcfg["wheel_lock_color"]), self.outline_width)
        self.pen_spin = QPen(QColor(wcfg["wheel_spin_color"]), self.outline_width)
        self.pen_detached = QPen(QColor(wcfg["wheel_detached_color"]), self.outline_width, Qt.PenStyle.DashLine)
        self.pen_caption = QPen(QColor(wcfg["font_color_caption"]))
        self.pen_info_label = QPen(QColor(wcfg["font_color_info_label"]))
        self.pen_indicator = QPen(QColor(wcfg["font_color_indicator"]))
        self.pen_indicator_active = QPen(QColor(wcfg["font_color_indicator_active"]))
        # Visual effects
        self.depth_effects = bool(wcfg["enable_depth_effects"])
        self.alert_pulse = bool(wcfg["enable_alert_pulse"])
        self.pulse_frequency = min(max(wcfg["alert_pulse_frequency"], 0.2), 5)
        self.smooth_transition = bool(wcfg["enable_smooth_transition"])
        fade_time = max(wcfg["smooth_transition_duration"], 0) if self.smooth_transition else 0
        self.tyre_fades = [ColorFade(fade_time) for _ in range(4)]
        self.brake_fades = [ColorFade(fade_time) for _ in range(4)]
        # Tyre gloss: light on the left edge, shade on the right, turns with the tyre
        local = self.local_tyre
        gloss = QLinearGradient(local.left(), 0, local.right(), 0)
        gloss.setColorAt(0.0, QColor(255, 255, 255, 60))
        gloss.setColorAt(0.35, QColor(255, 255, 255, 0))
        gloss.setColorAt(0.7, QColor(0, 0, 0, 0))
        gloss.setColorAt(1.0, QColor(0, 0, 0, 80))
        self.brush_gloss = gloss
        self.shadow_offset = self.unit * 0.09
        # Caches: background layer (rebuilt on resize), fitted fonts, last drawn state
        self.static_layer: QPixmap | None = None
        self.font_cache: dict[tuple, QFont] = {}
        self.last_state: tuple = ()
        # Custom labels
        self.text = {key[5:]: value for key, value in wcfg.items() if key.startswith("text_")}

    def config_units(self, wcfg):
        """Units (widget override, or Units setting) & heatmap"""
        temp_unit = self.unit_name("temperature")
        pres_unit = self.unit_name("tyre_pressure")
        speed_unit = self.unit_name("speed")
        fuel_unit = self.unit_name("fuel")
        self.unit_temp = units.set_unit_temperature(temp_unit)
        self.unit_pres = units.set_unit_pressure(pres_unit)
        self.unit_speed = units.set_unit_speed(speed_unit)
        self.speed_label = {"KPH": "km/h", "MPH": "mph"}.get(speed_unit, "m/s")
        self.unit_fuel = units.set_unit_fuel(fuel_unit)
        self.fuel_label = "gal" if fuel_unit == "Gallon" else "L"
        self.pres_decimals = 0 if pres_unit == "kPa" else 1
        self.sign_text = "°" if wcfg["show_degree_sign"] else ""
        self.heatmap_tyre = 4 * [self.load_tyre_heatmap(wcfg["heatmap_name_tyre"])]
        self.heatmap_brake = 4 * [self.load_brake_heatmap(wcfg["heatmap_name_brake"])]

    def config_thresholds(self, wcfg):
        """Warning thresholds, targets, trends"""
        self.temp_warning = wcfg["tyre_temperature_warning_threshold"]  # Celsius, 0 disables
        # Per wheel (pressure min, pressure max, cold, hot), replaced by compound targets if set
        self.default_targets = (
            wcfg["tyre_pressure_target_minimum"], wcfg["tyre_pressure_target_maximum"],
            wcfg["tyre_temperature_cold_threshold"], self.temp_warning,
        )
        self.wheel_targets = [self.default_targets] * 4
        self.brake_cold = wcfg["brake_temperature_cold_threshold"]
        self.brake_hot = wcfg["brake_temperature_hot_threshold"]
        # Trends: needed for arrows, and for warming phase of cold tyres
        self.show_temp_trend = bool(wcfg["show_tyre_temperature_trend"])
        self.show_pres_trend = bool(wcfg["show_tyre_pressure_trend"])
        self.need_temp_trend = self.show_temp_trend or self.default_targets[2] > 0 or any(
            target[2] for target in self.compound_targets.values())
        window = wcfg["tyre_trend_duration"]
        self.temp_trends = [Trend(window, wcfg["tyre_heat_trend_threshold"]) for _ in range(4)]
        self.pres_trends = [Trend(window, wcfg["tyre_pressure_trend_threshold"]) for _ in range(4)]
        self.lock_threshold = -abs(wcfg["wheel_lock_threshold"])
        self.spin_threshold = abs(wcfg["wheel_spin_threshold"])
        self.min_speed = max(wcfg["slip_warning_minimum_speed"], 0) / 3.6  # km/h to m/s
        self.battery_low = wcfg["battery_low_threshold"]
        self.battery_high = wcfg["battery_high_threshold"]
        # Flashes a few times on crossing a threshold, then stays highlighted. Without the
        # flash the warning color is simply shown steadily, same as the Battery widget.
        if self.show_battery_bar and wcfg["show_battery_warning_flash"]:
            self.battery_flash = warning_flash(
                wcfg["battery_warning_flash_duration"],
                wcfg["battery_warning_flash_interval"],
                wcfg["number_of_battery_warning_flashes"],
            )
        else:
            self.battery_flash = None

    def config_recorder(self, wcfg):
        """Incident recorder & event log"""
        self.recorder = Recorder(
            duration=min(max(wcfg["recorder_duration"], 3), 120),
            deceleration_threshold=wcfg["incident_deceleration_threshold"],
        )
        self.event_log = EventLog(max(len(self.event_rows), 1))
        self.incident_display_time = max(wcfg["incident_display_duration"], 0)
        self.export_folder = (
            os.path.join(self.cfg.path.config, "blackbox") if wcfg["enable_incident_file_export"] else "")
        self.event_labels = {
            "puncture": self.text["puncture"], "flat": self.text["flat_spot"],
            "detached": self.text["detached"], "damage": self.text["damage"],
            "impact": self.text["impact"],
        }

    def reset_data(self):
        """Last data"""
        self.wheels = [WheelState() for _ in range(4)]
        self.body_damage: tuple = (0,) * 8
        self.damage_total = 0.0
        self.damage_aero = -1.0  # -1 if car reports no aero damage
        self.damage_detached: tuple = (False,) * 4
        self.damage_puncture: tuple = (False,) * 4
        self.damage_suspension: tuple = (0.0,) * 4
        self.impact_time = None
        self.impact_position: tuple = (0.0, 0.0)
        self.impact_visible = False  # last impact cone shown
        self.abs_active = False
        self.tc_active = False
        self.abs_level = -1
        self.tc_level = -1
        self.tc_cut_level = -1
        self.tc_slip_level = -1
        # Car has ABS/TC if game reports a level (LMU), or once seen active (rF2 does not report level)
        self.abs_seen = False
        self.tc_seen = False
        self.last_vehicle_name = None
        self.brake_bias = 0.0
        self.locking_front = 0.0  # percent of lap distance spent locking a front wheel
        self.locking_rear = 0.0
        self.brake_migration = 0.0  # percent
        self.delta_best = 0.0  # seconds, negative is faster
        self.laptime_current = 0.0  # seconds
        self.in_pits = False
        self.limiter = False
        self.gear = 0
        self.speed = 0.0
        self.rpm = 0.0
        self.rpm_max = 0.0
        self.refuel = 0.0
        self.refill = 0.0
        self.fuel_capacity = 0.0
        self.fuel_start = 0.0
        self.energy_capacity = 0.0
        self.energy_start = 0.0
        self.fuel = 0.0
        self.fuel_laps = 0.0
        self.energy = 0.0
        self.energy_laps = 0.0
        self.energy_available = False
        self.throttle = 0.0
        self.brake = 0.0
        self.last_in_pits = -1
        self.last_vehicle = ("", "")
        self.last_compounds: tuple = ("", "", "", "")
        self.battery_charge = 0.0  # percent
        self.battery_state = 0  # 0 n/a, 1 off, 2 drain, 3 regen
        self.battery_warning = 0  # 0 none, 1 low charge, 2 high charge
        self.battery_highlight = True  # warning color shown now (flash phase, or flash disabled)
        self.stint = StintTracker()
        self.stint_wear = self.stint_wear_delta = 0.0
        self.stint_pressure = self.stint_pressure_delta = 0.0
        self.stint_has_previous = False
        self.trace_version = 0  # changes when recorder adds a sample, so the trace repaints

    # Paint
    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, self.background_layer())
        if self.led_h:
            self.draw_leds(painter, self.rect_leds)
        for index, wheel in enumerate(self.wheels):
            self.draw_tyre(painter, self.rects_tyre[index], wheel, index)
            self.draw_disc(painter, index, self.rects_disc[index], wheel)
        if not self.rect_center.isNull():
            self.draw_center(painter, self.rect_center)
        if self.show_battery_bar:
            self.draw_battery_bar(painter, self.rect_battery)
        self.draw_bottom_rows(painter)
        if self.show_damage_panel:
            self.draw_damage_panel(painter, self.rect_damage)
        if self.show_recorder:
            self.draw_trace(painter, self.rect_trace)
        if self.show_event_log:
            self.draw_event_log(painter)
