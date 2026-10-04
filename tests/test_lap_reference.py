"""Community lap time reference (published Google Sheet) & driver stats viewer comparison"""

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tinypedal.setting import cfg
from tinypedal.userfile import lap_reference
from tinypedal.userfile.lap_reference import (
    csv_url,
    match_track,
    parse_lap_references,
    parse_time,
    vehicle_class_of,
)

HEADER = ",Last updated: 2026.10.02. 10:34 CEST,,,,,,,,,,,,,,,,,,,,,,,,\n" \
         ",Track,Patch,Class avgW,~100%,101%,102%,103%,104%,105%,106%,107%,Fastest car,Laptime,Best/Avg,,,,,,,,,,,\n"
SHEET = HEADER + (
    "SpaLMP2elms,Spa,1.4+,2:00.48,2:01.08,2:02.29,2:03.50,2:04.71,2:05.92,2:07.13,2:08.34,2:09.55,"
    "Oreca ELMS (v1.42),2:00.48,0.00%,2:00.48,LMP2elms,9,100%,100%,100%,100%,100%,100%,100%,100%\n"
    "SpaLMH,Spa,1.4+,1:59.37,1:59.97,2:01.16,2:02.36,2:03.55,2:04.74,2:05.94,2:07.13,2:08.32,"
    "Ferrari 499P (v1.41),1:59.20,-0.14%,1:59.43,LMH,47,100%,100%,100%,100%,100%,100%,100%,100%\n"
    "DaytonaGTE,Daytona,N/A,calculated:,1:43.69,1:44.73,1:45.77,1:46.80,1:47.84,1:48.88,1:49.91,1:50.95,"
    ",0:00.00,,#DIV/0!,GTE,199,0%,0%,0%,0%,0%,0%,0%,0%\n"
    ",,,,,,,,,,,,,,,,,,,,,,,,,\n"
)


def test_parse_sheet():
    table = parse_lap_references(SHEET)
    assert table.updated == "2026.10.02. 10:34 CEST"
    assert set(table.entries) == {("Spa", "LMP2elms"), ("Spa", "LMH"), ("Daytona", "GTE")}
    spa = table.entries[("Spa", "LMP2elms")]
    assert spa.class_best == pytest.approx(120.48) and spa.fastest_car == "Oreca ELMS (v1.42)"
    daytona = table.entries[("Daytona", "GTE")]
    assert daytona.class_best == 0 and daytona.reference == pytest.approx(103.69 / 1.005)  # from ladder
    assert parse_time("1:58.49") == pytest.approx(118.49) and parse_time("calculated:") == 0


def test_levels_and_percent():
    spa = parse_lap_references(SHEET).entries[("Spa", "LMP2elms")]
    assert spa.level(120.9) == 0  # Alien
    assert spa.level(121.5) == 1  # Competitive
    assert spa.level(124.0) == 3 and spa.level(125.9) == 3  # Midpack (103 & 104%)
    assert spa.level(127.0) == 4  # Tail-ender
    assert spa.level(140.0) == 5  # Offline
    assert spa.level(0) == -1
    assert spa.percent(121.5) == pytest.approx(121.5 / 120.48 * 100)


@pytest.mark.parametrize("name, track", [
    ("Circuit de Spa-Francorchamps Endurance", "Spa"),
    ("Fuji Speedway", "Fuji (chicane)"),
    ("Fuji Speedway Classic", "Fuji (classic)"),
    ("Michelin Raceway Road Atlanta", "Road Atlanta"),
    ("WeatherTech Raceway Laguna Seca", "Laguna Seca"),
    ("Autodromo Nazionale Monza Curva Grande", "Monza (curvagrande)"),
    ("Bahrain International Circuit", "Bahrain (wec)"),
    ("Bahrain International Circuit Paddock", "Bahrain (paddock)"),
    ("Circuit de la Sarthe Mulsanne", "Circuit de la Sarthe (straight)"),
    ("Silverstone International", "Silverstone (International)"),
    ("Sebring International Raceway", "Sebring"),
    ("Lusail Short Circuit", "Qatar (short)"),
    ("Circuit Paul Ricard 1A-V2", "Paul Ricard (1A v2)"),
    ("Autódromo José Carlos Pace", "Interlagos"),
    ("Nürburgring", ""),
])
def test_track_matching(name, track):
    assert match_track(name) == track


def test_vehicle_class():
    assert vehicle_class_of("LMP2_ELMS - Oreca") == "LMP2elms"
    assert vehicle_class_of("Hyper - Ferrari") == "LMH"
    assert vehicle_class_of("GT3") == "LMGT3"
    assert vehicle_class_of("LMP2") == "LMP2wec"
    assert vehicle_class_of("Oreca 07") == ""  # vehicle name only: class unknown


def test_csv_url():
    url = csv_url(lap_reference.DEFAULT_SHEET_URL)
    assert url.startswith("https://docs.google.com/spreadsheets/d/e/") and "/pub?" in url
    assert "output=csv" in url and "gid=1766901750" in url
    assert csv_url("https://docs.google.com/spreadsheets/d/abc/edit#gid=5") == \
        "https://docs.google.com/spreadsheets/d/abc/export?format=csv&gid=5"


def test_cache(tmp_path):
    lap_reference.save_cache(f"{tmp_path.as_posix()}/", SHEET)
    text, mtime = lap_reference.load_cache(f"{tmp_path.as_posix()}/")
    assert text == SHEET and mtime > 0
    assert lap_reference.load_cache(f"{tmp_path.as_posix()}/missing/") == ("", 0.0)


# --- Driver stats viewer
@pytest.fixture
def viewer(ui_env, monkeypatch):
    from tinypedal.api_control import api
    from tinypedal.ui import driver_stats_viewer

    monkeypatch.setattr(type(cfg), "save", lambda self, *args, **kwargs: None)
    stats = {
        "Circuit de Spa-Francorchamps Endurance": {
            "LMP2_ELMS - Oreca": {"pb": 121.5, "rb": 124.0, "meters": 50000.0, "seconds": 3600.0,
                                  "valid": 30, "invalid": 2, "races": 2, "wins": 1, "podiums": 2},
            "Hyper - Ferrari": {"pb": 119.0},
            "Oreca 07": {"pb": 125.0},
        },
    }
    with open(f"{cfg.path.config}driver.stats", "w", encoding="utf-8") as file:
        json.dump(stats, file)
    lap_reference.save_cache(cfg.path.config, SHEET)
    monkeypatch.setattr(type(api.read.session), "track_name",
                        lambda self: "Circuit de Spa-Francorchamps Endurance", raising=False)
    page = driver_stats_viewer.DriverStatsViewer(None)
    yield page
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def row_of(page, vehicle):
    table = page.table_stats
    return next(row for row in range(table.rowCount()) if table.item(row, 0).text() == vehicle)


def test_viewer_levels_in_table(viewer):
    table = viewer.table_stats
    header = viewer.table_header_key
    lmp2 = row_of(viewer, "LMP2_ELMS - Oreca")
    assert table.item(lmp2, header.index("level")).text() == "Competitive"
    assert table.item(lmp2, header.index("gap")).text() == f"{121.5 / 120.48 * 100:.2f} %"
    hyper = row_of(viewer, "Hyper - Ferrari")
    assert table.item(hyper, header.index("level")).text() == "Alien"
    unknown = row_of(viewer, "Oreca 07")
    assert table.item(unknown, header.index("level")).text() == "-"  # class unknown


def test_viewer_tiles(viewer):
    assert viewer.tile_best.label_value.text() == "1:59.000"  # best of track: hypercar
    assert viewer.tile_best.label_detail.text() == "Hyper - Ferrari"
    assert viewer.tile_level.label_value.text() == "Alien"
    assert viewer.tile_races.label_value.text() == "2"
    assert viewer.tile_laps.label_value.text() == "30"


def test_viewer_reference_card(viewer):
    viewer.table_stats.selectRow(row_of(viewer, "LMP2_ELMS - Oreca"))
    card = viewer.card_reference
    assert not card.ladder.isHidden() and "Spa" in card.label_subject.text()
    marks = [row[2].text() for row in card.ladder.rows]
    assert "PB" in marks[1] and "Race" in marks[3]  # PB competitive, race best midpack
    assert "Oreca ELMS" in card.label_fastest.text()
    viewer.table_stats.selectRow(row_of(viewer, "Oreca 07"))
    assert card.ladder.isHidden() and "classification" in card.label_empty.text()


def test_viewer_reference_off_and_download(viewer, monkeypatch):
    from tinypedal.ui import driver_stats_viewer

    viewer.action_enable.setChecked(False)
    assert cfg.user.config["driver_stats_viewer"]["enable_lap_reference"] is False
    lmp2 = row_of(viewer, "LMP2_ELMS - Oreca")
    assert viewer.table_stats.item(lmp2, viewer.table_header_key.index("level")).text() == "-"
    # Download (run at once, sheet with Spa LMP2 only)
    only_lmp2 = HEADER + SHEET.splitlines(keepends=True)[2]
    monkeypatch.setattr(lap_reference, "fetch_sheet", lambda url, timeout=15: only_lmp2)

    class Now:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(driver_stats_viewer.threading, "Thread", Now)
    viewer.action_enable.setChecked(True)  # turned on: downloaded again (cache older? forced below)
    viewer.download_reference(force=True)
    QCoreApplication.processEvents()
    assert set(viewer.references.entries) == {("Spa", "LMP2elms")}
    assert lap_reference.load_cache(cfg.path.config)[0] == only_lmp2


def test_viewer_download_failure_keeps_cache(viewer, monkeypatch):
    from tinypedal.ui import driver_stats_viewer

    class Now:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(driver_stats_viewer.threading, "Thread", Now)
    viewer.download_reference(force=True)  # offline (conftest)
    QCoreApplication.processEvents()
    assert viewer.references.entries  # cached reference kept
    assert viewer.reference_error


def test_viewer_change_sheet_url(viewer, monkeypatch):
    from tinypedal.ui import driver_stats_viewer

    dialogs = []
    monkeypatch.setattr(driver_stats_viewer.TextInputDialog, "open", lambda self: dialogs.append(self))
    warnings = []
    monkeypatch.setattr(driver_stats_viewer.QMessageBox, "warning",
                        staticmethod(lambda *args, **kwargs: warnings.append(args)))
    viewer.change_sheet_url()
    dialog = dialogs[0]
    assert not dialog._on_accept("https://example.com/sheet") and warnings
    assert dialog._on_accept("https://docs.google.com/spreadsheets/d/abc/edit#gid=5")
    assert cfg.user.config["driver_stats_viewer"]["lap_reference_sheet_url"].endswith("gid=5")
    dialog.deleteLater()
