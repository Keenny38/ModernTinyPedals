"""Broadcast graphics: championship CSV, graphics of the director (train, replay, onboard, qualifying, map, on
demand), timing table, layout editors (graphics & stream layout), QML panels"""

import json
import urllib.error
import urllib.request

import pytest
from PySide6.QtCore import QCoreApplication, QObject

from neopedal.process import championship as ch
from neopedal.process import director as dr
from tests.test_broadcast_director import car, director_page, poll, race_answers  # noqa: F401
from tests.test_stream_overlay import get, parse_bundle, server  # noqa: F401


def post(url: str, body: bytes) -> int:
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


# Championship
def test_championship_csv_titles_classes_ties():
    text = ("Pos;Pilote;Équipe;Classe;Points\n1;A. Martin;Vortex;Hypercar;98\n2;K. Sato;Apex;Hypercar;120,5\n"
            "3;L. Rossi;GT Team;LMGT3;60\n4;B. Lee;X;LMGT3;60\n")
    rows = ch.parse_championship(text)
    assert [(row.name, row.points, row.team, row.car_class) for row in rows[:2]] == [
        ("A. Martin", 98.0, "Vortex", "Hypercar"), ("K. Sato", 120.5, "Apex", "Hypercar")]
    assert ch.classes(rows) == ["Hypercar", "LMGT3"]
    assert [(place, row.name) for place, row in ch.standings(rows, "Hypercar")] == [(1, "K. Sato"), (2, "A. Martin")]
    assert [(place, row.name) for place, row in ch.standings(rows, "LMGT3")] == [(1, "B. Lee"), (1, "L. Rossi")]
    assert len(ch.standings(rows)) == 4
    # No titles, comma separated: first text column is the driver, last number the points
    rows = ch.parse_championship("Driver One,Team A,45\nDriver Two,Team B,50\n")
    assert [(row.name, row.points) for row in rows] == [("Driver One", 45.0), ("Driver Two", 50.0)]
    # English titles, team championship, byte order mark
    rows = ch.parse_championship("﻿Team,Pts,#\nVortex,77,13\n")
    assert [(row.name, row.points, row.number) for row in rows] == [("Vortex", 77.0, "13")]
    assert ch.parse_championship("") == [] and ch.parse_championship("just text\nmore text") == []
    assert ch.points_text(12.0) == "12" and ch.points_text(12.5) == "12.5"


# Graphics of the director
@pytest.fixture
def english():
    from neopedal import i18n

    i18n.set_language("English")


def test_graphics_train_tower_onboard_map_replay(director_page, english, monkeypatch):  # noqa: F811
    page, backend = director_page, director_page.backend
    for key in ("onboard", "map", "train"):
        backend.setGraphic(key, True)
    cars = [car(1, 1, distance=1100.0, best=90.0, last=91.0, penalties=1, grid=3),
            car(2, 2, distance=1080.0, grid=1), car(3, 3, distance=1060.0, grid=2), car(4, 4, distance=200.0)]
    answers = race_answers(100.0, *cars, focus=2)
    answers["/rest/watch/standings"][0]["carPosition"] = {"x": 10.0, "y": 0.0, "z": -20.0}
    poll(page, answers)
    backend.set_on_air(2, dr.BATTLE)
    state = backend.graphics_state()
    assert [item["number"] for item in state["train"]["cars"]] == ["1", "2", "3"]
    assert [item["air"] for item in state["train"]["cars"]] == [False, True, False]
    first = state["tower"][0]
    assert (first["lap"], first["lapId"], first["pen"], first["lapTone"]) == ("1:31.000", 10, 1, "")
    assert state["onboard"]["number"] == "2" and state["onboard"]["rpmMax"] == 9000.0
    assert state["map"]["cars"]["1"][:2] == [10.0, 20.0] and state["map"]["cars"]["2"][4] is True
    assert state["quali"] is None and state["grid"] is None and state["labels"]["pen"] == "PEN"
    # Live feed: game data of the last answer when shared memory has none (speed in app unit)
    monkeypatch.setattr(type(backend), "reader", staticmethod(lambda: None))
    live = backend.live_state()
    assert live["onboard"]["speed"] == 180.0 and live["onboard"]["gear"] is None
    cars = live["cars"]  # flat: slot, x, y of each car
    assert cars[cars.index(1):cars.index(1) + 3] == [1, 10, 20] and len(cars) == 12
    # Instant replay of a contact: both cars, banners held by the source
    backend.add_events([dr.Event("contact|t", dr.CONTACT, 99.0, (1, 2), ("Driver 1", "Driver 2"), "GT3")])
    backend.replayEvent("contact|t")
    info = backend.graphics_state()["replayInfo"]
    assert info["mode"] == "duel" and info["ahead"]["number"] == "1" and info["behind"]["number"] == "2"
    backend.backToLive()
    assert backend.graphics_state()["replayInfo"] is None
    backend.add_events([dr.Event("stopped|t", dr.STOPPED, 99.5, (3,), ("Driver 3",), "GT3")])
    backend.replayEvent("stopped|t")
    info = backend.graphics_state()["replayInfo"]
    assert info["mode"] == "driver" and info["car"]["number"] == "3" and info["kind"] == "Stopped Car"
    backend.backToLive()


def test_qualifying_lap_graphic(director_page, english):  # noqa: F811
    page, backend = director_page, director_page.backend
    cars = [car(1, 1, best=90.0, best_sector1=30.0, best_sector2=60.0),
            car(2, 2, best=91.0, current_sector1=29.8, sector=2)]
    poll(page, race_answers(200.0, *cars, focus=2, info={"session": "QUALIFY1"}))
    backend.set_on_air(2, dr.MANUAL)
    lap = backend.graphics_state()["quali"]
    assert (lap["position"], lap["delta"], lap["deltaTone"], lap["target"]) == ("P2", "-0.200", "gain", "1:30.000")
    assert lap["sectors"][0]["text"] == "29.800" and lap["running"] and lap["lapStart"] == 199.0
    backend.setGraphic("quali", False)
    assert backend.graphics_state()["quali"] is None


def test_on_demand_grid_event_results_championship(director_page, english, tmp_path):  # noqa: F811
    page, backend = director_page, director_page.backend
    cars = [car(1, 1, grid=3, best=90.0), car(2, 2, grid=1), car(3, 3, grid=0, finish="FSTAT_DNF"), car(4, 4, grid=2)]
    poll(page, race_answers(300.0, *cars, info={"endEventTime": 3900.0}))
    backend.showOnDemand("grid")
    state = backend.graphics_state()
    assert [item["number"] for item in state["grid"]["cars"]] == ["2", "4", "1", "3"]
    assert state["event"] is None and backend.onDemand == "grid"
    backend.showOnDemand("event")
    event = backend.graphics_state()["event"]
    assert event["track"] == "Test Ring" and ["Cars", "4"] in event["schedule"]
    assert ["Remaining", "1:00:00"] in event["schedule"]
    backend.showOnDemand("event")  # same again: hidden
    assert backend.onDemand == "" and backend.graphics_state()["event"] is None
    backend.captureResults()
    results = backend.graphics_state()["results"]
    assert backend.onDemand == "results" and results["rows"][0]["gap"] == "Leader"
    assert results["rows"][2]["status"] == "Retired" and backend.captureText == results["subtitle"]
    backend.clearResults()
    assert backend.onDemand == "" and backend.captureText == ""
    # Championship from a CSV file, kept between sessions
    path = tmp_path / "Endurance Cup.csv"
    path.write_text("Driver;Class;Points\nA;Hyper;50\nB;Hyper;80\nC;GT3;20\n", encoding="utf-8")
    assert backend.import_championship(str(path))
    assert backend.championshipNames == ["Endurance Cup"] and backend.championshipClasses == ["Hyper", "GT3"]
    backend.setChampionshipClass("Hyper")
    backend.showOnDemand("champ")
    standings = backend.graphics_state()["champ"]
    assert standings["title"] == "Endurance Cup" and standings["subtitle"] == "Hyper"
    assert [(row["name"], row["points"], row["medal"]) for row in standings["rows"]] == [("B", "80", 1), ("A", "50", 2)]
    from neopedal.ui.quick import director_backend as db

    assert [item["name"] for item in db.load_championships()] == ["Endurance Cup"]
    bad = tmp_path / "empty.csv"
    bad.write_text("nothing here", encoding="utf-8")
    assert not backend.import_championship(str(bad)) and backend.noticeError
    backend.removeChampionship()
    assert backend.championshipNames == [] and backend.onDemand == ""


def test_graphics_settings_choices_and_limits(director_page):  # noqa: F811
    backend = director_page.backend
    backend.setGraphic("onboardStyle", "helmet")
    backend.setGraphic("temperatureUnit", "fahrenheit")
    backend.setGraphic("opacity", 5)
    backend.setGraphic("onboardStyle", "nonsense")
    settings = backend.graphicsSettings
    assert (settings["onboardStyle"], settings["temperatureUnit"], settings["opacity"]) == ("helmet", "fahrenheit", 30)
    from neopedal.ui.quick import director_backend as db

    assert db.temperature_text(20.0, "fahrenheit") == "68°F" and db.temperature_text(20.0, "celsius") == "20°C"
    kept = db.graphics_setting({"opacity": 250, "towerMode": "bad", "onboard": "yes"})
    assert kept["opacity"] == 100 and kept["towerMode"] == "class" and kept["onboard"] is False


def test_timing_table_views_and_columns(director_page, english):  # noqa: F811
    page, backend = director_page, director_page.backend
    poll(page, race_answers(100.0, car(1, 1, distance=1040.0, best=90.0), car(2, 2, distance=1000.0, pitstops=1)))
    backend.setTimingOpen(True)
    model = backend.timingRows
    assert model.rowCount() == 2
    row = model.rows[1]
    from neopedal.ui.quick import director_backend as db

    assert set(db.TIMING_COLUMNS) <= set(row) and row["interval"] == "+0.8" and row["battle"]
    assert row["pits"] == "1" and model.rows[0]["bestTone"] == "fastest"
    columns = [column["key"] for column in backend.timingColumns]
    assert columns == list(db.TIMING_VIEWS["race"])
    backend.moveTimingColumn(0, 2)
    assert [column["key"] for column in backend.timingColumns][:3] == ["classPos", "change", "pos"]
    backend.toggleTimingColumn("team")
    backend.toggleTimingColumn("pos")
    shown = [column["key"] for column in backend.timingColumns]
    assert "team" in shown and "pos" not in shown
    assert next(item for item in backend.timingChoices if item["key"] == "team")["shown"]
    backend.setTimingView(1)
    assert backend.timingViewIndex == 1 and [column["key"] for column in backend.timingColumns] == list(
        db.TIMING_VIEWS["qualifying"])
    backend.setTimingView(0)
    backend.resetTimingColumns()
    assert [column["key"] for column in backend.timingColumns] == list(db.TIMING_VIEWS["race"])
    saved = db.load_page_settings()
    assert saved["timing_view"] == "race" and db.timing_setting({"race": ["bogus", "driver", "driver"]})["race"] == [
        "driver"]
    backend.setTimingOpen(False)


def test_graphics_panels_load_without_warnings(director_page):  # noqa: F811
    from PySide6.QtCore import qInstallMessageHandler

    page = director_page
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        root = page.view.rootObject()
        graphics = root.findChild(QObject, "graphicsPopup")
        for tab in (0, 1, 2):
            graphics.setProperty("tab", tab)
            graphics.setProperty("visible", True)
            QCoreApplication.processEvents()
        graphics.setProperty("visible", False)
        timing = root.findChild(QObject, "timingTable")
        timing.setProperty("visible", True)
        poll(page, race_answers(100.0, car(1, 1, distance=1040.0), car(2, 2, distance=1000.0)))
        QCoreApplication.processEvents()
        assert page.backend.timing_open
        timing.setProperty("visible", False)
        QCoreApplication.processEvents()
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


# Layout editors (browser): broadcast graphics & stream layout
def test_director_layout_editor_endpoints(server):  # noqa: F811
    from neopedal import stream_director as sd
    from neopedal.setting import cfg

    status, body, _ = get(server.url("/director", "edit=1"))
    assert status == 200 and b"setupEditor" in body
    status, body, _ = get(server.url("/api/director", "demo=1"))
    demo = json.loads(body)["state"]
    assert status == 200 and demo["demo"] and all(demo[key] for key in ("tower", "train", "grid", "event", "results",
                                                                         "champ", "quali", "onboard"))
    layout = {"tower": [0.1, 0.2, 1.2], "bogus": [1, 1, 1], "card": ["x", 1, 1], "clock": [9, -9, 99]}
    assert post(server.url("/api/director/layout"), json.dumps(layout).encode()) == 200
    expected = {"tower": [0.1, 0.2, 1.2], "clock": [1.5, -0.5, 3.0]}
    status, body, _ = get(server.url("/api/director", "v=0"))
    assert json.loads(body)["layout"] == expected
    with open(f"{cfg.path.config}broadcast_layout.json", encoding="utf-8") as file:
        assert json.load(file) == {"": expected}
    assert post(server.url("/api/director/layout"), b"{not json") == 400
    assert post(server.url("/api/director/layout").replace("token=", "token=x"), b"{}") == 403
    assert post(server.url("/api/director/layout"), b"x" * (sd.MAX_LAYOUT_BODY + 1)) == 413
    assert post(server.url("/api/nothing"), b"{}") == 404
    assert post(server.url("/api/director/layout"), b"{}") == 200  # every graphic back to its place
    assert sd.director_layout.get() == {}
    # Live feed & track outline
    sd.live_feed.publish({"onboard": None, "cars": [[1, 2.0, 3.0]]})
    status, body, _ = get(server.url("/api/director/live", "v=0"))
    assert json.loads(body)["live"]["cars"] == [[1, 2.0, 3.0]]
    sd.track_outline.set("Ring|3", [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)], [(1.0, 1.0)])
    status, body, _ = get(server.url("/api/director/track"))
    outline = json.loads(body)
    assert outline["key"] == "Ring|3" and outline["width"] == 10.0 and outline["pit"] == [[1.0, 1.0]]


def test_stream_layout_places(server, monkeypatch):  # noqa: F811
    from neopedal import stream_overlay
    from neopedal.ui.quick import stream_backend

    places = {"gear": [0.5, 0.25, 1.5], "../x": [0, 0, 1]}
    assert post(server.url("/api/layout", "crop=16:9"), json.dumps(places).encode()) == 200
    status, body, _ = get(server.url("/api/frames", "view=layout&seq=0&crop=16:9"))
    assert parse_bundle(body)[0]["places"] == {"gear": [0.5, 0.25, 1.5]}
    assert parse_bundle(get(server.url("/api/frames", "view=layout&seq=0"))[1])[0]["places"] == {}
    assert "places" not in parse_bundle(get(server.url("/api/frames", "view=gear&seq=0"))[1])[0]
    status, body, _ = get(server.url("/layout", "crop=16:9&edit=1"))
    assert status == 200 and b'"save": "Save"' in body and b"drawEditor" in body
    assert stream_overlay.layout_section("16:9") == "16:9" and stream_overlay.layout_section("x") == "screen"
    # Page: format 16:9 placed, reset
    monkeypatch.setattr(stream_backend, "streamoverlay", server)
    opened = []
    monkeypatch.setattr(stream_backend.StreamOverlaysBackend, "openInBrowser", lambda self, url: opened.append(url))
    backend = stream_backend.StreamOverlaysBackend()
    try:
        assert backend.layoutPlaced
        backend.editLayout()
        assert opened and opened[0].startswith(server.url("/layout")) and opened[0].endswith("&crop=16:9&edit=1")
        backend.resetLayout()
        assert not backend.layoutPlaced and stream_overlay.stream_layout.get("16:9") == {}
    finally:
        backend.release()
        backend.deleteLater()


# Sections of the graphics state, layout presets, sources with some graphics only
def test_section_feed_sends_changed_sections_only():
    from neopedal.stream_director import SectionFeed

    feed = SectionFeed()
    feed.publish({"tower": [1], "clock": {"text": "1:00"}})
    version, sections, full = feed.sections(0)
    assert full and set(sections) == {"tower", "clock"} and version == 1
    feed.publish({"tower": [1], "clock": {"text": "0:59"}})
    version, sections, full = feed.sections(1)
    assert not full and sections == {"clock": b'{"text":"0:59"}'} and version == 2
    feed.publish({"tower": [1]})  # section gone: sent as null
    assert feed.sections(2)[1] == {"clock": b"null"}
    feed.publish({"tower": [1]})  # nothing changed: same version
    assert feed.version == 3
    assert feed.sections(99)[2]  # version from another run: everything


def test_layout_presets_and_partial_sources(server, director_page, monkeypatch):  # noqa: F811
    from PySide6.QtGui import QGuiApplication

    from neopedal import stream_director as sd
    from neopedal import stream_overlay as so

    backend = director_page.backend
    assert post(server.url("/api/director/layout", "preset=race"), b'{"tower": [0.5, 0.5, 1]}') == 200
    assert post(server.url("/api/director/layout", "preset=bogus"), b"{}") == 400
    assert sd.director_layout.get("race") == {"tower": [0.5, 0.5, 1.0]} and sd.director_layout.get("") == {}
    _status, body, _ = get(server.url("/api/director", "v=0"))
    assert json.loads(body)["layout"] == {} and json.loads(body)["preset"] == ""
    backend.setLayoutPreset("race")  # sources without their own preset follow
    assert backend.layoutPreset == "race" and sd.director_layout.active() == "race"
    _, body, _ = get(server.url("/api/director", "v=0"))
    assert json.loads(body)["layout"] == {"tower": [0.5, 0.5, 1.0]}
    _, body, _ = get(server.url("/api/director", "v=0&preset="))  # source with the default preset
    assert json.loads(body)["layout"] == {}
    backend.nextLayoutPreset()
    assert backend.layoutPreset == "post"
    with open(f"{sd.director_layout.folder()}broadcast_layout.json", encoding="utf-8") as file:
        assert json.load(file)["__active__"] == "post"
    monkeypatch.setattr(so, "streamoverlay", server)
    backend.copyPartialUrl(["tower", "map", "bogus"], "race")
    copied = QGuiApplication.clipboard().text()
    assert copied.startswith(server.url("/director")) and copied.endswith("&only=tower,map&preset=race")
    assert {item["key"] for item in backend.graphicNames} == set(sd.GRAPHIC_IDS)
    backend.setLayoutPreset("")


def test_league_branding_files(server, director_page, tmp_path):  # noqa: F811
    import os

    from neopedal import stream_director as sd

    backend = director_page.backend
    picture = tmp_path / "league.png"
    picture.write_bytes(b"\x89PNG fake")
    assert backend.set_logo(str(picture))
    sponsors = os.path.join(sd.brand_folder(), "sponsors")
    os.makedirs(sponsors, exist_ok=True)
    with open(os.path.join(sponsors, "b sponsor.png"), "wb") as file:
        file.write(b"\x89PNG b")
    with open(os.path.join(sponsors, "notes.txt"), "w", encoding="utf-8") as file:
        file.write("not a picture")
    logo, pictures = sd.brand_pictures()
    assert logo.startswith("/api/director/brand/logo.png?t=") and len(pictures) == 1
    status, body, headers = get(server.url(pictures[0].split("?")[0]))
    assert status == 200 and body == b"\x89PNG b" and headers["Content-Type"] == "image/png"
    assert get(server.url("/api/director/brand/../config.json"))[0] == 404
    assert get(server.url("/api/director/brand/sponsors/notes.txt"))[0] == 404
    backend.setGraphic("brandName", "  Endurance Cup " + "x" * 80)
    backend.setGraphic("accent", "#12AB34")
    backend.setGraphic("accent", "red")  # not a color: kept
    state = backend.graphics_state()
    assert state["brand"]["name"].startswith("Endurance Cup") and len(state["brand"]["name"]) == 60
    assert state["graphics"]["accent"] == "#12AB34" and state["brand"]["logo"].startswith("/api/director/brand/logo")
    notes = tmp_path / "notes.txt"
    notes.write_text("x", encoding="utf-8")
    assert not backend.set_logo(str(notes))
    backend.clearLogo()
    assert sd.brand_pictures()[0] == ""


def test_message_countdown_and_automatic_graphics(director_page, english):  # noqa: F811
    import time

    page, backend = director_page, director_page.backend
    backend.showMessage("Race control", "  Red   flag ")
    assert backend.graphics_state()["message"] == {"id": 1, "title": "Race control", "text": "Red flag"}
    backend.hideMessage()
    assert backend.graphics_state()["message"] is None and backend.messageText == ""
    backend.startCountdown(2.0, "Start in")
    countdown = backend.graphics_state()["countdown"]
    assert countdown["label"] == "Start in" and 115_000 < countdown["endsAt"] - time.time() * 1000 <= 120_001
    assert backend.countdownRunning
    backend.stopCountdown()
    assert backend.graphics_state()["countdown"] is None
    # Formation lap: starting grid by itself, hidden once the race is green
    cars = [car(1, 1, grid=2), car(2, 2, grid=1)]
    poll(page, race_answers(10.0, *cars, info={"gamePhase": 3}))
    assert backend.onDemand == "grid" and backend.auto_shown == "grid"
    poll(page, race_answers(11.0, *cars, info={"gamePhase": 5}))
    assert backend.onDemand == ""
    poll(page, race_answers(12.0, *cars, info={"gamePhase": 3}))  # once a session
    assert backend.onDemand == ""
    # Winner: classification captured & shown, kept up to date while shown by the director
    backend.auto_graphics([dr.Event("winner|1", dr.WINNER, 12.0, (1,), ("Driver 1",), "GT3")])
    assert backend.onDemand == "results" and backend.captured is not None
    backend.showOnDemand("event")  # operator takes over
    assert backend.auto_shown == "" and backend.onDemand == "event"


def test_tower_onboard_map_details(director_page, english):  # noqa: F811
    page, backend = director_page, director_page.backend
    backend.setGraphic("map", True)
    backend.setGraphic("onboard", True)
    cars = [car(1, 1, distance=1300.0, best=90.0, pitstops=2, sector=1), car(2, 2, distance=1280.0, sector=2),
            car(3, 3, distance=2900.0, car_class="Hyper", in_pit=True, sector=2)]
    poll(page, race_answers(20.0, *cars, focus=2, info={"sectorFlag": ["UNKNOWN", "YELLOW", "UNKNOWN"]}))
    backend.set_on_air(2, dr.MANUAL)
    state = backend.graphics_state()
    first, second = state["tower"][0], state["tower"][1]
    assert first["fastest"] and first["stops"] == 2 and first["gapLeader"] == "" and second["gapLeader"] == "+0.4"
    assert state["onboard"]["ahead"] == "#1 +0.4"
    assert state["map"]["cars"]["3"][5] is True and state["map"]["yellowSectors"] == [False, True, False]
    assert state["map"]["sectors"] == []  # sector 2 seen in the pit lane only: not known yet
    poll(page, race_answers(21.0, *[cars[0], cars[1]._replace(distance=2700.0), cars[2]], focus=2))
    assert backend.graphics_state()["map"]["sectors"] == [0.325, 0.675]


def test_graphics_settings_new_choices(director_page):  # noqa: F811
    backend = director_page.backend
    for name, value in (("mapRotation", 90), ("mapRotation", 45), ("towerGap", "leader"), ("towerGap", "x"),
                        ("mapDots", 900), ("sponsorSeconds", 1)):
        backend.setGraphic(name, value)
    settings = backend.graphicsSettings
    assert (settings["mapRotation"], settings["towerGap"], settings["mapDots"], settings["sponsorSeconds"]) == (
        90, "leader", 200, 3)
    from neopedal.ui.quick import director_backend as db

    kept = db.graphics_setting({"mapRotation": 33, "accent": "#zz0000", "brandName": "a" * 99})
    assert kept["mapRotation"] == 0 and kept["accent"] == "#e5383b" and len(kept["brandName"]) == 60


def test_hotkeys_of_graphics(director_page):  # noqa: F811
    from neopedal.hotkey import command
    from neopedal.template.setting_shortcuts import SHORTCUTS_GENERAL

    backend = director_page.backend
    command.hotkey_director_starting_grid()
    assert backend.onDemand == "grid"
    command.hotkey_director_event_card()
    assert backend.onDemand == "event"
    command.hotkey_director_classification()
    assert backend.onDemand == "results" and backend.captured is not None
    command.hotkey_director_classification()  # shown: hidden
    assert backend.onDemand == ""
    command.hotkey_director_hide_graphics()
    assert backend.graphicsSettings["hidden"]
    command.hotkey_director_hide_graphics()
    command.hotkey_director_next_layout()
    assert backend.layoutPreset == "pre"
    backend.setLayoutPreset("")
    assert "director_next_layout" in SHORTCUTS_GENERAL and "director_championship" in SHORTCUTS_GENERAL


# Director: shown incidents, comebacks, overtake coming
def test_director_seen_comeback_and_overtake_camera():
    director = dr.Director()
    cars = [car(1, 1), car(2, 2), car(3, 3), car(4, 4)]
    events = [dr.Event("contact|1", dr.CONTACT, 99.0, (2, 1), ("Driver 2", "Driver 1"), "GT3")]
    fresh = director.candidates(events, [], cars, 100.0, 0.0, True)
    seen = director.candidates(events, [], cars, 100.0, 0.0, True, seen={"contact|1"})
    score = next(item.score for item in fresh if item.key == "contact|1")
    assert next(item.score for item in seen if item.key == "contact|1") == pytest.approx(score * dr.SEEN_SHARE)
    climbing = director.candidates([], [], cars, 100.0, 0.0, True, gained={4: 6})
    roam = {item.slot: item.score for item in climbing}
    plain = {item.slot: item.score for item in director.candidates([], [], cars, 100.0, 0.0, True)}
    assert roam[4] == pytest.approx(plain[4] + 6 * dr.CLIMB_BONUS)
    battle = dr.Battle(1, 2, "GT3", 1, 0.2, -0.1, 90.0)
    candidate = next(item for item in director.candidates([], [battle], cars, 100.0, 0.0, True)
                     if item.kind == dr.BATTLE)
    assert director.take(candidate, 1.0).camera == dr.OVERTAKE_CAMERA
    director.settings.camera_style = "keep"
    assert director.take(candidate, 2.0).camera == ""


# Race history of the drivers (results files)
def test_driver_history_from_race_files(tmp_path, monkeypatch):
    from neopedal.process import driver_history as dh
    from neopedal.process import results_file as rf

    def entry(name, cls, place, finished=True, swaps=()):
        return rf.Entry(name, "Team", "Car", "Car", cls, "1", 1, place, 1, place, 10, 90.0,
                        1000.0 if finished else 0.0, 1, "FINISHED" if finished else "DNF", "",
                        True, False, "", (), tuple(rf.Swap(driver, 1, 5) for driver in swaps))

    races = {
        "2026_10_01_20_00_00-70R1.xml": ("Spa", [entry("Ann Lee#12", "GT3", 1), entry("Bob Ray", "GT3", 2),
                                                  entry("Cid", "Hyper", 1, swaps=("Dee",))]),
        "2026_10_03_20_00_00-70R1.xml": ("Monza", [entry("Bob Ray", "GT3", 1), entry("Ann Lee", "GT3", 2, False)]),
        "2026_10_04_20_00_00-70Q1.xml": ("Monza", [entry("Ann Lee", "GT3", 1)]),  # qualifying: not a race
    }
    for name in races:
        (tmp_path / name).write_text("x", encoding="utf-8")

    def read(path, names=()):
        track, entries = races[path.replace("\\", "/").rsplit("/", 1)[-1]]
        return rf.SessionResult(path, "LMU", "", "", float(len(path)), "Race", "Race", track, track, "", 4000.0, "",
                                60, 0, 10, tuple(entries), ())

    monkeypatch.setattr(rf, "read_results", read)
    history = dh.DriverHistory()
    assert history.scan([str(tmp_path)]) and not history.scan([str(tmp_path)])  # read once
    stats = history.stats("ann lee", "Spa")
    assert (stats.starts, stats.wins, stats.podiums, stats.best_here) == (2, 1, 1, 1)
    assert history.stats("Dee").starts == 1 and history.stats("Nobody") is None
    assert history.head_to_head("Ann Lee", "Bob Ray") == (1, 1)
    assert history.head_to_head("Ann Lee", "Cid") == (0, 0)  # other class


def test_onboard_reads_shared_memory_of_car_on_air(director_page, english, monkeypatch):  # noqa: F811
    """Onboard of the car on air from the game data of the app (groups & readers of the real API): gear, rpm,
    pedals, 10 times a second (a reader of a missing group made it fall back to the speed
    of the game answer, once a second, without gear, rpm or pedals)"""
    from neopedal.adapter import _reader

    page, backend = director_page, director_page.backend
    backend.setGraphic("onboard", True)
    poll(page, race_answers(100.0, car(1, 1), car(7, 2, distance=600.0), focus=7))

    class Group:
        def __init__(self, **values):
            self.__dict__.update({name: (lambda index=None, value=value: value) for name, value in values.items()})

    class Reader:
        vehicle = Group(total_vehicles=2, speed=50.0, position_xyz=(1.0, 0.0, -2.0))
        engine = Group(gear=4, rpm=7200.0, rpm_max=9000.0)
        inputs = Group(throttle_raw=0.8, brake_raw=0.0)

    Reader.vehicle.slot_id = lambda index=None: (1, 7)[index]
    # Same group & reader names as the game data of the app
    groups = {"vehicle": _reader.Vehicle, "engine": _reader.Engine, "inputs": _reader.Inputs}
    from neopedal.adapter import APIDataReader

    assert set(groups) <= set(APIDataReader._fields)
    for group, base in groups.items():
        for name in vars(getattr(Reader, group)):
            assert hasattr(base, name), (group, name)
    monkeypatch.setattr(type(backend), "reader", staticmethod(lambda: Reader()))
    onboard = backend.live_state()["onboard"]
    assert (onboard["speed"], onboard["gear"], onboard["rpm"], onboard["throttle"]) == (180.0, 4, 7200, 0.8)
    assert "battery" not in onboard  # no battery on the onboard graphic
    from neopedal.ui.quick import director_backend as db

    assert db.LIVE_MS <= 100
