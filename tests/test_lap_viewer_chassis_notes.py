"""Lap viewer: pedals after driving aids, aero & chassis channels, bottoming marks, columns read from cache when used,
track notes shared with Track Notes overlay, 100 Hz recording option"""

import os
import pickle

import pytest

from neopedal.module import module_recorder
from neopedal.setting import cfg
from neopedal.ui.lap_viewer import CHANNEL_MAP, PlotLap
from neopedal.userfile import lap_cache
from neopedal.userfile.telemetry_lap import LapData
from tests.test_lap_viewer import flush_deleted, wait_loaded
from tests.test_lap_viewer_features import BASE, TRACK, lap_rows


def lap(**columns) -> LapData:
    count = len(next(iter(columns.values())))
    base = {"distance": [index * 10.0 for index in range(count)], "lap_time": [index * 0.1 for index in range(count)],
            "speed_kph": [150.0] * count}
    return LapData("lap", {**base, **columns})


def computed(column: str, data: LapData):
    from neopedal.ui.quick.trace_data import TraceData

    trace = TraceData.__new__(TraceData)  # computed() reads only the lap & placements
    trace.placements = {}
    from PySide6.QtGui import QColor

    return trace.computed(CHANNEL_MAP[column], PlotLap("key", "Lap", data, QColor("red")))


def test_recorded_sample_matches_header(ui_env):
    assert len(module_recorder.read_sample(0.0)) == len(module_recorder.CSV_HEADER)
    header = module_recorder.CSV_HEADER
    assert header[-8:] == ("throttle_car", "brake_car", "downforce_front", "downforce_rear",
                           "camber_fl", "camber_fr", "camber_rl", "camber_rr")
    assert header.index("fuel") == 10  # lap info reads fuel at its place: added columns only at the end


def test_driving_aid_aero_and_chassis_channels():
    data = lap(throttle=[1.0, 1.0, 0.2, 0.0], throttle_car=[1.0, 0.6, 0.4, 0.0], brake=[0.0] * 4, brake_car=[0.0] * 4,
               downforce_front=[0.1, 2.0, 3.0, 1.0], downforce_rear=[0.1, 2.0, 1.0, 3.0],
               ride_height_fl=[20.0] * 4, ride_height_fr=[22.0] * 4, ride_height_rl=[40.0] * 4,
               ride_height_rr=[42.0] * 4, susp_defl_fl=[10.0, 11.0, 12.0, 12.0])
    assert computed("throttle_cut", data)[1] == pytest.approx([0.0, 0.4, -0.2, 0.0])  # TC cut, blip below 0
    distances, balance = computed("aero_balance", data)
    assert distances == [10.0, 20.0, 30.0] and balance == pytest.approx([50.0, 75.0, 25.0])  # slow sample left out
    assert computed("rake", data)[1] == pytest.approx([20.0] * 4)
    assert computed("damper_vel_fl", data)[1] == pytest.approx([10.0, 10.0, 5.0, 0.0])  # mm per second
    assert CHANNEL_MAP["all:throttle_aid"].parts == ("throttle", "throttle_car")
    assert CHANNEL_MAP["damper_vel_fl"].quantity == "length" and CHANNEL_MAP["damper_vel_fl"].noisy


def test_bottoming_marks():
    from neopedal.ui.quick import lap_map

    count = 40
    heights = [30.0] * count
    heights[10:13] = [0.5, -1.0, 0.8]  # one episode
    heights[30] = 0.0
    data = lap(ride_height_fl=[30.0] * count, ride_height_fr=heights, ride_height_rl=[40.0] * count,
               ride_height_rr=[40.0] * count)
    assert lap_map.slip_events(data) == [(100.0, "bottom"), (300.0, "bottom")]
    zeros = lap(ride_height_fl=[0.0] * count, ride_height_fr=[0.0] * count, ride_height_rl=[0.0] * count,
                ride_height_rr=[0.0] * count)
    assert lap_map.slip_events(zeros) == []  # ride height not recorded


def test_columns_read_from_cache_when_used(tmp_path):
    folder = str(tmp_path)
    module_recorder.save_lap(f"{folder}/", TRACK, 2, 70.0, lap_rows(70.0), max_saved_laps=99, valid=True,
                             info={"track": "Atlanta"}, timestamp=BASE)
    path = os.path.join(folder, TRACK, module_recorder.lap_filename(2, 70.0, True, BASE))
    target = lap_cache.cache_file(folder, path)
    os.remove(target)  # cached by recorder: made again from CSV
    first = lap_cache.load_cached_lap(folder, path)
    assert isinstance(first.columns, lap_cache.CachedColumns) and os.path.exists(target)
    loaded = lap_cache.load_cached_lap(folder, path)
    columns = loaded.columns
    assert "tyre_temp_fl" in columns and "tyre_temp_fl" not in columns._loaded
    assert "distance" in columns._loaded
    assert list(columns["tyre_temp_fl"])[:2] == [80.0, 80.0]
    assert {"tyre_temp_fr", "tyre_temp_rl", "tyre_temp_rr"} <= set(columns._loaded)
    assert "missing" not in columns and columns.get("missing") is None
    with pytest.raises(KeyError):
        columns["missing"]
    assert len(columns) == len(module_recorder.CSV_HEADER) and list(columns) == list(module_recorder.CSV_HEADER)

    # Worker process: pickled with columns read so far, others read from file there
    copy = pickle.loads(pickle.dumps(loaded))
    assert list(copy.columns["tyre_pres_fl"]) == list(columns["tyre_pres_fl"])

    # Cache file gone (pruned): read from lap file
    other = lap_cache.load_cached_lap(folder, path)
    os.remove(target)
    assert list(other.columns["rpm"]) == list(columns["rpm"])
    assert len(other.columns["brake_temp_fl"]) == len(columns["distance"])


@pytest.fixture
def noted_viewer(ui_env, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    folder = cfg.path.telemetry.rstrip("/")
    for number, lap_time in ((1, 70.0), (2, 71.0)):
        module_recorder.save_lap(f"{folder}/", TRACK, number, lap_time, lap_rows(lap_time), max_saved_laps=99,
                                 valid=True, info={"kind": "lap", "track": "Atlanta"}, timestamp=BASE + number * 100)
    notes = os.path.join(cfg.path.track_notes, "Atlanta.tptn")
    with open(notes, "w", encoding="utf-8", newline="") as file:
        file.write("NEOPEDAL TRACK NOTES FILE VERSION,2\r\n\r\nTITLE,Atlanta\r\nAUTHOR,me\r\n\r\n"
                   "distance,track note,comment,tags\r\n300,Brake at board,,\r\n50,Pit exit,,#pit\r\n")
    from neopedal.ui.lap_viewer import LapViewer

    dialog = LapViewer(None)
    dialog.resize(1300, 800)
    wait_loaded(dialog)
    yield dialog, notes
    dialog.close()
    flush_deleted()


def test_track_notes_shared_with_overlay(noted_viewer, monkeypatch):
    dialog, path = noted_viewer
    notes = dialog.backend.trackNotes
    assert notes.available
    items = notes.items
    assert [(item["text"], item["distance"]) for item in items] == [("Brake at board", 300.0)]  # pit note left out
    assert "mapX" in items[0] and items[0]["x"] == pytest.approx(dialog.backend.xAtDistance(300.0))

    asked = []
    monkeypatch.setattr(notes, "ask", lambda label, text, saving: asked.append((label, text, saving)))
    notes.addAt(dialog.backend.xAtDistance(600.0))
    assert asked[-1][2]("  Turn   in  late ")
    assert [item["text"] for item in notes.items] == ["Brake at board", "Turn in late"]
    index = notes.items[0]["index"]
    notes.edit(index)
    assert asked[-1][1] == "Brake at board" and asked[-1][2]("Brake at 150")
    notes.remove(notes.items[1]["index"])
    assert [item["text"] for item in notes.items] == ["Brake at 150"]

    from neopedal.userfile.track_notes import HEADER_TRACK_NOTES, load_notes_file, parse_csv_notes

    saved, metadata = load_notes_file(cfg.path.track_notes, "Atlanta", HEADER_TRACK_NOTES, parse_csv_notes, ".tptn")
    assert [(note["distance"], note["track note"], note["tags"]) for note in saved] == [
        (50.0, "Pit exit", "#pit"), (300.0, "Brake at 150", "")]  # pit note & metadata kept
    assert metadata["AUTHOR"] == "me"

    # Edited by another editor: read again when laps change
    with open(path, "a", encoding="utf-8", newline="") as file:
        file.write("900,Kerb,,\r\n")
    os.utime(path, (os.path.getmtime(path) + 5,) * 2)
    notes.refresh()
    assert [item["text"] for item in notes.items] == ["Brake at 150", "Kerb"]


def test_100hz_recording_option(ui_env):
    from neopedal.module.module_recorder import Realtime

    cfg.user.setting["module_recorder"]["enable_100hz_lap_recording"] = False
    assert Realtime(cfg, "module_recorder").active_interval == pytest.approx(0.02)
    cfg.user.setting["module_recorder"]["enable_100hz_lap_recording"] = True
    assert Realtime(cfg, "module_recorder").active_interval == pytest.approx(0.01)


def saved_lap(folder: str, number: int = 2, lap_time: float = 70.0, info: dict | None = None) -> str:
    module_recorder.save_lap(f"{folder}/", TRACK, number, lap_time, lap_rows(lap_time), max_saved_laps=99, valid=True,
                             info=info or {"track": "Atlanta", "vehicle": "Porsche 963"}, timestamp=BASE + number)
    return os.path.join(folder, TRACK, module_recorder.lap_filename(number, lap_time, True, BASE + number))


def test_shared_lap_file(tmp_path, monkeypatch):
    from neopedal.ui.quick import lap_export
    from neopedal.userfile.telemetry_lap import load_lap, share_lap_job

    path = saved_lap(str(tmp_path / "mine"))
    monkeypatch.setattr(lap_export, "driver_name", lambda: "Steven")
    assert lap_export.shared_lap_name(path) == "Atlanta - Porsche 963 - Steven 1m10.000s.csv.gz"
    target = str(tmp_path / lap_export.shared_lap_name(path))
    assert share_lap_job(path, target, "Steven") == "" and not os.path.exists(f"{target}.tmp")
    shared, original = load_lap(target), load_lap(path)
    assert shared.info == {**original.info, "shared_by": "Steven"}
    assert {name: list(values) for name, values in shared.columns.items()} == \
        {name: list(values) for name, values in original.columns.items()}
    assert share_lap_job(str(tmp_path / "missing.csv"), str(tmp_path / "x.csv.gz")) != ""

    from neopedal.ui.lap_viewer import LapEntry
    from neopedal.ui.quick.lap_library import LapLibrary
    from neopedal.userfile.telemetry_lap import LapFile

    entry = LapEntry(LapFile(os.path.basename(target), target, True, 70.0), shared.info, external=True)
    assert "shared by Steven" in LapLibrary.entry_text(entry)


def test_passage_motec_export(tmp_path):
    from neopedal.userfile.motec_ld import export_lap_job, read_ld
    from neopedal.userfile.telemetry_lap import lap_part, load_lap

    path = saved_lap(str(tmp_path))
    lap = load_lap(path)
    part = lap_part(lap, 500.0, 1500.0)
    assert part.distance[0] >= 500.0 and part.distance[-1] <= 1500.0 and len(part) < len(lap)
    assert lap_part(lap, 5000.0, 6000.0) is lap  # nothing in range: whole lap
    target = str(tmp_path / "part.ld")
    assert export_lap_job(str(tmp_path), path, target, "Atlanta", (500.0, 1500.0)) == ""
    info, channels = read_ld(target)
    distances = next(channel for channel in channels if channel.name == "Lap Distance").values
    assert min(distances) >= 499.0 and max(distances) <= 1501.0 and info.comment.endswith("500-1500 m")


def test_session_corner_values(ui_env, tmp_path):
    from neopedal.ui.quick.lap_session import SessionTab, is_best, value_range
    from neopedal.userfile.corner_analysis import find_corners
    from neopedal.userfile.lap_geometry import session_values
    from neopedal.userfile.telemetry_lap import load_lap

    paths = [saved_lap(str(tmp_path), number, lap_time) for number, lap_time in ((1, 70.0), (2, 72.0))]
    corners = [(corner.number, corner.start, corner.apex, corner.end) for corner in find_corners(load_lap(paths[0]))]
    assert corners
    found = session_values(str(tmp_path), [(path, 1.0) for path in paths], corners)
    values = found[paths[0]][1]["corners"][str(corners[0][0])]
    assert len(values) == 3 and values[0] > 0 and values[2] > 0  # minimum speed, braking point, corner time
    assert "corners" not in session_values(str(tmp_path), [(paths[0], 1.0)])[paths[0]][1]  # no corner asked

    assert is_best(250.0, 250.0, True) and not is_best(249.0, 250.0, True) and is_best(70.0, 70.0)
    assert value_range([100.0, 100.5], 2.0) == pytest.approx([99.09, 101.41])  # 2 km/h at least, 8% margin
    assert SessionTab.metric_info("min:3")["higherBetter"] and SessionTab.metric_info("s2")["time"]
    assert SessionTab.metric_info("corner:3")["time"] and not SessionTab.metric_info("brake:3")["time"]
    rows = [{"valid": True, "time": 100.0 + index, "number": index + 1} for index in range(5)]
    trend = SessionTab.value_trend(rows)
    assert trend["slope"] == pytest.approx(1.0) and not any(row["outlier"] for row in rows)


def test_session_tab_value_choice(noted_viewer):
    dialog, _ = noted_viewer
    backend = dialog.backend
    session = backend.session
    keys = [item["key"] for item in session.metrics]
    assert keys[:4] == ["time", "s1", "s2", "s3"]
    corner = next(key for key in keys if key.startswith("min:"))
    backend.setSideTab(4)
    session.setMetric(corner)
    backend.wait_jobs()
    data = session.session_data()
    assert data["metric"]["higherBetter"] and data["best"] == max(row["time"] for row in data["laps"])
    assert all(row["text"].endswith("km/h") and row["lapText"] for row in data["laps"])
    session.setMetric("gone:9")  # corner of another reference lap: lap times
    assert session.metric == "time"
