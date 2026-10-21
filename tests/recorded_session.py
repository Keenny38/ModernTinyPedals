"""Recorded game sessions played frame by frame through the real API reader, data modules and overlays

A recorded session (tests/fixtures/sessions/*.tpreplay, made with tools/make_replay_fixture.py) is read
with the Le Mans Ultimate connector and reader the app uses, without its update thread: each step loads
the next recorded frame and syncs player data like the shared memory thread does (see adapter._sync).

Data modules run in their own threads as in the app, in lock step with the frames: their wait for new
game data returns once per frame, and the next frame is only loaded once every module waits again, so
each module computes every frame exactly once, whatever the speed of the computer.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from time import monotonic

from neopedal import realtime_state
from neopedal.adapter._sync import default_tele_indexes
from neopedal.api_connector import SimLMU
from neopedal.module._base import DataModule
from neopedal.replay import ReplayFile, ReplayPlayer

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sessions")
STEP_TIMEOUT = 30.0  # seconds a module may take on one frame before the test fails


def recorded_sessions() -> list[str]:
    """Names of recorded sessions with their expected values (name.tpreplay & name.json)"""
    if not os.path.isdir(FIXTURES):
        return []
    return sorted(
        name[:-9] for name in os.listdir(FIXTURES)
        if name.endswith(".tpreplay") and os.path.exists(os.path.join(FIXTURES, f"{name[:-9]}.json")))


def expected_values(name: str) -> dict:
    """Expected values of recorded session (game values read from the recording, see fixture json)"""
    with open(os.path.join(FIXTURES, f"{name}.json"), encoding="utf-8") as file:
        return json.load(file)


class Clock:
    """Replay time set by test"""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class RecordedSession:
    """Recorded session read through Le Mans Ultimate connector, one frame per step"""

    def __init__(self, name: str, api_setting: dict):
        self.replay = ReplayFile(os.path.join(FIXTURES, f"{name}.tpreplay"))
        self.clock = Clock()
        self.player = ReplayPlayer(self.replay, clock=self.clock)
        self.player.loop = False
        self.connector = SimLMU()
        self.connector.setup(api_setting)
        info = self.connector._shmmapi
        info.setReplay(self.player, self.connector._restapi_dataset)
        self.sync = info._sync
        self.sync.dataset.shmm.create()
        self.reader = self.connector.reader()
        self.index = -1
        self._last_timestamp = 0.0
        self._last_garage = False
        self._last_slot_id = -1
        self.sync._tele_indexes = default_tele_indexes()

    def __len__(self) -> int:
        return len(self.replay)

    @property
    def time(self) -> float:
        """Replay time of current frame"""
        return self.replay.times[self.index] if self.index >= 0 else 0.0

    def load(self, index: int) -> None:
        """Load frame, sync player data & realtime state (as connector update thread & overlay control)"""
        self.index = index
        self.clock.now = self.replay.times[index]
        sync = self.sync
        sync.dataset.update_mmap()
        sync._update_indexes()
        sync.paused = False
        sync.synced = sync._SyncData__sync_player_data()  # name mangled private method of _sync.SyncData
        scor_info = sync.dataset.shmm.data.scoring.scoringInfo
        timestamp = scor_info.mCurrentET
        results = sync.results
        if results.timestamp != timestamp:
            if results.timestamp > timestamp:
                results.clear()
            results.timestamp = timestamp
            results.update(sync._results_stream())
        if timestamp != self._last_timestamp:
            player = sync.player_scor
            if (
                self._last_timestamp > timestamp
                or self._last_garage < player.mInGarageStall
                or self._last_slot_id != player.mID
            ):
                sync.resets += 1
            sync.last_update = monotonic()
            self._last_timestamp = timestamp
            self._last_garage = player.mInGarageStall
            self._last_slot_id = player.mID
        state = self.reader.state
        realtime_state.active = state.active()
        realtime_state.paused = state.paused()
        realtime_state.resets = state.resets()
        realtime_state.shown = realtime_state.active
        if realtime_state.active:
            realtime_state.session_type = self.reader.session.session_type()
            realtime_state.in_pits = self.reader.vehicle.in_pits() or self.reader.vehicle.in_garage()

    def frames(self, step: int = 1) -> Iterator[int]:
        """Load every step-th frame, yield its index"""
        for index in range(0, len(self.replay), step):
            self.load(index)
            yield index

    def close(self) -> None:
        self.sync.dataset.shmm.close()
        self.replay.close()


class Lockstep:
    """Data module waits for game data replaced by frame steps (patched DataModule wait methods)

    Every module computes each frame once, one module at a time in list order (delta module first: modules
    following its position, WAKE_ON_DERIVED, compute after it as in the app), so a replay always gives the
    same values.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._arrived: dict[int, int] = {}  # id of module: number of waits
        self._released: dict[int, int] = {}  # id of module: number of frames released
        self.modules: list[DataModule] = []

    def wait(self, module: DataModule, _interval: float) -> bool:
        """Module wait: returns once module released for next frame, True once module stopping"""
        key = id(module)
        stop = module._event
        with self._cond:
            arrived = self._arrived[key] = self._arrived.get(key, 0) + 1
            self._cond.notify_all()
            self._cond.wait_for(lambda: self._released.get(key, 0) >= arrived or stop.is_set())
        return stop.is_set()

    def _waiting(self, module: DataModule) -> bool:
        key = id(module)
        return module.closed or self._arrived.get(key, 0) == self._released.get(key, 0) + 1

    def _wait_module(self, module: DataModule) -> None:
        if not self._cond.wait_for(lambda: self._waiting(module), STEP_TIMEOUT):
            raise TimeoutError(f"{module.module_name} still computing frame after {STEP_TIMEOUT} s")

    def step(self, load: Callable[[], None]) -> None:
        """Load next frame (every module waiting), then let each module compute it in turn"""
        with self._cond:
            for module in self.modules:
                self._wait_module(module)
            load()
            for module in self.modules:
                key = id(module)
                self._released[key] = self._released.get(key, 0) + 1
                self._cond.notify_all()
                self._wait_module(module)

    def finish(self) -> None:
        """Wait until every module computed last frame"""
        with self._cond:
            for module in self.modules:
                self._wait_module(module)

    def stop(self) -> None:
        """Stop modules (data saved), wait until their threads ended"""
        for module in self.modules:
            module.stop()
        with self._cond:
            self._cond.notify_all()
        for module in self.modules:
            assert module.wait_closed(STEP_TIMEOUT), f"{module.module_name} did not stop"


@contextmanager
def lockstep_modules(monkeypatch, names: Iterable[str], config) -> Iterator[Lockstep]:
    """Start data modules (by file name, such as "module_delta") in lock step with frames, delta module first"""
    from importlib import import_module

    names = sorted(names, key=lambda name: name != "module_delta")
    lockstep = Lockstep()
    def wait(module: DataModule, interval: float) -> bool:  # function: bound to each module instance
        return lockstep.wait(module, interval)

    monkeypatch.setattr(DataModule, "wait_update", wait)
    monkeypatch.setattr(DataModule, "wait_fixed", wait)
    for name in names:
        module = import_module(f"neopedal.module.{name}").Realtime(config, name)
        lockstep.modules.append(module)
    for module in lockstep.modules:
        module.start()
    try:
        yield lockstep
    finally:
        lockstep.stop()


class ErrorLog(logging.Handler):
    """Errors logged by app code (module or overlay exceptions caught and logged by supervisors)"""

    def __init__(self):
        super().__init__(logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [f"{record.name}: {self.format(record)}" for record in self.records]


@contextmanager
def logged_errors() -> Iterator[ErrorLog]:
    """Errors logged by neopedal while block runs"""
    handler = ErrorLog()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("neopedal")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
