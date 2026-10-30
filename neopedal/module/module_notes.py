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
Notes module
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from .. import calculation as calc
from .. import realtime_state
from ..api_control import api
from ..const_file import FileExt
from ..module_info import NotesData, minfo
from ..userfile.track_notes import (
    COLUMN_DISTANCE,
    COLUMN_TAGS,
    HEADER_PACE_NOTES,
    HEADER_TRACK_NOTES,
    TAG_PITNOTES,
    load_notes_file,
    parse_csv_notes_only,
)
from ..validator import generator_init, is_network_path
from ._base import WAIT_STATE_CHANGE, DataModule, derived_stamp

logger = logging.getLogger(__name__)


class Realtime(DataModule):
    """Notes data"""

    WAKE_ON_DERIVED = True  # stamp includes delta module position
    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        _event_wait = self.wait_update  # also wakes on new game data
        reset = False
        vehicle_resets = None
        update_interval = self.idle_interval
        last_stamp: tuple = ()  # game data stamp of last update

        userpath_pace_notes = self.cfg.path.pace_notes
        userpath_track_notes = self.cfg.path.track_notes
        output_pacenotes_out = minfo.pacenotes.out
        output_tracknotes_out = minfo.tracknotes.out
        output_pacenotes_pit = minfo.pacenotes.pit
        output_tracknotes_pit = minfo.tracknotes.pit

        setting_playback = self.cfg.user.setting["pace_notes_playback"]

        while not _event_wait(update_interval):
            if realtime_state.active:

                if not reset:
                    reset = True
                    update_interval = self.active_interval
                    last_stamp = ()  # never skip first tick

                # Skip while game data not updated since last tick
                stamp = derived_stamp(minfo.delta)  # pace notes follow delta module position
                if last_stamp == stamp:
                    continue
                last_stamp = stamp

                # Reset
                if vehicle_resets != realtime_state.resets:
                    # Delay reset until driving
                    if not realtime_state.active:
                        continue
                    vehicle_resets = realtime_state.resets

                    output_pacenotes_out.reset()
                    output_pacenotes_pit.reset()
                    output_tracknotes_out.reset()
                    output_tracknotes_pit.reset()
                    track_name = api.read.session.track_name()
                    track_length = api.read.lap.track_length()

                    # Load pace notes
                    pace_notes = load_pace_notes_file(
                        config=setting_playback,
                        filepath=userpath_pace_notes,
                        filename=track_name,
                        table_header=HEADER_PACE_NOTES,
                        parser=parse_csv_notes_only,
                        extension=FileExt.TPPN,
                    )
                    gen_pacenotes_out = notes_selector(
                        output=output_pacenotes_out,
                        dataset=filter_notes(pace_notes),
                    )
                    gen_pacenotes_pit = notes_selector(
                        output=output_pacenotes_pit,
                        dataset=filter_tags(pace_notes, TAG_PITNOTES),
                    )

                    # Load track notes
                    track_notes = load_notes_file(
                        filepath=userpath_track_notes,
                        filename=track_name,
                        table_header=HEADER_TRACK_NOTES,
                        parser=parse_csv_notes_only,
                        extension=FileExt.TPTN,
                    )
                    gen_tracknotes_out = notes_selector(
                        output=output_tracknotes_out,
                        dataset=filter_notes(track_notes),
                    )
                    gen_tracknotes_pit = notes_selector(
                        output=output_tracknotes_pit,
                        dataset=filter_tags(track_notes, TAG_PITNOTES),
                    )

                # Update position
                pos_synced = minfo.delta.lapDistance
                pos_offset = offset_position(pos_synced, setting_playback["pace_notes_global_offset"], track_length)

                # Update pace notes
                if gen_pacenotes_out:
                    gen_pacenotes_out.send(pos_offset)
                if gen_pacenotes_pit:
                    gen_pacenotes_pit.send(pos_offset)

                # Update track notes
                if gen_tracknotes_out:
                    gen_tracknotes_out.send(pos_synced)
                if gen_tracknotes_pit:
                    gen_tracknotes_pit.send(pos_synced)

            else:
                if reset:
                    reset = False
                    update_interval = WAIT_STATE_CHANGE  # idle until activity changes


def offset_position(position: float, offset: float, track_length: float) -> float:
    """Position with playback offset, wrapped into lap (notes past finish line played on time)"""
    position += offset
    if track_length > 0:
        return position % track_length
    return position


def load_pace_notes_file(
    config: dict, filepath: str, filename: str,
    table_header: tuple, parser: Callable, extension: str):
    """Load pace notes, file of preset never on a network path (shared preset: opening it sends the Windows
    sign-in hash to the share host)"""
    if config["enable_manual_file_selector"]:
        filepath = ""
        filename = config["pace_notes_file_name"]
        extension = ""
        if is_network_path(filename):
            logger.warning("NOTES: pace notes file on network path not loaded: %s", filename)
            return None
    return load_notes_file(
        filepath=filepath,
        filename=filename,
        table_header=table_header,
        parser=parser,
        extension=extension,
    )


@generator_init
def notes_selector(output: NotesData, dataset: tuple[Mapping, ...]):
    """Notes selector

    Args:
        output: module info.
        dataset: list of notes.
    """
    if not dataset:
        return

    last_index = -99999  # make sure initial index is different
    next_index = 0  # next note line index
    pos_reference = reference_position(dataset)
    end_index = len(pos_reference) - 1  # end note line index
    pos_final = pos_reference[-1] if pos_reference else 0.0  # final reference position
    output.reset()  # initial reset before updating

    while True:
        pos_curr = yield
        curr_index = calc.binary_search_lower(pos_reference, pos_curr, 0, end_index)

        if last_index == curr_index:
            continue

        last_index = curr_index
        next_index = (curr_index + 1) * (pos_curr < pos_final)

        if curr_index < 0:  # before first note: last note of lap before (only note: same pass, same index)
            curr_index = output.currentIndex if end_index == 0 and output.currentNote else end_index
        elif end_index == 0 and output.currentNote:
            # Only note passed again (next lap): index alternates (0, -1), so readers keyed on index (overlay
            # display duration, audio playback) take it as a new note, as with notes in between
            curr_index = -1 - output.currentIndex

        output.currentIndex = curr_index
        output.currentNote = dataset[curr_index]
        output.nextIndex = next_index
        output.nextNote = dataset[next_index]


def filter_notes(dataset: list[Mapping]) -> tuple[Mapping, ...]:
    """Filter notes without tags"""
    if not dataset:
        return ()
    return tuple(_note for _note in dataset if not _note.get(COLUMN_TAGS))


def filter_tags(dataset: list[Mapping], tag_name: str) -> tuple[Mapping, ...]:
    """Filter notes with specific tag"""
    if not dataset:
        return ()
    return tuple(_note for _note in dataset if tag_name in _note.get(COLUMN_TAGS, ""))


def reference_position(dataset: tuple[Mapping, ...]) -> tuple[float, ...]:
    """Reference notes position list"""
    if not dataset:
        return ()
    return tuple(_note[COLUMN_DISTANCE] for _note in dataset)
