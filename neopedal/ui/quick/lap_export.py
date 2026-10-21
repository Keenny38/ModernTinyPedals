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
Lap viewer exports & imports (part of LapViewerBackend, QML backend.exports): MoTeC & CSV exports in worker process, MoTeC logs imported
in worker process, lap as delta best, page picture
"""

from __future__ import annotations

import base64
import csv
import functools
import html
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Protocol

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QLocale,
    QObject,
    QPointF,
    QRectF,
    QStandardPaths,
    Qt,
    QUrl,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
    QTextDocument,
)
from PySide6.QtWidgets import QApplication, QFileDialog

from ...formatter import strip_invalid_char
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.lap_cache import load_cached_lap
from ...userfile.lap_library import import_foreign_job
from ...userfile.lap_offset import aligned_on, is_recorded
from ...userfile.motec_ld import export_lap_job, import_ld_job
from ...userfile.telemetry_lap import (
    IMPORT_FOLDER,
    LapData,
    export_series_csv,
    lap_end_distance,
    lap_folder_name,
    lap_length,
    lap_stem,
    lap_time_of,
    length_ratio,
    monotonic_distance,
    official_lap_time,
    read_lap_info,
    same_circuit,
    share_lap_job,
)
from ..lap_viewer import CHANNEL_MAP, Channel, LapEntry, PlotLap, channel_title, format_laptime, lap_label
from . import lap_map
from .corner_report import build_report
from .formatting import day_month_year_minutes
from .lap_base import COLOR_GAIN, COLOR_LOSS, PagePart, weak_host

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ...userfile.corner_analysis import CornerComparison
    from .trace_data import TraceData

logger = logging.getLogger(__name__)

CSV_TIME_STEP = 0.02  # seconds between rows of CSV export on time base (50 rows per second)
REPORT_COLUMNS = (  # corner report table: corner row key, column title
    ("label", "Corner"), ("apex", "Apex"), ("time", "Time"), ("speed", "Min Speed"), ("brake", "Braking"),
    ("throttle", "Full Throttle"), ("entry", "Entry"), ("exit", "Exit"), ("gear", "Gear"),
    ("trail", "Trail Braking"), ("coast", "Coasting"), ("overlap", "Overlap"), ("peakBrake", "Brake Pressure"),
    ("best", "Fastest"),
)
REPORT_MAP = "corner-map.png"  # map picture of PDF report (text document resource)
REPORT_PDF_MAP = 560  # map picture largest side on PDF page (fits on a landscape page)
DELTA_BEST_BACKUPS = 5  # dated backups kept of delta best files replaced by a lap (first backup kept apart)
IMPORT_STOPPED = "import stopped, file too big or unreadable"  # import job without result (worker process died)
NO_LAP_TIME = "no lap time"  # delta best not written: too few timed samples


def backup_delta_best(target: str):
    """Copy delta best file about to be replaced: first one to <file>.bak (never overwritten: delta best driven
    before a lap was first used), later ones dated (newest DELTA_BEST_BACKUPS kept), raises OSError"""
    first = f"{target}.bak"
    if not os.path.exists(first):
        shutil.copy2(target, first)
        return
    shutil.copy2(target, f"{target}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    folder, name = os.path.split(target)
    dated = re.compile(re.escape(name) + r"\.\d{8}-\d{6}\.bak")
    backups = sorted(entry for entry in os.listdir(folder) if dated.fullmatch(entry))
    for old in backups[:-DELTA_BEST_BACKUPS]:
        with suppress(OSError):
            os.remove(os.path.join(folder, old))


def unique_export_name(folder: str, stem: str, ext: str, taken: set[str]) -> str:
    """Path of a new file of folder for a batch export: <stem><ext>, else <stem> (2)<ext>, (3)... when that name is
    already used by another file of the batch (same lap file name from two track/class folders, imported & recorded
    lap) or by a file already in folder (former export kept, never overwritten), name reserved in taken (lowercase:
    case-insensitive file systems)"""
    number = 1
    while True:
        name = f"{stem}{ext}" if number == 1 else f"{stem} ({number}){ext}"
        target = os.path.join(folder, name)
        if name.lower() not in taken and not os.path.exists(target):
            taken.add(name.lower())
            return target
        number += 1


def delta_best_error(target: str, lap: LapData, lap_time: float, scale: float = 1.0) -> str:
    """Write delta best file of lap (distances multiplied by scale, thread job), former file kept as backup (see
    backup_delta_best), returns "" if written, NO_LAP_TIME if lap has too few timed rows, else error text"""
    rows = LapExports.delta_best_rows(lap, lap_time, scale)
    if len(rows) < 12:
        return NO_LAP_TIME
    temp = f"{target}.tmp"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target):
            backup_delta_best(target)
        with open(temp, "w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerows(rows)
        os.replace(temp, target)
    except OSError as error:
        logger.error("LAP VIEWER: unable to save delta best %s: %s", target, error)
        with suppress(OSError):
            os.remove(temp)
        return str(error)
    return ""


def write_pdf(document: QTextDocument, filename: str):
    """Document printed to PDF file: written to a temporary file of the same folder, then moved in place
    (QPdfWriter fails silently: locked or read-only target raises OSError here, old file kept)"""
    fd, temp = tempfile.mkstemp(suffix=".pdf", prefix=".report-", dir=os.path.dirname(filename) or ".")
    os.close(fd)
    try:
        writer = QPdfWriter(temp)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(QPageLayout.Orientation.Landscape)
        writer.setResolution(96)  # page sizes in screen pixels, like the HTML report
        document.print_(writer)
        del writer  # file closed before moved
        if os.path.getsize(temp) == 0:
            raise OSError(tr("Unable to write file"))
        os.replace(temp, filename)
    except BaseException:
        with suppress(OSError):
            os.remove(temp)
        raise


class ExportHost(Protocol):
    """What the exports part uses of the lap viewer page"""

    data: TraceData
    entries: list[LapEntry]  # laps of shown track
    external: list[LapEntry]  # laps added from other folders
    folder: str
    reference_key: str
    visible: list[str]  # channels shown on charts
    widget: QWidget  # page host (dialogs parent)

    def shown_track(self) -> str: ...
    def track_name(self) -> str: ...
    def track_map(self) -> dict: ...
    def corner_rows(self) -> list[CornerComparison]: ...
    def corner_table(self) -> list[dict]: ...
    def coaching_rows(self) -> list[dict]: ...
    def compared_lap(self) -> PlotLap | None: ...
    def reference_map_line(self) -> lap_map.MapLine | None: ...
    def ordered_checked(self) -> list[str]: ...
    def short_label(self, key: str) -> str: ...
    def add_external(self, lap_paths: list[str], reference_from: list[str] | None = None,
                     checked: list[str] | None = None): ...
    def store_lap(self, path: str, lap: LapData | None): ...
    def set_status(self, text: str, transient: bool = True): ...
    def run_job(self, name: str, work: Callable[[], Any], done: Callable[[Any], None]): ...
    def run_process_job(self, name: str, done: Callable[[Any], None], function: Callable, *args): ...


def driver_name() -> str:
    """Player name (online ranks profile), empty if unknown"""
    from ...rank_info import ranks

    player = ranks.player
    return str(player.name) if player is not None and player.name else ""


def share_folder() -> str:
    """Folder a shared lap is saved to first: Documents"""
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or os.path.expanduser("~")


def shared_lap_name(path: str) -> str:
    """File name of shared lap: track, vehicle, driver & lap time ("Atlanta - Porsche 963 - Steven 1m10.907s.csv.gz")"""
    info = read_lap_info(path)
    lap_time = lap_time_of(os.path.basename(path)) or official_lap_time(LapData("", {}, info))
    minutes, seconds = divmod(round(lap_time, 3), 60)
    parts = [str(info.get(key, "")) for key in ("track", "vehicle") if info.get(key)]
    parts.append(" ".join(part for part in (driver_name(), f"{int(minutes)}m{seconds:06.3f}s" if lap_time > 0 else "")
                          if part))
    return strip_invalid_char(" - ".join(part for part in parts if part) or lap_stem(path)) + ".csv.gz"


class LapExports(PagePart):
    """Exports & imports of lap viewer page (QML backend.exports)"""

    def __init__(self, page: ExportHost, lap_cache: dict[str, LapData | None], parent: QObject | None = None):
        super().__init__(parent)
        self._page = weak_host(page)
        self._lap_cache = lap_cache  # laps read by page (lap path: lap data, None if unreadable)
        self._exports = 0  # MoTeC & CSV export jobs running
        self._imports = 0  # MoTeC logs being imported

    def exporting(self) -> bool:
        """Export jobs running (files written whole even if page closes)"""
        return self._exports > 0

    def importing(self) -> bool:
        """Import jobs running (busy indicator)"""
        return self._imports > 0

    """Exports & imports of lap viewer page"""

    # Delta best: recorded lap as delta reference of Delta Best widgets (same file as module_delta)
    @staticmethod
    def delta_best_file(track: str) -> str:
        """Delta best file of track (track & class folder is the game combo name)"""
        return os.path.join(cfg.path.delta_best, f"{track}.csv")

    def delta_best_track(self, path: str) -> str:
        """Track folder (game combo) whose delta best lap can be: its track for a lap of current track, current track
        for an added lap driven there (foreign lap of same combo, imported lap of same track name & length), empty if
        none"""
        if path in {entry.file.path for entry in self._page.entries}:
            return os.path.basename(os.path.dirname(path))
        entry = next((entry for entry in self._page.external if entry.file.path == path), None)
        if entry is None or not self._page.shown_track():
            return ""
        combo = str(entry.info.get("combo", ""))
        if combo:
            return self._page.shown_track() if lap_folder_name(combo).lower() == self._page.shown_track().lower() else ""
        track = str(entry.info.get("track", ""))
        if not track or track.lower() != self._page.shown_track().rsplit(" - ", 1)[0].lower():
            return ""
        recorded = self._page.entries[0].info if self._page.entries else {}
        return self._page.shown_track() if same_circuit(LapData("", {}, recorded), LapData("", {}, entry.info)) else ""

    def delta_best_lap(self, path: str, lap: LapData) -> tuple[LapData, float]:
        """Lap used as delta best & factor bringing its distances to game track distance: imported lap aligned on a lap
        recorded by the app (distance zero at the line: lap as shown, else aligned on reference or newest recorded lap
        of track) & scaled to track length (driven distance), lap recorded by the app as is"""
        return self.delta_best_source(path, lap)()

    def delta_best_source(self, path: str, lap: LapData) -> Callable[[], tuple[LapData, float]]:
        """Function giving delta best lap & distance factor (see delta_best_lap), page state read now: may run in a
        thread (anchor lap read & alignment measured there)"""
        if is_recorded(lap):
            return lambda: (lap, 1.0)
        shown = next((plot.data for plot in self._page.data.laps if plot.key == path), None)
        entries = {entry.file.path: entry for entry in self._page.entries}
        recorded = next((entry for entry in (entries.get(self._page.reference_key), *self._page.entries)
                         if entry is not None and "combo" in entry.info and entry.file.path != path), None)
        anchor_path = recorded.file.path if recorded is not None else ""
        anchor_cached = self._lap_cache.get(anchor_path) if anchor_path in self._lap_cache else None
        folder = self._page.folder

        def source() -> tuple[LapData, float]:
            aligned = shown
            if aligned is None:
                anchor = anchor_cached
                if anchor is None and anchor_path:
                    try:
                        anchor = load_cached_lap(folder, anchor_path)
                    except (OSError, ValueError) as error:
                        logger.error("LAP VIEWER: unable to load %s: %s", anchor_path, error)
                aligned = aligned_on(anchor, lap)[0] if anchor is not None else lap
            length = lap_length(LapData("", {}, recorded.info)) if recorded is not None else lap_length(aligned)
            return aligned, length_ratio(length, lap_end_distance(aligned)) if length > 0 else 1.0

        return source

    @staticmethod
    def delta_best_rows(lap: LapData, lap_time: float, scale: float = 1.0) -> list[tuple[float, float]]:
        """Distance & lap time rows of delta best file (same layout as module_delta: start, every meter, end), lap
        distances multiplied by scale (game track distance)"""
        distances, times = monotonic_distance(lap)
        if scale != 1.0:
            distances = [distance * scale for distance in distances]
        rows = [(0.0, 0.0)]
        for distance, seconds in zip(distances, times):
            if distance > rows[-1][0] + 1.0 and seconds > rows[-1][1] and 0 < seconds < lap_time:
                rows.append((round(distance, 6), round(seconds, 6)))
        rows.append((round(rows[-1][0] + 10, 6), round(lap_time, 6)))  # end value, like module_delta
        return rows

    @Slot(str)
    def exportDeltaBest(self, path: str = ""):
        """Use lap (recorded, or added lap driven on current track & class) as delta best reference of its track
        (former file kept as backup): lap & current delta best read, then delta best written in background"""
        path = path or self._page.reference_key
        if not path:
            self._page.set_status(tr("Check laps to export first."))
            return
        track = self.delta_best_track(path)
        if not track:
            self._page.set_status(tr("Lap of another track or class: not usable as delta best of this track."))
            return
        target = self.delta_best_file(track)
        cached = self._lap_cache.get(path)
        known = path in self._lap_cache  # loaded, or unreadable (None)
        folder = self._page.folder

        def reading() -> tuple[LapData | None, str, float]:
            from ...userfile.delta_best import load_delta_best_file

            lap, error = cached, ""
            if not known:
                try:
                    lap = load_cached_lap(folder, path)
                except (OSError, ValueError) as reason:
                    logger.error("LAP VIEWER: unable to load %s: %s", path, reason)
                    error = str(reason)
            return lap, error, load_delta_best_file(f"{os.path.dirname(target)}/", track, ((), 0.0))[1]

        def read(result):
            self._exports -= 1
            if result is None:  # job failed (logged)
                return
            lap, error, current = result
            if not known and path not in self._lap_cache:
                self._page.store_lap(path, lap)
            if error:
                self._page.set_status(trm(f"Unable to load lap: {error}"))
            self.confirm_delta_best(path, track, target, lap, current)

        self._exports += 1
        self._page.run_job("delta best", reading, read)

    def confirm_delta_best(self, path: str, name: str, target: str, lap: LapData | None, current: float):
        """Lap read: used as delta best once confirmed, aligned & written in background"""
        lap_time = lap_time_of(os.path.basename(path)) or (lap.lap_time if lap is not None else 0.0)
        if lap is None or lap_time <= 0 or "lap_time" not in lap.columns:
            self._page.set_status(tr("This lap has no lap time: not usable as delta best."))
            return
        message = trm(f"Use <b>{html.escape(lap_label(os.path.basename(path)))}</b> as delta best of "
                      f"<b>{html.escape(name)}</b>?")
        if current > 0:
            message += "<br>" + trm(f"Current delta best: {format_laptime(current)} (kept as backup file)")
        from .._common import confirm_action

        if not confirm_action(self._page.widget, tr("Delta Best"), message, tr("Use as Delta Best")):
            return
        aligning = self.delta_best_source(path, lap)

        def writing() -> str:
            aligned, scale = aligning()
            return delta_best_error(target, aligned, lap_time, scale)

        def written(error):
            self._exports -= 1
            if error == "":
                self._page.set_status(trm(f"Delta best of {html.escape(name)}: {format_laptime(lap_time)} "
                                    "(used next time you drive)"))
            elif error == NO_LAP_TIME:
                self._page.set_status(tr("This lap has no lap time: not usable as delta best."))
            else:  # None: job failed (logged)
                self._page.set_status(trm(f"Unable to save delta best: {error or tr('Unknown error')}"))

        self._exports += 1
        self._page.run_job("delta best", writing, written)

    # Added laps: other folders, MoTeC logs, imported laps library
    @Slot()
    def addFiles(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self._page.widget, tr("Add File..."), self._page.folder,
            f"{tr('Laps')} (*.csv *.csv.gz *.ld);;NeoPedal Lap (*.csv *.csv.gz);;MoTeC i2 (*.ld)")
        logs = [filename for filename in filenames if filename.lower().endswith(".ld")]
        self._page.add_external([filename for filename in filenames if filename not in logs])
        if logs:  # MoTeC logs: complete laps converted to lap files in background
            self.import_motec(logs)

    # Laps of other drivers: teammate or shared folder, copied to imported laps (foreign group)
    def track_reference_info(self) -> tuple[dict, str]:
        """Lap info laps of another folder must match (reference lap of track, else newest lap) & vehicle class"""
        entries = {entry.file.path: entry for entry in self._page.entries}
        entry = entries.get(self._page.reference_key) or (self._page.entries[0] if self._page.entries else None)
        info = entry.info if entry is not None else {}
        vehicle_class = str(info.get("class", "")) or (self._page.shown_track().rsplit(" - ", 1)[1] if " - " in self._page.shown_track() else "")
        return info, vehicle_class

    @Slot()
    def importFolder(self):
        """Laps of another driver's folder (teammate, shared folder) driven on current track with same class"""
        if not self._page.shown_track():
            self._page.set_status(tr("No recorded lap. Enable the Recorder module, then drive a few laps."))
            return
        source = QFileDialog.getExistingDirectory(self._page.widget, tr("Import Folder..."), os.path.expanduser("~"))
        if source:
            self.import_folder(source)

    def import_folder(self, source: str, background: bool = True):
        """Copy laps of source folder matching current track & class to a foreign group of imported laps (worker
        process if background), listed once copied: fastest one shown"""
        reference, vehicle_class = self.track_reference_info()
        name = html.escape(os.path.basename(os.path.normpath(source)))

        def imported(result):
            if not isinstance(result, dict):  # job failed (logged), or its worker process died: never run again
                result = {"paths": [], "error": IMPORT_STOPPED}
            paths = [os.path.normpath(path) for path in result.get("paths", [])]
            present = int(result.get("present", 0))
            skipped = int(result.get("circuit", 0)) + int(result.get("class", 0))
            if result.get("error"):
                self._page.set_status(trm(f"Unable to import laps: {html.escape(tr(str(result['error'])))}"))
            elif not paths:
                self._page.set_status(trm(f"No lap of this track & class in: {name}"))
            else:
                message = trm(f"{len(paths) - present} foreign lap(s) imported from {name}")
                if present:
                    message += " · " + trm(f"{present} already imported")
                if skipped:
                    message += " · " + trm(f"{skipped} skipped (other circuit or class)")
                if result.get("file"):  # CSV files not recorded laps (notes, exports)
                    message += " · " + trm(f"{int(result['file'])} other file(s) skipped")
                self._page.set_status(message)
            if paths:
                fastest = min(paths, key=lambda path: lap_time_of(os.path.basename(path)) or float("inf"))
                self._page.add_external(paths, checked=[fastest])

        if not background:
            imported(import_foreign_job(self._page.folder, source, reference, vehicle_class))
            return
        self.run_import_job("Lap import", imported, import_foreign_job, self._page.folder, source, reference, vehicle_class)
        self._page.set_status(trm(f"Importing laps from {name}..."), False)

    def run_import_job(self, name: str, done: Callable[[Any], None], function: Callable, *args):
        """Run import job in worker process (laps written to imported laps), counted while running: busy indicator
        shown, page closing lets it finish (app exit waits for it a few seconds, see lap_backend.IMPORT_JOBS)"""

        def finished(result):
            self._imports -= 1
            done(result)

        self._imports += 1
        self._page.run_process_job(name, finished, function, *args)

    def import_motec(self, filenames: list[str], background: bool = True,
                     done: Callable[[list[tuple[str, list[str], str]]], None] | None = None):
        """Import complete laps of MoTeC .ld files, shown once every log is read (fastest imported lap as reference),
        or results given to done instead (imported laps library): log, lap paths, error of each log

        Logs read by worker process if background: a long log takes seconds, window stays responsive.
        """
        folder = os.path.join(self._page.folder, IMPORT_FOLDER)
        results: list[tuple[str, list[str], str]] = []

        def imported(filename: str, result):
            # None: job failed (logged), or its worker process died (log too big or broken): never run again
            paths, error = result if isinstance(result, tuple) else ([], tr(IMPORT_STOPPED))
            results.append((filename, [os.path.normpath(path) for path in paths], error))
            if len(results) < len(filenames):
                return
            laps = [path for _, paths, _ in results for path in paths]
            failed = next(((name, error) for name, _, error in results if error), None)
            empty = next((name for name, paths, error in results if not paths and not error), "")
            if failed is not None:
                self._page.set_status(trm(f"Unable to import MoTeC file: {html.escape(failed[1])}"))
            elif empty:
                self._page.set_status(trm(f"No complete lap in: {html.escape(os.path.basename(empty))}"))
            else:
                self._page.set_status(trm(f"MoTeC log imported: <b>{html.escape(os.path.basename(results[0][0]))}</b> "
                                    f"({len(laps)} laps)"))
            if done is not None:
                done(results)
            else:
                self._page.add_external(laps, laps)

        if not background:
            for filename in filenames:
                imported(filename, import_ld_job(filename, folder))
            return
        for filename in filenames:
            self.run_import_job("MoTeC import", functools.partial(imported, filename), import_ld_job, filename, folder)
        self._page.set_status(trm(f"Importing MoTeC log: {html.escape(os.path.basename(filenames[0]))}..."), False)

    # Export
    @Slot(str)
    def exportMotec(self, path: str = ""):
        """Export lap (reference lap by default) to MoTeC .ld file, lap read & written by worker process"""
        path = path or self._page.reference_key
        if not path or (path in self._lap_cache and self._lap_cache[path] is None):  # unreadable lap
            return
        filename, _ = QFileDialog.getSaveFileName(
            self._page.widget, tr("Export MoTeC..."), lap_stem(path) + ".ld", "MoTeC i2 (*.ld)")
        if not filename:
            return

        def exported(error):
            self._exports -= 1
            if error == "":
                self._page.set_status(trm(f"Exported: {os.path.basename(filename)}"))
            else:  # None: job failed (logged)
                self._page.set_status(trm(f"Unable to export lap: {error or tr('Unknown error')}"))

        self._exports += 1
        venue = os.path.basename(os.path.dirname(path)).split(" - ")[0]
        self._page.run_process_job("MoTeC export", exported, export_lap_job, self._page.folder, path, filename, venue)

    @Slot(float, float)
    def exportPassageMotec(self, start: float, end: float):
        """Reference lap between two axis positions (markers A & B) to MoTeC .ld file, by worker process"""
        path = self._page.reference_key
        if not path or (path in self._lap_cache and self._lap_cache[path] is None):  # unreadable lap
            return
        low, high = sorted((self._page.data.distance_at_x(start), self._page.data.distance_at_x(end)))
        filename, _ = QFileDialog.getSaveFileName(
            self._page.widget, tr("Export MoTeC..."), f"{lap_stem(path)} {low:.0f}-{high:.0f}m.ld", "MoTeC i2 (*.ld)")
        if not filename:
            return

        def exported(error):
            self._exports -= 1
            if error == "":
                self._page.set_status(trm(f"Exported: {os.path.basename(filename)}"))
            else:  # None: job failed (logged)
                self._page.set_status(trm(f"Unable to export lap: {error or tr('Unknown error')}"))

        self._exports += 1
        venue = os.path.basename(os.path.dirname(path)).split(" - ")[0]
        self._page.run_process_job("MoTeC export", exported, export_lap_job, self._page.folder, path, filename, venue,
                                   (low, high))

    @Slot(str)
    def shareLap(self, path: str = ""):
        """Lap (reference lap by default) as one compressed file to send to another driver, who adds it to their
        lap viewer with Add File (lap info tells who shared it), written by worker process"""
        path = path or self._page.reference_key
        if not path or not os.path.isfile(path):
            return
        filename, _ = QFileDialog.getSaveFileName(
            self._page.widget, tr("Share Lap..."), os.path.join(share_folder(), shared_lap_name(path)),
            f"{tr('NeoPedal Lap')} (*.csv.gz)")
        if not filename:
            return
        if not filename.lower().endswith(".csv.gz"):
            filename = filename.removesuffix(".gz").removesuffix(".csv") + ".csv.gz"

        def shared(error):
            self._exports -= 1
            if error == "":
                self._page.set_status(trm(f"Lap saved to share: <b>{html.escape(os.path.basename(filename))}</b> · "
                                          "send this file, the other driver adds it with Add File..."))
            else:  # None: job failed (logged)
                self._page.set_status(trm(f"Unable to share lap: {html.escape(error or tr('Unknown error'))}"))

        self._exports += 1
        self._page.run_process_job("lap share", shared, share_lap_job, path, filename, driver_name())

    @Slot(bool)
    def exportMotecMany(self, whole_track: bool):
        """Export displayed laps, or every lap of track, to folder (in background)"""
        paths = [entry.file.path for entry in self._page.entries] if whole_track else self._page.ordered_checked()
        if not paths:
            return
        folder = QFileDialog.getExistingDirectory(self._page.widget, tr("Export MoTeC..."), self._page.folder)
        if folder:
            self.export_many(paths, folder)

    def export_many(self, paths: list[str], folder: str, background: bool = True) -> int:
        """Export laps to folder (laps read from binary cache), one worker process job per lap if background
        (window stays responsive), returns count if not"""
        taken: set[str] = set()
        jobs = [(path, unique_export_name(folder, os.path.basename(lap_stem(path)), ".ld", taken),
                 os.path.basename(os.path.dirname(path)).split(" - ")[0]) for path in paths]
        if not background:
            results = [export_lap_job(self._page.folder, path, target, venue) for path, target, venue in jobs]
            self._page.set_status(self.export_message(folder, results))
            return results.count("")
        errors: list[str] = []
        self._exports += len(jobs)

        def exported(error):
            self._exports -= 1
            errors.append(tr("Unknown error") if error is None else error)  # None: job failed (logged)
            if len(errors) < len(jobs):
                self._page.set_status(trm(f"Exporting {len(errors)}/{len(jobs)} laps..."), False)
            else:
                self._page.set_status(self.export_message(folder, errors))

        self._page.set_status(trm(f"Exporting 0/{len(jobs)} laps..."), False)
        for path, target, venue in jobs:
            self._page.run_process_job("MoTeC export", exported, export_lap_job, self._page.folder, path, target, venue)
        return 0

    @staticmethod
    def export_message(folder: str, errors: list[str]) -> str:
        """Exported file count, then failed count & first reason if any failed"""
        message = trm(f"Exported <b>{errors.count('')}</b> file(s) to: {folder}")
        failed = [error for error in errors if error]
        if failed:
            message += " · " + trm(f"{len(failed)} failed: {html.escape(failed[0])}")
        return message

    @Slot()
    def exportCsv(self):
        """Displayed charts of displayed laps to CSV, every meter"""
        if not self._page.data.laps:
            self._page.set_status(tr("Check laps to export first."))
            return
        default = os.path.join(self._page.folder, f"{self._page.shown_track() or 'laps'}.csv")
        filename, _ = QFileDialog.getSaveFileName(self._page.widget, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename:
            self.write_csv(filename, background=True)

    def csv_channels(self) -> list[Channel]:
        """Displayed channels, combined panels as their sub-channels"""
        channels: list[Channel] = []
        for column in self._page.visible:
            for part in CHANNEL_MAP[column].parts or (column,):
                if CHANNEL_MAP[part] not in channels:
                    channels.append(CHANNEL_MAP[part])
        return channels

    @Slot()
    def exportTimeCsv(self):
        """Displayed charts of displayed laps to CSV along lap time, every CSV_TIME_STEP seconds"""
        if not self._page.data.laps:
            self._page.set_status(tr("Check laps to export first."))
            return
        default = os.path.join(self._page.folder, f"{self._page.shown_track() or 'laps'} - {tr('Time')}.csv")
        filename, _ = QFileDialog.getSaveFileName(self._page.widget, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename:
            self.write_csv(filename, background=True, time_base=True)

    def write_csv(self, filename: str, decimal_point: str = "", start: float = 0.0, end: float = -1.0,
                  background: bool = False, time_base: bool = False) -> bool:
        """Distance (or lap time), then each displayed channel of each displayed lap, resampled every meter (or
        every CSV_TIME_STEP seconds of each lap own time on time base), start to end

        Number format follows system locale (decimal comma & semicolon separator in French), for Excel.
        Series resampled by worker process if background (page thread does no resampling). Laps exported at
        their place on track (not shifted when aligned on a braking point).
        """
        decimal = decimal_point or QLocale.system().decimalPoint() or "."
        if time_base:
            length = max((self._page.data.lap_times(lap)[1][-1] for lap in self._page.data.laps if self._page.data.lap_times(lap)[1]),
                         default=0.0)
        else:
            length = max((self._page.data.lap_end(lap) * self._page.data.scale_of(lap) for lap in self._page.data.laps
                          if len(lap.data)), default=0.0)
        last = min(end, length) if end >= 0 else length
        header = [f"{tr('Time')} (s)" if time_base else f"{tr('Distance')} (m)"]
        series: list[tuple[Sequence[float], Sequence[float]]] = []
        for lap in self._page.data.laps:
            for channel in self.csv_channels():
                unit = self._page.data.unit_of(channel)
                header.append(f"{lap.label} - {channel_title(channel)}" + (f" ({unit})" if unit else ""))
                series.append(self._page.data.series(channel, lap, time_axis=time_base, aligned=False))
        step = CSV_TIME_STEP if time_base else 1.0
        if background:  # numbers written by worker process (page stays responsive)
            name = html.escape(os.path.basename(filename))

            def written(error):
                self._exports -= 1
                if error is None or error:  # None: job failed (logged)
                    self._page.set_status(trm(f"Unable to export lap: {html.escape(error or tr('Unknown error'))}"))
                else:
                    self._page.set_status(trm(f"Exported: {name}"))

            self._exports += 1
            self._page.run_process_job("CSV export", written, export_series_csv, filename, header, start, last, series,
                                 decimal, step)
            return True
        error = export_series_csv(filename, header, start, last, series, decimal, step)
        if error:
            self._page.set_status(trm(f"Unable to export lap: {error}"))
            return False
        return True

    # Corner report: corner table, deltas, coaching notes & map in one HTML file (or PDF)
    def corner_map_image(self, size: int = 900) -> QImage | None:
        """Track map of report: reference line, each corner colored by time lost or gained, corner names & deltas"""
        if not self._page.track_map():
            return None
        line = self._page.reference_map_line()  # reference lap line, else official circuit (lap without positions)
        if line is None or len(line.xs) < 2:
            return None
        x0, x1, y0, y1 = min(line.xs), max(line.xs), min(line.ys), max(line.ys)
        margin = 48
        scale = (size - margin * 2) / max(x1 - x0, y1 - y0, 1.0)
        image = QImage(int((x1 - x0) * scale) + margin * 2, int((y1 - y0) * scale) + margin * 2,
                       QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        def path_of(part) -> QPainterPath:
            path = QPainterPath()
            for index, (x, y) in enumerate(zip(part.xs, part.ys)):  # map y down, like track map
                point = QPointF(margin + (x - x0) * scale, margin + (y - y0) * scale)
                if index:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
            return path

        def pen(color: str, width: float) -> QPen:
            return QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        painter.setPen(pen("#D1D5DB", 10))
        painter.drawPath(path_of(lap_map.simplify(line, 1 / scale)))
        for row in self._page.corner_rows():
            delta = row.time_delta
            if delta is None or abs(delta) < 0.005:
                continue
            painter.setPen(pen("#DC2626" if delta > 0 else "#16A34A", 6))
            painter.drawPath(path_of(lap_map.part(line, row.corner.start, row.corner.end)))
        font = QFont(painter.font())
        font.setPixelSize(15)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        for corner in self._page.track_map().get("corners", []):  # name & delta beside apex, on a light patch (readable over lines)
            x, y = margin + (corner["x"] - x0) * scale, margin + (corner["y"] - y0) * scale
            text = f"{corner['label']} {corner['delta']}".strip()
            width = metrics.horizontalAdvance(text)
            left = x + 7 if x + 7 + width < image.width() - 2 else x - 7 - width  # kept inside picture
            box = QRectF(left - 3, y - 7 - metrics.ascent(), width + 6, metrics.height())
            painter.fillRect(box, QColor(255, 255, 255, 215))
            color = {COLOR_LOSS: "#B91C1C", COLOR_GAIN: "#15803D"}.get(corner.get("deltaColor", ""), "#1F2937")
            painter.setPen(QColor(color))
            painter.drawText(QPointF(left, y - 7), text)
        painter.end()
        return image

    def corner_report(self, image: QImage | None, pdf: bool = False) -> str:
        """HTML report of corner tab with map picture (embedded, or document resource REPORT_MAP for PDF), empty if
        no corner"""
        rows = [row for row in self._page.corner_table() if row.get("kind") in ("corner", "sum", "total", "ideal")]
        reference = self._page.data.reference
        if not rows or reference is None:
            return ""
        compared = self._page.compared_lap()
        laps = [{"label": self._page.short_label(reference.key), "color": reference.color.name(), "role": tr("Reference")}]
        if compared is not None:
            laps.append({"label": self._page.short_label(compared.key), "color": compared.color.name(),
                         "role": tr("Compared lap")})
        png = ""
        size = (0, 0)
        if image is not None and pdf:  # fitted in a page
            fit = min(REPORT_PDF_MAP / max(image.width(), 1), REPORT_PDF_MAP / max(image.height(), 1), 1.0)
            size = (round(image.width() * fit), round(image.height() * fit))
        if image is not None and not pdf:
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")  # type: ignore[call-overload]  # device save refuses bytes format at run time
            png = base64.b64encode(bytes(data.data())).decode("ascii")
        return build_report(
            title=f"{self._page.track_name() or self._page.shown_track()} · {tr('Corners')}",
            subtitle=f"{tr('Reference')} {format_laptime(official_lap_time(reference.data) or reference.data.lap_time)}"
                     f" · {day_month_year_minutes()}",
            laps=laps, headers=[tr(title) for _, title in REPORT_COLUMNS],
            keys=[key for key, _ in REPORT_COLUMNS], rows=rows, coaching=self._page.coaching_rows(),
            coaching_title=tr("Where time is lost") + (f" · {self._page.short_label(compared.key)}" if compared else ""),
            png=png, map_title=tr("Track Map"), footer="NeoPedal",
            image_src=REPORT_MAP if pdf and image is not None else "", image_size=size,
        )

    @Slot()
    def exportCornerReport(self):
        """Corner report to HTML file (self-contained) or PDF"""
        if not self.corner_report(None):
            self._page.set_status(tr("No corner to report: check laps with speed recorded."))
            return
        default = os.path.join(self._page.folder, f"{self._page.shown_track() or 'laps'} - {tr('Corners')}.html")
        filename, _ = QFileDialog.getSaveFileName(self._page.widget, tr("Export Corner Report..."), default,
                                                  "HTML (*.html);;PDF (*.pdf)")
        if filename:
            self.write_report(filename)

    def write_report(self, filename: str) -> bool:
        """Write corner report: PDF if file name ends with .pdf, else HTML"""
        image = self.corner_map_image()
        pdf = filename.lower().endswith(".pdf")
        report = self.corner_report(image, pdf)
        if not report:
            return False
        try:
            if pdf:
                document = QTextDocument()
                if image is not None:
                    document.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(REPORT_MAP), image)
                document.setHtml(report)
                write_pdf(document, filename)
            else:
                with open(filename, "w", encoding="utf-8") as file:
                    file.write(report)
        except OSError as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self._page.set_status(trm(f"Unable to export lap: {error}"))
            return False
        self._page.set_status(trm(f"Exported: {html.escape(os.path.basename(filename))}"))
        return True

    @Slot("QVariant")
    def saveImage(self, image):
        """Save page picture (charts, map) to PNG file"""
        if not isinstance(image, QImage) or image.isNull():
            return
        default = os.path.join(self._page.folder, f"{self._page.shown_track() or 'laps'}.png")
        filename, _ = QFileDialog.getSaveFileName(self._page.widget, tr("Export Picture..."), default, "PNG (*.png)")
        if filename:
            if image.save(filename, b"PNG"):
                self._page.set_status(trm(f"Exported: {html.escape(os.path.basename(filename))}"))
            else:
                self._page.set_status(trm(f"Unable to save picture: {html.escape(os.path.basename(filename))}"))

    @Slot("QVariant")
    def copyImage(self, image):
        """Page picture to clipboard (paste in Discord...)"""
        if isinstance(image, QImage) and not image.isNull():
            QApplication.clipboard().setImage(image)
            self._page.set_status(tr("Picture copied to clipboard."))

    @Slot(float, float)
    def exportPassageCsv(self, start: float, end: float):
        """Displayed charts of displayed laps between two axis positions (markers A & B, zoomed part) to CSV,
        every meter"""
        if not self._page.data.laps:
            self._page.set_status(tr("Check laps to export first."))
            return
        low, high = sorted((self._page.data.distance_at_x(start), self._page.data.distance_at_x(end)))
        default = os.path.join(self._page.folder, f"{self._page.shown_track() or 'laps'} {low:.0f}-{high:.0f}m.csv")
        filename, _ = QFileDialog.getSaveFileName(self._page.widget, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename:
            self.write_csv(filename, "", low, high, background=True)
