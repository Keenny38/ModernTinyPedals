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
Game Replays page replay folder (mixin of GameReplaysBackend): replay files added, exported, renamed,
protected, moved to the recycle bin (in background, with progress), temporary files of the game cleaned up
"""

from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import Property, QUrl, Slot
from PySide6.QtWidgets import QFileDialog

from ...i18n import tr, trm
from ...process.game_info import GameReplay
from . import dialogs, last_folder, replay_files
from .replays_base import ReplaysBase
from .replays_common import OFFLINE, copy_reporter, size_text


class ReplaysFolder(ReplaysBase):
    """Replay folder of Game Replays page"""

    # Replay files
    @Property(bool, notify=ReplaysBase.filesChanged)
    def copying(self) -> bool:
        return self.request_copy.busy

    @Property(float, notify=ReplaysBase.copyProgressChanged)
    def copyProgress(self) -> float:
        """Replays being copied: 0 to 1"""
        return max(self.copy_progress, 0.0)

    @Property(bool, notify=ReplaysBase.filesChanged)
    def trashing(self) -> bool:
        """Files being moved to the recycle bin (in background)"""
        return self.request_trash.busy

    @Property(float, notify=ReplaysBase.trashProgressChanged)
    def trashProgress(self) -> float:
        """Files being moved to the recycle bin: 0 to 1"""
        return max(self.trash_progress, 0.0)

    @Property(str, notify=ReplaysBase.filesChanged)
    def copyKind(self) -> str:
        """add (to game folder) or export"""
        return self.copy_kind

    @Property(dict, notify=ReplaysBase.filesChanged)
    def folderInfo(self) -> dict:
        """Replays & temporary files of game folder: counts, sizes (texts), made again only once replays,
        temporary files or protected replays changed (lists are replaced, never changed in place)"""
        sources = (self.replays, self.temp, self.protected)
        cached = self._folder_info
        if cached is not None and all(new is old for new, old in zip(sources, cached[0])):
            return cached[1]
        info = {
            "replays": len(self.replays), "size": size_text(sum(replay.size for replay in self.replays)),
            "temp": len(self.temp), "tempSize": self.temp_size(), "protected": len(self.protected & {
                replay.name for replay in self.replays}),
        }
        self._folder_info = (sources, info)
        return info

    def set_copy_progress(self, progress: float):
        if progress != self.copy_progress:
            self.copy_progress = progress
            self.copyProgressChanged.emit()

    def set_trash_progress(self, progress: float):
        if progress != self.trash_progress:
            self.trash_progress = progress
            self.trashProgressChanged.emit()

    def update_files(self):
        """Temporary files of replay folder looked up again"""
        folder = self.replay_folder()
        self.temp = replay_files.temp_files(folder) if folder else []
        self.filesChanged.emit()

    @Slot()
    def addReplays(self):
        """Replay files chosen in a file dialog copied to replay folder of game"""
        if not self.replay_folder():
            self.notify(tr("Replay folder unknown: start LMU once so the page lists its replays"), True)
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self._window, tr("Add Replays"), last_folder.start_folder("replays_add"),
            f"{tr('LMU replays')} (*{replay_files.REPLAY_EXTENSION})")
        if paths:
            last_folder.remember("replays_add", paths[0])
            self.add_files(paths)

    @Slot(list)
    def addFiles(self, urls: list):
        """Replay files dropped on page (file urls) copied to replay folder of game"""
        self.add_files([(url if isinstance(url, QUrl) else QUrl(str(url))).toLocalFile() for url in urls])

    def add_files(self, paths: list[str]):
        folder = self.replay_folder()
        if not folder:
            self.notify(tr("Replay folder unknown: start LMU once so the page lists its replays"), True)
            return
        sources = [path for path in paths if replay_files.is_replay_file(path)]
        if not sources:
            self.notify(tr("No LMU replay file (.Vcr) to add"), True)
            return
        self.start_copy(sources, folder, "add")

    def start_copy(self, sources: list[str], folder: str, kind: str):
        if self.request_copy.busy:
            self.notify(tr("Replays are still being copied, try again once done"), True)
            return
        self.copy_progress, self.copy_kind = 0.0, kind
        self.copy_cancel = cancelled = threading.Event()
        progress = copy_reporter(self)
        self.request_copy.start(lambda: replay_files.copy_replays(sources, folder, progress, cancelled))
        self.filesChanged.emit()
        self.copyProgressChanged.emit()

    @Slot()
    def cancelCopy(self):
        self.copy_cancel.set()

    def copy_done(self, result: replay_files.CopyResult):
        self.copy_progress = -1.0
        self.filesChanged.emit()
        self.copyProgressChanged.emit()
        count = len(result.added)
        if result.cancelled:
            self.notify(trm(f"Copy cancelled, {count} replay(s) copied"), True)
        elif result.errors:
            self.notify(trm(f"Unable to copy: {'; '.join(result.errors)}"), True)
        elif self.copy_kind == "export":
            self.notify(trm(f"{count} replay(s) exported"))
        elif result.added:
            self.notify(trm(f"{count} replay(s) added to the game replay folder"))
        else:
            self.notify(tr("These replays are already in the game replay folder"))
        if result.added and self.copy_kind == "add":
            self.refresh_files(added=result.added)

    def copy_failed(self):
        """Copy ended by an unexpected error (logged): progress bar hidden, buttons enabled again"""
        self.copy_done(replay_files.CopyResult([], ["unexpected error, see log file"]))

    @Slot(str)
    def exportReplays(self, key: str):
        """Replay (selected replays if it is one of them) copied to a folder chosen in a dialog"""
        folder = self.replay_folder()
        replays = self.chosen_replays(key)
        if not folder or not replays:
            return
        target = QFileDialog.getExistingDirectory(self._window, tr("Export Replays"),
                                                  last_folder.start_folder("replays_export"))
        if target:
            last_folder.remember("replays_export", target)
            self.start_copy([replay_files.replay_path(folder, replay.name) for replay in replays], target, "export")

    @Slot(str)
    def renameReplay(self, key: str):
        """Replay file renamed (name given in the page), game lists it under its new name"""
        folder = self.replay_folder()
        if not folder or self.replay_of(key) is None:
            return
        dialogs.ask_text(self._window, tr("Rename Replay"), tr("New replay name:"),
                         lambda name: self.rename_replay(key, name.strip()), key, accept_text=tr("Rename"))

    def rename_replay(self, key: str, name: str) -> bool:
        """Replay renamed (name typed), True: input closed; False: name refused (told), input kept to correct it"""
        folder = self.replay_folder()
        if not folder or not name or name == key or self.replay_of(key) is None:  # gone meanwhile
            return True
        error = replay_files.rename_replay(folder, key, name)
        if error:
            self.notify(trm(f"Unable to rename: {error}"), True)
            return False
        if key in self.protected:
            self.protected = (self.protected - {key}) | {name}
            self.save_settings()
        replay = self.replay_of(key)
        self.replays = [entry._replace(name=name, id=-1) if entry is replay else entry for entry in self.replays]
        renamed = self.selected_replay == key
        if renamed:
            self.selected_replay = name  # row of new name made selected
        self.refresh_files()
        if renamed:
            self.update_selected_protected()
            self.selectionChanged.emit()
        return True

    @Slot(str)
    def toggleProtected(self, key: str):
        """Replay (selected replays if it is one of them) protected from deletion & clean up, or no longer"""
        names = {replay.name for replay in self.chosen_replays(key)}
        if not names:
            return
        self.protected = self.protected - names if key in self.protected else self.protected | names
        self._replays_model.update_rows(lambda row: {"isProtected": row["key"] in self.protected})
        self.update_selected_protected()
        self.filesChanged.emit()
        self.save_settings()

    @Slot(str)
    def deleteReplays(self, key: str):
        """Replay (selected replays if it is one of them) moved to the recycle bin, after confirmation"""
        self.delete_replays(self.chosen_replays(key))

    def delete_replays(self, replays: list[GameReplay], title: str = "Delete Replays"):
        """Replays (protected ones kept) moved to the recycle bin in background, after a red confirmation: the app
        cannot undo it (recycle bin of the system)"""
        if self.trash_busy():
            return
        folder = self.replay_folder()
        kept = [replay for replay in replays if replay.name in self.protected]
        replays = [replay for replay in replays if replay.name not in self.protected]
        if kept and not replays:
            self.notify(trm(f"{len(kept)} protected replay(s) kept"), True)
        if not folder or not replays:
            return
        size = size_text(sum(replay.size for replay in replays))
        message = (f"Move replay <b>{replays[0].name}</b> ({size}) to the recycle bin?" if len(replays) == 1
                   else f"Move <b>{len(replays)}</b> replays ({size}) to the recycle bin?")
        paths = [replay_files.replay_path(folder, replay.name) for replay in replays]

        def confirmed(chosen: bool):
            if chosen and not self.trash_busy():  # asked in the page: another deletion may have started meanwhile
                self.start_trash(paths, "replays", len(kept))

        dialogs.confirm(self._window, tr(title), trm(message), tr(title), confirmed, danger=True)

    def trash_busy(self) -> bool:
        """Files still being moved to the recycle bin (told): one deletion at a time"""
        if self.request_trash.busy:
            self.notify(tr("Files are still being moved to the recycle bin, try again once done"), True)
        return self.request_trash.busy

    def start_trash(self, paths: list[str], kind: str, kept: int = 0):
        """Files moved to the recycle bin in background (hundreds of large replays take a while), progress shown,
        list refreshed once done"""
        self.trash_progress, self.trash_kind, self.trash_kept = 0.0, kind, kept
        self.trash_cancel = cancelled = threading.Event()
        progress = copy_reporter(self, "set_trash_progress")
        self.request_trash.start(lambda: replay_files.trash_replays(paths, progress, cancelled))
        self.filesChanged.emit()
        self.trashProgressChanged.emit()

    @Slot()
    def cancelTrash(self):
        """Files not moved yet left in place"""
        self.trash_cancel.set()

    def trash_done(self, result: replay_files.TrashResult):
        self.trash_progress = -1.0
        self.filesChanged.emit()
        self.trashProgressChanged.emit()
        count = len(result.moved)
        if result.errors:
            self.notify(trm(f"Unable to delete (replay open in game?): {', '.join(result.errors)}"), True)
        elif result.cancelled:
            self.notify(trm(f"Deletion stopped, {count} file(s) moved to the recycle bin"), True)
        elif self.trash_kind == "temp":
            self.notify(trm(f"{count} temporary file(s) moved to the recycle bin"))
        else:
            kept = self.trash_kept
            self.notify(trm(f"{count} replay(s) moved to the recycle bin")
                        + (f" · {trm(f'{kept} protected replay(s) kept')}" if kept else ""))
        if self.trash_kind == "temp":
            self.update_files()
        elif result.moved:
            extension = len(replay_files.REPLAY_EXTENSION)
            self.refresh_files(deleted=[os.path.basename(path)[:-extension] for path in result.moved])

    def trash_failed(self):
        """Recycle bin moves ended by an unexpected error (logged): progress hidden, list read again"""
        self.trash_done(replay_files.TrashResult([], ["unexpected error, see log file"]))
        self.refresh_files()

    @Slot()
    def deleteOlderThan(self):
        """Replays older than a number of days (asked in the page) moved to the recycle bin, protected ones kept"""
        def older_than(days: int):
            limit = time.time() - days * 86400
            self.delete_replays([replay for replay in self.replays if 0 < replay.time < limit], "Delete Old Replays")

        dialogs.ask_number(self._window, tr("Delete Old Replays"), tr("Delete replays older than (days):"),
                           older_than, 30, 1, 3650)

    @Slot()
    def keepLatest(self):
        """Replays but the latest ones (number asked in the page) moved to the recycle bin, protected ones kept"""
        def keep(count: int):
            # Replays of unknown time (0) kept, as Delete Older Than does: their age is unknown
            dated = [replay for replay in self.replays if replay.time > 0]
            latest = sorted(dated, key=lambda replay: replay.time, reverse=True)
            self.delete_replays(latest[count:], "Keep Latest Replays")

        dialogs.ask_number(self._window, tr("Keep Latest Replays"), tr("Number of latest replays kept:"),
                           keep, 20, 1, 1000)

    @Slot()
    def deleteTempFiles(self):
        """Temporary files left by the game in replay folder moved to the recycle bin, after confirmation"""
        if self.trash_busy():
            return
        self.update_files()
        if not self.temp:
            self.notify(tr("No temporary file left by the game"))
            return
        size = self.temp_size()
        paths = list(self.temp)

        def confirmed(chosen: bool):
            if chosen and not self.trash_busy():
                self.start_trash(paths, "temp")

        dialogs.confirm(self._window, tr("Delete Temporary Files"),
                        trm(f"Move <b>{len(paths)}</b> temporary files ({size}) to the recycle bin?"),
                        tr("Delete Temporary Files"), confirmed, danger=True)

    def refresh_files(self, added: list[str] | None = None, deleted: list[str] | None = None):
        """Replays list updated after files changed: at once from files, then from game (ids, metadata)"""
        folder = self.replay_folder()
        replays = [replay for replay in self.replays if replay.name not in (deleted or ())]
        for name in added or ():
            path = replay_files.replay_path(folder, name)
            if os.path.exists(path):  # listed by game once asked again
                replays.append(GameReplay(-1, name, "", "", "", os.path.getmtime(path), os.path.getsize(path),
                                          "", folder))
        replays.sort(key=lambda replay: replay.time, reverse=True)
        self.replays = replays
        self.update_replays()
        self.update_files()
        if self.state != OFFLINE:
            self.ask_replays()
