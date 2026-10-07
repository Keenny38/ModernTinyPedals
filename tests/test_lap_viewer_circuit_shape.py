"""Lap viewer: imported lap (MoTeC) of another circuit or layout about as long as laps of shown track refused from its
telemetry (driven line laid over reference line whatever the logger coordinates, else speed trace with track names
only helping), laps of the same circuit kept; consistency map aligns imported laps read in worker process like shown
laps"""

import json
import math
import os

import pytest

from tests.telemetry_sim import circuit_lap
from tinypedal.setting import cfg
from tinypedal.userfile.circuit_match import names_match, same_imported_circuit, same_shape
from tinypedal.userfile.telemetry_lap import LapData

LENGTH = 3000.0
COMBO = "Spa - GT3"
RECORDED = {"kind": "lap", "combo": COMBO, "track": "Circuit de Spa-Francorchamps", "track_length": LENGTH}
# Turns (lap share, angle, length share) of shown circuit, another circuit, another layout of the same venue
SPA = ((0.1, 90, 0.02), (0.3, 90, 0.03), (0.55, -45, 0.02), (0.6, 45, 0.02), (0.8, 180, 0.05))
OTHER = ((0.2, 120, 0.03), (0.45, 60, 0.02), (0.7, 90, 0.04), (0.9, 90, 0.02))
LAYOUT = ((0.1, 90, 0.02), (0.3, 90, 0.03), (0.40, -90, 0.01), (0.43, 90, 0.01), (0.46, 90, 0.01),
          (0.49, -90, 0.01), (0.55, -45, 0.02), (0.6, 45, 0.02), (0.8, 180, 0.05))
OTHER_CORNERS = ((0.2, 0.03, 40.0), (0.5, 0.02, 30.0), (0.75, 0.04, 45.0))  # braking zones of another circuit


def lap_name(number: int, lap_time: float) -> str:
    minutes, seconds = divmod(lap_time, 60)
    return f"2026-10-06 12-{number:02d}-00 lap{number:03d} {int(minutes)}m{seconds:06.3f}s"


def make_lap(number: int, turns=SPA, shift: float = 0.0, pace: float = 1.0, recorded: bool = False,
             turn: float = 0.0, mirrored: bool = False, scale: float = 1.0, positions: bool = True,
             corners=(), venue: str = "Spa") -> LapData:
    """Lap of circuit (turns), imported (driven distance, logger coordinates turned, moved, mirrored) or recorded"""
    columns, lap_time = circuit_lap(LENGTH, shift, pace, positions=positions, turns=turns, corners=corners)
    columns["distance"] = [value * scale for value in columns["distance"]]
    if positions:
        rotation = complex(math.cos(turn), math.sin(turn))
        points = [complex(x, z) for x, z in zip(columns["pos_x"], columns["pos_z"])]
        points = [(point.conjugate() if mirrored else point) * rotation + complex(800.0, -350.0) * bool(turn)
                  for point in points]
        columns["pos_x"] = [point.real for point in points]
        columns["pos_z"] = [point.imag for point in points]
    if recorded:
        info = dict(RECORDED)
    else:
        info = {"kind": "lap", "source": "MoTeC", "imported_from": "log.ld", "track": venue,
                "track_length": math.ceil(round(max(columns["distance"]) * 10, 6)) / 10}
    return LapData(lap_name(number, lap_time), columns, info)


def write_lap(folder: str, lap: LapData) -> str:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{lap.name}.csv")
    names = list(lap.columns)
    lines = [f"# {json.dumps(lap.info)}", ",".join(names)]
    lines += [",".join(f"{lap.columns[name][index]:.4f}" for name in names) for index in range(len(lap))]
    with open(path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return os.path.normpath(path)


# Names: only confident answers
@pytest.mark.parametrize(("first", "second", "expected"), [
    ("Circuit de Spa-Francorchamps", "spa francorchamps", True),
    ("Autódromo José Carlos Pace", "autodromo jose carlos pace", True),
    ("Spa", "Spa-Francorchamps", None),  # abbreviated: unsure
    ("Silverstone GP", "Silverstone National", None),  # layouts of a venue: unsure
    ("Circuit de la Sarthe", "Le Mans", False),  # names differ (never deciding alone)
    ("Monza", "Imola", False),
    ("", "Monza", None),
])
def test_names_match(first, second, expected):
    assert names_match(first, second) is expected


# Driven line
@pytest.mark.parametrize("variant", ["same", "turned", "mirrored", "longer"])
def test_same_circuit_line_kept(variant):
    """Same circuit in other logger coordinates (turned, moved, mirrored), driven distance longer, other pace &
    distance zero away from the line"""
    reference = make_lap(1, recorded=True)
    options = {"same": {"shift": 120.0, "pace": 1.03}, "turned": {"shift": -80.0, "turn": 2.1},
               "mirrored": {"shift": 40.0, "turn": 0.7, "mirrored": True}, "longer": {"scale": 1.05}}[variant]
    imported = make_lap(2, **options)
    assert same_shape(reference, imported) is True
    assert same_imported_circuit(reference, imported) is True


@pytest.mark.parametrize("turns", [OTHER, LAYOUT], ids=["other circuit", "other layout"])
def test_other_circuit_line_refused(turns):
    reference = make_lap(1, recorded=True)
    for options in ({}, {"turn": 1.3, "shift": 90.0}):
        imported = make_lap(2, turns, venue="Spa", **options)  # venue name alike: telemetry decides
        assert same_shape(reference, imported) is False
        assert same_imported_circuit(reference, imported) is False


def test_short_off_track_excursion_kept():
    """Lap of the same circuit with a short trip off the line (gravel): still the same circuit"""
    reference = make_lap(1, recorded=True)
    imported = make_lap(2, shift=30.0)
    xs, zs, distances = imported.columns["pos_x"], imported.columns["pos_z"], imported.distance
    columns = dict(imported.columns)
    columns["pos_x"] = [x + (40.0 if 1500 < distance < 1560 else 0.0) for x, distance in zip(xs, distances)]
    columns["pos_z"] = list(zs)
    assert same_shape(reference, LapData(imported.name, columns, imported.info)) is True


# Without positions: speed trace & names
def test_speed_trace_fallback_without_positions():
    reference = make_lap(1, recorded=True, positions=False)
    same = make_lap(2, shift=60.0, pace=1.04, positions=False, venue="Le Mans")  # names differ: speed decides
    assert same_imported_circuit(reference, same) is True
    other = make_lap(3, OTHER, positions=False, corners=OTHER_CORNERS)
    assert same_imported_circuit(reference, other) is not True  # speed alone unsure: lap kept unless names differ
    assert same_imported_circuit(reference, make_lap(4, OTHER, positions=False, corners=OTHER_CORNERS,
                                                     venue="Monza")) is False
    assert same_imported_circuit(reference, make_lap(5, OTHER, positions=False, corners=OTHER_CORNERS,
                                                     venue="Spa-Francorchamps")) is None  # names match: kept
    flat = make_lap(6, positions=False)
    flat.columns["speed_kph"] = [150.0] * len(flat)  # no speed trace to compare: names never decide alone
    assert same_imported_circuit(reference, LapData(flat.name, flat.columns,
                                                    {**flat.info, "track": "Monza"})) is None
    recorded = make_lap(7, OTHER, recorded=True, positions=False, corners=OTHER_CORNERS)
    assert same_imported_circuit(reference, recorded) is None  # laps of the app: game names & lengths decide


# Lap viewer
@pytest.fixture
def track(ui_env):
    from PySide6.QtWidgets import QWidget

    from tests.test_lap_viewer import wait_loaded
    from tinypedal.ui.quick.lap_backend import LapViewerBackend

    folder = os.path.join(cfg.path.telemetry.rstrip("/"), COMBO)
    paths = [write_lap(folder, make_lap(number, recorded=True, pace=1 + number / 100)) for number in (1, 2)]
    parent = QWidget()
    backend = LapViewerBackend(parent, cfg.path.telemetry)
    backend.refresh()
    wait_loaded(backend)
    yield backend, paths
    backend.release()
    parent.deleteLater()


def test_imported_lap_of_other_circuit_refused(track, tmp_path):
    from tests.test_lap_viewer import wait_loaded

    backend, paths = track
    shown = [lap.key for lap in backend.data.laps]
    assert shown and backend.reference_key in paths
    reference = backend.reference_key
    other = write_lap(str(tmp_path / "logs"), make_lap(5, OTHER, turn=0.8))
    layout = write_lap(str(tmp_path / "logs"), make_lap(6, LAYOUT))
    same = write_lap(str(tmp_path / "logs"), make_lap(7, shift=70.0, turn=2.0, pace=1.02))
    backend.add_external([other, layout, same])  # MoTeC import & library: lap infos alike (no game name)
    wait_loaded(backend)
    listed = {row["path"] for row in backend.lap_rows()}
    keys = [lap.key for lap in backend.data.laps]
    assert other not in listed and layout not in listed and other not in keys and layout not in keys
    assert "another circuit" in backend.status and "not added" in backend.status
    assert same in listed and same in keys and backend.reference_key == reference
    backend.setReference(other)  # refused even if asked again
    assert backend.reference_key == reference


def test_imported_lap_of_other_circuit_in_track_folder_unchecked(track):
    """Imported lap of another circuit saved in track folder: unchecked & hinted, never reference"""
    from tests.test_lap_viewer import wait_loaded

    backend, paths = track
    folder = os.path.dirname(paths[0])
    other = write_lap(folder, make_lap(8, OTHER))
    backend.refresh()
    wait_loaded(backend)
    backend.add_external([other])  # listed in track: checked
    backend.setReference(paths[0])
    backend.checked.add(other)
    backend.load_laps()
    wait_loaded(backend)
    assert other not in backend.checked and other not in [lap.key for lap in backend.data.laps]
    assert "another circuit" in backend.status
    row = next(row for row in backend.lap_rows() if row["path"] == other)
    assert row["hint"]
    backend.setReference(other)
    assert backend.reference_key != other and "not usable" in backend.status


# Consistency map (laps not shown read in worker process)
def test_consistency_job_aligns_imported_laps(ui_env, tmp_path):
    from PySide6.QtGui import QColor

    from tinypedal.ui.lap_viewer import PlotLap
    from tinypedal.ui.quick.trace_data import TraceData
    from tinypedal.userfile.lap_geometry import mini_sector_job
    from tinypedal.userfile.telemetry_lap import load_lap

    folder = str(tmp_path / COMBO)
    reference_path = write_lap(folder, make_lap(1, recorded=True, positions=False))
    imported_path = write_lap(folder, make_lap(2, shift=120.0, positions=False))
    recorded_path = write_lap(folder, make_lap(3, recorded=True, positions=False, pace=1.01))
    reference = PlotLap(reference_path, "ref", load_lap(reference_path), QColor("red"))
    laps = [reference, *(PlotLap(path, path, load_lap(path), QColor("blue")) for path in (imported_path,
                                                                                          recorded_path))]
    data = TraceData()
    data.set_laps(laps, reference_path)
    assert data.auto_offsets.get(imported_path) == pytest.approx(120.0, abs=1.0)
    mini = data.mini_sectors()
    args = (str(tmp_path), [imported_path, recorded_path], list(mini["bounds"]), data.lap_end(reference),
            dict(reference.data.meta))
    found = mini_sector_job(*args, reference_path)
    for path, times in zip((imported_path, recorded_path), mini["times"][1:]):  # same times as shown laps
        assert found[path] == pytest.approx(times, abs=0.01)
    unaligned = mini_sector_job(*args)  # before: imported lap mini-sectors 120 m away
    assert max(abs(a - b) for a, b in zip(unaligned[imported_path], mini["times"][1])) > 0.1
    assert unaligned[recorded_path] == pytest.approx(found[recorded_path])  # recorded lap never shifted
