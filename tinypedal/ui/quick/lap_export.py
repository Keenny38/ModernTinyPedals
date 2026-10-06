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
Lap viewer exports & imports (mixin of LapViewerBackend): MoTeC & CSV exports in worker process, MoTeC logs imported
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
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QLocale, QPointF, QRectF, Qt, QUrl, Slot
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
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.lap_library import import_foreign_job
from ...userfile.motec_ld import export_lap, export_lap_job, import_ld_job
from ...userfile.telemetry_lap import (
    IMPORT_FOLDER,
    LapData,
    export_series_csv,
    lap_folder_name,
    lap_stem,
    lap_time_of,
    monotonic_distance,
    official_lap_time,
    same_circuit,
)
from ..lap_viewer import CHANNEL_MAP, Channel, channel_title, format_laptime, lap_label
from . import lap_map
from .corner_report import build_report
from .lap_base import COLOR_GAIN, COLOR_LOSS, BackendBase

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


class LapExports(BackendBase):
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
        if path in {entry.file.path for entry in self.entries}:
            return os.path.basename(os.path.dirname(path))
        entry = next((entry for entry in self.external if entry.file.path == path), None)
        if entry is None or not self._track:
            return ""
        combo = str(entry.info.get("combo", ""))
        if combo:
            return self._track if lap_folder_name(combo).lower() == self._track.lower() else ""
        track = str(entry.info.get("track", ""))
        if not track or track.lower() != self._track.rsplit(" - ", 1)[0].lower():
            return ""
        recorded = self.entries[0].info if self.entries else {}
        return self._track if same_circuit(LapData("", {}, recorded), LapData("", {}, entry.info)) else ""

    @staticmethod
    def delta_best_rows(lap: LapData, lap_time: float) -> list[tuple[float, float]]:
        """Distance & lap time rows of delta best file (same layout as module_delta: start, every meter, end)"""
        distances, times = monotonic_distance(lap)
        rows = [(0.0, 0.0)]
        for distance, seconds in zip(distances, times):
            if distance > rows[-1][0] + 1.0 and seconds > rows[-1][1] and 0 < seconds < lap_time:
                rows.append((round(distance, 6), round(seconds, 6)))
        rows.append((round(rows[-1][0] + 10, 6), round(lap_time, 6)))  # end value, like module_delta
        return rows

    @Slot(str)
    def exportDeltaBest(self, path: str = ""):
        """Use lap (recorded, or added lap driven on current track & class) as delta best reference of its track
        (former file kept as backup)"""
        from ...userfile.delta_best import load_delta_best_file

        path = path or self.reference_key
        if not path:
            self.set_status(tr("Check laps to export first."))
            return
        track = self.delta_best_track(path)
        if not track:
            self.set_status(tr("Lap of another track or class: not usable as delta best of this track."))
            return
        lap = self.read_lap(path)
        lap_time = lap_time_of(os.path.basename(path)) or (lap.lap_time if lap is not None else 0.0)
        if lap is None or lap_time <= 0 or "lap_time" not in lap.columns:
            self.set_status(tr("This lap has no lap time: not usable as delta best."))
            return
        target = self.delta_best_file(track)
        name = track
        current = load_delta_best_file(f"{os.path.dirname(target)}/", name, ((), 0.0))[1]
        message = trm(f"Use <b>{html.escape(lap_label(os.path.basename(path)))}</b> as delta best of "
                      f"<b>{html.escape(name)}</b>?")
        if current > 0:
            message += "<br>" + trm(f"Current delta best: {format_laptime(current)} (kept as backup file)")
        confirm = QMessageBox.question(
            self._window, tr("Delta Best"), message,
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            defaultButton=QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self.write_delta_best(target, lap, lap_time):
            self.set_status(trm(f"Delta best of {html.escape(name)}: {format_laptime(lap_time)} "
                                "(used next time you drive)"))

    def write_delta_best(self, target: str, lap: LapData, lap_time: float) -> bool:
        """Write delta best file of lap, former file kept as backup (see backup_delta_best)"""
        rows = self.delta_best_rows(lap, lap_time)
        if len(rows) < 12:
            self.set_status(tr("This lap has no lap time: not usable as delta best."))
            return False
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
            self.set_status(trm(f"Unable to save delta best: {error}"))
            with suppress(OSError):
                os.remove(temp)
            return False
        return True

    # Added laps: other folders, MoTeC logs, imported laps library
    @Slot()
    def addFiles(self):
        filenames, _ = QFileDialog.getOpenFileNames(
            self._window, tr("Add File..."), self.folder,
            f"{tr('Laps')} (*.csv *.csv.gz *.ld);;Modern Tiny Pedals Lap (*.csv *.csv.gz);;MoTeC i2 (*.ld)")
        logs = [filename for filename in filenames if filename.lower().endswith(".ld")]
        self.add_external([filename for filename in filenames if filename not in logs])
        if logs:  # MoTeC logs: complete laps converted to lap files in background
            self.import_motec(logs)

    # Laps of other drivers: teammate or shared folder, copied to imported laps (foreign group)
    def track_reference_info(self) -> tuple[dict, str]:
        """Lap info laps of another folder must match (reference lap of track, else newest lap) & vehicle class"""
        entries = {entry.file.path: entry for entry in self.entries}
        entry = entries.get(self.reference_key) or (self.entries[0] if self.entries else None)
        info = entry.info if entry is not None else {}
        vehicle_class = str(info.get("class", "")) or (self._track.rsplit(" - ", 1)[1] if " - " in self._track else "")
        return info, vehicle_class

    @Slot()
    def importFolder(self):
        """Laps of another driver's folder (teammate, shared folder) driven on current track with same class"""
        if not self._track:
            self.set_status(tr("No recorded lap. Enable the Recorder module, then drive a few laps."))
            return
        source = QFileDialog.getExistingDirectory(self._window, tr("Import Folder..."), os.path.expanduser("~"))
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
                self.set_status(trm(f"Unable to import laps: {html.escape(tr(str(result['error'])))}"))
            elif not paths:
                self.set_status(trm(f"No lap of this track & class in: {name}"))
            else:
                message = trm(f"{len(paths) - present} foreign lap(s) imported from {name}")
                if present:
                    message += " · " + trm(f"{present} already imported")
                if skipped:
                    message += " · " + trm(f"{skipped} skipped (other circuit or class)")
                if result.get("file"):  # CSV files not recorded laps (notes, exports)
                    message += " · " + trm(f"{int(result['file'])} other file(s) skipped")
                self.set_status(message)
            if paths:
                fastest = min(paths, key=lambda path: lap_time_of(os.path.basename(path)) or float("inf"))
                self.add_external(paths, checked=[fastest])

        if not background:
            imported(import_foreign_job(self.folder, source, reference, vehicle_class))
            return
        self.run_import_job("Lap import", imported, import_foreign_job, self.folder, source, reference, vehicle_class)
        self.set_status(trm(f"Importing laps from {name}..."), False)

    def run_import_job(self, name: str, done: Callable[[Any], None], function: Callable, *args):
        """Run import job in worker process (laps written to imported laps), counted while running: busy indicator
        shown, page closing lets it finish (app exit waits for it a few seconds, see lap_backend.IMPORT_JOBS)"""

        def finished(result):
            self._imports -= 1
            done(result)

        self._imports += 1
        self.run_process_job(name, finished, function, *args)

    def import_motec(self, filenames: list[str], background: bool = True,
                     done: Callable[[list[tuple[str, list[str], str]]], None] | None = None):
        """Import complete laps of MoTeC .ld files, shown once every log is read (fastest imported lap as reference),
        or results given to done instead (imported laps library): log, lap paths, error of each log

        Logs read by worker process if background: a long log takes seconds, window stays responsive.
        """
        folder = os.path.join(self.folder, IMPORT_FOLDER)
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
                self.set_status(trm(f"Unable to import MoTeC file: {html.escape(failed[1])}"))
            elif empty:
                self.set_status(trm(f"No complete lap in: {html.escape(os.path.basename(empty))}"))
            else:
                self.set_status(trm(f"MoTeC log imported: <b>{html.escape(os.path.basename(results[0][0]))}</b> "
                                    f"({len(laps)} laps)"))
            if done is not None:
                done(results)
            else:
                self.add_external(laps, laps)

        if not background:
            for filename in filenames:
                imported(filename, import_ld_job(filename, folder))
            return
        for filename in filenames:
            self.run_import_job("MoTeC import", functools.partial(imported, filename), import_ld_job, filename, folder)
        self.set_status(trm(f"Importing MoTeC log: {html.escape(os.path.basename(filenames[0]))}..."), False)

    # Export
    @Slot(str)
    def exportMotec(self, path: str = ""):
        """Export lap (reference lap by default) to MoTeC .ld file"""
        path = path or self.reference_key
        lap = self.read_lap(path) if path else None
        if lap is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self._window, tr("Export MoTeC..."), lap_stem(path) + ".ld", "MoTeC i2 (*.ld)")
        if filename and self.export_file(path, lap, filename):
            self.set_status(trm(f"Exported: {os.path.basename(filename)}"))

    @Slot(bool)
    def exportMotecMany(self, whole_track: bool):
        """Export displayed laps, or every lap of track, to folder (in background)"""
        paths = [entry.file.path for entry in self.entries] if whole_track else self.ordered_checked()
        if not paths:
            return
        folder = QFileDialog.getExistingDirectory(self._window, tr("Export MoTeC..."), self.folder)
        if folder:
            self.export_many(paths, folder)

    def export_many(self, paths: list[str], folder: str, background: bool = True) -> int:
        """Export laps to folder (laps read from binary cache), one worker process job per lap if background
        (window stays responsive), returns count if not"""
        jobs = [(path, os.path.join(folder, os.path.basename(lap_stem(path)) + ".ld"),
                 os.path.basename(os.path.dirname(path)).split(" - ")[0]) for path in paths]
        if not background:
            results = [export_lap_job(self.folder, path, target, venue) for path, target, venue in jobs]
            self.set_status(self.export_message(folder, results))
            return results.count("")
        errors: list[str] = []
        self._exports += len(jobs)

        def exported(error):
            self._exports -= 1
            errors.append(tr("Unknown error") if error is None else error)  # None: job failed (logged)
            if len(errors) < len(jobs):
                self.set_status(trm(f"Exporting {len(errors)}/{len(jobs)} laps..."), False)
            else:
                self.set_status(self.export_message(folder, errors))

        self.set_status(trm(f"Exporting 0/{len(jobs)} laps..."), False)
        for path, target, venue in jobs:
            self.run_process_job("MoTeC export", exported, export_lap_job, self.folder, path, target, venue)
        return 0

    @staticmethod
    def export_message(folder: str, errors: list[str]) -> str:
        """Exported file count, then failed count & first reason if any failed"""
        message = trm(f"Exported <b>{errors.count('')}</b> file(s) to: {folder}")
        failed = [error for error in errors if error]
        if failed:
            message += " · " + trm(f"{len(failed)} failed: {html.escape(failed[0])}")
        return message

    def export_file(self, path: str, lap: LapData, filename: str) -> bool:
        track = os.path.basename(os.path.dirname(path)).split(" - ")[0]
        try:
            export_lap(lap, filename, venue=track, timestamp=os.path.getmtime(path))
        except (OSError, ValueError) as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self.set_status(trm(f"Unable to export lap: {error}"))
            return False
        return True

    @Slot()
    def exportCsv(self):
        """Displayed charts of displayed laps to CSV, every meter"""
        if not self.data.laps:
            self.set_status(tr("Check laps to export first."))
            return
        default = os.path.join(self.folder, f"{self._track or 'laps'}.csv")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename:
            self.write_csv(filename, background=True)

    def csv_channels(self) -> list[Channel]:
        """Displayed channels, combined panels as their sub-channels"""
        channels: list[Channel] = []
        for column in self.visible:
            for part in CHANNEL_MAP[column].parts or (column,):
                if CHANNEL_MAP[part] not in channels:
                    channels.append(CHANNEL_MAP[part])
        return channels

    @Slot()
    def exportTimeCsv(self):
        """Displayed charts of displayed laps to CSV along lap time, every CSV_TIME_STEP seconds"""
        if not self.data.laps:
            self.set_status(tr("Check laps to export first."))
            return
        default = os.path.join(self.folder, f"{self._track or 'laps'} - {tr('Time')}.csv")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export CSV..."), default, "CSV (*.csv)")
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
            length = max((self.data.lap_times(lap)[1][-1] for lap in self.data.laps if self.data.lap_times(lap)[1]),
                         default=0.0)
        else:
            length = max((self.data.lap_end(lap) * self.data.scale_of(lap) for lap in self.data.laps
                          if len(lap.data)), default=0.0)
        last = min(end, length) if end >= 0 else length
        header = [f"{tr('Time')} (s)" if time_base else f"{tr('Distance')} (m)"]
        series: list[tuple[Sequence[float], Sequence[float]]] = []
        for lap in self.data.laps:
            for channel in self.csv_channels():
                unit = self.data.unit_of(channel)
                header.append(f"{lap.label} - {channel_title(channel)}" + (f" ({unit})" if unit else ""))
                series.append(self.data.series(channel, lap, time_axis=time_base, aligned=False))
        step = CSV_TIME_STEP if time_base else 1.0
        if background:  # numbers written by worker process (page stays responsive)
            name = html.escape(os.path.basename(filename))

            def written(error):
                self._exports -= 1
                if error is None or error:  # None: job failed (logged)
                    self.set_status(trm(f"Unable to export lap: {html.escape(error or tr('Unknown error'))}"))
                else:
                    self.set_status(trm(f"Exported: {name}"))

            self._exports += 1
            self.run_process_job("CSV export", written, export_series_csv, filename, header, start, last, series,
                                 decimal, step)
            return True
        error = export_series_csv(filename, header, start, last, series, decimal, step)
        if error:
            self.set_status(trm(f"Unable to export lap: {error}"))
            return False
        return True

    # Corner report: corner table, deltas, coaching notes & map in one HTML file (or PDF)
    def corner_map_image(self, size: int = 900) -> QImage | None:
        """Track map of report: reference line, each corner colored by time lost or gained, corner names & deltas"""
        if not self._map:
            return None
        line = self.reference_map_line()  # reference lap line, else official circuit (lap without positions)
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
        for row in self._corner_rows:
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
        for corner in self._map.get("corners", []):  # name & delta beside apex, on a light patch (readable over lines)
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
        rows = [row for row in self._corners if row.get("kind") in ("corner", "sum", "total", "ideal")]
        reference = self.data.reference
        if not rows or reference is None:
            return ""
        compared = self.compared_lap()
        laps = [{"label": self.short_label(reference.key), "color": reference.color.name(), "role": tr("Reference")}]
        if compared is not None:
            laps.append({"label": self.short_label(compared.key), "color": compared.color.name(),
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
            title=f"{self.track_name() or self._track} · {tr('Corners')}",
            subtitle=f"{tr('Reference')} {format_laptime(official_lap_time(reference.data) or reference.data.lap_time)}"
                     f" · {time.strftime('%d/%m/%Y %H:%M')}",
            laps=laps, headers=[tr(title) for _, title in REPORT_COLUMNS],
            keys=[key for key, _ in REPORT_COLUMNS], rows=rows, coaching=self._coaching,
            coaching_title=tr("Where time is lost") + (f" · {self.short_label(compared.key)}" if compared else ""),
            png=png, map_title=tr("Track Map"), footer="Modern Tiny Pedals",
            image_src=REPORT_MAP if pdf and image is not None else "", image_size=size,
        )

    @Slot()
    def exportCornerReport(self):
        """Corner report to HTML file (self-contained) or PDF"""
        if not self.corner_report(None):
            self.set_status(tr("No corner to report: check laps with speed recorded."))
            return
        default = os.path.join(self.folder, f"{self._track or 'laps'} - {tr('Corners')}.html")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export Corner Report..."), default,
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
                writer = QPdfWriter(filename)
                writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
                writer.setPageOrientation(QPageLayout.Orientation.Landscape)
                writer.setResolution(96)  # page sizes in screen pixels, like the HTML report
                document.print_(writer)
                if not os.path.isfile(filename):
                    raise OSError(tr("Unable to write file"))
            else:
                with open(filename, "w", encoding="utf-8") as file:
                    file.write(report)
        except OSError as error:
            logger.error("LAP VIEWER: unable to export %s: %s", filename, error)
            self.set_status(trm(f"Unable to export lap: {error}"))
            return False
        self.set_status(trm(f"Exported: {html.escape(os.path.basename(filename))}"))
        return True

    @Slot("QVariant")
    def saveImage(self, image):
        """Save page picture (charts, map) to PNG file"""
        if not isinstance(image, QImage) or image.isNull():
            return
        default = os.path.join(self.folder, f"{self._track or 'laps'}.png")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export Picture..."), default, "PNG (*.png)")
        if filename:
            if image.save(filename, b"PNG"):
                self.set_status(trm(f"Exported: {html.escape(os.path.basename(filename))}"))
            else:
                self.set_status(trm(f"Unable to save picture: {html.escape(os.path.basename(filename))}"))

    @Slot("QVariant")
    def copyImage(self, image):
        """Page picture to clipboard (paste in Discord...)"""
        if isinstance(image, QImage) and not image.isNull():
            QApplication.clipboard().setImage(image)
            self.set_status(tr("Picture copied to clipboard."))

    @Slot(float, float)
    def exportPassageCsv(self, start: float, end: float):
        """Displayed charts of displayed laps between markers A & B to CSV, every meter"""
        if not self.data.laps:
            self.set_status(tr("Check laps to export first."))
            return
        low, high = sorted((self.data.distance_at_x(start), self.data.distance_at_x(end)))
        default = os.path.join(self.folder, f"{self._track or 'laps'} {low:.0f}-{high:.0f}m.csv")
        filename, _ = QFileDialog.getSaveFileName(self._window, tr("Export CSV..."), default, "CSV (*.csv)")
        if filename:
            self.write_csv(filename, "", low, high, background=True)
