"""Lap viewer lap list: sessions shown by kind (practice, qualifying, race), sessions & laps order, saved"""

import pytest

from neopedal.setting import cfg
from neopedal.ui.lap_viewer import load_viewer_setting
from neopedal.ui.quick.lap_library import session_kind
from tests.test_lap_viewer_fix_list import BASE, open_page, save


@pytest.fixture
def typed(ui_env):
    """Race (newest), qualifying, practice (oldest, fastest session); race laps 3 faster than 1"""
    race = [save(number, 63.0 - number, BASE + 7200 + number * 70, BASE + 7200, session="Race") for number in (1, 2, 3)]
    qualify = [save(number, 61.0 + number, BASE + 3600 + number * 70, BASE + 3600, session="Qualify")
               for number in (1, 2)]
    practice = [save(number, 59.0 + number, BASE + number * 70, BASE, session="Practice") for number in (1, 2)]
    return {"race": race, "qualify": qualify, "practice": practice}


@pytest.fixture
def page(typed):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    backend = open_page(parent)
    yield backend
    backend.release()
    parent.deleteLater()


def session_titles(page) -> list[str]:
    return [row["title"].split()[0] for row in page.lap_model.all_rows if row["kind"] == "session"]


def test_session_kind():
    assert [session_kind(name) for name in ("Race", "Qualify", "Practice", "Test day", "Warmup", "")] == [
        "race", "qualify", "practice", "practice", "practice", "practice"]


def test_sessions_filtered_by_kind(page, typed):
    assert session_titles(page) == ["Race", "Qualify", "Practice"]
    assert page.sessionCounts == {"practice": 1, "qualify": 1, "race": 1}
    shown = page.checked | {page.reference_key}  # newest lap shown on opening: listed anyway
    page.setSessionShown("race", False)
    page.setSessionShown("practice", False)
    assert page.sessionKinds == ["qualify"]
    assert {row["path"] for row in page.lap_rows()} - shown == set(typed["qualify"])
    assert load_viewer_setting(cfg.path.telemetry)["lap_session_kinds"] == ["qualify"]
    page.setSessionShown("qualify", False)
    assert {row["path"] for row in page.lap_rows()} <= shown and page.noMatch  # hint: show all sessions
    page.showAllSessions()
    assert session_titles(page) == ["Race", "Qualify", "Practice"] and not page.noMatch


def test_checked_lap_stays_listed(page, typed):
    page.setLapChecked(typed["race"][0], True)
    page.setSessionShown("race", False)
    assert typed["race"][0] in {row["path"] for row in page.lap_rows()}


def test_sessions_and_laps_order(page, typed):
    page.setSessionOrder("oldest")
    assert session_titles(page) == ["Practice", "Qualify", "Race"]
    page.setSessionOrder("fastest")
    assert session_titles(page) == ["Race", "Practice", "Qualify"]  # best laps 60.0, 60.0 (newest first), 62.0
    page.setSessionOrder("newest")
    page.setLapOrder("fastest")
    race = [row["path"] for row in page.lap_rows() if row["path"] in typed["race"]]
    assert race == typed["race"][::-1]  # 60.0, 61.0, 62.0
    setting = load_viewer_setting(cfg.path.telemetry)
    assert setting["lap_session_order"] == "newest" and setting["lap_order"] == "fastest"
    page.setLapOrder("bogus")
    assert page.lapOrder == "fastest"


def test_view_loaded_again(page, typed):
    from PySide6.QtWidgets import QWidget

    page.setSessionShown("practice", False)
    page.setSessionOrder("oldest")
    parent = QWidget()
    again = open_page(parent)
    try:
        assert again.sessionKinds == ["qualify", "race"] and again.sessionOrder == "oldest"
        assert session_titles(again) == ["Qualify", "Race"]
    finally:
        again.release()
        parent.deleteLater()
