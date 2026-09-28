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
Overlay base painter class.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from ..perf_monitor import timed_event


class OverlayStyle:
    """Shared overlay painting style"""

    # Corner radius scale, relative to the shorter side of rect (0 = square corner)
    corner_scale = 0.0


@lru_cache(maxsize=1024)
def _rounded_path(x: float, y: float, width: float, height: float, radius: float) -> QPainterPath:
    """Rounded rect path, cached as same bar sizes are repainted every update"""
    path = QPainterPath()
    path.addRoundedRect(x, y, width, height, radius, radius)
    return path


def fill_rect(painter: QPainter, rect: QRectF, color) -> None:
    """Fill rect, with rounded corner if enabled in overlay style"""
    radius = min(rect.width(), rect.height()) * OverlayStyle.corner_scale
    if radius < 1:
        painter.fillRect(rect, color)
        return
    rect = QRectF(rect)
    path = _rounded_path(rect.x(), rect.y(), rect.width(), rect.height(), radius)
    antialiased = painter.testRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.fillPath(path, QColor(color))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, antialiased)


# A chip is a small pill-shaped element (LED, indicator badge, gauge bar). It rounds far more
# than fill_rect does, because these are thin and only read as pills at a large radius.
_CHIP_RADIUS_MULTIPLIER = 10


def chip_radius(rect: QRectF) -> float:
    """Corner radius for a capsule-shaped chip, 0 if the user disabled rounded corners

    Based on the shorter side, so a wide/short bar (RPM, pedals) and a narrow/tall one
    (battery) both read as a clean capsule instead of one of them turning into a lens shape.
    """
    short_side = min(rect.width(), rect.height())
    return short_side * min(OverlayStyle.corner_scale * _CHIP_RADIUS_MULTIPLIER, 0.5)


def fill_chip(painter: QPainter, rect: QRectF, color) -> None:
    """Fill rect as a capsule, for small chip-like elements"""
    radius = chip_radius(rect)
    if radius < 0.5:
        painter.fillRect(rect, QColor(color))
        return
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, QColor(color))


def fill_chip_gradient(painter: QPainter, rect: QRectF, color) -> None:
    """Capsule fill with a subtle gradient along its length (brighter toward the leading edge:
    right for a horizontal bar, top for a vertical one), for continuous value bars (RPM, pedals,
    battery) instead of a flat fill"""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    base = QColor(color)
    if rect.width() >= rect.height():  # horizontal bar, fills left to right
        gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
    else:  # vertical bar, fills bottom to top
        gradient = QLinearGradient(0, rect.bottom(), 0, rect.top())
    gradient.setColorAt(0.0, base.darker(112))
    gradient.setColorAt(1.0, base.lighter(122))
    radius = chip_radius(rect)
    if radius < 0.5:
        painter.fillRect(rect, QBrush(gradient))
        return
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, QBrush(gradient))


def fill_glow(painter: QPainter, rect: QRectF, color, alpha: int = 70) -> None:
    """Soft halo behind a lit element"""
    glow = QColor(color)
    glow.setAlpha(alpha)
    radius = rect.height() / 2
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, glow)


def fit_font(painter: QPainter, font: QFont, text: str, width: float, height: float) -> QFont:
    """Smaller copy of font if text does not fit in box (never larger)"""
    painter.setFont(font)
    metrics = painter.fontMetrics()
    text_w = metrics.horizontalAdvance(text)
    ratio = min(width / text_w if text_w else 1, height / metrics.height() if metrics.height() else 1)
    if ratio >= 1:
        return font
    fitted = QFont(font)
    fitted.setPixelSize(max(int(font.pixelSize() * ratio), 6))
    return fitted


def fill_pixmap(pixmap: QPixmap, color) -> None:
    """Fill pixmap background, with rounded corner if enabled in overlay style"""
    if OverlayStyle.corner_scale <= 0:
        pixmap.fill(color)
        return
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    fill_rect(painter, QRectF(QPointF(0, 0), pixmap.deviceIndependentSize()), color)
    painter.end()


class WheelGaugeBar(QWidget):
    """Wheel gauge bar"""

    def __init__(
        self,
        parent,
        padding_x: int,
        bar_width: int,
        bar_height: int,
        offset_y: int = 0,
        decimals: int = 0,
        display_range: int = 100,
        input_color: str = "",
        fg_color: str = "",
        bg_color: str = "",
        mark_width: int = 0,
        mark_color: str = "",
        maxrange_height: int = 0,
        maxrange_color: str = "",
        right_side: bool = False,
        top_side: bool = True,
    ):
        super().__init__(parent)
        self.last = -1
        self.display_range = display_range
        self.decimals = max(decimals, 0)
        self.width_scale = bar_width / self.display_range
        self.input_color = input_color
        self.bg_color = bg_color
        self.mark_color = mark_color
        self.maxrange_color = maxrange_color
        self.rect_bg = QRectF(0, 0, bar_width, bar_height)
        self.rect_input = self.rect_bg.adjusted(0, 0, 0, 0)
        self.rect_text = self.rect_bg.adjusted(padding_x, offset_y, -padding_x, 0)
        self.right_side = right_side

        if self.mark_color:
            self.rect_mark = QRectF(0, 0, mark_width, bar_height)
        else:
            self.rect_mark = self.rect_bg

        if self.maxrange_color:
            if top_side:
                self.rect_max = QRectF(0, 0, bar_width, maxrange_height)
            else:
                self.rect_max = QRectF(0, bar_height - maxrange_height, bar_width, maxrange_height)
            if right_side:
                self.rect_max.setWidth(0)
            else:
                self.rect_max.setX(bar_width)
        else:
            self.rect_max = self.rect_bg

        if right_side:
            self.align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        else:
            self.align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        self.pen = QPen()
        self.pen.setColor(fg_color)
        self.setFixedSize(bar_width, bar_height)

    def update_input(self, input_value: float):
        """Update input value"""
        if self.right_side:
            self.rect_input.setWidth(input_value * self.width_scale)
        else:
            self.rect_input.setX((self.display_range - input_value) * self.width_scale)
        self.update()

    def update_mark(self, mark_value: float):
        """Update mark"""
        if self.right_side:
            self.rect_mark.moveRight(mark_value * self.width_scale)
        else:
            self.rect_mark.moveLeft((self.display_range - mark_value) * self.width_scale)

    def update_maxrange(self, input_value: float):
        """Update max range"""
        if self.right_side:
            self.rect_max.setWidth(input_value * self.width_scale)
        else:
            self.rect_max.setX((self.display_range - input_value) * self.width_scale)

    def paintEvent(self, event):
        """Draw normal without warning or negative highlighting"""
        painter = QPainter(self)
        fill_rect(painter, self.rect_bg, self.bg_color)
        fill_rect(painter, self.rect_input, self.input_color)
        if self.mark_color:
            painter.fillRect(self.rect_mark, self.mark_color)
        if self.maxrange_color:
            painter.fillRect(self.rect_max, self.maxrange_color)
        painter.setPen(self.pen)
        painter.drawText(self.rect_text, self.align, f"{self.last:.{self.decimals}f}")


class PedalInputBar(QWidget):
    """Pedal input bar"""

    def __init__(
        self,
        parent,
        pedal_length: int,
        pedal_extend: int,
        pedal_size: tuple[int, int, int, int],
        raw_size: tuple[int, int, int, int],
        filtered_size: tuple[int, int, int, int],
        max_size: tuple[int, int, int, int],
        reading_size: tuple[int, int, int, int],
        fg_color: str = "",
        bg_color: str = "",
        input_color: str = "",
        ffb_color: str = "",
        show_reading: bool = False,
        horizontal_style: bool = False,
    ):
        super().__init__(parent)
        self.last: Any = None
        self.is_maxed = False
        self.show_reading = show_reading
        self.input_reading = 0.0
        self.pedal_length = pedal_length
        self.pedal_extend = pedal_extend
        self.input_color = input_color
        self.bg_color = bg_color
        self.rect_pedal = QRectF(*pedal_size)
        self.rect_raw = QRectF(*raw_size)
        self.rect_filtered = QRectF(*filtered_size)
        self.rect_text = QRectF(*reading_size)
        self.horizontal_style = horizontal_style

        if ffb_color:
            self.rect_max = self.rect_pedal
            self.max_color = ffb_color
        else:
            self.rect_max = QRectF(*max_size)
            self.max_color = input_color

        self.pen = QPen()
        self.pen.setColor(fg_color)
        self.setFixedSize(pedal_size[2], pedal_size[3])

    def update_input(self, input_raw: float, input_filtered: float):
        """Update input value - horizontal style"""
        self.input_reading = max(input_raw, input_filtered) * 100
        if self.horizontal_style:
            scaled_raw = self.__scale_horizontal(input_raw)
            scaled_filtered = self.__scale_horizontal(input_filtered)
            self.rect_raw.setRight(scaled_raw)
            self.rect_filtered.setRight(scaled_filtered)
            self.is_maxed = scaled_raw >= self.pedal_length
        else:
            scaled_raw = self.__scale_vertical(input_raw)
            scaled_filtered = self.__scale_vertical(input_filtered)
            self.rect_raw.setTop(scaled_raw)
            self.rect_filtered.setTop(scaled_filtered)
            self.is_maxed = scaled_raw <= self.pedal_extend
        self.update()

    def __scale_horizontal(self, input_value: float) -> float:
        """Scale input - horizontal style"""
        return input_value * self.pedal_length

    def __scale_vertical(self, input_value: float) -> float:
        """Scale input - vertical style"""
        return (1 - input_value) * self.pedal_length + self.pedal_extend

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        fill_rect(painter, self.rect_pedal, self.bg_color)
        fill_rect(painter, self.rect_raw, self.input_color)
        fill_rect(painter, self.rect_filtered, self.input_color)
        if self.is_maxed:
            painter.fillRect(self.rect_max, self.max_color)
        if self.show_reading:
            painter.setPen(self.pen)
            painter.drawText(self.rect_text, Qt.AlignmentFlag.AlignCenter, f"{self.input_reading:.0f}")


class ProgressBar(QWidget):
    """Progress bar"""

    def __init__(
        self,
        parent,
        font: QFont | None = None,
        text: str = "",
        width: int = 0,
        height: int = 0,
        offset_x: int = 0,
        offset_y: int = 0,
        input_color: str = "",
        fg_color: str = "",
        bg_color: str = "",
        show_reading: bool = False,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        right_side: bool = False,
    ):
        super().__init__(parent)
        self.last = -1
        self.text = text
        if show_reading and font is not None:
            height = max(font.pixelSize(), height)
            self.setFont(font)
        self.bar_width = width
        self.rect_bar = QRectF(0, 0, width, height)
        self.rect_input = QRectF(0, 0, width, height)
        self.rect_text = QRectF(width * (offset_x - 0.5), offset_y, width, height)
        self.input_color = input_color
        self.bg_color = bg_color
        self.show_reading = show_reading
        self.align = align
        self.right_side = right_side
        self.pen = QPen()
        self.pen.setColor(fg_color)
        self.setFixedSize(width, height)

    def update_input(self, input_value: float):
        """Update input"""
        if self.right_side:
            self.rect_input.setLeft((1 - input_value) * self.bar_width)
        else:
            self.rect_input.setRight(input_value * self.bar_width)
        self.update()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        fill_rect(painter, self.rect_bar, self.bg_color)
        fill_rect(painter, self.rect_input, self.input_color)
        if self.show_reading:
            painter.setPen(self.pen)
            painter.drawText(self.rect_text, self.align, self.text)


class FuelLevelBar(QWidget):
    """Fuel level bar"""

    def __init__(
        self,
        parent,
        width: int,
        height: int,
        start_mark_width: int,
        refill_mark_width: int,
        input_color: str = "",
        bg_color: str = "",
        start_mark_color: str = "",
        refill_mark_color: str = "",
        show_start_mark: bool = True,
        show_refill_mark: bool = True,
    ):
        super().__init__(parent)
        self.last: Any = None
        self.bar_width = width
        self.rect_bar = QRectF(0, 0, width, height)
        self.rect_input = QRectF(0, 0, width, height)
        self.rect_start = QRectF(0, 0, start_mark_width, height)
        self.rect_refuel = QRectF(0, 0, refill_mark_width, height)
        self.input_color = input_color
        self.bg_color = bg_color
        self.start_mark_color = start_mark_color
        self.refill_mark_color = refill_mark_color
        self.show_start_mark = show_start_mark
        self.show_refill_mark = show_refill_mark
        self.setFixedSize(width, height)

    def update_input(self, input_value: float, start_value: float, refill_value: float):
        """Update input"""
        self.rect_input.setRight(input_value * self.bar_width)
        self.rect_start.moveLeft(start_value * self.bar_width)
        self.rect_refuel.moveLeft(refill_value * self.bar_width)
        self.update()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        fill_rect(painter, self.rect_bar, self.bg_color)
        fill_rect(painter, self.rect_input, self.input_color)
        if self.show_start_mark:
            painter.fillRect(self.rect_start, self.start_mark_color)
        if self.show_refill_mark:
            painter.fillRect(self.rect_refuel, self.refill_mark_color)


class GearGaugeBar(QWidget):
    """Gear gauge bar"""

    def __init__(
        self,
        parent,
        width: int,
        height: int,
        font_speed: QFont,
        gear_size: tuple[int, int, int, int],
        speed_size: tuple[int, int, int, int],
        fg_color: str,
        bg_color: str,
        show_speed: bool = True,
    ):
        super().__init__(parent)
        self.last = -1
        self.gear = "N"
        self.speed = 0
        self.color_index = 0
        self.show_speed = show_speed
        self.font_speed = font_speed
        self.bg_color = bg_color
        self.rect_gear = QRectF(*gear_size)
        self.rect_speed = QRectF(*speed_size)
        self.rect_bar = QRectF(0, 0, width, height)

        self.pen = QPen()
        self.pen.setColor(fg_color)
        self.setFixedSize(width, height)

    def update_input(self, gear: str, speed: int, color_index: int, bg_color: str):
        """Update input"""
        self.gear = gear
        self.speed = speed
        self.color_index = color_index
        self.bg_color = bg_color
        self.update()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        fill_rect(painter, self.rect_bar, self.bg_color)
        if self.color_index == -4:  # flicker trigger
            return
        painter.setPen(self.pen)
        painter.drawText(self.rect_gear, Qt.AlignmentFlag.AlignCenter, self.gear)
        if self.show_speed:
            painter.setFont(self.font_speed)
            painter.drawText(self.rect_speed, Qt.AlignmentFlag.AlignCenter, f"{self.speed:03.0f}")


class RawText(QWidget):
    """Raw text widget for optimized drawing"""

    def __init__(
        self,
        parent,
        font: QFont | None = None,
        text: str = "",
        width: int = 0,
        height: int = 0,
        fixed_width: int = 0,
        fixed_height: int = 0,
        offset_y: int = 0,
        fg_color: str = "",
        bg_color: str = "",
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        last: Any = None,
    ):
        super().__init__(parent)
        if font is not None:
            self.setFont(font)

        if fixed_width > 0:
            self.setFixedWidth(fixed_width)
        elif width > 0:
            self.setMinimumWidth(width)

        if fixed_height > 0:
            self.setFixedHeight(fixed_height)
        elif height > 0:
            self.setMinimumHeight(height)

        self.state = None
        self.last: Any = last
        self.text = text
        self.fg = fg_color if fg_color else Qt.GlobalColor.transparent
        self.bg = bg_color if bg_color else Qt.GlobalColor.transparent
        self._alignment = alignment
        self._offset_y = offset_y
        self._pen_text = QPen()
        self._width = self.width()
        self._height = self.height()

    def clear(self):
        """Clear display"""
        self.text = ""
        self.fg = Qt.GlobalColor.transparent
        self.bg = Qt.GlobalColor.transparent

    def resizeEvent(self, event):
        """Update size info"""
        self._width = self.width()
        self._height = self.height()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        self._pen_text.setColor(self.fg)
        painter.setPen(self._pen_text)
        fill_rect(painter, QRectF(0, 0, self._width, self._height), self.bg)
        painter.drawText(0, self._offset_y, self._width, self._height, self._alignment, self.text)


class RawImage(QWidget):
    """Raw image widget for optimized drawing"""

    def __init__(
        self,
        parent,
        image: QPixmap | None = None,
        width: int = 0,
        height: int = 0,
        fixed_width: int = 0,
        fixed_height: int = 0,
        bg_color: str = "",
        last: Any = None,
    ):
        super().__init__(parent)
        if fixed_width > 0:
            self.setFixedWidth(fixed_width)
        elif width > 0:
            self.setMinimumWidth(width)

        if fixed_height > 0:
            self.setFixedHeight(fixed_height)
        elif height > 0:
            self.setMinimumHeight(height)

        self.state = None
        self.last: Any = last
        self.image = image
        self.bg = bg_color if bg_color else Qt.GlobalColor.transparent
        self._width = self.width()
        self._height = self.height()

    def clear(self):
        """Clear display"""
        self.image = None
        self.bg = Qt.GlobalColor.transparent

    def resizeEvent(self, event):
        """Update size info"""
        self._width = self.width()
        self._height = self.height()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        fill_rect(painter, QRectF(0, 0, self._width, self._height), self.bg)
        if isinstance(self.image, QPixmap):
            painter.drawPixmap(
                (self._width - self.image.width()) // 2,  # align center
                (self._height - self.image.height()) // 2,
                self.image,
            )


class RawFrame(QWidget):
    """Raw frame widget for optimized drawing"""

    def __init__(
        self,
        parent,
        width: int = 0,
        height: int = 0,
        fixed_width: int = 0,
        fixed_height: int = 0,
        bg_color: str = "",
        last: Any = None,
    ):
        super().__init__(parent)
        if fixed_width > 0:
            self.setFixedWidth(fixed_width)
        elif width > 0:
            self.setMinimumWidth(width)

        if fixed_height > 0:
            self.setFixedHeight(fixed_height)
        elif height > 0:
            self.setMinimumHeight(height)

        self.state = None
        self.last: Any = last
        self.bg = bg_color if bg_color else Qt.GlobalColor.transparent
        self._width = self.width()
        self._height = self.height()

    def clear(self):
        """Clear display"""
        self.bg = Qt.GlobalColor.transparent

    def resizeEvent(self, event):
        """Update size info"""
        self._width = self.width()
        self._height = self.height()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        fill_rect(painter, QRectF(0, 0, self._width, self._height), self.bg)


class MultiCompounds(QWidget):
    """Multi color compounds text"""

    def __init__(
        self,
        parent,
        font: QFont | None = None,
        count: int = 4,
        spacing: int = 0,
        padding: int = 0,
        width: int = 0,
        height: int = 0,
        offset_y: int = 0,
        fg_color: str = "",
        bg_color: str = "",
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        last: Any = None,
    ):
        super().__init__(parent)
        if font is not None:
            self.setFont(font)

        self.setFixedWidth(count * (width + spacing) + padding)
        self.setFixedHeight(height)

        self.state = None
        self.last: Any = last
        fg = fg_color if fg_color else Qt.GlobalColor.transparent
        self.bg = bg_color if bg_color else Qt.GlobalColor.transparent
        self._count = count
        self._alignment = alignment
        self._offset_y = offset_y
        self._padding = padding // 2
        self._word_width = width + spacing
        self._pen_text = QPen()
        self._width = self.width()
        self._height = self.height()
        self.compounds = ()
        self.colors = (fg,) * count

    def clear(self):
        """Clear display"""
        self.compounds = ()
        self.colors = (Qt.GlobalColor.transparent,) * self._count
        self.bg = Qt.GlobalColor.transparent

    def resizeEvent(self, event):
        """Update size info"""
        self._width = self.width()
        self._height = self.height()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        fill_rect(painter, QRectF(0, 0, self._width, self._height), self.bg)
        for index, compound in enumerate(self.compounds):
            if compound == "":
                continue
            self._pen_text.setColor(self.colors[index])
            painter.setPen(self._pen_text)
            painter.drawText(
                self._padding + self._word_width * index,
                self._offset_y,
                self._word_width,
                self._height,
                self._alignment,
                compound,
            )


class DeltaLapTime(QWidget):
    """Delta lap time text"""

    def __init__(
        self,
        parent,
        font: QFont | None = None,
        count: int = 5,
        spacing: int = 0,
        padding: int = 0,
        width: int = 0,
        height: int = 0,
        offset_y: int = 0,
        fg_color: str = "",
        bg_color: str = "",
        fg_color_gain: str = "",
        fg_color_loss: str = "",
        fg_color_player: str = "",
        inverted: bool = False,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        last: Any = None,
    ):
        super().__init__(parent)
        if font is not None:
            self.setFont(font)

        self.setFixedWidth(count * (width + spacing) + padding)
        self.setFixedHeight(height)

        self.state = None
        self.last: Any = last
        self.fg = fg_color if fg_color else Qt.GlobalColor.transparent
        self.bg = bg_color if bg_color else Qt.GlobalColor.transparent
        self.fg_gain = fg_color_gain
        self.fg_loss = fg_color_loss
        self.fg_player = fg_color_player
        self._count = count
        self._alignment = alignment
        self._offset_y = offset_y
        self._padding = padding // 2
        self._word_width = width + spacing
        self._pen_text = QPen()
        self._width = self.width()
        self._height = self.height()
        self._inverted = inverted
        self.delta = ()
        self.is_player = False

    def clear(self):
        """Clear display"""
        self.delta = ()
        self.bg = Qt.GlobalColor.transparent
        self.is_player = False

    def resizeEvent(self, event):
        """Update size info"""
        self._width = self.width()
        self._height = self.height()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        fill_rect(painter, QRectF(0, 0, self._width, self._height), self.bg)
        for index, delta in enumerate(
            reversed(self.delta) if self._inverted else self.delta
        ):
            if delta == "":
                continue

            if -999 < delta < 0:  # player time gain
                if delta < -9.94:
                    text = f"{-delta:.0f}"
                else:
                    text = f"{-delta:.1f}"
                fg_color = self.fg_gain
            elif 0 < delta < 999:  # player time loss
                if delta > 9.94:
                    text = f"{delta:.0f}"
                else:
                    text = f"{delta:.1f}"
                fg_color = self.fg_loss
            elif delta == 0:
                text = "0.0"
                fg_color = self.fg
            else:
                text = "-.-"
                fg_color = self.fg

            if self.is_player:
                fg_color = self.fg_player

            self._pen_text.setColor(fg_color)
            painter.setPen(self._pen_text)
            painter.drawText(
                self._padding + self._word_width * index,
                self._offset_y,
                self._word_width,
                self._height,
                self._alignment,
                text,
            )


# Record paint time of all painter widgets (only while performance monitor is enabled)
for _painter_class in (
    WheelGaugeBar, PedalInputBar, ProgressBar, FuelLevelBar, GearGaugeBar,
    RawText, RawImage, RawFrame, MultiCompounds, DeltaLapTime,
):
    _painter_class.paintEvent = timed_event(_painter_class.paintEvent, "paint")  # type: ignore[method-assign]
