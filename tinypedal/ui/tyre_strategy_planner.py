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
Race calculator, tyre side: tyre plan (tyre set on each wheel per stint), tyre stock & rules

Tyre tab of the race calculator page (race_calculator.py). Once the fuel strategy is ready,
plan rows follow its stints, and the tyre change time of each stop is added to that stop.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QPoint, QSignalBlocker, QStandardPaths, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..const_file import ConfigType, FileExt, FileFilter
from ..formatter import format_option_name
from ..i18n import tr, trm
from ..process.team_usage import tyre_allocation
from ..setting import cfg
from ..userfile.tyre_strategy import (
    DEFAULT_TYRE_SET,
    DEFAULT_TYRE_SETTING,
    HEADER_TYREPLAN,
    TYRE_STRATEGY_FILE_VERSION,
    create_tyre_strategy,
    decode_tyre_name,
    encode_tyre_name,
    export_tyre_strategy_file,
    extract_tyre_key,
    load_tyre_strategy_file,
    save_tyre_strategy_file,
)
from ._common import (
    QVAL_FILENAME,
    BaseEditor,
    CompactButton,
    UIScaler,
    add_vertical_separator,
    table_item,
)
from .config import UserConfig
from .game_rest import GameRequest
from .race_widgets import Card, double_box, muted_label, set_warning, spin_box
from .toast import show_toast

if TYPE_CHECKING:
    from ..fuel_strategy import Strategy


CORNER_STARTING_TREAD = (
    "front_left_starting_tread",
    "front_right_starting_tread",
    "rear_left_starting_tread",
    "rear_right_starting_tread",
)
CORNER_WEAR_PER_STINT = (
    "front_left_wear_per_stint",
    "front_right_wear_per_stint",
    "rear_left_wear_per_stint",
    "rear_right_wear_per_stint",
)
AUTOSAVE_NAME = "race_calculator_tyres"  # tyre plan kept between sessions (config folder)
MEASURED_DEFAULT = tuple(DEFAULT_TYRE_SET).index("Medium")


def average_setting(setting: dict, keys: tuple[str, ...]) -> float:
    """Average of 4 wheels of a compound setting"""
    return sum(max(setting[key], 0.0) for key in keys) / len(keys)


def set_tyre_strategy_file_path(filename: str = "") -> str:
    """Set file path"""
    filepath = cfg.user.config["tyre_strategy_planner"]["last_file_path"]
    if not filepath or not os.path.exists(filepath):
        filepath = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if not filepath.endswith("/"):
            filepath += "/"
    return f"{filepath}{filename}"


def save_tyre_strategy_file_path(filepath: str):
    """Save file path"""
    if filepath != cfg.user.config["tyre_strategy_planner"]["last_file_path"]:
        cfg.user.config["tyre_strategy_planner"]["last_file_path"] = filepath
        cfg.save(config_type=ConfigType.CONFIG)


class TyreNameListItem(QListWidgetItem):
    """Tyre name list item with custom sort order"""

    sort_type = 0

    def __init__(self, tyre_name: str):
        super().__init__(tyre_name)
        # Sort reference
        self.compound = decode_tyre_name(tyre_name)
        self.stints = 0  # number of planned stints using this tyre set
        self.stints = 0

    def __lt__(self, other):
        """Sort"""
        # Sort by number of stints
        if TyreNameListItem.sort_type:
            return self.stints > other.stints
        # Sort by compound type
        return self.compound < other.compound


class TyrePlanTable(QTableWidget):
    """Tyre plan table"""

    refresh = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self._restrict_allocation = True
        self._wheel_count = 4

    def set_drag_mode(self):
        """Set drag mode based selection"""
        if len(self.selectedIndexes()) > 1:
            self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
            return
        # Disable empty drag
        item = self.currentItem()
        if not item or not item.text():
            self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def set_allocation(self, checked: bool):
        """Set restrict tyre allocation"""
        self._restrict_allocation = checked

    def dropEvent(self, event):
        """Verify drop location & store a temp item copy"""
        item = self.itemAt(event.position().toPoint())
        if not item:
            return
        # Restrict drop inside row & column
        max_row = self.rowCount()
        row_index = item.row()
        column_index = item.column()
        if row_index >= max_row or column_index >= self._wheel_count:
            return
        # Create copy before drop
        temp_item = item.clone()
        super().dropEvent(event)
        # Remove row from invalid drop
        if max_row < self.rowCount():
            self.removeRow(max_row)
            return
        # Verify new item
        tyre_name = item.text()
        if tyre_name:
            if (same_index := self._same_row(tyre_name, row_index, column_index)) != column_index:
                self.setItem(row_index, column_index, temp_item)
                msg_text = (
                    f"<b>{tyre_name}</b> already installed on <b>{HEADER_TYREPLAN[same_index]}</b> wheel.<br><br>"
                    f"Cannot install the same tyre on two wheels at the same time."
                )
                QMessageBox.information(self, tr("Incorrect Tyre Allocation"), trm(msg_text))
            elif self._restrict_allocation and (same_index := self._same_allocation(tyre_name, row_index, column_index)) != column_index:
                self.setItem(row_index, column_index, temp_item)
                msg_text = (
                    f"<b>{tyre_name}</b> already used on <b>{HEADER_TYREPLAN[same_index]}</b> wheel.<br><br>"
                    f"Cannot allocate already used tyre on a different wheel."
                )
                QMessageBox.information(self, tr("Incorrect Tyre Allocation"), trm(msg_text))
            elif not self.cellWidget(row_index, column_index):
                self._add_stats(row_index, column_index)
        else:  # ignore emptry drop
            self.setItem(row_index, column_index, temp_item)
        # Signal update
        self.refresh.emit(True)

    def append_row(self, row_index: int = -1):
        """Add new table row"""
        self._add_row(row_index)
        # Signal update
        self.refresh.emit(True)

    def duplicate_row(self):
        """Duplicate current row (tyre column only)"""
        row_index = self.currentRow()
        column_count = self._wheel_count
        new_row_index = row_index + 1
        self._add_row(new_row_index)

        for column_index in range(column_count):
            item = self.item(row_index, column_index)
            if not item:
                continue
            tyre_name = item.text()
            if not tyre_name:
                continue
            table_item(self, new_row_index, column_index).setText(tyre_name)
            self._add_stats(new_row_index, column_index)
        # Signal update
        self.refresh.emit(True)

    def insert_above(self):
        """Insert new row at above or below current row"""
        self._add_row(self.currentRow())
        # Signal update
        self.refresh.emit(True)

    def insert_below(self):
        """Insert new row at above or below current row"""
        self._add_row(self.currentRow() + 1)
        # Signal update
        self.refresh.emit(True)

    def delete_row(self):
        """Delete selected row"""
        selected_rows = set(data.row() for data in self.selectedIndexes())
        for row_index in sorted(selected_rows, reverse=True):
            self.removeRow(row_index)
        # Signal update
        self.refresh.emit(True)

    def remove_items(self):
        """Remove selected items"""
        for item in self.selectedItems():
            row_index = item.row()
            column_index = item.column()
            self._remove_item(row_index, column_index)
        # Signal update
        self.refresh.emit(True)

    def remove_invalid(self, tyre_name_list: tuple[str, ...]):
        """Remove invalid items according to reference item list"""
        row_count = self.rowCount()
        column_count = self._wheel_count
        for row_index in range(row_count):
            for column_index in range(column_count):
                item = self.item(row_index, column_index)
                if not item:
                    continue
                tyre_name = item.text()
                if not tyre_name:
                    continue
                if tyre_name not in tyre_name_list:
                    self._remove_item(row_index, column_index)
        # Signal update
        self.refresh.emit(True)

    def export_to_list(self, column_count: int = 4) -> list[list[str]]:
        """Export data to row[column[tyre_name, ...], ...]"""
        row_list = []
        row_count = self.rowCount()
        for row_index in range(row_count):
            column_list = []
            for column_index in range(column_count):
                item = self.item(row_index, column_index)
                tyre_name = item.text() if item else ""
                column_list.append(tyre_name)
            row_list.append(column_list)
        return row_list

    def load_tyre_plan(self, user_data: list[list[str]]):
        """Load tyre plan data to table"""
        self.setRowCount(0)
        if len(user_data) < 1:
            self._add_row()
            return
        for row_index, row_data in enumerate(user_data):
            self.insertRow(row_index)
            self.setCurrentCell(row_index, 0)
            for column_index in range(self.columnCount()):
                if column_index < self._wheel_count:
                    text = row_data[column_index]
                else:
                    text = ""
                self._add_item(row_index, column_index, text)

    def load_row(self, row_index: int, tyre_names: list[str]):
        """New row at row_index with given tyres"""
        self._add_row(row_index)
        for column_index, tyre_name in enumerate(tyre_names[:self._wheel_count]):
            if tyre_name:
                table_item(self, row_index, column_index).setText(tyre_name)
                self._add_stats(row_index, column_index)

    def copy_row(self, source_row: int, row_index: int):
        """New row at row_index with tyres of source row (same tyres, no change)"""
        self._add_row(row_index)
        for column_index in range(self._wheel_count):
            item = self.item(source_row, column_index) if source_row >= 0 else None
            tyre_name = item.text() if item else ""
            if tyre_name:
                table_item(self, row_index, column_index).setText(tyre_name)
                self._add_stats(row_index, column_index)

    def set_change_time(self, row_index: int, column_index: int, seconds: float):
        """Set tyre change time"""
        item = table_item(self, row_index, column_index)
        if seconds <= 0:
            text_time = "N/A"
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        else:
            text_time = f"{seconds:+.1f}s"
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setText(text_time)

    def _add_row(self, row_index: int = -1):
        """Add new table row"""
        if row_index < 0:
            row_index = self.rowCount()
        self.insertRow(row_index)
        self.setCurrentCell(row_index, 0)
        for column_index in range(self.columnCount()):
            self._add_item(row_index, column_index, "")

    def _add_item(self, row_index: int, column_index: int, text: str):
        """Add item"""
        flag_tyre = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsDragEnabled
        flag_readonly = Qt.ItemFlag.ItemIsEnabled
        item = QTableWidgetItem()
        if column_index < self._wheel_count:
            item.setText(text)
            item.setFlags(flag_tyre)
            if text:
                self._add_stats(row_index, column_index)
        else:
            item.setFlags(flag_readonly)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row_index, column_index, item)

    def _add_stats(self, row_index: int, column_index: int):
        """Add item stats"""
        item_stats = TyrePlanItemTag(None)
        self.setCellWidget(row_index, column_index, item_stats)

    def _remove_item(self, row_index: int, column_index: int):
        """Remove one item from specific cell"""
        item = table_item(self, row_index, column_index)
        item.setText("")
        self.removeCellWidget(row_index, column_index)

    def _same_allocation(self, target_tyre_name: str, target_row: int, target_column: int) -> int:
        """Check allocation of same tyre"""
        column_index = -1
        row_count = self.rowCount()
        column_count = self._wheel_count
        for row_index in range(row_count):
            for column_index in range(column_count):
                item = self.item(row_index, column_index)
                if not item:
                    continue
                tyre_name = item.text()
                if row_index == target_row and column_index == target_column:
                    continue
                if tyre_name == target_tyre_name:
                    return column_index
        return target_column

    def _same_row(self, target_tyre_name: str, target_row: int, target_column: int) -> int:
        """Check allocation of same tyre on the same row"""
        column_index = -1
        column_count = self._wheel_count
        for column_index in range(column_count):
            item = self.item(target_row, column_index)
            if not item:
                continue
            tyre_name = item.text()
            if column_index == target_column:
                continue
            if tyre_name == target_tyre_name:
                return column_index
        return target_column


class TyreSetList(QListWidget):
    """Tyre set list"""

    def set_drag_mode(self):
        """Set drag mode based on selection"""
        if len(self.selectedIndexes()) > 1:
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def tyre_in_stock(self) -> tuple[str, ...]:
        """List all tyre name in stock"""
        return tuple(self.item(row).text() for row in range(self.count()))

    def load_tyre_stock(self, user_data: list[str]):
        """Load tyre stock to list"""
        self.clear()
        if len(user_data) < 1:
            return
        for row_data in user_data:
            self._add_item(row_data)

    def sort_by_compound(self):
        """Sort by compound type"""
        if self.count() > 1:
            TyreNameListItem.sort_type = 0
            self.sortItems(Qt.SortOrder.AscendingOrder)

    def sort_by_stints(self):
        """Sort by number of stints"""
        if self.count() > 1:
            TyreNameListItem.sort_type = 1
            self.sortItems(Qt.SortOrder.AscendingOrder)

    def add_tyre(self, tyre_key: str):
        """Add tyre"""
        tyre_name = encode_tyre_name(tyre_key, self.tyre_in_stock())
        self._add_item(tyre_name)

    def remove_tyre(self, items: list[QListWidgetItem]):
        """Remove selected tyre items"""
        for item in items:
            self.takeItem(self.row(item))

    def update_uses(self, tyre_name_list: list[str]):
        """Update number of stints for each tyre (counted in one pass)"""
        uses = Counter(tyre_name_list)
        for row in range(self.count()):
            item = cast(TyreNameListItem, self.item(row))
            count_stints = uses[item.text()]
            item.stints = count_stints
            cast(TyreSetItemTag, self.itemWidget(item)).set_uses(count_stints)

    def count_stock(self, tyre_set_data: dict) -> int:
        """Count stock tyres"""
        count = 0
        for row in range(self.count()):
            item = self.item(row)
            tyre_name = item.text()
            tyre_key = extract_tyre_key(tyre_name)
            tyre_setting = tyre_set_data.get(tyre_key, DEFAULT_TYRE_SETTING)
            if not tyre_setting["enable_limited_stock"]:
                continue
            count += 1
        return count

    def count_used(self) -> int:
        """Count used tyres"""
        count = 0
        for row in range(self.count()):
            item = cast(TyreNameListItem, self.item(row))
            if item.stints > 0:
                count += 1
        return count

    def _add_item(self, tyre_name: str):
        """Add tyre item"""
        item = TyreNameListItem(tyre_name)
        self.addItem(item)
        label_item = TyreSetItemTag(None)
        self.setItemWidget(item, label_item)


class TyreSetItemTag(QWidget):
    """Tyre set item tag"""

    def __init__(self, parent):
        super().__init__(parent)
        layout_item = QHBoxLayout()
        layout_item.setContentsMargins(0, 0, 0, 0)
        layout_item.setSpacing(0)
        layout_item.addStretch(1)

        self._label_stints = QLabel()
        layout_item.addWidget(self._label_stints)

        self.setLayout(layout_item)
        self._stints: int | None = None
        self.set_uses(0)

    def set_uses(self, stints: int):
        """Set number of stints the tyre used (style sheet & text set only when changed: tyre
        plan refreshed at every strategy calculation)"""
        if stints == self._stints:
            return
        if self._stints is None or (stints > 0) != (self._stints > 0):
            self._label_stints.setStyleSheet(f"background:{'#996633' if stints > 0 else '#777777'}")
        self._stints = stints
        self._label_stints.setText(trm(f"Stints: {stints}"))


class TyrePlanItemTag(QWidget):
    """Tyre plan item tag"""

    def __init__(self, parent):
        super().__init__(parent)
        font = self.font()
        font.setWeight(QFont.Weight.Bold)
        self.setFont(font)
        self.remaining = 0.0
        self.end = 0.0

    def set_remaining(self, percent: float, wear_per_stint: float):
        """Set remaining tyre tread (fraction)"""
        self.remaining = percent
        self.end = percent - wear_per_stint

    def paintEvent(self, event):
        percent = self.remaining
        end = self.end
        if percent > 0.9:
            color = "#00AA33"
        elif percent > 0.8:
            color = "#33AA00"
        elif percent > 0.7:
            color = "#66AA00"
        elif percent > 0.6:
            color = "#88AA00"
        elif percent > 0.5:
            color = "#AAAA00"
        elif percent > 0.4:
            color = "#AA8800"
        elif percent > 0.3:
            color = "#AA6600"
        elif percent > 0.2:
            color = "#BB3300"
        else:
            color = "#CC0000"
        painter = QPainter(self)
        width = self.width()
        height = self.height()
        painter.fillRect(int(width * (1 - percent)), int(height * 0.9), int(width * percent), height, QColor(color))
        painter.setPen(QPen(color))
        if end < 0:
            text = "Blowout"
        elif percent < 1:
            text = f"{percent * 100:.0f}-{end:.0%}"
        else:
            text = f"New-{end:.0%}"
        text_align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(0, 0, width, height, text_align, text)


class TyreStatusBar(QStatusBar):
    """Tyre usage info status bar"""

    def __init__(self, parent):
        super().__init__(parent)
        self._tyre_stock = QLabel()
        self._tyre_used = QLabel()
        self._stints = QLabel()
        self._pit_stops = QLabel()
        self._changes = QLabel()
        self._change_time = QLabel()

        self.addWidget(self._tyre_stock)
        self.addWidget(add_vertical_separator())
        self.addWidget(self._tyre_used)
        self.addWidget(add_vertical_separator())
        self.addWidget(self._stints)
        self.addWidget(add_vertical_separator())
        self.addWidget(self._pit_stops)
        self.addWidget(add_vertical_separator())
        self.addWidget(self._changes)
        self.addWidget(add_vertical_separator())
        self.addWidget(self._change_time)

    def update_info(self, tyre_used: int, tyre_max: int, tyre_stock: int, stints: int, changes: int, change_time: float):
        """Update tyre usage info"""
        stock_color = "color:#F20;" if tyre_stock > tyre_max else ""
        stock_invalid = " (invalid)" if stock_color else ""
        self._tyre_stock.setStyleSheet(stock_color)
        self._tyre_stock.setText(trm(f"Stock: {tyre_stock} / {tyre_max}{stock_invalid}"))
        self._tyre_used.setText(trm(f"Used: {tyre_used}"))
        self._stints.setText(trm(f"Stints: {stints}"))
        self._pit_stops.setText(trm(f"Pits: {max(stints - 1, 0)}"))
        self._changes.setText(trm(f"Changes: {changes}"))
        self._change_time.setText(trm(f"Time: {change_time:+.2f}s"))


class TyreRulePanel(Card):
    """Tyre rules: maximum tyres, change time by tyres changed, allocation"""

    def __init__(self, parent: TyrePlannerPanel):
        button_game = CompactButton(tr("From Game"))
        button_game.setToolTip(tr("Tyres allowed by the session in the game (LMU)"))
        button_game.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        super().__init__(parent, tr("Tyre Rules"), (button_game,))
        self.button_game = button_game
        self._max_tyre = spin_box(999, tooltip=tr("Tyres allowed for the race (limited stock compounds)"))
        self._max_tyre.setValue(4)
        self._max_tyre.valueChanged.connect(parent.update_tyre_status)
        self._game_request = GameRequest(self, ("/rest/garage/UIScreen/TireManagement",), self.received_allocation)
        self.button_game.clicked.connect(self.ask_allocation)

        self._tyre_alloc = QCheckBox(tr("Restrict Allocation"))
        self._tyre_alloc.setToolTip(tr("A used tyre stays on the same wheel"))
        self._tyre_alloc.setChecked(True)
        self._tyre_alloc.toggled.connect(parent.update_tyre_status)

        self._change_time_1 = self._add_tyre_time_spinbox(1)
        self._change_time_2 = self._add_tyre_time_spinbox(2)
        self._change_time_3 = self._add_tyre_time_spinbox(3)
        self._change_time_4 = self._add_tyre_time_spinbox(4)
        for spinbox in (self._change_time_1, self._change_time_2, self._change_time_3, self._change_time_4):
            spinbox.valueChanged.connect(parent.update_tyre_wear)

        self._highlight_new = QCheckBox(tr("Highlight New Tyre"))
        self._highlight_new.setChecked(True)
        self._highlight_new.toggled.connect(parent.update_tyre_wear)

        self.add_row(tr("Maximum Tyres"), self._max_tyre, 0)
        label = muted_label(tr("Change Time"))
        label.setToolTip(tr("Time added to the stop, by number of tyres changed"))
        self.grid.addWidget(label, 1, 0, 1, 2)
        for row, spinbox in enumerate(
                (self._change_time_1, self._change_time_2, self._change_time_3, self._change_time_4), start=2):
            self.add_row(trm(f"{row - 1} tyre(s)"), spinbox, row)
        self.grid.addWidget(self._tyre_alloc, 6, 0, 1, 2)
        self.grid.addWidget(self._highlight_new, 7, 0, 1, 2)

    def ask_allocation(self):
        """Tyre allocation of the session asked to game"""
        if self._game_request.start():
            self.button_game.setEnabled(False)

    def received_allocation(self, answers: list):
        """Tyres allowed set from game answer"""
        self.button_game.setEnabled(True)
        allocation = tyre_allocation(answers[0])
        if allocation is None:
            show_toast(self, tr("No tyre allocation from game: LMU not running or not in a session"))
            return
        self._max_tyre.setValue(allocation.maximum)
        show_toast(self, trm(f"Tyre allocation from game: {allocation.maximum} tyre(s), {allocation.new_left} new left"))

    def _add_tyre_time_spinbox(self, count: int):
        """Add tyre time spinbox"""
        return double_box(99, 1, 0.1, "s")

    def load_tyre_rule(self, user_data: dict):
        """Load tyre rule from user data"""
        self._max_tyre.setValue(user_data["maximum_tyre"])
        self._tyre_alloc.setChecked(user_data["enable_restricted_allocation"])
        self._change_time_1.setValue(user_data["tyre_change_time_1"])
        self._change_time_2.setValue(user_data["tyre_change_time_2"])
        self._change_time_3.setValue(user_data["tyre_change_time_3"])
        self._change_time_4.setValue(user_data["tyre_change_time_4"])

    def export_tyre_rule(self):
        """export tyre rule from user data"""
        return {
            "maximum_tyre": self._max_tyre.value(),
            "enable_restricted_allocation": self._tyre_alloc.isChecked(),
            "tyre_change_time_1": self._change_time_1.value(),
            "tyre_change_time_2": self._change_time_2.value(),
            "tyre_change_time_3": self._change_time_3.value(),
            "tyre_change_time_4": self._change_time_4.value(),
        }

    def max_allowed(self) -> int:
        """Max allowed tyres"""
        return self._max_tyre.value()

    def is_restrict_allocation(self) -> bool:
        """Is restrict tyre allocation"""
        return self._tyre_alloc.isChecked()

    def is_highlight_new(self) -> bool:
        """Is highlight new tyre"""
        return self._highlight_new.isChecked()

    def change_time(self) -> tuple[float, float, float, float, float]:
        """Tyre change time (seconds) list"""
        return (
            0.0,  # no change
            self._change_time_1.value(),
            self._change_time_2.value(),
            self._change_time_3.value(),
            self._change_time_4.value(),
        )


class TyreSetPanel(Card):
    """Tyre stock: compound selector, tyres available to the plan (drag to a wheel)"""

    def __init__(self, parent: TyrePlannerPanel, tyre_set_list: TyreSetList):
        super().__init__(parent, tr("Tyre Stock"))
        self.setMinimumWidth(UIScaler.size(15))

        # Button top
        self._tyre_selector = QComboBox()
        self._tyre_selector.setToolTip(tr("Compound added to stock, and of proposed tyre changes"))
        self._tyre_selector.currentIndexChanged.connect(lambda: parent.changed.emit())  # strategy wear follows

        button_addtyre = CompactButton(tr("Add"))
        button_addtyre.clicked.connect(parent.add_tyre_to_set)

        button_config = CompactButton(tr("Config"))
        button_config.setToolTip(tr("Starting tread & wear per stint of compound"))
        button_config.clicked.connect(parent.open_tyre_config_dialog)

        layout_top = QHBoxLayout()
        layout_top.addWidget(self._tyre_selector, stretch=1)
        layout_top.addWidget(button_addtyre)
        layout_top.addWidget(button_config)

        # Button low
        sort_menu = QMenu(self)

        sort_by_tyre = sort_menu.addAction(tr("Compound Type"))
        sort_by_tyre.triggered.connect(tyre_set_list.sort_by_compound)

        sort_by_uses = sort_menu.addAction(tr("Number of Stints"))
        sort_by_uses.triggered.connect(tyre_set_list.sort_by_stints)

        button_sort = CompactButton(tr("Sort By"), has_menu=True)
        button_sort.setMenu(sort_menu)

        button_remove = CompactButton(tr("Remove"))
        button_remove.clicked.connect(parent.remove_tyre_from_set)

        button_clearall = CompactButton(tr("Clear All"))
        button_clearall.clicked.connect(parent.remove_all_tyres)

        button_unused = CompactButton(tr("Remove Unused"))
        button_unused.setToolTip(tr("Remove tyres the plan does not use"))
        button_unused.clicked.connect(parent.remove_unused_tyres)

        layout_button = QVBoxLayout()  # two rows: stock card stays narrow
        layout_sort = QHBoxLayout()
        layout_sort.addWidget(button_sort)
        layout_sort.addStretch(1)
        layout_sort.addWidget(button_unused)
        layout_remove = QHBoxLayout()
        layout_remove.addStretch(1)
        layout_remove.addWidget(button_remove)
        layout_remove.addWidget(button_clearall)
        layout_button.addLayout(layout_sort)
        layout_button.addLayout(layout_remove)

        hint = muted_label(tr("Drag a tyre onto a wheel of the plan."))
        hint.setWordWrap(True)
        self.layout_card.addLayout(layout_top)
        self.layout_card.addWidget(hint)
        self.layout_card.addWidget(tyre_set_list, stretch=1)
        self.layout_card.addLayout(layout_button)

    def load_tyre_set(self, userdata: dict[str, dict], selected: str = ""):
        """Load tyre set, selected compound (else third one) shown"""
        selector = self._tyre_selector
        with QSignalBlocker(selector):  # not a compound change of the user
            selector.clear()
            selector.addItems(tuple(userdata))
            index = selector.findText(selected) if selected else -1
            selector.setCurrentIndex(index if index >= 0 else min(2, selector.count() - 1))

    def selected_tyre(self) -> str:
        """Selected tyre name"""
        return self._tyre_selector.currentText()


class TyrePlanPanel(Card):
    """Tyre plan: one row per stint (follows the fuel strategy once it is ready), file actions"""

    def __init__(self, parent: TyrePlannerPanel, tyre_plan_table: TyrePlanTable):
        self.button_propose = QPushButton(tr("Propose Changes"))
        self.button_propose.setToolTip(tr(
            "New tyres at the start and at the stops the strategy proposes (minimum tread), "
            "compound selected in tyre stock"))
        self.button_propose.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button_propose.clicked.connect(parent.propose_changes)
        super().__init__(parent, tr("Tyre Plan"), (self.button_propose,))
        self.setMinimumWidth(UIScaler.size(34))

        # Filename edit
        self._filename = QLineEdit()
        self._filename.setValidator(QVAL_FILENAME)

        # Button top
        file_menu = QMenu(self)

        new_file = file_menu.addAction(tr("New File"))
        new_file.triggered.connect(parent.create_new_file)

        file_menu.addSeparator()

        open_file = file_menu.addAction(tr("Open File"))
        open_file.triggered.connect(parent.load_from_file)

        file_menu.addSeparator()

        save_as = file_menu.addAction(tr("Save As..."))
        save_as.triggered.connect(parent.saving)

        export_csv = file_menu.addAction(tr("Export As..."))
        export_csv.triggered.connect(parent.export_as_csv)

        button_file = CompactButton(tr("File"), has_menu=True)
        button_file.setMenu(file_menu)

        button_save = CompactButton(tr("Save As"))
        button_save.clicked.connect(parent.saving)

        layout_top = self.layout_top = QHBoxLayout()
        layout_top.addWidget(button_file)
        layout_top.addWidget(self._filename, stretch=1)
        layout_top.addWidget(button_save)

        # Row buttons: manual plan only (rows follow stints once the fuel strategy is ready)
        self.row_buttons = QWidget()
        layout_button = QHBoxLayout(self.row_buttons)
        layout_button.setContentsMargins(0, 0, 0, 0)
        for text, action in (
            (tr("Duplicate Row"), parent.duplicate_row),
            (tr("New Row"), parent.add_new_row),
            (tr("Insert Below"), parent.insert_row_below),
            (tr("Insert Above"), parent.insert_row_above),
            (tr("Delete Row"), parent.delete_row),
        ):
            button = CompactButton(text)
            button.clicked.connect(action)
            layout_button.addWidget(button)
        layout_button.addStretch(1)
        self.label_linked = muted_label(tr("One row per stint of the strategy: tyre change time added to "
                                           "the stop, wear = wear per lap x stint laps (compound wear "
                                           "per stint without wear per lap)."))
        self.label_linked.setWordWrap(True)
        self.label_linked.hide()
        self.label_proposal = QLabel("")  # proposal short of tyres allowed
        self.label_proposal.setWordWrap(True)
        self.label_proposal.hide()

        self.layout_card.addLayout(layout_top)
        self.layout_card.addWidget(self.label_linked)
        self.layout_card.addWidget(self.label_proposal)
        self.layout_card.addWidget(tyre_plan_table, stretch=1)
        self.layout_card.addWidget(self.row_buttons)
        self.layout_card.addWidget(parent.tyre_status_bar)

    def set_linked(self, linked: bool):
        """Rows follow stints: manual row buttons hidden"""
        self.row_buttons.setHidden(linked)
        self.label_linked.setHidden(not linked)

    def set_filename(self, filename: str):
        """Set tyre strategy file name"""
        self._filename.setText(filename)

    def filename(self) -> str:
        """Tyre strategy file name"""
        return self._filename.text()


class TyrePlannerPanel(QWidget):
    """Tyre tab of the race calculator: tyre rules & extra cards (left), tyre plan, tyre stock

    Editor state (modified, confirmations) belongs to the race calculator page (host).
    Linked to the fuel strategy, see fuel_calculator.TyreLink.
    """

    changed = Signal()  # tyre plan edited by user: tyre change time may change the strategy

    def __init__(self, parent, host: BaseEditor):
        super().__init__(parent)
        self.host = host
        self.user_data: dict = {}
        self.linked = False  # rows follow stints of the fuel strategy
        self._syncing = False  # rows set by the strategy: not a user edit
        self._row_changes: list[int] = []  # tyres changed on each row (row 0: start)
        self._has_tyres = False  # any tyre on a wheel of the plan
        self.proposed_rows: Callable[[], list[int]] = list  # rows needing new tyres, set by host
        self.wear_per_lap: Callable[[], float] = float  # tread % per lap of the strategy, set by host
        self.minimum_tread: Callable[[], float] = float  # tread % never gone below, set by host
        self._stint_laps: list[int] = []  # laps of each stint (row) once linked
        self._stints_key: tuple | None = None  # stints, wear & rows last synced (see set_stints)
        self._spare_rows: list[list[str]] = []  # rows taken out by a shorter strategy, back when it grows
        self._proposed_names: set[str] = set()  # tyres added to stock by last proposal
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(500)
        self._autosave_timer.timeout.connect(self.autosave)

        # Compound the wear per lap was measured on: other compounds scaled by their wear
        self.combo_measured = QComboBox()
        self.combo_measured.addItems(tuple(DEFAULT_TYRE_SET))
        self.combo_measured.setToolTip(tr("Compound of measured wear per lap: wear of other compounds "
                                          "scaled by their wear per stint"))
        index = cfg.user.config["fuel_calculator"].get("input_measured_compound", MEASURED_DEFAULT)
        self.combo_measured.setCurrentIndex(index if isinstance(index, int) and
                                            0 <= index < self.combo_measured.count() else MEASURED_DEFAULT)
        self.combo_measured.currentIndexChanged.connect(self.measured_compound_changed)
        self.status_listener: Callable[..., None] | None = None  # tyre status for key figure tile

        # Tyre set list
        tyre_set = TyreSetList(self)
        tyre_set.setAlternatingRowColors(True)
        tyre_set.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        tyre_set.itemSelectionChanged.connect(tyre_set.set_drag_mode)

        tyre_set.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tyre_set.customContextMenuRequested.connect(self.open_context_menu_tyre_list)

        self.tyre_set = tyre_set

        # Tyre plan table
        tyre_plan = TyrePlanTable(self)
        tyre_plan.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tyre_plan.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        tyre_plan.setShowGrid(False)
        tyre_plan.setAlternatingRowColors(True)
        tyre_plan.setFrameShape(QFrame.Shape.NoFrame)

        tyre_plan.setColumnCount(len(HEADER_TYREPLAN))
        tyre_plan.setHorizontalHeaderLabels([tr(name) for name in HEADER_TYREPLAN])

        tyre_plan.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        tyre_plan.setColumnWidth(4, UIScaler.size(5))

        tyre_plan.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tyre_plan.customContextMenuRequested.connect(self.open_context_menu_tyre_table)

        tyre_plan.itemSelectionChanged.connect(tyre_plan.set_drag_mode)
        tyre_plan.refresh.connect(self.update_tyre_wear)

        self.tyre_plan = tyre_plan

        # Set panels
        self.tyre_status_bar = TyreStatusBar(self)
        self.tyre_status_bar.setSizeGripEnabled(False)
        self.tyre_rule_panel = TyreRulePanel(self)
        self.tyre_set_panel = TyreSetPanel(self, self.tyre_set)
        self.tyre_plan_panel = TyrePlanPanel(self, self.tyre_plan)

        # Layout: left column (cards added by host too), plan, stock
        self.layout_left = QVBoxLayout()
        self.layout_left.setContentsMargins(0, 0, 0, 0)
        self.layout_left.setSpacing(UIScaler.pixel(10))
        self.layout_left.addWidget(self.tyre_rule_panel)
        self.layout_left.addStretch(1)
        left = QWidget(self)
        left.setLayout(self.layout_left)
        left.setFixedWidth(UIScaler.size(23))
        self.layout_plan_stock = QBoxLayout(QBoxLayout.Direction.LeftToRight)  # stock below plan when narrow
        self.layout_plan_stock.setSpacing(UIScaler.pixel(10))
        self.layout_plan_stock.addWidget(self.tyre_plan_panel, stretch=3)
        self.layout_plan_stock.addWidget(self.tyre_set_panel, stretch=1)
        layout_main = QHBoxLayout(self)
        layout_main.setContentsMargins(0, 0, 0, 0)
        layout_main.setSpacing(UIScaler.pixel(10))
        layout_main.addWidget(left)
        layout_main.addLayout(self.layout_plan_stock, stretch=1)

        # Shortcut
        self._add_keyboard_shortcut()

        # Init setting & table: tyre plan of last time
        self.load_autosave()

    def set_wide(self, wide: bool):
        """Narrow page: tyre stock below tyre plan"""
        self.layout_plan_stock.setDirection(
            QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom)

    def measured_compound_changed(self, index: int):
        config = cfg.user.config["fuel_calculator"]
        if config.get("input_measured_compound") != index:
            config["input_measured_compound"] = index
            cfg.save(config_type=ConfigType.CONFIG)
        self.update_tyre_wear()
        self.changed.emit()  # strategy wear follows compound

    # Tyre plan kept between sessions
    def autosave_path(self) -> tuple[str, str]:
        return cfg.path.config, f"{AUTOSAVE_NAME}{FileExt.TYRESTRATEGY}"

    def capture_data(self) -> dict:
        """Tyre strategy data of current plan (file format)"""
        user_data = self.user_data
        user_data["file_version"] = TYRE_STRATEGY_FILE_VERSION
        user_data["tyre_rule"].update(self.tyre_rule_panel.export_tyre_rule())
        user_data["tyre_stock"] = list(self.tyre_set.tyre_in_stock())
        user_data["tyre_plan"] = self.tyre_plan.export_to_list() + [list(row) for row in self._spare_rows]
        return user_data

    def autosave(self):
        """Tyre plan saved to config folder, reopened next time"""
        filepath, filename = self.autosave_path()
        try:
            save_tyre_strategy_file(dict_user=self.capture_data(), filename=filename, filepath=filepath)
        except OSError:
            return
        config = cfg.user.config["tyre_strategy_planner"]
        if config.get("last_file_name") != self.tyre_plan_panel.filename():
            config["last_file_name"] = self.tyre_plan_panel.filename()
            cfg.save(config_type=ConfigType.CONFIG)

    def load_autosave(self):
        """Tyre plan of last time, new plan if none"""
        filepath, filename = self.autosave_path()
        user_data = load_tyre_strategy_file(filepath=filepath, filename=filename) \
            if os.path.exists(f"{filepath}{filename}") else None
        if user_data is None:
            self.create_new_file()
            return
        self.user_data = user_data
        self.tyre_plan_panel.set_filename(cfg.user.config["tyre_strategy_planner"].get("last_file_name")
                                          or tr("Untitled plan"))
        self.refresh_table()
        self.set_unmodified()

    # Undo & redo (host page)
    def capture_state(self) -> dict:
        return {
            "rule": self.tyre_rule_panel.export_tyre_rule(),
            "stock": list(self.tyre_set.tyre_in_stock()),
            "plan": self.tyre_plan.export_to_list(),
            "spare": [list(row) for row in self._spare_rows],
        }

    def restore_state(self, state: dict):
        self._stints_key = None
        self.user_data["tyre_rule"].update(state["rule"])
        self.tyre_rule_panel.load_tyre_rule(self.user_data["tyre_rule"])
        self.tyre_set.load_tyre_stock(state["stock"])
        self.tyre_plan.load_tyre_plan(state["plan"])
        self._spare_rows = [list(row) for row in state["spare"]]
        self.update_tyre_wear()
        self.changed.emit()

    def add_left_card(self, card: QWidget, position: int = -1):
        """Card of the race calculator in left column (above stretch)"""
        count = self.layout_left.count() - 1  # last item: stretch
        self.layout_left.insertWidget(count if position < 0 else position, card)

    # Editor state of host page
    def confirm_discard(self) -> bool:
        return self.host.confirm_discard()

    def confirm_operation(self, title: str = "Confirm", message: str = "") -> bool:
        return self.host.confirm_operation(title, message)

    def is_modified(self) -> bool:
        return self.host.is_modified()

    def set_modified(self):
        if not self._syncing:
            self.host.set_modified()

    def set_unmodified(self):
        self.host.set_unmodified()

    def _add_keyboard_shortcut(self):
        """Add keyboard shortcut"""
        delete_key = QShortcut(self)
        delete_key.setKey(QKeySequence(QKeySequence.StandardKey.Delete))
        delete_key.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        delete_key.activated.connect(self.remove_tyre_from_table)

    def clear_kept_rows(self):
        """Another plan loaded: rows kept aside & tyres of last proposal belong to the plan replaced"""
        self._spare_rows.clear()
        self._proposed_names.clear()

    def refresh_table(self):
        """Refresh table"""
        self._stints_key = None
        self.tyre_rule_panel.load_tyre_rule(self.user_data["tyre_rule"])
        # Compound of measured wear selected: proposals wear as measured until another is picked
        self.tyre_set_panel.load_tyre_set(self.user_data["tyre_set"], self.combo_measured.currentText())
        self.tyre_set.load_tyre_stock(self.user_data["tyre_stock"])
        self.tyre_plan.load_tyre_plan(self.user_data["tyre_plan"])
        self.update_tyre_wear()

    # Link to fuel strategy
    def compound(self, tyre_key: str) -> dict:
        return self.user_data["tyre_set"].get(tyre_key, DEFAULT_TYRE_SETTING)

    def row_wear(self, row_index: int, setting: dict, corner: int) -> float:
        """Tread used over a stint by a wheel (fraction)

        Linked to the strategy with a wear per lap (measured or entered): wear per lap x laps of
        that stint, scaled by compound (its wear per stint relative to the measured compound).
        Otherwise wear per stint of compound.
        """
        wear_per_stint = max(setting[CORNER_WEAR_PER_STINT[corner]], 0.0) * 0.01
        wear_per_lap = self.wear_per_lap()
        if self.linked and wear_per_lap > 0 and row_index < len(self._stint_laps):
            reference = average_setting(self.compound(self.combo_measured.currentText()), CORNER_WEAR_PER_STINT)
            factor = wear_per_stint * 100 / reference if reference > 0 else 1.0
            return wear_per_lap * self._stint_laps[row_index] * 0.01 * factor
        return wear_per_stint

    def has_tyres(self) -> bool:
        return self._has_tyres

    def full_change_seconds(self) -> float:
        return self.tyre_rule_panel.change_time()[4]

    def start_tread(self, default: float) -> float:
        """Tread at start: tyres of first stint (compound starting tread), else default"""
        treads = []
        for column_index in range(4):
            item = self.tyre_plan.item(0, column_index) if self.tyre_plan.rowCount() else None
            if item and item.text():
                setting = self.compound(extract_tyre_key(item.text()))
                treads.append(min(setting[CORNER_STARTING_TREAD[column_index]], 100.0))
        return sum(treads) / len(treads) if treads else default

    def fresh_tread(self) -> float:
        return min(average_setting(self.compound(self.tyre_set_panel.selected_tyre()), CORNER_STARTING_TREAD), 100.0)

    def wear_factor(self) -> float:
        """Wear of compound selected in stock relative to measured compound"""
        reference = average_setting(self.compound(self.combo_measured.currentText()), CORNER_WEAR_PER_STINT)
        selected = average_setting(self.compound(self.tyre_set_panel.selected_tyre()), CORNER_WEAR_PER_STINT)
        return selected / reference if reference > 0 and selected > 0 else 1.0

    def stop_change_times(self) -> list[float]:
        """Tyre change seconds of each stop (rows after start)"""
        times = []
        for row_index in range(1, self.tyre_plan.rowCount()):
            item = self.tyre_plan.item(row_index, 4)
            text = item.text() if item else ""
            times.append(float(text.rstrip("s")) if text.endswith("s") else 0.0)
        return times

    def stop_tyre_changes(self) -> list[int]:
        """Tyres changed at each stop, empty list if no tyre planned"""
        if not self._has_tyres:
            return []
        return self._row_changes[1:]

    def set_stints(self, strategy: Strategy):
        """One row per stint of a ready strategy: added rows keep the tyres of the stint before

        Same stints & wear as last time: nothing to change (strategy calculated again for
        another input, or tyre plan rounds of a calculation).
        """
        linked = strategy.ready
        table = self.tyre_plan
        key = (tuple(strategy.stints) if linked else (), linked, self.wear_per_lap(), table.rowCount())
        if key == self._stints_key:
            return
        self._syncing = True
        try:
            self._stint_laps = list(strategy.stints) if linked else []
            if linked:
                count = len(strategy.stints)
                while table.rowCount() > count:  # kept aside (not lost), back when stints grow
                    self._spare_rows.insert(0, table.export_to_list()[-1])
                    table.removeRow(table.rowCount() - 1)
                while table.rowCount() < count:
                    if self._spare_rows:
                        table.load_row(table.rowCount(), self._spare_rows.pop(0))
                    else:
                        table.copy_row(table.rowCount() - 1, table.rowCount())
                first = 1
                labels = []
                for index, laps in enumerate(strategy.stints, start=1):
                    labels.append(f"{index}  ({first}-{first + laps - 1})")
                    first += laps
                table.setVerticalHeaderLabels(labels)
            elif self.linked:
                table.setVerticalHeaderLabels([str(row + 1) for row in range(table.rowCount())])
            if linked != self.linked:
                self.linked = linked
                self.tyre_plan_panel.set_linked(linked)
            self.update_tyre_wear()
        finally:
            self._syncing = False
        self._stints_key = (tuple(strategy.stints) if linked else (), linked, self.wear_per_lap(), table.rowCount())
        self._autosave_timer.start()

    def propose_changes(self):
        """New tyres (compound selected in stock) on each wheel at the stint it would go below the
        minimum tread, within tyres allowed: short of tyres, the best worn tyre that wheel used
        before (restricted allocation) or any wheel used is fitted again, else tyres are kept"""
        table = self.tyre_plan
        compound = self.tyre_set_panel.selected_tyre()
        if not compound:
            QMessageBox.warning(self, tr("Error"), tr("Invalid tyre name."))
            return
        if self._has_tyres and not self.confirm_operation(
                message=tr("<b>Replace tyre plan with proposed changes?</b>")):
            return
        setting = self.compound(compound)
        for row_index in range(table.rowCount()):
            for column_index in range(4):
                table._remove_item(row_index, column_index)
        self._spare_rows.clear()
        # Tyres a previous proposal added, now unused: removed, so proposing again adds no stock
        self.tyre_set.remove_tyre([
            self.tyre_set.item(row) for row in range(self.tyre_set.count())
            if self.tyre_set.item(row).text() in self._proposed_names
        ])
        self._proposed_names.clear()
        stock = self.tyre_set.tyre_in_stock()
        if setting["enable_limited_stock"]:
            others = sum(
                1 for name in stock
                if extract_tyre_key(name) != compound and self.compound(extract_tyre_key(name))["enable_limited_stock"])
            allowed = max(self.tyre_rule_panel.max_allowed() - others, 0)
        else:
            allowed = len(stock) + table.rowCount() * 4  # no limit
        free = [name for name in stock if extract_tyre_key(name) == compound]
        restricted = self.tyre_rule_panel.is_restrict_allocation()
        removed: list[list[tuple[str, float]]] = [[] for _ in range(4)]  # tyres taken off, per wheel
        minimum = self.minimum_tread() * 0.01
        current = ["", "", "", ""]
        tread = [0.0, 0.0, 0.0, 0.0]
        fitted = 0
        short_rows: list[int] = []
        for row_index in range(table.rowCount()):
            for corner in range(4):
                wear = self.row_wear(row_index, setting, corner)
                if current[corner] and tread[corner] - wear >= minimum - 1e-9:
                    pass  # tyre lasts this stint
                elif fitted < allowed:
                    if free:
                        name = free.pop(0)
                    else:
                        name = encode_tyre_name(compound, self.tyre_set.tyre_in_stock())
                        self.tyre_set.add_tyre(compound)
                        self._proposed_names.add(name)
                    fitted += 1
                    if current[corner]:
                        removed[corner].append((current[corner], tread[corner]))
                    current[corner] = name
                    tread[corner] = min(setting[CORNER_STARTING_TREAD[corner]], 100.0) * 0.01
                else:
                    pool = removed[corner] if restricted else [tyre for wheel in removed for tyre in wheel]
                    best = max(pool, key=lambda tyre: tyre[1], default=None)
                    if best is not None and best[1] > tread[corner]:
                        for wheel in removed:
                            if best in wheel:
                                wheel.remove(best)
                        if current[corner]:
                            removed[corner].append((current[corner], tread[corner]))
                        current[corner], tread[corner] = best
                    if tread[corner] - wear < minimum - 1e-9 and row_index + 1 not in short_rows:
                        short_rows.append(row_index + 1)
                if current[corner]:
                    table_item(table, row_index, corner).setText(current[corner])
                    table._add_stats(row_index, corner)
                tread[corner] -= wear
        label = self.tyre_plan_panel.label_proposal
        label.setText(trm(f"Not enough tyres allowed: worn tyres kept at stint {', '.join(map(str, short_rows))}")
                      if short_rows else "")
        label.setHidden(not short_rows)
        set_warning(label, bool(short_rows))
        table.refresh.emit(True)

    def remove_unused_tyres(self):
        """Remove tyres of stock the plan does not use"""
        unused = [item for item in (self.tyre_set.item(row) for row in range(self.tyre_set.count()))
                  if not cast(TyreNameListItem, item).stints]
        if not unused:
            return
        self.tyre_set.remove_tyre(unused)
        self._proposed_names.difference_update(item.text() for item in unused)
        self.update_tyre_status()

    # File create, load, save, export
    def create_new_file(self):
        """Create new file"""
        if not self.confirm_discard():
            return
        self.tyre_plan_panel.set_filename(tr("Untitled plan"))
        self.user_data = create_tyre_strategy()
        self.clear_kept_rows()
        self.refresh_table()
        self.set_unmodified()
        self.changed.emit()

    def load_from_file(self):
        """Load tyre strategy from file"""
        if not self.confirm_discard():
            return
        filename_full, _ = QFileDialog.getOpenFileName(
            self,
            dir=set_tyre_strategy_file_path(),
            filter=FileFilter.TYRESTRATEGY,
        )
        if not filename_full:
            return
        filepath = os.path.dirname(filename_full) + "/"
        filename = os.path.basename(filename_full)
        user_data = load_tyre_strategy_file(
            filepath=filepath,
            filename=filename,
        )
        if user_data is None:
            msg_text = "Cannot open selected file.<br><br>Invalid tyre strategy file."
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return
        self.user_data = user_data
        self.clear_kept_rows()
        # Update file name
        save_tyre_strategy_file_path(filepath)
        self.tyre_plan_panel.set_filename(os.path.splitext(filename)[0])
        self.refresh_table()
        self.set_unmodified()
        self.changed.emit()

    def saving(self):
        """Save tyre strategy file"""
        filename = self.tyre_plan_panel.filename()
        if not filename:
            QMessageBox.warning(self, tr("Error"), tr("Invalid file name."))
            return
        filename_full, _ = QFileDialog.getSaveFileName(
            self,
            dir=set_tyre_strategy_file_path(filename),
            filter=FileFilter.TYRESTRATEGY,
        )
        if not filename_full:  # save canceled
            return
        # Prepare data
        user_data = self.user_data
        user_data["file_version"] = TYRE_STRATEGY_FILE_VERSION
        user_data["tyre_rule"].update(self.tyre_rule_panel.export_tyre_rule())
        user_data["tyre_stock"] = self.tyre_set.tyre_in_stock()
        user_data["tyre_plan"] = self.tyre_plan.export_to_list()
        # Save data
        filepath = os.path.dirname(filename_full) + "/"
        filename = os.path.basename(filename_full)
        save_tyre_strategy_file(
            dict_user=user_data,
            filename=filename,
            filepath=filepath,
        )
        # Update file name
        save_tyre_strategy_file_path(filepath)
        self.tyre_plan_panel.set_filename(os.path.splitext(filename)[0])
        self.set_unmodified()
        msg_text = f"Tyre strategy file saved at:<br><b>{filename_full}</b>"
        show_toast(self, trm(msg_text))

    def export_as_csv(self):
        """Export tyre strategy as spreadsheet (CSV)"""
        filename = self.tyre_plan_panel.filename()
        if not filename:
            QMessageBox.warning(self, tr("Error"), tr("Invalid file name."))
            return
        filename_full, _ = QFileDialog.getSaveFileName(
            self,
            dir=set_tyre_strategy_file_path(filename),
            filter=FileFilter.CSV,
        )
        if not filename_full:  # save canceled
            return
        # Tyre rule
        tyre_rule = self.tyre_rule_panel.export_tyre_rule()
        tyre_rule_data = [
            [format_option_name(name) for name in tyre_rule],
            list(tyre_rule.values()),
        ]
        # Tyre stock list
        tyre_set = self.tyre_set
        tyre_stock_data: list[list[str | int]] = [["Tyre Stock", "Stints"]]
        for row in range(tyre_set.count()):
            item = cast(TyreNameListItem, tyre_set.item(row))
            tyre_stock_data.append([item.text(), item.stints])
        # Tyre plan table
        tyre_plan_header = ["Stint"]
        for index, name in enumerate(HEADER_TYREPLAN):
            tyre_plan_header.append(name)
            if index < 4:
                tyre_plan_header.append("Tread (%)")
        tyre_plan = self.tyre_plan
        tyre_plan_data: list[list] = [tyre_plan_header]
        row_count = tyre_plan.rowCount()
        column_count = tyre_plan.columnCount()
        for row_index in range(row_count):
            column_list: list = [row_index + 1]
            for column_index in range(column_count):
                cell = tyre_plan.item(row_index, column_index)
                if cell:
                    tyre_name = cell.text()
                else:
                    tyre_name = ""
                column_list.append(tyre_name)
                if column_index < 4:
                    item_tag = cast(TyrePlanItemTag | None, tyre_plan.cellWidget(row_index, column_index))
                    if item_tag:
                        tyre_remaining = f"{item_tag.remaining * 100:.2f} - {max(item_tag.end, 0.0) * 100:.2f}"
                    else:
                        tyre_remaining = "0.0"
                    column_list.append(tyre_remaining)
            tyre_plan_data.append(column_list)
        # Save data
        filepath = os.path.dirname(filename_full) + "/"
        filename = os.path.basename(filename_full)
        export_tyre_strategy_file(
            rule_data=tyre_rule_data,
            stock_data=tyre_stock_data,
            plan_data=tyre_plan_data,
            filename=filename,
            filepath=filepath,
        )
        save_tyre_strategy_file_path(filepath)
        msg_text = f"Tyre strategy file exported at:<br><b>{filename_full}</b>"
        show_toast(self, trm(msg_text))

    # Context menu
    def open_context_menu_tyre_list(self, position: QPoint):
        """Open context menu - tyre list"""
        tyre_list = self.tyre_set
        if not tyre_list.itemAt(position):
            return
        menu = QMenu()
        remove_from_set = menu.addAction(tr("Remove Selected"))
        selected_action = menu.exec(tyre_list.mapToGlobal(position))
        if not selected_action:
            return
        if selected_action == remove_from_set:
            self.remove_tyre_from_set()

    def open_context_menu_tyre_table(self, position: QPoint):
        """Open context menu - tyre plan table"""
        table = self.tyre_plan
        if not table.itemAt(position):
            return
        menu = QMenu()
        remove_from_table = menu.addAction(tr("Remove Selected"))
        duplicate_row = menu.addAction(tr("Duplicate Row"))
        menu.addSeparator()
        insert_above = menu.addAction(tr("Insert Row Above"))
        insert_below = menu.addAction(tr("Insert Row Below"))
        menu.addSeparator()
        delete_row = menu.addAction(tr("Delete Row"))
        position += QPoint(table.verticalHeader().width(), table.horizontalHeader().height())
        selected_action = menu.exec(table.mapToGlobal(position))
        if not selected_action:
            return
        if selected_action == duplicate_row:
            self.duplicate_row()
        elif selected_action == insert_above:
            self.insert_row_above()
        elif selected_action == insert_below:
            self.insert_row_below()
        elif selected_action == delete_row:
            self.delete_row()
        elif selected_action == remove_from_table:
            self.remove_tyre_from_table()

    # Update tyre table, list, status
    def update_tyre_status(self):
        """Update tyre status info, strategy told about user edits (tyre change time)"""
        self.set_modified()
        if not self._syncing:
            self.changed.emit()
            self._autosave_timer.start()
        self.tyre_plan.set_allocation(self.tyre_rule_panel.is_restrict_allocation())
        tyre_used = self.tyre_set.count_used()
        tyre_max = self.tyre_rule_panel.max_allowed()
        tyre_stock = self.tyre_set.count_stock(self.user_data["tyre_set"])
        stints = self.tyre_plan.rowCount()
        # Sum of tyre change time
        total_changes = 0
        total_change_time = 0.0
        for row_index in range(1, self.tyre_plan.rowCount()):
            item = self.tyre_plan.item(row_index, 4)
            if not item:
                continue
            text = item.text()
            if not text.endswith("s"):
                continue
            total_change_time += float(text.rstrip("s"))
            total_changes += 1
        # Update
        self.tyre_status_bar.update_info(
            tyre_used=tyre_used,
            tyre_max=tyre_max,
            tyre_stock=tyre_stock,
            stints=stints,
            changes=total_changes,
            change_time=total_change_time,
        )
        if self.status_listener is not None:
            self.status_listener(tyre_used, tyre_max, tyre_stock, total_changes, total_change_time)

    @Slot(bool)  # type: ignore[operator]
    def update_tyre_wear(self):
        """Update tyre wear"""
        table = self.tyre_plan
        tyre_change_time = self.tyre_rule_panel.change_time()
        is_highlight_new = self.tyre_rule_panel.is_highlight_new()
        tyre_set_data = self.user_data["tyre_set"]
        tyre_name_list = []
        uses: Counter[str] = Counter()  # stints run so far by each tyre
        worn: dict[str, float] = {}  # tread used so far by each tyre (fraction)
        row_count = table.rowCount()
        column_count = 4
        self._row_changes = []
        for row_index in range(row_count):
            count_changed = 0
            for column_index in range(column_count):
                item = table.item(row_index, column_index)
                if not item:
                    continue
                tyre_name = item.text()
                if not tyre_name:
                    continue
                # Count changed tyres
                item_above = table.item(max(row_index - 1, 0), column_index)
                if not item_above or item_above.text() != tyre_name:
                    count_changed += 1
                # Count used tyres
                tyre_name_list.append(tyre_name)
                uses[tyre_name] += 1
                # Get unique tyre key name
                tyre_key = extract_tyre_key(tyre_name)
                if not tyre_key:
                    continue
                # Calculate wear
                tyre_item = cast(TyrePlanItemTag | None, table.cellWidget(row_index, column_index))
                if not tyre_item:
                    continue
                tyre_setting = tyre_set_data.get(tyre_key, DEFAULT_TYRE_SETTING)
                starting_tread = min(tyre_setting[CORNER_STARTING_TREAD[column_index]], 100.0) * 0.01
                count_stints = uses[tyre_name] - 1
                highlight = (not is_highlight_new or count_stints < 1)
                item.setForeground(Qt.BrushStyle.NoBrush if highlight else QBrush(Qt.GlobalColor.darkGray))
                wear = self.row_wear(row_index, tyre_setting, column_index)
                used = worn.get(tyre_name, 0.0)
                tyre_item.set_remaining(starting_tread - used, wear)
                worn[tyre_name] = used + wear
            # Calculate tyre change time
            table.set_change_time(row_index, column_count, tyre_change_time[count_changed])
            self._row_changes.append(count_changed)

        self._has_tyres = bool(tyre_name_list)
        self.tyre_set.update_uses(tyre_name_list)
        self.update_tyre_status()

    # Tyre list actions
    def open_tyre_config_dialog(self):
        """Open tyre config dialog"""
        tyre_name = self.tyre_set_panel.selected_tyre()
        _dialog = UserConfig(
            self,
            key_name=tyre_name,
            preset_name="Tyre Compound",
            config_type="",
            user_setting=self.user_data["tyre_set"],
            default_setting=DEFAULT_TYRE_SET,
            reload_func=self.update_tyre_wear,
        )
        _dialog.open()

    def add_tyre_to_set(self):
        """Add tyre to tyre set list"""
        tyre_key = self.tyre_set_panel.selected_tyre()
        if not tyre_key:
            QMessageBox.warning(self, tr("Error"), tr("Invalid tyre name."))
            return
        self.tyre_set.add_tyre(tyre_key)
        self.update_tyre_status()

    def remove_tyre_from_set(self):
        """Remove tyre from tyre set list and table"""
        items = self.tyre_set.selectedItems()
        if not items:
            QMessageBox.warning(self, tr("Error"), tr("No tyre selected."))
            return False
        msg_text = (
            "<b>Remove selected tyre from list?</b><br><br>"
            "Corresponding tyre will be removed from table."
        )
        if self.confirm_operation(message=msg_text):
            self.tyre_set.remove_tyre(items)
            self.tyre_plan.remove_invalid(self.tyre_set.tyre_in_stock())

    def remove_all_tyres(self):
        """Remove all tyres from tyre set list and table"""
        msg_text = (
            "<b>Remove all tyres from list?</b><br><br>"
            "All allocated tyres will be removed from table."
        )
        if self.confirm_operation(message=msg_text):
            self.tyre_set.clear()
            self.tyre_plan.remove_invalid(())

    # Tyre table actions
    def remove_tyre_from_table(self):
        """Remove selected tyres from table"""
        if not self.tyre_plan.hasFocus() or not self.tyre_plan.selectedIndexes():
            return
        if self.confirm_operation(message=tr("<b>Remove selected tyre from table?</b>")):
            self.tyre_plan.remove_items()

    def add_new_row(self):
        """Add new row"""
        self.tyre_plan.append_row()

    def insert_row_above(self):
        """Insert row above"""
        self.tyre_plan.insert_above()

    def insert_row_below(self):
        """Insert row below"""
        self.tyre_plan.insert_below()

    def duplicate_row(self):
        """Duplicate row"""
        if not self.tyre_plan.selectedIndexes():
            QMessageBox.warning(self, tr("Error"), tr("No data selected."))
            return
        self.tyre_plan.duplicate_row()

    def delete_row(self):
        """Delete row"""
        if not self.tyre_plan.selectedIndexes():
            QMessageBox.warning(self, tr("Error"), tr("No data selected."))
            return
        if self.confirm_operation(message=tr("<b>Delete selected row?</b>")):
            self.tyre_plan.delete_row()
