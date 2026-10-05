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
Common
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, TypeVar, overload

import shiboken6
from PySide6.QtCore import QObject, QRegularExpression, Qt, QTimer
from PySide6.QtGui import (
    QDoubleValidator,
    QIntValidator,
    QKeySequence,
    QRegularExpressionValidator,
    QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..const_app import APP_NAME
from ..i18n import tr, trm
from ..setting import cfg
from ..userfile.json_setting import copy_setting
from ..validator import is_string_number
from . import UIScaler

# Validator
QVAL_INTEGER = QIntValidator(-999999, 999999)
QVAL_FLOAT = QDoubleValidator(-999999.9999, 999999.9999, 6)
QVAL_COLOR = QRegularExpressionValidator(QRegularExpression('^#[0-9a-fA-F]*'))
QVAL_HEATMAP = QRegularExpressionValidator(QRegularExpression('[0-9a-zA-Z_]*'))
QVAL_FILENAME = QRegularExpressionValidator(QRegularExpression('[^\\\\/:*?"<>|]*'))


def run_after_saving(callback: Callable[[], object], interval: int = 10):
    """Run callback once saving is finished, without blocking GUI thread

    Callback of a widget deleted meanwhile (page rebuilt on language change) is skipped.
    """
    if cfg.is_saving:
        QTimer.singleShot(interval, lambda: run_after_saving(callback, interval))
        return
    owner = getattr(callback, "__self__", None)
    if isinstance(owner, QObject) and not shiboken6.isValid(owner):
        return
    callback()


def add_vertical_separator() -> QFrame:
    """Add vertical separator"""
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.VLine)
    separator.setFrameShadow(QFrame.Shadow.Sunken)
    return separator


def singleton_dialog(dialog_type: str, show_error: bool = True):
    """Singleton dialog decorator"""

    def decorator(dialog_class: type[BaseDialog]):

        def unset_dialog_state(pointer):
            DialogSingleton.remove(dialog_type)

        def wrapper(*args, **kwargs):
            parent = kwargs.get("parent", args[0] if args else None)
            if page_host(parent, dialog_class) is not None:
                # Shown as page in app: one page per dialog, opening the same one shows its page again
                return dialog_class(*args, **kwargs)
            if DialogSingleton.new(dialog_type):
                instance = dialog_class(*args, **kwargs)
                instance.destroyed.connect(unset_dialog_state)
                return instance
            return DialogSingletonError(dialog_type, show_error)

        return wrapper

    return decorator


class DialogSingleton:
    """Singleton dialog"""

    _instance_type: set[str] = set()

    def __init__(self):
        raise TypeError("not for instantiate")

    @classmethod
    def is_opened(cls, dialog_type: str) -> bool:
        """Is dialog open"""
        return dialog_type in cls._instance_type

    @classmethod
    def new(cls, dialog_type: str) -> bool:
        """Append new dialog type if not exist"""
        if dialog_type not in cls._instance_type:
            cls._instance_type.add(dialog_type)
            return True
        return False

    @classmethod
    def remove(cls, dialog_type: str):
        """Remove dialog type"""
        cls._instance_type.remove(dialog_type)


class DialogSingletonError:
    """Error dialog for singleton"""

    def __init__(self, dialog_type: str, show_error: bool = True):
        self._dialog_type = dialog_type
        self._show_error = show_error

    def _message(self, parent=None):
        """Error for qdialog"""
        if not self._show_error:
            return
        msg_text = (
            f"Already opened <b>{self._dialog_type.title()} dialog</b>."
            "<br><br>Please close previous dialog first."
        )
        QMessageBox.warning(parent, tr("Error"), trm(msg_text))

    def open(self, parent=None):
        self._message(parent)

    def show(self, parent=None):
        self._message(parent)

    def exec(self, parent=None):
        self._message(parent)


class CompactButton(QPushButton):
    """Compact button style"""

    def __init__(self, text, parent=None, has_menu=False):
        super().__init__(text, parent)
        self.setFixedWidth(
            self.fontMetrics().boundingRect(text).width()
            + UIScaler.FONT_PIXEL_SCALED * (1 + has_menu)
        )


def find_dialog_host(widget: QWidget | None):
    """Main window page host (shows dialogs as pages inside app), None if no main window"""
    if widget is None:
        return None
    central = getattr(widget.window(), "centralWidget", None)
    host = central() if callable(central) else None
    return host if hasattr(host, "show_dialog_page") else None


def page_host(parent, dialog_class: type):
    """Page host for dialog class opened from parent, None if dialog stays a separate window

    Dialogs opened from another dialog (offset, rename, file info...) stay small popups over it.
    """
    if not getattr(dialog_class, "EMBED_IN_APP", False) or not isinstance(parent, QWidget):
        return None
    ancestor: QWidget | None = parent
    while ancestor is not None:
        if isinstance(ancestor, QDialog):
            # Opened from a dialog page: page too if class allows it (text input), else popup over it
            if getattr(ancestor, "in_app_page", False) and getattr(dialog_class, "EMBED_FROM_PAGE", False):
                break
            return None
        ancestor = ancestor.parentWidget()
    return find_dialog_host(parent)


def embedded_host(dialog: QDialog):
    """Page host of dialog, None if already shown as page or staying a separate window"""
    if getattr(dialog, "in_app_page", False):
        return None
    return page_host(dialog.parentWidget(), type(dialog))


# Dialog class
class BaseDialog(QDialog):
    """Base dialog class

    Opened with show() or open() from main window, dialog is shown as a page inside app
    (see TabView.show_dialog_page), unless EMBED_IN_APP is False. exec() keeps a modal window.
    """
    MARGIN = UIScaler.pixel(6)
    EMBED_IN_APP = True
    in_app_page = False  # set when shown as page

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    def show(self):
        host = embedded_host(self)
        if host is not None and not self.isVisible() and host.show_dialog_page(self):
            return
        super().show()

    def open(self):
        host = embedded_host(self)
        if host is not None and not self.isVisible() and host.show_dialog_page(self):
            return
        super().open()

    def set_config_title(self, option_name: str, preset_name: str):
        """Set config dialog title"""
        if preset_name:
            title = f"{option_name} - {preset_name}"
        else:
            title = option_name
        self.setWindowTitle(title)

    def set_utility_title(self, name: str):
        """Set utility dialog title"""
        self.setWindowTitle(f"{name} - {APP_NAME}")

    def confirm_operation(self, title: str = "Confirm", message: str = "") -> bool:
        """Confirm operation"""
        confirm = QMessageBox.question(
            self, tr(title), trm(message),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No,
        )
        return confirm == QMessageBox.StandardButton.Yes


class BaseEditor(BaseDialog):
    """Base editor class"""

    MAX_UNDO = 100

    def __init__(self, parent):
        super().__init__(parent)
        self._is_modified = False
        # Undo & redo history (snapshot based), see enable_undo()
        self._undo_capture: Callable[[], object] | None = None
        self._undo_restore: Callable[[object], None] | None = None
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._undo_state: object = None
        self._undo_busy = False

    def enable_undo(self, capture: Callable[[], Any], restore: Callable[[Any], None]):
        """Enable undo & redo (Ctrl+Z, Ctrl+Y)

        Args:
            capture: return copy of current editor data (called after each change).
            restore: rebuild editor from a copy of editor data.
        """
        self._undo_capture = capture
        self._undo_restore = restore
        self._undo_state = self.__capture_state()
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self, self.undo)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Redo), self, self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)

    def enable_table_undo(self, temp_name: str, update_temp: Callable[[], None], refresh_table: Callable[[], None]):
        """Enable undo & redo for editor that syncs table with a temp dict

        Args:
            temp_name: attribute name of temp dict (ex. "brakes_temp").
            update_temp: function that updates temp dict from table.
            refresh_table: function that rebuilds table from temp dict.
        """
        def capture():
            update_temp()
            return copy_setting(getattr(self, temp_name))

        def restore(state):
            temp = getattr(self, temp_name)
            temp.clear()
            temp.update(copy_setting(state))
            refresh_table()

        self.enable_undo(capture, restore)

    def add_undo_buttons(self, layout: QHBoxLayout):
        """Add undo & redo buttons to layout"""
        button_undo = CompactButton(tr("Undo"))
        button_undo.setToolTip(tr("Undo (Ctrl+Z)"))
        button_undo.clicked.connect(self.undo)
        button_redo = CompactButton(tr("Redo"))
        button_redo.setToolTip(tr("Redo (Ctrl+Y)"))
        button_redo.clicked.connect(self.redo)
        layout.addWidget(button_undo)
        layout.addWidget(button_redo)

    def __capture_state(self) -> object:
        """Capture editor state, None if editor is being rebuilt"""
        if self._undo_capture is None:
            return None
        try:
            return self._undo_capture()
        except (AttributeError, LookupError, TypeError, ValueError):  # table partially filled
            return None

    def __record_change(self):
        """Record change to undo history"""
        if self._undo_capture is None or self._undo_busy:
            return
        new_state = self.__capture_state()
        if new_state is None or new_state == self._undo_state:
            return
        if self._undo_state is not None:
            self._undo_stack.append(self._undo_state)
            del self._undo_stack[:-self.MAX_UNDO]
        self._undo_state = new_state
        self._redo_stack.clear()

    def __apply_state(self, state: object):
        """Restore editor state without recording history"""
        if self._undo_restore is None:
            return
        self._undo_busy = True
        try:
            self._undo_restore(state)
        finally:
            self._undo_busy = False
        self._undo_state = state
        self._is_modified = True

    def replace_table_data(self, refresh_table: Callable[[], None]):
        """Rebuild table from replaced temp data (reset, import), recorded as one undo step

        Cell changes while rebuilding are not recorded, as recording reads the partially
        filled table back into temp data that the rebuild is reading from.
        """
        self._undo_busy = True
        try:
            refresh_table()
        finally:
            self._undo_busy = False
        self.set_modified()

    def reset_undo(self):
        """Clear undo history, use current state as start point"""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._undo_state = self.__capture_state()

    def undo(self):
        """Undo last change"""
        self.__record_change()  # include pending change not yet recorded
        if self._undo_stack:
            self._redo_stack.append(self._undo_state)
            self.__apply_state(self._undo_stack.pop())

    def redo(self):
        """Redo last undone change"""
        if self._redo_stack:
            self._undo_stack.append(self._undo_state)
            self.__apply_state(self._redo_stack.pop())

    def confirm_discard(self) -> bool:
        """Confirm save or discard changes"""
        if not self._is_modified:
            return True

        confirm = QMessageBox.question(
            self, tr("Confirm"), tr("<b>Save changes before continue?</b>"),
            buttons=QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)

        if confirm == QMessageBox.StandardButton.Save:
            self.saving()
            return self.confirm_discard()

        return confirm == QMessageBox.StandardButton.Discard

    def is_modified(self) -> bool:
        """Is modified"""
        return self._is_modified

    def set_modified(self):
        """Set modified state"""
        if not self._is_modified:
            self._is_modified = True
        self.__record_change()

    def record_change(self):
        """Record change to undo history, editor not marked modified (changes saved at once)"""
        self.__record_change()

    def set_unmodified(self):
        """Set unmodified state"""
        if self._is_modified:
            self._is_modified = False

    def saving(self):
        """Save changes"""

    def reject(self):
        """Reject(ESC) confirm"""
        self.close()

    def closeEvent(self, event):
        """Close editor"""
        if not self.confirm_discard():
            event.ignore()

    @staticmethod
    def new_name_increment(name: str, table: QTableWidget, column: int = 0) -> str:
        """New name with number increment add at the end"""
        new_index = 1
        new_name = f"{name} {new_index}"
        exist = True
        while exist:  # check existing name
            items = table.findItems(new_name, Qt.MatchFlag.MatchExactly)
            for item in items:
                if item.column() == column:  # match column
                    new_index += 1
                    new_name = f"{name} {new_index}"
                    break
            else:
                exist = False
        return new_name

    @staticmethod
    def is_value_in_table(target: str, table: QTableWidget, column: int = 0) -> bool:
        """Is there any matching value in table"""
        items = table.findItems(target, Qt.MatchFlag.MatchExactly)
        return any(item.column() == column for item in items)

    @staticmethod
    def reloading(reload_module: bool = True, reload_widget: bool = True) -> None:
        """Reloading module & widget only"""
        # Delay import
        from ..module_control import mctrl, wctrl

        if reload_module:
            mctrl.reload()
        if reload_widget:
            wctrl.reload()


class TextInputDialog(BaseDialog):
    """Text input shown as page in app (replaces QInputDialog), on_accept(text) returns True to close

    Opened from a dialog page, it is a page too (back to that page when closed).
    """

    EMBED_FROM_PAGE = True

    def __init__(
        self, parent, title: str, label: str, on_accept: Callable[[str], bool], text: str = "",
        multiline: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._on_accept = on_accept
        label_text = QLabel(label, self)
        label_text.setWordWrap(True)
        label_text.setTextFormat(Qt.TextFormat.RichText)
        self.edit: QLineEdit | QPlainTextEdit
        if multiline:
            self.edit = QPlainTextEdit(self)
            self.edit.setPlainText(text)
        else:
            self.edit = QLineEdit(self)
            self.edit.setText(text)
            self.edit.selectAll()
            self.edit.returnPressed.connect(self.accepting)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accepting)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(label_text)
        layout.addWidget(self.edit, stretch=1 if multiline else 0)
        if not multiline:
            layout.addStretch(1)
        layout.addWidget(buttons)
        layout.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setMinimumWidth(UIScaler.size(24))

    def text(self) -> str:
        if isinstance(self.edit, QPlainTextEdit):
            return self.edit.toPlainText()
        return self.edit.text()

    def accepting(self):
        if self._on_accept(self.text()):
            self.accept()


class BatchOffset(BaseDialog):
    """Batch offset"""

    def __init__(self, parent, offset_func: Callable):
        super().__init__(parent)
        self.setWindowTitle(tr("Batch Offset"))
        self.decimals = 0
        self.value_range = 0, 1
        self.offset_func = offset_func
        self.edit_offset = QDoubleSpinBox()
        self.last_offset = QLabel("0")
        self.last_label = QLabel(tr("Last Offset:"))
        self.checkbox_scale = QCheckBox(tr("Scale Mode"))

    def config(self, decimals: int, step: float, min_range: int, max_range: int):
        """Config offset"""
        self.decimals = decimals
        self.value_range = min_range, max_range

        # Label
        layout_label = QHBoxLayout()
        layout_label.addWidget(self.last_label)
        layout_label.addStretch(1)
        layout_label.addWidget(self.last_offset)

        # Edit offset
        self.edit_offset.setDecimals(self.decimals)
        self.edit_offset.setRange(*self.value_range)
        self.edit_offset.setSingleStep(step)
        self.edit_offset.setAlignment(Qt.AlignmentFlag.AlignRight)

        # Scale mode
        self.checkbox_scale.setChecked(False)
        self.checkbox_scale.toggled.connect(self.toggle_mode)

        # Button
        button_apply = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply)
        button_apply.clicked.connect(self.applying)

        button_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_close.rejected.connect(self.reject)

        layout_button = QHBoxLayout()
        layout_button.addWidget(button_apply)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        # Set layout
        layout_main = QVBoxLayout()
        layout_main.addLayout(layout_label)
        layout_main.addWidget(self.edit_offset)
        layout_main.addWidget(self.checkbox_scale)
        layout_main.addLayout(layout_button)
        self.setLayout(layout_main)
        self.setFixedSize(UIScaler.size(12), self.sizeHint().height())

    def toggle_mode(self, checked: bool):
        """Toggle mode"""
        self.last_offset.setText("0")
        if checked:
            self.edit_offset.setRange(0, 100)
            self.edit_offset.setDecimals(6)
            self.last_label.setText(tr("Last Scale:"))
        else:
            self.edit_offset.setRange(*self.value_range)
            self.edit_offset.setDecimals(self.decimals)
            self.last_label.setText(tr("Last Offset:"))

    def applying(self):
        """Apply offset"""
        value = self.edit_offset.value()
        if value != 0:
            self.offset_func(value, self.checkbox_scale.isChecked())
            offset_text = f"{value:.{self.edit_offset.decimals()}f}"
            self.last_offset.setText(offset_text.rstrip("0").rstrip("."))
            self.edit_offset.setValue(0)


class TableBatchReplace(BaseDialog):
    """Table batch replace"""

    def __init__(
        self, parent, table_selector: dict, table_data: QTableWidget):
        """
        Args:
            table_selector: table selector dictionary. key=column name, value=column index.
        """
        super().__init__(parent)
        self.table_selector = table_selector
        self.table_data = table_data
        self.setWindowTitle(tr("Batch Replace"))

        # Label & combobox
        self.search_selector = QComboBox()
        self.search_selector.setEditable(True)
        self.search_selector.setCompleter(QCompleter())  # disable auto-complete

        self.column_selector = QComboBox()
        self.column_selector.addItems(tuple(self.table_selector))
        self.column_selector.currentIndexChanged.connect(self.update_selector)
        self.update_selector(self.table_selector[self.column_selector.currentText()])

        self.replace_entry = QLineEdit()

        self.checkbox_casematch = QCheckBox(tr("Match Case"))
        self.checkbox_casematch.setChecked(False)
        self.checkbox_exactmatch = QCheckBox(tr("Match Whole Word"))
        self.checkbox_exactmatch.setChecked(False)

        layout_option = QGridLayout()
        layout_option.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout_option.addWidget(QLabel(tr("Column:")), 0, 0)
        layout_option.addWidget(QLabel(tr("Find:")), 1, 0)
        layout_option.addWidget(QLabel(tr("Replace:")), 2, 0)
        layout_option.addWidget(self.column_selector, 0, 1)
        layout_option.addWidget(self.search_selector, 1, 1)
        layout_option.addWidget(self.replace_entry, 2, 1)
        layout_option.addWidget(self.checkbox_exactmatch, 3, 1)
        layout_option.addWidget(self.checkbox_casematch, 4, 1)

        # Button
        button_replace = QPushButton(tr("Replace"))
        button_replace.clicked.connect(self.replacing)

        button_close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_close.rejected.connect(self.reject)

        layout_button = QHBoxLayout()
        layout_button.addWidget(button_replace)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        # Set layout
        layout_main = QVBoxLayout()
        layout_main.addLayout(layout_option)
        layout_main.addLayout(layout_button)
        self.setLayout(layout_main)
        self.setMinimumWidth(UIScaler.size(22))
        self.setFixedHeight(self.sizeHint().height())

    def update_selector(self, column_index: int, last_search: str = ""):
        """Update selector list"""
        column_index = self.table_selector[self.column_selector.currentText()]
        self.search_selector.clear()
        selector_list = set(
            table_item(self.table_data, row_index, column_index).text()
            for row_index in range(self.table_data.rowCount())
        )
        self.search_selector.addItems(sorted(selector_list))
        self.search_selector.setCurrentText(last_search)

    def replacing(self):
        """Replace"""
        if not self.search_selector.currentText():
            QMessageBox.warning(self, tr("Error"), tr("Invalid name."))
            return

        column_index = self.table_selector[self.column_selector.currentText()]
        search = self.search_selector.currentText()
        replace = self.replace_entry.text()

        pattern = re.escape(search)  # escape special chars
        if self.checkbox_exactmatch.isChecked():
            pattern = f"^{pattern}$"

        if self.checkbox_casematch.isChecked():
            match_flag = 0
        else:
            match_flag = re.IGNORECASE

        for row_index in range(self.table_data.rowCount()):
            item = table_item(self.table_data, row_index, column_index)
            item.setText(re.sub(pattern, replace, item.text(), flags=match_flag))

        self.update_selector(column_index, search)


# Table item access
TableItemT = TypeVar("TableItemT", bound=QTableWidgetItem)


@overload
def table_item(table: QTableWidget, row: int, column: int) -> QTableWidgetItem: ...
@overload
def table_item(table: QTableWidget, row: int, column: int, item_type: type[TableItemT]) -> TableItemT: ...
def table_item(table: QTableWidget, row: int, column: int, item_type: type = QTableWidgetItem):
    """Get table cell item, raise LookupError if cell is empty or has unexpected item type

    All editor tables populate every cell on refresh, so a missing item is a programming error
    (or an invalid row index such as -1 from currentRow() with no selection).
    """
    item = table.item(row, column)
    if not isinstance(item, item_type):
        raise LookupError(f"no {item_type.__name__} at row {row}, column {column}")
    return item


# Table item class
class FloatTableItem(QTableWidgetItem):
    """Float type QTableWidgetItem with validation"""

    def __init__(self, value: float):
        """Convert & set float value to string"""
        super().__init__()
        self._value = 0.0
        self.setValue(value)

    def setValue(self, value: float):
        """Set value"""
        self._value = value
        self.setText(str(value))

    def value(self) -> float:
        """Get value"""
        return self._value

    def validate(self):
        """Validate value, replace invalid value with old value if invalid"""
        value = self.text()
        if is_string_number(value):
            self._value = float(value)
        else:
            self.setText(str(self._value))

    def __lt__(self, other):
        """Sort by value"""
        return self.value() < other.value()


class NumericTableItem(QTableWidgetItem):
    """Numeric QTableWidgetItem with sortable text"""

    def __init__(self, value: float, text: str):
        """Set numeric value & string text"""
        super().__init__()
        self.value = value
        self.setText(text)

    def __lt__(self, other):
        """Sort by value"""
        return self.value < other.value


class ClockTableItem(QTableWidgetItem):
    """Clock type QTableWidgetItem with validation"""

    def __init__(self, value: str):
        super().__init__()
        self._value = ""
        self.setText(value)

    def value(self) -> str:
        """Get value"""
        return self._value

    def validate(self):
        """Validate value, replace invalid value with old value if invalid"""
        value = self.__verify(self.text())
        if value:
            self._value = value
        self.setText(self._value)

    def __lt__(self, other):
        """Sort by value"""
        return self.value() < other.value()

    def __verify(self, clock_time: str) -> str:
        """Validate clock time (Hour:Minute) string"""
        try:
            data = clock_time.split(":")
            if len(data) != 2:
                raise ValueError
            hours = min(max(int(data[0]), 0), 24)
            minutes = min(max(int(data[1]), 0), 60)
            if minutes >= 60:
                hours += 1
                minutes = 0
            if hours >= 24:
                hours = 24
                minutes = 0
            return f"{hours:02d}:{minutes:02d}"
        except (AttributeError, IndexError, ValueError, TypeError):
            return ""
