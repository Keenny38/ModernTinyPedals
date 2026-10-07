"""Module tests, replaying simulated laps through real module code"""

from types import SimpleNamespace

import pytest

from tests.telemetry_sim import LapSim, fake_reader
from tinypedal import realtime_state
from tinypedal.api_control import api
from tinypedal.module import module_delta, module_fuel
from tinypedal.module_info import DeltaInfo, FuelInfo, minfo


@pytest.fixture
def sim_api(monkeypatch):
    """Patch api reader & active state, return function to set simulator"""
    monkeypatch.setattr(realtime_state, "active", True)
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))

    def use(sim: LapSim):
        monkeypatch.setattr(api, "read", fake_reader(sim))
    return use


def run_delta(sim: LapSim, tmp_path, on_tick=None) -> DeltaInfo:
    """Run delta module generators through simulated laps"""
    output = DeltaInfo()
    gen_distance = module_delta.calc_delta_distance(output=output)
    gen_time = module_delta.calc_delta_time(
        output=output,
        filepath=f"{tmp_path}/",
        min_delta_distance=5,
        delta_smoothing_samples=1,
        laptime_pace_samples=5,
        laptime_pace_margin=5,
    )
    while not sim.finished or sim.elapsed < sim.lap_start + 3:  # keep running 3s after finish
        gen_distance.send(0)
        gen_time.send(0)
        if on_tick:
            on_tick(sim, output)
        sim.tick()
    return output


def test_delta_best_lap(sim_api, tmp_path):
    sim = LapSim([92.0, 90.0, 91.0])
    sim_api(sim)
    samples = []

    def check(sim, output):
        # Record delta at mid-lap of 3rd lap (1s slower than best lap 90s at same pace profile)
        if sim.lap_index == 2 and 0.49 < sim.lap_progress < 0.51:
            samples.append(output.deltaBest)

    output = run_delta(sim, tmp_path, check)
    assert output.lapTimeBest == pytest.approx(90.0, abs=0.05)
    assert output.lapTimeLast == pytest.approx(91.0, abs=0.05)
    # Half lap into 91s lap vs 90s best: about +0.5s
    assert samples
    assert sum(samples) / len(samples) == pytest.approx(0.5, abs=0.1)
    # Best lap saved to delta best file
    assert (tmp_path / "SimTrack - SimCar.csv").exists()


def test_delta_best_file_reloaded(sim_api, tmp_path):
    first = LapSim([99.0, 90.0, 95.0])  # first lap is out lap (not timed from start line)
    sim_api(first)
    run_delta(first, tmp_path)  # first session, store best lap file
    sim = LapSim([93.0])
    sim_api(sim)
    output = run_delta(sim, tmp_path)
    assert output.lapTimeBest == pytest.approx(90.0, abs=0.05)  # from file


def test_fuel_consumption(sim_api, tmp_path, monkeypatch):
    sim = LapSim([90.0, 90.0, 90.0], fuel_per_lap=[2.0, 2.5, 3.0], fuel_start=40.0)
    sim_api(sim)
    monkeypatch.setattr(minfo, "delta", DeltaInfo())
    output = FuelInfo()
    gen = module_fuel.calc_consumption(
        output=output,
        is_energy=False,
        filepath=f"{tmp_path}/",
        extension=".fuel",
        min_delta_distance=5,
        fuel_density=0.75,
    )
    while not sim.finished or sim.elapsed < sim.lap_start + 3:
        minfo.delta.lapDistance = sim.distance
        gen.send(0)
        sim.tick()
    assert output.lastLapConsumption == pytest.approx(3.0, abs=0.05)
    assert output.amountCurrent == pytest.approx(40.0 - 7.5, abs=0.05)
    assert output.weight == pytest.approx(0.75 * output.amountCurrent, abs=0.01)


def test_telemetry_recorder(sim_api, tmp_path):
    from tinypedal.module import module_recorder

    sim = LapSim([95.0, 90.0, 91.0])  # first lap is out lap (not complete), 2 complete laps saved
    sim_api(sim)
    gen = module_recorder.record_telemetry(filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10)
    while not sim.finished or sim.elapsed < sim.lap_start + 2:  # validated 1s after crossing line
        gen.send(0)
        sim.tick()
    files = sorted((tmp_path / "SimTrack - SimCar").glob("*.csv"))
    assert len(files) == 2
    assert not any("invalid" in file.name for file in files)
    assert "1m30.000s" in files[0].name or "1m30.000s" in files[1].name
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith('# {"kind": "lap"')  # lap info
    assert lines[1].startswith("time,lap_time,distance,speed_kph")
    assert lines[2].split(",")[4:6] == ["0.8", "0.1"]  # unfiltered throttle & brake (pedal position)
    assert len(lines) > 4000  # 90s at 50Hz


class InvalidLapSim(LapSim):
    """All laps invalid (track limits), game reports no last lap time"""

    def tick(self):
        super().tick()
        self.last_laptime = -1.0


def test_telemetry_recorder_invalid_lap(sim_api, tmp_path):
    from tinypedal.module import module_recorder

    sim = InvalidLapSim([95.0, 90.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10)
    while not sim.finished or sim.elapsed < sim.lap_start + 11:  # not validated within 10s
        gen.send(0)
        sim.tick()
    files = list((tmp_path / "SimTrack - SimCar").glob("*.csv"))
    assert len(files) == 1 and files[0].name.endswith(" invalid.csv")


def test_telemetry_recorder_limit_per_track(tmp_path):
    from tinypedal.module import module_recorder

    for lap in range(5):
        module_recorder.save_lap(f"{tmp_path}/", "TrackA - GT3", lap, 90.0 + lap, [], max_saved_laps=3)
    module_recorder.save_lap(f"{tmp_path}/", "TrackB - GT3", 1, 80.0, [], max_saved_laps=3)
    assert len(list((tmp_path / "TrackA - GT3").glob("*.csv"))) == 3
    assert len(list((tmp_path / "TrackB - GT3").glob("*.csv"))) == 1


def run_recorder(sim, gen, extra=2.0):
    while not sim.finished or sim.elapsed < sim.lap_start + extra:
        gen.send(0)
        sim.tick()


def test_telemetry_recorder_keeps_best_laps(tmp_path):
    from tinypedal.module import module_recorder

    times = [95.0, 88.0, 91.0, 92.0, 93.0, 94.0]
    for lap, lap_time in enumerate(times):
        module_recorder.save_lap(
            f"{tmp_path}/", "T - C", lap, lap_time, [], max_saved_laps=3, keep_best=1, timestamp=1000.0 + lap)
    names = sorted(file.name for file in (tmp_path / "T - C").glob("*.csv"))
    assert len(names) == 3
    assert any("1m28.000s" in name for name in names)  # best lap kept although oldest
    assert any("1m34.000s" in name for name in names)  # newest kept


def test_telemetry_recorder_discards_lap_when_time_goes_back(sim_api, tmp_path):
    """Replay looping: elapsed time jumps back, incomplete lap is dropped instead of saved with wrong time"""
    from tinypedal.module import module_recorder

    sim = LapSim([95.0, 90.0, 91.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10)
    jumped = False
    while not sim.finished or sim.elapsed < sim.lap_start + 2:
        gen.send(0)
        sim.tick()
        if not jumped and sim.lap_index == 1 and sim.lap_progress > 0.5:
            jumped = True  # rewind to start of lap 2
            sim.elapsed = sim.lap_start + 0.02
    files = list((tmp_path / "SimTrack - SimCar").glob("*.csv"))
    assert len(files) == 1 and "1m31.000s" in files[0].name  # rewound lap 2 dropped, lap 3 saved


def test_telemetry_recorder_skips_duplicate_samples(sim_api, tmp_path):
    from tinypedal.module import module_recorder

    sim = LapSim([95.0, 90.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10)
    while not sim.finished or sim.elapsed < sim.lap_start + 2:
        gen.send(0)
        gen.send(0)  # game data not updated between module updates
        sim.tick()
    lines = next((tmp_path / "SimTrack - SimCar").glob("*.csv")).read_text(encoding="utf-8").splitlines()
    times = [line.split(",")[0] for line in lines[2:]]
    assert len(times) == len(set(times))


class PitLapSim(LapSim):
    """Car starts in pit lane (out lap), last lap ends in pit lane (in lap)"""

    def in_pits(self):
        return self.lap_index == 0 or self.lap_index >= len(self.lap_times) - 1


def test_telemetry_recorder_out_and_in_laps(sim_api, tmp_path):
    from tinypedal.module import module_recorder
    from tinypedal.userfile.telemetry_lap import list_laps, load_lap

    for save_out_in, expected in ((False, 1), (True, 3)):
        folder = tmp_path / str(save_out_in)
        sim = PitLapSim([100.0, 100.0, 90.0, 100.0])
        sim_api(sim)
        api_read = module_recorder.api.read
        api_read.vehicle.in_pits = lambda index=None, sim=sim: sim.in_pits()
        gen = module_recorder.record_telemetry(
            filepath=f"{folder}/", min_lap_fraction=0.9, max_saved_laps=10, save_out_in=save_out_in)
        run_recorder(sim, gen)
        laps = list_laps(f"{folder}/", "SimTrack - SimCar")
        assert len(laps) == expected
        kinds = sorted(load_lap(lap.path).meta["kind"] for lap in laps)
        assert kinds == (["in", "lap", "out"] if save_out_in else ["lap"])


def test_auto_replay(monkeypatch):
    from tinypedal import replay_session
    from tinypedal.replay import replay

    calls = []
    state = {"recording": False}
    monkeypatch.setattr(replay_session, "api_supported", lambda: True)
    monkeypatch.setattr(type(replay), "recording", property(lambda self: state["recording"]))
    monkeypatch.setattr(type(replay), "active", property(lambda self: False))

    def start(auto=False):
        calls.append("start")
        state["recording"] = True
        return "replay-auto-x.tpreplay"

    def stop():
        calls.append("stop")
        state["recording"] = False

    monkeypatch.setattr(replay_session, "start_api_recording", start)
    monkeypatch.setattr(replay, "stop_recording", stop)
    monkeypatch.setattr(replay_session, "remove_old_replays", lambda *args: ["old.tpreplay"])
    auto = replay_session.AutoReplay(keep=2, stop_delay=5.0)
    auto.update(False, 0.0)
    assert calls == []
    auto.update(True, 1.0)
    auto.update(True, 2.0)
    assert calls == ["start"]
    auto.update(False, 3.0)
    auto.update(False, 7.0)
    assert calls == ["start"]  # not stopped before delay
    auto.update(False, 8.5)
    assert calls == ["start", "stop"]
    auto.update(True, 9.0)
    assert calls == ["start", "stop", "start"]
    state["recording"] = False  # stopped from replay window
    auto.update(True, 10.0)
    assert calls == ["start", "stop", "start"]  # not restarted while still driving
    auto.update(False, 11.0)
    auto.update(True, 12.0)
    assert calls[-1] == "start"


class LateResetSim(LapSim):
    """Lap distance reset 0.2s after lap start (game scoring slower than telemetry)"""

    @property
    def distance(self):
        if self.lap_index > 0 and self.elapsed - self.lap_start < 0.2:
            return self.track_length - 1.0
        if self.lap_index == 2:  # timing restarted after 6s: car only covered a few meters
            return (self.elapsed - self.lap_start) * 20.0
        return super().distance


def test_telemetry_recorder_ignores_late_distance_reset(sim_api, tmp_path):
    """A short lap (timing restarted 6s after start line) was saved because its first samples
    carried previous lap distance, passing the minimum distance check"""
    from tinypedal.module import module_recorder

    sim = LateResetSim([95.0, 90.0, 6.0, 91.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10)
    run_recorder(sim, gen, extra=11.0)
    names = sorted(file.name for file in (tmp_path / "SimTrack - SimCar").glob("*.csv"))
    assert len(names) == 2 and not any("0m06" in name for name in names)


def test_telemetry_recorder_validates_lap_when_leaving_track(sim_api, tmp_path):
    from tinypedal.module import module_recorder

    sim = LapSim([95.0, 90.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10)
    while not sim.finished or sim.elapsed < sim.lap_start + 0.5:
        gen.send(0)
        sim.tick()
    gen.send(None)  # back to garage
    names = [file.name for file in (tmp_path / "SimTrack - SimCar").glob("*.csv")]
    assert len(names) == 1 and "invalid" not in names[0]  # game confirmed lap time: valid


def test_telemetry_recorder_background_saver(sim_api, tmp_path):
    from tinypedal.module import module_recorder

    saved = []
    sim = LapSim([95.0, 90.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(
        filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10,
        saver=lambda pending, options, valid: saved.append((pending.lap_time, valid)))
    run_recorder(sim, gen)
    assert saved == [(90.0, True)]


# --- Audit fixes (package A)
def test_lap_samples_same_csv_as_rows():
    """Samples stored in typed columns: same values & types back, CSV unchanged"""
    from array import array

    from tinypedal.module import module_recorder

    rows = [
        (1.5, 2, 0, "x", True, 7.25, 1e-7),
        (2.25, 3, 1.5, "y", False, 0, 123456.789),  # int 0 in float column (invalid value check)
        (3.0, -1, 2.0, "z", True, 1.0, -0.0),
    ]
    samples = module_recorder.LapSamples()
    for row in rows:
        samples.append(row)
    assert len(samples) == 3 and list(samples) == rows and samples[-1] == rows[-1]
    assert module_recorder.lap_text(samples, {"kind": "lap"}) == module_recorder.lap_text(rows, {"kind": "lap"})
    assert isinstance(samples.column(0), array) and isinstance(samples.column(1), array)  # stable types
    assert list(samples.column(5)) == [7.25, 0, 1.0] and type(samples.column(5)[1]) is int
    empty = module_recorder.LapSamples()
    assert not empty and list(empty.column(2)) == []
    with pytest.raises(ValueError):
        samples.append((1.0,))


def test_recorder_samples_written_as_before(sim_api, tmp_path):
    """Lap file content from typed columns equals content from rows of tuples"""
    from tinypedal.module import module_recorder

    saved = []
    sim = LapSim([95.0, 90.0])
    sim_api(sim)
    gen = module_recorder.record_telemetry(
        filepath=f"{tmp_path}/", min_lap_fraction=0.9, max_saved_laps=10,
        saver=lambda pending, options, valid: saved.append(pending))
    run_recorder(sim, gen)
    rows = saved[0].rows
    assert isinstance(rows, module_recorder.LapSamples) and len(rows) > 4000
    assert module_recorder.lap_text(rows) == module_recorder.lap_text([tuple(row) for row in rows])


def test_recorder_module_saves_pending_lap_on_stop(ui_env, monkeypatch):
    """Module stopped (reload, quit) right after a lap: lap waiting for validation is saved, saver awaited"""
    import time

    from tinypedal.module import module_recorder
    from tinypedal.setting import cfg

    sends = []

    def fake_recorder(**kwargs):
        def recorder():
            while True:
                sends.append((yield None))

        gen = recorder()
        next(gen)
        return gen

    waits = []
    monkeypatch.setattr(module_recorder, "record_telemetry", fake_recorder)
    monkeypatch.setattr(module_recorder, "wait_lap_saver", lambda timeout=None: waits.append(timeout) or True)
    monkeypatch.setattr(realtime_state, "active", True)
    module = module_recorder.Realtime(cfg, "module_recorder")
    module.start()
    end = time.monotonic() + 5
    while len(sends) < 2 and time.monotonic() < end:
        time.sleep(0.01)
    module.stop()
    while not module.closed and time.monotonic() < end:
        time.sleep(0.01)
    assert module.closed and sends[0] is not None
    assert sends[-1] is None and waits  # pending lap flushed, then saving awaited


def test_wait_lap_saver():
    import threading

    from tinypedal.module import module_recorder

    release = threading.Event()
    module_recorder.LAP_SAVER.submit(release.wait, 5)
    assert not module_recorder.wait_lap_saver(0.05)  # lap still being written
    release.set()
    assert module_recorder.wait_lap_saver(5)


def test_background_lap_save_error_logged(caplog):
    """Unexpected error while saving lap in background is logged, not lost with discarded future"""
    from tinypedal.module import module_recorder

    class BrokenLap:
        def save(self, options, valid):
            raise KeyError("broken")

    with caplog.at_level("ERROR", logger=module_recorder.__name__):
        module_recorder.save_lap_background(BrokenLap(), None, True)
        assert module_recorder.wait_lap_saver(5)
    records = [record for record in caplog.records if "failed saving lap" in record.getMessage()]
    assert records and records[0].exc_info is not None


def test_remove_old_laps_skips_locked_file(tmp_path, monkeypatch):
    """A lap open in lap viewer (Windows: PermissionError) must not stop rotation"""
    import os

    from tinypedal.module import module_recorder

    folder = tmp_path / "T - C"
    for lap in range(5):
        module_recorder.save_lap(f"{tmp_path}/", "T - C", lap, 90.0 + lap, [], max_saved_laps=99, timestamp=1000.0 + lap)
    paths = sorted(folder.glob("*.csv"))
    for index, path in enumerate(paths):
        os.utime(path, (1000 + index, 1000 + index))
    locked = str(paths[0])
    remove = os.remove

    def locked_remove(path):
        if os.path.normpath(path) == os.path.normpath(locked):
            raise PermissionError(13, "used by another process")
        remove(path)

    monkeypatch.setattr(module_recorder.os, "remove", locked_remove)
    module_recorder.remove_old_laps(str(folder), 3)
    remaining = sorted(folder.glob("*.csv"))
    assert remaining == [paths[0], paths[3], paths[4]]  # locked kept, next oldest removed instead


def test_unreadable_lap_marks_keep_kept_laps_and_marks(tmp_path, monkeypatch):
    """Marks file locked or damaged: no lap removed, marks never saved over (was: kept lap removed, marks erased)"""
    import json
    import os

    from tinypedal.module import module_recorder
    from tinypedal.userfile import lap_marks

    folder = tmp_path / "T - C"
    for lap in range(4):
        module_recorder.save_lap(f"{tmp_path}/", "T - C", lap, 90.0 + lap, [], max_saved_laps=99, timestamp=1000.0 + lap)
    paths = sorted(folder.glob("*.csv"))
    for index, path in enumerate(paths):
        os.utime(path, (1000 + index, 1000 + index))
    assert lap_marks.set_mark(str(paths[0]), kept=True)
    assert lap_marks.set_mark(str(paths[1]), note="wet")
    marks_path = folder / lap_marks.MARKS_FILE
    saved = marks_path.read_text(encoding="utf-8")
    # Locked by other program (sync client, antivirus)
    with monkeypatch.context() as patch:
        def locked_open(file, *args, **kwargs):
            if str(file).endswith(lap_marks.MARKS_FILE):
                raise PermissionError(13, "used by another process")
            return open(file, *args, **kwargs)
        patch.setattr(lap_marks, "open", locked_open, raising=False)
        module_recorder.remove_old_laps(str(folder), 2)
        assert sorted(folder.glob("*.csv")) == paths  # kept lap unknown: none removed
        assert not lap_marks.set_mark(str(paths[2]), kept=True)
        assert not lap_marks.remove_mark(str(paths[1]))
    assert marks_path.read_text(encoding="utf-8") == saved
    # Damaged file: same
    marks_path.write_text('{"broken', encoding="utf-8")
    module_recorder.remove_old_laps(str(folder), 2)
    assert sorted(folder.glob("*.csv")) == paths
    assert not lap_marks.set_mark(str(paths[2]), kept=True)
    assert marks_path.read_text(encoding="utf-8") == '{"broken'
    assert lap_marks.load_marks(str(folder)) == {}  # viewer still opens
    # Readable again: oldest lap kept, next oldest removed
    marks_path.write_text(saved, encoding="utf-8")
    module_recorder.remove_old_laps(str(folder), 2)
    assert sorted(folder.glob("*.csv")) == [paths[0], paths[3]]
    assert json.loads(marks_path.read_text(encoding="utf-8"))[paths[0].name] == {"kept": True}


def test_lap_folder_name_valid_on_windows(tmp_path):
    from tinypedal.module import module_recorder

    name = module_recorder.lap_folder_name
    assert name("Spa - ") == "Spa"  # empty class: Windows drops trailing space, files not writable
    assert name("Spa - GT3.") == "Spa - GT3" and name("Spa - GT3") == "Spa - GT3"
    assert name("") == "unknown" and name(" . ") == "unknown" and name("CON") == "CON_"
    assert module_recorder.save_lap(f"{tmp_path}/", "Spa - ", 1, 90.0, [], max_saved_laps=5)
    assert len(list((tmp_path / "Spa").glob("*.csv"))) == 1
