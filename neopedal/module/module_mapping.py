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
Mapping module
"""

import logging
import threading
import time
from collections.abc import Callable

from .. import calculation as calc
from .. import realtime_state
from ..api_control import api
from ..const_file import FileExt
from ..module_info import NO_TRACK_MAP, MapCoords, MappingInfo, TrackMap
from ..setting import cfg
from ..userfile.track_info import load_track_info, save_track_info
from ..userfile.track_map import load_track_map_file, save_track_map_file
from ..userfile.track_map_official import OfficialMap, Point, fetch_official_points
from ..validator import file_last_modified, generator_init
from ._base import MODULE_STOP, WAIT_STATE_CHANGE, DataModule, data_stamp

logger = logging.getLogger(__name__)

MAX_NODE_GAP = 400.0  # meters between two nodes of a lap: farther is a teleport (back to garage, skipped part of lap)
MAX_SPEED = 125.0  # m/s (450 km/h): gap farther than driven at this speed since last node is a teleport

OfficialFetch = Callable[[str, float], "list[Point] | None"]  # (track name, track length) -> circuit points


class Realtime(DataModule):
    """Mapping data"""

    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        _event_wait = self.wait_update  # also wakes on new game data
        reset = False
        vehicle_resets = None
        update_interval = self.idle_interval
        last_stamp: tuple = ()  # game data stamp of last update

        output = self.ctx.minfo.mapping
        gen_record_track_map = record_track_map(
            output=output,
            filepath=self.cfg.path.track_map,
            min_node_distance=min(max(self.mcfg["minimum_node_distance"], 0.1), 50.0),
            official=fetch_official_points,
        )
        gen_record_track_info = record_track_info(
            output=output,
        )

        try:
            while not _event_wait(update_interval):
                if realtime_state.active or vehicle_resets != realtime_state.resets:
                    vehicle_resets = realtime_state.resets

                    if not reset:
                        reset = True
                        update_interval = self.active_interval
                        last_stamp = ()  # never skip first tick

                    # Skip while game data not updated since last tick
                    stamp = data_stamp()
                    if last_stamp == stamp:
                        continue
                    last_stamp = stamp

                    # Recording map data
                    gen_record_track_map.send(vehicle_resets)
                    gen_record_track_info.send(vehicle_resets)

                else:
                    reset = False
                    update_interval = WAIT_STATE_CHANGE  # idle until activity changes
        finally:
            # Also save on error exit, as restarted module reloads data from file
            self.save_on_stop(gen_record_track_info)


def set_sunlight_phase(sunrise: str, sunset: str):
    """Set sunlight phase time"""
    sec_sunrise = calc.clock_time_to_seconds(sunrise)
    sec_sunset = calc.clock_time_to_seconds(sunset)
    sec_midday = calc.clockwise_median_time(sec_sunrise, sec_sunset)
    sec_midnight = calc.clockwise_median_time(sec_sunset, sec_sunrise)
    return tuple(sorted((
        (sec_sunrise, 0),
        (sec_midday, 1),
        (sec_sunset, 2),
        (sec_midnight, 3),
    )))


@generator_init
def record_track_info(output: MappingInfo):
    """Update track info"""
    last_reset = None  # reset check
    delayed_save = False
    measured: dict[str, float] = {}  # values measured since last reset, only ones saved

    track_name = ""
    pit_entry = 0.0
    pit_exit = 0.0
    pit_speed = 0.0

    while True:
        reset = yield None

        # Reset
        if last_reset != reset:
            # Save data: only measured values, never cached ones over values edited meanwhile (track info editor)
            if delayed_save:
                if measured or track_name not in cfg.user.tracks:  # new track always added
                    save_track_info(track_name, **measured)
                measured = {}
                delayed_save = False

            # Delay reset until driving (module stopping: data saved only)
            if reset is MODULE_STOP or not realtime_state.active:
                continue
            last_reset = reset

            # Load track info
            track_name = api.read.session.track_name()
            pit_entry = load_track_info(track_name, "pit_entry")
            pit_exit = load_track_info(track_name, "pit_exit")
            pit_speed = load_track_info(track_name, "pit_speed")
            output.speedTrapPosition = load_track_info(track_name, "speed_trap")
            output.orientation = load_track_info(track_name, "orientation")
            output.sunlightPhases = set_sunlight_phase(
                load_track_info(track_name, "sunrise"),
                load_track_info(track_name, "sunset"),
            )

            # Set default
            pos_last = 0.0
            last_speed = 0.0
            pitlane_length = 0.0
            last_in_pits = -1
            delayed_save = True

        in_pits = api.read.vehicle.in_pits()

        # Calibrate pit speed limit
        if in_pits and api.read.switch.speed_limiter():
            pos_curr = api.read.lap.distance()
            if pos_last != pos_curr:  # position check
                pos_last = pos_curr
                speed = api.read.vehicle.speed()
                if (api.read.inputs.throttle_raw() > 0.95 and  # full throttle check
                    api.read.inputs.brake_raw() < 0.01 and  # no braking check
                    speed > 1 and  # moving check
                    0.1 > speed - last_speed > 0):  # limit speed delta in 0.0 - 0.1m/s
                    pit_speed = measured["pit_speed"] = speed
                last_speed = speed

        # Calculate pit lane length
        if last_in_pits != in_pits:
            if last_in_pits != -1 and api.read.vehicle.speed() > 1:  # avoid ESC desync
                if in_pits:  # entering pit
                    pit_entry = measured["pit_entry"] = max(api.read.lap.distance(), 0.0)
                else:  # exiting pit
                    pit_exit = measured["pit_exit"] = max(api.read.lap.distance(), 0.0)
            last_in_pits = in_pits
            pitlane_length = calc.pitlane_length(
                api.read.lap.track_length(),
                pit_entry,
                pit_exit,
            )

        output.pitSpeedLimit = pit_speed
        output.pitEntryPosition = pit_entry
        output.pitExitPosition = pit_exit
        output.pitLaneLength = pitlane_length
        output.pitPassTime = pitlane_length / pit_speed if pit_speed else 0.0


def start_official_fetch(fetch: OfficialFetch, track_name: str, track_length: float) -> list:
    """Official circuit asked in a background thread (game Rest API: blocking), list filled with its points (None
    if none) once answered"""
    result: list = []

    def fetching() -> None:
        points = None
        try:
            points = fetch(track_name, track_length)
        except Exception:  # unexpected answer: recorded laps only
            logger.exception("TRACK MAP: unable to read official circuit of %s", track_name)
        result.append(points)

    threading.Thread(target=fetching, name="track map official", daemon=True).start()
    return result


def publish_map(output: MappingInfo, coords: tuple[tuple[float, float], ...] | None,
                dists: tuple[tuple[float, float], ...] | None, sectors: tuple[int, int] | None) -> None:
    """Track map shown by overlays replaced as a whole (new publish time: overlays draw it again)"""
    output.trackMap = TrackMap(coords, dists, sectors, max(time.time(), output.trackMap.lastModified + 0.001))


@generator_init
def record_track_map(output: MappingInfo, filepath: str, min_node_distance: float = 5.0,
                     official: OfficialFetch | None = None):
    """Record map data, a node every min_node_distance meters at least

    A stall of app or game (gap in lap distance a car can drive since last node) keeps the lap: shown, but saved only
    once a lap without gap is recorded. Official circuit of game (official: fetch function, None: recorded laps only)
    shown until a lap is recorded, saved as track map once its start & both sector lines are known.
    """
    last_reset = None  # reset check
    delayed_save = False

    recording = False
    validating = False
    last_sector_idx = -1
    last_lap_stime = -1.0  # last lap start time
    pos_last = 0.0  # last checked player vehicle position
    pos_recorded = 0.0  # position of last recorded node
    time_recorded = 0.0  # elapsed time of last recorded node
    is_pit_lap = False  # recording lap visited pit lane
    temp_pit_lap = False  # validating lap visited pit lane
    lap_gaps = 0  # stalls of recording lap
    temp_gaps = 0  # stalls of validating lap
    shown_gaps = -1  # stalls of recorded lap shown but not saved, -1 none shown
    shown_lap = ("", NO_TRACK_MAP)  # track & recorded lap shown but not saved (kept after a vehicle reset)
    # File info
    map_exist = False
    last_modified = 0.0
    filename = ""
    # Map data
    output_data = MapCoords()
    recorder_data = MapCoords()
    temp_data = MapCoords()
    # Official circuit
    official_track = ""  # track asked to game
    official_result: list = []  # filled by fetch thread
    official_map: OfficialMap | None = None
    official_car = 0  # car sampled next (start line placement)
    official_sector = -1  # last sector index of player

    while True:
        reset = yield None

        # Reset
        if last_reset != reset:
            # Save data
            if delayed_save:
                save_track_map_file(
                    filepath=filepath,
                    filename=filename,
                    view_box=calc.svg_view_box(output_data.coords, 20),
                    raw_coords=output_data.coords,
                    raw_dists=output_data.dists,
                    sector_index=output_data.sectors,
                    decimals=4,
                )
                output_data.clear()
                delayed_save = False
                #logger.info("map saved, stopped map recording")

            # Delay reset until driving
            if not realtime_state.active:
                continue
            last_reset = reset

            # Check if same map loaded: same track & file time (maps of 2 tracks can share a file time)
            last_filename = filename
            filename = api.read.session.track_name()
            modified = file_last_modified(
                filepath=filepath,
                filename=filename,
                extension=FileExt.SVG,
            )
            map_exist = (last_filename == filename and last_modified == modified > 0)
            last_modified = modified
            if map_exist:
                continue

            # Load map file
            output_data.coords, output_data.dists, output_data.sectors = load_track_map_file(
                filepath=filepath,
                filename=filename,
            )
            if output_data.is_valid():
                output.trackMap = TrackMap(output_data.coords, output_data.dists, output_data.sectors, last_modified)
                map_exist = True
                official_map = None
                #logger.info("map exist")
            else:
                output.reset_map()
                map_exist = False
                #logger.info("map not exist")
                if official is not None and official_track != filename:  # asked once per track
                    official_track = filename
                    official_map = None
                    official_result = start_official_fetch(official, filename, api.read.lap.track_length())
                elif official_map is not None:  # same track after a reset: shown again
                    publish_map(output, official_map.coords, official_map.dists, official_map.sector_indexes())
                if shown_lap[0] == filename and shown_lap[1].coordinates:  # same track after a reset: shown again
                    output.trackMap = shown_lap[1]
                else:
                    shown_lap = ("", NO_TRACK_MAP)
                    shown_gaps = -1

            # Reset to defaults
            output_data.clear()
            temp_data.clear()
            recorder_data.clear()
            recording = False
            validating = False
            last_sector_idx = -1
            last_lap_stime = -1.0
            pos_last = pos_recorded = 0.0
            is_pit_lap = temp_pit_lap = False
            official_sector = -1

        # Recording map data
        if map_exist:
            continue

        # Official circuit: shown once answered, start line placed from a car on track, sector lines from player
        if official_result:
            points = official_result.pop()
            official_map = OfficialMap.build(points, api.read.lap.track_length())
            if official_map is None:
                official_track = ""  # asked again after next reset (game in session, other layout)
            elif shown_gaps < 0:
                publish_map(output, official_map.coords, None, None)
        if official_map is not None:
            changed = False
            if not official_map.placed:
                total = api.read.vehicle.total_vehicles()
                if total > 0:  # a car per update: path projected only for a car's first & second sample
                    car = official_car % total
                    official_car = car + 1
                    if not api.read.vehicle.in_pits(car):
                        changed = official_map.sample(
                            car,
                            api.read.vehicle.position_longitudinal(car),
                            api.read.vehicle.position_lateral(car),
                            api.read.lap.distance(car),
                        )
            sector_idx = api.read.lap.sector_index()
            if official_sector != sector_idx:
                if 0 <= official_sector == sector_idx - 1 and not api.read.vehicle.in_pits():  # crossed a line
                    changed |= official_map.sector_crossed(official_sector, api.read.lap.distance())
                official_sector = sector_idx
            if changed:
                sectors = official_map.sector_indexes()
                if sectors is not None:  # complete: saved as track map, loaded in next loop
                    output_data.coords = official_map.coords
                    output_data.dists = official_map.dists
                    output_data.sectors = sectors
                    official_map = None
                    recording = False
                    validating = False
                    delayed_save = True
                    last_reset = None
                    continue
                if shown_gaps < 0:  # recorded lap shown has a start line
                    publish_map(output, official_map.coords, official_map.dists, None)

        # Lap start & finish detection
        # Init reset
        lap_stime = api.read.timing.start()
        if last_lap_stime == -1:
            recorder_data.reset()
            last_lap_stime = lap_stime

        # New lap
        if lap_stime > last_lap_stime:
            # End recording: full lap only (enough nodes, both sector lines crossed in order)
            if (recorder_data.coords and len(recorder_data.coords) >= 10
                    and 0 < recorder_data.sectors[0] < recorder_data.sectors[1]):
                temp_data.coords = tuple(recorder_data.coords)
                temp_data.dists = tuple(recorder_data.dists)
                temp_data.sectors = tuple(recorder_data.sectors)
                temp_pit_lap = is_pit_lap
                temp_gaps = lap_gaps
                validating = True
            # Reset
            recorder_data.reset()
            last_lap_stime = lap_stime
            pos_last = pos_recorded = 0.0
            is_pit_lap = False
            lap_gaps = 0
            recording = True
            #logger.info("map recording")

        # Validate map data after crossing finish line
        if validating:
            laptime_curr = api.read.timing.current_laptime()
            # Save data
            if 1 < laptime_curr <= 8 and api.read.timing.last_laptime() > 0 and not temp_pit_lap:
                if temp_gaps:  # lap with gaps: shown unless a better map is, next laps recorded on
                    if ((official_map is None or not official_map.placed)
                            and (shown_gaps < 0 or temp_gaps < shown_gaps)):
                        publish_map(output, temp_data.coords, temp_data.dists, temp_data.sectors)
                        shown_gaps = temp_gaps
                        shown_lap = (filename, output.trackMap)
                    temp_data.clear()
                    validating = False
                else:
                    output_data.coords = temp_data.coords
                    output_data.dists = temp_data.dists
                    output_data.sectors = temp_data.sectors
                    # Reset
                    temp_data.clear()
                    recorder_data.clear()
                    recording = False
                    validating = False
                    delayed_save = True
                    last_reset = None  # load recorded map in next loop
            # Switch off validating after 8s
            elif 8 < laptime_curr < 10:
                temp_data.clear()
                validating = False

        # Record map coords
        if recording:
            is_pit_lap |= api.read.vehicle.in_pits()

            # Record sector index
            sector_idx = api.read.lap.sector_index()
            if last_sector_idx != sector_idx:
                if sector_idx == 1:
                    recorder_data.sectors[0] = len(recorder_data.coords) - 1
                elif sector_idx == 2:
                    recorder_data.sectors[1] = len(recorder_data.coords) - 1
                last_sector_idx = sector_idx

            # Record driving path
            # Update if position value is different & positive
            pos_curr = api.read.lap.distance()
            if 0 <= pos_curr != pos_last:
                delta_pos = pos_curr - pos_recorded
                record = delta_pos >= min_node_distance  # further than last node
                if delta_pos > 100:
                    if not recorder_data.coords:  # lap distance of previous lap still read at lap start: wait for its reset
                        record = False
                    elif (delta_pos > MAX_NODE_GAP
                            or delta_pos > (api.read.timing.elapsed() - time_recorded) * MAX_SPEED):
                        # teleported (back to garage, skipped part of lap): lap not recorded
                        recording = False
                        recorder_data.clear()
                        record = False
                    else:  # app or game stalled (busy disk, CPU load) while driving: gap kept in lap
                        lap_gaps += 1
                if record:
                    pos_x = api.read.vehicle.position_longitudinal()
                    pos_y = api.read.vehicle.position_lateral()
                    pos_z = api.read.vehicle.position_vertical()
                    recorder_data.coords.append((pos_x, pos_y))
                    recorder_data.dists.append((pos_curr, pos_z))
                    pos_recorded = pos_curr
                    time_recorded = api.read.timing.elapsed()
                pos_last = pos_curr  # reset last position
