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

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap

from .. import units
from ._base import Overlay, store_screen_layout
from ._black_box.base import PaintBase
from ._black_box.center import CenterPainter
from ._black_box.common import LAYOUT_COMPACT
from ._black_box.damage import DamagePainter, damage_geometry
from ._black_box.layout import LayoutInput, build_layout
from ._black_box.modules import ModuleStatus, enable_modules, required_modules
from ._black_box.panels import PanelPainter
from ._black_box.persist import keep_records, memory, restore_records
from ._black_box.reader import DataReader
from ._black_box.recorder import EventLog, IncidentBrowse, Recorder, open_folder
from ._black_box.sizing import COMPACT_START, Debounce, Fit, Presence, anchored_position, fit_content
from ._black_box.state import (
    BrakePeak,
    BumpStop,
    LapStats,
    PressureRange,
    SteerConvention,
    StintTracker,
    SuspensionTravel,
    Trend,
    WheelState,
    display_overrides,
    parse_class_targets,
    parse_compound_targets,
    pressure_target_kpa,
)
from ._black_box.status import StatusPainter
from ._black_box.suspension import TYRE_DIAMETER_MM, WHEEL_TRAVEL_MM, SuspensionPainter
from ._black_box.trace import TracePainter
from ._black_box.wheels import ColorFade, WheelPainter
from ._common import warning_flash
from ._painter import OverlayStyle
from ._style import StyledConfig


class Realtime(
    DataReader, WheelPainter, SuspensionPainter, CenterPainter, PanelPainter, DamagePainter, TracePainter, StatusPainter,
    PaintBase, Overlay,
):
    """Draw widget

    Data reading and each painted part live in their own mixin, see _black_box package.
    """

    update_while_hidden = True  # incident recorder & event log keep recording

    # Geometry copied from layout (see set_layout)
    rect_main: QRectF
    rect_leds: QRectF
    rect_battery: QRectF
    rect_damage: QRectF

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
        self.config_modules(wcfg)

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
        self.gear_speed_cluster = bool(wcfg["show_gear_speed_cluster"])
        self.center_order = self.ordered_center_items()
        self.has_center = self.layout_mode != LAYOUT_COMPACT and bool(self.center_order)
        shown = set(self.center_order) if self.has_center else set()
        self.show_recorder = bool(wcfg["show_incident_recorder"])
        self.show_event_log = bool(wcfg["show_event_log"])
        self.match_heatmap = bool(wcfg["enable_heatmap_auto_matching"])
        self.show_tyre_wear = bool(wcfg["show_tyre_wear"])
        self.need_switches = bool(wcfg["show_abs_indicator"] or wcfg["show_tc_indicator"]) or self.show_recorder
        side = set(self.side_rows())  # brake bias & motor map between right wheels
        self.need_brake_bias = "brake_bias" in side
        self.need_locking = "locking" in shown
        self.need_brake_migration = "brake_migration" in side or ("brake_bias" in side and self.merged_brake_bias())
        self.need_motor_map = bool(wcfg["show_motor_map"])
        self.need_delta = "delta" in shown
        self.need_laptime = "laptime" in shown
        # Justified: speed and RPM use the same label/value rows as brake bias and delta,
        # so every value in the column lines up on the right edge instead of each being centered.
        self.justify_center = wcfg["center_column_alignment"] == "Justified"
        self.need_limiter = "pit_limiter" in shown
        self.need_lights = bool(wcfg["show_headlights_indicator"])
        self.need_engine = bool(wcfg["show_engine_status"])
        self.need_gear = "gear" in shown or self.show_recorder
        self.need_pedals = "pedals" in shown or self.show_recorder
        self.need_rpm = "rpm" in shown or bool(wcfg["show_rpm_leds"]) or (
            "gear" in shown and bool(wcfg["enable_gear_rpm_color"]))
        self.need_slip = bool(wcfg["show_slip_warning"])
        self.show_stint = bool(wcfg["show_stint_comparison"])
        self.need_pressure = bool(wcfg["show_tyre_pressure"]) or self.show_stint
        self.compound_targets = {  # pressure in kPa, entered in kPa, psi or bar
            symbol: (pressure_target_kpa(p_min), pressure_target_kpa(p_max), t_min, t_max)
            for symbol, (p_min, p_max, t_min, t_max) in parse_compound_targets(wcfg["tyre_target_by_compound"]).items()
        }
        self.need_compound = self.match_heatmap or bool(wcfg["show_tyre_compound"]) or bool(self.compound_targets)
        self.need_fuel_rows = bool(wcfg["show_fuel_gauge"])
        self.need_energy_rows = bool(wcfg["show_energy_gauge"])
        self.show_damage_panel = bool(wcfg["show_damage_panel"])
        self.show_suspension = bool(wcfg["show_suspension"])
        self.wheel_suspension_motion = self.show_suspension and bool(wcfg["enable_wheel_suspension_motion"])
        self.show_susp_damage = self.show_suspension and bool(wcfg["show_coilover_damage"])
        # Setup readings: tyre & brake extras, suspension lap statistics
        self.show_pressure_range = bool(wcfg["show_tyre_pressure_range"])
        self.show_camber_spread = bool(wcfg["show_tyre_camber_spread"])
        self.show_surface_overheat = bool(wcfg["show_tyre_surface_overheat"])
        self.wear_forecast_laps = max(wcfg["tyre_wear_forecast_laps"], 0)
        self.show_brake_peak = bool(wcfg["show_brake_peak_temperature"]) and bool(wcfg["show_brake_temperature"])
        self.brake_wear_laps = wcfg["brake_wear_display"] == "Laps"
        self.brake_imbalance_threshold = max(wcfg["brake_imbalance_threshold"], 0)
        self.need_brake_heat = "brake_heat" in shown
        self.show_ride_min = bool(wcfg["show_ride_height_minimum"])
        self.show_lap_stats = bool(wcfg["show_suspension_lap_stats"]) and self.show_suspension
        self.show_heave = bool(wcfg["show_third_spring"])
        self.show_damper_histogram = bool(wcfg["show_damper_histogram"]) and self.show_suspension
        self.bottoming_threshold = max(wcfg["ride_height_bottoming_threshold"], 0)
        self.need_lap_stats = self.show_ride_min or self.show_lap_stats or self.show_damper_histogram
        self.need_pressure = self.need_pressure or self.show_pressure_range
        self.need_damage_total = self.show_recorder or self.show_event_log
        # Slow changing data (temperatures, pressure, wear, damage, fuel) is read every N updates
        slow_interval = max(wcfg["slow_data_update_interval"], 0)
        self.slow_every = max(round(slow_interval / max(wcfg["update_interval"], 1)), 1)
        self.tick = 0

    def config_geometry(self, wcfg):
        """Widget geometry, see _black_box.layout & _black_box.sizing"""
        self.show_battery_bar = bool(wcfg["show_battery_bar"])
        self.battery_bar_left = wcfg["battery_bar_position"] != "Right"
        self.max_steer = min(max(wcfg["maximum_wheel_angle"], 0), 45) if wcfg["show_wheel_angle"] else 0
        self.auto_resize = bool(wcfg["enable_auto_resize"])
        self.resize_anchor = wcfg["resize_anchor"]
        self.fixed_size = (wcfg["fixed_width"], wcfg["fixed_height"])
        # Auto resize: start compact, blocks appear with their data. Otherwise room for every block.
        self.presence = COMPACT_START if self.auto_resize else Presence()
        self.resize_debounce = Debounce(self.presence, wcfg["resize_delay"])
        self.fit = Fit(0, 0, 1.0, 0.0, 0.0)
        self.relayout(self.presence)

    def relayout(self, presence: Presence):
        """Build geometry for blocks present now, resize widget keeping anchor in place"""
        wcfg = self.wcfg
        self.presence = presence
        self.row_fuel = self.need_fuel_rows and presence.fuel_row
        self.row_energy = self.need_energy_rows and presence.energy_row
        self.row_battery = self.show_battery_bar and presence.battery
        self.row_stint = self.show_stint and presence.stint
        self.row_damper = self.show_damper_histogram
        layout = build_layout(LayoutInput(
            unit=self.unit,
            layout_mode=self.layout_mode,
            has_center=self.has_center,
            center_height=self.center_height(),
            max_steer=self.max_steer,
            show_caption=bool(wcfg["show_caption"]),
            show_leds=bool(wcfg["show_rpm_leds"]),
            show_battery_bar=self.row_battery,
            battery_bar_left=self.battery_bar_left,
            battery_bar_scale=min(max(wcfg["battery_bar_scale"], 0.3), 4),
            bottom_rows=int(self.row_fuel) + int(self.row_energy) + int(self.row_stint) + int(self.row_damper),
            trace_height_scale=min(max(wcfg["trace_height_scale"], 1), 8) if self.show_recorder else 0,
            event_lines=min(max(wcfg["number_of_event_log_lines"], 1), 10) if self.show_event_log else 0,
            damage_panel_scale=min(max(wcfg["damage_panel_scale"], 2), 10) if self.show_damage_panel else 0,
            tyre_scale=min(max(wcfg["tyre_scale"], 0.5), 3),
            center_scale=min(max(wcfg["center_column_scale"], 0.5), 3),
            row_scale=min(max(wcfg["gauge_row_scale"], 0.5), 3),
            event_scale=min(max(wcfg["event_log_line_scale"], 0.5), 3),
            corner_scale=OverlayStyle.corner_scale,
            damage_position=wcfg["damage_panel_position"],
            suspension_scale=min(max(wcfg["suspension_scale"], 0.5), 3) if self.show_suspension else 0,
            status_height=self.status_height(),
            wheel_travel=(WHEEL_TRAVEL_MM / TYRE_DIAMETER_MM * max(wcfg["suspension_motion_scale"], 0)
                          if self.wheel_suspension_motion else 0),
        ))
        self.car_layout = layout
        # Painting code reads geometry as widget attributes (width & height stay QWidget methods)
        for name, value in vars(layout).items():
            if name not in ("width", "height"):
                setattr(self, name, value)
        self.damage_shapes = damage_geometry(layout.rect_damage, self.unit)
        # Suspension drawn 1:1 with the tyre drawing: tyre height stands for real tyre diameter
        tyre_h = layout.rects_tyre[0].height() if layout.rects_tyre else 0
        self.susp_pixels_per_mm = tyre_h / TYRE_DIAMETER_MM * max(wcfg["suspension_motion_scale"], 0)
        self.static_layer = None
        self.fit = fit_content(layout.width, layout.height, *self.fixed_size)
        self.resize_anchored(self.fit.width, self.fit.height)

    def centering_rect(self) -> QRect:
        """Center actions center the black box card only, damage panel card left out"""
        fit = self.fit
        main = self.rect_main
        return QRectF(
            fit.offset_x + main.x() * fit.scale, fit.offset_y + main.y() * fit.scale,
            main.width() * fit.scale, main.height() * fit.scale,
        ).toRect()

    def resize_anchored(self, width: int, height: int):
        """Resize, moving widget so the anchor corner stays where it was"""
        old_w, old_h = self.width(), self.height()
        if (old_w, old_h) == (width, height):
            return
        if self.isVisible():
            self.move_anchored(old_w, old_h, width, height)
        else:
            # Widget rebuilt after an option change: new size starts from the size it had on
            # screen, so adding or removing blocks keeps the anchor corner in place as well
            last = memory(self.widget_name).geometry
            if last is not None and last[:2] == (self.x(), self.y()) and last[2:] != (width, height):
                self.move_anchored(last[2], last[3], width, height)
        self.resize(width, height)

    def move_anchored(self, old_w: int, old_h: int, width: int, height: int):
        """Move so the anchor corner stays in place, position saved for next start

        Auto resize moves the widget while driving: the file is only written once the car
        leaves the track (post_update) or the widget stops, never during a lap.
        """
        x, y = anchored_position(self.x(), self.y(), old_w, old_h, width, height, self.resize_anchor)
        if (x, y) == (self.x(), self.y()):
            return
        self.move(x, y)
        setting = self.cfg.user.setting[self.widget_name]
        if (setting["position_x"], setting["position_y"]) != (x, y):
            setting["position_x"], setting["position_y"] = x, y
            self.position_unsaved = True

    def save_position(self):
        """Write position moved by auto resize to file"""
        if self.__dict__ and self.position_unsaved:
            self.position_unsaved = False
            self.cfg.save()
            store_screen_layout(self.cfg)

    def post_update(self):
        self.save_position()

    def stop(self):
        """Save moved position, hand incidents & event log over to the rebuilt widget"""
        if self.__dict__:
            self.save_position()
            keep_records(self.widget_name, self.recorder, self.event_log)
        super().stop()

    def menu_actions(self):
        if not self.export_folder:
            return ()
        return (("Open Incident Folder", lambda: open_folder(self.export_folder)),)

    def moveEvent(self, event):
        """Remember geometry shown on screen, see resize_anchored"""
        super().moveEvent(event)
        self.remember_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.remember_geometry()

    def remember_geometry(self):
        if self.__dict__ and self.isVisible():  # not previews, not closed widgets
            memory(self.widget_name).geometry = (self.x(), self.y(), self.width(), self.height())

    def config_style(self, wcfg):
        """Pens, visual effects & caches"""
        self.pen_text = QPen(QColor(wcfg["font_color"]))
        self.pen_temp = QPen(QColor(wcfg["font_color_temperature"]))
        self.outline_width = max(wcfg["warning_outline_width"], 1)
        self.pen_lock = QPen(QColor(wcfg["wheel_lock_color"]), self.outline_width)
        self.pen_locked = QPen(QColor(wcfg["wheel_lock_color"]), self.outline_width * 2)
        self.pen_spin = QPen(QColor(wcfg["wheel_spin_color"]), self.outline_width)
        self.pen_detached = QPen(QColor(wcfg["wheel_detached_color"]), self.outline_width, Qt.PenStyle.DashLine)
        self.pen_caption = QPen(QColor(wcfg["font_color_caption"]))
        self.pen_info_label = QPen(QColor(wcfg["font_color_info_label"]))
        self.pen_indicator = QPen(QColor(wcfg["font_color_indicator"]))
        self.pen_indicator_active = QPen(QColor(wcfg["font_color_indicator_active"]))
        # Visual effects
        self.depth_effects = bool(wcfg["enable_depth_effects"])
        # Frequency / duration 0 turns the effect off
        self.alert_pulse = wcfg["alert_pulse_frequency"] > 0
        self.pulse_frequency = min(max(wcfg["alert_pulse_frequency"], 0.2), 5)
        fade_time = max(wcfg["smooth_transition_duration"], 0)
        self.smooth_transition = fade_time > 0
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
        self.tyre_temp_source = wcfg["tyre_temperature_source"]
        self.heatmap_tyre = 4 * [self.load_tyre_heatmap(wcfg["heatmap_name_tyre"])]
        self.heatmap_brake: list = 4 * [self.load_brake_heatmap(wcfg["heatmap_name_brake"])]

    def config_thresholds(self, wcfg):
        """Warning thresholds, targets, trends"""
        self.temp_warning = wcfg["tyre_temperature_warning_threshold"]  # Celsius, 0 disables
        # Per wheel (pressure min, pressure max, cold, hot), replaced by compound targets if set,
        # pressure in kPa, entered in kPa, psi or bar
        self.default_targets = (
            pressure_target_kpa(wcfg["tyre_pressure_target_minimum"]),
            pressure_target_kpa(wcfg["tyre_pressure_target_maximum"]),
            wcfg["tyre_temperature_cold_threshold"], self.temp_warning,
        )
        # Rear axle: own pressure window if set (0 = same as front)
        self.default_targets_rear = (
            pressure_target_kpa(wcfg["tyre_pressure_target_rear_minimum"]) or self.default_targets[0],
            pressure_target_kpa(wcfg["tyre_pressure_target_rear_maximum"]) or self.default_targets[1],
            *self.default_targets[2:],
        )
        self.wheel_targets = [self.default_targets] * 2 + [self.default_targets_rear] * 2
        # Brake disc window: by car class (carbon or iron discs work in very different ranges),
        # else the cold & hot thresholds
        self.default_brake_window = (
            wcfg["brake_temperature_cold_threshold"], wcfg["brake_temperature_hot_threshold"])
        self.brake_class_targets = parse_class_targets(wcfg["brake_target_by_class"])
        self.brake_cold: float
        self.brake_hot: float
        self.brake_cold, self.brake_hot = self.default_brake_window
        self.brake_class: str | None = None
        # Trends: needed for arrows, and for warming phase of cold tyres
        self.show_temp_trend = bool(wcfg["show_tyre_temperature_trend"])
        self.show_pres_trend = bool(wcfg["show_tyre_pressure_trend"])
        self.need_temp_trend = self.show_temp_trend or self.default_targets[2] > 0 or any(
            target[2] for target in self.compound_targets.values())
        window = wcfg["tyre_trend_duration"]
        self.temp_trends = [Trend(window, wcfg["tyre_heat_trend_threshold"]) for _ in range(4)]
        self.pres_trends = [Trend(window, wcfg["tyre_pressure_trend_threshold"]) for _ in range(4)]
        # Brake disc: heats within a braking zone and cools on the next straight, short window
        self.show_brake_trend = bool(wcfg["show_brake_temperature_trend"]) and bool(wcfg["show_brake_temperature"])
        self.brake_trends = [
            Trend(wcfg["brake_trend_duration"], wcfg["brake_heat_trend_threshold"]) for _ in range(4)]
        self.lock_threshold = -abs(wcfg["wheel_lock_threshold"])  # past peak grip
        self.locked_threshold = min(-abs(wcfg["wheel_locked_threshold"]), self.lock_threshold)  # wheel stopped
        self.spin_threshold = abs(wcfg["wheel_spin_threshold"])
        self.min_speed = max(wcfg["slip_warning_minimum_speed"], 0) / 3.6  # km/h to m/s
        # Damper speeds (mm/s): low / high speed knee, and speed of full tint
        self.susp_low_speed = max(wcfg["suspension_low_speed_threshold"], 1.0)
        self.susp_full_speed = max(wcfg["suspension_velocity_scale"], self.susp_low_speed + 1)
        self.susp_bump_margin = max(wcfg["suspension_bump_force_margin"], 0.05)
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
        damage_threshold = max(wcfg["damage_event_threshold"], 0)
        self.recorder = Recorder(
            duration=min(max(wcfg["recorder_duration"], 3), 120),
            deceleration_threshold=wcfg["incident_deceleration_threshold"],
            damage_threshold=damage_threshold,
        )
        self.event_log = EventLog(max(len(self.event_rows), 1), damage_threshold)
        restore_records(self.widget_name, self.recorder, self.event_log)
        self.export_format = wcfg["incident_export_format"]
        self.browse_seen: int = IncidentBrowse.requests  # hotkey requests already handled
        self.browse_incident = None  # incident picked with hotkey, shown instead of the last one
        self.browse_since = 0.0
        self.incident_display_time = max(wcfg["incident_display_duration"], 0)
        self.export_folder = (
            os.path.join(self.cfg.path.config, "blackbox") if wcfg["enable_incident_file_export"] else "")
        self.event_labels = {
            "puncture": self.text["puncture"], "flat": self.text["flat_spot"],
            "detached": self.text["detached"], "damage": self.text["damage"],
            "impact": self.text["impact"], "yellow": self.text["yellow_flag"], "blue": self.text["blue_flag"],
            "pit_in": self.text["pit_in"], "pit_out": self.text["pit_out"], "penalty": self.text["penalty"],
            "track_limits": self.text["track_limits"], "overheat": self.text["overheat"],
            "oil": self.text["oil"], "water": self.text["water"],
            "contact": self.text["contact"], "wall": self.text["wall"],
        }
        # Race events in the event log
        log = self.show_event_log
        self.log_flag_events = log and bool(wcfg["show_flag_events"])
        self.log_pit_events = log and bool(wcfg["show_pit_events"])
        self.log_penalty_events = log and bool(wcfg["show_penalty_events"])
        self.log_engine_events = log and bool(wcfg["show_engine_overheat_events"])
        self.log_race_events = (self.log_flag_events or self.log_pit_events
                                or self.log_penalty_events or self.log_engine_events)
        self.log_contact_events = log and bool(wcfg["show_contact_events"])
        self.contacts_seen: tuple = ()  # game contact list last checked
        self.contacts_logged: dict[str, float] = {}  # other driver: session time of last contact logged
        self.contacts_session_time = 0.0
        # Frozen incident: replay cursor, previous incident speed drawn behind for comparison
        self.incident_replay = bool(wcfg["enable_incident_replay"])
        self.show_previous_incident = bool(wcfg["show_previous_incident_trace"])

    def config_modules(self, wcfg):
        """Data modules needed by enabled options, checked about once per second"""
        settings = self.cfg.user.setting
        self.modules = ModuleStatus(settings, required_modules(wcfg))
        if wcfg["enable_required_modules"] and self.modules.missing:
            enable_modules(self.modules.missing, settings, self.cfg.save)
            self.modules.refresh()
        self.module_check_every = max(round(1000 / max(wcfg["update_interval"], 1)), 1)
        self.show_module_warning = bool(wcfg["show_module_warning"])
        self.apply_module_status()

    def reset_data(self):
        """Last data"""
        self.wheels = [WheelState() for _ in range(4)]
        self.body_damage: tuple = (0,) * 8
        self.damage_total = 0.0
        self.damage_aero = -1.0  # -1 if car reports no aero damage
        self.damage_detached: tuple = (False,) * 4
        self.damage_puncture: tuple = (False,) * 4
        self.damage_suspension: tuple = (0.0,) * 4
        self.impact_time: float | None = None
        self.recorder_impact_time: float | None = None  # last game impact time seen by incident recorder
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
        self.last_vehicle_name: str | None = None
        self.brake_bias = 0.0
        self.locking_front = 0.0  # percent of lap distance spent locking a front wheel
        self.locking_rear = 0.0
        self.brake_migration = 0.0  # percent
        self.motor_map_level = -1  # engine/motor map, -1 if car has none
        self.delta_best = 0.0  # seconds, negative is faster
        self.delta_shown = False  # reference lap exists & current lap comparable (see delta_available)
        self.laptime_current = 0.0  # seconds
        self.in_pits = False
        self.limiter = False
        self.headlights = False
        self.ignition = 0  # 0 off, 1 ignition on & engine stopped, 2 engine running
        self.oil_temp = 0.0  # Celsius
        self.water_temp = 0.0
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
        self.clutch = 0.0
        self.last_in_pits: int = -1
        self.last_vehicle: tuple[str, str] = ("", "")
        self.last_compounds: tuple = ("", "", "", "")
        self.battery_charge = 0.0  # percent
        self.battery_state = 0  # 0 n/a, 1 off, 2 drain, 3 regen
        self.battery_warning = 0  # 0 none, 1 low charge, 2 high charge
        self.battery_highlight = True  # warning color shown now (flash phase, or flash disabled)
        self.stint = StintTracker()
        self.susp_travels = [SuspensionTravel() for _ in range(4)]
        self.tyre_diameters: tuple[float, ...] = (TYRE_DIAMETER_MM,) * 4  # millimeters, from Wheels module once learned
        self.vehicle_name = ""
        self.steer_convention = SteerConvention()
        self.steer_vehicle: str | None = None
        self.susp_bumps = [BumpStop() for _ in range(4)]
        self.pressure_ranges = [PressureRange() for _ in range(4)]
        self.brake_peaks = [BrakePeak() for _ in range(4)]
        self.lap_stats = [LapStats() for _ in range(4)]
        self.stats_lap = None  # lap of lap statistics
        self.last_fast_time: float = 0.0
        self.last_session_elapsed: float = 0.0
        self.last_pits_state: bool | None = None
        self.brake_heat_balance = 0.0  # average front minus rear disc temperature (Celsius)
        self.impact_direction: str = ""  # arrow toward last impact reported by game
        self.susp_vehicle: str | None = None
        self.stint_wear = self.stint_wear_delta = 0.0
        self.stint_pressure = self.stint_pressure_delta = 0.0
        self.stint_has_previous = False
        self.trace_version = 0  # changes when recorder adds a sample, so the trace repaints
        self.pause_start: float | None = None  # recorder clock stopped at (game paused), see recorder_now
        self.paused_total = 0.0
        self.position_unsaved = False  # position moved by auto resize, not written to file yet

    # Paint
    def paintEvent(self, event):
        """Draw, without global depth shading (black box draws its own, set by enable_depth_effects)"""
        depth_effects = OverlayStyle.depth_effects
        OverlayStyle.depth_effects = False
        try:
            self.paint_content()
        finally:
            OverlayStyle.depth_effects = depth_effects

    def paint_content(self):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, self.background_layer())
        self.apply_fit(painter)
        if self.led_h:
            self.draw_leds(painter, self.rect_leds)
        for index, wheel in enumerate(self.wheels):
            # Tyre & disc hang on the suspension, like on the car: they move with the wheel
            # mount, by the real offset (screen vertical axis = suspension axis, as the spring)
            shift = self.wheel_shift(index, wheel)
            if shift:
                painter.save()
                painter.translate(0, shift)
            self.draw_tyre(painter, self.rects_tyre[index], wheel, index)
            self.draw_disc(painter, index, self.rects_disc[index], wheel)
            if shift:
                painter.restore()
            if self.show_suspension:
                self.draw_suspension(painter, self.rects_susp[index], wheel, index)
        if not self.rect_center.isNull():
            self.draw_center(painter, self.rect_center)
        self.draw_status_icons(painter)
        self.draw_side_rows(painter)
        if self.row_battery:
            self.draw_battery_bar(painter, self.rect_battery)
        self.draw_bottom_rows(painter)
        if self.show_damage_panel:
            self.draw_damage_panel(painter, self.rect_damage)
        if self.show_recorder:
            self.draw_trace(painter, self.rect_trace)
        if self.show_event_log:
            self.draw_event_log(painter)
        if self.show_module_warning and self.modules.missing:
            self.draw_module_warning(painter)
