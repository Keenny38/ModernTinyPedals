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
Race calculator plan picture: strategy timeline & pit stop plan drawn in app colors, to share
(saved as PNG or copied to paste in a chat), same size whatever the page size or scroll
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPalette, QPen

from .race_model import TYRE_COLOR

MIN_WIDTH = 900


def plan_picture(title: str, symbol: str, timeline: dict, header: Sequence[str], rows: Sequence[Sequence[str]],
                 footer: str, tyres_column: int = -1) -> QImage:
    """Title & fuel unit, strategy timeline (stints, stops, safety car & rain), plan table, footer"""
    palette = QGuiApplication.palette()
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)
    alternate = palette.color(QPalette.ColorRole.AlternateBase)
    text = palette.color(QPalette.ColorRole.Text)
    dim = palette.color(QPalette.ColorRole.PlaceholderText)
    accent = palette.color(QPalette.ColorRole.Highlight)
    font = QFont(QGuiApplication.font())
    bold = QFont(font)
    bold.setBold(True)
    big = QFont(bold)
    big.setPointSizeF(font.pointSizeF() * 1.35)
    metrics, metrics_bold, metrics_big = QFontMetricsF(font), QFontMetricsF(bold), QFontMetricsF(big)
    line = metrics.height()
    margin = round(line * 1.2)
    row_h = round(line * 1.7)

    # Column widths: widest text, table stretched to picture width
    columns = len(header)
    widths = [max([metrics_bold.horizontalAdvance(str(header[column]))]
                  + [metrics.horizontalAdvance(str(row[column])) for row in rows]) + line * 1.6
              for column in range(columns)]
    width = max(MIN_WIDTH, round(sum(widths) + margin * 2))
    extra = (width - margin * 2 - sum(widths)) / max(columns, 1)
    widths = [value + extra for value in widths]
    timeline_h = line * 4.6 if timeline.get("ready") else 0.0
    height = round(margin * 2 + metrics_big.height() + line * 0.8 + timeline_h + row_h * (len(rows) + 1)
                   + (line * 1.8 if footer else 0))

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(window)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # Title & fuel unit badge
    top = float(margin)
    painter.setFont(big)
    painter.setPen(text)
    painter.drawText(QRectF(margin, top, width - margin * 2, metrics_big.height()),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
    badge_w = metrics_bold.horizontalAdvance(symbol) + line
    badge = QRectF(width - margin - badge_w, top + (metrics_big.height() - line * 1.3) / 2, badge_w, line * 1.3)
    painter.setFont(bold)
    painter.setPen(QPen(accent, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(badge, 4, 4)
    painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, symbol)
    top += metrics_big.height() + line * 0.8

    if timeline_h:
        draw_timeline(painter, QRectF(margin, top, width - margin * 2, timeline_h), timeline, font, text, dim,
                      accent)
        top += timeline_h

    # Plan table
    table = QRectF(margin, top, width - margin * 2, row_h * (len(rows) + 1))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(base)
    painter.drawRoundedRect(table, 6, 6)
    for index, row in enumerate([header, *rows]):
        y = top + row_h * index
        if index and index % 2 == 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(alternate)
            painter.drawRect(QRectF(margin, y, table.width(), row_h))
        x = float(margin)
        painter.setFont(bold if index == 0 else font)
        for column, value in enumerate(row):
            if index == 0:
                painter.setPen(dim)
            elif column == tyres_column and value:
                painter.setPen(QColor(TYRE_COLOR))
            else:
                painter.setPen(text)
            painter.drawText(QRectF(x, y, widths[column], row_h), Qt.AlignmentFlag.AlignCenter, str(value))
            x += widths[column]
    top += table.height()

    if footer:
        painter.setFont(font)
        painter.setPen(dim)
        painter.drawText(QRectF(margin, top + line * 0.4, width - margin * 2, line * 1.4),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, footer)
    painter.end()
    return image


def draw_timeline(painter: QPainter, area: QRectF, timeline: dict, font: QFont, text: QColor, dim: QColor,
                  accent: QColor):
    """Stint blocks (stint laps inside), stop laps above (never overlapping), first & last lap below"""
    metrics = QFontMetricsF(font)
    line = metrics.height()
    bar = QRectF(area.left(), area.top() + line * 1.3, area.width(), line * 1.5)
    painter.setFont(font)
    for band in timeline.get("bands", ()):
        color = QColor(band["color"])
        color.setAlphaF(0.45)
        x0 = bar.left() + band["start"] * bar.width()
        x1 = bar.left() + band["end"] * bar.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRect(QRectF(x0, bar.top() - 3, max(x1 - x0, 2), bar.height() + 6))
    stints = timeline.get("stints", ())
    for index, stint in enumerate(stints):
        x0 = bar.left() + stint["start"] * bar.width() + (1 if index else 0)
        x1 = bar.left() + stint["end"] * bar.width() - (1 if index < len(stints) - 1 else 0)
        color = QColor(stint["color"]) if stint["color"] else QColor(accent)
        color.setAlphaF(0.85 if stint["color"] or index % 2 == 0 else 0.55)
        block = QRectF(x0, bar.top(), max(x1 - x0, 1), bar.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(block, 5, 5)
        label = str(stint["laps"])
        if block.width() > metrics.horizontalAdvance(label) + 8:
            painter.setPen(QColor("white"))
            painter.drawText(block, Qt.AlignmentFlag.AlignCenter, label)
    label_end = -1e9
    for stop in timeline.get("stops", ()):
        x = bar.left() + stop["pos"] * bar.width()
        painter.setPen(QPen(QColor(TYRE_COLOR) if stop["tyres"] else text, 1.2))
        painter.drawLine(QPointF(x, area.top() + line), QPointF(x, bar.top() - 1))
        label = str(stop["lap"])
        label_w = metrics.horizontalAdvance(label) + 6
        label_x = min(max(x - label_w / 2, area.left()), area.right() - label_w)
        if label_x >= label_end:
            painter.drawText(QRectF(label_x, area.top(), label_w, line), Qt.AlignmentFlag.AlignCenter, label)
            label_end = label_x + label_w
    painter.setPen(dim)
    for position, lap in ((0.0, timeline.get("first", 0)), (1.0, timeline.get("last", 0))):
        x = bar.left() + position * bar.width()
        align = Qt.AlignmentFlag.AlignLeft if position == 0 else Qt.AlignmentFlag.AlignRight
        rect = QRectF(x if position == 0 else x - line * 4, bar.bottom() + 4, line * 4, line)
        painter.drawText(rect, align | Qt.AlignmentFlag.AlignTop, str(lap))
