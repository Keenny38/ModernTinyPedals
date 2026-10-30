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
Brake editor: failure thickness & heatmap of each brake (table editor page, see quick/table_editor.py)
"""

from ..api_control import api
from ..const_file import ConfigType
from ..setting import cfg
from ..template.setting_brakes import BRAKEINFO_DEFAULT
from ..userfile.heatmap import HEATMAP_DEFAULT_BRAKE, set_predefined_brake_name
from .quick.table_editor import KIND_CHOICE, KIND_NAME, KIND_NUMBER, Column, TableEditorBackend, dict_rows
from .quick.table_editor_host import TableEditorPage

KEYS = ("failure_thickness", "heatmap")


class BrakeBackend(TableEditorBackend):
    """Brakes: name, failure thickness (mm), heatmap"""

    COLUMNS = (
        Column("", "Brake name", KIND_NAME, width=14),
        Column("failure_thickness", "Failure", KIND_NUMBER, width=5, symbol="mm"),
        Column("heatmap", "Heatmap name", KIND_CHOICE, width=12),
    )
    CONFIG_TYPE = ConfigType.BRAKES
    NEW_NAME = "New Brake Name"
    RESET_TEXT = "Reset every brake to default? Changes are saved only by Save."

    def load(self) -> list[list]:
        return dict_rows(cfg.user.brakes, KEYS, BRAKEINFO_DEFAULT)

    def default_rows(self) -> list[list]:
        return dict_rows(cfg.default.brakes, KEYS, BRAKEINFO_DEFAULT)

    def to_setting(self, rows: list[list]) -> dict:
        return {name: {"failure_thickness": thickness, "heatmap": heatmap} for name, thickness, heatmap in rows}

    def choice_values(self, column: int) -> tuple[str, ...]:
        return tuple(cfg.user.heatmap)

    def new_row(self, name: str) -> list:
        return [name, 0.0, HEATMAP_DEFAULT_BRAKE]

    def session_rows(self) -> list[list]:
        """Front & rear brakes of every car of the session"""
        rows = []
        for index in range(api.read.vehicle.total_vehicles()):
            class_name = api.read.vehicle.class_name(index)
            vehicle_name = api.read.vehicle.vehicle_name(index)
            for is_front in (True, False):
                rows.append(self.new_row(set_predefined_brake_name(class_name, vehicle_name, is_front)))
        return rows


class BrakeEditor(TableEditorPage):
    """Brake editor"""

    BACKEND = BrakeBackend
    TITLE = "Brake Editor"
