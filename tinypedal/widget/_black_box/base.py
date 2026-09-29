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
Black box widget, shared painting helpers: cached background, fitted text, units
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPixmap

from .._painter import fill_rect, fit_font
from .common import FONT_CACHE_SIZE


class PaintBase:
    """Shared painting helpers: cached background, fitted text, units"""

    def unit_name(self, name: str) -> str:
        """Unit set in widget, or the one in Units setting"""
        value = self.wcfg[f"override_unit_{name}"]
        return self.cfg.units[f"{name}_unit"] if value == "Global" else value

    def background_layer(self) -> QPixmap:
        """Background, caption & trace panel, drawn once, then again only if
        size or screen scale changes"""
        ratio = self.devicePixelRatioF()
        layer = self.static_layer
        if layer is not None and layer.devicePixelRatio() == ratio and layer.deviceIndependentSize() == self.size():
            return layer
        layer = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self.font())
        wcfg = self.wcfg
        if wcfg["show_background"]:
            fill_rect(painter, self.rect_bg, wcfg["background_color"])
        if not self.rect_caption.isEmpty():
            fill_rect(painter, self.rect_caption, wcfg["background_color_caption"])
            painter.setPen(self.pen_caption)
            self.draw_fit_text(painter, self.rect_caption, wcfg["caption_text"], self.font_small)
        if not self.rect_trace.isNull():
            fill_rect(painter, self.rect_trace, wcfg["trace_background_color"])
        painter.end()
        self.static_layer = layer
        return layer

    def draw_fit_text(self, painter: QPainter, rect: QRectF, text: str, font: QFont,
                      align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter):
        """Draw text with font adapted to box size"""
        painter.setFont(self.fitted_font(painter, font, text, rect.width() * 0.96, rect.height() * 1.1))
        painter.drawText(rect, align, text)
        painter.setFont(self.font())

    def fitted_font(self, painter: QPainter, font: QFont, text: str, width: float, height: float) -> QFont:
        """fit_font result, cached: the same texts come back in the same boxes every frame"""
        key = (font.key(), text, round(width), round(height))
        fitted = self.font_cache.get(key)
        if fitted is None:
            if len(self.font_cache) >= FONT_CACHE_SIZE:
                self.font_cache.clear()
            fitted = self.font_cache[key] = fit_font(painter, font, text, width, height)
        return fitted

    def format_temp(self, value: float) -> str:
        if value < -100:
            return "-"
        return f"{self.unit_temp(value):.0f}{self.sign_text}"
