"""Broadcast Director: race events & shots (process/director), page backend & QML page (LMU Rest API faked)"""

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from neopedal.process import director as dr
from neopedal.process.game_info import Contact, Standing
from tests.test_game_info import FakeGame, wait_commands, wait_requests

TRACK = 4000.0


def car(slot, position, laps=10, distance=1000.0, car_class="GT3", speed=50.0, **values) -> Standing:
    """Car of watch standings"""
    fields = dict(
        slot=slot, position=position, driver=f"Driver {slot}", number=str(slot), car_class=car_class,
        vehicle="Car", team=f"Team {slot}", laps=laps, best=0.0, last=0.0, gap=0.0, laps_behind=0, pitstops=0,
        in_pit=False, penalties=0, finish="FSTAT_NONE", focus=False, player=False, speed=speed, distance=distance,
    )
    fields.update(values)
    return Standing(**fields)


def news(events):
    """Events but battles (cars close in these tests)"""
    return [event for event in events if event.kind != dr.BATTLE]


def field(*cars):
    return sorted(cars, key=lambda item: item.position)


# Race events
def test_track_gap_from_distance_and_speed():
    ahead, behind = car(1, 1, distance=1050.0), car(2, 2, distance=1000.0, speed=50.0)
    assert dr.track_gap(ahead, behind, TRACK) == pytest.approx(1.0)
    # Car ahead a lap up (crossed the line): still right ahead on track
    assert dr.track_gap(car(1, 1, laps=11, distance=20.0), car(2, 2, laps=10, distance=3990.0), TRACK) == \
        pytest.approx(30 / 50)
    assert dr.track_gap(car(1, 1, laps=11, distance=1000.0), behind, TRACK) == -1  # a lap apart
    assert dr.track_gap(car(1, 1, distance=900.0), behind, TRACK) == -1  # behind it on track
    assert dr.track_gap(ahead, car(2, 2, distance=1000.0, speed=1.0), TRACK) == pytest.approx(50 / dr.MIN_SPEED)
    # No track length: game gaps of same lap cars
    assert dr.track_gap(car(1, 1, gap=0.0), car(2, 2, gap=0.8), 0.0) == pytest.approx(0.8)
    assert dr.track_gap(car(1, 1), car(2, 2, gap=0.8, laps_behind=1), 0.0) == -1


def test_class_places_by_overall_place():
    cars = [car(1, 1, car_class="Hyper"), car(2, 2), car(3, 3, car_class="Hyper"), car(4, 4)]
    assert dr.class_places(cars) == {1: 1, 2: 1, 3: 2, 4: 2}


def test_first_answer_tells_contacts_as_history_only():
    watcher = dr.RaceWatcher()
    contacts = (Contact(50.0, "Driver 1", "Driver 2"), Contact(60.0, "Driver 2", "Immovable"))
    events = watcher.update(field(car(1, 1), car(2, 2, distance=500.0)), contacts, 100.0, "RACE1", TRACK)
    assert [(event.kind, event.live) for event in events] == [(dr.CONTACT, False), (dr.WALL, False)]
    assert events[0].slots == (1, 2) and events[1].drivers == ("Driver 2",)
    # Same contacts again: not told twice; a new one is news
    contacts += (Contact(101.0, "Driver 1", "Driver 2"),)
    events = watcher.update(field(car(1, 1), car(2, 2, distance=500.0)), contacts, 102.0, "RACE1", TRACK)
    assert [(event.kind, event.live, event.time) for event in events] == [(dr.CONTACT, True, 101.0)]


def test_overtake_told_once_settled():
    watcher = dr.RaceWatcher()
    news(watcher.update(field(car(1, 1, distance=1010.0), car(2, 2)), (), 100.0, "RACE1", TRACK))
    passed = field(car(2, 1, distance=1012.0), car(1, 2, distance=1010.0))
    assert news(watcher.update(passed, (), 100.5, "RACE1", TRACK)) == []  # side by side: not settled yet
    assert news(watcher.update(passed, (), 101.0, "RACE1", TRACK)) == []
    events = news(watcher.update(passed, (), 101.6, "RACE1", TRACK))
    assert [(event.kind, event.slots, event.position) for event in events] == [(dr.LEAD, (2, 1), 1)]
    assert news(watcher.update(passed, (), 102.6, "RACE1", TRACK)) == []


def test_overtake_for_place_and_swap_back_not_told():
    watcher = dr.RaceWatcher()
    start = field(car(1, 1, distance=2000.0), car(2, 2, distance=1010.0), car(3, 3))
    news(watcher.update(start, (), 100.0, "RACE1", TRACK))
    swapped = field(car(1, 1, distance=2000.0), car(3, 2, distance=1012.0), car(2, 3, distance=1010.0))
    news(watcher.update(swapped, (), 100.5, "RACE1", TRACK))
    assert news(watcher.update(start, (), 101.0, "RACE1", TRACK)) == []  # swapped back before settling
    news(watcher.update(swapped, (), 102.0, "RACE1", TRACK))
    events = news(watcher.update(swapped, (), 103.5, "RACE1", TRACK))
    assert [(event.kind, event.slots, event.position) for event in events] == [(dr.OVERTAKE, (3, 2), 2)]


def test_place_lost_in_pits_is_no_overtake():
    watcher = dr.RaceWatcher()
    news(watcher.update(field(car(1, 1, distance=1100.0), car(2, 2)), (), 100.0, "RACE1", TRACK))
    pitted = field(car(2, 1), car(1, 2, in_pit=True, speed=20.0))
    events = news(watcher.update(pitted, (), 101.0, "RACE1", TRACK))
    assert [event.kind for event in events] == [dr.PIT_IN]
    events = news(watcher.update(pitted, (), 102.5, "RACE1", TRACK))
    assert [event.kind for event in events] == []
    # Outside races: no overtakes, no pit stops
    watcher = dr.RaceWatcher()
    news(watcher.update(field(car(1, 1, distance=1100.0), car(2, 2)), (), 100.0, "QUALIFY1", TRACK))
    assert news(watcher.update(pitted, (), 101.0, "QUALIFY1", TRACK)) == []


def test_pit_stop_duration_and_stint():
    watcher = dr.RaceWatcher()
    watcher.update([car(1, 1, laps=20)], (), 100.0, "RACE1", TRACK)
    for now in (101.0, 111.0, 121.0):  # answers about every second (a jump of 20 s is a replay seek)
        watcher.update([car(1, 1, laps=20, in_pit=True, speed=20.0)], (), now, "RACE1", TRACK)
    events = watcher.update([car(1, 1, laps=21, in_pit=False, pitstops=1)], (), 131.5, "RACE1", TRACK)
    assert [(event.kind, event.value) for event in events] == [(dr.PIT_OUT, 30.5)]
    assert watcher.pit_stops[1] == [dr.PitStop(21, 101.0, 30.5)]
    assert watcher.stint_laps(car(1, 1, laps=25)) == 4


def test_battle_found_tracked_and_ended():
    watcher = dr.RaceWatcher(battle_gap=1.0)
    close = field(car(1, 1, distance=1040.0), car(2, 2, distance=1000.0), car(3, 3, distance=500.0))
    events = watcher.update(close, (), 100.0, "RACE1", TRACK)
    assert events == [] and list(watcher.battles) == [(1, 2)]  # known on first answer, not told
    battle = watcher.battles[1, 2]
    assert battle.position == 1 and battle.gap == pytest.approx(0.8)
    closer = field(car(1, 1, distance=1040.0), car(2, 2, distance=1015.0), car(3, 3, distance=500.0))
    watcher.update(closer, (), 101.0, "RACE1", TRACK)
    assert watcher.battles[1, 2].trend < 0  # closing
    # Gap just over battle gap: kept (margin), then over margin: ended
    watcher.update(field(car(1, 1, distance=1060.0), car(2, 2, distance=1000.0)), (), 102.0, "RACE1", TRACK)
    assert (1, 2) in watcher.battles
    watcher.update(field(car(1, 1, distance=1080.0), car(2, 2, distance=1000.0)), (), 103.0, "RACE1", TRACK)
    assert not watcher.battles
    # Another class between them on track: still a class battle; new one told
    events = watcher.update(field(car(1, 1, distance=1040.0), car(9, 2, car_class="Hyper", distance=1020.0),
                                  car(2, 3, distance=1000.0)), (), 104.0, "RACE1", TRACK)
    assert [(event.kind, event.slots) for event in events] == [(dr.BATTLE, (2, 1))]
    # Pit lane: no battle
    watcher.update(field(car(1, 1, distance=1040.0), car(2, 2, distance=1000.0, in_pit=True)), (), 105.0,
                   "RACE1", TRACK)
    assert not watcher.battles


def test_fastest_lap_of_class():
    watcher = dr.RaceWatcher()
    watcher.update([car(1, 1, best=90.0), car(2, 2, best=91.0), car(3, 3, car_class="Hyper")], (), 10.0,
                   "RACE1", TRACK)
    events = watcher.update([car(1, 1, best=90.0), car(2, 2, best=89.5), car(3, 3, car_class="Hyper", best=95.0)],
                            (), 11.0, "RACE1", TRACK)
    # GT3 record beaten; first Hyper lap time is no record
    assert [(event.kind, event.slots, event.value) for event in events] == [(dr.FASTEST, (2,), 89.5)]
    assert watcher.update([car(1, 1, best=89.7), car(2, 2, best=89.5)], (), 12.0, "RACE1", TRACK) == []


def test_finish_win_retire_penalty():
    watcher = dr.RaceWatcher()
    cars = [car(1, 1), car(2, 2), car(3, 3)]
    watcher.update(cars, (), 10.0, "RACE1", TRACK)
    events = watcher.update([car(1, 1, finish="FSTAT_FINISHED"), car(2, 2, penalties=1),
                             car(3, 3, finish="FSTAT_DNF")], (), 11.0, "RACE1", TRACK)
    assert sorted((event.kind, event.slots) for event in events) == [
        (dr.PENALTY, (2,)), (dr.RETIRED, (3,)), (dr.WINNER, (1,))]
    events = watcher.update([car(1, 1, finish="FSTAT_FINISHED"), car(2, 2, penalties=1, finish="FSTAT_FINISHED"),
                             car(3, 3, finish="FSTAT_DNF")], (), 12.0, "RACE1", TRACK)
    assert [(event.kind, event.slots) for event in events] == [(dr.FINISH, (2,))]


def test_stopped_car_but_not_halted_race():
    watcher = dr.RaceWatcher()
    cars = [car(slot, slot) for slot in range(1, 7)]
    watcher.update(cars, (), 10.0, "RACE1", TRACK)
    stopped = [car(1, 1, speed=0.5), *cars[1:]]
    watcher.update(stopped, (), 11.0, "RACE1", TRACK)
    assert watcher.update(stopped, (), 12.0, "RACE1", TRACK) == []
    events = watcher.update(stopped, (), 14.5, "RACE1", TRACK)
    assert [(event.kind, event.slots, event.time) for event in events] == [(dr.STOPPED, (1,), 11.0)]
    assert watcher.update(stopped, (), 16.0, "RACE1", TRACK) == []  # told once
    # Red flag: every car stops, nothing told
    watcher = dr.RaceWatcher()
    watcher.update(cars, (), 10.0, "RACE1", TRACK)
    halted = [car(slot, slot, speed=0.0) for slot in range(1, 7)]
    for now in (11.0, 12.0, 15.0):
        assert watcher.update(halted, (), now, "RACE1", TRACK) == []


def test_time_jump_watches_again():
    watcher = dr.RaceWatcher()
    watcher.update([car(1, 1), car(2, 2)], (), 500.0, "RACE1", TRACK)
    watcher.update([car(1, 1, in_pit=True)], (), 501.0, "RACE1", TRACK)
    stops = dict(watcher.pit_stops)
    # Replay seek backwards: no events from comparing two moments far apart, pit stops seen are kept
    assert watcher.update([car(2, 1), car(1, 2)], (), 200.0, "RACE1", TRACK) == []
    assert watcher.pit_stops == stops


# Shots
def candidate(slot, kind, score, key=None):
    return dr.Candidate(slot, kind, score, key or f"{kind}|{slot}")


def test_director_keeps_shot_until_shortest_length_unless_urgent():
    director = dr.Director(dr.DirectorSettings(min_shot=8.0, max_shot=30.0))
    first = director.decide([candidate(1, dr.BATTLE, 60)], 0.0)
    director.take(first, 0.0)
    battle = candidate(1, dr.BATTLE, 60)
    assert director.decide([candidate(2, dr.OVERTAKE, 75), battle], 3.0) is None  # not urgent
    assert director.decide([candidate(3, dr.CONTACT, 90), battle], 1.0) is None  # too soon even for urgent
    assert director.decide([candidate(3, dr.CONTACT, 90), battle], 3.0).slot == 3
    # After the shortest shot: another story only if clearly better while the story goes on
    assert director.decide([candidate(2, dr.OVERTAKE, 65), battle], 10.0) is None
    assert director.decide([candidate(2, dr.OVERTAKE, 75), battle], 10.0).slot == 2
    # Longest shot reached: another car
    assert director.decide([battle, candidate(2, dr.ROAM, 12)], 31.0).slot == 2
    # Story over: another car
    assert director.decide([candidate(1, dr.ROAM, 12), candidate(4, dr.ROAM, 11)], 12.0).slot == 4
    # Roaming: cars shown twice the shortest shot, unless something happens
    director.take(candidate(4, dr.ROAM, 11), 20.0)
    assert director.decide([candidate(5, dr.ROAM, 14), candidate(4, dr.ROAM, 11)], 30.0) is None
    assert director.decide([candidate(5, dr.ROAM, 14), candidate(4, dr.ROAM, 11)], 37.0).slot == 5
    assert director.decide([candidate(6, dr.PIT_IN, 30), candidate(4, dr.ROAM, 11)], 30.0).slot == 6


def test_director_operator_cut_holds_and_cameras_in_turn():
    director = dr.Director(dr.DirectorSettings(manual_hold=20.0))
    director.manual(5, "COCKPIT", 0.0)
    assert director.decide([candidate(3, dr.CONTACT, 95)], 10.0) is None
    assert director.decide([candidate(3, dr.CONTACT, 95)], 21.0).slot == 3
    assert [director.camera_for(dr.BATTLE) for _ in range(5)] == [*dr.CAMERA_PLAN[dr.BATTLE], "TRACKSIDE0"]
    director.settings.camera_style = "keep"
    assert director.camera_for(dr.CONTACT) == ""
    director.settings.camera_style = "trackside"
    assert director.camera_for(dr.FASTEST) == "TRACKSIDE0"


def test_candidates_scores():
    director = dr.Director()
    cars = [car(1, 1), car(2, 2), car(3, 3, garage=True)]
    events = [
        dr.Event("contact|1", dr.CONTACT, 99.0, (2, 1), ("Driver 2", "Driver 1"), "GT3"),
        dr.Event("contact|old", dr.CONTACT, 10.0, (1,), ("Driver 1",), "GT3"),  # too old
        dr.Event("contact|history", dr.CONTACT, 99.0, (1,), ("Driver 1",), "GT3", live=False),
        dr.Event("pit|3", dr.PIT_IN, 99.0, (3,), ("Driver 3",), "GT3"),  # car in garage
        dr.Event("battle|start", dr.BATTLE, 99.0, (2, 1), ("Driver 2", "Driver 1"), "GT3"),  # battles list instead
    ]
    battles = [dr.Battle(1, 2, "GT3", 1, 0.3, -0.1, 90.0)]
    result = director.candidates(events, battles, cars, 100.0, 0.0, True)
    assert [(item.kind, item.slot) for item in result[:2]] == [(dr.CONTACT, 2), (dr.BATTLE, 2)]
    assert {item.key for item in result} >= {"roam|1", "roam|2"} and "roam|3" not in {item.key for item in result}
    assert not any(item.key in ("contact|old", "contact|history", "pit|3", "battle|start") for item in result)
    # Car just shown is less wanted
    director.shown[2] = 0.0
    later = director.candidates(events, battles, cars, 100.0, 5.0, True)
    assert next(item for item in later if item.key == "contact|1").score == pytest.approx(
        next(item for item in result if item.key == "contact|1").score - director.settings.repeat_penalty)


# Page backend
def standings_json(*cars, focus=-1, session_time=0.0):
    return [{
        "slotID": item.slot, "position": item.position, "driverName": item.driver, "carNumber": item.number,
        "carClass": item.car_class, "vehicleName": item.vehicle, "fullTeamName": item.team,
        "lapsCompleted": item.laps, "bestLapTime": item.best, "lastLapTime": item.last, "timeBehindLeader": 0.0,
        "lapsBehindLeader": 0, "pitstops": item.pitstops, "pitting": item.in_pit, "penalties": item.penalties,
        "finishStatus": item.finish, "hasFocus": item.slot == focus, "player": False, "lapDistance": item.distance,
        "carVelocity": {"velocity": item.speed}, "lapStartET": session_time - 1.0, "timeIntoLap": 1.0,
        "sector": f"SECTOR{item.sector}" if item.sector else "", "pitState": item.pit_state, "inGarageStall": item.garage,
        "qualification": item.grid, "lastSectorTime1": item.last_sector1, "lastSectorTime2": item.last_sector2,
        "currentSectorTime1": item.current_sector1, "currentSectorTime2": item.current_sector2,
        "bestLapSectorTime1": item.best_sector1, "bestLapSectorTime2": item.best_sector2,
        "veFraction": item.energy if item.energy >= 0 else 0,
    } for item in cars]


def race_answers(session_time, *cars, focus=1, replay=False, contacts=(), info=None):
    return {
        "/rest/replay/isActive": replay,
        "/rest/watch/focus": focus,
        "/rest/watch/sessionInfo": {"currentEventTime": session_time, "trackName": "Test Ring", "session": "RACE1",
                                    "lapDistance": TRACK, "gamePhase": 5, **(info or {})},
        "/rest/watch/standings": standings_json(*cars, focus=focus, session_time=session_time),
        "/rest/watch/getIncidentsList/1": [{"et": time, "player": driver, "contactWith": other}
                                           for time, driver, other in contacts],
        "/rest/replay/CameraController/getCameraInfo": {"cameraName": "SWINGMAN", "currentCameraGroup": "Driving"},
    }


@pytest.fixture
def director_page(ui_env, monkeypatch):
    from neopedal.ui import broadcast_director, game_rest
    from neopedal.ui._common import BaseDialog

    game = FakeGame()
    monkeypatch.setattr(BaseDialog, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(game_rest, "GameConnection", game.connection)
    page = broadcast_director.BroadcastDirector(None)
    page.game = game
    page.backend._shown = True  # page shown: lists made at each answer (not shown: once shown again)
    yield page
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def poll(page, answers):
    page.game.answers = answers
    backend = page.backend
    backend._timer.stop()
    backend.refresh_state()
    wait_requests(backend.request_state)
    backend._timer.stop()


def test_page_loads_and_follows_session(director_page):
    page, backend = director_page, director_page.backend
    assert not page.view.errors(), [error.toString() for error in page.view.errors()]
    poll(page, {})
    assert backend.gameState == "offline" and not backend.inSession
    poll(page, race_answers(100.0, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0), car(3, 3, car_class="Hyper")))
    assert backend.gameState == "session" and backend.sessionText == "Test Ring · Race"
    rows = [backend.carRows.rows[index] for index in range(backend.carRows.rowCount())]
    assert [row["slot"] for row in rows] == [1, 2, 3]
    assert rows[1]["interval"] == "+0.8" and rows[1]["battle"] and rows[0]["onAir"]
    # Car followed by game camera: on air as chosen in game, no command sent
    assert backend.onAir["slot"] == 1 and backend.on_air_kind == "game" and page.game.sent == []
    assert backend.battleCount == 1


def test_operator_cut_and_camera_commands(director_page):
    page, backend = director_page, director_page.backend
    poll(page, race_answers(100.0, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0)))
    backend.cutToCar(2)
    backend.selectCamera("TVCOCKPIT")
    wait_commands(backend)
    assert page.game.sent == [
        ("PUT", "/rest/watch/focus/2"), ("PUT", "/rest/watch/focus/1/0/false"),
        ("POST", "/rest/replay/CameraController/setCamera", json.dumps({"cameraGroup": "Driving", "direction": 1})),
    ]
    assert backend.onAir["slot"] == 2 and backend.on_air_kind == dr.MANUAL
    backend.stepCar(1)  # next by place, wraps around
    wait_commands(backend)
    assert page.game.sent[-1] == ("PUT", "/rest/watch/focus/1")
    # Car chosen in game later (after the grace time): followed as an operator cut
    backend.last_cut = 0.0
    poll(page, race_answers(101.0, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0), focus=2))
    assert backend.on_air_slot == 2 and backend.on_air_kind == "game"


def test_automatic_mode_cuts_to_events(director_page):
    page, backend = director_page, director_page.backend
    cars = (car(1, 1, distance=2000.0), car(2, 2, distance=1000.0), car(3, 3, distance=400.0))
    poll(page, race_answers(100.0, *cars))
    assert backend.mode == "assist"
    backend.setMode(2)
    wait_commands(backend)
    assert backend.mode == "auto"
    backend.director.hold_until = 0.0
    backend.director.shot = backend.director.shot._replace(start=-100.0) if backend.director.shot else None
    poll(page, race_answers(101.0, *cars, contacts=((100.5, "Driver 3", "Driver 2"),)))
    wait_commands(backend)
    assert backend.on_air_slot == 3 and backend.on_air_kind == dr.CONTACT
    assert ("PUT", "/rest/watch/focus/3") in page.game.sent
    assert ("PUT", "/rest/watch/focus/4/0/false") in page.game.sent  # trackside cycle on contacts
    feed = [backend.feedRows.rows[index] for index in range(backend.feedRows.rowCount())]
    assert feed[0]["title"] == "Contact: #3 Driver 3 and #2 Driver 2" and feed[0]["live"]
    backend.setFeedFilter(3)  # pit stops only
    assert backend.feedRows.rowCount() == 0


def test_settings_saved_automatic_mode_not_restored(director_page, ui_env):
    from neopedal.ui.quick import director_backend

    page, backend = director_page, director_page.backend
    poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=200.0)))
    backend.setMode(2)
    backend.setNumber("minShot", 12)
    backend.setNumber("maxShot", 5)  # never shorter than shortest shot
    backend.setNumber("battleGap", 9)
    backend.setCameraStyle(3)
    backend.selectCar(2)
    backend.setNote("  Rookie, first endurance race ")
    data = director_backend.load_page_settings()
    assert data["min_shot"] == 12 and data["max_shot"] == 12 and data["battle_gap"] == 3.0
    assert data["camera_style"] == "keep" and data["notes"] == {"Driver 2": "Rookie, first endurance race"}
    assert backend.sheet["note"] == "Rookie, first endurance race"
    other = director_backend.DirectorBackend(None)
    try:
        assert other.mode == "assist" and other.director.settings.min_shot == 12
    finally:
        other.release()


def test_event_in_replay_seeks_before_it(director_page):
    page, backend = director_page, director_page.backend
    cars = (car(1, 1, distance=2000.0), car(2, 2, distance=1000.0))
    poll(page, race_answers(300.0, *cars, replay=True, contacts=((250.0, "Driver 2", "Immovable"),)))
    assert backend.replayActive
    key = backend.feedRows.rows[0]["key"]
    backend.showEvent(key)
    wait_commands(backend)
    assert ("PUT", "/rest/watch/focus/2") in page.game.sent
    assert page.game.sent[-1] == ("PUT", "/rest/watch/replaytime/245")


def test_hotkeys_reach_open_page(director_page, monkeypatch):
    from neopedal.hotkey import command

    page, backend = director_page, director_page.backend
    poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=200.0)))
    command.hotkey_director_auto()
    assert backend.mode == "auto"
    command.hotkey_director_auto()
    assert backend.mode == "assist"
    command.hotkey_director_next_car()
    wait_commands(backend)
    assert page.game.sent[-1] == ("PUT", "/rest/watch/focus/2")
    page.close()
    assert command.open_director() is None
    sent = []
    from neopedal.ui import game_rest

    monkeypatch.setattr(game_rest, "game_command", lambda *args: sent.append(args))
    monkeypatch.setattr(command.threading, "Thread", lambda target, args, **kwargs: type(
        "Run", (), {"start": lambda self: target(*args)})())
    command.hotkey_director_previous_car()  # page closed: game camera on previous car
    assert sent == [("PUT", "/rest/watch/focusBackward")]


def test_page_qml_bundled_modules_and_translated():
    """Release build bundles only QML_MODULES; every text of the page has a French translation"""
    import re

    from neopedal.i18n.fr import TRANSLATION
    from neopedal.ui.quick import QML_FOLDER
    from neopedal.ui.quick import director_backend as db
    from neopedal.ui.quick.qml_modules import QML_MODULES

    pattern = re.compile(r'i18n\.tr\("((?:[^"\\]|\\.)*)"\)')
    missing = []
    for name in ("BroadcastDirector", "DirectorCars", "DirectorDesk", "DirectorCommentary", "DirectorSheet", "DirectorLaps",
                 "DirectorSettings", "DirectorGraphics", "DirectorTiming"):
        with open(f"{QML_FOLDER}/{name}.qml", encoding="utf-8") as file:
            text = file.read()
        modules = re.findall(r"^import ([A-Za-z.]+)", text, flags=re.MULTILINE)
        assert modules and all(module.replace(".", "/") in QML_MODULES for module in modules), (name, modules)
        missing += [found for found in pattern.findall(text) if found not in TRANSLATION]
    for table in (db.STATE_TEXTS, db.KIND_TEXTS, db.SESSION_TEXTS):
        missing += [text for text in table.values() if text not in TRANSLATION]
    missing += [text for text in db.CAMERA_STYLE_TEXTS if text not in TRANSLATION]
    missing += [title for title, _, _ in db.TIMING_COLUMNS.values() if title not in TRANSLATION and title not in
                ("#", "+/-", "S1", "S2", "S3")]
    assert not missing


def test_tool_registered():
    from neopedal.ui.nav_rail import TOOL_SHORT_LABELS
    from neopedal.ui.tools_view import TOOL_KEYWORDS, TOOL_SECTIONS

    path = "broadcast_director.BroadcastDirector"
    assert any(entry[2] == path for _, entries in TOOL_SECTIONS for entry in entries)
    assert path in TOOL_KEYWORDS and TOOL_SHORT_LABELS["broadcast_director"] == "Broadcast"


def test_navigation_bar_broadcast_in_place_of_spectate_for_everyone():
    """Setting 2.50.8: every navigation bar back to the new default once (Broadcast Director in place of Spectate),
    bars changed after the update kept"""
    from neopedal.setting_preupdate import preupdate_global_setting
    from neopedal.template.setting_global import GLOBAL_DEFAULT

    default = GLOBAL_DEFAULT["application"]["rail_items"]
    assert "broadcast_director" in default and "spectate" not in default and "app_settings" not in default
    old = {"application": {"rail_items": "home,spectate,tools", "language": "Français"}}
    preupdate_global_setting((2, 50, 7), old)
    assert old["application"] == {"language": "Français"}  # default bar given at load
    kept = {"application": {"rail_items": "home,tools"}}
    preupdate_global_setting((2, 50, 8), kept)
    assert kept["application"]["rail_items"] == "home,tools"


# From LMU Broadcast Control: slow cars, flags, race start, pit box time, laps & sectors, energy
def test_standings_sectors_grid_and_session_state():
    from neopedal.process.game_info import parse_session_state, parse_standings

    data = standings_json(car(3, 1, last=90.0, last_sector1=20.0, last_sector2=55.0, current_sector1=19.5,
                              sector=2, grid=4, pit_state="STOPPED"))
    parsed = parse_standings(data)[0]
    assert (parsed.sector, parsed.grid, parsed.pit_state) == (2, 4, "STOPPED")
    assert dr.last_sectors(parsed) == (20.0, 35.0, 35.0)
    assert dr.current_sectors(parsed) == (19.5, -1.0, -1.0)
    assert dr.current_sectors(parsed._replace(sector=1)) == (-1.0, -1.0, -1.0)
    state = parse_session_state({"gamePhase": 6, "yellowFlagState": "pits_closed", "sectorFlag": ["UNKNOWN", "YELLOW"],
                                 "ambientTemp": 26.2, "trackTemp": 31.0, "raining": 0.2, "averagePathWetness": 0.0})
    assert state.phase == 6 and state.yellow == "PITS_CLOSED" and state.sector_flags == (False, True)
    assert state.air == 26.2 and state.rain == 0.2
    assert parse_session_state(None).phase == -1


def learned(watcher, speed=60.0, laps=5):
    """Usual speed of every part of the lap known"""
    for _ in range(dr.SPEED_SAMPLES + 1):
        watcher.learn_speeds([car(90 + index, 50 + index, laps=laps, distance=index * dr.SPEED_BIN + 1, speed=speed)
                              for index in range(int(TRACK // dr.SPEED_BIN) + 1)])


def test_slow_car_compared_with_usual_speed_at_that_place():
    watcher = dr.RaceWatcher()
    watcher.update([car(1, 1, speed=60.0), car(2, 2, distance=2000.0, speed=60.0)], (), 10.0, "RACE1", TRACK)
    learned(watcher)
    slow = [car(1, 1, speed=15.0), car(2, 2, distance=2000.0, speed=60.0)]
    for now in (11.0, 12.0):
        assert news(watcher.update(slow, (), now, "RACE1", TRACK)) == []
    events = news(watcher.update(slow, (), 14.5, "RACE1", TRACK))
    assert [(event.kind, event.slots, event.time) for event in events] == [(dr.SLOW, (1,), 11.0)]
    assert news(watcher.update(slow, (), 15.5, "RACE1", TRACK)) == []  # told once
    # Under full course yellow every car is slow: not told
    watcher = dr.RaceWatcher()
    yellow = dr.SessionState(phase=6, yellow="PENDING")
    watcher.update([car(1, 1, speed=60.0)], (), 10.0, "RACE1", TRACK, yellow)
    learned(watcher)
    for now in (11.0, 12.0, 15.0):
        assert [event.kind for event in watcher.update([car(1, 1, speed=15.0)], (), now, "RACE1", TRACK, yellow)
                if event.kind == dr.SLOW] == []


def test_flags_full_course_yellow_and_sector_yellow():
    from neopedal.process.game_info import SessionState

    watcher = dr.RaceWatcher()
    green = SessionState(phase=5, yellow="NONE", sector_flags=(False, False, False))
    cars = [car(1, 1, sector=2, speed=8.0), car(2, 2, sector=2, distance=500.0, speed=60.0)]
    watcher.update(cars, (), 10.0, "RACE1", TRACK, green)
    learned(watcher)
    events = watcher.update(cars, (), 11.0, "RACE1", TRACK, green._replace(sector_flags=(False, True, False)))
    assert [(event.kind, event.slots, event.value) for event in events if event.kind == dr.YELLOW] == [
        (dr.YELLOW, (1,), 2.0)]
    events = watcher.update(cars, (), 12.0, "RACE1", TRACK, SessionState(phase=6, yellow="PENDING"))
    assert [event.kind for event in events if event.kind in (dr.FCY, dr.GREEN)] == [dr.FCY]
    events = watcher.update(cars, (), 13.0, "RACE1", TRACK, green)
    assert [event.kind for event in events if event.kind in (dr.FCY, dr.GREEN)] == [dr.GREEN]


def test_pit_box_time_laps_sectors_and_energy():
    watcher = dr.RaceWatcher()
    watcher.update([car(1, 1, laps=10, energy=0.80)], (), 100.0, "RACE1", TRACK)
    lap = dict(last=90.0, last_sector1=20.0, last_sector2=55.0)
    watcher.update([car(1, 1, laps=11, energy=0.76, **lap)], (), 101.0, "RACE1", TRACK)
    watcher.update([car(1, 1, laps=12, energy=0.72, **lap)], (), 102.0, "RACE1", TRACK)
    faster = dict(last=89.0, last_sector1=19.5, last_sector2=55.0)
    watcher.update([car(1, 1, laps=13, energy=0.67, **faster)], (), 103.0, "RACE1", TRACK)
    records = watcher.laps[1]
    assert [(record.lap, record.time, record.pit) for record in records] == [
        (11, 90.0, False), (12, 90.0, False), (13, 89.0, False)]
    assert records[-1].sectors == (19.5, 35.5, 34.0)
    assert watcher.energy_average(1, 3) == pytest.approx((0.04 + 0.04 + 0.05) / 3)
    assert watcher.energy_average(1, 5) == -1  # not enough laps
    personal, classes = watcher.best_sectors([car(1, 1, laps=13, best=89.0),
                                              car(2, 2, best=88.0, best_sector1=19.0, best_sector2=54.0)])
    assert personal[1] == [19.5, 35.0, 34.0] and classes["GT3"] == [19.0, 35.0, 34.0]
    # Pit stop: lane & box time, pit lap, energy average reset
    for now, values in ((104.0, dict(in_pit=True, speed=20.0)), (110.0, dict(in_pit=True, pit_state="STOPPED")),
                        (120.0, dict(in_pit=True, pit_state="STOPPED")),
                        (140.0, dict(in_pit=True, pit_state="EXITING", speed=15.0))):
        watcher.update([car(1, 1, laps=13, energy=0.65, **values)], (), now, "RACE1", TRACK)
    events = watcher.update([car(1, 1, laps=14, energy=0.95, last=150.0)], (), 150.0, "RACE1", TRACK)
    assert [(event.kind, event.value, event.extra) for event in events] == [(dr.PIT_OUT, 46.0, 30.0)]
    assert watcher.pit_stops[1][-1].stopped == 30.0
    assert watcher.laps[1][-1].pit and watcher.laps[1][-1].energy == -1  # refilled
    assert watcher.energy_average(1, 3) == -1


def test_race_start_follows_leader():
    director = dr.Director()
    cars = [car(1, 2), car(2, 1), car(3, 3)]
    result = director.candidates([], [], cars, 10.0, 0.0, True, start=True)
    assert (result[0].kind, result[0].slot) == (dr.START, 2)
    assert all(item.kind != dr.START for item in director.candidates([], [], cars, 10.0, 0.0, True))


def test_lock_unseen_export_laps_and_weather(director_page, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    page, backend = director_page, director_page.backend
    cars = (car(1, 1, distance=2000.0, grid=2), car(2, 2, distance=1000.0, grid=1), car(3, 3, distance=400.0))
    poll(page, race_answers(100.0, *cars, info={"ambientTemp": 25.6, "trackTemp": 31.2, "raining": 0.25}))
    assert backend.weather == ["Air 26°C", "Track 31°C", "Rain 25%"]
    rows = {row["slot"]: row for row in backend.carRows.rows}
    assert rows[1]["gained"] == 1 and rows[2]["gained"] == -1
    # Locked car: automatic mode does not cut
    backend.setMode(2)
    backend.toggleLock()
    assert backend.carLocked and backend.onAir["locked"]
    backend.director.hold_until = 0.0
    poll(page, race_answers(101.0, *cars, contacts=((100.5, "Driver 3", "Driver 2"),)))
    assert backend.on_air_slot == 1
    # Unseen incident until shown, marked seen
    assert backend.unseenCount == 1 and backend.feedRows.rows[0]["unseen"]
    backend.markAllSeen()
    assert backend.unseenCount == 0
    backend.toggleLock()
    # Export
    path = tmp_path / "events.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    backend.exportEvents()
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("Session time,Kind") and "Contact: #3 Driver 3 and #2 Driver 2" in lines[1]
    # Lap history of a car
    lap = dict(last=91.0, last_sector1=20.0, last_sector2=56.0)
    poll(page, race_answers(102.0, car(1, 1, laps=11, distance=10.0, **lap), *cars[1:]))
    backend.showLaps(1)
    assert backend.lapsOpen and backend.lapsTitle == "#1 Driver 1"
    assert [(row["lap"], row["time"], row["s2"]) for row in backend.lapRows.rows] == [(11, "1:31.000", "36.000")]
    backend.showLaps(-1)
    assert not backend.lapsOpen


def test_instant_replay_of_live_session(director_page, monkeypatch):
    from neopedal.ui.quick import game_camera

    monkeypatch.setattr(game_camera, "REPLAY_READY", 0.0)
    monkeypatch.setattr(game_camera, "SEEK_WAIT", 0.0)
    page, backend = director_page, director_page.backend
    cars = (car(1, 1, distance=2000.0), car(2, 2, distance=1000.0))
    poll(page, race_answers(100.0, *cars, contacts=((96.0, "Driver 2", "Immovable"),)))
    poll(page, race_answers(101.0, *cars, contacts=((96.0, "Driver 2", "Immovable"),
                                                   (100.6, "Driver 1", "Driver 2"))))
    key = next(row["key"] for row in backend.feedRows.rows if row["kind"] == dr.CONTACT)
    game = page.game

    class Answers(dict):  # replay open once the game was asked to open it
        def get(self, key, default=None):
            if key == "/rest/replay/isActive":
                return ("POST", "/rest/replay/toggleactive") in game.sent
            return super().get(key, default)

    game.answers = Answers(game.answers)
    backend.replayEvent(key)
    assert backend.instantReplay
    wait_commands(backend)
    sent = page.game.sent
    assert ("POST", "/rest/replay/toggleactive") in sent and ("PUT", "/rest/watch/focus/1") in sent
    assert ("PUT", "/rest/watch/replaytime/95") in sent
    assert sent.index(("PUT", "/rest/watch/focus/1")) > sent.index(("PUT", "/rest/watch/replaytime/95"))
    assert not backend.instant_waiting and backend._instant_timer.isActive()
    assert backend._instant_timer.interval() == (backend.seconds_before + backend.post_roll) * 1000
    # Replay frames are not the race going on: no events from them
    events = len(backend.events)
    poll(page, race_answers(95.0, *cars, replay=True))
    assert len(backend.events) == events and backend.instantReplay
    backend.backToLive()
    wait_commands(backend)
    assert not backend.instantReplay and sent[-1] == ("POST", "/rest/replay/toggleactive")


def test_lock_hotkey(director_page):
    from neopedal.hotkey import command

    command.hotkey_director_lock()
    assert director_page.backend.carLocked


def test_seek_replay_then_camera_on_car(monkeypatch):
    from neopedal.ui.quick import game_camera

    monkeypatch.setattr(game_camera, "REPLAY_READY", 0.0)
    monkeypatch.setattr(game_camera, "SEEK_WAIT", 0.0)
    game = FakeGame()  # standings keep live values in the replay of a live session: not checked
    game.answers = {"/rest/watch/standings": standings_json(car(1, 1), session_time=500.0)}
    assert game_camera.seek_replay(95, 1)(game.connection())
    assert game.sent == [("PUT", "/rest/watch/replaytime/95"), ("PUT", "/rest/watch/focus/1")]
    game.refused.add("/rest/watch/replaytime/95")
    game.sent.clear()
    assert not game_camera.seek_replay(95, 1)(game.connection())
    assert game.sent == [("PUT", "/rest/watch/replaytime/95")]


def test_instant_replay_kept_while_standings_tell_live(director_page, monkeypatch):
    """Replay of a live session: standings keep live times, the replay is still shown until its end"""
    from neopedal.ui.quick import game_camera

    monkeypatch.setattr(game_camera, "REPLAY_READY", 0.0)
    monkeypatch.setattr(game_camera, "SEEK_WAIT", 0.0)
    page, backend = director_page, director_page.backend
    cars = (car(1, 1, distance=2000.0), car(2, 2, distance=1000.0))
    poll(page, race_answers(300.0, *cars, contacts=((250.0, "Driver 2", "Immovable"),)))
    game = page.game

    class Answers(dict):  # replay open once the game was asked to open it
        def get(self, key, default=None):
            if key == "/rest/replay/isActive":
                return ("POST", "/rest/replay/toggleactive") in game.sent
            return super().get(key, default)

    game.answers = Answers(game.answers)
    backend.replayEvent(backend.feedRows.rows[0]["key"])
    wait_commands(backend)
    assert backend.instantReplay and backend._instant_timer.isActive()
    assert game.sent.count(("POST", "/rest/replay/toggleactive")) == 1  # not back to live yet
    # Game refuses the replay time: back to live at once
    backend.backToLive()
    wait_commands(backend)
    game.sent.clear()
    game.refused.add("/rest/watch/replaytime/245")
    backend.replayEvent(backend.feedRows.rows[0]["key"])
    wait_commands(backend)
    assert not backend.instantReplay



# Optimizations & improvements
def test_contacts_merged_again_only_when_list_changes(monkeypatch):
    calls = []
    real = dr.merge_contacts
    monkeypatch.setattr(dr, "merge_contacts", lambda contacts: calls.append(len(contacts)) or real(contacts))
    watcher = dr.RaceWatcher()
    contacts = (Contact(50.0, "Driver 1", "Driver 2"),)
    for now in (100.0, 101.0, 102.0):
        watcher.update([car(1, 1), car(2, 2, distance=500.0)], contacts, now, "RACE1", TRACK)
    assert calls == [1]
    # Replay: incident still ahead of replay time, looked at again until it happened
    watcher = dr.RaceWatcher()
    calls.clear()
    ahead = (Contact(105.0, "Driver 1", "Driver 2"),)
    for now in (100.0, 101.0, 106.0, 107.0):
        events = watcher.update([car(1, 1), car(2, 2, distance=500.0)], ahead, now, "RACE1", TRACK)
    assert calls == [1, 1, 1] and events == []
    assert any(key[0] == 105.0 for key in watcher.seen_incidents)


def test_hidden_page_lists_made_once_shown(director_page):
    page, backend = director_page, director_page.backend
    backend._shown = False
    poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=200.0)))
    assert backend.carRows.rowCount() == 0 and backend._stale
    assert backend.watcher.now == 100.0  # watcher & director go on
    backend.page_shown()
    assert backend.carRows.rowCount() == 2 and not backend._stale
    wait_requests(backend.request_state)
    backend._timer.stop()


def test_state_requests_keep_one_connection(director_page):
    page = director_page
    made = []
    connection = page.game.connection

    def counted(*args, **kwargs):
        made.append(1)
        return connection()

    from neopedal.ui import game_rest

    game_rest.GameConnection = counted  # restored by monkeypatch of the fixture
    for now in (100.0, 101.0, 102.0):
        poll(page, race_answers(now, car(1, 1)))
    assert len(made) == 1


def test_search_cut_and_suggestion_by_number(director_page):
    page, backend = director_page, director_page.backend
    cars = (car(7, 1, distance=2040.0), car(77, 2, distance=2000.0, driver="Zoé Lefèvre"), car(3, 3, distance=500.0))
    poll(page, race_answers(100.0, *cars, focus=3))
    backend.setSearch("7")
    assert [row["slot"] for row in backend.carRows.rows] == [7, 77]
    backend.setSearch("zoe")  # accents & case ignored
    assert [row["slot"] for row in backend.carRows.rows] == [77]
    backend.cutToFirstMatch()
    wait_commands(backend)
    assert page.game.sent[-1] == ("PUT", "/rest/watch/focus/77")
    backend.setSearch("")
    assert backend.carRows.rowCount() == 3
    key = backend.suggestionRows.rows[0]["key"]
    backend.takeSuggestionAt(0)
    assert backend.director.shot.key == key
    backend.takeSuggestionAt(9)  # no such suggestion: nothing


def test_game_camera_changes_followed_without_holding_director(director_page):
    page, backend = director_page, director_page.backend
    cars = (car(1, 1, distance=2000.0), car(2, 2, distance=1000.0), car(3, 3, distance=400.0))
    poll(page, race_answers(100.0, *cars, focus=1))
    backend.setMode(2)
    backend.setFollowGameCuts(False)
    backend.director.hold_until = 0.0
    backend.last_cut = 0.0
    poll(page, race_answers(101.0, *cars, focus=3))  # another app put car 3 on air
    assert backend.on_air_slot == 3 and backend.director.hold_until == 0.0
    from neopedal.ui.quick import director_backend

    assert director_backend.load_page_settings()["follow_game_cuts"] is False


def test_battle_trend_per_lap_and_pit_lane_timer(director_page):
    page, backend = director_page, director_page.backend
    battle = dr.Battle(1, 2, "GT3", 1, 0.5, -0.004, 90.0)
    assert backend.trend_text(battle, car(2, 2, last=100.0)) == "-0.4 s/lap"
    assert backend.trend_text(battle._replace(trend=0.0002), car(2, 2, last=100.0)) == ""
    assert backend.trend_text(battle, None) == ""
    poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=500.0)))
    poll(page, race_answers(101.0, car(1, 1), car(2, 2, distance=500.0, in_pit=True, speed=20.0)))
    poll(page, race_answers(110.0, car(1, 1), car(2, 2, distance=500.0, in_pit=True, pit_state="STOPPED")))
    poll(page, race_answers(125.0, car(1, 1), car(2, 2, distance=500.0, in_pit=True, pit_state="STOPPED")))
    row = next(row for row in backend.pitRows.rows if row["slot"] == 2)
    assert row["status"] == "Pit lane 24 s · Stopped 15 s"


def test_stint_unknown_until_pit_exit_seen():
    watcher = dr.RaceWatcher()
    watcher.update([car(1, 1, laps=40, pitstops=2), car(2, 2, laps=40, distance=500.0)], (), 100.0, "RACE1", TRACK)
    assert watcher.stint_laps(car(1, 1, laps=41, pitstops=2)) == -1  # joined after its last stop
    assert watcher.stint_laps(car(2, 2, laps=41)) == 41  # never stopped: since the start
    assert watcher.stint_laps(car(3, 3, laps=41, pitstops=1)) == -1  # never seen



# Pictures, tyres, forecast, game on another computer, events log, contact severity
def test_contact_severity_from_speed_lost():
    watcher = dr.RaceWatcher()
    def cars(speed1, speed2):
        return [car(1, 1, speed=speed1), car(2, 2, distance=600.0, speed=speed2),
                car(3, 3, distance=1200.0, speed=60.0)]
    watcher.update(cars(60.0, 60.0), (), 100.0, "RACE1", TRACK)
    watcher.update(cars(60.0, 60.0), (), 101.0, "RACE1", TRACK)
    heavy = (Contact(101.5, "Driver 1", "Driver 2"),)
    watcher.update(cars(25.0, 58.0), heavy, 102.0, "RACE1", TRACK)
    key = next(iter(watcher.severity))
    assert watcher.severity[key] == pytest.approx(1 - 25 / 60, abs=0.01)  # car 1 lost most of its speed
    light = (*heavy, Contact(102.5, "Driver 2", "Driver 3"))
    watcher.update(cars(30.0, 57.0), light, 103.0, "RACE1", TRACK)
    light_key = next(key for key in watcher.severity if "Driver 3" in key)
    assert watcher.severity[light_key] < dr.LIGHT
    director = dr.Director()
    events = [event for event in watcher.measuring]
    scores = {candidate.key: candidate.score for candidate in director.candidates(
        events, [], cars(30.0, 57.0), 103.0, 0.0, True, severity=watcher.severity)}
    assert scores[key] > dr.PRIORITY[dr.CONTACT] and scores[light_key] < dr.PRIORITY[dr.CONTACT] * 0.6


def test_forecast_and_tyres(ui_env):
    from neopedal.ui.quick import director_backend as db

    answer = {"RACE": {"START": {"WNV_RAIN_CHANCE": {"currentValue": 10}, "WNV_TEMPERATURE": {"currentValue": 21.4},
                                 "WNV_SKY": {"stringValue": "Cloudy"}},
                       "NODE_50": {"WNV_RAIN_CHANCE": {"currentValue": 80}}},
              "PRACTICE": {}}
    assert db.parse_forecast(answer, "RACE1") == [
        {"label": "Start", "rain": "10%", "temperature": "21°C", "sky": "Cloudy", "wet": False, "celsius": 21.4},
        {"label": "50%", "rain": "80%", "temperature": "", "sky": "", "wet": True, "celsius": -1000.0}]
    assert db.parse_forecast(None, "RACE1") == [] and db.parse_forecast(answer, "QUALIFY1") == []

    class Reader:
        class vehicle:
            total_vehicles = staticmethod(lambda: 2)
            slot_id = staticmethod(lambda index: (7, 9)[index])

        class tyre:
            compound_name = staticmethod(lambda index: (("Soft",) * 2 + ("Medium",) * 2, ("Wet",) * 4)[index])

    assert db.read_tyres(Reader()) == {7: ("S", "M"), 9: ("W", "W")}
    assert db.read_tyres(object()) == {}


def test_tyres_logos_game_computer_and_log(director_page, monkeypatch):
    from neopedal.ui.quick import director_backend as db

    page, backend = director_page, director_page.backend
    monkeypatch.setattr(db.DirectorBackend, "read_tyres", staticmethod(lambda: {1: ("W", "W"), 2: ("S", "M")}))
    poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=600.0)))
    rows = {row["slot"]: row for row in backend.carRows.rows}
    assert (rows[2]["tyreFront"], rows[2]["tyreRear"]) == ("S", "M") and "brandLogo" in rows[1]
    backend.selectCar(2)
    assert backend.sheet["tyres"] == "S/M"
    # Game on another computer: no shared memory (another session), commands & requests to that address
    made = []
    from neopedal.ui import game_rest

    connection = page.game.connection
    monkeypatch.setattr(game_rest, "GameConnection", lambda *args, **kwargs: made.append(kwargs) or connection())
    backend.setGameHost("192.168.1.20")
    wait_requests(backend.request_state)
    backend._timer.stop()
    assert backend.game_address()[0] == "192.168.1.20" and made[-1]["address"][0] == "192.168.1.20"
    poll(page, race_answers(101.0, car(1, 1), car(2, 2, distance=600.0)))
    assert backend.tyres == {}
    backend.setGameHost("localhost")
    wait_requests(backend.request_state)
    backend._timer.stop()
    assert backend.game_address() is None and backend.local_game()
    # Events log: one line per live event as it comes
    backend.setLogEvents(True)
    poll(page, race_answers(102.0, car(1, 1), car(2, 2, distance=600.0), contacts=((101.8, "Driver 1", "Immovable"),)))
    with open(backend.log_path(), encoding="utf-8-sig") as file:
        lines = file.read().splitlines()
    assert lines[0].startswith("Time,Session time") and "#1 Driver 1 hits the wall" in lines[1]



# Broadcast graphics (stream overlay server source)
def test_director_feed_long_poll():
    import threading
    import time as clock

    from neopedal.stream_director import DirectorFeed

    feed = DirectorFeed()
    assert not feed.watched()
    feed.publish({"a": 1})
    version, body = feed.wait(0, timeout=0.01)
    assert version == 1 and json.loads(body) == {"a": 1} and feed.watched()
    feed.publish({"a": 1})  # same state: no new version
    assert feed.version == 1
    threading.Timer(0.05, lambda: feed.publish({"a": 2})).start()
    begin = clock.monotonic()
    version, body = feed.wait(1, timeout=2.0)  # waits for the next state, answered as soon as it comes
    assert version == 2 and json.loads(body) == {"a": 2} and clock.monotonic() - begin < 1.0
    assert feed.wait(2, timeout=0.01)[0] == 2  # nothing new: same state once timeout passed


def test_graphics_source_routes(ui_env, monkeypatch):
    import threading
    import urllib.request

    from neopedal.stream_director import director_feed
    from neopedal.stream_overlay import StreamHandler, StreamServer, streamoverlay
    from tests.test_stream_overlay import free_port

    port = free_port()
    StreamHandler.token = streamoverlay.access_token()
    server = StreamServer(("127.0.0.1", port), StreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    token = StreamHandler.token
    try:
        director_feed.publish({"live": True, "tower": []})
        base = f"http://127.0.0.1:{port}"
        page = urllib.request.urlopen(f"{base}/director?token={token}", timeout=5).read().decode("utf-8")
        assert "/api/director" in page and "<title>Broadcast Director</title>" in page
        data = json.loads(urllib.request.urlopen(f"{base}/api/director?v=0&token={token}", timeout=5).read())
        assert data["v"] == director_feed.version and data["full"]
        assert data["state"]["live"] is True and data["state"]["tower"] == []
        # Next answers: only the sections changed since the version the source has
        version = data["v"]
        director_feed.publish({**{key: None for key in data["state"]}, "live": True, "tower": [1]})
        data = json.loads(urllib.request.urlopen(f"{base}/api/director?v={version}&token={token}", timeout=5).read())
        assert data["state"] == {"tower": [1]} and not data["full"] and data["v"] == version + 1
        index = urllib.request.urlopen(f"{base}/?token={token}", timeout=5).read().decode("utf-8")
        assert "/director" not in index  # source of the Broadcast Director page only
        try:
            urllib.request.urlopen(f"{base}/api/director?v=0&token=wrong", timeout=5)
            raise AssertionError("no access without token")
        except urllib.error.HTTPError as error:
            assert error.code == 403
    finally:
        server.shutdown()
        director_feed.clear()


def test_graphics_state_and_settings(director_page, monkeypatch):
    from neopedal.stream_director import director_feed
    from neopedal.ui.quick import director_backend as db

    page, backend = director_page, director_page.backend
    published = []
    monkeypatch.setattr(director_feed, "publish", published.append)
    monkeypatch.setattr(director_feed, "watched", lambda: True)
    cars = (car(1, 1, distance=2040.0, grid=2, driver="Lena Hartmann"), car(2, 2, distance=2000.0, grid=1),
            car(3, 3, distance=400.0, in_pit=True))
    poll(page, race_answers(100.0, *cars, focus=2, info={"endEventTime": 3700.0}))
    state = published[-1]
    assert [row["name"] for row in state["tower"]] == ["L. Hartmann", "D. 2", "D. 3"]
    assert state["tower"][1]["air"] and state["tower"][2]["pit"] and state["tower"][0]["change"] == 1
    assert not state["tower"][1]["close"] and state["tower"][1]["gapClass"] == "+0.8"  # 40 m at 50 m/s
    assert state["onAir"]["name"] == "Driver 2" and state["clock"] == {"text": "1:00:00", "label": "Remaining"}
    cut = state["cut"]
    # Battle on air: battle card state
    backend.takeSuggestion(next(row["key"] for row in backend.suggestionRows.rows if row["kind"] == dr.BATTLE))
    state = published[-1]
    assert state["battle"]["ahead"]["name"] == "L. Hartmann" and state["battle"]["gap"] == "0.8 s"
    assert state["cut"] == cut  # same car on air: driver card not shown again
    # Banners: live events of banner kinds, with the event that just happened marked fresh
    poll(page, race_answers(101.0, *cars, contacts=((100.6, "Driver 3", "Driver 1"),)))
    backend.add_events([dr.Event("fastest|x", dr.FASTEST, 100.5, (1,), ("Lena Hartmann",), "GT3", 1, 88.0)])
    backend.publish_graphics(force=True)
    events = published[-1]["events"]
    assert [event["id"] for event in events] == ["fastest|x"] and events[0]["fresh"]
    # Settings: kept, checked
    backend.setGraphic("towerMode", "air")
    backend.setGraphic("towerMode", "nope")
    backend.setGraphic("towerRows", 1)
    backend.setGraphic("hidden", True)
    backend.setGraphic("unknown", 3)
    assert backend.graphics["towerMode"] == "air" and backend.graphics["towerRows"] == 3 and backend.graphics["hidden"]
    assert published[-1]["graphics"]["hidden"]
    assert db.load_page_settings()["graphics"]["towerMode"] == "air"
    assert db.graphics_setting({"towerMode": "x", "towerRows": "9", "card": False})["towerMode"] == "class"
    assert db.graphics_setting({"towerRows": "9", "card": False})["towerRows"] == 12
    assert db.short_name("Tobias Mueller#7949") == "T. Mueller" and db.short_name("Senna") == "Senna"
    # Source address only while stream overlays run
    from neopedal.stream_overlay import streamoverlay

    monkeypatch.setattr(type(streamoverlay), "running", property(lambda self: False))
    assert backend.graphicsUrl == ""
    monkeypatch.setattr(type(streamoverlay), "running", property(lambda self: True))
    assert "/director?token=" in backend.graphicsUrl


def test_pit_radar_of_car_on_air(director_page, monkeypatch):
    from neopedal.stream_director import director_feed

    # Cars near the car in the pit lane, closest first, across the start line too
    target = car(1, 1, distance=10.0, in_pit=True)
    cars = [target, car(2, 2, distance=14.0, in_pit=True), car(3, 3, distance=TRACK - 30.0, in_pit=True),
            car(4, 4, distance=11.0), car(5, 5, distance=500.0, in_pit=True), car(6, 6, distance=20.0, in_pit=True,
                                                                                 garage=True)]
    radar = dr.pit_radar(target, cars, TRACK)
    assert [(item.slot, round(item.distance), item.alongside) for item in radar] == [(2, 4, True), (3, -40, False)]
    assert dr.pit_radar(car(1, 1), cars, TRACK) == []  # not in the pit lane
    # Graphics & desk
    page, backend = director_page, director_page.backend
    published = []
    monkeypatch.setattr(director_feed, "publish", published.append)
    monkeypatch.setattr(director_feed, "watched", lambda: True)
    poll(page, race_answers(100.0, *cars, focus=1))
    radar = published[-1]["pitRadar"]
    assert [row["number"] for row in radar["rows"]] == ["2", "3"] and radar["rows"][0]["alongside"]
    assert radar["rows"][1]["distance"] == "40 m" and not radar["rows"][1]["ahead"]
    assert radar["count"] == "1 cars approaching"
    assert [row["number"] for row in backend.onAir["pitRadar"]] == ["2", "3"]
    backend.setGraphic("pitRadar", False)
    assert published[-1]["pitRadar"] is None
    backend.setGraphic("pitRadarRange", 5000)
    assert backend.graphics["pitRadarRange"] == 400


def test_overlays_follow_car_on_air_and_stop(director_page, monkeypatch):
    """Option on: spectate mode on the car on air; option off: spectate mode off (overlays back to own car)"""
    from neopedal.api_control import api
    from neopedal.setting import cfg

    page, backend = director_page, director_page.backend
    setups = []
    monkeypatch.setattr(type(api), "setup", lambda self: setups.append(1))
    monkeypatch.setitem(cfg.api, "enable_player_index_override", False)
    poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=600.0), focus=2))
    backend.setFollowOverlays(True)
    assert cfg.api["enable_player_index_override"] and cfg.api["player_index"] == 2 and setups
    backend.cutToCar(1)
    assert cfg.api["player_index"] == 1
    backend.setFollowOverlays(False)
    assert not cfg.api["enable_player_index_override"] and len(setups) == 3
    backend.setFollowOverlays(False)  # already off: nothing done again
    assert len(setups) == 3
