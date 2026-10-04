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
Race calculator, fuel side: inputs, results & consumption history

CalculatorPanel holds every input & result of the fuel strategy: lap & consumption, race setup,
start amounts, tyre wear (used by the strategy to propose tyre changes). Race calculator page
(race_calculator.py) places its parts: race setup & key figures above the tabs, fuel inputs &
results in the fuel tab, tyre wear & tyre life in the tyre tab. A tyre plan linked to it (see
TyreLink) adds its tyre change time to each stop and gets one row per stint.

Every input change recalculates at once (one calculation per change, see CalculatorPanel.batch),
inputs are kept for next time. Pit stop plan: see fuel_strategy.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from math import ceil, floor
from typing import Protocol

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import calculation as calc
from .. import units
from ..api_control import api
from ..const_file import ConfigType
from ..formatter import laptime_string_to_seconds
from ..fuel_strategy import Strategy, StrategyInput, plan, representative_laps, saving_target, target_consumption
from ..i18n import tr, trm
from ..module_info import ConsumptionDataSet
from ..setting import cfg
from ._common import NumericTableItem, UIScaler
from .race_widgets import (
    INVALID_COLOR,
    TYRE_COLOR,
    Card,
    KpiTile,
    double_box,
    laps_text,
    muted_label,
    set_warning,
    spin_box,
    value_label,
)

VALID_ROLE = Qt.ItemDataRole.UserRole + 1  # history item: lap is valid
INDEX_ROLE = Qt.ItemDataRole.UserRole + 2  # history item: index of lap in history data
RACE_SESSION = 4


class TyreLink(Protocol):
    """Tyre plan linked to the fuel strategy (tyre tab)"""

    def stop_change_times(self) -> list[float]:
        """Tyre change seconds of each stop (row after start)"""

    def stop_tyre_changes(self) -> list[int]:
        """Tyres changed at each stop, empty list if no tyre planned"""

    def set_stints(self, strategy: Strategy) -> None:
        """One row per stint of a ready strategy (manual rows otherwise)"""

    def has_tyres(self) -> bool:
        """Any tyre on a wheel of the plan"""

    def full_change_seconds(self) -> float:
        """Time to change 4 tyres (tyre rules)"""

    def start_tread(self, default: float) -> float:
        """Tread of tyres at start: tyres of first stint, else default"""

    def fresh_tread(self) -> float:
        """Tread of new tyres of compound selected in stock"""

    def wear_factor(self) -> float:
        """Wear of compound selected in stock relative to measured compound"""


# Saved inputs (config "fuel_calculator"): key, default
SAVED_INPUTS = {
    "input_lap_time": 0.0,
    "input_fuel_per_lap": 0.0,
    "input_energy_per_lap": 0.0,
    "input_tank_capacity": 0.0,
    "enable_lap_race": False,
    "input_race_minutes": 0,
    "input_race_laps": 0,
    "input_formation_laps": 0.0,
    "input_pit_seconds": 0.0,
    "input_safety_margin": 0.0,
    "input_fuel_start": 0.0,
    "input_energy_start": 0.0,
    "input_tread_start": 100.0,
    "input_wear_per_lap": 0.0,
    "input_minimum_tread": 0.0,
    "input_refuel_rate": 0.0,
    "input_energy_rate": 0.0,
    "enable_tyres_during_refuel": False,
    "input_driver_change_seconds": 0.0,
    "input_minimum_stops": 0,
    "input_max_stint_minutes": 0.0,
    "input_drivers": 1,
    "input_fuel_effect": 0.0,
    "input_track_evolution": 0.0,
    "input_target_stint_laps": 0,
}


def live_race_length() -> tuple[str, int] | None:
    """Race length of live race session: ("minutes" | "laps", value), None if not in a race"""
    session = api.read.session
    if session.session_type() != RACE_SESSION:
        return None
    if session.finish_type() == 1:  # laps only
        laps = api.read.lap.maximum()
        return ("laps", laps) if 0 < laps < 100000 else None
    minutes = round((session.end() - max(session.start(), 0)) / 60)
    return ("minutes", minutes) if minutes > 0 else None


class PitStopPreview(QWidget):
    """Strategy timeline: race laps left to right, one block per stint, pit lap above each stop,
    tyre changes marked"""

    def __init__(self, parent):
        super().__init__(parent)
        self.strategy = Strategy()
        self.setFixedHeight(UIScaler.size(4.4))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @property
    def pit_laps(self) -> list[int]:
        return [stop.lap for stop in self.strategy.stops]

    def set_strategy(self, strategy: Strategy):
        self.strategy = strategy
        self.update()

    def paintEvent(self, event):
        """Draw"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        metrics = self.fontMetrics()
        text_h = metrics.height()
        width, height = self.width(), self.height()
        muted = palette.placeholderText().color()

        strategy = self.strategy
        total = strategy.race_laps
        if not strategy.ready:
            painter.setPen(muted)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             tr("Enter lap time, consumption and race length"))
            return

        pad = metrics.horizontalAdvance(str(total)) / 2 + 2
        left, right = pad, width - pad
        # Rows: pit laps, bar (stint lengths inside), lap ticks & first / last lap
        bar = QRectF(left, text_h + 5, right - left, max(height - text_h * 2 - 12, text_h * 0.6))
        radius = min(bar.height() / 2, 6)

        # Stints: blocks between pit stops, alternating shade
        bounds = [0]
        for stint in strategy.stints:
            bounds.append(bounds[-1] + stint)
        highlight = palette.highlight().color()
        gap = 2.0
        last = len(bounds) - 2
        for index in range(len(bounds) - 1):
            x0 = left + bounds[index] / total * bar.width() + (gap / 2 if index else 0)
            x1 = left + bounds[index + 1] / total * bar.width() - (gap / 2 if index < last else 0)
            color = QColor(highlight)
            color.setAlphaF(0.85 if index % 2 == 0 else 0.55)
            block = QRectF(x0, bar.top(), max(x1 - x0, 1), bar.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(block, radius, radius)
            if block.width() > metrics.horizontalAdvance("00") + 6:  # stint length inside block
                painter.setPen(palette.highlightedText().color())
                painter.drawText(block, Qt.AlignmentFlag.AlignCenter, str(bounds[index + 1] - bounds[index]))

        # Lap ticks below bar, first & last lap
        painter.setPen(QPen(muted))
        step = max(1, ceil(total / max(width / (metrics.horizontalAdvance("000") * 2), 1)))
        for lap in range(0, total + 1, step):
            x = left + lap / total * bar.width()
            painter.drawLine(int(x), int(bar.bottom() + 2), int(x), int(bar.bottom() + 5))
        for lap in (0, total):
            x = left + lap / total * bar.width()
            painter.drawText(QRectF(x - pad * 2, bar.bottom() + 5, pad * 4, text_h),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, str(lap))
        # Pit laps above bar, tyre change in tyre color. Labels never overlap: short label
        # (lap number only) when the full one does not fit, none when even that does not fit.
        label_end = -1.0
        for stop in strategy.stops:
            x = left + stop.lap / total * bar.width()
            color = QColor(TYRE_COLOR) if stop.tyres else palette.windowText().color()
            painter.setPen(color)
            painter.drawLine(int(x), int(text_h + 1), int(x), int(bar.top() - 1))
            for label in (f"{tr('Lap')} {stop.lap}", str(stop.lap)):
                label_w = metrics.horizontalAdvance(label) + 6
                label_x = min(max(x - label_w / 2, 0), width - label_w)  # kept inside widget
                if label_x >= label_end:
                    painter.drawText(QRectF(label_x, 0, label_w, text_h), Qt.AlignmentFlag.AlignCenter, label)
                    label_end = label_x + label_w
                    break


class HistoryPanel(QFrame):
    """History data panel"""

    def __init__(self, parent):  # race calculator page: column menus
        super().__init__(parent)
        self.setObjectName("fuelCard")
        # Set (freeze) fuel unit
        self.unit_fuel = units.set_unit_fuel(cfg.units["fuel_unit"])
        self.symbol_fuel = units.set_symbol_fuel(cfg.units["fuel_unit"])

        headers = (
            tr("Lap"),
            tr("Time"),
            f"{tr('Fuel')} ({self.symbol_fuel})",
            f"{tr('Energy')} (%)",
            tr("F/E Ratio"),
            f"{tr('Drain')} (%)",
            f"{tr('Regen')} (%)",
            f"{tr('Net')} (%)",
            f"{tr('Tyre')} (%)",
            f"{tr('Tank')} ({self.symbol_fuel})",
        )

        title = QLabel(tr("Consumption History"))
        title.setObjectName("fuelCardTitle")
        button_columns = QPushButton(tr("Columns"))
        button_columns.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button_columns.clicked.connect(
            lambda: parent.column_menu(button_columns.mapToGlobal(button_columns.rect().bottomLeft())))
        layout_title = QHBoxLayout()
        layout_title.addWidget(title, stretch=1)
        layout_title.addWidget(button_columns)
        hint = muted_label(tr("Select laps, then add them: their average goes to the calculator, "
                              "invalid laps (red) left out."))
        hint.setWordWrap(True)
        self.dataset: list[ConsumptionDataSet] = []
        self.check_valid_only = QCheckBox(tr("Valid Laps Only"))
        self.check_valid_only.setChecked(bool(cfg.user.config["fuel_calculator"].get("enable_valid_laps_only")))
        self.check_valid_only.toggled.connect(self.toggle_valid_only)
        layout_title.insertWidget(1, self.check_valid_only)

        self.table_history = QTableWidget(self)
        self.table_history.setColumnCount(len(headers))
        self.table_history.setHorizontalHeaderLabels(headers)
        self.table_history.verticalHeader().setVisible(False)
        self.table_history.setShowGrid(False)
        self.table_history.setAlternatingRowColors(True)
        self.table_history.setWordWrap(False)
        self.table_history.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_history.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_history.setFrameShape(QFrame.Shape.NoFrame)
        header = self.table_history.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(parent.table_header_menu)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # newest first until a column is clicked
        self.table_history.setSortingEnabled(True)
        self.table_history.setMinimumHeight(UIScaler.size(14))
        self.toggle_column()

        self.label_empty = muted_label(tr("No lap recorded yet: drive a few laps, or load a file."))
        self.label_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_empty.setWordWrap(True)
        self.label_added = muted_label("")

        self.button_adddata = QPushButton(tr("Add Selected Data"))
        self.button_adddata.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button_delete = QPushButton(tr("Delete Selected"))
        self.button_delete.setToolTip(tr("Delete selected laps from consumption history"))
        self.button_delete.clicked.connect(lambda: parent.delete_laps(self.selected_indexes()))
        self.button_delete_all = QPushButton(tr("Delete All"))
        self.button_delete_all.setToolTip(tr("Delete whole consumption history of this track & class"))
        self.button_delete_all.clicked.connect(lambda: parent.delete_laps(None))
        layout_buttons = QHBoxLayout()
        for button in (self.button_delete, self.button_delete_all):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            layout_buttons.addWidget(button)
        layout_buttons.addWidget(self.button_adddata, stretch=1)

        layout = QVBoxLayout(self)
        margin = UIScaler.pixel(10)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(UIScaler.pixel(6))
        layout.addLayout(layout_title)
        layout.addWidget(hint)
        layout.addWidget(self.table_history, stretch=1)
        layout.addWidget(self.label_empty, stretch=1)
        layout.addWidget(self.label_added)
        layout.addLayout(layout_buttons)

    def toggle_column(self):
        """Toggle column visibility"""
        config = cfg.user.config["fuel_calculator"]
        self.table_history.setColumnHidden(4, not config["show_column_fuel_ratio"])
        self.table_history.setColumnHidden(5, not config["show_column_battery_drain"])
        self.table_history.setColumnHidden(6, not config["show_column_battery_regen"])
        self.table_history.setColumnHidden(7, not config["show_column_battery_net_change"])
        self.table_history.setColumnHidden(8, not config["show_column_tyre_wear"])
        self.table_history.setColumnHidden(9, not config["show_column_tank_capacity"])

    def refresh(self, dataset: Sequence[ConsumptionDataSet]):
        """Refresh history data table (sorted by clicked column, numbers sorted by value)"""
        self.dataset = list(dataset)
        table = self.table_history
        invalid_color = QColor(INVALID_COLOR)
        flag_selectable = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        flag_unselectable = Qt.ItemFlag.NoItemFlags

        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)  # rows filled in history order, sorted once filled
        table.clearContents()
        table.setRowCount(len(dataset))  # rows set at once, not one insert per lap
        for row_index, lap_data in enumerate(dataset):
            valid = bool(lap_data.isValidLap)
            highlight_color = None if valid else invalid_color
            fuel = self.unit_fuel(lap_data.lastLapUsedFuel)
            ratio = calc.fuel_to_energy_ratio(lap_data.lastLapUsedFuel, lap_data.lastLapUsedEnergy)
            net = lap_data.batteryRegenLast - lap_data.batteryDrainLast
            tank = self.unit_fuel(lap_data.capacityFuel)
            row_items: tuple[tuple, ...] = (
                ("lap", lap_data.lapNumber, f"{lap_data.lapNumber}", flag_unselectable),
                ("time", lap_data.lapTimeLast, calc.sec2laptime_full(lap_data.lapTimeLast), flag_selectable, highlight_color),
                ("fuel", fuel, f"{fuel:.3f}", flag_selectable, highlight_color),
                ("energy", lap_data.lastLapUsedEnergy, f"{lap_data.lastLapUsedEnergy:.3f}", flag_selectable, highlight_color),
                ("ratio", ratio, f"{ratio:.3f}", flag_unselectable),
                ("drain", lap_data.batteryDrainLast, f"{lap_data.batteryDrainLast:.3f}", flag_unselectable),
                ("regen", lap_data.batteryRegenLast, f"{lap_data.batteryRegenLast:.3f}", flag_unselectable),
                ("net", net, f"{net:+.3f}", flag_unselectable),
                ("tyre", lap_data.tyreAvgWearLast, f"{lap_data.tyreAvgWearLast:.3f}", flag_selectable),
                ("tank", tank, f"{tank:.3f}", flag_selectable),
            )
            for column_index, item in enumerate(row_items):
                table_item = self._add_table_item(*item)
                table_item.setData(VALID_ROLE, valid)
                table_item.setData(INDEX_ROLE, row_index)
                table.setItem(row_index, column_index, table_item)
        table.setSortingEnabled(True)
        table.setUpdatesEnabled(True)
        has_rows = table.rowCount() > 0
        table.setHidden(not has_rows)
        self.label_empty.setHidden(has_rows)
        for button in (self.button_adddata, self.button_delete, self.button_delete_all):
            button.setEnabled(has_rows)
        self.toggle_valid_only(self.check_valid_only.isChecked())

    def toggle_valid_only(self, checked: bool):
        """Invalid laps hidden (filter kept for next time)"""
        table = self.table_history
        for row_index in range(table.rowCount()):
            item = table.item(row_index, 1)
            table.setRowHidden(row_index, checked and item is not None and not item.data(VALID_ROLE))
        config = cfg.user.config["fuel_calculator"]
        if config.get("enable_valid_laps_only") != checked:
            config["enable_valid_laps_only"] = checked
            cfg.save(config_type=ConfigType.CONFIG)

    def selected_indexes(self) -> set[int]:
        """Indexes in history data of selected laps"""
        return {item.data(INDEX_ROLE) for item in self.table_history.selectedItems()}

    def _add_table_item(self, header: str, value: float, text: str, flags: Qt.ItemFlag, highlight_color=None):
        """Add table item, sorted by value"""
        item = NumericTableItem(value, text)
        item.setData(Qt.ItemDataRole.UserRole, header)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setFlags(flags)
        if highlight_color:
            item.setForeground(highlight_color)
        return item


class CalculatorPanel(QWidget):
    """Fuel tab: input cards on the left, results on the right

    Parts placed by the race calculator page elsewhere: card_race & tiles (above the tabs),
    card_tyre_input & card_tyre_life (tyre tab).
    """

    def __init__(self, parent):
        super().__init__(parent)
        # Set (freeze) fuel unit
        self.is_gallon = cfg.units["fuel_unit"] == "Gallon"
        self.unit_fuel = units.set_unit_fuel(cfg.units["fuel_unit"])
        self.symbol_fuel = units.set_symbol_fuel(cfg.units["fuel_unit"])
        self._batch = 1  # no calculation while inputs are built & loaded
        self._updating = False
        self.strategy = Strategy()
        self.tyre_link: TyreLink | None = None  # tyre plan of tyre tab, set by page
        self.proposed_tyre_rows: list[int] = []  # tyre plan rows (stints) needing new tyres (minimum tread)

        self.input_laptime = InputLapTime(self)
        self.input_fuel = InputFuel(self)
        self.input_race = InputRace(self)
        self.refill_fuel = InputRefill(self, "Fuel")
        self.refill_energy = InputRefill(self, "Energy")
        self.input_tyre = InputTyreWear(self)
        self.input_pit = InputPit(self)
        self.input_rules = InputRules(self)
        self.input_pace = InputPace(self)
        self.usage_fuel = OutputUsage(self)
        self.usage_energy = OutputUsage(self)
        self.pit_preview = PitStopPreview(self)

        # Inputs
        card_lap = Card(self, tr("Lap & Consumption"))
        card_lap.add_row(tr("Lap Time"), self.input_laptime, 0)
        card_lap.add_row(tr("Fuel per Lap"), self.input_fuel.fuel_used, 1)
        card_lap.add_row(tr("Energy per Lap"), self.input_fuel.energy_used, 2,
                         tooltip=tr("Virtual energy, 0 if the car has none"))
        card_lap.add_row(tr("Tank Capacity"), self.input_fuel.capacity, 3)
        card_lap.add_row(tr("F/E Ratio"), self.input_fuel.fuel_ratio, 4,
                         tooltip=tr("Fuel used per 1% of virtual energy"))
        self.label_fill_source = muted_label("")
        self.label_fill_source.setWordWrap(True)
        card_lap.grid.addWidget(self.label_fill_source, 5, 0, 1, 2)

        # Race setup, shared by both tabs (duration or laps in the same place), see arrange_top
        self.card_race = Card(self, tr("Race"))
        self.label_minutes = QLabel(tr("Duration"))
        self.label_laps = QLabel(tr("Race Laps"))
        self.race_pairs: list[tuple[QWidget, ...]] = [
            (QLabel(tr("Race Type")), self.input_race.mode_switch),
            (self.label_minutes, self.input_race.minutes, self.label_laps, self.input_race.laps),
        ]
        for title, editor, tooltip in (
            (tr("Formation / Rolling"), self.input_race.formation,
             tr("Laps driven before the race counts, fuel needed for them too")),
            (tr("Pit Stop Time"), self.input_race.pit_seconds,
             tr("Time lost per stop, tyre change time of the tyre plan added "
                "(time race: fewer laps fit in the race time)")),
            (tr("Safety Margin"), self.input_race.margin,
             tr("Laps of fuel kept in the tank at every stop and at the finish")),
        ):
            label = QLabel(title)
            label.setToolTip(tooltip)
            editor.setToolTip(tooltip)
            self.race_pairs.append((label, editor))

        card_start = Card(self, tr("Start"))
        card_start.add_row(tr("Starting Fuel"), self.refill_fuel.amount_start, 0,
                           tooltip=tr("0 = full tank, or exactly what the race needs without a stop"))
        card_start.add_row(tr("Starting Energy"), self.refill_energy.amount_start, 1,
                           tooltip=tr("0 = full, or exactly what the race needs without a stop"))
        hint = muted_label(tr("0 = full tank"))
        card_start.grid.addWidget(hint, 2, 1, Qt.AlignmentFlag.AlignRight)

        card_tyre_input = self.card_tyre_input = Card(self, tr("Tyre Wear"))
        card_tyre_input.add_row(tr("Starting Tread"), self.input_tyre.start_tread, 0)
        card_tyre_input.add_row(tr("Wear per Lap"), self.input_tyre.wear_lap, 1)
        card_tyre_input.add_row(tr("Minimum Tread"), self.input_tyre.minimum_tread, 2,
                                tooltip=tr("Tyres changed at the stop before tread would go below"))

        card_pit = Card(self, tr("Pit Stop"))
        card_pit.add_row(tr("Refuel Rate"), self.input_pit.refuel_rate, 0,
                         tooltip=tr("Fuel added per second, 0 = refuelling time included in pit stop time"))
        card_pit.add_row(tr("Energy Rate"), self.input_pit.energy_rate, 1,
                         tooltip=tr("Energy added per second, 0 = included in pit stop time"))
        card_pit.add_row(tr("Driver Change"), self.input_pit.driver_change, 2,
                         tooltip=tr("Time added to every stop when drivers take turns"))
        card_pit.grid.addWidget(self.input_pit.tyres_during_refuel, 3, 0, 1, 2)

        card_rules = Card(self, tr("Race Rules"))
        card_rules.add_row(tr("Mandatory Stops"), self.input_rules.minimum_stops, 0,
                           tooltip=tr("Stints shortened evenly until the race has at least this many stops"))
        card_rules.add_row(tr("Max Stint Time"), self.input_rules.max_stint_minutes, 1,
                           tooltip=tr("Driver limit: longest stint allowed, 0 = none"))
        card_rules.add_row(tr("Drivers"), self.input_rules.drivers, 2,
                           tooltip=tr("Drivers taking turns, one driver change at each stop"))

        card_pace = Card(self, tr("Pace"))
        card_pace.add_row(tr("Fuel Effect"), self.input_pace.fuel_effect, 0,
                          tooltip=tr("Lap time lost per 10 fuel units in the tank (lap time is the one at half tank)"))
        card_pace.add_row(tr("Track Evolution"), self.input_pace.track_evolution, 1,
                          tooltip=tr("Lap time change per hour of race, negative when the track gets faster"))

        column_inputs = QVBoxLayout()
        column_inputs.setContentsMargins(0, 0, 0, 0)
        column_inputs.setSpacing(UIScaler.pixel(10))
        for card in (card_lap, card_start, card_pit, card_rules, card_pace):
            column_inputs.addWidget(card)
        column_inputs.addStretch(1)
        inputs = QWidget(self)
        inputs.setLayout(column_inputs)
        inputs.setFixedWidth(UIScaler.size(23))

        # Results: key figures, strategy, stop plan, details, tyres
        self.tile_fuel = KpiTile(self, tr("Race Fuel"), tr("Fuel for the whole race, safety margin included"))
        self.tile_energy = KpiTile(self, tr("Race Energy"), tr("Energy for the whole race, safety margin included"))
        self.tile_pits = KpiTile(self, tr("Pit Stops"))
        self.tile_stint = KpiTile(self, tr("Max Stint"), tr("Longest stint, whole laps"))
        self.tile_refill = KpiTile(self, tr("Refill per Stop"))
        self.tile_tyres = KpiTile(self, tr("Tyres"), tr("Tyres used by the tyre plan / maximum allowed"))
        self.tiles = QWidget(self)
        self.layout_tiles = QGridLayout(self.tiles)
        self.layout_tiles.setContentsMargins(0, 0, 0, 0)
        self.layout_tiles.setSpacing(UIScaler.pixel(10))
        self.arrange_top(wide=True)

        card_strategy = Card(self, tr("Strategy"))
        self.label_strategy = muted_label("")
        self.label_strategy.setWordWrap(True)
        card_strategy.grid.addWidget(self.pit_preview, 0, 0)
        card_strategy.grid.addWidget(self.label_strategy, 1, 0)

        self.button_copy = QPushButton(tr("Copy"))
        self.button_copy.setToolTip(tr("Copy pit stop plan as text"))
        self.button_copy.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button_copy.clicked.connect(self.copy_plan)
        card_plan = Card(self, tr("Pit Stop Plan"), (self.button_copy,))
        self.table_plan = QTableWidget(0, 7, self)
        self.table_plan.setHorizontalHeaderLabels((
            tr("Stop"), tr("Lap"), f"{tr('Fuel')} ({self.symbol_fuel})", f"{tr('Energy')} (%)", tr("Tyres"),
            tr("Driver"), f"{tr('Stop Time')} (s)"))
        self.table_plan.verticalHeader().setVisible(False)
        self.table_plan.setShowGrid(False)
        self.table_plan.setAlternatingRowColors(True)
        self.table_plan.setFrameShape(QFrame.Shape.NoFrame)
        self.table_plan.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_plan.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table_plan.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table_plan.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column in (4, 6):  # tyre change & stop time: whole header text shown
            self.table_plan.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table_plan.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        card_plan.grid.addWidget(self.table_plan, 0, 0)

        card_detail = Card(self, tr("Details"))
        grid = card_detail.grid
        self.label_head_fuel = QLabel(f"<b>{tr('Fuel')}</b> ({self.symbol_fuel})")
        self.label_head_energy = QLabel(f"<b>{tr('Energy')}</b> (%)")
        for label in (self.label_head_fuel, self.label_head_energy):
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.label_head_fuel, 0, 1)
        grid.addWidget(self.label_head_energy, 0, 2)
        rows = (
            (tr("Total Needed"), "total_needed", "", tr("Whole race, safety margin included: exact ≈ rounded up")),
            (tr("Pit Stops"), "pit_stops", "", tr("Stops this resource alone needs: estimate ≈ whole stops")),
            (tr("Total Laps"), "total_laps", tr("lap"), tr("Laps the total amount lasts")),
            (tr("Total Minutes"), "total_minutes", "min", tr("Minutes the total amount lasts")),
            (tr("Max Stint Laps"), "stint_laps", tr("lap"), tr("Laps a full tank lasts, safety margin kept")),
            (tr("Max Stint Minutes"), "stint_minutes", "min", tr("Minutes a full tank lasts, safety margin kept")),
            (tr("Left at Stint End"), "end_stint", "", tr("Left in the tank when pitting (less than one lap)")),
            (tr("Consumption for One Less Stop"), "one_less_stint", tr("per lap"),
             tr("Consumption per lap to save one pit stop")),
        )
        for row, (title, name, unit, tooltip) in enumerate(rows, start=1):
            label = QLabel(title)
            label.setToolTip(tooltip)
            grid.addWidget(label, row, 0)
            grid.addWidget(getattr(self.usage_fuel, name), row, 1)
            grid.addWidget(getattr(self.usage_energy, name), row, 2)
            grid.addWidget(muted_label(unit), row, 3)
        row = len(rows) + 1
        label = QLabel(tr("Average Refill"))
        label.setToolTip(tr("Average amount added per stop of the pit stop plan"))
        grid.addWidget(label, row, 0)
        grid.addWidget(self.refill_fuel.average_refill, row, 1)
        grid.addWidget(self.refill_energy.average_refill, row, 2)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # Saving target: one stop less (automatic), or laps per stint to aim for
        card_saving = Card(self, tr("Saving Target"))
        self.input_target = spin_box(999, tr("lap"), tooltip=tr("Laps per stint to aim for, 0 = none"))
        self.input_target.valueChanged.connect(self.update_input)
        self.label_one_less = muted_label("")
        self.label_one_less.setWordWrap(True)
        self.label_target = muted_label("")
        self.label_target.setWordWrap(True)
        card_saving.grid.addWidget(self.label_one_less, 0, 0, 1, 2)
        card_saving.add_row(tr("Laps per Stint"), self.input_target, 1)
        card_saving.grid.addWidget(self.label_target, 2, 0, 1, 2)

        card_tyre = self.card_tyre_life = Card(self, tr("Tyre Life"))
        card_tyre.add_row(tr("Laps"), self.input_tyre.lifespan_laps, 0, 0)
        card_tyre.add_row(tr("Minutes"), self.input_tyre.lifespan_minutes, 0, 1)
        card_tyre.add_row(tr("Stints"), self.input_tyre.lifespan_stints, 1, 0,
                          tooltip=tr("Longest stints a set of tyres lasts"))
        card_tyre.add_row(tr("Wear per Stint"), self.input_tyre.wear_stint, 1, 1,
                          tooltip=tr("Tread used over the longest stint"))

        column_results = QVBoxLayout()
        column_results.setContentsMargins(0, 0, 0, 0)
        column_results.setSpacing(UIScaler.pixel(10))
        column_results.addWidget(card_strategy)
        column_results.addWidget(card_plan)
        column_results.addWidget(card_detail)
        column_results.addWidget(card_saving)
        column_results.addStretch(1)

        layout_panel = QHBoxLayout(self)
        layout_panel.setContentsMargins(0, 0, 0, 0)
        layout_panel.setSpacing(UIScaler.pixel(10))
        layout_panel.addWidget(inputs)
        layout_panel.addLayout(column_results, stretch=1)

        self.load_inputs()
        self._batch = 0
        self.update_input()

    def wide_top_width(self) -> int:
        """Width the race setup needs on one row"""
        grid = self.card_race.grid
        width = sum(
            max(widget.minimumSizeHint().width() for widget in widgets[::2])
            + max(widget.minimumSizeHint().width() for widget in widgets[1::2])
            for widgets in self.race_pairs
        )
        margins = self.card_race.layout_card.contentsMargins()
        return width + grid.horizontalSpacing() * (len(self.race_pairs) * 2 - 1) + margins.left() + margins.right()

    def arrange_top(self, wide: bool):
        """Race setup on one row & tiles in one row, or wrapped on two rows each (narrow page)"""
        grid = self.card_race.grid
        columns = len(self.race_pairs) if wide else 3
        for column in range(len(self.race_pairs) * 2):
            grid.setColumnStretch(column, 0)
        for index, widgets in enumerate(self.race_pairs):
            row, column = divmod(index, columns)
            for label, editor in zip(widgets[::2], widgets[1::2]):  # duration & laps share a place
                grid.removeWidget(label)
                grid.removeWidget(editor)
                grid.addWidget(label, row, column * 2)
                grid.addWidget(editor, row, column * 2 + 1)
            grid.setColumnStretch(column * 2 + 1, 1)
        tiles = (self.tile_fuel, self.tile_energy, self.tile_pits, self.tile_stint, self.tile_refill, self.tile_tyres)
        columns = len(tiles) if wide else 3
        for index, tile in enumerate(tiles):
            self.layout_tiles.removeWidget(tile)
            self.layout_tiles.addWidget(tile, *divmod(index, columns))

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Several inputs changed together: one calculation at the end, not one per input"""
        self._batch += 1
        try:
            yield
        finally:
            self._batch -= 1
            if not self._batch:
                self.update_input()

    # Saved inputs
    def input_values(self) -> dict:
        race = self.input_race
        return {
            "input_lap_time": round(self.input_laptime.to_seconds(), 3),
            "input_fuel_per_lap": self.input_fuel.fuel_used.value(),
            "input_energy_per_lap": self.input_fuel.energy_used.value(),
            "input_tank_capacity": self.input_fuel.capacity.value(),
            "enable_lap_race": race.lap_race,
            "input_race_minutes": race.minutes.value(),
            "input_race_laps": race.laps.value(),
            "input_formation_laps": race.formation.value(),
            "input_pit_seconds": race.pit_seconds.value(),
            "input_safety_margin": race.margin.value(),
            "input_fuel_start": self.refill_fuel.amount_start.value(),
            "input_energy_start": self.refill_energy.amount_start.value(),
            "input_tread_start": self.input_tyre.start_tread.value(),
            "input_wear_per_lap": self.input_tyre.wear_lap.value(),
            "input_minimum_tread": self.input_tyre.minimum_tread.value(),
            "input_refuel_rate": self.input_pit.refuel_rate.value(),
            "input_energy_rate": self.input_pit.energy_rate.value(),
            "enable_tyres_during_refuel": self.input_pit.tyres_during_refuel.isChecked(),
            "input_driver_change_seconds": self.input_pit.driver_change.value(),
            "input_minimum_stops": self.input_rules.minimum_stops.value(),
            "input_max_stint_minutes": self.input_rules.max_stint_minutes.value(),
            "input_drivers": self.input_rules.drivers.value(),
            "input_fuel_effect": self.input_pace.fuel_effect.value(),
            "input_track_evolution": self.input_pace.track_evolution.value(),
            "input_target_stint_laps": self.input_target.value(),
        }

    def set_input_values(self, values: dict):
        race = self.input_race
        with self.batch():
            self.input_laptime.set_seconds(values["input_lap_time"])
            self.input_fuel.fuel_used.setValue(values["input_fuel_per_lap"])
            self.input_fuel.energy_used.setValue(values["input_energy_per_lap"])
            self.input_fuel.capacity.setValue(values["input_tank_capacity"])
            race.minutes.setValue(int(values["input_race_minutes"]))
            race.laps.setValue(int(values["input_race_laps"]))
            race.set_lap_race(bool(values["enable_lap_race"]))
            race.formation.setValue(values["input_formation_laps"])
            race.pit_seconds.setValue(values["input_pit_seconds"])
            race.margin.setValue(values["input_safety_margin"])
            self.refill_fuel.amount_start.setValue(values["input_fuel_start"])
            self.refill_energy.amount_start.setValue(values["input_energy_start"])
            self.input_tyre.start_tread.setValue(values["input_tread_start"])
            self.input_tyre.wear_lap.setValue(values["input_wear_per_lap"])
            self.input_tyre.minimum_tread.setValue(values["input_minimum_tread"])
            self.input_pit.refuel_rate.setValue(values["input_refuel_rate"])
            self.input_pit.energy_rate.setValue(values["input_energy_rate"])
            self.input_pit.tyres_during_refuel.setChecked(bool(values["enable_tyres_during_refuel"]))
            self.input_pit.driver_change.setValue(values["input_driver_change_seconds"])
            self.input_rules.minimum_stops.setValue(int(values["input_minimum_stops"]))
            self.input_rules.max_stint_minutes.setValue(values["input_max_stint_minutes"])
            self.input_rules.drivers.setValue(int(values["input_drivers"]))
            self.input_pace.fuel_effect.setValue(values["input_fuel_effect"])
            self.input_pace.track_evolution.setValue(values["input_track_evolution"])
            self.input_target.setValue(int(values["input_target_stint_laps"]))

    def load_inputs(self):
        """Inputs of last time"""
        self.set_input_values(checked_inputs(cfg.user.config["fuel_calculator"]))

    def save_inputs(self):
        """Inputs kept for next time (saved once changed)"""
        config = cfg.user.config["fuel_calculator"]
        values = self.input_values()
        if all(config.get(key) == value for key, value in values.items()):
            return
        config.update(values)
        cfg.save(config_type=ConfigType.CONFIG)

    def reset_inputs(self):
        """Every input back to default (zero, new tyres)"""
        self.set_input_values(SAVED_INPUTS)
        self.label_fill_source.setText("")

    # Data
    def fill_in_data(self, dataset: Sequence[ConsumptionDataSet], race_length: tuple[str, int] | None = None):
        """Fill in history data: average of latest laps at race pace, race length of a live race"""
        with self.batch():
            if race_length is not None:
                kind, value = race_length
                if kind == "laps":
                    self.input_race.laps.setValue(value)
                else:
                    self.input_race.minutes.setValue(value)
                self.input_race.set_lap_race(kind == "laps")
            if not dataset:
                return
            # Load tank capacity
            capacity = max(api.read.engine.tank_capacity(), dataset[0].capacityFuel)
            if capacity:
                self.input_fuel.capacity.setValue(self.unit_fuel(capacity))
            laps = representative_laps(dataset)
            if not laps:
                self.label_fill_source.setText(tr("No valid lap at race pace to fill in"))
                return
            self.input_laptime.set_seconds(calc.dataset_mean([lap.lapTimeLast for lap in laps]))
            self.input_fuel.fuel_used.setValue(self.unit_fuel(calc.dataset_mean([lap.lastLapUsedFuel for lap in laps])))
            self.input_fuel.energy_used.setValue(calc.dataset_mean([lap.lastLapUsedEnergy for lap in laps]))
            self.input_tyre.wear_lap.setValue(calc.dataset_mean([lap.tyreAvgWearLast for lap in laps]))
            self.label_fill_source.setText(trm(f"Average of {len(laps)} valid lap(s) at race pace"))

    def add_table_data(self, selected_data: list[QTableWidgetItem]) -> tuple[int, int]:
        """Add selected history data (invalid laps left out), (laps used, laps left out)"""
        data_laptime = []
        data_fuel = []
        data_energy = []
        data_tyrewear = []
        data_capacity = []
        used_rows, skipped_rows = set(), set()

        for data in selected_data:
            if not data.data(VALID_ROLE):
                skipped_rows.add(data.row())
                continue
            used_rows.add(data.row())
            header = data.data(Qt.ItemDataRole.UserRole)
            if header == "time":
                data_laptime.append(laptime_string_to_seconds(data.text()))
            elif header == "fuel":
                data_fuel.append(float(data.text()))
            elif header == "energy":
                data_energy.append(float(data.text()))
            elif header == "tyre":
                data_tyrewear.append(float(data.text()))
            elif header == "tank":
                data_capacity.append(float(data.text()))

        # Send data to calculator
        with self.batch():
            if data_laptime:
                self.input_laptime.set_seconds(calc.dataset_mean(data_laptime))
            if data_fuel:
                self.input_fuel.fuel_used.setValue(calc.dataset_mean(data_fuel))
            if data_energy:
                self.input_fuel.energy_used.setValue(calc.dataset_mean(data_energy))
            if data_tyrewear:
                self.input_tyre.wear_lap.setValue(calc.dataset_mean(data_tyrewear))
            if data_capacity:
                self.input_fuel.capacity.setValue(max(data_capacity))
        if used_rows:
            self.label_fill_source.setText(trm(f"Average of {len(used_rows)} selected lap(s)"))
        return len(used_rows), len(skipped_rows)

    # Calculation
    def strategy_input(self) -> StrategyInput:
        race = self.input_race
        return StrategyInput(
            laptime=self.input_laptime.to_seconds(),
            race_minutes=0 if race.lap_race else race.minutes.value(),
            race_laps=race.laps.value() if race.lap_race else 0,
            formation_laps=race.formation.value(),
            pit_seconds=race.pit_seconds.value(),
            tank_capacity=self.input_fuel.capacity.value(),
            fuel_per_lap=self.input_fuel.fuel_used.value(),
            energy_per_lap=self.input_fuel.energy_used.value(),
            fuel_start=self.refill_fuel.amount_start.value(),
            energy_start=self.refill_energy.amount_start.value(),
            margin_laps=race.margin.value(),
            tread_start=self.input_tyre.start_tread.value(),
            wear_per_lap=self.input_tyre.wear_lap.value(),
            minimum_tread=self.input_tyre.minimum_tread.value(),
            refuel_rate=self.input_pit.refuel_rate.value(),
            energy_rate=self.input_pit.energy_rate.value(),
            tyres_during_refuel=self.input_pit.tyres_during_refuel.isChecked(),
            driver_change_seconds=self.input_pit.driver_change.value(),
            minimum_stops=self.input_rules.minimum_stops.value(),
            max_stint_minutes=self.input_rules.max_stint_minutes.value(),
            drivers=self.input_rules.drivers.value(),
            fuel_effect=self.input_pace.fuel_effect.value(),
            track_evolution=self.input_pace.track_evolution.value(),
        )

    def update_input(self):
        """Calculate and output results"""
        if self._batch or self._updating:
            return
        self._updating = True  # lap time carry over sets inputs: no nested calculation
        try:
            self.input_laptime.carry_over()
            self.calculate()
        finally:
            self._updating = False
        self.save_inputs()

    def plan_with_tyres(self, setup: StrategyInput) -> Strategy:
        """Pit stop plan, tyre change time of the linked tyre plan added to each stop

        Tyre plan rows follow stints and stints follow tyre time (time race): settled in a few
        rounds. Tyre plan with tyres: its changes replace the proposed ones (minimum tread).
        """
        link = self.tyre_link
        if link is None:
            strategy = plan(setup)
            self.proposed_tyre_rows = [index for index, stop in enumerate(strategy.stops, 1) if stop.tyres]
            return strategy
        setup = replace(
            setup,
            tyre_change_seconds=link.full_change_seconds(),
            tread_start=link.start_tread(setup.tread_start),
            fresh_tread=link.fresh_tread(),
            wear_per_lap=setup.wear_per_lap * link.wear_factor(),
        )

        def tyre_times() -> tuple[float, ...]:  # proposed changes cost 4 tyres until tyres are planned
            return tuple(link.stop_change_times()) if link.has_tyres() else ()

        extra = tyre_times()
        strategy = plan(replace(setup, stop_extra_seconds=extra))
        for _ in range(3):
            link.set_stints(strategy)
            new_extra = tyre_times()
            if new_extra == extra:
                break
            extra = new_extra
            strategy = plan(replace(setup, stop_extra_seconds=extra))
        else:
            link.set_stints(strategy)
        self.proposed_tyre_rows = [index for index, stop in enumerate(strategy.stops, 1) if stop.tyres]
        changes = link.stop_tyre_changes()
        if changes:
            strategy.tyre_changes = changes[:len(strategy.stops)]
            strategy.stops = [
                replace(stop, tyres=index < len(changes) and changes[index] > 0)
                for index, stop in enumerate(strategy.stops)
            ]
        return strategy

    def set_tyre_status(self, used: int, maximum: int, stock: int, changes: int, change_time: float):
        """Tyre tile from tyre plan: tyres used / allowed, changes & time spent"""
        self.tile_tyres.set_text(
            f"{used} / {maximum}", trm(f"{changes} change(s) · {change_time:+.1f} s"), warning=stock > maximum)

    def calculate(self):
        setup = self.strategy_input()
        strategy = self.strategy = self.plan_with_tyres(setup)
        has_energy = setup.energy_per_lap > 0

        # Calc fuel ratio
        fuel_used = setup.fuel_per_lap * 3.785411784 if self.is_gallon else setup.fuel_per_lap
        fuel_ratio = calc.fuel_to_energy_ratio(fuel_used, setup.energy_per_lap)
        self.input_fuel.fuel_ratio.setText(f"{fuel_ratio:.3f}" if has_energy else "-")

        # Details of fuel & energy, same race length (pit stops shared)
        ready = strategy.ready
        stops = len(strategy.stops)
        fuel_stint = self._calc_consumption(
            "fuel", setup.tank_capacity, setup.fuel_per_lap, setup.fuel_start or setup.tank_capacity,
            strategy.race_laps, setup.margin_laps, setup.laptime)
        self._calc_consumption(
            "energy", 100, setup.energy_per_lap, setup.energy_start or 100,
            strategy.race_laps, setup.margin_laps, setup.laptime)
        self.refill_fuel.average_refill.setText(f"{strategy.average_fuel:.2f}" if stops else "-")
        self.refill_energy.average_refill.setText(f"{strategy.average_energy:.2f}" if stops else "-")
        has_fuel = setup.fuel_per_lap > 0 and setup.tank_capacity > 0
        if not ready or not has_fuel:  # energy only car: no fuel figure
            self.usage_fuel.clear()
            self.refill_fuel.average_refill.setText("-")
        self.usage_fuel.set_enabled(has_fuel or not has_energy)
        self.label_head_fuel.setEnabled(has_fuel or not has_energy)
        if not ready or not has_energy:
            self.usage_energy.clear()
            self.refill_energy.average_refill.setText("-")
        self.usage_energy.set_enabled(has_energy)
        self.label_head_energy.setEnabled(has_energy)
        self.refill_energy.average_refill.setEnabled(has_energy)

        # Calc tyre
        self._calc_tyre_consumption(strategy.max_stint if ready else floor(fuel_stint), setup.laptime)

        self.pit_preview.set_strategy(strategy)
        self.update_plan(strategy, has_energy)
        self.update_summary(strategy, has_energy, setup)
        self.update_saving(strategy, has_energy, setup)

    def update_saving(self, strategy: Strategy, has_energy: bool, setup: StrategyInput):
        """Saving target: consumption for one stop less, and for laps per stint aimed at"""
        symbol = self.symbol_fuel

        def consumption_text(fuel: float, energy: float) -> str:
            parts = []
            if setup.fuel_per_lap > 0:
                parts.append(trm(f"{fuel:.3f} {symbol} per lap ({fuel - setup.fuel_per_lap:+.3f})"))
            if has_energy:
                parts.append(trm(f"{energy:.3f} % per lap ({energy - setup.energy_per_lap:+.3f})"))
            return " · ".join(parts)

        target = saving_target(self.strategy_input(), strategy) if strategy.ready else None
        if target is None:
            self.label_one_less.setText(tr("No stop to save") if strategy.ready else "")
        else:
            laps, fuel, energy, saving = target
            self.label_one_less.setText(
                trm(f"One stop less: {laps} laps per stint, {len(saving.stops)} stop(s)") + "<br>"
                + consumption_text(fuel, energy))
        laps_target = self.input_target.value()
        if laps_target <= 0 or not strategy.ready:
            self.label_target.setText("")
            return
        fuel, energy = target_consumption(setup, laps_target)
        aimed = plan(replace(
            self.strategy_input(),
            fuel_per_lap=min(setup.fuel_per_lap, fuel) if setup.fuel_per_lap > 0 else 0.0,
            energy_per_lap=min(setup.energy_per_lap, energy) if has_energy else 0.0,
        ))
        self.label_target.setText(
            consumption_text(fuel, energy) + "<br>" + trm(f"{len(aimed.stops)} stop(s) with this target"))

    def update_summary(self, strategy: Strategy, has_energy: bool, setup: StrategyInput):
        """Key figure tiles & strategy line"""
        symbol = self.symbol_fuel
        self.tile_energy.setHidden(not has_energy)
        self.button_copy.setEnabled(strategy.ready)
        if not strategy.ready:
            for tile in (self.tile_fuel, self.tile_energy, self.tile_pits, self.tile_stint, self.tile_refill):
                tile.set_text("-")
            impossible = strategy.impossible
            self.tile_pits.set_text("-", warning=impossible)
            self.label_strategy.setText(tr("Tank too small for one lap plus the safety margin") if impossible else "")
            set_warning(self.label_strategy, impossible)
            return
        has_fuel = setup.fuel_per_lap > 0 and setup.tank_capacity > 0
        self.tile_fuel.setHidden(not has_fuel and has_energy)  # energy only car
        fuel_full = ceil(strategy.fuel_needed * 10) / 10 if self.is_gallon else ceil(strategy.fuel_needed)
        self.tile_fuel.set_text(f"{fuel_full:g} {symbol}", f"{strategy.fuel_needed:.2f} {symbol}")
        self.tile_energy.set_text(f"{ceil(strategy.energy_needed):g} %", f"{strategy.energy_needed:.2f} %")
        stops = len(strategy.stops)
        limit = {
            "energy": tr("limited by energy"), "stint": tr("limited by stint length"),
            "fuel": tr("limited by fuel") if has_energy else "",
        }[strategy.limit]
        tyre_stops = len(strategy.tyre_stops)
        detail = " · ".join(text for text in (limit, trm(f"{tyre_stops} with tyres") if tyre_stops else "") if text)
        self.tile_pits.set_text(f"{stops}", detail, warning=not strategy.feasible)
        self.tile_stint.set_text(laps_text(strategy.max_stint), f"≈ {max(strategy.stint_seconds, default=0) / 60:.0f} min")
        if not has_fuel:  # energy only car
            self.tile_refill.set_text(
                f"{strategy.average_energy if stops else strategy.energy_load:.1f} %",
                "" if stops else tr("No stop needed"), title=tr("Refill per Stop") if stops else tr("Fuel to Load"))
        elif stops:
            self.tile_refill.set_text(
                f"{strategy.average_fuel:.1f} {symbol}",
                f"{strategy.average_energy:.1f} %" if has_energy else "", title=tr("Refill per Stop"))
        else:  # no stop: what to load at start
            self.tile_refill.set_text(
                f"{strategy.fuel_load:.1f} {symbol}",
                f"{strategy.energy_load:.1f} %" if has_energy else tr("No stop needed"), title=tr("Fuel to Load"))

        if not strategy.feasible:
            self.label_strategy.setText(tr("Tank too small for one lap plus the safety margin"))
            set_warning(self.label_strategy, True)
            return
        set_warning(self.label_strategy, False)
        text = trm(f"{len(strategy.stints)} stint(s), {strategy.race_laps} race laps")
        pit_laps = ", ".join(str(stop.lap) for stop in strategy.stops)
        if pit_laps:
            text += " · " + (tr("Stop at lap") if stops == 1 else tr("Stops at laps")) + " " + pit_laps
        if tyre_stops:
            text += " · " + tr("Tyres at lap") + " " + ", ".join(str(lap) for lap in strategy.tyre_stops)
        if stops:
            text += " · " + trm(f"{strategy.pit_seconds:.0f} s in the pits")
        self.label_strategy.setText(text)

    def plan_rows(self, strategy: Strategy, has_energy: bool) -> list[tuple[str, ...]]:
        """Pit stop plan rows: start load, then every stop (stop, lap, fuel, energy, tyres, driver, time)"""
        if not strategy.ready:
            return []
        rows: list[tuple[str, ...]] = [(tr("Start"), "0", f"{strategy.fuel_load:.1f}",
                 f"{strategy.energy_load:.1f}" if has_energy else "-", "", "1", "")]
        counts = strategy.tyre_changes
        for index, stop in enumerate(strategy.stops, start=1):
            tyres = (f"{tr('Change')} ({counts[index - 1]})" if counts else tr("Change")) if stop.tyres else ""
            rows.append((str(index), str(stop.lap), f"{stop.fuel:.1f}",
                         f"{stop.energy:.1f}" if has_energy else "-", tyres, str(stop.driver), f"{stop.seconds:.1f}"))
        return rows

    def update_plan(self, strategy: Strategy, has_energy: bool):
        """Pit stop plan table, cells updated in place (no new item per calculation)"""
        table = self.table_plan
        rows = self.plan_rows(strategy, has_energy)
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
                if column == 4:
                    item.setForeground(QColor(TYRE_COLOR) if text else table.palette().text().color())
        table.setColumnHidden(3, not has_energy)
        table.setColumnHidden(5, self.input_rules.drivers.value() < 2)
        table.setUpdatesEnabled(True)
        # Fit rows without inner scroll, up to 12 rows
        visible = min(max(len(rows), 1), 12)
        row_h = table.verticalHeader().defaultSectionSize()
        table.setFixedHeight(table.horizontalHeader().sizeHint().height() + row_h * visible + 4)

    def plan_text(self) -> str:
        """Pit stop plan as plain text (clipboard)"""
        strategy = self.strategy
        symbol = self.symbol_fuel
        has_energy = self.input_fuel.energy_used.value() > 0
        lines = [
            f"{tr('Pit Stop Plan')} · {trm(f'{len(strategy.stints)} stint(s), {strategy.race_laps} race laps')}",
            f"{tr('Start')}: {strategy.fuel_load:.1f} {symbol}"
            + (f" · {strategy.energy_load:.1f} %" if has_energy else ""),
        ]
        counts = strategy.tyre_changes
        drivers = self.input_rules.drivers.value() > 1
        for index, stop in enumerate(strategy.stops, start=1):
            line = f"{tr('Stop')} {index} · {tr('Lap')} {stop.lap} · +{stop.fuel:.1f} {symbol}"
            if has_energy:
                line += f" · +{stop.energy:.1f} %"
            if stop.tyres:
                line += f" · {tr('Tyres')}" + (f" ({counts[index - 1]})" if counts else "")
            if drivers:
                line += f" · {tr('Driver')} {stop.driver}"
            line += f" · {stop.seconds:.1f} s"
            lines.append(line)
        tyre_seconds = sum(stop.tyre_seconds for stop in strategy.stops)
        lines.append(trm(f"{strategy.pit_seconds:.0f} s in the pits") + (
            f" · {tr('Tyres')} {tyre_seconds:.1f} s" if tyre_seconds else ""))
        return "\n".join(lines)

    def copy_plan(self):
        QGuiApplication.clipboard().setText(self.plan_text())

    def _calc_consumption(self, output_type, tank_capacity, consumption, fuel_start,
                          total_race_laps, margin_laps, laptime) -> float:
        """Fuel or energy details for race length of pit stop plan, max stint laps returned"""
        # Total needed incl. margin, rounded up (keep 1 decimal place for Gallon)
        total_need_frac = calc.total_fuel_needed(total_race_laps + margin_laps, consumption, 0)
        if self.is_gallon and output_type == "fuel":
            total_need_full = ceil(total_need_frac * 10) / 10
        else:
            total_need_full = ceil(total_need_frac)
        reserve = margin_laps * consumption
        usable = max(tank_capacity - reserve, 0)

        amount_curr = min(total_need_full, tank_capacity)
        end_stint_fuel = calc.end_stint_fuel(max(amount_curr - reserve, 0), 0, consumption)
        estimate_pit_counts = max(calc.end_stint_pit_counts(
            total_need_full - fuel_start, usable - end_stint_fuel), 0)
        pits = ceil(estimate_pit_counts)

        total_runlaps = calc.end_stint_laps(total_need_full, consumption)
        total_runmins = calc.end_stint_minutes(total_runlaps, laptime)
        if total_need_full > tank_capacity:
            stint_runlaps = calc.end_stint_laps(usable, consumption)
            stint_runmins = calc.end_stint_minutes(stint_runlaps, laptime)
        else:
            stint_runlaps = total_runlaps
            stint_runmins = total_runmins

        output_usage = self.usage_fuel if output_type == "fuel" else self.usage_energy
        output_usage.total_needed.setText(f"{total_need_frac:.2f} ≈ {total_need_full:g}")
        output_usage.end_stint.setText(f"{end_stint_fuel:.2f}")
        output_usage.pit_stops.setText(f"{estimate_pit_counts:.2f} ≈ {pits}")
        if pits:  # one less stop only means something with a stop
            used_one_less = calc.one_less_pit_stop_consumption(
                estimate_pit_counts, usable, max(amount_curr - reserve, 0), total_race_laps)
            output_usage.one_less_stint.setText(f"{max(used_one_less, 0):.3f}")
        else:
            output_usage.one_less_stint.setText("-")
        output_usage.total_laps.setText(f"{total_runlaps:.2f}")
        output_usage.total_minutes.setText(f"{total_runmins:.2f}")
        output_usage.stint_laps.setText(f"{stint_runlaps:.2f}")
        output_usage.stint_minutes.setText(f"{stint_runmins:.2f}")
        return stint_runlaps

    def _calc_tyre_consumption(self, stint_laps: int, laptime: float):
        """Tyre life, wear over the longest stint (whole laps actually driven)"""
        tyre_start_tread = self.input_tyre.start_tread.value()
        tyre_wear_lap = self.input_tyre.wear_lap.value()
        labels = (self.input_tyre.lifespan_laps, self.input_tyre.lifespan_minutes,
                  self.input_tyre.lifespan_stints, self.input_tyre.wear_stint)
        if tyre_wear_lap <= 0:  # no wear entered: no lifespan to show
            for label in labels:
                label.setText("-")
                set_warning(label, False)
            return
        tyre_wear_stint = tyre_wear_lap * stint_laps
        usable_tread = max(tyre_start_tread - self.input_tyre.minimum_tread.value(), 0)
        tyre_lifespan_laps = calc.wear_lifespan_in_laps(usable_tread, tyre_wear_lap)
        tyre_lifespan_mins = calc.wear_lifespan_in_mins(usable_tread, tyre_wear_lap, laptime)
        tyre_lifespan_stints = tyre_lifespan_laps / stint_laps if stint_laps else 0

        self.input_tyre.lifespan_laps.setText(f"{tyre_lifespan_laps:.2f}")
        self.input_tyre.lifespan_minutes.setText(f"{tyre_lifespan_mins:.2f}")
        self.input_tyre.lifespan_stints.setText(f"{tyre_lifespan_stints:.2f}" if stint_laps else "-")
        self.input_tyre.wear_stint.setText(f"{tyre_wear_stint:.2f} %")
        set_warning(self.input_tyre.lifespan_stints, 0 < tyre_lifespan_stints < 1)
        set_warning(self.input_tyre.wear_stint, tyre_wear_stint >= usable_tread)

    def validate_starting_fuel(self):
        """Starting fuel never above tank capacity (checked on both changes)"""
        capacity = self.input_fuel.capacity.value()
        if capacity > 0 and self.refill_fuel.amount_start.value() > capacity:
            self.refill_fuel.amount_start.setValue(capacity)


class InputLapTime(QWidget):
    """Lap time input: minutes : seconds . milliseconds"""

    def __init__(self, parent: CalculatorPanel) -> None:
        super().__init__(parent)
        self.minutes = spin_box(9999)
        self.seconds = spin_box(60, minimum=-1)
        self.mseconds = spin_box(1000, minimum=-1)
        self.mseconds.setSingleStep(100)
        for box, digits in ((self.minutes, 2), (self.seconds, 2), (self.mseconds, 3)):
            box.valueChanged.connect(parent.update_input)
            box.setMinimumWidth(box.fontMetrics().horizontalAdvance("0" * digits) + UIScaler.size(1.2))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(UIScaler.pixel(3))
        layout.addWidget(self.minutes, stretch=2)
        layout.addWidget(muted_label(":"))
        layout.addWidget(self.seconds, stretch=2)
        layout.addWidget(muted_label("."))
        layout.addWidget(self.mseconds, stretch=3)

    def set_seconds(self, seconds: float):
        """Set lap time from seconds"""
        milliseconds = round(max(seconds, 0) * 1000)
        self.minutes.setValue(milliseconds // 60000)
        self.seconds.setValue(milliseconds // 1000 % 60)
        self.mseconds.setValue(milliseconds % 1000)

    def to_seconds(self):
        """Output lap time value to seconds"""
        return (
            self.minutes.value() * 60
            + self.seconds.value()
            + self.mseconds.value() * 0.001
        )

    def carry_over(self):
        """Carry over lap time value"""
        if self.seconds.value() > 59:
            self.seconds.setValue(0)
            self.minutes.setValue(self.minutes.value() + 1)
        elif self.seconds.value() < 0:
            if self.minutes.value() > 0:
                self.seconds.setValue(59)
                self.minutes.setValue(self.minutes.value() - 1)
            else:
                self.seconds.setValue(0)

        if self.mseconds.value() > 999:
            self.mseconds.setValue(0)
            self.seconds.setValue(self.seconds.value() + 1)
        elif self.mseconds.value() < 0:
            if self.seconds.value() > 0 or self.minutes.value() > 0:
                self.mseconds.setValue(900)
                self.seconds.setValue(self.seconds.value() - 1)
            else:
                self.mseconds.setValue(0)


class InputFuel:
    """Fuel inputs: tank capacity, consumption per lap, fuel to energy ratio (result)"""

    def __init__(self, parent: CalculatorPanel) -> None:
        self.capacity = double_box(9999, 2, 1.0, parent.symbol_fuel)
        self.capacity.valueChanged.connect(parent.validate_starting_fuel)
        self.capacity.valueChanged.connect(parent.update_input)
        self.fuel_used = double_box(9999, 3, 0.1, parent.symbol_fuel)
        self.fuel_used.valueChanged.connect(parent.update_input)
        self.energy_used = double_box(100, 3, 0.1, "%")
        self.energy_used.valueChanged.connect(parent.update_input)
        self.fuel_ratio = value_label()


class InputRace:
    """Race inputs: time or lap race (switch), formation laps, pit stop time, safety margin"""

    def __init__(self, parent: CalculatorPanel) -> None:
        self.parent = parent
        self.minutes = spin_box(9999, "min")
        self.minutes.valueChanged.connect(parent.update_input)
        self.laps = spin_box(9999, tr("lap"))
        self.laps.valueChanged.connect(parent.update_input)
        self.formation = double_box(9999, 2, 0.1, tr("lap"))
        self.formation.valueChanged.connect(parent.update_input)
        self.pit_seconds = double_box(9999, 1, 1.0, "s")
        self.pit_seconds.valueChanged.connect(parent.update_input)
        self.margin = double_box(99, 2, 0.1, tr("lap"))
        self.margin.valueChanged.connect(parent.update_input)

        self.button_time = QPushButton(tr("Time"))
        self.button_laps = QPushButton(tr("Laps"))
        self.mode_group = QButtonGroup(parent)
        self.mode_switch = QWidget()
        layout = QHBoxLayout(self.mode_switch)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for button in (self.button_time, self.button_laps):
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setObjectName("fuelSegment")
            self.mode_group.addButton(button)
            layout.addWidget(button, stretch=1)
        self.button_time.setChecked(True)
        self.mode_group.buttonToggled.connect(self.mode_toggled)

    @property
    def lap_race(self) -> bool:
        return self.button_laps.isChecked()

    def set_lap_race(self, lap_race: bool):
        (self.button_laps if lap_race else self.button_time).setChecked(True)
        self.show_mode()

    def mode_toggled(self, button, checked: bool):
        if checked:
            self.show_mode()
            self.parent.update_input()

    def show_mode(self):
        """Only the field of the race type is shown (the other keeps its value)"""
        lap_race = self.lap_race
        for widget in (self.minutes, getattr(self.parent, "label_minutes", None)):
            if widget is not None:
                widget.setHidden(lap_race)
        for widget in (self.laps, getattr(self.parent, "label_laps", None)):
            if widget is not None:
                widget.setHidden(not lap_race)


class OutputUsage:
    """Fuel or energy results, one column of the details card"""

    def __init__(self, parent: CalculatorPanel) -> None:
        self.total_needed = value_label()
        self.pit_stops = value_label()
        self.total_laps = value_label()
        self.total_minutes = value_label()
        self.stint_laps = value_label()
        self.stint_minutes = value_label()
        self.end_stint = value_label()
        self.one_less_stint = value_label()

    def labels(self) -> tuple[QLabel, ...]:
        return (self.total_needed, self.pit_stops, self.total_laps, self.total_minutes,
                self.stint_laps, self.stint_minutes, self.end_stint, self.one_less_stint)

    def set_enabled(self, enabled: bool):
        """Muted when not used (car without energy)"""
        for label in self.labels():
            label.setEnabled(enabled)

    def clear(self):
        """Dashes while there is nothing to calculate"""
        for label in self.labels():
            label.setText("-")
            set_warning(label, False)


class InputRefill:
    """Starting amount (input) & average refill per stop (result) of fuel or energy"""

    def __init__(self, parent: CalculatorPanel, type_name: str) -> None:
        if type_name == "Fuel":
            self.amount_start = double_box(9999, 2, 1.0, parent.symbol_fuel)
            self.amount_start.valueChanged.connect(parent.validate_starting_fuel)
        else:
            self.amount_start = double_box(100, 2, 1.0, "%")
        self.amount_start.valueChanged.connect(parent.update_input)
        self.average_refill = value_label()


class InputTyreWear:
    """Tyre inputs (starting tread, wear per lap, minimum tread) & tyre life results"""

    def __init__(self, parent: CalculatorPanel) -> None:
        self.start_tread = double_box(100, 3, 0.01, "%")
        self.start_tread.setValue(100.0)
        self.start_tread.valueChanged.connect(parent.update_input)
        self.wear_lap = double_box(100, 3, 0.01, "%")
        self.wear_lap.valueChanged.connect(parent.update_input)
        self.minimum_tread = double_box(100, 1, 1.0, "%")
        self.minimum_tread.valueChanged.connect(parent.update_input)
        self.wear_stint = value_label()
        self.lifespan_laps = value_label()
        self.lifespan_minutes = value_label()
        self.lifespan_stints = value_label()


class InputPit:
    """Pit stop service: refuel & energy rate, tyres during refuelling, driver change"""

    def __init__(self, parent: CalculatorPanel) -> None:
        self.refuel_rate = double_box(999, 2, 0.1, f"{parent.symbol_fuel}/s")
        self.energy_rate = double_box(100, 2, 0.1, "%/s")
        self.driver_change = double_box(999, 1, 1.0, "s")
        self.tyres_during_refuel = QCheckBox(tr("Tyres Changed While Refuelling"))
        self.tyres_during_refuel.setToolTip(tr("Longest of refuelling and tyre change counts, not both"))
        for box in (self.refuel_rate, self.energy_rate, self.driver_change):
            box.valueChanged.connect(parent.update_input)
        self.tyres_during_refuel.toggled.connect(parent.update_input)


class InputRules:
    """Race rules: mandatory stops, stint time limit, drivers"""

    def __init__(self, parent: CalculatorPanel) -> None:
        self.minimum_stops = spin_box(99)
        self.max_stint_minutes = double_box(9999, 0, 1.0, "min")
        self.drivers = spin_box(9, minimum=1)
        for box in (self.minimum_stops, self.max_stint_minutes, self.drivers):
            box.valueChanged.connect(parent.update_input)


class InputPace:
    """Lap time model: fuel effect & track evolution"""

    def __init__(self, parent: CalculatorPanel) -> None:
        self.fuel_effect = double_box(9, 3, 0.01, f"s/10 {parent.symbol_fuel}")
        self.track_evolution = double_box(9, 2, 0.05, "s/h")
        self.track_evolution.setMinimum(-9)
        for box in (self.fuel_effect, self.track_evolution):
            box.valueChanged.connect(parent.update_input)


def checked_inputs(values: dict) -> dict:
    """Saved inputs with type checked (file or config), default for missing or wrong values"""
    inputs = {}
    for key, default in SAVED_INPUTS.items():
        value = values.get(key, default)
        if isinstance(default, bool):
            value = value if isinstance(value, bool) else default
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            value = default
        inputs[key] = value
    return inputs
