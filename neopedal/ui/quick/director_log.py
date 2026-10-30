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
Broadcast Director events log (QML: backend.log): events written to a file of the session as they happen (one
writer thread, no file write on the UI thread), events exported to a CSV file
"""

from __future__ import annotations

import atexit
import csv
import logging
import os
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, Signal, Slot

from ...i18n import tr
from ...process import director as dr
from ...setting import cfg
from . import last_folder
from .director_shared import KIND_TEXTS, LOG_FLUSH_SECONDS, LOG_FOLDER, DirectorPart, car_label, clock_text, safe_name
from .formatting import clock_seconds, iso_day

if TYPE_CHECKING:
    from .director_backend import DirectorBackend

logger = logging.getLogger(__name__)


def safe_cell(value: Any) -> Any:
    """CSV cell never read as a formula by a spreadsheet (driver names, texts from the game): text starting
    like a formula gets a leading quote, numbers & signed values ("+1.2", "-3 laps") kept as they are"""
    if not isinstance(value, str) or not value:
        return value
    first, second = value[0], value[1:2]
    if first in "=@\t\r" or (first in "+-" and not (second.isdigit() or second in ". ")):
        return f"'{value}"
    return value


def safe_row(row: tuple) -> tuple:
    return tuple(safe_cell(value) for value in row)


def write_log_rows(path: str, rows: list[tuple]):
    """Lines added to an events log file, header first in a new file (writer thread)"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path)
        # Text not encodable (lone surrogate in a name from the game) replaced, never a lost line
        with open(path, "a", encoding="utf-8-sig" if new else "utf-8", errors="replace", newline="") as file:
            writer = csv.writer(file)
            if new:
                writer.writerow(("Time", "Session time", "Kind", "Event", "Detail", "Class", "Cars"))
            writer.writerows(safe_row(row) for row in rows)
    except (OSError, ValueError, csv.Error) as error:
        logger.warning("Broadcast director: events log not written: %s", error)


class LogWriter:
    """Lines of the events log written in order by one writer thread (no file write on the UI thread)"""

    def __init__(self):
        self._lock = threading.Condition()
        self._queue: deque[tuple[str, list[tuple]]] = deque()
        self._busy = False  # writer thread running

    def append(self, path: str, rows: list[tuple]):
        with self._lock:
            self._queue.append((path, rows))
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._write, daemon=True, name="Director events log").start()

    def _write(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._busy = False
                    self._lock.notify_all()
                    return
                path, rows = self._queue.popleft()
            try:
                write_log_rows(path, rows)
            except Exception:  # thread kept writing: never left busy (later lines lost, flush waiting)
                logger.exception("Broadcast director: events log lines not written")

    def flush(self, timeout: float = LOG_FLUSH_SECONDS) -> bool:
        """Lines given so far written (page closing, log read), False if still writing after timeout"""
        with self._lock:
            return self._lock.wait_for(lambda: not self._busy, timeout)


# One writer for every page instance (lines of a closed page & of the page opened again never mixed in a file):
# a closing page never waits for it, lines written in background, waited once when the app exits
WRITER = LogWriter()
atexit.register(WRITER.flush)



class EventsLog(DirectorPart):
    """Events log of the page: written as they happen (setting), exported on demand"""

    changed = Signal()

    def __init__(self, page: DirectorBackend, settings: dict[str, Any]):
        super().__init__(page)
        self.log_events = settings.get("log_events") is True  # events written to a file as they happen
        self.writer = WRITER

    def page_settings(self) -> dict[str, Any]:
        return {"log_events": self.log_events}

    def flush(self):
        """Lines given so far written (app quitting)"""
        self.writer.flush()

    def log_file(self) -> str:
        track, session = self.page.session_key[:2]
        name = f"{iso_day()} {safe_name(track)} {safe_name(session)}.csv"
        return os.path.join(cfg.path.config, LOG_FOLDER, name)

    def log_path(self) -> str:
        """Log file of the session, lines of events given so far written"""
        self.writer.flush()
        return self.log_file()

    def write_log(self, events: list[dr.Event]):
        """Events added to the log file of the session (race control): one line each, as they happen (lines made
        here, written in order by the log writer thread)"""
        if not events:
            return
        page = self.page
        rows = []
        for event in events:
            title, detail = page.event_texts(event)
            cars = " / ".join(car_label(page.by_slot.get(slot)) for slot in event.slots)
            rows.append((clock_seconds(), clock_text(event.time), page.kind_text(event), title, detail,
                         event.car_class, cars))
        self.writer.append(self.log_file(), rows)

    @Property(bool, notify=changed)
    def logEvents(self) -> bool:
        return self.log_events

    @Slot(bool)
    def setLogEvents(self, log: bool):
        self.log_events = log
        self.page.save_settings()
        self.changed.emit()

    @Slot()
    def openLogFolder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = os.path.join(cfg.path.config, LOG_FOLDER)
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Slot()
    def exportEvents(self):
        """Race events saved as a CSV file (session time, kind, title, detail, class, cars)"""
        from PySide6.QtWidgets import QFileDialog, QWidget

        page = self.page
        parent = page.parent()
        track, session = page.session_key[:2]
        name = "-".join(part for part in (track, session, time.strftime("%Y-%m-%d-%H%M")) if part)
        path, _ = QFileDialog.getSaveFileName(parent if isinstance(parent, QWidget) else None,
                                              tr("Export Events"), last_folder.start_path("director_events", f"{name}.csv"),
                                              "CSV (*.csv)")
        if not path:
            return
        last_folder.remember("director_events", path)
        try:
            with open(path, "w", encoding="utf-8-sig", errors="replace", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(("Session time", "Kind", "Event", "Detail", "Class", "Cars"))
                for event in page.events:
                    title, detail = page.event_texts(event)
                    cars = " / ".join(car_label(page.by_slot.get(slot)) for slot in event.slots)
                    writer.writerow(safe_row((clock_text(event.time), tr(KIND_TEXTS[event.kind]), title, detail,
                                              event.car_class, cars)))
        except (OSError, csv.Error) as error:
            page.notify(f"{tr('Events not saved')}: {error}", True)
            return
        page.notify(tr("Events saved"), file=path)
