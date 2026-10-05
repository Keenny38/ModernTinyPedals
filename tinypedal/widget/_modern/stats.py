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
Modern overlay design: stat panels (label & value)

Horizontal: segments side by side, small caps label above value, thin dividers between.
Vertical: one row per stat, label on left, value on right.
Labels & dividers are static (drawn once); each update only draws values.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter

from ...i18n import tr_overlay as tr
from .base import CENTER, LEFT, RIGHT
from .draw import bar, panel, rounded

MARK_SIZE = 0.32  # colored mark before label, in unit
MARK_GAP = 0.3


class Stat(NamedTuple):
    """Stat definition"""

    key: str
    label: str  # English, translated when drawn
    sample: str  # widest value text, for sizing
    role: str = "value"  # value font role
    accent: QColor | None = None  # small colored mark before label
    sub_sample: str = ""  # widest secondary text, for sizing


class Value(NamedTuple):
    """Stat value of one update"""

    text: str = ""
    color: QColor | None = None
    fill: QColor | None = None  # highlighted segment background
    sub: str = ""  # small secondary text (below value, or after it in vertical layout)
    sub_color: QColor | None = None
    bar: float = -1.0  # 0-1 progress under value, -1 = none
    bar_color: QColor | None = None


class StatSlot(NamedTuple):
    """Stat geometry"""

    stat: Stat
    box: QRectF  # whole segment / row
    label: QRectF
    value: QRectF
    sub: QRectF
    row: int = 0  # grid position (horizontal layout)
    column: int = 0


class StatsMixin:
    """Draw stat panels, for ModernOverlay widgets"""

    slots: tuple[StatSlot, ...]
    stats_vertical: bool

    def build_stats(self: Any, stats: list[Stat], vertical: bool = False, show_labels: bool = True,
                    show_sub: bool = False, value_align: Any = None, columns: int = 0,
                    top: float | None = None, min_width: float = 0.0) -> tuple[float, float]:
        """Stat geometry, returns content size (width, height)

        Args:
            columns: horizontal layout, stats per row (0 = all on one row).
            top: top of first stat (default: panel padding).
            min_width: horizontal layout, stretch columns to at least this content width.
        """
        unit = self.unit
        pad = unit * 0.3
        if top is None:
            top = pad
        self.stats_vertical = vertical
        self.stats_align = value_align
        slots = []
        if not stats:
            self.slots = ()
            return pad * 2, top + pad
        if vertical:
            label_w = max(self.label_width(s) for s in stats) if show_labels else 0
            value_w = max(self.text_width(s.role, s.sample) for s in stats)
            sub_w = max((self.text_width("small", s.sub_sample or s.sample) for s in stats), default=0) if show_sub else 0
            row_h = unit * 1.45
            gap = unit * 0.5
            inner_pad = unit * 0.45
            width = pad * 2 + inner_pad * 2 + label_w + (gap if show_labels else 0) + value_w + (gap + sub_w if show_sub else 0)
            width = max(width, min_width + pad * 2)
            for row, stat in enumerate(stats):
                box = QRectF(pad, top, width - pad * 2, row_h)
                left = box.left() + inner_pad
                label = QRectF(left, top, label_w, row_h)
                value_left = label.right() + (gap if show_labels else 0)
                value_w_row = box.right() - inner_pad - value_left - (gap + sub_w if show_sub else 0)
                value = QRectF(value_left, top, value_w_row, row_h)
                sub = QRectF(value.right() + gap, top, sub_w, row_h)
                slots.append(StatSlot(stat, box, label, value, sub, row, 0))
                top += row_h + unit * 0.12
            self.slots = tuple(slots)
            return width, top - unit * 0.12 + pad
        label_h = unit * 0.95 if show_labels else 0
        value_h = unit * 1.35
        sub_h = unit * 0.9 if show_sub else 0
        inner_pad = unit * 0.55
        row_h = unit * 0.25 + label_h + value_h + sub_h + unit * 0.2
        per_row = columns if columns > 0 else len(stats)
        widths = [0.0] * per_row
        for index, stat in enumerate(stats):
            column = index % per_row
            widths[column] = max(
                widths[column],
                self.label_width(stat) if show_labels else 0,
                self.text_width(stat.role, stat.sample),
                self.text_width("small", stat.sub_sample) if show_sub else 0,
            )
        widths = [width + inner_pad * 2 for width in widths]
        extra = min_width - sum(widths)
        if extra > 0:
            widths = [width + extra / per_row for width in widths]
        for index, stat in enumerate(stats):
            row, column = divmod(index, per_row)
            left = pad + sum(widths[:column])
            box = QRectF(left, top + row * row_h, widths[column], row_h)
            label = QRectF(box.left() + inner_pad, box.top() + unit * 0.25, box.width() - inner_pad * 2, label_h)
            value = QRectF(label.left(), label.bottom(), label.width(), value_h)
            sub = QRectF(label.left(), value.bottom(), label.width(), sub_h)
            slots.append(StatSlot(stat, box, label, value, sub, row, column))
        rows = (len(stats) + per_row - 1) // per_row
        self.slots = tuple(slots)
        return pad * 2 + sum(widths), top + rows * row_h + pad

    def label_width(self: Any, stat: Stat) -> float:
        """Label width, with colored mark"""
        width = self.text_width("label", tr(stat.label))
        if stat.accent is not None:
            width += self.unit * (MARK_SIZE + MARK_GAP)
        return width

    def paint_stats_static(self: Any, painter: QPainter, show_panel: bool = True):
        """Panel, labels, dividers"""
        theme = self.theme
        if show_panel:
            panel(painter, QRectF(self.rect()), theme, self.radius(0.5), self.depth_effects)
        vertical = self.stats_vertical
        divider = theme.tint(theme.text, 26)
        unit = self.unit
        for slot in self.slots:
            stat = slot.stat
            if vertical:
                rounded(painter, slot.box, self.radius(0.3), theme.tint(theme.surface_alt, 170))
            else:
                if slot.column:
                    painter.fillRect(QRectF(slot.box.left() - 0.5, slot.box.top() + unit * 0.35, 1,
                                            slot.box.height() - unit * 0.7), divider)
                if slot.row:
                    painter.fillRect(QRectF(slot.box.left() + unit * 0.35, slot.box.top() - 0.5,
                                            slot.box.width() - unit * 0.7, 1), divider)
            if slot.label.width() > 0:
                label = slot.label
                text = tr(stat.label)
                if stat.accent is not None:
                    dot = self.unit * MARK_SIZE
                    if not vertical:  # mark & label centered together
                        width = self.label_width(stat)
                        label = QRectF(label.center().x() - width / 2, label.top(), width, label.height())
                    rounded(painter, QRectF(label.left(), label.center().y() - dot / 2, dot, dot), dot / 2, stat.accent)
                    label = label.adjusted(self.unit * (MARK_SIZE + MARK_GAP), 0, 0, 0)
                    self.draw_text(painter, label, text, "label", theme.text_muted, LEFT)
                else:
                    self.draw_text(painter, label, text, "label", theme.text_muted, LEFT if vertical else CENTER)

    def draw_stats(self: Any, painter: QPainter, values: tuple[Value, ...]):
        """Values of current update"""
        theme = self.theme
        vertical = self.stats_vertical
        align = self.stats_align or (RIGHT if vertical else CENTER)
        for slot, value in zip(self.slots, values):
            if value.fill is not None:
                box = slot.box if vertical else slot.box.adjusted(self.unit * 0.12, self.unit * 0.12, -self.unit * 0.12, -self.unit * 0.12)
                rounded(painter, box, self.radius(0.3), value.fill)
            self.draw_text(painter, slot.value, value.text, slot.stat.role, value.color or theme.text, align)
            if value.sub and slot.sub.width() > 0:
                self.draw_text(painter, slot.sub, value.sub, "small", value.sub_color or theme.text_dim,
                               LEFT if vertical else CENTER)
            if value.bar >= 0:
                height = max(self.unit * 0.14, 2)
                track = QRectF(slot.value.left(), slot.box.bottom() - height - self.unit * 0.18, slot.value.width(), height)
                bar(painter, track, value.bar, value.bar_color or theme.accent, theme.surface_raised, height / 2)
