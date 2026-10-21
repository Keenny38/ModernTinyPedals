"""Recorded game sessions replayed through the real reader, data modules and overlays (see recorded_session)

Values computed by modules are compared with the game values of the recording, read straight from the
recorded shared memory (GameTruth), and with the facts of each session written in its json file.
"""

import csv
import json
import os
from importlib import import_module

import pytest
from PySide6.QtCore import QCoreApplication, Qt, QTimerEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget

from neopedal import realtime_state
from neopedal.api_control import api
from neopedal.module_info import ModuleInfo, minfo
from neopedal.setting import cfg
from neopedal.template.setting_module import MODULE_FILENAME
from neopedal.widget._modern import create_widget
from tests.recorded_session import (
    RecordedSession,
    expected_values,
    lockstep_modules,
    logged_errors,
    recorded_sessions,
)
from tests.test_widget_render import WIDGET_NAMES

SESSIONS = recorded_sessions()
PAINT_EVERY = 20  # overlays painted every 20 frames (updated every frame)


@pytest.fixture
def fresh_minfo(monkeypatch):
    """Module outputs of a new app start"""
    fresh = ModuleInfo()
    for name in ModuleInfo.__slots__:
        monkeypatch.setattr(minfo, name, getattr(fresh, name))


@pytest.fixture
def session(ui_env, fresh_minfo, monkeypatch, request):
    """Recorded session read by app API (request.param: session name)"""
    for name in ("active", "paused", "resets", "shown", "session_type", "in_pits"):
        monkeypatch.setattr(realtime_state, name, getattr(realtime_state, name))
    # As app start: inactive until first frame synced (state left active by an earlier test: modules started
    # before frame 0 read player telemetry not synced yet, None)
    realtime_state.active = realtime_state.paused = realtime_state.shown = realtime_state.in_pits = False
    realtime_state.resets = 0
    monkeypatch.setattr(realtime_state, "singleton", True)  # single instance (as app): driver stats recorded
    recorded = RecordedSession(request.param, cfg.api)
    monkeypatch.setattr(api, "_api", recorded.connector)
    monkeypatch.setattr(api, "read", recorded.reader)
    yield recorded
    recorded.close()


class GameTruth:
    """Game values of every frame of recorded session, read from raw shared memory structures"""

    def __init__(self, session: RecordedSession):
        self.laps: list[tuple[int, float, float, float, bool]] = []  # lap, start, end, fuel used, seen from start
        driving = None
        self.pit_entries = 0
        self.refuels: list[float] = []
        self.distance = 0.0
        lap_start = last_fuel = last_dist = None
        lap_fuel = 0.0
        seen_from_start = False
        in_pits = False
        for _ in session.frames():
            scor, tele = session.sync.player_scor, session.sync.player_tele
            info = session.sync.dataset.shmm.data.scoring.scoringInfo
            if scor.mInGarageStall:  # back to garage (car reset): not driving
                continue
            fuel, dist = tele.mFuel, scor.mLapDist
            if last_fuel is not None:
                if fuel < last_fuel:
                    lap_fuel += last_fuel - fuel
                elif fuel > last_fuel + 0.5:  # refilled in pit stop
                    self.refuels.append(fuel - last_fuel)
            # Lap start of telemetry: updated with every sample (scoring lags up to 0.2 s)
            if lap_start is not None and tele.mLapStartET > lap_start:
                self.laps.append((tele.mLapNumber, lap_start, tele.mLapStartET, lap_fuel, seen_from_start))
                lap_fuel = 0.0
                seen_from_start = True
            if last_dist is not None and dist >= 0:
                moved = dist - last_dist
                if moved < -info.mLapDist / 2:  # crossed line
                    moved += info.mLapDist
                if 0 < moved < 200:  # never a jump (teleport)
                    self.distance += moved
            if scor.mInPits and not in_pits:
                self.pit_entries += 1
            in_pits = scor.mInPits
            lap_start, last_fuel, last_dist = tele.mLapStartET, fuel, dist
            driving = (tele.mFuelCapacity, info.mNumVehicles, info.mTrackName.decode(), scor.mVehicleClass.decode(),
                       info.mSession, scor.mNumPitstops)
        assert driving is not None, "no frame driving"
        # Values of last frame driving
        self.fuel = last_fuel
        self.capacity, self.vehicles, self.track, self.vehicle_class, self.session_type, self.pit_stops = driving


def session_name(session: RecordedSession) -> str:
    return os.path.basename(session.replay.filename)[:-len(".tpreplay")]


def replay(session: RecordedSession, lockstep, on_frame=None):
    """Play every frame of session with modules (on_frame: called with frame index before each frame is
    loaded, modules waiting, then once with frame count after last frame)"""
    for index in range(len(session)):
        def load(index=index):
            if on_frame is not None:
                on_frame(index)
            session.load(index)
        lockstep.step(load)
    lockstep.finish()
    if on_frame is not None:
        on_frame(len(session))


def history_rows() -> list[dict]:
    """Consumption history saved by stint module (laps, newest first, placeholder row removed)"""
    folder = cfg.path.fuel_delta
    files = [name for name in os.listdir(folder) if name.endswith(".consumption")]
    assert len(files) == 1, files
    with open(os.path.join(folder, files[0]), encoding="utf-8", newline="") as file:
        return [row for row in csv.DictReader(file) if float(row["lapTimeLast"]) > 0]


@pytest.mark.parametrize("session", SESSIONS, indirect=True)
def test_recording_matches_its_facts(session):
    """Fixture holds what its json says (checked by hand when added), player renamed"""
    truth = GameTruth(session)
    expected = expected_values(session_name(session))
    assert truth.track == expected["track"]
    assert truth.vehicle_class == expected["vehicle_class"]
    assert truth.session_type == expected["session_type"]
    assert truth.vehicles == expected["vehicles"]
    assert truth.pit_entries == expected["pit_stops"]
    assert bool(truth.refuels) == expected["refuel"]
    assert session.sync.dataset.shmm.data.scoring.scoringInfo.mPlayerName.startswith(b"Test Driver")


@pytest.mark.parametrize("session", SESSIONS, indirect=True)
def test_modules_follow_game_values(session, monkeypatch):
    truth = GameTruth(session)
    expected = expected_values(session_name(session))
    with logged_errors() as errors, lockstep_modules(monkeypatch, MODULE_FILENAME, cfg) as lockstep:
        replay(session, lockstep)
        # Fuel: tank and amount of game
        assert minfo.fuel.capacity == pytest.approx(truth.capacity)
        assert minfo.fuel.amountCurrent == pytest.approx(truth.fuel, abs=0.01)
        # Laps: last lap time from lap start times of game
        _, start, end, _, _ = truth.laps[-1]
        assert minfo.delta.lapTimeLast == pytest.approx(end - start, abs=0.01)
        # Field: every car, player found
        assert minfo.vehicles.totalVehicles == truth.vehicles
        player = minfo.vehicles.dataSet[minfo.vehicles.playerIndex]
        assert player.isPlayer
        assert player.numPitStops == truth.pit_stops
        # Pit lane: speed limit measured while in pit lane
        assert minfo.mapping.pitSpeedLimit * 3.6 == pytest.approx(expected["pit_speed_limit_kph"], abs=1.5)
    assert not errors.messages()

    # Consumption history (saved on stop): laps seen from their start only, with fuel used in game
    rows = history_rows()
    seen = {lap: (end - start, fuel) for lap, start, end, fuel, from_start in truth.laps if from_start}
    assert [int(row["lapNumber"]) for row in rows] == sorted(seen, reverse=True)
    for row in rows:
        laptime, fuel = seen[int(row["lapNumber"])]
        assert float(row["lapTimeLast"]) == pytest.approx(laptime, abs=0.01)
        assert float(row["lastLapUsedFuel"]) == pytest.approx(fuel, abs=0.01)
        assert float(row["capacityFuel"]) == pytest.approx(truth.capacity)

    # Driver stats (saved on stop): distance driven
    with open(os.path.join(cfg.path.config, "driver.stats"), encoding="utf-8") as file:
        (vehicle_stats,) = json.load(file)[truth.track].values()
    assert vehicle_stats["meters"] == pytest.approx(truth.distance, rel=0.02)


@pytest.mark.parametrize("session", SESSIONS, indirect=True)
def test_partial_first_lap_not_in_consumption_history(session, monkeypatch):
    """App started mid-lap: that lap's consumption only counts its end, never saved as a lap"""
    partial = [lap for lap, *_, from_start in GameTruth(session).laps if not from_start]
    if not partial:
        pytest.skip("recording starts at lap start")
    with lockstep_modules(monkeypatch, MODULE_FILENAME, cfg) as lockstep:
        replay(session, lockstep)
        assert minfo.fuel.lastLapPartial is False  # laps after first one counted from their start
    assert partial[0] not in {int(row["lapNumber"]) for row in history_rows()}


@pytest.mark.parametrize("theme", ["Modern Dark", "Legacy Dark"])
@pytest.mark.parametrize("session", SESSIONS, indirect=True)
def test_overlays_update_and_paint(session, theme, bundled_fonts, monkeypatch):
    """Every overlay updated on every frame and painted along the session, no error"""
    cfg.user.config["overlay_style"]["overlay_theme"] = theme
    widgets = []
    failures = []

    def on_frame(index):
        if not realtime_state.shown:  # as app: overlay timers stopped while not shown
            return
        for name, widget in widgets:
            try:
                widget.timerEvent(QTimerEvent(0))
                if index % PAINT_EVERY == 0 or index == len(session):
                    pixmap = QPixmap(widget.size())
                    pixmap.fill(Qt.GlobalColor.transparent)
                    widget.render(pixmap, renderFlags=QWidget.RenderFlag.DrawChildren)
            except Exception as error:  # every failing overlay reported, not only first one
                failures.append(f"{name} at frame {index}: {error!r}")

    with logged_errors() as errors, lockstep_modules(monkeypatch, MODULE_FILENAME, cfg) as lockstep:
        try:
            widgets.extend(
                (name, create_widget(import_module(f"neopedal.widget.{name}"), cfg, name)) for name in WIDGET_NAMES)
            replay(session, lockstep, on_frame)
        finally:
            for _, widget in widgets:
                widget.deleteLater()
            QCoreApplication.processEvents()
    assert not failures[:20]
    assert not errors.messages()
