"""Game info of LMU Rest API: chat widget, contacts (black box event log, game replays page),
pit lane entry (race plan widget), setup name (laps), replays saved by game"""

import os
from importlib import import_module
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tests.test_dialog_pages import window  # noqa: F401 (window: fixture)
from tinypedal.adapter import lmu_restapi
from tinypedal.api_control import api
from tinypedal.process import game_info
from tinypedal.setting import cfg

CHAT = [
    {"message": "M Toit: Leaving pits", "timestamp": 17911691634142719},
    {"message": "M Toit: Go Left", "timestamp": 17911691624658497},
    {"message": "", "timestamp": 17911691634142800},  # empty: left out
    {"timestamp": 1},  # no message: left out
]
CONTACTS = [
    {"contactWith": "Kevin Ramirez", "et": 1777.99, "player": "Zaac Latta"},
    {"contactWith": "Immovable", "et": 1601.79, "player": "Gabe Poblete"},
    {"contactWith": "Zaac Latta", "et": 1776.74, "player": "Kevin Ramirez"},
    {"et": "x"},
]
REPLAYS = [
    {"id": 0, "replayName": "Algarve P1 1", "size": 66644097, "timestamp": 1791165314,
     "metadata": {"eventTitle": "Daily Q1", "sceneDesc": "PORTIMAOWEC", "session": "PRACTICE"}},
    {"id": 1, "replayName": "Bahrain R1", "size": 1048576, "timestamp": 1791169000, "metadata": {}},
    "bad",
]
STANDINGS = [{"driverName": "Zaac Latta", "slotID": 4}, {"driverName": "Kevin Ramirez", "slotID": 7}, {}]


# --- Parsers
def test_parse_chat_oldest_first():
    messages = game_info.parse_chat(CHAT, ())
    assert [message.text for message in messages] == ["M Toit: Go Left", "M Toit: Leaving pits"]
    assert messages[0].time == pytest.approx(1791169162.4658497)
    assert game_info.parse_chat(None, ()) == ()


def test_parse_contacts_and_player_contacts():
    contacts = game_info.parse_contacts(CONTACTS, ())
    assert [contact.time for contact in contacts] == [1601.79, 1776.74, 1777.99]
    assert contacts[0] == game_info.Contact(1601.79, "Gabe Poblete", game_info.IMMOVABLE)
    assert game_info.player_contacts(contacts, "Zaac Latta") == [(1776.74, "Kevin Ramirez"), (1777.99, "Kevin Ramirez")]
    assert game_info.player_contacts(contacts, "Gabe Poblete") == [(1601.79, game_info.IMMOVABLE)]
    assert game_info.parse_contacts({"status": "unavailable"}, ()) == ()


def test_distance_ahead_wraps_lap():
    assert game_info.distance_ahead(4902.0, 4500.0, 5412.0) == pytest.approx(402.0)
    assert game_info.distance_ahead(4902.0, 5000.0, 5412.0) == pytest.approx(5314.0)  # next lap
    assert game_info.distance_ahead(-1.0, 100.0, 5412.0) == -1.0
    assert game_info.distance_ahead(6000.0, 100.0, 5412.0) == -1.0  # not on this track
    assert game_info.parse_distance(4902.05, -1.0) == 4902.05
    assert game_info.parse_distance(True, -1.0) == -1.0 and game_info.parse_distance(0, -1.0) == -1.0


def test_parse_replays():
    replays = game_info.parse_replays(REPLAYS)
    assert [replay.id for replay in replays] == [1, 0]  # newest first
    assert replays[1] == game_info.GameReplay(0, "Algarve P1 1", "Daily Q1", "PRACTICE", "PORTIMAOWEC",
                                              1791165314.0, 66644097)
    assert game_info.parse_replays(None) == []
    # Game answers null for missing event title: no "None" shown
    replay = game_info.parse_replays([{"id": 3, "replayName": "Fuji Speedway P1 5", "replayDirectory": "C:\\R\\",
                                       "metadata": {"eventTitle": None, "eventType": "quick-race"}}])[0]
    assert (replay.event, replay.event_type, replay.folder, replay.time) == ("", "quick-race", "C:\\R\\", 0.0)


def test_replay_title():
    assert game_info.replay_title("Grand Prix of Long Beach R1 4") == ("Grand Prix of Long Beach", "R1 4")
    assert game_info.replay_title("Circuit de la Sarthe P1 16") == ("Circuit de la Sarthe", "P1 16")
    assert game_info.replay_title("Bahrain R1") == ("Bahrain R1", "")  # no file number: kept whole


def test_merge_contacts():
    contacts = game_info.parse_contacts([
        *CONTACTS,
        {"contactWith": "Kevin Ramirez", "et": 1779.5, "player": "Zaac Latta"},  # same cars, 1.5 s later
        {"contactWith": "Kevin Ramirez", "et": 1790.0, "player": "Zaac Latta"},  # same cars, later: new incident
        {"contactWith": "Immovable", "et": 1602.5, "player": "Gabe Poblete"},
    ], ())
    incidents = game_info.merge_contacts(contacts)
    assert incidents == (
        game_info.Incident(1601.79, "Gabe Poblete", game_info.IMMOVABLE, 2),
        game_info.Incident(1776.74, "Kevin Ramirez", "Zaac Latta", 3),  # both sides & repeat merged
        game_info.Incident(1790.0, "Zaac Latta", "Kevin Ramirez", 1),
    )
    assert game_info.merge_contacts(()) == ()


def test_parse_cars_focus_and_session_time():
    cars = game_info.parse_cars([{"driverName": "Zaac Latta", "slotID": 4, "carNumber": "7", "carClass": "Hypercar",
                                  "player": True}, {"driverName": "Kevin Ramirez", "slotID": "x"}, "bad"])
    assert cars == {"Zaac Latta": game_info.CarInfo(4, "Zaac Latta", "7", "Hypercar", True)}
    assert set(game_info.parse_cars(STANDINGS)) == {"Zaac Latta", "Kevin Ramirez"}
    assert game_info.parse_cars(None) == {}
    assert game_info.parse_focus(4) == 4 and game_info.parse_focus(-1) == -1
    assert game_info.parse_focus(True) == -1 and game_info.parse_focus("3") == -1
    assert game_info.parse_session_time({"currentEventTime": 1800.5}) == 1800.5
    assert game_info.parse_session_time({"currentEventTime": None}) == -1.0
    assert game_info.parse_session_time(None) == -1.0


# --- Rest API data & readers
def update_task(data, path: str, answer):
    task = next(task for task in lmu_restapi.lmu_restapi_tasks() if task.path == path)
    for output in task.outputs:
        output.update(data, answer)
    return task


def test_rest_tasks_and_readers():
    from tinypedal import api_connector

    sim = api_connector.SimLMU()
    data = sim._restapi_dataset
    assert update_task(data, "/rest/chat/", CHAT).condition == "enable_race_info"
    assert update_task(data, "/rest/watch/getIncidentsList/1", CONTACTS).repeated
    update_task(data, "/rest/sessions/GetGameState", {"PitEntryDist": 4902.05, "PitState": "NONE"})
    summary = update_task(data, "/rest/garage/summary", {"activeSetup": " Race Bahrain ", "unsavedChanges": True})
    assert summary.condition == "enable_garage_setup_info" and not summary.repeated
    read = sim.reader()
    assert read.session.chat_messages()[-1][1] == "M Toit: Leaving pits"
    assert read.session.contacts()[0][2] == game_info.IMMOVABLE
    assert read.lap.pit_entry_distance() == pytest.approx(4902.05)
    assert read.vehicle.setup_name() == "Race Bahrain" and read.vehicle.setup_modified()
    update_task(data, "/rest/sessions/GetGameState", {"status": "unavailable"})
    assert read.lap.pit_entry_distance() == -1.0
    from tinypedal.template.setting_api import API_DEFAULT

    assert API_DEFAULT["api_lmu"]["enable_race_info"]


# --- Chat widget
def test_chat_lines_wrap_hide_and_highlight():
    from tinypedal.widget.chat import chat_lines

    messages = ((100.0, "A: old message"), (170.0, "B: " + "word " * 12), (195.0, "C: new"))
    lines = chat_lines(messages, 200.0, 20, 5, 60.0, 10.0, False)
    assert [text for text, _ in lines][-1] == "C: new" and lines[-1][1]  # newest highlighted
    assert all(len(text) <= 20 for text, _ in lines)
    assert "A: old message" not in [text for text, _ in lines]  # older than 60 s
    assert not lines[0][1]
    assert len(chat_lines(messages, 200.0, 20, 2, 0.0, 0.0, False)) == 2  # newest lines kept
    assert len(chat_lines(messages, 200.0, 20, 9, 0.0, 0.0, False)) >= 4  # always shown
    timed = chat_lines(((200.0, "C: new"),), 200.0, 40, 3, 0.0, 0.0, True)
    assert timed[0][0].endswith(" C: new") and len(timed[0][0]) == len("12:34 C: new")


@pytest.mark.parametrize("modern", [False, True])
def test_chat_widget(ui_env, monkeypatch, modern):
    from tinypedal.widget._modern import create_widget

    cfg.user.config["overlay_style"]["overlay_theme"] = "Modern Dark" if modern else "Legacy Dark"
    cfg.user.setting["chat"]["number_of_lines"] = 3
    monkeypatch.setattr(api.read.session, "chat_messages",
                        lambda: tuple(game_info.parse_chat(CHAT, ())))
    widget = create_widget(import_module("tinypedal.widget.chat"), cfg, "chat")
    widget.max_duration = 0  # sample messages are old
    widget.timerEvent(None)
    if modern:  # sender & message apart
        shown = [f"{line.name}: {line.text}" for line in widget.state]
    else:
        shown = [bar.text.strip() for bar in widget.bars if not bar.isHidden()]
    assert shown == ["M Toit: Go Left", "M Toit: Leaving pits"]
    widget.deleteLater()


# --- Black box contact events
def test_black_box_contact_events(monkeypatch):
    from tinypedal.widget._black_box.reader import DataReader
    from tinypedal.widget._black_box.recorder import EventLog

    state = {"elapsed": 1780.0, "contacts": game_info.parse_contacts(CONTACTS, ())}
    monkeypatch.setattr(api, "read", SimpleNamespace(
        session=SimpleNamespace(elapsed=lambda: state["elapsed"], contacts=lambda: state["contacts"]),
        vehicle=SimpleNamespace(driver_name=lambda: "Zaac Latta"),
        lap=SimpleNamespace(number=lambda: 12),
    ))
    reader = SimpleNamespace(
        event_log=EventLog(5), event_labels={"contact": "CONTACT", "wall": "WALL"},
        contacts_seen=(), contacts_logged={}, contacts_session_time=0.0,
    )
    DataReader.update_contact_events(reader)  # type: ignore[arg-type]
    # Both contacts with the same car within 2 seconds: logged once, at first contact time
    assert [(event.lap, event.session_time, event.text) for event in reader.event_log.events] == [
        (12, 1776.74, "CONTACT Kevin Ramirez")]
    DataReader.update_contact_events(reader)  # type: ignore[arg-type]  # same list: nothing new
    assert len(reader.event_log.events) == 1
    state["contacts"] = (*state["contacts"], game_info.Contact(1781.0, "Zaac Latta", game_info.IMMOVABLE))
    state["elapsed"] = 1782.0
    DataReader.update_contact_events(reader)  # type: ignore[arg-type]
    assert reader.event_log.events[-1].text == "WALL"
    # Contacts long over when first seen (widget started later): not logged
    late = SimpleNamespace(event_log=EventLog(5), event_labels=reader.event_labels,
                           contacts_seen=(), contacts_logged={}, contacts_session_time=0.0)
    state["elapsed"] = 3000.0
    DataReader.update_contact_events(late)  # type: ignore[arg-type]
    assert not late.event_log.events


# --- Race plan: pit lane entry
def test_race_plan_pit_entry(monkeypatch):
    from tinypedal.widget import race_plan

    monkeypatch.setattr(api, "read", SimpleNamespace(lap=SimpleNamespace(
        pit_entry_distance=lambda: 4902.0, distance=lambda: 4500.0, track_length=lambda: 5412.0)))
    assert race_plan.pit_entry_ahead() == pytest.approx(402.0)
    assert race_plan.distance_text(402.0, "Meter") == "402m"
    assert race_plan.distance_text(402.0, "Kilometer") == "0.40km"
    assert race_plan.distance_text(402.0, "Feet") == "1319ft"
    assert race_plan.distance_text(-1.0, "Meter") == "--"


# --- Setup name with laps
def test_lap_info_setup_name(monkeypatch):
    from tinypedal.module import module_recorder
    from tinypedal.ui.quick.lap_backend import setup_text

    vehicle = SimpleNamespace(setup=lambda: ("a=1",), setup_name=lambda: "Race Bahrain", setup_modified=lambda: True)
    monkeypatch.setattr(api, "read", SimpleNamespace(vehicle=vehicle))
    info = module_recorder.lap_info("lap", [])
    assert info["setup_name"] == "Race Bahrain" and info["setup_modified"] is True and info["setup"]
    assert setup_text(info) == f"Race Bahrain* ({info['setup']})"
    assert setup_text({"setup": "abcd1234"}) == "abcd1234"
    assert setup_text({"setup_name": "Quali"}) == "Quali"


# --- Game replays page (Qt Quick)
TRACKMAP = [{"type": 0, "x": x, "y": 0.0, "z": z} for x, z in ((0, 0), (500, 0), (500, 400), (0, 400), (0, 10))] + [
    {"type": 1, "x": 10, "y": 0, "z": 20}, {"type": 1, "x": 200, "y": 0, "z": 20}]
GAME_ANSWERS = {
    "/rest/watch/replays": REPLAYS, "/rest/replay/isActive": True, "/rest/watch/getIncidentsList/1": CONTACTS,
    "/rest/watch/standings": [
        {"driverName": "Zaac Latta", "slotID": 4, "carNumber": "7", "carClass": "Hypercar", "player": True,
         "position": 2, "lapsCompleted": 11, "bestLapTime": 99.25, "lastLapTime": 0, "lapsBehindLeader": 1,
         "pitState": "STOPPED", "fullTeamName": "Team Z", "carPosition": {"x": 120.0, "y": 0, "z": 50.0}},
        {"driverName": "Kevin Ramirez", "slotID": 7, "position": 1, "carClass": "LMP2", "lapsCompleted": 12,
         "bestLapTime": 101.5, "lastLapTime": 102.25, "pitstops": 1, "hasFocus": True,
         "vehicleName": "Oreca 07", "finishStatus": "FSTAT_FINISHED", "carPosition": {"x": 300.0, "y": 0, "z": 400.0}},
        {"driverName": "Kevin Ramirez", "slotID": 9, "position": 3, "carClass": "LMP2", "inGarageStall": True,
         "pitting": True, "pitState": "EXITING"},  # same name, other car (team entries)
    ],
    "/rest/watch/focus": 7, "/rest/watch/sessionInfo": {"currentEventTime": 1800.0, "endEventTime": 3600.0,
                                                        "trackName": "Circuit de la Sarthe", "session": "RACE1"},
    "/rest/replay/CameraController/getCameraInfo": {"cameraName": "TRACKING021", "currentCameraGroup": "TracksideCycle"},
    "/rest/hud": {"chat": True, "mfd": True, "speedo": False},
    "/rest/watch/trackmap": TRACKMAP,
}


class FakeGame:
    """Game Rest API of tests: answers by resource, commands recorded (accepted)"""

    def __init__(self):
        self.answers: dict = {}
        self.sent: list = []
        self.asked: list = []
        self.refused: set = set()

    def connection(self, *args, **kwargs):
        game = self

        class Connection:
            failed = False

            def __init__(self):
                self.answered = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, resource):
                game.asked.append(resource)
                self.answered = bool(game.answers)
                return game.answers.get(resource)

            def send(self, method, resource, body=None):
                game.sent.append((method, resource) if body is None else (method, resource, body))
                return resource not in game.refused

        return Connection()


@pytest.fixture
def replays_page(ui_env, monkeypatch):
    from tinypedal.ui import game_replays, game_rest
    from tinypedal.ui._common import BaseDialog

    game = FakeGame()
    monkeypatch.setattr(BaseDialog, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(game_rest, "GameConnection", game.connection)
    page = game_replays.GameReplays(None)
    page.game = game
    page.sent = game.sent
    yield page
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_requests(*requests, timeout=5.0):
    import time

    end = time.monotonic() + timeout
    while any(request.busy for request in requests) and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert not any(request.busy for request in requests)


def wait_commands(backend, timeout=5.0):
    """Queued commands sent one batch after another"""
    import time

    end = time.monotonic() + timeout
    while (backend.command_queue or backend.request_command.busy) and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert not backend.command_queue and not backend.request_command.busy


def answered(page, answers: dict, monkeypatch=None):
    page.game.answers = answers
    page.backend.refresh()
    wait_requests(page.backend.request_replays, page.backend.request_state)
    return page.backend


def test_game_replays_page(replays_page):
    backend = replays_page.backend
    assert not backend.replayActive and backend.gameState == "offline"
    answered(replays_page, GAME_ANSWERS)
    assert backend.gameState == "replay" and backend.replayActive
    assert backend.statusText == "Replay open in game" and backend.updatedText.startswith("Updated from game at")
    # Replays: newest first, game code of name, selection of first
    rows = backend.replayRows.rows
    assert [row["track"] for row in rows] == ["Bahrain R1", "Algarve"]
    assert rows[1]["code"] == "P1 1" and rows[1]["sessionLabel"] == "Practice" and rows[1]["size"] == "64 MB"
    assert backend.selectedReplay == "Bahrain R1" and backend.replaysSummary == "2 · 65 MB"
    assert backend.replayIndex("Algarve P1 1") == 1 and backend.replayIndex("x") == -1
    # Incidents: both sides of a contact merged, cars & player from standings, camera car by slot
    assert backend.counts == {"all": 2, "cars": 1, "walls": 1, "mine": 1, "shown": 2}
    incidents = backend.incidentRows.rows
    assert incidents[1]["driver"] == "Kevin Ramirez" and incidents[1]["other"] == "Zaac Latta"
    assert incidents[1]["count"] == 2 and incidents[1]["mine"] and incidents[1]["otherCar"] == "#7 · Hypercar"
    assert incidents[1]["focused"] == "driver" and backend.focusedDriver == "Kevin Ramirez"
    assert incidents[0]["wall"] and incidents[0]["other"] == "Wall"
    assert backend.incidentIndex(incidents[1]["key"]) == 1
    assert backend.playerName == "Zaac Latta" and backend.drivers[0] == {
        "name": "Gabe Poblete", "count": 1, "mine": False, "car": ""}  # same count: by name
    assert backend.drivers[2]["mine"] and backend.drivers[2]["car"] == "#7 · Hypercar"
    # Replay time (no lap timing in standings: session info), session length on timeline
    assert backend.replayTime == 1800.0 and backend.sessionEnd == 3600.0
    assert len(backend.timeline["markers"]) == 2 and backend.timeline["end"] == pytest.approx(3600.0)
    # Watch replay (id looked up by name when sent), playback, camera car, timeline seek, jump
    backend.watchReplay("Algarve P1 1")
    backend.playback("VCRCOMMAND_PLAY")
    backend.focusCar(1)
    backend.seek(1200.4)
    backend.setSecondsBefore(5)
    backend.jumpTo(incidents[1]["key"], "")
    backend.jumpTo(incidents[1]["key"], "Zaac Latta")
    wait_commands(backend)
    assert replays_page.sent == [
        ("GET", "/rest/watch/play/0"),
        ("PUT", "/rest/watch/replayCommand/VCRCOMMAND_PLAY"),
        ("PUT", "/rest/watch/focusForward"),
        ("PUT", "/rest/watch/replaytime/1200"),
        ("PUT", "/rest/watch/focus/4"), ("PUT", "/rest/watch/replaytime/1771"),
        ("PUT", "/rest/watch/focus/4"), ("PUT", "/rest/watch/replaytime/1771"),
    ]
    assert backend.lastCommand == "VCRCOMMAND_PLAY"
    backend.togglePlay()  # playing: pause
    assert backend.lastCommand == "VCRCOMMAND_STOP"
    assert [mode["command"] for mode in backend.playbackModes][-1] == "VCRCOMMAND_FORWARDSCANFAST"


def test_game_replays_replay_time_from_standings(replays_page):
    from tinypedal.process import game_info as info

    cars = info.parse_standings([
        {"driverName": "A", "slotID": 1, "lapStartET": 600.0, "timeIntoLap": 12.5},
        {"driverName": "B", "slotID": 2, "lapStartET": 590.0, "timeIntoLap": 22.0},
        {"driverName": "C", "slotID": 3, "lapStartET": 0.0, "timeIntoLap": -1.0},  # unknown: left out
    ])
    assert info.standings_time(cars) == 612.5 and info.standings_time([]) == -1.0
    answers = dict(GAME_ANSWERS)
    answers["/rest/watch/standings"] = [{"driverName": "A", "slotID": 1, "lapStartET": 600.0, "timeIntoLap": 12.5}]
    backend = answered(replays_page, answers)
    assert backend.replayTime == 612.5  # replay frame time, not session info


def test_game_replays_filters(replays_page):
    from tinypedal.ui.quick import replays_backend

    backend = answered(replays_page, GAME_ANSWERS)
    algarve, bahrain = "Algarve P1 1", "Bahrain R1"
    backend.setSearch("algarve daily")
    assert [row["key"] for row in backend.replayRows.rows] == [algarve] and backend.selectedReplay == algarve
    assert backend.replaysSummary == "1 / 2 · 64 MB"
    backend.setSearch("")
    backend.setSessionFilter(1)  # practice
    assert [row["key"] for row in backend.replayRows.rows] == [algarve]
    backend.setSessionFilter(0)
    backend.setSort("size")
    assert [row["key"] for row in backend.replayRows.rows] == [algarve, bahrain]
    assert backend.replayRows.rows[0]["section"] == ""
    backend.setSort("date")
    assert backend.replayRows.rows[0]["section"]  # day of replay
    backend.moveReplaySelection(-1)
    assert backend.selectedReplay == bahrain
    # Several replays: Ctrl adds / removes, Shift selects range, all, filtered out: no longer selected
    backend.clickReplay(algarve, replays_backend.CTRL)
    assert backend.checkedCount == 2 and backend.checkedSummary == "2 · 65 MB"
    assert [row["checked"] for row in backend.replayRows.rows] == [True, True]
    backend.clickReplay(bahrain, replays_backend.CTRL)
    assert backend.checked == {algarve} and backend.selectedReplay == bahrain
    backend.clickReplay(algarve, replays_backend.SHIFT)
    assert backend.checked == {algarve, bahrain}
    backend.selectReplay(bahrain)
    backend.selectAllReplays()
    assert backend.checkedCount == 2
    backend.setSearch("bahrain")
    assert backend.checked == {bahrain}
    backend.setSearch("")
    # Incidents: kind, my car, driver (same driver again: all)
    backend.setIncidentFilter(2)  # walls
    assert [row["driver"] for row in backend.incidentRows.rows] == ["Gabe Poblete"]
    backend.setIncidentFilter(0)
    backend.setMineOnly(True)
    assert [row["driver"] for row in backend.incidentRows.rows] == ["Kevin Ramirez"]
    backend.setMineOnly(False)
    backend.setDriverFilter("Gabe Poblete")
    assert backend.counts["shown"] == 1 and not backend.timeline["markers"][1]["shown"]
    backend.setDriverFilter("Gabe Poblete")
    assert backend.counts["shown"] == 2
    backend.jumpNext(1)  # first incident selected, replay goes there (car not in standings: camera kept)
    wait_commands(backend)
    assert backend.selectedIncident == backend.incidentRows.rows[0]["key"]
    assert replays_page.sent == [("PUT", "/rest/watch/replaytime/1596")]


def test_game_replays_page_game_states(replays_page, monkeypatch):
    from tinypedal.ui.quick import replays_backend

    backend = answered(replays_page, {})  # nothing answers
    assert backend.gameState == "offline" and backend.replayCount == 0 and backend.statusText
    # Game in menus: replays listed, no session (focus answers -1 outside sessions)
    answered(replays_page, {"/rest/watch/replays": REPLAYS, "/rest/watch/focus": -1})
    assert backend.gameState == "menu" and backend.replayCount == 2 and not backend.inSession
    backend.playback("VCRCOMMAND_PLAY")  # no replay open: nothing sent
    backend.jumpTo("x", "")
    assert replays_page.sent == []
    # In session, no replay open
    answered(replays_page, {"/rest/watch/replays": REPLAYS, "/rest/replay/isActive": False,
                            "/rest/watch/getIncidentsList/1": CONTACTS, "/rest/watch/standings":
                                GAME_ANSWERS["/rest/watch/standings"]})
    assert backend.gameState == "session" and backend.inSession and backend.replayTime == -1.0
    # Session left: its incidents & standings kept (last session), no jump; replays list asked again
    monkeypatch.setattr(replays_backend, "SESSION_END_DELAY_MS", 0)
    asked = len([resource for resource in replays_page.game.asked if resource == "/rest/watch/replays"])
    replays_page.game.answers = {"/rest/watch/replays": REPLAYS, "/rest/watch/focus": -1}
    backend.refresh_state()
    wait_requests(backend.request_state)
    for _ in range(5):
        QCoreApplication.processEvents()
    wait_requests(backend.request_replays)
    assert backend.gameState == "menu" and backend.lastSession and backend.counts["all"] == 2 and backend.carCount == 3
    assert len([resource for resource in replays_page.game.asked if resource == "/rest/watch/replays"]) == asked + 1
    backend.jumpTo(backend.incidentRows.rows[0]["key"], "")
    assert replays_page.sent == []


def test_game_replays_page_shown_asks_game(replays_page):
    replays_page.show()
    wait_requests(replays_page.backend.request_replays, replays_page.backend.request_state)
    # Game not running: replays list & folder, replay state, no incidents or standings asked
    assert sorted(replays_page.game.asked) == ["/rest/replay/isActive", "/rest/watch/focus",
                                               "/rest/watch/replay/getReplayFolder", "/rest/watch/replays"]
    assert replays_page.backend._timer.isActive()  # asked again later while shown
    replays_page.hide()
    assert not replays_page.backend._timer.isActive()


def test_game_replays_standings_asked_when_needed(replays_page):
    answers = dict(GAME_ANSWERS, **{"/rest/replay/isActive": False})  # live session
    backend = answered(replays_page, answers)
    asked = replays_page.game.asked
    asked.clear()
    backend.refresh_state()
    wait_requests(backend.request_state)
    assert "/rest/watch/standings" not in asked  # same contacts: cars known (Gabe not in standings, looked up once)
    answers["/rest/watch/getIncidentsList/1"] = CONTACTS[:2]  # another session: contacts changed
    backend.refresh_state()
    wait_requests(backend.request_state)
    assert asked.count("/rest/watch/standings") == 1 and backend.counts["all"] == 2


def test_game_replays_standings_and_camera(replays_page):
    import json

    backend = answered(replays_page, GAME_ANSWERS)
    # Standings by position, class position, laps & times, gap, status, camera car (slot), incidents
    rows = backend.standingRows.rows
    assert [row["driver"] for row in rows] == ["Kevin Ramirez", "Zaac Latta", "Kevin Ramirez"] and backend.carCount == 3
    kevin, zaac, kevin_other = rows
    assert (kevin["position"], kevin["classPosition"], kevin["laps"], kevin["best"], kevin["last"]) == (
        1, 1, 12, "1:41.500", "1:42.250")
    assert kevin["gap"] == "" and kevin["status"] == "Finished" and kevin["statusTone"] == "gain"
    assert kevin["onCamera"] and not kevin_other["onCamera"]  # same name: camera by slot
    assert kevin["fastest"] and kevin["incidents"] == 1 and kevin["vehicle"] == "Oreca 07"
    assert zaac["gap"] == "+1 Lap" and zaac["status"] == "In Pits" and zaac["last"] == "-"
    assert kevin_other["status"] == "Garage" and kevin_other["statusTone"] == "dim"
    assert zaac["player"] and zaac["number"] == "7" and zaac["vehicle"] == "Team Z" and zaac["classPosition"] == 1
    assert [car["name"] for car in backend.classes] == ["LMP2", "Hypercar"]
    assert backend.classes[1]["color"] == "#FF4400"  # vehicle class editor color
    backend.setClassFilter("Hypercar")
    assert [row["driver"] for row in backend.standingRows.rows] == ["Zaac Latta"]
    backend.setClassFilter("Hypercar")  # same class again: all
    assert backend.standingRows.rows[0]["driver"] == "Kevin Ramirez" and backend.carIndex("4") == 1
    backend.showDriverIncidents("Zaac Latta")
    assert backend.panelIndex == 0 and backend.driverFilter == "Zaac Latta" and backend.counts["shown"] == 1
    # Camera: group reported by game, angles of a group, car of standings; HUD
    assert backend.cameraGroup == "Trackside" and backend.cameraName == "TRACKING021"
    assert backend.hudShown and [part["key"] for part in backend.hudComponents] == ["chat", "mfd", "speedo"]
    backend.setCamera("Onboard", -1)
    backend.setCamera("Driving", 1)
    backend.setCamera("Unknown", 1)  # not a group: nothing sent
    backend.watchCar("4")
    backend.toggleHudComponent("speedo")
    backend.setHudShown(False)
    wait_commands(backend)
    assert replays_page.sent == [
        ("POST", "/rest/replay/CameraController/setCamera", json.dumps({"cameraGroup": "Onboard", "direction": -1})),
        ("POST", "/rest/replay/CameraController/setCamera", json.dumps({"cameraGroup": "Driving", "direction": 1})),
        ("PUT", "/rest/watch/focus/4"),
        ("POST", "/rest/hud/toggle/speedo"),
        ("POST", "/rest/hud/toggleAllComponents/false"), ("POST", "/rest/sessions/setHudOnWatchScreen", "false"),
        ("POST", "/rest/watch/replay/setReplayUIVisible", "false"),
    ]
    assert backend.selectedCar == "4"


def test_game_replays_map(replays_page):
    backend = replays_page.backend
    backend.setPanel(2)
    answered(replays_page, GAME_ANSWERS)
    view = backend.mapView
    assert view["minX"] == 0 and view["maxX"] == 500 and view["minY"] == -400 and view["maxY"] == 0  # x, -z
    from tinypedal.ui.quick.lines import VertexStore

    assert VertexStore.has(view["road"]) and VertexStore.has(view["pit"])
    cars = {row["key"]: row for row in backend.mapCars.rows}
    assert (cars["7"]["mapX"], cars["7"]["mapY"], cars["7"]["onCamera"]) == (300.0, -400.0, True)
    assert cars["4"]["player"] and cars["4"]["inPit"] and "9" not in cars  # no position: not on map
    asked = replays_page.game.asked
    asked.clear()
    backend.refresh_state()
    wait_requests(backend.request_state)
    assert "/rest/watch/trackmap" not in asked  # same track: map kept
    revision = backend.mapRevision
    backend.setMapScale(5.0)
    assert backend.mapRevision == revision + 1
    backend.release()
    assert not VertexStore.has(view["road"])


def test_game_replays_live_rewatch(replays_page, monkeypatch):
    """Live session: jump opens the replay of the session (toggle read first), back to live later"""
    import time

    from tinypedal.ui.quick import replays_backend

    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    answers = dict(GAME_ANSWERS, **{"/rest/replay/isActive": False})
    backend = answered(replays_page, answers)
    game = replays_page.game
    original_send = game.connection

    def connection():  # replay opens once toggled
        link = original_send()
        send = link.send

        def sending(method, resource, body=None):
            if resource == replays_backend.TOGGLE_REPLAY_RESOURCE:
                answers["/rest/replay/isActive"] = not answers["/rest/replay/isActive"]
            return send(method, resource, body)
        link.send = sending
        return link

    from tinypedal.ui import game_rest

    monkeypatch.setattr(game_rest, "GameConnection", connection)
    key = backend.incidentRows.rows[1]["key"]
    backend.jumpTo(key, "")
    wait_commands(backend)
    backend.refresh_state()  # page not shown: state asked by test
    wait_requests(backend.request_state)
    assert game.sent == [("POST", "/rest/replay/toggleactive"), ("PUT", "/rest/watch/focus/4"),
                         ("PUT", "/rest/watch/replaytime/1771")]
    assert backend.gameState == "replay" and backend.canGoLive
    backend.backToLive()
    wait_commands(backend)
    assert game.sent[-1] == ("POST", "/rest/replay/toggleactive") and not backend.canGoLive


def test_game_replays_go_to_lap(monkeypatch):
    """Lap start found from lap times of car, replay moved until car is in that lap"""
    import time

    from tinypedal.ui.quick import replays_backend

    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    state = {"time": 950.0}
    sent: list = []

    class Connection:
        def get(self, resource):
            now = state["time"]
            return [{"driverName": "A", "slotID": 3, "lapsCompleted": int(now // 100), "lapStartET": now // 100 * 100,
                     "timeIntoLap": now % 100, "lastLapTime": 100.0}]

        def send(self, method, resource, body=None):
            sent.append(resource)
            if "replaytime" in resource:
                state["time"] = float(resource.rsplit("/", 1)[1])
            return True

    assert replays_backend.go_to_lap(3, 4, 5)(Connection())  # lap 4: 300 to 400
    assert sent[0] == "/rest/watch/focus/3" and sent[-1] == "/rest/watch/replaytime/295"
    assert not replays_backend.go_to_lap(8, 4, 5)(Connection())  # car not in standings


def test_replay_files_copy(tmp_path, monkeypatch):
    import threading

    from tinypedal.ui.quick import replay_files

    folder, source = tmp_path / "Replays", tmp_path / "Downloads"
    folder.mkdir()
    source.mkdir()
    (folder / "Spa R1 1.Vcr").write_bytes(b"old")
    (source / "Spa R1 1.Vcr").write_bytes(b"x" * 1000)  # same name: numbered
    (source / "Fuji P1 2.vcr").write_bytes(b"y" * 3000)
    (source / "notes.txt").write_text("not a replay")
    progress: list[float] = []
    added, errors, cancelled = replay_files.copy_replays(
        [str(path) for path in source.iterdir()] + [str(folder / "Spa R1 1.Vcr")], str(folder), progress.append)
    assert sorted(added) == ["Fuji P1 2", "Spa R1 1 (2)"] and errors == [] and not cancelled
    assert (folder / "Spa R1 1 (2).Vcr").read_bytes() == b"x" * 1000 and (folder / "Spa R1 1.Vcr").read_bytes() == b"old"
    assert progress[-1] == 1.0 and progress == sorted(progress)
    assert not list(folder.glob("*.part"))
    assert replay_files.free_name(str(folder), "Spa R1 1") == "Spa R1 1 (3)"
    # Cancelled: nothing left, not enough disk space: nothing copied
    stop = threading.Event()
    stop.set()
    result = replay_files.copy_replays([str(source / "Fuji P1 2.vcr")], str(tmp_path), progress.append, stop)
    assert result.cancelled and not list(tmp_path.glob("Fuji*"))
    real = replay_files.shutil.disk_usage
    monkeypatch.setattr(replay_files.shutil, "disk_usage", lambda path: real(path)._replace(free=100))
    result = replay_files.copy_replays([str(source / "Fuji P1 2.vcr")], str(tmp_path), progress.append)
    monkeypatch.undo()
    assert not result.added and "not enough free space" in result.errors[0]
    # Rename, temporary files of game (old ones only)
    assert replay_files.rename_replay(str(folder), "Fuji P1 2", "Fuji race") == ""
    assert (folder / "Fuji race.Vcr").exists()
    assert replay_files.rename_replay(str(folder), "Fuji race", "Spa R1 1") == "name already used"
    assert replay_files.rename_replay(str(folder), "Fuji race", "a/b") == "invalid name"
    (folder / "_vcr123.tmp").write_bytes(b"t")
    assert replay_files.temp_files(str(folder)) == []  # being recorded maybe
    assert [os.path.basename(path) for path in replay_files.temp_files(str(folder), now=4e9)] == ["_vcr123.tmp"]


def test_game_replays_add_and_delete(replays_page, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tinypedal.ui.quick import replay_files, replays_backend

    backend = answered(replays_page, GAME_ANSWERS)
    assert backend.replayFolder == ""  # game gave no replay folder: files cannot be added
    backend.add_files([])
    assert backend.noticeError and "Replay folder unknown" in backend.noticeText
    folder = tmp_path / "Replays"
    folder.mkdir()
    for name in ("Algarve P1 1", "Bahrain R1"):
        (folder / f"{name}.Vcr").write_bytes(b"replay")
    # Replay folder told by game (known without replay)
    answers = dict(GAME_ANSWERS, **{"/rest/watch/replay/getReplayFolder": {"custom": "", "default": str(folder)}})
    answered(replays_page, answers)
    assert backend.replayFolder == str(folder)
    # Add: copied in background, list asked again to game
    new = tmp_path / "Monza R1 3.Vcr"
    new.write_bytes(b"z" * 100)
    backend.addFiles([new.as_uri(), (tmp_path / "x.txt").as_uri()])
    wait_requests(backend.request_copy)
    assert (folder / "Monza R1 3.Vcr").exists() and not backend.copying
    assert backend.noticeText == "1 replay(s) added to the game replay folder" and not backend.noticeError
    wait_requests(backend.request_replays)
    backend.addFiles([(tmp_path / "x.txt").as_uri()])
    assert backend.noticeError
    # Export to a folder chosen in a dialog
    export = tmp_path / "Export"
    export.mkdir()
    monkeypatch.setattr(replays_backend.QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(export))
    backend.exportReplays("Algarve P1 1")
    wait_requests(backend.request_copy)
    assert (export / "Algarve P1 1.Vcr").exists() and backend.noticeText == "1 replay(s) exported"
    # Protect: kept by delete & clean up, remembered
    backend.toggleProtected("Algarve P1 1")
    assert backend.replayRows.rows[1]["isProtected"] and backend.folderInfo["protected"] == 1
    assert replays_backend.load_page_settings()["protected"] == ["Algarve P1 1"]
    # Delete: selected replays to the recycle bin, after confirmation, protected one kept
    trashed: list[str] = []
    monkeypatch.setattr(replay_files, "QFile", SimpleNamespace(
        moveToTrash=lambda path: trashed.append(os.path.basename(path)) or os.remove(path) is None))
    backend.selectReplay("Bahrain R1")
    backend.clickReplay("Algarve P1 1", replays_backend.SHIFT)
    backend.deleteReplays("Algarve P1 1")
    assert trashed == ["Bahrain R1.Vcr"]
    assert backend.noticeText == "1 replay(s) moved to the recycle bin · 1 protected replay(s) kept"
    assert sorted(path.name for path in folder.iterdir()) == ["Algarve P1 1.Vcr", "Monza R1 3.Vcr"]
    wait_requests(backend.request_replays)
    # Rename: file renamed, protection follows
    monkeypatch.setattr(replays_backend.QInputDialog, "getText", lambda *args, **kwargs: ("Algarve best", True))
    backend.renameReplay("Algarve P1 1")
    assert (folder / "Algarve best.Vcr").exists() and backend.protected == {"Algarve best"}
    wait_requests(backend.request_replays)
    # Clean up: older than, latest kept (protected kept), temporary files
    backend.replays = [replays_backend.GameReplay(0, "Monza R1 3", "", "", "", 1.0, 100),
                       replays_backend.GameReplay(1, "Algarve best", "", "", "", 2.0, 100)]
    monkeypatch.setattr(replays_backend.QInputDialog, "getInt", lambda *args, **kwargs: (30, True))
    backend.deleteOlderThan()
    assert "Monza R1 3.Vcr" in trashed and "Algarve best.Vcr" not in trashed
    (folder / "_vcr1.tmp").write_bytes(b"t" * 10)
    os.utime(folder / "_vcr1.tmp", (1, 1))
    backend.deleteTempFiles()
    assert "_vcr1.tmp" in trashed and backend.noticeText == "1 temporary file(s) moved to the recycle bin"
    # Refused by system (file open in game): left in place, told
    monkeypatch.setattr(replay_files, "QFile", SimpleNamespace(moveToTrash=lambda path: False))
    backend.toggleProtected("Algarve best")
    backend.deleteReplays("Algarve best")
    assert backend.noticeError and "Algarve best.Vcr" in backend.noticeText


def test_game_replays_incidents_export(replays_page, monkeypatch, tmp_path):
    from PySide6.QtGui import QGuiApplication

    from tinypedal.ui.quick import replays_backend

    backend = answered(replays_page, GAME_ANSWERS)
    backend.copyIncidents()
    text = QGuiApplication.clipboard().text()
    assert text.splitlines()[0] == "Time\tDriver\tCar\tContact With\tCar\tContacts"
    assert text.splitlines()[2] == "0:29:36\tKevin Ramirez\tLMP2\tZaac Latta\t#7 · Hypercar\t2"
    target = tmp_path / "incidents.csv"
    monkeypatch.setattr(replays_backend.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    backend.exportIncidents()
    assert target.read_text(encoding="utf-8-sig").splitlines()[1] == "0:26:41,Gabe Poblete,,Wall,,1"
    assert backend.noticeText == "2 incident(s) exported"


def test_game_replays_settings_kept(replays_page):
    from tinypedal.ui.quick.replays_backend import GameReplaysBackend

    backend = replays_page.backend
    backend.setSecondsBefore(12)
    backend.setPanel(1)
    backend.setSort("size")
    backend.setSessionFilter(3)
    backend.setIncidentFilter(1)
    again = GameReplaysBackend(replays_page)
    assert (again.secondsBefore, again.panelIndex, again.sortKey, again.sessionFilter, again.incidentFilter) == (
        12, 1, "size", 3, 1)
    assert again._midnight.isActive()  # Today / Yesterday updated at midnight
    again.release()


def test_game_replays_french_messages():
    from tinypedal import i18n

    i18n.set_language("Français")
    try:
        assert i18n.trm("Move <b>3</b> replays (1,2 Go) to the recycle bin?") == "Mettre <b>3</b> rejeux (1,2 Go) à la corbeille ?"
        assert i18n.trm("Move replay <b>Spa R1 1</b> (182 Mo) to the recycle bin?") == (
            "Mettre le rejeu <b>Spa R1 1</b> (182 Mo) à la corbeille ?")
        assert i18n.trm("2 replay(s) moved to the recycle bin") == "2 rejeu(x) mis à la corbeille"
        assert i18n.trm("1 replay(s) added to the game replay folder") == "1 rejeu(x) ajouté(s) au dossier des rejeux du jeu"
        assert i18n.trm("Unable to delete (replay open in game?): a.Vcr").startswith("Impossible de supprimer")
        assert i18n.trm("Unable to rename: name already used") == "Impossible de renommer : nom déjà utilisé"
        assert i18n.trm("You are in a session: opening a replay may leave it.<br><br>Open replay <b>X</b> in the game?") == (
            "Vous êtes en session : ouvrir un rejeu peut la quitter.<br><br>Ouvrir le rejeu <b>X</b> dans le jeu ?")
        assert i18n.trm("Lap of Keenny Hess:") == "Tour de Keenny Hess :"
        assert i18n.tr("Trackside") == "Bord de piste" and i18n.tr("In Pits") == "Aux stands"
    finally:
        i18n.set_language("English")


def test_game_replays_qml_page(replays_page):
    from PySide6.QtCore import qInstallMessageHandler

    def texts_of(view) -> set:
        found, stack = set(), [view.rootObject()]
        while stack:
            item = stack.pop()
            text = item.property("text")
            if isinstance(text, str):
                found.add(text)
            stack.extend(item.childItems())
        return found

    def shown_texts(wanted: set) -> set:
        """Texts of page once wanted ones are shown (layout of a tab shown: some event loops)"""
        import time

        end = time.monotonic() + 3.0
        while True:
            QCoreApplication.processEvents()
            found = texts_of(replays_page.view)
            if wanted <= found or time.monotonic() > end:
                return found
            time.sleep(0.01)

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        assert not replays_page.view.errors(), [error.toString() for error in replays_page.view.errors()]
        answered(replays_page, GAME_ANSWERS)
        replays_page.resize(1400, 860)
        replays_page.show()
        for _ in range(10):
            QCoreApplication.processEvents()
        texts = texts_of(replays_page.view)
        assert "Algarve" in texts and "Incidents  2" in texts and "Replay open in game" in texts
        assert "Trackside · Cycle All" in texts and "Map" in texts  # camera shown as camera menu names it
        backend = replays_page.backend
        backend.setPanel(1)  # standings
        backend.clickReplay("Algarve P1 1", 0x04000000)  # 2 replays selected: selection bar
        texts = shown_texts({"Kevin Ramirez", "1:41.500", "Finished", "In Pits", "Garage", "Selected  2 · 65 MB"})
        assert {"Kevin Ramirez", "1:41.500", "Finished", "In Pits", "Garage", "Selected  2 · 65 MB"} <= texts
        backend.setPanel(2)  # map
        backend.refresh_state()
        wait_requests(backend.request_state)
        assert "7" in shown_texts({"7"})  # car number on map
        replays_page.resize(700, 860)  # narrow: one column
        for _ in range(5):
            QCoreApplication.processEvents()
    finally:
        qInstallMessageHandler(previous)
    qml = [text for text in messages if ".qml" in text]
    assert not qml, qml


def test_game_replays_practice_gap_energy_and_live_time(replays_page):
    """As the game shows it: practice gap = best lap behind best lap of leader, energy of own team cars,
    live session time"""
    standings = [
        {"driverName": "Y Lheritier", "slotID": 4, "position": 1, "lapsCompleted": 12, "bestLapTime": 206.32,
         "veFraction": 0.1255, "fuelFraction": 0.0, "timeBehindLeader": 0.0},
        {"driverName": "W Bils", "slotID": 7, "position": 2, "lapsCompleted": 3, "bestLapTime": 208.049,
         "veFraction": 0.69, "lapsBehindLeader": 9, "timeBehindLeader": 0.0},
        {"driverName": "K Hess", "slotID": 5, "position": 3, "lapsCompleted": 0, "bestLapTime": -1.0,
         "veFraction": 0.0, "fuelFraction": 0.0, "inGarageStall": True},
    ]
    backend = answered(replays_page, {
        "/rest/watch/replays": REPLAYS, "/rest/replay/isActive": False, "/rest/watch/getIncidentsList/1": [],
        "/rest/watch/standings": standings, "/rest/watch/focus": 7,
        "/rest/watch/sessionInfo": {"currentEventTime": 1809.0, "session": "PRACTICE1"},
    })
    backend.setPanel(1)
    backend.refresh_state()
    wait_requests(backend.request_state)
    rows = {row["driver"]: row for row in backend.standingRows.rows}
    assert rows["Y Lheritier"]["gap"] == "" and rows["W Bils"]["gap"] == "+1.729" and rows["K Hess"]["gap"] == "-"
    assert rows["Y Lheritier"]["energy"] == "13%" and rows["W Bils"]["energy"] == "69%"
    assert rows["K Hess"]["energy"] == "" and rows["K Hess"]["energyLevel"] == -1.0  # hidden (0 from game)
    assert backend.hasEnergy and backend.liveTime == 1809.0 and backend.replayTime == -1.0


def test_game_replays_lap_marks_and_steps(replays_page):
    """Lap starts of cars seen while replay plays: timeline marks of car followed by camera, lap steps"""
    answers = dict(GAME_ANSWERS)

    def standings(laps: int, start: float) -> list:
        return [{"driverName": "Kevin Ramirez", "slotID": 7, "position": 1, "lapsCompleted": laps,
                 "lapStartET": start, "timeIntoLap": 10.0, "lastLapTime": 100.0}]

    answers["/rest/watch/standings"] = standings(3, 300.0)
    backend = answered(replays_page, answers)
    answers["/rest/watch/standings"] = standings(4, 400.0)
    backend.refresh_state()
    wait_requests(backend.request_state)
    assert backend.lapMarks == [{"lap": 4, "time": 300.0}, {"lap": 5, "time": 400.0}] and backend.cameraLap == 5
    assert backend.replayTime == 410.0
    backend.stepLap(-1)  # lap 4 start seen: at once
    wait_commands(backend)
    assert replays_page.sent == [("PUT", "/rest/watch/replaytime/300")]


def test_game_replays_camera_menu(replays_page):
    """Cameras of game camera menu chosen directly (camera types seen live), check on camera shown"""
    from PySide6.QtCore import QMetaObject, QObject

    backend = answered(replays_page, GAME_ANSWERS)
    assert backend.cameraKey == "TRACKSIDE0" and backend.cameraLabel == "Trackside · Cycle All"
    assert [camera["key"] for camera in backend.cameras][:4] == ["COCKPIT", "SWINGMAN", "NOSECAM", "TVCOCKPIT"]
    assert backend.cameras[-1]["text"] == "Group 4" and backend.cameras[5]["text"] == "Cockpit"  # onboard cockpit
    backend.selectCamera("ONBOARD02")
    backend.selectCamera("TVCOCKPIT")  # no camera type: cockpit, then next driving camera
    backend.selectCamera("TRACKSIDE3")
    backend.selectCamera("nope")
    wait_commands(backend)
    assert replays_page.sent == [
        ("PUT", "/rest/watch/focus/9/0/false"),
        ("PUT", "/rest/watch/focus/1/0/false"),
        ("POST", "/rest/replay/CameraController/setCamera", '{"cameraGroup": "Driving", "direction": 1}'),
        ("PUT", "/rest/watch/focus/4/3/false"),
    ]
    # Game tells trackside group only for cycle: group chosen from page kept until another camera
    camera = {"cameraName": "TRACKING065", "currentCameraGroup": "Trackside"}
    replays_page.game.answers = dict(GAME_ANSWERS, **{"/rest/replay/CameraController/getCameraInfo": camera})
    backend.refresh_state()
    wait_requests(backend.request_state)
    assert backend.cameraKey == "TRACKSIDE3" and backend.cameraLabel == "Trackside · Group 3"
    backend.setCamera("Trackside", 1)
    assert backend.cameraKey == ""
    camera.update(cameraName="ONBOARD02", currentCameraGroup="Onboard")
    backend.refresh_state()
    wait_requests(backend.request_state)
    assert backend.cameraLabel == "Onboard · Dash Camera"
    replays_page.resize(1400, 860)
    replays_page.show()
    for _ in range(10):
        QCoreApplication.processEvents()
    dash = replays_page.view.rootObject().findChild(QObject, "camera_ONBOARD02")
    cockpit = replays_page.view.rootObject().findChild(QObject, "camera_COCKPIT")
    assert dash.property("checked") and not cockpit.property("checked")
    QMetaObject.invokeMethod(cockpit, "trigger")
    wait_commands(backend)
    assert replays_page.sent[-1] == ("PUT", "/rest/watch/focus/1/0/false")


def test_game_replays_hud_menu(replays_page):
    """HUD menu kept while trackside camera changes angle by itself, checks follow game"""
    from PySide6.QtCore import QMetaObject, QObject

    backend = answered(replays_page, GAME_ANSWERS)
    replays_page.resize(1400, 860)
    replays_page.show()
    for _ in range(10):
        QCoreApplication.processEvents()
    chat = replays_page.view.rootObject().findChild(QObject, "hud_chat")
    speedo = replays_page.view.rootObject().findChild(QObject, "hud_speedo")
    timing = replays_page.view.rootObject().findChild(QObject, "hud_timing")
    assert chat.property("checked") and not speedo.property("checked")
    assert not timing.property("enabled")  # not listed by game
    hud_changes, camera_changes = [], []
    backend.hudChanged.connect(lambda: hud_changes.append(1))
    backend.cameraChanged.connect(lambda: camera_changes.append(1))
    camera = dict(GAME_ANSWERS["/rest/replay/CameraController/getCameraInfo"], cameraName="TRACKING022")
    replays_page.game.answers = dict(GAME_ANSWERS, **{"/rest/replay/CameraController/getCameraInfo": camera})
    backend.refresh_state()
    wait_requests(backend.request_state)
    assert camera_changes and not hud_changes  # HUD menu not rebuilt
    QMetaObject.invokeMethod(chat, "trigger")  # chat hidden from menu
    QMetaObject.invokeMethod(speedo, "trigger")  # speedometer shown
    QCoreApplication.processEvents()
    assert not chat.property("checked") and speedo.property("checked")
    assert backend.hudState == {"chat": False, "mfd": True, "speedo": True}
    backend.setHudShown(False)
    QCoreApplication.processEvents()
    assert not chat.property("checked") and not speedo.property("checked")
    wait_commands(backend)
    assert replays_page.sent[:2] == [("POST", "/rest/hud/toggle/chat"), ("POST", "/rest/hud/toggle/speedo")]
    # Game answer wins (command lost): checks follow it again
    backend.refresh_state()
    wait_requests(backend.request_state)
    QCoreApplication.processEvents()
    assert chat.property("checked") and not speedo.property("checked")


def test_game_replays_toggle_game_ui(replays_page, monkeypatch):
    """Whole game UI shown or hidden as a middle click in game (posted to game window)"""
    import time

    from tinypedal.ui.quick import game_window

    backend = answered(replays_page, GAME_ANSWERS)
    clicks: list = []
    monkeypatch.setattr(game_window, "find_game_window", lambda: (42, 1920, 1080))
    monkeypatch.setattr(game_window, "middle_click", lambda found: clicks.append(found) or True)
    backend.toggleGameUi()
    end = time.monotonic() + 2
    while not clicks and time.monotonic() < end:  # clicked in background (button held a frame)
        time.sleep(0.01)
    assert clicks == [(42, 1920, 1080)] and not backend.noticeError
    monkeypatch.setattr(game_window, "find_game_window", lambda: (0, 0, 0))  # game window not found
    backend.toggleGameUi()
    assert backend.noticeError and "Game window not found" in backend.noticeText
    answered(replays_page, {"/rest/watch/replays": REPLAYS, "/rest/watch/focus": -1})  # menus: no watch screen
    monkeypatch.setattr(game_window, "find_game_window", lambda: (42, 1920, 1080))
    backend.toggleGameUi()
    time.sleep(0.1)
    assert len(clicks) == 1


def test_game_window_click_only_to_game(monkeypatch):
    """Middle click posted only to a window of game process"""
    import sys

    from tinypedal.ui.quick import game_window

    real_path = game_window.process_path
    monkeypatch.setattr(game_window, "process_path", lambda pid: "C:/Windows/explorer.exe")
    assert game_window.find_game_window() == (0, 0, 0)
    assert not game_window.middle_click_game() and not game_window.middle_click((0, 0, 0))
    if sys.platform == "win32":  # a window of game process: largest one, client size
        monkeypatch.setattr(game_window, "process_path", lambda pid: "C:/Games/Le Mans Ultimate/Le Mans Ultimate.exe")
        hwnd, width, height = game_window.find_game_window()
        assert hwnd and width >= 0 and height >= 0
    monkeypatch.setattr(game_window, "process_path", real_path)
    monkeypatch.setattr(game_window.sys, "platform", "linux")  # other systems: no game window
    assert game_window.find_game_window() == (0, 0, 0) and game_window.process_path(1) == ""


def test_game_replays_shown_as_app_page(window):  # noqa: F811
    """Page inside app: game asked while page shown, not while another page is shown, closed with page"""
    from tinypedal.ui import game_rest
    from tinypedal.ui.tools_view import open_tool

    game = FakeGame()
    import pytest as _pytest

    patch = _pytest.MonkeyPatch()
    patch.setattr(game_rest, "GameConnection", game.connection)
    try:
        view = window.centralWidget()
        window.show()
        dialog = open_tool("game_replays.GameReplays", window)
        assert [type(page.dialog).__name__ for page in view.dialog_pages()] == ["GameReplays"]
        assert not dialog.view.errors() and dialog.backend._shown
        wait_requests(dialog.backend.request_replays, dialog.backend.request_state)
        assert dialog.backend._timer.isActive()
        view.set_current_index(1)  # another page: game no longer asked
        assert not dialog.backend._shown and not dialog.backend._timer.isActive()
        dialog.close()
        assert not view.dialog_pages()
        window.hide()
    finally:
        patch.undo()


def test_game_connection_keeps_connection(monkeypatch):
    """One connection for the requests of a job, error status with json body kept, no answer: None at once"""
    import http.client

    from tinypedal.ui import game_rest

    opened: list = []

    class Response:
        def __init__(self, status, body):
            self.status, self.body, self.will_close = status, body, False

        def read(self):
            return self.body

    class Connection:
        def __init__(self, host, port, timeout):
            opened.append(host)
            self.answer = None

        def request(self, method, resource, body=None, headers=None):
            if resource == "/down":
                raise ConnectionRefusedError
            self.answer = {"/rest/watch/focus": Response(400, b"-1"), "/rest/x": Response(200, b"[1]"),
                           "/rest/text": Response(400, b"not json")}[resource]

        def getresponse(self):
            return self.answer

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(game_rest, "game_address", lambda: ("localhost", 6397))
    monkeypatch.setattr(game_rest, "resolve_hostname", lambda host, port, timeout: host)
    with game_rest.GameConnection() as connection:
        assert connection.get("/rest/watch/focus") == -1 and connection.answered
        assert connection.get("/rest/x") == [1] and connection.get("/rest/text") is None
        assert connection.send("PUT", "/rest/x")
        assert len(opened) == 1
        assert connection.get("/down") is None and connection.failed
        assert connection.get("/rest/x") is None  # game gone: no more waiting


def test_game_request_thread_kept(ui_env, monkeypatch):
    """Requests of a game request done on one thread, kept for next ones; failed job: next one can start"""
    import threading

    from PySide6.QtCore import QObject

    from tinypedal.ui import game_rest

    parent = QObject()
    # Default work (team stints, tyre allocation pages): json answers of resources
    monkeypatch.setattr(game_rest, "request_game", {"/a": 1, "/b": [2]}.get)
    answers: list = []
    resources = game_rest.GameRequest(parent, ("/a", "/b", "/c"), answers.append)
    assert resources.start() and not resources.start()  # one request at a time
    wait_requests(resources)
    assert answers == [[1, [2], None]]
    results: list = []
    request = game_rest.GameRequest(parent, (), results.append)
    request.start(lambda: threading.current_thread().ident)
    wait_requests(request)
    request.start(lambda: threading.current_thread().ident)
    wait_requests(request)
    assert results[0] == results[1] != threading.current_thread().ident
    request.start(lambda: 1 / 0)
    wait_requests(request)
    assert request.start(lambda: "next")
    wait_requests(request)
    assert results[-1] == "next"
    parent.deleteLater()


def test_game_request_page_freed_at_once(ui_env):
    """Request holds method of its page weakly: page without parent freed as soon as unused, in UI thread

    With a reference cycle, the garbage collector freed it later on any thread (game request thread
    reading results files): its file watcher left a dangling socket notifier in the Linux event loop, and
    the next page shown crashed.
    """
    import gc
    import weakref

    from PySide6.QtCore import QObject

    from tinypedal.ui import game_rest

    class Page(QObject):
        def __init__(self):
            super().__init__()
            self.answers: list = []
            self.request = game_rest.GameRequest(self, (), self.received)

        def received(self, answer):
            self.answers.append(answer)

    page = Page()
    page.request.start(lambda: "done")
    wait_requests(page.request)
    assert page.answers == ["done"]
    freed = weakref.ref(page)
    gc.disable()
    try:
        del page
        assert freed() is None  # no cycle: freed without garbage collector
    finally:
        gc.enable()


def test_game_replays_text_helpers(ui_env):
    from PySide6.QtCore import QDate, QDateTime

    from tinypedal.ui.quick import replays_backend

    assert replays_backend.clock_text(3725.9) == "1:02:05"
    assert replays_backend.size_text(190658701) == "182 MB"
    assert replays_backend.size_text(814337) == "0.8 MB"
    assert replays_backend.size_text(8454000000) == "7.9 GB"
    today = QDate(2026, 10, 5)
    noon = QDateTime(today, QDateTime.currentDateTime().time()).toSecsSinceEpoch()
    assert replays_backend.day_text(noon, today) == "Today"
    assert replays_backend.day_text(noon - 86400, today) == "Yesterday"
    assert replays_backend.day_text(0, today) == "Unknown Date"
    assert replays_backend.event_type_text("specialevent") == "Special Event"
    assert replays_backend.event_type_text("new-kind") == "New Kind"
    assert replays_backend.session_text("QUALIFY") == "Qualify"


def test_lap_info_tyre_compound(monkeypatch):
    from tinypedal.module import module_recorder
    from tinypedal.ui.quick.stint_analysis import lap_compound

    def value(result):
        return lambda *args: result

    read = SimpleNamespace(
        session=SimpleNamespace(session_type=value(3), track_name=value("Spa"), combo_name=value("Spa - LMP2"),
                                track_temperature=value(31.0), ambient_temperature=value(20.0),
                                wetness_average=value(0.0)),
        vehicle=SimpleNamespace(vehicle_name=value("Oreca"), class_name=value("LMP2"), setup=value(()),
                                setup_name=value(""), setup_modified=value(False)),
        lap=SimpleNamespace(track_length=value(7004.0)),
        timing=SimpleNamespace(elapsed=value(600.0)),
        tyre=SimpleNamespace(compound_name=value(("Medium", "Soft"))),
    )
    monkeypatch.setattr(api, "read", read)
    info = module_recorder.lap_info("lap", [])
    assert info["compound"] == ["Medium", "Soft"]  # lap viewer groups stints by compound
    assert lap_compound(info) == "Medium/Soft"
