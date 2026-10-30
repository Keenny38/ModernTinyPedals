"""Audit I lot B1: shared memory acquisition, replay & supervision

Direct access mmap closed on stop, Rest API snapshot validation, player accessors defaults, track limits parse,
activity signal threads, zeroed player scoring while not synced, update loop never dead, results purged on session
change, replay zone copy, player index fast path, LMU copy header compare, recording stop & rate, API stop split.
"""

import ctypes
import gc
import logging
import mmap
import threading
import time
from types import SimpleNamespace

import pytest

from neopedal import overlay_signal, realtime_state, thread_guard
from neopedal.adapter import _sync, lmu_connector, restapi_connector, rf2_connector
from neopedal.penalty_info import Penalty
from neopedal.replay import RecordingSources, ReplayControl, ReplayFile, ReplayMMap, ReplayPlayer, apply_rest_snapshot
from pyLMUSharedMemory import lmu_data, lmu_mmap
from tests.test_replay import Clock, make_frames, write_replay
from tests.test_restapi_connector import TASKS, config
from tests.test_rf2_connector import game, wait_until  # noqa: F401


class MemoryShmm:
    """LMU shared memory zone kept in memory (no mmap), same interface as MMapControl"""

    def __init__(self):
        self.data = lmu_data.LMUObjectOut()
        self.closed = False

    def create(self, *args):
        pass

    def update(self):
        return None  # unknown whether changed, like direct access

    def close(self):
        self.closed = True


@pytest.fixture
def lmu_sync():
    """LMU sync data on in-memory structure, 3 cars, player in scoring slot 2 (id 7), telemetry slot 1"""
    sync = lmu_connector.SyncData()
    shmm = MemoryShmm()
    sync.dataset.shmm = shmm
    data = shmm.data
    data.scoring.scoringInfo.mNumVehicles = 3
    data.telemetry.activeVehicles = 3
    for index, slot_id in enumerate((3, 5, 7)):
        data.scoring.vehScoringInfo[index].mID = slot_id
        data.scoring.vehScoringInfo[index].mDriverName = b"Driver %d" % slot_id
    for index, slot_id in enumerate((5, 7, 3)):
        data.telemetry.telemInfo[index].mID = slot_id
    data.scoring.vehScoringInfo[2].mIsPlayer = True
    yield sync, data
    if sync._updating:
        sync.stop()


def anonymous_mmap(name, size):
    """Anonymous mapping instead of a named one (no game, no file in /dev/shm)"""
    return mmap.mmap(-1, size)


# --- BUG-010: direct access mmap closed on stop
def test_direct_access_mmap_closed_on_stop(monkeypatch, caplog):
    """Update loop's reference to the live structure released before close: no BufferError, mapping closed"""
    monkeypatch.setattr(lmu_mmap, "platform_mmap", anonymous_mmap)
    sync = lmu_connector.SyncData()
    sync.start(1)
    assert wait_until(lambda: sync._last_data is not None)  # loop read the live structure
    with caplog.at_level(logging.ERROR):
        sync.stop()
    assert sync.dataset.shmm._mmap_buffer.closed
    assert not any("buffer error" in record.message for record in caplog.records)
    assert sync.player_scor.mID == 0 and sync.player_tele.mID == 0  # final copies still readable


def test_close_mmap_retries_after_garbage_collection(caplog):
    """A view of the mapping kept alive only by a reference cycle never leaves it open"""
    buffer = mmap.mmap(-1, 64)
    gc.disable()
    try:
        view = (ctypes.c_char * 64).from_buffer(buffer)
        cycle = [view]
        cycle.append(cycle)
        del view, cycle
        with pytest.raises(BufferError):
            buffer.close()
        with caplog.at_level(logging.ERROR):
            assert lmu_mmap.close_mmap(buffer, "test")
    finally:
        gc.enable()
    assert buffer.closed and not caplog.records


# --- BUG-011: Rest API snapshot of another shape
class Node(tuple):
    """Named tuple like node of 4 fields"""
    _fields = ("a", "b", "c", "d")

    def __new__(cls, a, b, c, d):
        return super().__new__(cls, (a, b, c, d))


class RestData:
    __slots__ = ("nodes", "values", "scalar")

    def __init__(self):
        self.nodes = (Node(1, 2, 3, 4),)
        self.values = (1.0, 2.0)
        self.scalar = 5.0


def test_rest_snapshot_of_another_shape_keeps_current_values(caplog):
    data = RestData()
    with caplog.at_level(logging.WARNING):
        apply_rest_snapshot(data, {"nodes": [[1, 2, 3, 4, 5]], "values": None, "scalar": 7.0})  # old file
        apply_rest_snapshot(data, {"nodes": ["abcd"]})  # string is not a node
        apply_rest_snapshot(data, {"nodes": 3})
    assert data.nodes == (Node(1, 2, 3, 4),) and data.values == (1.0, 2.0) and data.scalar == 7.0
    assert sum("nodes" in record.message for record in caplog.records) == 1  # logged once per field
    apply_rest_snapshot(data, {"nodes": [[5, 6, 7, 8], (9, 10, 11, 12)], "values": [3.0]})
    assert data.nodes == (Node(5, 6, 7, 8), Node(9, 10, 11, 12)) and type(data.nodes[1]) is Node
    assert data.values == (3.0,)


# --- BUG-012: lmuPenalty & lmuResults without index read the local player
def test_lmu_penalty_and_results_default_to_player(lmu_sync):
    sync, data = lmu_sync
    info = lmu_connector.LMUInfo()
    info._sync = sync
    info._shmm = sync.dataset.shmm
    data.scoring.vehScoringInfo[-1].mDriverName = b"Last slot"
    sync.results.penalties = {b"Driver 7": Penalty(1, "Drive Thru", 0, 0, False), b"Last slot": Penalty(2)}
    sync.results.data = {b"Driver 7": {"track_cut": 3}, b"Last slot": {"track_cut": 9}}
    sync._SyncData__sync_player_data()
    assert info.lmuPenalty().pending == 1 and info.lmuResults()["track_cut"] == 3
    assert info.lmuPenalty(2).pending == 1 and info.lmuResults(2)["track_cut"] == 3


# --- BUG-013: track limits line without closing quote
def test_track_limits_line_cut_ignored():
    results = lmu_connector.LMUResults()
    results.update(b'<TrackLimits et="10.0" Driver="Keenny Hess" Action="Warning">\n<TrackLimits et="11.0" Driver="Flo')
    assert results.data[b"Keenny Hess"]["track_cut"] == 1
    assert b"Fl" not in results.data and b"Flo" not in results.data  # no ghost driver of a cut name


# --- BUG-014: activity signal removed (follow-up): a change notified from a data thread emits no Qt signal
def test_activity_change_notified_from_worker_thread():
    assert not hasattr(overlay_signal, "activity")
    version = realtime_state.version
    worker = threading.Thread(target=realtime_state.notify_change)
    worker.start()
    worker.join(5)
    assert realtime_state.version == version + 1


# --- BUG-037: zeroed player scoring while not synced
def test_player_scoring_zeroed_while_not_synced(lmu_sync):
    sync, data = lmu_sync
    data.scoring.vehScoringInfo[-1].mID = 99  # stale last slot of a dense session
    sync._SyncData__sync_player_scor()
    assert sync.player_scor is lmu_connector.EMPTY_SCOR and sync.player_scor.mID == 0
    rf2 = rf2_connector.SyncData.__new__(rf2_connector.SyncData)
    _sync.SyncData.__init__(rf2, SimpleNamespace(scor=SimpleNamespace(data=rf2_connector.rF2data.rF2Scoring())))
    rf2._scor_rows = rf2_connector.NO_ROWS
    rf2._SyncData__sync_player_scor()
    assert rf2.player_scor is rf2_connector.EMPTY_SCOR


def test_no_reset_counted_while_player_not_synced(game):  # noqa: F811
    """Player car gone & back in the same slot: no reset from the zeroed structure (slot id 0)"""
    info, scor, _, _ = game
    scor.mScoringInfo.mCurrentET = 10.0  # data not frozen: synced state set by update loop
    info.start()
    assert wait_until(lambda: info._sync.synced and info.playerIndex == 2)
    scor.mScoringInfo.mCurrentET = 11.0  # first tick with a player slot id: one reset by construction
    assert wait_until(lambda: info.vehicleResets == 1)
    resets = info.vehicleResets
    scor.mVehicles[2].mIsPlayer = False
    for _ in range(40):  # elapsed time keeps moving while unsynced
        scor.mScoringInfo.mCurrentET += 1.0
        time.sleep(0.02)
        if not info._sync.synced:
            break
    assert not info._sync.synced and info.rf2ScorVeh() is rf2_connector.EMPTY_SCOR
    for _ in range(5):
        scor.mScoringInfo.mCurrentET += 1.0
        time.sleep(0.03)
    scor.mVehicles[2].mIsPlayer = True
    for _ in range(40):
        scor.mScoringInfo.mCurrentET += 1.0
        time.sleep(0.02)
        if info._sync.synced:
            break
    assert info._sync.synced and info.rf2ScorVeh().mID == 7
    assert info.vehicleResets == resets


# --- BUG-038: update loop never dead while not stopped
def test_run_supervised_keeps_restarting_with_growing_delays(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(thread_guard, "monotonic", lambda: clock[0])
    calls, errors, waits = [], [], []
    event = threading.Event()
    monkeypatch.setattr(event, "wait", lambda delay: waits.append(delay) or False)

    def target():
        calls.append(clock[0])
        clock[0] += 1.0
        if len(calls) <= 7:
            raise RuntimeError("torn read")

    assert thread_guard.run_supervised(
        target, "test", event, max_restarts=3, restart_delay=1.0, retry_delays=(2.0, 5.0),
        on_error=lambda: errors.append(len(calls)))
    assert len(calls) == 8 and len(errors) == 7
    assert waits == [1.0, 1.0, 1.0, 2.0, 5.0, 5.0, 5.0]  # budget, then growing delays, last one repeated


def test_run_supervised_retry_cancelled_by_stop(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(thread_guard, "monotonic", lambda: clock[0])
    event = threading.Event()
    calls = []

    def target():
        calls.append(1)
        if len(calls) == 4:
            event.set()  # stopped while in the retry phase
        raise RuntimeError("torn read")

    assert not thread_guard.run_supervised(target, "test", event, max_restarts=3, restart_delay=0, retry_delays=(0,))
    assert len(calls) == 4


def test_sync_update_loop_retries_and_hides_overlays_meanwhile(lmu_sync, monkeypatch):
    sync, _ = lmu_sync
    seen = {}

    def supervised(target, name, event, max_restarts, restart_delay, retry_delays, on_error):
        seen["retry_delays"] = retry_delays
        on_error()
        return False

    monkeypatch.setattr(_sync, "run_supervised", supervised)
    sync.synced = True
    sync._SyncData__update(threading.Event())
    assert seen["retry_delays"] == _sync.RETRY_DELAYS and sync.paused and not sync.synced


# --- BUG-039: results purged when session changed with a larger elapsed time
def test_results_purged_on_session_change_with_larger_elapsed_time(lmu_sync):
    sync, data = lmu_sync
    scor_info = data.scoring.scoringInfo
    scor_info.mTrackName = b"Spa"
    scor_info.mSession = 1
    scor_info.mCurrentET = 1800.0
    data.scoring.scoringStream = b'<TrackLimits et="10.0" Driver="Driver 7" Action="Warning">\n'
    sync.start(0)
    assert wait_until(lambda: sync.results.data.get(b"Driver 7", {}).get("track_cut") == 1)
    # Joined a race on another track, further into its session
    scor_info.mTrackName = b"Le Mans"
    scor_info.mSession = 10
    scor_info.mCurrentET = 4000.0
    data.scoring.scoringStream = b""
    assert wait_until(lambda: not sync.results.data)
    assert sync.results.timestamp == 4000.0


# --- PERF-011: replay zone copied from a view of the frame
def test_replay_zones_copy_without_slicing(tmp_path):
    clock = Clock()
    player = ReplayPlayer(ReplayFile(write_replay(tmp_path, make_frames(20, 8))), clock=clock)
    whole = ReplayMMap(ctypes.c_char * 8, player, 0)
    primary = ReplayMMap(ctypes.c_char * 4, player, 0)
    secondary = ReplayMMap(ctypes.c_char * 4, player, 4, primary=False)
    assert whole._whole and not primary._whole and not secondary._whole
    for zone in (whole, primary, secondary):
        zone.create()
    clock.now = 0.5
    for zone in (whole, primary, secondary):
        zone.update()
    frame = player.replay.frame(5)
    assert bytes(whole.data) == frame and bytes(primary.data) + bytes(secondary.data) == frame


# --- PERF-012: player index fast path & cached wrappers
def test_player_index_fast_path_and_cached_wrappers(lmu_sync, monkeypatch):
    sync, data = lmu_sync
    assert sync._player_scoring_index() == 2
    sync.player_scor_index = 2
    monkeypatch.setattr(lmu_connector, "local_scoring_index", lambda *args: pytest.fail("scanned"))
    assert sync._player_scoring_index() == 2  # last index still the player: no scan
    sync._SyncData__sync_player_scor(2)
    sync._SyncData__sync_player_tele(1)
    rows = sync.vehicle_rows(data)
    assert sync.player_scor is rows[1][2] and sync.player_tele is rows[2][1]
    monkeypatch.undo()
    data.scoring.vehScoringInfo[2].mIsPlayer = False
    data.scoring.vehScoringInfo[0].mIsPlayer = True
    assert sync._player_scoring_index() == 0  # player moved: scanned again
    sync.override_player_index = True
    sync.player_slot_id = 5
    sync.player_scor_index = 1
    monkeypatch.setattr(lmu_connector, "local_scoring_index_by_id", lambda *args: pytest.fail("scanned"))
    assert sync._player_scoring_index() == 1
    sync.player_scor_index = 2  # slot id of last index differs: scanned
    monkeypatch.undo()
    assert sync._player_scoring_index() == 1


# --- PERF-013: LMU copy access compares sample times before the whole structure
def test_lmu_copy_access_header_compare_keeps_copy_semantics(monkeypatch):
    monkeypatch.setattr(lmu_mmap, "platform_mmap", anonymous_mmap)
    control = lmu_mmap.MMapControl("test", lmu_data.LMUObjectOut)
    control.create(0)
    live = lmu_data.LMUObjectOut.from_buffer(control._mmap_buffer)
    live.generic.events.SME_UPDATE_TELEMETRY = 1
    assert control.update() is True  # events changed: copied
    assert control.update() is False  # same data: not copied
    live.scoring.scoringInfo.mCurrentET = 12.5
    assert control.update() is True and control.data.scoring.scoringInfo.mCurrentET == 12.5
    live.telemetry.telemInfo[0].mElapsedTime = 12.51
    assert control.update() is True and control.data.telemetry.telemInfo[0].mElapsedTime == 12.51
    live.scoring.scoringStream = b"<Incident>"  # same sample times, other data: full compare still copies
    assert control.update() is True and control.data.scoring.scoringStream == b"<Incident>"
    assert control.update() is False
    del live
    control.close()
    assert control._mmap_buffer.closed and control.data.scoring.scoringInfo.mCurrentET == 12.5


# --- PERF-014: recording stop waits outside the recording lock
def test_stop_recording_joins_outside_lock():
    control = ReplayControl()
    joined = []

    class Recorder:
        def is_alive(self):
            return not joined

        def join(self, timeout):
            assert not control._rec_lock.locked()  # recorder module may start (and be refused) meanwhile
            joined.append(timeout)

    control._rec_thread = Recorder()
    control.stop_recording()
    assert joined == [5.0] and control._rec_thread is None and not control.recording_closing
    control._rec_thread = Recorder()
    joined.clear()
    control.stop_recording(timeout=0)  # only signalled
    assert not joined and control.recording_closing and control._rec_event.is_set()


# --- PERF-053: recording rate compensated for processing time
def test_recording_rate_compensates_processing_time(tmp_path, monkeypatch):
    from neopedal import replay as replay_module

    clock = [0.0]

    class FakeTime:
        """Monotonic clock advanced by waits & processing, other time functions real"""
        monotonic = staticmethod(lambda: clock[0])

        def __getattr__(self, name):
            return getattr(time, name)

    class Stop:
        def wait(self, timeout):
            clock[0] += timeout
            return clock[0] >= 1.0

    def frame():
        clock[0] += 0.002  # processing of a frame: copy, XOR, compression
        return b"abcd"

    monkeypatch.setattr(replay_module, "time", FakeTime())
    control = ReplayControl()
    filename = str(tmp_path / "rate.tpreplay")
    control._ReplayControl__recording(filename, RecordingSources(frame), 100, None, Stop())
    assert 98 <= control.recorded_frames <= 100  # 83 with wait + processing per frame
    assert ReplayFile(filename).duration == pytest.approx(0.99, abs=0.02)


# --- PERF-052: API threads signalled then waited, no join in Rest API start
def test_sync_request_stop_then_wait_stopped(game):  # noqa: F811
    info, _, _, _ = game
    info.start()
    sync = info._sync
    thread = sync._update_thread
    sync.request_stop()
    assert sync._updating and sync._event.is_set()
    assert sync.wait_stopped(timeout=5)
    assert not thread.is_alive() and not sync._updating and sync._last_data is None
    assert sync.wait_stopped() is True  # already stopped


def test_restapi_start_never_waits_previous_thread(monkeypatch):
    runs = []
    monkeypatch.setattr(
        restapi_connector.RestAPIConnector, "_RestAPIConnector__update",
        lambda self, event, state: runs.append((event, state)))
    connector = restapi_connector.RestAPIConnector(TASKS, SimpleNamespace())
    connector.setConnection(config(1))

    class Stuck:
        def is_alive(self):
            return True

        def join(self, timeout=None):
            pytest.fail("start waited a previous thread")

    connector._update_thread = Stuck()
    connector.start()
    assert len(runs) == 1 and connector._update_thread is not Stuck
    connector.request_stop()
    assert connector._updating and connector._event.is_set() and connector._state.wake.is_set()
    assert connector.wait_stopped(timeout=5) and not connector._updating
