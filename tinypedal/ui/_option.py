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
    QFileDialog,
    QLabel,
    QLineEdit,
    QMenu,
)

from ..const_file import FileFilter
from ..i18n import tr
from ..userfile import set_relative_path, set_user_data_path
from ..validator import image_exists, is_clock_format, is_hex_color, is_string_number

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
    for subject, unit_key, converter_name, base_unit in _UNIT_HINTS:
        if subject not in key:
            continue
        unit_name = units.get(unit_key, base_unit)
        if unit_name == base_unit:
            return ""  # already typing in the unit they read
        converter = getattr(unit_module, converter_name)(unit_name)
        return f"{converter(float(text)):.4g} {_UNIT_SUFFIX.get(unit_name, unit_name)}"
    return ""


# Misc
class OptionGroup(QLabel):
    """Option group label"""


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
    """Option QComboBox with default value & reset method"""

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


class FloatEdit(BaseLineEdit):
    """Float number option edit"""

    def validate(self):
        """Validate & export value, returns None if invalid"""
        value = self.text()
        if not is_string_number(value):
            return None
        value = float(value)
        if value % 1 == 0:  # remove unnecessary decimal points
            value = int(value)
        return value


class DropDownListEdit(BaseComboBox):
    """Drop down list option edit"""

    def validate(self):
        """Validate & export value, returns None if invalid"""
        return self.currentText()


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
        """Validate & export value, returns None if invalid"""
        # Try convert to relative path again, in case user manually sets path
        value = set_relative_path(self.text())
        if not set_user_data_path(value):
            return None
        self.setText(value)  # update reformatted path
        return value

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

    def open_dialog_image(self):
        """Open image file path dialog"""
        path_selected = QFileDialog.getOpenFileName(self, dir=self.init_value, filter=FileFilter.PNG)[0]
        if image_exists(path_selected):
            self.setText(path_selected)
            self.init_value = path_selected
