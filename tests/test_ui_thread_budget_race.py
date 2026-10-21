"""Race calculator UI thread budget: live tab refresh, live values filled in & team stints of a 24 h race

Live tab rows synced in place (race time changes at each refresh: race card only notified), dry plan made once
per input change, team usage of the game parsed off the UI thread. Budget kept generous (slow CI machines).
"""

import sys
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication

from neopedal.api_control import api
from neopedal.module_info import ConsumptionDataSet, minfo
from neopedal.process import team_usage
from tests.test_game_usage import wait_request
from tests.test_perf_page_state import qml_warnings  # noqa: F401 (fixture)
from tests.test_race_calculator import host, page, set_race  # noqa: F401 (host, page: fixtures)
from tests.test_race_live_data import REFUEL_SCREEN, SESSION_SETTINGS, TYRE_SCREEN

UI_BUDGET = 0.05  # seconds a slot may hold the UI thread
DRIVERS = 60  # every driver of the usage answer late in a 24 h race
DRIVER_LAPS = 350


def timed(call) -> float:
    start = time.perf_counter()
    call()
    return time.perf_counter() - start


def best_of(call, count: int = 3) -> float:
    """Fastest of a few runs: one slow run on a busy CI machine is not the slot's cost"""
    return min(timed(call) for _ in range(count))


def big_usage() -> dict:
    usage, lap = {}, 0
    for driver in range(DRIVERS):
        entries = []
        for number in range(DRIVER_LAPS):
            lap += 1
            used = number % 35
            entries.append({"lap": lap, "stint": driver * 10 + number // 35, "fuel": 1 - used * 0.02,
                            "ve": 1 - used * 0.025, "tyres": [100 - used * 0.3] * 4, "pit": used == 0})
        usage[f"Driver {driver}"] = entries
    return usage


@pytest.fixture
def race_24h(page, monkeypatch):  # noqa: F811
    """24 h race under way: 100 laps of history, garage answered, live tab shown"""
    from neopedal.ui import game_rest
    from neopedal.ui.quick.race_backend import TABS

    laps = tuple(ConsumptionDataSet(lapNumber=400 - index, isValidLap=1, lapTimeLast=210.0 + index % 3,
                                    lastLapUsedFuel=4.0, lastLapUsedEnergy=3.5, tyreAvgWearLast=0.5,
                                    capacityFuel=100.0) for index in range(100))
    monkeypatch.setattr(minfo.history, "consumptionDataSet", laps)
    monkeypatch.setattr(game_rest, "request_game", lambda resource: None)  # game not asked
    clock = {"elapsed": 3600.0}
    read = api.read
    for target, name, value in (
            (read.state, "active", lambda: True), (read.session, "session_type", lambda: 4),
            (read.session, "in_race", lambda: True), (read.session, "start", lambda: 0.0),
            (read.session, "elapsed", lambda: clock["elapsed"]),
            (read.session, "remaining", lambda: 86400.0 - clock["elapsed"])):
        monkeypatch.setattr(target, name, value)
    backend = page.backend
    set_race(backend, minutes=1440, laptime=210.0, tank=100.0, fuel=4.0, pit=60.0, wear=0.5, minimum=20)
    backend.setTab(TABS.index("live"))
    backend.received_garage([REFUEL_SCREEN, TYRE_SCREEN, SESSION_SETTINGS])
    return backend, clock


def test_live_rows_kept_race_card_only(race_24h):
    backend, clock = race_24h
    model = backend.live_model
    assert model.rows[0]["header"] and model.rows[0]["key"].startswith("hdr:")
    assert len(backend.liveData["rows"]) == len(model.rows) - sum(1 for row in model.rows if row["header"])
    assert backend.liveRace and backend.liveTyres["allowed"] == 56
    signals: dict[str, list[int]] = {name: [] for name in ("liveRaceChanged", "liveTyresChanged", "liveDataStatusChanged",
                                     "liveBusyChanged", "liveDifferingChanged", "liveDataChanged")}
    resets, inserts, removes = [], [], []
    connections = [getattr(backend, name).connect(lambda *_, found=found: found.append(1))
                   for name, found in signals.items()]
    connections += [model.modelReset.connect(lambda: resets.append(1)),
                    model.rowsInserted.connect(lambda *_: inserts.append(1)),
                    model.rowsRemoved.connect(lambda *_: removes.append(1))]
    try:
        clock["elapsed"] += 2.0  # next live refresh: race time & time left only
        backend.publish_live_data()
        assert signals["liveRaceChanged"] and signals["liveDataChanged"]
        assert not (signals["liveTyresChanged"] or signals["liveDataStatusChanged"] or signals["liveBusyChanged"]
                    or signals["liveDifferingChanged"])
        assert not (resets or inserts or removes)
        signals["liveDataChanged"].clear()
        backend.publish_live_data()  # nothing changed: nothing notified
        assert not signals["liveDataChanged"]
        backend.setLiveFollowed("input_refuel_rate", False)  # one row changed in place
        assert not (resets or inserts or removes)
        assert not next(row for row in model.rows if row["key"] == "input_refuel_rate")["followed"]
    finally:
        for connection in connections:
            backend.disconnect(connection)


def test_dry_plan_made_once(race_24h, monkeypatch):
    from neopedal.ui.quick import race_live_tab

    backend, clock = race_24h
    plans = []
    original = race_live_tab.plan

    def plan_spy(setup):
        if sys._getframe(1).f_code.co_name == "dry_plan_laps":  # calculation of results left out
            plans.append(setup)
        return original(setup)

    monkeypatch.setattr(race_live_tab, "plan", plan_spy)
    for _ in range(3):  # live refreshes, inputs unchanged
        clock["elapsed"] += 2.0
        backend.publish_live_data()
    assert not plans
    backend.applyLiveValue("input_refuel_rate")  # inputs changed: planned again once, live values not read again
    assert len(plans) == 1
    collected = []

    def collect_spy(*args):
        collected.append(1)
        return []

    monkeypatch.setattr(race_live_tab, "collect_live", collect_spy)
    backend.applyAllLive()
    assert len(collected) == 1  # filled in & shown from one reading of the game


def test_team_usage_parsed_off_ui_thread(page, monkeypatch):  # noqa: F811
    from neopedal.ui import game_rest

    usage = big_usage()
    answers = {"/rest/strategy/usage": usage, "/rest/garage/UIScreen/RepairAndRefuel": {"fuelInfo": {"maxFuel": 100.0}}}
    monkeypatch.setattr(game_rest, "request_game", answers.get)
    threads = []
    parse = team_usage.parse_usage

    def parse_spy(data):
        threads.append(threading.current_thread())
        return parse(data)

    from neopedal.ui.quick import race_history

    monkeypatch.setattr(race_history, "parse_usage", parse_spy)
    backend = page.backend
    received = backend.received_team
    handed = []
    monkeypatch.setattr(backend.team_request, "_callback", lambda: lambda answer: handed.append(
        timed(lambda: received(answer))))
    backend.refreshTeam()
    wait_request(backend.team_request, timeout=30.0)
    assert threads and threads[0] is not threading.main_thread()
    assert len(backend.team_stints) == DRIVERS * 10 and backend.team_capacity == 100.0
    assert handed and handed[0] < UI_BUDGET * 2  # stints shown: 600 rows synced
    assert backend.team["rows"][0]["cells"][4] == "2.000"


def test_parse_usage_same_laps():
    data = {"A": [{"lap": 2, "stint": 1, "fuel": 0.5, "ve": 0.4, "tyres": [90, 92, 94, 96], "pit": 1},
                  {"lap": 1, "stint": 1, "fuel": "0.6", "ve": None, "tyres": None},
                  {"lap": 3, "stint": 1, "fuel": 1e999}, {"lap": 4, "stint": 1, "tyres": ["nan"]},
                  {"lap": 5, "stint": 1, "tyres": 5}, {"lap": 6}, "text"]}
    assert team_usage.parse_usage(data) == [team_usage.UsageLap("A", 1, 1, 0.6, 0.0, 0.0, False),
                                            team_usage.UsageLap("A", 1, 2, 0.5, 0.4, 93.0, True)]


def test_live_refresh_within_budget(race_24h):
    backend, clock = race_24h
    backend.set_active(True)
    try:
        for _ in range(3):
            clock["elapsed"] += 2.0
            assert timed(backend.publish_live_data) < UI_BUDGET
            assert timed(backend.refresh_live) < UI_BUDGET
        assert best_of(lambda: backend.apply_live(followed=True, filled=True)) < UI_BUDGET * 2
        assert best_of(backend.applyAllLive) < UI_BUDGET * 2
    finally:
        backend.set_active(False)


def test_live_tab_delegates_kept(page, race_24h, qml_warnings):  # noqa: F811
    """Live tab rows of the page kept on refresh: same delegates (scroll & hover kept), texts updated"""
    from PySide6.QtQuick import QQuickItem

    backend, clock = race_24h
    view = page.ensure_view()
    page.resize(1400, 2400)  # every row shown
    page.show()
    for _ in range(5):
        QCoreApplication.processEvents()
    stack, lists = [view.rootObject()], []
    while stack:
        item = stack.pop()
        if item.property("model") is backend.live_model:
            lists.append(item)
        stack.extend(item.childItems())
    assert lists
    content = lists[0].property("contentItem")
    assert isinstance(content, QQuickItem)

    def delegates():
        return {item.property("key"): item for item in content.childItems() if item.property("key")}

    before = delegates()
    assert "input_drivers" in before and before["hdr:race"].property("header")
    clock["elapsed"] += 2.0
    backend.publish_live_data()
    backend.setLiveFollowed("input_drivers", False)
    QCoreApplication.processEvents()
    after = delegates()
    assert all(after.get(key) is item for key, item in before.items())
    assert after["input_drivers"].property("followed") is False
    assert not qml_warnings


def test_plan_table_columns_kept(page, qml_warnings):  # noqa: F811
    """Plan table: shown columns & column widths replaced only when they change (not at each input step)"""
    backend = page.backend
    set_race(backend, minutes=1440, laptime=210.0, tank=100.0, fuel=4.0, pit=60.0, wear=0.5, minimum=20)
    backend.setTab(0)
    page.ensure_view()
    page.resize(1400, 1600)
    page.show()
    for _ in range(5):
        QCoreApplication.processEvents()
    stack, tables = [page.view.rootObject()], []
    while stack:
        item = stack.pop()
        if item.property("hiddenKeys") is not None and item.property("columns"):
            tables.append(item)
        stack.extend(item.childItems())
    table = next(item for item in tables if len(item.property("rows")) > 10)  # stints of the 24 h plan
    shown, widths, rows = [], [], []
    table.shownChanged.connect(lambda: shown.append(1))
    table.naturalWidthsChanged.connect(lambda: widths.append(1))
    table.rowsChanged.connect(lambda: rows.append(1))
    for step in range(1, 6):  # texts of the same widths: columns & widths kept
        backend.setInput("input_pit_seconds", 60.0 + step)
        QCoreApplication.processEvents()
    assert rows and not shown and not widths
    backend.setInput("input_lap_time", 211.0)  # new texts: columns kept
    QCoreApplication.processEvents()
    assert not shown
    assert not qml_warnings
