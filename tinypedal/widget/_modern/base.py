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
Modern overlay design: base widget

A modern widget is one painted surface (no child cell widgets): timerEvent reads data into
a state tuple, refresh() repaints only if state changed, paint() draws from state. Background
parts that never change are drawn once into a cached layer (paint_static).

Sizes derive from one unit: widget "font_size" option (already multiplied by global overlay
scale), so a widget scales as a whole.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Iterable
from math import ceil
from time import gmtime, strftime
from typing import Any, ClassVar

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap, QStaticText

from ...const_file import FontFile
from .._base import Overlay
from .draw import drawable
from .theme import Theme, build_theme

Align = Qt.AlignmentFlag
LEFT = Align.AlignLeft
RIGHT = Align.AlignRight
CENTER = Align.AlignHCenter

DASH = chr(0x2013)  # en dash: missing value
STEADY = "0.0"  # temperature difference text when steady (shown without arrow or sign)
DEFAULT_CORNER_SCALE = 0.05  # global corner_radius_scale default, = radius unit 1
# Unit = font_size option x this: design font is lighter & narrower than classic monospace
# fonts, same font_size option reads about as large
DESIGN_SCALE = 1.12
# Cached text layouts (about 0.8 KB each) & widths, in proportion to texts drawn per paint: labels
# & names drawn every update stay cached, changing values (times, gaps) make way
TEXT_CACHE_SIZE = 2048  # at most (tables of many drivers)
TEXT_CACHE_MIN = 128  # at least
TEXT_CACHE_PER_DRAW = 4  # per text drawn in last paint
WEIGHTS = {
    "regular": QFont.Weight.Normal,
    "medium": QFont.Weight.Medium,
    "semibold": QFont.Weight.DemiBold,
    "bold": QFont.Weight.Bold,
}


def design_font_family(style: dict) -> str:
    """Font family of modern design"""
    return style.get("modern_design_font_name") or FontFile.DESIGN_FAMILY


def display_order_options(name: str) -> tuple[str, ...]:
    """Display order options of widget (listed in options of designs that honour them)"""
    from ...template.setting_widget import WIDGET_DEFAULT

    return tuple(key for key in WIDGET_DEFAULT.get(name, {}) if key.startswith("display_order_"))


def clock_samples(clock_format: str) -> tuple[str, ...]:
    """Texts of clock format to size its value: morning & afternoon (AM / PM, day name...),
    every digit as 8 (widest digit, digits are tabular)"""
    try:
        return tuple(
            re.sub(r"\d", "8", strftime(clock_format, gmtime(seconds)))
            for seconds in (3600 * 10, 3600 * 22, 86400 * 3 + 3600 * 10)  # Thursday & Sunday
        )
    except ValueError:  # invalid format
        return (clock_format,)


class ModernOverlay(Overlay):
    """Modern design widget base"""

    # Widget options read by modern design, shown in config dialog (common options always shown)
    options: ClassVar[tuple[str, ...]] = ()

    theme: Theme

    def __init__(self, config, widget_name):
        super().__init__(config, widget_name)
        style = self.cfg.user.config["overlay_style"]
        self.theme = build_theme(style)
        self.unit = max(self.design_unit(), 6.0)
        self.font_family = design_font_family(style)
        corner = min(max(float(style.get("corner_radius_scale", DEFAULT_CORNER_SCALE)), 0.0), 0.5)
        self.corner = corner / DEFAULT_CORNER_SCALE  # 1 = default roundness, 0 = square
        self.depth_effects = bool(style.get("enable_depth_effects", True))
        self.fonts: dict[str, QFont] = {}
        self.metrics: dict[str, QFontMetricsF] = {}
        self._text_cache: OrderedDict[tuple, QStaticText] = OrderedDict()
        self._elide_cache: dict[tuple, str] = {}
        self._width_cache: dict[tuple, float] = {}
        self._texts_drawn = 0  # in current paint
        self._last_texts_drawn = 0  # in last paint, sets cache size
        self._caps_roles: set[str] = set()
        self._static_layer: QPixmap | None = None
        self.state: Any = None
        self.add_font("value", 1.0, "semibold")
        self.add_font("strong", 1.0, "bold")
        self.add_font("dim", 1.0, "medium")
        self.add_font("small", 0.8, "semibold")
        self.add_font("label", 0.68, "bold", spacing=106, caps=True)

    # Options
    def user_text(self, key: str, design_text: str) -> str:
        """Text option changed by user, else design text (translated label): classic text options
        default to short codes (P, G, LDR...) that design replaces by its own labels"""
        text = self.wcfg.get(key, "")
        if text and text != self.cfg.default.setting.get(self.widget_name, {}).get(key, text):
            return text
        return design_text

    def display_ordered(self, items: list, key: Any = None, names: dict[str, str] | None = None) -> list:
        """Items in display_order_* option order, once user changed one of them (design order kept
        while every display order option is at default value)

        Args:
            items: rows, tiles or columns in design order.
            key: function returning item name (default: item.key).
            names: item name -> display order option suffix, if different.
        """
        get_key = key or (lambda item: item.key)
        names = names or {}
        options = [f"display_order_{names.get(name, name)}" for name in map(get_key, items)]
        default = self.cfg.default.setting.get(self.widget_name, {})
        wcfg = self.wcfg
        if all(wcfg.get(option) == default.get(option) for option in options):
            return items
        last = max((wcfg[option] for option in options if isinstance(wcfg.get(option), int)), default=0)
        orders = [wcfg[option] if isinstance(wcfg.get(option), int) else last + 1 + index
                  for index, option in enumerate(options)]  # items without option keep their place after
        return [item for _, item in sorted(zip(orders, items), key=lambda pair: pair[0])]

    # Sizes
    def design_unit(self) -> float:
        """Base size of design (override for widgets without font size option)"""
        return float(self.wcfg.get("font_size", 15)) * DESIGN_SCALE

    def px(self, scale: float) -> float:
        """Size relative to unit"""
        return self.unit * scale

    def radius(self, scale: float = 0.4) -> float:
        """Corner radius relative to unit, follows global corner roundness"""
        return self.unit * scale * self.corner

    def set_size(self, width: float, height: float):
        """Fixed widget size"""
        self.setFixedSize(max(ceil(width), 1), max(ceil(height), 1))
        self._static_layer = None

    # Fonts & text
    def add_font(self, role: str, scale: float, weight: str = "semibold", spacing: float = 100,
                 caps: bool = False, family: str = "") -> QFont:
        """Create font for role (value, label...), size relative to unit"""
        font = self.config_font(family or self.font_family, self.unit * scale)
        font.setWeight(WEIGHTS.get(weight, QFont.Weight.DemiBold))
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        if spacing != 100:
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
        if caps:
            font.setCapitalization(QFont.Capitalization.AllUppercase)
            self._caps_roles.add(role)
        else:
            self._caps_roles.discard(role)
        self._width_cache.clear()
        self.fonts[role] = font
        self.metrics[role] = QFontMetricsF(font)
        return font

    def text_width(self, role: str, text: str) -> float:
        """Text advance width with role font"""
        if self.fonts[role].capitalization() == QFont.Capitalization.AllUppercase:
            text = text.upper()
        return self.metrics[role].horizontalAdvance(text)

    def widest(self, role: str, texts: Iterable[str]) -> str:
        """Widest of texts with role font (sizing sample of values that vary by unit or language)"""
        return max(texts, key=lambda text: self.text_width(role, text), default="")

    def advance(self, role: str, text: str) -> float:
        """Cached text advance width (text already in role capitalization)"""
        key = (role, text)
        width = self._width_cache.get(key)
        if width is None:
            if len(self._width_cache) > self.text_cache_size():
                self._width_cache.clear()
            width = self.metrics[role].horizontalAdvance(text)
            self._width_cache[key] = width
        return width

    def digit_width(self, role: str) -> float:
        """Width of one digit (tabular figures)"""
        return self.metrics[role].horizontalAdvance("0")

    def text_cache_size(self) -> int:
        """Number of cached texts: in proportion to texts drawn in last paint (memory of long races)"""
        return min(TEXT_CACHE_SIZE, max(TEXT_CACHE_MIN, self._last_texts_drawn * TEXT_CACHE_PER_DRAW))

    def static_text(self, role: str, text: str) -> QStaticText:
        """Cached text layout, least recently drawn dropped first (names & labels drawn every
        update stay cached in long races, changing values make way)"""
        self._texts_drawn += 1
        key = (role, text)
        cache = self._text_cache
        static = cache.get(key)
        if static is None:
            static = QStaticText(text)
            static.setTextFormat(Qt.TextFormat.PlainText)
            static.setPerformanceHint(QStaticText.PerformanceHint.AggressiveCaching)
            static.prepare(font=self.fonts[role])
            cache[key] = static
            size = self.text_cache_size()
            while len(cache) > size:
                cache.popitem(last=False)
        else:
            cache.move_to_end(key)
        return static

    def elided(self, role: str, text: str, width: float) -> str:
        """Text cut with ellipsis to fit width"""
        key = (role, text, int(width))
        result = self._elide_cache.get(key)
        if result is None:
            if len(self._elide_cache) > self.text_cache_size():
                self._elide_cache.clear()
            result = self.metrics[role].elidedText(text, Qt.TextElideMode.ElideRight, width)
            self._elide_cache[key] = result
        return result

    def draw_text(self, painter: QPainter, rect: QRectF, text: str, role: str = "value",
                  color: QColor | None = None, align: Qt.AlignmentFlag = LEFT, elide: bool = True):
        """Draw single line text in rect, capital letters centered vertically"""
        if not text or not drawable(rect):
            return
        metrics = self.metrics[role]
        if role in self._caps_roles:
            text = text.upper()
        width = self.advance(role, text)
        if elide and width > rect.width() + 0.5:  # (centered text not elided overflows on both sides)
            text = self.elided(role, text, rect.width())
            width = self.advance(role, text)
        static = self.static_text(role, text)
        if align & RIGHT:
            x = rect.right() - width
        elif align & CENTER:
            x = rect.center().x() - width / 2
        else:
            x = rect.left()
        y = rect.center().y() + metrics.capHeight() / 2 - metrics.ascent()
        painter.setFont(self.fonts[role])
        painter.setPen(color if color is not None else self.theme.text)
        painter.drawStaticText(QPointF(x, y), static)

    # Update & paint
    def refresh(self, state: Any):
        """Repaint if state changed"""
        if state != self.state:
            self.state = state
            self.update()

    def redraw_static(self):
        """Background parts changed (rarely changing data drawn in static layer): draw it again"""
        self._static_layer = None
        self.update()

    def static_layer(self) -> QPixmap:
        """Background drawn once per size & screen scale"""
        ratio = self.devicePixelRatioF()
        layer = self._static_layer
        if layer is not None and layer.devicePixelRatio() == ratio and layer.deviceIndependentSize() == self.size():
            return layer
        layer = QPixmap(max(round(self.width() * ratio), 1), max(round(self.height() * ratio), 1))
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.GlobalColor.transparent)
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.paint_static(painter)
        painter.end()
        self._static_layer = layer
        return layer

    def paintEvent(self, event):
        """Draw cached background, then current state"""
        self._texts_drawn = 0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.drawPixmap(0, 0, self.static_layer())
        if self.state is not None:
            self.paint(painter)
        self._last_texts_drawn = self._texts_drawn

    def paint_static(self, painter: QPainter):
        """Draw parts that never change (override)"""

    def paint(self, painter: QPainter):
        """Draw current state (override)"""
