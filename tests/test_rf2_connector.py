"""rF2 shared memory connector on in-memory data: player sync, index override, resets, pause & resume, info"""

import threading
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


# --- Audit fixes (package A)
class FailingZone(Zone):
    """Zone whose shared memory exists with another size (older plugin, other tool)"""

    def __init__(self, data):
        super().__init__(None)
        self.closed = False

    def create(self, *args):
        raise PermissionError(5, "Access is denied")


class OpenedZone(Zone):
    def __init__(self, data):
        super().__init__(data)
        self.closed = False

    def create(self, *args):
        pass

    def close(self):
        self.closed = True


def test_shared_memory_open_failure_not_connected(monkeypatch):
    """Opening error must not stop app start: not connected state, stop safe"""
    from tinypedal import app_signal

    errors: list[str] = []
    app_signal.error.connect(errors.append)
    info = RF2Info()
    dataset = MemoryDataSet()
    dataset.scor = OpenedZone(rF2data.rF2Scoring())
    dataset.tele = FailingZone(None)
    dataset.live = (dataset.scor, dataset.tele, dataset.ext, dataset.ffb, dataset.rule)
    info._sync.dataset = dataset
    info.setReplay(None)
    try:
        info.start()  # no exception
        assert dataset.scor.closed  # zone opened before failure closed again
        assert info.isPaused and not info.isActive and not info._sync._updating
        assert "Access is denied" in info.openError and errors
        assert info.rf2ScorInfo.mCurrentET == 0.0 and info.rf2TeleVeh().mID == 0  # zeroed data readable
        assert info.rawData is not None
        info.stop()  # warning only, no crash on missing copy
    finally:
        app_signal.error.disconnect(errors.append)


def test_lmu_shared_memory_open_failure_not_connected():
    from tinypedal.adapter import lmu_connector

    info = lmu_connector.LMUInfo()
    info._sync.dataset.shmm = FailingZone(None)
    info._shmm = info._sync.dataset.shmm
    info.start()
    assert info.isPaused and not info.isActive and info.openError
    assert info.lmuScorInfo.mNumVehicles == 0 and info.lmuTeleVeh().mID == 0
    info.stop()


def test_gave_up_after_errors_hides_overlays(game, monkeypatch):
    """Update thread stopped after repeated crashes: no frozen values left visible"""
    info, _, _, _ = game
    info._sync.paused = False
    info._sync.synced = True
    monkeypatch.setattr(rf2_connector, "run_supervised", lambda *args: False)
    info._sync._SyncData__update(threading.Event())
    assert info._sync.paused and not info._sync.synced and not info.isActive


def test_lmu_gave_up_after_errors_hides_overlays(monkeypatch):
    from tinypedal.adapter import lmu_connector

    sync = lmu_connector.SyncData()
    sync.synced = True
    monkeypatch.setattr(lmu_connector, "run_supervised", lambda *args: False)
    sync._SyncData__update(threading.Event())
    assert sync.paused and not sync.synced


def test_lmu_telemetry_matched_on_active_vehicles():
    from pyLMUSharedMemory import lmu_data
    from tinypedal.adapter import lmu_connector

    telemetry = lmu_data.LMUTelemetryData()
    telemetry.activeVehicles = 2
    for index, slot_id in enumerate((7, 3, 9)):  # third entry left from a car that left
        telemetry.telemInfo[index].mID = slot_id
    indexes: dict = {}
    lmu_connector.SyncData._SyncData__update_tele_indexes(telemetry, indexes)
    assert indexes == {7: 0, 3: 1}


def test_telemetry_slots_forgotten_on_session_change(game):
    info, scor, tele, _ = game
    info.start()
    scor.mScoringInfo.mCurrentET = 50.0
    tele.mVehicles[0].mID = 42  # slot of current session
    assert wait_until(lambda: info._sync._tele_indexes.get(42) == 0)
    tele.mVehicles[0].mID = 5
    scor.mScoringInfo.mCurrentET = 1.0  # new session
    assert wait_until(lambda: 42 not in info._sync._tele_indexes)  # old slot forgotten
    assert info._sync._tele_indexes.get(5) == 0


def test_unknown_slot_never_reads_other_car_telemetry():
    """Slot id without telemetry match: zeroed telemetry, not another car (same index) or last entry"""
    from pyLMUSharedMemory import lmu_data
    from tinypedal.adapter import lmu_connector, rf2_connector

    assert rf2_connector.default_tele_indexes() == {} == lmu_connector.default_tele_indexes()
    # rF2
    info = rf2_connector.RF2Info()
    dataset = MemoryDataSet()
    info._sync.dataset = dataset
    info.setReplay(None)
    scor, tele = dataset.scor.data, dataset.tele.data
    scor.mScoringInfo.mNumVehicles = tele.mNumVehicles = 2
    scor.mVehicles[0].mID, scor.mVehicles[1].mID = 0, 1  # car 1 telemetry not received yet
    tele.mVehicles[0].mID, tele.mVehicles[1].mID = 0, 9
    tele.mVehicles[1].mEngineRPM = tele.mVehicles[-1].mEngineRPM = 8000.0
    sync = info._sync
    sync._SyncData__update_tele_indexes(1, tele, sync._tele_indexes)
    sync._SyncData__update_tele_map()
    assert info.rf2TeleVeh(1) is rf2_connector.EMPTY_TELE and info.rf2TeleVeh(1).mEngineRPM == 0.0
    sync.tele_map = rf2_connector.NO_TELE_MAP  # not mapped: matched on demand, same result
    assert info.rf2TeleVeh(1).mEngineRPM == 0.0
    # Player without telemetry index: zeroed, not last entry
    sync._SyncData__sync_player_tele(-1)
    assert sync.player_tele is rf2_connector.EMPTY_TELE
    # LMU
    from types import SimpleNamespace

    lmu = lmu_connector.LMUInfo()
    data = lmu_data.LMUObjectOut()
    zone = SimpleNamespace(data=data)
    lmu._sync.dataset.shmm = zone  # type: ignore[assignment]
    lmu._shmm = zone  # type: ignore[assignment]
    data.scoring.scoringInfo.mNumVehicles = 2
    data.telemetry.activeVehicles = 1
    data.scoring.vehScoringInfo[1].mID = 1
    data.telemetry.telemInfo[1].mEngineRPM = data.telemetry.telemInfo[-1].mEngineRPM = 8000.0
    lmu_sync = lmu._sync
    lmu_sync._SyncData__update_tele_indexes(data.telemetry, lmu_sync._tele_indexes)
    lmu_sync._SyncData__update_tele_map()
    assert lmu.lmuTeleVeh(1) is lmu_connector.EMPTY_TELE
    assert lmu.lmuTeleVeh(0).mEngineRPM == 0.0 and lmu.lmuTeleVeh(0) is not lmu_connector.EMPTY_TELE
    lmu_sync._SyncData__sync_player_tele(-1)
    assert lmu_sync.player_tele is lmu_connector.EMPTY_TELE


def test_rf2_replay_paused_state():
    dataset = MemoryDataSet()
    assert not dataset.replay_paused()
    dataset.scor.paused = True
    assert not dataset.replay_paused()  # live data never treated as replay
    dataset.replaying = True
    assert dataset.replay_paused()


# --- Audit fixes (thread & player index)
class StuckThread:
    """Update thread outliving stop() join"""

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return True


def test_stop_warns_on_thread_outliving_join_and_restart_uses_new_event(game, caplog):
    info, scor, _, _ = game
    sync: SyncData = info._sync
    info.start()
    old_thread, old_event = sync._update_thread, sync._event
    sync._update_thread = StuckThread()
    info.stop()
    assert "still stopping" in caplog.text
    info.start()  # restart never clears stop event of a thread still stopping
    assert old_event.is_set() and sync._event is not old_event and not sync._event.is_set()
    old_thread.join(5)
    assert not old_thread.is_alive()
    scor.mScoringInfo.mCurrentET = 1.0
    assert wait_until(lambda: not info.isPaused)  # new thread updating


def test_player_index_bound_by_vehicle_count(game):
    info, scor, _, _ = game
    scor.mVehicles[2].mIsPlayer = False
    scor.mVehicles[5].mIsPlayer = True  # stale slot beyond vehicle count
    scor.mVehicles[5].mID = 7
    info.start()
    assert info.playerIndex == INVALID_INDEX
    info.stop()
    scor.mScoringInfo.mNumVehicles = 6
    info.start()
    assert info.playerIndex == 5


def test_scoring_index_helpers_bound_by_vehicle_count():
    from pyLMUSharedMemory import lmu_data
    from tinypedal.adapter import lmu_connector

    vehicles = (rF2data.rF2VehicleScoring * 5)()
    vehicles[3].mIsPlayer = True
    vehicles[3].mID = 9
    assert rf2_connector.local_scoring_index(vehicles, 3) == INVALID_INDEX
    assert rf2_connector.local_scoring_index(vehicles, 4) == 3
    assert rf2_connector.local_scoring_index_by_id(9, vehicles, 3) == INVALID_INDEX
    assert rf2_connector.local_scoring_index_by_id(9, vehicles, 4) == 3
    lmu_vehicles = (lmu_data.LMUVehicleScoring * 5)()
    lmu_vehicles[3].mIsPlayer = True
    lmu_vehicles[3].mID = 9
    assert lmu_connector.local_scoring_index(lmu_vehicles, 2) == INVALID_INDEX
    assert lmu_connector.local_scoring_index(lmu_vehicles, 10**6) == 3  # clamped to maximum
    assert lmu_connector.local_scoring_index_by_id(9, lmu_vehicles, 2) == INVALID_INDEX
    assert lmu_connector.local_scoring_index_by_id(9, lmu_vehicles, 4) == 3


def test_lmu_restart_uses_new_event(monkeypatch, caplog):
    from tinypedal.adapter import lmu_connector

    class MemoryShmm(Zone):
        def __init__(self):
            super().__init__(lmu_connector.lmu_struct.LMUObjectOut())

    info = lmu_connector.LMUInfo()
    info._sync.dataset.shmm = MemoryShmm()
    info._shmm = info._sync.dataset.shmm
    sync = info._sync
    info.start()
    old_thread, old_event = sync._update_thread, sync._event
    sync._update_thread = StuckThread()
    info.stop()
    assert "still stopping" in caplog.text
    info.start()
    assert old_event.is_set() and sync._event is not old_event and not sync._event.is_set()
    old_thread.join(5)
    assert not old_thread.is_alive()
    info.stop()


def test_lmu_results_driver_key_with_parenthesis_and_xml_entities():
    """Incident driver key: name up to "(id) reported contact" (may contain parenthesis),
    XML entities decoded to match mDriverName"""
    from tinypedal.adapter import lmu_connector

    results = lmu_connector.LMUResults()
    results.update(
        b'<Incident et="120.0">Max (FR) Dupont(3) reported contact (12.5) with another vehicle B(4)\n'
        b'<Incident et="130.0">A &amp; B(5) reported contact (3.0) with Immovable\n'
        b'<TrackLimits et="140.0" Driver="O&apos;Neil" Lap="2" Resolution="Warning">Warning\n'
    )
    assert results.data[b"Max (FR) Dupont"]["contact_vehicle"] == 1
    assert results.data[b"A & B"]["contact_immovable"] == 1
    assert results.data[b"O'Neil"]["track_cut"] == 1
    assert set(results.data) == {b"Max (FR) Dupont", b"A & B", b"O'Neil"}
