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
Race calculator, scenarios & extras: drivers, safety car, rain, strategy comparison, driving
time, plan against race, class rivals, race clock, plan export (text, Discord, CSV) & share code

Inputs connect to CalculatorPanel.update_input (fuel_calculator.py), results are filled by it.
"""

from __future__ import annotations

import base64
import binascii
import csv
import json
import zlib
from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QWidget,
)

from ..fuel_strategy import MAX_DRIVERS, Strategy, Variant, driver_table_text, parse_driver_table, race_result
from ..i18n import tr
from ..module_info import StintDataSet
from ..race_live import Rival
from .race_widgets import Card, double_box, muted_label, set_warning, spin_box

DRIVER_COLORS = ("#4C9AFF", "#F5A623", "#7ED321", "#BD10E0", "#50E3C2", "#E94B3C", "#B8E986", "#9013FE", "#F8E71C")
SAFETY_CAR_COLOR = "#F8E71C"
RAIN_COLOR = "#4FC3F7"
SHARE_CODE_PREFIX = "TPRP1:"  # race plan share code, version 1


def clock_text(seconds: float) -> str:
    """Race time as h:mm"""
    minutes = int(max(seconds, 0) // 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def day_time_text(start_minutes: int, seconds: float) -> str:
    """Time of day (hh:mm) of race clock seconds, race started at start_minutes after midnight"""
    minutes = int((start_minutes * 60 + max(seconds, 0)) // 60) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def duration_text(seconds: float) -> str:
    """Race duration as h:mm:ss"""
    seconds = round(max(seconds, 0))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def read_only_table(columns: Sequence[str], parent: QWidget) -> QTableWidget:
    """Result table: no selection, no edit, columns sized to fit"""
    table = QTableWidget(0, len(columns), parent)
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.setFrameShape(QFrame.Shape.NoFrame)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def fill_table(table: QTableWidget, rows: Sequence[Sequence[str]], bold_row: int = -1, max_rows: int = 12):
    """Cells updated in place, table as high as its rows (up to max_rows)"""
    table.setUpdatesEnabled(False)
    table.setRowCount(len(rows))
    for row, texts in enumerate(rows):
        for column, text in enumerate(texts):
            item = table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, column, item)
            if item.text() != text:
                item.setText(text)
            font = item.font()
            if font.bold() != (row == bold_row):
                font.setBold(row == bold_row)
                item.setFont(font)
    table.setUpdatesEnabled(True)
    visible = min(max(len(rows), 1), max_rows)
    table.setFixedHeight(table.horizontalHeader().sizeHint().height()
                         + table.verticalHeader().defaultSectionSize() * visible + 4)


class DriverInputs(Card):
    """Drivers: stints before next driver, pace & driving time limits of each driver"""

    def __init__(self, parent, changed: Callable[[], None]):
        super().__init__(parent, tr("Drivers"))
        self.stints_per_driver = spin_box(9, minimum=1, tooltip=tr("Stints driven before the next driver takes over"))
        self.stints_per_driver.valueChanged.connect(changed)
        self.grid.addWidget(QLabel(tr("Stints per Driver")), 0, 0, 1, 2)  # whole title: over 2 columns
        self.grid.addWidget(self.stints_per_driver, 0, 2, 1, 2)
        header = (muted_label(tr("Driver")), muted_label(tr("Pace")), muted_label(tr("Min")), muted_label(tr("Max")))
        header[1].setToolTip(tr("Lap time difference of the driver (seconds)"))
        header[2].setToolTip(tr("Total driving time the driver must reach (minutes), 0 = none"))
        header[3].setToolTip(tr("Total driving time allowed to the driver (minutes), 0 = none"))
        for column, label in enumerate(header):
            self.grid.addWidget(label, 1, column)
        self.rows: list[tuple[QLabel, QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox]] = []
        for index in range(MAX_DRIVERS):
            label = QLabel(str(index + 1))
            pace = double_box(9, 2, 0.1, "s")
            pace.setMinimum(-9)
            minimum = double_box(9999, 0, 10.0, "min")
            maximum = double_box(9999, 0, 10.0, "min")
            for column, widget in enumerate((label, pace, minimum, maximum)):
                self.grid.addWidget(widget, index + 2, column)
            for box in (pace, minimum, maximum):
                box.valueChanged.connect(changed)
            self.rows.append((label, pace, minimum, maximum))
        self.grid.setColumnStretch(0, 0)
        self.set_count(1)

    def set_count(self, drivers: int):
        """Rows of the drivers taking turns shown (card hidden for one driver)"""
        self.setHidden(drivers < 2)
        for index, widgets in enumerate(self.rows):
            for widget in widgets:
                widget.setHidden(index >= drivers)

    def values(self) -> list[tuple[float, float, float]]:
        return [(pace.value(), minimum.value(), maximum.value()) for _, pace, minimum, maximum in self.rows]

    def table_text(self) -> str:
        return driver_table_text(self.values())

    def set_table_text(self, text: str):
        rows = parse_driver_table(text)
        for index, (_, pace, minimum, maximum) in enumerate(self.rows):
            values = rows[index] if index < len(rows) else (0.0, 0.0, 0.0)
            pace.setValue(values[0])
            minimum.setValue(values[1])
            maximum.setValue(values[2])


class SafetyCarInputs(Card):
    """Safety car scenario: laps under safety car, consumption & lap time, opportunistic stop"""

    def __init__(self, parent, changed: Callable[[], None]):
        super().__init__(parent, tr("Safety Car"))
        self.enabled = QCheckBox(tr("Safety Car Scenario"))
        self.enabled.setToolTip(tr("Plan with a safety car (or full course yellow) period"))
        self.lap = spin_box(9999, tr("lap"), minimum=1, tooltip=tr("First lap under safety car (lap of the plan)"))
        self.laps = spin_box(99, tr("lap"), minimum=1, tooltip=tr("Laps under safety car"))
        self.consumption = double_box(100, 0, 5.0, "%", tr("Consumption under safety car, % of race pace"))
        self.laptime = double_box(500, 0, 10.0, "%", tr("Lap time under safety car, % of race pace"))
        self.wear = double_box(100, 0, 5.0, "%", tr("Tyre wear under safety car, % of race pace"))
        self.pit = QCheckBox(tr("Stop under Safety Car"))
        self.pit.setToolTip(tr("Stop at the end of the first lap under safety car"))
        self.pit_saving = double_box(100, 0, 10.0, "%", tr("Part of pit lane time not lost under safety car"))
        self.grid.addWidget(self.enabled, 0, 0, 1, 2)
        self.add_row(tr("From Lap"), self.lap, 1)
        self.add_row(tr("Laps"), self.laps, 2)
        self.add_row(tr("Consumption"), self.consumption, 3)
        self.add_row(tr("Lap Time"), self.laptime, 4)
        self.add_row(tr("Tyre Wear"), self.wear, 5)
        self.grid.addWidget(self.pit, 6, 0, 1, 2)
        self.add_row(tr("Pit Time Saved"), self.pit_saving, 7)
        self.label_result = muted_label("")
        self.label_result.setWordWrap(True)
        self.grid.addWidget(self.label_result, 8, 0, 1, 2)
        for box in (self.lap, self.laps, self.consumption, self.laptime, self.wear, self.pit_saving):
            box.valueChanged.connect(changed)
        for check in (self.enabled, self.pit):
            check.toggled.connect(changed)
        self.enabled.toggled.connect(self.show_enabled)
        self.show_enabled(False)

    def show_enabled(self, enabled: bool):
        for widget in (self.lap, self.laps, self.consumption, self.laptime, self.wear, self.pit, self.pit_saving):
            widget.setEnabled(enabled)

    def set_result(self, strategy: Strategy, without: Strategy | None):
        """Plan with safety car against plan without"""
        if not self.enabled.isChecked() or without is None or not strategy.ready or not without.ready:
            self.label_result.setText("")
            return
        stops = len(strategy.stops) - len(without.stops)
        laps = strategy.race_laps - without.race_laps
        parts = [f"{tr('Without safety car')}: {len(without.stops)} {tr('stop(s)')}, {without.race_laps} {tr('laps')}",
                 f"{tr('With safety car')}: {stops:+d} {tr('stop(s)')}, {laps:+d} {tr('laps')}"]
        stop = next((stop for stop in strategy.stops if stop.safety_car), None)
        if stop is not None:
            parts.append(f"{tr('Stop under safety car at lap')} {stop.lap} ({stop.seconds:.1f} s)")
        if not strategy.safety_car[1]:
            parts.append(tr("Safety car after the finish: no effect"))
        self.label_result.setText("<br>".join(parts))


class RainInputs(Card):
    """Rain scenario: laps in the wet, consumption & lap time, wet tyres fitted & taken off"""

    def __init__(self, parent, changed: Callable[[], None]):
        super().__init__(parent, tr("Rain"))
        self.enabled = QCheckBox(tr("Rain Scenario"))
        self.enabled.setToolTip(tr("Plan with a wet period"))
        self.lap = spin_box(9999, tr("lap"), minimum=1, tooltip=tr("First lap in the wet (lap of the plan)"))
        self.laps = spin_box(9999, tr("lap"), tooltip=tr("Laps in the wet, 0 = until the finish"))
        self.consumption = double_box(200, 0, 5.0, "%", tr("Consumption in the wet, % of race pace"))
        self.laptime = double_box(500, 0, 5.0, "%", tr("Lap time in the wet, % of race pace"))
        self.tyres = QCheckBox(tr("Wet Tyres"))
        self.tyres.setToolTip(tr("Stop for wet tyres at the end of the first lap in the wet, "
                                 "and for slicks at the end of the last one (4 tyres)"))
        self.grid.addWidget(self.enabled, 0, 0, 1, 2)
        self.add_row(tr("From Lap"), self.lap, 1)
        self.add_row(tr("Laps"), self.laps, 2)
        self.add_row(tr("Consumption"), self.consumption, 3)
        self.add_row(tr("Lap Time"), self.laptime, 4)
        self.grid.addWidget(self.tyres, 5, 0, 1, 2)
        self.label_result = muted_label("")
        self.label_result.setWordWrap(True)
        self.grid.addWidget(self.label_result, 6, 0, 1, 2)
        for box in (self.lap, self.laps, self.consumption, self.laptime):
            box.valueChanged.connect(changed)
        for check in (self.enabled, self.tyres):
            check.toggled.connect(changed)
        self.enabled.toggled.connect(self.show_enabled)
        self.show_enabled(False)

    def show_enabled(self, enabled: bool):
        for widget in (self.lap, self.laps, self.consumption, self.laptime, self.tyres):
            widget.setEnabled(enabled)

    def set_result(self, strategy: Strategy, without: Strategy | None):
        """Plan with rain against plan without"""
        if not self.enabled.isChecked() or without is None or not strategy.ready or not without.ready:
            self.label_result.setText("")
            return
        if not strategy.rain[0]:
            self.label_result.setText(tr("Rain after the finish: no effect"))
            return
        stops = len(strategy.stops) - len(without.stops)
        laps = strategy.race_laps - without.race_laps
        parts = [f"{tr('Without rain')}: {len(without.stops)} {tr('stop(s)')}, {without.race_laps} {tr('laps')}",
                 f"{tr('With rain')}: {stops:+d} {tr('stop(s)')}, {laps:+d} {tr('laps')}"]
        for stop in strategy.stops:
            if stop.reason in ("rain", "dry"):
                name = tr("Wet tyres at lap") if stop.reason == "rain" else tr("Slicks at lap")
                parts.append(f"{name} {stop.lap} ({stop.seconds:.1f} s)")
        self.label_result.setText("<br>".join(parts))


class TimeEdit(QTimeEdit):
    """Wheel changes value only once focused, so scrolling the page never edits it"""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class RaceClockInput(QWidget):
    """Time of day of race start (hh:mm, midnight included), unchecked: race time shown"""

    def __init__(self, changed: Callable[[], None]):
        super().__init__()
        self.check = QCheckBox()
        self.check.setToolTip(tr("Pit stops shown at their time of day, unchecked: race time"))
        self.edit = TimeEdit()
        self.edit.setDisplayFormat("HH:mm")
        self.edit.setKeyboardTracking(False)
        self.edit.setToolTip(tr("Time of day of the race start"))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.check)
        layout.addWidget(self.edit, stretch=1)
        self.check.toggled.connect(self.edit.setEnabled)
        self.check.toggled.connect(changed)
        self.edit.timeChanged.connect(changed)
        self.edit.setEnabled(False)

    def minutes(self) -> int:
        """Minutes after midnight, -1 = not set"""
        if not self.check.isChecked():
            return -1
        time = self.edit.time()
        return time.hour() * 60 + time.minute()

    def set_minutes(self, minutes: int):
        minutes = int(minutes)
        valid = 0 <= minutes < 24 * 60
        if valid:
            self.edit.setTime(QTime(minutes // 60, minutes % 60))
        self.check.setChecked(valid)


class ComparisonCard(Card):
    """Strategies side by side: stops, saving needed, lap time lost, race result"""

    def __init__(self, parent, symbol_fuel: str):
        super().__init__(parent, tr("Strategy Comparison"))
        self.table = read_only_table((
            tr("Pit Stops"), f"{tr('Fuel')} ({symbol_fuel})", f"{tr('Energy')} (%)", tr("Saving Cost"),
            tr("Pit Time"), tr("Laps"), tr("Race Time"), tr("Gap")), self)
        self.table.setToolTip(tr("Plans with fewer stops (fuel saving) or one stop more, "
                                 "best one in bold. Fuel & energy per lap, lap time lost to saving."))
        hint = muted_label(tr("Saving cost (Pace card) slows the laps of plans saving fuel."))
        hint.setWordWrap(True)
        self.grid.addWidget(self.table, 0, 0)
        self.grid.addWidget(hint, 1, 0)

    def set_variants(self, variants: Sequence[Variant], has_energy: bool):
        self.setHidden(len(variants) < 2)
        if len(variants) < 2:
            return
        best = min(variants, key=lambda variant: race_result(variant.strategy))
        rows = []
        for variant in variants:
            strategy = variant.strategy
            if strategy.race_laps != best.strategy.race_laps:
                gap = f"{strategy.race_laps - best.strategy.race_laps:+d} {tr('laps')}"
            else:
                gap = f"{strategy.race_seconds - best.strategy.race_seconds:+.1f} s"
            name = f"{variant.stops}" + (f" ({tr('now')})" if variant.current else "")
            rows.append((
                name, f"{variant.fuel:.3f}", f"{variant.energy:.3f}" if has_energy else "-",
                f"{variant.lap_cost:+.2f} s" if variant.lap_cost else "-",
                f"{strategy.pit_seconds:.0f} s", str(strategy.race_laps),
                duration_text(strategy.race_seconds), gap if variant is not best else "-",
            ))
        fill_table(self.table, rows, bold_row=list(variants).index(best))
        self.table.setColumnHidden(2, not has_energy)


class DriverTimesCard(Card):
    """Driving time of each driver: stints, time, limits not met"""

    def __init__(self, parent):
        super().__init__(parent, tr("Driving Time"))
        self.table = read_only_table((tr("Driver"), tr("Stints"), tr("Time"), tr("Limits")), self)
        self.grid.addWidget(self.table, 0, 0)

    def set_strategy(self, strategy: Strategy, drivers: int,
                     limits: Sequence[tuple[float, float, float]]):
        self.setHidden(drivers < 2 or not strategy.ready)
        if self.isHidden():
            return
        issues = dict.fromkeys(driver for driver, _ in strategy.driver_issues)
        rows = []
        for index in range(drivers):
            stints = sum(1 for driver in strategy.stint_drivers if driver == index + 1)
            seconds = strategy.driver_seconds[index] if index < len(strategy.driver_seconds) else 0.0
            _, minimum, maximum = limits[index] if index < len(limits) else (0.0, 0.0, 0.0)
            limit = " / ".join(text for text in (
                f"≥ {minimum:g} min" if minimum else "", f"≤ {maximum:g} min" if maximum else "") if text)
            problems = [kind for driver, kind in strategy.driver_issues if driver == index + 1]
            if problems:
                limit += "  " + " · ".join(tr("below minimum") if kind == "min" else tr("above maximum")
                                            for kind in problems)
            rows.append((str(index + 1), str(stints), duration_text(seconds), limit or "-"))
        fill_table(self.table, rows, max_rows=MAX_DRIVERS)
        set_warning(self.label_title, bool(issues))


def plan_markdown(title: str, header: Sequence[str], rows: Sequence[Sequence[str]], footer: str = "") -> str:
    """Pit stop plan for Discord: title in bold, table in a code block (columns aligned)"""
    widths = [max(len(str(row[column])) for row in (header, *rows)) for column in range(len(header))]
    lines = [" | ".join(str(text).ljust(width) for text, width in zip(row, widths)).rstrip()
             for row in (header, *rows)]
    lines.insert(1, "-+-".join("-" * width for width in widths))
    text = f"**{title}**\n```\n" + "\n".join(lines) + "\n```"
    return text + (f"\n{footer}" if footer else "")


def write_plan_csv(filename: str, header: Sequence[str], rows: Sequence[Sequence[str]]):
    """Pit stop plan as spreadsheet (CSV)"""
    with open(filename, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)


class PlanVsRaceCard(Card):
    """Stints of the race (stint history of live session) against stints of the plan"""

    def __init__(self, parent, symbol_fuel: str):
        super().__init__(parent, tr("Plan against Race"))
        self.table = read_only_table((
            tr("Stint"), tr("Laps"), tr("Lap Time"), f"{tr('Fuel')} ({symbol_fuel}/{tr('lap')})",
            f"{tr('Energy')} (%/{tr('lap')})", f"{tr('Tyre Wear')} (%)"), self)
        self.table.setToolTip(tr("Stints driven (consumption history of this race) against the plan: "
                                 "race value / plan value"))
        self.grid.addWidget(self.table, 0, 0)
        self.setHidden(True)

    def set_stints(self, stints: Sequence[StintDataSet], strategy: Strategy, setup_fuel: float,
                   setup_energy: float, laptime: float, unit_fuel: Callable[[float], float], has_energy: bool):
        """Stints done (oldest first) against stints planned before the race"""
        done = [stint for stint in stints if stint.totalLaps > 0]
        self.setHidden(not done)
        if not done:
            return
        rows = []
        for index, stint in enumerate(done):
            laps = stint.totalLaps
            planned = strategy.stints[index] if index < len(strategy.stints) else 0
            planned_time = (strategy.stint_seconds[index] / planned) if planned else laptime
            fuel = unit_fuel(stint.totalFuel) / laps
            energy = stint.totalEnergy / laps
            rows.append((
                str(index + 1), f"{laps} / {planned or '-'}",
                f"{stint.totalTime / laps:.2f} / {planned_time:.2f}",
                f"{fuel:.3f} / {setup_fuel:.3f}",
                f"{energy:.3f} / {setup_energy:.3f}" if has_energy else "-",
                f"{stint.totalTyreWear:.1f}",
            ))
        fill_table(self.table, rows)
        self.table.setColumnHidden(4, not has_energy)


class RivalsCard(Card):
    """Cars of the player class: place, laps, stops, laps since last stop, next stop expected"""

    def __init__(self, parent):
        super().__init__(parent, tr("Class Rivals"))
        self.table = read_only_table((
            tr("Place"), tr("Driver"), tr("Laps"), tr("Pit Stops"), tr("Since Stop"), tr("Next Stop")), self)
        self.table.setToolTip(tr("Cars of your class in the live race. Next stop: lap of last stop seen "
                                 "(while the page is open) plus your full tank laps, ~ when unknown"))
        self.grid.addWidget(self.table, 0, 0)
        self.setHidden(True)

    def set_rivals(self, rivals: Sequence[Rival], stint_laps: int):
        """Rivals by place, next stop from your stint length (same class, close consumption)"""
        self.setHidden(len(rivals) < 2)
        if len(rivals) < 2:
            return
        rows = []
        player_row = -1
        for row, rival in enumerate(rivals):
            if rival.player:
                player_row = row
            since = rival.laps - rival.last_stop_lap if rival.last_stop_lap else rival.laps
            known = bool(rival.last_stop_lap) or rival.stops == 0
            next_stop = rival.laps - since + stint_laps if stint_laps else 0
            rows.append((
                str(rival.place), rival.driver, str(rival.laps),
                str(rival.stops) + (f" ({tr('pit')})" if rival.in_pits else ""),
                str(since) if known else f"~{since}",
                (str(next_stop) if known else f"~{next_stop}") if stint_laps else "-",
            ))
        fill_table(self.table, rows, bold_row=player_row, max_rows=20)


def encode_share_code(data: dict) -> str:
    """Race plan as one line of text, to paste in a chat"""
    raw = zlib.compress(json.dumps(data, separators=(",", ":")).encode("utf-8"), 9)
    return SHARE_CODE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def decode_share_code(text: str) -> dict:
    """Race plan of a share code, ValueError when not a race plan code"""
    text = "".join(str(text).split())  # line breaks of a chat left out
    if not text.startswith(SHARE_CODE_PREFIX):
        raise ValueError("not a race plan share code")
    try:
        data = json.loads(zlib.decompress(base64.urlsafe_b64decode(text[len(SHARE_CODE_PREFIX):])))
    except (binascii.Error, zlib.error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("damaged race plan share code") from error
    if not isinstance(data, dict):
        raise ValueError("not a race plan")
    return data
