"""Results & replays page: sessions of results files & replays of the game in one page, each linked to the other"""

import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from neopedal.process import results_file as rf
from tests.test_game_info import GAME_ANSWERS, FakeGame, wait_commands, wait_requests
from tests.test_race_results import PRACTICE_XML, RACE_NAME, RACE_XML, wait_until, write_results

REPLAY = "24 Heures du Mans R1 1"


@pytest.fixture
def page(ui_env, tmp_path, monkeypatch):
    from neopedal.ui import game_rest, race_results_viewer
    from neopedal.ui._common import BaseDialog

    root = tmp_path / "Le Mans Ultimate"
    folder = root / "UserData" / "Log" / "Results"
    write_results(folder, {RACE_NAME: RACE_XML, "2026_09_21_18_00_00-10P1.xml": PRACTICE_XML.format(laps=5)})
    (root / "UserData" / "Replays").mkdir(parents=True)
    replay = root / "UserData" / "Replays" / f"{REPLAY}.Vcr"
    replay.write_bytes(b"vcr")
    written = os.path.getmtime(folder / RACE_NAME)
    os.utime(replay, (written + 60, written + 60))
    monkeypatch.setattr(rf, "find_results_folders", lambda libraries=None: {"LMU": str(folder)})
    game = FakeGame()
    game.answers = {**GAME_ANSWERS, "/rest/watch/replays": [
        {"id": 0, "replayName": "Algarve P1 1", "size": 1, "timestamp": 1791165314, "metadata": {}},
        {"id": 1, "replayName": REPLAY, "size": 1, "timestamp": 1791169000, "metadata": {"session": "RACE"}},
    ]}
    monkeypatch.setattr(BaseDialog, "confirm_operation", lambda self, *args, **kwargs: True)
    monkeypatch.setattr(game_rest, "GameConnection", game.connection)
    dialog = race_results_viewer.RaceResultsViewer(None)
    dialog.game = game
    dialog.resize(1300, 800)
    yield dialog, folder
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_sessions_and_replays_linked(page):
    from neopedal.ui.quick.results_backend import REPLAY_TAB

    dialog, folder = page
    results, replays = dialog.backend, dialog.replays
    dialog.show()
    assert wait_until(lambda: results.loaded_once and results.hasSession)
    assert not dialog.view.errors()
    assert replays.results_links == {REPLAY: str(folder / RACE_NAME)}
    assert not replays._shown  # sessions list & classification: game not asked
    # Replays list: game asked, replay picked shows results of its session
    results.setListMode(1)
    assert replays._shown
    wait_requests(replays.request_replays, replays.request_state)
    rows = {row["key"]: row for row in replays.replayRows.rows}
    assert rows[REPLAY]["hasResults"] and not rows["Algarve P1 1"]["hasResults"]
    results.select(str(folder / "2026_09_21_18_00_00-10P1.xml"))
    assert wait_until(lambda: results.selectedKey.endswith("10P1.xml"))
    replays.selectReplay(REPLAY)
    assert wait_until(lambda: results.selectedKey.endswith(RACE_NAME))
    # Sessions list: session picked picks its replay
    results.setListMode(0)
    replays.selectReplay("Algarve P1 1")
    results.select(str(folder / "2026_09_21_18_00_00-10P1.xml"))
    assert wait_until(lambda: results.selectedKey.endswith("10P1.xml"))
    results.select(str(folder / RACE_NAME))
    assert wait_until(lambda: results.selectedKey.endswith(RACE_NAME) and results.sessionHeader.get("replay") == REPLAY)
    assert replays.selectedReplay == REPLAY
    # Watch replay of session: replay tab shown (game asked), replay opened in game
    results.setTab(0)
    dialog.game.sent.clear()
    results.watchReplay()
    assert results.tabIndex == REPLAY_TAB and replays._shown
    wait_commands(replays)
    assert ("GET", "/rest/watch/play/1") in dialog.game.sent
    assert not dialog.view.errors()


def test_former_replays_path_opens_replays_list(page):
    from neopedal.ui.tools_view import RENAMED_TOOLS

    dialog, _ = page
    assert RENAMED_TOOLS["game_replays.GameReplays"] == "race_results_viewer.RaceResultsViewer"
    dialog.show_replays()
    assert dialog.backend.listMode == 1


def test_page_hidden_stops_game_requests(page):
    from neopedal.ui.quick.results_backend import REPLAY_TAB

    dialog, _ = page
    dialog.backend.setTab(REPLAY_TAB)
    dialog.show()
    assert dialog.replays._shown
    dialog.hide()
    assert not dialog.replays._shown and not dialog.replays._timer.isActive()
