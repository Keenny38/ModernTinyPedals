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
Game replays (LMU): replays saved by the game, opened in game, replay playback commands,
contacts between cars of the session with a jump to each one in the game replay

Everything goes through the game Rest API (see game_rest), the game must be running.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..i18n import tr, trm
from ..process.game_info import IMMOVABLE, GameReplay, driver_slots, parse_contacts, parse_replays
from ._common import BaseEditor, NumericTableItem, UIScaler
from .game_rest import GameRequest, game_command
from .race_widgets import Card, muted_label, spin_box

STATE_RESOURCES = ("/rest/replay/isActive", "/rest/watch/getIncidentsList/1", "/rest/watch/standings")
REPLAYS_RESOURCE = "/rest/watch/replays"
REFRESH_MS = 5000  # replay state & contacts asked again while page shown
DATA_ROLE = Qt.ItemDataRole.UserRole + 1  # table item: index in replays or contacts
# Replay playback commands: (label, tooltip, game command)
PLAYBACK = (
    ("Rewind", "Rewind fast", "VCRCOMMAND_REVERSESCANFAST"),
    ("Reverse", "Play backwards", "VCRCOMMAND_PLAYBACKWARDS"),
    ("Pause", "Pause replay", "VCRCOMMAND_STOP"),
    ("Slow", "Play slowly", "VCRCOMMAND_SLOW"),
    ("Play", "Play replay", "VCRCOMMAND_PLAY"),
    ("Fast Forward", "Play fast", "VCRCOMMAND_FORWARDSCANFAST"),
)


def clock_text(seconds: float) -> str:
    """Session time as h:mm:ss"""
    seconds = max(int(seconds), 0)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def table(parent, headers: Sequence[str]) -> QTableWidget:
    """Read only table, rows selected one at a time"""
    widget = QTableWidget(parent)
    widget.setColumnCount(len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().setVisible(False)
    widget.setShowGrid(False)
    widget.setAlternatingRowColors(True)
    widget.setWordWrap(False)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    header = widget.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # data order until a column is clicked
    widget.setSortingEnabled(True)
    return widget


def fill_table(widget: QTableWidget, rows: Sequence[Sequence[tuple[float | None, str]]]):
    """Rows of (sort value or None for text, text) cells, row index kept in each item"""
    widget.setSortingEnabled(False)
    widget.clearContents()
    widget.setRowCount(len(rows))
    for row_index, cells in enumerate(rows):
        for column_index, (value, text) in enumerate(cells):
            item = QTableWidgetItem(text) if value is None else NumericTableItem(value, text)
            item.setData(DATA_ROLE, row_index)
            widget.setItem(row_index, column_index, item)
    widget.setSortingEnabled(True)


def selected_index(widget: QTableWidget) -> int:
    """Data index of selected row, -1 if none"""
    items = widget.selectedItems()
    return int(items[0].data(DATA_ROLE)) if items else -1


class GameReplays(BaseEditor):
    """Game replays & contacts of session (LMU)"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Game Replays"))
        self.replays: list[GameReplay] = []
        self.contacts: list = []
        self.slots: dict[str, int] = {}
        self.replay_active = False
        self.request_replays = GameRequest(self, (REPLAYS_RESOURCE,), self.received_replays)
        self.request_state = GameRequest(self, STATE_RESOURCES, self.received_state)
        self.request_command = GameRequest(self, (), self.command_done)
        self.command_queue: list[tuple[tuple[str, str], ...]] = []  # commands waiting for the one sent

        # Header
        self.label_status = muted_label(tr("Asking game..."))
        button_refresh = QPushButton(tr("Refresh"))
        button_refresh.setToolTip(tr("Ask game again"))
        button_refresh.clicked.connect(self.refresh_all)
        layout_header = QHBoxLayout()
        layout_header.addWidget(self.label_status, stretch=1)
        layout_header.addWidget(button_refresh)

        # Replays saved by game
        card_replays = Card(self, tr("Replays"))
        self.table_replays = table(self, (tr("Date"), tr("Name"), tr("Event"), tr("Session"), tr("Track"),
                                          tr("Size")))
        self.table_replays.itemDoubleClicked.connect(lambda item: self.watch_replay())
        self.button_watch = QPushButton(tr("Watch in Game"))
        self.button_watch.setToolTip(tr("Open selected replay in the game"))
        self.button_watch.clicked.connect(self.watch_replay)
        layout_watch = QHBoxLayout()
        layout_watch.addWidget(muted_label(tr("Replays saved by the game (UserData/Replays).")), stretch=1)
        layout_watch.addWidget(self.button_watch)
        card_replays.layout_card.addWidget(self.table_replays, stretch=1)
        card_replays.layout_card.addLayout(layout_watch)

        # Playback of replay open in game
        card_playback = Card(self, tr("Replay Playback"))
        self.label_playback = muted_label("")
        layout_playback = QHBoxLayout()
        self.playback_buttons = []
        for label, tooltip, command in PLAYBACK:
            button = QPushButton(tr(label))
            button.setToolTip(tr(tooltip))
            button.clicked.connect(lambda checked=False, command=command: self.send_playback(command))
            layout_playback.addWidget(button)
            self.playback_buttons.append(button)
        layout_playback.addStretch(1)
        card_playback.layout_card.addWidget(self.label_playback)
        card_playback.layout_card.addLayout(layout_playback)

        # Contacts of session
        card_contacts = Card(self, tr("Contacts"))
        self.table_contacts = table(self, (tr("Time"), tr("Driver"), tr("Contact With")))
        self.table_contacts.itemDoubleClicked.connect(lambda item: self.jump_to_contact())
        self.seconds_before = spin_box(60, "s", tooltip=tr("Replay starts this long before the contact"))
        self.seconds_before.setValue(5)
        self.button_jump = QPushButton(tr("Jump to Contact"))
        self.button_jump.setToolTip(tr("Replay open in game goes to selected contact, camera on the car"))
        self.button_jump.clicked.connect(self.jump_to_contact)
        layout_jump = QHBoxLayout()
        layout_jump.addWidget(muted_label(tr("Contacts between cars of the session, as the game lists them.")),
                              stretch=1)
        layout_jump.addWidget(QLabel(tr("Seconds Before")))
        layout_jump.addWidget(self.seconds_before)
        layout_jump.addWidget(self.button_jump)
        card_contacts.layout_card.addWidget(self.table_contacts, stretch=1)
        card_contacts.layout_card.addLayout(layout_jump)

        layout_main = QVBoxLayout(self)
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        layout_main.setSpacing(UIScaler.pixel(8))
        layout_main.addLayout(layout_header)
        layout_main.addWidget(card_replays, stretch=3)
        layout_main.addWidget(card_playback)
        layout_main.addWidget(card_contacts, stretch=2)
        self.resize(UIScaler.size(64), UIScaler.size(44))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_state)
        self.show_replays([])
        self.show_state(None, [], {})

    def showEvent(self, event):
        """Asked to game at once, replay state & contacts again every few seconds while shown"""
        super().showEvent(event)
        self.refresh_all()
        self._timer.start(REFRESH_MS)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    # Game requests
    def refresh_all(self):
        self.request_replays.start()
        self.refresh_state()

    def refresh_state(self):
        self.request_state.start()

    def received_replays(self, answers: list):
        replays = answers[0]
        if replays is None:
            self.label_status.setText(tr("No data from game: LMU not running or not in a session"))
            return
        self.show_replays(parse_replays(replays))
        self.label_status.setText(trm(f"Updated from game at {time.strftime('%H:%M:%S')}"))

    def received_state(self, answers: list):
        active, contacts, standings = answers
        self.show_state(active, list(parse_contacts(contacts, ())), driver_slots(standings))

    def command_done(self, accepted: bool):
        if not accepted:
            self.label_status.setText(tr("Game did not accept the command"))
        if self.command_queue:
            self.send()
        else:
            self.refresh_state()

    def send(self, *commands: tuple[str, str]):
        """Commands to game in background, in order (stops at first refused), after commands sent before"""
        if commands:
            self.command_queue.append(commands)
        if self.request_command.busy or not self.command_queue:
            return
        batch = self.command_queue.pop(0)
        self.request_command.start(lambda: all(game_command(method, resource) for method, resource in batch))

    # Display
    def show_replays(self, replays: list[GameReplay]):
        self.replays = replays
        fill_table(self.table_replays, [(
            (replay.time, time.strftime("%Y-%m-%d %H:%M", time.localtime(replay.time)) if replay.time else "-"),
            (None, replay.name),
            (None, replay.event),
            (None, tr(replay.session.title()) if replay.session else ""),
            (None, replay.track),
            (replay.size, f"{replay.size / 1048576:.0f} MB"),
        ) for replay in replays])
        self.button_watch.setEnabled(bool(replays))

    def show_state(self, active, contacts: list, slots: dict[str, int]):
        """Replay open in game (True, False, None if no answer), contacts of session"""
        self.replay_active = active is True
        self.slots = slots
        if active is None:
            self.label_playback.setText(tr("No data from game: LMU not running or not in a session"))
        elif self.replay_active:
            self.label_playback.setText(tr("Replay open in game"))
        else:
            self.label_playback.setText(tr("No replay open in game: watch one, or open the replay of this session in the game"))
        for button in self.playback_buttons:
            button.setEnabled(self.replay_active)
        if contacts != self.contacts:
            selected = self.selected_contact()
            self.contacts = contacts
            fill_table(self.table_contacts, [(
                (contact.time, clock_text(contact.time)),
                (None, contact.driver),
                (None, tr("Wall") if contact.other == IMMOVABLE else contact.other),
            ) for contact in contacts])
            if selected in contacts:
                self.select_contact(contacts.index(selected))
        self.button_jump.setEnabled(self.replay_active and bool(contacts))

    def selected_contact(self):
        index = selected_index(self.table_contacts)
        return self.contacts[index] if 0 <= index < len(self.contacts) else None

    def select_contact(self, index: int):
        for row in range(self.table_contacts.rowCount()):
            item = self.table_contacts.item(row, 0)
            if item is not None and item.data(DATA_ROLE) == index:
                self.table_contacts.selectRow(row)
                return

    # Actions
    def watch_replay(self):
        """Selected replay opened in game, after confirmation"""
        index = selected_index(self.table_replays)
        if not 0 <= index < len(self.replays):
            return
        replay = self.replays[index]
        if not self.confirm_operation("Watch in Game", f"Open replay <b>{replay.name}</b> in the game?"):
            return
        self.send(("GET", f"/rest/watch/play/{replay.id}"))

    def send_playback(self, command: str):
        self.send(("PUT", f"/rest/watch/replayCommand/{command}"))

    def jump_to_contact(self):
        """Replay open in game goes to selected contact (seconds before), camera on the driver's car"""
        contact = self.selected_contact()
        if contact is None or not self.replay_active:
            return
        commands = []
        slot = self.slots.get(contact.driver)
        if slot is not None:
            commands.append(("PUT", f"/rest/watch/focus/{slot}"))
        replay_time = max(int(contact.time - self.seconds_before.value()), 0)
        commands.append(("PUT", f"/rest/watch/replaytime/{replay_time}"))
        self.send(*commands)
