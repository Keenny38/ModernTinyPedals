"""UI/UX audit 2026-10-29, Broadcast Director (B2, B3, B4, R1, R2, R3): no cut in manual mode, suggestion numbers
kept on their story, desk kept through a missed game answer, on air card of fixed height, keys in tooltips & keys
sheet, readable desk, Esc never closes the page"""

import re
import time

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest

from neopedal import i18n
from neopedal.process import director as dr
from neopedal.ui.quick import qml_path
from tests.test_audit_g_qml_pages import item_named, pump, shown_director
from tests.test_broadcast_director import candidate, car, director_page, poll, race_answers  # noqa: F401
from tests.test_perf_page_state import qml_warnings  # noqa: F401

CARS = (car(1, 1, distance=1040.0), car(2, 2, distance=1000.0), car(3, 3, distance=500.0))


@pytest.fixture
def french():
    i18n.set_language("Français")
    yield
    i18n.set_language("English")


def qml(name: str) -> str:
    with open(qml_path(f"{name}.qml"), encoding="utf-8") as file:
        return file.read()


def stories(backend, *candidates):
    """Suggestions listed from these candidates (score order as given)"""
    backend.candidates = list(candidates)
    backend.update_suggestions()
    return [(row["key"], row["hotkey"]) for row in backend.suggestionRows.rows]


# --- B2: manual mode never cuts to a story
def test_manual_mode_takes_no_suggestion(director_page):  # noqa: F811
    from neopedal.hotkey import command

    page, backend = director_page, director_page.backend
    poll(page, race_answers(100.0, *CARS, focus=3))
    backend.setMode(0)  # manual
    assert backend.modeName == "manual" and backend.candidates
    shot = backend.director.shot
    backend.takeBest()
    assert backend.noticeText.startswith("Manual mode")  # told why (hotkey pressed with the list hidden)
    backend.takeSuggestionAt(0)
    backend.takeSuggestion(backend.candidates[0].key)
    command.hotkey_director_take_best()
    assert backend.director.shot is shot and backend.on_air_slot == 3  # nothing cut
    assert 'backend.modeName !== "manual"; onActivated: backend.takeBest()' in qml("BroadcastDirector")
    backend.setMode(1)  # assisted: Enter takes the best one again
    backend.takeBest()
    assert backend.director.shot is not shot


def test_enter_key_does_nothing_in_manual_mode(director_page):  # noqa: F811
    backend, root = shown_director(director_page, *CARS)
    backend.setMode(0)
    root.forceActiveFocus()
    pump(0.1)
    shot = backend.director.shot
    QTest.keyClick(director_page.view, Qt.Key.Key_Return)
    pump(0.1)
    assert backend.director.shot is shot
    backend.setMode(1)  # assisted: the same key cuts
    pump(0.1)
    QTest.keyClick(director_page.view, Qt.Key.Key_Return)
    pump(0.1)
    assert backend.director.shot is not shot


# --- B3: numbers stay on their story
def test_suggestion_numbers_kept_while_listed_and_reused(director_page):  # noqa: F811
    backend = director_page.backend
    poll(director_page, race_answers(100.0, *CARS, focus=3))
    a, b, c, d = (candidate(slot, dr.BATTLE, score, key) for slot, score, key in
                  ((1, 90, "a"), (2, 80, "b"), (3, 70, "c"), (2, 60, "d")))
    assert stories(backend, a, b, c) == [("a", 1), ("b", 2), ("c", 3)]
    # List reordered live: each story keeps its number
    assert stories(backend, c._replace(score=99), a, b) == [("c", 3), ("a", 1), ("b", 2)]
    # A story gone frees its number, the next new story takes the lowest free one
    assert stories(backend, c, b, d) == [("c", 3), ("b", 2), ("d", 1)]
    best = next(row for row in backend.suggestionRows.rows if row["best"])
    assert best["key"] == "c"  # first by score: the one Enter takes
    backend.takeSuggestionAt(1)  # key 2: story "b", wherever it is listed
    assert backend.director.shot.key == "b"
    stories(backend)  # game in menus or no story: numbers forgotten
    assert backend._story_numbers == {}


def test_rows_kept_in_place_while_aiming(director_page):  # noqa: F811
    backend = director_page.backend
    poll(director_page, race_answers(100.0, *CARS, focus=3))
    a, b = (candidate(slot, dr.BATTLE, score, key) for slot, score, key in ((1, 90, "a"), (2, 80, "b")))
    stories(backend, a, b)
    backend.holdSuggestions(True)  # pointer over the list
    new = candidate(3, dr.OVERTAKE, 99, "c")
    assert [key for key, _ in stories(backend, new, b, a)] == ["a", "b", "c"]  # new one after, others in place
    assert next(row for row in backend.suggestionRows.rows if row["best"])["key"] == "c"
    backend.holdSuggestions(False)  # let go (a second after): score order again
    assert [row["key"] for row in backend.suggestionRows.rows] == ["c", "b", "a"]
    desk = qml("DirectorDesk")
    assert "backend.holdSuggestions(true)" in desk and "interval: 1000" in desk and "text: story.hotkey" in desk


# --- B4: one missed answer keeps the desk
def test_missed_game_answer_keeps_the_desk(qml_warnings, director_page):  # noqa: F811
    backend, root = shown_director(director_page, *CARS)
    rows = backend.suggestionRows.rowCount()
    assert backend.inSession and rows
    poll(director_page, {})  # one answer without the session (game busy, network)
    assert backend.inSession and backend.gameLost and backend.suggestionRows.rowCount() == rows
    assert backend.game.needs_fresh()  # asked again every second, page shown or not
    pump(0.1)
    banner, panels = item_named(root, "lostBanner"), item_named(root, "deskPanels")
    assert banner.isVisible() and not panels.property("enabled") and panels.isVisible()
    assert "Game not responding for 1 s" in banner.property("text")
    poll(director_page, race_answers(101.0, *CARS))  # answering again
    assert backend.inSession and not backend.gameLost
    pump(0.1)
    assert not banner.isVisible() and panels.property("enabled")
    # Session really left: switched after LOST_ANSWERS answers, suggestions emptied
    for _ in range(3):
        poll(director_page, {})
    assert backend.gameState == "offline" and not backend.gameLost and backend.suggestionRows.rowCount() == 0
    assert not qml_warnings, qml_warnings


def test_session_left_after_two_answers_far_apart(director_page):  # noqa: F811
    backend = director_page.backend
    poll(director_page, race_answers(100.0, *CARS, replay=True))
    assert backend.replayActive
    menu = {"/rest/watch/focus": 1}  # game answers something: running, in menus
    poll(director_page, menu)
    assert backend.replayActive and backend.gameLost
    backend._lost_start = time.monotonic() - 2.5  # page hidden: answers 5 s apart
    poll(director_page, menu)
    assert backend.gameState == "menu" and not backend.gameLost
    poll(director_page, {})  # no session shown: told at once
    assert backend.gameState == "offline"


def test_director_off_ends_lost_answers(director_page):  # noqa: F811
    backend = director_page.backend
    poll(director_page, race_answers(100.0, *CARS))
    poll(director_page, {})
    assert backend.gameLost
    backend.setEnabled(False)
    assert not backend.gameLost and backend.gameState == "offline"
    backend.setEnabled(True)


# --- R1, R3: on air card keeps its height, desk readable
def test_on_air_card_height_kept(qml_warnings, director_page):  # noqa: F811
    backend, root = shown_director(director_page, *CARS)
    card, line, radar = (item_named(root, name) for name in ("onAirCard", "airStatusLine", "pitRadar"))
    height = card.height()
    backend.setMode(2)  # automatic: shortest shot bar shown
    pump(0.2)
    assert card.height() == height and line.isVisible()
    backend.toggleLock()  # bar hidden
    pump(0.1)
    assert card.height() == height
    backend.toggleLock()
    assert radar.parentItem() is line  # over the line, not in the card's layout
    desk = qml("DirectorDesk")
    camera = desk[desk.index("component CameraButton"):desk.index("// On air")]
    assert "implicitHeight: theme.controlHeight" in camera and "fontSmall" not in camera
    assert "height: theme.rowTall" in desk
    assert not qml_warnings, qml_warnings


# --- R2: keys in tooltips & keys sheet
def test_hotkeys_shown_in_tooltips_and_keys_sheet(qml_warnings, director_page, monkeypatch):  # noqa: F811
    from neopedal.setting import cfg

    backend, root = shown_director(director_page, *CARS)
    monkeypatch.setitem(cfg.application, "enable_global_hotkey", True)
    shortcuts = dict(cfg.user.shortcuts)
    shortcuts["director_take_best"] = {"bind": "ctrl+b"}
    monkeypatch.setattr(cfg.user, "shortcuts", shortcuts)
    backend.page_shown()  # hotkeys read again when shown
    assert backend.keyLabels["director_take_best"] == "Ctrl+B" and backend.globalHotkeys
    assert len(backend.hotkeyRows) == 12 and backend.hotkeyRows[0]["label"]
    pump(0.1)
    take = item_named(root, "takeBestButton")
    assert take.property("tip").endswith("Hotkey Ctrl+B")
    root.forceActiveFocus()
    QTest.keyClick(director_page.view, Qt.Key.Key_Question, Qt.KeyboardModifier.ShiftModifier)
    pump(0.2)
    sheet = root.findChild(QObject, "keysSheet")
    assert sheet.property("visible")
    sheet.setProperty("visible", False)
    pump(0.2)
    monkeypatch.setitem(cfg.application, "enable_global_hotkey", False)
    backend.refresh_key_labels()
    assert backend.keyLabels["director_take_best"] == "" and not backend.globalHotkeys
    assert not qml_warnings, qml_warnings


# --- Esc & switches
def test_escape_never_closes_the_page(director_page):  # noqa: F811
    backend, root = shown_director(director_page, *CARS)
    root.forceActiveFocus()
    pump(0.1)
    QTest.keyClick(director_page.view, Qt.Key.Key_Escape)
    pump(0.1)
    assert director_page.isVisible() and backend.is_open


def test_switches_follow_backend():
    """TpSwitch bound to a backend value never breaks its binding on click (checkable false, onClicked)"""
    for name in ("BroadcastDirector", "DirectorGraphics", "DirectorSettings", "IncidentPanel", "DirectorDesk",
                 "DirectorKeys"):
        assert not re.search(r"onToggled", qml(name)), name


# --- French: header fits the page minimum width
def test_header_fits_minimum_width_in_french(french, director_page):  # noqa: F811
    size = director_page.page_minimum_size()
    _, root = shown_director(director_page, *CARS)
    director_page.resize(size.width(), size.height())
    pump(0.3)
    header = item_named(root, "headerRow")
    fixed = sum(child.implicitWidth() for child in header.childItems()
                if child.isVisible() and "QQuickText" not in child.metaObject().className())
    assert fixed <= header.width()  # only the session text (elided) gives room
    assert item_named(root, "keysButton").isVisible()
