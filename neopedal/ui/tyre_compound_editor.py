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
Tyre compound editor: symbol, color & heatmap of each compound (table editor page, see quick/table_editor.py)
"""

from ..api_control import api
from ..const_file import ConfigType
from ..setting import cfg
from ..template.setting_compounds import COMPOUNDINFO_DEFAULT, name_color
from ..userfile.heatmap import HEATMAP_DEFAULT_TYRE, set_predefined_compound_symbol
from .quick.table_editor import (
    KIND_CHOICE,
    KIND_COLOR,
    KIND_NAME,
    KIND_SYMBOL,
    Column,
    TableEditorBackend,
    dict_rows,
)
from .quick.table_editor_host import TableEditorPage

KEYS = ("symbol", "color", "heatmap")
NEW_COLOR = "#AAAAAA"


class CompoundBackend(TableEditorBackend):
    """Tyre compounds: name, one letter symbol, color, heatmap"""

    COLUMNS = (
        Column("", "Compound name", KIND_NAME, width=12),
        Column("symbol", "Symbol", KIND_SYMBOL, width=3, replace=True),
        Column("color", "Color", KIND_COLOR, width=7),
        Column("heatmap", "Heatmap name", KIND_CHOICE, width=12),
    )
    CONFIG_TYPE = ConfigType.COMPOUNDS
    NEW_NAME = "New Compound Name"
    RESET_TEXT = "Reset every compound to default? Changes are saved only by Save."

    def load(self) -> list[list]:
        return dict_rows(cfg.user.compounds, KEYS, COMPOUNDINFO_DEFAULT)

    def default_rows(self) -> list[list]:
        return dict_rows(cfg.default.compounds, KEYS, COMPOUNDINFO_DEFAULT)

    def to_setting(self, rows: list[list]) -> dict:
        return {name: {"symbol": symbol, "color": color, "heatmap": heatmap} for name, symbol, color, heatmap in rows}

    def choice_values(self, column: int) -> tuple[str, ...]:
        return tuple(cfg.user.heatmap)

    def new_row(self, name: str) -> list:
        return [name, "?", NEW_COLOR, HEATMAP_DEFAULT_TYRE]

    def session_rows(self) -> list[list]:
        """Compounds of every car of the session (predefined symbol & color)"""
        rows = []
        for index in range(api.read.vehicle.total_vehicles()):
            for compound in dict.fromkeys(api.read.tyre.compound_class(index)):  # front & rear, in order
                rows.append([compound, set_predefined_compound_symbol(compound), name_color(compound),
                             HEATMAP_DEFAULT_TYRE])
        return rows


class TyreCompoundEditor(TableEditorPage):
    """Tyre compound editor"""

    BACKEND = CompoundBackend
    TITLE = "Tyre Compound Editor"
