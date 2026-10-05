"""API data readers (LMU native & rF2 plugin), fed with real shared memory structs (no game needed)

Contract: every reader method of both APIs must work on empty data (game in menu, loading)
and return the type declared in adapter/_reader.py. Unit conversions are checked on known values.
"""

import inspect
import math
import typing

import pytest

from pyLMUSharedMemory import lmu_data
from pyRfactor2SharedMemory import rF2data
from tinypedal import api_connector
from tinypedal.adapter import APIDataReader, _reader


def lmu_api() -> tuple[api_connector.SimLMU, lmu_data.LMUObjectOut]:
    """LMU API with zeroed shared memory, player at index 0"""
    sim = api_connector.SimLMU()
    info = sim._shmmapi
    data = lmu_data.LMUObjectOut()
    info._shmm.data = data
    info._sync.player_scor = data.scoring.vehScoringInfo[0]
    info._sync.player_tele = data.telemetry.telemInfo[0]
    info._sync.player_scor_index = 0
    return sim, data


def rf2_api() -> tuple[api_connector.SimRF2, typing.Any]:
    """rF2 API with zeroed shared memory, player at index 0"""
    sim = api_connector.SimRF2()
    info = sim._shmmapi
    info._scor.data = rF2data.rF2Scoring()
    info._tele.data = rF2data.rF2Telemetry()
    info._ext.data = rF2data.rF2Extended()
    info._ffb.data = rF2data.rF2ForceFeedback()
    info._rule.data = rF2data.rF2Rules()
    info._sync.player_scor = info._scor.data.mVehicles[0]
    info._sync.player_tele = info._tele.data.mVehicles[0]
    info._sync.player_scor_index = 0
    return sim, info


API_FACTORIES = {"lmu": lmu_api, "rf2": rf2_api}


def reader_methods(reader: APIDataReader):
    """(group name, method name, bound method, declared return type) of all reader methods"""
    for group_name, group in zip(reader._fields, reader):
        base = type(group).__mro__[1]  # _reader abstract class
        assert base.__module__ == _reader.__name__, group_name
        hints_owner = vars(_reader)
        for name, func in inspect.getmembers(base, inspect.isfunction):
            if name.startswith("_"):
                continue
            hints = typing.get_type_hints(func, globalns=hints_owner)
            yield group_name, name, getattr(group, name), hints.get("return")


def matches(value, expected) -> bool:
    """Check value against declared return type"""
    if expected is None or expected is typing.Any:
        return True
    origin = typing.get_origin(expected)
    if origin is typing.Union or (origin is not None and str(origin) == "<class 'types.UnionType'>"):
        return any(matches(value, arg) for arg in typing.get_args(expected))
    if expected is type(None):
        return value is None
    if origin is tuple:
        return isinstance(value, tuple)
    if origin is list:
        return isinstance(value, list)
    if origin is dict:
        return isinstance(value, dict)
    if expected is float:
        return isinstance(value, (int, float))
    if isinstance(expected, type):
        return isinstance(value, expected)
    return True


def all_numbers_finite(value) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, (tuple, list)):
        return all(all_numbers_finite(item) for item in value)
    return True


@pytest.mark.parametrize("api_name", API_FACTORIES)
def test_all_methods_on_empty_data(api_name):
    sim, _ = API_FACTORIES[api_name]()
    reader = sim.reader()
    checked = 0
    failures = []
    for group_name, name, method, expected in reader_methods(reader):
        try:
            value = method()
        except TypeError as error:
            if "required positional argument" in str(error):
                continue  # method needs explicit arguments
            failures.append(f"{group_name}.{name}: {error!r}")
            continue
        except Exception as error:
            failures.append(f"{group_name}.{name}: {error!r}")
            continue
        checked += 1
        if not matches(value, expected):
            failures.append(f"{group_name}.{name}: {value!r} is not {expected}")
    assert not failures, "\n".join(failures)
    assert checked > 150  # guard against silently skipping everything


@pytest.mark.parametrize("api_name", API_FACTORIES)
def test_methods_with_vehicle_index(api_name):
    """Opponent data path (index != None) on empty data"""
    sim, _ = API_FACTORIES[api_name]()
    checked = 0
    failures = []
    for group_name, name, method, expected in reader_methods(sim.reader()):
        if "index" not in inspect.signature(method).parameters:
            continue
        try:
            value = method(index=5)
        except Exception as error:
            failures.append(f"{group_name}.{name}: {error!r}")
            continue
        checked += 1
        if not matches(value, expected):
            failures.append(f"{group_name}.{name}: {value!r} is not {expected}")
    assert not failures, "\n".join(failures)
    assert checked > 50


@pytest.mark.parametrize("api_name", API_FACTORIES)
def test_readers_cover_same_methods(api_name):
    """Every abstract reader method is implemented"""
    sim, _ = API_FACTORIES[api_name]()
    for group in sim.reader():
        assert not getattr(type(group), "__abstractmethods__", None), type(group).__name__


def test_lmu_nan_values_sanitized():
    sim, data = lmu_api()
    reader = sim.reader()
    tele = data.telemetry.telemInfo[0]
    tele.mRearBrakeBias = float("nan")
    for index in range(4):
        tele.mWheels[index].mBrakeTemp = float("inf")
        tele.mWheels[index].mBrakePressure = float("nan")
    assert all_numbers_finite(reader.brake.bias_front())
    assert all_numbers_finite(reader.brake.temperature())
    assert all_numbers_finite(reader.brake.pressure())


def test_lmu_unit_conversion():
    sim, data = lmu_api()
    reader = sim.reader()
    tele = data.telemetry.telemInfo[0]
    tele.mRearBrakeBias = 0.44
    for index, kelvin in enumerate((573.15, 673.15, 473.15, 373.15)):
        tele.mWheels[index].mBrakeTemp = kelvin
    assert reader.brake.bias_front() == pytest.approx(0.56)
    assert reader.brake.temperature() == pytest.approx((300, 400, 200, 100))
    data.generic.gameVersion = 123
    assert reader.state.version() == "1.23"
    data.generic.gameVersion = 1
    assert reader.state.version() == "unknown"


def test_rf2_unit_conversion():
    sim, info = rf2_api()
    reader = sim.reader()
    tele = info._tele.data.mVehicles[0]
    tele.mRearBrakeBias = 0.4
    for index, kelvin in enumerate((573.15, 673.15, 473.15, 373.15)):
        tele.mWheels[index].mBrakeTemp = kelvin
    assert reader.brake.bias_front() == pytest.approx(0.6)
    assert reader.brake.temperature() == pytest.approx((300, 400, 200, 100))


@pytest.mark.parametrize("api_name", API_FACTORIES)
def test_same_input_same_output(api_name):
    """Both APIs agree on shared telemetry fields (same struct layout for vehicle telemetry)"""
    sim, _ = API_FACTORIES[api_name]()
    info = sim._shmmapi
    tele = info._sync.player_tele
    tele.mLocalVel.x, tele.mLocalVel.y, tele.mLocalVel.z = 3.0, 0.0, -4.0
    tele.mEngineRPM = 7000.0
    tele.mGear = 3
    reader = sim.reader()
    assert reader.vehicle.speed() == pytest.approx(5.0)
    assert reader.engine.rpm() == pytest.approx(7000.0)
    assert reader.engine.gear() == 3


# --- Audit fixes (package A): LMU data exposed in reader API
def test_lmu_extra_data():
    sim, data = lmu_api()
    reader = sim.reader()
    tele = data.telemetry.telemInfo[0]
    scor_info = data.scoring.scoringInfo
    tele.mDeltaBest = -0.25
    tele.mLapInvalidated = True
    tele.mTimeGapCarAhead, tele.mTimeGapCarBehind = 1.5, 2.5
    tele.mTimeGapPlaceAhead, tele.mTimeGapPlaceBehind = 3.5, 4.5
    tele.mWheels[2].mFlat = True
    tele.mWheels[0].mOptimalTemp = 85.0
    tele.mWheels[1].mOptimalTemp = 358.15  # Kelvin value: converted
    tele.mSpeedLimiterAvailable, tele.mSpeedLimiterActive = 1, True
    tele.mStateOfCharge = 64.0
    tele.mFrontRideHeight, tele.mRearRideHeight, tele.mDrag = 0.045, 0.07, 1500.0
    tele.mScheduledStops, tele.mOverheating = 2, True
    data.scoring.vehScoringInfo[0].mPitLapDist = 1234.5
    data.scoring.vehScoringInfo[0].mUnderYellow = True
    scor_info.mSessionTimeRemaining = 600.0
    scor_info.mYellowFlagState = b"\xff"
    scor_info.mSectorFlag[0] = 1  # game index 0 = sector 3
    scor_info.mWind.x, scor_info.mWind.z = 2.0, -3.0
    scor_info.mDarkCloud = 0.4
    scor_info.mIsFixedSetup = True
    data.telemetry.playerHasVehicle = True
    data.generic.events.SME_START_SESSION = 6
    assert reader.timing.delta_best() == pytest.approx(-0.25) and reader.lap.invalidated()
    assert (reader.timing.gap_car_ahead(), reader.timing.gap_car_behind()) == (1.5, 2.5)
    assert (reader.timing.gap_place_ahead(), reader.timing.gap_place_behind()) == (3.5, 4.5)
    assert reader.tyre.flat() == (False, False, True, False)
    assert reader.tyre.optimal_temperature()[:2] == pytest.approx((85.0, 85.0))
    assert reader.switch.speed_limiter_available() and reader.switch.speed_limiter_active()
    assert reader.emotor.state_of_charge() == 64.0
    assert reader.vehicle.ride_height_front() == pytest.approx(45.0)
    assert reader.vehicle.ride_height_rear() == pytest.approx(70.0)
    assert reader.vehicle.drag() == 1500.0 and reader.vehicle.scheduled_pitstops() == 2
    assert reader.engine.overheating()
    assert reader.lap.pit_box_distance() == pytest.approx(1234.5) and reader.lap.pit_box_distance(3) == -1.0
    assert reader.vehicle.under_yellow() and reader.vehicle.player_has_vehicle()
    assert reader.session.time_remaining() == 600.0 and reader.session.yellow_flag_state() == -1
    assert reader.session.sector_yellow_flags() == (False, False, True)
    assert reader.session.wind_velocity() == (2.0, 0.0, -3.0) and reader.session.dark_cloud() == pytest.approx(0.4)
    assert reader.session.fixed_setup()
    assert reader.state.session_events() == (True, False, False, False)


def test_rf2_extra_data_fallbacks():
    sim, info = rf2_api()
    reader = sim.reader()
    scor = info._scor.data
    scor.mScoringInfo.mNumVehicles = 3
    for index, (place, behind) in enumerate(((1, 0.0), (3, 4.0), (2, 1.5))):
        scor.mVehicles[index].mPlace = place
        scor.mVehicles[index].mTimeBehindNext = behind
    scor.mScoringInfo.mYellowFlagState = b"\x02"
    scor.mScoringInfo.mSectorFlag[1] = 1  # sector 1
    scor.mVehicles[0].mIsPlayer = True
    assert reader.timing.gap_place_behind() == 1.5  # car placed 2nd, behind player placed 1st
    assert reader.timing.gap_place_ahead(1) == 4.0
    assert reader.timing.gap_car_ahead() == 0.0 and not reader.lap.invalidated()
    assert reader.session.yellow_flag_state() == 2 and reader.session.sector_yellow_flags() == (True, False, False)
    assert reader.vehicle.player_has_vehicle() and reader.session.time_remaining() == 0.0
    assert reader.tyre.optimal_temperature() == (0.0, 0.0, 0.0, 0.0)
    assert reader.state.session_events() == (False, False, False, False)


@pytest.mark.parametrize("api_name", API_FACTORIES)
def test_player_only_rest_data(api_name):
    """Damage & brake wear from Rest API are local player data: neutral for other vehicles"""
    sim, _ = API_FACTORIES[api_name]()
    rest = sim._restapi_dataset
    rest.brakeWear = (0.03, 0.03, 0.02, 0.02)
    rest.aeroDamage = 0.2
    rest.suspensionDamage = (0.1, 0.0, 0.0, 0.0)
    reader = sim.reader()
    assert reader.brake.wear() == rest.brakeWear and reader.brake.wear(0) == rest.brakeWear  # player index 0
    assert reader.brake.wear(5) == (-1.0, -1.0, -1.0, -1.0)
    assert reader.vehicle.aero_damage() == 0.2 and reader.vehicle.aero_damage(5) == -1.0
    assert reader.wheel.suspension_damage(5) == (-1.0, -1.0, -1.0, -1.0)
