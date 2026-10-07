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
Sectors module
"""

from __future__ import annotations

from .. import realtime_state
from ..api_control import api
from ..const_common import MAX_SECONDS
from ..module_info import SectorData, minfo
from ..userfile.sector_best import load_sector_best_file, save_sector_best_file
from ..validator import generator_init, is_same_session, session_token, valid_sectors
from ._base import MODULE_STOP, DataModule, data_stamp


class Realtime(DataModule):
    """Sectors data"""

    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        _event_wait = self._event.wait
        reset = False
        vehicle_resets = None
        update_interval = self.idle_interval
        last_stamp: tuple = ()  # game data stamp of last update

        gen_record_sectors = record_sectors(
            output_session=minfo.sectors.sessionBest,
            output_alltime=minfo.sectors.allTimeBest,
            filepath=self.cfg.path.sector_best,
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

                    # Run calculation
                    gen_record_sectors.send(vehicle_resets)

                else:
                    if reset:
                        reset = False
                        update_interval = self.idle_interval
        finally:
            # Also save on error exit, as restarted module reloads data from file
            self.save_on_stop(gen_record_sectors)


@generator_init
def record_sectors(output_session: SectorData, output_alltime: SectorData, filepath: str):
    """Record sectors data"""
    last_reset = None  # reset check
    delayed_save = False

    last_sector_idx = -1  # previous recorded sector index value
    combo_name = ""
    session_id: tuple[float, ...] = ()  # session token
    last_lap_stime = -1.0  # last lap start time
    is_bad_lap = False  # lap with pit visit or invalidated by game (no best S1/S2)
    last_lap_bad = False  # lap before current lap was bad (no best S3 nor personal best sectors from it)
    s3_lap_stime = -1.0  # start time of lap last seen in sector 3 (S3 of lap still in progress or just finished)

    while True:
        reset = yield None

        # Reset
        if last_reset != reset:
            # Save data
            if delayed_save:
                save_sector_best_file(
                    filepath=filepath,
                    filename=combo_name,
                    session_id=session_id,
                    session_best_tb=output_session.sectorBestTB,
                    session_best_pb=output_session.sectorBestPB,
                    alltime_best_tb=output_alltime.sectorBestTB,
                    alltime_best_pb=output_alltime.sectorBestPB,
                )
                delayed_save = False

            # Delay reset until driving (module stopping: data saved only)
            if reset is MODULE_STOP or not realtime_state.active:
                continue
            last_reset = reset

            # Load data
            output_session.reset()
            output_alltime.reset()
            last_lap_stime = -1.0
            is_bad_lap = last_lap_bad = False
            s3_lap_stime = -1.0
            combo_name = api.read.session.combo_name()
            session_id = session_token(api.read.session.identifier())
            (
                output_session.sectorBestTB[:],
                output_session.sectorBestPB[:],
                output_alltime.sectorBestTB[:],
                output_alltime.sectorBestPB[:],
            ) = load_sector_best_file(
                filepath=filepath,
                filename=combo_name,
                session_id=session_id,
                defaults=(MAX_SECONDS, MAX_SECONDS, MAX_SECONDS),
            )

        # Pit visit & track limits of lap in progress (flag of lap just completed may stay a moment)
        lap_stime = api.read.timing.start()
        if last_lap_stime != lap_stime:
            last_lap_stime = lap_stime
            last_lap_bad = is_bad_lap  # line crossed: flag of finished lap kept for its S3 (computed later)
            is_bad_lap = False
        is_bad_lap |= api.read.vehicle.in_pits()
        lap_started = api.read.timing.current_laptime() > 1
        if lap_started:
            is_bad_lap |= api.read.lap.invalidated()

        # Update previous & best sector time
        sector_idx = api.read.lap.sector_index()
        if sector_idx == 2 and lap_started:
            s3_lap_stime = lap_stime
        if last_sector_idx != sector_idx:  # keep checking until conditions met

            # Keep session token recent (saved with data), so a game pause is not taken as new session
            new_session_id = session_token(api.read.session.identifier())
            if is_same_session(session_id, new_session_id):
                session_id = new_session_id

            laptime_valid = api.read.timing.last_laptime()
            curr_sector1 = api.read.timing.current_sector1()
            curr_sector2 = api.read.timing.current_sector2()
            last_sector2 = api.read.timing.last_sector2()
            # Lap finished (S3): still lap in progress until game updates lap start time, else lap before
            finished_bad = is_bad_lap if s3_lap_stime == lap_stime else last_lap_bad

            # Session sectors
            last_sector_idx = calc_sector_time(
                output=output_session,
                sector_idx=sector_idx,
                last_sector_idx=last_sector_idx,
                laptime_valid=laptime_valid,
                curr_sector1=curr_sector1,
                curr_sector2=curr_sector2,
                last_sector2=last_sector2,
                is_bad_lap=is_bad_lap,
                is_last_lap_bad=finished_bad,
            )

            # All time sectors
            last_sector_idx = calc_sector_time(
                output=output_alltime,
                sector_idx=sector_idx,
                last_sector_idx=last_sector_idx,
                laptime_valid=laptime_valid,
                curr_sector1=curr_sector1,
                curr_sector2=curr_sector2,
                last_sector2=last_sector2,
                is_bad_lap=is_bad_lap,
                is_last_lap_bad=finished_bad,
            )

            # Save if recorded new valid data
            if not delayed_save and last_sector_idx == sector_idx:
                delayed_save = valid_sectors(output_alltime.sectorPrev)


def calc_sector_time(
    output: SectorData,
    sector_idx: int,
    last_sector_idx: int,
    laptime_valid: float,
    curr_sector1: float,
    curr_sector2: float,
    last_sector2: float,
    is_bad_lap: bool = False,
    is_last_lap_bad: bool = False,
) -> int:
    """Calculate sector time (is_bad_lap: lap in progress, is_last_lap_bad: lap just finished, S3 & personal best
    sectors)"""
    no_delta_sector = None

    prev_s = output.sectorPrev
    delta_s_tb = output.deltaSectorBestTB
    delta_s_pb = output.deltaSectorBestPB
    best_s_tb = output.sectorBestTB
    best_s_pb = output.sectorBestPB

    # While vehicle in S1, update S3 data
    if sector_idx == 0 and laptime_valid > 0 and last_sector2 > 0:
        last_sector_idx = sector_idx  # reset & stop checking

        prev_s[2] = laptime_valid - last_sector2

        # Update (time gap) deltabest bestlap sector 3
        if valid_sectors(best_s_pb[2]):
            delta_s_pb[2] = prev_s[2] - best_s_pb[2]

        # Update deltabest sector 3
        if valid_sectors(best_s_tb[2]):
            delta_s_tb[2] = prev_s[2] - best_s_tb[2]
            no_delta_sector = False
        else:
            no_delta_sector = True

        # Save best sector 3 time (not from pit or invalidated lap)
        if prev_s[2] < best_s_tb[2] and not is_last_lap_bad:
            best_s_tb[2] = prev_s[2]

        # Save sector time from personal best laptime (not from pit or invalidated lap)
        if laptime_valid < sum(best_s_pb) and valid_sectors(prev_s) and not is_last_lap_bad:
            best_s_pb[:] = prev_s

    # While vehicle in S2, update S1 data
    elif sector_idx == 1 and curr_sector1 > 0:
        last_sector_idx = sector_idx  # reset

        prev_s[0] = curr_sector1

        # Update (time gap) deltabest bestlap sector 1
        if valid_sectors(best_s_pb[0]):
            delta_s_pb[0] = prev_s[0] - best_s_pb[0]

        # Update deltabest sector 1
        if valid_sectors(best_s_tb[0]):
            delta_s_tb[0] = prev_s[0] - best_s_tb[0]
            no_delta_sector = False
        else:
            no_delta_sector = True

        # Save best sector 1 time (not from pit or invalidated lap)
        if prev_s[0] < best_s_tb[0] and not is_bad_lap:
            best_s_tb[0] = prev_s[0]

    # While vehicle in S3, update S2 data
    elif sector_idx == 2 and curr_sector2 > 0 and curr_sector1 > 0:
        last_sector_idx = sector_idx  # reset

        prev_s[1] = curr_sector2 - curr_sector1

        # Update (time gap) deltabest bestlap sector 2
        if valid_sectors(best_s_pb[1]):
            delta_s_pb[1] = prev_s[1] - best_s_pb[1]

        # Update deltabest sector 2
        if valid_sectors(best_s_tb[1]):
            delta_s_tb[1] = prev_s[1] - best_s_tb[1]
            no_delta_sector = False
        else:
            no_delta_sector = True

        # Save best sector 2 time (not from pit or invalidated lap)
        if prev_s[1] < best_s_tb[1] and not is_bad_lap:
            best_s_tb[1] = prev_s[1]

    # Output sectors data
    output.sectorIndex = sector_idx
    if no_delta_sector is not None:
        output.noDeltaSector = no_delta_sector

    return last_sector_idx
