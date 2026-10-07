"""Audit fixes: replay Rest API snapshots decoded on demand & written as changes, recording kept
while loading replay, recording error reported & retried, recorder lap number read after validation"""

import ctypes
import io
import json
import time
import zlib
from types import SimpleNamespace

import pytest

from tests.telemetry_sim import LapSim, fake_reader
from tests.test_replay_load import replay_view, wait_loaded, write_long_replay  # noqa: F401
from tinypedal import realtime_state
from tinypedal import replay as replay_module
from tinypedal.api_control import api
from tinypedal.replay import (
    FRAME_HEADER,
    REST_DELTA,
    REST_FRAME,
    REST_KEY_INTERVAL,
    ReplayControl,
    ReplayFile,
    ReplayMMap,
    ReplayPlayer,
    ReplayWriter,
)


# --- Rest API snapshots: changed fields only, decoded on demand
def rest_states(count: int) -> list[dict]:
    """Snapshots: large field never changing, one changing every snapshot, one growing now & then"""
    setup = [f"SETTING_{index}=//{index}" for index in range(100)]
    return [
        {"setup": setup, "wear": [1.0 - index * 0.01] * 4, "contacts": [[i, "x"] for i in range(index // 7)]}
        for index in range(count)
    ]


def write_rest_replay(filename: str, states: list[dict]) -> None:
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, 4, 10, {"source": "Le Mans Ultimate"})
        for index, state in enumerate(states):
            writer.write(float(index), b"abcd")
            writer.write_rest(float(index), state)
        writer.finish()


def rest_payloads(filename: str) -> list[dict]:
    """Decoded Rest API frames as written in file"""
    payloads = []
    with open(filename, "rb") as file:
        file.readline()
        while True:
            head = file.read(FRAME_HEADER.size)
            if len(head) < FRAME_HEADER.size:
                return payloads
            _, frame_type, size, _ = FRAME_HEADER.unpack(head)
            payload = file.read(size)
            if frame_type == REST_FRAME:
                payloads.append(json.loads(zlib.decompress(payload)))


def test_rest_written_as_changes_with_full_snapshots(tmp_path):
    filename = str(tmp_path / "rest.tpreplay")
    states = rest_states(REST_KEY_INTERVAL * 2 + 5)
    write_rest_replay(filename, states)
    payloads = rest_payloads(filename)
    assert len(payloads) == len(states)
    full = [index for index, data in enumerate(payloads) if REST_DELTA not in data]
    assert full == [0, REST_KEY_INTERVAL, REST_KEY_INTERVAL * 2]
    assert payloads[1] == {REST_DELTA: 1, "wear": states[1]["wear"]}  # unchanged setup & contacts left out
    assert payloads[0] == states[0]


def test_rest_field_gone_writes_full_snapshot():
    file = io.BytesIO()
    writer = ReplayWriter(file, 4, 10)
    assert writer.write_rest(0.0, {"a": 1, "b": 2})
    assert writer.write_rest(1.0, {"a": 1})
    assert not writer.write_rest(2.0, {"a": 1})


def test_rest_decoded_on_demand(tmp_path, monkeypatch):
    filename = str(tmp_path / "rest.tpreplay")
    states = rest_states(REST_KEY_INTERVAL * 2 + 5)
    write_rest_replay(filename, states)
    decoded = []
    loads = json.loads
    monkeypatch.setattr(replay_module.json, "loads", lambda data: decoded.append(1) or loads(data))
    replay = ReplayFile(filename)
    assert not hasattr(replay, "rest_data") and len(replay.rest_times) == len(states)
    assert len(decoded) <= 2  # header & summary only: snapshots not decoded at load
    order = [5, 6, 7, REST_KEY_INTERVAL + 3, 2, len(states) - 1, 0, REST_KEY_INTERVAL - 1, REST_KEY_INTERVAL]
    for index in order:
        assert replay.rest(index) == states[index]
    replay.rest(REST_KEY_INTERVAL + 1)
    decoded.clear()
    replay.rest(REST_KEY_INTERVAL + 2)
    assert len(decoded) == 1  # cached snapshot: next one decodes one frame
    assert replay.rest(-1) is None and replay.rest(len(states)) is None
    replay.close()


def test_old_full_snapshot_files_still_read(tmp_path):
    """Files of earlier versions: every Rest API frame a full snapshot"""
    filename = str(tmp_path / "old.tpreplay")
    states = rest_states(5)
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, 4, 10, {"source": "Le Mans Ultimate"})
        for index, state in enumerate(states):
            writer.write(float(index), b"abcd")
            writer._write(float(index), REST_FRAME, zlib.compress(json.dumps(state).encode("utf-8"), 1))
        writer._write(4.5, REST_FRAME, b"damaged")
        writer.finish()
    replay = ReplayFile(filename)
    assert [replay.rest(index) for index in (4, 1, 3, 0, 2)] == [states[index] for index in (4, 1, 3, 0, 2)]
    assert replay.rest(5) == states[4]  # damaged frame: last good snapshot kept
    replay.close()


def test_rest_applied_by_replay_zone_after_seek(tmp_path):
    filename = str(tmp_path / "rest.tpreplay")
    states = [{"wear": index, "setup": "x"} for index in range(REST_KEY_INTERVAL + 10)]
    write_rest_replay(filename, states)
    class Target:  # Rest API data set: apply_rest_snapshot sets fields listed in slots
        __slots__ = ("wear", "setup")

        def __init__(self):
            self.wear, self.setup = -1, ""

    target = Target()
    player = ReplayPlayer(ReplayFile(filename), clock=lambda: 0.0)
    player.paused = True
    zone = ReplayMMap(ctypes.c_char * 4, player, rest_target=target)
    zone.create()
    for position in (REST_KEY_INTERVAL + 5, 3, REST_KEY_INTERVAL - 2):
        player.seek(position)
        zone.update()
        assert (target.wear, target.setup) == (position, "x")


def test_export_rebuilds_rest_snapshots(tmp_path):
    filename = str(tmp_path / "full.tpreplay")
    states = rest_states(REST_KEY_INTERVAL + 20)
    write_rest_replay(filename, states)
    replay = ReplayFile(filename)
    section = str(tmp_path / "section.tpreplay")
    replay.export(section, REST_KEY_INTERVAL - 3, REST_KEY_INTERVAL + 10)
    part = ReplayFile(section)
    assert part.rest(0) == states[REST_KEY_INTERVAL - 3]  # full snapshot in effect at section start
    assert REST_DELTA not in rest_payloads(section)[0]
    assert [part.rest(index) for index in range(len(part.rest_times))] == states[REST_KEY_INTERVAL - 3:
                                                                                 REST_KEY_INTERVAL + 11]
    part.close()
    replay.close()


# --- Replay window: recording kept while replay file loads
def test_open_file_keeps_recording_until_loaded(replay_view, tmp_path, monkeypatch):  # noqa: F811
    from tinypedal.replay import replay
    from tinypedal.ui import replay_view as module

    state = {"recording": True}
    stopped = []
    monkeypatch.setattr(type(replay), "recording", property(lambda self: state["recording"]))
    monkeypatch.setattr(replay, "stop_recording", lambda: stopped.append(replay.active))
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: None)
    bad = tmp_path / "bad.tpreplay"
    bad.write_bytes(b"not a replay")
    replay_view.open_file(str(bad))
    assert stopped == []  # not stopped before loading
    wait_loaded(replay_view)
    assert stopped == [] and not replay.active  # load failed: recording goes on
    replay_view.open_file(write_long_replay(tmp_path, 5))
    assert stopped == []
    wait_loaded(replay_view)
    assert stopped == [False] and replay.active  # stopped once loaded, before replay played


# --- Recording error: reported, state cleared, automatic recording retried
def test_recording_error_reported(tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(replay_module, "app_signal", SimpleNamespace(error=SimpleNamespace(emit=errors.append)))
    control = ReplayControl()
    count = [0]

    def frame():
        count[0] += 1
        if count[0] > 3:
            raise OSError(28, "No space left on device")
        return b"abcd"

    filename = str(tmp_path / "full-disk.tpreplay")
    control.start_recording(filename, frame, rate=100)
    end = time.monotonic() + 5
    while control.recording and time.monotonic() < end:
        time.sleep(0.01)
    assert not control.recording
    assert "No space left on device" in control.recording_error
    assert errors == [f"Replay recording stopped: {control.recording_error}"]
    assert control.recording_file == ""
    assert control.start_recording(str(tmp_path / "next.tpreplay"), lambda: None, rate=100)
    assert control.recording_error == ""  # cleared by next recording
    control.stop_recording()
    assert control.recording_error == "" and not errors[1:]  # stopped on request: no error


def test_auto_replay_retries_after_recording_error(monkeypatch):
    from tinypedal import replay_session
    from tinypedal.replay import replay

    calls = []
    state = {"recording": False}
    monkeypatch.setattr(replay_session, "api_supported", lambda: True)
    monkeypatch.setattr(type(replay), "recording", property(lambda self: state["recording"]))
    monkeypatch.setattr(type(replay), "active", property(lambda self: False))
    monkeypatch.setattr(replay, "recording_error", "")

    def start(auto=False):
        calls.append("start")
        state["recording"] = True
        replay.recording_error = ""
        return "replay-auto-x.tpreplay"

    monkeypatch.setattr(replay_session, "start_api_recording", start)
    auto = replay_session.AutoReplay(keep=2, retry_delay=30.0)
    auto.update(True, 0.0)
    assert calls == ["start"]
    state["recording"] = False  # disk full
    replay.recording_error = "No space left on device"
    auto.update(True, 1.0)
    auto.update(True, 30.0)
    assert calls == ["start"] and not auto.user_stopped  # waits retry delay
    auto.update(True, 31.0)
    assert calls == ["start", "start"]  # retried while driving
    state["recording"] = False  # stopped from replay window
    auto.update(True, 32.0)
    auto.update(True, 100.0)
    assert calls == ["start", "start"] and auto.user_stopped


# --- Recorder: lap number of file name read once lap confirmed by scoring
@pytest.fixture
def lagging_scoring(monkeypatch):
    """Completed laps (scoring) updated 0.5s after line crossing"""
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    sim = LapSim([95.0, 90.0, 92.0])
    reader = fake_reader(sim)
    reader.lap.completed_laps = lambda index=None: (
        sim.lap_index if sim.elapsed - sim.lap_start >= 0.5 else max(sim.lap_index - 1, 0))
    monkeypatch.setattr(api, "read", reader)
    return sim


def test_recorder_lap_number_read_after_validation(lagging_scoring):
    from tinypedal.module import module_recorder

    sim = lagging_scoring
    saved = []
    gen = module_recorder.record_telemetry(
        filepath="", min_lap_fraction=0.9, max_saved_laps=10,
        saver=lambda pending, options, valid: saved.append((pending.lap_number, valid)))
    while not sim.finished or sim.elapsed < sim.lap_start + 2:
        gen.send(0)
        sim.tick()
    assert saved == [(2, True), (3, True)]  # same numbers as live completed laps, no duplicate


def test_recorder_invalid_lap_keeps_crossing_number(lagging_scoring, monkeypatch):
    from tinypedal.module import module_recorder

    saved = []
    pending = module_recorder.PendingLap("T - C", 4, 90.0, 0.0, [], {}, 0.0)
    monkeypatch.setattr(module_recorder, "official_sectors", lambda lap_time: None)
    lagging_scoring.lap_index, lagging_scoring.elapsed = 5, 10.0
    module_recorder.save_pending(pending, None, lambda lap, options, valid: saved.append(lap.lap_number), False)
    module_recorder.save_pending(pending, None, lambda lap, options, valid: saved.append(lap.lap_number), True)
    lagging_scoring.lap_index = 0  # session changed meanwhile: crossing value kept
    module_recorder.save_pending(pending, None, lambda lap, options, valid: saved.append(lap.lap_number), True)
    assert saved == [4, 5, 4]
