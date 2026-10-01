"""Shared memory replay: file format, seeking, playback and LMU integration"""

import ctypes
import io

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

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
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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


def test_rest_snapshot_lookup(tmp_path):
    filename = str(tmp_path / "rest.tpreplay")
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, 4, 10)
        for index in range(5):
            writer.write(index * 1.0, b"abcd")
            writer.write_rest(index * 1.0, {"timeScale": index})
    replay = ReplayFile(filename)
    assert replay.rest_at(-1) == -1 and replay.rest_at(0) == 0 and replay.rest_at(2.5) == 2 and replay.rest_at(99) == 4


def test_secondary_zone_reads_same_frame(tmp_path):
    clock = Clock()
    player = ReplayPlayer(ReplayFile(write_replay(tmp_path, make_frames(20, 8))), clock=clock)
    primary = ReplayMMap(ctypes.c_char * 4, player, 0)
    secondary = ReplayMMap(ctypes.c_char * 4, player, 4, primary=False)
    primary.create()
    secondary.create()
    primary.update()
    clock.now = 1.0  # time moves between zone updates
    secondary.update()
    assert bytes(primary.data) + bytes(secondary.data) == player.replay.frame(0)


def test_markers_summary_and_quick_info(tmp_path):
    from tinypedal.replay import list_replays, read_replay_info

    filename = str(tmp_path / "replay-a.tpreplay")
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, 4, 10, {"source": "Le Mans Ultimate", "info": {"track": "Spa"}})
        for index in range(30):
            writer.write(index * 0.1, b"abcd")
            if index == 10:
                writer.write_marker(index * 0.1, "lap", "2")
        writer.write_marker(0.5, "incident", "8.0g")  # written later, earlier time
        writer.finish()
    replay = ReplayFile(filename)
    assert [marker.kind for marker in replay.markers] == ["incident", "lap"]  # sorted by time
    assert replay.markers_of("lap")[0].text == "2"
    assert replay.summary["frames"] == 30
    assert replay.info == {"track": "Spa"}
    replay.close()
    info = read_replay_info(filename)
    assert info.duration == pytest.approx(2.9) and info.info["track"] == "Spa"
    assert [item.filename for item in list_replays(str(tmp_path))] == [filename]


def test_interrupted_recording_has_unknown_duration(tmp_path):
    from tinypedal.replay import read_replay_info

    assert read_replay_info(write_replay(tmp_path, make_frames(5))).duration == -1


def test_rest_snapshot_written_only_when_changed():
    writer = ReplayWriter(io.BytesIO(), 4, 10)
    assert writer.write_rest(0.0, {"a": 1})
    assert not writer.write_rest(1.0, {"a": 1})
    assert writer.write_rest(2.0, {"a": 2})


def test_frames_read_from_file_on_demand(tmp_path):
    frames = make_frames(KEYFRAME_INTERVAL + 20)
    replay = ReplayFile(write_replay(tmp_path, frames))
    assert not hasattr(replay, "_payloads")  # only frame positions in memory
    section = [frame for _, frame in replay.iter_frames(KEYFRAME_INTERVAL + 5, KEYFRAME_INTERVAL + 7)]
    assert section == frames[KEYFRAME_INTERVAL + 5:KEYFRAME_INTERVAL + 8]
    replay.close()


def test_export_section(tmp_path):
    frames = make_frames(KEYFRAME_INTERVAL * 2)
    filename = str(tmp_path / "full.tpreplay")
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, len(frames[0]), 10, {"source": "Le Mans Ultimate"})
        for index, frame in enumerate(frames):
            writer.write(index * 0.1, frame)
            if index % 50 == 0:
                writer.write_rest(index * 0.1, {"timeScale": index})
        writer.write_marker(12.0, "incident", "x")
        writer.finish()
    replay = ReplayFile(filename)
    section = str(tmp_path / "section.tpreplay")
    count = replay.export(section, 11.0, 13.0)
    assert count == 21
    part = ReplayFile(section)
    assert len(part) == 21 and part.times[0] == 0.0
    assert [part.frame(index) for index in range(21)] == frames[110:131]  # first frame re-keyed
    assert part.rest_data[0] == {"timeScale": 100}  # snapshot in effect at section start
    assert part.markers[0].time == pytest.approx(1.0)
    assert part.header["trimmed_from"] == "full.tpreplay"
    part.close()
    replay.close()


def test_player_step(tmp_path):
    clock = Clock()
    player = ReplayPlayer(ReplayFile(write_replay(tmp_path, make_frames(10))), clock=clock)
    player.seek(0.5)
    player.step(1)
    assert player.paused and player.position == pytest.approx(0.6)
    player.step(-3)
    assert player.position == pytest.approx(0.3)
    player.step(-99)
    assert player.position == 0.0


def test_recording_skips_inactive_frames_and_writes_markers(tmp_path):
    import time

    from tinypedal.replay import RecordingSources

    control = ReplayControl()
    state = {"active": True, "lap": 1}
    filename = str(tmp_path / "rec.tpreplay")
    sources = RecordingSources(
        frame=lambda: b"abcd", active=lambda: state["active"], lap=lambda: state["lap"],
        info=lambda: {"track": "Spa"})
    control.start_recording(filename, sources, rate=100)
    while control.recorded_frames < 5:
        time.sleep(0.005)
    state["active"] = False
    time.sleep(1.3)  # inactive gap removed from replay time
    state["active"] = True
    state["lap"] = 2
    assert control.add_marker("incident", "9g", ago=0.0)
    frames = control.recorded_frames
    while control.recorded_frames < frames + 5:
        time.sleep(0.005)
    control.stop_recording()
    assert not control.add_marker("incident")  # not recording
    replay = ReplayFile(filename)
    assert replay.duration < 1.0
    assert [marker.text for marker in replay.markers_of("lap")] == ["1", "2"]
    assert replay.markers_of("incident")[0].text == "9g"
    assert replay.info == {"track": "Spa"} and replay.summary
    replay.close()


def test_recording_without_frame_leaves_no_file(tmp_path):
    import time

    control = ReplayControl()
    filename = str(tmp_path / "empty.tpreplay")
    control.start_recording(filename, lambda: None, rate=100)
    time.sleep(0.05)
    control.stop_recording()
    assert not (tmp_path / "empty.tpreplay").exists()


def test_remove_old_replays(tmp_path):
    import os

    from tinypedal.replay import remove_old_replays

    for index in range(4):
        path = tmp_path / f"replay-auto-{index}.tpreplay"
        path.write_bytes(b"x")
        os.utime(path, (1000 + index, 1000 + index))
    (tmp_path / "replay-manual.tpreplay").write_bytes(b"x")
    removed = remove_old_replays(str(tmp_path), "replay-auto-", 2)
    assert sorted(removed) == ["replay-auto-0.tpreplay", "replay-auto-1.tpreplay"]
    assert (tmp_path / "replay-manual.tpreplay").exists()  # manual recordings never removed


def test_replay_view_markers_and_section(ui_env, tmp_path, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.replay import replay
    from tinypedal.ui import replay_view

    size = ctypes.sizeof(lmu_data.LMUObjectOut)
    filename = str(tmp_path / "markers.tpreplay")
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, size, 10, {"info": {"track": "Spa"}})
        frame = bytes(size)
        for index in range(100):
            writer.write(index * 0.1, frame)
        writer.write_marker(2.0, "lap", "3")
        writer.write_marker(6.0, "incident", "9g")
        writer.finish()
    monkeypatch.setattr(replay_view, "restart_api", lambda: None)
    monkeypatch.setattr(type(api), "name", property(lambda self: replay_view.API_LMU_NAME))
    monkeypatch.setattr(replay_view.cfg.path, "telemetry", str(tmp_path))
    dialog = replay_view.ReplayView(None)
    try:
        assert dialog.replay_list.topLevelItemCount() == 1
        assert dialog.replay_list.topLevelItem(0).text(1) == "Spa"
        dialog.replay_list.setCurrentItem(dialog.replay_list.topLevelItem(0))
        dialog.open_selected()
        assert replay.active
        assert dialog.slider.laps == [2.0] and dialog.slider.incidents == [6.0]
        assert dialog.combo_lap.count() == 1
        replay.player.set_paused(True)
        dialog.goto_lap(0)
        assert replay.player.position == pytest.approx(2.0)
        dialog.goto_incident(1)
        assert replay.player.position == pytest.approx(3.0)  # 3 seconds before incident
        dialog.step(1)
        assert replay.player.position == pytest.approx(3.1)
        dialog.set_section(0)
        replay.player.seek(5.0)
        dialog.set_section(1)
        assert dialog.button_section_save.isEnabled()
        target = str(tmp_path / "part.tpreplay")
        monkeypatch.setattr(replay_view.QFileDialog, "getSaveFileName", lambda *args: (target, ""))
        dialog.save_section()
        part = ReplayFile(target)
        assert part.duration == pytest.approx(1.9)
        part.close()
        dialog.stop_replay()
    finally:
        replay.unload()
        dialog.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_unload_keeps_frames_readable_until_api_restarts(tmp_path):
    """Back to Game: API reads frames until restarted, file closing must not break it"""
    control = ReplayControl()
    player = control.load(write_replay(tmp_path, make_frames(5)))
    control.unload()
    assert player.current_frame()  # was "seek of closed file" in API thread
