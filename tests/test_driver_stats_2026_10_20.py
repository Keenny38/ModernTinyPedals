"""Driver Stats Viewer 2026-10-20: road conditions, start position & online state recorded per stint, session filters
(road, server, game version), history columns (wet PB, PB of latest version, places gained, clean races), rusty
combos, table search, class filter & grouping, lap time goals, chart & sessions linked, activity of a year & driving
time distribution, rivals, official races to come, rank history, personal best card & share code, parts of the page"""

import csv
import json
import time
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

from neopedal.api_control import api
from neopedal.module import module_stats
from neopedal.module_info import StatsInfo
from neopedal.process import driver_ranks as dr
from neopedal.process import results_file as rf
from neopedal.process import results_index as ri
from neopedal.setting import cfg
from neopedal.ui.quick import formatting, stats_analysis, stats_card, stats_common, stats_overview
from neopedal.userfile import driver_history, pb_code
from neopedal.userfile.driver_history import SessionRecord, parse_record, record_line, session_record
from tests.test_driver_stats_viewer import (  # noqa: F401  (fixtures)
    OREGA,
    SPA,
    STATS,
    backend,
    dialogs,
    item_texts,
    page,
    settle,
    window,
    write_stats,
)
from tests.test_module_mapping_stats_notes import drive_stats_lap, stats_env, tele  # noqa: F401

FERRARI = "Hyper - Ferrari"
OLD = 1_700_000_000.0  # 2023-11-14
HISTORY = [
    SessionRecord(OLD, SPA, OREGA, 1, 123.0, valid=5, seconds=900.0, wetness=0.0, track_temp=30.0, online=0, game_version="1.41"),
    SessionRecord(OLD + 1000, SPA, OREGA, 2, 121.5, valid=4, seconds=600.0, wetness=0.0, track_temp=31.0, online=1,
                  game_version="1.42", compound="Soft"),
    SessionRecord(OLD + 2000, SPA, OREGA, 4, 125.0, valid=20, wetness=0.4, track_temp=18.0, online=1,
                  game_version="1.42", start_position=8, position=5, finish=1, compound="Wet"),
    SessionRecord(OLD + 3000, SPA, OREGA, 4, 124.0, valid=3, wetness=0.5, track_temp=17.0, online=0,
                  game_version="1.42", finish=2),
    SessionRecord(OLD + 4000, "Monza", "GT3 - BMW", 1, 107.2, seconds=300.0),
]


def summary(**values) -> ri.ResultSummary:
    base = {"path": "", "game": "LMU", "start": OLD, "end": OLD, "kind": "Race", "code": "R", "track": SPA,
            "venue": "", "game_version": "1.42", "setting": "Multiplayer", "server": "", "cars": 20, "class_cars": 10,
            "driver": "Me", "vehicle": "", "car": "", "car_class": "LMP2", "position": 5, "class_position": 3,
            "status": rf.FINISHED, "best_lap": 120.0, "laps": 20, "gap_laps": 0, "gap_time": 1.0, "contacts": 0,
            "impacts": 0, "penalties": 0, "track_limits": 0.0}
    base.update(values)
    return ri.ResultSummary(**base)


# --- Session history: new fields
def test_record_line_writes_known_fields_only():
    plain = SessionRecord(OLD, SPA, OREGA, 1, 120.0)
    data = json.loads(record_line(plain))
    assert not {"wetness", "track_temp", "compound", "start_position", "online"} & set(data)
    assert parse_record(data) == plain and not plain.conditions_known and not plain.wet
    full = HISTORY[2]
    data = json.loads(record_line(full))
    assert data["wetness"] == 0.4 and data["track_temp"] == 18.0 and data["compound"] == "Wet"
    assert data["start_position"] == 8 and data["online"] == 1
    assert parse_record(data) == full and full.wet
    dry = SessionRecord(OLD, SPA, OREGA, wetness=0.0, track_temp=0.0)
    assert json.loads(record_line(dry))["wetness"] == 0.0 and dry.conditions_known and not dry.wet


def test_session_record_rounds_and_checks_values():
    record = session_record(SPA, OREGA, 4, 120.0, 1, 0, 1.0, 60.0, 2, 1, OLD, wetness=0.123456, track_temp=21.27,
                            start_position=-3, online=7)
    assert record.wetness == 0.123 and record.track_temp == 21.3 and record.start_position == 0 and record.online == -1
    assert session_record(SPA, OREGA, 4, 120.0, 1, 0, 1.0, 60.0, 2, 1, OLD, wetness=5.0).wetness == -1.0
    assert session_record(SPA, OREGA, 4, 120.0, 1, 0, 1.0, 60.0, 2, 1, OLD, wetness=0.2,
                          track_temp=float("nan")).wetness == -1.0


# --- Stats module: conditions of best lap, start position, online server
class InstantThread:
    """Thread running its target at start (answer known before the stint is saved)"""

    def __init__(self, target, daemon=True, name=""):
        self.target = target

    def start(self):
        self.target()


def test_stint_records_conditions_start_and_online(stats_env, monkeypatch):  # noqa: F811
    values, filepath = stats_env
    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(module_stats, "lmu_address", lambda: ("localhost", 1))
    asked = []
    monkeypatch.setattr(module_stats, "fetch_game", lambda address, route, timeout: (
        asked.append(route), (200, b'"JOIN_JOINED_SERVER"'))[1])
    monkeypatch.setattr(module_stats.threading, "Thread", InstantThread)
    values.update({"session.pre_race": True, "vehicle.place": 8, "session.wetness_average": 0.35,
                 "session.track_temperature": 21.26, "tyre.compound_name": ("Wet", "Wet", "Wet", "Wet")})
    gen = module_stats.record_driver_stats(StatsInfo(), filepath, "Class", max_moved_distance=1500,
                                           podium_by_class=False)
    gen.send(1)
    gen.send(1)
    values["session.pre_race"] = False  # green flag: start position
    gen.send(1)
    values["vehicle.place"] = 5
    drive_stats_lap(values, gen, 0.0, 90.0)
    gen.send(1)  # best lap validated (game last lap time matches): its conditions
    values["session.wetness_average"] = 0.6  # wetter after the best lap: best lap conditions kept
    values["vehicle.finish_state"] = 1
    gen.send(1)
    gen.send(2)  # back to garage: saved
    record = driver_history.load_history(filepath)[-1]
    assert asked[0] == module_stats.JOIN_ROUTE  # asked once per stint (next stint asked too)
    assert (record.wetness, record.track_temp, record.compound) == (0.35, 21.3, "Wet")
    assert (record.start_position, record.position, record.online) == (8, 5, 1)


def test_online_check_drops_late_answer_and_unknown_settings(monkeypatch):
    targets = []

    class HeldThread(InstantThread):
        def start(self):
            targets.append(self.target)

    monkeypatch.setattr(api, "_api", SimpleNamespace(NAME="Le Mans Ultimate"))
    monkeypatch.setattr(module_stats, "lmu_address", lambda: ("localhost", 1))
    monkeypatch.setattr(module_stats.threading, "Thread", HeldThread)
    answers = iter([(200, b"JOIN_JOINED_SERVER"), (200, b"JOIN_NOT_JOINED")])
    monkeypatch.setattr(module_stats, "fetch_game", lambda *args: next(answers))
    check = module_stats.OnlineCheck()
    check.start()
    check.start()  # next stint before the first answer
    targets[0]()  # late answer of the first stint: dropped
    assert check.result == -1
    targets[1]()
    assert check.result == 0
    monkeypatch.setattr(module_stats, "lmu_address", lambda: (_ for _ in ()).throw(AttributeError("no setting")))
    check.start()
    assert check.result == -1 and len(targets) == 2  # nothing asked


def test_compound_text_front_rear(monkeypatch):
    monkeypatch.setattr(api, "read", SimpleNamespace(tyre=SimpleNamespace(compound_name=lambda: (
        "Soft", "Soft", "Medium", "Medium"))))
    assert module_stats.compound_text() == "Soft/Medium"
    monkeypatch.setattr(api, "read", SimpleNamespace(tyre=SimpleNamespace(compound_name=lambda: 0)))
    assert module_stats.compound_text() == ""


# --- Results files: start position & people of player class
def entry(name: str, car_class: str, position: int, human: bool, player: bool = False,
          status: str = rf.FINISHED) -> rf.Entry:
    return rf.Entry(name, "", "", "", car_class, "", 0, position, 0, position, 10, 100.0 + position, 0.0, 0, status,
                    "", human, player, "", (), ())


def test_rivals_of_race_people_of_class_only():
    me = entry("Me", "GT3", 2, True, True)
    result = SimpleNamespace(kind="Race", entries=[entry("Ann", "GT3", 1, True), me, entry("AI", "GT3", 3, False),
                                                   entry("Bob", "LMP2", 4, True)])
    assert [rival.name for rival in ri.rivals_of(result, me)] == ["Ann"]
    assert ri.rivals_of(SimpleNamespace(kind="Practice", entries=result.entries), me) == ()


# --- Pure helpers
def test_helpers_versions_laptimes_places(monkeypatch):
    assert stats_common.version_key("1.415") < stats_common.version_key("1.42") < stats_common.version_key("2.0")
    assert stats_common.version_key("beta")[0] == -1
    assert stats_common.parse_laptime("1:52.300") == pytest.approx(112.3)
    assert stats_common.parse_laptime("112,3") == pytest.approx(112.3)
    assert stats_common.parse_laptime("1:75.0") == 0 and stats_common.parse_laptime("fast") == 0
    race = SessionRecord(OLD, SPA, OREGA, 4, position=4, finish=1)
    assert stats_common.places_gained(race._replace(start_position=7), None) == 3
    assert stats_common.places_gained(race, summary(class_grid=2, class_position=4)) == -2  # from results file
    assert stats_common.places_gained(race._replace(finish=2), summary(class_grid=2)) is None
    assert stats_common.online_value(race, summary(setting="Race Weekend")) == 0
    assert stats_common.online_value(race._replace(online=1), None) == 1
    monkeypatch.setattr(formatting, "fahrenheit", lambda: False)
    assert stats_common.conditions_text(HISTORY[2]).startswith("Wet road 40 %")
    assert stats_common.conditions_text(HISTORY[2]).endswith("Track Temp 18 °C")
    assert stats_common.conditions_text(HISTORY[4]) == ""
    monkeypatch.setattr(formatting, "fahrenheit", lambda: True)  # user temperature unit (audit F5)
    assert stats_common.conditions_text(HISTORY[2]).endswith("Track Temp 64 °F")


def test_race_record_streak_and_places():
    races = [summary(contacts=1), summary(class_grid=6, class_position=3), summary(class_grid=2, class_position=4),
             summary(kind="Qualifying", contacts=5)]
    assert stats_analysis.clean_streak(races) == 2  # qualifying left out
    assert stats_analysis.average_gained(races) == (pytest.approx(0.5), 2)


def test_rivals_record():
    ann = ri.Rival("Ann", 2, rf.FINISHED, 119.0)
    bob = ri.Rival("Bob", 0, "DNF", 0.0)
    summaries = [summary(end=OLD + 1, class_position=3, rivals=(ann, bob)),
                 summary(end=OLD + 2, class_position=1, best_lap=118.5, rivals=(ann._replace(class_position=4),)),
                 summary(end=OLD + 3, setting="Race Weekend", rivals=(bob,))]  # offline: left out
    rivals = stats_analysis.rivals(summaries)
    assert [rival.name for rival in rivals] == ["Ann"]  # Bob met once online
    assert (rivals[0].races, rivals[0].ahead, rivals[0].behind, rivals[0].last) == (2, 1, 1, OLD + 2)
    assert rivals[0].gap == pytest.approx((1.0 - 0.5) / 2)


def test_rank_chart_points():
    history = [dr.HistoryEntry(OLD, dr.Rank("Silver", 1, 50), None), dr.HistoryEntry(OLD + 10, dr.Rank("Gold", 2, 0),
                                                                                      dr.Rank("Silver", 3, 0))]
    points = stats_analysis.rank_chart(history, "driver")
    assert [point["x"] for point in points] == [0, 1] and points[0]["y"] < points[1]["y"] <= 1
    assert stats_analysis.rank_chart(history, "safety") == []  # seen once


def test_distribution_and_years():
    records = [SessionRecord(datetime(2025, 3, 1, 12).timestamp(), SPA, OREGA, seconds=600.0),
               SessionRecord(datetime(2025, 3, 2, 12).timestamp(), "Monza", "GT3 - BMW", seconds=1200.0,
                             vehicle_class="GT3"),
               SessionRecord(datetime(2024, 3, 2, 12).timestamp(), "Imola", "GT3 - BMW", seconds=99.0)]
    first, last = stats_analysis.period_bounds(2025, date(2026, 10, 20))
    tracks, classes = stats_analysis.distribution(records, first, last, lambda vehicle: vehicle.split(" - ")[0])
    assert tracks == [("Monza", 1200.0), (SPA, 600.0)] and classes == [("GT3", 1200.0), ("LMP2_ELMS", 600.0)]
    assert stats_analysis.history_years(records) == [2025, 2024]
    assert stats_analysis.period_bounds(0, date(2026, 10, 20))[0] == date(2025, 10, 21)


def test_official_races_parsed_and_matched():
    event = {"configuration": {"title": "Sprint", "starts": "2026-10-21T18:00:00Z",
                               "content": {"track": {"name": "PORTIMAO", "friendly": "",
                                                     "subItems": [{"name": "Portimao_WEC", "scn": "PORTIMAOWEC"}]}}},
             "registered": {"total": 3, "class": {"Hypercar": 2, "LMGT3": 1}}}
    races = stats_analysis.parse_events("advanced", [event, {"configuration": {}}, "junk"])
    assert len(races) == 1 and races[0].scene == "PORTIMAOWEC" and races[0].track == "Portimao WEC"
    assert races[0].classes == ("Hypercar", "LMGT3")
    assert races[0].start == datetime(2026, 10, 21, 18, tzinfo=stats_analysis.UTC).timestamp()
    names = stats_analysis.track_names([{"sceneDesc": "PORTIMAOWEC", "name": "6 Hours of Portimao",
                                         "shortName": "Algarve International Circuit 1.27",
                                         "displayProperties": {"shortName": "Algarve International Circuit"}}])
    assert stats_analysis.stats_track(races[0], ["Monza", "Algarve International Circuit"], names) == \
        "Algarve International Circuit"
    assert stats_analysis.stats_track(races[0], ["Monza"], names) == ""
    asked = []
    read = stats_analysis.read_upcoming(lambda path: asked.append(path) or ([event] if "advanced" in path else None))
    assert len(read) == 1 and len(asked) == 3 and asked[0].startswith("api/v1/daily/list/beginner")


def test_pb_code_round_trip():
    best = pb_code.SharedBest(SPA, OREGA, "LMP2", 121.5, OLD, "1.42", "Jo <b>")
    code = pb_code.encode(best, "0.27.0")
    assert code.startswith("NP1:pb:")
    found = pb_code.decode(f"look at this: {code} !")
    assert found == best._replace(driver="Jo b")  # markup characters stripped
    assert pb_code.decode("NP1:pb:AAAA") is None and pb_code.decode("hello") is None
    bad = pb_code.encode(best._replace(laptime=-1.0))
    assert pb_code.decode(bad) is None


def test_card_drawn():
    image = stats_card.draw_card(stats_card.CardData(SPA, OREGA, "2:01.500", "Jo", "14/11/2023", "Pro", "#33AA55",
                                                     "100.50 % of reference"))
    assert (image.width(), image.height()) == (stats_card.WIDTH, stats_card.HEIGHT) and not image.isNull()


# --- Page: filters, columns, goals, table, overview, sharing
@pytest.fixture
def stats(backend):  # noqa: F811
    driver_history.save_history(cfg.path.config, HISTORY)
    backend.reload_stats()
    settle(backend)
    backend.selectTrack(SPA)
    backend.selectRow(OREGA)
    return backend


def test_session_filters(stats):
    assert stats.versionChoices[1:] == [{"text": "Since v1.42", "value": "1.42"},
                                        {"text": "Since v1.41", "value": "1.41"}]
    assert len(stats.sessions) == 4 and not stats.filtered
    stats.setConditionFilter(2)  # wet
    assert len(stats.sessions) == 2 and stats.filtered and stats.conditionFilter == 2
    assert "Best with filters 2:04.000 (Wet Road)" in stats.progression["info"]
    stats.setOnlineFilter(1)
    assert len(stats.sessions) == 1 and "Best with filters 2:05.000 (Wet Road · Online Only)" in stats.progression["info"]
    stats.clearFilters()
    stats.setVersionFilter(1)  # since 1.42
    assert len(stats.sessions) == 3 and stats.versionIndex == 1
    stats.setConditionFilter(1)  # dry
    assert [entry["best"] for entry in stats.sessions] == ["2:01.500"]
    stats.clearFilters()
    assert stats.viewer_config()["since_version"] == "" and len(stats.sessions) == 4


def test_sessions_rows_linked_to_chart(stats):
    sessions, points = stats.sessions, stats.progression["points"]
    assert [entry["point"] for entry in sessions] == [3, 2, 1, 0]  # newest first
    assert [point["session"] for point in points] == [3, 2, 1, 0]
    assert sessions[1]["wet"] and sessions[1]["online"] == 1 and sessions[1]["gained"] == "+3"
    assert sessions[1]["gainedColor"] == "gain" and "Start P8 · finish P5 (+3)" in sessions[1]["tip"]
    assert "Wet road 40 % · Track Temp 18 °C · Wet" in sessions[1]["tip"]
    assert points[2]["wet"] and "Wet road" in points[2]["tip"]


def test_history_columns_and_rust(stats):
    cells = {key: stats.cell(OREGA, key) for key in stats_common.HISTORY_KEYS}
    assert cells["wet_pb"].text == "2:04.000" and cells["version_pb"].value == pytest.approx(121.5)
    assert cells["gained"].value == pytest.approx(3.0) and cells["clean_rate"].value is None
    assert stats._labels["version_pb"] == "PB v1.42"
    last = stats.cell(OREGA, "last")
    assert last.color and "Not driven for" in last.tip  # 2023: rusty
    assert stats.cell(FERRARI, "last").value is None


def test_table_search_class_filter_and_groups(stats):
    assert stats.tableClasses == ["Hyper", "LMP2_ELMS"]
    stats.setSearch("ferr")
    assert stats.row_keys() == [FERRARI]
    stats.setSearch("nothing")
    assert not stats.hasRows and stats.emptyText == "No row matches the search or class filter."
    stats.setSearch("")
    stats.setClassFilter("LMP2_ELMS")
    assert stats.row_keys() == [OREGA] and stats.classFilter == "LMP2_ELMS"
    stats.setClassFilter("")
    stats.setGroupByClass(True)
    assert [row["group"] for row in stats.rows.rows] == ["", "LMP2_ELMS"] and stats.groupByClass
    assert stats.cell(FERRARI, "pb").tip == ""  # alone in its class
    stats.setGroupByClass(False)
    stats.selectTrack("")
    stats.setClassFilter("GT3")
    assert stats.row_keys() == ["Monza"]
    assert "class:Hyper" not in [column["key"] for column in stats.columns]
    stats.setClassFilter("")


def test_goal_set_reached_once(stats, monkeypatch):
    from neopedal.ui import toast

    toasts = []
    monkeypatch.setattr(toast, "show_toast", lambda host, text, **kwargs: toasts.append(text))
    assert stats.goal["visible"] and not stats.goal["set"] and stats.goal["suggestion"].startswith("Suggested:")
    stats.set_goal(f"{SPA}|{OREGA}", 121.0)
    goal = stats.goal
    assert goal["set"] and goal["time"] == "2:01.000" and goal["gap"] == "+0.500 s to find"
    assert goal["gapColor"] == "loss" and goal["ratio"] == pytest.approx((123.0 - 121.5) / (123.0 - 121.0))
    assert stats.progression["goal"] == "2:01.000" and stats.progression["goalY"] >= 0
    write_stats({**STATS, SPA: {**STATS[SPA], OREGA: {**STATS[SPA][OREGA], "pb": 120.9}}})
    stats.reload_stats()
    settle(stats)
    assert len(toasts) == 1 and "Goal reached" in toasts[0] and stats.goal["reached"]
    stats.reload_stats()
    settle(stats)
    assert len(toasts) == 1  # told once
    stats.set_goal(f"{SPA}|{OREGA}", 125.0)  # slower than personal best: reached already, nothing told
    stats.reload_stats()
    settle(stats)
    assert len(toasts) == 1
    stats.clearGoal()
    assert not stats.goal["set"] and f"{SPA}|{OREGA}" not in stats.goals()


def test_activity_year_and_distribution(stats):
    stats.selectTrack("")
    activity = stats.activity
    assert activity["years"][0]["value"] == 0 and {"text": "2023", "value": 2023} in activity["years"]
    assert activity["summary"] == "No driving in this period."  # history of 2023 only
    stats.setActivityYear([entry["value"] for entry in activity["years"]].index(2023))
    activity = stats.activity
    assert activity["yearIndex"] > 0 and activity["weeks"] >= 53
    assert activity["tracks"][0]["name"] == SPA and activity["classes"][0]["ratio"] == 1.0
    assert sum(day["level"] >= 0 for day in activity["days"]) == 365  # days of 2023 only
    stats.setActivityYear(0)


def test_driver_card_figures_and_rivals(stats):
    ann = ri.Rival("Ann", 2, rf.FINISHED, 119.0)
    stats.results = [summary(class_grid=5, class_position=3, rivals=(ann,)), summary(end=OLD + 9, rivals=(ann,))]
    stats.profile = None
    stats._results_serial += 1
    stats.selectTrack("")
    figures = {figure["label"]: figure["value"] for figure in stats.driver["figures"]}
    assert figures["Clean Streak"] == "2" and figures["Places Gained"] == "+2.0"
    assert stats.rivals[0]["name"] == "Ann" and stats.rivals[0]["record"] == "0-2"
    assert stats.rivals[0]["tone"] == "loss" and stats.rivals[0]["gap"] == "+1.000"


def test_official_races_option(stats, monkeypatch):
    monkeypatch.setattr(stats_overview, "online_enabled", lambda: True)
    reads = []
    event = stats_analysis.Upcoming("advanced", "Sprint", time.time() + 3600, "Spa", "SPASCENE", ("LMP2",))
    monkeypatch.setattr(stats_overview, "read_official_races", lambda: reads.append(1) or (
        [event], {"spascene": (SPA,)}))
    stats.selectTrack("")
    assert not stats.upcomingEnabled and not reads
    stats.setUpcomingEnabled(True)
    settle(stats)
    races = stats.upcoming["races"]
    assert reads == [1] and races[0]["track"] == SPA and races[0]["tier"] == "Advanced"
    bests = {best["vehicleClass"]: best["best"] for best in races[0]["bests"]}
    assert bests == {"Hyper": "1:59.000", "LMP2_ELMS": "2:01.500"} and races[0]["known"]
    stats.load_upcoming()  # read again only after a while
    settle(stats)
    assert reads == [1]
    monkeypatch.setattr(stats_overview, "online_enabled", lambda: False)
    stats.refreshUpcoming()
    assert "Turn on online ranks" in stats.upcoming["note"]
    stats.setUpcomingEnabled(False)
    assert not stats.upcoming["enabled"]


def test_share_code_card_and_compare(stats, dialogs, monkeypatch):  # noqa: F811
    from neopedal.ui import toast

    monkeypatch.setattr(toast, "show_toast", lambda *args, **kwargs: None)
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: infos.append(args[2]))
    stats.copyPbCode()
    shared = pb_code.decode(QGuiApplication.clipboard().text())
    assert shared is not None and shared.track == SPA and shared.laptime == pytest.approx(121.5)
    assert shared.time == OLD + 1000 and shared.game_version == "1.42"
    card = stats.card_data()
    assert card is not None and card.laptime == "2:01.500" and card.level
    stats.compare_shared(shared._replace(vehicle="LMP2_ELMS - Other", laptime=120.0, driver="Ann"))
    assert stats.goal_of(SPA, OREGA) == pytest.approx(120.0)  # faster: offered as goal, confirmed
    stats.compare_shared(shared._replace(laptime=125.0))
    assert "You are faster." in infos[-1]
    stats.compare_shared(shared._replace(track="Imola"))
    assert "no lap time on this track" in infos[-1]


def test_history_csv_rows_match_header(stats, tmp_path):
    filename = str(tmp_path / "history.csv")
    assert stats.write_history(filename, "csv", ".")
    with open(filename, encoding="utf-8-sig") as file:
        rows = list(csv.reader(file))
    assert len(rows[0]) == len(stats_common.HISTORY_COLUMNS) and all(len(row) == len(rows[0]) for row in rows)
    assert rows[3][rows[0].index("Start Position")] == "8" and rows[3][rows[0].index("Compound")] == "Wet"


def test_page_new_parts_without_qml_warnings(page, monkeypatch):  # noqa: F811
    monkeypatch.setattr(stats_overview, "online_enabled", lambda: True)
    event = stats_analysis.Upcoming("beginner", "Daily", time.time() + 3600, SPA, "", ())
    monkeypatch.setattr(stats_overview, "read_official_races", lambda: ([event], {}))
    driver_history.save_history(cfg.path.config, HISTORY)
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        page.resize(1400, 860)
        page.show()
        backend = page.backend
        backend.reload_stats()
        settle(backend)
        for step in (lambda: backend.selectTrack(SPA), lambda: backend.setStatsTab(1), lambda: backend.selectRow(OREGA),
                     lambda: backend.set_goal(f"{SPA}|{OREGA}", 121.0), lambda: backend.setConditionFilter(2),
                     lambda: backend.clearFilters(), lambda: backend.setGroupByClass(True),
                     lambda: backend.setSearch("ore"), lambda: backend.setClassFilter("LMP2_ELMS"),
                     lambda: backend.setSearch(""), lambda: backend.setClassFilter(""),
                     lambda: backend.selectTrack(""), lambda: backend.setUpcomingEnabled(True),
                     lambda: backend.setActivityYear(1), lambda: page.resize(860, 640), lambda: page.resize(1400, 860),
                     lambda: backend.setStatsTab(0)):  # Progression tab, then Overview (cards kept once made)
            step()
            settle(backend)
            for _ in range(3):
                QCoreApplication.processEvents()
        texts = item_texts(page.view)
        assert "Official Races to Come" in texts and "Driving time by track" in texts
        backend.selectTrack(SPA)
        QCoreApplication.processEvents()
        texts = item_texts(page.view)
        assert "Lap Time Goal" in texts and "2:01.000" in texts
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages
