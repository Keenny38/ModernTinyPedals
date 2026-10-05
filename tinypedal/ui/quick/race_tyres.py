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
Race calculator, tyre side: tyre plan (tyre set on each wheel per stint), tyre stock & rules

Plain Python model of the tyre tab (no Qt). Once the fuel strategy is ready, plan rows follow its
stints, and the tyre change time of each stop is added to that stop (see TyrePlan.set_stints and
the TyreLink methods used by race_backend.RaceBackend.plan_with_tyres).
"""

from __future__ import annotations

import os
from collections import Counter
from math import isfinite
from typing import TYPE_CHECKING

from PySide6.QtCore import QStandardPaths

from ...const_file import ConfigType
from ...i18n import tr, trm
from ...setting import cfg
from ...userfile.json_setting import copy_setting
from ...userfile.tyre_strategy import (
    DEFAULT_TYRE_RULE,
    DEFAULT_TYRE_SET,
    DEFAULT_TYRE_SETTING,
    HEADER_TYREPLAN,
    TYRE_STRATEGY_FILE_VERSION,
    create_tyre_strategy,
    decode_tyre_name,
    encode_tyre_name,
    extract_tyre_key,
)

if TYPE_CHECKING:
    from ...fuel_strategy import Strategy

CORNER_STARTING_TREAD = (
    "front_left_starting_tread",
    "front_right_starting_tread",
    "rear_left_starting_tread",
    "rear_right_starting_tread",
)
CORNER_WEAR_PER_STINT = (
    "front_left_wear_per_stint",
    "front_right_wear_per_stint",
    "rear_left_wear_per_stint",
    "rear_right_wear_per_stint",
)
WHEELS = 4
AUTOSAVE_NAME = "race_calculator_tyres"  # tyre plan kept between sessions (config folder)
MEASURED_DEFAULT = tuple(DEFAULT_TYRE_SET).index("Medium")
NUMBER_LIMIT = 1e6  # beyond every rule & compound value: huge numbers of a file clamped to it
RULE_RANGES = {  # rule: maximum, decimals
    "maximum_tyre": (999, 0),
    "tyre_change_time_1": (99, 1),
    "tyre_change_time_2": (99, 1),
    "tyre_change_time_3": (99, 1),
    "tyre_change_time_4": (99, 1),
}
TREAD_COLORS = (  # tread left above fraction: color
    (0.9, "#00AA33"), (0.8, "#33AA00"), (0.7, "#66AA00"), (0.6, "#88AA00"), (0.5, "#AAAA00"),
    (0.4, "#AA8800"), (0.3, "#AA6600"), (0.2, "#BB3300"), (float("-inf"), "#CC0000"),
)


def average_setting(setting: dict, keys: tuple[str, ...]) -> float:
    """Average of 4 wheels of a compound setting"""
    return sum(max(setting[key], 0.0) for key in keys) / len(keys)


def checked_setting(setting: dict, default: dict):
    """Tyre rule or compound setting of a file made usable in place (hand edited file): wrong
    type, nan & infinity back to default, huge numbers clamped"""
    for key, default_value in default.items():
        value = setting.get(key, default_value)
        if isinstance(default_value, bool):
            setting[key] = value if isinstance(value, bool) else default_value
        elif (not isinstance(value, (int, float)) or isinstance(value, bool)
              or (isinstance(value, float) and not isfinite(value))):
            setting[key] = default_value
        else:
            setting[key] = min(max(value, -NUMBER_LIMIT), NUMBER_LIMIT)


def checked_tyre_data(user_data: dict) -> dict:
    """Tyre strategy data (validated file) with numbers the planner can show & calculate with"""
    checked_setting(user_data["tyre_rule"], DEFAULT_TYRE_RULE)
    for key, setting in user_data["tyre_set"].items():
        checked_setting(setting, DEFAULT_TYRE_SET.get(key, DEFAULT_TYRE_SETTING))
    return user_data


def set_tyre_strategy_file_path(filename: str = "") -> str:
    """Folder of last tyre plan or race plan file (documents at first), file name added"""
    filepath = cfg.user.config["tyre_strategy_planner"]["last_file_path"]
    if not filepath or not os.path.exists(filepath):
        filepath = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if not filepath.endswith("/"):
            filepath += "/"
    return f"{filepath}{filename}"


def save_tyre_strategy_file_path(filepath: str):
    """Folder of last tyre plan or race plan file kept"""
    if filepath != cfg.user.config["tyre_strategy_planner"]["last_file_path"]:
        cfg.user.config["tyre_strategy_planner"]["last_file_path"] = filepath
        cfg.save(config_type=ConfigType.CONFIG)


def tread_color(fraction: float) -> str:
    """Color of tread left (fraction of new tyre)"""
    if not isfinite(fraction):
        fraction = 0.0
    return next((color for limit, color in TREAD_COLORS if fraction > limit), TREAD_COLORS[-1][1])


def tread_text(remaining: float, end: float) -> str:
    """Tread at start & end of stint: "New-70%", "95-65%", "Blowout" (below zero)"""
    if not (isfinite(remaining) and isfinite(end)):
        return "-"
    if end < 0:
        return tr("Blowout")
    if remaining < 1:
        return f"{remaining * 100:.0f}-{end:.0%}"
    return trm(f"New-{end:.0%}")


class TyrePlan:
    """Tyre plan of the race calculator: rows of 4 tyre names (one row per stint once linked to the
    fuel strategy), tyre stock, tyre rules & compounds (user_data, tyre strategy file format)"""

    def __init__(self):
        self.user_data: dict = create_tyre_strategy()
        self.name = tr("Untitled plan")
        self.rows: list[list[str]] = [[""] * WHEELS]
        self.stock: list[str] = []
        self.measured = tuple(DEFAULT_TYRE_SET)[MEASURED_DEFAULT]  # compound of measured wear per lap
        self.compound = self.measured  # compound selected in stock: added & proposed tyres
        self.highlight_new = True
        self.linked = False  # rows follow stints of the fuel strategy
        self.stint_laps: list[int] = []  # laps of each stint (row) once linked
        self.labels: list[str] = []  # row titles
        self.spare_rows: list[list[str]] = []  # rows taken out by a shorter strategy, back when it grows
        self.proposed_names: set[str] = set()  # tyres added to stock by last proposal
        self.proposal_short: list[int] = []  # stints of last proposal short of tyres
        self.wear_per_lap = 0.0  # tread % per lap of the strategy (set by backend)
        self.minimum_tread = 0.0  # tread % never gone below (set by backend)
        self.row_changes: list[int] = []  # tyres changed on each row (row 0: start)
        self.change_times: list[float] = []  # tyre change seconds of each row (row 0: 0)
        self.cells: list[list[dict]] = []  # tread of each wheel of each row (see refresh)
        self.uses: Counter[str] = Counter()  # stints run by each tyre
        self._stints_key: tuple | None = None
        self.load(self.user_data, self.name)

    # Data
    @property
    def rule(self) -> dict:
        return self.user_data["tyre_rule"]

    @property
    def compounds(self) -> list[str]:
        return list(self.user_data["tyre_set"])

    def setting(self, tyre_key: str) -> dict:
        return self.user_data["tyre_set"].get(tyre_key, DEFAULT_TYRE_SETTING)

    def load(self, user_data: dict, name: str):
        """Tyre strategy data (validated file) of a new plan: rows kept aside dropped"""
        self.user_data = checked_tyre_data(user_data)
        for key, (maximum, decimals) in RULE_RANGES.items():  # rules in the range of their fields
            number = min(max(float(self.rule[key]), 0.0), maximum)
            self.rule[key] = round(number) if decimals == 0 else round(number, decimals)
        self.name = name
        self.stock = [str(tyre) for tyre in user_data.get("tyre_stock", [])]
        rows = [[str(tyre) for tyre in row[:WHEELS]] for row in user_data.get("tyre_plan", [])]
        self.rows = rows or [[""] * WHEELS]
        self.spare_rows = []
        self.proposed_names = set()
        self.proposal_short = []
        self.linked = False
        self.stint_laps = []
        self.labels = []
        # Compound of measured wear selected: proposals wear as measured until another is picked
        compounds = self.compounds
        self.compound = self.measured if self.measured in compounds else compounds[min(2, len(compounds) - 1)]
        self._stints_key = None
        self.refresh()

    def new_plan(self):
        self.load(create_tyre_strategy(), tr("Untitled plan"))

    def capture_data(self) -> dict:
        """Tyre strategy data of current plan (file format), rows kept aside included"""
        data = self.user_data
        data["file_version"] = TYRE_STRATEGY_FILE_VERSION
        data["tyre_stock"] = list(self.stock)
        data["tyre_plan"] = [list(row) for row in self.rows] + [list(row) for row in self.spare_rows]
        return data

    def file_data(self) -> dict:
        """Tyre strategy data of a saved file: rows of the plan only"""
        data = self.capture_data()
        data["tyre_plan"] = [list(row) for row in self.rows]
        return data

    # Undo & redo
    def capture_state(self) -> dict:
        return {
            "rule": dict(self.rule), "stock": list(self.stock), "plan": [list(row) for row in self.rows],
            "spare": [list(row) for row in self.spare_rows], "set": copy_setting(self.user_data["tyre_set"]),
            "compound": self.compound,
        }

    def restore_state(self, state: dict):
        self._stints_key = None
        self.rule.update(state["rule"])
        self.user_data["tyre_set"] = copy_setting(state["set"])
        self.stock = list(state["stock"])
        self.rows = [list(row) for row in state["plan"]] or [[""] * WHEELS]
        self.spare_rows = [list(row) for row in state["spare"]]
        self.compound = state["compound"]
        self.refresh()

    # Wear, change time & stock uses
    def row_wear(self, row_index: int, setting: dict, corner: int) -> float:
        """Tread used over a stint by a wheel (fraction)

        Linked to the strategy with a wear per lap (measured or entered): wear per lap x laps of
        that stint, scaled by compound (its wear per stint relative to the measured compound).
        Otherwise wear per stint of compound.
        """
        wear_per_stint = max(setting[CORNER_WEAR_PER_STINT[corner]], 0.0) * 0.01
        if self.linked and self.wear_per_lap > 0 and row_index < len(self.stint_laps):
            reference = average_setting(self.setting(self.measured), CORNER_WEAR_PER_STINT)
            factor = wear_per_stint * 100 / reference if reference > 0 else 1.0
            return self.wear_per_lap * self.stint_laps[row_index] * 0.01 * factor
        return wear_per_stint

    def refresh(self):
        """Tread of each wheel (start & end of stint), tyres changed & change time of each row,
        stints run by each tyre of stock"""
        times = self.change_time_table()
        uses: Counter[str] = Counter()
        worn: dict[str, float] = {}  # tread used so far by each tyre (fraction)
        self.row_changes = []
        self.change_times = []
        self.cells = []
        for row_index, row in enumerate(self.rows):
            changed = 0
            cells: list[dict] = []
            for corner, tyre_name in enumerate(row):
                if not tyre_name:
                    cells.append({})
                    continue
                if row_index and self.rows[row_index - 1][corner] != tyre_name:
                    changed += 1
                uses[tyre_name] += 1
                setting = self.setting(extract_tyre_key(tyre_name))
                starting = min(setting[CORNER_STARTING_TREAD[corner]], 100.0) * 0.01
                wear = self.row_wear(row_index, setting, corner)
                used = worn.get(tyre_name, 0.0)
                remaining = starting - used
                worn[tyre_name] = used + wear
                cells.append({"remaining": remaining, "end": remaining - wear, "used": uses[tyre_name] > 1})
            self.cells.append(cells)
            self.row_changes.append(changed)
            self.change_times.append(max(times[changed], 0.0) if row_index else 0.0)
        self.uses = uses

    def change_time_table(self) -> tuple[float, float, float, float, float]:
        """Tyre change seconds by number of tyres changed (0 to 4)"""
        rule = self.rule
        return (0.0, *(float(rule[f"tyre_change_time_{count}"]) for count in range(1, 5)))  # type: ignore[return-value]

    def has_tyres(self) -> bool:
        """Any tyre on a wheel of the plan"""
        return any(name for row in self.rows for name in row)

    def status(self) -> dict:
        """Tyres used & allowed, limited stock tyres, stints, changes & time spent changing tyres"""
        changes = sum(1 for seconds in self.change_times[1:] if seconds > 0)
        return {
            "used": sum(1 for name in self.stock if self.uses[name] > 0),
            "maximum": int(self.rule["maximum_tyre"]),
            "stock": sum(1 for name in self.stock if self.setting(extract_tyre_key(name))["enable_limited_stock"]),
            "stints": len(self.rows), "pits": max(len(self.rows) - 1, 0),
            "changes": changes, "time": sum(self.change_times[1:]),
        }

    # Link to fuel strategy (see fuel_calculator TyreLink of former page)
    def full_change_seconds(self) -> float:
        """Time to change 4 tyres (tyre rules)"""
        return self.change_time_table()[4]

    def start_tread(self, default: float) -> float:
        """Tread at start: tyres of first stint (compound starting tread), else default"""
        treads = [min(self.setting(extract_tyre_key(name))[CORNER_STARTING_TREAD[corner]], 100.0)
                  for corner, name in enumerate(self.rows[0]) if name] if self.rows else []
        return sum(treads) / len(treads) if treads else default

    def fresh_tread(self) -> float:
        """Tread of new tyres of compound selected in stock"""
        return min(average_setting(self.setting(self.compound), CORNER_STARTING_TREAD), 100.0)

    def wear_factor(self) -> float:
        """Wear of compound selected in stock relative to measured compound"""
        reference = average_setting(self.setting(self.measured), CORNER_WEAR_PER_STINT)
        selected = average_setting(self.setting(self.compound), CORNER_WEAR_PER_STINT)
        return selected / reference if reference > 0 and selected > 0 else 1.0

    def stop_change_times(self) -> list[float]:
        """Tyre change seconds of each stop (rows after start)"""
        return list(self.change_times[1:])

    def stop_tyre_changes(self) -> list[int]:
        """Tyres changed at each stop, empty list if no tyre planned"""
        return list(self.row_changes[1:]) if self.has_tyres() else []

    def set_stints(self, strategy: Strategy) -> bool:
        """One row per stint of a ready strategy: added rows keep the tyres of the stint before
        (or of rows kept aside), True if rows or wear changed

        Same stints & wear as last time: nothing to change (strategy calculated again for
        another input, or tyre plan rounds of a calculation).
        """
        linked = strategy.ready
        key = (tuple(strategy.stints) if linked else (), linked, self.wear_per_lap, len(self.rows))
        if key == self._stints_key:
            return False
        self.stint_laps = list(strategy.stints) if linked else []
        if linked:
            count = len(strategy.stints)
            while len(self.rows) > count:  # kept aside (not lost), back when stints grow
                self.spare_rows.insert(0, self.rows.pop())
            while len(self.rows) < count:
                if self.spare_rows:
                    self.rows.append(self.spare_rows.pop(0))
                else:
                    self.rows.append(list(self.rows[-1]) if self.rows else [""] * WHEELS)
            first = 1
            self.labels = []
            for index, laps in enumerate(strategy.stints, start=1):
                self.labels.append(f"{index}  ({first}-{first + laps - 1})")
                first += laps
        else:
            self.labels = []
        self.linked = linked
        self.refresh()
        self._stints_key = (tuple(strategy.stints) if linked else (), linked, self.wear_per_lap, len(self.rows))
        return True

    def forget_stints(self):
        """Rows synced again at next strategy (tyres or rows edited)"""
        self._stints_key = None

    # Proposal
    def propose(self):
        """New tyres (compound selected in stock) on each wheel at the stint it would go below the
        minimum tread, within tyres allowed: short of tyres, the best worn tyre that wheel used
        before (restricted allocation) or any wheel used is fitted again, else tyres are kept"""
        compound = self.compound
        setting = self.setting(compound)
        self.rows = [[""] * WHEELS for _ in self.rows] or [[""] * WHEELS]
        self.spare_rows.clear()
        # Tyres a previous proposal added, now unused: removed, so proposing again adds no stock
        self.stock = [name for name in self.stock if name not in self.proposed_names]
        self.proposed_names.clear()
        if setting["enable_limited_stock"]:
            others = sum(1 for name in self.stock if extract_tyre_key(name) != compound
                         and self.setting(extract_tyre_key(name))["enable_limited_stock"])
            allowed = max(int(self.rule["maximum_tyre"]) - others, 0)
        else:
            allowed = len(self.stock) + len(self.rows) * WHEELS  # no limit
        free = [name for name in self.stock if extract_tyre_key(name) == compound]
        restricted = bool(self.rule["enable_restricted_allocation"])
        removed: list[list[tuple[str, float]]] = [[] for _ in range(WHEELS)]  # tyres taken off, per wheel
        minimum = self.minimum_tread * 0.01
        current = [""] * WHEELS
        tread = [0.0] * WHEELS
        fitted = 0
        short_rows: list[int] = []
        for row_index, row in enumerate(self.rows):
            for corner in range(WHEELS):
                wear = self.row_wear(row_index, setting, corner)
                if current[corner] and tread[corner] - wear >= minimum - 1e-9:
                    pass  # tyre lasts this stint
                elif fitted < allowed:
                    if free:
                        name = free.pop(0)
                    else:
                        name = encode_tyre_name(compound, tuple(self.stock))
                        self.stock.append(name)
                        self.proposed_names.add(name)
                    fitted += 1
                    if current[corner]:
                        removed[corner].append((current[corner], tread[corner]))
                    current[corner] = name
                    tread[corner] = min(setting[CORNER_STARTING_TREAD[corner]], 100.0) * 0.01
                else:
                    pool = removed[corner] if restricted else [tyre for wheel in removed for tyre in wheel]
                    best = max(pool, key=lambda tyre: tyre[1], default=None)
                    if best is not None and best[1] > tread[corner]:
                        for wheel in removed:
                            if best in wheel:
                                wheel.remove(best)
                        if current[corner]:
                            removed[corner].append((current[corner], tread[corner]))
                        current[corner], tread[corner] = best
                    if tread[corner] - wear < minimum - 1e-9 and row_index + 1 not in short_rows:
                        short_rows.append(row_index + 1)
                row[corner] = current[corner]
                tread[corner] -= wear
        self.proposal_short = short_rows
        self.forget_stints()
        self.refresh()

    # Plan edits
    def assign(self, row: int, corner: int, name: str) -> str:
        """Tyre of stock on a wheel of a row, "" once fitted, else why not (same tyre on another
        wheel of the row, or used on another wheel with restricted allocation)"""
        if not (0 <= row < len(self.rows) and 0 <= corner < WHEELS) or name not in self.stock:
            return tr("Invalid tyre name.")
        for column, other in enumerate(self.rows[row]):
            if column != corner and other == name:
                return trm(f"<b>{name}</b> already installed on <b>{HEADER_TYREPLAN[column]}</b> wheel.<br><br>"
                           f"Cannot install the same tyre on two wheels at the same time.")
        if self.rule["enable_restricted_allocation"]:
            for row_index, tyres in enumerate(self.rows):
                for column, other in enumerate(tyres):
                    if other == name and column != corner and (row_index, column) != (row, corner):
                        return trm(f"<b>{name}</b> already used on <b>{HEADER_TYREPLAN[column]}</b> wheel.<br><br>"
                                   f"Cannot allocate already used tyre on a different wheel.")
        self.rows[row][corner] = name
        self.forget_stints()
        self.refresh()
        return ""

    def clear_cells(self, cells: list[tuple[int, int]]):
        """Tyres taken off wheels of rows"""
        for row, corner in cells:
            if 0 <= row < len(self.rows) and 0 <= corner < WHEELS:
                self.rows[row][corner] = ""
        self.forget_stints()
        self.refresh()

    def insert_row(self, row: int, copy_from: int = -1):
        """New row at row (end if out of range), tyres of row copy_from (none if -1)"""
        if not 0 <= row <= len(self.rows):
            row = len(self.rows)
        tyres = list(self.rows[copy_from]) if 0 <= copy_from < len(self.rows) else [""] * WHEELS
        self.rows.insert(row, tyres)
        self.forget_stints()
        self.refresh()

    def delete_rows(self, rows: list[int]):
        """Rows deleted (a plan keeps one row)"""
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self.rows):
                del self.rows[row]
        if not self.rows:
            self.rows.append([""] * WHEELS)
        self.forget_stints()
        self.refresh()

    # Stock
    def add_tyre(self, compound: str = "") -> str:
        """New tyre of a compound (compound selected in stock by default) added to stock"""
        name = encode_tyre_name(compound or self.compound, tuple(self.stock))
        self.stock.append(name)
        self.refresh()
        return name

    def remove_tyres(self, names: list[str]):
        """Tyres taken out of stock, and off the plan"""
        removed = set(names)
        self.stock = [name for name in self.stock if name not in removed]
        self.proposed_names.difference_update(removed)
        self.rows = [[name if name not in removed else "" for name in row] for row in self.rows]
        self.spare_rows = [[name if name not in removed else "" for name in row] for row in self.spare_rows]
        self.forget_stints()
        self.refresh()

    def unused_tyres(self) -> list[str]:
        return [name for name in self.stock if self.uses[name] <= 0]

    def sort_stock(self, by_stints: bool):
        """Stock sorted by compound (then number), or by stints run (most first)"""
        if by_stints:
            self.stock.sort(key=lambda name: -self.uses[name])
        else:
            self.stock.sort(key=decode_tyre_name)

    def set_rule(self, key: str, value) -> bool:
        """Tyre rule changed (in range), True if changed"""
        if key == "enable_restricted_allocation":
            value = bool(value)
        elif key in RULE_RANGES:
            maximum, decimals = RULE_RANGES[key]
            try:
                number = float(value)
            except (TypeError, ValueError):
                return False
            number = min(max(number if isfinite(number) else 0.0, 0.0), maximum)
            value = round(number) if decimals == 0 else round(number, decimals)
        else:
            return False
        if self.rule.get(key) == value:
            return False
        self.rule[key] = value
        self.forget_stints()
        self.refresh()
        return True

    # QML view
    def view(self) -> dict:
        """Tyre tab: rows (tyre & tread of each wheel, change time), stock, rules, status"""
        rows = []
        for row_index, row in enumerate(self.rows):
            cells = []
            for corner, name in enumerate(row):
                info = self.cells[row_index][corner] if row_index < len(self.cells) else {}
                if not name or not info:
                    cells.append({"name": "", "text": "", "color": "", "fraction": 0.0, "dim": False})
                    continue
                remaining, end = info["remaining"], info["end"]
                cells.append({
                    "name": name, "text": tread_text(remaining, end), "color": tread_color(remaining),
                    "fraction": min(max(remaining, 0.0), 1.0) if isfinite(remaining) else 0.0,
                    "endFraction": min(max(end, 0.0), 1.0) if isfinite(end) else 0.0,
                    "dim": self.highlight_new and info["used"], "compound": extract_tyre_key(name),
                })
            seconds = self.change_times[row_index] if row_index < len(self.change_times) else 0.0
            rows.append({
                "label": self.labels[row_index] if self.linked and row_index < len(self.labels) else str(row_index + 1),
                "cells": cells, "change": f"{seconds:+.1f}s" if seconds > 0 else tr("N/A"),
                "changes": self.row_changes[row_index] if row_index < len(self.row_changes) else 0,
            })
        stock = [{"name": name, "stints": self.uses[name], "compound": extract_tyre_key(name)} for name in self.stock]
        return {
            "name": self.name, "linked": self.linked, "rows": rows, "stock": stock,
            "compounds": self.compounds, "compound": self.compound, "rule": dict(self.rule),
            "highlightNew": self.highlight_new, "status": self.status(),
            "proposal": trm(f"Not enough tyres allowed: worn tyres kept at stint {', '.join(map(str, self.proposal_short))}")
            if self.proposal_short else "",
        }
