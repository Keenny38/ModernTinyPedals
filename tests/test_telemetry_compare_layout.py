"""Telemetry comparison overlay: reference lap only from laps recorded on current track layout (game track length),
several layouts sharing a track name never mixed, no reference lap rather than a lap of another layout"""

import json
import os

from tests.test_telemetry_compare import (  # noqa: F401  (fixtures)
    LENGTH,
    TRACK,
    drive,
    driving,
    laps,
    loading_thread,
    write_lap,
)
from tinypedal.userfile.reference_trace import ReferenceLoader, reference_file
from tinypedal.userfile.telemetry_lap import VIEWER_SETTING

OTHER_LENGTH = 1150.0  # another layout of the same track name


def write_layout_lap(folder, stamp: str, lap_time: float, length: float, valid: bool = True) -> str:
    """Recorded lap of the layout of track length"""
    name = write_lap(folder, stamp, lap_time, valid)
    path = os.path.join(folder, name)
    with open(path, encoding="utf-8") as file:
        lines = file.read().splitlines()
    lines[0] = "# " + json.dumps({"track": "Track", "combo": TRACK, "track_length": length})
    with open(path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return name


def test_reference_lap_of_current_layout(laps):  # noqa: F811
    root, best, newest = laps
    folder = root / TRACK
    faster = write_layout_lap(folder, "10-03-00", 45.0, OTHER_LENGTH)  # fastest lap, on another layout
    latest = write_layout_lap(folder, "10-09-00", 47.0, OTHER_LENGTH)  # newest lap, on another layout
    root = str(root)
    assert reference_file(root, TRACK, "Best", LENGTH).filename == best
    assert reference_file(root, TRACK, "Last", LENGTH).filename == newest
    assert reference_file(root, TRACK, "Best", OTHER_LENGTH).filename == faster
    assert reference_file(root, TRACK, "Last", LENGTH * 1.005).filename == newest  # same tolerance as viewer
    assert reference_file(root, TRACK, "Best", 0.0).filename == faster  # length unknown: any lap
    selections = {"selections": {TRACK: {"reference": latest}}}  # viewer reference of another layout: not used
    with open(os.path.join(root, VIEWER_SETTING), "w", encoding="utf-8") as file:
        json.dump(selections, file)
    assert reference_file(root, TRACK, "Viewer", LENGTH).filename == best
    assert reference_file(root, TRACK, "Best", 3000.0) is None  # no lap of this layout: no reference
    assert reference_file(root, TRACK, "Last", 3000.0) is None


def test_lap_without_lap_info_kept(tmp_path):
    """Older lap without lap info: layout unknown, still used"""
    folder = tmp_path / TRACK
    name = write_lap(folder, "10-00-00", 50.0)
    path = folder / name
    path.write_text("\n".join(path.read_text(encoding="utf-8").splitlines()[1:]) + "\n", encoding="utf-8")
    assert reference_file(str(tmp_path), TRACK, "Best", 3000.0).filename == name


def test_loader_drops_reference_of_other_layout(laps):  # noqa: F811
    root, _, _ = laps
    loader = ReferenceLoader(str(root), "Best", 2.0)
    loader.poll(TRACK, 0.0, LENGTH)
    loader._job.result(timeout=10)
    loader.poll(TRACK, 0.0, LENGTH)
    assert loader.trace is not None and loader.trace.length == LENGTH
    assert not loader.poll(TRACK, 1.0, LENGTH * 1.002)  # same layout (rounding): kept, no check before due
    assert loader.poll(TRACK, 1.0, 3000.0) and loader.trace is None  # game on another layout: dropped at once
    loader._job.result(timeout=10)
    loader.poll(TRACK, 1.0, 3000.0)
    assert loader.trace is None  # no lap of this layout


def test_widget_without_lap_of_current_layout(driving, monkeypatch):  # noqa: F811
    from tests.test_race_aid_widgets import make, set_reader

    set_reader(monkeypatch, "lap", "track_length", 3000.0)  # same track name, longer layout
    widget = make("telemetry_compare", True)
    widget.timerEvent(None)  # reference check started with game track length
    assert widget.loader.track_length == 3000.0 and widget.loader._job is not None
    widget.loader._job.result(timeout=10)
    drive(widget, driving, 100.0, 200.0)
    assert widget.loader.track_length == 3000.0 and widget.reference is None and widget.reference_text() == "No reference lap"
