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
Tyre compound editor
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
from ..template.setting_compounds import name_color
from ..userfile.heatmap import HEATMAP_DEFAULT_TYRE, set_predefined_compound_symbol
from ..validator import is_hex_color
from ._common import (
    QVAL_COLOR,
    BaseEditor,
    TableBatchReplace,
    UIScaler,
    column_texts,
    run_after_saving,
    table_item,
)
from ._option import ColorEdit

HEADER_COMPOUNDS = "Compound name", "Symbol", "Color", "Heatmap name"

logger = logging.getLogger(__name__)


class TyreCompoundEditor(BaseEditor):
    """Tyre compound editor"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Tyre Compound Editor"))
        self.setMinimumSize(UIScaler.size(42), UIScaler.size(38))

        self.compounds_temp = copy_setting(cfg.user.compounds)

        # Set table
        self.table_compounds = self.editor_table(HEADER_COMPOUNDS, {1: 5, 2: 7, 3: 12})  # symbol, color & heatmap
        self.table_compounds.cellChanged.connect(self.verify_input)
        self.refresh_table()
        self.enable_table_undo("compounds_temp", self.update_compounds_temp, self.refresh_table)
        self.set_unmodified()

        # Set button
        layout_button = self.set_layout_button()

        # Set layout
        layout_main = QVBoxLayout()
        layout_main.addWidget(self.table_compounds)
        layout_main.addLayout(layout_button)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self.setLayout(layout_main)

    def set_layout_button(self):
        """Set button layout"""
        return self.editor_buttons(
            (("Add", self.add_compound), ("Sort", self.sort_compound), ("Delete", self.delete_compound),
             ("Replace", self.open_replace_dialog)),
            self.reset_setting, self.applying)

    def refresh_table(self):
        """Refresh compounds list"""
        self.table_compounds.setRowCount(0)
        row_index = 0
        for compound_name, compound_data in self.compounds_temp.items():
            self.add_compound_entry(
                row_index,
                compound_name,
                compound_data["symbol"],
                compound_data["color"],
                compound_data["heatmap"],
            )
            row_index += 1

    def __add_option_color(self, key):
        """Color string"""
        color_edit = ColorEdit(self, key)
        color_edit.setMaxLength(9)
        color_edit.setValidator(QVAL_COLOR)
        color_edit.textChanged.connect(self.set_modified)
        color_edit.setText(key)  # load selected option
        return color_edit

    def __add_option_combolist(self, key):
        """Combo droplist string"""
        combo_edit = QComboBox()
        combo_edit.addItems(tuple(cfg.user.heatmap))
        combo_edit.setCurrentText(key)
        combo_edit.currentTextChanged.connect(self.set_modified)
        return combo_edit

    def open_replace_dialog(self):
        """Open replace dialog"""
        selector = {tr(HEADER_COMPOUNDS[1]): 1}
        _dialog = TableBatchReplace(self, selector, self.table_compounds)
        _dialog.open()

    def add_compound(self):
        """Add new compound"""
        start_index = row_index = self.table_compounds.rowCount()
        listed = column_texts(self.table_compounds, 0)
        with self.batch_edit():  # one undo step
            # Add all missing vehicle name from active session
            veh_total = api.read.vehicle.total_vehicles()
            for index in range(veh_total):
                compounds = set(api.read.tyre.compound_class(index))
                for compound in compounds:
                    if compound not in listed:
                        self.add_compound_entry(
                            row_index,
                            compound,
                            set_predefined_compound_symbol(compound),
                            name_color(compound),
                        )
                        listed.add(compound)
                        row_index += 1
            if start_index != row_index:
                self.table_compounds.setCurrentCell(row_index - 1, 0)  # last added
            # Add new name entry
            else:
                new_compound_name = self.new_name_increment("New Compound Name", self.table_compounds)
                self.add_compound_entry(row_index, new_compound_name)
                self.table_compounds.setCurrentCell(row_index, 0)

    def add_compound_entry(
        self, row_index: int, compound_name: str, symbol_name: str = "?", color: str = "#AAAAAA",
        heatmap_name: str = HEATMAP_DEFAULT_TYRE):
        """Add new compound entry to table"""
        self.table_compounds.insertRow(row_index)
        self.table_compounds.setItem(row_index, 0, QTableWidgetItem(compound_name))
        self.table_compounds.setItem(row_index, 1, QTableWidgetItem(symbol_name))
        self.table_compounds.setCellWidget(row_index, 2, self.__add_option_color(color))
        self.table_compounds.setCellWidget(row_index, 3, self.__add_option_combolist(heatmap_name))

    def sort_compound(self):
        """Sort compounds in ascending order"""
        if self.table_compounds.rowCount() > 1:
            self.table_compounds.sortItems(0)
            self.set_modified()

    def delete_compound(self):
        """Delete compound entry"""
        selected_rows = set(data.row() for data in self.table_compounds.selectedIndexes())
        if not selected_rows:
            QMessageBox.warning(self, tr("Error"), tr("No data selected."))
            return

        if not self.confirm_operation(message=tr("<b>Delete selected rows?</b>")):
            return

        for row_index in sorted(selected_rows, reverse=True):
            self.table_compounds.removeRow(row_index)
        self.set_modified()

    def reset_setting(self):
        """Reset setting"""
        msg_text = (
            "Reset <b>compounds preset</b> to default?<br><br>"
            "Changes are only saved after clicking Apply or Save Button."
        )
        if self.confirm_operation(message=msg_text):
            self.compounds_temp = copy_setting(cfg.default.compounds)
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
        item = table_item(self.table_compounds, row_index, column_index)
        if column_index == 1:  # symbol column
            text = item.text()
            if not text:
                item.setText("?")
            else:
                item.setText(text[:1])

    def verify_table(self) -> bool:
        """Verify table before saving, warn if a compound name is listed twice or a color is invalid"""
        compound_names = set()
        for index in range(self.table_compounds.rowCount()):
            compound_name = table_item(self.table_compounds, index, 0).text()
            color = cast(ColorEdit, self.table_compounds.cellWidget(index, 2)).text()
            if compound_name in compound_names:
                msg_text = (
                    f"<b>{compound_name}</b> is listed more than once.<br><br>"
                    "Each name can only be listed once, rename or delete duplicate rows."
                )
            elif not is_hex_color(color):
                msg_text = (
                    f"Invalid color <b>{color}</b> for <b>{compound_name}</b>.<br><br>"
                    "Use #RGB, #RRGGBB or #AARRGGBB format."
                )
            else:
                compound_names.add(compound_name)
                continue
            self.table_compounds.setCurrentCell(index, 0)  # show invalid row
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return False
        return True

    def update_compounds_temp(self):
        """Update temporary changes to compounds temp first"""
        self.compounds_temp.clear()
        for index in range(self.table_compounds.rowCount()):
            compound_name = table_item(self.table_compounds, index, 0).text()
            symbol_name = table_item(self.table_compounds, index, 1).text()
            color = cast(ColorEdit, self.table_compounds.cellWidget(index, 2)).text()
            heatmap_name = cast(QComboBox, self.table_compounds.cellWidget(index, 3)).currentText()
            self.compounds_temp[compound_name] = {
                "symbol": symbol_name,
                "color": color,
                "heatmap": heatmap_name,
            }

    def save_setting(self) -> bool:
        """Save setting, False if table is invalid (not saved)"""
        if not self.verify_table():
            return False
        self.update_compounds_temp()
        cfg.user.compounds = copy_setting(self.compounds_temp)
        cfg.save(0, config_type=ConfigType.COMPOUNDS)
        self.set_unmodified()
        run_after_saving(self.reloading)
        return True
