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
Vehicles module
"""

from __future__ import annotations

from time import monotonic

from .. import calculation as calc
from .. import realtime_state
from ..api_control import api
from ..const_common import FLOAT_INF, MAX_METERS, MAX_SECONDS
from ..module_info import (
    DeltaFuelHistory,
    DeltaLapTimeHistory,
    LapSectors,
    LicoTimer,
    PitTimer,
    ScoringSnapshot,
    SpeedTrap,
    VehicleDataSet,
    VehiclesInfo,
    minfo,
)
from ..userfile.brands import select_brand_name
from ._base import WAIT_STATE_CHANGE, DataModule, data_stamp

# Slot id per vehicle index: game compacts vehicle array when a car leaves (multiplayer),
# so another car may take the index of a previous one
_index_slot_ids: dict[int, int] = {}
TIMING_POINTS = 100  # timing points per lap: time behind a car = time since it passed the same point
_point_times: dict[int, PointTimes] = {}  # vehicle index: session time at each timing point passed
# Cars within this straight line distance (meters) of player: telemetry (position, lift & coast) read at full
# rate (radar, spotter, navigation), farther ones every FAR_INTERVAL (track map) or scoring update
NEAR_RANGE = 300.0
FAR_INTERVAL = 0.05  # seconds of game time between telemetry updates of far cars (20 per second)
LOW_PRIORITY_MAX_WAIT = 1.0  # seconds: low priority data refreshed this often without scoring update


class Realtime(DataModule):
    """Vehicles info"""

    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data

        Full rate (active interval) only while overlays are shown (driving, or streamed while spectating),
        as overlays are their only consumers at that rate; idle interval otherwise (garage, monitor,
        replay or spectating off air), data still kept up to date (histories, pit timers, finish time).
        Per car work (see update_vehicle_data): scoring data & low priority pass once per game scoring
        update, telemetry (lift & coast, position) at full rate for cars near player only.
        """
        _event_wait = self.wait_update  # also wakes on new game data
        reset = False
        update_interval = self.idle_interval

        output = minfo.vehicles
        max_lap_diff_ahead = self.mcfg["lap_difference_ahead_threshold"]
        max_lap_diff_behind = self.mcfg["lap_difference_behind_threshold"]
        max_finish_time_diff = max(self.mcfg["finish_time_difference_threshold"], 0)
        last_version_update = None
        near_range = NEAR_RANGE

        while not _event_wait(update_interval):
            if not realtime_state.paused:

                if not reset:
                    reset = True
                    output.dataSetVersion = -1
                    output.scoringSnapshot = None
                    _index_slot_ids.clear()  # new session or reload: slot ids from scratch
                    reset_session_timing(output)
                    last_veh_total = -1
                    last_session_elapsed = -1.0
                    last_in_race = -1
                    last_scoring_time = -1.0
                    last_tick_veh_total = -1
                    last_low_priority = 0.0  # clock time of last low priority pass
                    last_far_time = FLOAT_INF  # player telemetry time of last update of far cars
                    last_plr_index = -2
                    name_turn = 0  # car whose names & compound are read again on next low priority pass
                    last_stamp: tuple = ()  # never skip first tick

                # Full rate only while overlays are shown (their only consumer at that rate)
                update_interval = self.active_interval if realtime_state.shown else self.idle_interval

                # Check setting: range of cars updated at full rate (overlays showing cars around player)
                if last_version_update != self.cfg.version_update:
                    last_version_update = self.cfg.version_update
                    near_range = near_range_of(self.cfg.user.setting)

                veh_total = output.totalVehicles = api.read.vehicle.total_vehicles()

                # Skip while game data not updated since last tick,
                # so dataSetVersion (overlays redraw on change) only changes with new data
                stamp = (data_stamp(), veh_total)
                if last_stamp == stamp:
                    continue
                last_stamp = stamp

                if veh_total > 0:
                    session_elapsed = api.read.timing.elapsed()
                    in_race = api.read.session.in_race()
                    # Game scoring (pit state, laps, distance of cars) updated (5 times per second)
                    scoring_time = api.read.session.elapsed()
                    update_scoring = last_scoring_time != scoring_time or last_tick_veh_total != veh_total
                    last_scoring_time = scoring_time
                    last_tick_veh_total = veh_total
                    # Low priority data (standings, gaps, names) only changes with scoring,
                    # also refreshed at least every LOW_PRIORITY_MAX_WAIT (other modules data, finish time)
                    now = monotonic()
                    update_low_priority = update_scoring or now - last_low_priority >= LOW_PRIORITY_MAX_WAIT
                    if update_low_priority:
                        last_low_priority = now
                        name_turn = (name_turn + 1) % veh_total
                    # Cars far from player: telemetry less often (track map, far part of navigation)
                    plr_index = api.read.vehicle.player_index()
                    update_far = (
                        update_scoring
                        or plr_index != last_plr_index  # positions relative to other player
                        or not last_far_time <= session_elapsed < last_far_time + FAR_INTERVAL
                    )
                    last_plr_index = plr_index
                    if update_far:
                        last_far_time = session_elapsed

                    update_vehicle_data(
                        output,
                        max_lap_diff_ahead,
                        max_lap_diff_behind,
                        update_low_priority,
                        session_elapsed,
                        in_race,
                        update_scoring,
                        update_far,
                        near_range,
                        # Names of every car read again after other session or car count change
                        name_turn if (
                            last_veh_total == veh_total
                            and last_session_elapsed <= session_elapsed
                            and last_in_race == in_race
                        ) else None,
                    )

                    if update_low_priority:

                        if in_race:
                            update_finish_time(output, max_finish_time_diff)

                        if last_session_elapsed > session_elapsed or last_in_race != in_race:  # other session
                            reset_session_timing(output)
                        if (
                            last_veh_total != veh_total
                            or last_session_elapsed > session_elapsed
                            or last_in_race != in_race
                        ):
                            update_qualify_position(output)
                            output.finishTimeOffset = 0.0
                            output.finishAsLap = True
                            output.finishLapOffset = 0.0
                            output.finishLapOffsetLeader = 0.0

                        last_veh_total = veh_total
                        last_session_elapsed = session_elapsed
                        last_in_race = in_race

            else:
                if reset:
                    reset = False
                    update_interval = WAIT_STATE_CHANGE  # game paused: idle until activity changes

        # Must reset on close
        output.finishTimeOffset = 0.0
        output.finishAsLap = True
        output.finishLapOffset = 0.0
        output.finishLapOffsetLeader = 0.0
        output.scoringSnapshot = None


def near_range_of(setting: dict) -> float:
    """Straight line distance (meters) of cars updated at full rate: NEAR_RANGE, or view of enabled
    navigation & radar overlays if larger (cars drawn around player)"""
    near_range = NEAR_RANGE
    try:
        navigation = setting.get("navigation") or {}
        if navigation.get("enable"):
            near_range = max(near_range, float(navigation.get("view_radius", 0)) * 2.5)  # its view range
        radar = setting.get("radar") or {}
        if radar.get("enable"):
            near_range = max(near_range, float(radar.get("radar_radius", 0)) * 2)
    except (AttributeError, TypeError, ValueError):
        pass
    return near_range


def update_vehicle_data(
    output: VehiclesInfo,
    max_lap_diff_ahead: float,
    max_lap_diff_behind: float,
    update_low_priority: bool,
    elapsed_time: float,
    in_race: bool,
    update_scoring: bool = True,
    update_far: bool = True,
    near_range: float = MAX_METERS,
    name_turn: int | None = None,
) -> None:
    """Update vehicle data

    Scoring data of a car (speed, pit state, laps, distance) only changes with game scoring update,
    so it is read (pit timer, speed trap & yellow flag updated) on scoring update or while in pits only.
    Telemetry of a car (lift & coast inputs, position relative to player) is read on every update for cars
    within near_range of player, else only if update_far; throttle & brake again only after car telemetry update.

    Args:
        update_far: also update telemetry of cars farther than near_range.
        near_range: straight line distance (meters) of cars updated on every call.
        name_turn: index of car whose names, class & compound are read again (low priority update), others
            only while in pits (driver swap, tyre change), new or unnamed; None: read for every car.
    """
    nearest_line = MAX_METERS
    nearest_time_behind = -MAX_SECONDS
    nearest_yellow_ahead = MAX_METERS
    nearest_yellow_behind = -MAX_METERS
    nearest_blue_class = ""

    # Counter
    total_completed_laps = 0
    total_out_pits = 0
    total_in_pits = 0
    total_stopped_pits = 0
    total_pit_requests = 0

    # General data
    scoring_time = api.read.session.elapsed()  # time of scoring data (laps & lap distance of cars)
    track_length = api.read.lap.track_length()
    under_blue = api.read.session.blue_flag()
    speedtrap_distance = minfo.mapping.speedTrapPosition

    # Local player data
    plr_lap_distance = api.read.lap.distance()
    plr_lap_progress_total = api.read.lap.completed_laps() + calc.lap_progress_distance(plr_lap_distance, track_length)
    plr_laptime_est = api.read.timing.estimated_laptime()
    plr_timeinto_est = api.read.timing.estimated_time_into()
    plr_pos_x = api.read.vehicle.position_longitudinal()
    plr_pos_y = api.read.vehicle.position_lateral()
    plr_ori_yaw = api.read.vehicle.orientation_yaw_radians()
    # Player index of this tick, -1 if no listed car is the player (never a stale index of another car)
    plr_index = api.read.vehicle.player_index()
    output.playerIndex = plr_index if 0 <= plr_index < output.totalVehicles else -1
    # Scoring data of every car for relative module (same scoring sample: read once)
    snapshot_rows: list[tuple] = []

    # Update dataset from all vehicles in current session
    for index, data in zip(range(output.totalVehicles), output.dataSet):
        data.isPlayer = is_player = index == plr_index

        # Update high priority info
        read_scoring = update_scoring or update_low_priority or data.inPit
        new_car = False
        if read_scoring:
            data.speed = speed = api.read.vehicle.speed(index)
            slot_id = api.read.vehicle.slot_id(index)
            known_slot = _index_slot_ids.get(index)
            if known_slot != slot_id:  # other car in index, or first seen since module reset
                if known_slot is not None:
                    reset_vehicle_history(data)
                    _point_times.pop(index, None)
                _index_slot_ids[index] = slot_id
                new_car = True
            laps_completed = api.read.lap.completed_laps(index)
            lap_distance = api.read.lap.distance(index)
            data.inPit = api.read.vehicle.in_paddock(index)
            data.pitTimer.update(data.inPit, elapsed_time, laps_completed, speed)
            data.isYellow = speed < 8 and data.inPit != 2
        else:
            speed = data.speed

        # Car telemetry: every update near player, else less often (far cars)
        read_telemetry = is_player or update_far or data.relativeStraightDistance < near_range
        if read_telemetry:
            opt_etime = elapsed_time if is_player else api.read.timing.elapsed(index)

        if data.inPit:
            data.licoTimer.elapsed = 0.0
            data.speedTrap.speed = 0.0
        else:
            if read_telemetry:
                lico = data.licoTimer
                if lico.input_time != opt_etime:  # car telemetry updated
                    lico.input_time = opt_etime
                    lico.throttle = api.read.inputs.throttle_raw(index)
                    lico.brake = api.read.inputs.brake_raw(index)
                lico.update(elapsed_time, lico.throttle, lico.brake)
            if read_scoring:  # distance unchanged otherwise
                data.speedTrap.update(speed, lap_distance, speedtrap_distance, track_length)

        if is_player:
            data.elapsedTime = elapsed_time
            data.worldPositionX = plr_pos_x
            data.worldPositionY = plr_pos_y
            if data.isYellow:
                nearest_yellow_ahead = 0.0
                nearest_yellow_behind = 0.0
        else:
            # Relative position & orientation
            if read_telemetry and data.elapsedTime != opt_etime:
                opt_pos_x = api.read.vehicle.position_longitudinal(index)
                opt_pos_y = api.read.vehicle.position_lateral(index)
                opt_ori_yaw = api.read.vehicle.orientation_yaw_radians(index)
                # Player data update rate may be (twice) higher than opponents
                # Interpolate coordinates to avoid desync
                est_pos_x, est_pos_y = calc.time_interp_coordinate(
                    opt_pos_x,
                    data.worldPositionX,
                    opt_pos_y,
                    data.worldPositionY,
                    opt_etime,
                    data.elapsedTime,
                    elapsed_time,
                )
                data.worldPositionX = opt_pos_x
                data.worldPositionY = opt_pos_y
                data.elapsedTime = opt_etime

                data.relativeOrientationRadians = opt_ori_yaw - plr_ori_yaw
                data.relativeRotatedPositionX, data.relativeRotatedPositionY = calc.rotate_coordinate(
                    plr_ori_yaw - 3.14159265,  # plr_ori_rad, rotate view
                    est_pos_x - plr_pos_x,  # x position related to player
                    est_pos_y - plr_pos_y,  # y position related to player
                )
                # Relative distance & time gap
                data.relativeStraightDistance = calc.distance(
                    (plr_pos_x, plr_pos_y),
                    (est_pos_x, est_pos_y)
                )

            # Nearest straight line distance (non local players)
            if nearest_line > data.relativeStraightDistance:
                nearest_line = data.relativeStraightDistance

        # Update low priority info
        if update_low_priority:
            data.currentLapProgress = calc.lap_progress_distance(lap_distance, track_length)
            data.totalLapProgress = laps_completed + data.currentLapProgress
            if in_race:
                points = _point_times.get(index)
                if points is None:
                    points = _point_times[index] = PointTimes()
                points.update(data.totalLapProgress, scoring_time)
            data.isLapped = calc.lap_difference(
                data.totalLapProgress, plr_lap_progress_total,
                max_lap_diff_ahead, max_lap_diff_behind
            ) if in_race else 0

            data.positionOverall = api.read.vehicle.place(index)
            data.bestLapTime = api.read.timing.best_laptime(index)
            data.numPitStops = api.read.vehicle.number_pitstops(index, api.read.vehicle.number_penalties(index))
            data.pitRequested = api.read.vehicle.pit_request(index)
            # Names, class & compound (decoded text): only change in pits (driver swap, tyres) or with car
            if name_turn is None or new_car or data.inPit or index == name_turn or not data.driverName:
                data.driverName = api.read.vehicle.driver_name(index)
                data.vehicleName = api.read.vehicle.vehicle_name(index)
                data.vehicleBrand = select_brand_name(index, data.vehicleName)
                data.vehicleClass = api.read.vehicle.class_name(index)
                data.tireCompoundName = api.read.tyre.compound_class(index)
            data.vehicleIntegrity = api.read.vehicle.integrity(index)
            data.isFinished = api.read.vehicle.finish_state(index) == 1
            data.incidents = api.read.vehicle.incidents(index)
            data.trackLimitsPoints = api.read.session.cut_points(index)
            data.penalty = api.read.vehicle.penalty(index)

            if in_race:  # gaps in class once every car updated, outside race: best lap gaps
                data.gapBehindNext = calc_gap_behind_next(index)
                data.gapBehindLeader = calc_gap_behind_leader(index)

            lap_start_time = api.read.timing.start(index)
            data.lapStartTime = lap_start_time
            last_laptime = api.read.timing.last_laptime(index)
            data.sectors.update(
                laps_completed, api.read.lap.sector_index(index),
                api.read.timing.current_sector1(index), api.read.timing.current_sector2(index),
                api.read.timing.last_sector1(index), api.read.timing.last_sector2(index),
                last_laptime, bool(data.inPit),
                api.read.timing.best_sector1(index), api.read.timing.best_sector2(index), data.bestLapTime)
            fuel_remaining = api.read.engine.fuel_fraction(index)
            energy_remaining = api.read.engine.virtual_energy(index)

            data.lapTimeHistory.update(lap_start_time, elapsed_time, data.bestLapTime)
            data.isValidLap = last_laptime > 0
            data.lastLapTime = last_laptime if data.isValidLap else data.lapTimeHistory.last

            data.fuelHistory.update(lap_start_time, fuel_remaining)
            data.energyHistory.update(lap_start_time, energy_remaining)
            update_stint_usage(data, fuel_remaining, energy_remaining)

            # Update counter
            total_completed_laps += laps_completed
            opt_timeinto_est = api.read.timing.estimated_time_into(index)

            if data.inPit == 1:  # in pit (exclude garage)
                total_in_pits += 1
                total_stopped_pits += (speed < 0.1)
            elif data.inPit == 0:  # out pit
                total_out_pits += 1
                total_pit_requests += data.pitRequested
                # Nearest traffic time gap (opponents behind local players)
                opt_time_behind = calc.circular_position_relative(
                    plr_laptime_est,
                    plr_timeinto_est,
                    opt_timeinto_est,
                )
                if 0 > opt_time_behind > nearest_time_behind:
                    nearest_time_behind = opt_time_behind
                    if under_blue and (not in_race or data.isLapped > 0):
                        nearest_blue_class = data.vehicleClass

            # Nearest yellow flag distance
            if data.isYellow:
                opt_rel_distance = calc.circular_position_relative(
                    track_length, plr_lap_distance, lap_distance)
                if nearest_yellow_ahead > opt_rel_distance >= 0:
                    nearest_yellow_ahead = opt_rel_distance
                if nearest_yellow_behind < opt_rel_distance <= 0:
                    nearest_yellow_behind = opt_rel_distance

            # Save leader info
            if data.positionOverall == 1:
                output.leaderIndex = index
                output.leaderBestLapTime = data.bestLapTime

            snapshot_rows.append((
                data.inPit == 2,  # in garage
                data.inPit != 0,  # in pit lane or garage
                opt_timeinto_est,
                data.vehicleClass,
                data.positionOverall,
                data.bestLapTime,
                last_laptime,
            ))

    if update_low_priority:
        update_class_best_sectors(output)
        if in_race:
            update_class_gaps(output, scoring_time)
        else:
            update_best_lap_gaps(output)
        output.nearestTraffic = -nearest_time_behind
        output.nearestYellowAhead = nearest_yellow_ahead
        output.nearestYellowBehind = nearest_yellow_behind
        output.nearestBlueClass = nearest_blue_class

        output.totalOutPits = total_out_pits
        output.totalInPits = total_in_pits
        output.totalStoppedPits = total_stopped_pits
        output.totalPitRequests = total_pit_requests
        output.totalCompletedLaps = total_completed_laps
        output.scoringSnapshot = ScoringSnapshot(scoring_time, tuple(snapshot_rows))

    # Output extra info
    output.nearestLine = nearest_line
    output.dataSetVersion += 1


def update_finish_time(output: VehiclesInfo, max_finish_time_diff: float) -> None:
    """Estimated finish time & offset based on remaining laps"""
    finish_type = api.read.session.finish_type()
    remaining_time = api.read.session.remaining()
    leader_index = output.leaderIndex
    player_index = output.playerIndex
    leader_pace = output.dataSet[leader_index].lapTimeHistory.average
    player_pace = minfo.delta.lapTimePace

    # Time only
    if finish_type == 0:

        # Final pit stop time offset
        if minfo.energy.available:
            est_pits_late = minfo.energy.estimatedNumPitStopsEnd
        else:
            est_pits_late = minfo.fuel.estimatedNumPitStopsEnd

        if 0.2 < est_pits_late < 1.2:
            final_pit_time = minfo.mapping.pitPassTime + api.read.vehicle.pit_stop_time()
        else:
            final_pit_time = 0.0

        # Leader time, no offset without valid lap pace yet (formation & first lap)
        if (
            leader_index == player_index
            or player_index < 0  # no player car listed
            or output.dataSet[leader_index].isFinished
            or not 0 < leader_pace < MAX_SECONDS
            or not 0 < player_pace < MAX_SECONDS
        ):
            player_lap_offset = laps_gain_from_leader = 0.0
        else:
            leader_lap_into = api.read.lap.progress(leader_index)
            player_lap_into = api.read.lap.progress(player_index)

            # Leader finish remaining time
            leader_lap_remaining = calc.end_timer_laps_remain(leader_lap_into, leader_pace, remaining_time)
            leader_finish_offset = (1 - leader_lap_remaining % 1) * leader_pace
            leader_finish_time = remaining_time + leader_finish_offset

            # Player finish remaining time without pit
            player_lap_remaining = calc.end_timer_laps_remain(player_lap_into, player_pace, remaining_time)
            player_laps_left_nopit = calc.time_type_laps_remain(calc.ceil(player_lap_remaining), player_lap_into)

            # Player finish remaining time with final pit
            player_lap_remaining = calc.end_timer_laps_remain(player_lap_into, player_pace, remaining_time - final_pit_time)
            player_laps_left_pit = calc.time_type_laps_remain(calc.ceil(player_lap_remaining), player_lap_into)

            # Player finish remaining time towards leader
            to_leader_lap_remaining = calc.end_timer_laps_remain(player_lap_into, player_pace, leader_finish_time)
            to_leader_laps_left = calc.time_type_laps_remain(calc.ceil(to_leader_lap_remaining), player_lap_into)

            # Laps gain
            laps_gain_from_pit = player_laps_left_pit - player_laps_left_nopit
            laps_gain_from_leader = to_leader_laps_left - player_laps_left_nopit

            player_lap_offset = laps_gain_from_leader + laps_gain_from_pit

        output.finishTimeOffset = 0.0
        output.finishAsLap = True
        output.finishLapOffset = player_lap_offset
        # Leader part alone for fuel module: final pit part comes from its own pit stop estimate
        output.finishLapOffsetLeader = laps_gain_from_leader
        return

    output.finishLapOffsetLeader = 0.0  # leader finish in finish time offset

    # Leader time
    if leader_index >= 0 and 0 < leader_pace < MAX_SECONDS:
        leader_finish_time = leader_pace * api.read.lap.remaining(leader_index)
        leader_finish_offset = max(remaining_time - leader_finish_time, 0.0)
    else:  # default to lap if unavailable
        leader_finish_time = 0.1
        leader_finish_offset = 0.1

    # Player time
    if player_index >= 0 and 0 < player_pace < MAX_SECONDS:
        player_finish_time = player_pace * api.read.lap.remaining(player_index)
        player_finish_offset = max(remaining_time - player_finish_time, 0.0)
    else:  # default to lap if unavailable
        player_finish_time = 0.1
        player_finish_offset = 0.1

    # Laps only
    if finish_type == 1:
        output.finishTimeOffset = -leader_finish_time
        output.finishAsLap = (
            leader_finish_time > 0  # default to lap if unavailable
            and player_finish_time - leader_finish_time < max_finish_time_diff
        )
        return

    # Laps & time
    if finish_type == 2:
        output.finishTimeOffset = leader_finish_offset
        output.finishAsLap = (
            leader_finish_offset > 0
            and leader_finish_offset - player_finish_offset < max_finish_time_diff
        )
        return


def update_qualify_position(output: VehiclesInfo) -> None:
    """Update qualify position"""
    temp_class = sorted((
        api.read.vehicle.class_name(index),  # 0 class name
        api.read.vehicle.qualification(index),  # 1 qualification position
        index,  # 2 player index
    ) for index in range(output.totalVehicles))
    # Update position
    qualify_in_class = 0
    last_class_name = None
    for class_name, qualify_overall, plr_index in temp_class:
        if last_class_name != class_name:
            last_class_name = class_name
            qualify_in_class = 1
        else:
            qualify_in_class += 1
        output.dataSet[plr_index].qualifyOverall = qualify_overall
        output.dataSet[plr_index].qualifyInClass = qualify_in_class


def calc_time_gap_behind(
    ahead_index: int,
    behind_index: int,
    lap_diff: float,
) -> float:
    """Calculate interval behind next in class"""
    if ahead_index < 0:
        return 0.0
    if lap_diff >= 1 or lap_diff <= -1:  # laps
        return int(abs(lap_diff))
    # Time gap between driver ahead and behind
    time_gap = api.read.timing.estimated_time_into(ahead_index) - api.read.timing.estimated_time_into(behind_index)
    # Check lap diff (positive) for position correction
    # in case the ahead driver is momentarily behind (such as during double-file formation lap)
    if time_gap < 0 < lap_diff:
        time_gap += api.read.timing.estimated_laptime(behind_index)
    return abs(time_gap)


class PointTimes:
    """Session time a car passed each timing point of its last laps (TIMING_POINTS per lap), points passed
    between two scoring updates timed by interpolation"""

    __slots__ = ("times", "progress", "time")

    def __init__(self):
        self.times: dict[int, float] = {}  # timing point number from session start (lap * TIMING_POINTS + point)
        self.progress = -1.0  # laps & fraction of lap at last update
        self.time = 0.0

    def update(self, progress: float, time: float):
        """Car at progress (laps) at session time: points passed since last update timed"""
        last_progress, last_time = self.progress, self.time
        self.progress, self.time = progress, time
        if last_progress < 0 or progress < last_progress or progress - last_progress > 1 or time <= last_time:
            if progress < last_progress:  # went back (pits, restart): earlier times no longer apply
                self.times.clear()
            return
        first = int(last_progress * TIMING_POINTS) + 1
        last = int(progress * TIMING_POINTS)
        if last < first:
            return
        times = self.times
        rate = (time - last_time) / (progress - last_progress)
        for point in range(first, last + 1):
            times[point] = last_time + (point / TIMING_POINTS - last_progress) * rate
        if len(times) > TIMING_POINTS * 3:  # last two laps kept
            oldest = last - TIMING_POINTS * 2
            for point in [point for point in times if point < oldest]:
                del times[point]

    def time_at(self, progress: float) -> float | None:
        """Session time car passed progress (laps), None if not timed (not passed, or before kept laps)"""
        point = int(progress * TIMING_POINTS)
        before = self.times.get(point)
        after = self.times.get(point + 1)
        if before is None or after is None:
            return None
        return before + (after - before) * (progress * TIMING_POINTS - point)


def time_behind(ahead: PointTimes | None, behind_progress: float, now: float) -> float | None:
    """Time behind a car (now - when it passed the point where the car behind is), None if unknown"""
    if ahead is None:
        return None
    passed = ahead.time_at(behind_progress)
    return now - passed if passed is not None and passed <= now else None


def update_class_gaps(output: VehiclesInfo, now: float) -> None:
    """Race gaps in class: laps if a lap or more behind, else time since the car ahead (or class leader) passed
    the same point of the lap; estimate of game time into lap until the car ahead has passed timed points"""
    total = min(output.totalVehicles, len(output.dataSet))
    cars = output.dataSet
    for index in range(total):
        data = cars[index]
        for target, ahead_index in (("gapBehindNextInClass", data.classAheadIndex),
                                    ("gapBehindLeaderInClass", data.classLeaderIndex)):
            if not 0 <= ahead_index < total or ahead_index == index:
                setattr(data, target, 0.0)
                continue
            lap_diff = cars[ahead_index].totalLapProgress - data.totalLapProgress
            gap = None
            if -1 < lap_diff < 1:
                gap = time_behind(_point_times.get(ahead_index), data.totalLapProgress, now)
            setattr(data, target, gap if gap is not None else calc_time_gap_behind(ahead_index, index, lap_diff))


def reset_session_timing(output: VehiclesInfo) -> None:
    """New session: sector times & bests, timing points of every car from scratch (compared within session only)"""
    _point_times.clear()
    for data in output.dataSet:
        data.sectors = LapSectors()
        data.classBestSectors = (0.0, 0.0, 0.0)
        data.classBestLap = 0.0


def update_class_best_sectors(output: VehiclesInfo) -> None:
    """Best S1, S2, S3 (personal bests of its cars) & best lap of each class in session, told to every car of class
    (purple times, as game live timing)"""
    total = min(output.totalVehicles, len(output.dataSet))
    cars = output.dataSet
    best: dict[str, list[float]] = {}
    for index in range(total):
        data = cars[index]
        found = best.setdefault(data.vehicleClass, [0.0, 0.0, 0.0, 0.0])
        lap = data.bestLapTime if 0 < data.bestLapTime < MAX_SECONDS else 0.0
        for number, value in enumerate((*data.sectors.best, lap)):
            if value and (not found[number] or value < found[number]):
                found[number] = value
    for index in range(total):
        data = cars[index]
        found = best[data.vehicleClass]
        data.classBestSectors = (found[0], found[1], found[2])
        data.classBestLap = found[3]


def update_best_lap_gaps(output: VehiclesInfo) -> None:
    """Gaps & intervals outside race: best lap time behind leader & car ahead (overall, in class)

    Standings follow best lap outside race, so time & distance on track between cars mean nothing.
    Gap is 0 while car or car ahead has no lap time.
    """
    total = min(output.totalVehicles, len(output.dataSet))
    cars = output.dataSet[:total]
    best_of_place = {data.positionOverall: data.bestLapTime for data in cars}
    leader_best = best_of_place.get(1, 0.0)
    for data in cars:
        best = data.bestLapTime
        data.gapBehindNext = best_lap_gap(best, best_of_place.get(data.positionOverall - 1, 0.0))
        data.gapBehindLeader = best_lap_gap(best, leader_best)
        ahead, leader = data.classAheadIndex, data.classLeaderIndex
        data.gapBehindNextInClass = best_lap_gap(best, cars[ahead].bestLapTime) if 0 <= ahead < total else 0.0
        data.gapBehindLeaderInClass = best_lap_gap(best, cars[leader].bestLapTime) if 0 <= leader < total else 0.0


def best_lap_gap(best: float, ahead_best: float) -> float:
    """Best lap time behind other car's best lap, 0 if either has no lap time"""
    if 0 < best < MAX_SECONDS and 0 < ahead_best < MAX_SECONDS:
        return max(best - ahead_best, 0.0)
    return 0.0


def calc_gap_behind_next(index: int) -> float:
    """Calculate interval behind next"""
    laps_behind_next = api.read.lap.behind_next(index)
    if laps_behind_next > 0:
        return laps_behind_next
    return api.read.timing.behind_next(index)


def calc_gap_behind_leader(index: int) -> float:
    """Calculate interval behind leader"""
    laps_behind_leader = api.read.lap.behind_leader(index)
    if laps_behind_leader > 0:
        return laps_behind_leader
    return api.read.timing.behind_leader(index)


def reset_vehicle_history(data: VehicleDataSet) -> None:
    """Reset per car history data, index now holds another car"""
    data.pitTimer = PitTimer()
    data.fuelHistory = DeltaFuelHistory()
    data.energyHistory = DeltaFuelHistory()
    data.lapTimeHistory = DeltaLapTimeHistory("d", (0, 0, 0, 0, 0))
    data.licoTimer = LicoTimer()
    data.speedTrap = SpeedTrap()
    data.sectors = LapSectors()
    data.currentStintLaps = 0  # recalculated from new pit timer & histories
    data.estimatedStintLaps = 0.0
    data.elapsedTime = 0.0  # no earlier sample: position never extrapolated from previous car's


def update_stint_usage(
    data: VehicleDataSet,
    fuel_remaining: float,
    energy_remaining: float,
) -> None:
    """Update stint usage data"""
    if energy_remaining > 0:
        if fuel_remaining > 0:
            est_run_laps = min(data.fuelHistory.laps, data.energyHistory.laps)
        else:
            est_run_laps = data.energyHistory.laps
    elif fuel_remaining > 0:
        est_run_laps = data.fuelHistory.laps
    else:
        est_run_laps = 0.0

    stint_laps_done = data.pitTimer.laps
    stint_laps_est = (stint_laps_done + est_run_laps) if est_run_laps > 0 else 0.0

    if energy_remaining != 0:
        data.energyRemaining = energy_remaining
    elif fuel_remaining > 0:
        data.energyRemaining = fuel_remaining
    else:
        data.energyRemaining = -1

    data.currentStintLaps = stint_laps_done
    data.estimatedStintLaps = stint_laps_est
