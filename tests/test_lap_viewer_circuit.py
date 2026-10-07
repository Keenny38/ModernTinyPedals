"""Lap viewer: laps of another circuit never compared with laps of shown track (file, library, MoTeC, reference):
opened alone, viewer switches to their circuit; compared laps lined up with reference lap along distance, overlay
reference lap wrapped at lap length"""

import os

import pytest

from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_fix_list import BASE, page, sessions  # noqa: F401
from tinypedal.module import module_recorder


def other_lap(folder: str, track: str = "Monza", length: float = 490.0, info: bool = True) -> str:
    """Recorded lap of another track (same length as Atlanta laps: only track name tells them apart), in its own
    track folder, with or without lap info (older laps)"""
    combo = f"{track} - Hyper"
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    lap_info = {"kind": "lap", "track": track, "combo": combo, "track_length": length} if info else None
    module_recorder.save_lap(f"{folder}/", combo, 7, 50.0, rows, max_saved_laps=99, info=lap_info, timestamp=BASE)
    return os.path.normpath(os.path.join(folder, combo, module_recorder.lap_filename(7, 50.0, True, BASE)))


def shown(backend) -> list[str]:
    return [lap.key for lap in backend.data.laps]


def listed(backend) -> set[str]:
    return {row["path"] for row in backend.lap_rows()}


def test_circuit_name():
    from tinypedal.ui.quick.lap_backend import circuit_name

    path = os.path.join("x", "Monza - Hyper", "lap.csv")
    assert circuit_name({"combo": "Spa - GT3", "track": "Spa"}, path) == "Spa"  # recorded: game track name
    assert circuit_name({}, path) == "Monza"  # older lap without lap info: track folder
    assert circuit_name({}, os.path.join("x", "logs", "lap.csv")) == ""  # unknown
    assert circuit_name({"track": "Monza venue", "track_length": 5800.0}, path) == ""  # imported log: venue name


def test_lap_of_other_circuit_shown_alone(page, tmp_path):  # noqa: F811
    """Lap of another track added from a file: viewer switches to its circuit (lap shown alone, laps of former track
    no longer listed nor compared), library lap of that circuit compared with it, game track picked again: its laps
    back, lap of the other circuit never compared with them nor reference lap"""
    before, reference, track = shown(page), page.reference_key, page.currentTrack
    assert before and track
    other = other_lap(str(tmp_path / "other"))
    page.add_external([other])  # Add File...
    wait_loaded(page)
    assert shown(page) == [other] and page.reference_key == other and listed(page) == {other}
    assert page.status == "Showing Monza: lap from another circuit"
    assert page.currentTrack == "" and page.trackLabel == "Monza"  # track picker: opened circuit
    page.refresh()  # opened circuit kept
    wait_loaded(page)
    assert shown(page) == [other] and listed(page) == {other}
    second = other_lap(str(tmp_path / "other2"))
    page.add_from_library([second])  # same circuit as shown lap now: compared with it
    wait_loaded(page)
    assert sorted(shown(page)) == sorted([other, second]) and listed(page) == {other, second}
    page.currentTrack = track  # way back: track picker
    wait_loaded(page)
    assert sorted(shown(page)) == sorted(before) and page.reference_key == reference and page.trackLabel == ""
    assert other not in page.checked
    page.setReference(other)  # still listed (dimmed): never reference lap of another circuit
    wait_loaded(page)
    assert page.reference_key == reference and sorted(shown(page)) == sorted(before) and "not usable" in page.status


def test_older_lap_of_other_circuit_shown_alone(page, tmp_path):  # noqa: F811
    """Lap without lap info (older app): circuit of its track folder"""
    other = other_lap(str(tmp_path / "old"), info=False)
    page.add_external([other])
    wait_loaded(page)
    assert shown(page) == [other] and listed(page) == {other} and "Monza" in page.status


def test_lap_of_other_track_folder_shows_that_track(page):  # noqa: F811
    """Lap of another track folder of the app opened: that track shown (its laps listed to compare, picker on it),
    opened lap alone shown, refresh keeps it"""
    from tinypedal.setting import cfg

    folder = cfg.path.telemetry.rstrip("/")
    other = other_lap(folder)
    older = os.path.normpath(os.path.join(folder, "Monza - Hyper", module_recorder.lap_filename(6, 52.0, True, BASE)))
    rows = [(i * 0.1, i * 0.1, i * 10.0, 100.0) + (0,) * (len(module_recorder.CSV_HEADER) - 4) for i in range(50)]
    module_recorder.save_lap(f"{folder}/", "Monza - Hyper", 6, 52.0, rows, max_saved_laps=99,
                             info={"kind": "lap", "track": "Monza", "combo": "Monza - Hyper", "track_length": 490.0},
                             timestamp=BASE)
    page.refresh()
    wait_loaded(page)
    page.add_from_library([other])
    wait_loaded(page)
    from tests.test_lap_viewer_circuit_shape import listed_path

    other, older = listed_path(page, other), listed_path(page, older)
    assert page.currentTrack == "Monza - Hyper" and page.trackLabel == ""
    assert shown(page) == [other] and listed(page) == {other, older} and not page.external
    assert "Showing Monza" in page.status


def test_motec_lap_of_other_circuit_shown_alone(page, tmp_path):  # noqa: F811
    """MoTeC log of another circuit imported: its laps shown on their own track length, former laps not compared"""
    from tests.test_motec_import import logger_channels, write_logger_ld

    before = shown(page)
    log = tmp_path / "Monza run.ld"
    write_logger_ld(str(log), logger_channels(track=1000.0), venue="Monza")
    page.import_motec([str(log)], background=False)
    wait_loaded(page)
    keys = shown(page)
    assert keys and not set(keys) & set(before) and not listed(page) & set(before)
    assert page.data.max_x() == pytest.approx(1000.0, rel=0.02)  # Atlanta laps: 490 m
    assert "Showing Monza" in page.status and page.trackLabel == "Monza"


def test_laps_of_two_other_circuits_first_kept(page, tmp_path):  # noqa: F811
    """Laps of two other circuits opened together: circuit of first lap (fastest lap given as reference) kept,
    others refused, never shown together"""
    monza = other_lap(str(tmp_path / "a"))
    imola = other_lap(str(tmp_path / "b"), track="Imola", length=700.0)
    page.add_external([monza, imola])
    wait_loaded(page)
    assert shown(page) == [monza] and listed(page) == {monza}
    assert "Showing Monza" in page.status and "not added: Imola" in page.status
    fast = other_lap(str(tmp_path / "c"), track="Spa", length=900.0)
    os.rename(fast, fast := fast.replace("0m50.000s", "0m40.000s"))
    page.add_from_library([imola, fast])  # fastest lap circuit kept
    wait_loaded(page)
    assert shown(page) == [fast] and listed(page) == {fast}
    assert "Showing Spa" in page.status and "Imola" in page.status


def test_lap_of_same_circuit_added(page, tmp_path):  # noqa: F811
    """Lap of shown circuit from another folder added & compared, laps of another circuit given with it left out"""
    same = other_lap(str(tmp_path / "teammate"), track="Atlanta")
    other = other_lap(str(tmp_path / "other"))
    page.add_from_library([other, same])
    wait_loaded(page)
    assert same in listed(page) and other not in listed(page)
    assert page.reference_key == same and same in shown(page) and other not in shown(page)


def test_compared_laps_line_up_on_distance(ui_env):
    """Corner of compared lap at the same axis position as on reference lap: other lap time & sampling, imported log
    on driven distance (scaled to reference lap length), on time axis delta & laps at their own lap time"""
    from tests.test_lap_viewer_audit import game_lap
    from tinypedal.ui.lap_viewer import CHANNEL_MAP, LAP_COLORS, PlotLap
    from tinypedal.ui.quick.trace_data import TraceData
    from tinypedal.userfile.telemetry_lap import LapData

    def with_corner(lap: LapData, length: float = 1000.0) -> LapData:
        speeds = [60.0 if abs(distance / length * 1000.0 - 400.0) < 20 else 200.0 for distance in lap.distance]
        return LapData(lap.name, {**lap.columns, "speed_kph": speeds}, lap.meta)

    reference = with_corner(game_lap(1, 50.0))
    slower = with_corner(game_lap(2, 52.0, first=0.12, stale=0.05))
    imported = game_lap(3, 51.0, length=1030.0)  # driven distance: 3% longer
    imported = with_corner(LapData(imported.name, imported.columns, {"kind": "lap", "track_length": 1030.0}), 1030.0)
    data = TraceData()
    laps = [PlotLap(name, name, lap, LAP_COLORS[index]) for index, (name, lap) in enumerate(
        (("a", reference), ("b", slower), ("c", imported)))]
    data.set_laps(laps, "a")
    speed = CHANNEL_MAP["speed_kph"]

    def corner(lap: PlotLap) -> float:
        xs, ys = data.series(speed, lap)
        inside = [x for x, y in zip(xs, ys) if y < 100]
        return (inside[0] + inside[-1]) / 2

    assert [corner(lap) for lap in laps] == pytest.approx([400.0] * 3, abs=1.0)
    for lap in laps:  # cursor on corner: every lap at its corner (map, G circle)
        assert data.lap_distance_at_x(lap, 400.0) * data.scale_of(lap) == pytest.approx(400.0, abs=0.01)
    distances, deltas = data.deltas["b"]
    assert deltas[-1] == pytest.approx(2.0, abs=0.01) and distances[-1] == pytest.approx(1000.0)
    data.set_time_axis(True)
    assert corner(laps[1]) == pytest.approx(400.0 * 52.0 / 1000.0, abs=0.05)  # its own lap time at corner
    xs = data.series(CHANNEL_MAP["delta"], laps[1])[0]
    assert xs[-1] == pytest.approx(52.0)


def test_overlay_reference_wraps_at_lap_length(tmp_path):
    """Telemetry comparison overlay: reference values one whole step apart over lap, value of next lap at its own
    distance past the line (lap length not a multiple of chosen step: no shift after the line)"""
    import json

    from tinypedal.userfile.reference_trace import load_trace
    from tinypedal.userfile.telemetry_lap import lap_files

    length = 1001.3
    folder = tmp_path / "Track - Class"
    folder.mkdir()
    lines = ["# " + json.dumps({"track": "Track", "combo": "Track - Class", "track_length": length}),
             "time,lap_time,distance,speed_kph"]
    for index in range(1001):
        distance = index * length / 1000
        lines.append(f"{distance / 20},{distance / 20},{distance},{100 + distance / 10}")  # speed grows along lap
    (folder / "2026-10-06 10-00-00 lap001 0m50.065s.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    trace = load_trace(str(tmp_path), lap_files(str(folder))[0], 2.0)
    count = len(trace.channels["speed_kph"])
    assert count * trace.step == pytest.approx(length) and trace.step >= 2.0
    # Index of next lap (drawn past the line) reads lap start, at lap length + its distance
    assert trace.at("speed_kph", count) == pytest.approx(100.0, abs=0.01)
    assert trace.at("speed_kph", count - 1) == pytest.approx(100 + (length - trace.step) / 10, abs=0.01)
    assert trace.value("speed_kph", length + 10.0) == pytest.approx(trace.value("speed_kph", 10.0))
