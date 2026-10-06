"""Lap viewer audit J (E): MoTeC import & export, imported laps library, laps of other drivers' folders, delta best,
replay link"""

import json
import os
import time
from array import array

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMessageBox

from tests.test_lap_library import import_log, open_library, viewer  # noqa: F401
from tests.test_lap_viewer_e2 import TRACK, backend, lap_info, write_lap  # noqa: F401
from tests.test_motec_import import logger_channels, write_logger_ld
from tinypedal.userfile import lap_library, motec_import
from tinypedal.userfile.lap_cache import cache_file, load_cached_lap
from tinypedal.userfile.lap_library import delete_laps, import_foreign_job, list_imported, restore_laps
from tinypedal.userfile.motec_import import ImportedLap, import_laps, import_ld_file, save_imported_lap
from tinypedal.userfile.motec_ld import Channel, LdInfo, export_lap, read_ld, write_ld
from tinypedal.userfile.telemetry_lap import LapData, lap_timestamp_of, load_lap, read_lap_info


def write_float_ld(filename: str, rate: int, channels: dict[str, list[float]], info: LdInfo | None = None):
    write_ld(filename, [Channel(name, "", "", rate, values) for name, values in channels.items()],
             info or LdInfo(venue="X"))


# --- MoTeC import: memory, lap split, distance (J6, J33, J34, J25)
def test_import_reads_used_channels_only(tmp_path, monkeypatch):
    filename = str(tmp_path / "log.ld")
    # Unused 1 Hz channel 16 hours long: never decoded, never makes the time base longer
    write_logger_ld(filename, [*logger_channels(), ("Junk", "", 1, [0.0] * 60000, 0, 1, 0)])
    _, channels = read_ld(filename, {"lap distance", "ground speed"})
    assert [channel.name for channel in channels] == ["Lap Distance", "Ground Speed"]
    assert isinstance(channels[0].values, array)  # packed, not a list of floats
    start = time.perf_counter()
    _, laps = import_laps(filename)
    assert [lap.number for lap in laps] == [11, 12, 13] and time.perf_counter() - start < 3
    monkeypatch.setattr(motec_import, "MAX_LOG_SECONDS", 26)  # time base capped: laps past it left out
    assert [lap.number for lap in import_laps(filename)[1]] == [11, 12]


def test_laps_split_on_lap_time_without_lap_number(tmp_path):
    rate, lap_seconds, length = 20, 60.0, 3000.0
    times = [index / rate for index in range(int(rate * lap_seconds * 3.5))]  # 3.5 laps from start line
    filename = str(tmp_path / "laps.ld")
    write_float_ld(filename, rate, {
        "Lap Time": [t % lap_seconds for t in times],
        "Lap Distance": [(t % lap_seconds) / lap_seconds * length for t in times],
        "Ground Speed": [180.0] * len(times),
    })
    laps = import_laps(filename)[1]  # was one lap of 210 s named after the last partial lap
    assert [lap.number for lap in laps] == [1, 2, 3]
    assert [lap.lap_time for lap in laps] == pytest.approx([60.0] * 3, abs=0.06)
    # Lap time resets only, distance an odometer (never back to 0): laps from lap time, distance from 0 each lap
    write_float_ld(filename, rate, {
        "Lap Time": [t % lap_seconds for t in times],
        "Distance": [t / lap_seconds * length for t in times],
        "Ground Speed": [180.0] * len(times),
    })
    laps = import_laps(filename)[1]
    assert len(laps) == 3 and all(lap.lap_time == pytest.approx(60.0, abs=0.06) for lap in laps)
    for lap in laps:
        distances = lap.columns["distance"]
        assert distances[0] < 10 and 2950 < max(distances) <= lap.info["track_length"] < 3010


def test_odometer_distance_rebased_per_lap(tmp_path):
    rate, lap_seconds, length = 20, 60.0, 3000.0
    times = [index / rate for index in range(int(rate * lap_seconds * 3.5))]
    filename = str(tmp_path / "odometer.ld")
    write_float_ld(filename, rate, {
        "Lap Number": [float(t // lap_seconds) for t in times],
        "Distance": [t / lap_seconds * length for t in times],  # since log start
        "Ground Speed": [180.0] * len(times),
    })
    laps = import_laps(filename)[1]
    assert [lap.number for lap in laps] == [1, 2]
    for lap in laps:  # was 3000 -> 6000 m with track length 5997
        distances = lap.columns["distance"]
        assert distances[0] == pytest.approx(0.0, abs=1) and max(distances) == pytest.approx(3000.0, abs=200)
        assert lap.info["track_length"] >= max(distances)  # rounded up: last sample never past lap end


def test_track_length_rounded_up(tmp_path):
    filename = str(tmp_path / "spa.ld")
    write_logger_ld(filename, logger_channels())
    for lap in import_laps(filename)[1]:
        assert max(lap.columns["distance"]) <= lap.info["track_length"] <= max(lap.columns["distance"]) + 0.1


# --- MoTeC lap identity & channels (J62), step channels (J47)
def recorded_lap(name: str = "2026-10-01 18-28-49 lap002 1m11.760s") -> LapData:
    count = 3589
    times = [index * 0.02 + (0.007 if index % 2 else 0.0) for index in range(count)]  # recorder timing jitter
    times[-1] = 71.76
    columns: dict = {
        "lap_time": times,
        "distance": [t * 50 for t in times],
        "speed_kph": [180.0] * count,
        "gear": [2.0 if t < 30 else 3.0 for t in times],
        "sector": [0.0 if t < 30 else 1.0 for t in times],
        "tc_active": [float(index // 7 % 2) for index in range(count)],
        "brake_bias": [56.0] * count,
        "tyre_wear_fl": [98.0 - t / 71.76 for t in times],  # remaining %
        "tyre_load_fl": [3.5] * count,  # kN
        "tyre_temp_in_fl": [90.0] * count,
        "tyre_temp_mid_fl": [85.0] * count,
        "tyre_temp_out_fl": [80.0] * count,
        "water_temp": [92.0] * count,
        "oil_temp": [105.0] * count,
        "path_lateral": [-2.5] * count,
        "track_edge": [6.0] * count,
    }
    return LapData(name, columns, {"vehicle": "Car", "track": "Monza", "driver": "Ace", "session": "Race"})


def test_export_channels_and_round_trip(tmp_path):
    lap = recorded_lap()
    filename = str(tmp_path / "lap.ld")
    export_lap(lap, filename)
    info, channels = read_ld(filename)
    values = {channel.name: channel.values for channel in channels}
    for name in ("Gear", "Sector", "TC Active"):  # held, never 2.5
        assert all(value == round(value) for value in values[name]), name
    assert info.driver == "Ace" and info.comment == lap.name
    assert abs(info.timestamp - (lap_timestamp_of(lap.name) - 71.76)) <= 1  # log date: lap start
    assert values["Brake Bias Rear"][0] == pytest.approx(44.0)
    assert values["Tyre Wear FL"][0] == pytest.approx(2.0) and values["Tyre Wear FL"][-1] > 2.5  # worn %, as LMU
    assert values["Tyre Load FL"][0] == pytest.approx(3500.0)
    assert values["Eng Water Temp"][0] == pytest.approx(92.0) and values["Track Edge"][0] == pytest.approx(6.0)

    paths = import_ld_file(filename, str(tmp_path / "imported"))
    assert [os.path.basename(path) for path in paths] == [f"{lap.name}.csv"]  # same date, lap number & lap time
    back = load_lap(paths[0])
    assert read_lap_info(paths[0])["finished"] == pytest.approx(lap_timestamp_of(lap.name))
    for column, value in (("brake_bias", 56.0), ("tyre_load_fl", 3.5), ("water_temp", 92.0), ("oil_temp", 105.0),
                          ("tyre_temp_in_fl", 90.0), ("tyre_temp_mid_fl", 85.0), ("tyre_temp_out_fl", 80.0),
                          ("path_lateral", -2.5), ("track_edge", 6.0), ("tyre_wear_fl", 98.0)):
        assert back.columns[column][0] == pytest.approx(value, abs=0.01), column
    assert set(back.columns["gear"]) == {2.0, 3.0}


def test_logger_laps_dated_from_log_header(tmp_path):
    filename = str(tmp_path / "lmu.ld")
    write_logger_ld(filename, [
        *logger_channels(),
        ("Eng Water Temp", "C", 10, [80.0] * 400, 0, 1, 1),
        ("Brake Bias Rear", "%", 10, [44.0] * 400, 0, 1, 1),
        ("Tyre Load FL", "N", 10, [3000.0] * 400, 0, 1, 0),
    ])
    folder = str(tmp_path / "imported")
    paths = import_ld_file(filename, folder)
    log_start = time.mktime(time.strptime("24/09/2026 14:05:12", "%d/%m/%Y %H:%M:%S"))
    for path, end in zip(paths, (15.0, 25.0, 35.0)):  # lap ends: line crossings 15, 25 & 35 s into log
        assert abs(lap_timestamp_of(os.path.basename(path)) - (log_start + end)) <= 1  # not file copy time
        info = read_lap_info(path)
        assert info["finished"] == pytest.approx(log_start + end, abs=0.05)
    lap = load_lap(paths[0])
    assert lap.columns["water_temp"][0] == pytest.approx(80.0) and lap.columns["brake_bias"][0] == pytest.approx(56.0)
    assert lap.columns["tyre_load_fl"][0] == pytest.approx(3.0)  # N to kN
    assert lap.columns["tyre_temp_in_fl"][0] == pytest.approx(90.0, abs=0.1)  # tread edges kept, not only average
    assert lap.columns["tyre_temp_fl"][0] == pytest.approx(80.0, abs=0.1)
    # Imported again (J32): same laps not written twice
    assert import_ld_file(filename, folder) == paths
    assert len(os.listdir(os.path.dirname(paths[0]))) == 3


def test_imported_lap_written_whole(tmp_path, monkeypatch):
    columns: dict = {"time": [0.0, 1.0], "lap_time": [0.0, 1.0], "distance": [0.0, 50.0]}
    lap = ImportedLap(1, 60.0, columns, {"source": "MoTeC"})
    folder = str(tmp_path / "log")

    def failing(source, target):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", failing)
    with pytest.raises(OSError):
        save_imported_lap(lap, folder, 1.0e9)
    monkeypatch.undo()
    assert os.listdir(folder) == []  # no partial lap file with a valid name
    assert os.path.basename(save_imported_lap(lap, folder, 1.0e9)) in os.listdir(folder)


# --- Imported laps library: delete to trash, locked file, undo, caches (J7, J63)
def test_delete_laps_to_trash_with_locked_file(tmp_path, monkeypatch):
    folder = str(tmp_path)
    paths = import_log(folder, "mate", [90.0, 91.0, 92.0])
    group = os.path.dirname(paths[0])
    with open(os.path.join(group, lap_library.FOREIGN_MARK), "w", encoding="utf-8") as file:
        json.dump({"source": "x"}, file)
    for path in paths:
        load_cached_lap(folder, path)
    trash = os.path.join(folder, ".trash", "2026-10-06 10-00-00")
    locked = paths[1]
    real_replace = os.replace

    def replace(source, target):
        if os.path.normpath(source) == locked:
            raise PermissionError(13, "file in use")
        real_replace(source, target)

    monkeypatch.setattr(lap_library, "RENAME_RETRIES", 2)
    monkeypatch.setattr(os, "replace", replace)
    first = delete_laps(folder, paths, trash)
    monkeypatch.setattr(os, "replace", real_replace)
    assert first.failed == {locked: "file in use"} and sorted(first.deleted) == sorted([paths[0], paths[2]])
    assert os.path.exists(locked) and lap_library.is_foreign(locked)  # group kept: one lap left
    assert not os.path.exists(cache_file(folder, paths[0])) and os.path.exists(cache_file(folder, locked))
    assert all(os.path.exists(target) for _, target in first.trashed)

    second = delete_laps(folder, [locked], trash)  # last lap: group removed, its foreign mark kept in trash
    assert second.deleted == [locked] and not os.path.exists(group)
    restored = restore_laps(first.trashed + second.trashed)  # undo
    assert sorted(restored) == sorted(paths) and lap_library.is_foreign(paths[0])
    assert not os.path.exists(trash)  # empty trash folders removed


def test_library_delete_undo_and_locked_file(viewer, monkeypatch):  # noqa: F811
    from tinypedal.ui import lap_library as library_page

    library = open_library(viewer)
    library.add_to_viewer([library.tree.topLevelItem(0)])
    paths = library.lap_paths([library.tree.topLevelItem(0)])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: warnings.append(args[2])))
    monkeypatch.setattr(library_page, "show_toast", lambda *args, **kwargs: None)
    monkeypatch.setattr(lap_library, "RENAME_RETRIES", 1)
    real_replace = os.replace

    def replace(source, target):
        if os.path.normpath(source) == paths[0]:
            raise PermissionError(13, "file in use")
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace)
    library.tree.topLevelItem(0).setSelected(True)
    library.delete()  # was: exception out of the slot, first files gone, viewer not told
    monkeypatch.setattr(os, "replace", real_replace)
    assert warnings and "file in use" in warnings[0]
    assert [entry.file.path for entry in viewer.backend.external] == [paths[0]]  # deleted one forgotten only
    assert library.tree.topLevelItem(0).childCount() == 1 and library.button_undo.isVisibleTo(library)
    library.undo_delete()
    assert library.tree.topLevelItem(0).childCount() == 2 and not library.button_undo.isVisibleTo(library)
    assert all(os.path.exists(path) for path in paths)
    library.close()


def test_library_import_is_page_job(viewer, monkeypatch, tmp_path):  # noqa: F811
    from tinypedal.ui import lap_library as library_page
    from tinypedal.ui.quick import lap_backend

    log = tmp_path / "Monza run.ld"
    write_logger_ld(str(log), logger_channels(), venue="Monza")
    monkeypatch.setattr(library_page.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *args, **kwargs: ([str(log)], "")))
    page = viewer.backend
    library = open_library(viewer)
    library.import_logs()
    assert page._imports == 1 and page.loading  # page close lets it finish, busy indicator shown
    assert "MoTeC import" in [handle.name for handle, *_ in page._jobs]
    assert "MoTeC import" in lap_backend.EXPORT_JOBS  # app exit waits for it
    page.wait_jobs()
    assert page._imports == 0 and library.top_items()[0].text(0) == "Monza run"
    assert not page.external  # library import: laps not added to viewer
    library.import_logs()
    library.close()
    library.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    page.wait_jobs()  # library gone before import ended: nothing to update
    assert page._imports == 0


def test_import_stopped_with_worker(backend, monkeypatch, tmp_path):  # noqa: F811
    """Worker process died with an import (never run again in page process): done gets None, told clearly"""
    jobs = []
    monkeypatch.setattr(backend, "run_process_job", lambda name, done, function, *args: jobs.append(done))
    backend.import_motec([str(tmp_path / "huge.ld")])
    assert backend._imports == 1
    jobs.pop()(None)
    assert "import stopped, file too big or unreadable" in backend.status and backend._imports == 0
    backend.import_folder(str(tmp_path))
    jobs.pop()(None)
    assert "Unable to import laps: import stopped" in backend.status and backend._imports == 0


# --- Laps of other drivers' folders (J29, J30, J31, J32)
def lap_file(folder, name: str, info: dict | None = None) -> str:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as file:
        if info is not None:
            file.write("# " + json.dumps(info) + "\n")
        file.write("time,lap_time,distance\n0,0,0\n1,1,50\n")
    return path


def test_foreign_import_skips_other_files_and_tracks(tmp_path):
    telemetry = str(tmp_path / "telemetry")
    mate = tmp_path / "Teammate"
    lap_file(mate / TRACK, "2026-01-01 10-00-00 lap001 1m30.000s.csv", lap_info())
    lap_file(mate / TRACK, "2026-01-01 10-01-30 lap002 1m29.000s.csv")  # older lap without info, this track
    lap_file(mate / "Other - GT3", "2026-01-01 11-00-00 lap001 1m40.000s.csv")  # older lap of another track
    lap_file(mate / TRACK, "notes.csv")  # not laps
    lap_file(mate, f"{TRACK}.csv")  # lap viewer CSV export
    result = import_foreign_job(telemetry, str(mate), lap_info(), "GT3")
    names = sorted(os.path.basename(path) for path in result["paths"])
    assert names == ["2026-01-01 10-00-00 lap001 1m30.000s.csv", "2026-01-01 10-01-30 lap002 1m29.000s.csv"]
    assert result["file"] == 2 and result["circuit"] == 1 and not result["error"]

    again = import_foreign_job(telemetry, str(mate), lap_info(), "GT3")  # same group, nothing copied twice
    assert sorted(again["paths"]) == sorted(result["paths"]) and again["present"] == 2
    assert [name for name, _ in list_imported(telemetry)] == ["Teammate"]
    lap_library.rename_group(telemetry, "Teammate", "Max laps")
    lap_file(mate / TRACK, "2026-01-02 10-00-00 lap003 1m28.000s.csv", lap_info())
    third = import_foreign_job(telemetry, str(mate), lap_info(), "GT3")  # renamed group still used
    assert third["present"] == 2 and len(third["paths"]) == 3
    groups = list_imported(telemetry)
    assert [name for name, _ in groups] == ["Max laps"] and len(groups[0][1]) == 3


def test_foreign_import_own_folder_guard(tmp_path):
    telemetry = tmp_path / "telemetry"
    own = lap_file(telemetry / TRACK, "2026-01-01 10-00-00 lap001 1m30.000s.csv", lap_info())
    lap_file(tmp_path / "telemetry_mate" / TRACK, "2026-01-02 10-00-00 lap001 1m31.000s.csv", lap_info())
    sibling = import_foreign_job(str(telemetry), str(tmp_path / "telemetry_mate"), lap_info(), "GT3")
    assert not sibling["error"] and len(sibling["paths"]) == 1  # was refused as own folder (name prefix)
    parent = import_foreign_job(str(telemetry), str(tmp_path), lap_info(), "GT3")
    assert os.path.basename(own) not in [os.path.basename(path) for path in parent["paths"]]  # own laps skipped
    inside = import_foreign_job(str(telemetry), str(telemetry / TRACK), lap_info(), "GT3")
    assert inside["error"] == "own telemetry folder"


def test_foreign_import_current_track_first(tmp_path, monkeypatch):
    mate = tmp_path / "mate"
    for track in range(3):  # other track folders, listed before current one
        for number in range(5):
            lap_file(mate / f"Algarve {track} - GT3", f"2026-01-01 10-00-0{number} lap00{number} 1m40.000s.csv",
                     lap_info(track="Algarve", combo="Algarve", track_length=4600.0))
    for number in range(3):
        lap_file(mate / TRACK, f"2026-01-02 10-00-0{number} lap00{number} 1m30.000s.csv", lap_info())
    monkeypatch.setattr(lap_library, "FOREIGN_MAX_FILES", 10)
    result = import_foreign_job(str(tmp_path / "telemetry"), str(mate), lap_info(), "GT3")
    assert len(result["paths"]) == 3  # was: files of other tracks filled the limit first
    monkeypatch.setattr(lap_library, "FOREIGN_MAX_LAPS", 2)  # limit counts laps matching current track & class
    result = import_foreign_job(str(tmp_path / "telemetry2"), str(mate), lap_info(), "GT3")
    assert len(result["paths"]) == 2


# --- Delta best (J35, J67, J36)
def test_added_lap_as_delta_best(backend, tmp_path, monkeypatch):  # noqa: F811
    from tinypedal.setting import cfg

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    mate = tmp_path / "Teammate"
    write_lap(str(mate), 7, 88.5, info=lap_info(combo=TRACK))
    backend.import_folder(str(mate), background=False)
    foreign = next(entry.file.path for entry in backend.external)
    backend.exportDeltaBest(foreign)  # teammate lap of this track & class as delta target
    target = os.path.join(cfg.path.delta_best, f"{TRACK}.csv")
    assert os.path.exists(target) and "1:28.500" in backend.status

    other = import_log(backend.folder, "Monza log", [100.0], track="Monza")
    backend.add_external(other)
    backend.exportDeltaBest(other[0])  # was: nothing done, nothing told
    assert "another track" in backend.status
    backend.reference_key = ""
    backend.exportDeltaBest("")
    assert "Check laps" in backend.status


def test_delta_best_backups_kept(tmp_path):
    from tinypedal.ui.quick.lap_export import DELTA_BEST_BACKUPS, backup_delta_best

    target = tmp_path / "Track - GT3.csv"
    target.write_text("driven", encoding="utf-8")
    backup_delta_best(str(target))
    target.write_text("lap A", encoding="utf-8")
    for index in range(DELTA_BEST_BACKUPS + 2):  # older dated backups
        (tmp_path / f"Track - GT3.csv.2026010{index}-120000.bak").write_text("old", encoding="utf-8")
    backup_delta_best(str(target))
    assert (tmp_path / "Track - GT3.csv.bak").read_text(encoding="utf-8") == "driven"  # never overwritten
    dated = sorted(name for name in os.listdir(tmp_path) if name.count(".") == 3)
    assert len(dated) == DELTA_BEST_BACKUPS and (tmp_path / dated[-1]).read_text(encoding="utf-8") == "lap A"


# --- Replay link (J48)
def test_replay_link_of_imported_and_interrupted(backend, tmp_path, monkeypatch):  # noqa: F811
    from tinypedal import replay
    from tinypedal.replay import ReplayInfo
    from tinypedal.ui.lap_viewer import PlotLap

    times = [index * 0.5 for index in range(181)]
    columns: dict = {"lap_time": times, "distance": [t * 30 for t in times]}
    end = 1_800_000_090.0
    name = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(end)) + " lap001 1m30.000s.csv"
    created = end - 200
    interrupted = tmp_path / "cut.tpreplay"
    interrupted.write_bytes(b"x")
    os.utime(interrupted, (created + 50, created + 50))  # recording stopped before the lap
    replays = [ReplayInfo(str(interrupted), created, 0, -1.0, "LMU", {})]
    monkeypatch.setattr(replay, "list_replays", lambda folder: replays)

    def target(meta: dict):
        lap = PlotLap(str(tmp_path / name), "lap", LapData(name, columns, meta), QColor("red"))
        backend.data.set_laps([lap])
        return backend.replay_target(lap, 0.0)

    assert target({}) is None  # interrupted replay no longer assumed 24 h long
    os.utime(interrupted, (end + 10, end + 10))
    assert target({})[1] == pytest.approx(200 - 90 + 0.5)  # file name date: middle of its second
    assert target({"source": "MoTeC"}) is None  # imported lap named at import time: no link
    assert target({"source": "MoTeC", "finished": end - 20})[1] == pytest.approx(200 - 90 - 20)
