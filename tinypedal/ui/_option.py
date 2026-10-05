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
Option edit widget
"""

from __future__ import annotations

import os
from collections import deque
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, qGray
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..const_file import FileFilter
from ..i18n import tr
from ..template.widget.black_box_ui import (
    PRESSURE_TARGET_PREFIX,
    format_compound_targets,
    parse_compound_targets,
    pressure_target_kpa,
)
from ..userfile import set_relative_path, set_user_data_path
from ..validator import image_exists, is_clock_format, is_hex_color, is_string_number
from ._common import translate_filter

# Numeric options are stored in a fixed base unit (kPa, Celsius, meters per second, liters),
# never in whatever unit the overlay displays, so that changing the display unit cannot
# silently reinterpret a saved threshold. That leaves the user typing 160 for a pressure they
# read as 23.2 psi, so the editor shows the same value in their display unit as a live hint.
# Only temperature and pressure are listed: those two have one base unit across the whole
# project. Speed options do not (some are stored in km/h, some in m/s), so a hint for them
# would be wrong as often as right.
_UNIT_HINTS = (
    # matched in order, first match wins: "temperature" before "pressure" so that
    # hot_pressure_temperature_threshold is read as a temperature
    ("temperature", "temperature_unit", "set_unit_temperature", "Celsius"),
    ("pressure", "tyre_pressure_unit", "set_unit_pressure", "kPa"),
)
_UNIT_SUFFIX = {"Fahrenheit": "°F", "Celsius": "°C"}


def unit_hint(key: str, text: str, units: Mapping[str, str]) -> str:
    """Same value in the user's display unit, "" when the option carries no unit

    Args:
        key: option key name.
        text: current editor text.
        units: the Units section of the settings.
    """
    from .. import units as unit_module

    if not is_string_number(text):
        return ""
    value = float(text)
    for subject, unit_key, converter_name, base_unit in _UNIT_HINTS:
        if subject not in key:
            continue
        unit_name = units.get(unit_key, base_unit)
        if key.startswith(PRESSURE_TARGET_PREFIX):  # typed in kPa, psi or bar, see pressure_target_kpa
            value_kpa = pressure_target_kpa(value)
            if unit_name == base_unit:
                return "" if value_kpa == value else f"{value_kpa:.4g} kPa"
            value = value_kpa
        elif unit_name == base_unit:
            return ""  # already typing in the unit they read
        converter = getattr(unit_module, converter_name)(unit_name)
        return f"{converter(value):.4g} {_UNIT_SUFFIX.get(unit_name, unit_name)}"
    return ""


# Misc
class OptionGroup(QLabel):
    """Option group label"""


class OptionSection(QLabel):
    """Option section label, above option groups"""


# Base option edit class
class BaseLineEdit(QLineEdit):
    """QLineEdit with default value & reset method"""

    def __init__(self, parent):
        super().__init__(parent)
        self._default = None

    def set_default(self, default: Any):
        """Set default value (once) & create reset-context-menu"""
        if self._default is None:
            self._default = default
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._reset_menu)

    def default(self) -> Any:
        """Return default value"""
        return self._default

    def reset_to_default(self):
        """Reset to default value"""
        if self._default is not None:
            self.setText(str(self._default))

    def _reset_menu(self, position: QPoint):
        """Context menu for reset option to default value"""
        if self._default is not None:
            menu = QMenu()  # no parent for temp menu
            option_reset = menu.addAction(tr("Reset to Default"))
            action = menu.exec(self.mapToGlobal(position))
            if action == option_reset:
                self.reset_to_default()

    def validate(self) -> Any:
        """Validate & export value, returns None if invalid"""
        return self.text()

    def invalid_reason(self) -> str:
        """Short reason why text is invalid (English, translated by caller), "" if valid

        Checked while typing (see UserConfig), so editors validated with side effects
        (folder created) return "" and are checked when saving only.
        """
        return "" if self.validate() is not None else "Invalid value"


class BaseCheckBox(QCheckBox):
    """Option QCheckBox with default value & reset method"""

    def __init__(self, parent):
        super().__init__(parent)
        self._default = None

    def set_default(self, default: Any):
        """Set default value (once) & create reset-context-menu"""
        if self._default is None:
            self._default = default
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._reset_menu)

    def default(self) -> Any:
        """Return default value"""
        return self._default

    def reset_to_default(self):
        """Reset to default value"""
        if self._default is not None:
            self.setChecked(self._default)

    def _reset_menu(self, position: QPoint):
        """Context menu for reset option to default value"""
        if self._default is not None:
            menu = QMenu()  # no parent for temp menu
            option_reset = menu.addAction(tr("Reset to Default"))
            action = menu.exec(self.mapToGlobal(position))
            if action == option_reset:
                self.reset_to_default()


class BaseComboBox(QComboBox):
    """Option QComboBox with default value & reset method

    Choices added by add_choices show translated text, English value kept as item data
    (saved value, see value), and setCurrentText selects by value first.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self._default = None

    def add_choices(self, items, translate: bool = True):
        """Add choices, shown translated (value kept as item data)"""
        for item in items:
            text = str(item)
            self.addItem(tr(text) if translate else text, text)

    def value(self) -> str:
        """Value of selected choice (English), text if added without value"""
        data = self.currentData()
        return data if isinstance(data, str) else self.currentText()

    def setCurrentText(self, text: str):
        """Select choice by value (English), else by shown text"""
        index = self.findData(text)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            super().setCurrentText(text)

    def set_default(self, default: Any):
        """Set default value (once) & create reset-context-menu"""
        if self._default is None:
            self._default = default
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._reset_menu)

    def default(self) -> Any:
        """Return default value"""
        return self._default

    def reset_to_default(self):
        """Reset to default value"""
        if self._default is not None:
            self.setCurrentText(str(self._default))

    def _reset_menu(self, position: QPoint):
        """Context menu for reset option to default value"""
        if self._default is not None:
            menu = QMenu()  # no parent for temp menu
            option_reset = menu.addAction(tr("Reset to Default"))
            action = menu.exec(self.mapToGlobal(position))
            if action == option_reset:
                self.reset_to_default()


# Specific option edit widget
class BooleanEdit(BaseCheckBox):
    """Boolean option edit"""

    def validate(self):
        """Validate & export value, returns None if invalid"""
        return self.isChecked()


class StringEdit(BaseLineEdit):
    """String option edit"""

    def validate(self):
        """Validate & export value, returns None if invalid"""
        return self.text()


class ClockFormatEdit(BaseLineEdit):
    """Clock format option edit"""

    def validate(self):
        """Validate & export value, returns None if invalid"""
        value = self.text()
        if not is_clock_format(value):
            return None
        return value

    def invalid_reason(self) -> str:
        return "" if self.validate() is not None else "Invalid clock format"


class IntegerEdit(BaseLineEdit):
    """Integer number option edit"""

    def validate(self):
        """Validate & export value, returns None if invalid"""
        value = self.text()
        if not is_string_number(value):  # accepts decimals, which int() cannot parse
            return None
        try:
            return int(value)
        except ValueError:  # decimal typed in an integer option, report as invalid
            return None

    def invalid_reason(self) -> str:
        if self.validate() is not None:
            return ""
        if is_string_number(self.text()):
            return "Whole number required"
        return "Number required"


class FloatEdit(BaseLineEdit):
    """Float number option edit"""

    def validate(self):
        """Validate & export value, returns None if invalid"""
        text = self.text()
        if not is_string_number(text):
            return None
        value = float(text)
        if value % 1 == 0:  # remove unnecessary decimal points
            return int(value)
        return value

    def invalid_reason(self) -> str:
        return "" if self.validate() is not None else "Number required"


class DropDownListEdit(BaseComboBox):
    """Drop down list option edit"""

    def validate(self):
        """Validate & export value, returns None if invalid"""
        return self.value()


class ColorEdit(BaseLineEdit):
    """Color option edit with double click dialog trigger"""

    HISTORY: deque[QColor] = deque(
        [QColor("#FFF")] * QColorDialog.customCount(),
        maxlen=QColorDialog.customCount()
    )

    def __init__(self, parent, init: str):
        super().__init__(parent)
        self.init_value = init
        self.textChanged.connect(self._preview_color)

    def mouseDoubleClickEvent(self, event):
        """Double click to open dialog"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.open_dialog_color()

    def validate(self):
        """Validate & export value, returns None if invalid"""
        value = self.text()
        if not is_hex_color(value):
            return None
        return value

    def invalid_reason(self) -> str:
        return "" if self.validate() is not None else "Color as #RRGGBB or #AARRGGBB"

    def open_dialog_color(self):
        """Open color dialog"""
        color_dialog = QColorDialog()
        # Load color history to custom color slot
        for index, old_color in enumerate(ColorEdit.HISTORY):
            color_dialog.setCustomColor(index, QColor(old_color))
        # Open color selector dialog
        color_get = color_dialog.getColor(
            initial=QColor(self.init_value),
            options=QColorDialog.ColorDialogOption.ShowAlphaChannel
        )
        if color_get.isValid():
            # Add new color to color history
            if ColorEdit.HISTORY[0] != color_get:
                ColorEdit.HISTORY.appendleft(color_get)
            # Set output format
            if color_get.alpha() == 255:  # without alpha value
                color = color_get.name(QColor.NameFormat.HexRgb).upper()
            else:  # with alpha value
                color = color_get.name(QColor.NameFormat.HexArgb).upper()
            # Update edit box and init value
            self.setText(color)
            self.init_value = color

    def _preview_color(self):
        """Update edit preview color"""
        color_str = self.text()
        if is_hex_color(color_str):
            # Set foreground color based on background color lightness
            qcolor = QColor(color_str)
            if qcolor.alpha() > 128 > qGray(qcolor.rgb()):
                fg_color = "#FFF"
            else:
                fg_color = "#000"
            # Apply style
            self.setStyleSheet(f"QLineEdit {{color:{fg_color};background:{color_str};}}")


class CompoundTargetEdit(StringEdit):
    """Tyre targets per compound, as text, with double click table editor"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setToolTip(tr("Double click to edit as a table"))

    def mouseDoubleClickEvent(self, event):
        """Double click to open table editor"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.open_dialog_table()

    def open_dialog_table(self):
        dialog = CompoundTargetDialog(self, self.text())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.setText(dialog.result_text())


class CompoundTargetDialog(QDialog):
    """Table of tyre targets: compound, pressure range (kPa), optional temperature range (Celsius)"""

    COLUMNS = ("Compound", "Pressure Min (kPa)", "Pressure Max (kPa)", "Temp Min (°C)", "Temp Max (°C)")

    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle(tr("Tyre Targets by Compound"))
        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels([tr(name) for name in self.COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for symbol, values in parse_compound_targets(text).items():
            self.add_row((symbol, *values))

        button_add = QPushButton(tr("Add"))
        button_add.clicked.connect(lambda: self.add_row(("", 160, 190, None, None)))
        button_remove = QPushButton(tr("Remove Selected"))
        button_remove.clicked.connect(self.remove_rows)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout_button = QHBoxLayout()
        layout_button.addWidget(button_add)
        layout_button.addWidget(button_remove)
        layout_button.addStretch(1)
        layout_button.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Compound symbol (see Tyre Compound Editor) or full name. "
                                   "Temperature range is optional.")))
        layout.addWidget(self.table)
        layout.addLayout(layout_button)

    def add_row(self, values):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate(values):
            text = "" if value is None else (f"{value:g}" if isinstance(value, float) else str(value))
            self.table.setItem(row, column, QTableWidgetItem(text))

    def remove_rows(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def cell(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item else ""

    def result_text(self) -> str:
        """Table back to option text, incomplete rows dropped"""
        targets = {}
        for row in range(self.table.rowCount()):
            symbol = self.cell(row, 0)
            try:
                p_min, p_max = float(self.cell(row, 1)), float(self.cell(row, 2))
            except ValueError:
                continue
            t_min: float | None
            t_max: float | None
            try:
                t_min, t_max = float(self.cell(row, 3)), float(self.cell(row, 4))
            except ValueError:
                t_min = t_max = None
            if symbol:
                targets[symbol.upper()] = (p_min, p_max, t_min, t_max)
        return format_compound_targets(targets)


class FilePathEdit(BaseLineEdit):
    """File path option edit with double click dialog trigger"""

    def __init__(self, parent, init: str):
        super().__init__(parent)
        self.init_value = init

    def mouseDoubleClickEvent(self, event):
        """Double click to open dialog"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.open_dialog_path()

    def validate(self):
        """Validate & export value, returns None if invalid (empty, or drive root)"""
        if not self.text().strip():  # would point data folder to drive root
            return None
        # Try convert to relative path again, in case user manually sets path
        value = set_relative_path(self.text())
        full_path = os.path.abspath(value)
        if os.path.dirname(full_path) == full_path:  # drive or file system root
            return None
        if not set_user_data_path(value):
            return None
        self.setText(value)  # update reformatted path
        return value

    def invalid_reason(self) -> str:
        """Checked when saving only: validating creates the folder"""
        return ""

    def open_dialog_path(self):
        """Open file path dialog"""
        path_selected = QFileDialog.getExistingDirectory(self, dir=self.init_value)
        if os.path.exists(path_selected):
            # Convert to relative path if in APP root folder
            path_valid = set_relative_path(path_selected)
            # Update edit box and init value
            self.setText(path_valid)
            self.init_value = path_valid


class ImagePathEdit(BaseLineEdit):
    """Image path option edit with double click dialog trigger"""

    def __init__(self, parent, init: str):
        super().__init__(parent)
        self.init_value = init

    def mouseDoubleClickEvent(self, event):
        """Double click to open dialog"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.open_dialog_image()

    def validate(self):
        """Validate & export value, returns None if invalid"""
        value = self.text()
        if value and not os.path.exists(value):
            return None
        return value

    def invalid_reason(self) -> str:
        return "" if self.validate() is not None else "File not found"

    def open_dialog_image(self):
        """Open image file path dialog"""
        path_selected = QFileDialog.getOpenFileName(self, dir=self.init_value, filter=translate_filter(FileFilter.PNG))[0]
        if image_exists(path_selected):
            self.setText(path_selected)
            self.init_value = path_selected
