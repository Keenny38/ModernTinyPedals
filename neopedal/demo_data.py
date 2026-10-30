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
Simulated race data: overlay pictures of the app (Overlays page, Overlay Options, setup wizard)
and of the repo (tools/make_readme_preview.py, tools/make_change_visual.py)

A GT3 car at speed mid race at Road Atlanta, in a 20 car multi-class field. Game data comes from
a zeroed LMU shared memory filled here (never connected to the game); data modules do not run,
so their outputs (module info) are filled directly. The track path is a recorded lap, downsampled.

Widgets read game data through `api.read` and module outputs through `minfo`, globals of each
widget module. While a picture is drawn, `demo_globals` points those globals of widget modules to
a simulated session, then puts the real ones back. Pictures are drawn on the UI thread, like
running overlays, so overlays never see simulated values; data modules (own threads, own module
globals) never do either.
"""

from __future__ import annotations

import math
import sys
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from PySide6.QtCore import QTimerEvent

from pyLMUSharedMemory import lmu_data

from . import api_connector
from .const_common import MAX_SECONDS, SECTOR_FLAG_ORDER
from .demo_state import demo_drawing
from .module_info import ConsumptionDataSet, ModuleInfo, StintDataSet, TrackMap, VehicleDataSet
from .penalty_info import NO_PENALTY, Penalty
from .process.weather import WeatherNode
from .template.widget.registry import DEMO_GAPS, DEMO_HISTORY, DEMO_LAP, DEMO_SAMPLE, demo_names

KELVIN = 273.15

# Session state
TRACK_NAME = "Michelin Raceway Road Atlanta"
TRACK_LENGTH = 4083.5
TRACK_SECTORS = (22, 111)  # indexes of sector lines in track points
LAP_DISTANCE = 1460.0  # player position into lap (meters)
ELAPSED = 2 * 3600 + 1250.0
LAP_START = ELAPSED - 31.4
PLAYER_LAPS = 72
PLAYER_BEST = 84.912
PLAYER_LAST = 85.274

# Field: driver, vehicle, class, best lap. Order is the running order (overall position).
FIELD = (
    ("M. Laurent", "Ferrari 499P", "Hyper", 72.84),
    ("J. Hartmann", "Porsche 963", "Hyper", 72.97),
    ("K. Tanaka", "Toyota GR010", "Hyper", 73.05),
    ("S. Dubois", "Alpine A424", "Hyper", 73.21),
    ("R. Costa", "Cadillac V-Series.R", "Hyper", 73.30),
    ("L. Becker", "BMW M Hybrid V8", "Hyper", 73.48),
    ("A. Rossi", "Peugeot 9X8", "Hyper", 73.66),
    ("T. Novak", "Oreca 07", "LMP2", 76.92),
    ("E. Walsh", "Oreca 07", "LMP2", 77.05),
    ("P. Moreau", "Oreca 07", "LMP2", 77.31),
    ("D. Silva", "Oreca 07", "LMP2", 77.48),
    ("N. Fischer", "Ferrari 296 GT3", "GT3", 84.71),
    ("C. Bennett", "Porsche 911 GT3 R", "GT3", 84.83),
    ("You", "McLaren 720S GT3 Evo", "GT3", PLAYER_BEST),  # player
    ("H. Lindqvist", "BMW M4 GT3", "GT3", 85.02),
    ("G. Romano", "Aston Martin Vantage AMR", "GT3", 85.16),
    ("I. Kowalski", "Lexus RC F GT3", "GT3", 85.31),
    ("F. Martin", "Corvette Z06 GT3.R", "GT3", 85.44),
    ("V. Petrov", "Ford Mustang GT3", "GT3", 85.62),
    ("B. Clarke", "Lamborghini Huracan GT3", "GT3", 85.79),
)
PLAYER = 13
# Lap distance of each car (meters), around the player, so the radar, relative and map have traffic
CAR_DISTANCE = {
    PLAYER - 1: LAP_DISTANCE + 7.5, PLAYER + 1: LAP_DISTANCE - 6.5, 9: LAP_DISTANCE - 70,
    PLAYER - 2: LAP_DISTANCE + 160, PLAYER + 2: LAP_DISTANCE - 210,
}

HISTORY_WIDGETS = demo_names(DEMO_HISTORY)  # draw recent inputs: fed a corner before drawn
HISTORY_FRAMES = 150
LAP_WIDGETS = demo_names(DEMO_LAP)  # draw delta over the lap: fed last lap and current lap so far
LAP_FRAMES = 60  # per lap
DELTA_SOURCES = ("deltaBest", "deltaSession", "deltaStint", "deltaLast")
GAP_WIDGETS = demo_names(DEMO_GAPS)  # draw gaps per lap: fed gaps at end of last laps
GAP_LAPS = 8  # laps fed before current one (gap trend default number_of_laps)
UPDATES = 3  # updates before a picture, so smoothed values settle
# Widgets drawing a sample of every item before their first update (nothing to show on this data),
# feeds of widgets declared in template.widget.registry.OVERLAYS
SAMPLE_WIDGETS = frozenset(demo_names(DEMO_SAMPLE))
# Corner coach: corners of reference lap (official number, start, apex, end, braking point or -1, minimum speed km/h)
# & last corner driven (official number, minimum speed, reference minimum speed)
COACH_CORNERS = (
    ("1", 300.0, 490.0, 640.0, 345.0, 112.0), ("2", 640.0, 740.0, 860.0, -1.0, 158.0),
    ("3", 860.0, 950.0, 1030.0, 880.0, 131.0), ("4", 1030.0, 1105.0, 1250.0, -1.0, 165.0),
    ("5", 1250.0, 1405.0, 1700.0, 1300.0, 98.0), ("6", 1700.0, 1985.0, 2080.0, 1845.0, 104.0),
    ("7", 2080.0, 2155.0, 2700.0, 2095.0, 82.0), ("10a", 2700.0, 3515.0, 3545.0, 3400.0, 89.0),
    ("10b", 3545.0, 3575.0, 3700.0, -1.0, 95.0), ("11", 3700.0, 3758.0, 3860.0, -1.0, 175.0),
    ("12", 3860.0, 3925.0, 4080.0, 3870.0, 141.0),
)
COACH_LAST = ("5", 95.0, 98.0)


def tyre_temperature_trend(temperature: float, count: int) -> tuple[float, ...]:
    """Surface temperature samples of a tyre (Celsius, oldest first) ending at its simulated temperature: tyre
    warming up, then steady with corner peaks (tyre temperature trend, fed by the overlay itself)"""
    last = max(count - 1, 1)
    return tuple(round(temperature - 16 * (1 - step / last) ** 3 + 1.8 * math.sin(5 * math.pi * step / last), 1)
                 for step in range(count))


def car_distance(index: int) -> float:
    """Lap distance of a car (meters)"""
    return CAR_DISTANCE.get(index, (LAP_DISTANCE + (PLAYER - index) * 330) % TRACK_LENGTH)


def track_position(distance: float) -> tuple[float, float, float, float]:
    """World x, y, elevation and heading (radians) at lap distance"""
    points = TRACK_POINTS
    distance %= TRACK_LENGTH
    for index in range(1, len(points)):
        if points[index][0] >= distance:
            break
    d0, x0, y0, z0 = points[index - 1]
    d1, x1, y1, z1 = points[index]
    ratio = (distance - d0) / max(d1 - d0, 0.01)
    heading = math.atan2(y1 - y0, x1 - x0)
    return x0 + (x1 - x0) * ratio, y0 + (y1 - y0) * ratio, z0 + (z1 - z0) * ratio, heading


def lmu_api() -> tuple[api_connector.SimLMU, Any]:
    """LMU API on zeroed shared memory (never connected), player at index 0"""
    sim = api_connector.SimLMU()
    info = sim._shmmapi
    data = lmu_data.LMUObjectOut()
    info._shmm.data = data
    info._sync.player_scor = data.scoring.vehScoringInfo[0]
    info._sync.player_tele = data.telemetry.telemInfo[0]
    info._sync.player_scor_index = 0
    # Telemetry matched by slot id as update thread would do (same id & index)
    info._sync._tele_indexes = {index: index for index in range(128)}
    return sim, data


def set_telemetry(sim, data):
    """Player car: GT3 at speed, exiting a fast corner"""
    tele = data.telemetry.telemInfo[PLAYER]
    tele.mElapsedTime = ELAPSED
    tele.mLapNumber = PLAYER_LAPS  # LMU: same as completed laps (recorded sessions)
    tele.mLapStartET = LAP_START
    tele.mVehicleName = b"McLaren 720S GT3 Evo #59"
    tele.mVehicleModel = b"McLaren 720S GT3 Evo"
    tele.mTrackName = TRACK_NAME.encode()
    pos_x, pos_y, pos_z, heading = track_position(LAP_DISTANCE)
    tele.mPos.x, tele.mPos.y, tele.mPos.z = pos_x, pos_z, -pos_y
    tele.mOri[2].x, tele.mOri[2].z = math.sin(heading), math.cos(heading)
    tele.mOri[0].x, tele.mOri[0].z = math.cos(heading), -math.sin(heading)
    tele.mOri[1].y = 1.0
    tele.mLocalVel.z = -58.0  # m/s, about 209 km/h
    tele.mLocalVel.x = 0.6
    tele.mLocalAccel.x = 11.8  # lateral, about 1.2 g
    tele.mLocalAccel.z = -3.4
    tele.mLocalRot.y = 0.21
    tele.mGear = 5
    tele.mMaxGears = 6
    tele.mEngineRPM = 7150
    tele.mIgnitionStarter = 1  # engine running (ignition off reads as engine off)
    tele.mEngineMaxRPM = 8250
    tele.mEngineTorque = 612
    tele.mTurboBoostPressure = 1.85 * 100000
    tele.mEngineOilTemp = 104.2
    tele.mEngineWaterTemp = 88.6
    tele.mUnfilteredThrottle = tele.mFilteredThrottle = 0.92
    tele.mUnfilteredBrake = tele.mFilteredBrake = 0.0
    tele.mUnfilteredClutch = tele.mFilteredClutch = 0.0
    tele.mUnfilteredSteering = tele.mFilteredSteering = -0.11
    tele.mSteeringShaftTorque = -6.4
    tele.mPhysicalSteeringWheelRange = tele.mVisualSteeringWheelRange = 480
    tele.mFront3rdDeflection = 0.012
    tele.mRear3rdDeflection = 0.016
    tele.mFrontRideHeight = 0.052
    tele.mRearRideHeight = 0.071
    tele.mFrontDownforce = 3150
    tele.mRearDownforce = 3880
    tele.mDrag = 2150
    tele.mFuel = 42.3
    tele.mFuelCapacity = 120.0
    tele.mRearBrakeBias = 0.438
    tele.mHeadlights = False
    tele.mCurrentSector = 1
    tele.mTC = 4
    tele.mTCMax = 11
    tele.mTCSlip = 3
    tele.mTCSlipMax = 10
    tele.mTCCut = 5
    tele.mTCCutMax = 10
    tele.mABS = 6
    tele.mABSMax = 11
    tele.mMotorMap = 2
    tele.mMotorMapMax = 5
    tele.mMigration = 3
    tele.mMigrationMax = 7
    tele.mFrontAntiSway = 4
    tele.mFrontAntiSwayMax = 8
    tele.mRearAntiSway = 3
    tele.mRearAntiSwayMax = 8
    tele.mLiftAndCoastProgress = 0
    tele.mTrackLimitsSteps = 2
    tele.mVirtualEnergy = 0.58
    tele.mDeltaBest = -0.284
    tele.mBatteryChargeFraction = 0.64
    tele.mElectricBoostMotorState = 2
    tele.mElectricBoostMotorTorque = 142
    tele.mElectricBoostMotorRPM = 11800
    tele.mElectricBoostMotorTemperature = 61.5
    tele.mElectricBoostWaterTemperature = 48.2
    tele.mRegen = -175.5  # kW, negative while deploying
    tele.mStateOfCharge = 64.0  # same as battery charge
    for index in range(4):
        wheel = tele.mWheels[index]
        front = index < 2
        left = index % 2 == 0
        wheel.mBrakeTemp = KELVIN + (432 if front else 365) + index * 7
        wheel.mBrakePressure = 0.0
        wheel.mPressure = (176.4 if front else 172.8) + index * 0.4
        wheel.mWear = (0.91 if front else 0.94) - index * 0.006
        wheel.mTireLoad = (4120 if front else 4870) + (850 if not left else -650)
        wheel.mSuspForce = (6400 if front else 7900) + (900 if not left else -700)
        wheel.mSuspensionDeflection = (0.028 if front else 0.034) + (0.006 if not left else -0.004)
        wheel.mRideHeight = (0.051 if front else 0.072) + (-0.004 if not left else 0.003)
        wheel.mRotation = -(58.0 + index * 0.25) / 0.34 * (1.0 if front else 1.012)
        wheel.mLateralPatchVel = 0.9 + index * 0.15
        wheel.mLongitudinalPatchVel = -0.4 - index * 0.2
        wheel.mLateralGroundVel = 0.6
        wheel.mLongitudinalGroundVel = -58.0
        wheel.mCamber = (-0.064 if front else -0.045) * (1 if left else -1)
        wheel.mToe = (0.002 if front else -0.003) * (1 if left else -1)
        wheel.mStaticUndeflectedRadius = 34
        wheel.mVerticalTireDeflection = 0.0118 + index * 0.0006
        wheel.mCompoundType = 1  # medium
        wheel.mOptimalTemp = 85
        base = (86 if front else 82) + (5 if not left else 0)
        for layer in range(3):  # left, center, right seen from car: inner edge hottest (right of left tyres)
            inward = layer if left else 2 - layer  # 2 at inner edge
            wheel.mTemperature[layer] = KELVIN + base + inward * 2.5
            wheel.mTireInnerLayerTemperature[layer] = KELVIN + base + 4 + inward * 1.5
        wheel.mTireCarcassTemperature = KELVIN + base + 2
        wheel.mSurfaceType = 0
    tele.mFrontTireCompoundIndex = tele.mRearTireCompoundIndex = 1
    tele.mFrontTireCompoundName = tele.mRearTireCompoundName = b"Medium"

    scoring = data.scoring.scoringInfo
    scoring.mTrackName = TRACK_NAME.encode()
    scoring.mNumVehicles = len(FIELD)
    scoring.mLapDist = TRACK_LENGTH
    scoring.mSession = 10  # race
    scoring.mGamePhase = 5  # green flag
    scoring.mCurrentET = ELAPSED
    scoring.mEndET = 6 * 3600
    scoring.mMaxLaps = 2147483647
    scoring.mStartET = 13 * 3600
    scoring.mTimeOfDay = 15 * 3600 + 47 * 60
    scoring.mTrackTemp = 31.5
    scoring.mAmbientTemp = 22.0
    scoring.mRaining = 0.0
    scoring.mDarkCloud = 0.2
    scoring.mCloudCoverage = 3
    scoring.mMinPathWetness = scoring.mMaxPathWetness = scoring.mAvgPathWetness = 0.0
    scoring.mTrackGripLevel = 4
    scoring.mWind.x, scoring.mWind.z = 3.0, -2.0  # light breeze (3.6 m/s)
    scoring.mTrackLimitsStepsPerPoint = 2
    scoring.mTrackLimitsStepsPerPenalty = 8
    for index, (driver, vehicle, vclass, best) in enumerate(FIELD):
        veh = data.scoring.vehScoringInfo[index]
        is_player = index == PLAYER
        veh.mID = index
        veh.mIsPlayer = is_player
        veh.mDriverName = driver.encode()
        veh.mVehicleName = f"{vehicle} #{10 + index * 3}".encode()
        veh.mVehicleClass = vclass.encode()
        veh.mPlace = index + 1
        veh.mTotalLaps = PLAYER_LAPS + (2 if vclass == "Hyper" else 1 if vclass == "LMP2" else 0)
        veh.mBestLapTime = best
        veh.mLastLapTime = best + 0.35 + (index % 4) * 0.08
        veh.mBestSector1 = best * 0.122
        veh.mBestSector2 = best * 0.649
        veh.mLastSector1 = best * 0.123
        veh.mLastSector2 = best * 0.651
        veh.mCurSector1 = best * 0.1225
        veh.mLapDist = car_distance(index)
        veh.mLapStartET = LAP_START - (PLAYER - index) * 1.6
        veh.mNumPitstops = 2 if index % 3 else 3
        veh.mInPits = False
        veh.mPitState = 0
        veh.mSector = 2
        veh.mEstimatedLapTime = best + 0.6
        veh.mTimeIntoLap = veh.mLapDist / TRACK_LENGTH * veh.mEstimatedLapTime
        veh.mTimeBehindLeader = index * 4.9
        veh.mTimeBehindNext = 4.9 if index else 0.0
        veh.mQualification = index + 1 + (1 if index % 3 == 1 else -1 if index % 3 == 2 else 0)
        veh.mFuelFraction = 46 + (index * 7) % 30
        veh.mFlag = 0
        veh.mCountLapFlag = 2
        veh.mServerScored = 1
        veh.mControl = 0 if is_player else 1
    player = data.scoring.vehScoringInfo[PLAYER]
    player.mLastLapTime = PLAYER_LAST
    player.mLapStartET = LAP_START

    for index in range(len(FIELD)):
        data.telemetry.telemInfo[index].mID = index
    sync = sim._shmmapi._sync
    sync.player_scor = data.scoring.vehScoringInfo[PLAYER]
    sync.player_tele = tele
    sync.player_scor_index = PLAYER

    rest = sim._restapi_dataset
    rest.maxVirtualEnergy = 900.0
    rest.brakeWear = (0.0312, 0.0309, 0.0288, 0.0291)
    rest.suspensionDamage = (0.0, 0.0, 0.0, 0.0)
    rest.aeroDamage = 0.0
    rest.steeringWheelRange = 480.0
    rest.pitStopTime = 31.6
    rest.absoluteRefill = 68.0
    rest.forecastRace = (
        WeatherNode(0.0, 2, 22.0, 0.0),
        WeatherNode(0.25, 3, 23.0, 0.05),
        WeatherNode(0.5, 4, 22.0, 0.2),
        WeatherNode(0.75, 6, 20.0, 0.45),
        WeatherNode(1.0, 5, 19.0, 0.3),
    )


def vehicles_info(read, size: int, plr_index: int) -> tuple[list, list, list, list]:
    """Relative lists, classes & draw order, as module_relative.get_vehicles_info makes them from
    game data (no car in pits nor garage here), without its buffers shared with the module thread"""
    laptime_est = read.timing.estimated_laptime()
    plr_time = read.timing.estimated_time_into()
    relative_ahead = []
    relative_behind = []
    classes = []
    for index in range(size):
        if index != plr_index and laptime_est:
            diff_time = read.timing.estimated_time_into(index) - plr_time
            diff_time_ahead = diff_time_behind = diff_time - diff_time // laptime_est * laptime_est
            if diff_time_ahead < 0:
                diff_time_ahead += laptime_est
            if diff_time_behind > 0:
                diff_time_behind -= laptime_est
            relative_ahead.append((diff_time_ahead, index))
            relative_behind.append((diff_time_behind, index))
        laptime_best = read.timing.best_laptime(index)
        laptime_last = read.timing.last_laptime(index)
        classes.append((
            read.vehicle.class_name(index),
            read.vehicle.place(index),
            index,
            laptime_best if laptime_best > 0 else MAX_SECONDS,
            laptime_last if laptime_last > 0 else MAX_SECONDS,
        ))
    # Draw order: leader last, then player
    draw_order = list(range(size))
    leader_index = next((index for index in range(size) if read.vehicle.place(index) == 1), 0)
    if leader_index != draw_order[-1]:
        leader_pos = draw_order.index(leader_index)
        draw_order[leader_pos], draw_order[-1] = draw_order[-1], draw_order[leader_pos]
    if plr_index != leader_index:
        player_pos = draw_order.index(plr_index)
        draw_order[player_pos], draw_order[-2] = draw_order[-2], draw_order[player_pos]
    relative_ahead.sort(reverse=True)
    relative_behind.sort(reverse=True)
    classes.sort()
    return relative_ahead, relative_behind, classes, draw_order


SECTOR_SHARES = (0.33, 0.35, 0.32)  # demo lap split into sectors


def set_demo_sectors(data, index: int, best: float):
    """Sector times of demo car: last lap, sectors of lap being driven, personal bests"""
    sectors = data.sectors
    sectors.best = [best * share - (index % 3) * 0.02 for share in SECTOR_SHARES]
    if index == PLAYER:  # player holds best S1 of class (purple in track map & driver lists)
        sectors.best[0] -= 1.0
    # Last lap: some sectors are personal bests (green, purple when best of session), others slower (yellow)
    sectors.last = tuple(sectors.best[number] if (index + number) % 3 == 0 else data.lastLapTime * share
                         for number, share in enumerate(SECTOR_SHARES))
    sectors.sector = (index + 1) % 3
    first = sectors.best[0] if index % 2 else sectors.best[0] + 0.15  # S1 being driven: personal best or slower
    sectors.current = (first if sectors.sector >= 1 else 0.0, sectors.best[1] + 0.2 if sectors.sector == 2 else 0.0)
    sectors.laps = PLAYER_LAPS
    # Running lap time: line just crossed in S1 (completed lap shown), else completed sectors & half of next one
    data.lapStartTime = ELAPSED - (2.5 if sectors.sector == 0 else
                                   sum(sectors.current[:sectors.sector]) + sectors.best[sectors.sector] * 0.5)


def demo_class_best_sectors(cars) -> None:
    """Best sectors & best lap of each class told to its cars"""
    from .module_info import set_class_bests

    set_class_bests(cars)


def set_vehicles(minfo: ModuleInfo, standings: Mapping[str, Any], read):
    """Vehicles and relative module outputs: full field, consistent with scoring data

    Args:
        minfo: module info filled.
        standings: Standings widget setting (vehicles per class split).
        read: reader of simulated game data.
    """
    from .module.module_relative import standings_index, standings_limits, update_position_in_class

    vehicles = minfo.vehicles
    size = len(FIELD)
    vehicles.dataSet = tuple(VehicleDataSet() for _ in range(size))
    vehicles.totalVehicles = size
    vehicles.playerIndex = PLAYER
    vehicles.leaderIndex = 0
    vehicles.leaderBestLapTime = FIELD[0][3]
    vehicles.totalCompletedLaps = size * PLAYER_LAPS
    vehicles.dataSetVersion = 1
    class_leader: dict[str, int] = {}
    class_members: dict[str, list[int]] = {}
    for index, (_, _, vclass, _) in enumerate(FIELD):
        class_leader.setdefault(vclass, index)
        class_members.setdefault(vclass, []).append(index)
    plr_x, plr_y, _, plr_heading = track_position(LAP_DISTANCE)
    for index, (driver, vehicle, vclass, best) in enumerate(FIELD):
        data = vehicles.dataSet[index]
        members = class_members[vclass]
        place_in_class = members.index(index) + 1
        distance = car_distance(index)
        laps = PLAYER_LAPS + (2 if vclass == "Hyper" else 1 if vclass == "LMP2" else 0)
        data.isPlayer = index == PLAYER
        data.elapsedTime = ELAPSED
        data.speed = 58.0 - (index % 5) * 1.5
        data.positionOverall = index + 1
        data.positionInClass = place_in_class
        data.qualifyOverall = index + 1 + (1 if index % 3 == 1 else -1 if index % 3 == 2 else 0)
        data.qualifyInClass = max(place_in_class + (1 if index % 3 == 1 else -1 if index % 3 == 2 else 0), 1)
        data.driverName = driver
        data.vehicleName = f"{vehicle} #{10 + index * 3}"
        data.vehicleBrand = vehicle.split()[0]
        data.vehicleClass = vclass
        data.classLeaderIndex = class_leader[vclass]
        data.classAheadIndex = members[place_in_class - 2] if place_in_class > 1 else -1
        data.classBehindIndex = members[place_in_class] if place_in_class < len(members) else -1
        data.classBestLapTime = FIELD[class_leader[vclass]][3]
        data.bestLapTime = best
        data.lastLapTime = PLAYER_LAST if data.isPlayer else best + 0.35 + (index % 4) * 0.08
        data.currentLapProgress = distance / TRACK_LENGTH
        data.totalLapProgress = laps + data.currentLapProgress
        data.gapBehindNext = 0.0 if index == 0 else 1.2 + (index * 7 % 11) * 0.35
        data.gapBehindLeader = 0.0 if index == 0 else (1 if vclass == "GT3" else 0) or index * 4.9
        leader = class_leader[vclass]
        data.gapBehindNextInClass = 0.0 if index == leader else 1.4 + (index % 4) * 0.6
        data.gapBehindLeaderInClass = (index - leader) * 2.3
        data.isLapped = 0 if vclass == "GT3" else (-1 if vclass == "Hyper" else 0)
        data.isValidLap = True
        data.inPit = 0
        data.isClassFastestLastLap = index in (0, 7, 12)
        data.numPitStops = -1 if index == 9 else 2 if index % 3 else 3  # car 10: stop & go to serve
        data.penalty = Penalty(1, "Stop/Go", 10) if index == 9 else NO_PENALTY
        data.pitRequested = index == 16
        data.tireCompoundName = (f"{vclass} - Medium",) * 4 if index % 4 else (f"{vclass} - Soft",) * 4
        data.vehicleIntegrity = 1.0 if index not in (5, 17) else 0.86
        data.incidents = (index * 3) % 7
        data.trackLimitsPoints = (0.0, 0.5, 0.0, 1.75, 4.5)[index % 5]
        data.energyRemaining = 0.32 + (index * 13 % 50) / 100
        data.currentStintLaps = 11 + index % 6
        data.estimatedStintLaps = 26 + index % 5
        data.speedTrap.speed = (79.5 if vclass == "Hyper" else 77.0 if vclass == "LMP2" else 74.6) + (index % 4) * 0.3
        data.licoTimer.elapsed = 0.0 if vclass == "GT3" else 1.4 + (index % 3) * 0.6
        data.pitTimer.laps = data.currentStintLaps
        data.fuelHistory.used = 0.031
        data.fuelHistory.laps = 14.5
        for lap in range(5):
            data.lapTimeHistory[lap] = best + 0.25 + ((index + lap) * 37 % 9) * 0.06
        data.lapTimeHistory.best = best
        data.lapTimeHistory.last = data.lastLapTime
        data.lapTimeHistory.average = best + 0.42
        set_demo_sectors(data, index, best)
        world_x, world_y, _, heading = track_position(distance)
        data.worldPositionX = world_x
        data.worldPositionY = world_y
        data.relativeOrientationRadians = heading - plr_heading
        # Position relative to the player, in the player's rotated frame (+Y behind)
        dx, dy = world_x - plr_x, world_y - plr_y
        rot = plr_heading - math.pi / 2
        data.relativeRotatedPositionX = dx * math.cos(rot) + dy * math.sin(rot)
        data.relativeRotatedPositionY = dx * math.sin(rot) - dy * math.cos(rot)
        data.relativeStraightDistance = math.hypot(dx, dy)
    demo_class_best_sectors(vehicles.dataSet[:len(FIELD)])
    # Radar: a car just ahead on the left, one close behind on the right
    vehicles.dataSet[PLAYER - 1].relativeRotatedPositionX = -2.4
    vehicles.dataSet[PLAYER - 1].relativeRotatedPositionY = -7.5
    vehicles.dataSet[PLAYER - 1].relativeOrientationRadians = 0.04
    vehicles.dataSet[PLAYER + 1].relativeRotatedPositionX = 1.3
    vehicles.dataSet[PLAYER + 1].relativeRotatedPositionY = 6.5
    vehicles.dataSet[PLAYER + 1].relativeOrientationRadians = -0.05
    vehicles.nearestLine = 6.9
    vehicles.nearestTraffic = 1.1
    vehicles.nearestBlueClass = ""
    vehicles.nearestBlueGap = 1.1

    # Relative lists, standings (display mode of standings options) and draw order, as the relative module
    # computes them
    relative = minfo.relative
    relative.relativeAhead, relative.relativeBehind, classes, relative.drawOrder = vehicles_info(read, size, PLAYER)
    plr_class, plr_class_place = update_position_in_class(classes, PLAYER, vehicles.dataSet)
    relative.standings = standings_index(
        standings_limits(standings), classes, PLAYER + 1, plr_class, plr_class_place, is_multi_class=True)


def set_modules(minfo: ModuleInfo):
    """Data module outputs the widgets read"""
    delta = minfo.delta
    delta.deltaBest = -0.284
    delta.lapTimeCurrent = 31.4
    delta.lapTimeLast = PLAYER_LAST
    delta.lapTimeBest = PLAYER_BEST
    delta.lapTimeEstimated = PLAYER_BEST - 0.284
    delta.lapTimeSession = PLAYER_BEST
    delta.lapTimeStint = 85.02
    delta.deltaLast = -0.646
    delta.deltaSession = -0.284
    delta.deltaStint = -0.392
    delta.lapTimePace = 85.08
    delta.isValidLap = True
    delta.isDeltaAvailable = True  # reference laps recorded, current lap comparable
    delta.hasLastLap = True
    delta.lapDistance = LAP_DISTANCE
    delta.speedDeltaBest = 0.92  # m/s, + faster than reference lap at same point
    delta.speedDeltaSession = 0.92
    delta.speedDeltaStint = 1.37
    delta.speedDeltaLast = -0.61
    delta.deltaBestData = tuple(
        (point[0], point[0] / TRACK_LENGTH * PLAYER_BEST) for point in TRACK_POINTS
    )

    fuel = minfo.fuel
    fuel.available = True
    fuel.capacity = 120.0
    fuel.amountStart = 120.0
    fuel.amountCurrent = 42.3
    fuel.amountUsedCurrent = 1.04  # this lap so far (LAP_DISTANCE into lap)
    fuel.amountEndStint = 1.8
    fuel.neededRelative = 6.3
    fuel.neededAbsolute = 48.6
    fuel.lastLapConsumption = 2.94
    fuel.estimatedConsumption = 2.91
    fuel.estimatedValidConsumption = 2.91
    fuel.estimatedLaps = 14.5
    fuel.estimatedMinutes = 20.6
    fuel.estimatedNumPitStopsEnd = 1.53
    fuel.estimatedNumPitStopsEarly = 0.97
    fuel.deltaConsumption = -0.03
    fuel.oneLessPitConsumption = 2.62
    fuel.rateOfConsumption = 0.034
    fuel.weight = 31.7

    energy = minfo.energy
    energy.available = True
    energy.capacity = 100.0
    energy.amountStart = 100.0
    energy.amountCurrent = 58.0
    energy.amountUsedCurrent = 1.37
    energy.amountEndStint = 2.4
    energy.neededRelative = 4.1
    energy.neededAbsolute = 62.1
    energy.lastLapConsumption = 3.88
    energy.estimatedConsumption = 3.84
    energy.estimatedValidConsumption = 3.84
    energy.estimatedLaps = 15.1
    energy.estimatedMinutes = 21.4
    energy.estimatedNumPitStopsEnd = 1.48
    energy.estimatedNumPitStopsEarly = 0.92
    energy.deltaConsumption = -0.04
    energy.oneLessPitConsumption = 3.52
    energy.rateOfConsumption = 0.045

    force = minfo.force
    force.lgtGForceRaw = -0.35
    force.latGForceRaw = 1.21
    force.maxAvgLatGForce = 1.86
    force.maxLgtGForce = 2.14
    force.maxLatGForce = 2.02
    force.downForceFront = 3150
    force.downForceRear = 3880
    force.downForceRatio = 0.448  # fraction, as module output (front downforce of total)
    force.brakingRate = 0.0
    force.transientMaxBrakingRate = 1.92
    force.maxBrakingRate = 2.14
    force.deltaBrakingRate = -0.08

    hybrid = minfo.hybrid
    hybrid.batteryCharge = 64.0
    hybrid.batteryDrain = 3.2
    hybrid.batteryRegen = 4.1
    hybrid.batteryDrainLast = 18.4
    hybrid.batteryRegenLast = 19.6
    hybrid.batteryNetChange = 1.2
    hybrid.motorActiveTimer = 4.6
    hybrid.motorInactiveTimer = 0.0
    hybrid.motorState = 2
    hybrid.fuelEnergyRatio = 0.758
    hybrid.fuelEnergyBias = 0.012

    mapping = minfo.mapping
    mapping.trackMap = TrackMap(
        tuple((point[1], point[2]) for point in TRACK_POINTS),
        tuple((point[0], point[3]) for point in TRACK_POINTS),
        TRACK_SECTORS,
        1.0,
    )
    mapping.speedTrapPosition = 3420.0
    mapping.pitEntryPosition = 3880.0
    mapping.pitExitPosition = 260.0
    mapping.pitLaneLength = 470.0
    mapping.pitSpeedLimit = 22.2
    mapping.pitPassTime = 24.8

    best_sectors = [PLAYER_BEST * 0.122, PLAYER_BEST * 0.527, PLAYER_BEST * 0.351]
    for sector_data, offset in ((minfo.sectors.sessionBest, 0.0), (minfo.sectors.allTimeBest, -0.12)):
        sector_data.noDeltaSector = sector_data.noDeltaSectorPB = False
        sector_data.sectorIndex = sector_data.recordedIndex = 1
        sector_data.sectorPrev = [best_sectors[0] - 0.041, best_sectors[1] + 0.118, best_sectors[2] + 0.062]
        sector_data.sectorBestTB = [value + offset / 3 for value in best_sectors]
        sector_data.sectorBestPB = [value + offset / 3 for value in best_sectors]
        sector_data.deltaSectorBestPB = [-0.041, 0.118 - offset / 3, 0.062]
        sector_data.deltaSectorBestTB = [-0.041, 0.118 - offset / 3, 0.062]

    minfo.stats.metersDriven = 18_640_000

    # Notes of the track (pace & track notes overlays: shown, not auto hidden as without notes)
    from .userfile.track_notes import COLUMN_COMMENT, COLUMN_DISTANCE, COLUMN_PACENOTE, COLUMN_TRACKNOTE

    for notes, column, (current, following) in (
        (minfo.pacenotes, COLUMN_PACENOTE, ("3 Right tightens", "Long left over crest")),
        (minfo.tracknotes, COLUMN_TRACKNOTE, ("Turn 5 chicane", "Turn 6 fast left")),
    ):
        notes.out.currentIndex = 4
        notes.out.currentNote = {COLUMN_DISTANCE: 1820.0, column: current, COLUMN_COMMENT: "Brake at 100 board"}
        notes.out.nextNote = {COLUMN_DISTANCE: 2140.0, column: following, COLUMN_COMMENT: "Stay off the kerb"}

    history = minfo.history
    history.consumptionDataSet = deque(
        (
            ConsumptionDataSet(
                lapNumber=PLAYER_LAPS - lap,
                isValidLap=lap != 3,
                lapTimeLast=PLAYER_LAST + (lap * 37 % 7) * 0.09 - 0.2,
                lastLapUsedFuel=2.94 - (lap % 3) * 0.03,
                lastLapUsedEnergy=3.88 - (lap % 3) * 0.04,
                batteryDrainLast=18.4,
                batteryRegenLast=19.6,
                tyreAvgWearLast=0.42 + (lap % 2) * 0.03,
                capacityFuel=120.0,
            )
            for lap in range(12)
        ),
        100,
    )
    history.consumptionDataVersion = 12
    stint = history.stintDataCurrent
    stint.totalLaps = 14
    stint.totalTime = 14 * 85.2
    stint.totalFuel = 41.2
    stint.totalEnergy = 54.3
    stint.totalTyreWear = 6.1
    stint.lapTimeDelta = 0.312
    stint.lapTimeConsistency = 98.7  # percent, as stint module
    stint.tyreCompound = "MMMM"
    stint.tyreCompoundNames = ("Medium",) * 4
    history.stintDataSet = deque(
        (
            StintDataSet(14, 14 * 85.2, 41.2, 54.3, 6.1, 0.312, 98.7, "MMMM", ("Medium",) * 4),
            StintDataSet(29, 29 * 85.4, 85.1, 99.2, 12.8, 0.398, 98.1, "MMMM", ("Medium",) * 4),
            StintDataSet(28, 28 * 85.6, 82.0, 98.6, 13.4, 0.441, 97.9, "SSSS", ("Soft",) * 4),
        ),
        100,
    )
    history.stintDataVersion = 3

    wheels = minfo.wheels
    wheels.lockingPercentFront = 0.4
    wheels.lockingPercentRear = 0.1
    wheels.yawRate = 0.21
    wheels.currentTreadDepth = [86.2, 87.1, 90.4, 91.1]  # percent of tread left
    wheels.currentLapTreadWear = [0.031, 0.028, 0.019, 0.018]
    wheels.lastLapTreadWear = [0.074, 0.069, 0.046, 0.044]
    wheels.estimatedTreadWear = [0.073, 0.069, 0.046, 0.045]
    wheels.estimatedValidTreadWear = [0.073, 0.069, 0.046, 0.045]
    wheels.lockingTreadWear = [0.002, 0.001, 0.0, 0.0]
    wheels.maxBrakeThickness = [32.0, 32.0, 29.0, 29.0]
    wheels.failureBrakeThickness = [18.0, 18.0, 16.0, 16.0]
    wheels.currentBrakeThickness = [30.4, 30.5, 28.1, 28.1]
    wheels.currentlapBrakeWear = [0.012, 0.012, 0.007, 0.007]
    wheels.lastLapBrakeWear = [0.031, 0.030, 0.018, 0.018]
    wheels.estimatedBrakeWear = [0.031, 0.030, 0.018, 0.018]
    wheels.estimatedValidBrakeWear = [0.031, 0.030, 0.018, 0.018]
    wheels.currentSuspensionPosition = [24.1, 34.6, 30.2, 40.8]
    wheels.staticSuspensionPosition = [28.0, 28.0, 34.0, 34.0]
    wheels.minSuspensionPosition = [8.2, 9.1, 12.6, 13.3]
    wheels.maxSuspensionPosition = [52.4, 54.1, 60.2, 61.7]
    wheels.motionRatio = [0.92, 0.92, 0.88, 0.88]
    wheels.wheelRadius = [0.338, 0.338, 0.351, 0.351]
    wheels.wheelRadiusFront = 338.0
    wheels.wheelRadiusRear = 351.0
    wheels.minimumStaticWeight = 1300.0
    wheels.totalStaticWeight = 1330.0
    wheels.totalDynamicWeight = 1478.0
    wheels.frontWeightRatio = 0.462
    wheels.leftWeightRatio = 0.468
    wheels.crossWeightRatio = 0.501
    wheels.slipRatio = [0.012, 0.009, 0.031, 0.027]
    # Angles in degrees. Front wheel angle includes steering: about 13:1 ratio for -26 deg at the wheel
    wheels.slipAngle = [-2.35, -2.18, -1.66, -1.55]
    wheels.averageFrontSlipAngle = -2.27
    wheels.averageRearSlipAngle = -1.61
    wheels.slipAngleDifference = 0.66  # abs(front average) - abs(rear average), as wheels module
    wheels.toeAngle = [-2.03, -1.995, -0.18, 0.18]
    wheels.averageFrontToeAngle = -2.02
    wheels.averageRearToeAngle = 0.0
    wheels.frontToeAngleDifference = -0.035  # left - right, as wheels module
    wheels.rearToeAngleDifference = -0.36
    wheels.camberAngle = [-3.67, -3.49, -2.58, -2.46]
    wheels.frontCamberAngleDifference = -0.18
    wheels.rearCamberAngleDifference = -0.12


def corner_inputs(phase: float) -> tuple[float, float, float, float, float]:
    """Inputs of a corner at phase (0 to 1): straight, braking, turn in, exit up to the simulated
    state (throttle, brake, steering, longitudinal G, lateral G)"""
    def ease(start: float, end: float, low: float, high: float) -> float:
        fraction = min(max((phase - start) / (end - start), 0.0), 1.0)
        return low + (high - low) * (0.5 - 0.5 * math.cos(math.pi * fraction))

    if phase < 0.25:  # straight, full throttle
        return 1.0, 0.0, 0.0, -0.45, ease(0.0, 0.25, 0.1, 0.0)
    if phase < 0.45:  # hard braking
        return 0.0, ease(0.25, 0.3, 0.0, 0.95), 0.0, ease(0.25, 0.3, -0.45, 1.85), 0.0
    if phase < 0.7:  # trail braking, turn in
        return (0.0, ease(0.45, 0.7, 0.95, 0.0), ease(0.45, 0.6, 0.0, -0.2),
                ease(0.45, 0.7, 1.85, 0.1), ease(0.45, 0.65, 0.0, 1.95))
    # Exit: throttle up, to simulated state
    return (ease(0.7, 1.0, 0.25, 0.92), 0.0, ease(0.7, 1.0, -0.2, -0.11),
            ease(0.7, 1.0, 0.1, -0.35), ease(0.7, 1.0, 1.95, 1.21))


def replay_history(widget, data, minfo: ModuleInfo, update: Callable[[Any], None] | None = None):
    """Feed a widget drawing input history (trace, trailing plot) a corner, ending at the simulated
    state; telemetry & G force put back after

    Args:
        widget: widget updated.
        data: simulated LMU shared memory.
        minfo: simulated module info.
        update: updates widget once (default: widget timerEvent).
    """
    if update is None:
        update = timer_event
    tele = data.telemetry.telemInfo[PLAYER]
    force = minfo.force
    saved = (tele.mElapsedTime, tele.mUnfilteredThrottle, tele.mFilteredThrottle, tele.mUnfilteredBrake,
             tele.mFilteredBrake, tele.mUnfilteredSteering, tele.mFilteredSteering,
             force.lgtGForceRaw, force.latGForceRaw)
    try:
        for frame in range(HISTORY_FRAMES):
            throttle, brake, steering, lgt, lat = corner_inputs(frame / (HISTORY_FRAMES - 1))
            tele.mElapsedTime = ELAPSED - (HISTORY_FRAMES - frame) * 0.02
            tele.mUnfilteredThrottle = tele.mFilteredThrottle = throttle
            tele.mUnfilteredBrake = tele.mFilteredBrake = brake
            tele.mUnfilteredSteering = tele.mFilteredSteering = steering
            force.lgtGForceRaw, force.latGForceRaw = lgt, lat
            update(widget)
    finally:
        (tele.mElapsedTime, tele.mUnfilteredThrottle, tele.mFilteredThrottle, tele.mUnfilteredBrake,
         tele.mFilteredBrake, tele.mUnfilteredSteering, tele.mFilteredSteering,
         force.lgtGForceRaw, force.latGForceRaw) = saved


def lap_delta(lap: int, progress: float) -> float:
    """Delta to best lap (seconds) at lap progress: last lap lost time, current lap gains so far"""
    if lap < PLAYER_LAPS:  # last lap
        return (PLAYER_LAST - PLAYER_BEST) * progress + 0.07 * math.sin(4 * math.pi * progress)
    fraction = progress / (LAP_DISTANCE / TRACK_LENGTH)
    return -0.284 * fraction + 0.06 * math.sin(3 * math.pi * fraction)


def replay_lap(widget, data, minfo: ModuleInfo, update: Callable[[Any], None] | None = None):
    """Feed a widget drawing delta over the lap the last lap and the current lap so far, ending at
    the simulated state; scoring, telemetry & delta put back after"""
    if update is None:
        update = timer_event
    scor = data.scoring.vehScoringInfo[PLAYER]
    tele = data.telemetry.telemInfo[PLAYER]
    delta = minfo.delta
    saved = (scor.mLapDist, scor.mTotalLaps, tele.mElapsedTime, tele.mLapStartET,
             tuple(getattr(delta, source) for source in DELTA_SOURCES))
    end = LAP_DISTANCE / TRACK_LENGTH
    frames = [(PLAYER_LAPS - 1, frame / LAP_FRAMES) for frame in range(LAP_FRAMES)]
    frames += [(PLAYER_LAPS, end * frame / (LAP_FRAMES // 2)) for frame in range(LAP_FRAMES // 2 + 1)]
    try:
        for lap, progress in frames:
            scor.mTotalLaps = lap
            scor.mLapDist = progress * TRACK_LENGTH
            tele.mLapStartET = LAP_START if lap == PLAYER_LAPS else LAP_START - PLAYER_LAST
            tele.mElapsedTime = tele.mLapStartET + progress * PLAYER_BEST
            value = lap_delta(lap, progress)
            for source in DELTA_SOURCES:
                setattr(delta, source, value)
            update(widget)
    finally:
        scor.mLapDist, scor.mTotalLaps, tele.mElapsedTime, tele.mLapStartET, values = saved
        for source, value in zip(DELTA_SOURCES, values):
            setattr(delta, source, value)


def replay_gaps(widget, data, minfo: ModuleInfo, update: Callable[[Any], None] | None = None):
    """Feed a widget drawing gaps per lap the gaps to cars ahead & behind (overall & in class) at end of the
    last laps, ending at the simulated state: gap ahead shrinking, gap behind growing; scoring & gaps put back
    after"""
    if update is None:
        update = timer_event
    scor = data.scoring.vehScoringInfo[PLAYER]
    cars = minfo.vehicles.dataSet
    # Gap ahead is the player's own gap, gap behind the gap of the car behind
    ahead = cars[PLAYER]
    behind_overall = cars[PLAYER + 1]
    behind_class = cars[ahead.classBehindIndex] if ahead.classBehindIndex >= 0 else behind_overall
    saved = (scor.mTotalLaps, ahead.gapBehindNext, ahead.gapBehindNextInClass, behind_overall.gapBehindNext,
             behind_class.gapBehindNextInClass)
    _, ahead_gap, ahead_class_gap, behind_gap, behind_class_gap = saved
    try:
        for lap in range(PLAYER_LAPS - GAP_LAPS, PLAYER_LAPS + 1):  # first lap read only (seen partly)
            laps_to_go = PLAYER_LAPS - lap
            wobble = 0.06 * math.sin(1.7 * laps_to_go)
            scor.mTotalLaps = lap
            ahead.gapBehindNext = ahead_gap + 0.18 * laps_to_go + wobble
            ahead.gapBehindNextInClass = ahead_class_gap + 0.18 * laps_to_go + wobble
            behind_overall.gapBehindNext = max(behind_gap - 0.11 * laps_to_go + wobble, 0.1)
            behind_class.gapBehindNextInClass = max(behind_class_gap - 0.11 * laps_to_go + wobble, 0.1)
            update(widget)
    finally:
        (scor.mTotalLaps, ahead.gapBehindNext, ahead.gapBehindNextInClass, behind_overall.gapBehindNext,
         behind_class.gapBehindNextInClass) = saved


# Animated preview (hovered card of Overlays page): a corner driven in a loop
MOTION_PERIOD = 6.0  # seconds per corner
MOTION_SPEEDS = ((0.0, 0.25, 52.0, 64.0), (0.25, 0.45, 64.0, 30.0), (0.45, 0.7, 30.0, 27.0), (0.7, 1.0, 27.0, 52.0))
GEAR_TOP_SPEEDS = (0.0, 14.0, 24.0, 33.0, 42.0, 52.0, 66.0)  # m/s at top of each gear, see set_motion
MOTION_DISTANCE = 270.0  # meters driven per corner (lap distance looped back after)
MOTION_START = 0.18  # phase of first picture: braking comes at once (no long straight first)
WHEEL_MOTION_FIELDS = ("mBrakeTemp", "mTireLoad", "mSuspForce", "mSuspensionDeflection", "mRideHeight", "mRotation",
                       "mLateralPatchVel", "mLongitudinalPatchVel", "mVerticalTireDeflection")


def eased(phase: float, start: float, end: float, low: float, high: float) -> float:
    """Value going from low to high (eased) while phase goes from start to end"""
    fraction = min(max((phase - start) / (end - start), 0.0), 1.0)
    return low + (high - low) * (0.5 - 0.5 * math.cos(math.pi * fraction))


def set_motion(session: DemoSession, seconds: float):
    """Player car driven through a corner, looped (MOTION_PERIOD): inputs, G force, speed, gear & RPM, steering
    torque, delta and position into lap; clocks run on

    Wheels follow (brake pressure & temperature, tyre surface temperature, load, suspension, ride height, wheel
    speed & slip) around their simulated values. In pits (scenario): rolling in the pit lane at the limiter.
    Only for a session of its own (see widget_preview.LivePreview): the shared session of still pictures is never
    moved.
    """
    phase = ((seconds / MOTION_PERIOD) + MOTION_START) % 1.0
    data, minfo = session.data, session.minfo
    tele = data.telemetry.telemInfo[PLAYER]
    wheels = tele.mWheels
    if session.motion is None:  # simulated values the motion goes around
        session.motion = {
            "wheels": [{field: getattr(wheel, field) for field in WHEEL_MOTION_FIELDS} for wheel in wheels],
            "temperature": [tuple(wheel.mTemperature) for wheel in wheels],
            "ride": (tele.mFrontRideHeight, tele.mRearRideHeight),
            "suspension": tuple(minfo.wheels.currentSuspensionPosition),  # wheels module outputs
            "slip": tuple(minfo.wheels.slipRatio),
        }
    base = session.motion
    elapsed = ELAPSED + seconds
    tele.mElapsedTime = data.scoring.scoringInfo.mCurrentET = elapsed
    wave = math.sin(2 * math.pi * phase)
    if session.scenario == "pits":  # limiter on in the pit lane: inputs only
        throttle = 0.35 + 0.05 * wave
        tele.mUnfilteredThrottle = tele.mFilteredThrottle = throttle
        tele.mUnfilteredSteering = tele.mFilteredSteering = 0.04 * wave
        tele.mEngineRPM = 4300 + 60 * wave
        return
    throttle, brake, steering, lgt, lat = corner_inputs(phase)
    speed = next(eased(phase, *part) for part in MOTION_SPEEDS if phase <= part[1])
    gear = next((index for index, top in enumerate(GEAR_TOP_SPEEDS) if index and speed <= top), 6)
    low, top = GEAR_TOP_SPEEDS[gear - 1], GEAR_TOP_SPEEDS[gear]
    elapsed = ELAPSED + seconds
    tele.mElapsedTime = data.scoring.scoringInfo.mCurrentET = elapsed
    tele.mUnfilteredThrottle = tele.mFilteredThrottle = throttle
    tele.mUnfilteredBrake = tele.mFilteredBrake = brake
    tele.mUnfilteredSteering = tele.mFilteredSteering = steering
    tele.mSteeringShaftTorque = steering * 58.0
    tele.mLocalVel.z = -speed
    tele.mLocalAccel.x = lat * 9.81
    tele.mLocalAccel.z = lgt * 7.5
    tele.mLocalRot.y = lat * 0.17
    tele.mGear = gear
    tele.mEngineRPM = min(3800.0 + 4300.0 * (speed - low) / (top - low), tele.mEngineMaxRPM - 150.0)
    minfo.force.lgtGForceRaw, minfo.force.latGForceRaw = lgt, lat
    distance = (LAP_DISTANCE + phase * MOTION_DISTANCE) % TRACK_LENGTH
    data.scoring.vehScoringInfo[PLAYER].mLapDist = distance
    pos_x, pos_y, pos_z, heading = track_position(distance)
    tele.mPos.x, tele.mPos.y, tele.mPos.z = pos_x, pos_z, -pos_y
    tele.mOri[2].x, tele.mOri[2].z = math.sin(heading), math.cos(heading)
    tele.mOri[0].x, tele.mOri[0].z = math.cos(heading), -math.sin(heading)
    value = lap_delta(PLAYER_LAPS, LAP_DISTANCE / TRACK_LENGTH) + 0.05 * wave
    for source in DELTA_SOURCES:
        setattr(minfo.delta, source, value)
    # Brakes heat up while braking, cool down after; load moves forward under braking, outward in the corner
    heat = eased(phase, 0.25, 0.45, 0.0, 1.0) if phase < 0.45 else eased(phase, 0.45, 1.0, 1.0, 0.0)
    pitch = (lgt + 0.45) / 2.3  # 0 accelerating, 1 hardest braking
    tele.mFrontRideHeight = base["ride"][0] - 0.008 * pitch
    tele.mRearRideHeight = base["ride"][1] + 0.006 * pitch
    suspension, slips = list(base["suspension"]), list(base["slip"])
    for index, wheel in enumerate(wheels):
        front = index < 2
        side = 1.0 if index % 2 else -1.0  # right wheels loaded in the corner (lateral G positive)
        shift = (1.0 if front else -1.0) * pitch + side * lat / 2.0  # share of load moved onto this wheel
        values = base["wheels"][index]
        wheel.mBrakePressure = brake * (0.95 if front else 0.78)
        wheel.mBrakeTemp = values["mBrakeTemp"] + (190.0 if front else 140.0) * heat
        wheel.mTireLoad = values["mTireLoad"] * (1.0 + 0.45 * shift)
        wheel.mSuspForce = values["mSuspForce"] * (1.0 + 0.4 * shift)
        wheel.mSuspensionDeflection = values["mSuspensionDeflection"] * (1.0 + 0.5 * shift)
        wheel.mVerticalTireDeflection = values["mVerticalTireDeflection"] * (1.0 + 0.3 * shift)
        wheel.mRideHeight = values["mRideHeight"] - 0.006 * shift
        slip = (0.06 if front else 0.03) * brake - (0.0 if front else 0.04) * throttle  # lock up, wheelspin
        wheel.mRotation = values["mRotation"] * speed / 58.0 * (1.0 - slip)
        suspension[index] = base["suspension"][index] * (1.0 + 0.5 * shift)
        slips[index] = base["slip"][index] + abs(slip)
        wheel.mLongitudinalPatchVel = values["mLongitudinalPatchVel"] * (1.0 + 20.0 * abs(slip))
        wheel.mLateralPatchVel = values["mLateralPatchVel"] * (0.3 + lat)
        for layer, temperature in enumerate(base["temperature"][index]):
            wheel.mTemperature[layer] = temperature + 4.0 * shift + (1.5 * heat if front else 0.0)
    minfo.wheels.currentSuspensionPosition = suspension
    minfo.wheels.slipRatio = slips


class DemoAPI:
    """Stands for api_control.api in widget modules: reader of the simulated session"""

    __slots__ = ("_api", "read")

    def __init__(self, sim: api_connector.SimLMU):
        self._api = sim
        self.read = sim.reader()


# Race situations of preview (Overlay Options): what overlays show only then (flags, pit, damage, rain), "" racing
SCENARIOS = ("", "flags", "pits", "damage", "rain")
SCENARIO_LABELS = {"": "Racing", "flags": "Yellow & Blue Flags", "pits": "In Pits", "damage": "Damage",
                   "rain": "Rain"}


def set_scenario(sim, data, minfo: ModuleInfo, scenario: str):
    """Race situation set on simulated session (after set_telemetry, set_vehicles & set_modules)"""
    tele = data.telemetry.telemInfo[PLAYER]
    scoring = data.scoring.scoringInfo
    player = data.scoring.vehScoringInfo[PLAYER]
    rest = sim._restapi_dataset
    if scenario == "flags":  # yellow in next sector (car stopped ahead), faster car behind (blue flag)
        scoring.mSectorFlag[SECTOR_FLAG_ORDER[2]] = 1  # cars in sector 2: yellow in next sector
        player.mFlag = 6
        minfo.vehicles.nearestYellowAhead = 180.0
    elif scenario == "pits":  # pit lane, limiter on, stop asked
        player.mInPits = True
        player.mPitState = 2  # entering
        tele.mSpeedLimiter = 1
        tele.mSpeedLimiterActive = 1
        tele.mLocalVel.z = -16.6  # 60 km/h
        tele.mLocalVel.x = tele.mLocalAccel.x = tele.mLocalRot.y = 0.0
        tele.mGear = 2
        tele.mEngineRPM = 4300
        tele.mUnfilteredThrottle = tele.mFilteredThrottle = 0.35
        tele.mUnfilteredSteering = tele.mFilteredSteering = 0.0
    elif scenario == "damage":  # front left hit: body dents, aero & suspension damage, puncture
        for part, severity in enumerate((2, 1, 0, 0, 0, 0, 1, 2)):
            tele.mDentSeverity[part] = severity
        rest.aeroDamage = 0.35
        rest.suspensionDamage = (0.42, 0.06, 0.0, 0.0)
        tele.mWheels[0].mFlat = True
        tele.mWheels[0].mPressure = 40.0
        tele.mLastImpactET = ELAPSED - 2.0
        tele.mLastImpactMagnitude = 4800.0
        tele.mLastImpactPos.x, tele.mLastImpactPos.z = 0.8, -1.9  # front left
    elif scenario == "rain":  # wet track, wipers & lights on, wet surface under the car
        scoring.mRaining = 0.65
        scoring.mDarkCloud = 0.9
        scoring.mCloudCoverage = 8
        scoring.mMinPathWetness, scoring.mAvgPathWetness, scoring.mMaxPathWetness = 0.4, 0.6, 0.8
        tele.mWiperState = 2
        tele.mHeadlights = True
        for wheel in tele.mWheels:
            wheel.mSurfaceType = 1



class DemoSession:
    """Simulated race: game data (api.read) and module outputs (minfo) read by widgets"""

    __slots__ = ("sim", "data", "api", "minfo", "scenario", "motion")

    def __init__(self, standings: Mapping[str, Any], scenario: str = ""):
        self.sim, self.data = lmu_api()
        self.api = DemoAPI(self.sim)
        self.minfo = ModuleInfo()
        self.scenario = scenario
        self.motion: dict[str, Any] | None = None  # simulated values moved around (see set_motion)
        set_telemetry(self.sim, self.data)
        set_vehicles(self.minfo, standings, self.api.read)
        set_modules(self.minfo)
        if scenario:
            set_scenario(self.sim, self.data, self.minfo, scenario)


_session: tuple[dict, str, DemoSession] | None = None


def demo_session(standings: Mapping[str, Any], scenario: str = "") -> DemoSession:
    """Simulated session (in race situation), made again only when standings setting or situation changes"""
    global _session
    if scenario not in SCENARIOS:
        scenario = ""
    if _session is None or _session[0] != standings or _session[1] != scenario:
        _session = (dict(standings), scenario, DemoSession(standings, scenario))
    return _session[2]


def release_session():
    """Simulated session dropped (no page draws pictures), made again when next needed"""
    global _session
    _session = None


def widget_modules() -> Iterator[Any]:
    """Loaded modules whose api & minfo globals are pointed to a simulated session"""
    for name, module in tuple(sys.modules.items()):
        if module is not None and (name.startswith("neopedal.widget.") or name == "neopedal.race_live"):
            yield module


@contextmanager
def demo_globals(session: DemoSession) -> Iterator[Callable[[], None]]:
    """Widget modules read the simulated session inside block (UI thread only), user presets
    never changed by simulated cars (see demo_state)

    Yields a function pointing modules loaded later in block (widget imports) to the session too.
    Nested blocks keep the outer session.
    """
    from .api_control import api
    from .module_info import minfo

    swaps = (("api", api, session.api), ("minfo", minfo, session.minfo))
    patched: list[tuple[dict, str, Any]] = []

    def patch():
        for module in widget_modules():
            namespace = vars(module)
            for attr, real, demo in swaps:
                if namespace.get(attr) is real:
                    namespace[attr] = demo
                    patched.append((namespace, attr, real))

    patch()
    try:
        with demo_drawing(session.api.read):  # shared helpers (brands, heatmap presets) too
            yield patch
    finally:
        for namespace, attr, real in reversed(patched):
            namespace[attr] = real


def timer_event(widget):
    """Widget timerEvent, as its update timer calls it"""
    widget.timerEvent(QTimerEvent(0))


def update_once(widget):
    """Widget timerEvent, not recorded by performance monitor (not a running overlay)"""
    method = type(widget).timerEvent
    getattr(method, "__wrapped__", method)(widget, QTimerEvent(0))


def update_widget(widget, name: str, session: DemoSession):
    """Widget updated on simulated session (inside demo_globals block): input or lap history fed
    first if drawn, then a few updates so smoothed values settle"""
    if name in HISTORY_WIDGETS:
        replay_history(widget, session.data, session.minfo, update_once)
    elif name in LAP_WIDGETS:
        with shapes_deferred(widget):
            replay_lap(widget, session.data, session.minfo, update_once)
    elif name in GAP_WIDGETS:
        replay_gaps(widget, session.data, session.minfo, update_once)
    for _ in range(UPDATES):
        update_once(widget)


@contextmanager
def shapes_deferred(widget) -> Iterator[None]:
    """Lap trace widgets (delta graph): chart shapes, built from the trace only, not built on every replayed
    frame but once on next update (same picture, most of the drawing time)"""
    if not (callable(getattr(widget, "build_shapes", None)) and hasattr(widget, "shapes_version")):
        yield
        return
    widget.build_shapes = lambda: widget.shapes  # shapes kept as they are while replaying
    try:
        yield
    finally:
        del widget.build_shapes
        widget.shapes_version = -1  # built from the whole trace on next update


# Recorded lap of Road Atlanta, downsampled: lap distance (m), world x, world y, elevation (m)
TRACK_POINTS = (
    (4.2, 10.0, -6.31, 0.2), (33.1, 34.3, 9.32, -0.6), (62.4, 58.8, 25.45, -1.4), (92.1, 84.0, 42.46, -2.1),
    (122.1, 108.1, 58.9, -2.6), (152.4, 133.9, 76.24, -3.1), (183.0, 158.7, 92.81, -3.4),
    (213.8, 185.0, 110.31, -3.7), (244.8, 210.1, 127.14, -4.1), (276.1, 236.1, 144.41, -4.4),
    (307.1, 262.1, 161.62, -4.7), (335.6, 286.7, 178.96, -5.0), (361.1, 306.2, 194.78, -5.4),
    (385.1, 323.5, 212.51, -5.9), (408.1, 336.7, 231.13, -6.5), (431.2, 346.7, 251.07, -7.2),
    (454.7, 353.4, 273.19, -7.8), (478.9, 355.8, 295.42, -7.6), (502.4, 354.0, 319.29, -6.5),
    (525.9, 347.9, 342.19, -4.7), (549.9, 338.2, 364.11, -2.3), (574.1, 325.3, 384.88, 0.2),
    (598.9, 310.6, 404.04, 2.6), (624.1, 293.5, 422.61, 5.0), (649.8, 274.9, 440.35, 7.4),
    (676.0, 255.4, 458.66, 9.6), (702.3, 237.9, 477.72, 11.2), (728.0, 223.1, 497.99, 12.0),
    (752.0, 211.4, 518.21, 12.2), (774.0, 203.4, 537.34, 12.4), (793.8, 196.8, 555.52, 12.6),
    (811.2, 188.7, 571.43, 12.6), (828.6, 178.9, 585.62, 12.2), (845.4, 167.9, 596.65, 11.7),
    (868.3, 147.5, 609.25, 10.8), (885.2, 132.0, 615.48, 10.0), (903.0, 116.8, 621.93, 9.2),
    (921.6, 101.6, 630.46, 8.5), (940.5, 87.4, 641.67, 7.7), (960.3, 74.6, 655.66, 6.9), (980.7, 63.6, 672.64, 6.1),
    (1001.6, 55.5, 690.98, 5.2), (1023.0, 49.6, 711.96, 4.3), (1044.9, 45.2, 733.02, 3.3),
    (1067.9, 38.7, 755.51, 1.8), (1091.3, 29.8, 776.69, -0.0), (1115.2, 17.1, 798.71, -2.4),
    (1141.2, 2.5, 817.16, -4.8), (1167.7, -16.2, 834.98, -7.5), (1193.9, -37.1, 850.29, -9.7),
    (1220.3, -59.9, 863.93, -10.8), (1248.5, -81.8, 878.63, -10.6), (1276.6, -103.3, 896.53, -9.1),
    (1303.8, -123.2, 914.13, -7.0), (1329.8, -144.5, 929.52, -4.8), (1354.1, -165.0, 941.39, -2.7),
    (1375.7, -183.1, 950.35, -0.8), (1394.5, -198.9, 960.18, 0.6), (1413.6, -212.5, 972.52, 2.2),
    (1431.9, -222.3, 986.1, 3.9), (1449.1, -229.5, 1001.8, 5.7), (1466.5, -234.2, 1019.32, 7.6),
    (1484.8, -236.3, 1037.03, 9.3), (1503.9, -237.8, 1056.49, 10.9), (1523.8, -239.2, 1075.75, 11.9),
    (1544.3, -240.3, 1096.82, 12.5), (1565.7, -241.1, 1117.68, 12.6), (1587.9, -241.9, 1141.0, 12.1),
    (1610.8, -242.6, 1162.85, 11.1), (1634.6, -243.2, 1187.2, 9.9), (1659.1, -243.8, 1211.69, 9.2),
    (1684.1, -244.4, 1236.09, 8.8), (1709.8, -245.2, 1262.34, 8.4), (1736.2, -245.8, 1287.87, 7.7),
    (1763.0, -246.4, 1315.26, 6.4), (1790.3, -246.7, 1341.82, 4.9), (1818.0, -246.2, 1369.51, 3.2),
    (1846.2, -244.8, 1398.32, 1.9), (1874.3, -243.3, 1425.6, 1.7), (1899.5, -242.3, 1450.77, 2.1),
    (1921.2, -242.2, 1472.41, 2.7), (1940.3, -244.4, 1492.62, 3.1), (1958.4, -249.2, 1509.63, 3.2),
    (1976.4, -256.8, 1524.49, 3.2), (1994.5, -267.8, 1537.8, 3.3), (2013.2, -281.3, 1548.2, 3.7),
    (2032.0, -297.6, 1556.1, 4.5), (2050.6, -316.1, 1561.45, 5.5), (2069.6, -334.6, 1564.28, 6.4),
    (2086.8, -352.1, 1565.65, 7.3), (2107.9, -373.1, 1566.44, 8.3), (2126.1, -391.1, 1564.41, 9.0),
    (2143.4, -407.3, 1556.8, 9.3), (2163.6, -418.4, 1545.62, 9.4), (2183.9, -425.5, 1526.48, 9.2),
    (2200.8, -425.4, 1509.48, 8.9), (2220.8, -422.6, 1488.84, 8.3), (2244.0, -418.4, 1465.85, 7.7),
    (2261.1, -415.2, 1449.85, 7.4), (2279.1, -411.6, 1431.57, 7.2), (2298.3, -408.0, 1413.2, 7.2),
    (2318.4, -403.9, 1392.94, 7.4), (2339.5, -399.8, 1372.85, 7.6), (2361.4, -396.4, 1351.41, 8.0),
    (2384.1, -393.7, 1328.51, 8.5), (2407.6, -391.7, 1305.4, 9.2), (2431.6, -390.5, 1281.61, 10.3),
    (2456.3, -390.3, 1257.86, 11.7), (2481.3, -390.8, 1233.03, 13.4), (2506.7, -392.0, 1207.17, 14.9),
    (2532.4, -393.6, 1181.56, 16.1), (2558.6, -395.6, 1155.47, 16.8), (2585.3, -397.8, 1129.58, 17.0),
    (2612.4, -400.2, 1101.22, 16.8), (2640.0, -402.7, 1074.44, 16.3), (2667.9, -405.1, 1046.57, 16.2),
    (2696.3, -407.7, 1018.35, 16.6), (2724.9, -410.1, 990.59, 17.3), (2753.8, -412.6, 961.8, 18.0),
    (2783.0, -415.1, 931.98, 18.8), (2812.4, -417.6, 902.6, 19.5), (2842.2, -420.0, 873.7, 20.3),
    (2872.2, -422.6, 843.06, 21.1), (2902.4, -425.1, 813.68, 21.9), (2932.9, -427.9, 782.57, 22.8),
    (2963.6, -430.4, 752.77, 23.7), (2994.5, -432.6, 721.98, 24.5), (3025.7, -434.0, 690.95, 25.1),
    (3057.3, -434.4, 658.13, 25.5), (3089.0, -433.4, 627.48, 25.5), (3120.9, -430.6, 595.96, 25.1),
    (3152.9, -425.8, 564.5, 24.6), (3169.0, -422.7, 548.83, 24.3), (3185.1, -419.4, 533.98, 24.0),
    (3201.2, -415.3, 517.63, 23.7), (3217.4, -411.2, 502.08, 23.3), (3233.6, -406.8, 486.56, 22.8),
    (3249.8, -402.5, 471.83, 22.3), (3266.1, -397.7, 456.31, 21.6), (3282.3, -392.6, 440.01, 20.7),
    (3298.7, -387.7, 424.46, 19.8), (3315.1, -383.0, 409.64, 18.8), (3331.5, -377.9, 393.19, 17.6),
    (3347.9, -373.0, 377.59, 16.5), (3364.1, -368.1, 362.13, 15.5), (3394.7, -359.4, 333.75, 14.1),
    (3420.9, -351.8, 308.63, 13.6), (3443.1, -345.2, 287.0, 13.6), (3461.3, -340.1, 270.07, 13.8),
    (3483.9, -335.2, 247.9, 14.5), (3503.0, -334.7, 228.41, 14.9), (3525.3, -340.2, 211.48, 15.5),
    (3543.9, -351.1, 196.46, 16.1), (3564.6, -363.9, 180.13, 16.8), (3588.0, -370.3, 161.11, 18.1),
    (3610.8, -369.8, 140.11, 20.1), (3633.0, -363.7, 118.28, 22.3), (3649.2, -356.4, 103.33, 23.9),
    (3666.5, -348.1, 88.75, 25.4), (3684.7, -337.7, 72.71, 26.5), (3703.6, -326.8, 58.11, 26.8),
    (3723.4, -313.5, 42.48, 26.3), (3744.7, -299.2, 27.87, 25.2), (3766.9, -282.6, 13.08, 23.1),
    (3789.2, -265.3, -0.25, 20.2), (3812.5, -245.9, -13.08, 16.4), (3836.8, -224.5, -25.34, 12.3),
    (3861.8, -202.1, -36.34, 8.7), (3887.4, -178.0, -45.43, 6.3), (3913.4, -153.0, -51.34, 4.5),
    (3939.8, -126.3, -53.54, 3.5), (3967.6, -98.5, -51.51, 3.1), (3995.7, -72.4, -45.94, 2.7),
    (4024.0, -45.5, -36.59, 2.0), (4051.9, -20.0, -24.45, 1.3), (4080.4, 4.0, -10.44, 0.4),
)
