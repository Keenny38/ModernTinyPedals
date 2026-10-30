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
Race calculator team plan (mixin of RaceBackend): line-up typed before the race (driver names, drivers
added or removed), driver planned for each stint (else chosen by the plan), names of the LMU team taking
the place of the names typed once the game gives them (see merge_team_names)
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from PySide6.QtCore import Slot

from ...fuel_strategy import MAX_DRIVERS, MAX_STOPS, driver_numbers, parse_stint_drivers, stint_drivers_text
from ...i18n import tr
from .race_base import RaceBase
from .race_model import DRIVER_COLORS, driver_rows, driver_table_text, duration_text, laps_text

MAX_NAME_LENGTH = 40  # driver name typed
WORD_SPLIT = re.compile(r"[\s._\-]+")


def team_names(text: str) -> list[str]:
    """Names of the calculator drivers (input_driver_names: one per line, LMU team order), "" not set"""
    if not isinstance(text, str) or not text.strip():
        return []
    names = [name.strip() for name in text.split("\n")][:MAX_DRIVERS]
    while names and not names[-1]:
        names.pop()
    return names


def team_names_text(names: Sequence[str]) -> str:
    names = [str(name).strip()[:MAX_NAME_LENGTH] for name in names][:MAX_DRIVERS]
    while names and not names[-1]:
        names.pop()
    return "\n".join(names)


def names_alike(typed: str, real: str) -> bool:
    """Name typed close to a game name: one inside the other, or a word in common (3 letters at least)"""
    typed, real = typed.strip().casefold(), real.strip().casefold()
    if len(typed) < 3 or len(real) < 3:
        return typed == real and bool(typed)
    if typed in real or real in typed:
        return True
    words = {word for word in WORD_SPLIT.split(typed) if len(word) >= 3}
    return any(word in words for word in WORD_SPLIT.split(real) if len(word) >= 3)


def merge_team_names(names: Sequence[str], game: Sequence[str]) -> list[str]:
    """Names of the calculator drivers with the names of the game team: a name typed matching a game
    name (same name, else close: see names_alike) keeps its place and takes the game name, other game
    names take in order the places of names matching none (typed names first, then places not named),
    then are added after (drivers planned for stints keep their place: names change, never places)"""
    result = [str(name).strip() for name in names][:MAX_DRIVERS]
    real: list[str] = []
    for name in game:
        name = str(name).strip()
        if name and name.casefold() not in {other.casefold() for other in real}:
            real.append(name)
    taken: set[int] = set()
    placed: set[int] = set()
    for match in (lambda typed, name: typed.casefold() == name.casefold(), names_alike):
        for game_index, name in enumerate(real):
            if game_index in placed:
                continue
            for place, typed in enumerate(result):
                if place not in taken and typed and match(typed, name):
                    result[place] = name
                    taken.add(place)
                    placed.add(game_index)
                    break
    free = [place for place, typed in enumerate(result) if place not in taken and typed]
    free += [place for place, typed in enumerate(result) if place not in taken and not typed]
    for game_index, name in enumerate(real):
        if game_index in placed:
            continue
        if free:
            result[free.pop(0)] = name
        elif len(result) < MAX_DRIVERS:
            result.append(name)
    return result


class TeamPlan(RaceBase):
    """Line-up & driver of each stint of race calculator page (team tab)"""

    game_team: tuple[str, ...] = ()  # names of the LMU team car drivers, as the game gave them last

    def driver_names(self) -> list[str]:
        """Name of each calculator driver ("" not named), as many as drivers"""
        names = team_names(self.values["input_driver_names"])
        count = self.values["input_drivers"]
        return (names + [""] * count)[:count]

    def driver_label(self, number: int) -> str:
        """Name of calculator driver (1 to drivers), else "Driver N" """
        names = self.driver_names()
        if 0 < number <= len(names) and names[number - 1]:
            return names[number - 1]
        return f"{tr('Driver')} {number}"

    def driver_short(self, number: int) -> str:
        """Name of calculator driver, else its number (plan column)"""
        names = self.driver_names()
        return names[number - 1] if 0 < number <= len(names) and names[number - 1] else str(number)

    def keep_team_names(self):
        """Driver names of the LMU team (garage screen team, drivers of team stints) take the place of
        the names typed (see merge_team_names)"""
        game = list(self.garage.drivers)
        game += [usage.driver for usage in self.team_stints if usage.driver not in game]
        game_team = tuple(name for name in game if name.strip())
        if not game_team:
            return
        text = team_names_text(merge_team_names(team_names(self.values["input_driver_names"]), game_team))
        changed = game_team != self.game_team
        self.game_team = game_team
        if self.values["input_driver_names"] != text:
            self.setInput("input_driver_names", text)  # plan & team plan shown again
        elif changed:
            self.publish("teamPlan", self.team_plan_view())

    # Line-up
    @Slot(int, str)
    def setDriverName(self, index: int, name: str):
        names = team_names(self.values["input_driver_names"])
        if not 0 <= index < min(self.values["input_drivers"], MAX_DRIVERS):
            return
        names += [""] * (index + 1 - len(names))
        names[index] = " ".join(str(name).split())[:MAX_NAME_LENGTH]
        self.setInput("input_driver_names", team_names_text(names))

    @Slot()
    def addDriver(self):
        drivers = self.values["input_drivers"]
        if drivers < MAX_DRIVERS:
            self.setInput("input_drivers", drivers + 1)

    @Slot(int)
    def removeDriver(self, index: int):
        """Driver removed: name, pace & driving times of the drivers after it move up, stints planned for
        it chosen by the plan again, stints of the drivers after it follow them"""
        drivers = self.values["input_drivers"]
        if drivers < 2 or not 0 <= index < drivers:
            return
        names = team_names(self.values["input_driver_names"])
        if index < len(names):
            del names[index]
        rows = driver_rows(self.values["input_driver_table"])
        del rows[index]
        rows.append((0.0, 0.0, 0.0))
        number = index + 1
        planned = [0 if driver == number else driver - 1 if driver > number else driver
                   for driver in parse_stint_drivers(self.values["input_stint_drivers"])]
        self.set_values({
            "input_drivers": drivers - 1,
            "input_driver_names": team_names_text(names),
            "input_driver_table": driver_table_text(rows),
            "input_stint_drivers": stint_drivers_text(planned),
        })

    # Driver of each stint
    @Slot(int, int)
    def setStintDriver(self, stint: int, driver: int):
        """Driver planned for a stint of the race (index), 0 = chosen by the plan"""
        if not 0 <= stint <= MAX_STOPS or not 0 <= driver <= self.values["input_drivers"]:
            return
        planned = list(parse_stint_drivers(self.values["input_stint_drivers"]))
        planned += [0] * (stint + 1 - len(planned))
        planned[stint] = driver
        self.setInput("input_stint_drivers", stint_drivers_text(planned))

    @Slot()
    def keepStintDrivers(self):
        """Drivers the plan chose kept as planned for every stint (rotation kept when the plan changes)"""
        strategy = self.race_strategy
        if strategy.ready and self.values["input_drivers"] > 1:
            self.setInput("input_stint_drivers", stint_drivers_text(strategy.stint_drivers))

    @Slot()
    def clearStintDrivers(self):
        self.setInput("input_stint_drivers", "")

    def team_plan_view(self) -> dict:
        """Line-up (name, color, stints & driving time of each driver) & stints of the race with their
        driver (planned or chosen by the plan); race under way: stints done with the driver seen"""
        count = self.values["input_drivers"]
        names = self.driver_names()
        game = {name.casefold() for name in self.game_team}
        planned = parse_stint_drivers(self.values["input_stint_drivers"])
        strategy, base, state = self.strategy, self.race_strategy, self.race_state
        offset = strategy.stops_done if state is not None else 0
        team = count > 1
        stints = []
        stint_count = [0] * count
        if state is not None and offset:
            seen = driver_numbers(state.stint_drivers, base, count, tuple(names)) if team else []
            for index in range(offset):
                number = (seen[index] if index < len(seen) else 0) or (base.driver_of(index) if team else 1)
                stints.append(self.stint_row(index, number, "done", "", tr("Stint done"), planned))
                if 0 < number <= count:
                    stint_count[number - 1] += 1
        if strategy.ready:
            starts = [self.plan_setup.clock_offset if state is not None else 0.0]
            starts += [stop.clock + stop.seconds for stop in strategy.stops]
            for index, (first, last) in enumerate(strategy.stint_bounds()):
                number = strategy.driver_of(index) if team else 1
                seconds = strategy.stint_seconds[index] if index < len(strategy.stint_seconds) else 0.0
                laps = f"{tr('Laps')} {first}-{last} · {laps_text(last - first + 1)}"
                timing = f"{self.time_text(starts[index]) if index < len(starts) else ''} · {seconds / 60:.0f} min"
                kind = "current" if state is not None and index == 0 else "plan"
                stints.append(self.stint_row(offset + index, number, kind, laps, timing, planned))
                if 0 < number <= count:
                    stint_count[number - 1] += 1
        drivers = []
        for index in range(count):
            seconds = strategy.driver_seconds[index] if index < len(strategy.driver_seconds) else 0.0
            name = names[index]
            drivers.append({
                "number": index + 1, "name": name, "placeholder": f"{tr('Driver')} {index + 1}",
                "color": DRIVER_COLORS[index % len(DRIVER_COLORS)], "fromGame": bool(name) and name.casefold() in game,
                "stints": stint_count[index], "time": duration_text(seconds) if strategy.ready and team else "",
            })
        return {
            "drivers": drivers, "stints": stints, "team": team, "canAdd": count < MAX_DRIVERS,
            "planned": any(planned), "ready": strategy.ready,
            "choices": [tr("Auto")] + [self.driver_label(index + 1) for index in range(count)],
            "gameTeam": ", ".join(self.game_team),
        }

    def stint_row(self, stint: int, number: int, kind: str, laps: str, timing: str, planned: Sequence[int]) -> dict:
        """Stint of the race (index): driver shown & planned (0 = chosen by the plan), kind "done", "current"
        (in progress: driver in the car) or "plan" """
        count = self.values["input_drivers"]
        wanted = planned[stint] if stint < len(planned) and planned[stint] <= count else 0
        name = self.driver_label(number) if count > 1 else self.driver_label(1)
        return {
            "stint": stint, "number": stint + 1, "driver": number, "planned": wanted, "kind": kind,
            "name": name,
            # Driver combo box of a stint planned: Auto (driver chosen by the plan), then each driver
            "choices": [f"{tr('Auto')} · {name}", *(self.driver_label(index + 1) for index in range(count))]
            if kind == "plan" else [],
            "color": DRIVER_COLORS[(number - 1) % len(DRIVER_COLORS)] if number > 0 else "",
            "laps": laps, "timing": timing,
        }
