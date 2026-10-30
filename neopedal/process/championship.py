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
Championship standings imported from a CSV file (spreadsheet export), for the Broadcast Director graphics

Columns found by their title (English or French, any case): driver (or name, team when no driver), points,
and if there: team, class, car number. Comma, semicolon or tab separated. Without titles: first text column is
the driver, last number column the points. Drivers sorted by points (by class when classes are given), places
& medals (first three) counted in each class. No Qt.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any, NamedTuple

MAX_ROWS = 500
COLUMN_NAMES = {
    "driver": ("driver", "drivers", "pilote", "pilotes", "name", "nom", "driver name"),
    "points": ("points", "pts", "point", "total"),
    "team": ("team", "équipe", "equipe", "team name", "écurie", "ecurie"),
    "class": ("class", "classe", "category", "catégorie", "categorie", "cat"),
    "number": ("number", "no", "no.", "num", "numéro", "numero", "#", "car", "car number"),
}


class ChampionshipRow(NamedTuple):
    """Driver (or team) of a championship"""

    name: str
    points: float
    team: str = ""
    car_class: str = ""
    number: str = ""


def number_value(text: str) -> float | None:
    """Points of a cell ("125", "12,5", "98 pts"), None if not a number"""
    cleaned = text.strip().lower().replace("pts", "").replace("points", "").replace(" ", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_rows(text: str) -> list[list[str]]:
    """Cells of CSV text (separator guessed), empty lines left out"""
    sample = text[:4096]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for row in csv.reader(io.StringIO(text), dialect):
        cells = [cell.strip() for cell in row]
        if any(cells):
            rows.append(cells)
        if len(rows) > MAX_ROWS:
            break
    return rows


def find_columns(header: list[str]) -> dict[str, int]:
    """Column of each known title"""
    columns: dict[str, int] = {}
    for index, title in enumerate(header):
        name = title.strip().lower()
        for key, names in COLUMN_NAMES.items():
            if name in names and key not in columns:
                columns[key] = index
    return columns


def parse_championship(text: str) -> list[ChampionshipRow]:
    """Drivers of a championship CSV file, empty if none found"""
    rows = read_rows(text.lstrip("﻿"))
    if not rows:
        return []
    columns = find_columns(rows[0])
    if "points" in columns and ("driver" in columns or "team" in columns):
        body = rows[1:]
        name_column = columns.get("driver", columns.get("team", 0))
    else:  # no titles: first text column is the name, last number column the points
        body = rows[1:] if all(number_value(cell) is None for cell in rows[0]) else rows
        if not body:
            return []
        first = body[0]
        name_column = next((index for index, cell in enumerate(first) if cell and number_value(cell) is None), -1)
        point_columns = [index for index, cell in enumerate(first) if number_value(cell) is not None]
        if name_column < 0 or not point_columns:
            return []
        columns = {"points": point_columns[-1]}
    result = []
    for row in body:
        def cell(key: str, row: list[str] = row) -> str:
            index = columns.get(key, -1)
            return row[index] if 0 <= index < len(row) else ""

        name = row[name_column] if name_column < len(row) else ""
        points = number_value(cell("points"))
        if not name or points is None:
            continue
        team = cell("team") if columns.get("team") != name_column else ""
        result.append(ChampionshipRow(name, points, team, cell("class"), cell("number").lstrip("#")))
    return result


def standings(rows: list[ChampionshipRow], car_class: str = "") -> list[tuple[int, ChampionshipRow]]:
    """Place & row of each driver of a class (or every driver), most points first"""
    chosen = [row for row in rows if not car_class or row.car_class == car_class]
    chosen.sort(key=lambda row: (-row.points, row.name.casefold()))
    result = []
    place = 0
    previous: float | None = None
    for index, row in enumerate(chosen, 1):
        if row.points != previous:  # same points: same place
            place = index
            previous = row.points
        result.append((place, row))
    return result


def classes(rows: list[ChampionshipRow]) -> list[str]:
    """Classes of a championship in file order, empty if none given"""
    return list(dict.fromkeys(row.car_class for row in rows if row.car_class))


def points_text(points: float) -> str:
    """Points as shown ("12", "12.5"), "-" if not a number"""
    if not math.isfinite(points):
        return "-"
    return str(int(points)) if points == int(points) else f"{points:.1f}"
