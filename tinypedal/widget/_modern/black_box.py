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
Black box Widget, modern design

Same car view, readings & layout as classic black box (all its options kept), drawn in modern
design: design font with caps labels, theme colors by role (options left at default value, so
light & colorblind themes recolor it too), cards with soft shading & hairline border, RPM LEDs
as capsules keeping a faint tint of their zone color while unlit. Colors customized by user
are kept.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen

from ..black_box import Realtime as Classic
from .base import DEFAULT_CORNER_SCALE
from .draw import rounded
from .restyle import Restyled, restyled_options
from .theme import build_theme

DEPTH_TOP = QColor(255, 255, 255, 14)
DEPTH_BOTTOM = QColor(0, 0, 0, 26)
LED_GLOW_ALPHA = 60
LED_ZONE_ALPHA = 46
LED_SHINE = QColor(255, 255, 255, 45)

# Default color option -> theme token (same meaning: warning, cold, gain...)
COLOR_TOKENS: dict[str, str | tuple[str, int]] = {
    "font_color": "text",
    "info_background_color": "surface_raised",
    "font_color_info_label": "text_muted",
    "font_color_caption": "text_muted",
    "background_color_caption": "surface_raised",
    "font_color_module_warning": "warning",
    "wheel_lock_color": "negative",
    "wheel_spin_color": "warning",
    "font_color_tyre_temperature_warning": "negative",
    "font_color_tyre_temperature_cold": "accent",
    "font_color_tyre_temperature_warming": "warning",
    "tyre_pressure_low_color": "accent",
    "tyre_pressure_high_color": "negative",
    "tyre_pressure_warning_background_color": "surface",
    "tyre_wear_warning_color": "surface",
    "font_color_tyre_wear_warning": "negative",
    "wheel_puncture_color": "negative",
    "wheel_flat_spot_color": "warning",
    "wheel_detached_color": "text_muted",
    "font_color_brake_temperature_cold": "accent",
    "font_color_brake_temperature_hot": "negative",
    "font_color_brake_wear_warning": "negative",
    "brake_pressure_color": "accent",
    "suspension_spring_color": "text_dim",
    "suspension_compression_color": "warning",
    "suspension_rebound_color": "blue",
    "suspension_bump_color": "negative",
    "suspension_airborne_color": "accent",
    "rpm_led_low_color": "positive",
    "rpm_led_mid_color": "caution",
    "rpm_led_high_color": "negative",
    "rpm_led_shift_color": "accent",
    "font_color_gear": "text",
    "gear_color_low": "text",
    "gear_color_mid": "warning",
    "gear_color_shift": "negative",
    "abs_active_color": "warning",
    "tc_active_color": "accent",
    "indicator_inactive_color": "surface_strong",
    "font_color_indicator": "text_dim",
    "brake_bias_color": "warning",
    "motor_map_color": "blue",
    "headlights_active_color": "accent",
    "engine_running_color": "positive",
    "engine_warning_color": "negative",
    "engine_off_color": "negative",
    "engine_ignition_color": "caution",
    "delta_gain_color": "positive",
    "delta_loss_color": "negative",
    "pit_active_color": "accent",
    "limiter_active_color": "caution",
    "rpm_bar_color": "accent",
    "rpm_redline_color": "negative",
    "throttle_color": "positive",
    "brake_color": "negative",
    "clutch_color": "blue",
    "fuel_gauge_color": "blue",
    "energy_gauge_color": "positive",
    "gauge_low_color": "negative",
    "gauge_start_mark_color": "warning",
    "gauge_refill_mark_color": "positive",
    "battery_idle_color": "text_muted",
    "battery_charge_color": "positive",
    "battery_discharge_color": "accent",
    "warning_color_low_battery": "negative",
    "warning_color_high_battery": "best",
    "damage_panel_body_color_light": "caution",
    "damage_panel_body_color_heavy": "orange",
    "damage_panel_body_color_detached": "negative",
    "damage_panel_suspension_color": "positive",
    "damage_panel_suspension_color_light": "caution",
    "damage_panel_suspension_color_medium": "warning",
    "damage_panel_suspension_color_heavy": "negative",
    "damage_panel_suspension_color_totaled": "best",
    "damage_panel_wheel_color_detached": "negative",
    "damage_panel_puncture_color": "negative",
    "damage_panel_impact_cone_color": "negative",
    "trace_speed_color": "text",
    "trace_steering_color": "blue",
    "trace_background_color": "surface_alt",
    "incident_color": "negative",
    "font_color_event_log": "text_dim",
}


class Realtime(Restyled, Classic):
    """Draw widget"""

    color_tokens = COLOR_TOKENS
    options = restyled_options("black_box", COLOR_TOKENS)

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        self.theme = build_theme(self.cfg.user.config["overlay_style"])

    def config_fonts(self, wcfg):
        """Classic fonts in design font, labels in caps like other modern overlays"""
        super().config_fonts(wcfg)
        label = self.font_label
        label.setCapitalization(QFont.Capitalization.AllUppercase)
        label.setWeight(QFont.Weight.Bold)
        label.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 106)

    def fill_background(self, painter: QPainter):
        """Cards: background color, soft vertical shading, hairline border"""
        path = self.path_bg
        painter.fillPath(path, QColor(self.wcfg["background_color"]))
        bounds = path.boundingRect()
        if self.depth_effects:
            shade = QLinearGradient(0, bounds.top(), 0, bounds.bottom())
            shade.setColorAt(0.0, DEPTH_TOP)
            shade.setColorAt(1.0, DEPTH_BOTTOM)
            painter.fillPath(path, QBrush(shade))
        pen = QPen(self.theme.border, 1)
        pen.setCosmetic(True)
        painter.save()
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()

    def draw_leds(self, painter: QPainter, rect: QRectF):
        """RPM LEDs: capsules lighting up from green to red, all flash over shift point, unlit
        ones keep a faint tint of their zone color"""
        wcfg = self.wcfg
        theme = self.theme
        count = min(max(int(wcfg["number_of_rpm_leds"]), 3), 20)
        ratio = self.rpm / self.rpm_max if self.rpm_max > 0 else 0
        start = min(max(wcfg["rpm_led_start_ratio"], 0), 0.95)
        redline = max(wcfg["rpm_redline_ratio"], start + 0.01)
        over = ratio >= redline
        flash_off = over and self.flash_off()
        gap = rect.height() * 0.3
        led_w = (rect.width() - gap * (count - 1)) / count
        inactive = QColor(wcfg["indicator_inactive_color"])
        radius = min(led_w, rect.height()) / 2 * min(self.theme_corner(), 1.0)
        grow = min(rect.height() * 0.18, 4.0)
        for led in range(count):
            led_rect = QRectF(rect.left() + led * (led_w + gap), rect.top(), led_w, rect.height())
            position = led / max(count - 1, 1)
            key = "rpm_led_low_color" if position < 0.5 else "rpm_led_mid_color" if position < 0.8 else "rpm_led_high_color"
            zone = QColor(wcfg[key])
            if over:
                lit = not flash_off
                color = QColor(wcfg["rpm_led_shift_color"])
            else:
                lit = ratio >= start + led / count * (redline - start)
                color = zone
            rounded(painter, led_rect, radius, inactive)
            if not lit:
                rounded(painter, led_rect, radius, theme.tint(zone, LED_ZONE_ALPHA))
                continue
            rounded(painter, led_rect.adjusted(-grow, -grow, grow, grow), radius + grow, theme.tint(color, LED_GLOW_ALPHA))
            rounded(painter, led_rect, radius, color)
            rounded(painter, QRectF(led_rect.left() + radius * 0.3, led_rect.top() + led_rect.height() * 0.12,
                                    led_rect.width() - radius * 0.6, led_rect.height() * 0.3), radius * 0.6, LED_SHINE)

    def theme_corner(self) -> float:
        """Global corner roundness, 1 = default"""
        style = self.cfg.user.config["overlay_style"]
        corner = min(max(float(style.get("corner_radius_scale", DEFAULT_CORNER_SCALE)), 0.0), 0.5)
        return corner / DEFAULT_CORNER_SCALE
