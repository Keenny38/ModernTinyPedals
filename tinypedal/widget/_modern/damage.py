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
Damage Widget, modern design

Same drawing as black box damage panel: rounded body shell in 8 segments lighting up by damage
severity (detached parts pulse), wheels colored by suspension damage, outlined on puncture,
dashed when detached, integrity with gauge in the middle, fading cone toward last impact.
"""

from __future__ import annotations

import math
from time import monotonic

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from ...api_control import api
from .._black_box.damage import DamagePainter, damage_geometry
from .._painter import fit_font
from .._style import StyledConfig
from .base import ModernOverlay
from .draw import panel

# Black box damage panel palette (modern design)
DAMAGE_COLORS = {
    "damage_panel_body_color": "#5A6472",
    "damage_panel_body_color_light": "#FFC400",
    "damage_panel_body_color_heavy": "#FF5A1F",
    "damage_panel_body_color_detached": "#E0182D",
    "damage_panel_suspension_color": "#2FB36A",
    "damage_panel_suspension_color_light": "#FFC400",
    "damage_panel_suspension_color_medium": "#FF9F1C",
    "damage_panel_suspension_color_heavy": "#FF3D3D",
    "damage_panel_suspension_color_totaled": "#B0106A",
    "damage_panel_wheel_color_detached": "#E0182D",
    "damage_panel_puncture_color": "#FF3D3D",
    "damage_panel_impact_cone_color": "#CCFF3D3D",
    "indicator_inactive_color": "#2A303C",
}


class Realtime(DamagePainter, ModernOverlay):
    """Draw widget"""

    options = (
        "font_size", "show_background", "show_detached_warning_flash",
        "suspension_damage_light_threshold", "suspension_damage_medium_threshold",
        "suspension_damage_heavy_threshold", "suspension_damage_totaled_threshold",
        "show_last_impact_cone", "last_impact_cone_angle", "last_impact_cone_duration",
        "show_integrity_reading", "show_aero_integrity_if_available",
    )

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        wcfg = self.wcfg
        # Damage panel options read by black box damage painter, from this widget options
        panel_options = {
            **DAMAGE_COLORS,
            **{f"damage_panel_suspension_{level}_threshold": wcfg[f"suspension_damage_{level}_threshold"]
               for level in ("light", "medium", "heavy", "totaled")},
            "show_damage_panel_impact_cone": wcfg["show_last_impact_cone"],
            "damage_panel_impact_cone_angle": wcfg["last_impact_cone_angle"],
            "show_damage_panel_integrity": wcfg["show_integrity_reading"],
            "show_damage_panel_aero_integrity": wcfg["show_aero_integrity_if_available"],
        }
        self.wcfg = StyledConfig(self.wcfg, panel_options)
        unit = self.unit
        self.setFont(self.fonts["strong"])
        self.font_label = self.fonts["label"]
        self.pen_info_label = QPen(self.theme.text_muted)
        self.text = {"integrity_aero": "AERO", "integrity_body": "BODY"}
        pad = unit * 0.3
        body_w = unit * 4.6
        body_h = unit * 6.4
        self.rect_panel = QRectF(pad, pad, body_w, body_h)
        self.damage_shapes = damage_geometry(self.rect_panel, unit)
        self.set_size(body_w + pad * 2, body_h + pad * 2)
        self.cone_duration = wcfg["last_impact_cone_duration"]
        self.flash = wcfg["show_detached_warning_flash"]
        # Damage state (black box painter attributes)
        self.body_damage: tuple[int, ...] = (0,) * 8
        self.damage_aero = -1.0
        self.damage_detached: tuple[bool, ...] = (False,) * 4
        self.damage_puncture: tuple[bool, ...] = (False,) * 4
        self.damage_suspension: tuple[float, ...] = (0.0,) * 4
        self.impact_position = (0.0, 0.0)
        self.impact_visible = False
        self.last_impact_time = None

    # Black box painter helpers
    def pulse(self) -> float:
        """Pulse strength of detached parts (0.35 to 1)"""
        if not self.flash:
            return 1.0
        return 0.675 + 0.325 * math.sin(monotonic() * math.tau * 1.2)

    def pulsed_color(self, color: str, strength: float) -> QColor:
        pulsed = QColor(color)
        pulsed.setAlphaF(pulsed.alphaF() * min(max(strength, 0.0), 1.0))
        return pulsed

    def draw_fit_text(self, painter: QPainter, rect: QRectF, text: str, font: QFont,
                      align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter):
        painter.setFont(fit_font(painter, font, text, rect.width() * 0.96, rect.height() * 1.1))
        painter.drawText(rect, align, text)

    def grown_font(self, font: QFont, rect: QRectF) -> QFont:
        grown = QFont(font)
        grown.setPixelSize(max(int(rect.height() * 0.85), 6))
        return grown

    def paint_static(self, painter: QPainter):
        if self.wcfg["show_background"]:
            panel(painter, QRectF(self.rect()), self.theme, self.radius(0.6), self.depth_effects)

    def paint(self, painter: QPainter):
        self.draw_damage_panel(painter, self.rect_panel)

    def timerEvent(self, event):
        """Update when vehicle on track"""
        vehicle = api.read.vehicle
        if self.wcfg["show_damage_panel_impact_cone"]:
            impact_time = vehicle.impact_time()
            if self.last_impact_time != impact_time:
                self.last_impact_time = impact_time
                self.impact_position = vehicle.impact_position()
            self.impact_visible = bool(impact_time) and api.read.timing.elapsed() - impact_time <= self.cone_duration
        self.body_damage = tuple(vehicle.damage_severity())
        self.damage_aero = vehicle.aero_damage()
        self.damage_detached = tuple(api.read.wheel.is_detached())
        self.damage_puncture = tuple(api.read.tyre.puncture())
        self.damage_suspension = tuple(round(value, 3) for value in api.read.wheel.suspension_damage())
        detached = any(severity >= 3 for severity in self.body_damage) or any(self.damage_detached)
        self.refresh((
            self.body_damage, self.damage_aero, self.damage_detached, self.damage_puncture, self.damage_suspension,
            self.impact_visible, self.impact_position, monotonic() if detached and self.flash else 0,
        ))
