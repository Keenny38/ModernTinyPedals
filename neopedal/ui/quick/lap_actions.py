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
import weakref
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import (
    Slot,
)

from ...i18n import tr, trm
from ...userfile.lap_cache import (
    remove_cached_lap,
)
from ...userfile.lap_library import FOREIGN_MARK, Deletion, is_foreign
from ...userfile.lap_marks import remove_marks, restore_marks, set_mark, set_marks
from ...userfile.telemetry_lap import (
    IMPORT_FOLDER,
    LapFile,
    is_lap_file,
    is_valid_name,
    lap_number_of,
    lap_stem,
    lap_time_of,
    lap_timestamp_of,
    list_laps,
    list_tracks,
)
from ..lap_viewer import (
    LapEntry,
    format_laptime,
    lap_label,
)
from . import dialogs
from .formatting import day_month_minutes, file_stamp
from .lap_base import (
    BackendBase,
)

logger = logging.getLogger(__name__)

TRASH_FOLDER = ".trash"  # deleted laps, in telemetry folder (hidden: not a track), restored by undo
TRASH_DAYS = 30  # deleted laps kept in trash folder
UNDO_DEPTH = 20  # deletions undone one after another (older ones restored from Recently Deleted)
FILES_BACKGROUND = 8  # more lap files moved (trash, restore) at once than this: moved in a thread job (a session or
# every checked lap deleted: tens of os.replace, each slow behind an antivirus or on a network share)


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
            # Imported laps (library): .imported/<log>/<lap> in batch, put back in their log of imported laps
            parts = [(track, group) for group in subfolders(os.path.join(root, batch, track))] \
                if track == IMPORT_FOLDER else [(track,)]
            for part in parts:
                try:
                    names = os.listdir(os.path.join(root, batch, *part))
                except OSError:
                    continue
                laps.extend((made, os.path.join(root, batch, *part, name), os.path.join(folder, *part, name))
                            for name in names if len(part) == 1 or is_lap_file(name))
    laps.sort(key=lambda lap: (lap[0], os.path.basename(lap[2])), reverse=True)
    return laps


def subfolders(folder: str) -> list[str]:
    """Names of the folders in folder, none if unreadable"""
    try:
        return [entry.name for entry in os.scandir(folder) if entry.is_dir()]
    except OSError:
        return []


def trash_origin(folder: str, trashed: str) -> str:
    """Place a lap of trash goes back to (track folder, or log of imported laps), empty if trashed is not a lap of
    the trash of telemetry folder"""
    root = os.path.abspath(os.path.join(folder, TRASH_FOLDER))
    path = os.path.abspath(trashed)
    try:
        parts = os.path.relpath(path, root).split(os.sep)
    except ValueError:  # other drive
        return ""
    if (len(parts) == 3 and not parts[1].startswith(".")) or (len(parts) == 4 and parts[1] == IMPORT_FOLDER):
        if trash_batch_time(parts[0]) > 0 and ".." not in parts:
            return os.path.join(folder, *parts[1:])
    return ""


def is_imported(folder: str, path: str) -> bool:
    """Whether lap path is a lap of imported laps library of telemetry folder"""
    return path_key(os.path.dirname(os.path.dirname(path))) == path_key(os.path.join(folder, IMPORT_FOLDER))


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

        dialogs.ask_text(self._window, tr("Lap Note"), tr("Note for this lap (empty to remove):"), saving,
                         str(self.lap_marks(path).get("note", "")))

    @Slot(str)
    def deleteLap(self, path: str):
        """Move recorded lap file to trash (undo restores it)"""
        self.deleteLaps([path])

    @Slot(list)
    def deleteLaps(self, paths: list):
        """Move recorded laps to trash without confirmation, however many: undo restores them (toast, Ctrl+Z)"""
        recorded = {entry.file.path for entry in self.entries}
        paths = [str(path) for path in paths if str(path) in recorded]
        if paths:
            self.trash_laps(paths)

    def trash_laps(self, paths: list[str]):
        """Recorded laps moved to trash, laps being read moved once loaded"""
        recorded = {entry.file.path for entry in self.entries}
        paths = [path for path in paths if path in recorded]  # list changed while asked
        if not paths:
            return
        joined = False  # laps being read join this deletion once loaded (undone together)
        if self._loader is not None:  # file read by background loading: deleted once loaded
            reading = [path for path in paths if path in self._loaded_paths]
            if reading and not self._pending_delete:
                joined, self._pending_batch = True, None
            self._pending_delete.extend(path for path in reading if path not in self._pending_delete)
            paths = [path for path in paths if path not in self._loaded_paths]
        if paths:
            self.apply_delete(paths, joined=joined)

    def trash_folder(self) -> str:
        """New trash batch folder (deletion time)"""
        return os.path.join(self.folder, TRASH_FOLDER, file_stamp())

    def start_file_action(self, work: Callable[[], Any], done: Callable[[Any], Any]):
        """Lap files moved on a thread (page busy meanwhile, see is_loading), done(result) on the page thread (None
        if the job failed)"""
        self._file_actions += 1
        self.notify_status()  # busy indicator

        def finished(result):
            self._file_actions -= 1
            self.notify_status()
            done(result)

        self.run_job("lap files", work, finished)

    @staticmethod
    def move_to_trash(folder: str, moves: list[tuple[str, str, str]]) -> tuple[list[tuple[str, str]], list[str]]:
        """Lap files moved to trash (thread job or page thread): (lap path, trash path, track limits part) of each,
        caches of laps moved forgotten, marks file of each folder saved once; (moved (path, target), errors)"""
        moved: list[tuple[str, str]] = []
        errors: list[str] = []
        for path, target, part in moves:
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(path, target)
            except OSError as error:
                logger.error("LAP VIEWER: unable to delete %s: %s", path, error)
                errors.append(str(error))
                continue
            remove_cached_lap(folder, path)
            with suppress(OSError):
                os.remove(part)
            moved.append((path, target))
        if moved:
            remove_marks([path for path, _ in moved])
        return moved, errors

    def apply_delete(self, paths: list[str], pending: bool = False, joined: bool = False) -> bool:
        """Move laps to trash, forget their caches, deletion put on undo stack (pending: laps deleted while being read,
        restored with laps of same deletion; joined: laps being read join this deletion once loaded), False if none
        moved. Many laps: files moved on a thread, state applied once moved (True returned)."""
        batch = self.trash_folder()
        marks = {path: dict(self.lap_marks(path)) for path in paths}
        moves = [(path, os.path.join(batch, os.path.basename(os.path.dirname(path)), os.path.basename(path)),
                  os.path.join(self.limits_parts_folder(os.path.basename(os.path.dirname(path))),
                               os.path.basename(path) + ".bin")) for path in paths]
        if len(moves) > FILES_BACKGROUND:
            folder = self.folder
            self.start_file_action(lambda: self.move_to_trash(folder, moves),
                                   lambda result: self.deleted(result, marks, pending, joined))
            return True
        return self.deleted(self.move_to_trash(self.folder, moves), marks, pending, joined)

    def deleted(self, result: Any, marks: dict[str, dict], pending: bool, joined: bool) -> bool:
        """Laps moved to trash (see move_to_trash): list, charts & undo stack updated, errors told, False if none"""
        if not isinstance(result, tuple):  # job failed
            self.page_toast(tr("Unable to delete laps"), "error")
            return False
        for error in result[1]:
            self.page_toast(trm(f"Unable to delete lap: {html.escape(error)}"), "error")
        moved = [(path, target, marks.get(path, {}), path in self.checked, path == self.reference_key)
                 for path, target in result[0]]
        if not moved:
            return False
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
        elif joined:  # laps being read join this deletion once loaded
            self._pending_batch = deletion
        self.undoChanged.emit()
        self.fill_list()
        self.load_laps()
        self.trashed(len(deletion), lap_label(os.path.basename(deletion[0][0])) if len(deletion) == 1 else "")
        return True

    def trashed(self, count: int, label: str):
        """Laps moved to trash, told once: lap library panel open, its own toast (the page toast is under its
        scrim), else page toast naming the lap with Undo (Ctrl+Z too). Never the status line as well."""
        self.lapsTrashed.emit(count, label)
        if getattr(getattr(self, "_library", None), "_shown", False):  # ImportedLaps panel open
            return
        text = (tr("%1 moved to trash").replace("%1", f"<b>{html.escape(label)}</b>") if count == 1 and label
                else tr("%1 laps moved to trash").replace("%1", str(count)))
        page = weakref.ref(self)
        self.page_toast(text, action_text=tr("Undo"),
                        action=lambda: (backend := page()) is not None and backend.undoDelete())

    def page_toast(self, text: str, level: str = "success", action_text: str = "", action=None):
        """Toast of this page when shown (never the toast of another page): results of lap actions, errors
        (level "error"); the status line is for progress only"""
        bridge = dialogs.page_bridge(self._window)
        if bridge is not None:
            bridge.show_toast(text, level, action_text=action_text, action=action)

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

    @staticmethod
    def move_from_trash(folder: str, items: Sequence[tuple[str, str, dict, bool, bool]]) -> list[str]:
        """Lap files of items (see restore_laps) moved back from trash (thread job or page thread), marks file of
        each folder written once, empty trash folders removed; lap paths restored"""
        restored = []
        marks: dict[str, dict] = {}
        trash = path_key(os.path.join(folder, TRASH_FOLDER))
        for path, target, mark, _checked, _reference in items:
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
            if is_imported(folder, path):
                # Mark of laps of another driver's folder, trashed with the last lap of its log
                mark_target = os.path.join(os.path.dirname(target), FOREIGN_MARK)
                mark_path = os.path.join(os.path.dirname(path), FOREIGN_MARK)
                if os.path.isfile(mark_target) and not os.path.exists(mark_path):
                    with suppress(OSError):
                        os.replace(mark_target, mark_path)
            batch = os.path.dirname(target)
            while path_key(batch).startswith(trash + os.sep):  # trash folders removed once empty (never above)
                with suppress(OSError):
                    os.rmdir(batch)
                batch = os.path.dirname(batch)
        if marks:  # marks file of each folder written once
            restore_marks(marks)
        return restored

    def restore_laps(self, items: Sequence[tuple[str, str, dict, bool, bool]]) -> list[str]:
        """Laps moved back from trash (marks, check state & reference too), lap list & charts updated, paths restored
        (many laps: files moved on a thread, state applied once moved, paths asked returned)"""
        if len(items) > FILES_BACKGROUND:
            folder = self.folder
            self.start_file_action(lambda: self.move_from_trash(folder, items),
                                   lambda result: self.restored(items, result if isinstance(result, list) else []))
            return [item[0] for item in items]
        return self.restored(items, self.move_from_trash(self.folder, items))

    def restored(self, items: Sequence[tuple[str, str, dict, bool, bool]], restored: list[str]) -> list[str]:
        """Laps moved back from trash (see move_from_trash): check state & reference back, list & charts updated"""
        imported: list[str] = []  # imported laps restored (library), shown again if they were
        shown: list[str] = []
        reference_from: list[str] = []
        back = set(restored)
        for path, _target, _mark, checked, reference in items:
            if path not in back:
                continue
            if is_imported(self.folder, path):
                imported.append(path)
                shown.extend([path] if checked or reference else [])
                reference_from.extend([path] if reference else [])
            else:
                if checked:
                    self.checked.add(path)
                if reference:
                    self.reference_key = path
        self._marks.clear()
        if self._track:
            laps = list_laps(self.folder, self._track)
            self.entries = [LapEntry(lap, info) for lap, info in zip(laps, self.track_infos(self._track, laps))]
        if restored:
            self.page_toast(trm(f"{len(restored)} lap(s) restored"))
        self.fill_list()
        self.load_laps()
        if imported:
            self._library.restored(imported)
        if shown:  # imported laps shown when deleted: shown again (reference too)
            self.add_external(shown, reference_from or None, checked=shown)
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
        self._trash_serial += 1
        serial = self._trash_serial
        self.run_job("trash", lambda: list_trash(folder), lambda laps: self.trash_read(laps, serial))

    def trash_read(self, laps: list[tuple[float, str, str]] | None, serial: int = 0):
        if serial and serial != self._trash_serial:  # older listing finished after a newer one
            return
        self._trash_loading = False
        self._trash_rows = [self.trash_row(*lap) for lap in laps or ()]
        self.trashChanged.emit()

    def trash_row(self, deleted: float, trashed: str, path: str) -> dict:
        name = os.path.basename(path)
        number = lap_number_of(name)
        recorded = lap_timestamp_of(name)
        place = os.path.basename(os.path.dirname(path))
        if is_imported(self.folder, path):  # lap of an imported log (library)
            place = f"{tr('Imported Laps')} · {place}"
        return {
            "key": trashed, "track": place,
            "title": trm(f"Lap {number}") if number else lap_stem(name),
            "time": format_laptime(lap_time_of(name)), "recorded": day_month_minutes(recorded) if recorded else "",
            "deleted": day_month_minutes(deleted),
        }

    @Slot(str)
    def restoreTrashed(self, key: str):
        """Lap of trash restored to its track folder (marks, check state & reference too if deleted this session)"""
        origin = trash_origin(self.folder, key)
        if not origin:
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
            item = (origin, key, {}, False, False)
        if not self.restore_laps([item]):
            self.page_toast(trm(f"Unable to restore lap: {html.escape(os.path.basename(key))}"), "error")
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
        """Imported laps library panel opened (LapLibraryPanel.qml, see lap_library_panel)"""
        self._library.openRequested.emit()

    def add_from_library(self, paths: list[str]):
        """Laps picked in library shown & checked, fastest one as reference"""
        self.add_external(paths, paths)

    def trash_imported(self, deletion: Deletion):
        """Imported laps moved to lap viewer trash by the library: one deletion of page undo (Ctrl+Z, toast) &
        Recently Deleted, shown ones dropped from charts (shown again by undo)"""
        laps = [(path, target) for path, target in deletion.trashed if is_lap_file(path)]
        if laps:
            self._undo.append([(path, target, {}, path in self.checked, path == self.reference_key)
                               for path, target in laps])
            del self._undo[:-UNDO_DEPTH]
            self.undoChanged.emit()
        if deletion.deleted:
            self.library_changed(dict.fromkeys(deletion.deleted, ""))
        if laps:
            self.trashed(len(laps), lap_label(os.path.basename(laps[0][0])) if len(laps) == 1 else "")
            if self._trash_rows:
                self.read_trash()

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
