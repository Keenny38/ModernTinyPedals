"""Delta module: session best & stint best laps kept while module restarts in the same session
(app restarted, preset reloaded, setting saved), reset by new session or pit stop; no delta on out
laps (back to garage, pit lane) and before start line in pit lane, delta overlays show a dash"""

from types import SimpleNamespace

import pytest

from tinypedal import realtime_state, validator
from tinypedal.api_control import api
from tinypedal.const_common import DELTA_DEFAULT, MAX_SECONDS
from tinypedal.module import module_delta
from tinypedal.module_info import DeltaInfo
from tinypedal.userfile.delta_best import load_delta_session_file, save_delta_session_file

STEP = 0.05
TRACK = 4000.0
STAMP = 360001  # 1 hour practice


def lap_rows(laptime: float) -> tuple:
    """Delta set of a lap at constant speed"""
    return tuple((TRACK * index / 40, laptime * index / 40) for index in range(41))


@pytest.fixture
def wall_clock(monkeypatch):
    clock = {"now": 10_000.0}
    monkeypatch.setattr(validator, "time", SimpleNamespace(time=lambda: clock["now"]))
    return clock


# --- File
def test_session_file_same_session_only(tmp_path, wall_clock):
    folder = f"{tmp_path}/"
    token = validator.session_token((STAMP, 300, 4))
    save_delta_session_file(folder, "Track - GT3", token, 1, lap_rows(98.0), lap_rows(99.5))
    wall_clock["now"] += 200
    later = validator.session_token((STAMP, 500, 6))
    session, session_time, stint, stint_time = load_delta_session_file(folder, "Track - GT3", later, 1)
    assert (session_time, stint_time) == (98.0, 99.5) and len(session) == len(stint) == 41
    # Pit stop since saved: stint best of an old stint, left out
    _, session_time, stint, stint_time = load_delta_session_file(folder, "Track - GT3", later, 2)
    assert session_time == 98.0 and (stint, stint_time) == (DELTA_DEFAULT, MAX_SECONDS)
    # Session restarted (same length & type, started after saved one): nothing kept
    wall_clock["now"] += 5000
    restarted = validator.session_token((STAMP, 100, 1))
    assert load_delta_session_file(folder, "Track - GT3", restarted, 1)[1::2] == (MAX_SECONDS, MAX_SECONDS)
    # Other combo, invalid file
    assert load_delta_session_file(folder, "Other - GT3", later, 1)[1] == MAX_SECONDS
    (tmp_path / "Track - GT3.session").write_text('{"session": [1, 2], "session_best": "x"}', encoding="utf-8")
    assert load_delta_session_file(folder, "Track - GT3", later, 1)[1::2] == (MAX_SECONDS, MAX_SECONDS)


def test_session_file_without_stint_best(tmp_path, wall_clock):
    folder = f"{tmp_path}/"
    token = validator.session_token((STAMP, 300, 4))
    save_delta_session_file(folder, "Track - GT3", token, 0, lap_rows(98.0), DELTA_DEFAULT)
    _, session_time, _, stint_time = load_delta_session_file(folder, "Track - GT3", token, 0)
    assert session_time == 98.0 and stint_time == MAX_SECONDS


# --- Module
class Game:
    """Player car driving laps at constant speed, session & wall clocks running together"""

    def __init__(self, clock: dict):
        self.clock = clock
        self.elapsed = 10.0
        self.lap_start = 10.0
        self.last_laptime = -1.0
        self.distance = 0.0
        self.in_pits = False
        self.speed = 40.0
        self.laps = 0
        self.pitstops = 0

    def reader(self):
        return SimpleNamespace(
            timing=SimpleNamespace(
                start=lambda: self.lap_start,
                current_laptime=lambda: max(self.elapsed - self.lap_start, 0.0),
                last_laptime=lambda: self.last_laptime,
                elapsed=lambda: self.elapsed,
                reference_laptime=lambda laptime=0.0: laptime,
            ),
            lap=SimpleNamespace(distance=lambda: self.distance),
            vehicle=SimpleNamespace(
                in_pits=lambda: self.in_pits, speed=lambda: self.speed, number_pitstops=lambda: self.pitstops),
            session=SimpleNamespace(
                combo_name=lambda: "Track - GT3", identifier=lambda: (STAMP, int(self.elapsed), self.laps)),
        )


class Driver:
    """Delta module generator fed by game"""

    def __init__(self, game: Game, folder: str):
        self.game = game
        self.folder = folder
        self.output = DeltaInfo()
        self.resets = 0
        self.start_module()

    def start_module(self):
        self.gen = module_delta.calc_delta_time(self.output, self.folder, 10, 5, 6, 3.0)
        self.resets += 1
        self.tick()

    def tick(self, seconds: float = STEP):
        self.game.elapsed += seconds
        self.game.clock["now"] += seconds
        self.output.lapDistance = self.game.distance
        self.gen.send(self.resets)

    def lap(self, laptime: float):
        game = self.game
        start = game.lap_start
        while game.elapsed + STEP - start < laptime:
            game.distance = (game.elapsed - start) / laptime * TRACK
            self.tick()
        self.tick(start + laptime - game.elapsed)  # finish line
        game.lap_start = game.elapsed
        game.distance = 0.0
        game.laps += 1
        for _ in range(30):  # last lap time reported a moment later
            self.tick()
        game.last_laptime = laptime
        for _ in range(40):
            self.tick()

    def pit_stop(self):
        game = self.game
        game.pitstops += 1
        game.in_pits, game.speed = True, 0.0
        for _ in range(100):
            self.tick()
        game.in_pits, game.speed = False, 40.0

    def bests(self) -> tuple[float, float]:
        return self.output.lapTimeSession, self.output.lapTimeStint


@pytest.fixture
def driver(monkeypatch, tmp_path, wall_clock):
    game = Game(wall_clock)
    monkeypatch.setattr(api, "read", game.reader())
    monkeypatch.setattr(realtime_state, "active", True)
    return Driver(game, f"{tmp_path}/")


def test_stint_best_resets_at_pit_stop_session_best_kept(driver):
    for laptime in (100.0, 98.0, 99.0):  # first lap partial (not timed)
        driver.lap(laptime)
    assert driver.bests() == (98.0, 98.0)  # first stint: same lap
    driver.pit_stop()
    assert driver.bests() == (98.0, MAX_SECONDS)
    for laptime in (101.0, 99.5):
        driver.lap(laptime)
    assert driver.bests() == (98.0, 99.5)


def test_bests_kept_when_module_restarts_in_same_session(driver):
    for laptime in (100.0, 98.0, 99.0):
        driver.lap(laptime)
    driver.pit_stop()
    for laptime in (101.0, 99.5):
        driver.lap(laptime)
    driver.start_module()  # preset reloaded, setting saved, app restarted...
    driver.lap(100.2)
    assert driver.bests() == (98.0, 99.5)  # session best not lost (was 100.2, same as stint best)
    # Restart after a pit stop the module missed: stint best of old stint left out
    driver.game.pitstops += 1
    driver.start_module()
    driver.lap(100.4)
    assert driver.bests() == (98.0, MAX_SECONDS)  # (lap after restart partial, not timed)


# --- Out lap: back to garage starts a new lap, lap distance negative in garage & pit lane before line
def run_garage_out_lap(driver):
    """Laps, back to garage mid lap, out lap through pit lane, flying lap; flags at each step"""
    game = driver.game
    flags = {}
    for laptime in (100.0, 98.0):
        driver.lap(laptime)
    for _ in range(200):  # 10 s into lap
        game.distance += 4.0
        driver.tick()
    # Back to garage: game counts a lap (invalid) and starts the next one, car before line
    game.lap_start = game.elapsed
    game.laps += 1
    game.last_laptime = -1.0
    game.in_pits, game.speed, game.distance = True, 0.0, -245.0
    driver.resets += 1
    for _ in range(100):
        driver.tick()
    flags["garage"] = (driver.output.isDeltaAvailable, driver.output.hasLastLap)
    for _ in range(100):  # pit lane, before start line
        game.speed = 15.0
        game.distance += 0.75
        driver.tick()
    flags["pit lane"] = driver.output.isDeltaAvailable
    game.in_pits = False
    game.speed = 40.0
    while game.distance < TRACK - 2:  # out lap on track (lap continues from garage)
        game.distance += 2.0
        driver.tick()
    flags["out lap"] = driver.output.isDeltaAvailable
    driver.tick(0.01)
    game.lap_start = game.elapsed  # timing line on track: flying lap starts
    game.laps += 1
    game.distance = 0.0
    for _ in range(100):
        game.distance += 2.0
        driver.tick()
    flags["flying lap"] = (driver.output.isDeltaAvailable, driver.output.hasLastLap)
    return flags


def test_no_delta_on_out_lap_from_garage(driver):
    flags = run_garage_out_lap(driver)
    assert flags["garage"] == (False, False)
    assert flags["pit lane"] is False and flags["out lap"] is False
    assert flags["flying lap"] == (True, False)  # last lap was the out lap: not comparable
    assert driver.output.lapTimeSession == 98.0


def test_last_lap_comparable_after_flying_lap(driver):
    driver.lap(100.0)
    driver.lap(99.0)
    assert driver.output.isDeltaAvailable and driver.output.hasLastLap


@pytest.fixture
def overlays(ui_env, bundled_fonts):
    from importlib import import_module

    from PySide6.QtCore import QCoreApplication

    from tinypedal.setting import cfg
    from tinypedal.widget._modern import create_widget

    created = []

    def make(name: str, **options):
        cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark"
        cfg.user.setting[name].update(options)
        widget = create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)
        created.append(widget)
        return widget

    yield make
    for widget in created:
        widget.deleteLater()
    QCoreApplication.processEvents()


def delta_info(monkeypatch, **values):
    from tinypedal.module_info import minfo

    base = {"lapTimeCurrent": 50.0, "lapTimeLast": 99.0, "lapTimeBest": 97.0, "lapTimeSession": 98.0,
            "lapTimeStint": MAX_SECONDS, "deltaBest": 0.4, "deltaSession": -0.2, "deltaStint": 0.0, "deltaLast": 0.1,
            "isDeltaAvailable": True, "hasLastLap": True}
    for key, value in {**base, **values}.items():
        monkeypatch.setattr(minfo.delta, key, value)


def test_extended_dash_without_reference_or_delta(overlays, monkeypatch):
    from tinypedal.widget._modern.base import DASH

    delta_info(monkeypatch)
    widget = overlays("deltabest_extended", show_all_time_deltabest=True, show_session_deltabest=True,
                      show_stint_deltabest=True, show_deltalast=True, show_game_deltabest_if_available=False)
    widget.timerEvent(None)
    texts = dict(zip(widget.keys, (value.text for value in widget.state)))
    assert texts["all_time_deltabest"] == "+0.400" and texts["session_deltabest"] == "-0.200"
    assert texts["stint_deltabest"] == DASH  # no lap in stint yet
    assert texts["deltalast"] == "+0.100"
    delta_info(monkeypatch, isDeltaAvailable=False)  # out lap, pit lane
    widget.timerEvent(None)
    assert all(value.text == DASH for value in widget.state)
    widget.grab()


def test_deltabest_dash_without_reference_or_delta(overlays, monkeypatch):
    delta_info(monkeypatch)
    widget = overlays("deltabest", deltabest_source="Best", show_game_deltabest_if_available=False)
    widget.timerEvent(None)
    assert widget.state[0] == 0.4
    delta_info(monkeypatch, isDeltaAvailable=False)
    widget.timerEvent(None)
    assert widget.state[0] is None
    widget.grab()  # dash drawn
    stint = overlays("deltabest", deltabest_source="Stint")
    delta_info(monkeypatch)
    stint.timerEvent(None)
    assert stint.state[0] is None  # no stint best yet


def classic_overlay(name: str, **options):
    from importlib import import_module

    from tinypedal.setting import cfg
    from tinypedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Legacy Dark"
    cfg.user.setting[name].update(options)
    return create_widget(import_module(f"tinypedal.widget.{name}"), cfg, name)


def test_classic_delta_overlays_dash_without_delta(ui_env, bundled_fonts, monkeypatch):
    delta_info(monkeypatch)
    deltabest = classic_overlay("deltabest", deltabest_source="Best")
    extended = classic_overlay("deltabest_extended", show_stint_deltabest=True, show_deltalast=True)
    history = classic_overlay("lap_time_history", show_delta=True)
    try:
        for widget in (deltabest, extended, history):
            widget.timerEvent(None)
        assert deltabest.delta_best == 0.4
        assert extended.bar_stbest.text.strip().endswith("-")  # no stint best yet
        assert history.bars_delta[0].text.startswith("+0.1")
        delta_info(monkeypatch, isDeltaAvailable=False)  # out lap
        for widget in (deltabest, extended, history):
            widget.timerEvent(None)
            widget.grab()
        assert deltabest.delta_best is None
        assert extended.bar_atbest.text.strip().endswith("-") and extended.bar_labest.text.strip().endswith("-")
        assert history.bars_delta[0].text == "-"
    finally:
        for widget in (deltabest, extended, history):
            widget.deleteLater()


def test_estimated_laptime_none_on_out_lap(driver):
    for laptime in (100.0, 98.0):
        driver.lap(laptime)
    assert driver.output.lapTimeEstimated > 0
    driver.game.in_pits = True  # lap started in pit lane: out lap
    driver.lap(130.0)
    assert driver.output.lapTimeEstimated == 0 and not driver.output.isDeltaAvailable


def test_web_dashboard_delta_available(monkeypatch):
    from tinypedal import web_dashboard

    delta_info(monkeypatch)
    assert web_dashboard.delta_available()
    delta_info(monkeypatch, isDeltaAvailable=False)
    assert not web_dashboard.delta_available()
