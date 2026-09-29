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
Black box widget, suspension (coilover) beside each brake

Drawn from the side: top mount fixed to the chassis, damper body, shaft, and a coil spring
down to the bottom mount. The bottom mount moves 1:1 with the car: its offset from the static
position (tick) is the real suspension offset in millimeters, at the same scale as the tyre
drawing (tyre height = real tyre diameter). suspension_motion_scale can magnify it.

The coilover turns with its wheel around the tyre center, like the brake disc, so the corner
reads as one assembly when steering. Tyre & disc move by the wheel travel (spring travel / motion ratio), which is larger than
the spring travel on a pushrod or rocker suspension. The spring is tinted by damper speed in two
zones (low speed body motion, high speed kerbs & bumps), and turns bump stop color (pulsing)
while the bump rubber is loaded, or airborne color while the wheel is in the air.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from .state import WheelState, damper_tint

COILS = 6
MAX_COMPRESSION = 0.8  # shortest spring is 1 - this, relative to longest
# Spring length at static position, relative to longest: 0.5 puts the wheel mount at the
# middle of the suspension rect, which is as tall as the tyre, so at the tyre (hub) center
STATIC_LENGTH = 0.5
DAMPER_LENGTH = 0.18  # damper body, relative to longest spring (shorter than shortest spring)
TYRE_DIAMETER_MM = 680.0  # tyre drawing height stands for this real diameter (race tyre)


def blend(base: QColor, tint: QColor, amount: float) -> QColor:
    """Mix tint into base color, amount 0 to 1"""
    amount = min(max(amount, 0.0), 1.0)
    return QColor.fromRgbF(
        base.redF() + (tint.redF() - base.redF()) * amount,
        base.greenF() + (tint.greenF() - base.greenF()) * amount,
        base.blueF() + (tint.blueF() - base.blueF()) * amount,
        base.alphaF(),
    )


def spring_length(full: float, travel: float) -> float:
    """Spring length for travel (0 full droop, 1 bump stop)"""
    return full * (1 - MAX_COMPRESSION * min(max(travel, 0.0), 1.0))


def spring_length_real(full: float, offset_mm: float, pixels_per_mm: float) -> float:
    """Spring length for a real offset from static position (positive = compressed), 1:1"""
    length = full * STATIC_LENGTH - offset_mm * pixels_per_mm
    return min(max(length, full * (1 - MAX_COMPRESSION)), full)


def spring_frame(rect: QRectF) -> tuple[float, float, float]:
    """(mount cap height, chassis mount y, longest spring length) of a suspension rect"""
    cap_h = max(rect.height() * 0.07, 2)
    return cap_h, rect.top() + cap_h, rect.height() - cap_h * 2


class SuspensionPainter:
    """Draw suspension beside brakes"""

    def draw_suspension(self, painter: QPainter, rect: QRectF, wheel: WheelState, index: int = 0):
        """Coilover anchored to its wheel: turns with the wheel around the tyre center, like the
        brake disc, and its wheel mount is linked to the disc bar (hub)"""
        wcfg = self.wcfg
        width = rect.width()
        cap_h, top, full = spring_frame(rect)  # top: chassis mount, fixed
        # Wheel mount follows the wheel (same travel as tyre & disc), so the corner moves as one piece
        bottom = top + spring_length_real(full, wheel.susp_wheel_offset, self.pixels_per_mm(index))
        center = rect.center().x()
        spring_color = self.spring_color(wheel)
        mount_color = QColor(wcfg["suspension_spring_color"]).darker(160)

        painter.save()
        if wheel.steer and index < len(self.rects_tyre):  # same rotation as tyre & disc
            pivot = self.rects_tyre[index].center() + QPointF(0, self.wheel_shift(index, wheel))
            painter.translate(pivot)
            painter.rotate(wheel.steer)
            painter.translate(-pivot)
        # Link from wheel mount to disc bar (hub), so spring, disc and tyre read as one assembly
        if index < len(self.rects_disc):
            disc = self.rects_disc[index]
            if index % 2:  # right side: disc bar on the right of the spring
                link_left, link_right = rect.right(), disc.right() - self.brake_bar_w
            else:
                link_left, link_right = disc.left() + self.brake_bar_w, rect.left()
            link_h = max(cap_h * 0.6, 1)
            painter.fillRect(QRectF(link_left, bottom + (cap_h - link_h) / 2, max(link_right - link_left, 0),
                                    link_h), mount_color.lighter(130))
        # Damper body (fixed to chassis) and shaft (to wheel mount), behind the spring
        body_w = width * 0.42
        body = QRectF(center - body_w / 2, top, body_w, full * DAMPER_LENGTH)
        shade = QLinearGradient(body.left(), 0, body.right(), 0)
        shade.setColorAt(0.0, mount_color.darker(130))
        shade.setColorAt(0.5, mount_color.lighter(150))
        shade.setColorAt(1.0, mount_color.darker(130))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawRoundedRect(body, body_w * 0.3, body_w * 0.3)
        shaft_w = max(width * 0.14, 1)
        painter.fillRect(QRectF(center - shaft_w / 2, body.bottom(), shaft_w, max(bottom - body.bottom(), 0)),
                         QColor(wcfg["suspension_spring_color"]).lighter(115))
        # Coil spring between mounts
        painter.setPen(QPen(spring_color, max(self.unit * 0.08, 1.2), Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.coil_path(rect.left() + width * 0.08, rect.right() - width * 0.08, top, bottom))
        # Mounts
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(mount_color)
        radius = cap_h * 0.4
        painter.drawRoundedRect(QRectF(rect.left(), top - cap_h, width, cap_h), radius, radius)
        painter.setBrush(spring_color.darker(120))
        painter.drawRoundedRect(QRectF(rect.left(), bottom, width, cap_h), radius, radius)
        # Static position tick, where the wheel mount sits with the car at rest: the gap between
        # it and the wheel mount is the real suspension offset. Hollow while the rest position is
        # only estimated (joined while driving, Wheels module off): offset is then approximate.
        static_y = top + full * STATIC_LENGTH
        tick = QColor(wcfg["font_color"])
        tick_rect = QRectF(rect.left() - width * 0.15, static_y, width * 0.2, max(cap_h * 0.35, 1))
        if wheel.susp_estimated:
            tick.setAlpha(110)
            painter.setPen(QPen(tick, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(tick_rect)
        else:
            tick.setAlpha(140)
            painter.fillRect(tick_rect, tick)
        painter.restore()

    def wheel_shift(self, index: int, wheel: WheelState) -> float:
        """Vertical shift of tyre & disc by the real wheel travel, 1:1 with the car
        (0 if suspension hidden or wheel motion disabled)"""
        if not self.wheel_suspension_motion or index >= len(self.rects_susp) or self.rects_susp[index].isNull():
            return 0.0
        _, _, full = spring_frame(self.rects_susp[index])
        return spring_length_real(full, wheel.susp_wheel_offset, self.pixels_per_mm(index)) - full * STATIC_LENGTH

    def pixels_per_mm(self, index: int) -> float:
        """Scale of wheel index: tyre drawing height stands for that tyre's real diameter"""
        diameters = getattr(self, "tyre_diameters", ())
        diameter = diameters[index] if index < len(diameters) else TYRE_DIAMETER_MM
        return self.susp_pixels_per_mm * TYRE_DIAMETER_MM / max(diameter, 1)

    @staticmethod
    def coil_path(left: float, right: float, top: float, bottom: float) -> QPainterPath:
        """Zigzag coil from top to bottom, one full coil = left to right and back"""
        path = QPainterPath(QPointF((left + right) / 2, top))
        steps = COILS * 2
        for step in range(1, steps + 1):
            x = right if step % 2 else left
            if step == steps:
                x = (left + right) / 2
            path.lineTo(x, top + (bottom - top) * step / steps)
        return path

    def spring_color(self, wheel: WheelState) -> QColor:
        """Airborne or bump stop color (pulsing), else tinted by damper speed in two zones"""
        wcfg = self.wcfg
        if wheel.susp_airborne:
            return QColor(self.pulsed_color(wcfg["suspension_airborne_color"], self.pulse()))
        if wheel.susp_bump:
            return QColor(self.pulsed_color(wcfg["suspension_bump_color"], self.pulse()))
        base = QColor(wcfg["suspension_spring_color"])
        velocity = wheel.susp_velocity
        amount = damper_tint(velocity, self.susp_low_speed, self.susp_full_speed)
        if velocity > 0:
            return blend(base, QColor(wcfg["suspension_compression_color"]), amount)
        if velocity < 0:
            return blend(base, QColor(wcfg["suspension_rebound_color"]), amount)
        return base
