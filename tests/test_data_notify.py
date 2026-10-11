"""Event-driven data modules: connector notifies new game data, modules wait for it instead of polling"""

import csv
import ctypes
import io
import json
import random
import threading
import time
from types import SimpleNamespace

import pytest

from tinypedal.adapter import data_notify, lmu_connector, rf2_connector
from tinypedal.adapter.data_notify import DataNotifier
from tinypedal.module import _base, module_delta, module_recorder


@pytest.fixture
def notifier(monkeypatch):
    """Fresh notifier used by modules & connectors"""
    fresh = DataNotifier()
    monkeypatch.setattr(data_notify, "notifier", fresh)
    monkeypatch.setattr(_base, "notifier", fresh)
    monkeypatch.setattr(lmu_connector, "notifier", fresh)
    monkeypatch.setattr(rf2_connector, "notifier", fresh)
    monkeypatch.setattr(module_delta, "notifier", fresh)
    return fresh


def make_module(active=0.01, idle=0.4):
    """Data module without settings"""
    module = _base.DataModule.__new__(_base.DataModule)
    module.module_name = "module_test"
    module.closed = True
    module.discard = False
    module._event = threading.Event()
    module._done = threading.Event()
    module._done.set()
    module._wake = threading.Event()
    module.active_interval = active
    module.idle_interval = idle
    module._max_wait = max(active, min(idle, _base.DATA_MAX_WAIT))
    return module


# --- Notifier
def test_notifier_sets_subscribed_events():
    notifier = DataNotifier()
    plain, derived = threading.Event(), threading.Event()
    notifier.subscribe(plain)
    notifier.subscribe(derived, derived=True)
    notifier.subscribe(plain)  # once only
    assert not notifier.available
    notifier.notify_derived()
    assert derived.is_set() and not plain.is_set()
    derived.clear()
    notifier.notify()
    assert plain.is_set() and derived.is_set()
    notifier.unsubscribe(plain)
    notifier.unsubscribe(derived)
    assert notifier._data_events == () == notifier._derived_events


def test_notifier_attach_detach_wakes_modules():
    notifier = DataNotifier()
    event = threading.Event()
    notifier.subscribe(event)
    notifier.attach()
    notifier.attach()
    assert notifier.available and event.is_set()
    event.clear()
    notifier.detach()
    assert notifier.available and event.is_set()  # other connector thread still running
    notifier.detach()
    notifier.detach()  # never negative
    assert not notifier.available and notifier._sources == 0


# --- Module wait
class RecordingEvent:
    """Stop event recording waits, never set"""

    def __init__(self):
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return False

    def is_set(self):
        return False


def test_wait_polls_at_interval_without_connector(notifier):
    module = make_module()
    module._event = RecordingEvent()
    module._wake = None  # never used without connector
    assert module.wait_update(0.01) is False
    assert module._event.waits == [0.01]


def test_wait_polls_at_idle_interval(notifier):
    notifier.attach()
    module = make_module()
    module._event = RecordingEvent()
    module._wake = None  # never used: idle interval longer than longest data wait
    assert module.wait_update(module.idle_interval) is False


def test_wait_returns_at_once_after_data_notified_meanwhile(notifier):
    notifier.attach()
    module = make_module()
    notifier.subscribe(module._wake)
    notifier.notify()  # data arrived while module was updating
    started = time.monotonic()
    assert module.wait_update(0.01) is False
    assert time.monotonic() - started < 0.09
    assert not module._wake.is_set()  # consumed


def test_wait_for_new_data_up_to_longest_wait(notifier):
    notifier.attach()
    module = make_module()
    module._max_wait = 0.3
    notifier.subscribe(module._wake)
    module._wake.clear()
    started = time.monotonic()
    assert module.wait_update(0.01) is False
    assert time.monotonic() - started >= 0.25  # no new data: longest wait
    timer = threading.Timer(0.05, notifier.notify)
    timer.start()
    started = time.monotonic()
    assert module.wait_update(0.01) is False
    assert time.monotonic() - started < 0.25  # woken by new data
    timer.join()


def test_stop_wakes_module_waiting_for_data(notifier):
    notifier.attach()

    class Waiting(_base.DataModule):
        __slots__ = ()

        def update_data(self):
            while not self.wait_update(self.active_interval):
                pass

    module = make_module()
    module.__class__ = Waiting
    module._max_wait = 30.0
    module.start()
    assert wait_until(lambda: module._wake in notifier._data_events)
    time.sleep(0.05)
    started = time.monotonic()
    module.stop()
    assert module.wait_closed(5) and time.monotonic() - started < 1.0
    assert module._wake not in notifier._data_events  # unsubscribed once stopped


def test_derived_modules_subscribed_to_derived_data():
    from tinypedal.module import module_fuel, module_notes, module_vehicles

    assert module_fuel.Realtime.WAKE_ON_DERIVED and module_notes.Realtime.WAKE_ON_DERIVED
    assert not module_vehicles.Realtime.WAKE_ON_DERIVED and not module_delta.Realtime.WAKE_ON_DERIVED


def wait_until(check, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.01)
    return False


# --- Wake-up count: 10 ms module, connector at 50 Hz telemetry
def count_loops(notifier, attach: bool, rate: float, duration: float = 0.6) -> tuple[int, int]:
    """Module loop iterations & notifications in duration, connector notifying at rate (Hz, 0: no data)"""
    loops = [0]

    class Counting(_base.DataModule):
        __slots__ = ()

        def update_data(self):
            while not self.wait_update(self.active_interval):
                loops[0] += 1

    module = make_module()
    module.__class__ = Counting
    stop = threading.Event()
    notified = [0]

    def connector():
        if attach:
            notifier.attach()
        try:
            while not stop.wait(1 / rate if rate else duration):
                if rate:
                    notifier.notify()
                    notified[0] += 1
        finally:
            if attach:
                notifier.detach()

    feeder = threading.Thread(target=connector, daemon=True)
    feeder.start()
    module.start()
    time.sleep(duration)
    module.stop()
    stop.set()
    assert module.wait_closed(5)
    feeder.join(5)
    return loops[0], notified[0]


def test_wakeups_follow_game_data(notifier):
    duration = 0.6
    polling, _ = count_loops(notifier, attach=False, rate=0, duration=duration)
    no_data, _ = count_loops(notifier, attach=True, rate=0, duration=duration)
    with_data, notified = count_loops(notifier, attach=True, rate=50, duration=duration)
    # No new data: woken by longest wait only (10 per second)
    assert no_data <= duration / _base.DATA_MAX_WAIT + 3
    assert no_data < polling
    # New data at 50 Hz: about once per notification, never more often than update interval
    assert with_data <= notified + 4
    assert with_data >= no_data


# --- Shared memory copy reports new data
def test_lmu_copy_reports_new_data():
    from pyLMUSharedMemory import lmu_data
    from pyLMUSharedMemory.lmu_mmap import MMapControl

    size = ctypes.sizeof(lmu_data.LMUObjectOut)
    shared = bytearray(size)  # stands for game shared memory
    control = MMapControl("test", lmu_data.LMUObjectOut)
    control._mmap_buffer = shared
    control._buffer[:] = shared
    control._realtime = lmu_data.LMUObjectOut.from_buffer(shared)
    control.data = lmu_data.LMUObjectOut.from_buffer(control._buffer)
    update = control._MMapControl__buffer_copy
    live = control._realtime
    live.scoring.scoringInfo.mCurrentET = 5.0
    assert update() is False and control.data.scoring.scoringInfo.mCurrentET == 0.0  # game not updating
    live.generic.events.SME_UPDATE_TELEMETRY = 1
    assert update() is True and control.data.scoring.scoringInfo.mCurrentET == 5.0
    assert update() is False  # same data
    live.generic.FFBTorque = 0.5
    assert update() is True and control.data.generic.FFBTorque == 0.5
    live.scoring.scoringInfo.mNumVehicles = 2  # telemetry not updated yet for all vehicles
    live.scoring.scoringInfo.mCurrentET = 6.0
    assert update() is False and control.data.scoring.scoringInfo.mCurrentET == 5.0
    assert bytes(control._buffer) != bytes(shared)


def test_rf2_copy_reports_new_data():
    from pyRfactor2SharedMemory import rF2data
    from pyRfactor2SharedMemory.rF2MMap import MMapControl

    shared = bytearray(ctypes.sizeof(rF2data.rF2Scoring))
    control = MMapControl("test", rF2data.rF2Scoring)
    control._mmap_buffer = shared
    control._buffer[:] = shared
    control.data = rF2data.rF2Scoring.from_buffer(control._buffer)
    control._version = rF2data.rF2MappedBufferVersionBlock.from_buffer(shared)
    control.set_scratch(bytearray(len(shared)))
    live = rF2data.rF2Scoring.from_buffer(shared)
    update = control._MMapControl__buffer_copy
    assert update() is False
    live.mVersionUpdateBegin = 1  # game writing
    live.mScoringInfo.mCurrentET = 3.0
    assert update() is False
    live.mVersionUpdateEnd = 1  # written
    assert update() is True and control.data.mScoringInfo.mCurrentET == 3.0
    assert update() is False


class WriteWhileCopying(bytearray):
    """Scratch copy buffer: plugin writes while copying (version at start of data copied first, then body)

    writes: per copy, "full" (write started & finished) or "start" (still writing after copy).
    """

    def __init__(self, size, live):
        super().__init__(size)
        self.live = live
        self.writes: list[str] = []

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if self.writes:
            write = self.writes.pop(0)
            self.live.mVersionUpdateBegin += 1
            self.live.mScoringInfo.mCurrentET += 1.0
            if write == "full":
                self.live.mVersionUpdateEnd += 1


@pytest.mark.parametrize("writes, first_result", ((["full"], True), (["start"], False), (["full", "full"], False)))
def test_rf2_copy_overlapping_plugin_write(writes, first_result):
    """Copy overlapping a plugin write: copied again once if written, else not reported & data copy left
    unchanged (never torn), copied next update"""
    from pyRfactor2SharedMemory import rF2data
    from pyRfactor2SharedMemory.rF2MMap import MMapControl

    shared = bytearray(ctypes.sizeof(rF2data.rF2Scoring))
    live = rF2data.rF2Scoring.from_buffer(shared)
    control = MMapControl("test", rF2data.rF2Scoring)
    control._mmap_buffer = shared
    scratch = WriteWhileCopying(len(shared), live)
    control._buffer = bytearray(len(shared))
    control.data = data = rF2data.rF2Scoring.from_buffer(control._buffer)
    control._version = rF2data.rF2MappedBufferVersionBlock.from_buffer(shared)
    control.set_scratch(scratch)
    update = control._MMapControl__buffer_copy
    live.mVersionUpdateBegin = live.mVersionUpdateEnd = 1  # written
    scratch.writes = list(writes)
    assert update() is first_result
    if not first_result:
        # Torn copy never reported as new data, nor kept: data copy as before
        assert bytes(control._buffer) == bytes(len(shared))
        live.mVersionUpdateEnd = live.mVersionUpdateBegin  # write finished
        assert update() is True
    assert data.mVersionUpdateBegin == data.mVersionUpdateEnd == live.mVersionUpdateEnd
    assert data.mScoringInfo.mCurrentET == live.mScoringInfo.mCurrentET
    assert update() is False


def test_rf2_copy_access_checks_copy_before_keeping_it(monkeypatch):
    """Created copy access: torn copy (plugin still writing after copied twice) never replaces data copy"""
    from pyRfactor2SharedMemory import rF2data, rF2MMap

    shared = bytearray(ctypes.sizeof(rF2data.rF2Scoring))
    live = rF2data.rF2Scoring.from_buffer(shared)
    monkeypatch.setattr(rF2MMap, "platform_mmap", lambda name, size, pid="": shared)
    control = rF2MMap.MMapControl("test", rF2data.rF2Scoring)
    control.create(0)
    assert len(control._scratch) == len(shared)
    live.mVersionUpdateBegin = live.mVersionUpdateEnd = 1
    live.mScoringInfo.mCurrentET = 1.0
    assert control.update() is True and control.data.mScoringInfo.mCurrentET == 1.0
    scratch = WriteWhileCopying(len(shared), live)
    control.set_scratch(scratch)
    scratch.writes = ["full", "start"]  # second copy overlaps a write still running
    live.mVersionUpdateBegin = live.mVersionUpdateEnd = 2
    assert control.update() is False
    assert control.data.mScoringInfo.mCurrentET == 1.0 and control.data.mVersionUpdateEnd == 1  # kept as before
    live.mVersionUpdateEnd = live.mVersionUpdateBegin  # write finished
    assert control.update() is True and control.data.mScoringInfo.mCurrentET == live.mScoringInfo.mCurrentET


# --- Connector update loop: index maps & sync only on new data, modules notified on change
class ScriptedZone:
    """LMU data zone with scripted copy results"""

    def __init__(self, data):
        self.data = data
        self.results = []

    def update(self):
        return self.results.pop(0) if self.results else False


class ScriptedStop:
    """Stop event of update loop, runs one step before each tick"""

    def __init__(self, steps):
        self.steps = list(steps)

    def wait(self, timeout=None):
        if not self.steps:
            return True
        self.steps.pop(0)()
        return False


def lmu_sync():
    from pyLMUSharedMemory import lmu_data

    sync = lmu_connector.SyncData()
    data = lmu_data.LMUObjectOut()
    zone = ScriptedZone(data)
    sync.dataset.shmm = zone  # type: ignore[assignment]
    data.scoring.scoringInfo.mNumVehicles = data.telemetry.activeVehicles = 2
    for index, slot_id in enumerate((3, 5)):
        data.scoring.vehScoringInfo[index].mID = slot_id
        data.telemetry.telemInfo[index].mID = slot_id
    data.scoring.vehScoringInfo[0].mIsPlayer = True
    sync.player_scor = data.scoring.vehScoringInfo[0]
    sync.player_tele = lmu_connector.EMPTY_TELE
    return sync, zone, data


def test_lmu_loop_rebuilds_maps_and_notifies_only_on_new_data(notifier, monkeypatch):
    sync, zone, data = lmu_sync()
    maps = []
    syncs = []
    original_map = lmu_connector.SyncData._SyncData__update_tele_map
    original_sync = lmu_connector.SyncData._SyncData__sync_player_data

    def counting_map(self):
        maps.append(1)
        original_map(self)

    def counting_sync(self):
        syncs.append(1)
        return original_sync(self)

    monkeypatch.setattr(lmu_connector.SyncData, "_SyncData__update_tele_map", counting_map)
    monkeypatch.setattr(lmu_connector.SyncData, "_SyncData__sync_player_data", counting_sync)
    woken = threading.Event()
    notifier.subscribe(woken)
    notified = []

    def tick(copied=False, change=None):
        def step():
            notified.append(woken.is_set())
            woken.clear()
            if change:
                change()
            zone.results.append(copied)
        return step

    def new_sample():
        data.scoring.scoringInfo.mCurrentET += 0.2
        data.telemetry.telemInfo[0].mElapsedTime += 0.2

    def spectate():
        sync.override_player_index = True
        sync.player_slot_id = 5

    data.scoring.scoringInfo.mCurrentET = 1.0
    stop = ScriptedStop((
        tick(True),  # 1 new data: resumed
        tick(),  # 2 player synced (resume), synced state notified
        tick(),  # 3 nothing new
        tick(True, new_sample),  # 4 new sample
        tick(),  # 5 nothing new
        tick(False, spectate),  # 6 player index override: synced again without new data
        tick(),  # 7
    ))
    sync._SyncData__update_loop(stop)
    notified.append(woken.is_set())
    assert notified[1:] == [True, True, False, True, False, True, False]  # notified by previous tick
    assert len(maps) == 2  # ticks with new data only
    assert len(syncs) == 3  # resume, new sample, override change
    assert sync.player_scor_index == 1 and sync.synced
    assert sync.tele_map[1] == (0, 1)


def test_lmu_loop_unknown_copy_state_rebuilds_every_tick(notifier, monkeypatch):
    """Direct access & replay (copy state unknown): same as before, maps rebuilt every tick"""
    sync, zone, data = lmu_sync()
    maps = []
    original_map = lmu_connector.SyncData._SyncData__update_tele_map
    monkeypatch.setattr(
        lmu_connector.SyncData, "_SyncData__update_tele_map", lambda self: (maps.append(1), original_map(self)))
    data.scoring.scoringInfo.mCurrentET = 1.0
    stop = ScriptedStop([lambda: zone.results.append(None)] * 4)
    sync._SyncData__update_loop(stop)
    assert len(maps) == 4


def test_lmu_player_lost_paused_after_5_ticks_without_new_data(notifier):
    """Player sync result kept while data unchanged: player paused after same number of ticks as before"""
    sync, zone, data = lmu_sync()
    data.scoring.scoringInfo.mCurrentET = 1.0
    steps = [lambda: zone.results.append(True), lambda: None]

    def player_left():
        data.scoring.vehScoringInfo[0].mIsPlayer = False
        data.scoring.scoringInfo.mCurrentET = 1.2
        zone.results.append(True)

    steps.append(player_left)
    states = []
    steps += [lambda: states.append(sync.synced)] * 6
    sync._SyncData__update_loop(ScriptedStop(steps))
    assert states == [True, True, True, True, False, False]  # 5th failed sync pauses player data
    assert sync.player_scor_index == lmu_connector.INVALID_INDEX


def test_lmu_update_thread_attached_while_running(notifier, monkeypatch):
    sync, _, _ = lmu_sync()
    seen = []
    monkeypatch.setattr(
        lmu_connector.SyncData, "_SyncData__update_loop", lambda self, event: seen.append(notifier.available))
    sync._SyncData__update(threading.Event())
    assert seen == [True] and not notifier.available


def test_rf2_loop_skips_maps_without_new_data(notifier, monkeypatch):
    from tests.test_rf2_connector import MemoryDataSet

    sync = rf2_connector.SyncData()
    dataset = MemoryDataSet()
    sync.dataset = dataset
    results = []
    dataset.scor.update = lambda: results.pop(0) if results else False
    dataset.tele.update = lambda: False
    scor = dataset.scor.data
    scor.mScoringInfo.mNumVehicles = dataset.tele.data.mNumVehicles = 1
    scor.mVehicles[0].mIsPlayer = True
    scor.mScoringInfo.mCurrentET = 1.0
    sync.player_scor = scor.mVehicles[0]
    sync.player_tele = rf2_connector.EMPTY_TELE
    maps = []
    original_map = rf2_connector.SyncData._SyncData__update_tele_map
    monkeypatch.setattr(
        rf2_connector.SyncData, "_SyncData__update_tele_map", lambda self: (maps.append(1), original_map(self)))
    woken = threading.Event()
    notifier.subscribe(woken)
    sync._SyncData__update_loop(ScriptedStop([lambda: results.append(True)] + [lambda: None] * 3))
    assert len(maps) == 1 and sync.synced and woken.is_set()
    assert rf2_connector.MMapDataSet.update_mmap(SimpleNamespace(
        scor=SimpleNamespace(update=lambda: False), tele=SimpleNamespace(update=lambda: None), replaying=False,
    )) is None  # unknown copy state of a zone: treated as new data


# --- Lap file written by chunk
def previous_lap_text(rows, info=None) -> str:
    """Lap file content before chunked writing"""
    buffer = io.StringIO()
    if info:
        buffer.write(module_recorder.INFO_PREFIX + json.dumps(info) + "\n")
    writer = csv.writer(buffer)
    writer.writerow(module_recorder.CSV_HEADER)
    writer.writerows(rows)
    return buffer.getvalue()


def synthetic_samples(count: int) -> "module_recorder.LapSamples":
    rng = random.Random(count)
    samples = module_recorder.LapSamples()
    for index in range(count):
        row = [round(rng.uniform(-500, 9000), 3) for _ in range(len(module_recorder.CSV_HEADER))]
        row[8] = rng.randint(-1, 7)  # gear
        row[9] = 0 if index % 97 == 0 else row[9]  # int in float column: plain list column
        row[20] = "text,with \"quote\"" if index % 50 == 0 else row[20]
        samples.append(row)
    return samples


@pytest.mark.parametrize("count", [0, 1, 249, 250, 251, 500, 5003])
def test_lap_text_same_output_as_single_write(count):
    samples = synthetic_samples(count)
    info = {"kind": "lap", "track": "Le Mans"}
    expected = previous_lap_text(samples, info)
    assert module_recorder.lap_text(samples, info) == expected
    assert module_recorder.lap_text(samples, info, chunk_rows=7) == expected
    assert module_recorder.lap_text(list(samples), None, chunk_rows=0) == previous_lap_text(samples)


def test_lap_text_releases_gil_between_chunks(monkeypatch):
    sleeps: list = []
    monkeypatch.setattr(module_recorder, "time", SimpleNamespace(sleep=sleeps.append))
    module_recorder.lap_text(synthetic_samples(1000), chunk_rows=250)
    assert len(sleeps) == 4 and set(sleeps) == {0}


def test_delta_position_update_wakes_derived_modules(ui_env, notifier, monkeypatch):
    """Fuel & notes stamps include delta module position: woken when it changes, not on same position"""
    from tinypedal import realtime_state
    from tinypedal.module_info import minfo
    from tinypedal.setting import cfg

    positions = iter((10.0, 10.0, 12.5))

    def distance(output):
        def send(_reset):
            output.lapDistance = next(positions)
        return SimpleNamespace(send=send)

    stamps = iter(range(100))
    monkeypatch.setattr(module_delta, "calc_delta_distance", distance)
    monkeypatch.setattr(module_delta, "calc_delta_time", lambda **kwargs: SimpleNamespace(send=lambda _: False))
    monkeypatch.setattr(module_delta, "data_stamp", lambda: next(stamps))
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(minfo.delta, "lapDistance", 0.0)
    derived, plain = threading.Event(), threading.Event()
    notifier.subscribe(derived, derived=True)
    notifier.subscribe(plain)
    woken = []

    def wait(interval):
        woken.append(derived.is_set())
        derived.clear()
        return len(woken) > 3

    module = module_delta.Realtime(cfg, "module_delta")
    monkeypatch.setattr(module_delta.Realtime, "wait_update", lambda self, interval: wait(interval))
    module.update_data()
    assert woken == [False, True, False, True]  # position 10.0, same 10.0, then 12.5
    assert not plain.is_set()
