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
from .._painter import fill_chip, fill_chip_gradient

INTACT_ALPHA = 200  # intact body & wheels: visible, but behind damaged parts
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
    """Car seen from above: rounded body shell cut in 8 segments, wheels sticking out on both
    sides at front & rear, integrity in the middle of the body"""
    margin = max(unit * 0.2, 2)
    gap = max(unit * 0.08, 1)
    inner = rect.adjusted(margin, margin, -margin, -margin)
    wheel_w = max(inner.width() * 0.15, 3)
    body = inner.adjusted(wheel_w + gap, 0, -wheel_w - gap, 0)
    # Segment grid: side columns & front / rear rows, middle row taller
    side_w = body.width() * 0.3
    front_h = body.height() * 0.28
    columns = (
        (body.left(), side_w),
        (body.left() + side_w + gap, body.width() - side_w * 2 - gap * 2),
        (body.right() - side_w, side_w),
    )
    rows = (
        (body.top(), front_h),
        (body.top() + front_h + gap, body.height() - front_h * 2 - gap * 2),
        (body.bottom() - front_h, front_h),
    )
    grid = ((0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2))  # (column, row)
    parts = tuple(
        QRectF(columns[column][0], rows[row][0], columns[column][1], rows[row][1]) for column, row in grid
    )
    radius = body.width() * 0.38  # rounded nose & tail
    thickness = max(body.width() * 0.2, 2)
    shell = QPainterPath()
    shell.addRoundedRect(body, radius, radius)
    hole = body.adjusted(thickness, thickness, -thickness, -thickness)
    cut = QPainterPath()
    cut.addRoundedRect(hole, max(radius - thickness, 1), max(radius - thickness, 1))
    shell = shell.subtracted(cut)

    wheel_h = body.height() * 0.22
    front_y = body.top() + body.height() * 0.1
    rear_y = body.bottom() - body.height() * 0.1 - wheel_h
    wheels = (
        QRectF(inner.left(), front_y, wheel_w, wheel_h),
        QRectF(inner.right() - wheel_w, front_y, wheel_w, wheel_h),
        QRectF(inner.left(), rear_y, wheel_w, wheel_h),
        QRectF(inner.right() - wheel_w, rear_y, wheel_w, wheel_h),
    )
    text_area = hole.adjusted(gap, hole.height() * 0.12, -gap, -hole.height() * 0.12)
    caption = QRectF(text_area.left(), text_area.top(), text_area.width(), text_area.height() * 0.22)
    integrity = QRectF(text_area.left(), caption.bottom(), text_area.width(), text_area.height() * 0.5)
    gauge_h = max(text_area.height() * 0.08, 2)
    gauge = QRectF(text_area.left() + text_area.width() * 0.1, integrity.bottom() + gap,
                   text_area.width() * 0.8, gauge_h)
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
        # No panel box of its own: drawn straight on the widget background (tab of the same color)
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
        # Thin outline keeps the car shape readable at a glance, whatever the damage
        edge = QColor(self.wcfg["damage_panel_body_color"]).lighter(150)
        edge.setAlpha(170)
        painter.strokePath(shapes.shell, QPen(edge, max(self.unit * 0.05, 1)))

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
        self.draw_fit_text(painter, shapes.integrity, f"{value:.0%}", self.grown_font(self.font(), shapes.integrity),
                           align)
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
