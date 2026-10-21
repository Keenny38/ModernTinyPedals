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
Lap viewer lap actions (mixin of LapViewerBackend): lap list context menu (keep, note, delete & undo),
recently deleted laps (trash folder), added laps (other folders, MoTeC logs, imported laps library)
"""

from __future__ import annotations

import html
import logging
import os
import shutil
import time
from collections.abc import Sequence
from contextlib import suppress

from PySide6.QtCore import (
    Slot,
)

from ...i18n import tr, trm
from ...userfile.lap_cache import (
    remove_cached_lap,
)
from ...userfile.lap_library import is_foreign
from ...userfile.lap_marks import remove_marks, restore_marks, set_mark, set_marks
from ...userfile.telemetry_lap import (
    LapFile,
    is_valid_name,
    lap_number_of,
    lap_stem,
    lap_time_of,
    lap_timestamp_of,
    list_laps,
    list_tracks,
)
from .._common import TextInputDialog
from ..lap_viewer import (
    LapEntry,
    format_laptime,
    lap_label,
)
from .formatting import day_month_minutes, file_stamp
from .lap_base import (
    BackendBase,
)

logger = logging.getLogger(__name__)

TRASH_FOLDER = ".trash"  # deleted laps, in telemetry folder (hidden: not a track), restored by undo
TRASH_DAYS = 30  # deleted laps kept in trash folder
UNDO_DEPTH = 20  # deletions undone one after another (older ones restored from Recently Deleted)


def trash_batch_time(name: str) -> float:
    """Time trash batch folder was made (folder name), 0 if not a batch folder"""
    try:
        return time.mktime(time.strptime(name, "%Y-%m-%d %H-%M-%S"))
    except (ValueError, OverflowError):
        return 0.0


def purge_trash(folder: str, days: int = TRASH_DAYS) -> int:
    """Remove deleted laps older than days from trash, returns batch folders removed"""
    root = os.path.join(folder, TRASH_FOLDER)
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    removed = 0
    limit = time.time() - days * 86400
    for name in names:
        made = trash_batch_time(name)
        if 0 < made < limit:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
            removed += 1
    return removed


def list_trash(folder: str, days: int = TRASH_DAYS) -> list[tuple[float, str, str]]:
    """Laps in trash (thread job): deletion time, trash path & lap path to restore, newest deletion first; laps
    purge_trash removes (older than days) left out"""
    root = os.path.join(folder, TRASH_FOLDER)
    try:
        batches = os.listdir(root)
    except OSError:
        return []
    limit = time.time() - days * 86400
    laps: list[tuple[float, str, str]] = []
    for batch in batches:
        made = trash_batch_time(batch)
        if made < limit or made <= 0:
            continue
        try:
            tracks = os.listdir(os.path.join(root, batch))
        except OSError:  # not a folder, or removed meanwhile
            continue
        for track in tracks:
            try:
                names = os.listdir(os.path.join(root, batch, track))
            except OSError:
                continue
            laps.extend((made, os.path.join(root, batch, track, name), os.path.join(folder, track, name))
                        for name in names)
    laps.sort(key=lambda lap: (lap[0], os.path.basename(lap[2])), reverse=True)
    return laps


def path_key(path: str) -> str:
    """Lap file path compared with others: listed laps use mixed slashes & relative telemetry folder, picked files
    absolute paths"""
    return os.path.normcase(os.path.abspath(path))


class LapActions(BackendBase):
    """Lap actions, trash & added laps of lap viewer page"""

    # Lap actions (lap list context menu)
    @Slot(str, result=dict)
    def lapActions(self, path: str) -> dict:
        """Actions available for lap: recorded laps of track can be kept, noted, deleted & used as delta best"""
        recorded = path in {entry.file.path for entry in self.entries}
        return {"recorded": recorded, "kept": bool(self.lap_marks(path).get("kept")) if recorded else False}

    @Slot(str, result=bool)
    def isCompared(self, path: str) -> bool:
        """Lap shown & not reference lap (setup differences with reference lap)"""
        return path != self.reference_key and any(lap.key == path for lap in self.data.laps)

    @Slot(str, bool)
    def keepLap(self, path: str, keep: bool):
        """Kept lap is never removed by recorder (oldest laps over limit are)"""
        set_mark(path, kept=keep)
        self.marks_changed(path)

    def marks_changed(self, path: str = ""):
        """Lap kept or noted (any lap if no path): its row changed in place, list built again while searching (marks
        are searched)"""
        if path:
            self._marks.pop(os.path.dirname(path), None)
        else:
            self._marks.clear()
        if self._filter:
            self.fill_list()
            self.update_list_state(self.data.laps)
            return
        entries = {entry.file.path: entry for entry in self.entries}
        self.lap_model.update_rows(lambda row: self.mark_values(entries[row["path"]], row.get("vehicle", ""))
                                   if row["path"] in entries and path in ("", row["path"]) else {})

    @Slot(str)
    def editNote(self, path: str):
        """Free text note of lap, shown in lap list"""
        def saving(text: str) -> bool:
            set_mark(path, note=text)
            self.marks_changed(path)
            return True

        TextInputDialog(self._window, tr("Lap Note"), tr("Note for this lap (empty to remove):"), saving,
                        str(self.lap_marks(path).get("note", ""))).show()

    @Slot(str)
    def deleteLap(self, path: str):
        """Move recorded lap file to trash (undo restores it)"""
        self.deleteLaps([path])

    @Slot(list)
    def deleteLaps(self, paths: list):
        """Move recorded laps to trash, confirmation asked for several laps (undo restores them)"""
        recorded = {entry.file.path for entry in self.entries}
        paths = [str(path) for path in paths if str(path) in recorded]
        if not paths:
            return
        if len(paths) > 1:
            from .._common import confirm_action

            if not confirm_action(self._window, tr("Delete Laps"), trm(f"Move {len(paths)} laps to trash?"),
                                  tr("Move to Trash")):
                return
        joined = False  # laps being read join this deletion once loaded (undone together)
        if self._loader is not None:  # file read by background loading: deleted once loaded
            reading = [path for path in paths if path in self._loaded_paths]
            if reading and not self._pending_delete:
                joined, self._pending_batch = True, None
            self._pending_delete.extend(path for path in reading if path not in self._pending_delete)
            paths = [path for path in paths if path not in self._loaded_paths]
        if paths and self.apply_delete(paths) and joined:
            self._pending_batch = self._undo[-1]

    def trash_folder(self) -> str:
        """New trash batch folder (deletion time)"""
        return os.path.join(self.folder, TRASH_FOLDER, file_stamp())

    def apply_delete(self, paths: list[str], pending: bool = False) -> bool:
        """Move laps to trash, forget their caches, deletion put on undo stack (pending: laps deleted while being read,
        restored with laps of same deletion), False if none moved"""
        batch = self.trash_folder()
        moved = []
        for path in paths:
            target = os.path.join(batch, os.path.basename(os.path.dirname(path)), os.path.basename(path))
            mark = dict(self.lap_marks(path))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(path, target)
            except OSError as error:
                logger.error("LAP VIEWER: unable to delete %s: %s", path, error)
                self.set_status(trm(f"Unable to delete lap: {error}"))
                continue
            remove_cached_lap(self.folder, path)
            with suppress(OSError):
                os.remove(os.path.join(self.limits_parts_folder(os.path.basename(os.path.dirname(path))),
                                       os.path.basename(path) + ".bin"))
            moved.append((path, target, mark, path in self.checked, path == self.reference_key))
        if not moved:
            return False
        remove_marks([item[0] for item in moved])  # marks file of each folder saved once
        gone = {item[0] for item in moved}
        for path in gone:
            self._marks.pop(os.path.dirname(path), None)
            self._lap_cache.pop(path, None)
        self.entries = [entry for entry in self.entries if entry.file.path not in gone]
        self.checked -= gone
        if self.reference_key in gone:
            self.reference_key = ""
        deletion = self._pending_batch if pending else None
        if deletion is not None and any(item is deletion for item in self._undo):
            deletion.extend(moved)
        else:
            deletion = moved
            self._undo.append(moved)
            del self._undo[:-UNDO_DEPTH]  # older deletions stay in trash (Recently Deleted) until purged
        if pending:
            self._pending_batch = None
        self.undoChanged.emit()
        self.set_status(trm(f"{len(deletion)} lap(s) moved to trash"))
        self.fill_list()
        self.load_laps()
        self.lapsTrashed.emit(len(deletion), lap_label(os.path.basename(deletion[0][0])) if len(deletion) == 1 else "")
        return True

    @Slot()
    def undoDelete(self):
        """Restore last deleted laps from trash (marks, check state & reference too), deletion before it next"""
        if not self._undo:
            return
        items = self._undo.pop()
        self.undoChanged.emit()
        self.restore_laps(items)
        if self._trash_rows:
            self.read_trash()

    def restore_laps(self, items: Sequence[tuple[str, str, dict, bool, bool]]) -> list[str]:
        """Laps moved back from trash (marks, check state & reference too), lap list & charts updated, paths restored"""
        restored = []
        marks: dict[str, dict] = {}
        for path, target, mark, checked, reference in items:
            if os.path.exists(path):
                continue
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                os.replace(target, path)
            except OSError as error:
                logger.error("LAP VIEWER: unable to restore %s: %s", path, error)
                continue
            if mark.get("kept") or mark.get("note"):
                marks[path] = mark
            restored.append(path)
            if checked:
                self.checked.add(path)
            if reference:
                self.reference_key = path
            for folder in (os.path.dirname(target), os.path.dirname(os.path.dirname(target))):
                with suppress(OSError):  # trash track & batch folders removed once empty (never above)
                    os.rmdir(folder)
        if marks:  # marks file of each folder written once
            restore_marks(marks)
        self._marks.clear()
        if self._track:
            laps = list_laps(self.folder, self._track)
            self.entries = [LapEntry(lap, info) for lap, info in zip(laps, self.track_infos(self._track, laps))]
        self.set_status(trm(f"{len(restored)} lap(s) restored"))
        self.fill_list()
        self.load_laps()
        return restored

    # Recently deleted laps (trash folder, kept TRASH_DAYS days)
    @Slot()
    def openTrash(self):
        """Recently deleted laps read in background (Recently Deleted dialog)"""
        self._trash_loading = True
        self.trashChanged.emit()
        self.read_trash()

    def read_trash(self):
        folder = self.folder
        self.run_job("trash", lambda: list_trash(folder), self.trash_read)

    def trash_read(self, laps: list[tuple[float, str, str]] | None):
        self._trash_loading = False
        self._trash_rows = [self.trash_row(*lap) for lap in laps or ()]
        self.trashChanged.emit()

    def trash_row(self, deleted: float, trashed: str, path: str) -> dict:
        name = os.path.basename(path)
        number = lap_number_of(name)
        recorded = lap_timestamp_of(name)
        return {
            "key": trashed, "track": os.path.basename(os.path.dirname(path)),
            "title": trm(f"Lap {number}") if number else lap_stem(name),
            "time": format_laptime(lap_time_of(name)), "recorded": day_month_minutes(recorded) if recorded else "",
            "deleted": day_month_minutes(deleted),
        }

    @Slot(str)
    def restoreTrashed(self, key: str):
        """Lap of trash restored to its track folder (marks, check state & reference too if deleted this session)"""
        root = os.path.normcase(os.path.abspath(os.path.join(self.folder, TRASH_FOLDER)))
        if os.path.dirname(os.path.dirname(os.path.dirname(os.path.normcase(os.path.abspath(key))))) != root:
            return  # not a lap of trash
        target = os.path.normcase(os.path.abspath(key))
        item = None
        for batch in self._undo:
            item = next((entry for entry in batch if os.path.normcase(os.path.abspath(entry[1])) == target), None)
            if item is not None:
                batch.remove(item)
                break
        self._undo = [batch for batch in self._undo if batch]
        self.undoChanged.emit()
        if item is None:  # deleted before this session: lap only
            item = (os.path.join(self.folder, os.path.basename(os.path.dirname(key)), os.path.basename(key)), key, {},
                    False, False)
        if not self.restore_laps([item]):
            self.set_status(trm(f"Unable to restore lap: {html.escape(os.path.basename(key))}"))
        self.read_trash()

    @Slot(bool)
    def keepChecked(self, keep: bool):
        """Keep (or stop keeping) every checked recorded lap"""
        recorded = {entry.file.path for entry in self.entries}
        paths = [path for path in self.ordered_checked() if path in recorded]
        if paths:
            set_marks(paths, kept=keep)  # marks file of each folder saved once
            self.marks_changed()

    @Slot()
    def deleteChecked(self):
        """Move every checked recorded lap to trash"""
        self.deleteLaps(self.ordered_checked())

    def session_paths(self, key: str) -> list[str]:
        """Laps listed in session (lap list order)"""
        return [row["path"] for row in self.lap_rows() if row["session"] == key]

    @Slot(str, str)
    def sessionAction(self, key: str, action: str):
        """Session header menu: show, hide, keep, delete laps listed in session"""
        paths = self.session_paths(key)
        if not paths:
            return
        recorded = {entry.file.path for entry in self.entries}
        if action == "show":
            self.checked.update(paths)
            self.load_laps()
        elif action == "hide":
            self.checked.difference_update(path for path in paths if path != self.reference_key)
            self.load_laps()
        elif action in ("keep", "unkeep"):
            set_marks([path for path in paths if path in recorded], kept=action == "keep")
            self.marks_changed()
        elif action == "delete":
            self.deleteLaps(paths)

    # Added laps: other folders, MoTeC logs (see lap_export), imported laps library
    def add_external(self, lap_paths: list[str], reference_from: list[str] | None = None,
                     checked: list[str] | None = None):
        """Show laps from other folders (checked laps only if given, else every lap given, listed before or not),
        fastest of reference_from laps set as reference; laps of another driver's folder marked foreign, laps of shown
        track listed once (as track laps)

        Laps of one circuit only are ever shown: laps of shown circuit kept, others refused (told in status line).
        Laps given all driven on another circuit: viewer switches to it (see switch_circuit), laps of the circuit of
        the fastest reference_from lap (else first lap) kept.
        """
        listed = {path_key(entry.file.path): entry.file.path for entry in self.all_entries()}
        main = self.main_circuit() if self.entries or self.reference_key in self.checked else None
        new: dict[str, dict] = {}  # lap infos of laps not listed yet
        for lap_path in lap_paths:
            path = os.path.normpath(lap_path)
            if path_key(lap_path) not in listed and path not in new:
                new[path] = self.lap_info(path)
        kept = [path for path in new if main is None or not self.other_circuit(main, new[path], path)]
        listed_given = any(path_key(path) in listed for path in lap_paths)  # laps of shown circuit given again
        switching = main is not None and bool(new) and not kept and not listed_given
        if new and (switching or main is None):  # laps of one circuit kept: circuit of lead lap
            lead = self.lead_lap(list(new), reference_from, checked)
            kept = [path for path in new if not self.other_circuit((new[lead], lead), new[path], path)]
        rejected = {path: info for path, info in new.items() if path not in kept}
        added = []
        for path in kept:
            name = os.path.basename(path)
            self.external.append(LapEntry(
                LapFile(name, path, is_valid_name(name), lap_time_of(name)), new[path], external=True,
                foreign=is_foreign(path)))
            listed[path_key(path)] = path
            added.append(path)
        refused = ""
        if rejected:
            refused = trm(f"Laps from another circuit, not added: "
                          f"{', '.join(self.circuit_names(list(rejected), rejected))}")
            self.set_status(refused)
            lap_paths = [path for path in lap_paths if os.path.normpath(path) not in rejected]
            reference_from = [path for path in reference_from or () if os.path.normpath(path) not in rejected]
            checked = None if checked is None else [path for path in checked if os.path.normpath(path) not in rejected]
        shown = [listed.get(path_key(path), "") for path in (lap_paths if checked is None else checked)]
        shown = [path for path in shown if path and (switching or path not in self.checked)]
        reference = ""
        if reference_from:  # compare own laps with fastest imported lap
            fastest = min(reference_from, key=lambda path: lap_time_of(os.path.basename(path)) or float("inf"))
            reference = listed.get(path_key(fastest), os.path.normpath(fastest))
        if switching:
            self.switch_circuit(added, shown, reference or (shown or added)[0], refused)
            return
        self.checked.update(shown)
        if reference:
            self.reference_key = self._chosen_reference = reference
        if main is not None and added:  # imported laps checked against shown circuit once loaded
            self._added_batch = (added, [path for path in added if path in self.checked],
                                 reference if reference in added else "")
        if added or shown or reference_from:
            self.fill_list()
            self.load_laps()

    @staticmethod
    def lead_lap(paths: list[str], reference_from: list[str] | None, checked: list[str] | None) -> str:
        """Lap whose circuit is kept among added laps of several circuits: fastest reference_from lap, else first
        checked lap, else first lap"""
        fastest = sorted((os.path.normpath(path) for path in reference_from or ()
                          if os.path.normpath(path) in paths),
                         key=lambda path: lap_time_of(os.path.basename(path)) or float("inf"))
        first = [os.path.normpath(path) for path in checked or () if os.path.normpath(path) in paths]
        return (fastest or first or paths)[0]

    def track_folder_of(self, path: str) -> str:
        """Track folder of telemetry folder lap is in ("<track> - <class>"), empty if none (imported log, other
        folder)"""
        folder = os.path.dirname(path)
        name = os.path.basename(folder)
        if not name or name.startswith(".") or path_key(os.path.dirname(folder)) != path_key(self.folder):
            return ""
        if name not in self._tracks and os.path.isdir(folder):  # recorded since list was read
            self._tracks = list_tracks(self.folder)
        return name if name in self._tracks else ""

    def switch_circuit(self, paths: list[str], shown: list[str], reference: str, refused: str = ""):
        """Laps of another circuit opened (file, library, MoTeC log, folder): viewer shows that circuit instead,
        laps of former circuit no longer listed nor compared. Track folder of reference lap shown if it is one (its
        laps listed, notes, pins, track limits, official circuit), else opened laps alone; track picker goes back."""
        keep = set(paths)
        self.external = [entry for entry in self.external if entry.file.path in keep]
        infos = {entry.file.path: entry.info for entry in self.external}
        self.checked = (set(shown) | {reference}) & keep if reference else set(shown) & keep
        self.reference_key = self._chosen_reference = reference
        self._added_batch = self._pending_switch = None
        track = self.track_folder_of(reference)
        self._switch_to = (track, set(self.checked), reference)
        plural = "s" if len(paths) > 1 else ""
        message = trm(f"Showing {', '.join(self.circuit_names([reference], infos))}: "
                      f"lap{plural} from another circuit")
        self.set_status(f"{message} · {refused}" if refused else message)
        self.load_track(track)

    def show_track_laps(self, reference: str, compared: str = "") -> bool:
        """Laps of a track folder shown alone, reference lap first (Home page debrief): track folder of reference
        lap shown, False if it is not one"""
        track = self.track_folder_of(reference)
        if not track:
            return False
        listed = {path_key(lap.path): lap.path for lap in list_laps(self.folder, track)}  # paths as listed
        reference = listed.get(path_key(reference), "")
        if not reference:
            return False
        shown = {reference, *(path for path in (listed.get(path_key(compared), ""),) if path)}
        self._added_batch = self._pending_switch = None
        self._switch_to = (track, shown, reference)
        self._chosen_reference = reference
        self.load_track(track)
        return True

    @Slot()
    def openLibrary(self):
        from ..lap_library import LapLibrary

        LapLibrary(self._window, self.folder, self.add_from_library, self.library_changed).show()

    def add_from_library(self, paths: list[str]):
        """Laps picked in library shown & checked, fastest one as reference"""
        self.add_external(paths, paths)

    def library_changed(self, moved: dict[str, str]):
        """Imported laps renamed (new path) or deleted (empty path) in library"""
        moved = {os.path.normpath(old): os.path.normpath(new) if new else "" for old, new in moved.items()}
        if not any(entry.file.path in moved for entry in self.external):
            return
        self.checked = {moved.get(path, path) for path in self.checked} - {""}
        external = []
        for entry in self.external:
            path = moved.get(entry.file.path, entry.file.path)
            if path:
                external.append(entry._replace(file=entry.file._replace(path=path)))
            self._lap_cache.pop(entry.file.path, None)
        self.external = external
        if self.reference_key in moved:
            self.reference_key = moved[self.reference_key]
        self._chosen_reference = moved.get(self._chosen_reference, self._chosen_reference)
        self.fill_list()
        self.load_laps()
