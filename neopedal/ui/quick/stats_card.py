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
Personal best card of Driver Stats Viewer: picture to share (Discord, forums), drawn the same in any theme
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath, QPen

from ...const_app import APP_NAME

WIDTH, HEIGHT = 1200, 630  # social card size
BACKGROUND = ("#141A24", "#0B0F16")
ACCENT = "#3D9BFF"
TEXT = "#F2F5FA"
DIM = "#9AA6B8"
FAMILIES = ("Barlow", "Segoe UI", "Arial")  # first installed one (Barlow: app font of overlays)


class CardData(NamedTuple):
    """What a personal best card shows (texts as shown, level color "" if no level)"""

    track: str
    vehicle: str
    laptime: str
    driver: str = ""
    date: str = ""
    level: str = ""
    level_color: str = ""
    detail: str = ""  # gap to reference, conditions...
    logo: str = ""  # circuit logo file path, "" if none
    title: str = "PERSONAL BEST"  # in app language


def font_family() -> str:
    families = set(QFontDatabase.families())
    return next((family for family in FAMILIES if family in families), "")


def card_font(size: float, bold: bool = False) -> QFont:
    font = QFont(font_family()) if font_family() else QFont()
    font.setPixelSize(round(size))
    font.setBold(bold)
    return font


def ink_on(color: QColor) -> QColor:
    """Readable text color on a fill"""
    return QColor("#101418") if color.lightnessF() > 0.6 else QColor(TEXT)


def draw_card(data: CardData) -> QImage:
    """Personal best card picture"""
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        gradient = QLinearGradient(0, 0, WIDTH, HEIGHT)
        gradient.setColorAt(0, QColor(BACKGROUND[0]))
        gradient.setColorAt(1, QColor(BACKGROUND[1]))
        painter.fillRect(image.rect(), gradient)
        # Accent stripe at the left
        painter.fillRect(QRectF(0, 0, 14, HEIGHT), QColor(ACCENT))
        margin = 72.0
        right = WIDTH - margin
        # Circuit logo at the top right
        logo_width = 0.0
        if data.logo:
            logo = QImage(data.logo)
            if not logo.isNull():
                scaled = logo.scaled(260, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
                painter.drawImage(int(right - scaled.width()), int(margin), scaled)
                logo_width = scaled.width() + 30
        text_width = right - margin - logo_width
        painter.setPen(QColor(DIM))
        painter.setFont(card_font(30, True))
        painter.drawText(QRectF(margin, margin, text_width, 40), Qt.AlignmentFlag.AlignLeft, data.title)
        painter.setPen(QColor(TEXT))
        painter.setFont(card_font(58, True))
        painter.drawText(QRectF(margin, margin + 46, text_width, 76), Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, elided(painter, data.track, text_width))
        painter.setPen(QColor(DIM))
        painter.setFont(card_font(36))
        painter.drawText(QRectF(margin, margin + 126, text_width, 48), Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, elided(painter, data.vehicle, text_width))
        # Lap time, level pill after it
        painter.setPen(QColor(ACCENT))
        painter.setFont(card_font(150, True))
        time_rect = QRectF(margin, 250, right - margin, 170)
        painter.drawText(time_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, data.laptime)
        time_width = painter.fontMetrics().horizontalAdvance(data.laptime)
        if data.level and data.level_color:
            fill = QColor(data.level_color)
            painter.setFont(card_font(34, True))
            pill_width = painter.fontMetrics().horizontalAdvance(data.level) + 48
            pill = QRectF(margin + time_width + 36, 312, pill_width, 56)
            path = QPainterPath()
            path.addRoundedRect(pill, 28, 28)
            painter.fillPath(path, fill)
            painter.setPen(ink_on(fill))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, data.level)
        if data.detail:
            painter.setPen(QColor(TEXT))
            painter.setFont(card_font(32))
            painter.drawText(QRectF(margin, 430, right - margin, 44), Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter, elided(painter, data.detail, right - margin))
        # Footer: driver & date, app name
        painter.setPen(QPen(QColor(255, 255, 255, 40), 2))
        painter.drawLine(int(margin), HEIGHT - 110, int(right), HEIGHT - 110)
        painter.setPen(QColor(TEXT))
        painter.setFont(card_font(32, True))
        footer = " · ".join(part for part in (data.driver, data.date) if part)
        painter.drawText(QRectF(margin, HEIGHT - 96, right - margin - 260, 56), Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, elided(painter, footer, right - margin - 260))
        painter.setPen(QColor(DIM))
        painter.setFont(card_font(28))
        painter.drawText(QRectF(right - 260, HEIGHT - 96, 260, 56), Qt.AlignmentFlag.AlignRight
                         | Qt.AlignmentFlag.AlignVCenter, APP_NAME)
    finally:
        painter.end()
    return image


def elided(painter: QPainter, text: str, width: float) -> str:
    return painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(width))
