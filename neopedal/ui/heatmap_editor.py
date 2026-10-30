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
Heatmap editor: temperature steps & colors of each heatmap preset (table editor page, see quick/table_editor.py)

Preset picker (New, Copy, Delete), live preview of the colors of the heatmap being edited, temperatures in the
user's unit (stored in Celsius, keys rounded to 0.1), Offset adds a value to selected temperatures or scales
them. Undo history is per heatmap (cleared when another one is picked); Save writes every heatmap.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import Property, Signal, Slot

from ..const_file import ConfigType
from ..i18n import tr
from ..setting import cfg, copy_setting
from ..validator import is_hex_color
from .quick.table_editor import KIND_COLOR, KIND_NUMBER, Column, TableEditorBackend
from .quick.table_editor_host import TableEditorPage

if TYPE_CHECKING:
    _MixinBase = TableEditorBackend
else:
    _MixinBase = object

NEW_HEATMAP = {"-273.0": "#4444FF"}
VALID_NAME = re.compile(r"[0-9a-zA-Z_]+")


def temperature_key(value: float) -> str:
    """Heatmap key of a temperature (Celsius)"""
    return f"{value:.1f}"


class HeatmapMixin(_MixinBase):
    """Heatmap presets & preview (own signals: a property of a QObject subclass naming a signal of its base loses
    its notify)"""

    presetsChanged = Signal()
    bandsChanged = Signal()

    if TYPE_CHECKING:  # set & defined by HeatmapBackend
        heatmap_temp: dict[str, dict]
        selected_key: str

        def update_current(self) -> None: ...
        def show_preset(self, name: str) -> None: ...

    @Property(list, notify=presetsChanged)
    def presetNames(self) -> list[str]:
        return list(self.heatmap_temp)

    @Property(int, notify=presetsChanged)
    def presetIndex(self) -> int:
        return list(self.heatmap_temp).index(self.selected_key) if self.selected_key in self.heatmap_temp else -1

    @Property(bool, notify=presetsChanged)
    def canDeletePreset(self) -> bool:
        return self.selected_key not in cfg.default.heatmap and len(self.heatmap_temp) > 1

    @Property(list, notify=bandsChanged)
    def bands(self) -> list[dict]:
        """Steps of heatmap being edited, coldest first: color, start temperature (user unit)"""
        found = []
        for temperature, color in sorted(self.rows, key=lambda row: row[0]):
            if not is_hex_color(color):
                continue
            label = self.display(0, temperature)
            unit = self._converters[0][2] if 0 in self._converters else ""
            found.append({"color": color, "label": label, "tip": tr("From") + f" {label} {unit}".rstrip()})
        return found

    @Slot(str, result=str)
    def checkPresetName(self, name: str) -> str:
        """Error of a new preset name, "" if valid"""
        if not name or not VALID_NAME.fullmatch(name):
            return tr("Invalid preset name.")
        if name in self.heatmap_temp:  # includes presets not saved yet
            return tr("Preset already exists.")
        return ""

    @Slot(int, result=bool)
    def selectPreset(self, index: int) -> bool:
        """Other heatmap edited, False if the table has errors (kept on this one)"""
        names = list(self.heatmap_temp)
        if not 0 <= index < len(names) or names[index] == self.selected_key:
            return False
        if not self.verify():
            self.presetsChanged.emit()  # picker back to this one
            return False
        self.update_current()
        self.show_preset(names[index])
        return True

    @Slot(str, bool)
    def createPreset(self, name: str, copy: bool):
        """New preset (copy of this one with its edits, or a single step), edited at once"""
        error = self.checkPresetName(name)
        if error:
            self._host.warn(error)
            return
        if not self.verify():
            return
        self.update_current()
        self.heatmap_temp[name] = dict(self.heatmap_temp[self.selected_key]) if copy else dict(NEW_HEATMAP)
        self.show_preset(name)
        self._host.set_modified()

    @Slot()
    def askDeletePreset(self):
        if self.canDeletePreset:
            self.ask(tr("Delete Preset?"),
                     tr("Heatmap preset deleted once saved:") + f" {self.selected_key}", tr("Delete"), "deletePreset")

    @Slot()
    def deletePreset(self):
        if not self.canDeletePreset:
            return
        names = list(self.heatmap_temp)
        index = names.index(self.selected_key)
        self.heatmap_temp.pop(self.selected_key)
        names.pop(index)
        self.show_preset(names[min(index, len(names) - 1)])
        self._host.set_modified()

    @Slot(float, bool)
    def offsetSelected(self, amount: float, scale: bool):
        """Temperatures of selected rows offset (or scaled) in the unit shown, one undo step"""
        if not self._selected or (scale and amount <= 0) or (not scale and amount == 0):
            return
        to_shown, to_base, _ = self._converters.get(0, (float, float, ""))
        for key, row in zip(self.keys, self.rows):
            if key in self._selected:
                shown = to_shown(row[0])
                row[0] = round(to_base(shown * amount if scale else shown + amount), 6)
        self.changed()


class HeatmapBackend(HeatmapMixin, TableEditorBackend):
    """Heatmap steps of selected preset: temperature (Celsius), color"""

    COLUMNS = (
        Column("", "Temperature", KIND_NUMBER, width=6, unit="temperature", decimals=1),
        Column("", "Color", KIND_COLOR, width=8),
    )
    CONFIG_TYPE = ConfigType.HEATMAP
    FEATURES = ("heatmap",)
    RESET_TEXT = "Reset this heatmap preset to default? Changes are saved only by Save."

    def setup(self):
        self.heatmap_temp: dict[str, dict] = copy_setting(cfg.user.heatmap)
        self.selected_key = next(iter(self.heatmap_temp), "")

    def heatmap_rows(self, heatmap: dict) -> list[list]:
        rows = []
        for temperature, color in heatmap.items():
            try:
                rows.append([float(temperature), color])
            except (TypeError, ValueError):
                continue  # not a temperature: dropped
        return rows

    def load(self) -> list[list]:
        return self.heatmap_rows(self.heatmap_temp.get(self.selected_key, {}))

    def default_rows(self) -> list[list]:
        return self.heatmap_rows(cfg.default.heatmap.get(self.selected_key, {}))

    def can_reset(self) -> bool:
        return self.selected_key in cfg.default.heatmap

    def unique_text(self, value) -> str:
        return temperature_key(value)

    def duplicate_message(self, row: list) -> str:
        return (
            f"Temperature <b>{temperature_key(row[0])}</b> is listed more than once.<br><br>"
            "Each temperature can only be listed once, change or remove duplicate rows."
        )

    def row_label(self, row: list) -> str:
        return f"{temperature_key(row[0])} °C"

    def refresh(self):
        super().refresh()
        self.bandsChanged.emit()

    def sort_rows(self):
        """Rows by temperature (keys & selection kept), no undo step"""
        order = sorted(range(len(self.rows)), key=lambda number: self.rows[number][0])
        self.rows = [self.rows[number] for number in order]
        self.keys = [self.keys[number] for number in order]

    def rows_to_add(self) -> tuple[list[list], bool]:
        """Step 10 degrees above the hottest one (white), or -273 (blue) in an empty heatmap: temperature to type"""
        self.sort_rows()
        if self.rows:
            return [[self.rows[-1][0] + 10, "#FFFFFF"]], True
        return [[-273.0, "#4444FF"]], True

    def update_current(self):
        """Table (sorted) applied to selected heatmap"""
        self.sort_rows()
        self.heatmap_temp[self.selected_key] = {temperature_key(value): color for value, color in self.rows}

    def show_preset(self, name: str):
        """Heatmap edited: its rows, undo history of its own"""
        self.selected_key = name
        self._selected = set()
        self.set_rows(self.load())
        self._host.reset_undo()
        self.presetsChanged.emit()

    def to_setting(self, rows: list[list]) -> dict:
        self.update_current()
        self.refresh()  # shown sorted
        return self.heatmap_temp

    def store(self, setting: dict):
        cfg.user.heatmap = copy_setting(setting)
        cfg.save(0, config_type=ConfigType.HEATMAP)


class HeatmapEditor(TableEditorPage):
    """Heatmap editor"""

    BACKEND = HeatmapBackend
    TITLE = "Heatmap Editor"

