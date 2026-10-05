"""
Render README preview image from real widgets: images/readme_preview.png

Every widget is built with default modern settings on simulated LMU data: a GT3 car at
speed mid race at Road Atlanta, in a 20 car multi-class field. Data modules do not run
here, so their outputs (minfo) are filled directly. Widgets are then packed on a neutral
background, largest first.

The track path (tools/readme_preview_track.json) is a recorded lap, downsampled.

Run from project root after visual changes to widgets:
    python tools/make_readme_preview.py
"""

from __future__ import annotations

import json
import math
import os
import pkgutil
import sys
from collections import deque
from importlib import import_module
from itertools import chain

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF, Qt, QTimerEvent
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication(sys.argv)

from tests.test_readers import lmu_api
from tinypedal.api_control import api
from tinypedal.main import load_bundled_fonts
from tinypedal.module.module_relative import (
    get_vehicles_info,
    max_vehicles_in_class,
    min_top_vehicles_in_class,
    standings_index_from_all_classes,
    update_position_in_class,
)
from tinypedal.module_info import ConsumptionDataSet, StintDataSet, VehicleDataSet, minfo
from tinypedal.process.weather import WeatherNode
from tinypedal.setting import cfg
from tinypedal.userfile.json_setting import copy_setting
from tinypedal.widget._modern import create_widget

OUTPUT = os.path.join("images", "readme_preview.png")
TRACK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "readme_preview_track.json")
WIDTH = 1920
MARGIN = 24
SPACING = 14
BACKGROUND = QColor(28, 31, 36)
KELVIN = 273.15

# Session state
TRACK_LENGTH = 4083.5
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


def car_distance(index: int) -> float:
    """Lap distance of a car (meters)"""
    return CAR_DISTANCE.get(index, (LAP_DISTANCE + (PLAYER - index) * 330) % TRACK_LENGTH)


def load_track():
    with open(TRACK_FILE, encoding="utf-8") as file:
        return json.load(file)


TRACK = load_track()


def track_position(distance: float) -> tuple[float, float, float, float]:
    """World x, y, elevation and heading (radians) at lap distance"""
    points = TRACK["points"]
    distance %= TRACK_LENGTH
    for index in range(1, len(points)):
        if points[index][0] >= distance:
            break
    d0, x0, y0, z0 = points[index - 1]
    d1, x1, y1, z1 = points[index]
    ratio = (distance - d0) / max(d1 - d0, 0.01)
    heading = math.atan2(y1 - y0, x1 - x0)
    return x0 + (x1 - x0) * ratio, y0 + (y1 - y0) * ratio, z0 + (z1 - z0) * ratio, heading


def set_telemetry(sim, data):
    """Player car: GT3 at speed, exiting a fast corner"""
    tele = data.telemetry.telemInfo[PLAYER]
    tele.mElapsedTime = ELAPSED
    tele.mLapNumber = PLAYER_LAPS + 1
    tele.mLapStartET = LAP_START
    tele.mVehicleName = b"McLaren 720S GT3 Evo #59"
    tele.mVehicleModel = b"McLaren 720S GT3 Evo"
    tele.mTrackName = TRACK["track"].encode()
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
    tele.mRegen = 0.0
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
        for layer in range(3):
            wheel.mTemperature[layer] = KELVIN + base + (2 - layer) * 2.5
            wheel.mTireInnerLayerTemperature[layer] = KELVIN + base + 4 + (2 - layer) * 1.5
        wheel.mTireCarcassTemperature = KELVIN + base + 2
        wheel.mSurfaceType = 0
    tele.mFrontTireCompoundIndex = tele.mRearTireCompoundIndex = 1
    tele.mFrontTireCompoundName = tele.mRearTireCompoundName = b"Medium"

    scoring = data.scoring.scoringInfo
    scoring.mTrackName = TRACK["track"].encode()
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


def set_vehicles():
    """Vehicles and relative module outputs: full field, consistent with scoring data"""
    vehicles = minfo.vehicles
    size = len(FIELD)
    vehicles.dataSet = tuple(VehicleDataSet() for _ in range(size))
    vehicles.totalVehicles = size
    vehicles.playerIndex = PLAYER
    vehicles.leaderIndex = 0
    vehicles.leaderBestLapTime = FIELD[0][3]
    vehicles.totalCompletedLaps = size * PLAYER_LAPS
    vehicles.dataSetVersion = 1
    class_leader = {}
    class_members = {}
    for index, (_, _, vclass, _) in enumerate(FIELD):
        class_leader.setdefault(vclass, index)
        class_members.setdefault(vclass, []).append(index)
    plr_x, plr_y, _, plr_heading = track_position(LAP_DISTANCE)
    nearest_line = 9999.0
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
        data.numPitStops = 2 if index % 3 else 3
        data.pitRequested = index == 16
        data.tireCompoundName = (f"{vclass} - Medium",) * 4 if index % 4 else (f"{vclass} - Soft",) * 4
        data.vehicleIntegrity = 1.0 if index not in (5, 17) else 0.86
        data.incidents = (index * 3) % 7
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
        if not data.isPlayer:
            nearest_line = min(nearest_line, data.relativeStraightDistance)
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

    # Relative lists, standings (split by class) and draw order, as the relative module computes them
    relative = minfo.relative
    (relative.relativeAhead, relative.relativeBehind, classes, relative.drawOrder, _) = get_vehicles_info(
        size, PLAYER, False, False, relative.relativeDeltaAhead, relative.relativeDeltaBehind)
    plr_class, plr_class_place = update_position_in_class(classes, PLAYER)
    setting = cfg.user.setting["standings"]
    min_top = min_top_vehicles_in_class(setting["minimum_top_vehicles"])
    relative.standings = list(chain(*standings_index_from_all_classes(
        min_top, classes, plr_class, plr_class_place,
        max_vehicles_in_class(setting["maximum_vehicles_per_split_others"], min_top, 0),
        max_vehicles_in_class(setting["maximum_vehicles_per_split_player"], min_top, 2),
    )))


def set_modules():
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
    delta.lapDistance = LAP_DISTANCE
    delta.deltaBestData = tuple(
        (point[0], point[0] / TRACK_LENGTH * PLAYER_BEST) for point in TRACK["points"]
    )

    fuel = minfo.fuel
    fuel.available = True
    fuel.capacity = 120.0
    fuel.amountStart = 120.0
    fuel.amountCurrent = 42.3
    fuel.amountUsedCurrent = 77.7
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
    energy.amountUsedCurrent = 42.0
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
    force.maxLgtGForce = -2.14
    force.maxLatGForce = 2.02
    force.downForceFront = 3150
    force.downForceRear = 3880
    force.downForceRatio = 44.8
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
    points = TRACK["points"]
    mapping.coordinates = tuple((point[1], point[2]) for point in points)
    mapping.elevations = tuple((point[0], point[3]) for point in points)
    mapping.sectors = tuple(TRACK["sectors"])
    mapping.lastModified = 1.0
    mapping.speedTrapPosition = 3420.0
    mapping.pitEntryPosition = 3880.0
    mapping.pitExitPosition = 260.0
    mapping.pitLaneLength = 470.0
    mapping.pitSpeedLimit = 22.2
    mapping.pitPassTime = 24.8

    best_sectors = [PLAYER_BEST * 0.122, PLAYER_BEST * 0.527, PLAYER_BEST * 0.351]
    for sector_data, offset in ((minfo.sectors.sessionBest, 0.0), (minfo.sectors.allTimeBest, -0.12)):
        sector_data.noDeltaSector = False
        sector_data.sectorIndex = 1
        sector_data.sectorPrev = [best_sectors[0] - 0.041, best_sectors[1] + 0.118, best_sectors[2] + 0.062]
        sector_data.sectorBestTB = [value + offset / 3 for value in best_sectors]
        sector_data.sectorBestPB = [value + offset / 3 for value in best_sectors]
        sector_data.deltaSectorBestPB = [-0.041, 0.118 - offset / 3, 0.062]
        sector_data.deltaSectorBestTB = [-0.041, 0.118 - offset / 3, 0.062]

    minfo.stats.metersDriven = 18_640_000

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
    stint.lapTimeConsistency = 0.987
    stint.tyreCompound = "MMMM"
    history.stintDataSet = deque(
        (
            StintDataSet(14, 14 * 85.2, 41.2, 54.3, 6.1, 0.312, 0.987, "MMMM"),
            StintDataSet(29, 29 * 85.4, 85.1, 99.2, 12.8, 0.398, 0.981, "MMMM"),
            StintDataSet(28, 28 * 85.6, 82.0, 98.6, 13.4, 0.441, 0.979, "SSSS"),
        ),
        100,
    )
    history.stintDataVersion = 3

    wheels = minfo.wheels
    wheels.lockingPercentFront = 0.4
    wheels.lockingPercentRear = 0.1
    wheels.yawRate = 0.21
    wheels.currentTreadDepth = [8.62, 8.71, 9.04, 9.11]
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
    wheels.slipAngleDifference = -0.66
    wheels.toeAngle = [-2.03, -1.995, -0.18, 0.18]
    wheels.averageFrontToeAngle = -2.02
    wheels.averageRearToeAngle = 0.0
    wheels.frontToeAngleDifference = 0.035
    wheels.rearToeAngleDifference = 0.36
    wheels.camberAngle = [-3.67, -3.49, -2.58, -2.46]
    wheels.frontCamberAngleDifference = -0.18
    wheels.rearCamberAngleDifference = -0.12


def pack(sizes: dict[str, tuple[int, int]], width: int) -> tuple[dict[str, tuple[int, int]], int]:
    """Pack rectangles (largest first) into a fixed width, using skyline bottom-left placement"""
    skyline = [(0, width, 0)]  # segments: x, width, top y
    positions = {}
    for name, (w, h) in sorted(sizes.items(), key=lambda item: (-item[1][1], -item[1][0])):
        best = None
        for start, (seg_x, _, _) in enumerate(skyline):
            if seg_x + w > width:
                break
            # Lowest y where the rect fits starting at this segment
            top, span, index = 0, 0, start
            while span < w and index < len(skyline):
                top = max(top, skyline[index][2])
                span = skyline[index][0] + skyline[index][1] - seg_x
                index += 1
            if span < w:
                continue
            if best is None or top < best[1] or (top == best[1] and seg_x < best[0]):
                best = (seg_x, top)
        x, y = best
        positions[name] = (x, y)
        # Update skyline
        new_skyline = []
        for seg_x, seg_w, seg_y in skyline:
            seg_end = seg_x + seg_w
            if seg_end <= x or seg_x >= x + w:
                new_skyline.append((seg_x, seg_w, seg_y))
                continue
            if seg_x < x:
                new_skyline.append((seg_x, x - seg_x, seg_y))
            if seg_end > x + w:
                new_skyline.append((x + w, seg_end - x - w, seg_y))
        new_skyline.append((x, w, y + h))
        new_skyline.sort()
        skyline = new_skyline
    return positions, max(y + sizes[name][1] for name, (_, y) in positions.items())


def render_widgets() -> dict[str, QPixmap]:
    names = sorted(
        module.name
        for module in pkgutil.iter_modules(import_module("tinypedal.widget").__path__)
        if not module.name.startswith("_")
    )
    pixmaps = {}
    for name in names:
        widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
        widget.adjustSize()
        for _ in range(3):  # a few updates, so smoothed values settle
            widget.timerEvent(QTimerEvent(0))
        widget.adjustSize()  # rows shown on update (standings, relative) change the size
        # Render on transparent pixmap: grab() fills translucent areas with an opaque background
        pixmap = QPixmap(widget.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        widget.render(pixmap, renderFlags=QWidget.RenderFlag.DrawChildren)
        pixmaps[name] = pixmap
        widget.deleteLater()
    return pixmaps


def main():
    load_bundled_fonts()
    cfg.default.set_default()
    for name in cfg.user.__slots__:
        setattr(cfg.user, name, copy_setting(getattr(cfg.default, name)))
    sim, data = lmu_api()
    api._api, api.read = sim, sim.reader()
    set_telemetry(sim, data)
    set_vehicles()
    set_modules()

    pixmaps = render_widgets()
    sizes = {name: (pixmap.width() + SPACING, pixmap.height() + SPACING) for name, pixmap in pixmaps.items()}
    positions, height = pack(sizes, WIDTH - MARGIN * 2 + SPACING)

    caption_height = 40
    image = QPixmap(WIDTH, height - SPACING + MARGIN * 2 + caption_height)
    image.fill(BACKGROUND)
    painter = QPainter(image)
    for name, (x, y) in positions.items():
        painter.drawPixmap(MARGIN + x, MARGIN + y, pixmaps[name])
    painter.setFont(QFont("JetBrains Mono", 13))
    painter.setPen(QColor(255, 255, 255, 140))
    painter.drawText(
        QRectF(MARGIN, image.height() - MARGIN - 24, WIDTH - MARGIN * 2, 24),
        Qt.AlignmentFlag.AlignRight,
        f"Modern Tiny Pedals · all {len(pixmaps)} widgets · simulated data",
    )
    painter.end()
    image.save(OUTPUT)
    print(f"saved {OUTPUT} {image.width()}x{image.height()} ({math.floor(os.path.getsize(OUTPUT) / 1024)} KB)")


if __name__ == "__main__":
    main()
