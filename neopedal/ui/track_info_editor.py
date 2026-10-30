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
Track info editor: pit lane, speed trap, map orientation, sun times & primary preset of each track
(table editor page, see quick/table_editor.py)

Distances & pit speed follow the user's Units settings (stored in meters & m/s). Primary preset: chosen among
existing presets, the same setting as the Presets page (track tags); a preset since deleted is marked "not found".
Speed trap cell menu sets it from the car position (current track, out of pit lane).
"""

import html

from ..api_control import api
from ..const_file import ConfigType
from ..i18n import tr
from ..setting import cfg
from ..template.setting_tracks import TRACKINFO_DEFAULT
from .quick.table_editor import (
    KIND_CLOCK,
    KIND_NAME,
    KIND_NUMBER,
    KIND_PRESET,
    Column,
    TableEditorBackend,
    dict_rows,
)
from .quick.table_editor_host import TableEditorPage

KEYS = tuple(TRACKINFO_DEFAULT)
SPEED_TRAP = KEYS.index("speed_trap") + 1  # column
PRESET = KEYS.index("preset") + 1


class TrackBackend(TableEditorBackend):
    """Tracks: name, then TRACKINFO_DEFAULT values"""

    COLUMNS = (
        Column("", "Track name", KIND_NAME, width=12),
        Column("pit_entry", "Pit entry", KIND_NUMBER, width=5, unit="distance"),
        Column("pit_exit", "Pit Exit", KIND_NUMBER, width=5, unit="distance"),
        Column("pit_speed", "Pit speed", KIND_NUMBER, width=5, unit="speed", decimals=2),
        Column("speed_trap", "Speed Trap", KIND_NUMBER, width=5, unit="distance", action="telemetry"),
        Column("orientation", "Map orientation", KIND_NUMBER, width=4, symbol="°"),
        Column("sunrise", "Sunrise", KIND_CLOCK, width=4),
        Column("sunset", "Sunset", KIND_CLOCK, width=4),
        Column("preset", "Primary preset", KIND_PRESET, width=9),
    )
    CONFIG_TYPE = ConfigType.TRACKS
    NEW_NAME = "New Track Name"
    RESET_TEXT = "Reset every track to default? Changes are saved only by Save."

    def load(self) -> list[list]:
        rows = [self.rounded(row) for row in dict_rows(cfg.user.tracks, KEYS, TRACKINFO_DEFAULT)]
        self.loaded_presets = {row[0]: row[PRESET] for row in rows}  # primary presets when page opened
        return rows

    def default_rows(self) -> list[list]:
        return [self.rounded(row) for row in dict_rows(cfg.default.tracks, KEYS, TRACKINFO_DEFAULT)]

    @staticmethod
    def rounded(row: list) -> list:
        """Numbers rounded as shown before (4 decimals)"""
        return [round(value, 4) if isinstance(value, float) else value for value in row]

    def to_setting(self, rows: list[list]) -> dict:
        """Primary preset left as is here keeps the one set from the Presets page meanwhile (saved at once there)"""
        saved = cfg.user.tracks
        setting = {}
        for row in rows:
            data = dict(zip(KEYS, row[1:]))
            current = saved.get(row[0])
            if (isinstance(current, dict) and "preset" in current
                    and data["preset"] == self.loaded_presets.get(row[0], data["preset"])):
                data["preset"] = current["preset"]
            setting[row[0]] = data
        return setting

    def read_saved(self) -> bool:
        """Primary presets set from the Presets page while hidden shown (rows left as is here)"""
        changed = False
        for row in self.rows:
            current = cfg.user.tracks.get(row[0])
            loaded = self.loaded_presets.get(row[0])
            if isinstance(current, dict) and row[PRESET] == loaded and current.get("preset", loaded) != loaded:
                row[PRESET] = self.loaded_presets[row[0]] = current.get("preset", "")
                changed = True
        if changed:
            self._host.record_change()  # own undo step, editor not marked modified
        return changed

    def store(self, setting: dict):
        super().store(setting)
        self.loaded_presets = {name: data["preset"] for name, data in setting.items()}
        changed = False
        for row in self.rows:  # primary presets kept from the Presets page shown
            preset = self.loaded_presets.get(row[0], row[PRESET])
            if preset != row[PRESET]:
                row[PRESET] = preset
                changed = True
        if changed:
            self.refresh()
            self._host.record_change()  # own undo step, editor not marked modified

    def new_row(self, name: str) -> list:
        return [name, *TRACKINFO_DEFAULT.values()]

    def session_rows(self) -> list[list]:
        """Track of the session"""
        track_name = api.read.session.track_name()
        return [self.new_row(track_name)] if track_name else []

    def cell_action(self, key: int, column: int):
        """Speed trap at car position (asked first): current track only, out of pit lane"""
        number = self.index_of(key)
        track_name = str(self.rows[number][0])
        current_name = api.read.session.track_name()
        if track_name != current_name:
            self._host.warn(
                f"Unable to set speed trap position for selected track:<br><b>{html.escape(track_name)}</b><br><br>"
                f"Only support to set speed trap position for current track:<br><b>{html.escape(current_name)}</b>"
            )
            return
        if api.read.vehicle.in_pits():
            self._host.warn("Cannot set speed trap position while in pit lane.")
            return
        position = round(api.read.lap.distance(), 4)
        shown = self.display(SPEED_TRAP, position)
        self.ask(
            tr("Set from Telemetry"),
            tr("Speed trap set at the car position:") + f" {shown}\n{track_name}", tr("Set"),
            "set_value", key, SPEED_TRAP, position)

    def set_value(self, key: int, column: int, value: float):
        """Cell value set (base unit), one undo step"""
        number = self.index_of(key)
        if number >= 0 and self.rows[number][column] != value:
            self.rows[number][column] = value
            self.changed()


class TrackInfoEditor(TableEditorPage):
    """Track info editor"""

    BACKEND = TrackBackend
    TITLE = "Track Info Editor"
