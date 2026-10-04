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
Race calculator, shared widgets: cards, key figure tiles, number boxes, result labels

Styled in ui/__init__.py (RaceCalculator section).
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ._common import UIScaler

INVALID_COLOR = "#F40"  # invalid lap & values out of range (tank too small, tyres worn out)
TYRE_COLOR = "#F5B342"  # tyre change marks


def set_warning(label: QLabel, warning: bool):
    """Warning color on a result (style sheet: RaceCalculator QLabel[warning="true"])"""
    if label.property("warning") == warning:
        return
    label.setProperty("warning", warning)
    label.style().unpolish(label)
    label.style().polish(label)


def setup_number_box(box: QSpinBox | QDoubleSpinBox, suffix: str, tooltip: str = ""):
    """Spin box shared setup: no arrows, unit inside, decimal point as in results & history"""
    locale = QLocale(QLocale.Language.C)
    locale.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator)
    box.setLocale(locale)
    box.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    # Typing: value applied on Enter or leaving the box, not at every key (a half typed value
    # would recalculate the strategy, and reshape the tyre plan, for nothing)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(f" {suffix}")
    if tooltip:
        box.setToolTip(tooltip)


class SpinBox(QSpinBox):
    """Wheel changes value only once focused, so scrolling the page never edits it"""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class DoubleSpinBox(QDoubleSpinBox):
    """Wheel changes value only once focused, so scrolling the page never edits it"""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


def spin_box(maximum: int, suffix: str = "", minimum: int = 0, tooltip: str = "") -> QSpinBox:
    box = SpinBox()
    box.setRange(minimum, maximum)
    setup_number_box(box, suffix, tooltip)
    return box


def double_box(maximum: float, decimals: int, step: float, suffix: str = "", tooltip: str = "") -> QDoubleSpinBox:
    box = DoubleSpinBox()
    box.setRange(0, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    setup_number_box(box, suffix, tooltip)
    return box


def value_label(text: str = "-") -> QLabel:
    """Result value, right aligned, selectable"""
    label = QLabel(text)
    label.setObjectName("fuelValue")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setEnabled(False)  # muted color
    return label


def laps_text(laps: int) -> str:
    return f"{laps} {tr('lap') if laps < 2 else tr('laps')}"


class Card(QFrame):
    """Rounded panel with a title (and optional header widgets), content added to its grid"""

    def __init__(self, parent, title: str, buttons: Sequence[QWidget] = ()):
        super().__init__(parent)
        self.setObjectName("fuelCard")
        layout = QVBoxLayout(self)
        margin = UIScaler.pixel(10)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(UIScaler.pixel(6))
        self.label_title = QLabel(title)
        self.label_title.setObjectName("fuelCardTitle")
        layout_title = QHBoxLayout()
        layout_title.addWidget(self.label_title, stretch=1)
        for button in buttons:
            layout_title.addWidget(button)
        layout.addLayout(layout_title)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(UIScaler.pixel(8))
        self.grid.setVerticalSpacing(UIScaler.pixel(4))
        layout.addLayout(self.grid)
        self.layout_card = layout

    def add_row(self, title: str, editor: QWidget, row: int, column: int = 0, tooltip: str = "") -> QLabel:
        """Label & editor side by side, several pairs per row allowed"""
        label = QLabel(title)
        if tooltip:
            label.setToolTip(tooltip)
            editor.setToolTip(editor.toolTip() or tooltip)
        self.grid.addWidget(label, row, column * 2)
        self.grid.addWidget(editor, row, column * 2 + 1)
        self.grid.setColumnStretch(column * 2 + 1, 1)
        return label


class KpiTile(QFrame):
    """Key figure: title, big value, detail line"""

    def __init__(self, parent, title: str, tooltip: str = ""):
        super().__init__(parent)
        self.setObjectName("fuelTile")
        self.label_title = muted_label(title)
        self.label_value = QLabel("-")
        self.label_value.setObjectName("fuelTileValue")
        self.label_detail = muted_label("")
        self.label_detail.setWordWrap(True)  # narrow tile: detail on two lines
        layout = QVBoxLayout(self)
        margin = UIScaler.pixel(10)
        layout.setContentsMargins(margin, UIScaler.pixel(8), margin, UIScaler.pixel(8))
        layout.setSpacing(0)
        layout.addWidget(self.label_title)
        layout.addWidget(self.label_value)
        layout.addWidget(self.label_detail)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)  # row of same height
        if tooltip:
            self.setToolTip(tooltip)

    def set_text(self, value: str, detail: str = "", warning: bool = False, title: str = ""):
        if title:
            self.label_title.setText(title)
        self.label_value.setText(value)
        self.label_detail.setText(detail)
        set_warning(self.label_value, warning)
