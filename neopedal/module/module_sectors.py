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
Sectors module
"""

from __future__ import annotations

from .. import realtime_state
from ..api_control import api
from ..const_common import MAX_SECONDS
from ..module_info import SectorData, minfo
from ..userfile.sector_best import merge_sector_best, read_sector_best_file, save_sector_best_file
from ..validator import generator_init, is_same_session, session_token, valid_sectors
from ._base import PENDING_CHECK, WAIT_STATE_CHANGE, DataModule, PendingLap, data_stamp
from ._lap_state import LOAD, SKIP, LapState


class Realtime(DataModule):
    """Sectors data"""

    __slots__ = ()

    def __init__(self, config, module_name):
        super().__init__(config, module_name)

    def update_data(self):
        """Update module data"""
        _event_wait = self.wait_update  # also wakes on new game data
        reset = False
        vehicle_resets = None
        waiting = False  # completed lap waiting for validation
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
                    waiting = gen_record_sectors.send(vehicle_resets)

                else:
                    reset = False
                    if waiting:  # left track just after line: keep validating lap just completed
                        waiting = gen_record_sectors.send(PENDING_CHECK)
                    # Idle until activity changes, unless a lap waits for validation
                    update_interval = self.idle_interval if waiting else WAIT_STATE_CHANGE
        finally:
            # Also save on error exit, as restarted module reloads data from file
            self.save_on_stop(gen_record_sectors)


@generator_init
def record_sectors(output_session: SectorData, output_alltime: SectorData, filepath: str):
    """Record sectors data

    Sector 3 of lap just completed is set once game updates last lap time. Lap completed just before
    leaving track (reset, inactive: PENDING_CHECK sent) keeps being validated for up to PENDING_WAIT
    seconds before data is saved & reset (MODULE_STOP: last check), so its S3 & personal best sectors
    are not lost. Yields whether a lap is waiting for validation.
    """
    readable = True  # sector file readable at load, False if not accessible (never saved over)

    last_sector_idx = -1  # previous recorded sector index value
    combo_name = ""
    session_id: tuple[float, ...] = ()  # session token
    last_lap_stime = -1.0  # last lap start time
    lap_invalid = False  # lap in progress invalidated by game (no best sector from it)
    sector_pits = [False, False, False]  # pit lane visited in each sector of lap in progress (no best of that sector)
    last_lap_bad = (False, False)  # S3 bad, lap bad of lap before current lap (no best S3, no personal best sectors)
    s3_lap_stime = -1.0  # start time of lap last seen in sector 3 (S3 of lap still in progress or just finished)
    lap_sector2 = -1.0  # sector 1+2 time of lap in sector 3 (lap just finished until its S3 is set), -1 if unknown

    def save_data():
        """Best sectors saved (on reset, module stop & every CHECKPOINT_INTERVAL while driving)"""
        nonlocal readable
        if not readable:  # not accessible at load: best sectors of file kept
            saved, readable = read_sector_best_file(
                filepath=filepath,
                filename=combo_name,
                session_id=session_id,
                defaults=(MAX_SECONDS, MAX_SECONDS, MAX_SECONDS),
            )
            if readable:
                merge_sector_best(output_session.sectorBestTB, output_session.sectorBestPB, *saved[:2])
                merge_sector_best(output_alltime.sectorBestTB, output_alltime.sectorBestPB, *saved[2:])
        if readable:
            save_sector_best_file(
                filepath=filepath,
                filename=combo_name,
                session_id=session_id,
                session_best_tb=output_session.sectorBestTB,
                session_best_pb=output_session.sectorBestPB,
                alltime_best_tb=output_alltime.sectorBestTB,
                alltime_best_pb=output_alltime.sectorBestPB,
            )
            lap_state.delayed_save = False

    def resolved_lap(lap: PendingLap, valid: bool):
        """Set S3 of lap completed before player left track once validated by game"""
        nonlocal last_sector_idx
        if valid:
            laptime_valid = api.read.timing.last_laptime()
            last_sector2 = api.read.timing.last_sector2()
            for output in (output_session, output_alltime):
                last_sector_idx = calc_sector_time(
                    output=output,
                    sector_idx=0,
                    last_sector_idx=last_sector_idx,
                    laptime_valid=laptime_valid,
                    curr_sector1=-1.0,
                    curr_sector2=-1.0,
                    last_sector2=last_sector2,
                    is_last_s3_bad=lap.data[0],
                    is_last_lap_bad=lap.data[1],
                )
            if not lap_state.delayed_save and last_sector_idx == 0:
                lap_state.delayed_save = valid_sectors(output_alltime.sectorPrev)

    # Lap waiting for its S3, best sectors saved on reset & checkpoints
    lap_state = LapState(resolved_lap, save_data, checkpoint=True)

    while True:
        step = lap_state.receive((yield lap_state.pending is not None))
        if step == SKIP:
            continue

        # Reset (data saved, then loaded once driving)
        if step == LOAD:
            # Load data (laps not saved, file not accessible: discarded, file kept)
            output_session.reset()
            output_alltime.reset()
            last_sector_idx = -1  # sector index of reset outputs (-1) set again from current sector
            last_lap_stime = -1.0
            lap_invalid = False
            sector_pits[:] = (False, False, False)
            last_lap_bad = (False, False)
            s3_lap_stime = -1.0
            lap_sector2 = -1.0
            combo_name = api.read.session.combo_name()
            session_id = session_token(api.read.session.identifier())
            (
                output_session.sectorBestTB[:],
                output_session.sectorBestPB[:],
                output_alltime.sectorBestTB[:],
                output_alltime.sectorBestPB[:],
            ), readable = read_sector_best_file(
                filepath=filepath,
                filename=combo_name,
                session_id=session_id,
                defaults=(MAX_SECONDS, MAX_SECONDS, MAX_SECONDS),
                backup=True,  # own sector file, replaced by next save
            )

        # Pit visit (per sector: out & in lap sectors on track still count) & track limits of lap in progress
        # (flag of lap just completed may stay a moment)
        lap_stime = api.read.timing.start()
        if last_lap_stime != lap_stime:
            lap_flags = (lap_invalid or sector_pits[2], lap_invalid or any(sector_pits))
            # Line crossed after sector 3 of lap (not back to garage): lap kept until its S3 is set
            if lap_state.pending is None and 0 <= s3_lap_stime == last_lap_stime < lap_stime and last_sector_idx == 2:
                lap_state.pending = PendingLap(lap_stime - last_lap_stime, lap_stime, lap_flags)
            last_lap_stime = lap_stime
            last_lap_bad = lap_flags  # line crossed: flags of finished lap kept for its S3 (computed later)
            lap_invalid = False
            sector_pits[:] = (False, False, False)
        pending = lap_state.pending
        if pending is not None and not pending.deadline and api.read.timing.elapsed() - pending.finish > 10:
            lap_state.pending = None  # no S3 for lap just completed (no valid lap time)
        lap_started = api.read.timing.current_laptime() > 1
        if lap_started:
            lap_invalid |= api.read.lap.invalidated()

        # Update previous & best sector time
        sector_idx = api.read.lap.sector_index()
        if api.read.vehicle.in_pits():
            # Sector index of lap before may stay a moment after line: start of lap is in S1
            sector_pits[sector_idx if lap_started else 0] = True
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
            # Lap finished: game last lap data still of lap before (sector index reported first) never taken as S3
            if sector_idx == 0 and lap_sector2 > 0 and abs(last_sector2 - lap_sector2) > 0.001:
                laptime_valid = -1.0
            # Lap finished (S3): still lap in progress until game updates lap start time, else lap before
            if s3_lap_stime == lap_stime:
                finished_s3_bad, finished_bad = lap_invalid or sector_pits[2], lap_invalid or any(sector_pits)
            else:
                finished_s3_bad, finished_bad = last_lap_bad
            # S1 (in S2) or S2 (in S3) just finished
            sector_bad = lap_invalid or sector_pits[sector_idx - 1]

            # Session sectors
            last_sector_idx = calc_sector_time(
                output=output_session,
                sector_idx=sector_idx,
                last_sector_idx=last_sector_idx,
                laptime_valid=laptime_valid,
                curr_sector1=curr_sector1,
                curr_sector2=curr_sector2,
                last_sector2=last_sector2,
                is_bad_sector=sector_bad,
                is_last_s3_bad=finished_s3_bad,
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
                is_bad_sector=sector_bad,
                is_last_s3_bad=finished_s3_bad,
                is_last_lap_bad=finished_bad,
            )

            if last_sector_idx == sector_idx:  # sector just finished recorded
                lap_sector2 = curr_sector2 if sector_idx == 2 else -1.0
                # Save if recorded new valid data
                if not lap_state.delayed_save:
                    lap_state.delayed_save = valid_sectors(output_alltime.sectorPrev)

            # S3 of lap just completed set (sector 1), or skipped (sector 2 of next lap)
            if lap_state.pending is not None and last_sector_idx == sector_idx != 2:
                lap_state.pending = None


def calc_sector_time(
    output: SectorData,
    sector_idx: int,
    last_sector_idx: int,
    laptime_valid: float,
    curr_sector1: float,
    curr_sector2: float,
    last_sector2: float,
    is_bad_sector: bool = False,
    is_last_s3_bad: bool = False,
    is_last_lap_bad: bool = False,
) -> int:
    """Calculate sector time (is_bad_sector: S1 or S2 just finished, is_last_s3_bad: S3 of lap just finished,
    is_last_lap_bad: lap just finished, personal best sectors; bad = pit visit or invalidated by game)"""
    no_delta_sector = None
    no_delta_pb = None

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
        no_delta_pb = not valid_sectors(best_s_pb[2])
        if not no_delta_pb:
            delta_s_pb[2] = prev_s[2] - best_s_pb[2]

        # Update deltabest sector 3
        if valid_sectors(best_s_tb[2]):
            delta_s_tb[2] = prev_s[2] - best_s_tb[2]
            no_delta_sector = False
        else:
            no_delta_sector = True

        # Save best sector 3 time (not from pit or invalidated lap)
        if prev_s[2] < best_s_tb[2] and not is_last_s3_bad:
            best_s_tb[2] = prev_s[2]

        # Save sector time from personal best laptime (not from pit or invalidated lap), all sectors of this lap
        # (sum is lap time: S1 & S2 not missed)
        if (laptime_valid < sum(best_s_pb) and valid_sectors(prev_s) and not is_last_lap_bad
                and abs(sum(prev_s) - laptime_valid) < 0.002):
            best_s_pb[:] = prev_s

    # While vehicle in S2, update S1 data
    elif sector_idx == 1 and curr_sector1 > 0:
        last_sector_idx = sector_idx  # reset

        prev_s[0] = curr_sector1

        # Update (time gap) deltabest bestlap sector 1
        no_delta_pb = not valid_sectors(best_s_pb[0])
        if not no_delta_pb:
            delta_s_pb[0] = prev_s[0] - best_s_pb[0]

        # Update deltabest sector 1
        if valid_sectors(best_s_tb[0]):
            delta_s_tb[0] = prev_s[0] - best_s_tb[0]
            no_delta_sector = False
        else:
            no_delta_sector = True

        # Save best sector 1 time (not from pit or invalidated lap)
        if prev_s[0] < best_s_tb[0] and not is_bad_sector:
            best_s_tb[0] = prev_s[0]

    # While vehicle in S3, update S2 data
    elif sector_idx == 2 and curr_sector2 > 0 and curr_sector1 > 0:
        last_sector_idx = sector_idx  # reset

        prev_s[1] = curr_sector2 - curr_sector1

        # Update (time gap) deltabest bestlap sector 2
        no_delta_pb = not valid_sectors(best_s_pb[1])
        if not no_delta_pb:
            delta_s_pb[1] = prev_s[1] - best_s_pb[1]

        # Update deltabest sector 2
        if valid_sectors(best_s_tb[1]):
            delta_s_tb[1] = prev_s[1] - best_s_tb[1]
            no_delta_sector = False
        else:
            no_delta_sector = True

        # Save best sector 2 time (not from pit or invalidated lap)
        if prev_s[1] < best_s_tb[1] and not is_bad_sector:
            best_s_tb[1] = prev_s[1]

    # Output sectors data
    if no_delta_sector is not None:
        output.noDeltaSector = no_delta_sector
    if no_delta_pb is not None:
        output.noDeltaSectorPB = no_delta_pb
    output.recordedIndex = last_sector_idx
    output.sectorIndex = sector_idx

    return last_sector_idx
