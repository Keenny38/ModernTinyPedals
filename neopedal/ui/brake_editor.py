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
Brake editor
"""

import logging
from typing import cast

from PySide6.QtWidgets import (
    QComboBox,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..api_control import api
from ..const_file import ConfigType
from ..i18n import tr, trm
from ..setting import cfg, copy_setting
from ..userfile.heatmap import HEATMAP_DEFAULT_BRAKE, set_predefined_brake_name
from ._common import (
    BaseEditor,
    FloatTableItem,
    UIScaler,
    #TableBatchReplace,
    column_texts,
    run_after_saving,
    table_item,
)

HEADER_BRAKES = "Brake name","Failure (mm)","Heatmap name"

logger = logging.getLogger(__name__)


class BrakeEditor(BaseEditor):
    """Brake editor"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Brake Editor"))
        self.setMinimumSize(UIScaler.size(45), UIScaler.size(38))

        self.brakes_temp = copy_setting(cfg.user.brakes)

        # Set table
        self.table_brakes = self.editor_table(HEADER_BRAKES, {1: 7, 2: 12})  # thickness & heatmap columns
        self.table_brakes.cellChanged.connect(self.verify_input)
        self.refresh_table()
        self.enable_table_undo("brakes_temp", self.update_brakes_temp, self.refresh_table)
        self.set_unmodified()

        # Set button
        layout_button = self.set_layout_button()

        # Set layout
        layout_main = QVBoxLayout()
        layout_main.addWidget(self.table_brakes)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)

    def set_layout_button(self):
        """Set button layout"""
        return self.editor_buttons(
            (("Add", self.add_brake), ("Sort", self.sort_brake), ("Delete", self.delete_brake)),
            self.reset_setting, self.applying)

    def refresh_table(self):
        """Refresh brakes list"""
        self.table_brakes.setRowCount(0)
        row_index = 0
        for class_name, brake_data in self.brakes_temp.items():
            self.add_brake_entry(
                row_index,
                class_name,
                brake_data["failure_thickness"],
                brake_data["heatmap"],
            )
            row_index += 1

    def __add_option_combolist(self, key):
        """Combo droplist string"""
        combo_edit = QComboBox()
        combo_edit.addItems(tuple(cfg.user.heatmap))
        combo_edit.setCurrentText(key)
        combo_edit.currentTextChanged.connect(self.set_modified)
        return combo_edit

    #def open_replace_dialog(self):
    #    """Open replace dialog"""
    #    selector = {tr(HEADER_BRAKES[0]): 0}
    #    _dialog = TableBatchReplace(self, selector, self.table_brakes)
    #    _dialog.open()

    def add_brake(self):
        """Add new brake"""
        start_index = row_index = self.table_brakes.rowCount()
        listed = column_texts(self.table_brakes, 0)
        with self.batch_edit():  # one undo step
            # Add all missing vehicle name from active session
            veh_total = api.read.vehicle.total_vehicles()
            for index in range(veh_total):
                class_name = api.read.vehicle.class_name(index)
                vehicle_name = api.read.vehicle.vehicle_name(index)
                brake_names = (
                    set_predefined_brake_name(class_name, vehicle_name, True),
                    set_predefined_brake_name(class_name, vehicle_name, False),
                )
                for brake in brake_names:
                    if brake not in listed:
                        self.add_brake_entry(row_index, brake, 0)
                        listed.add(brake)
                        row_index += 1
            if start_index != row_index:
                self.table_brakes.setCurrentCell(row_index - 1, 0)  # last added
            # Add new name entry
            else:
                new_class_name = self.new_name_increment("New Brake Name", self.table_brakes)
                self.add_brake_entry(row_index, new_class_name, 0)
                self.table_brakes.setCurrentCell(row_index, 0)

    def add_brake_entry(
        self, row_index: int, class_name: str, failure_thickness: float,
        heatmap_name: str = HEATMAP_DEFAULT_BRAKE):
        """Add new brake entry to table"""
        self.table_brakes.insertRow(row_index)
        self.table_brakes.setItem(row_index, 0, QTableWidgetItem(class_name))
        self.table_brakes.setItem(row_index, 1, FloatTableItem(failure_thickness))
        self.table_brakes.setCellWidget(row_index, 2, self.__add_option_combolist(heatmap_name))

    def sort_brake(self):
        """Sort brakes in ascending order"""
        if self.table_brakes.rowCount() > 1:
            self.table_brakes.sortItems(0)
            self.set_modified()

    def delete_brake(self):
        """Delete brake entry"""
        selected_rows = set(data.row() for data in self.table_brakes.selectedIndexes())
        if not selected_rows:
            QMessageBox.warning(self, tr("Error"), tr("No data selected."))
            return

        if not self.confirm_operation(message=tr("<b>Delete selected rows?</b>")):
            return

        for row_index in sorted(selected_rows, reverse=True):
            self.table_brakes.removeRow(row_index)
        self.set_modified()

    def reset_setting(self):
        """Reset setting"""
        msg_text = (
            "Reset <b>brakes preset</b> to default?<br><br>"
            "Changes are only saved after clicking Apply or Save Button."
        )
        if self.confirm_operation(message=msg_text):
            self.brakes_temp = copy_setting(cfg.default.brakes)
            self.replace_table_data(self.refresh_table)

    def applying(self):
        """Save & apply"""
        self.save_setting()

    def saving(self):
        """Save & close"""
        if self.save_setting():
            self.accept()  # close

    def verify_input(self, row_index: int, column_index: int):
        """Verify input value"""
        self.set_modified()
        if column_index == 1:  # failure thickness column
            table_item(self.table_brakes, row_index, column_index, FloatTableItem).validate()

    def verify_table(self) -> bool:
        """Verify table before saving, warn if a brake name is listed more than once"""
        brake_names = set()
        for index in range(self.table_brakes.rowCount()):
            class_name = table_item(self.table_brakes, index, 0).text()
            if class_name in brake_names:
                self.table_brakes.setCurrentCell(index, 0)  # show duplicate row
                msg_text = (
                    f"<b>{class_name}</b> is listed more than once.<br><br>"
                    "Each name can only be listed once, rename or delete duplicate rows."
                )
                QMessageBox.warning(self, tr("Error"), trm(msg_text))
                return False
            brake_names.add(class_name)
        return True

    def update_brakes_temp(self):
        """Update temporary changes to brakes temp first"""
        self.brakes_temp.clear()
        for index in range(self.table_brakes.rowCount()):
            class_name = table_item(self.table_brakes, index, 0).text()
            failure_thickness = table_item(self.table_brakes, index, 1, FloatTableItem).value()
            heatmap_name = cast(QComboBox, self.table_brakes.cellWidget(index, 2)).currentText()
            self.brakes_temp[class_name] = {
                "failure_thickness": failure_thickness,
                "heatmap": heatmap_name,
            }

    def save_setting(self) -> bool:
        """Save setting, False if table is invalid (not saved)"""
        if not self.verify_table():
            return False
        self.update_brakes_temp()
        cfg.user.brakes = copy_setting(self.brakes_temp)
        cfg.save(0, config_type=ConfigType.BRAKES)
        self.set_unmodified()
        run_after_saving(self.reloading)
        return True
