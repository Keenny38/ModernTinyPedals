"""Broadcast Director performance: hidden page & tabs make no rows, settings written & graphics sent once changes
pause, best sectors once per answer, events log & results files off the UI thread, frequently changing parts bound
apart, popups made when opened, timing cells light"""

import json
import threading
import time

from PySide6.QtCore import QCoreApplication, QEvent, QObject, qInstallMessageHandler
from PySide6.QtQuick import QQuickItem
from shiboken6 import getCppPointer

from neopedal.process import director as dr
from tests.test_broadcast_director import car, director_page, poll, race_answers  # noqa: F401
from tests.test_game_info import wait_requests


def process_events(seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def descendants(item: QQuickItem):
    """Visual children of an item, all levels (view delegates have no QObject parent)"""
    for child in item.childItems():
        yield child
        yield from descendants(child)


def wait_jobs(backend, timeout: float = 5.0):
    end = time.monotonic() + timeout
    while backend.jobs.running and time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert not backend.jobs.running


def test_timing_rows_made_while_page_shown_only(director_page):  # noqa: F811
    page, backend = director_page, director_page.backend
    backend.timing.setTimingOpen(True)
    backend._shown = False
    poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=600.0)))
    assert backend.timing.timingRows.rowCount() == 0 and backend.timing._timing_stale
    backend.page_shown()
    wait_requests(backend.game.request_state)
    backend.game._timer.stop()
    assert backend.timing.timingRows.rowCount() == 2 and not backend.timing._timing_stale


def test_settings_written_once_changes_pause(director_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import director_backend as db
    from neopedal.ui.quick import page_settings

    backend = director_page.backend
    writes: list[dict] = []
    real = page_settings.write_settings

    def save(name, data):
        writes.append(json.loads(json.dumps(data)))
        real(name, data)

    monkeypatch.setattr(page_settings, "write_settings", save)
    for value in range(10, 20):  # arrow held on a number
        backend.setNumber("minShot", value)
    assert writes == [] and backend.page_file.pending and backend.minShot == 19
    process_events(db.SAVE_DELAY_MS / 1000 + 0.3)
    assert len(writes) == 1 and writes[0]["min_shot"] == 19
    backend.setNumber("battleGap", 2.0)
    assert db.load_page_settings()["battle_gap"] == 2.0  # settings read: changes of the open page written first
    assert len(writes) == 2
    backend.setNumber("secondsBefore", 7)
    backend.app_quitting()  # app closing with the page open: written at once
    assert len(writes) == 3 and writes[-1]["seconds_before"] == 7
    backend.setNumber("postRoll", 9)
    backend.release()  # page closing: written at once
    assert len(writes) == 4 and writes[-1]["post_roll"] == 9 and not backend.page_file.pending


def test_graphics_sent_at_most_every_delay_while_a_setting_changes(director_page, monkeypatch):  # noqa: F811
    from neopedal.stream_director import director_feed
    from neopedal.ui.quick import director_graphics as dgfx

    backend = director_page.backend
    published: list[dict] = []
    monkeypatch.setattr(director_feed, "publish", published.append)
    monkeypatch.setattr(director_feed, "watched", lambda: False)  # sent only when forced (settings)
    monkeypatch.setattr(dgfx, "PUBLISH_DELAY_MS", 500)  # slow machines: arrow repeats stay within the delay
    backend.graphics._publish_timer.setInterval(500)
    for rows in range(3, 13):  # arrow held: first value sent at once, the last one once the delay passed
        backend.graphics.setGraphic("towerRows", rows)
    assert len(published) == 1 and published[0]["graphics"]["towerRows"] == 3
    process_events(0.8)
    assert len(published) == 2 and published[-1]["graphics"]["towerRows"] == 12
    backend.graphics.setGraphic("hidden", True)  # another setting: sent at once
    assert len(published) == 3 and published[-1]["graphics"]["hidden"]
    backend.graphics.setGraphic("towerRows", 4)
    backend.graphics.setGraphic("towerRows", 5)
    backend.release()  # page closing: last change sent
    assert published[-1]["graphics"]["towerRows"] == 5


def test_best_sectors_made_once_per_answer(director_page, monkeypatch):  # noqa: F811
    page, backend = director_page, director_page.backend
    calls = []
    real = dr.RaceWatcher.best_sectors

    def best_sectors(self, cars):
        calls.append(1)
        return real(self, cars)

    monkeypatch.setattr(dr.RaceWatcher, "best_sectors", best_sectors)
    cars = (car(1, 1, distance=2040.0, best=90.0, best_sector1=30.0, best_sector2=60.0), car(2, 2, distance=2000.0))
    poll(page, race_answers(100.0, *cars))
    backend.timing.setTimingOpen(True)  # cars, timing, sheet & laps: four lists using best sectors
    backend.selectCar(1)
    backend.showLaps(1)
    calls.clear()
    poll(page, race_answers(101.0, *cars))
    assert len(calls) == 1
    assert backend.sheet["sectors"][0]["tone"] == "" and backend.timing.timingRows.rows[0]["bestTone"] == "fastest"


def test_events_log_written_in_order_by_writer_thread(director_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import director_log as dlog

    page, backend = director_page, director_page.backend
    gate = threading.Event()
    threads = []
    real = dlog.write_log_rows

    def slow(path, rows):
        gate.wait(5)
        threads.append(threading.current_thread().name)
        real(path, rows)

    monkeypatch.setattr(dlog, "write_log_rows", slow)
    backend.log.setLogEvents(True)
    poll(page, race_answers(100.0, car(1, 1), car(2, 2, distance=600.0)))
    start = time.perf_counter()
    for number in range(3):  # disk slow: the page does not wait
        backend.add_events([dr.Event(f"fastest|{number}", dr.FASTEST, 100.0 + number, (1,), ("Driver 1",), "GT3",
                                     1, 88.0 - number)])
    assert time.perf_counter() - start < 1.0 and not threads
    gate.set()
    with open(backend.log.log_path(), encoding="utf-8-sig") as file:  # lines given so far written first
        lines = file.read().splitlines()
    assert lines[0].startswith("Time,Session time")
    assert [line.split(",")[1] for line in lines[1:]] == ["0:01:40", "0:01:41", "0:01:42"]
    assert threads and all(name == "Director events log" for name in threads)


def test_results_files_read_by_page_jobs(director_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import director_backend as db
    from neopedal.ui.quick import director_graphics as dgfx

    backend = director_page.backend
    wait_jobs(backend)  # history read when the page opened
    gate = threading.Event()
    scans = []

    def scan():
        gate.wait(5)
        scans.append(threading.current_thread().name)
        return True

    monkeypatch.setattr(db, "scan_history", scan)
    sheets = []
    monkeypatch.setattr(backend, "update_sheet", lambda: sheets.append(1))
    backend.read_history()
    backend.read_history()  # one read at a time
    assert backend.jobs.running == 1 and backend.jobs.is_busy("history")
    gate.set()
    wait_jobs(backend)
    assert scans == ["Broadcast director race history"] and sheets == [1]  # sheet shows the new history
    # Qualifying times of the starting grid: read once a session, shown once read
    monkeypatch.setattr(dgfx, "read_qualifying_times", lambda track: {"Driver 1": 88.5} if track == "test ring" else {})
    backend.session_key = ("Test Ring", "RACE1", 0)
    assert backend.graphics.qualifying_times() == {}
    wait_jobs(backend)
    assert backend.graphics.qualifying_times() == {"Driver 1": 88.5}
    # Page closing: jobs cancelled, nothing handed over
    backend.session_key = ("Other Ring", "RACE1", 0)
    backend.graphics.qualifying_times()
    backend.release()
    wait_jobs(backend)
    assert backend.graphics._quali_times == (("Other Ring", "RACE1", 0), {})


def test_pit_radar_rows_change_without_touching_on_air_card(director_page):  # noqa: F811
    page, backend = director_page, director_page.backend

    def cars(gap):
        return car(1, 1, distance=10.0, in_pit=True), car(2, 2, distance=10.0 + gap, in_pit=True), car(3, 3)

    poll(page, race_answers(100.0, *cars(30.0), focus=1))
    assert backend.onAir["slot"] == 1 and backend.pitRadarCount == 1
    card, radar = [], []
    backend.onAirChanged.connect(lambda: card.append(1))
    backend.pitRadarChanged.connect(lambda: radar.append(1))
    poll(page, race_answers(101.0, *cars(20.0), focus=1))
    assert backend.pitRadarRows.rows[0]["distance"] == "20 m" and radar and not card
    assert backend.onAir["pitRadar"][0]["distance"] == "20 m"  # Python readers: last radar on the card too
    poll(page, race_answers(102.0, car(1, 1, distance=10.0), *cars(20.0)[1:], focus=1))  # out of the pit lane
    assert backend.pitRadarCount == 0


def test_sheet_live_values_bound_apart_from_driver(director_page):  # noqa: F811
    page, backend = director_page, director_page.backend
    poll(page, race_answers(100.0, car(1, 1, distance=2040.0), car(2, 2, distance=2000.0)))
    backend.selectCar(2)
    assert backend.sheetCar["driver"] == "Driver 2" and backend.sheetLive["intervalAhead"] == "+0.8"
    fixed, live = [], []
    backend.sheetCarChanged.connect(lambda: fixed.append(1))
    backend.sheetLiveChanged.connect(lambda: live.append(1))
    poll(page, race_answers(101.0, car(1, 1, distance=2040.0), car(2, 2, distance=1980.0)))
    assert live and not fixed and backend.sheet["intervalAhead"] == backend.sheetLive["intervalAhead"] == "+1.2"
    assert not set(backend.sheetCar) & set(backend.sheetLive)
    assert set(backend.sheetCar) | set(backend.sheetLive) == set(backend.sheet)


def test_hidden_commentary_tabs_made_once_shown(director_page):  # noqa: F811
    page, backend = director_page, director_page.backend
    counts = []
    backend.battlesChanged.connect(lambda: counts.append(backend.battleCount))
    cars = (car(1, 1, distance=1040.0), car(2, 2, distance=1000.0, pitstops=1))
    poll(page, race_answers(100.0, *cars))
    assert backend.commentary_tab == 0  # events tab shown
    assert backend._battles_model.rowCount() == 0 and backend._pits_model.rowCount() == 0
    assert backend.battleCount == 1 and counts == [1]  # count of the tab title told anyway
    backend.setCommentaryTab(1)
    assert backend._battles_model.rowCount() == 1 and backend._pits_model.rowCount() == 0
    assert backend.pitRows.rowCount() == 1  # model asked (view given it): made at once


def test_unseen_count_and_filter_told_apart_from_feed(director_page):  # noqa: F811
    page, backend = director_page, director_page.backend
    cars = (car(1, 1, distance=2000.0), car(2, 2, distance=1000.0), car(3, 3, distance=400.0))
    poll(page, race_answers(100.0, *cars))
    unseen, filters = [], []
    backend.unseenChanged.connect(lambda: unseen.append(backend.unseenCount))
    backend.feedFilterChanged.connect(lambda: filters.append(backend.feedFilter))
    contacts = ((100.5, "Driver 3", "Driver 2"),)
    poll(page, race_answers(101.0, *cars, contacts=contacts))
    poll(page, race_answers(102.0, *cars, contacts=contacts))
    assert unseen == [1]
    backend.setFeedFilter(1)
    assert filters == [1] and unseen == [1]
    backend.markAllSeen()
    assert unseen == [1, 0]
    assert backend.camera.cameras is backend.camera.cameras and backend.cameraStyles is backend.cameraStyles


def test_timing_column_moved_or_toggled_alone(director_page):  # noqa: F811
    backend = director_page.backend
    model = backend.timing.timingColumnRows

    def keys():
        return [row["key"] for row in model.rows]

    assert keys() == [column["key"] for column in backend.timing.timingColumns]
    resets, moves, inserts = [], [], []
    model.modelReset.connect(lambda: resets.append(1))
    model.rowsMoved.connect(lambda *args: moves.append(1))
    model.rowsInserted.connect(lambda *args: inserts.append(1))
    backend.timing.moveTimingColumn(0, 2)
    assert keys() == [column["key"] for column in backend.timing.timingColumns] and moves == [1]
    backend.timing.toggleTimingColumn("team")
    assert keys()[-1] == "team" and inserts == [1] and not resets


def test_popup_contents_made_when_opened_and_timing_cells_light(director_page, monkeypatch):  # noqa: F811
    from neopedal.ui.quick import director_backend as db

    page, backend = director_page, director_page.backend
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        root = page.view.rootObject()
        page.resize(1400, 900)  # room for the table rows (popups stay inside the window)
        page.show()
        process_events(0.2)
        for name in ("graphicsTabs", "lapList", "timingList", "timingViews"):
            assert root.findChild(QObject, name) is None, name  # made once opened
        graphics = root.findChild(QObject, "graphicsPopup")
        graphics.setProperty("visible", True)
        QCoreApplication.processEvents()
        assert root.findChild(QObject, "graphicsTabs") is not None
        graphics.setProperty("visible", False)
        process_events(0.3)
        assert root.findChild(QObject, "graphicsTabs") is not None  # kept: opens at once next time
        monkeypatch.setattr(db.DirectorBackend, "read_tyres", staticmethod(lambda: {1: ("S", "M"), 2: ("W", "W")}))
        cars = [car(slot, slot, distance=3000.0 - slot * 50, penalties=slot % 2) for slot in range(1, 7)]
        poll(page, race_answers(100.0, *cars))
        timing = root.findChild(QObject, "timingTable")
        timing.setProperty("visible", True)
        process_events(0.2)
        view = root.findChild(QQuickItem, "timingList")
        table = view.property("contentItem")
        columns = backend.timing.timingColumnRows.rowCount()
        cells = [item for item in descendants(table) if item.property("size") is not None]
        rows = len(cells) // columns
        assert rows == 6 and len(cells) == rows * columns
        rings = [item.property("letter") for item in descendants(table) if item.property("letter") and item.isVisible()]
        assert sorted(rings) == ["M", "S", "W"]  # one ring per compound
        items = len(list(descendants(table)))
        assert items < rows * columns * 2.5  # one Text per cell, a Loader for tyres, energy & penalties only

        def cells_of(key):
            return [item for item in descendants(table) if item.property("key") == key
                    and item.property("size") is not None]

        def driver_cells():
            return {getCppPointer(item)[0] for item in cells_of("driver")}

        before = driver_cells()
        backend.timing.moveTimingColumn(0, 2)
        process_events(0.1)
        assert driver_cells() == before  # cells of other columns kept
        assert cells_of("penalties")[0].property("text") == "1"
        timing.setProperty("exit", None)  # closes at once: an offscreen window may never run the fade out
        timing.setProperty("visible", False)
        for _ in range(30):  # close & deferred delete (not run by processEvents outside an event loop)
            process_events(0.1)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            if root.findChild(QObject, "timingList") is None:
                break
        assert root.findChild(QObject, "timingList") is None  # big table freed once closed
        backend.timing.setTimingOpen(False)
        # Car sheet & pit radar bound on their own, settings & lap history made when opened: no warning
        backend.selectCar(2)
        settings = root.findChild(QObject, "settingsPopup")
        settings.setProperty("visible", True)
        backend.showLaps(1)
        process_events(0.2)
        assert root.findChild(QObject, "lapList") is not None
        backend.showLaps(-1)
        settings.setProperty("visible", False)
        process_events(0.2)
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages


def test_layout_file_written_as_before(tmp_path):
    from neopedal.stream_director import PlacementStore

    store = PlacementStore("layout.json")
    setattr(store, "folder", lambda: str(tmp_path))  # noqa: B010
    store.set("", {"tower": [0.1, 0.2, 1.2], "clock": [0.5, 0.5, 1.0]})
    text = (tmp_path / "layout.json").read_text(encoding="utf-8")
    assert text == json.dumps({"": {"tower": [0.1, 0.2, 1.2], "clock": [0.5, 0.5, 1.0]}}, indent=1)


def test_state_requests_share_answers_of_other_readers():
    """Recent answer of another reader (connector, page) used, own answers handed to them; game asked once"""
    from neopedal.game_rest_cache import rest_cache
    from neopedal.ui.quick import director_game as dgame
    from neopedal.ui.quick import director_shared as ds

    address = ("localhost", 6397)
    asked = []

    class Connection:
        failed = False
        answered = False

        def __init__(self):
            self.address = address

        def request(self, method, resource, body=None):
            asked.append((method, resource))
            self.answered = True
            return (400, b"-1") if resource == "/rest/watch/focus" else (200, b"null")

    rest_cache.store("/rest/replay/isActive", 200, b"false", address)
    shared = dgame.SharedConnection(Connection(), ds.SHARED_MAX_AGE)
    assert shared.get("/rest/replay/isActive") is False and shared.answered and asked == []
    assert shared.get("/rest/watch/focus") == -1  # error status: body kept, as asked directly
    assert asked == [("GET", "/rest/watch/focus")]
    assert rest_cache.fresh("/rest/watch/focus", 1.0, address).body == b"-1"
    assert shared.get("/rest/watch/focus") == -1 and len(asked) == 1
    # Game not answering: nothing stored, nothing asked after
    failed = Connection()
    failed.failed = True
    assert dgame.SharedConnection(failed, ds.SHARED_MAX_AGE).get("/rest/watch/standings") is None
    assert rest_cache.fresh("/rest/watch/standings", 1.0, address) is None
