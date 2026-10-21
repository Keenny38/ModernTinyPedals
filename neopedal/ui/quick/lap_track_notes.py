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
Lap viewer track notes (part of LapViewerBackend, QML backend.trackNotes): notes at a track distance, shown on charts
& track map of every lap of the track

Notes are the track notes file of the track (Track Notes overlay reads the same file while driving): a note added in
the viewer shows in game, notes written for the overlay show in the viewer. Pit lane notes (#pit tag) left out.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from ...const_file import FileExt
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile import atomic_write
from ...userfile.track_notes import (
    COLUMN_COMMENT,
    COLUMN_DISTANCE,
    COLUMN_TAGS,
    COLUMN_TRACKNOTE,
    HEADER_TRACK_NOTES,
    TAG_PITNOTES,
    create_notes_metadata,
    load_notes_file,
    parse_csv_notes,
    write_csv_notes,
)
from ..lap_viewer import distance_text
from . import lap_map
from .lap_base import PagePart, weak_host

if TYPE_CHECKING:
    from PySide6.QtCore import SignalInstance
    from PySide6.QtWidgets import QWidget

    from .trace_data import TraceData

logger = logging.getLogger(__name__)

MAX_NOTE_LENGTH = 200  # characters kept of a note typed in the viewer


class TrackNotesHost(Protocol):
    """What the track notes part uses of the lap viewer page"""

    data: TraceData
    _window: QWidget

    @property
    def chartChanged(self) -> SignalInstance: ...
    @property
    def mapDataChanged(self) -> SignalInstance: ...
    @property
    def mapCornersChanged(self) -> SignalInstance: ...
    def reference_map_line(self) -> lap_map.MapLine | None: ...
    def set_status(self, text: str, transient: bool = True): ...


def track_of(data: TraceData) -> str:
    """Game track name of reference lap (track notes file name), empty if unknown"""
    reference = data.reference
    track = reference.data.meta.get("track", "") if reference is not None else ""
    return track if isinstance(track, str) else ""


def notes_path(track: str) -> str:
    return f"{cfg.path.track_notes}{track}{FileExt.TPTN}"


def file_time(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def is_pit_note(note: dict) -> bool:
    return TAG_PITNOTES in str(note.get(COLUMN_TAGS, ""))


class TrackNotes(PagePart):
    """Track notes of the track of reference lap (QML backend.trackNotes)"""

    changed = Signal()  # notes, track or their place on charts & map

    def __init__(self, page: TrackNotesHost, parent: QObject | None = None):
        super().__init__(parent)
        self._page = weak_host(page)
        self._track = ""
        self._time = 0.0  # notes file time when read (changed by another editor: read again)
        self._notes: list[dict] = []  # every note of file (pit notes kept when saving)
        self._metadata: dict = {}
        self._items: list[dict] = []  # notes on charts & map (see place)
        page.chartChanged.connect(self.refresh)
        page.mapDataChanged.connect(self.place)  # map turned or rebuilt: places on map
        page.mapCornersChanged.connect(self.place)

    def release(self):
        self._track, self._time, self._notes, self._metadata, self._items = "", 0.0, [], {}, []

    def refresh(self):
        """Laps shown changed: notes of reference lap track (read again if file changed), places on charts"""
        track = track_of(self._page.data)
        if track != self._track or (track and file_time(notes_path(track)) != self._time):
            self.read(track)
        self.place()

    def read(self, track: str):
        self._track = track
        self._notes, self._metadata = [], {}
        self._time = 0.0
        if not track:
            return
        path = notes_path(track)
        self._time = file_time(path)
        if not self._time:
            return
        loaded = load_notes_file(cfg.path.track_notes, track, HEADER_TRACK_NOTES, parse_csv_notes, FileExt.TPTN)
        if loaded:
            notes, metadata = loaded
            self._notes = [note for note in notes if isinstance(note, dict)]
            self._metadata = metadata if isinstance(metadata, dict) else {}

    def shown(self) -> list[tuple[int, dict]]:
        """Notes along the lap (pit lane notes left out): index in file, note"""
        return [(index, note) for index, note in enumerate(self._notes) if not is_pit_note(note)]

    @Property(bool, notify=changed)
    def available(self) -> bool:
        """Whether notes can be added (track of reference lap known)"""
        return bool(self._track)

    @Property(list, notify=changed)
    def items(self) -> list[dict]:
        """Notes on charts & map: axis position, map point (none if map unknown), text, distance, index in file"""
        return self._items

    def place(self):
        """Notes placed on charts & map again (laps, axis or map changed)"""
        self._items = self.placed()
        self.changed.emit()

    def placed(self) -> list[dict]:
        data = self._page.data
        if data.reference is None:
            return []
        line = self._page.reference_map_line()
        items = []
        for index, note in self.shown():
            distance = float(note.get(COLUMN_DISTANCE, 0.0))
            text = str(note.get(COLUMN_TRACKNOTE, "") or note.get(COLUMN_COMMENT, "")).strip()
            item = {"index": index, "x": data.x_at_distance(distance), "distance": distance, "text": text,
                    "comment": str(note.get(COLUMN_COMMENT, "")), "place": distance_text(distance)}
            if line is not None:
                item["mapX"], item["mapY"] = lap_map.point_at(line, distance)
            items.append(item)
        return items

    @Slot(float)
    def addAt(self, x: float):
        """New note at axis position (text asked)"""
        if not self._track:
            return
        distance = round(self._page.data.distance_at_x(x), 1)

        def saving(text: str) -> bool:
            text = " ".join(text.split())[:MAX_NOTE_LENGTH]
            if not text:
                return True
            notes = [*self._notes, {COLUMN_DISTANCE: distance, COLUMN_TRACKNOTE: text, COLUMN_COMMENT: "",
                                    COLUMN_TAGS: ""}]
            return self.save(notes)

        self.ask(trm(f"Note at {distance_text(distance)} (shown on every lap of this track & by Track Notes overlay):"),
                 "", saving)

    @Slot(int)
    def edit(self, index: int):
        """Change text of note (empty text removes it)"""
        if not 0 <= index < len(self._notes):
            return
        note = self._notes[index]

        def saving(text: str) -> bool:
            text = " ".join(text.split())[:MAX_NOTE_LENGTH]
            if not text:
                return self.save([other for position, other in enumerate(self._notes) if position != index])
            return self.save([{**other, COLUMN_TRACKNOTE: text} if position == index else other
                              for position, other in enumerate(self._notes)])

        self.ask(tr("Note text (empty to remove):"), str(note.get(COLUMN_TRACKNOTE, "")), saving)

    @Slot(int)
    def remove(self, index: int):
        if 0 <= index < len(self._notes):
            self.save([note for position, note in enumerate(self._notes) if position != index])

    def ask(self, label: str, text: str, saving):
        from .._common import TextInputDialog

        TextInputDialog(self._page._window, tr("Track Note"), label, saving, text).show()

    def save(self, notes: list[dict]) -> bool:
        """Write notes file (sorted by distance), True if saved"""
        track = self._track
        if not track:
            return False
        notes = sorted(notes, key=lambda note: float(note.get(COLUMN_DISTANCE, 0.0)))
        metadata = self._metadata or create_notes_metadata()
        try:
            os.makedirs(cfg.path.track_notes, exist_ok=True)
            with atomic_write(notes_path(track), newline="", raise_error=True) as file:
                write_csv_notes(file, HEADER_TRACK_NOTES, notes, metadata, track)
        except OSError as error:
            logger.error("LAP VIEWER: unable to save track notes of %s: %s", track, error)
            self._page.set_status(trm(f"Unable to save track notes: {error.strerror or error}"))
            return False
        self._notes, self._metadata = notes, metadata
        self._time = file_time(notes_path(track))
        self.place()
        return True
