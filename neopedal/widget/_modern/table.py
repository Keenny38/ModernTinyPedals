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
Modern overlay design: table rows (relative, standings, rivals...)

A widget builds its columns once (key, width, alignment), then each update turns every row
into cells: plain values (text, colors), so state comparison is cheap and painting is pure.
"""

from __future__ import annotations

import weakref
from typing import Any, NamedTuple

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap

from ...i18n import tr_overlay as tr
from ...userfile import custom_image, game_images  # modules: logo loader & game pictures replaced by tests
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
LOGO = 7  # brand logo image: text = brand name, extra = vehicle name (game car list)
TREND = 8  # gap trend: extra = (seconds per lap, gap growing or shrinking; good for player), None if steady
PAIR = 9  # two cells side by side: extra = (left cell, right cell, width of left part)
LAPTIME = 10  # lap time: text, role, color; extra = LapTimeExtra (sector bars, delta, trend)
ICON = 11  # picture file (svg, png) in a square: text = file ("" while none: dot of color), color = dot
INSIDE_CELL = (TEXT, LOGO, LAPTIME)  # kinds drawn inside their cell (elided text, logo fit, lap time parts): repainted alone

SEPARATOR = "separator"  # row list item: space between class groups
CLASS_HEADER_SCALE = 0.82  # class header strip height, in row height
CHANGE_ARROW = 0.42  # position change arrow size, in row height
COMPOUND_SIZE = 0.62  # tyre compound square, in row height
COMPOUND_GRID = 0.9  # per wheel compounds 2x2 grid height, in row height
LOGO_CHECK_MS = 150  # waited logo checked for at this interval (update timer may be stopped)
# Layered overlay window uploads bounding rect of each repaint: far apart changed parts repainted one by one
MAX_FLUSHES = 4  # at most, else one repaint of all


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


class LapTimeExtra(NamedTuple):
    """Lap time cell parts: sector bars under time ((color, filled share) of S1, S2, S3, color None: not driven
    yet), trend arrow at right end (-1 slower, 1 faster than lap before, 0 none), width of time slot (lap time,
    delta or running time, one at a time), of space kept for arrow, of sector bars"""

    sectors: tuple = ()
    trend: int = 0
    time_width: float = 0.0
    side_width: float = 0.0
    bars_width: float = 0.0


class Row(NamedTuple):
    """Table row"""

    cells: tuple[Cell, ...]
    player: bool = False
    stripe: QColor | None = None  # left edge color (vehicle class)
    faded: bool = False  # less contrast (in garage, finished)


class ClassHeader(NamedTuple):
    """Row list item: name of class above its cars, info at right end (strength of field)"""

    text: str
    color: QColor
    info: str = ""
    info_color: QColor | None = None


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
    split_scale: float = 1.0  # space between class groups, in design space

    @property
    def width(self) -> float:
        if not self.columns:
            return self.pad * 2
        return self.x[-1] + self.columns[-1].width + self.col_gap * 0.75 + self.pad

    @property
    def separator(self) -> float:
        """Space between class groups (added to row gap)"""
        return self.row_height * 0.32 * self.split_scale

    @property
    def class_header(self) -> float:
        """Height of class header strip"""
        return self.row_height * CLASS_HEADER_SCALE

    def height(self, rows: int, separators: int = 0, class_headers: int = 0) -> float:
        return (self.pad * 2 + self.header + rows * self.row_height + max(rows - 1, 0) * self.row_gap
                + separators * self.separator + class_headers * (self.class_header + self.row_gap))

    def content_height(self, rows: tuple) -> float:
        """Height of row list (rows, separators & class headers)"""
        separators = sum(1 for row in rows if row is SEPARATOR)
        headers = sum(1 for row in rows if isinstance(row, ClassHeader))
        return self.height(len(rows) - separators - headers, separators, headers)

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
        """Draw every row of table (Row, None for empty row, SEPARATOR), first one at row index start
        (rows outside region being painted skipped)"""
        table = self.table
        top = table.pad + table.header + start * (table.row_height + table.row_gap)
        width = table.width - table.pad * 2
        index = start
        region = getattr(self, "paint_region", None)
        for row in rows:
            if row is SEPARATOR:
                top += table.separator
                continue
            if isinstance(row, ClassHeader):
                rect = QRectF(table.pad, top, width, table.class_header)
                top += table.class_header + table.row_gap
                if region is None or region.intersects(self.row_update_rect(rect.top())):
                    self.draw_class_header(painter, rect, row)
                continue
            rect = QRectF(table.pad, top, width, table.row_height)
            top += table.row_height + table.row_gap
            index += 1
            if region is not None and not region.intersects(self.row_update_rect(rect.top())):
                continue
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

    def row_slots(self: Any, rows: tuple, start: int = 0) -> dict[float, tuple]:
        """Top of each row drawn by draw_rows -> (row, row index)"""
        table = self.table
        top = table.pad + table.header + start * (table.row_height + table.row_gap)
        slots = {}
        index = start
        for row in rows:
            if row is SEPARATOR:
                top += table.separator
                continue
            if isinstance(row, ClassHeader):
                slots[top] = (row, index)
                top += table.class_header + table.row_gap
                continue
            index += 1
            slots[top] = (row, index)
            top += table.row_height + table.row_gap
        return slots

    def row_update_rect(self: Any, top: float) -> QRect:
        """Strip of widget a row is drawn in: whole width (centered text may overflow its cell), a pixel
        above & below (antialiased edges)"""
        return QRectF(0, top, self.width(), self.table.row_height).toAlignedRect().adjusted(0, -1, 0, 1)

    def cell_update_rect(self: Any, left: float, width: float, top: float) -> QRect:
        """Part of widget a text cell is drawn in: cell & 3/4 of the gap on each side (glyph overhang, antialiased
        edges of text ending on a half pixel at screen scale), a pixel around"""
        gap = self.table.col_gap * 0.75
        return QRectF(left - gap, top, width + gap * 2, self.table.row_height).toAlignedRect().adjusted(-1, -1, 1, 1)

    def changed_rects(self: Any, top: float, before: tuple | None, after: tuple) -> list[QRect]:
        """Parts of a row slot to repaint: changed cells drawn inside their cell (text, logo), else whole row"""
        if before is None or before[1] != after[1]:  # row index: background stripe
            return [self.row_update_rect(top)]
        old, new = before[0], after[0]
        if not (isinstance(old, Row) and isinstance(new, Row)) or old[1:] != new[1:] or len(old.cells) != len(new.cells):
            return [self.row_update_rect(top)]
        table = self.table
        rects = []
        for column, left, old_cell, cell in zip(table.columns, table.x, old.cells, new.cells):
            if old_cell == cell:
                continue
            if old_cell.kind not in INSIDE_CELL or cell.kind not in INSIDE_CELL:  # may overflow its cell
                return [self.row_update_rect(top)]
            rects.append(self.cell_update_rect(left, column.width, top))
        return rects

    def refresh_rows(self: Any, rows: tuple) -> bool:
        """Repaint rows that changed, moved, appeared or left, only changed cells of a row otherwise unchanged
        (whole widget before first paint or once resized)

        Returns:
            True if anything is repainted (rows changed, or logos arrived).
        """
        old = self.state
        if self.logos_arrived():  # logo cells of any row
            self.state = rows
            self.update()
            return True
        if rows == old:
            return False
        self.state = rows
        if old is None or self._static_layer is None:
            self.update()
            return True
        before, after = self.row_slots(old), self.row_slots(rows)
        rects = []
        for top, item in after.items():
            last = before.get(top)
            if last != item:
                rects.extend(self.changed_rects(top, last, item))
        rects.extend(self.row_update_rect(top) for top in before.keys() - after.keys())
        clusters = flush_clusters(rects) if self.dirty_region.pending.isNull() and self.isVisible() else None
        if clusters is None:
            self.dirty_region.update(self, rects)
        else:  # each painted & uploaded now on its own (update requests would merge into one bounding rect)
            for rect in clusters:
                self.repaint(rect)
        return True

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
        elif kind == TREND:
            self.draw_trend(painter, rect, cell.extra)
        elif kind == CHANGE:
            self.draw_change(painter, rect, cell.extra, column.align)
        elif kind == COMPOUND:
            self.draw_compounds(painter, rect, cell.extra, column.align)
        elif kind == DELTAS:
            self.draw_deltas(painter, rect, cell.extra)
        elif kind == LOGO:
            self.draw_logo(painter, rect, cell.text, cell.extra or "")
        elif kind == LAPTIME:
            self.draw_laptime(painter, rect, cell)
        elif kind == ICON:
            self.draw_icon(painter, rect, cell, column.align)
        elif kind == PAIR:
            left, right, left_width = cell.extra
            gap = self.unit * 0.3
            part = column._replace(align=CENTER)
            self.draw_cell(painter, QRectF(rect.left(), rect.top(), left_width, rect.height()),
                           part, left, row)
            self.draw_cell(painter, QRectF(rect.left() + left_width + gap, rect.top(),
                                           max(rect.width() - left_width - gap, 0.0), rect.height()), part, right, row)
        elif kind == PILL:
            if not cell.text:
                return
            box = rect.adjusted(0, rect.height() * 0.2, 0, -rect.height() * 0.2)
            rounded(painter, box, box.height() / 2 * min(self.corner, 1.0), cell.fill or theme.surface_raised)
            self.draw_text(painter, box, cell.text, "label", cell.color, CENTER, elide=False)

    def draw_class_header(self: Any, painter: QPainter, rect: QRectF, header: ClassHeader):
        """Class name on a pill of class color, then a thin line of class color to the right edge"""
        box = rect.adjusted(0, rect.height() * 0.1, 0, -rect.height() * 0.1)
        text_width = self.text_width("label", header.text)
        pill = QRectF(box.left(), box.top(), min(text_width + self.unit * 1.1, box.width()), box.height())
        rounded(painter, pill, self.radius(0.25), header.color)
        self.draw_text(painter, pill, header.text, "label", readable_on(header.color), CENTER)
        line_left = pill.right() + self.unit * 0.35
        right = box.right()
        if header.info:  # right end: info, line stops before it
            info_width = min(self.text_width("label", header.info), max(right - line_left, 0.0))
            info_box = QRectF(right - info_width, box.top(), info_width, box.height())
            self.draw_text(painter, info_box, header.info, "label", header.info_color or self.theme.text_dim, RIGHT)
            right = info_box.left() - self.unit * 0.35
        if line_left < right:
            line = QColor(header.color)
            line.setAlpha(150)
            thickness = max(self.unit * 0.08, 1.0)
            painter.fillRect(QRectF(line_left, box.center().y() - thickness / 2, right - line_left, thickness), line)

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

    def draw_laptime(self: Any, painter: QPainter, rect: QRectF, cell: Cell):
        """Time slot right aligned (lap time, delta or running time), trend arrow in space kept at right end,
        sector bars under time (fixed width: bars stay still while slot text changes)"""
        extra: LapTimeExtra = cell.extra
        theme = self.theme
        right = rect.right()
        if extra.side_width:
            size = rect.height() * CHANGE_ARROW * 0.8
            if extra.trend:
                arrow = QRectF(right - size, rect.center().y() - size / 2, size, size)
                triangle(painter, arrow, extra.trend < 0, theme.negative if extra.trend < 0 else theme.positive)
            right -= extra.side_width
        time_width = min(extra.time_width or rect.width(), right - rect.left())
        if not extra.sectors:
            self.draw_text(painter, QRectF(right - time_width, rect.top(), time_width, rect.height()), cell.text,
                           cell.role, cell.color, RIGHT, elide=False)
            return
        # Time raised, sector bars under it (as wide as the time)
        height = max(rect.height() * 0.075, 1.5)
        margin = rect.height() * 0.1
        lift = (height + margin) * 0.55
        self.draw_text(painter, QRectF(right - time_width, rect.top() - lift, time_width, rect.height()), cell.text,
                       cell.role, cell.color, RIGHT, elide=False)
        bars_width = min(extra.bars_width or time_width, time_width)
        gap = self.unit * 0.1
        width = max((bars_width - gap * 2) / 3, 1.0)
        top = rect.bottom() - height - margin
        left = right - bars_width
        track = theme.tint(theme.text_faint, 60)
        for number, (color, fill) in enumerate(extra.sectors):
            bar = QRectF(left + number * (width + gap), top, width, height)
            if color is None or fill < 1:
                rounded(painter, bar, height / 2, track)
            if color is not None and fill > 0:
                rounded(painter, QRectF(bar.left(), top, max(width * fill, height), height), height / 2, color)

    def draw_trend(self: Any, painter: QPainter, rect: QRectF, trend: tuple[float, bool] | None):
        """Gap change per lap: arrow up if gap grows, down if it shrinks, green if good for player, red if not"""
        theme = self.theme
        if trend is None:
            self.draw_text(painter, rect, DASH, "dim", theme.text_faint, CENTER)
            return
        rate, good = trend
        color = theme.positive if good else theme.negative
        size = rect.height() * CHANGE_ARROW
        arrow = QRectF(rect.left(), rect.center().y() - size / 2, size, size)
        triangle(painter, arrow, rate > 0, color)
        text_rect = QRectF(arrow.right() + size * 0.3, rect.top(), rect.width() - size * 1.3, rect.height())
        self.draw_text(painter, text_rect, f"{min(abs(rate), 9.9):.1f}", "value", color, LEFT, elide=False)

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

    def draw_compounds(self: Any, painter: QPainter, rect: QRectF, compounds: tuple, align=LEFT):
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
            left = aligned_left(rect, grid, align)
            for index, (symbol, color) in enumerate(compounds):
                row, column = divmod(index, 2)
                box = QRectF(left + column * (size + gap), top + row * (size + gap), size, size)
                rounded(painter, box, radius * 0.7, color)
                self.draw_text(painter, box, symbol, role, readable_on(color), CENTER, elide=False)
            return
        size = rect.height() * COMPOUND_SIZE
        gap = size * 0.18
        left = aligned_left(rect, size * len(compounds) + gap * (len(compounds) - 1), align)
        top = rect.center().y() - size / 2
        for symbol, color in compounds:
            box = QRectF(left, top, size, size)
            rounded(painter, box, radius, color)
            self.draw_text(painter, box, symbol, "label", readable_on(color), CENTER, elide=False)
            left += size + gap

    def draw_logo(self: Any, painter: QPainter, rect: QRectF, brand: str, vehicle: str = ""):
        """Brand logo centered in cell (own logo of brand logo folder, else game logo), brand
        initials while no logo"""
        if not brand and not vehicle:
            return
        pixmap = self.brand_logo(brand, vehicle, rect.width() - self.unit * 0.2, rect.height() * 0.74)
        if pixmap.isNull():
            initials = brand[:3]
            if initials and self.text_width("label", initials) <= rect.width():
                self.draw_text(painter, rect, initials, "label", self.theme.text_faint, CENTER)
            return
        ratio = pixmap.devicePixelRatio() or 1.0
        width = pixmap.width() / ratio
        height = pixmap.height() / ratio
        target = QRectF(rect.center().x() - width / 2, rect.center().y() - height / 2, width, height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.restore()

    def draw_icon(self: Any, painter: QPainter, rect: QRectF, cell: Cell, align):
        """Picture in a square of compound size (each file read once per size), else a dot of cell color"""
        size = min(rect.height() * COMPOUND_SIZE, rect.width())
        if size <= 0:
            return
        left = aligned_left(rect, size, align)
        box = QRectF(left, rect.center().y() - size / 2, size, size)
        pixmap = QPixmap()
        if cell.text:
            pixmaps = self.__dict__.setdefault("_icon_cache", {})
            key = (cell.text, round(size))
            pixmap = pixmaps.get(key)
            if pixmap is None:
                from ...userfile.custom_image import load_picture

                pixmap = pixmaps[key] = load_picture(cell.text, size, size, 2.0)  # sharp on high DPI screen
        if not pixmap.isNull():
            ratio = pixmap.devicePixelRatio() or 1.0
            width, height = pixmap.width() / ratio, pixmap.height() / ratio
            target = QRectF(box.center().x() - width / 2, box.center().y() - height / 2, width, height)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
            painter.restore()
        elif cell.color is not None:
            dot = size * 0.45
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(cell.color)
            painter.drawEllipse(box.center(), dot / 2, dot / 2)
            painter.restore()

    def brand_logo(self: Any, brand: str, vehicle: str, width: float, height: float) -> QPixmap:
        """Brand logo scaled to fit cell, null while none (brand initials drawn instead)

        Logo file found once per car (again once game pictures change, if none), each logo file read once
        (cars of a brand share it). On screen, file lookup & reading run on logo loader thread: null until
        ready, then table repainted (see logos_arrived). Off screen (preview, test render), done at once.
        """
        files = self.__dict__.setdefault("_logo_files", {})
        pixmaps = self.__dict__.setdefault("_logo_cache", {})
        found = files.get((brand, vehicle))
        version = game_images.images.version
        if found is None or (not found[0] and found[1] != version):
            args = (self.cfg.path.brand_logo, brand, self.theme.surface.lightness() > 128, vehicle,
                    width, height, 2.0)  # sharp on high DPI screen
            if self.isVisible():
                loader = custom_image.LOGO_LOADER
                done, value = loader.result(("brand", *args, version),
                                            lambda: custom_image.brand_logo_image(*args))
                if not done:  # initials meanwhile (no logo found before either)
                    self.__dict__["_logos_waited"] = loader.finished
                    self.watch_logos()
                    return QPixmap()
                path, image = value if value is not None else ("", None)
            else:
                path, image = custom_image.brand_logo_image(*args)
            found = files[(brand, vehicle)] = (path, version)
            if path and path not in pixmaps:
                pixmaps[path] = QPixmap.fromImage(image) if image is not None and not image.isNull() else QPixmap()
        return pixmaps.get(found[0], QPixmap()) if found[0] else QPixmap()

    def logos_arrived(self: Any) -> bool:
        """Logo waited for by last paint may be ready (logo loader finished a job since): paint again"""
        waited = self.__dict__.get("_logos_waited")
        if waited is None or waited == custom_image.LOGO_LOADER.finished:
            return False
        del self.__dict__["_logos_waited"]
        return True

    def watch_logos(self: Any):
        """Check shortly whether waited logo arrived: update timer may be stopped (paused, off track),
        rows then never refreshed (one check timer per widget, armed again while logo not ready)"""
        timer = self.__dict__.get("_logo_timer")
        if timer is None:
            timer = self.__dict__["_logo_timer"] = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(LOGO_CHECK_MS)
            widget = weakref.ref(self)  # no reference cycle through the timer's callback
            timer.timeout.connect(lambda: (table := widget()) is not None and table.check_logos())
        if not timer.isActive():
            timer.start()

    def check_logos(self: Any):
        """Repaint once waited logo is ready, else check again"""
        if self.logos_arrived():
            self.update()
        elif "_logos_waited" in self.__dict__:
            self.watch_logos()


def aligned_left(rect: QRectF, width: float, align) -> float:
    """Left of content of width in rect by column alignment"""
    if align & Qt.AlignmentFlag.AlignRight:
        return rect.right() - width
    if align & Qt.AlignmentFlag.AlignHCenter:
        return rect.center().x() - width / 2
    return rect.left()


def compounds_width(unit: float, row_scale: float, count: int) -> float:
    """Width of compound cell for count compounds"""
    size = unit * row_scale * COMPOUND_SIZE
    return size * count + size * 0.18 * max(count - 1, 0)


def change_width(unit: float, row_scale: float, digit_width: float, digits: int = 2) -> float:
    """Width of position change cell: arrow & gap, then number of places"""
    return unit * row_scale * CHANGE_ARROW * 1.3 + digit_width * digits



def _area(rect: QRect) -> int:
    return max(rect.width(), 0) * max(rect.height(), 0)


def flush_clusters(rects: list[QRect]) -> list[QRect] | None:
    """Bounding rects of far apart groups of rects to repaint one by one, None if one repaint of all costs about
    as much: a layered window uploads the bounding rect of each repaint (2 changed rows far apart: whole table
    between them), at most MAX_FLUSHES groups (each repaint has its own paint & upload cost)"""
    if len(rects) < 2:
        return None
    clusters: list[QRect] = []
    for rect in sorted(rects, key=lambda item: (item.top(), item.left())):
        if clusters:
            last = clusters[-1]
            united = last.united(rect)
            if _area(united) <= 2 * (_area(last) + _area(rect)):  # close: one repaint
                clusters[-1] = united
                continue
        clusters.append(rect)
    if not 1 < len(clusters) <= MAX_FLUSHES:
        return None
    bounding = QRect()
    for rect in clusters:
        bounding = bounding.united(rect)
    if _area(bounding) <= 2 * sum(map(_area, clusters)):
        return None
    return clusters
