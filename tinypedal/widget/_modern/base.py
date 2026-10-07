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
from functools import lru_cache
from math import ceil
from time import gmtime, strftime
from typing import Any, ClassVar

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap, QStaticText

from ...const_file import FontFile
from .._base import Overlay
from .._painter import layer_fits
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


# Value text (number with sign, separators & short unit: "1:23.456", "+0.12", "88°", "1.85bar",
# "0 km/h", "73.36/~227.92 (+0)"), drawn in the value font (monospace) when modern font is on.
# Text with a word before the number ("Max 2.02", "GT3", "S1") is a label: design font.
VALUE_TEXT = re.compile(
    r"[^\w\s]*\s*"  # leading symbols (arrows, signs)
    r"[x\u00d7]?"  # multiplier ("x1")
    r"[\d\s.,:+\-\u2212\u2013/~%°()Δ±]*\d[\d\s.,:+\-\u2212\u2013/~%°()Δ±]*"
    r"(?:[A-Za-z]{1,4}(?:/[A-Za-z]{1,2})?)?"  # unit ("kW", "km/h", "PM")
    r"\s*[^\w\s]*"  # trailing symbols (arrows, dots)
)


def design_font_family(style: dict) -> str:
    """Font family of modern design"""
    return style.get("modern_design_font_name") or FontFile.DESIGN_FAMILY


def modern_font_enabled(style: dict) -> bool:
    """Modern font on: design font for text, modern (monospace) font for values of modern design;
    off: each modern design overlay uses its own "font_name" option for all text"""
    return bool(style.get("enable_modern_font", True))


def value_font_family(style: dict) -> str:
    """Font family of values (numbers) of modern design, "" if values use design font"""
    if not modern_font_enabled(style):
        return ""
    return style.get("modern_font_name") or FontFile.MODERN_FAMILY


@lru_cache(maxsize=4096)
def is_value_text(text: str) -> bool:
    """Whether text is a value (number, time, gap...) drawn in value font"""
    return VALUE_TEXT.fullmatch(text) is not None


def cap_height_ratio(font: QFont, value_family: str) -> float:
    """Pixel size ratio of value font to font, for the same capital letter & digit height (value
    font digits as tall as design text beside them)"""
    return _cap_height_ratio(font.family(), font.weight().value, value_family)


@lru_cache(maxsize=32)
def _cap_height_ratio(family: str, weight: int, value_family: str) -> float:
    heights = []
    for name in (family, value_family):
        font = QFont(name)
        font.setPixelSize(100)
        font.setWeight(QFont.Weight(weight))
        heights.append(QFontMetricsF(font).capHeight())
    if heights[1] <= 0:
        return 1.0
    return min(max(heights[0] / heights[1], 0.7), 1.3)


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
        # Modern font on: design font & monospace values, off: widget font option for all text
        self.modern_font = modern_font_enabled(style)
        self.font_family = design_font_family(style) if self.modern_font else (
            self.wcfg.get("font_name") or design_font_family(style))
        self.value_family = value_font_family(style)
        corner = min(max(float(style.get("corner_radius_scale", DEFAULT_CORNER_SCALE)), 0.0), 0.5)
        self.corner = corner / DEFAULT_CORNER_SCALE  # 1 = default roundness, 0 = square
        self.depth_effects = bool(style.get("enable_depth_effects", True))
        self.fonts: dict[str, QFont] = {}
        self.metrics: dict[str, QFontMetricsF] = {}
        self._value_roles: dict[str, str] = {}  # role: role of its value font (numbers)
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
        """Create font for role (value, label...), size relative to unit

        Modern font on, a role in design font (not caps labels, nor own family) gets a value font:
        values (numbers) drawn with role are in modern font (monospace digits), same digit height.
        Modern font off, every role is in widget font option.
        """
        if not self.modern_font:
            family = ""  # widget font for all text
        font = self._make_font(role, family or self.font_family, self.unit * scale, weight, spacing, caps)
        if caps:
            self._caps_roles.add(role)
        else:
            self._caps_roles.discard(role)
        value_role = f"{role}#value"
        if self.value_family and not caps and not family:
            ratio = cap_height_ratio(font, self.value_family)
            self._make_font(value_role, self.value_family, self.unit * scale * ratio, weight, spacing, caps)
            self._value_roles[role] = value_role
        else:
            self._value_roles.pop(role, None)
            self.fonts.pop(value_role, None)
            self.metrics.pop(value_role, None)
        self._width_cache.clear()
        return font

    def _make_font(self, role: str, family: str, size: float, weight: str, spacing: float,
                   caps: bool) -> QFont:
        font = self.config_font(family, size)
        font.setWeight(WEIGHTS.get(weight, QFont.Weight.DemiBold))
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        if spacing != 100:
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
        if caps:
            font.setCapitalization(QFont.Capitalization.AllUppercase)
        self.fonts[role] = font
        self.metrics[role] = QFontMetricsF(font)
        return font

    def font_role(self, role: str, text: str) -> str:
        """Role whose font draws text: value font role for values (modern font on), else role"""
        value_role = self._value_roles.get(role)
        if value_role is not None and is_value_text(text):
            return value_role
        return role

    def text_font(self, role: str, text: str) -> QFont:
        """Font drawing text with role (value font for values)"""
        return self.fonts[self.font_role(role, text)]

    def text_width(self, role: str, text: str) -> float:
        """Text advance width with role font"""
        if self.fonts[role].capitalization() == QFont.Capitalization.AllUppercase:
            text = text.upper()
        return self.metrics[self.font_role(role, text)].horizontalAdvance(text)

    def widest(self, role: str, texts: Iterable[str]) -> str:
        """Widest of texts with role font (sizing sample of values that vary by unit or language)"""
        return max(texts, key=lambda text: self.text_width(role, text), default="")

    def advance(self, role: str, text: str, font_role: str = "") -> float:
        """Cached text advance width (text already in role capitalization)

        Args:
            font_role: role whose font measures text, else found from text (see font_role).
        """
        key = (role, text, font_role) if font_role else (role, text)
        width = self._width_cache.get(key)
        if width is None:
            if len(self._width_cache) > self.text_cache_size():
                self._width_cache.clear()
            width = self.metrics[font_role or self.font_role(role, text)].horizontalAdvance(text)
            self._width_cache[key] = width
        return width

    def digit_width(self, role: str) -> float:
        """Width of one digit (tabular figures, value font when modern font is on)"""
        return self.metrics[self.font_role(role, "0")].horizontalAdvance("0")

    def text_cache_size(self) -> int:
        """Number of cached texts: in proportion to texts drawn in last paint (memory of long races)"""
        return min(TEXT_CACHE_SIZE, max(TEXT_CACHE_MIN, self._last_texts_drawn * TEXT_CACHE_PER_DRAW))

    def static_text(self, role: str, text: str, font_role: str = "") -> QStaticText:
        """Cached text layout, least recently drawn dropped first (names & labels drawn every
        update stay cached in long races, changing values make way)

        Args:
            font_role: role whose font lays out text, else found from text (see font_role).
        """
        self._texts_drawn += 1
        key = (role, text, font_role) if font_role else (role, text)
        cache = self._text_cache
        static = cache.get(key)
        if static is None:
            static = QStaticText(text)
            static.setTextFormat(Qt.TextFormat.PlainText)
            static.setPerformanceHint(QStaticText.PerformanceHint.AggressiveCaching)
            static.prepare(font=self.fonts[font_role or self.font_role(role, text)])
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
            result = self.metrics[self.font_role(role, text)].elidedText(text, Qt.TextElideMode.ElideRight, width)
            self._elide_cache[key] = result
        return result

    def draw_text(self, painter: QPainter, rect: QRectF, text: str, role: str = "value",
                  color: QColor | None = None, align: Qt.AlignmentFlag = LEFT, elide: bool = True):
        """Draw single line text in rect, capital letters centered vertically"""
        if not text or not drawable(rect):
            return
        if role in self._caps_roles:
            text = text.upper()
        font_role = self.font_role(role, text)  # value font for values
        width = self.advance(role, text)
        cut_role = ""  # elided text keeps font of whole text ("#93 Peug…" is no value)
        if elide and width > rect.width() + 0.5:  # (centered text not elided overflows on both sides)
            text = self.elided(role, text, rect.width())
            cut_role = font_role
            width = self.advance(role, text, cut_role)
        metrics = self.metrics[font_role]
        static = self.static_text(role, text, cut_role)
        if align & RIGHT:
            x = rect.right() - width
        elif align & CENTER:
            x = rect.center().x() - width / 2
        else:
            x = rect.left()
        y = rect.center().y() + metrics.capHeight() / 2 - metrics.ascent()
        painter.setFont(self.fonts[font_role])
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
        if layer is not None and layer_fits(layer, self.width(), self.height(), ratio):
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
