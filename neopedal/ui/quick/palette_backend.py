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
Command palette backend (qml/shell/CommandPalette.qml): results of the typed search in groups, recent commands
when nothing is typed, prefixes ">" commands, "@" options, "#" presets; the chosen command runs once the palette
is closed (see ui.command_palette for commands & scoring)
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from ...i18n import tr, untr
from .. import command_palette as palette
from .models import DictListModel
from .shell_popup import ShellBackend, ShellPopup, centered_top, popup_size

KIND = "palette"
ROLES = ("key", "title", "group", "detail", "shortcut", "glyph")


class PaletteBackend(ShellBackend):
    """Search & results of the palette"""

    resultsChanged = Signal()

    def __init__(self, window: QWidget):
        super().__init__()
        self._window = window
        self.commands = palette.build_commands(window)
        self._presets: list[palette.Command] | None = None
        self._query = ""
        self._results: list[palette.Command] = []
        self._rows: list[dict] = []
        self.model = DictListModel(ROLES, self)  # rows synced in place: delegates of results kept are not rebuilt
        self.update_results("")

    @property
    def presets(self) -> list[palette.Command]:
        """Preset commands, read on first use (folder listed)"""
        if self._presets is None:
            self._presets = palette.preset_commands()
        return self._presets

    @property
    def options(self):
        """Option index of Find Option (cached until settings change)"""
        from ..option_finder import cached_index

        return cached_index()

    def recent_commands(self) -> list[palette.Command]:
        """Commands run last that still exist, newest first, in Recent group"""
        keys = palette.recent_keys()
        if not keys:
            return []
        known = {command.key: command for command in (*self.commands, *self.presets) if command.key}
        group = tr(palette.GROUP_RECENT)
        recent = []
        for key in keys:
            command = known.get(key)
            if command is None and key.startswith("option:"):
                command = self.option_command(key.removeprefix("option:"))
            if command is not None:
                recent.append(command._replace(kind=group, glyph=command.glyph or palette.GROUP_GLYPHS[
                    palette.GROUP_RECENT]))
        return recent

    def option_command(self, path: str) -> palette.Command | None:
        """Option command of "section/key", None if the option is gone"""
        section, _, key = path.partition("/")
        from ..option_finder import open_option

        for entry in self.options:
            if entry.section == section and entry.key == key:
                from ...i18n.options import module_label, option_label

                return palette.Command(
                    option_label(key), tr(palette.GROUP_OPTIONS), entry.text,
                    partial(open_option, self._window, entry), palette.GROUP_GLYPHS[palette.GROUP_OPTIONS],
                    key=f"option:{path}", detail=module_label(section))
        return None

    def results_for(self, query: str) -> list[palette.Command]:
        """Commands shown for query"""
        prefix, text = palette.split_prefix(query)
        if prefix == palette.PREFIX_COMMANDS:
            group = tr(palette.GROUP_COMMANDS)
            return palette.match_commands([command for command in self.commands if command.kind == group], text)
        if prefix == palette.PREFIX_OPTIONS:
            return palette.option_commands(self._window, text) if text else []
        if prefix == palette.PREFIX_PRESETS:
            return palette.match_commands(self.presets, text)
        if not text:
            return self.recent_commands() + self.commands[:palette.MAX_COMMANDS]
        found = palette.match_commands([*self.commands, *self.presets], text)
        if len(text) >= 2:
            found += palette.option_commands(self._window, text)
        return found

    def update_results(self, query: str):
        self._query = query
        results = self.results_for(query)
        rows = []
        seen: dict[str, int] = {}  # row key: times listed (a command in Recent and in its group: two rows)
        for command in results:
            key = f"{command.kind}\n{command.key or command.title}"
            seen[key] = seen.get(key, 0) + 1
            rows.append({
                "key": key if seen[key] == 1 else f"{key}\n{seen[key]}",
                "title": command.title, "group": command.kind, "detail": command.detail, "shortcut": command.shortcut,
                "glyph": command.glyph or palette.GROUP_GLYPHS.get(untr(command.kind), ""),
            })
        self._results = results
        if rows != self._rows:
            self._rows = rows
            self.model.sync(rows, reset_if_mostly_new=True)
            self.resultsChanged.emit()  # first result selected again (see CommandPalette.qml)

    @property
    def results(self) -> list[dict]:
        """Rows shown (tests): title, group, detail, shortcut, glyph"""
        return self._rows

    @Property(QObject, constant=True)
    def resultsModel(self) -> QObject:
        return self.model

    @Property(str, constant=True)
    def hint(self) -> str:
        return tr("Type > for commands, @ for options, # for presets")

    @Slot(str)
    def setQuery(self, text: str):
        if text != self._query:
            self.update_results(text)

    def titles(self) -> list[str]:
        """Titles of results (tests)"""
        return [command.title for command in self._results]

    def command_at(self, index: int) -> palette.Command | None:
        return self._results[index] if 0 <= index < len(self._results) else None

    @Slot(int)
    def run(self, index: int):
        """Run result: palette closed first, command run once the QML handler is done"""
        command = self.command_at(index)
        if command is None:
            return
        palette.remember_recent(command.key)
        self.closeRequested.emit()
        QTimer.singleShot(0, self._window, command.run)

    @Slot()
    def close(self):
        self.closeRequested.emit()


class PalettePopup(ShellPopup):
    """Command palette popup, centered near the top of the main window"""

    backend: PaletteBackend

    @classmethod
    def open_for(cls, window: QWidget) -> PalettePopup:
        size = popup_size(window, 40, 28)
        popup = cls(window, KIND, "CommandPalette.qml", PaletteBackend(window), size)
        popup.popup(centered_top(window, size))
        return popup

    @property
    def commands(self) -> list[palette.Command]:
        return self.backend.commands

    @property
    def options(self):
        return self.backend.options

    def set_search(self, text: str):
        """Search text, results at once (tests, command line)"""
        self.backend.setQuery(text)

    def run_selected(self):
        """Run first result"""
        self.backend.run(0)
