"""Race results: game results files (process/results_file.py), results page backend & Qt Quick page"""

import json
import os
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent

from tinypedal.process import results_file as rf

RACE_XML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE rF [
<!ENTITY rFEnt "rFactor Entity">
]>
<rFactorXML version="1.0">
<RaceResults>
<Setting>Multiplayer</Setting>
<ServerName>Test Server</ServerName>
<DateTime>1790000000</DateTime>
<TrackVenue>Circuit de la Sarthe</TrackVenue>
<TrackCourse>Circuit de la Sarthe</TrackCourse>
<TrackEvent>24 Heures du Mans</TrackEvent>
<TrackLength>13626.0</TrackLength>
<GameVersion>1.4200</GameVersion>
<Race>
<DateTime>1790000600</DateTime>
<Laps>2147483647</Laps>
<Minutes>20</Minutes>
<Stream>
<ChatMessage et="10.5">A Driver: good luck</ChatMessage>
<Incident et="120.0">Alice Driver(0) reported contact (150.50) with another vehicle Bob Racer(1)</Incident>
<Incident et="120.1">Bob Racer(1) reported contact (180.00) with another vehicle Alice Driver(0)</Incident>
<Incident et="300.0">Carl Slow(2) reported contact (900.00) with Immovable</Incident>
<Score et="301.0">Carl Slow(2) lap=2 point=1 t=10.000 et=301.000</Score>
<Penalty Driver="Bob Racer" ID="1" Penalty="Stop/Go" Time="10" Laps="0" Reason="Speeding In Pitlane" et="400.0">Bob Racer received Stop/Go penalty, 10s, 0laps for Speeding In Pitlane. Result: penalties=1</Penalty>
<TrackLimits Driver="Bob Racer" ID="1" Lap="2" WarningPoints="0.5" CurrentPoints="0.5" Resolution="5" et="450.0">Invalid Lap Cut Track</TrackLimits>
<TrackLimits Driver="Bob Racer" ID="1" Lap="2" WarningPoints="0.5" CurrentPoints="0.5" Resolution="5" et="450.0">Invalid Lap Cut Track</TrackLimits>
<TrackLimits Driver="Alice Driver" ID="0" Lap="2" WarningPoints="0" CurrentPoints="0" Resolution="7" et="460.0">No Further Action</TrackLimits>
</Stream>
<MostLapsCompleted>3</MostLapsCompleted>
<Driver>
<Name>Bob Racer</Name>
<TeamName>Team B</TeamName>
<VehName>Car B #2</VehName>
<CarType>Ferrari 499P</CarType>
<CarClass>Hyper</CarClass>
<CarNumber>2</CarNumber>
<isPlayer>1</isPlayer>
<GridPos>1</GridPos>
<Position>2</Position>
<ClassGridPos>1</ClassGridPos>
<ClassPosition>2</ClassPosition>
<Lap num="1" p="1" et="100.0" s1="30.0" s2="40.0" s3="30.5" topspeed="300.5" fcompound="0,Medium" rcompound="0,Medium">100.5000</Lap>
<Lap num="2" p="2" et="200.5" s1="29.0" s2="41.0" topspeed="301.0" fcompound="0,Medium" rcompound="0,Medium">--.----</Lap>
<Lap num="3" p="2" et="302.0" s1="29.5" s2="40.5" s3="30.0" topspeed="299.0" fcompound="1,Hard" rcompound="1,Hard" pit="1">100.0000</Lap>
<BestLapTime>100.0000</BestLapTime>
<FinishTime>302.5000</FinishTime>
<Laps>3</Laps>
<Pitstops>1</Pitstops>
<FinishStatus>Finished Normally</FinishStatus>
</Driver>
<Driver>
<Name>Alice Driver</Name>
<TeamName>Team A</TeamName>
<VehName>Car A #1</VehName>
<CarType>Toyota GR010</CarType>
<CarClass>Hyper</CarClass>
<CarNumber>1</CarNumber>
<isPlayer>1</isPlayer>
<GridPos>2</GridPos>
<Position>1</Position>
<ClassGridPos>2</ClassGridPos>
<ClassPosition>1</ClassPosition>
<Swap startLap="1" endLap="1">Zed Partner</Swap>
<Swap startLap="2" endLap="3">Alice Driver</Swap>
<Lap num="1" p="2" et="100.0" s1="30.2" s2="40.1" s3="30.6" topspeed="299.5" fuel="0.900" fuelUsed="0.030" ve="0.880" veUsed="0.040" twfl="0.990" twfr="0.980" twrl="0.990" twrr="0.990" fcompound="0,Medium" rcompound="0,Medium">100.9000</Lap>
<Lap num="2" p="1" et="200.9" s1="28.5" s2="39.5" s3="29.9" topspeed="302.0" fuel="0.860" fuelUsed="0.040" ve="0.840" veUsed="0.040" twfl="0.970" twfr="0.960" twrl="0.980" twrr="0.980" fcompound="0,Medium" rcompound="0,Medium">97.9000</Lap>
<Lap num="3" p="1" et="298.8" s1="29.0" s2="40.0" s3="30.0" topspeed="301.5" fcompound="0,Medium" rcompound="0,Medium">99.0000</Lap>
<BestLapTime>97.9000</BestLapTime>
<FinishTime>297.8000</FinishTime>
<Laps>3</Laps>
<Pitstops>0</Pitstops>
<FinishStatus>Finished Normally</FinishStatus>
<ControlAndAids startLap="1" endLap="3">PlayerControl,Clutch,AutoBlip</ControlAndAids>
</Driver>
<Driver>
<Name>Carl Slow</Name>
<TeamName>Team C</TeamName>
<VehName>Car C #3</VehName>
<CarType>Porsche 911 GT3 R</CarType>
<CarClass>GT3</CarClass>
<CarNumber>3</CarNumber>
<isPlayer>0</isPlayer>
<GridPos>3</GridPos>
<Position>3</Position>
<ClassGridPos>1</ClassGridPos>
<ClassPosition>1</ClassPosition>
<Lap num="1" p="3" et="100.0" topspeed="250.0" fcompound="0,Soft" rcompound="0,Soft">110.0000</Lap>
<Lap num="2" p="3" et="210.0" topspeed="251.0" fcompound="0,Soft" rcompound="0,Soft">--.----</Lap>
<BestLapTime>110.0000</BestLapTime>
<Laps>2</Laps>
<Pitstops>0</Pitstops>
<FinishStatus>DNF</FinishStatus>
<DNFReason>Suspension</DNFReason>
</Driver>
</Race>
</RaceResults>
</rFactorXML>
\x7f"""

PRACTICE_XML = """<?xml version="1.0" encoding="utf-8"?>
<rFactorXML version="1.0">
<RaceResults>
<Setting>Race Weekend</Setting>
<TrackVenue>Monza</TrackVenue>
<TrackCourse>Monza GP</TrackCourse>
<TrackEvent>Monza</TrackEvent>
<Practice1>
<DateTime>1790000100</DateTime>
<Laps>2147483647</Laps>
<Minutes>60</Minutes>
<MostLapsCompleted>{laps}</MostLapsCompleted>
<Driver>
<Name>AI Driver</Name>
<CarClass>GT3</CarClass>
<CarNumber>7</CarNumber>
<isPlayer>0</isPlayer>
<Position>1</Position>
<ClassPosition>1</ClassPosition>
<BestLapTime>107.0000</BestLapTime>
<Laps>{laps}</Laps>
<FinishStatus>None</FinishStatus>
</Driver>
<Driver>
<Name>Offline Player</Name>
<CarClass>GT3</CarClass>
<CarNumber>8</CarNumber>
<isPlayer>1</isPlayer>
<Position>2</Position>
<ClassPosition>2</ClassPosition>
<BestLapTime>107.5000</BestLapTime>
<Laps>{laps}</Laps>
<FinishStatus>None</FinishStatus>
</Driver>
</Practice1>
</RaceResults>
</rFactorXML>
"""

RACE_NAME = "2026_09_21_19_10_00-12R1.xml"
PRACTICE_NAME = "2026_09_21_18_00_00-10P1.xml"
EMPTY_NAME = "2026_09_21_17_00_00-11P1.xml"


def race() -> rf.SessionResult:
    return rf.parse_results(RACE_XML.encode("utf-8"), RACE_NAME, ["alice driver"])


# Results files
def test_parse_race_session():
    result = race()
    assert (result.kind, result.tag, result.setting, result.server) == ("Race", "Race", "Multiplayer", "Test Server")
    assert (result.track, result.venue, result.course) == ("24 Heures du Mans", "Circuit de la Sarthe", "Circuit de la Sarthe")
    assert result.time == 1790000600  # session start, not event start
    assert (result.minutes, result.lap_limit, result.most_laps) == (20, 0, 3)
    assert [entry.name for entry in result.entries] == ["Alice Driver", "Bob Racer", "Carl Slow"]  # by position
    assert result.classes == ["Hyper", "GT3"]
    alice = result.entries[0]
    assert alice.player and not result.entries[1].player  # by profile name, every human online is "player"
    assert result.player_entry is alice
    assert [swap.driver for swap in alice.swaps] == ["Zed Partner", "Alice Driver"]
    assert alice.aids == "PlayerControl,Clutch,AutoBlip"
    carl = result.entries[2]
    assert (carl.status, carl.dnf_reason, carl.finish_time, carl.grid) == ("DNF", "Suspension", 0.0, 3)


def test_parse_laps():
    bob = race().entries[1]
    first, invalid, pit = bob.laps
    assert (first.number, first.position, first.time, first.start) == (1, 1, 100.5, 100.0)
    assert first.sectors == (30.0, 40.0, 30.5)
    assert (first.compound, first.pit, first.fuel, first.wear) == ("Medium", False, -1.0, ())
    assert invalid.time == 0.0 and invalid.sectors == (29.0, 41.0, 0.0)
    assert pit.pit and pit.compound == "Hard"
    alice_lap = race().entries[0].laps[0]
    assert (alice_lap.fuel, alice_lap.fuel_used, alice_lap.energy_used) == (0.9, 0.03, 0.04)
    assert alice_lap.wear == (0.99, 0.98, 0.99, 0.99)


def test_parse_events():
    events = race().events
    kinds = [event.kind for event in events]
    assert kinds == ["chat", "contact", "contact", "contact", "penalty", "track_limits"]  # no further action left out,
    # repeated track limits line once, score lines ignored
    contact = events[1]
    assert (contact.driver, contact.other, contact.value) == ("Alice Driver", "Bob Racer", 150.5)
    wall = events[3]
    assert (wall.driver, wall.other) == ("Carl Slow", rf.IMMOVABLE)
    penalty = events[4]
    assert (penalty.driver, penalty.other, penalty.value) == ("Bob Racer", "Stop/Go", 10.0)
    assert events[5].value == 0.5
    assert events[0].driver == "A Driver"


def test_event_counts():
    events = race().events
    assert rf.contact_counts(events) == {"Alice Driver": (1, 0), "Bob Racer": (1, 0), "Carl Slow": (0, 1)}
    assert rf.penalty_counts(events) == {"Bob Racer": 1}
    assert rf.track_limit_points(events) == {"Bob Racer": 0.5}


def test_race_gaps():
    alice, bob, carl = race().entries
    assert rf.race_gap(alice, alice) == rf.Gap(0, 0.0)
    assert rf.race_gap(bob, alice).time == pytest.approx(4.7)  # finish times
    assert rf.race_gap(carl, alice) == rf.Gap(1, 0.0)
    unfinished_bob = bob._replace(finish_time=0.0)
    unfinished_alice = alice._replace(finish_time=0.0)
    # Race left before its end: end of last lap both completed (next lap start, else start + lap time)
    assert rf.lap_end_time(unfinished_alice, 2) == pytest.approx(298.8)
    assert rf.lap_end_time(unfinished_bob, 3) == pytest.approx(402.0)
    assert rf.race_gap(unfinished_bob, unfinished_alice).time == pytest.approx(402.0 - 397.8)
    assert rf.best_lap_gap(bob, alice) == pytest.approx(2.1)
    assert rf.best_lap_gap(bob._replace(best_lap=0.0), alice) == -1.0
    assert not rf.race_unfinished(race())
    unfinished = race()._replace(entries=tuple(entry._replace(status="None") for entry in race().entries))
    assert rf.race_unfinished(unfinished)


def test_best_sectors():
    assert rf.best_sectors(race().entries) == (28.5, 39.5, 29.9)


def test_player_found_offline_without_profile():
    result = rf.parse_results(PRACTICE_XML.format(laps=5).encode(), PRACTICE_NAME)
    assert result.kind == "Practice"
    assert result.player_entry is not None and result.player_entry.name == "Offline Player"  # only human car
    assert result.lap_limit == 0 and result.track == "Monza"


def test_no_player_when_several_humans_and_no_name():
    assert rf.parse_results(RACE_XML.encode("utf-8"), RACE_NAME).player_entry is None


@pytest.mark.parametrize("data", [
    b"",
    b"<html></html>",
    b"<?xml version='1.0'?><rFactorXML><RaceResults><Setting>x</Setting></RaceResults></rFactorXML>",
    RACE_XML.encode("utf-8")[:2000],  # game still writing
    b"<rFactorXML><RaceResults><Race><Driver><Name>x</Name></Race></rFactorXML>",  # broken
])
def test_invalid_files(data):
    with pytest.raises(ValueError):
        rf.parse_results(data)


@pytest.mark.parametrize("tag, kind", [
    ("Practice1", "Practice"), ("Practice", "Practice"), ("Qualify", "Qualifying"), ("Qualify2", "Qualifying"),
    ("Warmup", "Warmup"), ("Race", "Race"), ("Race2", "Race"), ("RaceTime", ""), ("Stream", ""),
])
def test_session_kind(tag, kind):
    assert rf.session_kind(tag) == kind


def write_results(folder, files: dict[str, str]):
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")


def test_results_files(tmp_path):
    write_results(tmp_path, {RACE_NAME: RACE_XML, PRACTICE_NAME: PRACTICE_XML, "BatchTemplateR1.ini": "",
                             "notes.xml": "<x/>"})
    assert [os.path.basename(path) for path in rf.results_files(str(tmp_path))] == [RACE_NAME, PRACTICE_NAME]
    assert rf.results_files(str(tmp_path / "missing")) == []
    with pytest.raises(OSError):
        rf.read_results(str(tmp_path / "missing.xml"))


def test_game_folders(tmp_path):
    library = tmp_path / "Library"
    results = library / "steamapps" / "common" / "Le Mans Ultimate" / "UserData" / "Log" / "Results"
    results.mkdir(parents=True)
    profile = library / "steamapps" / "common" / "Le Mans Ultimate" / "UserData" / "player"
    profile.mkdir(parents=True)
    (profile / "Settings.JSON").write_text('{"DRIVER": {"Player Name": "Alice Driver", "Player Nick": " "}}',
                                           encoding="utf-8")
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    escaped = str(library).replace("\\", "\\\\")
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{escaped}"\n\t}}\n}}\n', encoding="utf-8")
    libraries = rf.steam_libraries(str(steam))
    assert libraries == [str(steam), os.path.normpath(str(library))]
    found = rf.find_results_folders(libraries)
    assert found == {"LMU": str(results)}
    assert rf.profile_player_names(found["LMU"]) == ["Alice Driver"]
    assert rf.game_of_path(str(results / RACE_NAME)) == "LMU"
    assert rf.game_of_path("") == ""
    assert rf.steam_libraries(str(tmp_path / "nowhere")) == [str(tmp_path / "nowhere")]
    assert rf.profile_player_names(str(tmp_path)) == []


# Page texts & rows
@pytest.fixture
def english():
    from tinypedal import i18n

    i18n.set_language("English")
    yield


def test_race_classification_rows(english, ui_env):
    from tinypedal.ui.quick import results_backend as rb

    rows = rb.classification_rows(race(), "", "1")
    assert [row["driver"] for row in rows] == ["Alice Driver", "Bob Racer", "Carl Slow"]
    alice, bob, carl = rows
    assert alice["gapText"] == "4:57.800"  # race time of winner
    assert bob["gapText"] == "+4.700"
    assert (carl["gapText"], carl["gapTone"], carl["reasonText"]) == ("DNF", "loss", "Suspension failure")
    assert (alice["gridDelta"], bob["gridDelta"], carl["gridDelta"]) == (1, -1, 0)  # retired: no change shown
    assert alice["bestTone"] == "purple" and bob["bestTone"] == ""
    assert alice["classText"] == "Hyper" and alice["classPosText"] == "1"  # several classes
    assert alice["drivers"] == "Zed Partner, Alice Driver"
    assert (alice["contacts"], bob["penalties"], carl["contacts"]) == (1, 1, 1)
    assert alice["player"] and bob["selected"] and not alice["selected"]
    gt3 = rb.classification_rows(race(), "GT3", "")
    assert [row["driver"] for row in gt3] == ["Carl Slow"] and gt3[0]["posText"] == "1"


def test_practice_rows(english, ui_env):
    from tinypedal.ui.quick import results_backend as rb

    practice = rf.parse_results(PRACTICE_XML.format(laps=5).encode(), PRACTICE_NAME)
    rows = rb.classification_rows(practice, "", "")
    assert [row["gapText"] for row in rows] == ["", "+0.500"]  # leader time in best lap column
    assert rows[0]["classText"] == ""  # one class: no class column
    row = rb.session_row(practice, QDate.currentDate())
    assert (row["code"], row["resultText"], row["detailText"], row["online"]) == ("P", "P2", "", False)
    assert rb.session_row(race(), QDate.currentDate())["resultText"] == "P1"


def test_summary_tiles(english, ui_env):
    from tinypedal.ui.quick import results_backend as rb

    tiles = {tile["label"]: tile for tile in rb.summary_tiles(race())}
    assert tiles["Position"]["value"] == "P1" and tiles["Position"]["tone"] == "gold"
    assert tiles["Grid"]["detail"] == "+1"
    assert tiles["Best Lap"]["value"] == "1:37.900" and tiles["Best Lap"]["tone"] == "purple"
    assert tiles["Contacts"]["detail"] == "1 car · 0 walls"
    assert "Fastest Lap" not in tiles  # player has it
    carl = race()._replace(entries=tuple(entry._replace(player=entry.name == "Carl Slow") for entry in race().entries))
    tiles = {tile["label"]: tile for tile in rb.summary_tiles(carl)}
    assert (tiles["Position"]["value"], tiles["Position"]["detail"]) == ("DNF", "Suspension failure")
    assert tiles["Fastest Lap"]["detail"] == "Alice Driver"
    nobody = race()._replace(entries=tuple(entry._replace(player=False) for entry in race().entries))
    assert rb.summary_tiles(nobody)[0]["label"] == "Winner"


def test_lap_rows(english, ui_env):
    from tinypedal.ui.quick import results_backend as rb

    result = race()
    alice = rb.lap_rows(result, result.entries[0])
    assert [row["timeTone"] for row in alice] == ["", "purple", ""]
    assert alice[0]["deltaText"] == "+3.000" and alice[1]["deltaText"] == ""
    assert alice[1]["s1Tone"] == "purple" and alice[0]["s1Tone"] == ""
    assert alice[0]["usageText"] == "4.0 %" and alice[0]["wearText"] == "98 %"
    bob = rb.lap_rows(result, result.entries[1])
    assert bob[1]["timeTone"] == "dim" and bob[1]["timeText"] == "-"
    assert bob[2]["pit"] and bob[2]["compound"] == "Hard" and bob[2]["timeTone"] == "gain"  # own best
    stats = {tile["label"]: tile["value"] for tile in rb.lap_stats(result, result.entries[0])}
    assert stats["Best Lap"] == "1:37.900" and stats["Theoretical Best"] == "1:37.900"
    assert "Average" in stats and stats["Top Speed"].endswith("km/h")


def test_positions_chart(ui_env):
    from tinypedal.ui.quick import results_backend as rb

    chart = rb.positions_chart(race(), "")
    assert (chart["laps"], chart["places"]) == (3, 3)
    alice = chart["series"][0]
    assert alice["points"] == [[0, 2], [1, 2], [2, 1], [3, 1]] and alice["player"]
    hyper = rb.positions_chart(race(), "Hyper")
    assert [series["points"][-1] for series in hyper["series"]] == [[3, 1], [3, 2]]  # class places
    empty = rf.parse_results(PRACTICE_XML.format(laps=0).encode(), EMPTY_NAME)
    assert rb.positions_chart(empty, "")["series"] == []


def test_event_rows(english, ui_env):
    from tinypedal.ui.quick import results_backend as rb

    result = race()
    rows = rb.event_rows(result, "", set(), {"Alice Driver"})
    assert [row["kind"] for row in rows] == ["chat", "contact", "contact", "penalty", "track_limits"]  # pair once
    assert rows[1]["title"] == "Alice Driver  ↔  Bob Racer" and rows[1]["detail"] == "Impact 180" and rows[1]["mine"]
    assert rows[2]["title"] == "Carl Slow  ↔  Wall"
    assert rows[3]["detail"] == "Stop & go 10 s · Pit lane speeding"
    assert rows[4]["detail"] == "Lap invalidated (corner cut) · 0.5 pts"
    assert [row["kind"] for row in rb.event_rows(result, "contact", {"Carl Slow"}, set())] == ["contact"]
    assert rb.event_counts(result) == [5, 2, 1, 1, 1]


def test_game_texts_french(ui_env):
    from tinypedal import i18n
    from tinypedal.process import results_text

    i18n.set_language("Français")
    try:
        for label in results_text.GAME_LABELS.values():
            assert i18n.tr(label) != label or label in ("Accident", "Stop & go", "Drive-through")
        assert results_text.game_text("Unknown reason") == "Unknown reason"
        assert results_text.game_text("Suspension") == "Casse suspension"
    finally:
        i18n.set_language("English")


# Page
def wait_until(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def results_folder(tmp_path, ui_env, monkeypatch):
    """Results folder chosen by user, no game installed"""
    from tinypedal.setting import cfg

    folder = tmp_path / "Results"
    write_results(folder, {RACE_NAME: RACE_XML, PRACTICE_NAME: PRACTICE_XML.format(laps=5),
                           EMPTY_NAME: PRACTICE_XML.format(laps=0)})
    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {})
    with open(os.path.join(cfg.path.config, "race_results.json"), "w", encoding="utf-8") as file:
        json.dump({"folder": str(folder)}, file)
    slot_errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: slot_errors.append(exc_info[1]))
    yield folder
    assert not slot_errors


@pytest.fixture
def backend(results_folder):
    from tinypedal.ui.quick.results_backend import RaceResultsBackend

    backend = RaceResultsBackend()
    backend.page_shown()
    assert wait_until(lambda: backend.loaded_once)
    yield backend
    backend.release()
    backend.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_backend_sessions(backend, english):
    assert backend.sessionCount == 3
    assert backend.shownCount == 2  # session without lap hidden
    assert backend.selectedKey.endswith(RACE_NAME)  # newest first
    assert backend.isRace and backend.hasSession
    assert backend.sessionHeader["title"] == "24 Heures du Mans"
    assert backend.classificationModel.rowCount() == 3
    assert backend.selectedEntry == "0"  # player
    assert backend.lapModel.rowCount() == 3 and backend.lapColumns == {"usage": True, "wear": True}
    assert len(backend.positions["series"]) == 3
    assert backend.eventModel.rowCount() == 5
    backend.setHideEmpty(False)
    assert backend.shownCount == 3
    backend.setKindFilter(3)  # practice
    assert backend.shownCount == 2 and backend.selectedKey.endswith(PRACTICE_NAME)
    assert not backend.isRace and backend.positions["series"] == []
    backend.setKindFilter(0)
    backend.setSearch("monza")
    assert backend.shownCount == 2
    backend.setSearch("sarthe server")
    assert backend.shownCount == 1
    backend.setSearch("")
    assert backend.moveSelection(1) == 1
    assert backend.moveSelection(-5) == 0 and backend.selectedKey.endswith(RACE_NAME)


def test_backend_car_and_filters(backend, english):
    backend.selectEntry("1")
    assert backend.selectedEntry == "1" and backend.driverInfo["name"] == "Bob Racer"
    assert backend.lapColumns == {"usage": False, "wear": False}
    rows = backend.classificationModel.rows
    assert [row["selected"] for row in rows] == [False, True, False]
    backend.selectEntry("99")  # unknown car ignored
    assert backend.selectedEntry == "1"
    backend.setEventMine(True)
    assert backend.eventModel.rowCount() == 3  # contact, penalty, track limits of Bob
    backend.setEventKind(2)
    assert backend.eventModel.rowCount() == 1
    backend.setClassFilter("GT3")
    assert backend.classFilter == "GT3" and backend.selectedEntry == "2"  # car of class picked
    assert backend.classificationModel.rowCount() == 1
    backend.setClassFilter("Unknown")
    assert backend.classFilter == "GT3"
    backend.setTab(1)
    assert backend.tabIndex == 1
    from tinypedal.ui.quick.results_backend import load_page_settings

    assert load_page_settings()["event_filter"] == 2 and load_page_settings()["tab"] == 1


def test_backend_reads_new_file(backend, results_folder):
    newer = "2026_09_21_20_00_00-13R1.xml"
    write_results(results_folder, {newer: RACE_XML.replace("1790000600", "1790009999")})
    backend.reload()
    assert wait_until(lambda: backend.sessionCount == 4)
    assert backend.selectedKey.endswith(newer)  # newest was shown: new one shown


def test_backend_without_folder(ui_env, monkeypatch, tmp_path):
    from tinypedal.ui.quick.results_backend import RaceResultsBackend

    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {})
    backend = RaceResultsBackend()
    backend.page_shown()
    assert wait_until(lambda: backend.loaded_once)
    assert (backend.sessionCount, backend.folderText, backend.hasSession) == (0, "", False)
    backend.release()
    backend.deleteLater()  # deleted now, in UI thread (file watcher with it)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_page_loads(results_folder, english):
    from PySide6.QtCore import qInstallMessageHandler
    from PySide6.QtQuickWidgets import QQuickWidget

    from tinypedal.ui.race_results_viewer import RaceResultsViewer

    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        viewer = RaceResultsViewer(None)
        viewer.resize(1400, 800)
        viewer.show()
        assert wait_until(lambda: viewer.backend.loaded_once)
        assert viewer.view.status() == QQuickWidget.Status.Ready, viewer.view.errors()
        for tab in range(4):  # every tab shown, car picked, class filter, narrow page
            viewer.backend.setTab(tab)
            wait_until(lambda: False, 0.05)
        viewer.backend.selectEntry("2")
        viewer.backend.setClassFilter("Hyper")
        viewer.resize(700, 600)
        wait_until(lambda: False, 0.05)
        viewer.backend.setKindFilter(3)
        wait_until(lambda: False, 0.05)
        assert viewer.view.status() == QQuickWidget.Status.Ready
        viewer.close()
        viewer.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages
