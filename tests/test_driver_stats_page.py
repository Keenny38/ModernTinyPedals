"""Driver stats viewer page rework: level scale, chart grid, daily activity, recent sessions, header line,
history read once per change, rows moved in place when sorted, keyboard actions, page without QML warnings"""

import time
from datetime import date, datetime, timedelta

import pytest
from PySide6.QtCore import QCoreApplication, qInstallMessageHandler

from tests.test_driver_stats_viewer import (  # noqa: F401  (fixtures)
    HISTORY,
    OREGA,
    SPA,
    STATS,
    backend,
    dialogs,
    item_texts,
    page,
    window,
)
from tinypedal.setting import cfg
from tinypedal.ui.quick import stats_backend
from tinypedal.userfile import driver_history
from tinypedal.userfile.driver_history import SessionRecord


def test_level_scale_marks(backend):  # noqa: F811
    backend.selectRow(OREGA)
    reference = backend.reference
    gauge = reference["gauge"]
    names = [segment["name"] for segment in gauge["segments"]]
    assert names[0] == "Offline" and names[-1] == "Alien" and len(names) == 6  # slowest on the left
    markers = {marker["label"]: marker for marker in gauge["markers"]}
    assert gauge["markers"][-1]["main"] and gauge["markers"][-1]["label"] == "PB"  # drawn on top
    # Faster lap time further right: PB 121.5 < qualifying 122.4 < race 124.0
    assert markers["PB"]["pos"] > markers["Qualifying"]["pos"] > markers["Race"]["pos"]
    assert 4 / 6 <= markers["PB"]["pos"] <= 5 / 6  # inside Competitive, 5th level from the left
    assert markers["Race"]["short"] == "R" and markers["PB"]["time"] == "2:01.500"
    assert reference["level"] == "Competitive" and reference["letter"] == "C" and reference["percent"].endswith(" %")
    assert reference["nextLevel"]["name"] == "Alien" and reference["nextLevel"]["toFind"] == chr(0x2212) + "0.42 s"
    assert reference["gapTime"].startswith("+") and reference["referenceTime"]
    ladder = {row["name"]: row for row in reference["ladder"]}
    assert ladder["Competitive"]["pills"] == ["PB"] and ladder["Competitive"]["letter"] == "C"


def test_level_scale_unknown_ladder():
    from tinypedal.userfile.lap_reference import LapReference

    viewer = stats_backend.DriverStatsBackend.__new__(stats_backend.DriverStatsBackend)
    reference = LapReference("Spa", "LMH", "", 100.0, (100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), "", 0.0)
    assert viewer.gauge_data(reference, [("PB", 101.0)]) == {}


def test_chart_ticks_and_grid(backend):  # noqa: F811
    assert stats_backend.chart_ticks(69.5, 72.6) == [70.0, 71.0, 72.0]
    assert stats_backend.chart_ticks(120.9, 121.7) == [121.0, 121.2, 121.4, 121.6]
    assert stats_backend.chart_ticks(5.0, 5.0) == []
    driver_history.save_history(cfg.path.config, HISTORY)
    backend.reload_stats()
    backend.selectRow(OREGA)
    progression = backend.progression
    assert progression["ticks"] and all(0 <= tick["y"] <= 1 for tick in progression["ticks"])
    assert progression["pbY"] == pytest.approx(progression["points"][1]["y"])  # personal best line
    assert [point["kind"] for point in progression["points"]] == [1, 2, 3, 3]  # practice, qualifying, race
    sessions = backend.sessions
    assert sessions[1]["podium"] == 2 and sessions[0]["podium"] == 0 and sessions[0]["kind"] == 3


def test_activity_and_recent_sessions(backend):  # noqa: F811
    today = datetime.combine(date.today(), datetime.min.time())
    noon = (today + timedelta(hours=12)).timestamp()
    driver_history.save_history(cfg.path.config, [
        SessionRecord(noon - 86400 * 400, SPA, OREGA, 1, 125.0, seconds=3000.0),  # older than shown weeks
        SessionRecord(noon - 86400 * 2, SPA, OREGA, 1, 122.0, seconds=1000.0),
        SessionRecord(noon - 86400, SPA, OREGA, 4, 121.5, seconds=4000.0, position=1, finish=1),
        SessionRecord(noon - 3600, "Monza", "GT3 - BMW", 2, 107.2, seconds=8000.0),
        SessionRecord(noon, "Imola", "GT3 - BMW", 1, 99.0, seconds=600.0),  # track without stats
    ])
    backend.reload_stats()
    backend.selectTrack("")
    activity = backend.activity
    days = activity["days"]
    assert activity["weeks"] == stats_backend.ACTIVITY_WEEKS and len(days) == stats_backend.ACTIVITY_WEEKS * 7
    first = date.today() - timedelta(days=date.today().weekday() + (stats_backend.ACTIVITY_WEEKS - 1) * 7)
    index = (date.today() - first).days
    assert days[index]["level"] == 4  # 8000 s + 600 s today
    assert days[index - 1]["level"] == 3 and days[index - 2]["level"] == 1  # 4000 s, 1000 s
    assert all(day["level"] == -1 for day in days[index + 1:])  # days to come
    assert "3 days driven" in activity["summary"] and "longest streak 3 days" in activity["summary"]
    assert activity["months"][0]["week"] == 0 and len(activity["dayNames"]) == 3
    recent = backend.recent
    assert [row["track"] for row in recent] == ["Monza", SPA, SPA, SPA]  # newest first, removed track left out
    assert recent[0]["pb"] and recent[0]["kind"] == 2 and recent[1]["result"] == "P1" and recent[1]["podium"] == 1
    assert recent[1]["pb"] and not recent[2]["pb"]
    assert backend.activity is backend.activity_data()  # computed once per history & day


def test_header_line_and_tiles(backend):  # noqa: F811
    driver_history.save_history(cfg.path.config, HISTORY)
    backend.reload_stats()
    info = backend.trackInfo
    assert info["live"] and info["subtitle"].startswith("2 vehicles · 4 sessions · last driven")
    assert all(tile["glyph"] for tile in backend.tiles)
    tiles = {tile["title"]: tile for tile in backend.tiles}
    assert tiles["Level"]["letter"] == "A" and 0 < tiles["Valid Laps"]["ratio"] <= 1
    backend.selectTrack("")
    assert not backend.trackInfo["live"] and backend.trackInfo["subtitle"].startswith("2 tracks · 5 sessions · since")


def test_cells_dimmed_and_level_pill(backend):  # noqa: F811
    columns = [column["key"] for column in backend.columns]
    row = backend.rows.rows[backend.row_keys().index(OREGA)]["cells"]
    theory = row[columns.index("theory")]
    level = row[columns.index("level")]
    assert theory["dim"] and not theory["pill"]  # no sector best: unknown
    assert level["pill"] and not level["dim"] and level["color"]
    assert row[columns.index("pb")]["bold"]


def test_history_read_only_when_changed(backend, monkeypatch):  # noqa: F811
    calls = []
    original = stats_backend.load_history
    monkeypatch.setattr(stats_backend, "load_history", lambda path: calls.append(path) or original(path))
    backend.reload_stats()
    backend.reload_stats()
    assert not calls  # stats saved every lap: history unchanged
    driver_history.append_record(cfg.path.config, SessionRecord(time.time(), SPA, OREGA, 1, 121.9, seconds=900.0))
    backend.reload_stats()
    assert len(calls) == 1 and len(backend.history) == 1


def test_sort_moves_rows_in_place(backend):  # noqa: F811
    model = backend.rows
    resets, moves = [], []
    model.modelReset.connect(lambda: resets.append(True))
    model.rowsMoved.connect(lambda *args: moves.append(args))
    sort_signals = []
    backend.sortChanged.connect(lambda: sort_signals.append(True))
    stats_signals = []
    backend.statsChanged.connect(lambda: stats_signals.append(True))
    backend.selectionChanged.connect(lambda: stats_signals.append(True))  # chart drawn again
    assert backend.row_keys() == ["Hyper - Ferrari", OREGA]  # personal best, fastest first
    backend.sortBy("pb")  # slowest first
    assert backend.row_keys() == [OREGA, "Hyper - Ferrari"] and moves and not resets
    assert sort_signals and not stats_signals  # key figures & columns not built again
    backend.reload_stats()  # stats saved meanwhile: same track, rows kept
    assert not resets
    backend.selectTrack("Monza")
    assert resets  # other track: rows rebuilt


def test_open_session_and_delete_selected(backend):  # noqa: F811
    backend.selectTrack("")
    backend.openSession(SPA, "Hyper - Ferrari")
    assert backend.currentTrack == SPA and backend.selectedKey == "Hyper - Ferrari"
    backend.openSession("Removed", "Car")  # track without stats: nothing
    assert backend.currentTrack == SPA
    backend.deleteSelected()  # vehicle of track
    assert "Hyper - Ferrari" not in backend.stats_temp[SPA]
    backend.showAllTracks()
    backend.selectRow("Monza")
    backend.deleteSelected()  # track of All Tracks
    assert "Monza" not in backend.stats_temp
    backend.undo()
    assert "Monza" in backend.stats_temp


def test_page_without_qml_warnings(page):  # noqa: F811
    messages = []
    previous = qInstallMessageHandler(lambda mode, context, text: messages.append(text))
    try:
        page.resize(1400, 860)
        page.show()
        backend = page.backend
        for step in (lambda: backend.selectRow(OREGA), lambda: backend.sortBy("vehicle"),
                     lambda: backend.setSessionFilter(3), lambda: backend.selectTrack(""),
                     lambda: backend.sortBy("meters"), lambda: backend.setColumnVisible("meters", False),
                     lambda: page.resize(860, 640), lambda: backend.selectTrack(SPA),
                     lambda: backend.setColumnVisible("meters", True), lambda: page.resize(1400, 860)):
            step()
            for _ in range(3):
                QCoreApplication.processEvents()
        backend.selectTrack("")
        QCoreApplication.processEvents()
        texts = item_texts(page.view)
        assert "Activity" in texts and "Recent Sessions" in texts and "Levels, All Tracks" in texts
        backend.selectTrack(SPA)
        QCoreApplication.processEvents()
        texts = item_texts(page.view)
        assert "Lap Time Reference" in texts and "Progression" in texts and "Next level" in texts
    finally:
        qInstallMessageHandler(previous)
    assert not [text for text in messages if ".qml" in text], messages
