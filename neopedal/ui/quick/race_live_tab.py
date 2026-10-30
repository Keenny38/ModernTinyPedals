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
Race calculator live tab (mixin of RaceBackend): every input value the game gives (see race_live_data),
garage screens asked, live values filled in or followed, live race items
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from html import escape
from typing import Any

from PySide6.QtCore import Slot

from ...api_control import api
from ...const_api import API_LMU_NAME
from ...fuel_strategy import (
    history_laps,
    plan,
    whole_laps,
)
from ...i18n import tr, trm
from ...module_info import minfo
from ...process.results_text import number_text, position_text
from ...race_live import clock as race_clock
from ...race_live_data import (
    LITERS_PER_GALLON,
    GarageData,
    LiveValue,
    collect_rain,
    parse_garage,
    write_pit_menu,
)
from ...race_live_data import collect as collect_live
from ...setting import cfg
from ...userfile.tyre_strategy import (
    DEFAULT_TYRE_SET,
    HEADER_TYREPLAN,
)
from . import race_results as results
from .formatting import clock_seconds
from .race_base import TABS, RaceBase
from .race_model import (
    INPUT_SPECS,
    RACE_SESSION,
    laptime_text,
    start_time_text,
    unit_text,
)
from .race_tyres import (
    tread_color,
)

LIVE_GROUPS = (  # live tab groups: key, title
    ("race", "Race"), ("pace", "Pace & Consumption"), ("start", "Race Start"), ("pit", "Pit Stop"),
    ("tyres", "Tyres"), ("weather", "Weather"),
)
FILLED_KEYS = frozenset((  # live values the Game Session source & Follow Live fill in from laps (fill_in_data)
    "race_length", "input_lap_time", "input_fuel_per_lap", "input_energy_per_lap", "input_wear_per_lap",
    "input_tank_capacity",
))
LIVE_PART_SIGNALS = {"status": "liveDataStatusChanged", "busy": "liveBusyChanged", "differing": "liveDifferingChanged",
                     "tyres": "liveTyresChanged", "race": "liveRaceChanged"}


class LiveTab(RaceBase):
    """Live game data of race calculator page"""

    # Live game data (live tab): every input value the game gives, see race_live_data
    @staticmethod
    def unfollowed_live() -> set[str]:
        """Live values the user turned off: left out of the Game Session source, Follow Live & Fill In All"""
        text = cfg.user.config["fuel_calculator"].get("live_unfollowed", "")
        return {key for key in text.split(",") if key} if isinstance(text, str) else set()

    def update_garage_timer(self):
        """LMU garage screens asked at once, then every few seconds while the live or team tab is shown
        (names of the team drivers) or inputs follow live"""
        follow = bool(cfg.user.config["fuel_calculator"].get("enable_follow_live"))
        if self.active and self.game_data and (self.tab in (TABS.index("live"), TABS.index("team")) or follow):
            if not self._garage_timer.isActive():
                self._garage_timer.start()
                self.refresh_garage()
        else:
            self._garage_timer.stop()

    @Slot()
    def refreshGarage(self):
        if self.game_data_refused():
            return
        self.refresh_garage()
        self.publish_live_data()

    def refresh_garage(self, apply: bool = False):
        """LMU garage screens asked (game in a session only), apply: followed values filled in once
        answered"""
        if not self.game_data or not api.read.state.active():
            self._apply_garage = False
            if self.garage != GarageData():  # values of a session left behind
                self.garage = GarageData()
                self.garage_time = ""
            return
        if apply:
            self._apply_garage = True
        self.garage_request.start()

    def received_garage(self, answers: list):
        """Game answers: repair & refuel screen, tyre screen, session settings"""
        self.garage_request.busy = False
        refuel, tyres, session = (list(answers) + [None] * 3)[:3]
        self.garage = parse_garage(refuel, tyres, session)
        self.garage_time = clock_seconds() if self.garage.available else ""
        self.keep_team_names()
        apply = self._apply_garage or bool(cfg.user.config["fuel_calculator"].get("enable_follow_live"))
        self._apply_garage = False
        values = None
        if apply and self.garage.available and self.live_source:
            self.apply_live(followed=True)
            values = self.live_values
        self.publish_live_data(values)

    def update_pit_menu_available(self):
        """Pit Menu button enabled in an LMU session only (the game pit menu exists there), told to QML"""
        available = bool(self.game_data) and api.name == API_LMU_NAME and bool(api.read.state.active())
        if available != self.pit_menu_available:
            self.pit_menu_available = available
            self.liveChanged.emit()

    def next_plan_stop(self):
        """Next stop of the plan shown: first stop of the rest of the race (live race state), else the first stop
        of the whole race plan not done yet (live plan off while a race is under way: stops already made left
        out), None if none left"""
        strategy = self.strategy
        if not strategy.ready or not strategy.stops:
            return None
        stops = strategy.stops
        if self.race_state is None and self._race_running:  # plan of the whole race while the race is under way
            done = whole_laps(self.race_setup.formation_laps) + max(api.read.lap.completed_laps(), 0)
            stops = [stop for stop in stops if stop.lap > done]
        return stops[0] if stops else None

    @Slot()
    def setGamePitMenu(self):
        """Refill of the next stop of the plan set in the LMU pit menu (fuel, or virtual energy of a
        car using it), in background"""
        if not self.game_data:
            self.host.toast(tr("Race Calculator is off"))
            return
        if not self.strategy.ready or not self.strategy.stops:
            self.host.toast(tr("No pit stop in the plan"))
            return
        stop = self.next_plan_stop()
        if stop is None:
            self.host.toast(tr("Every stop of the plan is done: plan the race under way (Live Race) for the next one"))
            return
        fuel = stop.fuel_after * LITERS_PER_GALLON if self.is_gallon else stop.fuel_after
        self.jobs.run("pit menu", partial(write_pit_menu, fuel, stop.energy_after), self.pit_menu_written,
                      key="pit menu")

    def pit_menu_written(self, result: tuple):
        state, refill = result
        if state == "set" and refill is not None:
            self.host.toast(tr("Pit menu set for the next stop:") + " " + escape(refill.text))
        elif state == "refused":
            self.host.toast(tr("The game refused the pit menu change"))
        elif state == "missing":
            self.host.toast(tr("No refill in the game pit menu (LMU, in a session)"))
        else:
            self.host.toast(tr("Game not answering: pit menu not set"))

    def garage_request_failed(self):
        """Game request raised an error: asked again by the garage timer"""
        self.garage_request.busy = False
        self._apply_garage = False
        self.publish_live_data()

    def dry_plan_laps(self) -> int:
        """Laps of the whole race plan without rain scenario (wet laps of the forecast), from the
        inputs of now (not the last calculation: values filled in together agree)"""
        setup = replace(self.strategy_input(), rain_lap=0, rain_laps=0, rain_tyres=False,
                        tyre_change_seconds=self.tyres.full_change_seconds())
        last, laps = self._dry_plan
        if setup != last:  # planned again only when an input changed (live tab asks every few seconds)
            strategy = plan(setup)
            laps = strategy.race_laps if strategy.ready else 0
            self._dry_plan = (setup, laps)
        return laps

    def collect_live_values(self) -> list[LiveValue]:
        return collect_live(history_laps(minfo.history.consumptionDataSet), self.garage, self.unit_fuel,
                            self.symbol_fuel, self.dry_plan_laps(), tuple(DEFAULT_TYRE_SET))

    def apply_live(self, keys: set[str] | None = None, followed: bool = False, filled: bool = False) -> int:
        """Live values filled in: those of keys, or every value followed (filled: values the Game Session source
        fills in from laps too), count filled in"""
        unfollowed = self.unfollowed_live()

        def wanted(item: LiveValue) -> bool:
            if item.value is None:
                return False
            if keys is not None:
                return item.key in keys
            return (followed and item.follow and item.key not in unfollowed
                    and (filled or item.key not in FILLED_KEYS))

        count = 0
        values = self.collect_live_values()  # game read once per action
        with self.batch():
            for item in values:
                if item.key != "rain" and wanted(item) and not self.live_matches(item):
                    self.apply_live_value(item)
                    count += 1
            # Rain laps last: race laps follow the values just filled in (only rain planned again)
            if count and values and values[-1].key == "rain":
                values[-1] = collect_rain(self.garage, self.dry_plan_laps())
            rain = next((item for item in values if item.key == "rain"), None)
            if rain is not None and wanted(rain) and not self.live_matches(rain):
                self.apply_live_value(rain)
                count += 1
        self.live_values = values  # as filled in: shown by publish_live_data of the same action
        return count

    def apply_live_value(self, item: LiveValue):
        """One live value filled in (inputs, tyre rules or rain scenario)"""
        key, value = item.key, item.value
        if key == "race_length":
            kind, length = value
            self.setInput("input_race_laps" if kind == "laps" else "input_race_minutes", length)
            self.setInput("enable_lap_race", kind == "laps")
        elif key == "input_measured_compound":
            self.set_measured_compound(int(value))
        elif key in ("tyre_change_times", "maximum_tyre"):
            rules: tuple[tuple[str, Any], ...]
            if key == "maximum_tyre":
                rules = (("maximum_tyre", value),)
            else:
                two, four = value
                rules = (("tyre_change_time_1", two), ("tyre_change_time_2", two),
                         ("tyre_change_time_3", four), ("tyre_change_time_4", four))
            changed = False
            for rule, number in rules:
                changed |= self.tyres.set_rule(rule, number)
            if changed:
                self.tyre_plan_changed(user_edit=False)
        elif key == "rain":
            wet, first, laps = value
            self.setInput("enable_rain", bool(wet))
            if wet:
                self.setInput("input_rain_lap", first)
                self.setInput("input_rain_laps", laps)
        elif key == "input_drivers":
            self.setInput(key, value)
            self.keep_team_names()
        else:
            self.setInput(key, value)

    def live_matches(self, item: LiveValue) -> bool:
        """Calculator already holds the live value (to the decimals of the input)"""
        key, value, values = item.key, item.value, self.values
        if value is None:
            return True
        if key == "race_length":
            kind, length = value
            laps = kind == "laps"
            return values["enable_lap_race"] == laps and values["input_race_laps" if laps else "input_race_minutes"] == length
        if key == "input_measured_compound":
            return self.measured_index == value
        rule = self.tyres.rule
        if key == "tyre_change_times":
            two, four = value
            return all(abs(float(rule[f"tyre_change_time_{count}"]) - seconds) < 0.05
                       for count, seconds in ((1, two), (2, two), (3, four), (4, four)))
        if key == "maximum_tyre":
            return int(rule["maximum_tyre"]) == value
        if key == "rain":
            wet, first, laps = value
            if not wet:
                return not values["enable_rain"]
            return bool(values["enable_rain"]) and values["input_rain_lap"] == first and values["input_rain_laps"] == laps
        current = values.get(key)
        if isinstance(value, bool) or isinstance(current, bool):
            return bool(current) == bool(value)
        spec = INPUT_SPECS.get(key)
        decimals = spec.decimals if spec is not None else 3
        if not isinstance(current, (int, float)):
            return False
        return abs(float(current) - float(value)) < 0.5 * 10 ** -decimals + 1e-9

    def live_current(self, key: str) -> str:
        """Value of the calculator a live value would replace, as text"""
        values, symbol = self.values, self.symbol_fuel
        rule = self.tyres.rule
        if key == "race_length":
            if values["enable_lap_race"]:
                return trm(f"{values['input_race_laps']} laps")
            return f"{values['input_race_minutes']} min"
        if key == "input_formation_laps":
            return trm(f"{values[key]:g} lap(s)")
        if key == "input_race_start_minutes":
            return start_time_text(values[key]) if values[key] >= 0 else results.DASH
        if key == "input_drivers":
            return f"{values[key]}"
        if key == "input_lap_time":
            return laptime_text(values[key])
        if key == "input_measured_compound":
            return tuple(DEFAULT_TYRE_SET)[self.measured_index]
        if key in ("input_fuel_start", "input_energy_start") and values[key] <= 0:
            return tr("Full Tank")
        if key == "tyre_change_times":
            return f"{number_text(float(rule['tyre_change_time_2']), 1)} s / {number_text(float(rule['tyre_change_time_4']), 1)} s"
        if key == "maximum_tyre":
            return f"{int(rule['maximum_tyre'])}"
        if key == "rain":
            if not values["enable_rain"]:
                return tr("Off")
            first, laps = values["input_rain_lap"], values["input_rain_laps"]
            return trm(f"Laps {first}-{first + laps - 1}") if laps > 0 else trm(f"From lap {first}")
        value = values.get(key)
        if isinstance(value, bool):
            return tr("On") if value else tr("Off")
        spec = INPUT_SPECS.get(key)
        if spec is None or not isinstance(value, (int, float)):
            return f"{value}"
        decimals = {"input_tank_capacity": 1, "input_fuel_start": 1, "input_energy_start": 1, "input_tread_start": 1,
                    "input_pit_seconds": 1, "input_driver_change_seconds": 1}.get(key, spec.decimals)
        unit = unit_text(spec.unit, symbol)
        return f"{number_text(value, decimals)} {unit}".strip()

    def live_race_items(self) -> list[dict]:
        """Race under way read from the game: lap, race time, amounts, stops, track state, penalties,
        repair, class position (empty out of a race)"""
        read = api.read
        session = read.session
        if session.session_type() != RACE_SESSION or not read.state.active() or not session.in_race():
            return []
        elapsed = max(session.elapsed() - max(session.start(), 0.0), 0.0)
        left = session.remaining()
        lap_race = session.finish_type() == 1
        laps_done = read.lap.completed_laps()
        maximum = read.lap.maximum()
        if read.lap.safety_car_active():
            track, warning = tr("Safety Car"), True
        elif session.yellow_flag_state() > 0:
            track, warning = tr("Full Course Yellow"), True
        else:
            track, warning = tr("Green Flag"), False
        penalties = read.vehicle.number_penalties()
        repair = read.vehicle.repair_time()
        pit_time = read.vehicle.pit_stop_time()
        player = read.vehicle.player_index()
        place, cars = 0, 0
        for index in range(read.vehicle.total_vehicles()):
            if index == player or read.vehicle.same_class(index):
                cars += 1
                if index != player and read.vehicle.place(index) < read.vehicle.place():
                    place += 1
        items = [
            {"title": tr("Lap"), "value": f"{laps_done + 1}" + (f" / {maximum}" if lap_race and 0 < maximum < 100000 else ""),
             "warning": False},
            {"title": tr("Race Time"), "value": race_clock(elapsed), "warning": False},
            {"title": tr("Time left"), "value": race_clock(max(left, 0.0)) if not lap_race else results.DASH,
             "warning": False},
            {"title": tr("Fuel"), "value": f"{number_text(self.unit_fuel(read.engine.fuel()), 1)} {self.symbol_fuel}",
             "warning": False},
            {"title": tr("Energy"), "value": f"{read.engine.virtual_energy() * 100:.0f} %", "warning": False},
            {"title": tr("Tread"), "value": f"{sum(read.tyre.wear()) * 25:.0f} %", "warning": False},
            {"title": tr("Pit Stops"), "value": f"{read.vehicle.number_pitstops()}", "warning": False},
            {"title": tr("Track"), "value": track, "warning": warning},
            {"title": tr("Penalties"), "value": f"{penalties}", "warning": penalties > 0},
        ]
        if cars:
            items.append({"title": tr("Class Position"), "value": position_text(place + 1, cars), "warning": False})
        if repair > 0:
            items.append({"title": tr("Pending Repair"), "value": f"{repair:.0f} s", "warning": True})
        if pit_time > 0:
            items.append({"title": tr("Next Stop (Game)"), "value": f"{number_text(pit_time, 1)} s", "warning": False})
        return items

    def garage_tyres(self) -> dict:
        """Tyres the pit menu offers (LMU): allocation, new compounds, used tyres of each wheel"""
        garage = self.garage
        wheels = []
        for wheel, offers in zip(HEADER_TYREPLAN, garage.used_tyres):
            wheels.append({"wheel": tr(wheel), "tyres": [
                {"text": f"{offer.compound} {offer.tread:.0f}%", "color": tread_color(offer.tread / 100),
                 "compound": offer.compound, "tip": offer.text} for offer in offers]})
        return {
            "known": bool(garage.new_compounds or garage.used_tyres or garage.tyres_allowed),
            "allowed": garage.tyres_allowed, "newLeft": garage.new_tyres_left,
            "newCompounds": list(garage.new_compounds), "wheels": wheels,
            "used": sum(len(offers) for offers in garage.used_tyres),
        }

    def live_data_status(self) -> str:
        if not api.read.state.active():
            return tr("Game not running or not in a session: values of the car & session needed")
        if self.garage_request.busy and not self.garage_time:
            return tr("Asking game…")
        if self.garage_time:
            return trm("LMU garage data at {}").replace("{}", self.garage_time, 1)
        return tr("No LMU garage data: pit stop times, tyres & team come from LMU in a session")

    def publish_live_data(self, values: list[LiveValue] | None = None):
        """Live tab shown again where anything changed: values of the game against the calculator (values:
        collected by apply_live in the same action, else collected now), rows synced in place, other parts
        notified only when changed (race time changes at each refresh: race card only)"""
        if not self.game_data:  # calculator off: page empty, game not read
            return
        if values is None:
            values = self.collect_live_values()
        self.live_values = values
        unfollowed = self.unfollowed_live()
        rows = []
        for item in values:
            known = item.value is not None
            rows.append({
                "key": item.key, "group": item.group, "header": False, "title": tr(item.title),
                "game": trm(tr(item.text)), "calc": self.live_current(item.key),
                "source": trm(tr(item.source)), "tip": trm(tr(item.tip)), "known": known, "auto": item.follow,
                "followed": item.follow and item.key not in unfollowed,
                "differs": known and not self.live_matches(item),
            })
        parts = {
            "status": self.live_data_status(), "busy": self.garage_request.busy,
            "differing": sum(1 for row in rows if row["differs"] and row["followed"]),
            "tyres": self.garage_tyres(), "race": self.live_race_items(),
        }
        changed = [name for name, value in parts.items() if value != self._live_parts[name]]
        rows_changed = rows != self._live_rows
        if rows_changed:
            self._live_rows = rows
            shown = []
            for key, title in LIVE_GROUPS:  # title row before each group
                members = [row for row in rows if row["group"] == key]
                if members:
                    shown.append({"key": f"hdr:{key}", "header": True, "title": tr(title), "game": "", "calc": "",
                                  "source": "", "tip": "", "known": True, "auto": False, "followed": False,
                                  "differs": False})
                    shown.extend(members)
            self.live_model.sync(shown)
        for name in changed:
            self._live_parts[name] = parts[name]
            getattr(self, LIVE_PART_SIGNALS[name]).emit()
        if changed or rows_changed:
            self.liveDataChanged.emit()

    @Slot()
    def addGameTyres(self):
        """Used tyres the pit menu offers added to the tyre stock with their tread (fitted by hand),
        tyre allocation of the game set"""
        tyres = [(offer.compound, offer.tread) for offers in self.garage.used_tyres for offer in offers]
        if not tyres:
            return
        added = self.tyres.add_used_tyres(tyres)
        if self.garage.tyres_allowed > 0:
            self.tyres.set_rule("maximum_tyre", self.garage.tyres_allowed)
        self.tyre_plan_changed()
        self.host.toast(trm(f"{len(added)} used tyre(s) added to stock"))

    @Slot(str)
    def applyLiveValue(self, key: str):
        """Live value of a row filled in (followed or not)"""
        if self.apply_live(keys={key}):
            self.publish_live_data(self.live_values)

    @Slot()
    def applyAllLive(self):
        """Every live value followed filled in"""
        count = self.apply_live(followed=True, filled=True)
        self.host.toast(trm(f"{count} live value(s) filled in") if count else tr("Calculator already holds the live values"))
        self.publish_live_data(self.live_values)

    @Slot(str, bool)
    def setLiveFollowed(self, key: str, followed: bool):
        """Live value filled in by the Game Session source, Follow Live & Fill In All, or left out (kept for next time)"""
        names = self.unfollowed_live() - {key}
        if not followed:
            names.add(key)
        self.set_option("live_unfollowed", ",".join(sorted(names)))
        self.publish_live_data()
