"""Vehicles module on a simulated LMU field: positions, pits, yellow flag, gaps, qualifying"""

import pytest

from tests.test_readers import lmu_api
from tinypedal.module import module_vehicles
from tinypedal.module_info import VehiclesInfo

# (driver, class, place, lap distance, speed m/s, in pits, total laps, qualification)
CARS = (
    ("Player", "LMP2", 2, 1000.0, 60.0, False, 10, 3),
    ("Leader", "LMP2", 1, 1200.0, 62.0, False, 10, 1),
    ("Pitting", "GT3", 3, 3900.0, 0.0, True, 10, 2),
    ("Slow", "GT3", 4, 1500.0, 3.0, False, 9, 4),
)


@pytest.fixture
def field(ui_env, monkeypatch):
    from tinypedal.api_control import api

    sim, data = lmu_api()
    info = data.scoring.scoringInfo
    info.mNumVehicles = len(CARS)
    info.mLapDist = 4000.0
    info.mCurrentET = 600.0
    info.mSession = 10  # race
    for index, (driver, class_name, place, distance, speed, in_pits, laps, qualify) in enumerate(CARS):
        car = data.scoring.vehScoringInfo[index]
        car.mID = index
        car.mDriverName = driver.encode()
        car.mVehicleName = f"{driver} car".encode()
        car.mVehicleClass = class_name.encode()
        car.mPlace = place
        car.mLapDist = distance
        car.mLocalVel.z = -speed
        car.mInPits = in_pits
        car.mTotalLaps = laps
        car.mQualification = qualify
        car.mIsPlayer = index == 0
        car.mBestLapTime = 95.0 + index
        car.mLastLapTime = 96.0 + index
        car.mEstimatedLapTime = 96.0
        car.mTimeIntoLap = distance / 4000 * 96
        car.mPos.x, car.mPos.z = index * 10.0, index * 5.0
        tele = data.telemetry.telemInfo[index]  # speed of every car from telemetry
        tele.mID = index
        tele.mLocalVel.z = -speed
        tele.mElapsedTime = 600.0
    monkeypatch.setattr(api, "_api", sim)
    monkeypatch.setattr(api, "read", sim.reader())
    output = VehiclesInfo()
    output.totalVehicles = len(CARS)
    return output


def test_vehicle_data_from_field(field):
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    cars = field.dataSet[:len(CARS)]
    assert field.playerIndex == 0 and cars[0].isPlayer
    assert field.leaderIndex == 1 and field.leaderBestLapTime == pytest.approx(96.0)
    assert [car.driverName for car in cars] == [car[0] for car in CARS]
    assert [car.positionOverall for car in cars] == [car[2] for car in CARS]
    assert cars[2].inPit and not cars[0].inPit
    assert (field.totalInPits, field.totalStoppedPits, field.totalOutPits) == (1, 1, 3)
    assert cars[3].isYellow and not cars[1].isYellow  # slow car on track
    assert field.nearestYellowAhead == pytest.approx(500.0)  # slow car 500 m ahead of player
    assert field.totalCompletedLaps == sum(car[6] for car in CARS)
    assert cars[1].currentLapProgress == pytest.approx(1200 / 4000)
    assert field.dataSetVersion == 0


def test_vehicle_history_reset_when_another_car_takes_index(field, monkeypatch):
    """Multiplayer: car leaves, game compacts vehicle array, next car takes its index"""
    monkeypatch.setattr(module_vehicles, "_index_slot_ids", {})
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    for car in field.dataSet[2:4]:
        car.lapTimeHistory[4] = 95.0
        car.fuelHistory.used = 2.5
        car.pitTimer.laps = 7
    timers = [(car.speedTrap, car.licoTimer) for car in field.dataSet[2:4]]
    from tinypedal.api_control import api
    api._api._shmmapi._shmm.data.scoring.vehScoringInfo[3].mID = 42  # another car now at index 3
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.1, True)
    kept, replaced = field.dataSet[2], field.dataSet[3]
    assert kept.lapTimeHistory[4] == 95.0 and kept.fuelHistory.used == 2.5
    assert (kept.speedTrap, kept.licoTimer) == timers[0]
    assert replaced.lapTimeHistory[4] == 0.0 and replaced.fuelHistory.used == 0.0
    assert replaced.pitTimer.laps == 0
    # Speed trap & lift and coast timer of new car, stint laps recalculated
    assert replaced.speedTrap is not timers[1][0] and replaced.licoTimer is not timers[1][1]
    assert replaced.currentStintLaps == 0


def test_slot_ids_forgotten_when_module_resets(field, monkeypatch):
    """New session (module reset): slot ids of previous session never reset history of new one"""
    from tinypedal import realtime_state
    from tinypedal.setting import cfg

    monkeypatch.setattr(module_vehicles, "_index_slot_ids", {0: 99, 7: 5})
    monkeypatch.setattr(realtime_state, "paused", False)
    module = module_vehicles.Realtime(cfg, "module_vehicles")
    waits = iter((True,))
    module._event.wait = lambda interval: next(waits, True)  # stop at once: reset branch not reached
    module.update_data()
    assert module_vehicles._index_slot_ids == {0: 99, 7: 5}
    waits = iter((False, True))
    module._event.wait = lambda interval: next(waits, True)  # one update then stop
    module.update_data()
    assert 7 not in module_vehicles._index_slot_ids  # cleared at reset, then filled from game
    assert module_vehicles._index_slot_ids.get(0, 0) == 0


def test_vehicle_data_high_priority_only(field):
    """Fast update: positions & pit state only, names & laps left for low priority update"""
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, False, 600.0, True)
    assert field.dataSet[1].driverName == ""
    assert field.dataSet[2].inPit
    assert field.nearestLine < 1e6  # straight line distance to nearest opponent


def test_qualify_position_by_class(field):
    module_vehicles.update_qualify_position(field)
    cars = field.dataSet[:len(CARS)]
    assert [car.qualifyOverall for car in cars] == [3, 1, 2, 4]
    assert [car.qualifyInClass for car in cars] == [2, 1, 1, 2]  # LMP2: leader 1st, GT3: pitting 1st


def test_class_gap_in_laps_or_time(field):
    assert module_vehicles.calc_time_gap_behind(-1, 0, 0.5) == 0.0  # no car ahead
    assert module_vehicles.calc_time_gap_behind(1, 3, 1.3) == 1  # a lap or more: laps
    gap = module_vehicles.calc_time_gap_behind(1, 0, 0.05)  # leader 200 m ahead
    assert gap == pytest.approx(200 / 4000 * 96, abs=0.01)


def test_stint_usage_from_history(field):
    data = field.dataSet[0]
    data.fuelHistory.laps = 12.0
    data.energyHistory.laps = 9.0
    module_vehicles.update_stint_usage(data, 0.5, 0.4)
    assert data.estimatedStintLaps == pytest.approx(9.0)  # energy runs out first
    module_vehicles.update_stint_usage(data, 0.5, 0.0)
    assert data.estimatedStintLaps == pytest.approx(12.0)  # fuel only


class CountedGroup:
    """Reader group, calls of one method recorded (index of each call)"""

    def __init__(self, group, *names: str):
        self._group = group
        self.calls: dict[str, list] = {name: [] for name in names}

    def __getattr__(self, name):
        method = getattr(self._group, name)
        if name not in self.calls:
            return method

        def counted(index=None, *args):
            self.calls[name].append(index)
            return method(index, *args)

        return counted


class CountedReader:
    """API reader, groups with counted method calls"""

    def __init__(self, reader):
        self._reader = reader
        self.groups: dict[str, CountedGroup] = {}

    def __getattr__(self, name):
        return self.groups.get(name) or getattr(self._reader, name)


def count_calls(monkeypatch, group_name: str, name: str) -> list:
    """Count calls of a reader method (index of each call)"""
    from tinypedal.api_control import api

    if not isinstance(api.read, CountedReader):
        monkeypatch.setattr(api, "read", CountedReader(api.read))
    reader = api.read
    group = reader.groups.setdefault(group_name, CountedGroup(getattr(reader._reader, group_name)))
    group.calls[name] = []
    return group.calls[name]


def test_scoring_data_read_on_scoring_update_or_in_pits_only(field, monkeypatch):
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    distance_calls = count_calls(monkeypatch, "lap", "distance")
    laps_calls = count_calls(monkeypatch, "lap", "completed_laps")
    # High priority update between two scoring updates: only the car in pits (pit timer)
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, False, 600.01, True, update_scoring=False)
    assert [index for index in distance_calls if index is not None] == [2]
    assert [index for index in laps_calls if index is not None] == [2]
    assert field.dataSet[2].inPit and field.dataSet[3].isYellow  # kept from last scoring update
    # Scoring updated: every car read
    distance_calls.clear()
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, False, 600.02, True, update_scoring=True)
    assert sorted(index for index in distance_calls if index is not None) == [0, 1, 2, 3]


def test_lift_and_coast_inputs_read_after_telemetry_update_only(field, monkeypatch):
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, True, 600.0, True)
    throttle_calls = count_calls(monkeypatch, "inputs", "throttle_raw")
    module_vehicles.update_vehicle_data(field, 1.0, 1.0, False, 600.01, True, update_scoring=False)
    assert throttle_calls == [0]  # player (own telemetry time changed), opponents' telemetry unchanged
    lico = field.dataSet[1].licoTimer
    assert lico.input_time == 600.0 and lico.throttle == 0.0
