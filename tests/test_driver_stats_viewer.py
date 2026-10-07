"""Driver stats viewer (Qt Quick page, quick/stats_backend.py): edits, undo, history, All Tracks, export, page"""

import json
import os
import sys
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMessageBox
from test_lap_reference import SHEET

from tinypedal.const_common import MAX_SECONDS, TEXT_NOLAPTIME
from tinypedal.setting import cfg
from tinypedal.userfile import driver_history, driver_stats, lap_reference
from tinypedal.userfile.driver_history import SessionRecord
from tinypedal.userfile.driver_stats import DriverStats, validate_stats_file

SPA = "Circuit de Spa-Francorchamps Endurance"
OREGA = "LMP2_ELMS - Oreca"


@pytest.fixture
def dialogs(ui_env, monkeypatch):
    """Confirm every question, record warnings, fail on exception raised in Qt slots"""
    from tinypedal.ui._common import BaseDialog

    warnings = []
    slot_errors = []
    monkeypatch.setattr(BaseDialog, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))
    monkeypatch.setattr(sys, "excepthook", lambda *exc_info: slot_errors.append(exc_info[1]))
    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    yield warnings
    assert not slot_errors


def write_stats(stats: dict):
    with open(f"{cfg.path.config}driver.stats", "w", encoding="utf-8") as file:
        json.dump(stats, file)


def load_stats() -> dict:
    with open(f"{cfg.path.config}driver.stats", encoding="utf-8") as file:
        return json.load(file)


STATS = {
    SPA: {
        OREGA: {"pb": 121.5, "qb": 122.4, "rb": 124.0, "meters": 50000.0, "seconds": 1800.0,
                "liters": 20.0, "valid": 30, "invalid": 10, "penalties": 1, "races": 2, "wins": 1,
                "podiums": 1, "starts": 4, "dnf": 1, "positions": 4, "placed": 2},
        "Hyper - Ferrari": {"pb": 119.0},
    },
    "Monza": {"GT3 - BMW": {"pb": 107.2, "seconds": 600.0}},
}


@pytest.fixture
def window(dialogs, monkeypatch):
    """Page host without Qt Quick view: backend alone"""
    from tinypedal.api_control import api
    from tinypedal.ui._common import BaseDialog

    write_stats(STATS)
    lap_reference.save_cache(cfg.path.config, SHEET)
    monkeypatch.setattr(type(api.read.session), "track_name", lambda self: SPA, raising=False)
    host = BaseDialog(None)
    yield host
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def backend(window):
    from tinypedal.ui.quick.stats_backend import DriverStatsBackend

    page = DriverStatsBackend(window)
    yield page
    page.release()


def text_of(page, key, column):
    return page.cell(key, column).text


# --- Corrections
def test_invalid_values_converted():
    stats = validate_stats_file({"T": {"Car": {"pb": None, "valid": "4", "meters": "abc", "wins": True, "x": "y"},
                                       "Bad": 3}})
    car = stats["T"]["Car"]
    assert car["pb"] == DriverStats.pb and car["valid"] == 4 and car["meters"] == 0.0 and car["wins"] == 1
    assert car["x"] == "y"  # unknown key kept
    assert stats["T"]["Bad"] == {}


def test_page_with_invalid_values(window):
    from tinypedal.ui.quick.stats_backend import DriverStatsBackend

    write_stats({"T": {"Car": {"pb": None, "rb": "abc", "seconds": "x", "valid": "4"}}})
    page = DriverStatsBackend(window)
    page.selectTrack("T")
    assert text_of(page, "Car", "valid") == "4"


def test_edit_keeps_stats_saved_meanwhile(backend):
    stats = load_stats()  # saved by stats module after page opened
    stats["Monza"]["GT3 - BMW"]["seconds"] = 999.0
    stats["Imola"] = {"GT3 - BMW": {"pb": 101.0}}
    write_stats(stats)
    backend.resetLapTime("Hyper - Ferrari", "pb")
    saved = load_stats()
    assert saved[SPA]["Hyper - Ferrari"]["pb"] > 9999
    assert saved["Monza"]["GT3 - BMW"]["seconds"] == 999.0 and "Imola" in saved


def test_undo_merges_stats_recorded_since(backend):
    backend.deleteTrack(SPA)
    assert SPA not in load_stats()
    # Stats module saves a stint on deleted track, before undo
    driver_stats.save_driver_stats((SPA, OREGA), DriverStats(pb=121.0, valid=5, meters=1000.0), cfg.path.config)
    backend.undo()
    restored = load_stats()[SPA][OREGA]
    assert restored["valid"] == 35 and restored["meters"] == 51000.0  # added
    assert restored["pb"] == 121.0  # faster lap kept
    assert load_stats()[SPA]["Hyper - Ferrari"] == {"pb": 119.0}
    # Lap time reset, faster lap set since: undo keeps it
    backend.resetLapTime(OREGA, "qb")
    driver_stats.save_driver_stats((SPA, OREGA), DriverStats(qb=120.5), cfg.path.config)
    backend.undo()
    assert load_stats()[SPA][OREGA]["qb"] == 120.5


def test_undo_redo_edits(backend):
    backend.selectRow("Hyper - Ferrari")
    backend.removeVehicle()
    assert "Hyper - Ferrari" not in load_stats()[SPA]
    backend.resetLapTime(OREGA, "qb")
    assert load_stats()[SPA][OREGA]["qb"] > 9999
    backend.undo()
    assert load_stats()[SPA][OREGA]["qb"] == 122.4
    backend.undo()
    assert load_stats()[SPA]["Hyper - Ferrari"] == {"pb": 119.0}
    assert backend.canRedo and not backend.canUndo
    backend.redo()
    assert "Hyper - Ferrari" not in load_stats()[SPA]
    backend.deleteTrack("")
    assert SPA not in load_stats() and backend.selected_stats_key == "Monza"
    backend.undo()
    assert SPA in load_stats() and backend.selected_stats_key == SPA


def test_sort_and_selection_kept_on_reload(backend):
    backend.sortBy("valid")
    assert backend.sortKey == "valid" and backend.sortDescending  # more first
    backend.selectRow("Hyper - Ferrari")
    stats = load_stats()
    stats[SPA]["Hyper - Ferrari"]["valid"] = 99
    write_stats(stats)
    os.utime(f"{cfg.path.config}driver.stats", (1, 1))
    backend.reload_if_changed()
    assert backend.sortKey == "valid" and backend.row_keys()[0] == "Hyper - Ferrari"
    assert backend.selectedKey == "Hyper - Ferrari"
    backend.sortBy("valid")  # again: reverse order
    assert not backend.sortDescending and backend.row_keys()[-1] == "Hyper - Ferrari"
    backend.reference_downloaded(SHEET, "")
    assert backend.selectedKey == "Hyper - Ferrari"


def test_stats_file_lock_between_module_and_page(tmp_path):
    filepath = f"{tmp_path.as_posix()}/"
    done = threading.Event()

    def module_save():
        driver_stats.save_driver_stats(("T", "Car"), DriverStats(valid=1), filepath)
        done.set()

    with driver_stats.STATS_LOCK:  # page edit in progress
        thread = threading.Thread(target=module_save)
        thread.start()
        assert not done.wait(0.2)  # module waits
    assert done.wait(5)
    thread.join()
    assert driver_stats.load_driver_stats(("T", "Car"), filepath).valid == 1


def test_reset_lap_time_clears_history_best(backend):
    driver_history.save_history(cfg.path.config, [
        SessionRecord(1000.0, SPA, OREGA, 1, 123.0), SessionRecord(2000.0, SPA, OREGA, 1, 121.5),
        SessionRecord(3000.0, SPA, OREGA, 4, 122.0)])
    backend.reload_stats()
    backend.selectRow(OREGA)
    backend.resetLapTime(OREGA, "pb")
    bests = [record.best for record in driver_history.load_history(cfg.path.config)]
    assert bests == [123.0, 0.0, 122.0]  # reset lap left out of progression
    backend.selectRow(OREGA)
    assert len(backend.progression["points"]) == 2
    assert "2:01.500" not in backend.progression["top"]
    backend.undo()
    assert [record.best for record in driver_history.load_history(cfg.path.config)] == [123.0, 121.5, 122.0]
    # Faster session best than personal best (reset by older version): left out
    assert driver_history.best_progression([SessionRecord(1.0, "T", "C", 1, 100.0),
                                            SessionRecord(2.0, "T", "C", 1, 102.0)], best=101.0)[0][1] == 102.0


def test_plurals_and_dates(backend, monkeypatch):
    from tinypedal import i18n
    from tinypedal.ui.quick import stats_backend

    tiles = {tile["title"]: tile for tile in backend.tiles}
    assert tiles["Races"]["detail"] == "1 win · 1 podium"
    assert stats_backend.plural(2, "session", "sessions") == "2 sessions"
    i18n.set_language("Français")
    try:
        assert stats_backend.plural(1, "win", "wins") == "1 victoire"
        assert stats_backend.plural(0, "win", "wins") == "0 victoire"
        monkeypatch.setattr(stats_backend.QLocale, "system", staticmethod(lambda: stats_backend.QLocale("en_US")))
        date = stats_backend.format_date(1_760_000_000)  # 2025-10-09
        assert date.startswith(("09/10/", "9/10/"))  # French day first
    finally:
        i18n.set_language("English")
    assert stats_backend.format_date(0) == "-"


# --- Quick improvements & additions
HISTORY = [
    SessionRecord(1_700_000_000.0, SPA, OREGA, 1, 123.0, valid=8, invalid=1),
    SessionRecord(1_700_100_000.0, SPA, OREGA, 2, 121.5, valid=4),
    SessionRecord(1_700_200_000.0, SPA, OREGA, 4, 122.0, valid=20, position=2, finish=1),
    SessionRecord(1_700_250_000.0, SPA, OREGA, 4, 122.8, valid=3, finish=2),
    SessionRecord(1_700_300_000.0, "Monza", "GT3 - BMW", 1, 107.2),
]


def test_progression_tips_filter_and_sessions(backend):
    driver_history.save_history(cfg.path.config, HISTORY)
    backend.reload_stats()
    backend.selectRow(OREGA)
    progression = backend.progression
    assert progression["visible"] and len(progression["points"]) == 4
    first = progression["points"][0]
    assert "Practice" in first["tip"] and "2:03.000" in first["tip"] and first["newPb"]
    assert [point["newPb"] for point in progression["points"]] == [True, True, False, False]
    assert len(progression["dates"]) == 3 and progression["top"] == "2:01.500"
    assert "PB 2:01.500 set on" in progression["info"] and "4 sessions" in progression["info"]
    sessions = backend.sessions
    assert [entry["result"] for entry in sessions] == ["DNF", "P2", "", ""]  # newest first
    assert sessions[2]["pb"] and sessions[0]["laps"] == "3/3" and sessions[3]["laps"] == "8/9"
    backend.setSessionFilter(3)  # race sessions
    assert len(backend.sessions) == 2 and len(backend.progression["points"]) == 2
    backend.setSessionFilter(1)  # practice: one session, no chart
    assert not backend.progression["visible"] and len(backend.sessions) == 1


def test_next_level_and_qualifying_mark(backend):
    backend.selectRow(OREGA)
    reference = backend.reference
    marks = [row["marks"] for row in reference["ladder"]]
    assert "PB" in marks[1] and "Qualifying" in marks[2] and "Race" in marks[3]
    assert reference["next"] == "Next level Alien: 0.42 s to find"  # 121.50 - 121.08
    backend.selectRow("Hyper - Ferrari")
    assert backend.reference["next"] == "Top level reached"
    spa = lap_reference.parse_lap_references(SHEET).entries[("Spa", "LMP2elms")]
    assert spa.level_limit(3) == pytest.approx(125.92) and spa.level_limit(5) == 0
    assert spa.next_level(140.0) == (4, pytest.approx(140.0 - 128.34))


def test_durations_and_derived_columns(backend, monkeypatch):
    from tinypedal.ui.quick import stats_backend

    assert stats_backend.format_duration(45 * 60) == "45 min"
    assert stats_backend.format_duration(12 * 3600 + 5 * 60) == "12 h 05 min"
    assert {tile["title"]: tile["value"] for tile in backend.tiles}["Driving Time"] == "30 min"
    assert text_of(backend, OREGA, "valid_rate") == "75 %"
    assert text_of(backend, OREGA, "speed") == "100.0"  # 50 km in half an hour
    assert text_of(backend, OREGA, "consumption") == "40.0"  # 20 L / 50 km
    assert text_of(backend, OREGA, "win_rate") == "25 %" and text_of(backend, OREGA, "penalty_rate") == "0.25"
    assert text_of(backend, OREGA, "avg_finish") == "2.0"
    assert text_of(backend, "Hyper - Ferrari", "speed") == "-"
    monkeypatch.setitem(cfg.units, "speed_unit", "MPH")
    assert stats_backend.header_label("speed") == "Avg. Speed (mph)"
    assert stats_backend.derived_value("win_rate", {"races": 4, "wins": 1}) == 25  # no starts recorded


def test_columns_hidden_resized_and_reset(backend):
    keys = [column["key"] for column in backend.columns]
    assert "win_rate" not in keys and "speed" in keys  # hidden by default
    backend.setColumnVisible("speed", False)
    assert "speed" not in [column["key"] for column in backend.columns]
    assert "speed" in cfg.user.config["driver_stats_viewer"]["hidden_columns"].split(",")
    assert len(backend.rows.rows[0]["cells"]) == len(backend.columns)  # cells of shown columns
    backend.setColumnWidth("pb", 300.0)
    assert {column["key"]: column["width"] for column in backend.columns}["pb"] == 300
    assert cfg.user.config["driver_stats_viewer"]["column_widths"].startswith("pb:")
    backend.resetColumnWidths()
    width = {column["key"]: column["width"] for column in backend.columns}["pb"]
    assert 0 < width < 300  # from contents


def test_export_csv_text_and_raw(backend, tmp_path):
    filename = tmp_path / "stats.csv"
    assert backend.write_csv(str(filename), decimal_point=",")
    lines = filename.read_text(encoding="utf-8-sig").splitlines()
    header = lines[0].split(";")
    assert header[0] == "Vehicle" and "% Wins" not in header  # hidden column left out
    assert lines[1].split(";")[:2] == ["Hyper - Ferrari", "1:59.000"]
    assert lines[2].split(";")[header.index("% Ref.")] == f"{121.5 / 120.48 * 100:.2f} %".replace(".", ",")
    assert backend.write_csv(str(filename), decimal_point=".", raw=True)
    raw = filename.read_text(encoding="utf-8-sig").splitlines()
    header = raw[0].split(",")
    assert "PB (s)" in header and "Km (m)" in header
    oreca = raw[2].split(",")
    assert oreca[header.index("PB (s)")] == "121.5" and oreca[header.index("Km (m)")] == "50000"
    assert raw[1].split(",")[header.index("Theoretical (s)")] == ""  # unknown: empty


def test_backup_before_edit_and_restore(backend):
    assert not backend.backups
    backend.resetLapTime("Hyper - Ferrari", "pb")
    backups = backend.backups
    assert len(backups) == 1 and backups[0]["date"]
    backend.restoreBackup(backups[0]["name"])
    assert load_stats()[SPA]["Hyper - Ferrari"]["pb"] == 119.0
    backend.undo()  # restore undone
    assert load_stats()[SPA]["Hyper - Ferrari"]["pb"] > 9999
    assert driver_stats.load_stats_backup(cfg.path.config, "../driver.stats") is None


def test_history_records_worth_keeping(tmp_path):
    assert not driver_history.worth_recording(0, 0, 30)  # garage exit
    assert driver_history.worth_recording(0, 0, 60) and driver_history.worth_recording(1, 0, 10)
    folder = f"{tmp_path.as_posix()}/"
    record = driver_history.session_record("T", "Car", 4, MAX_SECONDS, 3, 1, 1000.0, 300.0, 1, 1, time=10.0,
                                           vehicle_class="GT3")
    assert record.best == 0
    driver_history.append_record(folder, record)
    with open(driver_history.history_path(folder), "a", encoding="utf-8") as file:
        file.write('{"broken": \n["not a record"]\n')
    assert driver_history.load_history(folder) == [record]
    assert driver_history.vehicle_classes([record]) == {"Car": "GT3"}
    assert driver_history.best_lap_date([record._replace(best=90.0)], 90.0) == 10.0
    assert driver_history.last_driven([record]) == {("T", "Car"): 10.0}


def test_history_trimmed_when_loaded_over_limit(tmp_path, monkeypatch):
    folder = f"{tmp_path.as_posix()}/"
    driver_history.save_history(folder, [SessionRecord(float(index + 1), "T", "Car") for index in range(10)])
    monkeypatch.setattr(driver_history, "MAX_RECORDS", 4)
    assert [record.time for record in driver_history.load_history(folder)] == [7.0, 8.0, 9.0, 10.0]
    assert len(driver_history.read_records(folder)) == 4  # file rewritten


def test_vehicle_name_classification_grouped_by_recorded_class(window):
    from tinypedal.ui.quick.stats_backend import DriverStatsBackend

    write_stats({SPA: {"Oreca 07 #22": {"pb": 121.5}, "Ferrari 499P #50": {"pb": 119.0}}})
    driver_history.save_history(cfg.path.config, [
        SessionRecord(1.0, SPA, "Oreca 07 #22", vehicle_class="LMP2_ELMS"),
        SessionRecord(2.0, SPA, "Ferrari 499P #50", vehicle_class="Hyper")])
    page = DriverStatsBackend(window)
    assert text_of(page, "Oreca 07 #22", "level") == "Competitive"  # reference by recorded class
    page.selectTrack("")
    assert page.table_header_key[:3] == ["track", "class:Hyper", "class:LMP2_ELMS"]


def test_all_tracks_view_actions_and_letters(backend):
    backend.selectTrack("")
    assert backend.allTracks and not backend.canDelete
    assert backend.table_header_key[:4] == ["track", "class:GT3", "class:Hyper", "class:LMP2_ELMS"]
    hyper = backend.cell(SPA, "class:Hyper")
    assert hyper.text == "1:59.000" and hyper.badge == "A" and hyper.color
    assert text_of(backend, "Monza", "class:Hyper") == "-" and text_of(backend, SPA, "races") == "2"
    assert backend.level_counts[:2] == [1, 1] and backend.unrated == 1  # Monza GT3: no reference
    assert [level["count"] for level in backend.levels][:2] == [1, 1]
    tiles = {tile["title"]: tile for tile in backend.tiles}
    assert tiles["Tracks"]["value"] == "2" and "Spa" in tiles["Tracks"]["detail"]
    assert tiles["Level"]["value"] == "Alien"  # median of Alien & Competitive
    actions = [action["id"] for action in backend.rowActions("Monza", "track")]
    assert actions == ["show", "delete", "laps"]
    backend.runAction("delete", "Monza", "track")
    assert "Monza" not in load_stats() and backend.allTracks
    backend.openRow(SPA)
    assert backend.selected_stats_key == SPA


def test_colorblind_level_colors(backend):
    from tinypedal.ui.quick.stats_backend import COLORBLIND_LEVEL_COLORS

    normal = backend.cell(OREGA, "level").color
    backend.setColorblind(True)
    assert backend.colorblind and cfg.user.config["driver_stats_viewer"]["enable_colorblind_colors"]
    colorblind = backend.cell(OREGA, "level").color
    assert colorblind != normal
    base = QColor(COLORBLIND_LEVEL_COLORS[1])
    assert colorblind in (base.name(), base.darker(135).name())  # darker on light theme


def test_theoretical_best_read_again_when_changed(backend, monkeypatch):
    from tinypedal.ui.quick import stats_backend
    from tinypedal.userfile.sector_best import save_sector_best_file

    save_sector_best_file(cfg.path.sector_best, f"{SPA} - LMP2_ELMS", (0, 0, 0), [40.0] * 3, [40.0] * 3,
                          [40.0, 40.2, 40.3], [40.1, 40.5, 40.9])
    backend.reload_stats()
    assert text_of(backend, OREGA, "theory") == "2:00.500" and text_of(backend, OREGA, "potential") == "1.000"
    assert text_of(backend, "Hyper - Ferrari", "theory") == TEXT_NOLAPTIME
    reads = []
    original = stats_backend.load_theoretical_best
    monkeypatch.setattr(stats_backend, "load_theoretical_best", lambda *args: reads.append(1) or original(*args))
    backend.reload_stats()
    assert not reads  # file unchanged: cached
    save_sector_best_file(cfg.path.sector_best, f"{SPA} - LMP2_ELMS", (0, 0, 0), [40.0] * 3, [40.0] * 3,
                          [39.0, 40.2, 40.3], [40.1, 40.5, 40.9])
    os.utime(f"{cfg.path.sector_best}{SPA} - LMP2_ELMS.sector", (5, 5))
    backend.reload_stats()
    assert reads and text_of(backend, OREGA, "theory") == "1:59.500"


def test_open_lap_viewer_on_personal_best_lap(backend, monkeypatch):
    from tinypedal.ui import tools_view
    from tinypedal.userfile.telemetry_lap import LapFile

    folder = f"{SPA} - LMP2_ELMS"

    class LapBackend:
        tracks = [folder]
        currentTrack = ""
        reference = ""
        entries = [
            SimpleNamespace(file=LapFile("a", "laps/a", True, 121.2), info={"vehicle": "Ligier JS P217"}),
            SimpleNamespace(file=LapFile("b", "laps/b", True, 121.5), info={"vehicle": "Oreca 07 Gibson"}),
            SimpleNamespace(file=LapFile("c", "laps/c", True, 121.9), info={"vehicle": "Oreca 07 Gibson"}),
        ]

        def refresh(self):
            pass

        def setReference(self, path):
            self.reference = path

    viewer = SimpleNamespace(backend=LapBackend())
    opened = []
    monkeypatch.setattr(tools_view, "open_tool", lambda path, parent: opened.append(path) or viewer)
    backend.selectRow(OREGA)
    assert not backend.hasLaps
    os.makedirs(os.path.join(cfg.path.telemetry, folder))
    backend.update_selection()
    assert backend.hasLaps
    backend.openLapViewer()
    assert opened == ["lap_viewer.LapViewer"] and viewer.backend.currentTrack == folder
    assert viewer.backend.reference == "laps/b"  # personal best lap of Oreca, not faster Ligier lap


def test_reload_deferred_while_page_hidden(backend, monkeypatch):
    calls = []
    original = type(backend).reload_stats
    monkeypatch.setattr(type(backend), "reload_stats", lambda self, *args, **kwargs: calls.append(1) or original(self))
    backend.page_hidden()
    stats = load_stats()
    stats[SPA]["Hyper - Ferrari"]["valid"] = 12
    write_stats(stats)
    os.utime(f"{cfg.path.config}driver.stats", (1, 1))
    backend.reload_if_changed()
    assert not calls
    backend.page_shown()
    assert calls and text_of(backend, "Hyper - Ferrari", "valid") == "12"


def test_tracks_list_and_sort_by_last_driven(backend):
    driver_history.save_history(cfg.path.config, HISTORY)
    backend.reload_stats()
    assert [track["key"] for track in backend.tracks] == ["", SPA, "Monza"]
    assert backend.tracks[1]["current"] and backend.tracks[2]["date"] != "-"
    backend.setSortRecent(True)
    assert [track["key"] for track in backend.tracks] == ["", "Monza", SPA]
    backend.selectTrack("")
    assert backend.sortKey == "last" and backend.row_keys()[0] == "Monza"


def test_keyboard_selection(backend):
    assert backend.selectedIndex == 0
    backend.moveSelection(1)
    assert backend.selectedKey == OREGA
    backend.moveSelection(5)
    assert backend.selectedIndex == 1  # last row
    assert driver_history.index_history(HISTORY)[(SPA, OREGA)][0] == HISTORY[0]


def test_reference_cache_time(tmp_path):
    folder = f"{tmp_path.as_posix()}/"
    assert lap_reference.cache_time(folder) == 0
    lap_reference.save_cache(folder, SHEET)
    assert lap_reference.cache_time(folder) == pytest.approx(os.path.getmtime(tmp_path / lap_reference.CACHE_NAME))


EDIT_HISTORY = [SessionRecord(1000.0, SPA, OREGA, 1, 123.0), SessionRecord(2000.0, SPA, OREGA, 1, 121.5),
           SessionRecord(3000.0, SPA, "Hyper - Ferrari", 4, 119.0)]


def lock_history(monkeypatch):
    """History file locked by other program (sync client, antivirus): open raises PermissionError"""
    def locked_open(file, *args, **kwargs):
        if str(file).endswith(driver_history.HISTORY_FILE):
            raise PermissionError(13, "locked", file)
        return open(file, *args, **kwargs)
    monkeypatch.setattr(driver_history, "open", locked_open, raising=False)


def test_undo_with_unreadable_history_keeps_sessions(backend, dialogs, monkeypatch):
    """History unreadable on undo: never rewritten with restored records only (was: all sessions lost)"""
    driver_history.save_history(cfg.path.config, EDIT_HISTORY)
    backend.reload_stats()
    backend.resetLapTime(OREGA, "pb")
    with monkeypatch.context() as patch:
        lock_history(patch)
        backend.undo()
        assert dialogs and backend.canUndo  # undo kept to retry
        assert load_stats()[SPA][OREGA]["pb"] > 9999  # stats not changed either
    assert len(driver_history.read_records(cfg.path.config)) == 3
    with monkeypatch.context() as patch:
        lock_history(patch)
        backend.selectRow("Hyper - Ferrari")
        backend.removeVehicle()  # history unreadable: nothing removed, no undo
        assert "Hyper - Ferrari" in load_stats()[SPA] and len(backend._edits_undo) == 1
    backend.undo()
    assert driver_history.read_records(cfg.path.config) == EDIT_HISTORY
    with pytest.raises(OSError), monkeypatch.context() as patch:
        lock_history(patch)
        driver_history.remove_records(cfg.path.config, lambda record: True)
    assert driver_history.read_records(cfg.path.config) == EDIT_HISTORY


def test_edit_not_saved_leaves_history_and_undo(backend, dialogs, monkeypatch):
    """Stats file not saved (locked, disk full): history unchanged, no undo, warned (was: treated as saved)"""
    from tinypedal.userfile import json_setting

    driver_history.save_history(cfg.path.config, EDIT_HISTORY)
    monkeypatch.setattr(json_setting, "save_json_file", lambda *args, **kwargs: None)  # write lost
    backend.selectRow("Hyper - Ferrari")
    backend.removeVehicle()
    assert "Hyper - Ferrari" in load_stats()[SPA]
    assert driver_history.read_records(cfg.path.config) == EDIT_HISTORY  # history change undone
    assert not backend.canUndo and dialogs


# --- Qt Quick page
@pytest.fixture
def page(dialogs, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.ui.driver_stats_viewer import DriverStatsViewer

    write_stats(STATS)
    lap_reference.save_cache(cfg.path.config, SHEET)
    driver_history.save_history(cfg.path.config, HISTORY)
    monkeypatch.setattr(type(api.read.session), "track_name", lambda self: SPA, raising=False)
    viewer = DriverStatsViewer(None)
    yield viewer
    viewer.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def item_texts(view) -> set:
    texts, stack = set(), [view.rootObject()]
    while stack:
        item = stack.pop()
        text = item.property("text")
        if isinstance(text, str):
            texts.add(text)
        stack.extend(item.childItems())
    return texts


def test_qml_page_loads(page):
    assert not page.view.errors(), [error.toString() for error in page.view.errors()]
    assert page.view.rootObject() is not None
    page.resize(1400, 860)
    page.show()
    page.backend.selectRow(OREGA)
    QCoreApplication.processEvents()
    texts = item_texts(page.view)
    assert "Lap Time Reference" in texts and "Progression" in texts and "2:01.500" in texts
    page.backend.selectTrack("")
    QCoreApplication.processEvents()
    assert "Levels, All Tracks" in item_texts(page.view)


def test_qml_page_translated(dialogs, monkeypatch):
    from tinypedal import i18n
    from tinypedal.api_control import api
    from tinypedal.ui.driver_stats_viewer import DriverStatsViewer

    write_stats(STATS)
    monkeypatch.setattr(type(api.read.session), "track_name", lambda self: SPA, raising=False)
    i18n.set_language("Français")
    try:
        viewer = DriverStatsViewer(None)
        texts = item_texts(viewer.view)
        assert "Voir la carte" in texts and "View Map" not in texts
        viewer.close()
    finally:
        i18n.set_language("English")


def test_qml_page_loads_with_bundled_modules(page, tmp_path):
    """Release build bundles only QML_MODULES: page must load with nothing else on import path"""
    import shutil

    from PySide6.QtCore import QLibraryInfo
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtWidgets import QWidget

    from tinypedal.ui.quick import QML_FOLDER, create_quick_view
    from tinypedal.ui.quick.qml_modules import QML_MODULES

    source = QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath)
    for module in QML_MODULES:
        target = tmp_path / module
        target.mkdir(parents=True, exist_ok=True)
        for entry in os.scandir(os.path.join(source, module)):
            if entry.is_file():
                shutil.copy2(entry.path, target)
    set_source = QQuickWidget.setSource

    def restricted_source(view, url):
        view.engine().setImportPathList([str(tmp_path), QML_FOLDER])
        set_source(view, url)

    QQuickWidget.setSource = restricted_source
    parent = QWidget()
    try:
        view = create_quick_view(parent, "DriverStats.qml", {"backend": page.backend})
        assert not view.errors(), [error.toString() for error in view.errors()]
    finally:
        QQuickWidget.setSource = set_source
        parent.deleteLater()
