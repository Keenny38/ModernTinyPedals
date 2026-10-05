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
Display order dialog: order of widget columns or rows (display_order_* options)

Rows are dragged to reorder, or moved with their arrows (Alt+Up / Alt+Down), see OrderedPicker.
Apply writes the orders to config dialog and saves it, Ctrl+Z / Ctrl+Y undo & redo.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ..i18n import tr
from ..i18n.options import option_label
from ._common import BaseEditor, FocusRingButton, UIScaler
from .ordered_picker import OrderedPicker, PickerEntry, icon_font_family


def ordered_keys(orders: dict) -> list[str]:
    """Option keys sorted by display order value"""
    return sorted(orders, key=lambda key: orders[key])


class DisplayOrder(BaseEditor):
    """Adjust display order for widget column or row"""

    def __init__(self, parent, user_orders: dict, default_orders: dict):
        super().__init__(parent)
        self.set_config_title(tr("Display Order"), parent.windowTitle().split(" - ")[0])
        self.setMinimumSize(UIScaler.size(23), UIScaler.size(24))
        self._parent = parent
        self.temp_orders = user_orders
        self.default_orders = default_orders

        label = QLabel(tr("Drag rows to reorder, or use the arrows (Alt+Up / Alt+Down)."))
        label.setObjectName("pickerHelp")
        label.setWordWrap(True)
        entries = {
            key: PickerEntry(key, option_label(key.replace("display_order_", "")), removable=False)
            for key in default_orders
        }
        self.picker = OrderedPicker(self, entries, ordered_keys({**default_orders, **user_orders}),
                                    icon_font_family())
        self.picker.changed.connect(self.set_modified)
        self.list_widget = self.picker.shown_list
        self.enable_undo(self.picker.shown_keys, lambda keys: self.picker.set_shown(keys, notify=False))

        button_reset = FocusRingButton(tr("Reset"))
        button_reset.setToolTip(tr("Back to default order (saved with Apply)"))
        button_reset.clicked.connect(self._reset_order)
        self.button_close = FocusRingButton(tr("Close"))
        self.button_close.clicked.connect(self.close)
        button_apply = FocusRingButton(tr("Apply"))
        button_apply.setObjectName("editorPrimary")
        button_apply.setDefault(True)
        button_apply.clicked.connect(self.applying)
        layout_button = QHBoxLayout()
        layout_button.addWidget(button_reset)
        self.add_undo_buttons(layout_button)
        layout_button.addStretch(1)
        layout_button.addWidget(self.button_close)
        layout_button.addWidget(button_apply)

        layout_main = QVBoxLayout(self)
        layout_main.setSpacing(UIScaler.pixel(10))
        layout_main.addWidget(label)
        layout_main.addWidget(self.picker, stretch=1)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN * 2, self.MARGIN * 2, self.MARGIN * 2, self.MARGIN * 2)
        line = self.fontMetrics().height()
        self.resize(UIScaler.size(26), min(round(line * (2.6 * len(entries) + 8)), UIScaler.size(40)))

    def showEvent(self, event):
        """Shown as page: page has its own Close button"""
        super().showEvent(event)
        if self.in_app_page:
            self.button_close.hide()

    def applying(self):
        """Apply display order (config dialog saves it), editor kept open"""
        for row, key in enumerate(self.picker.shown_keys(), 1):
            if key in self.temp_orders or key in self.default_orders:
                self.temp_orders[key] = row
        self._parent.update_display_order(self.temp_orders)
        self._parent.applying()
        self.set_unmodified()

    def saving(self):
        """Apply when closing with unsaved changes"""
        self.applying()

    def _reset_order(self):
        """Default display order (saved with Apply)"""
        default = ordered_keys(self.default_orders)
        if self.picker.shown_keys() != default:
            self.picker.set_shown(default)
