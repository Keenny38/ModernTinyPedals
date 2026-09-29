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
Black box widget, damage panel (same data as the Damage widget)

Body drawn as a rounded shell cut in 8 segments (front, sides, rear): intact segments stay
faint, damaged ones light up with a soft gradient, detached ones pulse. Wheels are rounded
chips colored by suspension damage, outlined on puncture, dashed when detached. The middle
shows integrity (colored by level) with its source and a gauge, and a fading cone points
toward the last impact for a few seconds. Sits at the bottom right.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from ... import calculation as calc
from .._painter import fill_chip, fill_chip_gradient, fill_rect

INTACT_ALPHA = 150  # intact body & wheels stay in the background
GOOD_INTEGRITY = 0.75
LOW_INTEGRITY = 0.4


class DamageGeometry(NamedTuple):
    """Damage panel shapes, computed once from panel rect"""

    parts: tuple[QRectF, ...]  # FL, F, FR, L, R, RL, Re, RR (grid cells, clipped to shell)
    shell: QPainterPath  # rounded body shell, hollow middle
    wheels: tuple[QRectF, ...]  # FL, FR, RL, RR
    caption: QRectF  # integrity source (BODY / AERO)
    integrity: QRectF  # integrity reading
    gauge: QRectF  # integrity gauge


def damage_geometry(rect: QRectF, unit: float) -> DamageGeometry:
    """Rounded body shell cut in 8 segments, wheels inside its corners, integrity in the middle"""
    margin = max(unit * 0.15, 1)
    gap = max(unit * 0.07, 1)
    inner = rect.adjusted(margin, margin, -margin, -margin)
    part_h = (inner.height() - gap * 2) / 3
    side_w = (inner.width() - gap * 2) * 0.3
    center_w = inner.width() - gap * 2 - side_w * 2
    columns = (
        (inner.left(), side_w),
        (inner.left() + side_w + gap, center_w),
        (inner.right() - side_w, side_w),
    )
    rows = (inner.top(), inner.top() + part_h + gap, inner.bottom() - part_h)
    grid = ((0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2))  # (column, row)
    parts = tuple(QRectF(columns[column][0], rows[row], columns[column][1], part_h) for column, row in grid)

    short = min(inner.width(), inner.height())
    thickness = max(short * 0.13, 2)
    shell = QPainterPath()
    shell.addRoundedRect(inner, short * 0.32, short * 0.32)
    hole = inner.adjusted(thickness, thickness, -thickness, -thickness)
    cut = QPainterPath()
    hole_radius = max(short * 0.32 - thickness, 1)
    cut.addRoundedRect(hole, hole_radius, hole_radius)
    shell = shell.subtracted(cut)

    wheel_w = max(hole.width() * 0.2, 2)
    wheel_h = max(hole.height() * 0.26, 2)
    pad = gap * 1.5
    wheels = (
        QRectF(hole.left() + pad, hole.top() + pad, wheel_w, wheel_h),
        QRectF(hole.right() - pad - wheel_w, hole.top() + pad, wheel_w, wheel_h),
        QRectF(hole.left() + pad, hole.bottom() - pad - wheel_h, wheel_w, wheel_h),
        QRectF(hole.right() - pad - wheel_w, hole.bottom() - pad - wheel_h, wheel_w, wheel_h),
    )
    middle_left = wheels[0].right() + gap
    middle_w = max(wheels[1].left() - gap - middle_left, 2)
    caption = QRectF(middle_left, hole.top() + hole.height() * 0.18, middle_w, hole.height() * 0.18)
    integrity = QRectF(middle_left, caption.bottom(), middle_w, hole.height() * 0.36)
    gauge_h = max(hole.height() * 0.07, 2)
    gauge = QRectF(middle_left, integrity.bottom() + gap, middle_w, gauge_h)
    return DamageGeometry(parts, shell, wheels, caption, integrity, gauge)


def faded(color: QColor, alpha: int) -> QColor:
    faint = QColor(color)
    faint.setAlpha(min(faint.alpha(), alpha))
    return faint


class DamagePainter:
    """Draw damage panel"""

    def draw_damage_panel(self, painter: QPainter, rect: QRectF):
        wcfg = self.wcfg
        shapes = self.damage_shapes
        strength = self.pulse()
        fill_rect(painter, rect, wcfg["info_background_color"])
        if self.impact_visible and wcfg["show_damage_panel_impact_cone"]:
            self.draw_impact_cone(painter, rect)
        self.draw_damage_shell(painter, shapes, strength)
        self.draw_damage_wheels(painter, shapes, strength)
        if wcfg["show_damage_panel_integrity"]:
            self.draw_integrity(painter, shapes)

    def draw_damage_shell(self, painter: QPainter, shapes: DamageGeometry, strength: float):
        """Body segments, damaged ones with a soft vertical gradient"""
        painter.save()
        painter.setClipPath(shapes.shell)
        for part, severity in zip(shapes.parts, self.body_damage):
            color = self.damage_body_color(severity, strength)
            if severity and self.depth_effects:
                shade = QLinearGradient(0, part.top(), 0, part.bottom())
                shade.setColorAt(0.0, color.lighter(125))
                shade.setColorAt(1.0, color.darker(115))
                painter.fillRect(part, shade)
            else:
                painter.fillRect(part, color)
        painter.restore()

    def draw_damage_wheels(self, painter: QPainter, shapes: DamageGeometry, strength: float):
        wcfg = self.wcfg
        outline = max(self.unit * 0.08, 1)
        for wheel_rect, detached, puncture, suspension in zip(
            shapes.wheels, self.damage_detached, self.damage_puncture, self.damage_suspension
        ):
            radius = min(wheel_rect.width(), wheel_rect.height()) * 0.35
            if detached:  # empty dashed place where the wheel was
                pen = QPen(self.pulsed_color(wcfg["damage_panel_wheel_color_detached"], strength), outline,
                           Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(wheel_rect, radius, radius)
                continue
            color = self.damage_wheel_color(False, suspension)
            if self.depth_effects and suspension >= wcfg["damage_panel_suspension_light_threshold"]:
                fill_chip_gradient(painter, wheel_rect, color)
            else:
                fill_chip(painter, wheel_rect, color)
            if puncture:
                pen = QPen(self.pulsed_color(wcfg["damage_panel_puncture_color"], strength), outline)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(wheel_rect, radius, radius)

    def draw_integrity(self, painter: QPainter, shapes: DamageGeometry):
        """Integrity value colored by level, its source, and a gauge"""
        wcfg = self.wcfg
        value = self.integrity()
        color = QColor(self.integrity_color(value))
        align = Qt.AlignmentFlag.AlignCenter
        painter.setPen(self.pen_info_label)
        source = "integrity_aero" if self.uses_aero_integrity() else "integrity_body"
        self.draw_fit_text(painter, shapes.caption, self.text[source], self.font_label, align)
        painter.setPen(color)
        self.draw_fit_text(painter, shapes.integrity, f"{value:.0%}", self.font(), align)
        gauge = shapes.gauge
        fill_chip(painter, gauge, wcfg["indicator_inactive_color"])
        if value > 0.005:
            fill_chip_gradient(painter, QRectF(gauge.left(), gauge.top(), gauge.width() * value, gauge.height()),
                               color)

    def draw_impact_cone(self, painter: QPainter, rect: QRectF):
        """Cone toward last impact, fading out from the middle"""
        wcfg = self.wcfg
        angle = min(max(wcfg["damage_panel_impact_cone_angle"], 2), 90)
        size = max(rect.width(), rect.height())
        center = rect.center()
        raw_angle = calc.degrees(calc.oriyaw(*self.impact_position))
        color = QColor(wcfg["damage_panel_impact_cone_color"])
        glow = QRadialGradient(center, size * 0.75)
        glow.setColorAt(0.0, color)
        glow.setColorAt(1.0, faded(color, 0))
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawPie(
            QRectF(center.x() - size, center.y() - size, size * 2, size * 2),
            int(16 * (raw_angle - 90 - angle * 0.5)), int(16 * angle),
        )
        painter.restore()

    def uses_aero_integrity(self) -> bool:
        return bool(self.wcfg["show_damage_panel_aero_integrity"]) and self.damage_aero >= 0

    def integrity(self) -> float:
        """Remaining body integrity (or aero integrity if available), 0 to 1"""
        damage = self.damage_aero if self.uses_aero_integrity() else sum(self.body_damage) / 16
        return min(max(1 - damage, 0.0), 1.0)

    def integrity_color(self, value: float) -> str:
        """Same palette as damage: intact suspension color, then light, then heavy"""
        wcfg = self.wcfg
        if value >= GOOD_INTEGRITY:
            return wcfg["damage_panel_suspension_color"]
        if value >= LOW_INTEGRITY:
            return wcfg["damage_panel_body_color_light"]
        return wcfg["damage_panel_body_color_heavy"]

    def damage_body_color(self, severity: int, strength: float = 1.0) -> QColor:
        wcfg = self.wcfg
        if severity >= 3:  # part detached
            return self.pulsed_color(wcfg["damage_panel_body_color_detached"], strength)
        if severity == 2:
            return QColor(wcfg["damage_panel_body_color_heavy"])
        if severity == 1:
            return QColor(wcfg["damage_panel_body_color_light"])
        return faded(QColor(wcfg["damage_panel_body_color"]), INTACT_ALPHA)

    def damage_wheel_color(self, detached: bool, suspension: float, strength: float = 1.0) -> QColor:
        wcfg = self.wcfg
        if detached:
            return self.pulsed_color(wcfg["damage_panel_wheel_color_detached"], strength)
        for level in ("totaled", "heavy", "medium", "light"):
            if suspension >= wcfg[f"damage_panel_suspension_{level}_threshold"]:
                return QColor(wcfg[f"damage_panel_suspension_color_{level}"])
        return faded(QColor(wcfg["damage_panel_suspension_color"]), INTACT_ALPHA)
