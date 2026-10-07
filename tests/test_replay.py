"""Shared memory replay: file format, seeking, playback and LMU integration"""

import ctypes
import io
import time

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


def wait_until(condition, timeout: float = 10.0):
    """Wait for recorder thread, fail instead of hanging if it stalls"""
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "recorder stalled"
        time.sleep(0.002)


def test_record_from_source(tmp_path):
    control = ReplayControl()
    source = ctypes.create_string_buffer(b"abcd", 4)
    filename = str(tmp_path / "rec.tpreplay")
    control.start_recording(filename, lambda: source, rate=200)
    wait_until(lambda: control.recorded_frames >= 3)
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
    monkeypatch.setattr(type(api), "replay_layout", lambda self: [["shmm", len(frame)]])
    monkeypatch.setattr(replay_view.QFileDialog, "getOpenFileName", lambda *args: (filename, ""))
    dialog = replay_view.ReplayView(None)
    try:
        assert not dialog.button_play.isEnabled()
        dialog.open_replay()  # loaded in background
        assert not replay.active and dialog.loader.busy
        assert dialog.loader.wait(10)
        QCoreApplication.processEvents()  # finished signal from loading thread
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
    wait_until(lambda: control.recorded_frames >= 5)
    state["active"] = False
    time.sleep(1.3)  # inactive gap removed from replay time
    state["active"] = True
    state["lap"] = 2
    assert control.add_marker("incident", "9g", ago=0.0)
    frames = control.recorded_frames
    wait_until(lambda: control.recorded_frames >= frames + 5)
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
    monkeypatch.setattr(type(api), "replay_layout", lambda self: [["shmm", size]])
    monkeypatch.setattr(replay_view.cfg.path, "telemetry", str(tmp_path))
    dialog = replay_view.ReplayView(None)
    try:
        assert dialog.replay_list.topLevelItemCount() == 1
        assert dialog.replay_list.topLevelItem(0).text(1) == "Spa"
        dialog.replay_list.setCurrentItem(dialog.replay_list.topLevelItem(0))
        dialog.open_selected()
        assert dialog.loader.wait(10)
        QCoreApplication.processEvents()  # finished signal from loading thread
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
        suggested = []

        def save_name(parent, caption, default, *args):
            suggested.append(default)
            return target, ""

        monkeypatch.setattr(replay_view.QFileDialog, "getSaveFileName", save_name)
        dialog.save_section()  # saved in background, overlays keep running
        assert dialog.export.wait(10)
        QCoreApplication.processEvents()  # finished signal from export thread
        assert "frames" in dialog.label_section.text() and dialog.button_section_save.isEnabled()
        assert suggested[0].endswith("markers-3-5.tpreplay")
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


# --- Audit fixes (package A): format version, layout check, damaged files, recording safety
def write_v1_replay(path, frames: list[bytes], header: dict | None = None, summary: bool = True) -> str:
    """Replay in format 1 (no CRC, LMU files without layout), as written by older versions"""
    import json
    import zlib

    from tinypedal.replay import FRAME_HEADER_V1, MAGIC_V1, SUMMARY_FRAME, TRAILER, TRAILER_MAGIC

    filename = str(path / "old.tpreplay")
    with open(filename, "wb") as file:
        file.write(MAGIC_V1 + json.dumps({"frame_size": len(frames[0]), "rate": 10, **(header or {})}).encode() + b"\n")
        for index, frame in enumerate(frames):
            payload = zlib.compress(frame)
            file.write(FRAME_HEADER_V1.pack(index * 0.1, 1, len(payload)) + payload)  # every frame a keyframe
        if summary:
            offset = file.tell()
            payload = json.dumps({"duration": (len(frames) - 1) * 0.1, "frames": len(frames)}).encode()
            file.write(FRAME_HEADER_V1.pack(0.0, SUMMARY_FRAME, len(payload)) + payload)
            file.write(TRAILER.pack(offset, TRAILER_MAGIC))
    return filename


def test_replay_header_has_format_version(tmp_path):
    from tinypedal.replay import FORMAT_VERSION, MAGIC, read_header

    filename = write_replay(tmp_path, make_frames(3))
    with open(filename, "rb") as file:
        assert file.read(len(MAGIC)) == MAGIC
        file.seek(0)
        assert read_header(file)["format"] == FORMAT_VERSION
    assert ReplayFile(filename).format == FORMAT_VERSION


def test_format_1_replay_still_loads(tmp_path):
    from tinypedal.replay import read_replay_info

    frames = make_frames(4)
    filename = write_v1_replay(tmp_path, frames)
    replay = ReplayFile(filename)
    assert replay.format == 1 and replay.layout == [("shmm", 64)]
    assert [replay.frame(index) for index in range(4)] == frames
    assert read_replay_info(filename).duration == pytest.approx(0.3)
    replay.close()


def test_zero_filled_tail_ignored(tmp_path):
    """Power loss leaves zeros at file end: frames end there"""
    frames = make_frames(5)
    for writer in (write_replay, write_v1_replay):
        filename = writer(tmp_path, frames)
        with open(filename, "ab") as file:
            file.write(bytes(4096))
        replay = ReplayFile(filename)
        assert len(replay) == 5 and replay.damaged
        assert replay.frame(4) == frames[4]
        replay.close()


def test_damaged_frame_skipped_until_keyframe(tmp_path):
    frames = make_frames(KEYFRAME_INTERVAL + 5)
    filename = write_replay(tmp_path, frames)
    replay = ReplayFile(filename)
    offset = replay._offsets[3]
    replay.close()
    with open(filename, "r+b") as file:  # flip a byte of delta frame 3 payload: CRC fails
        file.seek(offset)
        byte = file.read(1)
        file.seek(offset)
        file.write(bytes((byte[0] ^ 0xFF,)))
    replay = ReplayFile(filename)
    assert replay.frame(2) == frames[2]
    assert replay.frame(3) == frames[2] and replay.frame(50) == frames[2]  # last good frame held
    assert replay.frame(KEYFRAME_INTERVAL + 1) == frames[KEYFRAME_INTERVAL + 1]  # next keyframe decodes again
    exported = [frame for _, frame in replay.iter_frames(0, KEYFRAME_INTERVAL)]
    assert exported == [frames[0], frames[1], frames[2], frames[KEYFRAME_INTERVAL]]
    replay.close()


def test_summary_length_is_bounded(tmp_path):
    """Corrupt summary length must not make a 4 GB read"""
    from tinypedal.replay import FRAME_HEADER, SUMMARY_FRAME, TRAILER, TRAILER_MAGIC, read_summary

    data = io.BytesIO()
    data.write(b"x" * 10)
    data.write(FRAME_HEADER.pack(0.0, SUMMARY_FRAME, 0xFFFFFFFF, 0))
    data.write(TRAILER.pack(10, TRAILER_MAGIC))
    assert read_summary(data) == {}


@pytest.mark.parametrize("frame_size", [0, -1, "64", 1 << 40])
def test_invalid_frame_size_rejected(tmp_path, frame_size):
    import json

    filename = tmp_path / "bad.tpreplay"
    filename.write_bytes(b"TPREPLAY2 " + json.dumps({"frame_size": frame_size}).encode() + b"\n")
    with pytest.raises(ValueError):
        ReplayFile(str(filename))


def test_load_checks_api_and_structure_size(tmp_path):
    from tinypedal.replay import ReplayMismatch

    control = ReplayControl()
    filename = write_replay(tmp_path, make_frames(3))  # old style LMU file: no layout, 64 bytes
    assert control.load(filename, "Le Mans Ultimate", [["shmm", 64]])  # exact size accepted
    for api_name, layout, reason in (
        ("Le Mans Ultimate", [["shmm", 80]], "layout"),  # game structure grew: offsets would shift
        ("Le Mans Ultimate", [["shmm", 32]], "layout"),
        ("rFactor 2", [["scor", 64]], "source"),
    ):
        with pytest.raises(ReplayMismatch) as error:
            control.load(filename, api_name, layout)
        assert error.value.reason == reason and error.value.source == "Le Mans Ultimate"
        assert not control.active


def test_api_falls_back_to_game_for_incompatible_replay(tmp_path, monkeypatch):
    """Switching API (hotkey, preset) with a replay loaded: start reads game instead of failing"""
    from tinypedal import api_connector, app_signal
    from tinypedal.replay import replay

    errors: list[str] = []
    app_signal.error.connect(errors.append)
    frame = bytes(ctypes.sizeof(lmu_data.LMUObjectOut))
    replay.load(write_replay(tmp_path, [frame, frame]))
    try:
        assert api_connector.SimLMU().replay_player() is replay.player  # same structure: played
        assert api_connector.SimRF2().replay_player() is None  # LMU replay with rF2 API
        assert not replay.active and errors and "rFactor 2" in errors[0]
        replay.load(write_replay(tmp_path, [frame[:-8], frame[:-8]]))  # older, smaller structure
        assert api_connector.SimLMU().replay_player() is None and not replay.active
    finally:
        app_signal.error.disconnect(errors.append)
        replay.unload()


def test_recorded_header_has_layout(tmp_path):
    from tinypedal import api_connector

    lmu, rf2 = api_connector.SimLMU(), api_connector.SimRF2()
    assert lmu.replay_header()["layout"] == [["shmm", ctypes.sizeof(lmu_data.LMUObjectOut)]]
    assert [name for name, _ in rf2.replay_header()["layout"]] == ["scor", "tele", "ext", "ffb", "rule"]
    assert api_connector.SimLMULegacy().raw_data() is None  # before start: no AttributeError, no frame


def test_auto_replay_rotation_keeps_sections(tmp_path):
    import os

    from tinypedal.replay import remove_old_replays
    from tinypedal.replay_session import AUTO_NAME, section_filename

    names = [f"replay-auto-2026-10-0{day}-12-00-00.tpreplay" for day in range(1, 5)]
    section = "replay-auto-2026-10-01-12-00-00-12-345.tpreplay"  # saved by older versions
    for index, name in enumerate([*names, section]):
        path = tmp_path / name
        path.write_bytes(b"x")
        os.utime(path, (1000 + index, 1000 + index))
    removed = remove_old_replays(str(tmp_path), AUTO_NAME, 2)
    assert sorted(removed) == names[:2]
    assert (tmp_path / section).exists()
    default = section_filename(str(tmp_path / names[3]), 12.4, 345.9)
    assert os.path.basename(default) == "replay-2026-10-04-12-00-00-12-345.tpreplay"
    assert not AUTO_NAME.fullmatch(os.path.basename(default))


def test_recording_file_complete_after_source_error(tmp_path):
    """Unexpected error in a source: file still gets summary & trailer"""
    import time

    from tinypedal.replay import read_replay_info

    control = ReplayControl()
    count = [0]

    def frame():
        count[0] += 1
        if count[0] > 3:
            raise RuntimeError("source broken")
        return b"abcd"

    filename = str(tmp_path / "broken.tpreplay")
    control.start_recording(filename, frame, rate=100)
    end = time.monotonic() + 5
    while control.recording and time.monotonic() < end:
        time.sleep(0.01)
    control.stop_recording()
    info = read_replay_info(filename)
    assert info.duration >= 0  # summary written
    assert len(ReplayFile(filename)) == 3


def test_start_recording_only_once(tmp_path):
    import time

    control = ReplayControl()
    assert control.start_recording(str(tmp_path / "first.tpreplay"), lambda: None, rate=100)
    assert not control.start_recording(str(tmp_path / "second.tpreplay"), lambda: None, rate=100)
    control.stop_recording()
    time.sleep(0.01)
    assert not control.recording


def test_frame_decoded_outside_player_lock(tmp_path, monkeypatch):
    """Position reads (user interface) never wait for frame decoding"""
    player = ReplayPlayer(ReplayFile(write_replay(tmp_path, make_frames(5))))
    locked = []
    decode = player.replay.frame

    def frame(index):
        locked.append(player._lock.locked())
        return decode(index)

    monkeypatch.setattr(player.replay, "frame", frame)
    assert player.current_frame() == player.last_frame
    assert locked == [False]


def lmu_frames(count: int, paused_from: int | None = None) -> list[bytes]:
    """LMU frames, player on track, session time moving 0.1s per frame"""
    frames = []
    for index in range(count):
        frame = bytearray(ctypes.sizeof(lmu_data.LMUObjectOut))
        data = lmu_data.LMUObjectOut.from_buffer(frame)
        data.scoring.scoringInfo.mCurrentET = 10.0 + index * 0.1
        data.scoring.scoringInfo.mInRealtime = True
        data.scoring.scoringInfo.mNumVehicles = 1
        data.scoring.vehScoringInfo[0].mIsPlayer = True
        data.telemetry.activeVehicles = 1
        del data
        frames.append(bytes(frame))
    return frames


def test_paused_replay_keeps_overlays_active(tmp_path, monkeypatch):
    """Paused replay (frame by frame, lap viewer opening replay at lap) is not a frozen game"""
    import time

    clock = {"offset": 0.0}
    monkeypatch.setattr(lmu_connector, "monotonic", lambda: time.monotonic() + clock["offset"])
    player = ReplayPlayer(ReplayFile(write_replay(tmp_path, lmu_frames(30))))
    info = lmu_connector.LMUInfo()
    info.setReplay(player)
    info.start()
    try:
        end = time.monotonic() + 5
        while not info.isActive and time.monotonic() < end:
            time.sleep(0.02)
        assert info.isActive
        player.set_paused(True)
        clock["offset"] = 10.0  # data unchanged for 10 s
        time.sleep(0.3)
        assert info.isActive and not info.isPaused
        player.set_paused(False)
        player.loop = False
        player.seek(player.replay.duration)  # end of replay: frozen data
        clock["offset"] = 30.0
        end = time.monotonic() + 5
        while not info.isPaused and time.monotonic() < end:
            time.sleep(0.02)
        assert info.isPaused and not info.isActive
    finally:
        info.stop()
