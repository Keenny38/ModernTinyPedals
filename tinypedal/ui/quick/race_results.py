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
Race calculator results shown by the QML page: key figures, strategy timeline, pit stop plan,
details, tyre life, scenarios, driving time, plan against race, class rivals

Plain values (texts, numbers, lists & dicts): handed to QML as they are.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from html import escape
from math import ceil, floor

from ... import calculation as calc
from ...fuel_strategy import RaceState, SavingTarget, Strategy, StrategyInput, Variant, race_result
from ...i18n import tr, trm
from ...module_info import StintDataSet
from ...race_live import Rival
from .race_model import DRIVER_COLORS, RAIN_COLOR, SAFETY_CAR_COLOR, duration_text, laps_text

PLAN_COLUMNS = ("stop", "lap", "window", "time", "fuel", "energy", "tyres", "driver", "seconds")
DASH = "-"


def consumption_details(output_type: str, tank_capacity: float, consumption: float, amount_start: float,
                        total_needed: float, reserve: float, laptime: float, is_gallon: bool) -> tuple[dict, float]:
    """Fuel or energy details for race length of pit stop plan, and laps of a full tank

    consumption: planned per lap (safety margin on consumption included), total_needed: whole
    race incl. safety margin, reserve: kept in tank at every stop.
    """
    total_need_frac = total_needed
    if is_gallon and output_type == "fuel":  # rounded up, 1 decimal place for gallon
        total_need_full = ceil(total_need_frac * 10) / 10
    else:
        total_need_full = ceil(total_need_frac)
    usable = max(tank_capacity - reserve, 0)

    amount_curr = min(total_need_full, tank_capacity)
    end_stint_fuel = calc.end_stint_fuel(max(amount_curr - reserve, 0), 0, consumption)
    estimate_pit_counts = max(calc.end_stint_pit_counts(total_need_full - amount_start, usable - end_stint_fuel), 0)
    pits = ceil(estimate_pit_counts)

    total_runlaps = calc.end_stint_laps(total_need_full, consumption)
    total_runmins = calc.end_stint_minutes(total_runlaps, laptime)
    # Full tank, whether the race needs it or not
    stint_runlaps = calc.end_stint_laps(usable, consumption)
    stint_runmins = calc.end_stint_minutes(stint_runlaps, laptime)
    return {
        "total_needed": f"{total_need_frac:.2f} ≈ {total_need_full:g}",
        "end_stint": f"{end_stint_fuel:.2f}",
        "pit_stops": f"{estimate_pit_counts:.2f} ≈ {pits}",
        "total_laps": f"{total_runlaps:.2f}",
        "total_minutes": f"{total_runmins:.2f}",
        "stint_laps": f"{stint_runlaps:.2f}",
        "stint_minutes": f"{stint_runmins:.2f}",
    }, stint_runlaps


DETAIL_ROWS = (  # name, title, unit, tooltip
    ("total_needed", "Total Needed", "", "Whole race, safety margin included: exact ≈ rounded up"),
    ("pit_stops", "Refuel Stops", "", "Stops this resource alone needs: estimate ≈ whole stops. The pit stop plan "
                                      "may stop more often (driver limit, mandatory stops)"),
    ("total_laps", "Total Laps", "lap", "Laps the total amount lasts"),
    ("total_minutes", "Total Minutes", "min", "Minutes the total amount lasts"),
    ("stint_laps", "Max Stint Laps", "lap", "Laps a full tank lasts, safety margin kept"),
    ("stint_minutes", "Max Stint Minutes", "min", "Minutes a full tank lasts, safety margin kept"),
    ("end_stint", "Left at Stint End", "", "Left in the tank when pitting (less than one lap)"),
    ("one_less_stint", "Consumption for One Less Stop", "per lap", "Consumption per lap to save one pit stop"),
    ("average_refill", "Average Refill", "", "Average amount added per stop of the pit stop plan"),
)


def detail_rows(fuel: dict, energy: dict) -> list[dict]:
    """Details card rows: title, fuel & energy values (one less stop & refill filled in later)"""
    rows = []
    for name, title, unit, tooltip in DETAIL_ROWS:
        rows.append({
            "key": name, "title": tr(title), "tip": tr(tooltip), "unit": tr(unit) if unit != "min" else unit,
            "fuel": fuel.get(name, DASH), "energy": energy.get(name, DASH),
        })
    return rows


def tyre_life(start_tread: float, wear_lap: float, minimum_tread: float, stint_laps: int, laptime: float) -> dict:
    """Tyre life, wear over the longest stint (whole laps actually driven), dashes without wear"""
    if wear_lap <= 0:
        return {"laps": DASH, "minutes": DASH, "stints": DASH, "wearStint": DASH,
                "stintsWarning": False, "wearWarning": False}
    wear_stint = wear_lap * stint_laps
    usable_tread = max(start_tread - minimum_tread, 0)
    lifespan_laps = calc.wear_lifespan_in_laps(usable_tread, wear_lap)
    lifespan_mins = calc.wear_lifespan_in_mins(usable_tread, wear_lap, laptime)
    lifespan_stints = lifespan_laps / stint_laps if stint_laps else 0
    return {
        "laps": f"{lifespan_laps:.2f}", "minutes": f"{lifespan_mins:.2f}",
        "stints": f"{lifespan_stints:.2f}" if stint_laps else DASH, "wearStint": f"{wear_stint:.2f} %",
        "stintsWarning": 0 < lifespan_stints < 1, "wearWarning": wear_stint >= usable_tread,
    }


def problem_text(strategy: Strategy) -> str:
    return {
        "tank": tr("Tank too small for one lap plus the safety margin"),
        "start": tr("Starting fuel or energy below one lap plus the safety margin"),
        "stops": tr("Over 200 stops: tank too small for this race"),
    }.get(strategy.problem, tr("Tank too small for one lap plus the safety margin"))


def tile(key: str, title: str, value: str = DASH, detail: str = "", tip: str = "", warning: bool = False,
         visible: bool = True) -> dict:
    return {"key": key, "title": title, "value": value, "detail": detail, "tip": tip,
            "warning": warning, "visible": visible}


def key_figures(strategy: Strategy, setup: StrategyInput, symbol: str, is_gallon: bool, tyres: dict) -> list[dict]:
    """Key figure tiles: race fuel & energy, pit stops, longest stint, refill, tyres"""
    has_energy = setup.energy_per_lap > 0
    has_fuel = setup.fuel_per_lap > 0 and setup.tank_capacity > 0
    fuel = tile("fuel", tr("Race Fuel"), tip=tr("Fuel for the whole race, safety margin included"),
                visible=has_fuel or not has_energy)  # energy only car: no fuel figure
    energy = tile("energy", tr("Race Energy"), tip=tr("Energy for the whole race, safety margin included"),
                  visible=has_energy)
    pits = tile("pits", tr("Pit Stops"))
    stint = tile("stint", tr("Max Stint"), tip=tr("Longest stint, whole laps"))
    refill = tile("refill", tr("Refill per Stop"))
    tyre = tile("tyres", tr("Tyres"), f"{tyres['used']} / {tyres['maximum']}",
                trm(f"{tyres['changes']} change(s) · {tyres['time']:+.1f} s"),
                tr("Tyres used by the tyre plan / maximum allowed"), warning=tyres["stock"] > tyres["maximum"])
    tiles = [fuel, energy, pits, stint, refill, tyre]
    if not strategy.ready:
        pits["warning"] = strategy.impossible
        return tiles
    fuel_full = ceil(strategy.fuel_needed * 10) / 10 if is_gallon else ceil(strategy.fuel_needed)
    fuel.update(value=f"{fuel_full:g} {symbol}", detail=f"{strategy.fuel_needed:.2f} {symbol}")
    energy.update(value=f"{ceil(strategy.energy_needed):g} %", detail=f"{strategy.energy_needed:.2f} %")
    stops = len(strategy.stops)
    limit = {
        "energy": tr("limited by energy"), "stint": tr("limited by stint length"),
        "stops": tr("set by mandatory stops"), "fuel": tr("limited by fuel") if has_energy else "",
        "tyres": tr("limited by tyre life"),
    }.get(strategy.limit, "")
    tyre_stops = len(strategy.tyre_stops)
    detail = " · ".join(text for text in (limit, trm(f"{tyre_stops} with tyres") if tyre_stops else "") if text)
    pits.update(value=f"{stops}", detail=detail, warning=not strategy.feasible)
    stint.update(value=laps_text(strategy.max_stint), detail=f"≈ {max(strategy.stint_seconds, default=0) / 60:.0f} min")
    if not has_fuel:  # energy only car
        refill.update(value=f"{strategy.average_energy if stops else strategy.energy_load:.1f} %",
                      detail="" if stops else tr("No stop needed"),
                      title=tr("Refill per Stop") if stops else tr("Fuel to Load"))
    elif stops:
        refill.update(value=f"{strategy.average_fuel:.1f} {symbol}",
                      detail=f"{strategy.average_energy:.1f} %" if has_energy else "")
    else:  # no stop: what to load at start
        refill.update(value=f"{strategy.fuel_load:.1f} {symbol}", title=tr("Fuel to Load"),
                      detail=f"{strategy.energy_load:.1f} %" if has_energy else tr("No stop needed"))
    return tiles


def summary(strategy: Strategy, race_state: RaceState | None) -> dict:
    """Strategy line under the timeline: stints, stops, tyres, time in the pits, problem"""
    if not strategy.ready:
        impossible = strategy.impossible
        return {"text": problem_text(strategy) if impossible else "", "warning": impossible}
    if not strategy.feasible:
        return {"text": problem_text(strategy), "warning": True}
    parts = []
    if strategy.first_lap and race_state is not None:
        live = f"<b>{tr('Live Race')}</b>: {tr('rest of race from lap')} {strategy.first_lap}"
        in_car = race_state.stint_drivers[-1] if race_state.stint_drivers else ""
        parts.append(live + (f" ({escape(in_car)})" if in_car else ""))
    parts.append(trm(f"{len(strategy.stints)} stint(s), {strategy.race_laps} race laps"))
    stops = len(strategy.stops)
    pit_laps = ", ".join(str(stop.lap) for stop in strategy.stops)
    if pit_laps:
        parts.append((tr("Stop at lap") if stops == 1 else tr("Stops at laps")) + " " + pit_laps)
    tyre_stops = strategy.tyre_stops
    if tyre_stops:
        parts.append(tr("Tyres at lap") + " " + ", ".join(str(lap) for lap in tyre_stops))
    if stops:
        parts.append(trm(f"{strategy.pit_seconds:.0f} s in the pits"))
    sc_first, sc_laps = strategy.safety_car
    if sc_laps:
        parts.append(f"{tr('Safety Car')} {sc_first}-{sc_first + sc_laps - 1}")
    if strategy.driver_issues:
        parts.append(tr("driving time limits not met (Driving Time)"))
    return {"text": " · ".join(parts), "warning": bool(strategy.driver_issues)}


# Pit stop plan
def plan_header(symbol: str) -> tuple[str, ...]:
    names = {
        "stop": tr("Stop"), "lap": tr("Lap"), "window": tr("Window"), "time": tr("Time"),
        "fuel": f"{tr('Fuel')} ({symbol})", "energy": f"{tr('Energy')} (%)", "tyres": tr("Tyres"),
        "driver": tr("Driver"), "seconds": f"{tr('Stop Time')} (s)",
    }
    return tuple(names[name] for name in PLAN_COLUMNS)


PLAN_TIPS = {
    "window": "Earliest & latest lap of the stop keeping the same number of stops",
    "time": "Race time of the stop, or time of day when the start time is set",
}


def plan_rows(strategy: Strategy, has_energy: bool, time_text: Callable[[float], str],
              clock_offset: float) -> list[tuple[str, ...]]:
    """Pit stop plan rows (columns of PLAN_COLUMNS): start load (or now), then every stop"""
    if not strategy.ready:
        return []
    live = strategy.first_lap > 0
    rows: list[tuple[str, ...]] = [(
        tr("Now") if live else tr("Start"), str(strategy.first_lap), "", time_text(clock_offset),
        f"{strategy.fuel_load:.1f}", f"{strategy.energy_load:.1f}" if has_energy else DASH, "",
        str(strategy.driver_of(0)), "")]
    counts = strategy.tyre_changes
    for index, stop in enumerate(strategy.stops):
        tyres = (f"{tr('Change')} ({counts[index]})" if index < len(counts) else tr("Change")) if stop.tyres else ""
        window = f"{strategy.windows[index][0]}-{strategy.windows[index][1]}" if index < len(strategy.windows) else ""
        mark = {"sc": " SC", "rain": f" {tr('Wet')}", "dry": f" {tr('Dry')}"}.get(
            stop.reason, " SC" if stop.safety_car else "")
        number = str(strategy.stops_done + index + 1) + mark
        rows.append((number, str(stop.lap), window, time_text(stop.clock), f"{stop.fuel:.1f}",
                     f"{stop.energy:.1f}" if has_energy else DASH, tyres, str(stop.driver), f"{stop.seconds:.1f}"))
    return rows


def plan_hidden(strategy: Strategy, has_energy: bool, drivers: int) -> list[str]:
    """Plan columns left out: energy without energy, driver for one driver, window without windows"""
    hidden = []
    if not has_energy:
        hidden.append("energy")
    if not strategy.windows:
        hidden.append("window")
    if drivers < 2:
        hidden.append("driver")
    return hidden


def plan_title(strategy: Strategy) -> str:
    return f"{tr('Pit Stop Plan')} · {trm(f'{len(strategy.stints)} stint(s), {strategy.race_laps} race laps')}"


def plan_footer(strategy: Strategy) -> str:
    tyre_seconds = sum(stop.tyre_seconds for stop in strategy.stops)
    return trm(f"{strategy.pit_seconds:.0f} s in the pits") + (
        f" · {tr('Tyres')} {tyre_seconds:.1f} s" if tyre_seconds else "")


def plan_text(strategy: Strategy, symbol: str, has_energy: bool, drivers: int,
              time_text: Callable[[float], str]) -> str:
    """Pit stop plan as plain text (clipboard)"""
    lines = [
        plan_title(strategy),
        f"{tr('Now') if strategy.first_lap else tr('Start')}: {strategy.fuel_load:.1f} {symbol}"
        + (f" · {strategy.energy_load:.1f} %" if has_energy else ""),
    ]
    counts = strategy.tyre_changes
    for index, stop in enumerate(strategy.stops):
        line = (f"{tr('Stop')} {strategy.stops_done + index + 1} · {tr('Lap')} {stop.lap}"
                f" · {time_text(stop.clock)} · +{stop.fuel:.1f} {symbol}")
        if has_energy:
            line += f" · +{stop.energy:.1f} %"
        if stop.tyres:
            line += f" · {tr('Tyres')}" + (f" ({counts[index]})" if index < len(counts) else "")
        if drivers > 1:
            line += f" · {tr('Driver')} {stop.driver}"
        line += f" · {stop.seconds:.1f} s"
        if index < len(strategy.windows):
            line += f" · {tr('Window')} {strategy.windows[index][0]}-{strategy.windows[index][1]}"
        lines.append(line)
    lines.append(plan_footer(strategy))
    return "\n".join(lines)


# Strategy timeline
def timeline(strategy: Strategy, drivers: int, symbol: str, time_text: Callable[[float], str]) -> dict:
    """Race laps left to right (fractions of the plan), one block per stint (driver color when
    drivers take turns), stops with their details, safety car & rain bands"""
    if not strategy.ready:
        return {"ready": False, "first": 0, "last": 0, "stints": [], "stops": [], "bands": []}
    total = strategy.race_laps
    first_lap = strategy.first_lap

    def position(lap: float) -> float:
        return min(max((lap - first_lap) / total, 0.0), 1.0)

    stints = []
    bounds = strategy.stint_bounds()
    for index, (first, last) in enumerate(bounds):
        seconds = strategy.stint_seconds[index] if index < len(strategy.stint_seconds) else 0.0
        driver = strategy.driver_of(index) if drivers > 1 else 0
        tip = [f"<b>{tr('Stint')} {strategy.stops_done + index + 1}</b> · {tr('Laps')} {first}-{last}",
               f"{laps_text(last - first + 1)} · {seconds / 60:.1f} min"]
        if driver:
            tip.append(f"{tr('Driver')} {driver}")
        stints.append({
            "start": position(first - 1), "end": position(last), "laps": last - first + 1,
            "color": DRIVER_COLORS[(driver - 1) % len(DRIVER_COLORS)] if driver else "", "tip": "<br>".join(tip),
        })
    stops = []
    for index, stop in enumerate(strategy.stops):
        tip = [f"<b>{tr('Stop')} {strategy.stops_done + index + 1}</b> · {tr('Lap')} {stop.lap}",
               f"{tr('Time')} {time_text(stop.clock)}",
               f"+{stop.fuel:.1f} {symbol}" + (f" · +{stop.energy:.1f} %" if stop.energy else "")]
        if index < len(strategy.windows):
            tip.append(f"{tr('Pit Window')} {strategy.windows[index][0]}-{strategy.windows[index][1]}")
        if stop.tyres:
            tip.append(tr("Tyres"))
        if drivers > 1:
            tip.append(f"{tr('Driver')} {stop.driver}")
        if stop.safety_car:
            tip.append(tr("Under safety car"))
        tip.append(f"{stop.seconds:.1f} s")
        stops.append({"pos": position(stop.lap), "lap": stop.lap, "tyres": stop.tyres, "tip": "<br>".join(tip)})
    bands = []
    sc_first, sc_laps = strategy.safety_car
    for band_first, band_last, color, name in (
        (sc_first, sc_first + sc_laps - 1, SAFETY_CAR_COLOR, tr("Safety Car")) if sc_laps else (0, -1, "", ""),
        (*strategy.rain, RAIN_COLOR, tr("Rain")) if strategy.rain[0] else (0, -1, "", ""),
    ):
        if band_last < band_first or band_first > strategy.last_lap or band_last <= first_lap:
            continue
        bands.append({"start": position(max(band_first - 1, first_lap)), "end": position(min(band_last, strategy.last_lap)),
                      "color": color, "name": name, "tip": f"<b>{name}</b> · {tr('Laps')} {band_first}-{band_last}"})
    return {"ready": True, "first": first_lap, "last": strategy.last_lap, "stints": stints, "stops": stops,
            "bands": bands}


def fuel_levels(strategy: Strategy, setup: StrategyInput, has_fuel: bool) -> list[list[float]]:
    """Tank level over the plan: (position, fraction of tank) at start, each stop (before & after),
    finish. Empty without fuel or plan."""
    capacity = setup.tank_capacity
    if not strategy.ready or not strategy.feasible or not has_fuel or capacity <= 0:
        return []
    total = strategy.race_laps
    first_lap = strategy.first_lap
    points = [[0.0, min(strategy.fuel_load / capacity, 1.0)]]
    tank = strategy.fuel_load
    for stop in strategy.stops:
        position = min(max((stop.lap - first_lap) / total, 0.0), 1.0)
        before = max(stop.fuel_after - stop.fuel, 0.0) if stop.fuel_after else max(tank - setup.fuel_per_lap, 0.0)
        points.append([position, min(before / capacity, 1.0)])
        tank = stop.fuel_after or before + stop.fuel
        points.append([position, min(tank / capacity, 1.0)])
    last = strategy.stints[-1] if strategy.stints else 0
    end = max(tank - last * setup.fuel_per_lap, 0.0)
    points.append([1.0, min(end / capacity, 1.0)])
    return points


# Scenarios
def saving_texts(strategy: Strategy, plan_setup: StrategyInput, setup: StrategyInput, target: SavingTarget | None,
                 aimed: tuple[StrategyInput, Strategy] | None, symbol: str) -> dict:
    """Saving target: consumption for one stop less (lap time lost & race time it makes), and for
    laps per stint aimed at"""
    has_energy = setup.energy_per_lap > 0

    def consumption_text(fuel: float, energy: float) -> str:
        parts = []
        if setup.fuel_per_lap > 0:
            parts.append(trm(f"{fuel:.3f} {symbol} per lap ({fuel - setup.fuel_per_lap:+.3f})"))
        if has_energy:
            parts.append(trm(f"{energy:.3f} % per lap ({energy - setup.energy_per_lap:+.3f})"))
        return " · ".join(parts)

    if target is None:
        one_less = tr("No stop to save") if strategy.ready else ""
    else:
        saving = target.strategy
        one_less = (trm(f"One stop less: {target.laps} laps per stint, {len(saving.stops)} stop(s)") + "<br>"
                    + consumption_text(target.fuel, target.energy))
        if setup.saving_cost > 0:
            cost = saving.saving_seconds - plan_setup.saving_seconds
            if saving.race_laps != strategy.race_laps:
                gain = f"{saving.race_laps - strategy.race_laps:+d} {tr('laps')}"
            else:
                gain = f"{saving.race_seconds - strategy.race_seconds:+.1f} s"
            worth = race_result(saving) < race_result(strategy)
            one_less += (f"<br>{tr('Saving Cost')}: +{cost:.2f} s/{tr('lap')} · {tr('Race')} {gain} · "
                         + (tr("worth it") if worth else tr("not worth it")))
    aimed_text = ""
    if aimed is not None:
        aimed_setup, aimed_strategy = aimed
        aimed_text = (consumption_text(aimed_setup.fuel_per_lap, aimed_setup.energy_per_lap) + "<br>"
                      + trm(f"{len(aimed_strategy.stops)} stop(s) with this target"))
    return {
        "oneLess": one_less, "target": aimed_text,
        "oneLessFuel": f"{target.fuel:.3f}" if target and strategy.ready else DASH,
        "oneLessEnergy": f"{target.energy:.3f}" if target and has_energy else DASH,
    }


def comparison(variants: Sequence[Variant], has_energy: bool, symbol: str) -> dict:
    """Strategies side by side: stops, saving needed, lap time lost, race result (best in bold)"""
    columns = [tr("Pit Stops"), f"{tr('Fuel')} ({symbol})", f"{tr('Energy')} (%)", tr("Saving Cost"),
               tr("Pit Time"), tr("Laps"), tr("Race Time"), tr("Gap")]
    if len(variants) < 2:
        return {"visible": False, "columns": columns, "rows": [], "best": -1, "hidden": []}
    best = min(variants, key=lambda variant: race_result(variant.strategy))
    rows = []
    for variant in variants:
        strategy = variant.strategy
        if strategy.race_laps != best.strategy.race_laps:
            gap = f"{strategy.race_laps - best.strategy.race_laps:+d} {tr('laps')}"
        else:
            gap = f"{strategy.race_seconds - best.strategy.race_seconds:+.1f} s"
        name = f"{variant.stops}" + (f" ({tr('now')})" if variant.current else "")
        rows.append([
            name, f"{variant.fuel:.3f}", f"{variant.energy:.3f}" if has_energy else DASH,
            f"{variant.lap_cost:+.2f} s" if variant.lap_cost else DASH,
            f"{strategy.pit_seconds:.0f} s", str(strategy.race_laps),
            duration_text(strategy.race_seconds), gap if variant is not best else DASH,
        ])
    return {"visible": True, "columns": columns, "rows": rows, "best": list(variants).index(best),
            "hidden": [] if has_energy else [2]}


def scenario_text(kind: str, strategy: Strategy, without: Strategy | None) -> str:
    """Plan with safety car or rain against plan without"""
    if without is None or not strategy.ready or not without.ready:
        return ""
    stops = len(strategy.stops) - len(without.stops)
    laps = strategy.race_laps - without.race_laps
    if kind == "rain":
        if not strategy.rain[0]:
            return tr("Rain after the finish: no effect")
        parts = [f"{tr('Without rain')}: {len(without.stops)} {tr('stop(s)')}, {without.race_laps} {tr('laps')}",
                 f"{tr('With rain')}: {stops:+d} {tr('stop(s)')}, {laps:+d} {tr('laps')}"]
        for stop in strategy.stops:
            if stop.reason in ("rain", "dry"):
                name = tr("Wet tyres at lap") if stop.reason == "rain" else tr("Slicks at lap")
                parts.append(f"{name} {stop.lap} ({stop.seconds:.1f} s)")
        return "<br>".join(parts)
    parts = [f"{tr('Without safety car')}: {len(without.stops)} {tr('stop(s)')}, {without.race_laps} {tr('laps')}",
             f"{tr('With safety car')}: {stops:+d} {tr('stop(s)')}, {laps:+d} {tr('laps')}"]
    sc_stop = next((stop for stop in strategy.stops if stop.safety_car), None)
    if sc_stop is not None:
        parts.append(f"{tr('Stop under safety car at lap')} {sc_stop.lap} ({sc_stop.seconds:.1f} s)")
    if not strategy.safety_car[1]:
        parts.append(tr("Safety car after the finish: no effect"))
    return "<br>".join(parts)


def driver_times(strategy: Strategy, drivers: int, limits: Sequence[tuple[float, float, float]]) -> dict:
    """Driving time of each driver: stints, time, limits not met"""
    columns = [tr("Driver"), tr("Stints"), tr("Time"), tr("Limits")]
    if drivers < 2 or not strategy.ready:
        return {"visible": False, "columns": columns, "rows": [], "warning": False}
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
        rows.append([str(index + 1), str(stints), duration_text(seconds), limit or DASH])
    return {"visible": True, "columns": columns, "rows": rows, "warning": bool(strategy.driver_issues)}


def plan_against_race(stints: Sequence[StintDataSet], strategy: Strategy, setup_fuel: float, setup_energy: float,
                      laptime: float, unit_fuel: Callable[[float], float], has_energy: bool, symbol: str,
                      drivers: Sequence[str] = ()) -> dict:
    """Stints done (oldest first) against stints planned before the race, driver of each stint of
    the race (drivers, "" unknown) when known"""
    columns = [tr("Stint"), tr("Driver"), tr("Laps"), tr("Lap Time"), f"{tr('Fuel')} ({symbol}/{tr('lap')})",
               f"{tr('Energy')} (%/{tr('lap')})", f"{tr('Tyre Wear')} (%)"]
    done = [stint for stint in stints if stint.totalLaps > 0]
    if not done:
        return {"visible": False, "columns": columns, "rows": [], "hidden": []}
    rows = []
    for index, stint in enumerate(done):
        laps = stint.totalLaps
        planned = strategy.stints[index] if index < len(strategy.stints) else 0
        planned_time = (strategy.stint_seconds[index] / planned) if planned else laptime
        fuel = unit_fuel(stint.totalFuel) / laps
        energy = stint.totalEnergy / laps
        rows.append([
            str(index + 1), (drivers[index] if index < len(drivers) else "") or DASH, f"{laps} / {planned or DASH}",
            f"{stint.totalTime / laps:.2f} / {planned_time:.2f}", f"{fuel:.3f} / {setup_fuel:.3f}",
            f"{energy:.3f} / {setup_energy:.3f}" if has_energy else DASH, f"{stint.totalTyreWear:.1f}",
        ])
    hidden = [] if any(drivers[:len(done)]) else [1]
    if not has_energy:
        hidden.append(5)
    return {"visible": True, "columns": columns, "rows": rows, "hidden": hidden}


def class_rivals(rivals: Sequence[Rival], stint_laps: int) -> dict:
    """Cars of the player class by place, next stop from your stint length (same class, close consumption)"""
    columns = [tr("Place"), tr("Driver"), tr("Laps"), tr("Pit Stops"), tr("Since Stop"), tr("Next Stop")]
    if len(rivals) < 2:
        return {"visible": False, "columns": columns, "rows": [], "player": -1}
    rows = []
    player_row = -1
    for row, rival in enumerate(rivals):
        if rival.player:
            player_row = row
        since = rival.laps - rival.last_stop_lap if rival.last_stop_lap else rival.laps
        known = bool(rival.last_stop_lap) or rival.stops == 0
        next_stop = rival.laps - since + stint_laps if stint_laps else 0
        rows.append([
            str(rival.place), rival.driver, str(rival.laps),
            str(rival.stops) + (f" ({tr('pit')})" if rival.in_pits else ""),
            str(since) if known else f"~{since}",
            (str(next_stop) if known else f"~{next_stop}") if stint_laps else DASH,
        ])
    return {"visible": True, "columns": columns, "rows": rows, "player": player_row}


def stint_laps_of(strategy: Strategy, full_tank: float) -> int:
    """Longest stint planned, else laps of a full tank"""
    return strategy.max_stint if strategy.ready else floor(full_tank)
