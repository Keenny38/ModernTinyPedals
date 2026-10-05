"""Game info of LMU Rest API: chat widget, contacts (black box event log, game replays page),
pit lane entry (race plan widget), setup name (laps), replays saved by game"""

from importlib import import_module
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

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


def test_parse_replays_and_slots():
    replays = game_info.parse_replays(REPLAYS)
    assert [replay.id for replay in replays] == [1, 0]  # newest first
    assert replays[1] == game_info.GameReplay(0, "Algarve P1 1", "Daily Q1", "PRACTICE", "PORTIMAOWEC",
                                              1791165314.0, 66644097)
    assert game_info.driver_slots(STANDINGS) == {"Zaac Latta": 4, "Kevin Ramirez": 7}
    assert game_info.parse_replays(None) == [] and game_info.driver_slots(None) == {}


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

    cfg.user.config["overlay_style"]["enable_modern_style"] = modern
    cfg.user.setting["chat"]["number_of_lines"] = 3
    monkeypatch.setattr(api.read.session, "chat_messages",
                        lambda: tuple(game_info.parse_chat(CHAT, ())))
    widget = create_widget(import_module("tinypedal.widget.chat"), cfg, "chat")
    widget.max_duration = 0  # sample messages are old
    widget.timerEvent(None)
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


# --- Game replays page
@pytest.fixture
def replays_page(ui_env, monkeypatch):
    from tinypedal.ui import game_replays
    from tinypedal.ui._common import BaseEditor

    sent: list = []
    monkeypatch.setattr(BaseEditor, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(game_replays, "game_command", lambda method, resource: sent.append((method, resource)) or True)
    page = game_replays.GameReplays(None)
    page.sent = sent
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


def test_game_replays_page(replays_page, monkeypatch):
    from tinypedal.ui import game_rest

    answers = {
        "/rest/watch/replays": REPLAYS, "/rest/replay/isActive": True,
        "/rest/watch/getIncidentsList/1": CONTACTS, "/rest/watch/standings": STANDINGS,
    }
    monkeypatch.setattr(game_rest, "request_game", answers.get)
    page = replays_page
    assert not page.button_jump.isEnabled() and not page.playback_buttons[0].isEnabled()
    page.refresh_all()
    wait_requests(page.request_replays, page.request_state)
    assert page.table_replays.rowCount() == 2 and page.table_replays.item(0, 1).text() == "Bahrain R1"
    assert page.table_contacts.rowCount() == 3 and page.button_jump.isEnabled()
    assert all(button.isEnabled() for button in page.playback_buttons)
    # Watch replay, playback command, jump to contact (camera on the driver, seconds before)
    page.table_replays.selectRow(1)
    page.watch_replay()
    page.playback_buttons[4].click()
    wait_requests(page.request_command)
    page.select_contact(2)  # 1777.99 Zaac Latta
    page.seconds_before.setValue(5)
    page.jump_to_contact()
    wait_requests(page.request_command, page.request_state)
    assert page.sent == [
        ("GET", "/rest/watch/play/0"),
        ("PUT", "/rest/watch/replayCommand/VCRCOMMAND_PLAY"),
        ("PUT", "/rest/watch/focus/4"), ("PUT", "/rest/watch/replaytime/1772"),
    ]


def test_game_replays_page_game_not_running(replays_page, monkeypatch):
    from tinypedal.ui import game_rest

    monkeypatch.setattr(game_rest, "request_game", lambda resource: None)
    page = replays_page
    page.refresh_all()
    wait_requests(page.request_replays, page.request_state)
    assert page.table_replays.rowCount() == 0 and not page.button_jump.isEnabled()
    assert page.label_status.text() and page.label_playback.text()
