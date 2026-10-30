"""UI/UX audit 2026-10-29, sections 5 & 6 (app pages): numbers, lap times, missing values, dates, user units,
written forms (F1-F6), lap record mark, session filters, podium colors & session badge (C1, C5, C6)"""

import os
import re

import pytest
from PySide6.QtCore import QLocale
from PySide6.QtGui import QColor

from neopedal import i18n
from neopedal.process import results_text as rt
from tests.test_race_results import english, race  # noqa: F401  (fixture)
from tests.test_ui_audit_2026_10_29_foundations import named, page  # noqa: F401  (fixture)

QML = os.path.join(os.path.dirname(os.path.dirname(__file__)), "neopedal", "ui", "qml")
MISSING, MINUS = chr(0x2014), chr(0x2212)


def qml(*parts: str) -> str:
    with open(os.path.join(QML, *parts), encoding="utf-8") as file:
        return file.read()


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


# --- F1 / F2 / F3 / F6: shared number, time & missing value texts
def test_numbers_localized_with_typeset_minus(french):
    assert rt.number_text(12.345, 2) == "12,35" and rt.number_text(-2.5, 1) == f"{MINUS}2,5"
    assert rt.number_text(-0.04, 1) == "0,0"  # rounded "-0" shown without sign
    assert rt.signed_text(1.24, 1, " s") == "+1,2 s"
    assert rt.signed_text(-0.345, 3) == f"{MINUS}0,345"
    assert rt.seconds_text(12.34) == "12,3 s" and rt.seconds_text(1.2, sign=True) == "+1,2 s"  # space before "s"


def test_lap_sector_position_and_missing_texts():
    assert rt.MISSING == MISSING
    assert rt.laptime_text(59.123) == "0:59.123" and rt.laptime_text(0) == MISSING  # one lap time form, dot kept
    assert rt.laptime_text(-1, "") == "" and rt.lap_text(91.5) == "1:31.500"
    assert rt.sector_text(32.4564) == "32.456" and rt.sector_text(61.2) == "1:01.200" and rt.sector_text(0) == MISSING
    assert rt.position_text(3, 12) == "P3/12" and rt.position_text(3) == "P3" and rt.position_text(0) == MISSING


def test_lap_viewer_texts_share_the_helpers(french):
    from neopedal.ui import lap_viewer

    assert lap_viewer.format_laptime(9.5) == "0:09.500" and lap_viewer.format_laptime(0) == MISSING
    delta = lap_viewer.CHANNEL_MAP["delta"]
    assert lap_viewer.format_channel_value(delta, -0.25) == f"{MINUS}0,250"  # typeset minus sign (was "-")
    assert lap_viewer.format_value(-1.5) == f"{MINUS}1,50" and lap_viewer.signed(2, 0, " m") == "+2 m"


def test_director_sectors_keep_the_dot_of_lap_times(french):
    from neopedal.ui.quick import director_shared

    assert director_shared.delta_text(-0.2) == f"{MINUS}0,200" and director_shared.lap_text(0) == MISSING
    source = qml("..", "quick", "director_graphics.py")
    assert 'localized(f"{value:.3f}")' not in source and '"sectors": [{"text": sector_text(value)' in source


def test_race_calculator_numbers_localized(french):
    from neopedal.ui.quick import race_results

    assert race_results.DASH == MISSING
    assert race_results.trm_number("1.5 s behind ") == "à 1,5 s derrière "  # message rules, then comma
    tile = race_results.tyre_life(100.0, 4.0, 0.0, 0, 90.0)
    assert tile["laps"] == "25,00" and tile["stints"] == MISSING
    source = qml("..", "quick", "race_results.py")
    raw = [line for line in source.splitlines() if re.search(r"\{[^{}]*:\+?\.[1-3]f\}", line) and "trm_number(" not in line]
    assert raw == []  # every decimal shown through number_text / signed_text


def test_results_lap_gap_and_best_lap_rank(english, ui_env):  # noqa: F811
    from neopedal.ui.quick import results_backend as rb

    assert rb.signed_seconds(-0.5) == f"{MINUS}0.500"  # English: dot
    result = race()
    carl = result._replace(entries=tuple(entry._replace(player=entry.name == "Alice Driver") for entry in result.entries))
    tiles = {tile["label"]: tile for tile in rb.summary_tiles(carl)}
    detail = tiles["Best Lap"]["detail"]
    assert "#" not in detail and (detail == "Fastest" or re.fullmatch(r"Lap rank \d+/\d+", detail)), detail


# --- F4: one date rule
def test_dates_in_language_format(monkeypatch):
    from neopedal.ui.quick import formatting

    stamp = 1_760_025_907.0  # 2025-10-09 18:05 (local)
    monkeypatch.setattr(formatting, "date_locale", lambda: QLocale("en_US"))
    assert formatting.day_month(stamp).startswith("10/") and formatting.date_text(stamp).endswith(
        formatting.clock_minutes(stamp))
    monkeypatch.setattr(formatting, "date_locale", lambda: QLocale("de_DE"))
    assert formatting.day_month_format() == "dd.MM"
    assert formatting.format_date(0) == MISSING
    for name in ("lap_library_panel.py", "session_recorder_backend.py"):  # ISO only for file names
        source = qml("..", "quick", name)
        assert "iso_minutes(" not in source and "date_text(" in source, name


# --- F5: user units
def test_temperature_and_distance_in_user_units(monkeypatch):
    from neopedal.ui.quick import formatting

    units = {"temperature_unit": "Celsius", "odometer_unit": "Kilometer"}
    monkeypatch.setattr(formatting, "cfg", type("Cfg", (), {"units": units})())
    assert formatting.temperature_text(24.4) == "24 °C" and formatting.temperature_text(-999) == MISSING
    assert formatting.odometer_text(5793) == "5.79 km"
    units.update(temperature_unit="Fahrenheit", odometer_unit="Mile")
    assert formatting.temperature_text(20) == "68 °F" and formatting.odometer_text(5793) == "3.60 mi"
    units["odometer_unit"] = "Meter"
    assert formatting.odometer_text(5793) == "5793 m"


# --- C1: one lap record mark
def test_lap_record_mark_shared(page):  # noqa: F811
    view, root, warnings = page('''
    Row {
        TpLapTime { objectName: "session"; text: "1:23.456"; record: "session" }
        TpLapTime { objectName: "personal"; text: "1:24.000"; record: "personal" }
        TpLapTime { objectName: "plain"; text: "1:25.000" }
        TpLapTime { objectName: "tight"; text: "1:25.000"; reserveMark: false }
    }''')
    assert warnings == []
    session, personal, plain = named(root, "session"), named(root, "personal"), named(root, "plain")
    theme = view.engine().rootContext().contextProperty("theme")
    assert QColor(session.property("recordColor")) == QColor(theme.property("purple"))
    assert QColor(personal.property("recordColor")) == QColor(theme.property("gain"))
    assert session.property("marked") and not plain.property("marked")
    assert plain.property("markRoom") > 0 and named(root, "tight").property("markRoom") == 0  # times line up
    component = qml("components", "TpLapTime.qml")
    assert 'text: lapTime.record === "personal" ? "●" : "◆"' in component and "anchors.left: label.right" in component


@pytest.mark.parametrize("path", [("telemetry", "LapList.qml"), ("telemetry", "LapLibraryPanel.qml"),
                                  ("analysis", "ResultsTable.qml"), ("analysis", "ResultsLaps.qml"),
                                  ("director", "StandingsPanel.qml"), ("analysis", "StatsRecentCard.qml"),
                                  ("analysis", "StatsProgressionCard.qml"), ("telemetry", "SessionView.qml")])
def test_record_mark_used_everywhere(path):
    text = qml(*path)
    assert "TpLapTime" in text and "★" not in text and 'i18n.tr("PB")' not in text, path
    assert '" ◆"' not in text and 'text: "◆"' not in text, path


# --- Session filters, podium colors, session badge
def test_session_filters_one_list_one_order():
    from neopedal.ui.quick import results_backend, stats_common

    assert rt.SESSION_FILTER_LABELS == ("All", "Practice", "Qualifying", "Race")
    assert stats_common.SESSION_FILTERS == rt.SESSION_FILTER_LABELS
    assert results_backend.KIND_FILTERS == ("", "Practice", "Qualifying", "Race")
    options = '[i18n.tr("All"), i18n.tr("Practice"), i18n.tr("Qualifying"), i18n.tr("Race")]'
    assert options in qml("analysis", "ResultsSessionList.qml") and options in qml("analysis", "ReplayList.qml")
    from neopedal.ui.quick import replays_common

    assert replays_common.SESSIONS["QUALIFY"] == "Qualifying"


def test_results_session_filter_saved_by_name():
    from neopedal.ui.quick.results_backend import RaceResultsBackend

    assert RaceResultsBackend._kind_index({"session_kind": "Race"}) == 3
    assert RaceResultsBackend._kind_index({"kind": 1}) == 3  # races in the order of 0.27.0
    assert RaceResultsBackend._kind_index({"kind": 3}) == 1  # practice
    assert RaceResultsBackend._kind_index({"kind": "bad", "session_kind": "nothing"}) == 0


def test_podium_and_retired_tones_shared():
    from neopedal.ui.quick import stats_common
    from neopedal.userfile.driver_history import SessionRecord

    assert [rt.place_tone(place, True) for place in (1, 2, 3, 4)] == ["gold", "silver", "bronze", ""]
    assert rt.place_tone(1, False) == "" and rt.place_tone(1, True, retired=True) == "loss"
    record = SessionRecord(1.0, "Spa", "Car", 4, position=2, finish=1)
    assert stats_common.result_tone(record) == "silver"
    assert stats_common.result_tone(record._replace(finish=2)) == "loss"  # DNF: same tone as Results
    assert stats_common.result_tone(record._replace(finish=3)) == "loss"
    for name in ("StatsRecentCard.qml", "StatsProgressionCard.qml"):
        assert 'if (result === "DNF" || result === "DQ") return theme.warning' not in qml("analysis", name)
        assert "resultTone" in qml("analysis", name)


def test_stats_session_badge_and_click():
    from neopedal.ui.quick import stats_common

    assert [stats_common.session_code(index) for index in range(5)] == ["T", "P", "Q", "W", "R"]
    assert stats_common.session_code(9) == ""
    recent = qml("analysis", "StatsRecentCard.qml")
    assert "ResultsBadge {" in recent and "StatsPill {\n                            text: recentItem.modelData.session" not in recent
    # Same main action as Progression (results), track & vehicle in the row menu
    assert "if (linked) backend.openResults(modelData.results)" in recent and "id: sessionMenu" in recent
    assert "backend.openResults(sessionItem.modelData.results)" in qml("analysis", "StatsProgressionCard.qml")


def test_missing_value_placeholder_on_pages():
    tile = qml("components", "TpStatTile.qml")
    assert f'property string value: "{MISSING}"' in tile and f': "{MISSING}"' in tile
    simple = qml("telemetry", "SimpleView.qml")
    dash = chr(0x2013)  # en dash: missing value of in-game overlays only
    assert f'"{dash}"' not in simple and f'"{dash}")' not in qml("telemetry", "LapSummaryBand.qml")


# --- Follow-up: lap list compound badge, Director timing marks, map sector times
def test_lap_rows_carry_their_compound_and_director_marks_after_time():
    from neopedal.ui.quick import lap_backend
    from neopedal.ui.quick.director_timing import TIME_MARKS

    assert "compound" in lap_backend.LAP_ROLES
    lap_list = qml("telemetry", "LapList.qml")
    assert "required property string compound" in lap_list and "TpCompound {" in lap_list
    assert TIME_MARKS == {"fastest": " ◆", "gain": " ●"}  # right of the time, as TpLapTime
    source = qml("..", "quick", "lap_map_marks.py")
    assert "sector_text(reference_times[index]" in source and "format_laptime" not in source
