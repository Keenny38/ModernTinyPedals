"""Bug audit 2026-10-29 of lap telemetry viewer & race calculator: one test per bug fixed"""

import math
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from neopedal.fuel_strategy import RaceState, StrategyInput, plan, remaining_input
from neopedal.race_live import StopCounter
from neopedal.race_live_data import parse_garage
from neopedal.setting import cfg
from neopedal.userfile import lap_cache, motec_import
from neopedal.userfile.lap_offset import OFFSET_INFO
from neopedal.userfile.telemetry_lap import LapData
from tests.test_lap_viewer import wait_loaded
from tests.test_lap_viewer_fix_list import page as lap_page  # noqa: F401 (fixture)
from tests.test_lap_viewer_fix_list import sessions  # noqa: F401 (fixture)
from tests.test_race_calculator import host, page, set_race  # noqa: F401 (fixtures)

SESSION = 360010


def write_lap(folder: str) -> str:
    from neopedal.module.module_recorder import CSV_HEADER, lap_text

    os.makedirs(os.path.join(folder, "T"), exist_ok=True)
    path = os.path.join(folder, "T", "2026-01-01 10-00-00 lap001 1m30.000s.csv")
    rows = [tuple(float(index) if column not in (8, 9) else 1 for column in range(len(CSV_HEADER)))
            for index in range(100)]
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(lap_text(rows, {"kind": "lap"}))
    return path


# A1: cache file stamp taken after it is touched: lazy columns read from cache, not from CSV again
def test_cached_lap_lazy_columns_read_from_cache(tmp_path, monkeypatch):
    folder = str(tmp_path)
    path = write_lap(folder)
    lap_cache.load_cached_lap(folder, path)  # cache made
    target = lap_cache.cache_file(folder, path)
    past = time.time() - 60
    os.utime(target, (past, past))  # cache file written a while ago
    lap = lap_cache.load_cached_lap(folder, path)
    calls = []
    monkeypatch.setattr(lap_cache, "load_lap", lambda name: calls.append(name))
    stat = os.stat(target)
    assert lap.columns._file == (stat.st_size, stat.st_mtime_ns)
    assert len(lap.columns["tyre_pres_fl"]) == 100
    assert not calls


# A2: lap viewer worker process module free of Qt GUI
def test_lap_geometry_needs_no_qt_gui():
    code = "import sys, neopedal.userfile.lap_geometry; print('PySide6.QtGui' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), check=True)
    assert result.stdout.strip() == "False"


def test_font_weights_match_qt():
    from PySide6.QtGui import QFont

    from neopedal.regex_pattern import FONT_WEIGHT_MAP

    assert FONT_WEIGHT_MAP["Semi Bold"] == QFont.Weight.DemiBold.value
    assert FONT_WEIGHT_MAP["Black"] == QFont.Weight.Black.value
    assert QFont.Weight(FONT_WEIGHT_MAP["Bold"]) == QFont.Weight.Bold


# A3: passage of a lap exported by the app never imported back as a whole lap
def test_passage_comment_not_a_lap():
    assert motec_import.PASSAGE_COMMENT.search("2026-01-01 10-00-00 lap001 1m30.000s 1200-2000 m")
    assert not motec_import.PASSAGE_COMMENT.search("2026-01-01 10-00-00 lap001 1m30.000s")


# A4: imported lap file name rounded first: never 1m60.000s
def test_imported_lap_name_rounded():
    lap = SimpleNamespace(lap_time=119.9996, number=3, finished=0.0)
    assert motec_import.lap_file_name(lap, 0.0).endswith("lap003 2m00.000s.csv")


# F1 & F2: measured compound of undo & of a race plan shown and saved
def test_measured_compound_undo_saved_and_shown(page):  # noqa: F811
    backend = page.backend
    set_race(backend, minutes=60, wear=2.0)
    page.reset_undo()
    before = backend.measured_index
    other = 0 if before != 0 else 1
    backend.setInput("input_measured_compound", other)
    seen = []
    backend.inputsChanged.connect(lambda: seen.append(backend.inputs["input_measured_compound"]))
    page.undo()
    assert backend.measured_index == before
    assert seen and seen[-1] == before
    assert cfg.user.config["fuel_calculator"]["input_measured_compound"] == before


def test_race_plan_measured_compound_saved(page, tmp_path):  # noqa: F811
    backend = page.backend
    set_race(backend, minutes=60, wear=2.0)
    backend.setInput("input_measured_compound", 3)
    path = tmp_path / "plan.rplan"
    backend.save_race_plan(str(path))
    backend.setInput("input_measured_compound", 0)
    assert backend.load_race_plan(str(path))
    assert backend.measured_index == 3
    assert backend.inputs["input_measured_compound"] == 3
    assert cfg.user.config["fuel_calculator"]["input_measured_compound"] == 3


# B1: lap left out by the list filter checked or made reference from Session tab: shown
def test_filtered_out_lap_checked_from_session_tab(lap_page):  # noqa: F811
    lap_page.setFilter("lap003")
    listed = {row["path"] for row in lap_page.lap_rows()}
    target = next(entry.file.path for entry in lap_page.entries
                  if entry.file.path not in listed and entry.file.path not in lap_page.checked)
    lap_page.setLapChecked(target, True)
    wait_loaded(lap_page)
    lap_page.wait_jobs()
    assert target in [lap.key for lap in lap_page.data.laps]
    lap_page.setReference(target)
    wait_loaded(lap_page)
    lap_page.wait_jobs()
    assert lap_page.reference_key == target


# B2: passage of an imported reference lap shown aligned: exported at its own distances
def test_passage_in_file_distances():
    from neopedal.ui.quick.lap_export import LapExports

    raw = LapData("lap", {"distance": [float(value) for value in range(0, 1001, 10)]}, {})
    shown = LapData("lap", {"distance": [0.0]}, {OFFSET_INFO: 300.0})
    part = SimpleNamespace(_page=SimpleNamespace(data=SimpleNamespace(laps=[SimpleNamespace(key="p", data=shown)])),
                           _lap_cache={"p": raw})
    assert LapExports.file_passage(part, "p", 400.0, 600.0) == (100.0, 300.0)
    assert LapExports.file_passage(part, "p", 200.0, 400.0) is None  # across start of log
    part._lap_cache["p"] = shown
    assert LapExports.file_passage(part, "p", 400.0, 600.0) == (400.0, 600.0)


# B3: shared lap file finished like other exports when the viewer closes
def test_share_lap_is_export_job():
    from neopedal.ui.quick.lap_backend import EXPORT_JOBS

    assert "lap share" in EXPORT_JOBS


# B4: older trash listing finishing after a newer one never applied
def test_older_trash_listing_dropped(lap_page):  # noqa: F811
    lap_page._trash_serial = 2
    lap_page._trash_rows = []
    lap_page.trash_read([(1.0, "x", os.path.join("T", "2026-01-01 10-00-00 lap001 1m30.000s.csv"))], 1)
    assert lap_page._trash_rows == []
    lap_page.trash_read([], 2)
    assert not lap_page._trash_loading


# C1: no distance marks along circuit of track map file (point numbers, not meters)
def test_no_distance_marks_on_numbered_circuit():
    from neopedal.ui.quick import lap_map
    from neopedal.ui.quick.lap_map_view import MapView

    road = lap_map.MapLine([float(index) for index in range(1100)], [0.0] * 1100, [0.0] * 1100)
    view = SimpleNamespace(_road=road, _road_numbered=True, guide_line=lambda: road, map_ticks=lambda line: ["tick"])
    assert MapView.distance_marks(view) == []
    view._road_numbered = False
    assert MapView.distance_marks(view) == ["tick"]


# C2: corner near the start line placed outside its bend (points taken around the line)
def test_corner_at_line_faces_outward():
    from neopedal.userfile import corner_coach
    from neopedal.userfile.track_corners import TrackCorner

    radius, count = 60.0, 400
    length = 2 * math.pi * radius
    distances = [length * index / count for index in range(count)]
    xs = [radius * math.cos(value / radius) for value in distances]
    ys = [radius * math.sin(value / radius) for value in distances]

    def corners(name, dists, x, y):
        return [TrackCorner(str(index), place, radius * math.cos(place / radius), radius * math.sin(place / radius))
                for index, place in enumerate((5.0, length - 5.0))], True

    with mock.patch.object(corner_coach, "track_corners", corners):
        placed = corner_coach.place_map_corners("x", list(zip(xs, ys)), [(value, 0.0) for value in distances])
    for corner in placed.corners:
        assert corner.out_x * corner.x / radius + corner.out_y * corner.y / radius > 0.99


# E1: driver short of own minimum keeps the car when no other driver needs time
def test_driver_short_of_minimum_keeps_car():
    strategy = plan(StrategyInput(laptime=120, race_laps=60, pit_seconds=60, tank_capacity=100, fuel_per_lap=3,
                                  drivers=2, driver_min_minutes=(0, 90)))
    assert strategy.stints == [15, 33, 12] and strategy.stint_drivers == [1, 2, 2]
    assert not strategy.driver_issues


# E2: maximum driving times below the race: planned without them (no one-lap stints), still reported
def test_maximums_below_race_no_one_lap_stints():
    strategy = plan(StrategyInput(laptime=120, race_minutes=240, pit_seconds=30, tank_capacity=100, fuel_per_lap=3,
                                  drivers=2, driver_max_minutes=(100, 100)))
    assert strategy.feasible and len(strategy.stops) == 3 and min(strategy.stints) > 1
    assert {kind for _, kind in strategy.driver_issues} == {"max"}


# E3: rest of race planned during the out lap of a stop: out lap consumption kept
def test_rest_of_race_on_out_lap():
    setup = StrategyInput(laptime=100, race_laps=30, tank_capacity=50, fuel_per_lap=3, pit_seconds=30,
                          pit_lap_consumption=0.8)
    base = plan(setup)
    assert base.stints == [16, 14]
    state = RaceState(16, 0.0, 1630, 0, 41.4, 0, 100, 1, 16, 1630)  # fuel after the stop of the plan
    rest = remaining_input(setup, base, state)
    assert rest.out_lap
    assert plan(rest).stints == [14]


# G1: stop & go served (car held, nothing added) is no pit stop
def test_stop_and_go_not_counted():
    def visit(penalty: bool) -> int:
        counter = StopCounter()
        now = 100.0
        counter.update((SESSION, 100, 5), False, 50, 40, 80, 90, 0, now=now, laps=5.5, clock=now)
        for step in range(7):
            now += 2
            counter.update((SESSION, int(now), 5), True, 20 if not step else 0.0, 40, 80, 90, 0, now=now,
                           laps=5.7, clock=now, penalty=penalty)
        now += 2
        return counter.update((SESSION, int(now), 5), False, 60, 40, 80, 90, 0, now=now, laps=5.9, clock=now)

    assert visit(False) == 1  # car held without penalty: stop (tyres or driver change)
    assert visit(True) == 0


# G3: spectated car changed: stops counted from that car's own count
def test_stop_counter_follows_car_change():
    counter = StopCounter()
    counter.update((SESSION, 1000, 10), False, 50, 40, 80, 90, 1, now=1000, laps=10.5, clock=1000, car=7)
    assert counter.update((SESSION, 1002, 12), False, 50, 40, 80, 90, 3, now=1002, laps=12.5, clock=1002, car=9) == 3
    assert counter.update((SESSION, 1004, 12), False, 50, 40, 80, 90, 1, now=1004, laps=10.6, clock=1004, car=7) == 1


# G4: null driver name of game left out
def test_null_driver_name_left_out():
    assert parse_garage({"teamInfo": {"driverNames": [None, " A ", ""]}}).drivers == ("A",)


# G2: race start amounts followed on the grid only (completed laps stay 0 on formation lap & lap 1)
def test_start_amounts_on_grid_only(page, monkeypatch):  # noqa: F811 (page: api started)
    from neopedal.api_control import api
    from neopedal.race_live_data import before_start

    read = api.read
    monkeypatch.setattr(read.session, "session_type", lambda: 4)
    monkeypatch.setattr(read.lap, "completed_laps", lambda *args: 0)
    monkeypatch.setattr(read.session, "before_formation", lambda: True)
    assert before_start()
    monkeypatch.setattr(read.session, "before_formation", lambda: False)
    assert not before_start()


# --- End to end: game simulated through the API (in-game checks run on game values instead)
class SimCar:
    """Player car of a simulated LMU race, read through the API like shared memory"""

    def __init__(self, monkeypatch):
        from neopedal import race_live
        from neopedal.api_control import api
        from neopedal.penalty_info import Penalty

        self.clock = 0.0  # session time & monotonic clock (seconds)
        self.laps, self.progress, self.fuel, self.in_pits, self.speed = 10, 0.5, 30.0, False, 60.0
        self.game_stops, self.penalties, self.slot, self.garage = 0, 0, 7, False
        read = api.read
        values = {
            (read.state, "active"): lambda: True, (read.session, "session_type"): lambda: 4,
            (read.session, "in_race"): lambda: True, (read.session, "start"): lambda: 0.0,
            (read.session, "end"): lambda: 0.0, (read.session, "remaining"): lambda: 0.0,
            (read.session, "elapsed"): lambda: self.clock,
            (read.session, "identifier"): lambda: (SESSION, int(self.clock), self.laps),
            (read.lap, "completed_laps"): lambda: self.laps, (read.lap, "progress"): lambda: self.progress,
            (read.engine, "fuel"): lambda: self.fuel, (read.engine, "virtual_energy"): lambda: 0.0,
            (read.tyre, "wear"): lambda: (0.9, 0.9, 0.9, 0.9),
            (read.vehicle, "in_pits"): lambda: self.in_pits, (read.vehicle, "speed"): lambda: self.speed,
            (read.vehicle, "number_pitstops"): lambda: self.game_stops,
            (read.vehicle, "driver_name"): lambda: "Alice", (read.vehicle, "slot_id"): lambda: self.slot,
            (read.vehicle, "number_penalties"): lambda: self.penalties,
            (read.vehicle, "penalty"): lambda: Penalty(self.penalties, "Stop/Go" if self.penalties else "", 10),
            (read.vehicle, "repair_time"): lambda: 0.0, (read.vehicle, "in_garage"): lambda: self.garage,
        }
        for (group, name), value in values.items():
            monkeypatch.setattr(group, name, lambda *args, value=value, **kwargs: value(), raising=False)
        monkeypatch.setattr(race_live, "monotonic", lambda: self.clock)
        self.counter = StopCounter()

    def read(self):
        from neopedal.race_live import read_race_state

        return read_race_state(float, self.counter)

    def tick(self, seconds: float = 0.5):
        self.clock += seconds
        return self.read()

    def pit(self, hold: float, fuel_added: float = 0.0, serve_penalty: bool = False):
        """Pit lane at end of lap: drive in, stand hold seconds (fuel added meanwhile), line crossed in pit lane,
        drive out"""
        self.progress = 0.95
        self.tick(5.0)
        self.in_pits, self.speed = True, 20.0
        self.tick(5.0)
        self.speed = 0.0
        for step in range(int(hold * 2)):
            self.tick()
            if fuel_added and step == 2:
                self.fuel += fuel_added
        if serve_penalty:
            self.penalties = 0
        self.speed = 20.0
        self.tick(5.0)
        self.laps, self.progress = self.laps + 1, 0.05
        self.in_pits, self.speed = False, 60.0
        return self.tick()


def test_game_stop_and_go_then_real_stop(page, monkeypatch):  # noqa: F811 (page: api started)
    car = SimCar(monkeypatch)
    car.read()
    car.penalties = 1
    state = car.pit(10.0, serve_penalty=True).state  # stop & go: held 10 s, nothing added
    assert state.stops_done == 0 and state.penalties == 0
    state = car.pit(20.0, fuel_added=60.0).state  # real stop: refuelled
    assert state.stops_done == 1 and state.last_stop_lap == car.laps  # stop at end of lap driven (completed + 1)


def test_game_spectated_car_switched(page, monkeypatch):  # noqa: F811
    car = SimCar(monkeypatch)
    car.game_stops = 1
    assert car.read().state.stops_done == 1
    # Director follows a car of the same lap with no stop, standing in its pit box
    car.slot, car.game_stops, car.in_pits, car.speed = 9, 0, True, 0.0
    for _ in range(6):
        assert car.tick().state.stops_done == 0
    # Back to the player car on track: no stop made up from the other car's pit visit
    car.slot, car.game_stops, car.in_pits, car.speed = 7, 1, False, 60.0
    assert car.tick().state.stops_done == 1
    assert car.counter.stops == []


def test_game_out_lap_replan(page, monkeypatch):  # noqa: F811
    setup = StrategyInput(laptime=100, race_laps=30, tank_capacity=50, fuel_per_lap=3, pit_seconds=30,
                          pit_lap_consumption=0.8)
    base = plan(setup)
    assert base.stints == [16, 14] and len(base.stops) == 1
    car = SimCar(monkeypatch)
    car.laps, car.progress, car.fuel, car.clock = 15, 0.9, 3.0, 1500.0
    car.read()
    state = car.pit(20.0, fuel_added=38.4).state  # stop of the plan at lap 16, fuel of the plan added
    assert state.stops_done == 1 and state.last_stop_lap == 16
    rest = plan(remaining_input(setup, base, state))
    assert rest.stints == [14] and not rest.stops  # no more stop: out lap at pit lap consumption


def test_readers_before_formation():
    from neopedal.adapter import lmu_reader, rf2_reader

    for module, struct in ((lmu_reader, "lmuScorInfo"), (rf2_reader, "rf2ScorInfo")):
        session = object.__new__(module.Session)
        for phase, grid, before_green in ((0, True, True), (2, True, True), (3, False, True), (4, False, True),
                                          (5, False, False)):
            object.__setattr__(session, "shmm", SimpleNamespace(**{struct: SimpleNamespace(mGamePhase=phase)}))
            assert (session.before_formation(), session.pre_race()) == (grid, before_green), (module, phase)


def test_game_start_amounts_followed_on_grid_only(page, monkeypatch):  # noqa: F811
    from neopedal.api_control import api
    from neopedal.ui.quick.race_backend import TABS
    from tests.test_race_live_data import row

    backend = page.backend
    set_race(backend, minutes=360, laptime=100.0, tank=100.0, fuel=3.0)
    backend.setTab(TABS.index("live"))
    car = SimCar(monkeypatch)
    car.laps, car.fuel = 0, 88.0
    phase = {"grid": True}
    monkeypatch.setattr(api.read.session, "before_formation", lambda: phase["grid"], raising=False)
    backend.received_garage([])
    assert row(backend, "input_fuel_start")["known"] and row(backend, "input_fuel_start")["game"].startswith("88.0")
    phase["grid"], car.fuel = False, 85.0  # formation lap & lap 1: completed laps still 0
    backend.received_garage([])
    assert not row(backend, "input_fuel_start")["known"]


def test_aligned_imported_passage_exported_at_file_distances(ui_env, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QWidget

    from neopedal.ui.quick.lap_backend import LapViewerBackend
    from neopedal.userfile.telemetry_lap import lap_part, load_lap
    from tests.test_lap_viewer_circuit_shape import COMBO, listed_path, make_lap, write_lap
    from tests.test_lap_viewer_imported_reference import corner_distance

    folder = os.path.join(cfg.path.telemetry.rstrip("/"), COMBO)
    paths = [write_lap(folder, make_lap(number, recorded=True, pace=1 + number / 100)) for number in (1, 2)]
    parent = QWidget()
    backend = LapViewerBackend(parent, cfg.path.telemetry)
    try:
        backend.refresh()
        wait_loaded(backend)
        recorded = listed_path(backend, paths[0])
        imported = write_lap(str(tmp_path / "logs"), make_lap(7, shift=150.0, pace=0.99))
        backend.add_external([imported], [imported])  # reference: aligned on recorded laps (150 m)
        wait_loaded(backend)
        assert backend.reference_key == imported
        shown = {lap.key: lap for lap in backend.data.laps}
        corner = corner_distance(backend.data, shown[recorded])  # slowest corner, chart distance
        jobs = []
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(tmp_path / "p.ld"), ""))
        monkeypatch.setattr(backend, "run_process_job", lambda name, done, function, *args: jobs.append(args))
        backend.exports.exportPassageMotec(corner - 60.0, corner + 60.0)
        assert jobs, backend.status
        low, high = jobs[0][-1]
        assert high - low == pytest.approx(120.0, abs=1.0)
        raw = load_lap(imported)
        speeds = raw.columns["speed_kph"]
        part = lap_part(raw, low, high)
        # Passage of the file around the same corner: its slowest point, not 150 m away from it
        assert min(part.columns["speed_kph"]) == pytest.approx(min(speeds[100:-100]), abs=0.5)
    finally:
        backend.release()
        parent.deleteLater()


# QML parser: member import (glyphs.import) breaks the binding after it (read as a dynamic import), use
# glyphs["import"]: the page did not load at all
def test_no_import_member_in_qml():
    import re
    from pathlib import Path

    from neopedal.ui.quick import QML_FOLDER

    member = re.compile(r"\.import\b")
    found = [f"{path.name}:{number}" for path in sorted(Path(QML_FOLDER).rglob("*.qml"))
             for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
             if not line.lstrip().startswith("//") and member.search(line.split("//")[0])]
    assert not found


# Garage stall (found on live LMU data: 33 of 41 pit visits of a practice server went to the garage, never counted
# by the game, all counted as stops before): standing still in the garage is no stop
def garage_visit(counter: StopCounter, start: float, game_before: int, game_after: int, box_still: float = 0.0,
                 garage_still: float = 20.0, rise_after_exit: bool = False, speed_in_box: float = 0.0) -> int:
    """Pit entry, optional stand at the pit box, drive to the garage stall, stand there, drive out"""
    now, game = start, game_before

    def tick(in_pits, speed, garage=False, seconds=0.5):
        nonlocal now
        now += seconds
        return counter.update((SESSION, int(now), 5), in_pits, speed, 50.0, 0.0, 90.0, game, now=now, laps=5.9,
                              clock=now, garage=garage)

    tick(False, 60.0)
    tick(True, 20.0)
    for _ in range(int(box_still * 2)):
        tick(True, speed_in_box)
    if not rise_after_exit:
        game = game_after
    for _ in range(int(garage_still * 2)):
        tick(True, 0.0, garage=True)
    tick(True, 20.0)
    count = tick(False, 60.0)
    if rise_after_exit:
        game = game_after
        count = tick(False, 60.0)
    return tick(False, 60.0) if count is not None else count


def test_garage_visit_no_stop():
    counter = StopCounter()
    assert garage_visit(counter, 100.0, 0, 0, box_still=3.0) == 0 and counter.stops == []


def test_box_service_then_garage_counted_once():
    counter = StopCounter()
    assert garage_visit(counter, 100.0, 0, 1, box_still=25.0) == 1 and len(counter.stops) == 1
    counter = StopCounter()  # game count rising just after the pit exit
    assert garage_visit(counter, 100.0, 0, 1, box_still=25.0, rise_after_exit=True) == 1
    assert len(counter.stops) == 1 and counter.stops[0].lap == 6


def test_drive_through_counted_by_game_no_stop():
    counter = StopCounter()
    # Game count rising during a visit the car never stood still in: left out as before (drive-through penalty)
    assert garage_visit(counter, 100.0, 0, 1, garage_still=0.0, speed_in_box=15.0, box_still=10.0) == 0
    assert counter.stops == []
