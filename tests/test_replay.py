"""Shared memory replay: file format, seeking, playback and LMU integration"""

import ctypes
import io

import pytest

from pyLMUSharedMemory import lmu_data
from tinypedal.adapter import lmu_connector
from tinypedal.replay import (
    KEYFRAME_INTERVAL,
    ReplayControl,
    ReplayFile,
    ReplayMMap,
    ReplayPlayer,
    ReplayWriter,
)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_frames(count: int, size: int = 64) -> list[bytes]:
    return [bytes((index + offset) % 256 for offset in range(size)) for index in range(count)]


def write_replay(path, frames: list[bytes], step: float = 0.1) -> str:
    filename = str(path / "test.tpreplay")
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, len(frames[0]), rate=10)
        for index, frame in enumerate(frames):
            writer.write(index * step, frame)
    return filename


def test_roundtrip_sequential_and_seek(tmp_path):
    frames = make_frames(KEYFRAME_INTERVAL * 2 + 7)
    replay = ReplayFile(write_replay(tmp_path, frames))
    assert len(replay) == len(frames)
    assert [replay.frame(index) for index in range(len(frames))] == frames
    for index in (5, KEYFRAME_INTERVAL + 3, 0, len(frames) - 1, 150, 10):  # random seeking
        assert replay.frame(index) == frames[index]


def test_index_at(tmp_path):
    replay = ReplayFile(write_replay(tmp_path, make_frames(10)))
    assert replay.duration == pytest.approx(0.9)
    assert replay.index_at(0) == 0
    assert replay.index_at(0.35) == 3
    assert replay.index_at(100) == 9


def test_truncated_file_keeps_complete_frames(tmp_path):
    filename = write_replay(tmp_path, make_frames(5))
    with open(filename, "rb+") as file:
        file.truncate(file.seek(0, io.SEEK_END) - 3)
    assert len(ReplayFile(filename)) == 4


@pytest.mark.parametrize("content", [b"", b"not a replay\n", b'TPREPLAY1 {"frame_size": 4}\n'])
def test_invalid_file(tmp_path, content):
    filename = tmp_path / "bad.tpreplay"
    filename.write_bytes(content)
    with pytest.raises(ValueError):
        ReplayFile(str(filename))


def test_writer_rejects_wrong_frame_size():
    writer = ReplayWriter(io.BytesIO(), 4, rate=10)
    with pytest.raises(ValueError):
        writer.write(0, b"abc")


def test_player_speed_pause_seek_loop(tmp_path):
    frames = make_frames(11)  # 0.0 .. 1.0 seconds
    clock = Clock()
    player = ReplayPlayer(ReplayFile(write_replay(tmp_path, frames)), clock=clock)
    clock.now = 0.5
    assert player.current_frame() == frames[5]
    player.set_speed(2.0)
    clock.now = 0.7
    assert player.position == pytest.approx(0.9)
    player.set_paused(True)
    clock.now = 5.0
    assert player.position == pytest.approx(0.9)
    player.set_paused(False)
    player.set_speed(1.0)
    clock.now = 5.3  # 1.2 > duration, loops back
    assert player.position == pytest.approx(0.2)
    player.loop = False
    clock.now = 9.0
    assert player.position == pytest.approx(1.0)
    player.seek(0.35)
    assert player.current_frame() == frames[3]


def test_replay_mmap_feeds_structure(tmp_path):
    class Data(ctypes.Structure):
        _fields_ = [("value", ctypes.c_int32)]

    frames = [ctypes.c_int32(value).value.to_bytes(4, "little") for value in (1, 2, 3)]
    clock = Clock()
    player = ReplayPlayer(ReplayFile(write_replay(tmp_path, frames)), clock=clock)
    shmm = ReplayMMap(Data, player)
    shmm.create()
    assert shmm.data.value == 1
    clock.now = 0.2
    shmm.update()
    assert shmm.data.value == 3
    shmm.close()
    shmm.update()  # no-op after close, keeps last frame
    assert shmm.data.value == 3


def test_record_from_source(tmp_path):
    control = ReplayControl()
    source = ctypes.create_string_buffer(b"abcd", 4)
    filename = str(tmp_path / "rec.tpreplay")
    control.start_recording(filename, lambda: source, rate=200)
    while control.recorded_frames < 3:
        pass
    control.stop_recording()
    assert not control.recording
    replay = ReplayFile(filename)
    assert replay.frame(0) == b"abcd"


def test_lmu_info_switches_between_replay_and_live(tmp_path):
    size = ctypes.sizeof(lmu_data.LMUObjectOut)
    frame = bytearray(size)
    data = lmu_data.LMUObjectOut.from_buffer(frame)
    data.scoring.scoringInfo.mCurrentET = 42.5
    player = ReplayPlayer(ReplayFile(write_replay(tmp_path, [bytes(frame)])))
    info = lmu_connector.LMUInfo()
    live = info.rawData
    info.setReplay(player)
    assert info.lmuScorInfo.mCurrentET == 42.5
    info.setReplay(None)
    assert info.rawData is live


def test_replay_view_loads_and_leaves_replay(ui_env, tmp_path, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.replay import replay
    from tinypedal.ui import replay_view

    frame = bytes(ctypes.sizeof(lmu_data.LMUObjectOut))
    filename = write_replay(tmp_path, [frame, frame])
    restarts = []
    monkeypatch.setattr(replay_view, "restart_api", lambda: restarts.append(replay.active))
    monkeypatch.setattr(type(api), "name", property(lambda self: replay_view.API_LMU_NAME))
    monkeypatch.setattr(replay_view.QFileDialog, "getOpenFileName", lambda *args: (filename, ""))
    dialog = replay_view.ReplayView(None)
    try:
        assert not dialog.button_play.isEnabled()
        dialog.open_replay()
        assert replay.active and restarts == [True]
        assert dialog.button_play.isEnabled()
        dialog.toggle_pause()
        assert replay.player is not None and replay.player.paused
        dialog.stop_replay()
        assert not replay.active and restarts == [True, False]
    finally:
        replay.unload()
        dialog.close()


def test_rf2_replay_reads_every_zone(tmp_path):
    from pyRfactor2SharedMemory import rF2data

    from tinypedal.adapter import rf2_connector, rf2_restapi

    info = rf2_connector.RF2Info()
    zones = []
    for name, data_struct in rf2_connector.REPLAY_ZONES:
        zone = data_struct()
        if name == "scor":
            zone.mScoringInfo.mCurrentET = 12.5
        elif name == "rule":
            zone.mTrackRules.mStage = 3
        zones.append(bytes(zone))
    frame = b"".join(zones)
    filename = str(tmp_path / "rf2.tpreplay")
    rest = rf2_restapi.RestAPIData()
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, len(frame), 10, {"source": "rFactor 2", "layout": rf2_connector.replay_layout()})
        writer.write(0.0, frame)
        writer.write_rest(0.0, {"timeScale": 4, "forecastRace": [[0.0, 2, 21.5, 0.3]]})
        writer.write(0.1, frame)
    replay = ReplayFile(filename)
    assert replay.source == "rFactor 2" and len(replay) == 2 and len(replay.rest_data) == 1
    player = ReplayPlayer(replay)
    info.setReplay(player, rest)
    for zone in info._sync.dataset.zones():
        zone.create()
    info._sync.dataset.update_mmap()
    assert info.rf2ScorInfo.mCurrentET == 12.5
    assert info.rf2Rule.mTrackRules.mStage == 3
    assert rest.timeScale == 4 and rest.forecastRace[0].temperature == 21.5  # Rest API snapshot applied
    assert len(info.rawData) == len(frame)
    info.setReplay(None)
    assert not info._sync.dataset.replaying
    assert isinstance(info._sync.dataset.scor.data, rF2data.rF2Scoring) or info._sync.dataset.scor.data is None


def test_replay_compatibility():
    from tinypedal.replay import replay_compatible

    assert replay_compatible("Le Mans Ultimate", "Le Mans Ultimate")
    assert replay_compatible("rFactor 2", "Le Mans Ultimate (legacy)")
    assert not replay_compatible("Le Mans Ultimate", "rFactor 2")


def test_old_replay_file_is_lmu(tmp_path):
    replay = ReplayFile(write_replay(tmp_path, make_frames(3)))
    assert replay.source == "Le Mans Ultimate" and replay.zone_offset("shmm") == 0
