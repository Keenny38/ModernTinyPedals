"""rF2 shared memory connector on in-memory data: player sync, index override, resets, pause & resume, info"""

import time

import pytest

from tinypedal.adapter import rf2_connector
from tinypedal.adapter.rf2_connector import INVALID_INDEX, RF2Info, SyncData, rF2data


class Zone:
    """Shared memory zone kept in memory"""

    def __init__(self, data):
        self.data = data

    def create(self, *args):
        pass

    def update(self):
        pass

    def close(self):
        pass


class MemoryDataSet(rf2_connector.MMapDataSet):
    """Data set without real shared memory"""

    def __init__(self):  # super init would open shared memory
        self.scor = Zone(rF2data.rF2Scoring())
        self.tele = Zone(rF2data.rF2Telemetry())
        self.ext = Zone(rF2data.rF2Extended())
        self.ffb = Zone(rF2data.rF2ForceFeedback())
        self.rule = Zone(rF2data.rF2Rules())
        self.live = (self.scor, self.tele, self.ext, self.ffb, self.rule)
        self.replaying = False

    def __del__(self):
        pass


def wait_until(check, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def game(monkeypatch):
    """3 cars, player in scoring slot 2 (id 7) & telemetry slot 1, controllable clock"""
    clock = {"offset": 0.0}
    monkeypatch.setattr(rf2_connector, "monotonic", lambda: time.monotonic() + clock["offset"])
    info = RF2Info()
    dataset = MemoryDataSet()
    info._sync.dataset = dataset
    info.setReplay(None)  # zones from data set
    scor, tele = dataset.scor.data, dataset.tele.data
    scor.mScoringInfo.mNumVehicles = tele.mNumVehicles = 3
    for index, slot_id in enumerate((3, 5, 7)):
        scor.mVehicles[index].mID = slot_id
    for index, slot_id in enumerate((5, 7, 3)):
        tele.mVehicles[index].mID = slot_id
    scor.mVehicles[2].mIsPlayer = True
    tele.mVehicles[1].mIgnitionStarter = 1
    yield info, scor, tele, clock
    if info._sync._updating:
        info.stop()


def test_player_synced_and_resets_counted(game):
    info, scor, _, _ = game
    info.start()
    assert info.playerIndex == 2 and info.rf2ScorVeh().mID == 7 and info.rf2TeleVeh().mID == 7
    assert info.rf2TeleVeh(0).mID == 3  # telemetry slot matched by id
    scor.mScoringInfo.mCurrentET = 1.0  # data moving: resumed
    assert wait_until(lambda: info._sync.synced and not info.isPaused)
    assert info.isActive  # ignition on
    resets = info.vehicleResets
    scor.mVehicles[2].mInGarageStall = 1  # back to garage
    scor.mScoringInfo.mCurrentET = 2.0
    assert wait_until(lambda: info.vehicleResets == resets + 1)
    scor.mScoringInfo.mCurrentET = 1.5  # session restarted
    assert wait_until(lambda: info.vehicleResets == resets + 2)
    info.stop()
    assert info.rf2ScorVeh().mID == 7  # final copy kept after close


def test_pause_when_data_stops(game):
    info, scor, _, clock = game
    info.start()
    scor.mScoringInfo.mCurrentET = 1.0
    assert wait_until(lambda: not info.isPaused)
    clock["offset"] = 10.0  # no new data for 10 s
    assert wait_until(lambda: info.isPaused) and not info.isActive


def test_player_lost_then_index_override(game):
    info, scor, _, _ = game
    info.start()
    scor.mScoringInfo.mCurrentET = 1.0
    assert wait_until(lambda: info._sync.synced)
    scor.mVehicles[2].mIsPlayer = False  # player left: paused after 5 tries
    for step in range(8):
        scor.mScoringInfo.mCurrentET = 2.0 + step
        time.sleep(0.03)
    assert wait_until(lambda: info.playerIndex == INVALID_INDEX and not info._sync.synced)
    info.setPlayerOverride(True)  # spectate car id 5
    info.setPlayerIndex(5)
    scor.mScoringInfo.mCurrentET = 20.0
    assert wait_until(lambda: info.playerIndex == 1 and info.rf2ScorVeh().mID == 5)


def test_state_override_and_settings(game):
    info, _, _, _ = game
    info.setStateOverride(True)
    info.setActiveState(True)
    assert info.isActive
    info.setActiveState(False)
    assert not info.isActive
    info.setMode(1)
    info.setPID(1234)
    assert info._access_mode == 1 and info._rf2_pid == "1234"
    assert len(info.rawData) == sum(rf2_connector.ctypes.sizeof(struct) for _, struct in rf2_connector.REPLAY_ZONES)
    assert info.rf2Ext is not None and info.rf2Ffb is not None and info.rf2Rule is not None
    info._sync.stop()  # not started: warning only


def test_scoring_index_helpers():
    vehicles = (rF2data.rF2VehicleScoring * 3)()
    vehicles[1].mIsPlayer = True
    vehicles[2].mID = 9
    assert rf2_connector.local_scoring_index(vehicles) == 1
    assert rf2_connector.local_scoring_index_by_id(9, vehicles) == 2
    assert rf2_connector.local_scoring_index_by_id(4, vehicles) == INVALID_INDEX
    assert rf2_connector.replay_layout()[0][0] == "scor"
    copied = rf2_connector.copy_struct(vehicles[2])
    assert copied.mID == 9


def test_sync_data_double_start_warns(game):
    info, _, _, _ = game
    sync: SyncData = info._sync
    info.start()
    sync.start(0, "")  # already started: ignored
    assert sync._updating
