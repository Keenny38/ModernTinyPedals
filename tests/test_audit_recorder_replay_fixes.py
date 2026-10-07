"""Audit fixes: module data saved on error, recorder lap validation after reset, replay files, imports"""

import math
import os
import zipfile
from types import SimpleNamespace

import pytest

from tests.telemetry_sim import LapSim, fake_reader
from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.module._base import MODULE_STOP, DataModule
from tinypedal.replay import KEYFRAME_INTERVAL, ReplayFile, ReplayWriter, list_replays, read_replay_info


# --- Module data saved when update loop ends by error
def test_save_on_stop_survives_broken_generators(caplog):
    sent = []

    class Generator:
        def send(self, value):
            sent.append(value)

    class Ended:
        def send(self, value):
            raise StopIteration

    class Broken:
        def send(self, value):
            raise OSError("disk full")

    module = DataModule.__new__(DataModule)
    module.discard = False
    module.module_name = "module_test"
    module.save_on_stop(Ended(), Broken(), Generator())
    assert sent == [MODULE_STOP]  # other generators still saved
    assert any("saving data on stop failed" in record.getMessage() for record in caplog.records)


def test_module_saves_data_when_update_crashes(monkeypatch):
    """Error in update loop: data not saved yet is written before module restarts (and reloads file)"""
    import threading

    from tinypedal.module import module_stint

    sent = []

    def consumption(**kwargs):
        return SimpleNamespace(send=sent.append)

    def stint(**kwargs):
        def send(value):
            raise KeyError("broken")
        return SimpleNamespace(send=send)

    monkeypatch.setattr(module_stint, "record_consumption_history", consumption)
    monkeypatch.setattr(module_stint, "record_stint_history", stint)
    monkeypatch.setattr(realtime_state, "active", True)
    module = module_stint.Realtime.__new__(module_stint.Realtime)
    module.module_name = "module_stint"
    module.discard = False
    module._event = threading.Event()
    module.active_interval = module.idle_interval = 0.001
    module.mcfg = {"minimum_stint_threshold_minutes": 1, "minimum_pitstop_threshold_seconds": 1,
                   "minimum_tyre_temperature_threshold": 1}
    module.cfg = SimpleNamespace(path=SimpleNamespace(fuel_delta=""))
    with pytest.raises(KeyError):
        module.update_data()
    assert sent[-1] is MODULE_STOP


# --- Recorder: lap left just after start line validated when game confirms it
@pytest.fixture
def sim_api(monkeypatch):
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))

    def use(sim):
        monkeypatch.setattr(api, "read", fake_reader(sim))
    return use


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def leave_after_line(sim_api, clock):
    """Lap completed, back to garage 0.3s later while game last lap time not updated yet"""
    from tinypedal.module import module_recorder

    saved = []
    sim = LapSim([95.0, 90.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(
        filepath="", min_lap_fraction=0.9, max_saved_laps=10, clock=clock,
        saver=lambda pending, options, valid: saved.append((pending.lap_time, valid)))
    while not sim.finished or sim.elapsed < sim.lap_start + 0.3:
        gen.send(0)
        sim.tick()
    official, sim.last_laptime = sim.last_laptime, 95.0  # scoring (slower) still has previous lap
    return sim, gen, saved, official


def test_recorder_validates_lap_after_leaving_track(sim_api):
    clock = Clock()
    sim, gen, saved, official = leave_after_line(sim_api, clock)
    assert gen.send(None) is True  # back to garage: lap kept waiting for game lap time
    assert saved == []
    clock.now += 0.5
    sim.last_laptime = official  # scoring updated
    assert gen.send(None) is False
    assert saved == [(90.0, True)]


def test_recorder_lap_left_unconfirmed_saved_invalid_after_delay(sim_api):
    from tinypedal.module import module_recorder

    clock = Clock()
    _, gen, saved, _ = leave_after_line(sim_api, clock)
    gen.send(None)
    clock.now += module_recorder.PENDING_WAIT - 1
    gen.send(None)
    assert saved == []
    clock.now += 1
    gen.send(None)
    assert saved == [(90.0, False)]


def test_recorder_lap_left_unconfirmed_saved_on_module_stop(sim_api):
    _, gen, saved, _ = leave_after_line(sim_api, Clock())
    gen.send(None)
    assert gen.send(MODULE_STOP) is False
    assert saved == [(90.0, False)]


def test_lap_info_replay_unloaded_meanwhile(monkeypatch):
    """Replay unloaded from GUI thread between check & use: no AttributeError"""
    from tinypedal.module import module_recorder

    class Replay:
        def __init__(self):
            self.reads = 0

        @property
        def player(self):
            self.reads += 1
            if self.reads == 1:
                return SimpleNamespace(replay=SimpleNamespace(filename="/x/replay.tpreplay", created=0), position=0)
            return None

    monkeypatch.setattr(module_recorder, "replay", Replay())
    monkeypatch.setattr(api, "read", SimpleNamespace())
    info = module_recorder.lap_info("lap", [])
    assert info["replay"] == "replay.tpreplay"


# --- Replay session: folder creation failure never stops recorder module
def test_auto_replay_folder_error(monkeypatch, caplog):
    from tinypedal import replay_session
    from tinypedal.replay import replay

    makedirs = []

    def failing_makedirs(*args, **kwargs):
        makedirs.append(args)
        raise PermissionError("denied")

    monkeypatch.setattr(replay_session, "api_supported", lambda: True)
    monkeypatch.setattr(type(replay), "recording", property(lambda self: False))
    monkeypatch.setattr(type(replay), "active", property(lambda self: False))
    monkeypatch.setattr(replay_session.os, "makedirs", failing_makedirs)
    monkeypatch.setattr(replay, "start_recording", lambda *args, **kwargs: pytest.fail("recording started"))
    assert replay_session.start_api_recording() == ""
    auto = replay_session.AutoReplay(keep=2)
    auto.update(True, 1.0)
    auto.update(True, 2.0)
    assert len(makedirs) == 2  # direct call + one try while driving, not every update
    auto.update(False, 3.0)
    auto.update(True, 4.0)
    assert len(makedirs) == 3  # tried again next driving


# --- Replay files
def write_replay(filename, count: int = KEYFRAME_INTERVAL + 5, extra: dict | None = None) -> str:
    frames = [bytes((index + offset) % 256 for offset in range(32)) for index in range(count)]
    with open(filename, "wb") as file:
        writer = ReplayWriter(file, 32, 10, extra)
        for index, frame in enumerate(frames):
            writer.write(index * 0.1, frame)
        writer.finish()
    return str(filename)


@pytest.mark.parametrize("field", [{"created": None}, {"created": [1]}, {"rate": None}, {"rate": "x"},
                                   {"source": None}, {"created": float("inf")}, {"created": 10 ** 400}])
def test_replay_header_types_validated(tmp_path, field):
    good = write_replay(tmp_path / "good.tpreplay")
    bad = write_replay(tmp_path / "bad.tpreplay", extra=field)
    assert [item.filename for item in list_replays(str(tmp_path))] == [good]  # one bad file never hides others
    with pytest.raises(ValueError):
        read_replay_info(bad)
    with pytest.raises(ValueError):
        ReplayFile(bad)


def test_replay_summary_duration_type(tmp_path, monkeypatch):
    """Summary with null duration: unknown duration instead of TypeError"""
    from tinypedal import replay as replay_module

    filename = write_replay(tmp_path / "a.tpreplay")
    monkeypatch.setattr(replay_module, "read_summary", lambda file, frame_header=None: {"duration": None})
    assert read_replay_info(filename).duration == -1.0


def test_replay_index_packed(tmp_path):
    from array import array

    replay_file = ReplayFile(write_replay(tmp_path / "a.tpreplay"))
    assert isinstance(replay_file.times, array) and isinstance(replay_file.keyframes, bytearray)
    assert replay_file.keyframes[0] and not replay_file.keyframes[1]
    assert replay_file.index_at(0.35) == 3
    replay_file.close()


def test_export_section_atomic(tmp_path, monkeypatch):
    replay_file = ReplayFile(write_replay(tmp_path / "full.tpreplay"))
    target = tmp_path / "section.tpreplay"
    target.write_bytes(b"previous section")

    def broken(*args):
        yield 0.0, bytes(32)
        raise OSError("disk full")

    monkeypatch.setattr(replay_file, "iter_frames", broken)
    with pytest.raises(OSError):
        replay_file.export(str(target), 0.5, 1.5)
    assert target.read_bytes() == b"previous section"  # never truncated
    assert not list(tmp_path.glob("*.part"))
    monkeypatch.undo()
    assert replay_file.export(str(target), 0.5, 1.5) == 11
    assert len(ReplayFile(str(target))) == 11
    replay_file.close()


def test_export_section_never_replaces_open_replay(tmp_path):
    source = tmp_path / "full.tpreplay"
    replay_file = ReplayFile(write_replay(source))
    size = source.stat().st_size
    other_name = str(tmp_path / "." / "full.tpreplay")
    link = tmp_path / "link.tpreplay"
    names = [other_name]
    try:
        os.symlink(source, link)
        names.append(str(link))
    except (OSError, NotImplementedError):
        pass
    for name in names:
        with pytest.raises(ValueError):
            replay_file.export(name, 0.5, 1.5)
    assert source.stat().st_size == size
    replay_file.close()


def test_same_file(tmp_path):
    from tinypedal.replay import same_file

    first = tmp_path / "a.tpreplay"
    first.write_bytes(b"x")
    assert same_file(str(first), str(tmp_path / "." / "a.tpreplay"))
    assert not same_file(str(first), str(tmp_path / "missing.tpreplay"))
    assert same_file(str(tmp_path / "missing.tpreplay"), str(tmp_path / "missing.tpreplay"))


# --- Bug report
def test_bug_report_written_atomically(ui_env, tmp_path, monkeypatch):
    from tinypedal import bug_report

    target = tmp_path / "report.zip"
    target.write_bytes(b"previous report")

    system_info = bug_report.system_info
    failing = [True]

    def broken():
        if failing[0]:
            raise OSError("disk full")
        return system_info()

    monkeypatch.setattr(bug_report, "system_info", broken)
    with pytest.raises(OSError):
        bug_report.create_bug_report(str(target))
    assert target.read_bytes() == b"previous report"
    assert not list(tmp_path.glob("*.part"))
    failing[0] = False
    files = bug_report.create_bug_report(str(target), "log")
    assert "system-info.txt" in files
    with zipfile.ZipFile(target) as package:
        assert "system-info.txt" in package.namelist()
    assert not list(tmp_path.glob("*.part"))


# --- MoTeC import: channels read up to time limit only
def test_read_ld_max_seconds(tmp_path):
    from tinypedal.userfile.motec_ld import Channel, LdInfo, read_ld, write_ld

    filename = str(tmp_path / "log.ld")
    channels = [Channel("Ground Speed", "km/h", "km/h", 10, [float(index) for index in range(1000)]),
                Channel("Lap Distance", "m", "m", 50, [float(index) for index in range(5000)])]
    write_ld(filename, channels, LdInfo())
    _, full = read_ld(filename)
    assert [len(channel.values) for channel in full] == [1000, 5000]
    _, limited = read_ld(filename, max_seconds=20)
    assert [len(channel.values) for channel in limited] == [201, 1001]
    assert list(limited[0].values[:3]) == [0.0, 1.0, 2.0]


def test_import_ld_job_memory_error(monkeypatch):
    from tinypedal.userfile import motec_import, motec_ld

    def huge(*args):
        raise MemoryError

    monkeypatch.setattr(motec_import, "import_ld_file", huge)
    laps, error = motec_ld.import_ld_job("log.ld", "")
    assert laps == [] and error == "MemoryError"


# --- Official circuit: unexpected REST answer
def test_fetch_geometry_unexpected_answer(monkeypatch):
    from tinypedal.userfile import track_geometry

    center = [{"type": 0, "x": 300 * math.cos(step / 50 * math.tau), "y": 0,
               "z": 200 * math.sin(step / 50 * math.tau)} for step in range(50)]
    answers = {
        "/rest/race/track": [
            {"id": "a", "shortName": "Atlanta 1.0", "displayProperties": None, "length": ""},
            {"id": "b", "name": "Other", "displayProperties": None, "length": "   "},
        ],
        "/rest/race/track/a/trackmap": center,
    }
    monkeypatch.setattr(track_geometry, "rest_get", lambda host, port, resource, timeout=3: answers.get(resource))
    found = track_geometry.fetch_geometry("localhost", 6397, "Atlanta", [])
    assert found is not None and found.layout == "a" and found.length > 0  # length from path

