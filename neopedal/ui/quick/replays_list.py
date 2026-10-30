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
Game Replays page replays list (mixin of GameReplaysBackend): replays saved by the game filtered (session,
search), sorted, selected (Ctrl / Shift), opened in game (from race results too, with what to do once open)
"""

from __future__ import annotations

import os
import time
from typing import Any

from PySide6.QtCore import Property, QDate, QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices

from ...i18n import tr, trm
from ...process.game_info import GameReplay, replay_title
from . import dialogs, replay_files
from .formatting import clock_minutes, date_text, day_text
from .game_camera import Command
from .models import DictListModel
from .replays_base import ReplaysBase
from .replays_common import (
    ACTION_WAIT,
    CTRL,
    REPLAY,
    SESSION,
    SESSION_FILTERS,
    SHIFT,
    SORTS,
    ReplayAction,
    event_type_text,
    go_to_lap,
    move_selection,
    play_replay,
    session_text,
    size_text,
)


class ReplaysList(ReplaysBase):
    """Replays list of Game Replays page"""

    # Replays
    @Property(QObject, constant=True)
    def replayRows(self) -> DictListModel:
        return self._replays_model

    @Property(int, notify=ReplaysBase.replaysChanged)
    def replayCount(self) -> int:
        return len(self.replays)

    @Property(int, notify=ReplaysBase.replaysChanged)
    def shownCount(self) -> int:
        return len(self._replays_model.rows)

    @Property(str, notify=ReplaysBase.replaysChanged)
    def replaysSummary(self) -> str:
        """Replays shown & their size: "57 · 7.9 GB", "12 / 57 · 1.2 GB" when filtered"""
        shown = [replay for replay in self.replays if replay.name in self.shown_keys()]
        count = f"{len(shown)} / {len(self.replays)}" if len(shown) != len(self.replays) else f"{len(shown)}"
        return f"{count} · {size_text(sum(replay.size for replay in shown))}"

    @Property(str, notify=ReplaysBase.filesChanged)
    def replayFolder(self) -> str:
        """Replay folder of game, "" if unknown or not on this computer"""
        return self.replay_folder()

    def replay_folder(self) -> str:
        return self.folder if self.folder and os.path.isdir(self.folder) else ""

    @Property(int, notify=ReplaysBase.filterChanged)
    def sessionFilter(self) -> int:
        return self.session_filter

    @Property(str, notify=ReplaysBase.filterChanged)
    def sortKey(self) -> str:
        return self.sort

    @Property(str, notify=ReplaysBase.selectionChanged)
    def selectedReplay(self) -> str:
        return self.selected_replay

    @Property(int, notify=ReplaysBase.checkedChanged)
    def checkedCount(self) -> int:
        return len(self.checked)

    @Property(str, notify=ReplaysBase.checkedChanged)
    def checkedSummary(self) -> str:
        """Replays selected & their size: "3 · 412 MB" (made once selection or replays changed)"""
        return self.checked_summary

    @Property(bool, notify=ReplaysBase.selectedProtectedChanged)
    def selectedProtected(self) -> bool:
        return self.selected_protected

    @Slot(int)
    def setSessionFilter(self, index: int):
        if 0 <= index < len(SESSION_FILTERS) and index != self.session_filter:
            self.session_filter = index
            self.filterChanged.emit()
            self.update_replays()
            self.save_settings()

    @Slot(str)
    def setSearch(self, text: str):
        words = text.lower().split()
        if words != self.search_words:
            self.search_words = words
            self.update_replays()

    @Slot()
    def clearFilters(self):
        """Every replay listed again: search & session filter cleared"""
        if self.search_words or self.session_filter:
            self.search_words = []
            if self.session_filter:
                self.session_filter = 0
                self.filterChanged.emit()
                self.save_settings()
            self.update_replays()

    @Slot(str)
    def setSort(self, key: str):
        if key in SORTS and key != self.sort:
            self.sort = key
            self.filterChanged.emit()
            self.update_replays()
            self.save_settings()

    @Slot(str)
    def selectReplay(self, key: str):
        """Replay selected alone"""
        self.clickReplay(key, 0)

    @Slot(str, int)
    def clickReplay(self, key: str, modifiers: int):
        """Replay clicked: selected alone, Ctrl: added to / removed from selection, Shift: range from current"""
        keys = [row["key"] for row in self._replays_model.rows]
        if modifiers & SHIFT and self.selected_replay in keys and key in keys:
            first, last = sorted((keys.index(self.selected_replay), keys.index(key)))
            checked = set(keys[first:last + 1])
        elif modifiers & CTRL and key:
            checked = self.checked ^ {key}
            self.set_selected_replay(key)
        else:
            checked = {key} if key else set()
            self.set_selected_replay(key)
        self.set_checked(checked)
        self.selectionChanged.emit()  # every click told, same replay too: results page shows its session again

    @Slot()
    def selectAllReplays(self):
        self.set_checked({row["key"] for row in self._replays_model.rows})

    def set_selected_replay(self, key: str):
        """Current replay row: selected role of former & new rows changed (selectionChanged emitted by caller)"""
        old, self.selected_replay = self.selected_replay, key
        if old != key:
            move_selection(self._replays_model, old, key)
        self.update_selected_protected()

    def update_selected_protected(self):
        protected = self.selected_replay in self.protected
        if protected != self.selected_protected:
            self.selected_protected = protected
            self.selectedProtectedChanged.emit()

    def set_checked(self, checked: set[str]):
        if checked != self.checked:  # rows made with the selection have it already
            self.checked = checked
            self._replays_model.update_rows(lambda row: {"checked": row["key"] in checked})
        self.update_checked()

    def update_checked(self):
        """Count & size of replays selected told once changed (sizes summed once, not per read)"""
        summary = f"{len(self.checked)} · {size_text(sum(replay.size for replay in self.checked_replays()))}"
        if summary != self.checked_summary:  # count is part of it
            self.checked_summary = summary
            self.checkedChanged.emit()

    @Slot(int)
    def moveReplaySelection(self, step: int):
        keys = [row["key"] for row in self._replays_model.rows]
        if keys:
            index = keys.index(self.selected_replay) + step if self.selected_replay in keys else 0
            self.selectReplay(keys[max(0, min(index, len(keys) - 1))])

    @Slot(str, result=int)
    def replayIndex(self, key: str) -> int:
        """Row of replay (list scrolled to it), -1 if not shown"""
        return self._replays_model.index_of(key)  # cached row index

    @Slot(str)
    def watchReplay(self, key: str):
        """Replay opened in game, after confirmation (warning in a live session)"""
        self.watch(key)

    def watch(self, key: str, action: ReplayAction | None = None):
        """Replay opened in game after confirmation, then action done once it is open (already open from page:
        action done at once, no confirmation)"""
        replay = self.replay_of(key)
        if replay is None:
            return
        if key not in self.checked:
            self.selectReplay(key)
        if action is not None and self.state == REPLAY and self.playing == replay.name:
            self.action, self.action_deadline = action, time.monotonic() + ACTION_WAIT
            self.action_generation, self.action_after = self.state_generation, 0.0
            self.check_action(None)
            return
        message = f"Open replay <b>{replay.name}</b> in the game?"
        if self.state == SESSION:
            message = f"You are in a session: opening a replay may leave it.<br><br>{message}"
        name = replay.name

        def confirmed(chosen: bool):
            if chosen:
                self.open_replay(name, action)

        dialogs.confirm(self._window, tr("Watch in Game"), trm(message), tr("Watch in Game"), confirmed)

    def open_replay(self, name: str, action: ReplayAction | None):
        """Replay opened in game (confirmed), then action done once it is open"""
        self.playing = name
        command = play_replay(name)
        self.action, self.action_deadline = action, time.monotonic() + ACTION_WAIT
        self.action_generation = self.state_generation + 1  # state asked once game accepted the replay
        self.play_command = command if action is not None else None
        self.play_sent = command
        self.playbackChanged.emit()  # replay opening (openingReplay)
        self.send(command)

    def watch_named(self, name: str, action: ReplayAction | None = None):
        """Replay of name opened in game (race results): at once if game lists it, else once it answers"""
        if self.replays_answered and self.replay_of(name) is not None:
            self.watch(name, action)
            return
        self.pending_watch, self.pending_action = name, action
        self.ask_replays()

    def watch_pending(self):
        """Replay asked by race results opened once replays list answered, else told why not"""
        name, self.pending_watch = self.pending_watch, ""
        action, self.pending_action = self.pending_action, None
        if not name:
            return
        if not self.replays_answered:
            self.notify(trm(f"Start Le Mans Ultimate to watch replay {name}"), True)
        elif self.replay_of(name) is None:
            self.notify(trm(f"Replay not found in game: {name}"), True)
        else:
            self.watch(name, action)

    def check_action(self, state: dict | None):
        """Action of replay opened from race results done once replay is open with its cars (state answer asked
        after it was opened), given up after ACTION_WAIT"""
        action = self.action
        if action is None:
            return
        if time.monotonic() > self.action_deadline:
            self.action = None
            self.notify(trm(f"Replay did not open in time: {action.replay}"), True)
            return
        if state is not None and state.get("generation", self.state_generation) < self.action_generation:
            return
        if self.play_command is not None or time.monotonic() < self.action_after:  # replay still opening
            return
        if self.state != REPLAY or not self.cars or self.replay_time < 0:
            return
        self.action = None
        car = next((self.cars[name] for name in action.drivers if name in self.cars), None)
        lead = self.seconds_before if action.lead < 0 else action.lead
        if action.time < 0 and action.lap > 0:  # lap start unknown: looked for in replay
            if car is None:
                self.notify(trm(f"Driver not found in replay: {action.drivers[0] if action.drivers else ''}"), True)
                return
            self.send(go_to_lap(car.slot, action.lap, int(lead)))
            return
        commands: list[Command] = []
        if car is not None:
            commands.append(("PUT", f"/rest/watch/focus/{car.slot}"))
        if action.time >= 0:
            commands.append(("PUT", f"/rest/watch/replaytime/{max(int(action.time - lead), 0)}"))
        if commands:
            self.send(*commands)

    def set_results_links(self, links: dict[str, str]):
        """Results file of each replay (replay name: path), from race results files"""
        if links != self.results_links:
            self.results_links = links
            if self.replays:
                self.update_replays()

    @Slot(str, result=str)
    def resultsOf(self, key: str) -> str:
        """Results file of replay's session, "" if none"""
        return self.results_links.get(key, "")

    @Slot()
    def openFolder(self):
        folder = self.replay_folder()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Slot(str)
    def showInFolder(self, key: str):
        folder = self.replay_folder()
        if folder and self.replay_of(key) is not None:
            replay_files.show_in_folder(replay_files.replay_path(folder, key))

    def replay_of(self, key: str) -> GameReplay | None:
        return next((replay for replay in self.replays if replay.name == key), None)

    def checked_replays(self) -> list[GameReplay]:
        return [replay for replay in self.replays if replay.name in self.checked]

    def chosen_replays(self, key: str) -> list[GameReplay]:
        """Replays of an action on key: selected replays if key is one of them, else key"""
        return self.checked_replays() if key in self.checked else [replay for replay in self.replays
                                                                   if replay.name == key]

    def shown_keys(self) -> set[str]:
        return {row["key"] for row in self._replays_model.rows}

    def matches(self, replay: GameReplay) -> bool:
        session = SESSION_FILTERS[self.session_filter]
        if session and replay.session.upper() != session:
            return False
        if not self.search_words:
            return True
        text = " ".join((replay.name, replay.event, replay.track, session_text(replay.session),
                         event_type_text(replay.event_type))).lower()
        return all(word in text for word in self.search_words)

    @Slot()
    def pictures_changed(self):
        """Logos fetched from game meanwhile (once shown again if hidden: hidden pages never rebuild)"""
        if self.defer_while_hidden(self.pictures_changed):
            return
        if self.replays:
            self.update_replays()
        if self.standings:
            self.update_standings()

    def update_replays(self):
        """Replays rows: filtered, sorted, section of each (day, track)"""
        replays = [replay for replay in self.replays if self.matches(replay)]
        if self.sort == "size":
            replays.sort(key=lambda replay: replay.size, reverse=True)
        elif self.sort == "track":
            replays.sort(key=lambda replay: (replay_title(replay.name)[0].lower(), -replay.time))
        today = QDate.currentDate()
        rows: list[dict[str, Any]] = []
        for replay in replays:
            track, code = replay_title(replay.name)
            by_date = self.sort == "date"
            rows.append({
                "key": replay.name,
                "track": track,
                "code": code,
                "session": replay.session.upper(),
                "sessionLabel": session_text(replay.session) if replay.session else "",
                "event": replay.event,
                "eventType": event_type_text(replay.event_type) if replay.event_type else "",
                "section": day_text(replay.time, today) if by_date else track if self.sort == "track" else "",
                "date": "" if replay.time <= 0 else clock_minutes(replay.time) if by_date else date_text(replay.time),
                "size": size_text(replay.size),
                "tip": f"{replay.name}\n{date_text(replay.time)}".strip(),
                "checked": replay.name in self.checked,
                "selected": replay.name == self.selected_replay,
                "isProtected": replay.name in self.protected,
                "trackLogo": self.logos.track(track, replay.track),
                "hasResults": replay.name in self.results_links,
            })
        self._replays_model.sync(rows)
        shown = self.shown_keys()
        if self.checked - shown:  # selected replays filtered out or deleted: no longer selected
            self.set_checked(self.checked & shown)
        if self.selected_replay not in shown:
            self.selectReplay(rows[0]["key"] if rows else "")
        self.update_checked()  # sizes of selected replays told by game
        self.replaysChanged.emit()
