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
Vehicle class editor: alias & color of each car class (table editor page, see quick/table_editor.py)

Primary preset of a class is set from the Presets page: kept as is here.
"""

import random

from ..api_control import api
from ..const_common import EMPTY_DICT
from ..const_file import ConfigType
from ..formatter import random_color_class
from ..setting import cfg
from ..template.setting_classes import CLASS_PRESET_KEYS, CLASSINFO_DEFAULT
from .quick.table_editor import KIND_COLOR, KIND_NAME, KIND_TEXT, Column, TableEditorBackend, dict_rows
from .quick.table_editor_host import TableEditorPage

KEYS = ("alias", "color")


class ClassBackend(TableEditorBackend):
    """Car classes: name, alias, color (primary preset kept)"""

    COLUMNS = (
        Column("", "Class name", KIND_NAME, width=12),
        Column("alias", "Alias name", KIND_TEXT, width=8),
        Column("color", "Color", KIND_COLOR, width=7),
    )
    CONFIG_TYPE = ConfigType.CLASSES
    NEW_NAME = "New Class Name"
    RESET_TEXT = "Reset every class to default? Changes are saved only by Save."

    def load(self) -> list[list]:
        return dict_rows(cfg.user.classes, KEYS, CLASSINFO_DEFAULT)

    def default_rows(self) -> list[list]:
        return dict_rows(cfg.default.classes, KEYS, CLASSINFO_DEFAULT)

    def to_setting(self, rows: list[list]) -> dict:
        """Primary presets of each class kept (every session & by session, set from Presets page)"""
        saved = cfg.user.classes
        return {
            name: {
                "alias": alias, "color": color,
                **{key: saved.get(name, EMPTY_DICT).get(key, "") for key in CLASS_PRESET_KEYS},
            }
            for name, alias, color in rows
        }

    def new_row(self, name: str) -> list:
        return [name, "NAME", random_color_class(str(random.random()))]

    def session_rows(self) -> list[list]:
        """Classes of the session (alias: class name, color from name)"""
        rows = []
        for index in range(api.read.vehicle.total_vehicles()):
            class_name = api.read.vehicle.class_name(index)
            rows.append([class_name, class_name, random_color_class(class_name)])
        return rows


class VehicleClassEditor(TableEditorPage):
    """Vehicle class editor"""

    BACKEND = ClassBackend
    TITLE = "Vehicle Class Editor"
