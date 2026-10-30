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
Relative module
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache
from itertools import chain
from operator import itemgetter
from time import monotonic
from typing import NamedTuple

from .. import realtime_state
from ..api_control import api
from ..calculation import asym_max
from ..const_common import MAX_SECONDS, MAX_VEHICLES
from ..module_info import ScoringSnapshot, minfo
from ._base import WAIT_STATE_CHANGE, DataModule, vehicles_updates

REF_PLACES = tuple(range(1, MAX_VEHICLES + 1))
TEMP_RELATIVE_AHEAD = [(0.0, -1)] * MAX_VEHICLES
TEMP_RELATIVE_BEHIND = [(0.0, -1)] * MAX_VEHICLES
TEMP_CLASSES = [("", -1, -1, -1.0, -1.0)] * MAX_VEHICLES
TEMP_DRAW_ORDER = list(range(MAX_VEHICLES))
RELATIVE_DELTA_INTERVAL = 1.0  # seconds between relative delta updates


class Realtime(DataModule):
    """Relative & standings data"""

    WAKE_ON_VEHICLES = True  # follows scoring passes of vehicles module while it runs (its snapshot read once)
    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        _event_wait = self.wait_update
        reset = False
        update_interval = self.idle_interval

        output = minfo.relative
        last_version_update = None
        slot_ids = [-1] * MAX_VEHICLES  # vehicle slot id per index, of relative delta data
        last_stamp: tuple = ()  # scoring data stamp of last update
        last_delta_update = 0.0  # time of last relative delta update
        last_plr_slot = -1  # slot id of car gaps are measured from, of relative delta data

        while not _event_wait(update_interval):
            if not realtime_state.paused:

                # Full rate only while overlays are shown (their only consumer), else idle interval
                update_interval = self.active_interval if realtime_state.shown else self.idle_interval

                if not reset:
                    reset = True
                    # New session or reload: relative delta of vehicles from scratch
                    reset_relative_delta(
                        slot_ids, output.relativeDeltaAhead, output.relativeDeltaBehind)
                    last_stamp = ()  # never skip first tick

                # Check setting
                if last_version_update != self.cfg.version_update:
                    last_version_update = self.cfg.version_update
                    # Read again at every setting change: preset loaded or options applied may hand new dicts
                    show_in_garage = self.cfg.user.setting["relative"]["show_vehicle_in_garage"]
                    limits = standings_limits(self.cfg.user.setting["standings"])

                # Relative delta updated at 1 second interval (same time with or without new data)
                now = monotonic()
                update_relative_delta = now - last_delta_update >= RELATIVE_DELTA_INTERVAL

                # Skip while inputs not updated since last tick: every vehicle input is scoring data
                # (updated 5 times per second, along with session elapsed time), read by vehicles module
                # first while it runs (its last scoring pass followed: this module is woken once published)
                read = api.read
                veh_total = max(read.vehicle.total_vehicles(), 1)
                plr_index = read.vehicle.player_index()
                snapshot = scoring_snapshot(minfo.vehicles.scoringSnapshot, veh_total, read.session.elapsed())
                stamp = (
                    read, read.session.elapsed() if snapshot is None else snapshot.scoringTime, veh_total,
                    plr_index, realtime_state.resets, last_version_update,
                )
                if last_stamp == stamp and not update_relative_delta:
                    continue
                last_stamp = stamp
                if update_relative_delta:
                    last_delta_update = now
                # Car identity, not index (index shifts when a car with lower index joins or leaves)
                plr_slot = read.vehicle.slot_id(plr_index) if 0 <= plr_index < veh_total else -1
                if last_plr_slot != plr_slot:
                    last_plr_slot = plr_slot
                    # Other car followed (spectating, Director): gap changes of every car from scratch
                    reset_relative_delta(
                        slot_ids, output.relativeDeltaAhead, output.relativeDeltaBehind)

                # Base info
                plr_place = read.vehicle.place()

                # Get vehicles info (scoring data of vehicles module snapshot if any, else read from game)
                (relative_ahead, relative_behind, classes_list, draw_order_list, is_multi_class,
                 ) = get_vehicles_info(
                    veh_total, plr_index, show_in_garage, update_relative_delta,
                    output.relativeDeltaAhead, output.relativeDeltaBehind, slot_ids,
                    None if snapshot is None else snapshot.rows)

                # Update vehicle class position info
                plr_class_name, plr_class_place = update_position_in_class(classes_list, plr_index)

                # Output data
                output.relativeAhead = relative_ahead
                output.relativeBehind = relative_behind
                output.standings = standings_index(
                    limits, classes_list, plr_place, plr_class_name, plr_class_place, is_multi_class)
                output.drawOrder = draw_order_list

            else:
                if reset:
                    reset = False
                    update_interval = WAIT_STATE_CHANGE  # game paused: idle until activity changes
                    create_reference_place.cache_clear()


def scoring_snapshot(
    snapshot: ScoringSnapshot | None, veh_total: int, session_elapsed: float,
) -> ScoringSnapshot | None:
    """Scoring data of vehicles module to use for this update, None to read game scoring instead

    While vehicles module runs (vehicles_updates.active), its last scoring pass is followed: this module is
    woken once it is published, so the snapshot is the scoring data to use even when the game has a newer
    sample already (read by vehicles module next, this module woken again). Else only a snapshot of the
    current game scoring sample (vehicles module just stopped). Never a snapshot of another car count.
    """
    if snapshot is None or len(snapshot.rows) != veh_total:
        return None
    if vehicles_updates.active or snapshot.scoringTime == session_elapsed:
        return snapshot
    return None


def reset_relative_delta(
    slot_ids: list[int], relative_delta_ahead: tuple, relative_delta_behind: tuple,
):
    """Reset relative delta data of all vehicles"""
    slot_ids[:] = [-1] * len(slot_ids)
    for delta_ahead in relative_delta_ahead:
        delta_ahead.reset()
    for delta_behind in relative_delta_behind:
        delta_behind.reset()


def get_vehicles_info(
    veh_total: int, plr_index: int, show_in_garage: bool, update_relative_delta: bool,
    relative_delta_ahead: tuple, relative_delta_behind: tuple, slot_ids: list[int] | None = None,
    scoring_rows: tuple | None = None,
):
    """Get vehicles info: relative time gap, classes, places, laptime

    Args:
        slot_ids: vehicle slot id per index of relative delta data, reset on other vehicle in index.
        scoring_rows: scoring data of every car of this scoring sample read by vehicles module
            (ScoringSnapshot.rows, same values), None: read from game.
    """
    laptime_est = api.read.timing.estimated_laptime()
    plr_time = api.read.timing.estimated_time_into()
    last_class_name = None
    classes_count = 0
    recorded_index = 0
    leader_index = 0
    pitter_index = 0
    draw_order = TEMP_DRAW_ORDER[:veh_total]

    rows = scoring_rows
    for index in range(veh_total):
        if rows is None:
            in_garage = api.read.vehicle.in_garage(index)
            in_pitlane = api.read.vehicle.in_pits(index) or in_garage
        else:
            in_garage, in_pitlane, opt_time, class_name, place_overall, laptime_best, laptime_last = rows[index]

        # Update relative time gap list
        if index != plr_index and laptime_est and (show_in_garage or not in_garage):
            if rows is None:
                opt_time = api.read.timing.estimated_time_into(index)
            diff_time = opt_time - plr_time
            diff_time_ahead = diff_time_behind = diff_time - diff_time // laptime_est * laptime_est
            if diff_time_ahead < 0:
                diff_time_ahead += laptime_est
            if diff_time_behind > 0:
                diff_time_behind -= laptime_est

            TEMP_RELATIVE_AHEAD[recorded_index] = (
                diff_time_ahead,  # 0 relative time gap
                index,  # 1 player index
            )
            TEMP_RELATIVE_BEHIND[recorded_index] = (
                diff_time_behind,  # 0 relative time gap
                index,  # 1 player index
            )
            recorded_index += 1

            if update_relative_delta:  # update at 1 sec interval
                # Other vehicle took index (joined, left), or all reset (new session, other car followed):
                # delta of previous one not kept, first gap is the reference of next changes (not a change from 0)
                if slot_ids is not None:
                    slot_id = api.read.vehicle.slot_id(index)
                    if slot_ids[index] != slot_id:
                        slot_ids[index] = slot_id
                        relative_delta_ahead[index].reset()
                        relative_delta_behind[index].reset()
                        relative_delta_ahead[index].last = diff_time_ahead
                        relative_delta_behind[index].last = -diff_time_behind
                relative_delta_ahead[index].update(diff_time_ahead)
                relative_delta_behind[index].update(-diff_time_behind)

        # Update classes list
        if rows is None:
            class_name = api.read.vehicle.class_name(index)
            place_overall = api.read.vehicle.place(index)
            laptime_best = api.read.timing.best_laptime(index)
            laptime_last = api.read.timing.last_laptime(index)

        if laptime_last > 0 and not in_pitlane:
            laptime_personal_last = laptime_last
        else:
            laptime_personal_last = MAX_SECONDS

        if laptime_best > 0:
            laptime_personal_best = laptime_best
        else:
            laptime_personal_best = MAX_SECONDS

        TEMP_CLASSES[index] = (
            class_name,  # 0 vehicle class name
            place_overall,  # 1 overall position/place
            index,  # 2 player index
            laptime_personal_best,  # 3 best lap time
            laptime_personal_last,  # 4 last lap time (for fastest last lap check)
        )

        # Update draw order list
        if place_overall == 1:  # save leader index
            leader_index = index
        elif in_pitlane:  # swap opponent in pit/garage to start
            draw_order[index], draw_order[pitter_index] = draw_order[pitter_index], draw_order[index]
            pitter_index += 1

        # Check is multi classes
        if classes_count < 2 and last_class_name != class_name:
            last_class_name = class_name
            classes_count += 1

    # Finalize draw order list
    if 0 <= leader_index < veh_total and leader_index != draw_order[-1]:  # move leader to end
        leader_pos = draw_order.index(leader_index)
        draw_order[leader_pos], draw_order[-1] = draw_order[-1], draw_order[leader_pos]
    if 0 <= plr_index < veh_total and plr_index != leader_index:   # move player to 2nd end if not leader
        player_pos = draw_order.index(plr_index)
        draw_order[player_pos], draw_order[-2] = draw_order[-2], draw_order[player_pos]

    # Sort output in-place
    relative_ahead = TEMP_RELATIVE_AHEAD[:recorded_index]
    relative_ahead.sort(reverse=True)  # by reversed time gap

    relative_behind = TEMP_RELATIVE_BEHIND[:recorded_index]
    relative_behind.sort(reverse=True)  # by reversed time gap

    new_classes = TEMP_CLASSES[:veh_total]
    new_classes.sort()  # by vehicle class

    return (
        relative_ahead,
        relative_behind,
        new_classes,  # classes_list
        draw_order,
        classes_count > 1,  # is_multi_class
    )


def update_position_in_class(sorted_veh_class: list, plr_index: int, veh_data: tuple | None = None):
    """Update vehicle position in class

    Args:
        veh_data: vehicles data set updated (default: module info, simulated race has its own).
    """
    last_class_name = None
    place_in_class = 0
    opt_index_ahead = -1
    opt_index_leader = -1
    laptime_class_best = MAX_SECONDS
    last_fastest_laptime = MAX_SECONDS
    last_fastest_index = -1
    plr_class_name = ""
    plr_class_place = 0
    if veh_data is None:
        veh_data = minfo.vehicles.dataSet
    class_best = class_best_laptimes(sorted_veh_class)

    for class_name, _, opt_index, _, laptime_last in sorted_veh_class:
        output_data = veh_data[opt_index]

        if last_class_name == class_name:
            place_in_class += 1
            veh_data[opt_index_ahead].classBehindIndex = opt_index
        else:
            last_class_name = class_name  # reset class name
            place_in_class = 1  # reset position counter
            opt_index_ahead = -1  # no opponent ahead of class leader
            opt_index_leader = opt_index
            laptime_class_best = class_best[class_name]  # fastest of class, not of class leader
            last_fastest_laptime = MAX_SECONDS  # reset last fastest
            if last_fastest_index != -1:  # mark fastest last lap
                veh_data[last_fastest_index].isClassFastestLastLap = True
                last_fastest_index = -1  # reset last fastest index

        if opt_index == plr_index:
            plr_class_name = class_name
            plr_class_place = place_in_class

        if last_fastest_laptime > laptime_last:
            last_fastest_laptime = laptime_last
            last_fastest_index = opt_index

        output_data.classAheadIndex = opt_index_ahead
        output_data.classBehindIndex = -1
        output_data.classLeaderIndex = opt_index_leader
        output_data.positionInClass = place_in_class
        output_data.classBestLapTime = laptime_class_best
        output_data.isClassFastestLastLap = False
        opt_index_ahead = opt_index  # store opponent index for next

    if last_fastest_index != -1:  # mark for last class
        veh_data[last_fastest_index].isClassFastestLastLap = True

    return plr_class_name, plr_class_place


def standings_index_from_all_classes(
    min_top_veh: int, class_pos_list: list, plr_class_name: str, plr_class_place: int,
    veh_limit_other: int, veh_limit_player: int, class_rank: Mapping[str, int] | None = None):
    """Generate class standings index list from all classes, in class order (class_rank, see class_order_rank),
    classes not ranked after, fastest class first"""
    rank = class_rank or {}
    class_collection = sorted(split_class_list(class_pos_list), key=lambda collection: (
        rank.get(class_key(collection[0][0]), len(rank)), sort_class_collection(collection)))
    for class_list in class_collection:
        if plr_class_name == class_list[0][0]:  # match class name
            veh_limit = veh_limit_player
            plr_place = plr_class_place  # 1 position in class
        else:
            veh_limit = veh_limit_other
            plr_place = 0
        if veh_limit <= 0:  # class hidden: no empty group (gap without vehicles)
            continue
        yield calc_standings_index(min_top_veh, veh_limit, plr_place, class_list)


def standings_index_from_same_class(
    min_top_veh: int, class_pos_list: list, plr_class_name: str, plr_class_place: int, veh_limit_player: int
) -> list[int]:
    """Generate class standings index list from same class only"""
    class_list = [class_data for class_data in class_pos_list if plr_class_name == class_data[0]]
    if not class_list:
        return [-1]
    return calc_standings_index(min_top_veh, veh_limit_player, plr_class_place, class_list)


def calc_standings_index(
    min_top_veh: int, veh_limit: int, plr_place: int, class_index_list: list
) -> list[int]:
    """Calculate vehicle standings index list"""
    veh_total = len(class_index_list)
    ref_place_list = create_reference_place(min_top_veh, veh_total, plr_place, veh_limit)
    # Create final standing index list
    return list(standings_index_from_place_reference(ref_place_list, class_index_list, veh_total))


@lru_cache(maxsize=20)
def create_reference_place(
    min_top_veh: int, veh_total: int, plr_place: int, veh_limit: int
) -> tuple[int, ...]:
    """Create reference place list"""
    if veh_total <= veh_limit:
        return REF_PLACES[:veh_total]
    if plr_place <= min_top_veh:
        return REF_PLACES[:veh_limit]
    # Find nearby slice range relative to player
    max_cut_range = veh_limit - min_top_veh
    # Number of rear slots, should be equal or less than front slots (exclude player slot)
    rear_cut_count = (max_cut_range - 1) // 2  # exclude player slot, then floor divide
    front_cut_count = max_cut_range - rear_cut_count  # include player slot
    # Find front slice limit
    front_cut_raw = plr_place - front_cut_count
    if front_cut_raw < min_top_veh:
        front_cut_raw = min_top_veh
    # Find rear slice limit
    rear_cut_max = front_cut_raw + max_cut_range
    if rear_cut_max > veh_total:
        rear_cut_max = veh_total
    front_cut_max = rear_cut_max - max_cut_range
    return REF_PLACES[:min_top_veh] + REF_PLACES[front_cut_max:rear_cut_max]


def standings_index_from_place_reference(
    ref_place_list: tuple, class_index_list: list, veh_total: int
):
    """Match place from reference list to generate standings player index list (-1 where places are skipped:
    top places, then the places around the player, apart)"""
    last_ref = 0
    for ref_index in ref_place_list:
        if 0 < ref_index <= veh_total:  # prevent out of range
            if ref_index > last_ref + 1:
                yield -1  # places left out between: shown apart
            last_ref = ref_index
            yield class_index_list[ref_index - 1][2]  # 2 - player index
        else:
            break
    yield -1  # append an empty index as gap between classes


def split_class_list(class_list: list):
    """Split class list into class collection"""
    class_name = class_list[0][0]
    index_start = 0
    index_end = 0
    for vehicle in class_list:
        if vehicle[0] == class_name:
            index_end +=1
        elif vehicle[0] != class_name:
            class_name = vehicle[0]
            yield class_list[index_start:index_end]
            index_start = index_end
            index_end +=1
    # Final split
    yield class_list[index_start:index_end]


def min_top_vehicles_in_class(min_top_veh: int) -> int:
    """Minimum number of top vehicles in class list

    min_top_veh: value range limited in 1 to 5
    """
    return int(asym_max(min_top_veh, 1, 5))


def max_vehicles_in_class(max_cls_veh: int, min_top_veh: int, min_add_veh: int = 0) -> int:
    """Maximum number of vehicles in class list

    max_cls_veh: maximum vehicles per class limit
    min_top_veh: minimum top vehicles limit
    min_add_veh: minimum addition vehicles limit (for class has local player)
    """
    return max(int(max_cls_veh), min_top_veh + min_add_veh)


def other_class_vehicles(max_cls_veh: int) -> int:
    """Number of top vehicles shown of each class player is not in (split mode), 0 = class hidden

    Not raised to minimum top vehicles (player class only): any number of cars of other classes can be shown.
    """
    return max(int(max_cls_veh), 0)


_class_key_separators = re.compile(r"[\s_\-]+")


@lru_cache(maxsize=64)  # few classes, looked up per class at every standings update
def class_key(class_name: str) -> str:
    """Class name compared in class order: case, spaces, underscores & hyphens left out ("LMP2 ELMS" = "LMP2_ELMS")"""
    return _class_key_separators.sub("", class_name).casefold()


def class_order_rank(class_order: str) -> dict[str, int]:
    """Place of each class of class order option (class names separated by commas, first shown first)"""
    rank: dict[str, int] = {}
    for name in str(class_order).split(","):
        key = class_key(name)
        if key and key not in rank:
            rank[key] = len(rank)
    return rank


def sort_class_collection(collection: list) -> float:
    """Sort class collection by class best laptime (fastest of class, not of class leader)"""
    return min(vehicle[3] for vehicle in collection)  # 3 best laptime


def class_best_laptimes(sorted_veh_class: list) -> dict[str, float]:
    """Best laptime of each class (fastest of class, MAX_SECONDS if none)"""
    class_best: dict[str, float] = {}
    for class_name, _, _, laptime_best, _ in sorted_veh_class:
        class_best[class_name] = min(laptime_best, class_best.get(class_name, MAX_SECONDS))
    return class_best


class StandingsLimits(NamedTuple):
    """Standings options read by module (see standings_limits)"""

    is_exclusive_mode: bool
    is_split_mode: bool
    min_top_veh: int
    veh_limit_exclusive: int
    veh_limit_combined: int
    veh_limit_other: int
    veh_limit_player: int
    class_rank: dict[str, int]


def standings_limits(setting_standings: Mapping) -> StandingsLimits:
    """Display mode & vehicle limits of standings options"""
    min_top_veh = min_top_vehicles_in_class(setting_standings["minimum_top_vehicles"])
    return StandingsLimits(
        is_exclusive_mode=setting_standings["enable_single_class_exclusive_mode"],
        is_split_mode=setting_standings["enable_multi_class_split_mode"],
        min_top_veh=min_top_veh,
        veh_limit_exclusive=max_vehicles_in_class(
            setting_standings["maximum_vehicles_exclusive_mode"], min_top_veh, 2),
        veh_limit_combined=max_vehicles_in_class(
            setting_standings["maximum_vehicles_combined_mode"], min_top_veh, 2),
        veh_limit_other=other_class_vehicles(setting_standings["maximum_vehicles_per_split_others"]),
        veh_limit_player=max_vehicles_in_class(
            setting_standings["maximum_vehicles_per_split_player"], min_top_veh, 2),
        class_rank=class_order_rank(setting_standings.get("class_order", "")),
    )


def standings_index(
    limits: StandingsLimits, classes_list: list, plr_place: int, plr_class_name: str, plr_class_place: int,
    is_multi_class: bool,
) -> list[int]:
    """Standings index list of display mode (-1: gap between classes), classes_list sorted by class (sorted by
    overall position in place in mixed class mode)"""
    if limits.is_exclusive_mode:  # single class exclusive list
        return standings_index_from_same_class(
            limits.min_top_veh, classes_list, plr_class_name, plr_class_place, limits.veh_limit_exclusive)
    if limits.is_split_mode and is_multi_class:  # multi-class split list
        return list(chain(*standings_index_from_all_classes(
            limits.min_top_veh, classes_list, plr_class_name, plr_class_place,
            limits.veh_limit_other, limits.veh_limit_player, limits.class_rank))) or [-1]
    # Mixed class list
    classes_list.sort(key=itemgetter(1))  # sort by overall position
    return calc_standings_index(limits.min_top_veh, limits.veh_limit_combined, plr_place, classes_list)
