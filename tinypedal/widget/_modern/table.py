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
Modern overlay design: table rows (relative, standings, rivals...)

A widget builds its columns once (key, width, alignment), then each update turns every row
into cells: plain values (text, colors), so state comparison is cheap and painting is pure.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

from ...i18n import tr_overlay as tr
from .base import CENTER, DASH, LEFT, RIGHT
from .draw import accent_edge, readable_on, rounded, triangle

# Cell kinds
TEXT = 0  # text: role, color
BADGE = 1  # text on filled rounded box: color = text, fill = box
CLASS = 2  # class pill: text = alias, fill = class color, extra = position in class text
CHANGE = 3  # position change: extra = signed number of places gained
COMPOUND = 4  # tyre compounds: extra = ((symbol, color), ...)
PILL = 5  # status pill (pit, garage, flag): text, color, fill
DELTAS = 6  # lap time deltas to player: extra = (seconds, ...), MAX_SECONDS if unknown
LOGO = 7  # brand logo image: text = brand name (logo file name)

SEPARATOR = "separator"  # row list item: space between class groups
CHANGE_ARROW = 0.42  # position change arrow size, in row height
COMPOUND_SIZE = 0.62  # tyre compound square, in row height
COMPOUND_GRID = 0.9  # per wheel compounds 2x2 grid height, in row height


class Column(NamedTuple):
    """Table column"""

    key: str
    width: float
    align: Qt.AlignmentFlag = LEFT
    label: str = ""  # header text (English, translated when drawn)


class Cell(NamedTuple):
    """Table cell"""

    kind: int = TEXT
    text: str = ""
    role: str = "value"
    color: QColor | None = None
    fill: QColor | None = None
    extra: Any = None


class Row(NamedTuple):
    """Table row"""

    cells: tuple[Cell, ...]
    player: bool = False
    stripe: QColor | None = None  # left edge color (vehicle class)
    faded: bool = False  # less contrast (in garage, finished)


EMPTY_CELL = Cell()


class TableLayout(NamedTuple):
    """Table geometry"""

    pad: float  # around table
    row_height: float
    row_gap: float
    col_gap: float
    stripe: float  # left edge width
    columns: tuple[Column, ...]
    x: tuple[float, ...]  # column left positions
    header: float = 0.0  # header row height, 0 = no header

    @property
    def width(self) -> float:
        if not self.columns:
            return self.pad * 2
        return self.x[-1] + self.columns[-1].width + self.col_gap * 0.75 + self.pad

    @property
    def separator(self) -> float:
        """Space between class groups (added to row gap)"""
        return self.row_height * 0.32

    def height(self, rows: int, separators: int = 0) -> float:
        return (self.pad * 2 + self.header + rows * self.row_height + max(rows - 1, 0) * self.row_gap
                + separators * self.separator)

    def content_height(self, rows: tuple) -> float:
        """Height of row list (rows & separators)"""
        separators = sum(1 for row in rows if row is SEPARATOR)
        return self.height(len(rows) - separators, separators)

    def row_rect(self, index: int) -> QRectF:
        top = self.pad + self.header + index * (self.row_height + self.row_gap)
        return QRectF(self.pad, top, self.width - self.pad * 2, self.row_height)


class TableMixin:
    """Draw table rows, for ModernOverlay widgets"""

    table: TableLayout

    def build_table(self: Any, columns: list[Column], row_scale: float = 1.62, header: bool = False) -> TableLayout:
        """Table geometry from columns, header row (column labels) if header"""
        unit = self.unit
        pad = unit * 0.3
        col_gap = unit * 0.42
        stripe = unit * 0.2
        x = []
        left = pad + stripe + col_gap * 0.75
        sized = []
        for column in columns:
            if header and column.label:  # column at least as wide as its label
                column = column._replace(width=max(column.width, self.text_width("label", tr(column.label))))
            sized.append(column)
            x.append(left)
            left += column.width + col_gap
        return TableLayout(
            pad=pad,
            row_height=unit * row_scale,
            row_gap=unit * 0.12,
            col_gap=col_gap,
            stripe=stripe,
            columns=tuple(sized),
            x=tuple(x),
            header=unit * 1.05 if header else 0.0,
        )

    def draw_header(self: Any, painter: QPainter):
        """Column labels above rows (static)"""
        table = self.table
        if not table.header:
            return
        top = table.pad
        for column, left in zip(table.columns, table.x):
            if column.label:
                rect = QRectF(left, top, column.width, table.header - table.row_gap)
                self.draw_text(painter, rect, tr(column.label), "label", self.theme.text_muted, column.align, elide=False)

    def draw_row_background(self: Any, painter: QPainter, rect: QRectF, row: Row | None, index: int):
        """Row fill, player highlight, class color edge"""
        theme = self.theme
        radius = self.radius(0.3)
        if row is None:
            rounded(painter, rect, radius, theme.tint(theme.surface_alt, 90))
            return
        if row.player:
            rounded(painter, rect, radius, theme.highlight)
        else:
            rounded(painter, rect, radius, theme.tint(theme.surface_alt, 200 if index % 2 else 150))
        edge = theme.accent if row.player else row.stripe
        if edge is not None:
            accent_edge(painter, rect, edge, self.table.stripe, radius)

    def draw_rows(self: Any, painter: QPainter, rows: tuple, start: int = 0):
        """Draw every row of table (Row, None for empty row, SEPARATOR), first one at row index start"""
        table = self.table
        top = table.pad + table.header + start * (table.row_height + table.row_gap)
        width = table.width - table.pad * 2
        index = start
        for row in rows:
            if row is SEPARATOR:
                top += table.separator
                continue
            rect = QRectF(table.pad, top, width, table.row_height)
            top += table.row_height + table.row_gap
            index += 1
            self.draw_row_background(painter, rect, row, index)
            if row is None:
                continue
            if row.faded:
                painter.setOpacity(0.55)
            for column, left, cell in zip(table.columns, table.x, row.cells):
                if cell.kind == TEXT and not cell.text:
                    continue
                self.draw_cell(painter, QRectF(left, rect.top(), column.width, rect.height()), column, cell, row)
            if row.faded:
                painter.setOpacity(1.0)

    def draw_cell(self: Any, painter: QPainter, rect: QRectF, column: Column, cell: Cell, row: Row):
        """Draw one cell"""
        kind = cell.kind
        theme = self.theme
        if kind == TEXT:
            self.draw_text(painter, rect, cell.text, cell.role, cell.color, column.align)
        elif kind == BADGE:
            box = rect.adjusted(0, rect.height() * 0.14, 0, -rect.height() * 0.14)
            rounded(painter, box, self.radius(0.25), cell.fill or theme.surface_raised)
            self.draw_text(painter, box, cell.text, cell.role, cell.color, CENTER, elide=False)
        elif kind == CLASS:
            self.draw_class_pill(painter, rect, cell)
        elif kind == CHANGE:
            self.draw_change(painter, rect, cell.extra, column.align)
        elif kind == COMPOUND:
            self.draw_compounds(painter, rect, cell.extra)
        elif kind == DELTAS:
            self.draw_deltas(painter, rect, cell.extra)
        elif kind == LOGO:
            self.draw_logo(painter, rect, cell.text)
        elif kind == PILL:
            if not cell.text:
                return
            box = rect.adjusted(0, rect.height() * 0.2, 0, -rect.height() * 0.2)
            rounded(painter, box, box.height() / 2 * min(self.corner, 1.0), cell.fill or theme.surface_raised)
            self.draw_text(painter, box, cell.text, "label", cell.color, CENTER, elide=False)

    def draw_class_pill(self: Any, painter: QPainter, rect: QRectF, cell: Cell):
        """Class color pill with alias, then position in class on darker part (or on cell color:
        class styled position)"""
        theme = self.theme
        box = rect.adjusted(0, rect.height() * 0.17, 0, -rect.height() * 0.17)
        radius = self.radius(0.25)
        fill = cell.fill or theme.surface_raised
        if cell.extra:
            pos_fill = cell.color or theme.surface_raised
            rounded(painter, box, radius, pos_fill)
            split = box.width() * 0.6
            alias_box = QRectF(box.left(), box.top(), split, box.height())
            rounded(painter, alias_box, radius, fill)
            painter.fillRect(QRectF(alias_box.right() - radius, box.top(), radius, box.height()), fill)
            self.draw_text(painter, alias_box, cell.text, "small", readable_on(fill), CENTER)
            pos_box = QRectF(box.left() + split, box.top(), box.width() - split, box.height())
            pos_color = readable_on(pos_fill) if cell.color is not None else theme.text
            self.draw_text(painter, pos_box, cell.extra, "small", pos_color, CENTER, elide=False)
        else:
            rounded(painter, box, radius, fill)
            self.draw_text(painter, box, cell.text, "small", readable_on(fill), CENTER)

    def draw_change(self: Any, painter: QPainter, rect: QRectF, places: int, align: Qt.AlignmentFlag):
        """Places gained (green up arrow) or lost (red down arrow)"""
        theme = self.theme
        if not places:
            self.draw_text(painter, rect, DASH, "dim", theme.text_faint, CENTER)
            return
        color = theme.positive if places > 0 else theme.negative
        size = rect.height() * CHANGE_ARROW
        arrow = QRectF(rect.left(), rect.center().y() - size / 2, size, size)
        triangle(painter, arrow, places > 0, color)
        text_rect = QRectF(arrow.right() + size * 0.3, rect.top(), rect.width() - size * 1.3, rect.height())
        self.draw_text(painter, text_rect, f"{abs(places)}", "value", color, LEFT, elide=False)

    def draw_deltas(self: Any, painter: QPainter, rect: QRectF, deltas: tuple):
        """Lap time difference to player of recent laps: green if player was faster"""
        if not deltas:
            return
        theme = self.theme
        width = rect.width() / len(deltas)
        for index, delta in enumerate(deltas):
            box = QRectF(rect.left() + width * index, rect.top(), width, rect.height())
            if -999 < delta < 0:
                text, color = f"{-delta:.0f}" if delta < -9.94 else f"{-delta:.1f}", theme.positive
            elif 0 < delta < 999:
                text, color = f"{delta:.0f}" if delta > 9.94 else f"{delta:.1f}", theme.negative
            elif delta == 0:
                text, color = "0.0", theme.text_dim
            else:
                text, color = DASH, theme.text_faint
            self.draw_text(painter, box, text, "small", color, RIGHT, elide=False)

    def draw_compounds(self: Any, painter: QPainter, rect: QRectF, compounds: tuple):
        """Tyre compound letters on compound colored squares: one per axle side by side, or 4 in
        a 2x2 grid (front left, front right, rear left, rear right) when wheels of an axle differ"""
        if not compounds:
            return
        radius = self.radius(0.2)
        if len(compounds) == 4:
            role = "tiny" if "tiny" in self.fonts else "label"
            grid = rect.height() * COMPOUND_GRID
            gap = grid * 0.08
            size = (grid - gap) / 2
            top = rect.center().y() - grid / 2
            for index, (symbol, color) in enumerate(compounds):
                row, column = divmod(index, 2)
                box = QRectF(rect.left() + column * (size + gap), top + row * (size + gap), size, size)
                rounded(painter, box, radius * 0.7, color)
                self.draw_text(painter, box, symbol, role, readable_on(color), CENTER, elide=False)
            return
        size = rect.height() * COMPOUND_SIZE
        gap = size * 0.18
        left = rect.left()
        top = rect.center().y() - size / 2
        for symbol, color in compounds:
            box = QRectF(left, top, size, size)
            rounded(painter, box, radius, color)
            self.draw_text(painter, box, symbol, "label", readable_on(color), CENTER, elide=False)
            left += size + gap

    def draw_logo(self: Any, painter: QPainter, rect: QRectF, brand: str):
        """Brand logo centered in cell"""
        if not brand:
            return
        pixmap = self.brand_logo(brand, rect.width(), rect.height() * 0.72)
        if pixmap.isNull():
            return
        ratio = pixmap.devicePixelRatio() or 1.0
        width = pixmap.width() / ratio
        height = pixmap.height() / ratio
        target = QRectF(rect.center().x() - width / 2, rect.center().y() - height / 2, width, height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.restore()

    def brand_logo(self: Any, brand: str, width: float, height: float) -> QPixmap:
        """Brand logo from brand logo folder scaled to fit cell, loaded once per brand (empty
        pixmap if none)"""
        from ...userfile.custom_image import load_brand_logo_image

        cache = self.__dict__.setdefault("_logo_cache", {})
        pixmap = cache.get(brand)
        if pixmap is None:
            scale = 2.0  # sharp on high DPI screen
            pixmap = load_brand_logo_image(
                filepath=self.cfg.path.brand_logo, filename=brand,
                max_width=max(round(width * scale), 1), max_height=max(round(height * scale), 1),
            )
            if not pixmap.isNull():
                pixmap.setDevicePixelRatio(scale)
            cache[brand] = pixmap
        return pixmap


def compounds_width(unit: float, row_scale: float, count: int) -> float:
    """Width of compound cell for count compounds"""
    size = unit * row_scale * COMPOUND_SIZE
    return size * count + size * 0.18 * max(count - 1, 0)


def change_width(unit: float, row_scale: float, digit_width: float, digits: int = 2) -> float:
    """Width of position change cell: arrow & gap, then number of places"""
    return unit * row_scale * CHANGE_ARROW * 1.3 + digit_width * digits

