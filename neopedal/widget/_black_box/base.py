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
Black box widget, shared painting helpers: cached background, fitted text, units
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from .._painter import fill_rect, fit_font, layer_fits
from .common import FONT_CACHE_SIZE

if TYPE_CHECKING:
    from ...template.widget_config_types import BlackBoxConfig


class PaintBase:
    """Shared painting helpers: cached background, fitted text, units"""

    # Attributes set by black box widget class (widget/black_box.py) or other parts
    cfg: Any
    devicePixelRatioF: Any
    fit: Any
    font: Any
    font_label: Any
    font_small: Any
    height: Any
    modules: Any
    path_bg: Any
    pen_caption: Any
    rect_caption: Any
    rect_car_view: Any
    rect_trace: Any
    sign_text: Any
    size: Any
    unit: Any
    unit_temp: Any
    wcfg: BlackBoxConfig
    width: Any

    static_layer: QPixmap | None
    _widget_font: QFont | None = None
    _fitted_fonts: dict[tuple, tuple[QFont, QFont]] | None = None

    def widget_font(self) -> QFont:
        """Widget font, kept (font() returns a new copy every call; set once, see config_fonts)"""
        font = self._widget_font
        if font is None:
            font = self._widget_font = self.font()
        return font

    def unit_name(self, name: str) -> str:
        """Unit set in widget, or the one in Units setting"""
        value = self.wcfg[f"override_unit_{name}"]
        return self.cfg.units[f"{name}_unit"] if value == "Global" else value

    def background_layer(self) -> QPixmap:
        """Background, caption & trace panel, drawn once, then again only if
        size or screen scale changes"""
        ratio = self.devicePixelRatioF()
        layer = self.static_layer
        if layer is not None and layer_fits(layer, self.width(), self.height(), ratio):
            return layer
        layer = QPixmap(max(round(self.width() * ratio), 1), max(round(self.height() * ratio), 1))
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(self.widget_font())
        wcfg = self.wcfg
        fit = self.fit
        fitted = fit.scale != 1 or fit.offset_x or fit.offset_y
        if wcfg["show_background"] and fitted:  # fixed size: whole widget, room around content included
            fill_rect(painter, QRectF(0, 0, self.width(), self.height()), wcfg["background_color"])
        self.apply_fit(painter)
        if wcfg["show_background"] and not fitted:  # main area & damage panel tab, nothing above panel
            self.fill_background(painter)
        if not self.rect_caption.isEmpty():
            fill_rect(painter, self.rect_caption, wcfg["background_color_caption"])
            painter.setPen(self.pen_caption)
            self.draw_fit_text(painter, self.rect_caption, wcfg["caption_text"], self.font_small)
        if not self.rect_trace.isNull():
            fill_rect(painter, self.rect_trace, wcfg["trace_background_color"])
        painter.end()
        self.static_layer = layer
        return layer

    def fill_background(self, painter: QPainter):
        """Background shape: main card & damage panel card"""
        painter.fillPath(self.path_bg, QColor(self.wcfg["background_color"]))

    def draw_module_warning(self, painter: QPainter):
        """Which data module is off, at the bottom of the car view, on its own chip"""
        text = self.modules.missing_text()
        view = self.rect_car_view
        chip_h = self.unit * 0.8
        painter.setFont(self.font_label)
        chip_w = min(painter.fontMetrics().horizontalAdvance(text) + self.unit * 0.8, view.width())
        chip = QRectF(view.center().x() - chip_w / 2, view.bottom() - chip_h - self.unit * 0.1, chip_w, chip_h)
        fill_rect(painter, chip, self.wcfg["info_background_color"])
        painter.setPen(QColor(self.wcfg["font_color_module_warning"]))
        self.draw_fit_text(painter, chip, text, self.font_label)
        painter.setFont(self.widget_font())

    def apply_fit(self, painter: QPainter):
        """Content transform for fixed width / height: uniform scale, centered"""
        fit = self.fit
        if fit.scale != 1 or fit.offset_x or fit.offset_y:
            painter.translate(fit.offset_x, fit.offset_y)
            painter.scale(fit.scale, fit.scale)

    def draw_fit_text(self, painter: QPainter, rect: QRectF, text: str, font: QFont,
                      align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter):
        """Draw text with font adapted to box size"""
        painter.setFont(self.fitted_font(painter, font, text, rect.width() * 0.96, rect.height() * 1.1))
        painter.drawText(rect, align, text)
        painter.setFont(self.widget_font())

    def fitted_font(self, painter: QPainter, font: QFont, text: str, width: float, height: float) -> QFont:
        """fit_font result, cached: the same texts come back in the same boxes every frame

        Keyed by font object: cache holds it, so its id is not reused by another font. Copies of the widget font
        (font()) share the widget font entries.
        """
        cache = self._fitted_fonts
        if cache is None:
            cache = self._fitted_fonts = {}
        key = (id(font), text, round(width), round(height))
        entry = cache.get(key)
        if entry is not None:
            return entry[1]
        widget_font = self.widget_font()
        if font is not widget_font and font == widget_font:
            return self.fitted_font(painter, widget_font, text, width, height)
        if len(cache) >= FONT_CACHE_SIZE:
            cache.clear()
        fitted = fit_font(painter, font, text, width, height)
        cache[key] = (font, fitted)
        return fitted

    def format_temp(self, value: float) -> str:
        if value < -100:
            return "-"
        return f"{self.unit_temp(value):.0f}{self.sign_text}"
