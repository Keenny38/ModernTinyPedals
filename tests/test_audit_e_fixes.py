"""Regression tests: delta set validation, position interpolation, notes parsing, brake wear, atomic writes"""

import gzip
import os
import threading

import pytest

from tinypedal.module import module_recorder
from tinypedal.process.vehicle import export_wheels
from tinypedal.userfile import atomic_write, temp_file_name, track_notes, write_text_file
from tinypedal.validator import valid_delta_set, vehicle_position_interp

WHEELS_NA = (-1.0, -1.0, -1.0, -1.0)


# --- Delta set
@pytest.mark.parametrize("lines", (10, 11, 12, 13, 40))
def test_delta_set_minimum_lines_accepted(lines):
    data = tuple((float(index), float(index) * 0.5) for index in range(lines))
    assert valid_delta_set(data) == data


@pytest.mark.parametrize("lines", (0, 1, 2, 9))
def test_delta_set_too_short_rejected(lines):
    data = tuple((float(index), float(index)) for index in range(lines))
    with pytest.raises(ValueError):
        valid_delta_set(data)


def test_delta_set_first_rows_distance_decreasing_rejected():
    data = [(float(index), float(index)) for index in range(20)]
    data[5] = (100.0, 5.0)
    with pytest.raises(ValueError):
        valid_delta_set(tuple(data))


# --- Position interpolation
def test_position_interp_unchanged_distance_on_first_send():
    gen = vehicle_position_interp()
    assert gen.send((1.0, 0.0)) == 0.0  # distance unchanged: no UnboundLocalError
    assert gen.send((2.0, 10.0)) == 0.0
    assert gen.send((3.0, 20.0)) == 0.0
    assert gen.send((3.5, 20.0)) == pytest.approx(25.0)  # still running


# --- Notes
def test_notes_non_finite_distance_rejected():
    for value in ("nan", "inf", "-inf", "x", ""):
        assert not track_notes.verify_notes({"distance": value}, "distance")
    line = {"distance": "12.5"}
    assert track_notes.verify_notes(line, "distance") and line["distance"] == 12.5


def test_gpl_notes_metadata_prefix_removed_not_char_set():
    lines = (
        ";AUTHOR:Rob\n",
        ";TITLE: Monza\n",
        "left.mp3,nan\n",
        "right.mp3,100.0\n",
    )
    notes, meta = track_notes.parse_gpl_notes(lines, ("distance", "pace_note", "comment"))
    assert meta["AUTHOR"] == "Rob"
    assert meta["TITLE"] == "Monza"
    assert [note["distance"] for note in notes] == [100.0]  # nan line left out


# --- Brake wear from REST
@pytest.mark.parametrize("data", (
    None, [], [1.0, 2.0], [None, 1.0, 1.0, 1.0], ["a", 1.0, 1.0, 1.0], [float("nan"), 1.0, 1.0, 1.0],
    {"a": 1}, "abcd",
))
def test_export_wheels_invalid_default(data):
    assert export_wheels(data, WHEELS_NA) == WHEELS_NA


def test_export_wheels_converted_to_float():
    assert export_wheels([1, "2", 3.5, 4, 5], WHEELS_NA) == (1.0, 2.0, 3.5, 4.0)


# --- Atomic writes
def test_temp_file_name_unique_per_thread():
    names = [temp_file_name("data.json")]
    thread = threading.Thread(target=lambda: names.append(temp_file_name("data.json")))
    thread.start()
    thread.join()
    assert names[0] != names[1]
    assert all(name.startswith("data.json.") and name.endswith(".tmp") for name in names)
    assert str(os.getpid()) in names[0]


def test_concurrent_writers_same_target(tmp_path):
    target = str(tmp_path / "laps.consumption")
    results = []

    def writer(text):
        for _ in range(30):
            results.append(write_text_file(target, text))

    threads = [threading.Thread(target=writer, args=(char * 1000,)) for char in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Windows may refuse a replace while the other thread replaces (logged), never mixed content
    assert any(results)
    assert (tmp_path / "laps.consumption").read_text(encoding="utf-8") in ("a" * 1000, "b" * 1000)
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_leaves_no_temp_file(tmp_path):
    target = tmp_path / "data.csv"
    with atomic_write(str(target)) as file:
        file.write("a")
    assert target.read_text(encoding="utf-8") == "a"
    assert not list(tmp_path.glob("*.tmp"))


def test_write_gzip_file_flushed_to_disk(tmp_path, monkeypatch):
    flushed = []
    monkeypatch.setattr(module_recorder, "flush_to_disk", lambda file: flushed.append(file.name))
    target = str(tmp_path / "lap.csv.gz")
    assert module_recorder.write_gzip_file(target, "a,b\n1,2\n")
    with gzip.open(target, "rt", encoding="utf-8") as file:
        assert file.read() == "a,b\n1,2\n"
    assert len(flushed) == 1 and flushed[0].endswith(".tmp")
    assert not list(tmp_path.glob("*.tmp"))


def test_write_gzip_file_error_removes_temp(tmp_path):
    assert not module_recorder.write_gzip_file(str(tmp_path / "missing" / "lap.csv.gz"), "a")
    assert not list(tmp_path.rglob("*.tmp"))
